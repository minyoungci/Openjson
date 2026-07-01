from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.activity_service import get_project_activity
from app.audit_service import list_project_audit_log
from app.auth_middleware import configure_api_token_authentication
from app.auth_service import (
    accept_project_invitation,
    authenticate_bearer_token,
    complete_oidc_callback,
    create_project_api_token,
    create_project_invitation,
    create_oidc_login_url,
    get_current_session_user,
    list_project_api_tokens,
    list_project_invitations,
    login_with_password,
    logout_session,
    parse_bearer_token,
    refresh_session,
    revoke_project_api_token,
    signup_with_password,
)
from app.backup_scheduler import BackupScheduler, backup_scheduler_config_from_env
from app.database import DEFAULT_DB_PATH, init_db
from app.comment_service import (
    add_comment,
    create_comment_thread,
    list_comment_threads,
    reopen_comment_thread,
    resolve_comment_thread,
)
from app.collaboration_service import get_collaboration_state, leave_editor_presence, upsert_editor_presence
from app.document_service import (
    create_document,
    delete_document,
    diff_document_versions,
    get_document,
    get_document_editor_state,
    get_document_event_detail,
    get_document_path_blame,
    get_document_path_history,
    get_document_version,
    get_history,
    get_project_editor_bootstrap,
    get_project_document_tree,
    list_project_document_events,
    list_project_documents,
    patch_document,
    preview_document_content_conflict,
    preview_document_content_update,
    preview_document_patch,
    restore_document,
    rollback_document,
    search_project_documents,
    update_document_content,
    validate_document,
)
from app.errors import AppError, ErrorCode
from app.email_service import send_invitation_email
from app.export_service import export_project_archive
from app.health_service import health_status, readiness_status, version_status
from app.integrity_service import (
    check_document_event_chain_integrity,
    check_document_replay_integrity,
    check_project_event_chain_integrity,
    check_project_replay_integrity,
)
from app.observability import REQUEST_ID_HEADER, configure_request_observability
from app.offline_sync_service import apply_offline_sync_batch
from app.project_usage_service import get_project_usage, project_usage_limit_config_from_env
from app.rate_limit import (
    FixedWindowRateLimiter,
    configure_rate_limiting,
    rate_limit_config_from_env,
    websocket_rate_limit_config_from_env,
)
from app.request_body_limit import configure_request_body_limiting, request_body_limit_config_from_env
from app.realtime_service import collaboration_hub, invalid_realtime_message, websocket_error_payload
from app.review_service import (
    apply_review_request,
    approve_review_request,
    comment_on_review_request,
    create_review_request,
    get_review_request,
    list_project_review_requests,
    request_review_changes,
)
from app.schema_match_service import preview_project_schema_matches
from app.schema_service import create_schema, get_schema, list_project_schemas
from app.schema_usage_service import get_schema_usage
from app.text_collaboration_service import text_collaboration_manager
from app.validation_report_service import get_project_validation_report
from app.workspace_service import (
    add_project_member,
    create_project,
    create_user,
    create_workspace,
    get_project,
    get_workspace,
    list_project_members,
    list_workspace_projects,
    list_workspaces,
    remove_project_member,
    update_project_member,
)
from app.zip_import_service import apply_zip_import, preview_zip_import
from app.schemas import (
    AddCommentRequest,
    AcceptInvitationRequest,
    CreateApiTokenRequest,
    AddProjectMemberRequest,
    ContentConflictPreviewRequest,
    ContentPreviewRequest,
    ContentUpdateRequest,
    CreateCommentThreadRequest,
    CreateDocumentRequest,
    CreateProjectRequest,
    CreateProjectInvitationRequest,
    CreateReviewRequest,
    CreateSchemaRequest,
    CreateUserRequest,
    CreateWorkspaceRequest,
    DeleteDocumentRequest,
    EditorPresenceRequest,
    PatchDocumentRequest,
    PatchPreviewRequest,
    RestoreDocumentRequest,
    ReviewCommentRequest,
    ReviewDecisionRequest,
    RollbackDocumentRequest,
    LoginRequest,
    OidcCallbackRequest,
    OfflineSyncBatchRequest,
    RefreshSessionRequest,
    SignupRequest,
    UpdateProjectMemberRequest,
)


ActorHeader = Annotated[str | None, Header(alias="X-Actor-Id")]
EventActorQuery = Annotated[str | None, Query(alias="actor_id")]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]

DEBUG_ERROR_ENV = "OPENJSON_DEBUG_ERROR_DETAILS"


