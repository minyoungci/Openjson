# Collaborative JSON DB Workspace — Technical Specification

**Version:** v0.1 Draft  
**Date:** 2026-06-24  
**Prepared for:** Product / Engineering Team  
**Document type:** Technical specification  
**Primary goal:** 여러 JSON 파일로 구성된 구조화 데이터베이스를 팀 단위로 공동 편집, 검증, 추적, 리뷰, 복구할 수 있는 웹 기반 협업 플랫폼 설계

---

## 0. Executive Summary

본 문서는 여러 사용자가 같은 workspace 안에서 JSON 파일들을 GitHub repository처럼 폴더 구조로 관리하고, Google Docs처럼 빠르게 공유·수정하며, 모든 변경을 JSON path 단위로 추적할 수 있는 서비스를 구현하기 위한 기술 명세서이다.

서비스의 핵심은 단순한 JSON editor가 아니다. 최종 목표는 **Collaborative JSON-native Versioned Data Platform**이다. 이 시스템은 JSON 파일의 최신 상태를 빠르게 조회하기 위한 snapshot과, 모든 수정 이력을 신뢰 가능하게 보존하기 위한 append-only event log를 함께 저장한다. 모든 변경은 actor, timestamp, before value, after value, changed path, version metadata를 포함해야 한다.

가장 중요한 설계 원칙은 다음과 같다.

- Source of truth는 `latest snapshot + append-only event log`의 hybrid 구조로 둔다.
- 저장 가능한 canonical change unit은 text diff가 아니라 JSON path-level operation이다.
- Main 상태에는 syntax-invalid JSON을 절대 저장하지 않는다.
- Schema-invalid JSON은 draft에는 제한적으로 허용할 수 있으나 main 적용은 막는다.
- Rollback은 과거 history를 삭제하지 않고 새로운 rollback event로 기록한다.
- 실시간 협업은 처음부터 문자 단위 editor 동기화가 아니라 JSON path-level operation 동기화를 우선한다.

---

## 1. Product and Technical Scope

### 1.1 Product Definition

이 서비스는 팀이 여러 JSON 파일로 구성된 데이터베이스를 하나의 공유 공간에서 관리하도록 돕는다. 사용자는 workspace와 project를 만들고, project 안에 folder와 JSON document를 생성할 수 있다. 여러 사용자는 같은 JSON document를 열어 수정할 수 있으며, 변경사항은 실시간 또는 준실시간으로 다른 사용자에게 반영된다.

서비스는 다음 질문에 즉시 답할 수 있어야 한다.

- 누가 이 값을 고쳤는가?
- 언제 고쳤는가?
- 어떤 JSON path가 바뀌었는가?
- 이전 값은 무엇이었고 현재 값은 무엇인가?
- 변경 이유나 관련 comment가 있는가?
- 이 변경은 schema validation을 통과했는가?
- 문제가 생기면 어떤 version으로 되돌릴 수 있는가?

### 1.2 Goals

- Workspace / Project / Folder / JSON Document 구조를 제공한다.
- 여러 JSON document를 하나의 project 안에서 관리한다.
- JSON document를 code editor, tree editor, form editor로 수정할 수 있게 한다.
- 모든 변경을 JSON path 단위로 추적한다.
- JSON Schema 기반 validation을 제공한다.
- 특정 JSON path에 comment thread를 생성할 수 있게 한다.
- 특정 version 간 diff와 rollback을 제공한다.
- 역할 기반 권한 관리를 제공한다.
- 실시간 협업과 presence를 제공한다.
- 향후 review request, branch, release tag, Git import/export를 확장할 수 있게 설계한다.

### 1.3 Non-goals

- 일반 문서 편집기 대체가 아니다.
- SQL database 전체 기능 대체가 아니다.
- spreadsheet 전체 기능 대체가 아니다.
- GitHub의 모든 기능 복제가 아니다.
- 대용량 binary file storage 제공이 아니다.
- 초기에 완전한 offline-first 협업을 필수 기능으로 두지 않는다.
- 초기에 복잡한 distributed merge engine을 직접 구현하지 않는다.

---

## 2. Normative Language

본 문서의 요구사항은 다음 의미로 해석한다.

| Term | Meaning |
|---|---|
| MUST | 구현에서 반드시 만족해야 하는 요구사항 |
| SHOULD | 강하게 권장되며, 제외하려면 명확한 이유가 필요한 요구사항 |
| MAY | 선택적으로 구현 가능한 요구사항 |
| MUST NOT | 구현에서 허용하면 안 되는 사항 |

---

## 3. Core Technical Decisions

