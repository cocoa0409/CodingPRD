"""Boundary precision: the low-confidence QA sampling threshold at 89 vs 90,
and retention expiry at the exact eligibility instant.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.fixtures import (
    create_draft,
    create_encounter,
    create_note_template,
    create_patient,
    create_physician,
    edit_draft,
    grant_consent,
    set_clock,
    start_capture,
    start_encounter,
    stop_capture,
    submit_review,
    transcribe,
)
from test_helpers.test_users import ADMIN


class TestLowConfidenceSamplingThreshold89Vs90:
    """completeness_at_attestation 89 (strictly below threshold 90) queues a
    LOW_CONFIDENCE sample; exactly 90 does not."""

    def _attest_with_multiplier(self, client, patient, physician, multiplier):
        """CRITICAL+MAJOR template; only chief filled; completeness is
        100 - round_half_up(10 * multiplier). Returns (draft_id, body)."""
        template = create_note_template(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("hpi", "MAJOR", True),
            ],
            completeness_multiplier=multiplier,
            low_confidence_threshold=90,
        )
        set_clock(client, "2026-09-01T16:00:00Z")
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        capture = start_capture(client, encounter, physician)
        capture = stop_capture(client, capture, physician)
        transcribe(client, capture)
        draft = create_draft(client, encounter, physician, template)
        draft = edit_draft(
            client, draft, physician, [f.field_update("chief_complaint", "dyspnea")]
        )
        submit_review(client, draft, physician)
        headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        body = validate_success(client.attest_draft(draft["id"], headers=headers))
        return draft["id"], body, headers

    def test_score_89_queues_low_confidence_sample(self, client):
        """PRD 3.5: "And if the snapshot `completeness_at_attestation` is
        strictly below the template's `low_confidence_threshold`, a QA sample
        is auto-queued in `QUEUED` status with `sampling_reason`
        `LOW_CONFIDENCE` and `created_by_user_id` recorded as the literal
        string `system`."

        Design: Difficulty/boundary_precision_check/low_confidence_sampling_threshold_89_vs_90
        """
        patient = create_patient(client)
        physician = create_physician(client)
        draft_id, attested, headers = self._attest_with_multiplier(
            client, patient, physician, 1.1
        )
        assert attested["completeness_score"] == 89, (
            "multiplier 1.1: 100 - round_half_up(11) = 89, got {0}".format(
                attested["completeness_score"]
            )
        )
        samples, _meta = validate_paginated(
            client.list_draft_qa_samples(draft_id, headers=headers)
        )
        assert len(samples) == 1, "89 is strictly below 90, one sample expected"
        assert samples[0]["sampling_reason"] == "LOW_CONFIDENCE"
        assert samples[0]["status"] == "QUEUED"

    def test_score_90_does_not_queue(self, client):
        """PRD 3.5: "And if the snapshot `completeness_at_attestation` is
        strictly below the template's `low_confidence_threshold`, a QA sample
        is auto-queued in `QUEUED` status with `sampling_reason`
        `LOW_CONFIDENCE` and `created_by_user_id` recorded as the literal
        string `system`."
        PRD 3.1: "`low_confidence_threshold` (default 90, between 0 and 100)
        sets the completeness bar below which attested notes auto-queue a
        low-confidence QA sample."

        Design: Difficulty/boundary_precision_check/low_confidence_sampling_threshold_89_vs_90
        """
        patient = create_patient(client)
        physician = create_physician(client)
        draft_id, attested, headers = self._attest_with_multiplier(
            client, patient, physician, 1.0
        )
        assert attested["completeness_score"] == 90, (
            "multiplier 1.0: 100 - 10 = 90, got {0}".format(
                attested["completeness_score"]
            )
        )
        samples, _meta = validate_paginated(
            client.list_draft_qa_samples(draft_id, headers=headers)
        )
        assert len(samples) == 0, "90 is NOT below the threshold; no sample"


class TestRetentionEligibilityExactInstantBoundary:
    """One second before ended_at + 30 days the capture survives; exactly at
    that instant the sweep expires it."""

    def _setup(self, client):
        """TRANSCRIBED capture stopped 2026-09-01T10:02:00Z, retention 30."""
        patient = create_patient(client)
        physician = create_physician(client)
        set_clock(client, "2026-09-01T10:00:00Z")
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        capture = start_capture(client, encounter, physician)
        set_clock(client, "2026-09-01T10:02:00Z")
        capture = stop_capture(client, capture, physician)
        capture = transcribe(client, capture)
        headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        return {"capture": capture, "headers": headers}

    def test_one_second_before_not_expired(self, client):
        """PRD 3.8: "a capture is eligible when the current logical time is
        at or past its `ended_at` plus `retention_days_effective` whole days
        (the boundary instant exactly on the deadline is eligible) and its
        `legal_hold` is false"

        Design: Difficulty/boundary_precision_check/retention_eligibility_exact_instant_boundary
        """
        w = self._setup(client)
        set_clock(client, "2026-10-01T10:01:59Z")
        get_success_data(client.run_retention_sweep(headers=ADMIN))
        capture = get_success_data(
            client.get_audio_capture(w["capture"]["id"], headers=w["headers"])
        )
        assert capture["status"] == "TRANSCRIBED", (
            "one second before the eligibility instant the capture survives"
        )

    def test_exactly_at_deadline_expires(self, client):
        """PRD 3.8: "a capture is eligible when the current logical time is
        at or past its `ended_at` plus `retention_days_effective` whole days
        (the boundary instant exactly on the deadline is eligible) and its
        `legal_hold` is false; eligible captures move to `RETENTION_EXPIRED`
        with `purge_reason` `RETENTION`."

        Design: Difficulty/boundary_precision_check/retention_eligibility_exact_instant_boundary
        """
        w = self._setup(client)
        set_clock(client, "2026-10-01T10:01:59Z")
        get_success_data(client.run_retention_sweep(headers=ADMIN))
        set_clock(client, "2026-10-01T10:02:00Z")
        get_success_data(client.run_retention_sweep(headers=ADMIN))
        capture = get_success_data(
            client.get_audio_capture(w["capture"]["id"], headers=w["headers"])
        )
        assert capture["status"] == "RETENTION_EXPIRED"
        assert capture["purge_reason"] == "RETENTION"
