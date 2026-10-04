"""Host selection, slot accounting, thresholds, and alternates (PRD §3.3-§3.4)."""
from test_helpers import (
    ApiErrorId,
    application_transition_payload,
    assert_grant,
    assert_slot_conservation,
    close_cycle,
    decline_application,
    get_application,
    host_decide,
    make_national_reviewer_headers,
    post_national_quorum_scores,
    recommend_application,
    setup_application_in_host_review,
    setup_host_review_pair,
    setup_submitted_application,
    validate_error,
    validate_success,
    withdraw_application,
)

NATIONAL_REVIEWER_1 = "nr-1"


def test_immediate_consistency_on_selection_side_effects(api, program_officer_headers):
    """PRD §3.4: "A DECIDE with `outcome` SELECT consumes one of the country
    program's quota slots: it requires `slots_remaining` to be at least 1
    (`ERR_COUNTRY_QUOTA_EXHAUSTED`, the fiscal gate of §2.7), moves the
    application HOST_REVIEW → SELECTED, and in the same atomic step creates a
    Grant for the application — bound to it via `application_id` — in
    PROVISIONAL status with the provisional award terms of §3.6."
    PRD §2.10: "Single operations routinely mutate several entities as one
    atomic unit: selecting an application consumes a country slot and creates
    a provisional grant; a declined or failed placement releases the slot and
    may promote an alternate; activating a grant moves its visa sponsorship;
    completing or terminating a grant cascades into the sponsorship, the
    residency ledger, and a freshly created alumni profile."

    Design: Corner/consistency_model/immediate_consistency_on_selection_side_effects
    """
    bundle = setup_application_in_host_review(
        application_overrides={"dependents_count": 1},
    )
    decided = host_decide(bundle["application"], "SELECT")
    assert decided["status"] == "SELECTED", (
        "the SELECT response itself must carry the new status"
    )

    grants = validate_success(
        api.list_application_grants(decided["id"], program_officer_headers)
    )
    assert len(grants) == 1, "exactly one grant may exist for the application"
    grant = grants[0]
    assert_grant(grant)
    assert grant["status"] == "PROVISIONAL"
    assert grant["provisional_monthly_stipend_cents"] == 300000
    assert grant["provisional_total_cents"] == 3850000, (
        f"(300000 + 50000*1 + 20000)*10 + 150000 = 3850000, "
        f"got {grant['provisional_total_cents']}"
    )

    program = validate_success(
        api.get_country_program(bundle["program"]["id"], program_officer_headers)
    )
    assert program["slots_remaining"] == 0


def test_recommend_at_exactly_threshold_succeeds(api):
    """PRD §3.3: "RECOMMEND then requires the stored weighted score to be at
    least 70.00, inclusive, and the feasibility average to be at least 50,
    inclusive (`ERR_SCORE_BELOW_THRESHOLD`)."

    Two (70,70,70) national scores give a weighted score of exactly 70.00;
    the inclusive boundary admits the recommendation.

    Design: Difficulty/boundary_precision_check/recommend_threshold_exactly_at_70
    """
    bundle = setup_submitted_application(program_overrides={"slot_quota": 2})
    app = bundle["application"]
    post_national_quorum_scores(app, scores=(70, 70))
    close_cycle(bundle["cycle"])

    scored = get_application(app)
    assert abs(scored["national_weighted_score"] - 70.00) < 1e-9, (
        f"expected exactly 70.00, got {scored['national_weighted_score']}"
    )

    decided = recommend_application(app)
    assert decided["status"] == "HOST_REVIEW", (
        "a weighted score of exactly 70.00 satisfies the inclusive threshold"
    )
    assert decided["recommend_seq"] == 1


def test_recommend_below_threshold_rejected(api):
    """PRD §3.3: "RECOMMEND then requires the stored weighted score to be at
    least 70.00, inclusive, and the feasibility average to be at least 50,
    inclusive (`ERR_SCORE_BELOW_THRESHOLD`)."

    Scores (70,70,70) and (69,69,69) give per-axis averages of 69.50 and a
    weighted score of 69.50, one score-step below the threshold.

    Design: Difficulty/boundary_precision_check/recommend_threshold_exactly_at_70
    """
    bundle = setup_submitted_application()
    app = bundle["application"]
    post_national_quorum_scores(app, scores=(70, 69))
    close_cycle(bundle["cycle"])

    scored = get_application(app)
    assert abs(scored["national_weighted_score"] - 69.50) < 0.005, (
        f"expected 69.50, got {scored['national_weighted_score']}"
    )

    resp = api.transition_application(
        app["id"], application_transition_payload("DECIDE", outcome="RECOMMEND"),
        make_national_reviewer_headers(NATIONAL_REVIEWER_1),
    )
    validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_THRESHOLD)

    assert get_application(app)["status"] == "NATIONAL_SCREENING"


