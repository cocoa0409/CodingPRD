# test_helpers INTERFACE — frozen for Step 5b

Import everything from the barrel: `from test_helpers import <name>`.
Never `import test_helpers.api_client as ac` expecting a module — the barrel
re-exports the shared ApiClient **instance** under that name (verified:
`from test_helpers import api_client` binds an `ApiClient` instance).

## Framework generics re-exported (from prd_bench_local_runner.testing)

- `validate_success(response, expected_status=200) -> dict` — returns `data`.
  **Creating POSTs return 201: pass `201` explicitly** (PRD §4). All other
  successful ops (drives, actions, reads, clock advance) return 200.
- `validate_error(response, expected_error_id, expected_status=None) -> dict` —
  HTTP status auto-checked from the registered map; pass an `ApiErrorId` value
  (they are `str` enums).
- `validate_error_is_one_of(response, acceptable_error_ids: list) -> str` —
  error-precedence relaxation; returns the actual error_id; no status check.
- `validate_paginated(response) -> (list, meta)` — meta carries limit, offset,
  total_count, has_more.
- `get_success_data(response) -> dict` — lenient 2xx, used inside fixtures.
- `is_valid_uuid(s)`, `is_iso8601_timestamp(s)`, `assert_cost_precision(v)`,
  `assert_version_incremented(before, after)`, `assert_timestamp_format(s)`,
  `run_race(*callables)`, `assert_race_outcome(results, ok, fail)`,
  `assert_exactly_one_succeeds(a, b)`, `assert_at_least_one_succeeds(*rs)`,
  `build_user_headers(user_id, role)`, `NON_EXISTENT_UUID`.

## api_client.py — `api_client` (shared ApiClient), `ApiClient`

Base URL from `API_BASE_URL` env (harness-injected). All paths under `/api`.
Every method returns a raw `requests.Response`. Methods (payload-first for
bodies; `headers` always required; list methods take `params=None` dict):

- `set_clock(to_iso8601, headers)` — POST /api/_clock/set_current_utc → 200 `{current_utc}`
- `create_group_pricing_agreement(payload, headers)` → 201
- `list_group_pricing_agreements(headers, params=None)` — params: group_code, status, limit, offset
- `create_clinic(payload, headers)` → 201
- `get_clinic(clinic_id, headers)`
- `update_clinic(clinic_id, payload, headers)` — caseload_current_tests?/status?
- `create_placement_agreement(payload, headers)` → 201
- `get_placement_agreement(agreement_id, headers)`
- `list_placement_agreements(headers, params=None)` — clinic_id, status, limit, offset
- `approve_placement_agreement(agreement_id, headers)`
- `activate_placement_agreement(agreement_id, headers)`
- `request_renegotiation(agreement_id, headers)`
- `resolve_renegotiation(agreement_id, payload, headers)` — payload: accept, expected_agreement_version, new_minimum_cents?, waive_period_ids?
- `close_commitment_period(agreement_id, payload, headers)` — payload: period_month, expected_agreement_version → returns the CommitmentPeriod
- `list_commitment_periods(agreement_id, headers, params=None)` — period_status, limit, offset; ordered period_month ASC
- `record_payment(period_id, payload, headers)` — payload: amount_cents
- `create_analyzer(payload, headers)` → 201
- `get_analyzer(analyzer_id, headers)`
- `list_analyzers(headers, params=None)` — clinic_id, agreement_id, operational_status, limit, offset
- `update_analyzer(analyzer_id, payload, headers)` — operational_status?/connectivity_status?
- `create_service_case(payload, headers)` → 201
- `list_service_cases(analyzer_id, headers, params=None)` — status, limit, offset; serviced-unit OR loaner
- `update_service_case(case_id, payload, headers)` — action DISPATCH|RESOLVE|CANCEL, resolution_note?
- `create_reagent_order(payload, headers)` → 201 (pricing locked in response)
- `get_reagent_order(order_id, headers)`
- `list_reagent_orders(headers, params=None)` — clinic_id, agreement_id, status, limit, offset
- `update_reagent_order(order_id, payload, headers)` — status FULFILLED|CANCELLED
- `create_lab_test_order(payload, headers)` → 201
- `get_lab_test_order(order_id, headers)`
- `list_lab_test_orders(headers, params=None)` — clinic_id, analyzer_id, status, limit, offset
- `update_lab_test_order(order_id, payload, headers)` — action RECEIVE|RECORD_RESULT|DELIVER|CANCEL, result_value?
- `list_lab_test_results(order_id, headers, params=None)` — array of length 0|1

