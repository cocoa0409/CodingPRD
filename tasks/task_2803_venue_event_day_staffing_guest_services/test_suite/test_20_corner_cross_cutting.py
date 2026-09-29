"""Cross-cutting layers: the version guard, the reliability window and the surcharge step."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ERR_STALE_EVENT_VERSION,
    ERR_VALIDATION_FAILED,
    activate_plan,
    advance_event,
    assert_cents,
    assert_fields,
    assert_slot_fill,
    attendance,
    change_member_status,
    create_assignment,
    create_event,
    create_member,
    create_plan,
    create_position_type,
    create_slot,
    err,
    ok,
    patch_event,
    read_assignment,
    read_event,
    read_member,
    read_plan,
    read_slot,
    set_clock,
)
from test_helpers.factories import plan_activate_payload

TICKET_TAKER = {
    "code": "TICKET_TAKER",
    "display_name": "Ticket Taker",
    "base_hourly_rate_cents": 2000,
    "attendance_ratio_per_1000": 0.8,
    "min_headcount": 1,
    "required_certifications": [],
}

SHIFT_WINDOWS = (
    ("Z110", "2026-09-12T12:00:00Z", "2026-09-12T13:00:00Z"),
    ("Z120", "2026-09-12T14:00:00Z", "2026-09-12T15:00:00Z"),
    ("Z130", "2026-09-12T16:00:00Z", "2026-09-12T17:00:00Z"),
    ("Z140", "2026-09-12T18:00:00Z", "2026-09-12T19:00:00Z"),
    ("Z150", "2026-09-12T20:00:00Z", "2026-09-12T21:00:00Z"),
)


def _fixture_event(client, name, **overrides):
    """The gate-day event these cross-cutting recipes hang their rows from."""
    return create_event(
        client,
        name=name,
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
        **overrides,
    )


def _absent(entity, *fields):
    """A field the PRD calls absent reads as missing or null, never as a value."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} must be absent, got {entity.get(field)!r}"
        )


def _five_block_day(client, member_name):
    """One worker booked onto five hour-long blocks an hour apart, event IN_PROGRESS.

    The hour-long gaps clear the 30-minute rest buffer, so the eligibility ladder
    admits all five placements, and every block needs exactly one head.
    """
    set_clock(client, "2026-09-12T11:00:00Z")
    event = create_event(
        client,
        name=f"Reliability Window Doubleheader ({member_name})",
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T11:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
    )
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])
    slots = [
        create_slot(
            client,
            plan["id"],
            family["id"],
            zone_code=zone,
            shift_start=start,
            shift_end=end,
            required_headcount_override=1,
        )
        for zone, start, end in SHIFT_WINDOWS
    ]
    activate_plan(client, plan["id"], event["id"])
    member = create_member(client, full_name=member_name, hourly_rate_cents=2000)
    assert_fields(
        member,
        status="ACTIVE",
        reliability_score=100,
        season_reliability_score=100,
        no_show_strikes=0,
        completed_assignment_count=0,
        in_backfill_pool=True,
    )
    _absent(member, "last_status_reason")
    assignments = [create_assignment(client, slot["id"], member["id"]) for slot in slots]
    for assignment in assignments:
        assert_fields(assignment, attendance_status="SCHEDULED", payout_status="PENDING")
    advance_event(client, event["id"], "IN_PROGRESS")
    return event, member, assignments


def _scores(client, member_id):
    """The pair of reliability figures, rolling first."""
    member = read_member(client, member_id)
    return member["reliability_score"], member["season_reliability_score"]


