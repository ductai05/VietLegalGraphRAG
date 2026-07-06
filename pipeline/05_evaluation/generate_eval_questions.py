"""
generate_eval_questions.py
==========================
Tạo bộ câu hỏi trắc nghiệm (multiple-choice) từ chunks văn bản pháp luật Việt Nam
để đánh giá hệ thống GraphRAG.

Sử dụng: Gemini API với model gemma-4-31b-it
Input:   data/legal_chunking_dataset/{chunks,metadata}.parquet
Output:  pipeline/05_evaluation/eval_questions.json

Usage:
    # Dry-run (chỉ sampling, không gọi API)
    python generate_eval_questions.py --dry-run

    # Chạy đầy đủ
    python generate_eval_questions.py

    # Chạy với seed tùy chỉnh
    python generate_eval_questions.py --seed 123

    # Chạy tiếp từ checkpoint
    python generate_eval_questions.py --resume
"""

import os
import sys
import json
import time
import random
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import polars as pl
from google import genai
from google.genai import types

# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
DATA_DIR = BASE_DIR / "data" / "preprocessed" / "chunking"
CHUNKS_PATH = DATA_DIR / "chunks.parquet"
META_PATH = DATA_DIR / "metadata.parquet"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "eval_questions.json"
CHECKPOINT_FILE = OUTPUT_DIR / "_checkpoint.json"
SAMPLED_DATA_FILE = OUTPUT_DIR / "_sampled_data.json"

# Sampling config
NUM_DOCS_TO_SAMPLE = 60
CHUNKS_PER_DOC = 4              # target consecutive chunks per document
TARGET_QUESTIONS = 200
QUESTIONS_PER_CALL = 4          # questions to generate per API call
SEED = 42

# API config
MODEL_NAME = "gemma-4-31b-it"
RATE_LIMIT_DELAY = 2.0          # seconds between API calls
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0          # exponential backoff base

# Chunk types to sample (meaningful content for Q&A)
VALID_CHUNK_TYPES = {
    "article", "clause_group", "preamble",
    "procedure_record", "chapter", "part", "section",
    "appendix", "table_summary"
}

# Legal types for stratified sampling (priority order)
PRIORITY_LEGAL_TYPES = [
    "Luật", "Bộ luật", "Nghị định", "Thông tư",
    "Quyết định", "Nghị quyết", "Pháp lệnh",
    "Chỉ thị", "Công văn", "Thông tư liên tịch"
]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# PHASE 1: SAMPLING
# ============================================================

def load_metadata() -> pl.DataFrame:
    """Load metadata parquet using Polars."""
    logger.info("Loading metadata from %s", META_PATH)
    needed = ["id", "title", "legal_type", "effect_status", "issuing_authority"]
    df = pl.scan_parquet(META_PATH, glob=False).select(needed).collect()
    logger.info("Metadata loaded: %d documents", df.height)
    return df


def stratified_sample_documents(
    meta_df: pl.DataFrame,
    num_docs: int,
    seed: int,
) -> List[Dict]:
    """
    Stratified random sample of documents across legal_type categories.
    Returns list of dicts with document info.
    """
    rng = random.Random(seed)

    # Filter by effect_status
    active_df = meta_df.filter(
        pl.col("effect_status").fill_null("").str.contains("Còn hiệu lực")
    )

    ids = active_df["id"].to_list()
    titles = active_df["title"].to_list()
    legal_types = active_df["legal_type"].to_list()
    issuing_auths = active_df["issuing_authority"].to_list()

    # Build per-type pools
    type_pools: Dict[str, List[Dict]] = {}
    for i in range(len(ids)):
        lt = legal_types[i] or "Khác"
        doc = {
            "doc_id": ids[i],
            "title": titles[i] or "",
            "legal_type": lt,
            "issuing_authority": issuing_auths[i] or "",
        }
        type_pools.setdefault(lt, []).append(doc)

    logger.info(
        "Document pools after filtering (Còn hiệu lực): %s",
        {k: len(v) for k, v in sorted(type_pools.items(), key=lambda x: -len(x[1]))[:15]}
    )

    # Allocate slots across types
    sampled = []
    remaining = num_docs

    # Priority types first
    for lt in PRIORITY_LEGAL_TYPES:
        pool = type_pools.get(lt, [])
        if not pool:
            continue
        # Proportional allocation, at least 2 per type if available
        share = max(2, int(num_docs * len(pool) / sum(len(v) for v in type_pools.values())))
        share = min(share, remaining, len(pool))
        chosen = rng.sample(pool, share)
        sampled.extend(chosen)
        remaining -= share
        if remaining <= 0:
            break

    # Fill remaining from all pools
    if remaining > 0:
        all_remaining = []
        sampled_ids = {d["doc_id"] for d in sampled}
        for pool in type_pools.values():
            for doc in pool:
                if doc["doc_id"] not in sampled_ids:
                    all_remaining.append(doc)
        extra = rng.sample(all_remaining, min(remaining, len(all_remaining)))
        sampled.extend(extra)

    rng.shuffle(sampled)
    logger.info("Sampled %d documents across %d legal types",
                len(sampled), len({d["legal_type"] for d in sampled}))
    return sampled


