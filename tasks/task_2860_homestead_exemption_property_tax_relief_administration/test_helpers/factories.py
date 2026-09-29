"""Request-payload builders with PRD-legal defaults.

Every builder accepts keyword overrides that are merged over the defaults, so a
test can vary exactly the field under examination and leave everything else at a
value the screening order is known to accept.

Money is always an ``int`` count of cents and every rate is an ``int`` count of
basis points.  Calendar-date fields carry ``YYYY-MM-DD`` strings; instant fields
carry a full ISO-8601 UTC instant.
"""

from typing import Any, Dict, Optional

from .constants import (
    ADDR_CEDAR,
    ADDR_FARM,
    ADDR_OAK,
    ADDR_PINE,
    DEFAULT_ASSESSMENT_CAP_PCT_BPS,
)

__all__ = [
    "OMIT",
    "homestead_basic_program",
    "senior_freeze_program",
    "disability_income_program",
    "veteran_disability_program",
    "agricultural_use_program",
    "parcel",
    "farm_parcel",
    "destination_parcel",
    "second_destination_parcel",
    "taxpayer_account",
    "ownership_record",
    "application",
    "verification_check",
    "approve_determination",
    "deny_determination",
    "request_info_determination",
    "respond_info_payload",
    "income_certification",
    "registry_record",
    "port_request",
    "compliance_action",
    "retroactive_claim",
    "claim_decision",
    "fraud_case",
    "fraud_decision",
    "recovery_action",
    "hearing_docket",
    "appeal",
    "hearing_slot",
    "appeal_decision",
    "assessment_roll_run",
]


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    """Sentinel that removes a defaulted key from a payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


_OMIT = _Omit()
OMIT = _OMIT


# ------------------------------------------------------------- programmes


def homestead_basic_program(**overrides: Any) -> Dict[str, Any]:
    """A plain residence programme: no income test, no freeze, first in the waterfall."""
    return _merge(
        {
            "program_code": "HOMESTEAD_BASIC",
            "name": "Basic Homestead",
            "relief_pct_bps": 2500,
            "max_exempt_value_cents": 10000000,
            "statutory_lookback_years": 3,
            "penalty_pct_bps": 1000,
            "interest_pct_bps_per_year": 500,
            "priority_rank": 10,
        },
        overrides,
    )


def senior_freeze_program(**overrides: Any) -> Dict[str, Any]:
    """A freeze-enabled programme, so approval pins the assessed value."""
    return _merge(
        {
            "program_code": "SENIOR_FREEZE",
            "name": "Senior Valuation Freeze",
            "relief_pct_bps": 1000,
            "max_exempt_value_cents": 5000000,
            "statutory_lookback_years": 3,
            "penalty_pct_bps": 1000,
            "interest_pct_bps_per_year": 500,
            "priority_rank": 20,
            "freeze_enabled": True,
        },
        overrides,
    )


def disability_income_program(**overrides: Any) -> Dict[str, Any]:
    """An income-tested programme with both a income ceiling and an asset ceiling."""
    return _merge(
        {
            "program_code": "DISABILITY_INCOME",
            "name": "Disability Income Relief",
            "relief_pct_bps": 3000,
            "max_exempt_value_cents": 12000000,
            "statutory_lookback_years": 3,
            "penalty_pct_bps": 1000,
            "interest_pct_bps_per_year": 500,
            "priority_rank": 30,
            "income_limit_cents": 6000000,
            "asset_limit_cents": 4000000,
            "requires_income_certification": True,
            "recertification_required": True,
        },
        overrides,
    )


def veteran_disability_program(**overrides: Any) -> Dict[str, Any]:
    """A programme whose relief is scaled by the claimant's disability rating."""
    return _merge(
        {
            "program_code": "VETERAN_DISABILITY",
            "name": "Veteran Disability Exemption",
            "relief_pct_bps": 4000,
            "max_exempt_value_cents": 20000000,
            "statutory_lookback_years": 3,
            "penalty_pct_bps": 1000,
            "interest_pct_bps_per_year": 500,
            "priority_rank": 50,
        },
        overrides,
    )


def agricultural_use_program(**overrides: Any) -> Dict[str, Any]:
    """A non-residence programme, last in the waterfall."""
    return _merge(
        {
            "program_code": "AGRICULTURAL_USE",
            "name": "Agricultural Use Valuation",
            "relief_pct_bps": 2000,
            "max_exempt_value_cents": 8000000,
            "statutory_lookback_years": 2,
            "penalty_pct_bps": 1500,
            "interest_pct_bps_per_year": 500,
            "priority_rank": 40,
        },
        overrides,
    )


# ----------------------------------------------------------------- parcels


