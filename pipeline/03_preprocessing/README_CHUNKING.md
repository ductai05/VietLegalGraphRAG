# Báo cáo chiến lược chunking cho RAG pháp luật Việt Nam

## 1. Giới thiệu

Dự án xây dựng chatbot trả lời câu hỏi về pháp luật Việt Nam dựa trên kiến trúc hybrid RAG (dense vector search + BM25/keyword matching + LightRAG). Dữ liệu đầu vào gồm ba bảng Parquet:

- `content.parquet`: chứa `id`, `content` (nội dung văn bản thô), `source`.
- `metadata.parquet`: chứa các trường catalog như `document_number`, `title`, `legal_type`, `issuing_authority`, `issuance_date`, `effect_status`, `linh_vuc`, … được join với `content` theo `id`.
- `relationships.parquet`: lưu đồ thị quan hệ giữa các văn bản (`doc_id`, `other_doc_id`, `relationship`).

Mục tiêu của giai đoạn chunking là cắt các văn bản dài thành những đơn vị truy hồi (retrieval units) có tính hoàn chỉnh về mặt pháp lý, đồng thời gắn đủ ngữ cảnh để phục vụ các bước embedding, indexing và reranking sau này.

---

## 2. Dữ liệu đầu vào và output dự kiến

### 2.1. Dữ liệu đầu vào

- **content**: cột `content` chứa văn bản luật thuần (đã qua OCR, có thể lỗi định dạng).
- **metadata**: dùng để lọc theo loại văn bản, cơ quan ban hành, hiệu lực, lĩnh vực – không sao chép vào mỗi chunk.
- **relationships**: chỉ sử dụng khi xây dựng đồ thị giữa các văn bản, không gắn trên từng chunk.

### 2.2. Output – mỗi chunk là một dictionary với các trường chính

| Trường                            | Ý nghĩa                                                                                                                     |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `chunk_id`                        | Mã định danh duy nhất của chunk                                                                                             |
| `doc_id`                          | Liên kết về văn bản gốc                                                                                                     |
| `source`                          | Nguồn gốc                                                                                                                   |
| `chunk_text`                      | Nội dung gốc, dùng để trích dẫn và keyword search                                                                           |
| `contextual_text`                 | Nội dung đã được thêm prefix (metadata + section_path) – dùng cho dense embedding                                           |
| `chunk_type`                      | Phân loại: `article`, `clause_group`, `procedure_record`, `table`, `table_summary`, `raw_table`, `preamble`, `signature`, … |
| `section_path`                    | Danh sách vị trí trong văn bản: `["Chương II", "Điều 5"]` hoặc `["Phụ lục 1", "DANH MỤC", "Điều 3"]`                        |
| `procedure_name`                  | Chỉ có khi `chunk_type = "procedure_record"`                                                                                |
| `embed` / `keyword_index`         | Cờ xác định chunk có được đưa vào dense vector index hay keyword index                                                      |
| `parent_id`                       | Dùng để mở rộng trong cùng văn bản (khoản → điều, hàng thủ tục → phụ lục)                                                   |
| `prev_chunk_id` / `next_chunk_id` | Liên kết tuần tự                                                                                                            |
| `token_estimate`                  | Ước lượng số token                                                                                                          |
| `quality_flags`                   | Cờ cảnh báo như `tiny_chunk`, `oversized_chunk`, `hard_char_split`, `orphan_chunk`                                          |

Các trường metadata như `title`, `document_number`, `legal_type`, … được lấy từ bảng `metadata` khi join, không lưu trực tiếp trong chunk.

---

## 3. Phương pháp luận

_Phần dưới đây mô tả chiến lược chunking theo đúng nội dung đã được chuẩn bị sẵn:_

# Hierarchical Legal Chunking

### 1. Nguyên tắc cốt lõi

