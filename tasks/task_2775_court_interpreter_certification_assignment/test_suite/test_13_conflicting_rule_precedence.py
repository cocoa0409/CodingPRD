"""Precedence between two simultaneously violated checks on POST /assignments.

PRD §2.12 declares one global ordered evaluation ladder, so when a single
create request trips two rungs at once the response is pinned to the lower
rung's error. Each conflict scenario is paired with an isolated control that
proves the masked rule is genuinely armed.

Every test builds its own world from scratch — the harness relaunches the API
before each individual test, so no state is shared.
"""

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    create_assignment_payload,
    validate_error,
)
import test_helpers.fixtures as fixtures


# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------
def _vri_hearing_overrides(case_number, scheduled_start, scheduled_end):
    """A class C civil motion asking for video remote interpreting."""
    return {
        "case_number": case_number,
        "hearing_type": "CIVIL_MOTION",
        "in_custody": False,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "requested_delivery_mode": "VRI",
    }


def _setup_unequipped_courthouse_world():
    """North Annex (remote_equipment_tier NONE) plus an ACTIVE CERTIFIED interpreter."""
    config = fixtures.setup_program_config(with_north_courthouse=True)
    bundle = fixtures.setup_active_interpreter(
        config["language"]["id"], target_tier="CERTIFIED"
    )
    assert config["north_courthouse"]["remote_equipment_tier"] == "NONE", (
        "expected NONE, got "
        f"{config['north_courthouse']['remote_equipment_tier']} on the north courthouse"
    )
    return config, bundle


def _schedule_north_vri_hearing(config, case_number, scheduled_start, scheduled_end):
    return fixtures.schedule_hearing(
        config["north_courthouse"]["id"],
        config["language"]["id"],
        **_vri_hearing_overrides(case_number, scheduled_start, scheduled_end),
    )


def _setup_registered_interpreter_on_a_confirmed_class_c_hearing():
    """An ACTIVE REGISTERED interpreter already CONFIRMED on a 12:00-14:00 hearing."""
    config = fixtures.setup_program_config()
    bundle = fixtures.setup_active_interpreter(
        config["language"]["id"],
        target_tier="REGISTERED",
        written_score=TEST_DEFAULTS["REGISTERED_WRITTEN_SCORE"],
        interpreter_overrides={
            "full_name": "Dev Kaur",
            "email": "dev.kaur@courts.example.gov",
        },
    )
    hearing_a = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CV-2026-0026",
        hearing_type="CIVIL_MOTION",
        in_custody=False,
        scheduled_start="2026-08-03T12:00:00.000Z",
        scheduled_end="2026-08-03T14:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    assignment_a = fixtures.propose_assignment(
        hearing_a["id"], bundle["interpreter"]["id"], estimated_one_way_miles=5.0
    )
    assignment_a = fixtures.confirm_assignment(
        assignment_a["id"], bundle["interpreter"]["id"]
    )
    return config, bundle, hearing_a, assignment_a


