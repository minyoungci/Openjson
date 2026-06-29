from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateDocumentRequest(BaseModel):
    full_path: str
    content: Any
    schema_id: str | None = None


class CreateUserRequest(BaseModel):
    email: str
    display_name: str


class SignupRequest(BaseModel):
    email: str
    display_name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshSessionRequest(BaseModel):
    refresh_token: str


class OidcCallbackRequest(BaseModel):
    provider: str = "default"
    state: str
    code: str


class CreateProjectInvitationRequest(BaseModel):
    email: str
    role: str
    send_email: bool = True


class AcceptInvitationRequest(BaseModel):
    token: str


class CreateWorkspaceRequest(BaseModel):
    name: str


class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None


class AddProjectMemberRequest(BaseModel):
    user_id: str
    role: str


class UpdateProjectMemberRequest(BaseModel):
    role: str


class CreateApiTokenRequest(BaseModel):
    name: str


class PatchOperation(BaseModel):
    op: str
    path: str
    value: Any = None


class PatchDocumentRequest(BaseModel):
    base_version: int = Field(ge=0)
    patch: list[dict[str, Any]]
    reason: str | None = None


class PatchPreviewRequest(BaseModel):
    base_version: int = Field(ge=1)
    patch: list[dict[str, Any]]


class ContentPreviewRequest(BaseModel):
    base_version: int = Field(ge=1)
    content: Any | None = None
    content_text: str | None = None


class ContentConflictPreviewRequest(BaseModel):
    base_version: int = Field(ge=1)
    content: Any | None = None
    content_text: str | None = None


class ContentUpdateRequest(BaseModel):
    base_version: int = Field(ge=1)
    content: Any | None = None
    content_text: str | None = None
    reason: str | None = None
    merge_strategy: str | None = None


class OfflineSyncItemRequest(BaseModel):
    client_operation_id: str
    document_id: str
    operation_type: str = "content_update"
    base_version: int = Field(ge=1)
    content: Any | None = None
    content_text: str | None = None
    reason: str | None = None
    merge_strategy: str | None = None


class OfflineSyncBatchRequest(BaseModel):
    items: list[OfflineSyncItemRequest]


class EditorPresenceRequest(BaseModel):
    status: str = "viewing"
    base_version: int = Field(ge=0)
    dirty: bool = False
    cursor_path: str | None = None


class DeleteDocumentRequest(BaseModel):
    base_version: int = Field(ge=1)
    reason: str | None = None


class RestoreDocumentRequest(BaseModel):
    base_version: int = Field(ge=1)
    reason: str | None = None


class RollbackDocumentRequest(BaseModel):
    base_version: int = Field(ge=1)
    target_version: int = Field(ge=1)
    reason: str | None = None


class CreateSchemaRequest(BaseModel):
    name: str
    version: str
    schema_: Any = Field(alias="schema")
    file_pattern: str | None = None

    model_config = {"populate_by_name": True}


class CreateCommentThreadRequest(BaseModel):
    body: str
    anchor_type: str = "document"
    path: str | None = None
    event_id: str | None = None


class AddCommentRequest(BaseModel):
    body: str


class ReviewChangeRequest(BaseModel):
    document_id: str
    base_version: int = Field(ge=1)
    patch: list[dict[str, Any]]
    reason: str | None = None


class CreateReviewRequest(BaseModel):
    title: str
    description: str | None = None
    changes: list[ReviewChangeRequest]


class ReviewDecisionRequest(BaseModel):
    comment: str | None = None


class ReviewCommentRequest(BaseModel):
    comment: str
