"""Combinatorial formulas: the three nested clamps of the price quote, the
per-line rounding of retail commission, and the pre-charge basis of the
service-charge tier selection.
"""

from test_helpers import (
    assert_integer_cents,
    assert_list_count,
    assert_pool_conserved,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import (
    CANON_ACTUAL_DURATION_MINUTES,
    CANON_GRATUITY_CENTS,
    CANON_RETAIL_AMOUNT_CENTS,
    CANON_START_AT,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


def _two_menu_world():
    """The canonical world extended with an off-peak DRY60 menu item, a DRY room,
    a BASIC SWEDISH certification and a second day of availability."""
    world = fx.build_world()
    dry_type = fx.create_treatment_type(
        code="DRY60", name="Swedish Dry 60", duration_minutes=60,
        room_class_required="DRY", required_skill_code="SWEDISH",
        required_scope_level="BASIC", base_price_cents=18000,
        contraindication_codes=[], high_demand=False)
    dry_room = fx.create_room(code="DRY-1", room_class="DRY",
                              turnover_buffer_minutes=15,
                              hourly_fixed_cost_cents=2500)
    fx.grant_certification(world.therapist_id, user="co-20",
                           skill_code="SWEDISH", scope_level="BASIC")
    fx.add_shift_block(world.therapist_id,
                       start_at="2026-08-11T08:00:00.000Z",
                       end_at="2026-08-11T20:00:00.000Z")
    return world, dry_type, dry_room


def test_price_quote_clamps_the_summed_surcharge_before_clamping_the_discount():
    """Both caps bind, and only clamping in the declared order yields 42800.

    PRD §3.5: "a peak component of 1,500 basis points applies when the UTC hour
    of the submitted `start_at` is at least 16 and less than 20 (this is the UTC
    hour of the submitted instant and never a local-time conversion) and is
    otherwise zero, a high-demand component of 1,000 basis points applies when
    the treatment's `high_demand` is true and is otherwise zero, and the
    effective surcharge rate is the smaller of their sum and the surcharge cap of
    2,000 basis points — so a high-demand treatment booked in the peak window is
    surcharged at 20 percent rather than 25."

    PRD §3.5: "the applied discount is the smaller of that raw figure and the
    absolute discount cap of 4,000 cents, so no single treatment may be
    discounted by more than 40 units of currency however generous the tier."

    Design: Difficulty/combinatorial_formula/price_quote_nested_surcharge_and_discount_caps
    """
    world, _dry_type, _dry_room = _two_menu_world()

    appointment = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_id)

    assert_integer_cents(appointment["quoted_price_cents"], "quoted_price_cents")
    assert appointment["quoted_price_cents"] == 42800, (
        "39000 room-adjusted, surcharge_bp min(1500 + 1000, 2000) = 2000 giving "
        "7800, subtotal 46800, raw PLATINUM discount 7020 clamped to 4000, floor "
        f"37440 slack: expected 42800, got {appointment['quoted_price_cents']}")
    assert appointment["quoted_price_cents"] != 44750, (
        "44750 is what an unclamped 2500 bp surcharge would produce")
    assert appointment["quoted_price_cents"] != 39780, (
        "39780 is what an unclamped 1500 bp loyalty discount would produce")
    assert appointment["high_demand_slot"] is True, (
        "17:00Z sits in the peak window and the treatment is high_demand")


def test_price_quote_leaves_both_caps_slack_off_peak_on_a_dry_room():
    """The same formula with no surcharge and an unclamped discount.

    PRD §3.5: "the multipliers are 10,000 basis points for a `DRY` room (no
    adjustment at all), 11,500 for `WET`, 13,000 for `HYDRO` and 12,500 for
    `COUPLES`."

    PRD §3.5: "`high_demand_slot` is true when either the treatment type's
    `high_demand` flag is true or the UTC hour of `start_at` is at least 16 and
    less than 20 — the four-hour late-afternoon peak — and false otherwise."

    Design: Difficulty/combinatorial_formula/price_quote_nested_surcharge_and_discount_caps
    """
    world, dry_type, dry_room = _two_menu_world()

    appointment = fx.book_appointment(
        world.guest_id, dry_type["id"], dry_room["id"],
        "2026-08-11T09:00:00.000Z", world.therapist_id)

    assert appointment["quoted_price_cents"] == 15300, (
        "18000 unadjusted, no peak surcharge at 09:00Z and high_demand false, "
        "PLATINUM discount 2700 under the 4000 cap, floor 14400 slack: expected "
        f"15300, got {appointment['quoted_price_cents']}")
    assert appointment["high_demand_slot"] is False, (
        "09:00Z is outside the peak window and the treatment is not high-demand")


# ---------------------------------------------------------------------------
# Per-line retail commission rounding
# ---------------------------------------------------------------------------

def _final_settlement_world():
    """The canonical appointment, checked in at 17:00, with two PURCHASED 4595c
    retail lines, completed at 105 minutes with a 5000c gratuity, then settled."""
    world = fx.world_with_checked_in_appointment(arrival_clock=CANON_START_AT)
    appointment_id = world.appointments["a"]["id"]
    for sku in ("MARINE-SERUM-30", "MARINE-BALM-50"):
        attachment = validate_success(api_client.create_retail_attachment(
            appointment_id,
            f.retail_attachment_payload(
                product_sku=sku, amount_cents=CANON_RETAIL_AMOUNT_CENTS),
            world.therapist_headers), 201)
        validate_success(api_client.resolve_retail_attachment(
            attachment["id"], f.resolve_payload("PURCHASED"),
            world.guest_headers))
    fx.start_service(appointment_id, world.therapist_id)
    fx.complete_service(appointment_id, world.therapist_id,
                        CANON_ACTUAL_DURATION_MINUTES, CANON_GRATUITY_CENTS)
    appointment = validate_success(
        api_client.get_appointment(appointment_id, fx.DIRECTOR))
    final_row = validate_success(api_client.create_settlement(
        appointment_id, f.settlement_payload(appointment["version"]),
        fx.DIRECTOR), 201)
    return world, final_row


def test_retail_commission_rounds_each_line_before_summing():
    """Two 4595c lines at 1,200 bp give 1102, not 1103.

    PRD §3.9: "`retail_commission_cents` is computed per line and then summed:
    for each `PURCHASED` attachment, multiply its `amount_cents` by 1,200 basis
    points, divide by ten thousand and round half up, then add those per-line
    figures together."

    PRD §3.9: "It is **not** one rounding applied to the summed retail revenue,
    and on a multi-line attachment set the two approaches differ by cents."

    Design: Difficulty/combinatorial_formula/retail_commission_per_line_rounding_then_sum
    """
    _world, final_row = _final_settlement_world()

    assert final_row["retail_revenue_cents"] == 9190, (
        "4595 + 4595 = 9190 of PURCHASED retail revenue")
    assert final_row["retail_commission_cents"] == 1102, (
        "551 + 551 with each 551.4c line rounded half up individually: expected "
        f"1102, got {final_row['retail_commission_cents']}")
    assert final_row["retail_commission_cents"] != 1103, (
        "1103 is round_half_up(9190 * 1200 / 10000), the sum-then-round order")


def test_labor_cost_and_margin_absorb_the_per_line_commission():
    """The one-cent per-line difference propagates into the cost figures.

    PRD §3.9: "`labor_cost_cents` is the therapist's `base_hourly_cost_cents`
    multiplied by `basis_duration_minutes` and divided by 60, rounded half up,
    and then increased by `therapist_commission_cents`, `therapist_share_cents`
    and `retail_commission_cents`."

    PRD §3.9: "`net_margin_cents` is `realized_price_cents` plus
    `retail_revenue_cents` less `labor_cost_cents` less `room_fixed_cost_cents`."

    Design: Difficulty/combinatorial_formula/retail_commission_per_line_rounding_then_sum
    """
    _world, final_row = _final_settlement_world()

    expected_labor = (9100 + final_row["therapist_commission_cents"]
                      + final_row["therapist_share_cents"]
                      + final_row["retail_commission_cents"])
    assert final_row["labor_cost_cents"] == expected_labor
    assert final_row["labor_cost_cents"] == 34493, (
        "9100 base labour + 17214 commission + 7077 therapist share + 1102 "
        f"retail commission: expected 34493, got {final_row['labor_cost_cents']}")
    assert final_row["labor_cost_cents"] != 34494, (
        "34494 is what the sum-then-round retail commission would produce")
    assert final_row["net_margin_cents"] == 12997, (
        f"45300 + 9190 - 34493 - 7000: expected 12997, "
        f"got {final_row['net_margin_cents']}")


# ---------------------------------------------------------------------------
# Service-charge tier basis
# ---------------------------------------------------------------------------

def test_service_charge_tier_is_selected_on_the_pre_charge_basis():
    """The tier reads the pre-charge basis, never the row's own folio total.

    PRD §3.9: "The third step selects the service-charge rate, and the basis for
    that selection is pinned deliberately: the tier basis is
    `realized_price_cents` plus `retail_revenue_cents`, evaluated **before** any
    service charge exists, never `folio_total_cents` (which already contains the
    service charge and would make the rule circular)."

    Design: Difficulty/combinatorial_formula/service_charge_tier_basis_evaluation_order
    """
    world = fx.world_with_checked_in_appointment(arrival_clock=CANON_START_AT)
    appointment_id = world.appointments["a"]["id"]

    rows = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 1,
        "settlement rows after check-in")
    row = rows[0]
    assert row["variant"] == "PROVISIONAL" and row["status"] == "PROVISIONAL"
    assert row["realized_price_cents"] == 42800
    assert row["retail_revenue_cents"] == 0
    assert row["service_charge_bp"] == 1800, (
        "the tier basis 42800 + 0 is below the 50,000c threshold, so the "
        f"standard 1,800 bp rate applies; got {row['service_charge_bp']}")
    assert row["service_charge_pool_cents"] == 7704, (
        f"round_half_up(42800 * 1800 / 10000) = 7704, got "
        f"{row['service_charge_pool_cents']}")
    assert row["service_charge_pool_cents"] != 6420, (
        "6420 is what the reduced 1,500 bp rate would give if the tier were "
        "keyed on the row's own folio_total_cents")
    assert row["folio_total_cents"] == 50504, (
        "the same row's folio total is above the threshold, which is exactly "
        "what makes the circular reading detectable")


