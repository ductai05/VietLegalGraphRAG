from contract_ocr.config import Settings
import main as app_main


def test_main_configures_queue_and_launch(monkeypatch) -> None:
    settings = Settings(
        server_name="0.0.0.0",
        server_port=9000,
        gradio_share=True,
        queue_size=7,
    )
    calls = []

    class FakeDemo:
        def queue(self, **kwargs):
            calls.append(("queue", kwargs))
            return self

        def launch(self, **kwargs):
            calls.append(("launch", kwargs))

    monkeypatch.setattr(app_main.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(
        app_main,
        "build_app",
        lambda settings: FakeDemo(),
    )

    app_main.main()

    assert calls[0] == (
        "queue",
        {"max_size": 7, "default_concurrency_limit": 2},
    )
    assert calls[1][0] == "launch"
    assert calls[1][1]["server_name"] == "0.0.0.0"
    assert calls[1][1]["server_port"] == 9000
    assert calls[1][1]["share"] is True
    assert calls[1][1]["show_error"] is False
    assert calls[1][1]["css"] == app_main.APP_CSS
