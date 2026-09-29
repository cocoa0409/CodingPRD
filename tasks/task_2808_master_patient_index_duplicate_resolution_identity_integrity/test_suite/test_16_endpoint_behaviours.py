"""Endpoint-shaped behaviour: partial updates, terminal branches and nested lists.

Each case exercises one endpoint's own contract — the fields a PATCH is allowed
to touch, the branch that closes a pair without moving any chart, the live
status a dispatch reads, the strict element threshold, the scoping of a nested
collection and the terminal referral step.
"""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import ERR_DOWNSTREAM_SYSTEM_PAUSED
from test_helpers.constants import (
    CLASSIFICATION_AUTO_LINK,
    CLASSIFICATION_POTENTIAL_DUPLICATE,
    IDENTITY_ACTIVE,
    INTEGRITY_FRAUD_CONFIRMED,
    INTEGRITY_REMEDIATION_PENDING,
    INVESTIGATION_REFERRED,
    INVESTIGATION_SUBSTANTIATED,
    MERGE_PENDING_PROPAGATION,
    OPENED_BY_OFFICER,
    OUTCOME_DISTINCT,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_SAME_PERSON,
    OVERLAY_CLINICAL_MISFILE,
    OVERLAY_UNDER_CORRECTION,
    PROPAGATION_MODE_BATCH,
    QUEUE_NEW,
    QUEUE_RECOMMENDED_DISTINCT,
    QUEUE_RECOMMENDED_MERGE,
    QUEUE_RESOLVED_DISTINCT,
    RECOMMENDATION_DISTINCT,
    REMEDIATION_OPEN,
    SCORE_VARIANT_STRICT,
    SCORE_VARIANT_TOLERANT,
    SOURCE_TYPE_OVERLAY,
    TASK_QUEUED,
    TASK_SENT,
    TRIGGER_INSURANCE_CONFLICT,
)
from test_helpers.test_users import (
    admin_headers,
    analyst_headers,
    officer_headers,
    steward_headers,
)


class TestSitePartialUpdate:
    def test_a_patch_moves_only_the_keys_it_carries(self, api):
        """Two single-key PATCHes leave every unmentioned field exactly as it was.

        PRD §3.1: "An administrator may later amend a site by supplying any of
        `name`, `registrar_headcount` or `status`."

        Design: Corner/endpoints/patch_registration_site_updates_only_the_supplied_fields
        """
        site = F.create_site(
            api, "EA-SITE", name="Eastside Admitting", region_code="US-NC",
            registrar_headcount=5,
        )
        A.assert_version(site, 1)
        assert site["region_code"] == "US-NC"

        headcount_only = A.assert_ok(
            api.patch_site(site["id"], {"registrar_headcount": 9}, admin_headers())
        )
        name_only = A.assert_ok(
            api.patch_site(
                site["id"],
                {"name": "Eastside Admitting & Registration"},
                admin_headers(),
            )
        )

        A.assert_integer(
            headcount_only["registrar_headcount"], 9, "registrar_headcount"
        )
        assert headcount_only["name"] == "Eastside Admitting"
        assert headcount_only["region_code"] == "US-NC"
        assert headcount_only["status"] == "ACTIVE"
        A.assert_version(headcount_only, 2)
        assert name_only["name"] == "Eastside Admitting & Registration"
        A.assert_integer(name_only["registrar_headcount"], 9, "registrar_headcount")
        assert name_only["status"] == "ACTIVE"
        A.assert_version(name_only, 3)
        stored = F.get_site(api, site["id"])
        assert stored["site_code"] == "EA-SITE"
        A.assert_site_counters(stored, active_record_count=0)


