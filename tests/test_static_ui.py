from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import connect, init_db
from app.main import create_app


class StaticUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _counts(self) -> dict[str, int]:
        with connect(self.db_path) as conn:
            return {
                "documents": conn.execute("SELECT COUNT(*) AS count FROM json_documents").fetchone()["count"],
                "events": conn.execute("SELECT COUNT(*) AS count FROM document_events").fetchone()["count"],
            }

    def test_static_editor_shell_routes_are_public_and_do_not_mutate(self) -> None:
        client = TestClient(create_app(self.db_path))
        before = self._counts()

        index = client.get("/")
        app = client.get("/app")
        css = client.get("/static/styles.css")
        js = client.get("/static/app.js")
        favicon = client.get("/favicon.ico")

        self.assertEqual(index.status_code, 200)
        self.assertIn("text/html", index.headers["content-type"])
        self.assertIn("OpenJson", index.text)
        self.assertIn("authScreen", index.text)
        self.assertIn("projectScreen", index.text)
        self.assertIn("workspaceShell", index.text)
        self.assertIn("workspaceNameInput", index.text)
        self.assertIn("projectNameInput", index.text)
        self.assertIn("showCreateProjectButton", index.text)
        self.assertIn("cancelProjectCreateButton", index.text)
        self.assertIn("projectListPanel", index.text)
        self.assertIn("projectCreatePanel", index.text)
        self.assertIn("projectList", index.text)
        self.assertIn("projectInviteTokenInput", index.text)
        self.assertIn("JSON editor", index.text)
        self.assertIn("copyLinkButton", index.text)
        self.assertIn("editorFileInput", index.text)
        self.assertIn("conflictKeepLocalButton", index.text)
        self.assertIn("schemaPanel", index.text)
        self.assertIn("schemaSelect", index.text)
        self.assertIn("schemaMatchPanel", index.text)
        self.assertIn("zipFileInput", index.text)
        self.assertIn("zipImportOutput", index.text)
        self.assertIn("teamMembersOutput", index.text)
        self.assertIn("signupButton", index.text)
        self.assertIn("loginButton", index.text)
        self.assertIn("logoutButton", index.text)
        self.assertIn("createInviteButton", index.text)
        self.assertIn("acceptInviteButton", index.text)
        self.assertIn("inviteLinkInput", index.text)
        self.assertIn("copyInviteLinkButton", index.text)
        self.assertIn("autosaveToggle", index.text)
        self.assertIn("autoMergeToggle", index.text)
        self.assertIn("liveTextToggle", index.text)
        self.assertIn("commitLiveButton", index.text)
        self.assertIn("collaborationPanel", index.text)
        self.assertIn("commentsPanel", index.text)
        self.assertIn("commentsButton", index.text)
        self.assertIn("commentAnchorTypeSelect", index.text)
        self.assertIn("commentPathInput", index.text)
        self.assertIn("commentEventIdInput", index.text)
        self.assertIn("commentBodyInput", index.text)
        self.assertIn("createCommentThreadButton", index.text)
        self.assertNotIn("Create User", index.text)
        self.assertNotIn("Add Member", index.text)
        self.assertNotIn(">Actor<", index.text)
        self.assertNotIn(">Token<", index.text)
        self.assertNotIn("connectionForm", index.text)
        self.assertNotIn("actorIdInput", index.text)
        self.assertNotIn("projectIdInput", index.text)
        self.assertNotIn("tokenInput", index.text)
        self.assertEqual(app.status_code, 200)
        self.assertIn("text/html", app.headers["content-type"])
        self.assertEqual(css.status_code, 200)
        self.assertIn("text/css", css.headers["content-type"])
        self.assertIn("workspace-grid", css.text)
        self.assertIn("entry-screen", css.text)
        self.assertIn("project-row", css.text)
        self.assertIn("project-mode-actions", css.text)
        self.assertIn("project-create-panel", css.text)
        self.assertIn("top-actions", css.text)
        self.assertIn("member-badge", css.text)
        self.assertIn(".hidden", css.text)
        self.assertIn("schema-row", css.text)
        self.assertIn("comment-thread", css.text)
        self.assertEqual(js.status_code, 200)
        self.assertIn("javascript", js.headers["content-type"])
        self.assertIn("loadProjectHome", js.text)
        self.assertIn("createProjectFromGate", js.text)
        self.assertIn("showProjectListMode", js.text)
        self.assertIn("showProjectCreateMode", js.text)
        self.assertIn("renderProjectHome", js.text)
        self.assertIn('apiFetch("/workspaces"', js.text)
        self.assertIn("/workspaces/${encodeURIComponent(workspace.id)}/projects", js.text)
        project_creator = js.text.split("async function createProjectFromGate()", 1)[1].split(
            "async function openProject", 1
        )[0]
        self.assertIn("const sessionUserId = state.userId", project_creator)
        self.assertIn("const workspaceNameText = els.workspaceName.value", project_creator)
        self.assertIn("const projectNameText = els.projectName.value", project_creator)
        self.assertIn("const descriptionText = els.projectDescription.value", project_creator)
        self.assertIn("const requestId = state.createProjectRequestId + 1", project_creator)
        self.assertIn("state.createProjectRequestId = requestId", project_creator)
        self.assertIn("state.creatingProject = true", project_creator)
        self.assertIn("if (!isCurrentCreateProjectRequest(requestId, sessionUserId, workspaceNameText, projectNameText, descriptionText))", project_creator)
        self.assertIn("function isCurrentCreateProjectRequest(requestId, sessionUserId, workspaceNameText, projectNameText, descriptionText)", js.text)
        self.assertIn("state.createProjectRequestId === requestId", js.text)
        self.assertIn("state.userId === sessionUserId", js.text)
        self.assertIn("els.workspaceName.value === workspaceNameText", js.text)
        self.assertIn("els.projectName.value === projectNameText", js.text)
        self.assertIn("els.projectDescription.value === descriptionText", js.text)
        self.assertIn("!els.projectCreatePanel.classList.contains(\"hidden\")", js.text)
        self.assertIn("function invalidateCreateProjectRequests()", js.text)
        self.assertIn("state.createProjectRequestId += 1", js.text)
        self.assertIn("state.creatingProject = false", js.text)
        self.assertIn("els.workspaceName.disabled = busy || !state.token", js.text)
        self.assertIn("els.projectName.disabled = busy || !state.token", js.text)
        self.assertIn("els.projectDescription.disabled = busy || !state.token", js.text)
        self.assertIn("els.workspaceName.addEventListener(\"input\"", js.text)
        self.assertIn("els.projectName.addEventListener(\"input\"", js.text)
        self.assertIn("els.projectDescription.addEventListener(\"input\"", js.text)
        signup_loader = js.text.split("async function signupWithPassword()", 1)[1].split(
            "async function loginWithPassword", 1
        )[0]
        self.assertIn("const displayNameText = els.authName.value", signup_loader)
        self.assertIn("const emailText = els.authEmail.value", signup_loader)
        self.assertIn("const pendingInviteToken = state.pendingInviteToken", signup_loader)
        self.assertIn("const requestId = state.authRequestId + 1", signup_loader)
        self.assertIn("state.authRequestId = requestId", signup_loader)
        self.assertIn("state.authenticating = true", signup_loader)
        self.assertIn("if (!isCurrentAuthRequest(requestId, emailText, pendingInviteToken, displayNameText))", signup_loader)
        login_loader = js.text.split("async function loginWithPassword()", 1)[1].split(
            "async function logoutSession", 1
        )[0]
        self.assertIn("const emailText = els.authEmail.value", login_loader)
        self.assertIn("const pendingInviteToken = state.pendingInviteToken", login_loader)
        self.assertIn("const requestId = state.authRequestId + 1", login_loader)
        self.assertIn("state.authRequestId = requestId", login_loader)
        self.assertIn("state.authenticating = true", login_loader)
        self.assertIn("if (!isCurrentAuthRequest(requestId, emailText, pendingInviteToken))", login_loader)
        logout_loader = js.text.split("async function logoutSession()", 1)[1].split(
            "function isCurrentAuthRequest", 1
        )[0]
        self.assertIn("const sessionUserId = state.userId", logout_loader)
        self.assertIn("const sessionToken = state.token", logout_loader)
        self.assertIn("const requestId = state.logoutRequestId + 1", logout_loader)
        self.assertIn("state.logoutRequestId = requestId", logout_loader)
        self.assertIn("state.loggingOut = true", logout_loader)
        self.assertIn("if (!isCurrentLogoutRequest(requestId, sessionUserId, sessionToken))", logout_loader)
        self.assertIn("function isCurrentAuthRequest(requestId, emailText, pendingInviteToken, displayNameText)", js.text)
        self.assertIn("state.authRequestId === requestId", js.text)
        self.assertIn("els.authEmail.value === emailText", js.text)
        self.assertIn("state.pendingInviteToken === pendingInviteToken", js.text)
        self.assertIn("displayNameText === undefined || els.authName.value === displayNameText", js.text)
        self.assertIn("function invalidateAuthRequests()", js.text)
        self.assertIn("state.authRequestId += 1", js.text)
        self.assertIn("state.authenticating = false", js.text)
        self.assertIn("function isCurrentLogoutRequest(requestId, sessionUserId, sessionToken)", js.text)
        self.assertIn("state.logoutRequestId === requestId", js.text)
        self.assertIn("state.token === sessionToken", js.text)
        self.assertIn("function invalidateLogoutRequests()", js.text)
        self.assertIn("state.logoutRequestId += 1", js.text)
        self.assertIn("state.loggingOut = false", js.text)
        self.assertIn("els.authName.addEventListener(\"input\"", js.text)
        self.assertIn("els.authEmail.addEventListener(\"input\"", js.text)
        self.assertIn("els.authPassword.addEventListener(\"input\"", js.text)
        self.assertIn(
            "invalidateAuthRequests()",
            js.text.split("els.authPassword.addEventListener(\"input\"", 1)[1].split(
                "els.signupButton.addEventListener", 1
            )[0],
        )
        self.assertIn("/editor-bootstrap", js.text)
        self.assertIn("/schemas", js.text)
        self.assertIn("/schema-matches", js.text)
        self.assertIn("/imports/zip-preview", js.text)
        self.assertIn("/imports/zip-apply", js.text)
        zip_file_handler = js.text.split('els.zipFileInput.addEventListener("change"', 1)[1].split(
            "els.zipPreviewButton.addEventListener", 1
        )[0]
        self.assertIn("invalidateZipImportRequests()", zip_file_handler)
        zip_preview = js.text.split("async function previewZipImport()", 1)[1].split(
            "async function applyZipImport", 1
        )[0]
        self.assertIn("const projectId = state.projectId", zip_preview)
        self.assertIn("const file = state.zipFile", zip_preview)
        self.assertIn("const requestId = state.zipPreviewRequestId + 1", zip_preview)
        self.assertIn("state.zipPreviewRequestId = requestId", zip_preview)
        self.assertIn("state.zipPreviewing = true", zip_preview)
        self.assertIn("const body = await file.arrayBuffer()", zip_preview)
        self.assertIn("if (!isCurrentZipPreviewRequest(requestId, projectId, file))", zip_preview)
        self.assertIn("/projects/${encodeURIComponent(projectId)}/imports/zip-preview", zip_preview)
        self.assertIn("state.zipPreview = result", zip_preview)
        zip_apply = js.text.split("async function applyZipImport()", 1)[1].split(
            "async function readJsonFile", 1
        )[0]
        self.assertIn("const projectId = state.projectId", zip_apply)
        self.assertIn("const file = state.zipFile", zip_apply)
        self.assertIn("const preview = state.zipPreview", zip_apply)
        self.assertIn("const selectedDocumentId = state.selectedDocumentId || \"\"", zip_apply)
        self.assertIn("const requestId = state.zipApplyRequestId + 1", zip_apply)
        self.assertIn("state.zipApplyRequestId = requestId", zip_apply)
        self.assertIn("state.zipApplying = true", zip_apply)
        self.assertIn("const body = await file.arrayBuffer()", zip_apply)
        self.assertIn(
            "if (!isCurrentZipApplyRequest(requestId, projectId, file, preview, selectedDocumentId))",
            zip_apply,
        )
        self.assertIn("/projects/${encodeURIComponent(projectId)}/imports/zip-apply", zip_apply)
        self.assertIn("Imported ${file.name} from OpenJson UI", zip_apply)
        self.assertIn("await loadBootstrap(firstCreated ? firstCreated.id : selectedDocumentId || null)", zip_apply)
        self.assertIn("function isCurrentZipPreviewRequest(requestId, projectId, file)", js.text)
        self.assertIn("state.zipPreviewRequestId === requestId", js.text)
        self.assertIn("state.zipFile === file", js.text)
        self.assertIn(
            "function isCurrentZipApplyRequest(requestId, projectId, file, preview, selectedDocumentId)",
            js.text,
        )
        self.assertIn("state.zipApplyRequestId === requestId", js.text)
        self.assertIn("state.zipPreview === preview", js.text)
        self.assertIn("(state.selectedDocumentId || \"\") === selectedDocumentId", js.text)
        self.assertIn("function invalidateZipImportRequests()", js.text)
        self.assertIn("state.zipPreviewRequestId += 1", js.text)
        self.assertIn("state.zipApplyRequestId += 1", js.text)
        self.assertIn("function resetZipImportSelection(message)", js.text)
        self.assertIn("state.zipPreviewing = false", js.text)
        self.assertIn("state.zipApplying = false", js.text)
        self.assertIn("state.authenticating", js.text)
        self.assertIn("state.loggingOut", js.text)
        self.assertIn("state.refreshingSession", js.text)
        self.assertIn("state.creatingProject", js.text)
        self.assertIn("state.creatingInvite", js.text)
        self.assertIn("state.acceptingInvite", js.text)
        self.assertIn("state.creatingDocument", js.text)
        self.assertIn("state.authRequestId", js.text)
        self.assertIn("state.logoutRequestId", js.text)
        self.assertIn("state.sessionRefreshRequestId", js.text)
        self.assertIn("state.sessionRefreshPromise", js.text)
        self.assertIn("state.createFileImportRequestId", js.text)
        self.assertIn("state.editorFileImportRequestId", js.text)
        self.assertIn("state.projectInviteAcceptRequestId", js.text)
        self.assertIn("/projects/${encodeURIComponent(targetProjectId)}/members", js.text)
        self.assertIn("/projects/${encodeURIComponent(targetProjectId)}/usage", js.text)
        self.assertIn("/auth/signup", js.text)
        self.assertIn("/auth/login", js.text)
        self.assertIn("/auth/logout", js.text)
        self.assertIn("/auth/refresh", js.text)
        refresh_loader = js.text.split("async function refreshAccessToken()", 1)[1].split(
            "function isCurrentSessionRefreshRequest", 1
        )[0]
        self.assertIn("const refreshToken = state.refreshToken", refresh_loader)
        self.assertIn("state.refreshingSession && state.sessionRefreshPromise", refresh_loader)
        self.assertIn("return state.sessionRefreshPromise", refresh_loader)
        self.assertIn("const requestId = state.sessionRefreshRequestId + 1", refresh_loader)
        self.assertIn("state.sessionRefreshRequestId = requestId", refresh_loader)
        self.assertIn("state.refreshingSession = true", refresh_loader)
        self.assertIn("refresh_token: refreshToken", refresh_loader)
        self.assertIn("if (!isCurrentSessionRefreshRequest(requestId, refreshToken))", refresh_loader)
        self.assertIn("state.sessionRefreshPromise = refreshPromise", refresh_loader)
        self.assertIn("function isCurrentSessionRefreshRequest(requestId, refreshToken)", js.text)
        self.assertIn("state.sessionRefreshRequestId === requestId && state.refreshToken === refreshToken", js.text)
        self.assertIn("function invalidateSessionRefreshRequests()", js.text)
        self.assertIn("state.sessionRefreshRequestId += 1", js.text)
        self.assertIn("state.refreshingSession = false", js.text)
        self.assertIn("state.sessionRefreshPromise = null", js.text)
        session_clearer_for_auth = js.text.split("function clearSessionState", 1)[1].split(
            "function invitePromptText", 1
        )[0]
        self.assertIn("invalidateAuthRequests()", session_clearer_for_auth)
        self.assertIn("invalidateLogoutRequests()", session_clearer_for_auth)
        self.assertIn("invalidateSessionRefreshRequests()", session_clearer_for_auth)
        self.assertIn("/offline-sync", js.text)
        self.assertIn("/invitations/accept", js.text)
        self.assertIn("/projects/${encodeURIComponent(projectId)}/invitations", js.text)
        self.assertIn("/ws/documents/", js.text)
        self.assertIn("merge_strategy", js.text)
        self.assertIn("/collaboration-state", js.text)
        self.assertIn("/presence", js.text)
        self.assertIn("/content-conflict-preview", js.text)
        self.assertIn("/rollback", js.text)
        self.assertIn("URLSearchParams", js.text)
        self.assertIn("navigator.clipboard", js.text)
        self.assertIn("importEditorFile", js.text)
        self.assertIn("keepLocalBufferOnLatest", js.text)
        self.assertIn("previewCreateSchemaMatch", js.text)
        self.assertIn("renderSchema", js.text)
        schema_match_preview = js.text.split("async function previewCreateSchemaMatch()", 1)[1].split(
            "function renderSchema", 1
        )[0]
        self.assertIn("const requestId = state.schemaMatchRequestId + 1", schema_match_preview)
        self.assertIn("state.schemaMatchRequestId = requestId", schema_match_preview)
        self.assertIn("const projectId = state.projectId", schema_match_preview)
        self.assertIn("/projects/${encodeURIComponent(projectId)}/schema-matches", schema_match_preview)
        self.assertIn("if (!isCurrentSchemaMatchRequest(requestId, projectId, fullPath))", schema_match_preview)
        self.assertIn("function isCurrentSchemaMatchRequest(requestId, projectId, fullPath)", js.text)
        self.assertIn("state.schemaMatchRequestId === requestId", js.text)
        self.assertIn("cleanOptional(els.newPath.value) === fullPath", js.text)
        document_creator = js.text.split("async function createDocument()", 1)[1].split(
            "async function importCreateFile", 1
        )[0]
        self.assertIn("const projectId = state.projectId", document_creator)
        self.assertIn("const selectedDocumentId = state.selectedDocumentId || \"\"", document_creator)
        self.assertIn("const contentText = els.newContent.value", document_creator)
        self.assertIn("const requestId = state.createDocumentRequestId + 1", document_creator)
        self.assertIn("state.createDocumentRequestId = requestId", document_creator)
        self.assertIn("state.creatingDocument = true", document_creator)
        self.assertIn("/projects/${encodeURIComponent(projectId)}/documents", document_creator)
        self.assertIn(
            "if (!isCurrentCreateDocumentRequest(requestId, projectId, selectedDocumentId, fullPath, contentText, schemaId))",
            document_creator,
        )
        self.assertIn(
            "function isCurrentCreateDocumentRequest(requestId, projectId, selectedDocumentId, fullPath, contentText, schemaId)",
            js.text,
        )
        self.assertIn("state.createDocumentRequestId === requestId", js.text)
        self.assertIn("(state.selectedDocumentId || \"\") === selectedDocumentId", js.text)
        self.assertIn("els.newContent.value === contentText", js.text)
        self.assertIn("cleanOptional(els.schemaSelect.value) === schemaId", js.text)
        self.assertIn("!els.createPanel.classList.contains(\"hidden\")", js.text)
        self.assertIn("function invalidateCreateDocumentRequests()", js.text)
        self.assertIn("state.createDocumentRequestId += 1", js.text)
        self.assertIn("state.creatingDocument = false", js.text)
        self.assertIn("syncButtons()", js.text.split("function invalidateCreateDocumentRequests()", 1)[1])
        self.assertIn("els.newContent.addEventListener(\"input\"", js.text)
        create_form_import = js.text.split("async function importCreateFile()", 1)[1].split(
            "async function importEditorFile", 1
        )[0]
        self.assertIn("const projectId = state.projectId", create_form_import)
        self.assertIn("const selectedDocumentId = state.selectedDocumentId || \"\"", create_form_import)
        self.assertIn("const pathText = els.newPath.value", create_form_import)
        self.assertIn("const contentText = els.newContent.value", create_form_import)
        self.assertIn("const requestId = state.createFileImportRequestId + 1", create_form_import)
        self.assertIn("state.createFileImportRequestId = requestId", create_form_import)
        self.assertIn("if (!isCurrentCreateFileImportRequest(", create_form_import)
        self.assertIn("invalidateCreateDocumentRequests()", create_form_import)
        editor_import = js.text.split("async function importEditorFile()", 1)[1].split(
            "async function previewZipImport", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", editor_import)
        self.assertIn("const currentVersion = state.currentVersion", editor_import)
        self.assertIn("const contentText = els.editorBuffer.value", editor_import)
        self.assertIn("const requestId = state.editorFileImportRequestId + 1", editor_import)
        self.assertIn("state.editorFileImportRequestId = requestId", editor_import)
        self.assertIn("if (!isCurrentEditorFileImportRequest(", editor_import)
        self.assertIn("function isCurrentCreateFileImportRequest", js.text)
        self.assertIn("state.createFileImportRequestId === requestId", js.text)
        self.assertIn("selectedFile === file", js.text)
        self.assertIn("els.newPath.value === pathText", js.text)
        self.assertIn("els.newContent.value === contentText", js.text)
        self.assertIn("function invalidateCreateFileImportRequests()", js.text)
        self.assertIn("state.createFileImportRequestId += 1", js.text)
        self.assertIn("function isCurrentEditorFileImportRequest", js.text)
        self.assertIn("state.editorFileImportRequestId === requestId", js.text)
        self.assertIn("state.currentVersion === currentVersion", js.text)
        self.assertIn("els.editorBuffer.value === contentText", js.text)
        self.assertIn("function invalidateEditorFileImportRequests()", js.text)
        self.assertIn("state.editorFileImportRequestId += 1", js.text)
        self.assertIn("invalidateEditorFileImportRequests()", js.text.split("els.editorBuffer.addEventListener(\"input\"", 1)[1])
        self.assertIn("SCHEMA_VALIDATION_FAILED", js.text)
        self.assertIn("renderSchemaValidationFailure", js.text)
        self.assertIn("renderZipImportResult", js.text)
        self.assertIn("apiFetchBinary", js.text)
        self.assertIn("renderCollaboration", js.text)
        self.assertIn("buildEditorCursorPath", js.text)
        self.assertIn("findJsonPointerNearOffset", js.text)
        self.assertIn("cursor_path: buildEditorCursorPath()", js.text)
        self.assertIn("cursor_path: payload.cursor_path", js.text)
        self.assertIn("at ${user.cursor_path || \"/\"}", js.text)
        self.assertIn("event.actor_display_name || event.actor_id", js.text)
        self.assertIn("checkpoint.display_name || checkpoint.actor_id", js.text)
        self.assertIn("user.display_name || user.actor_id", js.text)
        self.assertIn("thread.created_by_display_name || thread.created_by", js.text)
        self.assertIn("comment.author_display_name || comment.author_id", js.text)
        self.assertIn("renderInvitationResult", js.text)
        self.assertIn("Invitation email sent", js.text)
        self.assertIn("buildInviteUrl", js.text)
        self.assertIn("clearInviteResult", js.text)
        self.assertIn("copyInviteLink", js.text)
        self.assertIn("Invite link copied", js.text)
        self.assertIn("pendingInviteToken", js.text)
        self.assertIn("invitePromptText", js.text)
        self.assertIn("acceptPendingInvitation", js.text)
        self.assertIn("acceptInvitationToken", js.text)
        self.assertIn("Joining invited project", js.text)
        self.assertIn("renderTeamPanel", js.text)
        self.assertIn("fetchProjectUsageSafe", js.text)
        self.assertIn("formatBytes", js.text)
        self.assertIn("openCollaborationSocket", js.text)
        self.assertIn("openProjectWorkspaceSocket", js.text)
        self.assertIn("sendRealtimeMessage", js.text)
        self.assertIn("sendPresenceHeartbeat", js.text)
        self.assertIn("activePresenceDocumentId", js.text)
        self.assertIn("sendPresenceLeave(state.activePresenceDocumentId || state.selectedDocumentId)", js.text)
        self.assertIn("targetDocumentId || !state.token", js.text)
        self.assertIn("text_session.join", js.text)
        self.assertIn("text_session.commit", js.text)
        self.assertIn("client_operation_id", js.text)
        self.assertIn("newClientOperationId", js.text)
        self.assertIn("idempotent_replay", js.text)
        self.assertIn("authoritativeText", js.text)
        self.assertIn("liveTextPendingOperation", js.text)
        self.assertIn("finishLocalLiveTextOperation", js.text)
        self.assertIn("hasLocalLiveTextBuffer", js.text)
        self.assertIn("scheduleLiveTextDiffIfNeeded", js.text)
        self.assertIn("Live text session rejoined", js.text)
        self.assertIn("Live text session reset to document", js.text)
        self.assertIn("Local buffer preserved and syncing", js.text)
        self.assertIn("liveTextNeedsResync", js.text)
        self.assertIn("session_reset", js.text)
        self.assertIn("if (payload.document_id !== state.selectedDocumentId)", js.text)
        self.assertIn("loadBootstrap(payload.document_id)", js.text)
        collaboration_socket_handler = js.text.split("function openCollaborationSocket()", 1)[1].split(
            "function sendRealtimeMessage", 1
        )[0]
        self.assertIn("if (state.collaborationSocket !== socket)", collaboration_socket_handler)
        collaboration_state_loader = js.text.split("async function refreshCollaborationState()", 1)[1].split(
            "async function applyCollaborationState", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", collaboration_state_loader)
        self.assertIn("const currentVersion = state.currentVersion", collaboration_state_loader)
        self.assertIn("const requestId = state.collaborationStateRequestId + 1", collaboration_state_loader)
        self.assertIn("state.collaborationStateRequestId = requestId", collaboration_state_loader)
        self.assertIn("/documents/${encodeURIComponent(documentId)}/collaboration-state", collaboration_state_loader)
        self.assertIn("query: { since_version: currentVersion }", collaboration_state_loader)
        self.assertIn(
            "if (!isCurrentCollaborationStateRequest(requestId, documentId, currentVersion))",
            collaboration_state_loader,
        )
        self.assertIn("function isCurrentCollaborationStateRequest(requestId, documentId, currentVersion)", js.text)
        self.assertIn("state.collaborationStateRequestId === requestId", js.text)
        self.assertIn("state.selectedDocumentId === documentId", js.text)
        self.assertIn("state.currentVersion === currentVersion", js.text)
        self.assertIn("function invalidateCollaborationStateRequests()", js.text)
        self.assertIn("state.collaborationStateRequestId += 1", js.text)
        collaboration_stop = js.text.split("function stopCollaborationLoop()", 1)[1].split(
            "function ensureProjectWorkspaceSocket", 1
        )[0]
        self.assertIn("invalidateCollaborationStateRequests()", collaboration_stop)
        self.assertIn("markLiveTextOperationUnacknowledged", js.text)
        self.assertIn("resyncLiveTextSessionAfterConflict", js.text)
        self.assertIn("Live text change is still syncing.", js.text)
        self.assertIn("Syncing latest live text before commit.", js.text)
        self.assertIn("flushOfflineQueue", js.text)
        self.assertIn("Autosaved from OpenJson UI", js.text)
        validation_loader = js.text.split("async function validateSelected()", 1)[1].split(
            "async function previewSelected", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", validation_loader)
        self.assertIn("const currentVersion = state.currentVersion", validation_loader)
        self.assertIn("const requestId = state.validationRequestId + 1", validation_loader)
        self.assertIn("state.validationRequestId = requestId", validation_loader)
        self.assertIn("if (!isCurrentValidationRequest(requestId, documentId, currentVersion))", validation_loader)
        preview_loader = js.text.split("async function previewSelected()", 1)[1].split(
            "async function saveSelected", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", preview_loader)
        self.assertIn("const baseVersion = state.baseVersion", preview_loader)
        self.assertIn("const contentText = els.editorBuffer.value", preview_loader)
        self.assertIn("const requestId = state.previewRequestId + 1", preview_loader)
        self.assertIn("state.previewRequestId = requestId", preview_loader)
        self.assertIn("if (!isCurrentPreviewRequest(requestId, documentId, baseVersion, contentText))", preview_loader)
        conflict_preview_loader = js.text.split("async function loadConflictPreview", 1)[1].split(
            "async function keepLocalBufferOnLatest", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", conflict_preview_loader)
        self.assertIn("const contentText = els.editorBuffer.value", conflict_preview_loader)
        self.assertIn("const requestId = state.conflictPreviewRequestId + 1", conflict_preview_loader)
        self.assertIn("state.conflictPreviewRequestId = requestId", conflict_preview_loader)
        self.assertIn(
            "if (!isCurrentConflictPreviewRequest(requestId, documentId, baseVersion, contentText))",
            conflict_preview_loader,
        )
        history_loader = js.text.split("async function loadHistory()", 1)[1].split(
            "async function loadDiff", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", history_loader)
        self.assertIn("const currentVersion = state.currentVersion", history_loader)
        self.assertIn("const requestId = state.historyRequestId + 1", history_loader)
        self.assertIn("state.historyRequestId = requestId", history_loader)
        self.assertIn("if (!isCurrentHistoryRequest(requestId, documentId, currentVersion))", history_loader)
        diff_loader = js.text.split("async function loadDiff()", 1)[1].split(
            "async function rollbackSelected", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", diff_loader)
        self.assertIn("const currentVersion = state.currentVersion", diff_loader)
        self.assertIn("const requestId = state.diffRequestId + 1", diff_loader)
        self.assertIn("state.diffRequestId = requestId", diff_loader)
        self.assertIn("if (!isCurrentDiffRequest(requestId, documentId, currentVersion, fromVersion, toVersion))", diff_loader)
        rollback_loader = js.text.split("async function rollbackSelected()", 1)[1].split(
            "async function loadCommentThreads", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", rollback_loader)
        self.assertIn("const baseVersion = state.currentVersion", rollback_loader)
        self.assertIn("const requestId = state.rollbackRequestId + 1", rollback_loader)
        self.assertIn("state.rollbackRequestId = requestId", rollback_loader)
        self.assertIn("state.rollingBack = true", rollback_loader)
        self.assertIn("/documents/${encodeURIComponent(documentId)}/rollback", rollback_loader)
        self.assertIn("base_version: baseVersion", rollback_loader)
        self.assertIn("if (!isCurrentRollbackRequest(requestId, documentId, baseVersion, targetVersion))", rollback_loader)
        self.assertIn("await loadBootstrap(documentId)", rollback_loader)
        self.assertIn("function isCurrentValidationRequest(requestId, documentId, currentVersion)", js.text)
        self.assertIn("function isCurrentPreviewRequest(requestId, documentId, baseVersion, contentText)", js.text)
        self.assertIn("function isCurrentConflictPreviewRequest(requestId, documentId, baseVersion, contentText)", js.text)
        self.assertIn("function isCurrentHistoryRequest(requestId, documentId, currentVersion)", js.text)
        self.assertIn("function isCurrentDiffRequest(requestId, documentId, currentVersion, fromVersion, toVersion)", js.text)
        self.assertIn("function isCurrentRollbackRequest(requestId, documentId, baseVersion, targetVersion)", js.text)
        self.assertIn("function invalidateDocumentPanelRequests()", js.text)
        self.assertIn("state.validationRequestId += 1", js.text)
        self.assertIn("state.previewRequestId += 1", js.text)
        self.assertIn("state.conflictPreviewRequestId += 1", js.text)
        self.assertIn("state.historyRequestId += 1", js.text)
        self.assertIn("state.diffRequestId += 1", js.text)
        self.assertIn("function invalidateRollbackRequests()", js.text)
        self.assertIn("state.rollbackRequestId += 1", js.text)
        self.assertIn("state.rollingBack = false", js.text)
        save_loader = js.text.split("async function saveSelected", 1)[1].split(
            "async function loadConflictPreview", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", save_loader)
        self.assertIn("const baseVersion = state.baseVersion", save_loader)
        self.assertIn("const contentText = els.editorBuffer.value", save_loader)
        self.assertIn("const mergeStrategy = state.autoMergeEnabled ? \"auto\" : \"reject\"", save_loader)
        self.assertIn("const requestId = state.saveRequestId + 1", save_loader)
        self.assertIn("state.saveRequestId = requestId", save_loader)
        self.assertIn("state.saving = true", save_loader)
        self.assertIn("/documents/${encodeURIComponent(documentId)}/content", save_loader)
        self.assertIn("if (!isCurrentSaveRequest(requestId, documentId, baseVersion, contentText))", save_loader)
        self.assertIn("queueOfflineSave(savePayload)", save_loader)
        self.assertIn("function isCurrentSaveRequest(requestId, documentId, baseVersion, contentText)", js.text)
        self.assertIn("function invalidateSaveRequests()", js.text)
        self.assertIn("state.saveRequestId += 1", js.text)
        self.assertIn("state.saving = false", js.text)
        self.assertIn("state.zipPreviewing", js.text)
        self.assertIn("state.zipApplying", js.text)
        editor_state_setter = js.text.split("function setSelectedEditorState", 1)[1].split("function clearEditor", 1)[0]
        self.assertIn("state.selectedDocumentId !== editorState.document.id", editor_state_setter)
        self.assertIn("invalidateSaveRequests()", editor_state_setter)
        self.assertIn("invalidateRollbackRequests()", editor_state_setter)
        self.assertIn("invalidateCreateDocumentRequests()", editor_state_setter)
        self.assertIn("invalidateCreateFileImportRequests()", editor_state_setter)
        self.assertIn("invalidateEditorFileImportRequests()", editor_state_setter)
        self.assertIn("loadCommentThreads", js.text)
        self.assertIn("comment_threads.updated", js.text)
        self.assertIn("applyCommentThreadsUpdated", js.text)
        comment_loader = js.text.split("async function loadCommentThreads()", 1)[1].split(
            "async function applyCommentThreadsUpdated", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", comment_loader)
        self.assertIn("const requestId = state.commentThreadsRequestId + 1", comment_loader)
        self.assertIn("state.commentThreadsRequestId = requestId", comment_loader)
        self.assertIn("if (!isCurrentCommentThreadsRequest(requestId, documentId))", comment_loader)
        self.assertIn("function isCurrentCommentThreadsRequest(requestId, documentId)", js.text)
        self.assertIn("function invalidateCommentThreadsRequests()", js.text)
        self.assertIn("state.commentThreadsRequestId += 1", js.text)
        self.assertIn("Notes updated.", js.text)
        self.assertIn("document.lifecycle", js.text)
        self.assertIn("applyDocumentLifecycleUpdate", js.text)
        self.assertIn("Local buffer preserved.", js.text)
        self.assertIn("Document restored at version", js.text)
        self.assertIn("/ws/projects/", js.text)
        self.assertIn("project.documents.changed", js.text)
        self.assertIn("applyProjectDocumentsChanged", js.text)
        project_socket_handler = js.text.split("function openProjectWorkspaceSocket()", 1)[1].split(
            "function openCollaborationSocket()", 1
        )[0]
        self.assertIn("if (state.projectSocket !== socket)", project_socket_handler)
        self.assertNotIn("state.collaborationSocket !== socket", project_socket_handler)
        self.assertIn("Project documents changed. Save or reload", js.text)
        self.assertIn("Project documents updated.", js.text)
        project_documents_changed = js.text.split("async function applyProjectDocumentsChanged", 1)[1].split(
            "async function createCommentThread", 1
        )[0]
        self.assertIn("const projectId = state.projectId", project_documents_changed)
        self.assertIn("const selectedDocumentId = state.selectedDocumentId || \"\"", project_documents_changed)
        self.assertIn("const requestId = state.projectDocumentsChangeRequestId + 1", project_documents_changed)
        self.assertIn("state.projectDocumentsChangeRequestId = requestId", project_documents_changed)
        self.assertIn("await loadBootstrap(selectedDocumentId || null)", project_documents_changed)
        self.assertIn(
            "if (!isCurrentProjectDocumentsChangeRequest(requestId, projectId, selectedDocumentId))",
            project_documents_changed,
        )
        self.assertIn("function isCurrentProjectDocumentsChangeRequest(requestId, projectId, selectedDocumentId)", js.text)
        self.assertIn("state.projectDocumentsChangeRequestId === requestId", js.text)
        self.assertIn("(state.selectedDocumentId || \"\") === selectedDocumentId", js.text)
        self.assertIn("!state.dirty", js.text)
        self.assertIn("function invalidateProjectDocumentsChangeRequests()", js.text)
        self.assertIn("state.projectDocumentsChangeRequestId += 1", js.text)
        bootstrap_loader = js.text.split("async function loadBootstrap", 1)[1].split(
            "async function fetchProjectSchemasSafe", 1
        )[0]
        self.assertIn("const projectId = state.projectId", bootstrap_loader)
        self.assertIn("const requestId = state.bootstrapRequestId + 1", bootstrap_loader)
        self.assertIn("state.bootstrapRequestId = requestId", bootstrap_loader)
        self.assertIn("invalidateCreateFileImportRequests()", bootstrap_loader)
        self.assertIn("invalidateEditorFileImportRequests()", bootstrap_loader)
        self.assertIn("invalidateProjectInviteRequests()", bootstrap_loader)
        self.assertIn("invalidateProjectInviteAcceptRequests()", bootstrap_loader)
        self.assertIn("/projects/${encodeURIComponent(projectId)}/editor-bootstrap", bootstrap_loader)
        self.assertIn("fetchProjectSchemasSafe(projectId)", bootstrap_loader)
        self.assertIn("fetchProjectMembersSafe(projectId)", bootstrap_loader)
        self.assertIn("fetchProjectUsageSafe(projectId)", bootstrap_loader)
        self.assertIn("if (!isCurrentBootstrapRequest(requestId, projectId))", bootstrap_loader)
        self.assertIn("finishStaleBootstrapRequest(requestId)", bootstrap_loader)
        self.assertIn("function isCurrentBootstrapRequest(requestId, projectId)", js.text)
        self.assertIn("function invalidateBootstrapRequests()", js.text)
        self.assertIn("function finishStaleBootstrapRequest(requestId)", js.text)
        self.assertIn("state.bootstrapRequestId += 1", js.text)
        project_home_loader = js.text.split("async function loadProjectHome()", 1)[1].split(
            "async function createProjectFromGate", 1
        )[0]
        self.assertIn("const requestId = state.projectHomeRequestId + 1", project_home_loader)
        self.assertIn("state.projectHomeRequestId = requestId", project_home_loader)
        self.assertIn("invalidateCreateProjectRequests()", project_home_loader)
        self.assertIn("invalidateBootstrapRequests()", project_home_loader)
        self.assertIn("invalidateTeamMembersRequests()", project_home_loader)
        self.assertIn("invalidateCreateDocumentRequests()", project_home_loader)
        self.assertIn("invalidateProjectInviteRequests()", project_home_loader)
        self.assertIn("invalidateProjectInviteAcceptRequests()", project_home_loader)
        self.assertIn("stopCollaborationLoop()", project_home_loader)
        self.assertIn("stopProjectWorkspaceSocket()", project_home_loader)
        self.assertIn("if (!isCurrentProjectHomeRequest(requestId))", project_home_loader)
        self.assertIn("state.workspaces = workspaces", project_home_loader)
        self.assertIn("state.projectHomeErrors = projectHomeErrors", project_home_loader)
        self.assertIn("function isCurrentProjectHomeRequest(requestId)", js.text)
        self.assertIn("function invalidateProjectHomeRequests()", js.text)
        self.assertIn("state.projectHomeRequestId += 1", js.text)
        self.assertIn("invalidateProjectDocumentsChangeRequests()", project_home_loader)
        self.assertIn("invalidateCreateFileImportRequests()", project_home_loader)
        self.assertIn("invalidateEditorFileImportRequests()", project_home_loader)
        self.assertIn('resetZipImportSelection("No ZIP selected.")', project_home_loader)
        project_opener = js.text.split("async function openProject", 1)[1].split("function setProjectId", 1)[0]
        self.assertIn("invalidateProjectHomeRequests()", project_opener)
        self.assertIn("invalidateCreateProjectRequests()", project_opener)
        self.assertIn("invalidateProjectDocumentsChangeRequests()", project_opener)
        self.assertIn("invalidateCreateDocumentRequests()", project_opener)
        self.assertIn("invalidateCreateFileImportRequests()", project_opener)
        self.assertIn("invalidateEditorFileImportRequests()", project_opener)
        self.assertIn("invalidateProjectInviteRequests()", project_opener)
        self.assertIn("invalidateProjectInviteAcceptRequests()", project_opener)
        self.assertIn('resetZipImportSelection("No ZIP selected.")', project_opener)
        session_clearer = js.text.split("function clearSessionState", 1)[1].split("function invitePromptText", 1)[0]
        self.assertIn("invalidateProjectHomeRequests()", session_clearer)
        self.assertIn("invalidateCreateProjectRequests()", session_clearer)
        self.assertIn("invalidateTeamMembersRequests()", session_clearer)
        self.assertIn("invalidateDocumentPanelRequests()", session_clearer)
        self.assertIn("invalidateSaveRequests()", session_clearer)
        self.assertIn("invalidateRollbackRequests()", session_clearer)
        self.assertIn("invalidateProjectDocumentsChangeRequests()", session_clearer)
        self.assertIn("invalidateCreateDocumentRequests()", session_clearer)
        self.assertIn("invalidateCreateFileImportRequests()", session_clearer)
        self.assertIn("invalidateEditorFileImportRequests()", session_clearer)
        self.assertIn("invalidateProjectInviteRequests()", session_clearer)
        self.assertIn("invalidateProjectInviteAcceptRequests()", session_clearer)
        self.assertIn('resetZipImportSelection("No ZIP selected.")', session_clearer)
        team_members_refresher = js.text.split("async function refreshTeamMembers()", 1)[1].split(
            "async function createProjectInvite", 1
        )[0]
        self.assertIn("const projectId = state.projectId", team_members_refresher)
        self.assertIn("const requestId = state.teamMembersRequestId + 1", team_members_refresher)
        self.assertIn("state.teamMembersRequestId = requestId", team_members_refresher)
        self.assertIn("fetchProjectMembersSafe(projectId)", team_members_refresher)
        self.assertIn("if (!isCurrentTeamMembersRequest(requestId, projectId))", team_members_refresher)
        self.assertIn("function isCurrentTeamMembersRequest(requestId, projectId)", js.text)
        self.assertIn("function invalidateTeamMembersRequests()", js.text)
        self.assertIn("state.teamMembersRequestId += 1", js.text)
        invite_creator = js.text.split("async function createProjectInvite()", 1)[1].split(
            "function renderInvitationResult", 1
        )[0]
        self.assertIn("const projectId = state.projectId", invite_creator)
        self.assertIn("const sessionUserId = state.userId", invite_creator)
        self.assertIn("const emailText = els.inviteEmail.value", invite_creator)
        self.assertIn("const requestId = state.projectInviteRequestId + 1", invite_creator)
        self.assertIn("state.projectInviteRequestId = requestId", invite_creator)
        self.assertIn("state.creatingInvite = true", invite_creator)
        self.assertIn("/projects/${encodeURIComponent(projectId)}/invitations", invite_creator)
        self.assertIn("if (!isCurrentProjectInviteRequest(requestId, projectId, sessionUserId, emailText, role))", invite_creator)
        self.assertIn("function isCurrentProjectInviteRequest(requestId, projectId, sessionUserId, emailText, role)", js.text)
        self.assertIn("state.projectInviteRequestId === requestId", js.text)
        self.assertIn("state.userId === sessionUserId", js.text)
        self.assertIn("els.inviteEmail.value === emailText", js.text)
        self.assertIn("els.inviteRole.value === role", js.text)
        self.assertIn("function invalidateProjectInviteRequests()", js.text)
        self.assertIn("state.projectInviteRequestId += 1", js.text)
        self.assertIn("state.creatingInvite = false", js.text)
        self.assertIn("els.inviteEmail.addEventListener(\"input\"", js.text)
        self.assertIn("els.inviteRole.addEventListener(\"change\"", js.text)
        self.assertIn("els.inviteEmail.disabled = busy || !state.projectId", js.text)
        self.assertIn("els.inviteRole.disabled = busy || !state.projectId", js.text)
        pending_invite_acceptor = js.text.split("async function acceptPendingInvitation()", 1)[1].split(
            "async function loadBootstrap", 1
        )[0]
        self.assertIn("const sessionUserId = state.userId", pending_invite_acceptor)
        self.assertIn("const requestId = state.projectInviteAcceptRequestId + 1", pending_invite_acceptor)
        self.assertIn("state.projectInviteAcceptRequestId = requestId", pending_invite_acceptor)
        self.assertIn("state.acceptingInvite = true", pending_invite_acceptor)
        self.assertIn("if (!isCurrentProjectInviteAcceptRequest(requestId, sessionUserId, token, true))", pending_invite_acceptor)
        manual_invite_acceptor = js.text.split("async function acceptProjectInvite()", 1)[1].split(
            "async function acceptInvitationToken", 1
        )[0]
        self.assertIn("const sessionUserId = state.userId", manual_invite_acceptor)
        self.assertIn("const tokenText = els.projectInviteToken.value", manual_invite_acceptor)
        self.assertIn("const requestId = state.projectInviteAcceptRequestId + 1", manual_invite_acceptor)
        self.assertIn("state.projectInviteAcceptRequestId = requestId", manual_invite_acceptor)
        self.assertIn("state.acceptingInvite = true", manual_invite_acceptor)
        self.assertIn("if (!isCurrentProjectInviteAcceptRequest(requestId, sessionUserId, tokenText, false))", manual_invite_acceptor)
        self.assertIn(
            "function isCurrentProjectInviteAcceptRequest(requestId, sessionUserId, tokenText, requirePendingToken)",
            js.text,
        )
        self.assertIn("state.projectInviteAcceptRequestId === requestId", js.text)
        self.assertIn("state.userId === sessionUserId", js.text)
        self.assertIn("els.projectInviteToken.value === tokenText", js.text)
        self.assertIn("!requirePendingToken || state.pendingInviteToken === tokenText", js.text)
        self.assertIn("function invalidateProjectInviteAcceptRequests()", js.text)
        self.assertIn("state.projectInviteAcceptRequestId += 1", js.text)
        self.assertIn("state.acceptingInvite = false", js.text)
        self.assertIn(
            "invalidateProjectInviteAcceptRequests()",
            js.text.split("els.projectInviteToken.addEventListener(\"input\"", 1)[1].split(
                "els.newDocumentButton", 1
            )[0],
        )
        self.assertIn("els.acceptInviteButton.disabled = busy || !els.projectInviteToken.value.trim()", js.text)
        self.assertIn("result.document_id !== state.selectedDocumentId", js.text)
        self.assertIn("createCommentThread", js.text)
        self.assertIn("addCommentReply", js.text)
        self.assertIn("setCommentThreadStatus", js.text)
        self.assertIn("renderCommentThreads", js.text)
        comment_creator = js.text.split("async function createCommentThread()", 1)[1].split(
            "async function addCommentReply", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", comment_creator)
        self.assertIn("/documents/${encodeURIComponent(documentId)}/comment-threads", comment_creator)
        self.assertIn("catch (error)", comment_creator)
        self.assertIn("if (!isCurrentCommentAction(documentId))", comment_creator)
        self.assertIn("throw error", comment_creator)
        self.assertIn("await loadCommentThreads()", comment_creator)
        self.assertGreaterEqual(comment_creator.count("if (!isCurrentCommentAction(documentId))"), 3)
        comment_reply = js.text.split("async function addCommentReply", 1)[1].split(
            "async function setCommentThreadStatus", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", comment_reply)
        self.assertIn("catch (error)", comment_reply)
        self.assertIn("if (!isCurrentCommentAction(documentId))", comment_reply)
        self.assertIn("throw error", comment_reply)
        self.assertIn("await loadCommentThreads()", comment_reply)
        self.assertGreaterEqual(comment_reply.count("if (!isCurrentCommentAction(documentId))"), 3)
        comment_status = js.text.split("async function setCommentThreadStatus", 1)[1].split(
            "async function handleCommentsPanelClick", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", comment_status)
        self.assertIn("catch (error)", comment_status)
        self.assertIn("if (!isCurrentCommentAction(documentId))", comment_status)
        self.assertIn("throw error", comment_status)
        self.assertIn("await loadCommentThreads()", comment_status)
        self.assertGreaterEqual(comment_status.count("if (!isCurrentCommentAction(documentId))"), 3)
        self.assertIn("function isCurrentCommentAction(documentId)", js.text)
        self.assertIn("return state.selectedDocumentId === documentId", js.text)
        self.assertIn("/comment-threads", js.text)
        self.assertIn("/comments", js.text)
        self.assertIn("/resolve", js.text)
        self.assertIn("/reopen", js.text)
        self.assertIn("handleCreationError", js.text)
        self.assertIn("formatDiagnosticValue", js.text)
        self.assertIn("openjson.userId", js.text)
        self.assertIn("Authorization = `Bearer ${state.token}`", js.text)
        self.assertNotIn("X-Actor-Id", js.text)
        self.assertNotIn("openjson.actorId", js.text)
        self.assertNotIn("connectionForm", js.text)
        self.assertNotIn("actorId", js.text)
        self.assertEqual(favicon.status_code, 200)
        self.assertIn("image/svg", favicon.headers["content-type"])
        self.assertEqual(self._counts(), before)

    def test_static_editor_shell_route_is_registered(self) -> None:
        routes = {(route.path, ",".join(sorted(route.methods))) for route in create_app(self.db_path).routes if hasattr(route, "methods")}

        self.assertIn(("/", "GET"), routes)
        self.assertIn(("/app", "GET"), routes)
        self.assertIn(("/favicon.ico", "GET"), routes)


if __name__ == "__main__":
    unittest.main()
