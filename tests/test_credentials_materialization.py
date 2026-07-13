from __future__ import annotations

import json


def test_materialize_google_credentials_writes_ignored_json_and_scrubs_inline_env(tmp_path) -> None:
    from src.infra.scripts.materialize_google_credentials import materialize_google_credentials

    env_file = tmp_path / ".env"
    credentials_path = tmp_path / "credentials" / "google-service-account.json"
    env_file.write_text(
        "\n".join(
            [
                "OCR_PROVIDER=google",
                f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}",
                "GOOGLE_SERVICE_ACCOUNT_PROJECT_ID=test-project",
                "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID=key-id",
                'GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n"',
                "GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL=svc@test.iam.gserviceaccount.com",
                "GOOGLE_SERVICE_ACCOUNT_CLIENT_ID=client-id",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = materialize_google_credentials(env_file=env_file, output_path=credentials_path)

    assert result == credentials_path
    data = json.loads(credentials_path.read_text(encoding="utf-8"))
    assert data["type"] == "service_account"
    assert data["project_id"] == "test-project"
    assert data["private_key"] == "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"
    updated_env = env_file.read_text(encoding="utf-8")
    assert f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}" in updated_env
    assert "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY=" not in updated_env
    assert "GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL=" not in updated_env
