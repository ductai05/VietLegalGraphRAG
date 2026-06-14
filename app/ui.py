from __future__ import annotations

from pathlib import Path
from typing import Any

import gradio as gr

from contract_ocr.config import Settings
from contract_ocr.exceptions import ContractAppError
from contract_ocr.models import OCRDocument
from contract_ocr.service import ContractReviewService


APP_CSS = """
.app-shell { max-width: 1500px; margin: 0 auto; }
.hero {
  border: 1px solid var(--border-color-primary);
  border-radius: 16px;
  padding: 18px 22px;
  margin-bottom: 14px;
  background: linear-gradient(135deg, rgba(35, 99, 235, .10), rgba(14, 165, 233, .04));
}
.muted-note { color: var(--body-text-color-subdued); font-size: 0.92rem; }
"""


def _uploaded_path(upload: Any) -> str:
    if upload is None:
        raise ContractAppError("Hãy tải lên một tệp hợp đồng PDF.")
    if isinstance(upload, (str, Path)):
        return str(upload)
    name = getattr(upload, "name", None)
    if name:
        return str(name)
    raise ContractAppError("Không đọc được đường dẫn tệp PDF đã tải lên.")


def _status_markdown(document: OCRDocument) -> str:
    truncation = (
        f" Chỉ xử lý {document.processed_pages}/{document.total_pages} trang theo "
        "giới hạn hiện tại."
        if document.truncated
        else ""
    )
    return (
        "### OCR hoàn tất\n"
        f"- Thiết bị: `{document.device}`\n"
        f"- Detector: `{document.detector_model}`\n"
        f"- Recognizer: `{document.recognizer_model}`\n"
        f"- Số trang: `{document.processed_pages}`\n"
        f"- Số dòng nhận diện: `{document.line_count}`\n"
        f"- Độ tin cậy trung bình: `{document.average_confidence:.1%}`\n"
        f"- Thời gian: `{document.elapsed_seconds:.2f} giây`\n\n"
        f"{truncation}"
    )