| Area | Decision | Rationale |
|---|---|---|
| Source of truth | Latest snapshot + append-only event log | 빠른 조회와 완전한 감사 추적을 동시에 만족 |
| Persisted change unit | JSON path-level operation | field-level blame, diff, rollback, comment 연결에 적합 |
| Path format | JSON Pointer-compatible path | 표준화된 JSON 내부 위치 표현에 적합 |
| Patch format | JSON Patch-like event | add/remove/replace/move/copy/test 구조 확장 가능 |
| Latest storage | PostgreSQL JSONB | 최신 snapshot 조회와 indexing에 유리 |
| Collaboration | WebSocket + path-level patch broadcast | MVP에서 복잡도를 낮추면서 실시간 반영 가능 |
| Validation | Syntax + Schema + Custom rule + Review gate | 데이터 오염 방지 |
| Deletion | Soft delete by default | 감사 로그와 복구 가능성 보존 |
| Rollback | New event, not history deletion | 변경 이력의 불변성 보존 |
| Git integration | Import/export first, not primary backend | 실시간 협업과 field-level audit에는 event model이 더 적합 |

---

## 4. High-level Architecture

### 4.1 Architecture Overview

```text
[Browser Client]
   ├── JSON Code Editor
   ├── JSON Tree Editor
   ├── Schema-based Form Editor
   ├── Comment Sidebar
   ├── History / Diff Viewer
   └── Presence Indicator
          │
          │ REST + WebSocket
          ▼
[Backend Application]
   ├── Auth Service
   ├── Permission Service
   ├── Workspace / Project Service
   ├── Document Service
   ├── Event Log Service
   ├── Validation Service
   ├── Comment / Review Service
   ├── Realtime Collaboration Service
   └── Export / Backup Service
          │
          ▼
[Storage]
   ├── PostgreSQL: JSONB latest snapshots
   ├── PostgreSQL: append-only event logs
   ├── PostgreSQL: schemas, comments, reviews, permissions
   ├── Redis: session, presence, transient collaboration state
   └── Object Storage: export, backup, archive
```

### 4.2 Suggested Initial Tech Stack

| Layer | Recommended Stack |
|---|---|
| Frontend | Next.js, React, Monaco Editor, custom JSON tree editor |
| Backend | NestJS or FastAPI |
| Realtime | WebSocket; optional Yjs for editor session layer |
| Database | PostgreSQL with JSONB |
| Cache / Presence | Redis |
| Validation | JSON Schema validator + custom rule engine |
| Auth | Managed auth provider or JWT-based internal auth |
| Deployment | Docker, PostgreSQL, Redis, reverse proxy |

### 4.3 Architecture Principle

Raw JSON text MUST NOT be the only source of truth. Text editing is a user interface concern. The canonical persisted state SHOULD be a structured JSON object, and the canonical persisted change SHOULD be a JSON path-level operation.

This distinction matters because raw text can be temporarily invalid during editing. For example, a user can type `{ "age": }`, which is not valid JSON. Such intermediate text states MAY exist locally in the editor, but MUST NOT be persisted as the latest document snapshot.

---

## 5. Domain Model

### 5.1 Core Entities

| Entity | Description |
|---|---|
| User | 서비스 사용자 |
| Workspace | 여러 project를 포함하는 최상위 협업 공간 |
| Project | GitHub repository와 유사한 JSON DB 관리 단위 |
| Folder | project 내부의 가상 디렉토리 |
| JsonDocument | 하나의 JSON 파일 또는 JSON 문서 |
| DocumentSnapshot | 특정 version의 전체 JSON 상태 |
| DocumentEvent | 특정 version에서 다음 version으로 넘어가는 변경 이벤트 |
| Schema | JSON document를 검증하기 위한 schema |
| CommentThread | file-level 또는 path-level comment 묶음 |
| ReviewRequest | 변경사항을 승인 또는 수정 요청하는 리뷰 단위 |
| PermissionPolicy | 사용자/역할/경로 기반 접근 정책 |

### 5.2 Entity Hierarchy

```text
Workspace
 └── Project
      ├── Folder
      │    ├── JsonDocument
      │    └── JsonDocument
      ├── Schema Registry
      ├── Comment Threads
      ├── Review Requests
      ├── Activity Log
      ├── Release Tags
      └── Members / Permissions
```

### 5.3 Naming Rules

- `JsonDocument`는 사용자가 보는 JSON 파일 단위이다.
- `DocumentEvent`는 JSON document의 version을 증가시키는 단일 변경 이벤트이다.
- `DocumentSnapshot`은 특정 version의 전체 JSON materialized state이다.
- `Patch`는 하나 이상의 JSON path-level operation으로 구성된다.
- `Changed path`는 변경의 영향을 받은 JSON Pointer-compatible path이다.

---

## 6. Data Model

### 6.1 Database Overview

초기 구현에서는 PostgreSQL을 primary database로 사용한다. 최신 JSON 상태는 `documents.current_snapshot_jsonb`에 저장하고, 변경 이력은 `document_events`에 append-only 방식으로 저장한다.

### 6.2 Tables

