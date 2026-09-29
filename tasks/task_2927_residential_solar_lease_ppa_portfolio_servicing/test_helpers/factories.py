"""Request-payload builders.

Every money field is a JSON integer of whole cents or whole millicents, per
§2.6: "Every monetary amount in this system is an integer number of whole
cents", and rates are "integer millicents per kilowatt-hour". Calendar dates are
sent date-only; instants are sent as full ISO-8601 instants.

The literal profiles below are the shared scenario terms used across the suite;
individual tests override only the fields their rule is about.
"""

import itertools

from . import constants as C
from .types import Payload

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short discriminator for fields the PRD requires to be unique."""
    return f"{next(_counter):04d}"


# ---------------------------------------------------------------------------
# Homeowners (§3.1)
# ---------------------------------------------------------------------------
def homeowner_payload(
    full_name: str = "Dana Reyes",
    email: str = None,
    state_code: str = "CA",
    fico_score: int = 742,
    dti_ratio: float = 0.28,
    monthly_income_cents: int = 1150000,
    **overrides,
) -> Payload:
    payload = {
        "full_name": full_name,
        "email": email if email is not None else f"dana.reyes.{unique_suffix()}@example.com",
        "state_code": state_code,
        "fico_score": fico_score,
        "dti_ratio": dti_ratio,
        "monthly_income_cents": monthly_income_cents,
    }
    payload.update(overrides)
    return payload


def buyer_payload(
    full_name: str = "Priya Nandan",
    email: str = None,
    state_code: str = "CA",
    fico_score: int = 705,
    dti_ratio: float = 0.31,
    monthly_income_cents: int = 980000,
    **overrides,
) -> Payload:
    """The assuming buyer registered "again for an assuming buyer" (§3.1)."""
    return homeowner_payload(
        full_name=full_name,
        email=email if email is not None else f"priya.nandan.{unique_suffix()}@example.com",
        state_code=state_code,
        fico_score=fico_score,
        dti_ratio=dti_ratio,
        monthly_income_cents=monthly_income_cents,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Utility tariffs (§3.1)
# ---------------------------------------------------------------------------
def tariff_payload(
    utility_code: str = "PGE",
    tariff_code: str = None,
    generation: str = C.GEN_NEM_2,
    retail_rate_per_kwh_millicents: int = 32500,
    export_credit_rate_per_kwh_millicents: int = 28000,
    monthly_fixed_charge_cents: int = 1500,
    effective_from_date: str = "2020-04-15",
    grandfathers_predecessors: bool = True,
    **overrides,
) -> Payload:
    payload = {
        "utility_code": utility_code,
        "tariff_code": tariff_code if tariff_code is not None else f"NEM2-ETOUC-{unique_suffix()}",
        "generation": generation,
        "retail_rate_per_kwh_millicents": retail_rate_per_kwh_millicents,
        "export_credit_rate_per_kwh_millicents": export_credit_rate_per_kwh_millicents,
        "monthly_fixed_charge_cents": monthly_fixed_charge_cents,
        "effective_from_date": effective_from_date,
        "grandfathers_predecessors": grandfathers_predecessors,
    }
    payload.update(overrides)
    return payload


def successor_tariff_payload(
    grandfathers_predecessors: bool = True,
    tariff_code: str = None,
    utility_code: str = "PGE",
    generation: str = C.GEN_NEM_3,
    retail_rate_per_kwh_millicents: int = 38000,
    export_credit_rate_per_kwh_millicents: int = 7500,
    monthly_fixed_charge_cents: int = 2400,
    effective_from_date: str = "2023-04-15",
    **overrides,
) -> Payload:
    """A `NEM_3` successor schedule: dearer imports, far cheaper exports."""
    return tariff_payload(
        utility_code=utility_code,
        tariff_code=tariff_code
        if tariff_code is not None
        else f"NEM3-SUCCESSOR-{unique_suffix()}",
        generation=generation,
        retail_rate_per_kwh_millicents=retail_rate_per_kwh_millicents,
        export_credit_rate_per_kwh_millicents=export_credit_rate_per_kwh_millicents,
        monthly_fixed_charge_cents=monthly_fixed_charge_cents,
        effective_from_date=effective_from_date,
        grandfathers_predecessors=grandfathers_predecessors,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Agreements (§3.1)
# ---------------------------------------------------------------------------
def ppa_agreement_payload(
    homeowner_id: str,
    tariff_id: str,
    site_address: str = "918 Alder Way, Fremont, CA",
    state_code: str = "CA",
    term_years: int = 20,
    contract_start_date: str = "2025-01-01",
    escalator_pct: float = 0.029,
    guaranteed_annual_kwh: int = 9600,
    system_dc_kw: float = 7.2,
    base_ppa_rate_per_kwh_millicents: int = 14750,
    **overrides,
) -> Payload:
    payload = {
        "homeowner_id": homeowner_id,
        "tariff_id": tariff_id,
        "site_address": site_address,
        "state_code": state_code,
        "product_type": C.PRODUCT_PPA,
        "term_years": term_years,
        "contract_start_date": contract_start_date,
        "escalator_pct": escalator_pct,
        "guaranteed_annual_kwh": guaranteed_annual_kwh,
        "system_dc_kw": system_dc_kw,
        "base_ppa_rate_per_kwh_millicents": base_ppa_rate_per_kwh_millicents,
    }
    payload.update(overrides)
    return payload


def lease_agreement_payload(
    homeowner_id: str,
    tariff_id: str,
    site_address: str = "51 Marsh Ln, Fremont, CA",
    state_code: str = "CA",
    term_years: int = 20,
    contract_start_date: str = "2025-01-01",
    escalator_pct: float = 0.019,
    guaranteed_annual_kwh: int = 8400,
    system_dc_kw: float = 6.4,
    base_monthly_lease_cents: int = 12900,
    **overrides,
) -> Payload:
    payload = {
        "homeowner_id": homeowner_id,
        "tariff_id": tariff_id,
        "site_address": site_address,
        "state_code": state_code,
        "product_type": C.PRODUCT_LEASE,
        "term_years": term_years,
        "contract_start_date": contract_start_date,
        "escalator_pct": escalator_pct,
        "guaranteed_annual_kwh": guaranteed_annual_kwh,
        "system_dc_kw": system_dc_kw,
        "base_monthly_lease_cents": base_monthly_lease_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Metered months (§3.3)
# ---------------------------------------------------------------------------
def period_payload(
    agreement_id: str,
    period_year: int,
    period_month: int,
    metered_kwh: int,
    **overrides,
) -> Payload:
    payload = {
        "agreement_id": agreement_id,
        "period_year": period_year,
        "period_month": period_month,
        "metered_kwh": metered_kwh,
    }
    payload.update(overrides)
    return payload


def reconcile_payload(issue_credit: bool = False) -> Payload:
    return {"issue_credit": issue_credit}


# ---------------------------------------------------------------------------
# True-ups (§3.4)
# ---------------------------------------------------------------------------
def true_up_payload(
    agreement_id: str,
    contract_year: int,
    method: str,
    expected_agreement_version: int,
    **overrides,
) -> Payload:
    payload = {
        "agreement_id": agreement_id,
        "contract_year": contract_year,
        "method": method,
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Monitoring (§3.5)
# ---------------------------------------------------------------------------
def outage_event_payload(
    agreement_id: str,
    detected_at: str,
    inverter_serial: str = "INV-88213",
    outage_type: str = C.OUTAGE_TYPE_INVERTER_FAULT,
    **overrides,
) -> Payload:
    payload = {
        "agreement_id": agreement_id,
        "inverter_serial": inverter_serial,
        "outage_type": outage_type,
        "detected_at": detected_at,
    }
    payload.update(overrides)
    return payload


def truck_roll_payload(
    outage_event_id: str,
    scheduled_window_start: str,
    scheduled_window_end: str,
    expected_outage_event_version: int,
    technician_code: str = "TECH-4471",
    **overrides,
) -> Payload:
    payload = {
        "outage_event_id": outage_event_id,
        "technician_code": technician_code,
        "scheduled_window_start": scheduled_window_start,
        "scheduled_window_end": scheduled_window_end,
        "expected_outage_event_version": expected_outage_event_version,
    }
    payload.update(overrides)
    return payload


def complete_payload(disposition: str, root_cause: str = None) -> Payload:
    payload: Payload = {"disposition": disposition}
    if root_cause is not None:
        payload["root_cause"] = root_cause
    return payload


# ---------------------------------------------------------------------------
# Roof work (§3.7)
# ---------------------------------------------------------------------------
def roof_work_order_payload(
    agreement_id: str,
    requested_removal_date: str,
    reinstall_target_date: str,
    roofer_company: str = "Bayline Roofing",
    **overrides,
) -> Payload:
    payload = {
        "agreement_id": agreement_id,
        "requested_removal_date": requested_removal_date,
        "reinstall_target_date": reinstall_target_date,
        "roofer_company": roofer_company,
    }
    payload.update(overrides)
    return payload


def quote_payload(quote_cents: int = 480000) -> Payload:
    return {"quote_cents": quote_cents}


# ---------------------------------------------------------------------------
# Transfers (§3.8)
# ---------------------------------------------------------------------------
def assumption_payload(
    agreement_id: str, closing_date: str, buyer_homeowner_id: str, **overrides
) -> Payload:
    payload = {
        "agreement_id": agreement_id,
        "transfer_type": C.TYPE_ASSUMPTION,
        "closing_date": closing_date,
        "buyer_homeowner_id": buyer_homeowner_id,
    }
    payload.update(overrides)
    return payload


def prepayment_payload(agreement_id: str, closing_date: str, **overrides) -> Payload:
    payload = {
        "agreement_id": agreement_id,
        "transfer_type": C.TYPE_PREPAYMENT,
        "closing_date": closing_date,
    }
    payload.update(overrides)
    return payload


def relocation_payload(
    agreement_id: str,
    closing_date: str,
    new_site_address: str = "77 Bayside Rd, Alameda, CA",
    **overrides,
) -> Payload:
    payload = {
        "agreement_id": agreement_id,
        "transfer_type": C.TYPE_RELOCATION,
        "closing_date": closing_date,
        "new_site_address": new_site_address,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# UCC filings (§3.9)
# ---------------------------------------------------------------------------
def ucc_filing_payload(
    agreement_id: str,
    filed_date: str,
    filing_number: str = None,
    jurisdiction_code: str = "CA-ALAMEDA",
    filing_type: str = C.FILING_TYPE_FIXTURE,
    **overrides,
) -> Payload:
    payload = {
        "agreement_id": agreement_id,
        "filing_number": filing_number
        if filing_number is not None
        else f"UCC-{unique_suffix()}",
        "jurisdiction_code": jurisdiction_code,
        "filing_type": filing_type,
        "filed_date": filed_date,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# End-of-term elections (§3.10)
# ---------------------------------------------------------------------------
def election_payload(agreement_id: str, election_type: str, **overrides) -> Payload:
    payload = {"agreement_id": agreement_id, "election_type": election_type}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Warranty claims (§3.6)
# ---------------------------------------------------------------------------
def warranty_claim_payload(
    truck_roll_id: str,
    component_type: str = C.COMPONENT_INVERTER,
    manufacturer_code: str = "SOLAREDGE",
    serial_number: str = "SE-99120-A",
    component_install_date: str = "2025-01-01",
    claim_amount_cents: int = 52000,
    **overrides,
) -> Payload:
    payload = {
        "truck_roll_id": truck_roll_id,
        "component_type": component_type,
        "manufacturer_code": manufacturer_code,
        "serial_number": serial_number,
        "component_install_date": component_install_date,
        "claim_amount_cents": claim_amount_cents,
    }
    payload.update(overrides)
    return payload


def info_request_payload(note: str = "Send the inverter event log for the fault window.") -> Payload:
    return {"info_request_note": note}


def approval_payload(approved_amount_cents: int) -> Payload:
    return {"approved_amount_cents": approved_amount_cents}
