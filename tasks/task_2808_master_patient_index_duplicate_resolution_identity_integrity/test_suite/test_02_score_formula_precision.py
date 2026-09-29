"""Rounding order, component caps and threshold inclusivity in the score chain."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.constants import (
    CLASSIFICATION_AUTO_LINK,
    CLASSIFICATION_NON_DUPLICATE,
    CLASSIFICATION_POTENTIAL_DUPLICATE,
    CONFLICT_BIOMETRIC,
    INTEGRITY_CLEAR,
    INTEGRITY_FRAUD_SUSPECTED,
    INVESTIGATION_OPEN,
    OPENED_BY_SYSTEM,
    OUTCOME_SAME_PERSON,
    QUEUE_ESCALATED_FRAUD,
    QUEUE_NEW,
    QUEUE_UNDER_REVIEW,
    SCORE_VARIANT_STRICT,
    SCORE_VARIANT_TOLERANT,
    TRIGGER_BIOMETRIC_CONFLICT,
)
from test_helpers.test_users import admin_headers, analyst_headers, officer_headers

ODD_WEIGHTS = {
    "last_name": 24.99,
    "first_name": 15.01,
    "dob": 25.05,
    "ssn_last4": 14.95,
    "sex": 5.05,
    "postal_code": 9.95,
    "phone": 5.00,
}
ODD_BREAKDOWN = {
    "last_name": 12.50,
    "first_name": 7.51,
    "dob": 12.53,
    "ssn_last4": 3.74,
    "sex": 0.00,
    "postal_code": 4.98,
    "phone": 1.25,
}


def _odd_weight_pair(api):
    site = F.create_site(
        api, "SITE-OD", name="Odd Weights Clinic", region_code="US-IL",
        registrar_headcount=2,
    )
    rule_set = F.create_rule_set(
        api, activate=False, name="Odd Weight Match Rules", version_label="V-ODD-1",
        attribute_weights=ODD_WEIGHTS, auto_link_threshold=90.00,
        review_threshold=70.00, conflict_penalty_points=12.00,
    )
    record_a = F.create_record(
        api, site["id"], "OD-2001", "Okonkwo", "Chidera", "1979-06-14", "F",
        ssn_last4="8802", postal_code="60614", clinical_element_count=7,
    )
    record_b = F.create_record(
        api, site["id"], "OD-2002", "Okoye", "Chidi", "1979-06-02", "M",
        postal_code="60618", clinical_element_count=2,
    )
    return F.create_pair(
        api, record_a["id"], record_b["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_TOLERANT,
    )


class TestRoundThenSumOrderIsPinned:
    def test_each_attribute_contribution_is_rounded_before_the_sum(self, api):
        """Odd weights make the published contributions individually rounded.

        PRD §3.3: "Rounding each contribution first and summing afterwards is the
        specified order; summing the exact products and rounding once at the end is
        a different and incorrect computation."

        Design: Difficulty/combinatorial_formula/pair_match_score_round_then_sum_order_is_pinned
        """
        pair = _odd_weight_pair(api)

        A.assert_breakdown(pair["attribute_score_breakdown"], ODD_BREAKDOWN)
        A.assert_score(pair["raw_score"], 42.51, "raw_score")
        assert pair["raw_score"] != pytest.approx(42.49, abs=0.001), (
            "raw_score 42.49 means the exact products were summed before rounding"
        )

    def test_the_published_breakdown_reconciles_with_the_raw_score(self, api):
        """The seven published contributions sum to raw_score exactly.

        PRD §3.3: "`raw_score` is then the sum of those **already-rounded** seven
        contributions, itself rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/pair_match_score_round_then_sum_order_is_pinned
        """
        pair = _odd_weight_pair(api)

        total = sum(pair["attribute_score_breakdown"].values())
        assert total == pytest.approx(42.51, abs=0.01)
        A.assert_score(pair["match_score"], 42.51, "match_score")
        assert pair["conflict_flags"] == []
        assert pair["classification"] == CLASSIFICATION_NON_DUPLICATE
        assert pair["base_band"] == "P3"
        assert pair["priority_band"] == "P3"
        A.assert_score(pair["effective_score"], 42.51, "effective_score")


def _biometric_conflict_setup(api):
    site = F.create_site(
        api, "SITE-FR", name="Fraud Screening Clinic", region_code="US-MA",
        registrar_headcount=5,
    )
    rule_set = F.create_rule_set(api, activate=False)
    record_a = F.create_record(
        api, site["id"], "FR-3001", "Marchetti", "Giulia", "1990-11-02", "F",
        ssn_last4="5150", postal_code="02139", phone="6175550188",
        biometric_template_hash="BIO-HASH-AAA", clinical_element_count=11,
    )
    record_b = F.create_record(
        api, site["id"], "FR-3002", "Marchetti", "Giulia", "1990-11-02", "F",
        ssn_last4="5150", postal_code="02139", phone="6175550188",
        biometric_template_hash="BIO-HASH-BBB", clinical_element_count=4,
    )
    pair = F.create_pair(
        api, record_a["id"], record_b["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    return site, record_a, record_b, pair


class TestFraudRiskScoreComponentsAndCaps:
    def test_a_biometric_conflict_escalates_the_pair_and_opens_one_investigation(
        self, api
    ):
        """A conflicted AUTO_LINK pair escalates instead of auto-recommending.

        PRD §3.3: "If `conflict_flags` contains `BIOMETRIC_CONFLICT` or
        `INSURANCE_CONFLICT` **and** `raw_score` is at or above 70.00, the pair does
        not enter the queue at all: it opens directly in `ESCALATED_FRAUD` and the
        fraud machinery of §3.9 engages."

        Design: Difficulty/combinatorial_formula/fraud_risk_score_four_components_with_nested_caps
        """
        _, record_a, record_b, pair = _biometric_conflict_setup(api)

        A.assert_score(pair["raw_score"], 100.00, "raw_score")
        assert pair["conflict_flags"] == [CONFLICT_BIOMETRIC]
        A.assert_score(pair["match_score"], 88.00, "match_score")
        assert pair["classification"] == CLASSIFICATION_AUTO_LINK
        assert pair["queue_state"] == QUEUE_ESCALATED_FRAUD
        assert pair["subject_record_mrn"] == "FR-3002"

        subject_rows = F.investigations_for_record(api, record_b["id"])
        other_rows = F.investigations_for_record(api, record_a["id"])
        assert len(subject_rows) == 1
        assert len(other_rows) == 0
        investigation = subject_rows[0]
        assert investigation["opened_by"] == OPENED_BY_SYSTEM
        assert investigation["opened_by_user_id"] is None
        assert investigation["trigger_kind"] == TRIGGER_BIOMETRIC_CONFLICT
        assert investigation["state"] == INVESTIGATION_OPEN
        assert investigation["pair_id"] == pair["id"]

    def test_risk_score_sums_four_capped_components_to_fifty_points(self, api):
        """30.00 conflict + 18.00 score + 2.00 site + 0.00 insurance = 50.00.

        PRD §3.9: "The **site component** is 2.00 points for every record currently
        counted in the subject's site `flagged_record_count`, capped at 20.00"

        Design: Difficulty/combinatorial_formula/fraud_risk_score_four_components_with_nested_caps
        """
        site, record_a, record_b, _ = _biometric_conflict_setup(api)

        investigation = F.investigations_for_record(api, record_b["id"])[0]

        A.assert_score(investigation["risk_score"], 50.00, "risk_score")
        subject = F.get_record(api, record_b["id"])
        other = F.get_record(api, record_a["id"])
        assert subject["integrity_state"] == INTEGRITY_FRAUD_SUSPECTED
        assert other["integrity_state"] == INTEGRITY_CLEAR
        A.assert_site_counters(
            F.get_site(api, site["id"]), flagged_record_count=1
        )


def _boundary_threshold_setup(api):
    site = F.create_site(
        api, "SITE-BD", name="Boundary Clinic", region_code="US-NY",
        registrar_headcount=6,
    )
    rs_base = F.create_rule_set(api, activate=False)
    rs_hi = F.create_rule_set(
        api, activate=False, name="Raised Review Threshold Rules",
        version_label="V-HI-1", auto_link_threshold=85.00, review_threshold=70.01,
    )
    record_a = F.create_record(
        api, site["id"], "BD-3001", "Petrov", "Dmitri", "1972-08-19", "M",
        ssn_last4="3388", postal_code="10011", phone="2125550142",
        clinical_element_count=11,
    )
    record_b = F.create_record(
        api, site["id"], "BD-3002", "Petrov", "Dmitri", "1972-08-19", "M",
        clinical_element_count=2,
    )
    return site, rs_base, rs_hi, record_a, record_b


class TestReviewThresholdInclusivity:
    def test_a_score_exactly_on_the_review_threshold_is_a_potential_duplicate(
        self, api
    ):
        """70.00 against a review threshold of 70.00 classifies as a duplicate.

        PRD §3.3: "otherwise `POTENTIAL_DUPLICATE` when `match_score` is at or above
        `review_threshold`; otherwise `NON_DUPLICATE`."

        Design: Difficulty/boundary_precision_check/match_score_exactly_at_review_threshold_is_inclusive
        """
        _, rs_base, _, record_a, record_b = _boundary_threshold_setup(api)

        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rs_base["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        A.assert_score(pair["raw_score"], 70.00, "raw_score")
        A.assert_score(pair["match_score"], 70.00, "match_score")
        A.assert_breakdown(
            pair["attribute_score_breakdown"],
            {
                "last_name": 25.00,
                "first_name": 15.00,
                "dob": 25.00,
                "ssn_last4": 0.00,
                "sex": 5.00,
                "postal_code": 0.00,
                "phone": 0.00,
            },
        )
        assert pair["conflict_flags"] == []
        assert pair["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert pair["queue_state"] == QUEUE_NEW
        A.assert_version(pair, 1)
        assert pair["base_band"] == "P2"
        A.assert_score(pair["effective_score"], 70.00, "effective_score")
        assert pair["priority_band"] == "P2"

    def test_raising_the_threshold_by_one_hundredth_flips_the_classification(self, api):
        """The score does not move; only the rule set's threshold does.

        PRD §3.4: "Step one derives `base_band` from `match_score` alone: `P1` when
        `match_score` is at or above 85.00, `P2` when it is at or above 70.00, and
        `P3` otherwise."

        Design: Difficulty/boundary_precision_check/match_score_exactly_at_review_threshold_is_inclusive
        """
        _, rs_base, rs_hi, record_a, record_b = _boundary_threshold_setup(api)
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rs_base["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        rescored = A.assert_ok(
            api.rescore_pair(
                pair["id"],
                f.rescore_payload(
                    rs_hi["id"], SCORE_VARIANT_STRICT,
                    expected_pair_version=pair["version"],
                ),
                analyst_headers(),
            )
        )

        assert rescored["rule_set_id"] == rs_hi["id"]
        A.assert_score(rescored["match_score"], 70.00, "match_score")
        assert rescored["classification"] == CLASSIFICATION_NON_DUPLICATE
        assert rescored["base_band"] == "P2"
        assert rescored["priority_band"] == "P2"
        assert rescored["queue_state"] == QUEUE_NEW
        A.assert_version(rescored, 2)


def _band_multiplier_setup(api):
    site = F.create_site(
        api, "SITE-EV", name="Evidence Clinic", region_code="US-GA",
        registrar_headcount=5,
    )
    rule_set = F.create_rule_set(
        api, activate=False, name="Band Test Rules", version_label="V-BAND-1",
        auto_link_threshold=90.00, review_threshold=70.00,
    )
    record_a = F.create_record(
        api, site["id"], "EV-4001", "Adeyemi", "Folake", "1988-02-29", "F",
        ssn_last4="7071", clinical_element_count=14,
    )
    record_b = F.create_record(
        api, site["id"], "EV-4002", "Adeyemi", "Folake", "1988-02-29", "F",
        ssn_last4="7071", clinical_element_count=6,
    )
    pair = F.create_pair(
        api, record_a["id"], record_b["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    F.advance_to_under_review(api, pair["id"], "Rounding-mode probe pair.")
    return pair


class TestEvidenceAdjustmentRoundsHalfUp:
    def test_a_pair_at_the_p1_cutoff_scales_its_first_evidence_by_one_and_a_half(
        self, api
    ):
        """4.00 evidence points on a P1 pair adjust the score by 6.00.

        PRD §3.4: "`evidence_adjustment` is then `evidence_points` multiplied by
        that pinned multiplier, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/evidence_adjustment_rounds_half_up_at_third_decimal
        """
        pair = _band_multiplier_setup(api)
        before = F.get_pair(api, pair["id"])
        A.assert_score(before["match_score"], 85.00, "match_score")
        assert before["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert before["base_band"] == "P1"
        A.assert_score(before["evidence_points"], 0.00, "evidence_points")
        A.assert_score(before["evidence_adjustment"], 0.00, "evidence_adjustment")
        A.assert_score(before["effective_score"], 85.00, "effective_score")

        F.add_evidence(
            api, pair["id"], "PHOTO_ID", OUTCOME_SAME_PERSON, 4.00,
            note="Same photograph on both encounters.",
        )

        after = F.get_pair(api, pair["id"])
        A.assert_score(after["evidence_points"], 4.00, "evidence_points")
        A.assert_score(after["evidence_adjustment"], 6.00, "evidence_adjustment")
        A.assert_score(after["effective_score"], 91.00, "effective_score")
        assert after["priority_band"] == "P1"

    def test_a_half_cent_product_rounds_up_rather_than_to_even(self, api):
        """8.15 points times 1.50 is 12.225, which must render as 12.23.

        PRD §2.5: "are carried to exactly 2 decimal places and rounded half up."

        Design: Difficulty/boundary_precision_check/evidence_adjustment_rounds_half_up_at_third_decimal
        """
        pair = _band_multiplier_setup(api)
        F.add_evidence(
            api, pair["id"], "PHOTO_ID", OUTCOME_SAME_PERSON, 4.00,
            note="Same photograph on both encounters.",
        )
        F.add_evidence(
            api, pair["id"], "INSURANCE_CARD", OUTCOME_SAME_PERSON, 4.15,
            note="Identical member id and group number.",
        )

        after = F.get_pair(api, pair["id"])
        A.assert_score(after["evidence_points"], 8.15, "evidence_points")
        A.assert_score(after["evidence_adjustment"], 12.23, "evidence_adjustment")
        A.assert_score(after["effective_score"], 97.23, "effective_score")
        assert after["base_band"] == "P1"
        assert after["priority_band"] == "P1"
        assert after["queue_state"] == QUEUE_UNDER_REVIEW
        A.assert_version(after, 5)

        rows = A.list_rows(
            api.list_evidence(pair["id"], analyst_headers()), expected_total=2
        )
        # PRD §3.4 pins `weight_points` as "stored exactly as supplied", but the
        # two rows share one logical-clock `created_at`, and PRD §2.3 declares no
        # tie-break for the evidence collection -- so only the multiset is
        # uniquely derivable, not the order.
        assert sorted(row["weight_points"] for row in rows) == pytest.approx(
            [4.00, 4.15]
        )