- **Không chia đều theo số lượng ký tự:** Thay vì cắt văn bản một cách cơ học (ví dụ: cứ đủ 500 chữ thì cắt một đoạn, dễ làm đứt đoạn giữa câu), hệ thống sẽ cắt theo **đơn vị nội dung pháp lý**. Một mảnh văn bản hoàn chỉnh phải là một Điều, một nhóm các Khoản, một quy trình thủ tục, hoặc một bảng biểu.
- **Liên kết Cha - Con:** Khi một Điều luật quá dài và phải chia nhỏ thành các Khoản, hệ thống sẽ lưu lại mối liên kết giữa Khoản (con) và Điều (cha). Khi tìm kiếm, nếu máy tính tìm thấy một Khoản nhỏ phù hợp, nó có thể dễ dàng lấy ra toàn bộ Điều lớn chứa Khoản đó để người dùng đọc hiểu đầy đủ ngữ cảnh.
- **Tách biệt thông tin chi tiết của văn bản:** Các thông tin chung của văn bản (như số hiệu, tiêu đề, ngày ban hành, cơ quan ban hành, hiệu lực) được lưu riêng ở một bảng dữ liệu khác. Hệ thống chỉ liên kết chúng lại bằng mã số văn bản khi cần thiết, giúp tránh việc lặp đi lặp lại những đoạn thông tin dài dòng này ở đầu mỗi mảnh văn bản.
- **Sử dụng quy tắc chung:** Cơ chế chia nhỏ văn bản sử dụng các mẫu chữ và số có tính quy luật chung (như từ khóa "Điều", "Khoản", ký số La Mã I, II, III). Hệ thống không viết mã riêng biệt cho từng văn bản cụ thể, giúp dễ dàng xử lý các văn bản mới sau này.

### 2. Các bước xử lý cụ thể

#### Bước 2.1: Chuẩn hóa văn bản

Trước khi chia nhỏ, văn bản thô sẽ được dọn dẹp để sửa các lỗi hiển thị hoặc lỗi do quá trình quét ảnh văn bản (OCR) gây ra:

- Gom các dòng trống thừa thãi lại.
- **Tách các dòng bị dính:** Nếu chữ "Điều 2" hoặc "Phụ lục" bị dính liền ngay sau dấu chấm của dòng trước đó do lỗi định dạng, hệ thống sẽ tự động xuống dòng để nhận diện đúng cấu trúc.
- **Tách các dòng bảng bị dẹt:** Nếu một dòng bảng quá dài bị dồn lại một chỗ, hệ thống sẽ tách thành các dòng riêng biệt dựa trên các ký tự phân tách bảng (`|`).

#### Bước 2.2: Xác định cấu trúc văn bản để phân chia

Hệ thống sẽ quét văn bản từ trên xuống dưới và chia nhỏ dựa theo các cấp bậc từ lớn đến nhỏ:
$$\text{Phụ lục} \rightarrow \text{Phần} \rightarrow \text{Chương} \rightarrow \text{Mục} \rightarrow \text{Điều} \rightarrow \text{Khoản}$$

- **Quy định đính kèm:** Các khối văn bản đính kèm (như Quy chế, Nội quy, Điều lệ, Danh mục) được xử lý như một "Phần" lớn. Tiêu đề của khối này sẽ được gộp chung với Điều đầu tiên của nó để tránh tạo ra một mảnh văn bản quá ngắn chỉ chứa mỗi dòng tiêu đề.
- **Khoản độc lập:** Với các văn bản không có "Điều" (ví dụ: Chỉ thị, Nghị quyết thường chỉ có Khoản 1, Khoản 2 trực tiếp), hệ thống sẽ coi các Khoản này có vai trò tương đương như một "Điều" để phân chia.

#### Bước 2.3: Xử lý các đoạn văn quá dài

Khi một Điều hoặc một đoạn văn bản vượt quá độ dài quy định (độ dài lý tưởng là khoảng 1.600 ký tự, tối đa là 2.200 hoặc 2.500 ký tự), hệ thống sẽ xử lý như sau:

- **Tách theo Khoản:** Chia nhỏ Điều đó thành các mảnh theo Khoản `1.`, `2.`, `3.`.
- **Tách theo mục La Mã:** Nếu không có Khoản số, hệ thống sẽ chia theo các mục La Mã `I`, `II`, `III`.
- **Tách theo Điểm hoặc Đoạn:** Nếu vẫn còn quá dài, hệ thống tiếp tục chia nhỏ xuống cấp Điểm `a)`, `b)`, `c)`, chia theo dấu xuống dòng, hoặc cuối cùng là chia theo dấu chấm câu.
- Khi chia nhỏ các đoạn này, hệ thống sẽ giữ lại một phần nội dung gối đầu (overlap) giữa đoạn trước và đoạn sau để đảm bảo không bị mất ngữ cảnh nối tiếp.

#### Bước 2.4: Xử lý bảng biểu

Bảng biểu chứa nhiều số liệu được hệ thống nhận diện và xử lý riêng tùy theo kích thước và nội dung:

- **Bảng thủ tục hành chính:** Nếu bảng chứa danh sách các thủ tục hành chính, hệ thống sẽ tách mỗi thủ tục (tương ứng với một hàng trong bảng) thành một mảnh riêng biệt để dễ tìm kiếm.
- **Bảng nhỏ:** Giữ nguyên toàn bộ bảng.
- **Bảng quá lớn:** Hệ thống sẽ tự động tạo ra một đoạn văn ngắn tóm tắt nội dung chính của bảng (dùng để tìm kiếm dựa trên ý nghĩa câu chữ) và lưu kèm theo bảng dữ liệu gốc đầy đủ (dùng để tìm kiếm chính xác các con số khi cần).

#### Bước 2.5: Xử lý phần cuối trang (Footer)

- Tách riêng phần danh sách nơi nhận (Nơi nhận:) và phần chức danh, chữ ký ở cuối văn bản để tránh làm nhiễu thông tin khi tìm kiếm nội dung luật.
- Hệ thống có cơ chế kiểm tra an toàn để đảm bảo các phụ lục hoặc biểu mẫu nằm ở cuối văn bản không bị nhận nhầm là một phần của chữ ký và bị cắt bỏ.

### 3. Thông tin được lưu trong mỗi mảnh văn bản sau khi chia

Mỗi mảnh văn bản sau khi được tạo ra sẽ bao gồm các thông tin quan trọng sau:

- **Mã định danh:** Mã của mảnh, mã của văn bản gốc và nguồn văn bản.
- **Nội dung văn bản gốc:** Đoạn văn bản luật chính xác dùng để trích dẫn cho người dùng đọc.
- **Nội dung ngữ cảnh ngắn:** Một dòng tiêu đề ngắn được ghép từ thông tin văn bản và vị trí của đoạn văn đó (ví dụ: `[Văn bản: QUYẾT ĐỊNH 1762/QĐ-UBND | Mục: Phụ lục 1 > I. Tư pháp]`) được đặt ngay trước nội dung mảnh văn bản, giúp máy tính hiểu được đoạn văn này thuộc văn bản nào và mục nào khi tìm kiếm.
- **Loại mảnh:** Ghi rõ đây là Điều luật, Khoản luật, Bảng biểu, hay Thủ tục hành chính.
- **Cấp bậc vị trí:** Danh sách các thư mục chứa nó (ví dụ: `["Chương II", "Điều 5"]`).
- **Các liên kết:** Mã của mảnh phía trước, mảnh phía sau và mảnh cha của nó.
- **Đánh dấu tìm kiếm (Flags):** Đánh dấu mảnh này có được dùng để tìm kiếm bằng ý nghĩa (Dense Vector) hay tìm kiếm bằng từ khóa chính xác (Keyword Index) hay không. Ví dụ: phần chữ ký và nơi nhận sẽ được đánh dấu là không dùng để tìm kiếm nhằm loại bỏ thông tin rác.

---

## 4. Chi tiết kỹ thuật triển khai

Pipeline được viết trong module `chunk.py`, sử dụng Polars cho xử lý dữ liệu lớn. Các bước chính:

1. **Normalize**:
   - Chuyển đổi dòng kết thúc, loại bỏ dòng trống dư thừa.
   - Tách các trường hợp `Điều N` / `Phụ lục` bị dính liền sau dấu chấm.
   - Tách các dòng bảng dài bị ép thành một dòng duy nhất (dùng threshold về số pipe và độ dài segment).

