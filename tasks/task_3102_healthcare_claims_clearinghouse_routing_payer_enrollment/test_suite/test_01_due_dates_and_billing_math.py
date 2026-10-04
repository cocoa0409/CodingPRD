"""Depth tests: dual-variant due dates and tiered/rounded billing math."""

from test_helpers import (
    ApiClient,
    assert_instants_equal,
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    create_pricing_tier,
    create_usage_invoice,
    enroll_and_approve,
    finalize_invoice,
    forward_claim,
    respond_inquiry,
    set_clock,
    setup_claims_pipeline,
    setup_world,
    submit_claim,
    submit_inquiry,
)


class TestEnrollmentDueDateDualVariant:
    def test_enrollment_due_date_business_variant_skips_weekend(self, api: ApiClient):
        """PRD §3.3: "The deadline, `payer_decision_due_at`, is the business-day
        addition of the payer's lead time for that transaction type onto
        `submitted_at`". PRD §2.4: "Adding N business days to an instant means
        stepping forward N days while skipping Saturdays and Sundays; there is
        no holiday calendar."

        Design: Difficulty/dual_variant_calc/enrollment_due_date_business_vs_calendar_diverges_across_weekend
        """
        world = setup_world(
            api,
            clock="2026-09-04T00:00:00Z",  # a Friday
            payer_overrides={
                "claims_lead_time_days": 3,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
            },
        )
        admin = world.admin_headers()
        resp = api.create_enrollment(
            world.provider_id,
            {"payer_id": world.payer_id, "transaction_type": "CLAIMS_837"},
            admin,
        )
        enrollment = get_success_data(resp)

        resp = api.submit_enrollment(world.provider_id, enrollment["id"], admin)
        submitted = validate_success(resp)

        # Friday 2026-09-04 + 3 business days skips Sat 9/5 and Sun 9/6,
        # landing on Wednesday 2026-09-09.
        assert_instants_equal(
            submitted["payer_decision_due_at"],
            "2026-09-09T00:00:00Z",
            "payer_decision_due_at",
        )

    def test_enrollment_due_date_calendar_variant_differs_across_weekend(self, api: ApiClient):
        """PRD §3.3: "Alongside the business-day value the response also
        surfaces `payer_decision_due_at_calendar`, the naive calendar-day
        addition, for transparency; it is never later than the business-day
        value and is strictly earlier whenever the window crosses a weekend."

        Design: Difficulty/dual_variant_calc/enrollment_due_date_business_vs_calendar_diverges_across_weekend
        """
        world = setup_world(
            api,
            clock="2026-09-04T00:00:00Z",  # a Friday
            payer_overrides={
                "claims_lead_time_days": 3,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
            },
        )
        admin = world.admin_headers()
        enrollment = get_success_data(
            api.create_enrollment(
                world.provider_id,
                {"payer_id": world.payer_id, "transaction_type": "CLAIMS_837"},
                admin,
            )
        )

        submitted = validate_success(
            api.submit_enrollment(world.provider_id, enrollment["id"], admin)
        )

        # Friday 2026-09-04 + 3 calendar days lands on Monday 2026-09-07.
        assert_instants_equal(
            submitted["payer_decision_due_at_calendar"],
            "2026-09-07T00:00:00Z",
            "payer_decision_due_at_calendar",
        )
        assert submitted["payer_decision_due_at"] != submitted["payer_decision_due_at_calendar"], (
            "the two variants must produce different timestamps when the window crosses a weekend"
        )


class TestClaimResponseDueDualVariant:
    def test_claim_response_due_business_variant_skips_weekend(self, api: ApiClient):
        """PRD §3.4: "A successful forward stamps `forwarded_at`, computes
        `payer_response_due_at` as the business-day addition of the payer's
        `claims_lead_time_days` onto `forwarded_at`". PRD §2.4: "Adding N
        business days to an instant means stepping forward N days while
        skipping Saturdays and Sundays; there is no holiday calendar."

        Design: Difficulty/dual_variant_calc/claim_response_due_business_vs_calendar_on_remitted_claim
        """
        world = setup_claims_pipeline(
            api,
            clock="2026-09-04T10:00:00Z",  # a Friday
            payer_overrides={
                "claims_lead_time_days": 3,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
            },
        )
        claim = submit_claim(api, world)

        forwarded = forward_claim(api, claim)

        # Friday 2026-09-04 10:00 + 3 business days -> Wednesday 2026-09-09 10:00.
        assert_instants_equal(
            forwarded["payer_response_due_at"],
            "2026-09-09T10:00:00Z",
            "payer_response_due_at",
        )

    def test_claim_response_due_calendar_variant_differs_across_weekend(self, api: ApiClient):
        """PRD §3.4: "computes `payer_response_due_at` as the business-day
        addition of the payer's `claims_lead_time_days` onto `forwarded_at`
        (with the calendar-day sibling `payer_response_due_at_calendar`
        surfaced alongside)".

        Design: Difficulty/dual_variant_calc/claim_response_due_business_vs_calendar_on_remitted_claim
        """
        world = setup_claims_pipeline(
            api,
            clock="2026-09-04T10:00:00Z",  # a Friday
            payer_overrides={
                "claims_lead_time_days": 3,
                "remittance_lead_time_days": 5,
                "eligibility_lead_time_seconds": 60,
            },
        )
        claim = submit_claim(api, world)

        forwarded = forward_claim(api, claim)

        # Friday 2026-09-04 10:00 + 3 calendar days -> Monday 2026-09-07 10:00.
        assert_instants_equal(
            forwarded["payer_response_due_at_calendar"],
            "2026-09-07T10:00:00Z",
            "payer_response_due_at_calendar",
        )
        assert forwarded["payer_response_due_at"] != forwarded["payer_response_due_at_calendar"], (
            "the weekend between Friday and Monday separates the two variants"
        )