```sql
users
- id UUID PRIMARY KEY
- email TEXT UNIQUE NOT NULL
- display_name TEXT NOT NULL
- created_at TIMESTAMP NOT NULL
- updated_at TIMESTAMP NOT NULL

workspaces
- id UUID PRIMARY KEY
- name TEXT NOT NULL
- owner_id UUID REFERENCES users(id)
- created_at TIMESTAMP NOT NULL
- updated_at TIMESTAMP NOT NULL

projects
- id UUID PRIMARY KEY
- workspace_id UUID REFERENCES workspaces(id)
- name TEXT NOT NULL
- description TEXT
- default_branch TEXT DEFAULT 'main'
- created_at TIMESTAMP NOT NULL
- updated_at TIMESTAMP NOT NULL

documents
- id UUID PRIMARY KEY
- project_id UUID REFERENCES projects(id)
- folder_path TEXT NOT NULL
- file_name TEXT NOT NULL
- full_path TEXT NOT NULL
- current_version INTEGER NOT NULL
- current_snapshot_jsonb JSONB NOT NULL
- schema_id UUID NULL
- is_deleted BOOLEAN DEFAULT FALSE
- created_by UUID REFERENCES users(id)
- created_at TIMESTAMP NOT NULL
- updated_at TIMESTAMP NOT NULL
```

```sql
document_events
- id UUID PRIMARY KEY
- document_id UUID REFERENCES documents(id)
- actor_id UUID REFERENCES users(id)
- event_type TEXT NOT NULL
- base_version INTEGER NOT NULL
- result_version INTEGER NOT NULL
- patch_jsonb JSONB NOT NULL
- inverse_patch_jsonb JSONB NULL
- changed_paths_jsonb JSONB NOT NULL
- summary TEXT
- reason TEXT
- created_at TIMESTAMP NOT NULL

schemas
- id UUID PRIMARY KEY
- project_id UUID REFERENCES projects(id)
- name TEXT NOT NULL
- schema_jsonb JSONB NOT NULL
- file_pattern TEXT NULL
- version INTEGER NOT NULL
- created_by UUID REFERENCES users(id)
- created_at TIMESTAMP NOT NULL

comment_threads
- id UUID PRIMARY KEY
- document_id UUID REFERENCES documents(id)
- json_pointer_path TEXT NULL
- status TEXT NOT NULL
- created_by UUID REFERENCES users(id)
- created_at TIMESTAMP NOT NULL
- resolved_at TIMESTAMP NULL

comments
- id UUID PRIMARY KEY
- thread_id UUID REFERENCES comment_threads(id)
- author_id UUID REFERENCES users(id)
- body TEXT NOT NULL
- created_at TIMESTAMP NOT NULL
- updated_at TIMESTAMP NOT NULL
```

```sql
review_requests
- id UUID PRIMARY KEY
- project_id UUID REFERENCES projects(id)
- title TEXT NOT NULL
- description TEXT
- author_id UUID REFERENCES users(id)
- status TEXT NOT NULL
- created_at TIMESTAMP NOT NULL
- applied_at TIMESTAMP NULL

review_request_changes
- id UUID PRIMARY KEY
- review_request_id UUID REFERENCES review_requests(id)
- document_id UUID REFERENCES documents(id)
- from_version INTEGER NOT NULL
- to_version INTEGER NOT NULL

permissions
- id UUID PRIMARY KEY
- workspace_id UUID REFERENCES workspaces(id)
- project_id UUID NULL REFERENCES projects(id)
- subject_type TEXT NOT NULL
- subject_id UUID NOT NULL
- role TEXT NOT NULL
- path_scope TEXT NULL
- created_at TIMESTAMP NOT NULL
```

### 6.3 Data Integrity Invariants

The system MUST satisfy the following invariants.

- `documents.current_version` MUST equal the latest `document_events.result_version` for the same document.
- Replaying all accepted document events from the initial snapshot MUST reconstruct the latest snapshot exactly.
- Every accepted mutation MUST be stored in `document_events` before or within the same transaction as snapshot update.
- Rollback MUST create a new event and MUST NOT delete prior events.
- Soft-deleted documents MUST retain event history.
- `full_path` MUST be unique within a project among non-deleted documents.

---

## 7. JSON Document Lifecycle

### 7.1 Create Document

1. User requests document creation.
2. System checks project permission.
3. System checks path uniqueness.
4. System validates JSON syntax.
5. System binds matching schema if available.
6. System validates against schema if required.
7. System creates `documents` row with version `1`.
8. System creates initial `document_events` row.
9. System broadcasts document creation event to project members.

### 7.2 Edit Document

1. Client loads latest snapshot and current version.
2. User edits through code, tree, or form editor.
3. Client generates candidate patch.
4. Client sends patch with `base_version`.
5. Server checks permission.
6. Server checks version compatibility.
7. Server applies patch to latest snapshot.
8. Server runs validation policy.
9. Server writes document event.
10. Server updates latest snapshot and current version.
11. Server broadcasts accepted patch to active clients.

### 7.3 Delete Document

