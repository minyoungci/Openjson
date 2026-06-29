---
title: "OpenJson Goal Engineering Playbook"
subtitle: "배포 전까지 목표 기반으로 개발을 통제하는 agent 실행 문서"
status: "Execution Baseline"
version: "0.2"
last_updated: "2026-06-27"
---

# OpenJson Goal Engineering Playbook

## 0. 문서 목적

이 문서는 agent에게 `goal` 명령어를 사용해 OpenJson 개발을 계속 진행시킬 때 필요한 실행 규칙이다.

중요한 점은, `goal` 명령어가 “무한히 기능을 추가하라”는 뜻이 아니라는 것이다. 올바른 방식은 다음이다.

```text
baseline 읽기
-> goal 계획 보고
-> 승인된 범위만 구현
-> 테스트와 증거 제출
-> baseline 고정
-> 다음 goal 선택
```

배포 이전까지 완성도를 높이려면 “무한 엔지니어링”이 아니라 **통제된 goal loop**가 필요하다. 그렇지 않으면 scope creep 때문에 제품이 커지기만 하고 신뢰성은 떨어진다.

---

## 1. 모든 goal의 공통 계약

모든 goal 명령은 아래 구조를 가져야 한다.

```text
/goal <GOAL_ID>

Objective:
  이번 goal에서 달성해야 하는 것.

Required reading:
  agent가 코딩 전에 읽어야 하는 문서.

Scope:
  구현해도 되는 범위.

Out of scope:
  절대 구현하면 안 되는 범위.

Data integrity constraints:
  깨지면 안 되는 invariant.

Expected files:
  생성/수정 예상 파일.

API changes:
  추가/변경할 endpoint.

DB changes:
  table, column, index, trigger, migration.

Tests required:
  반드시 추가해야 하는 테스트.

Acceptance gate:
  goal 완료로 인정되는 조건.

Report format:
  구현 완료 후 보고 형식.
```

Agent는 구현 전에 반드시 계획과 파일 목록을 먼저 보고해야 한다.

---

## 2. Global rules

모든 goal에서 반드시 지켜야 하는 규칙이다.

```text
제품 방향을 몰래 바꾸지 마세요.
현재 goal 범위를 넘는 기능을 구현하지 마세요.
Realtime은 validation과 permission gate 이후에만 구현하세요.
UI는 backend behavior가 안정화된 뒤 구현하세요.
Snapshot을 event 없이 변경하지 마세요.
Rollback을 event 삭제로 구현하지 마세요.
Schema validation 실패가 event를 만들면 안 됩니다.
Schema validation 실패가 snapshot을 바꾸면 안 됩니다.
Actor 존재 확인만으로 production permission을 대체하지 마세요.
SQLite를 production-ready storage로 취급하지 마세요.
새 dependency는 이유를 보고한 뒤 추가하세요.
```

절대 invariant:

```text
Replay(DocumentEvent[0..N]) == latest snapshot
```

---

## 3. 현재 baseline

| Task | Status | Purpose |
|---|---:|---|
| TASK_001 | 완료 | Versioned JSON document foundation |
| TASK_001_HARDENING | 완료 | Replay, rollback, diff, transaction safety |
| TASK_002 | 완료 | JSON Schema validation + schema registry |
| TASK_002_HARDENING | 다음 | Schema immutability + validation audit hardening |

현재 명시적으로 금지된 기능:

- realtime collaboration
- comments/memo
- review workflow
- Git integration
- AI features
- branching
- pull request clone
- UI implementation
- WebSocket
- offline sync
- automatic merge/conflict resolution
- complex path-level permission

---

## 4. 배포까지 권장 goal 순서

```text
GOAL_002H  TASK_002_HARDENING
GOAL_003   Minimal project membership / RBAC
GOAL_004   Path-level comments / memo
GOAL_005   Review workflow
GOAL_006   PostgreSQL migration and managed migrations
GOAL_007   Frontend MVP
GOAL_008   Realtime collaboration
GOAL_009   Deployment hardening
GOAL_010   Observability, backup, restore
GOAL_011   Security hardening
GOAL_BETA  Beta release gate
```