def parcel(**overrides: Any) -> Dict[str, Any]:
    """A 2026 parcel whose base-year value is six years old.

    With base 30000000, six elapsed years and a 200 bps annual cap the capped
    value is 33600000 while the market value is 40000000, so the cap is the
    controlling basis.
    """
    return _merge(
        {
            "apn": "P-0001",
            "situs_address_normalized": ADDR_OAK,
            "county_zone": "NORTH",
            "tax_year": 2026,
            "base_year": 2020,
            "base_year_value_cents": 30000000,
            "market_value_cents": 40000000,
            "assessment_cap_pct_bps": DEFAULT_ASSESSMENT_CAP_PCT_BPS,
        },
        overrides,
    )


def farm_parcel(**overrides: Any) -> Dict[str, Any]:
    """A second parcel with a recent base year, so its capped value is 20800000."""
    return _merge(
        {
            "apn": "P-0002",
            "situs_address_normalized": ADDR_FARM,
            "county_zone": "NORTH",
            "tax_year": 2026,
            "base_year": 2024,
            "base_year_value_cents": 20000000,
            "market_value_cents": 25000000,
            "assessment_cap_pct_bps": DEFAULT_ASSESSMENT_CAP_PCT_BPS,
        },
        overrides,
    )


def destination_parcel(**overrides: Any) -> Dict[str, Any]:
    """A portability destination: base year equals the tax year, so no cap growth."""
    return _merge(
        {
            "apn": "P-0003",
            "situs_address_normalized": ADDR_PINE,
            "county_zone": "NORTH",
            "tax_year": 2026,
            "base_year": 2026,
            "base_year_value_cents": 40000000,
            "market_value_cents": 45000000,
            "assessment_cap_pct_bps": DEFAULT_ASSESSMENT_CAP_PCT_BPS,
        },
        overrides,
    )


def second_destination_parcel(**overrides: Any) -> Dict[str, Any]:
    """A second portability destination identical in valuation to the first."""
    return _merge(
        {
            "apn": "P-0004",
            "situs_address_normalized": ADDR_CEDAR,
            "county_zone": "NORTH",
            "tax_year": 2026,
            "base_year": 2026,
            "base_year_value_cents": 40000000,
            "market_value_cents": 45000000,
            "assessment_cap_pct_bps": DEFAULT_ASSESSMENT_CAP_PCT_BPS,
        },
        overrides,
    )


# ------------------------------------------------------ taxpayer accounts


def taxpayer_account(**overrides: Any) -> Dict[str, Any]:
    """A claimant born in 1955, so the senior age test is satisfied in 2026."""
    return _merge(
        {
            "full_name": "TERESA OWNER",
            "date_of_birth": "1955-03-10",
            "ssn_last4": "4321",
            "mailing_address_normalized": ADDR_OAK,
        },
        overrides,
    )


# ------------------------------------------------------ ownership records


def ownership_record(
    parcel_id: str, taxpayer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A whole-share, open-ended primary residence record from the deed registry.

    A deed-registry record is VERIFIED the moment it is created, and an omitted
    end date leaves the occupancy interval open.
    """
    return _merge(
        {
            "parcel_id": parcel_id,
            "taxpayer_id": taxpayer_id,
            "ownership_pct_bps": 10000,
            "deed_recorded_date": "2019-06-01",
            "occupancy_type": "PRIMARY_RESIDENCE",
            "occupancy_start_date": "2019-06-01",
            "source_system": "DEED_REGISTRY",
        },
        overrides,
    )


# ------------------------------------------------ exemption applications


def application(
    parcel_id: str, taxpayer_id: str, program_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A 2026 application whose claimed address matches the parcel situs address."""
    return _merge(
        {
            "parcel_id": parcel_id,
            "taxpayer_id": taxpayer_id,
            "program_id": program_id,
            "tax_year": 2026,
            "claimed_occupancy_date": "2019-06-01",
            "claimed_address_normalized": ADDR_OAK,
        },
        overrides,
    )


def verification_check(source: str) -> Dict[str, Any]:
    """A cross-match request against one external data source."""
    return {"source": source}


def approve_determination(expected_parcel_version: int, **overrides: Any) -> Dict[str, Any]:
    """An APPROVE determination carrying the parcel version the reviewer read."""
    return _merge(
        {"outcome": "APPROVE", "expected_parcel_version": expected_parcel_version},
        overrides,
    )


def deny_determination(
    expected_parcel_version: int,
    denial_reason: str = "Residency could not be verified.",
    **overrides: Any,
) -> Dict[str, Any]:
    """A DENY determination, which mails an appealable denial notice."""
    return _merge(
        {
            "outcome": "DENY",
            "expected_parcel_version": expected_parcel_version,
            "denial_reason": denial_reason,
        },
        overrides,
    )


def request_info_determination(
    expected_parcel_version: int, **overrides: Any
) -> Dict[str, Any]:
    """A REQUEST_INFO determination, which returns the application to the taxpayer."""
    return _merge(
        {"outcome": "REQUEST_INFO", "expected_parcel_version": expected_parcel_version},
        overrides,
    )


def respond_info_payload(
    claimed_occupancy_date: str,
    claimed_address_normalized: str = ADDR_OAK,
    **overrides: Any,
) -> Dict[str, Any]:
    """A taxpayer's answer to an information request.

    The answer restates both the claimed address and the claimed occupancy date,
    and both replace the values previously on file.
    """
    return _merge(
        {
            "claimed_address_normalized": claimed_address_normalized,
            "claimed_occupancy_date": claimed_occupancy_date,
        },
        overrides,
    )


# ------------------------------------------------- income certifications


def income_certification(taxpayer_id: str, **overrides: Any) -> Dict[str, Any]:
    """A 2026 certification comfortably inside a 6000000 income ceiling."""
    return _merge(
        {
            "taxpayer_id": taxpayer_id,
            "certification_year": 2026,
            "household_income_cents": 3000000,
            "countable_asset_cents": 1500000,
            "household_size": 3,
            "recertification_due_date": "2026-12-31",
        },
        overrides,
    )


# ------------------------------------------------------ registry records


def registry_record(taxpayer_id: str, source: str, **overrides: Any) -> Dict[str, Any]:
    """An external data-source row for cross-matching.

    Address-bearing sources carry ``address_normalized``; the income source
    carries ``reported_income_cents`` instead.
    """
    base: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "source": source,
        "record_effective_date": "2026-01-05",
    }
    if source == "INCOME_DOR":
        base["reported_income_cents"] = 3000000
    else:
        base["address_normalized"] = ADDR_OAK
    return _merge(base, overrides)


