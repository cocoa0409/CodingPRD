# Worklog — task_3406_engine_aftermarket_service_agreements_flight_hour_pricing

## Step 1: Create task directory — 2026-10-01T19:10:00.000Z

Task directory pre-allocated by the invocation args: `tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/` with `workspace/` inside (verified, empty). No index computed, no other task_* directory created. Difficulty instruction: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 2: Generate scaffold — 2026-10-01T20:40:00.000Z

Subagent summary (verbatim):

All generation, verification, and lint passes are complete. Summary below.

**Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/`):**

- `SCAFFOLD.yaml` — 1591 lines. §1.0–§1.7 plus preamble and concurrency rules; contains NO `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1202 lines. Single top-level key `scaffold_difficulty_design`; all 9 difficulty rules × 2 instances = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1685 lines. Single top-level key `scaffold_corner_design`; 9 taxonomy sections, 54 instances (46 active + 8 `excluded_because` stubs, all stubs referencing real difficulty instances).

**Counts:** 12 entities, 40 endpoints (at the cap), 9 calculations, 10 ordered validation rows, 39 error codes, 5 roles, 9 state machines, 2 OCC concurrency rules.

**Design character (depth over sprawl):** pricing_engine + ledger_reconciliation archetypes; cyclic state machines (agreement DRAFT→ACTIVE↔RENEGOTIATION loop; workscope SUBMITTED→{APPROVED,REJECTED}→REOPENED→SUPERSEDED version loop); dual-variant calcs in three domains (billing provisional/final input sets, recognition PROJECTED vs ACTUAL, cycle- vs calendar-based visit forecasting); combinatorial formulas in distinct modes (tiered+compounding rate; pinned round-per-line-then-sum order; evaluation-order-pinned workscope determination); two transitive cascades from different triggers (verify→engine→visit-date→lease-cancel depth 3; directive→workscope-reopen→requisition-cancel depth 2); priority conflicts on distinct category pairs (state>fiscal, safety>referential); boundary precision at ratio==1.10 (strict `>`) and half-open lease adjacency; two overlap semantics (pairwise half-open asset exclusion vs aggregate daily induction capacity = 2); two compensating invariants (spare-pool availability; visit committed parts cost across supersede-cancel).

**Verification results:**
- Every append chunk parse-checked incrementally; all three files parse as YAML.
- Constant audit: all 27 named constants (UTIL_BAND_*, CLASS_COST_FACTOR_*, CLASS_LEAD_DAYS_*, SHOP_INDUCTION_DAILY_CAPACITY, MIN_POST_VISIT_INTERVAL_MONTHS, LLP_RESET_CYCLES, etc.) defined exactly once in a calculation's `constants:` block.
- All formula-derived assert literals were pre-computed in Python (e.g., provisional 154500.00 / final 79825.00 / adjustment −74675.00; recognition 96000.00 vs 17000.00 with onerous 1020000.00; rounding-order 599.98; forecast dates 2027-01-29 / 2026-10-31).
- Domain-token grep confirms engine / flight_hour / shop_visit / workscope (plus lease, directive, recognition) content throughout.
- Enum-closure, error-reachability (39/39 referenced and test-covered), role closure, endpoint-output resolution, and instance-name uniqueness (72/72) all pass.
- Lint verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (533 calls scanned).

result: Scaffold triple for task_3406 (engine aftermarket flight-hour service agreements) generated at 12 entities / 40 endpoints / 9 calculations / 18 difficulty + 54 corner instances, all YAML parses and scaffold_lint clean.

Orchestrator verification: all 3 files exist with claimed line counts; all parse as YAML with correct top-level keys; SCAFFOLD.yaml has 0 forbidden keys; domain tokens present (engine ×178, shop_visit ×21, workscope ×107, flight_hour ×10).

## Step 3: Copy shared files — 2026-10-01T20:42:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). No subagent.

## Step 4: Generate PRD — 2026-10-01T21:05:00.000Z

Subagent summary (verbatim):

All checks pass. The document is complete and verified.