def _parse_cors_origins(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _env_flag(raw: str | None) -> bool:
    return bool(raw and raw.strip().lower() in {"1", "true", "yes", "on"})


def _env_flag_default(raw: str | None, *, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _request_fields_set(request: object) -> set[str]:
    model_fields_set = getattr(request, "model_fields_set", None)
    if model_fields_set is not None:
        return set(model_fields_set)
    return set(getattr(request, "__fields_set__", set()))


async def _broadcast_document_mutation_checkpoint(
    db_path: str,
    *,
    document_id: str,
    actor_id: str | None,
    previous_version: int | None,
    reason: str,
) -> None:
    try:
        state = get_collaboration_state(
            db_path,
            document_id=document_id,
            actor_id=actor_id,
            since_version=previous_version,
        )
    except AppError:
        return
    await collaboration_hub.broadcast_state(document_id, state, reason=reason)


def _unexpected_error_details(request: Request | None, exc: Exception, *, debug: bool) -> dict:
    request_id = None
    if request is not None:
        request_id = getattr(request.state, "request_id", request.headers.get(REQUEST_ID_HEADER))
    details = {"diagnostic_code": "UNEXPECTED_EXCEPTION", "request_id": request_id}
    if debug:
        details.update(
            {
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
    return details


def _error_response(request: Request | None, *, status_code: int, content: dict) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content=content)
    request_id = None
    if request is not None:
        request_id = getattr(request.state, "request_id", request.headers.get(REQUEST_ID_HEADER))
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


def create_app(db_path: str | None = None) -> FastAPI:
    application = FastAPI(title="Collaborative JSON DB Workspace")
    application.state.db_path = db_path or os.environ.get("OPENJSON_DB_PATH", DEFAULT_DB_PATH)
    application.state.static_dir = Path(__file__).resolve().parents[1] / "static"
    application.state.allow_actor_header = _env_flag_default(
        os.environ.get("OPENJSON_ALLOW_ACTOR_HEADER"),
        default=True,
    )
    application.state.debug_error_details = _env_flag(os.environ.get(DEBUG_ERROR_ENV))
    collaboration_hub.configure(redis_url=os.environ.get("OPENJSON_REDIS_URL"))
    init_db(application.state.db_path)
    configure_api_token_authentication(
        application,
        db_path=application.state.db_path,
        allow_actor_header=application.state.allow_actor_header,
    )
    rate_limit_config = rate_limit_config_from_env(
        enabled_raw=os.environ.get("OPENJSON_RATE_LIMIT_ENABLED"),
        requests_raw=os.environ.get("OPENJSON_RATE_LIMIT_REQUESTS"),
        window_seconds_raw=os.environ.get("OPENJSON_RATE_LIMIT_WINDOW_SECONDS"),
    )
    application.state.websocket_rate_limit_config = websocket_rate_limit_config_from_env(
        enabled_raw=os.environ.get("OPENJSON_WS_RATE_LIMIT_ENABLED"),
        messages_raw=os.environ.get("OPENJSON_WS_RATE_LIMIT_MESSAGES"),
        window_seconds_raw=os.environ.get("OPENJSON_WS_RATE_LIMIT_WINDOW_SECONDS"),
    )
    request_body_limit_config = request_body_limit_config_from_env(
        enabled_raw=os.environ.get("OPENJSON_REQUEST_BODY_LIMIT_ENABLED"),
        max_bytes_raw=os.environ.get("OPENJSON_MAX_REQUEST_BODY_BYTES"),
    )
    application.state.project_usage_limit_config = project_usage_limit_config_from_env(
        enabled_raw=os.environ.get("OPENJSON_PROJECT_USAGE_LIMIT_ENABLED"),
        max_documents_raw=os.environ.get("OPENJSON_MAX_PROJECT_DOCUMENTS"),
        max_snapshot_bytes_raw=os.environ.get("OPENJSON_MAX_PROJECT_SNAPSHOT_BYTES"),
    )
    application.state.backup_scheduler_config = backup_scheduler_config_from_env(
        db_path=application.state.db_path,
    )
    application.state.backup_scheduler = BackupScheduler(application.state.backup_scheduler_config)
    configure_request_body_limiting(application, config=request_body_limit_config)
    configure_rate_limiting(application, config=rate_limit_config)
    configure_request_observability(
        application,
        emit_logs=_env_flag(os.environ.get("OPENJSON_REQUEST_LOGGING")),
    )
    cors_origins = _parse_cors_origins(os.environ.get("OPENJSON_CORS_ORIGINS"))
    application.state.cors_origins_configured = bool(cors_origins)
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    if application.state.static_dir.exists():
        application.mount(
            "/static",
            StaticFiles(directory=str(application.state.static_dir)),
            name="static",
        )

    @application.on_event("startup")
    async def realtime_startup() -> None:
        await collaboration_hub.start()
        await application.state.backup_scheduler.start()

    @application.on_event("shutdown")
    async def realtime_shutdown() -> None:
        await application.state.backup_scheduler.stop()
        await collaboration_hub.stop()

    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(request, status_code=exc.status_code, content=exc.as_response())

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        app_error = AppError(
            ErrorCode.INVALID_JSON_SYNTAX,
            "Request body is invalid or malformed.",
            {"errors": exc.errors()},
        )
        return _error_response(request, status_code=app_error.status_code, content=app_error.as_response())

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        app_error = AppError(
            ErrorCode.INTERNAL_ERROR,
            "Unexpected internal error.",
            _unexpected_error_details(
                request,
                exc,
                debug=application.state.debug_error_details,
            ),
        )
        return _error_response(request, status_code=app_error.status_code, content=app_error.as_response())

    @application.get("/health")
    def health_endpoint() -> dict:
        return health_status()

    @application.get("/version")
    def version_endpoint() -> dict:
        return version_status(
            allow_actor_header=application.state.allow_actor_header,
            cors_origins_configured=application.state.cors_origins_configured,
            rate_limit_config=application.state.rate_limit_config,
            websocket_rate_limit_config=application.state.websocket_rate_limit_config,
            request_body_limit_config=application.state.request_body_limit_config,
            project_usage_limit_config=application.state.project_usage_limit_config,
            backup_scheduler_config=application.state.backup_scheduler_config,
        )

    @application.get("/ready")
    def ready_endpoint() -> dict:
        return readiness_status(
            application.state.db_path,
            backup_scheduler_config=application.state.backup_scheduler_config,
        )

    @application.get("/", include_in_schema=False)
    def ui_index_endpoint() -> FileResponse:
        return FileResponse(application.state.static_dir / "index.html")

    @application.get("/app", include_in_schema=False)
    def ui_app_endpoint() -> FileResponse:
        return FileResponse(application.state.static_dir / "index.html")

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon_endpoint() -> FileResponse:
        return FileResponse(application.state.static_dir / "favicon.svg", media_type="image/svg+xml")

    @application.post("/users")
    def create_user_endpoint(request: CreateUserRequest) -> dict:
        return create_user(
            application.state.db_path,
            email=request.email,
            display_name=request.display_name,
        )

    @application.post("/auth/signup")
    def signup_endpoint(request: SignupRequest) -> dict:
        return signup_with_password(
            application.state.db_path,
            email=request.email,
            display_name=request.display_name,
            password=request.password,
        )

    @application.post("/auth/login")
    def login_endpoint(request: LoginRequest) -> dict:
        return login_with_password(
            application.state.db_path,
            email=request.email,
            password=request.password,
        )

    @application.post("/auth/refresh")
    def refresh_endpoint(request: RefreshSessionRequest) -> dict:
        return refresh_session(
            application.state.db_path,
            refresh_token=request.refresh_token,
        )

    @application.post("/auth/logout")
    def logout_endpoint(authorization: AuthorizationHeader = None) -> dict:
        token = parse_bearer_token(authorization)
        if token is None:
            raise AppError(ErrorCode.AUTH_REQUIRED, "Logout requires a bearer session token.")
        return logout_session(application.state.db_path, token=token)

    @application.get("/auth/me")
    def me_endpoint(actor_id: ActorHeader = None) -> dict:
        return get_current_session_user(application.state.db_path, actor_id=actor_id)

    @application.get("/auth/oidc/login")
    def oidc_login_endpoint(
        provider: str = Query(default="default"),
        return_to: str | None = Query(default=None),
    ) -> dict:
        return create_oidc_login_url(
            application.state.db_path,
            provider=provider,
            return_to=return_to,
        )

    @application.post("/auth/oidc/callback")
    def oidc_callback_endpoint(request: OidcCallbackRequest) -> dict:
        return complete_oidc_callback(
            application.state.db_path,
            provider=request.provider,
            state=request.state,
            code=request.code,
        )

    @application.post("/workspaces")
    def create_workspace_endpoint(
        request: CreateWorkspaceRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return create_workspace(
            application.state.db_path,
            actor_id=actor_id,
            name=request.name,
        )

    @application.get("/workspaces")
    def list_workspaces_endpoint(actor_id: ActorHeader = None) -> dict:
        return list_workspaces(application.state.db_path, actor_id=actor_id)

    @application.get("/workspaces/{workspace_id}")
    def get_workspace_endpoint(workspace_id: str, actor_id: ActorHeader = None) -> dict:
        return get_workspace(
            application.state.db_path,
            workspace_id=workspace_id,
            actor_id=actor_id,
        )

    @application.post("/workspaces/{workspace_id}/projects")
    def create_project_endpoint(
        workspace_id: str,
        request: CreateProjectRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return create_project(
            application.state.db_path,
            workspace_id=workspace_id,
            actor_id=actor_id,
            name=request.name,
            description=request.description,
        )

    @application.get("/workspaces/{workspace_id}/projects")
    def list_workspace_projects_endpoint(workspace_id: str, actor_id: ActorHeader = None) -> dict:
        return list_workspace_projects(
            application.state.db_path,
            workspace_id=workspace_id,
            actor_id=actor_id,
        )

    @application.get("/projects/{project_id}")
    def get_project_endpoint(project_id: str, actor_id: ActorHeader = None) -> dict:
        return get_project(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
        )

    @application.get("/projects/{project_id}/usage")
    def get_project_usage_endpoint(project_id: str, actor_id: ActorHeader = None) -> dict:
        return get_project_usage(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
        )

    @application.get("/projects/{project_id}/members")
    def list_project_members_endpoint(project_id: str, actor_id: ActorHeader = None) -> dict:
        return list_project_members(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
        )

    @application.get("/projects/{project_id}/audit-log")
    def list_project_audit_log_endpoint(project_id: str, actor_id: ActorHeader = None) -> dict:
        return list_project_audit_log(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
        )

    @application.get("/projects/{project_id}/activity")
    def get_project_activity_endpoint(
        project_id: str,
        source: str | None = "all",
        activity_actor_id: str | None = Query(default=None, alias="actor_id"),
        document_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        actor_id: ActorHeader = None,
    ) -> dict:
        return get_project_activity(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            source=source,
            activity_actor_id=activity_actor_id,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

    @application.post("/projects/{project_id}/offline-sync")
    def offline_sync_endpoint(
        project_id: str,
        request: OfflineSyncBatchRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return apply_offline_sync_batch(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            items=[item.model_dump(exclude_unset=True) for item in request.items],
        )

    @application.get("/projects/{project_id}/export")
    def export_project_archive_endpoint(
        project_id: str,
        include_deleted: bool = False,
        include_comments: bool = False,
        include_reviews: bool = False,
        include_audit_log: bool = False,
        actor_id: ActorHeader = None,
    ) -> dict:
        return export_project_archive(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            include_deleted=include_deleted,
            include_comments=include_comments,
            include_reviews=include_reviews,
            include_audit_log=include_audit_log,
        )

    @application.get("/projects/{project_id}/integrity/replay")
    def project_replay_integrity_endpoint(
        project_id: str,
        include_deleted: bool = True,
        actor_id: ActorHeader = None,
    ) -> dict:
        return check_project_replay_integrity(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            include_deleted=include_deleted,
        )

    @application.get("/projects/{project_id}/integrity/events")
    def project_event_chain_integrity_endpoint(
        project_id: str,
        include_deleted: bool = True,
        actor_id: ActorHeader = None,
    ) -> dict:
        return check_project_event_chain_integrity(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            include_deleted=include_deleted,
        )

    @application.get("/documents/{document_id}/integrity/replay")
    def document_replay_integrity_endpoint(document_id: str, actor_id: ActorHeader = None) -> dict:
        return check_document_replay_integrity(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
        )

    @application.get("/documents/{document_id}/integrity/events")
    def document_event_chain_integrity_endpoint(document_id: str, actor_id: ActorHeader = None) -> dict:
        return check_document_event_chain_integrity(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
        )

    @application.get("/projects/{project_id}/validation-report")
    def project_validation_report_endpoint(
        project_id: str,
        include_deleted: bool = False,
        only_invalid: bool = False,
        actor_id: ActorHeader = None,
    ) -> dict:
        return get_project_validation_report(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            include_deleted=include_deleted,
            only_invalid=only_invalid,
        )

    @application.post("/projects/{project_id}/api-tokens")
    def create_project_api_token_endpoint(
        project_id: str,
        request: CreateApiTokenRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return create_project_api_token(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            name=request.name,
        )

    @application.get("/projects/{project_id}/api-tokens")
    def list_project_api_tokens_endpoint(project_id: str, actor_id: ActorHeader = None) -> dict:
        return list_project_api_tokens(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
        )

    @application.delete("/projects/{project_id}/api-tokens/{token_id}")
    def revoke_project_api_token_endpoint(
        project_id: str,
        token_id: str,
        actor_id: ActorHeader = None,
    ) -> dict:
        return revoke_project_api_token(
            application.state.db_path,
            project_id=project_id,
            token_id=token_id,
            actor_id=actor_id,
        )

    @application.post("/projects/{project_id}/invitations")
    def create_project_invitation_endpoint(
        project_id: str,
        request: CreateProjectInvitationRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        invitation = create_project_invitation(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            email=request.email,
            role=request.role,
        )
        if request.send_email:
            invitation["email_delivery"] = send_invitation_email(
                application.state.db_path,
                invitation=invitation,
                token=invitation["token"],
            )
        return invitation

    @application.get("/projects/{project_id}/invitations")
    def list_project_invitations_endpoint(project_id: str, actor_id: ActorHeader = None) -> dict:
        return list_project_invitations(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
        )

    @application.post("/invitations/accept")
    def accept_project_invitation_endpoint(
        request: AcceptInvitationRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return accept_project_invitation(
            application.state.db_path,
            token=request.token,
            actor_id=actor_id,
        )

    @application.post("/projects/{project_id}/members")
    def add_project_member_endpoint(
        project_id: str,
        request: AddProjectMemberRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return add_project_member(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            user_id=request.user_id,
            role=request.role,
        )

    @application.patch("/projects/{project_id}/members/{user_id}")
    def update_project_member_endpoint(
        project_id: str,
        user_id: str,
        request: UpdateProjectMemberRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return update_project_member(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            user_id=user_id,
            role=request.role,
        )

    @application.delete("/projects/{project_id}/members/{user_id}")
    def remove_project_member_endpoint(
        project_id: str,
        user_id: str,
        actor_id: ActorHeader = None,
    ) -> dict:
        return remove_project_member(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            user_id=user_id,
        )

    @application.post("/projects/{project_id}/documents")
    def create_document_endpoint(
        project_id: str,
        request: CreateDocumentRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return create_document(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            full_path=request.full_path,
            content=request.content,
            schema_id=request.schema_id,
        )

    @application.get("/projects/{project_id}/documents")
    def list_project_documents_endpoint(
        project_id: str,
        include_deleted: bool = False,
        path_prefix: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        actor_id: ActorHeader = None,
    ) -> dict:
        return list_project_documents(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
            q=q,
            limit=limit,
            offset=offset,
        )

    @application.post("/projects/{project_id}/imports/zip-preview")
    async def preview_zip_import_endpoint(
        project_id: str,
        request: Request,
        actor_id: ActorHeader = None,
    ) -> dict:
        return preview_zip_import(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            archive_bytes=await request.body(),
        )

    @application.post("/projects/{project_id}/imports/zip-apply")
    async def apply_zip_import_endpoint(
        project_id: str,
        request: Request,
        reason: str | None = None,
        actor_id: ActorHeader = None,
    ) -> dict:
        return apply_zip_import(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            archive_bytes=await request.body(),
            reason=reason,
        )

    @application.get("/projects/{project_id}/document-tree")
    def get_project_document_tree_endpoint(
        project_id: str,
        include_deleted: bool = False,
        path_prefix: str | None = None,
        actor_id: ActorHeader = None,
    ) -> dict:
        return get_project_document_tree(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
        )

    @application.get("/projects/{project_id}/editor-bootstrap")
    def get_project_editor_bootstrap_endpoint(
        project_id: str,
        selected_document_id: str | None = None,
        include_validation: bool = True,
        recent_events_limit: int = 10,
        include_deleted: bool = False,
        path_prefix: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        actor_id: ActorHeader = None,
    ) -> dict:
        return get_project_editor_bootstrap(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            selected_document_id=selected_document_id,
            include_validation=include_validation,
            recent_events_limit=recent_events_limit,
            include_deleted=include_deleted,
            path_prefix=path_prefix,
            q=q,
            limit=limit,
            offset=offset,
        )

    @application.get("/projects/{project_id}/document-events")
    def list_project_document_events_endpoint(
        project_id: str,
        event_type: str | None = None,
        event_actor_id: EventActorQuery = None,
        document_id: str | None = None,
        changed_path: str | None = None,
        limit: int = 50,
        offset: int = 0,
        actor_id: ActorHeader = None,
    ) -> dict:
        return list_project_document_events(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            event_type=event_type,
            event_actor_id=event_actor_id,
            document_id=document_id,
            changed_path=changed_path,
            limit=limit,
            offset=offset,
        )

    @application.get("/projects/{project_id}/document-search")
    def search_project_documents_endpoint(
        project_id: str,
        q: str | None = None,
        path: str | None = None,
        include_deleted: bool = False,
        limit: int = 50,
        offset: int = 0,
        max_matches_per_document: int = 5,
        actor_id: ActorHeader = None,
    ) -> dict:
        return search_project_documents(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            q=q or "",
            path=path,
            include_deleted=include_deleted,
            limit=limit,
            offset=offset,
            max_matches_per_document=max_matches_per_document,
        )

    @application.get("/documents/{document_id}")
    def get_document_endpoint(document_id: str, actor_id: ActorHeader = None) -> dict:
        return get_document(application.state.db_path, document_id, actor_id=actor_id)

    @application.get("/documents/{document_id}/editor-state")
    def get_document_editor_state_endpoint(
        document_id: str,
        include_validation: bool = True,
        recent_events_limit: int = 10,
        actor_id: ActorHeader = None,
    ) -> dict:
        return get_document_editor_state(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            include_validation=include_validation,
            recent_events_limit=recent_events_limit,
        )

    @application.get("/documents/{document_id}/collaboration-state")
    def get_collaboration_state_endpoint(
        document_id: str,
        since_version: int | None = None,
        actor_id: ActorHeader = None,
    ) -> dict:
        return get_collaboration_state(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            since_version=since_version,
        )

    @application.post("/documents/{document_id}/presence")
    def upsert_editor_presence_endpoint(
        document_id: str,
        request: EditorPresenceRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return upsert_editor_presence(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            status=request.status,
            base_version=request.base_version,
            dirty=request.dirty,
            cursor_path=request.cursor_path,
        )

    @application.delete("/documents/{document_id}/presence")
    def leave_editor_presence_endpoint(document_id: str, actor_id: ActorHeader = None) -> dict:
        return leave_editor_presence(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
        )

    @application.websocket("/ws/documents/{document_id}/collaboration")
    async def document_collaboration_websocket(
        websocket: WebSocket,
        document_id: str,
        actor_id: str | None = Query(default=None),
        token: str | None = Query(default=None),
    ) -> None:
        await websocket.accept()
        if token:
            try:
                token_context = authenticate_bearer_token(application.state.db_path, token)
                if token_context["token_type"] == "api_token":
                    from app.auth_service import enforce_api_token_scope

                    enforce_api_token_scope(
                        application.state.db_path,
                        token_project_id=token_context["project_id"],
                        method="GET",
                        path=f"/documents/{document_id}",
                    )
                if actor_id is not None and actor_id != token_context["actor_id"]:
                    raise AppError(
                        ErrorCode.PERMISSION_DENIED,
                        "actor_id does not match bearer token actor.",
                        {"actor_id": actor_id},
                    )
                actor_id = token_context["actor_id"]
            except AppError as exc:
                await websocket.send_json(websocket_error_payload(exc))
                await websocket.close(code=1008)
                return
        elif actor_id and not application.state.allow_actor_header:
            error = AppError(
                ErrorCode.AUTH_REQUIRED,
                "Bearer token authentication is required.",
                {"actor_query_allowed": False},
            )
            await websocket.send_json(websocket_error_payload(error))
            await websocket.close(code=1008)
            return
        if not actor_id:
            error = AppError(
                ErrorCode.AUTH_REQUIRED,
                "WebSocket collaboration requires actor information.",
            )
            await websocket.send_json(websocket_error_payload(error))
            await websocket.close(code=1008)
            return

        connected = False
        try:
            state = get_collaboration_state(
                application.state.db_path,
                document_id=document_id,
                actor_id=actor_id,
                since_version=None,
            )
            await collaboration_hub.connect(document_id, websocket)
            connected = True
            await websocket.send_json(
                {
                    "type": "collaboration_state",
                    "reason": "connected",
                    "state": state,
                }
            )
            websocket_rate_limit_config = application.state.websocket_rate_limit_config
            websocket_rate_limiter = (
                FixedWindowRateLimiter(
                    limit=websocket_rate_limit_config.requests,
                    window_seconds=websocket_rate_limit_config.window_seconds,
                )
                if websocket_rate_limit_config.enabled
                else None
            )

            while True:
                try:
                    message = await websocket.receive_json()
                    if websocket_rate_limiter is not None:
                        rate_result = websocket_rate_limiter.check("messages")
                        if not rate_result["allowed"]:
                            await websocket.send_json(
                                websocket_error_payload(
                                    AppError(
                                        ErrorCode.RATE_LIMITED,
                                        "Too many WebSocket messages. Please retry after the rate limit window resets.",
                                        {
                                            "limit": rate_result["limit"],
                                            "window_seconds": websocket_rate_limit_config.window_seconds,
                                            "retry_after_seconds": rate_result["reset_seconds"],
                                        },
                                    )
                                )
                            )
                            await websocket.close(code=1008)
                            return
                    if not isinstance(message, dict):
                        await websocket.send_json(
                            invalid_realtime_message(
                                "WebSocket collaboration messages must be JSON objects.",
                            )
                        )
                        continue
                    message_type = message.get("type")
                    if message_type == "presence":
                        try:
                            base_version = int(message.get("base_version", state["current_version"]))
                        except (TypeError, ValueError):
                            raise AppError(
                                ErrorCode.INVALID_REQUEST,
                                "base_version must be an integer.",
                                {"base_version": message.get("base_version")},
                            )
                        state = upsert_editor_presence(
                            application.state.db_path,
                            document_id=document_id,
                            actor_id=actor_id,
                            status=str(message.get("status") or "viewing"),
                            base_version=base_version,
                            dirty=bool(message.get("dirty", False)),
                            cursor_path=message.get("cursor_path"),
                        )
                        await collaboration_hub.broadcast_state(
                            document_id,
                            state,
                            reason="presence",
                        )
                    elif message_type == "refresh":
                        raw_since_version = message.get("since_version")
                        try:
                            since_version = int(raw_since_version) if raw_since_version is not None else None
                        except (TypeError, ValueError):
                            raise AppError(
                                ErrorCode.INVALID_REQUEST,
                                "since_version must be an integer.",
                                {"since_version": raw_since_version},
                            )
                        state = get_collaboration_state(
                            application.state.db_path,
                            document_id=document_id,
                            actor_id=actor_id,
                            since_version=since_version,
                        )
                        await collaboration_hub.broadcast_state(
                            document_id,
                            state,
                            reason="refresh",
                        )
                    elif message_type == "text_session.join":
                        text_state = await text_collaboration_manager.join(
                            application.state.db_path,
                            document_id=document_id,
                            actor_id=actor_id,
                        )
                        await websocket.send_json(text_state)
                    elif message_type == "text_session.op":
                        accepted = await text_collaboration_manager.apply_operation(
                            application.state.db_path,
                            document_id=document_id,
                            actor_id=actor_id,
                            message=message,
                        )
                        if accepted.get("idempotent_replay"):
                            await websocket.send_json(accepted)
                        else:
                            await collaboration_hub.broadcast(document_id, accepted)
                    elif message_type == "text_session.commit":
                        committed = await text_collaboration_manager.commit(
                            application.state.db_path,
                            document_id=document_id,
                            actor_id=actor_id,
                            message=message,
                        )
                        await collaboration_hub.broadcast(document_id, committed)
                        state = get_collaboration_state(
                            application.state.db_path,
                            document_id=document_id,
                            actor_id=actor_id,
                            since_version=None,
                        )
                        await collaboration_hub.broadcast_state(
                            document_id,
                            state,
                            reason="text_session.commit",
                        )
                    elif message_type == "ping":
                        await websocket.send_json({"type": "pong"})
                    else:
                        await websocket.send_json(
                            invalid_realtime_message(
                                "Unsupported WebSocket collaboration message type.",
                                {"type": message_type},
                            )
                        )
                except AppError as exc:
                    await websocket.send_json(websocket_error_payload(exc))
                    if exc.code in {
                        ErrorCode.AUTH_REQUIRED,
                        ErrorCode.PERMISSION_DENIED,
                        ErrorCode.DOCUMENT_NOT_FOUND,
                    }:
                        await websocket.close(code=1008)
                        return
                except ValueError:
                    await websocket.send_json(
                        invalid_realtime_message(
                            "WebSocket collaboration messages must be valid JSON.",
                        )
                    )
        except WebSocketDisconnect:
            pass
        finally:
            if connected:
                await collaboration_hub.disconnect(document_id, websocket)
                try:
                    state = leave_editor_presence(
                        application.state.db_path,
                        document_id=document_id,
                        actor_id=actor_id,
                    )
                except AppError:
                    return
                await collaboration_hub.broadcast_state(
                    document_id,
                    state,
                    reason="leave",
                )

    @application.patch("/documents/{document_id}")
    async def patch_document_endpoint(
        document_id: str,
        request: PatchDocumentRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        result = patch_document(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=request.base_version,
            patch=request.patch,
            reason=request.reason,
        )
        await _broadcast_document_mutation_checkpoint(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            previous_version=result.get("previous_version"),
            reason="document.patch",
        )
        return result

    @application.post("/documents/{document_id}/patch-preview")
    def patch_preview_endpoint(
        document_id: str,
        request: PatchPreviewRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return preview_document_patch(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=request.base_version,
            patch=request.patch,
        )

    @application.post("/documents/{document_id}/content-preview")
    def content_preview_endpoint(
        document_id: str,
        request: ContentPreviewRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        fields = _request_fields_set(request)
        return preview_document_content_update(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=request.base_version,
            content=request.content,
            content_text=request.content_text,
            content_provided="content" in fields,
            content_text_provided="content_text" in fields,
        )

    @application.post("/documents/{document_id}/content-conflict-preview")
    def content_conflict_preview_endpoint(
        document_id: str,
        request: ContentConflictPreviewRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        fields = _request_fields_set(request)
        return preview_document_content_conflict(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=request.base_version,
            content=request.content,
            content_text=request.content_text,
            content_provided="content" in fields,
            content_text_provided="content_text" in fields,
        )

    @application.put("/documents/{document_id}/content")
    async def content_update_endpoint(
        document_id: str,
        request: ContentUpdateRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        fields = _request_fields_set(request)
        result = update_document_content(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=request.base_version,
            content=request.content,
            content_text=request.content_text,
            content_provided="content" in fields,
            content_text_provided="content_text" in fields,
            reason=request.reason,
            merge_strategy=request.merge_strategy,
        )
        await _broadcast_document_mutation_checkpoint(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            previous_version=result.get("previous_version"),
            reason="document.content",
        )
        return result

    @application.delete("/documents/{document_id}")
    def delete_document_endpoint(
        document_id: str,
        request: DeleteDocumentRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return delete_document(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=request.base_version,
            reason=request.reason,
        )

    @application.post("/documents/{document_id}/restore")
    def restore_document_endpoint(
        document_id: str,
        request: RestoreDocumentRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return restore_document(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=request.base_version,
            reason=request.reason,
        )

    @application.get("/documents/{document_id}/history")
    def history_endpoint(document_id: str, actor_id: ActorHeader = None) -> dict:
        return get_history(application.state.db_path, document_id, actor_id=actor_id)

    @application.get("/documents/{document_id}/history/{version}")
    def history_version_endpoint(document_id: str, version: int, actor_id: ActorHeader = None) -> dict:
        return get_document_version(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            version=version,
        )

    @application.get("/documents/{document_id}/events/{event_id}")
    def document_event_detail_endpoint(
        document_id: str,
        event_id: str,
        include_snapshots: bool = False,
        actor_id: ActorHeader = None,
    ) -> dict:
        return get_document_event_detail(
            application.state.db_path,
            document_id=document_id,
            event_id=event_id,
            actor_id=actor_id,
            include_snapshots=include_snapshots,
        )

    @application.get("/documents/{document_id}/path-history")
    def path_history_endpoint(document_id: str, path: str = "", actor_id: ActorHeader = None) -> dict:
        return get_document_path_history(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            path=path,
        )

    @application.get("/documents/{document_id}/blame")
    def blame_endpoint(document_id: str, path: str = "", actor_id: ActorHeader = None) -> dict:
        return get_document_path_blame(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            path=path,
        )

    @application.get("/documents/{document_id}/diff")
    def diff_endpoint(document_id: str, from_version: int, to_version: int, actor_id: ActorHeader = None) -> dict:
        return diff_document_versions(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            from_version=from_version,
            to_version=to_version,
        )

    @application.post("/documents/{document_id}/rollback")
    async def rollback_endpoint(
        document_id: str,
        request: RollbackDocumentRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        result = rollback_document(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            base_version=request.base_version,
            target_version=request.target_version,
            reason=request.reason,
        )
        await _broadcast_document_mutation_checkpoint(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            previous_version=result.get("previous_version"),
            reason="document.rollback",
        )
        return result

    @application.post("/projects/{project_id}/schemas")
    def create_schema_endpoint(
        project_id: str,
        request: CreateSchemaRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return create_schema(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            name=request.name,
            version=request.version,
            schema_json=request.schema_,
            file_pattern=request.file_pattern,
        )

    @application.get("/projects/{project_id}/schemas")
    def list_schemas_endpoint(project_id: str, actor_id: ActorHeader = None) -> dict:
        return list_project_schemas(application.state.db_path, project_id, actor_id=actor_id)

    @application.get("/projects/{project_id}/schema-matches")
    def preview_project_schema_matches_endpoint(
        project_id: str,
        full_path: str | None = None,
        actor_id: ActorHeader = None,
    ) -> dict:
        return preview_project_schema_matches(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            full_path=full_path,
        )

    @application.get("/schemas/{schema_id}")
    def get_schema_endpoint(schema_id: str, actor_id: ActorHeader = None) -> dict:
        return get_schema(application.state.db_path, schema_id, actor_id=actor_id)

    @application.get("/schemas/{schema_id}/usage")
    def get_schema_usage_endpoint(
        schema_id: str,
        include_deleted: bool = False,
        only_invalid: bool = False,
        limit: int = 50,
        offset: int = 0,
        actor_id: ActorHeader = None,
    ) -> dict:
        return get_schema_usage(
            application.state.db_path,
            schema_id=schema_id,
            actor_id=actor_id,
            include_deleted=include_deleted,
            only_invalid=only_invalid,
            limit=limit,
            offset=offset,
        )

    @application.post("/documents/{document_id}/validate")
    def validate_document_endpoint(document_id: str, actor_id: ActorHeader = None) -> dict:
        return validate_document(application.state.db_path, document_id, actor_id=actor_id)

    @application.post("/documents/{document_id}/comment-threads")
    def create_comment_thread_endpoint(
        document_id: str,
        request: CreateCommentThreadRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return create_comment_thread(
            application.state.db_path,
            document_id=document_id,
            actor_id=actor_id,
            body=request.body,
            anchor_type=request.anchor_type,
            path=request.path,
            event_id=request.event_id,
        )

    @application.get("/documents/{document_id}/comment-threads")
    def list_comment_threads_endpoint(document_id: str, actor_id: ActorHeader = None) -> dict:
        return list_comment_threads(application.state.db_path, document_id=document_id, actor_id=actor_id)

    @application.post("/comment-threads/{thread_id}/comments")
    def add_comment_endpoint(
        thread_id: str,
        request: AddCommentRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return add_comment(
            application.state.db_path,
            thread_id=thread_id,
            actor_id=actor_id,
            body=request.body,
        )

    @application.post("/comment-threads/{thread_id}/resolve")
    def resolve_comment_thread_endpoint(thread_id: str, actor_id: ActorHeader = None) -> dict:
        return resolve_comment_thread(application.state.db_path, thread_id=thread_id, actor_id=actor_id)

    @application.post("/comment-threads/{thread_id}/reopen")
    def reopen_comment_thread_endpoint(thread_id: str, actor_id: ActorHeader = None) -> dict:
        return reopen_comment_thread(application.state.db_path, thread_id=thread_id, actor_id=actor_id)

    @application.post("/projects/{project_id}/review-requests")
    def create_review_request_endpoint(
        project_id: str,
        request: CreateReviewRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return create_review_request(
            application.state.db_path,
            project_id=project_id,
            actor_id=actor_id,
            title=request.title,
            description=request.description,
            changes=[change.model_dump() for change in request.changes],
        )

    @application.get("/projects/{project_id}/review-requests")
    def list_project_review_requests_endpoint(project_id: str, actor_id: ActorHeader = None) -> dict:
        return list_project_review_requests(application.state.db_path, project_id=project_id, actor_id=actor_id)

    @application.get("/review-requests/{review_request_id}")
    def get_review_request_endpoint(review_request_id: str, actor_id: ActorHeader = None) -> dict:
        return get_review_request(
            application.state.db_path,
            review_request_id=review_request_id,
            actor_id=actor_id,
        )

    @application.post("/review-requests/{review_request_id}/approve")
    def approve_review_request_endpoint(
        review_request_id: str,
        request: ReviewDecisionRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return approve_review_request(
            application.state.db_path,
            review_request_id=review_request_id,
            actor_id=actor_id,
            comment=request.comment,
        )

    @application.post("/review-requests/{review_request_id}/request-changes")
    def request_review_changes_endpoint(
        review_request_id: str,
        request: ReviewDecisionRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return request_review_changes(
            application.state.db_path,
            review_request_id=review_request_id,
            actor_id=actor_id,
            comment=request.comment,
        )

    @application.post("/review-requests/{review_request_id}/comment")
    def comment_on_review_request_endpoint(
        review_request_id: str,
        request: ReviewCommentRequest,
        actor_id: ActorHeader = None,
    ) -> dict:
        return comment_on_review_request(
            application.state.db_path,
            review_request_id=review_request_id,
            actor_id=actor_id,
            comment=request.comment,
        )

    @application.post("/review-requests/{review_request_id}/apply")
    def apply_review_request_endpoint(review_request_id: str, actor_id: ActorHeader = None) -> dict:
        return apply_review_request(
            application.state.db_path,
            review_request_id=review_request_id,
            actor_id=actor_id,
        )

    return application


app = create_app()
