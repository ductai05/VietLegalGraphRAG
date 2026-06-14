from contract_ocr.config import Settings
from ui import APP_CSS, build_app


def main() -> None:
    settings = Settings.from_env()
    demo = build_app(settings=settings)
    demo.queue(
        max_size=settings.queue_size,
        default_concurrency_limit=2,
    ).launch(
        server_name=settings.server_name,
        server_port=settings.server_port,
        share=settings.gradio_share,
        show_error=False,
        css=APP_CSS,
    )


if __name__ == "__main__":
    main()