def collect_chunks_for_docs(
    doc_ids: List[int],
    chunks_per_doc: int = CHUNKS_PER_DOC,
    seed: int = SEED,
) -> Dict[int, List[Dict]]:
    """
    Read chunks.parquet with Polars scan_parquet and filter pushdown.
    """
    rng = random.Random(seed)
    target_ids = set(doc_ids)

    needed_cols = [
        "chunk_id", "doc_id", "chunk_text", "contextual_text",
        "chunk_type", "section_path", "embed",
        "prev_chunk_id", "next_chunk_id", "token_estimate", "char_count",
    ]

    logger.info("Reading chunks.parquet with Polars predicate pushdown for %d docs...",
                len(target_ids))

    # Use Polars lazy frame for fast columnar scanning
    lf = pl.scan_parquet(CHUNKS_PATH, glob=False).select(needed_cols)
    
    # Apply filters
    filtered_df = lf.filter(
        pl.col("doc_id").is_in(list(target_ids)) &
        pl.col("embed").fill_null(False) &
        pl.col("chunk_type").is_in(list(VALID_CHUNK_TYPES)) &
        (pl.col("chunk_text").str.len_chars() >= 50)
    ).collect()

    logger.info("Filtered table: %d rows (from 7.47M total)", filtered_df.height)

    # Convert to Python dicts grouped by doc_id
    doc_chunks: Dict[int, List[Dict]] = {did: [] for did in target_ids}
    
    # We can iter_rows for dictionaries
    for row in filtered_df.iter_rows(named=True):
        did = row["doc_id"]
        chunk = {
            "chunk_id": row["chunk_id"],
            "doc_id": did,
            "chunk_text": row["chunk_text"],
            "contextual_text": row["contextual_text"] or "",
            "chunk_type": row["chunk_type"],
            "section_path": row["section_path"].to_list() if isinstance(row["section_path"], pl.Series) else (row["section_path"] or []),
            "prev_chunk_id": row["prev_chunk_id"],
            "next_chunk_id": row["next_chunk_id"],
            "token_estimate": row["token_estimate"] or 0,
            "char_count": row["char_count"] or 0,
        }
        doc_chunks[did].append(chunk)

    del filtered_df
    found = sum(1 for v in doc_chunks.values() if v)
    logger.info("Found chunks for %d/%d docs", found, len(target_ids))

    # Select consecutive chunks per doc
    result: Dict[int, List[Dict]] = {}
    for did, chunks in doc_chunks.items():
        if not chunks:
            logger.warning("No valid chunks found for doc_id=%d", did)
            continue

        if len(chunks) <= chunks_per_doc:
            result[did] = chunks
        else:
            # Try to find consecutive chunks using linked list
            chunk_by_id = {c["chunk_id"]: c for c in chunks}
            best_group = None

            # Find starting points (chunks with no prev or prev not in set)
            starts = [c for c in chunks if c["prev_chunk_id"] is None
                      or c["prev_chunk_id"] not in chunk_by_id]

            for start in starts:
                group = [start]
                current = start
                while len(group) < chunks_per_doc:
                    next_id = current.get("next_chunk_id")
                    if next_id and next_id in chunk_by_id:
                        current = chunk_by_id[next_id]
                        group.append(current)
                    else:
                        break
                if best_group is None or len(group) > len(best_group):
                    best_group = group

            # Fallback: random sample if no good consecutive group
            if best_group and len(best_group) >= 2:
                result[did] = best_group
            else:
                result[did] = rng.sample(chunks, min(chunks_per_doc, len(chunks)))

    logger.info("Collected chunks for %d documents (avg %.1f chunks/doc)",
                len(result),
                sum(len(v) for v in result.values()) / max(len(result), 1))
    return result


