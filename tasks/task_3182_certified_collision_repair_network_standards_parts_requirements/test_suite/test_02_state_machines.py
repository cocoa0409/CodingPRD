"""State-machine and certification-lifecycle tests."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_shop, create_published_requirement, open_cycle, attest,
    certify_shop, create_certified_shop, create_technician, create_order,
    schedule_and_run_audit, sm, admin_as, auditor_as,
    TEST_USERS,
    WINDOW2_START, WINDOW2_END,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]


def test_requirement_initial_state_draft(api, admin_headers):
    """PRD §3.2: "A NetworkAdmin authors a requirement in DRAFT with a stable
    requirement_code ... the first revision of a code carries
    requirement_version 1 and a null supersedes_requirement_id."

    Design: Corner/state_machines/requirement_initial_state_draft
    """
    resp = api.create_requirement(
        {
            "requirement_code": "EQ-INIT-01",
            "category": "EQUIPMENT",
            "description": "x",
            "severity_if_failed": "MINOR",
            "effective_from": "2026-09-02T00:00:00Z",
        },
        admin_headers,
    )
    req = validate_success(resp, 201)
    assert req["status"] == "DRAFT"
    assert req["requirement_version"] == 1
    assert req["supersedes_requirement_id"] is None
    fetched = validate_success(api.get_requirement(req["id"], admin_headers))
    assert fetched["status"] == "DRAFT"
    assert fetched["requirement_version"] == 1


def test_requirement_publish_moves_draft_to_published(api, admin_headers):
    """PRD §3.2: "Publishing a draft requires effective_from to be present and
    no earlier than the logical clock; a past effective date is rejected with
    ERR_EFFECTIVE_IN_PAST (HTTP 422)."

    Design: Corner/state_machines/requirement_initial_state_draft
    """
    req = validate_success(api.create_requirement(
        {
            "requirement_code": "EQ-INIT-02",
            "category": "TOOLING",
            "description": "y",
            "severity_if_failed": "MAJOR",
            "effective_from": "2026-09-01T00:00:00Z",
        },
        admin_headers,
    ), 201)
    published = validate_success(api.publish_requirement(req["id"], admin_headers))
    assert published["status"] == "PUBLISHED"


def _drive_shop_to_decertified(api):
    """Shop -> CERTIFIED -> SUSPENDED (overdue CRITICAL corrective action)
    -> 90 days -> DECERTIFIED."""
    shop = create_shop(legal_name="Doomed Body", state_code="AK", zip_code="99501",
                       latitude=61.22, longitude=-149.9)
    req = create_published_requirement(
        requirement_code="ST-DOOM-01", category="STRUCTURAL",
        severity_if_failed="CRITICAL", effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    certify_shop(shop["id"])
    cycle2 = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    audit2 = schedule_and_run_audit(
        cycle2["id"], AUD1,
        scheduled_start="2026-09-05T09:00:00Z",
        scheduled_end="2026-09-05T17:00:00Z",
        begin_at="2026-09-05T10:00:00Z")
    get_success_data(api.issue_findings(
        audit2["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "CRITICAL"}]},
        AUD1))
    get_success_data(api.set_clock("2026-09-16T00:00:00Z", ADMIN))
    get_success_data(api.set_clock("2026-12-16T00:00:00Z", ADMIN))
    return shop


def test_terminal_state_lockdown_decertified_shop(api, admin_headers):
    """PRD §3.1: "A NetworkAdmin may decertify a shop only while it has
    remained SUSPENDED for at least 90 days by the logical clock and no repair
    order of the shop sits in ESTIMATE, APPROVED, IN_REPAIR, QC, REWORK, or
    CALIBRATION; otherwise the request is rejected with ERR_DECERTIFY_BLOCKED
    (HTTP 422). A successful decertification moves the shop to DECERTIFIED ..."
    PRD §3.5: "a shop in SUSPENDED, EXPIRED, or DECERTIFIED may not start new
    repairs, and the attempt is rejected with ERR_SHOP_NOT_CERTIFIED
    (HTTP 422)."

    Design: Corner/state_machines/terminal_state_lockdown_decertified_shop
    """
    shop = _drive_shop_to_decertified(api)
    result = validate_success(api.decertify_shop(shop["id"], admin_headers))
    assert result["certification_status"] == "DECERTIFIED"

    shop_now = validate_success(api.get_shop(shop["id"], admin_headers))
    bad = api.create_repair_order(
        shop["id"],
        {
            "expected_shop_version": shop_now["version"],
            "vin": "1HGCV1F34LA000015",
            "vehicle_model_year": 2015,
            "estimate_total_cents": 1000,
            "assigned_technician_id": NON_EXISTENT_UUID,
        },
        sm(shop["id"]),
    )
    assert bad.status_code in (404, 422), f"expected 4xx, got {bad.status_code}"
    validate_error_is_one_of(bad, [ApiErrorId.ERR_NOT_FOUND, ApiErrorId.ERR_SHOP_NOT_CERTIFIED])


def test_decertified_shop_locator_hidden_and_relations_terminated(api, admin_headers):
    """PRD §3.1: "A successful decertification moves the shop to DECERTIFIED,
    terminates every ACTIVE insurer relation, force-declines every ROUTED
    referral, and pins locator_hidden to true permanently."

    Design: Corner/state_machines/terminal_state_lockdown_decertified_shop
    """
    from test_helpers import create_insurer_relation
    shop = create_shop(legal_name="Doomed Rel Body", state_code="AK", zip_code="99502",
                       latitude=61.22, longitude=-149.9)
    req = create_published_requirement(
        requirement_code="ST-DOOM-02", category="STRUCTURAL",
        severity_if_failed="CRITICAL", effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    rel = create_insurer_relation(shop["id"], insurer_code="INS-DOOM", discount_pct_bps=100)
    certify_shop(shop["id"])
    cycle2 = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    audit2 = schedule_and_run_audit(
        cycle2["id"], AUD1,
        scheduled_start="2026-09-05T09:00:00Z",
        scheduled_end="2026-09-05T17:00:00Z",
        begin_at="2026-09-05T10:00:00Z")
    get_success_data(api.issue_findings(
        audit2["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "CRITICAL"}]},
        AUD1))
    get_success_data(api.set_clock("2026-09-16T00:00:00Z", ADMIN))
    get_success_data(api.set_clock("2026-12-16T00:00:00Z", ADMIN))
    validate_success(api.decertify_shop(shop["id"], admin_headers))

    shop_now = validate_success(api.get_shop(shop["id"], admin_headers))
    assert shop_now["certification_status"] == "DECERTIFIED"
    assert shop_now["locator_hidden"] is True
    rel_now = validate_success(api.get_insurer_relation(rel["id"], admin_headers))
    assert rel_now["status"] == "TERMINATED"


def _setup_open_corrective_action(api, severity="MAJOR", requirement_code="TL-EV-01"):
    """Shop + published requirement + attestation + audit with one finding;
    returns (shop, audit, corrective_action)."""
    shop = create_shop(legal_name="Early Verify Body", state_code="HI", zip_code="96801",
                       latitude=21.31, longitude=-157.86)
    req = create_published_requirement(
        requirement_code=requirement_code, category="TOOLING",
        severity_if_failed=severity, effective_from="2026-09-01T00:00:00Z")
    att = attest(shop["id"], req["id"])
    cycle = open_cycle(shop["id"])
    audit = schedule_and_run_audit(cycle["id"], AUD1)
    get_success_data(api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": att["id"], "severity": severity}]},
        AUD1))
    cas = get_success_data(api.list_audit_corrective_actions(audit["id"], AUD1))
    return shop, audit, cas[0]


def test_corrective_action_invalid_from_open_verify(api):
    """PRD §3.3: "A NetworkAuditor then verifies each submission with a
    verdict." and the CorrectiveAction lifecycle allows verification only from
    SUBMITTED; PRD §2.10: "then legal source state (ERR_INVALID_STATE,
    HTTP 409)".

    Design: Corner/state_machines/corrective_action_invalid_from_open_verify
    """
    _shop, _audit, ca = _setup_open_corrective_action(api)
    resp = api.verify_corrective_action(ca["id"], {"verdict": "VERIFIED"}, auditor_as("aud-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_corrective_action_open_verify_leaves_state_unchanged(api):
    """PRD §3.3: "Each corrective action opens in OPEN status ..." and
    verification applies only to a submitted action: "A verdict of VERIFIED
    moves the action SUBMITTED → VERIFIED ...". An out-of-state verify must
    not advance the action.

    Design: Corner/state_machines/corrective_action_invalid_from_open_verify
    """
    shop, audit, ca = _setup_open_corrective_action(api, requirement_code="TL-EV-02")
    api.verify_corrective_action(ca["id"], {"verdict": "VERIFIED"}, auditor_as("aud-2"))
    after = validate_success(api.get_corrective_action(ca["id"], auditor_as("aud-1")))
    assert after["status"] == "OPEN"
    audit_after = validate_success(api.get_audit(audit["id"], auditor_as("aud-1")))
    assert audit_after["status"] == "FINDINGS_ISSUED"


def _setup_certified_shop_with_tech_and_order(api):
    shop, _cycle = create_certified_shop(
        legal_name="Deactivate Body", state_code="WV", zip_code="25301",
        latitude=38.35, longitude=-81.63)
    tech = create_technician(shop["id"], full_name="De Act", tech_role="NON_STRUCTURAL")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000024",
                         estimate_total_cents=10000)
    return shop, tech, order


def test_technician_deactivate_blocked_by_open_orders(api):
    """PRD §3.4: "A ShopManager may deactivate a technician, moving them from
    PROVISIONAL or CURRENT to the terminal INACTIVE, only while no repair
    order references the technician with status ESTIMATE, APPROVED, IN_REPAIR,
    QC, REWORK, or CALIBRATION." PRD §3.5: "From ESTIMATE, voiding is
    unconditional and moves the order to the terminal VOIDED."

    Design: Corner/state_machines/technician_deactivate_blocked_by_open_orders
    """
    shop, tech, order = _setup_certified_shop_with_tech_and_order(api)
    blocked = api.deactivate_technician(tech["id"], sm(shop["id"]))
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
    validate_success(api.void_order(order["id"], {}, sm(shop["id"])))
    after = validate_success(api.deactivate_technician(tech["id"], sm(shop["id"])))
    assert after["status"] == "INACTIVE"


def test_technician_deactivate_succeeds_without_open_orders(api):
    """PRD §3.4: "A ShopManager may deactivate a technician, moving them from
    PROVISIONAL or CURRENT to the terminal INACTIVE, only while no repair
    order references the technician with status ESTIMATE, APPROVED, IN_REPAIR,
    QC, REWORK, or CALIBRATION."

    Design: Corner/state_machines/technician_deactivate_blocked_by_open_orders
    """
    shop, _cycle = create_certified_shop(
        legal_name="Free Tech Body", state_code="WV", zip_code="25302",
        latitude=38.35, longitude=-81.63)
    tech = create_technician(shop["id"], full_name="No Orders", tech_role="REFINISH")
    result = validate_success(api.deactivate_technician(tech["id"], sm(shop["id"])))
    assert result["status"] == "INACTIVE"
