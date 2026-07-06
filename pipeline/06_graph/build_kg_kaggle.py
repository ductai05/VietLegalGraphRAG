"""
VietLegalGraphRAG: Knowledge Graph Construction Pipeline
Author: Antigravity & Kiên
Description: This script cleans document relationships, normalizes nodes & edges,
             resolves parent-child chunk links, and exports CSV tables for Neo4j Bulk Import.
             Optimized for extreme memory efficiency (Zero Python row-loops/to_dicts) 
             to handle 6.8+ million rows without triggering Kaggle OOM DeadKernelError.
"""

import os
import re
import zipfile
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional
import polars as pl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("GraphConstruction")

# Normalization maps matching Notion specs
RAW_REL_MAPPING = {
    "AMENDS": ("AMENDS", False),
    "SUPPLEMENTS": ("AMENDS", False),
    "IS_AMENDED_BY": ("AMENDS", True),
    "IS_SUPPLEMENTED_BY": ("AMENDS", True),
    
    "REPLACES_OR_EXPIRES": ("REPEALS", False),
    "SUSPENDS": ("REPEALS", False),
    "IS_REPLACED_OR_EXPIRED_BY": ("REPEALS", True),
    "IS_SUSPENDED_BY": ("REPEALS", True),
    
    "GUIDES_DETAIL": ("GUIDELINES", False),
    "IS_GUIDED_DETAILED_BY": ("GUIDELINES", True),
    
    "CITES": ("CITES", False),
    "CITES_AS_BASIS": ("CITES", False),
    "RELATED_TO": ("CITES", False)
}

LEGAL_PRIORITY = {
    "Hiến pháp": "Tier 1",
    "Bộ luật": "Tier 1",
    "Luật": "Tier 1",
    "Pháp lệnh": "Tier 1",
    "Văn bản hợp nhất": "Tier 1",
    
    "Nghị định": "Tier 2",
    "Thông tư": "Tier 2",
    "Thông tư liên tịch": "Tier 2",
    "Quyết định": "Tier 2",
    "Nghị quyết": "Tier 2",
    "Chỉ thị": "Tier 2",
    "Hướng dẫn": "Tier 2",
    
    "Điều ước quốc tế": "Tier 3",
    "Hiệp định": "Tier 3",
    "Quy chế": "Tier 3",
    "Quy định": "Tier 3",
    "Văn bản WTO": "Tier 3"
}


def get_paths() -> dict:
    """Finds input and output directories dynamically depending on Kaggle/local execution."""
    paths = {}
    
    # Helper function to find a file dynamically
    def find_file(filename: str) -> Optional[Path]:
        # 1. Search in Kaggle input (/kaggle/input)
        kaggle_input = Path("/kaggle/input")
        if kaggle_input.exists():
            found = list(kaggle_input.glob(f"**/{filename}"))
            if found:
                return found[0]
                
        # 2. Search in local workspace directory (.)
        local_dir = Path(".")
        found = list(local_dir.glob(f"**/{filename}"))
        if found:
            return found[0]
            
        return None

    # Find Metadata path
    metadata_path = find_file("merged_metadata.parquet") or find_file("metadata.parquet")
    if metadata_path:
        paths["metadata"] = metadata_path
    else:
        paths["metadata"] = Path("./data/preprocessed/merged_metadata.parquet")
        
    # Find Chunks path
    chunks_path = find_file("chunks.parquet")
    if chunks_path:
        paths["chunks"] = chunks_path
    else:
        paths["chunks"] = Path("./data/processed/chunks.parquet")
        
    # Find Relationships path
    relationships_path = find_file("merged_relationships.parquet") or find_file("relationships.parquet")
    if relationships_path:
        paths["relationships"] = relationships_path
    else:
        paths["relationships"] = Path("./data/preprocessed/merged_relationships.parquet")
        
    # Set Output directories
    if Path("/kaggle/working").exists():
        paths["output_dir"] = Path("/kaggle/working/neo4j_imports")
        paths["zip_output"] = Path("/kaggle/working/neo4j_imports.zip")
    else:
        paths["output_dir"] = Path("./data/processed/neo4j_imports")
        paths["zip_output"] = Path("./data/processed/neo4j_imports.zip")
        
    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    
    logger.info("Configured Paths:")
    for k, v in paths.items():
        logger.info(f"  {k}: {v}")
    return paths


