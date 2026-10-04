"""Child profiles: age-band derivation, input validation, archival."""
import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    TEST_USERS,
    assert_child,
    create_child,
    create_child_payload,
    create_connection,
    create_family,
    make_parent_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_child_age_band_computed_from_clock(api):
    """PRD §3.1: "The child's age is derived as the current clock year minus
    `birth_year`, and must fall between 0 and 17 inclusive; a `birth_year`
    implying a negative age or an age over 17 is rejected with
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "From the age, the system derives the child's `age_band`:
    `CHILD_9_UNDER` for age 9 or younger, `PRETEEN_10_12` for ages 10 through 12,
    `TEEN_13_15` for ages 13 through 15, and `OLDER_TEEN_16_17` for ages 16 and
    17."

    Design: Corner/entities/child_age_band_computed_from_clock
    """
    fam, parent = create_family()
    cases = [
        (2020, "CHILD_9_UNDER"),
        (2014, "PRETEEN_10_12"),
        (2012, "TEEN_13_15"),
        (2009, "OLDER_TEEN_16_17"),
    ]
    for birth_year, expected_band in cases:
        child = create_child(fam["id"], parent["id"], birth_year=birth_year)
        assert_child(child)
        assert child["age_band"] == expected_band, (
            f"birth_year {birth_year}: expected age_band {expected_band}, "
            f"got {child['age_band']}"
        )


def test_child_create_with_adult_birth_year_returns_400(api):
    """PRD §3.1: "The child's age is derived as the current clock year minus
    `birth_year`, and must fall between 0 and 17 inclusive; a `birth_year`
    implying a negative age or an age over 17 is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/child_create_with_adult_birth_year_returns_400
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    payload = create_child_payload(
        family_account_id=fam["id"], display_name="Adult", birth_year=2000
    )
    resp = api.create_child(payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_child_create_missing_birth_year_returns_400(api):
    """PRD §3.1: "a `Parent` creates child profiles by submitting the
    `family_account_id`, the child's `display_name`, the child's `birth_year`,
    and optionally a `monitoring_sensitivity` of `LENIENT`, `STANDARD`, or
    `STRICT` (defaulting to `STANDARD`)."
    PRD §5: "`ERR_INVALID_REQUEST` | 400"

    Design: Corner/entities/child_create_missing_birth_year_returns_400
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    payload = {"family_account_id": fam["id"], "display_name": "NoYear"}
    resp = api.create_child(payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_child_not_found_returns_404(api, parent_headers):
    """PRD §2.7: "Any identifier that does not resolve to an existing resource
    produces `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_child_not_found_returns_404
    """
    resp = api.get_child(MISSING_UUID, parent_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_archived_child_blocks_connection_create_returns_409(api):
    """PRD §3.2: "Once a child is archived, child-scoped writes are blocked:
    consenting, resuming, or re-consenting a connection of an archived child is
    rejected with `ERR_CHILD_ARCHIVED`, as is district-link consent for an
    archived child."

    Design: Corner/state_machines/archived_child_blocks_connection_create_returns_409
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])
    resp = api.patch_child(
        child["id"],
        {"profile_status": "ARCHIVED", "expected_child_version": child["version"]},
        headers,
    )
    archived = validate_success(resp)
    assert archived["profile_status"] == "ARCHIVED"

    resp = api.create_connection(
        child["id"],
        {"service_type": "EMAIL", "external_handle": "kidar@mail",
         "credential_token": "tok-ar"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_CHILD_ARCHIVED)


def test_archive_cascades_connections_to_revoked(api):
    """PRD §3.2: "When archival succeeds, it cascades: every service connection
    of the child whose `consent_status` is `AWAITING_CONSENT`, `ACTIVE`, or
    `PAUSED` is moved to `REVOKED`, and the child's `version` increments."

    Design: Corner/state_machines/archive_cascades_connections_to_revoked
    """
    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])

    conn1 = create_connection(
        child["id"], parent["id"],
        service_type="MESSAGING", external_handle="kidac@msg",
        credential_token="tok-ac1",
    )
    resp = api.set_connection_state(conn1["id"], {"to_status": "ACTIVE"}, headers)
    validate_success(resp)
    conn2 = create_connection(
        child["id"], parent["id"],
        service_type="EMAIL", external_handle="kidac@mail",
        credential_token="tok-ac2",
    )

    resp = api.patch_child(
        child["id"],
        {"profile_status": "ARCHIVED", "expected_child_version": child["version"]},
        headers,
    )
    archived = validate_success(resp)
    assert archived["profile_status"] == "ARCHIVED"

    c1 = validate_success(api.get_connection(conn1["id"], headers))
    c2 = validate_success(api.get_connection(conn2["id"], headers))
    assert c1["consent_status"] == "REVOKED", (
        f"ACTIVE connection must be REVOKED by archive cascade, got {c1['consent_status']}"
    )
    assert c2["consent_status"] == "REVOKED", (
        f"AWAITING_CONSENT connection must be REVOKED by archive cascade, "
        f"got {c2['consent_status']}"
    )
