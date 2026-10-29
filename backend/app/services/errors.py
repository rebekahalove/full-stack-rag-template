class ServiceError(Exception):
    """Base class for safe, expected application errors."""

    status_code = 500
    default_detail = "The request could not be completed."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class InvalidUploadError(ServiceError):
    status_code = 422
    default_detail = "The uploaded document is invalid or unsupported."


class UploadTooLargeError(ServiceError):
    status_code = 413
    default_detail = "The uploaded document exceeds the configured size limit."


class DocumentNotFoundError(ServiceError):
    status_code = 404
    default_detail = "Document not found."


class DocumentNotReadyError(ServiceError):
    status_code = 409
    default_detail = "The document is not ready for questions."


class InvalidQuestionError(ServiceError):
    status_code = 422
    default_detail = "The question is invalid."


class ProcessingError(ServiceError):
    status_code = 500
    default_detail = "Document processing failed."
