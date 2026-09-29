"""Governing the cycle: posture moves, the locked write gate and the recalibration vote."""
from test_helpers import (
    ApiErrorId,
    AUDITOR_USER_ID,
    WPO_USER_ID,
    amend_payload,
    api_client,
    create_cycle,
    create_neighborhood,
    create_team,
    draft_review,
    finalize,
    list_all,
    open_and_finalize_week,
    open_week,
    pin_clock,
    posture_payload,
    read_allocation,
    read_cycle,
    read_neighborhood,
    read_review,
    read_team,
    read_week,
    read_employee,
    recalibration_decision_payload,
    register_employee,
    reserve_allocation,
    seat_allocation_payload,
    set_posture,
    submit_review,
    decide_review,
    validate_error,
)
from test_helpers.fixtures import AUDITOR, HRBP, SYSTEM, WPO

GOVERNED_CYCLE = {
    "effective_from": "2026-09-01",
    "effective_to": "2026-12-31",
    "days_in_office_floor": 2,
    "badge_weight": 0.60,
    "network_weight": 0.40,
    "collaboration_target_score": 70.00,
    "equity_variance_threshold_pct": 20.00,
}

BOUNDARY_CYCLE = {
    "effective_from": "2026-09-01",
    "effective_to": "2026-12-31",
    "days_in_office_floor": 2,
    "badge_weight": 0.60,
    "network_weight": 0.40,
    "collaboration_target_score": 60.00,
    "equity_variance_threshold_pct": 50.00,
}

THREE_DAY_TEAM = {
    "expected_days_in_office_per_week": 3,
    "core_collaboration_days": ["TUE", "WED", "THU"],
    "headcount_planned": 12,
    "signal_corroboration_required": False,
}

BADGED_DATES = ["2026-09-08", "2026-09-09", "2026-09-10"]


def _a_cycle_holding_space_and_two_weeks():
    """A reserved slice, one settled week and one still-open week under a single cycle."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CE2", **GOVERNED_CYCLE)
    team = create_team(cycle["id"], team_code="T1-CORE", **THREE_DAY_TEAM)
    employee = register_employee(
        team["id"], employee_number="E-1001", work_email="e1001@corp.example"
    )
    zone = create_neighborhood(
        cycle["id"], team["id"], neighborhood_code="N-A1", site_code="NYC-01",
        seat_count=30, buffer_seats=4, desk_index_from=1, desk_index_to=30,
    )
    allocation = reserve_allocation(zone["id"], team["id"], 5, "2026-W37", "2026-W41")
    settled_week = finalize(open_week(employee["id"], "2026-W37")["id"])
    live_week = open_week(employee["id"], "2026-W38")
    return {
        "cycle": cycle,
        "team": team,
        "employee": employee,
        "zone": zone,
        "allocation": allocation,
        "settled_week": settled_week,
        "live_week": live_week,
    }


def _two_teams_facing_a_vote():
    """A three-day team that cannot absorb -2 and a five-day team that can."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CRN31", **GOVERNED_CYCLE)
    small_team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    large_team = create_team(
        cycle["id"], team_code="T-B", expected_days_in_office_per_week=5,
        core_collaboration_days=["MON", "TUE", "WED", "THU", "FRI"],
        headcount_planned=40, signal_corroboration_required=True,
    )
    recalibrating = set_posture(cycle["id"], "RECALIBRATING", note="H1 recalibration vote")
    return {
        "cycle": cycle,
        "small_team": small_team,
        "large_team": large_team,
        "recalibrating": recalibrating,
    }


def _a_workforce_split_across_bands(cycle_label, cycle_dials, roster,
                                    breaching_numbers):
    """One team whose people sit in the named bands, with the named ones in breach."""
    pin_clock()
    cycle = create_cycle(cycle_label=cycle_label, **cycle_dials)
    team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    people = {}
    for number, band in roster:
        people[number] = register_employee(
            team["id"], employee_number=number,
            work_email=f"{number.lower().replace('-', '')}@corp.example",
            demographic_band=band,
        )
    for number in breaching_numbers:
        open_and_finalize_week(people[number]["id"], "2026-W37", BADGED_DATES)
    recalibrating = set_posture(cycle["id"], "RECALIBRATING")
    return {
        "cycle": cycle,
        "team": team,
        "people": people,
        "recalibrating": recalibrating,
    }


def test_01_locking_the_cycle_freezes_every_zone_and_locks_every_settled_week():
    """One posture write reaches into space and into attendance without touching load.

    PRD 2.9: "A cycle in `LOCKED` posture accepts no mutation at all — `LOCKED` is
    terminal, and nothing brings a cycle back out of it."
    PRD 3.1: "Reaching `LOCKED`, from either predecessor posture, does three things
    beyond setting `posture`: every neighborhood in the cycle recomputes its
    `allocation_state`, which becomes `FROZEN` because the parent posture is now
    `LOCKED`; every attendance week of every employee on a team in the cycle whose
    `status` is `FINALIZED` transitions to `LOCKED`; and the cycle's own `version`
    advances by one."
    PRD 3.8: "And `allocation_state` is `FROZEN` whenever the parent cycle's posture is
    `LOCKED`; otherwise `TIGHT` when `utilization_pct` has reached 90.00; otherwise
    `OPEN`."
    PRD 3.3: "Every role in the company is eventually classified as one of three
    eligibility classes — `FULLY_REMOTE`, `HYBRID` or `ONSITE_REQUIRED` — and until a
    classification has been approved the employee is treated as `ONSITE_REQUIRED`."
    PRD 3.4: "An `ONSITE_REQUIRED` employee is required for all five working days."

    Design: Difficulty/cross_entity_state_dependency/cycle_lock_freezes_space_and_blocks_every_child_write
    """
    scenario = _a_cycle_holding_space_and_two_weeks()
    cycle_id = scenario["cycle"]["id"]
    zone_id = scenario["zone"]["id"]
    assert read_neighborhood(zone_id)["allocation_state"] == "OPEN"
    assert scenario["settled_week"]["status"] == "FINALIZED"
    assert scenario["live_week"]["status"] == "OPEN"

    before_lock_version = read_cycle(cycle_id)["version"]
    locked = set_posture(cycle_id, "LOCKED", note="cycle closed for the FY27 audit")
    assert locked["posture"] == "LOCKED"
    assert locked["version"] == before_lock_version + 1, (
        "the lock advances the cycle's version by exactly one from wherever the "
        "fixture's own cascades left it"
    )

    zone = read_neighborhood(zone_id)
    assert zone["allocation_state"] == "FROZEN", (
        "the frozen state is derived from the parent posture, not from the load"
    )
    assert zone["utilization_pct"] == 0.00, "nothing was ever committed here"
    assert zone["peak_committed_seats"] == 0

    assert read_week(scenario["settled_week"]["id"])["status"] == "LOCKED"
    assert read_week(scenario["live_week"]["id"])["status"] == "OPEN", (
        "only settled weeks were swept; an open week is left where it stood"
    )

    employee = read_employee(scenario["employee"]["id"])
    assert employee["cumulative_shortfall_days"] == 5, (
        "the locked week still counts, so locking erases no compliance history"
    )


