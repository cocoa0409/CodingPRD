"""Endpoint corners: CRUD round trips, action verbs and computed reads."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    FACILITIES_HEADERS,
    SCHEDULER_HEADERS,
    make_producer_headers,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_the_resource_class_and_status_filters_compose_on_the_listing(client):
    """Filtering is a list concern only; the row stays readable by id.

    PRD 3.6: "A registered asset opens `AVAILABLE` with `open_reservation_count` at
    0 and a null `status_reason`. Resources may be listed filtered by
    `resource_class` or `status`."

    PRD 3.6: "`AVAILABLE → MAINTENANCE` and `MAINTENANCE → AVAILABLE` are both
    freely available and both simply record the reason and increment the asset's
    `version` by 1"

    PRD 2.3: "Every list response reports `limit` and `offset` as they were applied,
    `total_count` as the number of rows matching the filters before pagination, and
    `has_more` as true exactly when rows remain beyond the current page."

    PRD 2.3: "Collection reads are ordered by `created_at` ascending."

    Design: Corner/endpoints/corner_studio_resource_crud_and_filtered_listing
    """
    first_studio = fx.create_resource(
        client,
        resource_code="STUDIO-A",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    second_studio = fx.create_resource(
        client,
        resource_code="STUDIO-B",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=3,
        turnaround_minutes=15,
        base_deposit_cents=9000,
        replacement_value_cents=500000,
    )
    camera_kit = fx.create_resource(
        client,
        resource_code="CAM-KIT",
        resource_class="FIELD_CAMERA_KIT",
        required_competency_code="ENG_CAMERA",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=5000,
        replacement_value_cents=90000,
    )
    assert first_studio["status"] == "AVAILABLE"
    assert first_studio["open_reservation_count"] == 0
    a.assert_field_absent_or_null(first_studio, "status_reason")

    read_back = a.data_of(client.get_studio_resource(first_studio["id"], FACILITIES_HEADERS))
    assert read_back["resource_code"] == "STUDIO-A"
    assert read_back["capacity_slots"] == 1
    assert read_back["turnaround_minutes"] == 30
    a.assert_cents(read_back["base_deposit_cents"], 12345, "base_deposit_cents")
    a.assert_common_fields(read_back, expected_version=1)

    studios, studio_meta = a.assert_pagination_meta(
        client.list_studio_resources(
            SCHEDULER_HEADERS, {"resource_class": "STUDIO_A", "limit": 10, "offset": 0}
        ),
        2,
    )
    a.assert_ids_equal(studios, [first_studio["id"], second_studio["id"]])
    assert studio_meta["has_more"] is False
    a.assert_excludes_id(studios, camera_kit["id"])

    in_maintenance = fx.set_resource_status(
        client, second_studio["id"], "MAINTENANCE", status_reason="Floor resurfacing"
    )
    assert in_maintenance["status"] == "MAINTENANCE"
    assert in_maintenance["status_reason"] == "Floor resurfacing"

    available, available_meta = a.assert_pagination_meta(
        client.list_studio_resources(
            SCHEDULER_HEADERS,
            {"resource_class": "STUDIO_A", "status": "AVAILABLE", "limit": 10, "offset": 0},
        ),
        1,
    )
    a.assert_ids_equal(available, [first_studio["id"]])
    assert available_meta["has_more"] is False
    hidden = fx.read_resource(client, second_studio["id"])
    assert hidden["status"] == "MAINTENANCE"
    assert hidden["status_reason"] == "Floor resurfacing"


def test_releasing_a_confirmed_volunteer_restates_the_slots_coverage(client):
    """Nothing aired, so the release credits no hours and cancels no booking.

    PRD 3.5: "From `CONFIRMED` it does the same and additionally lowers the
    volunteer's `confirmed_crew_commitments` by 1; releasing a confirmed volunteer is
    exactly how a slot falls back from `READY` to `UNDERSTAFFED`."

    PRD 3.5: "Release requires a `release_reason` and is available to the volunteer
    or to a `SchedulingCoordinator`."

    PRD 2.9: "A producer's `volunteer_hours_tenths` is the sum of
    `credited_hours_tenths` over that producer's `COMPLETED` crew assignments, in
    tenths of an hour as a whole number."

    PRD 3.5: "the slot is `READY` when every role in `required_crew_roles` appears in
    that set, and `UNDERSTAFFED` otherwise."

    Design: Corner/endpoints/corner_crew_release_action_frees_commitment_and_restates_staffing
    """
    owner = fx.setup_live_certified_producer(client, legal_name="Ada Lovelace")
    volunteer = fx.setup_active_producer(client, legal_name="Vera Rubin")
    channel = fx.create_channel(client, call_sign="PATV1")
    program = fx.setup_approved_program(
        client, owner["id"], title="Crewed Feature", runtime_seconds=1800,
        is_live=True, required_crew_roles=["AUDIO"],
    )
    slot = fx.book_slot(client, channel["id"], program["id"], "2026-08-20T18:00:00Z")
    assignment = fx.offer_crew(client, slot["id"], volunteer["id"], "AUDIO")
    confirmed = fx.confirm_crew(client, assignment["id"], volunteer["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert fx.read_slot(client, slot["id"])["staffing_status"] == "READY"
    a.assert_producer_counters(fx.read_producer(client, volunteer["id"]), commitments=1)

    released = a.data_of(
        client.release_crew_assignment(
            assignment["id"],
            f.crew_release_payload(release_reason="Volunteer unavailable that evening"),
            make_producer_headers(volunteer["id"]),
        )
    )

    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "Volunteer unavailable that evening"
    assert released["credited_hours_tenths"] == 0

    after_slot = fx.read_slot(client, slot["id"])
    assert after_slot["staffing_status"] == "UNDERSTAFFED"
    assert after_slot["status"] == "SCHEDULED"
    a.assert_producer_counters(
        fx.read_producer(client, volunteer["id"]), volunteer_tenths=0, commitments=0
    )


def test_a_studio_booking_may_only_be_linked_to_its_own_producers_airing(client):
    """The optional link is resolved as a foreign key first and an owner second.

    PRD 2.8: "**Body foreign-key existence (priority 5)** — the referenced entity's
    own not-found error, 404. Applies to enrollment creation, series creation,
    program creation, playback-slot creation, reservation creation and
    crew-assignment creation."

    PRD 3.6: "Where a `linked_slot_id` is supplied, the program behind that slot must
    belong to the same producer as `producer_id`, and a mismatch is refused with
    `ERR_SLOT_PRODUCER_MISMATCH` (422)."

    PRD 3.6: "Step three computes the live loading: where the reservation names a
    `linked_slot_id` whose program has `is_live` true, the live loading is 2000 basis
    points, otherwise it is 0."

    PRD 3.6: "A clean comparison case, with no suspension points, a two-hour window
    and no live link, gives the base 12345 plus a duration line of 617, for a hold of
    12962 cents."

    Design: Corner/endpoints/corner_reservation_link_requires_own_existing_slot
    """
    booker = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    stranger = fx.setup_basic_certified_producer(client, score=88, legal_name="Grace Hopper")
    channel = fx.create_channel(client, call_sign="PATV1")
    own_program = fx.setup_approved_program(
        client, booker["id"], title="Riverside Weekly Recap", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    other_program = fx.setup_approved_program(
        client, stranger["id"], title="Harbor Nightly Recap", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    own_slot = fx.book_slot(client, channel["id"], own_program["id"], "2026-08-20T18:00:00Z")
    other_slot = fx.book_slot(client, channel["id"], other_program["id"], "2026-08-20T19:00:00Z")
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
    headers = make_producer_headers(booker["id"])

    def _request(linked_slot_id):
        return client.create_reservation(
            f.reservation_payload(
                booker["id"], resource["id"],
                "2026-08-20T16:00:00Z", "2026-08-20T18:00:00Z",
                linked_slot_id=linked_slot_id,
            ),
            headers,
        )

    a.error_of(_request(UNKNOWN_UUID), e.ERR_PLAYBACK_SLOT_NOT_FOUND, 404)
    a.error_of(_request(other_slot["id"]), e.ERR_SLOT_PRODUCER_MISMATCH, 422)

    accepted = a.created_of(_request(own_slot["id"]))

    assert accepted["status"] == "REQUESTED"
    assert accepted["linked_slot_id"] == own_slot["id"]
    a.assert_cents(accepted["deposit_hold_cents"], 0, "deposit_hold_cents")
    mine, _meta = a.assert_pagination_meta(
        client.list_reservations(FACILITIES_HEADERS, {"producer_id": booker["id"]}), 1
    )
    a.assert_ids_equal(mine, [accepted["id"]])

    confirmed = fx.confirm_reservation(client, accepted["id"])
    a.assert_cents(confirmed["deposit_hold_cents"], 12962, "deposit_hold_cents")
    assert confirmed["risk_bp"] == 0


def test_the_open_reservation_count_is_read_off_the_reservation_table(client):
    """A plain read shows 0, then 1, then 0 again as the booking moves.

    PRD 2.9: "A studio resource's `open_reservation_count` is the count of its
    reservations whose status is `CONFIRMED`, `CHECKED_OUT` or `DAMAGE_REVIEW`."

    PRD 3.6: "A successful confirmation freezes both `risk_bp` and
    `deposit_hold_cents` on the reservation — neither is ever recomputed afterwards,
    so a later suspension does not retroactively raise an existing hold — raises the
    producer's `deposit_held_cents` by the hold amount, raises the asset's
    `open_reservation_count` by 1, and increments the reservation's `version` by 1."

    PRD 3.6: "From `CONFIRMED` it is a compensating action: `deposit_refunded_cents`
    is set to the full `deposit_hold_cents`, `deposit_forfeited_cents` is set to 0 and
    `uncovered_liability_cents` is set to 0, while `deposit_hold_cents` itself is
    retained for audit rather than zeroed."

    Design: Corner/endpoints/corner_computed_read_resource_open_reservation_count
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
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
    reservation = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-20T10:00:00Z", end_at="2026-08-20T12:00:00Z",
    )

    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 0

    confirmed = fx.confirm_reservation(client, reservation["id"])
    a.assert_cents(confirmed["deposit_hold_cents"], 12962, "deposit_hold_cents")
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=12962)

    cancelled = a.data_of(
        client.cancel_reservation(
            reservation["id"],
            f.reservation_cancel_payload(cancellation_reason="Shoot postponed"),
            make_producer_headers(producer["id"]),
        )
    )

    assert cancelled["status"] == "CANCELLED"
    a.assert_cents(cancelled["deposit_refunded_cents"], 12962, "deposit_refunded_cents")
    a.assert_cents(cancelled["deposit_hold_cents"], 12962, "deposit_hold_cents")
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 0
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=0)


