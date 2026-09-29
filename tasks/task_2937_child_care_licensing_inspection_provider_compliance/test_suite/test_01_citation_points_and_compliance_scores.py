"""Point assessment and the two compliance scores (PRD §3.5).

Every test in this file pins one of the normative arithmetic orders of §3.5:
aggravate -> multiply -> round -> cap for a single citation's points, and
round-each-line-then-sum for an inspection's raw deduction.
"""

import pytest

from test_helpers import (
    CODE_FACILITY,
    CODE_NUTRITION,
    CODE_RATIO,
    CODE_SUPERVISION,
    CODE_SUPERVISION_PLAN,
    assert_compliance_score_read,
    assert_point_ledger,
    assert_points,
    assert_score,
    fixtures as fx,
    validate_success,
)

ALL_AGE_GROUPS = ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]


def _complaint_visit_in_progress(api, catalog, *, target_age_groups):
    """A CENTER provider with a screened-in-free complaint and an IN_PROGRESS
    COMPLAINT visit, which is the cheapest state in which citations are legal."""
    inspector = fx.register_inspector(api, certified_age_groups=ALL_AGE_GROUPS)
    provider = fx.create_provider(
        api, legal_name="Maple Court Center", requested_capacity=60
    )
    complaint = fx.intake_complaint(
        api,
        provider["id"],
        intake_channel="PHONE",
        allegation_category="SUPERVISION",
        affected_age_group="INFANT",
        alleged_serious_harm=True,
        anonymous=True,
    )
    inspection = fx.schedule_visit(
        api,
        provider["id"],
        inspector["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="COMPLAINT",
        target_age_groups=target_age_groups,
        duration_minutes=120,
        complaint_id=complaint["id"],
    )
    fx.start_visit(api, inspection["id"], inspector["id"])
    return provider, inspector, inspection


class TestSingleCitationPointArithmetic:
    """§3.5: "`assessed_points` is then computed once and **frozen at
    creation**"."""

    def test_infant_aggravation_rounds_a_half_upward(self, api, catalog):
        """A critical infant citation goes 15 -> 22.5 -> 23, and a minor infant
        citation goes 1 -> 1.5 -> 2 rather than down to 1.

        PRD §3.5: "a critical infant-exposed first citation goes 15, then 22.5,
        then 22.5, then rounds to 23; ... a minor infant-exposed citation goes 1,
        then 1.5, and rounds **up** to 2, not down to 1"

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_violation_points_nested_branch_and_cap
        """
        _, inspector, inspection = _complaint_visit_in_progress(
            api, catalog, target_age_groups=["INFANT", "TODDLER", "PRESCHOOL"]
        )

        critical_infant = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="INFANT",
            narrative="Infant room unattended.",
        )
        minor_infant = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_NUTRITION],
            primary_age_group="INFANT",
            narrative="Bottle log not maintained in the infant room.",
        )

        assert_points(critical_infant["assessed_points"], 23, "assessed_points")
        assert critical_infant["infant_exposure"] is True
        assert critical_infant["severity"] == "CRITICAL"
        assert critical_infant["status"] == "CITED"
        assert critical_infant["auto_generated"] is False
        assert critical_infant["correction_due_date"] is None
        assert critical_infant["corrected_at"] is None
        assert critical_infant["vacated_reason"] is None

        assert_points(minor_infant["assessed_points"], 2, "assessed_points")
        assert minor_infant["infant_exposure"] is True
        assert minor_infant["severity"] == "MINOR"

    def test_non_infant_critical_citation_is_not_aggravated(self, api, catalog):
        """SU-102 is not infant_sensitive and the room is PRESCHOOL, so the
        citation stays at its 15 base points with infant_exposure false.

        PRD §3.5: "a critical citation with no infant exposure stays 15"

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_violation_points_nested_branch_and_cap
        """
        _, inspector, inspection = _complaint_visit_in_progress(
            api, catalog, target_age_groups=["INFANT", "TODDLER", "PRESCHOOL"]
        )

        violation = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION_PLAN],
            primary_age_group="PRESCHOOL",
            narrative="No written supervision plan for the preschool room.",
        )

        assert_points(violation["assessed_points"], 15, "assessed_points")
        assert violation["infant_exposure"] is False
        assert violation["severity"] == "CRITICAL"
        assert violation["repeat_chain_depth"] == 0

    def test_severity_override_replaces_the_catalog_default_before_scoring(
        self, api, catalog
    ):
        """A MINOR catalog row cited with a CRITICAL override scores 15, because
        the override is the effective severity every downstream rule reads.

        PRD §3.5: "The `severity` actually recorded on the citation is the
        `severity_override` when one is supplied and the checklist item's
        `default_severity` otherwise; this is the *effective severity*, and every
        downstream rule — points, correction deadline, critical counting, outcome
        agreement — reads it rather than the catalog default."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_violation_points_nested_branch_and_cap
        """
        _, inspector, inspection = _complaint_visit_in_progress(
            api, catalog, target_age_groups=["INFANT", "TODDLER", "PRESCHOOL"]
        )

        violation = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_NUTRITION],
            primary_age_group="PRESCHOOL",
            narrative="Allergy plan absent; escalated by the inspector.",
            severity_override="CRITICAL",
        )

        assert violation["severity"] == "CRITICAL"
        assert_points(violation["assessed_points"], 15, "assessed_points")
        assert violation["infant_exposure"] is False


