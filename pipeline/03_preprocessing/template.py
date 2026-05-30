# %% [markdown]
# <h1 id="setup" style="
#     padding: 15px; 
#     background: linear-gradient(90deg, #ff8c00, #ff4500); 
#     border-left: 5px solid #ff4500; 
#     border-radius: 4px; 
#     box-shadow: 2px 2px 10px rgba(0,0,0,0.5); 
#     color: #ffffff; 
#     font-size: 1.5em; 
#     font-weight: bold; 
#     text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">
#     1. Setup
# </h1>

# %% [code] {"execution":{"iopub.status.busy":"2026-05-24T17:23:02.487003Z","iopub.execute_input":"2026-05-24T17:23:02.487236Z","iopub.status.idle":"2026-05-24T17:23:10.186340Z","shell.execute_reply.started":"2026-05-24T17:23:02.487209Z","shell.execute_reply":"2026-05-24T17:23:10.185214Z"}}
!pip install langchain transformers torch langchain-text-splitters beautifulsoup4 lxml pyarrow -q

# %% [code] {"execution":{"iopub.status.busy":"2026-05-24T17:23:48.007995Z","iopub.execute_input":"2026-05-24T17:23:48.008368Z","iopub.status.idle":"2026-05-24T17:23:51.640974Z","shell.execute_reply.started":"2026-05-24T17:23:48.008325Z","shell.execute_reply":"2026-05-24T17:23:51.640051Z"},"jupyter":{"source_hidden":true},"scrolled":true}
# === Clear RAM ===
import gc

def clear_all(exclude=None):
    """
    Clear CPU + GPU memory
    """
    import gc
    
    if exclude is None:
        exclude = []

    # clear globals
    for name in list(globals().keys()):
        if name.startswith("_") or name in exclude:
            continue
        try:
            del globals()[name]
        except:
            pass

    gc.collect()

    # clear GPU if available
    try:
        import torch
        torch.cuda.empty_cache()
    except:
        pass

clear_all()

# %% [code] {"execution":{"iopub.status.busy":"2026-05-24T17:23:57.640513Z","iopub.execute_input":"2026-05-24T17:23:57.641240Z","iopub.status.idle":"2026-05-24T17:24:25.217298Z","shell.execute_reply.started":"2026-05-24T17:23:57.641202Z","shell.execute_reply":"2026-05-24T17:24:25.216343Z"}}
import hashlib
import re
import uuid
import warnings
from datasets import load_dataset, Features, Value
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from typing import List, Dict, Any
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

import shutil, os

from kaggle_secrets import UserSecretsClient
from huggingface_hub import hf_hub_download

# Lấy token từ Kaggle Secrets
user_secrets = UserSecretsClient()
hf_token = user_secrets.get_secret("HF_TOKEN")

# Thiết lập biến môi trường
os.environ["HF_TOKEN"] = hf_token

# Thay 'vietnamese-legal-documents' bằng tên tập dữ liệu chính xác của bạn trên Kaggle
dataset_path = '/kaggle/input/vietnamese-legal-documents' 

for dirname, _, filenames in os.walk(dataset_path):
    for filename in filenames:
        print(os.path.join(dirname, filename))

# %% [markdown]
# <h1 id="setup" style="padding: 15px; background-color: #1a1a1a; border-left: 5px solid #ffcc33; border-radius: 4px; box-shadow: 2px 2px 10px rgba(0,0,0,0.5); color: #ffcc33; font-size: 1.5em; font-weight: bold; text-shadow: 0 0 8px rgba(255, 204, 51, 0.5);">
#     🚀 1.1. Download Dataset
# </h1>

# %% [code]
# === Legacy ===
# Không cần tải lại vì dataset đã được import qua Kaggle input.

# repo_id = "th1nhng0/vietnamese-legal-documents"
# local_dir = "./"

# hf_hub_download(
#     repo_id=repo_id,
#     filename="legacy/content.parquet",
#     repo_type="dataset",
#     local_dir=local_dir
# )

# hf_hub_download(
#     repo_id=repo_id,
#     filename="legacy/metadata.parquet",
#     repo_type="dataset",
#     local_dir=local_dir
# )

# print("Tải thành công! Kiểm tra các file đang có:")
# print(os.listdir("./legacy"))

# %% [code]
# === Data ===
# Không cần tải lại vì dataset đã được import qua Kaggle input.

# REPO_ID = "th1nhng0/vietnamese-legal-documents"
# REPO_TYPE = "dataset"
# LOCAL_DIR = "/kaggle/working"

# os.makedirs(LOCAL_DIR, exist_ok=True)

# for file in ["data/metadata.parquet", "data/relationships.parquet", "data/content.parquet"]:
#     hf_hub_download(
#         repo_id=REPO_ID,
#         filename=file,
#         repo_type=REPO_TYPE,
#         local_dir=LOCAL_DIR,
#         local_dir_use_symlinks=False,
#     )
#     print(f"Đã tải {file}")

# %% [code]
# === Download Dataset ===
# Không cần export zip trong pipeline preprocessing.

# import zipfile
# import os
# from IPython.display import FileLink, display

# data_dir = "/kaggle/working"
# zip_path = "/kaggle/working/data_export.zip"

# with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
#     for root, _, files in os.walk(data_dir):
#         for file in files:
#             file_path = os.path.join(root, file)
#             arcname = os.path.relpath(file_path, start=os.path.dirname(data_dir))
#             zipf.write(file_path, arcname)

# display(FileLink(zip_path))

# %% [markdown]
# <h1 id="setup" style="padding: 15px; background-color: #1a1a1a; border-left: 5px solid #ffcc33; border-radius: 4px; box-shadow: 2px 2px 10px rgba(0,0,0,0.5); color: #ffcc33; font-size: 1.5em; font-weight: bold; text-shadow: 0 0 8px rgba(255, 204, 51, 0.5);">
#     🚀 1.2. Load Dataset
# </h1>

# %% [code] {"execution":{"iopub.status.busy":"2026-05-24T17:24:59.006874Z","iopub.execute_input":"2026-05-24T17:24:59.007919Z","iopub.status.idle":"2026-05-24T17:25:12.862849Z","shell.execute_reply.started":"2026-05-24T17:24:59.007864Z","shell.execute_reply":"2026-05-24T17:25:12.862001Z"}}
DATA_CONTENT_PATH = '/kaggle/input/datasets/brdh7940/vietnamese-legal-documents/data/content.parquet'
DATA_METADATA_PATH = '/kaggle/input/datasets/brdh7940/vietnamese-legal-documents/data/metadata.parquet'
DATA_RELATIONSHIPS_PATH = '/kaggle/input/datasets/brdh7940/vietnamese-legal-documents/data/relationships.parquet'
LEGACY_CONTENT_PATH = '/kaggle/input/datasets/brdh7940/vietnamese-legal-documents/legacy/content.parquet'
LEGACY_METADATA_PATH = '/kaggle/input/datasets/brdh7940/vietnamese-legal-documents/legacy/metadata.parquet'
STOP_AFTER_PREPROCESSING = True