## api_errors.py

- `ApiErrorId` — 29 str-enum error ids (ERR_*), exact PRD §5 names.
- `HTTP_STATUS_CODES` — ApiErrorId → int, registered with the framework at import.
  Map: 400 → MISSING_OR_INVALID_USER_CONTEXT_HEADER, INVALID_REQUEST,
  INVALID_PROGRAM_TERMS, UNKNOWN_SKU, WINDOW_INVALID. 403 → INSUFFICIENT_PERMISSIONS,
  CLINIC_OWNERSHIP_MISMATCH. 404 → CLINIC/AGREEMENT/ANALYZER/ORDER/PERIOD/
  TEST_ORDER/SERVICE_CASE _NOT_FOUND. 409 → CLINIC_NOT_ACTIVE, AGREEMENT/
  ANALYZER/ORDER/PERIOD/TEST_ORDER/SERVICE_CASE _INVALID_STATE,
  CONNECTIVITY_NOT_ACTIVE, PROFICIENCY_LAPSED, PRICING_AGREEMENT_WINDOW_OVERLAP,
  PLACEMENT_TERM_OVERLAP. 422 → RENEGOTIATION_CASELOAD_DELTA_INSUFFICIENT.
  402 → OUTSTANDING_SHORTFALL_UNPAID, PAYMENT_AMOUNT_MISMATCH.
  412 → STALE_AGREEMENT_VERSION.

## types.py

Str enums: `UserRole` (PlatformAdmin/FinanceReviewer/ClinicManager/
FieldServiceEngineer/LaboratoryTechnician), `GroupType`, `GroupPricingAgreementStatus`,
`ClinicStatus`, `AnalyzerModel`, `ProgramType`, `AgreementStatus`,
`OperationalStatus`, `ConnectivityStatus`, `ProficiencyStanding`,
`ReagentOrderStatus`, `PeriodStatus`, `BillingStatus`, `TestOrderOrigin`,
`TestOrderKind`, `LabTestOrderStatus`, `DeliveryStatus`, `LabResultSource`,
`ProficiencyVerdict`, `ServiceCaseType`, `ServiceCaseStatus`,
`ServiceCaseAction`, `LabTestOrderAction`, `PriceSource`, `SkuFamily`.
TypedDicts: `SkuOverride{sku,unit_price_cents}`, `OrderLine{sku,quantity}`,
`PricingDetailLine` (total=False), and entity shapes `GroupPricingAgreement`,
`Clinic`, `PlacementAgreement`, `Analyzer`, `ReagentOrder`, `CommitmentPeriod`,
`LabTestOrder`, `ServiceCase` (all with id/created_at/updated_at/version),
`LabResult` (**no** updated_at/version — immutable record, PRD §2.5).

## constants.py (all values verified verbatim against PRD.md)

- `CLOCK_START_ISO = "2026-09-01T00:00:00Z"` (§2.4 startup default)
- Forward clock targets (all > start, legal single advances): `CLOCK_2026_09_01_20H`,
  `CLOCK_2026_09_02_09H`, `CLOCK_2026_10_01`, `CLOCK_2026_10_01_1S`,
  `CLOCK_2026_10_02`, `CLOCK_2026_10_05`, `CLOCK_2026_11_01`, `CLOCK_2027_01_15`,
  `CLOCK_2028_09_02` (past a 24-month end_date).
- `MAX_DISCOUNT_PCT=0.40`; `PRICE_TABLE` dict of 8 SKUs → {family,
  list_price_cents} (420/760/890/385/153/3000/3000/12500); `KNOWN_SKUS`;
  `QC_MATERIAL_SKUS` = ["QC_LEVEL_1","QC_LEVEL_2"].
- `ALLOWED_TERM_MONTHS=[24,36,48,60]`; `MIN_MONTHLY_MINIMUM_CENTS=50000`.
- `SHORTFALL_BILLING_RATE=0.80`; `SHORTFALL_BREACH_THRESHOLD_CENTS=250000`.
- `RENEGOTIATION_CASELOAD_DELTA_PCT=0.30`.
- `PROFICIENCY_TOLERANCE_PCT=0.05`; `QC_VALIDITY_DAYS=30`.
- `RESPONSE_SLA_HOURS=24`; `UPTIME_WINDOW_DAYS=90`; `UPTIME_WINDOW_HOURS=2160`;
  `UPTIME_BREACH_THRESHOLD_PCT=0.985`; `CALIBRATION_FREE_HOURS_PER_YEAR=16`;
  `UPTIME_SERVICE_CREDIT_CENTS=25000`.
