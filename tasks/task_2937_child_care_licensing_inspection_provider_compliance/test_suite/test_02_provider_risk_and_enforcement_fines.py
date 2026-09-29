"""The provider risk assessment and the frozen enforcement fine (PRD §3.5, §3.8).

Two arithmetic contracts live here.  The risk read has two weightings that
disagree on the *tier*, not merely on the number, and only one of them is ever
persisted.  The fine derives its pricing tier exactly once, from the gross, and
that single tier supplies both the surcharge and the credit percentage.
"""

from test_helpers import (
    CODE_FACILITY,
    CODE_NUTRITION,
    CODE_RATIO,
    CODE_SUPERVISION_PLAN,
    DEFAULT_LOGICAL_CLOCK,
    assert_cents,
    assert_point_ledger,
    assert_points,
    assert_risk,
    assert_risk_assessment,
    assert_score,
    fixtures as fx,
    intake_headers,
    supervisor_headers,
    validate_paginated,
    validate_success,
)

ALL_AGE_GROUPS = ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]


def _provider_with_ten_open_points(api, catalog):
    """Ten open points, one substantiated and one inconclusive complaint.

    Ada works the complaint visit; Ben investigates, because §3.7 bars an
    inspector who finalized a visit of that provider inside twelve months from
    taking its casework.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=ALL_AGE_GROUPS,
        max_daily_visits=3,
    )
    ben = fx.register_inspector(
        api,
        full_name="Ben Investigator",
        certified_age_groups=ALL_AGE_GROUPS,
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Cedar Lane Center",
        site_address="40 Cedar Ln",
        program_type="CENTER",
        requested_capacity=60,
    )
    substantiated = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="WEB",
        allegation_category="RECORDS",
        affected_age_group="PRESCHOOL",
        narrative="Immunisation records missing for several preschoolers.",
        alleged_serious_harm=False,
        anonymous=False,
        complainant_name="R. Parent",
    )
    fx.screen_complaint(api, substantiated["id"], "SCREEN_IN")

    visit = fx.run_visit(
        api,
        provider["id"],
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
        complaint_id=substantiated["id"],
        catalog=catalog,
        citations=[
            {
                "code": CODE_RATIO,
                "primary_age_group": "PRESCHOOL",
                "narrative": "Preschool room at one adult to fourteen children.",
            },
            {
                "code": CODE_NUTRITION,
                "primary_age_group": "PRESCHOOL",
                "narrative": "Weekly menu not posted.",
            },
        ],
        outcome="CONDITIONAL_PASS",
    )

    fx.assign_investigator(api, substantiated["id"], ben["id"])
    fx.record_determination(api, substantiated["id"], ben["id"], "SUBSTANTIATED")

    inconclusive = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="MAIL",
        allegation_category="RECORDS",
        affected_age_group="PRESCHOOL",
        narrative="Anonymous letter alleging incomplete attendance logs.",
        alleged_serious_harm=False,
        anonymous=True,
    )
    fx.screen_complaint(api, inconclusive["id"], "SCREEN_IN")
    fx.assign_investigator(api, inconclusive["id"], ben["id"])
    fx.record_determination(api, inconclusive["id"], ben["id"], "INCONCLUSIVE")

    return {
        "provider_id": provider["id"],
        "inspection": visit["inspection"],
        "substantiated_id": substantiated["id"],
        "inconclusive_id": inconclusive["id"],
        "ada": ada,
        "ben": ben,
    }


class TestProviderRiskIntakeVersusEnforcementReview:
    """§3.5: "The two risk variants differ in exactly one weight." """

    def test_the_two_variants_disagree_on_the_tier_not_only_the_number(
        self, api, catalog
    ):
        """Ten open points, one substantiated and one inconclusive complaint read
        18.00/LOW under intake screening and 22.00/MODERATE under enforcement
        review, and the gap is exactly the inconclusive weight.

        PRD §3.5: "Under **intake screening**, inconclusive complaints are
        weighted **0**: unproven allegations are given no weight at all, so that
        unsubstantiated reports cannot inflate a provider's public risk profile.
        Under **enforcement review**, each inconclusive complaint is weighted
        **4**."

        Design: Difficulty/dual_variant_calc/dual_variant_provider_risk_intake_vs_enforcement
        """
        ctx = _provider_with_ten_open_points(api, catalog)
        provider = validate_success(api.get_provider(ctx["provider_id"], headers=supervisor_headers()))

        assert_point_ledger(provider, 10, 0, 10)
        assert provider["substantiated_complaint_count_24mo"] == 1
        assert provider["inconclusive_complaint_count_24mo"] == 1
        assert provider["critical_violation_count_24mo"] == 0
        assert provider["license_status"] == "NONE"

        intake = validate_success(
            api.get_risk_assessment(
                ctx["provider_id"],
                variant="INTAKE_SCREENING",
                headers=intake_headers(),
            )
        )
        enforcement = validate_success(
            api.get_risk_assessment(
                ctx["provider_id"],
                variant="ENFORCEMENT_REVIEW",
                headers=supervisor_headers(),
            )
        )

        assert_risk_assessment(
            intake,
            "INTAKE_SCREENING",
            18.00,
            "LOW",
            open_violation_points=10,
            substantiated_complaint_count_24mo=1,
            inconclusive_complaint_count_24mo=1,
            critical_violation_count_24mo=0,
        )
        assert_risk_assessment(
            enforcement,
            "ENFORCEMENT_REVIEW",
            22.00,
            "MODERATE",
            open_violation_points=10,
            substantiated_complaint_count_24mo=1,
            inconclusive_complaint_count_24mo=1,
            critical_violation_count_24mo=0,
        )

        gap = round(enforcement["risk_score"] - intake["risk_score"], 2)
        assert_score(gap, 4.00, "enforcement minus intake risk_score")
        assert intake["risk_tier"] != enforcement["risk_tier"], (
            "18.00 bands LOW and 22.00 bands MODERATE, so the two variants must "
            "disagree on the tier as well as the number"
        )

    def test_only_the_enforcement_review_variant_is_persisted_on_the_provider(
        self, api, catalog
    ):
        """The stored risk_score/risk_tier pair is the enforcement-review answer,
        never the intake-screening one.

        PRD §3.5: "The enforcement-review variant is the one used whenever the
        ladder is evaluated and is the **only** variant ever persisted into
        `risk_score` and `risk_tier`; the intake-screening variant is used when a
        complaint is screened and when a public-facing tier is displayed, and is
        never written to the provider row."

        Design: Difficulty/dual_variant_calc/dual_variant_provider_risk_intake_vs_enforcement
        """
        ctx = _provider_with_ten_open_points(api, catalog)

        provider = validate_success(api.get_provider(ctx["provider_id"], headers=supervisor_headers()))
        assert_risk(provider, 22.00, "MODERATE")

        intake = validate_success(
            api.get_risk_assessment(
                ctx["provider_id"],
                variant="INTAKE_SCREENING",
                headers=intake_headers(),
            )
        )
        assert_score(intake["risk_score"], 18.00, "intake risk_score")

        after = validate_success(api.get_provider(ctx["provider_id"], headers=supervisor_headers()))
        assert_risk(after, 22.00, "MODERATE")
        assert after["version"] == provider["version"], (
            "a risk read recomputes on demand and must not write the provider row"
        )

    def test_the_cascade_stops_below_the_probation_threshold(self, api, catalog):
        """Ten recomputed points are below 30, so link four of the substantiated
        cascade never fires and no enforcement action exists.

        PRD §3.7: "when the provider's new `open_violation_points` is at least 30
        **and** the provider's `current_ladder_step` is strictly below 2, one
        enforcement action is auto-created in `PROPOSED` ... If the points stay
        below 30, or the provider is already at ladder step 2 or higher, the chain
        stops after link three and no action is created."

        Design: Difficulty/dual_variant_calc/dual_variant_provider_risk_intake_vs_enforcement
        """
        ctx = _provider_with_ten_open_points(api, catalog)

        actions, _meta = validate_paginated(
            api.list_enforcement_actions(
                provider_id=ctx["provider_id"], headers=supervisor_headers()
            )
        )
        assert actions == [], (
            "open_violation_points 10 is below the 30-point probation threshold, "
            f"so the cascade must create no action; got {actions!r}"
        )

        provider = validate_success(api.get_provider(ctx["provider_id"], headers=supervisor_headers()))
        assert provider["current_ladder_step"] == 0
        assert provider["probation_cycle_count"] == 0


def _two_providers_with_finalized_points(api, catalog):
    """Provider ONE carries 15+15+8+8+4 = 50 open points, provider TWO a single
    15-point critical finding.

    Both complaint visits are finalized, because §3.5 restricts every provider
    point counter to violations "whose owning inspection is `FINALIZED`" and the
    proposal reads those counters.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    one = fx.create_provider(
        api,
        legal_name="Provider One Center",
        site_address="1 First St",
        program_type="CENTER",
        requested_capacity=60,
    )
    two = fx.create_provider(
        api,
        legal_name="Provider Two Center",
        site_address="2 Second St",
        program_type="CENTER",
        requested_capacity=60,
    )
    complaint_one = fx.intake_complaint(
        api,
        one["id"],
        intake_channel="PHONE",
        allegation_category="RATIO",
        affected_age_group="PRESCHOOL",
        narrative="Repeated ratio complaints at the preschool rooms.",
        anonymous=True,
    )
    complaint_two = fx.intake_complaint(
        api,
        two["id"],
        intake_channel="PHONE",
        allegation_category="RATIO",
        affected_age_group="PRESCHOOL",
        narrative="Single ratio complaint at the preschool room.",
        anonymous=True,
    )

    visit_one = fx.run_visit(
        api,
        one["id"],
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
        complaint_id=complaint_one["id"],
        catalog=catalog,
        citations=[
            {"code": CODE_SUPERVISION_PLAN, "narrative": "No supervision plan for room A."},
            {"code": CODE_SUPERVISION_PLAN, "narrative": "No supervision plan for room B."},
            {"code": CODE_RATIO, "narrative": "Room A over ratio."},
            {"code": CODE_RATIO, "narrative": "Room B over ratio."},
            {"code": CODE_FACILITY, "narrative": "Loose decking board in the yard."},
        ],
        outcome="FAIL",
    )
    visit_two = fx.run_visit(
        api,
        two["id"],
        ada["id"],
        "2026-08-07T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
        complaint_id=complaint_two["id"],
        catalog=catalog,
        citations=[
            {"code": CODE_SUPERVISION_PLAN, "narrative": "No supervision plan on file."}
        ],
        outcome="FAIL",
    )

    return {
        "one_id": one["id"],
        "two_id": two["id"],
        "one_inspection": visit_one["inspection"],
        "two_inspection": visit_two["inspection"],
        "ada": ada,
    }


