import re
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from langchain_core.documents import Document
import pandas as pd
from IPython.display import display

# === Preprocess HTML ===
def preprocess_legal_text(html_content):
    if not html_content: return ""
    
    # 1. Loại bỏ các thẻ không cần thiết
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["title", "script", "style"]):
        tag.decompose()
    
    text = soup.get_text(separator="\n")
    
    # 2. Sửa lỗi "Điều X :"
    text = re.sub(r'(Điều\s+\d+)\s*\n*\s*:', r'\1:', text)

    # 3. Tách dòng
    raw_lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    if not raw_lines: return ""

    # 4. Logic nối dòng (Merging) có bổ sung điều kiện chặn Header
    merged_lines = []
    buffer = raw_lines[0]
    
    for i in range(1, len(raw_lines)):
        curr = raw_lines[i]
        
        # Kiểm tra xem dòng hiện tại có phải là Header hoặc Điều khoản không
        is_curr_header = curr.isupper() and len(curr) > 3
        is_curr_article = re.match(r'^Điều\s+\d+:', curr)
        
        # Điều kiện nối dòng cũ
        is_split_word = len(buffer) <= 2
        is_unfinished_sentence = re.search(r'[a-zà-ỹ,;]\s*$', buffer)
        is_next_lowercase = curr[0].islower() if curr else False

        # SỬA LỖI TẠI ĐÂY: Nếu dòng tiếp theo là Header hoặc Article thì KHÔNG nối
        if (is_split_word or is_unfinished_sentence or is_next_lowercase) \
           and not is_curr_header \
           and not is_curr_article:
            buffer += " " + curr
        else:
            merged_lines.append(buffer)
            buffer = curr
            
    merged_lines.append(buffer)

    # 5. Format cuối cùng
    final_output = []
    for line in merged_lines:
        line = re.sub(r'\s+', ' ', line).strip()
        
        is_header = line.isupper() and len(line) > 3
        is_article = re.match(r'^Điều\s+\d+:', line)

        if is_header or is_article:
            if final_output and final_output[-1] != "":
                final_output.append("")
            final_output.append(line)
            if is_article:
                final_output.append("") 
        else:
            final_output.append(line)

    result = '\n'.join(final_output)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

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

for sample in content.take(1):
    doc_info = {
        "id": sample.get('id'),
        "title": sample.get('title'),
        "so_ky_hieu": sample.get('so_ky_hieu'),
        "content_cleaned": preprocess_legal_text(sample['content_html']) # Hàm clean HTML của bạn
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

import unicodedata
import pandas as pd

def norm_text(text):
    """Hàm bổ trợ để chuẩn hóa font Tiếng Việt và xóa khoảng trắng thừa"""
    if not text: return ""
    return unicodedata.normalize('NFC', str(text)).strip()

print("⏳ Đang lập chỉ mục Metadata để tra cứu...")

loai_van_ban_feature = metadata.features["loai_van_ban"]
is_class_label = hasattr(loai_van_ban_feature, "int2str")

meta_lookup = {}
for row in metadata:
    # FIX 1: Luôn ép ID về string để đảm bảo khớp giữa 2 bảng dữ liệu
    doc_id = str(row["id"])
    raw_type = row.get("loai_van_ban")
    
    if is_class_label and isinstance(raw_type, int):
        label = loai_van_ban_feature.int2str(raw_type)
    else:
        label = str(raw_type)
    
    # FIX 2: Chuẩn hóa Unicode NFC để tránh lỗi "Luật" (NFC) != "Luật" (NFD)
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

# =================================================================
# 3. QUÉT content VÀ CHẠY THỬ NGHIỆM
# =================================================================
samples_found = {}
print("\n⏳ Đang quét content stream để tìm mẫu đại diện...")

for item in content:
    # FIX 3: Ép ID của content về string để lookup
    doc_id = str(item["id"])
    doc_meta = meta_lookup.get(doc_id)
    
    if doc_meta:
        doc_type = doc_meta["loai_van_ban"]
        
        # Kiểm tra khớp loại văn bản
        if doc_type in target_types and doc_type not in samples_found:
            samples_found[doc_type] = {
                "id": doc_id,
                "title": doc_meta["title"],
                "so_ky_hieu": doc_meta["so_ky_hieu"],
                "content_html": item["content_html"]
            }
            print(f" -> Đã tìm thấy: {doc_type}")
            
        if len(samples_found) == len(target_types):
            break

# 4. XỬ LÝ VÀ HIỂN THỊ KẾT QUẢ
if not samples_found:
    print("❌ Vẫn không tìm thấy mẫu nào! Hãy kiểm tra print(meta_lookup) xem ID có dạng gì.")
else:
    print(f"✅ Đã lấy đủ {len(samples_found)} mẫu. Bắt đầu quá trình chunking...\n")
    
    results_summary = []
    for doc_type, data in samples_found.items():
        # 1. Tiền xử lý văn bản
        content_cleaned = preprocess_legal_text(data['content_html'])
        doc_info = {**data, "content_cleaned": content_cleaned, "loai_van_ban": doc_type}
        
        # HIỂN THỊ VĂN BẢN TRƯỚC KHI CHUNK
        print("="*80)
        print(f"📄 VĂN BẢN GỐC (ĐÃ CLEAN) - LOẠI: {doc_type.upper()}")
        print("-" * 30)
        print(content_cleaned) 
        print("-" * 30)
        
        # 2. Thực hiện chunking
        chunks = legal_structural_splitter(doc_info, max_chunk_size=1500)
        
        results_summary.append({
            "Loại văn bản": doc_type,
            "Số lượng chunks": len(chunks),
            "Chunk types": list(set([c.metadata.get('chunk_type', 'N/A') for c in chunks]))
        })
        
        # 3. HIỂN THỊ TẤT CẢ CÁC CHUNK
        print(f"\n🔥 DANH SÁCH {len(chunks)} CHUNKS CHO: {doc_type.upper()}")
        
        for i, chunk in enumerate(chunks):
            chunk_type = chunk.metadata.get('chunk_type', 'unknown')
            print(f"\n📍 [CHUNK {i+1}/{len(chunks)}] - Type: {chunk_type}")
            print(f"--- Nội dung chunk ---")
            print(chunk.page_content)
            print("-" * 40)

        print("="*80 + "\n")

    # Hiển thị bảng tổng hợp cuối cùng
    summary_df = pd.DataFrame(results_summary)
    display(summary_df)