result: PRD generated and self-audited at /home/ubuntu/github/CodingPRD/tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/workspace/PRD.md (357 lines)

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/workspace/PRD.md` — 357 lines, ending cleanly on the final error-table row (`ERR_INSUFFICIENT_LIFE_RESTORATION`), no truncation, no audit footer.

**Section list**: §1 Introduction (2 paragraphs) · §2.1 RBAC · §2.2 API Response Structure (fixed block verbatim) · §2.3 Pagination · §2.4 The Logical Clock · §2.5 Common Resource Properties · §2.6 Monetary Precision and Rounding · §2.7 Optimistic Concurrency Control · §2.8 Validation Order and Error Precedence · §2.9 Nested Resource Resolution · §2.10 The Utilization Band Pricing Model · §3.1 Registering Operators, Engines, and the Spare Pool · §3.2 Service Agreements (draft/activate/enroll/renegotiate) · §3.3 Flight-Hour Reporting and the Verification Cascade · §3.4 Monthly Billing (PROVISIONAL/FINAL) · §3.5 Shop Visits (forecast/induct/complete) · §3.6 Workscope Determination, Directives, Life-Restoration Floor · §3.7 Parts Sourcing and Committed Parts Cost · §3.8 Spare Engine Leasing · §3.9 Contract Accounting and Revenue Recognition · §4 Endpoint Definitions (40 rows, 4 columns) · §5 Error Code Catalogue (39 rows, 2 columns).

**Contract 1 — Field coverage**: 83 required identifiers (all entity fields incl. line-item and workscope-item sub-fields, plus endpoint inputs `to_iso8601`, `expected_agreement_version`, `expected_shop_visit_version`, `override`, `limit`, `offset`, query filters `operator_id`/`agreement_id`) — grep-verified all present in backticks; first pass caught `line_items` and `workscope_id` missing, both repaired and re-verified. PASS.

**Contract 2 — Rule coverage**: all 10 validation priorities rendered as an explicit ordered list in §2.8 with every error_id; both OCC rules expressed with write operation + `expected_*_version` + `ERR_STALE_VERSION`/412; all 9 calculations fully narrated (escalation anniversary count, 0.90/1.10 bands with 0.95/1.00/1.08 factors and 1.00 no-data default, pinned line-then-total rounding, 30 days/month and 72-month forecast variants with CYCLE_BASED tie rule, 18-month life floor with 18×`assumed_cycles_per_month` buffer, class factors 1.00/0.70/0.45 and lead days 7/21/3 with NEW→REPAIRED→USM tie-break, 50,000 USD deposit waived for `A`, recognition constants 8,000 / 1,200,000 / 1.00/1.15/1.30 / 0.15 / 0.05, induction capacity 2 with at-or-above rejection boundary); all state transitions and cascades (verify, directive reopen, supersede compensation, lease auto-cancel, auto-expiry) with version increments; all 39 error ids grep-confirmed in §2/§3 prose. Sibling variants (PROVISIONAL/FINAL, CYCLE_BASED/CALENDAR_BASED, PROJECTED/ACTUAL) rendered with equal density. PASS.

**Contract 3 — §3 path purity**: 473 backtick tokens scanned in §3; zero starting with `/`, zero bare HTTP methods, zero method+path tokens (re-scanned after edits). PASS.

No pseudocode operators or fuzzy words survive (grep-verified); §2.2 emitted byte-identical to the fixed source; the withheld design-index files and test directories were never opened.

Orchestrator verification: PRD.md is 357 lines; tail ends cleanly on the error table; 40 endpoint rows (matches scaffold); constants 0.95/1.08, 50,000 present; ERR_STALE_VERSION ×6.

Note: Step 5 will be split into 5a (test_helpers, frozen) and 5b (test_suite) per pipeline experience with large generation steps; Steps 5 and 6 run SEQUENTIALLY (not concurrently) because this model endpoint duplicates parallel tool calls — Step 6's prompt carries an explicit read-ban on the test artifacts instead.

## Step 5a: Generate test_helpers — 2026-10-01T21:35:00.000Z

Subagent summary (verbatim):

---

**Stage 5a complete — test_helpers/ for task_3406 (engine aftermarket service agreements)**

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/test_helpers/`, 2031 lines total):

| file | lines |
|---|---|
| `__init__.py` | 33 |
| `types.py` | 298 |
| `api_client.py` | 233 |
| `api_errors.py` | 92 |
| `assertions.py` | 322 |
| `factories.py` | 207 |
| `constants.py` | 104 |
| `test_users.py` | 35 |
| `fixtures.py` | 707 |

**Verification**: AST parse OK on all 9 files; package imports cleanly with no server running (no import-time network; `api_client.base_url` resolves lazily from `API_BASE_URL` env, default `http://localhost:10000`); tail of the largest file (`fixtures.py`) ends intact with `__all__`; error map registers 39 error IDs. Every constant in `constants.py` was grep-verified verbatim against PRD.md (0.90/1.10/0.95/1.00/1.08, "twelve calendar months", 30 days/month, 72 months, 18 months, 7/21/3-day leads, 50,000 USD deposit, 8,000 LLP reset, 1,200,000 base visit cost, severity factors 1.00/1.15/1.30, margin 0.15 / floor 0.05, capacity "reached 2", clock init `2026-09-01T00:00:00Z`). No server run, no pytest, no test_suite/ created.

**Helper API surface (frozen contract for Stage 5b)**

*types.py* — enums `UserRole, CreditRating, SeverityTier, EngineStatus, AgreementStatus, ReportStatus, StatementStatus, ShopVisitStatus, ForecastMethod, WorkscopeStatus, WorkscopeItemType, SourcingClass, RequisitionStatus, SpareEngineStatus, LeaseStatus, DirectiveType`; TypedDicts `Operator, Engine, ServiceAgreement, FlightHourReport, BillingLineItem, BillingStatement, ShopVisit, WorkscopeItem, Workscope, PartRequisition, SpareEngine, SpareEngineLease` (all with `id/created_at/updated_at/version`), and append-only `Directive, RecognitionSnapshot` (id + created_at only, NO version/updated_at).

*api_client.py* — `ApiClient(GenericApiClient)` and module instance `api_client`. Methods (all return raw `requests.Response`; `headers` required, pass `None` for no-auth tests): `set_clock(payload, headers)`; `create_operator/create_engine/create_spare_engine/create_directive(payload, headers)`; `submit_flight_hour_report(engine_id, payload, headers)`; `verify_flight_hour_report(report_id, headers)`; `create_shop_visit(engine_id, payload, headers)`; `induct_shop_visit(visit_id, headers)`; `complete_shop_visit(visit_id, headers)`; `create_agreement(payload, headers)`; `activate_agreement/open_renegotiation(agreement_id, headers)`; `amend_agreement(agreement_id, payload, headers)`; `enroll_engine(agreement_id, payload, headers)`; `issue_billing_statement(agreement_id, payload, headers)`; `settle_billing_statement(statement_id, headers)`; `create_recognition_snapshot(agreement_id, headers)`; `create_workscope(visit_id, payload, headers)`; `approve_workscope/reject_workscope(workscope_id, headers)`; `create_part_requisition(workscope_id, payload, headers)`; `source_part_requisition(requisition_id, headers, payload=None)`; `create_spare_engine_lease(payload, headers)`; `activate_spare_engine_lease/return_spare_engine_lease(lease_id, headers)`; GETs: `get_engine`, `list_engines`, `list_engine_shop_visits`, `list_engine_flight_hour_reports`, `get_agreement`, `list_agreement_billing_statements`, `list_agreement_recognition_snapshots`, `get_shop_visit`, `list_shop_visit_workscopes`, `list_shop_visit_leases`, `get_workscope`, `list_workscope_part_requisitions`, `get_spare_engine`, `list_spare_engine_leases` (list methods take `(headers, params=None)`).