class TestDistinctResolution:
    def test_closing_a_pair_as_distinct_moves_no_chart_and_frees_the_records(
        self, api
    ):
        """The verdict is terminal for the pair and invisible to both records.

        PRD §3.4: "It moves the pair `RECOMMENDED_DISTINCT → RESOLVED_DISTINCT`,
        records the approver as `approved_by_user_id`, and advances `version` by 1."

        PRD §3.4: "What does change is future eligibility: because both
        `RESOLVED_DISTINCT` and `RESOLVED_MERGED` are excluded from the live-pair test
        of §3.3, closing a pair this way permits a new pair to be raised over the same
        two records later, should new information arrive."

        Design: Corner/endpoints/resolve_distinct_closes_the_pair_and_leaves_both_records_active
        """
        site = F.create_site(
            api, "EB-SITE", name="Distinct Resolution Clinic", region_code="US-SC",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "EB-1000", "Villanueva", "Rosa", "1981-04-04", "F",
            ssn_last4="2929", postal_code="29201", phone="8035550101",
            clinical_element_count=7,
        )
        record_b = F.create_record(
            api, site["id"], "EB-2000", "Villanueva", "Rosa", "1981-04-04", "F",
            clinical_element_count=3,
        )
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        A.assert_score(pair["match_score"], 70.00, "match_score")
        assert pair["classification"] == CLASSIFICATION_POTENTIAL_DUPLICATE
        assert pair["queue_state"] == QUEUE_NEW
        F.advance_to_under_review(
            api, pair["id"], "Mother and daughter suspected."
        )
        F.add_evidence(
            api, pair["id"], "PHOTO_ID", OUTCOME_DISTINCT, 3.00,
            note="Different faces.",
        )
        F.add_evidence(
            api, pair["id"], "CLINICAL_CHART_COMPARE", OUTCOME_DISTINCT, 2.00,
            note="Different obstetric histories.",
        )
        recommended = F.recommend(api, pair["id"], RECOMMENDATION_DISTINCT)
        A.assert_score(recommended["evidence_points"], -5.00, "evidence_points")
        A.assert_score(recommended["effective_score"], 65.00, "effective_score")
        assert recommended["queue_state"] == QUEUE_RECOMMENDED_DISTINCT

        closed = A.assert_ok(
            api.resolve_distinct(
                pair["id"],
                f.resolve_distinct_payload("Confirmed two different patients."),
                steward_headers(),
            )
        )
        reopened = api.create_pair(
            f.pair_payload(
                record_a["id"], record_b["id"], rule_set["id"], SCORE_VARIANT_TOLERANT
            ),
            analyst_headers(),
        )

        assert closed["queue_state"] == QUEUE_RESOLVED_DISTINCT
        assert closed["approved_by_user_id"] == "steward-1"
        A.assert_version(closed, 7)
        kept = F.get_record(api, record_a["id"])
        assert kept["identity_state"] == IDENTITY_ACTIVE
        A.assert_integer(kept["clinical_element_count"], 7, "clinical_element_count")
        assert kept["survivor_record_id"] is None
        other = F.get_record(api, record_b["id"])
        assert other["identity_state"] == IDENTITY_ACTIVE
        A.assert_integer(other["clinical_element_count"], 3, "clinical_element_count")
        assert other["survivor_record_id"] is None
        second_pair = A.assert_created(reopened)
        assert second_pair["score_variant"] == SCORE_VARIANT_TOLERANT
        A.assert_score(second_pair["match_score"], 77.50, "match_score")
        assert A.list_rows(api.list_merges(admin_headers()), expected_total=0) == []


EC_DEMOGRAPHICS = {
    "last_name": "Baptiste",
    "first_name": "Yvette",
    "dob": "1994-09-09",
    "sex": "F",
    "ssn_last4": "3131",
    "postal_code": "30303",
    "phone": "4045550101",
}


