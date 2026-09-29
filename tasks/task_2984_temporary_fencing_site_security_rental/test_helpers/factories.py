"""Request-payload builders.

Every builder returns a fresh dict of exactly the fields PRD §3 defines for its
endpoint, honouring the shape rules of PRD §2.5: money and counts are JSON
integers (never strings), ``daily_capacity_hours`` is a JSON number, and every
instant is a full ISO 8601 UTC timestamp ending in ``Z`` — never a bare date.

Overrides are merged into a single dict before the payload is built, so a
derived builder can never pass the same keyword twice.
"""

from typing import Any, Dict, List, Optional

from . import constants as C

_UNSET = object()


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``overrides`` onto ``base``; a value of ``None`` is kept as JSON null."""
    merged = dict(base)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v is not _UNSET}


# ---------------------------------------------------------------------------
# Municipality (PRD §3.1)
# ---------------------------------------------------------------------------


def municipality_payload(**overrides: Any) -> Dict[str, Any]:
    """A permitting jurisdiction; ``rental_tax_rate_bp`` 890 is 8.9 percent."""
    return _merge(
        {
            "name": C.HRB_NAME,
            "jurisdiction_code": C.HRB_CODE,
            "permit_lead_time_days": C.HRB_LEAD_TIME_DAYS,
            "max_concurrent_closure_linear_feet": C.HRB_MAX_CLOSURE_FT,
            "rental_tax_rate_bp": C.HRB_TAX_RATE_BP,
            "permit_review_rounds_allowed": C.HRB_REVIEW_ROUNDS,
            "allows_solid_wind_screen": True,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# CustomerAccount (PRD §3.1)
# ---------------------------------------------------------------------------


def account_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": "Ridgeline Builders LLC",
            "billing_email": "ap@ridgeline.example",
            "credit_limit_cents": C.UNLIMITED_CREDIT_CENTS,
        },
        overrides,
    )


def event_account_payload(**overrides: Any) -> Dict[str, Any]:
    return account_payload(
        **_merge(
            {
                "legal_name": "Harborfest Events Inc",
                "billing_email": "ap@harborfest.example",
            },
            overrides,
        )
    )


def payment_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents}, overrides)


# ---------------------------------------------------------------------------
# FenceProduct (PRD §3.1, §2.11)
# ---------------------------------------------------------------------------


def panel_product_payload(**overrides: Any) -> Dict[str, Any]:
    """A ``FENCE_PANEL``: positive ``panel_length_ft``, zero unit monthly rate."""
    return _merge(
        {
            "code": C.PANEL_CODE,
            "category": C.CATEGORY_FENCE_PANEL,
            "description": "10 ft chain-link fence panel",
            "panel_length_ft": C.PANEL_LENGTH_FT,
            "unit_monthly_rate_cents": 0,
            "replacement_cost_cents_per_unit": C.PANEL_REPLACEMENT_CENTS,
            "fleet_age_months": C.PANEL_FLEET_AGE_MONTHS,
            "wind_load_rating_mph": 90,
            "owned_count": C.PANEL_OWNED_COUNT,
        },
        overrides,
    )


def gate_product_payload(**overrides: Any) -> Dict[str, Any]:
    """A ``GATE``: ``panel_length_ft`` must be null."""
    return _merge(
        {
            "code": C.GATE_CODE,
            "category": C.CATEGORY_GATE,
            "description": "12 ft double swing gate",
            "unit_monthly_rate_cents": C.GATE_MONTHLY_CENTS,
            "replacement_cost_cents_per_unit": C.GATE_REPLACEMENT_CENTS,
            "fleet_age_months": C.GATE_FLEET_AGE_MONTHS,
            "owned_count": C.GATE_OWNED_COUNT,
        },
        overrides,
    )


def barricade_product_payload(**overrides: Any) -> Dict[str, Any]:
    """A ``BARRICADE``: ``panel_length_ft`` must be null."""
    return _merge(
        {
            "code": C.BARRICADE_CODE,
            "category": C.CATEGORY_BARRICADE,
            "description": "8 ft interlocking steel barricade",
            "unit_monthly_rate_cents": C.BARRICADE_MONTHLY_CENTS,
            "replacement_cost_cents_per_unit": C.BARRICADE_REPLACEMENT_CENTS,
            "fleet_age_months": C.BARRICADE_FLEET_AGE_MONTHS,
            "owned_count": C.BARRICADE_OWNED_COUNT,
        },
        overrides,
    )


def water_barrier_product_payload(**overrides: Any) -> Dict[str, Any]:
    """A ``WATER_BARRIER``: ``panel_length_ft`` must be null."""
    return _merge(
        {
            "code": C.WATER_BARRIER_CODE,
            "category": C.CATEGORY_WATER_BARRIER,
            "description": "6 ft water-filled barrier",
            "unit_monthly_rate_cents": C.WATER_BARRIER_MONTHLY_CENTS,
            "replacement_cost_cents_per_unit": C.WATER_BARRIER_REPLACEMENT_CENTS,
            "fleet_age_months": C.WATER_BARRIER_FLEET_AGE_MONTHS,
            "owned_count": C.WATER_BARRIER_OWNED_COUNT,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Crew (PRD §3.1)
# ---------------------------------------------------------------------------


def crew_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "crew_code": C.CREW_A,
            "depot_code": C.DEPOT,
            "daily_capacity_hours": C.CREW_CAPACITY_HOURS,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Jobsite (PRD §3.1)
# ---------------------------------------------------------------------------


def jobsite_payload(
    customer_account_id: str, municipality_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "customer_account_id": customer_account_id,
            "municipality_id": municipality_id,
            "site_label": "Foundry Road Phase Yard",
            "address_line": "402 Foundry Road",
            "site_condition": C.CONDITION_SOIL,
            "requires_sidewalk_closure": False,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Quote (PRD §3.2)
# ---------------------------------------------------------------------------


def addon_line(product_code: str, quantity: int) -> Dict[str, Any]:
    return {"product_code": product_code, "quantity": quantity}


def quote_payload(expected_jobsite_version: int, **overrides: Any) -> Dict[str, Any]:
    """A ``CONSTRUCTION`` quote at the three-month minimum term.

    ``expected_jobsite_version`` is the non-optional concurrency token of
    PRD §2.8; no other quote field carries a version.
    """
    return _merge(
        {
            "expected_jobsite_version": expected_jobsite_version,
            "contract_type": C.CONTRACT_TYPE_CONSTRUCTION,
            "linear_feet": 500,
            "panel_product_code": C.PANEL_CODE,
            "term_months": C.MIN_TERM_MONTHS_CONSTRUCTION,
            "wind_screen": C.SCREEN_NONE,
        },
        overrides,
    )


def event_quote_payload(
    expected_jobsite_version: int, **overrides: Any
) -> Dict[str, Any]:
    """An ``EVENT`` quote, whose ``term_months`` must be exactly 1."""
    merged = _merge(
        {
            "contract_type": C.CONTRACT_TYPE_EVENT,
            "linear_feet": 250,
            "term_months": C.TERM_MONTHS_EVENT,
        },
        overrides,
    )
    version = merged.pop("expected_jobsite_version", expected_jobsite_version)
    return quote_payload(version, **merged)


def accept_payload(accepted_by_name: str = C.ACCEPTOR_CONSTRUCTION, **overrides: Any):
    return _merge({"accepted_by_name": accepted_by_name}, overrides)


# ---------------------------------------------------------------------------
# PermitApplication (PRD §3.4)
# ---------------------------------------------------------------------------


def permit_payload(jobsite_id: str, **overrides: Any) -> Dict[str, Any]:
    """A half-open closure window of PRD §2.6, clear of the 5-day lead time."""
    return _merge(
        {
            "jobsite_id": jobsite_id,
            "closure_linear_feet": 300,
            "closure_start_utc": "2026-08-10T00:00:00Z",
            "closure_end_utc": "2026-08-20T00:00:00Z",
            "sidewalk_closure_type": C.CLOSURE_PARTIAL,
        },
        overrides,
    )


def submit_payload(**overrides: Any) -> Dict[str, Any]:
    """A submission body; the three window/footage overrides are all optional."""
    return _merge({}, overrides)


def decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# RentalContract (PRD §3.3, §3.5, §3.8, §3.9)
# ---------------------------------------------------------------------------


def contract_payload(
    quote_id: str, terms_acknowledged_by: str = C.ACCEPTOR_CONSTRUCTION, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"quote_id": quote_id, "terms_acknowledged_by": terms_acknowledged_by},
        overrides,
    )


def work_order_payload(
    work_order_type: str, ordered_linear_feet: int, **overrides: Any
) -> Dict[str, Any]:
    """A planned visit; ``phase_from``/``phase_to`` are not accepted here."""
    return _merge(
        {
            "work_order_type": work_order_type,
            "ordered_linear_feet": ordered_linear_feet,
        },
        overrides,
    )


def reset_order_payload(
    expected_contract_version: int,
    ordered_linear_feet: int,
    phase_to: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A phase move; ``expected_contract_version`` is non-optional (PRD §2.8)."""
    return _merge(
        {
            "expected_contract_version": expected_contract_version,
            "ordered_linear_feet": ordered_linear_feet,
            "phase_to": phase_to,
        },
        overrides,
    )