def test_occ_stale_expected_event_version_returns_412(client):
    """The one guarded write refuses a stale token, mutates nothing, and outranks state checks.

    "Exactly one write in this system takes a version guard. `POST /staffing-plans/{id}/activate` requires the non-optional field `expected_event_version`, carrying the `version` of the parent event as the client last observed it — the value returned by reading that event."

    "If `expected_event_version` does not equal the event's current `version`, the request is refused with `ERR_STALE_EVENT_VERSION` (412) and nothing at all mutates: the plan stays `DRAFT`, any incumbent plan stays `ACTIVE`, and the event's `version` does not move. A successful activation increments the event's `version` by exactly 1, which means a second activation replaying the same `expected_event_version` is refused. The version check sits after authentication, role authorization, request-schema validation and the resolution of path and body foreign keys, and before any check on the plan's or the event's own status."

    "A successful revision recomputes `attendance_tier`, then walks every staffing plan of the event whose status is `DRAFT` or `ACTIVE` and recomputes that plan's `basis_attendance` and `basis_attendance_tier`, then re-derives every non-closed shift block's `ratio_derived_headcount`, `required_headcount`, `slot_labor_cost_cents` and `status`, then recomputes the plan's four cost and headcount aggregates. It also re-derives `refund_budget_remaining_cents` and increments the event's `version` by 1."

    "Activation is the moment a paper exercise becomes a labour commitment, and it is the one write in this system guarded by the event version described in §2.7. A `StaffingCoordinator` activates a plan that is `DRAFT`; a plan in any other status is refused with `ERR_PLAN_STATE_INVALID`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_event_version_returns_412
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    event = _fixture_event(client, "Gate Rebuild Doubleheader")
    assert event["version"] == 1, "a newly registered event opens at version 1"

    family = create_position_type(client, **TICKET_TAKER)
    plan_a = create_plan(client, event["id"])
    plan_b = create_plan(client, event["id"])
    create_slot(
        client,
        plan_a["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    create_slot(
        client,
        plan_b["id"],
        family["id"],
        zone_code="Z200",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )

    # A revision burns the token the client is holding.
    revised = patch_event(client, event["id"], name="Gate Rebuild Doubleheader (Revised)")
    assert revised["version"] == 2, "a successful revision increments the version by 1"

    stale = client.activate_staffing_plan(
        plan_a["id"], plan_activate_payload(expected_event_version=1), COORDINATOR_HEADERS
    )
    assert stale.status_code == 412, "a stale version token answers 412"
    err(stale, ERR_STALE_EVENT_VERSION)
    assert read_event(client, event["id"])["version"] == 2, "the refusal moved no version"
    held = read_plan(client, plan_a["id"])
    assert_fields(held, status="DRAFT")
    _absent(held, "activated_at")

    # The current token is accepted, and spends itself.
    activated = activate_plan(client, plan_a["id"], event["id"], expected_event_version=2)
    assert_fields(activated, status="ACTIVE")
    settled = read_event(client, event["id"])
    assert_fields(settled, status="PLANNED", version=3)

    # Plan B replaying the very token plan A consumed is refused; the incumbent stands.
    replay = client.activate_staffing_plan(
        plan_b["id"], plan_activate_payload(expected_event_version=2), COORDINATOR_HEADERS
    )
    assert replay.status_code == 412
    err(replay, ERR_STALE_EVENT_VERSION)
    assert_fields(read_plan(client, plan_b["id"]), status="DRAFT")
    _absent(read_plan(client, plan_b["id"]), "activated_at")
    assert_fields(read_plan(client, plan_a["id"]), status="ACTIVE")
    assert read_event(client, event["id"])["version"] == 3

    # Plan A is now ACTIVE *and* holds a stale token: the guard is reported, not the state.
    guard_first = client.activate_staffing_plan(
        plan_a["id"], plan_activate_payload(expected_event_version=2), COORDINATOR_HEADERS
    )
    assert guard_first.status_code == 412, (
        "the version check sits before any check on the plan's own status"
    )
    body = err(guard_first, ERR_STALE_EVENT_VERSION)
    assert body["error_id"] == ERR_STALE_EVENT_VERSION
    assert read_event(client, event["id"])["version"] == 3, "still nothing mutated"
    assert_fields(read_plan(client, plan_a["id"]), status="ACTIVE")


def test_occ_version_token_round_trips_through_the_read_endpoint(client):
    """Reads never bump the token, a refused write never burns it, and each success moves it by one.

    "All resources except satisfaction responses additionally carry `updated_at` — an ISO 8601 UTC instant refreshed on every mutation of the resource — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation."

    "Exactly one write in this system takes a version guard. `POST /staffing-plans/{id}/activate` requires the non-optional field `expected_event_version`, carrying the `version` of the parent event as the client last observed it — the value returned by reading that event."

    "3. Request schema — required fields present, JSON types correct, enum values recognized, integers inside their declared ranges (a forecast attendance of at least 0, a requested unit count of at least 1, a satisfaction score from 1 through 5, a headcount override either absent or at least 1), and pagination inside its declared range (`ERR_VALIDATION_FAILED`)."

    "On the event side, activation advances `FORECAST → PLANNED` when the event was still `FORECAST`, and in every case increments the event's `version` by exactly 1 — the same mutation the version guard protects."

    "Advancing `PLANNED → IN_PROGRESS` requires that exactly one plan of the event stands in `ACTIVE`. That plan moves `ACTIVE → LOCKED`, which freezes the block numbers: from that point a revision of the event can no longer recompute any block's `required_headcount`, `ratio_derived_headcount` or `slot_labor_cost_cents`, because revising the event is itself refused with `ERR_EVENT_STATE_INVALID` from `IN_PROGRESS` onward."

    Design: Corner/cross_cutting_complexity_layers/occ_version_token_round_trips_through_the_read_endpoint
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    event = _fixture_event(client, "Token Round Trip Matinee")
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])
    create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )

    # Two consecutive reads serve the same token: reading is not a mutation.
    first = read_event(client, event["id"])
    second = read_event(client, event["id"])
    assert first["version"] == 1
    assert second["version"] == 1, "a read never increments the version"
    assert second["updated_at"] == first["updated_at"], "a read never refreshes updated_at"

    # A schema-refused revision mutates nothing, so it cannot burn the token either.
    refused = client.update_event(
        event["id"], {"expected_attendance": -1}, DIRECTOR_HEADERS
    )
    assert refused.status_code == 422
    err(refused, ERR_VALIDATION_FAILED)
    after_refusal = read_event(client, event["id"])
    assert_fields(after_refusal, version=1, status="FORECAST", expected_attendance=6000)
    assert after_refusal["updated_at"] == first["updated_at"]

    # The token the client has been holding all along is still current, so it is accepted.
    activated = activate_plan(client, plan["id"], event["id"], expected_event_version=1)
    assert_fields(activated, status="ACTIVE")
    after_activation = read_event(client, event["id"])
    assert_fields(after_activation, status="PLANNED", version=2)
    assert after_activation["version"] - after_refusal["version"] == 1, (
        "a successful activation increments the version by exactly 1"
    )

    started = advance_event(client, event["id"], "IN_PROGRESS")
    assert_fields(started, status="IN_PROGRESS", version=3)
    assert started["version"] - after_activation["version"] == 1, "never a jump of more than 1"
    assert_fields(read_plan(client, plan["id"]), status="LOCKED")
    assert read_event(client, event["id"])["version"] == 3


