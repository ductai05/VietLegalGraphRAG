from __future__ import annotations
import argparse
import json
import mimetypes
import os
from typing import Any, Protocol

from dotenv import load_dotenv, find_dotenv
from google.cloud import vision
from google.oauth2 import service_account

load_dotenv(find_dotenv())


class OcrService(Protocol):
    def process(self, content: bytes, mime_type: str) -> dict[str, Any]:
        ...


class GoogleVisionOcrService:
    def __init__(self) -> None:
        project_id = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PROJECT_ID")
        private_key_id = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
        private_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY")
        client_email = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL")
        client_id = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CLIENT_ID")

        if project_id and private_key and client_email:
            # Handle newline characters from .env properly
            private_key = private_key.replace("\\n", "\n")
            credentials_info = {
                "type": "service_account",
                "project_id": project_id,
                "private_key_id": private_key_id,
                "private_key": private_key,
                "client_email": client_email,
                "client_id": client_id,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{client_email.replace('@', '%40')}" if client_email else "",
                "universe_domain": "googleapis.com"
            }
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            self.client = vision.ImageAnnotatorClient(credentials=credentials)
        else:
            # Fallback to standard GOOGLE_APPLICATION_CREDENTIALS if variables are not set
            self.client = vision.ImageAnnotatorClient()

    def process(self, content: bytes, mime_type: str) -> dict[str, Any]:
        """
        Process an image or pdf file using Google Vision API.
        mime_type should be 'application/pdf' or an image mime type like 'image/jpeg', 'image/png'.
        Returns a JSON structure containing the extracted text.
        """
        if mime_type == "application/pdf":
            return self._process_pdf(content)
        elif mime_type.startswith("image/"):
            return self._process_image(content)
        else:
            raise ValueError(f"Unsupported mime type: {mime_type}")

    def _process_image(self, content: bytes) -> dict[str, Any]:
        image = vision.Image(content=content)
        response = self.client.document_text_detection(image=image)
        
        if response.error.message:
            raise Exception(
                f"{response.error.message}\nFor more info on error messages, check: "
                "https://cloud.google.com/apis/design/errors"
            )

        full_text = response.full_text_annotation.text if response.full_text_annotation else ""
        return {
            "success": True,
            "text": full_text,
            "pages": [{"page_num": 1, "text": full_text}],
            "mime_type": "image/*"
        }

    def _process_pdf(self, content: bytes) -> dict[str, Any]:
        """
        Synchronously process a PDF document.
        Note: Google Vision API limits synchronous PDF processing to 5 pages.
        For larger documents, async_batch_annotate_files (requiring Google Cloud Storage) is needed,
        or the PDF should be split into images beforehand.
        """
        mime_type = "application/pdf"
        feature = vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)
        request = vision.AnnotateFileRequest(
            input_config=vision.InputConfig(content=content, mime_type=mime_type),
            features=[feature],
        )
        # requests list must contain exactly one request
        response = self.client.batch_annotate_files(requests=[request])
        
        full_text = ""
        pages_data = []
        
        for file_response in response.responses:
            for i, page_response in enumerate(file_response.responses):
                if page_response.error.message:
                    raise Exception(f"Error on page {i + 1}: {page_response.error.message}")
                
                page_text = page_response.full_text_annotation.text if page_response.full_text_annotation else ""
                full_text += page_text + "\n"
                pages_data.append({
                    "page_num": i + 1,
                    "text": page_text
                })
                
        return {
            "success": True,
            "text": full_text.strip(),
            "pages": pages_data,
            "mime_type": "application/pdf"
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