class TestFineTierDerivedOnceFromTheGross:
    """§3.8: "**The tier is derived exactly once, from the gross, and the same
    tier supplies both percentages**"."""

    def test_suspension_on_fifty_basis_points_is_two_hundred_eighty_seven_thousand_three_hundred_seventy_five(
        self, api, catalog
    ):
        """The 275000 gross tiers second, so the credit is 5 percent of the
        302500 net and the fine is 287375 — not the 257125 a re-tiered net gives.

        PRD §3.8: "A suspension on 50 basis points is worth 150000 plus 125000,
        so 275000 gross, which is the second tier; the surcharge is 27500, the net
        302500, the credit 15125, and the fine 287375. An implementation that
        re-tiered on the 302500 net into the third tier would take a 15 percent
        credit of 45375 and return 257125, which is incorrect."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_fine_tier_derived_once_from_gross
        """
        ctx = _two_providers_with_finalized_points(api, catalog)
        provider = validate_success(
            api.get_provider(ctx["one_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 50, 0, 50)

        action = fx.propose_action(
            api,
            ctx["one_id"],
            "SUSPENSION",
            rationale="Fifty open violation points across supervision and ratio.",
        )

        assert action["action_type"] == "SUSPENSION"
        assert action["ladder_step"] == 3
        assert_points(action["basis_points"], 50, "basis_points")
        assert_cents(action["fine_amount_cents"], 287375)
        assert action["fine_amount_cents"] != 257125, (
            "257125 is the answer produced by re-deriving the pricing tier from "
            "the 302500 net after the surcharge, which the PRD calls incorrect"
        )
        assert action["status"] == "PROPOSED"
        assert action["issued_at"] is None
        assert action["effective_at"] is None
        assert action["appeal_deadline_at"] is None
        assert action["issued_by_user_id"] is None
        assert action["capacity_held_slots"] == 0

    def test_warning_on_fifteen_basis_points_takes_no_surcharge_and_no_credit(
        self, api, catalog
    ):
        """A 37500 gross sits in the first tier, where both percentages are zero,
        so the fine equals the gross exactly.

        PRD §3.8: "A warning on 15 basis points grosses 37500, sits in the first
        tier, takes no surcharge and no credit, and its fine is 37500 cents."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_fine_tier_derived_once_from_gross
        """
        ctx = _two_providers_with_finalized_points(api, catalog)
        provider = validate_success(
            api.get_provider(ctx["two_id"], headers=supervisor_headers())
        )
        assert_point_ledger(provider, 15, 0, 15)

        action = fx.propose_action(
            api,
            ctx["two_id"],
            "WARNING",
            rationale="Single critical supervision-plan finding.",
        )

        assert action["action_type"] == "WARNING"
        assert action["ladder_step"] == 1
        assert_points(action["basis_points"], 15, "basis_points")
        assert_cents(action["fine_amount_cents"], 37500)
        assert action["status"] == "PROPOSED"

    def test_each_provider_carries_its_own_tiered_fine(self, api, catalog):
        """Both proposals coexist and each keeps the fine derived from its own
        gross; the ladder rung follows the points, not the other provider.

        PRD §3.8: "Begin with the gross amount: the base for the action type — 0
        cents for a warning, 50000 for probation, 150000 for suspension, 500000
        for revocation — plus 2500 cents for each of the frozen `basis_points`."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_fine_tier_derived_once_from_gross
        """
        ctx = _two_providers_with_finalized_points(api, catalog)
        suspension = fx.propose_action(api, ctx["one_id"], "SUSPENSION")
        warning = fx.propose_action(api, ctx["two_id"], "WARNING")

        for provider_id, expected in (
            (ctx["one_id"], suspension["id"]),
            (ctx["two_id"], warning["id"]),
        ):
            rows, _meta = validate_paginated(
                api.list_enforcement_actions(
                    provider_id=provider_id, headers=supervisor_headers()
                )
            )
            assert [row["id"] for row in rows] == [expected], (
                f"provider {provider_id} must carry exactly one proposed action"
            )

        assert_cents(
            validate_success(
                api.get_enforcement_action(
                    suspension["id"], headers=supervisor_headers()
                )
            )["fine_amount_cents"],
            287375,
        )
        assert_cents(
            validate_success(
                api.get_enforcement_action(warning["id"], headers=supervisor_headers())
            )["fine_amount_cents"],
            37500,
        )
