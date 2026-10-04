"""Composite setup helpers.

Every test starts against an empty database, so these helpers build the full
precondition chain with PRD-declared endpoints only. All success calls use
the lenient get_success_data() so setup failures surface as setup errors.

Identity threading (PRD §2.1): entity-backed roles always pass the real
entity id as X-User-ID via the make_*_headers builders.
"""
from prd_bench_local_runner.testing import build_user_headers, get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO
from .factories import (
    asset_account_payload,
    channel_partner_payload,
    charger_payload,
    counterfeit_case_payload,
    insight_payload,
    listing_payload,
    pack_payload,
    platform_payload,
    safety_bulletin_payload,
    service_center_payload,
    tool_model_payload,
    tracked_asset_payload,
    warranty_claim_payload,
)
from .test_users import (
    make_account_manager_headers,
    make_channel_manager_headers,
    make_service_agent_headers,
)

ADMIN = build_user_headers("admin-1", "PlatformAdmin")
PE = build_user_headers("pe-ana", "ProductEngineer")
CE = build_user_headers("ce-bob", "ComplianceEngineer")
FR = build_user_headers("fr-kim", "FieldResearcher")


def pe_headers(user_id: str = "pe-ana") -> dict:
    return build_user_headers(user_id, "ProductEngineer")


def ce_headers(user_id: str = "ce-bob") -> dict:
    return build_user_headers(user_id, "ComplianceEngineer")


def fr_headers(user_id: str = "fr-kim") -> dict:
    return build_user_headers(user_id, "FieldResearcher")


