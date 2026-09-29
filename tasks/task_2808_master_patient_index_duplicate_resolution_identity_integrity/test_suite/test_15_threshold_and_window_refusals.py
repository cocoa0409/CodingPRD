"""Counted minimums, stored flags and the instants a window closes.

Each case pins the refusal against the neighbouring value that is accepted, so
the boundary itself is what the test measures.
"""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import (
    ERR_DUPLICATE_CREATION_BLOCKED,
    ERR_INSUFFICIENT_REVIEW_EVIDENCE,
    ERR_PROPAGATION_WINDOW_EXPIRED,
    ERR_REASSIGN_TARGET_INVALID,
    ERR_REMEDIATION_COUNT_INVALID,
    ERR_REVERSAL_WINDOW_EXPIRED,
    ERR_SEARCH_ATTEMPT_EXPIRED,
)
from test_helpers.constants import (
    IDENTITY_ACTIVE,
    IDENTITY_MERGED_SUBSUMED,
    INTEGRITY_REMEDIATION_PENDING,
    MERGE_COMPLETED,
    MERGE_UNMERGED,
    OUTCOME_SAME_PERSON,
    PROPAGATION_MODE_SYNCHRONOUS,
    QUEUE_RECOMMENDED_MERGE,
    QUEUE_UNDER_REVIEW,
    RECOMMENDATION_MERGE,
    REMEDIATION_OPEN,
    REMEDIATION_QUARANTINED,
    REMEDIATION_REASSIGNED,
    SCORE_VARIANT_STRICT,
    TASK_QUEUED,
    TASK_SENT,
)
from test_helpers.test_users import (
    STEWARD_2_USER_ID,
    admin_headers,
    analyst_headers,
    officer_headers,
    registrar_headers,
    steward_headers,
)


class TestEvidenceFloor:
    def test_a_single_evidence_row_is_not_enough_to_recommend(self, api):
        """The byte-identical recommend succeeds once a second row is on file.

        PRD §2.8: "The number of review evidence entries attached to the pair is at
        least 2 — otherwise `ERR_INSUFFICIENT_REVIEW_EVIDENCE`, HTTP 422."

        Design: Corner/validations/recommending_with_one_evidence_row_returns_insufficient_review_evidence
        """
        site = F.create_site(
            api, "SITE-VF", name="Evidence Floor Clinic", region_code="US-MO",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "VF-1000", "Karlsson", "Bengt", "1963-05-21", "M",
            ssn_last4="1010", postal_code="63101", phone="3145550101",
            clinical_element_count=3,
        )
        record_b = F.create_record(
            api, site["id"], "VF-2000", "Karlsson", "Bengt", "1963-05-21", "M",
            clinical_element_count=1,
        )
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        F.advance_to_under_review(api, pair["id"], "Likely the same patient.")
        first_row = F.add_evidence(
            api, pair["id"], "INSURANCE_CARD", OUTCOME_SAME_PERSON, 5.00,
            note="Same member id.",
        )
        assert first_row["pair_id"] == pair["id"]

        refused = api.recommend(
            pair["id"], f.recommend_payload(RECOMMENDATION_MERGE), analyst_headers()
        )

        A.assert_error_envelope(refused, ERR_INSUFFICIENT_REVIEW_EVIDENCE, 422)
        held = F.get_pair(api, pair["id"])
        assert held["queue_state"] == QUEUE_UNDER_REVIEW
        A.assert_version(held, 4)
        assert held["recommendation"] is None
        assert held["recommended_by_user_id"] is None

        F.add_evidence(
            api, pair["id"], "PHOTO_ID", OUTCOME_SAME_PERSON, 5.00, note="Same face.",
        )
        accepted = A.assert_ok(
            api.recommend(
                pair["id"], f.recommend_payload(RECOMMENDATION_MERGE), analyst_headers()
            )
        )

        assert accepted["queue_state"] == QUEUE_RECOMMENDED_MERGE
        assert accepted["recommendation"] == RECOMMENDATION_MERGE
        assert accepted["recommended_by_user_id"] == "analyst-1"
        A.assert_score(accepted["evidence_points"], 10.00, "evidence_points")
        A.assert_score(accepted["evidence_adjustment"], 10.00, "evidence_adjustment")
        A.assert_score(accepted["effective_score"], 80.00, "effective_score")
        assert accepted["priority_band"] == "P2"
        A.assert_version(accepted, 6)
        rows = A.list_rows(
            api.list_evidence(pair["id"], admin_headers()), expected_total=2
        )
        assert len(rows) == 2


