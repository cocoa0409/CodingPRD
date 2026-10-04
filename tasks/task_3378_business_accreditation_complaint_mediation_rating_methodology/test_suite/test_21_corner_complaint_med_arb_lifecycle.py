"""Corner queue — complaint, mediation and arbitration lifecycle: initial
state, invalid forward/verdict from-states, the full arbitration pipeline,
mediation decline and offer expiry (PRD §3.4, §3.5)."""

from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    accept_mediation,
    assert_complaint,
    business_respond,
    complaint_response_payload,
    conclude_mediation_case,
    consumer_reject,
    create_bureau,
    create_business,
    create_complaint_payload,
    create_consumer,
    escalate_to_arbitration,
    file_and_forward_complaint,
    file_complaint,
    forward_complaint,
    get_business,
    get_complaint,
    make_business_rep_headers,
    make_consumer_headers,
    offer_mediation,
    parse_iso,
    party_response_payload,
    render_decision_payload,
    run_daily_close,
    schedule_arbitration_hearing,
    schedule_mediation_session,
    set_clock,
    setup_mediation_offered,
    setup_unresolved_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def _setup_world():
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    return bureau, consumer, business


def _get_mediation_case(api, complaint_id, case_id):
    rows, _meta = validate_paginated(
        api.list_mediation_cases(complaint_id, ADMIN))
    for row in rows:
        if row["id"] == case_id:
            return row
    raise AssertionError(f"mediation case {case_id} missing")


def test_complaint_created_in_received_with_empty_responses(api):
    """PRD §3.4: "The complaint opens in `RECEIVED` with `filed_at` stamped
    at the current instant; the business's `complaints_open_count` rises by 1,
    and the filing consumer's `complaints_filed_count` reflects the new row."

    Design: Corner/state_machines/complaint_created_in_received_with_empty_responses
    """
    _bureau, consumer, business = _setup_world()
    resp = api.create_complaint(
        create_complaint_payload(consumer["id"], business["id"],
                                 category="SERVICE", description="p1"),
        make_consumer_headers(consumer["id"]))
    data = validate_success(resp, 201)
    assert_complaint(data)
    assert data["status"] == "RECEIVED"
    assert parse_iso(data["filed_at"]) == parse_iso(CLOCK_START_ISO)
    assert data["responses"] == []
    assert data["rebuttal_count"] == 0
    assert data["reopen_count"] == 0
    for field in ("forwarded_at", "response_deadline_at",
                  "last_unresolved_at", "resolution_outcome", "closed_at"):
        assert data[field] is None, field
    assert get_business(business["id"])["complaints_open_count"] == 1


def test_forward_twice_rejected_and_deadline_unchanged(api):
    """PRD §3.4: "Forwarding a complaint in any other state is rejected with
    `ERR_COMPLAINT_INVALID_STATE`."
    PRD §3.4: "the status moves from `RECEIVED` to `FORWARDED`,
    `forwarded_at` is stamped, and `response_deadline_at` is set exactly 14
    days later — precisely 1209600 seconds after `forwarded_at`."

    Design: Corner/state_machines/forward_twice_rejected_and_deadline_unchanged
    """
    _bureau, consumer, business = _setup_world()
    complaint = file_and_forward_complaint(consumer, business)
    assert parse_iso(complaint["response_deadline_at"]) == parse_iso(
        "2026-09-15T00:00:00Z")
    resp = api.forward_complaint(complaint["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_INVALID_STATE)
    current = get_complaint(complaint["id"])
    assert parse_iso(current["response_deadline_at"]) == parse_iso(
        current["forwarded_at"]) + timedelta(days=14)
    assert parse_iso(current["response_deadline_at"]) == parse_iso(
        "2026-09-15T00:00:00Z"), "the rejected forward must not move it"


def test_consumer_accept_before_any_business_response_rejected(api):
    """PRD §3.4: "A response whose `kind` does not match the complaint's
    current state is rejected with `ERR_COMPLAINT_INVALID_STATE`."
    PRD §2.7: "The target resource must be in a valid from-state for the
    requested transition — submit needs `DRAFT`, decision needs `SUBMITTED`,
    reapplication needs `DENIED`; forward needs `RECEIVED`; a business
    response needs `FORWARDED` or `CONSUMER_REBUTTED`; a consumer verdict or
    rebuttal needs `RESPONSE_RECEIVED`; reopen needs `RESOLVED` or
    `UNANSWERED`; a mediation offer needs `UNRESOLVED`; arbitration needs
    `MEDIATION_FAILED`"

    Design: Corner/state_machines/consumer_accept_before_any_business_response_rejected
    """
    _bureau, consumer, business = _setup_world()
    complaint = file_and_forward_complaint(consumer, business)
    resp = api.add_complaint_response(
        complaint["id"],
        complaint_response_payload(kind="CONSUMER_ACCEPT", body="premature"),
        make_consumer_headers(consumer["id"]))
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_INVALID_STATE)
    current = get_complaint(complaint["id"])
    assert current["status"] == "FORWARDED"
    assert current["responses"] == []


def test_arbitration_full_path_adverse_decision_closes_complaint(api):
    """PRD §3.5: "Rendering the decision — `BureauAdmin`, valid only from
    `HEARING_SCHEDULED` (otherwise `ERR_ARBITRATION_INVALID_STATE`) — supplies
    an `outcome` of `ADVERSE_TO_BUSINESS` or `NO_FAULT`, stamps `decided_at`,
    and closes the case as `DECIDED`."
    PRD §3.5: "The complaint then closes as `ARBITRATED`, with
    `resolution_outcome` `ARBITRATION_ADVERSE` when the outcome is adverse to
    the business or `ARBITRATION_NO_FAULT` on a no-fault finding; `closed_at`
    is stamped, `complaints_open_count` drops by 1, `complaints_closed_count`
    rises by 1, and the provisional rating regenerates."
    PRD §3.4: "reopening from any other state is
    `ERR_COMPLAINT_INVALID_STATE`."

    Design: Corner/state_machines/arbitration_full_path_adverse_decision_closes_complaint
    """
    _bureau, consumer, business = _setup_world()
    complaint = setup_unresolved_complaint(consumer, business)
    case = offer_mediation(complaint)
    case = accept_mediation(case, business, consumer)
    case = schedule_mediation_session(
        case, mediator_id="med-a",
        session_start_at="2026-09-22T09:00:00Z",
        session_end_at="2026-09-22T10:00:00Z")
    conclude_mediation_case(case, outcome="NO_AGREEMENT")
    arb = escalate_to_arbitration(get_complaint(complaint["id"]))
    assert arb["status"] == "FILED"
    # A decision before any hearing is scheduled is out of state.
    resp = api.render_arbitration_decision(
        arb["id"], render_decision_payload("ADVERSE_TO_BUSINESS"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_ARBITRATION_INVALID_STATE)
    schedule_arbitration_hearing(
        arb, hearing_room_id="room-A",
        hearing_start_at="2026-10-05T10:00:00Z",
        hearing_end_at="2026-10-05T11:00:00Z")
    resp = api.render_arbitration_decision(
        arb["id"], render_decision_payload("ADVERSE_TO_BUSINESS"), ADMIN)
    decided = validate_success(resp, 200)
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "ADVERSE_TO_BUSINESS"
    assert parse_iso(decided["decided_at"]) == parse_iso(CLOCK_START_ISO)
    closed = get_complaint(complaint["id"])
    assert closed["status"] == "ARBITRATED"
    assert closed["resolution_outcome"] == "ARBITRATION_ADVERSE"
    assert closed["closed_at"] is not None
    mirror = get_business(business["id"])
    assert mirror["complaints_open_count"] == 0
    assert mirror["complaints_closed_count"] == 1
    # ARBITRATED is terminal: reopen is out of state.
    resp = api.reopen_complaint(complaint["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_INVALID_STATE)


def test_mediation_decline_returns_complaint_to_unresolved_without_refresh(
        api):
    """PRD §3.5: "The instant any side declines, the case becomes `DECLINED`
    and the complaint falls back from `MEDIATION_OFFERED` to `UNRESOLVED` —
    importantly without refreshing `last_unresolved_at`, so a declined offer
    does not buy a new mediation window."

    Design: Corner/state_machines/mediation_decline_returns_complaint_to_unresolved_without_window_refresh
    """
    _bureau, consumer, business = _setup_world()
    complaint, case = setup_mediation_offered(consumer, business)
    last_unresolved = get_complaint(complaint["id"])["last_unresolved_at"]
    resp = api.mediation_party_response(
        case["id"],
        party_response_payload(party="BUSINESS", response="DECLINED"),
        make_business_rep_headers(business["id"]))
    declined = validate_success(resp, 200)
    assert declined["status"] == "DECLINED"
    assert declined["business_response"] == "DECLINED"
    after = get_complaint(complaint["id"])
    assert after["status"] == "UNRESOLVED"
    assert after["last_unresolved_at"] == last_unresolved, \
        "a declined offer must not refresh the mediation window anchor"
    # DECLINED is terminal for the case; the complaint admits a fresh offer.
    resp = api.create_mediation_case(complaint["id"], ADMIN)
    assert validate_success(resp, 201)["status"] == "OFFERED"


def test_mediation_offer_expires_via_daily_close(api):
    """PRD §3.5: "If the daily close finds an `OFFERED` case past its
    `offer_deadline_at` without both parties accepted, it expires the case to
    `DECLINED_EXPIRED` with the same fall-back to `UNRESOLVED`, again leaving
    `last_unresolved_at` untouched."
    PRD §3.5: "A party may answer only once: responding when that side's field
    is no longer `PENDING` is rejected with `ERR_MEDIATION_INVALID_STATE`, as
    is any party response while the case is not `OFFERED`."

    Design: Corner/state_machines/mediation_offer_expires_via_daily_close
    """
    bureau, consumer, business = _setup_world()
    complaint, case = setup_mediation_offered(consumer, business)
    assert parse_iso(case["offer_deadline_at"]) == parse_iso(
        case["offered_at"]) + timedelta(days=7)
    set_clock("2026-09-09T00:00:00Z")  # one day past the offer deadline
    run_daily_close(bureau["id"])
    expired = _get_mediation_case(api, complaint["id"], case["id"])
    assert expired["status"] == "DECLINED_EXPIRED"
    assert get_complaint(complaint["id"])["status"] == "UNRESOLVED"
    resp = api.mediation_party_response(
        case["id"],
        party_response_payload(party="CONSUMER", response="ACCEPTED"),
        make_consumer_headers(consumer["id"]))
    validate_error(resp, ApiErrorId.ERR_MEDIATION_INVALID_STATE)
