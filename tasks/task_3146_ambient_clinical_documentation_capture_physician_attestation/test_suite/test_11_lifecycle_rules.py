"""Lifecycle corners: invalid transitions, terminal-state lockdowns, the
suggestion expiry side effect at attestation, the QA appeal cap, rescore
segregation, and the encounter's initial state dimensions.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    create_draft,
    create_encounter,
    create_patient,
    create_physician,
    create_qa_auditor,
    edit_draft,
    grant_consent,
    ready_world,
    set_clock,
    start_capture,
    start_encounter,
    submit_review,
    world_with_attested_draft,
)
from test_helpers.test_users import COMPLIANCE, make_qa_auditor_headers


class TestStartInProgressEncounter:
    def test_second_start_returns_409(self, client):
        """PRD 3.2: "starting the encounter (attending physician only) moves
        `SCHEDULED` to `IN_PROGRESS` and stamps `started_at` from the logical
        clock"

        Design: Corner/state_machines/corner_start_in_progress_encounter_returns_409
        """
        patient = create_patient(client)
        physician = create_physician(client)
        encounter = create_encounter(client, patient, physician)
        encounter = start_encounter(client, encounter, physician)
        headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        resp = client.start_encounter(encounter["id"], headers=headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestCancelledEncounterTerminalLockdown:
    def test_start_after_cancel_returns_409(self, client):
        """PRD 3.2: "cancellation from either `SCHEDULED` or `IN_PROGRESS` —
        available to a `Physician` or a `ComplianceOfficer` — moves the
        encounter to `CANCELLED`, stamps `ended_at`, and records the optional
        `cancel_reason` from the request."

        Design: Corner/state_machines/corner_cancelled_encounter_terminal_lockdown_returns_409
        """
        patient = create_patient(client)
        physician = create_physician(client)
        encounter = create_encounter(client, patient, physician)
        headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        get_success_data(
            client.cancel_encounter(
                encounter["id"], {"cancel_reason": "no-show"}, headers=headers
            )
        )
        resp = client.start_encounter(encounter["id"], headers=headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestRegenerateFromDraftRejected:
    def test_regenerate_requires_in_review(self, client):
        """PRD 3.4: "Regeneration moves the draft from `IN_REVIEW` back to
        `DRAFT`, increments `regeneration_count`, recomputes the
        `completeness_score`, returns the encounter's `documentation_status`
        to `DRAFTING`, and increments the draft's `version`."

        Design: Corner/state_machines/corner_regenerate_from_draft_status_returns_409
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        resp = client.regenerate_draft(draft["id"], headers=world["physician_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestPatchAttestedNoteLocked:
    def test_patch_on_attested_returns_409(self, client):
        """PRD 3.4: "Edits are permitted while the draft is `DRAFT`,
        `EDITED`, `IN_REVIEW`, or `AMENDED`; an edit on an `ATTESTED` or
        `VOID` draft is rejected with `ERR_NOTE_LOCKED`."

        Design: Corner/state_machines/corner_patch_attested_note_locked_returns_409
        """
        world = world_with_attested_draft(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        headers = world["physician_headers"]
        current = get_success_data(
            client.get_note_draft(world["draft"]["id"], headers=headers)
        )
        resp = client.patch_note_draft(
            world["draft"]["id"],
            f.patch_note_draft_payload(
                current["version"],
                [f.field_update("chief_complaint", "edited post-attestation")],
            ),
            headers=headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOTE_LOCKED.value, 409)


class TestUnconfirmedSuggestionsExpireOnAttestation:
    def test_attestation_expires_suggested_and_locks_confirm(self, client):
        """PRD 3.5: "Every code suggestion of the draft still in `SUGGESTED`
        or `MODIFIED` expires (`SUGGESTED` → `EXPIRED`, `MODIFIED` →
        `EXPIRED`) and drops out of both billing variants, so
        `billing_provisional_cents` and `billing_final_cents` are
        recomputed."
        PRD 3.6: "Confirming or rejecting or modifying is allowed only while
        the owning draft is not `ATTESTED` (and not `VOID`); once the draft
        is `ATTESTED` or `VOID`, all three actions are rejected with
        `ERR_CODE_SUGGESTION_LOCKED`."

        Design: Corner/state_machines/corner_unconfirmed_suggestions_expire_on_attestation
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        physician = world["physician"]
        headers = world["physician_headers"]
        draft = create_draft(client, world["encounter"], physician, world["template"])
        draft = edit_draft(
            client, draft, physician, [f.field_update("chief_complaint", "fever")]
        )
        suggestions = validate_success(
            client.create_code_suggestions(
                draft["id"],
                {"suggestions": [f.diagnosis_suggestion_payload("D500")]},
                headers=headers,
            ),
            201,
        )
        suggestion_id = suggestions[0]["id"]
        submit_review(client, draft, physician)
        get_success_data(client.attest_draft(draft["id"], headers=headers))
        rows, _meta = validate_paginated(
            client.list_code_suggestions(draft["id"], headers=headers)
        )
        assert rows[0]["status"] == "EXPIRED", (
            "attestation expired the unconfirmed suggestion"
        )
        resp = client.confirm_suggestion(suggestion_id, headers=headers)
        validate_error(resp, ApiErrorId.ERR_CODE_SUGGESTION_LOCKED.value, 409)


def _scored_sample_with_two_appeals(client, world, qa_a, qa_b):
    """Drive a manual sample through score/appeal/rescore twice. Returns the
    sample id with appeal_count == 2."""
    headers = world["physician_headers"]
    sample = get_success_data(
        client.queue_qa_sample(world["draft"]["id"], headers=COMPLIANCE)
    )
    get_success_data(
        client.assign_qa_sample(
            sample["id"], {"auditor_id": qa_a["id"]}, headers=COMPLIANCE
        )
    )
    get_success_data(
        client.score_qa_sample(
            sample["id"],
            f.qa_scores_payload(80, 90, 100),
            headers=make_qa_auditor_headers(qa_a["id"]),
        )
    )
    get_success_data(
        client.appeal_qa_sample(sample["id"], {"reason": "disagree"}, headers=headers)
    )
    get_success_data(
        client.rescore_qa_sample(
            sample["id"],
            f.qa_scores_payload(90, 90, 90),
            headers=make_qa_auditor_headers(qa_b["id"]),
        )
    )
    get_success_data(
        client.appeal_qa_sample(
            sample["id"], {"reason": "still disagree"}, headers=headers
        )
    )
    get_success_data(
        client.rescore_qa_sample(
            sample["id"],
            f.qa_scores_payload(95, 95, 95),
            headers=make_qa_auditor_headers(qa_a["id"]),
        )
    )
    return sample


class TestQaAppealMaxTwo:
    def test_third_appeal_returns_422(self, client):
        """PRD 3.7: "At most two appeals are permitted per sample: an appeal
        when `appeal_count` has reached 2 is rejected with
        `ERR_QA_MAX_APPEALS`."

        Design: Corner/state_machines/corner_qa_appeal_max_two_returns_422
        """
        world = world_with_attested_draft(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        qa_a = create_qa_auditor(client, employee_code="QA-A-1", specialty_codes=["CARD"])
        qa_b = create_qa_auditor(client, employee_code="QA-B-1", specialty_codes=["CARD"])
        sample = _scored_sample_with_two_appeals(client, world, qa_a, qa_b)
        resp = client.appeal_qa_sample(
            sample["id"], {"reason": "third appeal"},
            headers=world["physician_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_QA_MAX_APPEALS.value, 422)


class TestRescoreBySameScorerForbidden:
    def test_last_scorer_cannot_rescore(self, client):
        """PRD 3.7: "An appealed sample is rescored (`APPEALED` → `RESCORED`)
        by a different auditor: the rescorer must differ from
        `last_scorer_id` and must also differ from the sample's
        `created_by_user_id`, with violations rejected as
        `ERR_QA_SELF_REVIEW_FORBIDDEN`."

        Design: Corner/state_machines/corner_rescore_by_same_scorer_returns_403
        """
        world = world_with_attested_draft(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        qa_a = create_qa_auditor(client, employee_code="QA-A-1", specialty_codes=["CARD"])
        sample = get_success_data(
            client.queue_qa_sample(world["draft"]["id"], headers=COMPLIANCE)
        )
        get_success_data(
            client.assign_qa_sample(
                sample["id"], {"auditor_id": qa_a["id"]}, headers=COMPLIANCE
            )
        )
        get_success_data(
            client.score_qa_sample(
                sample["id"],
                f.qa_scores_payload(80, 90, 100),
                headers=make_qa_auditor_headers(qa_a["id"]),
            )
        )
        get_success_data(
            client.appeal_qa_sample(
                sample["id"], {"reason": "disagree"},
                headers=world["physician_headers"],
            )
        )
        resp = client.rescore_qa_sample(
            sample["id"],
            f.qa_scores_payload(95, 95, 95),
            headers=make_qa_auditor_headers(qa_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QA_SELF_REVIEW_FORBIDDEN.value, 403)


class TestCompleteWithActiveRecording:
    def test_complete_blocked_while_recording(self, client):
        """PRD 3.2: "completion is refused while any capture of the encounter
        is still `RECORDING` or `PAUSED`."

        Design: Corner/state_machines/corner_complete_with_active_recording_returns_409
        """
        patient = create_patient(client)
        physician = create_physician(client)
        set_clock(client, "2026-09-01T16:00:00Z")
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        start_capture(client, encounter, physician)
        headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        resp = client.complete_encounter(encounter["id"], headers=headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestVoidDraftTerminalLockdown:
    def test_submit_review_after_void_returns_409(self, client):
        """PRD 3.4: "A draft that will never be used can be voided by its
        author or by a `ComplianceOfficer` from any of `DRAFT`, `EDITED`,
        `IN_REVIEW`, or `AMENDED`; `VOID` is terminal."

        Design: Corner/state_machines/corner_void_draft_terminal_lockdown_returns_409
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        headers = world["physician_headers"]
        get_success_data(client.void_draft(draft["id"], headers=headers))
        resp = client.submit_review(draft["id"], headers=headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestEncounterInitialStateDimensions:
    def test_new_encounter_state_dimensions(self, client):
        """PRD 3.2: "The first, `encounter_status`, begins at `SCHEDULED`"
        PRD 3.2: "The second dimension, `audio_status`, begins at
        `NOT_RECORDING`"
        PRD 3.2: "The third, `documentation_status`, begins at `NOT_STARTED`
        and mirrors the active note draft's status (`DRAFTING`, `IN_REVIEW`,
        `ATTESTED`, `AMENDED`)."

        Design: Corner/state_machines/corner_encounter_initial_state_dimensions
        """
        patient = create_patient(client)
        physician = create_physician(client)
        encounter = create_encounter(client, patient, physician)
        assert encounter["encounter_status"] == "SCHEDULED"
        assert encounter["audio_status"] == "NOT_RECORDING"
        assert encounter["documentation_status"] == "NOT_STARTED"
