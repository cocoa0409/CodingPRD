"""Endpoint-surface breadth: round trips, the one deletion and the batch actions."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    DIRECTOR_USER_ID,
    ERR_CERTIFICATION_MISSING,
    ERR_PAYOUT_PHASE_INVALID,
    ERR_PLAN_STATE_INVALID,
    ERR_POSITION_SLOT_NOT_FOUND,
    ERR_REFUND_STATE_INVALID,
    ERR_ROLE_NOT_PERMITTED,
    ERR_STAFF_MEMBER_NOT_FOUND,
    SUPERVISOR_HEADERS,
    SUPERVISOR_USER_ID,
    activate_plan,
    advance_event,
    assert_cents,
    assert_common_fields,
    assert_fields,
    assert_instant,
    assert_ledger,
    assert_payout_totals,
    assert_ratio,
    assert_slot_fill,
    attendance,
    create_assignment,
    create_bid,
    create_certification,
    create_event,
    create_issue,
    create_member,
    create_plan,
    create_position_type,
    create_satisfaction_response,
    create_slot,
    created,
    decide_refund,
    err,
    file_refund,
    ids_of,
    make_staff_member_headers,
    make_supervisor_headers,
    ok,
    page,
    read_assignment,
    read_bid,
    read_event,
    read_plan,
    read_slot,
    run_bid_award,
    run_payout,
    set_clock,
)
from test_helpers.factories import (
    payout_run_payload,
    refund_decision_payload,
    revoke_payload,
    satisfaction_response_payload,
    shift_bid_payload,
    staff_assignment_payload,
)

ABSENT_ID = "00000000-0000-0000-0000-0000000000ff"

TICKET_TAKER = {
    "code": "TICKET_TAKER",
    "display_name": "Ticket Taker",
    "base_hourly_rate_cents": 2000,
    "attendance_ratio_per_1000": 0.8,
    "min_headcount": 1,
    "required_certifications": [],
}

ELEVATOR_OPERATOR = {
    "code": "ELEVATOR_OPERATOR",
    "display_name": "Elevator Operator",
    "base_hourly_rate_cents": 2400,
    "attendance_ratio_per_1000": 0.2,
    "min_headcount": 1,
    "required_certifications": ["ELEVATOR_OPERATION"],
}


def _fixture_event(client, name, **overrides):
    """The gate-day event every endpoint recipe here hangs its rows from."""
    return create_event(
        client,
        name=name,
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
        **overrides,
    )


def _deleted(response):
    """The one deletion in the surface answers 204 and carries nothing but an empty data object."""
    assert response.status_code == 204, (
        f"expected 204 from the deletion, got {response.status_code}: {response.text}"
    )
    if response.text.strip():
        assert response.json().get("data") in ({}, None, []), (
            f"the deletion must answer with an empty data object, got {response.text}"
        )


def _quantized(actual, expected, label=""):
    """A two-decimal figure must arrive at exactly the half-up quantized value."""
    assert float(actual) == float(expected), (
        f"{label}: expected exactly {expected}, got {actual!r}"
    )


def _absent(entity, *fields):
    """A field the PRD calls absent reads as missing or null, never as a value."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} must be absent, got {entity.get(field)!r}"
        )


