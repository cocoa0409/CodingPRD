"""Resource fundamentals: creation, retrieval, pagination, and request errors.

Covers the PRD's common resource properties (section 2.4), the response
envelope (section 2.2), pagination (section 2.3), and the authentication
precedence rule (section 2.7).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_bureau,
    assert_employer,
    build_user_headers,
    create_bureau_payload,
    create_employer_payload,
    create_policy_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_carrier_data_reporter_headers,
    set_clock,
    setup_bureau_carrier_employer,
    setup_rated_policy,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def test_bureau_create_returns_all_declared_fields_and_version_one(api):
    """PRD section 2.4: "All resources additionally carry `created_at`, an ISO
    8601 UTC timestamp with three fractional digits recording when the resource
    was created. All resources except the `ClassCode` carry `updated_at`, a
    timestamp of the same format refreshed on every mutation, and `version`,
    an integer that starts at 1 and increments by one on every mutation of
    that resource."

    Design: Corner/entities/bureau_create_returns_all_declared_fields_and_version_one
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_bureau(create_bureau_payload(), ADMIN)
    body = resp.json()
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)

    bureau = validate_success(resp, expected_status=201)
    assert_bureau(bureau)
    assert bureau["split_point_cents"] == 1000000
    assert bureau["credibility_ballast_bp"] == 4000
    assert bureau["eligibility_threshold_cents"] == 500000
    assert bureau["credibility_excess_divisor_bp"] == 6000
    assert bureau["underwriting_threshold_cents"] == 2500000
    assert bureau["version"] == 1, f"New bureau must start at version 1, got {bureau['version']}"
    assert is_valid_uuid(bureau["id"])
    assert is_iso8601_timestamp(bureau["created_at"])
    assert is_iso8601_timestamp(bureau["updated_at"])


def test_employer_get_returns_stored_row_unchanged(api):
    """PRD section 3.1: "A new employer enters as `ACTIVE`"; PRD section 2.4:
    "`version`, an integer that starts at 1 and increments by one on every
    mutation of that resource."

    Design: Corner/entities/employer_get_returns_stored_row_unchanged
    """
    set_clock("2026-09-01T00:00:00Z")
    bureau = api.create_bureau(create_bureau_payload(), ADMIN)
    assert bureau.status_code == 201, f"Setup failed: {bureau.text}"

    created = validate_success(
        api.create_employer(create_employer_payload(), ADMIN), expected_status=201
    )
    resp = api.get_employer(created["id"], ADMIN)
    fetched = validate_success(resp, expected_status=200)
    assert_employer(fetched)
    assert fetched["fein"] == "75-1000001"
    assert fetched["legal_name"] == "Pecos Machine Works"
    assert fetched["state_code"] == "TX"
    assert fetched["status"] == "ACTIVE", f"New employer must be ACTIVE, got {fetched['status']}"
    assert fetched["version"] == 1


def test_policies_list_paginates_with_total_count_and_has_more(api):
    """PRD section 2.3: "Paginated list responses include the fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope."

    Design: Corner/entities/policies_list_paginates_with_total_count_and_has_more
    """
    set_clock("2026-01-15T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy1 = setup_rated_policy(
        payroll_dollars=100000, policy_number="WC-P1"
    )
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    for number, eff, exp in (
        ("WC-P2", "2025-01-01", "2026-01-01"),
        ("WC-P3", "2026-01-01", "2027-01-01"),
    ):
        resp = api.create_policy(
            create_policy_payload(
                employer_id=employer["id"],
                carrier_id=carrier["id"],
                policy_number=number,
                effective_date=eff,
                expiration_date=exp,
                class_codes=[{"class_code": class_code["code"], "payroll_dollars": 100000}],
            ),
            reporter,
        )
        assert resp.status_code == 201, f"Setup failed creating {number}: {resp.text}"

    data, meta = validate_paginated(
        api.list_policies(ADMIN, params={"employer_id": employer["id"], "limit": 2, "offset": 0})
    )
    assert len(data) == 2, f"Expected 2 rows, got {len(data)}"
    assert meta["total_count"] == 3, f"Expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(
        api.list_policies(ADMIN, params={"employer_id": employer["id"], "limit": 2, "offset": 2})
    )
    assert len(data2) == 1, f"Expected 1 row on second page, got {len(data2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_employer_get_with_unknown_id_returns_not_found(api):
    """PRD section 2.7: "Next comes resource existence (`ERR_NOT_FOUND`)";
    PRD section 5: ERR_NOT_FOUND maps to HTTP 404.

    Design: Corner/entities/employer_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_bureau(create_bureau_payload(), ADMIN)
    assert resp.status_code == 201, f"Setup failed: {resp.text}"

    resp = api.get_employer("00000000-0000-4000-8000-000000000000", ADMIN)
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    assert resp.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_policy_create_missing_class_codes_returns_invalid_request(api):
    """PRD section 3.2: a policy is issued by "supplying the `employer_id`,
    the writing `carrier_id`, a `policy_number` unique per carrier, the term
    bounded by `effective_date` and `expiration_date`, and a `class_codes`
    array pairing each classification with its estimated `payroll_dollars`";
    PRD section 5: ERR_INVALID_REQUEST maps to HTTP 400.

    Design: Corner/entities/policy_create_missing_class_codes_returns_invalid_request
    """
    set_clock("2026-01-15T00:00:00Z")
    bureau, carrier, employer, class_code, table, _policy = setup_rated_policy(
        payroll_dollars=100000, policy_number="WC-BASE"
    )
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    payload = {
        "employer_id": employer["id"],
        "carrier_id": carrier["id"],
        "policy_number": "WC-MISS",
        "effective_date": "2026-02-01",
        "expiration_date": "2027-02-01",
    }
    resp = api.create_policy(payload, reporter)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    data, meta = validate_paginated(
        api.list_policies(ADMIN, params={"employer_id": employer["id"]})
    )
    assert meta["total_count"] == 1, (
        f"Rejected create must not persist a policy; expected only the setup "
        f"policy, got total_count {meta['total_count']}"
    )


def test_unit_stat_report_submission_number_defaults_to_one(api):
    """PRD section 3.3: "Every report for a policy receives a sequential
    `submission_number`, starting at one for the first submission. The report
    enters in `SUBMITTED`."

    Design: Corner/entities/unit_stat_report_submission_number_defaults_to_one
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy = setup_rated_policy(
        payroll_dollars=100000, policy_number="WC-1001"
    )
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    payload = {
        "policy_id": policy["id"],
        "payroll_lines": [{"class_code": class_code["code"], "payroll_dollars": 100000}],
        "claim_lines": [
            {
                "claim_number": "Q1",
                "claim_type": "MEDICAL",
                "incurred_cents": 50000,
                "paid_cents": 50000,
                "claim_status": "CLOSED",
                "state_code": "TX",
            }
        ],
    }
    report = validate_success(
        api.create_unit_stat_report(payload, reporter), expected_status=201
    )
    assert report["submission_number"] == 1, (
        f"First submission must be numbered 1, got {report['submission_number']}"
    )
    assert report["status"] == "SUBMITTED"