def test_02_the_locked_gate_answers_before_any_child_lifecycle_or_version_rule():
    """Four writes that would each fail for their own reasons all report the lock instead.

    PRD 2.9: "The `LOCKED` refusal is `ERR_CYCLE_LOCKED` (HTTP 409) and it guards fifteen
    operations: `POST /teams`, `POST /employees`, `POST /eligibility-classifications`,
    `POST /attendance-weeks`, `POST /attendance-weeks/{week_id}/signals`, `POST
    /attendance-weeks/{week_id}/finalize`, `POST /attendance-weeks/{week_id}/amend`,
    `POST /exception-requests`, `POST /neighborhoods`, `POST /seat-allocations`, `POST
    /seat-allocations/{allocation_id}/commit`, `POST /desk-assignments`, `POST
    /desk-assignments/auto`, `POST /recalibration-reviews` and `POST
    /recalibration-reviews/{review_id}/submit`."
    PRD 2.9: "Every entity in this system is reachable, through the entity graph, from
    exactly one `PolicyCycle`, and that cycle's `posture` gates writes across the whole
    subtree."
    PRD 3.5: "Only an `HRBusinessPartner` may reopen a week, moving it `FINALIZED →
    AMENDED` with a supplied `amendment_reason`; a week in any other status is refused
    with `ERR_WEEK_NOT_FINALIZED` (409), and the parent cycle must again be `OPEN` or
    `RECALIBRATING`."
    PRD 3.8: "Commit requires `RESERVED` status: an allocation already `COMMITTED` is
    refused with `ERR_ALLOCATION_NOT_RESERVED` (409), while an allocation that has been
    `RELEASED` — a terminal status neither trigger can ever apply to again — is refused
    with `ERR_ALLOCATION_TERMINAL` (409)."

    Design: Difficulty/cross_entity_state_dependency/cycle_lock_freezes_space_and_blocks_every_child_write
    """
    scenario = _a_cycle_holding_space_and_two_weeks()
    zone_id = scenario["zone"]["id"]
    allocation_id = scenario["allocation"]["id"]
    set_posture(scenario["cycle"]["id"], "LOCKED")
    # Read the zone's version *after* the lock: the FROZEN recompute is itself a
    # mutation of the zone, and PRD 2.10 ranks optimistic concurrency (band 8)
    # above cycle posture (band 9), so a pre-lock version would legitimately draw
    # ERR_STALE_NEIGHBORHOOD_VERSION instead of the lock refusal under test.
    live_version = read_neighborhood(zone_id)["version"]

    validate_error(
        api_client.commit_seat_allocation(allocation_id, WPO),
        ApiErrorId.ERR_CYCLE_LOCKED.value,
        409,
    )
    assert read_allocation(allocation_id)["status"] == "RESERVED", (
        "the commit that a frozen zone would also have refused moved nothing"
    )

    validate_error(
        api_client.finalize_week(scenario["live_week"]["id"], SYSTEM),
        ApiErrorId.ERR_CYCLE_LOCKED.value,
        409,
    )
    assert read_week(scenario["live_week"]["id"])["status"] == "OPEN", (
        "the week itself was perfectly open; it is the cycle that is not"
    )

    validate_error(
        api_client.amend_week(
            scenario["settled_week"]["id"], amend_payload("late badge export"), HRBP
        ),
        ApiErrorId.ERR_CYCLE_LOCKED.value,
        409,
    )
    assert read_week(scenario["settled_week"]["id"])["status"] == "LOCKED", (
        "the lock outranks the week's own no-longer-finalized objection"
    )

    validate_error(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, scenario["team"]["id"], live_version,
                allocated_seats=1, window_start_week="2026-W41",
                window_end_week="2026-W43",
            ),
            WPO,
        ),
        ApiErrorId.ERR_CYCLE_LOCKED.value,
        409,
    )
    assert read_neighborhood(zone_id)["version"] == live_version, (
        "the supplied version was current, so the refusal was not the version guard"
    )


def test_03_posture_loops_between_open_and_recalibrating_then_stops_dead_at_locked():
    """The round trip keeps climbing the version, a self-target is refused, LOCKED is final.

    PRD 3.1: "Posture moves are a small, deliberate state machine driven by a
    `target_posture` value and an optional `note`."
    PRD 3.1: "From `OPEN` the cycle may move to `RECALIBRATING` (opening a recalibration
    round) or straight to `LOCKED`; from `RECALIBRATING` it may return to `OPEN` (closing
    the round) or move to `LOCKED`."
    PRD 3.1: "Any request naming a target that is not reachable from the current posture
    — including one naming the posture the cycle is already in, and any target at all out
    of `LOCKED` — is refused with `ERR_INVALID_POSTURE_TRANSITION` (HTTP 409)."
    PRD 3.1: "The two non-terminal moves, `OPEN → RECALIBRATING` and `RECALIBRATING →
    OPEN`, change only `posture` and advance the cycle's `version`."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row, including mutations a cascade
    performs rather than the caller."

    Design: Corner/state_machines/policy_cycle_posture_round_trip_then_locked_rejects_every_target
    """
    cycle = create_cycle(cycle_label="FY27-CRN20", **GOVERNED_CYCLE)
    cycle_id = cycle["id"]
    assert cycle["posture"] == "OPEN"
    assert cycle["version"] == 1

    recalibrating = set_posture(cycle_id, "RECALIBRATING", note="H1 measurement window")
    assert recalibrating["posture"] == "RECALIBRATING"
    assert recalibrating["version"] == 2

    validate_error(
        api_client.set_cycle_posture(
            cycle_id, posture_payload("RECALIBRATING"), WPO
        ),
        ApiErrorId.ERR_INVALID_POSTURE_TRANSITION.value,
        409,
    )
    assert read_cycle(cycle_id)["version"] == 2, (
        "naming the posture the cycle already holds is a refusal, not a silent success"
    )

    reopened = set_posture(cycle_id, "OPEN")
    assert reopened["posture"] == "OPEN"
    assert reopened["version"] == 3, "the loop closed and the version did not reset"

    locked = set_posture(cycle_id, "LOCKED")
    assert locked["posture"] == "LOCKED"
    assert locked["version"] == 4

    for refused_target in ("OPEN", "RECALIBRATING"):
        validate_error(
            api_client.set_cycle_posture(
                cycle_id, posture_payload(refused_target), WPO
            ),
            ApiErrorId.ERR_INVALID_POSTURE_TRANSITION.value,
            409,
        )
    terminal = read_cycle(cycle_id)
    assert terminal["posture"] == "LOCKED"
    assert terminal["version"] == 4, "nothing leaves the terminal posture"


