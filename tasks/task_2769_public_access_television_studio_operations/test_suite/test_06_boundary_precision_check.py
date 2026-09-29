"""Inclusive thresholds and two-decimal rounding examined one unit either side."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN_HEADERS


# ---------------------------------------------------------------------------
# The repair escalation threshold of 50000 cents
# ---------------------------------------------------------------------------
def _two_minor_incidents_either_side_of_the_escalation_threshold(client):
    """Two producers damage the same studio, one at 49999 and one at 50000.

    Both estimates sit far below the studio's replacement value, so the
    assessed repair is the filed estimate in both cases and nothing is clamped.
    """
    below_producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    at_producer = fx.setup_basic_certified_producer(
        client, score=84, legal_name="Grace Hopper", email="grace@patv.example"
    )
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
    _res, below = fx.setup_confirmed_reservation(
        client, below_producer["id"], resource,
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
    )
    at_threshold = fx.request_reservation(
        client, at_producer["id"], resource["id"],
        start_at="2026-08-09T10:00:00Z", end_at="2026-08-09T12:00:00Z",
    )
    at_threshold = fx.confirm_reservation(client, at_threshold["id"])

    fx.set_clock(client, "2026-08-08T10:00:00Z")
    fx.checkout_reservation(client, below["id"], condition_notes="Handover clean")
    fx.set_clock(client, "2026-08-08T11:30:00Z")
    fx.return_damaged(
        client, below["id"], "MINOR", 49999, damage_notes="Scratched monitor bezel"
    )
    fx.set_clock(client, "2026-08-09T10:00:00Z")
    fx.checkout_reservation(client, at_threshold["id"], condition_notes="Handover clean")
    fx.set_clock(client, "2026-08-09T11:30:00Z")
    fx.return_damaged(
        client, at_threshold["id"], "MINOR", 50000, damage_notes="Cracked monitor bezel"
    )
    return {
        "below_producer": below_producer,
        "at_producer": at_producer,
        "resource": resource,
        "below": below,
        "at_threshold": at_threshold,
        "below_assessment": fx.list_assessments_for(client, below["id"])[0],
        "at_assessment": fx.list_assessments_for(client, at_threshold["id"])[0],
    }


def test_one_cent_below_the_escalation_threshold_stays_at_the_minor_base_point(client):
    """49999 cents on a minor incident is worth the base point only.

    PRD 3.7: "it converts `severity` into `suspension_points_assessed`: a
    `MINOR` incident is worth 1 point, a `MAJOR` one 2 points and a `TOTAL_LOSS`
    3 points, with one extra point added whenever the assessed repair reaches
    50000 cents."

    PRD 3.7: "An estimate of 49999 cents on a minor incident therefore assesses
    1 point, while 50000 cents on the same incident assesses 2; a total loss
    estimated at 1200000 cents against a replacement value of 900000 is assessed
    at 900000 cents and 4 points."

    Design: Difficulty/boundary_precision_check/repair_escalation_threshold_exact_boundary_adds_one_point
    """
    world = _two_minor_incidents_either_side_of_the_escalation_threshold(client)

    finalized = fx.finalize_assessment(client, world["below_assessment"]["id"])

    a.assert_cents(finalized["assessed_repair_cents"], 49999, "assessed_repair_cents")
    assert finalized["suspension_points_assessed"] == 1
    below_producer = fx.read_producer(client, world["below_producer"]["id"])
    a.assert_producer_counters(below_producer, suspension_points=1)
    assert below_producer["status"] == "ACTIVE"
    assert below_producer["certification_level"] == "BASIC"

    settled = fx.read_reservation(client, world["below"]["id"])
    a.assert_cents(settled["late_fee_cents"], 0, "late_fee_cents")
    a.assert_cents(settled["deposit_forfeited_cents"], 12962, "deposit_forfeited_cents")
    a.assert_cents(settled["deposit_refunded_cents"], 0, "deposit_refunded_cents")
    a.assert_cents(settled["uncovered_liability_cents"], 37037, "uncovered_liability_cents")


def test_the_escalation_threshold_itself_adds_the_extra_suspension_point(client):
    """50000 cents reaches the threshold, so the boundary is inclusive.

    PRD 3.7: "Step six sets `uncovered_liability_cents` to the total charges less
    `deposit_hold_cents`, floored at 0."

    PRD 2.9: "A producer's `suspension_points` is the running penalty total
    contributed by `FINALIZED` damage assessments, less any credit granted at
    reinstatement."

    Design: Difficulty/boundary_precision_check/repair_escalation_threshold_exact_boundary_adds_one_point
    """
    world = _two_minor_incidents_either_side_of_the_escalation_threshold(client)
    fx.finalize_assessment(client, world["below_assessment"]["id"])

    finalized = fx.finalize_assessment(client, world["at_assessment"]["id"])

    a.assert_cents(finalized["assessed_repair_cents"], 50000, "assessed_repair_cents")
    assert finalized["suspension_points_assessed"] == 2
    at_producer = fx.read_producer(client, world["at_producer"]["id"])
    a.assert_producer_counters(at_producer, suspension_points=2)
    assert at_producer["status"] == "ACTIVE"
    assert at_producer["certification_level"] == "BASIC"

    settled = fx.read_reservation(client, world["at_threshold"]["id"])
    a.assert_cents(settled["late_fee_cents"], 0, "late_fee_cents")
    a.assert_cents(settled["deposit_forfeited_cents"], 12962, "deposit_forfeited_cents")
    a.assert_cents(settled["deposit_refunded_cents"], 0, "deposit_refunded_cents")
    a.assert_cents(settled["uncovered_liability_cents"], 37038, "uncovered_liability_cents")
    assert fx.read_resource(client, world["resource"]["id"])["open_reservation_count"] == 0


# ---------------------------------------------------------------------------
# The household norm of 1000 and the two-decimal impact index
# ---------------------------------------------------------------------------
def _three_unstaffed_slots_on_one_evening(client):
    """Three back-to-back 1920-second slots that need no crew at all."""
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    channel = fx.create_channel(client, call_sign="PATV1")
    slots = []
    for title, start_at in (
        ("Reach Study A", "2026-08-20T18:00:00Z"),
        ("Reach Study B", "2026-08-20T18:35:00Z"),
        ("Reach Study C", "2026-08-20T19:10:00Z"),
    ):
        program = fx.setup_approved_program(
            client, producer["id"], title=title, runtime_seconds=1800,
            is_live=False, required_crew_roles=[],
        )
        slots.append(fx.book_slot(client, channel["id"], program["id"], start_at))
    return producer, channel, slots


def _asset_for(client, slot_id):
    return a.data_of(client.list_archive_assets(ADMIN_HEADERS, {"source_slot_id": slot_id}))[0]


def test_reach_one_household_below_the_norm_scores_to_two_decimal_places(client):
    """999 households give 49.95, not 49.9 and not a binary float artefact.

    PRD 3.9: "The reach component is `measured_households` divided by 1000, or 1
    if that quotient exceeds 1."

    PRD 3.9: "The index is 100 multiplied by the weighted sum of the three
    components, with the reach component weighted 0.5, the demand component 0.3
    and the volunteer component 0.2, and the result rounded half up to two
    decimal places and emitted as a JSON number."

    PRD 3.4: "`staffing_status` is initialised to `NOT_REQUIRED` when the frozen
    `required_crew_roles` list is empty, and to `UNDERSTAFFED` otherwise."

    Design: Difficulty/boundary_precision_check/reach_component_clip_at_household_norm_boundary_on_air
    """
    _producer, _channel, slots = _three_unstaffed_slots_on_one_evening(client)
    assert slots[0]["staffing_status"] == "NOT_REQUIRED"

    fx.set_clock(client, "2026-08-20T18:00:00Z")
    aired = fx.air_slot(client, slots[0]["id"], 999)

    assert aired["status"] == "AIRED"
    assert aired["measured_households"] == 999
    a.assert_instant_equals(aired["aired_at"], "2026-08-20T18:00:00Z", "aired_at")

    asset = _asset_for(client, slots[0]["id"])
    assert asset["impact_variant"] == "PROVISIONAL"
    a.assert_index_equals(asset["community_impact_index"], 49.95)
    assert asset["on_demand_views"] == 0
    assert asset["volunteer_hours_tenths"] == 0
    assert asset["on_demand_status"] == "PENDING"


def test_reach_saturates_at_the_household_norm_and_exceeding_it_adds_nothing(client):
    """1000 households give exactly 50.00 and 1001 give the same clipped score.

    PRD 3.9: "**The community impact index** blends three normalised components,
    each capped at its own ceiling and clipped at 1."

    PRD 3.4: "On the channel's airtime ledger, `scheduled_seconds` falls by the
    slot's `occupied_seconds` and `aired_seconds` rises by the same figure, so the
    two counters together always account for every booked second exactly once."

    Design: Difficulty/boundary_precision_check/reach_component_clip_at_household_norm_boundary_on_air
    """
    _producer, channel, slots = _three_unstaffed_slots_on_one_evening(client)

    fx.set_clock(client, "2026-08-20T18:00:00Z")
    fx.air_slot(client, slots[0]["id"], 999)
    fx.set_clock(client, "2026-08-20T18:35:00Z")
    fx.air_slot(client, slots[1]["id"], 1000)
    fx.set_clock(client, "2026-08-20T19:10:00Z")
    fx.air_slot(client, slots[2]["id"], 1001)

    at_norm = _asset_for(client, slots[1]["id"])
    above_norm = _asset_for(client, slots[2]["id"])
    a.assert_index_equals(at_norm["community_impact_index"], 50.00)
    a.assert_index_equals(above_norm["community_impact_index"], 50.00)
    assert above_norm["measured_households"] == 1001
    assert at_norm["impact_variant"] == "PROVISIONAL"
    assert above_norm["impact_variant"] == "PROVISIONAL"

    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 0, 5760)
