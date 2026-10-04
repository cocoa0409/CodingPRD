"""Price pinning, the claim appeal loop, and the reversal compensation."""
import pytest

from test_helpers import (
    CLAIMS,
    CLAIMS_REVIEW,
    NETWORK,
    PHARMACIST,
    REVIEWER_ID,
    api_client,
    approve_preauthorization,
    assert_claim,
    assert_pharmacy_pool_conserved,
    create_advocate,
    create_bundle,
    create_claim_payload,
    create_employer,
    create_member,
    create_medication_order_payload,
    create_plan,
    create_preauthorization,
    create_clinic,
    create_contract,
    make_care_advocate_headers,
    make_claims_reviewer_headers,
    make_clinical_reviewer_headers,
    select_clinic_for_plan,
    setup_adjudicated_claim,
    setup_approved_authorization,
    setup_clock,
    setup_dispensed_medication_order,
    setup_member_plan_clinic,
    validate_success,
)


class TestClaimAppealLoop:
    """A denied claim loops back through appeal into an adjudicated reading."""

    def test_appeal_carries_a_denied_claim_back_into_adjudication(self):
        """PRD §3.9: "A denied claim may be appealed by the member's `CareAdvocate` within
        the configured appeal window measured from the end of the authorization's
        validity, moving it to `APPEALED`, and the appeal is decided by a `ClaimsReviewer`
        under the segregation-of-duties rule"
        PRD §3.9: "A successful appeal re-adjudicates the claim, recomputing the allowance
        and the member share with the same rules and moving it back to `ADJUDICATED`."

        Design: Difficulty/non_linear_state_machine/claim_cyclic_deny_appeal_revise_dimension_independence
        """
        scenario = setup_denied_claim_for_appeal()
        claim = scenario["claim"]
        assert claim["claim_status"] == "DENIED"
        assert claim["plan_paid_cents"] == 0
        assert claim["member_cost_share_cents"] == 0

        appealed = validate_success(api_client.appeal_claim(
            claim["id"], make_care_advocate_headers(scenario["advocate"]["id"])), 200)
        assert appealed["claim_status"] == "APPEALED"

        decided = validate_success(api_client.decide_appeal(
            claim["id"], make_claims_reviewer_headers("rev-appeal-1")), 200)

        assert decided["claim_status"] == "ADJUDICATED"
        # The ceiling is the plan's own pinned price, which the PRD leaves the
        # implementation to derive; only the relation to it is assertable.
        ceiling = scenario["plan"]["selected_bundle_price_cents"]
        assert ceiling > 0, "the plan's price is pinned when the clinic is selected"
        assert decided["allowed_cents"] == ceiling, (
            "the pinned bundle ceiling, not the 2000000 billed charge"
        )
        assert decided["adjudication_basis"] == "BUNDLE_COMPONENT_RULE"
        # PRD 3.9: the final share starts at the authorization's 20 percent share of the
        # allowance, is capped by the 250000-cent out-of-pocket maximum (nothing has
        # accumulated yet), takes no specialty differential (the category is not
        # MEDICATION or DONOR_MATERIAL), and then nets out the 15000-cent
        # cost-difference cap, floored at zero.
        share = decided["member_cost_share_cents"]
        assert share == max(0, min(round(ceiling * 0.20), 250000) - 15000)
        assert decided["plan_paid_cents"] == ceiling - share
        assert_claim(decided)

    def test_appeal_decision_must_come_from_a_different_reviewer_than_the_adjudicator(self):
        """PRD §2.1: "a `ClaimsReviewer` deciding an appeal must present an `X-User-ID`
        different from the `decision_actor` recorded on the claim's last adjudication; both
        violations are refused with `ERR_SOD_CONFLICT` and a 403 status."

        Design: Difficulty/non_linear_state_machine/claim_cyclic_deny_appeal_revise_dimension_independence
        """
        scenario = setup_denied_claim_for_appeal()
        claim = scenario["claim"]
        validate_success(api_client.appeal_claim(
            claim["id"], make_care_advocate_headers(scenario["advocate"]["id"])), 200)

        # Re-present the identity that produced the claim's last adjudication record.
        # Every claim write in this fixture is made by the shared ClaimsProcessor
        # identity, so that is the actor the adjudication recorded.
        same_actor = "test-claims-processor-1"
        refused = api_client.decide_appeal(claim["id"], make_claims_reviewer_headers(same_actor))
        assert refused.status_code == 403
        assert refused.json()["data"]["error_id"] == "ERR_SOD_CONFLICT"

        still_appealed = validate_success(api_client.get_claim(claim["id"], CLAIMS), 200)
        assert still_appealed["claim_status"] == "APPEALED", "the refusal changed nothing"


