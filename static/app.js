(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const initialParams = new URLSearchParams(window.location.search);

  const els = {
    authScreen: $("authScreen"),
    projectScreen: $("projectScreen"),
    workspaceShell: $("workspaceShell"),
    copyLinkButton: $("copyLinkButton"),
    projectSwitcherButton: $("projectSwitcherButton"),
    projectLogoutButton: $("projectLogoutButton"),
    authName: $("authNameInput"),
    authEmail: $("authEmailInput"),
    authPassword: $("authPasswordInput"),
    signupButton: $("signupButton"),
    loginButton: $("loginButton"),
    logoutButton: $("logoutButton"),
    authOutput: $("authOutput"),
    sessionBadge: $("sessionBadge"),
    projectHomeLabel: $("projectHomeLabel"),
    workspaceName: $("workspaceNameInput"),
    projectName: $("projectNameInput"),
    projectDescription: $("projectDescriptionInput"),
    showCreateProjectButton: $("showCreateProjectButton"),
    cancelProjectCreateButton: $("cancelProjectCreateButton"),
    projectListPanel: $("projectListPanel"),
    projectCreatePanel: $("projectCreatePanel"),
    createProjectButton: $("createProjectButton"),
    refreshProjectsButton: $("refreshProjectsButton"),
    projectList: $("projectList"),
    projectInviteToken: $("projectInviteTokenInput"),
    projectSetupOutput: $("projectSetupOutput"),
    projectLabel: $("projectLabel"),
    pathPrefix: $("pathPrefixInput"),
    query: $("queryInput"),
    filterButton: $("filterButton"),
    documentTree: $("documentTree"),
    zipSelectButton: $("zipSelectButton"),
    zipPreviewButton: $("zipPreviewButton"),
    zipApplyButton: $("zipApplyButton"),
    zipFileInput: $("zipFileInput"),
    zipImportOutput: $("zipImportOutput"),
    refreshTeamButton: $("refreshTeamButton"),
    teamMembersOutput: $("teamMembersOutput"),
    inviteEmail: $("inviteEmailInput"),
    inviteRole: $("inviteRoleSelect"),
    createInviteButton: $("createInviteButton"),
    inviteToken: $("inviteTokenInput"),
    inviteLink: $("inviteLinkInput"),
    copyInviteLinkButton: $("copyInviteLinkButton"),
    acceptInviteButton: $("acceptInviteButton"),
    teamActionOutput: $("teamActionOutput"),
    newDocumentButton: $("newDocumentButton"),
    createPanel: $("createPanel"),
    newPath: $("newPathInput"),
    schemaSelect: $("schemaSelect"),
    schemaMatchPanel: $("schemaMatchPanel"),
    newContent: $("newContentInput"),
    createDocumentButton: $("createDocumentButton"),
    cancelCreateButton: $("cancelCreateButton"),
    importCreateButton: $("importCreateButton"),
    createFileInput: $("createFileInput"),
    documentPath: $("documentPath"),
    documentMeta: $("documentMeta"),
    statusChips: $("statusChips"),
    editorBuffer: $("editorBuffer"),
    editorStatus: $("editorStatus"),
    reloadButton: $("reloadButton"),
    validateButton: $("validateButton"),
    importEditorButton: $("importEditorButton"),
    editorFileInput: $("editorFileInput"),
    autosaveToggle: $("autosaveToggle"),
    autoMergeToggle: $("autoMergeToggle"),
    liveTextToggle: $("liveTextToggle"),
    commitLiveButton: $("commitLiveButton"),
    previewButton: $("previewButton"),
    saveButton: $("saveButton"),
    validationPanel: $("validationPanel"),
    schemaPanel: $("schemaPanel"),
    collaborationPanel: $("collaborationPanel"),
    commentsButton: $("commentsButton"),
    commentsPanel: $("commentsPanel"),
    commentAnchorType: $("commentAnchorTypeSelect"),
    commentPathField: $("commentPathField"),
    commentPath: $("commentPathInput"),
    commentEventField: $("commentEventField"),
    commentEventId: $("commentEventIdInput"),
    commentBody: $("commentBodyInput"),
    createCommentThreadButton: $("createCommentThreadButton"),
    conflictPanel: $("conflictPanel"),
    conflictActions: $("conflictActions"),
    conflictReloadButton: $("conflictReloadButton"),
    conflictKeepLocalButton: $("conflictKeepLocalButton"),
    historyButton: $("historyButton"),
    historyPanel: $("historyPanel"),
    diffButton: $("diffButton"),
    diffFrom: $("diffFromInput"),
    diffTo: $("diffToInput"),
    diffPanel: $("diffPanel"),
    rollbackButton: $("rollbackButton"),
    rollbackTarget: $("rollbackTargetInput"),
    rollbackPanel: $("rollbackPanel"),
  };

  const state = {
    userId: localStorage.getItem("openjson.userId") || "",
    projectId: initialParams.get("project_id") || localStorage.getItem("openjson.projectId") || "",
    token: localStorage.getItem("openjson.token") || "",
    refreshToken: localStorage.getItem("openjson.refreshToken") || "",
    userDisplayName: localStorage.getItem("openjson.userDisplayName") || "",
    userEmail: localStorage.getItem("openjson.userEmail") || "",
    pendingInviteToken: initialParams.get("invite_token") || "",
    workspaces: [],
    availableProjects: [],
    projectHomeErrors: [],
    selectedDocumentId: initialParams.get("document_id") || localStorage.getItem("openjson.selectedDocumentId") || "",
    selectedEditorState: null,
    bootstrap: null,
    projectSchemas: [],
    schemaListError: null,
    projectMembers: [],
    memberListError: null,
    projectUsage: null,
    projectUsageError: null,
    commentThreads: [],
    createSchemaMatch: null,
    schemaMatchTimer: null,
    zipFile: null,
    zipPreview: null,
    presenceCursorTimer: null,
    activePresenceDocumentId: "",
    collaborationTimer: null,
    presenceTimer: null,
    collaborationSocket: null,
    collaborationReconnectTimer: null,
    collaborationTransport: "polling",
    collaborationStopped: false,
    projectSocket: null,
    projectSocketProjectId: "",
    projectReconnectTimer: null,
    projectWorkspaceStopped: false,
    autosaveTimer: null,
    autosaveEnabled: localStorage.getItem("openjson.autosaveEnabled") === "1",
    autoMergeEnabled: localStorage.getItem("openjson.autoMergeEnabled") === "1",
    liveTextEnabled: localStorage.getItem("openjson.liveTextEnabled") === "1",
    liveTextRevision: 0,
    liveTextShadow: "",
    liveTextApplyingRemote: false,
    liveTextPendingOperation: false,
    liveTextNeedsResync: false,
    liveTextClientId: localStorage.getItem("openjson.liveTextClientId") || "",
    offlineQueue: readOfflineQueue(),
    autosaving: false,
    conflictLocalText: "",
    originalText: "",
    baseVersion: null,
    currentVersion: null,
    syntaxValid: false,
    dirty: false,
    loading: false,
  };

  class ApiError extends Error {
    constructor(response, body) {
      const payload = body && body.error ? body.error : {};
      super(payload.message || `HTTP ${response.status}`);
      this.status = response.status;
      this.body = body;
      this.code = payload.code || "HTTP_ERROR";
      this.details = payload.details || {};
    }
  }

  function init() {
    els.authName.value = state.userDisplayName;
    els.authEmail.value = state.userEmail;
    els.autosaveToggle.checked = state.autosaveEnabled;
    els.autoMergeToggle.checked = state.autoMergeEnabled;
    els.liveTextToggle.checked = state.liveTextEnabled;
    if (!state.liveTextClientId) {
      state.liveTextClientId =
        window.crypto && crypto.randomUUID ? crypto.randomUUID() : `client-${Date.now()}-${Math.random()}`;
      localStorage.setItem("openjson.liveTextClientId", state.liveTextClientId);
    }
    els.pathPrefix.value = initialParams.get("path_prefix") || "";
    els.query.value = initialParams.get("q") || "";
    if (state.pendingInviteToken) {
      els.projectInviteToken.value = state.pendingInviteToken;
    }
    syncCommentAnchorControls();
    bindEvents();
    syncButtons();
    initializeEntry().catch((error) => showGlobalError(error));
  }

  function bindEvents() {
    els.copyLinkButton.addEventListener("click", () => {
      copyShareLink().catch((error) => renderError(els.validationPanel, error));
    });

    els.projectSwitcherButton.addEventListener("click", () => {
      loadProjectHome().catch((error) => renderError(els.projectSetupOutput, error));
    });

    els.refreshProjectsButton.addEventListener("click", () => {
      loadProjectHome().catch((error) => renderError(els.projectSetupOutput, error));
    });

    els.createProjectButton.addEventListener("click", () => {
      createProjectFromGate().catch((error) => renderError(els.projectSetupOutput, error));
    });

    els.showCreateProjectButton.addEventListener("click", () => {
      showProjectCreateMode();
    });

    els.cancelProjectCreateButton.addEventListener("click", () => {
      showProjectListMode();
    });

    els.projectList.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const projectId = target.dataset.openProject;
      if (!projectId) {
        return;
      }
      openProject(projectId, null).catch((error) => renderError(els.projectSetupOutput, error));
    });

    els.signupButton.addEventListener("click", () => {
      signupWithPassword().catch((error) => renderError(els.authOutput, error));
    });

    els.loginButton.addEventListener("click", () => {
      loginWithPassword().catch((error) => renderError(els.authOutput, error));
    });

    els.logoutButton.addEventListener("click", () => {
      logoutSession().catch((error) => renderError(els.authOutput, error));
    });

    els.projectLogoutButton.addEventListener("click", () => {
      logoutSession().catch((error) => renderError(els.projectSetupOutput, error));
    });

    els.filterButton.addEventListener("click", () => {
      loadBootstrap(state.selectedDocumentId || null).catch((error) => showGlobalError(error));
    });

    els.zipSelectButton.addEventListener("click", () => {
      els.zipFileInput.click();
    });

    els.zipFileInput.addEventListener("change", () => {
      const file = els.zipFileInput.files && els.zipFileInput.files[0];
      state.zipFile = file || null;
      state.zipPreview = null;
      if (state.zipFile) {
        renderText(els.zipImportOutput, `Selected ${state.zipFile.name}`, "muted");
      } else {
        clearPanel(els.zipImportOutput, "No ZIP selected.");
      }
      syncButtons();
    });

    els.zipPreviewButton.addEventListener("click", () => {
      previewZipImport().catch((error) => handleZipImportError(error));
    });

    els.zipApplyButton.addEventListener("click", () => {
      applyZipImport().catch((error) => handleZipImportError(error));
    });

    els.refreshTeamButton.addEventListener("click", () => {
      refreshTeamMembers().catch((error) => renderError(els.teamMembersOutput, error));
    });

    els.createInviteButton.addEventListener("click", () => {
      createProjectInvite().catch((error) => renderError(els.teamActionOutput, error));
    });

    els.copyInviteLinkButton.addEventListener("click", () => {
      copyInviteLink().catch((error) => renderError(els.teamActionOutput, error));
    });

    els.acceptInviteButton.addEventListener("click", () => {
      acceptProjectInvite().catch((error) => renderError(els.projectSetupOutput, error));
    });

    els.inviteToken.addEventListener("input", () => {
      updateInviteLinkField();
      syncButtons();
    });

    els.projectInviteToken.addEventListener("input", () => {
      syncButtons();
    });

    els.newDocumentButton.addEventListener("click", () => {
      els.createPanel.classList.toggle("hidden");
      if (!els.createPanel.classList.contains("hidden")) {
        renderSchemaOptions();
        scheduleSchemaMatchPreview();
      }
    });

    els.cancelCreateButton.addEventListener("click", () => {
      els.createPanel.classList.add("hidden");
    });

    els.newPath.addEventListener("input", () => {
      scheduleSchemaMatchPreview();
      syncButtons();
    });

    els.schemaSelect.addEventListener("change", () => {
      previewCreateSchemaMatch().catch((error) => renderError(els.schemaMatchPanel, error));
      syncButtons();
    });

    els.importCreateButton.addEventListener("click", () => {
      els.createFileInput.click();
    });

    els.createFileInput.addEventListener("change", () => {
      importCreateFile().catch((error) => renderFileImportError(error));
    });

    els.createDocumentButton.addEventListener("click", () => {
      createDocument().catch((error) => handleCreationError(error));
    });

    els.editorBuffer.addEventListener("input", () => {
      handleLiveTextInput();
      updateSyntaxState();
      schedulePresenceCursorUpdate();
      syncButtons();
    });
    els.editorBuffer.addEventListener("click", schedulePresenceCursorUpdate);
    els.editorBuffer.addEventListener("keyup", schedulePresenceCursorUpdate);
    els.editorBuffer.addEventListener("select", schedulePresenceCursorUpdate);

    els.reloadButton.addEventListener("click", () => {
      if (state.selectedDocumentId) {
        loadBootstrap(state.selectedDocumentId).catch((error) => showGlobalError(error));
      } else {
        loadBootstrap(null).catch((error) => showGlobalError(error));
      }
    });

    els.validateButton.addEventListener("click", () => {
      validateSelected().catch((error) => renderError(els.validationPanel, error));
    });

    els.importEditorButton.addEventListener("click", () => {
      els.editorFileInput.click();
    });

    els.editorFileInput.addEventListener("change", () => {
      importEditorFile().catch((error) => renderFileImportError(error));
    });

    els.autosaveToggle.addEventListener("change", () => {
      state.autosaveEnabled = els.autosaveToggle.checked;
      localStorage.setItem("openjson.autosaveEnabled", state.autosaveEnabled ? "1" : "0");
      scheduleAutosave();
      syncButtons();
    });

    els.autoMergeToggle.addEventListener("change", () => {
      state.autoMergeEnabled = els.autoMergeToggle.checked;
      localStorage.setItem("openjson.autoMergeEnabled", state.autoMergeEnabled ? "1" : "0");
      syncButtons();
    });

    els.liveTextToggle.addEventListener("change", () => {
      state.liveTextEnabled = els.liveTextToggle.checked;
      localStorage.setItem("openjson.liveTextEnabled", state.liveTextEnabled ? "1" : "0");
      if (state.liveTextEnabled) {
        joinLiveTextSession();
      }
      syncButtons();
    });

    els.commitLiveButton.addEventListener("click", () => {
      commitLiveTextSession();
    });

    els.previewButton.addEventListener("click", () => {
      previewSelected().catch((error) => handleMutationError(error));
    });

    els.saveButton.addEventListener("click", () => {
      saveSelected().catch((error) => handleMutationError(error));
    });

    els.historyButton.addEventListener("click", () => {
      loadHistory().catch((error) => renderError(els.historyPanel, error));
    });

    els.diffButton.addEventListener("click", () => {
      loadDiff().catch((error) => renderError(els.diffPanel, error));
    });

    els.rollbackButton.addEventListener("click", () => {
      rollbackSelected().catch((error) => renderError(els.rollbackPanel, error));
    });

    els.commentsButton.addEventListener("click", () => {
      loadCommentThreads().catch((error) => renderError(els.commentsPanel, error));
    });

    els.commentAnchorType.addEventListener("change", () => {
      syncCommentAnchorControls();
      syncButtons();
    });

    els.commentPath.addEventListener("input", () => {
      syncButtons();
    });

    els.commentEventId.addEventListener("input", () => {
      syncButtons();
    });

    els.commentBody.addEventListener("input", () => {
      syncButtons();
    });

    els.createCommentThreadButton.addEventListener("click", () => {
      createCommentThread().catch((error) => renderError(els.commentsPanel, error));
    });

    els.commentsPanel.addEventListener("click", (event) => {
      handleCommentsPanelClick(event).catch((error) => renderError(els.commentsPanel, error));
    });

    els.conflictReloadButton.addEventListener("click", () => {
      if (state.selectedDocumentId) {
        loadBootstrap(state.selectedDocumentId).catch((error) => showGlobalError(error));
      }
    });

    els.conflictKeepLocalButton.addEventListener("click", () => {
      keepLocalBufferOnLatest().catch((error) => renderError(els.conflictPanel, error));
    });

    window.addEventListener("beforeunload", () => {
      sendPresenceLeave();
    });

    window.addEventListener("online", () => {
      flushOfflineQueue().catch((error) => setEditorStatus(error.message || "Offline sync failed.", "error"));
    });
  }

  async function initializeEntry() {
    if (!state.token && state.refreshToken) {
      await refreshAccessToken();
    }
    if (!state.token) {
      showAuthScreen(invitePromptText());
      return;
    }
    await enterAuthenticatedArea();
  }

  async function enterAuthenticatedArea() {
    if (state.pendingInviteToken) {
      await acceptPendingInvitation();
      return;
    }
    if (state.projectId) {
      try {
        await loadBootstrap(state.selectedDocumentId || null);
        return;
      } catch (error) {
        state.projectId = "";
        state.selectedDocumentId = "";
        localStorage.removeItem("openjson.projectId");
        localStorage.removeItem("openjson.selectedDocumentId");
        renderError(els.projectSetupOutput, error);
      }
    }
    await loadProjectHome();
  }

  async function loadProjectHome() {
    if (!state.token) {
      showAuthScreen(invitePromptText());
      return;
    }
    stopCollaborationLoop();
    stopProjectWorkspaceSocket();
    state.loading = true;
    showProjectScreen();
    clearPanel(els.projectList, "Loading projects...");
    syncButtons();
    try {
      const workspaceData = await apiFetch("/workspaces");
      state.workspaces = workspaceData.workspaces || [];
      state.projectHomeErrors = [];
      const projectGroups = await Promise.all(
        state.workspaces.map(async (workspace) => {
          try {
            const projectData = await apiFetch(`/workspaces/${encodeURIComponent(workspace.id)}/projects`);
            return (projectData.projects || []).map((project) => ({ workspace, project }));
          } catch (error) {
            state.projectHomeErrors.push(error);
            return [];
          }
        })
      );
      state.availableProjects = projectGroups.flat();
      renderProjectHome();
    } finally {
      state.loading = false;
      syncButtons();
    }
  }

  async function createProjectFromGate() {
    if (!state.token) {
      showAuthScreen(invitePromptText());
      return;
    }
    const workspaceName = els.workspaceName.value.trim();
    const projectName = els.projectName.value.trim();
    const description = cleanOptional(els.projectDescription.value);
    if (!workspaceName || !projectName) {
      renderText(els.projectSetupOutput, "Workspace name and project name are required.", "error-text");
      return;
    }
    state.loading = true;
    showProjectCreateMode();
    syncButtons();
    try {
      const workspace = await apiFetch("/workspaces", {
        method: "POST",
        body: { name: workspaceName },
      });
      const project = await apiFetch(`/workspaces/${encodeURIComponent(workspace.id)}/projects`, {
        method: "POST",
        body: { name: projectName, description },
      });
      els.projectName.value = "";
      els.projectDescription.value = "";
      renderText(els.projectSetupOutput, `Created ${project.name}.`, "ok-text");
      await openProject(project.id, null);
    } finally {
      state.loading = false;
      syncButtons();
    }
  }

  async function openProject(projectId, selectedDocumentId) {
    setProjectId(projectId);
    if (!selectedDocumentId) {
      state.selectedDocumentId = "";
      localStorage.removeItem("openjson.selectedDocumentId");
    }
    await loadBootstrap(selectedDocumentId || null);
  }

  function setProjectId(projectId) {
    state.projectId = projectId;
    localStorage.setItem("openjson.projectId", projectId);
    clearInviteResult();
  }

  function showAuthScreen(message) {
    stopCollaborationLoop();
    stopProjectWorkspaceSocket();
    els.authScreen.classList.remove("hidden");
    els.projectScreen.classList.add("hidden");
    els.workspaceShell.classList.add("hidden");
    if (message) {
      clearPanel(els.authOutput, message);
    }
    syncAccountLabels();
  }

  function showProjectScreen(message) {
    stopProjectWorkspaceSocket();
    els.authScreen.classList.add("hidden");
    els.projectScreen.classList.remove("hidden");
    els.workspaceShell.classList.add("hidden");
    if (message) {
      clearPanel(els.projectSetupOutput, message);
    }
    syncAccountLabels();
  }

  function showProjectListMode() {
    els.projectListPanel.classList.remove("hidden");
    els.projectCreatePanel.classList.add("hidden");
    els.showCreateProjectButton.classList.remove("hidden");
    syncButtons();
  }

  function showProjectCreateMode() {
    els.projectListPanel.classList.add("hidden");
    els.projectCreatePanel.classList.remove("hidden");
    els.showCreateProjectButton.classList.add("hidden");
    clearPanel(els.projectSetupOutput, "Create a workspace and project for your JSON files.");
    syncButtons();
  }

  function showWorkspaceScreen() {
    els.authScreen.classList.add("hidden");
    els.projectScreen.classList.add("hidden");
    els.workspaceShell.classList.remove("hidden");
    syncAccountLabels();
  }

  function syncAccountLabels() {
    const name = state.userDisplayName || els.authName.value.trim();
    const email = state.userEmail || els.authEmail.value.trim();
    els.sessionBadge.textContent = name ? `${name}${email ? ` / ${email}` : ""}` : email || "";
    els.projectHomeLabel.textContent = name ? `${name}'s projects` : "Create a project or open one you already belong to.";
  }

  function renderProjectHome() {
    showProjectListMode();
    clear(els.projectList);
    if (!state.availableProjects.length) {
      renderText(els.projectList, "No projects yet.", "muted");
    }
    for (const item of state.availableProjects) {
      const row = document.createElement("div");
      row.className = "project-row";
      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = item.project.name;
      const meta = document.createElement("span");
      meta.className = "muted";
      meta.textContent = `${item.workspace.name} / ${item.project.role || "member"}`;
      details.append(title, meta);
      const button = document.createElement("button");
      button.className = "secondary-button";
      button.type = "button";
      button.dataset.openProject = item.project.id;
      button.textContent = "Open";
      row.append(details, button);
      els.projectList.appendChild(row);
    }
    if (state.projectHomeErrors.length) {
      clear(els.projectSetupOutput);
      renderText(els.projectSetupOutput, "Some project lists could not be loaded.", "error-text");
    } else if (state.availableProjects.length) {
      clearPanel(els.projectSetupOutput, "Select a project or create a new one.");
    } else {
      clearPanel(els.projectSetupOutput, "Create your first project to start editing JSON.");
    }
  }

  async function signupWithPassword() {
    const displayName = els.authName.value.trim();
    const email = els.authEmail.value.trim();
    const password = els.authPassword.value;
    if (!displayName || !email || !password) {
      renderText(els.authOutput, "Name, email, and password are required.", "error-text");
      return;
    }
    const result = await apiFetch("/auth/signup", {
      method: "POST",
      auth: false,
      body: {
        display_name: displayName,
        email,
        password,
      },
    });
    applyAuthenticatedSession(result);
    renderText(els.authOutput, `Signed in as ${result.user.display_name}.`, "ok-text");
    await enterAuthenticatedArea();
  }

  async function loginWithPassword() {
    const email = els.authEmail.value.trim();
    const password = els.authPassword.value;
    if (!email || !password) {
      renderText(els.authOutput, "Email and password are required.", "error-text");
      return;
    }
    const result = await apiFetch("/auth/login", {
      method: "POST",
      auth: false,
      body: {
        email,
        password,
      },
    });
    applyAuthenticatedSession(result);
    renderText(els.authOutput, `Signed in as ${result.user.display_name}.`, "ok-text");
    await enterAuthenticatedArea();
  }

  async function logoutSession() {
    if (!state.token) {
      clearSessionState({ preserveInvite: Boolean(state.pendingInviteToken) });
      renderText(els.authOutput, "Session cleared.", "muted");
      syncButtons();
      return;
    }
    const preserveInvite = Boolean(state.pendingInviteToken);
    await apiFetch("/auth/logout", {
      method: "POST",
    });
    clearSessionState({ preserveInvite });
    renderText(els.authOutput, "Signed out.", "muted");
    restartCollaborationLoop();
    syncButtons();
    showAuthScreen(preserveInvite ? invitePromptText() : "Signed out.");
  }

  function applyAuthenticatedSession(result) {
    state.userId = result.user.id;
    state.token = result.token;
    state.userDisplayName = result.user.display_name || "";
    state.userEmail = result.user.email || "";
    els.authName.value = state.userDisplayName;
    els.authEmail.value = state.userEmail;
    localStorage.setItem("openjson.userId", state.userId);
    localStorage.setItem("openjson.token", state.token);
    localStorage.setItem("openjson.userDisplayName", state.userDisplayName);
    localStorage.setItem("openjson.userEmail", state.userEmail);
    if (!els.workspaceName.value.trim()) {
      els.workspaceName.value = `${state.userDisplayName || "Team"} Workspace`;
    }
    if (result.refresh_token) {
      state.refreshToken = result.refresh_token;
      localStorage.setItem("openjson.refreshToken", state.refreshToken);
    }
    syncAccountLabels();
  }

  function clearSessionState(options) {
    const preserveInvite = Boolean(options && options.preserveInvite);
    const inviteToken = preserveInvite ? state.pendingInviteToken || els.projectInviteToken.value.trim() : "";
    state.userId = "";
    state.token = "";
    state.refreshToken = "";
    state.projectId = "";
    state.selectedDocumentId = "";
    state.bootstrap = null;
    state.selectedEditorState = null;
    state.projectMembers = [];
    state.projectSchemas = [];
    state.availableProjects = [];
    if (preserveInvite && inviteToken) {
      state.pendingInviteToken = inviteToken;
      els.projectInviteToken.value = inviteToken;
    } else {
      state.pendingInviteToken = "";
      els.projectInviteToken.value = "";
      clearInviteResult();
    }
    localStorage.removeItem("openjson.token");
    localStorage.removeItem("openjson.refreshToken");
    localStorage.removeItem("openjson.userId");
    localStorage.removeItem("openjson.projectId");
    localStorage.removeItem("openjson.selectedDocumentId");
  }

  function invitePromptText() {
    return state.pendingInviteToken
      ? "Sign up or log in with the invited email address to join this project."
      : undefined;
  }

  async function acceptPendingInvitation() {
    const token = state.pendingInviteToken || els.projectInviteToken.value.trim();
    if (!token) {
      await loadProjectHome();
      return;
    }
    state.pendingInviteToken = token;
    els.projectInviteToken.value = token;
    showProjectScreen("Joining invited project...");
    try {
      const result = await acceptInvitationToken(token);
      state.pendingInviteToken = "";
      els.projectInviteToken.value = "";
      renderText(els.projectSetupOutput, `Joined project as ${result.member.role}.`, "ok-text");
      await openProject(result.invitation.project_id, null);
    } catch (error) {
      showProjectScreen();
      clearPanel(els.projectList, "Invite token is ready for manual retry.");
      renderError(els.projectSetupOutput, error);
      syncButtons();
    }
  }

  async function loadBootstrap(selectedDocumentId) {
    if (!state.projectId) {
      showProjectScreen("Create or select a project first.");
      return;
    }
    state.loading = true;
    syncButtons();
    const params = {
      include_validation: "true",
      recent_events_limit: "5",
      path_prefix: cleanOptional(els.pathPrefix.value),
      q: cleanOptional(els.query.value),
    };
    if (selectedDocumentId) {
      params.selected_document_id = selectedDocumentId;
    }
    const [data, schemaData, memberData, usageData] = await Promise.all([
      apiFetch(`/projects/${encodeURIComponent(state.projectId)}/editor-bootstrap`, {
        query: params,
      }),
      fetchProjectSchemasSafe(),
      fetchProjectMembersSafe(),
      fetchProjectUsageSafe(),
    ]);
    state.bootstrap = data;
    state.projectSchemas = schemaData.schemas;
    state.schemaListError = schemaData.error;
    state.projectMembers = memberData.members;
    state.memberListError = memberData.error;
    state.projectUsage = usageData.usage;
    state.projectUsageError = usageData.error;
    state.loading = false;
    showWorkspaceScreen();
    renderBootstrap(data);
    updateBrowserUrl();

    if (!data.selected_document_editor_state) {
      const first = data.documents.documents[0];
      if (first && !selectedDocumentId) {
        await loadBootstrap(first.id);
        return;
      }
      clearEditor();
    } else {
      setSelectedEditorState(data.selected_document_editor_state);
    }
    ensureProjectWorkspaceSocket();
    restartCollaborationLoop();
    syncButtons();
  }

  async function fetchProjectSchemasSafe() {
    try {
      const data = await apiFetch(`/projects/${encodeURIComponent(state.projectId)}/schemas`);
      return { schemas: data.schemas || [], error: null };
    } catch (error) {
      return { schemas: [], error };
    }
  }

  async function fetchProjectMembersSafe() {
    try {
      const data = await apiFetch(`/projects/${encodeURIComponent(state.projectId)}/members`);
      return { members: data.members || [], error: null };
    } catch (error) {
      return { members: [], error };
    }
  }

  async function fetchProjectUsageSafe() {
    try {
      const data = await apiFetch(`/projects/${encodeURIComponent(state.projectId)}/usage`);
      return { usage: data, error: null };
    } catch (error) {
      return { usage: null, error };
    }
  }

  async function refreshTeamMembers() {
    const data = await fetchProjectMembersSafe();
    state.projectMembers = data.members;
    state.memberListError = data.error;
    renderTeamPanel();
  }

  async function createProjectInvite() {
    const email = els.inviteEmail.value.trim();
    const role = els.inviteRole.value;
    if (!state.projectId || !email) {
      renderText(els.teamActionOutput, "Project ID and invite email are required.", "error-text");
      return;
    }
    const invitation = await apiFetch(`/projects/${encodeURIComponent(state.projectId)}/invitations`, {
      method: "POST",
      body: {
        email,
        role,
      },
    });
    els.inviteToken.value = invitation.token || "";
    updateInviteLinkField();
    renderInvitationResult(invitation);
  }

  function renderInvitationResult(invitation) {
    clear(els.teamActionOutput);
    const delivery = invitation.email_delivery || null;
    if (!delivery) {
      renderText(els.teamActionOutput, `Invite token created for ${invitation.email}.`, "ok-text");
      return;
    }
    if (delivery.status === "sent") {
      renderText(
        els.teamActionOutput,
        `Invitation email sent to ${invitation.email} via ${delivery.delivery_backend}.`,
        "ok-text",
      );
    } else if (delivery.status === "skipped") {
      renderText(
        els.teamActionOutput,
        `Invite created for ${invitation.email}. Email delivery is ${delivery.delivery_backend}.`,
        "muted",
      );
    } else {
      renderText(
        els.teamActionOutput,
        `Invite created for ${invitation.email}, but email delivery failed: ${delivery.error_message || "unknown error"}`,
        "error-text",
      );
    }
    renderText(els.teamActionOutput, "Invite link and token are available below as fallback join paths.", "muted");
  }

  function buildInviteUrl(token) {
    const url = new URL("/app", window.location.origin);
    url.searchParams.set("invite_token", token);
    return url;
  }

  function updateInviteLinkField() {
    const token = els.inviteToken.value.trim();
    els.inviteLink.value = token ? buildInviteUrl(token).toString() : "";
  }

  function clearInviteResult() {
    els.inviteToken.value = "";
    els.inviteLink.value = "";
    clearPanel(els.teamActionOutput, "Invite a teammate by email, then share the generated link or token.");
  }

  async function copyInviteLink() {
    const link = els.inviteLink.value.trim();
    if (!link) {
      renderText(els.teamActionOutput, "Create an invite before copying its link.", "error-text");
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(link);
      renderText(els.teamActionOutput, "Invite link copied.", "ok-text");
      return;
    }
    renderText(els.teamActionOutput, link, "muted");
  }

  async function acceptProjectInvite() {
    const token = els.projectInviteToken.value.trim();
    if (!token) {
      renderText(els.projectSetupOutput, "Invite token is required.", "error-text");
      return;
    }
    const result = await acceptInvitationToken(token);
    state.pendingInviteToken = "";
    renderText(els.projectSetupOutput, `Joined project as ${result.member.role}.`, "ok-text");
    els.projectInviteToken.value = "";
    await openProject(result.invitation.project_id, null);
  }

  async function acceptInvitationToken(token) {
    return apiFetch("/invitations/accept", {
      method: "POST",
      body: {
        token,
      },
    });
  }

  function buildShareUrl() {
    const url = new URL("/app", window.location.origin);
    if (state.projectId) {
      url.searchParams.set("project_id", state.projectId);
    }
    if (state.selectedDocumentId) {
      url.searchParams.set("document_id", state.selectedDocumentId);
    }
    const pathPrefix = cleanOptional(els.pathPrefix.value);
    const query = cleanOptional(els.query.value);
    if (pathPrefix) {
      url.searchParams.set("path_prefix", pathPrefix);
    }
    if (query) {
      url.searchParams.set("q", query);
    }
    return url;
  }

  function updateBrowserUrl() {
    window.history.replaceState({}, "", buildShareUrl());
  }

  async function copyShareLink() {
    const url = buildShareUrl().toString();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(url);
      setEditorStatus("Share link copied.", "ok");
      return;
    }
    clear(els.validationPanel);
    renderText(els.validationPanel, url, "muted");
    setEditorStatus("Share link ready.", "info");
  }

  function renderBootstrap(data) {
    els.projectLabel.textContent = `${data.project.name} / ${data.actor.role}`;
    renderTree(data.document_tree.root);
    renderProjectChips(data);
    renderTeamPanel();
    renderSchemaOptions();
    previewCreateSchemaMatch().catch((error) => renderError(els.schemaMatchPanel, error));
  }

  function renderProjectChips(data) {
    clear(els.statusChips);
    els.statusChips.appendChild(chip(data.actor.role, "info"));
    if (data.actor.capabilities.can_patch) {
      els.statusChips.appendChild(chip("write", "ok"));
    } else {
      els.statusChips.appendChild(chip("read only", "warn"));
    }
    if (data.bootstrap.read_only) {
      els.statusChips.appendChild(chip("bootstrap", "info"));
    }
    if (state.projectUsage) {
      const usage = state.projectUsage.usage;
      const limits = state.projectUsage.limits;
      els.statusChips.appendChild(chip(`${usage.active_document_count} docs`, "info"));
      if (limits.enabled) {
        const ratio = usage.active_snapshot_bytes / Math.max(1, limits.max_project_snapshot_bytes);
        els.statusChips.appendChild(
          chip(
            `${formatBytes(usage.active_snapshot_bytes)} / ${formatBytes(limits.max_project_snapshot_bytes)}`,
            ratio >= 0.8 ? "warn" : "info",
          )
        );
      } else {
        els.statusChips.appendChild(chip(`${formatBytes(usage.active_snapshot_bytes)} snapshots`, "info"));
      }
    } else if (state.projectUsageError) {
      els.statusChips.appendChild(chip("usage unavailable", "warn"));
    }
  }

  function renderTeamPanel() {
    clear(els.teamMembersOutput);
    if (state.memberListError) {
      renderError(els.teamMembersOutput, state.memberListError);
      return;
    }
    if (!state.projectMembers.length) {
      renderText(els.teamMembersOutput, "No members loaded.", "muted");
      return;
    }
    for (const member of state.projectMembers) {
      const row = document.createElement("div");
      row.className = "team-member-row";
      const details = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = member.display_name || member.user_id;
      const meta = document.createElement("span");
      meta.className = "muted";
      meta.textContent = `${member.role} / ${member.email || member.user_id}`;
      details.append(name, meta);
      const badge = document.createElement("span");
      badge.className = "member-badge";
      badge.textContent = member.user_id === state.userId ? "You" : member.role;
      row.append(details, badge);
      els.teamMembersOutput.appendChild(row);
    }
  }

  function renderTree(root) {
    clear(els.documentTree);
    const children = root.children || [];
    if (!children.length) {
      const empty = document.createElement("div");
      empty.className = "tree-empty";
      empty.textContent = "No documents";
      els.documentTree.appendChild(empty);
      return;
    }
    for (const child of children) {
      els.documentTree.appendChild(renderTreeNode(child));
    }
  }

  function renderTreeNode(node) {
    if (node.type === "folder") {
      const wrapper = document.createElement("div");
      wrapper.className = "tree-folder";
      const name = document.createElement("div");
      name.className = "tree-folder-name";
      name.textContent = node.name || node.path || "/";
      wrapper.appendChild(name);
      const children = document.createElement("div");
      children.className = "tree-children";
      for (const child of node.children || []) {
        children.appendChild(renderTreeNode(child));
      }
      wrapper.appendChild(children);
      return wrapper;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "document-node";
    if (node.document && node.document.id === state.selectedDocumentId) {
      button.classList.add("active");
    }
    const label = document.createElement("span");
    label.textContent = node.name || node.path;
    const version = document.createElement("span");
    version.className = "version-pill";
    version.textContent = `v${node.document.current_version}`;
    button.append(label, version);
    button.addEventListener("click", () => {
      loadBootstrap(node.document.id).catch((error) => showGlobalError(error));
    });
    return button;
  }

  function setSelectedEditorState(editorState) {
    state.selectedEditorState = editorState;
    state.selectedDocumentId = editorState.document.id;
    state.originalText = editorState.document.content_text;
    state.liveTextShadow = state.originalText;
    state.liveTextRevision = 0;
    state.liveTextPendingOperation = false;
    state.liveTextNeedsResync = false;
    state.baseVersion = editorState.editor.required_base_version;
    state.currentVersion = editorState.document.current_version;
    localStorage.setItem("openjson.selectedDocumentId", state.selectedDocumentId);
    updateBrowserUrl();

    els.editorBuffer.value = state.originalText;
    els.documentPath.textContent = editorState.document.full_path;
    els.documentMeta.textContent = `Version ${state.currentVersion} / base ${state.baseVersion}`;
    els.diffTo.value = String(state.currentVersion);
    els.rollbackTarget.max = String(Math.max(1, state.currentVersion - 1));
    els.rollbackTarget.value = String(Math.max(1, state.currentVersion - 1));
    renderSchema(editorState.schema);
    renderValidation(editorState.validation);
    clearPanel(els.collaborationPanel, "Loading collaboration state...");
    clearPanel(els.commentsPanel, "Loading notes...");
    renderRecentEvents(editorState.recent_events || []);
    clearPanel(els.diffPanel, "No diff loaded");
    clearPanel(els.conflictPanel, "No conflict");
    hideConflictActions();
    clearPanel(els.rollbackPanel, "No rollback");
    updateSyntaxState();
    if (state.liveTextEnabled) {
      joinLiveTextSession();
    }
    loadCommentThreads().catch((error) => renderError(els.commentsPanel, error));
    setEditorStatus("Document loaded.", "ok");
  }

  function clearEditor() {
    state.selectedEditorState = null;
    state.selectedDocumentId = "";
    state.originalText = "";
    state.liveTextShadow = "";
    state.liveTextRevision = 0;
    state.liveTextPendingOperation = false;
    state.liveTextNeedsResync = false;
    state.baseVersion = null;
    state.currentVersion = null;
    state.commentThreads = [];
    localStorage.removeItem("openjson.selectedDocumentId");
    updateBrowserUrl();
    els.editorBuffer.value = "";
    els.documentPath.textContent = "No document selected";
    els.documentMeta.textContent = "Version -";
    clearPanel(els.schemaPanel, "No schema");
    clearPanel(els.validationPanel, "No validation");
    clearPanel(els.conflictPanel, "No conflict");
    hideConflictActions();
    clearPanel(els.historyPanel, "No history");
    clearPanel(els.diffPanel, "No diff loaded");
    clearPanel(els.rollbackPanel, "No rollback");
    clearPanel(els.collaborationPanel, "No active document.");
    clearPanel(els.commentsPanel, "No document selected.");
    stopCollaborationLoop();
    setEditorStatus("Load or create a document.", "info");
  }

  async function createDocument() {
    const fullPath = els.newPath.value.trim();
    if (!fullPath) {
      setEditorStatus("Document path is required.", "error");
      return;
    }
    let content;
    try {
      content = JSON.parse(els.newContent.value);
    } catch (error) {
      renderText(els.validationPanel, `Invalid JSON: ${error.message}`, "error-text");
      return;
    }
    const body = { full_path: fullPath, content };
    const schemaId = cleanOptional(els.schemaSelect.value);
    if (schemaId) {
      body.schema_id = schemaId;
    }
    const created = await apiFetch(`/projects/${encodeURIComponent(state.projectId)}/documents`, {
      method: "POST",
      body,
    });
    els.createPanel.classList.add("hidden");
    els.newPath.value = "";
    els.schemaSelect.value = "";
    clearPanel(els.schemaMatchPanel, "Enter a path to preview schema binding.");
    els.newContent.value = "{\n  \"name\": \"baseline\"\n}";
    await loadBootstrap(created.id);
  }

  async function importCreateFile() {
    const file = els.createFileInput.files && els.createFileInput.files[0];
    if (!file) {
      return;
    }
    const text = await readJsonFile(file);
    els.newContent.value = prettyJsonText(text);
    if (!els.newPath.value.trim()) {
      els.newPath.value = suggestedJsonPath(file.name);
    }
    els.createFileInput.value = "";
    scheduleSchemaMatchPreview();
    setEditorStatus("JSON file loaded into new document buffer.", "ok");
  }

  async function importEditorFile() {
    const file = els.editorFileInput.files && els.editorFileInput.files[0];
    if (!file) {
      return;
    }
    if (!state.selectedDocumentId) {
      throw new Error("Select a document before importing into the editor.");
    }
    const text = await readJsonFile(file);
    els.editorBuffer.value = prettyJsonText(text);
    els.editorFileInput.value = "";
    updateSyntaxState();
    syncButtons();
    setEditorStatus("JSON file loaded into editor buffer.", "ok");
  }

  async function previewZipImport() {
    if (!state.zipFile) {
      return;
    }
    const result = await apiFetchBinary(`/projects/${encodeURIComponent(state.projectId)}/imports/zip-preview`, {
      method: "POST",
      body: await state.zipFile.arrayBuffer(),
      contentType: "application/zip",
    });
    state.zipPreview = result;
    renderZipImportResult(result);
    syncButtons();
    setEditorStatus(
      result.can_apply ? `ZIP preview ready: ${result.archive.json_file_count} JSON file(s).` : "ZIP preview blocked.",
      result.can_apply ? "ok" : "error",
    );
  }

  async function applyZipImport() {
    if (!state.zipFile || !state.zipPreview || !state.zipPreview.can_apply) {
      return;
    }
    const result = await apiFetchBinary(`/projects/${encodeURIComponent(state.projectId)}/imports/zip-apply`, {
      method: "POST",
      query: { reason: `Imported ${state.zipFile.name} from OpenJson UI` },
      body: await state.zipFile.arrayBuffer(),
      contentType: "application/zip",
    });
    state.zipPreview = result;
    renderZipImportResult(result);
    const firstCreated = result.created_documents && result.created_documents[0];
    state.zipFile = null;
    els.zipFileInput.value = "";
    syncButtons();
    setEditorStatus(`Imported ${result.imported_count} JSON document(s).`, "ok");
    await loadBootstrap(firstCreated ? firstCreated.id : state.selectedDocumentId || null);
  }

  async function readJsonFile(file) {
    const text = await file.text();
    JSON.parse(text);
    return text;
  }

  function prettyJsonText(text) {
    return JSON.stringify(JSON.parse(text), null, 2);
  }

  function suggestedJsonPath(fileName) {
    const normalized = fileName.replace(/\\/g, "/").split("/").pop() || "document.json";
    return normalized.endsWith(".json") ? normalized : `${normalized}.json`;
  }

  async function validateSelected() {
    if (!state.selectedDocumentId) {
      return;
    }
    const result = await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/validate`, {
      method: "POST",
    });
    renderValidation({ available: true, valid: result.valid, errors: result.errors, warnings: result.warnings, context: result });
    setEditorStatus("Validation refreshed.", result.valid ? "ok" : "error");
  }

  async function previewSelected() {
    if (!state.selectedDocumentId || !state.syntaxValid) {
      return;
    }
    const result = await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/content-preview`, {
      method: "POST",
      body: {
        base_version: state.baseVersion,
        content_text: els.editorBuffer.value,
      },
    });
    renderPreview(result);
    setEditorStatus(`Preview ready: ${result.changed_paths.length} changed path(s).`, "ok");
  }

  async function saveSelected(options) {
    const autosave = Boolean(options && options.autosave);
    if (!state.selectedDocumentId || !state.syntaxValid || !state.dirty || state.autosaving) {
      return;
    }
    state.autosaving = autosave;
    syncButtons();
    try {
      const result = await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/content`, {
        method: "PUT",
        body: {
          base_version: state.baseVersion,
          content_text: els.editorBuffer.value,
          merge_strategy: state.autoMergeEnabled ? "auto" : "reject",
          reason: autosave ? "Autosaved from OpenJson UI" : "Saved from OpenJson UI",
        },
      });
      const mergeLabel = result.auto_merged ? " with auto-merge" : "";
      setEditorStatus(`${autosave ? "Autosaved" : "Saved"} version ${result.current_version}${mergeLabel}.`, "ok");
      sendRealtimeMessage({ type: "refresh", since_version: state.baseVersion || result.current_version - 1 });
      await loadBootstrap(state.selectedDocumentId);
    } catch (error) {
      if (!(error instanceof ApiError) && state.selectedDocumentId) {
        queueOfflineSave({
          document_id: state.selectedDocumentId,
          base_version: state.baseVersion,
          content_text: els.editorBuffer.value,
          merge_strategy: state.autoMergeEnabled ? "auto" : "reject",
          reason: autosave ? "Offline autosave from OpenJson UI" : "Offline save from OpenJson UI",
        });
        setEditorStatus(`Queued offline save. Pending: ${state.offlineQueue.length}.`, "info");
        return;
      }
      throw error;
    } finally {
      state.autosaving = false;
      syncButtons();
    }
  }

  async function loadConflictPreview(error) {
    if (!state.selectedDocumentId || !state.syntaxValid) {
      renderError(els.conflictPanel, error);
      return;
    }
    state.conflictLocalText = els.editorBuffer.value;
    const baseVersion = error.details.client_base_version || state.baseVersion;
    const result = await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/content-conflict-preview`, {
      method: "POST",
      body: {
        base_version: baseVersion,
        content_text: els.editorBuffer.value,
      },
    });
    renderConflict(result);
    setEditorStatus("Version conflict. Reload before saving.", "error");
  }

  async function keepLocalBufferOnLatest() {
    if (!state.selectedDocumentId || !state.conflictLocalText) {
      return;
    }
    const documentId = state.selectedDocumentId;
    const localText = state.conflictLocalText;
    await loadBootstrap(documentId);
    els.editorBuffer.value = localText;
    updateSyntaxState();
    syncButtons();
    setEditorStatus("Local buffer kept on latest base. Preview before saving.", "info");
  }

  async function loadHistory() {
    if (!state.selectedDocumentId) {
      return;
    }
    const history = await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/history`);
    renderHistory(history.events || []);
  }

  async function loadDiff() {
    if (!state.selectedDocumentId) {
      return;
    }
    const fromVersion = Number(els.diffFrom.value);
    const toVersion = Number(els.diffTo.value);
    const diff = await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/diff`, {
      query: { from_version: fromVersion, to_version: toVersion },
    });
    renderDiff(diff);
  }

  async function rollbackSelected() {
    if (!state.selectedDocumentId || !state.currentVersion) {
      return;
    }
    const targetVersion = Number(els.rollbackTarget.value);
    if (!Number.isInteger(targetVersion) || targetVersion < 1) {
      renderText(els.rollbackPanel, "Invalid target version.", "error-text");
      return;
    }
    if (!window.confirm(`Rollback to version ${targetVersion}?`)) {
      return;
    }
    const result = await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/rollback`, {
      method: "POST",
      body: {
        base_version: state.currentVersion,
        target_version: targetVersion,
        reason: "Rollback from OpenJson UI",
      },
    });
    renderText(els.rollbackPanel, `Rollback event ${result.event_id} created.`, "ok-text");
    await loadBootstrap(state.selectedDocumentId);
  }

  async function loadCommentThreads() {
    if (!state.selectedDocumentId) {
      state.commentThreads = [];
      clearPanel(els.commentsPanel, "No document selected.");
      return;
    }
    const documentId = state.selectedDocumentId;
    clearPanel(els.commentsPanel, "Loading notes...");
    const result = await apiFetch(`/documents/${encodeURIComponent(documentId)}/comment-threads`);
    if (documentId !== state.selectedDocumentId) {
      return;
    }
    state.commentThreads = result.threads || [];
    renderCommentThreads();
  }

  async function applyCommentThreadsUpdated(payload) {
    if (!payload || payload.document_id !== state.selectedDocumentId) {
      return;
    }
    await loadCommentThreads();
    setEditorStatus("Notes updated.", "info");
  }

  async function applyDocumentLifecycleUpdate(payload) {
    if (!payload || payload.document_id !== state.selectedDocumentId) {
      return;
    }
    const versionLabel = payload.current_version || "?";
    if (payload.event_type === "delete") {
      if (state.dirty) {
        const pathLabel = payload.full_path || els.documentPath.textContent || "Document";
        state.selectedEditorState = null;
        state.selectedDocumentId = "";
        state.liveTextShadow = "";
        state.liveTextRevision = 0;
        state.liveTextPendingOperation = false;
        state.liveTextNeedsResync = false;
        state.baseVersion = null;
        state.currentVersion = payload.current_version || null;
        state.commentThreads = [];
        localStorage.removeItem("openjson.selectedDocumentId");
        updateBrowserUrl();
        stopCollaborationLoop();
        els.documentPath.textContent = `${pathLabel} (deleted)`;
        els.documentMeta.textContent = `Deleted at version ${versionLabel}`;
        clearPanel(els.collaborationPanel, "Document deleted by another user.");
        clearPanel(els.commentsPanel, "Document deleted. Local buffer preserved.");
        setEditorStatus(`Document deleted at version ${versionLabel}. Local buffer preserved.`, "error");
        syncButtons();
        return;
      }
      setEditorStatus(`Document deleted at version ${versionLabel}.`, "error");
      await loadBootstrap(null);
      return;
    }
    if (payload.event_type === "restore") {
      setEditorStatus(`Document restored at version ${versionLabel}.`, "info");
      await loadBootstrap(payload.document_id);
    }
  }

  async function applyProjectDocumentsChanged(payload) {
    if (!payload || payload.project_id !== state.projectId) {
      return;
    }
    if (state.dirty) {
      setEditorStatus("Project documents changed. Save or reload to refresh the tree.", "info");
      return;
    }
    await loadBootstrap(state.selectedDocumentId || null);
    setEditorStatus("Project documents updated.", "info");
  }

  async function createCommentThread() {
    if (!state.selectedDocumentId) {
      return;
    }
    const body = cleanOptional(els.commentBody.value);
    if (!body) {
      renderText(els.commentsPanel, "Note body is required.", "error-text");
      return;
    }
    const anchorType = els.commentAnchorType.value;
    const payload = {
      body,
      anchor_type: anchorType,
    };
    if (anchorType === "path") {
      payload.path = cleanOptional(els.commentPath.value);
    } else if (anchorType === "event") {
      payload.event_id = cleanOptional(els.commentEventId.value);
    }
    await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/comment-threads`, {
      method: "POST",
      body: payload,
    });
    els.commentBody.value = "";
    await loadCommentThreads();
    setEditorStatus("Note added.", "ok");
    syncButtons();
  }

  async function addCommentReply(threadId) {
    const input = findReplyInput(threadId);
    const body = input ? cleanOptional(input.value) : "";
    if (!body) {
      renderText(els.commentsPanel, "Reply body is required.", "error-text");
      return;
    }
    await apiFetch(`/comment-threads/${encodeURIComponent(threadId)}/comments`, {
      method: "POST",
      body: { body },
    });
    await loadCommentThreads();
    setEditorStatus("Reply added.", "ok");
  }

  async function setCommentThreadStatus(threadId, action) {
    const path =
      action === "resolve"
        ? `/comment-threads/${encodeURIComponent(threadId)}/resolve`
        : `/comment-threads/${encodeURIComponent(threadId)}/reopen`;
    await apiFetch(path, {
      method: "POST",
    });
    await loadCommentThreads();
    setEditorStatus(action === "resolve" ? "Note resolved." : "Note reopened.", "ok");
  }

  async function handleCommentsPanelClick(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    const addButton = target.closest("[data-add-comment]");
    if (addButton) {
      const threadId = addButton.getAttribute("data-add-comment");
      if (threadId) {
        await addCommentReply(threadId);
      }
      return;
    }
    const resolveButton = target.closest("[data-resolve-thread]");
    if (resolveButton) {
      const threadId = resolveButton.getAttribute("data-resolve-thread");
      if (threadId) {
        await setCommentThreadStatus(threadId, "resolve");
      }
      return;
    }
    const reopenButton = target.closest("[data-reopen-thread]");
    if (reopenButton) {
      const threadId = reopenButton.getAttribute("data-reopen-thread");
      if (threadId) {
        await setCommentThreadStatus(threadId, "reopen");
      }
    }
  }

  function findReplyInput(threadId) {
    const inputs = els.commentsPanel.querySelectorAll("[data-comment-reply]");
    for (const input of inputs) {
      if (input instanceof HTMLTextAreaElement && input.dataset.commentReply === threadId) {
        return input;
      }
    }
    return null;
  }

  function syncCommentAnchorControls() {
    const anchorType = els.commentAnchorType.value;
    els.commentPathField.classList.toggle("hidden", anchorType !== "path");
    els.commentEventField.classList.toggle("hidden", anchorType !== "event");
  }

  function renderCommentThreads() {
    clear(els.commentsPanel);
    const openCount = state.commentThreads.filter((thread) => thread.status !== "resolved").length;
    const summary = document.createElement("div");
    summary.className = "chip-row left";
    summary.appendChild(chip(`${state.commentThreads.length} thread(s)`, "info"));
    summary.appendChild(chip(`${openCount} open`, openCount ? "warn" : "ok"));
    els.commentsPanel.appendChild(summary);

    if (!state.commentThreads.length) {
      renderText(els.commentsPanel, "No notes yet.", "muted");
      return;
    }

    const canComment = Boolean(
      state.selectedEditorState &&
        state.selectedEditorState.editor &&
        state.selectedEditorState.editor.capabilities &&
        state.selectedEditorState.editor.capabilities.can_comment
    );
    for (const thread of state.commentThreads) {
      els.commentsPanel.appendChild(renderCommentThread(thread, canComment));
    }
  }

  function renderCommentThread(thread, canComment) {
    const wrapper = document.createElement("div");
    wrapper.className = "comment-thread";

    const header = document.createElement("div");
    header.className = "comment-thread-header";
    const title = document.createElement("strong");
    title.textContent = threadAnchorLabel(thread);
    const status = chip(thread.status || "open", thread.status === "resolved" ? "ok" : "warn");
    header.append(title, status);
    wrapper.appendChild(header);

    const meta = document.createElement("span");
    meta.className = "muted";
    meta.textContent = `${thread.created_by_display_name || thread.created_by} / ${thread.created_at}`;
    wrapper.appendChild(meta);

    for (const comment of thread.comments || []) {
      const row = document.createElement("div");
      row.className = "comment-message";
      const body = document.createElement("div");
      body.textContent = comment.body;
      const detail = document.createElement("span");
      detail.className = "muted";
      detail.textContent = `${comment.author_display_name || comment.author_id} / ${comment.created_at}`;
      row.append(body, detail);
      wrapper.appendChild(row);
    }

    if (canComment) {
      const reply = document.createElement("textarea");
      reply.rows = 2;
      reply.placeholder = "Reply";
      reply.dataset.commentReply = thread.id;
      wrapper.appendChild(reply);

      const actions = document.createElement("div");
      actions.className = "button-row compact-row";
      const addButton = document.createElement("button");
      addButton.type = "button";
      addButton.className = "secondary-button";
      addButton.dataset.addComment = thread.id;
      addButton.textContent = "Reply";
      actions.appendChild(addButton);

      const statusButton = document.createElement("button");
      statusButton.type = "button";
      statusButton.className = "secondary-button";
      if (thread.status === "resolved") {
        statusButton.dataset.reopenThread = thread.id;
        statusButton.textContent = "Reopen";
      } else {
        statusButton.dataset.resolveThread = thread.id;
        statusButton.textContent = "Resolve";
      }
      actions.appendChild(statusButton);
      wrapper.appendChild(actions);
    }

    return wrapper;
  }

  function threadAnchorLabel(thread) {
    if (thread.anchor_type === "path") {
      return `Path ${thread.path || ""}`;
    }
    if (thread.anchor_type === "event") {
      return `Event ${thread.event_id || ""}`;
    }
    return "Document";
  }

  function updateSyntaxState() {
    const text = els.editorBuffer.value;
    state.dirty = text !== state.originalText;
    if (!state.selectedDocumentId) {
      state.syntaxValid = false;
      return;
    }
    try {
      JSON.parse(text);
      state.syntaxValid = true;
      setEditorStatus(state.dirty ? "Unsaved changes." : "Clean.", state.dirty ? "info" : "ok");
    } catch (error) {
      state.syntaxValid = false;
      setEditorStatus(`Invalid JSON: ${error.message}`, "error");
    }
    sendPresenceHeartbeat().catch(() => {});
    scheduleAutosave();
  }

  function restartCollaborationLoop() {
    stopCollaborationLoop();
    if (!state.selectedDocumentId) {
      clearPanel(els.collaborationPanel, "No active document.");
      return;
    }
    state.activePresenceDocumentId = state.selectedDocumentId;
    state.collaborationStopped = false;
    state.collaborationTransport = "polling";
    openCollaborationSocket();
    sendPresenceHeartbeat().catch(() => {});
    refreshCollaborationState().catch((error) => renderError(els.collaborationPanel, error));
    state.presenceTimer = window.setInterval(() => {
      sendPresenceHeartbeat().catch(() => {});
    }, 5000);
    state.collaborationTimer = window.setInterval(() => {
      if (sendRealtimeMessage({ type: "refresh", since_version: state.currentVersion })) {
        return;
      }
      refreshCollaborationState().catch((error) => renderError(els.collaborationPanel, error));
    }, 5000);
  }

  function stopCollaborationLoop() {
    state.collaborationStopped = true;
    sendPresenceLeave(state.activePresenceDocumentId || state.selectedDocumentId);
    state.activePresenceDocumentId = "";
    window.clearInterval(state.presenceTimer);
    window.clearInterval(state.collaborationTimer);
    window.clearTimeout(state.autosaveTimer);
    window.clearTimeout(state.collaborationReconnectTimer);
    state.presenceTimer = null;
    state.collaborationTimer = null;
    state.autosaveTimer = null;
    state.collaborationReconnectTimer = null;
    if (state.collaborationSocket) {
      const socket = state.collaborationSocket;
      state.collaborationSocket = null;
      socket.close();
    }
  }

  function ensureProjectWorkspaceSocket() {
    if (!state.projectId || !state.token || !("WebSocket" in window)) {
      return;
    }
    if (state.projectSocket && state.projectSocketProjectId === state.projectId) {
      return;
    }
    stopProjectWorkspaceSocket();
    state.projectWorkspaceStopped = false;
    openProjectWorkspaceSocket();
  }

  function stopProjectWorkspaceSocket() {
    state.projectWorkspaceStopped = true;
    window.clearTimeout(state.projectReconnectTimer);
    state.projectReconnectTimer = null;
    state.projectSocketProjectId = "";
    if (state.projectSocket) {
      const socket = state.projectSocket;
      state.projectSocket = null;
      socket.close();
    }
  }

  function openProjectWorkspaceSocket() {
    if (!state.projectId || !state.token || !("WebSocket" in window)) {
      return;
    }
    const projectId = state.projectId;
    const url = new URL(`/ws/projects/${encodeURIComponent(projectId)}/workspace`, window.location.origin);
    url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("token", state.token);
    const socket = new WebSocket(url.toString());
    state.projectSocket = socket;
    state.projectSocketProjectId = projectId;

    socket.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (payload.type === "project.documents.changed") {
        applyProjectDocumentsChanged(payload).catch((error) => renderError(els.validationPanel, error));
      } else if (payload.type === "error" && payload.error) {
        renderErrorObject(els.validationPanel, payload.error);
      }
    });

    socket.addEventListener("close", () => {
      if (state.projectSocket !== socket) {
        return;
      }
      state.projectSocket = null;
      state.projectSocketProjectId = "";
      if (state.projectWorkspaceStopped || state.projectId !== projectId) {
        return;
      }
      state.projectReconnectTimer = window.setTimeout(() => {
        openProjectWorkspaceSocket();
      }, 2000);
    });

    socket.addEventListener("error", () => {
      if (state.projectSocket === socket) {
        socket.close();
      }
    });
  }

  function openCollaborationSocket() {
    if (!state.selectedDocumentId || !state.token || !("WebSocket" in window)) {
      state.collaborationTransport = "polling";
      return;
    }
    const documentId = state.selectedDocumentId;
    const url = new URL(`/ws/documents/${encodeURIComponent(documentId)}/collaboration`, window.location.origin);
    url.protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    url.searchParams.set("token", state.token);
    const socket = new WebSocket(url.toString());
    state.collaborationSocket = socket;
    state.collaborationTransport = "connecting";

    socket.addEventListener("open", () => {
      if (state.collaborationSocket !== socket) {
        return;
      }
      state.collaborationTransport = "websocket";
      if (state.liveTextEnabled) {
        joinLiveTextSession();
      }
      sendPresenceHeartbeat().catch(() => {});
    });

    socket.addEventListener("message", (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (payload.type === "collaboration_state" && payload.state) {
        applyCollaborationState(payload.state).catch((error) => renderError(els.collaborationPanel, error));
      } else if (payload.type === "comment_threads.updated") {
        applyCommentThreadsUpdated(payload).catch((error) => renderError(els.commentsPanel, error));
      } else if (payload.type === "document.lifecycle") {
        applyDocumentLifecycleUpdate(payload).catch((error) => renderError(els.collaborationPanel, error));
      } else if (payload.type === "error" && payload.error) {
        markLiveTextOperationUnacknowledged();
        renderErrorObject(els.collaborationPanel, payload.error);
        resyncLiveTextSessionAfterConflict(payload.error);
      } else if (payload.type === "text_session.state") {
        applyLiveTextState(payload);
      } else if (payload.type === "text_session.op.accepted") {
        applyAcceptedLiveTextOperation(payload);
      } else if (payload.type === "text_session.committed") {
        setEditorStatus(`Live text committed as version ${payload.result_version}.`, "ok");
        loadBootstrap(state.selectedDocumentId).catch((error) => showGlobalError(error));
      }
    });

    socket.addEventListener("close", () => {
      if (state.collaborationSocket !== socket) {
        return;
      }
      state.collaborationSocket = null;
      state.collaborationTransport = "polling";
      markLiveTextOperationUnacknowledged();
      if (state.collaborationStopped || state.selectedDocumentId !== documentId) {
        return;
      }
      state.collaborationReconnectTimer = window.setTimeout(() => {
        openCollaborationSocket();
      }, 3000);
    });

    socket.addEventListener("error", () => {
      state.collaborationTransport = "polling";
      markLiveTextOperationUnacknowledged();
    });
  }

  function sendRealtimeMessage(payload) {
    if (!state.collaborationSocket || state.collaborationSocket.readyState !== WebSocket.OPEN) {
      return false;
    }
    state.collaborationSocket.send(JSON.stringify(payload));
    return true;
  }

  function newClientOperationId(prefix) {
    if (window.crypto && crypto.randomUUID) {
      return `${prefix}-${crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function joinLiveTextSession() {
    if (!state.liveTextEnabled || !state.selectedDocumentId) {
      return;
    }
    if (!sendRealtimeMessage({ type: "text_session.join" })) {
      openCollaborationSocket();
    }
  }

  function commitLiveTextSession() {
    if (!state.liveTextEnabled || !state.selectedDocumentId) {
      return;
    }
    if (state.liveTextPendingOperation) {
      setEditorStatus("Live text change is still syncing.", "info");
      return;
    }
    if (state.liveTextShadow !== els.editorBuffer.value) {
      handleLiveTextInput();
      setEditorStatus("Syncing latest live text before commit.", "info");
      return;
    }
    const sent = sendRealtimeMessage({
      type: "text_session.commit",
      text_revision: state.liveTextRevision,
      reason: "Committed collaborative text from OpenJson UI",
      merge_strategy: state.autoMergeEnabled ? "auto" : "reject",
    });
    if (!sent) {
      setEditorStatus("Live text socket is not connected.", "error");
    }
  }

  function applyLiveTextState(payload) {
    const sessionText = payload.content_text || "";
    const wasReset = payload.session_reset === true;
    const hasLocalLiveTextBuffer =
      state.liveTextPendingOperation || state.liveTextNeedsResync || state.liveTextShadow !== els.editorBuffer.value;
    state.liveTextRevision = payload.text_revision || 0;
    state.liveTextShadow = sessionText;
    state.liveTextPendingOperation = false;
    state.liveTextNeedsResync = false;
    if (hasLocalLiveTextBuffer) {
      updateSyntaxState();
      scheduleLiveTextDiffIfNeeded();
      const message = wasReset
        ? `Live text session reset to document v${payload.document_version}. Local buffer preserved and syncing.`
        : `Live text session rejoined at r${state.liveTextRevision}. Local buffer preserved and syncing.`;
      setEditorStatus(message, "info");
      return;
    }
    state.liveTextApplyingRemote = true;
    els.editorBuffer.value = sessionText;
    state.liveTextApplyingRemote = false;
    updateSyntaxState();
    const message = wasReset
      ? `Live text session reset to document v${payload.document_version}.`
      : `Live text session joined at r${state.liveTextRevision}.`;
    setEditorStatus(message, "ok");
  }

  function applyAcceptedLiveTextOperation(payload) {
    if (payload.document_id !== state.selectedDocumentId || !payload.op) {
      return;
    }
    state.liveTextRevision = Math.max(state.liveTextRevision, payload.server_text_revision || 0);
    const authoritativeText = typeof payload.content_text === "string" ? payload.content_text : null;
    if (payload.idempotent_replay || payload.client_id === state.liveTextClientId) {
      if (authoritativeText !== null) {
        state.liveTextShadow = authoritativeText;
      }
      finishLocalLiveTextOperation();
      return;
    }
    const hasLocalLiveTextBuffer =
      state.liveTextPendingOperation || state.liveTextNeedsResync || state.liveTextShadow !== els.editorBuffer.value;
    state.liveTextShadow = authoritativeText !== null ? authoritativeText : applyTextOperation(state.liveTextShadow, payload.op);
    state.liveTextNeedsResync = false;
    if (hasLocalLiveTextBuffer) {
      scheduleLiveTextDiffIfNeeded();
      return;
    }
    state.liveTextApplyingRemote = true;
    els.editorBuffer.value = authoritativeText !== null ? authoritativeText : applyTextOperation(els.editorBuffer.value, payload.op);
    state.liveTextApplyingRemote = false;
    updateSyntaxState();
  }

  function scheduleLiveTextDiffIfNeeded() {
    if (state.liveTextEnabled && !state.liveTextPendingOperation && state.liveTextShadow !== els.editorBuffer.value) {
      window.setTimeout(() => handleLiveTextInput(), 0);
    }
  }

  function finishLocalLiveTextOperation() {
    state.liveTextPendingOperation = false;
    state.liveTextNeedsResync = false;
    scheduleLiveTextDiffIfNeeded();
  }

  function markLiveTextOperationUnacknowledged() {
    if (state.liveTextPendingOperation) {
      state.liveTextNeedsResync = true;
    }
    state.liveTextPendingOperation = false;
  }

  function resyncLiveTextSessionAfterConflict(error) {
    if (error && error.code === "VERSION_CONFLICT" && state.liveTextEnabled && state.selectedDocumentId) {
      window.setTimeout(() => joinLiveTextSession(), 0);
    }
  }

  function handleLiveTextInput() {
    if (!state.liveTextEnabled || state.liveTextApplyingRemote || !state.selectedDocumentId) {
      return;
    }
    if (state.liveTextPendingOperation) {
      return;
    }
    const op = diffTextOperation(state.liveTextShadow, els.editorBuffer.value);
    if (!op) {
      return;
    }
    const sent = sendRealtimeMessage({
      type: "text_session.op",
      client_id: state.liveTextClientId,
      client_operation_id: newClientOperationId("live-op"),
      base_text_revision: state.liveTextRevision,
      op,
    });
    if (sent) {
      state.liveTextPendingOperation = true;
      state.liveTextNeedsResync = false;
      state.liveTextShadow = els.editorBuffer.value;
    }
  }

  function diffTextOperation(before, after) {
    if (before === after) {
      return null;
    }
    let prefix = 0;
    while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) {
      prefix += 1;
    }
    let beforeSuffix = before.length - 1;
    let afterSuffix = after.length - 1;
    while (beforeSuffix >= prefix && afterSuffix >= prefix && before[beforeSuffix] === after[afterSuffix]) {
      beforeSuffix -= 1;
      afterSuffix -= 1;
    }
    const removed = beforeSuffix - prefix + 1;
    const inserted = after.slice(prefix, afterSuffix + 1);
    if (removed > 0 && inserted.length === 0) {
      return { type: "delete", index: prefix, length: removed };
    }
    if (removed === 0 && inserted.length > 0) {
      return { type: "insert", index: prefix, text: inserted };
    }
    return { type: "replace", index: prefix, length: removed, text: inserted };
  }

  function applyTextOperation(text, op) {
    const index = Math.min(op.index, text.length);
    if (op.type === "insert") {
      return `${text.slice(0, index)}${op.text || ""}${text.slice(index)}`;
    }
    if (op.type === "replace") {
      const length = Math.min(op.length || 0, Math.max(0, text.length - index));
      return `${text.slice(0, index)}${op.text || ""}${text.slice(index + length)}`;
    }
    const length = Math.min(op.length || 0, Math.max(0, text.length - index));
    return `${text.slice(0, index)}${text.slice(index + length)}`;
  }

  function escapeJsonPointerSegment(segment) {
    return String(segment).replace(/~/g, "~0").replace(/\//g, "~1");
  }

  function pointerFromSegments(segments) {
    return segments.length ? `/${segments.map(escapeJsonPointerSegment).join("/")}` : "";
  }

  function valuePathForContainer(parent) {
    if (!parent) {
      return [];
    }
    if (parent.type === "object") {
      return parent.key === null ? parent.path.slice() : parent.path.concat(parent.key);
    }
    return parent.path.concat(String(parent.index));
  }

  function markValueComplete(stack) {
    const parent = stack[stack.length - 1];
    if (!parent) {
      return;
    }
    if (parent.type === "object") {
      parent.key = null;
      parent.expecting = "comma";
    } else {
      parent.index += 1;
      parent.expecting = "comma";
    }
  }

  function currentJsonCursorPath(stack) {
    const current = stack[stack.length - 1];
    if (!current) {
      return "";
    }
    if (current.type === "object") {
      return pointerFromSegments(current.key === null ? current.path : current.path.concat(current.key));
    }
    return pointerFromSegments(current.path.concat(String(current.index)));
  }

  function readJsonStringToken(text, start) {
    let value = "";
    let i = start + 1;
    while (i < text.length) {
      const char = text[i];
      if (char === "\\") {
        value += text.slice(i, i + 2);
        i += 2;
        continue;
      }
      if (char === '"') {
        return { value, end: i + 1 };
      }
      value += char;
      i += 1;
    }
    return { value, end: i };
  }

  function skipJsonLiteral(text, start) {
    let i = start;
    while (i < text.length && !/[\s,\]}:]/.test(text[i])) {
      i += 1;
    }
    return i;
  }

  function findJsonPointerNearOffset(text, offset) {
    const stack = [];
    let i = 0;
    while (i < text.length && i <= offset) {
      const char = text[i];
      if (/\s/.test(char)) {
        i += 1;
        continue;
      }
      const parent = stack[stack.length - 1];
      if (char === "{") {
        stack.push({ type: "object", path: valuePathForContainer(parent), key: null, index: 0, expecting: "key" });
        i += 1;
        continue;
      }
      if (char === "[") {
        stack.push({ type: "array", path: valuePathForContainer(parent), key: null, index: 0, expecting: "value" });
        i += 1;
        continue;
      }
      if (char === "}" || char === "]") {
        stack.pop();
        markValueComplete(stack);
        i += 1;
        continue;
      }
      if (char === ",") {
        if (parent) {
          parent.expecting = parent.type === "object" ? "key" : "value";
        }
        i += 1;
        continue;
      }
      if (char === ":") {
        if (parent && parent.type === "object") {
          parent.expecting = "value";
        }
        i += 1;
        continue;
      }
      if (char === '"') {
        const token = readJsonStringToken(text, i);
        if (parent && parent.type === "object" && parent.expecting === "key") {
          parent.key = token.value;
          parent.expecting = "colon";
        } else {
          markValueComplete(stack);
        }
        i = token.end;
        continue;
      }
      i = skipJsonLiteral(text, i);
      markValueComplete(stack);
    }
    return currentJsonCursorPath(stack);
  }

  function buildEditorCursorPath() {
    if (!state.selectedDocumentId || !els.editorBuffer) {
      return null;
    }
    const offset = Number.isInteger(els.editorBuffer.selectionStart) ? els.editorBuffer.selectionStart : 0;
    return findJsonPointerNearOffset(els.editorBuffer.value || "", offset);
  }

  function schedulePresenceCursorUpdate() {
    if (!state.selectedDocumentId) {
      return;
    }
    if (state.presenceCursorTimer) {
      window.clearTimeout(state.presenceCursorTimer);
    }
    state.presenceCursorTimer = window.setTimeout(() => {
      state.presenceCursorTimer = null;
      sendPresenceHeartbeat().catch(() => {});
    }, 250);
  }

  function buildPresencePayload() {
    if (!state.selectedDocumentId || !state.currentVersion) {
      return null;
    }
    const caps = state.selectedEditorState ? state.selectedEditorState.editor.capabilities : {};
    return {
      type: "presence",
      status: state.dirty && caps.can_patch ? "editing" : "viewing",
      base_version: state.baseVersion || state.currentVersion,
      dirty: Boolean(state.dirty),
      cursor_path: buildEditorCursorPath(),
    };
  }

  function sendPresenceLeave(documentId) {
    const targetDocumentId = documentId || state.activePresenceDocumentId || state.selectedDocumentId;
    if (!targetDocumentId || !state.token) {
      return;
    }
    const headers = { Accept: "application/json" };
    if (state.token) {
      headers.Authorization = `Bearer ${state.token}`;
    }
    fetch(`/documents/${encodeURIComponent(targetDocumentId)}/presence`, {
      method: "DELETE",
      headers,
      keepalive: true,
    }).catch(() => {});
  }

  async function sendPresenceHeartbeat() {
    const payload = buildPresencePayload();
    if (!payload) {
      return;
    }
    if (sendRealtimeMessage(payload)) {
      return;
    }
    await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/presence`, {
      method: "POST",
      body: {
        status: payload.status,
        base_version: payload.base_version,
        dirty: payload.dirty,
        cursor_path: payload.cursor_path,
      },
    });
  }

  async function refreshCollaborationState() {
    if (!state.selectedDocumentId || !state.currentVersion) {
      return;
    }
    const result = await apiFetch(`/documents/${encodeURIComponent(state.selectedDocumentId)}/collaboration-state`, {
      query: { since_version: state.currentVersion },
    });
    await applyCollaborationState(result);
  }

  async function applyCollaborationState(result) {
    if (!result || result.document_id !== state.selectedDocumentId) {
      return;
    }
    renderCollaboration(result);
    if (result.current_version > state.currentVersion) {
      if (state.dirty) {
        setEditorStatus(`New checkpoint v${result.current_version} is available. Reload before saving.`, "error");
      } else if (!state.loading) {
        const documentId = state.selectedDocumentId;
        setEditorStatus(`Loading checkpoint v${result.current_version}.`, "info");
        await loadBootstrap(documentId);
      }
    }
  }

  function scheduleAutosave() {
    window.clearTimeout(state.autosaveTimer);
    state.autosaveTimer = null;
    if (!state.autosaveEnabled || !state.selectedDocumentId || !state.syntaxValid || !state.dirty) {
      return;
    }
    const caps = state.selectedEditorState ? state.selectedEditorState.editor.capabilities : {};
    if (!caps.can_patch) {
      return;
    }
    state.autosaveTimer = window.setTimeout(() => {
      saveSelected({ autosave: true }).catch((error) => handleMutationError(error));
    }, 2500);
  }

  function syncButtons() {
    const caps = state.selectedEditorState ? state.selectedEditorState.editor.capabilities : {};
    const hasDoc = Boolean(state.selectedDocumentId);
    const canPatch = Boolean(caps.can_patch);
    const canPreview = Boolean(caps.can_patch_preview);
    const canValidate = Boolean(caps.can_validate);
    const canRollback = Boolean(caps.can_rollback);
    const canComment = Boolean(caps.can_comment);
    const commentAnchorType = els.commentAnchorType.value;
    const missingCommentAnchor =
      (commentAnchorType === "path" && !cleanOptional(els.commentPath.value)) ||
      (commentAnchorType === "event" && !cleanOptional(els.commentEventId.value));
    const ambiguousSchema =
      state.createSchemaMatch &&
      state.createSchemaMatch.resolution &&
      state.createSchemaMatch.resolution.status === "ambiguous" &&
      !cleanOptional(els.schemaSelect.value);
    const busy = state.loading || state.autosaving;
    els.signupButton.disabled = busy;
    els.loginButton.disabled = busy;
    els.logoutButton.disabled = busy || !state.token;
    els.projectLogoutButton.disabled = busy || !state.token;
    els.refreshProjectsButton.disabled = busy || !state.token;
    els.showCreateProjectButton.disabled = busy || !state.token;
    els.cancelProjectCreateButton.disabled = busy || !state.token;
    els.createProjectButton.disabled = busy || !state.token;
    els.reloadButton.disabled = busy;
    els.zipSelectButton.disabled = busy;
    els.zipPreviewButton.disabled = busy || !state.zipFile;
    els.zipApplyButton.disabled = busy || !state.zipFile || !state.zipPreview || !state.zipPreview.can_apply;
    els.refreshTeamButton.disabled = busy || !state.projectId;
    els.createInviteButton.disabled = busy || !state.projectId;
    els.copyInviteLinkButton.disabled = busy || !els.inviteLink.value.trim();
    els.acceptInviteButton.disabled = busy || !els.projectInviteToken.value.trim();
    els.createDocumentButton.disabled = busy || Boolean(ambiguousSchema);
    els.validateButton.disabled = busy || !hasDoc || !canValidate;
    els.importEditorButton.disabled = busy || !hasDoc || !canPatch;
    els.previewButton.disabled = busy || !hasDoc || !canPreview || !state.syntaxValid;
    els.saveButton.disabled = busy || !hasDoc || !canPatch || !state.syntaxValid || !state.dirty;
    els.commitLiveButton.disabled =
      busy ||
      !hasDoc ||
      !canPatch ||
      !state.liveTextEnabled ||
      state.collaborationTransport !== "websocket" ||
      !state.syntaxValid;
    els.historyButton.disabled = busy || !hasDoc;
    els.diffButton.disabled = busy || !hasDoc;
    els.rollbackButton.disabled = busy || !hasDoc || !canRollback;
    els.commentsButton.disabled = busy || !hasDoc;
    els.commentAnchorType.disabled = busy || !hasDoc || !canComment;
    els.commentPath.disabled = busy || !hasDoc || !canComment;
    els.commentEventId.disabled = busy || !hasDoc || !canComment;
    els.commentBody.disabled = busy || !hasDoc || !canComment;
    els.createCommentThreadButton.disabled =
      busy || !hasDoc || !canComment || !cleanOptional(els.commentBody.value) || missingCommentAnchor;
  }

  function renderSchemaOptions() {
    const current = els.schemaSelect.value;
    while (els.schemaSelect.firstChild) {
      els.schemaSelect.removeChild(els.schemaSelect.firstChild);
    }
    const automatic = document.createElement("option");
    automatic.value = "";
    automatic.textContent = "Automatic pattern match";
    els.schemaSelect.appendChild(automatic);

    if (state.schemaListError) {
      const unavailable = document.createElement("option");
      unavailable.value = "";
      unavailable.disabled = true;
      unavailable.textContent = "Schemas unavailable";
      els.schemaSelect.appendChild(unavailable);
      return;
    }

    for (const schema of state.projectSchemas) {
      const option = document.createElement("option");
      option.value = schema.id;
      option.textContent = schemaLabel(schema);
      option.disabled = !schema.is_active || Boolean(schema.schema_json_error);
      els.schemaSelect.appendChild(option);
    }
    if (current && state.projectSchemas.some((schema) => schema.id === current)) {
      els.schemaSelect.value = current;
    }
  }

  function scheduleSchemaMatchPreview() {
    window.clearTimeout(state.schemaMatchTimer);
    state.schemaMatchTimer = window.setTimeout(() => {
      previewCreateSchemaMatch().catch((error) => renderError(els.schemaMatchPanel, error));
    }, 220);
  }

  async function previewCreateSchemaMatch() {
    if (els.createPanel.classList.contains("hidden")) {
      return;
    }
    const explicitSchemaId = cleanOptional(els.schemaSelect.value);
    if (explicitSchemaId) {
      state.createSchemaMatch = null;
      renderExplicitCreateSchema(explicitSchemaId);
      syncButtons();
      return;
    }
    const fullPath = cleanOptional(els.newPath.value);
    if (!fullPath) {
      state.createSchemaMatch = null;
      clearPanel(els.schemaMatchPanel, "Enter a path to preview schema binding.");
      syncButtons();
      return;
    }
    const result = await apiFetch(`/projects/${encodeURIComponent(state.projectId)}/schema-matches`, {
      query: { full_path: fullPath },
    });
    state.createSchemaMatch = result;
    renderSchemaMatch(result);
    syncButtons();
  }

  function renderSchema(schema) {
    clear(els.schemaPanel);
    if (state.schemaListError) {
      renderText(els.schemaPanel, `Schema list unavailable: ${state.schemaListError.message}`, "error-text");
    }
    if (!schema) {
      renderText(els.schemaPanel, "Unbound document.", "muted");
      return;
    }
    els.schemaPanel.appendChild(schemaRow(schema));
    if (schema.schema_json_error) {
      const error = document.createElement("pre");
      error.textContent = JSON.stringify(schema.schema_json_error, null, 2);
      els.schemaPanel.appendChild(error);
    }
  }

  function renderExplicitCreateSchema(schemaId) {
    clear(els.schemaMatchPanel);
    const schema = state.projectSchemas.find((item) => item.id === schemaId);
    if (!schema) {
      renderText(els.schemaMatchPanel, "Selected schema is unavailable.", "error-text");
      return;
    }
    renderText(els.schemaMatchPanel, `Explicit binding: ${schemaLabel(schema)}`, schema.is_active ? "ok-text" : "error-text");
    if (schema.file_pattern) {
      renderText(els.schemaMatchPanel, `Pattern: ${schema.file_pattern}`, "muted");
    }
  }

  function renderSchemaMatch(result) {
    clear(els.schemaMatchPanel);
    const status = result.resolution ? result.resolution.status : "unknown";
    if (status === "matched") {
      renderText(els.schemaMatchPanel, "Automatic schema match.", "ok-text");
    } else if (status === "ambiguous") {
      renderText(els.schemaMatchPanel, "Multiple schemas match. Choose one explicitly.", "error-text");
    } else {
      renderText(els.schemaMatchPanel, "No schema match. Document will be unbound.", "muted");
    }
    for (const schema of result.matches || []) {
      els.schemaMatchPanel.appendChild(schemaRow(schema));
    }
  }

  function renderZipImportResult(result) {
    clear(els.zipImportOutput);
    const summary = document.createElement("div");
    summary.className = result.can_apply ? "ok-text" : "error-text";
    summary.textContent = result.can_apply
      ? `Ready: ${result.archive.json_file_count} JSON file(s)`
      : `Blocked: ${result.archive.json_file_count} JSON file(s)`;
    els.zipImportOutput.appendChild(summary);

    const meta = document.createElement("div");
    meta.className = "chip-row left";
    meta.appendChild(chip(`${result.folders.length} folder(s)`, "info"));
    meta.appendChild(chip(`${result.references.summary.edge_count} reference(s)`, "info"));
    if (result.references.summary.missing_count) {
      meta.appendChild(chip(`${result.references.summary.missing_count} missing`, "warn"));
    }
    if (result.archive.skipped_file_count) {
      meta.appendChild(chip(`${result.archive.skipped_file_count} skipped`, "warn"));
    }
    els.zipImportOutput.appendChild(meta);

    renderZipErrors(els.zipImportOutput, result.errors || []);

    for (const file of (result.files || []).slice(0, 24)) {
      const row = document.createElement("div");
      row.className = "change-row";
      const title = document.createElement("strong");
      title.textContent = file.path;
      row.appendChild(title);
      const detail = document.createElement("span");
      detail.className = "muted";
      const schemaStatus = file.schema_match && file.schema_match.status ? file.schema_match.status : "no_match";
      detail.textContent = `${file.root_type || "unknown"} / schema ${schemaStatus} / ${file.references.length} ref(s)`;
      row.appendChild(detail);
      renderZipErrors(row, file.errors || []);
      els.zipImportOutput.appendChild(row);
    }
    if ((result.files || []).length > 24) {
      renderText(els.zipImportOutput, `${result.files.length - 24} more file(s) omitted.`, "muted");
    }

    if (result.references && result.references.missing && result.references.missing.length) {
      renderText(els.zipImportOutput, "Missing references", "error-text");
      for (const ref of result.references.missing.slice(0, 8)) {
        renderText(els.zipImportOutput, `${ref.source_path} ${ref.source_pointer} -> ${ref.target_path || ref.value}`, "muted");
      }
    }

    if (result.created_documents && result.created_documents.length) {
      renderText(els.zipImportOutput, `Imported ${result.created_documents.length} document(s).`, "ok-text");
    }
  }

  function renderZipErrors(panel, errors) {
    for (const error of errors) {
      const row = document.createElement("div");
      row.className = "error-text";
      row.textContent = `${error.code}: ${error.message}`;
      panel.appendChild(row);
    }
  }

  function schemaRow(schema) {
    const row = document.createElement("div");
    row.className = "schema-row";
    const title = document.createElement("div");
    title.className = "schema-title";
    const name = document.createElement("strong");
    name.textContent = schemaLabel(schema);
    const stateChip = chip(schema.is_active ? "active" : "inactive", schema.is_active ? "ok" : "warn");
    title.append(name, stateChip);
    row.appendChild(title);
    const id = document.createElement("code");
    id.textContent = schema.id;
    row.appendChild(id);
    if (schema.file_pattern) {
      const pattern = document.createElement("span");
      pattern.className = "muted";
      pattern.textContent = `Pattern: ${schema.file_pattern}`;
      row.appendChild(pattern);
    }
    if (schema.schema_json_error) {
      const diagnostic = document.createElement("span");
      diagnostic.className = "error-text";
      diagnostic.textContent = schema.schema_json_error.diagnostic_code || "Schema diagnostic";
      row.appendChild(diagnostic);
    }
    return row;
  }

  function schemaLabel(schema) {
    return `${schema.name} v${schema.version}`;
  }

  function renderValidation(validation) {
    clear(els.validationPanel);
    if (!validation || validation.available === false) {
      renderText(els.validationPanel, validation ? `Unavailable: ${validation.reason}` : "No validation", "muted");
      return;
    }
    const summary = document.createElement("div");
    summary.className = validation.valid ? "ok-text" : "error-text";
    summary.textContent = validation.valid ? "Valid" : "Invalid";
    els.validationPanel.appendChild(summary);
    renderIssueList(els.validationPanel, validation.errors || [], "Errors");
    renderIssueList(els.validationPanel, validation.warnings || [], "Warnings");
  }

  function renderCollaboration(result) {
    clear(els.collaborationPanel);
    const summary = document.createElement("div");
    summary.className = "chip-row left";
    summary.appendChild(chip(`v${result.current_version}`, "info"));
    summary.appendChild(chip(`${result.active_users.length} active`, result.active_users.length ? "ok" : "info"));
    summary.appendChild(
      chip(
        state.collaborationTransport === "websocket" ? "live" : state.collaborationTransport,
        state.collaborationTransport === "websocket" ? "ok" : "info",
      )
    );
    if (result.has_updates) {
      summary.appendChild(chip("new checkpoint", "warn"));
    }
    if (state.autosaveEnabled) {
      summary.appendChild(chip("autosave", "ok"));
    }
    if (state.autoMergeEnabled) {
      summary.appendChild(chip("auto-merge", "info"));
    }
    if (state.liveTextEnabled) {
      summary.appendChild(chip(`live r${state.liveTextRevision}`, "info"));
    }
    if (state.offlineQueue.length) {
      summary.appendChild(chip(`${state.offlineQueue.length} offline`, "warn"));
    }
    els.collaborationPanel.appendChild(summary);

    renderText(els.collaborationPanel, "Active users", "muted");
    if (!result.active_users.length) {
      renderText(els.collaborationPanel, "No active users.", "muted");
    }
    for (const user of result.active_users) {
      const row = document.createElement("div");
      row.className = "event-row";
      const title = document.createElement("strong");
      title.textContent = user.display_name || user.actor_id;
      const meta = document.createElement("span");
      meta.className = user.is_stale_base ? "error-text" : "muted";
      const cursor = user.cursor_path || user.cursor_path === "" ? ` / at ${user.cursor_path || "/"}` : "";
      meta.textContent = `${user.status}${user.dirty ? " / dirty" : ""} / base v${user.base_version}${cursor}`;
      row.append(title, meta);
      els.collaborationPanel.appendChild(row);
    }

    renderText(els.collaborationPanel, "Checkpoints", "muted");
    if (!result.checkpoints.length) {
      renderText(els.collaborationPanel, "No newer checkpoints.", "muted");
    }
    for (const checkpoint of result.checkpoints.slice(0, 8)) {
      const row = document.createElement("div");
      row.className = "change-row";
      const title = document.createElement("strong");
      title.textContent = `v${checkpoint.result_version} ${checkpoint.event_type}`;
      const meta = document.createElement("span");
      meta.className = "muted";
      meta.textContent = `${checkpoint.display_name || checkpoint.actor_id} / ${checkpoint.created_at}`;
      row.append(title, meta);
      if (checkpoint.changed_paths && checkpoint.changed_paths.length) {
        const paths = document.createElement("span");
        paths.className = "muted";
        paths.textContent = checkpoint.changed_paths.slice(0, 4).join(", ");
        row.appendChild(paths);
      }
      els.collaborationPanel.appendChild(row);
    }
  }

  function renderIssueList(panel, items, label) {
    if (!items.length) {
      return;
    }
    const title = document.createElement("strong");
    title.textContent = label;
    panel.appendChild(title);
    for (const item of items) {
      const row = document.createElement("div");
      row.className = "change-row";
      const path = document.createElement("strong");
      path.textContent = item.path === "" ? '""' : item.path || "(unknown path)";
      const msg = document.createElement("span");
      msg.textContent = item.message || JSON.stringify(item);
      row.append(path, msg);
      appendIssueField(row, "validator", item.validator);
      appendIssueField(row, "expected", item.expected);
      appendIssueField(row, "actual", item.actual);
      panel.appendChild(row);
    }
  }

  function appendIssueField(row, label, value) {
    if (value === undefined) {
      return;
    }
    const detail = document.createElement("span");
    detail.className = "muted";
    detail.textContent = `${label}: ${formatDiagnosticValue(value)}`;
    row.appendChild(detail);
  }

  function formatDiagnosticValue(value) {
    if (typeof value === "string") {
      return value;
    }
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return String(value);
    }
  }

  function formatBytes(value) {
    const bytes = Number(value) || 0;
    if (bytes >= 1024 * 1024) {
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
    if (bytes >= 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${bytes} B`;
  }

  function renderPreview(preview) {
    clear(els.conflictPanel);
    hideConflictActions();
    const heading = document.createElement("div");
    heading.className = "ok-text";
    heading.textContent = `Preview: ${preview.changed_paths.length} changed path(s)`;
    els.conflictPanel.appendChild(heading);
    renderPatchList(els.conflictPanel, preview.generated_patch || []);
  }

  function renderConflict(result) {
    clear(els.conflictPanel);
    showConflictActions();
    const summary = document.createElement("div");
    summary.className = result.has_conflicts ? "error-text" : "muted";
    summary.textContent = result.has_conflicts ? "Overlapping changes" : "No direct path overlap";
    els.conflictPanel.appendChild(summary);
    renderChangeList(els.conflictPanel, result.conflicts || [], "Conflicts");
    renderChangeList(els.conflictPanel, result.client_changes || [], "Client");
    renderChangeList(els.conflictPanel, result.server_changes || [], "Server");
  }

  function showConflictActions() {
    els.conflictActions.classList.remove("hidden");
  }

  function hideConflictActions() {
    els.conflictActions.classList.add("hidden");
  }

  function renderRecentEvents(events) {
    if (!events.length) {
      clearPanel(els.historyPanel, "No history");
      return;
    }
    renderHistory(events);
  }

  function renderHistory(events) {
    clear(els.historyPanel);
    for (const event of events.slice(0, 12)) {
      const row = document.createElement("div");
      row.className = "event-row";
      const title = document.createElement("strong");
      title.textContent = `v${event.result_version} ${event.event_type}`;
      const meta = document.createElement("span");
      meta.className = "muted";
      meta.textContent = `${event.actor_display_name || event.actor_id} / ${event.created_at}`;
      row.append(title, meta);
      els.historyPanel.appendChild(row);
    }
  }

  function renderDiff(diff) {
    clear(els.diffPanel);
    if (!diff.changes.length) {
      renderText(els.diffPanel, "No changes", "muted");
      return;
    }
    renderChangeList(els.diffPanel, diff.changes, `v${diff.from_version} to v${diff.to_version}`);
  }

  function renderPatchList(panel, patch) {
    if (!patch.length) {
      renderText(panel, "No generated patch", "muted");
      return;
    }
    for (const op of patch) {
      const row = document.createElement("div");
      row.className = "change-row";
      const title = document.createElement("strong");
      title.textContent = `${op.op} ${op.path}`;
      const value = document.createElement("pre");
      value.textContent = JSON.stringify(op.value, null, 2);
      row.append(title, value);
      panel.appendChild(row);
    }
  }

  function renderChangeList(panel, changes, label) {
    const title = document.createElement("strong");
    title.textContent = label;
    panel.appendChild(title);
    if (!changes.length) {
      renderText(panel, "None", "muted");
      return;
    }
    for (const change of changes) {
      const row = document.createElement("div");
      row.className = "change-row";
      const head = document.createElement("strong");
      head.textContent = `${change.change_type || change.conflict_type || "change"} ${change.path || ""}`;
      const before = document.createElement("pre");
      before.textContent = `before: ${JSON.stringify(change.before, null, 2)}`;
      const after = document.createElement("pre");
      after.textContent = `after: ${JSON.stringify(change.after, null, 2)}`;
      row.append(head, before, after);
      panel.appendChild(row);
    }
  }

  async function apiFetch(path, options) {
    const method = options && options.method ? options.method : "GET";
    const includeAuth = !(options && options.auth === false);
    const url = new URL(path, window.location.origin);
    const query = options && options.query ? options.query : {};
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && String(value) !== "") {
        url.searchParams.set(key, String(value));
      }
    }
    const headers = { Accept: "application/json" };
    if (includeAuth && state.token) {
      headers.Authorization = `Bearer ${state.token}`;
    }
    const init = { method, headers };
    if (options && Object.prototype.hasOwnProperty.call(options, "body")) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    let response = await fetch(url, init);
    if (response.status === 401 && state.refreshToken && includeAuth && !(options && options.retrying)) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        return apiFetch(path, { ...options, retrying: true });
      }
    }
    const text = await response.text();
    const body = text ? JSON.parse(text) : null;
    if (!response.ok) {
      throw new ApiError(response, body);
    }
    return body;
  }

  async function refreshAccessToken() {
    try {
      const result = await apiFetch("/auth/refresh", {
        method: "POST",
        auth: false,
        body: {
          refresh_token: state.refreshToken,
        },
        retrying: true,
      });
      applyAuthenticatedSession(result);
      return true;
    } catch (error) {
      clearSessionState();
      return false;
    }
  }

  function queueOfflineSave(payload) {
    state.offlineQueue.push({
      client_operation_id: `offline-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      operation_type: "content_update",
      ...payload,
    });
    writeOfflineQueue();
  }

  async function flushOfflineQueue() {
    if (!state.projectId || !state.offlineQueue.length) {
      return;
    }
    const result = await apiFetch(`/projects/${encodeURIComponent(state.projectId)}/offline-sync`, {
      method: "POST",
      body: {
        items: state.offlineQueue,
      },
    });
    const unresolved = new Set(
      result.results
        .filter((item) => item.status === "conflict")
        .map((item) => item.client_operation_id)
    );
    state.offlineQueue = state.offlineQueue.filter((item) => unresolved.has(item.client_operation_id));
    writeOfflineQueue();
    setEditorStatus(
      `Offline sync applied ${result.summary.applied}, conflicts ${result.summary.conflict}, failed ${result.summary.failed}.`,
      result.summary.conflict || result.summary.failed ? "error" : "ok",
    );
    if (state.selectedDocumentId) {
      await loadBootstrap(state.selectedDocumentId);
    }
  }

  function readOfflineQueue() {
    try {
      const parsed = JSON.parse(localStorage.getItem("openjson.offlineQueue") || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function writeOfflineQueue() {
    localStorage.setItem("openjson.offlineQueue", JSON.stringify(state.offlineQueue));
  }

  async function apiFetchBinary(path, options) {
    const method = options && options.method ? options.method : "POST";
    const url = new URL(path, window.location.origin);
    const query = options && options.query ? options.query : {};
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && String(value) !== "") {
        url.searchParams.set(key, String(value));
      }
    }
    const headers = {
      Accept: "application/json",
      "Content-Type": (options && options.contentType) || "application/octet-stream",
    };
    if (state.token) {
      headers.Authorization = `Bearer ${state.token}`;
    }
    const response = await fetch(url, { method, headers, body: options ? options.body : undefined });
    const text = await response.text();
    const body = text ? JSON.parse(text) : null;
    if (!response.ok) {
      throw new ApiError(response, body);
    }
    return body;
  }

  function handleMutationError(error) {
    if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
      loadConflictPreview(error).catch((inner) => renderError(els.conflictPanel, inner));
      return;
    }
    if (isSchemaValidationError(error)) {
      renderSchemaValidationFailure(error);
      clearPanel(els.conflictPanel, "No conflict");
      hideConflictActions();
      setEditorStatus("Schema validation failed. No event was created.", "error");
      return;
    }
    renderError(els.conflictPanel, error);
    setEditorStatus(error.message || "Request failed.", "error");
  }

  function handleZipImportError(error) {
    renderError(els.zipImportOutput, error);
    setEditorStatus(error.message || "ZIP import failed.", "error");
    syncButtons();
  }

  function handleCreationError(error) {
    if (isSchemaValidationError(error)) {
      renderSchemaValidationFailure(error);
      setEditorStatus("Schema validation failed. Document was not created.", "error");
      return;
    }
    renderError(els.validationPanel, error);
    setEditorStatus(error.message || "Create failed.", "error");
  }

  function isSchemaValidationError(error) {
    return error instanceof ApiError && error.code === "SCHEMA_VALIDATION_FAILED";
  }

  function renderSchemaValidationFailure(error) {
    clear(els.validationPanel);
    renderText(els.validationPanel, "Schema validation failed.", "error-text");
    const errors = error.details && Array.isArray(error.details.errors) ? error.details.errors : [];
    renderIssueList(els.validationPanel, errors, "Errors");
    if (!errors.length) {
      renderError(els.validationPanel, error);
    }
  }

  function renderFileImportError(error) {
    els.createFileInput.value = "";
    els.editorFileInput.value = "";
    clear(els.validationPanel);
    renderText(els.validationPanel, `Invalid JSON file: ${error.message}`, "error-text");
    setEditorStatus("JSON file import failed.", "error");
  }

  function showGlobalError(error) {
    state.loading = false;
    syncButtons();
    renderError(els.validationPanel, error);
    setEditorStatus(error.message || "Request failed.", "error");
  }

  function renderError(panel, error) {
    clear(panel);
    if (panel === els.conflictPanel) {
      hideConflictActions();
    }
    const code = error instanceof ApiError ? error.code : "ERROR";
    const message = error.message || "Request failed.";
    renderText(panel, `${code}: ${message}`, "error-text");
    if (error instanceof ApiError && error.details && Object.keys(error.details).length) {
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(error.details, null, 2);
      panel.appendChild(pre);
    }
  }

  function renderErrorObject(panel, error) {
    clear(panel);
    renderText(panel, `${error.code || "ERROR"}: ${error.message || "Request failed."}`, "error-text");
    if (error.details && Object.keys(error.details).length) {
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(error.details, null, 2);
      panel.appendChild(pre);
    }
  }

  function renderText(panel, text, className) {
    const div = document.createElement("div");
    div.className = className || "";
    div.textContent = text;
    panel.appendChild(div);
  }

  function setEditorStatus(text, tone) {
    els.editorStatus.textContent = text;
    els.editorStatus.className = "editor-status";
    if (tone === "error") {
      els.editorStatus.classList.add("error-text");
    } else if (tone === "ok") {
      els.editorStatus.classList.add("ok-text");
    }
  }

  function clearPanel(panel, text) {
    clear(panel);
    renderText(panel, text, "muted");
  }

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function chip(text, tone) {
    const element = document.createElement("span");
    element.className = `chip ${tone || ""}`;
    element.textContent = text;
    return element;
  }

  function cleanOptional(value) {
    const trimmed = value.trim();
    return trimmed ? trimmed : undefined;
  }

  document.addEventListener("DOMContentLoaded", init);
})();
