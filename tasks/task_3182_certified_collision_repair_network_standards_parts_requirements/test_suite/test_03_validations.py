"""Validation-rule tests: audit window bounds, corrective-action deadline,
and part documentation rules."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_shop, create_published_requirement, open_cycle, attest,
    create_certified_shop, create_technician, create_order,
    schedule_and_run_audit, add_part, sm, auditor_as,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]


def _shop_with_scheduled_audit(api, start="2026-09-03T10:00:00Z", end="2026-09-03T14:00:00Z"):
    shop = create_shop(legal_name="Window Body", state_code="NH", zip_code="03101",
                       latitude=43.21, longitude=-71.54)
    cycle = open_cycle(shop["id"])
    resp = api.schedule_audit(cycle["id"], {"scheduled_start": start, "scheduled_end": end}, AUD1)
    return shop, get_success_data(resp)


def test_audit_begin_outside_window_rejected(api, admin_headers):
    """PRD §3.3: "beginning is legal only while the logical clock sits within
    the scheduled half-open window ... A begin outside the window is rejected
    with ERR_AUDIT_WINDOW_MISSED (HTTP 422)."

    Design: Corner/validations/audit_begin_outside_window_rejected
    """
    _shop, audit = _shop_with_scheduled_audit(api)
    get_success_data(api.set_clock("2026-09-03T09:59:59Z", ADMIN))
    bad = api.begin_audit(audit["id"], AUD1)
    validate_error(bad, ApiErrorId.ERR_AUDIT_WINDOW_MISSED)
    get_success_data(api.set_clock("2026-09-03T10:00:00Z", ADMIN))
    begun = validate_success(api.begin_audit(audit["id"], AUD1))
    assert begun["status"] == "IN_PROGRESS"


def test_audit_begin_at_scheduled_end_rejected(api, admin_headers):
    """PRD §3.3: "a half-open on-site window — inclusive at the start,
    exclusive at the end ... A begin outside the window is rejected with
    ERR_AUDIT_WINDOW_MISSED (HTTP 422)."

    Design: Corner/validations/audit_begin_outside_window_rejected
    """
    _shop, audit = _shop_with_scheduled_audit(api)
    get_success_data(api.set_clock("2026-09-03T14:00:00Z", ADMIN))
    bad = api.begin_audit(audit["id"], AUD1)
    validate_error(bad, ApiErrorId.ERR_AUDIT_WINDOW_MISSED)
    after = validate_success(api.get_audit(audit["id"], AUD1))
    assert after["status"] == "SCHEDULED"


def _setup_critical_corrective_action(api, requirement_code="ST-OD-01"):
    """Shop + CRITICAL attestation + audit + CRITICAL finding issued at
    2026-09-02T10:00; due_at = +10 days. Returns (shop, audit, ca)."""
    shop = create_shop(legal_name="Overdue Body", state_code="RI", zip_code="02901",
                       latitude=41.82, longitude=-71.41)
    req = create_published_requirement(
        requirement_code=requirement_code, category="STRUCTURAL",
        severity_if_failed="CRITICAL", effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    cycle = open_cycle(shop["id"])
    audit = schedule_and_run_audit(cycle["id"], AUD1)
    get_success_data(api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "CRITICAL"}]},
        AUD1))
    cas = get_success_data(api.list_audit_corrective_actions(audit["id"], AUD1))
    return shop, audit, cas[0]


def test_corrective_submit_after_due_rejected(api):
    """PRD §3.3: "submission is only legal at or before due_at (later attempts
    are rejected with ERR_CORRECTIVE_OVERDUE, HTTP 422)" and "a CRITICAL
    finding 10 days".

    Design: Corner/validations/corrective_submit_after_due_rejected
    """
    shop, _audit, ca = _setup_critical_corrective_action(api)
    get_success_data(api.set_clock("2026-09-12T10:00:01Z", ADMIN))
    resp = api.submit_corrective_action(ca["id"], {"evidence_uri": "s3://ev/late.pdf"}, sm(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_CORRECTIVE_OVERDUE)
    after = validate_success(api.get_corrective_action(ca["id"], AUD1))
    assert after["status"] == "OPEN"


def test_corrective_submit_at_due_succeeds(api):
    """PRD §3.3: "submission is only legal at or before due_at (later attempts
    are rejected with ERR_CORRECTIVE_OVERDUE, HTTP 422), moves the action to
    SUBMITTED".

    Design: Corner/validations/corrective_submit_after_due_rejected
    """
    shop, _audit, ca = _setup_critical_corrective_action(api, requirement_code="ST-OD-02")
    get_success_data(api.set_clock("2026-09-12T10:00:00Z", ADMIN))
    submitted = validate_success(
        api.submit_corrective_action(ca["id"], {"evidence_uri": "s3://ev/ontime.pdf"}, sm(shop["id"])))
    assert submitted["status"] == "SUBMITTED"


def _certified_shop_with_estimate_order(api, legal_name="Doc Body", state="TN", zip_code="37201"):
    shop, _cycle = create_certified_shop(
        legal_name=legal_name, state_code=state, zip_code=zip_code,
        latitude=36.16, longitude=-86.78)
    tech = create_technician(shop["id"], full_name="Al Ternative")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000025")
    return shop, tech, order


def test_alt_part_documented_passes(api):
    """PRD §3.6: "every line whose class is AFTERMARKET, RECYCLED, or
    REMANUFACTURED must carry a non-empty alternative_justification
    documenting the reason and the consumer's consent reference; a missing
    justification is rejected with ERR_ALT_PART_UNDOCUMENTED (HTTP 422)."

    Design: Corner/validations/alt_part_documented_passes
    """
    shop, _tech, order = _certified_shop_with_estimate_order(api)
    bad = api.create_part_line(
        order["id"],
        {"part_number": "MIR-4", "part_class": "AFTERMARKET",
         "unit_cost_cents": 8000, "quantity": 1},
        sm(shop["id"]),
    )
    validate_error(bad, ApiErrorId.ERR_ALT_PART_UNDOCUMENTED)
    good = api.create_part_line(
        order["id"],
        {"part_number": "MIR-4", "part_class": "AFTERMARKET",
         "unit_cost_cents": 8000, "quantity": 1,
         "alternative_justification": "consumer consent ref CC-42; OE on backorder 6 weeks"},
        sm(shop["id"]),
    )
    validate_success(good, 201)
    order_now = validate_success(api.get_repair_order(order["id"], sm(shop["id"])))
    assert order_now["oe_parts_ratio_by_count"] == 0.0


def test_alt_part_documented_rejected_for_each_non_oe_class(api):
    """PRD §3.6: "every line whose class is AFTERMARKET, RECYCLED, or
    REMANUFACTURED must carry a non-empty alternative_justification ...; a
    missing justification is rejected with ERR_ALT_PART_UNDOCUMENTED
    (HTTP 422)."

    Design: Corner/validations/alt_part_documented_passes
    """
    shop, _tech, order = _certified_shop_with_estimate_order(
        api, legal_name="Doc Body 2", zip_code="37202")
    for cls in ("RECYCLED", "REMANUFACTURED"):
        resp = api.create_part_line(
            order["id"],
            {"part_number": f"X-{cls}", "part_class": cls,
             "unit_cost_cents": 100, "quantity": 1},
            sm(shop["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALT_PART_UNDOCUMENTED)
