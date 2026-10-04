"""Dual-variant and boundary arithmetic: member share, pharmacy pool, cycle netting."""
import pytest

from test_helpers import (
    CLAIMS,
    NETWORK,
    PHARMACIST,
    TEST_DEFAULTS,
    api_client,
    assert_accumulator_advanced,
    assert_claim,
    assert_pharmacy_pool_conserved,
    create_claim_payload,
    create_preauthorization,
    setup_approved_authorizations,
    setup_bundle_pool_remainder,
    setup_dispensed_medication_order,
    setup_employer_bundle,
    setup_member_plan_clinic,
    validate_success,
)


class TestMemberCostShareVariants:
    """The member share has a provisional reading and a final reading."""

    def test_medication_claim_final_share_nets_the_cost_difference_cap(self):
        """PRD §3.9: "On the **final** reading — the one taken at adjudication and at
        appeal decision — the cost-difference cap of 15000 cents is netted out of the
        share, floored at zero, which means a member share smaller than the cap
        collapses to zero and one larger than the cap is reduced by exactly 15000 cents."
        PRD §3.9: "a 20000-cent allowed medication claim at a 20 percent share reads 4480
        cents provisionally and 0 cents finally, a spread wider than the cap itself."

        Design: Difficulty/dual_variant_calc/member_cost_share_provisional_vs_final_cents_delta
        """
        scenario = setup_dispensed_medication_order(
            acquisition_cost_cents=20000,
            preauth_overrides={"member_cost_share_pct": 20})
        claim = validate_success(api_client.create_claim(
            create_claim_payload(
                scenario["member"]["id"], scenario["preauthorization"]["id"],
                service_category="MEDICATION", billed_cents=20000,
                service_date_iso="2026-09-01T00:00:00Z"),
            CLAIMS), 201)
        assert claim["member_cost_share_cents"] == 4480, (
            "the provisional reading keeps the specialty differential inside the share"
        )

        adjudicated = validate_success(api_client.adjudicate_claim(claim["id"], CLAIMS), 200)

        assert adjudicated["member_cost_share_cents"] == 0
        assert adjudicated["allowed_cents"] == 20000
        assert adjudicated["plan_paid_cents"] == 20000
        assert adjudicated["claim_status"] == "ADJUDICATED"
        assert adjudicated["adjudication_basis"] == "BUNDLE_COMPONENT_RULE"
        assert adjudicated["member_accumulator_before_cents"] == 0
        assert adjudicated["member_accumulator_after_cents"] == 0
        assert_claim(adjudicated)
        assert_claim_invariants_after_adjudication(adjudicated)

    def test_medication_claim_provisional_share_reported_before_adjudication(self):
        """PRD §3.9: "On the **provisional** reading — the one exposed when a claim is
        first created, before adjudication — the share is returned exactly as computed,
        with the specialty differential still inside it and no cap applied."
        PRD §3.9: "for a `MEDICATION` or `DONOR_MATERIAL` claim only, a specialty
        differential of 12 percent is added on top of that capped figure, rounded
        half-up; for every other service category the differential is zero."

        Design: Difficulty/dual_variant_calc/member_cost_share_provisional_vs_final_cents_delta
        """
        scenario = setup_dispensed_medication_order(
            acquisition_cost_cents=20000,
            preauth_overrides={"member_cost_share_pct": 20})
        claim = validate_success(api_client.create_claim(
            create_claim_payload(
                scenario["member"]["id"], scenario["preauthorization"]["id"],
                service_category="MEDICATION", billed_cents=20000,
                service_date_iso="2026-09-01T00:00:00Z"),
            CLAIMS), 201)

        # 20 percent of 20000 is 4000; the 12 percent differential on 4000 is 480.
        assert claim["member_cost_share_cents"] == 4480
        assert claim["claim_status"] == "RECEIVED"
        assert claim["allowed_cents"] == 0
        assert claim["adjudication_basis"] is None
        assert claim["member_accumulator_before_cents"] == 0
        assert claim["member_accumulator_after_cents"] == claim["member_accumulator_before_cents"]
        assert_claim(claim)


def assert_claim_invariants_after_adjudication(claim: dict):
    """Helper kept local: the adjudicated claim's two sides must reconstruct the allowance."""
    assert claim["member_cost_share_cents"] + claim["plan_paid_cents"] == claim["allowed_cents"]


