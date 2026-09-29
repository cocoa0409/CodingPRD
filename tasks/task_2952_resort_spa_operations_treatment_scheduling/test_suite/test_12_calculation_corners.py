"""Calculation corners: the room-class multiplier table and both ends of the peak
band, the loyalty table with an inert cap and floor, the four-rung automatic
assignment ladder, the two faces of an empty candidate set, both settlement grace
edges, the half-open utilisation window and the three cancellation bands.
"""

from test_helpers import (
    ApiErrorId,
    assert_balance_equals_posting_sum,
    assert_folio_rows,
    assert_list_count,
    assert_percent_2dp,
    assert_pool_conserved,
    assert_same_instant,
    assert_settlement_row,
    assert_state_pair,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CANON_START_AT
from test_helpers import factories as f
from test_helpers import fixtures as fx

# The DRY60 menu row: 60 minutes, DRY, SWEDISH / BASIC, 18,000 cents of list
# price, with `contraindication_codes` and `high_demand` both omitted so the
# server mints an empty array and false.
DRY60_TYPE = {
    "code": "DRY60",
    "name": "Swedish Dry 60",
    "duration_minutes": 60,
    "room_class_required": "DRY",
    "required_skill_code": "SWEDISH",
    "required_scope_level": "BASIC",
    "base_price_cents": 18000,
    "contraindication_codes": None,
    "high_demand": None,
}
DRY_ROOM = {"room_class": "DRY", "turnover_buffer_minutes": 15,
            "hourly_fixed_cost_cents": 2500}
SWEDISH_BASIC = {"skill_code": "SWEDISH", "scope_level": "BASIC"}
NO_LOYALTY = {"loyalty_tier": None}

DRY_LIST_PRICE_CENTS = 18000
DRY_PRICE_FLOOR_CENTS = 14400        # round_half_up(18000 * 8000 / 10000)
WET_QUOTE_CENTS = 20700              # round_half_up(18000 * 11500 / 10000)
COUPLES_QUOTE_CENTS = 22500          # round_half_up(18000 * 12500 / 10000)
PEAK_QUOTE_CENTS = 20700             # 18000 + round_half_up(18000 * 1500 / 10000)
MAX_DISCOUNT_CENTS = 4000
HYDRO_OFF_PEAK_QUOTE_CENTS = 42900   # 39000 + round_half_up(39000 * 1000 / 10000)


def _dry_world(room_codes=("DRY-1",), **kwargs):
    """The DRY60 world: one DRY room at 2,500 cents an hour with a 15-minute
    turnover buffer, one SENIOR therapist certified SWEDISH / BASIC and one
    loyalty_tier NONE guest holding a SCREENED_CLEAR consented intake form."""
    return fx.build_world(
        room_codes=room_codes, treatment_type_overrides=DRY60_TYPE,
        room_overrides=DRY_ROOM, certification_overrides=SWEDISH_BASIC,
        guest_overrides=NO_LOYALTY, **kwargs)


# ---------------------------------------------------------------------------
# The room-class multiplier table and the peak band
# ---------------------------------------------------------------------------

def test_the_three_room_class_multipliers_are_read_off_one_base_price():
    """One 18,000-cent list price, three room classes, three different quotes.

    PRD §3.5: "First, the room-adjusted amount is the treatment's
    `base_price_cents` multiplied by the room-class multiplier and divided by ten
    thousand, rounded half up to a whole cent; the multipliers are 10,000 basis
    points for a `DRY` room (no adjustment at all), 11,500 for `WET`, 13,000 for
    `HYDRO` and 12,500 for `COUPLES`."

    PRD §3.5: "The quote reads exactly three records — the booked treatment type,
    the booked room (its `room_class` is read even though that class must already
    equal `room_class_required`) and the guest (its `loyalty_tier` only) — and no
    other appointment participates."

    Design: Corner/calculations/price_quote_room_class_table_and_peak_hour_boundary
    """
    world = _dry_world()
    assert world.guest["loyalty_tier"] == "NONE", (
        "loyalty_tier was omitted at registration, so the discount row is 0 and "
        "the multiplier is the only moving part")

    wet_type = fx.create_treatment_type(
        **dict(DRY60_TYPE, code="WET60", name="Thalasso Wet 60",
               room_class_required="WET"))
    couples_type = fx.create_treatment_type(
        **dict(DRY60_TYPE, code="CPL60", name="Couples Ritual 60",
               room_class_required="COUPLES"))
    wet_room = fx.create_room(code="WET-1", room_class="WET",
                              turnover_buffer_minutes=15,
                              hourly_fixed_cost_cents=3000)
    couples_room = fx.create_room(code="CPL-1", room_class="COUPLES",
                                  capacity_guests=2, turnover_buffer_minutes=20,
                                  hourly_fixed_cost_cents=3500)

    quotes = {}
    for label, treatment_type_id, room_id, start_at in (
            ("DRY", world.treatment_type_id, world.room_id,
             "2026-08-10T08:00:00.000Z"),
            ("WET", wet_type["id"], wet_room["id"], "2026-08-10T10:00:00.000Z"),
            ("COUPLES", couples_type["id"], couples_room["id"],
             "2026-08-10T12:00:00.000Z")):
        booked = fx.book_appointment(world.guest_id, treatment_type_id, room_id,
                                     start_at, world.therapist_id)
        assert booked["high_demand_slot"] is False, (
            f"the {label} probe sits outside the peak band and its type is not "
            f"high_demand, so no surcharge may enter the quote")
        assert booked["quoted_price_cents"] > DRY_PRICE_FLOOR_CENTS, (
            f"the {label} quote must sit above the 14400c floor, which is inert "
            f"here")
        quotes[label] = booked["quoted_price_cents"]

    assert quotes == {"DRY": DRY_LIST_PRICE_CENTS, "WET": WET_QUOTE_CENTS,
                      "COUPLES": COUPLES_QUOTE_CENTS}, (
        f"the three multiplier rows must produce 18000, 20700 and 22500, "
        f"got {quotes}")


def test_the_peak_band_includes_sixteen_hundred_and_excludes_twenty_hundred():
    """Four quotes an hour apart around the two ends of the band.

    PRD §3.5: "a peak component of 1,500 basis points applies when the UTC hour of
    the submitted `start_at` is at least 16 and less than 20 (this is the UTC hour
    of the submitted instant and never a local-time conversion) and is otherwise
    zero"

    PRD §3.5: "`high_demand_slot` is true when either the treatment type's
    `high_demand` flag is true or the UTC hour of `start_at` is at least 16 and
    less than 20 — the four-hour late-afternoon peak — and false otherwise."

    Design: Corner/calculations/price_quote_room_class_table_and_peak_hour_boundary
    """
    world = _dry_world()
    for day in ("11", "12", "13", "14"):
        fx.add_shift_block(world.therapist_id,
                           start_at=f"2026-08-{day}T08:00:00.000Z",
                           end_at=f"2026-08-{day}T22:00:00.000Z")

    probes = (
        ("2026-08-11T15:00:00.000Z", DRY_LIST_PRICE_CENTS, False),
        ("2026-08-12T16:00:00.000Z", PEAK_QUOTE_CENTS, True),
        ("2026-08-13T19:00:00.000Z", PEAK_QUOTE_CENTS, True),
        ("2026-08-14T20:00:00.000Z", DRY_LIST_PRICE_CENTS, False),
    )
    for start_at, expected_quote, expected_flag in probes:
        booked = fx.book_appointment(world.guest_id, world.treatment_type_id,
                                     world.room_id, start_at, world.therapist_id)
        assert booked["quoted_price_cents"] == expected_quote, (
            f"{start_at} must quote {expected_quote}, got "
            f"{booked['quoted_price_cents']}")
        assert booked["high_demand_slot"] is expected_flag, (
            f"{start_at} must report high_demand_slot {expected_flag}, got "
            f"{booked['high_demand_slot']}")

    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 4,
                      "appointments across the four probe days")


