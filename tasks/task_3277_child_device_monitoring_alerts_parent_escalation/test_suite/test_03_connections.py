"""Service connections: initial state, credential secrecy, duplicates, cycles."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_connection,
    create_connection,
    create_family,
    create_child,
    make_parent_headers,
    set_connection_state,
    validate_error,
    validate_success,
)


def test_connection_starts_awaiting_consent(api):
    """PRD §3.4: "A new connection starts in `AWAITING_CONSENT`."

    Design: Corner/entities/connection_starts_awaiting_consent
    """
    fam, parent = create_family()
    child = create_child(fam["id"], parent["id"])
    conn = create_connection(
        child["id"], parent["id"],
        service_type="EMAIL", external_handle="kidcn@mail", credential_token="tok-cn",
    )
    assert_connection(conn)
    assert conn["consent_status"] == "AWAITING_CONSENT"


def test_credential_token_never_serialized(api):
    """PRD §2.9: "The `credential_token` supplied when connecting an external
    service is write-only: it is stored opaquely and never serialized in any
    response, to any role."

    Design: Corner/entities/credential_token_never_serialized
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    resp = api.create_connection(
        child["id"],
        {"service_type": "SOCIAL", "external_handle": "kidct@social",
         "credential_token": "supersecret"},
        headers,
    )
    body = resp.text
    assert "credential_token" not in body and "supersecret" not in body, (
        "create response must not echo credential_token"
    )
    conn_id = resp.json()["data"]["id"]

    resp = api.get_connection(conn_id, headers)
    validate_success(resp)
    body = resp.text
    assert "credential_token" not in body and "supersecret" not in body, (
        "GET response must not serialize credential_token"
    )


def test_duplicate_connection_rejected(api):
    """PRD §3.4: "At most one connection per combination of child,
    `service_type`, and `external_handle` may exist outside the `REVOKED` state.
    Creating a connection while another connection for the same child, service
    type, and handle is `AWAITING_CONSENT`, `ACTIVE`, or `PAUSED` is rejected
    with `ERR_DUPLICATE_CONNECTION`; once the earlier connection is `REVOKED`,
    the handle may be connected again."

    Design: Corner/validations/duplicate_connection_rejected
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    resp = api.create_connection(
        child["id"],
        {"service_type": "MESSAGING", "external_handle": "kidz@msg",
         "credential_token": "tok-d1"},
        headers,
    )
    validate_success(resp, expected_status=201)

    # Exact duplicate -> 409.
    resp = api.create_connection(
        child["id"],
        {"service_type": "MESSAGING", "external_handle": "kidz@msg",
         "credential_token": "tok-d2"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CONNECTION)

    # Same handle under a different service type is accepted.
    resp = api.create_connection(
        child["id"],
        {"service_type": "EMAIL", "external_handle": "kidz@msg",
         "credential_token": "tok-d3"},
        headers,
    )
    validate_success(resp, expected_status=201)


def test_connection_pause_resume_reconsent_cycle(api):
    """PRD §3.4: "From `AWAITING_CONSENT`, consenting moves the connection to
    `ACTIVE`. This requires the child to be `ACTIVE` (otherwise
    `ERR_CHILD_ARCHIVED`) and the family to be `ACTIVE` (otherwise
    `ERR_FAMILY_SUSPENDED`)."
    PRD §3.4: "From `ACTIVE`, pausing moves it to `PAUSED` with no further
    preconditions."
    PRD §3.4: "From `PAUSED`, resuming moves it back to `ACTIVE`, requiring only
    that the child is still `ACTIVE` (`ERR_CHILD_ARCHIVED`)."
    PRD §3.4: "From either `ACTIVE` or `PAUSED`, revoking moves it to `REVOKED`
    with no further preconditions."
    PRD §3.4: "From `REVOKED`, a re-consent flow returns it to
    `AWAITING_CONSENT`, again requiring the child to be `ACTIVE`
    (`ERR_CHILD_ARCHIVED`)."
    PRD §3.4: "Every successful connection state change increments the
    connection's `version` by 1."

    Design: Difficulty/non_linear_state_machine/connection_pause_resume_reconsent_cycle
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"], birth_year=2010)
    conn = create_connection(
        child["id"], parent["id"],
        service_type="SOCIAL", external_handle="kidk@social",
        credential_token="tok-k",
    )
    assert conn["version"] == 1

    # ACTIVE -> PAUSED -> ACTIVE -> REVOKED -> AWAITING_CONSENT -> ACTIVE.
    expected_states = ["ACTIVE", "PAUSED", "ACTIVE", "REVOKED", "AWAITING_CONSENT", "ACTIVE"]
    current = conn
    for i, to_status in enumerate(expected_states):
        current = set_connection_state(current["id"], parent["id"], to_status)
        assert current["consent_status"] == to_status
        assert current["version"] == 2 + i, (
            f"after {i + 1} transitions version must be {2 + i}, got {current['version']}"
        )

    assert current["version"] == 7


def test_connection_invalid_transition_returns_409(api):
    """PRD §3.4: "Requesting a transition that does not exist from the
    connection's current state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/connection_pause_resume_reconsent_cycle
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])
    conn = create_connection(child["id"], parent["id"])

    # AWAITING_CONSENT -> REVOKED is not a declared edge.
    resp = api.set_connection_state(conn["id"], {"to_status": "REVOKED"}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    current = validate_success(api.get_connection(conn["id"], headers))
    assert current["consent_status"] == "AWAITING_CONSENT"
