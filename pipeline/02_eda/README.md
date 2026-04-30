---
language:
- vi
license: cc-by-4.0
pretty_name: Vietnamese Legal Documents
size_categories:
- 1M<n<10M
task_categories:
- text-classification
- text-generation
- question-answering
- summarization
tags:
- legal
- vietnamese
- law
- government
configs:
- config_name: metadata
  data_files:
  - split: data
    path: data/metadata.parquet
- config_name: relationships
  data_files:
  - split: data
    path: data/relationships.parquet
- config_name: content
  data_files:
  - split: data
    path: data/content.parquet
- config_name: legacy
  data_files:
  - split: content
    path: legacy/content.parquet
  - split: metadata
    path: legacy/metadata.parquet
dataset_info:
- config_name: legacy
  features:
  - name: id
    dtype: int64
  - name: document_number
    dtype: string
  - name: title
    dtype: string
  - name: legal_type
    dtype: string
  - name: legal_sectors
    dtype: string
  - name: issuing_authority
    dtype: string
  - name: issuance_date
    dtype: string
  - name: effect_date
    dtype: string
  - name: effectless_date
    dtype: string
  - name: effect_status
    dtype: string
  - name: signers
    dtype: string
  splits:
  - name: metadata
    num_bytes: 137000000
    num_examples: 518601
  - name: content
    num_bytes: 3507657146
    num_examples: 518235
  download_size: 3644657146
- config_name: metadata
  features:
  - name: id
    dtype: int64
  - name: title
    dtype: string
  - name: so_ky_hieu
    dtype: string
  - name: ngay_ban_hanh
    dtype: string
  - name: loai_van_ban
    dtype: string
  - name: ngay_co_hieu_luc
    dtype: string
  - name: ngay_het_hieu_luc
    dtype: string
  - name: nguon_thu_thap
    dtype: string
  - name: ngay_dang_cong_bao
    dtype: string
  - name: nganh
    dtype: string
  - name: linh_vuc
    dtype: string
  - name: co_quan_ban_hanh
    dtype: string
  - name: chuc_danh
    dtype: string
  - name: nguoi_ky
    dtype: string
  - name: pham_vi
    dtype: string
  - name: thong_tin_ap_dung
    dtype: string
  - name: tinh_trang_hieu_luc
    dtype: string
  num_rows: 153420
- config_name: relationships
  features:
  - name: doc_id
    dtype: int64
  - name: other_doc_id
    dtype: string
  - name: relationship
    dtype: string
  num_rows: 897890
- config_name: content
  features:
  - name: id
    dtype: string
  - name: content_html
    dtype: string
  num_rows: 178665
---

# Vietnamese Legal Documents


