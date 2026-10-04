"""Validation priority pairs: which error surfaces when two rules fail."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import create_draft, ready_world
from test_helpers.test_users import COMPLIANCE


class TestSafetyConsentBeatsStateOnAttest:
    """Attest on a DRAFT-status draft with REVOKED consent: the safety rule
    outranks the state rule."""

    def _setup(self, client):
        """Draft left in DRAFT (never submitted); consent revoked."""
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        world["draft"] = draft
        get_success_data(
            client.revoke_consent(
                world["consent"]["id"], {"reason": "legal request"},
                headers=COMPLIANCE,
            )
        )
        return world

    def test_consent_not_active_surfaces_over_invalid_state(self, client):
        """PRD 2.9: "then safety gates (`ERR_CONSENT_REQUIRED`,
        `ERR_CONSENT_NOT_ACTIVE`, `ERR_LEGAL_HOLD_ACTIVE`,
        `ERR_PHYSICIAN_NOT_ACTIVE`), then state-machine legality
        (`ERR_INVALID_STATE` and its more specific siblings)"

        Design: Difficulty/priority_pair_validation_conflict/safety_consent_beats_state_on_attest
        """
        world = self._setup(client)
        resp = client.attest_draft(
            world["draft"]["id"], headers=world["physician_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE.value, 422)

    def test_draft_state_unchanged_after_rejected_attest(self, client):
        """PRD 3.5: "the encounter must hold a `GRANTED` consent
        (`ERR_CONSENT_NOT_ACTIVE`)"

        Design: Difficulty/priority_pair_validation_conflict/safety_consent_beats_state_on_attest
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
        assert draft["status"] == "DRAFT", "rejected attestation must not move state"


class TestReferentialBeatsConstraintOnCodeBatch:
    """A batch with a malformed code_value that would also breach the active
    suggestion ceiling surfaces the referential error."""

    def _setup(self, client):
        """Draft holding seven active suggestions."""
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        world["draft"] = draft
        batch = [
            f.diagnosis_suggestion_payload(code)
            for code in ("D101", "D102", "D103", "D104")
        ] + [
            {"code_type": "ORDER", "code_value": code, "confidence": 0.9}
            for code in ("O101", "O102", "O103")
        ]
        get_success_data(
            client.create_code_suggestions(
                draft["id"], {"suggestions": batch},
                headers=world["physician_headers"],
            )
        )
        return world

    def test_malformed_code_beats_limit_exceeded(self, client):
        """PRD 2.9: "then request shape and referential validity
        (`ERR_INVALID_REQUEST`, `ERR_SPEAKER_ROLE_INVALID`,
        `ERR_TEMPLATE_FIELD_MISMATCH`, `ERR_CODE_VALUE_MALFORMED`), then
        safety gates (`ERR_CONSENT_REQUIRED`, `ERR_CONSENT_NOT_ACTIVE`,
        `ERR_LEGAL_HOLD_ACTIVE`, `ERR_PHYSICIAN_NOT_ACTIVE`), then
        state-machine legality (`ERR_INVALID_STATE` and its more specific
        siblings), then business constraints (`ERR_SIGNAGE_NOT_POSTED`,
        `ERR_DUPLICATE_CONSENT`, `ERR_CAPTURE_ACTIVE_EXISTS`,
        `ERR_TEMPLATE_INACTIVE`, `ERR_NO_TRANSCRIBED_AUDIO`,
        `ERR_NOTE_INCOMPLETE`, `ERR_CODE_LIMIT_EXCEEDED`,
        `ERR_QA_MAX_APPEALS`, `ERR_QA_SELF_REVIEW_FORBIDDEN`,
        `ERR_AUDITOR_SPECIALTY_MISMATCH`)"

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_code_batch
        """
        world = self._setup(client)
        resp = client.create_code_suggestions(
            world["draft"]["id"],
            {
                "suggestions": [
                    f.diagnosis_suggestion_payload("d-bad"),
                    f.diagnosis_suggestion_payload("D105"),
                ]
            },
            headers=world["physician_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CODE_VALUE_MALFORMED.value, 422)

    def test_rejected_batch_is_atomic(self, client):
        """PRD 3.6: "Every `code_value` must match the code format — an
        uppercase letter followed by 2 to 15 characters drawn from uppercase
        letters, digits, and dots — or the batch is rejected with
        `ERR_CODE_VALUE_MALFORMED`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_code_batch
        """
        world = self._setup(client)
        validate_error(
            client.create_code_suggestions(
                world["draft"]["id"],
                {
                    "suggestions": [
                        f.diagnosis_suggestion_payload("d-bad"),
                        f.diagnosis_suggestion_payload("D105"),
                    ]
                },
                headers=world["physician_headers"],
            ),
            ApiErrorId.ERR_CODE_VALUE_MALFORMED.value,
            422,
        )
        rows, _meta = validate_paginated(
            client.list_code_suggestions(
                world["draft"]["id"], headers=world["physician_headers"]
            )
        )
        assert len(rows) == 7, "the whole batch is rejected atomically"
