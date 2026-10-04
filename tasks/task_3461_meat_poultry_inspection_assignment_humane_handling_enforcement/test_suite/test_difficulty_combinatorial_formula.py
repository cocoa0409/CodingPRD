"""Depth tests: combinatorial formulas with pinned evaluation orders.

Pathogen categorization (minimum-data gate, then tiered rate thresholds), the
compliance score's nested rounding order, and the enforcement priority score's
base-tier-then-bonus evaluation order.
"""

import pytest

from test_helpers import (
    DISTRICT_MANAGER_HEADERS,
    fixtures as fx,
    validate_success,
)


def _granted_poultry_est_with_sampler(api):
    base = fx.create_granted_establishment(api, species_classes=["POULTRY"])
    inspector = fx.create_inspector(api, species_qualifications=["POULTRY"])
    return base["establishment"], inspector


class TestPathogenCategorizationTieredThresholds:
    def test_category_stays_null_below_ten_results_then_tier_fires(self, api):
        """PRD §3.6: "Fewer than 10 resulted samples means that pathogen
        contributes no categorization at all."
        PRD §3.6: "The pathogen is a `CAT_1` candidate when its positive rate
        is at most half the standard rate for that pathogen, a `CAT_2`
        candidate when its rate is at most the standard rate, and a `CAT_3`
        candidate when its rate exceeds the standard rate."

        Design: Difficulty/combinatorial_formula/pathogen_categorization_tiered_thresholds
        """
        est, inspector = _granted_poultry_est_with_sampler(api)
        samples = fx.collect_pathogen_samples(api, est["id"], inspector["id"], "SALMONELLA", 10)
        fx.record_sample_result(api, samples[0]["id"], inspector["id"], "POSITIVE")
        for sample in samples[1:9]:
            fx.record_sample_result(api, sample["id"], inspector["id"], "NEGATIVE")

        mid = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        assert mid["pathogen_category"] is None, (
            f"9 resulted samples is below the minimum of 10: expected null, got {mid['pathogen_category']!r}"
        )

        fx.record_sample_result(api, samples[9]["id"], inspector["id"], "NEGATIVE")

        after = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        # 1/10 == 0.10 is <= the 0.10 standard (not CAT_3) and > 0.05 half-standard (not CAT_1).
        assert after["pathogen_category"] == "CAT_2", (
            f"expected CAT_2 at rate 0.10, got {after['pathogen_category']!r}"
        )

    def test_reaching_cat2_creates_no_enforcement_action(self, api):
        """PRD §3.6: "Whenever a result recording causes any pathogen's
        recomputed category to transition to `CAT_3` from a different value,
        the system automatically creates an enforcement action against the
        establishment in the same request: `action_type`
        `NOTICE_OF_INTENDED_ENFORCEMENT`, `basis` `CATEGORY_3_PATHOGEN`,
        `status` `IN_EFFECT`, `auto_created` true, and `effective_at` stamped
        from the logical clock. A re-computation that lands on `CAT_3` from
        `CAT_3`, or that moves between `CAT_1` and `CAT_2`, creates nothing."

        Design: Difficulty/combinatorial_formula/pathogen_categorization_tiered_thresholds
        """
        est, inspector = _granted_poultry_est_with_sampler(api)
        fx.categorize_pathogen(api, est["id"], inspector["id"], "SALMONELLA", positives=1, negatives=9)

        data = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        assert data["pathogen_category"] == "CAT_2"
        actions = fx.list_enforcement_actions(api, est["id"])
        assert actions == [], f"no enforcement action may be created below CAT_3, got {len(actions)}"


class TestComplianceScoreRoundingOrder:
    def test_per_family_rounding_before_summation_yields_90_1(self, api):
        """PRD §2.10: "The rounding order is pinned: round each family penalty
        to 0.1 first, then subtract the sum of the rounded penalties from 100;
        the result is exact at the 0.1 scale and is not rounded again. The
        non-conformant alternative — summing the raw thirds and rounding once —
        is forbidden: with one `OPEN` record in each of the three families the
        pinned order yields 100 − (3.3 + 3.3 + 3.3) = 90.1, while the
        alternative yields 90.0."

        Design: Difficulty/combinatorial_formula/compliance_score_per_family_rounding_order
        """
        est = fx.create_establishment(
            api, name="D4 Mixed Plant", species_classes=["CATTLE"], slaughter_capable=False
        )
        inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
        for family, description in (
            ("SANITATION", "condensate over exposed product"),
            ("HACCP", "missed ccp check"),
            ("HUMANE", "no water in truck"),
        ):
            fx.issue_nr(api, est["id"], inspector["id"], regulation_family=family, description=description)

        data = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)

        assert data["open_nr_count"] == 3
        # 100 - (3.3 + 3.3 + 3.3): round-half-up per family FIRST, then sum.
        assert data["compliance_score"] == pytest.approx(90.1, abs=0.001), (
            f"pinned order yields 90.1 (not the sum-then-round 90.0); got {data['compliance_score']}"
        )
        assert abs(data["compliance_score"] - 90.0) > 0.01, (
            "the sum-then-round alternative (90.0) is forbidden"
        )

    def test_family_penalty_rounds_each_family_independently(self, api):
        """PRD §2.10: "For each regulation family F among `SANITATION`,
        `HACCP`, and `HUMANE`, count the establishment's records in family F
        whose status is one of the four open statuses above; multiply that
        count by 10 and divide by 3, rounding the result half-up to 1 decimal
        place to obtain the family penalty. The score is 100 minus the sum of
        the three rounded family penalties."

        Design: Difficulty/combinatorial_formula/compliance_score_per_family_rounding_order
        """
        est = fx.create_establishment(
            api, name="D4 Rounding Plant", species_classes=["CATTLE"], slaughter_capable=False
        )
        inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])

        fx.issue_nr(api, est["id"], inspector["id"], regulation_family="SANITATION")
        one = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        # round_half_up(1*10/3, 1) == 3.3 -> 100 - 3.3 == 96.7
        assert one["compliance_score"] == pytest.approx(96.7, abs=0.001), (
            f"single-family penalty: expected 96.7, got {one['compliance_score']}"
        )

        fx.issue_nr(api, est["id"], inspector["id"], regulation_family="HACCP")
        fx.issue_nr(api, est["id"], inspector["id"], regulation_family="HACCP")
        three = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        # round_half_up(2*10/3, 1) == 6.7 -> 100 - (3.3 + 6.7 + 0.0) == 90.0
        assert three["compliance_score"] == pytest.approx(90.0, abs=0.001), (
            f"two-record family penalty: expected 90.0, got {three['compliance_score']}"
        )
        assert three["open_nr_count"] == 3


