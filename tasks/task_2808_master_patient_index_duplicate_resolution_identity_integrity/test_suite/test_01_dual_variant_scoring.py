"""Null-handling variants and the two duplicate-rate attribution variants."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.constants import (
    ATTRIBUTION_CREATION_SITE,
    ATTRIBUTION_SURVIVOR_SITE,
    CLASSIFICATION_NON_DUPLICATE,
    CLASSIFICATION_POTENTIAL_DUPLICATE,
    MERGE_COMPLETED,
    QUEUE_NEW,
    RS_BASE_VERSION_LABEL,
    SCORE_VARIANT_STRICT,
    SCORE_VARIANT_TOLERANT,
)
from test_helpers.test_users import admin_headers, analyst_headers, steward_headers


def _dual_variant_setup(api):
    """One site, one draft rule set and the two records that differ only in nulls."""
    site = F.create_site(
        api, "SITE-DV", name="Dual Variant Clinic", region_code="US-CA",
        registrar_headcount=4,
    )
    rule_set = F.create_rule_set(api, activate=False)
    record_a = F.create_record(
        api, site["id"], "DV-1001", "Nguyen", "Anhthu", "1984-03-11", "F",
        ssn_last4="4417", postal_code="94110", phone="4155550101",
        clinical_element_count=6,
    )
    record_b = F.create_record(
        api, site["id"], "DV-1002", "nguyen", "Anh", "1984-03-11", "F",
        postal_code="94112", clinical_element_count=3,
    )
    return site, rule_set, record_a, record_b


STRICT_BREAKDOWN = {
    "last_name": 25.00,
    "first_name": 7.50,
    "dob": 25.00,
    "ssn_last4": 0.00,
    "sex": 5.00,
    "postal_code": 5.00,
    "phone": 0.00,
}
TOLERANT_BREAKDOWN = {
    "last_name": 25.00,
    "first_name": 7.50,
    "dob": 25.00,
    "ssn_last4": 3.75,
    "sex": 5.00,
    "postal_code": 5.00,
    "phone": 1.25,
}


class TestStrictVersusTolerantNullCredit:
    def test_strict_variant_gives_a_missing_attribute_no_credit_at_all(self, api):
        """A STRICT pair over two records with two null-on-one-side attributes.

        PRD §3.3: "Where agreement is undefined because a value was missing, the
        contribution depends on the pair's `score_variant`: under `STRICT` the
        contribution is exactly 0.00, and under `TOLERANT` the contribution is the
        weight multiplied by one quarter, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/strict_vs_tolerant_null_credit_flips_pair_classification
        """
        site, rule_set, record_a, record_b = _dual_variant_setup(api)

        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        A.assert_score(pair["raw_score"], 67.50, "raw_score")
        A.assert_score(pair["match_score"], 67.50, "match_score")
        A.assert_breakdown(pair["attribute_score_breakdown"], STRICT_BREAKDOWN)
        assert pair["conflict_flags"] == []
        assert pair["classification"] == CLASSIFICATION_NON_DUPLICATE
        assert pair["base_band"] == "P3"
        assert pair["priority_band"] == "P3"
        A.assert_score(pair["effective_score"], 67.50, "effective_score")
        assert pair["queue_state"] == QUEUE_NEW
        assert pair["subject_record_mrn"] == "DV-1002"
        assert pair["detected_at_site_id"] == site["id"]

    def test_tolerant_rescore_crosses_the_review_threshold_without_moving_the_queue(
        self, api
    ):
        """Re-scoring the same pair as TOLERANT reclassifies it but not its queue.

        PRD §3.3: "Re-scoring is not a queue transition: `queue_state` is left
        exactly as it was, and the operation is permitted only from `NEW`,
        `TRIAGED` or `UNDER_REVIEW`."

        Design: Difficulty/dual_variant_calc/strict_vs_tolerant_null_credit_flips_pair_classification
        """
        _, rule_set, record_a, record_b = _dual_variant_setup(api)
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        rescored = A.assert_ok(
            api.rescore_pair(
                pair["id"],
                f.rescore_payload(
                    rule_set["id"], SCORE_VARIANT_TOLERANT,
                    expected_pair_version=pair["version"],
                ),
                analyst_headers(),
            )
        )

        A.assert_score(rescored["raw_score"], 72.50, "raw_score")
        A.assert_score(rescored["match_score"], 72.50, "match_score")
        A.assert_breakdown(rescored["attribute_score_breakdown"], TOLERANT_BREAKDOWN)
        assert rescored["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert rescored["base_band"] == "P2"
        assert rescored["priority_band"] == "P2"
        A.assert_score(rescored["effective_score"], 72.50, "effective_score")
        assert rescored["queue_state"] == QUEUE_NEW
        A.assert_version(rescored, 2)

    def test_the_whole_variant_delta_comes_from_the_two_missing_attributes(self, api):
        """The 5.00 point swing is exactly the quarter-weight of ssn_last4 and phone.

        PRD §3.3: "The same two records can therefore land above `review_threshold`
        under `TOLERANT` while classifying as `NON_DUPLICATE` under `STRICT`, and
        that divergence is intended rather than a defect."

        Design: Difficulty/dual_variant_calc/strict_vs_tolerant_null_credit_flips_pair_classification
        """
        _, rule_set, record_a, record_b = _dual_variant_setup(api)
        strict = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        tolerant = A.assert_ok(
            api.rescore_pair(
                strict["id"],
                f.rescore_payload(
                    rule_set["id"], SCORE_VARIANT_TOLERANT,
                    expected_pair_version=strict["version"],
                ),
                analyst_headers(),
            )
        )

        delta = tolerant["match_score"] - strict["match_score"]
        assert delta == pytest.approx(5.00, abs=0.01)
        assert (
            tolerant["attribute_score_breakdown"]["ssn_last4"]
            + tolerant["attribute_score_breakdown"]["phone"]
        ) == pytest.approx(5.00, abs=0.01)
        for attribute in ("last_name", "first_name", "dob", "sex", "postal_code"):
            A.assert_score(
                tolerant["attribute_score_breakdown"][attribute],
                strict["attribute_score_breakdown"][attribute],
                f"breakdown[{attribute}]",
            )


def _cross_site_merge_setup(api):
    """A cross-site AUTO_LINK merge with no downstream consumer registered."""
    site_n = F.create_site(
        api, "SITE-N", name="North Registration", region_code="US-MW",
        registrar_headcount=6,
    )
    site_s = F.create_site(
        api, "SITE-S", name="South Registration", region_code="US-MW",
        registrar_headcount=3,
    )
    rule_set = F.create_rule_set(api, activate=True)
    F.create_record(
        api, site_n["id"], "N-5001", "Halvorsen", "Ingrid", "1957-01-23", "F",
        ssn_last4="1010", postal_code="55401", phone="6125550111",
        clinical_element_count=9,
    )
    survivor = F.create_record(
        api, site_s["id"], "S-7001", "Rasmussen", "Bjorn", "1962-09-08", "M",
        ssn_last4="6633", postal_code="55414", phone="6125550222",
        clinical_element_count=14,
    )
    subsumed = F.create_record(
        api, site_n["id"], "N-5002", "Rasmussen", "Bjorn", "1962-09-08", "M",
        ssn_last4="6633", postal_code="55414", phone="6125550222",
        clinical_element_count=5,
    )
    pair = F.create_pair(
        api, survivor["id"], subsumed["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_row = F.merge(
        api, pair["id"], survivor["id"], subsumed["id"],
        rationale="Confirmed same patient across sites; retain the South chart.",
    )
    return site_n, site_s, merge_row


class TestAttributionVariantDivergesOnACrossSiteMerge:
    def test_cross_site_merge_completes_with_no_downstream_consumer(self, api):
        """With no active consumer the merge finishes inside its own request.

        PRD §3.5: "It becomes `COMPLETED` immediately when
        `propagation_task_count` is 0"

        Design: Difficulty/dual_variant_calc/creation_vs_survivor_site_attribution_diverges_on_cross_site_merge
        """
        _, _, merge_row = _cross_site_merge_setup(api)

        assert merge_row["state"] == MERGE_COMPLETED
        A.assert_integer(merge_row["propagation_task_count"], 0, "propagation_task_count")
        A.assert_integer(
            merge_row["moved_clinical_element_count"], 5,
            "moved_clinical_element_count",
        )

    def test_creation_attribution_charges_the_subsumed_record_s_site(self, api):
        """SITE-N created the redundant chart, so it carries the 5000 bps rate.

        PRD §3.9: "under `CREATION_SITE_ATTRIBUTION` the attributed record is the
        merge's **subsumed** record, charging the duplicate to whichever desk
        created the redundant chart"

        Design: Difficulty/dual_variant_calc/creation_vs_survivor_site_attribution_diverges_on_cross_site_merge
        """
        site_n, _, _ = _cross_site_merge_setup(api)

        run = A.assert_created(
            F.run_metric(
                api, site_n["id"], "2026-08-01", "2026-08-31",
                ATTRIBUTION_CREATION_SITE,
            )
        )

        A.assert_integer(run["records_created"], 2, "records_created")
        A.assert_integer(run["confirmed_duplicates"], 1, "confirmed_duplicates")
        A.assert_integer(run["duplicate_rate_bps"], 5000, "duplicate_rate_bps")
        assert run["sample_size_sufficient"] is False
        assert run["rule_set_version_label"] == RS_BASE_VERSION_LABEL

    def test_survivor_attribution_moves_the_duplicate_to_the_other_site(self, api):
        """The identical window charges SITE-S instead, and SITE-N drops to zero.

        PRD §3.9: "while under `SURVIVOR_SITE_ATTRIBUTION` it is the merge's
        **survivor**, charging it to the desk that owns the retained chart."

        Design: Difficulty/dual_variant_calc/creation_vs_survivor_site_attribution_diverges_on_cross_site_merge
        """
        site_n, site_s, _ = _cross_site_merge_setup(api)

        creation_run = A.assert_created(
            F.run_metric(
                api, site_n["id"], "2026-08-01", "2026-08-31",
                ATTRIBUTION_CREATION_SITE,
            )
        )
        survivor_run_n = A.assert_created(
            F.run_metric(
                api, site_n["id"], "2026-08-01", "2026-08-31",
                ATTRIBUTION_SURVIVOR_SITE,
            )
        )
        survivor_run_s = A.assert_created(
            F.run_metric(
                api, site_s["id"], "2026-08-01", "2026-08-31",
                ATTRIBUTION_SURVIVOR_SITE,
            )
        )

        A.assert_integer(creation_run["duplicate_rate_bps"], 5000, "SITE-N creation bps")
        A.assert_integer(survivor_run_n["records_created"], 2, "records_created")
        A.assert_integer(
            survivor_run_n["confirmed_duplicates"], 0, "confirmed_duplicates"
        )
        A.assert_integer(survivor_run_n["duplicate_rate_bps"], 0, "SITE-N survivor bps")
        A.assert_integer(survivor_run_s["records_created"], 1, "records_created")
        A.assert_integer(
            survivor_run_s["confirmed_duplicates"], 1, "confirmed_duplicates"
        )
        A.assert_integer(
            survivor_run_s["duplicate_rate_bps"], 10000, "SITE-S survivor bps"
        )

    def test_both_variants_may_be_computed_over_the_identical_window(self, api):
        """Window exclusivity partitions by attribution variant, not by site alone.

        PRD §3.9: "Runs of the *other* variant are ignored entirely, so both
        attribution views may be computed over identical windows."

        Design: Difficulty/dual_variant_calc/creation_vs_survivor_site_attribution_diverges_on_cross_site_merge
        """
        site_n, _, _ = _cross_site_merge_setup(api)

        first = F.run_metric(
            api, site_n["id"], "2026-08-01", "2026-08-31", ATTRIBUTION_CREATION_SITE
        )
        second = F.run_metric(
            api, site_n["id"], "2026-08-01", "2026-08-31", ATTRIBUTION_SURVIVOR_SITE
        )

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        rows, meta = A.assert_list_meta(
            api.list_metric_runs(site_n["id"], admin_headers()), expected_total=2
        )
        assert len(rows) == 2
