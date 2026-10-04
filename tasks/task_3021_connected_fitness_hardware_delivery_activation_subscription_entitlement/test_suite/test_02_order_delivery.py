"""Order totals, delivery charges, stair-carry advisories and crew windows."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_household_user,
    advisory_stair_surcharge_cents,
    api_client,
    create_appointment,
    create_membership,
    create_delivery_quote_payload,
    delivery_fee_cents,
    get_order,
    mint_device,
    owner_headers,
    place_order,
    set_clock,
    setup_active_membership,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]
OWNER = TEST_USERS["membership_owner_headers"]


# =========================================================================
# Queue A — Difficulty instances
# =========================================================================

def test_order_carries_a_provisional_quote_and_a_chronological_capture_side_by_side():
    """PRD §3.1: "At that instant the platform writes `quote_total_cents`, the
    provisional total, using the forward-looking variant of the order-total rule:
    because no zone is known yet the delivery component is zero, so the pre-finance
    basis is merely the subtotal."
    PRD §3.2: "The order's `finance_charge_cents` is then the captured total minus
    the subtotal minus the delivery fee, floored at zero so it can never go
    negative."

    Design: Difficulty/dual_variant_calc/order_total_variants_diverge_when_delivery_crosses_the_finance_tier
    """
    base = setup_active_membership(clock_utc="2026-09-01T00:00:00Z", complete=False,
                                   zone="METRO", subtotal_cents=296_000,
                                   financing_method="FINANCE_SCHEDULED")
    o_id = base["order_id"]

    provisional = get_order(o_id, base["membership_id"])
    assert provisional["status"] == "DELIVERY_SCHEDULED"
    # FORWARD_LOOKING: basis 296000 (< 300000, rate 500 bps) -> 296000 + 14800
    assert provisional["quote_total_cents"] == 310_800
    assert provisional["captured_total_cents"] is None
    assert provisional["delivery_fee_cents"] == 0

    validate_success(api_client.complete_delivery_appointment(
        base["appointment_id"], {"completion_grade": "CLEAN"}, TECH), 200)

    captured = get_order(o_id, base["membership_id"])
    # CHRONOLOGICAL METRO: basis 296000 + 4500 = 300500 (>= 300000, rate 1000 bps)
    assert captured["captured_total_cents"] == 330_550
    assert captured["delivery_fee_cents"] == 4500
    assert captured["finance_charge_cents"] == 30_050
    assert captured["quote_total_cents"] == 310_800


def test_the_provisional_quote_is_never_revised_in_place():
    """PRD §3.1: "Nothing in the later delivery step overwrites this provisional
    figure; both totals remain readable side by side forever."
    PRD §3.2: "The parent order moves from `DELIVERY_SCHEDULED` to `DELIVERED`, and
    it is here — and only here — that the chronological variant of the order total
    runs: the order's `delivery_fee_cents` is written from the delivery charge for
    the actual zone, and its `captured_total_cents` is written on the same pinned
    pre-finance basis used at order time, now with a non-zero delivery component."

    Design: Difficulty/dual_variant_calc/order_total_variants_diverge_when_delivery_crosses_the_finance_tier
    """
    base = setup_active_membership(clock_utc="2026-09-01T00:00:00Z", complete=False,
                                   zone="RURAL", crew="CREW-R",
                                   subtotal_cents=296_000,
                                   financing_method="FINANCE_SCHEDULED")
    o_id = base["order_id"]
    assert get_order(o_id, base["membership_id"])["quote_total_cents"] == 310_800

    validate_success(api_client.complete_delivery_appointment(
        base["appointment_id"], {"completion_grade": "CLEAN"}, TECH), 200)

    captured = get_order(o_id, base["membership_id"])
    # RURAL TREAD: min(3 * 3000, 3000 + 2 * 900) == min(9000, 4800) == 4800
    assert captured["delivery_fee_cents"] == 4800
    assert captured["quote_total_cents"] == 310_800
    # CHRONOLOGICAL RURAL: basis 296000 + 4800 = 300800 (>= 300000, rate 1000 bps)
    assert captured["captured_total_cents"] == 330_880
    assert captured["quote_total_cents"] != captured["captured_total_cents"]


def test_the_service_order_and_parts_get_return_resource_not_found_for_unknown_ids():
    """PRD §2.11: "The first segment that does not resolve to an existing row aborts
    the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and no attempt is made to
    resolve later segments."

    Design: Corner/endpoints/service_order_and_part_get_with_an_unknown_id_returns_resource_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    res_so = api_client.get_service_order(NON_EXISTENT_UUID, TECH)
    res_part = api_client.get_part(NON_EXISTENT_UUID, TECH)

    assert res_so.status_code == 404, res_so.text
    assert res_so.json()["data"]["error_id"] == "ERR_RESOURCE_NOT_FOUND"
    assert res_part.status_code == 404, res_part.text
    assert res_part.json()["data"]["error_id"] == "ERR_RESOURCE_NOT_FOUND"
    assert res_so.json()["response_type"] == "error"
    assert res_part.json()["response_type"] == "error"


