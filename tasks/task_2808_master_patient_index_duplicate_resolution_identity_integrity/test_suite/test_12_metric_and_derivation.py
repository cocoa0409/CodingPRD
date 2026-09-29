"""Which rows a computation is allowed to read, and in which order.

Covers the registration search pool, the duplicate-rate populations, the band
multiplier's provenance and the integrity precedence chain.
"""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.constants import (
    ATTRIBUTION_CREATION_SITE,
    ATTRIBUTION_SURVIVOR_SITE,
    IDENTITY_ACTIVE,
    IDENTITY_MERGED_SUBSUMED,
    INTEGRITY_CLEAR,
    INTEGRITY_FRAUD_SUSPECTED,
    INTEGRITY_REMEDIATION_PENDING,
    INVESTIGATION_OPEN,
    INVESTIGATION_UNSUBSTANTIATED,
    MERGE_COMPLETED,
    MERGE_UNMERGED,
    OPENED_BY_OFFICER,
    OUTCOME_DISTINCT,
    OVERLAY_DETECTED,
    QUEUE_RECOMMENDED_MERGE,
    RS_BASE_VERSION_LABEL,
    SCORE_VARIANT_STRICT,
    TRIGGER_MANUAL,
)
from test_helpers.test_users import (
    STEWARD_2_USER_ID,
    analyst_headers,
    officer_headers,
    steward_headers,
)

SEARCH_TERMS = {
    "searched_last_name": "Thibodeaux",
    "searched_first_name": "Marcel",
    "searched_dob": "1966-09-09",
    "searched_sex": "M",
    "searched_ssn_last4": "6161",
    "searched_postal_code": "55401",
    "searched_phone": "6125550101",
}

POOL_DEMOGRAPHICS = {
    "last_name": "Thibodeaux",
    "first_name": "Marcel",
    "dob": "1966-09-09",
    "sex": "M",
    "ssn_last4": "6161",
    "postal_code": "55401",
    "phone": "6125550101",
}


class TestRegistrationSearchPool:
    def test_absorbing_one_of_two_twins_removes_it_from_the_search_pool(self, api):
        """The pool restriction is the one place identity_state filters the scorer.

        PRD §3.3: "Neither `identity_state` nor `integrity_state` restricts what the
        comparison may read — a record that has already been absorbed into a cluster
        can still be scored — the only place a pool restriction applies is the
        enterprise-wide registration search of §3.2, which considers `ACTIVE` records
        only."

        Design: Corner/calculations/registration_search_pool_excludes_merged_subsumed_records
        """
        site = F.create_site(
            api, "SITE-C6", name="Search Pool Clinic", region_code="US-MN",
            registrar_headcount=5,
        )
        rule_set = F.create_rule_set(api, activate=True)
        record_a = F.create_record(
            api, site["id"], "C6-1000", clinical_element_count=4, **POOL_DEMOGRAPHICS
        )
        record_b = F.create_record(
            api, site["id"], "C6-2000", clinical_element_count=1, **POOL_DEMOGRAPHICS
        )
        before = A.assert_created(
            api.create_search_attempt(
                site["id"], f.search_attempt_payload(**SEARCH_TERMS), analyst_headers()
            )
        )
        A.assert_integer(before["result_count"], 2, "result_count")
        A.assert_score(before["top_score"], 100.00, "top_score")
        assert before["top_match_record_mrn"] == "C6-1000"
        assert before["blocked_creation"] is True
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        A.assert_score(pair["match_score"], 100.00, "match_score")
        assert pair["queue_state"] == QUEUE_RECOMMENDED_MERGE
        merge_row = F.merge(
            api, pair["id"], record_b["id"], record_a["id"],
            rationale="Identical chart created twice at the same desk.",
        )
        assert merge_row["state"] == MERGE_COMPLETED

        after = A.assert_created(
            api.create_search_attempt(
                site["id"], f.search_attempt_payload(**SEARCH_TERMS), analyst_headers()
            )
        )

        A.assert_integer(after["result_count"], 1, "result_count")
        A.assert_score(after["top_score"], 100.00, "top_score")
        assert after["top_match_record_mrn"] == "C6-2000"
        assert after["blocked_creation"] is True
        assert after["rule_set_version_label"] == RS_BASE_VERSION_LABEL
        assert after["site_id"] == site["id"]
        rows = A.list_rows(
            api.list_search_attempts(site["id"], analyst_headers()), expected_total=2
        )
        assert len(rows) == 2
        assert F.get_record(api, record_a["id"])["identity_state"] == (
            IDENTITY_MERGED_SUBSUMED
        )


