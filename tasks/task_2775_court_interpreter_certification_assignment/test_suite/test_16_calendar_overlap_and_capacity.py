"""Two occupied resources with opposite interval conventions.

* The interpreter's own calendar is half-open — touching windows do not collide —
  but two in-person legs at *different* courthouses need a 60-minute travel
  buffer (PRD §3.6).
* The courthouse video cart is a closed-interval aggregate: a session ending at
  10:00 still blocks one starting at 10:00, in-person legs consume none of it,
  and a declined row stops occupying it (PRD §3.6, §3.7).

Every test builds its own world; the server starts empty before each test.
"""

import test_helpers.fixtures as fixtures
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["scheduling_coordinator_headers"]


def _schedule_leg(courthouse_id, language_id, case_number, start, end,
                  mode="IN_PERSON"):
    """A spa CIVIL_MOTION hearing, not in custody, in the given window."""
    return fixtures.schedule_hearing(
        courthouse_id,
        language_id,
        case_number=case_number,
        hearing_type="CIVIL_MOTION",
        in_custody=False,
        scheduled_start=start,
        scheduled_end=end,
        requested_delivery_mode=mode,
    )


def _attempt_assignment(api, hearing_id, interpreter_id, delivery_mode="IN_PERSON",
                        miles=0.0):
    """POST /assignments with a freshly read version pin; returns the raw response."""
    version = fixtures.read_hearing(hearing_id)["version"]
    payload = create_assignment_payload(
        hearing_id, version, interpreter_id,
        delivery_mode=delivery_mode, estimated_one_way_miles=miles,
    )
    return api.create_assignment(payload, COORDINATOR)


def _setup_confirmed_morning_leg():
    """Config with a second courthouse + Ana CONFIRMED at CH_MAIN 09:00-11:00Z."""
    config = fixtures.setup_program_config(with_north_courthouse=True)
    interpreter = fixtures.setup_active_interpreter(
        config["language"]["id"], target_tier="CERTIFIED"
    )["interpreter"]
    hearing = _schedule_leg(
        config["courthouse"]["id"], config["language"]["id"], "CV-2026-0701",
        "2026-09-20T09:00:00.000Z", "2026-09-20T11:00:00.000Z",
    )
    assignment = fixtures.propose_assignment(
        hearing["id"], interpreter["id"], estimated_one_way_miles=10.0
    )
    assignment = fixtures.confirm_assignment(assignment["id"], interpreter["id"])
    assert assignment["service_status"] == "CONFIRMED", (
        f"Setup step failed: expected CONFIRMED, got {assignment['service_status']}"
    )
    return config, interpreter, hearing


def _propose_second_main_leg(api, config, interpreter):
    """The accepted 11:00-13:00Z leg at CH_MAIN that the buffer tests build on."""
    hearing = _schedule_leg(
        config["courthouse"]["id"], config["language"]["id"], "CV-2026-0702",
        "2026-09-20T11:00:00.000Z", "2026-09-20T13:00:00.000Z",
    )
    created = validate_success(
        _attempt_assignment(api, hearing["id"], interpreter["id"], miles=10.0),
        expected_status=201,
    )
    return hearing, created


# ---------------------------------------------------------------------------
# The interpreter's calendar: half-open windows plus a conditional buffer
# ---------------------------------------------------------------------------
def test_touching_windows_at_the_same_courthouse_are_accepted(api):
    """PRD §3.6: "Treat each hearing window as half-open — it includes its start instant and excludes its end instant — and reject the proposal with `ERR_INTERPRETER_DOUBLE_BOOKED` when an existing window starts before the new window ends *and* the new window starts before that existing window ends."
    PRD §3.6: "Because the intervals are half-open, two hearings that merely touch do not collide: an interpreter finishing at 11:00 may begin another hearing at 11:00."
    PRD §3.6: "It is considered only when the existing assignment's `delivery_mode` is `IN_PERSON`, the proposed `delivery_mode` is `IN_PERSON`, and the two hearings sit at *different* courthouses; a remote leg on either side, or two in-person legs at the same courthouse, require no gap whatsoever."
    PRD §3.6: "Creation sets `service_status` to `PROPOSED` and `compliance_status` to `CLEAR`, leaves `actual_one_way_miles`, `check_in_utc`, `actual_end_utc` and `cancel_reason_code` null, and deliberately leaves the hearing in `SCHEDULED` — coverage is recorded only on confirmation."

    Design: Difficulty/resource_temporal_overlap/interpreter_half_open_touch_allowed_but_cross_courthouse_travel_buffer_enforced
    """
    config, interpreter, _hearing_a = _setup_confirmed_morning_leg()

    hearing_b, created = _propose_second_main_leg(api, config, interpreter)
    assert created["service_status"] == "PROPOSED", (
        f"expected PROPOSED, got {created['service_status']} on the back-to-back leg "
        "that starts exactly when the confirmed one ends"
    )
    assert created["compliance_status"] == "CLEAR", (
        f"expected CLEAR, got {created['compliance_status']} on a fresh assignment"
    )
    assert created["cancel_reason_code"] is None, (
        f"expected null, got {created['cancel_reason_code']} on a fresh assignment"
    )

    after = fixtures.read_hearing(hearing_b["id"])
    assert after["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {after['status']} — a PROPOSED assignment records no "
        "coverage"
    )