# ------------------------------------------------------------ portability


def port_request(
    destination_parcel_id: str,
    transfer_value_cents: int,
    expected_grant_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A portability transfer of frozen value to another parcel of the same owner."""
    return _merge(
        {
            "destination_parcel_id": destination_parcel_id,
            "transfer_value_cents": transfer_value_cents,
            "expected_grant_version": expected_grant_version,
        },
        overrides,
    )


def compliance_action(action: str, reason: str) -> Dict[str, Any]:
    """A REINSTATE or REVOKE action on a grant."""
    return {"action": action, "reason": reason}


# ------------------------------------------------------ retroactive claims


def retroactive_claim(grant_id: str, **overrides: Any) -> Dict[str, Any]:
    """A 2026 filing reaching back to 2023, the earliest year a 3-year lookback allows."""
    return _merge(
        {
            "grant_id": grant_id,
            "filing_tax_year": 2026,
            "requested_start_tax_year": 2023,
        },
        overrides,
    )


def claim_decision(action: str, note: str = "Reviewed against the roll.") -> Dict[str, Any]:
    """An APPROVE or DENY decision on a pending retroactive claim."""
    return {"action": action, "note": note}


# ------------------------------------------------------------ fraud cases


def fraud_case(grant_id: str, taxpayer_id: str, **overrides: Any) -> Dict[str, Any]:
    """A case alleging two improper years, assessed in 2026."""
    return _merge(
        {
            "taxpayer_id": taxpayer_id,
            "grant_id": grant_id,
            "improper_start_tax_year": 2024,
            "improper_end_tax_year": 2025,
            "assessment_tax_year": 2026,
        },
        overrides,
    )


def fraud_decision(action: str, findings: str = "Cross-match findings recorded.") -> Dict[str, Any]:
    """A SUBSTANTIATE or CLEAR decision on an open investigation."""
    return {"action": action, "findings": findings}


def recovery_action(
    action: str, amount_cents: Optional[int] = None, reason: str = "Recovery action."
) -> Dict[str, Any]:
    """A PAY or ABATE action against an assessed recovery balance."""
    payload: Dict[str, Any] = {"action": action, "reason": reason}
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    return payload


# --------------------------------------------------- dockets and appeals


def hearing_docket(**overrides: Any) -> Dict[str, Any]:
    """An eight-hour session on 2026-09-10 with room for four appeals."""
    return _merge(
        {
            "docket_date": "2026-09-10",
            "session_start_utc": "2026-09-10T09:00:00Z",
            "session_end_utc": "2026-09-10T17:00:00Z",
            "capacity": 4,
        },
        overrides,
    )


def appeal(notice_id: str, **overrides: Any) -> Dict[str, Any]:
    """An appeal against a mailed notice."""
    return _merge(
        {
            "notice_id": notice_id,
            "grounds": "Occupancy evidence was submitted on time.",
        },
        overrides,
    )


def hearing_slot(
    docket_id: str, hearing_start_utc: str, hearing_end_utc: str
) -> Dict[str, Any]:
    """A reservation request for one hearing interval on a docket."""
    return {
        "docket_id": docket_id,
        "hearing_start_utc": hearing_start_utc,
        "hearing_end_utc": hearing_end_utc,
    }


def appeal_decision(action: str, findings: str = "Findings of the hearing.") -> Dict[str, Any]:
    """A GRANT, DENY, DISMISS or CONTINUE decision on a scheduled appeal."""
    return {"action": action, "findings": findings}


# ------------------------------------------------- assessment roll runs


def assessment_roll_run(target_tax_year: int, **overrides: Any) -> Dict[str, Any]:
    """A roll advance to the given tax year."""
    return _merge({"target_tax_year": target_tax_year}, overrides)
