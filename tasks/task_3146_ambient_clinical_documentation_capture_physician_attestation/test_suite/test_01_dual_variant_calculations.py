"""Dual-variant calculations: provisional vs final billing totals and
provisional vs final documentation minutes on identical stored data.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers.fixtures import create_draft, ready_world, set_clock
from test_helpers.test_users import ADMIN


class TestBillingProvisionalVsFinalOnCodeSuggestions:
    """Two billing variants diverge on identical stored suggestion rows."""

    def _world_with_two_billing_lines(self, client):
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
        world["draft"] = draft
        resp = client.create_code_suggestions(
            draft["id"],
            {
                "suggestions": [
                    f.billing_suggestion_payload(
                        "B1001", confidence=0.5, unit_fee_cents=1000,
                        adjustment_pct=1.004,
                    ),
                    f.billing_suggestion_payload(
                        "B1002", confidence=1.0, unit_fee_cents=1000,
                        adjustment_pct=1.004,
                    ),
                ]
            },
            headers=world["physician_headers"],
        )
        validate_success(resp, 201)
        return world

    def test_provisional_is_confidence_weighted_and_final_is_zero(self, client):
        """PRD 3.6: "`billing_provisional_cents` is the forward-looking
        figure: it covers `BILLING` suggestions in `SUGGESTED`, `MODIFIED`,
        and `CONFIRMED` status, with each line's already-rounded total
        multiplied by that suggestion's `confidence` and the result rounded
        half-up to cents before summing."
        PRD 3.6: "`billing_final_cents` is the legal-record figure: the sum
        of the per-line totals over the draft's `BILLING` suggestions in
        `CONFIRMED` status only, unweighted; `EXPIRED` and `REJECTED` lines
        are excluded."

        Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_on_code_suggestions
        """
        world = self._world_with_two_billing_lines(client)
        body = validate_success(
            client.get_note_draft(
                world["draft"]["id"], headers=world["physician_headers"]
            )
        )
        assert body["billing_provisional_cents"] == 1500, (
            "Expected 1500 (500 weighted at 0.5 plus 1000 weighted at 1.0), "
            "got {0}".format(body["billing_provisional_cents"])
        )
        assert body["billing_final_cents"] == 0, (
            "No CONFIRMED lines yet, expected 0, got {0}".format(
                body["billing_final_cents"]
            )
        )

    def test_variants_diverge_by_exactly_the_weighted_gap(self, client):
        """PRD 3.6: "Rounding order is pinned — each line is rounded first,
        then the confidence weighting is applied and rounded again, then the
        lines are summed; summing first and rounding once is the rejected
        alternative."

        Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_on_code_suggestions
        """
        world = self._world_with_two_billing_lines(client)
        body = validate_success(
            client.get_note_draft(
                world["draft"]["id"], headers=world["physician_headers"]
            )
        )
        # round_half_up(1000*1*1.004)=1000 per line; provisional weights them.
        assert (
            body["billing_provisional_cents"] - body["billing_final_cents"] == 1500
        ), "The two variants must diverge by exactly 1500 cents"


class TestDocumentationMinutesProvisionalVsFinal:
    """DocumentationMetric spans: wall-clock vs pause-adjusted minutes, plus
    after-hours measurement."""

    def _attested_world_with_pause(self, client):
        """Start 16:00, pause 17:00, resume 17:15, stop 17:20, transcribe,
        draft, fill, submit, complete 17:25, attest 19:30."""
        patient = get_success_data(
            client.create_patient(f.create_patient_payload(), headers=ADMIN)
        )
        physician = get_success_data(
            client.create_physician(f.create_physician_payload(), headers=ADMIN)
        )
        template = get_success_data(
            client.create_note_template(
                f.create_note_template_payload(
                    field_specs=[
                        f.field_spec("chief_complaint", "CRITICAL", True),
                        f.field_spec("hpi", "MAJOR", True),
                        f.field_spec("exam", "MAJOR", True),
                        f.field_spec("plan", "MAJOR", True),
                        f.field_spec("ros", "MINOR", True),
                    ]
                ),
                headers=ADMIN,
            )
        )
        phy_headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
        pat_headers = {"X-User-ID": patient["id"], "X-User-Role": "Patient"}

        set_clock(client, "2026-09-01T16:00:00Z")
        encounter = get_success_data(
            client.create_encounter(
                f.create_encounter_payload(patient["id"], physician["id"]),
                headers=phy_headers,
            )
        )
        get_success_data(
            client.grant_consent(
                encounter["id"],
                f.grant_consent_payload(patient["id"], captured_via="VERBAL"),
                headers=pat_headers,
            )
        )
        get_success_data(client.start_encounter(encounter["id"], headers=phy_headers))
        capture = get_success_data(
            client.start_audio_capture(
                encounter["id"], f.start_capture_payload(), headers=phy_headers
            )
        )
        set_clock(client, "2026-09-01T17:00:00Z")
        get_success_data(client.pause_capture(capture["id"], headers=phy_headers))
        set_clock(client, "2026-09-01T17:15:00Z")
        get_success_data(client.resume_capture(capture["id"], headers=phy_headers))
        set_clock(client, "2026-09-01T17:20:00Z")
        get_success_data(client.stop_capture(capture["id"], headers=phy_headers))
        get_success_data(client.simulate_transcription(capture["id"], headers=ADMIN))
        enc_v = get_success_data(
            client.get_encounter(encounter["id"], headers=phy_headers)
        )["version"]
        draft = get_success_data(
            client.create_note_draft(
                encounter["id"],
                f.create_note_draft_payload(template["id"], enc_v),
                headers=phy_headers,
            )
        )
        get_success_data(
            client.patch_note_draft(
                draft["id"],
                f.patch_note_draft_payload(
                    draft["version"],
                    [
                        f.field_update("chief_complaint", "chest pain"),
                        f.field_update("hpi", "3 days"),
                        f.field_update("exam", "normal"),
                        f.field_update("plan", "stress test"),
                    ],
                ),
                headers=phy_headers,
            )
        )
        get_success_data(client.submit_review(draft["id"], headers=phy_headers))
        set_clock(client, "2026-09-01T17:25:00Z")
        get_success_data(client.complete_encounter(encounter["id"], headers=phy_headers))
        set_clock(client, "2026-09-01T19:30:00Z")
        get_success_data(client.attest_draft(draft["id"], headers=phy_headers))
        return {"physician": physician, "physician_headers": phy_headers}

    def test_provisional_final_and_after_hours_minutes(self, client):
        """PRD 3.8: "`provisional_minutes` is the wall-clock measure: each
        span's duration is converted to whole minutes (sub-minute remainders
        truncated per span, with partial minutes rounded up to the next whole
        minute before truncation of further precision) — that is, each span
        contributes its duration rounded up to the next minute — and the
        per-span minutes are summed."
        PRD 3.8: "`final_minutes` is the effort-adjusted measure over the
        identical spans: from each span's minutes, the minutes of that
        encounter's `PAUSED` recording intervals are subtracted before
        summing."
        PRD 3.8: "`after_hours_minutes` sums, over the same spans, the minutes
        of each span that fall between 18:00:00Z and midnight or between
        midnight and 07:00:00Z UTC, minus any paused minutes inside those
        windows."

        Design: Difficulty/dual_variant_calc/documentation_minutes_provisional_vs_final_on_encounter_spans
        """
        world = self._attested_world_with_pause(client)
        metric = validate_success(
            client.recompute_documentation_metrics(
                world["physician"]["id"],
                {"period_start": "2026-09-01T00:00:00Z"},
                headers=world["physician_headers"],
            )
        )
        assert metric["provisional_minutes"] == 210, (
            "19:30 - 16:00 wall clock = 210, got {0}".format(
                metric["provisional_minutes"]
            )
        )
        assert metric["final_minutes"] == 195, (
            "210 minus the 15-minute pause = 195, got {0}".format(
                metric["final_minutes"]
            )
        )
        assert metric["after_hours_minutes"] == 90, (
            "18:00-19:30 = 90 minutes in the after-hours window, got {0}".format(
                metric["after_hours_minutes"]
            )
        )
        assert metric["notes_attested"] == 1

    def test_provisional_differs_from_final_on_identical_spans(self, client):
        """PRD 3.8: "`final_minutes` is the effort-adjusted measure over the
        identical spans: from each span's minutes, the minutes of that
        encounter's `PAUSED` recording intervals are subtracted before
        summing."

        Design: Difficulty/dual_variant_calc/documentation_minutes_provisional_vs_final_on_encounter_spans
        """
        world = self._attested_world_with_pause(client)
        metric = validate_success(
            client.recompute_documentation_metrics(
                world["physician"]["id"],
                {"period_start": "2026-09-01T00:00:00Z"},
                headers=world["physician_headers"],
            )
        )
        assert metric["provisional_minutes"] == 210
        assert metric["final_minutes"] == 195
        assert metric["provisional_minutes"] != metric["final_minutes"], (
            "The two variants must diverge on identical span data"
        )
