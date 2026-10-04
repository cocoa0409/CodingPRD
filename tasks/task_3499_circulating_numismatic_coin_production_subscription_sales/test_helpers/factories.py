"""Payload factories — one per entity, input fields only (never computed fields).

Conventions:
  - Every factory takes **overrides; override values replace the defaults.
  - None-drops-key: overriding a field with None REMOVES the key from the
    payload (for optional fields like locked_unit_price_cents_per_tonne /
    program_id / description / subscription_eligible). To send an explicit
    JSON null, pass the string "null-sentinel" is NOT supported — absence and
    null are treated identically by the PRD for these optional fields.
  - Unique-per-process defaults (product_code, email, program/product names)
    carry a monotonically increasing suffix so repeated calls inside one test
    never collide on uniqueness constraints.
"""
import itertools

from .constants import (
    DEFAULT_COPPER_SPOT_CENTS_PER_TONNE,  # noqa: F401  (re-exported context)
    DEFAULT_DENOMINATION,
    DEFAULT_GOLD_SPOT_CENTS_PER_OZ,  # noqa: F401
    DEFAULT_LOCKED_COPPER_PRICE_CENTS_PER_TONNE,
    DEFAULT_LOT_BUDGET_PRICE_CENTS_PER_TONNE,
    DEFAULT_PRODUCT_PRICE_CENTS,
    DEFAULT_SUBSCRIPTION_PRODUCT_PRICE_CENTS,
)
from .types import (
    AuthorizedPurchaserTier,
    BullionMetal,
    Commodity,
    DesignDecision,
    Facility,
    InspectionOutcome,
    PaymentOutcome,
    ProductType,
    SubscriptionFrequency,
    Vault,
)

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def _apply_overrides(defaults: dict, overrides: dict) -> dict:
    payload = dict(defaults)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --- Entity create payloads ------------------------------------------------------

def create_denomination_payload(**overrides) -> dict:
    """Denomination inputs (PRD §3.1). Default: the canonical QUARTER
    (face 25c, blank 4.0c, striking 2.0c, 176000 blanks/tonne)."""
    return _apply_overrides(dict(DEFAULT_DENOMINATION), overrides)


def create_fed_order_payload(**overrides) -> dict:
    """FederalReserveOrder inputs. denomination_code must match an existing one."""
    defaults = {
        "fiscal_year": 2026,
        "denomination_code": DEFAULT_DENOMINATION["code"],
        "quantity_ordered_pieces": 50000,
        "due_date": "2026-12-31",
    }
    return _apply_overrides(defaults, overrides)


def create_metal_lot_payload(**overrides) -> dict:
    """MetalProcurementLot inputs. Hedged by default (locked price present);
    pass locked_unit_price_cents_per_tonne=None for an unhedged (spot) lot."""
    defaults = {
        "commodity": Commodity.COPPER.value,
        "denomination_code": DEFAULT_DENOMINATION["code"],
        "quantity_tonnes": 10,
        "budget_price_cents_per_tonne": DEFAULT_LOT_BUDGET_PRICE_CENTS_PER_TONNE,
        "locked_unit_price_cents_per_tonne": DEFAULT_LOCKED_COPPER_PRICE_CENTS_PER_TONNE,
        "vault": Vault.WEST_POINT.value,
        "planned_delivery_date": "2026-09-05",
    }
    return _apply_overrides(defaults, overrides)


def create_production_run_payload(**overrides) -> dict:
    """ProductionRun inputs. fed_order_id has no default — always supply it."""
    defaults = {
        "fed_order_id": "REQUIRED-OVERRIDE",
        "facility": Facility.DENVER.value,
        "press_line": "P1",
        "planned_start": "2026-10-05T08:00:00Z",
        "planned_end": "2026-10-05T12:00:00Z",
        "planned_quantity": 50000,
    }
    return _apply_overrides(defaults, overrides)


def create_program_payload(**overrides) -> dict:
    """CommemorativeProgram inputs (PRD §3.5)."""
    defaults = {
        "name": _uniq("Program"),
        "statute_reference": "PL 119-1",
        "max_mintage_legal": 5000,
        "surcharge_cents_per_unit": 500,
        "beneficiary_name": "Test Foundation",
        "beneficiary_cap_cents": 100000,
        "direct_costs_cents": 1000,
        "sales_window_start": "2026-09-15T00:00:00Z",
        "sales_window_end": "2026-12-31T00:00:00Z",
    }
    return _apply_overrides(defaults, overrides)


def create_product_payload(**overrides) -> dict:
    """NumismaticProduct inputs (PRD §3.6). program_id and
    subscription_eligible are optional (absent by default)."""
    defaults = {
        "product_code": _uniq("PROD"),
        "product_family": _uniq("FAM"),
        "product_type": ProductType.PROOF_SET.value,
        "price_cents": DEFAULT_PRODUCT_PRICE_CENTS,
        "mintage_limit": 100,
        "household_order_limit": 10,
        "release_datetime": "2026-10-01T14:00:00Z",
    }
    return _apply_overrides(defaults, overrides)