def test_the_three_paying_loyalty_rows_clear_both_the_cap_and_the_floor():
    """SILVER, GOLD and PLATINUM on one identical off-peak DRY booking.

    PRD §3.5: "The raw discount is the subtotal multiplied by the loyalty rate and
    divided by ten thousand, rounded half up, where the loyalty rate is 0 basis
    points for `NONE`, 500 for `SILVER`, 1,000 for `GOLD` and 1,500 for
    `PLATINUM`; the applied discount is the smaller of that raw figure and the
    absolute discount cap of 4,000 cents, so no single treatment may be discounted
    by more than 40 units of currency however generous the tier."

    PRD §3.5: "The price floor is the treatment's `base_price_cents` multiplied by
    8,000 basis points and divided by ten thousand, rounded half up — eighty
    percent of list."

    Design: Corner/calculations/price_quote_loyalty_table_rows_and_inert_price_floor
    """
    world = _dry_world(with_guest=False)
    probes = (
        ("SILVER", "Ava Silver", "2026-08-10T10:00:00.000Z", 17100),
        ("GOLD", "Ben Gold", "2026-08-10T12:00:00.000Z", 16200),
        ("PLATINUM", "Cleo Platinum", "2026-08-10T14:00:00.000Z", 15300),
    )
    for tier, full_name, start_at, expected_quote in probes:
        guest = fx.create_guest(full_name=full_name, loyalty_tier=tier)
        assert guest["loyalty_tier"] == tier
        fx.screened_intake(guest["id"], guest["version"])

        booked = fx.book_appointment(guest["id"], world.treatment_type_id,
                                     world.room_id, start_at, world.therapist_id)
        assert_state_pair(booked, "REQUESTED", "PENDING")
        assert booked["quoted_price_cents"] == expected_quote, (
            f"the {tier} row must quote {expected_quote}, got "
            f"{booked['quoted_price_cents']}")

        applied_discount = DRY_LIST_PRICE_CENTS - booked["quoted_price_cents"]
        assert applied_discount < MAX_DISCOUNT_CENTS, (
            f"the {tier} raw discount {applied_discount} is below the 4000c cap, "
            f"so the cap is inert and the subtotal minus the raw discount is the "
            f"quote")
        assert booked["quoted_price_cents"] > DRY_PRICE_FLOOR_CENTS, (
            f"the {tier} quote must sit above the 14400c floor, which never "
            f"engages here")


# ---------------------------------------------------------------------------
# The automatic assignment ladder
# ---------------------------------------------------------------------------

def _four_candidate_world():
    """Four credentialled SWEDISH therapists created at four distinct logical
    instants — A (5200c/h, BASIC), C (5200c/h, BASIC), B (4800c/h, ADVANCED) and
    D (4000c/h, BASIC), in that creation order — all available 08:00-22:00Z on
    2026-08-10. The clock is stepped between the four inserts so that `created_at`
    strictly orders them and the fourth ranking key has something to compare."""
    world = _dry_world(therapist_names=())
    roster = (
        ("A", "2026-08-03T09:00:00.000Z", 5200, "BASIC"),
        ("C", "2026-08-03T09:05:00.000Z", 5200, "BASIC"),
        ("B", "2026-08-03T09:10:00.000Z", 4800, "ADVANCED"),
        ("D", "2026-08-03T09:15:00.000Z", 4000, "BASIC"),
    )
    for index, (label, clock, hourly_cost, scope_level) in enumerate(roster):
        fx.set_clock(clock)
        therapist = fx.create_therapist(full_name=f"Therapist {label}",
                                        base_hourly_cost_cents=hourly_cost)
        world.therapists[label] = therapist
        fx.verified_license(therapist["id"], submit_user=f"co-s{index}",
                            review_user=f"co-r{index}",
                            license_number=f"HI-LMT-44{index}0")
        fx.grant_certification(therapist["id"], user=f"co-r{index}",
                               skill_code="SWEDISH", scope_level=scope_level)
        fx.add_shift_block(therapist["id"])
    return world


