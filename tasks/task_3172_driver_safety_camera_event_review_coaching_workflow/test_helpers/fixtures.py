"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints, using the lenient get_success_data() validator so setup failures
surface as clear "Setup failed" errors.

Shared base scenario (used by most fixtures):
  - logical clock at the default instant 2026-09-01T00:00:00Z
  - fleet (budget 1000000c), terminal, driver (E-1001, consent true),
    HIGH-tier vehicle, ACTIVE policy (cap 100 MB, inward enabled, all
    detections on, retention 30/180d)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, THRESHOLDS
from .factories import (
    create_camera_policy_payload,
    create_driver_payload,
    create_exoneration_claim_payload,
    create_fleet_payload,
    create_footage_clip_payload,
    create_litigation_hold_payload,
    create_safety_event_payload,
    create_terminal_payload,
    create_vehicle_payload,
    decide_claim_payload,
    review_payload,
)
from .test_users import (
    TEST_USERS,
    make_claims_adjuster_headers,
    make_driver_headers,
    make_safety_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INGEST = TEST_USERS["telematics_ingest_headers"]
MANAGER = TEST_USERS["safety_manager_headers"]  # reviewer_id sm-1
ADJUSTER = TEST_USERS["claims_adjuster_headers"]  # decided_by ca-1
EXEC = TEST_USERS["fleet_admin_headers"]
REVIEWER_ID = TEST_DEFAULTS["REVIEWER_USER_ID"]


def _setup_fail(step: str, resp):
    raise AssertionError(f"Setup failed at step {step}: {resp.status_code} {resp.text}")


def _data(step: str, resp):
    body = get_success_data(resp)
    if resp.status_code >= 400:
        _setup_fail(step, resp)
    return body


# ---------------------------------------------------------------------------
# Tier 1: basic anchors
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    if resp.status_code >= 400:
        _setup_fail("set_clock", resp)
    return get_success_data(resp)


def reset_clock_default():
    return set_clock(THRESHOLDS["CLOCK_DEFAULT_ISO"])


def create_fleet(**overrides):
    resp = api_client.create_fleet(create_fleet_payload(**overrides), ADMIN)
    if resp.status_code >= 400:
        _setup_fail("create_fleet", resp)
    return get_success_data(resp)


def create_terminal(fleet_id, **overrides):
    resp = api_client.create_terminal(create_terminal_payload(fleet_id, **overrides), ADMIN)
    if resp.status_code >= 400:
        _setup_fail("create_terminal", resp)
    return get_success_data(resp)


def create_driver(terminal_id, **overrides):
    resp = api_client.create_driver(create_driver_payload(terminal_id, **overrides), ADMIN)
    if resp.status_code >= 400:
        _setup_fail("create_driver", resp)
    return get_success_data(resp)


def create_vehicle(terminal_id, **overrides):
    resp = api_client.create_vehicle(create_vehicle_payload(terminal_id, **overrides), ADMIN)
    if resp.status_code >= 400:
        _setup_fail("create_vehicle", resp)
    return get_success_data(resp)


def create_active_policy(fleet_id, **overrides):
    resp = api_client.create_camera_policy(create_camera_policy_payload(fleet_id, **overrides), ADMIN)
    if resp.status_code >= 400:
        _setup_fail("create_camera_policy", resp)
    policy = get_success_data(resp)
    resp = api_client.activate_camera_policy(policy["id"], ADMIN)
    if resp.status_code >= 400:
        _setup_fail("activate_camera_policy", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: base scenario
# ---------------------------------------------------------------------------

def setup_base(clock: str = "2026-09-01T00:00:00Z", **overrides):
    """Clock + fleet + terminal + driver + HIGH-tier vehicle + ACTIVE policy.

    Returns a dict with keys: fleet, terminal, driver, vehicle, policy.
    """
    set_clock(clock)
    fleet = create_fleet(**overrides.get("fleet", {}))
    terminal = create_terminal(fleet["id"], **overrides.get("terminal", {}))
    driver = create_driver(terminal["id"], **overrides.get("driver", {}))
    vehicle = create_vehicle(terminal["id"], **overrides.get("vehicle", {}))
    policy = create_active_policy(fleet["id"], **overrides.get("policy", {}))
    return {
        "fleet": fleet,
        "terminal": terminal,
        "driver": driver,
        "vehicle": vehicle,
        "policy": policy,
    }


# ---------------------------------------------------------------------------
# Tier 3: event lifecycle helpers
# ---------------------------------------------------------------------------

def ingest_event(fleet_id, driver_id, vehicle_id, **overrides):
    resp = api_client.create_safety_event(
        create_safety_event_payload(fleet_id, driver_id, vehicle_id, **overrides), INGEST
    )
    if resp.status_code >= 400:
        _setup_fail("ingest_event", resp)
    return get_success_data(resp)


def register_clip(event_id, **overrides):
    resp = api_client.create_footage_clip(
        create_footage_clip_payload(event_id, **overrides), INGEST
    )
    if resp.status_code >= 400:
        _setup_fail("register_clip", resp)
    return get_success_data(resp)


def upload_clip(clip_id):
    """QUEUED -> UPLOADING -> UPLOADED. Returns the final clip payload."""
    resp = api_client.upload_begin_clip(clip_id, INGEST)
    if resp.status_code >= 400:
        _setup_fail("upload_begin_clip", resp)
    resp = api_client.upload_complete_clip(clip_id, INGEST)
    if resp.status_code >= 400:
        _setup_fail("upload_complete_clip", resp)
    return get_success_data(resp)


def get_event(event_id):
    resp = api_client.get_safety_event(event_id, MANAGER)
    if resp.status_code >= 400:
        _setup_fail("get_event", resp)
    return get_success_data(resp)


def review_event(event_id, action, rationale="reviewed", reviewer=REVIEWER_ID, **overrides):
    """Fetch the current version, then apply a review action. Returns the
    updated event payload."""
    current = get_event(event_id)
    resp = api_client.review_safety_event(
        event_id,
        review_payload(action, current["version"], rationale=rationale, **overrides),
        make_safety_manager_headers(reviewer),
    )
    if resp.status_code >= 400:
        _setup_fail(f"review_event[{action}]", resp)
    return get_success_data(resp)


def create_event_in_review(fleet_id, driver_id, vehicle_id, **overrides):
    """Ingest an event and upload one clip so it reaches IN_REVIEW."""
    occurred_at = overrides.pop("occurred_at", "2026-08-30T00:00:00Z")
    event = ingest_event(fleet_id, driver_id, vehicle_id, occurred_at=occurred_at, **overrides)
    clip = register_clip(event["id"], captured_at=occurred_at)
    upload_clip(clip["id"])
    return get_event(event["id"])


def create_confirmed_event(fleet_id, driver_id, vehicle_id, reviewer=REVIEWER_ID, **overrides):
    """Event brought to IN_REVIEW then CONFIRMED."""
    event = create_event_in_review(fleet_id, driver_id, vehicle_id, **overrides)
    return review_event(event["id"], "CONFIRM", reviewer=reviewer)


# ---------------------------------------------------------------------------
# Tier 4: claims / sessions / escalation composites
# ---------------------------------------------------------------------------

def submit_claim(event_id, driver_id, **overrides):
    resp = api_client.create_exoneration_claim(
        event_id,
        create_exoneration_claim_payload(**overrides),
        make_driver_headers(driver_id),
    )
    if resp.status_code >= 400:
        _setup_fail("submit_claim", resp)
    return get_success_data(resp)


def claim_in_evidence_review(event_id, driver_id, **overrides):
    claim = submit_claim(event_id, driver_id, **overrides)
    resp = api_client.begin_review_exoneration_claim(claim["id"], ADJUSTER)
    if resp.status_code >= 400:
        _setup_fail("begin_review_claim", resp)
    return get_success_data(resp)


def get_event_auto_session(event_id):
    resp = api_client.list_event_coaching_sessions(event_id, MANAGER)
    if resp.status_code >= 400:
        _setup_fail("list_event_coaching_sessions", resp)
    sessions = get_success_data(resp)
    assert len(sessions) == 1, f"expected exactly one auto session, got {len(sessions)}"
    return sessions[0]


def get_driver_awards(driver_id):
    resp = api_client.list_driver_incentive_awards(driver_id, EXEC)
    if resp.status_code >= 400:
        _setup_fail("list_driver_incentive_awards", resp)
    return get_success_data(resp)


def compute_snapshot(fleet_id, scope_type, period_start, period_end,
                     scope_id=None, finalize=False):
    payload = {
        "scope_type": scope_type,
        "period_start": period_start,
        "period_end": period_end,
        "finalize": finalize,
    }
    if scope_id is not None:
        payload["scope_id"] = scope_id
    resp = api_client.compute_score_snapshot(fleet_id, payload, EXEC)
    if resp.status_code >= 400:
        _setup_fail("compute_score_snapshot", resp)
    return get_success_data(resp)


def place_hold(fleet_id, scope, reason="matter M-1", holder=REVIEWER_ID, **overrides):
    payload = create_litigation_hold_payload(fleet_id, scope=scope, reason=reason, **overrides)
    resp = api_client.create_litigation_hold(payload, make_safety_manager_headers(holder))
    if resp.status_code >= 400:
        _setup_fail("place_hold", resp)
    return get_success_data(resp)
