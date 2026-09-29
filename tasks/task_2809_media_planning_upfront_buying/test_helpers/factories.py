"""Request payload builders.

Each builder returns a complete, valid payload for one endpoint and accepts
keyword overrides, so a test states only the figures its scenario turns on.

Money is always emitted as a JSON number of whole cents and audience figures as
JSON numbers of whole impressions — never as strings — because the requirement
declares those fields integral.  Percentages, rates and indices are emitted as
JSON numbers carrying at most the decimals the requirement permits on input.
"""

from typing import Any, Dict, List, Optional

from .constants import shift_days
from .types import (
    CategoryCode,
    Channel,
    Daypart,
    DedupMethod,
    ExclusivityMode,
    Market,
    MeasurementBasis,
    Platform,
    RightsKind,
)

Json = Dict[str, Any]


# ==========================================================================
# A coherent baseline calendar
# ==========================================================================
#: Campaign flight the baseline payloads share.
FLIGHT_START = "2026-12-01T00:00:00Z"
FLIGHT_END = "2027-02-28T00:00:00Z"

#: Avail window sitting inside that flight.
AVAIL_WINDOW_START = "2026-12-01T00:00:00Z"
AVAIL_WINDOW_END = "2027-01-31T00:00:00Z"

#: Air window sitting inside that avail window.
AIR_WINDOW_START = "2026-12-01T00:00:00Z"
AIR_WINDOW_END = "2026-12-31T00:00:00Z"

#: Selling quarter the baseline payloads share.
FISCAL_QUARTER = "2026Q4"


# ==========================================================================
# Counterparties
# ==========================================================================
def advertiser_payload(**overrides: Any) -> Json:
    """A brand client with a generous credit limit and the default terms."""
    payload: Json = {
        "name": "Northwind Beverages",
        "category_code": CategoryCode.BEVERAGE.value,
        "credit_limit_cents": 500_000_000,
    }
    payload.update(overrides)
    return payload


