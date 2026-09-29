"""Request payload factories.

Every builder returns a dict whose field names are the PRD's own input names.
Two conventions are load-bearing and hold everywhere in this module:

* every ``_cents`` value is a Python ``int``, because PRD 2.6 transports money
  as a JSON integer rather than a string or a decimal; and
* every date or instant literal is a full ISO 8601 instant with a ``Z`` suffix,
  because every temporal field in this API is an instant compared against the
  logical clock rather than a calendar date.
"""
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# The Harbor Bay roll.  These four properties give a district an assessable
# pool above the floor of three, one property per classification, and both
# boundary zones, so the assessment branches can all be exercised.
# --------------------------------------------------------------------------
DISTRICT_NAME = "Harbor Bay Tourism Improvement District"

B1_NAME = "Harbor Grand Hotel"
B1_ROOM_COUNT = 200
B1_REVENUE_CENTS = 60000000

B2_NAME = "Bayside Inn"
B2_ROOM_COUNT = 120
B2_REVENUE_CENTS = 20000000

B3_NAME = "Lighthouse Boutique"
B3_ROOM_COUNT = 60
B3_REVENUE_CENTS = 15000000

B4_NAME = "Cove Cottages"
B4_ROOM_COUNT = 40
B4_REVENUE_CENTS = 5000000


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``...`` so optional inputs can be
    omitted from the body entirely rather than sent as null."""
    return {k: v for k, v in payload.items() if v is not ...}


# --------------------------------------------------------------------------
# Districts (PRD 3.1)
# --------------------------------------------------------------------------
def district_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /districts.  Only ``name`` is required; the rest govern the
    district's life and each carries a declared default."""
    payload: Dict[str, Any] = {
        "name": DISTRICT_NAME,
        "assessment_method": "PCT_OF_ROOM_REVENUE",
        "included_zones": ["ZONE_CORE", "ZONE_PERIMETER"],
        "formation_threshold_pct": 0.6,
        "renewal_threshold_pct": 0.65,
        "renewal_headcount_threshold_pct": 0.75,
        "term_years": 1,
        "current_fiscal_year": 2027,
    }
    payload.update(overrides)
    return _prune(payload)


