---
title: "OpenJson Product Design Doc"
subtitle: "감사 가능한 Collaborative JSON DB Workspace"
status: "Design Baseline"
version: "0.3"
last_updated: "2026-06-27"
---

# OpenJson Product Design Doc

## 0. 문서 목적

OpenJson은 JSON 기반 구조화 데이터를 팀이 안전하게 관리하기 위한 협업형 데이터 워크스페이스다. 단순 JSON 파일 저장소가 아니다. 핵심은 JSON을 저장하는 것이 아니라, **검증 가능하고 감사 가능한 JSON 변경 이력 시스템**을 만드는 것이다.

제품의 중심 문장은 다음이다.

> 모든 JSON 변경은 누가, 언제, 무엇을, 왜 바꿨는지 설명 가능해야 하며, 전체 이벤트를 replay했을 때 최신 snapshot과 정확히 일치해야 한다.

최신 JSON snapshot은 빠른 조회용이다. 진짜 신뢰의 근거는 append-only `DocumentEvent`다.

---

## 1. 현재 구현 상태

| 영역 | 상태 | 설명 |
|---|---:|---|
| TASK_001 | 완료 | Versioned JSON document foundation |
| TASK_001_HARDENING | 완료 | replay, rollback, diff, transaction 신뢰성 보강 |
| TASK_002 | 완료 | JSON Schema validation + schema registry |
| TASK_002_HARDENING | 다음 gate | schema immutability, validation schema audit 기록, migration/negative smoke 보강 |
| Realtime collaboration | 미시작 | 아직 시작하면 안 됨 |
| Path-level comments | 미시작 | permission hardening 이후 권장 |
| Review workflow | 미시작 | comments + permission 이후 권장 |
| UI | 미시작 | backend integrity gate 이후 권장 |
| Deployment | 미시작 | PostgreSQL, auth, migration, observability 이후 가능 |

현재 단계는 backend foundation 단계다. 다음에 바로 realtime을 붙이는 것은 잘못된 순서다. 먼저 auditability와 permission boundary를 잠가야 한다.

---

## 2. 제품 정의

OpenJson은 다음 문제를 해결한다.

```text
JSON 파일은 쉽게 만들 수 있지만,
팀 단위로 안전하게 고치고,
검증하고,
누가 왜 바꿨는지 추적하고,
필요하면 복구하는 것은 어렵다.
```

OpenJson은 이 문제를 다음 방식으로 푼다.

```text
Workspace / Project / Document 구조
+ JSON Schema validation
+ append-only DocumentEvent
+ path-level history
+ version-to-version diff
+ rollback as new event
+ future path-level comments
+ future review workflow
+ future realtime collaboration
```

따라서 제품 포지셔닝은 다음과 같다.

> GitHub처럼 추적하고, JSON Schema처럼 검증하고, Google Docs처럼 협업하되, 내부 원장은 append-only event log로 유지하는 JSON-native data workspace.

---

## 3. 제품 원칙

### 3.1 Audit first

모든 mutation은 반드시 이벤트로 남아야 한다. 나중에 설명할 수 없는 변경은 지금 받아들이면 안 된다.

### 3.2 Schema before speed

실시간 협업보다 먼저 schema validation이 안정적이어야 한다. 빠르게 잘못된 데이터를 퍼뜨리는 것은 기능이 아니라 장애다.

### 3.3 Snapshot is cache, event log is memory

최신 snapshot은 빠른 조회를 위한 캐시성 상태다. 변경 이력, blame, rollback, replay, audit의 근거는 event log다.

### 3.4 No silent mutation

actor 없는 mutation 금지. base_version 없는 mutation 금지. event 없는 snapshot 변경 금지. event 삭제를 통한 rollback 금지.

### 3.5 Field-level context beats file-level noise

사용자는 파일 전체 diff를 읽지 않고도 `/model/learning_rate` 같은 JSON Pointer path 기준으로 변경 맥락을 이해할 수 있어야 한다.

