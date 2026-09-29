"""Two rules broken at once: the higher-priority refusal must be the one heard."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import FACILITIES_HEADERS, make_producer_headers


# ---------------------------------------------------------------------------
# Asset availability (409) outranks the producer's deposit ceiling (402)
# ---------------------------------------------------------------------------
def _ceiling_loaded_producer_on_an_asset_in_maintenance(client):
    """One confirmed 420000-cent hold, a twin request, and the asset off-line."""
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    resource = fx.create_resource(
        client,
        resource_code="CAM-RIG",
        resource_class="FIELD_CAMERA_KIT",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=5,
        turnaround_minutes=0,
        base_deposit_cents=400000,
        replacement_value_cents=900000,
    )
    first = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
    )
    twin = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
    )
    first = fx.confirm_reservation(client, first["id"])
    a.assert_cents(first["deposit_hold_cents"], 420000, "deposit_hold_cents")
    fx.set_resource_status(
        client, resource["id"], "MAINTENANCE", status_reason="Annual service window"
    )
    return producer, resource, first, twin


def test_an_asset_in_maintenance_masks_the_deposit_ceiling_on_confirmation(client):
    """The state band is heard even though the fiscal band is also breached.

    PRD 3.6: "Five conditions gate `REQUESTED → CONFIRMED`, and their relative
    order matters: the asset's status must be `AVAILABLE`, otherwise
    `ERR_RESOURCE_NOT_AVAILABLE` (409); the producer must be `ACTIVE`, otherwise
    `ERR_PRODUCER_NOT_ACTIVE` (409); the asset's `required_competency_code` must
    appear in the producer's `competency_codes`, otherwise
    `ERR_COMPETENCY_NOT_HELD` (422); the asset must have room for the interval,
    otherwise `ERR_RESOURCE_OVERBOOKED` (409); and the producer's aggregate
    deposit exposure must stay within its ceiling, otherwise
    `ERR_DEPOSIT_LIMIT_EXCEEDED` (402)."

    PRD 3.6: "The asset-state check is the highest of the five and the deposit
    ceiling is the lowest, so an asset in `MAINTENANCE` belonging to a producer
    who is also at their deposit ceiling reports `ERR_RESOURCE_NOT_AVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/pair_a_resource_unavailable_outranks_deposit_cap
    """
    producer, resource, _first, twin = _ceiling_loaded_producer_on_an_asset_in_maintenance(client)

    response = client.confirm_reservation(twin["id"], {}, FACILITIES_HEADERS)

    a.error_of(response, e.ERR_RESOURCE_NOT_AVAILABLE, 409)
    still_requested = fx.read_reservation(client, twin["id"])
    assert still_requested["status"] == "REQUESTED"
    a.assert_cents(still_requested["deposit_hold_cents"], 0, "deposit_hold_cents")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=420000)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1


def test_the_deposit_ceiling_surfaces_once_the_asset_is_available_again(client):
    """Clearing only the state violation proves the fiscal rule was live too.

    PRD 3.6: "The deposit ceiling is per producer, not per reservation: the
    producer's existing `deposit_held_cents` plus the newly computed hold must not
    exceed 500000 cents. Breaching it is `ERR_DEPOSIT_LIMIT_EXCEEDED` (402), and
    no hold is written."

    PRD 3.6: "`AVAILABLE → MAINTENANCE` and `MAINTENANCE → AVAILABLE` are both
    freely available and both simply record the reason and increment the asset's
    `version` by 1; existing reservations keep their own status across a
    maintenance move, but no `REQUESTED` reservation on the asset can be
    confirmed while it sits in `MAINTENANCE`."

    Design: Difficulty/priority_pair_validation_conflict/pair_a_resource_unavailable_outranks_deposit_cap
    """
    producer, resource, _first, twin = _ceiling_loaded_producer_on_an_asset_in_maintenance(client)
    a.error_of(
        client.confirm_reservation(twin["id"], {}, FACILITIES_HEADERS),
        e.ERR_RESOURCE_NOT_AVAILABLE,
        409,
    )

    fx.set_resource_status(client, resource["id"], "AVAILABLE", status_reason="Service complete")
    response = client.confirm_reservation(twin["id"], {}, FACILITIES_HEADERS)

    a.error_of(response, e.ERR_DEPOSIT_LIMIT_EXCEEDED, 402)
    still_requested = fx.read_reservation(client, twin["id"])
    assert still_requested["status"] == "REQUESTED"
    a.assert_cents(still_requested["deposit_hold_cents"], 0, "deposit_hold_cents")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=420000)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1


# ---------------------------------------------------------------------------
# Live certification (422) outranks the volunteer's own time conflict (409)
# ---------------------------------------------------------------------------
def _overlapping_slots_with_a_double_booked_pair(client):
    """Two overlapping slots on different channels, each already part-staffed.

    The first slot occupies 18:00 to 18:32 and the second 18:15 to 18:47, so a
    volunteer confirmed on one is unavailable for the other.
    """
    live_producer = fx.setup_live_certified_producer(
        client, legal_name="Lena Horne", email="lena@patv.example"
    )
    volunteer = fx.setup_active_producer(
        client, legal_name="Vera Rubin", email="vera@patv.example"
    )
    first_channel = fx.create_channel(client, call_sign="PATV1")
    second_channel = fx.create_channel(client, call_sign="PATV2")

    directed = fx.setup_approved_program(
        client,
        live_producer["id"],
        title="Live Town Forum",
        runtime_seconds=1800,
        is_live=True,
        required_crew_roles=["DIRECTOR", "CAMERA"],
    )
    staffed = fx.setup_approved_program(
        client,
        live_producer["id"],
        title="Neighborhood Notes",
        runtime_seconds=1800,
        is_live=True,
        required_crew_roles=["CAMERA", "AUDIO"],
    )
    early_slot = fx.book_slot(
        client, first_channel["id"], staffed["id"], "2026-08-20T18:00:00Z"
    )
    late_slot = fx.book_slot(
        client, second_channel["id"], directed["id"], "2026-08-20T18:15:00Z"
    )
    fx.staff_slot(client, early_slot["id"], volunteer["id"], "CAMERA")
    fx.staff_slot(client, early_slot["id"], live_producer["id"], "AUDIO")
    volunteer_directing = fx.offer_crew(client, late_slot["id"], volunteer["id"], "DIRECTOR")
    return live_producer, volunteer, early_slot, late_slot, volunteer_directing


def test_missing_live_certification_masks_the_volunteers_own_time_conflict(client):
    """The safety band is heard even though the volunteer is also double-booked.

    PRD 3.5: "Then certification: the roles `DIRECTOR` and `SWITCHER` are the two
    positions that demand top-tier training, so confirming either of them on a
    slot whose program has `is_live` true requires the volunteer's
    `certification_level` to be `LIVE`, and anything less is refused with
    `ERR_CERTIFICATION_INSUFFICIENT` (422)."

    PRD 3.5: "The certification check outranks the overlap check, so a
    `BASIC`-certified volunteer offered a `DIRECTOR` role who is also double-booked
    hears about the certification, not the clash."

    Design: Difficulty/priority_pair_validation_conflict/pair_b_live_certification_outranks_crew_time_conflict
    """
    _live_producer, volunteer, _early_slot, _late_slot, volunteer_directing = (
        _overlapping_slots_with_a_double_booked_pair(client)
    )
    uncertified = fx.read_producer(client, volunteer["id"])
    assert uncertified["certification_level"] == "NONE"
    assert uncertified["status"] == "ACTIVE"

    response = client.confirm_crew_assignment(
        volunteer_directing["id"], {}, make_producer_headers(volunteer["id"])
    )

    a.error_of(response, e.ERR_CERTIFICATION_INSUFFICIENT, 422)
    assert fx.read_crew(client, volunteer_directing["id"])["status"] == "OFFERED"
    a.assert_producer_counters(fx.read_producer(client, volunteer["id"]), commitments=1)


def test_the_time_conflict_surfaces_for_a_live_certified_volunteer(client):
    """Swapping in a LIVE volunteer leaves only the overlap rule broken.

    PRD 3.5: "Finally the volunteer must be free: if they already hold a
    `CONFIRMED` assignment on some other slot whose half-open interval from
    `start_at` to `end_at` overlaps this slot's interval, the request is refused
    with `ERR_CREW_TIME_CONFLICT` (409)."

    PRD 2.9: "A producer's `confirmed_crew_commitments` is the count of that
    producer's crew assignments whose status is `CONFIRMED`."

    Design: Difficulty/priority_pair_validation_conflict/pair_b_live_certification_outranks_crew_time_conflict
    """
    live_producer, volunteer, early_slot, late_slot, volunteer_directing = (
        _overlapping_slots_with_a_double_booked_pair(client)
    )
    a.error_of(
        client.confirm_crew_assignment(
            volunteer_directing["id"], {}, make_producer_headers(volunteer["id"])
        ),
        e.ERR_CERTIFICATION_INSUFFICIENT,
        422,
    )
    certified = fx.read_producer(client, live_producer["id"])
    assert certified["certification_level"] == "LIVE"
    assert sorted(certified["competency_codes"]) == [
        "AUDIO_BOARD", "EDIT_SUITE", "LIVE_SWITCHER", "STUDIO_FLOOR"
    ]

    producer_directing = fx.offer_crew(
        client, late_slot["id"], live_producer["id"], "DIRECTOR"
    )
    response = client.confirm_crew_assignment(
        producer_directing["id"], {}, make_producer_headers(live_producer["id"])
    )

    a.error_of(response, e.ERR_CREW_TIME_CONFLICT, 409)
    assert fx.read_crew(client, producer_directing["id"])["status"] == "OFFERED"
    assert fx.read_crew(client, volunteer_directing["id"])["status"] == "OFFERED"
    assert fx.read_slot(client, late_slot["id"])["staffing_status"] == "UNDERSTAFFED"
    assert fx.read_slot(client, early_slot["id"])["staffing_status"] == "READY"
    a.assert_producer_counters(fx.read_producer(client, live_producer["id"]), commitments=1)
    a.assert_producer_counters(fx.read_producer(client, volunteer["id"]), commitments=1)