Deletion SHOULD be soft delete by default.

1. User requests deletion.
2. System checks permission.
3. System records deletion event.
4. System sets `documents.is_deleted = true`.
5. System preserves event history.

### 7.4 Restore Document

1. User requests restore.
2. System checks admin or owner permission.
3. System records restore event.
4. System sets `is_deleted = false` if path conflict does not exist.
5. If path conflict exists, user MUST choose a new path.

---

## 8. Versioning and Change Tracking

### 8.1 Version Model

- Each `JsonDocument` has a monotonically increasing integer version.
- Initial version is `1`.
- Every accepted mutation increments the version by one.
- Version numbers are document-scoped, not project-scoped.
- Review request MAY group changes across multiple documents, but each document keeps its own version sequence.

### 8.2 Change Event Format

Each accepted change MUST include the following fields.

| Field | Required | Description |
|---|---:|---|
| event_id | Yes | unique event identifier |
| document_id | Yes | target document |
| actor_id | Yes | user who made the change |
| event_type | Yes | create, update, delete, restore, rollback, conflict_resolution |
| base_version | Yes | version before patch |
| result_version | Yes | version after patch |
| patch | Yes | JSON path-level operation list |
| inverse_patch | Strongly recommended | operation list for undo/rollback |
| changed_paths | Yes | affected JSON paths |
| timestamp | Yes | event creation time |
| summary | Optional | human-readable summary |
| reason | Optional | change reason |

Example:

```json
{
  "event_id": "evt_001",
  "document_id": "doc_001",
  "actor_id": "user_min",
  "event_type": "update",
  "base_version": 12,
  "result_version": 13,
  "timestamp": "2026-06-24T08:30:00Z",
  "patch": [
    {
      "op": "replace",
      "path": "/cohorts/ADNI/qc_pass",
      "value": true
    }
  ],
  "inverse_patch": [
    {
      "op": "replace",
      "path": "/cohorts/ADNI/qc_pass",
      "value": false
    }
  ],
  "changed_paths": ["/cohorts/ADNI/qc_pass"],
  "summary": "Updated ADNI QC status",
  "reason": "Manual QC review completed"
}
```

### 8.3 Blame

The system SHOULD support field-level blame.

For a selected JSON path, the system SHOULD return:

- latest modifying actor
- latest modifying timestamp
- previous value
- current value
- event id
- related comment threads
- related review request if applicable

### 8.4 Rollback

Rollback MUST create a new event.

Rollback MUST NOT rewrite or delete previous history.

Example rollback event:

```json
{
  "event_type": "rollback",
  "document_id": "doc_001",
  "actor_id": "user_001",
  "from_version": 24,
  "rollback_target_version": 18,
  "result_version": 25,
  "reason": "Reverting invalid label update"
}
```

---

## 9. Collaboration Model

### 9.1 Recommended Model

The canonical persisted state is a structured JSON object. The canonical persisted change unit is a JSON path-level operation.

Code editor collaboration MAY use a temporary text-level collaboration layer, but persisted changes MUST be converted into valid JSON patch events before being accepted into document history.

Tree editor and form editor SHOULD directly generate path-level operations.

### 9.2 Realtime Flow

```text
Client A edits /model/learning_rate
        │
        ▼
Client A sends document.patch.propose with base_version
        │
        ▼
Server checks permission, version, validation
        │
        ▼
Server writes event + updates latest snapshot
        │
        ▼
Server broadcasts document.patch.accepted
        │
        ▼
Client B applies accepted patch to local state
```

### 9.3 Conflict Policy

| Situation | Policy |
|---|---|
| Different JSON paths edited concurrently | Auto-merge SHOULD be allowed |
| Different keys under same object edited concurrently | Auto-merge SHOULD be allowed |
| Same scalar path edited concurrently | Create semantic conflict warning |
| Array insert/delete/reorder conflict | Review-required state SHOULD be created |
| Patch based on stale version | Server SHOULD reject or transform depending on operation safety |
| Invalid JSON result | MUST reject for main/latest snapshot |
| Schema-invalid result | MUST block main apply; MAY allow draft save |

### 9.4 Array Policy

Arrays are index-sensitive and can create unstable patches when multiple users insert, delete, or reorder items concurrently.

For identity-based records, object maps SHOULD be used instead of arrays.

Recommended:

```json
{
  "patients": {
    "P001": { "age": 72 },
    "P002": { "age": 65 }
  }
}
```

Not recommended:

```json
{
  "patients": [
    { "id": "P001", "age": 72 },
    { "id": "P002", "age": 65 }
  ]
}
```

---

## 10. Validation Model

### 10.1 Validation Levels

| Level | Name | Description |
|---|---|---|
| 1 | Syntax validation | JSON 문법 유효성 확인 |
| 2 | Schema validation | JSON Schema 기반 type, required, enum, format, range 확인 |
| 3 | Custom rule validation | project-specific rule, cross-file reference, duplicate ID 등 확인 |
| 4 | Review gate | 특정 path 또는 schema 변경 시 reviewer approval 요구 |