RBAC 전에 comments/review/realtime로 넘어가면 안 된다.

---

## 5. Goal command: TASK_002_HARDENING

```text
/goal GOAL_002H_TASK_002_HARDENING

Objective:
  Schema registry와 schema validation auditability를 보강한다.

Required reading:
  - AGENTS.md
  - docs/TASK_001_BASELINE.md
  - docs/TASK_002_PLAN.md
  - docs/DEV_USAGE.md

Scope:
  - docs/TASK_002_BASELINE.md 생성
  - schemas table update/delete 금지 trigger 추가
  - document_events.validation_schema_id nullable FK 추가
  - document response에 schema_id 포함 확인
  - full_path separator 정책 확정
  - schema-invalid patch/rollback no-mutation 검증
  - lightweight migration idempotence 검증
  - requirements.txt 기반 clean install 검증

Out of scope:
  - realtime
  - comments
  - review workflow
  - Git
  - AI
  - UI
  - WebSocket
  - complex permissions

Data integrity constraints:
  - schema validation 실패 시 event 없음
  - schema validation 실패 시 snapshot 변경 없음
  - schema validation 실패 시 version 증가 없음
  - rollback은 새 event
  - replay consistency 유지
  - schemas table은 TASK_002 baseline 기준 append-only

Tests required:
  - direct SQL UPDATE schemas 실패
  - direct SQL DELETE schemas 실패
  - bound create/patch/rollback event에 validation_schema_id 저장
  - unbound document event는 validation_schema_id null
  - document response에 schema_id 포함
  - backslash path policy test
  - migration idempotence test
  - schema-invalid rollback no-mutation test

Acceptance gate:
  - python -m unittest discover -v 통과
  - python -m compileall app tests scripts 통과
  - create/patch/rollback/schema validation 케이스에서 replay consistency 통과

Report format:
  - 변경 파일
  - DB schema 변경
  - 추가 trigger
  - validation_schema_id 동작
  - 테스트 결과
  - clean install 결과
  - limitation
```

---

## 6. Goal command: Minimal RBAC

```text
/goal GOAL_003_MINIMAL_RBAC

Objective:
  actor 존재 확인 수준의 mutation check를 project membership + role-based permission으로 대체한다.

Required reading:
  - AGENTS.md
  - docs/TASK_001_BASELINE.md
  - docs/TASK_002_BASELINE.md
  - docs/DEV_USAGE.md

Scope:
  - project_members table 추가
  - roles 추가: owner, admin, editor, reviewer, viewer
  - document/schema mutation permission check 추가
  - project-level permission만 구현
  - seed_dev.py에 project membership 생성 추가
  - 허용/거부 테스트 추가

Out of scope:
  - path-level permission
  - SSO
  - invitation email flow
  - UI
  - comments
  - review workflow

DB changes:
  project_members:
    - id
    - project_id
    - user_id
    - role
    - created_at
    - UNIQUE(project_id, user_id)

Permission policy:
  - owner/admin: 모든 project operation 가능
  - editor: document create/patch/delete/rollback/validate 가능
  - reviewer: read/history/diff/validate 가능
  - viewer: read/history/diff 가능

Acceptance gate:
  - 기존 TASK_001/TASK_002 테스트 통과
  - unauthorized mutation은 PERMISSION_DENIED
  - project member가 아닌 actor는 mutation 불가
  - viewer는 patch 불가
  - editor는 patch 가능
  - admin은 schema 생성 가능
  - replay consistency 유지
```

---

## 7. Goal command: Path-level comments

```text
/goal GOAL_004_PATH_LEVEL_COMMENTS

Objective:
  document, JSON Pointer path, event에 anchor되는 memo/comment thread를 추가한다.

Required reading:
  - AGENTS.md
  - docs/TASK_001_BASELINE.md
  - docs/TASK_002_BASELINE.md
  - docs/RBAC_BASELINE.md if available

Scope:
  - comment_threads table 추가
  - comments table 추가
  - file-level comment 지원
  - JSON Pointer path-level comment 지원
  - event-level comment 지원
  - resolve/reopen 지원
  - project-level permission 적용

Out of scope:
  - review workflow
  - realtime comment updates
  - mentions/notifications
  - UI
  - AI comment summarization

Data integrity constraints:
  - comment는 document snapshot을 변경하지 않음
  - comment는 DocumentEvent를 만들지 않음
  - soft-deleted document의 history/comment 접근 정책을 명확히 함

Acceptance gate:
  - create/list/resolve/reopen comment 테스트 통과
  - invalid JSON Pointer path 정책 확정
  - permission 테스트 통과
  - 기존 replay consistency 테스트 통과
```

