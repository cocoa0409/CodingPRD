"""The three version-pinning tokens and the observable order of the validation gates."""
import pytest

from test_helpers import (
    ADMIN,
    CARE_ADVOCATE_FALLBACK,
    CLAIMS,
    NETWORK,
    PHARMACIST,
    REVIEWER_ID,
    REVIEWER_2_ID,
    api_client,
    approve_preauthorization,
    create_claim_payload,
    create_clinic,
    create_contract,
    create_cycle,
    create_member,
    create_plan,
    create_preauthorization,
    create_treatment_cycle_payload,
    drive_cycle_to_outcome_recorded,
    make_care_advocate_headers,
    make_clinical_reviewer_headers,
    make_clinic_coordinator_headers,
    select_clinic_for_plan,
    setup_adjudicated_claim,
    setup_approved_authorization,
    setup_clock,
    setup_cycle_under_authorization,
    setup_member_plan_clinic,
    setup_recorded_outcome_cycle,
    validate_success,
)


class TestDecisionStalePlanVersion:
    """Deciding an authorization pins the plan's version."""

    def test_stale_plan_version_on_decide_is_refused(self):
        """PRD §2.8: "A decision on a pre-authorization requires
        `expected_treatment_plan_version`, carrying the client's last observed `version`
        of the plan whose cycle the authorization covers. If the plan's `version` has
        advanced since that observation — because another writer selected a different
        clinic, abandoned the plan, or moved it into planning revision — the decision is
        refused with `ERR_PLAN_VERSION_STALE` and a 412 status, because the decision was
        computed against a plan shape that no longer holds."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_treatment_plan_version_on_decide_returns_plan_version_stale
        """
        scenario = setup_member_plan_clinic()
        plan = scenario["plan"]
        preauth = create_preauthorization(scenario["plan"], scenario["advocate"], 1)
        validate_success(api_client.begin_clinical_review(
            preauth["id"], make_clinical_reviewer_headers(REVIEWER_ID)), 200)
        plan_now = validate_success(api_client.get_treatment_plan(plan["id"], NETWORK), 200)

        stale = api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "APPROVE",
             "expected_treatment_plan_version": plan_now["version"] - 1},
            make_clinical_reviewer_headers(REVIEWER_ID))

        assert stale.status_code == 412
        assert stale.json()["data"]["error_id"] == "ERR_PLAN_VERSION_STALE"

        still_review = validate_success(
            api_client.get_preauthorization(preauth["id"], CLAIMS), 200)
        assert still_review["review_status"] == "CLINICAL_REVIEW"
        assert still_review["denial_reason_code"] is None, (
            "the stale rejection records no denial"
        )

    def test_current_plan_version_on_decide_is_admitted(self):
        """PRD §3.5: "Rendering the decision is a separate act: the reviewer supplies a
        `decision` of approve or deny, together with `expected_treatment_plan_version`
        carrying the plan's `version` as the reviewer last observed it"

        Design: Corner/cross_cutting_complexity_layers/occ_stale_treatment_plan_version_on_decide_returns_plan_version_stale
        """
        scenario = setup_member_plan_clinic()
        preauth = create_preauthorization(scenario["plan"], scenario["advocate"], 1)
        headers = make_clinical_reviewer_headers(REVIEWER_ID)
        validate_success(api_client.begin_clinical_review(preauth["id"], headers), 200)
        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)

        approved = validate_success(api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "APPROVE", "expected_treatment_plan_version": plan_now["version"]},
            headers), 200)

        assert approved["review_status"] == "APPROVED"
        assert approved["decision_actor"] == REVIEWER_ID
        plan_after = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        assert plan_after["plan_status"] == "IN_PROGRESS"


