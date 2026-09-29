"""The money picture of a collision estimate: labor rates, parts pricing and the split.

Every figure the shop quotes is settled by arithmetic the requirements pin cent by
cent. A supplier discount lands on one unit before the quantity multiplies it. A
labor line is priced at whichever is lower, the shop's posted hourly rate or the
insurer program's ceiling for that labor family. The volume rebate on parts applies
one average rate to the whole gross the moment the gross reaches a tier floor. Paint
and materials stop at a declared cap. And when the owner upgrades to an
original-equipment part, the upgrade share moves off the insurer and onto the owner.

These tests drive orders through teardown, blueprint and estimate lock, price parts
with real suppliers, and then read the eight-step totals back off the repair order.
"""

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Local helpers: the two estimate shapes these tests reuse
# ---------------------------------------------------------------------------
_WORKED_PASS_LINES = [
    {"operation_code": "REF-A", "labor_type": "REFINISH", "guide_hours": 2.8, "two_stage": True},
    {"operation_code": "REF-B", "labor_type": "REFINISH", "guide_hours": 2.2, "is_adjacent_panel": True},
    {"operation_code": "REF-C", "labor_type": "REFINISH", "guide_hours": 1.6, "is_blend": True},
    {"operation_code": "BDY-1", "labor_type": "BODY", "guide_hours": 4.5},
    {"operation_code": "FRM-1", "labor_type": "FRAME", "guide_hours": 3.0},
]

_ONE_BODY_LINE = [{"operation_code": "BDY-1", "labor_type": "BODY", "guide_hours": 4.5}]


def _locked_body_order(api, insurer_overrides=None, order_overrides=None, customer_overrides=None):
    """A locked order carrying the single 4.5-hour body operation: labor 27000, supplies 1080."""
    order_defaults = {"deductible_cents": 25000, "initial_authorized_cents": 400000}
    order_defaults.update(order_overrides or {})
    insurer_defaults = {"rate_ceiling_cents": dict(C.CEILINGS_BELOW_POSTED)}
    insurer_defaults.update(insurer_overrides or {})
    return fx.locked_world(
        api,
        lines=list(_ONE_BODY_LINE),
        customer_overrides=customer_overrides,
        insurer_overrides=insurer_defaults,
        order_overrides=order_defaults,
    )


