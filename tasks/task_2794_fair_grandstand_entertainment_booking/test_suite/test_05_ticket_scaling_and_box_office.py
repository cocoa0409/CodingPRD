"""Ticket price structures and box-office movement: per-tier gross potential and
its rounding order, the two booking dimensions that join into on-sale, the
announcement's need for at least one price tier, and seat conservation across a
sale and its equal refund."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_append_only_common_fields,
    assert_seat_identity,
)
from test_helpers.factories import build_announce_payload
from test_helpers.fixtures import (
    add_ticket_scale,
    announce_booking,
    get_booking,
    get_ticket_scale,
    list_sales_batches,
    list_ticket_scales,
    prepare_completed_advance,
    record_sales_batch,
    setup_accepted_booking,
    setup_announced_booking,
)
from test_helpers.test_users import FAIR_OPERATIONS_DIRECTOR_HEADERS

# Reserved tier: face 6295 with a 400-cent facility fee, unbundled.
RESERVED_GOLD_1160 = {
    "seating_type": "RESERVED",
    "tier_name": "GOLD",
    "face_price_cents": 6295,
    "allotment_seats": 1160,
    "bundled_with_gate_admission": False,
    "facility_fee_cents": 400,
}

# General-admission tier whose ticket carries fair gate admission with it.
GA_LAWN_2100 = {
    "seating_type": "GENERAL_ADMISSION",
    "tier_name": "LAWN",
    "face_price_cents": 3950,
    "allotment_seats": 2100,
    "bundled_with_gate_admission": True,
    "facility_fee_cents": 250,
}

RESERVED_GOLD_2000 = {
    "seating_type": "RESERVED",
    "tier_name": "GOLD",
    "face_price_cents": 6295,
    "allotment_seats": 2000,
    "bundled_with_gate_admission": False,
    "facility_fee_cents": 400,
}

DOORS_TIME_UTC = "2026-08-22T18:00:00.000Z"


class TestTicketGrossPotential:
    """Each tier's potential is rounded on its own line before the lines are added."""

    def test_reserved_tier_potential_rounds_its_own_line_half_up(self):
        """A tier's potential is its artist-facing face value times its
        allotment times the complement of the admission tax, rounded half up on
        that one line and stored on the tier.

        "the product is rounded half up to whole cents and stored as the tier's `scale_gross_potential_cents`"

        Design: Difficulty/combinatorial_formula/ticket_gross_potential_per_line_then_sum
        """
        scenario = setup_accepted_booking()

        reserved = add_ticket_scale(scenario["booking"]["id"], **RESERVED_GOLD_1160)

        assert reserved["scale_gross_potential_cents"] == 6882324
        booking = get_booking(scenario["booking"]["id"])
        assert booking["gross_potential_cents"] == 6882324

    def test_bundled_general_admission_tier_deducts_the_gate_credit_first(self):
        """A bundled ticket carries fair gate admission, so sixty percent of the
        edition's gate admission price is carved out of the face value before
        the artist-facing potential of that tier is taken.

        "`bundle_credit_cents` is sixty percent of the edition's `gate_admission_price_cents`, rounded half up to whole cents"

        Design: Difficulty/combinatorial_formula/ticket_gross_potential_per_line_then_sum
        """
        scenario = setup_accepted_booking()

        add_ticket_scale(scenario["booking"]["id"], **RESERVED_GOLD_1160)
        lawn = add_ticket_scale(scenario["booking"]["id"], **GA_LAWN_2100)

        assert lawn["scale_gross_potential_cents"] == 6036713

    def test_booking_gross_potential_adds_the_rounded_tier_lines(self):
        """The show's potential is assembled from its tiers with each tier line
        rounded first, so the total sits one cent above what rounding a single
        unrounded grand total would have produced.

        "each tier's line amount is rounded to whole cents first and the rounded line amounts are then added together"

        Design: Difficulty/combinatorial_formula/ticket_gross_potential_per_line_then_sum
        """
        scenario = setup_accepted_booking()

        reserved = add_ticket_scale(scenario["booking"]["id"], **RESERVED_GOLD_1160)
        lawn = add_ticket_scale(scenario["booking"]["id"], **GA_LAWN_2100)

        booking = get_booking(scenario["booking"]["id"])
        assert booking["gross_potential_cents"] == 12919037
        assert booking["gross_potential_cents"] != 12919036
        assert booking["gross_potential_cents"] == (
            reserved["scale_gross_potential_cents"]
            + lawn["scale_gross_potential_cents"]
        )