class TestPaymentStaleAuthorizationVersion:
    """Paying a claim pins the authorization's version."""

    def test_stale_authorization_version_on_pay_is_refused(self):
        """PRD §2.8: "Paying a claim requires `expected_preauthorization_version`,
        carrying the client's last observed `version` of the authorization the claim is
        drawn against. If the authorization's `version` has advanced since that
        observation — because it has been freshly consumed, released by a reversal, or
        otherwise touched — the payment is refused with `ERR_PREAUTH_VERSION_STALE` and
        a 412 status, because the adjudicated allowance no longer reflects the
        authorization the payment would settle."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_preauthorization_version_on_pay_returns_preauth_version_stale
        """
        scenario = setup_claim_for_payment()
        claim = scenario["claim"]
        assert claim["claim_status"] == "ADJUDICATED"
        preauth = validate_success(
            api_client.get_preauthorization(scenario["preauthorization"]["id"], CLAIMS), 200)

        stale = api_client.pay_claim(
            claim["id"], {"expected_preauthorization_version": preauth["version"] - 1}, CLAIMS)

        assert stale.status_code == 412
        assert stale.json()["data"]["error_id"] == "ERR_PREAUTH_VERSION_STALE"
        unchanged = validate_success(api_client.get_claim(claim["id"], CLAIMS), 200)
        assert unchanged["claim_status"] == "ADJUDICATED"

    def test_current_authorization_version_on_pay_is_admitted_and_advances_it(self):
        """PRD §3.9: "Paying an adjudicated claim is the point at which the
        authorization's version is pinned."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_preauthorization_version_on_pay_returns_preauth_version_stale
        """
        scenario = setup_claim_for_payment()
        claim = scenario["claim"]
        preauth_before = validate_success(
            api_client.get_preauthorization(scenario["preauthorization"]["id"], CLAIMS), 200)

        paid = validate_success(api_client.pay_claim(
            claim["id"],
            {"expected_preauthorization_version": preauth_before["version"]}, CLAIMS), 200)

        assert paid["claim_status"] == "PAID"
        preauth_after = validate_success(
            api_client.get_preauthorization(scenario["preauthorization"]["id"], CLAIMS), 200)
        assert preauth_after["version"] > preauth_before["version"], (
            "payment is one of the mutations that touches the authorization"
        )


def setup_claim_for_payment() -> dict:
    """An adjudicated CLINIC_BUNDLE claim drawn against an approved authorization."""
    from test_helpers import setup_adjudicated_claim, validate_success
    from test_helpers import NETWORK
    return setup_adjudicated_claim()


class TestOutcomeReportStaleCycleVersion:
    """Reporting an outcome pins the cycle's version."""

    def test_stale_cycle_version_on_report_is_refused(self):
        """PRD §2.8: "Reporting an outcome from the clinic side requires
        `expected_treatment_cycle_version`, carrying the client's last observed
        `version` of the cycle being reported. If the cycle's `version` has advanced
        since that observation — for example because the cycle has been cancelled — the
        report is refused with `ERR_CYCLE_VERSION_STALE` and a 412 status, because the
        reported outcome would no longer describe a live cycle."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_treatment_cycle_version_on_report_outcome_returns_cycle_version_stale
        """
        scenario = setup_recorded_outcome_cycle()
        clinic = scenario["clinic"]
        cycle = validate_success(
            api_client.get_treatment_cycle(scenario["cycle"]["id"], NETWORK), 200)

        stale = api_client.report_outcome(
            clinic["id"],
            {"treatment_cycle_id": cycle["id"], "live_birth": True, "births_count": 1,
             "multiple_birth": False, "gestational_weeks": 39,
             "expected_treatment_cycle_version": cycle["version"] - 1},
            make_clinic_coordinator_headers(clinic["id"]))

        assert stale.status_code == 412
        assert stale.json()["data"]["error_id"] == "ERR_CYCLE_VERSION_STALE"

        records = validate_success(
            api_client.list_outcome_records(NETWORK, {"clinic_id": clinic["id"]}), 200)
        assert records == [], "the refusal persists no outcome record"
        clinic_after = validate_success(
            api_client.get_clinic(clinic["id"], NETWORK), 200)
        assert clinic_after["cycles_reported"] == 0

    def test_current_cycle_version_on_report_is_admitted(self):
        """PRD §3.3: "The accepted report is created in `outcome_status` `RECORDED`, and
        it drives `cycles_reported` and the derived quality readings on the clinic."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_treatment_cycle_version_on_report_outcome_returns_cycle_version_stale
        """
        scenario = setup_recorded_outcome_cycle()
        cycle = validate_success(
            api_client.get_treatment_cycle(scenario["cycle"]["id"], NETWORK), 200)

        record = validate_success(api_client.report_outcome(
            scenario["clinic"]["id"],
            {"treatment_cycle_id": cycle["id"], "live_birth": True, "births_count": 1,
             "multiple_birth": False, "gestational_weeks": 39,
             "expected_treatment_cycle_version": cycle["version"]},
            make_clinic_coordinator_headers(scenario["clinic"]["id"])), 201)

        assert record["outcome_status"] == "RECORDED"
        clinic_after = validate_success(
            api_client.get_clinic(scenario["clinic"]["id"], NETWORK), 200)
        assert clinic_after["cycles_reported"] == 1
        assert clinic_after["live_birth_rate_bps"] == 10000