def test_probation_threshold_holds_at_exactly_sixty_five(client):
    """A rolling score landing exactly on 65 does not demote; the next no-show, at 45, does.

    "Two reliability figures are maintained for every worker, and they are computed from the same rule over different row sets. The input set is the worker's assignments whose `attendance_status` is either `COMPLETED` or `NO_SHOW`; rows in `SCHEDULED`, `CHECKED_IN`, `RELEASED` or `CANCELLED` contribute nothing, which is why releasing a worker from a shift never moves either figure while marking that same shift a no-show moves both. Qualifying rows are ordered by the shift block's `shift_start` descending, with the assignment's own `created_at` descending as the tie-break. For any set of rows the score starts at 100, subtracts 25 for each row in `NO_SHOW`, subtracts a further 8 for each row in `COMPLETED` whose `late_check_in` flag is set, adds 3 for each row in `COMPLETED`, and is then clamped into the range 0 through 100."

    "`reliability_score` applies that rule to the three most recent qualifying rows only, so older no-shows fall out of the window and stop hurting the worker. `season_reliability_score` applies the same rule to every qualifying row."

    "Whenever a recomputation triggered by a completion or a no-show leaves an `ACTIVE` worker's `reliability_score` below 65, the system moves that worker `ACTIVE → PROBATION`, sets `in_backfill_pool` to false, and records `last_status_reason` as `AUTO_PROBATION_RELIABILITY`."

    "The system stamps `check_in_at` from the current logical clock and freezes `late_check_in` at that moment: the flag is set when `check_in_at` falls strictly later than the block's `shift_start` plus a five-minute grace allowance, so a worker arriving exactly at the grace boundary is on time."

    "The system stamps `checked_out_at` from the current logical clock and sets `worked_minutes` to the whole minutes between `check_in_at` and `checked_out_at`, truncated toward zero."

    "The assignment moves `SCHEDULED → NO_SHOW`, its `payout_status` is driven `PENDING → VOIDED` and `total_payout_cents` is set to 0. The block's `filled_headcount` is decremented by 1 and its `status` re-derived, and a backfill request is opened against that block in `OPEN` with `triggering_assignment_id` pointing at the assignment that just failed. The worker's `no_show_strikes` is incremented by 1 and both reliability figures are recomputed."

    Design: Corner/cross_cutting_complexity_layers/probation_threshold_holds_at_exactly_sixty_five
    """
    event, member, assignments = _five_block_day(client, "Rowan Ashcroft")
    a1, a2, a3, a4, a5 = assignments

    # Row 1: one no-show. 100 - 25 = 75.
    marked = attendance(client, a1["id"], "NO_SHOW", at="2026-09-12T13:05:00Z")
    assert_fields(marked, attendance_status="NO_SHOW", payout_status="VOIDED")
    assert_cents(marked["total_payout_cents"], 0, "total_payout_cents")
    assert _scores(client, member["id"]) == (75, 75)
    assert_fields(read_member(client, member["id"]), status="ACTIVE", in_backfill_pool=True)

    # Row 2: a late completion. 100 - 25 - 8 + 3 = 70.
    checked_in = attendance(client, a2["id"], "CHECK_IN", at="2026-09-12T14:06:00Z")
    assert_fields(checked_in, attendance_status="CHECKED_IN", late_check_in=True)
    done = attendance(client, a2["id"], "CHECK_OUT", at="2026-09-12T15:00:00Z")
    assert_fields(done, attendance_status="COMPLETED", payout_status="ACCRUED", worked_minutes=54)
    assert_cents(done["base_pay_cents"], 1800, "base_pay_cents")
    assert _scores(client, member["id"]) == (70, 70)
    assert_fields(read_member(client, member["id"]), status="ACTIVE", in_backfill_pool=True)

    # Row 3: a second late completion. 100 - 25 - 16 + 6 = exactly 65 — the strict floor holds.
    assert_fields(
        attendance(client, a3["id"], "CHECK_IN", at="2026-09-12T16:06:00Z"),
        late_check_in=True,
    )
    assert_fields(
        attendance(client, a3["id"], "CHECK_OUT", at="2026-09-12T17:00:00Z"),
        attendance_status="COMPLETED",
        worked_minutes=54,
    )
    assert _scores(client, member["id"]) == (65, 65)
    at_the_floor = read_member(client, member["id"])
    assert_fields(at_the_floor, status="ACTIVE", in_backfill_pool=True)
    _absent(at_the_floor, "last_status_reason")

    # Row 4: the oldest no-show rolls out of the window, so the rolling figure sits at 65 again.
    attendance(client, a4["id"], "NO_SHOW", at="2026-09-12T19:05:00Z")
    assert _scores(client, member["id"]) == (65, 40)
    still_standing = read_member(client, member["id"])
    assert_fields(still_standing, status="ACTIVE", in_backfill_pool=True, no_show_strikes=2)
    _absent(still_standing, "last_status_reason")

    # Row 5: two no-shows and one late completion in the window — 45, strictly below the floor.
    attendance(client, a5["id"], "NO_SHOW", at="2026-09-12T21:05:00Z")
    assert _scores(client, member["id"]) == (45, 15)
    demoted = read_member(client, member["id"])
    assert_fields(
        demoted,
        status="PROBATION",
        in_backfill_pool=False,
        last_status_reason="AUTO_PROBATION_RELIABILITY",
        no_show_strikes=3,
        completed_assignment_count=2,
    )

    # The demotion cascade only reaches families requiring ELEVATOR_OPERATION; this one does not.
    statuses = [read_assignment(client, a["id"])["attendance_status"] for a in assignments]
    assert statuses == ["NO_SHOW", "COMPLETED", "COMPLETED", "NO_SHOW", "NO_SHOW"]
    assert_slot_fill(read_slot(client, a1["position_slot_id"]), filled=0, required=1, status="OPEN")
    assert_slot_fill(
        read_slot(client, a2["position_slot_id"]), filled=1, required=1, status="FILLED"
    )


