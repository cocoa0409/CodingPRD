"""Request-payload factories for the Global Payroll Aggregation API.

Type discipline, per PRD 2.4 and 2.6:
  * every `_minor` field is emitted as a JSON integer, never a string;
  * percentages and exchange rates are emitted as JSON numbers;
  * `period_start_date`, `period_end_date`, `pay_date`, `value_date`, the cutover
    dates and `local_holidays` are date-only `YYYY-MM-DD` strings;
  * `occurred_at` and `to_iso8601` are full ISO 8601 UTC instants.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DECISION_APPROVE,
    FILING_RESPONSIBILITY_PROVIDER,
    PAY_FREQUENCY_MONTHLY,
    REGION_EU,
    SERVICE_GROSS_TO_NET,
    SERVICE_PAYMENT_DISBURSEMENT,
    SERVICE_STATUTORY_FILING,
    SOURCE_HRIS_CORE,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    FILING_TYPE_SOCIAL_INSURANCE,
)

# ─── Country-element maps by residency region (PRD 3.4) ───────────────────────

EU_ELEMENTS: Dict[str, str] = {
    "tax_id": "DE-TAX-100",
    "social_insurance_no": "DE-SI-100",
    "iban": "DE89370400440532013000",
}
UK_ELEMENTS: Dict[str, str] = {
    "tax_id": "UK-TAX-100",
    "ni_number": "QQ123456C",
    "sort_code": "12-34-56",
    "account_number": "12345678",
}
US_ELEMENTS: Dict[str, str] = {
    "tax_id": "US-TAX-100",
    "ssn_last4": "6789",
    "routing_number": "021000021",
}
APAC_ELEMENTS: Dict[str, str] = {
    "tax_id": "SG-TAX-100",
    "national_id": "S1234567D",
}
LATAM_ELEMENTS: Dict[str, str] = {
    "tax_id": "MX-TAX-100",
    "national_id": "MXNID100",
    "clabe": "002010077777777771",
}

ELEMENTS_BY_REGION: Dict[str, Dict[str, str]] = {
    "EU": EU_ELEMENTS,
    "UK": UK_ELEMENTS,
    "US": US_ELEMENTS,
    "APAC": APAC_ELEMENTS,
    "LATAM": LATAM_ELEMENTS,
}


def _payload(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is the sentinel."""
    result = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            result.pop(key, None)
        else:
            result[key] = value
    return result