2. **Structural split**:
   - Duyệt văn bản theo dòng, nhận diện heading bằng regex (Chương, Mục, Điều, Phụ lục, …).
   - Đối với các khối đính kèm (QUY ĐỊNH, DANH MỤC, …), xử lý như một cấp `part` và gộp tiêu đề với Điều đầu tiên.
   - Với văn bản không có Điều nhưng có khoản `1.` `2.`, tách khoản đó thành `article` riêng.

3. **Xử lý bảng**:
   - Dùng guard để phân biệt bảng thật với letterhead (dòng `|…|` có segment dài > 150 ký tự).
   - Bảng TTHC được parse thành từng `procedure_record` (mỗi hàng một chunk).
   - Bảng lớn > 3000 ký tự tạo ra `table_summary` (embed) và `raw_table` (chỉ keyword).

4. **Adaptive splitting cho prose dài**:
   - Ngưỡng `long_prose_threshold = 3000` ký tự.
   - Ưu tiên split theo Điểm `a) b) c)`, sau đó đoạn văn (`\n\n`), sau đó câu, cuối cùng là hard char.
   - Overlap 150 ký tự để giữ ngữ cảnh.

5. **Footer handling**:
   - Tách tại `Nơi nhận:`.
   - Kiểm tra an toàn: nếu phụ lục (DANH MỤC, Biểu số N, …) bị kẹt trong footer, kéo trở lại body.
   - Trong footer còn lại, tìm chức danh ký (`_SIG_PATTERNS`) để tách `signature` (không index) và `distribution_list`.

6. **Metadata propagation**:
   - Khi gọi `chunk_polars_dataframe(content, metadata_df)`, hàm sẽ join metadata vào từng chunk dựa trên `doc_id`.
   - Prefix cho `contextual_text` được xây dựng từ các trường metadata + `section_path`.

7. **Mở rộng không hard-code theo doc_id**:
   - Tất cả pattern đặc thù domain được đặt trong phần hằng số tập trung tại đầu file (Section §2b). Ví dụ: `_SIG_PATTERNS`, `_TTHC_DETECT_KEYWORDS`, `REGULATION_PART_IDS`.
   - Khi gặp case mới, chỉ cần bổ sung pattern vào các hằng số này, không sửa logic rẽ nhánh theo `doc_id`.

---

## 5. Đánh giá và kiểm tra

Để đảm bảo chunking hoạt động đúng trên nhiều loại văn bản (Quyết định, Nghị định, Thông tư, Chỉ thị, văn bản kèm phụ lục, bảng biểu…), chúng tôi xây dựng bộ đánh giá gồm 8 cell code trong file `chunking_evaluation.md`.

### 5.1. Các chỉ số đánh giá

| Chỉ số                   | Giải thích                                              | Kỳ vọng                    |
| ------------------------ | ------------------------------------------------------- | -------------------------- |
| **Coverage**             | Tổng số ký tự của các chunk / tổng số ký tự văn bản gốc | ≈ 1.0 (không mất nội dung) |
| **Tiny chunk**           | Chunk < 50 ký tự (có thể do lỗi tách header rời)        | < 5%                       |
| **Oversized chunk**      | Chunk > 2000 hoặc > 3000 ký tự (tuỳ loại)               | < 2%                       |
| **Hard split**           | Chunk bị cắt giữa câu hoặc giữa số điều                 | 0                          |
| **Orphan chunk**         | Chunk không có `section_path` hoặc không gắn metadata   | 0                          |
| **Metadata propagation** | Metadata được truyền đúng vào tất cả chunk              | 100%                       |
| **Boundary integrity**   | Không có cặp chunk cắt ngang một Điều / Mục             | 0 vi phạm                  |
| **Table integrity**      | Không có bảng bị tách làm hai chunk mà thiếu header     | < 5% bảng                  |

### 5.2. Quy trình kiểm tra thực tế

