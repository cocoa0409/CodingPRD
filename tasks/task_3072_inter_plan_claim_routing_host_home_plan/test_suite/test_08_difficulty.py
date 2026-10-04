"""Difficulty-design (queue A) tests: dual-variant calculations, combinatorial formulas, cycles, cascades, validation priority, boundaries, cross-entity gating, overlap, compensating invariants."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    ApiClient,
    create_applied_adjustment,
    create_finalized_batch,
    create_paid_claim,
    create_priced_claim,
    create_propagated_adjustment,
    create_routed_claim,
    get_success_data,
    set_clock,
    setup_paid_claim_world,
    setup_two_plan_world,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.test_users import make_home_plan_operator_headers


class TestClaimPricingDualVariant:
    def test_provisional_service_date_vs_final_pricing_date(self, api: ApiClient):
        """PRD §3.5: "it looks up the host plan's rate schedule for the submitted provider and procedure whose half-open window covers the `service_date`, sets `provisional_allowed_cents` to the smaller of `billed_amount_cents` and that schedule's `negotiated_rate_cents`"
        PRD §3.5: "it looks up the same rate schedule triple but keys the half-open window on the current logical clock date — the pricing date — and sets `priced_allowed_cents` to the smaller of `billed_amount_cents` and the matched `negotiated_rate_cents`."

        Design: Difficulty/dual_variant_calc/claim_pricing_service_date_vs_pricing_date_variant
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        host = world["host"]

        from test_helpers import create_rate_schedule

        create_rate_schedule(
            api, host, negotiated_rate_cents=20000, effective_start="2026-01-01", effective_end="2026-09-01"
        )
        create_rate_schedule(
            api, host, negotiated_rate_cents=30000, effective_start="2026-09-01", effective_end="2027-01-01"
        )

        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], host["id"], service_date="2026-08-15", billed_amount_cents=25000),
                world["host_headers"],
            )
        )
        assert claim["provisional_allowed_cents"] == 20000

        set_clock(api, "2026-10-01T00:00:00Z")
        priced = validate_success(api.price_claim(claim["id"], world["host_headers"]), 200)
        assert priced["priced_allowed_cents"] == 25000
        assert priced["current_allowed_cents"] == 25000
        assert priced["provisional_allowed_cents"] == 20000

    def test_provisional_fallback_vs_final_hard_failure(self, api: ApiClient):
        """PRD §3.5: "when no schedule window covers the service date — falls back to setting `provisional_allowed_cents` equal to the full `billed_amount_cents`."
        PRD §3.5: "Final pricing has no fallback: when no rate window covers the pricing date, the transition fails with `ERR_RATE_SCHEDULE_MISSING` (HTTP 422)."

        Design: Difficulty/dual_variant_calc/claim_pricing_service_date_vs_pricing_date_variant
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"], billed_amount_cents=25000),
                world["host_headers"],
            )
        )
        assert claim["provisional_allowed_cents"] == 25000

        res = api.price_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_RATE_SCHEDULE_MISSING", 422)


class TestSettlementNetVsGross:
    def _pay_two_claims(self, api, world):
        member2 = get_success_data(
            api.create_member(f.member_payload(world["home"]["id"], member_number="M2", full_name="Pat Two"), world["home_headers"])
        )
        c1 = create_paid_claim(api, world, service_date="2026-08-10", billed_amount_cents=20000)
        world_b = dict(world)
        world_b["member"] = member2
        c2 = create_paid_claim(api, world_b, service_date="2026-08-11", billed_amount_cents=20000)
        return c1, c2

    def test_net_variant_deducts_fees_from_remittance(self, api: ApiClient):
        """PRD §3.8: "under the `NET` variant the fees are deducted from the remittance, so the net settlement is the gross claims total minus the fees total"

        Design: Difficulty/dual_variant_calc/settlement_net_vs_gross_variant
        """
        world = setup_two_plan_world(api)
        self._pay_two_claims(api, world)

        batch = get_success_data(
            api.create_settlement_batch(
                f.settlement_batch_payload(world["home"]["id"], world["host"]["id"], settlement_variant="NET"),
                world["host_headers"],
            )
        )
        finalized = validate_success(api.finalize_batch(batch["id"], world["host_headers"]), 200)
        assert finalized["gross_claims_total_cents"] == 40000
        assert finalized["fees_total_cents"] == 2400
        assert finalized["net_settlement_cents"] == 37600

    def test_gross_variant_remitts_full_gross(self, api: ApiClient):
        """PRD §3.8: "under the `GROSS` variant the full provider-payment gross is remitted and the fees are settled separately, so the net settlement equals the gross claims total alone."

        Design: Difficulty/dual_variant_calc/settlement_net_vs_gross_variant
        """
        world = setup_two_plan_world(api)
        self._pay_two_claims(api, world)

        batch = get_success_data(
            api.create_settlement_batch(
                f.settlement_batch_payload(world["home"]["id"], world["host"]["id"], settlement_variant="GROSS"),
                world["host_headers"],
            )
        )
        finalized = validate_success(api.finalize_batch(batch["id"], world["host_headers"]), 200)
        assert finalized["gross_claims_total_cents"] == 40000
        assert finalized["fees_total_cents"] == 2400
        assert finalized["net_settlement_cents"] == 40000


class TestAccessFeeTierDiscountComposition:
    def test_tier2_base_fee_with_active_discount(self, api: ApiClient):
        """PRD §3.5: "When the current allowed amount exceeds the cap, the base fee is the full allowed amount multiplied by `tier2_rate`, rounded half-up to integer cents"
        PRD §3.5: "in that case the access fee is the base fee multiplied by one minus the schedule's `national_account_discount_pct`, rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/access_fee_tier_discount_composition
        """
        world = setup_two_plan_world(
            api,
            with_national_account=True,
            fee_overrides={"national_account_discount_pct": 0.25},
        )
        claim = create_routed_claim(api, world)
        assert claim["access_fee_cents"] == 300
        assert claim["status"] == "ROUTED"

    def test_tier2_base_fee_without_account_no_discount(self, api: ApiClient):
        """PRD §3.5: "When any of those conditions fails — no national account on the claim, an account controlled by a different plan, a suspended or terminated account, or a service date outside the account window — the fee is simply the undiscounted base fee."

        Design: Difficulty/combinatorial_formula/access_fee_tier_discount_composition
        """
        world = setup_two_plan_world(api, fee_overrides={"national_account_discount_pct": 0.25})
        claim = create_routed_claim(api, world)
        assert claim["access_fee_cents"] == 400


class TestAdminChargeRoundingOrder:
    def test_round_per_bracket_then_sum(self, api: ApiClient):
        """PRD §3.5: "Each bracket's charge is computed on its own slice and rounded half-up to integer cents first, and only then are the rounded bracket charges summed — rounding per bracket and then summing is the pinned order; summing the raw slices and rounding once is forbidden."

        Design: Difficulty/combinatorial_formula/admin_charge_round_per_bracket_then_sum
        """
        world = setup_two_plan_world(
            api,
            rate_overrides={"negotiated_rate_cents": 150000, "procedure_code": "99214"},
        )
        claim = create_routed_claim(api, world, procedure_code="99214", billed_amount_cents=100333)
        assert claim["admin_charge_cents"] == 3203
        assert claim["access_fee_cents"] == 2007

    def test_admin_charge_single_bracket(self, api: ApiClient):
        """PRD §3.5: "the slice of the allowed amount up to and including 10000 cents is charged at 5 percent"

        Design: Difficulty/combinatorial_formula/admin_charge_round_per_bracket_then_sum
        """
        world = setup_two_plan_world(
            api,
            rate_overrides={"negotiated_rate_cents": 8000},
        )
        claim = create_routed_claim(api, world, billed_amount_cents=50000)
        assert claim["admin_charge_cents"] == 400


class TestClaimPaidAdjustmentCycle:
    def test_paid_adjustment_cycle_returns_to_paid(self, api: ApiClient):
        """PRD §3.7: "Creating the adjustment moves a `PAID` claim to `ADJUSTMENT_PENDING`"
        PRD §3.7: "Application, again by the host plan, moves a `PROPAGATED` adjustment to `APPLIED` and returns the parent claim from `ADJUSTMENT_PENDING` to `PAID`."

        Design: Difficulty/non_linear_state_machine/claim_paid_adjustment_cycle_returns_to_paid
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]

        adjustment = create_applied_adjustment(api, world, claim, delta=-5000, reason="repricing")
        assert adjustment["status"] == "APPLIED"
        assert adjustment["recovery_amount_cents"] == 5000

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["status"] == "PAID"
        assert claim_after["current_allowed_cents"] == 15000

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 15000

    def test_paid_adjustment_cycle_can_repeat(self, api: ApiClient):
        """PRD §3.7: "A paid claim may be corrected through an **adjustment**, created by a `HostPlanOperator` of the host plan against a claim in `PAID` or `ADJUSTMENT_PENDING` status."

        The cycle PAID -> ADJUSTMENT_PENDING -> PAID may repeat with balances mutated on each traversal.

        Design: Difficulty/non_linear_state_machine/claim_paid_adjustment_cycle_returns_to_paid
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]

        a1 = create_applied_adjustment(api, world, claim, delta=-5000, reason="first")
        claim_after_first = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after_first["status"] == "PAID"
        assert claim_after_first["current_allowed_cents"] == 15000

        a2 = create_applied_adjustment(api, world, claim_after_first, delta=-5000, reason="second")
        assert a2["status"] == "APPLIED"
        claim_after_second = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after_second["status"] == "PAID"
        assert claim_after_second["current_allowed_cents"] == 10000

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 10000


class TestSettlementDisputeRefinalizeCycle:
    def test_dispute_refinalize_cycle_until_acknowledged(self, api: ApiClient):
        """PRD §3.8: "A batch may cycle `FINALIZED` to `DISPUTED` to `FINALIZED` repeatedly until it is acknowledged."

        Design: Difficulty/non_linear_state_machine/settlement_batch_dispute_refinalize_cycle
        """
        world = setup_paid_claim_world(api)
        batch = create_finalized_batch(api, world)
        assert batch["gross_claims_total_cents"] == 20000

        disputed = get_success_data(api.dispute_batch(batch["id"], world["home_headers"]))
        refinalized = validate_success(
            api.refinalize_batch(batch["id"], f.refinalize_payload(disputed["version"]), world["host_headers"]),
            200,
        )
        assert refinalized["status"] == "FINALIZED"
        assert refinalized["gross_claims_total_cents"] == 20000

        disputed2 = get_success_data(api.dispute_batch(batch["id"], world["home_headers"]))
        refinalized2 = validate_success(
            api.refinalize_batch(batch["id"], f.refinalize_payload(disputed2["version"]), world["host_headers"]),
            200,
        )
        assert refinalized2["gross_claims_total_cents"] == 20000

        acknowledged = validate_success(api.acknowledge_batch(batch["id"], world["home_headers"]), 200)
        assert acknowledged["status"] == "ACKNOWLEDGED"

    def test_refinalize_recomputes_same_totals_for_unchanged_population(self, api: ApiClient):
        """PRD §3.8: "re-finalization recomputes all totals with the same sweep rule as the original finalization"

        Design: Difficulty/non_linear_state_machine/settlement_batch_dispute_refinalize_cycle
        """
        world = setup_paid_claim_world(api)
        batch = create_finalized_batch(api, world)
        disputed = get_success_data(api.dispute_batch(batch["id"], world["home_headers"]))
        refinalized = validate_success(
            api.refinalize_batch(batch["id"], f.refinalize_payload(disputed["version"]), world["host_headers"]),
            200,
        )
        assert refinalized["gross_claims_total_cents"] == batch["gross_claims_total_cents"]
        assert refinalized["fees_total_cents"] == batch["fees_total_cents"]
        assert refinalized["net_settlement_cents"] == batch["net_settlement_cents"]


class TestAdjustmentApplyCascade:
    def test_apply_cascades_claim_and_host_balance(self, api: ApiClient):
        """PRD §3.7: "Application, again by the host plan, moves a `PROPAGATED` adjustment to `APPLIED` and returns the parent claim from `ADJUSTMENT_PENDING` to `PAID`."
        PRD §3.7: "The host plan's `claims_paid_balance_cents` is then reduced by the recovery amount; the receivables ledger is untouched by recoveries."

        Design: Difficulty/transitive_cascade/adjustment_apply_cascades_claim_and_host_balance
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        adjustment = create_propagated_adjustment(api, world, claim, delta=-5000, reason="audit recovery")

        applied = validate_success(api.apply_adjustment(adjustment["id"], world["host_headers"]), 200)
        assert applied["status"] == "APPLIED"

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["status"] == "PAID"
        assert claim_after["current_allowed_cents"] == 15000

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 15000

    def test_apply_upward_delta_has_zero_recovery(self, api: ApiClient):
        """PRD §3.7: "The adjustment's `recovery_amount_cents` is the magnitude of the delta when the delta is negative and the claim had been paid — that is, the larger of zero and the negated delta — and zero for any upward delta."

        Design: Difficulty/transitive_cascade/adjustment_apply_cascades_claim_and_host_balance
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        adjustment = create_propagated_adjustment(api, world, claim, delta=3000, reason="underpayment")
        applied = validate_success(api.apply_adjustment(adjustment["id"], world["host_headers"]), 200)
        assert applied["recovery_amount_cents"] == 0

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["current_allowed_cents"] == 23000

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 20000


class TestBatchReconcileCascade:
    def test_reconcile_cascades_swept_claims_to_settled(self, api: ApiClient):
        """PRD §3.8: "an `AssociationAdmin` reconciles a `DISBURSED` batch, moving it to the terminal `RECONCILED` state, at which point every swept claim transitions from `PAID` to `SETTLED`."

        Design: Difficulty/transitive_cascade/batch_reconcile_cascades_swept_claims_to_settled
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]

        batch = create_finalized_batch(api, world)
        get_success_data(api.acknowledge_batch(batch["id"], world["home_headers"]))
        get_success_data(api.disburse_batch(batch["id"], ASSOCIATION_ADMIN_HEADERS))
        reconciled = validate_success(api.reconcile_batch(batch["id"], ASSOCIATION_ADMIN_HEADERS), 200)
        assert reconciled["status"] == "RECONCILED"

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["status"] == "SETTLED"

        res = api.pay_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_INVALID_STATE", 409)

    def test_reconcile_block_claims_stay_settled(self, api: ApiClient):
        """PRD §3.8: "an `AssociationAdmin` reconciles a `DISBURSED` batch, moving it to the terminal `RECONCILED` state, at which point every swept claim transitions from `PAID` to `SETTLED`."
        PRD §3.6: "The claim stays in `PAID` — visible to settlement sweeps — until it is either adjusted or swept into a reconciled batch, at which point it reaches the terminal `SETTLED` state."

        Design: Difficulty/transitive_cascade/batch_reconcile_cascades_swept_claims_to_settled
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        from test_helpers import create_reconciled_batch

        create_reconciled_batch(api, world)
        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["status"] == "SETTLED"

        res_price = api.price_claim(claim["id"], world["host_headers"])
        validate_error(res_price, "ERR_INVALID_STATE", 409)


class TestValidationPriorityPairs:
    def test_state_beats_suspended_license_on_claim_route(self, api: ApiClient):
        """PRD §2.8: "Every request passes through the same ordered validation pipeline, and the first failing check determines the error returned. The checks, in order, are: authentication of the headers (§2.1, `ERR_UNAUTHENTICATED`); role authorization for the endpoint including plan-scoped ownership (`ERR_UNAUTHORIZED`); existence of every path identifier and every foreign key referenced in the body, validated left to right (`ERR_NOT_FOUND`, HTTP 404); whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409); and finally the business rules — license status, service area, window overlap, same-plan, uniqueness, amount, and floor constraints"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_suspended_license_on_claim_route
        """
        world = setup_two_plan_world(api)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        get_success_data(api.suspend_license(world["home"]["id"], ASSOCIATION_ADMIN_HEADERS))

        res = api.route_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_INVALID_STATE", 409)

    def test_license_violation_surfaces_when_state_allows(self, api: ApiClient):
        """PRD §3.5: "Routing first re-checks that both the home and host plans are `LICENSED` (a plan suspended between submission and routing blocks the transition with `ERR_PLAN_LICENSE_SUSPENDED`)"

        A PRICED claim (state satisfied) routing while the home plan is suspended surfaces the license error.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_suspended_license_on_claim_route
        """
        world = setup_two_plan_world(api)
        claim = create_priced_claim(api, world)
        get_success_data(api.suspend_license(world["home"]["id"], ASSOCIATION_ADMIN_HEADERS))
        res = api.route_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_PLAN_LICENSE_SUSPENDED", 409)

    def test_temporal_beats_fiscal_on_claim_create(self, api: ApiClient):
        """PRD §2.8: "Every request passes through the same ordered validation pipeline, and the first failing check determines the error returned. The checks, in order, are: authentication of the headers (§2.1, `ERR_UNAUTHENTICATED`); role authorization for the endpoint including plan-scoped ownership (`ERR_UNAUTHORIZED`); existence of every path identifier and every foreign key referenced in the body, validated left to right (`ERR_NOT_FOUND`, HTTP 404); whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409); and finally the business rules — license status, service area, window overlap, same-plan, uniqueness, amount, and floor constraints"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_claim_create
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        res = api.create_claim(
            f.claim_payload(
                world["member"]["id"],
                world["host"]["id"],
                service_state="NV",
                billed_amount_cents=0,
            ),
            world["host_headers"],
        )
        validate_error(res, "ERR_OUT_OF_SERVICE_AREA", 422)

    def test_amount_violation_surfaces_when_state_and_area_satisfied(self, api: ApiClient):
        """PRD §3.5: "the provider's `billed_amount_cents`, which must be greater than zero (otherwise `ERR_INVALID_AMOUNT`)"

        A zero billed amount with an in-area service state surfaces the amount error.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_claim_create
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        res = api.create_claim(
            f.claim_payload(world["member"]["id"], world["host"]["id"], billed_amount_cents=0),
            world["host_headers"],
        )
        validate_error(res, "ERR_INVALID_AMOUNT", 422)


class TestAccessFeeTier1Boundary:
    def test_allowed_exactly_at_cap_takes_flat_fee(self, api: ApiClient):
        """PRD §3.5: "When the current allowed amount is at or below the schedule's `tier1_cap_cents` — the boundary is inclusive — the base fee is the flat `tier1_fee_cents`."

        Design: Difficulty/boundary_precision_check/access_fee_tier1_cap_inclusive_boundary
        """
        world = setup_two_plan_world(
            api,
            rate_overrides={"negotiated_rate_cents": 10000},
        )
        claim = create_routed_claim(api, world, billed_amount_cents=50000)
        assert claim["current_allowed_cents"] == 10000
        assert claim["access_fee_cents"] == 150

    def test_allowed_one_cent_above_cap_takes_percentage(self, api: ApiClient):
        """PRD §3.5: "When the current allowed amount exceeds the cap, the base fee is the full allowed amount multiplied by `tier2_rate`, rounded half-up to integer cents"

        Design: Difficulty/boundary_precision_check/access_fee_tier1_cap_inclusive_boundary
        """
        world = setup_two_plan_world(
            api,
            rate_overrides={"negotiated_rate_cents": 10001, "procedure_code": "99214"},
        )
        claim = create_routed_claim(api, world, procedure_code="99214", billed_amount_cents=50000)
        assert claim["current_allowed_cents"] == 10001
        assert claim["access_fee_cents"] == 200


class TestEmptyBatchFinalize:
    def test_empty_batch_finalize_rejected(self, api: ApiClient):
        """PRD §3.8: "If the scope contains no `PAID` claim at all, finalization fails with `ERR_EMPTY_BATCH` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/empty_batch_finalize_rejected
        """
        world = setup_paid_claim_world(api)

        empty_batch = get_success_data(
            api.create_settlement_batch(
                f.settlement_batch_payload(
                    world["home"]["id"], world["host"]["id"], period_start="2026-06-01", period_end="2026-06-30"
                ),
                world["host_headers"],
            )
        )
        res = api.finalize_batch(empty_batch["id"], world["host_headers"])
        validate_error(res, "ERR_EMPTY_BATCH", 422)

    def test_batch_with_one_paid_claim_finalizes(self, api: ApiClient):
        """PRD §3.8: "If the scope contains no `PAID` claim at all, finalization fails with `ERR_EMPTY_BATCH` (HTTP 422)."
        PRD §3.8: "From the swept claims the system computes `gross_claims_total_cents` as the sum of their `provider_payment_cents`"

        Design: Difficulty/boundary_precision_check/empty_batch_finalize_rejected
        """
        world = setup_paid_claim_world(api)
        batch = get_success_data(
            api.create_settlement_batch(
                f.settlement_batch_payload(world["home"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        finalized = validate_success(api.finalize_batch(batch["id"], world["host_headers"]), 200)
        assert finalized["status"] == "FINALIZED"
        assert finalized["gross_claims_total_cents"] == 20000


class TestCrossEntityGating:
    def test_benefit_determination_gated_on_member_eligibility(self, api: ApiClient):
        """PRD §3.6: "Benefit determination moves the claim from `ROUTED` to `BENEFIT_DETERMINED` and requires the member's `eligibility_status` to be `ACTIVE` at that moment; a member who has since been terminated causes the determination to fail with `ERR_MEMBER_INELIGIBLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/benefit_determination_gated_on_member_eligibility
        """
        world = setup_two_plan_world(api)
        claim = create_routed_claim(api, world)
        get_success_data(api.terminate_member(world["member"]["id"], world["home_headers"]))

        res = api.determine_benefit(claim["id"], world["home_headers"])
        validate_error(res, "ERR_MEMBER_INELIGIBLE", 422)

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["status"] == "ROUTED"

    def test_benefit_determination_succeeds_for_active_member(self, api: ApiClient):
        """PRD §3.6: "Benefit determination moves the claim from `ROUTED` to `BENEFIT_DETERMINED` and requires the member's `eligibility_status` to be `ACTIVE` at that moment"

        Design: Difficulty/cross_entity_state_dependency/benefit_determination_gated_on_member_eligibility
        """
        world = setup_two_plan_world(api)
        claim = create_routed_claim(api, world)
        determined = validate_success(api.determine_benefit(claim["id"], world["home_headers"]), 200)
        assert determined["status"] == "BENEFIT_DETERMINED"

    def test_account_activation_gated_on_controlling_plan_license(self, api: ApiClient):
        """PRD §3.3: "Activation moves it from `PROPOSED` to `ACTIVE` and is permitted only while the controlling plan's `brand_license_status` is `LICENSED`."

        Design: Difficulty/cross_entity_state_dependency/national_account_activation_gated_on_controlling_plan_license
        """
        from test_helpers import create_plan, create_national_account

        set_clock(api)
        home = create_plan(api, plan_code="HCA", service_area_states=["CA"])
        account = create_national_account(api, home)

        res = api.activate_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS)
        validate_error(res, "ERR_INVALID_STATE", 409)

        get_success_data(api.activate_license(home["id"], ASSOCIATION_ADMIN_HEADERS))
        activated = validate_success(api.activate_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS), 200)
        assert activated["status"] == "ACTIVE"

    def test_account_reactivation_also_gated_on_license(self, api: ApiClient):
        """PRD §3.3: "Reactivation returns a `SUSPENDED` account to `ACTIVE`, again only while the controlling plan is `LICENSED`."

        Design: Difficulty/cross_entity_state_dependency/national_account_activation_gated_on_controlling_plan_license
        """
        from test_helpers import create_licensed_plan, create_national_account

        set_clock(api)
        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        account = create_national_account(api, home)
        get_success_data(api.activate_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS))
        get_success_data(api.suspend_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS))

        get_success_data(api.suspend_license(home["id"], ASSOCIATION_ADMIN_HEADERS))
        res = api.reactivate_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS)
        validate_error(res, "ERR_INVALID_STATE", 409)


class TestRateWindowOverlap:
    def test_half_open_adjacency_permitted_and_overlap_rejected(self, api: ApiClient):
        """PRD §3.4: "For a given triple of plan, provider, and procedure code, half-open windows may never overlap; because the windows are half-open, a new window whose start equals an existing window's end does not overlap it, while any other intersection is rejected with `ERR_RATE_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_adjacency_permitted
        """
        from test_helpers import create_plan

        set_clock(api)
        host = create_plan(api, plan_code="TTX", legal_name="Host Plan TX", service_area_states=["TX"])
        from test_helpers.test_users import make_host_plan_operator_headers

        host_headers = make_host_plan_operator_headers(host["id"])

        get_success_data(
            api.create_rate_schedule(
                f.rate_schedule_payload(host["id"], negotiated_rate_cents=20000, effective_start="2026-01-01", effective_end="2026-09-01"),
                host_headers,
            )
        )
        adjacent = validate_success(
            api.create_rate_schedule(
                f.rate_schedule_payload(host["id"], negotiated_rate_cents=30000, effective_start="2026-09-01", effective_end="2027-01-01"),
                host_headers,
            ),
            201,
        )
        assert adjacent["effective_start"] == "2026-09-01"

        res = api.create_rate_schedule(
            f.rate_schedule_payload(host["id"], negotiated_rate_cents=25000, effective_start="2026-08-31", effective_end="2026-12-31"),
            host_headers,
        )
        validate_error(res, "ERR_RATE_WINDOW_OVERLAP", 422)

    def test_identical_window_rejected_as_overlap(self, api: ApiClient):
        """PRD §3.4: "For a given triple of plan, provider, and procedure code, half-open windows may never overlap; because the windows are half-open, a new window whose start equals an existing window's end does not overlap it, while any other intersection is rejected with `ERR_RATE_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/rate_schedule_half_open_adjacency_permitted
        """
        from test_helpers import create_plan
        from test_helpers.test_users import make_host_plan_operator_headers

        set_clock(api)
        host = create_plan(api, plan_code="TTX", legal_name="Host Plan TX", service_area_states=["TX"])
        host_headers = make_host_plan_operator_headers(host["id"])
        get_success_data(
            api.create_rate_schedule(
                f.rate_schedule_payload(host["id"], effective_start="2026-01-01", effective_end="2026-09-01"),
                host_headers,
            )
        )
        res = api.create_rate_schedule(
            f.rate_schedule_payload(host["id"], negotiated_rate_cents=25000, effective_start="2026-01-01", effective_end="2026-09-01"),
            host_headers,
        )
        validate_error(res, "ERR_RATE_WINDOW_OVERLAP", 422)


class TestFeeWindowOverlap:
    def test_closed_adjacency_counts_as_overlap(self, api: ApiClient):
        """PRD §3.4: "For a given home-host pair, closed windows may never overlap — and here, unlike rate windows, adjacency sharing an endpoint date does count as overlap, since both endpoints are inclusive — with violations rejected as `ERR_FEE_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/access_fee_schedule_closed_adjacency_overlaps
        """
        from test_helpers import create_plan

        set_clock(api)
        home = create_plan(api, plan_code="HCA", legal_name="Home Plan CA", service_area_states=["CA"])
        host = create_plan(api, plan_code="TTX", legal_name="Host Plan TX", service_area_states=["TX"])

        get_success_data(
            api.create_access_fee_schedule(
                f.access_fee_schedule_payload(home["id"], host["id"], effective_start="2026-01-01", effective_end="2026-06-30"),
                ASSOCIATION_ADMIN_HEADERS,
            )
        )
        res = api.create_access_fee_schedule(
            f.access_fee_schedule_payload(home["id"], host["id"], tier1_fee_cents=160, effective_start="2026-06-30", effective_end="2026-12-31"),
            ASSOCIATION_ADMIN_HEADERS,
        )
        validate_error(res, "ERR_FEE_WINDOW_OVERLAP", 422)

    def test_window_starting_day_after_inclusive_end_accepted(self, api: ApiClient):
        """PRD §3.4: "For a given home-host pair, closed windows may never overlap — and here, unlike rate windows, adjacency sharing an endpoint date does count as overlap, since both endpoints are inclusive — with violations rejected as `ERR_FEE_WINDOW_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/access_fee_schedule_closed_adjacency_overlaps
        """
        from test_helpers import create_plan

        set_clock(api)
        home = create_plan(api, plan_code="HCA", legal_name="Home Plan CA", service_area_states=["CA"])
        host = create_plan(api, plan_code="TTX", legal_name="Host Plan TX", service_area_states=["TX"])

        get_success_data(
            api.create_access_fee_schedule(
                f.access_fee_schedule_payload(home["id"], host["id"], effective_start="2026-01-01", effective_end="2026-06-30"),
                ASSOCIATION_ADMIN_HEADERS,
            )
        )
        ok = validate_success(
            api.create_access_fee_schedule(
                f.access_fee_schedule_payload(home["id"], host["id"], tier1_fee_cents=160, effective_start="2026-07-01", effective_end="2026-12-31"),
                ASSOCIATION_ADMIN_HEADERS,
            ),
            201,
        )
        assert ok["tier1_fee_cents"] == 160


class TestCompensatingInvariants:
    def test_pay_then_full_recovery_restores_claims_paid_balance(self, api: ApiClient):
        """PRD §3.7: "The adjustment's `recovery_amount_cents` is the magnitude of the delta when the delta is negative and the claim had been paid — that is, the larger of zero and the negated delta — and zero for any upward delta. The host plan's `claims_paid_balance_cents` is then reduced by the recovery amount"

        Design: Difficulty/compensating_invariant/pay_then_full_recovery_restores_claims_paid_balance
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]

        host_after_pay = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after_pay["claims_paid_balance_cents"] == 20000

        adjustment = create_applied_adjustment(api, world, claim, delta=-20000, reason="full takeback")
        assert adjustment["recovery_amount_cents"] == 20000

        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["current_allowed_cents"] == 0

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 0

    def test_partial_recovery_leaves_remainder(self, api: ApiClient):
        """PRD §3.7: "The host plan's `claims_paid_balance_cents` is then reduced by the recovery amount; the receivables ledger is untouched by recoveries."

        Design: Difficulty/compensating_invariant/pay_then_full_recovery_restores_claims_paid_balance
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        create_applied_adjustment(api, world, claim, delta=-5000, reason="partial")
        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 15000
        assert host_after["fees_receivable_balance_cents"] == 1200

    def test_fee_receivables_cleared_exactly_by_disbursement(self, api: ApiClient):
        """PRD §3.8: "under the `NET` variant this clears the creditor plan's receivables by subtracting the batch's `fees_total_cents` from the creditor's `fees_receivable_balance_cents`, while the creditor's `claims_paid_balance_cents` is unchanged"

        Design: Difficulty/compensating_invariant/fee_receivables_cleared_exactly_by_disbursement
        """
        world = setup_paid_claim_world(api)
        batch = create_finalized_batch(api, world)
        get_success_data(api.acknowledge_batch(batch["id"], world["home_headers"]))

        host_before = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_before["fees_receivable_balance_cents"] == 1200

        disbursed = validate_success(api.disburse_batch(batch["id"], ASSOCIATION_ADMIN_HEADERS), 200)
        assert disbursed["fees_total_cents"] == 1200

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["fees_receivable_balance_cents"] == 0
        assert host_after["claims_paid_balance_cents"] == 20000

    def test_gross_disbursement_does_not_clear_receivables(self, api: ApiClient):
        """PRD §3.8: "under the `GROSS` variant no receivables are cleared at disbursement, since fees settle separately."

        Design: Difficulty/compensating_invariant/fee_receivables_cleared_exactly_by_disbursement
        """
        world = setup_paid_claim_world(api)
        batch = create_finalized_batch(api, world, settlement_variant="GROSS")
        get_success_data(api.acknowledge_batch(batch["id"], world["home_headers"]))
        validate_success(api.disburse_batch(batch["id"], ASSOCIATION_ADMIN_HEADERS), 200)

        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["fees_receivable_balance_cents"] == 1200
        assert host_after["claims_paid_balance_cents"] == 20000
