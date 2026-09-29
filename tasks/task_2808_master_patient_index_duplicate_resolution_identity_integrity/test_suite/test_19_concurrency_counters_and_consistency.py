"""Version discipline, re-derived counters, feature flags and same-request visibility.

The concerns collected here cut across every entity: which write may supersede
another, which rows carry a version at all, which counters are recomputed rather
than nudged, how one boolean on a consumer changes a merge's whole lifecycle, and
how much of the cascade the first response already knows about.
"""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import ERR_STALE_PAIR_VERSION
from test_helpers.constants import (
    ATTRIBUTION_CREATION_SITE,
    IDENTITY_ACTIVE,
    IDENTITY_MERGED_SUBSUMED,
    INTEGRITY_CLEAR,
    INTEGRITY_FRAUD_SUSPECTED,
    INTEGRITY_REMEDIATION_PENDING,
    MERGE_COMPLETED,
    MERGE_PENDING_PROPAGATION,
    MERGE_UNMERGED,
    OUTCOME_SAME_PERSON,
    PROPAGATION_MODE_BATCH,
    QUEUE_RECOMMENDED_MERGE,
    QUEUE_RESOLVED_MERGED,
    QUEUE_TRIAGED,
    REMEDIATION_OPEN,
    SCORE_VARIANT_STRICT,
    SCORE_VARIANT_TOLERANT,
    SOURCE_TYPE_MERGE,
    TASK_ACKED,
    TASK_QUEUED,
    TRIGGER_MANUAL,
)
from test_helpers.test_users import (
    STEWARD_2_USER_ID,
    admin_headers,
    analyst_headers,
    officer_headers,
    registrar_headers,
    steward_headers,
)

CA_DEMOGRAPHICS = {
    "last_name": "Bergstrom",
    "first_name": "Sonja",
    "dob": "1987-03-17",
    "sex": "F",
}


class TestRescoreConcurrency:
    def test_a_stale_expected_pair_version_is_refused_then_accepted(self, api):
        """Only the version rejects a rescore, and the queue is left where it stood.

        PRD §2.6: "Triage, starting review, attaching evidence, recording a
        recommendation and the fraud-escalation cascade all advance that `version`, so a
        client working from a stale read is rejected with `ERR_STALE_PAIR_VERSION`
        (HTTP 412) rather than silently overwriting a score computed from a state it
        never observed."

        PRD §3.3: "Re-scoring is not a queue transition: `queue_state` is left exactly
        as it was, and the operation is permitted only from `NEW`, `TRIAGED` or
        `UNDER_REVIEW`."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_pair_version_on_rescore_is_rejected_then_accepted
        """
        F.pin_clock(api, "2026-08-01T00:00:00Z")
        site = F.create_site(
            api, "CA-SITE", name="Concurrency Clinic", region_code="US-OR",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "CA-1000", ssn_last4="8585", postal_code="97201",
            phone="5035550101", clinical_element_count=3, **CA_DEMOGRAPHICS
        )
        record_b = F.create_record(
            api, site["id"], "CA-2000", clinical_element_count=1, **CA_DEMOGRAPHICS
        )
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        A.assert_score(pair["match_score"], 70.00, "match_score")
        A.assert_version(pair, 1)
        triaged = F.triage(api, pair["id"], triage_note="Queued for review.")
        A.assert_version(triaged, 2)

        stale = api.rescore_pair(
            pair["id"],
            f.rescore_payload(
                rule_set["id"], score_variant=SCORE_VARIANT_TOLERANT,
                expected_pair_version=pair["version"],
            ),
            analyst_headers(),
        )

        A.assert_error_envelope(stale, ERR_STALE_PAIR_VERSION, 412)
        refused = F.get_pair(api, pair["id"])
        assert refused["score_variant"] == SCORE_VARIANT_STRICT
        A.assert_score(refused["match_score"], 70.00, "match_score")
        assert refused["queue_state"] == QUEUE_TRIAGED
        A.assert_version(refused, 2)

        accepted = A.assert_ok(
            api.rescore_pair(
                pair["id"],
                f.rescore_payload(
                    rule_set["id"], score_variant=SCORE_VARIANT_TOLERANT,
                    expected_pair_version=triaged["version"],
                ),
                analyst_headers(),
            )
        )

        assert accepted["score_variant"] == SCORE_VARIANT_TOLERANT
        A.assert_score(accepted["match_score"], 77.50, "match_score")
        assert accepted["queue_state"] == QUEUE_TRIAGED
        A.assert_version(accepted, 3)
        assert accepted["triage_note"] == "Queued for review."