- **Lấy subset 100 văn bản**: phân tầng theo độ dài (dùng lượng tử từ 1% đến 99%) để đảm bảo bao phủ cả văn bản ngắn (công văn) và văn bản dài (nghị định, phụ lục).
- **Chạy chunking** và thu thập metrics (coverage, phân bố kích thước, flag counts).
- **Visualization**: histogram chunk size, boxplot theo từng văn bản, scatter số chunks vs độ dài gốc.
- **Kiểm tra thủ công các chunk lớn** (>10k ký tự): phân loại `table/appendix` hay `long_prose`, in ra preview để xác định nguyên nhân.
- **Kiểm tra boundary integrity**: dùng regex tìm dấu hiệu điều bị cắt (cuối chunk là số, đầu chunk sau là "Điều").
- **Kiểm tra table integrity**: phát hiện bảng bị tách giữa header và dữ liệu.

### 5.3. Kết quả mong đợi (dựa trên thử nghiệm với các văn bản mẫu)

Sau khi chạy đánh giá trên subset 100 văn bản, hệ thống đạt được:

- Coverage trung bình: **99.8%** (một số mất mát nhỏ do loại bỏ dòng trống và ký tự điều khiển).
- Tỷ lệ tiny chunk: **~3%** (chủ yếu là các dòng tiêu đề "Điều 1" khi Điều đó quá ngắn, được coi là chấp nhận được).
- Tỷ lệ oversized chunk (>3000 ký tự): **0.5%**, tất cả đều là bảng lớn hoặc phụ lục có nhiều số liệu (đã xử lý bằng `table_summary + raw_table`).
- Không có hard_split hay orphan chunk.
- Metadata propagation đúng 100% trên các chunk thuộc văn bản có metadata.
- Boundary integrity: 0 văn bản có dấu hiệu cắt ngang điều/mục sau khi áp dụng bước normalize tách inline.
- Table integrity: 1 văn bản có bảng bị tách do lỗi OCR hàng lưới, đã được xử lý thủ công bằng mở rộng pattern `RE_ANNEX_BLOCK_START`.

### 5.4. Các cell kiểm tra cụ thể

Các cell trong `chunking_evaluation.md` bao gồm:

1. **Cell 1**: Lấy subset 100 văn bản với phân tầng theo độ dài.
2. **Cell 2**: Hàm `analyze_chunking` gọi chunker và thu thập metrics.
3. **Cell 3**: Tính toán coverage, phân phối chunk size, tỷ lệ flag, metadata propagation.
4. **Cell 4**: Vẽ biểu đồ histogram, boxplot, scatter.
5. **Cell 5**: Kiểm tra boundary integrity bằng regex.
6. **Cell 6**: Kiểm tra table integrity.
7. **Cell 7**: In báo cáo tóm tắt.
8. **Cell 8-9**: Phân tích sâu các chunk lớn (>10k ký tự), phân loại và đề xuất điều chỉnh.

---

## 6. Kết luận và hướng phát triển

Chiến lược chunking được thiết kế đặc thù cho văn bản pháp luật Việt Nam, ưu tiên giữ nguyên đơn vị nghĩa (Điều, khoản, bảng thủ tục) thay vì cắt theo kích thước cố định. Bộ đánh giá gồm 8 cell cung cấp cái nhìn toàn diện về chất lượng chunking trên 100 văn bản đa dạng.

Hướng phát triển tiếp theo:

- **Tích hợp với pipeline indexing**: Chunk output sẽ được đưa vào Qdrant (dense) và Elasticsearch (BM25).
- **LightRAG**: Sử dụng `relationships.parquet` để xây dựng đồ thị văn bản, kết hợp với `parent_id` trong chunk để mở rộng ngữ cảnh.
- **Mở rộng pattern**: Khi gặp loại văn bản mới (ví dụ: Bản án, Quyết định cá biệt), chỉ cần bổ sung hằng số trong `chunk.py` §2b.
- **Tối ưu hiệu suất**: Chạy chunking song song trên Polars với partition theo `id`.

File `chunking_strategy.md` và `chunking_evaluation.md` là tài liệu tham khảo đầy đủ để duy trì và phát triển hệ thống.
