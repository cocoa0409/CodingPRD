# Worklog — task_3275_small_business_accounting_subscription_payroll_add_advisor

## Step 1: Create task directory — 2026-09-30T16:29:00.000Z

Task directory pre-allocated by the orchestrator invocation: `tasks/task_3275_small_business_accounting_subscription_payroll_add_advisor/` with `workspace/` inside. Verified present and empty; used as-is per command args (no new index computed).

## Step 2: Generate scaffold — 2026-09-30T16:56:00.000Z

All three files are on disk and pass `scaffold_lint.py` with a clean verdict. Summary of the generated scaffold for `task_3275_small_business_accounting_subscription_payroll_add_advisor`:

**Files written (absolute paths)**
- `/home/ubuntu/github/CodingPRD/tasks/task_3275_small_business_accounting_subscription_payroll_add_advisor/SCAFFOLD.yaml` — 2433 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3275_small_business_accounting_subscription_payroll_add_advisor/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1570 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3275_small_business_accounting_subscription_payroll_add_advisor/SCAFFOLD_CORNER_DESIGN.yaml` — 1152 lines

**Lint verdict (verbatim)**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Coverage**
- 20 entities, 128 endpoints, 44 error codes, 18 ordered validations, 8 calculations, 16 state machines, 3 OCC concurrency rules, 3 roles
- §1.8: 9 rules × 2 instances = 18 difficulty instances
- §1.9: 29 corner instances across all nine guide sections (entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting / consistency), including `excluded_because` stubs for claims already exercised in §1.8

**Design decisions worth recording**
- Primary archetype: `access_control_matrix`; secondary: `pricing_engine`. Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, conditional_feature_flags, rate_threshold_triggers, derived_field_reconciliation. State-machine shape: cyclic (Subscription has ACTIVE↔SUSPENDED↔ACTIVE, CANCELLED_READ_ONLY→REACTIVATED, plus parallel `billing_status` axis).
- Pinned rounding order on payroll per-employee fee: round each daily line half-up to cents, then sum (constant 30-day divisor). Pinned evaluation order on `invoice_total`: subtotal → tax → total (post-discount subtotal is the tax base, payroll included).
- Wholesale discount capped by ProAdvisor tier (SILVER 0.20 / GOLD 0.35 / PLATINUM 0.50), computed `min(firm.wholesale_discount_pct, tier_ceiling)` — a 3-input non-linear formula for §0.5 Rule 2 mode (a).
- OCC rules pin `expected_subscription_version` on `change_plan` and `billing_transfers/{id}/accept`, and `expected_payroll_addon_version` on employee `terminate`.
- Subscription cancel cascade (depth ≥ 4): Subscription → PayrollAddon, AccessGrant, BankConnection, AppIntegration, ClientCompany, MigrationJob; then read-only window expiry → ExportRequest EXPIRED (depth 5).
- Test-driver endpoints declared per §1.5 ladder rung 3: `POST /api/_clock/set_current_utc` (default boot time `2026-09-01T00:00:00Z`), `POST /api/_payments/simulate`, `POST /api/_sync/bank_feed_tick`, `POST /api/companies/{id}/exports/{eid}/mark_ready`.
- Reconciliation window uses CLOSED-interval overlap semantics (end == other's start counts as overlap; only end+1 day is true adjacency); MigrationJob uses a state-lifetime window — the two distinct interval semantics required by §0.5 Rule 8.
- Segregation of duties: `cancel subscription`, `accept billing transfer`, and `change_plan` require `permission_level == PRIMARY_ADMIN`; COMPANY_ADMIN cannot substitute (§1.4 priority 9).
- `api_prefix: /api` was chosen after the lint pass — initially `/companies` was the top-level resource path and made FK reverse-reachability undetectable; final scaffold uses `/api` with flat per-entity canonical single-resource GETs (e.g. `GET /api/subscriptions/{id}`) plus nested sub-resource GETs under `/api/companies/{id}/...` so both lookup styles exist.
- Endpoint count grew from 105 → 128 after adding flat filtered-list GETs (`/api/subscriptions`, `/api/bank_transactions`, `/api/access_grants`, etc.) to satisfy lint check (f) FK reverse-reachability.

Orchestrator verification: `wc -l` confirms all three files on disk (2433 / 1570 / 1152 lines); `grep -c "path:"` on SCAFFOLD.yaml = 128 endpoint paths. Note: endpoint count (128) is well above the >40 threshold known to risk Step 6 impl-gen report drift — Step 6 output will be verified on disk before proceeding.

## Step 3: Copy INSTRUCTION.md — 2026-09-30T16:56:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_3275_small_business_accounting_subscription_payroll_add_advisor/workspace/INSTRUCTION.md` (1424 bytes, verified with ls).

