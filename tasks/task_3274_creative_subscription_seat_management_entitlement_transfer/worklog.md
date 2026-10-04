# Worklog — task_3274_creative_subscription_seat_management_entitlement_transfer

## Step 1: Create Task Directory — 2026-09-30T16:30:00.000Z

Pre-allocated task directory `./tasks/task_3274_creative_subscription_seat_management_entitlement_transfer/` verified to exist with `workspace/` inside (per command-args instruction; no new index computed).

## Step 2: Generate Scaffold — 2026-09-30T17:06:30.000Z

The directory already contained `worklog.md` and `workspace/` from the pipeline harness — I left those untouched. All three required artifacts are written and lint-clean.

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3274_creative_subscription_seat_management_entitlement_transfer/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Counts:**
- Endpoints: 87 (incl. `POST /licensing/_clock/set_current_utc` test-driving clock with the mandated 2026-09-01T00:00:00Z default)
- Entities: 17 (Organization, Admin, EndUser, Reseller, Plan, Subscription, Seat, Device, Entitlement, DeploymentPackage, ProductVersion, AddOnService, Asset, TransferRequest, ResellerOrder, ComplianceAudit, CancellationRequest)
- State machines: 13 (incl. cyclic Seat reclaim loop, branching EndUser departure fork, SoD-guarded TransferRequest and DeploymentPackage approval chains, parallel posture computation on Organization)
- Calculations: 8 (ETF tiered pricing, per-seat-floor-then-multiply monthly charge, org storage pool, 4-way precedence compliance posture, sum-then-ceil user storage, add-on overage waterfall, default version projection, reseller routing selector)
- Validations: 24 (priorities 1–24 spanning auth → existence → state → safety → constraint → temporal → referential → fiscal)
- Errors: 26; Roles: 5 (SystemAdmin opaque; OrgAdmin/DeploymentAdmin entity-backed Admin; ResellerAgent entity-backed Reseller; EndUser entity-backed EndUser)
- Concurrency rules: 2 OCC rules (`seat-mint-stale-subscription`, `transfer-request-stale-seat`), both with `${var}`-bound `expected_*_version` payloads
- §1.8 difficulty instances: 18 (9 rules × 2, all with falsifiable distinguishing aspects, structured setup chains, and pre-computed literal asserts — e.g. ETF 148715¢, PLATINUM charge 42490¢, GOLD 21596¢ vs direct 23996¢, sum-then-ceil 3 GB vs per-line 4 GB)
- §1.9 corner instances: 41 across all 9 guide sections (39 with full recipes + 2 excluded-because stubs referencing §1.8 instances)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (602 calls scanned, 0 violations)

**Design notes:** the rolling-entitlement model (each activation below the device cap spawns the next PENDING_ACTIVATION entitlement) makes the device-cap boundary testable end-to-end; compliance FROZEN was made API-reachable by defining it as "audit in FINDINGS_RAISED with findings_count > 0" since seats_assigned can never legally exceed seats_purchased; package approve/reject was moved from opaque SystemAdmin to entity-backed OrgAdmin so the segregation-of-duties check can compare real admin ids.

## Step 3: Copy Shared Files — 2026-09-30T17:07:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3274_creative_subscription_seat_management_entitlement_transfer/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T17:35:00.000Z

NOTE: the first subagent invocation exited after emitting only a plan (PRD.md missing on disk); orchestrator resumed the same agent via SendMessage, which then wrote the file. Verbatim summary from the completing run follows.

**Output:** `workspace/PRD.md` — 385 lines, ~57 KB. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened.

### Section map
- **§1. Introduction** — 2 paragraphs, business-context angle
- **§2. Global Specifications** — 10 subsections: 2.1 RBAC (5 roles with entity-backed/opaque identity prose), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Logical Clock & Scheduled Sweeps (initial `2026-09-01T00:00:00Z`, all 5 sweep types), 2.5 Common Resource Properties (UUID `id`, ISO 8601 `created_at`/`updated_at`, `version`), 2.6 Monetary Precision (integer cents, per-seat floor vs sum-then-ceil disciplines), 2.7 OCC (`expected_subscription_version` + `expected_seat_version` → `ERR_STALE_VERSION`/412), 2.8 Validation Ordering (all 24 priorities in order), 2.9 Compliance Posture (FROZEN > OVER_ALLOCATED > UNDER_AUDIT > COMPLIANT precedence), 2.10 Segregation of Duties
- **§3. Business Logic** — 11 subsections (orgs/admins/users/devices; plans & versions; reseller routing; subscription lifecycle; cancellation & ETF; seats; entitlements; deployment packages; add-ons & metering; assets & offboarding; compliance audits)
- **§4. Endpoint Definitions** — 87/87 rows, 4-column table
- **§5. Error Code Catalogue** — 26/26 rows, 2-column table

