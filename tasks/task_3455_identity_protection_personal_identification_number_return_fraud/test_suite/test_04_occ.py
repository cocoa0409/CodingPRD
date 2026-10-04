"""Optimistic concurrency control tests: the two OCC-guarded writes anchored
on the Taxpayer aggregate (profile update and manual pin reissue).

PRD section 2.7.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_enrolled_taxpayer,
    create_taxpayer,
    list_pins,
    reissue_protection_pin_payload,
    set_clock,
    update_taxpayer_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]


def test_occ_stale_version_profile_update_rejected(api):
    """PRD section 2.7: "If the taxpayer's current `version` no longer equals
    `expected_taxpayer_version` — because another writer, such as a profile
    edit or a report-confirmation cascade, has legitimately advanced it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller
    must re-read the taxpayer before retrying."
    PRD section 3.1: "a successful update increments the taxpayer's `version`
    by exactly 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_profile_update_rejected
    """
    taxpayer = create_taxpayer(tin="100000170")
    assert taxpayer["version"] == 1

    first = api.update_taxpayer(
        taxpayer["id"],
        update_taxpayer_payload(taxpayer["version"],
                                pin_delivery_channel="ONLINE_ACCOUNT"),
        ADMIN,
    )
    updated = validate_success(first, 200)
    assert updated["version"] == 2

    replayed = api.update_taxpayer(
        taxpayer["id"],
        update_taxpayer_payload(1, full_name="Occ Stale"),
        ADMIN,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_VERSION)


def test_occ_stale_version_pin_reissue_rejected(api):
    """PRD section 2.7: "In the reissue case this guard matters because a
    reissue supersedes the prior `ACTIVE` pin, so issuing from a stale
    taxpayer view could supersede a pin the caller never saw."
    PRD section 3.2: "The request names the `taxpayer_id`, the `tax_year`, an
    optional `delivery_channel`, and — because reissue is the second
    OCC-guarded write of §2.7 — a mandatory `expected_taxpayer_version`; a
    version that no longer matches is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_pin_reissue_rejected
    """
    set_clock("2027-01-25T00:00:00Z")
    taxpayer, pin1 = create_enrolled_taxpayer()
    # Opt-in advanced the taxpayer past the version the caller last saw.
    stale_version = taxpayer["version"] - 1

    resp = api.reissue_protection_pin(
        reissue_protection_pin_payload(taxpayer["id"], stale_version),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    pins = list_pins(taxpayer["id"])
    assert len(pins) == 1, f"No pin may be created by a stale reissue: {pins}"
    assert pins[0]["status"] == "ACTIVE"
    assert pins[0]["pin_value"] == pin1["pin_value"]