class TestPartsExtensionRoundsPerUnit:
    """The supplier discount is rounded on one unit, and only then multiplied out."""

    def test_an_aftermarket_line_of_three_units_rounds_the_unit_before_the_quantity(self, api):
        """A 10,101-cent clip set at a 3.5 percent discount over three units extends to 29,241.

        PRD: "A supplier discount lands on **one unit**: the agreed unit price is multiplied by one minus the supplier's fractional discount, that product is rounded half up to a whole cent, and only then is the rounded per-unit figure multiplied by the quantity."
        PRD: "Multiplying first and rounding afterwards would give 29,242 for that second line — one cent high — and that cent propagates into the parts gross, possibly into the rebate tier, and out into the owner's share."
        Design: Difficulty/combinatorial_formula/parts_extended_price_rounds_per_unit_before_multiplying_quantity
        """
        world = _locked_body_order(
            api,
            insurer_overrides={
                "aftermarket_allowed": True,
                "alternate_parts_min_vehicle_age_years": 3,
                "parts_price_ceiling_pct": 1.1,
            },
            order_overrides={"vehicle_model_year": 2019},
        )
        vendor = fx.create_vendor(
            api,
            name="Valley Aftermarket",
            vendor_type="AFTERMARKET_DISTRIBUTOR",
            part_types_offered=["AFTERMARKET"],
            discount_pct=0.035,
            max_qty_per_line=4,
        )
        quoted = fx.quoted_part(
            api,
            world["line_ids"][0],
            vendor["id"],
            10101,
            part_number="AM-9001",
            part_description="Bumper clip set",
            part_type="AFTERMARKET",
            list_price_cents=10101,
            qty=3,
        )

        line = fx.accept_price(api, quoted["id"])

        A.assert_parts_line_state(
            line, procurement_status="PRICE_LOCKED", authorization_status="INSURER_ALLOWED"
        )
        A.assert_cents(line["unit_extended_cents"], 9747, "unit_extended_cents")
        A.assert_cents(line["extended_price_cents"], 29241, "extended_price_cents")
        assert line["extended_price_cents"] != 29242, (
            "the sum-then-round order is one cent high on this line"
        )

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            parts_gross_cents=29241,
            parts_discount_cents=0,
            parts_subtotal_cents=29241,
            labor_subtotal_cents=27000,
            supplies_fee_cents=1080,
            pre_tax_total_cents=57321,
        )

    def test_an_original_equipment_unit_at_a_half_cent_rounds_up_before_extending(self, api):
        """An 84,500-cent fender at a 7.5 percent discount rounds 78,162.5 up to 78,163.

        PRD: "Two illustrations of the unit-first rule: an `OEM` line at a unit price of 84,500 cents with a 7.5 percent discount and a quantity of 1 gives a rounded unit figure of 78,163 (from 78,162.5, rounded half up) and therefore an extended price of 78,163; an `AFTERMARKET` line at 10,101 cents with a 3.5 percent discount and a quantity of 3 gives a rounded unit figure of 9,747 (from 9,747.465) and an extended price of 29,241."
        PRD: "`extended_price_cents` is then `unit_extended_cents` multiplied by `qty` less `returned_qty`."
        Design: Difficulty/combinatorial_formula/parts_extended_price_rounds_per_unit_before_multiplying_quantity
        """
        world = _locked_body_order(api, insurer_overrides={"parts_price_ceiling_pct": 1.1})
        vendor = fx.create_vendor(
            api,
            name="Metro OEM Parts",
            vendor_type="OEM_DEALER",
            part_types_offered=["OEM"],
            discount_pct=0.075,
            max_qty_per_line=4,
        )
        quoted = fx.quoted_part(
            api,
            world["line_ids"][0],
            vendor["id"],
            84500,
            part_number="OEM-5501",
            part_description="Fender assembly",
            part_type="OEM",
            list_price_cents=84500,
            qty=1,
        )

        line = fx.accept_price(api, quoted["id"])

        A.assert_extension(line, unit_extended=78163, extended=78163)
        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            parts_gross_cents=78163,
            parts_discount_cents=0,
            parts_subtotal_cents=78163,
            pre_tax_total_cents=106243,
            insurer_authorized_cents=81243,
            customer_pay_cents=25000,
        )


