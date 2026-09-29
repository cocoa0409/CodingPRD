"""Writes whose outcome is decided by a row in another aggregate.

A transitional-living placement is gated on the youth's *newest* safety screening
rather than on any cleared screening ever recorded, and an admission's landing
state is selected by its program's derived posture.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    COORDINATOR,
    ApiErrorId,
    admission_payload,
    assert_admission,
    assert_safety_screening,
    assert_tlp_placement,
    clear_screening,
    disposition_screening,
    fetch_program,
    fetch_youth,
    instant,
    intake_youth,
    license_emergency_shelter,
    place_youth,
    request_admission,
    setup_tlp_ready_youth,
    submit_screening,
    tlp_placement_payload,
    validate_error,
    validate_paginated,
)

# ─── Instance: placement blocked until the latest screening is cleared ───

SHELTER_PROGRAM = {
    "name": "Riverside Emergency Shelter",
    "licensed_bed_capacity": 2,
    "min_age_years": 12,
    "max_age_years": 17,
    "max_stay_nights": 21,
}
TLP_PROGRAM = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
JADE = {
    "legal_first_name": "Jade", "legal_last_name": "Kimura",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}
INCOME_CENTS = 90000


def _tlp_ready_youth_with_a_newer_submitted_screening():
    """A youth who is otherwise placement-ready — cleared first screening, resolved
    notification, `OPEN` posture — but whose newest screening still stands
    `SUBMITTED`."""
    setup = setup_tlp_ready_youth(
        shelter_program_overrides=dict(SHELTER_PROGRAM),
        tlp_program_overrides=dict(TLP_PROGRAM),
        youth_overrides=dict(JADE),
        planned_discharge_at=instant("2026-08-15"),
    )
    setup["second_screening"] = submit_screening(
        setup["youth"]["id"], ["CURFEW_ENFORCED"], CASE_MANAGER
    )
    return setup


def test_placement_is_refused_while_the_newest_screening_is_not_cleared(api):
    """PRD §2.10: "30. The youth's most recent screening exists and is `CLEARED` —
    `ERR_SCREENING_REQUIRED`, 422 — on transitional-living placement."
    PRD §3.7: "The youth's most recent safety screening must not stand `ESCALATED`,
    or the request fails with `ERR_SCREENING_ESCALATED_BLOCKS_ACTION`; it must
    furthermore exist and stand `CLEARED`, and a missing or non-cleared screening
    fails with `ERR_SCREENING_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/tlp_placement_blocked_until_latest_screening_is_cleared
    """
    setup = _tlp_ready_youth_with_a_newer_submitted_screening()
    assert setup["screening"]["status"] == "CLEARED", (
        "the youth does own a cleared screening, which is exactly the trap"
    )
    newer = setup["second_screening"]
    assert_safety_screening(newer)
    assert newer["status"] == "SUBMITTED", (
        f"the newest screening has no disposition yet, got {newer['status']}"
    )
    assert newer["score"] == 10, (
        f"a single CURFEW_ENFORCED indicator scores 10, got {newer['score']}"
    )
    assert newer["tier"] == "LOW", f"a score of 10 tiers as LOW, got {newer['tier']}"

    response = api.create_tlp_placement(
        tlp_placement_payload(setup["youth"]["id"], setup["tlp_program"]["id"],
                              INCOME_CENTS),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_SCREENING_REQUIRED.value, 422)
    _rows, meta = validate_paginated(
        api.list_tlp_placements(ADMIN, {"youth_id": setup["youth"]["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no placement row survives the refusal, got {meta['total_count']}"
    )


def test_identical_placement_succeeds_once_that_screening_is_cleared(api):
    """PRD §3.7: "On acceptance the server stamps `placed_at` with the clock instant,
    records the acting coordinator as `coordinator_user_id`, opens the placement with
    `tenancy_status` `PLACED` and `compliance_status` `IN_COMPLIANCE`, sets
    `consecutive_probation_reviews` to 0, `life_skills_credit_hours` to 0,
    `required_savings_cents` to 0, `savings_balance_cents` to 0 and
    `match_awarded_cents` to 0, leaves `exited_at` and `exit_reason` null, copies
    `base_allowance_days` from the program's `max_placement_days`, raises the
    program's `occupied_beds` by one — which forces that program's `utilization_bp`
    and `posture` to be recomputed — and moves the youth `SHELTERED → TLP_ENROLLED`
    with the youth's `version` incremented by one and `governance_vote_eligible`
    recomputed, staying true."

    Design: Difficulty/cross_entity_state_dependency/tlp_placement_blocked_until_latest_screening_is_cleared
    """
    setup = _tlp_ready_youth_with_a_newer_submitted_screening()
    api.create_tlp_placement(
        tlp_placement_payload(setup["youth"]["id"], setup["tlp_program"]["id"],
                              INCOME_CENTS),
        COORDINATOR,
    )

    cleared = disposition_screening(setup["second_screening"]["id"], "CLEARED")
    assert cleared["status"] == "CLEARED", (
        f"the newest screening now stands cleared, got {cleared['status']}"
    )

    placement = place_youth(setup["youth"]["id"], setup["tlp_program"]["id"],
                            INCOME_CENTS)

    assert_tlp_placement(placement)
    assert placement["tenancy_status"] == "PLACED", (
        f"the tenancy opens as placed, got {placement['tenancy_status']}"
    )
    assert placement["compliance_status"] == "IN_COMPLIANCE", (
        f"the savings dimension opens in compliance, got {placement['compliance_status']}"
    )
    assert placement["base_allowance_days"] == 540, (
        "the base allowance is copied from the program's max_placement_days, got "
        f"{placement['base_allowance_days']}"
    )
    assert fetch_youth(setup["youth"]["id"])["status"] == "TLP_ENROLLED", (
        "the placement enrolls the youth in transitional living"
    )
    assert fetch_program(setup["tlp_program"]["id"])["occupied_beds"] == 1, (
        "the placement consumes a transitional-living bed"
    )
    _rows, meta = validate_paginated(
        api.list_tlp_placements(ADMIN, {"youth_id": setup["youth"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one placement was created, got {meta['total_count']}"
    )


# ─── Instance: the program's posture selects the admission's landing state ───

OCCUPANT_DISCHARGE = instant("2026-08-20")
LATER_DISCHARGE = instant("2026-08-25")
AVA = {
    "legal_first_name": "Ava", "legal_last_name": "Reyes",
    "date_of_birth": "2010-03-15", "unaccompanied": True,
}
BO = {
    "legal_first_name": "Bo", "legal_last_name": "Nakamura",
    "date_of_birth": "2012-06-10", "unaccompanied": True,
}
CY = {
    "legal_first_name": "Cy", "legal_last_name": "Ferrer",
    "date_of_birth": "2014-01-20", "unaccompanied": True,
}


def _one_bed_program_with_three_cleared_youths():
    """A one-bed program and three cleared, in-band youths, so nothing but the
    program's posture can decide where each request lands."""
    program = license_emergency_shelter(
        name="Riverside Emergency Shelter",
        licensed_bed_capacity=1,
        min_age_years=12,
        max_age_years=17,
        max_stay_nights=21,
    )
    youths = []
    for attributes in (AVA, BO, CY):
        youth = intake_youth(**dict(attributes))
        clear_screening(youth["id"])
        youths.append(youth)
    return program, youths


def test_first_request_lands_active_against_an_open_program(api):
    """PRD §3.3: "When the program's posture is not `FROZEN` and the youth's most
    recent safety screening — the screening of that youth with the greatest
    `created_at` — exists and stands `CLEARED`, and no other non-terminal admission
    of that youth overlaps the requested interval, and the priority floor is
    satisfied where a `RESTRICTED` posture demands it, the admission is created
    `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/admission_landing_state_determined_by_program_posture
    """
    program, (occupant, _bo, _cy) = _one_bed_program_with_three_cleared_youths()

    admission = request_admission(occupant["id"], program["id"], OCCUPANT_DISCHARGE)

    assert_admission(admission)
    assert admission["status"] == "ACTIVE", (
        f"an open program admits straight away, got {admission['status']}"
    )
    assert admission["capacity_blocked"] is False, (
        f"no capacity block applied, got {admission['capacity_blocked']}"
    )
    assert fetch_program(program["id"])["posture"] == "FROZEN", (
        "the single bed is now taken, so the program freezes"
    )


def test_same_request_lands_waitlisted_against_a_frozen_program(api):
    """PRD §3.3: "The `WAITLISTED` branch sets `capacity_blocked` to true, leaves
    `admitted_at` null, still freezes `priority_score`, raises the program's
    `waitlisted_count` by one, and consumes no bed at all, so `occupied_beds`,
    `utilization_bp` and `posture` are all unchanged; no notification obligation is
    created and the youth's `status` is untouched."
    PRD §3.3: "The **capacity branch is evaluated before the screening branch**, and
    this ordering matters: a youth with no cleared screening arriving at a `FROZEN`
    program lands in `WAITLISTED`, never in `PENDING_SCREENING`."

    Design: Difficulty/cross_entity_state_dependency/admission_landing_state_determined_by_program_posture
    """
    program, (occupant, waitlisted, _cy) = _one_bed_program_with_three_cleared_youths()
    request_admission(occupant["id"], program["id"], OCCUPANT_DISCHARGE)

    admission = request_admission(waitlisted["id"], program["id"], LATER_DISCHARGE)

    assert_admission(admission)
    assert admission["status"] == "WAITLISTED", (
        "an identical body against a frozen program rests on the waitlist, got "
        f"{admission['status']}"
    )
    assert admission["capacity_blocked"] is True, (
        f"the capacity block is recorded on the row, got {admission['capacity_blocked']}"
    )
    assert admission["admitted_at"] is None, (
        f"no stay has begun, got {admission['admitted_at']}"
    )
    assert admission["projected_billable_nights"] is None, (
        "nights are only projected from an admitted stay, got "
        f"{admission['projected_billable_nights']}"
    )
    assert admission["priority_score"] == 31, (
        "sixteen age points plus fifteen exposure points is 31, got "
        f"{admission['priority_score']}"
    )
    _rows, meta = validate_paginated(
        api.list_guardian_notifications(admission["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 0, (
        f"a waitlisted admission creates no obligation, got {meta['total_count']}"
    )
    youth = fetch_youth(waitlisted["id"])
    assert youth["status"] == "PROSPECT", (
        f"the youth's status is untouched, got {youth['status']}"
    )
    assert youth["risk_posture"] == "OPEN", (
        f"no obligation means no restriction, got {youth['risk_posture']}"
    )
    current = fetch_program(program["id"])
    assert current["occupied_beds"] == 1, (
        f"the waitlisted request consumes no bed, got {current['occupied_beds']}"
    )
    assert current["waitlisted_count"] == 1, (
        f"one candidate is now waiting, got {current['waitlisted_count']}"
    )


def test_waitlist_opt_out_turns_the_frozen_landing_into_a_refusal(api):
    """PRD §2.10: "43. Licensed capacity is respected — `ERR_BED_CAPACITY_EXCEEDED`,
    409 — on the admission request when waitlisting was opted out of against a
    `FROZEN` program, and on transitional-living placement when the program's beds
    are already full."
    PRD §3.3: "The optional `waitlist_opt_out` flag declares that the caller wants an
    outright refusal rather than a waitlist slot when no bed is free; when omitted it
    behaves as false."

    Design: Difficulty/cross_entity_state_dependency/admission_landing_state_determined_by_program_posture
    """
    program, (occupant, waitlisted, opted_out) = _one_bed_program_with_three_cleared_youths()
    request_admission(occupant["id"], program["id"], OCCUPANT_DISCHARGE)
    request_admission(waitlisted["id"], program["id"], LATER_DISCHARGE)

    response = api.create_admission(
        admission_payload(opted_out["id"], program["id"], LATER_DISCHARGE,
                          waitlist_opt_out=True),
        CASE_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_BED_CAPACITY_EXCEEDED.value, 409)
    _rows, meta = validate_paginated(
        api.list_admissions(ADMIN, {"youth_id": opted_out["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the refused request persists nothing, got {meta['total_count']}"
    )
    current = fetch_program(program["id"])
    assert current["occupied_beds"] == 1, (
        f"the refusal changes no bed accounting, got {current['occupied_beds']}"
    )
    assert current["waitlisted_count"] == 1, (
        f"only the earlier candidate waits, got {current['waitlisted_count']}"
    )
