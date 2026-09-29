"""Cascades that reach rows the request never names."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.constants import (
    CONFLICT_SSN4,
    IDENTITY_ACTIVE,
    IDENTITY_MERGED_SUBSUMED,
    INTEGRITY_CLEAR,
    INTEGRITY_FRAUD_CONFIRMED,
    INTEGRITY_FRAUD_SUSPECTED,
    MERGE_COMPLETED,
    OPENED_BY_OFFICER,
    QUEUE_ESCALATED_FRAUD,
    QUEUE_NEW,
    SCORE_VARIANT_STRICT,
    TRIGGER_MANUAL,
)
from test_helpers.test_users import admin_headers, analyst_headers, officer_headers

CLUSTER_DEMOGRAPHICS = {
    "last_name": "Fitzgerald",
    "first_name": "Declan",
    "dob": "1981-07-04",
    "sex": "M",
    "ssn_last4": "7788",
    "postal_code": "02108",
    "phone": "6175550144",
}


def _two_hop_cluster(api):
    """A-3000 merged into A-2000 first, then A-2000 merged into A-1000."""
    site = F.create_site(
        api, "SITE-A", name="Atlas Registration", region_code="US-MA",
        registrar_headcount=7,
    )
    rule_set = F.create_rule_set(api, activate=False)
    record_a = F.create_record(
        api, site["id"], "A-1000", clinical_element_count=10, **CLUSTER_DEMOGRAPHICS
    )
    record_b = F.create_record(
        api, site["id"], "A-2000", clinical_element_count=20, **CLUSTER_DEMOGRAPHICS
    )
    record_c = F.create_record(
        api, site["id"], "A-3000", clinical_element_count=5, **CLUSTER_DEMOGRAPHICS
    )
    pair_bc = F.create_pair(
        api, record_b["id"], record_c["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_one = F.merge(
        api, pair_bc["id"], record_b["id"], record_c["id"],
        rationale="A-3000 duplicates A-2000; retain A-2000.",
    )
    pair_ab = F.create_pair(
        api, record_a["id"], record_b["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_two = F.merge(
        api, pair_ab["id"], record_a["id"], record_b["id"],
        rationale="A-2000 duplicates A-1000; collapse the cluster onto A-1000.",
    )
    return {
        "site": site,
        "records": (record_a, record_b, record_c),
        "merges": (merge_one, merge_two),
    }


class TestMergePathCompression:
    def test_the_second_merge_records_the_grandchild_in_its_compression_list(self, api):
        """Only the re-pointed record's mrn is captured, in the declared order.

        PRD §3.5: "The `mrn` values of exactly those re-pointed records are captured
        in `recompressed_record_mrns`, ordered by their `created_at` ascending and
        then by `mrn` ascending — an ordered list, because a reversal re-points
        precisely those records and no others."

        Design: Difficulty/transitive_cascade/merge_path_compression_repoints_grandchild_to_new_survivor
        """
        built = _two_hop_cluster(api)
        merge_one, merge_two = built["merges"]

        A.assert_integer(
            merge_one["moved_clinical_element_count"], 5,
            "moved_clinical_element_count",
        )
        assert merge_one["recompressed_record_mrns"] == []
        A.assert_integer(
            merge_two["moved_clinical_element_count"], 25,
            "moved_clinical_element_count",
        )
        assert merge_two["subsumed_prior_enterprise_id"] == "EID-SITE-A-A-2000"
        assert merge_two["recompressed_record_mrns"] == ["A-3000"]
        assert merge_two["state"] == MERGE_COMPLETED
        A.assert_integer(merge_two["propagation_task_count"], 0, "propagation_task_count")
        A.assert_instant(merge_two["completed_at"], "2026-08-01T00:00:00Z", "completed_at")
        A.assert_instant(
            merge_two["reversal_deadline_at"], "2026-10-30T00:00:00Z",
            "reversal_deadline_at",
        )

    def test_the_grandchild_is_re_pointed_and_re_keyed_without_being_named(self, api):
        """A-3000 follows A-2000 onto A-1000 although the request never mentions it.

        PRD §3.5: "Every patient record that was pointing at the subsumed record as
        its own survivor, and whose `identity_state` is `MERGED_SUBSUMED`, is
        re-pointed at the new survivor and has its `enterprise_id` set to the
        survivor's `enterprise_id`."

        Design: Difficulty/transitive_cascade/merge_path_compression_repoints_grandchild_to_new_survivor
        """
        built = _two_hop_cluster(api)
        record_a, record_b, record_c = built["records"]

        survivor = F.get_record(api, record_a["id"])
        child = F.get_record(api, record_b["id"])
        grandchild = F.get_record(api, record_c["id"])

        A.assert_integer(survivor["clinical_element_count"], 35, "clinical_element_count")
        A.assert_integer(survivor["subsumed_member_count"], 2, "subsumed_member_count")
        assert survivor["enterprise_id"] == "EID-SITE-A-A-1000"
        assert survivor["identity_state"] == IDENTITY_ACTIVE
        A.assert_integer(child["clinical_element_count"], 0, "clinical_element_count")
        assert child["identity_state"] == IDENTITY_MERGED_SUBSUMED
        assert child["survivor_record_id"] == record_a["id"]
        assert child["enterprise_id"] == "EID-SITE-A-A-1000"
        assert grandchild["survivor_record_id"] == record_a["id"]
        assert grandchild["enterprise_id"] == "EID-SITE-A-A-1000"
        A.assert_integer(grandchild["clinical_element_count"], 0, "clinical_element_count")

    def test_the_cluster_reads_back_as_a_star_around_the_final_survivor(self, api):
        """Two members point at A-1000 and none at the intermediate survivor.

        PRD §3.5: "The survivor's `subsumed_member_count` is then recomputed as the
        number of records pointing at it whose `identity_state` is
        `MERGED_SUBSUMED`, and both member sites' `active_record_count` values are
        recomputed, since the subsumed record has left the active population of its
        site."

        Design: Difficulty/transitive_cascade/merge_path_compression_repoints_grandchild_to_new_survivor
        """
        built = _two_hop_cluster(api)
        record_a, record_b, _ = built["records"]
        merge_two = built["merges"][1]

        pointing_at_a = A.list_rows(
            api.list_records(analyst_headers(), {"survivor_record_id": record_a["id"]})
        )
        pointing_at_b = A.list_rows(
            api.list_records(analyst_headers(), {"survivor_record_id": record_b["id"]})
        )

        assert len(pointing_at_a) == 2
        assert pointing_at_b == []
        A.assert_site_counters(
            F.get_site(api, built["site"]["id"]), active_record_count=1
        )
        remediations = A.list_rows(
            api.list_remediations(
                admin_headers(), {"merge_operation_id": merge_two["id"]}
            )
        )
        assert remediations == []
        assert F.get_record(api, record_a["id"])["integrity_state"] == INTEGRITY_CLEAR


def _fraud_cascade_setup(api):
    """One record under three pairs, two of which name it."""
    site = F.create_site(
        api, "SITE-FC", name="Fraud Cascade Clinic", region_code="US-NY",
        registrar_headcount=9,
    )
    rule_set = F.create_rule_set(api, activate=False)
    subject = F.create_record(
        api, site["id"], "FC-8001", "Achterberg", "Willem", "1959-03-14", "M",
        ssn_last4="4455", postal_code="10021", phone="2125550177",
        clinical_element_count=18,
    )
    near_one = F.create_record(
        api, site["id"], "FC-8002", "achterberg", "Will", "1959-03-14", "M",
        ssn_last4="4455", clinical_element_count=6,
    )
    near_two = F.create_record(
        api, site["id"], "FC-8003", "Achterberg", "Wim", "1959-03-14", "M",
        ssn_last4="4455", clinical_element_count=2,
    )
    unrelated = F.create_record(
        api, site["id"], "FC-8004", "Bergstrom", "Elsa", "1994-10-22", "F",
        ssn_last4="1199", postal_code="98101", phone="2065550188",
        clinical_element_count=4,
    )
    pair_one = F.create_pair(
        api, subject["id"], near_one["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    pair_two = F.create_pair(
        api, subject["id"], near_two["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    F.advance_to_under_review(
        api, pair_two["id"], "Same surname, DOB and national-identifier tail."
    )
    pair_three = F.create_pair(
        api, near_one["id"], unrelated["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    return {
        "site": site,
        "records": (subject, near_one, near_two, unrelated),
        "pairs": (pair_one, pair_two, pair_three),
    }


class TestSubstantiatedFraudCascade:
    def test_opening_a_manual_investigation_escalates_only_the_subject_s_pairs(
        self, api
    ):
        """Two pairs escalate from two different origin states; the third is untouched.

        PRD §3.9: "Every candidate pair having the subject as a member and sitting in
        `NEW`, `TRIAGED`, `UNDER_REVIEW`, `RECOMMENDED_MERGE` or
        `RECOMMENDED_DISTINCT` transitions to `ESCALATED_FRAUD`, each advancing its
        own `version` by 1."

        Design: Difficulty/transitive_cascade/substantiated_fraud_cascades_record_pair_and_site_counter
        """
        built = _fraud_cascade_setup(api)
        subject = built["records"][0]
        pair_one, pair_two, pair_three = built["pairs"]

        F.open_manual_investigation(
            api, subject["id"], TRIGGER_MANUAL,
            note="Two different insurance cards presented under the same identity at intake.",
        )

        assert F.get_pair(api, pair_one["id"])["queue_state"] == QUEUE_ESCALATED_FRAUD
        assert F.get_pair(api, pair_two["id"])["queue_state"] == QUEUE_ESCALATED_FRAUD
        assert F.get_pair(api, pair_three["id"])["queue_state"] == QUEUE_NEW
        held = F.get_record(api, subject["id"])
        assert held["integrity_state"] == INTEGRITY_FRAUD_SUSPECTED
        assert held["identity_state"] == IDENTITY_ACTIVE
        A.assert_site_counters(
            F.get_site(api, built["site"]["id"]), flagged_record_count=1
        )

    def test_a_manual_investigation_scores_only_its_site_component(self, api):
        """With no pair referenced the only live component is 2.00 site points.

        PRD §3.9: "The **conflict component** is 30.00 points for each entry in the
        referenced pair's `conflict_flags`, or 0.00 when no `pair_id` is referenced,
        as for a `MANUAL` investigation."

        Design: Difficulty/transitive_cascade/substantiated_fraud_cascades_record_pair_and_site_counter
        """
        built = _fraud_cascade_setup(api)
        subject = built["records"][0]

        investigation = F.open_manual_investigation(
            api, subject["id"], TRIGGER_MANUAL,
            note="Two different insurance cards presented under the same identity at intake.",
        )

        assert investigation["opened_by"] == OPENED_BY_OFFICER
        assert investigation["opened_by_user_id"] == "officer-1"
        assert investigation["pair_id"] is None
        A.assert_score(investigation["risk_score"], 2.00, "risk_score")

    def test_substantiating_hardens_the_hold_without_moving_the_counters(self, api):
        """FRAUD_SUSPECTED becomes FRAUD_CONFIRMED and the site totals hold steady.

        PRD §3.9: "The subject's `integrity_state` hardens `FRAUD_SUSPECTED →
        FRAUD_CONFIRMED`, the site's `flagged_record_count` is recomputed,
        `risk_score` is recomputed, and the same queue sweep runs again over the
        subject's pairs in `NEW`, `TRIAGED`, `UNDER_REVIEW`, `RECOMMENDED_MERGE` or
        `RECOMMENDED_DISTINCT`, with the two recommendation edges again clearing
        `recommended_by_user_id` and `recommendation`."

        Design: Difficulty/transitive_cascade/substantiated_fraud_cascades_record_pair_and_site_counter
        """
        built = _fraud_cascade_setup(api)
        subject, near_one, near_two, _ = built["records"]
        pair_three = built["pairs"][2]
        investigation = F.open_manual_investigation(
            api, subject["id"], TRIGGER_MANUAL,
            note="Two different insurance cards presented under the same identity at intake.",
        )

        substantiated = A.assert_ok(
            api.substantiate(
                investigation["id"],
                f.substantiate_payload(
                    "Identity theft confirmed by the special investigations unit."
                ),
                officer_headers(),
            )
        )

        assert substantiated["state"] == "SUBSTANTIATED"
        A.assert_score(substantiated["risk_score"], 2.00, "risk_score")
        assert (
            F.get_record(api, subject["id"])["integrity_state"]
            == INTEGRITY_FRAUD_CONFIRMED
        )
        A.assert_site_counters(
            F.get_site(api, built["site"]["id"]),
            active_record_count=4,
            flagged_record_count=1,
        )
        assert F.get_record(api, near_one["id"])["integrity_state"] == INTEGRITY_CLEAR
        assert F.get_record(api, near_two["id"])["integrity_state"] == INTEGRITY_CLEAR
        untouched = F.get_pair(api, pair_three["id"])
        assert untouched["queue_state"] == QUEUE_NEW
        assert untouched["conflict_flags"] == [CONFLICT_SSN4]
        A.assert_score(untouched["match_score"], 0.00, "match_score")