def test_select_at_one_slot_succeeds_and_second_select_rejected(
    api, host_commission_headers, program_officer_headers,
):
    """PRD §3.4: "A DECIDE with `outcome` SELECT consumes one of the country
    program's quota slots: it requires `slots_remaining` to be at least 1
    (`ERR_COUNTRY_QUOTA_EXHAUSTED`, the fiscal gate of §2.7), moves the
    application HOST_REVIEW → SELECTED, and in the same atomic step creates a
    Grant for the application — bound to it via `application_id` — in
    PROVISIONAL status with the provisional award terms of §3.6."

    Design: Difficulty/boundary_precision_check/select_at_zero_slots_boundary
    """
    pair = setup_host_review_pair(slot_quota=1)
    app_a = host_decide(pair["application"], "SELECT")
    assert app_a["status"] == "SELECTED"

    program = validate_success(
        api.get_country_program(pair["program"]["id"], program_officer_headers)
    )
    assert program["slots_remaining"] == 0, "the single slot is now consumed"

    resp = api.transition_application(
        pair["application_b"]["id"],
        application_transition_payload("DECIDE", outcome="SELECT"),
        host_commission_headers,
    )
    validate_error(resp, ApiErrorId.ERR_COUNTRY_QUOTA_EXHAUSTED)

    assert get_application(pair["application_b"])["status"] == "HOST_REVIEW"


def test_alternate_decision_remains_legal_at_zero_slots(
    api, program_officer_headers,
):
    """PRD §3.4: "A DECIDE with `outcome` ALTERNATE parks the application as a
    reserve, consuming no slot."
    PRD §3.4: "a program's `slots_remaining` is its `slot_quota` minus the
    number of that program's applications currently in the slot-consuming
    states SELECTED, PLACEMENT, GRANT_PENDING, or AWARDED"

    Design: Difficulty/boundary_precision_check/select_at_zero_slots_boundary
    """
    pair = setup_host_review_pair(slot_quota=1)
    host_decide(pair["application"], "SELECT")

    decided_b = host_decide(pair["application_b"], "ALTERNATE")
    assert decided_b["status"] == "ALTERNATE", (
        "ALTERNATE consumes no slot, so it stays legal at slots_remaining 0"
    )

    program = validate_success(
        api.get_country_program(pair["program"]["id"], program_officer_headers)
    )
    assert program["slots_remaining"] == 0


def test_select_then_decline_slot_reconsumed_by_promotion(
    api, program_officer_headers,
):
    """PRD §2.10: "Slot conservation: for every country program, `slot_quota`
    always equals `slots_remaining` plus the number of that program's
    applications currently in slot-consuming states, so selecting and later
    declining the same application leaves `slots_remaining` unchanged."
    PRD §3.4: "The single winning alternate moves ALTERNATE → SELECTED,
    re-consumes the slot, and spawns its own PROVISIONAL grant with
    provisional award terms."

    Design: Difficulty/compensating_invariant/slot_consumption_conservation
    """
    pair = setup_host_review_pair(slot_quota=1)
    app_a, applicant_a = pair["application"], pair["applicant"]
    app_b = pair["application_b"]
    host_decide(app_a, "SELECT")
    host_decide(app_b, "ALTERNATE")

    program = validate_success(
        api.get_country_program(pair["program"]["id"], program_officer_headers)
    )
    assert_slot_conservation(program, 1)

    declined_a = decline_application(app_a, applicant_a)
    assert declined_a["status"] == "DECLINED"

    promoted_b = get_application(app_b)
    assert promoted_b["status"] == "SELECTED", (
        "the freed slot must immediately auto-promote the waiting alternate"
    )
    program = validate_success(
        api.get_country_program(pair["program"]["id"], program_officer_headers)
    )
    assert program["slots_remaining"] == 0, (
        "the promotion re-consumes the freed slot before it can leak"
    )
    assert_slot_conservation(program, 1)


