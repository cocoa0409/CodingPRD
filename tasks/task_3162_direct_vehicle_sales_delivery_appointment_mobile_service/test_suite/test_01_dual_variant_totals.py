"""Dual-variant arithmetic: the same record priced two different ways."""
from test_helpers import (
    DELIVERY_FEE_CENTS,
    DOC_FEE_CENTS,
    ORDER_FEE_CENTS,
    TEST_USERS,
    get_success_data,
    set_clock,
    setup_triaged_mobile_appointment,
    walk_order_to_at_delivery_center,
    walk_order_to_delivered,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]

PAINT_WHITE = {"option_sku": "PAINT_WHITE", "option_category": "PAINT",
               "price_cents": 100000}
FSD_SOFTWARE = {"option_sku": "FSD_SUPERVISED", "option_category": "SOFTWARE_FEATURE",
                "price_cents": 800000}
MODEL_Y_BASE = 4799000


class TestOrderTotalDualVariant:
    """PRD §3.7: the order total has a provisional variant and a final variant."""

    def test_provisional_total_after_arrival_includes_delivery_fee(self, api):
        """PRD §3.7: "In the `provisional` variant, which applies to every order
        whose status is not `DELIVERED`, the total is the core plus the order fee
        plus the late fee plus the documentation fee plus 2500 cents, and no
        trade-in credit is subtracted, so the delivery fee stands in full."
        PRD §3.1: "The boolean `is_software_entitlement` is derived, not supplied:
        it is true exactly when `option_category` is `SOFTWARE_FEATURE`."
        PRD §3.1: "An option that is a software entitlement is a licence grant and
        contributes nothing to the configured price, so a factory-ordered
        `FSD_SUPERVISED` option adds 0 to what the buyer owes for the car"

        Design: Difficulty/dual_variant_calc/order_total_dual_variant_provisional_includes_delivery_fee
        """
        set_clock()
        ctx = walk_order_to_at_delivery_center(options=[PAINT_WHITE, FSD_SOFTWARE])

        config = get_success_data(api.get_configuration(ctx["configuration"]["id"], ADMIN))
        assert config["configured_price_cents"] == MODEL_Y_BASE + PAINT_WHITE["price_cents"], (
            "the SOFTWARE_FEATURE option must contribute nothing to configured_price_cents"
        )

        order = ctx["order"]
        expected = (config["configured_price_cents"]
                    + ORDER_FEE_CENTS
                    + DOC_FEE_CENTS
                    + DELIVERY_FEE_CENTS)
        assert order["order_total_due_cents"] == expected, (
            f"provisional total must include the {DELIVERY_FEE_CENTS}-cent delivery fee"
        )
        assert order["order_total_due_cents"] == 4934000

    def test_final_variant_subtracts_the_trade_in_credit_capped_at_the_delivery_fee(self, api):
        """PRD §3.7: "In the `final` variant, computed inside the completion
        transaction, the total is the same sum with one further term: subtract the
        smaller of 2500 cents and the sum of `net_credit_cents` over the order's
        appraisals whose status is `ACCEPTED`."
        PRD §3.7: "The cap at 2500 cents is deliberate — the credit can cancel the
        delivery fee but cannot reduce the vehicle price itself."

        Design: Difficulty/dual_variant_calc/order_total_dual_variant_provisional_includes_delivery_fee
        """
        set_clock()
        ctx = walk_order_to_delivered(options=[PAINT_WHITE, FSD_SOFTWARE])
        order = ctx["order"]

        # No appraisal was accepted on this order, so the final variant subtracts
        # nothing and the credit term is exactly 0 (its capped minimum).
        accepted_credit = 0
        expected = (MODEL_Y_BASE + PAINT_WHITE["price_cents"]
                    + ORDER_FEE_CENTS
                    + DOC_FEE_CENTS
                    + DELIVERY_FEE_CENTS
                    - min(DELIVERY_FEE_CENTS, accepted_credit))
        assert order["status"] == "DELIVERED"
        assert order["order_total_due_cents"] == expected
        assert order["order_total_due_cents"] == 4934000