- `DEFAULT_LIMIT=10`; `MIN_LIMIT=1`; `MAX_LIMIT=100`; `DEFAULT_OFFSET=0`.
- `ALL_ROLES` (5 strings); `UNKNOWN_UUID_1`/`UNKNOWN_UUID_2` (distinct
  never-allocated UUIDs for multi-FK 404 tests; framework also exports
  `NON_EXISTENT_UUID`).
- `TEST_DEFAULTS` dict: CLINIC_NAME "Vale Veterinary", BASELINE_CASELOAD 1000,
  MONTHLY_MINIMUM_CENTS 100000, PURCHASE_PRICE_CENTS 950000,
  LEASE_RATE_CENTS 320000, TERM_MONTHS 24, START_DATE = CLOCK_START_ISO,
  MODEL_RC "VETCHEM_300", MODEL_PURCHASE "VETHEMAT_500", EXPECTED_RESULT 200.0,
  PROF_PASS_RESULT 205.0, PATIENT_RESULT 7.7, TEST_CODE_PATIENT "CBC",
  TEST_CODE_PROFICIENCY "PROF-CHEM", TEST_CODE_SEND_OUT "CHEM17",
  GPA_EFFECTIVE_TO "2027-09-01T00:00:00Z".

## assertions.py

- `assert_common_fields(data, label="resource")` — uuid/created_at/updated_at/version≥1.
- `assert_group_pricing_agreement(data)`, `assert_clinic(data)`,
  `assert_placement_agreement(data)` (incl. program-conditional field shape),
  `assert_analyzer(data)`, `assert_reagent_order(data)`,
  `assert_commitment_period(data)`, `assert_lab_test_order(data)` (incl.
  origin/kind conditional shape), `assert_lab_result(data)` (asserts
  updated_at/version ABSENT), `assert_service_case(data)`.
- `assert_agreement_ledger_invariants(data)` — billed ≥ unpaid ≥ 0, credit ≥ 0.
- `assert_analyzer_fresh_dimensions(data)` — INSTALLED/NOT_CONFIGURED/LAPSED,
  qc_valid_until None, downtime 0, uptimes 1.0, version 1.
- `assert_money_cents(value, name)`; `assert_uptime_ratio(value, name)` (0..1, ≤4dp).
- `assert_open_period_shape(data)` — OPEN/NONE, provisional present, final three null.
- `assert_closed_period_shape(data)` — CLOSED, provisional null, shortfall ==
  max(0, minimum-fulfilled), billing consistent with billed_cents.
- `extract_pricing_lines(pricing_detail) -> list` — accepts a bare list OR an
  object with `lines` (PRD pins per-line content, not the container).
- `assert_pricing_line(line, sku, unit_price_cents, price_source, line_total_cents)`.

## factories.py (input fields only; optional fields omitted unless supplied)

- `unique_serial(prefix="SN") -> str`; `reagent_line(sku, quantity) -> dict`;
  `sku_override(sku, unit_price_cents) -> dict`.
- `create_clinic_payload(**overrides)` — name, caseload_baseline_tests;
  corporate_group_code/buying_group_code only when passed.
- `create_group_pricing_agreement_payload(**overrides)` — group_type CORPORATE,
  group_code CORP-1, window [CLOCK_START_ISO, 2027-09-01), discount 0.10;
  sku_overrides only when passed.
- `create_reagent_commitment_agreement_payload(clinic_id, **overrides)` —
  VETCHEM_300, 24mo, start CLOCK_START_ISO, monthly_minimum_cents 100000.
- `create_purchase_agreement_payload(clinic_id, **overrides)` — VETHEMAT_500,
  purchase_price_cents 950000.
- `create_lease_agreement_payload(clinic_id, **overrides)` — VETURINE_200,
  lease_rate_cents 320000.
- `create_placement_agreement_payload(clinic_id, **overrides)` — generic (RC default).
- `create_analyzer_payload(clinic_id, agreement_id, **overrides)` — serial
  auto-unique; is_loaner_unit only when truthy.
