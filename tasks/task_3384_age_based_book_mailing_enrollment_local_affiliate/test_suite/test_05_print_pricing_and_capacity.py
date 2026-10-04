"""Print-order volume pricing and press capacity (PRD §3.6, §2.8)."""
import pytest

from test_helpers import (
    ACM_THIRD_ID,
    ApiErrorId,
    PrintOrderStatus,
    SelectionStatus,
    TEST_USERS,
    api_client,
    approve_selection,
    assert_confirmed_print_order_pricing,
    confirm_print_order,
    create_print_order,
    create_title,
    reopen_selection,
    set_logical_clock,
    setup_approved_selection,
    setup_five_titles,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_PUBLISHER = TEST_USERS["publisher_ops_headers"]


class TestTierBoundaries:
    def test_print_pricing_tier_boundary_4999_vs_5000(self, api):
        """PRD §3.6: "Pricing locks at confirmation on a volume tier, with each
        tier's lower bound inclusive: 210 cents per unit below 5,000; 185
        cents from 5,000; 160 cents from 20,000; and 140 cents from 50,000."
        and "The plate fee is 25,000 cents, waived entirely when the quantity
        is at least 20,000 or the order is a reprint. The confirmed
        `total_cents` is the quantity times the effective unit price plus the
        plate fee".

        Design: Corner/calculations/print_pricing_tier_boundary_4999_vs_5000
        """
        set_logical_clock()
        title = create_title("INFANT")
        sel_below = setup_approved_selection("2027-02", "INFANT", title_id=title["id"])[
            "selection"
        ]
        sel_at = setup_approved_selection("2027-03", "INFANT", title_id=title["id"])[
            "selection"
        ]
        order_below = confirm_print_order(create_print_order(sel_below["id"], 4999)["id"])
        order_at = confirm_print_order(create_print_order(sel_at["id"], 5000)["id"])
        assert_confirmed_print_order_pricing(order_below)
        assert_confirmed_print_order_pricing(order_at)
        assert order_below["unit_cents"] == 210
        assert order_below["plate_fee_cents"] == 25000
        assert order_below["total_cents"] == 4999 * 210 + 25000  # 1,074,790
        assert order_at["unit_cents"] == 185
        assert order_at["plate_fee_cents"] == 25000
        assert order_at["total_cents"] == 5000 * 185 + 25000  # 950,000
        assert order_at["total_cents"] < order_below["total_cents"], (
            "one more unit crosses the inclusive 5,000 tier bound and costs less"
        )


class TestTierPlateReprintInteraction:
    def test_tier_cliff_and_plate_waiver_invert_totals(self, api):
        """PRD §3.6: "Pricing locks at confirmation on a volume tier, with each
        tier's lower bound inclusive: 210 cents per unit below 5,000; 185
        cents from 5,000; 160 cents from 20,000; and 140 cents from 50,000."
        and "The plate fee is 25,000 cents, waived entirely when the quantity
        is at least 20,000 or the order is a reprint."

        Design: Difficulty/combinatorial_formula/print_pricing_tier_plate_reprint_interaction
        """
        set_logical_clock()
        title = create_title("INFANT")
        sel_nov = setup_approved_selection("2026-11", "INFANT", title_id=title["id"])[
            "selection"
        ]
        sel_dec = setup_approved_selection("2026-12", "INFANT", title_id=title["id"])[
            "selection"
        ]
        order_19999 = confirm_print_order(create_print_order(sel_nov["id"], 19999)["id"])
        order_20000 = confirm_print_order(create_print_order(sel_dec["id"], 20000)["id"])
        assert order_19999["unit_cents"] == 185
        assert order_19999["plate_fee_cents"] == 25000, (
            "19,999 is below the 20,000 plate-fee waiver bound"
        )
        assert order_19999["total_cents"] == 19999 * 185 + 25000  # 3,724,815
        assert order_20000["unit_cents"] == 160
        assert order_20000["plate_fee_cents"] == 0, "waived at 20,000 units"
        assert order_20000["total_cents"] == 20000 * 160  # 3,200,000
        assert order_20000["total_cents"] < order_19999["total_cents"], (
            "tier cliff plus plate waiver: ordering more costs less"
        )

    def test_reprint_discount_rounds_half_up_and_waives_plate(self, api):
        """PRD §3.6: "A reprint pays nine-tenths of its tier price, rounded
        half up to a whole cent. The plate fee is 25,000 cents, waived
        entirely when the quantity is at least 20,000 or the order is a
        reprint."
        PRD §3.6: "The order's `production_month` is derived as the
        selection's mailing month minus one calendar month."

        Design: Difficulty/combinatorial_formula/print_pricing_tier_plate_reprint_interaction
        """
        set_logical_clock()
        title = create_title("INFANT")
        sel_nov = setup_approved_selection("2026-11", "INFANT", title_id=title["id"])[
            "selection"
        ]
        sel_jan = setup_approved_selection("2027-01", "INFANT", title_id=title["id"])[
            "selection"
        ]
        order_plain = confirm_print_order(create_print_order(sel_nov["id"], 19999)["id"])
        order_reprint = confirm_print_order(
            create_print_order(sel_jan["id"], 6000, is_reprint=True)["id"]
        )
        # round_half_up(185 * 0.9) = round_half_up(166.5) = 167
        assert order_reprint["unit_cents"] == 167
        assert order_reprint["plate_fee_cents"] == 0, "reprints never pay the plate fee"
        assert order_reprint["total_cents"] == 6000 * 167  # 1,002,000
        assert order_plain["production_month"] == "2026-10"
        assert order_reprint["production_month"] == "2026-12"


class TestPressCapacity:
    def test_press_capacity_boundary_allows_exactly_400000(self, api):
        """PRD §3.6: "the sum of `quantity` over already-confirmed orders
        sharing this `production_month`, plus this order's quantity, must not
        exceed the monthly press capacity of 400,000 units, with exactly
        400,000 permitted (else `ERR_PRESS_CAPACITY_EXCEEDED`)."
        PRD §3.6: "140 cents from 50,000".

        Design: Difficulty/resource_temporal_overlap/press_capacity_monthly_aggregate_boundary
        """
        set_logical_clock()
        titles = setup_five_titles()
        sel_first = setup_approved_selection(
            "2027-01", "INFANT", title_id=titles["INFANT"]["id"]
        )["selection"]
        sel_second = setup_approved_selection(
            "2027-01", "TODDLER", title_id=titles["TODDLER"]["id"]
        )["selection"]
        first = confirm_print_order(create_print_order(sel_first["id"], 200000)["id"])
        assert first["status"] == PrintOrderStatus.CONFIRMED.value
        assert first["unit_cents"] == 140
        assert first["plate_fee_cents"] == 0
        assert first["total_cents"] == 200000 * 140  # 28,000,000
        second = confirm_print_order(create_print_order(sel_second["id"], 200000)["id"])
        assert second["status"] == PrintOrderStatus.CONFIRMED.value, (
            "an aggregate of exactly 400,000 units is permitted"
        )

    def test_press_capacity_exceeded_rejects_third_order(self, api):
        """PRD §3.6: "the sum of `quantity` over already-confirmed orders
        sharing this `production_month`, plus this order's quantity, must not
        exceed the monthly press capacity of 400,000 units, with exactly
        400,000 permitted (else `ERR_PRESS_CAPACITY_EXCEEDED`)."
        PRD §3.6: "Submitted-but-unconfirmed orders consume no capacity."

        Design: Difficulty/resource_temporal_overlap/press_capacity_monthly_aggregate_boundary
        """
        set_logical_clock()
        titles = setup_five_titles()
        sel_first = setup_approved_selection(
            "2027-01", "INFANT", title_id=titles["INFANT"]["id"]
        )["selection"]
        sel_second = setup_approved_selection(
            "2027-01", "TODDLER", title_id=titles["TODDLER"]["id"]
        )["selection"]
        sel_third = setup_approved_selection(
            "2027-01", "TWO", title_id=titles["TWO"]["id"]
        )["selection"]
        confirm_print_order(create_print_order(sel_first["id"], 200000)["id"])
        confirm_print_order(create_print_order(sel_second["id"], 200000)["id"])
        order_third = create_print_order(sel_third["id"], 1)
        resp = api.confirm_print_order(order_third["id"], _PUBLISHER)
        validate_error(resp, ApiErrorId.ERR_PRESS_CAPACITY_EXCEEDED)
        after = validate_success(api.get_print_order(order_third["id"], _ADMIN))
        assert after["status"] == PrintOrderStatus.SUBMITTED.value
        assert after["unit_cents"] is None, "a rejected confirm locks no pricing"
        selection_after = validate_success(api.get_selection(sel_third["id"], _ADMIN))
        assert selection_after["status"] == SelectionStatus.APPROVED.value, (
            "a rejected confirm must not lock the selection"
        )


class TestConfirmValidationOrdering:
    def test_confirm_state_precondition_beats_capacity_check(self, api):
        """PRD §2.8: "When a request violates several rules at once, the
        earliest applicable check in this order produces the error, and later
        checks are not consulted" — state preconditions (check 7) precede
        capacity gates (check 12).
        PRD §3.6: "the order must be `SUBMITTED` and its referenced selection
        `APPROVED` (else `ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_precondition_beats_capacity_check
        """
        set_logical_clock()
        title = create_title("TODDLER")
        selection = setup_approved_selection("2026-12", "TODDLER", title_id=title["id"])[
            "selection"
        ]
        order = create_print_order(selection["id"], 500000)
        reopen_selection(selection["id"])
        resp = api.confirm_print_order(order["id"], _PUBLISHER)
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != ApiErrorId.ERR_PRESS_CAPACITY_EXCEEDED, (
            "the reopened selection's state fires before the capacity gate"
        )
        after = validate_success(api.get_print_order(order["id"], _ADMIN))
        assert after["status"] == PrintOrderStatus.SUBMITTED.value
        assert after["unit_cents"] is None

    def test_capacity_check_fires_once_state_allows(self, api):
        """PRD §3.6: "the press must have room — the sum of `quantity` over
        already-confirmed orders sharing this `production_month`, plus this
        order's quantity, must not exceed the monthly press capacity of
        400,000 units, with exactly 400,000 permitted (else
        `ERR_PRESS_CAPACITY_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_precondition_beats_capacity_check
        """
        set_logical_clock()
        title = create_title("TODDLER")
        selection = setup_approved_selection("2026-12", "TODDLER", title_id=title["id"])[
            "selection"
        ]
        order = create_print_order(selection["id"], 500000)
        reopen_selection(selection["id"])
        approve_selection(selection["id"], approver_id=ACM_THIRD_ID)
        resp = api.confirm_print_order(order["id"], _PUBLISHER)
        validate_error(resp, ApiErrorId.ERR_PRESS_CAPACITY_EXCEEDED)
        after = validate_success(api.get_print_order(order["id"], _ADMIN))
        assert after["status"] == PrintOrderStatus.SUBMITTED.value