A comprehensive collection of Vietnamese legal documents — laws, decrees, circulars, decisions, and other normative acts — sourced from [vbpl.vn](https://vbpl.vn), the official Government Legal Document Portal operated by the Ministry of Justice. The dataset includes structured metadata for every document, raw HTML full-text content, and a rich graph of cross-document legal relationships (amendments, citations, repeals, etc.).

- **Curated by:** [Thịnh Ngô](https://huggingface.co/th1nhng0)
- **Source:** [vbpl.vn](https://vbpl.vn)
- **Language:** Vietnamese
- **License:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

## Quick Start

```python
from datasets import load_dataset

# Metadata for all 153k documents
meta = load_dataset("th1nhng0/vietnamese-legal-documents", "metadata", split="data")
print(meta.to_pandas().head())

# Cross-document relationships (amendments, citations, repeals, …)
rels = load_dataset("th1nhng0/vietnamese-legal-documents", "relationships", split="data")
print(rels.to_pandas().head())

# Full-text HTML content for ~149k documents
content = load_dataset("th1nhng0/vietnamese-legal-documents", "content", split="data")
print(content.to_pandas().head())
```

Join the two on `id` (metadata) ↔ `doc_id` (relationships):

```python
import pandas as pd

df = meta.to_pandas()
rel = rels.to_pandas()

# Find all documents that cite document 10420
citing = rel[rel["other_doc_id"] == "10420"].merge(df, left_on="doc_id", right_on="id")
print(citing[["id", "title", "relationship"]])
```

## Dataset Structure

The dataset has four configs:

| Config | Split | Rows | Description |
|---|---|---|---|
| `metadata` | `data` | 153,420 | One row per document — 16 metadata fields |
| `content` | `data` | 178,665 | Raw HTML full-text content |
| `relationships` | `data` | 897,890 | Directed edges between documents |
| `legacy` | `metadata` | 518,601 | Older crawl — English field names, more docs |
| `legacy` | `content` | 518,235 | Plain-text content for older crawl |

### `metadata`

| Column | Description |
|---|---|
| `id` | Unique document ID (int) |
| `title` | Full Vietnamese title |
| `so_ky_hieu` | Official number, e.g. `115/NQ-HĐBCQG` |
| `ngay_ban_hanh` | Issuance date (`DD/MM/YYYY`) |
| `loai_van_ban` | Type — Quyết định, Nghị quyết, Thông tư, … |
| `ngay_co_hieu_luc` | Effective date |
| `ngay_het_hieu_luc` | Expiry date (empty if still in effect) |
| `nguon_thu_thap` | Collection source (e.g. Công báo) |
| `ngay_dang_cong_bao` | Official Gazette publication date |
| `nganh` | Sector — Tài chính, Y tế, … |
| `linh_vuc` | Legal field / sub-domain |
| `co_quan_ban_hanh` | Issuing authority (551 unique bodies) |
| `chuc_danh` | Signatory title — Chủ tịch, Bộ trưởng, … |
| `nguoi_ky` | Signatory name |
| `pham_vi` | Geographical scope |
| `thong_tin_ap_dung` | Implementation note |
| `tinh_trang_hieu_luc` | Effect status — Còn hiệu lực, Hết hiệu lực toàn bộ, … |

### `content`

| Column | Description |
|---|---|
| `id` | Document ID (join key → `metadata.id`) |
| `content_html` | Raw HTML body of the document |

> **Note:** Some documents in `metadata` do not have a corresponding entry in `content` because the portal only provides PDF scans for those documents (no HTML version available).

### `relationships`

| Column | Description |
|---|---|
| `doc_id` | Source document ID (join key → `metadata.id`) |
| `other_doc_id` | Target document ID |
| `relationship` | Edge label  |

### `legacy`

An older, larger crawl snapshot with ~518 k documents. Field names and enumerated values are in English (unlike the current configs which use Vietnamese originals). Dates are `YYYY-MM-DD`. Use this config when you need broader coverage at the cost of reduced metadata richness.

**`legacy` / `metadata` split** (518,601 rows):

| Column | Description |
|---|---|
| `id` | Unique document ID (int) |
| `document_number` | Official number, e.g. `115/NQ-HĐBCQG` |
| `title` | Full Vietnamese title |
| `legal_type` | Document type in English — Resolution, Decision, Circular, … |
| `legal_sectors` | Sector in English — Finance, Education, … |
| `issuing_authority` | Issuing authority (Vietnamese name) |
| `issuance_date` | Issuance date (`YYYY-MM-DD`) |
| `effect_date` | Effective date (`YYYY-MM-DD`) |
| `effectless_date` | Expiry date (empty if still in effect) |
| `effect_status` | `In effect` or `Not in effect` |
| `signers` | Signatory name and ID, e.g. `Trần Thanh Mẫn:2140` |

**`legacy` / `content` split** (518,235 rows):

| Column | Description |
|---|---|
| `id` | Document ID (join key → `legacy/metadata.id`) |
| `content` | Plain-text body of the document |

> **Note:** The `content` column in `legacy` contains plain text, not HTML. The current `content` config stores raw HTML (`content_html`).

```python
from datasets import load_dataset

legacy_meta = load_dataset("th1nhng0/vietnamese-legal-documents", "legacy", split="metadata")
legacy_content = load_dataset("th1nhng0/vietnamese-legal-documents", "legacy", split="content")
```

## Statistics

![Documents by year](charts/docs_by_year.png)

![Document type distribution](charts/legal_type_distribution.png)

![Top issuing authorities](charts/top_authorities.png)

## Data Collection

All data was scraped from [vbpl.vn](https://vbpl.vn) using a [Scrapy](https://scrapy.org/) crawler (included under [`crawler/`](crawler/)). Metadata and cross-document relationships were extracted directly from the portal's structured pages.

```bash
cd crawler

scrapy crawl vbpl -a seed_file=data/ids.txt                          # basic
scrapy crawl vbpl -a seed_file=data/ids.txt -a proxy_file=proxies.txt  # with proxies
scrapy crawl vbpl -a seed_file=data/ids.txt -a resume=1               # resume
```

Output: `data/raw.jsonl`

## Limitations

- Coverage depends on what [vbpl.vn](https://vbpl.vn) has indexed; older or undigitized documents may be missing.
- Effect status reflects the portal at crawl time and may lag behind real-world changes.
- This is a snapshot, not a live mirror. Always cross-check with the portal for authoritative status.

## Privacy

The dataset contains names of document signatories (public officials acting in their official capacity). No private citizen data is included.

## Citation

```bibtex
@dataset{ngo_thinh_2026_vietnamese_legal,
  title     = {Vietnamese Legal Documents},
  author    = {Thịnh Ngô},
  year      = {2026},
  publisher = {Hugging Face},
  url       = {https://huggingface.co/datasets/th1nhng0/vietnamese-legal-documents},
}
```

## License

Vietnamese legal documents are **public domain** under the [Law on Access to Information (No. 104/2016/QH13)](https://chinhphu.vn/default.aspx?pageid=27160&docid=184568) and the [Law on Promulgation of Legal Documents (No. 64/2025/QH15)](https://chinhphu.vn/?pageid=27160&docid=213327&classid=1&typegroupid=3).

The compiled dataset (schema, processing, curation) is released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Not a substitute for legal advice.