def test_a_position_family_round_trips_through_create_read_retune_and_list(client):
    """One family answers 201, reads back, retunes to version 2, and lists by code.

    "A family is identified by its `code`, which is one of `USHER`, `TICKET_TAKER`, `ELEVATOR_OPERATOR` or `GUEST_SERVICES_REP`, and carries a `display_name` used on the staffing sheet, a `base_hourly_rate_cents` straight-time rate that must not be negative, an `attendance_ratio_per_1000` headcount ratio that must be strictly greater than zero, a `min_headcount` floor that must not be negative, and a `required_certifications` array drawn from `ACCESSIBILITY_SERVICES`, `EVACUATION_PROCEDURES`, `CODE_OF_CONDUCT` and `ELEVATOR_OPERATION`."

    "Two booleans complete the family: `is_tip_eligible`, false unless supplied, states whether assignments on the family share the event gratuity pool, and `is_contracted_position`, also false unless supplied, states whether the family is staffed by contracted workers."

    "A family may later be retuned in `display_name`, `base_hourly_rate_cents`, `attendance_ratio_per_1000`, `min_headcount`, `required_certifications`, `is_tip_eligible` or `is_contracted_position`, and retuning it changes no shift block, plan or assignment field in that same request — existing blocks are repriced only when the event or the block itself is next revised, which is exactly what makes the frozen numbers of a locked plan observable."

    "All resources except satisfaction responses additionally carry `updated_at` — an ISO 8601 UTC instant refreshed on every mutation of the resource — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation."

    "Three list endpoints do name a different ordering: the event list is returned with the latest `event_date` first, the position-family list is returned by `code` ascending, and the worker list is returned by `seniority_date` ascending with `created_at` ascending as the tie-break."

    "Families may be listed filtered by `code` and `is_tip_eligible`."

    Design: Corner/endpoints/position_type_crud_round_trip
    """
    set_clock(client, "2026-09-01T09:00:00Z")

    usher = create_position_type(
        client,
        code="USHER",
        display_name="Usher",
        base_hourly_rate_cents=2200,
        attendance_ratio_per_1000=1.5,
        min_headcount=4,
        required_certifications=["EVACUATION_PROCEDURES"],
    )
    assert_common_fields(usher)
    assert_fields(
        usher,
        code="USHER",
        display_name="Usher",
        min_headcount=4,
        required_certifications=["EVACUATION_PROCEDURES"],
        is_tip_eligible=False,
        is_contracted_position=False,
        version=1,
    )
    assert_cents(usher["base_hourly_rate_cents"], 2200, "base_hourly_rate_cents")
    assert_ratio(usher["attendance_ratio_per_1000"], 1.5, "attendance_ratio_per_1000")

    # the read surface is open to the director as well as to the coordinator who filed it
    as_director = ok(client.get_position_type(usher["id"], DIRECTOR_HEADERS))
    assert_fields(as_director, id=usher["id"], min_headcount=4, version=1)
    assert_cents(as_director["base_hourly_rate_cents"], 2200, "base_hourly_rate_cents")

    set_clock(client, "2026-09-01T09:30:00Z")
    retuned = ok(
        client.update_position_type(
            usher["id"],
            {"base_hourly_rate_cents": 2600, "min_headcount": 6, "is_tip_eligible": True},
            COORDINATOR_HEADERS,
        )
    )
    assert_fields(
        retuned,
        id=usher["id"],
        code="USHER",
        display_name="Usher",
        min_headcount=6,
        required_certifications=["EVACUATION_PROCEDURES"],
        is_tip_eligible=True,
        is_contracted_position=False,
        version=2,
    )
    assert_cents(retuned["base_hourly_rate_cents"], 2600, "base_hourly_rate_cents")
    assert_ratio(retuned["attendance_ratio_per_1000"], 1.5, "attendance_ratio_per_1000")
    assert_instant(retuned["created_at"], usher["created_at"], "created_at")
    assert retuned["updated_at"] != usher["updated_at"], (
        "updated_at must be refreshed by the retune"
    )

    create_position_type(client, **TICKET_TAKER)
    create_position_type(client, **ELEVATOR_OPERATOR)

    families, meta = page(client.list_position_types(COORDINATOR_HEADERS))
    assert meta["total_count"] == 3, f"expected three families, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert [family["code"] for family in families] == [
        "ELEVATOR_OPERATOR",
        "TICKET_TAKER",
        "USHER",
    ]

    only_ushers, usher_meta = page(
        client.list_position_types(SUPERVISOR_HEADERS, {"code": "USHER"})
    )
    assert usher_meta["total_count"] == 1, f"expected one usher family, got {usher_meta}"
    assert ids_of(only_ushers) == [usher["id"]]