### 3.6 Boring infrastructure wins

처음부터 복잡한 마법을 만들지 않는다. 명확한 REST API, transaction boundary, deterministic error, replay invariant가 우선이다.

---

## 4. 핵심 시스템 invariant

OpenJson에서 절대 깨지면 안 되는 조건은 다음이다.

```text
Replay(DocumentEvent[0..N]) == json_documents.current_snapshot_json
```

이 조건은 아래 모든 기능 이후에도 유지되어야 한다.

- create
- patch
- soft delete
- rollback
- schema validation
- migration
- future comments
- future review workflow
- future realtime collaboration

이 invariant를 깨는 기능은 기능이 아니라 regression이다.

---

## 5. 핵심 객체 모델

| 객체 | 제품 의미 | 기술적 역할 |
|---|---|---|
| Workspace | 조직 또는 팀 단위 공간 | 최상위 협업 boundary |
| Project | repository와 유사한 데이터 공간 | documents, schemas, members, policies 포함 |
| JsonDocument | 하나의 JSON 문서 | latest snapshot과 current_version 보유 |
| DocumentEvent | 하나의 승인된 변경 | append-only audit event |
| Schema | JSON 구조 검증 정책 | 문서 구조/타입/값 제약 검증 |
| CommentThread | 향후 path-level 논의 | document/path/event에 anchor |
| ReviewRequest | 향후 변경 승인 프로세스 | proposed changes를 apply 전 검토 |
| PermissionPolicy | 향후 권한 정책 | project/path 단위 capability 제어 |

---

## 6. DocumentEvent 디자인

`DocumentEvent`는 OpenJson의 신뢰 단위다.

권장 event shape:

```json
{
  "id": "event_001",
  "document_id": "doc_001",
  "actor_id": "user_001",
  "event_type": "patch",
  "base_version": 2,
  "result_version": 3,
  "patch": [
    {
      "op": "replace",
      "path": "/learning_rate",
      "value": 0.0005
    }
  ],
  "inverse_patch": [
    {
      "op": "replace",
      "path": "/learning_rate",
      "value": 0.001
    }
  ],
  "changed_paths": ["/learning_rate"],
  "before_values": {"/learning_rate": 0.001},
  "after_values": {"/learning_rate": 0.0005},
  "validation_schema_id": "schema_001",
  "summary": "Updated learning rate",
  "reason": "New baseline model config",
  "created_at": "2026-06-27T12:00:00Z"
}
```

권장 event type:

| Event type | 의미 |
|---|---|
| create | 문서 최초 생성 |
| patch | 일반 JSON 변경 |
| delete | soft delete |
| rollback | 과거 version snapshot으로 복구하는 새 event |
| schema_bind | 향후 명시적 schema binding 변경 시 사용 가능 |
| schema_revalidate | 향후 audit-only validation event로 사용 가능 |

중요한 결정:

> schema-bound document의 create/patch/rollback event에는 어떤 schema로 검증되었는지 남겨야 한다.

따라서 `document_events.validation_schema_id`는 TASK_002_HARDENING에서 반드시 고려해야 하는 필드다.

---

## 7. JSON Schema 디자인

현재 정책은 다음과 같다.

| 항목 | 결정 |
|---|---|
| JSON Schema draft | Draft 2020-12 |
| Validator | `jsonschema.Draft202012Validator` |
| Schema 자체 검증 | `Draft202012Validator.check_schema` |
| Format validation | TASK_002에서는 강제하지 않음 |
| Schema row | immutable insert-only |
| Schema update API | 없음 |
| Schema deactivate API | 없음 |
| Binding 우선순위 | explicit `schema_id` 우선, 없으면 `file_pattern` |
| file_pattern engine | `fnmatch.fnmatch(full_path, pattern)` |
| multiple match | `AMBIGUOUS_SCHEMA_MATCH` |

Schema validation 실패 시 반드시 아래가 보장되어야 한다.

```text
event 없음
snapshot 변경 없음
version 증가 없음
```

