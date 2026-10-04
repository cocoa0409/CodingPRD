"""Cross-cutting corners: derived-field reconciliation (live counter vs
stale minutes until recompute), create-with-supersede, and the
immediate-consistency read of the recomputed score in the PATCH response.
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
from test_helpers.test_users import ADMIN


def _attested_world_with_one_hour_span(client):
    """Start 16:00, capture, transcribe, draft, fill, submit, attest at
    17:00: a 60-minute documentation span with no pauses."""
    patient = create_patient(client)
    physician = create_physician(client)
    template = create_note_template(
        client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
    )
    headers = {"X-User-ID": physician["id"], "X-User-Role": "Physician"}
    set_clock(client, "2026-09-01T16:00:00Z")
    encounter = create_encounter(client, patient, physician)
    grant_consent(client, encounter, patient)
    encounter = start_encounter(client, encounter, physician)
    capture = start_capture(client, encounter, physician)
    capture = stop_capture(client, capture, physician)
    transcribe(client, capture)
    draft = create_draft(client, encounter, physician, template)
    draft = edit_draft(
        client, draft, physician, [f.field_update("chief_complaint", "fever")]
    )
    submit_review(client, draft, physician)
    set_clock(client, "2026-09-01T17:00:00Z")
    get_success_data(client.attest_draft(draft["id"], headers=headers))
    return {"physician": physician, "headers": headers}


class TestMetricMinutesStaleUntilRecompute:
    def test_counter_live_and_minutes_stale_then_reconciled(self, client):
        """PRD 3.8: "Until a recompute runs, all three counters read 0."
        PRD 3.8: "The `notes_attested` counter is maintained live by
        attestation and amendment (§3.5) rather than by recompute."

        Design: Corner/cross_cutting_layers/corner_metric_minutes_stale_until_recompute
        """
        world = _attested_world_with_one_hour_span(client)
        rows, _meta = validate_paginated(
            client.list_documentation_metrics(
                world["physician"]["id"], headers=world["headers"]
            )
        )
        assert len(rows) == 1
        assert rows[0]["notes_attested"] == 1
        assert rows[0]["provisional_minutes"] == 0, (
            "derived minutes stay 0 until recompute reconciles them"
        )

        metric = validate_success(
            client.recompute_documentation_metrics(
                world["physician"]["id"],
                {"period_start": "2026-09-01T00:00:00Z"},
                headers=world["headers"],
            )
        )
        assert metric["provisional_minutes"] == 60, (
            "16:00 -> 17:00 with no pauses, got {0}".format(
                metric["provisional_minutes"]
            )
        )
        assert metric["final_minutes"] == 60


class TestDraftCreateSupersedesActiveDraft:
    def test_second_create_voids_the_first(self, client):
        """PRD 3.4: "Generation supersedes any existing draft of the
        encounter in `DRAFT`, `EDITED`, `IN_REVIEW`, or `AMENDED` — the
        superseded draft moves to `VOID`"

        Design: Corner/cross_cutting_layers/corner_draft_create_supersedes_active_draft
        """
        world = ready_world(
            client, field_specs=[f.field_spec("chief_complaint", "CRITICAL", True)]
        )
        headers = world["physician_headers"]
        draft1 = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        draft2 = create_draft(
            client, world["encounter"], world["physician"], world["template"]
        )
        assert draft2["id"] != draft1["id"]
        body = validate_success(client.get_note_draft(draft1["id"], headers=headers))
        assert body["status"] == "VOID", "superseded by the new draft"


class TestPatchResponseImmediatelyReflectsRecompute:
    def test_recomputed_score_in_patch_response(self, client):
        """PRD 3.4: "Each edited field has its `field_value` set, its
        `source` flipped to `MANUAL`, and its `validated` flag set true, and
        the `completeness_score` is recomputed."
        PRD 2.4: "`version` is an integer that starts at its initial value
        at creation and increments by exactly 1 on every mutation of the
        resource"

        Design: Corner/consistency_model/corner_patch_response_immediately_reflects_recompute
        """
        world = ready_world(
            client,
            field_specs=[
                f.field_spec("chief_complaint", "CRITICAL", True),
                f.field_spec("ros", "MINOR", True),
            ],
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
        assert body["completeness_score"] == 95, (
            "missing MINOR ros: 100 - 5, in the PATCH response itself; got "
            "{0}".format(body["completeness_score"])
        )
        assert body["version"] == draft["version"] + 1
