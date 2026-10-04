"""Request payload builders.

Each builder returns a valid body for one write endpoint, with sensible
defaults that any test can override by keyword. Only client-supplied fields
are emitted; computed fields are never sent.
"""

from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


def dca_payload(
    docket_number: str = "52-000",
    reactor_model: str = TEST_DEFAULTS["REACTOR_MODEL"],
    target_power_mwt: int = TEST_DEFAULTS["TARGET_POWER_MWT"],
    plant_net_capacity_mw: int = TEST_DEFAULTS["PLANT_NET_CAPACITY_MW"],
    source_term_fraction: float = TEST_DEFAULTS["SOURCE_TERM_FRACTION"],
    site_boundary_miles: float = TEST_DEFAULTS["SITE_BOUNDARY_MILES"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "docket_number": docket_number,
        "reactor_model": reactor_model,
        "target_power_mwt": target_power_mwt,
        "plant_net_capacity_mw": plant_net_capacity_mw,
        "source_term_fraction": source_term_fraction,
        "site_boundary_miles": site_boundary_miles,
    }
    payload.update(overrides)
    return payload


def sar_payload(
    section_code: str = "CH03",
    revision_number: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "section_code": section_code,
        "revision_number": revision_number,
    }
    payload.update(overrides)
    return payload


def rai_payload(
    sar_section_code: str = "CH03",
    question_text: str = "Please clarify the analysis.",
    due_date: str = "2027-01-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sar_section_code": sar_section_code,
        "question_text": question_text,
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload


def rai_response_payload(
    response_text: str = "Response attached.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"response_text": response_text}
    payload.update(overrides)
    return payload


def test_program_payload(
    program_code: str = "TP-1",
    required_tests: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_code": program_code,
        "required_tests": required_tests,
    }
    payload.update(overrides)
    return payload


def test_result_payload(
    outcome: str = "PASS",
    run_at: str = "2026-09-01T00:00:00Z",
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome, "run_at": run_at}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


def vendor_payload(
    name: str = "Acme Nuclear",
    capability_scope: str = "pressure vessels",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "capability_scope": capability_scope}
    payload.update(overrides)
    return payload


def qualification_payload(
    audit_date: str = "2026-10-01T00:00:00Z",
    defects_found: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "audit_date": audit_date,
        "defects_found": defects_found,
    }
    payload.update(overrides)
    return payload


def component_lot_payload(
    vendor_id: str,
    program_id: str,
    component_type: str = "valve",
    quantity: int = 1,
    nuclear_grade: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "program_id": program_id,
        "component_type": component_type,
        "quantity": quantity,
    }
    if nuclear_grade is not None:
        payload["nuclear_grade"] = nuclear_grade
    payload.update(overrides)
    return payload


def site_permit_payload(
    permit_type: str,
    dca_id: str,
    site_name: str = "Test Site",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "permit_type": permit_type,
        "dca_id": dca_id,
        "site_name": site_name,
    }
    payload.update(overrides)
    return payload


def hearing_payload(
    scheduled_at: str = "2026-10-01T00:00:00Z",
    location: str = "Town Hall",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"scheduled_at": scheduled_at, "location": location}
    payload.update(overrides)
    return payload


def subscription_payload(
    utility_id: str,
    committed_mw: int,
    price_per_mwh_usd: float = TEST_DEFAULTS["PRICE_PER_MWH_USD"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "utility_id": utility_id,
        "committed_mw": committed_mw,
        "price_per_mwh_usd": price_per_mwh_usd,
    }
    payload.update(overrides)
    return payload


def subscription_withdraw_payload(
    expected_cost_share_agreement_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_cost_share_agreement_version": expected_cost_share_agreement_version,
    }
    payload.update(overrides)
    return payload


def cost_share_agreement_payload(
    dca_id: str,
    total_cost_usd: int,
    gov_contribution_usd: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dca_id": dca_id,
        "total_cost_usd": total_cost_usd,
        "gov_contribution_usd": gov_contribution_usd,
    }
    payload.update(overrides)
    return payload


def escalate_payload(overrun_usd: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"overrun_usd": overrun_usd}
    payload.update(overrides)
    return payload


def workforce_pipeline_payload(
    cohort_code: str = "C-1",
    required_operators: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cohort_code": cohort_code,
        "required_operators": required_operators,
    }
    payload.update(overrides)
    return payload


def operator_license_payload(
    candidate_name: str = "Op One",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"candidate_name": candidate_name}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
