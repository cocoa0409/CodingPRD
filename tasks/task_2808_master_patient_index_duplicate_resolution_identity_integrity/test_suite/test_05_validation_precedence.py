"""Requests that violate two rules at once and must report the earlier rank."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import (
    ERR_DISPATCH_CAPACITY_EXCEEDED,
    ERR_PAIR_INVALID_STATE,
    ERR_PROPAGATION_WINDOW_EXPIRED,
    ERR_RECORD_UNDER_FRAUD_HOLD,
    ERR_STALE_RECORD_VERSION,
)
from test_helpers.constants import (
    INTEGRITY_CLEAR,
    INTEGRITY_FRAUD_SUSPECTED,
    OVERLAY_CLINICAL_MISFILE,
    PROPAGATION_MODE_SYNCHRONOUS,
    QUEUE_ESCALATED_FRAUD,
    QUEUE_UNDER_REVIEW,
    SCORE_VARIANT_STRICT,
    TASK_QUEUED,
    TASK_SENT,
    TRIGGER_BIOMETRIC_CONFLICT,
    TRIGGER_MANUAL,
)
from test_helpers.test_users import admin_headers, analyst_headers, officer_headers

CORRECTED_SNAPSHOT = {"last_name": "Sorensen-Lie", "dob": "1983-08-26"}


def _record_under_hold_with_stale_version(api):
    """A record whose version moved to 2 because a fraud hold was opened on it."""
    site = F.create_site(
        api, "SITE-OC", name="Occ Conflict Clinic", region_code="US-WA",
        registrar_headcount=2,
    )
    record = F.create_record(
        api, site["id"], "OC-9001", "Sorensen", "Karin", "1983-08-25", "F",
        ssn_last4="6070", postal_code="98104", phone="2065550101",
        clinical_element_count=9,
    )
    stale_version = record["version"]
    F.open_manual_investigation(
        api, record["id"], TRIGGER_MANUAL,
        note="Conflicting insurance member ids submitted at two encounters.",
    )
    current = F.get_record(api, record["id"])
    A.assert_version(current, 2)
    assert current["integrity_state"] == INTEGRITY_FRAUD_SUSPECTED
    return record, stale_version, current["version"]


def _overlay_attempt(api, record_id, expected_record_version):
    return api.create_overlay(
        f.overlay_payload(
            record_id,
            CORRECTED_SNAPSHOT,
            3,
            "2026-07-05",
            "2026-07-19",
            expected_record_version,
        ),
        analyst_headers(),
    )


class TestConcurrencyOutranksFraudHold:
    def test_a_stale_expected_record_version_is_reported_before_the_fraud_hold(
        self, api
    ):
        """One filing violates both rank 20 and rank 21 and must answer 412.

        PRD §2.8: "Both concurrency checks (ranks 19 and 20) fire **before** any
        fraud hold, remediation hold, site-suspension or state check on the same
        request, so a client holding a stale `version` learns about the stale version
        rather than about the record's condition."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_record_version_outranks_fraud_hold
        """
        record, stale_version, _ = _record_under_hold_with_stale_version(api)

        response = _overlay_attempt(api, record["id"], stale_version)

        A.assert_error_envelope(response, ERR_STALE_RECORD_VERSION, 412)

    def test_the_same_filing_at_the_current_version_then_reports_the_fraud_hold(
        self, api
    ):
        """Both rules were live: correcting the version exposes the later one.

        PRD §2.8: "No patient record in scope has `integrity_state` of
        `FRAUD_SUSPECTED` or `FRAUD_CONFIRMED` — otherwise
        `ERR_RECORD_UNDER_FRAUD_HOLD`, HTTP 409."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_record_version_outranks_fraud_hold
        """
        record, stale_version, current_version = _record_under_hold_with_stale_version(
            api
        )
        _overlay_attempt(api, record["id"], stale_version)

        response = _overlay_attempt(api, record["id"], current_version)

        A.assert_error_envelope(response, ERR_RECORD_UNDER_FRAUD_HOLD, 409)
        overlays = A.list_rows(
            api.list_overlays(analyst_headers(), {"record_id": record["id"]})
        )
        assert overlays == []
        unchanged = F.get_record(api, record["id"])
        assert unchanged["last_name"] == "Sorensen"
        assert unchanged["dob"] == "1983-08-25"
        A.assert_version(unchanged, 2)


def _escalated_pair_with_hold(api):
    """A pair pushed from UNDER_REVIEW into ESCALATED_FRAUD by a member's hold."""
    site = F.create_site(
        api, "SITE-PC", name="Priority Conflict Clinic", region_code="US-OH",
        registrar_headcount=4,
    )
    rule_set = F.create_rule_set(api, activate=False)
    record_a = F.create_record(
        api, site["id"], "PC-7001", "Delacroix", "Mathilde", "1977-02-11", "F",
        ssn_last4="5544", clinical_element_count=15,
    )
    record_b = F.create_record(
        api, site["id"], "PC-7002", "delacroix", "Mat", "1977-02-11", "F",
        ssn_last4="5544", clinical_element_count=5,
    )
    pair = F.create_pair(
        api, record_a["id"], record_b["id"], rule_set["id"],
        score_variant=SCORE_VARIANT_STRICT,
    )
    F.advance_to_under_review(api, pair["id"], "Queueing for manual adjudication.")
    investigation = F.open_manual_investigation(
        api, record_a["id"], TRIGGER_BIOMETRIC_CONFLICT,
        note="Fingerprint template does not match the enrolled template.",
    )
    return site, record_a, pair, investigation