def test_four_auto_bookings_walk_the_ranking_ladder_rung_by_rung():
    """Scope, then cost, then tenure, and minutes-on-date over all three.

    PRD §3.5: "Survivors are then ranked, and the ranking is applied in a fixed
    sequence of four keys."

    PRD §3.5: "The first key is the therapist's committed minutes on the requested
    calendar date, taken in ascending order so that the least-loaded therapist
    wins: that figure is the sum of `scheduled_duration_minutes` over that
    therapist's appointments whose `schedule_status` is `REQUESTED`, `CONFIRMED`,
    `CHECKED_IN`, `IN_SERVICE` or `COMPLETED` and whose `start_at` falls on the
    same UTC calendar date as the requested `start_at` — a per-date figure that is
    deliberately not the same thing as the therapist's lifetime
    `assigned_minutes_total`."

    PRD §3.5: "The second key is the scope rank of the matching certification
    grant, taken in descending order, so an `ADVANCED` holder outranks a `BASIC`
    holder at equal load. The third key is `base_hourly_cost_cents` in ascending
    order, so the cheaper therapist wins at equal load and equal scope. The fourth
    and final tie-break is the therapist's `created_at` in ascending order, so the
    longest-tenured record wins."

    Design: Corner/calculations/auto_assignment_ranking_ladder_and_created_at_tie_break
    """
    world = _four_candidate_world()
    picked = []
    for start_at in ("2026-08-10T08:00:00.000Z", "2026-08-10T10:00:00.000Z",
                     "2026-08-10T12:00:00.000Z", "2026-08-10T14:00:00.000Z"):
        booked = validate_success(api_client.create_appointment(
            f.appointment_payload(world.guest_id, world.treatment_type_id,
                                  world.room_id, start_at),
            fx.COORDINATOR), 201)
        assert booked["assignment_mode"] == "AUTO", (
            "therapist_id was omitted, so the server chose the therapist")
        assert booked["therapist_id"] is not None, (
            "therapist_id is never null on a successfully created appointment")
        assert booked["quoted_price_cents"] == DRY_LIST_PRICE_CENTS
        picked.append(booked["therapist_id"])

    expected = [world.therapist_of("B"), world.therapist_of("D"),
                world.therapist_of("A"), world.therapist_of("C")]
    assert picked == expected, (
        "the ladder must pick B on scope, D on cost, A on tenure and C on "
        f"minutes-on-date; got {picked} instead of {expected}")

    for label in ("A", "B", "C", "D"):
        assert world.fetch_therapist(label)["assigned_minutes_total"] == 60, (
            f"therapist {label} holds exactly one 60-minute appointment")


def _basic_only_world():
    """The canonical HYDRO90 world — 90 minutes, HYDROTHERAPY / ADVANCED, 30,000
    cents of list price, high_demand true, in a HYDRO room with a 30-minute
    turnover buffer — whose only therapist holds a BASIC grant."""
    return fx.build_world(certification_overrides={"scope_level": "BASIC"},
                          guest_overrides=NO_LOYALTY)


def test_the_same_unbookable_slot_answers_two_different_refusals():
    """Omitting the therapist empties the pool; naming them hits the scope rule.

    PRD §3.5: "If the filter admits nobody at all, the booking is rejected with
    `ERR_NO_ELIGIBLE_THERAPIST`."

    PRD §3.5: "must hold an `ACTIVE`, unexpired certification grant for the
    treatment's `required_skill_code` at or above the required scope rank
    (`ERR_SCOPE_OF_PRACTICE_VIOLATION`), and must themselves be `ACTIVE`
    (`ERR_THERAPIST_NOT_ACTIVE`)."

    Design: Corner/calculations/auto_assignment_empty_candidate_set_and_scope_contrast
    """
    world = _basic_only_world()

    auto = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, CANON_START_AT),
        fx.COORDINATOR)
    validate_error(auto, ApiErrorId.ERR_NO_ELIGIBLE_THERAPIST.value, 409)

    explicit = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, CANON_START_AT, world.therapist_id),
        fx.COORDINATOR)
    validate_error(explicit, ApiErrorId.ERR_SCOPE_OF_PRACTICE_VIOLATION.value, 409)

    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after both refusals")
    assert world.fetch_room()["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0


def test_a_break_block_empties_the_candidate_pool_for_that_slot_alone():
    """The pool is per-slot: the same therapist is eligible two hours earlier.

    PRD §3.5: "no `BREAK` or `ADMIN` block of theirs intersects that interval with
    both intervals closed; and no appointment of theirs in `REQUESTED`,
    `CONFIRMED`, `CHECKED_IN` or `IN_SERVICE` intersects it with both intervals
    closed."

    PRD §3.5: "a high-demand component of 1,000 basis points applies when the
    treatment's `high_demand` is true and is otherwise zero, and the effective
    surcharge rate is the smaller of their sum and the surcharge cap of 2,000 basis
    points"

    Design: Corner/calculations/auto_assignment_empty_candidate_set_and_scope_contrast
    """
    world = _basic_only_world()
    fx.grant_certification(world.therapist_id, user="co-6",
                           scope_level="ADVANCED", granted_on="2024-06-01")
    fx.add_shift_block(world.therapist_id, block_type="BREAK",
                       start_at="2026-08-10T16:30:00.000Z",
                       end_at="2026-08-10T18:00:00.000Z")

    blocked = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, CANON_START_AT),
        fx.COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_NO_ELIGIBLE_THERAPIST.value, 409)

    accepted = validate_success(api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, "2026-08-10T09:00:00.000Z"),
        fx.COORDINATOR), 201)
    assert accepted["assignment_mode"] == "AUTO"
    assert accepted["therapist_id"] == world.therapist_id
    assert accepted["quoted_price_cents"] == HYDRO_OFF_PEAK_QUOTE_CENTS, (
        "09:00Z is outside the peak band, so only the 1000bp high-demand "
        "component surcharges the 39000c room-adjusted amount")

    assert world.fetch_room()["booked_minutes_total"] == 120
    assert world.fetch_therapist()["assigned_minutes_total"] == 90
    assert world.fetch_guest()["booking_privilege"] == "OPEN"
    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 0,
        "guest folio postings after two refusals and one accepted booking")


# ---------------------------------------------------------------------------
# The settlement grace bands
# ---------------------------------------------------------------------------