def test_policy_manual_premium_is_computed_and_input_ignored(api):
    """PRD section 3.2: "The policy's `manual_premium_cents` is computed at
    creation: for each line, the payroll in dollars is multiplied by the
    classification's `rate_per_100_payroll_cents` from the promulgated table
    in force at the policy's effective date and divided by one hundred, each
    line rounded half up to whole cents, and the rounded lines summed."

    Design: Corner/entities/policy_manual_premium_is_computed_and_input_ignored
    """
    set_clock("2026-01-15T00:00:00Z")
    bureau, carrier, employer = setup_bureau_carrier_employer(
        employer_overrides={"fein": "75-1000002", "legal_name": "Brazos Fabrication"}
    )
    from test_helpers import (
        create_class_code,
        create_and_promulgate_rating_table,
        create_policy_payload as _policy_payload,
    )

    class_code = create_class_code()
    create_and_promulgate_rating_table(effective_date="2026-01-01")
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    payload = _policy_payload(
        employer_id=employer["id"],
        carrier_id=carrier["id"],
        policy_number="WC-CMP",
        effective_date="2026-02-01",
        expiration_date="2027-02-01",
        class_codes=[{"class_code": class_code["code"], "payroll_dollars": 100000}],
    )
    payload["manual_premium_cents"] = 999999  # smuggled: must be ignored
    policy = validate_success(api.create_policy(payload, reporter), expected_status=201)
    # 100000 dollars * 250 cents per 100 dollars / 100 = 250000 cents.
    assert policy["manual_premium_cents"] == 250000, (
        f"manual_premium_cents must be system-computed 250000, got "
        f"{policy['manual_premium_cents']}"
    )
    assert policy["manual_premium_cents"] != 999999


def test_policy_status_is_system_set_input_ignored(api):
    """PRD section 3.2: "The new policy is `ACTIVE`"; PRD section 2.4:
    "`version`, an integer that starts at 1 and increments by one on every
    mutation of that resource."

    Design: Corner/entities/policy_status_is_system_set_input_ignored
    """
    set_clock("2026-01-15T00:00:00Z")
    bureau, carrier, employer = setup_bureau_carrier_employer(
        employer_overrides={"fein": "75-1000002", "legal_name": "Brazos Fabrication"}
    )
    from test_helpers import (
        create_class_code,
        create_and_promulgate_rating_table,
        create_policy_payload as _policy_payload,
    )

    class_code = create_class_code()
    create_and_promulgate_rating_table(effective_date="2026-01-01")
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    payload = _policy_payload(
        employer_id=employer["id"],
        carrier_id=carrier["id"],
        policy_number="WC-SYS",
        effective_date="2026-02-01",
        expiration_date="2027-02-01",
        class_codes=[{"class_code": class_code["code"], "payroll_dollars": 100000}],
    )
    payload["status"] = "CANCELLED"  # smuggled: must be ignored
    policy = validate_success(api.create_policy(payload, reporter), expected_status=201)
    assert policy["status"] == "ACTIVE", (
        f"New policy must be ACTIVE regardless of client input, got {policy['status']}"
    )
    assert policy["version"] == 1


def test_policy_create_referencing_unknown_employer_returns_not_found(api):
    """PRD section 2.7: "Next comes resource existence (`ERR_NOT_FOUND`)";
    PRD section 5: ERR_NOT_FOUND maps to HTTP 404.

    Design: Corner/entities/policy_create_referencing_unknown_employer_returns_not_found
    """
    set_clock("2026-01-15T00:00:00Z")
    bureau, carrier, _employer = setup_bureau_carrier_employer()
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    resp = api.create_policy(
        {
            "employer_id": "00000000-0000-4000-8000-000000000001",
            "carrier_id": carrier["id"],
            "policy_number": "WC-NFK",
            "effective_date": "2026-02-01",
            "expiration_date": "2027-02-01",
            "class_codes": [{"class_code": "3632", "payroll_dollars": 100000}],
        },
        reporter,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_missing_user_context_header_returns_400(api):
    """PRD section 2.1: "A request missing either header, or carrying a
    malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/errors/missing_user_context_header_returns_400
    """
    resp = api.get_employer(
        "00000000-0000-4000-8000-000000000000",
        headers={"X-User-ID": "test-user-no-role"},
    )
    validate_error(
        resp,
        ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        expected_status=400,
    )
