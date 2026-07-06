from legal_chunker import chunk_legal_document



def test_chunk_ids_are_stable_across_runs():
    content = """
    QUYẾT ĐỊNH

    Điều 1. Phạm vi điều chỉnh
    Văn bản này quy định về phạm vi điều chỉnh của thủ tục hành chính.
    Nội dung được áp dụng cho cơ quan, tổ chức, cá nhân có liên quan.
    Việc thực hiện phải bảo đảm công khai, minh bạch và đúng thẩm quyền.

    Điều 2. Tổ chức thực hiện
    Cơ quan có thẩm quyền có trách nhiệm tổ chức thực hiện văn bản này.
    Các đơn vị liên quan phối hợp kiểm tra, báo cáo và xử lý vướng mắc.
    Trường hợp phát sinh vấn đề mới thì tổng hợp để trình cấp có thẩm quyền.
    """

    first = chunk_legal_document(42, content, source="unit-test")
    second = chunk_legal_document(42, content, source="unit-test")

    assert [chunk["chunk_id"] for chunk in first] == [
        "chunk:42:000001",
        "chunk:42:000002",
        "chunk:42:000003",
    ]
    assert [chunk["chunk_id"] for chunk in second] == [
        "chunk:42:000001",
        "chunk:42:000002",
        "chunk:42:000003",
    ]
    assert first[0]["next_chunk_id"] == "chunk:42:000002"
    assert first[1]["prev_chunk_id"] == "chunk:42:000001"
