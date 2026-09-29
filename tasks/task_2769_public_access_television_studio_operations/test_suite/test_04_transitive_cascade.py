"""Cascades whose later links exist only because the earlier links fired."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import ADMIN_HEADERS, make_producer_headers


# ---------------------------------------------------------------------------
# Finalizing one major assessment reaches the slot's staffing status
# ---------------------------------------------------------------------------
def _damage_review_with_a_second_confirmed_reservation(client):
    """Build the four-level fixture and stop just before the finalize call.

    The volunteer P holds a `BASIC` competency in `STUDIO_FLOOR` so that the
    studio may be reserved, and the owning producer Q holds `LIVE`
    certification because only a live program may declare crew roles.
    """
    owner = fx.setup_live_certified_producer(
        client, legal_name="Grace Hopper", email="grace@patv.example"
    )
    volunteer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    channel = fx.create_channel(client, call_sign="PATV1")
    program = fx.setup_approved_program(
        client,
        owner["id"],
        title="Riverside Council Recap",
        runtime_seconds=1800,
        is_live=True,
        required_crew_roles=["CAMERA"],
    )
    slot = fx.book_slot(client, channel["id"], program["id"], "2026-08-20T18:00:00Z")
    assignment = fx.staff_slot(client, slot["id"], volunteer["id"], "CAMERA")

    resource = fx.create_resource(
        client,
        resource_code="STUDIO-A",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    _res, damaged = fx.setup_confirmed_reservation(
        client, volunteer["id"], resource,
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
    )
    spare = fx.request_reservation(
        client, volunteer["id"], resource["id"],
        start_at="2026-08-25T10:00:00Z", end_at="2026-08-25T12:00:00Z",
    )
    spare = fx.confirm_reservation(client, spare["id"])

    fx.set_clock(client, "2026-08-08T10:00:00Z")
    fx.checkout_reservation(client, damaged["id"], condition_notes="Pedestal head sound at handover")
    fx.set_clock(client, "2026-08-08T11:00:00Z")
    fx.return_damaged(
        client, damaged["id"], "MAJOR", 60000, damage_notes="Pedestal column bent"
    )
    assessment = fx.list_assessments_for(client, damaged["id"])[0]
    return {
        "owner": owner,
        "volunteer": volunteer,
        "channel": channel,
        "slot": slot,
        "assignment": assignment,
        "resource": resource,
        "damaged": damaged,
        "spare": spare,
        "assessment": assessment,
    }


def test_finalizing_a_major_assessment_settles_the_reservation_and_suspends_the_producer(client):
    """Links one to three: assessment, settlement, then membership suspension.

    PRD 3.7: "it converts `severity` into `suspension_points_assessed`: a
    `MINOR` incident is worth 1 point, a `MAJOR` one 2 points and a `TOTAL_LOSS`
    3 points, with one extra point added whenever the assessed repair reaches
    50000 cents."

    PRD 3.7: "The producer's `deposit_held_cents` falls by the reservation's
    `deposit_hold_cents`, their `deposit_forfeited_total_cents` rises by the
    forfeited amount, and the asset's `open_reservation_count` falls by 1. The
    producer's `suspension_points` rises by `suspension_points_assessed`."

    PRD 3.7: "When the producer is `ACTIVE` and the new `suspension_points` total
    reaches 3, the producer moves `ACTIVE → SUSPENDED` on the spot, and that
    transition has consequences of its own. Their `certification_level` collapses
    to `NONE`, because the derivation gates on membership status."

    PRD 3.1: "Because the derivation always reads the surviving enrollments,
    suspension is a suppression rather than an erasure: a suspended producer's
    level collapses to `NONE`, and reinstatement restores exactly the level the
    passed courses support."

    Design: Difficulty/transitive_cascade/finalized_major_assessment_cascades_four_levels_to_slot_staffing
    """
    world = _damage_review_with_a_second_confirmed_reservation(client)
    a.assert_producer_counters(
        fx.read_producer(client, world["volunteer"]["id"]), held=25924, suspension_points=0
    )

    finalized = fx.finalize_assessment(client, world["assessment"]["id"])

    assert finalized["status"] == "FINALIZED"
    a.assert_cents(finalized["assessed_repair_cents"], 60000, "assessed_repair_cents")
    assert finalized["suspension_points_assessed"] == 3

    settled = fx.read_reservation(client, world["damaged"]["id"])
    assert settled["status"] == "SETTLED"
    a.assert_cents(settled["late_fee_cents"], 0, "late_fee_cents")
    a.assert_cents(settled["assessed_repair_cents"], 60000, "assessed_repair_cents")
    a.assert_cents(settled["deposit_forfeited_cents"], 12962, "deposit_forfeited_cents")
    a.assert_cents(settled["deposit_refunded_cents"], 0, "deposit_refunded_cents")
    a.assert_cents(settled["uncovered_liability_cents"], 47038, "uncovered_liability_cents")

    suspended = fx.read_producer(client, world["volunteer"]["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["certification_level"] == "NONE"
    assert sorted(suspended["competency_codes"]) == ["EDIT_SUITE", "STUDIO_FLOOR"]
    a.assert_producer_counters(suspended, suspension_points=3)


def test_the_suspension_cancels_the_other_reservation_and_releases_the_crew_commitment(client):
    """Link four fans out to a reservation and to a crew assignment at once.

    PRD 3.7: "Every reservation of theirs whose status is `REQUESTED` or
    `CONFIRMED` moves to `CANCELLED` with `cancellation_reason` recorded as
    `PRODUCER_SUSPENDED`; each formerly `CONFIRMED` one releases its hold,
    setting `deposit_refunded_cents` to the full `deposit_hold_cents` and
    `deposit_forfeited_cents` to 0, and lowers that asset's
    `open_reservation_count` by 1."

    PRD 3.7: "Every crew assignment where they are the `volunteer_producer_id`
    whose status is `OFFERED` or `CONFIRMED`, and whose slot is still
    `SCHEDULED`, moves to `RELEASED` with `release_reason` recorded as
    `VOLUNTEER_SUSPENDED`."

    Design: Difficulty/transitive_cascade/finalized_major_assessment_cascades_four_levels_to_slot_staffing
    """
    world = _damage_review_with_a_second_confirmed_reservation(client)

    fx.finalize_assessment(client, world["assessment"]["id"])

    cancelled = fx.read_reservation(client, world["spare"]["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "PRODUCER_SUSPENDED"
    a.assert_cents(cancelled["deposit_refunded_cents"], 12962, "deposit_refunded_cents")
    a.assert_cents(cancelled["deposit_forfeited_cents"], 0, "deposit_forfeited_cents")

    released = fx.read_crew(client, world["assignment"]["id"])
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "VOLUNTEER_SUSPENDED"
    assert released["credited_hours_tenths"] == 0

    volunteer = fx.read_producer(client, world["volunteer"]["id"])
    a.assert_producer_counters(
        volunteer, held=0, forfeited_total=12962, commitments=0
    )
    assert fx.read_resource(client, world["resource"]["id"])["open_reservation_count"] == 0


def test_the_cascade_stops_at_slot_staffing_and_leaves_the_airtime_ledger_alone(client):
    """Link five drops the slot to UNDERSTAFFED without unscheduling it.

    PRD 3.5: "From `CONFIRMED` it does the same and additionally lowers the
    volunteer's `confirmed_crew_commitments` by 1; releasing a confirmed
    volunteer is exactly how a slot falls back from `READY` to `UNDERSTAFFED`."

    PRD 2.9: "A channel's `scheduled_seconds` is the sum of `occupied_seconds`
    over its `SCHEDULED` slots and its `aired_seconds` is the same sum over its
    `AIRED` slots."

    Design: Difficulty/transitive_cascade/finalized_major_assessment_cascades_four_levels_to_slot_staffing
    """
    world = _damage_review_with_a_second_confirmed_reservation(client)
    before = fx.read_slot(client, world["slot"]["id"])
    assert before["staffing_status"] == "READY"

    fx.finalize_assessment(client, world["assessment"]["id"])

    after = fx.read_slot(client, world["slot"]["id"])
    assert after["staffing_status"] == "UNDERSTAFFED"
    assert after["status"] == "SCHEDULED"
    a.assert_channel_ledger(fx.read_channel(client, world["channel"]["id"]), 1920, 0)

    untouched = fx.read_producer(client, world["owner"]["id"])
    assert untouched["status"] == "ACTIVE"
    a.assert_producer_counters(untouched, held=0, suspension_points=0)


# ---------------------------------------------------------------------------
# Withdrawing an approved episode reaches the series hold and the volunteer
# ---------------------------------------------------------------------------
def _series_hold_slot_with_a_confirmed_volunteer(client):
    """An episodic slot booked against a hold plan and fully staffed."""
    owner = fx.setup_live_certified_producer(
        client, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    volunteer = fx.setup_active_producer(
        client, legal_name="Vera Rubin", email="vera@patv.example"
    )
    series = fx.setup_active_series_with_hold_plan(
        client, owner["id"], slots=4, title="Riverside Weekly", cadence="WEEKLY",
        first_air_date="2026-08-20T00:00:00Z",
    )
    channel = fx.create_channel(client, call_sign="PATV1")
    program = fx.setup_approved_program(
        client,
        owner["id"],
        series_id=series["id"],
        episode_number=1,
        title="Riverside Weekly 001",
        runtime_seconds=1800,
        is_live=True,
        required_crew_roles=["CAMERA"],
    )
    slot = fx.book_slot(
        client, channel["id"], program["id"], "2026-08-20T18:00:00Z", series_id=series["id"]
    )
    assignment = fx.staff_slot(client, slot["id"], volunteer["id"], "CAMERA")
    return owner, volunteer, series, channel, program, slot, assignment


def test_withdrawing_an_approved_episode_withdraws_its_slot_and_releases_the_airtime(client):
    """Links one and two: the program, then the slot and the channel ledger.

    PRD 3.3: "Second, every playback slot carrying this program whose status is
    `SCHEDULED` moves to `WITHDRAWN`; each such withdrawal lowers that channel's
    `scheduled_seconds` by the slot's `occupied_seconds`, and where the slot's
    `booking_type` is `SERIES_HOLD` it raises the owning series'
    `remaining_hold_slots` by 1 **without** raising `missed_windows`."

    PRD 3.4: "Its `booking_type` becomes `SERIES_HOLD` when a `series_id` was
    supplied, in which case that series' `remaining_hold_slots` falls by 1;
    otherwise `booking_type` is `FIRST_COME`."

    Design: Difficulty/transitive_cascade/program_withdrawal_cascades_to_series_hold_and_volunteer_commitment
    """
    owner, _volunteer, series, channel, program, slot, _assignment = (
        _series_hold_slot_with_a_confirmed_volunteer(client)
    )
    assert slot["booking_type"] == "SERIES_HOLD"
    assert slot["occupied_seconds"] == 1920
    assert fx.read_series(client, series["id"])["remaining_hold_slots"] == 3
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 1920, 0)

    withdrawn = a.data_of(
        client.withdraw_program(
            program["id"], f.program_withdraw_payload(), make_producer_headers(owner["id"])
        )
    )

    assert withdrawn["review_status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason"] == "Producer pulled the episode for re-editing"
    assert fx.read_slot(client, slot["id"])["status"] == "WITHDRAWN"
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 0, 0)
    assert fx.read_series(client, series["id"])["remaining_hold_slots"] == 4


def test_an_editorial_withdrawal_restores_the_hold_slot_without_a_missed_window(client):
    """The series is not penalised for an editorial outcome.

    PRD 3.2: "A series-hold slot withdrawn because the underlying program was
    withdrawn or rejected returns its hold slot **without** touching
    `missed_windows`, because the series is not penalised for an editorial
    outcome."

    PRD 3.2: "Once `missed_windows` reaches 2 the series lapses on the spot: the
    `ACTIVE → LAPSED` transition fires as a system effect of that cancellation,
    `remaining_hold_slots` is forced to 0 so that no further priority booking is
    possible while the series is dormant"

    Design: Difficulty/transitive_cascade/program_withdrawal_cascades_to_series_hold_and_volunteer_commitment
    """
    owner, _volunteer, series, _channel, program, _slot, _assignment = (
        _series_hold_slot_with_a_confirmed_volunteer(client)
    )

    a.data_of(
        client.withdraw_program(
            program["id"], f.program_withdraw_payload(), make_producer_headers(owner["id"])
        )
    )

    after = fx.read_series(client, series["id"])
    assert after["missed_windows"] == 0
    assert after["status"] == "ACTIVE"
    assert after["remaining_hold_slots"] == 4
    assert after["hold_plan_slots_granted"] == 4


def test_withdrawal_releases_the_volunteer_without_crediting_any_airtime(client):
    """Links three and four: the crew row, then the volunteer's counters.

    PRD 3.3: "Third, every crew assignment on a slot withdrawn by the second
    effect whose status is `OFFERED` or `CONFIRMED` moves to `RELEASED` with
    `release_reason` recorded as `PROGRAM_WITHDRAWN`, and each such slot's
    `staffing_status` is re-derived."

    PRD 2.9: "A producer's `volunteer_hours_tenths` is the sum of
    `credited_hours_tenths` over that producer's `COMPLETED` crew assignments, in
    tenths of an hour as a whole number."

    Design: Difficulty/transitive_cascade/program_withdrawal_cascades_to_series_hold_and_volunteer_commitment
    """
    owner, volunteer, _series, channel, program, slot, assignment = (
        _series_hold_slot_with_a_confirmed_volunteer(client)
    )
    assert fx.read_slot(client, slot["id"])["staffing_status"] == "READY"
    a.assert_producer_counters(fx.read_producer(client, volunteer["id"]), commitments=1)

    a.data_of(
        client.withdraw_program(
            program["id"], f.program_withdraw_payload(), make_producer_headers(owner["id"])
        )
    )

    released = fx.read_crew(client, assignment["id"])
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "PROGRAM_WITHDRAWN"
    assert released["credited_hours_tenths"] == 0

    a.assert_producer_counters(
        fx.read_producer(client, volunteer["id"]), commitments=0, volunteer_tenths=0
    )
    assert fx.read_slot(client, slot["id"])["staffing_status"] == "UNDERSTAFFED"
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 0, 0)
    assets = a.data_of(client.list_archive_assets(ADMIN_HEADERS, {"program_id": program["id"]}))
    assert assets == []