class TestBookingDimensionsJoinIntoOnSale:
    """The contractual and box-office dimensions advance on their own triggers."""

    def test_first_price_tier_scales_the_box_office_and_leaves_the_contract_held(self):
        """Pricing the show is the box office's move alone: the first tier
        carries the box-office dimension out of its pending state while the
        contractual dimension stays exactly where acceptance left it.

        "The first tier ever created on a booking carries the box-office dimension `SCALED_PENDING → SCALED`."

        Design: Difficulty/non_linear_state_machine/show_booking_parallel_dimensions_join_to_on_sale
        """
        scenario = setup_accepted_booking()
        prepare_completed_advance(scenario)

        add_ticket_scale(scenario["booking"]["id"], **RESERVED_GOLD_1160)

        booking = get_booking(scenario["booking"]["id"])
        assert booking["ticketing_status"] == "SCALED"
        assert booking["booking_status"] == "DATE_HELD"

    def test_second_price_tier_leaves_the_box_office_latched_at_scaled(self):
        """Only the first tier ever created carries the box-office dimension
        forward, so adding a second tier to the same show leaves that dimension
        exactly where the first tier put it.

        "The first tier ever created on a booking carries the box-office dimension `SCALED_PENDING → SCALED`."

        Design: Difficulty/non_linear_state_machine/show_booking_parallel_dimensions_join_to_on_sale
        """
        scenario = setup_accepted_booking()
        prepare_completed_advance(scenario)

        add_ticket_scale(scenario["booking"]["id"], **RESERVED_GOLD_1160)
        add_ticket_scale(scenario["booking"]["id"], **GA_LAWN_2100)

        booking = get_booking(scenario["booking"]["id"])
        assert booking["ticketing_status"] == "SCALED"
        assert booking["booking_status"] == "DATE_HELD"

    def test_announcement_joins_both_dimensions_into_on_sale(self):
        """Going public is the operations director's move, and it is the second
        of the two dimensions to arrive, so the same request both announces the
        show and opens it for sale.

        "`ON_SALE` is reached exactly when `booking_status` reads `ANNOUNCED` and `ticketing_status` reads `SCALED`"

        Design: Difficulty/non_linear_state_machine/show_booking_parallel_dimensions_join_to_on_sale
        """
        scenario = setup_accepted_booking()
        prepare_completed_advance(scenario)
        reserved = add_ticket_scale(scenario["booking"]["id"], **RESERVED_GOLD_1160)
        lawn = add_ticket_scale(scenario["booking"]["id"], **GA_LAWN_2100)

        booking = announce_booking(scenario["booking"]["id"], DOORS_TIME_UTC)

        assert booking["booking_status"] == "ANNOUNCED"
        assert booking["ticketing_status"] == "ON_SALE"
        assert booking["doors_time_utc"] == DOORS_TIME_UTC
        assert get_ticket_scale(reserved["id"])["status"] == "ON_SALE_ELIGIBLE"
        assert get_ticket_scale(lawn["id"])["status"] == "ON_SALE_ELIGIBLE"


class TestAnnounceRequiresAPriceStructure:
    """Zero price tiers refuses the announcement; exactly one tier admits it."""

    def test_unpriced_booking_reports_zero_potential_without_being_in_error(self):
        """A show that has not been priced yet simply has no tiers to add up, so
        its potential legitimately reads zero and its box-office dimension is
        still waiting for its first tier.

        "because potential is a capacity figure and does not depend on sales; a booking with no tiers reads 0"

        Design: Difficulty/boundary_precision_check/announce_empty_price_structure_zero_versus_one_scale
        """
        scenario = setup_accepted_booking()
        prepare_completed_advance(scenario)

        booking = get_booking(scenario["booking"]["id"])
        assert booking["gross_potential_cents"] == 0
        assert booking["ticketing_status"] == "SCALED_PENDING"
        assert list_ticket_scales(booking["id"]) == []

    def test_announce_with_no_price_tiers_is_refused(self):
        """A show may not be announced to the public until it owns a price
        structure, so an announcement against a booking with no tiers at all is
        refused and the booking stays held with no doors instant.

        "the booking must own at least one price tier, an empty price structure being refused with `ERR_NO_TICKET_SCALES`"

        Design: Difficulty/boundary_precision_check/announce_empty_price_structure_zero_versus_one_scale
        """
        scenario = setup_accepted_booking()
        prepare_completed_advance(scenario)

        response = api_client.announce_show_booking(
            scenario["booking"]["id"],
            build_announce_payload(DOORS_TIME_UTC),
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_NO_TICKET_SCALES.value)

        booking = get_booking(scenario["booking"]["id"])
        assert booking["booking_status"] == "DATE_HELD"
        assert booking["doors_time_utc"] is None

    def test_announce_with_exactly_one_price_tier_succeeds(self):
        """One price tier is a sufficient price structure: the same announcement
        lands, the doors instant is written and the tier's potential is the whole
        show's potential.

        "On success the booking moves `DATE_HELD → ANNOUNCED`, `doors_time_utc` is written from the request, `announced_at_utc` is stamped from the logical clock"

        Design: Difficulty/boundary_precision_check/announce_empty_price_structure_zero_versus_one_scale
        """
        scenario = setup_accepted_booking()
        prepare_completed_advance(scenario)
        scale = add_ticket_scale(scenario["booking"]["id"], **RESERVED_GOLD_2000)

        response = api_client.announce_show_booking(
            scenario["booking"]["id"],
            build_announce_payload(DOORS_TIME_UTC),
            FAIR_OPERATIONS_DIRECTOR_HEADERS,
        )
        booking = validate_success(response, expected_status=200)

        assert booking["booking_status"] == "ANNOUNCED"
        assert booking["doors_time_utc"] == DOORS_TIME_UTC
        assert booking["ticketing_status"] == "ON_SALE"
        assert scale["scale_gross_potential_cents"] == 11866075
        assert booking["gross_potential_cents"] == 11866075


