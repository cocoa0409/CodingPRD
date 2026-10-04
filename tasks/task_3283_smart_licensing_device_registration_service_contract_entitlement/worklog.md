# Worklog — task_3283_smart_licensing_device_registration_service_contract_entitlement

## Step 1: Create task directory — 2026-09-30T17:05:00.000Z

Pre-allocated task directory verified: `./tasks/task_3283_smart_licensing_device_registration_service_contract_entitlement/` with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T17:31:00.000Z

  Scaffold generation complete for task_3283_smart_licensing_device_registration_service_contract_entitlement.

  - Endpoints: 63 (incl. `POST /api/_clock/set_current_utc` with fixed default 2026-09-01T00:00:00Z)
  - Entities: 14 (SmartAccount, PartnerOrg, PartnerDelegation, VirtualAccount, LicensePool, Device, DeviceLicenseAssignment, UsageReport, ComplianceEvent, ProductLifecycleMilestone, ServiceContract, ContractCoverage, RmaCase, LicenseTransferRequest)
  - Difficulty instances: 18 (9 rules × 2) in SCAFFOLD_DIFFICULTY_DESIGN.yaml
  - Corner instances: 29 across 11 sections in SCAFFOLD_CORNER_DESIGN.yaml
  - Also: 21 errors, 18 ordered validations, 11 state machines, 6 calculations, 2 OCC concurrency rules, 4 roles
  - `scaffold_lint.py` verdict: clean lint (all §1.8/§1.9 calls conform to §1.5; all FKs reverse-reachable)
  - All three required files exist at the target path and parse as valid YAML with correct top-level keys.

  [Orchestrator note: first Step 2 attempt died on the output cap without writing files; retry with strict output discipline succeeded. Orchestrator independently verified on disk: SCAFFOLD.yaml 68650 bytes, SCAFFOLD_DIFFICULTY_DESIGN.yaml 48826 bytes, SCAFFOLD_CORNER_DESIGN.yaml 50312 bytes; all parse; top-level keys correct; api_endpoints count = 63.]

## Step 3: Copy shared files — 2026-09-30T17:31:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T17:40:00.000Z

  PRD generation complete. Output: `/home/ubuntu/github/CodingPRD/tasks/task_3283_smart_licensing_device_registration_service_contract_entitlement/workspace/PRD.md` (248 lines).

  Sections: 1. Introduction; 2. Global Specifications (2.1 RBAC with per-role identity prose, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Common properties + logical clock, 2.5 Compliance posture gate, 2.6 OCC, 2.7 Uniqueness/referential integrity, 2.8 Validation ordering); 3. Business Logic (3.1 accounts/delegations, 3.2 pools & grace, 3.3 adjustments/tier upgrades, 3.4 devices/usage reports, 3.5 lifecycle milestones, 3.6 contracts/coverage, 3.7 RMA logistics, 3.8 license transfers); 4. Endpoint table (63 endpoints, 4 columns); 5. Error catalogue (21 errors, 2 columns).

  Hard contracts: Contract 1 PASS (62/62 field + input names backticked, 0 missing after fixes); Contract 2 PASS (all transitions, calculations incl. grace 90d/4h/24h/30d constants, tier proration, transfer waterfall, both OCC rules, validation priority order, applies_to scopes expressed); Contract 3 PASS (358 §3 backtick tokens scanned, 0 path/method violations).

  Confirmed: SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened, read, or referenced.

  [Orchestrator note: independently verified — PRD.md is 248 lines / 43325 bytes (dense paragraphs); all 21 error ids, all state names, and all 63 endpoint paths present verbatim in PRD. Calculation internal names absent as expected (prose formulas).]