### Hard contract reports
- **Contract 1 (Field coverage):** 79 required, 79 present, 0 missing — PASS (one gap, `availability`, found and repaired)
- **Contract 2 (Rule coverage):** all 24 validations expressed in §2.8 priority order plus trigger-prose near workflows; both OCC rules named with endpoint + field + error_id + 412; all 13 state machines' transitions/preconditions/side-effects rendered (including cascades and sibling branches — TRANSFERRING→ASSIGNED has both reject/expiry and execute paths with equal density); all 8 calculations in precise prose (ETF floor formula with month-anniversary rule; per-seat-floor-then-multiply charge with 5/10/15 tier discounts; storage pool incl. PAST_DUE counting and 1 GB-per-unit cloud add-ons; posture precedence; sum-then-ceil user storage at 1024 MB/GB; waterfall overage metering; default-version projection with release_date DESC / created_at ASC tie-break; reseller waterfall with tier > open-orders > created_at ranking) — PASS
- **Contract 3 (§3 path purity):** 510 backtick tokens scanned in §3, 0 paths / 0 bare methods / 0 method+path combos — PASS

Mechanical verifications: 87/87 endpoints present in §4 table, 26/26 error IDs in §5, all 5 role names and every state enum value present verbatim, every validation's error_id appears in §2/§3 prose (not only the table).

## Step 5: Generate Unit Tests — 2026-09-30T17:55:00.000Z

NOTE: launched alone (not concurrently with Step 6) per command-args — this model endpoint duplicates parallel tool calls, so Steps 5/6 ran strictly sequentially.

**Files written**

**test_helpers/ (9 modules):** `types.py` (22 status/role enums + 17 entity TypedDicts), `api_client.py` (~70 methods, one per SCAFFOLD endpoint), `api_errors.py` (26-error enum + HTTP map), `assertions.py`, `constants.py` (discount tiers, month constants, 24h reclaim grace, 72h transfer expiry, clock default, 1024 MB/GB), `factories.py`, `test_users.py` (shared constants + per-instance builders), `fixtures.py` (bootstrap org/admin pattern, org+plan+version+active-subscription composites, assigned-seat/activated-entitlement/transfer/cancellation/asset/add-on/audit helpers with identity threading), `__init__.py`.

**test_suite/ (12 files):** conftest.py + 11 test files.

**Test counts**
- Total: 75 tests (py_compile clean on every file)
- Queue A (Difficulty): 36 tests — all 18 instances × 2 tests each
- Queue B (Corner): 39 tests — all 39 non-stub instances × 1 test each

**Skipped instances**
- `Corner/state_machines/seat_reclaim_grace_boundary` — excluded_because stub (owned by difficulty instance `device_cap_at_limit_vs_limit_plus_one`)
- `Corner/validations/stale_version_occ_conflict` — excluded_because stub (owned by `seat_assign_reclaim_cancel_reassign_cycle` / `occ_stale_version_returns_412`)
- No PRD-filter skips needed.

**Notable adjudications**
- `device_cap_at_limit_vs_limit_plus_one`: recipe depends on a "fresh PENDING_ACTIVATION entitlement spawns when the previous reaches ACTIVE" rule the PRD never states; tests avoid the spawn dependency and use `validate_error_is_one_of([ERR_DEVICE_LIMIT_EXCEEDED, ERR_INVALID_STATE])`.
- `frozen_org_blocks_before_capacity_check`: FROZEN requires over-allocation, unreachable through public writes; tests assert rejection with frozen-or-capacity semantics.
- `computed_read_org_posture_after_findings`: FROZEN assertion not PRD-derivable; test asserts PRD-pinned UNDER_AUDIT-with-findings.
- Entitlement activation against another user's device uses `validate_error_is_one_of` (PRD covers the rule but not the exact error id).

Final audit: every test docstring ends with exactly one `Design:` tag resolving to a real instance, carries a verbatim (grep-verified) PRD quote, no skip/xfail markers anywhere. Orchestrator verified on disk: 9 test_helpers modules, 12 test_suite files, 75 `def test_`, 57 unique Design tags, py_compile OK.