이 원칙은 create, patch, rollback에 모두 적용된다.

---

## 8. 주요 사용자

### 8.1 Data maintainer

구조화 JSON 데이터를 직접 관리하는 사용자다.

필요한 것:

- JSON document 생성/수정
- schema validation 확인
- field-level history 확인
- rollback
- 변경 사유 기록

### 8.2 Developer

JSON 데이터를 애플리케이션, pipeline, API에서 소비하는 사용자다.

필요한 것:

- stable JSON shape
- schema-bound document
- predictable API error
- diff/version 정보
- API-first 접근

### 8.3 Reviewer

변경 적용 전 검토하는 사용자다. Review workflow 이후 중요해진다.

필요한 것:

- changed path 목록
- before/after values
- validation status
- comment/reason 확인
- approve/request changes

### 8.4 Admin

workspace, project, members, schema policy를 관리하는 사용자다.

필요한 것:

- project membership 관리
- role-based permission
- schema registry 관리
- audit export
- backup/restore 정책

---

## 9. 핵심 사용자 흐름

### 9.1 Schema-bound document 생성

```text
사용자가 project 선택
-> JSON document 생성
-> explicit schema_id 또는 file_pattern으로 schema binding
-> content root object/array 확인
-> schema validation
-> JsonDocument version 1 생성
-> create DocumentEvent 생성
-> response에 document_id, version, schema_id 반환
```

실패 시:

```text
schema validation 실패
-> document 생성 안 됨
-> event 생성 안 됨
-> SCHEMA_VALIDATION_FAILED 반환
-> error path는 JSON Pointer 형식
```

### 9.2 Document patch

```text
사용자가 특정 field 수정
-> client가 base_version과 patch 전송
-> server가 actor/document/base_version 확인
-> candidate snapshot 생성
-> schema-bound이면 schema validation
-> 통과 시 DocumentEvent insert + snapshot update
-> 둘은 같은 transaction
-> response에 result_version, changed_paths, schema_id 반환
```

실패 시:

```text
base_version 불일치
-> VERSION_CONFLICT
-> event 없음
-> snapshot 변경 없음
```

```text
schema validation 실패
-> SCHEMA_VALIDATION_FAILED
-> event 없음
-> snapshot 변경 없음
-> version 증가 없음
```

### 9.3 Rollback

```text
사용자가 target_version 지정
-> server가 target snapshot을 replay로 재구성
-> schema-bound이면 target snapshot validation
-> 통과 시 rollback event 생성
-> latest snapshot을 target 상태로 업데이트
-> 기존 event 삭제 없음
```

Rollback은 과거를 지우는 동작이 아니다. 과거 상태로 되돌리는 새 forward event다.

---

## 10. UX 방향

OpenJson의 UI는 일반 admin dashboard처럼 보이면 안 된다. 개발자 도구처럼 빠르고, 조밀하고, 명확해야 한다.

권장 layout:

```text
Top bar
- Workspace switcher
- Project switcher
- Global search
- Validation status
- User menu

Left rail
- Documents
- Schemas
- Activity
- Future: Reviews
- Future: Members

Main pane
- JSON editor
- Future: tree editor
- Future: schema-based form editor

Right inspector
- Validation
- History
- Diff
- Rollback
- Future: Comments
- Future: Review
```

문서 화면 예시:

```text
┌─────────────────────────────────────────────────────────────┐
│ project / config / model.json        v12   Schema: model@1.0 │
├───────────────┬────────────────────────────┬────────────────┤
│ File tree     │ JSON editor                │ Inspector      │
│               │                            │ - Validation   │
│ config/       │ {                          │ - Changed paths│
│ model.json    │   "model": "baseline",    │ - History      │
│ dataset.json  │   "learning_rate": 0.001  │ - Diff         │
│               │ }                          │ - Rollback     │
└───────────────┴────────────────────────────┴────────────────┘
```

### 10.1 UI tone

