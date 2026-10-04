"""Placement negotiation rounds and the alternate-promotion cascade (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    accept_placement_round,
    assert_grant,
    assert_placement_round,
    confirm_grant,
    confirm_grant_payload,
    create_placement_round_payload,
    decline_placement_round,
    expire_placement_round,
    get_application,
    get_grant,
    host_decide,
    make_applicant_headers,
    open_placement_round,
    placement_round_transition_payload,
    set_clock_to,
    setup_grant_pending,
    setup_host_review_pair,
    setup_selected_application,
    validate_error,
    validate_success,
)


def test_placement_respond_after_deadline_returns_offer_expired(
    api, program_officer_headers,
):
    """PRD §3.5: "Acceptance requires the round still OFFERED
    (`ERR_ROUND_NOT_OFFERED`) and the logical clock at or before the
    `response_deadline`, the deadline being inclusive (`ERR_OFFER_EXPIRED`);
    it stamps `responded_at` with the clock, moves the round OFFERED →
    ACCEPTED, and advances the application PLACEMENT → GRANT_PENDING."

    Design: Corner/state_machines/placement_respond_after_deadline_returns_offer_expired
    """
    bundle = setup_selected_application()
    app = bundle["application"]
    round_ = open_placement_round(app, response_deadline="2027-01-01T00:00:00Z")
    set_clock_to("2027-02-01T00:00:00Z")  # strictly past the deadline

    resp = api.transition_placement_round(
        round_["id"], placement_round_transition_payload("ACCEPT"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)

    rounds = validate_success(
        api.list_placement_rounds(app["id"], program_officer_headers)
    )
    assert rounds[0]["status"] == "OFFERED", (
        "a late response must not auto-expire or move the round"
    )
    assert get_application(app)["status"] == "PLACEMENT"


def test_placement_expire_before_deadline_rejected(api, program_officer_headers):
    """PRD §3.5: "A `ProgramOfficer` may instead expire a live offer once the
    clock has moved strictly past the deadline — expiring it any earlier is
    rejected with `ERR_INVALID_STATE` — moving the round OFFERED → EXPIRED."
    PRD §3.5: "Acceptance requires the round still OFFERED
    (`ERR_ROUND_NOT_OFFERED`) and the logical clock at or before the
    `response_deadline`, the deadline being inclusive (`ERR_OFFER_EXPIRED`);
    it stamps `responded_at` with the clock, moves the round OFFERED →
    ACCEPTED, and advances the application PLACEMENT → GRANT_PENDING."

    Design: Corner/state_machines/placement_expire_before_deadline_rejected
    """
    bundle = setup_selected_application()
    app = bundle["application"]
    round_ = open_placement_round(app, response_deadline="2027-01-01T00:00:00Z")
    set_clock_to("2027-01-01T00:00:00Z")  # exactly the deadline instant

    early = api.transition_placement_round(
        round_["id"], placement_round_transition_payload("EXPIRE"),
        program_officer_headers,
    )
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)

    accepted = api.transition_placement_round(
        round_["id"], placement_round_transition_payload("ACCEPT"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    round_data = validate_success(accepted, 200)
    assert_placement_round(round_data)
    assert round_data["status"] == "ACCEPTED", (
        "the response deadline is inclusive for the applicant's response"
    )
    assert get_application(app)["status"] == "GRANT_PENDING"


def test_second_open_placement_round_rejected(api, host_commission_headers):
    """PRD §3.5: "At most one non-terminal — that is, OFFERED — round may
    exist per application at a time (`ERR_ACTIVE_ROUND_EXISTS`), and the
    negotiation is hard-capped at three rounds in total."

    Design: Corner/state_machines/second_open_placement_round_rejected
    """
    bundle = setup_selected_application()
    app = bundle["application"]
    first = open_placement_round(app)
    assert first["round_number"] == 1

    current_version = get_application(app)["version"]
    resp = api.create_placement_round(
        app["id"],
        create_placement_round_payload(
            current_version,
            institution_name="Aachen Institute",
            institution_band="HIGH",
            response_deadline="2027-04-01T00:00:00Z",
        ),
        host_commission_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_ROUND_EXISTS)

    assert get_application(app)["placement_rounds_used"] == 1, (
        "a rejected round must not increment placement_rounds_used"
    )


def test_round_respond_twice_returns_round_not_offered(api, program_officer_headers):
    """PRD §2.7: "Two state guards carry their own codes at this priority: a
    placement round must be OFFERED to be accepted, declined, or expired
    (`ERR_ROUND_NOT_OFFERED`, 409), and a residency ledger must be ACCRUING to
    record stays or to request a waiver (`ERR_RESIDENCY_NOT_ACCRUING`, 409)."

    Design: Corner/endpoints/round_respond_twice_returns_round_not_offered
    """
    bundle = setup_grant_pending()  # round 1 already ACCEPTED
    round_ = bundle["round"]
    assert round_["status"] == "ACCEPTED"

    resp = api.transition_placement_round(
        round_["id"], placement_round_transition_payload("DECLINE"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROUND_NOT_OFFERED)

    rounds = validate_success(
        api.list_placement_rounds(bundle["application"]["id"], program_officer_headers)
    )
    assert rounds[0]["status"] == "ACCEPTED"
    assert get_application(bundle["application"])["status"] == "GRANT_PENDING"


def test_failed_rounds_leave_application_in_placement(api, program_officer_headers):
    """PRD §3.5: "The new round's `round_number` is the application's
    `placement_rounds_used` plus one, and that counter increments as the round
    opens; the very first round moves the application SELECTED → PLACEMENT."
    PRD §3.5: "Each round's `status` walks from OFFERED to exactly one of
    ACCEPTED, DECLINED, or EXPIRED."

    Rounds 1 (declined) and 2 (expired past its deadline) fail; the
    application survives both in PLACEMENT.

    Design: Difficulty/non_linear_state_machine/placement_round_cyclic_renegotiation
    """
    bundle = setup_selected_application()
    app = bundle["application"]

    r1 = open_placement_round(
        app, institution_name="Munich Marine",
        response_deadline="2027-01-01T00:00:00Z",
    )
    assert r1["round_number"] == 1
    r1 = decline_placement_round(r1, bundle["applicant"])
    assert r1["status"] == "DECLINED"
    assert get_application(app)["status"] == "PLACEMENT"

    r2 = open_placement_round(
        app, institution_name="Hamburg Oceanic", institution_band="HIGH",
        response_deadline="2027-02-01T00:00:00Z",
    )
    assert r2["round_number"] == 2
    set_clock_to("2027-02-02T00:00:00Z")  # strictly past round 2's deadline
    r2 = expire_placement_round(r2)
    assert r2["status"] == "EXPIRED"

    after = get_application(app)
    assert after["status"] == "PLACEMENT", (
        "the application survives failed rounds until the third one dies"
    )
    assert after["placement_rounds_used"] == 2


def test_third_round_acceptance_closes_the_negotiation(api, program_officer_headers):
    """PRD §3.5: "The new round's `round_number` is the application's
    `placement_rounds_used` plus one, and that counter increments as the round
    opens; the very first round moves the application SELECTED → PLACEMENT."
    PRD §3.5: "Acceptance requires the round still OFFERED
    (`ERR_ROUND_NOT_OFFERED`) and the logical clock at or before the
    `response_deadline`, the deadline being inclusive (`ERR_OFFER_EXPIRED`);
    it stamps `responded_at` with the clock, moves the round OFFERED →
    ACCEPTED, and advances the application PLACEMENT → GRANT_PENDING."

    Round 1 DECLINED, round 2 EXPIRED, round 3 ACCEPTED: the cycle ends in
    GRANT_PENDING with placement_rounds_used == 3.

    Design: Difficulty/non_linear_state_machine/placement_round_cyclic_renegotiation
    """
    bundle = setup_selected_application()
    app = bundle["application"]

    r1 = open_placement_round(
        app, institution_name="Munich Marine",
        response_deadline="2027-01-01T00:00:00Z",
    )
    decline_placement_round(r1, bundle["applicant"])

    r2 = open_placement_round(
        app, institution_name="Hamburg Oceanic", institution_band="HIGH",
        response_deadline="2027-02-01T00:00:00Z",
    )
    set_clock_to("2027-02-02T00:00:00Z")
    expire_placement_round(r2)
    assert get_application(app)["status"] == "PLACEMENT"

    r3 = open_placement_round(
        app, institution_name="Kiel Institute",
        response_deadline="2027-03-01T00:00:00Z",
    )
    assert r3["round_number"] == 3
    r3 = accept_placement_round(r3, bundle["applicant"])
    assert r3["status"] == "ACCEPTED"

    after = get_application(app)
    assert after["status"] == "GRANT_PENDING"
    assert after["placement_rounds_used"] == 3


def test_grant_confirmation_rejected_while_round_still_offered(
    api, program_officer_headers,
):
    """PRD §3.6: "Confirmation is gated: the application must be
    GRANT_PENDING, meaning an accepted placement exists
    (`ERR_PLACEMENT_NOT_SECURED`); the grant must still be PROVISIONAL
    (`ERR_INVALID_STATE`); the confirmed duration must fall within the country
    program's bounds (`ERR_DURATION_OUT_OF_RANGE`); the `start_date` must not
    precede the logical clock's date (`ERR_START_DATE_IN_PAST`); and the
    requested period must not collide with another live grant of the same
    applicant (`ERR_GRANT_PERIOD_OVERLAP`)."

    Design: Difficulty/cross_entity_state_dependency/grant_confirm_requires_accepted_placement
    """
    bundle = setup_selected_application()
    round_ = open_placement_round(bundle["application"])
    assert round_["status"] == "OFFERED"
    assert get_application(bundle["application"])["status"] == "PLACEMENT"

    resp = api.confirm_grant(
        bundle["application"]["id"],
        confirm_grant_payload(
            start_date="2027-09-01T00:00:00Z", end_date="2028-07-01T00:00:00Z",
        ),
        program_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_NOT_SECURED)

    grant = get_grant(bundle["grant"])
    assert grant["status"] == "PROVISIONAL"
    assert grant.get("final_total_cents") is None


def test_grant_confirmation_succeeds_once_placement_accepted(
    api, program_officer_headers,
):
    """PRD §3.6: "Confirmation moves the grant PROVISIONAL → CONFIRMED and the
    application GRANT_PENDING → AWARDED, its terminal success state."

    Control arm of the placement gate: once the round is ACCEPTED the same
    confirmation call succeeds.

    Design: Difficulty/cross_entity_state_dependency/grant_confirm_requires_accepted_placement
    """
    bundle = setup_grant_pending()
    assert get_application(bundle["application"])["status"] == "GRANT_PENDING"

    grant = confirm_grant(
        bundle["application"],
        start_date="2027-09-01T00:00:00Z", end_date="2028-07-01T00:00:00Z",
    )
    assert_grant(grant)
    assert grant["status"] == "CONFIRMED"
    assert grant["final_monthly_stipend_cents"] == 300000
    assert grant["final_total_cents"] == 3350000, (
        f"(300000 + 20000)*10 + 150000 = 3350000, got {grant['final_total_cents']}"
    )
    assert get_application(bundle["application"])["status"] == "AWARDED"


def test_third_round_decline_fails_placement_and_promotes_alternate(
    api, program_officer_headers,
):
    """PRD §3.5: "Either way, when the round that just died is the
    application's third — its `round_number` equal to the three-round cap —
    the negotiation is over: the application cascades PLACEMENT →
    PLACEMENT_FAILED, its slot is released, and the alternate auto-promotion
    of §3.4 runs for the freed slot."
    PRD §3.4: "The single winning alternate moves ALTERNATE → SELECTED,
    re-consumes the slot, and spawns its own PROVISIONAL grant with
    provisional award terms."

    Design: Difficulty/transitive_cascade/placement_exhaustion_triggers_alternate_promotion
    """
    pair = setup_host_review_pair(slot_quota=1)
    app_a, applicant_a = pair["application"], pair["applicant"]
    app_b = pair["application_b"]
    host_decide(app_a, "SELECT")
    host_decide(app_b, "ALTERNATE")

    round_ = None
    for institution in ("Bonn Geological", "Aachen Mining", "Dresden Geo"):
        round_ = open_placement_round(app_a, institution_name=institution)
        round_ = decline_placement_round(round_, applicant_a)

    assert round_["status"] == "DECLINED"
    assert round_["round_number"] == 3

    failed_a = get_application(app_a)
    assert failed_a["status"] == "PLACEMENT_FAILED", (
        "the third dead round must cascade the application to PLACEMENT_FAILED"
    )
    assert failed_a["placement_rounds_used"] == 3

    promoted_b = get_application(app_b)
    assert promoted_b["status"] == "SELECTED", (
        "the freed slot must auto-promote the lowest-seq alternate"
    )
    grants_b = validate_success(
        api.list_application_grants(app_b["id"], program_officer_headers)
    )
    assert len(grants_b) == 1
    grant_b = grants_b[0]
    assert_grant(grant_b)
    assert grant_b["status"] == "PROVISIONAL"
    assert grant_b["provisional_total_cents"] == 3350000, (
        f"(300000 + 0 + 20000)*10 + 150000 = 3350000, "
        f"got {grant_b['provisional_total_cents']}"
    )

    program = validate_success(
        api.get_country_program(pair["program"]["id"], program_officer_headers)
    )
    assert program["slots_remaining"] == 0, (
        "the freed slot is immediately re-consumed by the promotion"
    )


def test_promotion_creates_no_grant_for_failed_applicant(
    api, program_officer_headers,
):
    """PRD §3.5: "Either way, when the round that just died is the
    application's third — its `round_number` equal to the three-round cap —
    the negotiation is over: the application cascades PLACEMENT →
    PLACEMENT_FAILED, its slot is released, and the alternate auto-promotion
    of §3.4 runs for the freed slot."

    The cascade's links verified from the trigger outward: all three rounds
    of the failed negotiation are terminally DECLINED in order, the failed
    application rests in PLACEMENT_FAILED, and the promoted alternate holds
    the slot as SELECTED.

    Design: Difficulty/transitive_cascade/placement_exhaustion_triggers_alternate_promotion
    """
    pair = setup_host_review_pair(slot_quota=1)
    app_a, applicant_a = pair["application"], pair["applicant"]
    app_b = pair["application_b"]
    host_decide(app_a, "SELECT")
    host_decide(app_b, "ALTERNATE")

    for institution in ("Bonn Geological", "Aachen Mining", "Dresden Geo"):
        round_ = open_placement_round(app_a, institution_name=institution)
        round_ = decline_placement_round(round_, applicant_a)

    rounds_a = validate_success(
        api.list_placement_rounds(app_a["id"], program_officer_headers)
    )
    assert [r["round_number"] for r in rounds_a] == [1, 2, 3]
    assert all(r["status"] == "DECLINED" for r in rounds_a)

    assert get_application(app_a)["status"] == "PLACEMENT_FAILED"
    assert get_application(app_b)["status"] == "SELECTED"
