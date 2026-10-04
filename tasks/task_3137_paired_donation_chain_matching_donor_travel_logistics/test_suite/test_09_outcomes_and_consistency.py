"""Outcome attribution, center suspension consistency, and offer listing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_altruistic_donor,
    create_center,
    create_in_pool_pair,
    execute_chain_run,
    reset_clock,
    setup_attributed_failed_outcome,
    setup_locked_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["registry_admin_headers"]
OPERATOR = TEST_USERS["match_operator_headers"]


class TestReputation:
    def test_derived_field_reputation_recompute(self, api):
        """PRD §3.7: "A `RegistryAdmin` then attributes the outcome:
        `attributed_center_id` defaults to the recipient center of the offer,
        and if `outcome_kind` is `FAILED`, that center's `failed_outcome_count`
        increments by one and its `reputation_score_bps` is recomputed."
        PRD §3.7: "The score starts from `REPUTATION_BASE_BPS` of 10000,
        subtracts `REPUTATION_FAILURE_PENALTY_BPS` of 1500 per `FAILED` outcome
        attributed to the center up to a cumulative cap of
        `REPUTATION_FAILURE_CAP_BPS` of 4500, subtracts
        `REPUTATION_CIT_PENALTY_BPS` of 800 per probed cold-ischemia violation
        with no cap, adds `REPUTATION_SHIPMENT_BONUS_BPS` of 200 per
        successfully delivered shipment up to a cumulative cap of
        `REPUTATION_SHIPMENT_CAP_BPS` of 1000, and clamps the result to the
        closed range 0 to 10000."

        Design: Corner/cross_cutting_layers/derived_field_reputation_recompute
        """
        ctx, outcome = setup_attributed_failed_outcome()
        recipient_center_id = outcome["attributed_center_id"]
        center = validate_success(api.get_center(recipient_center_id, ADMIN))
        assert center["failed_outcome_count"] == 1
        # PRD §3.7: shipment bonus counts shipments whose origin_center_id is
        # the center. The position-1 offer's origin is the DONOR center
        # (center_a), not the recipient center (center_b). Center_b therefore
        # takes only the FAILED penalty: 10000 - 1500 = 8500.
        assert center["reputation_score_bps"] == 8500

    def test_reputation_failure_penalty_applied_per_failed_outcome(self, api):
        """PRD §3.7: "The score starts from `REPUTATION_BASE_BPS` of 10000,
        subtracts `REPUTATION_FAILURE_PENALTY_BPS` of 1500 per `FAILED` outcome
        attributed to the center up to a cumulative cap of
        `REPUTATION_FAILURE_CAP_BPS` of 4500".
        PRD §3.7: "if `outcome_kind` is `FAILED`, that center's
        `failed_outcome_count` increments by one and its
        `reputation_score_bps` is recomputed."

        Design: Corner/cross_cutting_layers/derived_field_reputation_recompute
        """
        ctx, outcome = setup_attributed_failed_outcome()
        recipient_center_id = outcome["attributed_center_id"]
        assert outcome["outcome_state"] == "ATTRIBUTED_TO_CENTER"
        center = validate_success(api.get_center(recipient_center_id, ADMIN))
        assert center["failed_outcome_count"] == 1
        assert center["reputation_score_bps"] < 10000


class TestCenterSuspensionConsistency:
    def test_immediate_consistency_after_center_suspend(self, api):
        """PRD §3.1: "A `RegistryAdmin` may suspend a center from either
        `ACTIVE` or `PROBATION`; any other starting state yields
        `ERR_CENTER_INVALID_STATE`. Because suspension cascades destructively,
        the call is OCC-guarded by `expected_center_version` (see §2.6). The
        suspension cascade does three things at once: every `RESERVED` surgery
        slot at the center moves to `RELEASED`; every offer at the center
        currently in `CENTER_ACCEPTED` rolls back to `CROSSMATCH_PASSED`,
        undoing the acceptance; and every offer at the center in
        `PENDING_CROSSMATCH` or `CROSSMATCH_PASSED` moves to `OFFER_FAILED`
        with `offer_failure_reason` equal to `CHAIN_BREAK_PROPAGATION`."

        Design: Corner/consistency_model/immediate_consistency_after_center_suspend
        """
        ctx = setup_locked_chain()
        center_b = ctx["center_b"]
        center_before = validate_success(api.get_center(center_b["id"], ADMIN))
        version_before = center_before["version"]
        resp = api.suspend_center(
            center_b["id"], {"expected_center_version": version_before}, ADMIN
        )
        suspended = validate_success(resp)
        assert suspended["participation_status"] == "SUSPENDED"
        # Immediate read-after-write shows SUSPENDED.
        reread = validate_success(api.get_center(center_b["id"], ADMIN))
        assert reread["participation_status"] == "SUSPENDED"
        # Cascaded offer state changes are immediately visible: the offer whose
        # recipient center is B was CENTER_ACCEPTED and must have rolled back.
        offer_at_b = None
        for offer in ctx["offers"]:
            if offer["recipient_center_id"] == center_b["id"]:
                offer_at_b = offer
        assert offer_at_b is not None
        refreshed = validate_success(api.get_match_offer(offer_at_b["id"], OPERATOR))
        assert refreshed["offer_state"] in ("CROSSMATCH_PASSED", "OFFER_FAILED")

    def test_suspend_center_requires_matching_occ_version(self, api):
        """PRD §2.6: "**Suspending a transplant center** requires
        `expected_center_version`, matched against the `TransplantCenter`'s
        current `version`."
        PRD §2.6: "A request that carries a stale value — one that does not
        equal the current `version` of the named parent entity — is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/consistency_model/immediate_consistency_after_center_suspend
        """
        reset_clock()
        center = create_center()
        resp = api.suspend_center(
            center["id"], {"expected_center_version": center["version"] + 5}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


class TestMatchOfferFiltering:
    def test_list_match_offers_filter_by_chain_id(self, api):
        """PRD §4: "GET | `/nkr/match-offers` | List match offers (filtered)".
        PRD §3.3: "Execution runs the chain-construction algorithm and mints
        `Chain` rows in `PROPOSED` state with embedded `MatchOffer` rows in
        `PENDING_CROSSMATCH`".

        Design: Corner/endpoints/list_match_offers_filter_by_chain_id
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        create_in_pool_pair(center_a, center_b, donor_abo="A", recipient_abo="B")
        create_in_pool_pair(center_b, center_a, donor_abo="B", recipient_abo="A")
        create_altruistic_donor(center_a, abo_type="O")
        run1 = execute_chain_run("filter-run")
        chains, _meta = validate_paginated(api.list_chains(OPERATOR))
        chain_id = chains[0]["id"]
        all_offers, _meta = validate_paginated(api.list_match_offers(OPERATOR))
        filtered, _meta = validate_paginated(
            api.list_match_offers(OPERATOR, params={"chain_id": chain_id})
        )
        assert len(filtered) == len(all_offers)
        for offer in filtered:
            assert offer["chain_id"] == chain_id

    def test_list_match_offers_filter_by_offer_state(self, api):
        """PRD §4: "GET | `/nkr/match-offers` | List match offers (filtered)".
        PRD §3.3: "Execution runs the chain-construction algorithm and mints
        `Chain` rows in `PROPOSED` state with embedded `MatchOffer` rows in
        `PENDING_CROSSMATCH`".

        Design: Corner/endpoints/list_match_offers_filter_by_chain_id
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        create_in_pool_pair(center_a, center_b, donor_abo="A", recipient_abo="B")
        create_in_pool_pair(center_b, center_a, donor_abo="B", recipient_abo="A")
        create_altruistic_donor(center_a, abo_type="O")
        execute_chain_run("filter-run-2")
        filtered, _meta = validate_paginated(
            api.list_match_offers(OPERATOR, params={"offer_state": "PENDING_CROSSMATCH"})
        )
        assert len(filtered) == 2
        for offer in filtered:
            assert offer["offer_state"] == "PENDING_CROSSMATCH"
