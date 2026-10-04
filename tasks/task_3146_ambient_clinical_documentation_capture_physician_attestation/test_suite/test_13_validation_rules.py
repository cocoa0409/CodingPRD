"""Validation corners: auth presence, authorization precedence, ownership,
signage, duplicate consent, transcription precondition, inactive template,
completeness floor, suggestion ceiling, OCC, billing cap, legal hold,
suspension, field-key mismatch, speaker role domain, QA hold, auditor
specialty, self-review, consent-required, active-capture, expired-consent
transcription, amend state, and finalized metric recompute.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    create_draft,
    create_encounter,
    create_note_template,
    create_patient,
    create_physician,
    create_qa_auditor,
    edit_draft,
    grant_consent,
    ready_world,
    set_clock,
    start_capture,
    start_encounter,
    stop_capture,
    submit_review,
    world_with_attested_draft,
)
from test_helpers.test_users import (
    ADMIN,
    COMPLIANCE,
    make_patient_headers,
    make_physician_headers,
    make_qa_auditor_headers,
)


class TestMissingAuthHeaders:
    def test_no_headers_returns_401(self, client):
        """PRD 2.1: "A request with either header missing, or whose role is
        not one of the five declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/corner_missing_auth_headers_returns_401
        """
        resp = client.get_patient(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


class TestAuthorizationPrecedesExistence:
    def test_physician_cannot_create_patient(self, client):
        """PRD 2.1: "A request whose role is authenticated but is not
        permitted for the target endpoint — or which fails an entity-backed
        ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD 2.9: "Authentication (`ERR_UNAUTHENTICATED`) is checked first,
        then authorization and ownership (`ERR_UNAUTHORIZED`), then
        left-to-right path resolution (`ERR_NOT_FOUND`)"

        Design: Corner/validations/corner_authz_beats_existence_wrong_role_returns_403
        """
        physician = create_physician(client)
        resp = client.create_patient(
            {"mrn": "MRN-V2-1", "full_name": "Pat V2"},
            headers=make_physician_headers(physician["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


class TestNonAuthorPhysicianPatch:
    def test_other_physician_cannot_edit(self, client):
        """PRD 3.4: "Only the author may work a draft."

        Design: Corner/validations/corner_non_author_physician_patch_returns_403
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        other = create_physician(client, npi="NPI-OTHER-1")
        resp = client.patch_note_draft(
            draft["id"],
            f.patch_note_draft_payload(
                draft["version"], [f.field_update("chief_complaint", "intruder edit")]
            ),
            headers=make_physician_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


class TestConsentGrantWithoutSignage:
    def test_signage_false_returns_422(self, client):
        """PRD 3.2: "Signage is non-negotiable: a grant with `signage_posted`
        other than true is rejected with `ERR_SIGNAGE_NOT_POSTED`."

        Design: Corner/validations/corner_consent_grant_without_signage_returns_422
        """
        patient = create_patient(client)
        physician = create_physician(client)
        encounter = create_encounter(client, patient, physician)
        resp = client.grant_consent(
            encounter["id"],
            f.grant_consent_payload(patient["id"], signage_posted=False),
            headers=make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SIGNAGE_NOT_POSTED.value, 422)


class TestDuplicateConsent:
    def test_second_granted_consent_returns_409(self, client):
        """PRD 3.2: "At most one consent may be `GRANTED` per encounter; a
        second grant while one is active is rejected with
        `ERR_DUPLICATE_CONSENT`."

        Design: Corner/validations/corner_duplicate_consent_returns_409
        """
        patient = create_patient(client)
        physician = create_physician(client)
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient, captured_via="VERBAL")
        resp = client.grant_consent(
            encounter["id"],
            f.grant_consent_payload(patient["id"], captured_via="PORTAL"),
            headers=make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONSENT.value, 409)


class TestDraftCreateWithoutTranscribedAudio:
    def test_stopped_but_not_transcribed_returns_422(self, client):
        """PRD 3.4: "Generation requires a `GRANTED` consent on the encounter
        (`ERR_CONSENT_NOT_ACTIVE` otherwise), an active template
        (`ERR_TEMPLATE_INACTIVE` otherwise), and at least one `TRANSCRIBED`
        capture on the encounter (`ERR_NO_TRANSCRIBED_AUDIO` otherwise)."

        Design: Corner/validations/corner_draft_create_without_transcribed_audio_returns_422
        """
        patient = create_patient(client)
        physician = create_physician(client)
        template = create_note_template(client)
        set_clock(client, "2026-09-01T16:00:00Z")
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        capture = start_capture(client, encounter, physician)
        stop_capture(client, capture, physician)
        headers = make_physician_headers(physician["id"])
        enc_v = get_success_data(
            client.get_encounter(encounter["id"], headers=headers)
        )["version"]
        resp = client.create_note_draft(
            encounter["id"],
            f.create_note_draft_payload(template["id"], enc_v),
            headers=headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_TRANSCRIBED_AUDIO.value, 422)