- `create_reagent_order_payload(clinic_id, agreement_id, **overrides)` —
  order_month "2026-09", lines [100 x VC300_CHEM_SLIDE].
- `create_lab_test_order_payload(clinic_id, **overrides)` — SEND_OUT/PATIENT default;
  analyzer_id/expected_result only when non-None.
- `create_patient_order_payload(clinic_id, analyzer_id, **overrides)` — IN_CLINIC PATIENT.
- `create_proficiency_order_payload(clinic_id, analyzer_id, **overrides)` —
  IN_CLINIC PROFICIENCY, expected_result 200.0.
- `create_send_out_order_payload(clinic_id, **overrides)` — SEND_OUT PATIENT, no analyzer.
- `create_service_case_payload(analyzer_id, **overrides)` — REPAIR default;
  loaner_analyzer_id only when passed. (PROFICIENCY_REMEDIATION is system-only.)
- `clock_set_payload(to_iso8601)`.
- `patch_clinic_payload(caseload_current_tests=None, status=None)`.
- `patch_analyzer_payload(operational_status=None, connectivity_status=None)`.
- `patch_reagent_order_payload(status)`.
- `patch_service_case_payload(action, resolution_note=None)`.
- `patch_lab_test_order_payload(action, result_value=None)`.
- `resolve_renegotiation_payload(accept, expected_agreement_version,
  new_minimum_cents=None, waive_period_ids=None)` — OCC field included.
- `close_commitment_period_payload(period_month, expected_agreement_version)` — OCC.
- `record_payment_payload(amount_cents)`.

## test_users.py

- `TEST_USERS` dict keys: platform_admin_headers, finance_reviewer_headers,
  clinic_manager_headers (**fallback only — matches no clinic; ownership-gated
  calls MUST use the builder**), field_service_engineer_headers,
  laboratory_technician_headers.
- `make_platform_admin_headers(user_id="test-platform-admin-1")`,
  `make_finance_reviewer_headers(user_id="test-finance-reviewer-1")`,
  `make_clinic_manager_headers(user_id)` — pass the real clinic id,
  `make_field_service_engineer_headers(user_id="test-field-service-engineer-1")`,
  `make_laboratory_technician_headers(user_id="test-laboratory-technician-1")`.

## fixtures.py (all return `data` payloads; lenient 2xx; ownership threaded)

Clock rule: `setup_*` fixtures assume the logical clock is still at
CLOCK_START_ISO on entry (fresh server per test). Fixtures that advance the
clock say so. OCC writes re-read the live version unless pinned.

- `iso_hours_after(base_iso, hours) -> str` — derived ISO arithmetic.
- Tier 1: `create_clinic(name=..., caseload_baseline_tests=1000,
  corporate_group_code=None, buying_group_code=None)`; `get_clinic(id)`;
  `update_caseload(clinic_id, caseload_current_tests)` (owning CM);
  `set_clinic_status(clinic_id, status)` (admin); `advance_clock(to_iso8601) ->
  current_utc`; `create_group_pricing_agreement(group_type="CORPORATE",
  group_code="CORP-1", effective_from=CLOCK_START_ISO,
  effective_to="2027-09-01T00:00:00Z", discount_pct=0.10, sku_overrides=None)`;
  `list_group_pricing_agreements(group_code=None, status=None) -> list`.
- Agreement lifecycle: `draft_reagent_commitment_agreement(clinic_id, **over)`;
  `draft_purchase_agreement(clinic_id, **over)`; `draft_lease_agreement(clinic_id,
  **over)`; `approve_agreement(id)`; `activate_agreement(id)` (snapshots
  baseline, creates periods); `get_agreement(id)`;
  `current_agreement_version(id) -> int`.
- Analyzers: `install_analyzer(clinic_id, agreement_id, serial_number=None,
  is_loaner_unit=False)`; `get_analyzer(id)`; `patch_analyzer(id,
  operational_status=None, connectivity_status=None)`; `enter_service(id)`;
  `set_connectivity(id, connectivity_status)`.