content = pl.read_parquet(DATA_CONTENT_PATH)
metadata = pl.read_parquet(DATA_METADATA_PATH)
relationships = pl.read_parquet(DATA_RELATIONSHIPS_PATH)

# %% [code] {"execution":{"iopub.status.busy":"2026-05-24T17:25:12.864540Z","iopub.execute_input":"2026-05-24T17:25:12.865567Z","iopub.status.idle":"2026-05-24T17:26:06.182044Z","shell.execute_reply.started":"2026-05-24T17:25:12.865518Z","shell.execute_reply":"2026-05-24T17:26:06.180979Z"}}
legacy_content = pl.read_parquet(LEGACY_CONTENT_PATH)
legacy_metadata = pl.read_parquet(LEGACY_METADATA_PATH)

# %% [markdown]
# <h1 id="setup" style="padding: 15px; background-color: #1a1a1a; border-left: 5px solid #ffcc33; border-radius: 4px; box-shadow: 2px 2px 10px rgba(0,0,0,0.5); color: #ffcc33; font-size: 1.5em; font-weight: bold; text-shadow: 0 0 8px rgba(255, 204, 51, 0.5);">
#     🚀 1.3. Helper Functions
# </h1>

# %% [code] {"jupyter":{"source_hidden":true},"execution":{"iopub.status.busy":"2026-05-21T12:46:03.41839Z","iopub.execute_input":"2026-05-21T12:46:03.419801Z","iopub.status.idle":"2026-05-21T12:46:03.430144Z","shell.execute_reply.started":"2026-05-21T12:46:03.419758Z","shell.execute_reply":"2026-05-21T12:46:03.429307Z"}}
# === Preprocess HTML ===
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
LEGAL_BREAK_RE = re.compile(r"(?=\b(?:Căn cứ|Xét|Theo đề nghị|QUYẾT ĐỊNH|Điều\s+\d+|Chương\s+[IVXLCDM\d]+|Mục\s+\d+|Phần\s+[IVXLCDM\d]+)\b)")


def _looks_like_html(text):
    return bool(HTML_TAG_RE.search(text[:5000]))


def _strip_html_fast(text):
    try:
        soup = BeautifulSoup(text, "lxml")
    except Exception:
        soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["title", "script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _legal_raw_lines(text):
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"(Điều\s+\d+)\s*\n*\s*:", r"\1:", text)
    text = re.sub(r"\s+(?=(?:Điều\s+\d+|Chương\s+[IVXLCDM\d]+|Mục\s+\d+|Phần\s+[IVXLCDM\d]+)\b)", "\n", text)
    lines = []
    for chunk in text.split("\n"):
        chunk = re.sub(r"[ \t\f\v]+", " ", chunk).strip()
        if not chunk:
            continue
        parts = [part.strip() for part in LEGAL_BREAK_RE.split(chunk) if part.strip()]
        lines.extend(parts or [chunk])
    return lines


def _format_legal_lines(raw_lines):
    if not raw_lines:
        return ""

    merged_lines = []
    buffer = raw_lines[0]

    for curr in raw_lines[1:]:
        is_curr_header = curr.isupper() and len(curr) > 3
        is_curr_article = re.match(r"^Điều\s+\d+:", curr)
        is_curr_structural = re.match(r"^(?:Chương|Mục|Phần)\s+[IVXLCDM\d]+", curr)
        is_buffer_header = buffer.isupper() and len(buffer) > 3
        is_buffer_article = re.match(r"^Điều\s+\d+:", buffer)
        is_buffer_structural = re.match(r"^(?:Chương|Mục|Phần)\s+[IVXLCDM\d]+", buffer)
        is_split_word = len(buffer) <= 2
        is_unfinished_sentence = re.search(r"[a-zà-ỹ,;]\s*$", buffer)
        is_next_lowercase = curr[0].islower() if curr else False

        if (is_split_word or is_unfinished_sentence or is_next_lowercase) and not is_curr_header and not is_curr_article and not is_curr_structural and not is_buffer_header and not is_buffer_article and not is_buffer_structural:
            buffer += " " + curr
        else:
            merged_lines.append(buffer)
            buffer = curr

    merged_lines.append(buffer)

    final_output = []
    for line in merged_lines:
        line = re.sub(r"\s+", " ", line).strip()
        is_header = line.isupper() and len(line) > 3
        is_article = re.match(r"^Điều\s+\d+:", line)
        is_structural = re.match(r"^(?:Chương|Mục|Phần)\s+[IVXLCDM\d]+", line)

        if is_header or is_article or is_structural:
            if final_output and final_output[-1] != "":
                final_output.append("")
            final_output.append(line)
            if is_article:
                final_output.append("")
        else:
            final_output.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(final_output)).strip()


def preprocess_legal_text(content):
    if content is None:
        return ""
    text = str(content).strip()
    if not text:
        return ""
    if _looks_like_html(text):
        text = _strip_html_fast(text)
    return _format_legal_lines(_legal_raw_lines(text))

# %% [markdown]
# <h1 id="setup" style="
#     padding: 15px; 
#     background: linear-gradient(90deg, #ff8c00, #ff4500); 
#     border-left: 5px solid #ff4500; 
#     border-radius: 4px; 
#     box-shadow: 2px 2px 10px rgba(0,0,0,0.5); 
#     color: #ffffff; 
#     font-size: 1.5em; 
#     font-weight: bold; 
#     text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">
#     2. Merge
# </h1>

# %% [code] {"execution":{"iopub.status.busy":"2026-05-21T15:37:16.954641Z","iopub.execute_input":"2026-05-21T15:37:16.955105Z","iopub.status.idle":"2026-05-21T15:37:18.118679Z","shell.execute_reply.started":"2026-05-21T15:37:16.954984Z","shell.execute_reply":"2026-05-21T15:37:18.117634Z"}}
import polars as pl
from IPython.display import display, HTML

# 1. CẤU HÌNH HIỂN THỊ CỰC ĐẠI
pl.Config.set_tbl_cols(-1)           # Hiện tất cả các cột
pl.Config.set_fmt_str_lengths(1000)  # Hiện tối đa 1000 ký tự trong mỗi cell
pl.Config.set_tbl_width_chars(2000)  # Tăng độ rộng bảng để không bị nhảy dòng
pl.Config.set_tbl_rows(20)           # Số dòng hiển thị

