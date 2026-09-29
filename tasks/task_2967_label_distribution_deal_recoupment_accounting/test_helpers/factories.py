"""
Request-payload builders for the Label Distribution Recoupment API.

Conventions every caller must know:

* **Money is always a JSON integer of whole cents.** Never pass a string.
* **Percentages are always ``decimal.Decimal``.** PRD Section 2.6 rejects a
  percentage "that is not written with four decimals", and a Python float cannot
  carry that distinction, so ``api_client`` serialises Decimals with their exact
  digits. Every factory normalises a percentage argument through ``_pct_arg``:
  an ``int``/``float``/``str`` is quantised to four decimal places, while a
  ``Decimal`` is passed through **verbatim** - which is how a test deliberately
  sends the two-decimal ``Decimal("0.15")`` that the PRD requires be rejected.
* **Optional fields are omitted when ``None``** so that the PRD's
  omission-defaults can be exercised. Pass ``ABSENT`` to force removal of a
  field a factory would otherwise include, and pass ``None`` inside
  ``**overrides`` to send an explicit JSON ``null``.
"""

import itertools
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence

from .constants import (
    BASIS_VARIANT_FINAL,
    DEAL_TYPE_DISTRIBUTION_FEE,
    DEAL_TYPE_LABEL_SERVICES,
    DEAL_TYPE_PROFIT_SHARE,
    DEFAULT_DSP_CODE,
    FORMAT_DIGITAL,
    PCT_QUANTUM,
    SPEND_CATEGORY_DIGITAL_ADS,
    TIER_PREMIUM,
)


class _Absent:
    """Sentinel meaning "leave this key out of the payload entirely"."""

    def __repr__(self):  # pragma: no cover - debugging aid only
        return "ABSENT"


ABSENT = _Absent()


def pct(value: Any) -> Decimal:
    """A percentage with exactly the digits written, e.g. ``pct("0.15")`` sends
    ``0.15`` - the malformed spelling the PRD rejects."""
    return Decimal(str(value))


def pct4(value: Any) -> Decimal:
    """A percentage forced to exactly four decimal places, e.g. 0.1500."""
    return Decimal(str(value)).quantize(PCT_QUANTUM)


def _pct_arg(value: Any) -> Any:
    """Decimal in -> Decimal out untouched; anything else is quantised to 4 dp."""
    if value is None or isinstance(value, _Absent):
        return value
    if isinstance(value, Decimal):
        return value
    return pct4(value)


