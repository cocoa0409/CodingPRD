"""Composite setup builders and the pytest fixtures that expose them.

Every builder drives the public API only.  Builders use ``get_success_data``
so a setup step the PRD allows to answer 200 or 201 is not pinned to one of
the two at every call site.

The running harness restarts the server before every test, so each test
rebuilds its world from scratch: the central builder ``ready_world`` walks
patient -> physician -> template -> clock -> encounter -> consent -> start
-> capture -> stop -> transcribe and returns every id and header a test
needs.

Identity threading: Patient, Physician and QAAuditor are entity-backed
roles, so ownership-gated calls are always made with
``make_physician_headers(physician["id"])`` / ``make_patient_headers(patient["id"])``
/ ``make_qa_auditor_headers(auditor["id"])`` — never a shared constant.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ADMIN,
    COMPLIANCE,
    make_patient_headers,
    make_physician_headers,
    make_qa_auditor_headers,
)

# ─── pytest fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def client():
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def api(client):
    """Alias kept so a test can read either name."""
    return client


# ─── Logical clock ────────────────────────────────────────────────────────


def set_clock(client, to_iso8601):
    """Advance the logical clock; the response carries the new time."""
    resp = client.set_clock(to_iso8601, headers=ADMIN)
    return get_success_data(resp)


# ─── Registry builders ────────────────────────────────────────────────────


def create_patient(client, **overrides):
    resp = client.create_patient(f.create_patient_payload(**overrides), headers=ADMIN)
    return get_success_data(resp)


def create_physician(client, **overrides):
    resp = client.create_physician(f.create_physician_payload(**overrides), headers=ADMIN)
    return get_success_data(resp)


def create_qa_auditor(client, **overrides):
    resp = client.create_qa_auditor(
        f.create_qa_auditor_payload(**overrides), headers=ADMIN
    )
    return get_success_data(resp)


def create_note_template(client, **overrides):
    resp = client.create_note_template(
        f.create_note_template_payload(**overrides), headers=ADMIN
    )
    return get_success_data(resp)


# ─── World assembly ───────────────────────────────────────────────────────


def create_encounter(client, patient, physician, **overrides):
    """Create an encounter as the attending physician (ownership-gated)."""
    headers = make_physician_headers(physician["id"])
    resp = client.create_encounter(
        f.create_encounter_payload(patient["id"], physician["id"], **overrides),
        headers=headers,
    )
    return get_success_data(resp)


def grant_consent(client, encounter, patient, **overrides):
    """Grant consent as the patient (ownership-gated). Returns the consent."""
    headers = make_patient_headers(patient["id"])
    resp = client.grant_consent(
        encounter["id"], f.grant_consent_payload(patient["id"], **overrides),
        headers=headers,
    )
    return get_success_data(resp)


def start_encounter(client, encounter, physician):
    headers = make_physician_headers(physician["id"])
    return get_success_data(client.start_encounter(encounter["id"], headers=headers))


def start_capture(client, encounter, physician, **overrides):
    headers = make_physician_headers(physician["id"])
    resp = client.start_audio_capture(
        encounter["id"], f.start_capture_payload(**overrides), headers=headers
    )
    return get_success_data(resp)


def stop_capture(client, capture, physician):
    headers = make_physician_headers(physician["id"])
    return get_success_data(client.stop_capture(capture["id"], headers=headers))


def transcribe(client, capture):
    return get_success_data(client.simulate_transcription(capture["id"], headers=ADMIN))


def refresh_encounter_version(client, encounter, physician):
    headers = make_physician_headers(physician["id"])
    body = get_success_data(client.get_encounter(encounter["id"], headers=headers))
    return body["version"]


def create_draft(client, encounter, physician, template):
    """Create a note draft with a fresh OCC version for the encounter."""
    headers = make_physician_headers(physician["id"])
    enc_v = refresh_encounter_version(client, encounter, physician)
    resp = client.create_note_draft(
        encounter["id"],
        f.create_note_draft_payload(template["id"], enc_v),
        headers=headers,
    )
    return get_success_data(resp)


def edit_draft(client, draft, physician, field_updates):
    """PATCH a draft with its current version; returns the updated draft."""
    headers = make_physician_headers(physician["id"])
    current = get_success_data(client.get_note_draft(draft["id"], headers=headers))
    resp = client.patch_note_draft(
        draft["id"],
        f.patch_note_draft_payload(current["version"], field_updates),
        headers=headers,
    )
    return get_success_data(resp)


def submit_review(client, draft, physician):
    headers = make_physician_headers(physician["id"])
    return get_success_data(client.submit_review(draft["id"], headers=headers))


def attest(client, draft, physician):
    headers = make_physician_headers(physician["id"])
    return get_success_data(client.attest_draft(draft["id"], headers=headers))


def ready_world(
    client,
    field_specs=None,
    clock_instant="2026-09-01T16:00:00Z",
    template_overrides=None,
    captured_via="ROOM_SIGNAGE",
    planned_retention_days=30,
    scheduled_start=None,
):
    """Patient + physician + template + clock + encounter + consent + start
    + capture -> stop -> transcribe.  Returns a dict with everything a test
    needs to keep going.

    After this builder the encounter is IN_PROGRESS with a GRANTED consent
    and one TRANSCRIBED capture — the canonical precondition for drafting.
    """
    patient = create_patient(client)
    physician = create_physician(client)
    tpl_overrides = dict(template_overrides or {})
    if field_specs is not None:
        tpl_overrides["field_specs"] = field_specs
    template = create_note_template(client, **tpl_overrides)
    set_clock(client, clock_instant)
    enc_overrides = {}
    if scheduled_start is not None:
        enc_overrides["scheduled_start"] = scheduled_start
    encounter = create_encounter(client, patient, physician, **enc_overrides)
    consent = grant_consent(client, encounter, patient, captured_via=captured_via)
    encounter = start_encounter(client, encounter, physician)
    capture = start_capture(
        client, encounter, physician, planned_retention_days=planned_retention_days
    )
    capture = stop_capture(client, capture, physician)
    capture = transcribe(client, capture)
    return {
        "patient": patient,
        "physician": physician,
        "template": template,
        "encounter": encounter,
        "consent": consent,
        "capture": capture,
        "physician_headers": make_physician_headers(physician["id"]),
        "patient_headers": make_patient_headers(patient["id"]),
    }


def world_with_draft(client, field_specs=None, **world_kwargs):
    """ready_world plus a freshly created note draft."""
    world = ready_world(client, field_specs=field_specs, **world_kwargs)
    world["draft"] = create_draft(
        client, world["encounter"], world["physician"], world["template"]
    )
    return world


def world_with_attested_draft(client, fill_updates=None, **world_kwargs):
    """A world whose single-CRITICAL-field draft is filled, submitted, and
    attested (completeness 100 on a one-required-field template)."""
    world = world_with_draft(client, **world_kwargs)
    physician = world["physician"]
    draft = world["draft"]
    if fill_updates is None:
        # Fill every required field on the template so completeness reaches 100.
        fill_updates = [
            f.field_update(spec["key"], "documented")
            for spec in world["template"]["field_specs"]
            if spec.get("required")
        ]
    if fill_updates:
        draft = edit_draft(client, draft, physician, fill_updates)
    draft = submit_review(client, draft, physician)
    draft = attest(client, draft, physician)
    world["draft"] = draft
    return world