### 10.2 Validation Result Format

```json
{
  "valid": false,
  "errors": [
    {
      "level": "schema",
      "severity": "error",
      "path": "/patients/P001/age",
      "message": "Expected number but received string",
      "expected": "number",
      "actual": "string"
    }
  ],
  "warnings": [
    {
      "level": "custom",
      "severity": "warning",
      "path": "/metadata/source",
      "message": "Source field is recommended for auditability"
    }
  ]
}
```

### 10.3 Validation Gate Policy

- Syntax-invalid JSON MUST NOT be persisted as latest snapshot.
- Schema-invalid JSON MAY be saved as draft if project setting allows it.
- Schema-invalid JSON MUST NOT be applied to main.
- Custom validation warning SHOULD NOT block save by default.
- Custom validation error SHOULD block main apply.
- Review-required paths MUST NOT be applied without approval.

### 10.4 Schema Binding

Schema can be bound at the following levels.

- Project default schema
- Folder-level schema
- File pattern schema, e.g. `schemas/*.json`, `cohorts/*.json`
- Document-specific schema override

Binding priority SHOULD be:

```text
Document-specific schema > File pattern schema > Folder-level schema > Project default schema
```

---

## 11. Comment and Review Model

### 11.1 Comment Types

| Type | Scope | Example |
|---|---|---|
| File-level comment | entire document | “이 파일은 최신 protocol 기준인지 확인 필요” |
| Path-level comment | specific JSON path | `/model/learning_rate`에 대한 논의 |
| Change-level comment | specific event or diff | version 12 → 13 변경에 대한 리뷰 |

### 11.2 Comment Thread States

- `open`
- `resolved`
- `reopened`

Example:

```json
{
  "thread_id": "thread_001",
  "document_id": "doc_001",
  "json_pointer_path": "/model/learning_rate",
  "status": "open",
  "comments": [
    {
      "comment_id": "comment_001",
      "author_id": "user_001",
      "body": "이 learning rate가 최신 실험 기준인지 확인 필요합니다.",
      "created_at": "2026-06-24T08:40:00Z"
    }
  ]
}
```

### 11.3 Review Request States

- `draft`
- `open`
- `approved`
- `changes_requested`
- `applied`
- `closed`

### 11.4 Review Decisions

Reviewers can submit:

- `approve`
- `request_changes`
- `comment_only`

MVP에서는 full branch/merge workflow를 바로 구현하지 않는다. 우선 “변경 묶음에 대한 review request”로 시작하고, 이후 branch와 release tag를 확장한다.

---

## 12. Permission and Security Model

### 12.1 Roles

| Role | Capabilities |
|---|---|
| Owner | workspace 삭제, billing/settings, 모든 권한 |
| Admin | project 관리, member 관리, schema 관리 |
| Editor | JSON document 생성/수정, comment 작성, review request 생성 |
| Reviewer | review decision 제출, comment 작성 |
| Viewer | 읽기 전용 |

### 12.2 Permission Requirements

- All API requests MUST be authenticated unless explicitly public.
- All document mutations MUST pass permission checks.
- All mutation attempts SHOULD be audit-logged, including rejected attempts for sensitive projects.
- Export operations SHOULD require Admin or Owner role.
- Schema changes SHOULD require Admin or designated schema owner role.
- Future implementation SHOULD support path-level permission.

Example future path-level rule:

```json
{
  "role": "clinical_data_manager",
  "path_scope": "/clinical_labels",
  "permissions": ["read", "write", "review"]
}
```

### 12.3 Security Requirements

- Passwords MUST NOT be stored in plaintext.
- API tokens MUST be scoped by workspace/project.
- Session tokens SHOULD be short-lived with refresh token flow.
- Sensitive audit logs SHOULD be immutable or tamper-evident.
- Soft deletion SHOULD be default for collaborative data.
- Production database backups MUST be encrypted.

---

## 13. REST API Specification

### 13.1 Workspace API

| Method | Endpoint | Description |
|---|---|---|
| POST | `/workspaces` | Create workspace |
| GET | `/workspaces` | List user workspaces |
| GET | `/workspaces/:workspace_id` | Get workspace detail |
| PATCH | `/workspaces/:workspace_id` | Update workspace |
| DELETE | `/workspaces/:workspace_id` | Soft delete workspace |

### 13.2 Project API

| Method | Endpoint | Description |
|---|---|---|
| POST | `/workspaces/:workspace_id/projects` | Create project |
| GET | `/workspaces/:workspace_id/projects` | List projects |
| GET | `/projects/:project_id` | Get project detail |
| PATCH | `/projects/:project_id` | Update project |
| DELETE | `/projects/:project_id` | Soft delete project |

### 13.3 Document API