class TestPausedConsumer:
    def test_the_same_dispatch_is_refused_while_paused_and_accepted_once_active(
        self, api
    ):
        """The precondition reads the consumer's status at the moment of the send.

        PRD §3.6: "The consumer's `status` must be `ACTIVE`, or the dispatch is
        rejected with `ERR_DOWNSTREAM_SYSTEM_PAUSED`."

        Design: Corner/endpoints/pausing_a_downstream_system_blocks_sends_until_it_is_reactivated
        """
        site = F.create_site(
            api, "EC-SITE", name="Paused Consumer Clinic", region_code="US-GA",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        system = F.create_system(
            api, "EC-SYS", name="Nightly Data Warehouse",
            propagation_mode=PROPAGATION_MODE_BATCH, ack_required=True,
            max_concurrent_dispatch=1,
        )
        survivor = F.create_record(
            api, site["id"], "EC-1000", clinical_element_count=3, **EC_DEMOGRAPHICS
        )
        subsumed = F.create_record(
            api, site["id"], "EC-2000", clinical_element_count=1, **EC_DEMOGRAPHICS
        )
        pair = F.create_pair(
            api, survivor["id"], subsumed["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        assert pair["classification"] == CLASSIFICATION_AUTO_LINK
        assert pair["queue_state"] == QUEUE_RECOMMENDED_MERGE
        assert pair["recommended_by_user_id"] is None
        merge_row = F.merge(
            api, pair["id"], survivor["id"], subsumed["id"],
            rationale="Same patient.",
        )
        assert merge_row["state"] == MERGE_PENDING_PROPAGATION
        A.assert_integer(
            merge_row["propagation_task_count"], 1, "propagation_task_count"
        )
        task = F.first_task_for_merge(api, merge_row["id"])
        A.assert_instant(
            task["propagation_deadline_at"], "2026-08-04T00:00:00.000Z",
            "propagation_deadline_at",
        )
        paused = A.assert_ok(
            api.patch_system(system["id"], {"status": "PAUSED"}, admin_headers())
        )
        assert paused["status"] == "PAUSED"
        A.assert_integer(paused["unacked_task_count"], 1, "unacked_task_count")
        payload = f.send_payload(
            "2026-08-01T01:00:00Z", "2026-08-01T02:00:00Z"
        )

        refused = api.send_task(task["id"], payload, admin_headers())
        A.assert_error_envelope(refused, ERR_DOWNSTREAM_SYSTEM_PAUSED, 409)
        held = F.get_task(api, task["id"])
        assert held["state"] == TASK_QUEUED
        A.assert_integer(held["attempt_count"], 0, "attempt_count")
        A.assert_version(held, 1)
        A.assert_ok(
            api.patch_system(system["id"], {"status": "ACTIVE"}, admin_headers())
        )

        accepted = api.send_task(task["id"], payload, admin_headers())

        sent = A.assert_ok(accepted)
        assert sent["state"] == TASK_SENT
        A.assert_integer(sent["attempt_count"], 1, "attempt_count")
        A.assert_instant(
            sent["dispatch_window_start_at"], "2026-08-01T01:00:00.000Z",
            "dispatch_window_start_at",
        )
        A.assert_version(sent, 2)
        still_open = F.get_merge(api, merge_row["id"])
        assert still_open["state"] == MERGE_PENDING_PROPAGATION
        assert still_open["completed_at"] is None


class TestOverlayRemediationThreshold:
    def test_twenty_five_elements_open_nothing_and_twenty_six_open_one(self, api):
        """The remediation branch is a strict greater-than, tested from both sides.

        PRD §3.8: "And when `affected_clinical_element_count` is greater than 25, a
        contamination remediation is opened with `source_type` of `OVERLAY`, `state` of
        `OPEN`, its `overlay_correction_id` pointing at this correction, its
        `merge_operation_id` null, its `record_id` set to the overlaid record, and its
        `element_count_subject` set to `affected_clinical_element_count`."

        Design: Corner/endpoints/overlay_apply_opens_a_remediation_only_above_the_element_threshold
        """
        site = F.create_site(
            api, "ED-SITE", name="Overlay Threshold Clinic", region_code="US-AL",
            registrar_headcount=2,
        )
        at_threshold = F.create_record(
            api, site["id"], "ED-1000", "Fitzwilliam", "Clara", "1977-06-15", "F",
            ssn_last4="4141", postal_code="35203", phone="2055550101",
            clinical_element_count=40,
        )
        above_threshold = F.create_record(
            api, site["id"], "ED-2000", "Osei", "Kwabena", "1962-02-22", "M",
            ssn_last4="5252", postal_code="35204", phone="2055550202",
            clinical_element_count=40,
        )
        overlay_at = F.create_overlay(
            api, at_threshold["id"], {"postal_code": "35205"}, 25,
            at_threshold["version"], encounter_from_date="2026-06-01",
            encounter_to_date="2026-06-30", overlay_type=OVERLAY_CLINICAL_MISFILE,
        )
        overlay_above = F.create_overlay(
            api, above_threshold["id"], {"postal_code": "35206"}, 26,
            above_threshold["version"], encounter_from_date="2026-06-01",
            encounter_to_date="2026-06-30", overlay_type=OVERLAY_CLINICAL_MISFILE,
        )

        applied_at = F.apply_overlay(api, overlay_at["id"])
        applied_above = F.apply_overlay(api, overlay_above["id"])

        assert applied_at["state"] == OVERLAY_UNDER_CORRECTION
        assert applied_at["prior_field_snapshot"] == {"postal_code": "35203"}
        A.assert_version(applied_at, 2)
        assert A.list_rows(
            api.list_remediations(
                admin_headers(), {"overlay_correction_id": overlay_at["id"]}
            ),
            expected_total=0,
        ) == []
        assert applied_above["state"] == OVERLAY_UNDER_CORRECTION
        rows = A.list_rows(
            api.list_remediations(
                admin_headers(), {"overlay_correction_id": overlay_above["id"]}
            ),
            expected_total=1,
        )
        assert len(rows) == 1
        opened = rows[0]
        assert opened["source_type"] == SOURCE_TYPE_OVERLAY
        assert opened["state"] == REMEDIATION_OPEN
        A.assert_integer(opened["element_count_subject"], 26, "element_count_subject")
        assert opened["merge_operation_id"] is None
        assert opened["record_id"] == above_threshold["id"]
        assert F.get_record(api, at_threshold["id"])["postal_code"] == "35205"
        assert F.get_record(api, above_threshold["id"])["postal_code"] == "35206"
        assert F.get_record(api, at_threshold["id"])["integrity_state"] == (
            INTEGRITY_REMEDIATION_PENDING
        )
        assert F.get_record(api, above_threshold["id"])["integrity_state"] == (
            INTEGRITY_REMEDIATION_PENDING
        )
        assert A.list_rows(api.list_tasks(admin_headers()), expected_total=0) == []


class TestEvidenceListing:
    def test_the_nested_evidence_page_is_filtered_to_its_own_pair(self, api):
        """Three rows on one pair and one on another; each list sees only its own.

        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside `meta`, where `total_count` is the number of records matching the filters
        before the page window is applied and `has_more` states whether any matching
        record remains beyond the current window."

        PRD §2.3: "Unless a specific collection declares otherwise, list results are
        ordered by `created_at` ascending."

        Design: Corner/endpoints/evidence_listing_is_scoped_to_its_pair_and_paginates
        """
        site = F.create_site(
            api, "EE-SITE", name="Evidence Listing Clinic", region_code="US-MS",
            registrar_headcount=3,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_1 = F.create_record(
            api, site["id"], "EE-1000", "Lindqvist", "Annika", "1986-05-05", "F",
            ssn_last4="6262", postal_code="39201", phone="6015550101",
            clinical_element_count=2,
        )
        record_2 = F.create_record(
            api, site["id"], "EE-2000", "Lindqvist", "Annika", "1986-05-05", "F",
            clinical_element_count=1,
        )
        record_3 = F.create_record(
            api, site["id"], "EE-3000", "Tremblay", "Etienne", "1953-08-19", "M",
            ssn_last4="7373", postal_code="39202", phone="6015550202",
            clinical_element_count=4,
        )
        record_4 = F.create_record(
            api, site["id"], "EE-4000", "Tremblay", "Etienne", "1953-08-19", "M",
            clinical_element_count=2,
        )
        pair_a = F.create_pair(
            api, record_1["id"], record_2["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        pair_b = F.create_pair(
            api, record_3["id"], record_4["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        F.advance_to_under_review(api, pair_a["id"], "Couple A.")
        F.advance_to_under_review(api, pair_b["id"], "Couple B.")
        F.add_evidence(
            api, pair_a["id"], "PHOTO_ID", OUTCOME_SAME_PERSON, 2.00, note="A-1"
        )
        F.pin_clock(api, "2026-08-01T00:01:00Z")
        F.add_evidence(
            api, pair_a["id"], "INSURANCE_CARD", OUTCOME_SAME_PERSON, 3.00, note="A-2"
        )
        F.pin_clock(api, "2026-08-01T00:02:00Z")
        third = F.add_evidence(
            api, pair_a["id"], "PHONE_VERIFICATION", OUTCOME_INCONCLUSIVE, 1.00,
            note="A-3",
        )
        assert third["pair_id"] == pair_a["id"]
        F.add_evidence(
            api, pair_b["id"], "BIOMETRIC_COMPARE", OUTCOME_SAME_PERSON, 4.00,
            note="B-1",
        )

        last_page, _ = A.assert_list_meta(
            api.list_evidence(
                pair_a["id"], steward_headers(), {"limit": 2, "offset": 2}
            ),
            expected_total=3, expected_limit=2, expected_offset=2,
            expected_has_more=False,
        )
        other_list, _ = A.assert_list_meta(
            api.list_evidence(pair_b["id"], steward_headers()),
            expected_total=1, expected_limit=10, expected_offset=0,
            expected_has_more=False,
        )

        assert len(last_page) == 1
        assert last_page[0]["note"] == "A-3"
        assert len(other_list) == 1
        assert other_list[0]["note"] == "B-1"
        assert other_list[0]["pair_id"] == pair_b["id"]
        scored_a = F.get_pair(api, pair_a["id"])
        A.assert_score(scored_a["evidence_points"], 5.00, "evidence_points")
        A.assert_score(scored_a["effective_score"], 75.00, "effective_score")
        scored_b = F.get_pair(api, pair_b["id"])
        A.assert_score(scored_b["evidence_points"], 4.00, "evidence_points")
        A.assert_score(scored_b["effective_score"], 74.00, "effective_score")


class TestReferral:
    def test_a_referral_is_terminal_book_keeping_that_holds_the_record(self, api):
        """The escalation moves the case forward and nothing about the record back.

        PRD §3.9: "Referring a case to law enforcement requires `state` of
        `SUBSTANTIATED`, stores a `referral_reference`, and moves the investigation
        `SUBSTANTIATED → REFERRED_LAW_ENFORCEMENT`, which is terminal; referral never
        releases the hold, and the subject stays `FRAUD_CONFIRMED`."

        Design: Corner/endpoints/referring_a_substantiated_investigation_keeps_the_fraud_hold
        """
        site = F.create_site(
            api, "EF-SITE", name="Referral Clinic", region_code="US-AR",
            registrar_headcount=2,
        )
        record = F.create_record(
            api, site["id"], "EF-1000", "Okonkwo", "Ifeanyi", "1989-11-11", "M",
            ssn_last4="8484", postal_code="72201", phone="5015550101",
            insurance_member_id="MBR-77777", clinical_element_count=3,
        )
        investigation = F.open_manual_investigation(
            api, record["id"], TRIGGER_INSURANCE_CONFLICT,
            note="Same member id used by three different patients.",
        )
        assert investigation["opened_by"] == OPENED_BY_OFFICER
        A.assert_score(investigation["risk_score"], 2.00, "risk_score")
        substantiated = A.assert_ok(
            api.substantiate(
                investigation["id"],
                f.substantiate_payload("Insurance identity theft confirmed."),
                officer_headers(),
            )
        )
        assert substantiated["state"] == INVESTIGATION_SUBSTANTIATED
        A.assert_version(substantiated, 2)

        referred = A.assert_ok(
            api.refer(
                investigation["id"],
                f.refer_payload("USAO-AR-2026-0311"),
                officer_headers(),
            )
        )

        assert referred["state"] == INVESTIGATION_REFERRED
        assert referred["referral_reference"] == "USAO-AR-2026-0311"
        A.assert_version(referred, 3)
        held = F.get_record(api, record["id"])
        assert held["integrity_state"] == INTEGRITY_FRAUD_CONFIRMED
        assert held["identity_state"] == IDENTITY_ACTIVE
        A.assert_site_counters(
            F.get_site(api, site["id"]), active_record_count=1, flagged_record_count=1
        )
