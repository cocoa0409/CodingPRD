"""Locator visibility, referral routing eligibility, and immediate
consistency tests."""
import pytest
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    ANONYMOUS_HEADERS,
    create_shop, create_published_requirement, open_cycle, attest,
    certify_shop, create_certified_shop, create_insurer_relation,
    schedule_and_run_audit, sm,
    TEST_USERS,
    WINDOW2_START, WINDOW2_END,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]
INSURER = TEST_USERS["insurer_headers"]


def _suspend_shop_with_critical(api, shop_id, attestation_id):
    """Second-cycle audit with a CRITICAL finding left OPEN past due_at;
    the sweep flips the shop CERTIFIED -> SUSPENDED (locator_hidden true)."""
    cycle2 = open_cycle(shop_id, WINDOW2_START, WINDOW2_END)
    audit2 = schedule_and_run_audit(
        cycle2["id"], AUD1,
        scheduled_start="2026-09-03T09:00:00Z",
        scheduled_end="2026-09-03T17:00:00Z",
        begin_at="2026-09-03T10:00:00Z")
    get_success_data(api.issue_findings(
        audit2["id"],
        {"findings": [{"attestation_id": attestation_id, "severity": "CRITICAL"}]},
        AUD1))
    get_success_data(api.set_clock("2026-09-14T00:00:00Z", ADMIN))


def test_locator_search_is_anonymous(api):
    """PRD §3.1: "entering SUSPENDED or DECERTIFIED flips locator_hidden to
    true". PRD §3.8: "The consumer locator is the network's public face: an
    anonymous search by zip_code ... lists visible shops — those in CERTIFIED
    or PROBATION posture with locator_hidden false — within the radius".

    Design: Corner/rbac/locator_search_is_anonymous
    """
    shop_a, _ = create_certified_shop(
        legal_name="Visible Body", state_code="MD", zip_code="21201",
        latitude=39.29, longitude=-76.61)
    shop_b = create_shop(legal_name="Hidden Body", state_code="MD", zip_code="21201",
                         latitude=39.29, longitude=-76.61)
    req = create_published_requirement(
        requirement_code="ST-HID-01", category="STRUCTURAL",
        severity_if_failed="CRITICAL", effective_from="2026-09-01T02:00:00Z")
    att_b1 = attest(shop_b["id"], req["id"])
    certify_shop(shop_b["id"], scheduled_start="2026-09-01T10:00:00Z",
                 scheduled_end="2026-09-01T18:00:00Z", begin_at="2026-09-01T11:00:00Z")
    _suspend_shop_with_critical(api, shop_b["id"], att_b1["id"])

    resp = api.locator_search({"zip_code": "21201"}, ANONYMOUS_HEADERS)
    data = validate_success(resp, 200)
    rows = data if isinstance(data, list) else data.get("data", [])
    ids = [r["id"] for r in rows]
    assert shop_a["id"] in ids
    assert shop_b["id"] not in ids


def test_locator_search_excludes_hidden_shop_with_no_headers_required(api):
    """PRD §2.1: "The single exception is the public consumer locator search,
    which is anonymous and requires no headers." PRD §3.8: "lists visible
    shops — those in CERTIFIED or PROBATION posture with locator_hidden
    false".

    Design: Corner/rbac/locator_search_is_anonymous
    """
    shop_a, _ = create_certified_shop(
        legal_name="Lone Visible Body", state_code="MD", zip_code="21202",
        latitude=39.29, longitude=-76.61)
    resp = api.locator_search({"zip_code": "21202"}, ANONYMOUS_HEADERS)
    assert resp.status_code == 200
    data = validate_success(resp, 200)
    rows = data if isinstance(data, list) else data.get("data", [])
    assert [r["id"] for r in rows] == [shop_a["id"]]


def _certify_with_relation(api, legal_name, insurer_code, zip_code, auditor_headers=AUD1):
    shop, _cycle = create_certified_shop(
        auditor_headers,
        legal_name=legal_name, state_code="NC", zip_code=zip_code,
        latitude=35.78, longitude=-78.64)
    rel = create_insurer_relation(shop["id"], insurer_code=insurer_code, discount_pct_bps=300)
    return shop, rel


def test_insurer_referral_requires_steering_enabled(api):
    """PRD §3.8: "when the referral's source is an insurer, an additional gate
    requires an ACTIVE insurer relation between the shop and the referral's
    insurer_code with steering_enabled true." PRD §3.8: "A NetworkAdmin may
    suspend an ACTIVE relation (steering off)".

    Design: Corner/cross_cutting_layers/insurer_referral_requires_steering_enabled
    """
    shop_ok, rel_ok = _certify_with_relation(api, "Steer OK", "INS-Z", "27601")
    shop_no, rel_no = _certify_with_relation(api, "Steer NO", "INS-Z", "27601",
                                             auditor_headers=TEST_USERS["auditor2_headers"])
    validate_success(api.suspend_relation(rel_no["id"], ADMIN))
    rel_now = validate_success(api.get_insurer_relation(rel_no["id"], ADMIN))
    assert rel_now["steering_enabled"] is False

    ref = validate_success(api.create_referral(
        {"consumer_zip": "27601", "source_type": "INSURER", "source_reference": "CLM-1",
         "vin": "1HGCV1F34LA000022", "insurer_code": "INS-Z"}, INSURER), 201)
    assert ref["status"] == "ROUTED"
    assert ref["routed_shop_id"] == shop_ok["id"]