def test_04_three_ranked_gates_guard_the_same_review_and_answer_in_their_own_order():
    """Repairing one gate exposes the next: window, then lifecycle, then duties.

    PRD 2.9: "`POST /recalibration-reviews/{review_id}/submit` and `POST
    /recalibration-reviews/{review_id}/decision` both require the parent cycle's posture
    to be exactly `RECALIBRATING`, and refuse with `ERR_CYCLE_NOT_RECALIBRATING` (HTTP
    409) otherwise."
    PRD 3.9: "A new review lands in `DRAFT` state with `submitted_by_user_id` and
    `decided_by_user_id` null, `decision_reason` null, `collaboration_index` and
    `equity_variance_pct` at 0.00, `total_space_chargeback_cents` and
    `qualifying_band_count` at 0, and `meets_collaboration_target` and `equity_flag` both
    false."
    PRD 3.9: "Submitting the review is what freezes the snapshot, and it requires `DRAFT`
    state — a second submit, or a submit against a `SUBMITTED`, `ADOPTED` or `REJECTED`
    review, is refused with `ERR_REVIEW_NOT_DRAFT` (409)."
    PRD 3.9: "It requires `SUBMITTED` state — a `DRAFT` review, or a second decision on
    an `ADOPTED` or `REJECTED` one, is refused with `ERR_REVIEW_NOT_SUBMITTED` (409) — and
    it requires the parent cycle to still be in `RECALIBRATING` posture."
    PRD 3.9: "The caller must not be the person recorded in `submitted_by_user_id`; that
    self-approval is refused with `ERR_SEGREGATION_OF_DUTIES` (409)."
    PRD 3.9: "On `REJECT`, `state` becomes `REJECTED` and not a single team is touched: no
    expectation moves and no entitlement is recomputed."
    PRD 3.9: "Everything else is common to both branches — `decided_by_user_id` is
    recorded as the calling `X-User-ID`, `decision_reason` is stored if supplied, the
    parent cycle's `posture` returns to `OPEN`, and the cycle's `version` advances by
    one."

    Design: Corner/state_machines/recalibration_lifecycle_demands_draft_then_submitted_inside_a_recalibration_window
    """
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CRN30", **GOVERNED_CYCLE)
    cycle_id = cycle["id"]
    team = create_team(cycle_id, team_code="T-A", **THREE_DAY_TEAM)
    review = draft_review(cycle_id, 0, review_label="R-1")
    review_id = review["id"]
    assert review["state"] == "DRAFT"
    assert review["submitted_by_user_id"] is None
    assert review["decided_by_user_id"] is None
    assert review["decision_reason"] is None
    assert review["collaboration_index"] == 0.00
    assert review["equity_variance_pct"] == 0.00
    assert review["total_space_chargeback_cents"] == 0
    assert review["qualifying_band_count"] == 0
    assert review["meets_collaboration_target"] is False
    assert review["equity_flag"] is False

    validate_error(
        api_client.submit_recalibration_review(review_id, WPO),
        ApiErrorId.ERR_CYCLE_NOT_RECALIBRATING.value,
        409,
    )
    assert read_review(review_id)["state"] == "DRAFT", (
        "the row was a perfectly good draft; only the window was shut"
    )

    before_recal_version = read_cycle(cycle_id)["version"]
    recalibrating = set_posture(cycle_id, "RECALIBRATING")
    assert recalibrating["version"] == before_recal_version + 1, (
        "the posture move advances the cycle's version by exactly one"
    )
    recal_version = recalibrating["version"]
    validate_error(
        api_client.decide_recalibration_review(
            review_id, recalibration_decision_payload("ADOPT", recal_version), AUDITOR
        ),
        ApiErrorId.ERR_REVIEW_NOT_SUBMITTED.value,
        409,
    )

    submitted = submit_review(review_id)
    assert submitted["state"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == WPO_USER_ID
    assert submitted["collaboration_index"] == 0.00, "no settled week exists anywhere"
    assert submitted["meets_collaboration_target"] is False
    assert submitted["total_space_chargeback_cents"] == 0
    assert submitted["qualifying_band_count"] == 0
    assert submitted["equity_variance_pct"] == 0.00
    assert submitted["equity_flag"] is False

    validate_error(
        api_client.submit_recalibration_review(review_id, WPO),
        ApiErrorId.ERR_REVIEW_NOT_DRAFT.value,
        409,
    )
    validate_error(
        api_client.decide_recalibration_review(
            review_id, recalibration_decision_payload("REJECT", recal_version), WPO
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )

    rejected = decide_review(
        review_id, "REJECT", recal_version,
        decision_reason="measurement window closed without a change",
    )
    assert rejected["state"] == "REJECTED"
    assert rejected["decided_by_user_id"] == AUDITOR_USER_ID
    assert rejected["decision_reason"] == "measurement window closed without a change"
    untouched = read_team(team["id"])
    assert untouched["expected_days_in_office_per_week"] == 3
    assert untouched["entitled_seats"] == 10
    reopened = read_cycle(cycle_id)
    assert reopened["posture"] == "OPEN", "a rejection reopens the cycle all the same"
    assert reopened["version"] == recal_version + 1, (
        "the decision advances the cycle's version by exactly one"
    )

    validate_error(
        api_client.decide_recalibration_review(
            review_id,
            recalibration_decision_payload("ADOPT", reopened["version"]),
            AUDITOR,
        ),
        ApiErrorId.ERR_REVIEW_NOT_SUBMITTED.value,
        409,
    )


def test_05_the_floor_is_checked_against_every_team_before_a_single_one_is_shifted():
    """A delta only one team cannot absorb changes nothing; the smaller delta moves both.

    PRD 3.9: "Two substantive gates then apply only to an adoption, and their relative
    order is fixed: an adoption whose delta would drive any team's
    `expected_days_in_office_per_week` below the cycle's `days_in_office_floor` is refused
    with `ERR_BELOW_DAYS_FLOOR` (409), and an adoption of a review whose `equity_flag` is
    true is refused with `ERR_EQUITY_FLAG_BLOCKS_ADOPTION` (409)."
    PRD 3.9: "On `ADOPT`, `state` becomes `ADOPTED` and every team in the cycle has its
    `expected_days_in_office_per_week` shifted by `proposed_days_in_office_delta` and then
    clamped into the range 0 through 5 — a team already at 5 receiving a delta of +1 stays
    at 5, and a team at 0 receiving -1 stays at 0 — with the teams processed in `team_code`
    ascending order, and each shifted team immediately re-running the five-step
    seat-entitlement derivation of §3.1 so that `expected_daily_attendance`,
    `base_entitlement`, `buffer_seats_entitled` and `entitled_seats` all reflect the new
    expectation."
    PRD 3.1: "Step three: a buffer percentage is selected from three tiers, evaluated in
    declared order and keyed on `base_entitlement` alone — never on the eventual total —
    where a base of at most 10 takes 20 percent, a base of at most 25 takes 12 percent,
    and any larger base takes 6 percent."
    PRD 3.1: "All four derived fields are recomputed whenever `headcount_planned` or
    `expected_days_in_office_per_week` changes — at enrolment, and again when a
    recalibration is adopted."
    PRD 3.9: "Everything else is common to both branches — `decided_by_user_id` is
    recorded as the calling `X-User-ID`, `decision_reason` is stored if supplied, the
    parent cycle's `posture` returns to `OPEN`, and the cycle's `version` advances by
    one."
    PRD 2.3: "Several collections override that default because their business ordering
    matters more than their insertion ordering: policy cycles are returned newest first,
    by `created_at` descending; teams are ordered by `team_code` ascending; employees by
    `employee_number` ascending; eligibility classifications by `effective_from`
    descending and then `created_at` descending, which is the same ranking the
    current-class selector uses; attendance weeks by `week_start_date` ascending;
    compliance signals by `observed_date` ascending and then `created_at` ascending;
    neighborhoods by `neighborhood_code` ascending; and desk assignments by `start_date`
    ascending and then `desk_index` ascending."

    Design: Corner/state_machines/recalibration_adopt_shifts_every_team_and_reruns_the_entitlement_tier
    """
    scenario = _two_teams_facing_a_vote()
    cycle_id = scenario["cycle"]["id"]
    small_id = scenario["small_team"]["id"]
    large_id = scenario["large_team"]["id"]
    recalibrating_version = scenario["recalibrating"]["version"]
    assert scenario["small_team"]["entitled_seats"] == 10, "base 8 in the 20 percent tier"
    assert scenario["large_team"]["entitled_seats"] == 43, "base 40 in the 6 percent tier"

    too_far = submit_review(
        draft_review(cycle_id, -2, review_label="R-DOWN2")["id"]
    )
    validate_error(
        api_client.decide_recalibration_review(
            too_far["id"],
            recalibration_decision_payload("ADOPT", recalibrating_version),
            AUDITOR,
        ),
        ApiErrorId.ERR_BELOW_DAYS_FLOOR.value,
        409,
    )
    assert read_team(small_id)["expected_days_in_office_per_week"] == 3, (
        "the three-day team would have landed on one, under a floor of two"
    )
    assert read_team(small_id)["entitled_seats"] == 10
    assert read_team(large_id)["expected_days_in_office_per_week"] == 5, (
        "the team that could have absorbed the delta was spared along with the other"
    )
    assert read_team(large_id)["entitled_seats"] == 43
    assert read_review(too_far["id"])["state"] == "SUBMITTED"
    blocked_cycle = read_cycle(cycle_id)
    assert blocked_cycle["posture"] == "RECALIBRATING"
    assert blocked_cycle["version"] == recalibrating_version, (
        "the refused adoption wrote nothing, so the same version guard still holds"
    )

    workable = submit_review(
        draft_review(cycle_id, -1, review_label="R-DOWN1")["id"]
    )
    adopted = decide_review(
        workable["id"], "ADOPT", recalibrating_version,
        decision_reason="collaboration outcomes support one fewer anchor day",
    )
    assert adopted["state"] == "ADOPTED"
    assert adopted["decision_reason"] == (
        "collaboration outcomes support one fewer anchor day"
    )

    shifted_small = read_team(small_id)
    assert shifted_small["expected_days_in_office_per_week"] == 2
    assert shifted_small["expected_daily_attendance"] == 5, "twelve heads over two days"
    assert shifted_small["base_entitlement"] == 5
    assert shifted_small["buffer_seats_entitled"] == 1, "a base of five takes 20 percent"
    assert shifted_small["entitled_seats"] == 6

    shifted_large = read_team(large_id)
    assert shifted_large["expected_days_in_office_per_week"] == 4
    assert shifted_large["expected_daily_attendance"] == 32
    assert shifted_large["base_entitlement"] == 32
    assert shifted_large["buffer_seats_entitled"] == 2, (
        "the tier is keyed on the new base of thirty-two, not on the old forty"
    )
    assert shifted_large["entitled_seats"] == 34

    reopened = read_cycle(cycle_id)
    assert reopened["posture"] == "OPEN"
    assert reopened["version"] == recalibrating_version + 1

    rows, meta = list_all(api_client.list_teams, WPO, {"policy_cycle_id": cycle_id})
    assert meta["total_count"] == 2
    assert [row["team_code"] for row in rows] == ["T-A", "T-B"]
    assert [row["expected_days_in_office_per_week"] for row in rows] == [2, 4]
    assert [row["entitled_seats"] for row in rows] == [6, 34]


def test_06_a_band_of_one_is_dropped_entirely_and_the_flag_it_would_have_raised_blocks_adopt():
    """The lone third band scores nothing and widens nothing; the two-band spread stops ADOPT.

    PRD 3.9: "The population is every employee on a team of this cycle whose `status` is
    `ACTIVE`; `ON_LEAVE` and `SEPARATED` employees are excluded from both the count and
    the compliant count."
    PRD 3.9: "For each of the four bands `BAND_A`, `BAND_B`, `BAND_C` and `BAND_D`, count
    the population in that band; a band holding fewer than 2 such employees is dropped
    entirely and contributes to nothing."
    PRD 3.9: "For each surviving band, count how many of its members have
    `compliance_state` `COMPLIANT`, and the band's rate is 100 multiplied by that
    compliant count, divided by the band's population count, rounded half up to two
    decimals."
    PRD 3.9: "`qualifying_band_count` is the number of surviving bands, considered in
    band-name ascending order."
    PRD 3.9: "Otherwise `equity_variance_pct` is the highest qualifying band rate minus
    the lowest, rounded half up to two decimals."
    PRD 3.9: "`equity_flag` is set to true only when at least 2 bands qualified **and**
    the spread is strictly greater than the cycle's `equity_variance_threshold_pct`; a
    spread exactly equal to the threshold does not raise the flag."
    PRD 3.9: "For each team, sum `credited_days` across all settled weeks of all its
    employees to get the credited total, and sum `required_days` across the same weeks to
    get the demanded total."
    PRD 3.9: "The team's sub-score is 100 multiplied by the credited total, divided by the
    demanded total or by 1 if that total is zero, **rounded half up to two decimals right
    there**."
    PRD 3.9: "`meets_collaboration_target` is then set to true when the index has reached
    the cycle's `collaboration_target_score`, and false otherwise."
    PRD 3.5: "`compliance_state` follows directly from the pressure: `COMPLIANT` when the
    pressure is exactly 0.00, `AT_RISK` when it is above 0.00 but strictly below 2.00, and
    `BREACH` at 2.00 or above."
    PRD 3.9: "On `REJECT`, `state` becomes `REJECTED` and not a single team is touched: no
    expectation moves and no entitlement is recomputed."

    Design: Corner/calculations/equity_variance_suppresses_small_bands_and_the_flag_blocks_adoption
    """
    scenario = _a_workforce_split_across_bands(
        "FY27-CRN44", GOVERNED_CYCLE,
        [("E-A1", "BAND_A"), ("E-A2", "BAND_A"), ("E-B1", "BAND_B"),
         ("E-B2", "BAND_B"), ("E-C1", "BAND_C")],
        ["E-B2", "E-C1"],
    )
    cycle_id = scenario["cycle"]["id"]
    people = scenario["people"]
    recalibrating_version = scenario["recalibrating"]["version"]
    assert read_employee(people["E-A1"]["id"])["compliance_state"] == "COMPLIANT"
    assert read_employee(people["E-B1"]["id"])["compliance_state"] == "COMPLIANT"
    breaching = read_employee(people["E-B2"]["id"])
    assert breaching["non_compliance_pressure"] == 4.00
    assert breaching["compliance_state"] == "BREACH"
    assert read_employee(people["E-C1"]["id"])["compliance_state"] == "BREACH"

    submitted = submit_review(
        draft_review(cycle_id, 0, review_label="R-EQ")["id"]
    )
    assert submitted["state"] == "SUBMITTED"
    assert submitted["qualifying_band_count"] == 2, (
        "two bands of two survive while the band of one is dropped"
    )
    assert submitted["equity_variance_pct"] == 50.00, (
        "the full band scores 100.00 and the halved band 50.00"
    )
    assert submitted["equity_variance_pct"] != 100.00, (
        "the suppressed band would have scored 0.00 and widened the spread"
    )
    assert submitted["equity_flag"] is True, "fifty points clears a twenty-point threshold"
    assert submitted["collaboration_index"] == 60.00, (
        "six credited days against ten demanded on the only team with a settled week"
    )
    assert submitted["meets_collaboration_target"] is False
    assert submitted["total_space_chargeback_cents"] == 0, (
        "no allocation is committed anywhere in the cycle"
    )

    validate_error(
        api_client.decide_recalibration_review(
            submitted["id"],
            recalibration_decision_payload("ADOPT", recalibrating_version),
            AUDITOR,
        ),
        ApiErrorId.ERR_EQUITY_FLAG_BLOCKS_ADOPTION.value,
        409,
    )
    assert read_review(submitted["id"])["state"] == "SUBMITTED"
    untouched = read_team(scenario["team"]["id"])
    assert untouched["expected_days_in_office_per_week"] == 3
    assert untouched["entitled_seats"] == 10
    assert read_cycle(cycle_id)["posture"] == "RECALIBRATING", (
        "the blocked adoption did not close the recalibration window"
    )

    rejected = decide_review(
        submitted["id"], "REJECT", recalibrating_version,
        decision_reason="equity spread must be investigated before any change",
    )
    assert rejected["state"] == "REJECTED", "the flag blocks adoption alone"
    assert rejected["equity_flag"] is True
    closed = read_cycle(cycle_id)
    assert closed["posture"] == "OPEN"
    assert closed["version"] == recalibrating_version + 1


def test_07_both_measures_land_exactly_on_their_thresholds_and_answer_in_opposite_directions():
    """Sixty reaches an inclusive target while fifty fails to exceed a strict one.

    PRD 3.9: "`meets_collaboration_target` is then set to true when the index has reached
    the cycle's `collaboration_target_score`, and false otherwise."
    PRD 3.9: "`equity_flag` is set to true only when at least 2 bands qualified **and**
    the spread is strictly greater than the cycle's `equity_variance_threshold_pct`; a
    spread exactly equal to the threshold does not raise the flag."
    PRD 3.9: "The team's sub-score is 100 multiplied by the credited total, divided by the
    demanded total or by 1 if that total is zero, **rounded half up to two decimals right
    there**."
    PRD 3.9: "Then take the headcount-weighted mean of those already-rounded sub-scores:
    multiply each sub-score by its team's `headcount_planned`, sum those products, divide
    by the sum of the same teams' `headcount_planned`, and round half up to two decimals
    once more."
    PRD 3.9: "Otherwise `equity_variance_pct` is the highest qualifying band rate minus
    the lowest, rounded half up to two decimals."
    PRD 3.2: "Registration also recomputes the parent cycle's
    `aggregate_compliance_rate`, which is the count of `ACTIVE` employees on teams of that
    cycle whose `compliance_state` is `COMPLIANT`, divided by the total count of `ACTIVE`
    employees on those teams, multiplied by 100 and rounded half up to two decimals; when
    no `ACTIVE` employee exists on the cycle's teams at all the rate is exactly 0.00
    rather than an error."
    PRD 3.4: "Under the `SIGNAL_UNION` standard, used when the team does not require
    corroboration, a date counts when **any** of badge, network or attestation evidence is
    satisfied, so a badge-only day counts."
    PRD 3.9: "Everything else is common to both branches — `decided_by_user_id` is
    recorded as the calling `X-User-ID`, `decision_reason` is stored if supplied, the
    parent cycle's `posture` returns to `OPEN`, and the cycle's `version` advances by
    one."

    Design: Corner/cross_cutting_complexity_layers/the_equity_threshold_is_strict_while_the_collaboration_target_is_inclusive
    """
    scenario = _a_workforce_split_across_bands(
        "FY27-CRN65", BOUNDARY_CYCLE,
        [("E-A1", "BAND_A"), ("E-A2", "BAND_A"), ("E-B1", "BAND_B"),
         ("E-B2", "BAND_B")],
        ["E-B1"],
    )
    cycle_id = scenario["cycle"]["id"]
    team_id = scenario["team"]["id"]
    recalibrating_version = scenario["recalibrating"]["version"]

    submitted = submit_review(
        draft_review(cycle_id, 0, review_label="R-EDGE")["id"]
    )
    assert submitted["collaboration_index"] == 60.00, (
        "three credited days against five demanded on the only settled week"
    )
    assert submitted["meets_collaboration_target"] is True, (
        "the target is reached, not exceeded, and reaching it is enough"
    )
    assert submitted["qualifying_band_count"] == 2
    assert submitted["equity_variance_pct"] == 50.00, (
        "one band at 100.00 and one at 50.00"
    )
    assert submitted["equity_flag"] is False, (
        "a spread exactly equal to the threshold does not raise the flag"
    )
    assert submitted["total_space_chargeback_cents"] == 0
    assert read_cycle(cycle_id)["aggregate_compliance_rate"] == 75.00, (
        "three of the four active employees are still compliant"
    )

    adopted = decide_review(
        submitted["id"], "ADOPT", recalibrating_version,
        decision_reason="no change, measures are exactly on target",
    )
    assert adopted["state"] == "ADOPTED", (
        "an inclusive equity comparison would have refused this adoption instead"
    )
    assert adopted["decided_by_user_id"] == AUDITOR_USER_ID
    closed = read_cycle(cycle_id)
    assert closed["posture"] == "OPEN"
    assert closed["version"] == recalibrating_version + 1, (
        "the decision advances the cycle's version by exactly one"
    )

    unmoved = read_team(team_id)
    assert unmoved["expected_days_in_office_per_week"] == 3, (
        "a zero delta adopts without moving the expectation"
    )
    assert unmoved["entitled_seats"] == 10