PROVISIONAL_DRY_ROW = {
    "basis_duration_minutes": 60,
    "realized_price_cents": 18000,
    "retail_revenue_cents": 0,
    "service_charge_bp": 1800,
    "service_charge_pool_cents": 3240,
    "gratuity_cents": 0,
    "folio_total_cents": 21240,
}
# actual 65 == scheduled + OVERTIME_GRACE_MINUTES: zero overtime blocks.
FINAL_ROW_65 = {
    "basis_duration_minutes": 65,
    "realized_price_cents": 18000,
    "retail_revenue_cents": 0,
    "service_charge_bp": 1800,
    "service_charge_pool_cents": 3240,
    "gratuity_cents": 0,
    "distributable_pool_cents": 3240,
    "therapist_share_cents": 1944,
    "support_pool_cents": 810,
    "house_share_cents": 486,
    "therapist_commission_cents": 6840,
    "retail_commission_cents": 0,
    "labor_cost_cents": 14417,
    "room_fixed_cost_cents": 2708,
    "folio_total_cents": 21240,
    "net_margin_cents": 875,
}
# actual 66: one minute past the grace buys one whole 15-minute block.
FINAL_ROW_66 = {
    "basis_duration_minutes": 66,
    "realized_price_cents": 20500,
    "retail_revenue_cents": 0,
    "service_charge_bp": 1800,
    "service_charge_pool_cents": 3690,
    "gratuity_cents": 0,
    "distributable_pool_cents": 3690,
    "therapist_share_cents": 2214,
    "support_pool_cents": 923,
    "house_share_cents": 553,
    "therapist_commission_cents": 7790,
    "retail_commission_cents": 0,
    "labor_cost_cents": 15724,
    "room_fixed_cost_cents": 2750,
    "folio_total_cents": 24190,
    "net_margin_cents": 2026,
}
# actual 55 == scheduled - SHORTFALL_GRACE_MINUTES: no shortfall credit.
FINAL_ROW_55 = {
    "basis_duration_minutes": 55,
    "realized_price_cents": 18000,
    "retail_revenue_cents": 0,
    "service_charge_bp": 1800,
    "service_charge_pool_cents": 3240,
    "gratuity_cents": 0,
    "distributable_pool_cents": 3240,
    "therapist_share_cents": 1944,
    "support_pool_cents": 810,
    "house_share_cents": 486,
    "therapist_commission_cents": 6840,
    "retail_commission_cents": 0,
    "labor_cost_cents": 13551,
    "room_fixed_cost_cents": 2292,
    "folio_total_cents": 21240,
    "net_margin_cents": 2157,
}
# actual 54: one minute past the shortfall grace credits six missing minutes.
FINAL_ROW_54 = {
    "basis_duration_minutes": 54,
    "realized_price_cents": 16200,
    "retail_revenue_cents": 0,
    "service_charge_bp": 1800,
    "service_charge_pool_cents": 2916,
    "gratuity_cents": 0,
    "distributable_pool_cents": 2916,
    "therapist_share_cents": 1750,
    "support_pool_cents": 729,
    "house_share_cents": 437,
    "therapist_commission_cents": 6156,
    "retail_commission_cents": 0,
    "labor_cost_cents": 12586,
    "room_fixed_cost_cents": 2250,
    "folio_total_cents": 19116,
    "net_margin_cents": 1364,
}
PROVISIONAL_FOLIO_TOTAL_CENTS = 21240
FOUR_SETTLEMENT_BALANCE_CENTS = 85786   # 4 * 21240 + 0 + 2950 + 0 - 2124


def _confirmed_dry_slots(world, hours):
    """One CONFIRMED x CLEARED 60-minute appointment per named UTC hour on
    2026-08-10, all in the same DRY room and all quoted at 18000."""
    slots = {}
    for hour in hours:
        booked = fx.book_appointment(
            world.guest_id, world.treatment_type_id, world.room_id,
            f"2026-08-10T{hour:02d}:00:00.000Z", world.therapist_id)
        assert booked["quoted_price_cents"] == DRY_LIST_PRICE_CENTS
        slots[hour] = fx.confirm(booked["id"])["id"]
    return slots


def _deliver(world, appointment_id, hour, actual_duration_minutes):
    """Advance the clock to the slot, check in, start and complete."""
    fx.set_clock(f"2026-08-10T{hour:02d}:00:00.000Z")
    fx.check_in(appointment_id)
    fx.start_service(appointment_id, world.therapist_id)
    return fx.complete_service(appointment_id, world.therapist_id,
                               actual_duration_minutes)


def _settle(world, appointment_id):
    version = world.fetch_appointment(appointment_id)["version"]
    return validate_success(api_client.create_settlement(
        appointment_id, f.settlement_payload(version), fx.DIRECTOR), 201)


def _adjustment_of(appointment_id):
    postings = validate_success(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR))
    rows = [row for row in postings if row["kind"] == "SETTLEMENT_ADJUSTMENT"]
    assert len(rows) == 1, (
        f"exactly one SETTLEMENT_ADJUSTMENT is posted per final cut, got {rows}")
    return rows[0]["amount_cents"]