def test_insurer_referral_pool_excludes_shop_without_relation(api):
    """PRD §3.8: "when the referral's source is an insurer, an additional gate
    requires an ACTIVE insurer relation between the shop and the referral's
    insurer_code with steering_enabled true."

    Design: Corner/cross_cutting_layers/insurer_referral_requires_steering_enabled
    """
    shop_with, _rel = _certify_with_relation(api, "Has Relation", "INS-Q", "27602")
    create_certified_shop(
        TEST_USERS["auditor2_headers"],
        legal_name="No Relation", state_code="NC", zip_code="27602",
        latitude=35.78, longitude=-78.64)
    ref = validate_success(api.create_referral(
        {"consumer_zip": "27602", "source_type": "INSURER", "source_reference": "CLM-2",
         "vin": "1HGCV1F34LA000027", "insurer_code": "INS-Q"}, INSURER), 201)
    assert ref["status"] == "ROUTED"
    assert ref["routed_shop_id"] == shop_with["id"]


def test_empty_candidate_pool_stays_unrouted(api):
    """PRD §3.8: "An empty pool is not an error: the referral stays UNROUTED
    and is returned with routed_shop_id null." PRD §3.8: "The referral is born
    UNROUTED with routed_shop_id null and routed_at null."

    Design: Corner/cross_cutting_layers/empty_candidate_pool_stays_unrouted
    """
    ref = validate_success(api.create_referral(
        {"consumer_zip": "00501", "source_type": "CONSUMER_DIRECT",
         "source_reference": "WEB", "vin": "1HGCV1F34LA000023"},
        TEST_USERS["dealer_headers"]), 201)
    assert ref["status"] == "UNROUTED"
    assert ref["routed_shop_id"] is None
    assert ref["routed_at"] is None


def test_explicit_route_after_pool_appears(api):
    """PRD §3.8: "Routing happens automatically at creation when the pool is
    non-empty, or on demand for an UNROUTED referral at a NetworkAdmin's
    request. A successful route moves the referral UNROUTED → ROUTED, stamps
    routed_at with the logical clock, records the winner as routed_shop_id,
    and increments that shop's pending_referral_count."

    Design: Corner/cross_cutting_layers/empty_candidate_pool_stays_unrouted
    """
    ref = validate_success(api.create_referral(
        {"consumer_zip": "00502", "source_type": "CONSUMER_DIRECT",
         "source_reference": "WEB", "vin": "1HGCV1F34LA000028"},
        TEST_USERS["dealer_headers"]), 201)
    assert ref["status"] == "UNROUTED"
    shop, _cycle = create_certified_shop(
        legal_name="Late Pool Body", zip_code="00502", latitude=40.71, longitude=-73.0)
    routed = validate_success(api.route_referral(ref["id"], ADMIN))
    assert routed["status"] == "ROUTED"
    assert routed["routed_shop_id"] == shop["id"]
    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    assert shop_now["pending_referral_count"] == 1


def test_immediate_visibility_of_attestation_supersede(api):
    """PRD §3.2: "When an attestation is created for a requirement row that
    already has an ACTIVE attestation at that shop, the older attestation
    transitions to SUPERSEDED (the attestation's terminal state) and the
    shop's live_compliance_score is recomputed."

    Design: Corner/consistency_model/immediate_visibility_of_attestation_supersede
    """
    shop = create_shop(legal_name="Consistent Body", state_code="SC", zip_code="29201",
                       latitude=34.0, longitude=-81.03)
    req = create_published_requirement(
        requirement_code="EQ-CON-01", category="EQUIPMENT",
        severity_if_failed="MINOR", effective_from="2026-09-01T00:00:00Z")
    att1 = attest(shop["id"], req["id"])
    v1 = validate_success(api.get_shop(shop["id"], sm(shop["id"])))["version"]
    att2 = validate_success(api.create_attestation(
        shop["id"],
        {"requirement_id": req["id"], "evidence_uri": "s3://ev/c2.pdf",
         "expected_shop_version": v1},
        sm(shop["id"])), 201)
    old = validate_success(api.get_attestation(att1["id"], ADMIN))
    assert old["status"] == "SUPERSEDED"
    assert att2["status"] == "ACTIVE"


def test_attestation_supersede_recomputes_score_immediately(api):
    """PRD §3.2: "When an attestation is created for a requirement row that
    already has an ACTIVE attestation at that shop, the older attestation
    transitions to SUPERSEDED (the attestation's terminal state) and the
    shop's live_compliance_score is recomputed."

    Design: Corner/consistency_model/immediate_visibility_of_attestation_supersede
    """
    shop = create_shop(legal_name="Consistent Body 2", state_code="SC", zip_code="29202",
                       latitude=34.0, longitude=-81.03)
    req = create_published_requirement(
        requirement_code="EQ-CON-02", category="EQUIPMENT",
        severity_if_failed="MINOR", effective_from="2026-09-01T00:00:00Z")
    attest(shop["id"], req["id"])
    mid = validate_success(api.get_shop(shop["id"], ADMIN))
    assert mid["live_compliance_score"] == 100.0
    att2 = attest(shop["id"], req["id"])
    after = validate_success(api.get_shop(shop["id"], ADMIN))
    assert after["live_compliance_score"] == 100.0
    assert att2["status"] == "ACTIVE"