class TestFraudHoldOutranksPairState:
    def test_re_triaging_an_escalated_pair_reports_the_hold_not_the_state(self, api):
        """Rank 21 and rank 26 both fail, and the earlier rank wins.

        PRD §2.8: "A later rule's condition is not even evaluated once an earlier one
        has failed."

        PRD §2.8: "No patient record in scope has `integrity_state` of
        `FRAUD_SUSPECTED` or `FRAUD_CONFIRMED` — otherwise
        `ERR_RECORD_UNDER_FRAUD_HOLD`, HTTP 409."

        Design: Difficulty/priority_pair_validation_conflict/fraud_hold_outranks_pair_queue_state
        """
        _, record_a, pair, _ = _escalated_pair_with_hold(api)
        before = F.get_pair(api, pair["id"])
        assert before["queue_state"] == QUEUE_ESCALATED_FRAUD
        assert (
            F.get_record(api, record_a["id"])["integrity_state"]
            == INTEGRITY_FRAUD_SUSPECTED
        )

        response = api.triage_pair(
            pair["id"],
            f.triage_payload("Attempting to re-triage the escalated pair."),
            analyst_headers(),
        )

        A.assert_error_envelope(response, ERR_RECORD_UNDER_FRAUD_HOLD, 409)

    def test_clearing_the_hold_exposes_the_queue_state_rejection_instead(self, api):
        """Once the record re-derives to CLEAR the pair returns to UNDER_REVIEW.

        PRD §3.9: "When and only when the record does re-derive to `CLEAR`, the site's
        `flagged_record_count` is decremented and every pair having that record as a
        member and sitting in `ESCALATED_FRAUD` returns `ESCALATED_FRAUD →
        UNDER_REVIEW`, each advancing its `version` by 1 — the third and last of the
        queue's back-edges."

        Design: Difficulty/priority_pair_validation_conflict/fraud_hold_outranks_pair_queue_state
        """
        site, record_a, pair, investigation = _escalated_pair_with_hold(api)
        api.triage_pair(
            pair["id"],
            f.triage_payload("Attempting to re-triage the escalated pair."),
            analyst_headers(),
        )

        cleared = A.assert_ok(
            api.unsubstantiate(
                investigation["id"],
                f.unsubstantiate_payload(
                    "Template mismatch traced to a faulty capture device; no fraud."
                ),
                officer_headers(),
            )
        )

        assert cleared["state"] == "UNSUBSTANTIATED"
        assert F.get_record(api, record_a["id"])["integrity_state"] == INTEGRITY_CLEAR
        assert F.get_pair(api, pair["id"])["queue_state"] == QUEUE_UNDER_REVIEW
        A.assert_site_counters(F.get_site(api, site["id"]), flagged_record_count=0)

        response = api.triage_pair(
            pair["id"],
            f.triage_payload("Attempting to re-triage the escalated pair."),
            analyst_headers(),
        )

        A.assert_error_envelope(response, ERR_PAIR_INVALID_STATE, 409)
        after = F.get_pair(api, pair["id"])
        assert after["queue_state"] == QUEUE_UNDER_REVIEW
        assert after["triage_note"] == "Queueing for manual adjudication."