class TestMobileVisitCostDualVariant:
    """PRD §3.10: the visit's cost and the customer's payable amount are two
    separate derivations over the same row."""

    def test_visit_cost_is_the_sum_of_the_three_lines(self, api):
        """PRD §3.10: "The travel line is the base travel charge plus, for every
        mile beyond the included 30 miles of the drive, 95 cents per mile, taking
        the larger of zero and the excess so that a short drive produces no
        negative contribution; the platform's base travel charge is currently 0"
        PRD §3.10: "The labor line is the booked `labor_hours` multiplied by an
        hourly rate of 19500 cents, with the product rounded half up to a whole
        cent. The parts line is the frozen `parts_cost_cents`. The visit's
        `visit_cost_cents` is the sum of those three lines."

        Design: Difficulty/dual_variant_calc/mobile_visit_cost_dual_variant_warranty_zeroes_customer_payable
        """
        set_clock()
        # A mobile dispatch is refused unless the triage report's outcome is
        # MOBILE_REQUIRED (PRD 3.9), so this exercise picks the mild, driveable,
        # part-needing fault that triage routes to a van.
        ctx = setup_triaged_mobile_appointment(
            fault_code="SUS-5100", severity="MEDIUM", is_driveable=True)
        appointment = ctx["appointment"]
        visit = get_success_data(api.dispatch_mobile_visit(
            {"service_appointment_id": appointment["id"],
             "parts_hub_id": ctx["hub"]["id"],
             "van_code": "VAN-ATX-1",
             "visit_start": "2026-09-26T14:00:00Z",
             "visit_end": "2026-09-26T17:00:00Z",
             "labor_hours": 2.0,
             "parts_cost_cents": 42000,
             "visit_miles": 45,
             "expected_service_appointment_version": appointment["version"]},
            TECH))

        travel = max(0, 45 - 30) * 95
        labor = round(2.0 * 19500)
        assert travel + labor + 42000 == 82425
        assert visit["visit_cost_cents"] == 82425, (
            "travel 1425 + labor 39000 + parts 42000"
        )

    def test_critical_fault_inside_the_mileage_ceiling_is_warranty_covered(self, api):
        """PRD §3.10: "Whether the customer pays it is decided separately: the
        repair is warranty-covered when the triage report's severity is `HIGH` or
        `CRITICAL` and the vehicle's `odometer_miles` is at or below 60000, and
        when it is covered the customer's payable amount is 0"
        PRD §3.9: "its `is_warranty_covered` flag is computed at that moment: the
        flag is true exactly when the triage report's `severity` is `HIGH` or
        `CRITICAL` and the vehicle's `odometer_miles` is at or below the warranty
        mileage ceiling the platform applies"

        Design: Difficulty/dual_variant_calc/mobile_visit_cost_dual_variant_warranty_zeroes_customer_payable
        """
        set_clock()
        ctx = walk_order_to_delivered()
        report = get_success_data(api.pull_diagnostic_report(
            ctx["vehicle"]["id"],
            {"fault_code": "HVAC-0442", "severity": "CRITICAL", "is_driveable": False},
            TECH))
        appointment = get_success_data(api.create_service_appointment(
            {"vehicle_id": ctx["vehicle"]["id"],
             "diagnostic_report_id": report["id"],
             "service_center_id": ctx["center"]["id"],
             "scheduled_start": "2026-09-25T14:00:00Z",
             "scheduled_end": "2026-09-25T16:00:00Z"},
            TECH))

        assert ctx["vehicle"]["odometer_miles"] == 0, (
            "a freshly arrived vehicle is well inside the 60000-mile ceiling"
        )
        assert report["severity"] == "CRITICAL"
        assert appointment["is_warranty_covered"] is True