*api_errors.py* — `ApiErrorId` enum (all 39 §5 IDs), `HTTP_STATUS_CODES` dict keyed by `ApiErrorId` (401/403/404×10/400/422×5/409×18/412), registered with the framework at import.

*assertions.py* — `assert_operator/engine/service_agreement/flight_hour_report/billing_line_item/billing_statement/shop_visit/workscope_item/workscope/part_requisition/spare_engine/spare_engine_lease/directive/recognition_snapshot(data)` (shape + enum + common-fields contract; `assert_directive`/`assert_recognition_snapshot` assert ABSENCE of `updated_at`/`version`); invariant checkers `assert_agreement_invariants`, `assert_engine_invariants`, `assert_recognition_invariants`.

*factories.py* — `set_clock_payload()`, `create_operator_payload()`, `create_engine_payload()`, `create_flight_hour_report_payload()`, `create_shop_visit_payload()`, `create_agreement_payload()`, `amend_agreement_payload(expected_agreement_version, **terms)`, `enroll_engine_payload(engine_id, **ov)`, `issue_billing_statement_payload()`, `workscope_item(**ov)` (item_code/item_type/estimated_cost_usd/restores_cycles/directive_ref), `create_workscope_payload(expected_shop_visit_version, items=None, **ov)`, `create_part_requisition_payload()`, `source_requisition_payload(override=None)` (returns `{}` when None), `create_spare_engine_payload()`, `create_spare_engine_lease_payload()`, `create_directive_payload()` — all `(**overrides) -> dict`; defaults valid against clock init 2026-09-01 (period "2026-09", agreement term 2026-09-01→2027-08-31).

*constants.py* — `CLOCK_INITIAL_ISO`, pagination defaults, `MONEY_DP/RATE_PRECISION_DP/PCT_PRECISION_DP`, `UTIL_BAND_{LOW,HIGH}_THRESHOLD` + `*_FACTOR`, `NO_DATA_RATIO`, `UTILIZATION_WINDOW_MONTHS`, `WORKSCOPE_BASE_COST_USD`, `SEVERITY_COST_FACTOR*` + dict, `FORECAST_DAYS_PER_MONTH`, `CALENDAR_INTERVAL_MONTHS`, `MIN_POST_VISIT_INTERVAL_MONTHS`, `CLASS_COST_FACTOR*` + dict, `CLASS_LEAD_DAYS*` + dict, `CLASS_PRIORITY`, `LEASE_DEPOSIT_USD`, `SHOP_INDUCTION_DAILY_CAPACITY`, `LLP_RESET_CYCLES`, `TARGET_MARGIN_PCT`, `MARGIN_FLOOR_PCT`.

*test_users.py* — `TEST_USERS` with keys `platform_admin_headers`, `contract_manager_headers`, `shop_planner_headers`, `finance_controller_headers` (opaque roles, canonical), and `operator_headers` (fallback ONLY for role-rejection tests — never for ownership-gated calls); `make_operator_headers(user_id)` builder for the entity-backed Operator role.

*fixtures.py* — module-level role aliases `ADMIN/MANAGER/PLANNER/FINANCE`; `_unwrap` raises "Setup failed (what): HTTP …" on 4xx. Single-resource helpers: `create_operator`, `create_engine(operator, ...)`, `create_spare_engine`, `create_directive(..., compliance_cycles=50)` (pass `compliance_cycles=None, compliance_date=...` for date-bound), `create_agreement`, `activate_agreement`, `create_active_agreement` (returns ACTIVE, version 2), `open_renegotiation`, `amend_agreement(agreement_id, expected_version, **terms)`, `get_agreement`, `enroll_engine(agreement, engine, assumed_annual_hours=2400, assumed_cycles_per_month=100)`. Reports: `submit_report(engine, operator_headers, ...)`, `verify_report(report)`, `submit_and_verify_report(...)`, `submit_history(engine, operator_headers, entries, verify=True)` (entries = (period, hours, cycles, severity) tuples or dicts). Visits: `create_visit`, `induct_visit`, `complete_visit`, `get_shop_visit`, `get_visit_version`. Workscopes: `create_workscope_version(visit_id, items=None, expected_shop_visit_version=None)` (reads OCC version fresh when omitted), `approve_workscope(ws, operator_headers)`, `reject_workscope`, `get_workscope`. Requisitions: `create_requisition(workscope, ...)`, `source_requisition(requisition, override=None)` (override=True uses ContractManager headers). Leases: `create_lease(spare, visit, operator_headers, start, end)`, `activate_lease`, `return_lease`. Billing/accounting: `issue_statement(agreement, period="2026-09")`, `settle_statement`, `issue_and_settle_statement`, `create_recognition_snapshot(agreement)`. Clock: `set_clock(to_iso8601)`. Composite `setup_*` fixtures return dicts: `setup_enrolled_engine(...)` → `{operator, engine, agreement, operator_headers}`; `setup_enrolled_engines(engine_specs, ...)` → `{operator, agreement, engines[], operator_headers}` (each spec: esn + optional engine_model/base_severity_tier/llp_remaining_cycles/assumed_annual_hours/assumed_cycles_per_month); `setup_scheduled_visit(fx, planned=...)` → fx+`visit`; `setup_inducted_visit(fx, ...)` → fx+`visit`(INDUCTED); `setup_submitted_workscope(fx, ...)` → fx+`visit`+`workscope`(SUBMITTED); `setup_approved_workscope(fx, ...)` → fx+`visit`+`workscope`(APPROVED); `setup_completed_visit(fx, ...)` → fx+`visit`(COMPLETED)+`workscope`; `setup_reserved_lease(fx, ...)` → fx+`visit`+`spare_engine`+`lease`(RESERVED).