def test_fifty_nine_minute_gap_to_a_different_courthouse_violates_the_travel_buffer(api):
    """PRD §3.6: "It is considered only when the existing assignment's `delivery_mode` is `IN_PERSON`, the proposed `delivery_mode` is `IN_PERSON`, and the two hearings sit at *different* courthouses; a remote leg on either side, or two in-person legs at the same courthouse, require no gap whatsoever."
    PRD §3.6: "Where it does apply, take the later of the two window start instants, subtract the earlier of the two window end instants, and express the difference in minutes: at least 60 minutes must separate the two appearances, with exactly 60 minutes accepted and anything less refused as `ERR_TRAVEL_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/interpreter_half_open_touch_allowed_but_cross_courthouse_travel_buffer_enforced
    """
    config, interpreter, _hearing_a = _setup_confirmed_morning_leg()
    _propose_second_main_leg(api, config, interpreter)

    hearing_c = _schedule_leg(
        config["north_courthouse"]["id"], config["language"]["id"], "CV-2026-0703",
        "2026-09-20T13:59:00.000Z", "2026-09-20T15:00:00.000Z",
    )
    response = _attempt_assignment(api, hearing_c["id"], interpreter["id"], miles=25.0)
    validate_error(response, ApiErrorId.ERR_TRAVEL_BUFFER_VIOLATION)

    rows, meta = validate_paginated(
        api.list_assignments(COORDINATOR, params={"hearing_id": hearing_c["id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected 0, got {meta['total_count']} — the refused create persists no "
        f"assignment (rows: {rows})"
    )


def test_gap_of_exactly_sixty_minutes_across_courthouses_is_accepted(api):
    """PRD §3.6: "Where it does apply, take the later of the two window start instants, subtract the earlier of the two window end instants, and express the difference in minutes: at least 60 minutes must separate the two appearances, with exactly 60 minutes accepted and anything less refused as `ERR_TRAVEL_BUFFER_VIOLATION`."
    PRD §3.6: "Both rules work at second-level precision."
    PRD §3.6: "Assignments are readable individually and by list, the list filterable by `hearing_id`, `interpreter_id`, `credential_id`, `service_status`, and `compliance_status`."

    Design: Difficulty/resource_temporal_overlap/interpreter_half_open_touch_allowed_but_cross_courthouse_travel_buffer_enforced
    """
    config, interpreter, _hearing_a = _setup_confirmed_morning_leg()
    _propose_second_main_leg(api, config, interpreter)

    hearing_d = _schedule_leg(
        config["north_courthouse"]["id"], config["language"]["id"], "CV-2026-0704",
        "2026-09-20T14:00:00.000Z", "2026-09-20T15:00:00.000Z",
    )
    created = validate_success(
        _attempt_assignment(api, hearing_d["id"], interpreter["id"], miles=25.0),
        expected_status=201,
    )
    assert created["service_status"] == "PROPOSED", (
        f"expected PROPOSED, got {created['service_status']} — 14:00 less 13:00 is "
        "exactly the 60 minutes the buffer accepts"
    )

    rows, meta = validate_paginated(
        api.list_assignments(
            COORDINATOR, params={"interpreter_id": interpreter["id"]}
        )
    )
    assert meta["total_count"] == 3, (
        f"expected 3, got {meta['total_count']} — one confirmed and two proposed legs "
        f"stand on this interpreter's calendar (rows: {len(rows)})"
    )

    after = fixtures.read_hearing(hearing_d["id"])
    assert after["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {after['status']} after a PROPOSED assignment"
    )


def test_genuinely_overlapping_window_is_refused_as_double_booking(api):
    """PRD §3.6: "Treat each hearing window as half-open — it includes its start instant and excludes its end instant — and reject the proposal with `ERR_INTERPRETER_DOUBLE_BOOKED` when an existing window starts before the new window ends *and* the new window starts before that existing window ends."
    PRD §3.6: "Two exclusivity rules protect the interpreter as an occupied resource, and both consider only that interpreter's own assignments whose `service_status` is `PROPOSED`, `CONFIRMED`, or `CHECKED_IN`; rows in `DECLINED`, `CANCELLED`, `SUPERSEDED`, `NO_SHOW`, or `COMPLETED` are ignored entirely."

    Design: Difficulty/resource_temporal_overlap/interpreter_half_open_touch_allowed_but_cross_courthouse_travel_buffer_enforced
    """
    config, interpreter, _hearing_a = _setup_confirmed_morning_leg()

    hearing_e = _schedule_leg(
        config["courthouse"]["id"], config["language"]["id"], "CV-2026-0705",
        "2026-09-20T10:00:00.000Z", "2026-09-20T12:00:00.000Z",
    )
    response = _attempt_assignment(api, hearing_e["id"], interpreter["id"], miles=10.0)
    validate_error(response, ApiErrorId.ERR_INTERPRETER_DOUBLE_BOOKED)

    rows, meta = validate_paginated(
        api.list_assignments(COORDINATOR, params={"hearing_id": hearing_e["id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected 0, got {meta['total_count']} — the double-booked create persists "
        f"nothing (rows: {rows})"
    )

    still_scheduled = fixtures.read_hearing(hearing_e["id"])
    assert still_scheduled["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {still_scheduled['status']} on the uncovered hearing"
    )


# ---------------------------------------------------------------------------
# The courthouse video cart: closed intervals, freed by a decline
# ---------------------------------------------------------------------------
def _setup_occupied_vri_cart(api):
    """CH_MAIN (VRI capacity 1) with Ana holding a PROPOSED VRI 09:00-10:00Z leg."""
    config = fixtures.setup_program_config()
    ana = fixtures.setup_active_interpreter(
        config["language"]["id"], target_tier="CERTIFIED"
    )["interpreter"]
    dev = fixtures.setup_active_interpreter(
        config["language"]["id"], target_tier="REGISTERED",
        interpreter_overrides={
            "full_name": "Dev Kaur",
            "email": "dev.kaur@courts.example.gov",
        },
    )["interpreter"]
    hearing_v1 = _schedule_leg(
        config["courthouse"]["id"], config["language"]["id"], "CV-2026-0801",
        "2026-09-21T09:00:00.000Z", "2026-09-21T10:00:00.000Z", mode="VRI",
    )
    av1 = fixtures.propose_assignment(
        hearing_v1["id"], ana["id"], delivery_mode="VRI", estimated_one_way_miles=0.0
    )
    return config, ana, dev, hearing_v1, av1


def _schedule_ten_to_eleven(config, case_number, mode):
    return _schedule_leg(
        config["courthouse"]["id"], config["language"]["id"], case_number,
        "2026-09-21T10:00:00.000Z", "2026-09-21T11:00:00.000Z", mode=mode,
    )


def test_touching_vri_windows_collide_under_the_closed_interval_convention(api):
    """PRD §3.6: "Count the assignments at the same courthouse whose `delivery_mode` is `VRI` and whose `service_status` is `PROPOSED`, `CONFIRMED`, or `CHECKED_IN`, keeping only those whose hearing window intersects the new hearing's window treating both windows as **closed** — an existing window intersects when its start is at or before the new window's end and the new window's start is at or before its end."
    PRD §3.6: "Add one for the assignment being created; if the result exceeds the courthouse's `vri_concurrent_capacity`, the create is refused with `ERR_VRI_CAPACITY_EXCEEDED`."
    PRD §3.6: "Touching endpoints *do* collide here, because the video cart needs setting up and tearing down: a session ending at 10:00 still occupies the courtroom for a session starting at 10:00."

    Design: Difficulty/resource_temporal_overlap/courthouse_vri_capacity_uses_closed_intervals_and_frees_on_decline
    """
    config, _ana, dev, _hearing_v1, av1 = _setup_occupied_vri_cart(api)
    assert config["courthouse"]["vri_concurrent_capacity"] == 1, (
        f"expected 1, got {config['courthouse']['vri_concurrent_capacity']} video "
        "courtrooms at this facility"
    )
    assert av1["service_status"] == "PROPOSED", (
        f"expected PROPOSED, got {av1['service_status']} — a merely proposed video leg "
        "already occupies the cart"
    )

    hearing_v2 = _schedule_ten_to_eleven(config, "CV-2026-0802", "VRI")
    response = _attempt_assignment(
        api, hearing_v2["id"], dev["id"], delivery_mode="VRI", miles=0.0
    )
    validate_error(response, ApiErrorId.ERR_VRI_CAPACITY_EXCEEDED)

    rows, meta = validate_paginated(
        api.list_assignments(COORDINATOR, params={"hearing_id": hearing_v2["id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected 0, got {meta['total_count']} — the refused create persists no "
        f"assignment (rows: {rows})"
    )


def test_in_person_leg_in_the_same_window_consumes_no_video_capacity(api):
    """PRD §3.6: "Count the assignments at the same courthouse whose `delivery_mode` is `VRI` and whose `service_status` is `PROPOSED`, `CONFIRMED`, or `CHECKED_IN`, keeping only those whose hearing window intersects the new hearing's window treating both windows as **closed** — an existing window intersects when its start is at or before the new window's end and the new window's start is at or before its end."
    PRD §3.6: "In-person and telephonic assignments never occupy video capacity, and terminal-service rows never occupy it."

    Design: Difficulty/resource_temporal_overlap/courthouse_vri_capacity_uses_closed_intervals_and_frees_on_decline
    """
    config, _ana, dev, _hearing_v1, _av1 = _setup_occupied_vri_cart(api)

    hearing_v3 = _schedule_ten_to_eleven(config, "CV-2026-0803", "IN_PERSON")
    created = validate_success(
        _attempt_assignment(
            api, hearing_v3["id"], dev["id"], delivery_mode="IN_PERSON", miles=12.0
        ),
        expected_status=201,
    )
    assert created["delivery_mode"] == "IN_PERSON", (
        f"expected IN_PERSON, got {created['delivery_mode']} on the accepted leg"
    )
    assert created["service_status"] == "PROPOSED", (
        f"expected PROPOSED, got {created['service_status']} — the identical window is "
        "free for a leg that needs no video cart"
    )


def test_declining_a_proposed_video_leg_leaves_its_hearing_untouched(api):
    """PRD §3.7: "Declining is the interpreter's own refusal, `PROPOSED → DECLINED`, and only the assignment's own interpreter may do it."
    PRD §3.7: "It carries a `reason_code` and records `cancel_reason_code` as `INTERPRETER_DECLINED`."
    PRD §3.7: "Because a proposed assignment never moved the hearing out of `SCHEDULED`, the hearing is left completely untouched — its `status` stays `SCHEDULED` and its `version` does not change — and because no claim exists yet, no ledger movement occurs."

    Design: Difficulty/resource_temporal_overlap/courthouse_vri_capacity_uses_closed_intervals_and_frees_on_decline
    """
    config, ana, _dev, hearing_v1, av1 = _setup_occupied_vri_cart(api)
    before = fixtures.read_hearing(hearing_v1["id"])

    declined = fixtures.decline_assignment(
        av1["id"], ana["id"], reason_code="INTERPRETER_DECLINED"
    )
    assert declined["service_status"] == "DECLINED", (
        f"expected DECLINED, got {declined['service_status']} after the interpreter "
        "refused the proposal"
    )
    assert declined["cancel_reason_code"] == "INTERPRETER_DECLINED", (
        f"expected INTERPRETER_DECLINED, got {declined['cancel_reason_code']} on the "
        "declined row"
    )

    after = fixtures.read_hearing(hearing_v1["id"])
    assert after["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {after['status']} — a proposal never covered it"
    )
    assert after["version"] == before["version"], (
        f"expected version {before['version']}, got {after['version']} — a decline "
        "leaves the hearing completely untouched"
    )
    assert fixtures.read_courthouse(config["courthouse"]["id"])[
        "encumbered_pay_cents"
    ] == 0, "expected 0 encumbered cents — nothing was ever confirmed"


def test_capacity_frees_on_decline_and_the_identical_video_request_then_succeeds(api):
    """PRD §3.6: "Count the assignments at the same courthouse whose `delivery_mode` is `VRI` and whose `service_status` is `PROPOSED`, `CONFIRMED`, or `CHECKED_IN`, keeping only those whose hearing window intersects the new hearing's window treating both windows as **closed** — an existing window intersects when its start is at or before the new window's end and the new window's start is at or before its end."
    PRD §3.6: "In-person and telephonic assignments never occupy video capacity, and terminal-service rows never occupy it."
    PRD §3.7: "Declining is the interpreter's own refusal, `PROPOSED → DECLINED`, and only the assignment's own interpreter may do it."
    PRD §2.9: "`encumbered_pay_cents` is the sum of `provisional_total_cents` over every pay claim whose `status` is `ENCUMBERED` and whose assignment's hearing sits at this courthouse."

    Design: Difficulty/resource_temporal_overlap/courthouse_vri_capacity_uses_closed_intervals_and_frees_on_decline
    """
    config, ana, dev, _hearing_v1, av1 = _setup_occupied_vri_cart(api)
    hearing_v2 = _schedule_ten_to_eleven(config, "CV-2026-0802", "VRI")

    validate_error(
        _attempt_assignment(
            api, hearing_v2["id"], dev["id"], delivery_mode="VRI", miles=0.0
        ),
        ApiErrorId.ERR_VRI_CAPACITY_EXCEEDED,
    )

    fixtures.decline_assignment(av1["id"], ana["id"], reason_code="INTERPRETER_DECLINED")

    created = validate_success(
        _attempt_assignment(
            api, hearing_v2["id"], dev["id"], delivery_mode="VRI", miles=0.0
        ),
        expected_status=201,
    )
    assert created["delivery_mode"] == "VRI", (
        f"expected VRI, got {created['delivery_mode']} on the re-issued request"
    )
    assert created["service_status"] == "PROPOSED", (
        f"expected PROPOSED, got {created['service_status']} — the declined row left "
        "the occupant set, so the identical booking now fits"
    )

    courthouse = fixtures.read_courthouse(config["courthouse"]["id"])
    assert courthouse["encumbered_pay_cents"] == 0, (
        f"expected 0, got {courthouse['encumbered_pay_cents']} — no claim reached "
        "ENCUMBERED because nothing was confirmed"
    )
