"""Optimistic-concurrency tests: stale-version rejection on channel-version
creation and grant resplit."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_channel,
    create_published_channel,
    create_ad_slot_grant,
    make_publisher_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_occ_channel_version_create_with_stale_expected_version():
    """PRD §2.7: "First, submitting a new channel version for certification
    requires the request to carry `expected_channel_version`, the version of
    the parent channel the client last observed. If the channel's current
    `version` has advanced beyond that observed value, the submission is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_channel_version_create_with_stale_expected_version
    """
    publisher = create_publisher(legal_name="Occ Pub")
    channel = create_channel(publisher, name="Occ Channel")
    observed_version = channel["version"]
    headers = make_publisher_headers(publisher["id"])

    payload = {
        "version_label": "1.0.0",
        "technical_checklist": {
            "deep_linking": True, "drm": True, "trick_play": True,
        },
        "expected_channel_version": observed_version,
    }
    first = validate_success(
        api_client.create_channel_version(channel["id"], payload, headers),
        expected_status=201,
    )
    assert first["review_status"] == "SUBMITTED"

    stale_payload = dict(payload, version_label="1.0.1")
    resp = api_client.create_channel_version(
        channel["id"], stale_payload, headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    current = get_success_data(api_client.get_channel(channel["id"], ADMIN))
    assert current["version"] == observed_version + 1, (
        "the failed write must not bump the channel version again"
    )


def test_occ_grant_resplit_with_stale_expected_version():
    """PRD §2.7: "Second, re-splitting an ad slot grant requires the request
    to carry `expected_grant_version`, the version of the grant the client
    last observed. A grant in `OPEN` status may be re-split repeatedly as
    publisher standing changes, so only this check distinguishes a write
    based on a stale split from one based on a fresh one; a mismatch with the
    grant's current `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_grant_resplit_with_stale_expected_version
    """
    publisher = create_publisher(legal_name="G Occ Pub",
                                 default_ad_share_bps=7000)
    channel = create_published_channel(publisher)
    grant = create_ad_slot_grant(channel["id"], period="2026-09",
                                 total_slots=1000)
    observed_version = grant["version"]
    get_success_data(api_client.set_publisher_standing(
        publisher["id"], {"to_standing": "SUSPENDED", "reason": "audit"},
        ADMIN,
    ))

    first = validate_success(api_client.resplit_ad_slot_grant(
        grant["id"], {"expected_grant_version": observed_version}, ADMIN,
    ))
    assert first["publisher_slots"] == 650, (
        f"floor(1000 * 6500/10000) = 650, got {first['publisher_slots']}"
    )
    assert first["version"] == observed_version + 1

    resp = api_client.resplit_ad_slot_grant(
        grant["id"], {"expected_grant_version": observed_version}, ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    current = get_success_data(api_client.get_ad_slot_grant(grant["id"], ADMIN))
    assert (
        current["publisher_slots"] + current["platform_slots"] == 1000
    ), "the rejected write must not disturb the split invariant"
