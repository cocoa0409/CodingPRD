"""States that no single row can decide on its own."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import ERR_DUPLICATE_CREATION_BLOCKED
from test_helpers.constants import (
    CLASSIFICATION_AUTO_LINK,
    IDENTITY_ACTIVE,
    IDENTITY_MERGED_SUBSUMED,
    INTEGRITY_CLEAR,
    MERGE_COMPLETED,
    MERGE_PENDING_PROPAGATION,
    OPERATION_MERGE,
    QUEUE_RECOMMENDED_MERGE,
    QUEUE_RESOLVED_MERGED,
    RS_BASE_VERSION_LABEL,
    SCORE_VARIANT_STRICT,
    TASK_ACKED,
    TASK_QUEUED,
    TASK_SENT,
)
from test_helpers.test_users import admin_headers, analyst_headers, registrar_headers

CE_DEMOGRAPHICS = {
    "last_name": "Halvorsen",
    "first_name": "Ingrid",
    "dob": "1959-06-14",
    "sex": "F",
    "ssn_last4": "8181",
    "postal_code": "02139",
    "phone": "6175550188",
}


def _merge_awaiting_one_ack(api):
    """A merge held in PENDING_PROPAGATION by a single ack-requiring consumer."""
    site = F.create_site(
        api, "SITE-CE", name="Cross Entity Clinic", region_code="US-MA",
        registrar_headcount=7,
    )
    rule_set = F.create_rule_set(api, activate=False)
    system = F.create_system(
        api, "CLAIMS-HUB", name="Enterprise Claims Hub", ack_required=True,
        max_concurrent_dispatch=3,
    )
    survivor = F.create_record(
        api, site["id"], "CE-6001", clinical_element_count=12, **CE_DEMOGRAPHICS
    )
    subsumed = F.create_record(
        api, site["id"], "CE-6002", clinical_element_count=8, **CE_DEMOGRAPHICS
    )
    pair = F.create_pair(
        api, survivor["id"], subsumed["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    merge_row = F.merge(
        api, pair["id"], survivor["id"], subsumed["id"],
        rationale="Identical demographics on all seven scored attributes.",
    )
    task = F.first_task_for_merge(api, merge_row["id"])
    return {
        "system": system,
        "records": (survivor, subsumed),
        "pair": pair,
        "merge": merge_row,
        "task": task,
    }


class TestMergeCompletionDependsOnItsTask:
    def test_an_auto_linked_merge_parks_in_pending_propagation(self, api):
        """One QUEUED task for an ack-requiring consumer leaves the merge waiting.

        PRD §3.5: "It becomes `COMPLETED` immediately when `propagation_task_count`
        is 0 — no active downstream system exists — or when none of the tasks it
        created belongs to a system requiring acknowledgement, since in both
        situations there is nothing left to wait for."

        Design: Difficulty/cross_entity_state_dependency/merge_completes_only_after_ack_required_task_is_acked
        """
        built = _merge_awaiting_one_ack(api)
        survivor, subsumed = built["records"]
        pair = F.get_pair(api, built["pair"]["id"])
        merge_row = built["merge"]
        task = built["task"]

        A.assert_score(pair["match_score"], 100.00, "match_score")
        assert pair["classification"] == CLASSIFICATION_AUTO_LINK
        assert pair["queue_state"] == QUEUE_RESOLVED_MERGED
        A.assert_integer(
            merge_row["moved_clinical_element_count"], 8,
            "moved_clinical_element_count",
        )
        A.assert_integer(merge_row["propagation_task_count"], 1, "propagation_task_count")
        assert merge_row["state"] == MERGE_PENDING_PROPAGATION
        assert merge_row["completed_at"] is None
        assert merge_row["reversal_deadline_at"] is None
        A.assert_integer(
            F.get_record(api, survivor["id"])["clinical_element_count"], 20,
            "clinical_element_count",
        )
        subsumed_row = F.get_record(api, subsumed["id"])
        A.assert_integer(
            subsumed_row["clinical_element_count"], 0, "clinical_element_count"
        )
        assert subsumed_row["identity_state"] == IDENTITY_MERGED_SUBSUMED
        assert task["state"] == TASK_QUEUED
        assert task["operation_kind"] == OPERATION_MERGE
        A.assert_instant(
            task["propagation_deadline_at"], "2026-08-04T00:00:00Z",
            "propagation_deadline_at",
        )

    def test_a_pair_that_auto_recommends_itself_needs_no_human_recommender(self, api):
        """The machine recommendation is what lets the merge run with no evidence.

        PRD §3.3: "Otherwise, if `classification` is `AUTO_LINK` and `conflict_flags`
        is empty, the pair opens in `RECOMMENDED_MERGE` — a system recommendation, so
        `recommendation` is set to `MERGE` and `recommended_by_user_id` is
        deliberately left null, which is precisely why §2.11's duty-separation check
        can never fail on a machine-recommended pair."

        Design: Difficulty/cross_entity_state_dependency/merge_completes_only_after_ack_required_task_is_acked
        """
        site = F.create_site(
            api, "SITE-CE", name="Cross Entity Clinic", region_code="US-MA",
            registrar_headcount=7,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "CE-6001", clinical_element_count=12, **CE_DEMOGRAPHICS
        )
        record_b = F.create_record(
            api, site["id"], "CE-6002", clinical_element_count=8, **CE_DEMOGRAPHICS
        )

        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        assert pair["queue_state"] == QUEUE_RECOMMENDED_MERGE
        assert pair["recommended_by_user_id"] is None

    def test_only_the_acknowledgement_completes_the_merge(self, api):
        """A SENT task is still not an acknowledged task.

        PRD §3.6: "Acknowledgement requires `state` of `SENT`, moves the task `SENT →
        ACKED`, advances its `version` by 1, refreshes `unacked_task_count`, and then
        **bubbles up**: if the parent merge is still `PENDING_PROPAGATION` and every
        one of its tasks that belongs to an acknowledgement-requiring consumer is now
        `ACKED`, with cancelled tasks disregarded, the merge transitions
        `PENDING_PROPAGATION → COMPLETED`, stamps `completed_at` from the logical
        clock, sets `reversal_deadline_at` to 90 days later, and advances the merge's
        `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/merge_completes_only_after_ack_required_task_is_acked
        """
        built = _merge_awaiting_one_ack(api)
        merge_id = built["merge"]["id"]
        task_id = built["task"]["id"]

        sent = F.send_task(api, task_id, "2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z")
        assert sent["state"] == TASK_SENT
        assert F.get_merge(api, merge_id)["state"] == MERGE_PENDING_PROPAGATION

        acked = F.ack_task(api, task_id)

        assert acked["state"] == TASK_ACKED
        completed = F.get_merge(api, merge_id)
        assert completed["state"] == MERGE_COMPLETED
        A.assert_instant(completed["completed_at"], "2026-08-01T00:00:00Z", "completed_at")
        A.assert_instant(
            completed["reversal_deadline_at"], "2026-10-30T00:00:00Z",
            "reversal_deadline_at",
        )
        A.assert_integer(
            F.get_system(api, built["system"]["id"])["unacked_task_count"], 0,
            "unacked_task_count",
        )


HOME_DEMOGRAPHICS = {
    "searched_last_name": "Kowalczyk",
    "searched_first_name": "Marta",
    "searched_dob": "1966-12-05",
    "searched_sex": "F",
    "searched_ssn_last4": "2244",
    "searched_postal_code": "60302",
    "searched_phone": "3125550190",
}


def _cross_site_registration_setup(api):
    """A record at SITE-HOME and two search attempts run by the SITE-AWAY desk."""
    site_home = F.create_site(
        api, "SITE-HOME", name="Home Registration Desk", region_code="US-IL",
        registrar_headcount=8,
    )
    site_away = F.create_site(
        api, "SITE-AWAY", name="Away Registration Desk", region_code="US-IL",
        registrar_headcount=3,
    )
    F.create_rule_set(api, activate=True)
    F.create_record(
        api, site_home["id"], "H-9100", "Kowalczyk", "Marta", "1966-12-05", "F",
        ssn_last4="2244", postal_code="60302", phone="3125550190",
        clinical_element_count=21,
    )
    away_headers = registrar_headers(site_away["id"])
    hit = A.assert_created(
        api.create_search_attempt(
            site_away["id"],
            f.search_attempt_payload(**HOME_DEMOGRAPHICS),
            away_headers,
        )
    )
    miss = A.assert_created(
        api.create_search_attempt(
            site_away["id"], f.search_attempt_payload("Zielinski"), away_headers
        )
    )
    return site_home, site_away, hit, miss, away_headers


class TestRegistrationBlockedByAForeignSiteRecord:
    def test_the_search_pool_reaches_across_sites_and_blocks_creation(self, api):
        """The away desk is warned about a chart it does not own.

        PRD §3.2: "The candidate pool is enterprise-wide, not site-scoped — duplicate
        prevention that only looked at the local desk would miss precisely the
        cross-site duplicates that matter most — and it comprises every patient
        record whose `identity_state` is `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/registration_blocked_by_active_record_at_a_different_site
        """
        _, _, hit, miss, _ = _cross_site_registration_setup(api)

        A.assert_integer(hit["result_count"], 1, "result_count")
        A.assert_score(hit["top_score"], 100.00, "top_score")
        assert hit["top_match_record_mrn"] == "H-9100"
        assert hit["blocked_creation"] is True
        assert hit["rule_set_version_label"] == RS_BASE_VERSION_LABEL
        A.assert_integer(miss["result_count"], 0, "result_count")
        A.assert_score(miss["top_score"], 0.00, "top_score")
        assert miss["top_match_record_mrn"] is None
        assert miss["blocked_creation"] is False

    def test_citing_the_blocking_attempt_is_rejected(self, api):
        """The registrar may not open a second chart for the same person.

        PRD §3.2: "Second, permission: the cited attempt's `blocked_creation` must be
        false."

        Design: Difficulty/cross_entity_state_dependency/registration_blocked_by_active_record_at_a_different_site
        """
        _, site_away, hit, _, away_headers = _cross_site_registration_setup(api)

        response = api.create_record(
            f.record_payload(
                site_away["id"], "W-4100", "Kowalczyk", "Marta", "1966-12-05", "F",
                ssn_last4="2244", postal_code="60302", phone="3125550190",
                clinical_element_count=0, origin_search_attempt_id=hit["id"],
            ),
            away_headers,
        )

        A.assert_error_envelope(response, ERR_DUPLICATE_CREATION_BLOCKED, 409)
        A.assert_site_counters(
            F.get_site(api, site_away["id"]), active_record_count=0
        )

    def test_citing_the_clean_attempt_registers_the_patient(self, api):
        """The same desk and the same mrn succeed behind a non-blocking search.

        PRD §3.2: "Its `enterprise_id` — the key by which the whole enterprise refers
        to this person — is composed as the literal text `EID-`, followed by the
        registering site's `site_code`, followed by a hyphen, followed by the
        record's `mrn`."

        Design: Difficulty/cross_entity_state_dependency/registration_blocked_by_active_record_at_a_different_site
        """
        site_home, site_away, hit, miss, away_headers = _cross_site_registration_setup(
            api
        )
        api.create_record(
            f.record_payload(
                site_away["id"], "W-4100", "Kowalczyk", "Marta", "1966-12-05", "F",
                ssn_last4="2244", postal_code="60302", phone="3125550190",
                clinical_element_count=0, origin_search_attempt_id=hit["id"],
            ),
            away_headers,
        )

        created = A.assert_created(
            api.create_record(
                f.record_payload(
                    site_away["id"], "W-4100", "Zielinski", "Ewa", "1971-04-18", "F",
                    clinical_element_count=0, origin_search_attempt_id=miss["id"],
                ),
                away_headers,
            )
        )

        assert created["identity_state"] == IDENTITY_ACTIVE
        assert created["integrity_state"] == INTEGRITY_CLEAR
        assert created["enterprise_id"] == "EID-SITE-AWAY-W-4100"
        assert created["origin_search_attempt_id"] == miss["id"]
        A.assert_site_counters(
            F.get_site(api, site_away["id"]), active_record_count=1
        )
        A.assert_site_counters(
            F.get_site(api, site_home["id"]), active_record_count=1
        )