class TestEstimateTotalsRateCeilingAndAuthorisation:
    """Two nested choices decide the money: the lesser rate per line, the capped split."""

    def test_the_worked_pass_prices_every_line_at_the_insurer_ceiling(self, api):
        """Five labor lines and two priced parts settle at a pre-tax total of 191,604.

        PRD: "For each approved labor line, `effective_rate_cents` is the lesser of the shop's posted rate for that line's `labor_type` (§2.10) and the insurer program's `rate_ceiling_cents` entry for the same `labor_type`."
        PRD: "A worked pass through those steps: with insurer ceilings of 6,000 for `BODY`, 8,000 for `FRAME`, 5,800 for `REFINISH`, 11,000 for `MECHANICAL` and 8,800 for `ALUMINUM_BODY`, a `deductible_cents` of 25,000, an `initial_authorized_cents` of 400,000, final refinish allocations of 3.1, 1.8 and 0.8 hours plus a 4.5-hour `BODY` line and a 3.0-hour `FRAME` line, and two priced parts lines extending to 78,163 and 29,241 cents: step 1 gives 17,980, 10,440, 4,640, 27,000 and 24,000, so `labor_subtotal_cents` is 84,060."
        Design: Difficulty/combinatorial_formula/estimate_totals_nested_min_max_over_rate_ceiling_and_authorisation
        """
        world = fx.locked_world(
            api,
            lines=list(_WORKED_PASS_LINES),
            insurer_overrides={
                "rate_ceiling_cents": dict(C.CEILINGS_BELOW_POSTED),
                "aftermarket_allowed": True,
                "alternate_parts_min_vehicle_age_years": 3,
                "parts_price_ceiling_pct": 1.1,
            },
            order_overrides={
                "deductible_cents": 25000,
                "initial_authorized_cents": 400000,
                "vehicle_model_year": 2019,
            },
        )
        oem_vendor = fx.create_vendor(
            api,
            name="Metro OEM Parts",
            vendor_type="OEM_DEALER",
            part_types_offered=["OEM"],
            discount_pct=0.075,
            max_qty_per_line=4,
        )
        aftermarket_vendor = fx.create_vendor(
            api,
            name="Valley Aftermarket",
            vendor_type="AFTERMARKET_DISTRIBUTOR",
            part_types_offered=["AFTERMARKET"],
            discount_pct=0.035,
            max_qty_per_line=4,
        )
        body_line_id = world["line_ids"][3]
        fx.price_locked_part(
            api,
            body_line_id,
            oem_vendor["id"],
            84500,
            part_number="OEM-5501",
            part_description="Fender assembly",
            part_type="OEM",
            list_price_cents=84500,
            qty=1,
        )
        second = fx.quoted_part(
            api,
            body_line_id,
            aftermarket_vendor["id"],
            10101,
            part_number="AM-9001",
            part_description="Clip set",
            part_type="AFTERMARKET",
            list_price_cents=10101,
            qty=3,
        )

        fx.accept_price(api, second["id"])

        two_stage_line = fx.read_estimate_line(api, world["line_ids"][0])
        A.assert_hours(two_stage_line["allocated_hours"], 3.1, "allocated_hours")
        A.assert_cents(two_stage_line["effective_rate_cents"], 5800, "effective_rate_cents")
        A.assert_cents(two_stage_line["line_amount_cents"], 17980, "line_amount_cents")
        body_line = fx.read_estimate_line(api, body_line_id)
        A.assert_cents(body_line["effective_rate_cents"], 6000, "effective_rate_cents")
        A.assert_cents(body_line["line_amount_cents"], 27000, "line_amount_cents")
        frame_line = fx.read_estimate_line(api, world["line_ids"][4])
        A.assert_cents(frame_line["line_amount_cents"], 24000, "line_amount_cents")

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            labor_subtotal_cents=84060,
            supplies_fee_cents=3362,
            parts_gross_cents=107404,
            parts_discount_cents=3222,
            parts_subtotal_cents=104182,
            betterment_cents=0,
            pre_tax_total_cents=191604,
            insurer_authorized_cents=166604,
            customer_pay_cents=25000,
        )
        A.assert_customer_pay_split(order)
        A.assert_posture(order, "OPEN")

    def test_the_posted_shop_rate_wins_when_the_insurer_ceiling_sits_above_it(self, api):
        """With ceilings above the rate card, the same five lines price at the posted rates.

        PRD: "Whenever labor is priced, the rate actually applied to a line is the **lesser** of the shop's posted rate for that line's labor type and the insurer program's ceiling for the same labor type."
        PRD: "Against those ceilings stands the shop's own posted hourly rate card, which is a system constant rather than configuration: body work is posted at 6,500 cents per hour, frame work at 8,500, refinish at 6,000, mechanical at 12,500, and aluminium body work at 9,500."
        Design: Difficulty/combinatorial_formula/estimate_totals_nested_min_max_over_rate_ceiling_and_authorisation
        """
        world = fx.locked_world(
            api,
            lines=list(_WORKED_PASS_LINES),
            insurer_overrides={"rate_ceiling_cents": dict(C.CEILINGS_ABOVE_POSTED)},
            order_overrides={"deductible_cents": 25000, "initial_authorized_cents": 400000},
        )

        two_stage_line = fx.read_estimate_line(api, world["line_ids"][0])
        A.assert_cents(two_stage_line["effective_rate_cents"], 6000, "effective_rate_cents")
        A.assert_cents(two_stage_line["line_amount_cents"], 18600, "line_amount_cents")
        body_line = fx.read_estimate_line(api, world["line_ids"][3])
        A.assert_cents(body_line["effective_rate_cents"], 6500, "effective_rate_cents")
        A.assert_cents(body_line["line_amount_cents"], 29250, "line_amount_cents")
        frame_line = fx.read_estimate_line(api, world["line_ids"][4])
        A.assert_cents(frame_line["effective_rate_cents"], 8500, "effective_rate_cents")
        A.assert_cents(frame_line["line_amount_cents"], 25500, "line_amount_cents")

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            labor_subtotal_cents=88950,
            supplies_fee_cents=3558,
            parts_subtotal_cents=0,
            pre_tax_total_cents=92508,
            insurer_authorized_cents=67508,
            customer_pay_cents=25000,
        )
        A.assert_posture(order, "OPEN")

    def test_the_insurer_share_stops_at_the_authorisation_ceiling(self, api):
        """An authorisation of only 1,000 cents caps the insurer and leaves the rest to the owner.

        PRD: "`insurer_authorized_cents` is then the pre-tax total less the `deductible_cents` less the `betterment_cents`, capped at that ceiling, and floored at zero — the insurer never funds the deductible and never funds the betterment, and never pays beyond what it authorised."
        PRD: "`customer_pay_cents` is `pre_tax_total_cents` less `insurer_authorized_cents`."
        Design: Difficulty/combinatorial_formula/estimate_totals_nested_min_max_over_rate_ceiling_and_authorisation
        """
        world = _locked_body_order(api, order_overrides={"initial_authorized_cents": 1000})

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            labor_subtotal_cents=27000,
            supplies_fee_cents=1080,
            pre_tax_total_cents=28080,
            insurer_authorized_cents=1000,
            customer_pay_cents=27080,
        )
        A.assert_customer_pay_split(order)
        A.assert_posture(order, "OPEN")