class TestRepeatChainAndPointCap:
    """§3.5: the repeat multiplier is applied before the round and before the
    30-point cap."""

    def test_repeat_chain_multiplier_saturates_at_depth_two(self, api, catalog):
        """A MODERATE finding repeated twice scores 4, 8 and 12 at depths 0, 1
        and 2.

        PRD §3.5: "Multiply the result by the repeat multiplier for the chain
        depth: 1.0 at depth 0, 2.0 at depth 1, 3.0 at depth 2."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_violation_points_nested_branch_and_cap
        """
        _, inspector, inspection = _complaint_visit_in_progress(
            api, catalog, target_age_groups=["INFANT", "TODDLER", "PRESCHOOL"]
        )

        first = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Loose decking board in the preschool yard.",
        )
        second = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Second decking board loose at the same location.",
            repeat_of_violation_id=first["id"],
        )
        third = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Third decking board loose at the same location.",
            repeat_of_violation_id=second["id"],
        )

        assert first["repeat_chain_depth"] == 0
        assert_points(first["assessed_points"], 4, "assessed_points")
        assert second["repeat_chain_depth"] == 1
        assert_points(second["assessed_points"], 8, "assessed_points")
        assert third["repeat_chain_depth"] == 2
        assert_points(third["assessed_points"], 12, "assessed_points")

    def test_cap_is_applied_after_the_repeat_multiplier(self, api, catalog):
        """A critical infant repeat at depth 1 goes 15 -> 22.5 -> 45 and is
        capped to 30; capping before the multiplier would return 23.

        PRD §3.5: "and a critical infant-exposed repeat at depth 1 goes 15, then
        22.5, then 45, and is capped to 30."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_violation_points_nested_branch_and_cap
        """
        _, inspector, inspection = _complaint_visit_in_progress(
            api, catalog, target_age_groups=["INFANT", "TODDLER", "PRESCHOOL"]
        )

        parent = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="INFANT",
            narrative="Infant room unattended.",
        )
        repeat = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="INFANT",
            narrative="Infant room unattended a second time during the same visit.",
            repeat_of_violation_id=parent["id"],
        )

        assert repeat["repeat_chain_depth"] == 1
        assert_points(repeat["assessed_points"], 30, "assessed_points")
        assert repeat["assessed_points"] != 45, "the 30-point cap was not applied"
        assert repeat["assessed_points"] != 23, "the cap was applied before the multiplier"

    def test_points_land_on_the_provider_only_when_the_visit_finalizes(
        self, api, catalog
    ):
        """The provider's counters read finalized inspections only, so the eight
        citations contribute nothing until finalization and 109 points after it.

        PRD §3.5: "Because all four counters read only finalized inspections, a
        citation recorded during a visit that has not yet been finalized
        contributes nothing to the provider's totals; finalization is the moment
        the points land."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_violation_points_nested_branch_and_cap
        """
        provider, inspector, inspection = _complaint_visit_in_progress(
            api, catalog, target_age_groups=["INFANT", "TODDLER", "PRESCHOOL"]
        )
        first_facility = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Loose decking board in the preschool yard.",
        )
        second_facility = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Second decking board loose at the same location.",
            repeat_of_violation_id=first_facility["id"],
        )
        fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Third decking board loose at the same location.",
            repeat_of_violation_id=second_facility["id"],
        )
        infant_supervision = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="INFANT",
            narrative="Infant room unattended.",
        )
        fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="INFANT",
            narrative="Infant room unattended a second time during the same visit.",
            repeat_of_violation_id=infant_supervision["id"],
        )
        fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION_PLAN],
            primary_age_group="PRESCHOOL",
            narrative="No written supervision plan for the preschool room.",
        )
        fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_NUTRITION],
            primary_age_group="INFANT",
            narrative="Bottle log not maintained in the infant room.",
        )
        fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_NUTRITION],
            primary_age_group="PRESCHOOL",
            narrative="Allergy plan absent; escalated by the inspector.",
            severity_override="CRITICAL",
        )

        before = validate_success(
            api.get_provider(provider["id"], headers=fx.make_applicant_headers(provider["id"]))
        )
        assert_point_ledger(before, 0, 0, 0)

        fx.submit_findings(
            api,
            inspection["id"],
            inspector["id"],
            "FAIL",
            ["INFANT", "TODDLER", "PRESCHOOL"],
        )
        fx.finalize_visit(api, inspection["id"])

        after = validate_success(
            api.get_provider(provider["id"], headers=fx.make_applicant_headers(provider["id"]))
        )
        # 4 + 8 + 12 + 23 + 30 + 15 + 2 + 15
        assert_point_ledger(after, 109, 0, 109)
        assert after["critical_open_count"] == 4