def test_advisory_stair_surcharge_rounds_each_component_before_it_sums_them():
    """PRD §3.1: "Both components are scaled by the 1.0825 taxed basis, each is
    rounded half up to a whole cent *separately* — the flat component on its own and
    the billable component on its own — and only then are the two rounded amounts
    added."
    PRD §3.1: "Of the eligible flights, the first is covered by the flat charge and
    only the remainder is billable, each billable flight charged at 250 cents."

    Design: Difficulty/combinatorial_formula/stair_surcharge_round_per_term_differs_from_round_at_end
    """
    set_clock("2026-09-01T00:00:00Z")
    quote = validate_success(api_client.get_delivery_quote(
        create_delivery_quote_payload(hardware_sku="TREAD", zone="METRO",
                                      stair_flights=3, has_elevator=False,
                                      assembly_required=False), TECH), 200)

    # 3 eligible flights, 2 billable:
    # round_half_up(500 * 1.0825) + round_half_up(2 * 250 * 1.0825) == 541 + 541 == 1082
    assert quote["stair_carry_fee_cents"] == 1082
    assert quote["stair_carry_fee_cents"] == advisory_stair_surcharge_cents(3, False)
    assert quote["delivery_fee_cents"] == 4500


def test_a_single_stair_flight_is_fully_absorbed_by_the_flat_first_flight_charge():
    """PRD §3.1: "The first flight is always charged at a flat 500 cents; a flight
    is waived when the building has a working elevator, so the eligible count is the
    number of flights reduced by one if `has_elevator` is true. Of the eligible
    flights, the first is covered by the flat charge and only the remainder is
    billable, each billable flight charged at 250 cents."

    Design: Difficulty/combinatorial_formula/stair_surcharge_round_per_term_differs_from_round_at_end
    """
    set_clock("2026-09-01T00:00:00Z")
    quote = validate_success(api_client.get_delivery_quote(
        create_delivery_quote_payload(hardware_sku="TREAD", zone="METRO",
                                      stair_flights=1, has_elevator=False,
                                      assembly_required=True), TECH), 200)

    # billable_flights == 0, so the whole charge is round_half_up(500 * 1.0825) == 541
    assert quote["stair_carry_fee_cents"] == 541
    assert quote["stair_carry_fee_cents"] == advisory_stair_surcharge_cents(1, False)

    elevated = validate_success(api_client.get_delivery_quote(
        create_delivery_quote_payload(hardware_sku="TREAD", zone="METRO",
                                      stair_flights=2, has_elevator=True), TECH), 200)
    # the elevator waives one flight, leaving one flight that is again absorbed
    assert elevated["stair_carry_fee_cents"] == 541


