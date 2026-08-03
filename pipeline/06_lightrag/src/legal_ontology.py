"""
Vietnamese Legal Ontology definitions and Prompt Templates for LightRAG Entity/Relation Extraction.
Inspired by LegalGraphRAG (ACL'26) and adapted for Vietnamese Legal Domain.
"""

from typing import Dict, List, Any

# 8 Core Entity Types for Vietnamese Legal System
ENTITY_TYPES: List[str] = [
    "LEGAL_DOCUMENT",     # Văn bản pháp luật (Luật, Nghị định, Thông tư, Quyết định, Bộ luật...)
    "LEGAL_ARTICLE",      # Điều khoản cụ thể (Điều X, Khoản Y, Điểm Z)
    "LEGAL_ORGANIZATION", # Cơ quan nhà nước, tổ chức có thẩm quyền (Quốc hội, Chính phủ, UBND, Bộ...)
    "LEGAL_SUBJECT",      # Đối tượng áp dụng (doanh nghiệp, người lao động, cá nhân, lái xe...)
    "LEGAL_CONCEPT",      # Khái niệm/nguyên tắc pháp lý chuyên ngành
    "LEGAL_PENALTY",      # Hình phạt, chế tài, mức xử phạt
    "LEGAL_PROCEDURE",    # Thủ tục, quy trình hành chính/pháp lý
    "TEMPORAL",           # Ngày hiệu lực, thời hạn, thời hiệu
]

# 10 Core Relation Types
RELATION_TYPES: List[str] = [
    "AMENDS",          # Sửa đổi, bổ sung văn bản/dẫn chiếu khác
    "REPLACES",        # Thay thế, bãi bỏ văn bản cũ
    "REFERENCES",      # Dẫn chiếu đến điều khoản/văn bản khác
    "IMPLEMENTS",      # Hướng dẫn thi hành, quy định chi tiết
    "GOVERNS",         # Điều chỉnh/áp dụng đối với chủ thể hoặc lĩnh vực
    "HAS_ARTICLE",     # Văn bản sở hữu điều khoản
    "REQUIRES",        # Điều kiện bắt buộc/hồ sơ yêu cầu
    "PENALIZES",       # Áp dụng hình phạt/chế tài đối với hành vi
    "EFFECTIVE_FROM",  # Ngày/thời điểm có hiệu lực
    "ISSUED_BY",       # Ban hành bởi cơ quan/tổ chức
]

FEW_SHOT_ENTITY_EXAMPLES: List[Dict[str, Any]] = [
    {
        "input": "Điều kiện thành lập công ty TNHH theo Luật Doanh nghiệp 2020: Chủ sở hữu là cá nhân hoặc tổ chức.",
        "entities": [
            {
                "name": "Luật Doanh nghiệp 2020",
                "type": "LEGAL_DOCUMENT",
                "description": "Văn bản luật quy định về thành lập, tổ chức quản lý, tổ chức lại, giải thể doanh nghiệp."
            },
            {
                "name": "công ty TNHH",
                "type": "LEGAL_SUBJECT",
                "description": "Loại hình doanh nghiệp có trách nhiệm hữu hạn trong phạm vi vốn góp."
            },
            {
                "name": "thành lập công ty TNHH",
                "type": "LEGAL_PROCEDURE",
                "description": "Thủ tục pháp lý để khai sinh loại hình doanh nghiệp TNHH."
            }
        ]
    },
    {
        "input": "Xử phạt người điều khiển xe ô tô vượt đèn đỏ từ 4.000.000 đồng đến 6.000.000 đồng theo Nghị định 100/2019/NĐ-CP.",
        "entities": [
            {
                "name": "Nghị định 100/2019/NĐ-CP",
                "type": "LEGAL_DOCUMENT",
                "description": "Nghị định quy định xử phạt vi phạm hành chính trong lĩnh vực giao thông đường bộ và đường sắt."
            },
            {
                "name": "người điều khiển xe ô tô",
                "type": "LEGAL_SUBJECT",
                "description": "Cá nhân trực tiếp vận hành xe ô tô trên đường giao thông."
            },
            {
                "name": "vượt đèn đỏ",
                "type": "LEGAL_CONCEPT",
                "description": "Hành vi không chấp hành hiệu lệnh của đèn tín hiệu giao thông."
            },
            {
                "name": "Phạt tiền từ 4.000.000đ đến 6.000.000đ",
                "type": "LEGAL_PENALTY",
                "description": "Mức phạt tiền hành chính đối với hành vi không chấp hành đèn tín hiệu giao thông của ô tô."
            }
        ]
    }
]

