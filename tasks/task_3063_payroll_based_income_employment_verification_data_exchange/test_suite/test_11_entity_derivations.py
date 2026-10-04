"""Server-controlled fields, projections, pagination and currency reconciliation."""
from test_helpers import (
    onboard_employer,
    register_worker,
    register_product,
    register_authorized_verifier,
    create_verified_layout,
    create_batch,
    attach_record,
    validate_batch,
    capture_authorization,
    request_disclosure,
    generate_disclosure,
    freeze_employer_to_active,
    get_employer,
    get_record,
    get_worker,
    get_disclosure,
    set_clock,
    make_worker_headers,
    api,
    validate_success,
    validate_paginated,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)


def test_employer_server_controlled_defaults_on_onboarding(api):
    """PRD §3.1: "Onboarding initializes `feed_status` to `CURRENT`, `freeze_state` to
    `NONE`, `review_state` to `NONE`, `last_feed_received_date` to null,
    `missing_periods` and `currency_score` to 0, `total_records_contributed` to 0,
    `dispute_open_count` to 0, `compensation_earned_cents` to 0 and
    `counted_verification_records` to 0."
    PRD §2.4: "Every persisted resource carries an integer `version` that starts at 1".

    Design: Corner/entities/payload_feed_status_and_version_are_server_controlled
    """
    set_clock("2026-09-01T00:00:00Z")
    response = api.create_employer(
        {
            "legal_name": "Northwind Logistics",
            "fein": "123456789",
            "employer_type": "PRIVATE",
            "payroll_frequency": "MONTHLY",
        },
        TEST_USERS["admin_headers"],
    )
    employer = validate_success(response, 201)

    assert employer["feed_status"] == "CURRENT"
    assert employer["freeze_state"] == "NONE"
    assert employer["review_state"] == "NONE"
    assert employer["last_feed_received_date"] is None
    assert employer["version"] == 1
    assert employer["counted_verification_records"] == 0
    assert employer["compensation_earned_cents"] == 0


