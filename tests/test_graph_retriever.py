from graph_retriever import GraphRetriever
from retrieval_modes import RetrievalRequest


class FakeRecord(dict):
    def data(self):
        return dict(self)


class FakeSession:
    def __init__(self, amendment=True, repeal=False, guideline=False):
        self.calls = []
        self._amendment = amendment
        self._repeal = repeal
        self._guideline = guideline

    def run(self, query, **params):
        self.calls.append((query, params))
        if "RETURN d" in query:
            return [FakeRecord({"d": {"id": "doc:1", "doc_id": "1", "title": "Doc 1"}})]
        if "RETURN source" in query and self._amendment:
            return [
                FakeRecord(
                    {
                        "source": {"id": "doc:2", "doc_id": "2", "title": "Doc 2"},
                        "target": {"id": "doc:1", "doc_id": "1", "title": "Doc 1"},
                        "type": "AMENDS",
                        "raw_label": "Van ban sua doi",
                    }
                )
            ]
        if "RETURN source" in query and self._repeal:
            return [
                FakeRecord(
                    {
                        "source": {"id": "doc:3", "doc_id": "3", "title": "Doc 3"},
                        "target": {"id": "doc:1", "doc_id": "1", "title": "Doc 1"},
                        "type": "REPEALS",
                        "raw_label": "Van ban het hieu luc",
                    }
                )
            ]
        if "RETURN source" in query and self._guideline:
            return [
                FakeRecord(
                    {
                        "source": {"id": "doc:4", "doc_id": "4", "title": "Doc 4"},
                        "target": {"id": "doc:1", "doc_id": "1", "title": "Doc 1"},
                        "type": "GUIDELINES",
                        "raw_label": "Van ban HD, QD chi tiet",
                    }
                )
            ]
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeDriver:
    def __init__(self, amendment=True, repeal=False, guideline=False):
        self.session_obj = FakeSession(
            amendment=amendment, repeal=repeal, guideline=guideline
        )

    def session(self, database=None):
        return self.session_obj


# ---------------------------------------------------------------------------
# Plan-specified tests
# ---------------------------------------------------------------------------


def test_graph_retriever_returns_neighbors_with_raw_label() -> None:
    retriever = GraphRetriever(driver=FakeDriver(), database="neo4j")

    context = retriever.get_document_neighbors("1", relations=["AMENDS"], depth=1)

    payload = context.to_dict()
    assert payload["center"]["properties"]["doc_id"] == "1"
    assert payload["edges"][0]["type"] == "AMENDS"
    assert payload["edges"][0]["raw_label"] == "Van ban sua doi"


def test_graph_retriever_protocol_retrieve_uses_retrieval_hit_doc_id() -> None:
    retriever = GraphRetriever(driver=FakeDriver(), database="neo4j")

    context = retriever.retrieve(
        query="Van ban nao sua doi?",
        retrieval_hits=[{"doc_id": "1"}],
        max_hops=1,
    )

    assert context.query_intent == "amendment"


# ---------------------------------------------------------------------------
# Repeal relationship
# ---------------------------------------------------------------------------


def test_graph_retriever_returns_repeal_relationship() -> None:
    retriever = GraphRetriever(
        driver=FakeDriver(amendment=False, repeal=True), database="neo4j"
    )

    context = retriever.get_document_neighbors("1", relations=["REPEALS"], depth=1)

    payload = context.to_dict()
    assert payload["center"]["properties"]["doc_id"] == "1"
    assert payload["edges"][0]["type"] == "REPEALS"
    assert payload["edges"][0]["raw_label"] == "Van ban het hieu luc"


# ---------------------------------------------------------------------------
# Guideline relationship
# ---------------------------------------------------------------------------


def test_graph_retriever_returns_guideline_relationship() -> None:
    retriever = GraphRetriever(
        driver=FakeDriver(amendment=False, guideline=True), database="neo4j"
    )

    context = retriever.get_document_neighbors("1", relations=["GUIDELINES"], depth=1)

    payload = context.to_dict()
    assert payload["edges"][0]["type"] == "GUIDELINES"
    assert payload["edges"][0]["raw_label"] == "Van ban HD, QD chi tiet"


# ---------------------------------------------------------------------------
# Version chain (AMENDS + REPEALS at depth 2)
# ---------------------------------------------------------------------------


def test_graph_retriever_returns_all_relations_when_no_filter() -> None:
    driver = FakeDriver(amendment=True, repeal=True)
    driver.session_obj._guideline = False
    retriever = GraphRetriever(driver=driver, database="neo4j")

    context = retriever.get_document_neighbors("1", depth=1)

    assert len(context.edges) >= 1
    assert context.center is not None


# ---------------------------------------------------------------------------
# Edge direction correctness
# ---------------------------------------------------------------------------


def test_graph_retriever_edge_direction_out_when_source_is_center() -> None:
    retriever = GraphRetriever(driver=FakeDriver(), database="neo4j")

    context = retriever.get_document_neighbors("1", relations=["AMENDS"], depth=1)

    # Center is doc:1, source is doc:2 (neighbor), target is doc:1 (center)
    # Since source.id != center_id (doc:2 != doc:1), direction = "in"
    payload = context.to_dict()
    assert payload["edges"][0]["direction"] == "in"


# ---------------------------------------------------------------------------
# Empty query result  (no matching document)
# ---------------------------------------------------------------------------


def test_graph_retriever_empty_result_when_no_center_found() -> None:
    class EmptySession:
        def run(self, query, **params):
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class EmptyDriver:
        def session(self, database=None):
            return EmptySession()

    retriever = GraphRetriever(driver=EmptyDriver(), database="neo4j")

    context = retriever.get_document_neighbors("999", depth=1)

    assert context.center is None
    assert context.nodes == []
    assert context.edges == []


# ---------------------------------------------------------------------------
# Retrieve with no retrieval hits (no doc_id)
# ---------------------------------------------------------------------------


def test_graph_retriever_retrieve_returns_empty_when_no_hits() -> None:
    retriever = GraphRetriever(driver=FakeDriver(), database="neo4j")

    context = retriever.retrieve(
        query="Van ban ve luat dat dai?",
        retrieval_hits=[],
        max_hops=1,
    )

    assert context.center is None
    assert context.query_intent == "general"


# ---------------------------------------------------------------------------
# GraphContext serialization round-trip
# ---------------------------------------------------------------------------


def test_graph_retriever_context_serializes_to_dict() -> None:
    retriever = GraphRetriever(driver=FakeDriver(), database="neo4j")

    context = retriever.get_document_neighbors("1", relations=["AMENDS"], depth=1)

    payload = context.to_dict()
    assert "center" in payload
    assert "nodes" in payload
    assert "edges" in payload
    assert "related_chunks" in payload
    assert "query_intent" in payload
    assert payload["center"]["properties"]["doc_id"] == "1"
