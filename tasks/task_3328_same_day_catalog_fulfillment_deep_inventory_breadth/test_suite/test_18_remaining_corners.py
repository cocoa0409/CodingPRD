"""Remaining corners: terminal re-drives and the automatic posture threshold."""

from test_helpers import (
    DCM,
    PICKER,
    account_headers,
    setup_account,
    setup_center,
    setup_clock,
    setup_curated_items,
    setup_order_scenario,
    setup_pick_shortage_with_claim,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import ApiErrorId

TERMINAL_OR_STATE = [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]


def test_a_cancelled_order_cannot_be_allocated(api):
    """PRD §3.3: "In all three cases the resulting order_status is the terminal value
    `CANCELLED`."
    PRD §2.9: "State legality. The target resource must be in a state that permits the
    operation, and the transition must be one the state machine lists for that state;
    otherwise `ERR_INVALID_STATE` (409). This guards every state-transition operation."

    Design: Corner/state_machines/cancelled_order_cannot_be_allocated
    """
    scenario = setup_order_scenario(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 5, "sku": "SM-1101"}],
        target="RELEASED",
    )
    headers = scenario["acct_headers"]
    cancelled = validate_success(api.cancel_order(scenario["order"]["id"], headers))
    assert cancelled["order_status"] == "CANCELLED"

    response = api.allocate_order(
        scenario["order"]["id"], {"expected_order_version": cancelled["version"]}, headers)
    validate_error_is_one_of(response, TERMINAL_OR_STATE)

    after = validate_success(api.get_order(scenario["order"]["id"], headers))
    assert after["order_status"] == "CANCELLED"
    assert after["fulfillment_status"] == "AWAITING_RELEASE"
    assert after["allocated_dc_id"] is None

    stock = validate_success(api.get_stock(scenario["stock_rows"][0]["id"], DCM))
    assert stock["reserved_units"] == 0, "the refused allocation reserved nothing"


def test_a_resolved_claim_refuses_a_second_resolve(api):
    """PRD §3.6: "From `RESUMED`, a manager may resolve the claim, which sets
    `claim_status` `RESOLVED` and `disposition` `ZERO_CHARGE_RESHIP` and decrements the
    account's `open_claim_count` by 1."
    PRD §2.9: "The target resource must not already sit in one of its declared terminal
    states; otherwise `ERR_ALREADY_TERMINAL` (409)."

    Design: Corner/state_machines/claim_and_shipment_cannot_be_re_driven_from_their_terminal_states
    """
    scenario = setup_pick_shortage_with_claim(
        api, line_units=3, actual_units=1, price=2500, on_hand=5,
        utc="2026-09-14T10:05:00Z", sku="SM-1201")
    claim = scenario["claim"]

    resumed = validate_success(api.resume_claim_fulfillment(claim["id"], PICKER))
    assert resumed["claim_status"] == "RESUMED"

    resolved = validate_success(api.resolve_claim(claim["id"], DCM))
    assert resolved["claim_status"] == "RESOLVED"
    after_first = validate_success(api.get_account(scenario["acct"]["id"], DCM))
    assert after_first["open_claim_count"] == 0

    again = api.resolve_claim(claim["id"], DCM)
    validate_error_is_one_of(again, TERMINAL_OR_STATE)

    still = validate_success(api.get_damage_claim(claim["id"], DCM))
    assert still["claim_status"] == "RESOLVED"
    after_second = validate_success(api.get_account(scenario["acct"]["id"], DCM))
    assert after_second["open_claim_count"] == 0, (
        "the rejected second resolve did not decrement the counter a second time"
    )


class TestDcPostureLifecycleIsAutomaticOnTheStockThreshold:
    """The OPEN/RESTRICTED axis follows the center's own reservation arithmetic."""

    def _allocated(self, api):
        setup_clock(api)
        bos = setup_center(api, code="BOS", inbound_capacity_units=10)
        acct = setup_account(api)
        catalog = setup_curated_items(
            api,
            specs=[{"price": 1000, "bundle": 20, "on_hand": 20, "sku": "PS-1001"}],
            account=acct, dc=bos, sku_prefix="PS")
        headers = account_headers(acct)
        order = validate_success(api.create_order(
            {"account_id": acct["id"],
             "lines": [{"item_id": catalog["items"][0]["id"], "quantity": 1}
                       for _ in range(9)]}, headers), 201)
        released = validate_success(api.release_order(order["id"], headers))
        allocated = validate_success(api.allocate_order(
            order["id"], {"expected_order_version": released["version"]}, headers))
        return {"dc": bos, "acct": acct, "headers": headers, "order": allocated,
                "stock_id": catalog["stock_rows"][0]["id"]}

    def test_the_inclusive_threshold_turns_the_center_restricted(self, api):
        """PRD §3.8: "It is `RESTRICTED` when it has no open hold and its
        `inbound_reserved_units` is at or above that same threshold."
        PRD §3.8: "The threshold comparison is inclusive at the boundary in a way
        implementations commonly get wrong: exactly the ceiling of capacity multiplied by
        the reserve ratio reserved units is already `RESTRICTED`, while one unit fewer is
        still `OPEN`."

        Design: Corner/state_machines/dc_posture_lifecycle_is_automatic_on_the_stock_threshold
        """
        context = self._allocated(api)

        after = validate_success(api.get_distribution_center(context["dc"]["id"], DCM))
        assert after["inbound_reserved_units"] == 9
        assert after["operations_posture"] == "RESTRICTED", (
            "9 is exactly ceil(10 * 0.90), the inclusive RESTRICTED threshold"
        )

    def test_freeing_the_order_returns_the_center_to_open(self, api):
        """PRD §3.8: "returning from `RESTRICTED` to `OPEN` happens automatically when the
        reserve falls back below it; neither requires a manager."
        PRD §3.3: "the center's `inbound_reserved_units` is reduced by the total released".

        Design: Corner/state_machines/dc_posture_lifecycle_is_automatic_on_the_stock_threshold
        """
        context = self._allocated(api)

        validate_success(api.cancel_order(context["order"]["id"], context["headers"]))

        after = validate_success(api.get_distribution_center(context["dc"]["id"], DCM))
        assert after["inbound_reserved_units"] == 0
        assert after["operations_posture"] == "OPEN"

        stock = validate_success(api.get_stock(context["stock_id"], DCM))
        assert stock["reserved_units"] == 0