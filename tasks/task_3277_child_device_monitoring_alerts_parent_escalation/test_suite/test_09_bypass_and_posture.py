"""Bypass events, strike windows, posture transitions, lockdown cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_grant,
    make_device_agent_headers,
    make_parent_headers,
    report_bypass_events,
    set_clock,
    setup_monitoring_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_bypass_strike_threshold_at_exactly_three(api):
    """PRD §3.11: "Each device's `bypass_strike_count` counts its bypass events
    whose `detected_at` falls within the trailing fourteen days, inclusive at
    both edges — an event detected exactly fourteen days ago still counts."
    PRD §3.11: "The count drives the device's posture: at least one strike puts
    the device into `BYPASS_WATCH`; at least three strikes put it into
    `LOCKDOWN`; and when clock advancement causes the count to decay back to
    zero, the device auto-heals from either `BYPASS_WATCH` or `LOCKDOWN` back to
    `NORMAL`. Posture is re-evaluated both when a bypass event is created and
    whenever the logical clock advances."

    Design: Difficulty/boundary_precision_check/bypass_strike_threshold_at_exactly_three
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])

    report_bypass_events(dev["id"], 2, kinds=["VPN", "SECONDARY_ACCOUNT"])
    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["bypass_strike_count"] == 2
    assert dev_now["device_posture"] == "BYPASS_WATCH"

    report_bypass_events(dev["id"], 1, kinds=["UNINSTALL_ATTEMPT"])
    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["bypass_strike_count"] == 3
    assert dev_now["device_posture"] == "LOCKDOWN"


def test_bypass_posture_watch_at_one_strike(api):
    """PRD §3.11: "The count drives the device's posture: at least one strike
    puts the device into `BYPASS_WATCH`; at least three strikes put it into
    `LOCKDOWN`; and when clock advancement causes the count to decay back to
    zero, the device auto-heals from either `BYPASS_WATCH` or `LOCKDOWN` back to
    `NORMAL`. Posture is re-evaluated both when a bypass event is created and
    whenever the logical clock advances."

    Design: Difficulty/boundary_precision_check/bypass_strike_threshold_at_exactly_three
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])

    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["device_posture"] == "NORMAL"
    assert dev_now["bypass_strike_count"] == 0

    report_bypass_events(dev["id"], 1, kinds=["VPN"])
    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["bypass_strike_count"] == 1
    assert dev_now["device_posture"] == "BYPASS_WATCH"


def test_bypass_strike_lockdown_grant_cascade(api):
    """PRD §3.11: "Entering `LOCKDOWN` has teeth: every access grant of the
    device whose `grant_status` is `SCHEDULED` or `ACTIVE` is moved to
    `CANCELLED` as part of the posture change. While a device is in `LOCKDOWN`,
    creating a new access grant for it is rejected with
    `ERR_DEVICE_LOCKED_DOWN`."

    Design: Difficulty/transitive_cascade/bypass_strike_lockdown_grant_cascade
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2011)
    headers = make_parent_headers(parent["id"])

    grant = create_grant(
        dev["id"], parent["id"],
        "2026-09-01T05:00:00Z", "2026-09-01T06:00:00Z", reason="homework",
    )
    assert grant["grant_status"] == "SCHEDULED"

    report_bypass_events(dev["id"], 2, kinds=["VPN", "TIMEZONE_SHIFT"])
    report_bypass_events(dev["id"], 1, kinds=["UNINSTALL_ATTEMPT"])

    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["bypass_strike_count"] == 3
    assert dev_now["device_posture"] == "LOCKDOWN"

    grants, _meta = validate_paginated(api.list_access_grants(dev["id"], headers))
    by_id = {g["id"]: g for g in grants}
    assert by_id[grant["id"]]["grant_status"] == "CANCELLED"


