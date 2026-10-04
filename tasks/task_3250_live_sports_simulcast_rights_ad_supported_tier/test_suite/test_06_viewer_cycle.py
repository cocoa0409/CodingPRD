"""Viewer billing-posture cycle with entitlement toggling (PRD §3.4)."""
from test_helpers import (
    PM,
    get_success_data,
    make_viewer_headers,
    set_clock,
    validate_success,
    viewer_with_bundle_entitlement,
)


def _entitlements(api, viewer_id):
    resp = api.list_entitlements(PM, params={"viewer_id": viewer_id})
    data = validate_success(resp)
    return data


def test_viewer_grace_cycle_toggles_entitlement(api):
    """PRD §3.4: "If a viewer remains in `GRACE` for 72 hours of logical
    time, the system transitions the viewer to `SUSPENDED` and flips every
    `Entitlement` of that viewer to `active` equal to `false`. Reactivation
    from `SUSPENDED` reactivates the viewer's entitlements (flipping
    `active` back to `true`)."

    Full cycle: ACTIVE -> GRACE -> ACTIVE -> GRACE -> (clock +72h) ->
    SUSPENDED -> ACTIVE; the entitlement flips off at the grace lapse and
    back on at reactivation.

    Design: Difficulty/non_linear_state_machine/viewer_grace_active_suspended_cycle_with_entitlement_toggle
    """
    partner, code, viewer, entitlement = viewer_with_bundle_entitlement()
    vid = viewer["id"]
    validate_success(api.suspend_billing_viewer(vid, PM))
    v = validate_success(api.get_viewer(vid, PM))
    assert v["subscription_status"] == "GRACE"
    validate_success(api.reactivate_viewer(vid, PM))
    v = validate_success(api.get_viewer(vid, PM))
    assert v["subscription_status"] == "ACTIVE"
    validate_success(api.suspend_billing_viewer(vid, PM))
    set_clock("2026-09-05T00:00:00Z")  # well past the 72h grace lapse
    v = validate_success(api.get_viewer(vid, PM))
    assert v["subscription_status"] == "SUSPENDED", (
        f"expected grace lapse to SUSPENDED, got {v['subscription_status']}"
    )
    ents = _entitlements(api, vid)
    assert len(ents) >= 1
    assert all(e["active"] is False for e in ents)
    validate_success(api.reactivate_viewer(vid, PM))
    v = validate_success(api.get_viewer(vid, PM))
    assert v["subscription_status"] == "ACTIVE"
    ents = _entitlements(api, vid)
    assert all(e["active"] is True for e in ents)


def test_viewer_entitlement_active_after_bundle_redeem(api):
    """PRD §3.6: "On success the code transitions to `REDEEMED` with
    `redeemed_by_viewer_id` set; a new `Entitlement` is created with
    `source_type` equal to `PARTNER_BUNDLE` ... `partner_id` set to the
    issuing partner, `tier_granted` equal to the partner's `bundled_tier`,
    `active_from` set to the current logical time, and `active` equal to
    `true`; the viewer's `subscription_tier` is set to the partner's
    `bundled_tier` and `subscription_status` is set to
    `ACTIVE`;"

    Design: Difficulty/non_linear_state_machine/viewer_grace_active_suspended_cycle_with_entitlement_toggle
    """
    partner, code, viewer, entitlement = viewer_with_bundle_entitlement()
    assert entitlement["source_type"] == "PARTNER_BUNDLE"
    assert entitlement["partner_id"] == partner["id"]
    assert entitlement["tier_granted"] == partner["bundled_tier"]
    assert entitlement["active"] is True
    assert viewer["subscription_tier"] == partner["bundled_tier"]
    assert viewer["subscription_status"] == "ACTIVE"
    assert viewer["acquisition_source"] == "PARTNER_BUNDLE"