**Interpretation decisions** (each resolved by PRD quote):
1. *Composite fixtures return dicts, not tuples* — with 5+ resources per preamble, dict keys (`fx["engine"]`, `fx["operator_headers"]`) are self-documenting; the skill mandates shape documentation, which the docstrings carry.
2. *Fixtures embed `operator_headers` bound to `operator["id"]`* — PRD §2.1: "When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator` entity"; this makes the entity-backed identity threading mandatory-by-default.
3. *Fixtures only wrap success paths; expected-error triggers call `api_client` directly* — fixtures raise "Setup failed" on 4xx (skill §1.8: get_success_data for setup), so Stage 5b must issue trigger calls via `api_client` + `TEST_USERS`/`make_operator_headers` + `validate_error`.
4. *`create_workscope_version` re-reads the visit for the OCC version when not given* — PRD §2.7 pins `expected_shop_visit_version` to "the caller's last observed `version`"; a fresh GET is the caller's observation point.
5. *`assert_directive`/`assert_recognition_snapshot` assert absence of `version`/`updated_at`* — PRD §2.5: "Neither has an `updated_at` field nor a `version` field" (a stated rule, not a silence).
6. *`source_requisition_payload(None)` omits the `override` field entirely* — PRD §3.7 makes override a ContractManager-only input; an explicit `override: false` from ShopPlanner is a needless edge the PRD doesn't pin.
7. *Default factory dates align to the initial logical clock* — PRD §2.4: "the logical clock reads exactly `2026-09-01T00:00:00Z`"; all design-index recipes key off that reading, so defaults (period "2026-09", term containing it) are consistent with every recipe.

result: Stage 5a test_helpers/ for task_3406 written and verified — 9 files (2031 lines), AST-clean, imports side-effect-free, constants grep-verified against PRD, fixture API covers every setup_api_calls shape in both design indices.

Orchestrator verification: all 9 files present; AST parse OK on all; test_suite/ absent (expected at this stage).

## Step 5b: Generate test_suite — 2026-10-01T22:20:00.000Z

Subagent summary (verbatim):

result: Test suite Stage 5b complete — 62 tests across 9 test files + conftest.py in /home/ubuntu/github/CodingPRD/tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/test_suite/, covering 17/18 difficulty instances (1 PRD-silence skip) and all 45 active corner instances; AST+citation audits both pass with zero defects.

---

**EXIT REPORT (for the orchestrator worklog)**

**Files written (all under `tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/test_suite/`):**
- `conftest.py` — 42 lines, session-scoped `api` fixture + 5 role-header fixtures (skill §2.0 bridge)
- `test_01_envelope_and_entities.py` — 253 lines, 8 tests
- `test_02_agreement_lifecycle.py` — 205 lines, 7 tests
- `test_03_flight_hour_reports.py` — 191 lines, 6 tests
- `test_04_billing_and_recognition.py` — 414 lines, 8 tests
- `test_05_workscope_lifecycle.py` — 324 lines, 10 tests
- `test_06_visit_gates.py` — 249 lines, 7 tests
- `test_07_parts_sourcing.py` — 197 lines, 4 tests
- `test_08_spare_leasing.py` — 261 lines, 7 tests
- `test_09_security_rbac.py` — 114 lines, 5 tests

Total: **62 tests**, 2250 lines.

**AST audit (real `ast.parse` + `yaml.safe_load`, no server/pytest run):**
- Tags found: 62 distinct; duplicates NONE; unknown NONE; missing-tag NONE; dual-tag NONE; parse errors NONE.
- Index census: 18 difficulty instances, 45 active corner instances, 9 `excluded_because` stubs (all cross-references resolve to real difficulty instances; zero stub leakage). Note: the brief said 8 stubs/46 active — the actual YAML has **9 stubs/45 active**, so the true max was 63.
- Uncovered instances: exactly 1 (the skip below).

**Skipped instance (PRD-silence, not weakened):**
- `Difficulty/cross_entity_state_dependency/lease_activate_gated_by_visit_status` — asserts `ERR_VISIT_NOT_ACTIVE_FOR_LEASE`; grep of PRD.md finds that error id **zero** times (not even the §5 catalog). PRD §3.8 states the visit-state requirement ("requires the covered visit to be `SCHEDULED` or `INDUCTED`") without binding an error id, so `ERR_INVALID_STATE` is an equally faithful reading — fails the coverage condition.

**Recipe-literal re-derivations:**
- `Corner/state_machines/statement_settle_twice_rejected` — the recipe enrolls at 2400 assumed h/yr, which under PRD §3.4 yields ratio (100·12/1)/2400 = 0.5 → LOW band 0.95 → final 9500.00, contradicting the recipe's asserted 10000.00. Fixed by enrolling at `assumed_annual_hours=1200` (ratio exactly 1.00 → STANDARD → rate 100.0000 → final 100·100.0000 = 10000.00), preserving the asserted literal; documented in the test docstring.
- All other recipe literals re-verified against the PRD clock (2026-09-01) and formulas — no conflicts: billing 154500.00/79825.00/−74675.00; recognition 480000/1500000/96000/17000/1020000 (remaining term 23 months, 1 forecast visit, margin −2.125 < 0.05); escalated rate 278.1000; rounding order 299.99×2=599.98; utilization boundary 1.10 → 100.0000 vs 1.102 → 108.0000; forecast 150d→2027-01-29 then 60d→2026-10-31; capacity boundary at 2/day; leases 36000/20000/21000/120000/6000 + deposits 0/50000; parts 4500.00/9000.00 release; directive append 450000.00.