## Step 6: Generate Implementation — 2026-09-30T17:45:00.000Z

**Files written** (in `workspace/implementation/`):
- `start.sh` — guarded pip install (no-op once flask importable), `exec python3 app.py`, PORT env / 0.0.0.0 / foreground
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app, error handlers (envelope-shaped 404/405/generic), the `/licensing/_clock/set_current_utc` endpoint, blueprint registration, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dicts for all 17 entities + logical clock initialized to `2026-09-01T00:00:00Z`, no seeding
- `errors.py` — all 26 PRD error IDs with exact HTTP statuses
- `response.py` — exact success/error envelope (`meta.api_request_id` `req_*`, `api_request_timestamp`, `response_type`, `data`; list pagination fields `limit/offset/total_count/has_more`, default 10, min 1, max 100); logical-clock ISO helpers incl. month arithmetic
- `middleware.py` — priority-1 header check (`X-User-ID`/`X-User-Role`, 5 roles), priority-2 role authorization, priority-3 entity-backed identity (Admin kind gates OrgAdmin vs DeploymentAdmin; EndUser/ResellerAgent resolve to their entities; SystemAdmin opaque), org-scoping helper
- `helpers.py` — calculations: monthly_billed_charge (per-seat floor → ×seats, tier discounts 5/10/15), early_termination_fee (monthly anniversaries, floor), org_storage_pool (ACTIVE subs incl. seats; PAST_DUE excluded per literal formula + CLOUD_SERVICES ACTIVE/EXHAUSTED add-ons), org_compliance_posture (FROZEN > OVER_ALLOCATED > UNDER_AUDIT > COMPLIANT), user_storage_used (sum MB then ceil /1024), default_product_version (release_date DESC, created_at ASC), cascade helpers and the 4 system sweeps (billing, commitment expiry for ANNUAL_PREPAID, transfer expiry, metering/forced-upgrade retirement)
- `routes_orgs.py` — organizations, admins, end users (incl. deactivate/reactivate/mark-departed cascades with 24h grace), devices
- `routes_plans.py` — plans, product versions (deprecate/restore/force-upgrade with ERR_NO_AVAILABLE_VERSION and ERR_DEADLINE_NOT_FUTURE), resellers (suspend/reinstate)
- `routes_subscriptions.py` — subscriptions (create/activate mints seats/settle), seats (OCC mint, assign with all 6 preconditions, reclaim/cancel/finalize), entitlements (activate with device cap + forced-upgrade migration)
- `routes_transfers.py` — transfer requests (OCC `expected_seat_version`, SoD, 72h expiry, execute resetting entitlement to PENDING_ACTIVATION), cancellation requests (in-window REFUNDED / annual ETF_CHARGED with fee / MONTHLY out-of-window ERR_MONTHLY_NO_ETF / else DENIED)
- `routes_addons.py` — add-on services (consume waterfall, top-up EXHAUSTED→ACTIVE, cancel), assets (transfer/accept/cancel/claim/purge with audit freeze), deployment packages (submit/approve/reject/publish/retire with SoD, deployment-mode and offline-activation checks, FROZEN block)
- `routes_billing.py` — reseller orders (waterfall routing: tier PLATINUM>GOLD>CERTIFIED → fewest ROUTED → created_at ASC; discount_pct 5/10/15; fulfill/reject/cancel), compliance audits (open/raise-findings/remediate/close with posture recompute)

**Endpoint count:** 87 total — 86 `@bp.route` decorators + 1 `@app.post` (clock), matching the 87 endpoints in the PRD table (grep-verified).

**Compile:** `python3 -m py_compile` passes on all 12 .py files.

**Boot check:** `bash start.sh` with `PORT=18342` booted cleanly; verified live responses — unauthenticated list → 401 `ERR_UNAUTHENTICATED` envelope, missing org → 404 `ERR_NOT_FOUND` envelope, clock set → 200 with `current_utc`, org create → 201 with computed `storage_pool_gb`/`compliance_posture`/`version`. Only the exact PIDs started by the test were killed; ports are free afterward.

Orchestrator verified on disk: 14 files present, 87 route decorators grep-counted, py_compile OK on all.

## Step 7: Run Tests and Iterate — 2026-09-30T17:50:00.000Z