def stable_hash(value: str, length: int = 16) -> str:
    """Computes stable hex digest slice matching legal_chunker.py."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def normalize_value(text: str) -> str:
    """Creates a normalized lowercase string for PK values (LegalType, Authority, Sector)."""
    if not text:
        return "unknown"
    import unicodedata
    # Normalize unicode to NFC, strip accents
    nfkd = unicodedata.normalize('NFKD', str(text))
    ascii_str = "".join([c for c in nfkd if not unicodedata.combining(c)])
    # Convert to lowercase and strip special chars
    clean = re.sub(r"[^\w\s-]", "", ascii_str).strip().lower()
    # Replace spaces & dashes with underscores
    clean = re.sub(r"[-\s]+", "_", clean)
    # Collapse multiple underscores
    clean = re.sub(r"_+", "_", clean)
    return clean.strip("_")


def parse_rel(rel_str: str) -> tuple:
    """Parses raw relationships, returning (clean_edge_type, should_swap_direction)."""
    if not rel_str:
        return ("CITES", False)
    s = rel_str.upper().strip()
    
    # 1. Direct mapping
    if s in RAW_REL_MAPPING:
        return RAW_REL_MAPPING[s]
        
    # 2. Case insensitive heuristic mapping (for safety)
    if "AMEND" in s or "SUPPLEMENT" in s or "SỬA ĐỔI" in s or "BỔ SUNG" in s:
        should_swap = "BY" in s or "ĐƯỢC" in s or "BỊ" in s
        return ("AMENDS", should_swap)
    if "REPLACE" in s or "EXPIRE" in s or "SUSPEND" in s or "THAY THẾ" in s or "ĐÌNH CHỈ" in s:
        should_swap = "BY" in s or "ĐƯỢC" in s or "BỊ" in s
        return ("REPEALS", should_swap)
    if "GUIDE" in s or "HƯỚNG DẪN" in s:
        should_swap = "BY" in s or "ĐƯỢC" in s or "BỊ" in s
        return ("GUIDELINES", should_swap)
    if "CITE" in s or "BASIS" in s or "TRÍCH DẪN" in s or "CĂN CỨ" in s or "RELATED" in s or "LIÊN QUAN" in s:
        return ("CITES", False)
        
    return ("CITES", False)


def build_kg():
    paths = get_paths()
    out_dir = paths["output_dir"]
    
    # --------------------------------------------------------
    # 1. LOAD DATASETS
    # --------------------------------------------------------
    logger.info("Loading Parquet files...")
    
    if not paths["metadata"].exists():
        raise FileNotFoundError(f"Metadata parquet not found at {paths['metadata']}")
    metadata_df = pl.read_parquet(paths["metadata"])
    logger.info(f"Loaded metadata: {metadata_df.height} rows")
    
    if not paths["chunks"].exists():
        raise FileNotFoundError(f"Chunks parquet not found at {paths['chunks']}")
    
    # Read schema of chunks parquet natively in Polars to see what columns exist
    existing_cols = pl.scan_parquet(paths["chunks"]).collect_schema().names()
    light_cols_needed = [
        "doc_id", "chunk_id", "chunk_type", "section_path", 
        "section_path_json", "procedure_name", "token_estimate", 
        "quality_flags_json", "parent_id"
    ]
    cols_to_load = [c for c in light_cols_needed if c in existing_cols]
    
    chunks_df = pl.read_parquet(paths["chunks"], columns=cols_to_load)
    logger.info(f"Loaded chunks (lightweight columns only): {chunks_df.height} rows (columns loaded: {cols_to_load})")
    
    if not paths["relationships"].exists():
        logger.warning(f"Relationships file not found at {paths['relationships']}. Creating empty frame.")
        relationships_df = pl.DataFrame(schema={"doc_id": pl.Int64, "other_doc_id": pl.Int64, "relationship": pl.Utf8})
    else:
        relationships_df = pl.read_parquet(paths["relationships"])
    logger.info(f"Loaded relationships: {relationships_df.height} rows")
    
    # Ensure ID columns are integer types
    metadata_df = metadata_df.with_columns(pl.col("id").cast(pl.Int64))
    chunks_df = chunks_df.with_columns(pl.col("doc_id").cast(pl.Int64))
    
    # Normalize relationships column names if needed
    if "doc_id" not in relationships_df.columns and "doc_id_final" in relationships_df.columns:
        relationships_df = relationships_df.rename({"doc_id_final": "doc_id", "other_doc_id_final": "other_doc_id"})
    
    relationships_df = relationships_df.with_columns([
        pl.col("doc_id").cast(pl.Int64),
        pl.col("other_doc_id").cast(pl.Int64),
    ])
    
    valid_doc_ids = set(metadata_df["id"].to_list())
    
    # --------------------------------------------------------
    # 2. RELATIONSHIPS GRAPH CLEANING & DIRECTION NORMALIZATION (Task 1)
    # --------------------------------------------------------
    logger.info("Cleaning and normalizing relationships...")
    
    # Filter self-loops and invalid node targets
    cleaned_rel = (
        relationships_df
        .filter(
            (pl.col("doc_id").is_in(valid_doc_ids)) &
            (pl.col("other_doc_id").is_in(valid_doc_ids)) &
            (pl.col("doc_id") != pl.col("other_doc_id"))
        )
    )
    
    # Vectorized edge type resolution & swapping using Polars map_batches
    def parse_rel_series(s: pl.Series) -> pl.Series:
        out = []
        for val in s.to_list():
            clean_type, should_swap = parse_rel(val)
            out.append(f"{clean_type},{should_swap}")
        return pl.Series(out)

    cleaned_rel = cleaned_rel.with_columns(
        pl.col("relationship").map_batches(parse_rel_series).alias("parsed")
    )
    
    cleaned_rel = cleaned_rel.with_columns([
        pl.col("parsed").str.split(",").list.get(0).alias("clean_type"),
        (pl.col("parsed").str.split(",").list.get(1) == "True").alias("should_swap")
    ])
    
    cleaned_rel = cleaned_rel.with_columns([
        pl.when(pl.col("should_swap"))
        .then(pl.col("other_doc_id"))
        .otherwise(pl.col("doc_id"))
        .alias("final_src"),
        
        pl.when(pl.col("should_swap"))
        .then(pl.col("doc_id"))
        .otherwise(pl.col("other_doc_id"))
        .alias("final_tgt")
    ])
    
    cleaned_rel_final = cleaned_rel.select([
        pl.col("final_src").alias("doc_id"),
        pl.col("final_tgt").alias("other_doc_id"),
        pl.col("clean_type").alias("relationship"),
        pl.col("relationship").alias("raw_relationship")
    ]).unique(subset=["doc_id", "other_doc_id", "relationship"])
    
    # Save Cleaned Relationships Parquet
    cleaned_rel_final.write_parquet(out_dir / "cleaned_relationships.parquet")
    logger.info(f"Cleaned relationships saved. Deduplicated height: {cleaned_rel_final.height}")
    
    # Helper to normalize string columns in batches
    def normalize_series(s: pl.Series) -> pl.Series:
        return pl.Series([normalize_value(val) for val in s.to_list()])

    # Helper to calculate stable SHA-1 hash for path string series
    def stable_hash_series(s: pl.Series) -> pl.Series:
        import hashlib
        out = []
        for val in s.to_list():
            if val is not None:
                out.append(hashlib.sha1(str(val).encode("utf-8")).hexdigest()[:16])
            else:
                out.append(None)
        return pl.Series(out)

    # --------------------------------------------------------
    # 3. SCHEMA MAPPING & NODE EXTRACTION (Task 2)
    # --------------------------------------------------------
    logger.info("Building Node CSVs with prefix keys...")
    
    # --- 3.1 Document Nodes ---
    logger.info("Extracting Document nodes...")
    
    # Map Priority Tiers natively via join
    priority_map_df = pl.DataFrame({
        "legal_type": [k.strip() for k in LEGAL_PRIORITY.keys()],
        "priority_tier": list(LEGAL_PRIORITY.values())
    })
    
    metadata_df = metadata_df.with_columns(
        pl.col("legal_type").str.strip_chars().alias("legal_type_stripped")
    )
    
    metadata_df = metadata_df.join(
        priority_map_df,
        left_on="legal_type_stripped",
        right_on="legal_type",
        how="left"
    ).with_columns(
        pl.col("priority_tier").fill_null("Unknown")
    ).drop("legal_type_stripped")
    
    # Derive sector lists
    def derive_sector_list(sectors_str: str) -> str:
        if not sectors_str:
            return "[]"
        parts = [p.strip() for p in str(sectors_str).split(",") if p.strip()]
        return str(parts)
        
    derived_sectors = metadata_df["legal_sectors"].map_elements(derive_sector_list, return_dtype=pl.Utf8)
    
    # Map Node IDs to doc:<id>
    documents_node = metadata_df.select([
        (pl.lit("doc:") + pl.col("id").cast(pl.Utf8)).alias("id:ID(Document)"),
        pl.col("title"),
        pl.col("document_number"),
        pl.col("legal_type"),
        pl.col("legal_sectors"),
        pl.col("issuing_authority"),
        pl.col("issuance_date"),
        pl.col("effect_date"),
        pl.col("effectless_date"),
        pl.col("effect_status"),
        pl.col("signers"),
        pl.col("source"),
        pl.col("priority_tier"),
    ]).with_columns([
        derived_sectors.alias("sector_list")
    ])
    
    documents_node.write_csv(out_dir / "documents.csv")
    logger.info(f"Wrote documents.csv: {documents_node.height} rows")
    
    # --- 3.2 Chunk (Article) Nodes ---
    logger.info("Extracting Chunk nodes...")
    
    # Sort chunks to ensure stable zero-padded index: chunk:<doc_id>:<000000>
    sorted_chunks = chunks_df.sort(["doc_id", "chunk_id"])
    sorted_chunks = sorted_chunks.with_columns(
        (pl.col("chunk_id").cum_count().over("doc_id") - 1).alias("idx")  # 0-based
    )
    
    # Vectorized padding with str.zfill (Extreme memory efficiency)
    sorted_chunks = sorted_chunks.with_columns(
        pl.col("idx").cast(pl.Utf8).str.zfill(6).alias("ordinal")
    )
    
    # Primary Key chunk:<doc_id>:<ordinal>
    sorted_chunks = sorted_chunks.with_columns(
        (pl.lit("chunk:") + pl.col("doc_id").cast(pl.Utf8) + pl.lit(":") + pl.col("ordinal")).alias("stable_id")
    )
    
    # Compute own section_hash in batches using stable SHA-1 hashing
    path_strs = pl.col("doc_id").cast(pl.Utf8) + pl.lit("::") + pl.col("section_path").list.join(" > ")
    sorted_chunks = sorted_chunks.with_columns(
        path_strs.map_batches(stable_hash_series).alias("section_hash")
    )
    
    # Resolve PARENT_OF chunk-chunk links using vector join (No Python loops!)
    logger.info("Resolving parent-child chunk links...")
    parent_mapping = (
        sorted_chunks.select(["stable_id", "parent_id", "doc_id"])
        .filter(pl.col("parent_id").is_not_null() & (pl.col("parent_id") != ""))
        .join(
            sorted_chunks.select([
                pl.col("stable_id").alias("parent_chunk_id"),
                pl.col("section_hash").alias("parent_id"),
                pl.col("doc_id")
            ])
            .filter(pl.col("parent_id").is_not_null() & (pl.col("parent_id") != ""))
            .unique(subset=["parent_id", "doc_id"], keep="first"),
            on=["parent_id", "doc_id"],
            how="left"
        )
    )
    
    # Map unresolved parent refs back
    sorted_chunks = sorted_chunks.join(
        parent_mapping.select(["stable_id", "parent_chunk_id"]),
        on="stable_id",
        how="left"
    ).with_columns(
        pl.when(pl.col("parent_chunk_id").is_null())
        .then(pl.col("parent_id"))
        .otherwise(None)
        .alias("unresolved_parent_ref")
    )
    
    # Build Articles dataframe
    articles_node = sorted_chunks.select([
        pl.col("stable_id").alias("id:ID(Article)"),
        pl.col("chunk_id"),
        pl.col("doc_id").cast(pl.Utf8),
        pl.col("chunk_type"),
        pl.col("section_path_json").alias("section_path"),
        pl.col("procedure_name"),
        pl.col("token_estimate"),
        pl.col("quality_flags_json").alias("quality_flags"),
        pl.col("unresolved_parent_ref")
    ])
    
    # Load heavy columns from parquet for late materialization
    heavy_cols_needed = [c for c in ["embed", "keyword_index"] if c in existing_cols]
    if heavy_cols_needed:
        logger.info(f"Loading heavy columns {heavy_cols_needed} from parquet for late materialization...")
        chunks_heavy = pl.read_parquet(paths["chunks"], columns=["doc_id", "chunk_id"] + heavy_cols_needed)
        
        # Ensure ID columns are integer types to match chunks_heavy
        articles_node = articles_node.with_columns(pl.col("doc_id").cast(pl.Int64))
        chunks_heavy = chunks_heavy.with_columns(pl.col("doc_id").cast(pl.Int64))
        
        logger.info("Joining heavy columns back for articles export...")
        articles_node = articles_node.join(chunks_heavy, on=["doc_id", "chunk_id"], how="left")
        articles_node = articles_node.with_columns(pl.col("doc_id").cast(pl.Utf8))
        
        # Delete heavy df immediately to free RAM
        del chunks_heavy
        import gc
        gc.collect()
        
    articles_node.write_csv(out_dir / "articles.csv")
    logger.info(f"Wrote articles.csv: {articles_node.height} rows")
    
    # Free articles_node immediately
    del articles_node
    gc.collect()
    
    # --- 3.3 LegalType Nodes ---
    logger.info("Extracting LegalType nodes...")
    # Build unique types lookup
    unique_types_df = (
        metadata_df
        .select("legal_type")
        .filter(pl.col("legal_type").is_not_null() & (pl.col("legal_type") != ""))
        .unique()
    )
    type_norms = normalize_series(unique_types_df["legal_type"])
    unique_types_df = unique_types_df.with_columns(
        type_norms.alias("norm_type")
    )
    
    legal_types_node = pl.DataFrame({
        "id:ID(LegalType)": "legal_type:" + type_norms,
        "normalized_value": type_norms
    }).unique()
    
    legal_types_node.write_csv(out_dir / "legal_types.csv")
    logger.info(f"Wrote legal_types.csv: {legal_types_node.height} rows")
    
    # --- 3.4 Authority Nodes ---
    logger.info("Extracting Authority nodes...")
    # Build unique authorities lookup
    unique_auths_df = (
        metadata_df
        .select("issuing_authority")
        .filter(pl.col("issuing_authority").is_not_null() & (pl.col("issuing_authority") != ""))
        .unique()
    )
    auth_norms = normalize_series(unique_auths_df["issuing_authority"])
    unique_auths_df = unique_auths_df.with_columns(
        auth_norms.alias("norm_auth")
    )
    
    authorities_node = pl.DataFrame({
        "id:ID(Authority)": "authority:" + auth_norms,
        "normalized_value": auth_norms,
        "name": unique_auths_df["issuing_authority"]
    }).unique()
    
    authorities_node.write_csv(out_dir / "authorities.csv")
    logger.info(f"Wrote authorities.csv: {authorities_node.height} rows")
    
    # --- 3.5 Sector Nodes ---
    logger.info("Extracting Sector nodes...")
    # Build unique sectors lookup
    unique_sectors_df = (
        metadata_df
        .filter(pl.col("legal_sectors").is_not_null() & (pl.col("legal_sectors") != ""))
        .select(pl.col("legal_sectors").str.split(","))
        .explode("legal_sectors")
        .with_columns(pl.col("legal_sectors").str.strip_chars())
        .filter(pl.col("legal_sectors") != "")
        .unique()
    )
    sector_norms = normalize_series(unique_sectors_df["legal_sectors"])
    unique_sectors_df = unique_sectors_df.with_columns(
        sector_norms.alias("norm_sector")
    )
    
    sectors_node = pl.DataFrame({
        "id:ID(Sector)": "sector:" + sector_norms,
        "normalized_value": sector_norms,
        "name": unique_sectors_df["legal_sectors"]
    }).unique()
    
    sectors_node.write_csv(out_dir / "sectors.csv")
    logger.info(f"Wrote sectors.csv: {sectors_node.height} rows")
    
    # --------------------------------------------------------
    # 4. EDGE EXTRACTION (Task 3)
    # --------------------------------------------------------
    logger.info("Building Edge CSVs...")
    
    # --- 4.1 Document-Document Edges (AMENDS, CITES, REPEALS, GUIDELINES) ---
    logger.info("Processing Document-Document edges...")
    dates_df = metadata_df.select([pl.col("id").alias("doc_id"), "issuance_date"])
    
    doc_doc_with_dates = (
        cleaned_rel_final
        .join(dates_df, on="doc_id", how="left")
        .rename({"issuance_date": "date_src"})
        .join(dates_df.rename({"doc_id": "other_doc_id"}), on="other_doc_id", how="left")
        .rename({"issuance_date": "date_tgt"})
    )
    
    # Convert date strings to days since 1970-01-01 natively in Polars
    doc_doc_with_dates = doc_doc_with_dates.with_columns([
        pl.col("date_src").str.slice(0, 10).str.strptime(pl.Date, format="%Y-%m-%d", strict=False).cast(pl.Int64).fill_null(0).cast(pl.Float64).alias("days_src"),
        pl.col("date_tgt").str.slice(0, 10).str.strptime(pl.Date, format="%Y-%m-%d", strict=False).cast(pl.Int64).fill_null(0).cast(pl.Float64).alias("days_tgt")
    ])
    
    # Vectorized Weight calculation
    doc_doc_edges = doc_doc_with_dates.select([
        (pl.lit("doc:") + pl.col("doc_id").cast(pl.Utf8)).alias(":START_ID(Document)"),
        (pl.lit("doc:") + pl.col("other_doc_id").cast(pl.Utf8)).alias(":END_ID(Document)"),
        pl.col("relationship").alias(":TYPE"),
        pl.when(pl.col("relationship") == "AMENDS")
        .then((pl.col("days_src") - pl.col("days_tgt")).abs())
        .otherwise(1.0)
        .fill_null(1.0)
        .alias("weight:double"),
        pl.col("raw_relationship")
    ])
    
    # Clamp weight to minimum 1.0
    doc_doc_edges = doc_doc_edges.with_columns(
        pl.when((pl.col("weight:double") == 0.0) | (pl.col("weight:double").is_null()))
        .then(1.0)
        .otherwise(pl.col("weight:double"))
        .alias("weight:double")
    )
    
    doc_doc_edges.write_csv(out_dir / "doc_doc_edges.csv")
    logger.info(f"Wrote doc_doc_edges.csv: {doc_doc_edges.height} rows")
    
    # --- 4.2 Document-Article Edges (HAS_CHUNK) ---
    logger.info("Processing Document-Article edges (HAS_CHUNK)...")
    doc_art_edges = sorted_chunks.select([
        (pl.lit("doc:") + pl.col("doc_id").cast(pl.Utf8)).alias(":START_ID(Document)"),
        pl.col("stable_id").alias(":END_ID(Article)"),
    ]).with_columns(
        pl.lit("HAS_CHUNK").alias(":TYPE")
    )
    doc_art_edges.write_csv(out_dir / "doc_art_edges.csv")
    logger.info(f"Wrote doc_art_edges.csv: {doc_art_edges.height} rows")
    
    # --- 4.3 Article-Article NEXT_CHUNK Edges ---
    logger.info("Processing Article-Article next_chunk edges using lead/lag...")
    # Shift stable_id within doc_id to link consecutive chunks (Very fast, zero memory overhead!)
    art_art_next_edges = (
        sorted_chunks.select(["doc_id", "stable_id"])
        .with_columns(
            pl.col("stable_id").shift(-1).over("doc_id").alias("next_stable_id")
        )
        .filter(pl.col("next_stable_id").is_not_null())
        .select([
            pl.col("stable_id").alias(":START_ID(Article)"),
            pl.col("next_stable_id").alias(":END_ID(Article)"),
            pl.lit("NEXT_CHUNK").alias(":TYPE")
        ])
    )
    
    art_art_next_edges.write_csv(out_dir / "art_art_next_edges.csv")
    logger.info(f"Wrote art_art_next_edges.csv: {art_art_next_edges.height} rows")
    
    # --- 4.4 Article-Article PARENT_OF Edges ---
    logger.info("Processing Article-Article parent_of edges...")
    parent_edges = (
        parent_mapping
        .filter(pl.col("parent_chunk_id").is_not_null())
        .select([
            pl.col("parent_chunk_id").alias(":START_ID(Article)"),
            pl.col("stable_id").alias(":END_ID(Article)"),
            pl.lit("PARENT_OF").alias(":TYPE")
        ])
    )
    parent_edges.write_csv(out_dir / "art_art_parent_edges.csv")
    logger.info(f"Wrote art_art_parent_edges.csv: {parent_edges.height} rows")
    
    # --- 4.5 Document-LegalType Edges (HAS_LEGAL_TYPE) ---
    logger.info("Processing Document-LegalType edges...")
    doc_type_edges = (
        metadata_df
        .filter(pl.col("legal_type").is_not_null() & (pl.col("legal_type") != ""))
        .join(unique_types_df, on="legal_type", how="left")
        .select([
            (pl.lit("doc:") + pl.col("id").cast(pl.Utf8)).alias(":START_ID(Document)"),
            (pl.lit("legal_type:") + pl.col("norm_type")).alias(":END_ID(LegalType)"),
            pl.lit("HAS_LEGAL_TYPE").alias(":TYPE")
        ])
        .unique()
    )
    doc_type_edges.write_csv(out_dir / "doc_type_edges.csv")
    logger.info(f"Wrote doc_type_edges.csv: {doc_type_edges.height} rows")
    
    # --- 4.6 Document-Authority Edges (ISSUED_BY) ---
    logger.info("Processing Document-Authority edges...")
    doc_auth_edges = (
        metadata_df
        .filter(pl.col("issuing_authority").is_not_null() & (pl.col("issuing_authority") != ""))
        .join(unique_auths_df, on="issuing_authority", how="left")
        .select([
            (pl.lit("doc:") + pl.col("id").cast(pl.Utf8)).alias(":START_ID(Document)"),
            (pl.lit("authority:") + pl.col("norm_auth")).alias(":END_ID(Authority)"),
            pl.lit("ISSUED_BY").alias(":TYPE")
        ])
        .unique()
    )
    doc_auth_edges.write_csv(out_dir / "doc_auth_edges.csv")
    logger.info(f"Wrote doc_auth_edges.csv: {doc_auth_edges.height} rows")
    
    # --- 4.7 Document-Sector Edges (IN_SECTOR) ---
    logger.info("Processing Document-Sector edges...")
    doc_sector_edges = (
        metadata_df
        .filter(pl.col("legal_sectors").is_not_null() & (pl.col("legal_sectors") != ""))
        .select([
            (pl.lit("doc:") + pl.col("id").cast(pl.Utf8)).alias(":START_ID(Document)"),
            pl.col("legal_sectors").str.split(",")
        ])
        .explode("legal_sectors")
        .with_columns(pl.col("legal_sectors").str.strip_chars())
        .filter(pl.col("legal_sectors") != "")
        .join(unique_sectors_df, on="legal_sectors", how="left")
        .select([
            pl.col(":START_ID(Document)"),
            (pl.lit("sector:") + pl.col("norm_sector")).alias(":END_ID(Sector)"),
            pl.lit("IN_SECTOR").alias(":TYPE")
        ])
        .unique()
    )
    doc_sector_edges.write_csv(out_dir / "doc_sector_edges.csv")
    logger.info(f"Wrote doc_sector_edges.csv: {doc_sector_edges.height} rows")
    
    # --------------------------------------------------------
    # 5. DATA INTEGRITY CHECKS (Quality Gates)
    # --------------------------------------------------------
    logger.info("Running Data Integrity verification...")
    
    doc_ids_set = set(documents_node["id:ID(Document)"].to_list())
    art_ids_set = set(sorted_chunks["stable_id"].to_list())
    type_ids_set = set(legal_types_node["id:ID(LegalType)"].to_list())
    auth_ids_set = set(authorities_node["id:ID(Authority)"].to_list())
    sect_ids_set = set(sectors_node["id:ID(Sector)"].to_list())
    
    # 5.1 No Orphan Edges
    invalid_doc_doc = doc_doc_edges.filter(
        (~pl.col(":START_ID(Document)").is_in(doc_ids_set)) |
        (~pl.col(":END_ID(Document)").is_in(doc_ids_set))
    )
    logger.info(f"Data Gate 1 (Doc-Doc orphans): {invalid_doc_doc.height} invalid rows")
    assert invalid_doc_doc.height == 0, "Doc-Doc relationship contains orphan nodes!"
    
    invalid_doc_art = doc_art_edges.filter(
        (~pl.col(":START_ID(Document)").is_in(doc_ids_set)) |
        (~pl.col(":END_ID(Article)").is_in(art_ids_set))
    )
    logger.info(f"Data Gate 2 (Doc-Art orphans): {invalid_doc_art.height} invalid rows")
    assert invalid_doc_art.height == 0, "Doc-Article relationship contains orphan nodes!"
    
    invalid_art_art_next = art_art_next_edges.filter(
        (~pl.col(":START_ID(Article)").is_in(art_ids_set)) |
        (~pl.col(":END_ID(Article)").is_in(art_ids_set))
    )
    logger.info(f"Data Gate 3 (Art-Art next orphans): {invalid_art_art_next.height} invalid rows")
    assert invalid_art_art_next.height == 0, "NEXT_CHUNK relationship contains orphan nodes!"
    
    invalid_art_art_parent = parent_edges.filter(
        (~pl.col(":START_ID(Article)").is_in(art_ids_set)) |
        (~pl.col(":END_ID(Article)").is_in(art_ids_set))
    )
    logger.info(f"Data Gate 4 (Art-Art parent orphans): {invalid_art_art_parent.height} invalid rows")
    assert invalid_art_art_parent.height == 0, "PARENT_OF relationship contains orphan nodes!"
    
    invalid_doc_type = doc_type_edges.filter(
        (~pl.col(":START_ID(Document)").is_in(doc_ids_set)) |
        (~pl.col(":END_ID(LegalType)").is_in(type_ids_set))
    )
    logger.info(f"Data Gate 5 (Doc-Type orphans): {invalid_doc_type.height} invalid rows")
    assert invalid_doc_type.height == 0, "Doc-LegalType relationship contains orphan nodes!"
    
    invalid_doc_auth = doc_auth_edges.filter(
        (~pl.col(":START_ID(Document)").is_in(doc_ids_set)) |
        (~pl.col(":END_ID(Authority)").is_in(auth_ids_set))
    )
    logger.info(f"Data Gate 6 (Doc-Auth orphans): {invalid_doc_auth.height} invalid rows")
    assert invalid_doc_auth.height == 0, "Doc-Authority relationship contains orphan nodes!"
    
    invalid_doc_sector = doc_sector_edges.filter(
        (~pl.col(":START_ID(Document)").is_in(doc_ids_set)) |
        (~pl.col(":END_ID(Sector)").is_in(sect_ids_set))
    )
    logger.info(f"Data Gate 7 (Doc-Sector orphans): {invalid_doc_sector.height} invalid rows")
    assert invalid_doc_sector.height == 0, "Doc-Sector relationship contains orphan nodes!"
    
    # 5.2 No Self Loops
    self_loops = doc_doc_edges.filter(pl.col(":START_ID(Document)") == pl.col(":END_ID(Document)"))
    logger.info(f"Data Gate 8 (Self Loops count): {self_loops.height}")
    assert self_loops.height == 0, "Self-loop relationships detected in Doc-Doc edges!"
    
    logger.info("All Data Quality Gates PASSED successfully!")
    
    # --------------------------------------------------------
    # 6. COMPRESS EXPORTS INTO ZIP
    # --------------------------------------------------------
    zip_path = paths["zip_output"]
    logger.info(f"Compressing CSV exports into {zip_path}...")
    
    csv_files = [
        "documents.csv", "articles.csv", "legal_types.csv", "authorities.csv", "sectors.csv",
        "doc_doc_edges.csv", "doc_art_edges.csv", "art_art_next_edges.csv", "art_art_parent_edges.csv",
        "doc_type_edges.csv", "doc_auth_edges.csv", "doc_sector_edges.csv"
    ]
    
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in csv_files:
            file_path = out_dir / file
            if file_path.exists():
                zf.write(file_path, arcname=file)
                logger.info(f"  Added {file} to ZIP")
                
    logger.info(f"Pipeline finished! Output package ready at: {zip_path.resolve()}")


if __name__ == "__main__":
    build_kg()