class TestPartsVolumeRebateTierFloor:
    """One cent of parts gross decides whether the three-percent rebate applies at all."""

    def _priced_oem_order(self, api, list_price_cents, quoted_unit_price_cents, claim_number):
        world = _locked_body_order(
            api,
            insurer_overrides={"parts_price_ceiling_pct": 1.1},
            order_overrides={"claim_number": claim_number},
        )
        vendor = fx.create_vendor(
            api,
            name="Metro OEM Parts",
            vendor_type="OEM_DEALER",
            part_types_offered=["OEM"],
            discount_pct=0,
            max_qty_per_line=4,
        )
        quoted = fx.quoted_part(
            api,
            world["line_ids"][0],
            vendor["id"],
            quoted_unit_price_cents,
            part_number="OEM-2201",
            part_description="Door shell",
            part_type="OEM",
            list_price_cents=list_price_cents,
            qty=1,
        )
        line = fx.accept_price(api, quoted["id"])
        return world, line

    def test_a_parts_gross_one_cent_under_the_tier_floor_earns_no_rebate(self, api):
        """A door shell at 99,999 cents leaves the parts subtotal untouched at 99,999.

        PRD: "`parts_discount_cents` applies an **average** rate to the whole parts gross rather than a marginal rate per tier: the rate is zero when `parts_gross_cents` is below 100,000 cents, three percent when it is at least 100,000 cents but below 500,000 cents, and five percent when it is 500,000 cents or more."
        PRD: "`parts_subtotal_cents` is then `parts_gross_cents` less `parts_discount_cents`."
        Design: Difficulty/boundary_precision_check/parts_volume_rebate_tier_starts_at_exactly_100000_on_accept_price
        """
        world, line = self._priced_oem_order(api, 99999, 99999, "CLM-77141A")

        A.assert_extension(line, unit_extended=99999, extended=99999)
        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            parts_gross_cents=99999,
            parts_discount_cents=0,
            parts_subtotal_cents=99999,
            pre_tax_total_cents=128079,
            customer_pay_cents=25000,
        )
        A.assert_posture(order, "OPEN")

    def test_a_parts_gross_exactly_on_the_tier_floor_earns_the_three_percent_rebate(self, api):
        """A door shell at 100,000 cents earns a 3,000-cent rebate on the whole gross.

        PRD: "`parts_discount_cents` is the parts gross multiplied by that single rate, rounded half up."
        PRD: "`pre_tax_total_cents` is `labor_subtotal_cents` plus `supplies_fee_cents` plus `parts_subtotal_cents`."
        Design: Difficulty/boundary_precision_check/parts_volume_rebate_tier_starts_at_exactly_100000_on_accept_price
        """
        world, line = self._priced_oem_order(api, 100000, 100000, "CLM-77141B")

        A.assert_extension(line, unit_extended=100000, extended=100000)
        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            parts_gross_cents=100000,
            parts_discount_cents=3000,
            parts_subtotal_cents=97000,
            pre_tax_total_cents=125080,
            customer_pay_cents=25000,
        )
        A.assert_posture(order, "OPEN")