def minimal_district_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /districts carrying nothing but the required ``name``, so that every
    declared default is exercised."""
    payload: Dict[str, Any] = {"name": DISTRICT_NAME}
    payload.update(overrides)
    return _prune(payload)


def boundary_revision_payload(
    included_zones: List[str], effective_on: str = "2026-08-01T00:00:00Z"
) -> Dict[str, Any]:
    """POST /districts/{id}/boundary-revisions"""
    return {"included_zones": included_zones, "effective_on": effective_on}


def dmo_coordination_payload(
    dmo_name: str = "Visit Harbor Bay",
    dmo_agreement_status: str = "EXECUTED",
    dmo_contract_cents: int = 200000,
    lodging_tax_match_pool_cents: Any = 400000,
    public_lodging_tax_offset_cents: Any = 0,
) -> Dict[str, Any]:
    """POST /districts/{id}/dmo-coordination"""
    return _prune(
        {
            "dmo_name": dmo_name,
            "dmo_agreement_status": dmo_agreement_status,
            "dmo_contract_cents": dmo_contract_cents,
            "lodging_tax_match_pool_cents": lodging_tax_match_pool_cents,
            "public_lodging_tax_offset_cents": public_lodging_tax_offset_cents,
        }
    )


def lifecycle_advance_payload(
    to_status: str, effective_on: Any = "2026-08-01T00:00:00Z", reason: Any = ...
) -> Dict[str, Any]:
    """POST /districts/{id}/lifecycle-advances"""
    return _prune(
        {"to_status": to_status, "effective_on": effective_on, "reason": reason}
    )


# --------------------------------------------------------------------------
# Lodging businesses (PRD 3.1)
# --------------------------------------------------------------------------
def lodging_business_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    """POST /lodging-businesses"""
    payload: Dict[str, Any] = {
        "district_id": district_id,
        "legal_name": B1_NAME,
        "boundary_zone": "ZONE_CORE",
        "classification": "FULL_SERVICE",
        "room_count": B1_ROOM_COUNT,
        "prior_year_gross_room_revenue_cents": B1_REVENUE_CENTS,
        "operator_contact_email": "ops@harborgrand.example",
    }
    payload.update(overrides)
    return _prune(payload)


def harbor_grand_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    """The core full-service property of the Harbor Bay roll."""
    return lodging_business_payload(district_id, **overrides)


def bayside_inn_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    """The core limited-service property of the Harbor Bay roll."""
    defaults = {
        "legal_name": B2_NAME,
        "boundary_zone": "ZONE_CORE",
        "classification": "LIMITED_SERVICE",
        "room_count": B2_ROOM_COUNT,
        "prior_year_gross_room_revenue_cents": B2_REVENUE_CENTS,
        "operator_contact_email": "ops@baysideinn.example",
    }
    defaults.update(overrides)
    return lodging_business_payload(district_id, **defaults)


def lighthouse_boutique_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    """The perimeter boutique property of the Harbor Bay roll."""
    defaults = {
        "legal_name": B3_NAME,
        "boundary_zone": "ZONE_PERIMETER",
        "classification": "BOUTIQUE",
        "room_count": B3_ROOM_COUNT,
        "prior_year_gross_room_revenue_cents": B3_REVENUE_CENTS,
        "operator_contact_email": "ops@lighthouse.example",
    }
    defaults.update(overrides)
    return lodging_business_payload(district_id, **defaults)


def cove_cottages_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    """The perimeter short-term-rental property of the Harbor Bay roll."""
    defaults = {
        "legal_name": B4_NAME,
        "boundary_zone": "ZONE_PERIMETER",
        "classification": "SHORT_TERM_RENTAL",
        "room_count": B4_ROOM_COUNT,
        "prior_year_gross_room_revenue_cents": B4_REVENUE_CENTS,
        "operator_contact_email": "ops@covecottages.example",
    }
    defaults.update(overrides)
    return lodging_business_payload(district_id, **defaults)


def revision_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /lodging-businesses/{id}/revisions — every input is optional and any
    subset may be supplied."""
    return _prune(dict(overrides))


# --------------------------------------------------------------------------
# Petition drives and signatures (PRD 3.2)
# --------------------------------------------------------------------------
def petition_drive_payload(
    district_id: str,
    drive_type: str = "FORMATION",
    closes_at: str = "2026-09-01T00:00:00Z",
) -> Dict[str, Any]:
    """POST /petition-drives"""
    return {
        "district_id": district_id,
        "drive_type": drive_type,
        "closes_at": closes_at,
    }


def signature_payload(lodging_business_id: str) -> Dict[str, Any]:
    """POST /petition-drives/{id}/signatures"""
    return {"lodging_business_id": lodging_business_id}


def withdrawal_payload(reason: Any = ...) -> Dict[str, Any]:
    """POST /petition-signatures/{id}/withdrawal"""
    return _prune({"reason": reason})


def certification_payload(certified_on: Any = "2026-08-01T00:00:00Z") -> Dict[str, Any]:
    """POST /petition-drives/{id}/certification"""
    return _prune({"certified_on": certified_on})


# --------------------------------------------------------------------------
# Assessment periods and statements (PRD 3.3)
# --------------------------------------------------------------------------
def assessment_period_payload(
    district_id: str,
    period_label: str = "FY2027-Q1",
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-11-01T00:00:00Z",
    due_date: str = "2026-11-15T00:00:00Z",
    grace_days: Any = 10,
) -> Dict[str, Any]:
    """POST /assessment-periods"""
    return _prune(
        {
            "district_id": district_id,
            "period_label": period_label,
            "period_start": period_start,
            "period_end": period_end,
            "due_date": due_date,
            "grace_days": grace_days,
        }
    )


def filing_payload(
    reported_room_nights: int = 2000,
    reported_gross_room_revenue_cents: int = 41225000,
) -> Dict[str, Any]:
    """POST /assessment-statements/{id}/filings"""
    return {
        "reported_room_nights": reported_room_nights,
        "reported_gross_room_revenue_cents": reported_gross_room_revenue_cents,
    }