def _compose(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return {k: v for k, v in payload.items() if not isinstance(v, _Absent)}


def _drop_none(payload: Dict[str, Any], *optional: str) -> Dict[str, Any]:
    for field in optional:
        if field in payload and payload[field] is None:
            del payload[field]
    return payload


# ---------------------------------------------------------------------------
# Unique literal generators (a fresh server per test, but still unique in-test)
# ---------------------------------------------------------------------------

_upc_counter = itertools.count(1)
_email_counter = itertools.count(1)


def next_upc() -> str:
    """A 12-digit ASCII UPC - the PRD's declared width is 12 to 14 digits."""
    return "01234567%04d" % next(_upc_counter)


def next_email(prefix: str = "artist") -> str:
    return "%s-%04d@example.com" % (prefix, next(_email_counter))


# ---------------------------------------------------------------------------
# Clock (PRD Section 2.5)
# ---------------------------------------------------------------------------

def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Distributor / Artist (PRD Section 3.1)
# ---------------------------------------------------------------------------

def distributor_payload(
    name: str = "Vector Digital",
    legal_entity: str = "Vector Digital LLC",
    default_returns_reserve_pct: Any = None,
    **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"name": name, "legal_entity": legal_entity}
    if default_returns_reserve_pct is not None:
        base["default_returns_reserve_pct"] = _pct_arg(default_returns_reserve_pct)
    return _compose(base, overrides)


def artist_payload(
    legal_name: str = "Nadia Frost",
    email: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    base = {
        "legal_name": legal_name,
        "email": email if email is not None else next_email(),
    }
    return _compose(base, overrides)


# ---------------------------------------------------------------------------
# DistributionDeal (PRD Section 3.1)
# ---------------------------------------------------------------------------

def deal_payload(
    distributor_id: str,
    deal_type: str = DEAL_TYPE_DISTRIBUTION_FEE,
    distribution_fee_pct: Any = ABSENT,
    profit_share_label_pct: Any = ABSENT,
    services_fee_pct: Any = ABSENT,
    services_monthly_fee_cents: Any = ABSENT,
    term_start_date: str = "2026-01-01",
    term_end_date: str = "2026-12-31",
    territory_codes: Sequence[str] = ("US",),
    cross_collateralized: bool = True,
    advance_amount_cents: int = 0,
    marketing_budget_cents: int = 0,
    objection_window_days: Optional[int] = None,
    post_term_collection_days: Optional[int] = None,
    **overrides: Any
) -> Dict[str, Any]:
    """Build a deal payload whose fee fields match ``deal_type``.

    "The structure decides which fee fields the payload must carry and which it
    must leave out, and the pairing is strict in both directions." When no fee
    field is passed explicitly, the type's own required fields are supplied with
    conventional defaults and the other structures' fields are left out. Pass a
    fee field explicitly - including one the chosen type does not use - to build
    a deliberately mismatched pairing.
    """
    base: Dict[str, Any] = {
        "distributor_id": distributor_id,
        "deal_type": deal_type,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
        "territory_codes": list(territory_codes),
        "cross_collateralized": cross_collateralized,
        "advance_amount_cents": advance_amount_cents,
        "marketing_budget_cents": marketing_budget_cents,
    }

    explicit = {
        "distribution_fee_pct": distribution_fee_pct,
        "profit_share_label_pct": profit_share_label_pct,
        "services_fee_pct": services_fee_pct,
        "services_monthly_fee_cents": services_monthly_fee_cents,
    }
    any_explicit = any(not isinstance(v, _Absent) for v in explicit.values())

    if any_explicit:
        for field, value in explicit.items():
            if isinstance(value, _Absent):
                continue
            if field == "services_monthly_fee_cents":
                base[field] = value
            else:
                base[field] = _pct_arg(value)
    elif deal_type == DEAL_TYPE_DISTRIBUTION_FEE:
        base["distribution_fee_pct"] = pct4("0.1500")
    elif deal_type == DEAL_TYPE_PROFIT_SHARE:
        base["profit_share_label_pct"] = pct4("0.6000")
    elif deal_type == DEAL_TYPE_LABEL_SERVICES:
        base["services_fee_pct"] = pct4("0.1000")
        base["services_monthly_fee_cents"] = 25000

    if objection_window_days is not None:
        base["objection_window_days"] = objection_window_days
    if post_term_collection_days is not None:
        base["post_term_collection_days"] = post_term_collection_days

    return _compose(base, overrides)


def execute_payload(
    advance_payment_reference: str = "WIRE-2026-0031", **overrides: Any
) -> Dict[str, Any]:
    return _compose({"advance_payment_reference": advance_payment_reference}, overrides)


# ---------------------------------------------------------------------------
# Release (PRD Section 3.2)
# ---------------------------------------------------------------------------

def release_payload(
    deal_id: str,
    primary_artist_id: str,
    upc: Optional[str] = None,
    title: str = "Glass Harbour",
    planned_release_date: str = "2026-02-01",
    formats: Sequence[str] = (FORMAT_DIGITAL,),
    advance_share_cents: Optional[int] = None,
    **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "deal_id": deal_id,
        "primary_artist_id": primary_artist_id,
        "upc": upc if upc is not None else next_upc(),
        "title": title,
        "planned_release_date": planned_release_date,
        "formats": list(formats),
    }
    if advance_share_cents is not None:
        base["advance_share_cents"] = advance_share_cents
    return _compose(base, overrides)


def release_to_market_payload(
    actual_release_date: str = "2026-02-01", **overrides: Any
) -> Dict[str, Any]:
    return _compose({"actual_release_date": actual_release_date}, overrides)


# ---------------------------------------------------------------------------
# ArtistAgreement (PRD Section 3.3)
# ---------------------------------------------------------------------------

def agreement_payload(
    artist_id: str,
    release_id: str,
    royalty_rate_pct: Any = "0.1200",
    escalated_royalty_rate_pct: Any = "0.1800",
    advance_amount_cents: int = 0,
    recording_costs_cents: int = 0,
    recording_recoupable_pct: Any = "0.5000",
    marketing_recoup_share_pct: Any = "0.5000",
    supersedes_agreement_id: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "artist_id": artist_id,
        "release_id": release_id,
        "royalty_rate_pct": _pct_arg(royalty_rate_pct),
        "escalated_royalty_rate_pct": _pct_arg(escalated_royalty_rate_pct),
        "advance_amount_cents": advance_amount_cents,
        "recording_costs_cents": recording_costs_cents,
        "recording_recoupable_pct": _pct_arg(recording_recoupable_pct),
        "marketing_recoup_share_pct": _pct_arg(marketing_recoup_share_pct),
    }
    if supersedes_agreement_id is not None:
        base["supersedes_agreement_id"] = supersedes_agreement_id
    return _compose(base, overrides)


def propose_amendment_payload(
    proposed_royalty_rate_pct: Any,
    proposed_advance_amount_cents: int,
    **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "proposed_royalty_rate_pct": _pct_arg(proposed_royalty_rate_pct),
            "proposed_advance_amount_cents": proposed_advance_amount_cents,
        },
        overrides,
    )


def resolve_amendment_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _compose({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# MarketingSpend (PRD Section 3.4)
# ---------------------------------------------------------------------------

def spend_payload(
    release_id: str,
    category: str = SPEND_CATEGORY_DIGITAL_ADS,
    amount_cents: int = 100000,
    vendor: str = "Northlight Media",
    **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "release_id": release_id,
            "category": category,
            "amount_cents": amount_cents,
            "vendor": vendor,
        },
        overrides,
    )


def submit_spend_payload(
    amount_cents: Optional[int] = None,
    category: Optional[str] = None,
    **overrides: Any
) -> Optional[Dict[str, Any]]:
    """Both fields are optional on the submit edge; an empty payload is sent as
    ``{}`` so the request still carries a JSON body."""
    base: Dict[str, Any] = {}
    if amount_cents is not None:
        base["amount_cents"] = amount_cents
    if category is not None:
        base["category"] = category
    return _compose(base, overrides)


def decide_spend_payload(
    decision: str,
    revision_note: Optional[str] = None,
    recoupability_override: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"decision": decision}
    if revision_note is not None:
        base["revision_note"] = revision_note
    if recoupability_override is not None:
        base["recoupability_override"] = recoupability_override
    return _compose(base, overrides)


def settle_spend_payload(settled_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _compose({"settled_amount_cents": settled_amount_cents}, overrides)


# ---------------------------------------------------------------------------
# StreamRateCard (PRD Section 3.5)
# ---------------------------------------------------------------------------

def rate_card_payload(
    dsp_code: str = DEFAULT_DSP_CODE,
    territory_code: str = "US",
    tier: str = TIER_PREMIUM,
    rate_micros_per_stream: int = 4000,
    effective_from: str = "2026-01-01",
    effective_to: Optional[str] = None,
    **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "dsp_code": dsp_code,
        "territory_code": territory_code,
        "tier": tier,
        "rate_micros_per_stream": rate_micros_per_stream,
        "effective_from": effective_from,
    }
    if effective_to is not None:
        base["effective_to"] = effective_to
    return _compose(base, overrides)


# ---------------------------------------------------------------------------
# DspRevenueReport / DspRevenueLine (PRD Sections 3.5, 3.6)
# ---------------------------------------------------------------------------

def report_payload(
    deal_id: str,
    dsp_code: str = DEFAULT_DSP_CODE,
    period_start: str = "2026-04-01",
    period_end: str = "2026-06-30",
    **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "deal_id": deal_id,
            "dsp_code": dsp_code,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


def line_payload(
    release_id: str,
    territory_code: str = "US",
    tier: str = TIER_PREMIUM,
    stream_count: int = 250000,
    **overrides: Any
) -> Dict[str, Any]:
    """The report a line joins is identified by the path, not by the body."""
    return _compose(
        {
            "release_id": release_id,
            "territory_code": territory_code,
            "tier": tier,
            "stream_count": stream_count,
        },
        overrides,
    )


def accept_report_payload(expected_deal_version: int, **overrides: Any) -> Dict[str, Any]:
    return _compose({"expected_deal_version": expected_deal_version}, overrides)


def dispute_report_payload(
    expected_deal_version: int, dispute_reason: str, **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "expected_deal_version": expected_deal_version,
            "dispute_reason": dispute_reason,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# PhysicalRun (PRD Section 3.7)
# ---------------------------------------------------------------------------

def run_payload(
    release_id: str,
    distributor_id: str,
    units_planned: int = 1200,
    unit_manufacturing_cost_cents: int = 250,
    window_start: str = "2026-04-01",
    window_end: str = "2026-06-30",
    returns_reserve_pct: Any = None,
    **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "release_id": release_id,
        "distributor_id": distributor_id,
        "units_planned": units_planned,
        "unit_manufacturing_cost_cents": unit_manufacturing_cost_cents,
        "window_start": window_start,
        "window_end": window_end,
    }
    if returns_reserve_pct is not None:
        base["returns_reserve_pct"] = _pct_arg(returns_reserve_pct)
    return _compose(base, overrides)


def manufacture_payload(units_manufactured: int, **overrides: Any) -> Dict[str, Any]:
    return _compose({"units_manufactured": units_manufactured}, overrides)


def ship_payload(
    units_shipped: int, wholesale_unit_price_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "units_shipped": units_shipped,
            "wholesale_unit_price_cents": wholesale_unit_price_cents,
        },
        overrides,
    )


def record_returns_payload(returned_units: int, **overrides: Any) -> Dict[str, Any]:
    return _compose({"returned_units": returned_units}, overrides)


def liquidate_payload(
    expected_run_version: int, liquidation_pct: Any, **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "expected_run_version": expected_run_version,
            "liquidation_pct": _pct_arg(liquidation_pct),
        },
        overrides,
    )


def void_liquidation_payload(expected_run_version: int, **overrides: Any) -> Dict[str, Any]:
    """Voiding takes nothing but the version echo."""
    return _compose({"expected_run_version": expected_run_version}, overrides)


# ---------------------------------------------------------------------------
# ArtistStatement (PRD Sections 3.8, 3.9)
# ---------------------------------------------------------------------------

def statement_payload(
    artist_agreement_id: str,
    period_start: str = "2026-04-01",
    period_end: str = "2026-06-30",
    basis_variant: str = BASIS_VARIANT_FINAL,
    **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "artist_agreement_id": artist_agreement_id,
            "period_start": period_start,
            "period_end": period_end,
            "basis_variant": basis_variant,
        },
        overrides,
    )


def object_payload(
    objection_reason_code: str,
    objection_disputed_amount_cents: int,
    objection_narrative: str,
    **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "objection_reason_code": objection_reason_code,
            "objection_disputed_amount_cents": objection_disputed_amount_cents,
            "objection_narrative": objection_narrative,
        },
        overrides,
    )


def resolve_objection_payload(
    resolution: str,
    objection_adjustment_cents: Optional[int] = None,
    **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"resolution": resolution}
    if objection_adjustment_cents is not None:
        base["objection_adjustment_cents"] = objection_adjustment_cents
    return _compose(base, overrides)


def request_audit_payload(
    audit_scope_period_start: str,
    audit_scope_period_end: str,
    auditor_name: str = "Harrow & Vance",
    **overrides: Any
) -> Dict[str, Any]:
    return _compose(
        {
            "audit_scope_period_start": audit_scope_period_start,
            "audit_scope_period_end": audit_scope_period_end,
            "auditor_name": auditor_name,
        },
        overrides,
    )


def conclude_audit_payload(
    findings_adjustment_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _compose({"findings_adjustment_cents": findings_adjustment_cents}, overrides)
