"""Equal-opportunity requests: admissibility, the parity bases, and the grant unwind."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    air_spot,
    assert_eo_request,
    classify_issue_advertiser,
    eo_request_payload,
    file_eo_request,
    grant_eo_request,
    make_advertiser_agent_headers,
    read_eo_request,
    read_order,
    run_audit_sweep,
    set_clock,
    setup_two_candidate_orders,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER_BETA = TEST_USERS["officer_beta_headers"]

MIXED_LENGTH_FLIGHT = [
    {"air_date": "2026-08-10", "start_offset_seconds": 0, "duration_seconds": 30, "program_code": "EN-T1"},
    {"air_date": "2026-08-10", "start_offset_seconds": 3600, "duration_seconds": 30, "program_code": "EN-T2"},
    {"air_date": "2026-08-10", "start_offset_seconds": 7200, "duration_seconds": 30, "program_code": "EN-T3"},
    {"air_date": "2026-08-10", "start_offset_seconds": 10800, "duration_seconds": 30, "program_code": "EN-T4"},
    {"air_date": "2026-08-10", "start_offset_seconds": 14400, "duration_seconds": 60, "program_code": "EN-T5"},
]


def _mixed_length_scenario(eo_parity_basis, call_sign):
    scenario = setup_two_candidate_orders(
        call_sign=call_sign,
        market_code="DMA-402",
        eo_parity_basis=eo_parity_basis,
        station_overrides={"licensee_name": "Statehouse Media Inc"},
        trigger_spots=MIXED_LENGTH_FLIGHT,
    )
    set_clock("2026-08-12T09:00:00Z")
    scenario["request"] = file_eo_request(
        scenario["station"]["id"],
        scenario["requester"]["id"],
        scenario["trigger_order"]["id"],
    )
    return scenario


def test_dollar_value_parity_floors_the_discounted_charge_over_the_card_rate(api):
    """PRD §3.8: "Under `DOLLAR_VALUE`, the platform first sums the
    `charged_rate_cents` of those same spots, then divides that total by the card unit
    rate of the trigger order's rate class — that class's `posted_rate_cents` multiplied
    by its daypart multiplier, rounded half up — and discards any fractional part of the
    quotient downward, never rounding up."
    PRD §3.8: "The transition `RECEIVED → GRANTED` computes `owed_units`, records
    `parity_basis_applied` as the station's `eo_parity_basis` in force at that moment,
    stores `granted_order_id`, stamps `responded_at` with the logical clock, and sets
    `fulfilled_units` to zero."

    Design: Difficulty/dual_variant_calc/eo_owed_units_dollar_value_diverges_from_spot_count
    """
    scenario = _mixed_length_scenario("DOLLAR_VALUE", "WGOV-TV")
    trigger_order = read_order(scenario["trigger_order"]["id"])
    assert trigger_order["gross_charge_cents"] == 570000

    granted = validate_success(
        api.respond_eo_request(
            scenario["request"]["id"],
            {"decision": "GRANT", "granted_order_id": scenario["granted_order"]["id"]},
            OFFICER_BETA,
        )
    )
    assert_eo_request(granted)

    assert granted["owed_units"] == 5, (
        "570000 cents over the undiscounted 100000-cent card unit rate floors to 5"
    )
    assert granted["parity_basis_applied"] == "DOLLAR_VALUE"
    assert granted["status"] == "GRANTED"
    assert granted["granted_order_id"] == scenario["granted_order"]["id"]
    assert granted["fulfilled_units"] == 0


def test_spot_count_parity_awards_one_unit_for_every_thirty_seconds(api):
    """PRD §3.8: "Under `SPOT_COUNT`, `owed_units` is the sum, across those spots, of
    each spot's `duration_seconds` divided by thirty — so a sixty-second opponent spot
    owes 2 units and a thirty-second spot owes 1, regardless of what either cost."
    PRD §3.8: "Because that denominator is the *undiscounted* card rate while the
    numerator reflects whatever volume discount the opponent earned, a discounted
    opponent order awards strictly fewer units under `DOLLAR_VALUE` than the very same
    spots would award under `SPOT_COUNT`."

    Design: Difficulty/dual_variant_calc/eo_owed_units_dollar_value_diverges_from_spot_count
    """
    scenario = _mixed_length_scenario("SPOT_COUNT", "WGO2-TV")

    granted = validate_success(
        api.respond_eo_request(
            scenario["request"]["id"],
            {"decision": "GRANT", "granted_order_id": scenario["granted_order"]["id"]},
            OFFICER_BETA,
        )
    )
    assert granted["owed_units"] == 6, "four 30-second spots owe 1 each and the 60-second spot owes 2"
    assert granted["parity_basis_applied"] == "SPOT_COUNT"
    assert granted["owed_units"] > 5, (
        "the same spots award strictly more units than DOLLAR_VALUE would"
    )


def test_request_against_a_trigger_order_that_has_not_aired_is_refused(api):
    """PRD §3.8: "The trigger order must have reached `RUNNING` or `COMPLETED`, so that
    a first use has genuinely aired; a trigger order still sitting in `ACCEPTED` is
    refused with `ERR_EO_TRIGGER_ORDER_NOT_AIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/eo_request_creation_depends_on_trigger_order_reaching_running
    """
    scenario = setup_two_candidate_orders(
        call_sign="WCRS-TV",
        market_code="DMA-266",
        station_overrides={"licensee_name": "Crossline Broadcasting"},
        air_trigger=False,
        build_granted_order=False,
    )
    station, requester = scenario["station"], scenario["requester"]
    trigger_order = read_order(scenario["trigger_order"]["id"])

    assert trigger_order["status"] == "ACCEPTED"
    assert trigger_order["first_air_at"] is None

    validate_error(
        api.create_eo_request(
            eo_request_payload(station["id"], requester["id"], trigger_order["id"]),
            make_advertiser_agent_headers(requester["id"]),
        ),
        ApiErrorId.ERR_EO_TRIGGER_ORDER_NOT_AIRED,
    )

    _rows, meta = validate_paginated(
        api.list_eo_requests(ADMIN, params={"station_id": station["id"]})
    )
    assert meta["total_count"] == 0


def test_request_becomes_admissible_once_the_trigger_order_has_aired(api):
    """PRD §3.8: "The trigger order must have reached `RUNNING` or `COMPLETED`, so that
    a first use has genuinely aired; a trigger order still sitting in `ACCEPTED` is
    refused with `ERR_EO_TRIGGER_ORDER_NOT_AIRED` (HTTP 409)."
    PRD §3.8: "The request copies its `election_id` from the trigger order rather than
    taking one from the client, stamps `received_at` with the logical clock, and enters
    `RECEIVED` with `owed_units` and `fulfilled_units` at zero and `granted_order_id`,
    `parity_basis_applied`, `denial_reason` and `responded_at` all null."
    PRD §3.8: "Its `response_due_at` is the `received_at` instant plus 24 hours — one
    full day, and no longer."

    Design: Difficulty/cross_entity_state_dependency/eo_request_creation_depends_on_trigger_order_reaching_running
    """
    scenario = setup_two_candidate_orders(
        call_sign="WCR2-TV",
        market_code="DMA-267",
        station_overrides={"licensee_name": "Crossline Broadcasting"},
        trigger_spots=[
            {"air_date": "2026-08-10", "start_offset_seconds": 0, "duration_seconds": 30, "program_code": "EN-T1"},
            {"air_date": "2026-08-10", "start_offset_seconds": 3600, "duration_seconds": 30, "program_code": "EN-T2"},
        ],
        air_trigger=False,
        build_granted_order=False,
    )
    station, requester = scenario["station"], scenario["requester"]

    set_clock("2026-08-10T12:00:00Z")
    air_spot(scenario["trigger_spots"][0]["id"])
    assert read_order(scenario["trigger_order"]["id"])["status"] == "RUNNING", (
        "one of the two spots still remains SCHEDULED"
    )

    created = validate_success(
        api.create_eo_request(
            eo_request_payload(station["id"], requester["id"], scenario["trigger_order"]["id"]),
            make_advertiser_agent_headers(requester["id"]),
        ),
        201,
    )
    assert_eo_request(created)
    assert created["status"] == "RECEIVED"
    assert created["election_id"] == scenario["election"]["id"]
    assert created["received_at"] == "2026-08-10T12:00:00.000Z"
    assert created["response_due_at"] == "2026-08-11T12:00:00.000Z"
    assert created["owed_units"] == 0
    assert created["fulfilled_units"] == 0
    assert created["granted_order_id"] is None
    assert created["responded_at"] is None


def _issue_buyer_past_the_request_window(call_sign, market_code):
    scenario = setup_two_candidate_orders(
        call_sign=call_sign,
        market_code=market_code,
        station_overrides={"licensee_name": "Equal Time Broadcasting"},
        build_granted_order=False,
    )
    scenario["issue_advertiser"] = classify_issue_advertiser(
        scenario["station"]["id"],
        legal_name="Empire Growth Fund",
        election_id=scenario["election"]["id"],
    )
    set_clock("2026-08-25T09:00:00Z")
    return scenario


def test_issue_advertiser_filing_an_eo_request_reports_the_qualification_error(api):
    """PRD §3.8: "The requesting advertiser must itself be sitting in
    `CLASSIFIED_CANDIDATE`; an issue advertiser or an unclassified buyer is refused with
    `ERR_ADVERTISER_NOT_QUALIFIED_CANDIDATE` (HTTP 409)."
    PRD §3.8: "And the filing must be timely: the logical clock must be on or before the
    instant 7 days — one week — after the trigger order's `first_air_at`. A filing at
    exactly that instant is admissible; one instant later is refused with
    `ERR_EO_REQUEST_WINDOW_CLOSED` (HTTP 422)."
    PRD §2.9: "7. **Compliance and safety gates.** `ERR_STATION_POSTURE_FROZEN`, then
    `ERR_ADVERTISER_NOT_CLASSIFIED`, then `ERR_ADVERTISER_NOT_QUALIFIED_CANDIDATE`, then
    `ERR_STATION_POSTURE_RESTRICTED`, then `ERR_DISCLOSURE_NONCONFORMING`, then
    `ERR_DISCLOSURE_AUTHORIZATION_MISSING`, then `ERR_RATE_CLASS_NOT_PREEMPTIBLE`."
    PRD §2.9: "9. **Temporal admissibility.** `ERR_SPOT_AIR_DATE_IN_PAST`, then
    `ERR_SPOT_AIR_DATE_NOT_REACHED`, then `ERR_EO_REQUEST_WINDOW_CLOSED`, then
    `ERR_EO_RESPONSE_DEADLINE_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_error_outranks_temporal_error_on_eo_request_by_issue_advertiser
    """
    scenario = _issue_buyer_past_the_request_window("WEQO-TV", "DMA-355")

    response = api.create_eo_request(
        eo_request_payload(
            scenario["station"]["id"],
            scenario["issue_advertiser"]["id"],
            scenario["trigger_order"]["id"],
        ),
        make_advertiser_agent_headers(scenario["issue_advertiser"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ADVERTISER_NOT_QUALIFIED_CANDIDATE)
    assert response.json()["data"]["error_id"] != "ERR_EO_REQUEST_WINDOW_CLOSED", (
        "the safety gate is evaluated before temporal admissibility"
    )


def test_no_equal_opportunity_row_is_written_when_the_safety_gate_fires(api):
    """PRD §3.8: "The requesting advertiser must itself be sitting in
    `CLASSIFIED_CANDIDATE`; an issue advertiser or an unclassified buyer is refused with
    `ERR_ADVERTISER_NOT_QUALIFIED_CANDIDATE` (HTTP 409)."
    PRD §3.8: "The request copies its `election_id` from the trigger order rather than
    taking one from the client, stamps `received_at` with the logical clock, and enters
    `RECEIVED` with `owed_units` and `fulfilled_units` at zero and `granted_order_id`,
    `parity_basis_applied`, `denial_reason` and `responded_at` all null."

    Design: Difficulty/priority_pair_validation_conflict/safety_error_outranks_temporal_error_on_eo_request_by_issue_advertiser
    """
    scenario = _issue_buyer_past_the_request_window("WEQ2-TV", "DMA-356")

    validate_error(
        api.create_eo_request(
            eo_request_payload(
                scenario["station"]["id"],
                scenario["issue_advertiser"]["id"],
                scenario["trigger_order"]["id"],
            ),
            make_advertiser_agent_headers(scenario["issue_advertiser"]["id"]),
        ),
        ApiErrorId.ERR_ADVERTISER_NOT_QUALIFIED_CANDIDATE,
    )

    _rows, meta = validate_paginated(
        api.list_eo_requests(ADMIN, params={"station_id": scenario["station"]["id"]})
    )
    assert meta["total_count"] == 0


def test_unanswered_request_expires_at_the_checkpoint_and_can_no_longer_be_granted(api):
    """PRD §3.8: "If the response deadline passes with the request still `RECEIVED`, the
    next audit checkpoint on that station moves it `RECEIVED → EXPIRED`, which is
    terminal."
    PRD §3.8: "The request must also still be sitting in `RECEIVED`; a request already
    granted, denied or expired is refused with `ERR_EO_REQUEST_NOT_OPEN` (HTTP 409)."
    PRD §3.9: "Step two expires stale equal-opportunity requests. Every request on the
    station still `RECEIVED` whose `response_due_at` the logical clock has passed moves
    `RECEIVED → EXPIRED`, processed in ascending `created_at` order."

    Design: Corner/state_machines/eo_request_expires_during_audit_sweep_once_the_response_deadline_passes
    """
    scenario = setup_two_candidate_orders(
        call_sign="WEXP-TV",
        market_code="DMA-112",
        station_overrides={"licensee_name": "Expiry Broadcasting Co"},
    )
    set_clock("2026-08-11T09:00:00Z")
    request = file_eo_request(
        scenario["station"]["id"],
        scenario["requester"]["id"],
        scenario["trigger_order"]["id"],
    )
    assert request["response_due_at"] == "2026-08-12T09:00:00.000Z"

    set_clock("2026-08-13T09:00:00Z")
    run_audit_sweep(scenario["station"]["id"])

    expired = read_eo_request(request["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["owed_units"] == 0
    assert expired["granted_order_id"] is None

    validate_error(
        api.respond_eo_request(
            request["id"],
            {"decision": "GRANT", "granted_order_id": scenario["granted_order"]["id"]},
            OFFICER_BETA,
        ),
        ApiErrorId.ERR_EO_REQUEST_NOT_OPEN,
    )


def _granted_request_scenario(call_sign, market_code):
    scenario = setup_two_candidate_orders(
        call_sign=call_sign,
        market_code=market_code,
        eo_parity_basis="SPOT_COUNT",
        station_overrides={"licensee_name": "Unit Parity Broadcasting"},
    )
    set_clock("2026-08-11T09:00:00Z")
    scenario["request"] = file_eo_request(
        scenario["station"]["id"],
        scenario["requester"]["id"],
        scenario["trigger_order"]["id"],
    )
    return scenario


def test_granting_the_request_records_the_owed_units_and_attaches_the_order(api):
    """PRD §3.8: "A `GRANT` requires a `granted_order_id` naming the requester's own
    order that the grant attaches to, and that order must satisfy four conditions at
    once: it must belong to the `requesting_advertiser_id`, it must be sitting in
    `ACCEPTED`, its `election_id` must equal the request's `election_id`, and its
    `rate_class_id` must equal the trigger order's `rate_class_id` — parity is measured
    within a single class of time, not across the rate card."
    PRD §3.8: "Under `SPOT_COUNT`, `owed_units` is the sum, across those spots, of each
    spot's `duration_seconds` divided by thirty — so a sixty-second opponent spot owes 2
    units and a thirty-second spot owes 1, regardless of what either cost."

    Design: Difficulty/compensating_invariant/cancelling_granted_order_conserves_election_equal_opportunity_units
    """
    scenario = _granted_request_scenario("WUNI-TV", "DMA-620")

    granted = grant_eo_request(
        scenario["request"]["id"], scenario["granted_order"]["id"]
    )
    assert_eo_request(granted)
    assert granted["status"] == "GRANTED"
    assert granted["owed_units"] == 1, "the opponent aired a single thirty-second spot"
    assert granted["fulfilled_units"] == 0
    assert granted["granted_order_id"] == scenario["granted_order"]["id"]
    assert granted["parity_basis_applied"] == "SPOT_COUNT"
    assert granted["responded_at"] == "2026-08-11T09:00:00.000Z"


def test_cancelling_the_granted_order_unwinds_the_grant_and_clears_the_units(api):
    """PRD §3.8: "And if the order a grant was attached to is later cancelled, the grant
    is unwound rather than left dangling: the request reverts `GRANTED → RECEIVED`,
    clearing `granted_order_id`, `parity_basis_applied` and `responded_at`, and
    resetting both `owed_units` and `fulfilled_units` to zero."
    PRD §3.6: "Cancellation also releases any equal-opportunity grant that was attached
    to this order, as described in Section 3.8."

    Design: Difficulty/compensating_invariant/cancelling_granted_order_conserves_election_equal_opportunity_units
    """
    scenario = _granted_request_scenario("WUN2-TV", "DMA-621")
    granted = grant_eo_request(scenario["request"]["id"], scenario["granted_order"]["id"])
    assert granted["owed_units"] == 1

    validate_success(
        api.cancel_order(
            scenario["granted_order"]["id"],
            {"cancellation_reason": "Requester released the equal opportunity flight"},
            make_advertiser_agent_headers(scenario["requester"]["id"]),
        )
    )

    reverted = read_eo_request(scenario["request"]["id"])
    assert reverted["status"] == "RECEIVED"
    assert reverted["owed_units"] == 0
    assert reverted["fulfilled_units"] == 0
    assert reverted["granted_order_id"] is None
    assert reverted["parity_basis_applied"] is None
    assert reverted["responded_at"] is None

    assert read_order(scenario["granted_order"]["id"])["status"] == "CANCELLED"

    outstanding, _meta = validate_paginated(
        api.list_eo_requests(
            ADMIN, params={"election_id": scenario["election"]["id"], "status": "GRANTED"}
        )
    )
    assert sum(row["owed_units"] - row["fulfilled_units"] for row in outstanding) == 0, (
        "the election carries no outstanding equal-opportunity obligation after the unwind"
    )