class TestInactiveTemplateRejected:
    def test_deactivated_template_returns_422(self, client):
        """PRD 3.1: "A template's `active` flag (default true) governs
        whether new drafts may be created from it"
        PRD 3.4: "Generation requires a `GRANTED` consent on the encounter
        (`ERR_CONSENT_NOT_ACTIVE` otherwise), an active template
        (`ERR_TEMPLATE_INACTIVE` otherwise), and at least one `TRANSCRIBED`
        capture on the encounter (`ERR_NO_TRANSCRIBED_AUDIO` otherwise)."

        Design: Corner/validations/corner_inactive_template_rejected_returns_422
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        get_success_data(
            client.update_note_template(
                world["template"]["id"], {"active": False}, headers=ADMIN
            )
        )
        headers = world["physician_headers"]
        enc_v = get_success_data(
            client.get_encounter(world["encounter"]["id"], headers=headers)
        )["version"]
        resp = client.create_note_draft(
            world["encounter"]["id"],
            f.create_note_draft_payload(world["template"]["id"], enc_v),
            headers=headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_INACTIVE.value, 422)


class TestAttestBelowCompletenessThreshold:
    def test_score_65_returns_422(self, client):
        """PRD 3.5: "and the draft's `completeness_score` must be at least 80
        — otherwise `ERR_NOTE_INCOMPLETE`."
        PRD 3.4: "Each missing field carries a penalty by importance: 25
        points for `CRITICAL`, 10 for `MAJOR`, 5 for `MINOR`."

        Design: Corner/validations/corner_attest_below_completeness_threshold_returns_422
        """
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
        draft = create_draft(
            client, world["encounter"], physician, world["template"]
        )
        headers = world["physician_headers"]
        body = validate_success(
            client.patch_note_draft(
                draft["id"],
                f.patch_note_draft_payload(
                    draft["version"], [f.field_update("chief_complaint", "fever")]
                ),
                headers=headers,
            )
        )
        assert body["completeness_score"] == 65, (
            "missing 3x MAJOR + 1x MINOR = 35 penalty, got {0}".format(
                body["completeness_score"]
            )
        )
        submit_review(client, draft, physician)
        validate_error(
            client.attest_draft(draft["id"], headers=headers),
            ApiErrorId.ERR_NOTE_INCOMPLETE.value,
            422,
        )


class TestCodeSuggestionLimitBoundary:
    def test_ninth_active_suggestion_returns_422(self, client):
        """PRD 3.6: "After the batch lands, the number of active suggestions
        on the draft — those in `SUGGESTED` or `MODIFIED` — must not exceed
        8; a batch that would push past that ceiling is rejected with
        `ERR_CODE_LIMIT_EXCEEDED`."

        Design: Corner/validations/corner_code_suggestion_limit_boundary_returns_422
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        headers = world["physician_headers"]
        eight = [
            f.diagnosis_suggestion_payload("D7{0:02d}".format(i))
            for i in range(1, 9)
        ]
        validate_success(
            client.create_code_suggestions(
                draft["id"], {"suggestions": eight}, headers=headers
            ),
            201,
        )
        resp = client.create_code_suggestions(
            draft["id"],
            {"suggestions": [f.diagnosis_suggestion_payload("D709")]},
            headers=headers,
        )
        validate_error(resp, ApiErrorId.ERR_CODE_LIMIT_EXCEEDED.value, 422)


