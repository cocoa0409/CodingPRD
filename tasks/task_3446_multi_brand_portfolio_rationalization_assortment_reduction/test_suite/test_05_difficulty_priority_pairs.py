"""Difficulty queue: validation-priority pairs — when one request violates two
rules from different categories, the earlier-priority error must win.
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_brand,
    create_item,
    create_plant,
    create_negotiation_respond_payload,
    create_product_transfer_payload,
    make_retailer_buyer_headers,
    propose_case,
    respond_to_negotiation,
    set_clock,
    setup_negotiation_terms_proposed,
    validate_error,
    validate_ok,
    validate_paginated,
    ApiErrorId,
)

PM = TEST_USERS["portfolio_manager_headers"]
SCP = TEST_USERS["supply_chain_planner_headers"]


class TestTransferStateGuardBeatsCapacityFiscal:
    def _setup_cut_proposed_item(self, target_capacity):
        """Item LISTED (annual 40000 -> 10000 quarterly units) with an open
        SCORED case (item now CUT_PROPOSED); tiny or ample target plant."""
        brand = create_brand(core_flag=True, private_label_share_pct=40,
                             annual_net_revenue_cents=1000000000)
        source = create_plant(quarterly_capacity_units=1000000)
        target = create_plant(quarterly_capacity_units=target_capacity)
        item = create_item(brand["id"], source["id"], annual_units=40000,
                           unit_net_revenue_cents=2000, unit_cost_cents=1700,
                           units_on_hand=0)
        propose_case(item["id"])
        return item, source, target

    def test_state_guard_wins_when_capacity_also_violated(self):
        """PRD §2.8: "When several validation rules could reject the same
        request, the server evaluates them in a fixed global order, and the
        first failing check determines the error returned."
        PRD §2.8: "8. Transfer-creation state guards: the item must be `LISTED`
        (`ERR_ITEM_NOT_TRANSFERABLE`)" and "20. Transfer capacity gate on the
        target plant (`ERR_PLANT_OVER_CAPACITY`)."

        Design: Difficulty/priority_pair_validation_conflict/transfer_state_guard_beats_capacity_fiscal
        """
        item, source, target = self._setup_cut_proposed_item(target_capacity=1000)
        # Projected 10000 quarterly units against capacity 1000 is 1000% —
        # the fiscal gate (priority 20) would also fail, but the state guard
        # (priority 8) is evaluated first.
        resp = api_client.create_product_transfer(
            create_product_transfer_payload(item["id"], source["id"], target["id"]),
            SCP,
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_TRANSFERABLE)
        transfers, _ = validate_paginated(
            api_client.list_product_transfers(SCP, params={"item_id": item["id"]})
        )
        assert transfers == [], "No transfer may be persisted on a rejected create"

    def test_state_guard_wins_with_ample_target_capacity(self):
        """PRD §3.4: "The item must be `LISTED` — an item in any other status
        is rejected with `ERR_ITEM_NOT_TRANSFERABLE` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/transfer_state_guard_beats_capacity_fiscal
        """
        item, source, target = self._setup_cut_proposed_item(target_capacity=1000000)
        resp = api_client.create_product_transfer(
            create_product_transfer_payload(item["id"], source["id"], target["id"]),
            SCP,
        )
        # Isolated violation: only the item-state guard can fire here.
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_TRANSFERABLE)


class TestRespondStateGuardBeatsTtlTemporal:
    def test_respond_rejected_negotiation_after_expiry_keeps_rejected(self):
        """PRD §2.8: "When several validation rules could reject the same
        request, the server evaluates them in a fixed global order, and the
        first failing check determines the error returned."
        PRD §2.8: "7. Generic single-entity and cross-entity state guards
        (`ERR_INVALID_STATE`)" and "18. Negotiation response time-to-live
        (`ERR_NEGOTIATION_EXPIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/respond_state_guard_beats_ttl_temporal
        """
        retailer, _, negotiation = setup_negotiation_terms_proposed()
        respond_to_negotiation(negotiation, "REJECT")
        set_clock("2026-10-02T00:00:00Z")  # past expires_at (created 2026-09-01 + 30d)
        resp = api_client.respond_to_negotiation(
            negotiation["id"],
            create_negotiation_respond_payload("ACCEPT"),
            make_retailer_buyer_headers(retailer["id"]),
        )
        # The negotiation is terminal AND past TTL; the state guard (priority
        # 7) is evaluated before the TTL rule (priority 18).
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_ok(api_client.get_combined_negotiation(negotiation["id"], PM))
        assert after["negotiation_status"] == "REJECTED", (
            "The EXPIRED auto-transition must not fire on a terminal negotiation"
        )

    def test_respond_accepted_negotiation_after_expiry_keeps_accepted(self):
        """PRD §3.6: "Responding while the negotiation is `TERMS_PROPOSED` and
        the logical clock is at or before `expires_at` moves it to `ACCEPTED`
        or `REJECTED` accordingly and increments its `version`."
        PRD §2.8: "7. Generic single-entity and cross-entity state guards
        (`ERR_INVALID_STATE`)" evaluated before "18. Negotiation response
        time-to-live (`ERR_NEGOTIATION_EXPIRED`)".

        Design: Difficulty/priority_pair_validation_conflict/respond_state_guard_beats_ttl_temporal
        """
        retailer, _, negotiation = setup_negotiation_terms_proposed()
        respond_to_negotiation(negotiation, "ACCEPT")
        set_clock("2026-10-02T00:00:00Z")
        resp = api_client.respond_to_negotiation(
            negotiation["id"],
            create_negotiation_respond_payload("REJECT"),
            make_retailer_buyer_headers(retailer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_ok(api_client.get_combined_negotiation(negotiation["id"], PM))
        assert after["negotiation_status"] == "ACCEPTED"
