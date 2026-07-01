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
        self.assertIn("/editor-bootstrap", js.text)
        self.assertIn("/schemas", js.text)
        self.assertIn("/schema-matches", js.text)
        self.assertIn("/imports/zip-preview", js.text)
        self.assertIn("/imports/zip-apply", js.text)
        self.assertIn("/projects/${encodeURIComponent(targetProjectId)}/members", js.text)
        self.assertIn("/projects/${encodeURIComponent(targetProjectId)}/usage", js.text)
        self.assertIn("/auth/signup", js.text)
        self.assertIn("/auth/login", js.text)
        self.assertIn("/auth/logout", js.text)
        self.assertIn("/auth/refresh", js.text)
        self.assertIn("/offline-sync", js.text)
        self.assertIn("/invitations/accept", js.text)
        self.assertIn("/projects/${encodeURIComponent(state.projectId)}/invitations", js.text)
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
        self.assertIn("const busy = state.loading || state.saving || state.rollingBack || state.autosaving", js.text)
        editor_state_setter = js.text.split("function setSelectedEditorState", 1)[1].split("function clearEditor", 1)[0]
        self.assertIn("state.selectedDocumentId !== editorState.document.id", editor_state_setter)
        self.assertIn("invalidateSaveRequests()", editor_state_setter)
        self.assertIn("invalidateRollbackRequests()", editor_state_setter)
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
        self.assertIn("invalidateBootstrapRequests()", project_home_loader)
        self.assertIn("invalidateTeamMembersRequests()", project_home_loader)
        self.assertIn("stopCollaborationLoop()", project_home_loader)
        self.assertIn("stopProjectWorkspaceSocket()", project_home_loader)
        self.assertIn("if (!isCurrentProjectHomeRequest(requestId))", project_home_loader)
        self.assertIn("state.workspaces = workspaces", project_home_loader)
        self.assertIn("state.projectHomeErrors = projectHomeErrors", project_home_loader)
        self.assertIn("function isCurrentProjectHomeRequest(requestId)", js.text)
        self.assertIn("function invalidateProjectHomeRequests()", js.text)
        self.assertIn("state.projectHomeRequestId += 1", js.text)
        self.assertIn("invalidateProjectDocumentsChangeRequests()", project_home_loader)
        project_opener = js.text.split("async function openProject", 1)[1].split("function setProjectId", 1)[0]
        self.assertIn("invalidateProjectHomeRequests()", project_opener)
        self.assertIn("invalidateProjectDocumentsChangeRequests()", project_opener)
        session_clearer = js.text.split("function clearSessionState", 1)[1].split("function invitePromptText", 1)[0]
        self.assertIn("invalidateProjectHomeRequests()", session_clearer)
        self.assertIn("invalidateTeamMembersRequests()", session_clearer)
        self.assertIn("invalidateDocumentPanelRequests()", session_clearer)
        self.assertIn("invalidateSaveRequests()", session_clearer)
        self.assertIn("invalidateRollbackRequests()", session_clearer)
        self.assertIn("invalidateProjectDocumentsChangeRequests()", session_clearer)
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
        self.assertIn("if (documentId !== state.selectedDocumentId)", comment_creator)
        comment_reply = js.text.split("async function addCommentReply", 1)[1].split(
            "async function setCommentThreadStatus", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", comment_reply)
        self.assertIn("if (documentId !== state.selectedDocumentId)", comment_reply)
        comment_status = js.text.split("async function setCommentThreadStatus", 1)[1].split(
            "async function handleCommentsPanelClick", 1
        )[0]
        self.assertIn("const documentId = state.selectedDocumentId", comment_status)
        self.assertIn("if (documentId !== state.selectedDocumentId)", comment_status)
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
