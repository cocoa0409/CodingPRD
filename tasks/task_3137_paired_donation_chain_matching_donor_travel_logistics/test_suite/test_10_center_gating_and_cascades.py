"""Center participation gating, suspension cascade, and decline/abort flows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_offer,
    create_altruistic_donor,
    create_center,
    create_in_pool_pair,
    execute_chain_run,
    find_chain,
    find_offer,
    get_success_data,
    list_offers,
    make_center_coordinator_headers,
    publish_chain_run,
    reset_clock,
    review_offer,
    setup_attributed_failed_outcome,
    setup_scheduled_chain,
    setup_two_pair_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["registry_admin_headers"]
OPERATOR = TEST_USERS["match_operator_headers"]


class TestCenterAcceptanceGating:
    def test_matchoffer_acceptance_gated_on_center_participation(self, api):
        """PRD §3.4: "With the offer in `CROSSMATCH_PASSED`, the recipient
        center's coordinator accepts it — moving the offer to `CENTER_ACCEPTED`
        and stamping `accepted_at_utc` — provided the recipient center's
        `participation_status` is `ACTIVE`, the donor center's
        `participation_status` is also `ACTIVE`, the logical clock has not
        reached `center_accept_deadline_utc`, and the acting coordinator's
        center matches `recipient_center_id`."
        PRD §3.4: "Both center-state failures surface as
        `ERR_CENTER_SUSPENDED`; a deadline failure surfaces as
        `ERR_REVIEW_DEADLINE_PASSED`; a center mismatch surfaces as
        `ERR_CENTER_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/matchoffer_acceptance_gated_on_center_participation
        """
        ctx = setup_two_pair_chain()
        # Position-1 offer: altruistic donor at center A -> p1 recipient at center B.
        # Suspend the recipient center B BEFORE crossmatch: at accept time, the
        # center-suspension guard fires (PRD §2.5 priority 5).
        offer1 = ctx["offers"][0]
        center_b = ctx["center_b"]
        center_now = validate_success(api.get_center(center_b["id"], ADMIN))
        get_success_data(
            api.suspend_center(
                center_b["id"],
                {"expected_center_version": center_now["version"]},
                ADMIN,
            )
        )
        resp = api.center_accept_offer(
            offer1["id"], make_center_coordinator_headers(center_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CENTER_SUSPENDED.value)

    def test_matchoffer_acceptance_gated_on_suspended_donor_center(self, api):
        """PRD §3.4: "With the offer in `CROSSMATCH_PASSED`, the recipient
        center's coordinator accepts it — moving the offer to `CENTER_ACCEPTED`
        and stamping `accepted_at_utc` — provided the recipient center's
        `participation_status` is `ACTIVE`, the donor center's
        `participation_status` is also `ACTIVE`, the logical clock has not
        reached `center_accept_deadline_utc`, and the acting coordinator's
        center matches `recipient_center_id`."
        PRD §3.4: "Both center-state failures surface as
        `ERR_CENTER_SUSPENDED`".

        Design: Difficulty/cross_entity_state_dependency/matchoffer_acceptance_gated_on_center_participation
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        # Build the canonical pool with the altruistic starter at center B so
        # position-1 offer has donor_center=B -> recipient_center=A.
        create_in_pool_pair(center_b, center_a, donor_abo="B", recipient_abo="A")
        create_in_pool_pair(center_a, center_b, donor_abo="A", recipient_abo="B")
        create_altruistic_donor(center_b, abo_type="O")
        run = execute_chain_run("gating-susp-donor-center")
        publish_chain_run(run)
        offers = sorted(list_offers(), key=lambda o: o["position_index"])
        # Position-1: starter@B -> p1.recipient@A. Position-2: p1.donor@A -> p2.recipient@B.
        target = offers[0]
        assert target["donor_center_id"] == center_b["id"]
        assert target["recipient_center_id"] == center_a["id"]
        review_offer(target)
        center_now = validate_success(api.get_center(center_b["id"], ADMIN))
        get_success_data(
            api.suspend_center(
                center_b["id"],
                {"expected_center_version": center_now["version"]},
                ADMIN,
            )
        )
        resp = api.center_accept_offer(
            target["id"], make_center_coordinator_headers(center_a["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CENTER_SUSPENDED.value)


class TestDonorHoldCascade:
    def test_donor_hold_fails_center_accepted_offer(self, api):
        """PRD §3.6: "A `CenterCoordinator` may place a cleared donor on hold
        (moving `medical_status` from `CLEARED` to `ON_HOLD`); doing so fails
        any offer in `PENDING_CROSSMATCH`, `CROSSMATCH_PASSED`, or
        `CENTER_ACCEPTED` that references the donor, with
        `offer_failure_reason` equal to `DONOR_UNAVAILABLE`."

        Design: Difficulty/transitive_cascade/donor_withdrawal_cascades_to_chain_break_and_orphan
        """
        ctx = setup_two_pair_chain()
        # Position-2 offer's donor is p1's paired donor (center_a).
        offer2 = ctx["offers"][1]
        review_offer(offer2)
        accept_offer(offer2)
        donor2 = ctx["p1"]["donor"]
        get_success_data(
            api.donor_medical_hold(
                donor2["id"], make_center_coordinator_headers(ctx["center_a"]["id"])
            )
        )
        refreshed = validate_success(api.get_match_offer(offer2["id"], OPERATOR))
        assert refreshed["offer_state"] == "OFFER_FAILED"
        assert refreshed["offer_failure_reason"] == "DONOR_UNAVAILABLE"

    def test_donor_hold_fails_pending_offer(self, api):
        """PRD §3.6: "A `CenterCoordinator` may place a cleared donor on hold
        (moving `medical_status` from `CLEARED` to `ON_HOLD`); doing so fails
        any offer in `PENDING_CROSSMATCH`, `CROSSMATCH_PASSED`, or
        `CENTER_ACCEPTED` that references the donor, with
        `offer_failure_reason` equal to `DONOR_UNAVAILABLE`."

        Design: Difficulty/transitive_cascade/donor_withdrawal_cascades_to_chain_break_and_orphan
        """
        ctx = setup_two_pair_chain()
        # Position-1 offer's donor is the altruistic starter (center_a).
        offer1 = ctx["offers"][0]
        donor1 = ctx["starter"]
        get_success_data(
            api.donor_medical_hold(
                donor1["id"], make_center_coordinator_headers(ctx["center_a"]["id"])
            )
        )
        refreshed = validate_success(api.get_match_offer(offer1["id"], OPERATOR))
        assert refreshed["offer_state"] == "OFFER_FAILED"
        assert refreshed["offer_failure_reason"] == "DONOR_UNAVAILABLE"


class TestCenterDecline:
    def test_center_decline_aborts_chain(self, api):
        """PRD §3.4: "Declining is the sibling action: a coordinator at the
        recipient center moves the offer to `CENTER_DECLINED`, which
        immediately finalizes the offer as `OFFER_FAILED` with
        `offer_failure_reason` equal to `CENTER_DECLINE`, and the chain may be
        reconstructed."

        Design: Difficulty/cross_entity_state_dependency/matchoffer_acceptance_gated_on_center_participation
        """
        ctx = setup_two_pair_chain()
        offer1 = ctx["offers"][0]
        review_offer(offer1)
        coord = make_center_coordinator_headers(offer1["recipient_center_id"])
        declined = validate_success(api.center_decline_offer(offer1["id"], coord))
        assert declined["offer_state"] == "OFFER_FAILED"
        assert declined["offer_failure_reason"] == "CENTER_DECLINE"

    def test_center_decline_offer_failure_reason(self, api):
        """PRD §3.4: "Declining is the sibling action: a coordinator at the
        recipient center moves the offer to `CENTER_DECLINED`, which
        immediately finalizes the offer as `OFFER_FAILED` with
        `offer_failure_reason` equal to `CENTER_DECLINE`, and the chain may be
        reconstructed."

        Design: Difficulty/cross_entity_state_dependency/matchoffer_acceptance_gated_on_center_participation
        """
        ctx = setup_two_pair_chain()
        offer2 = ctx["offers"][1]
        review_offer(offer2)
        coord = make_center_coordinator_headers(offer2["recipient_center_id"])
        declined = validate_success(api.center_decline_offer(offer2["id"], coord))
        assert declined["offer_state"] == "OFFER_FAILED"
        assert declined["offer_failure_reason"] == "CENTER_DECLINE"


class TestChainLockedSupersede:
    def test_chain_locked_error_on_supersede(self, api):
        """PRD §3.3: "Alternatively, an executed or published run may be
        superseded, which moves it to `SUPERSEDED` — but only while no child
        chain has reached `LOCKED` or any later state (otherwise
        `ERR_CHAIN_LOCKED`)."

        Design: Corner/errors/chain_locked_error_on_supersede
        """
        ctx = setup_scheduled_chain()
        resp = api.supersede_chain_run(ctx["run"]["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CHAIN_LOCKED.value)


class TestCenterSuspensionCascade:
    def test_center_suspend_cascades_slots_offers(self, api):
        """PRD §3.1: "The suspension cascade does three things at once: every
        `RESERVED` surgery slot at the center moves to `RELEASED`; every offer
        at the center currently in `CENTER_ACCEPTED` rolls back to
        `CROSSMATCH_PASSED`, undoing the acceptance; and every offer at the
        center in `PENDING_CROSSMATCH` or `CROSSMATCH_PASSED` moves to
        `OFFER_FAILED` with `offer_failure_reason` equal to
        `CHAIN_BREAK_PROPAGATION`."

        Design: Difficulty/transitive_cascade/center_suspend_cascades_slots_offers
        """
        ctx = setup_scheduled_chain()
        center_b = ctx["center_b"]
        # Center B has one RESERVED slot: the TRANSPLANT_OR for offer[0] (whose
        # recipient center is B).
        slots_at_b = [s for s in ctx["slots"] if s["center_id"] == center_b["id"]]
        assert len(slots_at_b) == 1
        center_now = validate_success(api.get_center(center_b["id"], ADMIN))
        suspended = validate_success(
            api.suspend_center(
                center_b["id"],
                {"expected_center_version": center_now["version"]},
                ADMIN,
            )
        )
        assert suspended["participation_status"] == "SUSPENDED"
        for slot in slots_at_b:
            refreshed = validate_success(api.get_slot(slot["id"], OPERATOR))
            assert refreshed["slot_state"] == "RELEASED"

    def test_center_suspend_releases_reserved_slots_and_rolls_back_acceptance(self, api):
        """PRD §3.1: "The suspension cascade does three things at once: every
        `RESERVED` surgery slot at the center moves to `RELEASED`; every offer
        at the center currently in `CENTER_ACCEPTED` rolls back to
        `CROSSMATCH_PASSED`, undoing the acceptance; and every offer at the
        center in `PENDING_CROSSMATCH` or `CROSSMATCH_PASSED` moves to
        `OFFER_FAILED` with `offer_failure_reason` equal to
        `CHAIN_BREAK_PROPAGATION`."

        Design: Difficulty/transitive_cascade/center_suspend_cascades_slots_offers
        """
        ctx = setup_two_pair_chain()
        center_b = ctx["center_b"]
        # Offer 1's recipient center is B: crossmatch-pass and accept it, then
        # suspend B. PRD §3.1's cascade: the CENTER_ACCEPTED -> CROSSMATCH_PASSED
        # rollback undoes the acceptance, then the crossmatch-passed-to-failed
        # branch fires, leaving the offer OFFER_FAILED with
        # offer_failure_reason = CHAIN_BREAK_PROPAGATION.
        offer1 = ctx["offers"][0]
        review_offer(offer1)
        accept_offer(offer1)
        center_now = validate_success(api.get_center(center_b["id"], ADMIN))
        get_success_data(
            api.suspend_center(
                center_b["id"],
                {"expected_center_version": center_now["version"]},
                ADMIN,
            )
        )
        refreshed = validate_success(api.get_match_offer(offer1["id"], OPERATOR))
        assert refreshed["offer_state"] == "OFFER_FAILED"
        assert refreshed["offer_failure_reason"] == "CHAIN_BREAK_PROPAGATION"


class TestCenterParticipationCycle:
    def test_transplant_center_participation_cyclic_active_probation(self, api):
        """PRD §3.1: "A center's `participation_status` moves among `ACTIVE`,
        `PROBATION`, and `SUSPENDED`."
        PRD §3.1: "Probation is a disciplinary step applied by a
        `RegistryAdmin`: it is permitted only from `ACTIVE`, and only when at
        least one of two triggers holds — the center's
        `probed_cold_ischemia_violations` has reached the probation threshold
        `PROBATION_CIT_VIOLATIONS`, or its `failed_outcome_count` has reached
        the probation threshold `PROBATION_FAILURES`. Otherwise the transition
        is rejected with `ERR_CENTER_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/transplant_center_participation_cyclic_active_probation
        """
        # With no violations and no failed outcomes, neither probation trigger
        # holds, so probating a fresh ACTIVE center is rejected.
        reset_clock()
        center = create_center()
        resp = api.probate_center(center["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CENTER_INVALID_STATE.value)
        after = validate_success(api.get_center(center["id"], ADMIN))
        assert after["participation_status"] == "ACTIVE"

    def test_transplant_center_probation_requires_threshold(self, api):
        """PRD §3.1: "Probation is a disciplinary step applied by a
        `RegistryAdmin`: it is permitted only from `ACTIVE`, and only when at
        least one of two triggers holds — the center's
        `probed_cold_ischemia_violations` has reached the probation threshold
        `PROBATION_CIT_VIOLATIONS`, or its `failed_outcome_count` has reached
        the probation threshold `PROBATION_FAILURES`. Otherwise the transition
        is rejected with `ERR_CENTER_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/transplant_center_participation_cyclic_active_probation
        """
        # A center with exactly one FAILED outcome is below the probation
        # threshold (reaching the threshold requires the full count), so
        # probation is still rejected and the center remains ACTIVE.
        ctx, outcome = setup_attributed_failed_outcome()
        recipient_center_id = outcome["attributed_center_id"]
        center = validate_success(api.get_center(recipient_center_id, ADMIN))
        assert center["failed_outcome_count"] == 1
        resp = api.probate_center(recipient_center_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CENTER_INVALID_STATE.value)
        after = validate_success(api.get_center(recipient_center_id, ADMIN))
        assert after["participation_status"] == "ACTIVE"