**Citation pass:** 107 quoted spans across all docstrings re-verified verbatim against PRD.md (whitespace-normalized), 0 failures (5 markdown-bold/bullet artifacts found and fixed mid-run).

**Helper-API mismatches:** none. Notes for orchestrator: (a) `ApiClient.source_part_requisition(requisition_id, headers, payload=None)` takes payload positionally after headers — used correctly; (b) difficulty coverage is 1 test/instance per the brief's 64-test cap, not the skill's ≥2/instance — flag if the orchestrator wants the second depth test per difficulty instance in a follow-up pass.

Orchestrator verification: 10 files (9 test + conftest), 2250 lines; AST parse finds exactly 62 test functions; `pytest --collect-only` collects 62 tests cleanly (no dangling imports). Census correction noted (45 active corner + 18 difficulty = 63 max, 1 skipped for PRD silence → 62). Orchestrator decision on note (b): 1 test/instance accepted — the design-index-only contract is satisfied; a second depth test per instance is optional and not required for benchmark validity.

## Step 6: Generate implementation — 2026-10-01T23:00:00.000Z

Subagent summary (verbatim):

All checks pass. Final state: 22 files, all AST-parse clean, tails confirmed, smoke-passed ports closed, start.sh executable, store boots empty (no seeding anywhere).

result: task_3406 reference implementation complete — 40/40 endpoints, full smoke chain passed on dynamic port with all computed values matching hand-derived expectations.

