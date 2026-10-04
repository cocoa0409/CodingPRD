"""Validation pipeline ordering: paired failures resolve to the earlier check.

Instance business_safety_vs_business_referential_conflict_on_order_create was
evaluated and SKIPPED: the PRD's posture gate (§2.10 item 8) applies to order
submission, vehicle authorization, and teaming approval — not to order
creation, where the pinned-list check (§2.10 item 14) governs. The asserted
pairing (ERR_AGREEMENT_NOT_GOOD_STANDING before ERR_PRICE_LIST_NOT_ACTIVE on
POST /orders) is therefore not uniquely derivable from the PRD.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_cleared_order,
    create_order,
    setup_active_chain,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["reseller_ops_headers"]


class TestStateBeforeBusinessFiscalOnDeliver:
    def test_deliver_draft_order_reports_invalid_state_not_ceiling(self, api):
        """PRD §2.10: "Every request passes through a fixed validation
        pipeline. The pipeline is evaluated in the order below; the first
        failing check produces the response."
        PRD §2.10: "State validity — the target entity must be in a state
        from which the requested transition is valid; failure yields
        ERR_INVALID_STATE (HTTP 409). Applies to all action endpoints."
        PRD §2.10: "Vehicle ceiling per buyer tier — delivery must not
        push tier-keyed consumption above the vehicle ceiling; failure yields
        ERR_VEHICLE_CEILING_EXCEEDED (HTTP 422). Applies to order delivery."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_conflict_on_deliver
        """
        # Vehicle ceiling 15000; one DELIVERED order consumes 10000; a DRAFT
        # order for another 10000 would exceed the ceiling if state allowed.
        _, _, vehicle, price_list = setup_active_chain(
            vehicle_overrides={"ceiling_cents": 15000},
        )
        o1 = create_cleared_order(vehicle["id"], price_list["id"])
        validate_success(api.deliver_order(o1["id"], OPS))
        o2 = create_order(vehicle["id"], price_list["id"])
        resp = api.deliver_order(o2["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        o2 = validate_success(api.get_order(o2["id"], OPS))
        assert o2["billing_status"] == "UNBILLED"

    def test_deliver_unsubmitted_order_leaves_billing_unbilled(self, api):
        """PRD §3.6: "Delivery requires the compliance dimension to be CLEARED
        and the billing dimension to still be UNBILLED, and it is the only
        point at which the vehicle ceiling is enforced (§3.2): consumption
        summed across the vehicle's delivered-and-billed orders sharing this
        order's buyer_tier, plus this order's order_total_cents, must not
        exceed ceiling_cents; equality is allowed and one cent over is
        rejected with ERR_VEHICLE_CEILING_EXCEEDED."
        PRD §2.10: "The pipeline is evaluated in the order below; the first
        failing check produces the response."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_conflict_on_deliver
        """
        _, _, vehicle, price_list = setup_active_chain(
            vehicle_overrides={"ceiling_cents": 15000},
        )
        o1 = create_cleared_order(vehicle["id"], price_list["id"])
        validate_success(api.deliver_order(o1["id"], OPS))
        # Second order: deliver before submit — compliance DRAFT, so state
        # validity (item 5) fails before the ceiling check (item 17) is read.
        o2 = create_order(vehicle["id"], price_list["id"])
        resp = api.deliver_order(o2["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        o2 = validate_success(api.get_order(o2["id"], OPS))
        assert o2["billing_status"] == "UNBILLED"
        assert o2["compliance_status"] == "DRAFT"
