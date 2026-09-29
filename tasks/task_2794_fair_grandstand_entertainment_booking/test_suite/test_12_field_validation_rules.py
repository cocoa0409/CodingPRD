"""Boundary behaviour of the service's field-level and cross-record validation
rules: seat allotments against the two stage capacity pools, the occupation
window's lower bound, the edition refund reserve, the radius waiver and the
order in which a lapsed offer and a stale echoed version are reported.
"""

from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_seat_identity, assert_ticket_scale
from test_helpers.factories import (
    build_contingency_action_payload,
    build_counter_payload,
    build_offer_payload,
    build_revise_payload,
    build_ticket_scale_payload,
)
from test_helpers.fixtures import (
    booking_version,
    create_offer,
    create_stage,
    find_advance_for_booking,
    get_booking,
    get_edition,
    get_offer,
    get_stage,
    get_ticket_scale,
    offer_version,
    record_sales_batch,
    set_clock,
    setup_accepted_booking,
    setup_announced_booking,
    setup_base_world,
)
from test_helpers.test_users import (
    BOX_OFFICE_MANAGER_HEADERS,
    FAIR_OPERATIONS_DIRECTOR_HEADERS,
    TALENT_BUYER_HEADERS,
)


def _assert_same_instant(actual, expected):
    """Compare two UTC instants by value, both rendered with a trailing Z."""
    assert actual is not None, "expected an instant, read null"
    assert actual.endswith("Z"), actual
    parsed_actual = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    parsed_expected = datetime.fromisoformat(expected.replace("Z", "+00:00"))
    assert parsed_actual == parsed_expected, f"{actual} is not the instant {expected}"