def test_the_overtime_grace_edge_is_free_and_one_minute_past_it_costs_a_block():
    """65 delivered minutes charge nothing; 66 buy a whole 15-minute block.

    PRD §3.9: "Overtime is granted a five-minute grace: take the delivered minutes
    less the scheduled minutes less 5, treat any non-positive result as zero,
    divide by 15 and round **up** to a whole number of blocks, then charge 2,500
    cents per block."

    PRD §3.9: "Under the provisional variant, `basis_duration_minutes` is the
    appointment's `scheduled_duration_minutes` and `realized_price_cents` is
    exactly the frozen `quoted_price_cents` — there is no overtime charge, no
    shortfall credit, and `gratuity_cents` on the row is 0 because a gratuity is
    only captured at completion."

    Design: Corner/calculations/settlement_overtime_and_shortfall_grace_band_boundaries
    """
    world = _dry_world()
    slots = _confirmed_dry_slots(world, (8, 10))

    _deliver(world, slots[8], 8, 65)
    provisional = assert_list_count(
        api_client.list_settlements(slots[8], fx.DIRECTOR), 1,
        "settlement rows before the final cut")[0]
    assert_settlement_row(provisional, PROVISIONAL_DRY_ROW, "provisional row")

    at_the_edge = _settle(world, slots[8])
    assert at_the_edge["variant"] == "FINAL" and at_the_edge["status"] == "FINALIZED"
    assert_settlement_row(at_the_edge, FINAL_ROW_65, "final row at 65 minutes")
    assert_pool_conserved(at_the_edge)
    assert _adjustment_of(slots[8]) == 0, (
        "the FINAL folio total equals the already-posted TREATMENT charge, and the "
        "zero row is still posted")

    _deliver(world, slots[10], 10, 66)
    past_the_edge = _settle(world, slots[10])
    assert_settlement_row(past_the_edge, FINAL_ROW_66, "final row at 66 minutes")
    assert_pool_conserved(past_the_edge)
    assert _adjustment_of(slots[10]) == 2950, (
        "24190 less the 21240 already posted against this appointment")
    assert world.fetch_appointment(slots[10])["realized_price_cents"] == 20500, (
        "the final cut writes the row's realized_price_cents onto the appointment")


def test_the_house_share_is_the_residual_and_never_the_nominal_rate():
    """3,690 splits 2,214 / 923 / 553 — the residual is 553, not 554.

    PRD §3.9: "and `house_share_cents` is whatever remains of the pool after both
    of those are removed. The house's nominal rate is 1,500 basis points, but the
    house share is **never** computed by applying that rate — it is always the
    remainder, so that the three buckets sum to `distributable_pool_cents` to the
    cent regardless of how the two roundings fell."

    PRD §3.9: "`labor_cost_cents` is the therapist's `base_hourly_cost_cents`
    multiplied by `basis_duration_minutes` and divided by 60, rounded half up, and
    then increased by `therapist_commission_cents`, `therapist_share_cents` and
    `retail_commission_cents`."

    Design: Corner/calculations/settlement_overtime_and_shortfall_grace_band_boundaries
    """
    world = _dry_world()
    slots = _confirmed_dry_slots(world, (8,))
    _deliver(world, slots[8], 8, 66)
    row = _settle(world, slots[8])

    assert row["support_pool_cents"] == 923, (
        "922.5 rounds half up to 923, which is what makes the residual visible")
    assert row["house_share_cents"] == 553, (
        f"the house takes the remainder 3690 - 2214 - 923; applying 1500bp to the "
        f"pool would give 554, got {row['house_share_cents']}")
    assert_pool_conserved(row)
    assert row["labor_cost_cents"] == 15724, (
        "round_half_up(5200 * 66 / 60) == 5720 plus the 7790 commission and the "
        "2214 therapist share, all on the delivered basis rather than the "
        "scheduled one")


def test_the_shortfall_grace_edge_is_free_and_one_minute_past_it_credits_back():
    """55 delivered minutes credit nothing; 54 credit six missing minutes.

    PRD §3.9: "A shortfall has its own five-minute grace: when the delivered
    minutes are at least the scheduled minutes less 5, the shortfall credit is
    zero; otherwise the credit is the frozen `quoted_price_cents` multiplied by the
    missing minutes and divided by the scheduled minutes, rounded half up."

    PRD §3.9: "It posts a folio charge of `kind` `SETTLEMENT_ADJUSTMENT` whose
    `amount_cents` is the final row's `folio_total_cents` less the sum of
    `amount_cents` over every folio posting already recorded against that
    appointment — a figure that is negative whenever the delivered service came in
    cheaper than the provisional estimate."

    Design: Corner/calculations/settlement_overtime_and_shortfall_grace_band_boundaries
    """
    world = _dry_world()
    slots = _confirmed_dry_slots(world, (12, 14))

    _deliver(world, slots[12], 12, 55)
    at_the_edge = _settle(world, slots[12])
    assert_settlement_row(at_the_edge, FINAL_ROW_55, "final row at 55 minutes")
    assert_pool_conserved(at_the_edge)
    assert _adjustment_of(slots[12]) == 0

    _deliver(world, slots[14], 14, 54)
    past_the_edge = _settle(world, slots[14])
    assert_settlement_row(past_the_edge, FINAL_ROW_54, "final row at 54 minutes")
    assert_pool_conserved(past_the_edge)
    assert _adjustment_of(slots[14]) == -2124, (
        "19116 less the 21240 already posted is a negative correction")

    postings = assert_list_count(
        api_client.list_appointment_folio_charges(slots[14], fx.DIRECTOR), 2,
        "postings on the short-delivered appointment")
    kinds = sorted(row["kind"] for row in postings)
    assert kinds == ["SETTLEMENT_ADJUSTMENT", "TREATMENT"], (
        f"the negative correction is an additional posting, not an edit of the "
        f"TREATMENT row; got {kinds}")


def test_four_settlements_leave_the_folio_at_the_exact_sum_of_its_postings():
    """Two grace edges and two overruns reconcile to one balance.

    PRD §3.9: "And it recomputes the guest's `folio_balance_cents` as the exact sum
    of the guest's postings, incrementing the guest's `version` by 1."

    PRD §3.9: "It transitions the appointment's provisional row
    `PROVISIONAL → SUPERSEDED`."

    Design: Corner/calculations/settlement_overtime_and_shortfall_grace_band_boundaries
    """
    world = _dry_world()
    slots = _confirmed_dry_slots(world, (8, 10, 12, 14))
    for hour, actual_duration_minutes in ((8, 65), (10, 66), (12, 55), (14, 54)):
        _deliver(world, slots[hour], hour, actual_duration_minutes)
        _settle(world, slots[hour])

    guest = world.fetch_guest()
    assert guest["folio_balance_cents"] == FOUR_SETTLEMENT_BALANCE_CENTS, (
        f"four provisional charges of {PROVISIONAL_FOLIO_TOTAL_CENTS} plus "
        f"adjustments 0, 2950, 0 and -2124, got {guest['folio_balance_cents']}")
    postings = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 8,
        "guest folio postings")
    assert_balance_equals_posting_sum(guest, postings)

    rows = assert_list_count(api_client.list_settlements(slots[10], fx.DIRECTOR),
                             2, "settlement rows on the overrun appointment")
    assert [row["variant"] for row in rows] == ["PROVISIONAL", "FINAL"], (
        "an appointment's rows are returned with the provisional row first")
    assert [row["status"] for row in rows] == ["SUPERSEDED", "FINALIZED"]
    assert rows[0]["folio_total_cents"] == PROVISIONAL_FOLIO_TOTAL_CENTS, (
        "the superseded row's computed money fields freeze where they stood")


