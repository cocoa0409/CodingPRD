"""Research utilization scoring, renewal posture and the contract-renewal gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_active_seat,
    create_analyst,
    create_completed_inquiry,
    create_seat,
    get_success_data,
    make_client_admin_headers,
    revoke_seat,
    set_clock,
    setup_account_with_active_seats,
    validate_error,
    validate_paginated,
)

# Accounts whose term ends on this date reach RENEWAL_REVIEW at the inclusive
# 90-day boundary of 2026-09-16T00:00:00Z.
CONTRACT_END = "2026-12-15T00:00:00Z"
RENEWAL_BOUNDARY = "2026-09-16T00:00:00Z"


def test_partially_activated_account_scores_with_each_component_capped():
    """PRD §2.7: "The activation component is 40 multiplied by the smaller of 1 and
    the ratio of `active_seat_count` to 80 percent of `seat_count_contracted`. The
    usage component is 35 multiplied by the smaller of 1 and the ratio of
    `consumed_inquiry_units` to 70 percent of a usage denominator. The retention
    component is 25 multiplied by the smaller of 1 and the ratio of one minus
    `revoked_seat_count` divided by `seat_count_contracted`, to 0.95."

    Design: Difficulty/combinatorial_formula/utilization_score_nested_min_across_five_inputs
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seats = setup_account_with_active_seats(
        seat_count_contracted=4, inquiry_allowance_total=4, active_count=4,
        account_overrides={"legal_name": "Meridian Health Network",
                           "industry": "Healthcare", "reprint_tier": "PREMIUM"},
    )
    analyst = create_analyst()
    revoke_seat(account, seats[3])

    create_completed_inquiry(account, seats[0], analyst, "2026-09-02T10:00:00Z",
                             "2026-09-02T12:00:00Z", question_summary="Completed one")
    # The second slot must not be requested in the past: the first completion
    # leaves the logical clock at 12:00, and PRD 3.1 refuses a requested start
    # strictly before the clock with ERR_INQUIRY_START_IN_PAST.
    create_completed_inquiry(account, seats[0], analyst, "2026-09-02T13:00:00Z",
                             "2026-09-02T14:00:00Z", question_summary="Completed two")

    data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert data["active_seat_count"] == 3
    assert data["revoked_seat_count"] == 1
    assert data["consumed_inquiry_units"] == 2
    assert data["utilization_score"] == 82.24, (
        "37.5 activation + 25.0 usage + 19.74 retention, rounded half up"
    )
    assert data["utilization_score_active_weighted"] == 90.57, (
        "The ACTIVE_WEIGHTED denominator is 4 * 3 / 4 = 3.00, so the usage term is "
        "35 * 2 / 2.10 = 33.33 and the total is 90.57"
    )
    assert data["renewal_posture"] == "HEALTHY"
    assert data["utilization_score"] != 100.00