class TestRefundBatchRestoresSeatInventory:
    """An equal and opposite refund returns the tier and the show to their start."""

    def test_sale_batch_moves_seat_counts_and_paid_attendance(self):
        """A sale batch on a paid channel adds its units to the tier and, one hop
        further out, to the show's paid attendance.

        "the booking's `paid_attendance` is recomputed across all of the booking's tiers as the net units contributed by batches whose `counts_toward_paid_attendance` reads true"

        Design: Difficulty/compensating_invariant/refund_batch_restores_seat_counts_and_paid_attendance
        """
        scenario = setup_announced_booking(scale_overrides=RESERVED_GOLD_2000)

        record_sales_batch(scenario["ticket_scale"]["id"], "SALE", 500, "ONLINE")

        scale = get_ticket_scale(scenario["ticket_scale"]["id"])
        assert scale["sold_seats"] == 500
        assert scale["available_seats"] == 1500
        assert_seat_identity(scale)
        assert get_booking(scenario["booking"]["id"])["paid_attendance"] == 500

    def test_equal_refund_batch_restores_seat_counts_and_paid_attendance(self):
        """Because both ledgers are recomputed as sales less refunds, a refund of
        exactly the units sold returns the tier's sold count to zero, its
        availability to the full allotment and the show's paid attendance to zero.

        "The tier's `sold_seats` is recomputed as the sum of the `quantity` values of its `SALE` batches less the sum of the `quantity` values of its `REFUND` batches."

        Design: Difficulty/compensating_invariant/refund_batch_restores_seat_counts_and_paid_attendance
        """
        scenario = setup_announced_booking(scale_overrides=RESERVED_GOLD_2000)

        record_sales_batch(scenario["ticket_scale"]["id"], "SALE", 500, "ONLINE")
        record_sales_batch(scenario["ticket_scale"]["id"], "REFUND", 500, "ONLINE")

        scale = get_ticket_scale(scenario["ticket_scale"]["id"])
        assert scale["sold_seats"] == 0
        assert scale["available_seats"] == 2000
        assert scale["available_seats"] == scale["allotment_seats"]
        assert_seat_identity(scale)

        booking = get_booking(scenario["booking"]["id"])
        assert booking["paid_attendance"] == 0
        assert booking["ticketing_status"] == "ON_SALE"

    def test_both_batches_survive_the_round_trip_as_append_only_history(self):
        """Nothing is deleted when a refund compensates a sale: both movements
        remain readable on the tier's batch history, and the tier's potential is
        a capacity figure that never moved with the sales at all.

        "Batches are append-only history: they carry `id` and `created_at` and neither `updated_at` nor `version`."

        Design: Difficulty/compensating_invariant/refund_batch_restores_seat_counts_and_paid_attendance
        """
        scenario = setup_announced_booking(scale_overrides=RESERVED_GOLD_2000)
        scale_id = scenario["ticket_scale"]["id"]

        sale = record_sales_batch(scale_id, "SALE", 500, "ONLINE")
        refund = record_sales_batch(scale_id, "REFUND", 500, "ONLINE")

        batches = list_sales_batches(scale_id)
        assert len(batches) == 2
        assert {batch["id"] for batch in batches} == {sale["id"], refund["id"]}
        assert {batch["batch_kind"] for batch in batches} == {"SALE", "REFUND"}
        for batch in batches:
            assert_append_only_common_fields(batch)
            assert batch["quantity"] == 500

        assert get_ticket_scale(scale_id)["scale_gross_potential_cents"] == 11866075
