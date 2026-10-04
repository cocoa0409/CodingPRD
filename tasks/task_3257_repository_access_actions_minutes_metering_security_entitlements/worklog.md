# Worklog — task_3257_repository_access_actions_minutes_metering_security_entitlements

## Step 1: Create task directory — 2026-09-30T14:54:55.849Z

Used pre-allocated directory `./tasks/task_3257_repository_access_actions_minutes_metering_security_entitlements/` (already created with `workspace/` inside); no new index computed.

## Step 2: Generate scaffold — 2026-09-30T15:55:00.000Z

All three scaffold artifacts are complete and lint-clean. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3257_repository_access_actions_minutes_metering_security_entitlements/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**SCAFFOLD.yaml counts:**
- Entities: 15 (Enterprise, Organization, UserAccount, CommitEvent, Team, TeamMembership, Repository, OutsideCollaborator, SelfHostedRunner, WorkflowRun, StorageArtifact, SecurityEntitlement, PersonalAccessToken, AuditLogEvent, MarketplaceAppInstallation)
- State machines: 12 (incl. cyclic SSO enforcement, parallel execution×billing dimensions on WorkflowRun, field-level cyclic TeamMembership role)
- Calculations: 6 (seat counting with CYCLE/PROJECTED variants, Actions minutes tiered billing with pinned round-per-run order, per-committer security pricing with frozen-at-activation, storage billing with half-open freeze overlap, collaborator limit threshold, team permission DAG with cycle detection)
- Validations: 19 (priority-ordered across auth/existence/state/safety/constraint/referential/temporal/fiscal)
- Endpoints: 40 (exactly at the cap; flat topology, merged lifecycle `.../transition` actions, `/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z)
- Errors: 50
- Roles: 5 (EnterpriseAdmin opaque, OrgAdmin opaque, UserAccount entity_backed:UserAccount, RunnerAgent opaque, Any opaque)
- Concurrency rules: 2 (OCC on Organization.version for entitlement create; OCC on Repository.version for run dispatch)

**Design files:**
- §1.8: 18 instances — all 9 rules × 2, each with structured setup_api_calls/trigger/assert chains and pre-computed literal asserts (e.g., 5×ceil(0.8)=5¢ per-run-rounding vs 4¢ sum-rounding; 1900¢ SECRET_SCANNING; ceil(10×1.6)=16¢ partial crossing)
- §1.9: 42 total — 36 active instances across entities/state_machines/calculations/validations/endpoints/errors/rbac/cross_cutting_layers/consistency_model sections, plus 6 `excluded_because` stubs citing §1.8 instances

**Lint:** `scaffold_lint.py` verdict — clean (374 calls scanned, 0 violations; all FKs reverse-reachable). Notable fixes along the way: restructured from nested to flat paths so the lint's segment derivation works; sub-resource GET parents renamed to literal `{id}` placeholders; removed forbidden "in parallel" vocabulary; added `retention_freeze_windows` to Organization to ground the retention-conflict calculation; added `ERR_ENTITLEMENT_NOT_PENDING_ACTIVATION` and `overage_cost_cents` field for observability.

## Step 3: Copy shared files — 2026-09-30T15:56:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T16:05:00.000Z

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3257_repository_access_actions_minutes_metering_security_entitlements/workspace/PRD.md`
**Line count:** 345
**Section structure produced:**

- §1 Introduction (3 paragraphs)
- §2 Global Specifications (9 subsections)
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Resource Identity, Hierarchy, and Common Fields
  - 2.5 Optimistic Concurrency Control
  - 2.6 Precision and Rounding Conventions
  - 2.7 The Logical Clock and Lazy Expiry
  - 2.8 Single Sign-On Posture as a Cross-Cutting Gate
  - 2.9 Validation Priority Order
- §3 Business Logic & Workflows (10 subsections)
  - 3.1 Enterprise Onboarding and SSO Lifecycle
  - 3.2 Billing Cycle, Included Allowances, and the Plan Tier
  - 3.3 Users, Committer Activity, and the Seat Ledger
  - 3.4 Teams, Memberships, and Inherited Permissions
  - 3.5 Repositories, Visibility, and Outside Collaborators
  - 3.6 Self-Hosted Runners and Workflow Run Metering
  - 3.7 Storage Artifacts, Retention, and Freeze Windows
  - 3.8 Security Entitlements and Per-Committer Pricing
  - 3.9 Organization Lifecycle, Suspension Cascades, and Archival
  - 3.10 Personal Access Tokens, Marketplace Applications, and Audit Trail
- §4 Endpoint Definitions (39-row table, 4 columns)
- §5 Error Code Catalogue (50-row table, 2 columns)

**Hard Contracts — all PASS:**

```
Field coverage check:
- entities[].fields: 50 required, 50 present, 0 missing
- endpoints[].request_body + query_params (union, deduped): 61 total required, 61 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed in priority-ordered §2.9 prose
- concurrency_rules[] OCC rejections: 2 checked (entitlement-create on expected_organization_version, workflow-run-create on expected_repository_version), both expressed with write capability, occ field name, ERR_STALE_VERSION, HTTP 412
- state_machines[].transitions: all transitions across Enterprise SSO, Organization, UserAccount, OutsideCollaborator, Repository, SelfHostedRunner, WorkflowRun (both dimensions), StorageArtifact, SecurityEntitlement, PersonalAccessToken, MarketplaceAppInstallation, TeamMembership expressed with preconditions and side effects
- calculations[]: all 6 expressed (active_committer_seat_count + 2 variants, actions_minutes_billing with pinned order and per-run rounding, security_entitlement_pricing, storage_billing with half-open interval semantics, outside_collaborator_limit_check, team_permission_inheritance)
- validations[] conditions: all 19 matchable to error_ids in §2.9 priority list and §3 narrative
- endpoints[].side_effects: covered in §3 narrative per entity
- entities[].fields[] structured content: defaults (pat_policy=UNRESTRICTED, plan_tier=TEAM, billing_cycle_anchor_day=1, role=MEMBER, retention_days=90, allowed_on_public_repos=false), enums (sso_enforcement, audit_log_stream_status, plan_tier, visibility, os_type, runner_kind, product, scopes, permission_scopes, all status fields) reconstructible from prose
- sibling-branch symmetry: QUEUED-cancel vs RUNNING-cancel; COMPLETE vs FAIL; revocation sources on PAT and runner REMOVED — expressed with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 528
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Constraint adherence:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, grepped, or referenced. No kill patterns were used; only Reads/Edits/Writes plus a single Python verification script and `wc -l`/`grep` for sanity checks.

## Step 5: Generate unit tests — 2026-09-30T16:25:00.000Z

All checks pass. 81 tests collected, all imports resolve, everything compiles. Final summary:

## Summary

**Task:** task_3257_repository_access_actions_minutes_metering_security_entitlements — full test infrastructure generated from the two design indices under the PRD-first two-condition filter.

### Files written

`test_helpers/` (all under `/home/ubuntu/github/CodingPRD/tasks/task_3257_repository_access_actions_minutes_metering_security_entitlements/`):
- `types.py` — 15 status/role enums + 15 entity TypedDicts (append-only `CommitEvent`/`AuditLogEvent` correctly omit `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per all 33 PRD §4 endpoints
- `api_errors.py` — `ApiErrorId` enum (50 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + seat-ledger invariant checker
- `factories.py` — 14 payload factories (input fields only)
- `constants.py` — OS multipliers, overage rates, product rates, plan allowances, 90-day/7-day/30-day windows
- `test_users.py` — `TEST_USERS` for the 3 opaque roles + `make_user_headers(user_id)` builder for the entity-backed `UserAccount` role
- `fixtures.py` — composite setup helpers (enterprise/org/repo chains, run dispatch+settle, runner activate, entitlement create/activate, PAT, app install, clock)
- `__init__.py` — barrel export

`test_suite/`:
- `conftest.py` + 7 test files (test_01 enterprise basics/access, test_02 SSO lifecycle, test_03 seats/collaborators, test_04 workflow minutes, test_05 runners/boundaries, test_06 org cascade/entitlements, test_07 storage/audit)

### Coverage (validated)
- **Total: 81 tests collected** by `pytest --collect-only`; all modules compile and import cleanly.
- **Queue A (§1.8 difficulty):** all 18/18 instances covered with exactly 2 tests each (36 tests).
- **Queue B (§1.9 corner):** all 29 non-stub instances covered with ≥1 test (45 tags); the 6 `excluded_because:` stubs in `state_machines_exclusions` were not translated (their difficulty-design owners carry the assertion — cross-references verified to resolve).
- Every test docstring ends with exactly one verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line; a tag sweep confirms all tags resolve to real instance names in the source YAMLs.

### Skipped instance
- None fully skipped. `Corner/state_machines/team_cycle_rejected` was translated as the acyclic-chain acceptance the instance's own `test_recipe.assert` specifies (the instance itself notes a true cycle cannot be expressed at creation since ids are server-minted).

### Notable translation choices
- Priority-pair instances assert the winning `error_id` explicitly named by PRD §2.9's ordered list (5 before 14; 7 before 11) — verbatim citations included.
- Cascade side effects on entities without GET endpoints (runner status, app installation status) are asserted through PRD-documented behavioral probes (heartbeat rejection, RESUME-only-from-SUSPENDED, filtered list reads) rather than over-asserting unobservable fields.
- `occ_stale_version_on_workflow_run_dispatch` uses a rename (not archive) to bump repo version, per PRD §2.5's own example.

## Step 6: Generate implementation — 2026-09-30T16:40:00.000Z

All 36 unique paths from the PRD endpoint table are implemented (40 route decorators — `/repositories/<rid>` and `/users/<uid>` and `/repositories/<rid>/workflow-runs` and `/repositories/<rid>/artifacts` each registered for two methods). The server has been stopped (kill PID I started). Done.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3257_repository_access_actions_minutes_metering_security_entitlements/workspace/implementation/`:

- `start.sh` — executable launcher: guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground).
- `requirements.txt` — `flask>=2.0`.
- `app.py` — Flask app, error handlers, all route handlers.
- `db.py` — in-memory store, logical clock defaulting to `2026-09-01T00:00:00Z` (never wall-clock).
- `errors.py` — full 46-entry error catalog with exact HTTP statuses.
- `response.py` — `meta`/`response_type`/`data` envelope, `req_` request IDs, millisecond ISO timestamps, `limit`/`offset`/`total_count`/`has_more` pagination (defaults 10/0, min 1, max 100).
- `services.py` — auth (X-User-ID/X-User-Role), serializers, seat ledger, storage accounting (3-decimal round-half-up), billing waterfall, lazy expiry sweeps, audit emission.

**Endpoint count:** all 36 paths / 38 endpoints from the PRD §4 table implemented (40 route registrations counting multi-method paths).

**Key behaviors verified by smoke tests:** envelope shape; 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; 403 `ERR_INSUFFICIENT_PERMISSIONS`; seat consume via commit event; CYCLE/PROJECTED seat-usage; workflow metering (ceil per run, WINDOWS 2x → 10 billed), allowance settlement; OCC `ERR_STALE_VERSION` (412); artifact storage add/re-credit; SSO CONFIGURE→ENFORCE with `pat.revoked_by_sso` cascade; entitlement activation (committer_count=1 → 1900 cents, `advanced_security_enabled=true`); clock-set invite expiry sweep (`ERR_INVITE_EXPIRED`); billing reset increments version and reports `reclaimed_seats`/`orgs_reset`; fresh reboot yields 404 for prior-run entities (no seeding, per-test isolation safe).

**start.sh contract:** respects `$PORT` (default 10000 via `app.py`), binds `0.0.0.0`, runs in foreground via `exec`.

## Step 7: Run tests and iterate — 2026-09-30T16:55:00.000Z

All 8 rounds pass 81/81. Leftover server PIDs I started were killed (2932600 and the launcher for 19881); the pgrep match shown is just the grep command itself. Cleanup done.

## Summary

- **Iterations run:** 2 sweeps of 8 parallel rounds each (16 rounds total).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none — both failing tests (`test_self_hosted_on_public_repo_with_disallowed_runner_forbidden`, `test_safety_error_wins_over_cross_org_reference`) are verbatim-covered by PRD §2.9 (rule 7 "Public-repository runner boundary ... else `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN`" ordered before rule 11 "Cross-organization referential integrity ... else `ERR_CROSS_ORG_REFERENCE`", plus "A request that fails an earlier rule is rejected with that rule's error and never reaches later rules") and PRD §3.6's unconditional "if the repository's `visibility` is `PUBLIC` and the run is `SELF_HOSTED`, the referenced runner's `allowed_on_public_repos` must be true". Unique derivability holds: the dispatch payload has exactly one foreign key (`runner_id`), so rule 7 unambiguously pre-empts rule 11.
- **Fixes applied to `implementation/`:** `workspace/implementation/app.py`, `dispatch_run` — reordered self-hosted runner validation to match PRD §2.9 priority: (a) `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN` check moved ahead of `ERR_RUNNER_LABEL_MISMATCH` and `ERR_CROSS_ORG_REFERENCE` (previously cross-org ran first, shadowing the rule-7 safety error), and (b) the public-repo check made unconditional on runner ownership (PRD §3.6 states the requirement with no ownership qualifier — an earlier edit adding an ownership guard was tested live, still failed, and was reverted). Final order: runner-not-found → public-repo boundary (rule 7) → label subset (rule 8) → cross-org reference (rule 11).
- **Final state:** 8/8 rounds, 81/81 tests passed, no flakiness.

## Step 8: Finalize PRD — 2026-09-30T17:00:00.000Z

Done. `PRD_FINALIZED.md` created at `/home/ubuntu/github/CodingPRD/tasks/task_3257_repository_access_actions_minutes_metering_security_entitlements/workspace/PRD_FINALIZED.md` — a byte-identical copy of `PRD.md` with zero edits.

## Summary

- **Line counts:** PRD.md = 345 lines; PRD_FINALIZED.md = 345 lines; delta = 0 lines (0.0%).
- **Changes:** none.

**Rationale.** The single `<step_7_diff>` item is an *implementation* fix to `workspace/implementation/app.py` `dispatch_run` (reordering self-hosted runner validation to runner-not-found → `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN` → `ERR_RUNNER_LABEL_MISMATCH` → `ERR_CROSS_ORG_REFERENCE`, and making the public-repo check unconditional on runner ownership). That fix brought the implementation into conformance with behavior the PRD already uniquely pins:

- PRD §2.9 rules 7, 8, 11 are explicitly ordered (public-repo boundary before label coverage before cross-org), with the closing sentence "A request that fails an earlier rule is rejected with that rule's error and never reaches later rules."
- PRD §2.9 rule 3 already resolves body-resource-not-found (`ERR_RUNNER_NOT_FOUND`) ahead of rule 7.
- PRD §3.6 states the public-repo requirement with no ownership qualifier and presents the two safety checks in the same order the implementation now uses.

Since the step_7_diff records no test-suite/test-helper fixes and no remaining PRD silence or mismatch, the minimal correct patch is the empty patch.

**Pre-edit search log (for the one evaluated candidate edit, which was rejected):**
- (a) Subject: dispatch-time self-hosted runner validation order and the unconditionality of the public-repo boundary check.
- (b) Impl paths enumerated and read/grepped: `implementation/app.py` `dispatch_run` (lines 756-803, the only site combining `ERR_RUNNER_NOT_FOUND`/boundary/label/cross-org), `create_runner` (701-719, only sets the `allowed_on_public_repos` default), `delete_runner` (736-750, unrelated `ERR_RUNNER_NOT_FOUND` reuse), `run_transition` START (822-840, re-checks only runner `ACTIVE`, no boundary/label logic). Verified via grep that `ERR_PUBLIC_REPO_RUNNER_FORBIDDEN` and `ERR_RUNNER_LABEL_MISMATCH` appear nowhere else.
- (c) Wording adjustment: none needed — existing PRD text (§2.9 rules 3/7/8/11 + closing precedence sentence; §3.6's unqualified "the referenced runner's `allowed_on_public_repos` must be true") is consistent with every enumerated path, so no edit was committed.

## Step 9: Complete PRD — 2026-09-30T17:10:00.000Z

All 36 hunks correspond to my edits (two edits landed on the same paragraph and merged into one hunk). The work is done. Summary:

## Summary

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_3257_repository_access_actions_minutes_metering_security_entitlements/workspace/PRD_COMPLETED.md` (created from `PRD_FINALIZED.md`; `PRD.md` is identical to `PRD_FINALIZED.md`).

- Source `PRD_FINALIZED.md`: 345 lines / 51,084 chars → `PRD_COMPLETED.md`: 345 lines / 59,737 chars (**+8,653 chars, 0 line delta** — all edits are in-paragraph inserts/revisions; no new sections).
- **Counts:** 31 ambiguity-pins, 5 mismatch-revisions (36 diff hunks total).

### Mismatch revisions (PRD described different behavior than impl)

- §2.1 — revise — mismatch — "five roles" → four literal header roles; `Any` redefined as a documentation-only pseudo-role never valid as an `X-User-Role` value — `services.py:10` (`VALID_ROLES` excludes `Any`), `services.py:60-62`.
- §3.2 — revise — mismatch — org `login` "unique within the enterprise" → uniqueness not enforced, duplicates accepted — `app.py:251-285` (no uniqueness check).
- §3.3 — revise — mismatch — user `login` "globally unique" → not enforced — `app.py:377-390`.
- §3.8 — revise — mismatch — entitlement `SUSPEND` "flips `advanced_security_enabled` to false" → recomputes the flag, which stays true if another ACTIVE entitlement covers the repo — `services.py:629-633`, `app.py:998-1005`.
- §3.9 — revise — mismatch — suspend cascade "each refunded run … increments the parent enterprise's `version`" → enterprise version increments exactly once, and only if at least one queued run was refunded — `app.py:309-316`.

### Ambiguity pins (PRD silent; pinned to impl)

- §2.3 — insert — pagination `limit`/`offset` violations → `ERR_INVALID_REQUEST` (400) — `response.py:46-58`.
- §2.5 — insert — org `version` also advances on artifact upload/delete/expiry, run metering/settlement, and cascades — `services.py:357-369, 573-618`.
- §2.7 — insert — clock endpoint rejects malformed `to_iso8601` with `ERR_INVALID_REQUEST`, responds `{"current_utc": ...}`, may move backward — `app.py:1178-1189`.
- §3.1 — insert — `purchased_seats` must be an integer ≥ 0 — `app.py:65`.
- §3.1 — insert — SSO-enforce depth-three app suspension emits no audit event — `app.py:151-158`.
- §3.1 — insert — stream toggle returns the enterprise resource; `streamed` filter parsed case-insensitively (`true/1/yes`, `false/0/no`), else `ERR_INVALID_REQUEST` — `app.py:218-246`.
- §3.2 — insert — freeze-window entries validated (object with ISO `start`/`end`, else `ERR_INVALID_REQUEST`) — `app.py:258-273`.
- §3.2 — insert — `storage_overage_cents` computed at reset is internal-only; response carries exactly `reclaimed_seats`, `orgs_reset` — `app.py:190-215`.
- §3.3 — insert — `is_active_committer` is org-agnostic (any org's commits) and recomputed only for the authoring user on ingest and for seat-holders at reset — `services.py:341-355`.
- §3.3 — insert — commit ingest exempt from org-active gate; `committed_at` ISO validation; unknown ids → `ERR_USER_NOT_FOUND`/`ERR_ORG_NOT_FOUND` — `app.py:431-455`.
- §3.3 — insert — `CYCLE` counts `seat_held_enterprise_id` holders; `PROJECTED` exact formula (in-window now AND latest commit ≥ clock+30d−90d; commit-events only); invalid mode → `ERR_INVALID_REQUEST` — `app.py:89-121`, `services.py:307-311`.
- §3.4 — insert — team create requires org ACTIVE; dangling `parent_team_id` → `ERR_TEAM_NOT_FOUND`; cross-org parent → `ERR_CROSS_ORG_REFERENCE` — `app.py:460-495`.
- §3.4 — insert — membership upsert requires org ACTIVE, unknown user → `ERR_USER_NOT_FOUND`, both create and role-update return 201 — `app.py:507-530`.
- §3.5 — insert — repo create requires org ACTIVE and applies the PUBLIC-visibility SSO gate — `app.py:535-556`.
- §3.5 — insert — patch requires org ACTIVE, accepts stripped `name`, non-`ARCHIVED` status → `ERR_INVALID_REQUEST`, no-op visibility emits no event — `app.py:564-608`.
- §3.5 — insert — invite: unknown repo → `ERR_REPO_NOT_FOUND`, cross-org repo → `ERR_CROSS_ORG_REFERENCE` — `app.py:613-641`.
- §3.5 — insert — accept: wrong user → `ERR_INSUFFICIENT_PERMISSIONS`; non-INVITED/non-EXPIRED row → `ERR_INVALID_REQUEST` — `app.py:644-672`.
- §3.5 — insert — revoke from `EXPIRED`/`REVOKED` is a 200 no-op — `app.py:675-696`.
- §3.6 — insert — runner removal moves to terminal `REMOVED` (200 with row); repeat delete → `ERR_RUNNER_NOT_FOUND` — `app.py:736-750`.
- §3.6 — insert — dispatch requires repo ACTIVE; SELF_HOSTED without `runner_id` / HOSTED with `runner_id` → `ERR_INVALID_REQUEST`; new run starts with `billed_minutes`=0, `overage_cost_cents`=0 and carries `organization_id` — `app.py:755-803`.
- §3.6 — insert — dispatch check order: public-repo boundary, then label subset, then cross-org — `app.py:780-789`.
- §3.6 — insert — START/COMPLETE/FAIL are RunnerAgent-only (others → 403); missing/removed runner on START → `ERR_RUNNER_NOT_ACTIVE` — `app.py:822-850`.
- §3.6 — insert — CANCEL from a terminal state → `ERR_INVALID_REQUEST`; refund floors consumption at zero — `app.py:851-862`, `services.py:610-618`.
- §3.7 — insert — upload requires repo ACTIVE; `retention_days` out of 1–400 → `ERR_INVALID_REQUEST` — `app.py:868-899`.
- §3.7 — insert — delete of `EXPIRED`/`DELETED` artifact is a 200 no-op — `app.py:916-927`.
- §3.8 — insert — entitlement create: unknown repo → `ERR_REPO_NOT_FOUND`, cross-org repo → `ERR_CROSS_ORG_REFERENCE`; new row starts with `committer_count`/`monthly_price_cents` 0 — `app.py:932-963`.
- §3.8 — insert — SUSPEND/RESUME/CANCEL from wrong states → `ERR_INVALID_REQUEST` — `app.py:998-1024`.
- §3.9 — insert — unsuspend checks SSO-in-flight before the SUSPENDED-state check — `app.py:326-331`.
- §3.9 — insert — archive from non-ACTIVE → `ERR_ORG_NOT_ACTIVE` — `app.py:343-345`.
- §3.10 — insert — PAT `scopes` must be a non-empty list; out-of-set or malformed → `ERR_INVALID_REQUEST`; `userId`≠`X-User-ID` → 403 — `app.py:1030-1056`.
- §3.10 — insert — APPROVE SSO check precedes pending-state check; APPROVE by UserAccount → 403; REVOKE from terminal state → `ERR_INVALID_REQUEST`; `EXPIRED` token state reserved (no API transition produces it); cross-user token list → 403 — `app.py:1059-1109`.
- §3.10 — insert — app installs: non-list scopes → `ERR_INVALID_REQUEST`; INSTALL SSO check before org-active; INSTALL/SUSPEND/RESUME/UNINSTALL from wrong states → `ERR_INVALID_REQUEST`; resume emits no audit event — `app.py:1114-1173`.
- §3.10 — insert — `actor_login` resolution: user's `login` for UserAccount-role callers with a resolvable id, raw `X-User-ID` otherwise, `system` when absent — `services.py:35-46, 244-258`.

## Post-Step-9 sweep re-run — 2026-09-30T17:12:00.000Z

Re-ran the 8-round parallel stability sweep (results files were missing after Step 9). All 8 rounds: 81/81 passed, 0 failed. No implementation edits occurred after Step 7 (mtimes confirm app.py last touched at Step 7; PRD_FINALIZED.md and PRD_COMPLETED.md are doc-only).
