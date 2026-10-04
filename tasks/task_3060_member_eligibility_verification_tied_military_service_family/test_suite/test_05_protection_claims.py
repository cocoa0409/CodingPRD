"""Protection claims: SCRA rate-relief arithmetic, variant selection by
deployment end-date nullability, eligibility preconditions, the fiscal
exposure cap, and supersede conservation."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers import factories, fixtures
from test_helpers.fixtures import (
    OFFICER_A,
    build_offering,
    decide_claim,
    file_rate_claim,
    member_version,
    open_entitlement,
    register_order,
)


class TestRateReliefVariants:
    def _member_with_order(self, api, name, end_date):
        """Member + ACTIVE scra_eligible order; returns (member_id, order)."""
        return fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date=end_date,
            scra_eligible=True, name=name,
        )

    def test_end_dated_order_uses_whole_months(self, api):
        """PRD §3.6.1: "The number of periods is the count of whole months
        from the `approval_effective_date` to the deployment's `end_date`,
        capped at 60..." and "Each period's relief, in integer cents, is the
        `monthly_interest_cents` scaled by the fraction of the rate removed —
        that is, multiplied by the difference between `base_rate_bps` and the
        capped rate, divided by `base_rate_bps` — with each period's result
        floored to whole cents before the periods are summed into
        `total_relief_cents`."

        Design: Difficulty/dual_variant_calc/scra_relief_standard_vs_open_ended_proration
        """
        member_id, order = self._member_with_order(
            api, "Ann Army", "2027-03-01"
        )
        claim = file_rate_claim(
            api, member_id, order["id"], 1100, 110000, "AUTO_LOAN",
        )
        decided = decide_claim(api, claim["id"], officer=OFFICER_A)
        assert decided["status"] == "APPROVED"
        assert decided["periods_granted"] == 6
        assert decided["total_relief_cents"] == 300000

    def test_open_ended_order_uses_twelve_periods(self, api):
        """PRD §3.6.1: "when the order is open-ended at approval time, the
        obligation-proration variant fixes the count at exactly 12 periods
        regardless of any `end_date` entered later."

        Design: Difficulty/dual_variant_calc/scra_relief_standard_vs_open_ended_proration
        """
        member_id, order = self._member_with_order(api, "Bob Navy", None)
        claim = file_rate_claim(
            api, member_id, order["id"], 1100, 110000, "AUTO_LOAN",
        )
        decided = decide_claim(api, claim["id"], officer=OFFICER_A)
        assert decided["status"] == "APPROVED"
        assert decided["periods_granted"] == 12
        assert decided["total_relief_cents"] == 600000


class TestFloorPerPeriodThenSum:
    def test_per_period_floor_before_sum(self, api):
        """PRD §3.6.1: "Each period's relief, in integer cents, is the
        `monthly_interest_cents` scaled by the fraction of the rate removed —
        that is, multiplied by the difference between `base_rate_bps` and the
        capped rate, divided by `base_rate_bps` — with each period's result
        floored to whole cents before the periods are summed into
        `total_relief_cents`." PRD §2.10: "Rate-relief computations floor
        each monthly period's relief to whole cents before summing across
        periods — the order is per-period floor, then sum, never
        sum-then-round."

        Design: Difficulty/combinatorial_formula/scra_relief_floor_per_period_then_sum_rounding_order
        """
        member_id, order = fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date="2027-03-01",
            scra_eligible=True, name="Cara Corps",
        )
        claim = file_rate_claim(
            api, member_id, order["id"], 700, 106, "CARD_1",
        )
        decided = decide_claim(api, claim["id"], officer=OFFICER_A)
        assert decided["status"] == "APPROVED"
        assert decided["periods_granted"] == 6
        # floor(106 * 100 / 700) = 15 per period; 15 * 6 = 90. A
        # sum-then-round implementation would report 91.
        assert decided["total_relief_cents"] == 90

    def test_per_period_floor_before_sum_second_ratio(self, api):
        """PRD §2.10: "the order is per-period floor, then sum, never
        sum-then-round." PRD §3.6.1: "with each period's result floored to
        whole cents before the periods are summed into
        `total_relief_cents`."

        Design: Difficulty/combinatorial_formula/scra_relief_floor_per_period_then_sum_rounding_order
        """
        # Second witness of the pinned order at a different ratio:
        # base 800 over 6 periods, monthly 201 -> floor(201*200/800)=50,
        # total 300 (sum-then-round would give round(6*201*200/800)=302).
        member_id, order = fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date="2027-03-01",
            scra_eligible=True, name="Cara Corps Two",
        )
        claim = file_rate_claim(
            api, member_id, order["id"], 800, 201, "CARD_2",
        )
        decided = decide_claim(api, claim["id"], officer=OFFICER_A)
        assert decided["status"] == "APPROVED"
        assert decided["periods_granted"] == 6
        assert decided["total_relief_cents"] == 300


class TestScraCapBoundary:
    def _member_with_one_month_order(self, api, name):
        return fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date="2026-10-01",
            scra_eligible=True, name=name,
        )

    def test_rate_at_cap_yields_no_relief(self, api):
        """PRD §3.6.1: "The statutory rate cap is 600 basis points: the
        capped rate is the lesser of `base_rate_bps` and 600." and "When the
        base rate is at or below 600 basis points, the per-period relief is
        zero and approval fails with `ERR_NO_RELIEF_AVAILABLE`."

        Design: Corner/calculations/scra_constants_applied_cap_at_600_bps
        """
        member_id, order = self._member_with_one_month_order(api, "Cap Carl")
        claim = file_rate_claim(
            api, member_id, order["id"], 600, 60000, "OBL_600",
        )
        resp = api.decide_protection_claim(
            claim["id"], {"decision": "APPROVE"}, OFFICER_A
        )
        validate_error(resp, ApiErrorId.ERR_NO_RELIEF_AVAILABLE)

    def test_rate_one_above_cap_yields_floored_relief(self, api):
        """PRD §3.6.1: "The statutory rate cap is 600 basis points: the
        capped rate is the lesser of `base_rate_bps` and 600." and "Each
        period's relief, in integer cents, is the `monthly_interest_cents`
        scaled by the fraction of the rate removed... with each period's
        result floored to whole cents..."

        Design: Corner/calculations/scra_constants_applied_cap_at_600_bps
        """
        member_id, order = self._member_with_one_month_order(api, "Cap Carla")
        claim = file_rate_claim(
            api, member_id, order["id"], 601, 60100, "OBL_601",
        )
        decided = decide_claim(api, claim["id"], officer=OFFICER_A)
        assert decided["status"] == "APPROVED"
        assert decided["periods_granted"] == 1
        # floor(60100 * 1 / 601) = 100
        assert decided["total_relief_cents"] == 100


class TestClaimApprovalDependencies:
    def test_decide_rejected_while_order_registered(self, api):
        """PRD §3.6: "for rate-reduction claims, that the referenced
        `deployment_order_id` resolves to an `ACTIVE` order whose
        `scra_eligible` flag is true (`ERR_SCRA_NOT_ELIGIBLE`)".

        Design: Difficulty/cross_entity_state_dependency/rate_claim_approval_depends_on_deployment_order_state
        """
        fixtures.ensure_clock(api)
        _, member_id = fixtures.approve_direct_member(
            api, name="Quinn Quay", still_serving=True,
        )
        order = register_order(
            api, member_id, start_date="2026-10-01", end_date="2027-04-01",
            scra_eligible=True,
        )
        assert order["status"] == "REGISTERED"
        claim = file_rate_claim(
            api, member_id, order["id"], 1100, 110000, "CARD_Q",
        )
        resp = api.decide_protection_claim(
            claim["id"], {"decision": "APPROVE"}, OFFICER_A
        )
        validate_error(resp, ApiErrorId.ERR_SCRA_NOT_ELIGIBLE)

    def test_decide_succeeds_once_clock_activates_order(self, api):
        """PRD §3.6: "for rate-reduction claims, that the referenced
        `deployment_order_id` resolves to an `ACTIVE` order whose
        `scra_eligible` flag is true (`ERR_SCRA_NOT_ELIGIBLE`)" and PRD §2.5:
        "Advancing the clock has exactly one retroactive consequence: every
        `REGISTERED` deployment order whose `start_date` is on or before the
        new clock reading auto-activates to `ACTIVE`..."

        Design: Difficulty/cross_entity_state_dependency/rate_claim_approval_depends_on_deployment_order_state
        """
        fixtures.ensure_clock(api)
        _, member_id = fixtures.approve_direct_member(
            api, name="Quinn Quay Two", still_serving=True,
        )
        order = register_order(
            api, member_id, start_date="2026-10-01", end_date="2027-04-01",
            scra_eligible=True,
        )
        claim = file_rate_claim(
            api, member_id, order["id"], 1100, 110000, "CARD_Q2",
        )
        validate_error(
            api.decide_protection_claim(
                claim["id"], {"decision": "APPROVE"}, OFFICER_A
            ),
            ApiErrorId.ERR_SCRA_NOT_ELIGIBLE,
        )
        fixtures.set_clock(api, "2026-10-01T00:00:00Z")
        decided = decide_claim(api, claim["id"], officer=OFFICER_A)
        assert decided["status"] == "APPROVED"
        assert decided["periods_granted"] == 6
        assert decided["total_relief_cents"] == 300000


class TestReliefCap:
    def test_completed_order_scra_error_masks_cap(self, api):
        """PRD §2.7: "the fiscal relief cap (`ERR_RELIEF_CAP_EXCEEDED`) is
        evaluated after SCRA eligibility." PRD §3.6: "The fiscal cap of
        §3.6.1 is evaluated after SCRA eligibility."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_claim_decide
        """
        # Clock pinned at the deployment's end date so completion succeeds.
        fixtures.set_clock(api, "2026-12-01T00:00:00Z")
        _, member_id = fixtures.approve_direct_member(
            api, name="Oda Ocean", still_serving=True,
        )
        offering = build_offering(
            api, categories=["ENLISTED_ACTIVE", "VETERAN_HONORABLE"],
            product_line="BANKING", product_code="AUTO_LOAN_P",
            product_name="Auto Loan",
        )
        open_entitlement(api, member_id, offering["id"], exposure_cents=100)
        order = register_order(
            api, member_id, start_date="2026-09-01", end_date="2026-12-01",
            scra_eligible=True,
        )
        validate_success(api.complete_deployment_order(order["id"], OFFICER_A))
        claim = file_rate_claim(
            api, member_id, order["id"], 1200, 12000, "OBL_X",
        )
        resp = api.decide_protection_claim(
            claim["id"], {"decision": "APPROVE"}, OFFICER_A
        )
        validate_error(resp, ApiErrorId.ERR_SCRA_NOT_ELIGIBLE)
        current = validate_success(
            api.get_protection_claim(claim["id"], OFFICER_A)
        )
        assert current["status"] == "REQUESTED"

    def test_claim_against_unknown_order_rejected_at_filing(self, api):
        """PRD §2.7: "foreign-key resolution producing
        `ERR_INVALID_REFERENCE`" — the second leg of the pair: a claim filed
        against a non-existent deployment order fails the referential check.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_claim_decide
        """
        fixtures.ensure_clock(api)
        _, member_id = fixtures.approve_direct_member(
            api, name="Oda Ocean Two", still_serving=True,
        )
        payload = factories.protection_claim_payload(
            claim_type="RATE_REDUCTION", obligation_label="OBL_BAD",
            deployment_order_id=NON_EXISTENT_UUID,
            base_rate_bps=1100, monthly_interest_cents=110000,
        )
        headers = fixtures.make_member_headers(member_id)
        resp = api.create_protection_claim(member_id, payload, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)

    def test_relief_exceeding_exposure_cap_rejected(self, api):
        """PRD §3.6.1: "Fourth, the check itself: the net relief plus the sum
        of `total_relief_cents` across the member's `APPROVED` claims must
        not exceed the member's exposure cap, which is the sum of
        `exposure_cents` over the member's `OPEN` and `GRANDFATHERED`
        entitlements. A violation is rejected with
        `ERR_RELIEF_CAP_EXCEEDED`."

        Design: Corner/errors/relief_cap_exceeded_triggerable
        """
        member_id, order = fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date="2026-12-01",
            scra_eligible=True, name="Cap Cara",
        )
        offering = build_offering(
            api, categories=["ENLISTED_ACTIVE", "VETERAN_HONORABLE"],
            product_line="BANKING", product_code="LOAN_SM",
            product_name="Small Loan",
        )
        open_entitlement(api, member_id, offering["id"], exposure_cents=1000)
        claim = file_rate_claim(
            api, member_id, order["id"], 1100, 1200, "OBL_CAP",
        )
        resp = api.decide_protection_claim(
            claim["id"], {"decision": "APPROVE"}, OFFICER_A
        )
        validate_error(resp, ApiErrorId.ERR_RELIEF_CAP_EXCEEDED)
        current = validate_success(
            api.get_protection_claim(claim["id"], OFFICER_A)
        )
        assert current["status"] == "REQUESTED"


class TestPinnedCapEvaluationOrder:
    def _setup_three_claims(self, api):
        """Member with exposure cap 10000, a 36-period scra order, and two
        APPROVED claims (1944 + 5544 = 7488 outstanding); returns member,
        order, and the two approved claims."""
        member_id, order = fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date="2029-09-01",
            scra_eligible=True, name="Dana Wing",
        )
        offering = build_offering(
            api, product_line="BANKING", product_code="CK_BASIC",
            product_name="Basic Checking",
        )
        open_entitlement(api, member_id, offering["id"], exposure_cents=10000)
        claim_a = file_rate_claim(
            api, member_id, order["id"], 1100, 120, "OBL_A",
        )
        approved_a = decide_claim(api, claim_a["id"], officer=OFFICER_A)
        claim_b = file_rate_claim(
            api, member_id, order["id"], 1100, 340, "OBL_B",
        )
        approved_b = decide_claim(api, claim_b["id"], officer=OFFICER_A)
        return member_id, order, approved_a, approved_b

    def test_outstanding_offset_totals(self, api):
        """PRD §3.6.1: "Second, the bank offset is the sum of
        `total_relief_cents` over the member's other claims currently in
        `APPROVED` status — `SUPERSEDED` and `DENIED` claims are excluded."

        Design: Difficulty/combinatorial_formula/protection_relief_cap_pinned_evaluation_order
        """
        _, _, approved_a, approved_b = self._setup_three_claims(api)
        # floor(120*500/1100)=54 over 36 periods; floor(340*500/1100)=154.
        assert approved_a["total_relief_cents"] == 1944
        assert approved_b["total_relief_cents"] == 5544

    def test_netting_before_cap_comparison_allows_third_claim(self, api):
        """PRD §3.6.1: "Third, because offset netting is mandated, the net
        relief is the gross relief reduced by the lesser of the bank offset
        and the gross relief minus one, floored at zero. Fourth, the check
        itself: the net relief plus the sum of `total_relief_cents` across
        the member's `APPROVED` claims must not exceed the member's exposure
        cap..."

        Design: Difficulty/combinatorial_formula/protection_relief_cap_pinned_evaluation_order
        """
        member_id, order, _, _ = self._setup_three_claims(api)
        claim_c = file_rate_claim(
            api, member_id, order["id"], 1100, 500, "OBL_C",
        )
        # Gross = floor(500*500/1100)=227 over 36 = 8172; cap on gross would
        # reject (8172 + 7488 = 15660 > 10000), but the pinned order nets
        # first: 8172 - min(7488, 8171) = 684; 684 + 7488 = 8172 <= 10000.
        decided = decide_claim(api, claim_c["id"], officer=OFFICER_A)
        assert decided["status"] == "APPROVED"
        assert decided["total_relief_cents"] == 8172


class TestSupersedeConservation:
    def _setup_supersede_scenario(self, api):
        member_id, order = fixtures.setup_active_member_with_deployment(
            api, start_date="2026-09-01", end_date="2027-09-01",
            scra_eligible=True, name="Val Vale",
        )
        offering = build_offering(
            api, categories=["ENLISTED_ACTIVE", "VETERAN_HONORABLE",
                             "OFFICER_CADET"],
            product_line="BANKING", product_code="CARD_PREM",
            product_name="Premium Card",
        )
        open_entitlement(api, member_id, offering["id"],
                         exposure_cents=1000000)
        claim1 = file_rate_claim(
            api, member_id, order["id"], 1100, 110000, "OBL_Z",
        )
        approved1 = decide_claim(api, claim1["id"], officer=OFFICER_A)
        claim2 = file_rate_claim(
            api, member_id, order["id"], 900, 90000, "OBL_Z",
        )
        return member_id, approved1, claim2

    def test_replacement_approval_supersedes_prior_claim(self, api):
        """PRD §3.6: "Approving a claim for an obligation that already has
        an `APPROVED` claim automatically moves that older claim to
        `SUPERSEDED` — the only exit from `APPROVED` — while the superseded
        claim keeps its historical `total_relief_cents` and the newer claim's
        relief is computed from its own `approval_effective_date` forward."

        Design: Difficulty/compensating_invariant/relief_conservation_across_supersede
        """
        member_id, approved1, claim2 = self._setup_supersede_scenario(api)
        assert approved1["total_relief_cents"] == 600000
        decided2 = decide_claim(api, claim2["id"], officer=OFFICER_A)
        assert decided2["status"] == "APPROVED"
        assert decided2["total_relief_cents"] == 360000
        first = validate_success(
            api.get_protection_claim(approved1["id"], OFFICER_A)
        )
        assert first["status"] == "SUPERSEDED"
        assert first["total_relief_cents"] == 600000
        # Conservation: exactly one APPROVED claim per obligation contributes.
        claims = validate_success(
            api.list_member_protection_claims(member_id, OFFICER_A)
        )
        approved_totals = [
            c["total_relief_cents"] for c in claims
            if c["status"] == "APPROVED" and c["obligation_label"] == "OBL_Z"
        ]
        assert sum(approved_totals) == 360000

    def test_denying_replacement_leaves_original_approved(self, api):
        """PRD §3.6: "A `VerificationOfficer` decides a `REQUESTED` claim
        with a `decision` of `APPROVE` or `DENY` and an optional
        `decision_note`. Denial needs nothing further."

        Design: Difficulty/compensating_invariant/relief_conservation_across_supersede
        """
        member_id, approved1, claim2 = self._setup_supersede_scenario(api)
        denied2 = decide_claim(api, claim2["id"], decision="DENY",
                               officer=OFFICER_A)
        assert denied2["status"] == "DENIED"
        first = validate_success(
            api.get_protection_claim(approved1["id"], OFFICER_A)
        )
        assert first["status"] == "APPROVED"
        assert first["total_relief_cents"] == 600000