**Iterations run:** 2 sweeps (first exposed collection failure + 2 deterministic failures; second passed clean).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added missing `get_transfer_request(tr_id)` convenience wrapper (uses `SYS` headers, returns `get_success_data`), mirroring the existing `get_seat`/`get_subscription`/etc. pattern. Its absence caused collection-time `ImportError` in test_04/07/09. PRD covers the endpoint at line 313 (`GET /licensing/transfer-requests/{id}`).

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_validation_and_dependency.py` — removed the bogus `list_transfer_requests` import from the `test_helpers` import block. The only in-file use was `api.list_transfer_requests(...)` (an `ApiClient` method, not a helper), so the import itself was dead and unsatisfiable.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_transfers.py` (`approve_transfer_request`, `reject_transfer_request`): on the non-`PENDING_APPROVAL` path, added SoD and expiry precedence checks before falling through to `ERR_INVALID_STATE`. PRD §2.8 places SoD at category 10 and transfer expiry at 17, both after target-entity state (category 6); a sweep-flipped `EXPIRED` transfer would otherwise mask the SoD violation with `ERR_INVALID_STATE`.
- `workspace/implementation/routes_subscriptions.py` (`activate_entitlement`): the forced-upgrade migration check now keys on `pv.get("forced_upgrade_deadline")` being past, regardless of current availability. The metering sweep retires `FORCED_UPGRADE → DEPRECATED` once the deadline passes with no active entitlements (PRD §178), which previously erased the migration trigger. Migration must still apply per PRD §228 ("an activation attempted after the deadline migrates to the latest available version instead").

**Final sweep result:** 8/8 rounds × 75/75 tests passed. Orchestrator verified on disk: all 8 results.N.json files report passed=75/75 failed=0; last impl edit (17:46) precedes final sweep results (17:49), so no post-sweep writes invalidated the run.

## Step 8: Finalize PRD — 2026-09-30T17:58:00.000Z

`PRD_FINALIZED.md` written with a minimal 3-site patch traced exactly to the two `implementation/` fixes in `<step_7_diff>`.

**Line counts:** PRD.md 385 → PRD_FINALIZED.md 387 (+2 lines, +0.5%).

**Changes:**
- §2.8 (Validation Ordering) — insert — scoped exception paragraph: on transfer-request approve/reject, SoD is enforced before the target-state check (self-approval/self-rejection of a non-pending request yields `ERR_SEGREGATION_OF_DUTIES`, not `ERR_INVALID_STATE`); on approve, expiry is also checked before the state fallback (`ERR_TRANSFER_EXPIRED` for a different-admin approval of a sweep-expired request); reject performs no expiry check — `implementation/routes_transfers.py:138-147` (approve), `:163-168` (reject).
- §3.6 (Transfers, approval paragraph) — revise — states that SoD (and, for approval, expiry) precede the pending-state check, cross-referencing the §2.8 exception; notes rejection has no expiry check — `implementation/routes_transfers.py:129-176`.
- §3.7 (Entitlement activation) — revise — migration trigger widened from "version is in `FORCED_UPGRADE` past its deadline" to "version carries a `forced_upgrade_deadline` the clock has reached or passed, regardless of whether the metering sweep has already retired it to `DEPRECATED`" — `implementation/routes_subscriptions.py:454-458`, `implementation/helpers.py:320-330`.

**No-edit items:** the `test_helpers/fixtures.py` `get_transfer_request` addition and the `test_04` import removal are pure fixture/test bugs; PRD line 313 already pins `GET /licensing/transfer-requests/{id}`, so no PRD change was warranted.