def _saturated_synchronous_consumer(api):
    """One SENT task holding the only dispatch slot, plus one QUEUED task."""
    site = F.create_site(
        api, "SITE-LF", name="Lab Feed Clinic", region_code="US-CO",
        registrar_headcount=3,
    )
    system = F.create_system(
        api, "LAB-FEED", name="Reference Lab Feed",
        propagation_mode=PROPAGATION_MODE_SYNCHRONOUS, ack_required=True,
        max_concurrent_dispatch=1,
    )
    record_one = F.create_record(
        api, site["id"], "LF-5001", "Ngata", "Hemi", "1986-01-09", "M",
        ssn_last4="2020", postal_code="80202", phone="3035550101",
        clinical_element_count=10,
    )
    record_two = F.create_record(
        api, site["id"], "LF-5002", "Paulsen", "Greta", "1991-12-30", "F",
        ssn_last4="3030", postal_code="80203", phone="3035550102",
        clinical_element_count=8,
    )
    overlay_one = F.create_overlay(
        api, record_one["id"], {"postal_code": "80206"}, 4, record_one["version"],
        encounter_from_date="2026-07-02", encounter_to_date="2026-07-08",
        overlay_type=OVERLAY_CLINICAL_MISFILE,
    )
    F.apply_overlay(api, overlay_one["id"])
    overlay_two = F.create_overlay(
        api, record_two["id"], {"postal_code": "80207"}, 4, record_two["version"],
        encounter_from_date="2026-07-03", encounter_to_date="2026-07-09",
        overlay_type=OVERLAY_CLINICAL_MISFILE,
    )
    F.apply_overlay(api, overlay_two["id"])
    task_one = F.first_task_for_overlay(api, overlay_one["id"])
    task_two = F.first_task_for_overlay(api, overlay_two["id"])
    sent = F.send_task(
        api, task_one["id"], "2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z"
    )
    assert sent["state"] == TASK_SENT
    A.assert_integer(sent["attempt_count"], 1, "attempt_count")
    return system, task_two


class TestDeadlineOutranksCapacity:
    def test_an_overlapping_window_inside_the_deadline_reports_capacity(self, api):
        """The consumer allows one concurrent dispatch and it is already taken.

        PRD §3.6: "When occupancy has already reached the ceiling, the dispatch is
        rejected with `ERR_DISPATCH_CAPACITY_EXCEEDED`; capacity is an aggregate
        allowance, so a single overlap is perfectly legal as long as the count stays
        below the ceiling."

        Design: Difficulty/priority_pair_validation_conflict/propagation_deadline_outranks_dispatch_capacity
        """
        _, task_two = _saturated_synchronous_consumer(api)
        A.assert_instant(
            task_two["propagation_deadline_at"], "2026-08-02T00:00:00Z",
            "propagation_deadline_at",
        )

        response = api.send_task(
            task_two["id"],
            f.send_payload("2026-08-01T10:30:00Z", "2026-08-01T11:30:00Z"),
            admin_headers(),
        )

        A.assert_error_envelope(response, ERR_DISPATCH_CAPACITY_EXCEEDED, 409)

    def test_after_the_deadline_the_identical_send_reports_the_expired_window(
        self, api
    ):
        """Rank 43 displaces rank 45 once the clock passes the deadline.

        PRD §2.8: "The current logical clock is no later than the task's
        `propagation_deadline_at` — otherwise `ERR_PROPAGATION_WINDOW_EXPIRED`, HTTP
        409."

        Design: Difficulty/priority_pair_validation_conflict/propagation_deadline_outranks_dispatch_capacity
        """
        system, task_two = _saturated_synchronous_consumer(api)
        api.send_task(
            task_two["id"],
            f.send_payload("2026-08-01T10:30:00Z", "2026-08-01T11:30:00Z"),
            admin_headers(),
        )
        F.pin_clock(api, "2026-08-03T00:00:00Z")

        response = api.send_task(
            task_two["id"],
            f.send_payload("2026-08-01T10:30:00Z", "2026-08-01T11:30:00Z"),
            admin_headers(),
        )

        A.assert_error_envelope(response, ERR_PROPAGATION_WINDOW_EXPIRED, 409)
        untouched = F.get_task(api, task_two["id"])
        assert untouched["state"] == TASK_QUEUED
        A.assert_integer(untouched["attempt_count"], 0, "attempt_count")
        A.assert_version(untouched, 1)
        assert untouched["dispatch_window_start_at"] is None
        assert untouched["dispatch_window_end_at"] is None
        A.assert_integer(
            F.get_system(api, system["id"])["unacked_task_count"], 2,
            "unacked_task_count",
        )