A7_DEMOGRAPHICS = {
    "last_name": "Stavropoulos",
    "first_name": "Eleni",
    "dob": "1991-04-04",
    "sex": "F",
    "ssn_last4": "7070",
    "postal_code": "50309",
    "phone": "5155550101",
}

B7_DEMOGRAPHICS = {
    "last_name": "Adeyemi",
    "first_name": "Folake",
    "dob": "1984-10-25",
    "sex": "F",
    "ssn_last4": "8080",
    "postal_code": "50310",
    "phone": "5155550202",
}


def _merge_one_twin_pair(api, site, rule_set, prefix, demographics, rationale):
    """Register two identical charts at one site and merge the second into the first."""
    survivor = F.create_record(
        api, site["id"], f"{prefix}-1000", clinical_element_count=3, **demographics
    )
    subsumed = F.create_record(
        api, site["id"], f"{prefix}-2000", clinical_element_count=1, **demographics
    )
    pair = F.create_pair(
        api, survivor["id"], subsumed["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_row = F.merge(
        api, pair["id"], survivor["id"], subsumed["id"], rationale=rationale
    )
    return survivor, subsumed, merge_row


class TestDuplicateRatePopulations:
    def test_a_reversed_merge_no_longer_counts_as_a_confirmed_duplicate(self, api):
        """Two identically prepared desks diverge only because one merge was undone.

        PRD §3.9: "`confirmed_duplicates` is the number of merge operations whose
        `state` is `PENDING_PROPAGATION` or `COMPLETED`, excluding those reversed to
        `UNMERGED`, whose *attributed* record belongs to this site and whose attributed
        record's `created_at` date falls in the same closed window."

        Design: Corner/calculations/duplicate_rate_excludes_unmerged_merge_operations
        """
        rule_set = F.create_rule_set(api, activate=True)
        site_kept = F.create_site(
            api, "SITE-C7A", name="Kept Merge Clinic", region_code="US-IA",
            registrar_headcount=2,
        )
        site_reversed = F.create_site(
            api, "SITE-C7B", name="Reversed Merge Clinic", region_code="US-IA",
            registrar_headcount=2,
        )
        _, kept_subsumed, kept_merge = _merge_one_twin_pair(
            api, site_kept, rule_set, "A7", A7_DEMOGRAPHICS,
            "Duplicate chart at the kept-merge site.",
        )
        _, reversed_subsumed, reversed_merge = _merge_one_twin_pair(
            api, site_reversed, rule_set, "B7", B7_DEMOGRAPHICS,
            "Duplicate chart at the reversed-merge site.",
        )
        assert kept_merge["state"] == MERGE_COMPLETED
        undone = A.assert_ok(
            api.unmerge(
                reversed_merge["id"],
                f.unmerge_payload(
                    "Wrong pair approved; the two charts are different patients."
                ),
                steward_headers(STEWARD_2_USER_ID),
            )
        )
        assert undone["state"] == MERGE_UNMERGED

        kept_run = A.assert_created(
            F.run_metric(api, site_kept["id"], "2026-08-01", "2026-08-01")
        )
        reversed_run = A.assert_created(
            F.run_metric(api, site_reversed["id"], "2026-08-01", "2026-08-01")
        )

        A.assert_integer(kept_run["records_created"], 2, "records_created")
        A.assert_integer(kept_run["confirmed_duplicates"], 1, "confirmed_duplicates")
        A.assert_integer(kept_run["duplicate_rate_bps"], 5000, "duplicate_rate_bps")
        A.assert_integer(reversed_run["records_created"], 2, "records_created")
        A.assert_integer(
            reversed_run["confirmed_duplicates"], 0, "confirmed_duplicates"
        )
        A.assert_integer(reversed_run["duplicate_rate_bps"], 0, "duplicate_rate_bps")
        assert kept_run["sample_size_sufficient"] is False
        assert reversed_run["sample_size_sufficient"] is False
        assert kept_run["rule_set_version_label"] == RS_BASE_VERSION_LABEL
        assert reversed_run["rule_set_version_label"] == RS_BASE_VERSION_LABEL
        assert F.get_record(api, reversed_subsumed["id"])["identity_state"] == (
            IDENTITY_ACTIVE
        )
        assert F.get_record(api, kept_subsumed["id"])["identity_state"] == (
            IDENTITY_MERGED_SUBSUMED
        )

    def test_an_empty_denominator_reports_zero_rather_than_failing(self, api):
        """A desk that registered nobody has a rate of 0, not a division error.

        PRD §3.9: "`duplicate_rate_bps` expresses the result in basis points, that is
        hundredths of a percentage point: it is 0 when `records_created` is 0, and
        otherwise `confirmed_duplicates` multiplied by 10,000 and divided by
        `records_created`, with a **single** half-up rounding to an integer applied at
        the very end."

        Design: Corner/calculations/duplicate_rate_is_zero_when_no_records_were_created
        """
        F.create_rule_set(api, activate=True)
        site = F.create_site(
            api, "SITE-C8", name="Empty Denominator Clinic", region_code="US-MT",
            registrar_headcount=1,
        )

        run = A.assert_created(
            F.run_metric(
                api, site["id"], "2026-07-01", "2026-08-01",
                attribution_variant=ATTRIBUTION_SURVIVOR_SITE,
                headers=analyst_headers(),
            )
        )

        A.assert_integer(run["records_created"], 0, "records_created")
        A.assert_integer(run["confirmed_duplicates"], 0, "confirmed_duplicates")
        A.assert_integer(run["duplicate_rate_bps"], 0, "duplicate_rate_bps")
        assert run["sample_size_sufficient"] is False
        assert run["rule_set_version_label"] == RS_BASE_VERSION_LABEL
        assert run["attribution_variant"] == ATTRIBUTION_SURVIVOR_SITE
        assert run["window_start_date"] == "2026-07-01"
        assert run["window_end_date"] == "2026-08-01"

    def test_a_repeating_ratio_rounds_half_up_once_at_the_end(self, api):
        """Two duplicates over three registrations is 6666.66..., reported as 6667.

        PRD §3.9: "No intermediate ratio is rounded and nothing is rounded per merge."

        Design: Corner/calculations/duplicate_rate_bps_rounds_half_up_from_a_repeating_ratio
        """
        rule_set = F.create_rule_set(api, activate=True)
        site = F.create_site(
            api, "SITE-CA", name="Repeating Ratio Clinic", region_code="US-CO",
            registrar_headcount=3,
        )
        demographics = {
            "last_name": "Nakagawa",
            "first_name": "Hiroshi",
            "dob": "1977-05-05",
            "sex": "M",
            "ssn_last4": "5050",
            "postal_code": "80202",
            "phone": "3035550101",
        }
        survivor = F.create_record(
            api, site["id"], "CA-1000", clinical_element_count=1, **demographics
        )
        second = F.create_record(
            api, site["id"], "CA-2000", clinical_element_count=1, **demographics
        )
        third = F.create_record(
            api, site["id"], "CA-3000", clinical_element_count=1, **demographics
        )
        first_pair = F.create_pair(
            api, survivor["id"], second["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        F.merge(
            api, first_pair["id"], survivor["id"], second["id"],
            rationale="First redundant chart.",
        )
        second_pair = F.create_pair(
            api, survivor["id"], third["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        F.merge(
            api, second_pair["id"], survivor["id"], third["id"],
            rationale="Second redundant chart.",
        )

        run = A.assert_created(
            F.run_metric(
                api, site["id"], "2026-08-01", "2026-08-01",
                attribution_variant=ATTRIBUTION_CREATION_SITE,
            )
        )

        A.assert_integer(run["records_created"], 3, "records_created")
        A.assert_integer(run["confirmed_duplicates"], 2, "confirmed_duplicates")
        A.assert_integer(run["duplicate_rate_bps"], 6667, "duplicate_rate_bps")
        assert run["sample_size_sufficient"] is False
        assert run["rule_set_version_label"] == RS_BASE_VERSION_LABEL
        cluster_head = F.get_record(api, survivor["id"])
        A.assert_integer(
            cluster_head["clinical_element_count"], 3, "clinical_element_count"
        )
        A.assert_integer(
            cluster_head["subsumed_member_count"], 2, "subsumed_member_count"
        )


BAND_WEIGHTS = {
    "last_name": 26.00,
    "first_name": 15.00,
    "dob": 25.00,
    "ssn_last4": 15.00,
    "sex": 5.00,
    "postal_code": 9.00,
    "phone": 5.00,
}


class TestBandMultiplierProvenance:
    def test_the_multiplier_stays_with_the_pre_evidence_band(self, api):
        """A P1 pair keeps 1.5 leverage even after the evidence drops it to P3.

        PRD §3.4: "A pair whose `base_band` is `P1` therefore has its evidence counted
        at one and a half times face value even if the evidence drags `effective_score`
        down into `P2` — the leverage belongs to the pre-evidence band."

        Design: Corner/calculations/evidence_multiplier_comes_from_base_band_not_priority_band
        """
        site = F.create_site(
            api, "SITE-C9", name="Band Multiplier Clinic", region_code="US-MA",
            registrar_headcount=4,
        )
        rule_set = F.create_rule_set(
            api, activate=False, name="Band Probe Rules", version_label="V-BAND-1",
            attribute_weights=BAND_WEIGHTS, auto_link_threshold=90.00,
            review_threshold=70.00, conflict_penalty_points=10.00,
        )
        record_a = F.create_record(
            api, site["id"], "C9-1000", "Fitzgerald", "Declan", "1968-02-29", "M",
            ssn_last4="3344", postal_code="02108", phone="6175550101",
            clinical_element_count=7,
        )
        record_b = F.create_record(
            api, site["id"], "C9-2000", "Fitzgerald", "Declan", "1968-02-29", "M",
            ssn_last4="3344", clinical_element_count=2,
        )
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        A.assert_score(pair["match_score"], 86.00, "match_score")
        assert pair["base_band"] == "P1"
        F.advance_to_under_review(
            api, pair["id"], "High score but the addresses do not line up."
        )
        F.add_evidence(
            api, pair["id"], "BIOMETRIC_COMPARE", OUTCOME_DISTINCT, 10.00,
            note="Fingerprints do not match.",
        )

        second = A.assert_created(
            api.add_evidence(
                pair["id"],
                f.evidence_payload(
                    "PHONE_VERIFICATION", OUTCOME_DISTINCT, 2.00,
                    note="Different household reached.",
                ),
                analyst_headers(),
            )
        )

        A.assert_score(second["weight_points"], 2.00, "weight_points")
        assert second["submitted_by_user_id"] == "analyst-1"
        final = F.get_pair(api, pair["id"])
        A.assert_score(final["evidence_points"], -12.00, "evidence_points")
        A.assert_score(final["evidence_adjustment"], -18.00, "evidence_adjustment")
        A.assert_score(final["effective_score"], 68.00, "effective_score")
        assert final["base_band"] == "P1"
        assert final["priority_band"] == "P3"
        A.assert_score(final["match_score"], 86.00, "match_score")
        A.assert_version(final, 5)


class TestIntegrityPrecedence:
    def test_fraud_outranks_remediation_and_falls_back_to_it_on_release(self, api):
        """First-match-wins, so closing the fraud hold reveals the open overlay again.

        PRD §2.9: "Because fraud outranks remediation, opening an investigation on a
        record that already has an open remediation moves the visible `integrity_state`
        to `FRAUD_SUSPECTED` while leaving the remediation itself untouched and still
        open — and when that investigation is later unsubstantiated, the still-open
        remediation pulls the record back down to `REMEDIATION_PENDING` rather than all
        the way to `CLEAR`."

        Design: Corner/calculations/integrity_state_precedence_puts_fraud_above_remediation
        """
        site = F.create_site(
            api, "SITE-CB", name="Precedence Clinic", region_code="US-NM",
            registrar_headcount=2,
        )
        record = F.create_record(
            api, site["id"], "CB-1000", "Delacroix", "Yvette", "1959-11-11", "F",
            ssn_last4="4040", postal_code="87501", phone="5055550101",
            clinical_element_count=10,
        )
        assert record["integrity_state"] == INTEGRITY_CLEAR
        overlay = F.create_overlay(
            api, record["id"], {"first_name": "Yvonne"}, 3, record["version"],
            encounter_from_date="2026-07-05", encounter_to_date="2026-07-06",
        )
        assert F.get_record(api, record["id"])["integrity_state"] == (
            INTEGRITY_REMEDIATION_PENDING
        )

        investigation = F.open_manual_investigation(
            api, record["id"], TRIGGER_MANUAL,
            note="Insurance card presented under another name.",
        )
        assert investigation["state"] == INVESTIGATION_OPEN
        assert investigation["opened_by"] == OPENED_BY_OFFICER
        assert investigation["opened_by_user_id"] == "officer-1"
        assert F.get_record(api, record["id"])["integrity_state"] == (
            INTEGRITY_FRAUD_SUSPECTED
        )
        A.assert_site_counters(F.get_site(api, site["id"]), flagged_record_count=1)

        released = A.assert_ok(
            api.unsubstantiate(
                investigation["id"],
                f.unsubstantiate_payload(
                    "The card belonged to a relative; no identity fraud."
                ),
                officer_headers(),
            )
        )

        assert released["state"] == INVESTIGATION_UNSUBSTANTIATED
        assert F.get_record(api, record["id"])["integrity_state"] == (
            INTEGRITY_REMEDIATION_PENDING
        )
        assert F.get_overlay(api, overlay["id"])["state"] == OVERLAY_DETECTED
        A.assert_site_counters(F.get_site(api, site["id"]), flagged_record_count=0)