def test_view_recording_stops_the_moment_the_asset_is_purged(client):
    """The cumulative total replaces the stored figure, until the lifecycle closes.

    PRD 3.9: "the caller supplies `on_demand_views` as the cumulative view total,
    which replaces the stored figure rather than adding to it, and the `FINAL`
    community impact index is immediately recomputed from it. This is accepted only
    while the asset is `PUBLISHED`; once the asset has moved to `WITHDRAWN` or
    `PURGED` it stops accepting view records and the request is refused with
    `ERR_INVALID_STATE_TRANSITION` (409)."

    PRD 3.9: "The index is 100 multiplied by the weighted sum of the three
    components, with the reach component weighted 0.5, the demand component 0.3 and
    the volunteer component 0.2, and the result rounded half up to two decimal places
    and emitted as a JSON number."

    PRD 3.9: "the boundary is inclusive: the asset becomes purgeable at the
    `retain_until` instant itself, so a purge at one second before `retain_until` is
    refused with `ERR_RETENTION_NOT_ELAPSED` (409) while a purge at exactly
    `retain_until` succeeds."

    PRD 3.9: "A successful purge stamps `purged_at` with the current logical instant,
    freezes `on_demand_views` and `community_impact_index` at their last values, and
    increments the asset's `version` by 1."

    Design: Corner/endpoints/corner_record_views_conditional_on_asset_not_purged
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    _channel, _program, _slot, asset = fx.setup_published_asset(
        client, producer["id"], "STANDARD_24M", "2026-08-20T18:00:00Z", 640,
        title="Neighborhood Notes", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    assert asset["on_demand_status"] == "PUBLISHED"
    assert asset["impact_variant"] == "FINAL"
    a.assert_instant_equals(asset["retain_until"], "2028-08-20T18:00:00Z", "retain_until")
    a.assert_index_equals(asset["community_impact_index"], 32.00)

    first = fx.record_views(client, asset["id"], 150)
    assert first["on_demand_views"] == 150
    a.assert_index_equals(first["community_impact_index"], 41.00)

    second = fx.record_views(client, asset["id"], 250)
    assert second["on_demand_views"] == 250
    a.assert_index_equals(second["community_impact_index"], 47.00)

    fx.set_clock(client, "2028-08-20T18:00:00Z")
    purged = fx.purge_asset(client, asset["id"])
    assert purged["on_demand_status"] == "PURGED"
    a.assert_instant_equals(purged["purged_at"], "2028-08-20T18:00:00Z", "purged_at")

    late = client.record_archive_views(asset["id"], f.record_views_payload(900), ADMIN_HEADERS)

    a.error_of(late, e.ERR_INVALID_STATE_TRANSITION, 409)
    frozen = fx.read_asset(client, asset["id"])
    assert frozen["on_demand_views"] == 250
    a.assert_index_equals(frozen["community_impact_index"], 47.00)
