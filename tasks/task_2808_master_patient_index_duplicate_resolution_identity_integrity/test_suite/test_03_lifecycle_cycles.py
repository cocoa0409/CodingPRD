"""Queue and dispatch lifecycles that re-enter a state they have already left."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.constants import (
    CLASSIFICATION_POTENTIAL_DUPLICATE,
    OPERATION_OVERLAY_CORRECTION,
    OUTCOME_INCONCLUSIVE,
    QUEUE_RECOMMENDED_MERGE,
    QUEUE_UNDER_REVIEW,
    RECOMMENDATION_MERGE,
    SCORE_VARIANT_STRICT,
    TASK_FAILED,
    TASK_SENT,
)
from test_helpers.test_users import (
    ANALYST_2_USER_ID,
    admin_headers,
    analyst_headers,
    steward_headers,
)

RETURN_NOTE = "Evidence is inconclusive; obtain a fresh photo ID before recommending."


def _recommended_pair(api):
    """A 77.50 POTENTIAL_DUPLICATE pair recommended once by analyst-1."""
    site = F.create_site(
        api, "SITE-CY", name="Cycle Review Clinic", region_code="US-NY",
        registrar_headcount=8,
    )
    rule_set = F.create_rule_set(api, activate=False)
    record_a = F.create_record(
        api, site["id"], "CY-6001", "Kowalski", "Barbara", "1975-05-30", "F",
        ssn_last4="9021", clinical_element_count=12,
    )
    record_b = F.create_record(
        api, site["id"], "CY-6002", "kowalski", "Barb", "1975-05-30", "F",
        ssn_last4="9021", clinical_element_count=3,
    )
    pair = F.create_pair(
        api, record_a["id"], record_b["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    F.advance_to_under_review(
        api, pair["id"], "Same surname and DOB; queueing for manual review."
    )
    F.add_evidence(
        api, pair["id"], "PHOTO_ID", OUTCOME_INCONCLUSIVE, 1.00,
        note="Photo on file is 12 years old.",
    )
    F.add_evidence(
        api, pair["id"], "PHONE_VERIFICATION", OUTCOME_INCONCLUSIVE, 1.00,
        note="Number disconnected.",
    )
    recommended = F.recommend(api, pair["id"], RECOMMENDATION_MERGE)
    return pair, recommended


class TestRecommendReturnRecommendCycle:
    def test_the_back_edge_clears_the_recommendation_and_its_author(self, api):
        """An approver's return-to-review destroys the verdict rather than editing it.

        PRD §3.4: "Both clear `recommendation` and `recommended_by_user_id` back to
        null, which forces a fresh analyst verdict and simultaneously releases the
        duty-separation lock, so the same analyst who recommended before may
        recommend again, and the returning approver is no longer barred from
        executing the eventual resolution."

        Design: Difficulty/non_linear_state_machine/pair_queue_recommend_return_recommend_cycle
        """
        pair, recommended = _recommended_pair(api)
        assert recommended["queue_state"] == QUEUE_RECOMMENDED_MERGE

        returned = A.assert_ok(
            api.return_to_review(
                pair["id"],
                f.return_to_review_payload(triage_note=RETURN_NOTE),
                steward_headers(),
            )
        )

        assert returned["queue_state"] == QUEUE_UNDER_REVIEW
        assert returned["recommended_by_user_id"] is None
        assert returned["recommendation"] is None

    def test_a_second_analyst_re_enters_the_recommended_state_on_version_eight(
        self, api
    ):
        """The queue lands back where it was, but the version count is monotonic.

        PRD §3.4: "Both branches behave identically in every other respect: the
        analyst's operator identifier is written to `recommended_by_user_id`,
        `recommendation` records the submitted verdict, and the pair's `version`
        advances by 1."

        Design: Difficulty/non_linear_state_machine/pair_queue_recommend_return_recommend_cycle
        """
        pair, _ = _recommended_pair(api)
        A.assert_ok(
            api.return_to_review(
                pair["id"],
                f.return_to_review_payload(triage_note=RETURN_NOTE),
                steward_headers(),
            )
        )

        second = F.recommend(
            api, pair["id"], RECOMMENDATION_MERGE,
            headers=analyst_headers(ANALYST_2_USER_ID),
        )

        assert second["queue_state"] == QUEUE_RECOMMENDED_MERGE
        assert second["recommended_by_user_id"] == ANALYST_2_USER_ID
        assert second["recommendation"] == RECOMMENDATION_MERGE
        A.assert_version(second, 8)
        assert second["approved_by_user_id"] is None

    def test_the_append_only_evidence_rows_survive_the_loop(self, api):
        """Two inconclusive rows still satisfy the two-entry rule on the second pass.

        PRD §3.4: "A pair with fewer than two entries is rejected with
        `ERR_INSUFFICIENT_REVIEW_EVIDENCE` — a single photograph is not a defensible
        basis for collapsing two clinical histories into one."

        Design: Difficulty/non_linear_state_machine/pair_queue_recommend_return_recommend_cycle
        """
        pair, _ = _recommended_pair(api)
        A.assert_ok(
            api.return_to_review(
                pair["id"],
                f.return_to_review_payload(triage_note=RETURN_NOTE),
                steward_headers(),
            )
        )
        F.recommend(
            api, pair["id"], RECOMMENDATION_MERGE,
            headers=analyst_headers(ANALYST_2_USER_ID),
        )

        rows = A.list_rows(
            api.list_evidence(pair["id"], analyst_headers()), expected_total=2
        )
        assert len(rows) == 2
        final = F.get_pair(api, pair["id"])
        A.assert_score(final["match_score"], 77.50, "match_score")
        assert final["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert final["base_band"] == "P2"
        A.assert_score(final["evidence_points"], 0.00, "evidence_points")
        A.assert_score(final["evidence_adjustment"], 0.00, "evidence_adjustment")
        A.assert_score(final["effective_score"], 77.50, "effective_score")
        assert final["priority_band"] == "P2"


def _queued_overlay_task(api):
    """One QUEUED OVERLAY_CORRECTION task on a BATCH consumer with spare capacity."""
    site = F.create_site(
        api, "SITE-PR", name="Propagation Retry Clinic", region_code="US-TX",
        registrar_headcount=3,
    )
    system = F.create_system(
        api, "EHR-CORE", name="Core EHR", ack_required=True,
        max_concurrent_dispatch=3,
    )
    record = F.create_record(
        api, site["id"], "PR-4001", "Villanueva", "Rosa", "1968-04-17", "F",
        ssn_last4="3311", postal_code="78701", phone="5125550133",
        clinical_element_count=10,
    )
    overlay = F.create_overlay(
        api, record["id"], {"last_name": "Villanueva-Ortiz"}, 4, record["version"],
        encounter_from_date="2026-07-01", encounter_to_date="2026-07-20",
    )
    F.apply_overlay(api, overlay["id"])
    task = F.first_task_for_overlay(api, overlay["id"])
    return system, overlay, task


class TestPropagationTaskRetryCycle:
    def test_a_failed_dispatch_can_be_re_sent_and_the_attempt_count_is_monotonic(
        self, api
    ):
        """SENT to FAILED to SENT leaves attempt_count at 2, not back at 1.

        PRD §3.6: "A failed task may be dispatched again — `SENT → FAILED → SENT` is
        a supported retry cycle, bounded only by the propagation deadline."

        Design: Difficulty/non_linear_state_machine/propagation_task_sent_failed_sent_retry_cycle
        """
        _, _, task = _queued_overlay_task(api)
        assert task["operation_kind"] == OPERATION_OVERLAY_CORRECTION
        A.assert_instant(
            task["propagation_deadline_at"], "2026-08-04T00:00:00Z",
            "propagation_deadline_at",
        )

        first = F.send_task(
            api, task["id"], "2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z"
        )
        assert first["state"] == TASK_SENT
        A.assert_integer(first["attempt_count"], 1, "attempt_count")
        A.assert_version(first, 2)

        failed = A.assert_ok(
            api.fail_task(task["id"], f.fail_payload("ACK_TIMEOUT"), admin_headers())
        )
        assert failed["state"] == TASK_FAILED
        A.assert_integer(failed["attempt_count"], 1, "attempt_count")
        assert failed["last_error_code"] == "ACK_TIMEOUT"
        A.assert_version(failed, 3)

        second = F.send_task(
            api, task["id"], "2026-08-02T13:00:00Z", "2026-08-02T14:00:00Z"
        )
        assert second["state"] == TASK_SENT
        A.assert_integer(second["attempt_count"], 2, "attempt_count")
        A.assert_version(second, 4)

    def test_the_re_send_replaces_the_window_and_keeps_the_recorded_failure(self, api):
        """A dispatch stores the new window; nothing in it clears last_error_code.

        PRD §3.6: "A successful dispatch stores the window, moves the task `QUEUED →
        SENT` or `FAILED → SENT`, increases `attempt_count` by 1, advances the task's
        `version` by 1, and refreshes the consumer's `unacked_task_count`."

        Design: Difficulty/non_linear_state_machine/propagation_task_sent_failed_sent_retry_cycle
        """
        system, overlay, task = _queued_overlay_task(api)
        F.send_task(api, task["id"], "2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z")
        A.assert_ok(
            api.fail_task(task["id"], f.fail_payload("ACK_TIMEOUT"), admin_headers())
        )
        F.send_task(api, task["id"], "2026-08-02T13:00:00Z", "2026-08-02T14:00:00Z")

        final = F.get_task(api, task["id"])
        assert final["last_error_code"] == "ACK_TIMEOUT"
        A.assert_instant(
            final["dispatch_window_start_at"], "2026-08-02T13:00:00Z",
            "dispatch_window_start_at",
        )
        A.assert_instant(
            final["dispatch_window_end_at"], "2026-08-02T14:00:00Z",
            "dispatch_window_end_at",
        )
        A.assert_integer(
            F.get_system(api, system["id"])["unacked_task_count"], 1,
            "unacked_task_count",
        )

    def test_a_small_overlay_opens_no_remediation_during_the_retry_cycle(self, api):
        """Four affected elements stay under the review threshold.

        PRD §3.8: "And when `affected_clinical_element_count` is greater than 25, a
        contamination remediation is opened with `source_type` of `OVERLAY`, `state`
        of `OPEN`, its `overlay_correction_id` pointing at this correction, its
        `merge_operation_id` null, its `record_id` set to the overlaid record, and
        its `element_count_subject` set to `affected_clinical_element_count`."

        Design: Difficulty/non_linear_state_machine/propagation_task_sent_failed_sent_retry_cycle
        """
        _, overlay, task = _queued_overlay_task(api)
        F.send_task(api, task["id"], "2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z")
        A.assert_ok(
            api.fail_task(task["id"], f.fail_payload("ACK_TIMEOUT"), admin_headers())
        )
        F.send_task(api, task["id"], "2026-08-02T13:00:00Z", "2026-08-02T14:00:00Z")

        rows = A.list_rows(
            api.list_remediations(
                admin_headers(), {"overlay_correction_id": overlay["id"]}
            )
        )
        assert rows == []
