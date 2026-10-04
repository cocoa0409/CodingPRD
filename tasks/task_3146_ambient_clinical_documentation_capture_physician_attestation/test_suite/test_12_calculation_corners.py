"""Calculation corners: the specialty multiplier on completeness, speaker
confidence decay, retention clamping after revocation, QA composite weight
variants, and suggestion ranking.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers.fixtures import (
    create_draft,
    create_encounter,
    create_patient,
    create_physician,
    create_qa_auditor,
    grant_consent,
    ready_world,
    set_clock,
    start_capture,
    start_encounter,
    stop_capture,
    transcribe,
    world_with_attested_draft,
)
from test_helpers.test_users import COMPLIANCE, make_qa_auditor_headers


class TestCompletenessSpecialtyMultiplierWeighting:
    def test_multiplier_scales_the_penalty(self, client):
        """PRD 3.4: "Each penalty is multiplied by the template's
        `completeness_multiplier`; the products are summed and the sum is
        rounded half-up; that rounded total is subtracted from 100."
        PRD 3.4: "Because the multiplier scales the penalties, the same set
        of missing fields yields different scores under different specialty
        templates — this is the specialty-weighted variant used for model
        tuning."

        Design: Corner/calculations/corner_completeness_specialty_multiplier_weighting
        """
        world = ready_world(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("hpi", "MAJOR", True),
            ],
            template_overrides={"completeness_multiplier": 1.5},
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        body = validate_success(
            client.patch_note_draft(
                draft["id"],
                f.patch_note_draft_payload(
                    draft["version"], [f.field_update("chief_complaint", "fever")]
                ),
                headers=world["physician_headers"],
            )
        )
        assert body["completeness_score"] == 85, (
            "missing one MAJOR: 100 - round_half_up(10 * 1.5) = 85; got "
            "{0}".format(body["completeness_score"])
        )


class TestSpeakerConfidenceDecayOnReassignment:
    def _setup_segment(self, client):
        world = ready_world(client)
        set_clock(client, "2026-09-01T16:01:00Z")
        capture = start_capture(client, world["encounter"], world["physician"])
        segment = validate_success(
            client.append_segment(
                capture["id"],
                f.segment_payload(
                    start_offset_ms=0,
                    end_offset_ms=4000,
                    speaker_role="PHYSICIAN",
                    base_confidence=0.95,
                ),
                headers=world["physician_headers"],
            ),
            201,
        )
        return world, segment

    def test_decay_after_one_reassignment(self, client):
        """PRD 3.3: "Each segment carries a computed `effective_confidence`,
        the diarization confidence after decay: the `base_confidence` is
        multiplied by 0.9 once for every reassignment that has been applied
        (that is, by 0.9 raised to the power of `reassignment_count`), and
        the result is rounded half-up to 4 decimal places."

        Design: Corner/calculations/corner_speaker_confidence_decay_on_reassignment
        """
        world, segment = self._setup_segment(client)
        assert segment["effective_confidence"] == 0.95, (
            "a fresh segment has no decay"
        )
        body = validate_success(
            client.reassign_speaker(
                segment["id"],
                {"new_speaker_role": "PATIENT"},
                headers=world["physician_headers"],
            )
        )
        assert body["reassignment_count"] == 1
        assert body["effective_confidence"] == 0.855, (
            "0.95 * 0.9 rounded half-up to 4 decimals, got {0}".format(
                body["effective_confidence"]
            )
        )

    def test_decay_compounds_after_two_reassignments(self, client):
        """PRD 3.3: "Reassigning a segment's speaker — by supplying
        `new_speaker_role` (subject to the same `ERR_SPEAKER_ROLE_INVALID`
        domain check) — increments its `reassignment_count` and bumps the
        segment's `version`."

        Design: Corner/calculations/corner_speaker_confidence_decay_on_reassignment
        """
        world, segment = self._setup_segment(client)
        get_success_data(
            client.reassign_speaker(
                segment["id"],
                {"new_speaker_role": "PATIENT"},
                headers=world["physician_headers"],
            )
        )
        body = validate_success(
            client.reassign_speaker(
                segment["id"],
                {"new_speaker_role": "CAREGIVER"},
                headers=world["physician_headers"],
            )
        )
        assert body["reassignment_count"] == 2
        assert body["effective_confidence"] == 0.7695, (
            "0.95 * 0.9^2 = 0.7695, got {0}".format(body["effective_confidence"])
        )
        assert body["speaker_role"] == "CAREGIVER"


class TestRetentionClampAfterRevocation:
    def test_revocation_clamps_retention_to_30(self, client):
        """PRD 3.2: "Link one: every capture of the encounter in `RECORDING`
        or `PAUSED` is purged, and every capture already in `CAPTURED` or
        `TRANSCRIBED` has its `retention_days_effective` shortened to the
        lesser of its planned retention and 30 days."
        PRD 3.3: "A capture's `retention_days_effective` normally equals its
        `planned_retention_days`; it is clamped downward only by the consent
        cascade described in §3.2."

        Design: Corner/calculations/corner_retention_clamp_after_revocation
        """
        patient = create_patient(client)
        physician = create_physician(client)
        set_clock(client, "2026-09-01T10:00:00Z")
        encounter = create_encounter(client, patient, physician)
        consent = grant_consent(client, encounter, patient, captured_via="VERBAL")
        encounter = start_encounter(client, encounter, physician)
        capture = start_capture(client, encounter, physician, planned_retention_days=90)
        capture = stop_capture(client, capture, physician)
        capture = transcribe(client, capture)
        get_success_data(
            client.revoke_consent(consent["id"], {"reason": "audit"}, headers=COMPLIANCE)
        )
        headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        body = get_success_data(client.get_audio_capture(capture["id"], headers=headers))
        assert body["retention_days_effective"] == 30, (
            "clamped from planned 90 by the revocation, got {0}".format(
                body["retention_days_effective"]
            )
        )
        assert body["status"] == "TRANSCRIBED", (
            "revocation does not purge an already-transcribed capture"
        )


class TestQaCompositeBaseAndAppealWeights:
    def _assigned_sample(self, client):
        world = world_with_attested_draft(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        qa_a = create_qa_auditor(client, employee_code="QA-A-1", specialty_codes=["CARD"])
        qa_b = create_qa_auditor(client, employee_code="QA-B-1", specialty_codes=["CARD"])
        sample = get_success_data(
            client.queue_qa_sample(world["draft"]["id"], headers=COMPLIANCE)
        )
        get_success_data(
            client.assign_qa_sample(
                sample["id"], {"auditor_id": qa_a["id"]}, headers=COMPLIANCE
            )
        )
        return world, sample, qa_a, qa_b

    def test_base_weights_on_score(self, client):
        """PRD 3.7: "The `composite_score` is the round-half-up integer of
        the weighted blend: accuracy contributes one half, completeness three
        tenths, and timeliness one fifth."

        Design: Corner/calculations/corner_qa_composite_base_and_appeal_weights
        """
        world, sample, qa_a, qa_b = self._assigned_sample(client)
        body = validate_success(
            client.score_qa_sample(
                sample["id"],
                f.qa_scores_payload(80, 90, 100),
                headers=make_qa_auditor_headers(qa_a["id"]),
            )
        )
        assert body["composite_score"] == 87, (
            "0.5*80 + 0.3*90 + 0.2*100 = 40+27+20, got {0}".format(
                body["composite_score"]
            )
        )
        assert body["status"] == "SCORED"

    def test_appeal_weights_on_rescore(self, client):
        """PRD 3.7: "The rescore uses appeal weights — accuracy now
        contributes seven tenths, completeness two tenths, timeliness one
        tenth — so identical sub-scores yield a different composite after
        appeal, again rounded half-up to an integer."

        Design: Corner/calculations/corner_qa_composite_base_and_appeal_weights
        """
        world, sample, qa_a, qa_b = self._assigned_sample(client)
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
        body = validate_success(
            client.rescore_qa_sample(
                sample["id"],
                f.qa_scores_payload(90, 90, 90),
                headers=make_qa_auditor_headers(qa_b["id"]),
            )
        )
        assert body["composite_score"] == 90, (
            "0.7*90 + 0.2*90 + 0.1*90 = 63+18+9, got {0}".format(
                body["composite_score"]
            )
        )
        assert body["status"] == "RESCORED"


class TestSuggestionRankingConfidenceThenCreatedAt:
    def test_ranks_follow_confidence_desc_then_creation_order(self, client):
        """PRD 3.6: "Each suggestion also receives a 1-based `rank` within
        the draft, assigned across all non-terminal suggestions (`SUGGESTED`,
        `MODIFIED`, `CONFIRMED`) ordered by `confidence` descending, with
        ties broken by `created_at` ascending; ranks are dense from 1."

        Design: Corner/calculations/corner_suggestion_ranking_confidence_then_created_at
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        draft = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        rows = validate_success(
            client.create_code_suggestions(
                draft["id"],
                {
                    "suggestions": [
                        f.diagnosis_suggestion_payload("D901", confidence=0.9),
                        f.diagnosis_suggestion_payload("D902", confidence=0.95),
                        f.diagnosis_suggestion_payload("D903", confidence=0.9),
                    ]
                },
                headers=world["physician_headers"],
            ),
            201,
        )
        by_code = {row["code_value"]: row for row in rows}
        assert by_code["D902"]["rank"] == 1, "highest confidence ranks first"
        assert by_code["D901"]["rank"] == 2, (
            "equal confidence: created first ranks ahead"
        )
        assert by_code["D903"]["rank"] == 3