---

## 8. Goal command: Review workflow

```text
/goal GOAL_005_REVIEW_WORKFLOW

Objective:
  canonical event로 적용되기 전 proposed JSON changes를 검토하는 review workflow를 추가한다.

Required reading:
  - AGENTS.md
  - docs/TASK_001_BASELINE.md
  - docs/TASK_002_BASELINE.md
  - docs/RBAC_BASELINE.md
  - docs/COMMENTS_BASELINE.md

Scope:
  - review_requests table 추가
  - review_request_changes table 추가
  - review decision 추가: approve, request_changes, comment_only
  - proposed patch는 apply 전 validation
  - apply 시 정상 DocumentEvent 생성

Out of scope:
  - Git branches
  - Pull request clone
  - Realtime review
  - UI
  - AI reviewer

Data integrity constraints:
  - proposed changes는 apply 전 canonical이 아님
  - apply 시 base_version 확인
  - apply 시 schema validation
  - apply 시 DocumentEvent 생성
  - rejected changes는 snapshot을 변경하지 않음

Acceptance gate:
  - approved review는 apply 가능
  - changes_requested는 apply 차단
  - schema-invalid proposed change는 apply 불가
  - apply 중 version conflict는 VERSION_CONFLICT
  - replay consistency 유지
```

---

## 9. Goal command: PostgreSQL migration

```text
/goal GOAL_006_POSTGRESQL_MIGRATION

Objective:
  SQLite MVP storage에서 PostgreSQL-ready architecture로 이동한다.

Scope:
  - PostgreSQL configuration 추가
  - migration tool 도입
  - JSON storage를 JSONB로 전환
  - event log semantics 유지
  - trigger 또는 equivalent constraint 이식
  - 가능한 범위에서 integration test 추가

Out of scope:
  - horizontal scaling
  - multi-region replication
  - enterprise deployment
  - realtime collaboration

Acceptance gate:
  - SQLite test 유지 여부 명확화
  - PostgreSQL test DB에서 core integration test 통과
  - replay consistency 통과
  - migration 문서화
  - backup/restore plan 초안 작성
```

---

## 10. Goal command: Frontend MVP

```text
/goal GOAL_007_FRONTEND_MVP

Objective:
  안정화된 backend 위에 최소 web UI를 만든다.

Scope:
  - document explorer
  - JSON editor 또는 structured textarea MVP
  - schema registry view
  - validation panel
  - history/diff panel
  - rollback confirmation

Out of scope:
  - realtime collaboration
  - review workflow UI unless backend exists
  - AI features
  - full design system
  - billing

UX principle:
  예쁜 화면보다 명확한 데이터 상태를 우선한다.

Acceptance gate:
  - schema-bound document 생성 가능
  - document patch 가능
  - validation error를 path 단위로 확인 가능
  - history/diff 확인 가능
  - rollback 가능
  - backend invariant 약화 없음
```

---

## 11. Goal command: Realtime collaboration

```text
/goal GOAL_008_REALTIME_COLLABORATION

Objective:
  validated DocumentEvent를 canonical persistence로 유지하면서 realtime collaboration을 추가한다.

Prerequisites:
  - TASK_001 baseline locked
  - TASK_002 baseline locked
  - RBAC baseline locked
  - Frontend MVP exists or client behavior is defined

Scope:
  - WebSocket session
  - presence
  - path-level editing indicator
  - accepted event broadcast
  - version conflict handling

Out of scope:
  - raw text CRDT as source of truth
  - offline-first sync
  - automatic semantic merge
  - review workflow changes

Critical rule:
  realtime update는 server validation 후 DocumentEvent가 생성되기 전까지 canonical이 아니다.

Acceptance gate:
  - 두 사용자가 다른 path 수정 가능
  - 같은 path conflict 정책 명확화
  - schema-invalid realtime proposal reject
  - accepted event broadcast가 저장된 DocumentEvent와 일치
  - replay consistency 통과
```