def test_the_stair_surcharge_is_never_copied_onto_an_order_total():
    """PRD §3.1: "Under the shipped configuration, however, the order's
    `stair_carry_fee_cents` and `assembly_fee_cents` are both pinned to zero on
    every order, so this formula is exposed only as the advisory figure returned by
    the quote preview and is never copied onto an order total."

    Design: Difficulty/combinatorial_formula/stair_surcharge_round_per_term_differs_from_round_at_end
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", complete=False,
                                   stair_flights=3, has_elevator=False)
    validate_success(api_client.complete_delivery_appointment(
        base["appointment_id"], {"completion_grade": "CLEAN"}, TECH), 200)

    order = get_order(base["order_id"], base["membership_id"])
    assert order["stair_carry_fee_cents"] == 0
    assert order["assembly_fee_cents"] == 0

    quote = validate_success(api_client.get_delivery_quote(
        create_delivery_quote_payload(hardware_sku="TREAD", zone="METRO",
                                      stair_flights=3, has_elevator=False), TECH), 200)
    assert quote["stair_carry_fee_cents"] == 1082


def test_a_window_abutting_an_open_crew_window_is_admissible():
    """PRD §2.9: "Every time interval in this system is half-open. A window stated as
    starting at one instant and ending at another includes its start instant and
    excludes its end instant, so two windows that merely touch end-to-start do not
    overlap."
    PRD §3.1: "Scheduling moves the appointment from `REQUESTED` to `SCHEDULED` and
    requires two things: the start instant must precede the end instant, and the
    half-open interval must not intersect any other appointment for the same
    `technician_crew_code` that is already `SCHEDULED` or `IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/delivery_crew_half_open_window_admits_abutting_and_rejects_contained
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:00:00Z", complete=False,
                                   zone="METRO", crew="CREW-A")
    second = _second_household(serial="TREAD-0002", crew="CREW-A",
                               start_at="2026-09-10T09:00:00Z",
                               end_at="2026-09-10T11:00:00Z")

    # CREW-A already holds [13:00, 15:00) in IN_PROGRESS on 5 September
    assert base["appointment"]["status"] == "IN_PROGRESS"

    scheduled = validate_success(api_client.schedule_delivery_appointment(
        second["appointment_id"],
        {"start_at": "2026-09-05T15:00:00Z", "end_at": "2026-09-05T17:00:00Z"},
        TECH), 200)
    assert scheduled["status"] == "SCHEDULED"


def test_a_window_contained_in_an_open_crew_window_is_refused():
    """PRD §2.9: "Personnel and instructors cannot be double-booked: a proposed
    window for a crew or an instructor is refused with `ERR_TEMPORAL_OVERLAP` (HTTP
    409) when it intersects an existing open window belonging to the same crew or
    the same instructor."

    Design: Difficulty/resource_temporal_overlap/delivery_crew_half_open_window_admits_abutting_and_rejects_contained
    """
    setup_active_membership(clock_utc="2026-09-05T13:00:00Z", complete=False,
                            zone="METRO", crew="CREW-A")
    second = _second_household(serial="TREAD-0002", crew="CREW-A",
                               start_at="2026-09-10T09:00:00Z",
                               end_at="2026-09-10T11:00:00Z")

    res = api_client.schedule_delivery_appointment(
        second["appointment_id"],
        {"start_at": "2026-09-05T13:30:00Z", "end_at": "2026-09-05T14:30:00Z"},
        TECH)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_TEMPORAL_OVERLAP"

    after = validate_success(
        api_client.get_delivery_appointment(second["appointment_id"], TECH), 200)
    assert after["status"] == "REQUESTED"


def test_the_same_window_is_admissible_for_a_different_crew():
    """PRD §2.9: "Personnel and instructors cannot be double-booked: a proposed
    window for a crew or an instructor is refused with `ERR_TEMPORAL_OVERLAP` (HTTP
    409) when it intersects an existing open window belonging to the same crew or
    the same instructor."
    PRD §3.1: "A `ServiceTechnician` then creates the installation window by
    supplying the `hardware_order_id` being fulfilled and a proposed half-open
    interval from `start_at` to `end_at`, together with the `zone` the crew will
    drive to — `METRO`, `SUBURBAN` or `RURAL` — and a `technician_crew_code`."

    Design: Difficulty/resource_temporal_overlap/delivery_crew_half_open_window_admits_abutting_and_rejects_contained
    """
    setup_active_membership(clock_utc="2026-09-05T13:00:00Z", complete=False,
                            zone="METRO", crew="CREW-A")
    second = _second_household(serial="TREAD-0002", crew="CREW-B",
                               start_at="2026-09-10T09:00:00Z",
                               end_at="2026-09-10T11:00:00Z")

    scheduled = validate_success(api_client.schedule_delivery_appointment(
        second["appointment_id"],
        {"start_at": "2026-09-05T13:30:00Z", "end_at": "2026-09-05T14:30:00Z"},
        TECH), 200)
    assert scheduled["status"] == "SCHEDULED"


# =========================================================================
# Queue B — Corner instances
# =========================================================================

def test_a_zone_delivery_quote_reports_the_advisory_charges_and_writes_nothing():
    """PRD §3.1: "A pre-purchase advisory quote is available without creating
    anything. A caller supplies `hardware_sku`, `zone`, `stair_flights`,
    `has_elevator` and an optional `assembly_required` flag, and receives back
    `delivery_fee_cents`, `stair_carry_fee_cents`, `assembly_fee_cents` and
    `quote_total_cents` as a pure preview that writes nothing to any table."

    Design: Corner/endpoints/delivery_quote_reports_the_advisory_charges_and_writes_nothing
    """
    set_clock("2026-09-01T00:00:00Z")
    quote = validate_success(api_client.get_delivery_quote(
        create_delivery_quote_payload(hardware_sku="TREAD", zone="RURAL",
                                      stair_flights=4, has_elevator=False,
                                      assembly_required=True), TECH), 200)

    assert quote["delivery_fee_cents"] == 4800
    assert quote["assembly_fee_cents"] == 0
    # RURAL TREAD: min(3 * 3000, 3000 + 2 * 900) == 4800
    # 4 flights, 3 billable: round_half_up(500*1.0825) + round_half_up(3*250*1.0825)
    #                      == 541 + 812 == 1353
    assert quote["stair_carry_fee_cents"] == 1353
    assert quote["quote_total_cents"] == 6153

    orders, orders_meta = validate_paginated(api_client.list_hardware_orders(ADMIN))
    assert orders_meta["total_count"] == 0
    appointments, appt_meta = validate_paginated(api_client.list_delivery_appointments(TECH))
    assert appt_meta["total_count"] == 0


def test_scheduling_is_conditional_on_state_window_and_clock():
    """PRD §3.1: "The visit itself begins with a start step that moves the appointment
    from `SCHEDULED` to `IN_PROGRESS`, admitted only once the logical clock has
    reached `start_at`; an early start is refused with `ERR_WINDOW_NOT_OPEN` (HTTP
    409)."
    PRD §3.1: "Confirming the window is a separate step. Scheduling moves the
    appointment from `REQUESTED` to `SCHEDULED` and requires two things: the start
    instant must precede the end instant, and the half-open interval must not
    intersect any other appointment for the same `technician_crew_code` that is
    already `SCHEDULED` or `IN_PROGRESS`."

    Design: Corner/endpoints/delivery_appointment_scheduling_is_conditional_on_state_and_window
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:00:00Z", complete=False,
                                   zone="METRO", crew="CREW-A")
    a_id = base["appointment_id"]

    # a fresh REQUESTED appointment whose window has not yet opened
    early = _second_household(serial="TREAD-0002", crew="CREW-B",
                              start_at="2026-09-06T13:00:00Z",
                              end_at="2026-09-06T15:00:00Z")
    set_clock("2026-09-06T12:00:00Z")

    scheduled = validate_success(api_client.schedule_delivery_appointment(
        early["appointment_id"],
        {"start_at": "2026-09-06T13:00:00Z", "end_at": "2026-09-06T15:00:00Z"},
        TECH), 200)
    assert scheduled["status"] == "SCHEDULED"

    # now SCHEDULED but still before start_at: the early start is refused
    res = api_client.start_delivery_appointment(early["appointment_id"], {}, TECH)
    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_WINDOW_NOT_OPEN"

    repeat = api_client.schedule_delivery_appointment(
        early["appointment_id"],
        {"start_at": "2026-09-06T13:00:00Z", "end_at": "2026-09-06T15:00:00Z"},
        TECH)
    assert repeat.status_code == 409, repeat.text
    assert repeat.json()["data"]["error_id"] == "ERR_INVALID_STATE"

    order = get_order(early["order_id"], early["membership_id"])
    assert order["status"] == "DELIVERY_SCHEDULED"


# ─── local helpers ─────────────────────────────────────

def _second_household(serial, crew, start_at, end_at, zone="METRO",
                      subtotal_cents=296_000):
    """A second, independent household holding a REQUESTED appointment."""
    membership = create_membership(household_name="Rhone Household",
                                   billing_email="rhone@x.com")
    m_id = membership["id"]
    owner = add_household_user(m_id, display_name="Bo Rhone", email="bo@x.com",
                               role="OWNER")
    device = mint_device(m_id, hardware_sku="TREAD", serial=serial)
    order = place_order(m_id, device["id"], hardware_sku="TREAD",
                        subtotal_cents=subtotal_cents)
    appointment = create_appointment(device["id"], order["id"], start_at, end_at,
                                     zone=zone, crew=crew)
    return {
        "membership": membership,
        "membership_id": m_id,
        "owner": owner,
        "device": device,
        "device_id": device["id"],
        "order": order,
        "order_id": order["id"],
        "appointment": appointment,
        "appointment_id": appointment["id"],
        "serial": serial,
        "headers": owner_headers(m_id),
    }
def test_an_ordered_install_visit_after_delivery_moves_the_order_forward():
    """PRD §3.1: "The appointment opens in `REQUESTED`, and the mere act of creating
    it advances the parent order from `PLACED` to `DELIVERY_SCHEDULED`."
    PRD §3.1: "The zone fixes the appointment's `delivery_legs`: one leg in `METRO`,
    two in `SUBURBAN`, three in `RURAL`."

    Design: Difficulty/resource_temporal_overlap/delivery_crew_half_open_window_admits_abutting_and_rejects_contained
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z", complete=False,
                                   zone="SUBURBAN", crew="CREW-S")
    appointment = api_client.get_delivery_appointment(base["appointment_id"], TECH)
    appointment = validate_success(appointment, 200)
    assert appointment["zone"] == "SUBURBAN"
    assert appointment["delivery_legs"] == 2

    order = validate_success(
        api_client.get_hardware_order(base["order_id"], owner_headers(base["membership_id"])), 200)
    assert order["status"] == "DELIVERY_SCHEDULED"

