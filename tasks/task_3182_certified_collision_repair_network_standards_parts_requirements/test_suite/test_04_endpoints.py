"""Endpoint side-effect tests: order creation counters, procedure-step
re-perform voiding, and filtered-list reverse lookups."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_shop, create_published_requirement, open_cycle, attest,
    create_certified_shop, create_technician, create_order, record_step,
    add_part, certify_shop, schedule_and_run_audit, sm,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]
DEALER = TEST_USERS["dealer_headers"]


def _certified_shop_with_tech(api, legal_name, zip_code, lat, lon):
    shop, _cycle = create_certified_shop(
        legal_name=legal_name, zip_code=zip_code, latitude=lat, longitude=lon)
    tech = create_technician(shop["id"])
    return shop, tech


def test_repair_order_side_effects_on_create(api):
    """PRD §3.5: "Creating the order increments the shop's
    lifetime_repair_count — the counter grows at create time and is never
    touched again — and bumps the shop's version. The order begins in
    ESTIMATE with rework_count 0 ..."."

    Design: Corner/endpoints/repair_order_side_effects_on_create
    """
    shop, tech = _certified_shop_with_tech(api, "Sideeffect Body", "06101", 41.76, -72.68)
    before = validate_success(api.get_shop(shop["id"], sm(shop["id"])))
    order = validate_success(api.create_repair_order(
        shop["id"],
        {
            "expected_shop_version": before["version"],
            "vin": "1HGCV1F34LA000017",
            "vehicle_model_year": 2015,
            "estimate_total_cents": 10000,
            "assigned_technician_id": tech["id"],
        },
        sm(shop["id"]),
    ), 201)
    assert order["status"] == "ESTIMATE"
    after = validate_success(api.get_shop(shop["id"], sm(shop["id"])))
    assert after["lifetime_repair_count"] == 1
    assert after["version"] == before["version"] + 1


def test_repair_order_create_increments_lifetime_count_per_order(api):
    """PRD §3.5: "Creating the order increments the shop's
    lifetime_repair_count — the counter grows at create time and is never
    touched again — and bumps the shop's version."

    Design: Corner/endpoints/repair_order_side_effects_on_create
    """
    shop, tech = _certified_shop_with_tech(api, "Sideeffect Body 2", "06102", 41.76, -72.68)
    for i in range(2):
        v = validate_success(api.get_shop(shop["id"], ADMIN))["version"]
        validate_success(api.create_repair_order(
            shop["id"],
            {
                "expected_shop_version": v,
                "vin": f"1HGCV1F34LA000{200 + i}",
                "vehicle_model_year": 2015,
                "estimate_total_cents": 10000,
                "assigned_technician_id": tech["id"],
            },
            sm(shop["id"]),
        ), 201)
    after = validate_success(api.get_shop(shop["id"], ADMIN))
    assert after["lifetime_repair_count"] == 2


def test_procedure_step_reperform_voids_prior(api):
    """PRD §3.5: "Re-performing a step of the same type voids the prior
    record: the older step of that step_type moves from RECORDED to VOIDED,
    and the order's chronology validations are re-evaluated against the
    surviving records."

    Design: Corner/endpoints/procedure_step_reperform_voids_prior
    """
    shop, tech = _certified_shop_with_tech(api, "Reperform Body", "02101", 42.36, -71.06)
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000018")

    # Approve without a PRE_SCAN must fail the mandatory pre-scan rule.
    no_scan = api.approve_order(order["id"], sm(shop["id"]))
    validate_error(no_scan, ApiErrorId.ERR_PRE_SCAN_REQUIRED)

    step1 = record_step(order["id"], "PRE_SCAN", tech["id"], "2026-09-01T03:00:00Z", "FAIL", shop["id"])
    validate_success(api.approve_order(order["id"], sm(shop["id"])))
    add_part(order["id"], shop["id"], part_number="PX")
    get_success_data(api.start_repair(order["id"], sm(shop["id"])))

    step2 = record_step(order["id"], "PRE_SCAN", tech["id"], "2026-09-01T04:00:00Z", "PASS", shop["id"])
    rows, _meta = validate_paginated(api.list_procedure_steps(order["id"], sm(shop["id"])))
    by_id = {r["id"]: r for r in rows}
    assert by_id[step1["id"]]["status"] == "VOIDED"
    assert by_id[step2["id"]]["status"] == "RECORDED"


def test_procedure_step_reperform_keeps_distinct_types(api):
    """PRD §3.5: "Re-performing a step of the same type voids the prior
    record: the older step of that step_type moves from RECORDED to VOIDED."
    A step of a different type must not void the earlier row.

    Design: Corner/endpoints/procedure_step_reperform_voids_prior
    """
    shop, tech = _certified_shop_with_tech(api, "Reperform Body 2", "02102", 42.36, -71.06)
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000018")
    step1 = record_step(order["id"], "PRE_SCAN", tech["id"], "2026-09-01T03:00:00Z", "PASS", shop["id"])
    validate_success(api.approve_order(order["id"], sm(shop["id"])))
    add_part(order["id"], shop["id"], part_number="PY")
    get_success_data(api.start_repair(order["id"], sm(shop["id"])))
    step2 = record_step(order["id"], "POST_SCAN", tech["id"], "2026-09-01T05:00:00Z", "PASS", shop["id"])
    rows, _meta = validate_paginated(api.list_procedure_steps(order["id"], sm(shop["id"])))
    by_id = {r["id"]: r for r in rows}
    assert by_id[step1["id"]]["status"] == "RECORDED"
    assert by_id[step2["id"]]["status"] == "RECORDED"


def test_fk_reverse_reachability_lists(api):
    """PRD §4: the endpoint table lists "GET /network/attestations" as
    "Filtered list of attestations across shops; requirement_id finds all
    attestations pinned to a requirement row" and "GET
    /network/corrective-actions" as "Filtered list of corrective actions;
    attestation_id finds actions against an attestation".

    Design: Corner/endpoints/fk_reverse_reachability_lists
    """
    shop = create_shop(legal_name="Reverse Body", state_code="KY", zip_code="40201",
                       latitude=38.25, longitude=-85.76)
    req = create_published_requirement(
        requirement_code="EQ-REV-99", category="EQUIPMENT",
        severity_if_failed="MINOR", effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    cycle = open_cycle(shop["id"])
    audit = schedule_and_run_audit(cycle["id"], AUD1)
    get_success_data(api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "MINOR"}]},
        AUD1))

    atts, _ = validate_paginated(api.list_attestations(AUD1, params={"requirement_id": req["id"]}))
    assert [a["id"] for a in atts] == [att["id"]]
    cas, _ = validate_paginated(api.list_corrective_actions(AUD1, params={"attestation_id": att["id"]}))
    assert len(cas) == 1
    assert cas[0]["attestation_id"] == att["id"]


def test_referrals_filtered_by_routed_shop(api):
    """PRD §4: the endpoint table lists "GET /network/referrals" as "Filtered
    list of referrals; routed_shop_id finds referrals pointing at a shop", and
    PRD §3.8: "Routing happens automatically at creation when the pool is
    non-empty".

    Design: Corner/endpoints/fk_reverse_reachability_lists
    """
    shop, _cycle = create_certified_shop(
        legal_name="Reverse Ref Body", zip_code="40202", latitude=38.25, longitude=-85.76)
    ref = validate_success(api.create_referral(
        {"consumer_zip": "40202", "source_type": "DEALER", "source_reference": "DLR-1",
         "vin": "1HGCV1F34LA000026"}, DEALER), 201)
    assert ref["status"] == "ROUTED"
    assert ref["routed_shop_id"] == shop["id"]
    rows, _ = validate_paginated(api.list_referrals(ADMIN, params={"routed_shop_id": shop["id"]}))
    assert [r["id"] for r in rows] == [ref["id"]]