class TestNoteEditStaleVersion:
    def test_replayed_version_returns_412(self, client):
        """PRD 2.7: "Editing a note draft requires the request to carry
        `expected_note_draft_version`, a non-optional input holding the
        `version` of the `NoteDraft` the client last observed. If that value
        does not match the draft's current `version` — because another write
        (a physician edit, a regenerate cycle, or a consent-driven cascade
        that recomputed completeness) has advanced it since the client last
        read the draft — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/validations/corner_note_edit_stale_version_returns_412
        """
        world = ready_world(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("hpi", "MAJOR", True),
            ],
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        headers = world["physician_headers"]
        first = validate_success(
            client.patch_note_draft(
                draft["id"],
                f.patch_note_draft_payload(
                    draft["version"], [f.field_update("chief_complaint", "fever")]
                ),
                headers=headers,
            )
        )
        assert first["version"] == draft["version"] + 1
        resp = client.patch_note_draft(
            draft["id"],
            f.patch_note_draft_payload(
                draft["version"], [f.field_update("hpi", "stale edit")]
            ),
            headers=headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


class TestNoteDraftCreateStaleEncounterVersion:
    def test_second_create_with_old_version_returns_412(self, client):
        """PRD 2.7: "Generating a note draft against an encounter requires
        the request to carry `expected_encounter_version`, a non-optional
        input holding the `version` of the parent `Encounter` the client last
        observed. If the encounter's `version` has advanced since then, the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/corner_note_draft_create_stale_encounter_version_returns_412
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        headers = world["physician_headers"]
        enc_v = get_success_data(
            client.get_encounter(world["encounter"]["id"], headers=headers)
        )["version"]
        first = validate_success(
            client.create_note_draft(
                world["encounter"]["id"],
                f.create_note_draft_payload(world["template"]["id"], enc_v),
                headers=headers,
            ),
            201,
        )
        assert first["id"]
        resp = client.create_note_draft(
            world["encounter"]["id"],
            f.create_note_draft_payload(world["template"]["id"], enc_v),
            headers=headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


class TestBillingCapOnConfirm:
    def test_second_confirm_breaches_cap(self, client):
        """PRD 3.6: "A fiscal cap guards confirmation of billing lines: the
        sum of `line_total_cents` over the draft's already-`CONFIRMED`
        billing suggestions plus the line being confirmed must not exceed
        10000000 cents; a confirmation that would breach the cap is rejected
        with `ERR_BILLING_CAP_EXCEEDED`."

        Design: Corner/validations/corner_billing_cap_on_confirm_returns_422
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        headers = world["physician_headers"]
        suggestions = validate_success(
            client.create_code_suggestions(
                draft["id"],
                {
                    "suggestions": [
                        f.billing_suggestion_payload(
                            "B9001", confidence=1.0, unit_fee_cents=6000000
                        ),
                        f.billing_suggestion_payload(
                            "B9002", confidence=1.0, unit_fee_cents=6000000
                        ),
                    ]
                },
                headers=headers,
            ),
            201,
        )
        get_success_data(client.confirm_suggestion(suggestions[0]["id"], headers=headers))
        resp = client.confirm_suggestion(suggestions[1]["id"], headers=headers)
        validate_error(resp, ApiErrorId.ERR_BILLING_CAP_EXCEEDED.value, 422)


class TestLegalHoldBlocksPurge:
    def test_purge_under_hold_returns_422(self, client):
        """PRD 3.3: "A purge on a capture whose `legal_hold` is true is
        rejected with `ERR_LEGAL_HOLD_ACTIVE`"

        Design: Corner/validations/corner_legal_hold_blocks_purge_returns_422
        """
        world = ready_world(client)
        get_success_data(
            client.set_legal_hold(
                world["capture"]["id"], {"hold": True}, headers=COMPLIANCE
            )
        )
        resp = client.purge_capture(world["capture"]["id"], headers=COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_LEGAL_HOLD_ACTIVE.value, 422)
        body = get_success_data(
            client.get_audio_capture(
                world["capture"]["id"], headers=world["physician_headers"]
            )
        )
        assert body["status"] == "TRANSCRIBED", "purge did not happen"


class TestSuspendedPhysicianAttest:
    def test_suspended_author_cannot_attest(self, client):
        """PRD 3.5: "the author's physician `status` must be `ACTIVE` — a
        `SUSPENDED` physician attesting is rejected with
        `ERR_PHYSICIAN_NOT_ACTIVE`"

        Design: Corner/validations/corner_suspended_physician_attest_returns_422
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        physician = world["physician"]
        draft = create_draft(
            client, world["encounter"], physician, world["template"]
        )
        edit_draft(client, draft, physician, [f.field_update("chief_complaint", "fever")])
        submit_review(client, draft, physician)
        get_success_data(
            client.update_physician(
                physician["id"], {"status": "SUSPENDED"}, headers=ADMIN
            )
        )
        resp = client.attest_draft(draft["id"], headers=world["physician_headers"])
        validate_error(resp, ApiErrorId.ERR_PHYSICIAN_NOT_ACTIVE.value, 422)


class TestFieldKeyMismatch:
    def test_unknown_field_key_returns_422(self, client):
        """PRD 3.4: "Every key in `field_updates` must be declared in the
        template's `field_specs`; an unknown key is rejected with
        `ERR_TEMPLATE_FIELD_MISMATCH`."

        Design: Corner/validations/corner_field_key_mismatch_returns_422
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        resp = client.patch_note_draft(
            draft["id"],
            f.patch_note_draft_payload(
                draft["version"], [f.field_update("no_such_field", "x")]
            ),
            headers=world["physician_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TEMPLATE_FIELD_MISMATCH.value, 422)


class TestInvalidSpeakerRole:
    def test_role_outside_enum_returns_400(self, client):
        """PRD 3.3: "A `speaker_role` outside the four declared values is
        rejected with `ERR_SPEAKER_ROLE_INVALID`."

        Design: Corner/validations/corner_invalid_speaker_role_returns_400
        """
        world = ready_world(client)
        set_clock(client, "2026-09-01T16:01:00Z")
        capture = start_capture(client, world["encounter"], world["physician"])
        resp = client.append_segment(
            capture["id"],
            f.segment_payload(
                start_offset_ms=0, end_offset_ms=1000, speaker_role="ALIEN"
            ),
            headers=world["physician_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_SPEAKER_ROLE_INVALID.value, 400)


class TestAttestUnderQaHold:
    def test_assigned_sample_blocks_attestation(self, client):
        """PRD 3.5: "no QA sample of the draft may be `ASSIGNED` — attesting
        under a QA hold is rejected with `ERR_QA_HOLD_ACTIVE`"

        Design: Corner/validations/corner_attest_under_qa_hold_returns_409
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        physician = world["physician"]
        qa_a = create_qa_auditor(client, employee_code="QA-A-1", specialty_codes=["CARD"])
        draft = create_draft(
            client, world["encounter"], physician, world["template"]
        )
        edit_draft(client, draft, physician, [f.field_update("chief_complaint", "fever")])
        submit_review(client, draft, physician)
        sample = get_success_data(
            client.queue_qa_sample(draft["id"], headers=COMPLIANCE)
        )
        get_success_data(
            client.assign_qa_sample(
                sample["id"], {"auditor_id": qa_a["id"]}, headers=COMPLIANCE
            )
        )
        resp = client.attest_draft(draft["id"], headers=world["physician_headers"])
        validate_error(resp, ApiErrorId.ERR_QA_HOLD_ACTIVE.value, 409)


class TestAuditorSpecialtyMismatch:
    def test_ortho_auditor_on_card_sample_returns_422(self, client):
        """PRD 3.7: "The target auditor must be `ACTIVE`, and their
        `specialty_codes` must contain the `specialty_code` of the draft's
        template; a mismatch is rejected with
        `ERR_AUDITOR_SPECIALTY_MISMATCH`."

        Design: Corner/validations/corner_auditor_specialty_mismatch_returns_422
        """
        world = world_with_attested_draft(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        qa_ortho = create_qa_auditor(
            client, employee_code="QA-O-1", specialty_codes=["ORTHO"]
        )
        sample = get_success_data(
            client.queue_qa_sample(world["draft"]["id"], headers=COMPLIANCE)
        )
        resp = client.assign_qa_sample(
            sample["id"], {"auditor_id": qa_ortho["id"]}, headers=COMPLIANCE
        )
        validate_error(resp, ApiErrorId.ERR_AUDITOR_SPECIALTY_MISMATCH.value, 422)


class TestQaCreatorCannotScoreOwnSample:
    def test_creator_scoring_returns_403(self, client):
        """PRD 3.7: "The creator may never score the sample — segregation of
        duties — enforced as `ERR_QA_SELF_REVIEW_FORBIDDEN`."

        Design: Corner/validations/corner_qa_creator_cannot_score_own_sample_returns_403
        """
        world = world_with_attested_draft(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        qa_a = create_qa_auditor(client, employee_code="QA-A-1", specialty_codes=["CARD"])
        qa_headers = make_qa_auditor_headers(qa_a["id"])
        sample = get_success_data(
            client.queue_qa_sample(world["draft"]["id"], headers=qa_headers)
        )
        get_success_data(
            client.assign_qa_sample(
                sample["id"], {"auditor_id": qa_a["id"]}, headers=qa_headers
            )
        )
        resp = client.score_qa_sample(
            sample["id"], f.qa_scores_payload(90, 90, 90), headers=qa_headers
        )
        validate_error(resp, ApiErrorId.ERR_QA_SELF_REVIEW_FORBIDDEN.value, 403)


class TestAudioStartWithoutConsent:
    def test_no_consent_returns_422(self, client):
        """PRD 3.3: "Starting a capture without a `GRANTED` consent is
        rejected with `ERR_CONSENT_REQUIRED`"

        Design: Corner/validations/corner_audio_start_without_consent_returns_422
        """
        patient = create_patient(client)
        physician = create_physician(client)
        set_clock(client, "2026-09-01T16:00:00Z")
        encounter = create_encounter(client, patient, physician)
        encounter = start_encounter(client, encounter, physician)
        resp = client.start_audio_capture(
            encounter["id"],
            f.start_capture_payload(),
            headers=make_physician_headers(physician["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value, 422)


class TestSecondActiveCapture:
    def test_second_capture_while_recording_returns_409(self, client):
        """PRD 3.3: "starting one while another capture of the same encounter
        is `RECORDING` or `PAUSED` is rejected with
        `ERR_CAPTURE_ACTIVE_EXISTS`"

        Design: Corner/validations/corner_second_active_capture_returns_409
        """
        patient = create_patient(client)
        physician = create_physician(client)
        set_clock(client, "2026-09-01T16:00:00Z")
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        start_capture(client, encounter, physician)
        resp = client.start_audio_capture(
            encounter["id"],
            f.start_capture_payload(planned_retention_days=60),
            headers=make_physician_headers(physician["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAPTURE_ACTIVE_EXISTS.value, 409)


class TestTranscriptionAfterConsentExpired:
    def test_transcription_with_expired_consent_returns_422(self, client):
        """PRD 3.3: "Transcription is a deterministic, test-driving step: a
        `PlatformAdmin` may advance a `CAPTURED` capture to `TRANSCRIBED` by
        supplying its `audio_capture_id`, provided the encounter still holds
        a `GRANTED` consent (otherwise `ERR_CONSENT_NOT_ACTIVE`)."

        Design: Corner/validations/corner_transcription_after_consent_expired_returns_422
        """
        patient = create_patient(client)
        physician = create_physician(client)
        set_clock(client, "2026-09-01T16:00:00Z")
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        capture = start_capture(client, encounter, physician)
        capture = stop_capture(client, capture, physician)
        headers = make_physician_headers(physician["id"])
        get_success_data(
            client.cancel_encounter(
                encounter["id"], {"cancel_reason": "walkout"}, headers=headers
            )
        )
        resp = client.simulate_transcription(capture["id"], headers=ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE.value, 422)


class TestAmendNonAttested:
    def test_amend_in_review_returns_409(self, client):
        """PRD 3.5: "The author opens an amendment on an `ATTESTED` draft"

        Design: Corner/validations/corner_amend_non_attested_returns_409
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        submit_review(client, draft, world["physician"])
        resp = client.amend_draft(draft["id"], headers=world["physician_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestMetricFinalizeThenRecompute:
    def test_recompute_on_final_returns_409(self, client):
        """PRD 3.8: "Passing `finalize` as true on the recompute locks the
        row: it moves from `PROVISIONAL` to terminal `FINAL`, and
        `finalized_at` is stamped. A `FINAL` row is immutable to recompute —
        recomputing it is rejected with `ERR_METRIC_PERIOD_CLOSED`."

        Design: Corner/validations/corner_metric_finalize_then_recompute_returns_409
        """
        world = world_with_attested_draft(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        headers = world["physician_headers"]
        finalized = validate_success(
            client.recompute_documentation_metrics(
                world["physician"]["id"],
                {"period_start": "2026-09-01T00:00:00Z", "finalize": True},
                headers=headers,
            )
        )
        assert finalized["status"] == "FINAL"
        resp = client.recompute_documentation_metrics(
            world["physician"]["id"],
            {"period_start": "2026-09-15T00:00:00Z"},
            headers=headers,
        )
        validate_error(resp, ApiErrorId.ERR_METRIC_PERIOD_CLOSED.value, 409)