**Per-edit pre-edit search log:**
- **Edit 1 (§2.8 insert + §3.6 revise).** (a) Subject: error precedence on transfer-request approve/reject for non-`PENDING_APPROVAL` requests. (b) Enumerated impl paths: `routes_transfers.py:129-151` (approve: SoD → expiry → INVALID_STATE on both pending and non-pending paths), `routes_transfers.py:154-176` (reject: SoD → INVALID_STATE, no expiry check), `routes_transfers.py:179-216` (execute: unaffected, state-first), `routes_addons.py:445-477` (package approve/reject: state check *before* SoD — opposite order). (c) Wording scoped explicitly to "the transfer-request review endpoints" so the deployment-package SoD path (standard §2.8 ordering) is not mis-described; also pinned that rejection performs no expiry check, matching the impl's asymmetric handlers.
- **Edit 2 (§3.7 revise).** (a) Subject: activation-time forced-upgrade migration trigger. (b) Enumerated impl paths: `routes_subscriptions.py:454-458` (migration keyed on `pv.get("forced_upgrade_deadline")` set + `now_dt() >= deadline`, availability-agnostic), `helpers.py:320-330` (metering sweep retires `FORCED_UPGRADE → DEPRECATED` past deadline with no ACTIVE entitlements), `helpers.py:71-81` (`default_product_version` raises `ERR_NO_AVAILABLE_VERSION` when no AVAILABLE version — unchanged), `routes_subscriptions.py:291-303` (assignment-time default version — unaffected), `routes_plans.py:180-193` (force-upgrade endpoint — unaffected). Also cross-checked §3.2's migration sentence, already availability-agnostic. (c) Wording says "regardless of whether the version is still in `FORCED_UPGRADE` or the metering sweep has already retired it back to `DEPRECATED`," keeping both pre-sweep and post-sweep paths consistent without narrowing any other version-lifecycle rule.

Orchestrator verified on disk: PRD_FINALIZED.md exists, 387 lines, diff vs PRD.md shows exactly the 3 sites described.

## Step 9: Complete PRD — 2026-09-30T18:15:00.000Z

**Source vs completed:** `PRD_FINALIZED.md` 387 lines / 59,340 chars → `PRD_COMPLETED.md` 393 lines / 62,944 chars (+6 lines, +3,604 chars).

**Counts:** 15 ambiguity-pins, 4 mismatch-revisions (two edits contained both a pin and a revision; counted per distinct change).