FEW_SHOT_RELATION_EXAMPLES: List[Dict[str, Any]] = [
    {
        "input": "Nghị định 01/2021/NĐ-CP hướng dẫn chi tiết thi hành Luật Doanh nghiệp 2020 về đăng ký doanh nghiệp.",
        "relations": [
            {
                "source": "Nghị định 01/2021/NĐ-CP",
                "target": "Luật Doanh nghiệp 2020",
                "relation_type": "IMPLEMENTS",
                "description": "Nghị định quy định chi tiết và hướng dẫn thi hành luật."
            }
        ]
    },
    {
        "input": "Bộ luật Lao động 2019 quy định trợ cấp mất việc làm đối với người lao động làm việc từ đủ 12 tháng trở lên.",
        "relations": [
            {
                "source": "Bộ luật Lao động 2019",
                "target": "người lao động",
                "relation_type": "GOVERNS",
                "description": "Bộ luật điều chỉnh quyền lợi và nghĩa vụ của người lao động."
            },
            {
                "source": "người lao động",
                "target": "trợ cấp mất việc làm",
                "relation_type": "REQUIRES",
                "description": "Người lao động làm đủ 12 tháng có quyền hưởng trợ cấp mất việc."
            }
        ]
    }
]

LEGAL_ENTITY_EXTRACTION_SYSTEM_PROMPT = """
Bạn là chuyên gia phân tích pháp luật Việt Nam hàng đầu.
Nhiệm vụ của bạn là phân tích đoạn văn bản pháp luật được cung cấp và trích xuất CHÍNH XÁC tất cả các thực thể pháp lý (Entities) và quan hệ giữa chúng (Relationships).

Các loại Thực thể (Entity Types) hợp lệ:
- LEGAL_DOCUMENT: Tên luật, bộ luật, nghị định, thông tư, quyết định (ví dụ: Luật Doanh nghiệp 2020, Nghị định 100/2019/NĐ-CP)
- LEGAL_ARTICLE: Điều khoản pháp lý (ví dụ: Điều 74, Khoản 1 Điều 5)
- LEGAL_ORGANIZATION: Cơ quan ban hành hoặc có thẩm quyền (ví dụ: Quốc hội, Chính phủ, Sở Kế hoạch và Đầu tư, UBND)
- LEGAL_SUBJECT: Chủ thể pháp luật / đối tượng áp dụng (ví dụ: công dân, doanh nghiệp, người lao động, lái xe)
- LEGAL_CONCEPT: Khái niệm pháp lý, nguyên tắc hoặc hành vi pháp luật (ví dụ: vượt đèn đỏ, chấm dứt HĐLĐ, năng lực hành vi dân sự)
- LEGAL_PENALTY: Hình phạt, mức phạt tiền, chế tài hành chính hoặc hình sự (ví dụ: Phạt tiền từ 4-6 triệu, tước GPLX 1-3 tháng)
- LEGAL_PROCEDURE: Quy trình, thủ tục hành chính hoặc pháp lý (ví dụ: đăng ký kết hôn, đăng ký doanh nghiệp)
- TEMPORAL: Ngày hiệu lực, thời hạn, mốc thời gian (ví dụ: từ đủ 12 tháng trở lên, 01 tháng đến 03 tháng)

Các loại Quan hệ (Relation Types) hợp lệ:
- AMENDS: Sửa đổi, bổ sung
- REPLACES: Thay thế, bãi bỏ
- REFERENCES: Dẫn chiếu đến
- IMPLEMENTS: Hướng dẫn thi hành, quy định chi tiết
- GOVERNS: Điều chỉnh chủ thể hoặc lĩnh vực
- HAS_ARTICLE: Chứa điều khoản
- REQUIRES: Yêu cầu điều kiện/hồ sơ
- PENALIZES: Áp dụng chế tài đối với hành vi
- EFFECTIVE_FROM: Có hiệu lực từ
- ISSUED_BY: Ban hành bởi

Hãy đảm bảo phản hồi xuất ra dưới định dạng đúng cấu trúc theo yêu cầu của LightRAG.
"""