## Step 4: Generate PRD — 2026-09-30T17:06:00.000Z

All three hard contracts now pass. Final state:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3275_small_business_accounting_subscription_payroll_add_advisor/workspace/PRD.md` — 390 lines.

**Section outline**
- §1 Introduction (2 paragraphs: commercial framing + the two design commitments of pinned money and delegated authority)
- §2 Global Specifications: 2.1 RBAC (headers, three roles with entity-backed vs opaque identity prose, permission levels, grant-level authorization), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1–100, offset 0, created_at ascending, all filter param names enumerated), 2.4 Resource Identity & Change Tracking (UUID, `updated_at`/`version`, and the explicit absence of both on `SubscriptionPlan` and `Category`; left-to-right path validation), 2.5 Monetary Precision & Tax (integer cents, half-up, US 0% / UK 20% / EU 21%), 2.6 OCC (all three rules with `expected_subscription_version` / `expected_payroll_addon_version` → `ERR_STALE_VERSION` 412), 2.7 Logical Clock & Simulation Drivers (boot time 2026-09-01T00:00:00Z, clock/payment/bank-tick drivers), 2.8 Reference Data & Derived Values, 2.9 Validation Order (all 18 priorities in explicit sequence)
- §3 Business Logic (11 subsections): 3.1 plans/catalog, 3.2 company onboarding & seats, 3.3 subscription lifecycle, 3.4 payroll, 3.5 invoicing/pricing/wholesale, 3.6 bank feeds & categorization, 3.7 reconciliation, 3.8 integrations & conflicts, 3.9 migration, 3.10 advisor channel (firms/grants/transfers), 3.11 exports
- §4 Endpoint table — 128 rows, 4 columns, exact set match to scaffold
- §5 Error catalogue — 44 rows, 2 columns, exact match to scaffold

**Hard contract results**
- Contract 1 (field coverage): 129 required identifiers (entity fields + endpoint inputs), 0 missing; all 49 state values and all 69 enum values present; all 44 error IDs present.
- Contract 2 (rule coverage): all 8 calculations rendered in precise prose (wholesale price with tier ceilings 0.20/0.35/0.50, day-by-day payroll proration with round-per-line-then-sum and 30-day divisor, invoice tax-after-discount order, recon difference with projected-vs-locked variants, tax-filing-status decision chain, seat boundary strict-greater-than, rule selector with priority-then-created_at tiebreak, proforma price chain); all 3 OCC rules named with write action, OCC field, error, and 412; all validation priorities expressed as an explicit ordering; all state-machine transitions and cascades (suspend/cancel/reactivation) covered.
- Contract 3 (§3 path purity): 587 backtick tokens scanned in §3, zero path/method violations — endpoints referenced only by state-pair framing, role+verb, or capability description.

**Zero-silence decisions** (pinned so tests derive uniquely)
- Reconciliation windows stated as closed at both ends with the explicit consequence that `end == other.start` counts as overlap and true adjacency requires starting the day after.
- Payroll proration rounding pinned as round-each-daily-line-half-up-then-sum, with the 30-day divisor fixed regardless of month length, and the provisional-vs-final invoice discrepancy explicitly acknowledged.
- Billing-transfer initial state pinned to `PENDING_CLIENT_ACCEPT` (the scaffold's declared initial state) rather than direction-dependent.
- Integration auto-pause at exactly 3 unresolved conflicts, with the asymmetric no-auto-resume rule stated.
- `SubscriptionPlan` and `Category` explicitly declared to lack `updated_at` and `version`.
- Billing-transfer expiry rejection pinned to `ERR_TRANSFER_EXPIRED`; grant-accept and export-download window expiries pinned to `ERR_WINDOW_EXPIRED`; reactivation-window expiry to `ERR_REACTIVATION_WINDOW_EXPIRED`.
- Trial-collapse, suspension, and cancel cascades enumerated exhaustively (payroll, grants, connections, integrations with preserved `conflict_count`, company status, migration jobs, upgrade prompt).

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

Orchestrator spot-check: verified on disk — PRD.md is 390 lines; grep confirms 78 `ERR_` mentions and verbatim pins for OCC (`expected_subscription_version` → `ERR_STALE_VERSION` 412), the 18-priority validation order, transfer initial state `PENDING_CLIENT_ACCEPT`, and tier ceilings 0.20/0.35/0.50 in the proforma pricing prose.

## Step 5: Generate unit tests — 2026-09-30T17:14:00.000Z

All files written and verified. Final summary:

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_3275_small_business_accounting_subscription_payroll_add_advisor/`):

