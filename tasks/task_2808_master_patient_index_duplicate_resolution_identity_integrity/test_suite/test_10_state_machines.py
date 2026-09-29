"""Declared transitions, their guards and the states that refuse them."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import (
    ERR_DOWNSTREAM_SYSTEM_PAUSED,
    ERR_INVESTIGATION_INVALID_STATE,
    ERR_PAIR_INVALID_STATE,
    ERR_PROPAGATION_IN_FLIGHT,
)
from test_helpers.constants import (
    CLASSIFICATION_POTENTIAL_DUPLICATE,
    IDENTITY_MERGED_SUBSUMED,
    INTEGRITY_CLEAR,
    INTEGRITY_REMEDIATION_PENDING,
    INVESTIGATION_UNSUBSTANTIATED,
    MERGE_PENDING_PROPAGATION,
    OPERATION_OVERLAY_CORRECTION,
    OUTCOME_DISTINCT,
    OVERLAY_CLINICAL_MISFILE,
    OVERLAY_CORRECTED,
    OVERLAY_DETECTED,
    OVERLAY_UNDER_CORRECTION,
    QUEUE_NEW,
    QUEUE_RESOLVED_DISTINCT,
    QUEUE_RESOLVED_MERGED,
    QUEUE_UNDER_REVIEW,
    RECOMMENDATION_DISTINCT,
    SCORE_VARIANT_STRICT,
    TASK_QUEUED,
    TASK_SENT,
    TRIGGER_MANUAL,
)
from test_helpers.test_users import (
    STEWARD_2_USER_ID,
    admin_headers,
    analyst_headers,
    officer_headers,
    steward_headers,
)


class TestRuleSetPromotion:
    def test_promoting_a_second_rule_set_retires_the_incumbent(self, api):
        """At most one rule set is ACTIVE, and both rows advance their version.

        PRD §3.1: "In the same request, whichever rule set previously held `status` of
        `ACTIVE` — at most one ever does — is transitioned `ACTIVE → RETIRED` and its
        own `version` advances by 1 as well."

        Design: Corner/state_machines/activating_a_second_rule_set_retires_the_first
        """
        first = F.create_rule_set(api, activate=False)
        second = F.create_rule_set(
            api, activate=False, name="Second Generation Rules",
            version_label="V-BASE-2", auto_link_threshold=88.00,
            review_threshold=72.00, conflict_penalty_points=10.00,
        )
        assert first["status"] == "DRAFT"

        promoted_first = A.assert_ok(
            api.activate_rule_set(first["id"], admin_headers())
        )
        promoted_second = A.assert_ok(
            api.activate_rule_set(second["id"], admin_headers())
        )
        retired = A.assert_ok(api.get_rule_set(first["id"], admin_headers()))

        assert promoted_first["status"] == "ACTIVE"
        A.assert_version(promoted_first, 2)
        assert promoted_second["status"] == "ACTIVE"
        A.assert_version(promoted_second, 2)
        assert retired["status"] == "RETIRED"
        A.assert_version(retired, 3)
        A.assert_score(retired["auto_link_threshold"], 85.00, "auto_link_threshold")
        A.assert_score(retired["review_threshold"], 70.00, "review_threshold")


def _seventy_point_pair(api, site_code, site_name, mrn_prefix, last_name, first_name,
                        dob, sex, ssn_last4, postal_code, phone):
    """A STRICT 70.00 pair: the second record leaves three scored attributes null."""
    site = F.create_site(
        api, site_code, name=site_name, region_code="US-NE", registrar_headcount=2
    )
    rule_set = F.create_rule_set(api, activate=False)
    record_a = F.create_record(
        api, site["id"], f"{mrn_prefix}-1000", last_name, first_name, dob, sex,
        ssn_last4=ssn_last4, postal_code=postal_code, phone=phone,
        clinical_element_count=5,
    )
    record_b = F.create_record(
        api, site["id"], f"{mrn_prefix}-2000", last_name, first_name, dob, sex,
        clinical_element_count=1,
    )
    pair = F.create_pair(
        api, record_a["id"], record_b["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    return site, rule_set, record_a, record_b, pair


class TestCandidatePairInitialState:
    def test_a_potential_duplicate_with_no_conflicts_opens_in_the_new_queue(self, api):
        """Neither create-time override applies, so the declared initial state holds.

        PRD §3.3: "The pair normally opens in `queue_state` of `NEW`, but two
        create-time branches override that, and the second outranks the first."

        Design: Corner/state_machines/candidate_pair_is_created_in_the_new_queue_state
        """
        site, rule_set, _, _, pair = _seventy_point_pair(
            api, "SITE-S2", "Initial State Clinic", "S2", "Bergstrom", "Anders",
            "1969-04-22", "M", "1919", "68102", "4025550101",
        )

        assert pair["queue_state"] == QUEUE_NEW
        A.assert_version(pair, 1)
        A.assert_score(pair["match_score"], 70.00, "match_score")
        assert pair["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert pair["conflict_flags"] == []
        assert pair["triage_note"] is None
        assert pair["recommended_by_user_id"] is None
        assert pair["recommendation"] is None
        assert pair["approved_by_user_id"] is None
        A.assert_score(pair["evidence_points"], 0.00, "evidence_points")
        A.assert_score(pair["evidence_adjustment"], 0.00, "evidence_adjustment")
        A.assert_score(pair["effective_score"], 70.00, "effective_score")
        assert pair["base_band"] == "P2"
        assert pair["priority_band"] == "P2"
        assert pair["detected_at_site_id"] == site["id"]
        assert pair["rule_set_id"] == rule_set["id"]
        assert pair["score_variant"] == SCORE_VARIANT_STRICT
        investigations = A.list_rows(
            api.list_investigations(officer_headers(), {"pair_id": pair["id"]})
        )
        assert investigations == []


class TestTerminalQueueStates:
    def test_a_pair_resolved_distinct_refuses_every_further_queue_action(self, api):
        """Both a return-to-review and a re-triage answer 409 and bump nothing.

        PRD §3.4: "It moves the pair `RECOMMENDED_DISTINCT → RESOLVED_DISTINCT`,
        records the approver as `approved_by_user_id`, and advances `version` by 1."

        Design: Corner/state_machines/resolved_distinct_pair_rejects_every_further_queue_action
        """
        _, _, _, _, pair = _seventy_point_pair(
            api, "SITE-S3", "Terminal Lockdown Clinic", "S3", "Achterberg", "Willem",
            "1958-01-30", "M", "3131", "57104", "6055550101",
        )
        F.advance_to_under_review(api, pair["id"], "Same name and dob, different social.")
        F.add_evidence(
            api, pair["id"], "PHOTO_ID", OUTCOME_DISTINCT, 3.00,
            note="Two different faces.",
        )
        F.add_evidence(
            api, pair["id"], "CLINICAL_CHART_COMPARE", OUTCOME_DISTINCT, 2.00,
            note="Incompatible surgical histories.",
        )
        F.recommend(api, pair["id"], RECOMMENDATION_DISTINCT)
        resolved = A.assert_ok(
            api.resolve_distinct(
                pair["id"],
                f.resolve_distinct_payload("Confirmed two distinct patients."),
                steward_headers(),
            )
        )
        assert resolved["queue_state"] == QUEUE_RESOLVED_DISTINCT
        A.assert_version(resolved, 7)
        assert resolved["recommendation"] == RECOMMENDATION_DISTINCT
        assert resolved["recommended_by_user_id"] == "analyst-1"
        assert resolved["approved_by_user_id"] == "steward-1"
        A.assert_score(resolved["evidence_points"], -5.00, "evidence_points")
        A.assert_score(resolved["evidence_adjustment"], -5.00, "evidence_adjustment")
        A.assert_score(resolved["effective_score"], 65.00, "effective_score")
        assert resolved["base_band"] == "P2"
        assert resolved["priority_band"] == "P3"

        first = api.return_to_review(
            pair["id"],
            f.return_to_review_payload(triage_note="Trying to reopen a terminal pair."),
            steward_headers(),
        )
        second = api.triage_pair(
            pair["id"],
            f.triage_payload("Trying to re-triage a terminal pair."),
            analyst_headers(),
        )

        A.assert_error_envelope(first, ERR_PAIR_INVALID_STATE, 409)
        A.assert_error_envelope(second, ERR_PAIR_INVALID_STATE, 409)
        final = F.get_pair(api, pair["id"])
        assert final["queue_state"] == QUEUE_RESOLVED_DISTINCT
        A.assert_version(final, 7)

    def test_starting_review_twice_is_not_idempotent(self, api):
        """UNDER_REVIEW is not a declared origin state of the start-review edge.

        PRD §3.4: "Opening manual review takes no input at all and moves the pair
        `TRIAGED → UNDER_REVIEW`, again advancing `version` by 1."

        Design: Corner/state_machines/start_review_twice_returns_pair_invalid_state
        """
        _, _, _, _, pair = _seventy_point_pair(
            api, "SITE-S4", "Idempotency Clinic", "S4", "Grimaldi", "Chiara",
            "1987-06-06", "F", "2727", "58102", "7015550101",
        )
        F.triage(api, pair["id"], "First pass.")
        opened = F.start_review(api, pair["id"])
        assert opened["queue_state"] == QUEUE_UNDER_REVIEW
        A.assert_version(opened, 3)

        response = api.start_review(pair["id"], analyst_headers())

        A.assert_error_envelope(response, ERR_PAIR_INVALID_STATE, 409)
        unchanged = F.get_pair(api, pair["id"])
        assert unchanged["queue_state"] == QUEUE_UNDER_REVIEW
        A.assert_version(unchanged, 3)
        A.assert_instant(unchanged["updated_at"], "2026-08-01T00:00:00Z", "updated_at")


class TestOverlaySideEffects:
    def test_applying_a_correction_writes_the_fields_and_raises_one_task(self, api):
        """The keys named in the snapshot are written; the others are left alone.

        PRD §3.8: "Every key in `corrected_field_snapshot` is written onto the patient
        record and the record's `version` advances by 1. One propagation task with
        `operation_kind` of `OVERLAY_CORRECTION` is raised per downstream system whose
        `status` is `ACTIVE`, in `system_code` ascending order, under the same
        acknowledgement rule as merge fan-out."

        Design: Corner/state_machines/apply_overlay_correction_executes_every_declared_side_effect
        """
        site = F.create_site(
            api, "SITE-S5", name="Overlay Side Effect Clinic", region_code="US-NC",
            registrar_headcount=3,
        )
        system = F.create_system(
            api, "OVL-SYS", name="Overlay Consumer", ack_required=True,
            max_concurrent_dispatch=2,
        )
        record = F.create_record(
            api, site["id"], "S5-1000", "Whitfield", "Miriam", "1976-02-18", "F",
            ssn_last4="8484", postal_code="27601", phone="9195550101",
            clinical_element_count=9,
        )
        overlay = F.create_overlay(
            api, record["id"], {"last_name": "Whitford", "postal_code": "27605"}, 5,
            record["version"], encounter_from_date="2026-07-10",
            encounter_to_date="2026-07-14",
        )
        assert overlay["state"] == OVERLAY_DETECTED
        assert overlay["prior_field_snapshot"] == {
            "last_name": "Whitfield",
            "postal_code": "27601",
        }
        A.assert_version(record, 1)

        applied = F.apply_overlay(api, overlay["id"])

        assert applied["state"] == OVERLAY_UNDER_CORRECTION
        A.assert_version(applied, 2)
        assert applied["created_by_user_id"] == "analyst-1"
        corrected = F.get_record(api, record["id"])
        assert corrected["last_name"] == "Whitford"
        assert corrected["postal_code"] == "27605"
        assert corrected["first_name"] == "Miriam"
        assert corrected["phone"] == "9195550101"
        assert corrected["enterprise_id"] == "EID-SITE-S5-S5-1000"
        A.assert_version(corrected, 3)
        assert corrected["integrity_state"] == INTEGRITY_REMEDIATION_PENDING
        tasks = F.tasks_for_overlay(api, overlay["id"])
        assert len(tasks) == 1
        assert tasks[0]["state"] == TASK_QUEUED
        assert tasks[0]["operation_kind"] == OPERATION_OVERLAY_CORRECTION
        assert tasks[0]["downstream_system_id"] == system["id"]
        A.assert_instant(
            tasks[0]["propagation_deadline_at"], "2026-08-04T00:00:00Z",
            "propagation_deadline_at",
        )
        remediations = A.list_rows(
            api.list_remediations(
                officer_headers(), {"overlay_correction_id": overlay["id"]}
            )
        )
        assert remediations == []
        A.assert_integer(
            F.get_system(api, system["id"])["unacked_task_count"], 1,
            "unacked_task_count",
        )

    def test_completing_a_correction_releases_the_remediation_hold(self, api):
        """Only completion re-derives the record's integrity state back to CLEAR.

        PRD §3.8: "It requires `state` of `UNDER_CORRECTION` and requires that no
        contamination remediation belonging to this correction remains in `OPEN`,
        `QUARANTINED` or `REASSIGNED`."

        Design: Corner/state_machines/complete_overlay_correction_releases_the_remediation_hold
        """
        site = F.create_site(
            api, "SITE-S6", name="Overlay Completion Clinic", region_code="US-SC",
            registrar_headcount=2,
        )
        record = F.create_record(
            api, site["id"], "S6-1000", "Pemberton", "Alice", "1962-12-19", "F",
            ssn_last4="6363", postal_code="29201", phone="8035550101",
            clinical_element_count=12,
        )
        overlay = F.create_overlay(
            api, record["id"], {"first_name": "Alicia"}, 5, record["version"],
            encounter_from_date="2026-07-20", encounter_to_date="2026-07-22",
            overlay_type=OVERLAY_CLINICAL_MISFILE, headers=steward_headers(),
        )
        F.apply_overlay(api, overlay["id"])
        mid = F.get_record(api, record["id"])
        assert mid["integrity_state"] == INTEGRITY_REMEDIATION_PENDING
        A.assert_version(mid, 3)

        completed = A.assert_ok(
            api.complete_overlay(
                overlay["id"],
                f.complete_overlay_payload(
                    "Misfiled encounters returned to the correct chart."
                ),
                steward_headers(),
            )
        )

        assert completed["state"] == OVERLAY_CORRECTED
        A.assert_version(completed, 3)
        assert completed["closure_note"] == (
            "Misfiled encounters returned to the correct chart."
        )
        released = F.get_record(api, record["id"])
        assert released["integrity_state"] == INTEGRITY_CLEAR
        A.assert_version(released, 4)
        assert released["first_name"] == "Alicia"
        A.assert_integer(
            released["clinical_element_count"], 12, "clinical_element_count"
        )
        rows = A.list_rows(
            api.list_overlays(
                officer_headers(),
                {"record_id": record["id"], "state": OVERLAY_CORRECTED},
            ),
            expected_total=1,
        )
        assert len(rows) == 1


class TestTerminalInvestigations:
    def test_substantiating_an_unsubstantiated_case_is_refused(self, api):
        """UNSUBSTANTIATED is terminal, so the released hold cannot be resurrected.

        PRD §3.9: "Unsubstantiating also requires `state` of `OPEN`, stores a
        `finding_note`, and moves the investigation `OPEN → UNSUBSTANTIATED`, which is
        terminal."

        Design: Corner/state_machines/substantiate_an_unsubstantiated_investigation_returns_investigation_invalid_state
        """
        site = F.create_site(
            api, "SITE-S7", name="Invalid Transition Clinic", region_code="US-MS",
            registrar_headcount=1,
        )
        record = F.create_record(
            api, site["id"], "S7-1000", "Bouchard", "Emile", "1971-07-07", "M",
            ssn_last4="5757", postal_code="39201", phone="6015550101",
            clinical_element_count=4,
        )
        investigation = F.open_manual_investigation(
            api, record["id"], TRIGGER_MANUAL,
            note="Two insurance cards presented under one identity.",
        )
        A.assert_score(investigation["risk_score"], 2.00, "risk_score")
        cleared = A.assert_ok(
            api.unsubstantiate(
                investigation["id"],
                f.unsubstantiate_payload(
                    "Cards belonged to the patient and a dependent; no fraud."
                ),
                officer_headers(),
            )
        )
        assert cleared["state"] == INVESTIGATION_UNSUBSTANTIATED

        response = api.substantiate(
            investigation["id"],
            f.substantiate_payload("Attempting to substantiate a closed investigation."),
            officer_headers(),
        )

        A.assert_error_envelope(response, ERR_INVESTIGATION_INVALID_STATE, 409)
        final = F.get_investigation(api, investigation["id"])
        assert final["state"] == INVESTIGATION_UNSUBSTANTIATED
        assert final["finding_note"] == (
            "Cards belonged to the patient and a dependent; no fraud."
        )
        assert F.get_record(api, record["id"])["integrity_state"] == INTEGRITY_CLEAR
        A.assert_site_counters(F.get_site(api, site["id"]), flagged_record_count=0)


class TestGuardsFromOtherEntities:
    def test_a_reversal_is_blocked_while_one_task_is_in_flight(self, api):
        """A change already handed to a consumer cannot be silently retracted.

        PRD §3.7: "No propagation task belonging to the merge may be in `SENT` — a
        change already handed to a consumer cannot be silently retracted, and the
        attempt is rejected with `ERR_PROPAGATION_IN_FLIGHT`."

        Design: Corner/state_machines/unmerge_with_a_sent_task_returns_propagation_in_flight
        """
        site = F.create_site(
            api, "SITE-S8", name="In Flight Clinic", region_code="US-AL",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        F.create_system(
            api, "PF-SYS", name="Propagation Flight System", ack_required=True,
            max_concurrent_dispatch=2,
        )
        demographics = {
            "last_name": "Castellanos",
            "first_name": "Mateo",
            "dob": "1994-03-27",
            "sex": "M",
            "ssn_last4": "9494",
            "postal_code": "35203",
            "phone": "2055550101",
        }
        survivor = F.create_record(
            api, site["id"], "S8-1000", clinical_element_count=6, **demographics
        )
        subsumed = F.create_record(
            api, site["id"], "S8-2000", clinical_element_count=4, **demographics
        )
        pair = F.create_pair(
            api, survivor["id"], subsumed["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        merge_row = F.merge(
            api, pair["id"], survivor["id"], subsumed["id"],
            rationale="Duplicate created during registration downtime.",
        )
        assert merge_row["state"] == MERGE_PENDING_PROPAGATION
        task = F.first_task_for_merge(api, merge_row["id"])
        sent = F.send_task(
            api, task["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
        )
        assert sent["state"] == TASK_SENT

        response = api.unmerge(
            merge_row["id"],
            f.unmerge_payload(
                "Attempting reversal while the mirror feed is in flight."
            ),
            steward_headers(STEWARD_2_USER_ID),
        )

        A.assert_error_envelope(response, ERR_PROPAGATION_IN_FLIGHT, 409)
        held = F.get_merge(api, merge_row["id"])
        assert held["state"] == MERGE_PENDING_PROPAGATION
        assert held["unmerged_at"] is None
        assert held["unmerge_reason"] is None
        subsumed_row = F.get_record(api, subsumed["id"])
        assert subsumed_row["identity_state"] == IDENTITY_MERGED_SUBSUMED
        A.assert_integer(
            subsumed_row["clinical_element_count"], 0, "clinical_element_count"
        )
        survivor_row = F.get_record(api, survivor["id"])
        A.assert_integer(
            survivor_row["clinical_element_count"], 10, "clinical_element_count"
        )
        A.assert_integer(
            survivor_row["subsumed_member_count"], 1, "subsumed_member_count"
        )
        assert F.get_pair(api, pair["id"])["queue_state"] == QUEUE_RESOLVED_MERGED
        assert F.get_task(api, task["id"])["state"] == TASK_SENT

    def test_a_paused_consumer_refuses_the_send_until_it_is_reactivated(self, api):
        """The identical dispatch succeeds the moment the consumer is ACTIVE again.

        PRD §3.6: "The consumer's `status` must be `ACTIVE`, or the dispatch is
        rejected with `ERR_DOWNSTREAM_SYSTEM_PAUSED`."

        Design: Corner/state_machines/send_a_task_on_a_paused_downstream_system_is_rejected_then_allowed
        """
        site = F.create_site(
            api, "SITE-S9", name="Guarded Transition Clinic", region_code="US-AR",
            registrar_headcount=1,
        )
        system = F.create_system(
            api, "PS-SYS", name="Pausable System", ack_required=True,
            max_concurrent_dispatch=2,
        )
        record = F.create_record(
            api, site["id"], "S9-1000", "Ferreira", "Tiago", "1989-09-19", "M",
            ssn_last4="1717", postal_code="72201", phone="5015550101",
            clinical_element_count=5,
        )
        overlay = F.create_overlay(
            api, record["id"], {"phone": "5015550199"}, 2, record["version"],
            encounter_from_date="2026-07-11", encounter_to_date="2026-07-12",
        )
        F.apply_overlay(api, overlay["id"])
        task = F.first_task_for_overlay(api, overlay["id"])
        paused = A.assert_ok(
            api.patch_system(system["id"], {"status": "PAUSED"}, admin_headers())
        )
        assert paused["status"] == "PAUSED"

        rejected = api.send_task(
            task["id"],
            f.send_payload("2026-08-02T13:00:00Z", "2026-08-02T14:00:00Z"),
            admin_headers(),
        )

        A.assert_error_envelope(rejected, ERR_DOWNSTREAM_SYSTEM_PAUSED, 409)
        untouched = F.get_task(api, task["id"])
        assert untouched["state"] == TASK_QUEUED
        A.assert_integer(untouched["attempt_count"], 0, "attempt_count")
        A.assert_version(untouched, 1)

        A.assert_ok(
            api.patch_system(system["id"], {"status": "ACTIVE"}, admin_headers())
        )
        accepted = F.send_task(
            api, task["id"], "2026-08-02T13:00:00Z", "2026-08-02T14:00:00Z"
        )

        assert accepted["state"] == TASK_SENT
        A.assert_integer(accepted["attempt_count"], 1, "attempt_count")
        A.assert_instant(
            accepted["dispatch_window_start_at"], "2026-08-02T13:00:00Z",
            "dispatch_window_start_at",
        )
        A.assert_instant(
            accepted["dispatch_window_end_at"], "2026-08-02T14:00:00Z",
            "dispatch_window_end_at",
        )
        final_system = F.get_system(api, system["id"])
        assert final_system["status"] == "ACTIVE"
        A.assert_integer(
            final_system["unacked_task_count"], 1, "unacked_task_count"
        )