def print_header(title):
    display(HTML(f"<h2 style='color: #2e7d32; border-bottom: 2px solid #2e7d32; padding-bottom: 5px;'>{title}</h2>"))

# 2. TÌM GIÁ TRỊ CHUNG ĐỂ LÀM MẪU
common_list = legacy_metadata["document_number"].unique().to_list()
common_series = metadata.filter(pl.col("so_ky_hieu").is_in(common_list)).select("so_ky_hieu").head(1)

if common_series.height > 0:
    common_val = common_series.item()
    id_current = metadata.filter(pl.col("so_ky_hieu") == common_val).select("id").head(1).item()
    id_legacy = legacy_metadata.filter(pl.col("document_number") == common_val).select("id").head(1).item()
else:
    common_val = None
    id_current = id_legacy = None

# 3. HÀM HIỂN THỊ SAMPLE ROW
def show_sample(df, name, filter_col=None, filter_val=None):
    print_header(f"SAMPLE VIEW: {name.upper()}")
    if filter_col and filter_val is not None:
        target_dtype = df.schema[filter_col]
        try:
            sample_df = df.filter(pl.col(filter_col) == pl.lit(filter_val).cast(target_dtype)).head(1)
            print(f"Hiển thị bản ghi có {filter_col} = '{filter_val}':")
        except:
            sample_df = df.head(1)
            print(f"Lỗi lọc dữ liệu, hiển thị dòng đầu tiên:")
    else:
        sample_df = df.head(1)
        print(f"Hiển thị dòng đầu tiên:")
    
    display(sample_df)

# --- THỰC THI HIỂN THỊ SAMPLE ---
if common_val:
    show_sample(metadata, "Metadata Current (Bản mới)", "so_ky_hieu", common_val)
    show_sample(legacy_metadata, "Metadata Legacy (Bản cũ)", "document_number", common_val)
    show_sample(content, "Content Current", "id", id_current)
    show_sample(legacy_content, "Content Legacy", "id", id_legacy)
else:
    show_sample(metadata, "Metadata Current")
    show_sample(legacy_metadata, "Metadata Legacy")
    show_sample(content, "Content Current")
    show_sample(legacy_content, "Content Legacy")

# 4. PHÂN TÍCH TRÙNG LẶP ID GIỮA CURRENT VÀ LEGACY
print_header("ID OVERLAP ANALYSIS (CURRENT vs LEGACY)")

def analyze_ids(df_curr, df_leg, name):
    curr_ids = set(df_curr["id"].unique())
    leg_ids = set(df_leg["id"].unique())
    overlap = len(curr_ids.intersection(leg_ids))
    
    display(pl.DataFrame({
        "Dataset": [name],
        "Total Current IDs": [len(curr_ids)],
        "Total Legacy IDs": [len(leg_ids)],
        "Overlapping IDs (Trùng)": [overlap],
        "Merge Suggestion": ["Cần drop_duplicates" if overlap > 0 else "Có thể concat trực tiếp"]
    }))

analyze_ids(metadata, legacy_metadata, "METADATA")
analyze_ids(content, legacy_content, "CONTENT")

# 5. KIỂM TRA TÍNH NHẤT QUÁN (METADATA vs CONTENT)
print_header("CONSISTENCY CHECK (METADATA <=> CONTENT)")

def check_orphans(meta, cont, name):
    meta_ids = set(meta["id"])
    cont_ids = set(cont["id"])
    
    orphans_meta = len(meta_ids - cont_ids)
    orphans_cont = len(cont_ids - meta_ids)
    
    display(pl.DataFrame({
        "Scope": [name],
        "Missing in Content": [orphans_meta],
        "Missing in Metadata": [orphans_cont],
        "Status": ["OK" if orphans_meta == 0 and orphans_cont == 0 else "Data Gap Detected"]
    }))

check_orphans(metadata, content, "CURRENT Set")
check_orphans(legacy_metadata, legacy_content, "LEGACY Set")

# %% [code]
# === MERGE: legacy làm gốc, bổ sung dữ liệu từ data ===
# Không join theo id vì EDA cho thấy id giữa 2 nguồn không cùng không gian định danh.
OUTPUT_DIR = "/kaggle/working/preprocessed"
os.makedirs(OUTPUT_DIR, exist_ok=True)

COL_MAP = {
    "so_ky_hieu": "document_number",
    "title": "title",
    "loai_van_ban": "legal_type",
    "co_quan_ban_hanh": "issuing_authority",
    "ngay_ban_hanh": "issuance_date",
    "ngay_co_hieu_luc": "effect_date",
    "ngay_het_hieu_luc": "effectless_date",
    "tinh_trang_hieu_luc": "effect_status",
    "nguoi_ky": "signers",
}

def _clean_expr(col):
    x = pl.col(col).cast(pl.Utf8, strict=False).str.replace_all(r"\s+", " ").str.strip_chars()
    return pl.when(x == "").then(None).otherwise(x)

def _date_expr(col):
    x = _clean_expr(col)
    return pl.coalesce(
        x.str.strptime(pl.Date, "%d/%m/%Y", strict=False),
        x.str.strptime(pl.Date, "%Y-%m-%d", strict=False),
    ).dt.strftime("%Y-%m-%d")

def _ensure_cols(df, cols):
    for c in cols:
        if c not in df.columns:
            df = df.with_columns(pl.lit(None).cast(pl.Utf8).alias(c))
    return df

def _add_key(df, cols):
    df = df.with_columns([_clean_expr(c).str.to_lowercase().alias(f"__k_{c}") for c in cols])
    key_parts = [pl.col(f"__k_{c}") for c in cols]
    has_key = pl.all_horizontal([p.is_not_null() for p in key_parts])
    return df.with_columns(
        pl.when(has_key).then(pl.concat_str(key_parts, separator="||")).otherwise(None).alias("join_key")
    ).drop([f"__k_{c}" for c in cols])