def dispatch_payload(crew_id: str, scheduled_start_utc: str, **overrides: Any):
    return _merge(
        {"crew_id": crew_id, "scheduled_start_utc": scheduled_start_utc}, overrides
    )


def complete_payload(completed_linear_feet: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"completed_linear_feet": completed_linear_feet}, overrides)


def abort_payload(abort_reason_code: str = "SITE_NOT_READY", **overrides: Any):
    return _merge({"abort_reason_code": abort_reason_code}, overrides)


def cancel_payload(cancel_reason_code: str = "CUSTOMER_RESCHEDULE", **overrides: Any):
    return _merge({"cancel_reason_code": cancel_reason_code}, overrides)


def billing_run_payload(
    period_start_utc: str, period_end_utc: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"period_start_utc": period_start_utc, "period_end_utc": period_end_utc},
        overrides,
    )


def void_payload(void_reason_code: str = "BILLED_IN_ERROR", **overrides: Any):
    return _merge({"void_reason_code": void_reason_code}, overrides)


# ---------------------------------------------------------------------------
# RemovalReconciliation (PRD §3.7)
# ---------------------------------------------------------------------------


def unit_return(
    product_code: str, returned: int, damaged: int = 0, missing: int = 0
) -> Dict[str, Any]:
    return {
        "product_code": product_code,
        "returned": returned,
        "damaged": damaged,
        "missing": missing,
    }


def finalize_payload(
    unit_returns: List[Dict[str, Any]],
    theft_police_report_number: Optional[str] = _UNSET,  # type: ignore[assignment]
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"unit_returns": unit_returns}
    if theft_police_report_number is not _UNSET:
        base["theft_police_report_number"] = theft_police_report_number
    return _merge(base, overrides)