class TestBlockedCreationFlag:
    def test_a_search_that_found_the_patient_forbids_a_second_chart(self, api):
        """The refusal reads the flag stored on the cited attempt, not a fresh search.

        PRD §2.8: "The cited search attempt's `blocked_creation` is false — otherwise
        `ERR_DUPLICATE_CREATION_BLOCKED`, HTTP 409."

        Design: Corner/validations/creating_a_record_from_a_blocked_search_attempt_returns_duplicate_creation_blocked
        """
        site = F.create_site(
            api, "SITE-VG", name="Duplicate Prevention Clinic", region_code="US-TX",
            registrar_headcount=4,
        )
        F.create_rule_set(api, activate=True)
        F.create_record(
            api, site["id"], "VG-1000", "Chukwuma", "Ada", "1992-03-13", "F",
            ssn_last4="2323", postal_code="77002", phone="7135550101",
            clinical_element_count=3,
        )
        desk = registrar_headers(site["id"])
        blocked = A.assert_created(
            api.create_search_attempt(
                site["id"],
                f.search_attempt_payload(
                    "Chukwuma", searched_first_name="Ada",
                    searched_dob="1992-03-13", searched_sex="F",
                    searched_ssn_last4="2323", searched_postal_code="77002",
                    searched_phone="7135550101",
                ),
                desk,
            )
        )
        A.assert_score(blocked["top_score"], 100.00, "top_score")
        assert blocked["blocked_creation"] is True
        clear = A.assert_created(
            api.create_search_attempt(
                site["id"], f.search_attempt_payload("Wojciechowski"), desk
            )
        )
        A.assert_score(clear["top_score"], 0.00, "top_score")
        assert clear["blocked_creation"] is False
        assert clear["top_match_record_mrn"] is None

        refused = api.create_record(
            f.record_payload(
                site["id"], "VG-2000", "Chukwuma", "Ada", "1992-03-13", "F",
                ssn_last4="2323", postal_code="77002", phone="7135550101",
                clinical_element_count=1, origin_search_attempt_id=blocked["id"],
            ),
            desk,
        )
        accepted = api.create_record(
            f.record_payload(
                site["id"], "VG-3000", "Wojciechowski", "Tomasz", "1959-06-04", "M",
                clinical_element_count=1, origin_search_attempt_id=clear["id"],
            ),
            desk,
        )

        A.assert_error_envelope(refused, ERR_DUPLICATE_CREATION_BLOCKED, 409)
        created = A.assert_created(accepted)
        assert created["mrn"] == "VG-3000"
        assert created["origin_search_attempt_id"] == clear["id"]
        rows = A.list_rows(
            api.list_records(admin_headers(), {"site_id": site["id"]}),
            expected_total=2,
        )
        assert sorted(A.mrns(rows)) == ["VG-1000", "VG-3000"]
        A.assert_site_counters(F.get_site(api, site["id"]), active_record_count=2)

    def test_the_fifteen_minute_freshness_window_includes_its_last_instant(self, api):
        """The citation is accepted at exactly created_at plus fifteen minutes.

        PRD §2.8: "The current logical clock is no later than the cited search
        attempt's `created_at` plus 15 minutes — otherwise
        `ERR_SEARCH_ATTEMPT_EXPIRED`, HTTP 409."

        Design: Corner/validations/search_attempt_expiry_is_inclusive_at_the_ttl_boundary
        """
        site = F.create_site(
            api, "SITE-VH", name="TTL Clinic", region_code="US-NV",
            registrar_headcount=2,
        )
        F.create_rule_set(api, activate=True)
        desk = registrar_headers(site["id"])
        attempt = A.assert_created(
            api.create_search_attempt(
                site["id"],
                f.search_attempt_payload(
                    "Yamashita", searched_first_name="Kenji",
                    searched_dob="1979-07-17",
                ),
                desk,
            )
        )
        assert attempt["blocked_creation"] is False
        A.assert_instant(attempt["created_at"], "2026-08-01T00:00:00Z", "created_at")

        F.pin_clock(api, "2026-08-01T00:15:00Z")
        accepted = api.create_record(
            f.record_payload(
                site["id"], "VH-1000", "Yamashita", "Kenji", "1979-07-17", "M",
                clinical_element_count=1, origin_search_attempt_id=attempt["id"],
            ),
            desk,
        )
        F.pin_clock(api, "2026-08-01T00:16:00Z")
        refused = api.create_record(
            f.record_payload(
                site["id"], "VH-2000", "Yamashita", "Kenji", "1979-07-17", "M",
                clinical_element_count=1, origin_search_attempt_id=attempt["id"],
            ),
            desk,
        )

        created = A.assert_created(accepted)
        assert created["mrn"] == "VH-1000"
        A.assert_instant(created["created_at"], "2026-08-01T00:15:00Z", "created_at")
        A.assert_error_envelope(refused, ERR_SEARCH_ATTEMPT_EXPIRED, 409)
        rows = A.list_rows(
            api.list_records(admin_headers(), {"site_id": site["id"]}),
            expected_total=1,
        )
        assert A.mrns(rows) == ["VH-1000"]
        A.assert_site_counters(F.get_site(api, site["id"]), active_record_count=1)