---

## 12. Goal command: Deployment hardening

```text
/goal GOAL_009_DEPLOYMENT_HARDENING

Objective:
  staging deployment를 준비한다.

Scope:
  - environment config
  - production auth plan
  - Docker setup
  - database migration command
  - health check endpoint
  - CORS policy
  - logging baseline
  - error tracking hooks

Out of scope:
  - enterprise SSO
  - billing
  - multi-region
  - Kubernetes unless explicitly needed

Acceptance gate:
  - clean checkout에서 dependency install 가능
  - DB init/migrate 가능
  - test 통과
  - server 실행 가능
  - smoke test 문서화
  - secret commit 없음
```

---

## 13. Goal command: Observability and backup

```text
/goal GOAL_010_OBSERVABILITY_BACKUP

Objective:
  배포 후 운영 가능한 상태를 만든다.

Scope:
  - structured request logging
  - request ID propagation
  - error logging
  - replay consistency check job
  - backup script
  - restore test script
  - validation failure metrics
  - migration logs

Out of scope:
  - full enterprise monitoring stack
  - data warehouse analytics
  - AI telemetry

Acceptance gate:
  - backup 생성 가능
  - restore 테스트 가능
  - replay consistency job이 pass/fail 보고
  - critical mutation log에 actor, document, version, event_id 포함
```

---

## 14. Beta release gate

```text
/goal GOAL_BETA_RELEASE_GATE

Objective:
  beta deployment 가능 여부를 판정한다.

Must pass:
  - all tests
  - fresh install
  - empty DB migration
  - previous baseline DB migration
  - replay consistency check
  - schema validation negative tests
  - RBAC mutation denial tests
  - rollback tests
  - backup/restore smoke
  - API smoke
  - security checklist
  - deployment smoke

Must document:
  - known limitations
  - data retention policy
  - backup policy
  - auth policy
  - supported JSON Patch operations
  - supported JSON Schema draft
  - non-goals

Decision:
  - APPROVE_BETA
  - BLOCK_BETA_WITH_FIXES
  - REJECT_BETA
```

---

## 15. 금지해야 할 anti-pattern

| Anti-pattern | 위험 |
|---|---|
| event 없는 snapshot update | audit 파괴 |
| rollback 중 event 삭제 | history 신뢰 파괴 |
| schema in-place update | 과거 validation 기준 불명확 |
| raw text realtime을 source of truth로 사용 | invalid intermediate state 가능 |
| actor 존재 확인만으로 permission 처리 | production 취약 |
| backend gate 전 UI 구현 | 재작업 가능성 증가 |
| Git을 primary backend로 사용 | path-level audit와 불일치 |
| goal 하나에 기능 과다 포함 | completion과 검증 불가능 |

---

## 16. 권장 operating loop

모든 goal은 아래 흐름을 따른다.

```text
1. Agent가 required docs를 읽는다.
2. Agent가 구현 계획과 파일 목록을 보고한다.
3. 사람이 scope를 승인하거나 수정한다.
4. Agent가 승인된 범위만 구현한다.
5. Agent가 test와 compile check를 실행한다.
6. Agent가 evidence를 보고한다.
7. 사람이 baseline 승인 여부를 결정한다.
8. Agent가 baseline 문서를 작성한다.
9. 다음 goal로 넘어간다.
```

이 방식이 빠르면서도 안전하다.

---

## 17. 최종 engineering stance

OpenJson은 ledger-backed developer tool처럼 개발해야 한다.

개발 철학은 다음이다.

```text
Every change is an event.
Every event is attributable.
Every snapshot is replayable.
Every schema-bound event is explainable.
Every goal has a gate.
```

“완벽함”을 기능 추가로 달성하려고 하면 실패한다. 배포 가능한 완성도는 **한 layer씩 baseline을 잠그는 방식**으로 만든다.