# ============================================================
# PHASE 2: PROMPT CONSTRUCTION
# ============================================================

SYSTEM_PROMPT = """Bạn là một chuyên gia pháp luật Việt Nam. Nhiệm vụ của bạn là tạo câu hỏi trắc nghiệm (multiple-choice) chất lượng cao dựa trên đoạn văn bản pháp luật được cung cấp.

YÊU CẦU:
1. Tạo đúng {n_questions} câu hỏi trắc nghiệm, mỗi câu có 4 lựa chọn (A, B, C, D).
2. Chỉ có DUY NHẤT 1 đáp án đúng cho mỗi câu.
3. Câu hỏi phải trả lời được DỰA TRÊN nội dung chunks đã cho, KHÔNG dựa trên kiến thức bên ngoài.
4. Phân bố các mức độ khó: 1 câu dễ (easy), 1-2 câu trung bình (medium), 1 câu khó (hard).
5. Các đáp án sai (distractors) phải hợp lý, không quá rõ ràng là sai.
6. Đa dạng loại câu hỏi: factual (hỏi sự kiện/thông tin), inference (suy luận), procedural (quy trình), comparison (so sánh).
7. Viết hoàn toàn bằng tiếng Việt.

ĐỊNH DẠNG OUTPUT: Trả về CHÍNH XÁC một JSON array, không có text nào khác trước hoặc sau JSON. Mỗi object trong array có cấu trúc:
```json
[
  {{
    "question": "Câu hỏi...",
    "choices": {{
      "A": "Lựa chọn A",
      "B": "Lựa chọn B",
      "C": "Lựa chọn C",
      "D": "Lựa chọn D"
    }},
    "answer": "B",
    "difficulty": "medium",
    "question_type": "factual",
    "reasoning": "Giải thích ngắn gọn tại sao đáp án đúng",
    "relevant_chunk_ids": ["chunk_id_1"]
  }}
]
```

Lưu ý:
- "answer" chỉ chứa ký tự A, B, C, hoặc D.
- "difficulty" là một trong: "easy", "medium", "hard".
- "question_type" là một trong: "factual", "inference", "procedural", "comparison".
- "relevant_chunk_ids" chứa chunk_id(s) liên quan nhất đến câu hỏi.
"""


def build_prompt(
    doc_info: Dict,
    chunks: List[Dict],
    n_questions: int = QUESTIONS_PER_CALL,
) -> str:
    """Build the user prompt with document context."""
    # Document header
    header = (
        f"=== THÔNG TIN VĂN BẢN ===\n"
        f"Tên: {doc_info['title']}\n"
        f"Loại: {doc_info['legal_type']}\n"
        f"Cơ quan ban hành: {doc_info['issuing_authority']}\n"
        f"Doc ID: {doc_info['doc_id']}\n"
    )

    # Chunks
    chunk_sections = []
    for i, chunk in enumerate(chunks, 1):
        section = chunk.get("section_path", [])
        section_str = " > ".join(section) if section else "N/A"
        chunk_sections.append(
            f"--- Chunk {i} (ID: {chunk['chunk_id']}, Type: {chunk['chunk_type']}, "
            f"Section: {section_str}) ---\n"
            f"{chunk['chunk_text']}\n"
        )

    chunks_text = "\n".join(chunk_sections)

    prompt = (
        f"{header}\n"
        f"=== NỘI DUNG CÁC CHUNKS ===\n"
        f"{chunks_text}\n"
        f"Hãy tạo {n_questions} câu hỏi trắc nghiệm dựa trên nội dung trên. "
        f"Trả về JSON array như format đã yêu cầu."
    )
    return prompt


