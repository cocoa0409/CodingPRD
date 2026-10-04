"""Transitive cascades: opt-out depth-3 cascade and cancel depth-2 cascade."""

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
    ready_world,
    set_clock,
    start_capture,
    start_encounter,
    stop_capture,
    submit_review,
    transcribe,
)
from test_helpers.test_users import (
    ADMIN,
    make_patient_headers,
    make_physician_headers,
)


class TestOptOutPurgeInvalidateDemote:
    """Consent opt-out purges in-flight audio, clamps retained audio,
    invalidates AUDIO-sourced fields, and demotes the in-review draft."""

    def _setup(self, client):
        """cap1 TRANSCRIBED (planned 90), cap2 RECORDING; draft IN_REVIEW with
        MANUAL chief_complaint and the rest AUDIO."""
        patient = create_patient(client)
        physician = create_physician(client)
        template = create_note_template(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("hpi", "MAJOR", True),
                f.field_spec("exam", "MAJOR", True),
                f.field_spec("plan", "MAJOR", True),
                f.field_spec("ros", "MINOR", True),
            ],
        )
        phy = make_physician_headers(physician["id"])
        pat = make_patient_headers(patient["id"])
        set_clock(client, "2026-09-01T10:00:00Z")
        encounter = create_encounter(client, patient, physician)
        consent = grant_consent(client, encounter, patient)
        encounter = start_encounter(client, encounter, physician)
        cap1 = start_capture(client, encounter, physician, planned_retention_days=90)
        set_clock(client, "2026-09-01T10:02:00Z")
        cap1 = stop_capture(client, cap1, physician)
        cap1 = transcribe(client, cap1)
        set_clock(client, "2026-09-01T10:03:30Z")
        cap2 = start_capture(client, encounter, physician)
        draft = create_draft(client, encounter, physician, template)
        draft = edit_draft(
            client, draft, physician, [f.field_update("chief_complaint", "back pain")]
        )
        draft = submit_review(client, draft, physician)
        get_success_data(client.regenerate_draft(draft["id"], headers=phy))
        draft = get_success_data(client.submit_review(draft["id"], headers=phy))
        return {
            "consent": consent,
            "cap1": cap1,
            "cap2": cap2,
            "draft": draft,
            "phy": phy,
            "pat": pat,
        }

    def test_opt_out_status_and_capture_cascade(self, client):
        """PRD 3.2: "Link one: every capture of the encounter in `RECORDING`
        or `PAUSED` is purged, and every capture already in `CAPTURED` or
        `TRANSCRIBED` has its `retention_days_effective` shortened to the
        lesser of its planned retention and 30 days."
        PRD 3.2: "Opt-out and revocation trigger the same three-link cascade,
        with only the purge reason differing (`OPT_OUT` versus `REVOKE`)."

        Design: Difficulty/transitive_cascade/opt_out_purge_invalidate_demote_depth3
        """
        w = self._setup(client)
        consent = validate_success(
            client.opt_out_consent(
                w["consent"]["id"],
                {"reason": "patient declined mid-visit"},
                headers=w["pat"],
            )
        )
        assert consent["status"] == "OPTED_OUT"
        assert consent["end_reason"] == "OPT_OUT"
        cap2 = get_success_data(
            client.get_audio_capture(w["cap2"]["id"], headers=w["phy"])
        )
        assert cap2["status"] == "PURGED"
        assert cap2["purge_reason"] == "OPT_OUT"
        cap1 = get_success_data(
            client.get_audio_capture(w["cap1"]["id"], headers=w["phy"])
        )
        assert cap1["status"] == "TRANSCRIBED", (
            "an already-transcribed capture is not purged by opt-out"
        )
        assert cap1["retention_days_effective"] == 30, (
            "clamped from planned 90 to 30, got {0}".format(
                cap1["retention_days_effective"]
            )
        )

    def test_opt_out_field_invalidation_and_draft_demotion(self, client):
        """PRD 3.2: "Link two: every note field of the encounter's drafts
        whose `source` is `AUDIO` has its `field_value` nulled and its
        `validated` flag reset to false; the field's `source` remains
        `AUDIO`."
        PRD 3.2: "Link three: drafts of the encounter in `IN_REVIEW` or
        `EDITED` are demoted back to `DRAFT` with their `completeness_score`
        recomputed, while drafts already `ATTESTED` are left untouched in
        status — the attested legal record is immutable — and are instead
        flagged with `phi_review_required` set to true."

        Design: Difficulty/transitive_cascade/opt_out_purge_invalidate_demote_depth3
        """
        w = self._setup(client)
        get_success_data(
            client.opt_out_consent(
                w["consent"]["id"], {"reason": "patient declined"}, headers=w["pat"]
            )
        )
        draft = get_success_data(
            client.get_note_draft(w["draft"]["id"], headers=w["phy"])
        )
        assert draft["status"] == "DRAFT", (
            "IN_REVIEW draft demoted to DRAFT, got {0}".format(draft["status"])
        )
        assert draft["completeness_score"] == 65, (
            "only MANUAL chief_complaint filled: missing 3x MAJOR + 1x MINOR "
            "= 35 penalty, got {0}".format(draft["completeness_score"])
        )
        fields, _meta = validate_paginated(
            client.list_note_fields(w["draft"]["id"], headers=w["phy"])
        )
        by_key = {row["field_key"]: row for row in fields}
        assert by_key["chief_complaint"]["field_value"] == "back pain", (
            "MANUAL fields are preserved"
        )
        for key in ("hpi", "exam", "plan", "ros"):
            row = by_key[key]
            assert row["source"] == "AUDIO"
            assert row["field_value"] is None
            assert row["validated"] is False


class TestEncounterCancelCascade:
    """Cancelling an encounter expires the consent, and the consent expiry
    purges the in-flight capture."""

    def _setup(self, client):
        world = ready_world(client, clock_instant="2026-09-01T10:00:00Z")
        # ready_world already stopped and transcribed its capture; start a
        # fresh RECORDING capture so the cascade has something in flight.
        world["recording_capture"] = start_capture(
            client, world["encounter"], world["physician"]
        )
        return world

    def test_cancel_expires_consent_and_purges_capture(self, client):
        """PRD 3.2: "Cancelling an encounter triggers a related but narrower
        cascade: a still-`GRANTED` consent on the cancelled encounter expires
        (`GRANTED` → `EXPIRED`, end_reason `EXPIRE`), and any captures in
        `RECORDING` or `PAUSED` are purged with purge reason `CANCEL`."

        Design: Difficulty/transitive_cascade/encounter_cancel_expires_consent_purges_capture_depth2
        """
        world = self._setup(client)
        headers = world["physician_headers"]
        encounter = validate_success(
            client.cancel_encounter(
                world["encounter"]["id"],
                {"cancel_reason": "patient left AMA"},
                headers=headers,
            )
        )
        assert encounter["encounter_status"] == "CANCELLED"
        consents, _meta = validate_paginated(
            client.list_encounter_consents(world["encounter"]["id"], headers=headers)
        )
        assert consents[0]["status"] == "EXPIRED"
        capture = get_success_data(
            client.get_audio_capture(
                world["recording_capture"]["id"], headers=headers
            )
        )
        assert capture["status"] == "PURGED"
        assert capture["purge_reason"] == "CANCEL"

    def test_cancel_stamps_ended_at_and_reason(self, client):
        """PRD 3.2: "cancellation from either `SCHEDULED` or `IN_PROGRESS` —
        available to a `Physician` or a `ComplianceOfficer` — moves the
        encounter to `CANCELLED`, stamps `ended_at`, and records the optional
        `cancel_reason` from the request."

        Design: Difficulty/transitive_cascade/encounter_cancel_expires_consent_purges_capture_depth2
        """
        world = self._setup(client)
        encounter = validate_success(
            client.cancel_encounter(
                world["encounter"]["id"],
                {"cancel_reason": "patient left AMA"},
                headers=world["physician_headers"],
            )
        )
        assert encounter["encounter_status"] == "CANCELLED"
        assert encounter["ended_at"], "ended_at must be stamped"
        assert encounter.get("cancel_reason") == "patient left AMA"