class TestSuppliesFeeCap:
    """Paint and materials are four percent of labor, until the declared cap binds."""

    def test_a_sixty_hour_mechanical_line_pays_the_capped_supplies_fee(self, api):
        """Labor of 660,000 would compute 26,400 of supplies, so the fee stops at 25,000.

        PRD: "`supplies_fee_cents` is four percent of `labor_subtotal_cents`, rounded half up, but capped: it is the **lesser** of that computed figure and 25,000 cents."
        PRD: "And non-refinish approved lines are not part of this allocation at all: their `allocated_hours` is simply their `guide_hours`, verbatim, with no deduction of any kind."
        Design: Corner/calculations/supplies_fee_stops_at_the_declared_cap
        """
        world = fx.locked_world(
            api,
            lines=[{"operation_code": "MEC-1", "labor_type": "MECHANICAL", "guide_hours": 60.0}],
            findings=[{"panel_code": "ENG-CRADLE", "severity": "SEVERE"}],
            insurer_overrides={"rate_ceiling_cents": dict(C.CEILINGS_BELOW_POSTED)},
            order_overrides={"deductible_cents": 25000, "initial_authorized_cents": 900000},
        )

        mechanical_line = fx.read_estimate_line(api, world["line_ids"][0])
        A.assert_hours(mechanical_line["allocated_hours"], 60.0, "allocated_hours")
        A.assert_cents(mechanical_line["effective_rate_cents"], 11000, "effective_rate_cents")
        A.assert_cents(mechanical_line["line_amount_cents"], 660000, "line_amount_cents")

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            labor_subtotal_cents=660000,
            supplies_fee_cents=25000,
            parts_subtotal_cents=0,
            betterment_cents=0,
            pre_tax_total_cents=685000,
            insurer_authorized_cents=660000,
            customer_pay_cents=25000,
        )
        A.assert_posture(order, "OPEN")


class TestPartsRebateAverageRate:
    """The top tier rebates every cent of the gross, not merely the excess over the floor."""

    def test_a_six_hundred_thousand_cent_gross_is_rebated_at_five_percent_throughout(self, api):
        """A 600,000-cent door assembly earns 30,000 of rebate, not the marginal 17,000.

        PRD: "`parts_discount_cents` applies an **average** rate to the whole parts gross rather than a marginal rate per tier: the rate is zero when `parts_gross_cents` is below 100,000 cents, three percent when it is at least 100,000 cents but below 500,000 cents, and five percent when it is 500,000 cents or more."
        PRD: "`parts_gross_cents` is the sum of `extended_price_cents` over the order's qualifying parts lines."
        Design: Corner/calculations/parts_rebate_applies_the_average_rate_to_the_whole_gross
        """
        world = _locked_body_order(api, order_overrides={"initial_authorized_cents": 900000})
        vendor = fx.create_vendor(
            api,
            name="Metro Honda",
            vendor_type="OEM_DEALER",
            part_types_offered=["OEM"],
            discount_pct=0,
            max_qty_per_line=5,
        )
        quoted = fx.quoted_part(
            api,
            world["line_ids"][0],
            vendor["id"],
            600000,
            part_number="OEM-9032",
            part_description="Complete door assembly",
            part_type="OEM",
            list_price_cents=700000,
            qty=1,
        )

        line = fx.accept_price(api, quoted["id"])

        A.assert_parts_line_state(line, procurement_status="PRICE_LOCKED")
        A.assert_cents(line["unit_price_cents"], 600000, "unit_price_cents")
        A.assert_extension(line, unit_extended=600000, extended=600000)

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            parts_gross_cents=600000,
            parts_discount_cents=30000,
            parts_subtotal_cents=570000,
            pre_tax_total_cents=598080,
            insurer_authorized_cents=573080,
            customer_pay_cents=25000,
        )