class _Omit:
    """Sentinel: pass `OMIT` for a field that must be absent from the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Country profiles (PRD 3.1) ───────────────────────────────────────────────


def country_profile_payload(**overrides: Any) -> Dict[str, Any]:
    """A German payroll country: EUR, EU residency, two required filing types.

    The 2026-09-25 local holiday only ever affects cutoff arithmetic, never a
    statutory `due_at`, so it is safe to carry on the default country.
    """
    return _payload(
        {
            "country_code": "DE",
            "local_currency": "EUR",
            "data_residency_region": REGION_EU,
            "statutory_filing_deadline_days": 10,
            "materiality_pct": 5.0,
            "materiality_floor_minor": 100000,
            "penalty_daily_rate_minor": 15000,
            "required_filing_types": [
                FILING_TYPE_INCOME_TAX_WITHHOLDING,
                FILING_TYPE_SOCIAL_INSURANCE,
            ],
            "local_holidays": ["2026-09-25"],
        },
        overrides,
    )


def single_filing_country_payload(**overrides: Any) -> Dict[str, Any]:
    """A country whose obligation set is a single filing type."""
    return country_profile_payload(
        required_filing_types=[FILING_TYPE_INCOME_TAX_WITHHOLDING],
        local_holidays=OMIT,
        **overrides,
    )


# ─── Providers (PRD 3.1) ──────────────────────────────────────────────────────


def provider_payload(**overrides: Any) -> Dict[str, Any]:
    """The incumbent EU provider, certified for gross-to-net and filing."""
    return _payload(
        {
            "legal_name": "EuroPay GmbH",
            "service_scope": [
                SERVICE_GROSS_TO_NET,
                SERVICE_STATUTORY_FILING,
                SERVICE_PAYMENT_DISBURSEMENT,
            ],
            "data_residency_regions": [REGION_EU],
            "annual_fee_minor": 6000000,
            "indemnity_cap_pct": 25.0,
        },
        overrides,
    )


def rival_provider_payload(**overrides: Any) -> Dict[str, Any]:
    """A second EU-certified provider, usable as a transition target."""
    return _payload(
        {
            "legal_name": "NordPay AB",
            "service_scope": [SERVICE_GROSS_TO_NET, SERVICE_STATUTORY_FILING],
            "data_residency_regions": [REGION_EU],
            "annual_fee_minor": 4000000,
            "indemnity_cap_pct": 30.0,
        },
        overrides,
    )


# ─── Engagements (PRD 3.2) ────────────────────────────────────────────────────


def engagement_payload(
    country_profile_id: str, provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "country_profile_id": country_profile_id,
            "provider_id": provider_id,
            "service_scope": [SERVICE_GROSS_TO_NET, SERVICE_STATUTORY_FILING],
            "filing_responsibility": FILING_RESPONSIBILITY_PROVIDER,
            "data_residency_region": REGION_EU,
            "pay_frequency": PAY_FREQUENCY_MONTHLY,
        },
        overrides,
    )


def residency_approve_payload(
    residency_terms_ref: str = "DPA-DE-2026-01", **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {"decision": DECISION_APPROVE, "residency_terms_ref": residency_terms_ref},
        overrides,
    )


def residency_reject_payload(
    rejection_note: str = "Residency terms not acceptable for this country.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"decision": "REJECT", "rejection_note": rejection_note}, overrides)


def transition_plan_payload(
    incoming_provider_id: str, expected_engagement_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _payload(
        {
            "incoming_provider_id": incoming_provider_id,
            "cutover_period_start_date": "2026-10-01",
            "cutover_period_end_date": "2026-11-01",
            "parallel_run_cycles": 1,
            "expected_engagement_version": expected_engagement_version,
        },
        overrides,
    )


# ─── Local bank accounts (PRD 3.1) ────────────────────────────────────────────


def bank_account_payload(engagement_id: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "engagement_id": engagement_id,
            "account_ref": "DE-ACC-1",
            "account_currency": "EUR",
            "residency_region": REGION_EU,
            "daily_cap_minor": 20000000,
            "settlement_window_hours": 24,
            "buffer_hours": 12,
        },
        overrides,
    )


# ─── Payroll cycles (PRD 3.3) ─────────────────────────────────────────────────


def cycle_payload(engagement_id: str, **overrides: Any) -> Dict[str, Any]:
    """The August 2026 monthly period: half-open 2026-08-01 → 2026-09-01."""
    return _payload(
        {
            "engagement_id": engagement_id,
            "period_label": "2026-08",
            "period_start_date": "2026-08-01",
            "period_end_date": "2026-09-01",
            "pay_date": "2026-08-31",
            "cutoff_lead_working_days": 3,
        },
        overrides,
    )


def september_cycle_payload(engagement_id: str, **overrides: Any) -> Dict[str, Any]:
    """The adjacent September 2026 period: 2026-09-01 → 2026-10-01."""
    return _payload(
        {
            "engagement_id": engagement_id,
            "period_label": "2026-09",
            "period_start_date": "2026-09-01",
            "period_end_date": "2026-10-01",
            "pay_date": "2026-09-30",
            "cutoff_lead_working_days": 3,
        },
        overrides,
    )


def cancel_payload(
    cancel_reason: str = "Period re-dated after an HR calendar correction.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"cancel_reason": cancel_reason}, overrides)


# ─── HR input files (PRD 3.4) ─────────────────────────────────────────────────


def input_file_payload(cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    """An EU extract of 200 records declaring 10 000 000 local minor units."""
    return _payload(
        {
            "cycle_id": cycle_id,
            "source_system": SOURCE_HRIS_CORE,
            "record_count": 200,
            "gross_declared_minor": 10000000,
            "country_elements": dict(EU_ELEMENTS),
            "residency_region_of_transfer": REGION_EU,
        },
        overrides,
    )


def input_file_resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "record_count": 200,
            "gross_declared_minor": 10000000,
            "country_elements": dict(EU_ELEMENTS),
        },
        overrides,
    )


# ─── Gross-to-net runs (PRD 3.5) ──────────────────────────────────────────────


def gtn_run_payload(
    cycle_id: str, input_file_id: str, expected_cycle_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Results matching the declared gross exactly, for 200 paid employees."""
    return _payload(
        {
            "cycle_id": cycle_id,
            "input_file_id": input_file_id,
            "gross_minor": 10000000,
            "net_minor": 6500000,
            "employer_cost_minor": 2000000,
            "provider_fee_minor": 150000,
            "employee_count": 200,
            "expected_cycle_version": expected_cycle_version,
        },
        overrides,
    )


