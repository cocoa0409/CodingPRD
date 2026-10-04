"""Member lifecycle: suspension, revocation cascades, reinstatement,
terminal lockdowns, and death processing."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures
from test_helpers.fixtures import (
    BENEFITS,
    OFFICER_A,
    add_evidence,
    build_household,
    build_offering,
    open_entitlement,
)


class TestLossAndReinstate:
    def test_reinstate_from_active_rejected(self, api):
        """PRD §3.8: "Reinstatement from `SUSPENDED` back to `ACTIVE`
        requires restoration evidence..." — the transition is defined only
        from `SUSPENDED`, so calling it on an `ACTIVE` member fails the
        state-machine precondition of PRD §2.7 with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/reinstate_from_active_rejected
        """
        _, member_id = fixtures.approve_direct_member(api, name="Active Amy")
        before = validate_success(api.get_member(member_id, OFFICER_A))
        resp = api.reinstate_member(member_id, OFFICER_A)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_member(member_id, OFFICER_A))
        assert after["status"] == "ACTIVE"
        assert after["version"] == before["version"]

    def test_grandfathered_entitlement_survives_reinstate(self, api):
        """PRD §3.8: "Reinstatement recomputes the member's matrix and
        household aggregate; entitlements already `GRANDFATHERED` remain so
        — reinstatement restores status, not the original entitlement
        states."

        Design: Corner/cross_cutting_layers/grandfathered_entitlement_survives_reinstate
        """
        case, member_id = fixtures.approve_direct_member(api, name="Gf Gina")
        offering = build_offering(
            api, categories=["VETERAN_HONORABLE"], product_line="INSURANCE"
        )
        entitlement = open_entitlement(
            api, member_id, offering["id"], exposure_cents=100000
        )
        validate_success(api.record_eligibility_loss(
            member_id, {"loss_type": "DOCUMENTATION_REVOKED"}, OFFICER_A,
        ))
        # Restoration evidence uploaded after the loss event.
        add_evidence(api, case["id"], content_hash="restore-gf")
        reinstated = validate_success(api.reinstate_member(member_id, OFFICER_A))
        assert reinstated["status"] == "ACTIVE"
        ent = validate_success(api.get_entitlement(entitlement["id"], OFFICER_A))
        assert ent["status"] == "GRANDFATHERED"
        assert ent["grandfathered"] is True


class TestDeathProcessing:
    def test_deceased_from_suspended_rejected(self, api):
        """PRD §3.9: "Only an `ACTIVE` member can be processed as deceased;
        a `SUSPENDED` member must be reinstated before death processing, and
        attempting otherwise fails with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/deceased_from_suspended_rejected
        """
        _, member_id = fixtures.approve_direct_member(api, name="Susp Sam")
        validate_success(api.record_eligibility_loss(
            member_id, {"loss_type": "DOCUMENTATION_REVOKED"}, OFFICER_A,
        ))
        resp = api.mark_deceased(member_id, {}, BENEFITS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        member = validate_success(api.get_member(member_id, OFFICER_A))
        assert member["status"] == "SUSPENDED"
        cases = validate_success(
            api.list_member_survivor_cases(member_id, BENEFITS)
        )
        assert cases == []

    def test_deceased_member_rejects_eligibility_loss_and_has_no_case(self, api):
        """PRD §3.9: "The transition to `DECEASED` — a terminal state..." and
        "When no surviving family member exists, no case is created."
        Terminal-state writes fail the state-machine precondition of PRD §2.7
        with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/deceased_member_rejects_all_further_transitions
        """
        _, member_id = fixtures.approve_direct_member(api, name="Late Larry")
        validate_success(api.mark_deceased(member_id, {}, BENEFITS))
        resp = api.record_eligibility_loss(
            member_id, {"loss_type": "DOCUMENTATION_REVOKED"}, OFFICER_A,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        member = validate_success(api.get_member(member_id, OFFICER_A))
        assert member["status"] == "DECEASED"
        cases = validate_success(
            api.list_member_survivor_cases(member_id, BENEFITS)
        )
        assert cases == []


class TestRevocationCascade:
    def _suspended_sponsor_with_child(self, api):
        """Sponsor ACTIVE with one entitlement + household; child ACTIVE in
        the sponsor's household; sponsor suspended via DOCUMENTATION_REVOKED
        (entitlement grandfathered)."""
        fixtures.ensure_clock(api)
        case_s, sponsor_id = fixtures.approve_direct_member(
            api, name="Gus Ground", dob="1979-11-11",
            start="1998-01-01", end="2018-01-01",
        )
        offering = build_offering(
            api, categories=["VETERAN_HONORABLE"], product_line="INVESTMENT",
            product_code="INV_BROKER", product_name="Brokerage",
        )
        entitlement = open_entitlement(
            api, sponsor_id, offering["id"], exposure_cents=500000
        )
        household = build_household(api, sponsor_id,
                                    household_name="Ground Family")
        _, child_id = fixtures.approve_family_member(
            api, sponsor_id, "CHILD", name="Kid Ground", dob="2005-01-01",
            doc_type="BIRTH_CERTIFICATE",
        )
        validate_success(api.record_eligibility_loss(
            sponsor_id, {"loss_type": "DOCUMENTATION_REVOKED"}, OFFICER_A,
        ))
        return {
            "case": case_s, "sponsor_id": sponsor_id, "child_id": child_id,
            "offering": offering, "entitlement": entitlement,
            "household": household,
        }

    def test_fraud_revocation_closes_grandfathered_entitlement(self, api):
        """PRD §3.8: "The `FRAUD_CONFIRMED` loss type moves a `SUSPENDED`
        member to `REVOKED`, a terminal state: every `OPEN` and every
        `GRANDFATHERED` entitlement closes with `closure_reason`
        `MEMBER_LOSS`, ending grandfathering."

        Design: Difficulty/transitive_cascade/revocation_depth3_descendant_suspension_cascade
        """
        parts = self._suspended_sponsor_with_child(api)
        revoked = validate_success(api.record_eligibility_loss(
            parts["sponsor_id"],
            {"loss_type": "FRAUD_CONFIRMED",
             "loss_note": "forged DD-214 confirmed"},
            OFFICER_A,
        ))
        assert revoked["status"] == "REVOKED"
        ent = validate_success(
            api.get_entitlement(parts["entitlement"]["id"], OFFICER_A)
        )
        assert ent["status"] == "CLOSED"
        assert ent["closure_reason"] == "MEMBER_LOSS"

    def test_fraud_revocation_suspends_active_descendants(self, api):
        """PRD §3.8: "Revocation cascades one generation down the lineage:
        every member whose `sponsor_member_id` is the revoked member and
        whose status is `ACTIVE` moves to `SUSPENDED`, with their product
        matrices and their households' aggregates recomputed alongside the
        revoked member's own."

        Design: Difficulty/transitive_cascade/revocation_depth3_descendant_suspension_cascade
        """
        parts = self._suspended_sponsor_with_child(api)
        validate_success(api.record_eligibility_loss(
            parts["sponsor_id"], {"loss_type": "FRAUD_CONFIRMED"}, OFFICER_A,
        ))
        child = validate_success(api.get_member(parts["child_id"], OFFICER_A))
        assert child["status"] == "SUSPENDED"
        household = validate_success(
            api.get_household(parts["household"]["id"], OFFICER_A)
        )
        assert isinstance(household["aggregate_product_count"], int)


class TestParallelStatusAndPosture:
    def _deployed_member(self, api):
        return fixtures.setup_active_member_with_deployment(
            api, start_date="2026-08-15", end_date="2027-02-15",
            scra_eligible=False, name="Fay Fleet",
        )

    def test_suspension_preserves_deployed_posture(self, api):
        """PRD §3.5: "A member's `deployment_posture` is a second,
        independent state dimension alongside status, with values `NONE` and
        `DEPLOYED`."

        Design: Difficulty/non_linear_state_machine/member_parallel_status_and_posture_dimensions
        """
        member_id, order = self._deployed_member(api)
        before = validate_success(api.get_member(member_id, OFFICER_A))
        assert before["deployment_posture"] == "DEPLOYED"
        suspended = validate_success(api.record_eligibility_loss(
            member_id,
            {"loss_type": "DOCUMENTATION_REVOKED",
             "loss_note": "source record withdrawn"},
            OFFICER_A,
        ))
        assert suspended["status"] == "SUSPENDED"
        assert suspended["deployment_posture"] == "DEPLOYED"

    def test_completion_releases_posture_without_touching_status(self, api):
        """PRD §3.5: "Posture flips from `NONE` to `DEPLOYED` whenever an
        order activates — provided the member's status is `ACTIVE` — and
        flips back to `NONE` when the last `ACTIVE` order completes or is
        cancelled, leaving no remaining `ACTIVE` order for the member."

        Design: Difficulty/non_linear_state_machine/member_parallel_status_and_posture_dimensions
        """
        member_id, order = self._deployed_member(api)
        validate_success(api.record_eligibility_loss(
            member_id, {"loss_type": "DOCUMENTATION_REVOKED"}, OFFICER_A,
        ))
        fixtures.set_clock(api, "2027-02-15T00:00:00Z")
        completed = validate_success(
            api.complete_deployment_order(order["id"], OFFICER_A)
        )
        assert completed["status"] == "COMPLETED"
        member = validate_success(api.get_member(member_id, OFFICER_A))
        assert member["deployment_posture"] == "NONE"
        assert member["status"] == "SUSPENDED"
