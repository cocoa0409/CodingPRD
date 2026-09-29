"""Payload factories — one per resource, carrying only client-supplied fields.

Money is always an integer number of cents and every rate is an integer number
of basis points; no factory ever emits a decimal or a numeric string. Every
instant is a full ISO 8601 UTC instant with three fractional-second digits.
"""
import itertools
import uuid

from .constants import AUG_01, BUILD_FROM, BUILD_TO, SEP_01, TEST_DEFAULTS

_counter = itertools.count(1)


def _suffix(width: int = 6) -> str:
    """Short unique suffix so globally unique codes never collide across tests."""
    return uuid.uuid4().hex[:width].upper()


def unique_program_code(prefix: str = "PRG") -> str:
    """A program_code of 1 to 32 characters, unique across all programs."""
    return f"{prefix}-{next(_counter):03d}-{_suffix()}"[:32]


def unique_dealer_code(prefix: str = "D") -> str:
    """A dealer_code of 1 to 16 characters, unique across all dealers."""
    return f"{prefix}{next(_counter):03d}{_suffix(4)}"[:16]


def unique_batch_code(prefix: str = "B") -> str:
    """A batch_code of 1 to 24 characters, unique across all batches."""
    return f"{prefix}-{next(_counter):03d}-{_suffix()}"[:24]


def unique_vin() -> str:
    """A vin of exactly 17 characters, globally unique across all deliveries."""
    body = f"{next(_counter):04d}{uuid.uuid4().hex[:9].upper()}"
    return f"VIN{body}"[:17].ljust(17, "0")


# --- IncentiveProgram --------------------------------------------------------


def create_program_payload(**overrides) -> dict:
    """CUSTOMER_CASH program over the August 2026 window."""
    payload = {
        "program_code": unique_program_code(),
        "name": "August Customer Cash",
        "incentive_type": "CUSTOMER_CASH",
        "effective_from": AUG_01,
        "effective_to": SEP_01,
        "per_unit_amount_cents": TEST_DEFAULTS["PER_UNIT_AMOUNT_CENTS"],
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
        "stack_group": "GEN",
        "priority_rank": 1,
        "accrual_method": "UNIT_BASED",
    }
    payload.update(overrides)
    return payload


def create_finance_program_payload(**overrides) -> dict:
    payload = create_program_payload(
        name="August Finance Subvention",
        incentive_type="FINANCE_SUBVENTION",
        per_unit_amount_cents=0,
        apr_buydown_bps=300,
    )
    payload.update(overrides)
    return payload


def create_lease_program_payload(**overrides) -> dict:
    payload = create_program_payload(
        name="August Lease Support",
        incentive_type="LEASE_SUPPORT",
        per_unit_amount_cents=100000,
        residual_support_bps=400,
    )
    payload.update(overrides)
    return payload


def create_stair_step_program_payload(**overrides) -> dict:
    payload = create_program_payload(
        name="August Dealer Stair Step",
        incentive_type="DEALER_STAIR_STEP",
        per_unit_amount_cents=0,
        tier_schedule=[
            {"tier_index": 1, "threshold_bps": 5000, "per_unit_bonus_cents": 30000},
            {"tier_index": 2, "threshold_bps": 10000, "per_unit_bonus_cents": 50000},
        ],
        tier_bonus_mode="MARGINAL",
    )
    payload.update(overrides)
    return payload


# --- EligibilityRule --------------------------------------------------------


def create_eligibility_rule_payload(**overrides) -> dict:
    payload = {
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "build_date_from": BUILD_FROM,
        "build_date_to": BUILD_TO,
        "allowed_deal_types": ["CASH"],
    }
    payload.update(overrides)
    return payload


# --- StackabilityConstraint -------------------------------------------------


def create_stackability_constraint_payload(program_b_id: str, mode: str = "ALLOWED",
                                           **overrides) -> dict:
    payload = {"program_b_id": program_b_id, "mode": mode}
    if mode == "CAPPED_TOTAL":
        payload["cap_amount_cents"] = overrides.pop("cap_amount_cents", 400000)
    payload.update(overrides)
    return payload