class TestBettermentSplit:
    """An owner-chosen original-equipment upgrade is funded by the owner, not the insurer."""

    def test_an_original_equipment_upgrade_puts_the_upgrade_share_on_the_owner(self, api):
        """A 20,000-cent upgrade adds 4,000 of betterment, so the owner pays 29,000.

        PRD: "`betterment_cents` is the sum, over the qualifying parts lines whose `oem_upgrade` flag is true, of each line's `unit_extended_cents` multiplied by its `qty` and then by 0.2, each such product rounded half up before it is added."
        PRD: "And last of all, the order's `customer_pay_cents` must not exceed the sum of its `deductible_cents` and its `betterment_cents`, or the request is refused with `ERR_AUTHORIZED_AMOUNT_EXCEEDED` — the owner's exposure has to stay inside what the insurer authorised and the owner agreed."
        Design: Corner/calculations/betterment_moves_the_upgrade_share_onto_the_customer
        """
        world = _locked_body_order(
            api,
            insurer_overrides={
                "aftermarket_allowed": True,
                "alternate_parts_min_vehicle_age_years": 5,
            },
            order_overrides={"vehicle_model_year": 2015},
        )
        vendor = fx.create_vendor(
            api,
            name="Uptown Honda",
            vendor_type="OEM_DEALER",
            part_types_offered=["OEM"],
            discount_pct=0,
            max_qty_per_line=5,
        )
        quoted = fx.quoted_part(
            api,
            world["line_ids"][0],
            vendor["id"],
            20000,
            part_number="OEM-9033",
            part_description="Door shell, OEM upgrade",
            part_type="OEM",
            list_price_cents=25000,
            qty=1,
            oem_upgrade=True,
        )

        line = fx.accept_price(api, quoted["id"])

        assert line["oem_upgrade"] is True, "the line was created as an owner-chosen upgrade"
        A.assert_parts_line_state(line, authorization_status="INSURER_ALLOWED")
        A.assert_extension(line, unit_extended=20000, extended=20000)

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            parts_gross_cents=20000,
            parts_discount_cents=0,
            parts_subtotal_cents=20000,
            betterment_cents=4000,
            pre_tax_total_cents=48080,
            insurer_authorized_cents=19080,
            customer_pay_cents=29000,
        )
        assert order["customer_pay_cents"] == order["deductible_cents"] + order["betterment_cents"], (
            "the owner's share is exactly the deductible plus the upgrade share"
        )
        A.assert_posture(order, "OPEN")

        ordered = fx.place_parts_order(api, line["id"], "2026-08-05T00:00:00Z")
        A.assert_parts_line_state(ordered, procurement_status="ORDERED")


class TestReconditionedCoreCharge:
    """A core charge joins the per-unit figure after the discount rounds, once per unit."""

    def test_a_reconditioned_core_charge_joins_every_unit_after_the_discount_rounds(self, api):
        """8,450 at 7.5 percent rounds to 7,816, the 5,000 core lands on each of two units.

        PRD: "On success `unit_price_cents` is frozen at the accepted quote and the per-unit extension runs: `unit_extended_cents` is the `unit_price_cents` multiplied by one minus the supplier's `discount_pct`, rounded half up to a whole cent, plus the supplier's `core_charge_cents` when — and only when — the line's `part_type` is `RECONDITIONED`."
        PRD: "Otherwise, if the owner's `preferred_alternate_parts_ok` is true, the line is created already `CUSTOMER_CONSENTED` on the strength of that standing written preference."
        Design: Corner/calculations/reconditioned_core_charge_is_added_after_the_discount_rounds_and_once_per_unit
        """
        world = _locked_body_order(
            api,
            customer_overrides={
                "full_name": "Eli Rune",
                "preferred_alternate_parts_ok": True,
            },
            insurer_overrides={
                "reconditioned_allowed": True,
                "alternate_parts_min_vehicle_age_years": 10,
            },
            order_overrides={"vehicle_model_year": 2019},
        )
        vendor = fx.create_vendor(
            api,
            name="Corefirst Reman",
            vendor_type="RECONDITIONER",
            part_types_offered=["RECONDITIONED"],
            discount_pct=0.075,
            core_charge_cents=5000,
            max_qty_per_line=5,
        )
        quoted = fx.quoted_part(
            api,
            world["line_ids"][0],
            vendor["id"],
            8450,
            part_number="REM-9034",
            part_description="Reman headlamp module",
            part_type="RECONDITIONED",
            list_price_cents=8450,
            qty=2,
        )

        line = fx.accept_price(api, quoted["id"])

        A.assert_extension(line, unit_extended=12816, extended=25632)
        A.assert_parts_line_state(
            line, procurement_status="PRICE_LOCKED", authorization_status="CUSTOMER_CONSENTED"
        )

        order = fx.read_order(api, world["order_id"])
        A.assert_totals(
            order,
            parts_gross_cents=25632,
            parts_discount_cents=0,
            parts_subtotal_cents=25632,
            betterment_cents=0,
            pre_tax_total_cents=53712,
            insurer_authorized_cents=28712,
            customer_pay_cents=25000,
        )