LEGAL_TYPE_MAP = {
    "Decision": "Quyết định",
    "Quyết định": "Quyết định",
    "Official Dispatch": "Công văn",
    "Công văn": "Công văn",
    "Resolution": "Nghị quyết",
    "Nghị quyết": "Nghị quyết",
    "Nghị Quyết": "Nghị quyết",
    "Announcement": "Thông báo",
    "Thông báo": "Thông báo",
    "Kế hoạch": "Kế hoạch",
    "Directive": "Chỉ thị",
    "Chỉ thị": "Chỉ thị",
    "Circular": "Thông tư",
    "Thông tư": "Thông tư",
    "Joint circular": "Thông tư liên tịch",
    "Thông tư liên tịch": "Thông tư liên tịch",
    "Instruction": "Hướng dẫn",
    "Integrated document": "Văn bản hợp nhất",
    "Văn bản hợp nhất": "Văn bản hợp nhất",
    "Official Telegram": "Công điện",
    "National Treaty": "Điều ước quốc tế",
    "Treaty": "Điều ước quốc tế",
    "Convention": "Công ước",
    "Công ước": "Công ước",
    "Agreement": "Hiệp định",
    "Hiệp định": "Hiệp định",
    "Protocal": "Nghị định thư",
    "Nghị định thư": "Nghị định thư",
    "Decree of Government": "Nghị định",
    "Nghị định": "Nghị định",
    "Order": "Lệnh",
    "Lệnh": "Lệnh",
    "Decree-Order": "Sắc lệnh",
    "Sắc lệnh": "Sắc lệnh",
    "Decree-Law": "Sắc luật",
    "Sắc luật": "Sắc luật",
    "Law": "Luật",
    "Luật": "Luật",
    "Statute": "Quy chế",
    "Bộ luật": "Bộ luật",
    "Ordinance": "Pháp lệnh",
    "Pháp lệnh": "Pháp lệnh",
    "Regulation": "Quy định",
    "Standing Rules": "Điều lệ",
    "Constitution": "Hiến pháp",
    "Other Documents": "Văn bản khác",
    "Văn bản khác": "Văn bản khác",
    "Documents about WTO": "Văn bản WTO",
    "WTO Documents": "Văn bản WTO",
    "WTO_Undertaken by Vietnam": "Cam kết WTO của Việt Nam",
    "Văn bản liên quan": "Văn bản liên quan",
    "Tiêu chuẩn Việt Nam": "Tiêu chuẩn Việt Nam",
    "Tiêu chuẩn ngành": "Tiêu chuẩn ngành",
    "Tiêu chuẩn XDVN": "Tiêu chuẩn xây dựng Việt Nam",
    "Nghị quyết liên tịch": "Nghị quyết liên tịch",
    "Thông tư liên bộ": "Thông tư liên bộ",
    "Chương trình": "Chương trình",
    "Báo cáo": "Báo cáo",
}

LEGAL_SECTOR_MAP = {
    "Administrative apparatus": "Bộ máy hành chính",
    "Taxes - Fees - Charges": "Thuế, phí, lệ phí",
    "Government finance": "Tài chính nhà nước",
    "Culture - Society": "Văn hóa - xã hội",
    "Export & Import": "Xuất nhập khẩu",
    "Natural resources – Environment": "Tài nguyên - môi trường",
    "Construction – Urban Planning": "Xây dựng - đô thị",
    "Trade": "Thương mại",
    "Real estate": "Bất động sản",
    "Sports - Health": "Thể thao - y tế",
    "Education": "Giáo dục",
    "Transport": "Giao thông vận tải",
    "Business": "Doanh nghiệp",
    "Employment - Wages": "Lao động - tiền lương",
    "Investment": "Đầu tư",
    "Information technology": "Công nghệ thông tin",
    "Other": "Khác",
    "Accounting - Audit": "Kế toán - kiểm toán",
    "Civil rights": "Quyền dân sự",
    "Banking - Finance": "Ngân hàng - tài chính",
    "Insurance": "Bảo hiểm",
    "Legal services": "Dịch vụ pháp lý",
    "Administrative violations": "Vi phạm hành chính",
    "Proceedings": "Tố tụng",
    "Criminal liability": "Trách nhiệm hình sự",
    "Intellectual property": "Sở hữu trí tuệ",
    "Securities": "Chứng khoán",
}

EFFECT_STATUS_MAP = {
    "In effect": "Còn hiệu lực",
    "Còn hiệu lực": "Còn hiệu lực",
    "Expired": "Hết hiệu lực",
    "Hết hiệu lực toàn bộ": "Hết hiệu lực",
    "No longer applicable": "Hết hiệu lực",
    "Không còn phù hợp": "Hết hiệu lực",
    "Hết hiệu lực một phần": "Hết hiệu lực một phần",
    "Ngưng hiệu lực": "Ngưng hiệu lực",
    "Ngưng hiệu lực một phần": "Ngưng hiệu lực một phần",
    "Chưa có hiệu lực": "Chưa có hiệu lực",
    "Unknown": None,
    "Chưa xác định": None,
    "Undetermined": None,
}


def _map_dict_expr(col, mapping):
    return pl.col(col).replace_strict(mapping, default=pl.col(col))


def _normalize_legal_sectors_expr(col):
    return pl.col(col).map_elements(
        lambda value: None if value is None else ", ".join(
            dict.fromkeys(LEGAL_SECTOR_MAP.get(part.strip(), part.strip()) for part in str(value).split(",") if part.strip())
        ),
        return_dtype=pl.Utf8,
    )

legacy_cols = [
    "id", "document_number", "title", "legal_type", "legal_sectors",
    "issuing_authority", "issuance_date", "effect_date", "effectless_date",
    "effect_status", "signers",
]
legacy_metadata_std = _ensure_cols(legacy_metadata, legacy_cols).select(legacy_cols)
legacy_text_cols = [c for c in legacy_cols if c not in ["id", "issuance_date", "effect_date", "effectless_date"]]
legacy_metadata_std = legacy_metadata_std.with_columns(
    pl.col("id").cast(pl.Int64, strict=False),
    *[_clean_expr(c).alias(c) for c in legacy_text_cols],
    _date_expr("issuance_date").alias("issuance_date"),
    _date_expr("effect_date").alias("effect_date"),
    _date_expr("effectless_date").alias("effectless_date"),
)

data_extra_cols = ["nguon_thu_thap", "ngay_dang_cong_bao", "nganh", "linh_vuc", "chuc_danh", "pham_vi", "thong_tin_ap_dung"]
data_text_cols = [c for c in COL_MAP.values() if c not in ["issuance_date", "effect_date", "effectless_date"]]
data_extra_text_cols = [c for c in data_extra_cols if c != "ngay_dang_cong_bao"]
metadata_std = metadata.rename({k: v for k, v in COL_MAP.items() if k in metadata.columns})
metadata_std = _ensure_cols(metadata_std, ["id", *COL_MAP.values(), *data_extra_cols]).select(["id", *COL_MAP.values(), *data_extra_cols])
metadata_std = metadata_std.with_columns(
    pl.col("id").cast(pl.Int64, strict=False).alias("data_id"),
    *[_clean_expr(c).alias(c) for c in data_text_cols],
    *[_clean_expr(c).alias(c) for c in data_extra_text_cols],
    _date_expr("issuance_date").alias("issuance_date"),
    _date_expr("effect_date").alias("effect_date"),
    _date_expr("effectless_date").alias("effectless_date"),
    _date_expr("ngay_dang_cong_bao").alias("ngay_dang_cong_bao"),
).drop("id")