class TestEnforcementPriorityEvaluationOrder:
    def _establishment_with_four_open_nrs_and_two_lifted_suspensions(self, api):
        base = fx.create_granted_establishment(api, species_classes=["CATTLE"], name="D5 Beef Plant")
        est = base["establishment"]
        pair = fx.create_inspector_pair(api, ["CATTLE"])
        issuer, reviewer = pair["issuer"], pair["reviewer"]
        for family, observed in (
            ("SANITATION", "2026-08-28T06:00:00Z"),
            ("HACCP", "2026-08-28T07:00:00Z"),
            ("OTHER", "2026-08-28T08:00:00Z"),
            ("LABELING", "2026-08-28T09:00:00Z"),
        ):
            fx.issue_nr(
                api, est["id"], issuer["id"],
                regulation_family=family, description=f"{family.lower()} finding",
                observed_at=observed,
            )
        # Two egregious confirmations, each auto-suspension lifted with evidence.
        fx.suspend_and_lift_via_egregious_event(
            api, est, issuer["id"], reviewer["id"], observed_at="2026-08-29T06:00:00Z"
        )
        fx.suspend_and_lift_via_egregious_event(
            api, est, issuer["id"], reviewer["id"], observed_at="2026-08-30T06:00:00Z"
        )
        return est["id"]

    def test_tier_is_derived_from_base_alone(self, api):
        """PRD §2.10: "First, the base is computed from the establishment's
        current fields: 10 points per open noncompliance record
        (`open_nr_count`) plus 25 points per lifetime effective suspension
        (`suspension_count`). Second, the tier is derived from the base alone:
        a base of at least 100 is `HIGH` with a bonus of 15; a base of at least
        50 but below 100 is `MEDIUM` with a bonus of 10; a base below 50 is
        `LOW` with a bonus of 5. Third, the score is the base plus the bonus.
        The tier must not be derived from the post-bonus score."

        Design: Difficulty/combinatorial_formula/enforcement_priority_base_tier_then_bonus
        """
        est_id = self._establishment_with_four_open_nrs_and_two_lifted_suspensions(api)

        data = validate_success(api.get_establishment(est_id, DISTRICT_MANAGER_HEADERS), 200)

        assert data["open_nr_count"] == 4
        assert data["suspension_count"] == 2
        # base == 10*4 + 25*2 == 90 -> MEDIUM tier (bonus 10) -> score 100.
        # Deriving the tier from the post-bonus 100 would give HIGH (+15) -> 105.
        assert data["enforcement_priority_score"] == 100, (
            f"expected base-tier-then-bonus score 100, got {data['enforcement_priority_score']}"
        )
        assert data["enforcement_priority_score"] != 105, (
            "the post-bonus-tier alternative (105) is forbidden"
        )
        assert data["inspection_status"] == "ACTIVE", "both suspensions were lifted"

    def test_low_and_medium_band_boundaries(self, api):
        """PRD §2.10: "a base of at least 100 is `HIGH` with a bonus of 15; a
        base of at least 50 but below 100 is `MEDIUM` with a bonus of 10; a
        base below 50 is `LOW` with a bonus of 5."

        Design: Difficulty/combinatorial_formula/enforcement_priority_base_tier_then_bonus
        """
        est = fx.create_establishment(api, name="D5 Band Plant", species_classes=["CATTLE"])
        inspector = fx.create_inspector(api, species_qualifications=["CATTLE"])
        for _ in range(4):
            fx.issue_nr(api, est["id"], inspector["id"], regulation_family="SANITATION")

        four = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        # base 40 < 50 -> LOW, bonus 5 -> 45.
        assert four["enforcement_priority_score"] == 45, (
            f"base 40 -> LOW (+5) == 45, got {four['enforcement_priority_score']}"
        )

        fx.issue_nr(api, est["id"], inspector["id"], regulation_family="SANITATION")
        five = validate_success(api.get_establishment(est["id"], DISTRICT_MANAGER_HEADERS), 200)
        # base 50 -> exactly at the MEDIUM floor -> bonus 10 -> 60.
        assert five["enforcement_priority_score"] == 60, (
            f"base 50 -> MEDIUM (+10) == 60, got {five['enforcement_priority_score']}"
        )
