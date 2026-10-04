"""Escalation cases: severe-alert cascade, resolution gating, legal reporting."""
import pytest

from test_helpers import (
    ApiErrorId,
    acknowledge_alert,
    make_parent_headers,
    make_school_admin_headers,
    set_clock,
    setup_active_district_link,
    setup_monitoring_pipeline,
    setup_severe_alert_with_case,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_severe_alert_escalation_district_cascade(api):
    """PRD §3.8: "A `SEVERE` alert always opens an escalation case in `OPEN`
    status, linked through the case's `alert_id` and the child's
    `child_profile_id`, with the alert's `escalation_case_id` pointing back (the
    field remains null for non-severe alerts)."
    PRD §3.8: "If an `ACTIVE` `DistrictLink` exists for the child whose
    district's `jurisdiction` is `MANDATED_REPORTING`, the case's
    `legal_report_due_at` is set to exactly 24 hours after the case's
    `created_at`, that link's `pending_legal_report` flips to true, and the
    case's `district_link_id` references the obligating link — when several
    links qualify, the one with the earliest `consented_at` is chosen."
    PRD §2.8: "The `District.open_obligation_count` equals the number of the
    district's links whose `pending_legal_report` is true, and filing a legal
    report decreases it by one."

    Design: Difficulty/transitive_cascade/severe_alert_escalation_district_cascade
    """
    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    district, link = setup_active_district_link(child["id"], parent["id"])

    from test_helpers import ingest_content

    item = ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "PREDATORY_CONTACT", "weight": 90}],
        raw_text="predatory contact item",
    )
    assert item["severity"] == "SEVERE"

    headers = make_parent_headers(parent["id"])
    alert = validate_success(api.get_alert(item["alert_id"], headers))
    case = validate_success(api.get_escalation_case(alert["escalation_case_id"], headers))
    assert case["case_status"] == "OPEN"
    # PRD §3.8: exactly 24 hours after the case's created_at (second-exact).
    from test_helpers.assertions import is_iso8601_timestamp
    from datetime import datetime, timedelta, timezone

    def _parse(ts):
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)

    assert is_iso8601_timestamp(case["legal_report_due_at"])
    assert _parse(case["legal_report_due_at"]) == _parse(case["created_at"]) + timedelta(hours=24)
    assert case["crisis_resource_codes"] == ["NCMEC_CYBERTIPLINE"]
    assert case["district_link_id"] == link["id"]

    links, _meta = validate_paginated(
        api.list_district_links_of_child(child["id"], headers)
    )
    by_id = {l["id"]: l for l in links}
    assert by_id[link["id"]]["pending_legal_report"] is True

    sa_headers = make_school_admin_headers(district["id"])
    dist_now = validate_success(api.get_district(district["id"], sa_headers))
    assert dist_now["open_obligation_count"] == 1


def test_case_no_mandated_link_has_no_deadline(api):
    """PRD §3.8: "If an `ACTIVE` `DistrictLink` exists for the child whose
    district's `jurisdiction` is `MANDATED_REPORTING`, the case's
    `legal_report_due_at` is set to exactly 24 hours after the case's
    `created_at`, that link's `pending_legal_report` flips to true, and the
    case's `district_link_id` references the obligating link — when several
    links qualify, the one with the earliest `consented_at` is chosen. Without
    such a link, `legal_report_due_at` remains null."

    Design: Difficulty/transitive_cascade/severe_alert_escalation_district_cascade
    """
    fam, parent, child, dev, conn, item, case = setup_severe_alert_with_case(
        category="SELF_HARM", weight=90
    )
    headers = make_parent_headers(parent["id"])
    full_case = validate_success(api.get_escalation_case(case["id"], headers))
    assert full_case["legal_report_due_at"] is None
    assert full_case["district_link_id"] is None
    assert full_case["crisis_resource_codes"] == ["CRISIS_TEXT_LINE", "988_LIFELINE"]


def test_severe_alert_resolve_requires_case_closed(api):
    """PRD §3.9: "From `ACKNOWLEDGED` or from `REOPENED`, resolving moves the
    alert to `RESOLVED` and recomputes the child's `open_alert_count` down by
    one — with one guard: resolving a `SEVERE` alert requires its linked
    escalation case to be `CLOSED` first, and is otherwise rejected with
    `ERR_ESCALATION_OPEN`."
    PRD §3.8: "From `GUIDANCE_ISSUED`, the parent may either move the case to
    `RESOURCE_REFERRED` or escalate it to `CRISIS_ESCALATED`. From
    `RESOURCE_REFERRED`, the parent closes the case directly into `CLOSED`,
    which recomputes the family's `open_escalation_count`."

    Design: Difficulty/cross_entity_state_dependency/severe_alert_resolve_requires_case_closed
    """
    fam, parent, child, dev, conn, item, case = setup_severe_alert_with_case()
    headers = make_parent_headers(parent["id"])
    alert_id = item["alert_id"]

    acknowledge_alert(alert_id, parent["id"])
    case_now = validate_success(api.get_escalation_case(case["id"], headers))
    assert case_now["case_status"] == "GUIDANCE_ISSUED"

    # Resolve blocked while the case is not CLOSED.
    resp = api.set_alert_state(alert_id, {"to_status": "RESOLVED"}, headers)
    validate_error(resp, ApiErrorId.ERR_ESCALATION_OPEN)

    # Advance the case to CLOSED, then resolve succeeds.
    validate_success(
        api.set_escalation_case_state(
            case["id"], {"to_status": "RESOURCE_REFERRED"}, headers
        )
    )
    validate_success(
        api.set_escalation_case_state(case["id"], {"to_status": "CLOSED"}, headers)
    )
    alert = validate_success(
        api.set_alert_state(alert_id, {"to_status": "RESOLVED"}, headers)
    )
    assert alert["alert_status"] == "RESOLVED"
    child_now = validate_success(api.get_child(child["id"], headers))
    assert child_now["open_alert_count"] == 0


def test_acknowledge_drives_case_to_guidance_issued(api):
    """PRD §3.8: "When the parent acknowledges the linked alert, an `OPEN` case
    automatically advances to `GUIDANCE_ISSUED`."

    Design: Difficulty/cross_entity_state_dependency/severe_alert_resolve_requires_case_closed
    """
    fam, parent, child, dev, conn, item, case = setup_severe_alert_with_case()
    headers = make_parent_headers(parent["id"])

    acknowledge_alert(item["alert_id"], parent["id"])
    case_now = validate_success(api.get_escalation_case(case["id"], headers))
    assert case_now["case_status"] == "GUIDANCE_ISSUED"


def test_escalation_invalid_step_open_to_closed_returns_409(api):
    """PRD §3.8: "Any requested transition that does not correspond to an edge
    from the case's current state is rejected with
    `ERR_INVALID_ESCALATION_STEP` — this includes a role attempting a step it is
    not permitted to perform."

    Design: Corner/state_machines/escalation_invalid_step_open_to_closed_returns_409
    """
    fam, parent, child, dev, conn, item, case = setup_severe_alert_with_case(
        category="SELF_HARM", weight=90
    )
    headers = make_parent_headers(parent["id"])
    assert case["case_status"] == "OPEN"

    # OPEN -> CLOSED is not a declared edge (OPEN advances only via ack).
    resp = api.set_escalation_case_state(
        case["id"], {"to_status": "CLOSED"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ESCALATION_STEP)

    case_now = validate_success(api.get_escalation_case(case["id"], headers))
    assert case_now["case_status"] == "OPEN"


def test_legal_report_without_mandated_link_returns_409(api):
    """PRD §3.8: "Filing the report — the move from `CRISIS_ESCALATED` to
    `LEGAL_REPORTED` — is permitted only to `SchoolAdmin` and `PlatformAdmin`,
    and it requires that an `ACTIVE` `MANDATED_REPORTING` district link for the
    child currently has `pending_legal_report` true; otherwise the attempt is
    rejected with `ERR_LEGAL_REPORT_NOT_REQUIRED`."

    Design: Corner/validations/legal_report_without_mandated_link_returns_409
    """
    fam, parent, child, dev, conn, item, case = setup_severe_alert_with_case(
        category="SELF_HARM", weight=90
    )
    headers = make_parent_headers(parent["id"])

    acknowledge_alert(item["alert_id"], parent["id"])
    validate_success(
        api.set_escalation_case_state(
            case["id"], {"to_status": "CRISIS_ESCALATED"}, headers
        )
    )

    from test_helpers import TEST_USERS

    resp = api.set_escalation_case_state(
        case["id"], {"to_status": "LEGAL_REPORTED"}, TEST_USERS["platform_admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_LEGAL_REPORT_NOT_REQUIRED)

    case_now = validate_success(api.get_escalation_case(case["id"], headers))
    assert case_now["case_status"] == "CRISIS_ESCALATED"


def test_link_withdraw_blocked_while_report_pending(api):
    """PRD §3.13: "Withdrawal moves a link from either `PENDING_CONSENT` or
    `ACTIVE` to `WITHDRAWN`, which is terminal; withdrawing an `ACTIVE` link is
    blocked while the link's `pending_legal_report` is true — a district with
    an outstanding mandated report cannot be quietly detached — and is rejected
    with `ERR_LINK_WITHDRAW_BLOCKED`."

    Design: Corner/validations/link_withdraw_blocked_while_report_pending
    """
    from test_helpers import ingest_content

    fam, parent, child, dev, conn = setup_monitoring_pipeline(birth_year=2012)
    district, link = setup_active_district_link(child["id"], parent["id"])

    ingest_content(
        conn["id"], dev["id"],
        signals=[{"category": "PREDATORY_CONTACT", "weight": 90}],
        raw_text="pending report item",
    )

    headers = make_parent_headers(parent["id"])
    resp = api.set_district_link_state(
        link["id"], {"to_status": "WITHDRAWN"}, headers
    )
    validate_error(resp, ApiErrorId.ERR_LINK_WITHDRAW_BLOCKED)

    links, _meta = validate_paginated(
        api.list_district_links_of_child(child["id"], headers)
    )
    by_id = {l["id"]: l for l in links}
    assert by_id[link["id"]]["link_status"] == "ACTIVE"


def test_error_district_suspended_blocks_consent(api):
    """PRD §3.13: "The parent's link state operation moves a link from
    `PENDING_CONSENT` to `ACTIVE`, which requires the district to be `ACTIVE`
    (otherwise `ERR_DISTRICT_SUSPENDED`) and the child to be `ACTIVE`
    (otherwise `ERR_CHILD_ARCHIVED`), and stamps the link's `consented_at` with
    the current clock time."

    Design: Corner/errors/error_district_suspended_blocks_consent
    """
    from test_helpers import (
        create_district,
        create_district_link,
        create_family,
        create_child,
    )

    fam, parent = create_family()
    child = create_child(fam["id"], parent["id"])
    district = create_district(
        district_name="District DS", contact_email="admin@ds.edu",
        jurisdiction="DISCRETIONARY",
    )
    link = create_district_link(district["id"], child["id"])
    assert link["link_status"] == "PENDING_CONSENT"

    headers = make_parent_headers(parent["id"])
    resp = api.set_district_link_state(link["id"], {"to_status": "ACTIVE"}, headers)
    active_link = validate_success(resp)
    assert active_link["link_status"] == "ACTIVE"
    assert active_link["consented_at"] is not None