JOIN_COLS = ["document_number", "issuance_date"]
legacy_keyed = _add_key(legacy_metadata_std, JOIN_COLS)
data_keyed = _add_key(metadata_std, JOIN_COLS)

# Chỉ nhận key one-to-one để tránh nhân dòng hoặc match sai với các số ký hiệu trùng nhiều nơi.
valid_keys = (
    legacy_keyed.group_by("join_key").agg(pl.len().alias("n_legacy"))
    .join(data_keyed.group_by("join_key").agg(pl.len().alias("n_data")), on="join_key", how="inner")
    .filter((pl.col("join_key").is_not_null()) & (pl.col("n_legacy") == 1) & (pl.col("n_data") == 1))
    .select("join_key")
)

data_for_join = data_keyed.join(valid_keys, on="join_key", how="inner").select(
    "join_key", "data_id",
    *[pl.col(c).alias(f"data_{c}") for c in COL_MAP.values()],
    *data_extra_cols,
)

merged_metadata_raw = legacy_keyed.join(data_for_join, on="join_key", how="left")

crosswalk = merged_metadata_raw.filter(pl.col("data_id").is_not_null()).select(
    pl.col("id").alias("legacy_id"), "data_id", "join_key"
)

DATA_ONLY_ID_OFFSET = 10_000_000_000
matched_data_ids = crosswalk.select("data_id")

data_only_keyed = data_keyed.join(matched_data_ids, on="data_id", how="anti")

legacy_lineage = merged_metadata_raw.select(
    pl.col("id").alias("merged_id"),
    pl.col("id").alias("legacy_id"),
    "data_id",
    "join_key",
    pl.when(pl.col("data_id").is_not_null()).then(pl.lit("legacy+data")).otherwise(pl.lit("legacy")).alias("source"),
)
data_only_lineage = data_only_keyed.select(
    (pl.lit(DATA_ONLY_ID_OFFSET) + pl.col("data_id")).alias("merged_id"),
    pl.lit(None).cast(pl.Int64).alias("legacy_id"),
    "data_id",
    "join_key",
    pl.lit("data").alias("source"),
)
document_lineage = pl.concat([legacy_lineage, data_only_lineage], how="vertical_relaxed")

legacy_merged_metadata = merged_metadata_raw.select(
    pl.col("id"),
    pl.coalesce("data_document_number", "document_number").alias("document_number"),
    pl.coalesce("data_title", "title").alias("title"),
    pl.coalesce("data_legal_type", "legal_type").alias("legal_type"),
    pl.coalesce("linh_vuc", "nganh", "legal_sectors").alias("legal_sectors"),
    pl.coalesce("data_issuing_authority", "issuing_authority").alias("issuing_authority"),
    pl.coalesce("data_issuance_date", "issuance_date").alias("issuance_date"),
    pl.coalesce("data_effect_date", "effect_date").alias("effect_date"),
    pl.coalesce("data_effectless_date", "effectless_date").alias("effectless_date"),
    pl.coalesce("data_effect_status", "effect_status").alias("effect_status"),
    pl.coalesce("data_signers", "signers").alias("signers"),
    *data_extra_cols,
    pl.when(pl.col("data_id").is_not_null()).then(pl.lit("legacy+data")).otherwise(pl.lit("legacy")).alias("source"),
)

data_only_metadata = data_only_keyed.select(
    (pl.lit(DATA_ONLY_ID_OFFSET) + pl.col("data_id")).alias("id"),
    "document_number",
    "title",
    "legal_type",
    pl.coalesce("linh_vuc", "nganh").alias("legal_sectors"),
    "issuing_authority",
    "issuance_date",
    "effect_date",
    "effectless_date",
    "effect_status",
    "signers",
    *data_extra_cols,
    pl.lit("data").alias("source"),
)

merged_metadata = pl.concat([legacy_merged_metadata, data_only_metadata], how="vertical_relaxed").with_columns(
    _map_dict_expr("legal_type", LEGAL_TYPE_MAP).alias("legal_type"),
    _normalize_legal_sectors_expr("legal_sectors").alias("legal_sectors"),
    _map_dict_expr("effect_status", EFFECT_STATUS_MAP).alias("effect_status"),
)

# Tối ưu RAM/CPU: ghi candidate content ra parquet tạm, clean mỗi document tối đa một lần.
metadata_rank = merged_metadata.select(
    "id",
    "source",
    pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int32) for c in merged_metadata.columns if c != "id"]).alias("metadata_non_nulls"),
)
metadata_source_by_id = {row["id"]: row["source"] for row in metadata_rank.select("id", "source").iter_rows(named=True)}
metadata_score_by_id = {row["id"]: row["metadata_non_nulls"] for row in metadata_rank.select("id", "metadata_non_nulls").iter_rows(named=True)}
data_to_merged = {
    row["data_id"]: (row["merged_id"], row["source"])
    for row in document_lineage.filter(pl.col("data_id").is_not_null()).select("data_id", "merged_id", "source").iter_rows(named=True)
}


