"""The pricing engines: the room package, the activity rate, the refund, and opt-in."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx


def test_room_package_surcharge_branches_on_party_size_against_the_room_maximum(api):
    """PRD §3.1: "When `waterpark_included_units` is at most the room type's
    `max_occupancy` minus 2, the party is at or below par and the surcharge is
    zero. Otherwise the surcharge is the number of complete groups of four guests
    in `waterpark_included_units` — any remainder discarded, since the division is
    floored — multiplied by the room fee actuation constant of 1400 cents."

    Design: Difficulty/combinatorial_formula/package_rate_surcharge_nested_occupancy_branch
    """
    resort = fx.create_resort(name="Grapevine", park_capacity_occupancy_units=40, day_pass_cap_units=20)
    room_type = fx.create_room_type(resort["id"])
    at_par = fx.create_reservation(resort["id"], room_type["id"], guest_count=6)
    over_par = fx.create_reservation(resort["id"], room_type["id"], guest_count=8)
    assert at_par["package_rate_total_cents"] == 113400
    assert over_par["package_rate_total_cents"] == 116200
    assert at_par["package_rate_total_cents"] != over_par["package_rate_total_cents"]


def test_the_surcharge_is_floored_to_complete_groups_of_four(api):
    """PRD §3.1: "Otherwise the surcharge is the number of complete groups of four
    guests in `waterpark_included_units` — any remainder discarded, since the
    division is floored — multiplied by the room fee actuation constant of 1400
    cents."

    Design: Difficulty/combinatorial_formula/package_rate_surcharge_nested_occupancy_branch
    """
    resort = fx.create_resort(name="Grapevine", park_capacity_occupancy_units=40, day_pass_cap_units=20)
    room_type = fx.create_room_type(resort["id"])
    eight_guests = fx.create_reservation(resort["id"], room_type["id"], guest_count=8)
    assert eight_guests["package_rate_total_cents"] == 116200
    assert eight_guests["waterpark_included_units"] == 8


def test_the_room_fee_surcharge_separates_the_two_package_figures(api):
    """PRD §3.1: "The amount actually authorised against the guest's debit
    instrument, which is what lands in `package_rate_total_cents`, is the
    underwritten total plus the surcharge once more."
    PRD §3.1: "That figure is the arcade half plus the room subtotal, with no surcharge at all. The two fields therefore differ by exactly the surcharge, and they coincide only when the party is at or below par — that is, only when `waterpark_included_units` is at most `max_occupancy` minus 2."

    Design: Difficulty/dual_variant_calc/package_rate_withheld_vs_debited_split
    """
    resort = fx.create_resort(name="Traverse City", park_capacity_occupancy_units=36,
                              day_pass_cap_units=20)
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=8)
    assert reservation["package_rate_total_cents"] == 116200
    assert reservation["package_rate_withheld_cents"] == 113400
    assert (
        reservation["package_rate_total_cents"] - reservation["package_rate_withheld_cents"] == 2800
    )


def test_the_withheld_figure_omits_the_surcharge_entirely(api):
    """PRD §3.1: "That figure is the arcade half plus the room subtotal, with no
    surcharge at all."

    Design: Difficulty/dual_variant_calc/package_rate_withheld_vs_debited_split
    """
    resort, room_type = fx.setup_resort_with_room_type(name="Traverse City")
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=8)
    assert reservation["package_rate_withheld_cents"] == 113400


def test_premium_tier_multiplies_the_session_price_before_the_bulk_discount(api):
    """PRD §3.9: "`tier_units` is the number of attendees multiplied by the tier's
    unit multiplier — 1 for `STANDARD`, 2 for `PREMIUM`, and 3 for `VIP` — and the
    subtotal is the session's `base_price_cents` multiplied by that figure."

    Design: Difficulty/combinatorial_formula/activity_rate_discount_order_pinned
    """
    resort, group_booking, session, booking = fx.setup_confirmed_group_with_activity(
        session_overrides={"tier_code": "PREMIUM", "base_price_cents": 3500, "capacity_units": 30},
        attendees=10,
        member_count=10,
    )
    assert booking["activity_rate_total_cents"] == 69000
    assert booking["activity_rate_total_cents"] != 34000
    assert booking["activity_booking_status"] == "PENDING_PAYMENT"


def test_a_party_below_ten_attracts_no_bulk_discount(api):
    """PRD §3.9: "When there are fewer than ten attendees the discount is zero."

    Design: Corner/calculations/activity_rate_below_bulk_threshold_has_no_discount
    """
    resort = fx.create_resort(name="Concord")
    session = fx.create_activity_session(resort["id"], base_price_cents=3500, capacity_units=20)
    group_booking = fx.create_group_booking(resort["id"], group_kind="SCHOOL", member_count=4,
                                            deposit_paid_cents=2000, service_date="2026-09-25")
    booking = fx.create_activity_booking(
        resort["id"], session["id"], group_booking["id"], attendees=4
    )
    assert booking["activity_rate_total_cents"] == 14000


def test_ten_attendees_earn_two_complete_five_groups_of_discount(api):
    """PRD §3.9: "The bulk discount applies only to parties of ten or more
    attendees, and when it applies it is the number of complete groups of five in
    the attendee count — the division is floored, so a remainder is discarded —
    multiplied by the 500-cent bulk discount constant."

    Design: Difficulty/combinatorial_formula/activity_rate_discount_order_pinned
    """
    resort, group_booking, session, booking = fx.setup_confirmed_group_with_activity(
        session_overrides={"tier_code": "PREMIUM", "base_price_cents": 3500, "capacity_units": 30},
        attendees=10,
        member_count=10,
    )
    # 3500 base x 2 (PREMIUM) x 10 attendees, less two 500-cent blocks.
    assert booking["activity_rate_total_cents"] == 3500 * 2 * 10 - 2 * 500


def test_cancelled_booking_refunds_the_summed_gross_rounded_once(api):
    """PRD §3.9: "That count is multiplied by the session's `base_price_cents` and
    then by the refund rate of 0.375 — three eighths — producing a gross figure
    that is then rounded half up to whole cents once, at the end, and stored in
    `activity_rate_refund_cents`."

    Design: Difficulty/combinatorial_formula/activity_refund_rounding_order_pinned
    """
    resort = fx.create_resort(name="Fitchburg")
    session = fx.create_activity_session(resort["id"], base_price_cents=3900, capacity_units=20)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=3, deposit_paid_cents=1500,
        service_date="2026-09-12",
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    booking = fx.create_activity_booking(resort["id"], session["id"], group_booking["id"], attendees=3)
    booking = validate_success(
        api.confirm_activity_booking(resort["id"], booking["id"], fx.group_headers_for(group_booking["id"]))
    )
    cancelled = validate_success(
        api.cancel_activity_booking(resort["id"], booking["id"], fx.group_headers_for(group_booking["id"]))
    )
    assert cancelled["activity_rate_refund_cents"] == 4388
    assert cancelled["activity_rate_refund_cents"] != 4387


def test_the_refund_rounds_at_the_end_rather_than_per_attendee(api):
    """PRD §3.9: "Because 0.375 produces a half-cent for any odd base price, the
    order of operations changes the answer: at a base price of 3900 cents, one
    refundable attendee rounds to 1463 cents, and two refundable attendees round as
    a pair to 2925 cents; rounding each attendee's refund first and then adding
    them yields 2926 cents, one cent more than the platform pays. The platform sums
    first and rounds once."

    Design: Difficulty/dual_variant_calc/activity_refund_sum_then_round_vs_per_attendee
    """
    resort = fx.create_resort(name="Mason", park_capacity_occupancy_units=40, day_pass_cap_units=20)
    session = fx.create_activity_session(resort["id"], name="Story Time", base_price_cents=3900,
                                         capacity_units=20)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=2, deposit_paid_cents=1000,
        service_date="2026-09-10",
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    booking = fx.create_activity_booking(resort["id"], session["id"], group_booking["id"], attendees=2)
    validate_success(
        api.confirm_activity_booking(resort["id"], booking["id"], fx.group_headers_for(group_booking["id"]))
    )
    cancelled = validate_success(
        api.cancel_activity_booking(resort["id"], booking["id"], fx.group_headers_for(group_booking["id"]))
    )
    assert cancelled["activity_booking_status"] == "CANCELLED"
    assert cancelled["activity_rate_refund_cents"] == 2925
    assert cancelled["activity_rate_refund_cents"] != 2926


def test_the_refund_is_visible_on_the_cancel_response_without_a_read_back(api):
    """PRD §3.9: "Cancellation is available to the owning `Group` organiser or to
    `platform_ops` from `CONFIRMED` status and computes the refund in the same
    transition, so a booking that is cancelled and a booking that is refunded are
    never observed separately."

    Design: Corner/consistency_model/immediate_visibility_of_cancel_refund_and_cabana_release
    """
    resort = fx.create_resort(name="Mason", park_capacity_occupancy_units=20, day_pass_cap_units=10)
    session = fx.create_activity_session(resort["id"], base_price_cents=3900, capacity_units=20)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=2, deposit_paid_cents=1000,
        service_date="2026-09-28",
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    booking = fx.create_activity_booking(resort["id"], session["id"], group_booking["id"], attendees=2)
    validate_success(
        api.confirm_activity_booking(resort["id"], booking["id"], fx.group_headers_for(group_booking["id"]))
    )
    response = validate_success(
        api.cancel_activity_booking(resort["id"], booking["id"], fx.group_headers_for(group_booking["id"]))
    )
    assert response["activity_booking_status"] == "CANCELLED"
    assert response["activity_rate_refund_cents"] == 2925


def test_the_opt_in_readings_diverge_when_nothing_is_booked_yet(api):
    """PRD §3.9: "The `opt_in_ratio_strict` is the same strict division of the
    session's capacity by that denominator, and it is null when the denominator is
    zero — a null value is the platform's way of saying there was no load to divide
    by rather than that the ratio is zero."
    PRD §3.9: "The `opt_in_ratio_inclusive` reads the session as part of its own
    denominator: the session's `capacity_units` divided by the denominator plus
    `capacity_units`."
    PRD §3.9: "A companion field, `opt_in_gate`, records the admission verdict implied by the strict ratio: `ADMIT` when the strict ratio meets or exceeds the configured opt-in ratio threshold, or when the denominator is zero; `HOLD` otherwise."

    Design: Corner/calculations/opt_in_ratio_variants_diverge_on_empty_occupancy
    """
    resort = fx.create_resort(name="Manteca")
    fx.set_clock(resort["id"], "2026-09-03T09:00:00Z")
    session = fx.create_activity_session(
        resort["id"], name="Story Time", tier_code="STANDARD", base_price_cents=3900,
        capacity_units=20,
    )
    assert session["opt_in_ratio_strict"] is None
    assert session["opt_in_ratio_inclusive"] == 1.0
    assert session["opt_in_gate"] == "ADMIT"


def test_the_opt_in_readings_are_stamped_against_current_occupancy(api):
    """PRD §3.9: "The `opt_in_ratio` is the session's `capacity_units` divided by a
    denominator that is the sum of the room, day-pass, and group contributions to
    the occupancy ledger over exactly the property's current service date."
    PRD §3.9: "All three ratios are stored to four decimal places, rounded half up."

    Design: Corner/calculations/opt_in_ratio_variants_diverge_on_empty_occupancy
    """
    resort = fx.create_resort(name="Manteca")
    fx.set_clock(resort["id"], "2026-09-03T09:00:00Z")
    room_type = fx.create_room_type(resort["id"])
    fx.create_reservation(resort["id"], room_type["id"], guest_count=4)
    session = fx.create_activity_session(resort["id"], capacity_units=20)
    assert session["opt_in_ratio_strict"] == 5.0
    assert session["opt_in_ratio_inclusive"] == 0.8333


def test_occupancy_landing_exactly_on_the_park_ceiling_is_accepted(api):
    """PRD §2.5: "Remaining capacity is never reported as a negative number. An operation that would push the total above the ceiling is refused with `ERR_PARK_CAPACITY_EXCEEDED` (HTTP 409) rather than being stored and clamped, and the same ceiling is enforced separately against the day-pass allocation with `ERR_DAY_PASS_CAP_EXCEEDED` (HTTP 409) when the day-passed units alone would overrun `day_pass_cap_units`."

    Design: Difficulty/boundary_precision_check/park_capacity_exact_equality_admits
    """
    resort, _reservation, _day_pass, _room_type = fx.setup_occupancy_filled(
        park_capacity=12, booking_units=6, day_pass_units=6
    )
    ledger = fx.get_capacity(resort["id"], "2026-09-03")
    assert ledger["occupancy_units"] == 12
    assert ledger["capacity_remaining_units"] == 0
    assert validate_success(api.get_resort(resort["id"], fx.PLATFORM_OPS))[
        "park_capacity_occupancy_units"
    ] == 12


def test_activating_a_band_past_the_park_ceiling_is_refused(api):
    """PRD §3.3: "Finally, the total of the room, group, and day-pass contributions
    on the band's service date, taken together, must not exceed the property's
    `park_capacity_occupancy_units`; a breach is refused with
    `ERR_PARK_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/park_capacity_breach_rejected_on_activation
    """
    resort = fx.create_resort(name="Fitchburg", park_capacity_occupancy_units=4,
                              day_pass_cap_units=4)
    fx.set_clock(resort["id"], "2026-09-03T09:00:00Z")
    room_type = fx.create_room_type(resort["id"])
    fx.create_reservation(resort["id"], room_type["id"], guest_count=4)
    day_pass = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=2)
    band = fx.create_wristband(
        resort["id"], "DAY_PASS_GUEST", "Ugo", day_pass_id=day_pass["id"],
        valid_on_service_date="2026-09-03",
    )
    response = api.activate_wristband(resort["id"], band["id"], fx.FRONT_DESK)
    validate_error(response, ApiErrorId.ERR_PARK_CAPACITY_EXCEEDED.value)
    assert validate_success(api.get_wristband(resort["id"], band["id"], fx.FRONT_DESK))[
        "wristband_status"
    ] == "ISSUED"


def test_a_booking_filling_the_session_exactly_is_seated(api):
    """PRD §3.9: "A session can seat a party when the requested `attendees` is no
    greater than the session's `capacity_units` minus the seats already taken,
    where the seats already taken are the sum of `attendees` across every existing
    booking on that same session whose status is `PENDING_PAYMENT` or `CONFIRMED`.
    At exact equality the booking is accepted; one attendee more is rejected."

    Design: Corner/calculations/activity_session_eligibility_at_exact_capacity
    """
    resort = fx.create_resort(name="Concord")
    session = fx.create_activity_session(resort["id"], base_price_cents=3500, capacity_units=5)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=6, deposit_paid_cents=3000,
        service_date="2026-09-26",
    )
    booking = fx.create_activity_booking(
        resort["id"], session["id"], group_booking["id"], attendees=5
    )
    assert booking["attendees"] == 5
    assert booking["activity_rate_total_cents"] == 17500


def test_a_booking_one_seat_past_the_session_is_refused(api):
    """PRD §3.9: "At exact equality the booking is accepted; one attendee more is
    rejected."

    Design: Corner/calculations/activity_session_eligibility_at_exact_capacity
    """
    resort = fx.create_resort(name="Concord")
    session = fx.create_activity_session(resort["id"], base_price_cents=3500, capacity_units=5)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=6, deposit_paid_cents=3000,
        service_date="2026-09-26",
    )
    fx.create_activity_booking(resort["id"], session["id"], group_booking["id"], attendees=5)
    response = api.create_activity_booking(
        resort["id"],
        {
            "activity_session_id": session["id"],
            "group_booking_id": group_booking["id"],
            "attendees": 6,
            "reservation_id": fx.reservation_for_group(resort["id"], group_booking["id"]),
        },
        fx.group_headers_for(group_booking["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_SESSION.value)

def test_a_lone_refundable_attendee_rounds_to_the_half_cent(api):
    """PRD §3.9: "at a base price of 3900 cents, one refundable attendee rounds to
    1463 cents, and two refundable attendees round as a pair to 2925 cents;
    rounding each attendee's refund first and then adding them yields 2926 cents,
    one cent more than the platform pays."

    Design: Difficulty/dual_variant_calc/activity_refund_sum_then_round_vs_per_attendee
    """
    resort = fx.create_resort(name="Mason", park_capacity_occupancy_units=40, day_pass_cap_units=20)
    session = fx.create_activity_session(resort["id"], base_price_cents=3900, capacity_units=20)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=2, deposit_paid_cents=1000,
        service_date="2026-09-10",
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    booking = fx.create_activity_booking(resort["id"], session["id"], group_booking["id"], attendees=1)
    headers = fx.group_headers_for(group_booking["id"])
    validate_success(api.confirm_activity_booking(resort["id"], booking["id"], headers))
    cancelled = validate_success(api.cancel_activity_booking(resort["id"], booking["id"], headers))
    assert cancelled["activity_rate_refund_cents"] == 1463


def test_a_pair_of_refundable_attendees_rounds_as_a_pair(api):
    """PRD §3.9: "at a base price of 3900 cents, one refundable attendee rounds to
    1463 cents, and two refundable attendees round as a pair to 2925 cents;
    rounding each attendee's refund first and then adding them yields 2926 cents,
    one cent more than the platform pays. The platform sums first and rounds once."

    Design: Difficulty/combinatorial_formula/activity_refund_rounding_order_pinned
    """
    resort = fx.create_resort(name="Mason", park_capacity_occupancy_units=40, day_pass_cap_units=20)
    session = fx.create_activity_session(resort["id"], base_price_cents=3900, capacity_units=20)
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=2, deposit_paid_cents=1000,
        service_date="2026-09-10",
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    booking = fx.create_activity_booking(resort["id"], session["id"], group_booking["id"], attendees=2)
    headers = fx.group_headers_for(group_booking["id"])
    validate_success(api.confirm_activity_booking(resort["id"], booking["id"], headers))
    cancelled = validate_success(api.cancel_activity_booking(resort["id"], booking["id"], headers))
    assert cancelled["activity_rate_refund_cents"] == 2925
    assert cancelled["activity_rate_refund_cents"] != 2926


def test_one_occupancy_unit_beyond_the_park_ceiling_is_refused(api, front_desk_headers):
    """PRD §2.5: "An operation that would push the total above the ceiling is refused with `ERR_PARK_CAPACITY_EXCEEDED` (HTTP 409) rather than being stored and clamped, and the same ceiling is enforced separately against the day-pass allocation with `ERR_DAY_PASS_CAP_EXCEEDED` (HTTP 409) when the day-passed units alone would overrun `day_pass_cap_units`."

    Design: Difficulty/boundary_precision_check/park_capacity_exact_equality_admits
    """
    resort = fx.create_resort(name="Fitchburg", park_capacity_occupancy_units=12,
                              day_pass_cap_units=12)
    fx.set_clock(resort["id"], "2026-09-03T08:00:00Z")
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=6)
    fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=6)
    band = validate_success(
        api.create_wristband(
            resort["id"],
            {
                "holder_type": "RESERVATION_GUEST",
                "owner_name": "Wren",
                "reservation_id": reservation["id"],
            },
            front_desk_headers,
        ),
        201,
    )
    response = api.activate_wristband(resort["id"], band["id"], front_desk_headers)
    assert response.status_code >= 400, "one unit past the ceiling is over capacity"


def test_activity_confirmation_is_gated_on_the_group_being_confirmed(api):
    """PRD §3.9: "Confirmation requires the linked group booking to be `CONFIRMED`;
    an activity booking whose group has not been confirmed is refused with
    `ERR_INVALID_STATE` on the state precondition."

    Design: Difficulty/cross_entity_state_dependency/activity_confirm_requires_group_confirmed
    """
    resort = fx.create_resort(name="Sandusky")
    session = fx.create_activity_session(
        resort["id"], name="Wolf Walk", tier_code="VIP", base_price_cents=2500, capacity_units=10
    )
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=4, deposit_paid_cents=0,
        service_date="2026-09-17",
    )
    booking = fx.create_activity_booking(
        resort["id"], session["id"], group_booking["id"], attendees=4
    )
    response = api.confirm_activity_booking(
        resort["id"], booking["id"], fx.group_headers_for(group_booking["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    unchanged = validate_success(api.get_activity_booking(resort["id"], booking["id"], fx.PLATFORM_OPS))
    assert unchanged["activity_booking_status"] == "PENDING_PAYMENT"
    assert unchanged["activity_rate_total_cents"] == 30000


def test_activity_confirmation_succeeds_once_the_group_is_confirmed(api):
    """PRD §3.9: "A confirmed booking moves to `CONFIRMED` and increments its
    `version`."

    Design: Difficulty/cross_entity_state_dependency/activity_confirm_requires_group_confirmed
    """
    resort = fx.create_resort(name="Sandusky")
    session = fx.create_activity_session(
        resort["id"], name="Wolf Walk", tier_code="VIP", base_price_cents=2500, capacity_units=10
    )
    group_booking = fx.create_group_booking(
        resort["id"], group_kind="BIRTHDAY", member_count=4, deposit_paid_cents=2000,
        service_date="2026-09-17",
    )
    group_booking = fx.confirm_group_booking(resort["id"], group_booking["id"])
    booking = fx.create_activity_booking(
        resort["id"], session["id"], group_booking["id"], attendees=4
    )
    confirmed = validate_success(
        api.confirm_activity_booking(
            resort["id"], booking["id"], fx.group_headers_for(group_booking["id"])
        )
    )
    assert confirmed["activity_booking_status"] == "CONFIRMED"
    assert confirmed["activity_rate_total_cents"] == 30000