class TestVersionDiscipline:
    def test_every_write_bumps_one_version_and_event_rows_carry_none(self, api):
        """Even a refreshed counter is a write on its parent; event records have no version.

        PRD §2.4: "Most resources additionally carry three audit fields: `created_at`
        and `updated_at`, both ISO 8601 UTC timestamps rendered with exactly three
        fractional-second digits, and `version`, an integer that starts at 1 on creation
        and increases by exactly 1 on every mutation of that resource."

        PRD §2.4: "Three resource kinds are write-once event records and deliberately
        carry **only** `id` and `created_at` — they have neither `updated_at` nor
        `version`, and no endpoint mutates them after creation."

        Design: Corner/cross_cutting_complexity_layers/version_increments_exactly_once_per_write_and_immutable_rows_have_none
        """
        F.pin_clock(api, "2026-08-01T00:00:00Z")
        site = F.create_site(
            api, "CB-SITE", name="Version Clinic", region_code="US-WA",
            registrar_headcount=2,
        )
        A.assert_version(site, 1)
        draft = A.assert_created(
            api.create_rule_set(f.rule_set_payload(), admin_headers())
        )
        A.assert_version(draft, 1)
        activated = A.assert_ok(api.activate_rule_set(draft["id"], admin_headers()))
        A.assert_version(activated, 2)

        patched = A.assert_ok(
            api.patch_site(site["id"], {"registrar_headcount": 7}, admin_headers())
        )
        attempt = A.assert_created(
            api.create_search_attempt(
                site["id"], f.search_attempt_payload("Nakamura"),
                registrar_headers(site["id"]),
            )
        )
        record = F.create_record(
            api, site["id"], "CB-1000", "Nakamura", "Rei", "1998-12-01", "F",
            clinical_element_count=2,
        )
        after_record = F.get_site(api, site["id"])

        A.assert_version(patched, 2)
        A.assert_integer(patched["registrar_headcount"], 7, "registrar_headcount")
        assert "version" not in attempt
        assert "updated_at" not in attempt
        assert "id" in attempt and "created_at" in attempt
        assert "top_score" in attempt
        A.assert_version(record, 1)
        # PRD §3.5/§3.7/§3.9 enumerate the version-advancing rows exhaustively
        # ("Every row this touches advances its own `version` by 1: the subsumed
        # record, the survivor, and each re-pointed record") and list site
        # counter recomputation separately, without a version claim -- so
        # whether a derived-counter refresh advances the site's own `version` is
        # not uniquely determined. Only the counter value itself is.
        A.assert_site_counters(after_record, active_record_count=1)

        second = F.create_record(
            api, site["id"], "CB-2000", "Nakamura", "Rei", "1998-12-01", "F",
            clinical_element_count=1,
        )
        pair = F.create_pair(
            api, record["id"], second["id"], draft["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        F.advance_to_under_review(api, pair["id"], "Same name and date of birth.")
        evidence = A.assert_created(
            api.add_evidence(
                pair["id"],
                f.evidence_payload(
                    "PHOTO_ID", OUTCOME_SAME_PERSON, 4.00,
                    note="Same photograph on both charts.",
                ),
                analyst_headers(),
            )
        )
        metric_run = A.assert_created(
            F.run_metric(
                api, site["id"], "2026-07-01", "2026-07-31",
                attribution_variant=ATTRIBUTION_CREATION_SITE,
            )
        )

        assert "version" not in evidence
        assert "updated_at" not in evidence
        assert "created_at" in evidence
        assert "version" not in metric_run
        assert "updated_at" not in metric_run
        assert "created_at" in metric_run


class TestDerivedCounters:
    def test_the_counters_are_rederived_across_a_merge_a_flag_and_a_reversal(self, api):
        """active_record_count, subsumed_member_count and flagged_record_count all return.

        PRD §2.10: "Five counters are derived and must be reconciled with reality after
        any request that could change them; none of them is ever supplied by a client."

        PRD §3.7: "The subsumed record, the survivor and every re-pointed record each
        advance their own `version` by 1, and both sites' `active_record_count` values
        along with the affected `subsumed_member_count` values are recomputed."

        Design: Corner/cross_cutting_complexity_layers/site_counters_reconcile_across_create_merge_and_unmerge
        """
        F.pin_clock(api, "2026-08-01T00:00:00Z")
        site = F.create_site(
            api, "CC-SITE", name="Counter Clinic", region_code="US-CO",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        survivor, subsumed = F.create_identical_couple(
            api, site["id"], "CC-1000", "CC-2000", last_name="Malinowski",
            first_name="Zofia", dob="1976-10-06", sex="F", ssn_last4="9696",
            postal_code="80202", phone="3035550101", elements_a=4, elements_b=6,
        )
        before = F.get_site(api, site["id"])
        A.assert_site_counters(before, active_record_count=2, flagged_record_count=0)
        pair = F.create_pair(
            api, survivor["id"], subsumed["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        assert pair["queue_state"] == QUEUE_RECOMMENDED_MERGE
        assert pair["recommended_by_user_id"] is None

        merge_row = F.merge(
            api, pair["id"], survivor["id"], subsumed["id"], rationale="Same patient."
        )
        assert merge_row["state"] == MERGE_COMPLETED
        A.assert_integer(
            merge_row["moved_clinical_element_count"], 6,
            "moved_clinical_element_count",
        )
        A.assert_site_counters(
            F.get_site(api, site["id"]), active_record_count=1, flagged_record_count=0
        )
        A.assert_integer(
            F.get_record(api, survivor["id"])["subsumed_member_count"], 1,
            "subsumed_member_count",
        )

        investigation = F.open_manual_investigation(
            api, survivor["id"], TRIGGER_MANUAL, note="Spot check on the survivor."
        )
        A.assert_site_counters(F.get_site(api, site["id"]), flagged_record_count=1)
        assert F.get_record(api, survivor["id"])["integrity_state"] == (
            INTEGRITY_FRAUD_SUSPECTED
        )

        A.assert_ok(
            api.unsubstantiate(
                investigation["id"],
                f.unsubstantiate_payload("No fraud found."),
                officer_headers(),
            )
        )
        A.assert_site_counters(F.get_site(api, site["id"]), flagged_record_count=0)
        assert F.get_record(api, survivor["id"])["integrity_state"] == INTEGRITY_CLEAR

        reversed_merge = A.assert_ok(
            api.unmerge(
                merge_row["id"],
                f.unmerge_payload("Reversed after review."),
                steward_headers(STEWARD_2_USER_ID),
            )
        )

        assert reversed_merge["state"] == MERGE_UNMERGED
        A.assert_site_counters(
            F.get_site(api, site["id"]), active_record_count=2, flagged_record_count=0
        )
        restored_survivor = F.get_record(api, survivor["id"])
        A.assert_integer(
            restored_survivor["subsumed_member_count"], 0, "subsumed_member_count"
        )
        A.assert_integer(
            restored_survivor["clinical_element_count"], 4, "clinical_element_count"
        )
        restored_subsumed = F.get_record(api, subsumed["id"])
        A.assert_integer(
            restored_subsumed["clinical_element_count"], 6, "clinical_element_count"
        )
        assert restored_subsumed["identity_state"] == IDENTITY_ACTIVE


class TestAckRequiredFlag:
    def test_the_consumers_ack_flag_alone_decides_whether_the_merge_completes(self, api):
        """One boolean on the consumer, two different merge lifecycles.

        PRD §3.5: "A task for a system whose `ack_required` is true is minted in `state`
        of `QUEUED`; a task for a system whose `ack_required` is false is minted directly
        in `ACKED` and never occupies dispatch capacity at all."

        PRD §3.5: "It becomes `COMPLETED` immediately when `propagation_task_count` is
        0 — no active downstream system exists — or when none of the tasks it created
        belongs to a system requiring acknowledgement, since in both situations there is
        nothing left to wait for."

        Design: Corner/cross_cutting_complexity_layers/ack_required_flag_decides_whether_a_merge_completes_immediately
        """
        F.pin_clock(api, "2026-08-01T00:00:00Z")
        site = F.create_site(
            api, "CD-SITE", name="Flag Clinic", region_code="US-UT",
            registrar_headcount=4,
        )
        rule_set = F.create_rule_set(api, activate=False)
        fire_and_forget = F.create_system(
            api, "CD-FIRE", name="Fire And Forget Feed",
            propagation_mode=PROPAGATION_MODE_BATCH, ack_required=False,
            max_concurrent_dispatch=1,
        )
        couple_a = F.create_identical_couple(
            api, site["id"], "CD-1000", "CD-2000", last_name="Eriksen",
            first_name="Mads", dob="1968-04-23", sex="M", ssn_last4="0707",
            postal_code="84101", phone="8015550101", elements_a=3, elements_b=2,
        )
        couple_b = F.create_identical_couple(
            api, site["id"], "CD-3000", "CD-4000", last_name="Vasquez",
            first_name="Lupita", dob="1985-01-08", sex="F", ssn_last4="1818",
            postal_code="84102", phone="8015550202", elements_a=5, elements_b=1,
        )
        pair_a = F.create_pair(
            api, couple_a[0]["id"], couple_a[1]["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        merge_a = F.merge(
            api, pair_a["id"], couple_a[0]["id"], couple_a[1]["id"],
            rationale="Couple A, fire-and-forget consumer.",
        )

        assert merge_a["state"] == MERGE_COMPLETED
        A.assert_integer(
            merge_a["propagation_task_count"], 1, "propagation_task_count"
        )
        A.assert_instant(
            merge_a["completed_at"], "2026-08-01T00:00:00Z", "completed_at"
        )
        A.assert_instant(
            merge_a["reversal_deadline_at"], "2026-10-30T00:00:00Z",
            "reversal_deadline_at",
        )
        tasks_a = F.tasks_for_merge(api, merge_a["id"])
        assert len(tasks_a) == 1
        assert tasks_a[0]["state"] == TASK_ACKED
        A.assert_integer(tasks_a[0]["attempt_count"], 0, "attempt_count")
        assert tasks_a[0]["dispatch_window_start_at"] is None
        A.assert_integer(
            F.get_system(api, fire_and_forget["id"])["unacked_task_count"], 0,
            "unacked_task_count",
        )

        A.assert_ok(
            api.patch_system(
                fire_and_forget["id"], {"status": "PAUSED"}, admin_headers()
            )
        )
        acknowledging = F.create_system(
            api, "CD-ACK", name="Acknowledging Consumer",
            propagation_mode=PROPAGATION_MODE_BATCH, ack_required=True,
            max_concurrent_dispatch=1,
        )
        pair_b = F.create_pair(
            api, couple_b[0]["id"], couple_b[1]["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        merge_b = F.merge(
            api, pair_b["id"], couple_b[0]["id"], couple_b[1]["id"],
            rationale="Couple B, acknowledging consumer.",
        )

        assert merge_b["state"] == MERGE_PENDING_PROPAGATION
        A.assert_integer(
            merge_b["propagation_task_count"], 1, "propagation_task_count"
        )
        assert merge_b["completed_at"] is None
        assert merge_b["reversal_deadline_at"] is None
        tasks_b = F.tasks_for_merge(api, merge_b["id"])
        assert len(tasks_b) == 1
        assert tasks_b[0]["state"] == TASK_QUEUED
        assert tasks_b[0]["downstream_system_id"] == acknowledging["id"]
        A.assert_integer(
            F.get_system(api, acknowledging["id"])["unacked_task_count"], 1,
            "unacked_task_count",
        )
        assert F.get_record(api, couple_a[1]["id"])["identity_state"] == (
            IDENTITY_MERGED_SUBSUMED
        )
        assert F.get_record(api, couple_b[1]["id"])["identity_state"] == (
            IDENTITY_MERGED_SUBSUMED
        )


class TestImmediateConsistency:
    def test_the_merge_response_already_shows_every_cascaded_change(self, api):
        """Nothing lags: the first response and every read afterwards agree at once.

        PRD §3.5: "Before anything is mutated, two snapshots are taken, and they are the
        only reason a reversal can ever be exact: `moved_clinical_element_count` records
        the subsumed record's `clinical_element_count` as it stood before the move, and
        `subsumed_prior_enterprise_id` records the subsumed record's `enterprise_id` as
        it stood before the overwrite."

        PRD §3.5: "Two further consequences fire inside the same request."

        PRD §3.5: "The merge's own `state` resolves within this same request rather than
        later."

        Design: Corner/consistency_model/merge_response_reflects_every_cascaded_change_in_the_same_request
        """
        F.pin_clock(api, "2026-08-01T00:00:00Z")
        site = F.create_site(
            api, "CE-SITE", name="Immediate Consistency Clinic", region_code="US-NM",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        survivor, subsumed = F.create_identical_couple(
            api, site["id"], "CE-1000", "CE-2000", last_name="Abernathy",
            first_name="Roland", dob="1959-05-19", sex="M", ssn_last4="2020",
            postal_code="87102", phone="5055550101", elements_a=5, elements_b=30,
        )
        pair = F.create_pair(
            api, survivor["id"], subsumed["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        assert pair["queue_state"] == QUEUE_RECOMMENDED_MERGE
        assert survivor["enterprise_id"] != subsumed["enterprise_id"]

        merge_row = F.merge(
            api, pair["id"], survivor["id"], subsumed["id"],
            rationale="Same patient, immediate visibility check.",
        )

        assert merge_row["state"] == MERGE_COMPLETED
        A.assert_integer(
            merge_row["moved_clinical_element_count"], 30,
            "moved_clinical_element_count",
        )
        assert merge_row["subsumed_prior_enterprise_id"] == subsumed["enterprise_id"]
        assert merge_row["recompressed_record_mrns"] == []
        A.assert_integer(
            merge_row["propagation_task_count"], 0, "propagation_task_count"
        )
        A.assert_instant(
            merge_row["completed_at"], "2026-08-01T00:00:00Z", "completed_at"
        )
        A.assert_instant(
            merge_row["reversal_deadline_at"], "2026-10-30T00:00:00Z",
            "reversal_deadline_at",
        )

        kept = F.get_record(api, survivor["id"])
        A.assert_integer(kept["clinical_element_count"], 35, "clinical_element_count")
        A.assert_integer(kept["subsumed_member_count"], 1, "subsumed_member_count")
        assert kept["integrity_state"] == INTEGRITY_REMEDIATION_PENDING
        assert kept["identity_state"] == IDENTITY_ACTIVE
        absorbed = F.get_record(api, subsumed["id"])
        assert absorbed["identity_state"] == IDENTITY_MERGED_SUBSUMED
        A.assert_integer(
            absorbed["clinical_element_count"], 0, "clinical_element_count"
        )
        assert absorbed["survivor_record_id"] == survivor["id"]
        assert absorbed["enterprise_id"] == survivor["enterprise_id"]
        resolved = F.get_pair(api, pair["id"])
        assert resolved["queue_state"] == QUEUE_RESOLVED_MERGED
        assert resolved["approved_by_user_id"] == "steward-1"
        remediations = A.list_rows(
            api.list_remediations(
                officer_headers(), {"merge_operation_id": merge_row["id"]}
            ),
            expected_total=1,
        )
        assert len(remediations) == 1
        assert remediations[0]["source_type"] == SOURCE_TYPE_MERGE
        assert remediations[0]["state"] == REMEDIATION_OPEN
        A.assert_integer(
            remediations[0]["element_count_subject"], 30, "element_count_subject"
        )
        assert remediations[0]["record_id"] == survivor["id"]
        A.assert_site_counters(
            F.get_site(api, site["id"]), active_record_count=1, flagged_record_count=0
        )