def build_app(
    settings: Settings | None = None,
    service: ContractReviewService | None = None,
) -> gr.Blocks:
    settings = settings or Settings.from_env()
    service = service or ContractReviewService(settings)

    def perform_ocr(
        pdf_file: Any,
        requested_pages: int,
        dpi: int,
        score_threshold: float,
        progress: gr.Progress,
    ) -> OCRDocument:
        pdf_path = _uploaded_path(pdf_file)

        def update_progress(done: int, total: int, message: str) -> None:
            progress(done / max(total, 1), desc=message)

        return service.ocr_pdf(
            pdf_path=pdf_path,
            requested_pages=int(requested_pages),
            dpi=int(dpi),
            score_threshold=float(score_threshold),
            progress_callback=update_progress,
        )

    def run_ocr(
        pdf_file: Any,
        requested_pages: int,
        dpi: int,
        score_threshold: float,
        progress: gr.Progress = gr.Progress(),
    ) -> tuple[str, str, dict[str, Any], list[list[Any]], dict[str, Any] | None]:
        try:
            document = perform_ocr(
                pdf_file,
                requested_pages,
                dpi,
                score_threshold,
                progress,
            )
            data = document.to_dict()
            return (
                _status_markdown(document),
                document.text,
                data,
                document.table_rows(),
                data,
            )
        except ContractAppError as exc:
            return f"### Không thể OCR\n{exc}", "", {}, [], None
        except Exception as exc:
            return f"### Lỗi không mong đợi khi OCR\n{exc}", "", {}, [], None

    def run_analysis(
        contract_text: str,
        api_key: str,
        model: str,
        progress: gr.Progress = gr.Progress(),
    ) -> str:
        try:
            def update_progress(done: int, total: int, message: str) -> None:
                progress(done / max(total, 1), desc=message)

            return service.analyze_contract(
                contract_text=contract_text,
                api_key=api_key,
                model=model,
                progress_callback=update_progress,
            )
        except ContractAppError as exc:
            return f"### Không thể phân tích\n{exc}"
        except Exception as exc:
            return f"### Lỗi không mong đợi khi gọi Gemini\n{exc}"

    def run_all(
        pdf_file: Any,
        api_key: str,
        model: str,
        requested_pages: int,
        dpi: int,
        score_threshold: float,
        progress: gr.Progress = gr.Progress(),
    ) -> tuple[
        str,
        str,
        dict[str, Any],
        list[list[Any]],
        dict[str, Any] | None,
        str,
    ]:
        try:
            document = perform_ocr(
                pdf_file,
                requested_pages,
                dpi,
                score_threshold,
                progress,
            )
            data = document.to_dict()

            def update_analysis_progress(
                done: int,
                total: int,
                message: str,
            ) -> None:
                progress(done / max(total, 1), desc=message)

            analysis = service.analyze_contract(
                contract_text=document.text,
                api_key=api_key,
                model=model,
                progress_callback=update_analysis_progress,
            )
            return (
                _status_markdown(document),
                document.text,
                data,
                document.table_rows(),
                data,
                analysis,
            )
        except ContractAppError as exc:
            return f"### Không thể hoàn tất\n{exc}", "", {}, [], None, ""
        except Exception as exc:
            return f"### Lỗi không mong đợi\n{exc}", "", {}, [], None, ""

    def clear_all() -> tuple[Any, str, str, dict[str, Any], list[Any], None, str]:
        return None, "", "", {}, [], None, ""

    with gr.Blocks(title="PP-OCRv6 Contract Review") as demo:
        ocr_state = gr.State(value=None)

        with gr.Column(elem_classes=["app-shell"]):
            gr.Markdown(
                """
                # OCR và rà soát hợp đồng
                **PP-OCRv6 medium safetensors** để detect dòng và recognizer
                tiếng Việt để đọc nội dung, sau đó gửi phần văn bản đã kiểm tra
                tới Gemini.

                Kết quả chỉ hỗ trợ rà soát ban đầu và không thay thế tư vấn pháp lý.
                """,
                elem_classes=["hero"],
            )

            with gr.Row(equal_height=False):
                with gr.Column(scale=4):
                    pdf_file = gr.File(
                        label="Hợp đồng PDF",
                        file_types=[".pdf"],
                        type="filepath",
                    )
                    api_key = gr.Textbox(
                        label="Gemini API key",
                        type="password",
                        placeholder="Để trống nếu máy chủ đã đặt GEMINI_API_KEY",
                    )
                    gemini_model = gr.Textbox(
                        label="Gemini model",
                        value=settings.gemini_model,
                        info="Mặc định dùng model stable được cấu hình trên server.",
                    )

                    with gr.Accordion("Tùy chọn OCR", open=False):
                        requested_pages = gr.Slider(
                            minimum=1,
                            maximum=settings.max_pages,
                            value=min(20, settings.max_pages),
                            step=1,
                            label="Số trang tối đa cần OCR",
                        )
                        dpi = gr.Slider(
                            minimum=96,
                            maximum=settings.max_pdf_dpi,
                            value=min(
                                settings.default_pdf_dpi,
                                settings.max_pdf_dpi,
                            ),
                            step=12,
                            label="DPI render PDF",
                        )
                        score_threshold = gr.Slider(
                            minimum=0.0,
                            maximum=1.0,
                            value=settings.text_rec_score_threshold,
                            step=0.05,
                            label="Ngưỡng tin cậy recognition",
                        )

                    run_all_button = gr.Button(
                        "OCR và phân tích hợp đồng",
                        variant="primary",
                    )
                    with gr.Row():
                        ocr_button = gr.Button("Chỉ chạy OCR")
                        analyze_button = gr.Button("Phân tích text hiện tại")
                    clear_button = gr.Button("Xóa dữ liệu", variant="secondary")
                    gr.Markdown(
                        """
                        Lần chạy OCR đầu tiên sẽ tải các model cần thiết và có
                        thể lâu hơn các lần sau. API key không được lưu vào kết
                        quả OCR.
                        """,
                        elem_classes=["muted-note"],
                    )

                with gr.Column(scale=7):
                    status = gr.Markdown("Chưa có tác vụ.")
                    ocr_text = gr.Textbox(
                        label="Văn bản OCR (có thể sửa trước khi phân tích)",
                        lines=18,
                        max_lines=30,
                    )
                    analysis = gr.Markdown(
                        value="Chưa có kết quả phân tích Gemini.",
                        label="Phân tích hợp đồng",
                    )

            with gr.Tabs():
                with gr.Tab("Các dòng OCR"):
                    line_table = gr.Dataframe(
                        headers=["Trang", "Dòng", "Văn bản", "Tin cậy"],
                        datatype=["number", "number", "str", "number"],
                        interactive=False,
                        wrap=True,
                    )
                with gr.Tab("JSON sẵn sàng cho RAG/KG"):
                    metadata = gr.JSON(label="OCR document")

        ocr_button.click(
            fn=run_ocr,
            inputs=[pdf_file, requested_pages, dpi, score_threshold],
            outputs=[status, ocr_text, metadata, line_table, ocr_state],
            concurrency_id="ocr_gpu",
            concurrency_limit=1,
        )
        analyze_button.click(
            fn=run_analysis,
            inputs=[ocr_text, api_key, gemini_model],
            outputs=[analysis],
            concurrency_limit=4,
        )
        run_all_button.click(
            fn=run_all,
            inputs=[
                pdf_file,
                api_key,
                gemini_model,
                requested_pages,
                dpi,
                score_threshold,
            ],
            outputs=[
                status,
                ocr_text,
                metadata,
                line_table,
                ocr_state,
                analysis,
            ],
            concurrency_id="ocr_gpu",
            concurrency_limit=1,
        )
        clear_button.click(
            fn=clear_all,
            inputs=[],
            outputs=[
                pdf_file,
                api_key,
                ocr_text,
                metadata,
                line_table,
                ocr_state,
                analysis,
            ],
        )

    return demo