| Method | Endpoint | Description |
|---|---|---|
| POST | `/projects/:project_id/documents` | Create JSON document |
| GET | `/documents/:document_id` | Get latest document snapshot |
| PATCH | `/documents/:document_id` | Apply patch to document |
| DELETE | `/documents/:document_id` | Soft delete document |

Patch request:

```json
{
  "base_version": 12,
  "patch": [
    {
      "op": "replace",
      "path": "/cohorts/ADNI/qc_pass",
      "value": true
    }
  ],
  "reason": "QC review completed"
}
```

Patch response:

```json
{
  "document_id": "doc_001",
  "previous_version": 12,
  "current_version": 13,
  "changed_paths": ["/cohorts/ADNI/qc_pass"],
  "validation": {
    "valid": true,
    "errors": [],
    "warnings": []
  }
}
```

### 13.4 History API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/documents/:document_id/history` | List document events |
| GET | `/documents/:document_id/history/:version` | Get snapshot or event for version |
| GET | `/documents/:document_id/diff?from=10&to=15` | Compare versions |
| POST | `/documents/:document_id/rollback` | Roll back to previous version as new event |

### 13.5 Schema API

| Method | Endpoint | Description |
|---|---|---|
| POST | `/projects/:project_id/schemas` | Create schema |
| GET | `/projects/:project_id/schemas` | List schemas |
| PATCH | `/schemas/:schema_id` | Update schema |
| DELETE | `/schemas/:schema_id` | Delete or deactivate schema |

### 13.6 Comment API

| Method | Endpoint | Description |
|---|---|---|
| POST | `/documents/:document_id/comments` | Create comment thread or comment |
| GET | `/documents/:document_id/comments` | List comments |
| PATCH | `/comments/:comment_id` | Update comment |
| POST | `/comments/:comment_id/resolve` | Resolve thread |
| POST | `/comments/:comment_id/reopen` | Reopen thread |

### 13.7 Review API

| Method | Endpoint | Description |
|---|---|---|
| POST | `/review-requests` | Create review request |
| GET | `/review-requests/:id` | Get review request |
| POST | `/review-requests/:id/approve` | Approve |
| POST | `/review-requests/:id/request-changes` | Request changes |
| POST | `/review-requests/:id/apply` | Apply reviewed changes |

---

## 14. WebSocket Event Specification

### 14.1 Endpoint

```text
WS /realtime/documents/:document_id
```

### 14.2 Event Types

| Event | Direction | Description |
|---|---|---|
| `presence.join` | client → server / server → clients | User joined document session |
| `presence.leave` | server → clients | User left document session |
| `presence.update_path` | client → server / server → clients | User is editing or viewing a path |
| `document.patch.propose` | client → server | Client proposes patch |
| `document.patch.accepted` | server → clients | Server accepted patch |
| `document.patch.rejected` | server → client | Server rejected patch |
| `document.version.updated` | server → clients | Document version changed |
| `document.validation.updated` | server → clients | Validation result changed |
| `comment.created` | server → clients | New comment created |
| `comment.resolved` | server → clients | Comment thread resolved |
| `review.status.updated` | server → clients | Review status changed |

### 14.3 Patch Propose Event

```json
{
  "type": "document.patch.propose",
  "document_id": "doc_001",
  "client_id": "client_abc",
  "base_version": 12,
  "patch": [
    {
      "op": "replace",
      "path": "/model/learning_rate",
      "value": 0.0001
    }
  ]
}
```

### 14.4 Patch Accepted Event

```json
{
  "type": "document.patch.accepted",
  "document_id": "doc_001",
  "event_id": "evt_001",
  "base_version": 12,
  "result_version": 13,
  "actor_id": "user_001",
  "patch": [
    {
      "op": "replace",
      "path": "/model/learning_rate",
      "value": 0.0001
    }
  ],
  "timestamp": "2026-06-24T08:50:00Z"
}
```

### 14.5 Patch Rejected Event

```json
{
  "type": "document.patch.rejected",
  "document_id": "doc_001",
  "reason": "VALIDATION_ERROR",
  "errors": [
    {
      "path": "/model/learning_rate",
      "message": "Expected number between 0 and 1"
    }
  ]
}
```

---

## 15. Error Handling

### 15.1 Standard Error Response

```json
{
  "error": {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Document failed schema validation.",
    "details": {
      "errors": [
        {
          "path": "/age",
          "message": "Expected number but received string"
        }
      ]
    }
  }
}
```

### 15.2 Error Codes

| Code | Meaning |
|---|---|
| `AUTH_REQUIRED` | Authentication required |
| `PERMISSION_DENIED` | User lacks permission |
| `WORKSPACE_NOT_FOUND` | Workspace not found |
| `PROJECT_NOT_FOUND` | Project not found |
| `DOCUMENT_NOT_FOUND` | Document not found |
| `INVALID_JSON_SYNTAX` | JSON syntax invalid |
| `SCHEMA_VALIDATION_FAILED` | Schema validation failed |
| `CUSTOM_VALIDATION_FAILED` | Custom rule validation failed |
| `VERSION_CONFLICT` | Client base version is stale |
| `PATH_NOT_FOUND` | JSON path does not exist |
| `PATCH_APPLY_FAILED` | Patch could not be applied |
| `REVIEW_REQUIRED` | Review gate blocks apply |
| `RATE_LIMITED` | Request rate limit exceeded |
| `INTERNAL_ERROR` | Unexpected server error |