# ---------------------------------------------------------------------------
# A CONTINUED hearing (rung 13) masks unavailable video equipment (rung 27)
# ---------------------------------------------------------------------------
def test_continued_hearing_masks_the_unavailable_video_equipment(
    api, scheduling_coordinator_headers
):
    """PRD §2.12: "When a single request could fail several checks at once, exactly one error is returned: the first failure in the ordered ladder below."
    PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."
    PRD §2.12 rung 13: "Hearing status admits scheduling work — otherwise `ERR_HEARING_NOT_SCHEDULABLE` (409). Applies to `POST /assignments` and `POST /hearings/{id}/continue`."
    PRD §2.12 rung 27: "Video remote interpreting is technically possible at the courthouse — otherwise `ERR_REMOTE_EQUIPMENT_UNAVAILABLE` (409). Applies to `POST /assignments`."
    PRD §3.5: "The hearing moves to `CONTINUED`, `continuance_count` is increased by 1, `continuance_reason_code` records the supplied code, and `version` is incremented by 1 — which invalidates any `expected_hearing_version` a client was holding."
    PRD §3.6: "The hearing must be in `SCHEDULED` status: a hearing that is `SERVED`, `UNMET`, or `CONTINUED` is not schedulable at all and is refused with `ERR_HEARING_NOT_SCHEDULABLE`, while a hearing that is merely `COVERED` — which is to say one that already carries a `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` assignment — is refused with the dedicated `ERR_HEARING_ALREADY_COVERED`."
    PRD §3.6: "A `VRI` assignment requires the courthouse's `remote_equipment_tier` to be `BASIC` or `CERTIFIED_VRI` and its `status` to be `OPEN`; a facility at tier `NONE` cannot host video remote interpreting at all and the attempt is refused with `ERR_REMOTE_EQUIPMENT_UNAVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_hearing_not_schedulable_wins_over_business_constraint_remote_equipment
    """
    config, bundle = _setup_unequipped_courthouse_world()
    hearing = _schedule_north_vri_hearing(
        config, "CV-2026-0501", "2026-09-15T09:00:00.000Z", "2026-09-15T10:00:00.000Z"
    )
    continued = fixtures.continue_hearing(hearing["id"], reason_code="COURT_CONGESTION")
    assert continued["status"] == "CONTINUED", (
        f"expected CONTINUED, got {continued['status']} after the continuance"
    )

    response = api.create_assignment(
        create_assignment_payload(
            hearing["id"], continued["version"], bundle["interpreter"]["id"],
            delivery_mode="VRI",
        ),
        scheduling_coordinator_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_HEARING_NOT_SCHEDULABLE.value)
    assert error["error_id"] != ApiErrorId.ERR_REMOTE_EQUIPMENT_UNAVAILABLE.value, (
        "the hearing-status rung must mask the video-equipment rung, got "
        f"{error['error_id']}"
    )


def test_continued_hearing_refusal_creates_no_assignment(
    api, scheduling_coordinator_headers
):
    """PRD §3.6: "The hearing must be in `SCHEDULED` status: a hearing that is `SERVED`, `UNMET`, or `CONTINUED` is not schedulable at all and is refused with `ERR_HEARING_NOT_SCHEDULABLE`, while a hearing that is merely `COVERED` — which is to say one that already carries a `CONFIRMED`, `CHECKED_IN`, or `COMPLETED` assignment — is refused with the dedicated `ERR_HEARING_ALREADY_COVERED`."
    PRD §3.5: "A continued hearing is terminal — the coordinator files a fresh hearing for the new date rather than reopening this one — and it is excluded from every counter in language-access reporting, so a continuance never depresses a courthouse's coverage rate."

    Design: Difficulty/priority_pair_validation_conflict/state_hearing_not_schedulable_wins_over_business_constraint_remote_equipment
    """
    config, bundle = _setup_unequipped_courthouse_world()
    hearing = _schedule_north_vri_hearing(
        config, "CV-2026-0501", "2026-09-15T09:00:00.000Z", "2026-09-15T10:00:00.000Z"
    )
    continued = fixtures.continue_hearing(hearing["id"], reason_code="COURT_CONGESTION")

    response = api.create_assignment(
        create_assignment_payload(
            hearing["id"], continued["version"], bundle["interpreter"]["id"],
            delivery_mode="VRI",
        ),
        scheduling_coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_HEARING_NOT_SCHEDULABLE.value)

    rows = fixtures.list_assignments_for_hearing(hearing["id"])
    assert rows == [], f"expected no assignment on the continued hearing, got {rows}"
    assert fixtures.read_hearing(hearing["id"])["status"] == "CONTINUED", (
        "the refused create must leave the hearing CONTINUED"
    )