def seller_payload(**overrides: Any) -> Json:
    """A media seller able to deliver on every platform."""
    payload: Json = {
        "name": "Meridian Media Group",
        "platform_types": [
            Platform.LINEAR.value,
            Platform.CTV.value,
            Platform.DIGITAL.value,
            Platform.AUDIO.value,
        ],
        "make_good_capacity_impressions": 50_000_000,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# Plan
# ==========================================================================
def campaign_payload(advertiser_id: str, **overrides: Any) -> Json:
    """A campaign objective with a two-hundred-million-cent working budget."""
    payload: Json = {
        "advertiser_id": advertiser_id,
        "name": "Northwind Winter Upfront",
        "target_demo": "A25-54",
        "universe_thousands": 120_000,
        "reach_goal_pct": 60.00,
        "frequency_goal": 3.00,
        "total_budget_cents": 200_000_000,
        "flight_start": FLIGHT_START,
        "flight_end": FLIGHT_END,
        "fiscal_quarter": FISCAL_QUARTER,
    }
    payload.update(overrides)
    return payload


def channel_allocation_payload(campaign_id: str, **overrides: Any) -> Json:
    """A linear television share of the plan bought upfront in prime."""
    payload: Json = {
        "campaign_id": campaign_id,
        "channel": Channel.LINEAR_TV.value,
        "allocation_pct": 30.00,
        "planned_cpm_cents": 2000,
        "planned_market": Market.UPFRONT.value,
        "primary_daypart": Daypart.PRIME.value,
    }
    payload.update(overrides)
    return payload


def reject_plan_payload(**overrides: Any) -> Json:
    """The note the client returns a plan with."""
    payload: Json = {"revision_note": "shift weight out of late night"}
    payload.update(overrides)
    return payload


def fund_payload(amount_cents: int, **overrides: Any) -> Json:
    """A client deposit against the campaign budget."""
    payload: Json = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ==========================================================================
# Inventory
# ==========================================================================
def inventory_forecast_payload(seller_id: str, **overrides: Any) -> Json:
    """A prime linear avail inside the baseline flight."""
    payload: Json = {
        "seller_id": seller_id,
        "market": Market.UPFRONT.value,
        "fiscal_quarter": FISCAL_QUARTER,
        "daypart": Daypart.PRIME.value,
        "program": "Evening Headlines",
        "platform": Platform.LINEAR.value,
        "window_start": AVAIL_WINDOW_START,
        "window_end": AVAIL_WINDOW_END,
        "total_impressions": 60_000_000,
        "forecast_cpm_cents": 2200,
    }
    payload.update(overrides)
    return payload


def exclusive_forecast_payload(seller_id: str, **overrides: Any) -> Json:
    """An avail that admits one occupying line per air window."""
    overrides.setdefault("exclusivity_mode", ExclusivityMode.EXCLUSIVE.value)
    return inventory_forecast_payload(seller_id, **overrides)


# ==========================================================================
# Negotiation
# ==========================================================================
def negotiation_payload(
    campaign_id: str, seller_id: str, channel_allocation_id: str, **overrides: Any
) -> Json:
    """An opening agency offer on the linear allocation."""
    payload: Json = {
        "campaign_id": campaign_id,
        "seller_id": seller_id,
        "channel_allocation_id": channel_allocation_id,
        "market": Market.UPFRONT.value,
        "channel": Channel.LINEAR_TV.value,
        "requested_impressions": 40_000_000,
        "opening_cpm_cents": 2000,
    }
    payload.update(overrides)
    return payload


def counter_payload(
    expected_negotiation_version: int,
    counter_cpm_cents: int = 2200,
    counter_impressions: int = 40_000_000,
    **overrides: Any,
) -> Json:
    """A seller counter carrying the version the seller last observed."""
    payload: Json = {
        "expected_negotiation_version": expected_negotiation_version,
        "counter_cpm_cents": counter_cpm_cents,
        "counter_impressions": counter_impressions,
    }
    payload.update(overrides)
    return payload


def revise_payload(
    offer_cpm_cents: int = 2100, offer_impressions: int = 40_000_000, **overrides: Any
) -> Json:
    """An agency revision after a seller counter."""
    payload: Json = {
        "offer_cpm_cents": offer_cpm_cents,
        "offer_impressions": offer_impressions,
    }
    payload.update(overrides)
    return payload


def withdraw_payload(**overrides: Any) -> Json:
    """The reason the agency withdraws with."""
    payload: Json = {"withdraw_reason": "budget reallocated to digital"}
    payload.update(overrides)
    return payload


# ==========================================================================
# Buy, unit lines and placement
# ==========================================================================
def buy_unit_payload(forecast_id: str, **overrides: Any) -> Json:
    """A unit line restating the avail's daypart, program and platform."""
    payload: Json = {
        "forecast_id": forecast_id,
        "daypart": Daypart.PRIME.value,
        "program": "Evening Headlines",
        "platform": Platform.LINEAR.value,
        "units": 100,
        "unit_rate_cents": 8_800,
        "projected_impressions": 40_000_000,
        "air_window_start": AIR_WINDOW_START,
        "air_window_end": AIR_WINDOW_END,
    }
    payload.update(overrides)
    return payload


def place_payload(expected_campaign_version: int, **overrides: Any) -> Json:
    """A placement carrying the campaign version the buyer last observed."""
    payload: Json = {"expected_campaign_version": expected_campaign_version}
    payload.update(overrides)
    return payload


def settle_aired_payload(actual_impressions: int, **overrides: Any) -> Json:
    """A settlement reporting the line aired with a measured audience."""
    payload: Json = {"outcome": "AIRED", "actual_impressions": actual_impressions}
    payload.update(overrides)
    return payload


def settle_preempted_payload(**overrides: Any) -> Json:
    """A settlement reporting the line was pre-empted."""
    payload: Json = {"outcome": "PREEMPTED"}
    payload.update(overrides)
    return payload


# ==========================================================================
# Rights
# ==========================================================================
def rights_exercise_payload(buy_id: str, kind: str, requested_pct: float, **overrides: Any) -> Json:
    """An option roll-up or a cancellation against a share of the guarantee."""
    payload: Json = {
        "buy_id": buy_id,
        "kind": kind,
        "requested_pct": requested_pct,
    }
    payload.update(overrides)
    return payload


def option_roll_payload(buy_id: str, requested_pct: float = 10.00, **overrides: Any) -> Json:
    """An option roll-up adding a share of the guarantee."""
    return rights_exercise_payload(
        buy_id, RightsKind.OPTION_ROLL.value, requested_pct, **overrides
    )


def cancellation_payload(buy_id: str, requested_pct: float = 100.00, **overrides: Any) -> Json:
    """A cancellation releasing a share of the guarantee."""
    return rights_exercise_payload(
        buy_id, RightsKind.CANCELLATION.value, requested_pct, **overrides
    )


# ==========================================================================
# Delivery, disputes and make-goods
# ==========================================================================
def delivery_report_payload(
    buy_id: str,
    delivered_impressions: int,
    delivered_demo_impressions: int,
    period_start: str = FLIGHT_START,
    period_end: str = FLIGHT_END,
    **overrides: Any,
) -> Json:
    """Measured delivery for a period of the buy, gross and on the target demo."""
    payload: Json = {
        "buy_id": buy_id,
        "measurement_basis": MeasurementBasis.LINEAR_C3.value,
        "period_start": period_start,
        "period_end": period_end,
        "delivered_impressions": delivered_impressions,
        "delivered_demo_impressions": delivered_demo_impressions,
    }
    payload.update(overrides)
    return payload


def dispute_payload(**overrides: Any) -> Json:
    """The reason the agency disputes a report with."""
    payload: Json = {"dispute_reason": "panel weighting under review"}
    payload.update(overrides)
    return payload


def make_good_offer_payload(
    offered_forecast_id: str,
    offered_impressions: int,
    offered_window_start: str = AIR_WINDOW_START,
    offered_window_end: str = AIR_WINDOW_END,
    **overrides: Any,
) -> Json:
    """A seller offer of replacement inventory against an open make-good."""
    payload: Json = {
        "offered_forecast_id": offered_forecast_id,
        "offered_impressions": offered_impressions,
        "offered_window_start": offered_window_start,
        "offered_window_end": offered_window_end,
    }
    payload.update(overrides)
    return payload


def make_good_rejection_payload(**overrides: Any) -> Json:
    """The reason the agency rejects an offered make-good with."""
    payload: Json = {"rejection_reason": "window falls outside the campaign flight"}
    payload.update(overrides)
    return payload


def waive_payload(credit_cents: Optional[int] = None, **overrides: Any) -> Json:
    """A waiver, optionally naming the cash credit the client receives."""
    payload: Json = {}
    if credit_cents is not None:
        payload["credit_cents"] = credit_cents
    payload.update(overrides)
    return payload


# ==========================================================================
# Reconciliation
# ==========================================================================
def sequential_dedup_payload(
    campaign_id: str,
    linear_ctv_duplication_pct: float = 20.00,
    ctv_digital_duplication_pct: float = 15.00,
    linear_digital_duplication_pct: float = 10.00,
    **overrides: Any,
) -> Json:
    """A run deduplicating pairwise between consecutive present groups."""
    payload: Json = {
        "campaign_id": campaign_id,
        "dedup_method": DedupMethod.SEQUENTIAL_DEDUP.value,
        "linear_ctv_duplication_pct": linear_ctv_duplication_pct,
        "ctv_digital_duplication_pct": ctv_digital_duplication_pct,
        "linear_digital_duplication_pct": linear_digital_duplication_pct,
    }
    payload.update(overrides)
    return payload


def aggregate_dedup_payload(
    campaign_id: str, aggregate_duplication_pct: float = 20.00, **overrides: Any
) -> Json:
    """A run applying one campaign-level duplication estimate."""
    payload: Json = {
        "campaign_id": campaign_id,
        "dedup_method": DedupMethod.AGGREGATE_DEDUP.value,
        "aggregate_duplication_pct": aggregate_duplication_pct,
    }
    payload.update(overrides)
    return payload


# ==========================================================================
# Billing and settlement
# ==========================================================================
def invoice_payload(
    buy_id: str,
    billing_period_start: str = AIR_WINDOW_START,
    billing_period_end: str = FLIGHT_END,
    **overrides: Any,
) -> Json:
    """A draft invoice for one billing period of the buy."""
    payload: Json = {
        "buy_id": buy_id,
        "billing_period_start": billing_period_start,
        "billing_period_end": billing_period_end,
    }
    payload.update(overrides)
    return payload


def client_payment_payload(amount_cents: int, **overrides: Any) -> Json:
    """A client payment against an issued invoice."""
    payload: Json = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def remittance_payload(amount_cents: int, **overrides: Any) -> Json:
    """A remittance to the seller against an issued invoice."""
    payload: Json = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str, **overrides: Any) -> Json:
    """The instant the logical clock should read."""
    payload: Json = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ==========================================================================
# Window helpers used when a scenario needs a second, disjoint calendar
# ==========================================================================
def window_after(reference: str, offset_days: int, length_days: int) -> Dict[str, str]:
    """A window opening ``offset_days`` after a reference and lasting so long."""
    start = shift_days(reference, offset_days)
    return {"start": start, "end": shift_days(start, length_days)}


def platform_types(*platforms: str) -> List[str]:
    """A seller's platform list, spelled from the declared vocabulary."""
    return list(platforms)