# ---------------------------------------------------------------------------
# The half-open room-utilisation window
# ---------------------------------------------------------------------------

REPORT_FROM_AT = "2026-08-10T08:00:00.000Z"
REPORT_TO_AT = "2026-08-11T08:00:00.000Z"
REPORT_WINDOW_MINUTES = 1440


def _deliver_at(world, appointment_id, clock, actual_duration_minutes):
    fx.set_clock(clock)
    fx.check_in(appointment_id)
    fx.start_service(appointment_id, world.therapist_id)
    return fx.complete_service(appointment_id, world.therapist_id,
                               actual_duration_minutes)


def _report_world():
    """Four bookings in DRY-1 and one idle DRY-2 room: b1 is COMPLETED and
    FINALIZED, b2 is COMPLETED with its settlement still PROVISIONAL, b3 is
    CANCELLED and b4 is COMPLETED but starts exactly at the exclusive `to_at`."""
    world = _dry_world()
    world.rooms["DRY-2"] = fx.create_room(code="DRY-2", room_class="DRY",
                                          turnover_buffer_minutes=15,
                                          hourly_fixed_cost_cents=2000)
    fx.add_shift_block(world.therapist_id,
                       start_at="2026-08-11T08:00:00.000Z",
                       end_at="2026-08-11T22:00:00.000Z")

    slots = {}
    for key, start_at in (("b1", "2026-08-10T08:00:00.000Z"),
                          ("b2", "2026-08-10T10:00:00.000Z"),
                          ("b3", "2026-08-10T12:00:00.000Z"),
                          ("b4", "2026-08-11T08:00:00.000Z")):
        slots[key] = fx.book_appointment(
            world.guest_id, world.treatment_type_id, world.room_id, start_at,
            world.therapist_id)["id"]
    for key in ("b1", "b2", "b4"):
        fx.confirm(slots[key])
    cancelled = validate_success(api_client.cancel_appointment(
        slots["b3"], f.cancel_payload("guest itinerary change"), fx.COORDINATOR))
    assert cancelled["schedule_status"] == "CANCELLED"

    _deliver_at(world, slots["b1"], "2026-08-10T08:00:00.000Z", 65)
    _settle(world, slots["b1"])
    _deliver_at(world, slots["b2"], "2026-08-10T10:00:00.000Z", 55)
    _deliver_at(world, slots["b4"], "2026-08-11T08:00:00.000Z", 60)
    return world, slots


def _room_row(report, room_id):
    rows = [row for row in report["rooms"] if row["room_id"] == room_id]
    assert len(rows) == 1, f"expected exactly one row for {room_id}, got {rows}"
    return rows[0]


def test_the_utilisation_input_set_is_completed_rows_inside_the_half_open_window():
    """A cancellation and a booking starting exactly at `to_at` both drop out.

    PRD §3.10: "For each room the report takes only that room's appointments whose
    `schedule_status` is `COMPLETED` and whose `start_at` is at or after `from_at`
    and strictly before `to_at`; appointments in `REQUESTED`, `CONFIRMED`,
    `CHECKED_IN`, `IN_SERVICE`, `CANCELLED`, `LATE_CANCELLED` or `NO_SHOW` are all
    excluded."

    PRD §3.10: "`occupied_minutes` is the sum, over those appointments, of each
    one's `actual_duration_minutes` plus that room's `turnover_buffer_minutes`"

    PRD §3.10: "`utilization_pct` is `occupied_minutes` multiplied by 100 and
    divided by `window_minutes`, rounded half up to exactly two decimal places."

    Design: Corner/calculations/room_utilization_report_input_set_and_half_open_window
    """
    world, _slots = _report_world()

    report = validate_success(api_client.get_room_utilization_report(
        fx.DIRECTOR, params=f.report_window(REPORT_FROM_AT, REPORT_TO_AT)))
    assert_same_instant(report["from_at"], REPORT_FROM_AT, "from_at")
    assert_same_instant(report["to_at"], REPORT_TO_AT, "to_at")
    assert report["window_minutes"] == REPORT_WINDOW_MINUTES

    row = _room_row(report, world.room_id)
    assert row["room_code"] == "DRY-1"
    assert row["occupied_minutes"] == 150, (
        f"(65 + 15) + (55 + 15): the 08:00 row starting exactly at from_at is in, "
        f"the 08-11T08:00 row starting exactly at to_at is out and the cancelled "
        f"row contributes nothing; got {row['occupied_minutes']}")
    assert_percent_2dp(row["utilization_pct"], "utilization_pct")
    assert float(row["utilization_pct"]) == 10.42, (
        f"150 * 100 / 1440 == 10.4166… rounds half up to 10.42, got "
        f"{row['utilization_pct']}")