def test_video_equipment_alone_refuses_a_schedulable_hearing(
    api, scheduling_coordinator_headers
):
    """PRD §3.6: "A `VRI` assignment requires the courthouse's `remote_equipment_tier` to be `BASIC` or `CERTIFIED_VRI` and its `status` to be `OPEN`; a facility at tier `NONE` cannot host video remote interpreting at all and the attempt is refused with `ERR_REMOTE_EQUIPMENT_UNAVAILABLE`."
    PRD §2.12 rung 27: "Video remote interpreting is technically possible at the courthouse — otherwise `ERR_REMOTE_EQUIPMENT_UNAVAILABLE` (409). Applies to `POST /assignments`."

    Design: Difficulty/priority_pair_validation_conflict/state_hearing_not_schedulable_wins_over_business_constraint_remote_equipment
    """
    config, bundle = _setup_unequipped_courthouse_world()
    hearing = _schedule_north_vri_hearing(
        config, "CV-2026-0502", "2026-09-16T09:00:00.000Z", "2026-09-16T10:00:00.000Z"
    )
    assert hearing["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {hearing['status']} on the control hearing"
    )

    response = api.create_assignment(
        create_assignment_payload(
            hearing["id"], hearing["version"], bundle["interpreter"]["id"],
            delivery_mode="VRI",
        ),
        scheduling_coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_REMOTE_EQUIPMENT_UNAVAILABLE.value)

    rows = fixtures.list_assignments_for_hearing(hearing["id"])
    assert rows == [], f"expected no assignment after the refusal, got {rows}"
    assert fixtures.read_hearing(hearing["id"])["status"] == "SCHEDULED", (
        "a refused video create must leave the hearing SCHEDULED"
    )


# ---------------------------------------------------------------------------
# The tier floor (rung 16) masks the double-booking conflict (rung 30)
# ---------------------------------------------------------------------------
def test_tier_floor_masks_the_double_booking_conflict(
    api, scheduling_coordinator_headers
):
    """PRD §2.12: "When a single request could fail several checks at once, exactly one error is returned: the first failure in the ordered ladder below."
    PRD §2.12: "The ladder is global — a check at a lower number always masks a check at a higher number — and it is the reason a request that is both unauthorized and malformed reports only the authorization failure."
    PRD §2.12 rung 16: "That credential's tier meets the hearing's tier floor — otherwise `ERR_TIER_BELOW_HEARING_REQUIREMENT` (409). Applies to `POST /assignments`."
    PRD §2.12 rung 30: "The hearing window does not overlap another live assignment of the same interpreter — otherwise `ERR_INTERPRETER_DOUBLE_BOOKED` (409). Applies to `POST /assignments`."
    PRD §3.5: "Add the type weight, the custody bonus, the rarity bonus and the urgency term, then cap the sum at 100; the result is `priority_score`."
    PRD §3.5: "From it the program derives `priority_class`: `A` when `priority_score` is 80 or more, `B` when it is 55 or more but below 80, and `C` otherwise."
    PRD §3.6: "Otherwise, a class `A` hearing requires `CERTIFIED`, a class `B` hearing requires `REGISTERED`, and a class `C` hearing requires `PROVISIONAL`."
    PRD §3.6: "The comparison is on tier rank — `MASTER` 3, `CERTIFIED` 2, `REGISTERED` 1, `PROVISIONAL` 0 — and the interpreter's best active credential in the hearing's language must rank at or above the required tier's rank."
    PRD §3.6: "A credential ranking below it is refused with `ERR_TIER_BELOW_HEARING_REQUIREMENT`."
    PRD §3.6: "Treat each hearing window as half-open — it includes its start instant and excludes its end instant — and reject the proposal with `ERR_INTERPRETER_DOUBLE_BOOKED` when an existing window starts before the new window ends *and* the new window starts before that existing window ends."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_tier_requirement_wins_over_business_temporal_double_booking
    """
    config, bundle, hearing_a, _ = (
        _setup_registered_interpreter_on_a_confirmed_class_c_hearing()
    )
    assert bundle["credential"]["tier"] == "REGISTERED", (
        f"expected REGISTERED, got {bundle['credential']['tier']} on the active credential"
    )
    assert hearing_a["priority_class"] == "C", (
        f"expected class C, got {hearing_a['priority_class']} on the 12:00-14:00 hearing"
    )

    hearing_b = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-0081",
        hearing_type="TRIAL",
        in_custody=True,
        scheduled_start="2026-08-03T13:00:00.000Z",
        scheduled_end="2026-08-03T15:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    assert hearing_b["priority_score"] == 81, (
        f"expected priority_score 81, got {hearing_b['priority_score']}"
    )
    assert hearing_b["priority_class"] == "A", (
        f"expected class A, got {hearing_b['priority_class']}"
    )

    response = api.create_assignment(
        create_assignment_payload(
            hearing_b["id"], hearing_b["version"], bundle["interpreter"]["id"],
            estimated_one_way_miles=5.0,
        ),
        scheduling_coordinator_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_TIER_BELOW_HEARING_REQUIREMENT.value)
    assert error["error_id"] != ApiErrorId.ERR_INTERPRETER_DOUBLE_BOOKED.value, (
        f"the tier rung must mask the double-booking rung, got {error['error_id']}"
    )


