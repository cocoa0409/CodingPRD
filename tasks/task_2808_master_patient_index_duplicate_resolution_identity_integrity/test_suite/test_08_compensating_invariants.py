"""Reversals that must give back exactly what the merge took."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.constants import (
    CLOSED_BY_UNMERGE,
    IDENTITY_ACTIVE,
    IDENTITY_MERGED_SUBSUMED,
    INTEGRITY_CLEAR,
    INTEGRITY_REMEDIATION_PENDING,
    MERGE_COMPLETED,
    MERGE_PENDING_PROPAGATION,
    MERGE_UNMERGED,
    OPERATION_MERGE,
    OPERATION_UNMERGE,
    QUEUE_UNDER_REVIEW,
    REMEDIATION_CLOSED,
    REMEDIATION_OPEN,
    SCORE_VARIANT_STRICT,
    SOURCE_TYPE_MERGE,
    TASK_CANCELLED,
    TASK_QUEUED,
)
from test_helpers.test_users import (
    STEWARD_2_USER_ID,
    admin_headers,
    analyst_headers,
    officer_headers,
    steward_headers,
)

CONSERVATION_DEMOGRAPHICS = {
    "last_name": "Ibarra",
    "first_name": "Rosalia",
    "dob": "1968-09-30",
    "sex": "F",
    "ssn_last4": "9090",
    "postal_code": "55401",
    "phone": "6125550111",
}

REVERSAL_REASON = (
    "Chart review proved A-2000 is a different patient with the same demographics."
)


def _two_level_cluster(api):
    """A-3000 under A-2000, then A-2000 under A-1000, with no consumer registered."""
    site = F.create_site(
        api, "SITE-A", name="Conservation Clinic", region_code="US-MN",
        registrar_headcount=5,
    )
    rule_set = F.create_rule_set(api, activate=False)
    record_a = F.create_record(
        api, site["id"], "A-1000", clinical_element_count=10,
        **CONSERVATION_DEMOGRAPHICS
    )
    record_b = F.create_record(
        api, site["id"], "A-2000", clinical_element_count=20,
        **CONSERVATION_DEMOGRAPHICS
    )
    record_c = F.create_record(
        api, site["id"], "A-3000", clinical_element_count=5,
        **CONSERVATION_DEMOGRAPHICS
    )
    pair_bc = F.create_pair(
        api, record_b["id"], record_c["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_one = F.merge(
        api, pair_bc["id"], record_b["id"], record_c["id"],
        rationale="A-3000 is a duplicate registration of A-2000.",
    )
    pair_ab = F.create_pair(
        api, record_a["id"], record_b["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_two = F.merge(
        api, pair_ab["id"], record_a["id"], record_b["id"],
        rationale="A-2000 and its cluster belong under the oldest identity A-1000.",
    )
    return {
        "site": site,
        "records": (record_a, record_b, record_c),
        "pairs": (pair_bc, pair_ab),
        "merges": (merge_one, merge_two),
    }


def _cluster_elements(api, records):
    return sum(
        F.get_record(api, record["id"])["clinical_element_count"]
        for record in records
    )


def _distinct_active_enterprise_ids(api, records):
    rows = [F.get_record(api, record["id"]) for record in records]
    return {
        row["enterprise_id"]
        for row in rows
        if row["identity_state"] == IDENTITY_ACTIVE
    }


class TestUnmergeRestoresTheCluster:
    def test_the_reversal_moves_exactly_the_snapshotted_quantity_back(self, api):
        """35 elements before the merge and 35 after the reversal, row by row.

        PRD §3.7: "Exactly `moved_clinical_element_count` elements move back: that
        quantity is subtracted from the survivor's `clinical_element_count` and added
        to the subsumed record's, restoring the snapshot value."

        Design: Difficulty/compensating_invariant/unmerge_restores_cluster_elements_and_enterprise_ids
        """
        built = _two_level_cluster(api)
        record_a, record_b, record_c = built["records"]
        merge_two = built["merges"][1]
        A.assert_integer(
            merge_two["moved_clinical_element_count"], 25,
            "moved_clinical_element_count",
        )
        assert merge_two["subsumed_prior_enterprise_id"] == "EID-SITE-A-A-2000"
        assert merge_two["recompressed_record_mrns"] == ["A-3000"]
        A.assert_integer(_cluster_elements(api, built["records"]), 35, "cluster total")

        reversed_merge = A.assert_ok(
            api.unmerge(
                merge_two["id"],
                f.unmerge_payload(REVERSAL_REASON),
                steward_headers(STEWARD_2_USER_ID),
            )
        )

        assert reversed_merge["state"] == MERGE_UNMERGED
        A.assert_instant(
            reversed_merge["unmerged_at"], "2026-08-01T00:00:00Z", "unmerged_at"
        )
        assert reversed_merge["unmerge_reason"] == REVERSAL_REASON
        A.assert_integer(
            F.get_record(api, record_a["id"])["clinical_element_count"], 10,
            "clinical_element_count",
        )
        A.assert_integer(
            F.get_record(api, record_b["id"])["clinical_element_count"], 25,
            "clinical_element_count",
        )
        A.assert_integer(
            F.get_record(api, record_c["id"])["clinical_element_count"], 0,
            "clinical_element_count",
        )
        A.assert_integer(_cluster_elements(api, built["records"]), 35, "cluster total")

    def test_the_restored_record_carries_back_its_exact_prior_key(self, api):
        """One enterprise identity is returned, not a freshly computed one.

        PRD §3.7: "The subsumed record moves `MERGED_SUBSUMED → ACTIVE`, has its
        `survivor_record_id` cleared to null, and has its `enterprise_id` restored
        from `subsumed_prior_enterprise_id` — byte for byte the key it carried before,
        not a recomputed one."

        Design: Difficulty/compensating_invariant/unmerge_restores_cluster_elements_and_enterprise_ids
        """
        built = _two_level_cluster(api)
        record_a, record_b, record_c = built["records"]
        merge_two = built["merges"][1]
        assert _distinct_active_enterprise_ids(api, built["records"]) == {
            "EID-SITE-A-A-1000"
        }

        A.assert_ok(
            api.unmerge(
                merge_two["id"],
                f.unmerge_payload(REVERSAL_REASON),
                steward_headers(STEWARD_2_USER_ID),
            )
        )

        restored = F.get_record(api, record_b["id"])
        assert restored["identity_state"] == IDENTITY_ACTIVE
        assert restored["survivor_record_id"] is None
        assert restored["enterprise_id"] == "EID-SITE-A-A-2000"
        assert F.get_record(api, record_a["id"])["enterprise_id"] == "EID-SITE-A-A-1000"
        assert _distinct_active_enterprise_ids(api, built["records"]) == {
            "EID-SITE-A-A-1000",
            "EID-SITE-A-A-2000",
        }
        assert F.get_record(api, record_c["id"])["identity_state"] == (
            IDENTITY_MERGED_SUBSUMED
        )

    def test_the_grandchild_follows_its_restored_parent(self, api):
        """A-3000 is re-pointed back to A-2000 and re-keyed to A-2000's key.

        PRD §3.7: "Every record whose `mrn` appears in `recompressed_record_mrns` is
        re-pointed from the survivor back to the subsumed record, in the stored order,
        with `enterprise_id` set to the subsumed record's restored key."

        Design: Difficulty/compensating_invariant/unmerge_restores_cluster_elements_and_enterprise_ids
        """
        built = _two_level_cluster(api)
        record_a, record_b, record_c = built["records"]
        merge_two = built["merges"][1]

        A.assert_ok(
            api.unmerge(
                merge_two["id"],
                f.unmerge_payload(REVERSAL_REASON),
                steward_headers(STEWARD_2_USER_ID),
            )
        )

        grandchild = F.get_record(api, record_c["id"])
        assert grandchild["survivor_record_id"] == record_b["id"]
        assert grandchild["enterprise_id"] == "EID-SITE-A-A-2000"
        A.assert_integer(
            F.get_record(api, record_a["id"])["subsumed_member_count"], 0,
            "subsumed_member_count",
        )
        A.assert_integer(
            F.get_record(api, record_b["id"])["subsumed_member_count"], 1,
            "subsumed_member_count",
        )
        A.assert_site_counters(
            F.get_site(api, built["site"]["id"]), active_record_count=2
        )

    def test_the_authorising_pair_re_opens_and_the_earlier_merge_stands(self, api):
        """Reversing the second merge must not disturb the first one.

        PRD §3.7: "The authorising pair moves `RESOLVED_MERGED → UNDER_REVIEW`, with
        `recommended_by_user_id`, `recommendation` and `approved_by_user_id` all
        cleared to null and the pair's `version` advanced by 1 — the work item is
        genuinely re-opened, awaiting a fresh analyst verdict."

        Design: Difficulty/compensating_invariant/unmerge_restores_cluster_elements_and_enterprise_ids
        """
        built = _two_level_cluster(api)
        pair_ab = built["pairs"][1]
        merge_one, merge_two = built["merges"]

        A.assert_ok(
            api.unmerge(
                merge_two["id"],
                f.unmerge_payload(REVERSAL_REASON),
                steward_headers(STEWARD_2_USER_ID),
            )
        )

        re_opened = F.get_pair(api, pair_ab["id"])
        assert re_opened["queue_state"] == QUEUE_UNDER_REVIEW
        assert re_opened["recommendation"] is None
        assert re_opened["recommended_by_user_id"] is None
        assert re_opened["approved_by_user_id"] is None
        assert F.get_merge(api, merge_one["id"])["state"] == MERGE_COMPLETED


R_DEMOGRAPHICS = {
    "last_name": "Vasquez",
    "first_name": "Camila",
    "dob": "1984-04-07",
    "sex": "F",
    "ssn_last4": "6262",
    "postal_code": "89101",
    "phone": "7025550122",
}

DOWNTIME_REASON = (
    "Downtime reconciliation showed two genuinely distinct patients."
)


def _merge_with_open_remediation(api):
    """A PENDING_PROPAGATION merge that moved 30 elements and opened a remediation."""
    site = F.create_site(
        api, "SITE-R", name="Remediation Clinic", region_code="US-NV",
        registrar_headcount=3,
    )
    rule_set = F.create_rule_set(api, activate=False)
    system = F.create_system(
        api, "REG-MIRROR", name="Registration Mirror", ack_required=True,
        max_concurrent_dispatch=2,
    )
    survivor = F.create_record(
        api, site["id"], "R-1000", clinical_element_count=4, **R_DEMOGRAPHICS
    )
    subsumed = F.create_record(
        api, site["id"], "R-2000", clinical_element_count=30, **R_DEMOGRAPHICS
    )
    pair = F.create_pair(
        api, survivor["id"], subsumed["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_row = F.merge(
        api, pair["id"], survivor["id"], subsumed["id"],
        rationale="Second registration created during a downtime event.",
    )
    remediation = A.list_rows(
        api.list_remediations(officer_headers(), {"merge_operation_id": merge_row["id"]})
    )[0]
    task = F.first_task_for_merge(api, merge_row["id"])
    return {
        "site": site,
        "system": system,
        "records": (survivor, subsumed),
        "pair": pair,
        "merge": merge_row,
        "remediation": remediation,
        "task": task,
    }


class TestUnmergeCompensatesTheSideEffects:
    def test_the_reversal_closes_the_remediation_the_merge_opened(self, api):
        """The system writes the closure note itself and the hold is lifted.

        PRD §3.7: "Any contamination remediation that this merge opened and that is
        still in `OPEN`, `QUARANTINED` or `REASSIGNED` is closed: it moves to
        `CLOSED`, its `closure_note` is written by the system as the exact text
        `CLOSED_BY_UNMERGE`, its `version` advances by 1, and the survivor's
        `integrity_state` is re-derived, which returns it to `CLEAR` when nothing else
        holds it."

        Design: Difficulty/compensating_invariant/unmerge_closes_merge_remediation_and_cancels_queued_task
        """
        built = _merge_with_open_remediation(api)
        survivor = built["records"][0]
        remediation = built["remediation"]
        assert built["merge"]["state"] == MERGE_PENDING_PROPAGATION
        A.assert_integer(
            built["merge"]["moved_clinical_element_count"], 30,
            "moved_clinical_element_count",
        )
        assert remediation["source_type"] == SOURCE_TYPE_MERGE
        assert remediation["state"] == REMEDIATION_OPEN
        A.assert_integer(
            remediation["element_count_subject"], 30, "element_count_subject"
        )
        assert remediation["record_id"] == survivor["id"]
        held = F.get_record(api, survivor["id"])
        assert held["integrity_state"] == INTEGRITY_REMEDIATION_PENDING
        A.assert_integer(held["clinical_element_count"], 34, "clinical_element_count")

        A.assert_ok(
            api.unmerge(
                built["merge"]["id"],
                f.unmerge_payload(DOWNTIME_REASON),
                admin_headers(),
            )
        )

        closed = F.get_remediation(api, remediation["id"])
        assert closed["state"] == REMEDIATION_CLOSED
        assert closed["closure_note"] == CLOSED_BY_UNMERGE
        assert F.get_record(api, survivor["id"])["integrity_state"] == INTEGRITY_CLEAR

    def test_the_queued_task_is_cancelled_and_a_reversal_task_is_raised(self, api):
        """The consumer is told to undo, and the stale instruction stops holding a slot.

        PRD §3.7: "And propagation is re-driven: every task belonging to this merge
        whose `state` is `QUEUED` or `FAILED` moves to `CANCELLED` with its `version`
        advanced by 1 and the consumer's `unacked_task_count` reduced accordingly,
        while one fresh task with `operation_kind` of `UNMERGE` is raised per
        downstream system whose `status` is `ACTIVE`, following exactly the same
        acknowledgement rule as merge fan-out — `QUEUED` where the consumer requires
        acknowledgement, directly `ACKED` where it does not."

        Design: Difficulty/compensating_invariant/unmerge_closes_merge_remediation_and_cancels_queued_task
        """
        built = _merge_with_open_remediation(api)
        merge_id = built["merge"]["id"]
        assert built["task"]["state"] == TASK_QUEUED
        assert built["task"]["operation_kind"] == OPERATION_MERGE

        A.assert_ok(
            api.unmerge(
                merge_id, f.unmerge_payload(DOWNTIME_REASON), admin_headers()
            )
        )

        assert F.get_task(api, built["task"]["id"])["state"] == TASK_CANCELLED
        rows = F.tasks_for_merge(api, merge_id)
        assert len(rows) == 2
        replacement = [
            row for row in rows if row["operation_kind"] == OPERATION_UNMERGE
        ]
        assert len(replacement) == 1
        assert replacement[0]["state"] == TASK_QUEUED
        A.assert_integer(
            F.get_system(api, built["system"]["id"])["unacked_task_count"], 1,
            "unacked_task_count",
        )

    def test_the_elements_and_the_identity_return_to_the_second_record(self, api):
        """A merge lowers the distinct active key count by one and the reversal restores it.

        PRD §3.7: "The second is **enterprise identity conservation**: counting the
        distinct `enterprise_id` values across all patient records whose
        `identity_state` is `ACTIVE`, enterprise-wide, gives the same integer
        immediately before the merge as immediately after the reversal, and the
        restored record's `enterprise_id` equals `subsumed_prior_enterprise_id`
        exactly."

        Design: Difficulty/compensating_invariant/unmerge_closes_merge_remediation_and_cancels_queued_task
        """
        built = _merge_with_open_remediation(api)
        survivor, subsumed = built["records"]

        A.assert_ok(
            api.unmerge(
                built["merge"]["id"],
                f.unmerge_payload(DOWNTIME_REASON),
                admin_headers(),
            )
        )

        A.assert_integer(
            F.get_record(api, survivor["id"])["clinical_element_count"], 4,
            "clinical_element_count",
        )
        restored = F.get_record(api, subsumed["id"])
        A.assert_integer(
            restored["clinical_element_count"], 30, "clinical_element_count"
        )
        assert restored["identity_state"] == IDENTITY_ACTIVE
        assert restored["enterprise_id"] == "EID-SITE-R-R-2000"
        assert _distinct_active_enterprise_ids(api, built["records"]) == {
            "EID-SITE-R-R-1000",
            "EID-SITE-R-R-2000",
        }
        assert F.get_pair(api, built["pair"]["id"])["queue_state"] == QUEUE_UNDER_REVIEW
        A.assert_site_counters(
            F.get_site(api, built["site"]["id"]), active_record_count=2
        )
