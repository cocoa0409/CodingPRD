"""Non-linear state machines: the NoteDraft revision/amendment cycle and the
Encounter's three parallel state dimensions.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.fixtures import (
    create_draft,
    create_encounter,
    edit_draft,
    grant_consent,
    ready_world,
    start_capture,
    start_encounter,
    stop_capture,
    transcribe,
)


class TestNoteDraftRevisionAndAmendmentCycle:
    """IN_REVIEW -> DRAFT via regenerate, then the full amendment loop
    ATTESTED -> AMENDED -> IN_REVIEW -> ATTESTED with attestation types."""

    def _drive_full_cycle(self, client):
        world = ready_world(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("hpi", "MAJOR", True),
                f.field_spec("exam", "MAJOR", True),
                f.field_spec("plan", "MAJOR", True),
                f.field_spec("ros", "MINOR", True),
            ],
        )
        physician = world["physician"]
        headers = world["physician_headers"]
        draft = create_draft(
            client, world["encounter"], physician, world["template"]
        )
        draft = edit_draft(
            client, draft, physician, [f.field_update("chief_complaint", "syncope")]
        )
        draft = get_success_data(client.submit_review(draft["id"], headers=headers))

        regen = get_success_data(client.regenerate_draft(draft["id"], headers=headers))
        get_success_data(client.submit_review(draft["id"], headers=headers))
        current = get_success_data(client.get_note_draft(draft["id"], headers=headers))
        edited = get_success_data(
            client.patch_note_draft(
                draft["id"],
                f.patch_note_draft_payload(
                    current["version"], [f.field_update("ros", "unremarkable")]
                ),
                headers=headers,
            )
        )
        get_success_data(client.submit_review(draft["id"], headers=headers))
        attested = get_success_data(client.attest_draft(draft["id"], headers=headers))
        amended = get_success_data(client.amend_draft(draft["id"], headers=headers))
        get_success_data(client.submit_review(draft["id"], headers=headers))
        reattested = get_success_data(client.attest_draft(draft["id"], headers=headers))
        attestations, _meta = validate_paginated(
            client.list_draft_attestations(draft["id"], headers=headers)
        )
        final = get_success_data(client.get_note_draft(draft["id"], headers=headers))
        return {
            "regen": regen,
            "edited": edited,
            "attested": attested,
            "amended": amended,
            "reattested": reattested,
            "attestations": attestations,
            "final": final,
        }

    def test_regenerate_returns_to_draft_with_full_score(self, client):
        """PRD 3.4: "Regeneration moves the draft from `IN_REVIEW` back to
        `DRAFT`, increments `regeneration_count`, recomputes the
        `completeness_score`, returns the encounter's `documentation_status`
        to `DRAFTING`, and increments the draft's `version`."
        PRD 3.4: "every field whose `source` is not `MANUAL` is refilled from
        the transcript (its `field_value` becomes the literal prefix
        `drafted:` followed by its `field_key`, its `source` becomes `AUDIO`,
        and `validated` resets to false), while `MANUAL` fields are preserved
        untouched."

        Design: Difficulty/non_linear_state_machine/note_draft_revision_and_amendment_cycle
        """
        out = self._drive_full_cycle(client)
        assert out["regen"]["status"] == "DRAFT", (
            "regenerate is IN_REVIEW -> DRAFT, got {0}".format(out["regen"]["status"])
        )
        assert out["regen"]["completeness_score"] == 100, (
            "AUDIO refill completes every field; got {0}".format(
                out["regen"]["completeness_score"]
            )
        )
        assert out["edited"]["status"] == "EDITED", (
            "PATCH from IN_REVIEW returns the draft to EDITED, got {0}".format(
                out["edited"]["status"]
            )
        )

    def test_amendment_loop_records_amendment_attestation(self, client):
        """PRD 3.5: "its `attestation_type` is `INITIAL` when the draft's
        `amendment_count` is zero and `AMENDMENT` for every re-attestation
        after an amend cycle"
        PRD 3.5: "The author opens an amendment on an `ATTESTED` draft, which
        moves it to `AMENDED`, increments `amendment_count`, sets the
        encounter's `documentation_status` to `AMENDED`, and decrements
        `notes_attested` on the metric row of the attestation period —
        compensating the earlier increment, so the live counter always equals
        the number of the physician's currently `ATTESTED` drafts attested in
        that period."

        Design: Difficulty/non_linear_state_machine/note_draft_revision_and_amendment_cycle
        """
        out = self._drive_full_cycle(client)
        assert out["attested"]["status"] == "ATTESTED"
        assert out["amended"]["status"] == "AMENDED"
        assert out["reattested"]["status"] == "ATTESTED"
        assert out["final"]["regeneration_count"] == 1
        assert out["final"]["amendment_count"] == 1
        attestations = out["attestations"]
        assert len(attestations) == 2, "expected INITIAL plus AMENDMENT rows"
        assert attestations[0]["attestation_type"] == "INITIAL"
        assert attestations[1]["attestation_type"] == "AMENDMENT"


class TestEncounterParallelStateDimensions:
    """encounter_status, audio_status and documentation_status move
    independently on one encounter row."""

    def _drive(self, client):
        world = ready_world(
            client,
            field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)],
        )
        headers = world["physician_headers"]
        patient = world["patient"]
        physician = world["physician"]
        template = world["template"]

        enc2 = create_encounter(client, patient, physician)
        grant_consent(client, enc2, patient)
        enc2 = start_encounter(client, enc2, physician)
        after_start = dict(enc2)
        cap = start_capture(client, enc2, physician)
        while_recording = get_success_data(
            client.get_encounter(enc2["id"], headers=headers)
        )
        stop_capture(client, cap, physician)
        transcribe(client, cap)
        after_stop = get_success_data(
            client.get_encounter(enc2["id"], headers=headers)
        )
        get_success_data(
            client.create_note_draft(
                enc2["id"],
                f.create_note_draft_payload(template["id"], after_stop["version"]),
                headers=headers,
            )
        )
        after_draft = get_success_data(
            client.get_encounter(enc2["id"], headers=headers)
        )
        return {
            "after_start": after_start,
            "while_recording": while_recording,
            "after_stop": after_stop,
            "after_draft": after_draft,
        }

    def test_dimensions_at_start_and_while_recording(self, client):
        """PRD 3.2: "The first, `encounter_status`, begins at `SCHEDULED`"
        PRD 3.2: "The second dimension, `audio_status`, begins at
        `NOT_RECORDING`, becomes `RECORDING_ACTIVE` while any capture is
        `RECORDING` or `PAUSED`, and settles at `AUDIO_STOPPED` when recording
        ceases."
        PRD 3.2: "The three dimensions advance independently: audio and
        documentation are moved purely by side effects of capture and draft
        transitions, and attestation remains allowed after the encounter is
        `COMPLETED` to support after-hours charting."

        Design: Difficulty/non_linear_state_machine/encounter_parallel_state_dimensions
        """
        out = self._drive(client)
        after_start = out["after_start"]
        assert after_start["encounter_status"] == "IN_PROGRESS"
        assert after_start["audio_status"] == "NOT_RECORDING"
        assert after_start["documentation_status"] == "NOT_STARTED"
        assert out["while_recording"]["audio_status"] == "RECORDING_ACTIVE"

    def test_stop_and_draft_move_only_their_own_dimensions(self, client):
        """PRD 3.3: "Stopping — permitted from either `RECORDING` or `PAUSED`
        — moves the capture to `CAPTURED`, stamps `ended_at`, finalizes
        `recorded_seconds` as the sum of the `RECORDING` intervals between
        `started_at` and `ended_at` with paused time excluded, and sets the
        encounter's `audio_status` to `AUDIO_STOPPED`."
        PRD 3.4: "The encounter's `documentation_status` becomes `DRAFTING`
        and the encounter's `version` increments."

        Design: Difficulty/non_linear_state_machine/encounter_parallel_state_dimensions
        """
        out = self._drive(client)
        after_stop = out["after_stop"]
        assert after_stop["audio_status"] == "AUDIO_STOPPED"
        assert after_stop["encounter_status"] == "IN_PROGRESS", (
            "stopping audio must not move encounter_status"
        )
        after_draft = out["after_draft"]
        assert after_draft["encounter_status"] == "IN_PROGRESS"
        assert after_draft["audio_status"] == "AUDIO_STOPPED"
        assert after_draft["documentation_status"] == "DRAFTING"