class TestMonthlyUsageFeeRoundingOrder:
    def test_shared_payer_fee_rounded_per_kind_before_summing(self, api: ApiClient):
        """PRD §2.9: "Where a calculation produces a fractional intermediate —
        specifically, multiplying a shared-payer fee by `shared_provider_pct` —
        rounding uses round-half-up, applied per (transaction kind, payer) line
        **before** the lines are summed."

        Design: Difficulty/combinatorial_formula/monthly_usage_fee_per_kind_payer_rounding_then_sum
        """
        set_clock(api, "2026-09-01T00:00:00Z")
        world = setup_world(
            api,
            clock="2026-09-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Hybrid Provider LLC",
                "tax_identification_number": "987654321",
                "national_provider_identifier": "1987654328",
                "billing_model": "HYBRID",
            },
            payer_overrides={
                "claims_lead_time_days": 1,
                "remittance_lead_time_days": 1,
                "eligibility_lead_time_seconds": 60,
                "pricing_model": "SHARED",
                "shared_provider_pct": 0.5,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYSH",
        )
        create_pricing_tier(api, world.payer_id, applies_to="CLAIM", volume_floor=1, rate_cents=3)
        create_pricing_tier(api, world.payer_id, applies_to="ELIGIBILITY", volume_floor=1, rate_cents=3)
        enroll_and_approve(api, world, "CLAIMS_837")
        enroll_and_approve(api, world, "ELIGIBILITY_270")

        # One forwarded claim and one responded inquiry in September.
        claim = submit_claim(
            api, world, patient_control_number="PCN-H1", idempotency_key="IDEM-H1"
        )
        forward_claim(api, claim)
        inquiry = submit_inquiry(api, world, subscriber_id="MBR-H1", idempotency_key="IDEM-E1")
        respond_inquiry(api, world, inquiry["id"])

        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")
        set_clock(api, "2026-10-01T00:00:00Z")
        finalized = finalize_invoice(api, invoice)

        # claim fee: 1 unit x 3 cents x 0.5 = 1.5 -> round-half-up -> 2
        # eligibility fee: 1 unit x 3 cents x 0.5 = 1.5 -> round-half-up -> 2
        # gross = 2 + 2 = 4 (sum-then-round would give round_half_up(3.0) = 3)
        assert finalized["gross_fee_cents"] == 4, (
            f"expected 4 cents after per-(kind, payer) rounding, got {finalized['gross_fee_cents']}"
        )
        assert finalized["gross_fee_cents"] != 3, "sum-then-round is non-compliant"
        assert finalized["amount_due_cents"] == 4

    def test_shared_payer_rounding_visible_on_single_kind(self, api: ApiClient):
        """PRD §3.8: "For shared payers the resulting per-kind fee is multiplied
        by `shared_provider_pct` and rounded half-up **at that per-kind,
        per-payer line** before anything is summed. The sum across kinds and
        payers is `gross_fee_cents`."

        Design: Difficulty/combinatorial_formula/monthly_usage_fee_per_kind_payer_rounding_then_sum
        """
        world = setup_world(
            api,
            clock="2026-09-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Single Kind Provider",
                "tax_identification_number": "987654322",
                "national_provider_identifier": "1987654336",
                "billing_model": "HYBRID",
            },
            payer_overrides={
                "claims_lead_time_days": 1,
                "remittance_lead_time_days": 1,
                "eligibility_lead_time_seconds": 60,
                "pricing_model": "SHARED",
                "shared_provider_pct": 0.5,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYS2",
        )
        create_pricing_tier(api, world.payer_id, applies_to="CLAIM", volume_floor=1, rate_cents=3)
        enroll_and_approve(api, world, "CLAIMS_837")

        # Three forwarded claims -> 3 units x 3 cents x 0.5 = 4.5 -> 5.
        for i in range(3):
            claim = submit_claim(
                api,
                world,
                patient_control_number=f"PCN-S{i}",
                idempotency_key=f"IDEM-S{i}",
            )
            forward_claim(api, claim)

        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")
        set_clock(api, "2026-10-01T00:00:00Z")
        finalized = finalize_invoice(api, invoice)

        assert finalized["gross_fee_cents"] == 5, (
            f"expected 5 cents (4.5 rounded half-up), got {finalized['gross_fee_cents']}"
        )
        assert finalized["amount_due_cents"] == 5