class TestValidationGateOrder:
    """The gates run in a declared order, and the first failure is the one reported."""

    def test_segregation_of_duties_fires_before_the_state_gate(self):
        """PRD §2.9: "The sequence is: header presence and role validity first; then
        authorization of the role for this operation; then resolution of every path
        identifier left to right, with the entity-specific not-found code for the failing
        segment; then the segregation-of-duties rule; then the declared-state rule for
        the requested transition"
        PRD §2.1: "A `ClinicalReviewer` may not begin clinical review of, or render a
        decision on, an authorization or pathway request whose recorded `decision_actor`
        already equals their own `X-User-ID`, and a `ClaimsReviewer` deciding an appeal
        must present an `X-User-ID` different from the `decision_actor` recorded on the
        claim's last adjudication; both violations are refused with `ERR_SOD_CONFLICT` and
        a 403 status."

        Design: Difficulty/priority_pair_validation_conflict/auth_versus_state_pair_on_dual_failure_decide
        """
        scenario = setup_approved_authorization()
        preauth = scenario["preauthorization"]
        assert preauth["review_status"] == "APPROVED"
        assert preauth["decision_actor"] == REVIEWER_ID
        plan_now = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        version_before = validate_success(
            api_client.get_preauthorization(preauth["id"], CLAIMS), 200)["version"]

        # The same reviewer, on an authorization that is no longer in CLINICAL_REVIEW.
        same_actor = api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "APPROVE", "expected_treatment_plan_version": plan_now["version"]},
            make_clinical_reviewer_headers(REVIEWER_ID))

        assert same_actor.status_code == 403
        assert same_actor.json()["data"]["error_id"] == "ERR_SOD_CONFLICT"

        # A conforming identity on the same row fails at the state gate instead.
        other_actor = api_client.decide_preauthorization(
            preauth["id"],
            {"decision": "APPROVE", "expected_treatment_plan_version": plan_now["version"]},
            make_clinical_reviewer_headers(REVIEWER_2_ID))

        assert other_actor.status_code == 409
        assert other_actor.json()["data"]["error_id"] == "ERR_INVALID_STATE"

        unchanged = validate_success(
            api_client.get_preauthorization(preauth["id"], CLAIMS), 200)
        assert unchanged["review_status"] == "APPROVED"
        assert unchanged["version"] == version_before, "both refusals advanced nothing"

    def test_body_foreign_key_gate_fires_before_the_service_window_gate(self):
        """PRD §2.9: "then body integrity — every foreign key in the body resolving, every
        required input present and inside its declared enumeration, and every
        pathway-specific reference present for its own enumeration member, reported as
        `ERR_SURROGACY_CARRIER_REQUIRED` for a surrogacy request without a carrier
        reference and `ERR_DONOR_AGENCY_REQUIRED` for a donor request without an agency
        reference; and only then the business rules"
        PRD §2.9: "A caller that supplies both a missing required field and a bad foreign
        key therefore sees the state error before the body error, and a caller that
        violates two business rules sees only the earlier one."

        Design: Difficulty/priority_pair_validation_conflict/existence_versus_temporal_pair_on_dual_failure_claim
        """
        scenario = setup_cycle_under_authorization()
        member = scenario["member"]
        preauth = scenario["preauthorization"]
        cycle = scenario["cycle"]

        # Close the authorization's validity window so the coverage rule would also fail.
        preauth_now = validate_success(
            api_client.get_preauthorization(preauth["id"], CLAIMS), 200)
        setup_clock(preauth_now["effective_to"])

        unresolved = api_client.create_claim(
            create_claim_payload(
                member["id"], preauth["id"], service_category="CLINIC_BUNDLE",
                billed_cents=900000,
                treatment_cycle_id="00000000-0000-4000-8000-000000000013",
                service_date_iso=preauth_now["effective_to"]),
            CLAIMS)
        assert unresolved.status_code == 404
        assert unresolved.json()["data"]["error_id"] == "ERR_NOT_FOUND"

        # Dropping only the unresolvable foreign key flips the answer to the coverage rule.
        windowed = api_client.create_claim(
            create_claim_payload(
                member["id"], preauth["id"], service_category="CLINIC_BUNDLE",
                billed_cents=900000, treatment_cycle_id=cycle["id"],
                service_date_iso=preauth_now["effective_to"]),
            CLAIMS)
        assert windowed.status_code == 422
        assert windowed.json()["data"]["error_id"] == "ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE"

        claims = validate_success(
            api_client.list_claims(NETWORK, {"member_id": member["id"]}), 200)
        assert claims == [], "neither rejected request persisted a claim"
        cycle_after = validate_success(
            api_client.get_treatment_cycle(cycle["id"], NETWORK), 200)
        assert cycle_after["cycle_status"] == "SCHEDULED"
        assert cycle_after["consumption_marker"] == "UNCONSUMED"

    def test_provider_and_clinic_gates_fire_before_the_allowance_gate(self):
        """PRD §2.10: "Ordered against one another, the coverage family precedes the
        allowance family, and within each family the rule stated earlier in the
        paragraphs above is evaluated earlier."

        Design: Difficulty/priority_pair_validation_conflict/existence_versus_temporal_pair_on_dual_failure_claim
        """
        scenario = setup_member_plan_clinic(select_clinic=False)
        plan = scenario["plan"]
        advocate = scenario["advocate"]
        uncontracted = create_clinic(min_live_birth_rate_bps=0)
        member_now = validate_success(api_client.get_member(plan["member_id"], NETWORK), 200)

        refused = api_client.select_plan_clinic(
            plan["id"],
            {"clinic_id": uncontracted["id"], "expected_member_version": member_now["version"]},
            make_care_advocate_headers(advocate["id"]))

        assert refused.status_code == 422
        assert refused.json()["data"]["error_id"] == "ERR_CLINIC_NOT_CONTRACTED"


