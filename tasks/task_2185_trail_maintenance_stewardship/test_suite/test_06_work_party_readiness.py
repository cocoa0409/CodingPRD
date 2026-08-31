"""The readiness axis: briefing, clearance, blocking and the weather that drives them."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_work_party,
    brief_party,
    create_party,
    observe_weather,
    read_party,
    read_segment,
    register_volunteer_on_party,
    set_clock,
    setup_approved_plan,
    setup_issued_permit,
    setup_party_with_sawyer,
    setup_planned_party,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def test_briefing_clears_the_readiness_axis_without_touching_the_schedule_axis(api):
    """PRD 3.6: "Nothing on the readiness axis moves the schedule axis, and the briefing capability in particular leaves `schedule_status` completely untouched."
    PRD 3.6: "The party advances `BRIEFED → CLEARED` when three things all hold: the governing agency either has `permit_required` false, or the referenced permit's status is `ISSUED` with the party's `work_type` inside that permit's `allowed_work_types` and both party dates inside the permit window; the segment's `posture` is `OPEN`, or is `HAZARD_RESTRICTED` with the party's `work_type` being anything other than `CHAINSAW`, or is `WET_RESTRICTED` with the party's `work_type` being `SIGNAGE` or `DRY_WORK`; and the governing adoption is `ACTIVE`."
    PRD 3.6: "When that predicate already holds at briefing time, the readiness axis runs straight through to `CLEARED` inside the same call."

    Design: Difficulty/non_linear_state_machine/work_party_schedule_and_readiness_axes_move_independently
    """
    world = setup_party_with_sawyer()

    after_briefing = read_party(world["party_id"])
    assert_work_party(after_briefing)
    assert after_briefing["readiness_status"] == "CLEARED"
    assert after_briefing["schedule_status"] == "PLANNED"

    confirmed = validate_success(
        api.confirm_work_party(world["party_id"], world["lead_headers"])
    )
    assert confirmed["schedule_status"] == "CONFIRMED"
    assert confirmed["readiness_status"] == "CLEARED"


def test_readiness_axis_cycles_while_the_schedule_axis_stays_confirmed(api):
    """PRD 3.6: "From either `CLEARED` or `BRIEFED`, a party moves to `BLOCKED` as soon as any blocking cause holds — the permit is revoked, denied or expired, the segment posture turns blocking, or the parent adoption suspends — and `block_reason` is set to `PERMIT_REVOKED`, `PERMIT_EXPIRED`, `SEGMENT_CLOSED` or `AGREEMENT_SUSPENDED` to say which."
    PRD 3.6: "A blocked party is recovered by re-briefing: the crew leader delivers the briefing again, which is accepted only once no blocking cause still holds — an attempt while a cause persists is refused with `ERR_INVALID_STATE` — and again only when `tool_checklist_complete` is true and `first_aid_kit_count` is at least 1."
    PRD 3.6: "That moves the readiness axis `BLOCKED → BRIEFED`, clears `block_reason` back to null, refreshes `briefing_delivered_at`, and once more runs straight through to `CLEARED` when the clearance predicate holds."
    PRD 3.1: "Any work party the recompute blocks receives `readiness_status` `BLOCKED` with `block_reason` `SEGMENT_CLOSED`."

    Design: Difficulty/non_linear_state_machine/work_party_schedule_and_readiness_axes_move_independently
    """
    world = setup_party_with_sawyer()
    validate_success(api.confirm_work_party(world["party_id"], world["lead_headers"]))

    wet = observe_weather(world["seg_id"], 0.72, "2026-08-01T00:00:00.000Z")
    assert wet["posture"] == "WET_RESTRICTED"

    blocked = read_party(world["party_id"])
    assert blocked["readiness_status"] == "BLOCKED"
    assert blocked["block_reason"] == "SEGMENT_CLOSED"
    assert blocked["schedule_status"] == "CONFIRMED", "the schedule axis never moved"

    dry = observe_weather(world["seg_id"], 0.20, "2026-08-01T00:00:00.000Z")
    assert dry["posture"] == "OPEN"

    still_blocked = read_party(world["party_id"])
    assert still_blocked["readiness_status"] == "BLOCKED", (
        "recovery from BLOCKED happens only by re-briefing"
    )
    assert still_blocked["schedule_status"] == "CONFIRMED"

    rebriefed = brief_party(world["party_id"], world["lead_id"])
    assert rebriefed["readiness_status"] == "CLEARED"
    assert rebriefed["block_reason"] is None
    assert rebriefed["schedule_status"] == "CONFIRMED"


def test_confirmation_is_refused_while_the_segment_is_wet_restricted(api):
    """PRD 2.6: "Under a `WET_RESTRICTED` posture, confirming or starting a work party is permitted only when the party's `work_type` is `SIGNAGE` or `DRY_WORK`; under a `HAZARD_RESTRICTED` posture, confirming or starting is permitted for every work type except `CHAINSAW`. Either restriction violation is rejected with `ERR_WET_WEATHER_RESTRICTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/work_party_confirm_gated_by_trail_segment_wet_posture
    """
    world = setup_party_with_sawyer()
    wet = observe_weather(world["seg_id"], 0.72, "2026-08-01T00:00:00.000Z")
    assert wet["posture"] == "WET_RESTRICTED"

    response = api.confirm_work_party(world["party_id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_WET_WEATHER_RESTRICTED.value, 409)
    assert read_party(world["party_id"])["schedule_status"] == "PLANNED"


def test_confirmation_succeeds_once_a_dry_observation_reopens_the_segment(api):
    """PRD 2.6: "A fresh observation below the threshold, or simply the ageing of the last observation past the 72-hour freshness horizon, returns the segment from `WET_RESTRICTED` to `OPEN` on the same conditions."
    PRD 3.6: "That moves the readiness axis `BLOCKED → BRIEFED`, clears `block_reason` back to null, refreshes `briefing_delivered_at`, and once more runs straight through to `CLEARED` when the clearance predicate holds."
    PRD 3.6: "Confirmation moves the schedule axis `PLANNED → CONFIRMED` and is where the heaviest gate in the system sits."

    Design: Difficulty/cross_entity_state_dependency/work_party_confirm_gated_by_trail_segment_wet_posture
    """
    world = setup_party_with_sawyer()
    observe_weather(world["seg_id"], 0.72, "2026-08-01T00:00:00.000Z")
    validate_error(
        api.confirm_work_party(world["party_id"], world["lead_headers"]),
        ApiErrorId.ERR_WET_WEATHER_RESTRICTED.value,
        409,
    )

    dry = observe_weather(world["seg_id"], 0.20, "2026-08-01T00:00:00.000Z")
    assert dry["posture"] == "OPEN"

    rebriefed = brief_party(world["party_id"], world["lead_id"])
    assert rebriefed["readiness_status"] == "CLEARED"

    confirmed = validate_success(
        api.confirm_work_party(world["party_id"], world["lead_headers"])
    )
    assert confirmed["schedule_status"] == "CONFIRMED"
    assert confirmed["block_reason"] is None


def test_briefing_is_refused_unless_both_gates_are_satisfied(api):
    """PRD 3.6: "The payload carries `tool_checklist_complete` and `first_aid_kit_count`; the briefing is accepted only when `tool_checklist_complete` is true and `first_aid_kit_count` is at least 1, and is otherwise refused with `ERR_BRIEFING_INCOMPLETE`."
    PRD 3.6: "A successful briefing moves the readiness axis `PENDING → BRIEFED`, stamps `briefing_delivered_at` with the logical clock and records the acting `X-User-ID` as `briefing_leader_user_id`."
    PRD 2.5: "On startup the clock is fixed at `2026-08-01T00:00:00Z`; it must never fall back to real wall-clock time."

    Design: Corner/validations/briefing_with_incomplete_tool_checklist_is_rejected
    """
    world = setup_planned_party()

    validate_error(
        api.deliver_briefing(
            world["party_id"],
            {"tool_checklist_complete": False, "first_aid_kit_count": 2},
            world["lead_headers"],
        ),
        ApiErrorId.ERR_BRIEFING_INCOMPLETE.value,
        422,
    )
    validate_error(
        api.deliver_briefing(
            world["party_id"],
            {"tool_checklist_complete": True, "first_aid_kit_count": 0},
            world["lead_headers"],
        ),
        ApiErrorId.ERR_BRIEFING_INCOMPLETE.value,
        422,
    )

    accepted = validate_success(
        api.deliver_briefing(
            world["party_id"],
            {"tool_checklist_complete": True, "first_aid_kit_count": 1},
            world["lead_headers"],
        )
    )
    assert accepted["readiness_status"] == "CLEARED"
    assert accepted["first_aid_kit_count"] == 1
    assert accepted["briefing_delivered_at"] == "2026-08-01T00:00:00.000Z"


def test_seasonal_closure_blocks_the_party_and_refuses_its_confirmation(api):
    """PRD 2.6: "Otherwise, if `seasonal_closure_start_mmdd` is not null and the logical clock's month-and-day falls inside the inclusive window running from `seasonal_closure_start_mmdd` to `seasonal_closure_end_mmdd` — a window that wraps across the year boundary when the start is later in the calendar than the end, as with a window from `12-01` to `03-31` — the posture is `SEASONAL_CLOSED`."
    PRD 2.6: "Any operation that would put people on the ground — confirming a work party, starting a work party, deciding a permit, submitting an adoption agreement, activating an adoption agreement — is rejected with `ERR_SEGMENT_CLOSED` (HTTP 409) when the posture is `SEASONAL_CLOSED` or `INCIDENT_CLOSED`."
    PRD 2.6: "Entering `SEASONAL_CLOSED` sets `readiness_status` to `BLOCKED` with `block_reason` `SEGMENT_CLOSED` on every work party on the segment whose `schedule_status` is `PLANNED` or `CONFIRMED`."

    Design: Corner/validations/seasonal_closure_blocks_work_party_confirm
    """
    world = setup_party_with_sawyer(
        segment_overrides={
            "seasonal_closure_start_mmdd": "09-01",
            "seasonal_closure_end_mmdd": "09-30",
        }
    )
    set_clock("2026-09-05T08:00:00.000Z")
    assert read_segment(world["seg_id"])["posture"] == "SEASONAL_CLOSED"

    response = api.confirm_work_party(world["party_id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_SEGMENT_CLOSED.value, 409)

    party = read_party(world["party_id"])
    assert party["readiness_status"] == "BLOCKED"
    assert party["block_reason"] == "SEGMENT_CLOSED"


def test_party_without_a_referenced_permit_cannot_be_confirmed(api):
    """PRD 2.7: "When a crew leader tries to confirm or start a party that is not `CLEARED`, the ladder above surfaces the specific underlying cause: a missing briefing as `ERR_BRIEFING_INCOMPLETE`, a closed or restricted segment as `ERR_SEGMENT_CLOSED` or `ERR_WET_WEATHER_RESTRICTED`, a missing or non-covering permit as `ERR_PERMIT_NOT_ISSUED`, and an inactive adoption as `ERR_ADOPTION_NOT_ACTIVE`."
    PRD 2.7: "Permit issued and covering (`ERR_PERMIT_NOT_ISSUED`, HTTP 409), on work-party confirmation."
    PRD 3.6: "Its `roster_capacity` is computed at creation and maintained thereafter as the smaller of `max_participants` and the referenced permit's `max_party_size` when a permit is referenced and that permit is `ISSUED`, and simply `max_participants` otherwise."

    Design: Corner/validations/confirm_without_a_referenced_permit_is_rejected
    """
    world = setup_approved_plan()
    party = create_party(world["plan_id"], world["seg_id"], world["lead_id"], None)
    assert party["work_permit_id"] is None
    world["party_id"] = party["id"]
    brief_party(party["id"], world["lead_id"])
    register_volunteer_on_party(
        party["id"], world["lead_id"], world["saw_id"], role_on_crew="SAWYER"
    )

    current = read_party(party["id"])
    assert current["readiness_status"] == "BRIEFED", (
        "an unpermitted party under a permit-requiring agency never clears"
    )
    assert current["roster_capacity"] == 8

    response = api.confirm_work_party(party["id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_PERMIT_NOT_ISSUED.value, 409)
    assert read_party(party["id"])["schedule_status"] == "PLANNED"


def test_party_outside_the_permit_window_is_refused_at_confirmation(api):
    """PRD 3.6: "A `CrewLeader` requesting it must satisfy, in the ladder order of section 2.7: the segment must not be `SEASONAL_CLOSED` or `INCIDENT_CLOSED`; the work-type restriction under `WET_RESTRICTED` or `HAZARD_RESTRICTED` must be honoured; every registrant must hold every certification in `required_certifications`, and where `work_type` is `CHAINSAW` under an agency with `requires_certified_sawyer` true, the party must still retain at least one non-withdrawn shift whose volunteer holds `CERT_SAWYER_B` or `CERT_SAWYER_C`, failing which the confirmation is refused with `ERR_CERTIFICATION_MISSING`; first-aid cover must be adequate; a briefing must be on record, meaning `readiness_status` is no longer `PENDING`; the governing adoption must be `ACTIVE`; where the agency has `permit_required` true, the party must reference a permit that is `ISSUED` and whose `allowed_work_types` contains the party's `work_type`, failing which the confirmation is refused with `ERR_PERMIT_NOT_ISSUED`; both the UTC date of `start_at` and the UTC date of `end_at` must fall inside the permit's inclusive window, failing which it is refused with `ERR_PERMIT_WINDOW_MISMATCH`; the segment interval rule below must be satisfied; and `max_participants` must be no greater than the referenced permit's `max_party_size`, failing which it is refused with `ERR_PARTY_SIZE_EXCEEDS_PERMIT`."

    Design: Corner/validations/permit_window_mismatch_blocks_confirm_of_out_of_window_party
    """
    world = setup_issued_permit()
    party = create_party(
        world["plan_id"],
        world["seg_id"],
        world["lead_id"],
        world["permit_id"],
        start_at="2026-10-10T09:00:00.000Z",
        end_at="2026-10-10T15:00:00.000Z",
    )
    brief_party(party["id"], world["lead_id"])
    register_volunteer_on_party(
        party["id"], world["lead_id"], world["saw_id"], role_on_crew="SAWYER"
    )

    response = api.confirm_work_party(party["id"], world["lead_headers"])
    validate_error(response, ApiErrorId.ERR_PERMIT_WINDOW_MISMATCH.value, 422)

    stored = read_party(party["id"])
    assert stored["readiness_status"] == "BRIEFED"
    assert stored["schedule_status"] == "PLANNED"
