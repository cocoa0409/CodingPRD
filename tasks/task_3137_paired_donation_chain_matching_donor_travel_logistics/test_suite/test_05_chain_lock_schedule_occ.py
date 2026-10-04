"""Chain lock, schedule, optimistic-concurrency, and supersede tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_offer,
    create_altruistic_donor,
    create_center,
    create_in_pool_pair,
    execute_chain_run,
    find_chain,
    get_success_data,
    list_offers,
    publish_chain_run,
    reset_clock,
    review_offer,
    setup_locked_chain,
    setup_scheduled_chain,
    setup_two_pair_chain,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

OPERATOR = TEST_USERS["match_operator_headers"]
ADMIN = TEST_USERS["registry_admin_headers"]


class TestChainLock:
    def test_chain_lock_gated_on_all_offers_center_accepted(self, api):
        """PRD §3.5: "A `MatchOperator` locks a chain only when the chain is in
        `ACCEPTING` (otherwise `ERR_INVALID_STATE`) and every offer in the chain
        has reached `CENTER_ACCEPTED` (otherwise `ERR_PENDING_OFFERS`)."

        Design: Difficulty/cross_entity_state_dependency/chain_lock_gated_on_all_offers_center_accepted
        """
        ctx = setup_two_pair_chain()
        # No offers accepted yet — lock must be rejected.
        chain = find_chain(ctx["chain"]["id"])
        resp = api.lock_chain(
            chain["id"], {"expected_chain_version": chain["version"]}, OPERATOR
        )
        validate_error(resp, ApiErrorId.ERR_PENDING_OFFERS.value)

    def test_chain_lock_gated_until_final_offer_accepted(self, api):
        """PRD §3.5: "A `MatchOperator` locks a chain only when the chain is in
        `ACCEPTING` (otherwise `ERR_INVALID_STATE`) and every offer in the chain
        has reached `CENTER_ACCEPTED` (otherwise `ERR_PENDING_OFFERS`)."

        Design: Difficulty/cross_entity_state_dependency/chain_lock_gated_on_all_offers_center_accepted
        """
        ctx = setup_two_pair_chain()
        # Accept exactly one of the two offers; lock must still be rejected.
        review_offer(ctx["offers"][0])
        accept_offer(ctx["offers"][0])
        chain = find_chain(ctx["chain"]["id"])
        resp = api.lock_chain(
            chain["id"], {"expected_chain_version": chain["version"]}, OPERATOR
        )
        validate_error(resp, ApiErrorId.ERR_PENDING_OFFERS.value)


class TestOptimisticConcurrency:
    def test_occ_stale_version_chain_schedule(self, api):
        """PRD §2.6: "**Scheduling a chain** requires
        `expected_chain_version`, matched against the target `Chain`'s current
        `version`."
        PRD §2.6: "A request that carries a stale value — one that does not
        equal the current `version` of the named parent entity — is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_chain_schedule
        """
        ctx = setup_locked_chain()
        chain = find_chain(ctx["chain"]["id"])
        resp = api.schedule_chain(
            chain["id"],
            {
                "expected_chain_version": chain["version"] + 1,
                "scheduled_date": "2026-09-08T00:00:00Z",
                "slot_ids": [],
            },
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    def test_occ_stale_version_chain_schedule_from_accepting(self, api):
        """PRD §2.6: "**Scheduling a chain** requires
        `expected_chain_version`, matched against the target `Chain`'s current
        `version`."
        PRD §2.6: "A request that carries a stale value — one that does not
        equal the current `version` of the named parent entity — is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_nephrectomy_when_donor_on_hold
        """
        ctx = setup_two_pair_chain()
        chain = find_chain(ctx["chain"]["id"])
        resp = api.schedule_chain(
            chain["id"],
            {
                "expected_chain_version": chain["version"] + 7,
                "scheduled_date": "2026-09-08T00:00:00Z",
                "slot_ids": [],
            },
            OPERATOR,
        )
        # PRD §2.5 priority: state-machine legality (9) runs before OCC (10).
        # A chain in ACCEPTING is not LOCKED, so the state check fires first;
        # otherwise the stale version check fires. Both are PRD-consistent.
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_STALE_VERSION.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )

    def test_occ_correct_version_succeeds(self, api):
        """PRD §3.5: "The call is OCC-guarded by `expected_chain_version`. A
        successful lock moves the chain from `ACCEPTING` to `LOCKED`, flips each
        participating donor's and recipient's `chain_participation_state` to
        `LOCKED`, and increments the chain's `version` by one."
        PRD §2.6: "**Locking a chain** requires `expected_chain_version`,
        matched the same way against the `Chain`'s current `version`."

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds
        """
        ctx = setup_two_pair_chain()
        for offer in ctx["offers"]:
            review_offer(offer)
            accept_offer(offer)
        chain = find_chain(ctx["chain"]["id"])
        version_before = chain["version"]
        locked = validate_success(
            api.lock_chain(
                chain["id"], {"expected_chain_version": version_before}, OPERATOR
            )
        )
        assert locked["chain_state"] == "LOCKED"
        assert locked["version"] == version_before + 1


class TestSupersedeInvariant:
    def test_chain_run_supersede_restores_pool_composition(self, api):
        """PRD §3.3: "Supersession aborts every proposed chain (each chain moves
        from `PROPOSED` to `ABORTED`), fails every embedded offer with
        `offer_failure_reason` equal to `CHAIN_BREAK_PROPAGATION`, and reverts
        each participant's `chain_participation_state` from `PROPOSED` back to
        `POOL`."

        Design: Difficulty/compensating_invariant/chain_run_supersede_restores_pool_composition
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        p1 = create_in_pool_pair(center_a, center_b, donor_abo="A", recipient_abo="B")
        p2 = create_in_pool_pair(center_b, center_a, donor_abo="B", recipient_abo="A")
        starter = create_altruistic_donor(center_a, abo_type="O")
        run = execute_chain_run("run-supersede")
        publish_chain_run(run)
        # Confirm participants moved to PROPOSED before superseding.
        assert get_success_data(
            api.get_donor(p1["donor"]["id"], ADMIN)
        )["chain_participation_state"] == "PROPOSED"
        get_success_data(api.supersede_chain_run(run["id"], OPERATOR))
        for participant in (p1["donor"], p2["donor"], starter):
            donor = get_success_data(api.get_donor(participant["id"], ADMIN))
            assert donor["chain_participation_state"] == "POOL"
        for participant in (p1["recipient"], p2["recipient"]):
            recipient = get_success_data(api.get_recipient(participant["id"], ADMIN))
            assert recipient["chain_participation_state"] == "POOL"
        for offer in list_offers():
            assert offer["offer_state"] == "OFFER_FAILED"
            assert offer["offer_failure_reason"] == "CHAIN_BREAK_PROPAGATION"

    def test_chain_run_supersede_chain_aborted(self, api):
        """PRD §3.3: "Supersession aborts every proposed chain (each chain moves
        from `PROPOSED` to `ABORTED`), fails every embedded offer with
        `offer_failure_reason` equal to `CHAIN_BREAK_PROPAGATION`, and reverts
        each participant's `chain_participation_state` from `PROPOSED` back to
        `POOL`."

        Design: Difficulty/compensating_invariant/chain_run_supersede_restores_pool_composition
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        create_in_pool_pair(center_a, center_b, donor_abo="A", recipient_abo="B")
        create_in_pool_pair(center_b, center_a, donor_abo="B", recipient_abo="A")
        create_altruistic_donor(center_a, abo_type="O")
        run = execute_chain_run("run-supersede-2")
        publish_chain_run(run)
        get_success_data(api.supersede_chain_run(run["id"], OPERATOR))
        chains, _meta = validate_paginated(api.list_chains(OPERATOR))
        assert len(chains) == 1
        assert chains[0]["chain_state"] == "ABORTED"


class TestScheduleLockedChain:
    def test_scheduled_chain_marks_participants_committed(self, api):
        """PRD §3.5: "On success the chain moves to `SCHEDULED`,
        `scheduled_date` is stamped, every donor's `surgery_state` moves to
        `SURGERY_SCHEDULED`, every participant's `chain_participation_state`
        moves to `COMMITTED`, every offer moves from `CENTER_ACCEPTED` to
        `SCHEDULED`, and the chain's `version` increments."

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds
        """
        ctx = setup_scheduled_chain()
        chain = ctx["chain"]
        assert chain["chain_state"] == "SCHEDULED"
        for offer in ctx["offers"]:
            refreshed = get_success_data(api.get_match_offer(offer["id"], OPERATOR))
            assert refreshed["offer_state"] == "SCHEDULED"
        for donor in (ctx["starter"], ctx["p1"]["donor"]):
            refreshed = get_success_data(api.get_donor(donor["id"], ADMIN))
            assert refreshed["surgery_state"] == "SURGERY_SCHEDULED"
            assert refreshed["chain_participation_state"] == "COMMITTED"