class TestTieredPricingMarginalRate:
    def test_units_straddling_tier_floor_pay_marginal_rates(self, api: ApiClient):
        """PRD §3.8: "the system takes the unit count attributable to
        provider-funded and shared payers, then walks that payer's pricing
        tiers for the kind in ascending `volume_floor` order: each tier
        overlapping the month's volume contributes its covered unit count —
        from the tier's `volume_floor` through the smaller of the month's total
        units and the tier's `volume_ceiling` (or the month's total when the
        ceiling is absent), inclusive at both ends — multiplied by its
        `rate_cents`."

        Design: Difficulty/combinatorial_formula/tiered_pricing_straddles_volume_floor_with_marginal_rate
        """
        world = setup_claims_pipeline(
            api,
            clock="2026-09-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Tiered Provider",
                "tax_identification_number": "555555555",
                "national_provider_identifier": "1555555550",
            },
            payer_overrides={
                "claims_lead_time_days": 1,
                "remittance_lead_time_days": 1,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYTB",
        )
        create_pricing_tier(
            api, world.payer_id, applies_to="CLAIM", volume_floor=1, volume_ceiling=10, rate_cents=100
        )
        create_pricing_tier(
            api, world.payer_id, applies_to="CLAIM", volume_floor=11, rate_cents=50
        )

        # Forward exactly 12 claims in September.
        for i in range(12):
            claim = submit_claim(
                api,
                world,
                patient_control_number=f"PCN-T{i:02d}",
                idempotency_key=f"IDEM-T{i:02d}",
                service_date="2026-09-02T00:00:00Z",
            )
            forward_claim(api, claim)

        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")
        set_clock(api, "2026-10-01T00:00:00Z")
        finalized = finalize_invoice(api, invoice)

        # 10 units x 100c (tier 1) + 2 units x 50c (tier 2) = 1100 cents.
        assert finalized["claim_units"] == 12
        assert finalized["gross_fee_cents"] == 1100, (
            f"expected marginal-rate total of 1100, got {finalized['gross_fee_cents']}"
        )
        assert finalized["gross_fee_cents"] != 750, "average-rate application is observably wrong"
        assert finalized["gross_fee_cents"] != 600, "flat-tier-2 application is observably wrong"

    def test_units_within_first_tier_pay_only_tier_one_rate(self, api: ApiClient):
        """PRD §3.8: "each tier overlapping the month's volume contributes its
        covered unit count — from the tier's `volume_floor` through the smaller
        of the month's total units and the tier's `volume_ceiling` (or the
        month's total when the ceiling is absent), inclusive at both ends —
        multiplied by its `rate_cents`."

        Design: Difficulty/combinatorial_formula/tiered_pricing_straddles_volume_floor_with_marginal_rate
        """
        world = setup_claims_pipeline(
            api,
            clock="2026-09-01T00:00:00Z",
            provider_overrides={
                "legal_name": "Single Tier Provider",
                "tax_identification_number": "555555556",
                "national_provider_identifier": "1555555568",
            },
            payer_overrides={
                "claims_lead_time_days": 1,
                "remittance_lead_time_days": 1,
                "eligibility_lead_time_seconds": 60,
                "monthly_minimum_cents": 0,
            },
            payer_code="PAYT1",
        )
        create_pricing_tier(
            api, world.payer_id, applies_to="CLAIM", volume_floor=1, volume_ceiling=10, rate_cents=100
        )
        create_pricing_tier(api, world.payer_id, applies_to="CLAIM", volume_floor=11, rate_cents=50)

        # Exactly 10 forwarded claims: the entire volume lands in tier 1.
        for i in range(10):
            claim = submit_claim(
                api,
                world,
                patient_control_number=f"PCN-U{i:02d}",
                idempotency_key=f"IDEM-U{i:02d}",
                service_date="2026-09-02T00:00:00Z",
            )
            forward_claim(api, claim)

        invoice = create_usage_invoice(api, world.provider_id, period="2026-09")
        set_clock(api, "2026-10-01T00:00:00Z")
        finalized = finalize_invoice(api, invoice)

        # 10 units x 100c = 1000 cents; tier 2 contributes nothing.
        assert finalized["claim_units"] == 10
        assert finalized["gross_fee_cents"] == 1000, (
            f"expected 1000 cents from tier 1 only, got {finalized['gross_fee_cents']}"
        )