def test_only_finalized_settlement_rows_put_money_into_the_report():
    """A COMPLETED appointment with a provisional row adds minutes but no money.

    PRD §3.10: "The money figures come only from the `FINALIZED` settlement rows of
    those appointments — provisional, superseded and reversed rows are excluded —
    so `revenue_cents` is the sum over those rows of `realized_price_cents` plus
    `retail_revenue_cents`, and `labor_cost_cents` is the sum of their
    `labor_cost_cents`."

    PRD §3.10: "`room_fixed_cost_cents` is the room's `hourly_fixed_cost_cents`
    multiplied by `occupied_minutes` and divided by 60, rounded half up.
    `net_margin_cents` is `revenue_cents` less `labor_cost_cents` less
    `room_fixed_cost_cents`. `revenue_per_room_hour_cents` is `revenue_cents`
    multiplied by 60 and divided by `window_minutes`, rounded half up."

    Design: Corner/calculations/room_utilization_report_input_set_and_half_open_window
    """
    world, slots = _report_world()
    unsettled = assert_list_count(
        api_client.list_settlements(slots["b2"], fx.DIRECTOR), 1,
        "settlement rows on the unsettled appointment")[0]
    assert unsettled["status"] == "PROVISIONAL"

    report = validate_success(api_client.get_room_utilization_report(
        fx.DIRECTOR, params=f.report_window(REPORT_FROM_AT, REPORT_TO_AT)))
    row = _room_row(report, world.room_id)

    assert row["revenue_cents"] == 18000, (
        "only the FINALIZED row of the first appointment contributes revenue")
    assert row["labor_cost_cents"] == 14417, (
        "the same single FINALIZED row supplies the labour figure")
    assert row["room_fixed_cost_cents"] == 6250, (
        "round_half_up(2500 * 150 / 60) follows the occupied minutes, both "
        "turnover buffers included")
    assert row["net_margin_cents"] == -2667, (
        f"18000 - 14417 - 6250 is negative and is not clamped to 0, got "
        f"{row['net_margin_cents']}")
    assert row["revenue_per_room_hour_cents"] == 750, (
        "round_half_up(18000 * 60 / 1440) divides by the window hours, not by the "
        "occupied hours")


def test_an_idle_room_still_reports_and_the_room_filter_keeps_the_window():
    """DRY-2 saw no business and still appears, with or without the filter.

    PRD §3.10: "it requires `from_at` and `to_at`, accepts an optional `room_id` to
    scope it to a single room, and treats `to_at` as **exclusive**"

    PRD §3.10: "A room with no completed appointments in the window reports
    `occupied_minutes` 0, `utilization_pct` exactly `0.00` and every money field 0
    rather than being omitted."

    Design: Corner/calculations/room_utilization_report_input_set_and_half_open_window
    """
    world, _slots = _report_world()
    idle_room_id = world.room_of("DRY-2")

    unfiltered = validate_success(api_client.get_room_utilization_report(
        fx.DIRECTOR, params=f.report_window(REPORT_FROM_AT, REPORT_TO_AT)))
    assert len(unfiltered["rooms"]) == 2, (
        f"both rooms appear whether or not they saw business, got "
        f"{[row['room_code'] for row in unfiltered['rooms']]}")

    filtered = validate_success(api_client.get_room_utilization_report(
        fx.DIRECTOR, params=f.report_window(REPORT_FROM_AT, REPORT_TO_AT,
                                            room_id=idle_room_id)))
    assert len(filtered["rooms"]) == 1, (
        f"the room_id filter scopes the array to one room, got "
        f"{[row['room_code'] for row in filtered['rooms']]}")
    assert filtered["window_minutes"] == REPORT_WINDOW_MINUTES, (
        "the window is unaffected by the room filter")

    for report in (unfiltered, filtered):
        row = _room_row(report, idle_room_id)
        assert row["room_code"] == "DRY-2"
        assert row["occupied_minutes"] == 0
        assert_percent_2dp(row["utilization_pct"], "utilization_pct")
        assert float(row["utilization_pct"]) == 0.00
        for field in ("revenue_cents", "labor_cost_cents",
                      "room_fixed_cost_cents", "net_margin_cents",
                      "revenue_per_room_hour_cents"):
            assert row[field] == 0, (
                f"{field} on an idle room must be 0, got {row.get(field)!r}")


# ---------------------------------------------------------------------------
# The cancellation bands and the no-show grace on a low-demand slot
# ---------------------------------------------------------------------------

LATE_CANCEL_CHARGE_CENTS = 9000     # round_half_up(18000 * 5000 / 10000)
SHORT_NOTICE_CHARGE_CENTS = 18000   # round_half_up(18000 * 10000 / 10000)


def _low_demand_world(day):
    """The DRY60 world with the therapist available all day on 2026-08-`day`, so
    a 10:00Z slot is bookable outside the 16-20 peak band."""
    return _dry_world(shift_block_overrides={
        "start_at": f"2026-08-{day}T08:00:00.000Z",
        "end_at": f"2026-08-{day}T22:00:00.000Z"})