# ============================================================
# PHASE 3: GEMINI API CALLS
# ============================================================

def init_gemini_client() -> genai.Client:
    """Load API key and initialize setup."""
    env_file = BASE_DIR / ".env"
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    
    if not api_key and env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip('"\'')
                elif line.startswith("GOOGLE_API_KEY="):
                    if not api_key:
                        api_key = line.split("=", 1)[1].strip('"\'')
    if not api_key:
        raise ValueError(
            "Missing GEMINI_API_KEY or GOOGLE_API_KEY in environment or .env file.\n"
            "Set it in: " + str(BASE_DIR / ".env")
        )

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=300_000)  # 300s timeout in milliseconds
    )
    logger.info("GenAI SDK client initialized for model: %s", MODEL_NAME)
    return client


def call_gemini(
    client: genai.Client,
    system_prompt: str,
    user_prompt: str,
    retry_count: int = 0,
) -> Optional[str]:
    """Call Gemini API via google-genai SDK with retry logic."""
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
                top_p=0.9,
                max_output_tokens=4096,
                response_mime_type="application/json",
            )
        )
        
        if response.text:
            return response.text
        logger.warning("Empty response from API: %s", response)
        return None

    except Exception as e:
        if retry_count < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** retry_count)
            logger.warning("API error (attempt %d/%d): %s. Retrying in %.1fs...",
                          retry_count + 1, MAX_RETRIES, str(e), delay)
            time.sleep(delay)
            return call_gemini(client, system_prompt, user_prompt, retry_count + 1)
        else:
            logger.error("API call failed after %d retries: %s", MAX_RETRIES, str(e))
            return None


def parse_questions_response(raw_text: str) -> List[Dict]:
    """Parse the JSON response from the model."""
    if not raw_text:
        return []

    # Clean the response - remove markdown code block markers if present
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict) and "questions" in parsed:
            return parsed["questions"]
        else:
            logger.warning("Unexpected JSON structure: %s", type(parsed))
            return [parsed] if isinstance(parsed, dict) else []
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON response: %s\nRaw text: %s...",
                     str(e), text[:200])
        return []


def validate_question(q: Dict) -> bool:
    """Validate a single question dict."""
    required = ["question", "choices", "answer", "difficulty", "question_type", "reasoning"]
    for field in required:
        if field not in q:
            return False

    if not isinstance(q["choices"], dict):
        return False
    if set(q["choices"].keys()) != {"A", "B", "C", "D"}:
        return False
    if q["answer"] not in {"A", "B", "C", "D"}:
        return False
    if q["difficulty"] not in {"easy", "medium", "hard"}:
        return False
    if q["question_type"] not in {"factual", "inference", "procedural", "comparison"}:
        return False

    return True


# ============================================================
# CHECKPOINT MANAGEMENT
# ============================================================

def load_checkpoint() -> Dict:
    """Load checkpoint if exists."""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_doc_ids": [], "questions": []}