class TestPharmacyPoolWaterfall:
    """The specialty pharmacy pool settles a fill exactly, with no cent left adrift."""

    def test_dispense_allocates_the_pool_remainder_exactly(self):
        """PRD §3.7: "The first splits the amount the pool will bear between the drug
        and the service of dispensing it: the ingredient portion is 82 percent of the
        claimable amount rounded half-up to whole cents, and the dispensing fee is
        whatever remains, so the two always sum back to the claimable amount exactly
        and no cent is ever lost to drift."

        Design: Difficulty/combinatorial_formula/pharmacy_pool_waterfall_remainder_absorption_mode_b
        """
        scenario = setup_bundle_pool_remainder(
            remaining_cents=500000, acquisition_cost_cents=420000, pool_cents=500000)
        order = scenario["boundary_order"]
        current = validate_success(
            api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST), 200)

        dispensed = validate_success(api_client.dispense_medication_order(
            order["id"], {"expected_bundle_entitlement_version": current["version"]}, PHARMACIST), 200)

        assert dispensed["plan_paid_cents"] == 420000
        assert dispensed["member_cost_cents"] == 0
        assert dispensed["pharmacy_status"] == "DISPENSING"

        # ingredient = 82 percent of 420000 = 344400; the fee bucket absorbs 75600.
        ingredient = round(420000 * 82 / 100)
        dispensing_fee = 420000 - ingredient
        assert ingredient == 344400
        assert dispensing_fee == 75600
        assert ingredient + dispensing_fee == dispensed["plan_paid_cents"], (
            "the two buckets must sum back to the claimable amount with no drift"
        )

        bundle = validate_success(
            api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST), 200)
        assert bundle["pharmacy_consumed_cents"] == 420000
        assert bundle["pharmacy_remaining_cents"] == 80000
        assert_pharmacy_pool_conserved(bundle)

    def test_pool_covers_fill_fully_leaves_nothing_to_the_member(self):
        """PRD §3.7: "A pool that covers the fill entirely therefore leaves the member with
        nothing to pay, while a fill that outruns the pool leaves the pool at exactly
        zero and passes the excess to the member; a subsequent fill against that pool
        then reports nothing paid by the plan and the whole acquisition cost on the
        member."
        PRD §3.7: "The order's `plan_paid_cents` is set to that claimable amount, its
        `member_cost_cents` to whatever part of the acquisition cost the pool did not
        cover, and the entitlement's `pharmacy_consumed_cents` is increased by the
        claimable amount with `pharmacy_remaining_cents` recomputed as the pool less
        consumption, floored at zero."

        Design: Difficulty/combinatorial_formula/pharmacy_pool_waterfall_remainder_absorption_mode_b
        """
        scenario = setup_bundle_pool_remainder(
            remaining_cents=500000, acquisition_cost_cents=420000, pool_cents=500000)
        order = scenario["boundary_order"]
        current = validate_success(
            api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST), 200)

        dispensed = validate_success(api_client.dispense_medication_order(
            order["id"], {"expected_bundle_entitlement_version": current["version"]}, PHARMACIST), 200)

        assert dispensed["plan_paid_cents"] == dispensed["acquisition_cost_cents"]
        assert dispensed["member_cost_cents"] == 0
        bundle = validate_success(
            api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST), 200)
        assert bundle["pharmacy_remaining_cents"] == 500000 - 420000
        assert bundle["pharmacy_consumed_cents"] == 420000


class TestPharmacyPoolBoundary:
    """A pool of exactly zero is a genuine stop; a pool of one cent is not."""

    def test_dispense_against_exactly_zero_pool_is_refused(self):
        """PRD §3.7: "A pool that has reached exactly zero admits nothing and the
        dispensing is refused with `ERR_PHARMACY_POOL_EXHAUSTED`; a stopping condition
        that is genuinely a stop, where a pool holding a single cent still admits the
        next fill."

        Design: Difficulty/boundary_precision_check/pharmacy_pool_remainder_exactly_one_cent
        """
        scenario = setup_bundle_pool_remainder(
            remaining_cents=0, acquisition_cost_cents=300000, pool_cents=500000)
        bundle = scenario["bundle"]
        assert bundle["pharmacy_consumed_cents"] == 500000
        assert bundle["pharmacy_remaining_cents"] == 0

        order = scenario["boundary_order"]
        response = api_client.dispense_medication_order(
            order["id"], {"expected_bundle_entitlement_version": bundle["version"]}, PHARMACIST)

        assert response.status_code == 422
        assert response.json()["data"]["error_id"] == "ERR_PHARMACY_POOL_EXHAUSTED"

        refused = validate_success(api_client.get_medication_order(order["id"], PHARMACIST), 200)
        assert refused["pharmacy_status"] == "PRESCRIBED"
        assert refused["plan_paid_cents"] == 0
        after = validate_success(
            api_client.get_bundle_entitlement(bundle["id"], PHARMACIST), 200)
        assert after["pharmacy_remaining_cents"] == 0

    def test_dispense_against_a_one_cent_pool_is_admitted(self):
        """PRD §3.7: "a stopping condition that is genuinely a stop, where a pool
        holding a single cent still admits the next fill."
        PRD §3.7: "The claimable amount is the order's `acquisition_cost_cents` when the
        pool can cover it in full and the pool's remaining balance otherwise — never
        more than the pool holds, so a shortfall lands on the member rather than driving
        the pool negative."

        Design: Difficulty/boundary_precision_check/pharmacy_pool_remainder_exactly_one_cent
        """
        scenario = setup_bundle_pool_remainder(
            remaining_cents=1, acquisition_cost_cents=300000, pool_cents=500000)
        bundle = scenario["bundle"]
        assert bundle["pharmacy_remaining_cents"] == 1

        order = scenario["boundary_order"]
        dispensed = validate_success(api_client.dispense_medication_order(
            order["id"], {"expected_bundle_entitlement_version": bundle["version"]}, PHARMACIST), 200)

        assert dispensed["pharmacy_status"] == "DISPENSING"
        assert dispensed["plan_paid_cents"] == 1, "the pool bears its single cent, never more"
        assert dispensed["member_cost_cents"] == dispensed["acquisition_cost_cents"] - 1

        after = validate_success(api_client.get_bundle_entitlement(bundle["id"], PHARMACIST), 200)
        assert after["pharmacy_remaining_cents"] == 0
        assert after["pharmacy_consumed_cents"] == 500000
        assert_pharmacy_pool_conserved(after)


