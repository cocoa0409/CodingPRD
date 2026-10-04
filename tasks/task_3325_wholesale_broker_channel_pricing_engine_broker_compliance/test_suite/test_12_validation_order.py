"""Validation ordering across categories and the submission gates."""
from test_helpers import (
    ANY,
    ApiErrorId,
    get_broker,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    create_and_approve_broker,
    create_submitted_broker,
    price_quote,
    publish_rate_sheet,
    record_license,
    request_and_approve_eligibility,
    set_clock,
    setup_full_scenario,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_broker_headers,
    make_compliance_officer_headers,
    make_channel_manager_headers,
)

STANDARD_TABLE = [
    {"dim": "credit", "bucket": "760-plus", "adjust_pct": -0.125},
    {"dim": "ltv", "bucket": "up-to-60", "adjust_pct": 0.000},
    {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
    {"dim": "product", "bucket": "CONVENTIONAL", "adjust_pct": 0.000},
]


def test_the_licensing_gate_outranks_the_product_envelope_gate(api):
    """PRD §2.11: "Within that catalogue the exclusivity and licensing rules are probed before
    the product-envelope, sheet-status and compensation-consistency rules"
    PRD §3.6: "it must appear in the broker's `licensed_states`, or the submission is refused
    with `ERR_PROPERTY_STATE_NOT_LICENSED`."

    Design: Difficulty/priority_pair_validation_conflict/license_expiry_between_eligibility_and_state_gate
    """
    broker = create_submitted_broker(home_state="TX")
    b = broker["id"]
    record_license(b, state_code="TX")
    from test_helpers import record_and_pass_financial_review

    record_and_pass_financial_review(b)
    # A deliberately tight envelope: the amount bound will fail for a 40000000-cent file.
    eligibility = request_and_approve_eligibility(
        b, product_code="CONVENTIONAL", max_ltv=0.7000, min_fico=760,
        max_loan_amount_cents=30_000_000,
    )
    assert eligibility["status"] == "APPROVED"
    plan = validate_success(
        api_client.create_compensation_plan(
            {
                "broker_id": b, "plan_code": "PLAN_A", "default_election": "LENDER_PAID",
                "lender_paid_amount_cents": 250_000, "borrower_paid_amount_cents": 300_000,
                "is_active": True,
            },
            make_channel_manager_headers(),
        ),
        expected_status=201,
    )
    validate_success(api_client.approve_broker(b, make_channel_manager_headers()))
    sheet = publish_rate_sheet(b, adjustment_table=STANDARD_TABLE)
    quote = price_quote(b, sheet, representative_fico=780, ltv_ratio=0.5500)

    response = api_client.create_loan_submission(
        {
            "broker_id": b, "pricing_quote_id": quote["id"],
            "borrower_name": "Priority Safety Borrower",
            "property_state": "CA",  # neither licensed nor inside the envelope
            "loan_amount_cents": 40_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
            "compensation_election": "LENDER_PAID", "comp_plan_id": plan["id"],
        },
        make_broker_headers(b),
    )
    validate_error(response, ApiErrorId.ERR_PROPERTY_STATE_NOT_LICENSED, expected_status=422)

    rows, meta = validate_paginated(
        api_client.list_loan_submissions(TEST_USERS["any_headers"], {"broker_id": b})
    )
    assert rows == [] and meta["total_count"] == 0


def test_the_same_submission_inside_both_gates_is_accepted(api):
    """PRD §3.6: "The `property_state` must be covered by an unexpired licence: it must appear in
    the broker's `licensed_states`"
    PRD §3.3: "a loan submission is only accepted when an `APPROVED` eligibility exists for the
    submitted product whose `max_ltv`, `min_fico` and `max_loan_amount_cents` all hold as
    inclusive bounds against the submission's figures"

    Design: Difficulty/priority_pair_validation_conflict/license_expiry_between_eligibility_and_state_gate
    """
    broker = create_submitted_broker(home_state="TX")
    b = broker["id"]
    record_license(b, state_code="TX")
    from test_helpers import record_and_pass_financial_review

    record_and_pass_financial_review(b)
    request_and_approve_eligibility(
        b, product_code="CONVENTIONAL", max_ltv=0.7000, min_fico=760,
        max_loan_amount_cents=30_000_000,
    )
    plan = validate_success(
        api_client.create_compensation_plan(
            {
                "broker_id": b, "plan_code": "PLAN_A", "default_election": "LENDER_PAID",
                "lender_paid_amount_cents": 250_000, "borrower_paid_amount_cents": 300_000,
                "is_active": True,
            },
            make_channel_manager_headers(),
        ),
        expected_status=201,
    )
    validate_success(api_client.approve_broker(b, make_channel_manager_headers()))
    sheet = publish_rate_sheet(b, adjustment_table=STANDARD_TABLE)
    quote = price_quote(b, sheet, representative_fico=780, ltv_ratio=0.5500)

    accepted = validate_success(
        api_client.create_loan_submission(
            {
                "broker_id": b, "pricing_quote_id": quote["id"],
                "borrower_name": "Inside Both Gates Borrower",
                "property_state": "TX", "loan_amount_cents": 30_000_000,
                "lock_expires_at": "2027-01-01T00:00:00Z",
                "compensation_election": "LENDER_PAID", "comp_plan_id": plan["id"],
            },
            make_broker_headers(b),
        ),
        expected_status=201,
    )
    assert accepted["status"] == "SUBMITTED"
    assert accepted["property_state"] == "TX"


def test_a_property_state_outside_the_licensed_set_is_refused(api):
    """PRD §3.6: "The `property_state` must be covered by an unexpired licence: it must appear in
    the broker's `licensed_states`, or the submission is refused with
    `ERR_PROPERTY_STATE_NOT_LICENSED`."

    Design: Difficulty/priority_pair_validation_conflict/license_expiry_between_eligibility_and_state_gate
    """
    scenario = setup_full_scenario(state_code="TX")
    b = scenario["broker_id"]
    response = api_client.create_loan_submission(
        {
            "broker_id": b, "pricing_quote_id": scenario["quote"]["id"],
            "borrower_name": "Cross Border Borrower", "property_state": "CA",
            "loan_amount_cents": 40_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
            "compensation_election": "LENDER_PAID", "comp_plan_id": scenario["plan"]["id"],
        },
        make_broker_headers(b),
    )
    validate_error(response, ApiErrorId.ERR_PROPERTY_STATE_NOT_LICENSED, expected_status=422)


def test_the_licensing_gate_outranks_the_broker_standing_gate(api):
    """PRD §2.11: "the acting-brokerage ownership rule follows it; and the broker-standing rule
    is the final business gate on the operations that carry it."
    PRD §3.6: "it must appear in the broker's `licensed_states`, or the submission is refused
    with `ERR_PROPERTY_STATE_NOT_LICENSED`."

    Design: Corner/errors/suspended_status_gate_precedes_unlicensed_state_on_submission
    """
    scenario = setup_full_scenario(state_code="TX")
    b = scenario["broker_id"]

    # Revoking the only licence empties licensed_states. Licence loss does not by
    # itself suspend a broker (PRD §2.4 lists the four automatic triggers and
    # licensing is not one of them), so the standing gate is raised separately by
    # a manual suspension — making both gates false at once.
    set_clock("2026-10-05T00:00:00Z")
    validate_success(
        api_client.revoke_license(b, scenario["license"]["id"], make_compliance_officer_headers())
    )
    set_clock("2026-09-01T00:00:00Z")
    validate_success(
        api_client.suspend_broker(
            b, {"reason": "channel management review pending"},
            make_channel_manager_headers(),
        )
    )

    broker = get_broker(b)
    assert broker["status"] == "SUSPENDED"
    assert broker["licensed_states"] == []

    response = api_client.create_loan_submission(
        {
            "broker_id": b, "pricing_quote_id": scenario["quote"]["id"],
            "borrower_name": "Suspended Gate Borrower", "property_state": "TX",
            "loan_amount_cents": 40_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
            "compensation_election": "LENDER_PAID", "comp_plan_id": scenario["plan"]["id"],
        },
        make_broker_headers(b),
    )
    validate_error(response, ApiErrorId.ERR_PROPERTY_STATE_NOT_LICENSED, expected_status=422)

    rows, _meta = validate_paginated(
        api_client.list_loan_submissions(TEST_USERS["any_headers"], {"broker_id": b})
    )
    # The scenario's own loan was pushed to SUSPENDED_REVIEW, so only that one remains visible.
    assert all(row["borrower_name"] != "Suspended Gate Borrower" for row in rows)
    assert len(rows) == 1


def test_a_broker_user_cannot_submit_against_a_foreign_brokerage(api):
    """PRD §2.1: "A `BrokerUser` that invokes a broker-scoped operation for a `broker_id` other
    than its own `X-User-ID` is refused with `ERR_BROKER_RESOURCE_FORBIDDEN` and a `403 Forbidden`
    status."

    Design: Corner/errors/error_broker_resource_forbidden_on_foreign_broker
    """
    scenario = setup_full_scenario(state_code="TX")
    b = scenario["broker_id"]
    second = create_submitted_broker(
        legal_name="Foreign Portal Brokers LLC", nmls_id="NMLS-3325918", home_state="TX",
        volume_expectation_cents=50_000_000,
    )

    response = api_client.create_loan_submission(
        {
            "broker_id": b, "pricing_quote_id": scenario["quote"]["id"],
            "borrower_name": "Foreign Portal Borrower", "property_state": "TX",
            "loan_amount_cents": 40_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
            "compensation_election": "LENDER_PAID", "comp_plan_id": scenario["plan"]["id"],
        },
        make_broker_headers(second["id"]),
    )
    validate_error(response, ApiErrorId.ERR_BROKER_RESOURCE_FORBIDDEN, expected_status=403)

    any_h = TEST_USERS["any_headers"]
    own, meta_own = validate_paginated(api_client.list_loan_submissions(any_h, {"broker_id": b}))
    foreign, meta_foreign = validate_paginated(
        api_client.list_loan_submissions(any_h, {"broker_id": second["id"]})
    )
    assert len(own) == 1, "only the scenario's own loan exists for the first broker"
    assert foreign == [] and meta_foreign["total_count"] == 0
    assert get_broker(b)["active_loan_count"] == 1


def test_the_product_amount_bound_is_enforced_inclusively_on_the_aggregate(api):
    """PRD §3.3: "a loan submission is only accepted when an `APPROVED` eligibility exists for
    the submitted product whose `max_ltv`, `min_fico` and `max_loan_amount_cents` all hold as
    inclusive bounds against the submission's figures, and a submission falling outside that
    envelope is refused with `ERR_PRODUCT_NOT_ELIGIBLE`."

    Design: Corner/validations/aggregate_eligibility_enforced_collectively_over_the_broker_loans
    """
    scenario = setup_full_scenario(state_code="TX")
    b = scenario["broker_id"]
    # Replace nothing: add a tight amount cap on a second, CONVENTIONAL eligibility row.
    from test_helpers import request_and_approve_eligibility

    # The scenario already approved a CONVENTIONAL eligibility with a 200000000 cap.
    over = api_client.create_loan_submission(
        {
            "broker_id": b, "pricing_quote_id": scenario["quote"]["id"],
            "borrower_name": "Aggregate Over Limit Borrower", "property_state": "TX",
            "loan_amount_cents": 400_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
            "compensation_election": "LENDER_PAID", "comp_plan_id": scenario["plan"]["id"],
        },
        make_broker_headers(b),
    )
    validate_error(over, ApiErrorId.ERR_PRODUCT_NOT_ELIGIBLE, expected_status=422)

    at_ceiling = validate_success(
        api_client.create_loan_submission(
            {
                "broker_id": b, "pricing_quote_id": scenario["quote"]["id"],
                "borrower_name": "Aggregate At Limit Borrower", "property_state": "TX",
                "loan_amount_cents": 200_000_000, "lock_expires_at": "2027-01-01T00:00:00Z",
                "compensation_election": "LENDER_PAID", "comp_plan_id": scenario["plan"]["id"],
            },
            make_broker_headers(b),
        ),
        expected_status=201,
    )
    assert at_ceiling["status"] == "SUBMITTED"
    assert at_ceiling["loan_amount_cents"] == 200_000_000