def save_checkpoint(checkpoint: Dict):
    """Save checkpoint."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def save_sampled_data(sampled_docs: List[Dict], doc_chunks: Dict[int, List[Dict]]):
    """Save sampled data for reproducibility and dry-run inspection."""
    data = {
        "sampled_docs": sampled_docs,
        "doc_chunks_summary": {
            str(did): {
                "num_chunks": len(chunks),
                "chunk_types": [c["chunk_type"] for c in chunks],
                "total_chars": sum(c.get("char_count", 0) for c in chunks),
                "chunk_ids": [c["chunk_id"] for c in chunks],
            }
            for did, chunks in doc_chunks.items()
        }
    }
    with open(SAMPLED_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Sampled data saved to %s", SAMPLED_DATA_FILE)


# ============================================================
# PHASE 4: POST-PROCESSING & EXPORT
# ============================================================

def build_final_output(
    all_questions: List[Dict],
    sampled_docs: List[Dict],
    seed: int,
) -> Dict:
    """Build the final JSON output."""
    tz_vn = timezone(timedelta(hours=7))

    output = {
        "metadata": {
            "generated_at": datetime.now(tz_vn).isoformat(),
            "model": MODEL_NAME,
            "total_questions": len(all_questions),
            "total_documents_sampled": len(sampled_docs),
            "seed": seed,
            "valid_chunk_types": sorted(VALID_CHUNK_TYPES),
        },
        "questions": all_questions,
    }
    return output


def deduplicate_questions(questions: List[Dict]) -> List[Dict]:
    """Remove near-duplicate questions based on question text."""
    seen = set()
    unique = []
    for q in questions:
        # Normalize for comparison
        normalized = q["question"].strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            unique.append(q)
        else:
            logger.info("Removed duplicate question: %s...", q["question"][:80])
    return unique


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_sampling(seed: int) -> Tuple[List[Dict], Dict[int, List[Dict]]]:
    """Phase 1: Sample documents and collect chunks."""
    meta_table = load_metadata()
    sampled_docs = stratified_sample_documents(meta_table, NUM_DOCS_TO_SAMPLE, seed)
    del meta_table  # free memory

    doc_ids = [d["doc_id"] for d in sampled_docs]
    doc_chunks = collect_chunks_for_docs(doc_ids, CHUNKS_PER_DOC, seed)

    # Remove docs without chunks
    sampled_docs = [d for d in sampled_docs if d["doc_id"] in doc_chunks]

    save_sampled_data(sampled_docs, doc_chunks)
    return sampled_docs, doc_chunks


def run_generation(
    sampled_docs: List[Dict],
    doc_chunks: Dict[int, List[Dict]],
    resume: bool = False,
) -> List[Dict]:
    """Phase 2-3: Generate questions via Gemini API."""
    client = init_gemini_client()

    # Load or init checkpoint
    checkpoint = load_checkpoint() if resume else {"completed_doc_ids": [], "questions": []}
    completed_ids = set(checkpoint["completed_doc_ids"])
    all_questions = list(checkpoint["questions"])

    # Filter docs to process
    docs_to_process = [d for d in sampled_docs if d["doc_id"] not in completed_ids]
    logger.info("Docs to process: %d (already done: %d, questions so far: %d)",
                len(docs_to_process), len(completed_ids), len(all_questions))

    # Check if we already have enough
    if len(all_questions) >= TARGET_QUESTIONS:
        logger.info("Already have %d questions (target: %d). Skipping generation.",
                    len(all_questions), TARGET_QUESTIONS)
        return all_questions

    question_counter = len(all_questions)

    for idx, doc in enumerate(docs_to_process):
        if question_counter >= TARGET_QUESTIONS:
            logger.info("Reached target of %d questions. Stopping.", TARGET_QUESTIONS)
            break

        doc_id = doc["doc_id"]
        chunks = doc_chunks.get(doc_id, [])
        if not chunks:
            continue

        # How many questions for this doc
        remaining = TARGET_QUESTIONS - question_counter
        n_q = min(QUESTIONS_PER_CALL, remaining)

        logger.info("[%d/%d] Generating %d questions for doc_id=%d (%s) with %d chunks...",
                    idx + 1, len(docs_to_process), n_q, doc_id,
                    doc["legal_type"], len(chunks))

        # Build prompts
        system_prompt = SYSTEM_PROMPT.format(n_questions=n_q)
        user_prompt = build_prompt(doc, chunks, n_q)

        # Call API
        raw_response = call_gemini(client, system_prompt, user_prompt)
        parsed = parse_questions_response(raw_response)

        # Validate and enrich
        valid_count = 0
        for q in parsed:
            if not validate_question(q):
                logger.warning("Invalid question skipped: %s", json.dumps(q, ensure_ascii=False)[:200])
                continue

            question_counter += 1
            q_final = {
                "question_id": f"q_{question_counter:03d}",
                "question": q["question"],
                "choices": q["choices"],
                "answer": q["answer"],
                "difficulty": q["difficulty"],
                "evidence": {
                    "chunk_ids": q.get("relevant_chunk_ids", [c["chunk_id"] for c in chunks]),
                    "chunk_texts": [c["chunk_text"][:500] for c in chunks],  # truncated
                    "doc_id": doc_id,
                    "doc_title": doc["title"],
                    "legal_type": doc["legal_type"],
                    "section_path": chunks[0].get("section_path", []),
                },
                "question_type": q["question_type"],
                "reasoning": q["reasoning"],
            }
            all_questions.append(q_final)
            valid_count += 1

        logger.info("  -> Got %d valid questions (total: %d/%d)",
                    valid_count, question_counter, TARGET_QUESTIONS)

        # Update checkpoint every call
        checkpoint["completed_doc_ids"].append(doc_id)
        checkpoint["questions"] = all_questions
        save_checkpoint(checkpoint)

        # Rate limiting
        if idx < len(docs_to_process) - 1:
            time.sleep(RATE_LIMIT_DELAY)

    return all_questions


def run_pipeline(args):
    """Run the full pipeline."""
    seed = args.seed
    logger.info("=" * 60)
    logger.info("RAG Evaluation Question Generator")
    logger.info("Seed: %d | Target: %d questions | Model: %s", seed, TARGET_QUESTIONS, MODEL_NAME)
    logger.info("=" * 60)

    # Phase 1: Sampling
    logger.info("\n--- PHASE 1: SAMPLING ---")
    start = time.time()
    sampled_docs, doc_chunks = run_sampling(seed)
    logger.info("Sampling completed in %.1fs. Got %d docs with chunks.",
                time.time() - start, len(doc_chunks))

    # Print sampling summary
    type_dist = {}
    for d in sampled_docs:
        lt = d["legal_type"]
        type_dist[lt] = type_dist.get(lt, 0) + 1
    logger.info("Legal type distribution: %s", json.dumps(type_dist, ensure_ascii=False))

    if args.dry_run:
        logger.info("\n=== DRY RUN MODE ===")
        logger.info("Sampled %d documents, %d total chunks",
                    len(sampled_docs),
                    sum(len(v) for v in doc_chunks.values()))
        logger.info("Check sampled data at: %s", SAMPLED_DATA_FILE)

        # Show a sample prompt
        if sampled_docs and doc_chunks:
            sample_doc = sampled_docs[0]
            sample_chunks = doc_chunks[sample_doc["doc_id"]]
            prompt = build_prompt(sample_doc, sample_chunks)
            logger.info("\n--- SAMPLE PROMPT (doc_id=%d) ---\n%s\n---",
                       sample_doc["doc_id"], prompt[:2000])
        return

    # Phase 2-3: Generation
    logger.info("\n--- PHASE 2-3: GENERATION ---")
    start = time.time()
    all_questions = run_generation(sampled_docs, doc_chunks, resume=args.resume)
    logger.info("Generation completed in %.1fs. Got %d questions.",
                time.time() - start, len(all_questions))

    # Phase 4: Post-processing
    logger.info("\n--- PHASE 4: POST-PROCESSING ---")
    all_questions = deduplicate_questions(all_questions)
    logger.info("After deduplication: %d questions", len(all_questions))

    # Build and save final output
    output = build_final_output(all_questions, sampled_docs, seed)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("Output saved to: %s", OUTPUT_FILE)

    # Print summary stats
    difficulties = {}
    qtypes = {}
    legal_types = {}
    for q in all_questions:
        difficulties[q["difficulty"]] = difficulties.get(q["difficulty"], 0) + 1
        qtypes[q["question_type"]] = qtypes.get(q["question_type"], 0) + 1
        lt = q["evidence"]["legal_type"]
        legal_types[lt] = legal_types.get(lt, 0) + 1

    logger.info("\n=== FINAL SUMMARY ===")
    logger.info("Total questions: %d", len(all_questions))
    logger.info("Difficulty distribution: %s", difficulties)
    logger.info("Question type distribution: %s", qtypes)
    logger.info("Legal type distribution: %s",
                json.dumps(legal_types, ensure_ascii=False))

    # Cleanup checkpoint
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Checkpoint cleaned up.")

    logger.info("\nDone! ✅")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate evaluation MCQ questions from legal chunks")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed for reproducibility")
    parser.add_argument("--dry-run", action="store_true", help="Only sample data, don't call API")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()
    run_pipeline(args)