---

## 16. Search, Diff, and Rollback

### 16.1 Search

The system SHOULD support:

- file name search
- full path search
- JSON key search
- JSON value search
- changed path search
- actor search
- comment text search
- review request search

### 16.2 Diff

The system SHOULD support:

- file-level diff
- path-level diff
- version-to-version diff
- review request diff
- schema change diff

Diff output SHOULD include:

- changed path
- operation type
- before value
- after value
- actor
- timestamp
- related event id

### 16.3 Rollback

Rollback can be implemented in two ways.

| Strategy | Description | Recommendation |
|---|---|---|
| Snapshot-based rollback | Load target version snapshot and replace latest state | Good for whole-document rollback |
| Inverse patch rollback | Apply inverse patches from later versions | Good for change-level undo |

MVP SHOULD implement snapshot-based rollback first. Inverse patch rollback SHOULD be added for field-level undo later.

---

## 17. Storage, Backup, and Retention

### 17.1 Storage Policy

- Latest document state MUST be stored as JSONB snapshot.
- Every accepted mutation MUST be stored as append-only event.
- Periodic compacted snapshots SHOULD be generated.
- Deleted documents SHOULD be soft-deleted by default.
- Physical deletion SHOULD require admin action and retention policy check.

### 17.2 Snapshot Compaction

To avoid reconstructing large documents from version 1, the system SHOULD store compacted snapshots every 100 accepted changes or every 24 hours, whichever comes first.

### 17.3 Backup

- Production database backup MUST run at least daily.
- Event logs MUST be included in backup.
- Restore procedure MUST be tested before production launch.
- Backup encryption SHOULD be enabled.
- Exported JSON archives SHOULD include metadata and event history when requested.

---

## 18. Performance Requirements

### 18.1 Initial MVP Limits

| Metric | Target |
|---|---:|
| Maximum JSON document size | 5 MB |
| Maximum files per project | 10,000 |
| Maximum concurrent users per document | 20 |
| Maximum workspace members | 100 |
| Document load p95 | < 500 ms for documents under 1 MB |
| Patch apply p95 | < 200 ms |
| WebSocket broadcast p95 | < 300 ms under normal load |

### 18.2 Performance Notes

- Very large JSON documents SHOULD be discouraged.
- Large object rendering SHOULD use virtualized tree rendering.
- Validation SHOULD be debounced on the client side.
- Expensive project-wide custom validation SHOULD run asynchronously.
- Search indexing MAY be moved to a dedicated search engine after MVP.

---

## 19. Testing Strategy

### 19.1 Unit Tests

- JSON path parser
- patch apply
- inverse patch generation
- diff generation
- schema validation
- custom validation
- permission check
- error response formatting

### 19.2 Integration Tests

- document create/edit/delete/restore
- event log creation
- snapshot update
- validation failure handling
- rollback
- review request apply
- comment creation and resolution

### 19.3 Realtime Tests

- two users editing different paths
- two users editing same scalar path
- array insert/delete conflict
- reconnect after temporary disconnect
- duplicate event prevention
- stale base version handling

### 19.4 Security Tests

- unauthenticated access
- viewer mutation attempt
- editor attempting admin action
- schema edit without permission
- export without permission
- project boundary violation

### 19.5 Data Integrity Tests

Critical invariant test:

```text
Replaying all accepted document events from the initial snapshot must reconstruct the latest snapshot exactly.
```

Additional checks:

- rollback preserves previous history
- deleted document can be restored by admin
- event log and latest snapshot remain consistent under concurrent writes
- schema migration does not corrupt existing documents

---

## 20. Deployment Architecture

### 20.1 Environments

- local
- development
- staging
- production

### 20.2 Services

```text
[frontend]
[backend-api]
[websocket-server]
[worker]
[postgresql]
[redis]
[object-storage]
```

### 20.3 CI/CD Pipeline

The pipeline SHOULD include:

- lint
- type check
- unit tests
- integration tests
- database migration check
- build
- deploy to staging
- smoke test
- manual approval for production

### 20.4 Initial Deployment Recommendation

MVP SHOULD start as a modular monolith, not microservices.

Recommended initial deployment:

```text
Next.js frontend
Backend API + WebSocket in one application boundary
PostgreSQL
Redis
Background worker
```

Split API, realtime, and workers only after product behavior stabilizes.

---

## 21. Observability and Audit

### 21.1 Application Logs

The system SHOULD log:

