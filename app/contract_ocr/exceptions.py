class ContractAppError(Exception):
    """Base exception that can be shown safely in the UI."""


class PDFValidationError(ContractAppError):
    """The uploaded PDF is invalid or outside configured limits."""


class OCRProcessingError(ContractAppError):
    """OCR initialization or inference failed."""


class GeminiAnalysisError(ContractAppError):
    """Gemini could not analyze the recognized contract text."""