class TestRawDeductionRoundsEachLineThenSums:
    """§3.5: "**The rounding mode is normative: round each line, then sum.**"""

    @staticmethod
    def _finalized_three_line_visit(api, catalog):
        """Two SU-101/INFANT citations (23 each) plus one RA-201/TODDLER (8),
        submitted FAIL and finalized."""
        inspector = fx.register_inspector(api, certified_age_groups=ALL_AGE_GROUPS)
        provider = fx.create_provider(
            api, legal_name="Willow Bend Center", requested_capacity=60
        )
        complaint = fx.intake_complaint(
            api,
            provider["id"],
            intake_channel="MANDATED_REPORTER",
            allegation_category="SUPERVISION",
            affected_age_group="INFANT",
            alleged_serious_harm=True,
            anonymous=False,
            complainant_name="N. Nurse",
        )
        result = fx.run_visit(
            api,
            provider["id"],
            inspector["id"],
            "2026-08-05T09:00:00Z",
            inspection_type="COMPLAINT",
            target_age_groups=["INFANT", "TODDLER"],
            age_groups_observed=["INFANT", "TODDLER"],
            duration_minutes=120,
            complaint_id=complaint["id"],
            catalog=catalog,
            citations=[
                {
                    "code": CODE_SUPERVISION,
                    "primary_age_group": "INFANT",
                    "narrative": "Infant room unattended at 09:20.",
                },
                {
                    "code": CODE_SUPERVISION,
                    "primary_age_group": "INFANT",
                    "narrative": "Infant room unattended again at 10:05.",
                },
                {
                    "code": CODE_RATIO,
                    "primary_age_group": "TODDLER",
                    "narrative": "Toddler room over ratio for twenty minutes.",
                },
            ],
            outcome="FAIL",
        )
        return provider, inspector, result

    def test_stored_raw_deduction_is_the_sum_of_rounded_lines(self, api, catalog):
        """Lines 30.71, 30.71 and 9.20 sum to 70.62 for a score of 29.38; the
        sum-then-round answer 70.61 / 29.39 must not appear.

        PRD §3.5: "`raw_deduction_points` is the sum of those already-rounded line
        deductions, itself rounded to two decimals. The score is 100 minus the raw
        deduction, floored at 0, rounded to two decimals."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_compliance_score_round_per_line_then_sum
        """
        _, _, result = self._finalized_three_line_visit(api, catalog)
        inspection = result["inspection"]
        points = [v["assessed_points"] for v in result["violations"]]

        assert points == [23, 23, 8], f"unexpected per-line points {points}"
        assert_score(inspection["raw_deduction_points"], 70.62, "raw_deduction_points")
        assert_score(
            inspection["final_compliance_score"], 29.38, "final_compliance_score"
        )
        assert_score(
            inspection["preliminary_compliance_score"],
            29.38,
            "preliminary_compliance_score",
        )
        assert float(inspection["raw_deduction_points"]) != pytest.approx(
            70.61, abs=1e-9
        ), "raw deduction was summed before rounding"
        assert inspection["violation_count"] == 3
        assert inspection["cap_required"] is True

    def test_live_score_read_agrees_with_the_stored_fields(self, api, catalog):
        """The compliance-score read recomputes from current data and, with no
        disposition yet recorded, returns the same 70.62 / 29.38.

        PRD §3.5: "Both variants are also computable live for any inspection
        through a scoring read that takes an optional `variant` selector naming
        either the preliminary or the final view."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_compliance_score_round_per_line_then_sum
        """
        _, _, result = self._finalized_three_line_visit(api, catalog)
        inspection_id = result["inspection"]["id"]

        final = validate_success(
            api.get_compliance_score(
                inspection_id, "FINAL", headers=fx.supervisor_headers()
            )
        )
        assert_compliance_score_read(
            final, "FINAL", 29.38, raw_deduction=70.62, violation_count=3
        )

        preliminary = validate_success(
            api.get_compliance_score(
                inspection_id, "PRELIMINARY", headers=fx.supervisor_headers()
            )
        )
        assert_compliance_score_read(preliminary, "PRELIMINARY", 29.38, raw_deduction=70.62)