# --- Dealer -----------------------------------------------------------------


def create_dealer_payload(**overrides) -> dict:
    payload = {
        "dealer_code": unique_dealer_code(),
        "name": "Harborview Motors",
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "historical_volume_units": TEST_DEFAULTS["HISTORICAL_VOLUME_UNITS"],
        "market_opportunity_bps": 0,
    }
    payload.update(overrides)
    return payload


def set_dealer_status_payload(status: str, **overrides) -> dict:
    payload = {"status": status}
    payload.update(overrides)
    return payload


# --- DealerObjective / ObjectiveProtest -------------------------------------


def create_objective_payload(dealer_id: str, **overrides) -> dict:
    payload = {"dealer_id": dealer_id, "stretch_bps": 0}
    payload.update(overrides)
    return payload


def create_protest_payload(claimed_basis_units: int, **overrides) -> dict:
    payload = {
        "claimed_basis_units": claimed_basis_units,
        "reason": "Fleet units were omitted from the historical basis.",
    }
    payload.update(overrides)
    return payload


def resolve_protest_payload(resolution: str, expected_objective_version: int,
                            **overrides) -> dict:
    payload = {
        "resolution": resolution,
        "expected_objective_version": expected_objective_version,
    }
    payload.update(overrides)
    return payload


# --- RetailDelivery ---------------------------------------------------------


def create_delivery_payload(dealer_id: str, **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "vin": unique_vin(),
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
        "trim_code": TEST_DEFAULTS["TRIM_CODE"],
        "build_date": "2026-06-01T00:00:00.000Z",
        "msrp_cents": TEST_DEFAULTS["MSRP_CENTS"],
        # The default sale instant equals the clock's startup default, so the
        # reporting lag is 0 and back_dated_flag stays false.
        "sale_date": AUG_01,
        "customer_region_code": TEST_DEFAULTS["REGION_CODE"],
        "deal_type": "CASH",
    }
    payload.update(overrides)
    return payload


def create_finance_delivery_payload(dealer_id: str, **overrides) -> dict:
    payload = create_delivery_payload(
        dealer_id,
        deal_type="FINANCE",
        term_months=60,
        contract_apr_bps=199,
    )
    payload.update(overrides)
    return payload


def create_lease_delivery_payload(dealer_id: str, **overrides) -> dict:
    payload = create_delivery_payload(
        dealer_id,
        deal_type="LEASE",
        term_months=36,
        base_residual_bps=5200,
    )
    payload.update(overrides)
    return payload


def reject_delivery_payload(reason: str = "The reported sale could not be "
                                          "corroborated.", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def unwind_delivery_payload(reason: str = "Customer financing fell through; the "
                                          "retail contract was unwound.",
                            **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# --- Claim ------------------------------------------------------------------


def create_claim_payload(delivery_id: str, program_id: str,
                         claimed_amount_cents: int,
                         expected_program_version: int, **overrides) -> dict:
    payload = {
        "delivery_id": delivery_id,
        "program_id": program_id,
        "claimed_amount_cents": claimed_amount_cents,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_chargeback_payload(reason: str, **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# --- PaymentBatch -----------------------------------------------------------


def create_payment_batch_payload(**overrides) -> dict:
    payload = {
        "batch_code": unique_batch_code(),
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "period_start": "2026-08-01T00:00:00.000Z",
        "period_end": "2026-08-31T00:00:00.000Z",
        "scheduled_pay_date": "2026-09-10T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def schedule_claims_payload(claim_ids, **overrides) -> dict:
    payload = {"claim_ids": list(claim_ids)}
    payload.update(overrides)
    return payload


# --- BudgetAccrual / RepricingEvent -----------------------------------------


def run_accrual_payload(period_month: str = "2026-08", **overrides) -> dict:
    payload = {"period_month": period_month}
    payload.update(overrides)
    return payload


def create_repricing_payload(mode: str, new_per_unit_amount_cents: int,
                             expected_program_version: int, **overrides) -> dict:
    payload = {
        "mode": mode,
        "new_per_unit_amount_cents": new_per_unit_amount_cents,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


# --- Logical clock ----------------------------------------------------------


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
