from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import dotenv_values


INLINE_KEYS = (
    "GOOGLE_SERVICE_ACCOUNT_PROJECT_ID",
    "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID",
    "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY",
    "GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL",
    "GOOGLE_SERVICE_ACCOUNT_CLIENT_ID",
)


def materialize_google_credentials(
    *,
    env_file: Path,
    output_path: Path | None = None,
) -> Path:
    values = dotenv_values(env_file)
    missing = [key for key in INLINE_KEYS if not values.get(key)]
    if missing:
        raise ValueError("missing_google_service_account_fields")

    target = output_path or Path(
        values.get("GOOGLE_APPLICATION_CREDENTIALS")
        or "credentials/google-service-account.json"
    )
    target = target.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    private_key = str(values["GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY"]).replace("\\n", "\n")
    credentials = {
        "type": "service_account",
        "project_id": values["GOOGLE_SERVICE_ACCOUNT_PROJECT_ID"],
        "private_key_id": values["GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID"],
        "private_key": private_key,
        "client_email": values["GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL"],
        "client_id": values["GOOGLE_SERVICE_ACCOUNT_CLIENT_ID"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": (
            "https://www.googleapis.com/robot/v1/metadata/x509/"
            + str(values["GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL"]).replace("@", "%40")
        ),
        "universe_domain": "googleapis.com",
    }
    target.write_text(json.dumps(credentials, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _scrub_inline_google_env(env_file, target)
    return target


def _scrub_inline_google_env(env_file: Path, credentials_path: Path) -> None:
    lines = env_file.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    saw_credentials_path = False
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in INLINE_KEYS:
            continue
        if key == "GOOGLE_APPLICATION_CREDENTIALS":
            output.append(f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}")
            saw_credentials_path = True
        else:
            output.append(line)
    if not saw_credentials_path:
        output.append(f"GOOGLE_APPLICATION_CREDENTIALS={credentials_path}")
    env_file.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write Google service-account JSON from inline .env fields, then remove inline fields."
    )
    parser.add_argument("--env-file", default=".env", type=Path)
    parser.add_argument("--output", default=None, type=Path)
    args = parser.parse_args()
    path = materialize_google_credentials(env_file=args.env_file, output_path=args.output)
    print(f"wrote_google_credentials={path}")


if __name__ == "__main__":
    main()