def statement_amendment_payload(
    expected_statement_version: int,
    reported_room_nights: int,
    reported_gross_room_revenue_cents: int,
    amendment_reason: Any = ...,
) -> Dict[str, Any]:
    """POST /assessment-statements/{id}/amendments"""
    return _prune(
        {
            "expected_statement_version": expected_statement_version,
            "reported_room_nights": reported_room_nights,
            "reported_gross_room_revenue_cents": reported_gross_room_revenue_cents,
            "amendment_reason": amendment_reason,
        }
    )


def remittance_payload(
    amount_cents: int,
    received_on: str = "2026-08-01T00:00:00Z",
    method: str = "WIRE",
) -> Dict[str, Any]:
    """POST /assessment-statements/{id}/remittances"""
    return {
        "amount_cents": amount_cents,
        "received_on": received_on,
        "method": method,
    }


def remittance_reversal_payload(
    remittance_id: str, reversal_reason: str = "returned bank transfer"
) -> Dict[str, Any]:
    """POST /assessment-statements/{id}/remittance-reversals"""
    return {"remittance_id": remittance_id, "reversal_reason": reversal_reason}


def audit_payload(
    audited_room_nights: Any = ...,
    audited_gross_room_revenue_cents: Any = ...,
    audit_note: Any = ...,
) -> Dict[str, Any]:
    """POST /assessment-statements/{id}/audit-certification with action AUDIT."""
    return _prune(
        {
            "action": "AUDIT",
            "audited_room_nights": audited_room_nights,
            "audited_gross_room_revenue_cents": audited_gross_room_revenue_cents,
            "audit_note": audit_note,
        }
    )


def certify_statement_payload(audit_note: Any = ...) -> Dict[str, Any]:
    """POST /assessment-statements/{id}/audit-certification with action CERTIFY."""
    return _prune({"action": "CERTIFY", "audit_note": audit_note})


# --------------------------------------------------------------------------
# Disputes (PRD 3.6)
# --------------------------------------------------------------------------
def dispute_payload(
    assessment_statement_id: str,
    dispute_type: str = "CALCULATION_ERROR",
    claimed_adjustment_cents: int = 82450,
    dispute_note: Any = "resort fee should not sit in the revenue basis",
) -> Dict[str, Any]:
    """POST /assessment-disputes"""
    return _prune(
        {
            "assessment_statement_id": assessment_statement_id,
            "dispute_type": dispute_type,
            "claimed_adjustment_cents": claimed_adjustment_cents,
            "dispute_note": dispute_note,
        }
    )


def proceeding_payload(action: str, note: Any = ...) -> Dict[str, Any]:
    """POST /assessment-disputes/{id}/proceedings"""
    return _prune({"action": action, "note": note})


def resolution_payload(
    outcome: str,
    granted_adjustment_cents: Any = ...,
    exempt_status_granted: Any = ...,
    resolution_note: Any = ...,
) -> Dict[str, Any]:
    """POST /assessment-disputes/{id}/resolution"""
    return _prune(
        {
            "outcome": outcome,
            "granted_adjustment_cents": granted_adjustment_cents,
            "exempt_status_granted": exempt_status_granted,
            "resolution_note": resolution_note,
        }
    )


# --------------------------------------------------------------------------
# Annual work plans (PRD 3.7)
# --------------------------------------------------------------------------
def expenditure_line(category: str, amount_cents: int, narrative: str) -> Dict[str, Any]:
    """One element of ``expenditure_lines``: a category, an amount of at least
    one cent, and a narrative."""
    return {"category": category, "amount_cents": amount_cents, "narrative": narrative}


#: A compliant category mix: 650000 marketing on a 1000000 budget is 0.65 of it,
#: administration 150000 is exactly the 0.15 cap and contingency 100000 is
#: exactly the 0.10 cap.
COMPLIANT_EXPENDITURE_LINES: List[Dict[str, Any]] = [
    expenditure_line("SALES_AND_MARKETING", 650000, "paid search, trade shows and group sales"),
    expenditure_line("ADMINISTRATION", 150000, "district staff and audit fees"),
    expenditure_line("CONTINGENCY_RESERVE", 100000, "statutory reserve"),
    expenditure_line("DESTINATION_EVENTS", 100000, "harbour festival"),
]