- API request id
- user id
- workspace/project/document id
- mutation attempt
- validation failure
- permission denial
- patch apply failure
- WebSocket connection lifecycle

### 21.2 Audit Log

The audit log MUST include accepted mutations. For sensitive projects, rejected mutation attempts SHOULD also be recorded.

Audit fields:

- actor
- action
- target resource
- timestamp
- request id
- before/after when applicable
- result status
- error code if rejected

### 21.3 Metrics

Recommended metrics:

- document load latency
- patch apply latency
- validation latency
- WebSocket connection count
- patch rejection rate
- schema validation failure rate
- rollback count
- review request approval time

---

## 22. MVP Milestones

### Milestone 1 — Basic JSON Workspace

- user auth
- workspace/project creation
- folder tree
- JSON document create/read/update/delete
- raw JSON editor
- syntax validation
- latest snapshot storage

### Milestone 2 — Versioning and History

- document versioning
- append-only event log
- before/after tracking
- path-level history
- version-to-version diff
- rollback

### Milestone 3 — Schema Validation and Comments

- schema registry
- file-pattern schema binding
- validation result UI
- validation gate
- file-level comments
- path-level comments
- resolve/reopen thread

### Milestone 4 — Realtime Collaboration

- WebSocket document session
- presence
- path-level editing indicator
- real-time patch broadcast
- conflict warning
- reconnect handling

### Milestone 5 — Review Workflow

- review request
- approve
- request changes
- apply to main
- review history
- review-required path policy

### Milestone 6 — Advanced Platform Features

- branch/draft workflow
- release tags
- Git import/export
- API tokens
- webhooks
- audit export
- path-level permissions

---

## 23. Open Decisions

Before implementation, the team should resolve the following.

| Decision | Options | Recommended Initial Choice |
|---|---|---|
| Realtime engine | Yjs, Automerge, custom patch sync, hybrid | Custom path-level patch sync first; optional Yjs later |
| Draft support | no draft, draft only, branch model | Draft support after basic event model |
| Invalid JSON handling | block always, allow local only, allow draft | Local only for MVP; draft later |
| Review workflow | MVP, phase 2, phase 3 | After versioning + comments |
| Git integration | primary backend, import/export, none | Import/export only |
| Array conflict UX | reject, warn, review-required | Review-required |
| Path-level permission | MVP, later | Later, but schema must allow extension |

---

## 24. Major Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Raw text collaboration creates invalid JSON states | High | Persist only validated structured JSON changes |
| Array index operations create semantic conflicts | High | Recommend object maps; review-required for reorder conflict |
| Event log and snapshot diverge | Critical | Transactional writes + replay consistency tests |
| Large JSON rendering is slow | Medium | Virtualized tree rendering + document size limits |
| Validation becomes too slow | Medium | Debounce client validation + async custom validation |
| Permission model becomes too complex | Medium | Start with RBAC; design path_scope for future |
| Git backend temptation increases complexity | Medium | Treat Git as export/import integration, not source of truth |

---

## 25. Developer Handoff Checklist

Before development starts, confirm the following.

- [ ] Product scope and non-goals are approved.
- [ ] Source of truth decision is approved.
- [ ] Document event format is approved.
- [ ] JSON path format is approved.
- [ ] Data model is reviewed.
- [ ] Patch apply + validation transaction policy is approved.
- [ ] Error code contract is approved.
- [ ] MVP limits are approved.
- [ ] Security model is reviewed.
- [ ] Test invariant for event replay is added to CI plan.
- [ ] Milestone order is accepted.

---

## 26. Implementation Recommendation

Do not start with real-time editor complexity. Start with the durable core.

Recommended build order:

1. Document CRUD with latest JSONB snapshot.
2. Patch-based update endpoint.
3. Append-only event log.
4. Version diff and rollback.
5. JSON Schema validation.
6. Path-level comment.
7. WebSocket patch broadcast.
8. Review request.
9. Branch/release/Git integration.

The strongest product foundation is not the editor. The strongest foundation is the invariant that every accepted JSON change is valid, attributable, replayable, reviewable, and reversible.

---

## 27. Reference Standards and Candidate Technologies

This section lists standards and candidate technologies for engineering discussion. Final selection should be validated during implementation spike.

- JSON Pointer-compatible path representation
- JSON Patch-compatible operation representation
- JSON Schema-based validation
- PostgreSQL JSONB for latest snapshot storage
- WebSocket for realtime collaboration
- Yjs or Automerge as optional collaboration-layer candidates
- Monaco Editor for raw JSON editing
- Redis for presence and transient collaboration state

---

## 28. Final Design Statement

The system should be designed around the following statement.

> JSON을 문서처럼 함께 수정하되, 데이터베이스처럼 검증하고, GitHub처럼 추적·리뷰·복구한다.

Technically, this means:

> The core persisted unit is not a whole JSON file overwrite. The core persisted unit is a validated, attributable, replayable JSON path-level change event.
