"""Episode activation: the authorize transition, its non-idempotency, the
first-appointment flip to ACTIVE, and in-response mutation visibility."""
from test_helpers import (
    TEST_USERS, api_client, validate_error, validate_success,
    get_authorization, schedule_appointment, setup_episode,
)

COORD = TEST_USERS["care_coordinator_headers"]
CLOCK_START = "2026-09-01T00:00:00Z"  # PRD §2.5 startup instant


def _instant(ts: str):
    """Parse an ISO-8601 UTC timestamp; the instant is contract-pinned, the
    string's fractional-second formatting is not."""
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_referral_authorize_valid_transition_sets_authorized_at():
    """PRD §3.3: "a `CareCoordinator` authorizes a `PENDING_REVIEW` referral,
    moving it to `AUTHORIZED`, stamping `authorized_at` with the current
    logical clock, and incrementing the authorization's `version` by one; from
    any other status the attempt is rejected with `ERR_INVALID_STATE`."
    PRD §2.5: "At startup the logical clock reads exactly
    2026-09-01T00:00:00Z."

    Design: Corner/state_machines/referral_authorize_valid_transition_sets_authorized_at
    """
    env = setup_episode(authorize=False)
    auth = env["authorization"]
    assert auth["status"] == "PENDING_REVIEW"

    resp = api_client.authorize_referral(auth["id"], COORD)
    data = validate_success(resp, 200)
    assert data["status"] == "AUTHORIZED"
    assert _instant(data["authorized_at"]) == _instant(CLOCK_START)
    assert data["version"] == auth["version"] + 1


def test_referral_authorize_from_authorized_returns_invalid_state():
    """PRD §3.3: "a `CareCoordinator` authorizes a `PENDING_REVIEW` referral,
    moving it to `AUTHORIZED`, stamping `authorized_at` with the current
    logical clock, and incrementing the authorization's `version` by one; from
    any other status the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/referral_authorize_from_authorized_returns_invalid_state
    """
    env = setup_episode()  # already AUTHORIZED
    auth = env["authorization"]
    assert auth["status"] == "AUTHORIZED"

    resp = api_client.authorize_referral(auth["id"], COORD)
    validate_error(resp, "ERR_INVALID_STATE")
    assert get_authorization(auth["id"])["status"] == "AUTHORIZED"


def test_first_appointment_flips_authorized_to_active():
    """PRD §3.3: "Thereafter the episode comes alive on first use — creating
    the first appointment against an `AUTHORIZED` referral flips it to `ACTIVE`
    automatically."
    PRD §3.5: "A successful booking reserves one visit — `reserved_visits`
    rises by one and `remaining_visits` falls by one — computes the
    appointment's timeliness flag, and, if it is the first appointment of an
    `AUTHORIZED` episode, flips the authorization to `ACTIVE`."

    Design: Corner/state_machines/first_appointment_flips_authorized_to_active
    """
    env = setup_episode()  # AUTHORIZED, authorized_visits == 2
    auth = env["authorization"]

    schedule_appointment(auth)
    after = get_authorization(auth["id"])
    assert after["status"] == "ACTIVE"
    assert after["reserved_visits"] == 1
    assert after["remaining_visits"] == 1


def test_mutation_visibility_immediate_in_same_response():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.3: "a `CareCoordinator` authorizes a `PENDING_REVIEW` referral,
    moving it to `AUTHORIZED`, stamping `authorized_at` with the current
    logical clock, and incrementing the authorization's `version` by one; from
    any other status the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/consistency/mutation_visibility_immediate_in_same_response
    """
    env = setup_episode(authorize=False)
    auth = env["authorization"]

    resp = api_client.authorize_referral(auth["id"], COORD)
    data = validate_success(resp, 200)
    # The mutation is fully visible in the authorize response itself.
    assert data["status"] == "AUTHORIZED"
    assert _instant(data["authorized_at"]) == _instant(CLOCK_START)
    assert data["version"] == auth["version"] + 1
