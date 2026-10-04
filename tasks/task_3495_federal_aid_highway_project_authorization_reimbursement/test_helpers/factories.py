"""Payload factories — one per write endpoint, input fields only (PRD §4).

Computed and system-managed fields (ids, statuses, shares, timestamps) are
never included; the server owns those.
"""
from . import constants as C


# ---------------------------------------------------------------------------
# Platform clock
# ---------------------------------------------------------------------------
def create_clock_payload(current_utc=C.CLOCK_START, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# FundingProgram / Apportionment
# ---------------------------------------------------------------------------
def create_funding_program_payload(
    code="NHPP",
    name=None,
    eligible_activity_codes=None,
    **overrides,
) -> dict:
    payload = {
        "code": code,
        "name": name if name is not None else f"{code} Program",
        "eligible_activity_codes": (
            list(eligible_activity_codes)
            if eligible_activity_codes is not None
            else ["ROAD_RESURFACING"]
        ),
    }
    payload.update(overrides)
    return payload


def create_apportionment_payload(
    funding_program_id,
    state_code=C.DEFAULT_STATE_CODE,
    federal_fiscal_year=C.DEFAULT_FFY,
    apportioned_cents=C.DEFAULT_APPORTIONED_CENTS,
    **overrides,
) -> dict:
    payload = {
        "funding_program_id": funding_program_id,
        "state_code": state_code,
        "federal_fiscal_year": federal_fiscal_year,
        "apportioned_cents": apportioned_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# STIP / PublicComment
# ---------------------------------------------------------------------------
def create_stip_payload(
    state_code=C.DEFAULT_STATE_CODE,
    state_federal_land_pct=0.0,
    start_federal_fiscal_year=C.DEFAULT_STIP_START_FFY,
    description="Statewide Transportation Improvement Program",
    **overrides,
) -> dict:
    payload = {
        "state_code": state_code,
        "state_federal_land_pct": state_federal_land_pct,
        "start_federal_fiscal_year": start_federal_fiscal_year,
        "description": description,
    }
    payload.update(overrides)
    return payload


def create_comment_payload(
    author_name="Public Citizen",
    comment_text="Please fund this corridor.",
    **overrides,
) -> dict:
    payload = {"author_name": author_name, "comment_text": comment_text}
    payload.update(overrides)
    return payload


def create_stip_decision_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
def create_project_payload(
    stip_id,
    funding_program_id,
    route_name="I-5",
    description="Corridor project",
    activity_code="ROAD_RESURFACING",
    is_interstate_system=False,
    dbe_goal_pct=C.DEFAULT_DBE_GOAL_PCT,
    total_estimated_cost_cents=C.DEFAULT_PROJECT_COST_CENTS,
    **overrides,
) -> dict:
    payload = {
        "stip_id": stip_id,
        "funding_program_id": funding_program_id,
        "route_name": route_name,
        "description": description,
        "activity_code": activity_code,
        "is_interstate_system": is_interstate_system,
        "dbe_goal_pct": dbe_goal_pct,
        "total_estimated_cost_cents": total_estimated_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_project_patch_payload(expected_project_version, **fields) -> dict:
    """OCC-guarded PATCH payload (PRD §2.8). Only description,
    total_estimated_cost_cents, and dbe_goal_pct are patchable (PRD §3.3)."""
    payload = {"expected_project_version": expected_project_version}
    payload.update(fields)
    return payload


def create_determination_payload(determination="ELIGIBLE", **overrides) -> dict:
    payload = {"determination": determination}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clearances
# ---------------------------------------------------------------------------
def create_clearance_payload(
    project_id,
    kind="ENVIRONMENTAL",
    nepa_class="CE",
    **overrides,
) -> dict:
    """nepa_class is required for ENVIRONMENTAL and must be null for
    RIGHT_OF_WAY (PRD §3.4). Pass nepa_class=None explicitly for ROW."""
    payload = {"project_id": project_id, "kind": kind}
    if nepa_class is not None:
        payload["nepa_class"] = nepa_class
    payload.update(overrides)
    return payload


def create_clearance_decision_payload(
    decision="CLEARED", row_cert_level=None, **overrides
) -> dict:
    """row_cert_level (LEVEL_1_FULL | LEVEL_2_CONDITIONAL) is required when
    clearing a RIGHT_OF_WAY clearance (PRD §3.4)."""
    payload = {"decision": decision}
    if row_cert_level is not None:
        payload["row_cert_level"] = row_cert_level
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def create_authorization_payload(
    project_id,
    agreement_number=C.DEFAULT_AGREEMENT_NUMBER,
    initial_obligated_cents=C.DEFAULT_INITIAL_OBLIGATED_CENTS,
    **overrides,
) -> dict:
    payload = {
        "project_id": project_id,
        "agreement_number": agreement_number,
        "initial_obligated_cents": initial_obligated_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bids / Award
# ---------------------------------------------------------------------------
def create_bid_entry(
    contractor_name="Low Bidder",
    bid_amount_cents=C.DEFAULT_BID_AMOUNT_CENTS,
    is_responsive=True,
) -> dict:
    return {
        "contractor_name": contractor_name,
        "bid_amount_cents": bid_amount_cents,
        "is_responsive": is_responsive,
    }


def create_open_bids_payload(bids=None, **overrides) -> dict:
    """bids: non-empty array of bid entries (PRD §3.6)."""
    payload = {"bids": list(bids) if bids is not None else [create_bid_entry()]}
    payload.update(overrides)
    return payload


def create_award_payload(
    bid_id,
    dbe_commitment_pct=C.DEFAULT_DBE_GOAL_PCT,
    good_faith_effort_documented=None,
    **overrides,
) -> dict:
    payload = {"bid_id": bid_id, "dbe_commitment_pct": dbe_commitment_pct}
    if good_faith_effort_documented is not None:
        payload["good_faith_effort_documented"] = good_faith_effort_documented
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Vouchers
# ---------------------------------------------------------------------------
def create_line_item(description="work item", eligible_amount_cents=10_000) -> dict:
    return {"description": description, "eligible_amount_cents": eligible_amount_cents}


def create_voucher_payload(
    authorization_id,
    period_start_date=C.DEFAULT_PERIOD_START,
    period_end_date=C.DEFAULT_PERIOD_END,
    line_items=None,
    documentation_complete=True,
    is_final=False,
    **overrides,
) -> dict:
    payload = {
        "authorization_id": authorization_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "line_items": (
            list(line_items) if line_items is not None else [create_line_item()]
        ),
        "documentation_complete": documentation_complete,
        "is_final": is_final,
    }
    payload.update(overrides)
    return payload


def create_voucher_submit_payload(**revisions) -> dict:
    """Resubmission revisions (PRD §3.7): only the fields being revised."""
    return dict(revisions)


def create_voucher_decision_payload(
    decision="APPROVE", ineligible_line_indexes=None, **overrides
) -> dict:
    payload = {"decision": decision}
    if ineligible_line_indexes is not None:
        payload["ineligible_line_indexes"] = list(ineligible_line_indexes)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Change orders
# ---------------------------------------------------------------------------
def create_change_order_payload(
    authorization_id,
    description="Unforeseen site conditions",
    delta_cost_cents=100_000,
    **overrides,
) -> dict:
    payload = {
        "authorization_id": authorization_id,
        "description": description,
        "delta_cost_cents": delta_cost_cents,
    }
    payload.update(overrides)
    return payload


def create_federal_decision_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------
def create_audit_payload(project_id, **overrides) -> dict:
    payload = {"project_id": project_id}
    payload.update(overrides)
    return payload


def create_findings_payload(
    findings_text="No ineligible expenditures found.",
    ineligible_amount_cents=0,
    **overrides,
) -> dict:
    payload = {
        "findings_text": findings_text,
        "ineligible_amount_cents": ineligible_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_repayment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload
