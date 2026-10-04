"""Composite setup helpers: multi-step scenarios shared across tests.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test). Setup calls use
the lenient get_success_data() validator so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_access_grant_payload,
    create_bypass_event_payload,
    create_child_payload,
    create_connection_payload,
    create_content_item_payload,
    create_district_link_payload,
    create_district_payload,
    create_family_payload,
    create_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_device_agent_headers,
    make_parent_headers,
    make_school_admin_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def create_family(**overrides):
    """Create a family and its primary parent.

    Returns (family, parent) where parent is the auto-created primary
    ParentMember record.
    """
    fam = get_success_data(api_client.create_family(create_family_payload(**overrides), ADMIN))
    parents = get_success_data(api_client.list_parents(fam["id"], ADMIN))
    assert isinstance(parents, list) and len(parents) == 1, (
        "Setup failed: expected exactly one auto-created primary parent"
    )
    return fam, parents[0]


def create_child(family_id, parent_id, **overrides):
    headers = make_parent_headers(parent_id)
    payload = create_child_payload(family_account_id=family_id, **overrides)
    return get_success_data(api_client.create_child(payload, headers))


def pair_device(child_id, parent_id, **overrides):
    headers = make_parent_headers(parent_id)
    from .factories import create_device_payload

    payload = create_device_payload(**overrides)
    return get_success_data(api_client.pair_device(child_id, payload, headers))


def create_connection(child_id, parent_id, **overrides):
    headers = make_parent_headers(parent_id)
    payload = create_connection_payload(**overrides)
    return get_success_data(api_client.create_connection(child_id, payload, headers))


def set_connection_state(connection_id, parent_id, to_status):
    headers = make_parent_headers(parent_id)
    return get_success_data(
        api_client.set_connection_state(connection_id, {"to_status": to_status}, headers)
    )


def create_active_connection(child_id, parent_id, **overrides):
    """Create a connection and consent it to ACTIVE. Returns the connection."""
    conn = create_connection(child_id, parent_id, **overrides)
    return set_connection_state(conn["id"], parent_id, "ACTIVE")


def ingest_content(connection_id, device_id, **overrides):
    """Ingest a content item as the device's agent. Returns the ContentItem."""
    headers = make_device_agent_headers(device_id)
    payload = create_content_item_payload(service_connection_id=connection_id, **overrides)
    return get_success_data(api_client.ingest_content_item(payload, headers))


def setup_family_with_child(**child_overrides):
    """Family + primary parent + one child. Returns (family, parent, child)."""
    fam, parent = create_family(**child_overrides.pop("family_overrides", {}))
    child = create_child(fam["id"], parent["id"], **child_overrides)
    return fam, parent, child


def setup_monitoring_pipeline(
    birth_year=2012,
    monitoring_sensitivity="STANDARD",
    service_type="MESSAGING",
    family_overrides=None,
):
    """Family + child + paired device + ACTIVE connection.

    Returns (family, parent, child, device, connection).
    """
    fam, parent, child = setup_family_with_child(
        birth_year=birth_year,
        monitoring_sensitivity=monitoring_sensitivity,
        family_overrides=family_overrides or {},
    )
    device = pair_device(child["id"], parent["id"])
    conn = create_active_connection(child["id"], parent["id"], service_type=service_type)
    return fam, parent, child, device, conn


def setup_alert(
    birth_year=2012,
    monitoring_sensitivity="STANDARD",
    signals=None,
    thread_depth=1,
    family_overrides=None,
    occurred_at=None,
    **ingest_overrides,
):
    """Full monitoring pipeline plus one ingested content item.

    Returns (family, parent, child, device, connection, content_item).
    The content item may or may not have produced an alert depending on the
    signals supplied.
    """
    fam, parent, child, device, conn = setup_monitoring_pipeline(
        birth_year=birth_year,
        monitoring_sensitivity=monitoring_sensitivity,
        family_overrides=family_overrides,
    )
    kwargs = {"signals": signals or [{"category": "BULLYING", "weight": 40}],
              "thread_depth": thread_depth}
    if occurred_at is not None:
        kwargs["occurred_at"] = occurred_at
    item = ingest_content(conn["id"], device["id"], **kwargs, **ingest_overrides)
    return fam, parent, child, device, conn, item


def setup_severe_alert_with_case(
    category="PREDATORY_CONTACT",
    weight=90,
    birth_year=2012,
    monitoring_sensitivity="STANDARD",
    family_overrides=None,
):
    """Monitoring pipeline + one SEVERE content item + its EscalationCase.

    Returns (family, parent, child, device, connection, content_item, case).
    """
    fam, parent, child, device, conn, item = setup_alert(
        birth_year=birth_year,
        monitoring_sensitivity=monitoring_sensitivity,
        signals=[{"category": category, "weight": weight}],
        family_overrides=family_overrides,
    )
    assert item["alert_created"] is True and item["severity"] == "SEVERE", (
        "Setup failed: expected a SEVERE content item to create an alert"
    )
    headers = make_parent_headers(parent["id"])
    cases, _meta = _list_cases(headers, params={"alert_id": item["alert_id"]})
    assert len(cases) == 1, "Setup failed: expected exactly one escalation case"
    return fam, parent, child, device, conn, item, cases[0]


def _list_cases(headers, params=None):
    from prd_bench_local_runner.testing import validate_paginated

    resp = api_client.list_escalation_cases(headers, params=params)
    return validate_paginated(resp)


def create_district(**overrides):
    return get_success_data(api_client.create_district(create_district_payload(**overrides), ADMIN))


def create_district_link(district_id, child_id):
    headers = make_school_admin_headers(district_id)
    payload = create_district_link_payload(child_profile_id=child_id)
    return get_success_data(api_client.create_district_link(district_id, payload, headers))


def consent_district_link(link_id, parent_id):
    headers = make_parent_headers(parent_id)
    return get_success_data(
        api_client.set_district_link_state(link_id, {"to_status": "ACTIVE"}, headers)
    )


def setup_active_district_link(child_id, parent_id, jurisdiction="MANDATED_REPORTING"):
    """Create a district, request a link, and consent it ACTIVE.

    Returns (district, link).
    """
    district = create_district(jurisdiction=jurisdiction)
    link = create_district_link(district["id"], child_id)
    link = consent_district_link(link["id"], parent_id)
    return district, link


def report_bypass_events(device_id, count, kinds=None):
    """Report `count` bypass events on a device as its own agent.

    Events are spaced 5 minutes apart, ending exactly at the default clock
    (2026-09-01T00:00:00Z) so none lies in the future relative to it. Returns
    the list of created BypassEvent records.
    """
    headers = make_device_agent_headers(device_id)
    events = []
    for i in range(count):
        kind = (kinds or ["VPN"] * count)[i]
        minutes = (count - 1 - i) * 5
        if minutes == 0:
            detected_at = "2026-09-01T00:00:00Z"
        else:
            detected_at = f"2026-08-31T23:{60 - minutes:02d}:00Z"
        payload = create_bypass_event_payload(
            bypass_kind=kind,
            detected_at=detected_at,
        )
        events.append(
            get_success_data(api_client.report_bypass_event(device_id, payload, headers))
        )
    return events


def create_grant(device_id, parent_id, start_at, end_at, reason=None):
    headers = make_parent_headers(parent_id)
    overrides = {"start_at": start_at, "end_at": end_at}
    if reason is not None:
        overrides["reason"] = reason
    payload = create_access_grant_payload(**overrides)
    return get_success_data(api_client.create_access_grant(device_id, payload, headers))


def acknowledge_alert(alert_id, parent_id):
    headers = make_parent_headers(parent_id)
    return get_success_data(
        api_client.set_alert_state(alert_id, {"to_status": "ACKNOWLEDGED"}, headers)
    )


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
