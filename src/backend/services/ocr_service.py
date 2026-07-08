from __future__ import annotations

import argparse
import json
import mimetypes
import os
from typing import Any, Protocol


class OcrService(Protocol):
    def process(self, content: bytes, mime_type: str) -> dict[str, Any]:
        ...


class NoopOcrService:
    """Returned when OCR is disabled or provider init fails."""

    def process(self, content: bytes, mime_type: str) -> dict[str, Any]:
        return {
            "success": False,
            "text": "",
            "pages": [],
            "mime_type": mime_type,
        }


class GoogleVisionOcrService:
    """Lazy import: google.cloud.vision only loaded on first process() call."""

    def __init__(self) -> None:
        project_id = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PROJECT_ID")
        private_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY")
        client_email = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL")
        self._credentials = None

        if project_id and private_key and client_email:
            self._project_id = project_id
            self._private_key_id = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
            self._private_key = private_key.replace("\\n", "\n")
            self._client_email = client_email
            self._client_id = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CLIENT_ID")

    def _ensure_credentials(self) -> Any:
        from google.oauth2 import service_account

        if self._credentials is not None:
            return self._credentials
        if self._project_id:
            credentials_info = {
                "type": "service_account",
                "project_id": self._project_id,
                "private_key_id": self._private_key_id,
                "private_key": self._private_key,
                "client_email": self._client_email,
                "client_id": self._client_id,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{self._client_email.replace('@', '%40')}" if self._client_email else "",
                "universe_domain": "googleapis.com",
            }
            self._credentials = service_account.Credentials.from_service_account_info(credentials_info)
        return self._credentials

    def _client(self) -> Any:
        from google.cloud import vision

        return vision.ImageAnnotatorClient(credentials=self._ensure_credentials())

    def process(self, content: bytes, mime_type: str) -> dict[str, Any]:
        if mime_type == "application/pdf":
            return self._process_pdf(content)
        elif mime_type.startswith("image/"):
            return self._process_image(content)
        else:
            raise ValueError(f"Unsupported mime type: {mime_type}")

    def _process_image(self, content: bytes) -> dict[str, Any]:
        from google.cloud import vision

        client = self._client()
        image = vision.Image(content=content)
        response = client.document_text_detection(image=image)

        if response.error.message:
            raise RuntimeError("ocr.provider_error")

        full_text = response.full_text_annotation.text if response.full_text_annotation else ""
        return {
            "success": True,
            "text": full_text,
            "pages": [{"page_num": 1, "text": full_text}],
            "mime_type": "image/*",
        }

    def _process_pdf(self, content: bytes) -> dict[str, Any]:
        from google.cloud import vision

        client = self._client()
        feature = vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)
        request = vision.AnnotateFileRequest(
            input_config=vision.InputConfig(content=content, mime_type="application/pdf"),
            features=[feature],
        )
        response = client.batch_annotate_files(requests=[request])

        full_text = ""
        pages_data = []

        for file_response in response.responses:
            for i, page_response in enumerate(file_response.responses):
                if page_response.error.message:
                    raise RuntimeError("ocr.provider_error")
                page_text = page_response.full_text_annotation.text if page_response.full_text_annotation else ""
                full_text += page_text + "\n"
                pages_data.append({"page_num": i + 1, "text": page_text})

        return {
            "success": True,
            "text": full_text.strip(),
            "pages": pages_data,
            "mime_type": "application/pdf",
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Google Vision OCR Service")
    parser.add_argument("file_path", help="Path to the image or PDF file to test")
    args = parser.parse_args()

    mime_type, _ = mimetypes.guess_type(args.file_path)
    if mime_type is None:
        if args.file_path.lower().endswith(".pdf"):
            mime_type = "application/pdf"
        elif args.file_path.lower().endswith(".png"):
            mime_type = "image/png"
        elif args.file_path.lower().endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"
        else:
            print("Could not determine mime type. Assuming image/jpeg")
            mime_type = "image/jpeg"

    with open(args.file_path, "rb") as f:
        content = f.read()

    service = GoogleVisionOcrService()
    try:
        print(f"Processing {args.file_path} as {mime_type}...")
        result = service.process(content, mime_type)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Error during OCR processing: {e}")
