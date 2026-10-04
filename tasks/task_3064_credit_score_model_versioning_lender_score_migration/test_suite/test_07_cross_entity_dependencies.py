"""Transitions whose legality depends on the state of a different aggregate."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    COMPLIANCE, FAIR_LENDING, REASON_ADMIN,
    setup_probationary_and_retired_licences,
    setup_retirement_blocked_by_reference_set,
    setup_reference_set_dependency,
)


class TestLicenceActivationDependsOnModelState:

    def test_activating_a_licence_on_a_superseded_version_is_refused(self, api):
        """PRD §3.7: "Activation, and equally reactivation, is refused when the
        licensed variant's model version has reached `SUPERSEDED` — reported as
        `ERR_MODEL_SUPERSEDED` — or `RETIRED`, reported as `ERR_MODEL_RETIRED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_license_activation_depends_on_model_state
        """
        fixture = setup_probationary_and_retired_licences()
        pending = get_success_data(
            api_client.get_license(fixture["lic_w"]["id"], COMPLIANCE), 200)
        res = api_client.activate_license(pending["id"], pending["version"], COMPLIANCE)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_MODEL_SUPERSEDED"

    def test_both_pending_licences_stay_pending_after_the_refusal(self, api):
        """PRD §3.7: "Activation moves a pending licence to `ACTIVE` and recomputes
        `cumulative_score_count` and `cumulative_fee_cents` from the licence's fee
        ledger."

        A refused activation must leave both licences on the superseded version in
        PENDING.

        Design: Difficulty/cross_entity_state_dependency/cross_entity_license_activation_depends_on_model_state
        """
        fixture = setup_probationary_and_retired_licences()
        pending = get_success_data(
            api_client.get_license(fixture["lic_w"]["id"], COMPLIANCE), 200)
        api_client.activate_license(pending["id"], pending["version"], COMPLIANCE)
        west = get_success_data(api_client.get_license(fixture["lic_w"]["id"], COMPLIANCE), 200)
        east = get_success_data(api_client.get_license(fixture["lic_e"]["id"], COMPLIANCE), 200)
        assert west["status"] == "PENDING"
        assert east["status"] == "PENDING"

    def test_retirement_is_blocked_while_a_reference_set_sits_outside_reconciled(self, api):
        """PRD §3.2: "A `ComplianceOfficer` may retire a deprecated version only
        when no reference set on it sits outside `RECONCILED`; a live compiled or
        bound reference set blocks the move with `ERR_RETIREMENT_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_license_activation_depends_on_model_state
        """
        fixture = setup_retirement_blocked_by_reference_set()
        model = get_success_data(
            api_client.get_score_model(fixture[1]["id"], COMPLIANCE), 200)
        assert model["status"] == "DEPRECATED"
        res = api_client.retire_model(model["id"], model["version"], COMPLIANCE)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_RETIREMENT_BLOCKED"
        after = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
        assert after["status"] == "DEPRECATED"

    def test_the_version_stays_superseded_after_the_blocked_retirement(self, api):
        """PRD §3.2: "`RETIRED` is the only terminal state of the model lifecycle,
        and `retired_at` is stamped when it is reached."
        PRD §2.8: "the predecessor `ScoreModel` moves to `SUPERSEDED` with
        `retired_at` stamped from the logical clock"

        Design: Difficulty/cross_entity_state_dependency/cross_entity_license_activation_depends_on_model_state
        """
        fixture = setup_probationary_and_retired_licences()
        model = get_success_data(
            api_client.get_score_model(fixture["m1"]["id"], COMPLIANCE), 200)
        api_client.retire_model(model["id"], model["version"], COMPLIANCE)
        after = get_success_data(api_client.get_score_model(model["id"], COMPLIANCE), 200)
        assert after["status"] == "SUPERSEDED"


class TestReferenceSetBindingDependsOnCodeState:

    def test_a_code_from_another_model_is_refused_as_a_mismatch(self, api):
        """PRD §3.5: "An optional `parent_reason_code_id` places the entry inside
        the same variant's catalogue tree, and a parent from a different variant is
        refused with `ERR_REASON_CODE_VARIANT_MISMATCH`."
        PRD §3.6: "and the attached code's `score_variant_id` must belong to this
        set's model version, otherwise `ERR_REASON_CODE_VARIANT_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_reference_set_attach_depends_on_variant_and_code_state
        """
        fixture = setup_reference_set_dependency()
        rs = get_success_data(
            api_client.get_reference_set(fixture["rs1"]["id"], FAIR_LENDING), 200)
        res = api_client.attach_reason_code(rs["id"], fixture["rc_m9"]["id"],
                                            rs["version"], FAIR_LENDING)
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_REASON_CODE_VARIANT_MISMATCH"

    def test_a_code_from_the_sets_own_model_binds_the_set(self, api):
        """PRD §3.6: "The set moves to `BOUND`, the `reason_code_id` is recorded,
        and the code's `bind_count` increments."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_reference_set_attach_depends_on_variant_and_code_state
        """
        fixture = setup_reference_set_dependency()
        rs = get_success_data(
            api_client.get_reference_set(fixture["rs1"]["id"], FAIR_LENDING), 200)
        attached = validate_success(
            api_client.attach_reason_code(rs["id"], fixture["rc_m1"]["id"],
                                          rs["version"], FAIR_LENDING), 200)
        assert attached["status"] == "BOUND"
        assert attached["reason_code_id"] == fixture["rc_m1"]["id"]

    def test_archiving_the_bound_code_reconciles_that_set_alone(self, api):
        """PRD §3.6: "First, every reference set whose `reason_code_id` is that code
        and whose status is `BOUND` moves to `RECONCILED`."

        The other model's reference set was never bound to that code, so it stays
        untouched.

        Design: Difficulty/cross_entity_state_dependency/cross_entity_reference_set_attach_depends_on_variant_and_code_state
        """
        fixture = setup_reference_set_dependency()
        rs = get_success_data(
            api_client.get_reference_set(fixture["rs1"]["id"], FAIR_LENDING), 200)
        api_client.attach_reason_code(rs["id"], fixture["rc_m1"]["id"],
                                      rs["version"], FAIR_LENDING)
        api_client.archive_reason_code(fixture["rc_m1"]["id"], REASON_ADMIN)
        rs1_after = get_success_data(
            api_client.get_reference_set(fixture["rs1"]["id"], FAIR_LENDING), 200)
        rs9_after = get_success_data(
            api_client.get_reference_set(fixture["rs9"]["id"], FAIR_LENDING), 200)
        assert rs1_after["status"] == "RECONCILED"
        assert rs9_after["status"] == "COMPILED"

    def test_the_cleared_binding_drops_out_of_the_reason_code_filter(self, api):
        """PRD §3.6: "Whichever route is taken, the `reason_code_id` is cleared to
        null and every posting on the set has its `decision` reset to `UNDECIDED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_reference_set_attach_depends_on_variant_and_code_state
        """
        fixture = setup_reference_set_dependency()
        rs = get_success_data(
            api_client.get_reference_set(fixture["rs1"]["id"], FAIR_LENDING), 200)
        api_client.attach_reason_code(rs["id"], fixture["rc_m1"]["id"],
                                      rs["version"], FAIR_LENDING)
        api_client.archive_reason_code(fixture["rc_m1"]["id"], REASON_ADMIN)
        res = api_client.list_reference_sets(
            FAIR_LENDING, params={"reason_code_id": fixture["rc_m1"]["id"]})
        data, meta = validate_success(res, 200), res.json()["meta"]
        assert data == []
        assert meta["total_count"] == 0