def test_fully_utilized_account_hits_every_component_cap():
    """PRD §2.7: "Research utilization is measured as a weighted score between 0 and
    100, computed from three components, each capped at its own weight."
    PRD §2.7: "The score is the sum of the three components, rounded half up to 2
    decimal places, applied once to the summed total."

    Design: Difficulty/combinatorial_formula/utilization_score_nested_min_across_five_inputs
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seats = setup_account_with_active_seats(
        seat_count_contracted=2, inquiry_allowance_total=2, active_count=2,
    )
    analyst = create_analyst()
    create_completed_inquiry(account, seats[0], analyst, "2026-09-02T10:00:00Z",
                             "2026-09-02T12:00:00Z", question_summary="Fully used one")
    create_completed_inquiry(account, seats[0], analyst, "2026-09-03T10:00:00Z",
                             "2026-09-03T12:00:00Z", question_summary="Fully used two")

    data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert data["active_seat_count"] == 2
    assert data["revoked_seat_count"] == 0
    assert data["consumed_inquiry_units"] == 2
    assert data["utilization_score"] == 100.00, (
        "Every ratio exceeds 1, so each component takes its full weight: 40 + 35 + 25"
    )
    assert data["utilization_score_active_weighted"] == 100.00
    assert data["renewal_posture"] == "HEALTHY"


def test_renewal_gate_reads_the_active_weighted_variant_not_the_dashboard_variant():
    """PRD §3.4: "The gate reads the ACTIVE_WEIGHTED variant of the score —
    `utilization_score_active_weighted` — not the dashboard variant, and requires it
    to be at least 40; a score of exactly 40 passes."
    PRD §3.4: "A `RENEW` that fails either condition is rejected with
    `ERR_RENEWAL_UTILIZATION_TOO_LOW` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/renewal_decision_requires_seat_derived_utilization
    """
    set_clock("2026-09-01T00:00:00Z")
    terms = {
        "contract_start_utc": "2025-12-16T00:00:00Z",
        "contract_end_utc": CONTRACT_END,
        "seat_count_contracted": 10,
        "inquiry_allowance_total": 20,
        "reprint_tier": "PREMIUM",
        "region": "NA",
    }
    account_a = create_account(legal_name="Northgate Utilities", industry="Energy", **terms)
    account_b = create_account(legal_name="Southgate Utilities", industry="Energy", **terms)
    analyst = create_analyst()
    seat_one = create_active_seat(account_a, seat_email="lead@northgate.example",
                                  research_role="STRATEGIST")
    create_active_seat(account_a, seat_email="arch@northgate.example",
                       research_role="ARCHITECT")
    create_completed_inquiry(account_a, seat_one, analyst, "2026-09-02T10:00:00Z",
                             "2026-09-02T12:00:00Z", question_summary="Settled usage")

    set_clock(RENEWAL_BOUNDARY)
    director_headers = TEST_USERS["research_director_headers"]

    for account in (account_a, account_b):
        state = get_success_data(
            api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
        )
        assert state["contract_status"] == "RENEWAL_REVIEW"

    refused = api_client.create_renewal_decision(
        account_b["id"], {"decision": "RENEW"}, director_headers
    )
    validate_error(refused, ApiErrorId.ERR_RENEWAL_UTILIZATION_TOO_LOW)

    still_open = get_success_data(
        api_client.get_client(account_b["id"], make_client_admin_headers(account_b["id"]))
    )
    assert still_open["contract_status"] == "RENEWAL_REVIEW"

    dashboard = get_success_data(
        api_client.get_client(account_a["id"], make_client_admin_headers(account_a["id"]))
    )
    assert dashboard["utilization_score"] == 37.50
    assert dashboard["utilization_score_active_weighted"] == 47.50, (
        "The ACTIVE_WEIGHTED denominator is 20 * 2 / 10 = 4.00, so the usage term is "
        "35 * 1 / 2.80 = 12.50 and the total is 47.50"
    )

    accepted = api_client.create_renewal_decision(
        account_a["id"], {"decision": "RENEW"}, director_headers
    )
    renewed = get_success_data(accepted, expected_status=200)
    assert renewed["contract_status"] == "RENEWED"
    assert renewed["renewal_decided_at"] is not None


def test_renewal_is_refused_while_a_seat_is_still_provisioned():
    """PRD §3.4: "The decision also requires that no seat on the account is still in
    `PROVISIONED` status, meaning every contracted seat has been either activated or
    revoked. A `RENEW` that fails either condition is rejected with
    `ERR_RENEWAL_UTILIZATION_TOO_LOW` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/renewal_decision_requires_seat_derived_utilization
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(
        legal_name="Harbor Logistics", industry="Transport", region="EMEA",
        contract_start_utc="2025-12-16T00:00:00Z", contract_end_utc=CONTRACT_END,
        seat_count_contracted=4, inquiry_allowance_total=4, reprint_tier="STANDARD",
    )
    for index in range(3):
        create_active_seat(account, seat_email=f"active{index + 1}@harbor.example")
    create_seat(account, seat_email="pending@harbor.example")

    set_clock(RENEWAL_BOUNDARY)
    director_headers = TEST_USERS["research_director_headers"]

    state = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert state["contract_status"] == "RENEWAL_REVIEW"
    assert state["provisioned_seat_count"] == 1
    assert state["utilization_score_active_weighted"] == 62.50, (
        "Utilization alone clears the 40 floor, so the seat condition is the blocker"
    )

    refused = api_client.create_renewal_decision(
        account["id"], {"decision": "RENEW"}, director_headers
    )
    validate_error(refused, ApiErrorId.ERR_RENEWAL_UTILIZATION_TOO_LOW)

    pending, _ = validate_paginated(
        api_client.list_seats(
            make_client_admin_headers(account["id"]),
            params={"client_account_id": account["id"], "status": "PROVISIONED"},
        )
    )
    assert len(pending) == 1
    revoke_seat(account, pending[0])

    accepted = api_client.create_renewal_decision(
        account["id"], {"decision": "RENEW"}, director_headers
    )
    renewed = get_success_data(accepted, expected_status=200)
    assert renewed["contract_status"] == "RENEWED"


def test_activation_target_boundary_caps_the_activation_component():
    """PRD §2.7: "The activation component is 40 multiplied by the smaller of 1 and
    the ratio of `active_seat_count` to 80 percent of `seat_count_contracted`."
    PRD §2.7: "`renewal_posture` is derived from a score using two ceilings: the
    posture is `AT_RISK` when the score is below 40, `WATCH` when the score is at
    least 40 and below 70, and `HEALTHY` when the score is 70 or above."

    Design: Corner/calculations/utilization_activation_target_boundary_at_eighty_percent
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seats = setup_account_with_active_seats(
        seat_count_contracted=5, inquiry_allowance_total=5, active_count=4,
        account_overrides={"legal_name": "Cobalt Financial",
                           "industry": "Financial services", "region": "EMEA"},
    )

    at_target = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert at_target["active_seat_count"] == 4
    assert at_target["utilization_score"] == 65.00, (
        "Four of five seats is exactly the 0.80 target, so activation takes all 40 points"
    )
    assert at_target["renewal_posture"] == "WATCH"
    assert at_target["utilization_score"] != 100.00

    revoke_seat(account, seats[3])
    below_target = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert below_target["active_seat_count"] == 3
    assert below_target["revoked_seat_count"] == 1
    assert below_target["utilization_score"] == 51.05, (
        "Activation drops to 30 and retention to 21.05 once a seat is revoked"
    )
    assert below_target["renewal_posture"] == "WATCH"
    assert below_target["contract_status"] == "ACTIVE", (
        "Three active seats is not below ceil(5 / 2), so the contract stays ACTIVE"
    )