- 빠르다
- 조밀하다
- 불필요한 장식이 없다
- 상태가 명확하다
- error가 숨겨지지 않는다
- JSON path가 1급 객체처럼 보인다
- history와 validation이 항상 가까이에 있다

### 10.2 Status chip

| Status | 의미 |
|---|---|
| Valid | 현재 snapshot이 schema를 통과 |
| Unbound | schema가 연결되지 않음 |
| Conflict | version conflict 또는 semantic conflict |
| Deleted | soft-deleted document |
| Replayed | event replay와 latest snapshot 일치 |
| Invalid | schema validation 실패 상태 |

---

## 11. API 디자인 방향

API는 명시적이고 단순해야 한다.

현재 및 근미래 endpoint:

```text
POST   /projects/{project_id}/documents
GET    /documents/{document_id}
PATCH  /documents/{document_id}
DELETE /documents/{document_id}
GET    /documents/{document_id}/history
GET    /documents/{document_id}/diff
POST   /documents/{document_id}/rollback

POST   /projects/{project_id}/schemas
GET    /projects/{project_id}/schemas
GET    /schemas/{schema_id}
POST   /documents/{document_id}/validate
```

향후 endpoint group:

```text
Membership / RBAC
POST   /projects/{project_id}/members
GET    /projects/{project_id}/members
PATCH  /projects/{project_id}/members/{user_id}

Comments
POST   /documents/{document_id}/comments
GET    /documents/{document_id}/comments
POST   /comments/{comment_id}/resolve

Review
POST   /review-requests
GET    /review-requests/{id}
POST   /review-requests/{id}/approve
POST   /review-requests/{id}/request-changes
POST   /review-requests/{id}/apply

Realtime
WS     /realtime/documents/{document_id}
```

Error response는 항상 아래 형태를 유지한다.

```json
{
  "error": {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Document failed schema validation.",
    "details": {
      "errors": [
        {
          "path": "/learning_rate",
          "message": "0.001 is less than the minimum of 0.01",
          "validator": "minimum",
          "expected": 0.01,
          "actual": 0.001
        }
      ]
    }
  }
}
```

---

## 12. Permission 방향

현재 permission은 actor 존재 확인 수준이다. 이것은 foundation test에는 충분하지만 제품에는 부족하다.

따라서 comments, review, realtime 전에 최소 project-level RBAC를 넣는 것이 맞다.

초기 role 제안:

| Role | Read | Edit | Schema create | Rollback | Manage members |
|---|---:|---:|---:|---:|---:|
| Owner | Yes | Yes | Yes | Yes | Yes |
| Admin | Yes | Yes | Yes | Yes | Yes |
| Editor | Yes | Yes | No 또는 설정 | Optional | No |
| Reviewer | Yes | No | No | No | No |
| Viewer | Yes | No | No | No | No |

초기에는 project-level permission만 구현한다. path-level permission은 review workflow 이후 별도 설계하는 것이 좋다.

---

## 13. Path-level comment 방향

Comment는 document snapshot을 바꾸면 안 된다. 별도 collaboration metadata로 관리한다.

권장 anchor:

| Anchor | 예시 | 목적 |
|---|---|---|
| document | `doc_001` | 문서 전체 논의 |
| path | `/model/learning_rate` | field-specific memo |
| event | `event_001` | 특정 변경에 대한 논의 |
| diff item | version 2 -> 3, path `/x` | review 중 변경 단위 논의 |

상태:

- open
- resolved
- reopened

Comment는 RBAC 이후 구현하는 것이 맞다. permission 없이 comment를 붙이면 나중에 권한 구조를 다시 뜯게 된다.

---

## 14. Review workflow 방향

Review workflow는 GitHub PR을 그대로 복제하면 안 된다. JSON-native review가 되어야 한다.

권장 review model:

```text
ReviewRequest
- id
- project_id
- author_id
- status
- title
- description
- target_document_ids
- from_versions
- proposed_patch_set
- created_at
- applied_at
```

상태:

| State | 의미 |
|---|---|
| draft | 아직 제출 전 |
| open | review 대기 |
| changes_requested | 수정 요청으로 apply 차단 |
| approved | apply 가능 |
| applied | canonical document에 반영 완료 |
| closed | 폐기 |

Review apply 시에도 기존 원칙은 유지된다.

```text
base_version 확인
schema validation
DocumentEvent 생성
snapshot update
replay consistency 유지
```

---

## 15. Realtime collaboration 방향

Realtime은 늦게 붙여야 한다. 이유는 단순하다.

- validation이 먼저 안정적이어야 한다.
- permission이 먼저 안정적이어야 한다.
- event model이 먼저 안정적이어야 한다.
- conflict policy가 먼저 명확해야 한다.

권장 원칙:

> realtime session은 협업 UX일 뿐이고, canonical persistence는 여전히 validated DocumentEvent다.

권장 흐름:

```text
client proposed change
-> server validates permission/version/schema
-> accepted DocumentEvent 생성
-> accepted event broadcast
```

Raw text collaboration을 source of truth로 만들면 안 된다.

---

## 16. 배포 전 readiness gate

### 16.1 Data integrity gate

- replay == latest snapshot
- append-only DocumentEvent 보호
- rollback as new event
- schema-bound event에 validation_schema_id 기록
- migration 이후 replay consistency 유지

### 16.2 API gate

- error format 통일
- version conflict 처리
- malformed payload 처리
- history/list pagination
- OpenAPI 검토

### 16.3 Security gate

- production auth
- project membership
- role-based permission
- `X-Actor-Id` spoofing 제거
- critical mutation audit log

### 16.4 Storage gate

- PostgreSQL migration
- JSONB storage
- migration tool 도입
- backup/restore 테스트
- transaction isolation 검토

### 16.5 Observability gate

- structured logs
- request ID
- error tracking
- replay consistency scheduled check
- validation failure metrics
- migration logs

### 16.6 UX gate

- document explorer
- JSON editor
- validation panel
- history/diff panel
- rollback confirmation
- schema registry view

---

## 17. Roadmap

| Task | 이름 | 이유 |
|---|---|---|
| TASK_002_HARDENING | Schema auditability baseline | schema 신뢰성 잠금 |
| TASK_003 | Minimal project membership / RBAC | permission refactor 방지 |
| TASK_004 | Path-level comments / memo | 협업 context 추가 |
| TASK_005 | Review workflow | controlled change process |
| TASK_006 | PostgreSQL migration | 배포 가능한 storage 기반 |
| TASK_007 | Frontend MVP | 실제 사용 가능한 제품화 |
| TASK_008 | Realtime collaboration | 안전 기반 이후 live 협업 |
| TASK_009 | Deployment hardening | staging/production 준비 |
| TASK_010 | Observability and backup | 운영 신뢰성 확보 |

---

## 18. 제품 리스크

| Risk | 문제 | 대응 |
|---|---|---|
| Git clone으로 변질 | 제품 범위 과대 | JSON-native review 유지 |
| Realtime 조기 구현 | invalid state 확산 | validation/permission 이후 구현 |
| Permission 취약 | audit 신뢰 하락 | RBAC를 comments/review 전 구현 |
| Schema history 불명확 | 과거 검증 기준 설명 불가 | validation_schema_id 기록 |
| SQLite 장기 사용 | production 한계 | PostgreSQL migration 별도 task |
| UI 조기 구현 | backend 변경으로 재작업 | backend gate 후 UI |

---

## 19. 최종 디자인 stance

OpenJson은 화려한 JSON editor가 아니라, ledger-backed developer tool이어야 한다.

제품의 최종 모양은 다음이다.

```text
GitHub-level audit discipline
+ JSON Schema validation
+ field-level history
+ rollback without history deletion
+ path-level comments
+ review workflow
+ eventual realtime collaboration
```

속도보다 먼저 신뢰를 얻어야 한다. Realtime은 마지막에 붙이는 가속 장치이지, 제품의 foundation이 아니다.