def test_masked_double_booking_leaves_both_hearings_untouched(
    api, scheduling_coordinator_headers
):
    """PRD §3.6: "A credential ranking below it is refused with `ERR_TIER_BELOW_HEARING_REQUIREMENT`."
    PRD §3.5: "`SCHEDULED → COVERED` fires when an assignment for the hearing reaches `CONFIRMED`; note that a merely proposed assignment leaves the hearing `SCHEDULED`, because coverage means acceptance, not intent."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_tier_requirement_wins_over_business_temporal_double_booking
    """
    config, bundle, _, assignment_a = (
        _setup_registered_interpreter_on_a_confirmed_class_c_hearing()
    )
    hearing_b = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CR-2026-0081",
        hearing_type="TRIAL",
        in_custody=True,
        scheduled_start="2026-08-03T13:00:00.000Z",
        scheduled_end="2026-08-03T15:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )

    response = api.create_assignment(
        create_assignment_payload(
            hearing_b["id"], hearing_b["version"], bundle["interpreter"]["id"],
            estimated_one_way_miles=5.0,
        ),
        scheduling_coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_TIER_BELOW_HEARING_REQUIREMENT.value)

    rows = fixtures.list_assignments_for_hearing(hearing_b["id"])
    assert rows == [], f"expected no assignment on the class A hearing, got {rows}"
    assert fixtures.read_hearing(hearing_b["id"])["status"] == "SCHEDULED", (
        "the refused create must leave the class A hearing SCHEDULED"
    )
    assert fixtures.read_assignment(assignment_a["id"])["service_status"] == "CONFIRMED", (
        "the earlier confirmed assignment must survive the refused create"
    )


def test_overlapping_window_alone_refuses_with_interpreter_double_booked(
    api, scheduling_coordinator_headers
):
    """PRD §3.6: "Treat each hearing window as half-open — it includes its start instant and excludes its end instant — and reject the proposal with `ERR_INTERPRETER_DOUBLE_BOOKED` when an existing window starts before the new window ends *and* the new window starts before that existing window ends."
    PRD §2.12 rung 30: "The hearing window does not overlap another live assignment of the same interpreter — otherwise `ERR_INTERPRETER_DOUBLE_BOOKED` (409). Applies to `POST /assignments`."
    PRD §3.6: "Otherwise, a class `A` hearing requires `CERTIFIED`, a class `B` hearing requires `REGISTERED`, and a class `C` hearing requires `PROVISIONAL`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_tier_requirement_wins_over_business_temporal_double_booking
    """
    config, bundle, _, _ = (
        _setup_registered_interpreter_on_a_confirmed_class_c_hearing()
    )
    hearing_c = fixtures.schedule_hearing(
        config["courthouse"]["id"],
        config["language"]["id"],
        case_number="CV-2026-0027",
        hearing_type="CIVIL_MOTION",
        in_custody=False,
        scheduled_start="2026-08-03T13:00:00.000Z",
        scheduled_end="2026-08-03T15:00:00.000Z",
        requested_delivery_mode="IN_PERSON",
    )
    assert hearing_c["priority_class"] == "C", (
        f"expected class C so the tier rung stays silent, got {hearing_c['priority_class']}"
    )

    response = api.create_assignment(
        create_assignment_payload(
            hearing_c["id"], hearing_c["version"], bundle["interpreter"]["id"],
            estimated_one_way_miles=5.0,
        ),
        scheduling_coordinator_headers,
    )
    validate_error(response, ApiErrorId.ERR_INTERPRETER_DOUBLE_BOOKED.value)

    rows = fixtures.list_assignments_for_hearing(hearing_c["id"])
    assert rows == [], f"expected no assignment on the overlapping hearing, got {rows}"
