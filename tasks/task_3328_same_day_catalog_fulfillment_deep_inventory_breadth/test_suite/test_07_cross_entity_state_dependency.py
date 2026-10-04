"""State dependencies that cross entity boundaries."""

from test_helpers import (
    CURATOR,
    DCM,
    setup_draft_order,
    setup_order_scenario,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

SKU_BASE = 7000


def _sku(offset: int) -> str:
    return f"SKU-{SKU_BASE + offset}"


class TestReleaseRequiresItemCurationApproval:
    """The release transition's validity lives on a different entity entirely."""

    def test_revoking_the_review_blocks_an_otherwise_releasable_draft(self, api):
        """PRD §3.1: "an order may only be released — and only be created — when every
        line's item has reached `curation_review_state` `APPROVED`. A line whose item is
        still `UNREVIEWED` blocks the operation with `ERR_CURATION_NOT_APPROVED`
        (HTTP 409)."
        PRD §3.1: "A curator may revoke a batch's approval, which moves `review_status` to
        `REVOKED` and returns every item in the batch to `curation_review_state`
        `UNREVIEWED`, so the items stop being order-selectable until they are approved
        again."

        Design: Difficulty/cross_entity_state_dependency/order_release_requires_item_curation_approved
        """
        scenario = setup_draft_order(
            api,
            lines_spec=[{"price": 5000, "qty": 2, "bundle": 8, "on_hand": 10, "sku": _sku(1)}],
        )
        order = scenario["order"]
        starting_version = order["version"]

        validate_success(api.revoke_curation_review(scenario["review"]["id"], CURATOR))
        item = validate_success(api.get_item(scenario["items"][0]["id"], CURATOR))
        assert item["curation_review_state"] == "UNREVIEWED"

        response = api.release_order(order["id"], scenario["acct_headers"])
        validate_error(response, ApiErrorId.ERR_CURATION_NOT_APPROVED)

        after = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
        assert after["order_status"] == "DRAFT"
        assert after["fulfillment_status"] == "AWAITING_RELEASE"

    def test_a_rejected_release_does_not_advance_the_order_version(self, api):
        """PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
        is incremented by exactly 1 by each write that mutates the row".

        Design: Difficulty/cross_entity_state_dependency/order_release_requires_item_curation_approved
        """
        scenario = setup_draft_order(
            api,
            lines_spec=[{"price": 5000, "qty": 2, "bundle": 8, "on_hand": 10, "sku": _sku(2)}],
        )
        order = scenario["order"]
        validate_success(api.revoke_curation_review(scenario["review"]["id"], CURATOR))

        api.release_order(order["id"], scenario["acct_headers"])
        after = validate_success(api.get_order(order["id"], scenario["acct_headers"]))

        assert after["version"] == order["version"], (
            "the rejected release did not mutate the order row"
        )


class TestShipmentHoldsFollowDcPosture:
    """A shipment's state has no client-reachable lock — the center's posture drives it."""

    def _shipped(self, api):
        return setup_order_scenario(
            api,
            lines_spec=[{"price": 7000, "qty": 2, "bundle": 8, "on_hand": 6, "sku": _sku(3)}],
            target="SHIPPED",
            utc="2026-09-14T10:05:00Z",
        )

    def test_a_held_shipment_refuses_dispatch_until_the_hold_clears(self, api):
        """PRD §3.7: "when the center's `operations_posture` becomes `LOCKDOWN`, every
        shipment at that center sitting in `CUTOFF_CONFIRMED` automatically moves to
        `HELD` — no manager action is required."
        PRD §2.9: "State legality. The target resource must be in a state that permits the
        operation, and the transition must be one the state machine lists for that state;
        otherwise `ERR_INVALID_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/shipment_holds_follow_dc_posture_not_order_state
        """
        scenario = self._shipped(api)
        shipment = scenario["shipment"]

        validate_success(api.reeducate(scenario["dc"]["id"],
                                       {"hold_action": "RAISE", "reason": "quality hold"}, DCM))
        held = validate_success(api.get_shipment(shipment["id"], DCM))
        assert held["shipment_status"] == "HELD"

        response = api.dispatch_shipment(shipment["id"], DCM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    def test_clearing_the_hold_restores_the_shipment_and_dispatch_completes(self, api):
        """PRD §3.7: "When the center's last open quality or damage hold is cleared and
        its posture returns to `OPEN`, every `HELD` shipment at that center automatically
        returns to `CUTOFF_CONFIRMED`."
        PRD §3.7: "A `DCManager` dispatches a cutoff-confirmed shipment, moving
        `shipment_status` from `CUTOFF_CONFIRMED` to `DISPATCHED`, which is the shipment's
        terminal state."

        Design: Difficulty/cross_entity_state_dependency/shipment_holds_follow_dc_posture_not_order_state
        """
        scenario = self._shipped(api)
        shipment = scenario["shipment"]
        stamped_freight = shipment["freight_charge_cents"]

        validate_success(api.reeducate(scenario["dc"]["id"],
                                       {"hold_action": "RAISE", "reason": "quality hold"}, DCM))
        validate_success(api.reeducate(scenario["dc"]["id"], {"hold_action": "CLEAR"}, DCM))

        restored = validate_success(api.get_shipment(shipment["id"], DCM))
        assert restored["shipment_status"] == "CUTOFF_CONFIRMED"

        dispatched = validate_success(api.dispatch_shipment(shipment["id"], DCM))
        assert dispatched["shipment_status"] == "DISPATCHED"
        assert dispatched["freight_charge_cents"] == stamped_freight, (
            "the freight figure is identical across the LOCKDOWN cycle"
        )