"""Composite setup helpers — multi-step preconditions built from PRD endpoints.

Every fixture builds its state from scratch (the server is restarted before
each test). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    VALID_HASH,
    create_agency_payload,
    create_budget_plan_payload,
    create_case_payload,
    create_device_payload,
    create_legal_hold_payload,
    create_officer_payload,
    create_policy_payload,
    create_recording_payload,
    create_redaction_job_payload,
    create_share_grant_payload,
)
from .test_users import (
    TEST_USERS,
    make_officer_headers,
    make_supervisor_headers,
)

ADMIN = TEST_USERS["agency_admin_headers"]
DC = TEST_USERS["device_coordinator_headers"]
RO = TEST_USERS["records_officer_headers"]

CLOCK_START = TEST_DEFAULTS["CLOCK_START"]
# PRD section 2.4/3.4: a content_hash_sha256 that is not exactly 64 lowercase
# hex is rejected with ERR_VALIDATION — it can never reach the integrity
# comparison. A declared integrity mismatch is instead produced by pairing a
# well-formed hash with a `payload` whose server-recomputed SHA-256 differs.
MISMATCH_HASH = "b" * 64  # well-formed; mismatches MISMATCH_PAYLOAD's SHA-256
MISMATCH_PAYLOAD = "tampered-media-bytes"


def set_clock(to_iso8601=CLOCK_START):
    """Pin the logical clock. Defaults to the PRD's default start instant."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_agency(name="Metro PD", **overrides):
    resp = api_client.create_agency(create_agency_payload(name=name, **overrides), ADMIN)
    return get_success_data(resp)


def create_active_policy(agency_id, **overrides):
    """Create + activate a policy. Returns the ACTIVE policy."""
    resp = api_client.create_policy(agency_id, create_policy_payload(**overrides), ADMIN)
    pol = get_success_data(resp)
    resp = api_client.activate_policy(agency_id, pol["id"], ADMIN)
    return get_success_data(resp)


def create_officer(agency_id, badge_number="B-100", full_name="Ana Ruiz", rank="OFFICER"):
    resp = api_client.create_officer(
        agency_id,
        create_officer_payload(badge_number=badge_number, full_name=full_name, rank=rank),
        ADMIN,
    )
    return get_success_data(resp)


def create_device(agency_id, serial_number="SN-1", model="AXON-B4", **overrides):
    resp = api_client.create_device(
        agency_id,
        create_device_payload(serial_number=serial_number, model=model, **overrides),
        DC,
    )
    return get_success_data(resp)


def assign_device(agency_id, device_id, officer_id):
    resp = api_client.assign_device(agency_id, device_id, {"officer_id": officer_id}, DC)
    return get_success_data(resp)


def setup_agency_with_policy(name="Metro PD", **policy_overrides):
    """Agency + ACTIVE policy. Returns (agency, policy)."""
    agency = create_agency(name=name)
    policy = create_active_policy(agency["id"], **policy_overrides)
    return agency, policy


def setup_officer_with_device(agency_id, badge_number="B-100", serial_number="SN-1",
                              officer_name="Ana Ruiz", rank="OFFICER",
                              device_overrides=None):
    """Officer + registered device assigned to them. Returns (officer, device)."""
    officer = create_officer(agency_id, badge_number=badge_number,
                             full_name=officer_name, rank=rank)
    device = create_device(agency_id, serial_number=serial_number,
                           **(device_overrides or {}))
    device = assign_device(agency_id, device["id"], officer["id"])
    return officer, device


def setup_agency_with_policy_and_officer(name="Metro PD", policy_overrides=None,
                                         officer_rank="OFFICER"):
    """Agency + ACTIVE policy + officer with assigned docked device.
    Returns (agency, policy, officer, device)."""
    agency, policy = setup_agency_with_policy(name=name, **(policy_overrides or {}))
    officer, device = setup_officer_with_device(agency["id"], rank=officer_rank)
    return agency, policy, officer, device


def upload_recording(agency_id, device, officer, **overrides):
    """Upload a recording as the device's assigned officer (ownership-threaded)."""
    payload = create_recording_payload(device["id"], **overrides)
    resp = api_client.create_recording(agency_id, payload, make_officer_headers(officer["id"]))
    return get_success_data(resp)


