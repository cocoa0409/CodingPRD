"""RBAC, optimistic-concurrency, and warranty-window error tests."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_shop, create_published_requirement, open_cycle, attest,
    create_certified_shop, create_technician, create_order,
    order_warranty_active, schedule_and_run_audit, sm,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]


def _setup_submitted_corrective_action(api):
    shop = create_shop(legal_name="RBAC Body", state_code="NJ", zip_code="07101",
                       latitude=40.74, longitude=-74.17)
    req = create_published_requirement(
        requirement_code="TL-RB-01", category="TOOLING",
        severity_if_failed="MAJOR", effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    cycle = open_cycle(shop["id"])
    audit = schedule_and_run_audit(cycle["id"], AUD1)
    get_success_data(api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "MAJOR"}]},
        AUD1))
    cas = get_success_data(api.list_audit_corrective_actions(audit["id"], AUD1))
    ca = cas[0]
    get_success_data(api.submit_corrective_action(
        ca["id"], {"evidence_uri": "s3://ev/rfix.pdf"}, sm(shop["id"])))
    return shop, ca


def test_shop_manager_cannot_verify_corrective_action(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for
    the endpoint per the authorization column in §4 is rejected with
    ERR_UNAUTHORIZED (HTTP 403)." PRD §4: verify corrective actions is listed
    for NetworkAuditor only.

    Design: Corner/rbac/shop_manager_cannot_verify_corrective_action
    """
    shop, ca = _setup_submitted_corrective_action(api)
    resp = api.verify_corrective_action(ca["id"], {"verdict": "VERIFIED"}, sm(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_dealer_rep_cannot_verify_corrective_action(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted for
    the endpoint per the authorization column in §4 is rejected with
    ERR_UNAUTHORIZED (HTTP 403)." PRD §4: verify corrective actions is listed
    for NetworkAuditor only.

    Design: Corner/rbac/shop_manager_cannot_verify_corrective_action
    """
    _shop, ca = _setup_submitted_corrective_action(api)
    resp = api.verify_corrective_action(
        ca["id"], {"verdict": "VERIFIED"}, TEST_USERS["dealer_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def _certified_shop_with_tech(api, legal_name="OCC Body", zip_code="23219", lat=37.54, lon=-77.44):
    shop, _cycle = create_certified_shop(
        legal_name=legal_name, state_code="VA", zip_code=zip_code, latitude=lat, longitude=lon)
    tech = create_technician(shop["id"], full_name="Oc Currence")
    return shop, tech


def test_occ_stale_shop_version_on_order_create(api):
    """PRD §2.9: "Creating a repair order under a shop requires a non-optional
    expected_shop_version input carrying the shop's version as the client last
    observed it. If the shop's current version has advanced since ... the
    create is rejected with ERR_STALE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_stale_shop_version_on_order_create
    """
    shop, tech = _certified_shop_with_tech(api)
    v1 = validate_success(api.get_shop(shop["id"], sm(shop["id"])))["version"]
    order1 = validate_success(api.create_repair_order(
        shop["id"],
        {
            "expected_shop_version": v1,
            "vin": "1HGCV1F34LA000020",
            "vehicle_model_year": 2015,
            "estimate_total_cents": 10000,
            "assigned_technician_id": tech["id"],
        },
        sm(shop["id"]),
    ), 201)
    stale = api.create_repair_order(
        shop["id"],
        {
            "expected_shop_version": v1,
            "vin": "1HGCV1F34LA000021",
            "vehicle_model_year": 2015,
            "estimate_total_cents": 10000,
            "assigned_technician_id": tech["id"],
        },
        sm(shop["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    assert shop_now["lifetime_repair_count"] == 1


def test_occ_current_shop_version_succeeds(api):
    """PRD §2.9: "Creating a repair order under a shop requires a non-optional
    expected_shop_version input carrying the shop's version as the client last
    observed it."

    Design: Corner/cross_cutting_layers/occ_stale_shop_version_on_order_create
    """
    shop, tech = _certified_shop_with_tech(api, legal_name="OCC Body 2", zip_code="23220")
    v = validate_success(api.get_shop(shop["id"], ADMIN))["version"]
    ok = api.create_repair_order(
        shop["id"],
        {
            "expected_shop_version": v,
            "vin": "1HGCV1F34LA000022",
            "vehicle_model_year": 2015,
            "estimate_total_cents": 10000,
            "assigned_technician_id": tech["id"],
        },
        sm(shop["id"]),
    )
    validate_success(ok, 201)


def test_warranty_expired_after_window_close(api):
    """PRD §3.7: "a filing outside the window or against an order in any other
    status is rejected with ERR_WARRANTY_EXPIRED (HTTP 422)" and "when the
    sweep finds the logical clock past the end of the warranty window with no
    claim of the order in FILED, UNDER_REVIEW, or ESCALATED, the order moves
    WARRANTY_ACTIVE → CLOSED".

    Design: Corner/errors/error_warranty_expired_triggerable
    """
    shop, _cycle = create_certified_shop(
        legal_name="Expired Warranty Body", state_code="DE", zip_code="19901",
        latitude=39.16, longitude=-75.52)
    tech = create_technician(shop["id"], full_name="Ex Pire")
    order = order_warranty_active(
        shop["id"], tech["id"], vin="1HGCV1F34LA000019", estimate_total_cents=10000)
    get_success_data(api.set_clock("2027-09-03T00:00:00Z", ADMIN))
    order_now = validate_success(api.get_repair_order(order["id"], ADMIN))
    assert order_now["status"] == "CLOSED"
    resp = api.create_warranty_claim(
        order["id"],
        {"claimant_contact": "late@example.com", "defect_category": "PAINT_ADHESION",
         "claim_amount_cents": 1000},
        TEST_USERS["admin2_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


def test_warranty_claim_within_window_succeeds(api):
    """PRD §3.7: "A claim may be filed by a ShopManager or NetworkAdmin ...
    only while the order is in WARRANTY_ACTIVE and the filing falls within
    that window; the server stamps filed_at and records filed_by_role ... The
    claim is born FILED."

    Design: Corner/errors/error_warranty_expired_triggerable
    """
    shop, _cycle = create_certified_shop(
        legal_name="Valid Warranty Body", state_code="DE", zip_code="19902",
        latitude=39.16, longitude=-75.52)
    tech = create_technician(shop["id"], full_name="On Time")
    order = order_warranty_active(
        shop["id"], tech["id"], vin="1HGCV1F34LA000030", estimate_total_cents=10000)
    order_now = validate_success(api.get_repair_order(order["id"], ADMIN))
    assert order_now["status"] == "WARRANTY_ACTIVE"
    claim = validate_success(api.create_warranty_claim(
        order["id"],
        {"claimant_contact": "ontime@example.com", "defect_category": "WORKMANSHIP",
         "claim_amount_cents": 1000},
        TEST_USERS["admin2_headers"],
    ), 201)
    assert claim["status"] == "FILED"