def create_subscription_product_payload(**overrides) -> dict:
    """Subscription-eligible SUBSCRIPTION_SERIES product at the canonical 9995c."""
    # Distinct product_family per default call so the 24h release-gap rule
    # never trips when one test creates several subscription products.
    defaults = {
        "product_code": _uniq("SUB"),
        "product_family": _uniq("SUBFAM"),
        "product_type": ProductType.SUBSCRIPTION_SERIES.value,
        "price_cents": DEFAULT_SUBSCRIPTION_PRODUCT_PRICE_CENTS,
        "mintage_limit": 10000,
        "household_order_limit": 1000,
        "release_datetime": "2026-08-15T00:00:00Z",
        "subscription_eligible": True,
    }
    return _apply_overrides(defaults, overrides)


def create_collector_payload(**overrides) -> dict:
    """Collector inputs (PRD §3.6)."""
    defaults = {
        "full_name": _uniq("Collector"),
        "email": f"{_uniq('collector')}@example.com",
        "household_id": _uniq("HH"),
    }
    return _apply_overrides(defaults, overrides)


def create_order_payload(**overrides) -> dict:
    """NumismaticOrder inputs. product_id has no default; collector_id comes
    from X-User-ID and is never payload-supplied."""
    defaults = {
        "product_id": "REQUIRED-OVERRIDE",
        "quantity": 1,
    }
    return _apply_overrides(defaults, overrides)


def create_subscription_payload(**overrides) -> dict:
    """Subscription inputs. product_id has no default."""
    defaults = {
        "product_id": "REQUIRED-OVERRIDE",
        "units_per_cycle": 1,
        "frequency": SubscriptionFrequency.MONTHLY.value,
    }
    return _apply_overrides(defaults, overrides)


def create_bullion_issue_payload(**overrides) -> dict:
    """BullionIssue inputs (PRD §3.8)."""
    defaults = {
        "name": _uniq("American Gold Eagle"),
        "metal": BullionMetal.GOLD.value,
        "unit_weight_oz": 1.0,
        "total_pool_units": 1000,
        "offer_window_hours": 48,
    }
    return _apply_overrides(defaults, overrides)


def create_authorized_purchaser_payload(**overrides) -> dict:
    """AuthorizedPurchaser inputs (PRD §3.8)."""
    defaults = {
        "name": _uniq("Dealer"),
        "tier": AuthorizedPurchaserTier.T1.value,
    }
    return _apply_overrides(defaults, overrides)


def create_allocation_payload(**overrides) -> dict:
    """BullionAllocation inputs: authorized_purchaser_id, quantity_units and
    the OCC field expected_bullion_issue_version (PRD §2.6) are all required."""
    defaults = {
        "authorized_purchaser_id": "REQUIRED-OVERRIDE",
        "quantity_units": 1,
        "expected_bullion_issue_version": "REQUIRED-OVERRIDE",
    }
    return _apply_overrides(defaults, overrides)


def create_error_coin_case_payload(**overrides) -> dict:
    """ErrorCoinCase inputs. production_run_id and error_pieces are required;
    description is optional (absent by default)."""
    defaults = {
        "production_run_id": "REQUIRED-OVERRIDE",
        "error_pieces": 1,
    }
    return _apply_overrides(defaults, overrides)


# --- Action payloads ---------------------------------------------------------------

def clock_payload(to_iso8601: str, spot_prices: dict = None) -> dict:
    """POST /_clock/set_current_utc body; spot_prices key omitted when None."""
    payload = {"to_iso8601": to_iso8601}
    if spot_prices is not None:
        payload["spot_prices"] = dict(spot_prices)
    return payload


def decide_design_payload(decision: str = DesignDecision.APPROVED.value) -> dict:
    return {"decision": decision}


def inspect_payload(outcome: str = InspectionOutcome.PASS.value, good_pieces=None) -> dict:
    """good_pieces is required on PASS (0 <= good_pieces <= reserved_blanks)
    and omitted on FAIL."""
    payload = {"outcome": outcome}
    if good_pieces is not None:
        payload["good_pieces"] = good_pieces
    return payload


def order_payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def billing_cycle_payload(expected_subscription_version: int) -> dict:
    """OCC-guarded billing cycle body (PRD §2.6)."""
    return {"expected_subscription_version": expected_subscription_version}


def invoice_payment_payload(outcome: str = PaymentOutcome.SUCCEEDED.value) -> dict:
    return {"outcome": outcome}


def set_status_payload(to_status: str) -> dict:
    return {"to_status": to_status}


def destroy_payload(primary_certifier_user_id: str, secondary_certifier_user_id: str) -> dict:
    return {
        "primary_certifier_user_id": primary_certifier_user_id,
        "secondary_certifier_user_id": secondary_certifier_user_id,
    }