def test_lockdown_cancels_active_grant(api):
    """PRD §3.11: "Entering `LOCKDOWN` has teeth: every access grant of the
    device whose `grant_status` is `SCHEDULED` or `ACTIVE` is moved to
    `CANCELLED` as part of the posture change."
    PRD §3.12: "When the logical clock enters the interval — reaching a moment
    on or after `start_at` and on or before `end_at` — the grant becomes
    `ACTIVE`; when the clock passes `end_at`, an `ACTIVE` grant becomes
    `EXPIRED`, and a `SCHEDULED` grant whose window elapsed without the clock
    having entered it likewise becomes `EXPIRED`."

    Design: Difficulty/transitive_cascade/bypass_strike_lockdown_grant_cascade
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2011)
    headers = make_parent_headers(parent["id"])

    grant = create_grant(
        dev["id"], parent["id"],
        "2026-09-01T00:30:00Z", "2026-09-01T23:00:00Z",
    )
    set_clock("2026-09-01T01:00:00Z")
    grants, _meta = validate_paginated(api.list_access_grants(dev["id"], headers))
    assert grants[0]["grant_status"] == "ACTIVE"

    report_bypass_events(dev["id"], 3, kinds=["VPN", "VPN", "VPN"])
    grants, _meta = validate_paginated(api.list_access_grants(dev["id"], headers))
    assert grants[0]["grant_status"] == "CANCELLED"


def test_strike_window_inclusive_14_day_boundary(api):
    """PRD §3.11: "Each device's `bypass_strike_count` counts its bypass events
    whose `detected_at` falls within the trailing fourteen days, inclusive at
    both edges — an event detected exactly fourteen days ago still counts."
    PRD §3.11: "The count drives the device's posture: at least one strike puts
    the device into `BYPASS_WATCH`; at least three strikes put it into
    `LOCKDOWN`; and when clock advancement causes the count to decay back to
    zero, the device auto-heals from either `BYPASS_WATCH` or `LOCKDOWN` back to
    `NORMAL`. Posture is re-evaluated both when a bypass event is created and
    whenever the logical clock advances."

    Design: Corner/calculations/strike_window_inclusive_14_day_boundary
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])
    report_bypass_events(dev["id"], 1, kinds=["VPN"])

    # Exactly 14 days later: still counted (inclusive trailing edge).
    set_clock("2026-09-15T00:00:00Z")
    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["bypass_strike_count"] == 1
    assert dev_now["device_posture"] == "BYPASS_WATCH"

    # 15 days later: decayed to zero, posture auto-heals.
    set_clock("2026-09-16T00:00:00Z")
    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["bypass_strike_count"] == 0
    assert dev_now["device_posture"] == "NORMAL"


def test_future_dated_bypass_event_returns_400(api):
    """PRD §3.11: "The on-device agent reports a bypass event with a
    `bypass_kind` — one of `VPN`, `SECONDARY_ACCOUNT`, `TIMEZONE_SHIFT`, or
    `UNINSTALL_ATTEMPT` — and the `detected_at` timestamp, which must not lie in
    the future relative to the logical clock (`ERR_INVALID_REQUEST`)."

    Design: Corner/validations/future_dated_bypass_event_returns_400
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])

    resp = api.report_bypass_event(
        dev["id"],
        {"bypass_kind": "VPN", "detected_at": "2026-09-02T00:00:00Z"},
        make_device_agent_headers(dev["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["bypass_strike_count"] == 0


def test_error_device_locked_down_blocks_grants(api):
    """PRD §3.11: "Entering `LOCKDOWN` has teeth: every access grant of the
    device whose `grant_status` is `SCHEDULED` or `ACTIVE` is moved to
    `CANCELLED` as part of the posture change. While a device is in `LOCKDOWN`,
    creating a new access grant for it is rejected with
    `ERR_DEVICE_LOCKED_DOWN`."

    Design: Corner/errors/error_device_locked_down_blocks_grants
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    headers = make_parent_headers(parent["id"])
    report_bypass_events(dev["id"], 3, kinds=["VPN", "VPN", "VPN"])

    dev_now = validate_success(api.get_device(dev["id"], headers))
    assert dev_now["device_posture"] == "LOCKDOWN"

    resp = api.create_access_grant(
        dev["id"],
        {"start_at": "2026-09-01T10:00:00Z", "end_at": "2026-09-01T11:00:00Z"},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_LOCKED_DOWN)