# --- clock & platform -------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_DEFAULT_ISO):
    """Drive the logical clock (endpoint lives outside the API prefix, PRD §2.5)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"clock set failed: {resp.text}"


def create_platform(**overrides) -> dict:
    return get_success_data(api_client.create_platform(platform_payload(**overrides), ADMIN))


# --- packs & chargers -------------------------------------------------------

def create_pack(platform_id: str, **overrides) -> dict:
    """Create a pack (starts in DESIGN)."""
    return get_success_data(api_client.create_pack(pack_payload(platform_id, **overrides), PE))


def submit_pack(pack_id: str, submitter: str = "pe-ana") -> dict:
    return get_success_data(
        api_client.submit_pack_certification(pack_id, pe_headers(submitter))
    )


def decide_pack(pack_id: str, decision: str, decider: str = "ce-bob") -> dict:
    return get_success_data(
        api_client.decide_pack_certification(pack_id, {"decision": decision}, ce_headers(decider))
    )


def certify_pack(pack_id: str, submitter: str = "pe-ana", decider: str = "ce-bob") -> dict:
    """DESIGN -> SUBMITTED -> CERTIFIED (segregation of duties respected)."""
    submit_pack(pack_id, submitter)
    return decide_pack(pack_id, "CERTIFIED", decider)


def create_certified_pack(platform_id: str, **overrides) -> dict:
    pack = create_pack(platform_id, **overrides)
    return certify_pack(pack["id"])


def get_pack(pack_id: str, headers=None, params=None) -> dict:
    return get_success_data(api_client.get_pack(pack_id, headers or PE, params=params))


def create_charger(platform_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_charger(charger_payload(platform_id, **overrides), PE))


# --- tool models & insights ---------------------------------------------------

def create_tool(platform_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_tool_model(tool_model_payload(platform_id, **overrides), PE))


def get_tool(tool_id: str) -> dict:
    return get_success_data(api_client.get_tool_model(tool_id, PE))


def submit_insight(tool_id: str, kind: str, severity: str = "HIGH",
                   summary: str = "field finding", researcher: str = "fr-kim") -> dict:
    return get_success_data(api_client.create_insight(
        insight_payload(tool_id, kind=kind, severity=severity, summary=summary),
        fr_headers(researcher),
    ))


def adopt_insight(insight_id: str, decider: str = "pe-ana") -> dict:
    return get_success_data(
        api_client.decide_insight(insight_id, {"decision": "ADOPTED"}, pe_headers(decider))
    )


def adopt_standard_research(tool_id: str):
    """Adopt 2 FIELD_RESEARCH + 1 JOBSITE_OBSERVATION insights for the tool.

    Satisfies the PROTOTYPE and ENGINEERING_VALIDATION stage gates (PRD §3.3).
    """
    adopt_insight(submit_insight(tool_id, "FIELD_RESEARCH", summary="fr1")["id"])
    adopt_insight(submit_insight(tool_id, "FIELD_RESEARCH", severity="LOW", summary="fr2")["id"])
    adopt_insight(submit_insight(tool_id, "JOBSITE_OBSERVATION", severity="MEDIUM", summary="jo1")["id"])


def transition_tool(tool_id: str, to_stage: str, expected_version=None) -> dict:
    """Transition a tool; when expected_version is None, read the fresh version."""
    if expected_version is None:
        expected_version = get_tool(tool_id)["version"]
    return get_success_data(api_client.transition_tool_model(
        tool_id,
        {"to_stage": to_stage, "expected_tool_model_version": expected_version},
        PE,
    ))


def stage_tool_to_engineering_validation(tool_id: str) -> dict:
    """CONCEPT -> FIELD_RESEARCH -> PROTOTYPE -> ENGINEERING_VALIDATION.

    Assumes the research gates are already satisfied.
    """
    transition_tool(tool_id, "FIELD_RESEARCH")
    transition_tool(tool_id, "PROTOTYPE")
    return transition_tool(tool_id, "ENGINEERING_VALIDATION")


def create_launch_ready_tool(platform_id: str, **overrides) -> dict:
    """Tool with standard adopted research, staged to ENGINEERING_VALIDATION."""
    tool = create_tool(platform_id, **overrides)
    adopt_standard_research(tool["id"])
    return stage_tool_to_engineering_validation(tool["id"])


# --- service centers, accounts, tracked assets -------------------------------

def create_center(**overrides) -> dict:
    return get_success_data(api_client.create_service_center(service_center_payload(**overrides), ADMIN))


def create_account(tier: str = "STANDARD", **overrides) -> dict:
    return get_success_data(api_client.create_asset_account(asset_account_payload(tier=tier, **overrides), ADMIN))


def create_battery_asset(account_id: str, pack_id: str, serial_number=None,
                         manufactured_at: str = "2026-08-01T00:00:00Z") -> dict:
    overrides = {
        "subject_type": "BATTERY",
        "battery_pack_id": pack_id,
        "manufactured_at": manufactured_at,
    }
    if serial_number is not None:
        overrides["serial_number"] = serial_number
    return get_success_data(api_client.create_tracked_asset(
        tracked_asset_payload(account_id, **overrides),
        make_account_manager_headers(account_id),
    ))


def create_tool_asset(account_id: str, tool_id: str, serial_number=None,
                      manufactured_at: str = "2026-08-01T00:00:00Z") -> dict:
    overrides = {
        "subject_type": "TOOL",
        "tool_model_id": tool_id,
        "manufactured_at": manufactured_at,
    }
    if serial_number is not None:
        overrides["serial_number"] = serial_number
    return get_success_data(api_client.create_tracked_asset(
        tracked_asset_payload(account_id, **overrides),
        make_account_manager_headers(account_id),
    ))


def get_asset(asset_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_tracked_asset(asset_id, headers or PE))


def transition_asset(asset_id: str, account_id: str, to_status: str) -> dict:
    return get_success_data(api_client.transition_tracked_asset(
        asset_id, {"to_status": to_status}, make_account_manager_headers(account_id)
    ))


# --- warranty claims -----------------------------------------------------------

def create_claim(asset_id: str, account_id: str, claim_type: str,
                 service_date: str, fault_code: str = "F1") -> dict:
    return get_success_data(api_client.create_warranty_claim(
        warranty_claim_payload(
            asset_id, claim_type=claim_type, service_date=service_date, fault_code=fault_code,
        ),
        make_account_manager_headers(account_id),
    ))


def adjudicate_claim(claim_id: str, service_center_id: str, decision: str) -> dict:
    return get_success_data(api_client.adjudicate_warranty_claim(
        claim_id, {"decision": decision}, make_service_agent_headers(service_center_id)
    ))


def complete_claim(claim_id: str, service_center_id: str) -> dict:
    return get_success_data(api_client.complete_warranty_claim(
        claim_id, make_service_agent_headers(service_center_id)
    ))


def get_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, headers or PE))


# --- channel partners & listings ------------------------------------------------

def create_partner(channel_type: str = "INDUSTRIAL_DISTRIBUTOR", **overrides) -> dict:
    return get_success_data(api_client.create_channel_partner(
        channel_partner_payload(channel_type=channel_type, **overrides), ADMIN
    ))


def create_listing(partner: dict, expected_channel_partner_version=None,
                   tool_model_id=None, battery_pack_id=None, charger_id=None,
                   wholesale_price_cents: int = 12000, allocation_qty: int = 10) -> dict:
    """Create a PROPOSED listing. OCC: pass the partner's current version.

    The response echoes channel_partner_version — resync the next create from it
    (PRD §2.7), since partner creation and every listing mutation bump it.
    """
    if expected_channel_partner_version is None:
        expected_channel_partner_version = partner["version"]
    payload = listing_payload(
        partner["id"], expected_channel_partner_version,
        wholesale_price_cents=wholesale_price_cents, allocation_qty=allocation_qty,
    )
    if tool_model_id is not None:
        payload["tool_model_id"] = tool_model_id
    if battery_pack_id is not None:
        payload["battery_pack_id"] = battery_pack_id
    if charger_id is not None:
        payload["charger_id"] = charger_id
    return get_success_data(api_client.create_listing(
        payload, make_channel_manager_headers(partner["id"])
    ))


def transition_listing(listing_id: str, partner_id: str, to_status: str) -> dict:
    return get_success_data(api_client.transition_listing(
        listing_id, {"to_status": to_status}, make_channel_manager_headers(partner_id)
    ))


def activate_listing(listing_id: str, partner_id: str) -> dict:
    return transition_listing(listing_id, partner_id, "ACTIVE")


def get_listing(listing_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_listing(listing_id, headers or PE))


def create_active_listing(partner: dict, expected_channel_partner_version=None, **product) -> dict:
    """Create a listing and activate it. Returns the ACTIVE listing."""
    listing = create_listing(
        partner, expected_channel_partner_version, **product,
    )
    return activate_listing(listing["id"], partner["id"])


# --- counterfeit cases & safety bulletins -----------------------------------------

def report_counterfeit(pack_id: str, reporter_headers: dict, reported_serial=None,
                       detection_method: str = "SERIAL_MISMATCH") -> dict:
    overrides = {"detection_method": detection_method}
    if reported_serial is not None:
        overrides["reported_serial"] = reported_serial
    return get_success_data(api_client.create_counterfeit_case(
        counterfeit_case_payload(pack_id, **overrides), reporter_headers
    ))


def issue_bulletin(platform_id: str, issuer: str = "ce-bob", **overrides) -> dict:
    return get_success_data(api_client.create_safety_bulletin(
        safety_bulletin_payload(platform_id, **overrides), ce_headers(issuer)
    ))


def get_bulletin(bulletin_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_safety_bulletin(bulletin_id, headers or PE))