class TestCycleAllowanceNetting:
    """The two allocation methods net different inclusion sets."""

    def test_concurrent_netting_counts_approved_but_unconsumed_cycles(self):
        """PRD §2.4: "An account configured `CONCURRENT_BUNDLE` nets every committed
        cycle — consumed cycles, approved-but-unperformed cycles, and authorizations
        still awaiting a clinical decision — so the same rows yield a strictly smaller
        `cycles_remaining`."

        Design: Corner/calculations/bundle_cycle_allowance_sequential_versus_concurrent_variant_divergence
        """
        scenario = setup_approved_authorizations(
            count=2, allocation_method="CONCURRENT_BUNDLE",
            bundle_overrides={"lifetime_max_cycles": 3, "max_cycles_per_year": 3})
        plan = validate_success(
            api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK), 200)
        assert plan["plan_status"] == "IN_PROGRESS", "the approved authorizations admit the plan"

        bundle = validate_success(
            api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST), 200)

        assert bundle["cycles_consumed"] == 0
        assert bundle["cycles_committed"] == 2
        assert bundle["cycles_remaining"] == 1
        assert bundle["bundle_status"] == "ACTIVE"

    def test_sequential_netting_leaves_approved_cycles_untouched(self):
        """PRD §2.4: "An account configured `allocation_method` `SEQUENTIAL_BUNDLE` nets
        only cycles that have already been recorded as consumed, so authorizations that
        have been approved but not yet performed leave `cycles_remaining` untouched."

        Design: Corner/calculations/bundle_cycle_allowance_sequential_versus_concurrent_variant_divergence
        """
        scenario = setup_approved_authorizations(
            count=2, allocation_method="SEQUENTIAL_BUNDLE",
            bundle_overrides={"lifetime_max_cycles": 3, "max_cycles_per_year": 3})

        bundle = validate_success(
            api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST), 200)

        assert bundle["cycles_consumed"] == 0
        assert bundle["cycles_remaining"] == 3, (
            "only consumed cycles are netted under the sequential policy"
        )
        assert bundle["bundle_status"] == "ACTIVE"


class TestBundleAllowanceIsAnnualCapped:
    """The annual slice binds when it is smaller than the lifetime allowance."""

    def test_remaining_is_capped_by_the_annual_slice(self):
        """PRD §3.9: "The remaining count is therefore the bundle's lifetime allowance,
        reduced by the cycles already consumed in the current plan year, then reduced
        again by whatever the sponsoring employer's netting policy nets out, and floored
        at zero so that it can never read negative; where the annual slice is smaller
        than the lifetime allowance, the annual slice is the binding figure."

        Design: Corner/calculations/bundle_cycle_allowance_sequential_versus_concurrent_variant_divergence
        """
        employer, bundle = setup_employer_bundle(
            bundle_overrides={"lifetime_max_cycles": 9, "max_cycles_per_year": 3})
        assert bundle["cycles_remaining"] == 3, (
            "a nine-cycle lifetime allowance with a three-cycle annual slice reads three"
        )
        assert bundle["cycles_committed"] == 0
        assert bundle["cycles_consumed"] == 0