COUPLE_A_VI = {
    "last_name": "Andrade",
    "first_name": "Beatriz",
    "dob": "1971-01-25",
    "sex": "F",
    "ssn_last4": "3535",
    "postal_code": "83702",
    "phone": "2085550101",
}

COUPLE_B_VI = {
    "last_name": "Kirkpatrick",
    "first_name": "Duncan",
    "dob": "1948-11-08",
    "sex": "M",
    "ssn_last4": "4646",
    "postal_code": "83704",
    "phone": "2085550202",
}


class TestReversalWindow:
    def test_a_reversal_is_admitted_on_its_deadline_and_refused_one_second_later(
        self, api
    ):
        """Two merges completed together diverge only by the clock they are undone at.

        PRD §2.8: "When the merge being reversed has `state` of `COMPLETED`, the
        current logical clock is no later than its `reversal_deadline_at` — otherwise
        `ERR_REVERSAL_WINDOW_EXPIRED`, HTTP 409."

        Design: Corner/validations/unmerge_at_the_reversal_deadline_is_allowed_but_one_second_later_is_not
        """
        site = F.create_site(
            api, "SITE-VI", name="Reversal Window Clinic", region_code="US-ID",
            registrar_headcount=4,
        )
        rule_set = F.create_rule_set(api, activate=False)
        survivor_a = F.create_record(
            api, site["id"], "VI-1000", clinical_element_count=3, **COUPLE_A_VI
        )
        subsumed_a = F.create_record(
            api, site["id"], "VI-2000", clinical_element_count=2, **COUPLE_A_VI
        )
        survivor_b = F.create_record(
            api, site["id"], "VI-3000", clinical_element_count=5, **COUPLE_B_VI
        )
        subsumed_b = F.create_record(
            api, site["id"], "VI-4000", clinical_element_count=4, **COUPLE_B_VI
        )
        pair_a = F.create_pair(
            api, survivor_a["id"], subsumed_a["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        merge_a = F.merge(
            api, pair_a["id"], survivor_a["id"], subsumed_a["id"],
            rationale="Couple A duplicate.",
        )
        pair_b = F.create_pair(
            api, survivor_b["id"], subsumed_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        merge_b = F.merge(
            api, pair_b["id"], survivor_b["id"], subsumed_b["id"],
            rationale="Couple B duplicate.",
        )
        assert merge_a["state"] == MERGE_COMPLETED
        A.assert_instant(
            merge_a["reversal_deadline_at"], "2026-10-30T00:00:00Z",
            "reversal_deadline_at",
        )

        F.pin_clock(api, "2026-10-30T00:00:00Z")
        on_time = A.assert_ok(
            api.unmerge(
                merge_a["id"],
                f.unmerge_payload("Reversed on the last permitted instant."),
                steward_headers(STEWARD_2_USER_ID),
            )
        )
        F.pin_clock(api, "2026-10-30T00:00:01Z")
        too_late = api.unmerge(
            merge_b["id"],
            f.unmerge_payload("One second too late."),
            steward_headers(STEWARD_2_USER_ID),
        )

        assert on_time["state"] == MERGE_UNMERGED
        A.assert_instant(on_time["unmerged_at"], "2026-10-30T00:00:00Z", "unmerged_at")
        A.assert_error_envelope(too_late, ERR_REVERSAL_WINDOW_EXPIRED, 409)
        intact = F.get_merge(api, merge_b["id"])
        assert intact["state"] == MERGE_COMPLETED
        assert intact["unmerged_at"] is None
        restored = F.get_record(api, subsumed_a["id"])
        assert restored["identity_state"] == IDENTITY_ACTIVE
        A.assert_integer(
            restored["clinical_element_count"], 2, "clinical_element_count"
        )
        still_absorbed = F.get_record(api, subsumed_b["id"])
        assert still_absorbed["identity_state"] == IDENTITY_MERGED_SUBSUMED
        A.assert_integer(
            still_absorbed["clinical_element_count"], 0, "clinical_element_count"
        )


class TestPropagationWindow:
    def test_a_dispatch_is_admitted_on_its_deadline_and_refused_one_second_later(
        self, api
    ):
        """Two sibling tasks from one correction differ only by dispatch instant.

        PRD §2.8: "The current logical clock is no later than the task's
        `propagation_deadline_at` — otherwise `ERR_PROPAGATION_WINDOW_EXPIRED`,
        HTTP 409."

        Design: Corner/validations/sending_a_task_after_its_propagation_deadline_returns_propagation_window_expired
        """
        site = F.create_site(
            api, "SITE-VJ", name="Propagation Deadline Clinic", region_code="US-MN",
            registrar_headcount=2,
        )
        system_a = F.create_system(
            api, "VJ-SYS-A", name="Core EHR",
            propagation_mode=PROPAGATION_MODE_SYNCHRONOUS, ack_required=True,
            max_concurrent_dispatch=2,
        )
        system_b = F.create_system(
            api, "VJ-SYS-B", name="Radiology PACS",
            propagation_mode=PROPAGATION_MODE_SYNCHRONOUS, ack_required=True,
            max_concurrent_dispatch=2,
        )
        record = F.create_record(
            api, site["id"], "VJ-1000", "Halvorsen", "Ingrid", "1984-02-19", "F",
            ssn_last4="5757", postal_code="55401", phone="6125550101",
            clinical_element_count=4,
        )
        overlay = F.create_overlay(
            api, record["id"],
            {"first_name": "Ingrid", "phone": "6125550999"}, 3, record["version"],
            encounter_from_date="2026-07-20", encounter_to_date="2026-07-22",
        )
        F.apply_overlay(api, overlay["id"])
        task_a = A.list_rows(
            api.list_tasks(admin_headers(), {"downstream_system_id": system_a["id"]}),
            expected_total=1,
        )[0]
        task_b = A.list_rows(
            api.list_tasks(admin_headers(), {"downstream_system_id": system_b["id"]}),
            expected_total=1,
        )[0]
        A.assert_instant(
            task_a["propagation_deadline_at"], "2026-08-02T00:00:00Z",
            "propagation_deadline_at",
        )
        assert task_a["state"] == TASK_QUEUED

        F.pin_clock(api, "2026-08-02T00:00:00Z")
        on_time = F.send_task(
            api, task_a["id"], "2026-08-02T00:00:00Z", "2026-08-02T01:00:00Z"
        )
        F.pin_clock(api, "2026-08-02T00:00:01Z")
        too_late = api.send_task(
            task_b["id"],
            f.send_payload("2026-08-02T00:00:00Z", "2026-08-02T01:00:00Z"),
            admin_headers(),
        )

        assert on_time["state"] == TASK_SENT
        A.assert_integer(on_time["attempt_count"], 1, "attempt_count")
        A.assert_version(on_time, 2)
        A.assert_error_envelope(too_late, ERR_PROPAGATION_WINDOW_EXPIRED, 409)
        undispatched = F.get_task(api, task_b["id"])
        assert undispatched["state"] == TASK_QUEUED
        A.assert_integer(undispatched["attempt_count"], 0, "attempt_count")
        assert undispatched["dispatch_window_start_at"] is None
        A.assert_version(undispatched, 1)
        A.assert_integer(
            F.get_system(api, system_a["id"])["unacked_task_count"], 1,
            "unacked_task_count",
        )


VK_DEMOGRAPHICS = {
    "last_name": "Nakagawa",
    "first_name": "Hideo",
    "dob": "1966-12-02",
    "sex": "M",
    "ssn_last4": "6868",
    "postal_code": "53703",
    "phone": "6085550101",
}

VL_DEMOGRAPHICS = {
    "last_name": "Oyelaran",
    "first_name": "Femi",
    "dob": "1990-08-11",
    "sex": "M",
    "ssn_last4": "7979",
    "postal_code": "50309",
    "phone": "5155550101",
}


def _merge_with_remediation(api, site, rule_set, prefix, demographics, survivor_elements):
    """Merge a 30-element chart into a small one, which opens a remediation."""
    survivor = F.create_record(
        api, site["id"], f"{prefix}-1000", clinical_element_count=survivor_elements,
        **demographics,
    )
    subsumed = F.create_record(
        api, site["id"], f"{prefix}-2000", clinical_element_count=30, **demographics
    )
    pair = F.create_pair(
        api, survivor["id"], subsumed["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_row = F.merge(
        api, pair["id"], survivor["id"], subsumed["id"],
        rationale="Same patient, second chart carries the encounters.",
    )
    remediation = A.list_rows(
        api.list_remediations(
            officer_headers(), {"merge_operation_id": merge_row["id"]}
        ),
        expected_total=1,
    )[0]
    return survivor, subsumed, merge_row, remediation


class TestRemediationCounts:
    def test_quarantining_more_than_the_subject_population_is_refused(self, api):
        """Exactly the subject count is admitted; one element more is not.

        PRD §2.8: "On a quarantine, `element_count_quarantined` does not exceed the
        remediation's `element_count_subject`; on a reassignment,
        `element_count_reassigned` does not exceed the remediation's
        `element_count_quarantined` — otherwise `ERR_REMEDIATION_COUNT_INVALID`,
        HTTP 422."

        Design: Corner/validations/quarantining_more_elements_than_the_subject_count_returns_remediation_count_invalid
        """
        site = F.create_site(
            api, "SITE-VK", name="Remediation Count Clinic", region_code="US-WI",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        survivor, _, merge_row, remediation = _merge_with_remediation(
            api, site, rule_set, "VK", VK_DEMOGRAPHICS, 2
        )
        A.assert_integer(
            merge_row["moved_clinical_element_count"], 30,
            "moved_clinical_element_count",
        )
        A.assert_integer(
            remediation["element_count_subject"], 30, "element_count_subject"
        )
        assert remediation["state"] == REMEDIATION_OPEN
        A.assert_integer(
            F.get_record(api, survivor["id"])["clinical_element_count"], 32,
            "clinical_element_count",
        )

        refused = api.quarantine(
            remediation["id"], f.quarantine_payload(31), officer_headers()
        )
        A.assert_error_envelope(refused, ERR_REMEDIATION_COUNT_INVALID, 422)
        held = F.get_remediation(api, remediation["id"])
        assert held["state"] == REMEDIATION_OPEN
        A.assert_integer(
            held["element_count_quarantined"], 0, "element_count_quarantined"
        )
        A.assert_version(held, 1)

        accepted = A.assert_ok(
            api.quarantine(
                remediation["id"], f.quarantine_payload(30), officer_headers()
            )
        )

        assert accepted["state"] == REMEDIATION_QUARANTINED
        A.assert_integer(
            accepted["element_count_quarantined"], 30, "element_count_quarantined"
        )
        A.assert_version(accepted, 2)
        untouched = F.get_record(api, survivor["id"])
        A.assert_integer(
            untouched["clinical_element_count"], 32, "clinical_element_count"
        )
        assert untouched["integrity_state"] == INTEGRITY_REMEDIATION_PENDING


class TestReassignTarget:
    def test_elements_cannot_be_refiled_inside_the_contaminated_cluster(self, api):
        """The cluster's own key is refused; an unrelated record's key is accepted.

        PRD §2.8: "`target_record_id` names a patient record whose `enterprise_id`
        differs from the remediated record's `enterprise_id`, because reassigned
        elements must leave the contaminated cluster — otherwise
        `ERR_REASSIGN_TARGET_INVALID`, HTTP 422."

        Design: Corner/validations/reassigning_into_the_same_enterprise_cluster_returns_reassign_target_invalid
        """
        site = F.create_site(
            api, "SITE-VL", name="Reassign Target Clinic", region_code="US-IA",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        survivor, _, _, remediation = _merge_with_remediation(
            api, site, rule_set, "VL", VL_DEMOGRAPHICS, 4
        )
        outsider = F.create_record(
            api, site["id"], "VL-3000", "Przybylski", "Marta", "1955-03-29", "F",
            ssn_last4="8080", postal_code="50310", phone="5155550202",
            clinical_element_count=5,
        )
        assert remediation["record_id"] == survivor["id"]
        quarantined = A.assert_ok(
            api.quarantine(
                remediation["id"], f.quarantine_payload(30), officer_headers()
            )
        )
        A.assert_integer(
            quarantined["element_count_quarantined"], 30, "element_count_quarantined"
        )

        refused = api.reassign(
            remediation["id"],
            f.reassign_payload(survivor["id"], 10),
            officer_headers(),
        )
        A.assert_error_envelope(refused, ERR_REASSIGN_TARGET_INVALID, 422)
        held = F.get_remediation(api, remediation["id"])
        assert held["state"] == REMEDIATION_QUARANTINED
        A.assert_integer(
            held["element_count_reassigned"], 0, "element_count_reassigned"
        )
        assert held["reassigned_to_record_mrn"] is None

        accepted = A.assert_ok(
            api.reassign(
                remediation["id"],
                f.reassign_payload(outsider["id"], 10),
                officer_headers(),
            )
        )

        assert accepted["state"] == REMEDIATION_REASSIGNED
        A.assert_integer(
            accepted["element_count_reassigned"], 10, "element_count_reassigned"
        )
        assert accepted["reassigned_to_record_mrn"] == "VL-3000"
        refiled = F.get_record(api, outsider["id"])
        A.assert_integer(
            refiled["clinical_element_count"], 15, "clinical_element_count"
        )
        assert refiled["enterprise_id"] == outsider["enterprise_id"]
        drained = F.get_record(api, survivor["id"])
        A.assert_integer(
            drained["clinical_element_count"], 24, "clinical_element_count"
        )