def test_both_the_free_cancel_edge_and_the_late_band_edge_are_inclusive():
    """24 hours out costs nothing; exactly 4 hours out costs half the quote.

    PRD §3.8: "When that figure is 24 hours or more — the boundary is inclusive —
    the appointment moves `REQUESTED → CANCELLED` or `CONFIRMED → CANCELLED`,
    `cancellation_charge_cents` is 0 and **no folio posting is made at all**."

    PRD §3.8: "The band rate is 5,000 basis points when the figure is 4 hours or
    more (again inclusive) and 10,000 basis points when it is under 4 hours, which
    includes every negative figure."

    PRD §3.8: "A guest below the threshold simply keeps `booking_privilege` at
    `OPEN` and none of the last three hops run."

    Design: Corner/calculations/cancellation_band_edges_and_no_show_grace_on_a_low_demand_slot
    """
    world = _low_demand_world("12")
    fx.add_shift_block(world.therapist_id,
                       start_at="2026-08-13T08:00:00.000Z",
                       end_at="2026-08-13T22:00:00.000Z")
    first = fx.book_appointment(world.guest_id, world.treatment_type_id,
                                world.room_id, "2026-08-12T10:00:00.000Z",
                                world.therapist_id)
    second = fx.book_appointment(world.guest_id, world.treatment_type_id,
                                 world.room_id, "2026-08-13T10:00:00.000Z",
                                 world.therapist_id)
    for booked in (first, second):
        assert booked["high_demand_slot"] is False, (
            "the type is not high_demand and 10:00Z is outside the peak band, so "
            "no uplift can reach either charge")
        assert booked["quoted_price_cents"] == DRY_LIST_PRICE_CENTS

    fx.set_clock("2026-08-11T10:00:00.000Z")
    free = validate_success(api_client.cancel_appointment(
        first["id"], f.cancel_payload("exactly 24 hours out"), fx.COORDINATOR))
    assert free["schedule_status"] == "CANCELLED"
    assert free["cancellation_charge_cents"] == 0
    assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 0,
        "guest folio postings after the free cancellation")

    fx.set_clock("2026-08-13T06:00:00.000Z")
    late = validate_success(api_client.cancel_appointment(
        second["id"], f.cancel_payload("exactly 4 hours out"), fx.COORDINATOR))
    assert late["schedule_status"] == "LATE_CANCELLED", (
        "the inclusive 4-hour comparison puts this in the LATE band rather than "
        "the SHORT_NOTICE band")
    assert late["cancellation_charge_cents"] == LATE_CANCEL_CHARGE_CENTS

    postings = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 1,
        "guest folio postings after the late cancellation")
    assert_folio_rows(postings, [("LATE_CANCEL", LATE_CANCEL_CHARGE_CENTS)],
                      "guest folio")

    guest = world.fetch_guest()
    assert guest["late_cancel_count"] == 1, (
        "the free cancellation does not count toward the restriction threshold")
    assert guest["folio_balance_cents"] == LATE_CANCEL_CHARGE_CENTS
    assert guest["booking_privilege"] == "OPEN"
    assert world.fetch_room()["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0


def test_the_guest_may_take_the_short_notice_band_on_their_own_appointment():
    """Three hours fifty-nine minutes out charges the whole quote.

    PRD §3.8: "Cancellation is available to a `SpaCoordinator` or to the `Guest`
    who owns the appointment, and it accepts an optional `cancel_reason`."

    PRD §3.8: "The charge is the appointment's frozen `quoted_price_cents`
    multiplied by the final rate and divided by ten thousand, rounded half up; it
    is never a re-quote at cancellation time."

    PRD §3.8: "When the appointment's `high_demand_slot` is true, an uplift of
    2,000 basis points is added to whichever band was selected, and the resulting
    rate is then capped at 10,000 basis points"

    Design: Corner/calculations/cancellation_band_edges_and_no_show_grace_on_a_low_demand_slot
    """
    world = _low_demand_world("14")
    booked = fx.book_appointment(world.guest_id, world.treatment_type_id,
                                 world.room_id, "2026-08-14T10:00:00.000Z",
                                 world.therapist_id)
    assert booked["high_demand_slot"] is False

    fx.set_clock("2026-08-14T06:01:00.000Z")
    cancelled = validate_success(api_client.cancel_appointment(
        booked["id"], f.cancel_payload("three hours fifty-nine minutes out"),
        world.guest_headers))
    assert cancelled["schedule_status"] == "LATE_CANCELLED"
    assert cancelled["cancellation_charge_cents"] == SHORT_NOTICE_CHARGE_CENTS, (
        f"the 10000bp band applied to the frozen 18000c quote, with no uplift on a "
        f"low-demand slot; got {cancelled['cancellation_charge_cents']}")

    postings = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 1,
        "guest folio postings")
    assert_folio_rows(postings, [("LATE_CANCEL", SHORT_NOTICE_CHARGE_CENTS)],
                      "guest folio")
    guest = world.fetch_guest()
    assert guest["late_cancel_count"] == 1
    assert guest["folio_balance_cents"] == SHORT_NOTICE_CHARGE_CENTS
    assert guest["booking_privilege"] == "OPEN"
    assert world.fetch_room()["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0


def test_the_no_show_grace_is_refused_one_minute_early_and_legal_at_the_edge():
    """Fourteen minutes past the start is too soon; fifteen is exactly enough.

    PRD §3.8: "A no-show is the coordinator's tool for a guest who never arrives,
    and it is legal only from `CONFIRMED` and only once the grace period has run:
    the logical clock must be at or past the appointment's `start_at` plus 15
    minutes, and an earlier attempt is refused with
    `ERR_INVALID_APPOINTMENT_STATE`."

    PRD §3.8: "the same shape of cascade runs with two differences: the posting
    carries `kind` `NO_SHOW`, and the counter that moves is `no_show_strikes`,
    whose restriction threshold is 1."

    Design: Corner/calculations/cancellation_band_edges_and_no_show_grace_on_a_low_demand_slot
    """
    world = _low_demand_world("15")
    booked = fx.book_appointment(world.guest_id, world.treatment_type_id,
                                 world.room_id, "2026-08-15T10:00:00.000Z",
                                 world.therapist_id)
    appointment_id = fx.confirm(booked["id"])["id"]

    fx.set_clock("2026-08-15T10:14:00.000Z")
    validate_error(
        api_client.no_show_appointment(appointment_id, {}, fx.COORDINATOR),
        ApiErrorId.ERR_INVALID_APPOINTMENT_STATE.value, 409)
    waiting = world.fetch_appointment(appointment_id)
    assert_state_pair(waiting, "CONFIRMED", "CLEARED")
    assert waiting["cancellation_charge_cents"] == 0

    fx.set_clock("2026-08-15T10:15:00.000Z")
    no_show = validate_success(
        api_client.no_show_appointment(appointment_id, {}, fx.COORDINATOR))
    assert no_show["schedule_status"] == "NO_SHOW"
    assert no_show["cancellation_charge_cents"] == SHORT_NOTICE_CHARGE_CENTS, (
        "the no-show band is 10000bp of the frozen quote, uncapped by any uplift "
        "on a low-demand slot")

    postings = assert_list_count(
        api_client.list_guest_folio_charges(world.guest_id, fx.COORDINATOR), 1,
        "guest folio postings")
    assert_folio_rows(postings, [("NO_SHOW", SHORT_NOTICE_CHARGE_CENTS)],
                      "guest folio")
    guest = world.fetch_guest()
    assert guest["no_show_strikes"] == 1
    assert guest["late_cancel_count"] == 0
    assert guest["folio_balance_cents"] == SHORT_NOTICE_CHARGE_CENTS
    assert guest["booking_privilege"] == "RESTRICTED", (
        "a single strike reaches the threshold of 1")
    assert world.fetch_room()["booked_minutes_total"] == 0
    assert world.fetch_therapist()["assigned_minutes_total"] == 0
