from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.api.dependencies import get_document_service
from app.schemas import DocumentRead, QuestionRequest, QuestionResponse
from app.services.protocols import DocumentServiceProtocol

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
DocumentServiceDependency = Annotated[DocumentServiceProtocol, Depends(get_document_service)]


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    service: DocumentServiceDependency,
    file: Annotated[UploadFile, File(description="A PDF, DOCX, or Markdown document")],
) -> DocumentRead:
    return await service.upload(file)


@router.get("", response_model=list[DocumentRead])
async def list_documents(service: DocumentServiceDependency) -> list[DocumentRead]:
    return await service.list_documents()


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(document_id: UUID, service: DocumentServiceDependency) -> DocumentRead:
    return await service.get_document(document_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, service: DocumentServiceDependency) -> Response:
    await service.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{document_id}/questions", response_model=QuestionResponse)
async def ask_question(
    document_id: UUID,
    request: QuestionRequest,
    service: DocumentServiceDependency,
) -> QuestionResponse:
    return await service.ask(document_id, request.question)