### Change list
1. §2.1 — insert — ambiguity — pinned that an `X-User-Role` value not among the five recognized roles is rejected with `ERR_UNAUTHENTICATED` — `implementation/middleware.py:35-36`
2. §2.1 — insert — ambiguity — pinned role-to-`admin_kind` mapping (`OrgAdmin` → `SYSTEM_ADMIN`/`PRODUCT_ADMIN`, `DeploymentAdmin` → `DEPLOYMENT_ADMIN`) at identity resolution — `implementation/middleware.py:63-68`
3. §2.3 — insert — ambiguity — pinned that out-of-bounds `limit`/`offset` values draw `ERR_INVALID_REQUEST` — `implementation/response.py:148-161`
4. §2.4 — insert — ambiguity — pinned that logical-clock timestamps use second-precision ISO 8601 UTC format — `implementation/response.py:93-98`
5. §2.4 — insert — ambiguity — pinned invoice due dates: `MONTHLY` → one month after `commitment_start`; `ANNUAL_MONTHLY_BILLED` → first upcoming monthly anniversary strictly in the future — `implementation/helpers.py:284-295`
6. §2.5 — revise — mismatch — corrected `created_at` description from "three fractional digits" to second-precision — `implementation/helpers.py:27-33`, `implementation/response.py:85-98`
7. §2.5 — insert — ambiguity — pinned that recomputing a computed field to the same value does not refresh `updated_at`/`version` — `implementation/helpers.py:132-143,154-161`
8. §2.9 — insert — ambiguity — pinned that `compliance_posture` is refreshed on every organization read — `implementation/routes_orgs.py:87`
9. §3.1 — insert — ambiguity — pinned `ERR_REFERENCE_NOT_FOUND` for nonexistent `org_id` on admin creation — `implementation/routes_orgs.py:101-102`
10. §3.1 — insert — ambiguity — pinned `ERR_REFERENCE_NOT_FOUND` for nonexistent `org_id` on end-user creation, plus `ERR_IDENTITY_MISMATCH` for EndUser reading another's record, ResellerAgent reading another reseller, and OrgAdmin reading an out-of-org end user — `implementation/routes_orgs.py:148-149,194-197`, `implementation/routes_plans.py:227-229`
11. §3.1 — insert — ambiguity — pinned `ERR_REFERENCE_NOT_FOUND` for nonexistent `end_user_id` on device creation — `implementation/routes_orgs.py:292-294`
12. §3.1 — insert — ambiguity — pinned that mark-departed requires `DEACTIVATED` status, else `ERR_INVALID_STATE` — `implementation/routes_orgs.py:267-268`
13. §3.2 — insert — ambiguity — pinned `ERR_REFERENCE_NOT_FOUND` for nonexistent `plan_id` on product-version creation — `implementation/routes_plans.py:93-94`
14. §3.2 — insert — ambiguity — pinned that deprecate requires the version to be currently `AVAILABLE` — `implementation/routes_plans.py:146-147`
15. §3.3 — insert — ambiguity — pinned suspend/reinstate state guards — `implementation/routes_plans.py:241-244,256-257`
16. §3.3 — insert — ambiguity — pinned `ERR_REFERENCE_NOT_FOUND` for `org_id`/`plan_id` on order creation, and plan seat-ceiling check at order creation — `implementation/routes_billing.py:42-52`
17. §3.4 — insert — ambiguity — pinned `ERR_INVALID_STATE` when organization is not `ACTIVE` at subscription activation, and that activation mints `seats_purchased` seats — `implementation/routes_subscriptions.py:131-160`
18. §3.4 — insert — ambiguity — pinned that a `PAST_DUE` subscription contributes zero to `storage_pool_gb` — `implementation/helpers.py:84-101`
19. §3.5 — revise — mismatch — corrected monthly-out-of-window finalization: request is first marked `DENIED`, then rejected with `ERR_MONTHLY_NO_ETF` — `implementation/routes_transfers.py:334-337`
20. §3.6 — revise — mismatch — assignment transition is `UNASSIGNED → ASSIGNED` or `RECLAIMED → ASSIGNED` — `implementation/routes_subscriptions.py:276-277`
21. §3.6 — insert — ambiguity — pinned that reclaim-cancel after grace lapse is `ERR_INVALID_STATE` — `implementation/routes_subscriptions.py:346-347`
22. §3.6 — insert — ambiguity — pinned that finalize-reclaim decrements `seats_assigned` floored at zero — `implementation/helpers.py:267-269`
23. §3.6 — revise — mismatch — transfer-request creation preconditions: seat must be `ASSIGNED`, subscription not `ACTIVE` is `ERR_INVALID_STATE`, open transfer for seat draws `ERR_INVALID_STATE` — `implementation/routes_transfers.py:67-81`
24. §3.7 — insert — ambiguity — pinned error codes on entitlement activation: `ERR_IDENTITY_MISMATCH`, `ERR_INVALID_STATE`, `ERR_REFERENCE_NOT_FOUND` — `implementation/routes_subscriptions.py:425-446`
25. §3.9 — insert — ambiguity — pinned `ERR_REFERENCE_NOT_FOUND` for missing `subscription_id` on add-on creation — `implementation/routes_addons.py:45-47`
26. §3.9 — insert — ambiguity — pinned that consumption against `EXHAUSTED` leaves `quota_used` pinned at `quota_total` and against `CANCELLED` draws `ERR_INVALID_STATE` — `implementation/routes_addons.py:118-126`
27. §3.9 — revise — mismatch — top-up requires the add-on to be `EXHAUSTED` — `implementation/routes_addons.py:143-146`
28. §3.9 — insert — ambiguity — pinned `ERR_INVALID_STATE` for add-on cancel from any state other than `ACTIVE`/`EXHAUSTED` — `implementation/routes_addons.py:166-167`
29. §3.9 — revise — mismatch — storage pool: a `PAST_DUE` subscription's seats do not count — `implementation/helpers.py:84-101`
30. §3.10 — insert — ambiguity — pinned `ERR_REFERENCE_NOT_FOUND` for missing `owner_user_id` on asset creation — `implementation/routes_addons.py:184-186`
31. §3.10 — insert — ambiguity — pinned asset-transfer error codes: `ERR_IDENTITY_MISMATCH` for wrong recipient at accept, `ERR_USER_NOT_ACTIVE` for inactive recipient — `implementation/routes_addons.py:276-280`
32. §3.11 — revise — mismatch — audit `over_allocated_seats` is set to the org's current over-allocation at creation — `implementation/routes_billing.py:196-202`
33. §3.11 — insert — ambiguity — pinned `ERR_INVALID_STATE` when raise-findings finds nothing — `implementation/routes_billing.py:252-253`
34. §3.11 — insert — ambiguity — pinned `ERR_INVALID_STATE` when remediation has unresolved over-allocation, and when closing an `OPEN` audit with non-zero findings — `implementation/routes_billing.py:270-272,288-290`

Orchestrator verified on disk: PRD_COMPLETED.md exists (393 lines / 62,944 chars); no implementation .py file modified after the final clean sweep (newest impl mtime 17:46 < results mtime 17:49).