def _normalize_legacy_content(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _flush_rows(writer, rows, schema):
    if rows:
        writer.write_table(pa.Table.from_pylist(rows, schema=schema))
        rows.clear()


CHUNK_SIZE = 2000
candidate_path = f"{OUTPUT_DIR}/content_candidates.parquet"
content_out_path = f"{OUTPUT_DIR}/merged_content.parquet"
content_schema = pa.schema([
    ("id", pa.int64()),
    ("content", pa.string()),
    ("source", pa.string()),
])

candidate_writer = pq.ParquetWriter(candidate_path, content_schema, compression="zstd")
buffer = []
data_candidate_merged_ids = set()
try:
    for batch in pq.ParquetFile(DATA_CONTENT_PATH).iter_batches(batch_size=CHUNK_SIZE, columns=["id", "content_html"]):
        for row in batch.to_pylist():
            data_id = None if row["id"] is None else int(row["id"])
            target = data_to_merged.get(data_id)
            if target is None:
                continue
            merged_id, source = target
            normalized_content = preprocess_legal_text(row["content_html"])
            if not normalized_content:
                continue
            data_candidate_merged_ids.add(merged_id)
            buffer.append({"id": merged_id, "content": normalized_content, "source": source})
            if len(buffer) >= CHUNK_SIZE:
                _flush_rows(candidate_writer, buffer, content_schema)

    for batch in pq.ParquetFile(LEGACY_CONTENT_PATH).iter_batches(batch_size=CHUNK_SIZE, columns=["id", "content"]):
        for row in batch.to_pylist():
            doc_id = None if row["id"] is None else int(row["id"])
            if metadata_source_by_id.get(doc_id) is None or doc_id in data_candidate_merged_ids:
                continue
            normalized_content = _normalize_legacy_content(row["content"])
            if not normalized_content:
                continue
            buffer.append({"id": doc_id, "content": normalized_content, "source": "legacy"})
            if len(buffer) >= CHUNK_SIZE:
                _flush_rows(candidate_writer, buffer, content_schema)

    _flush_rows(candidate_writer, buffer, content_schema)
finally:
    candidate_writer.close()

best_by_hash = {}
for batch in pq.ParquetFile(candidate_path).iter_batches(batch_size=CHUNK_SIZE):
    for row in batch.to_pylist():
        doc_id = row["id"]
        content_hash = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
        source_priority = {"legacy": 0, "data": 1, "legacy+data": 2}.get(row["source"], 0)
        candidate = (metadata_score_by_id.get(doc_id, 0), source_priority, -doc_id, doc_id, row["source"])
        if content_hash not in best_by_hash or candidate > best_by_hash[content_hash]:
            best_by_hash[content_hash] = candidate

winning_content_keys = {(item[3], content_hash) for content_hash, item in best_by_hash.items()}
valid_content_ids = {doc_id for doc_id, _ in winning_content_keys}
valid_merged_ids = pl.DataFrame({"id": list(valid_content_ids)}, schema={"id": pl.Int64})
merged_metadata = merged_metadata.join(valid_merged_ids, on="id", how="inner")
document_lineage = document_lineage.join(valid_merged_ids.rename({"id": "merged_id"}), on="merged_id", how="inner")
crosswalk = crosswalk.join(
    document_lineage.filter(pl.col("legacy_id").is_not_null() & pl.col("data_id").is_not_null()).select("legacy_id", "data_id"),
    on=["legacy_id", "data_id"],
    how="inner",
)

merged_metadata.write_parquet(f"{OUTPUT_DIR}/merged_metadata.parquet")
crosswalk.write_parquet(f"{OUTPUT_DIR}/data_to_legacy_crosswalk.parquet")
document_lineage.write_parquet(f"{OUTPUT_DIR}/document_lineage.parquet")

output_writer = pq.ParquetWriter(content_out_path, content_schema, compression="zstd")
buffer = []
try:
    for batch in pq.ParquetFile(candidate_path).iter_batches(batch_size=CHUNK_SIZE):
        for row in batch.to_pylist():
            content_hash = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
            if (row["id"], content_hash) not in winning_content_keys:
                continue
            buffer.append(row)
            if len(buffer) >= CHUNK_SIZE:
                _flush_rows(output_writer, buffer, content_schema)
    _flush_rows(output_writer, buffer, content_schema)
finally:
    output_writer.close()

merged_content = pl.scan_parquet(content_out_path).select("id", "source")

# Giải phóng RAM cho content sau khi merge xong
for name in ["content", "legacy_content", "best_by_hash", "buffer", "data_candidate_merged_ids"]:
    if name in globals():
        del globals()[name]
import gc
gc.collect()

display(pl.DataFrame({
    "metric": [
        "legacy rows",
        "data rows",
        "matched one-to-one rows after content filter",
        "data-only rows after content filter",
        "merged metadata rows",
    ],
    "value": [
        legacy_metadata.height,
        metadata.height,
        crosswalk.height,
        document_lineage.filter(pl.col("source") == "data").height,
        merged_metadata.height,
    ],
}))

# %% [code]
# === MERGE RELATIONSHIPS: remap data_id → merged_id ===
# relationships dùng doc_id/other_doc_id thuộc không gian ID của data.
# Cần remap sang merged_id qua document_lineage để giữ cả matched và data-only.

rels = relationships.with_columns(
    pl.col("doc_id").cast(pl.Int64, strict=False),
    pl.col("other_doc_id").cast(pl.Int64, strict=False),
)

# Bảng lookup đầy đủ: data_id → merged_id, gồm cả matched và data-only.
src_lookup = document_lineage.filter(pl.col("data_id").is_not_null()).select(
    pl.col("data_id").alias("doc_id"),
    pl.col("merged_id").alias("src_merged_id"),
)
tgt_lookup = document_lineage.filter(pl.col("data_id").is_not_null()).select(
    pl.col("data_id").alias("other_doc_id"),
    pl.col("merged_id").alias("tgt_merged_id"),
)

# Remap nghiêm ngặt: chỉ giữ edges khi cả hai đầu đều tồn tại trong merged output.
merged_rels_strict = (
    rels
    .join(src_lookup, on="doc_id", how="inner")
    .join(tgt_lookup, on="other_doc_id", how="inner")
    .select([
        pl.col("src_merged_id").alias("doc_id_final"),
        pl.col("tgt_merged_id").alias("other_doc_id_final"),
        "relationship"
    ])
)

# Lọc: chỉ giữ edges mà CẢ HAI đầu tồn tại trong merged output
valid_ids = merged_metadata.select("id")
merged_rels_valid = (
    merged_rels_strict
    .join(valid_ids.rename({"id": "doc_id_final"}), on="doc_id_final", how="semi")
    .join(valid_ids.rename({"id": "other_doc_id_final"}), on="other_doc_id_final", how="semi")
)

# Loại self-loop + dedup
merged_rels_clean = (
    merged_rels_valid
    .filter(pl.col("doc_id_final") != pl.col("other_doc_id_final"))
    .select(
        pl.col("doc_id_final").alias("doc_id"),
        pl.col("other_doc_id_final").alias("other_doc_id"),
        "relationship",
    )
    .unique(subset=["doc_id", "other_doc_id", "relationship"])
)

merged_rels_clean.write_parquet(f"{OUTPUT_DIR}/merged_relationships.parquet")

display(pl.DataFrame({
    "metric": [
        "original edges",
        "edges after strict map (both ends valid)",
        "edges final (dedup, no self-loop)",
        "dropped edges (unmapped or self-loop)",
    ],
    "value": [
        relationships.height,
        merged_rels_strict.height,
        merged_rels_clean.height,
        relationships.height - merged_rels_clean.height,
    ],
}))

if STOP_AFTER_PREPROCESSING:
    raise SystemExit("Preprocessing outputs written; stopping before EDA/chunk demo cells.")

# %% [markdown]
# <h1 id="setup" style="
#     padding: 15px; 
#     background: linear-gradient(90deg, #ff8c00, #ff4500); 
#     border-left: 5px solid #ff4500; 
#     border-radius: 4px; 
#     box-shadow: 2px 2px 10px rgba(0,0,0,0.5); 
#     color: #ffffff; 
#     font-size: 1.5em; 
#     font-weight: bold; 
#     text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">
#     3. EDA
# </h1>

# %% [code] {"execution":{"iopub.status.busy":"2026-05-21T08:34:52.065151Z","iopub.execute_input":"2026-05-21T08:34:52.065473Z","iopub.status.idle":"2026-05-21T08:35:05.443055Z","shell.execute_reply.started":"2026-05-21T08:34:52.065445Z","shell.execute_reply":"2026-05-21T08:35:05.44205Z"}}
num_samples = 1

for i, sample in enumerate(content.head(num_samples).to_dicts()):
    raw_html = sample['content_html']
    cleaned_text = preprocess_legal_text(raw_html)

    print("\n" + "="*80)
    print(f" SAMPLE {i+1} - ID: {sample['id']}")
    print("="*80)

    print("\n👉 [BEFORE - RAW HTML (Trích đoạn 200 ký tự đầu)]:")
    print(raw_html[:200] + "...")

    print("\n👉 [AFTER - CLEANED TEXT]:")
    print("-" * 40)
    print(cleaned_text)
    print("-" * 40)

# %% [markdown]
# <h1 id="setup" style="
#     padding: 15px; 
#     background: linear-gradient(90deg, #ff8c00, #ff4500); 
#     border-left: 5px solid #ff4500; 
#     border-radius: 4px; 
#     box-shadow: 2px 2px 10px rgba(0,0,0,0.5); 
#     color: #ffffff; 
#     font-size: 1.5em; 
#     font-weight: bold; 
#     text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">
#     4. Chunk
# </h1>

# %% [code] {"execution":{"iopub.status.busy":"2026-05-21T08:40:14.36275Z","iopub.execute_input":"2026-05-21T08:40:14.363578Z","iopub.status.idle":"2026-05-21T08:40:28.277211Z","shell.execute_reply.started":"2026-05-21T08:40:14.363544Z","shell.execute_reply":"2026-05-21T08:40:28.276054Z"}}
def legal_structural_splitter(doc_data: Dict[str, Any], max_chunk_size: int = 1500) -> List[Document]:
    """
    Chia văn bản pháp luật thành các chunk độc lập:
    - Mỗi chunk gồm một hoặc nhiều Điều hoàn chỉnh.
    - TUYỆT ĐỐI KHÔNG chồng lấn (no overlap).
    - TUYỆT ĐỐI KHÔNG cắt ngang Điều.
    - page_content chỉ chứa nội dung gốc.
    """
    content = doc_data.get('content_cleaned', '')
    doc_id = doc_data.get('id', 'N/A')
    title = doc_data.get('title', 'N/A')
    so_ky_hieu = doc_data.get('so_ky_hieu', 'N/A')

    # 1. Tách văn bản thành danh sách các đơn vị nội dung gốc (Intro, Điều)
    pattern = r'(?m)^((?:Chương|Mục|Phần|Điều(?: thứ)?)\s+[IVXLCDM\d]+[a-z]?|[IVXLCDM]+\.)[.:]?\s*(.*)$'
    matches = list(re.finditer(pattern, content))
    
    all_units = []
    
    # Lời nói đầu
    matches = list(re.finditer(pattern, content))
    all_units = []

    if not matches:
        # FALLBACK: Nếu không có cấu trúc Điều/La Mã, tách theo đoạn trắng (\n\n)
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        for idx, p in enumerate(paragraphs):
            all_units.append({"raw_text": p, "id_label": f"Para_{idx+1}"})
    else:
        # Giữ nguyên logic cũ nhưng dùng Regex mới
        first_match_start = matches[0].start()
        intro_text = content[:first_match_start].strip()
        if intro_text:
            all_units.append({"raw_text": intro_text, "id_label": "Intro"})

        for i, match in enumerate(matches):
            h_type = match.group(1).strip()
            h_title = match.group(2).strip()
            start = match.end()
            end = matches[i+1].start() if i+1 < len(matches) else len(content)
            
            raw_header = f"{h_type}" + (f" {h_title}" if h_title else "")
            body = content[start:end].strip()
            
            all_units.append({
                "raw_text": f"{raw_header}\n{body}".strip(),
                "id_label": h_type
            })
            
    # 2. Gom nhóm vào các Chunk ĐỘC LẬP
    chunks = []
    current_chunk_texts = []
    current_char_count = 0
    included_labels = []

    for unit in all_units:
        unit_text = unit["raw_text"]
        unit_len = len(unit_text)
        
        # Nếu thêm unit này vào mà vượt giới hạn (và chunk hiện tại đã có nội dung)
        if current_char_count + unit_len > max_chunk_size and current_chunk_texts:
            # Đóng chunk hiện tại
            final_content = "\n\n".join(current_chunk_texts)
            metadata = {
                "id": doc_id,
                "title": title,
                "so_ky_hieu": so_ky_hieu,
                "chunk_type": "legal_independent_chunk",
                "included_articles": included_labels
            }
            chunks.append(Document(page_content=final_content, metadata=metadata))
            
            # Reset cho chunk mới
            current_chunk_texts = []
            current_char_count = 0
            included_labels = []
        
        # Thêm unit vào buffer của chunk hiện tại
        current_chunk_texts.append(unit_text)
        current_char_count += unit_len + 2 # +2 cho dấu nối \n\n
        included_labels.append(unit["id_label"])

    # Đóng chunk cuối cùng (nếu còn dư)
    if current_chunk_texts:
        final_content = "\n\n".join(current_chunk_texts)
        metadata = {
            "id": doc_id,
            "title": title,
            "so_ky_hieu": so_ky_hieu,
            "chunk_type": "legal_independent_chunk",
            "included_articles": included_labels
        }
        chunks.append(Document(page_content=final_content, metadata=metadata))

    return chunks
    
# =================================================================
# 2. CHẠY VÀ HIỂN THỊ TOÀN BỘ NỘI DUNG
# =================================================================

for sample in content.head(1).to_dicts():
    doc_info = {
        "id": sample.get('id'),
        "title": sample.get('title', 'N/A'),
        "so_ky_hieu": sample.get('so_ky_hieu', 'N/A'),
        "content_cleaned": preprocess_legal_text(sample['content_html'])
    }

    final_chunks = legal_structural_splitter(doc_info, max_chunk_size=1500)

    print("\n" + "="*80)
    print(f"🔥 KẾT QUẢ CHUNK CHO: {doc_info['content_cleaned']}")
    print(f"📦 Tổng số chunk tạo ra: {len(final_chunks)}")
    print("="*80)

    for i, chunk in enumerate(final_chunks):
        print(f"\n[CHUNK {i+1} - Loại: {chunk.metadata['chunk_type']}]")
        print("-" * 40)
        print(chunk.page_content) # In toàn bộ nội dung chunk
        print("-" * 40)

    print("\n\n")

# %% [code] {"execution":{"iopub.status.busy":"2026-05-21T08:40:28.27851Z","iopub.execute_input":"2026-05-21T08:40:28.278824Z","iopub.status.idle":"2026-05-21T08:40:42.780979Z","shell.execute_reply.started":"2026-05-21T08:40:28.278786Z","shell.execute_reply":"2026-05-21T08:40:42.779437Z"}}
import unicodedata
import pandas as pd

def norm_text(text):
    """Hàm bổ trợ để chuẩn hóa font Tiếng Việt và xóa khoảng trắng thừa"""
    if not text: return ""
    return unicodedata.normalize('NFC', str(text)).strip()

print("⏳ Đang lập chỉ mục Metadata để tra cứu...")

meta_lookup = {}
for row in metadata.select(["id", "loai_van_ban", "title", "so_ky_hieu"]).iter_rows(named=True):
    doc_id = str(row["id"])
    raw_type = row.get("loai_van_ban")
    label = "" if raw_type is None else str(raw_type)

    meta_lookup[doc_id] = {
        "loai_van_ban": norm_text(label),
        "title": row.get("title"),
        "so_ky_hieu": row.get("so_ky_hieu")
    }

print(f"✅ Đã lập chỉ mục xong {len(meta_lookup)} tài liệu.")

# =================================================================
# 2. CHỈNH SỬA DANH SÁCH TARGET (Đã bọc trong chuẩn hóa)
# =================================================================
target_types = [norm_text(t) for t in [
    "Quyết định", "Sắc lệnh", "Nghị quyết", "Thông tư", 
    "Chỉ thị", "Nghị định", "Luật", "Công văn"
]]

# %% [code] {"execution":{"iopub.status.busy":"2026-05-21T08:40:42.782423Z","iopub.execute_input":"2026-05-21T08:40:42.782745Z","iopub.status.idle":"2026-05-21T08:40:57.670888Z","shell.execute_reply.started":"2026-05-21T08:40:42.782715Z","shell.execute_reply":"2026-05-21T08:40:57.670131Z"}}

# =================================================================
# 3. QUÉT content VÀ CHẠY THỬ NGHIỆM
# =================================================================
samples_found = {}
print("\n⏳ Đang quét content stream để tìm mẫu đại diện...")

target_ids_by_type = {}
for row in metadata.select(["id", "loai_van_ban", "title", "so_ky_hieu"]).iter_rows(named=True):
    doc_id = str(row["id"])
    doc_type = norm_text(row.get("loai_van_ban"))

    if doc_type in target_types and doc_type not in target_ids_by_type:
        target_ids_by_type[doc_type] = {
            "id": doc_id,
            "title": row.get("title"),
            "so_ky_hieu": row.get("so_ky_hieu"),
        }

    if len(target_ids_by_type) == len(target_types):
        break

if target_ids_by_type:
    target_ids = [data["id"] for data in target_ids_by_type.values()]
    content_samples = {
        str(row["id"]): row["content_html"]
        for row in (
            content
            .with_columns(pl.col("id").cast(pl.Utf8, strict=False).alias("id_str"))
            .filter(pl.col("id_str").is_in(target_ids))
            .select(["id", "content_html"])
            .iter_rows(named=True)
        )
    }

    for doc_type, data in target_ids_by_type.items():
        content_html = content_samples.get(data["id"])
        if content_html is None:
            continue

        samples_found[doc_type] = {**data, "content_html": content_html}
        print(f" -> Đã tìm thấy: {doc_type}")

# 4. XỬ LÝ VÀ HIỂN THỊ KẾT QUẢ
MAX_PREVIEW_CHARS = 2000
MAX_CHUNKS_TO_DISPLAY = 3

if not samples_found:
    print("❌ Vẫn không tìm thấy mẫu nào! Hãy kiểm tra print(meta_lookup) xem ID có dạng gì.")
else:
    print(f"✅ Đã lấy đủ {len(samples_found)} mẫu. Bắt đầu quá trình chunking...\n")

    results_summary = []
    for doc_type, data in samples_found.items():
        content_cleaned = preprocess_legal_text(data['content_html'])
        doc_info = {**data, "content_cleaned": content_cleaned, "loai_van_ban": doc_type}
        chunks = legal_structural_splitter(doc_info, max_chunk_size=1500)

        results_summary.append({
            "Loại văn bản": doc_type,
            "Số lượng chunks": len(chunks),
            "Chunk types": list(set([c.metadata.get('chunk_type', 'N/A') for c in chunks]))
        })

        print("="*80)
        print(f"📄 VĂN BẢN GỐC (ĐÃ CLEAN) - LOẠI: {doc_type.upper()}")
        print("-" * 30)
        print(content_cleaned[:MAX_PREVIEW_CHARS] + ("..." if len(content_cleaned) > MAX_PREVIEW_CHARS else ""))
        print("-" * 30)
        print(f"\n🔥 DANH SÁCH {len(chunks)} CHUNKS CHO: {doc_type.upper()} — hiển thị {min(len(chunks), MAX_CHUNKS_TO_DISPLAY)} chunk đầu")

        for i, chunk in enumerate(chunks[:MAX_CHUNKS_TO_DISPLAY]):
            chunk_type = chunk.metadata.get('chunk_type', 'unknown')
            chunk_text = chunk.page_content
            print(f"\n📍 [CHUNK {i+1}/{len(chunks)}] - Type: {chunk_type}")
            print("--- Nội dung chunk ---")
            print(chunk_text[:MAX_PREVIEW_CHARS] + ("..." if len(chunk_text) > MAX_PREVIEW_CHARS else ""))
            print("-" * 40)

        print("="*80 + "\n")
        del content_cleaned, doc_info, chunks

    summary_df = pd.DataFrame(results_summary)
    display(summary_df)