def gtn_resubmit_payload(expected_cycle_version: int, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {
            "gross_minor": 10000000,
            "net_minor": 6500000,
            "employer_cost_minor": 2000000,
            "provider_fee_minor": 150000,
            "employee_count": 200,
            "expected_cycle_version": expected_cycle_version,
        },
        overrides,
    )


def review_approve_payload(
    variance_justification: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"decision": DECISION_APPROVE}
    if variance_justification is not None:
        body["variance_justification"] = variance_justification
    return _payload(body, overrides)


def review_return_payload(
    return_reason: str = "Employer cost totals do not reconcile to the extract.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"decision": "RETURN", "return_reason": return_reason}, overrides)


# ─── Funding instructions (PRD 3.6) ───────────────────────────────────────────


def funding_instruction_payload(
    cycle_id: str, bank_account_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A USD-funded instruction against an EUR account at 0.92 local per source."""
    return _payload(
        {
            "cycle_id": cycle_id,
            "bank_account_id": bank_account_id,
            "value_date": "2026-08-10",
            "funding_currency": "USD",
            "fx_rate": 0.92,
        },
        overrides,
    )


def recall_payload(
    recall_reason: str = "Value date moved after the treasury cut-off.", **overrides: Any
) -> Dict[str, Any]:
    return _payload({"recall_reason": recall_reason}, overrides)


# ─── Statutory filings (PRD 3.7) ──────────────────────────────────────────────


def file_filing_payload(
    submission_ref: str = "AUTH-SUB-0001", **overrides: Any
) -> Dict[str, Any]:
    return _payload({"submission_ref": submission_ref}, overrides)


def confirm_filing_payload(
    confirmation_ref: str = "AUTH-CONF-0001", **overrides: Any
) -> Dict[str, Any]:
    return _payload({"confirmation_ref": confirmation_ref}, overrides)


def penalty_dispute_payload(
    dispute_reason: str = "The authority portal was unavailable on the due date.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"dispute_reason": dispute_reason}, overrides)


def penalty_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _payload(
        {"decision": decision, "decision_note": "Reviewed against the filing log."},
        overrides,
    )


# ─── Service-level incidents (PRD 3.8) ────────────────────────────────────────


def incident_payload(
    engagement_id: str,
    severity: str,
    incident_type: str = "DATA_INCIDENT",
    occurred_at: str = "2026-08-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """An operator-raised incident.

    `DATA_INCIDENT` is the default because the PRD lists it among the two types
    that are only ever raised by an operator, so a manually raised incident of
    that type can never be confused with a system-raised one.
    """
    return _payload(
        {
            "engagement_id": engagement_id,
            "incident_type": incident_type,
            "severity": severity,
            "occurred_at": occurred_at,
        },
        overrides,
    )


def escalate_payload(
    escalation_note: str = "Escalated after the second missed remediation window.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload({"escalation_note": escalation_note}, overrides)


def remediate_payload(
    remediation_ref: str = "REM-0001", **overrides: Any
) -> Dict[str, Any]:
    return _payload({"remediation_ref": remediation_ref}, overrides)


# ─── Audit evidence (PRD 3.9) ─────────────────────────────────────────────────


def audit_evidence_payload(
    cycle_id: str,
    control_ref: str,
    evidence_type: str = "DOCUMENT_HASH",
    payload_hash: str = "aaaabbbbccccdddd",
    **overrides: Any,
) -> Dict[str, Any]:
    return _payload(
        {
            "cycle_id": cycle_id,
            "control_ref": control_ref,
            "evidence_type": evidence_type,
            "payload_hash": payload_hash,
        },
        overrides,
    )


def pagination_params(
    limit: Optional[int] = None, offset: Optional[int] = None, **filters: Any
) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    for key, value in filters.items():
        if value is not None:
            params[key] = value
    return params


def elements_for_region(region: str, **overrides: Any) -> Dict[str, str]:
    """The required country-element map for a region, with optional overrides."""
    elements: Dict[str, str] = dict(ELEMENTS_BY_REGION[region])
    for key, value in overrides.items():
        if value is _OMIT:
            elements.pop(key, None)
        else:
            elements[key] = value
    return elements


def required_element_keys(region: str) -> List[str]:
    return list(ELEMENTS_BY_REGION[region].keys())
