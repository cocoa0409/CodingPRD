"""Compensating invariants: attest/amend conserve the notes_attested counter,
and pause/resume conserves recorded_seconds.
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
    create_patient,
    create_physician,
    edit_draft,
    grant_consent,
    ready_world,
    set_clock,
    start_capture,
    start_encounter,
    stop_capture,
    submit_review,
)


class TestAttestAmendReattestConserveNotesAttested:
    """The forward action attest (+1) and the compensating action amend (-1)
    leave the counter equal to the number of currently-ATTESTED drafts."""

    def _setup_in_review(self, client):
        """Draft IN_REVIEW, completeness 100 (single CRITICAL field filled)."""
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        physician = world["physician"]
        draft = create_draft(
            client, world["encounter"], physician, world["template"]
        )
        draft = edit_draft(
            client, draft, physician, [f.field_update("chief_complaint", "cough")]
        )
        submit_review(client, draft, physician)
        world["draft"] = draft
        return world

    def _notes_attested(self, client, world):
        rows, _meta = validate_paginated(
            client.list_documentation_metrics(
                world["physician"]["id"], headers=world["physician_headers"]
            )
        )
        assert len(rows) == 1, "exactly one metric row for the attestation month"
        return rows[0]["notes_attested"]

    def test_attest_increments_and_amend_compensates(self, client):
        """PRD 3.5: "The physician's documentation metric for the calendar
        month containing `attested_at` is auto-created as a `PROVISIONAL` row
        if absent, and its `notes_attested` counter increments by 1."
        PRD 3.5: "The author opens an amendment on an `ATTESTED` draft, which
        moves it to `AMENDED`, increments `amendment_count`, sets the
        encounter's `documentation_status` to `AMENDED`, and decrements
        `notes_attested` on the metric row of the attestation period —
        compensating the earlier increment, so the live counter always equals
        the number of the physician's currently `ATTESTED` drafts attested in
        that period."

        Design: Difficulty/compensating_invariant/attest_amend_reattest_conserve_notes_attested
        """
        world = self._setup_in_review(client)
        headers = world["physician_headers"]
        draft_id = world["draft"]["id"]
        get_success_data(client.attest_draft(draft_id, headers=headers))
        assert self._notes_attested(client, world) == 1
        get_success_data(client.amend_draft(draft_id, headers=headers))
        assert self._notes_attested(client, world) == 0, (
            "the compensating action exactly undoes the increment"
        )

    def test_reattest_restores_the_counter(self, client):
        """PRD 3.5: "The amended draft re-enters the normal flow: it may be
        edited, submitted back to `IN_REVIEW`, and re-attested (producing an
        `Attestation` of type `AMENDMENT`)."

        Design: Difficulty/compensating_invariant/attest_amend_reattest_conserve_notes_attested
        """
        world = self._setup_in_review(client)
        headers = world["physician_headers"]
        draft_id = world["draft"]["id"]
        get_success_data(client.attest_draft(draft_id, headers=headers))
        assert self._notes_attested(client, world) == 1
        get_success_data(client.amend_draft(draft_id, headers=headers))
        assert self._notes_attested(client, world) == 0
        get_success_data(client.submit_review(draft_id, headers=headers))
        get_success_data(client.attest_draft(draft_id, headers=headers))
        assert self._notes_attested(client, world) == 1, (
            "counter equals the count of currently-ATTESTED drafts"
        )


class TestPauseResumeConserveRecordedSeconds:
    """The pause/resume pair leaves recorded_seconds equal to wall time minus
    paused time."""

    def _drive(self, client):
        """Record 16:00:00 -> pause 16:01:00 -> resume 16:01:15 -> stop
        16:02:00."""
        patient = create_patient(client)
        physician = create_physician(client)
        headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        set_clock(client, "2026-09-01T16:00:00Z")
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        capture = start_capture(client, encounter, physician)
        set_clock(client, "2026-09-01T16:01:00Z")
        get_success_data(client.pause_capture(capture["id"], headers=headers))
        set_clock(client, "2026-09-01T16:01:15Z")
        get_success_data(client.resume_capture(capture["id"], headers=headers))
        set_clock(client, "2026-09-01T16:02:00Z")
        return validate_success(client.stop_capture(capture["id"], headers=headers))

    def test_recorded_seconds_exclude_the_pause(self, client):
        """PRD 3.3: "Stopping — permitted from either `RECORDING` or `PAUSED`
        — moves the capture to `CAPTURED`, stamps `ended_at`, finalizes
        `recorded_seconds` as the sum of the `RECORDING` intervals between
        `started_at` and `ended_at` with paused time excluded, and sets the
        encounter's `audio_status` to `AUDIO_STOPPED`."

        Design: Difficulty/compensating_invariant/pause_resume_conserve_recorded_seconds
        """
        stopped = self._drive(client)
        assert stopped["status"] == "CAPTURED"
        assert stopped["recorded_seconds"] == 105, (
            "RECORDING intervals 60s + 45s; the 15s pause is excluded; got "
            "{0}".format(stopped["recorded_seconds"])
        )

    def test_pause_resume_pair_is_compensating(self, client):
        """PRD 3.3: "The pause/resume pair is a compensating invariant: it
        leaves `recorded_seconds` unchanged."

        Design: Difficulty/compensating_invariant/pause_resume_conserve_recorded_seconds
        """
        stopped = self._drive(client)
        # recorded (105) + paused (15) == wall (120): nothing gained or lost.
        assert stopped["recorded_seconds"] + 15 == 120