## Step 5: Generate unit tests — 2026-09-30T18:05:00.000Z

  All verified: compile OK, tag audit clean (every tag resolves to a real instance; all 18 difficulty instances at 2 tests, all 29 corner instances at ≥1).

  Done. Summary:

  - **test_helpers/**: 9 files — `constants.py`, `types.py`, `api_errors.py` (registers 21-error HTTP map), `api_client.py` (all 47 PRD endpoints), `factories.py`, `test_users.py` (per-instance builders for entity-backed AccountAdmin/PartnerManager), `assertions.py`, `fixtures.py` (composite builders: grace-pool, covered device, open RMA, partner+delegation, approved transfer), `__init__.py` barrel.
  - **test_suite/**: conftest + 12 test files, **69 test functions total**.
  - **Coverage**: all 18 difficulty instances with exactly 2 tests each (36 difficulty-tagged tests); all 29 non-stub corner instances with ≥1 test each (33 corner-tagged tests). Every docstring carries verbatim-grep-able PRD citations + exactly one `Design:` tag matching a source YAML `name:`.
  - **Skipped instances**: none — every instance passed the PRD-first filter. Notes: the two `priority_pair_validation_conflict` instances are backed by PRD §2.8's explicit validation-ordering paragraph, so both kept as single-error assertions (no weakening); `error-precedence` did not apply anywhere.
  - `python3 -m py_compile` passes on all 22 generated files; no suite execution (no server yet).

  [Orchestrator note: independently verified on disk — test_helpers/ has 9 files, test_suite/ has conftest + 12 test files, 69 `def test_` functions, 69 `Design:` tags, all files compile.]

## Step 6: Generate implementation — 2026-09-30T18:30:00.000Z

  Done. Implementation complete and smoke-tested.

  **Files (workspace/implementation/, 2107 lines total):**
  - start.sh (8), requirements.txt (1), app.py (47)
  - store.py (38) — logical clock @ 2026-09-01T00:00:00Z + in-memory tables, no seeding
  - errors.py (57), respond.py (70) — envelope, pagination (limit/offset/total_count/has_more, sorted by created_at)
  - serializers.py (134), helpers.py (164) — auth (X-User-ID/X-User-Role), RBAC incl. partner delegation scope
  - services.py (205) — reconciled consumption, grace/OOC machine, posture rollup, contract/coverage/RMA cascades, clock sweep
  - routes/: accounts.py (163, incl. clock endpoint), partners.py (122), virtual_accounts.py (85), license_pools.py (147, OCC purchase-adjustment, tier-upgrade proration), devices.py (323, devices/usage-reports/assignments/milestones), contracts.py (168), rma.py (152, branch-aware), transfers.py (223, approve OCC + pinned execute order)

  **Smoke check:** booted via `PORT=18331 bash start.sh`; health OK; created account→VA→pool→device→activate→assignment(10 vs 5) → pool IN_GRACE with grace_deadline = overage+90d, posture GRACE, 401 without headers. Killed exact PID; server confirmed stopped.

  **Interpretation choices (PRD-ambiguous points):**
  - Grace/OOC evaluated lazily in `recompute_pool` (called on every pool mutation, pool GET, and clock advance); exactly AT deadline stays IN_GRACE.
  - Usage-report staleness raises ERR_STALE_REPORT (422) while still persisting the REJECTED report row, per scaffold validation p13 wording.
  - Transfer-execute target pool creation copies source's `subscription_expires_at`.
  - SmartAccount GET/list are not ownership-filtered for AccountAdmin reads only on list (filtered to own account); single-resource reads enforce ownership/delegation.
  - RMA close requires `delivered_at` set (replacement delivered on path) per scaffold precondition.

  [Orchestrator note: independently verified on disk — implementation/ has app.py + 6 top-level modules + routes/ with 8 modules, all compile, start.sh present with PORT/exec contract.]

## Step 7: Test-fix iteration loop — 2026-09-30T18:15:00.000Z

  All 8 rounds pass 69/69. Clean exit.

  Summary:
  - Iterations run: 2 sweeps (first: 9 stable failures in all 8 rounds; second: 69/69 × 8 rounds clean).
  - Tests deleted: none — all 9 failures were either format-silence test bugs or real implementation bugs.
  - Fixes applied to `test_helpers/`:
    - `assertions.py` — added `assert_ts_equal(actual, expected, msg)` which parses both ISO 8601 strings and compares instants. PRD §2.4 fixes three-fractional-digit rendering only for `created_at`/`updated_at`/`api_request_timestamp`; exact-string equality on other server-stamped timestamps is not uniquely derivable from PRD (both `Z` and `.000Z` renderings satisfy it).
  - Fixes applied to `test_suite/` (all replacing exact-string timestamp equality with `assert_ts_equal`; no assertion weakened semantically):
    - `test_02_device_lifecycle.py` — `test_reregister_refreshes_registered_at` (`registered_at`/`last_sync_at`).
    - `test_03_rma_logistics.py` — `opened_at`/`ship_by` in the ADVANCE_4H, ADVANCE_NBD, and advance-branch tests.
    - `test_04_compliance_cascades.py` — `grace_deadline` in `test_pool_in_grace_exactly_at_deadline`.
    - `test_10_state_preconditions.py` — `grace_deadline` in `test_expiry_zeroes_effective_entitlement_and_enters_grace`.
    - `test_11_envelope_and_consistency.py` — `registered_at`/`covered_from` in `test_default_clock_stamps_server_timestamps`.
  - Fixes applied to `implementation/`:
    - `services.py` `latest_accepted_reports()` — tiebreak on `(reported_at, created_at)` collapsed when logical clock didn't advance between equal-timestamp reports (identical `created_at`), so the first report won instead of the latest; added an insertion-sequence tiebreak with `>=` so the latest accepted report wins on full ties (PRD §3.2 "the device's own reported line quantity ... replaces whatever its assignments would otherwise imply", latest accepted wins).
    - `routes/transfers.py` `approve_transfer()` — `require_roles("PlatformAdmin","AccountAdmin")` fired `ERR_FORBIDDEN` for PartnerManager before the self-approval check, making line-121's `ERR_SELF_APPROVAL_FORBIDDEN` unreachable; restructured to admit PartnerManager past the role gate and raise `ERR_SELF_APPROVAL_FORBIDDEN` when approving a partner-initiated request (PRD §3.8 verbatim), `ERR_FORBIDDEN` otherwise.

  [Orchestrator note: Step 7 edited implementation/ during the loop, so per protocol I re-ran the full 8-round sweep MYSELF after the subagent exited. Independent result: 69/69 passed, 0 failed, in ALL 8 rounds. Clean sweep confirmed against on-disk code.]

## Step 8: Finalize PRD — 2026-09-30T18:20:00.000Z

  Done. PRD_FINALIZED.md written at `workspace/PRD_FINALIZED.md`.

  **Line counts:** PRD.md 248 lines, PRD_FINALIZED.md 248 lines (0% line-count delta; 3 lines revised in place).

  **Changes (one per step_7_diff theme):**
  - §2.4 — revise — added sentence: only `created_at`/`updated_at`/`api_request_timestamp` require exactly three fractional digits; all other server-stamped timestamps are ISO 8601 renderings of the instant and equivalent renderings (e.g. `Z` vs `.000Z`) are interchangeable — respond.py:18-21 (`iso()`), serializers.py (all `iso()` fields).
  - §3.4 — insert — added sentence pinning the latest-accepted-report tie-break: max `reported_at`, and on equal `reported_at` the most recently submitted accepted report wins — implementation/services.py:59-73.
  - §3.8 — revise — split the partner-approval rejection: partner approving a partner-initiated request → `ERR_SELF_APPROVAL_FORBIDDEN`; partner approving a non-partner-initiated request → `ERR_FORBIDDEN` — implementation/routes/transfers.py:117-120.

  **Per-edit pre-edit search log:**
  1. Timestamp rendering: (a) subject = fractional-digit/exact-rendering scope of server-stamped timestamps; (b) read/grepped respond.py, serializers.py, store.py, helpers.py:12-21, routes/devices.py:184-240, routes/accounts.py, test_suite 02/03/04/10/11; (c) wording scoped to "server-stamped timestamps other than created_at/updated_at/api_request_timestamp" and explicitly allows both renderings.
  2. Latest-report tie-break: (a) subject = definition of a device's "latest accepted report" under equal `reported_at`; (b) only consumer is services.py:78 (`recompute_pool`); read devices.py:216-233 staleness check (strict `<`, unaffected); (c) placed rule as "for the reconciled consumption of §3.2".
  3. Partner approval split: (a) subject = error surfaced when PartnerManager calls approve; (b) read transfers.py approve/reject/cancel + helpers.py `authorize_resource`; (c) added the `ERR_FORBIDDEN` branch for non-partner-initiated requests.

  No other step_7_diff items required PRD edits.

  [Orchestrator note: independently verified diff PRD.md vs PRD_FINALIZED.md — exactly 3 lines revised in place, matching the three reported edits (§2.4 timestamp rendering, §3.4 latest-report tie-break, §3.8 partner-approval error split). 248→248 lines, 43325→44029 bytes.]

## Step 9: Complete PRD — 2026-09-30T18:35:00.000Z

  Done. PRD_COMPLETED.md written as a minimal inline patch over PRD_FINALIZED.md, aligned endpoint-by-endpoint to implementation/.

  - Source: PRD_FINALIZED.md (248 lines, 44029 chars) -> PRD_COMPLETED.md (248 lines, 49407 chars; +5378 chars, 0 new lines/sections — all edits are in-paragraph inserts).
  - Counts: 15 ambiguity-pins, 3 mismatch-revisions.

  Changes:
  - §2.1 — insert — ambiguity — PartnerManager read rule = any ACTIVE delegation regardless of scope; visibility filters for smart-account list, delegation list, transfer list — helpers.py:132-157, accounts.py:59-67, partners.py:78-95, transfers.py:57-93.
  - §2.2 — insert — ambiguity — clock-set endpoint returns 200 with empty `data` object — routes/accounts.py:21-29.
  - §2.3 — insert — ambiguity — non-integer/out-of-range limit/offset rejected with ERR_INVALID_REQUEST — respond.py:45-62.
  - §2.4 — insert — ambiguity — version also increments on lazy-evaluation side effects (pool grace expiry, contract expiry, sla_breached flip); request-body timestamps parsed as ISO 8601 with offsetless = UTC, invalid -> ERR_INVALID_REQUEST — services.py:101-112,153-181; helpers.py:12-21.
  - §2.4 — revise — mismatch — clock endpoint sets (not monotonically advances) the clock; backward sets are legal and re-evaluate all time-dependent state — routes/accounts.py:26-28.
  - §2.8 — insert — ambiguity — endpoint role allowlist checked before all else; ownership/delegation ERR_FORBIDDEN evaluated after path/body existence and body-shape checks, before state/business checks — helpers.py:83-85.
  - §3.1 — insert — ambiguity — managing_partner_id must reference an existing partner org (ERR_NOT_FOUND) — routes/accounts.py:42-43.
  - §3.1 — insert — ambiguity — suspension also blocks pool purchase-adjustment/tier-upgrade and contract creation; closure "touching" transfers = source pool or target VA in account — license_pools.py:41,84,104; contracts.py:38-39; accounts.py:116-120.
  - §3.2 — insert — ambiguity — pool recompute also happens lazily on individual pool read — routes/license_pools.py:68.
  - §3.2 — insert — ambiguity — subscription_expires_at is optional (PERPETUAL pool may carry it; no effect) — routes/license_pools.py:39.
  - §3.3 — insert — ambiguity — tier-upgrade credit is zero when total subscription length floors to zero days — routes/license_pools.py:112-115.
  - §3.4 — insert — ambiguity — assignment creation requires REGISTERED device (ERR_INVALID_STATE) and same virtual account as pool (ERR_INVALID_REQUEST) — routes/devices.py:258-261.
  - §3.4 — insert — ambiguity — report lines non-empty, non-negative integer quantities; nonexistent line pool -> ERR_NOT_FOUND; only stale reports persisted REJECTED — routes/devices.py:191-233.
  - §3.4 — insert — ambiguity — report from non-REGISTERED device -> ERR_INVALID_STATE; accepted report sets last_sync_at to logical clock — routes/devices.py:206-207,235.
  - §3.6 — insert — ambiguity — contract cancel and coverage release precondition failures are ERR_INVALID_STATE — routes/contracts.py:75-81,161-165.
  - §3.7 — insert — ambiguity — RMA row initializes delivered_at unset (not serialized) — routes/rma.py:52.
  - §3.7 — revise — mismatch — confirm-delivery requires REPLACEMENT_SHIPPED; depot-window breach applies only to advance branches; reverse-order attempts are ERR_RMA_BRANCH_VIOLATION; close requires delivered_at; lazy sla_breached on RMA-case lists increments version — routes/rma.py:92-139; services.py:160-181.
  - §3.8 — revise — mismatch — execute rejects archived target VA with ERR_INVALID_STATE; target smart account not ACTIVE -> ERR_ACCOUNT_NOT_ACTIVE; new target pool copies subscription_expires_at from source — routes/transfers.py:185-189,219.
  - §4 — insert — ambiguity — partner-orgs/{id}: PartnerManager may read only its own organization — routes/partners.py:35-36.

  [Orchestrator note: verified on disk — PRD_COMPLETED.md 248 lines / 49301 bytes, 34 changed lines vs PRD_FINALIZED.md, all in-paragraph. mtime check: 0 .py files under implementation/, test_suite/, or test_helpers/ are newer than results.8.json — the independently-verified 8×69/69 clean sweep remains valid against current code.]

## Pipeline complete — 2026-09-30T18:36:00.000Z

Final state: 69 tests × 8 parallel rounds all passing under per-test-server isolation; PRD.md → PRD_FINALIZED.md (3 pins) → PRD_COMPLETED.md (15 ambiguity-pins + 3 mismatch-revisions). Task directory contains SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (12 files + conftest), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.1-8.json}.