def test_employer_feed_status_derives_from_the_creation_instant_before_any_feed(api):
    """PRD §3.8: "when no batch has ever validated, the employer's own creation instant
    stands in for the missing feed date."
    PRD §2.4: "Every persisted resource carries an integer `version` that starts at 1 and
    increments by exactly 1 on every mutation".

    Design: Corner/entities/payload_feed_status_and_version_are_server_controlled
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = onboard_employer()
    assert employer["feed_status"] == "CURRENT"
    set_clock("2026-12-15T00:00:00Z")
    assert get_employer(employer["id"])["feed_status"] == "STALLED"


def test_product_rendered_field_set_is_projected_from_the_tier(api):
    """PRD §3.5: "When the nominal depth is at least 24 months, the separation date and
    the final-pay-period income join it."
    PRD §2.6: "`rendered_field_set` is projected at product creation and lists, sorted
    lexicographically ascending, the canonical field names the tier renders."

    Design: Corner/entities/verification_product_rendered_field_set_projection
    """
    set_clock("2026-09-01T00:00:00Z")
    product = register_product(
        product_code="BG-FULL24",
        tier="FULL_INCOME_HISTORY",
        requesting_class="BACKGROUND",
        base_fee_cents=2400,
        history_months_included=24,
        includes_employment_status=True,
    )
    rendered = product["rendered_field_set"]
    assert rendered == sorted(rendered)
    assert "separation_date" in rendered
    assert "final_pay_period_income_cents" in rendered
    assert product["history_months_included"] == 24
    assert product["includes_employment_status"] is True


def test_employment_only_product_projection_omits_the_deeper_fields(api):
    """PRD §3.5: "Four names are always present regardless of tier: the employer's legal
    name, `hire_date`, the employer feed status and the record match count."
    PRD §3.5: "an employment-only tier carries none".

    Design: Corner/entities/verification_product_rendered_field_set_projection
    """
    product = register_product(
        product_code="TENANT-E0",
        tier="EMPLOYMENT_ONLY",
        requesting_class="TENANT",
        base_fee_cents=900,
        history_months_included=0,
        includes_employment_status=True,
    )
    rendered = product["rendered_field_set"]
    assert "income_history" not in rendered
    assert "pay_rate" not in rendered
    assert "final_pay_period_income_cents" not in rendered
    assert "employer_legal_name" in rendered
    assert "hire_date" in rendered


def test_employer_list_honours_limit_total_count_and_has_more(api):
    """PRD §2.3: "`total_count` reports the number of resources matching the filters
    before the page is cut, and `has_more` reports whether further rows exist beyond the
    returned page."
    PRD §2.3: "The default `limit` is 10, its minimum is 1 and its maximum is 100".

    Design: Corner/cross_cutting_layers/paginated_employer_list_reports_total_count_and_has_more
    """
    onboard_employer(fein="123456789", legal_name="Northwind Logistics")
    onboard_employer(
        fein="223456789", legal_name="Cedar Grove Staffing",
        employer_type="STAFFING_AGENCY", frequency="WEEKLY",
    )
    onboard_employer(
        fein="323456789", legal_name="Lakeside County Human Services",
        employer_type="GOVERNMENT", frequency="SEMIMONTHLY",
    )

    response = api.list_employers(TEST_USERS["admin_headers"], params={"limit": 2, "offset": 0})
    rows, meta = validate_paginated(response)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_employer_list_second_page_has_no_more_rows(api):
    """PRD §2.3: "List operations accept a page size in `limit` and a start position in
    `offset`."

    Design: Corner/cross_cutting_layers/paginated_employer_list_reports_total_count_and_has_more
    """
    onboard_employer(fein="123456789", legal_name="Northwind Logistics")
    onboard_employer(
        fein="223456789", legal_name="Cedar Grove Staffing",
        employer_type="STAFFING_AGENCY", frequency="WEEKLY",
    )
    onboard_employer(
        fein="323456789", legal_name="Lakeside County Human Services",
        employer_type="GOVERNMENT", frequency="SEMIMONTHLY",
    )

    response = api.list_employers(TEST_USERS["admin_headers"], params={"limit": 2, "offset": 2})
    rows, meta = validate_paginated(response)
    assert len(rows) == 1
    assert meta["has_more"] is False


def test_employer_list_filter_by_fein_returns_one_row(api):
    """PRD §4: "GET | /work-number/employers | List contributors with feed currency and
    freeze posture. | PlatformAdmin".

    Design: Corner/cross_cutting_layers/paginated_employer_list_reports_total_count_and_has_more
    """
    onboard_employer(fein="123456789", legal_name="Northwind Logistics")
    onboard_employer(
        fein="223456789", legal_name="Cedar Grove Staffing",
        employer_type="STAFFING_AGENCY", frequency="WEEKLY",
    )
    response = api.list_employers(TEST_USERS["admin_headers"], params={"fein": "223456789"})
    rows = validate_success(response, 200)
    assert len(rows) == 1
    assert rows[0]["legal_name"] == "Cedar Grove Staffing"


def _two_employer_worker():
    employer_a = onboard_employer(fein="123456789", legal_name="Northwind Logistics")
    employer_b = onboard_employer(
        fein="223456789", legal_name="Cedar Grove Staffing",
        employer_type="STAFFING_AGENCY", frequency="WEEKLY",
    )
    worker = register_worker()
    layout_a = create_verified_layout(employer_a["id"])
    batch_a = create_batch(
        employer_a["id"], layout_a["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    attach_record(employer_a["id"], worker["id"], batch_a["id"])
    validate_batch(employer_a["id"], batch_a["id"])

    layout_b = create_verified_layout(employer_b["id"])
    batch_b = create_batch(
        employer_b["id"], layout_b["id"], pay_period_end_date="2026-08-28T00:00:00Z", record_count=900
    )
    attach_record(
        employer_b["id"], worker["id"], batch_b["id"],
        employment_status="TERMINATED", hire_date="2020-03-01T00:00:00Z",
        separation_date="2024-06-30T00:00:00Z", pay_rate_cents=210000,
    )
    validate_batch(employer_b["id"], batch_b["id"])
    freeze_employer_to_active(employer_b["id"], reason_code="DATA_QUALITY_INVESTIGATION")
    return employer_a, employer_b, worker


def test_frozen_record_is_held_from_the_disclosure_file(api):
    """PRD §3.6: "The file's included set is the worker's spans whose `record_state` is
    `PENDING_VERIFICATION`, `VERIFIED` or `DISPUTED`, whose `updated_at` falls within the
    3650-day disclosure window ending at the current instant, and whose `currency_state`
    is not `FROZEN`."
    PRD §3.6: "an immutable span is held unless its last update falls inside the window,
    and a frozen span is always held regardless of its age".

    Design: Corner/cross_cutting_layers/frozen_record_withheld_from_disclosure_file
    """
    employer_a, employer_b, worker = _two_employer_worker()
    disclosure = request_disclosure(worker["id"])
    generate_disclosure(worker["id"], disclosure["id"])
    detail = get_disclosure(disclosure["id"], worker["id"])

    assert detail["included_record_count"] == 1
    assert detail["held_record_count"] == 1


def test_disclosure_counts_reconcile_without_silent_drops(api):
    """PRD §3.6: "the file reports the two populations as `included_record_count` and
    `held_record_count`."
    PRD §3.6: "Inside the file, records are ordered by `hire_date` descending and then by
    `created_at` ascending, and each carries a provenance block recording the employer's
    legal name, the employer's feed status and the employer's last feed received date."

    Design: Corner/cross_cutting_layers/frozen_record_withheld_from_disclosure_file
    """
    employer_a, employer_b, worker = _two_employer_worker()
    disclosure = request_disclosure(worker["id"])
    generate_disclosure(worker["id"], disclosure["id"])
    detail = get_disclosure(disclosure["id"], worker["id"])

    total = len(validate_success(
        api.list_records(TEST_USERS["admin_headers"], params={"covered_worker_id": worker["id"]}),
        200,
    ))
    assert detail["included_record_count"] + detail["held_record_count"] == total


def test_derived_currency_reconciles_after_a_recovery_batch(api):
    """PRD §3.3: "When the feed returns to `CURRENT` — which happens through a fresh
    validated batch — records in `STALE` are restored to `CURRENT` by that same
    validation."
    PRD §3.8: "`STALLED` once staleness exceeds three intervals".

    Design: Corner/cross_cutting_layers/derived_currency_field_reconciles_after_employer_feed_recovery
    """
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch_1 = create_batch(
        employer["id"], layout["id"], batch_sequence=1,
        pay_period_end_date="2026-05-31T00:00:00Z", record_count=900,
    )
    record = attach_record(employer["id"], worker["id"], batch_1["id"])
    validate_batch(employer["id"], batch_1["id"])

    set_clock("2026-09-30T00:00:00Z")
    assert get_employer(employer["id"])["feed_status"] == "STALLED"
    assert get_record(record["id"])["currency_state"] == "STALE"

    batch_2 = create_batch(
        employer["id"], layout["id"], batch_sequence=2,
        pay_period_end_date="2026-09-30T00:00:00Z", record_count=900,
    )
    validate_batch(employer["id"], batch_2["id"])

    employer_after = get_employer(employer["id"])
    assert employer_after["feed_status"] == "CURRENT"
    assert get_record(record["id"])["currency_state"] == "CURRENT"
    assert employer_after["last_feed_received_date"] == "2026-09-30T00:00:00.000Z"


def test_occ_stale_worker_version_rejects_a_second_authorization_capture(api):
    """PRD §2.5: "the capture must supply `expected_covered_worker_version`, the caller's
    last observed `version` of the `CoveredWorker` row, and a value that no longer equals
    the row's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.5: "a worker may legitimately hold several live authorizations for different
    requesting parties, so a second capture is not wrong in itself".

    Design: Corner/cross_cutting_layers/occ_stale_covered_worker_version_rejects_authorization_capture
    """
    worker = register_worker()
    verifier_a = register_authorized_verifier(legal_name="Meridian Home Lending")
    verifier_b = register_authorized_verifier(legal_name="Harbor Mortgage Group")

    stale_version = worker["version"]
    capture_authorization(worker, verifier_a, worker_version=stale_version)

    response = api.create_authorization(
        {
            "covered_worker_id": worker["id"],
            "verifier_id": verifier_b["id"],
            "permitted_purpose": "MORTGAGE_CREDIT_DECISION",
            "expected_covered_worker_version": stale_version,
        },
        make_worker_headers(worker["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert verifier_a["id"] != verifier_b["id"]


def test_re_read_version_admits_a_second_capture_and_bumps_the_worker(api):
    """PRD §3.2: "To let a requesting party verify them, the worker captures a
    `ConsumerAuthorization` naming the `verifier_id`, the `permitted_purpose`, and
    carrying `expected_covered_worker_version`."
    PRD §3.2: "Capturing an authorization bumps the worker's `version`."

    Design: Corner/cross_cutting_layers/occ_stale_covered_worker_version_rejects_authorization_capture
    """
    worker = register_worker()
    verifier_a = register_authorized_verifier(legal_name="Meridian Home Lending")
    verifier_b = register_authorized_verifier(legal_name="Harbor Mortgage Group")
    capture_authorization(worker, verifier_a)

    fresh_version = get_worker(worker["id"])["version"]
    response = api.create_authorization(
        {
            "covered_worker_id": worker["id"],
            "verifier_id": verifier_b["id"],
            "permitted_purpose": "MORTGAGE_CREDIT_DECISION",
            "expected_covered_worker_version": fresh_version,
        },
        make_worker_headers(worker["id"]),
    )
    data = validate_success(response, 201)
    assert get_worker(worker["id"])["version"] == fresh_version + 1
    assert data["verifier_id"] == verifier_b["id"]