"""One transport method per endpoint in PRD section 4.

Every method returns the raw HTTP response so a test asserts on status code
and envelope directly.  The ``/ambient-clinical-documentation`` prefix and
each path shape live here and nowhere else.
"""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH, RETENTION_SWEEP_PATH, TRANSCRIPTION_PATH


class ApiClient(GenericApiClient):
    """Thin, endpoint-shaped facade over the shared HTTP client."""

    # ─── Test-driving endpoints (PRD 2.5 / 3.8) ──────────────────────────

    def set_clock(self, to_iso8601, headers=None):
        return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)

    def simulate_transcription(self, audio_capture_id, headers=None):
        return self.post(
            TRANSCRIPTION_PATH, json={"audio_capture_id": audio_capture_id}, headers=headers
        )

    def run_retention_sweep(self, headers=None):
        return self.post(RETENTION_SWEEP_PATH, json={}, headers=headers)

    # ─── Patients ─────────────────────────────────────────────────────────

    def create_patient(self, payload, headers=None):
        return self.post(API_PREFIX + "/patients", json=payload, headers=headers)

    def get_patient(self, patient_id, headers=None):
        return self.get("{0}/patients/{1}".format(API_PREFIX, patient_id), headers=headers)

    def list_patient_encounters(self, patient_id, headers=None, params=None):
        return self.get(
            "{0}/patients/{1}/encounters".format(API_PREFIX, patient_id),
            headers=headers,
            params=params,
        )

    def list_patient_consents(self, patient_id, headers=None, params=None):
        return self.get(
            "{0}/patients/{1}/consents".format(API_PREFIX, patient_id),
            headers=headers,
            params=params,
        )

    # ─── Physicians ───────────────────────────────────────────────────────

    def create_physician(self, payload, headers=None):
        return self.post(API_PREFIX + "/physicians", json=payload, headers=headers)

    def get_physician(self, physician_id, headers=None):
        return self.get(
            "{0}/physicians/{1}".format(API_PREFIX, physician_id), headers=headers
        )

    def update_physician(self, physician_id, payload, headers=None):
        return self._request(
            "PATCH",
            "{0}/physicians/{1}".format(API_PREFIX, physician_id),
            payload,
            headers,
        )

    def list_physician_encounters(self, physician_id, headers=None, params=None):
        return self.get(
            "{0}/physicians/{1}/encounters".format(API_PREFIX, physician_id),
            headers=headers,
            params=params,
        )

    def list_physician_note_drafts(self, physician_id, headers=None, params=None):
        return self.get(
            "{0}/physicians/{1}/note-drafts".format(API_PREFIX, physician_id),
            headers=headers,
            params=params,
        )

    def list_physician_attestations(self, physician_id, headers=None, params=None):
        return self.get(
            "{0}/physicians/{1}/attestations".format(API_PREFIX, physician_id),
            headers=headers,
            params=params,
        )

    def list_documentation_metrics(self, physician_id, headers=None, params=None):
        return self.get(
            "{0}/physicians/{1}/documentation-metrics".format(API_PREFIX, physician_id),
            headers=headers,
            params=params,
        )

    def recompute_documentation_metrics(self, physician_id, payload, headers=None):
        return self.post(
            "{0}/physicians/{1}/documentation-metrics/recompute".format(
                API_PREFIX, physician_id
            ),
            json=payload,
            headers=headers,
        )

    # ─── QA auditors ──────────────────────────────────────────────────────

    def create_qa_auditor(self, payload, headers=None):
        return self.post(API_PREFIX + "/qa-auditors", json=payload, headers=headers)

    def get_qa_auditor(self, auditor_id, headers=None):
        return self.get(
            "{0}/qa-auditors/{1}".format(API_PREFIX, auditor_id), headers=headers
        )

    def list_auditor_qa_samples(self, auditor_id, headers=None, params=None):
        return self.get(
            "{0}/qa-auditors/{1}/qa-samples".format(API_PREFIX, auditor_id),
            headers=headers,
            params=params,
        )

    # ─── Note templates ───────────────────────────────────────────────────

    def create_note_template(self, payload, headers=None):
        return self.post(API_PREFIX + "/note-templates", json=payload, headers=headers)

    def get_note_template(self, template_id, headers=None):
        return self.get(
            "{0}/note-templates/{1}".format(API_PREFIX, template_id), headers=headers
        )

    def update_note_template(self, template_id, payload, headers=None):
        return self._request(
            "PATCH",
            "{0}/note-templates/{1}".format(API_PREFIX, template_id),
            payload,
            headers,
        )

    def list_template_note_drafts(self, template_id, headers=None, params=None):
        return self.get(
            "{0}/note-templates/{1}/note-drafts".format(API_PREFIX, template_id),
            headers=headers,
            params=params,
        )

    # ─── Encounters ───────────────────────────────────────────────────────

    def create_encounter(self, payload, headers=None):
        return self.post(API_PREFIX + "/encounters", json=payload, headers=headers)

    def get_encounter(self, encounter_id, headers=None):
        return self.get(
            "{0}/encounters/{1}".format(API_PREFIX, encounter_id), headers=headers
        )

    def start_encounter(self, encounter_id, headers=None):
        return self.post(
            "{0}/encounters/{1}/start".format(API_PREFIX, encounter_id),
            json={},
            headers=headers,
        )

    def complete_encounter(self, encounter_id, headers=None):
        return self.post(
            "{0}/encounters/{1}/complete".format(API_PREFIX, encounter_id),
            json={},
            headers=headers,
        )

    def cancel_encounter(self, encounter_id, payload=None, headers=None):
        return self.post(
            "{0}/encounters/{1}/cancel".format(API_PREFIX, encounter_id),
            json=payload or {},
            headers=headers,
        )

    # ─── Consents ─────────────────────────────────────────────────────────

    def list_encounter_consents(self, encounter_id, headers=None, params=None):
        return self.get(
            "{0}/encounters/{1}/consents".format(API_PREFIX, encounter_id),
            headers=headers,
            params=params,
        )

    def grant_consent(self, encounter_id, payload, headers=None):
        return self.post(
            "{0}/encounters/{1}/consents".format(API_PREFIX, encounter_id),
            json=payload,
            headers=headers,
        )

    def opt_out_consent(self, consent_id, payload=None, headers=None):
        return self.post(
            "{0}/consents/{1}/opt-out".format(API_PREFIX, consent_id),
            json=payload or {},
            headers=headers,
        )

    def revoke_consent(self, consent_id, payload=None, headers=None):
        return self.post(
            "{0}/consents/{1}/revoke".format(API_PREFIX, consent_id),
            json=payload or {},
            headers=headers,
        )

    # ─── Audio captures and segments ──────────────────────────────────────

    def list_encounter_audio_captures(self, encounter_id, headers=None, params=None):
        return self.get(
            "{0}/encounters/{1}/audio-captures".format(API_PREFIX, encounter_id),
            headers=headers,
            params=params,
        )

    def start_audio_capture(self, encounter_id, payload, headers=None):
        return self.post(
            "{0}/encounters/{1}/audio-captures".format(API_PREFIX, encounter_id),
            json=payload,
            headers=headers,
        )

    def get_audio_capture(self, capture_id, headers=None):
        return self.get(
            "{0}/audio-captures/{1}".format(API_PREFIX, capture_id), headers=headers
        )

    def pause_capture(self, capture_id, headers=None):
        return self.post(
            "{0}/audio-captures/{1}/pause".format(API_PREFIX, capture_id),
            json={},
            headers=headers,
        )

    def resume_capture(self, capture_id, headers=None):
        return self.post(
            "{0}/audio-captures/{1}/resume".format(API_PREFIX, capture_id),
            json={},
            headers=headers,
        )

    def stop_capture(self, capture_id, headers=None):
        return self.post(
            "{0}/audio-captures/{1}/stop".format(API_PREFIX, capture_id),
            json={},
            headers=headers,
        )

    def purge_capture(self, capture_id, headers=None):
        return self.post(
            "{0}/audio-captures/{1}/purge".format(API_PREFIX, capture_id),
            json={},
            headers=headers,
        )

    def set_legal_hold(self, capture_id, payload, headers=None):
        return self.post(
            "{0}/audio-captures/{1}/legal-hold".format(API_PREFIX, capture_id),
            json=payload,
            headers=headers,
        )

    def append_segment(self, capture_id, payload, headers=None):
        return self.post(
            "{0}/audio-captures/{1}/segments".format(API_PREFIX, capture_id),
            json=payload,
            headers=headers,
        )

    def list_segments(self, capture_id, headers=None, params=None):
        return self.get(
            "{0}/audio-captures/{1}/segments".format(API_PREFIX, capture_id),
            headers=headers,
            params=params,
        )

    def reassign_speaker(self, segment_id, payload, headers=None):
        return self.post(
            "{0}/segments/{1}/reassign-speaker".format(API_PREFIX, segment_id),
            json=payload,
            headers=headers,
        )

    # ─── Note drafts and fields ───────────────────────────────────────────

    def list_encounter_note_drafts(self, encounter_id, headers=None, params=None):
        return self.get(
            "{0}/encounters/{1}/note-drafts".format(API_PREFIX, encounter_id),
            headers=headers,
            params=params,
        )

    def create_note_draft(self, encounter_id, payload, headers=None):
        return self.post(
            "{0}/encounters/{1}/note-drafts".format(API_PREFIX, encounter_id),
            json=payload,
            headers=headers,
        )

    def get_note_draft(self, draft_id, headers=None):
        return self.get(
            "{0}/note-drafts/{1}".format(API_PREFIX, draft_id), headers=headers
        )

    def patch_note_draft(self, draft_id, payload, headers=None):
        return self._request(
            "PATCH", "{0}/note-drafts/{1}".format(API_PREFIX, draft_id), payload, headers
        )

    def submit_review(self, draft_id, headers=None):
        return self.post(
            "{0}/note-drafts/{1}/submit-review".format(API_PREFIX, draft_id),
            json={},
            headers=headers,
        )

    def regenerate_draft(self, draft_id, headers=None):
        return self.post(
            "{0}/note-drafts/{1}/regenerate".format(API_PREFIX, draft_id),
            json={},
            headers=headers,
        )

    def attest_draft(self, draft_id, headers=None):
        return self.post(
            "{0}/note-drafts/{1}/attest".format(API_PREFIX, draft_id),
            json={},
            headers=headers,
        )

    def amend_draft(self, draft_id, headers=None):
        return self.post(
            "{0}/note-drafts/{1}/amend".format(API_PREFIX, draft_id),
            json={},
            headers=headers,
        )

    def void_draft(self, draft_id, headers=None):
        return self.post(
            "{0}/note-drafts/{1}/void".format(API_PREFIX, draft_id),
            json={},
            headers=headers,
        )

    def list_note_fields(self, draft_id, headers=None, params=None):
        return self.get(
            "{0}/note-drafts/{1}/fields".format(API_PREFIX, draft_id),
            headers=headers,
            params=params,
        )

    def list_draft_attestations(self, draft_id, headers=None, params=None):
        return self.get(
            "{0}/note-drafts/{1}/attestations".format(API_PREFIX, draft_id),
            headers=headers,
            params=params,
        )

    # ─── Code suggestions ─────────────────────────────────────────────────

    def create_code_suggestions(self, draft_id, payload, headers=None):
        return self.post(
            "{0}/note-drafts/{1}/code-suggestions".format(API_PREFIX, draft_id),
            json=payload,
            headers=headers,
        )

    def list_code_suggestions(self, draft_id, headers=None, params=None):
        return self.get(
            "{0}/note-drafts/{1}/code-suggestions".format(API_PREFIX, draft_id),
            headers=headers,
            params=params,
        )

    def confirm_suggestion(self, suggestion_id, headers=None):
        return self.post(
            "{0}/code-suggestions/{1}/confirm".format(API_PREFIX, suggestion_id),
            json={},
            headers=headers,
        )

    def reject_suggestion(self, suggestion_id, headers=None):
        return self.post(
            "{0}/code-suggestions/{1}/reject".format(API_PREFIX, suggestion_id),
            json={},
            headers=headers,
        )

    def modify_suggestion(self, suggestion_id, payload, headers=None):
        return self.post(
            "{0}/code-suggestions/{1}/modify".format(API_PREFIX, suggestion_id),
            json=payload,
            headers=headers,
        )

    # ─── QA samples ───────────────────────────────────────────────────────

    def queue_qa_sample(self, draft_id, payload=None, headers=None):
        return self.post(
            "{0}/note-drafts/{1}/qa-samples".format(API_PREFIX, draft_id),
            json=payload or {},
            headers=headers,
        )

    def list_draft_qa_samples(self, draft_id, headers=None, params=None):
        return self.get(
            "{0}/note-drafts/{1}/qa-samples".format(API_PREFIX, draft_id),
            headers=headers,
            params=params,
        )

    def assign_qa_sample(self, sample_id, payload, headers=None):
        return self.post(
            "{0}/qa-samples/{1}/assign".format(API_PREFIX, sample_id),
            json=payload,
            headers=headers,
        )

    def score_qa_sample(self, sample_id, payload, headers=None):
        return self.post(
            "{0}/qa-samples/{1}/score".format(API_PREFIX, sample_id),
            json=payload,
            headers=headers,
        )

    def appeal_qa_sample(self, sample_id, payload=None, headers=None):
        return self.post(
            "{0}/qa-samples/{1}/appeal".format(API_PREFIX, sample_id),
            json=payload or {},
            headers=headers,
        )

    def rescore_qa_sample(self, sample_id, payload, headers=None):
        return self.post(
            "{0}/qa-samples/{1}/rescore".format(API_PREFIX, sample_id),
            json=payload,
            headers=headers,
        )

    def close_qa_sample(self, sample_id, headers=None):
        return self.post(
            "{0}/qa-samples/{1}/close".format(API_PREFIX, sample_id),
            json={},
            headers=headers,
        )


api_client = ApiClient()