def test_provisional_row_distribution_conserves_the_pool_and_posts_one_charge():
    """The three buckets sum to the pool and check-in posts exactly one charge.

    PRD §3.9: "the house share is **never** computed by applying that rate — it
    is always the remainder, so that the three buckets sum to
    `distributable_pool_cents` to the cent regardless of how the two roundings
    fell."

    PRD §3.6: "It then posts a folio charge of `kind` `TREATMENT` whose
    `amount_cents` is that row's `folio_total_cents`, recomputes the guest's
    `folio_balance_cents` as the exact sum of the guest's postings and increments
    the guest's `version` by 1."

    Design: Difficulty/combinatorial_formula/service_charge_tier_basis_evaluation_order
    """
    world = fx.world_with_checked_in_appointment(arrival_clock=CANON_START_AT)
    appointment_id = world.appointments["a"]["id"]

    row = assert_list_count(
        api_client.list_settlements(appointment_id, fx.DIRECTOR), 1,
        "settlement rows after check-in")[0]
    assert row["therapist_share_cents"] == 4622
    assert row["support_pool_cents"] == 1926
    assert row["house_share_cents"] == 1156
    assert_pool_conserved(row)

    postings = assert_list_count(
        api_client.list_appointment_folio_charges(appointment_id, fx.DIRECTOR),
        1, "appointment folio postings")
    assert postings[0]["kind"] == "TREATMENT"
    assert postings[0]["amount_cents"] == 50504
    assert world.fetch_guest()["folio_balance_cents"] == 50504
