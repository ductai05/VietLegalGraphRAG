"""Dedicated module for resolving document conflicts in legal contexts.

Handles:
1. Detecting expired/repealed documents in retrieval results
2. Finding replacement documents via graph edges (REPLACED_BY / REPEALS)
3. Resolving version overlap (keeping only the latest version)
4. Annotating resolution metadata on AnswerContext objects
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from contracts import AnswerContext, GraphContext

# Effect-status values that indicate a document is no longer in force.
# Values are case-folded for comparison.
EXPIRED_STATUSES = frozenset({
    "hết hiệu lực",
    "het hieu luc",
    "hết hiệu lực một phần",
    "het hieu luc mot phan",
    "ngưng hiệu lực",
    "ngung hieu luc",
})

# Edge types that indicate a replacement relationship.
REPLACEMENT_EDGE_TYPES = frozenset({"REPLACED_BY", "REPEALS"})


ResolutionAction = Literal[
    "kept",              # Document is still valid, no change
    "replaced",          # Document was expired and a replacement was found
    "superseded",        # A newer version of the same document exists
    "expired_warning",   # Document is expired but no replacement found
]


@dataclass
class ResolutionInfo:
    """Metadata describing why a particular context was kept or modified."""
    action: ResolutionAction
    reason: str
    original_doc_id: str | None = None
    replacement_doc_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolvedResult:
    """Output of the document resolution process."""
    contexts: list[AnswerContext] = field(default_factory=list)
    resolutions: list[ResolutionInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contexts": [ctx.to_dict() for ctx in self.contexts],
            "resolutions": [r.to_dict() for r in self.resolutions],
            "warnings": self.warnings,
        }


class DocumentResolver:
    """Resolves document conflicts, expirations, and version overlaps.

    This resolver sits between the raw retrieval/graph results and the
    final context that is sent to the answer service.  It ensures that:

    - Expired documents are flagged and, when possible, replaced by
      their successors from the knowledge graph.
    - When multiple versions of the same document appear in the context,
      only the most recent version is kept.
    - All resolution decisions are annotated on the AnswerContext so the
      answer service can reference them.
    """

    def __init__(
        self,
        version_chain_fn: Any | None = None,
    ) -> None:
        # Optional callable: (doc_id: str) -> list[dict] returning
        # the chronological version chain for a document.
        self.version_chain_fn = version_chain_fn

    def resolve(
        self,
        contexts: list[AnswerContext],
        graph_context: GraphContext | None,
    ) -> ResolvedResult:
        """Main entry point: resolve conflicts in *contexts*.

        Returns a ``ResolvedResult`` with cleaned contexts, resolution
        metadata, and any warnings produced during resolution.
        """
        if not contexts:
            return ResolvedResult()

        result = ResolvedResult()

        # Phase 1: detect expired documents and find replacements
        contexts = self._resolve_expired(contexts, graph_context, result)

        # Phase 2: resolve version overlaps (same document, multiple versions)
        contexts = self._resolve_version_overlap(contexts, result)

        result.contexts = contexts
        return result

    # ------------------------------------------------------------------
    # Phase 1: Expired document resolution
    # ------------------------------------------------------------------

    def _resolve_expired(
        self,
        contexts: list[AnswerContext],
        graph_context: GraphContext | None,
        result: ResolvedResult,
    ) -> list[AnswerContext]:
        """Flag expired documents and inject replacements when available."""
        replacement_map = self._build_replacement_map(graph_context)
        resolved: list[AnswerContext] = []
        seen_doc_ids: set[str] = set()

        for ctx in contexts:
            if not self._is_expired(ctx):
                # Document is still valid.
                ctx.resolution = ResolutionInfo(
                    action="kept",
                    reason="Tài liệu còn hiệu lực",
                ).to_dict()
                resolved.append(ctx)
                if ctx.doc_id:
                    seen_doc_ids.add(ctx.doc_id)
                continue

            # Document is expired — check for replacement.
            replacement_doc_id = replacement_map.get(ctx.doc_id)

            if replacement_doc_id and replacement_doc_id not in seen_doc_ids:
                # Keep the expired context with a warning annotation,
                # AND inject the replacement context (if available from
                # graph_context related_chunks).
                ctx.resolution = ResolutionInfo(
                    action="replaced",
                    reason=(
                        f"Tài liệu đã hết hiệu lực. "
                        f"Tài liệu thay thế: {replacement_doc_id}"
                    ),
                    original_doc_id=ctx.doc_id,
                    replacement_doc_id=replacement_doc_id,
                ).to_dict()
                resolved.append(ctx)
                seen_doc_ids.add(ctx.doc_id)

                replacement_ctx = self._find_replacement_context(
                    replacement_doc_id, graph_context,
                )
                if replacement_ctx is not None and replacement_ctx.doc_id not in seen_doc_ids:
                    replacement_ctx.resolution = ResolutionInfo(
                        action="kept",
                        reason=(
                            f"Tài liệu thay thế cho {ctx.doc_id} "
                            f"(đã hết hiệu lực)"
                        ),
                        original_doc_id=ctx.doc_id,
                    ).to_dict()
                    resolved.append(replacement_ctx)
                    seen_doc_ids.add(replacement_ctx.doc_id)
                    result.resolutions.append(ResolutionInfo(
                        action="replaced",
                        reason=f"{ctx.doc_id} -> {replacement_doc_id}",
                        original_doc_id=ctx.doc_id,
                        replacement_doc_id=replacement_doc_id,
                    ))
            else:
                # No replacement found — keep with warning.
                ctx.resolution = ResolutionInfo(
                    action="expired_warning",
                    reason="Tài liệu đã hết hiệu lực, không tìm thấy tài liệu thay thế",
                    original_doc_id=ctx.doc_id,
                ).to_dict()
                resolved.append(ctx)
                if ctx.doc_id:
                    seen_doc_ids.add(ctx.doc_id)
                result.warnings.append(
                    f"document.expired:{ctx.doc_id}"
                )
                result.resolutions.append(ResolutionInfo(
                    action="expired_warning",
                    reason=f"Tài liệu {ctx.doc_id} hết hiệu lực, không có thay thế",
                    original_doc_id=ctx.doc_id,
                ))

        return resolved

    # ------------------------------------------------------------------
    # Phase 2: Version overlap resolution
    # ------------------------------------------------------------------

    def _resolve_version_overlap(
        self,
        contexts: list[AnswerContext],
        result: ResolvedResult,
    ) -> list[AnswerContext]:
        """When multiple versions of the same document appear, keep the newest."""
        if self.version_chain_fn is None:
            return contexts

        # Group contexts by document_number (via citation prefix).
        doc_groups: dict[str, list[AnswerContext]] = {}
        ungrouped: list[AnswerContext] = []
        for ctx in contexts:
            doc_number = self._extract_document_number(ctx)
            if doc_number:
                doc_groups.setdefault(doc_number, []).append(ctx)
            else:
                ungrouped.append(ctx)

        resolved: list[AnswerContext] = list(ungrouped)
        for doc_number, group in doc_groups.items():
            if len(group) <= 1:
                resolved.extend(group)
                continue

            # Use version chain to determine order if possible.
            try:
                chain = self.version_chain_fn(group[0].doc_id)
            except Exception:
                chain = []

            if not chain:
                resolved.extend(group)
                continue

            # Build doc_id -> version_order map.
            order_map = {
                entry.get("doc_id", ""): entry.get("version_order", 0)
                for entry in chain
            }

            # Sort by version_order descending, keep the newest.
            group.sort(
                key=lambda ctx: order_map.get(ctx.doc_id, -1),
                reverse=True,
            )
            newest = group[0]
            newest.resolution = ResolutionInfo(
                action="kept",
                reason=f"Phiên bản mới nhất của {doc_number}",
            ).to_dict()
            resolved.append(newest)

            for older in group[1:]:
                older.resolution = ResolutionInfo(
                    action="superseded",
                    reason=f"Đã bị thay thế bởi phiên bản mới hơn ({newest.doc_id})",
                    replacement_doc_id=newest.doc_id,
                    original_doc_id=older.doc_id,
                ).to_dict()
                result.resolutions.append(ResolutionInfo(
                    action="superseded",
                    reason=f"{older.doc_id} -> {newest.doc_id}",
                    original_doc_id=older.doc_id,
                    replacement_doc_id=newest.doc_id,
                ))

        return resolved

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _is_expired(ctx: AnswerContext) -> bool:
        """Check if a context's source document is expired."""
        status = (ctx.effect_status or "").strip().casefold()
        return status in EXPIRED_STATUSES

    @staticmethod
    def _build_replacement_map(
        graph_context: GraphContext | None,
    ) -> dict[str, str]:
        """Build a mapping from expired doc_id -> replacement doc_id.

        Scans graph edges for REPLACED_BY and REPEALS relationships.
        """
        if graph_context is None:
            return {}

        replacements: dict[str, str] = {}
        for edge in graph_context.edges:
            if edge.type not in REPLACEMENT_EDGE_TYPES:
                continue
            # For REPLACED_BY: source -> target means source is replaced by target.
            # For REPEALS: source repeals target, so target is expired.
            if edge.type == "REPLACED_BY":
                replacements[edge.source] = edge.target
            elif edge.type == "REPEALS":
                replacements[edge.target] = edge.source
        return replacements

    @staticmethod
    def _find_replacement_context(
        replacement_doc_id: str,
        graph_context: GraphContext | None,
    ) -> AnswerContext | None:
        """Find an AnswerContext for the replacement document in graph chunks."""
        if graph_context is None:
            return None

        for chunk in graph_context.related_chunks:
            if chunk.doc_id == replacement_doc_id:
                return chunk

        # If no chunk found, try to build a minimal context from graph nodes.
        for node in graph_context.nodes:
            node_doc_id = node.properties.get("doc_id", "")
            node_id = node.properties.get("id", "")
            if node_doc_id == replacement_doc_id or node_id == f"doc:{replacement_doc_id}":
                return AnswerContext(
                    source="graph",
                    chunk_id=None,
                    doc_id=replacement_doc_id,
                    title=str(node.properties.get("title", "")),
                    text="",
                    citation=str(node.properties.get("document_number", "")),
                    effect_status=str(node.properties.get("effect_status", "")),
                )

        return None

    @staticmethod
    def _extract_document_number(ctx: AnswerContext) -> str:
        """Extract document number from a context's citation string.

        Citation format: "document_number | title | section_path | chunk_id: ..."
        """
        if not ctx.citation:
            return ""
        parts = ctx.citation.split("|")
        if parts:
            return parts[0].strip()
        return ""