- Tier 2 composites:
  - `setup_clinic_with_active_reagent_commitment(baseline=1000,
    monthly_minimum_cents=100000, term_months=24, start_date=CLOCK_START_ISO,
    model="VETCHEM_300", clinic_kwargs=None) -> {"clinic","agreement"}` —
    agreement ACTIVE at version 3 with 24 OPEN periods.
  - `setup_clinic_with_active_purchase(...) -> {"clinic","agreement"}`.
  - `setup_clinic_with_rc_and_purchase_agreements(**clinic_kwargs) ->
    {"clinic","rc_agreement","purchase_agreement"}` (different models — no
    term-overlap conflict).
  - `setup_in_service_analyzer(serial_number=None, **scenario_kwargs) ->
    {"clinic","agreement","analyzer"}` (PURCHASE scenario; IN_SERVICE).
  - `setup_online_analyzer(serial_number=None, expected_result=200.0,
    pass_result=205.0, **scenario_kwargs) -> {"clinic","agreement","analyzer",
    "proficiency_order"}` — IN_SERVICE + connectivity ACTIVE + proficiency
    CURRENT via one PASS (qc_valid_until = resulted_at + 30d).
  - `setup_patient_order_ready(test_code="CBC", **kw)` — online analyzer +
    PATIENT order ORDERED; adds "patient_order".
  - `setup_recorded_patient_result(result_value=7.7, **kw)` — + RECORD_RESULT;
    adds "results" (1-element list).
- Lab pipelines: `place_patient_order(clinic_id, analyzer_id, test_code="CBC")`;
  `place_proficiency_order(clinic_id, analyzer_id, expected_result=200.0,
  test_code="PROF-CHEM")`; `place_send_out_patient_order(clinic_id,
  test_code="CHEM17")`; `record_in_clinic_result(order_id, clinic_id,
  result_value)`; `record_proficiency_pass(clinic_id, analyzer_id,
  expected_result=200.0, result=205.0)`; `receive_send_out_order(order_id)`;
  `record_send_out_result(order_id, result_value)`;
  `deliver_test_order(order_id, clinic_id)`; `cancel_test_order(order_id,
  clinic_id)`; `get_test_order(order_id)`; `get_test_order_results(order_id) -> list`.
- Reagent orders: `place_reagent_order(clinic_id, agreement_id,
  order_month="2026-09", lines=None)`; `fulfill_reagent_order(order_id,
  clinic_id)`; `cancel_reagent_order(order_id, clinic_id)`;
  `get_reagent_order(order_id)`.
- Commitment/billing/renegotiation: `list_commitment_periods(agreement_id,
  period_status=None) -> list`; `get_period_by_month(agreement_id, period_month)`;
  `close_commitment_period(agreement_id, period_month,
  expected_agreement_version=None)`; `close_periods_chronologically(agreement_id,
  period_months) -> list`; `record_exact_payment(period_id, amount_cents)`;
  `request_renegotiation(agreement_id, clinic_id)`;
  `resolve_renegotiation(agreement_id, accept, expected_agreement_version,
  new_minimum_cents=None, waive_period_ids=None)`.
- Tier 4/5 composites:
  - `setup_agreement_with_closed_period(period_month="2026-09",
    clock_to=CLOCK_2026_10_02, order_specs=(), fulfill_after_clock_advance=False)
    -> {"clinic","agreement","orders","period","periods"}` — clock advanced to
    clock_to; with no orders the period closes fulfilled 0 / billed 80000 /
    ISSUED; with a September order fulfilled AFTER the advance, provisional 0
    vs final 42000 diverge.
  - `setup_agreement_in_renegotiation(current_caseload=1400, baseline=1000,
    monthly_minimum_cents=100000) -> {"clinic","agreement"}` — agreement
    RENEGOTIATION, snapshot == baseline, proposed computed.
  - `setup_breached_agreement(close_months=("2026-09",...,"2026-12"),
    clock_to=CLOCK_2027_01_15) -> {"clinic","agreement","closed_periods"}` —
    4 x 80000c bills; 4th close crosses 250000 → agreement BREACHED, clinic
    SUSPENDED (both re-read post-cascade).
  - `setup_resolved_downtime_case(case_type="REPAIR", downtime_hours=20,
    base_clock=CLOCK_START_ISO, resolution_note=None) -> {"clinic","agreement",
    "analyzer","service_case"}` — PURCHASE scenario; case opened AT base_clock
    (must still be the live clock), dispatched, clock += downtime_hours,
    resolved; analyzer re-read.
- Service cases: `open_service_case(analyzer_id, case_type="REPAIR",
  loaner_analyzer_id=None)`; `dispatch_service_case(case_id)`;
  `resolve_service_case(case_id, resolution_note=None)`;
  `cancel_service_case(case_id)`; `list_service_cases(analyzer_id, status=None)
  -> list`.
