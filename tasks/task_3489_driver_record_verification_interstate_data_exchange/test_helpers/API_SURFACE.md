# test_helpers API surface (frozen)

Every public name the test suite may rely on. Import anything below from
`test_helpers` directly (the package re-exports it), or from the module that
defines it. All endpoint methods return the raw `requests.Response`; validate
with `assert_created` / `assert_ok` / `assert_success(resp, status)` /
`assert_error(resp, ApiErrorId.X)` / `assert_list_page(resp)` — never assume a
default status (creates answer 201, modifications and reads answer 200).

Auth: registrar calls MUST use `make_jurisdiction_registrar_headers(jurisdiction["id"])`
— a placeholder id fails ownership and even driver registration (the
registrar's jurisdiction must exist). Opaque roles use their shared header
constants. The logical clock starts at `DEFAULT_CLOCK_ISO`; fixtures that need
another instant call `set_clock` explicitly, and date helpers always take the
relevant clock instant rather than reading the wall clock.

## api_client.py

- `API_PREFIX = "/driver-exchange"`
- `class ApiClient(GenericApiClient)` — one method per endpoint; constructor
  takes optional `base_url` (else `API_BASE_URL` env):
  - `set_clock(payload, headers)` — POST `/driver-exchange/_clock/set_current_utc`
  - `create_jurisdiction(payload, headers)` / `get_jurisdiction(id, headers)` /
    `update_jurisdiction(id, payload, headers)` (PATCH)
  - `list_jurisdiction_participations(id, headers, params=None)` /
    `list_jurisdiction_fee_invoices(id, headers, params=None)` /
    `list_jurisdiction_vehicle_titles(id, headers, params=None)`
  - `create_participation(payload, headers)` / `grant_certification(participation_id, headers)`
  - `create_certification(payload, headers)` / `get_certification(id, headers)` /
    `list_certifications(headers, params=None)` /
    `complete_certification(certification_id, payload, headers)`
  - `create_driver(payload, headers)` / `get_driver(id, headers)`
  - `create_driver_record(payload, headers)` / `get_driver_record(id, headers)` /
    `list_driver_records(headers, params=None)`
  - `list_record_convictions(record_id, headers, params=None)` /
    `list_record_disqualifications(record_id, headers, params=None)`
  - `create_conviction(payload, headers)` /
    `create_disqualification(payload, headers)` /
    `overturn_disqualification(disqualification_id, headers)`
  - `create_license(payload, headers)` / `get_license(id, headers)` /
    `list_licenses(headers, params=None)` /
    `post_verification_result(license_id, payload, headers)` /
    `reinstate_license(license_id, headers)`
  - `create_license_transfer(payload, headers)` / `get_license_transfer(id, headers)` /
    `list_license_transfers(headers, params=None)` /
    `record_surrender(transfer_id, headers)` /
    `contest_transfer(transfer_id, payload, headers)` /
    `complete_transfer(transfer_id, headers)`
  - `create_vehicle_title(payload, headers)` /
    `create_title_transfer(payload, headers)` / `get_title_transfer(id, headers)` /
    `list_title_transfers(headers, params=None)` /
    `complete_title_transfer(transfer_id, headers)`
  - `create_fee_invoice(payload, headers)` / `dispute_invoice(id, payload, headers)` /
    `reissue_invoice(id, payload, headers)` / `settle_invoice(id, payload, headers)` /
    `finalize_audit(id, payload, headers)`
  - `raw(method, path, payload=None, headers=None, params=None)` — escape hatch
- `make_api_client(base_url=None) -> ApiClient` — the way to obtain a client
  (there is deliberately no module-level instance)

## api_errors.py

- `class ApiErrorId(str, Enum)` — all 33 catalogue ids
  (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, `ERR_INSUFFICIENT_PERMISSIONS`,
  `ERR_JURISDICTION_OWNERSHIP_MISMATCH`, `ERR_INVALID_REQUEST`, `ERR_STALE_VERSION`,
  the eleven `ERR_*_NOT_FOUND`, `ERR_JURISDICTION_NOT_ACTIVE`, `ERR_INVALID_STATE`,
  `ERR_PARTICIPATION_NOT_CERTIFIED`, `ERR_RECORD_NOT_ACTIVE`, `ERR_LICENSE_NOT_ACTIVE`,
  `ERR_GRANT_REQUIRES_PASSED_CERTIFICATION`, `ERR_ACTIVE_DISQUALIFICATION`,
  `ERR_BRAND_DISCLOSURE_MISMATCH`, `ERR_RECORD_ALREADY_HELD`,
  `ERR_RECORD_HELD_BY_OTHER_JURISDICTION`, `ERR_TRANSFER_ALREADY_IN_FLIGHT`,
  `ERR_VIN_ALREADY_TITLED`, `ERR_PARTICIPATION_ALREADY_EXISTS`,
  `ERR_JURISDICTION_CODE_TAKEN`, `ERR_INVALID_WINDOW`, `ERR_CERT_WINDOW_OVERLAP`,
  `ERR_OUTSIDE_TEST_WINDOW`, `ERR_DISQUALIFICATION_OVERLAP`,
  `ERR_SAME_JURISDICTION_TRANSFER`, `ERR_FEE_AMOUNT_MISMATCH`)
- `HTTP_STATUS_CODES: dict[ApiErrorId, int]` — registered with the framework at
  import, so `validate_error`/`assert_error` auto-check the HTTP status

## assertions.py

- `assert_success(response, expected_status) -> dict` — status is a REQUIRED
  argument (no default)
- `assert_created(response) -> dict` (201) · `assert_ok(response) -> dict` (200)
- `assert_error(response, error_id) -> dict` — accepts `ApiErrorId` or str;
  HTTP status cross-checked from the registered catalogue
- `assert_list_page(response) -> (rows, meta)` — paginated list envelope
- `canonical_instant(value) -> str|None` — normalise to `...T...:... .mmmZ`;
  `assert_same_instant(actual, expected, label="instant")`
- `assert_mutable_common_fields(data)` — id/created_at/updated_at/version shape
- Entity shape assertions: `assert_jurisdiction`, `assert_participation`,
  `assert_certification`, `assert_driver_identity`, `assert_driver_record`,
  `assert_conviction` (also asserts updated_at/version are ABSENT),
  `assert_disqualification` (window order + OVERTURNED carries overturned_at),
  `assert_license`, `assert_license_transfer` (new_license_id only when
  COMPLETED), `assert_vehicle_title`, `assert_title_transfer` (carried_brands
  sorted-union shape), `assert_fee_invoice` (status-dependent fields;
  AUDITED reconciles final - settled == adjustment)

## factories.py

- Clock arithmetic (all anchored to an explicit clock instant, default
  `DEFAULT_CLOCK_ISO`; never wall clock):
  `date_plus_days(iso_date, days)`, `date_minus_days(iso_date, days)`,
  `instant_plus_days(iso_instant, days)`, `clock_date_of(clock_iso)`,
  `conviction_dates_for(days_before_posting, clock_iso=..., offense_gap_days=10)
  -> (offense_date, conviction_date)` (30 = timely, 31+ = late),
  `expected_dq_window(clock_iso, duration_days) -> (start_date, end_date)`
- Payload factories (all accept `**overrides`):
  `clock_payload(to_iso8601)`,
  `jurisdiction_payload(code="AA", name=..., fee_tier="TIER_1")`,
  `membership_transition_payload(status)`,
  `participation_payload(jurisdiction_id, system="POINTER_NETWORK")`,
  `certification_payload(participation_id, window_start=DEFAULT_CERT_WINDOW_START,
  window_end=DEFAULT_CERT_WINDOW_END)`,
  `certification_completion_payload(result="PASSED", score=95)` (score=None omits it),
  `driver_payload(...)`, `driver_record_payload(driver_id, expected_driver_version)`,
  `conviction_payload(record_id, offense_date=None, conviction_date=None,
  severity="NON_CMV", points=2, clock_iso=DEFAULT_CLOCK_ISO)` (dates default to a
  timely posting against `clock_iso`),
  `disqualification_payload(record_id, start_date=..., end_date=...)`,
  `license_payload(driver_id, license_class="STANDARD")`,
  `verification_result_payload(check_type="SSN", result="VERIFIED")`,
  `license_transfer_payload(driver_id, prior_license_id, expected_driver_version)`,
  `contest_payload(reason="DATA_MISMATCH")`,
  `vehicle_title_payload(vin="1HGCM82633A004352", brands=None)` (None omits the field),
  `title_transfer_payload(vehicle_title_id, disclosed_brands=None)`,
  `fee_invoice_payload(jurisdiction_id, fiscal_year=2027, projected_volume=8000)`,
  `dispute_payload(reason=...)`, `reissue_payload(projected_volume)`,
  `settle_payload(amount_cents)`, `finalize_audit_payload(actual_volume_quarters=None)`

## constants.py

- Clock: `DEFAULT_CLOCK_ISO` ("2026-09-01T00:00:00Z"), `DEFAULT_CLOCK_DATE`,
  `DEFAULT_CERT_WINDOW_START` ("2026-08-01T00:00:00Z"),
  `DEFAULT_CERT_WINDOW_END` ("2027-12-31T00:00:00Z" — contains every instant
  the scenarios reach)
- Points/DQ: `POINTS_WINDOW_DAYS` 1095, `POINTS_THRESHOLD` 12,
  `POINTS_BASE_DAYS` 90, `MAJOR_BASE_DAYS` 365, `DURATION_MULTIPLIER_CAP` 3,
  `CONVICTION_POSTING_DEADLINE_DAYS` 30 (inclusive), `CONVICTION_POINTS_MIN` 1,
  `CONVICTION_POINTS_MAX` 6, `TIMELINESS_SCORE_FULL_BP` 10000
- Dues: `BASE_FEE_CENTS` 2_500_000, `ANNUAL_CAP_CENTS` 20_000_000,
  `TIER1_LIMIT` 10_000, `TIER2_LIMIT` 50_000, `TIER1_RATE_CENTS` 12.5,
  `TIER2_RATE_CENTS` 10.5, `TIER3_RATE_CENTS` 8.5, `MULTIPLIER_FLOOR` 0.85,
  `DISCOUNT_STEP` 0.05, `AUDIT_QUARTERS_COUNT` 4
- Pagination: `DEFAULT_PAGE_LIMIT` 10, `MIN_PAGE_LIMIT` 1, `MAX_PAGE_LIMIT` 100,
  `DEFAULT_PAGE_OFFSET` 0; `VIN_LENGTH` 17

## types.py

- `class UserRole(str, Enum)` — ASSOCIATION_ADMIN, JURISDICTION_REGISTRAR,
  CERTIFICATION_ENGINEER, FEDERAL_VERIFIER, AUDIT_AUTHORITY
- Enums (values are the wire strings): `FeeTier`, `MembershipStatus`,
  `SystemName`, `ParticipationStatus`, `CertificationStatus`,
  `LawfulStatusBasis`, `RecordStatus`, `LicenseClass`, `LicenseStatus`,
  `CheckStatus`, `CheckType`, `TransferStatus`, `ConvictionSeverity`,
  `DisqualificationBasis`, `DisqualificationStatus` (derived),
  `TitleBrand`, `TitleStatus`, `TitleTransferStatus`, `InvoiceStatus`
- TypedDicts: `Jurisdiction`, `SystemParticipation`, `ConnectionCertification`,
  `DriverIdentity`, `DriverRecord`, `License`, `LicenseTransfer`, `Conviction`
  (id + created_at only — no updated_at/version), `Disqualification`,
  `VehicleTitle`, `TitleTransfer`, `FeeInvoice`

## test_users.py

- `TEST_USERS: dict` — shared header dicts keyed `association_admin_headers`,
  `jurisdiction_registrar_headers` (fallback only; not ownership-safe),
  `certification_engineer_headers`, `federal_verifier_headers`,
  `audit_authority_headers`
- Ready-made constants: `ASSOCIATION_ADMIN_HEADERS`,
  `CERTIFICATION_ENGINEER_HEADERS`, `FEDERAL_VERIFIER_HEADERS`,
  `AUDIT_AUTHORITY_HEADERS`, plus the opaque `*_ID` strings
- `EMPTY_HEADERS` — no identity headers (header-presence rung probes)
- `make_jurisdiction_registrar_headers(jurisdiction_id) -> dict` — THE
  registrar builder; pass the real Jurisdiction id
- `headers_without_user_id(role=...)`, `headers_without_role(user_id=...)`

## fixtures.py

All take the `ApiClient` first, use the lenient setup reader (failures surface
as setup errors with the response body), and thread registrar identity through
`make_jurisdiction_registrar_headers`. Context builders return a dict:
`setup_certified_jurisdiction` → `{jurisdiction, jurisdiction_id,
registrar_headers, participations: {system: participation}}`;
`setup_driver_record` / `setup_verified_license` extend it in place with
`driver`/`driver_id`/`record`/`record_id`/`driver_version`/`license`/`license_id`.

- Clock: `set_clock(api, to_iso8601)`,
  `advance_clock_past(api, iso_date)` (sets 00:00:00Z the next day)
- Jurisdictions: `create_jurisdiction(api, code="AA", name=None, fee_tier=...)`,
  `transition_jurisdiction(api, id, status)`, `activate_jurisdiction`,
  `suspend_jurisdiction` (fires both cascade links), `withdraw_jurisdiction`,
  `read_jurisdiction`
- Certification pipeline: `enroll_participation(api, jurisdiction_id, system)`,
  `schedule_certification(api, participation_id, window_start=..., window_end=...)`,
  `complete_certification(api, cert_id, result="PASSED", score=95)`,
  `grant_certification(api, participation_id)`,
  `certify_participation(api, participation_id, score=95, window_start=...,
  window_end=...)` (schedule+PASSED+grant),
  `setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",),
  fee_tier=..., activate=True)` (activation requires POINTER in systems),
  `read_participations`, `read_certification`, `list_certifications`
- Drivers/records/licenses: `register_driver(api, jurisdiction_id, **overrides)`,
  `read_driver`, `current_driver_version(api, driver_id)`,
  `claim_driver_record(api, driver_id, jurisdiction_id, expected_driver_version=None)`
  (reads the current version when omitted),
  `setup_driver_record(api, ctx, **driver_overrides)`,
  `read_record`, `list_driver_records(api, params=None)`,
  `issue_license(api, driver_id, jurisdiction_id, license_class=...)`,
  `verify_license(api, license_id, ssn_result=..., lawful_status_result=...)`
  (posts both dimensions; both VERIFIED → ACTIVE, any FAILED → DENIED),
  `setup_verified_license(api, ctx, license_class=..., **driver_overrides)`,
  `read_license`, `list_licenses(api, params=None)`,
  `reinstate_license(api, license_id, issuing_jurisdiction_id)`
- Convictions/DQ: `setup_conviction_world(api, code="AA", **driver_overrides)`
  (POINTER+COMMERCIAL certified, record held),
  `post_conviction(api, record_id, holding_jurisdiction_id, offense_date=None,
  conviction_date=None, severity=..., points=2, clock_iso=DEFAULT_CLOCK_ISO)`,
  `post_convictions(api, record_id, holding_jurisdiction_id, specs)`,
  `read_record_convictions(api, record_id)`,
  `create_manual_disqualification(api, record_id, start_date, end_date)`,
  `overturn_disqualification(api, disqualification_id)`,
  `read_record_disqualifications(api, record_id)` (derived statuses at the
  current clock),
  `setup_suspended_commercial_license(api, code="AA", conviction=None)` (verified
  COMMERCIAL license dropped to SUSPENDED by an AUTO_MAJOR DQ; ctx gains
  `disqualification` and a refreshed `license`)
- License transfers: `initiate_transfer(api, driver_id, prior_license_id,
  to_jurisdiction_id, expected_driver_version=None)`, `surrender_transfer(api,
  transfer_id, from_jurisdiction_id)`, `contest_transfer(api, transfer_id,
  to_jurisdiction_id, reason=...)`, `complete_transfer(api, transfer_id,
  to_jurisdiction_id)`, `read_license_transfer`,
  `list_license_transfers(api, params=None)`,
  `setup_transfer_world(api, from_code="AA", to_code="BB", license_class=...,
  stage="INITIATED", contest_reason=...)` — stage ∈ INITIATED /
  SURRENDER_RECORDED / CONTESTED / COMPLETED; returns `{from_ctx, to_ctx,
  transfer, transfer_id, driver_version}`
- Titles: `create_vehicle_title(api, jurisdiction_id, vin=..., brands=None)`,
  `create_title_transfer(api, vehicle_title_id, to_jurisdiction_id,
  disclosed_brands=None)`, `complete_title_transfer(api, transfer_id,
  to_jurisdiction_id)`, `read_title_transfer`,
  `list_title_transfers(api, params=None)`,
  `list_jurisdiction_titles(api, jurisdiction_id, params=None)` (the way to
  read title state — no single-get endpoint exists),
  `setup_title_world(api, from_code="AA", to_code="BB", vin=...,
  source_brands=None)` → `{from_ctx, to_ctx, title, title_id}`
- Fees: `issue_fee_invoice(api, jurisdiction_id, fiscal_year=2027,
  projected_volume=8000)`, `dispute_invoice(api, invoice_id, jurisdiction_id,
  reason=...)`, `reissue_invoice(api, invoice_id, projected_volume)`,
  `settle_invoice(api, invoice, amount_cents=None)` (defaults to the invoice's
  `provisional_amount_cents` — exact-change settlement),
  `finalize_audit(api, invoice_id, actual_volume_quarters)`,
  `list_jurisdiction_invoices(api, jurisdiction_id, params=None)` (the way to
  read invoice state),
  `setup_invoice(api, code="AA", systems=..., fee_tier=..., fiscal_year=2027,
  projected_volume=8000, stage="ISSUED")` — stage ∈ ISSUED / DISPUTED /
  SETTLED; ctx gains `invoice`/`invoice_id`/`provisional_amount_cents`
