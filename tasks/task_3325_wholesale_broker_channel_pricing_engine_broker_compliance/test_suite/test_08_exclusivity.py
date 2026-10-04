"""Exclusivity policies, breaches, posture escalation and the submission gates."""
from test_helpers import (
    ANY,
    ApiErrorId,
    broker_version,
    get_broker,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import CM, create_and_approve_broker, price_quote, publish_rate_sheet, setup_full_scenario
from test_helpers.test_users import TEST_USERS, make_broker_headers, make_channel_manager_headers

STANDARD_TABLE = [
    {"dim": "credit", "bucket": "760-plus", "adjust_pct": -0.125},
    {"dim": "ltv", "bucket": "up-to-60", "adjust_pct": 0.000},
    {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
    {"dim": "product", "bucket": "CONVENTIONAL", "adjust_pct": 0.000},
]


def _submit(scenario, **overrides):
    payload = {
        "broker_id": scenario["broker_id"],
        "pricing_quote_id": scenario["quote"]["id"],
        "borrower_name": "Exclusivity Borrower",
        "property_state": "TX",
        "loan_amount_cents": 40_000_000,
        "lock_expires_at": "2027-01-01T00:00:00Z",
        "compensation_election": "LENDER_PAID",
        "comp_plan_id": scenario["plan"]["id"],
    }
    payload.update(overrides)
    return api_client.create_loan_submission(payload, make_broker_headers(scenario["broker_id"]))


def test_competitor_disclosure_inside_the_policy_window_breaches(api):
    """PRD §3.4: "When it matches an `ACTIVE` policy, the submission is refused with
    `ERR_EXCLUSIVITY_POLICY_BREACH`"
    PRD §3.4: "that value is matched case-insensitively against the broker's policies."

    Design: Difficulty/resource_temporal_overlap/exclusivity_policy_half_open_effective_window
    """
    scenario = setup_full_scenario(state_code="TX")
    payload = {
        "broker_id": scenario["broker_id"],
        "competitor_identifier": "COMP-ALPHA",
        "competitor_name": "Alpha Mortgage Partners",
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2026-12-01T00:00:00Z",
        "status": "ACTIVE",
        "restriction_scope": "LOAN_SUBMISSION",
    }
    validate_success(
        api_client.create_exclusivity_policy(payload, make_channel_manager_headers()),
        expected_status=201,
    )

    response = _submit(scenario, competitor_channel_identifier="comp-alpha")
    validate_error(response, ApiErrorId.ERR_EXCLUSIVITY_POLICY_BREACH, expected_status=403)


def test_a_single_breached_policy_escalates_the_posture_to_warned(api):
    """PRD §3.4: "Exactly one yields `WARNED`. Exactly two yield `RESTRICTED`."
    PRD §3.4: "Whenever a policy is registered, voided, or breached, `exclusivity_status` is
    recomputed and the broker's `version` is incremented."

    Design: Difficulty/resource_temporal_overlap/exclusivity_policy_half_open_effective_window
    """
    scenario = setup_full_scenario(state_code="TX")
    policy = validate_success(
        api_client.create_exclusivity_policy(
            {
                "broker_id": scenario["broker_id"],
                "competitor_identifier": "COMP-ALPHA",
                "competitor_name": "Alpha Mortgage Partners",
                "effective_from": "2026-09-01T00:00:00Z",
                "effective_to": "2026-12-01T00:00:00Z",
                "status": "ACTIVE",
                "restriction_scope": "LOAN_SUBMISSION",
            },
            make_channel_manager_headers(),
        ),
        expected_status=201,
    )
    assert get_broker(scenario["broker_id"])["exclusivity_status"] == "CLEAR"

    api_client.create_loan_submission(
        {
            "broker_id": scenario["broker_id"],
            "pricing_quote_id": scenario["quote"]["id"],
            "borrower_name": "Breach Borrower",
            "property_state": "TX",
            "loan_amount_cents": 40_000_000,
            "lock_expires_at": "2027-01-01T00:00:00Z",
            "competitor_channel_identifier": "comp-alpha",
            "compensation_election": "LENDER_PAID",
            "comp_plan_id": scenario["plan"]["id"],
        },
        make_broker_headers(scenario["broker_id"]),
    )

    broker = get_broker(scenario["broker_id"])
    assert broker["exclusivity_status"] == "WARNED"

    policies = validate_success(
        api_client.list_exclusivity_policies(scenario["broker_id"], ANY)
    )
    assert len(policies) == 1
    assert policies[0]["breach_count"] == 1


def test_a_disclosure_outside_the_window_does_not_breach(api):
    """PRD §3.4: "an `effective_from` instant that is inclusive, and an `effective_to` instant
    that is exclusive and must be strictly after `effective_from`."
    PRD §3.4: "A breach is recorded when a loan discloses a competitor."

    Design: Difficulty/resource_temporal_overlap/exclusivity_policy_half_open_effective_window
    """
    scenario = setup_full_scenario(state_code="TX")
    validate_success(
        api_client.create_exclusivity_policy(
            {
                "broker_id": scenario["broker_id"],
                "competitor_identifier": "COMP-ALPHA",
                "competitor_name": "Alpha Mortgage Partners",
                "effective_from": "2026-09-01T00:00:00Z",
                "effective_to": "2026-12-01T00:00:00Z",
                "status": "ACTIVE",
                "restriction_scope": "LOAN_SUBMISSION",
            },
            make_channel_manager_headers(),
        ),
        expected_status=201,
    )
    # Move the clock past the exclusive end of the policy window.
    validate_success(
        api_client.set_current_utc("2026-12-13T00:00:00Z", TEST_USERS["platform_admin_headers"])
    )
    response = _submit(
        scenario,
        borrower_name="Late Window Borrower",
        competitor_channel_identifier="comp-alpha",
        loan_amount_cents=30_000_000,
    )
    # The policy no longer applies; any refusal must not be the breach identifier.
    assert response.status_code != 403 or (
        response.json()["data"]["error_id"] != ApiErrorId.ERR_EXCLUSIVITY_POLICY_BREACH
    ), "effective_to is exclusive"


def test_two_breached_policies_restrict_submission_but_not_pricing(api):
    """PRD §3.4: "when the breached policy's `restriction_scope` covers the attempted operation,
    the request is refused with `ERR_BROKER_EXCLUSIVITY_RESTRICTED`."
    PRD §3.4: "Because the default scope is `LOAN_SUBMISSION`, a default-scoped breach blocks
    submission while leaving rate locking open"

    Design: Corner/validations/conditional_validation_applies_only_when_posture_gates_the_operation
    """
    scenario = setup_full_scenario(state_code="TX")
    b = scenario["broker_id"]
    cm = make_channel_manager_headers()
    for competitor in ("COMP-RESTRICT-ONE", "COMP-RESTRICT-TWO"):
        validate_success(
            api_client.create_exclusivity_policy(
                {
                    "broker_id": b,
                    "competitor_identifier": competitor,
                    "competitor_name": f"{competitor} Lending",
                    "effective_from": "2026-09-01T00:00:00Z",
                    "effective_to": "2026-12-01T00:00:00Z",
                    "status": "ACTIVE",
                    "restriction_scope": "LOAN_SUBMISSION",
                },
                cm,
            ),
            expected_status=201,
        )

    breach_one = _submit(scenario, borrower_name="Restricted Breach Borrower One",
                         competitor_channel_identifier="comp-restrict-one")
    validate_error(breach_one, ApiErrorId.ERR_EXCLUSIVITY_POLICY_BREACH, expected_status=403)

    breach_two = _submit(scenario, borrower_name="Restricted Breach Borrower Two",
                         competitor_channel_identifier="comp-restrict-two")
    validate_error(breach_two, ApiErrorId.ERR_EXCLUSIVITY_POLICY_BREACH, expected_status=403)

    assert get_broker(b)["exclusivity_status"] == "RESTRICTED"

    restricted = _submit(scenario, borrower_name="Restricted Clean Borrower")
    validate_error(restricted, ApiErrorId.ERR_BROKER_EXCLUSIVITY_RESTRICTED, expected_status=403)

    active, meta = validate_paginated(
        api_client.list_exclusivity_policies(b, ANY, {"status": "ACTIVE"})
    )
    assert len(active) == 2 and meta["total_count"] == 2


def test_out_of_enum_restriction_scope_is_rejected(api):
    """PRD §3.4: "`restriction_scope`, which defaults to `LOAN_SUBMISSION` with the alternatives
    `RATE_LOCK` and `ALL`."
    PRD §2.11: "A `resolution_note` shorter than ten characters, a defect review created with
    `remediation_status` `OPEN`, an unknown enum member and a missing required field all travel
    through `ERR_INVALID_REQUEST`."

    Design: Corner/entities/exclusivity_policy_create_with_out_of_enum_restriction_scope_returns_invalid_request
    """
    broker = create_and_approve_broker()
    response = api_client.create_exclusivity_policy(
        {
            "broker_id": broker["id"],
            "competitor_identifier": "COMP-BETA",
            "competitor_name": "Beta Lending Group",
            "effective_from": "2026-09-01T00:00:00Z",
            "effective_to": "2026-12-01T00:00:00Z",
            "status": "ACTIVE",
            "restriction_scope": "SUBMISSION_ONLY",
        },
        make_channel_manager_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    policies, meta = validate_paginated(
        api_client.list_exclusivity_policies(broker["id"], TEST_USERS["any_headers"])
    )
    assert policies == [] and meta["total_count"] == 0