def test_the_one_deletion_answers_204_and_the_plan_reprices_without_the_block(client):
    """Removing a block answers 204, drops the row, and shrinks the plan's four aggregates.

    "The single deletion in the surface answers with 204 and an empty data object."

    "Removing a block entirely is permitted only while the owning plan is `DRAFT`, is refused with `ERR_PLAN_STATE_INVALID` otherwise, and is refused with `ERR_SLOT_STATE_INVALID` when any non-terminal bid or assignment still references the block; a successful removal recomputes the plan's four aggregates."

    "Step one prices each block on its own: `slot_labor_cost_cents` is the block's `required_headcount` multiplied by the family's `base_hourly_rate_cents` multiplied by the block's `shift_minutes` divided by 60, rounded half up to whole cents, one block at a time."

    "Step two sums those already-rounded per-block figures into `base_labor_cost_cents`; the exact products are never summed."

    "Step four selects an accessibility surcharge rate from that plan-level headcount total and never from an individual block: a total of 300 heads or more draws 900 basis points, at least 150 but fewer than 300 draws 600 basis points, at least 60 but fewer than 150 draws 350 basis points, and anything below 60 draws nothing."

    "Blocks may be listed filtered by `plan_id`, `position_type_id`, `status` and `zone_code`."

    Design: Corner/endpoints/position_slot_delete_returns_204_and_row_disappears
    """
    set_clock(client, "2026-09-01T09:00:00Z")
    event = _fixture_event(client, "Slot Delete Fixture")
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])

    kept = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="GATE_A",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
    )
    # 6000 / 1000 * 0.8 * 1.00 = 4.8000, raised to 5 heads over 245 minutes
    assert_fields(kept, ratio_derived_headcount=5, required_headcount=5, shift_minutes=245)
    assert_cents(kept["slot_labor_cost_cents"], 40833, "slot_labor_cost_cents")

    doomed = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="TOWER",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    assert_fields(doomed, ratio_derived_headcount=5, required_headcount=2, shift_minutes=245)
    assert_cents(doomed["slot_labor_cost_cents"], 16333, "slot_labor_cost_cents")

    before = read_plan(client, plan["id"])
    assert_fields(before, total_required_headcount=7)
    assert_cents(before["base_labor_cost_cents"], 57166, "base_labor_cost_cents")
    assert_cents(before["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(before["projected_labor_cost_cents"], 57166, "projected_labor_cost_cents")

    _deleted(client.delete_position_slot(doomed["id"], COORDINATOR_HEADERS))

    err(client.get_position_slot(doomed["id"], COORDINATOR_HEADERS), ERR_POSITION_SLOT_NOT_FOUND)

    survivors, survivor_meta = page(
        client.list_position_slots(COORDINATOR_HEADERS, {"plan_id": plan["id"]})
    )
    assert survivor_meta["total_count"] == 1, f"expected one block left, got {survivor_meta}"
    assert ids_of(survivors) == [kept["id"]]

    after = read_plan(client, plan["id"])
    assert_fields(after, total_required_headcount=5)
    assert_cents(after["base_labor_cost_cents"], 40833, "base_labor_cost_cents")
    assert_cents(after["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(after["projected_labor_cost_cents"], 40833, "projected_labor_cost_cents")

    # once the plan leaves DRAFT the deletion is refused and the block stays readable
    activate_plan(client, plan["id"], event["id"])
    response = client.delete_position_slot(kept["id"], COORDINATOR_HEADERS)
    err(response, ERR_PLAN_STATE_INVALID)

    still_there = read_slot(client, kept["id"])
    assert_fields(still_there, id=kept["id"], required_headcount=5)
    assert_cents(still_there["slot_labor_cost_cents"], 40833, "slot_labor_cost_cents")


def test_one_batch_sweep_awards_waitlists_and_declines_in_the_same_pass(client):
    """Four bids on a two-head block come back awarded, waitlisted and declined in one run.

    "Every bid on the block that is `SUBMITTED` or `WAITLISTED` is considered."

    "Eligible bids are ranked by the bidding worker's `reliability_score` descending, then the worker's `seniority_date` ascending so that the earlier hire wins, then the bid's own `created_at` ascending."

    "Ranked bids are awarded in that order until the block's remaining capacity — `required_headcount` less `filled_headcount` — is exhausted, each award producing the same assignment and the same block bookkeeping as a manual award, but with `decision_reason` recorded as `AUTO_AWARD_RERUN` when the bid was promoted from `WAITLISTED`."

    "`rank_score` is stamped on every bid the run ranked, carrying the snapshot of that worker's `reliability_score` at run time."

    "Bids that survive the eligibility ladder but find no capacity left move `SUBMITTED → WAITLISTED` with `decision_reason` recorded as `CAPACITY_EXHAUSTED`; no assignment is created for them and the block's `filled_headcount` does not move."

    "Bids that fail the ladder move `SUBMITTED → DECLINED_BY_SYSTEM`, and `decision_reason` records the *first* failing check in the fixed order `MEMBER_NOT_ACTIVE`, then `CERTIFICATION_MISSING`, then `REST_CONFLICT`."

    "A declined bid does not abort the sweep: the run continues with the remaining bids and returns 200 regardless, listing every bid it touched in ranking order — a run that awards nothing at all is still a success, not an error."

    "The worker must hold a credential whose `status` is `VALID` for every code listed in the block's position family `required_certifications`, or the attempt is refused with `ERR_CERTIFICATION_MISSING`."

    "A successful manual award moves the bid `SUBMITTED → AWARDED`, records `decision_reason` as `MANUAL_AWARD`, creates an assignment whose `source` is `BID_AWARD` and whose `shift_bid_id` points back at the awarded bid, opening in `attendance_status` `SCHEDULED` and `payout_status` `PENDING`, and increments the block's `filled_headcount` by 1 before re-deriving its `status`."

    Design: Corner/endpoints/run_bid_award_batch_mixes_award_waitlist_and_decline
    """
    set_clock(client, "2026-09-01T10:00:00Z")
    event = _fixture_event(client, "Bid Award Batch Fixture")
    family = create_position_type(
        client, **dict(TICKET_TAKER, required_certifications=["CODE_OF_CONDUCT"])
    )
    plan = create_plan(client, event["id"])
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="GATE_A",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    activate_plan(client, plan["id"], event["id"])

    m1 = create_member(
        client, full_name="M1 Senior", seniority_date="2018-01-01T00:00:00Z", hourly_rate_cents=2000
    )
    m2 = create_member(
        client, full_name="M2 Middle", seniority_date="2019-01-01T00:00:00Z", hourly_rate_cents=2000
    )
    m3 = create_member(
        client, full_name="M3 Junior", seniority_date="2020-01-01T00:00:00Z", hourly_rate_cents=2000
    )
    m4 = create_member(
        client,
        full_name="M4 Uncertified",
        seniority_date="2021-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    for member in (m1, m2, m3):
        create_certification(client, member["id"], "CODE_OF_CONDUCT")

    # filed youngest first, so only the seniority tie-break can produce the ranking
    bid4 = create_bid(client, m4["id"], slot["id"])
    bid3 = create_bid(client, m3["id"], slot["id"])
    bid2 = create_bid(client, m2["id"], slot["id"])
    bid1 = create_bid(client, m1["id"], slot["id"])

    touched = run_bid_award(client, slot["id"])
    assert isinstance(touched, list), f"the batch pass must answer with a list, got {touched!r}"
    assert len(touched) == 4, f"every touched bid must be listed, got {len(touched)}"
    assert set(ids_of(touched)) == {bid1["id"], bid2["id"], bid3["id"], bid4["id"]}
    ranked = [bid["id"] for bid in touched if bid["id"] != bid4["id"]]
    assert ranked == [bid1["id"], bid2["id"], bid3["id"]], (
        f"ranked bids must be listed senior-first, got {ranked}"
    )

    awarded_first = read_bid(client, bid1["id"])
    assert_fields(awarded_first, status="AWARDED")
    assert awarded_first["rank_score"] == 100, (
        f"rank_score must snapshot the reliability score, got {awarded_first['rank_score']!r}"
    )
    awarded_second = read_bid(client, bid2["id"])
    assert_fields(awarded_second, status="AWARDED")
    assert awarded_second["rank_score"] == 100

    waitlisted = read_bid(client, bid3["id"])
    assert_fields(waitlisted, status="WAITLISTED", decision_reason="CAPACITY_EXHAUSTED")

    declined = read_bid(client, bid4["id"])
    assert_fields(declined, status="DECLINED_BY_SYSTEM", decision_reason="CERTIFICATION_MISSING")

    assert_slot_fill(read_slot(client, slot["id"]), filled=2, required=2, status="FILLED")

    placements, placement_meta = page(
        client.list_staff_assignments(COORDINATOR_HEADERS, {"position_slot_id": slot["id"]})
    )
    assert placement_meta["total_count"] == 2, f"expected two placements, got {placement_meta}"
    assert {row["staff_member_id"] for row in placements} == {m1["id"], m2["id"]}
    assert {row["shift_bid_id"] for row in placements} == {bid1["id"], bid2["id"]}
    for row in placements:
        assert_fields(
            row, source="BID_AWARD", attendance_status="SCHEDULED", payout_status="PENDING"
        )

    for empty_handed in (m3, m4):
        _, none_meta = page(
            client.list_staff_assignments(
                COORDINATOR_HEADERS, {"staff_member_id": empty_handed["id"]}
            )
        )
        assert none_meta["total_count"] == 0, (
            f"no assignment may exist for {empty_handed['full_name']}, got {none_meta}"
        )


def test_the_payroll_run_settles_the_worked_row_and_steps_over_the_voided_one(client):
    """A released row is excluded from every phase while the completed row is paid.

    "The `GRATUITY_ALLOCATION` phase distributes the event's tip pool; it demands that the event's `status` be `CLOSED` and that at least one gratuity-eligible assignment still sit at `payout_status` `ACCRUED`, failing which it is refused with `ERR_PAYOUT_PHASE_INVALID`."

    "Gratuity eligibility is a conjunction of four conditions, and a row that misses any one of them is simply passed over rather than rejected."

    "The assignment's `payout_status` must be `ACCRUED`; the position family behind the assignment's shift block must have `is_tip_eligible` true; that same family must have `is_contracted_position` true; and the worker filling the assignment must have `employment_type` `CONTRACTED`."

    "Releasing a worker from a shift is the deliberate counterpart and is far quieter. The assignment moves `SCHEDULED → RELEASED`, its `payout_status` is driven to `VOIDED` and `total_payout_cents` is set to 0, and the block's `filled_headcount` is decremented and its `status` re-derived, restoring the invariant that `filled_headcount` equals the count of assignments in `SCHEDULED`, `CHECKED_IN` or `COMPLETED`."

    "The system stamps `checked_out_at` from the current logical clock and sets `worked_minutes` to the whole minutes between `check_in_at` and `checked_out_at`, truncated toward zero."

    "The rate used is the **worker's** own `hourly_rate_cents`, never the position family's `base_hourly_rate_cents`."

    "The payroll phase afterwards moves both `ACCRUED` rows — those that were never gratuity-eligible, whose `gratuity_cents` stays 0 and whose `total_payout_cents` keeps the value frozen at accrual — and `GRATUITY_ALLOCATED` rows to `PAID`, while `VOIDED` rows are skipped entirely and excluded from every phase."

    "Each run answers with the assignments it touched, listed in exactly the order the allocation ranked them."

    Design: Corner/endpoints/payout_run_payroll_skips_voided_rows
    """
    set_clock(client, "2026-09-01T10:00:00Z")
    event = _fixture_event(client, "Payroll Skip Fixture", gratuity_pool_cents=50000)
    family = create_position_type(
        client, **dict(TICKET_TAKER, is_tip_eligible=False, is_contracted_position=False)
    )
    plan = create_plan(client, event["id"])
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="GATE_A",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T21:00:00Z",
        required_headcount_override=2,
    )
    activate_plan(client, plan["id"], event["id"])

    worker = create_member(
        client, full_name="M1 Worker", seniority_date="2018-01-01T00:00:00Z", hourly_rate_cents=2000
    )
    stood_down = create_member(
        client,
        full_name="M2 Released",
        seniority_date="2019-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    worked = create_assignment(client, slot["id"], worker["id"])
    released = create_assignment(client, slot["id"], stood_down["id"])
    advance_event(client, event["id"], "IN_PROGRESS")

    attendance(client, worked["id"], "CHECK_IN", at="2026-09-12T18:00:00Z")
    stood_down_row = attendance(client, released["id"], "RELEASE")
    assert_fields(stood_down_row, attendance_status="RELEASED", payout_status="VOIDED")
    assert_cents(stood_down_row["total_payout_cents"], 0, "total_payout_cents")
    assert_slot_fill(read_slot(client, slot["id"]), filled=1, required=2, status="PARTIALLY_FILLED")

    completed = attendance(client, worked["id"], "CHECK_OUT", at="2026-09-12T21:00:00Z")
    assert_fields(completed, attendance_status="COMPLETED", payout_status="ACCRUED", worked_minutes=180)
    assert_payout_totals(completed, base=6000, gratuity=0, total=6000)

    # the tip run needs a closed event, whatever the pool holds
    err(
        client.event_payout_run(
            event["id"], payout_run_payload("GRATUITY_ALLOCATION"), DIRECTOR_HEADERS
        ),
        ERR_PAYOUT_PHASE_INVALID,
    )

    advance_event(client, event["id"], "CLOSED")

    # and once closed it still has nothing eligible to hand out: the family is not tip eligible
    err(
        client.event_payout_run(
            event["id"], payout_run_payload("GRATUITY_ALLOCATION"), DIRECTOR_HEADERS
        ),
        ERR_PAYOUT_PHASE_INVALID,
    )

    settled = run_payout(client, event["id"], "PAYROLL")
    assert isinstance(settled, list), f"the payout run must answer with a list, got {settled!r}"
    assert ids_of(settled) == [worked["id"]], (
        f"payroll must touch only the accrued row, got {ids_of(settled)}"
    )

    paid = read_assignment(client, worked["id"])
    assert_fields(paid, attendance_status="COMPLETED", payout_status="PAID", worked_minutes=180)
    assert_payout_totals(paid, base=6000, gratuity=0, total=6000)

    skipped = read_assignment(client, released["id"])
    assert_fields(skipped, attendance_status="RELEASED", payout_status="VOIDED")
    assert_cents(skipped["total_payout_cents"], 0, "total_payout_cents")

    closed_event = read_event(client, event["id"])
    assert_cents(closed_event["gratuity_allocated_cents"], 0, "gratuity_allocated_cents")


def test_revoking_a_credential_bites_the_next_placement_and_not_the_standing_one(client):
    """A revoked credential reads REVOKED, leaves the standing shift alone and blocks the next.

    "A credential's `status` is never stored as sent: it reads `REVOKED` whenever `revoked_at` carries a value, otherwise `EXPIRED` whenever the current logical clock is strictly after `expires_on`, and otherwise `VALID`."

    "A coordinator may revoke a credential with a `reason`, which stamps `revoked_at` with the current logical clock and drives `status` to `REVOKED`. Revocation is forward-looking: no existing assignment or bid is retro-cancelled, and only later eligibility checks change their answer."

    "Credentials may be listed filtered by `staff_member_id`, `cert_type` and `status`, and a worker's own credentials may be read as a sub-resource of that worker with the same `status` filter."

    "The worker must hold a credential whose `status` is `VALID` for every code listed in the block's position family `required_certifications`, or the attempt is refused with `ERR_CERTIFICATION_MISSING`."

    "A coordinator may also bypass the bid queue entirely and assign a worker to a block directly, naming the `position_slot_id` and the `staff_member_id`."

    Design: Corner/endpoints/certification_revoke_action_flips_status_to_revoked
    """
    set_clock(client, "2026-09-01T10:00:00Z")
    event = _fixture_event(client, "Revoke Fixture")
    family = create_position_type(client, **ELEVATOR_OPERATOR)
    plan = create_plan(client, event["id"])
    standing = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T20:00:00Z",
        required_headcount_override=2,
    )
    later = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z200",
        shift_start="2026-09-12T21:00:00Z",
        shift_end="2026-09-12T23:00:00Z",
        required_headcount_override=2,
    )
    activate_plan(client, plan["id"], event["id"])

    operator = create_member(
        client,
        full_name="Ada Certified",
        seniority_date="2018-01-01T00:00:00Z",
        hourly_rate_cents=2400,
    )
    credential = create_certification(client, operator["id"], "ELEVATOR_OPERATION")
    assert_fields(credential, status="VALID")
    _absent(credential, "revoked_at")

    placement = create_assignment(client, standing["id"], operator["id"])
    assert_fields(placement, attendance_status="SCHEDULED", payout_status="PENDING")

    set_clock(client, "2026-09-01T11:30:00Z")
    revoked = ok(
        client.revoke_certification(
            credential["id"], revoke_payload("Failed the annual lift refresher"), COORDINATOR_HEADERS
        )
    )
    assert_fields(revoked, id=credential["id"], status="REVOKED")
    assert_instant(revoked["revoked_at"], "2026-09-01T11:30:00.000Z", "revoked_at")

    # forward-looking: the shift the worker already holds is untouched
    untouched = read_assignment(client, placement["id"])
    assert_fields(untouched, attendance_status="SCHEDULED", payout_status="PENDING")
    assert_slot_fill(read_slot(client, standing["id"]), filled=1, required=2, status="PARTIALLY_FILLED")

    err(
        client.create_staff_assignment(
            staff_assignment_payload(later["id"], operator["id"]), COORDINATOR_HEADERS
        ),
        ERR_CERTIFICATION_MISSING,
    )
    assert_slot_fill(read_slot(client, later["id"]), filled=0, required=2, status="OPEN")

    _, valid_meta = page(
        client.list_staff_member_certifications(
            operator["id"], COORDINATOR_HEADERS, {"status": "VALID"}
        )
    )
    assert valid_meta["total_count"] == 0, f"no credential may read VALID now, got {valid_meta}"

    revoked_rows, revoked_meta = page(
        client.list_staff_member_certifications(
            operator["id"], COORDINATOR_HEADERS, {"status": "REVOKED"}
        )
    )
    assert revoked_meta["total_count"] == 1, f"expected one revoked credential, got {revoked_meta}"
    assert ids_of(revoked_rows) == [credential["id"]]


def test_a_bid_resolves_its_worker_before_its_block_and_then_files_clean(client):
    """Both bid links are checked in declaration order before a clean filing answers 201.

    "Foreign keys carried in a request body are resolved after every path identifier, and among themselves in the order the fields are declared on the target entity."

    "A bid names the `staff_member_id` of the bidding worker and the `position_slot_id` of the block being bid on."

    "A bid opens in `SUBMITTED` with `submitted_at` stamped from the current logical clock, `rank_score` absent and `decision_reason` absent."

    "Bids may be listed filtered by `staff_member_id`, `position_slot_id` and `status`."

    Design: Corner/endpoints/shift_bid_link_requires_both_member_and_slot
    """
    set_clock(client, "2026-09-01T10:00:00Z")
    event = _fixture_event(client, "Bid Link Fixture")
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="GATE_A",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    activate_plan(client, plan["id"], event["id"])
    bidder = create_member(
        client,
        full_name="Ada Bidder",
        seniority_date="2018-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )

    err(
        client.create_shift_bid(
            shift_bid_payload(ABSENT_ID, slot["id"]), COORDINATOR_HEADERS
        ),
        ERR_STAFF_MEMBER_NOT_FOUND,
    )
    err(
        client.create_shift_bid(
            shift_bid_payload(bidder["id"], ABSENT_ID), COORDINATOR_HEADERS
        ),
        ERR_POSITION_SLOT_NOT_FOUND,
    )
    # both missing: the worker is declared first, so the worker is reported
    err(
        client.create_shift_bid(
            shift_bid_payload(ABSENT_ID, ABSENT_ID), COORDINATOR_HEADERS
        ),
        ERR_STAFF_MEMBER_NOT_FOUND,
    )

    filed = created(
        client.create_shift_bid(
            shift_bid_payload(bidder["id"], slot["id"]), COORDINATOR_HEADERS
        )
    )
    assert_common_fields(filed)
    assert_fields(
        filed, staff_member_id=bidder["id"], position_slot_id=slot["id"], status="SUBMITTED"
    )
    assert_instant(filed["submitted_at"], "2026-09-01T10:00:00.000Z", "submitted_at")
    _absent(filed, "rank_score", "decision_reason")

    by_member, member_meta = page(
        client.list_shift_bids(COORDINATOR_HEADERS, {"staff_member_id": bidder["id"]})
    )
    assert member_meta["total_count"] == 1, f"expected one bid for the worker, got {member_meta}"
    assert ids_of(by_member) == [filed["id"]]

    by_slot, slot_meta = page(
        client.list_shift_bids(COORDINATOR_HEADERS, {"position_slot_id": slot["id"]})
    )
    assert slot_meta["total_count"] == 1, f"expected one bid on the block, got {slot_meta}"
    assert ids_of(by_slot) == [filed["id"]]

    _, all_meta = page(client.list_shift_bids(COORDINATOR_HEADERS))
    assert all_meta["total_count"] == 1, f"the refused filings must have stored nothing: {all_meta}"


def test_the_sentiment_summary_is_a_pure_read_over_every_response_filed(client):
    """Three responses from two zones drive the headline figures, and reading changes nothing.

    "A `GuestServicesSupervisor` or a `GuestExperienceDirector` files a response against an `event_id`, naming the `zone_code` it came from, a `score` between 1 and 5 inclusive, and an optional free-text `comment`; `submitted_by_user_id` is recorded from `X-User-ID`."

    "A response is the one resource in this system that carries no `updated_at` and no `version` at all — only its `id` and its `created_at` — because it can never be edited, withdrawn or corrected once filed."

    "Responses may be listed for an event, optionally narrowed to a single `zone_code`."

    "The event's sentiment summary is derived on demand from every response ever filed against the event, with none excluded."

    "When there is at least one, `average_score` is the sum of the scores divided by the count, quantized to two decimal places by rounding half up — eight responses summing to 35 give exactly 4.375, which is reported as 4.38 and not 4.37 — and `promoter_share_bp` is the count of responses scoring 4 or better, multiplied by 10000, divided by the total count, and rounded half up to a whole number of basis points."

    "A `zone_breakdown` accompanies the headline figures, one entry per distinct `zone_code` carrying that zone's `zone_code`, its own `response_count` and its own `average_score`, ordered by `zone_code` ascending."

    "Two issue counters complete the picture: `resolved_issue_count` is the number of the event's guest issues whose `status` is `RESOLVED` or `CLOSED`, and `sla_breached_issue_count` is the number whose `sla_breached` flag is true."

    Design: Corner/endpoints/satisfaction_summary_computed_read_zone_filter
    """
    set_clock(client, "2026-09-01T10:00:00Z")
    event = _fixture_event(client, "Satisfaction Summary Fixture")

    praised = create_satisfaction_response(
        client, event["id"], "Z_UPPER", 5, comment="The ushers were quick"
    )
    assert_common_fields(praised, versioned=False)
    assert_fields(praised, submitted_by_user_id=SUPERVISOR_USER_ID, comment="The ushers were quick")

    # the director may file too, and a response filed without a comment simply has none
    from_director = created(
        client.create_satisfaction_response(
            satisfaction_response_payload(event["id"], "Z_UPPER", 2), DIRECTOR_HEADERS
        )
    )
    assert_fields(from_director, submitted_by_user_id=DIRECTOR_USER_ID, score=2)
    _absent(from_director, "comment", "updated_at", "version")

    create_satisfaction_response(client, event["id"], "Z_LOWER", 4)

    summary = ok(client.get_satisfaction_summary(event["id"], DIRECTOR_HEADERS))
    assert_fields(summary, response_count=3, resolved_issue_count=0, sla_breached_issue_count=0)
    # (5 + 2 + 4) / 3 = 3.6666..., and two of the three scored 4 or better
    _quantized(summary["average_score"], 3.67, "average_score")
    assert summary["promoter_share_bp"] == 6667, (
        f"promoter_share_bp must be 6667, got {summary['promoter_share_bp']!r}"
    )
    breakdown = summary["zone_breakdown"]
    assert [entry["zone_code"] for entry in breakdown] == ["Z_LOWER", "Z_UPPER"]
    assert_fields(breakdown[0], zone_code="Z_LOWER", response_count=1)
    _quantized(breakdown[0]["average_score"], 4.00, "Z_LOWER average_score")
    assert_fields(breakdown[1], zone_code="Z_UPPER", response_count=2)
    _quantized(breakdown[1]["average_score"], 3.50, "Z_UPPER average_score")

    # the responses list narrows to one zone; the summary never excludes anything
    upper, upper_meta = page(
        client.list_event_satisfaction_responses(
            event["id"], SUPERVISOR_HEADERS, {"zone_code": "Z_UPPER"}
        )
    )
    assert upper_meta["total_count"] == 2, f"expected two upper-tier responses, got {upper_meta}"
    assert set(ids_of(upper)) == {praised["id"], from_director["id"]}

    # a computed read persists nothing whatever
    again = ok(client.get_satisfaction_summary(event["id"], DIRECTOR_HEADERS))
    assert again == summary, f"the summary read must be pure, got {again} then {summary}"
    _, all_meta = page(
        client.list_event_satisfaction_responses(event["id"], SUPERVISOR_HEADERS)
    )
    assert all_meta["total_count"] == 3, f"the reads must not have filed anything: {all_meta}"


def test_a_reversal_needs_a_live_authorization_and_a_director_to_file_it(client):
    """VOID is refused to a supervisor, refused on a pending ask, and restores the ledger.

    "A supervisor first files the ask, supplying `refund_requested_cents`; the system stores that amount, records `refund_requested_by_user_id` from `X-User-ID`, and moves `refund_status` `NONE → PENDING`. No money moves and no ledger figure changes at this point."

    "A `GuestExperienceDirector` owns the event itself: it creates events, drives the event lifecycle, sets the guest-recovery budget and the gratuity pool, runs payouts, holds the larger refund cap, is the only role that may reverse an authorized refund, and is the only role that may resolve an issue that has been escalated."

    "The issue's refund sub-state must admit the decision: an approval requires `refund_status` to be `NONE`, `PENDING` or `PARTIALLY_APPROVED`, and a reversal requires it to be `APPROVED` or `PARTIALLY_APPROVED`; anything else is refused with `ERR_REFUND_STATE_INVALID`."

    "First a role cap: 5000 cents for a `GuestServicesSupervisor` and 50000 cents for a `GuestExperienceDirector`."

    "The amount authorized is then the smallest of three figures: the `refund_requested_cents` asked for, the effective cap, and that available budget."

    "A reversal — available only to a `GuestExperienceDirector` — moves `refund_status` to `VOIDED` and resets `refund_approved_cents` to 0, and because the ledger is always re-derived by rescanning the event's issues, `refund_approved_total_cents` and `refund_budget_remaining_cents` return to exactly their pre-authorization values."

    Design: Corner/endpoints/refund_decision_void_is_conditional_on_a_live_authorization
    """
    set_clock(client, "2026-09-01T10:00:00Z")
    event = _fixture_event(client, "Void Conditional Fixture", refund_budget_total_cents=100000)
    issue = create_issue(client, event["id"], category="OTHER", severity="MEDIUM")

    asked = file_refund(client, issue["id"], 2000)
    assert_fields(
        asked, refund_status="PENDING", refund_requested_by_user_id=SUPERVISOR_USER_ID
    )
    assert_cents(asked["refund_requested_cents"], 2000, "refund_requested_cents")
    assert_ledger(read_event(client, event["id"]), approved=0, remaining=100000, total=100000)

    # a supervisor may never reverse, whatever the sub-state
    err(
        client.file_refund_decision(
            issue["id"], refund_decision_payload("VOID"), make_supervisor_headers("u-supervisor-2")
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    # and the director may not reverse an authorization that does not exist yet
    err(
        client.file_refund_decision(
            issue["id"], refund_decision_payload("VOID"), DIRECTOR_HEADERS
        ),
        ERR_REFUND_STATE_INVALID,
    )

    approved = decide_refund(client, issue["id"], "APPROVE", DIRECTOR_HEADERS)
    assert_fields(
        approved, refund_status="APPROVED", refund_decided_by_user_id=DIRECTOR_USER_ID
    )
    assert_cents(approved["refund_approved_cents"], 2000, "refund_approved_cents")
    assert_ledger(read_event(client, event["id"]), approved=2000, remaining=98000, total=100000)

    voided = decide_refund(client, issue["id"], "VOID", DIRECTOR_HEADERS)
    assert_fields(voided, refund_status="VOIDED")
    assert_cents(voided["refund_approved_cents"], 0, "refund_approved_cents")
    assert_cents(voided["refund_requested_cents"], 2000, "refund_requested_cents")
    assert_ledger(read_event(client, event["id"]), approved=0, remaining=100000, total=100000)


def test_every_role_may_drive_the_clock_and_nobody_needs_to_before_the_default(client):
    """The clock starts at its documented default, all four roles may move it, and moving it writes nothing.

    "Before any client sets it, the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."

    "An administrative test-driving capability sets the clock to a supplied `current_utc` instant and is available to all four roles."

    "Moving the clock writes no business row: it only changes what subsequent reads and writes compute."

    "In particular, a credential's `status` and a guest issue's `sla_breached` flag are re-derived on their next read rather than being refreshed by the clock move itself."

    "A credential's `status` is never stored as sent: it reads `REVOKED` whenever `revoked_at` carries a value, otherwise `EXPIRED` whenever the current logical clock is strictly after `expires_on`, and otherwise `VALID`."

    Design: Corner/endpoints/clock_endpoint_available_to_every_role
    """
    # no clock call has been made, so the default instant is what these two rows are read against
    probe = _fixture_event(client, "Default Clock Probe")
    assert_fields(probe, version=1)
    worker = create_member(client, full_name="Clock Probe Worker")
    on_the_boundary = create_certification(
        client,
        worker["id"],
        "CODE_OF_CONDUCT",
        issued_on="2026-01-01T00:00:00Z",
        expires_on="2026-08-01T00:00:00Z",
    )
    a_second_short = create_certification(
        client,
        worker["id"],
        "EVACUATION_PROCEDURES",
        issued_on="2026-01-01T00:00:00Z",
        expires_on="2026-07-31T23:59:59Z",
    )
    # the comparison is strict, so a credential lapsing exactly at the default instant still reads VALID
    assert_fields(on_the_boundary, status="VALID")
    assert_fields(a_second_short, status="EXPIRED")

    def credential_status(cert_id):
        return ok(client.get_certification(cert_id, COORDINATOR_HEADERS))["status"]

    # the director moves it forward past the boundary credential's expiry
    ok(client.set_clock("2026-09-05T05:00:00Z", DIRECTOR_HEADERS))
    assert credential_status(on_the_boundary["id"]) == "EXPIRED"

    # the coordinator moves it back before both expiries
    ok(client.set_clock("2026-07-01T00:00:00Z", COORDINATOR_HEADERS))
    assert credential_status(on_the_boundary["id"]) == "VALID"
    assert credential_status(a_second_short["id"]) == "VALID"

    # the supervisor moves it forward again
    ok(client.set_clock("2026-09-05T07:00:00Z", SUPERVISOR_HEADERS))
    assert credential_status(on_the_boundary["id"]) == "EXPIRED"
    assert credential_status(a_second_short["id"]) == "EXPIRED"

    # and so may a worker, who takes it back to a date before either credential lapsed
    ok(client.set_clock("2026-06-01T00:00:00Z", make_staff_member_headers(worker["id"])))
    assert credential_status(on_the_boundary["id"]) == "VALID"
    assert credential_status(a_second_short["id"]) == "VALID"

    # four clock moves later, no business row has been touched
    unmoved = read_event(client, probe["id"])
    assert_fields(unmoved, id=probe["id"], version=1, status="FORECAST")
    assert_instant(unmoved["created_at"], probe["created_at"], "created_at")
    assert_instant(unmoved["updated_at"], probe["updated_at"], "updated_at")
    still_valid = ok(client.get_certification(on_the_boundary["id"], COORDINATOR_HEADERS))
    assert_fields(still_valid, version=on_the_boundary["version"])
    _absent(still_valid, "revoked_at")