def upload_active_recordings(agency_id, device, officer, count, size_bytes=1048576,
                             category="INCIDENT", duration_seconds=60):
    """Upload `count` recordings at one-minute offsets. Returns list of recordings.

    The logical clock is pinned just past the final offset first, so that no
    upload's recorded_at lies in the future relative to the logical clock
    (PRD section 3.4 rejects future-dated recorded_at with ERR_VALIDATION).
    """
    if count > 0:
        last_offset = count - 1
        set_clock(f"2026-09-01T00:{last_offset:02d}:00Z")
    recordings = []
    for i in range(count):
        recorded_at = f"2026-09-01T00:{i:02d}:00Z"
        recordings.append(upload_recording(
            agency_id, device, officer,
            recorded_at=recorded_at, size_bytes=size_bytes,
            category=category, duration_seconds=duration_seconds,
        ))
    return recordings


def create_case(agency_id, lead_officer, case_number="CN-1", title="Case One"):
    resp = api_client.create_case(
        agency_id,
        create_case_payload(lead_officer["id"], case_number=case_number, title=title),
        make_officer_headers(lead_officer["id"]),
    )
    return get_success_data(resp)


def link_evidence(agency_id, case_id, recording_id, officer):
    resp = api_client.link_evidence(
        agency_id, case_id, {"recording_id": recording_id},
        make_officer_headers(officer["id"]),
    )
    return get_success_data(resp)


def submit_case(agency_id, case_id, officer):
    resp = api_client.submit_case_review(agency_id, case_id, make_officer_headers(officer["id"]))
    return get_success_data(resp)


def close_case(agency_id, case_id, supervisor_officer):
    """Close a case acting as Supervisor with the given (sergeant+) officer's id."""
    resp = api_client.close_case(agency_id, case_id, make_supervisor_headers(supervisor_officer["id"]))
    return get_success_data(resp)


def get_case(agency_id, case_id, headers=RO):
    resp = api_client.get_case(agency_id, case_id, headers)
    return get_success_data(resp)


def create_share_grant(agency_id, case_id, expected_case_version, headers=RO, **overrides):
    resp = api_client.create_share_grant(
        agency_id, case_id,
        create_share_grant_payload(expected_case_version, **overrides),
        headers,
    )
    return get_success_data(resp)


def setup_closed_case_with_grant(name="Metro PD", num_recordings=1, policy_overrides=None,
                                 grant_overrides=None):
    """Full pipeline: agency + policy + officer + device + N ACTIVE recordings linked
    to a case, case CLOSED, one ACTIVE share grant.
    Returns dict with agency, policy, officer, device, recordings, case, grant."""
    agency, policy = setup_agency_with_policy(name=name, **(policy_overrides or {}))
    officer, device = setup_officer_with_device(agency["id"])
    recordings = upload_active_recordings(agency["id"], device, officer, num_recordings)
    case = create_case(agency["id"], officer)
    for rec in recordings:
        link_evidence(agency["id"], case["id"], rec["id"], officer)
    submit_case(agency["id"], case["id"], officer)
    close_case(agency["id"], case["id"], officer)
    case = get_case(agency["id"], case["id"])
    grant = create_share_grant(agency["id"], case["id"], case["version"],
                               **(grant_overrides or {}))
    return {
        "agency": agency,
        "policy": policy,
        "officer": officer,
        "device": device,
        "recordings": recordings,
        "case": case,
        "grant": grant,
    }


def create_redaction_job(agency_id, recording_id, headers=RO, **overrides):
    resp = api_client.create_redaction_job(
        agency_id, recording_id, create_redaction_job_payload(**overrides), headers,
    )
    return get_success_data(resp)


def create_budget_plan(agency_id, **overrides):
    resp = api_client.create_budget_plan(agency_id, create_budget_plan_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_legal_hold(agency_id, headers=RO, **overrides):
    resp = api_client.create_legal_hold(
        agency_id, create_legal_hold_payload(**overrides), headers,
    )
    return get_success_data(resp)


def run_retention(agency_id):
    resp = api_client.run_retention(agency_id, ADMIN)
    return get_success_data(resp)


def refresh_recording(agency_id, recording_id, headers=RO):
    resp = api_client.get_recording(agency_id, recording_id, headers)
    return get_success_data(resp)


def refresh_officer(agency_id, officer_id, headers=RO):
    resp = api_client.get_officer(agency_id, officer_id, headers)
    return get_success_data(resp)


def refresh_agency(agency_id, headers=RO):
    resp = api_client.get_agency(agency_id, headers)
    return get_success_data(resp)


def list_custody_events(agency_id, recording_id, headers=RO):
    """Return the custody-event list for a recording."""
    resp = api_client.list_custody_events_for_recording(agency_id, recording_id, headers)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return data.get("items", data) if isinstance(data, dict) else data
