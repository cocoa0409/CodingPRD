"""Entity corners: creation round-trips, required fields, computed defaults,
existence, pagination, enum constraints and parent-child listing."""

from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, api_client, assert_employer,
    class_code_entry, create_employer, create_policy, is_iso8601_timestamp,
    is_valid_uuid, set_clock, setup_rating_table, validate_error,
    validate_paginated, validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_employer_create_round_trips_inputs_and_applies_system_defaults(api):
    """PRD §3.1: "An employer's status starts as ACTIVE and may later move to
    SUSPENDED."
    PRD §2.4: "Every resource in the system — Employer, StateRatingTable, Policy,
    PolicyClassCode, PayrollIntegration, PayrollReport, PayrollLine,
    PremiumInvoice, ClassCodeDispute, AuditReconciliation, and TaxFilingRecord —
    carries the same four system-managed properties".

    Design: Corner/entities/employer_create_round_trips_all_fields_with_system_defaults
    """
    res = api.create_employer({
        "legal_name": "Acme Anvils",
        "fein": "10-0000001",
        "contact_email": "ops@acme.example",
        "home_state": "CA",
    }, ADMIN)
    assert res.status_code == 201
    body = res.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id")
    assert body["meta"].get("api_request_timestamp")

    employer = body["data"]
    assert_employer(employer)
    assert employer["status"] == "ACTIVE", "the default is applied by the system"
    assert employer["legal_name"] == "Acme Anvils"
    assert employer["fein"] == "10-0000001"
    assert is_valid_uuid(employer["id"])
    assert is_iso8601_timestamp(employer["created_at"])
    assert is_iso8601_timestamp(employer["updated_at"])
    assert isinstance(employer["version"], int) and employer["version"] >= 1


def test_employer_create_without_contact_email_is_rejected(api):
    """PRD §2.9: "request well-formedness — required fields present, enum values
    valid, and every date range satisfying a start strictly before its end, with
    violations rejected as ERR_INVALID_REQUEST (HTTP 400)."
    PRD §3.1: "a contact_email that is required so that billing and audit notices
    always have a recipient".

    Design: Corner/entities/employer_create_missing_contact_email_returns_invalid_request
    """
    res = api.create_employer({
        "legal_name": "No Email Co",
        "fein": "10-0000002",
        "home_state": "CA",
    }, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_fresh_policy_has_zero_aggregates_and_initial_statuses(api):
    """PRD §3.2: "A new policy's coverage_status is PENDING, while its
    reporting_status starts COMPLIANT, its billing_status starts CURRENT, and its
    consecutive_missed_cycles starts at 0."
    PRD §2.8: "cumulative_billed_cents is the sum of total_cents over all of the
    policy's invoices currently in ISSUED or PAID status; cumulative_collected_cents
    is the sum of total_cents over invoices in PAID status only."

    Design: Corner/entities/policy_computed_aggregates_ignore_client_input
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Computed Fields Co",
                               fein="10-0000003",
                               contact_email="c@computed.example",
                               home_state="CA")
    policy = validate_success(api.create_policy({
        "employer_id": employer["id"],
        "policy_number": "WC-CMP-001",
        "effective_date": "2026-09-01T00:00:00Z",
        "expiry_date": "2027-09-01T00:00:00Z",
        "experience_mod": 1.0,
        "class_codes": [class_code_entry("CA", "8810", 1000000)],
        # Computed aggregates are server-maintained; client input must not set them.
        "cumulative_billed_cents": 999999,
        "cumulative_collected_cents": 888888,
    }, UW), 201)
    assert policy["coverage_status"] == "PENDING"
    assert policy["reporting_status"] == "COMPLIANT"
    assert policy["billing_status"] == "CURRENT"
    assert policy["consecutive_missed_cycles"] == 0
    # With no invoices yet, both sums over the empty set are zero.
    assert policy["cumulative_billed_cents"] == 0
    assert policy["cumulative_collected_cents"] == 0


def test_get_policy_with_nonexistent_id_returns_not_found(api):
    """PRD §2.9: "the first identifier in the path that does not correspond to an
    existing resource produces ERR_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/get_policy_with_nonexistent_id_returns_not_found
    """
    res = api.get_policy(NON_EXISTENT_UUID, UW)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_policies_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "Paginated list responses carry limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/entities/policies_list_paginates_with_total_count_and_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    for n in (1, 2, 3):
        create_policy(employer["id"], policy_number=f"WC-PAG-00{n}",
                      class_codes=[class_code_entry("CA", "8810", 100000)])

    page1, meta1 = validate_paginated(
        api.list_policies(UW, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_policies(UW, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_state_rating_table_rejects_unknown_ot_basis_value(api):
    """PRD §2.9: "request well-formedness — required fields present, enum values
    valid, and every date range satisfying a start strictly before its end, with
    violations rejected as ERR_INVALID_REQUEST (HTTP 400)."
    PRD §3.1: "the overtime treatment ot_basis — GROSS when overtime premium hours
    count at the full time-and-a-half wage, NET when only the straight-time wage
    counts".

    Design: Corner/entities/state_rating_table_invalid_enum_ot_basis_rejected
    """
    payload = {
        "state_code": "CA",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "monopolistic": False,
        "per_capita_admin_fee_cents": 250,
        "expense_constant_cents": 30000,
        "min_payroll_threshold_cents": 10000,
        "state_minimum_premium_cents": 50000,
        "ot_basis": "HALF",
        "class_rates": [{"class_code": "8810", "rate_per_100_cents": 125}],
        "max_payroll_per_executive_cents": 250000,
    }
    res = api.create_state_rating_table(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_class_codes_listed_as_children_of_their_policy(api):
    """PRD §3.2: "Each entry becomes a **PolicyClassCode** child with `assignment_status`
    of `ACTIVE` and an `effective_from` equal to the policy's `effective_date`."

    Design: Corner/entities/policy_class_code_child_listing_under_parent
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_policy(
        employer["id"], policy_number="WC-CHD-001",
        class_codes=[class_code_entry("CA", "8810", 500000),
                     class_code_entry("CA", "5645", 700000)])

    rows, _meta = validate_paginated(
        api.list_policy_class_codes(policy["id"], UW))
    assert len(rows) == 2
    for row in rows:
        assert row["policy_id"] == policy["id"]
        assert row["assignment_status"] == "ACTIVE"
        # PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
        assert row["effective_from"] == "2026-09-01T00:00:00.000Z"
    assert {row["class_code"] for row in rows} == {"8810", "5645"}