class TestSequenceGuardOnFiling:
    """Authorizations accumulate in order and refuse a filing at the wrong position."""

    def test_filing_at_a_position_that_is_not_the_plans_next_is_refused(self):
        """PRD §3.5: "The first is sequencing: the new authorization's
        `cycle_sequence_index` must be strictly greater than the highest index already on
        the plan, so a plan's authorizations accumulate in order and a request filed at a
        position that is not the plan's next is refused with
        `ERR_SEQUENCE_OUT_OF_ORDER`."

        Design: Difficulty/priority_pair_validation_conflict/auth_versus_state_pair_on_dual_failure_decide
        """
        scenario = setup_approved_authorization(sequence_index=1)

        # A second authorization at the plan's next position, so the collection has a
        # row that the filtering probe can actually distinguish from the target.
        create_preauthorization(scenario["plan"], scenario["advocate"], cycle_sequence_index=2)

        refiled = api_client.create_preauthorization(
            scenario["plan"]["id"],
            {"cycle_sequence_index": 1,
             "criteria_inputs": {"age_years": 33, "amh_ng_ml": 2.0, "prior_cycles": 0,
                                 "prior_live_birth": False, "fsh_iu_l": 6},
             "member_cost_share_pct": 20},
            make_care_advocate_headers(scenario["advocate"]["id"]))

        assert refiled.status_code == 422
        assert refiled.json()["data"]["error_id"] == "ERR_SEQUENCE_OUT_OF_ORDER"