def work_plan_payload(
    district_id: str,
    fiscal_year: int = 2027,
    expenditure_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """POST /annual-work-plans"""
    return {
        "district_id": district_id,
        "fiscal_year": fiscal_year,
        "expenditure_lines": (
            COMPLIANT_EXPENDITURE_LINES
            if expenditure_lines is None
            else expenditure_lines
        ),
    }


def board_action_payload(action: str, note: Any = ...) -> Dict[str, Any]:
    """POST /annual-work-plans/{id}/board-actions"""
    return _prune({"action": action, "note": note})


def work_plan_amendment_payload(
    expected_work_plan_version: int,
    expenditure_lines: List[Dict[str, Any]],
    amendment_reason: Any = ...,
) -> Dict[str, Any]:
    """POST /annual-work-plans/{id}/amendments"""
    return _prune(
        {
            "expected_work_plan_version": expected_work_plan_version,
            "expenditure_lines": expenditure_lines,
            "amendment_reason": amendment_reason,
        }
    )


# --------------------------------------------------------------------------
# Marketing programs, claims and performance (PRD 3.8)
# --------------------------------------------------------------------------
def marketing_program_payload(
    annual_work_plan_id: str,
    name: str = "Autumn Group Sales Push",
    channel: str = "GROUP_SALES",
    committed_cents: int = 62000,
    booking_window_start: str = "2026-09-01T00:00:00Z",
    booking_window_end: str = "2026-12-01T00:00:00Z",
    lodging_tax_matched_cents: Any = 0,
) -> Dict[str, Any]:
    """POST /marketing-programs"""
    return _prune(
        {
            "annual_work_plan_id": annual_work_plan_id,
            "name": name,
            "channel": channel,
            "committed_cents": committed_cents,
            "booking_window_start": booking_window_start,
            "booking_window_end": booking_window_end,
            "lodging_tax_matched_cents": lodging_tax_matched_cents,
        }
    )


def launch_payload(
    launch_note: Any = "campaign live for the autumn group sales window",
) -> Dict[str, Any]:
    """POST /marketing-programs/{id}/launch"""
    return _prune({"launch_note": launch_note})


def program_closure_payload(closure_note: Any = "measurement published") -> Dict[str, Any]:
    """POST /marketing-programs/{id}/closure"""
    return _prune({"closure_note": closure_note})


def room_night_claim_payload(
    lodging_business_id: str,
    stay_start: str = "2026-09-10T00:00:00Z",
    stay_end: str = "2026-09-12T00:00:00Z",
    room_nights: int = 100,
    attribution_method: Any = "DIRECT_PICKUP",
) -> Dict[str, Any]:
    """POST /marketing-programs/{id}/room-night-claims"""
    return _prune(
        {
            "lodging_business_id": lodging_business_id,
            "stay_start": stay_start,
            "stay_end": stay_end,
            "room_nights": room_nights,
            "attribution_method": attribution_method,
        }
    )


def verification_payload(
    decision: str,
    verified_room_nights: Any = ...,
    rejection_reason: Any = ...,
) -> Dict[str, Any]:
    """POST /room-night-claims/{id}/verification"""
    return _prune(
        {
            "decision": decision,
            "verified_room_nights": verified_room_nights,
            "rejection_reason": rejection_reason,
        }
    )


# --------------------------------------------------------------------------
# Transparency records (PRD 3.9)
# --------------------------------------------------------------------------
def transparency_record_payload(
    district_id: str,
    record_type: str = "PUBLIC_MEETING",
    fiscal_year: int = 2027,
    scheduled_for: str = "2026-09-15T00:00:00Z",
    required_by: str = "2026-10-01T00:00:00Z",
) -> Dict[str, Any]:
    """POST /transparency-records"""
    return {
        "district_id": district_id,
        "record_type": record_type,
        "fiscal_year": fiscal_year,
        "scheduled_for": scheduled_for,
        "required_by": required_by,
    }


def advance_transparency_payload(
    to_status: str, document_reference: Any = ...
) -> Dict[str, Any]:
    """POST /transparency-records/{id}/advance"""
    return _prune({"to_status": to_status, "document_reference": document_reference})


# --------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------
def clock_payload(current_utc: str) -> Dict[str, Any]:
    """POST /_clock/set_current_utc"""
    return {"current_utc": current_utc}
