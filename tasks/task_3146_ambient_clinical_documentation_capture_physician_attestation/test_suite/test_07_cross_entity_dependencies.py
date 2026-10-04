"""Cross-entity state dependencies: attestation gated on consent, capture
start gated on the encounter state.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    create_draft,
    create_encounter,
    create_patient,
    create_physician,
    edit_draft,
    grant_consent,
    ready_world,
    submit_review,
)
from test_helpers.test_users import COMPLIANCE


class TestAttestRequiresGrantedConsent:
    """An otherwise perfect attestation fails solely on revoked consent."""

    def _setup(self, client):
        """Draft IN_REVIEW with completeness 100; consent then revoked."""
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        physician = world["physician"]
        draft = create_draft(
            client, world["encounter"], physician, world["template"]
        )
        draft = edit_draft(
            client, draft, physician, [f.field_update("chief_complaint", "fever")]
        )
        submit_review(client, draft, physician)
        get_success_data(
            client.revoke_consent(
                world["consent"]["id"], {"reason": "compliance hold"},
                headers=COMPLIANCE,
            )
        )
        world["draft"] = draft
        return world

    def test_attest_rejected_with_consent_not_active(self, client):
        """PRD 3.5: "the encounter must hold a `GRANTED` consent
        (`ERR_CONSENT_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/attest_requires_granted_consent
        """
        world = self._setup(client)
        resp = client.attest_draft(
            world["draft"]["id"], headers=world["physician_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE.value, 422)

    def test_rejected_attestation_leaves_draft_in_review(self, client):
        """PRD 3.5: "The draft must be in `IN_REVIEW` to attest."

        Design: Difficulty/cross_entity_state_dependency/attest_requires_granted_consent
        """
        world = self._setup(client)
        validate_error(
            client.attest_draft(
                world["draft"]["id"], headers=world["physician_headers"]
            ),
            ApiErrorId.ERR_CONSENT_NOT_ACTIVE.value,
            422,
        )
        draft = get_success_data(
            client.get_note_draft(
                world["draft"]["id"], headers=world["physician_headers"]
            )
        )
        assert draft["status"] == "IN_REVIEW", "attestation did not occur"


class TestAudioStartRequiresInProgressEncounter:
    """Capture start on a SCHEDULED encounter is rejected even with consent."""

    def _setup(self, client):
        patient = create_patient(client)
        physician = create_physician(client)
        encounter = create_encounter(client, patient, physician)
        grant_consent(client, encounter, patient, captured_via="PORTAL")
        return {
            "encounter": encounter,
            "headers": {"X-User-ID": physician["id"], "X-User-Role": "Physician"},
        }

    def test_capture_on_scheduled_encounter_rejected(self, client):
        """PRD 3.3: "starting one while the encounter is not `IN_PROGRESS` is
        rejected with `ERR_ENCOUNTER_NOT_IN_PROGRESS`"

        Design: Difficulty/cross_entity_state_dependency/audio_start_requires_in_progress_encounter
        """
        w = self._setup(client)
        resp = client.start_audio_capture(
            w["encounter"]["id"], f.start_capture_payload(), headers=w["headers"]
        )
        validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_IN_PROGRESS.value, 409)

    def test_consent_alone_does_not_enable_capture(self, client):
        """PRD 3.3: "Once an encounter is `IN_PROGRESS` and holds a `GRANTED`
        consent, the attending physician may start an audio capture"

        Design: Difficulty/cross_entity_state_dependency/audio_start_requires_in_progress_encounter
        """
        w = self._setup(client)
        # Consent is GRANTED, so only the encounter-state dependency can fail.
        resp = client.start_audio_capture(
            w["encounter"]["id"],
            f.start_capture_payload(planned_retention_days=60),
            headers=w["headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ENCOUNTER_NOT_IN_PROGRESS.value, 409)