def test_surcharge_cumulative_threshold_boundary_at_sixty_heads(client):
    """59 heads draw no accessibility surcharge; the sixtieth draws 350 basis points, and back again.

    "Optionally the coordinator supplies `required_headcount_override`, an operator figure that replaces the ratio result outright; when it is supplied it must be at least 1, and when it is absent the ratio result stands."

    "`required_headcount` is then the `required_headcount_override` when that field carries a value and `ratio_derived_headcount` otherwise; note that the `min_headcount` floor is applied to the ratio result only and never to an override. Alongside the headcount the system records `shift_minutes`, the whole minutes between `shift_start` and `shift_end`."

    "Costing a plan is a six-step pass over the plan's shift blocks whose `status` is not `CLOSED`, taken in `created_at` ascending order, and each step consumes the rounded output of the one before it. Step one prices each block on its own: `slot_labor_cost_cents` is the block's `required_headcount` multiplied by the family's `base_hourly_rate_cents` multiplied by the block's `shift_minutes` divided by 60, rounded half up to whole cents, one block at a time. Step two sums those already-rounded per-block figures into `base_labor_cost_cents`; the exact products are never summed. Step three sums the blocks' `required_headcount` values into `total_required_headcount`, independently of any money. Step four selects an accessibility surcharge rate from that plan-level headcount total and never from an individual block: a total of 300 heads or more draws 900 basis points, at least 150 but fewer than 300 draws 600 basis points, at least 60 but fewer than 150 draws 350 basis points, and anything below 60 draws nothing. Step five computes `accessibility_surcharge_cents` as `base_labor_cost_cents` multiplied by that basis-point rate divided by 10000, rounded half up to whole cents. Step six adds the two together into `projected_labor_cost_cents`; the surcharge never re-enters the headcount total or the surcharge-tier selection."

    "Retiming or resizing a block accepts a new `zone_code`, `shift_start`, `shift_end` or `required_headcount_override`, and is permitted only while the owning plan is `DRAFT` or `ACTIVE` — on a `LOCKED`, `SUPERSEDED` or `VOIDED` plan it is refused with `ERR_PLAN_STATE_INVALID`, and on a block already `CLOSED` it is refused with `ERR_SLOT_STATE_INVALID`. The revision recomputes `shift_minutes`, `ratio_derived_headcount`, `required_headcount` and `slot_labor_cost_cents`, re-derives the block's `status` from `filled_headcount` against the new `required_headcount` — so shrinking a block can flip it from `PARTIALLY_FILLED` straight to `FILLED` — and recomputes the owning plan's four aggregates."

    Design: Corner/cross_cutting_complexity_layers/surcharge_cumulative_threshold_boundary_at_sixty_heads
    """
    set_clock(client, "2026-09-12T10:00:00Z")
    event = _fixture_event(client, "Surcharge Boundary Doubleheader")
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])

    # One 360-minute block, 59 heads: 59 x 2000 x 360/60 = 708000 cents, one head short of the band.
    block = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T16:00:00Z",
        shift_end="2026-09-12T22:00:00Z",
        required_headcount_override=59,
    )
    assert_fields(block, required_headcount=59, shift_minutes=360)
    assert_cents(block["slot_labor_cost_cents"], 708000, "slot_labor_cost_cents")
    below = read_plan(client, plan["id"])
    assert_fields(below, status="DRAFT", total_required_headcount=59)
    assert_cents(below["base_labor_cost_cents"], 708000, "base_labor_cost_cents")
    assert_cents(below["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(below["projected_labor_cost_cents"], 708000, "projected_labor_cost_cents")

    # The sixtieth head lands on the band floor: 720000 x 350 / 10000 = 25200.
    resized = ok(
        client.update_position_slot(
            block["id"], {"required_headcount_override": 60}, COORDINATOR_HEADERS
        )
    )
    assert_fields(resized, required_headcount=60, shift_minutes=360)
    assert_cents(resized["slot_labor_cost_cents"], 720000, "slot_labor_cost_cents")
    at_the_band = read_plan(client, plan["id"])
    assert_fields(at_the_band, total_required_headcount=60)
    assert_cents(at_the_band["base_labor_cost_cents"], 720000, "base_labor_cost_cents")
    assert_cents(at_the_band["accessibility_surcharge_cents"], 25200, "accessibility_surcharge_cents")
    assert_cents(at_the_band["projected_labor_cost_cents"], 745200, "projected_labor_cost_cents")

    # Shrinking back below the floor drops the surcharge entirely — the band is not sticky.
    shrunk = ok(
        client.update_position_slot(
            block["id"], {"required_headcount_override": 59}, COORDINATOR_HEADERS
        )
    )
    assert_fields(shrunk, required_headcount=59)
    assert_cents(shrunk["slot_labor_cost_cents"], 708000, "slot_labor_cost_cents")
    back_below = read_plan(client, plan["id"])
    assert_fields(back_below, total_required_headcount=59)
    assert_cents(back_below["base_labor_cost_cents"], 708000, "base_labor_cost_cents")
    assert_cents(back_below["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(back_below["projected_labor_cost_cents"], 708000, "projected_labor_cost_cents")


def test_probation_reset_restores_the_backfill_pool(client):
    """Automatic probation never reverses itself: recovery to 81 still needs the explicit reinstatement.

    "Two reliability figures are maintained for every worker, and they are computed from the same rule over different row sets. The input set is the worker's assignments whose `attendance_status` is either `COMPLETED` or `NO_SHOW`; rows in `SCHEDULED`, `CHECKED_IN`, `RELEASED` or `CANCELLED` contribute nothing, which is why releasing a worker from a shift never moves either figure while marking that same shift a no-show moves both. Qualifying rows are ordered by the shift block's `shift_start` descending, with the assignment's own `created_at` descending as the tie-break. For any set of rows the score starts at 100, subtracts 25 for each row in `NO_SHOW`, subtracts a further 8 for each row in `COMPLETED` whose `late_check_in` flag is set, adds 3 for each row in `COMPLETED`, and is then clamped into the range 0 through 100."

    "`reliability_score` applies that rule to the three most recent qualifying rows only, so older no-shows fall out of the window and stop hurting the worker. `season_reliability_score` applies the same rule to every qualifying row."

    "Whenever a recomputation triggered by a completion or a no-show leaves an `ACTIVE` worker's `reliability_score` below 65, the system moves that worker `ACTIVE → PROBATION`, sets `in_backfill_pool` to false, and records `last_status_reason` as `AUTO_PROBATION_RELIABILITY`."

    "Workforce standing is never changed through that update path — `status` moves only through the dedicated standing action, which carries a `target_status` and a mandatory `reason`. Sending a `target_status` equal to the worker's current status is refused with `ERR_VALIDATION_FAILED`, and any standing change attempted on a worker already in `TERMINATED` is refused with `ERR_STAFF_MEMBER_NOT_ACTIVE`. Each successful change records the supplied `reason` in `last_status_reason` and sets `in_backfill_pool` to false when the worker becomes `SUSPENDED` or `TERMINATED` and to true when the worker becomes `ACTIVE`."

    "Reinstatement is deliberately asymmetric. Coming back from `SUSPENDED → ACTIVE` carries no reliability requirement at all and simply restores `in_backfill_pool` to true. Coming back from `PROBATION → ACTIVE` additionally requires that the worker's `reliability_score` has recovered to 65 or more; below that the reinstatement is refused."

    Design: Corner/cross_cutting_complexity_layers/probation_reset_restores_the_backfill_pool
    """
    event, member, assignments = _five_block_day(client, "Imani Bexley")
    a1, a2, a3, a4, a5 = assignments

    # Row 1: a late completion. 100 - 8 + 3 = 95.
    assert_fields(
        attendance(client, a1["id"], "CHECK_IN", at="2026-09-12T12:06:00Z"),
        attendance_status="CHECKED_IN",
        late_check_in=True,
    )
    assert_fields(
        attendance(client, a1["id"], "CHECK_OUT", at="2026-09-12T13:00:00Z"),
        attendance_status="COMPLETED",
        payout_status="ACCRUED",
        worked_minutes=54,
    )
    assert _scores(client, member["id"]) == (95, 95)

    # Row 2: a no-show. 100 - 25 - 8 + 3 = 70, still above the floor.
    attendance(client, a2["id"], "NO_SHOW", at="2026-09-12T15:05:00Z")
    assert _scores(client, member["id"]) == (70, 70)
    assert_fields(read_member(client, member["id"]), status="ACTIVE", in_backfill_pool=True)

    # Row 3: a second no-show. 100 - 50 - 8 + 3 = 45, and the automatic demotion fires.
    attendance(client, a3["id"], "NO_SHOW", at="2026-09-12T17:05:00Z")
    assert _scores(client, member["id"]) == (45, 45)
    assert_fields(
        read_member(client, member["id"]),
        status="PROBATION",
        in_backfill_pool=False,
        last_status_reason="AUTO_PROBATION_RELIABILITY",
        no_show_strikes=2,
    )

    # Row 4: a clean completion lifts the rolling figure to 53 — recovering, still under the floor.
    assert_fields(
        attendance(client, a4["id"], "CHECK_IN", at="2026-09-12T18:00:00Z"),
        attendance_status="CHECKED_IN",
        late_check_in=False,
    )
    fourth = attendance(client, a4["id"], "CHECK_OUT", at="2026-09-12T19:00:00Z")
    assert_fields(fourth, attendance_status="COMPLETED", worked_minutes=60)
    assert_cents(fourth["base_pay_cents"], 2000, "base_pay_cents")
    assert _scores(client, member["id"]) == (53, 48)
    assert_fields(read_member(client, member["id"]), status="PROBATION", in_backfill_pool=False)

    # Row 5: the oldest no-show rolls out and the rolling figure reaches 81 — no self-reversal.
    assert_fields(
        attendance(client, a5["id"], "CHECK_IN", at="2026-09-12T20:00:00Z"),
        late_check_in=False,
    )
    assert_fields(
        attendance(client, a5["id"], "CHECK_OUT", at="2026-09-12T21:00:00Z"),
        attendance_status="COMPLETED",
        worked_minutes=60,
    )
    assert _scores(client, member["id"]) == (81, 51)
    recovered = read_member(client, member["id"])
    assert_fields(
        recovered,
        status="PROBATION",
        in_backfill_pool=False,
        last_status_reason="AUTO_PROBATION_RELIABILITY",
        completed_assignment_count=3,
        no_show_strikes=2,
    )

    # Only the explicit standing action restores the pool, and 81 clears the 65 requirement.
    reinstated = change_member_status(
        client, member["id"], "ACTIVE", "Two clean shifts after the automatic probation"
    )
    assert_fields(
        reinstated,
        status="ACTIVE",
        in_backfill_pool=True,
        last_status_reason="Two clean shifts after the automatic probation",
        reliability_score=81,
        season_reliability_score=51,
    )
    assert read_event(client, event["id"])["status"] == "IN_PROGRESS"