def setup_denied_claim_for_appeal() -> dict:
    """A CLINIC_BUNDLE claim denied once its authorization's validity has closed.

    The denial gate opens at the authorization's own `effective_to`, and the appeal
    window is measured from that same instant, so the clock is parked exactly there.
    """
    from test_helpers import CLAIMS

    scenario = setup_approved_authorization()
    preauth = validate_success(
        api_client.get_preauthorization(scenario["preauthorization"]["id"], CLAIMS), 200)
    assert preauth["effective_to"] is not None, "approval publishes the validity window"

    claim = validate_success(api_client.create_claim(
        create_claim_payload(scenario["member"]["id"], preauth["id"],
                             service_category="CLINIC_BUNDLE", billed_cents=2000000,
                             service_date_iso="2026-09-01T00:00:00Z"),
        CLAIMS), 201)

    setup_clock(preauth["effective_to"])
    denied = validate_success(api_client.deny_claim(claim["id"], CLAIMS), 200)
    scenario["claim"] = denied
    return scenario


class TestClaimReversalCompensation:
    """Reversing a paid claim unwinds the pool draw and conserves the pool."""

    def test_reversal_restores_the_specialty_pool_and_zeros_the_claim(self):
        """PRD §3.9: "Reversal moves the claim to `REVERSED`, resets
        `member_accumulator_after_cents` back to `member_accumulator_before_cents`,
        returns the cycle the claim belonged to from the consumed reading to
        `UNCONSUMED` — the marker is not re-applied later unless a fresh clinic outcome
        report re-records the cycle — decrements the authorization's `consumed_cycles`
        and recomputes its consumption posture, recomputes the bundle's cycle counters
        and its pharmacy counters, and zeros both `plan_paid_cents` and
        `member_cost_share_cents` on the reversed claim itself."
        PRD §2.4: "These are ledgers in the strict sense — they are recomputed from the
        rows that reference the entitlement, never incremented blindly, so a reversal or a
        cancellation restores the allowance it consumed."

        Design: Difficulty/compensating_invariant/claim_reversal_restores_cycle_and_pharmacy_conserved_cent_sum
        """
        scenario = setup_paid_medication_claim()
        bundle = scenario["bundle"]
        claim = scenario["claim"]

        assert claim["claim_status"] == "PAID"
        assert bundle["pharmacy_consumed_cents"] == 420000
        assert bundle["pharmacy_remaining_cents"] == 80000
        assert bundle["pharmacy_consumed_cents"] + bundle["pharmacy_remaining_cents"] == 500000

        reversed_claim = validate_success(
            api_client.reverse_claim(claim["id"], CLAIMS), 200)

        assert reversed_claim["claim_status"] == "REVERSED"
        assert reversed_claim["plan_paid_cents"] == 0
        assert reversed_claim["member_cost_share_cents"] == 0
        assert reversed_claim["member_accumulator_after_cents"] == (
            reversed_claim["member_accumulator_before_cents"]
        ), "no out-of-pocket drift survives a reversal"

        after = validate_success(
            api_client.get_bundle_entitlement(bundle["id"], PHARMACIST), 200)
        assert after["pharmacy_consumed_cents"] == 0
        assert after["pharmacy_remaining_cents"] == 500000
        assert_pharmacy_pool_conserved(after)

    def test_reversal_leaves_the_cycle_side_of_the_bundle_untouched(self):
        """PRD §3.9: "returns the cycle the claim belonged to from the consumed reading to
        `UNCONSUMED`"
        PRD §2.4: "An account configured `allocation_method` `SEQUENTIAL_BUNDLE` nets
        only cycles that have already been recorded as consumed"

        Design: Difficulty/compensating_invariant/claim_reversal_restores_cycle_and_pharmacy_conserved_cent_sum
        """
        scenario = setup_paid_medication_claim()
        bundle_before = scenario["bundle"]
        assert bundle_before["cycles_consumed"] == 0
        assert bundle_before["cycles_remaining"] == 3

        validate_success(api_client.reverse_claim(scenario["claim"]["id"], CLAIMS), 200)

        after = validate_success(
            api_client.get_bundle_entitlement(bundle_before["id"], PHARMACIST), 200)
        assert after["cycles_consumed"] == 0, "no cycle was ever consumed by this claim"
        assert after["cycles_remaining"] == 3
        assert after["version"] > bundle_before["version"], (
            "the pool recompute advanced the entitlement beyond its paid reading"
        )


def setup_paid_medication_claim() -> dict:
    """A sequential account whose specialty pool has funded one 420000-cent fill, with a
    matching MEDICATION claim adjudicated and paid."""
    from test_helpers import (
        create_medication_order_payload, drive_cycle_to_outcome_recorded,
    )

    setup_clock()
    employer = create_employer(allocation_method="SEQUENTIAL_BUNDLE")
    bundle = create_bundle(employer["id"], lifetime_max_cycles=3, max_cycles_per_year=3,
                           pharmacy_pool_cents=500000)
    advocate = create_advocate()
    clinic = create_clinic()
    create_contract(clinic, bundle_rates={"IVF_RETRIEVAL_TRANSFER": 1450000})
    member = create_member(employer["id"], advocate=advocate,
                           member_overrides={"external_ref": "REVERSAL-1"})
    plan = select_clinic_for_plan(
        create_plan(member, bundle, advocate, planned_cycles=2), clinic, advocate)
    preauth = approve_preauthorization(
        create_preauthorization(plan, advocate, 1, member_cost_share_pct=10),
        plan, reviewer_id=REVIEWER_ID)

    order = validate_success(api_client.create_medication_order(
        create_medication_order_payload(member["id"], preauth["id"],
                                        acquisition_cost_cents=420000), PHARMACIST), 201)
    current = validate_success(api_client.get_bundle_entitlement(bundle["id"], PHARMACIST), 200)
    validate_success(api_client.dispense_medication_order(
        order["id"], {"expected_bundle_entitlement_version": current["version"]}, PHARMACIST), 200)

    claim = validate_success(api_client.create_claim(
        create_claim_payload(member["id"], preauth["id"], service_category="MEDICATION",
                             billed_cents=420000, service_date_iso="2026-09-01T00:00:00Z"),
        CLAIMS), 201)
    claim = validate_success(api_client.adjudicate_claim(claim["id"], CLAIMS), 200)
    preauth_now = validate_success(api_client.get_preauthorization(preauth["id"], CLAIMS), 200)
    claim = validate_success(api_client.pay_claim(
        claim["id"], {"expected_preauthorization_version": preauth_now["version"]}, CLAIMS), 200)

    return {
        "employer": employer,
        "bundle": validate_success(
            api_client.get_bundle_entitlement(bundle["id"], PHARMACIST), 200),
        "advocate": advocate,
        "member": member,
        "plan": plan,
        "preauthorization": preauth,
        "medication_order": order,
        "claim": claim,
    }