**Exit report**

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/workspace/implementation/`):

| File | Lines | Domain |
|---|---|---|
| app.py | 74 | Flask bootstrap, error handlers, blueprint registration, 0.0.0.0:$PORT (default 10000) |
| start.sh | 10 | Guarded pip install + `exec python3 app.py`, foreground |
| requirements.txt | 1 | flask only |
| storage.py | 57 | In-memory DB dicts (empty at boot, no seeding), logical clock (init 2026-09-01T00:00:00Z), id/seq minting, touch() |
| timeutil.py | 88 | ISO-8601 parse/format (3 fractional digits, Z), add_months with day-clamp, YYYY-MM periods, future-period check |
| money.py | 39 | Decimal coercion, round-half-up 2dp/4dp, JSON number serialization |
| errors.py | 58 | ApiError + complete 39-entry error-id→HTTP-status catalog |
| envelope.py | 86 | `meta`/`response_type`/`data` envelope, error envelope, limit/offset pagination (10/0, 1–100) |
| validate.py | 96 | Tier-4 body shape validators |
| authz.py | 36 | X-User-ID/X-User-Role auth, role gates, Operator ownership |
| calc.py | 306 | effective rate (escalation anniversaries + utilization bands), visit forecast, directive-due, workscope assembly + 18-month life floor, sourcing selector, lease days/overlap, committed parts, billing computation, billed_to_date |
| recognition.py | 97 | recognition snapshot (PROJECTED + ACTUAL variants, onerous accrual) |
| serialize.py | 214 | Entity serializers; Directive/RecognitionSnapshot carry only id+created_at |
| cascade.py | 106 | Verify cascade (counters, LLP debit, forecast recompute, RESERVED lease auto-cancel), directive cascade (SUBMITTED append / APPROVED→REOPENED), supersede compensation, agreement auto-expiry |
| routes_admin.py | 134 | clock, operators, engines, engine nested lists |
| routes_agreements.py | 222 | agreement draft/activate/open-renegotiation/amend (OCC)/enroll, agreement reads |
| routes_reports.py | 63 | report submit/verify |
| routes_billing.py | 76 | statement issue/settle, snapshot append |
| routes_visits.py | 171 | visit schedule/induct (capacity 2/day)/complete (pinned compliance gate), visit reads |
| routes_workscopes.py | 160 | workscope create (OCC + supersede), approve (cost cap), reject |
| routes_parts.py | 83 | requisition create, sourcing run/escalation/override |
| routes_leasing.py | 158 | spare engines, lease reserve/activate/return |
| routes_directives.py | 51 | directive issuance + cascade trigger |

**Endpoint count: 40** — verified by dumping `app.url_map` (26 POST + 14 GET), matching the scaffold endpoint table exactly.

**Interpretations chosen** (where PRD left it open):
1. Entity `created_at`/`updated_at` use the **logical clock** (PRD §3.5 feeds `engine.created_at` into the calendar forecast — date-sensitive ⇒ logical); `meta.api_request_timestamp` uses wall-clock UTC.
2. `version` starts at **1** on creation (§2.5 pins increments, not the initial value).
3. GETs require authentication but **no Operator ownership match** (§2.1 "All read endpoints are available to every authenticated role" + RBAC "all GET endpoints" shared); ownership enforced on writes only.
4. Operator caller on a nonexistent path id → resource **404**, not 403 (ownership chain unresolvable); role-membership 403 still precedes existence.
5. open-renegotiation from non-ACTIVE → `ERR_INVALID_STATE` (the `ERR_AGREEMENT_NOT_ACTIVE` catalog entry enumerates billing/enrollment/induction only).
6. Lease activate with visit not in {SCHEDULED, INDUCTED} or spare not AVAILABLE → `ERR_INVALID_STATE` (scaffold's `ERR_VISIT_NOT_ACTIVE_FOR_LEASE` is absent from both error catalogs).
7. Fixed-tier orderings: lease-activation state checks (tier 6) before in-window (tier 8); lease-creation overlap (8) before model-match (9); enroll: agreement ACTIVE → already-enrolled → in-shop.
8. Cascaded recomputes (visit forecast on verify, agreement billed_to_date) bump `version` **only on effective value change**; explicit "increments version" sites always bump; directive-cascade item append always bumps.
9. ShopPlanner passing `override=true` on /source → `ERR_FORBIDDEN` (read as an authorization rule).
10. Escalation anniversary compared against the **last instant** of the statement month; lease days = whole days in `[start, end)` via `timedelta.days`; forecast tie → CYCLE_BASED; directive items appended in directive creation order.
11. From-ESCALATED re-source without override re-runs the selector; repeated failure leaves ESCALATED without a version bump (the escalation transition fires once).
12. Amend ignores non-amendable keys (`contract_ref`, `start_date`) rather than erroring; item `estimated_cost_usd` is numeric-only (no invented positivity bound); body-referenced ids 404 right after shape checks; out-of-range limit/offset → 400.

**Smoke-test evidence** (port 51789, server PID killed exactly after run): unauthenticated probe → 401; wrong-role probe → 403; operator → 201; engine → 201; agreement → 201; activate → 200; enroll → 200; report → 201; verify → 200 (VERIFIED); issue → 201 (provisional 91130.0 = 260 h × 350.50, standard band); settle → 200 (final 91130, adjustment 0); schedule visit → 201 (forecast 2028-03-25 CYCLE_BASED = clock + ⌊4760·30/250⌋ = 571 days; projected_cost 1380000); induct → 200; workscope v1 → 201; approve → 200; requisition → 201; source → 200 (NEW @ 10000); spare → 201; lease → 201 (153000 = 51 d × 3000; deposit 50000 for rating B); lease activate → 200; return → 200; directive (mandatory, matching model) → 201 → v1 observed REOPENED; workscope v2 → 201 (scope_version 2, server-appended AD-2026-0113, total 150000); approve v2 → 200; complete → 200 (compliance gate passed); snapshot → 201 (lifetime_revenue 4560005.0, cost_to_date 303000.0, lifetime_cost 3063000.0, pct 0.0989, rec_proj 450984.49, rec_actual 77460.5, onerous 0 — all matching hand derivations); list engines + get agreement → 200 (billed 91130, enrolled 1). **SMOKE PASS**, RC=0.

**AST/no-truncation:** all 22 files parsed via `ast.parse`; last lines of every file visually confirmed as intended terminators. No stray processes left; both smoke ports confirmed closed.

Orchestrator verification: 21 .py files + start.sh + requirements.txt (2386 lines total); AST clean; start.sh executable. Note: interpretation #6 aligns with Step 5b's skip (ERR_VISIT_NOT_ACTIVE_FOR_LEASE absent from PRD catalog; impl uses ERR_INVALID_STATE).

## Step 7: Test-and-fix loop — 2026-10-01T23:20:00.000Z

Subagent summary (verbatim):

## Summary

- **Iterations run:** 2 sweeps (initial sweep: 38/62 failed deterministically across all 8 rounds; post-fix sweep: 62/62 passed in all 8 rounds).
- **Tests deleted:** none.
- **Fixes applied to `test_suite/`:** 8 files, 39 call sites — `test_01_envelope_and_entities.py` (6), `test_02_agreement_lifecycle.py` (7), `test_03_flight_hour_reports.py` (1), `test_04_billing_and_recognition.py` (8), `test_05_workscope_lifecycle.py` (1), `test_06_visit_gates.py` (4), `test_08_spare_leasing.py` (7), `test_09_security_rbac.py` (5). Every letter+digit `iata_code` literal (e.g. `"A1"`, `"T3"`, `"X2"`) was replaced with a two-uppercase-letter code via a digit→letter mapping (1→A … 9→I). Why: PRD §3.1 states verbatim "its two-letter `iata_code` (two uppercase letters, unique across all operators)" — the implementation correctly rejected the codes with `ERR_INVALID_REQUEST`; the tests' setup payloads violated the PRD precondition (STEP 2 test bug, not an implementation bug). The intentional duplicate in `test_duplicate_iata_rejected` (D7→DG, twice) was preserved as a duplicate; per-test uniqueness was verified test-by-test before mapping (X1→XA / X2→XB in the foreign-engine test; overrides in `setup_enrolled_engine` callers replace fixture defaults so no collision with helper default "FA").
- **Fixes applied to `test_helpers/`:** none — helper defaults ("TA", "FA") were already PRD-faithful; all bad codes were inline literals in the test files.
- **Fixes applied to `implementation/`:** none — the implementation was faithful to PRD throughout.
- **Sibling unasserted paths observed (test-side fixes dominated):** the operator-create validation path is asserted only via the happy path plus the duplicate-IATA test; the negative branch (malformed `iata_code` → `ERR_INVALID_REQUEST`) has no dedicated test — the same is true for the other format-validated fields on the sibling admin creates (engine `esn`, spare `spare_serial`, directive `directive_ref`), which the tests exercise only on valid inputs. Flagging for the PRD-finalization step.
- **Results artifacts:** all 8 `results.${i}.json` files exist on disk at `/home/ubuntu/github/CodingPRD/tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/workspace/implementation/results.{1..8}.json`, each showing passed == total == 62.

result: task_3406 sweep green — 62/62 tests pass in all 8 parallel rounds after fixing 39 PRD-violating letter+digit iata_code literals across 8 test files (test-side fix only; no deletions, no implementation changes).

Orchestrator verification: all 8 results.*.json read from disk — each passed=62/total=62/failed=0; newest source file (test_09_security_rbac.py) predates results.1.json by 118s, so no post-sweep edits; sweep evidence is fresh and consistent. Step 8 NOT skipped by the letter of the rule (test_suite/ fixes occurred), but the diff is fixture-literal-only with zero impl fixes — Step 8 prompt will explicitly permit the zero-edit outcome and I will verify with `diff -q`.

## Step 8: Finalize PRD — 2026-10-01T23:45:00.000Z

Subagent summary (verbatim):

Sanity check complete: `diff -q` confirms exactly one line changed (line 129, the §2.8 tier-4 insertion); both files are 357 lines. The edit traces to the step_7_diff sibling-paths flag and was verified against every string-validation path in the implementation.

result: PRD_FINALIZED.md written at /home/ubuntu/github/CodingPRD/tasks/task_3406_engine_aftermarket_service_agreements_flight_hour_pricing/workspace/PRD_FINALIZED.md — one-line insert pinning non-empty required strings; all other step_7_diff items verified already PRD-determined.

**Summary**

- **Line counts / %-delta:** PRD.md 357 lines, PRD_FINALIZED.md 357 lines; 1 line modified in place, 0 added/removed (0.0% line-count delta; 1 of 357 lines revised = 0.28% of lines touched).

- **Changes (one bullet per change):**
  - §2.8 (Validation Order, tier 4 "Request shape") — revise — inserted "(a required string field must not be the empty string)" after "Required fields are present" — implementation/validate.py:39-44 (`as_str` default `allow_empty=False` → `ERR_INVALID_REQUEST` on `""`); applied at all 16 `as_str(req_field(...))` callsites including the flagged admin creates: implementation/routes_admin.py:58 (`esn`), implementation/routes_leasing.py:43 (`spare_serial`), implementation/routes_directives.py:22 (`directive_ref`).

- **Per-edit pre-edit search log (the single edit):**
  - (a) Subject: negative validation branch for string fields on admin creates (the step_7_diff sibling-paths flag for `esn` / `spare_serial` / `directive_ref`, and the malformed-`iata_code` branch).
  - (b) Impl paths enumerated and read/grepped: validate.py:28-44 (`req_field`, `as_str`, `allow_empty` default); grep for `allow_empty` across implementation/ (zero `allow_empty=True` callsites); all 16 `as_str(` callsites (routes_admin.py:37,38,57,58,59; routes_directives.py:22,24; routes_leasing.py:43,44,83,84; routes_parts.py:32; routes_workscopes.py:46,57; routes_agreements.py:52,168); every `req_field(`/`opt_field(` call not wrapped in a typed validator (period → `as_period` at routes_billing.py:23-24 and routes_reports.py:25-26; items → `as_list` at routes_workscopes.py:77-80; datetime fields → `as_datetime`, confirmed at routes_visits.py:39-40 and routes_agreements.py:44-88 amend/draft helper); enum fields via `as_enum` ("" fails membership → 400); `allowed_sourcing_classes` via `as_str_list` + per-element membership check (routes_agreements.py:71-79, "" element → 400); query-param filters `?operator_id=`/`?agreement_id=` (routes_admin.py:100-106) — empty value filters to an empty list with 200, not an error.
  - (c) Wording adjustment: scoped the insertion to "a **required** string field" (parenthetical on the sentence's existing subject) rather than a universal "string values are non-empty" claim, so no statement is made about query parameters (where empty values do not error) or optional-then-present strings (e.g. `items[].directive_ref`, routes_workscopes.py:57), both of which behave differently/outside the flagged scope. Under-determined wording preferred per the no-new-mismatch rule.

- **step_7_diff items checked against implementation/ with no edit needed (already PRD-determined):**
  - 39 `iata_code` fixture literal fixes across 8 test files — pure test bug: PRD §3.1 (PRD.md:157) states verbatim "two-letter `iata_code` (two uppercase letters, unique across all operators)"; impl enforces `^[A-Z]{2}$` → `ERR_INVALID_REQUEST` (implementation/routes_admin.py:19, 38-40) and duplicate → `ERR_DUPLICATE_RESOURCE` (routes_admin.py:42-43), matching §2.8 tiers 4-5 (PRD.md:129-130) and §3.1 (PRD.md:165). No PRD silence.
  - Malformed-`iata_code` negative branch — determined by the same §3.1 format rule + §2.8 tier-4 generic `ERR_INVALID_REQUEST`.
  - `esn`/`spare_serial`/`directive_ref` presence, string type, and uniqueness — determined by §2.8 tier 4 ("Required fields are present, types are valid"), §2.8 tier 5 and §3.1:165 (uniqueness → `ERR_DUPLICATE_RESOURCE`); impl routes_admin.py:58,66-67, routes_leasing.py:43,48-49, routes_directives.py:22,40-41 confirmed no field-specific format regex exists on these three fields (only the universal non-empty rule, which is what the single edit pins).
  - test_helpers/ fixes: none listed; helper defaults ("TA", "FA") already PRD-faithful — nothing to check.
  - implementation/ fixes: none listed — no impl-side change to mirror.

- **diff -q result:** `Files workspace/PRD.md and workspace/PRD_FINALIZED.md differ` (exit=1); full diff confirms the only change is the single §2.8 tier-4 line shown above.

Orchestrator verification: `diff` run by orchestrator confirms exactly one line changed (line 129, §2.8 tier 4) — the `(a required string field must not be the empty string)` parenthetical, nothing else.

## Step 9: Complete PRD — 2026-10-02T00:25:00.000Z

Subagent summary (verbatim):

All edits verified. Implementation mtimes (≤22:25) predate this session — implementation/ is untouched, so no AST/import re-check is required. The diff shows 15 clean prose hunks, each traced against every impl path touching its subject.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` 357 lines / 59,139 chars → `workspace/PRD_COMPLETED.md` 361 lines / 63,942 chars (char delta +4,803).

**Counts:** 21 ambiguity-pins (in 15 edit hunks), 0 mismatch-revisions, 0 impl-fixes. The exhaustive walk covered: envelope/meta shape, pagination, logical clock + set_clock, OCC endpoints, the 10-tier validation order and every error binding, RBAC incl. Operator ownership chains, all calculations (effective rate/escalation/utilization band, both forecast variants, workscope determination, sourcing selector, lease cost, both recognition variants + onerous accrual), all six state machines with version-bump semantics, induction capacity, lease overlap/deposit, directive cascades, append-only entity shapes, and all 40 routes. Every load-bearing PRD rule checked out against the implementation — nothing required an impl fix or a mismatch-revision.

**Changes (all `insert`/`revise` ambiguity-pins):**
- §2.3 — insert — ambiguity — out-of-range/malformed limit/offset rejected with ERR_INVALID_REQUEST (not clamped) — implementation/envelope.py:53-73
- §2.3 — insert — ambiguity — created_at ties break by insertion order, incl. billing line iteration after enrolled_at/created_at — all list routes + calc.py:268
- §2.3 — insert — ambiguity — has_more = (offset + returned) < total_count — envelope.py:76-86
- §2.4 — insert — ambiguity — set_clock accepts any instant, not required to be monotonic — routes_admin.py:23-30
- §2.5 — insert — ambiguity — created_at/updated_at and lifecycle stamps read from the logical clock — storage.py:35-57 and all creation sites
- §2.5 — insert — ambiguity — a recomputation yielding the current value is not a modification (no updated_at refresh, no version bump) — cascade.py:40-55, calc.py:292-306
- §2.8 tier 4 — revise — ambiguity — body must be a JSON object, missing body = {}, undefined fields ignored — validate.py:14-21
- §2.9 — insert — ambiguity — Operator ownership evaluates after the resource chain resolves (404 precedes ownership), before state tiers — authz.py:32-36 + all ownership call sites
- §2.9 — insert — ambiguity — body-carried identifiers (operator_id, engine_id, spare_engine_id, shop_visit_id) resolve after tier-4 shape, before uniqueness/later tiers — routes_admin.py:57-65, routes_agreements.py:175-177, routes_leasing.py:89-94
- §2.10 — insert — ambiguity — calendar-month arithmetic clamps day-of-month to target month's last day — timeutil.py:36-42
- §3.2 — insert — ambiguity — no start_date/end_date ordering constraint at drafting or amend; escalation_anchor_date unconstrained — routes_agreements.py:66-69
- §3.2 — insert — ambiguity — amend does not apply contract_ref/start_date even if supplied — routes_agreements.py:149-150
- §3.3 — insert — ambiguity — report period may precede enrollment or the agreement term — routes_reports.py:34-41
- §3.5 — insert — ambiguity — scheduling requires only enrollment; engine may be IN_SHOP; planned_induction_date unconstrained — routes_visits.py:34-54
- §3.6 — revise — ambiguity — items omittable; MANDATORY_DIRECTIVE items must carry non-null directive_ref; item estimated_cost_usd not sign-constrained — routes_workscopes.py:41-80
- §3.6 — insert — ambiguity — appended directive items follow proposer items in directive creation order — calc.py:161-178
- §3.6 — insert — ambiguity — rejection does not re-check the visit's status (approval does) — routes_workscopes.py:131-141
- §3.7 — revise — ambiguity — sourcing allowed from REQUESTED or ESCALATED (other statuses → ERR_INVALID_STATE); ESCALATED re-runnable without override; failed re-run leaves ESCALATED unchanged — routes_parts.py:68-83
- §3.8 — insert — ambiguity — reservation imposes no visit-status or clock-window constraint — routes_leasing.py:79-119
- §3.8 — insert — ambiguity — whole days = window duration floored to 24-hour days (36h prices as 1) — calc.py:235-237
- §3.9 — insert — ambiguity — snapshot append permitted in any agreement status — routes_billing.py:66-76

**Impl fixes:** none.

**diff -q result:** `Files workspace/PRD_FINALIZED.md and workspace/PRD_COMPLETED.md differ` — 15 hunks, 38 changed/added lines.

**Impl integrity:** implementation/ not touched (confirmed via mtimes, all pre-session); AST/import check not applicable.

result: PRD_COMPLETED.md written with 21 ambiguity-pins (15 hunks, +4803 chars), zero mismatch-revisions and zero impl fixes; exhaustive impl walk found every load-bearing PRD rule already honored, diff confirmed non-identical.

Orchestrator verification: diff shows 38 changed/added lines (17 removed/21 added, consistent with 15 hunks); PRD_COMPLETED.md is 361 lines; 0 implementation .py files newer than results.1.json — Step 9 did not touch the implementation, so the green 8-round sweep from Step 7 remains valid and no re-run is required. All 8 results.*.json artifacts are on disk.

## Pipeline complete — 2026-10-02T00:30:00.000Z

Final state: 62/62 tests passing in all 8 parallel stability rounds (per-test-server isolation). Deliverables: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (62 tests, 10 files), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, workspace/implementation/ (22 files, 40 endpoints, in-memory Flask), results.{1..8}.json all green.