class TestSeatAllotmentAgainstStageCapacity:
    """The reserved and general-admission pools are checked separately."""

    def test_reserved_allotment_one_seat_over_capacity_is_refused(self):
        """A single reserved tier of 4001 seats on a stage carrying 4000 reserved
        seats breaches the capacity ceiling, and the refusal is total: no tier is
        stored, the box-office dimension stays at SCALED_PENDING, the booking's
        gross potential stays 0 and its version does not move.
        "the total must not exceed the stage's `reserved_seat_capacity` for reserved tiers"

        Design: Corner/validations/allotment_one_seat_over_reserved_capacity_rejected
        """
        scenario = setup_accepted_booking()
        booking_id = scenario["booking"]["id"]
        version_before = booking_version(booking_id)

        payload = build_ticket_scale_payload(
            version_before,
            seating_type="RESERVED",
            tier_name="GOLD",
            face_price_cents=6295,
            allotment_seats=4001,
            bundled_with_gate_admission=False,
            facility_fee_cents=400,
        )
        response = api_client.create_ticket_scale(
            booking_id, payload, BOX_OFFICE_MANAGER_HEADERS
        )
        error = validate_error(
            response, ApiErrorId.ERR_ALLOTMENT_EXCEEDS_STAGE_CAPACITY.value
        )
        assert set(error.keys()) == {"error_id", "message"}

        scales, meta = validate_paginated(
            api_client.list_ticket_scales(booking_id, BOX_OFFICE_MANAGER_HEADERS)
        )
        assert scales == []
        assert meta["total_count"] == 0

        booking = get_booking(booking_id)
        assert booking["ticketing_status"] == "SCALED_PENDING"
        assert booking["gross_potential_cents"] == 0
        assert booking["version"] == version_before

    def test_reserved_allotment_exactly_at_capacity_is_admitted(self):
        """A reserved tier of exactly 4000 seats sits at the stage's reserved
        capacity rather than above it, so it is stored and it carries the
        box-office dimension into SCALED. Its gross potential is the artist-facing
        face value multiplied by the allotment and by the complement of the 5.75
        percent admission tax, rounded half up to whole cents.
        "the total must not exceed the stage's `reserved_seat_capacity` for reserved tiers"

        Design: Corner/validations/allotment_exactly_at_reserved_capacity_admitted
        """
        scenario = setup_accepted_booking()
        booking_id = scenario["booking"]["id"]

        payload = build_ticket_scale_payload(
            booking_version(booking_id),
            seating_type="RESERVED",
            tier_name="GOLD",
            face_price_cents=6295,
            allotment_seats=4000,
            bundled_with_gate_admission=False,
            facility_fee_cents=400,
        )
        created = validate_success(
            api_client.create_ticket_scale(
                booking_id, payload, BOX_OFFICE_MANAGER_HEADERS
            ),
            expected_status=201,
        )
        assert_ticket_scale(created)

        scale = get_ticket_scale(created["id"])
        assert scale["allotment_seats"] == 4000
        assert scale["sold_seats"] == 0
        assert scale["available_seats"] == 4000
        assert_seat_identity(scale)
        # The facility fee is promoter income and never enters the artist gross.
        assert scale["scale_gross_potential_cents"] == 23732150

        booking = get_booking(booking_id)
        assert booking["ticketing_status"] == "SCALED"
        assert booking["gross_potential_cents"] == 23732150
        assert booking["booking_status"] == "DATE_HELD"

    def test_allotment_sums_per_seating_type_not_across_types(self):
        """The ceiling is a running sum over the booking's existing tiers of the
        same seating type, so with 3000 reserved seats already scaled a further
        1001 reserved seats breach the 4000-seat reserved pool while 1000 do not,
        and a 6000-seat general-admission tier is still admitted against its own
        pool.
        "adding up `allotment_seats` across the booking's existing tiers of the same `seating_type`"

        Design: Corner/validations/seat_allotment_sums_per_seating_type_not_across_types
        """
        scenario = setup_accepted_booking()
        booking_id = scenario["booking"]["id"]

        lower = validate_success(
            api_client.create_ticket_scale(
                booking_id,
                build_ticket_scale_payload(
                    booking_version(booking_id),
                    seating_type="RESERVED",
                    tier_name="LOWER",
                    face_price_cents=6295,
                    allotment_seats=3000,
                    bundled_with_gate_admission=False,
                    facility_fee_cents=400,
                ),
                BOX_OFFICE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )

        version_after_lower = booking_version(booking_id)
        over_the_pool = api_client.create_ticket_scale(
            booking_id,
            build_ticket_scale_payload(
                version_after_lower,
                seating_type="RESERVED",
                tier_name="UPPER",
                face_price_cents=4000,
                allotment_seats=1001,
                bundled_with_gate_admission=False,
                facility_fee_cents=400,
            ),
            BOX_OFFICE_MANAGER_HEADERS,
        )
        validate_error(
            over_the_pool, ApiErrorId.ERR_ALLOTMENT_EXCEEDS_STAGE_CAPACITY.value
        )

        # The refused attempt mutated nothing, so the same version is still current.
        upper = validate_success(
            api_client.create_ticket_scale(
                booking_id,
                build_ticket_scale_payload(
                    version_after_lower,
                    seating_type="RESERVED",
                    tier_name="UPPER",
                    face_price_cents=4000,
                    allotment_seats=1000,
                    bundled_with_gate_admission=False,
                    facility_fee_cents=400,
                ),
                BOX_OFFICE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )

        lawn = validate_success(
            api_client.create_ticket_scale(
                booking_id,
                build_ticket_scale_payload(
                    booking_version(booking_id),
                    seating_type="GENERAL_ADMISSION",
                    tier_name="LAWN",
                    face_price_cents=3950,
                    allotment_seats=6000,
                    bundled_with_gate_admission=False,
                    facility_fee_cents=0,
                ),
                BOX_OFFICE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )

        scales, meta = validate_paginated(
            api_client.list_ticket_scales(booking_id, BOX_OFFICE_MANAGER_HEADERS)
        )
        assert meta["total_count"] == 3
        assert [scale["id"] for scale in scales] == [
            lower["id"],
            upper["id"],
            lawn["id"],
        ]
        assert [scale["allotment_seats"] for scale in scales] == [3000, 1000, 6000]

        # Each tier line is rounded to whole cents first, then the lines are added.
        assert lower["scale_gross_potential_cents"] == 17799113
        assert upper["scale_gross_potential_cents"] == 3770000
        assert lawn["scale_gross_potential_cents"] == 22337250
        booking = get_booking(booking_id)
        assert booking["gross_potential_cents"] == 43906363


def test_load_in_before_show_date_midnight_is_refused_then_admitted_at_midnight():
    """The occupation window carried by a drafted offer is well formed only when
    load-in falls at or after the performance date's own midnight, so a load-in
    an hour before that boundary is refused even though it precedes load-out,
    while a load-in exactly at midnight is admitted.
    "`load_in_start_utc` falls at or after the very beginning of `target_show_date`"

    Design: Corner/validations/load_in_before_show_date_midnight_returns_invalid_slot_window
    """
    world = setup_base_world()

    before_midnight = build_offer_payload(
        world["edition"]["id"],
        world["artist"]["id"],
        world["stage"]["id"],
        target_show_date="2026-08-22",
        load_in_start_utc="2026-08-21T23:00:00.000Z",
        load_out_end_utc="2026-08-22T23:00:00.000Z",
    )
    validate_error(
        api_client.create_offer(before_midnight, TALENT_BUYER_HEADERS),
        ApiErrorId.ERR_INVALID_SLOT_WINDOW.value,
    )

    at_midnight = build_offer_payload(
        world["edition"]["id"],
        world["artist"]["id"],
        world["stage"]["id"],
        target_show_date="2026-08-22",
        load_in_start_utc="2026-08-22T00:00:00.000Z",
        load_out_end_utc="2026-08-22T23:00:00.000Z",
    )
    offer = validate_success(
        api_client.create_offer(at_midnight, TALENT_BUYER_HEADERS),
        expected_status=201,
    )
    # A draft holds no slot and encumbers no budget, so nothing is stamped yet.
    assert offer["status"] == "DRAFT"
    assert offer["sent_at_utc"] is None
    assert offer["expires_at_utc"] is None

    offers, meta = validate_paginated(
        api_client.list_offers(
            TALENT_BUYER_HEADERS, {"artist_id": world["artist"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [record["id"] for record in offers] == [offer["id"]]


def test_refund_reserve_is_checked_against_edition_level_headroom():
    """A cancellation's refund liability is measured against the edition's whole
    reserve, not against anything on the booking: a full refund of 500 sold
    reserved seats at a refundable base of 6695 cents overruns a 1,000,000-cent
    reserve and is refused outright, while a rain-check postponement of the same
    show costs nothing and lands.
    "plus the candidate action's `refund_liability_cents` must not exceed the edition's `refund_reserve_cents`"

    Design: Corner/validations/refund_reserve_is_checked_against_edition_level_headroom
    """
    world = setup_base_world(edition_overrides={"refund_reserve_cents": 1_000_000})
    scenario = setup_announced_booking(
        world,
        scale_overrides={
            "seating_type": "RESERVED",
            "tier_name": "GOLD",
            "face_price_cents": 6295,
            "allotment_seats": 2000,
            "bundled_with_gate_admission": False,
            "facility_fee_cents": 400,
        },
        doors_time_utc="2026-08-22T18:00:00.000Z",
    )
    booking_id = scenario["booking"]["id"]
    record_sales_batch(scenario["ticket_scale"]["id"], "SALE", 500, "ONLINE")

    version_before = booking_version(booking_id)
    refused = api_client.create_contingency_action(
        booking_id,
        build_contingency_action_payload(
            version_before,
            action_type="CANCEL",
            reason_code="SEVERE_WEATHER",
            refund_policy="FULL_REFUND",
        ),
        FAIR_OPERATIONS_DIRECTOR_HEADERS,
    )
    validate_error(refused, ApiErrorId.ERR_REFUND_RESERVE_EXCEEDED.value)

    booking = get_booking(booking_id)
    assert booking["booking_status"] == "ANNOUNCED"
    assert booking["ticketing_status"] == "ON_SALE"
    assert booking["version"] == version_before
    assert get_edition(world["edition"]["id"])["refund_liability_committed_cents"] == 0

    action = validate_success(
        api_client.create_contingency_action(
            booking_id,
            build_contingency_action_payload(
                booking_version(booking_id),
                action_type="POSTPONE",
                reason_code="SEVERE_WEATHER",
                refund_policy="RAIN_CHECK",
                replacement_show_date="2026-08-26",
            ),
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert action["pre_doors"] is True
    assert action["refund_liability_cents"] == 0
    assert get_edition(world["edition"]["id"])["refund_liability_committed_cents"] == 0

    assert get_booking(booking_id)["booking_status"] == "POSTPONED"
    replacements, meta = validate_paginated(
        api_client.list_show_bookings(
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
            {"postponed_from_booking_id": booking_id},
        )
    )
    assert meta["total_count"] == 1
    replacement = replacements[0]
    assert replacement["booking_status"] == "DATE_HELD"
    assert replacement["show_date"] == "2026-08-26"
    assert find_advance_for_booking(replacement["id"])["status"] == "ADVANCE_PENDING"


def test_radius_waiver_granted_by_the_blocking_offer_disarms_the_clause():
    """The artist's radius clause is read off the blocking offer's own waiver flag
    and its own half-widths, so a second date three days later inside that window
    is refused while the first offer's waiver is unset, and the identical send is
    admitted once the agent's counter releases the clause.
    "An offer whose `radius_waiver_granted` reads true never blocks anything."

    Design: Corner/validations/radius_waiver_granted_disarms_the_radius_clause
    """
    world = setup_base_world()
    pavilion = create_stage(
        world["edition"]["id"],
        name="Riverside Pavilion",
        reserved_seat_capacity=1500,
        ga_capacity=2000,
        slot_soft_cap=4,
    )

    grandstand_offer = create_offer(
        world["edition"]["id"],
        world["artist"]["id"],
        world["stage"]["id"],
        radius_miles=150,
        radius_days_before=3,
        radius_days_after=3,
    )
    validate_success(
        api_client.send_offer(grandstand_offer["id"], TALENT_BUYER_HEADERS)
    )

    pavilion_offer = create_offer(
        world["edition"]["id"],
        world["artist"]["id"],
        pavilion["id"],
        offered_guarantee_cents=500_000,
        backend_breakeven_cents=0,
        target_show_date="2026-08-24",
        load_in_start_utc="2026-08-24T14:00:00.000Z",
        load_out_end_utc="2026-08-24T23:00:00.000Z",
        radius_miles=0,
        radius_days_before=0,
        radius_days_after=0,
    )
    validate_error(
        api_client.send_offer(pavilion_offer["id"], TALENT_BUYER_HEADERS),
        ApiErrorId.ERR_RADIUS_CLAUSE_CONFLICT.value,
    )
    blocked = get_offer(pavilion_offer["id"])
    assert blocked["status"] == "DRAFT"
    assert blocked["sent_at_utc"] is None

    countered = validate_success(
        api_client.counter_offer(
            grandstand_offer["id"],
            build_counter_payload(
                13_000_000,
                proposed_breakeven_cents=6_000_000,
                grant_radius_waiver=True,
                note="Waiving radius for the pavilion date",
            ),
            world["agent_headers"],
        )
    )
    assert countered["status"] == "COUNTERED"
    assert countered["radius_waiver_granted"] is True
    assert countered["countered_guarantee_cents"] == 13_000_000
    assert countered["round_count"] == 2
    # The encumbrance tracks the buyer's standing guarantee, never the agent's ask.
    edition = get_edition(world["edition"]["id"])
    assert edition["committed_guarantee_total_cents"] == 12_500_000

    sent = validate_success(
        api_client.send_offer(pavilion_offer["id"], TALENT_BUYER_HEADERS)
    )
    assert sent["status"] == "SENT"
    _assert_same_instant(sent["expires_at_utc"], "2026-08-03T00:00:00.000Z")

    pavilion_state = get_stage(pavilion["id"])
    assert pavilion_state["held_show_count"] == 1
    assert pavilion_state["booking_posture"] == "OPEN"


def test_expiry_outranks_stale_version_on_the_same_revise():
    """A revise that arrives after the response window has closed while also
    echoing a superseded offer version reports the lapse rather than the stale
    read, and the lapse is persisted: the offer is auto-transitioned to EXPIRED,
    its stage hold is released, and a second revise carrying the correct version
    then reports the terminal state instead.
    "the offer is first auto-transitioned to `EXPIRED` and the triggering request is then refused with `ERR_OFFER_EXPIRED`"

    Design: Corner/validations/expiry_outranks_stale_version_on_the_same_revise
    """
    world = setup_base_world()
    offer = create_offer(
        world["edition"]["id"], world["artist"]["id"], world["stage"]["id"]
    )
    validate_success(api_client.send_offer(offer["id"], TALENT_BUYER_HEADERS))
    stale_version = offer_version(offer["id"])

    set_clock("2026-08-02T00:00:00.000Z")
    validate_success(
        api_client.counter_offer(
            offer["id"],
            build_counter_payload(14_000_000, proposed_backend_split_pct=0.9000, note="Ask"),
            world["agent_headers"],
        )
    )
    fresh_version = offer_version(offer["id"])
    assert fresh_version != stale_version

    # The expiry boundary is inclusive, so this instant is already lapsed.
    set_clock("2026-08-03T00:00:00.000Z")
    lapsed = api_client.revise_offer(
        offer["id"],
        build_revise_payload(
            stale_version,
            13_000_000,
            backend_split_pct=0.8700,
            backend_breakeven_cents=6_000_000,
            note="Meeting in the middle",
        ),
        TALENT_BUYER_HEADERS,
    )
    validate_error(lapsed, ApiErrorId.ERR_OFFER_EXPIRED.value)
    assert get_offer(offer["id"])["status"] == "EXPIRED"

    terminal = api_client.revise_offer(
        offer["id"],
        build_revise_payload(
            fresh_version,
            13_000_000,
            backend_split_pct=0.8700,
            backend_breakeven_cents=6_000_000,
            note="Retry with the right version",
        ),
        TALENT_BUYER_HEADERS,
    )
    validate_error(terminal, ApiErrorId.ERR_INVALID_OFFER_STATE.value)

    rounds, meta = validate_paginated(
        api_client.list_offer_rounds(offer["id"], TALENT_BUYER_HEADERS)
    )
    assert meta["total_count"] == 2
    assert [record["proposed_by"] for record in rounds] == ["BUYER", "AGENT"]

    stage = get_stage(world["stage"]["id"])
    assert stage["held_show_count"] == 0
    assert stage["booking_posture"] == "OPEN"