def test_promoted_alternate_decline_leaves_slot_released(
    api, program_officer_headers,
):
    """PRD §2.10: "Slot conservation: for every country program, `slot_quota`
    always equals `slots_remaining` plus the number of that program's
    applications currently in slot-consuming states, so selecting and later
    declining the same application leaves `slots_remaining` unchanged."
    PRD §3.4: "If no alternate is waiting, no promotion happens and the slot
    simply stays released."

    Design: Difficulty/compensating_invariant/slot_consumption_conservation
    """
    pair = setup_host_review_pair(slot_quota=1)
    app_a, applicant_a = pair["application"], pair["applicant"]
    app_b, applicant_b = pair["application_b"], pair["applicant_b"]
    host_decide(app_a, "SELECT")
    host_decide(app_b, "ALTERNATE")
    decline_application(app_a, applicant_a)

    promoted_b = get_application(app_b)
    assert promoted_b["status"] == "SELECTED"
    declined_b = decline_application(promoted_b, applicant_b)
    assert declined_b["status"] == "DECLINED"

    program = validate_success(
        api.get_country_program(pair["program"]["id"], program_officer_headers)
    )
    assert program["slots_remaining"] == 1, (
        "with no alternate left the second decline releases the slot for good"
    )
    assert_slot_conservation(program, 0)


def test_select_on_withdrawn_with_quota_exhausted_state_wins(
    api, host_commission_headers, program_officer_headers,
):
    """PRD §2.7: "The target entity must be in a state from which the
    requested transition exists — otherwise `ERR_INVALID_STATE` (409)"
    PRD §2.7: "The ordering is observable behavior: an expired offer acted on
    through a nonexistent round 404s before any temporal check runs; a
    well-formed request from the wrong role 403s before state is examined; a
    stale `expected_application_version` is detected (412) before ownership is
    examined; and the quota gate fires only after every other check has
    passed."

    Both violations hold at trigger time (WITHDRAWN state, zero slots); the
    state error must win.

    Design: Difficulty/priority_pair_validation_conflict/select_on_withdrawn_with_quota_exhausted_state_wins
    """
    pair = setup_host_review_pair(slot_quota=1)
    host_decide(pair["application"], "SELECT")
    program = validate_success(
        api.get_country_program(pair["program"]["id"], program_officer_headers)
    )
    assert program["slots_remaining"] == 0

    app_b, applicant_b = pair["application_b"], pair["applicant_b"]
    withdrawn = withdraw_application(app_b, applicant_b)
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.transition_application(
        app_b["id"], application_transition_payload("DECIDE", outcome="SELECT"),
        host_commission_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    stayed = get_application(app_b)
    assert stayed["status"] == "WITHDRAWN"
    grants_b = validate_success(
        api.list_application_grants(app_b["id"], program_officer_headers)
    )
    assert grants_b == [], "no grant may be created by a rejected SELECT"


def test_select_with_only_quota_exhausted_returns_quota_error(
    api, host_commission_headers, program_officer_headers,
):
    """PRD §3.4: "A DECIDE with `outcome` SELECT consumes one of the country
    program's quota slots: it requires `slots_remaining` to be at least 1
    (`ERR_COUNTRY_QUOTA_EXHAUSTED`, the fiscal gate of §2.7), moves the
    application HOST_REVIEW → SELECTED, and in the same atomic step creates a
    Grant for the application — bound to it via `application_id` — in
    PROVISIONAL status with the provisional award terms of §3.6."

    The fiscal arm of the pair in isolation: the application is legally in
    HOST_REVIEW, so the quota gate is the one that fires.

    Design: Difficulty/priority_pair_validation_conflict/select_on_withdrawn_with_quota_exhausted_state_wins
    """
    pair = setup_host_review_pair(slot_quota=1)
    host_decide(pair["application"], "SELECT")

    app_b = pair["application_b"]
    resp = api.transition_application(
        app_b["id"], application_transition_payload("DECIDE", outcome="SELECT"),
        host_commission_headers,
    )
    validate_error(resp, ApiErrorId.ERR_COUNTRY_QUOTA_EXHAUSTED)

    assert get_application(app_b)["status"] == "HOST_REVIEW", (
        "a quota-rejected SELECT must leave the application in HOST_REVIEW"
    )