class TestPreliminaryVersusFinalComplianceScore:
    """§3.5: the same arithmetic over two different input sets."""

    @staticmethod
    def _five_line_initial_visit(api, catalog):
        """A CHECKS_CLEARED CENTER provider with a finalized INITIAL visit
        carrying the five citations of the §3.5 worked example."""
        inspector = fx.register_inspector(api, certified_age_groups=ALL_AGE_GROUPS)
        ctx = fx.setup_provider_dossier(
            api,
            legal_name="Bright Start Center",
            requested_capacity=60,
            rooms=[
                {"age_group": "INFANT", "requested_group_size": 8},
                {"age_group": "TODDLER", "requested_group_size": 12},
                {"age_group": "PRESCHOOL", "requested_group_size": 20},
                {"age_group": "SCHOOL_AGE", "requested_group_size": 20},
            ],
            catalog=catalog,
            seed_checklist=False,
        )
        fx.advance_to_checks_cleared(ctx)

        inspection = fx.schedule_visit(
            api,
            ctx.id,
            inspector["id"],
            "2026-08-05T09:00:00Z",
            inspection_type="INITIAL",
            target_age_groups=["INFANT", "TODDLER", "PRESCHOOL"],
            duration_minutes=120,
        )
        fx.start_visit(api, inspection["id"], inspector["id"])
        facility = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Gate latch to the preschool yard broken.",
        )
        infant_one = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="INFANT",
            narrative="Infant room unattended for four minutes.",
        )
        infant_two = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="INFANT",
            narrative="Second infant room unattended during nap transition.",
        )
        ratio = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_RATIO],
            primary_age_group="TODDLER",
            narrative="Toddler room at one adult to eight children.",
        )
        facility_repeat = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_FACILITY],
            primary_age_group="PRESCHOOL",
            narrative="Same gate latch still broken at re-walk.",
            repeat_of_violation_id=facility["id"],
        )
        fx.submit_findings(
            api,
            inspection["id"],
            inspector["id"],
            "FAIL",
            ["INFANT", "TODDLER", "PRESCHOOL"],
        )
        inspection = fx.finalize_visit(api, inspection["id"])
        return {
            "ctx": ctx,
            "inspector": inspector,
            "inspection": inspection,
            "facility": facility,
            "infant_one": infant_one,
            "infant_two": infant_two,
            "ratio": ratio,
            "facility_repeat": facility_repeat,
        }

    def test_both_scores_agree_at_finalization(self, api, catalog):
        """With every citation in CORRECTION_PENDING both variants see factor
        1.000, so 82.62 raw points give 17.38 twice over.

        PRD §3.5: "take an inspection finalized with five citations totalling
        82.62 raw points and a stored preliminary score of 17.38"

        Design: Difficulty/dual_variant_calc/dual_variant_inspection_compliance_preliminary_vs_final
        """
        state = self._five_line_initial_visit(api, catalog)
        inspection = state["inspection"]

        assert_points(state["facility"]["assessed_points"], 4, "assessed_points")
        assert_points(state["infant_one"]["assessed_points"], 23, "assessed_points")
        assert_points(state["infant_two"]["assessed_points"], 23, "assessed_points")
        assert_points(state["ratio"]["assessed_points"], 8, "assessed_points")
        assert_points(state["facility_repeat"]["assessed_points"], 8, "assessed_points")
        assert state["facility_repeat"]["repeat_chain_depth"] == 1

        assert_score(inspection["raw_deduction_points"], 82.62, "raw_deduction_points")
        assert_score(
            inspection["preliminary_compliance_score"],
            17.38,
            "preliminary_compliance_score",
        )
        assert_score(
            inspection["final_compliance_score"], 17.38, "final_compliance_score"
        )
        assert float(inspection["raw_deduction_points"]) != pytest.approx(
            82.61, abs=1e-9
        ), "raw deduction was summed before rounding"
        assert inspection["violation_count"] == 5

    def test_dispositions_move_the_final_score_and_freeze_the_preliminary(
        self, api, catalog
    ):
        """After one correction, one non-correction and one vacation the stored
        final score becomes 37.34 while the stored preliminary stays 17.38.

        PRD §3.5: "`preliminary_compliance_score` is stored at finalization and
        frozen there for ever; no disposition, plan completion or cascade ever
        changes the stored value."

        Design: Difficulty/dual_variant_calc/dual_variant_inspection_compliance_preliminary_vs_final
        """
        state = self._five_line_initial_visit(api, catalog)
        inspector_headers = fx.make_inspector_headers(state["inspector"]["id"])

        validate_success(
            api.disposition_violation(
                state["infant_one"]["id"],
                "VERIFIED_CORRECTED",
                headers=inspector_headers,
            )
        )
        validate_success(
            api.disposition_violation(
                state["infant_two"]["id"], "UNCORRECTED", headers=inspector_headers
            )
        )
        validate_success(
            api.disposition_violation(
                state["ratio"]["id"],
                "VACATED",
                vacated_reason=(
                    "Sign-in sheets show the room was compliant; citation withdrawn."
                ),
                headers=fx.supervisor_headers(),
            )
        )

        inspection = validate_success(
            api.get_inspection(state["inspection"]["id"], headers=fx.supervisor_headers())
        )
        assert_score(
            inspection["preliminary_compliance_score"],
            17.38,
            "preliminary_compliance_score",
        )
        assert_score(
            inspection["final_compliance_score"], 37.34, "final_compliance_score"
        )
        assert_score(inspection["raw_deduction_points"], 62.66, "raw_deduction_points")
        assert inspection["violation_count"] == 4

    def test_live_variants_disagree_after_the_dispositions(self, api, catalog):
        """The live final view sums 4.00 + 12.28 + 38.38 + 0.00 + 8.00 = 62.66
        for 37.34, while the live preliminary view drops the vacated row and
        forces factor 1.000 for 73.42 raw and 26.58.

        PRD §3.5: "The live final view now sums 4.00, 12.28, 38.38, 0.00 and 8.00
        to 62.66 raw for a score of 37.34, while the live preliminary view drops
        the vacated row and forces every factor to 1.000, summing 4.00, 30.71,
        30.71 and 8.00 to 73.42 raw for a score of 26.58 — and the stored
        `preliminary_compliance_score` remains 17.38."

        Design: Difficulty/dual_variant_calc/dual_variant_inspection_compliance_preliminary_vs_final
        """
        state = self._five_line_initial_visit(api, catalog)
        inspector_headers = fx.make_inspector_headers(state["inspector"]["id"])
        inspection_id = state["inspection"]["id"]

        validate_success(
            api.disposition_violation(
                state["infant_one"]["id"],
                "VERIFIED_CORRECTED",
                headers=inspector_headers,
            )
        )
        validate_success(
            api.disposition_violation(
                state["infant_two"]["id"], "UNCORRECTED", headers=inspector_headers
            )
        )
        validate_success(
            api.disposition_violation(
                state["ratio"]["id"],
                "VACATED",
                vacated_reason=(
                    "Sign-in sheets show the room was compliant; citation withdrawn."
                ),
                headers=fx.supervisor_headers(),
            )
        )

        final = validate_success(
            api.get_compliance_score(
                inspection_id, "FINAL", headers=fx.supervisor_headers()
            )
        )
        preliminary = validate_success(
            api.get_compliance_score(
                inspection_id, "PRELIMINARY", headers=fx.supervisor_headers()
            )
        )

        assert_compliance_score_read(final, "FINAL", 37.34, raw_deduction=62.66)
        assert_compliance_score_read(
            preliminary, "PRELIMINARY", 26.58, raw_deduction=73.42
        )
        assert float(final["compliance_score"]) - float(
            preliminary["compliance_score"]
        ) == pytest.approx(10.76, abs=0.005)