*test_helpers/* (2,746 lines):
- `__init__.py` (11) — barrel export
- `types.py` (504) — entity TypedDicts + status enums (SubscriptionPlan/Category correctly carry only `id`+`created_at`, no `version`/`updated_at`)
- `api_client.py` (895) — one method per PRD §4 endpoint incl. clock/payment/bank-feed drivers
- `api_errors.py` (142) — error IDs + HTTP status map, registered with framework
- `assertions.py` (260) — per-entity assertions
- `factories.py` (377) — payload factories (input fields only)
- `constants.py` (77) — discount ceilings, payroll rate card, tax rates, pagination
- `test_users.py` (66) — PlatformAdmin opaque shared header + per-instance `make_company_user_headers` / `make_accountant_user_headers` builders for entity-backed roles
- `fixtures.py` (414) — phased setup builders: clock, plan/firm/company/user creation, active-subscription composite, payroll/employees, bank connections/categories/rules, billing-transfer handoff, access-grant issue+accept, recon start/complete, drive-to-suspended, cancel

*test_suite/* (2,668 lines):
- `conftest.py` (10) — exposes `client`/`api` fixtures
- `test_01_dual_variant_pricing.py` (168) — 2 tests
- `test_02_combinatorial_pricing.py` (222) — 4 tests
- `test_03_non_linear_state_machines.py` (218) — 4 tests
- `test_04_transitive_cascades.py` (254) — 4 tests
- `test_05_validation_priority.py` (180) — 4 tests
- `test_06_boundary_precision.py` (228) — 4 tests
- `test_07_cross_entity_state.py` (240) — 4 tests
- `test_08_resource_overlap.py` (192) — 4 tests
- `test_09_compensating_invariants.py` (255) — 4 tests
- `test_10_entities.py` (291) — 10 tests
- `test_11_state_machines.py` (152) — 4 tests
- `test_12_calculations.py` (108) — 2 tests
- `test_13_validations.py` (136) — 4 tests
- `test_14_endpoints.py` (150) — 3 tests
- `test_15_errors.py` (72) — 1 test
- `test_16_rbac.py` (109) — 2 tests
- `test_17_cross_cutting.py` (173) — 3 tests

**Test counts:**
- Queue A (Difficulty): 36 tests — 9 rules × 2 instances × 2 tests each, all instances covered ≥2x.
- Queue B (Corner): 29 tests — every non-stub instance covered exactly 1x.
- Total: 65 tests.

**Instances skipped:** 5 `excluded_because:` stubs (3 in calculations, 2 in validations). Each stub's `difficulty_instance` cross-reference resolves to a covered queue-A instance or to another corner instance (e.g. `invalid_enum_excluded` → covered by `plan_create_with_out_of_enum_feature_value_rejected`). No freelance tests added.

**Tag audit:** All 65 tests carry exactly one valid `Design:` line. A verification script cross-checked every tag against the source YAMLs — 36 Difficulty tags all match real `(rule_id, instance.name)` pairs and 29 Corner tags all match real `(section, instance.name)` pairs. No untagged, dual-tagged, or dangling tags.

**Collection check:** `pytest --collect-only` collects 65 tests with no import errors.

Orchestrator verification: `wc -l` confirms all 9 test_helpers files + 18 test_suite files on disk (5,904 lines total); grep counts 65 `Design:` tags and 65 `def test_` functions — 1:1.

## Step 6: Generate implementation — 2026-09-30T17:52:00.000Z

Done. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3275_small_business_accounting_subscription_payroll_add_advisor/workspace/implementation/`):

- `start.sh` (13 lines) — guarded pip install, `exec python3 app.py`, PORT env, 0.0.0.0
- `requirements.txt` (1) — flask
- `app.py` (62) — Flask app, ApiError/404/405 handlers, blueprint registration
- `db.py` (95) — in-memory TABLES dict, logical clock (boots at 2026-09-01T00:00:00Z), UUID/timestamp/version helpers
- `errors.py` (246) — all 40 error IDs with exact HTTP statuses
- `helpers.py` (177) — body/enum/datetime parsing, pagination (limit/offset/total_count/has_more), filters
- `auth.py` (70) — X-User-Role/X-User-ID headers, PlatformAdmin opaque, CompanyUser/AccountantUser entity-backed identity, access-grant lookup
- `serializers.py` (290) — wire shapes; SubscriptionPlan and Category omit updated_at/version per PRD §2.4
- `services.py` (240) — wholesale pricing with tier ceilings (ROUND_HALF_UP), day-by-day payroll proration (round-per-line-then-sum, /30 divisor), invoice totals (discount → subtotal → tax), payroll_tax_filing_status pinned order, rule selector (priority ASC, created_at tiebreak), recon cleared/difference (projected vs locked variants), transfer proforma
- `routes/` — 16 modules: sim (clock/payments/bank-feed drivers + full time-driven re-evaluation), plans, firms (suspend cascade, close preconditions), companies (auto-provisions TRIAL subscription), users (seat limit boundary `occupied+1 > max_seats`, pending_upgrade_prompt), subscriptions (activate/change_plan OCC/cancel cascade/reactivate/resume), payroll, invoices, bank (connections, transactions, categorization flows), rules (tier-gated, re-evaluates UNCATEGORIZED), recons (closed-interval overlap, difference==0 gate, completion cascade to MATCHED_RECONCILED), integrations (conflict_count ≥ 3 → CONFLICT_PAUSED, asymmetric resume), migrations (one-in-flight, limitation codes), transfers (counter/firm-accept, proforma, OCC), grants, exports, flat (19 FK reverse-reachability GETs)

**Endpoint coverage**: all 128 scaffold endpoints implemented (65 nested/action routes + 19 flat-list pairs + 3 simulation drivers + plans/firms/companies CRUD etc.).

**Boot check**: started via `PORT=18755 bash start.sh` (PID 4183459), exercised plan create → company create (auto-TRIAL sub) → user invite/accept → subscription activate (anchor_day, first invoice ISSUED) → payroll addon + employee → bank connection authorize → category → rule → transaction ingest (auto-categorized by rule) → subscription cancel (full cascade: payroll CANCELLED, connection DISCONNECTED, READ_ONLY company, 365-day window) — all returned correct envelopes and statuses. Killed exactly PID 4183459; confirmed stopped.

Orchestrator verification (endpoint count was 128, well above the drift threshold — verified on disk): `ls` confirms 26 files (4,006 lines); grep counts exactly **128** `@bp.(get|post|patch|put|delete)(` route handlers across `routes/` (120 unique paths — difference from 128 is multi-method decorators on shared paths), matching the scaffold's 128 endpoints 1:1.

## Step 7: Test/iterate loop — 2026-09-30T18:52:00.000Z

Clean. Final sweep state is 8/8 rounds at 64/64 with zero failures.

**Iterations run:** 11 sweeps (8-round parallel each), converging from 14 deterministic failures to a clean 8×64/64.

**Tests deleted (1):**
- `test_stale_connection_blocks_recon_start` (test_suite/test_07_cross_entity_state.py) — unique-derivability collapse. PRD §3.7 pins recon-start preconditions to window hygiene only; PRD §3.6 says a STALE connection "halts ingestion of new transactions," not reconciliation. A faithful PRD-only reader can implement recon start without a connection-state gate (as the twin `test_active_connection_allows_recon_start`, which shares the same `Design:` tag and passed throughout, confirms). Scaffold rule `cross_entity_state_dependency/recon_start_blocked_by_bank_connection_stale` drove the test's generation but never made it into PRD prose.

**Tests relaxed (2):**
- `test_payroll_addon_requires_valid_subscription_fk` (test_10_entities.py) — relaxed exact `ERR_NOT_FOUND` to `validate_error_is_one_of([ERR_IDENTITY_MISMATCH, ERR_NOT_FOUND])`. PRD 2.9's priority order places identity resolution (priority 3) before body-FK existence (priority 5), and the test cross-company request trips both; PRD names both errors without pinning the winner for this overlap.
- `test_terminate_under_suspended_subscription_rejected` (test_07_cross_entity_state.py) — relaxed exact `ERR_SUBSCRIPTION_NOT_WRITABLE` to one-of `[ERR_SUBSCRIPTION_NOT_WRITABLE, ERR_PAYROLL_NOT_ACTIVE]`. PRD 3.4 pins `ERR_PAYROLL_NOT_ACTIVE` for "any payroll-employee operation against a non-active add-on" (the suspension cascade moves the add-on ACTIVE→PAUSED), while the SUSPENDED-specific writability error is scaffold-only.

**Fixes applied to `test_helpers/`:**
- `fixtures.py::issue_invoice_now` — was issuing with a subscription id in the invoice-id path slot (PRD's endpoint is `POST /api/companies/{id}/invoices/{iid}/issue` on a DRAFT invoice). Now lists the subscription's invoices, picks the latest DRAFT, issues by id.
- `fixtures.py::drive_subscription_to_suspended` — docstring corrected to match actual flow (issue current-period invoice, age 36 days to SUSPENDED).

**Fixes applied to `test_suite/` (beyond STEP-1 actions):**
- `test_14_endpoints.py::test_get_invoices_list_filter_by_status` — setup fixed to issue+pay the activation DRAFT, then advance to the second billing date (Oct 31) where the system generates period 2's DRAFT; previously assumed a mid-period issueable invoice that PRD's billing model doesn't produce.
- `test_03_non_linear_state_machines.py` (both suspend-cycle tests) — settle the PAST_DUE invoice via the PRD-named payment simulation driver instead of the pay endpoint, since PRD verbatim pins pay to ISSUED-only ("Attempting to pay an invoice that is not ISSUED ... is rejected with ERR_INVOICE_NOT_PAYABLE").
- `test_09_compensating_invariants.py::test_suspend_resume_round_trip_preserves_headcount` — same settle-via-simulation fix.

**Fixes applied to `implementation/`:**
- `routes/subscriptions.py` — activation now creates the first invoice in **DRAFT** covering [activation, +30d) (PRD: "An invoice is born DRAFT"), sets `anchor_day`, and initializes `next_billing_at`.
- `routes/sim.py::reevaluate_time_driven` — added monthly billing: at each billing date the system generates a DRAFT covering the just-ended 30-day period (PRD: "Issuing it — which the platform operator does on the billing date"); skips periods already covered by a PAID invoice; advances `next_billing_at`. Payment simulation driver now settles PAST_DUE invoices as well as ISSUED (PRD: "on SUCCEEDED the invoice moves ... to PAID" plus §3.3's settle-based recovery), without auto-lifting SUSPENDED (resume is the explicit path).
- `routes/invoices.py` — issue endpoint is idempotent for an already-ISSUED invoice (the activation flow's invoice is issued through this same path); nested list endpoint now supports the PRD-declared `subscription_id` filter; pay endpoint kept at PRD-verbatim ISSUED-only; settle bubble kept to PAST_DUE→ACTIVE and REACTIVATED→ACTIVE (no SUSPENDED auto-lift).
- `routes/transfers.py` — `ERR_TRANSFER_EXPIRED` now precedes the state check on accept/counter/firm-accept, per PRD: "acting on an expired transfer is rejected with ERR_TRANSFER_EXPIRED."
- `routes/users.py` — invite now enforces the subscription writability gate (PRD: "While in CANCELLED_READ_ONLY ... other mutations are rejected with ERR_SUBSCRIPTION_NOT_WRITABLE").

No implementation checks required by PRD were weakened; no data is seeded (storage remains in-memory dicts); no test assertion was downgraded below what PRD names.

Orchestrator verification: read all 8 `results.{1..8}.json` directly — each `passed == total == 64`, `failed == 0`; result mtimes (18:51) postdate all implementation source mtimes (≤17:48), so no post-sweep impl writes. Test count on disk is 64 (65 − 1 deletion, consistent); grep confirms zero `skip`/`xfail` markers in test_suite/ and test_helpers/.

## Step 8: Finalize PRD — 2026-09-30T18:58:00.000Z

The diff is exactly the nine intended edits, line count unchanged (390 → 390, 0.0% delta — all changes are inline revisions within existing lines).

### Changes

- **§3.3 (Subscription Lifecycle)** — revise — activation now creates the first invoice in `DRAFT` covering [activation, +30d) and initializes `next_billing_at`, instead of "issues the first `Invoice` in `ISSUED` state" — `implementation/routes/subscriptions.py:70-81`.
- **§3.3** — revise — appended "Settling alone never lifts `SUSPENDED`; the resume is always explicit" to the suspension-unwinds sentence — `implementation/routes/sim.py:188-191` (no SUSPENDED auto-lift), `implementation/routes/subscriptions.py:194-213` (explicit resume).
- **§3.4 (Payroll)** — revise — under a `SUSPENDED` subscription the add-on has already cascaded to `PAUSED`, so termination surfaces `ERR_PAYROLL_NOT_ACTIVE` (the add-on check is the operative gate) — `implementation/routes/payroll.py:208-211`.
- **§3.5 (Invoicing)** — revise — setting the logical clock generates the period `DRAFT` invoice on each billing date for `ACTIVE`/`PAST_DUE`/`REACTIVATED` subscriptions (skipping periods already covered by a `PAID` invoice) and advances the schedule; issuing an already-`ISSUED` invoice is idempotent; the issue-rejection wording now reads "neither `DRAFT` nor already `ISSUED`" — `implementation/routes/sim.py:111-146`, `implementation/routes/invoices.py:67-76`.
- **§2.7 (Simulation Drivers)** — revise — payment simulation `SUCCEEDED` moves an invoice from `ISSUED` **or `PAST_DUE`** to `PAID`, and does not auto-lift `SUSPENDED` — `implementation/routes/sim.py:171-191`.
- **§3.2 (Onboarding)** — revise — invitations are subject to the `CANCELLED_READ_ONLY` writability gate (`ERR_SUBSCRIPTION_NOT_WRITABLE`) — `implementation/routes/users.py:51-53`.
- **§3.10 (Billing Transfers)** — revise — `ERR_TRANSFER_EXPIRED` fires before the pending-state check on accept, counter, and firm accept — `implementation/routes/transfers.py:29-32` + callsites at 126, 149, 215.
- **§2.9 (Validation Order)** — revise — body-shape failures (`ERR_INVALID_REQUEST`) are rejected as the body is read, ahead of checks that depend on the rejected field — `implementation/helpers.py:26-41`, `implementation/routes/subscriptions.py:62-64` (token read before the TRIAL state check).
- **§4 (Endpoint table)** — revise — nested invoice list documented as filterable by `invoice_status` and `subscription_id` — `implementation/routes/invoices.py:45-47`.

### Step-7 items deliberately not patched

- Deleted `test_stale_connection_blocks_recon_start`: the deletion itself declares the behavior underivable; PRD stays silent (impl also has no gate — `implementation/routes/recons.py` start path checks overlap only).
- Relaxed `test_payroll_addon_requires_valid_subscription_fk`: impl (`payroll.py:36-42`) already matches the existing PRD §2.9 priority (identity before body-FK); the relaxation covers an alternative reading, so verbatim prose is correct.
- `test_helpers/fixtures.py` docstring/flow fixes: pure fixture bugs, no PRD content.

### Per-edit pre-edit search log

1. **§3.3 activation/DRAFT** — (a) activation invoice state + billing schedule; (b) read `subscriptions.py` (activate 57-82, `_issue_invoice` 29-44, cancel cascade, resume), `companies.py:44-59` (TRIAL provisioning, `anchor_day` None, no invoice), `sim.py:118-146` (billing loop skips TRIAL), `services.py:76-113` (lines identical for DRAFT/ISSUED), `test_14_endpoints.py:67-109` (second billing date Oct 31); (c) widened wording to mention `next_billing_at` initialization since impl exposes it on reads.
2. **§3.5 billing-date generation** — (a) monthly DRAFT generation + issue idempotency + issue error; (b) `sim.py:111-146`, `invoices.py:62-92`, `subscriptions.py:29-44` (shares `compute_invoice_lines`), `services.py:76-113`; (c) scoped generation to "setting the logical clock" (impl never auto-generates elsewhere) and adjusted the closing error sentence to "neither DRAFT nor already ISSUED" for consistency with the new idempotency sentence.
3. **§2.7 payment simulation** — (a) simulation settle statuses + subscription side effects; (b) `sim.py:162-192`, `invoices.py:23-36` (same settle bubble in pay), `test_03:45-60,96-98`, `test_09` suspend/resume test; (c) kept `DECLINED` wording verbatim and added the no-auto-lift sentence rather than touching `TIMEOUT` (impl treats it as a no-op; left under-determined).
4. **§3.3 explicit resume** — (a) SUSPENDED exit paths; (b) `sim.py:188-191`, `subscriptions.py:194-213`, `invoices.py:23-36`; (c) appended one clause instead of rewriting the existing sentence.
5. **§3.2 invite writability gate** — (a) subscription-state gates on user mutations; (b) `users.py:35-67` (invite: gate after duplicate check, before seats), `users.py:95-125` (accept has its own TRIAL/ACTIVE/PAST_DUE/REACTIVATED list — pinned already), `helpers.py:144-151`; (c) phrased as "subject to the §3.3 gate" without fixing position vs. seat limit (impl ordering: duplicate → writable → seat; PRD stays silent on that ordering).
6. **§3.10 transfer expiry precedence** — (a) expiry vs state checks on transfer actions; (b) `transfers.py` accept 126-128, counter 149-151, firm-accept 215-217, decline 170-171 (no expiry check), cancel 184-185 (no expiry check), `sim.py:83-89`; (c) enumerated "accept, counter, and firm accept" explicitly to avoid implying decline/cancel raise expiry.
7. **§3.4 suspended-termination error** — (a) payroll-employee ops under non-active add-on / non-writable subscription; (b) `payroll.py:130-157` (create employee: same `payroll_not_active` gate), `payroll.py:190-224` (terminate: add-on check before lifecycle check), `sim.py:72-76` (suspension cascade ACTIVE→PAUSED), `test_07:139-166`; (c) pinned the winner for the SUSPENDED overlap without restating check order generally.
8. **§2.9 body-shape placement** — (a) ERR_INVALID_REQUEST vs other checks; (b) `helpers.py:15-41` (`body_json`, `req_str`, `req_int`, `enum_check`), every write route's call pattern, `subscriptions.py:62-66` (token before state check); (c) hedged placement ("ahead of any check that depends on the rejected field") so it does not claim a universal position over path-existence or state checks.
9. **§4 invoice list filter row** — (a) filters on nested invoice list; (b) `invoices.py:39-50` (`invoice_status` + `subscription_id` via `filter_items`), PRD §2.3 filter vocabulary (both names already declared), flat `GET /api/invoices` row (already documents its filters); (c) none.

Orchestrator verification: PRD_FINALIZED.md on disk (390 lines, same as PRD.md); `diff` shows exactly 18 changed diff-lines (9 inline revisions) matching the 9 reported edits 1:1 — including the four most substantive ones (§2.7 PAST_DUE settle + no-auto-lift, §3.3 DRAFT-born first invoice, §3.5 billing-date generation + issue idempotency, §3.10 expiry-before-state precedence).

## Step 9: PRD completeness scan — 2026-09-30T19:12:00.000Z

Done. `PRD_COMPLETED.md` is written and verified clean of the revised/removed passages.

**Source vs output**: `PRD_FINALIZED.md` — 390 lines / 65,334 chars → `PRD_COMPLETED.md` — 389 lines / 69,687 chars (+4,353 chars, −1 line from removing the dead `ERR_TRIAL_EXPIRED` catalogue row).

**Counts**: 10 mismatch-revisions, 21 ambiguity-pins (20 edits total; some edits bundle one of each).

**Changes** (PRD section — kind — class — what changed — impl ref):

- §2.3 — insert — ambiguity — out-of-range/non-numeric `limit`/`offset` are clamped to defaults/range, not rejected — implementation/helpers.py:75-93
- §2.4 — insert — ambiguity — body-carried path id (`company_id`, `firm_id`) disagreeing with path → `ERR_NOT_FOUND` — implementation/routes/firms.py:97-100
- §2.5 — revise — mismatch — tax rate keyed on `data_region`, not `home_country` — implementation/services.py:72-73
- §3.1 — insert — ambiguity — plan feature flags optional, default `false` — implementation/routes/plans.py:26-29
- §3.2 — revise — mismatch — invitation accept outside TRIAL/ACTIVE/PAST_DUE/REACTIVATED → `ERR_SUBSCRIPTION_NOT_WRITABLE` — implementation/routes/users.py:108-109
- §3.2 — insert — ambiguity — self-disable and disable-primary → `ERR_INVALID_REQUEST`; non-ACTIVE target → `ERR_INVALID_STATE_TRANSITION` — implementation/routes/users.py:138-143
- §3.3 — revise — mismatch — expired-trial operations surface `ERR_SUBSCRIPTION_NOT_WRITABLE` (not `ERR_TRIAL_EXPIRED`) — implementation/helpers.py:149-151
- §3.3 — revise+insert — mismatch — suspension check pinned at `period_end`+35d; resume is always explicit (settling alone never lifts SUSPENDED); resume with unpaid invoices → `ERR_BILLING_STATE_BLOCKED` — implementation/routes/sim.py:62-82,188-191; routes/subscriptions.py:202-205
- §3.4 — revise — mismatch — payroll pause/resume open to any company user, not primary admin only — implementation/routes/payroll.py:75-106
- §3.4 — insert — ambiguity — `FILED_CURRENT` requires at least one invoice (all-PAID over trailing window) — implementation/services.py:132-134
- §3.4 — insert — ambiguity — employee creation gated only on add-on `ACTIVE`, no separate subscription-lifecycle gate — implementation/routes/payroll.py:144-145
- §3.5 — insert — ambiguity — wholesale discount line is zero while billing firm is suspended — implementation/services.py:84
- §3.5 — revise — mismatch — invoice issue no longer runs payment simulation in the same call; wrong lifecycle → `ERR_INVALID_STATE_TRANSITION`; issue advances `next_billing_at` to `period_end` when later — implementation/routes/invoices.py:73-91
- §3.6 — insert — ambiguity — authorize/reauthorize require PRIMARY_ADMIN/COMPANY_ADMIN; disconnect/revoke require PRIMARY_ADMIN; ingestion on non-ACTIVE connection → `ERR_INVALID_STATE_TRANSITION`; clock-set also re-evaluates consent expiry — implementation/routes/bank.py:123,142,163,180,197-198; routes/sim.py:105-110
- §3.6 — insert — ambiguity — rejected suggestions are re-evaluated by later rule create/resume; manual categorize clears `matched_rule_id` — implementation/services.py:168; routes/bank.py:301
- §3.6 — insert — ambiguity — rule delete admitted from ACTIVE/PAUSED, double-delete → `ERR_INVALID_STATE_TRANSITION`; no category-name uniqueness — implementation/routes/rules.py:178-181
- §3.7 — insert — ambiguity — recon start/complete/abandon in wrong state (incl. LOCKED) → `ERR_INVALID_STATE_TRANSITION` — implementation/routes/recons.py:123-124,139-140,167-168
- §3.8 — insert — ambiguity — invalid `resolution` value → `ERR_INVALID_REQUEST`; integration disconnect restricted to PRIMARY_ADMIN/COMPANY_ADMIN — implementation/routes/integrations.py:173-175,115
- §3.9 — insert — ambiguity — `PAYROLL_NOT_MIGRATED` signal = presence of any payroll add-on; illegitimate CLEAN outcome → `ERR_INVALID_STATE_TRANSITION` — implementation/routes/migrations.py:105-118
- §3.10 — insert — ambiguity — firm suspend/reactivate from wrong state → `ERR_INVALID_STATE_TRANSITION` — implementation/routes/firms.py:47-48,62-63
- §3.10 — insert — ambiguity — firm close: REACTIVATED subscriptions exempt from block; double-close → `ERR_INVALID_STATE_TRANSITION`; pending transfers (both pending states) cancelled — implementation/routes/firms.py:73-88
- §3.10 — insert — ambiguity — accountant user born with `user_status` ACTIVE — implementation/routes/firms.py:111
- §3.10 — revise — mismatch — grant `firm_id` recorded as given in the request, not denormalized from the advisor's firm — implementation/routes/grants.py:49
- §3.10 — insert — ambiguity — grant accept check order firm-active → PENDING_ACCEPT → expiry; wrong advisor accepting → `ERR_IDENTITY_MISMATCH` — implementation/routes/grants.py:122-132
- §3.10 — insert — ambiguity — transfer-cancel initiating party determined by `from_owner` — implementation/routes/transfers.py:187-199
- §3.11 — revise — mismatch — advisor export-create accepts `FULL_BOOKKEEPING` or `REPORTS_READ_ONLY` grant (not FULL_BOOKKEEPING only); PENDING requests do not expire on download deadline, only READY do — implementation/routes/exports.py:42-43; routes/sim.py:97-103
- §3.11 — insert — ambiguity — `requested_by_user_id` must be a company user; PURGED company → `ERR_INVALID_STATE_TRANSITION`; download restricted to PRIMARY_ADMIN or FULL_BOOKKEEPING advisor; not-READY check precedes deadline check — implementation/routes/exports.py:27-36,109-120
- §5 — revise — mismatch — removed dead `ERR_TRIAL_EXPIRED` catalogue row — implementation/errors.py (no such error raised anywhere)

No new sections added; all edits are in-paragraph inserts/revisions plus the single catalogue row deletion.

Orchestrator verification: PRD_COMPLETED.md on disk at 389 lines / 69,687 chars (matches reported counts exactly); diff vs PRD_FINALIZED.md = 49 changed diff-lines; `grep ERR_TRIAL_EXPIRED PRD_COMPLETED.md` returns nothing, confirming the catalogue-row removal.

## Pipeline complete — 2026-09-30T19:13:00.000Z

All 9 steps done. Final state: 64/64 tests passing across 8/8 parallel sweep rounds under per-test-server isolation; PRD chain = PRD.md → PRD_FINALIZED.md (9 inline revisions) → PRD_COMPLETED.md (20 edits: 10 mismatch-revisions + 21 ambiguity-pins). Deliverables: SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/ + test_suite/ (64 tests, all Design-tagged), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (128 endpoints, in-memory storage, start.sh)} + results.{1..8}.json all clean.
