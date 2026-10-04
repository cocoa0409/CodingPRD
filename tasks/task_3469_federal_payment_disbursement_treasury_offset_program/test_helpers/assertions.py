"""Entity assertions, envelope helpers, and PRD calculation re-implementations.

The calculation helpers (round_half_up_cents, expected_* ) re-derive expected
values from PRD prose so tests can state literal-cent assertions without
duplicating arithmetic; they encode ONLY rules stated verbatim in the PRD:
  - §2.6 integer cents, round-half-up on every percentage term, per-payment
    rounding before file-level summation
  - §2.9 remittance fee tiers (3% below 60000 pre-event YTD gross, else 2%;
    the current event never counts toward its own tier)
  - §3.4 offset pool: EXEMPT 0, FULL amount, PARTIAL min(base, cap) with the
    0.65 child-support branch; intake estimate applies neither cap nor branch
  - §3.7 AWG: PROVISIONAL round_half_up(0.15 * estimate); STATUTORY_FINAL
    min(0.15 term, max(0, D - 21750)); collected = min(garnishment, balance)
  - §3.6 refund restitution: clawback = min(claimed, net), treasury absorbs the
    withheld fee, refund == clawback + absorbed
"""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AWG_DISPOSABLE_PCT,
    AWG_WEEKLY_FLOOR_CENTS,
    CHILD_SUPPORT_PCT,
    PRIORITY_RANKS,
    REMIT_FEE_PCT_HIGH_BAND,
    REMIT_FEE_PCT_LOW_BAND,
    REMIT_TIER_THRESHOLD_CENTS,
)


# --- PRD calculation re-implementations -----------------------------------------

def round_half_up_cents(value) -> int:
    """Round a numeric value to whole cents, half up (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_remittance_fee_cents(gross_cents: int,
                                  pre_event_gross_ytd_cents: int) -> int:
    """PRD §2.9: 3% while the PRE-EVENT gross YTD is below 60000 cents, else 2%;
    the current event never counts toward its own tier; fee rounded half up."""
    pct = (REMIT_FEE_PCT_LOW_BAND
           if pre_event_gross_ytd_cents < REMIT_TIER_THRESHOLD_CENTS
           else REMIT_FEE_PCT_HIGH_BAND)
    return round_half_up_cents(gross_cents * pct)


def expected_intake_projection(amount_cents: int, exemption_class: str,
                               protected_minimum_cents=None) -> int:
    """PRD §3.4 INTAKE variant: EXEMPT -> 0; FULL -> amount; PARTIAL ->
    max(0, amount - protected_minimum). No percentage cap, no child-support
    branch — the worst-case projection for the submitting agency."""
    if exemption_class == "EXEMPT":
        return 0
    if exemption_class == "FULL":
        return amount_cents
    return max(0, amount_cents - (protected_minimum_cents or 0))


def expected_execution_pool(amount_cents: int, exemption_class: str,
                            protected_minimum_cents=None, max_offset_pct=None,
                            has_child_support_match: bool = False) -> int:
    """PRD §3.4 EXECUTION variant: PARTIAL pool is the lesser of the
    floor-adjusted base and round_half_up(amount * pct), where pct is 0.65 when
    any eligible matched debt is CHILD_SUPPORT, else the policy max_offset_pct."""
    if exemption_class == "EXEMPT":
        return 0
    if exemption_class == "FULL":
        return amount_cents
    base = max(0, amount_cents - (protected_minimum_cents or 0))
    pct = CHILD_SUPPORT_PCT if has_child_support_match else max_offset_pct
    return min(base, round_half_up_cents(amount_cents * pct))


def expected_awg_provisional_cents(disposable_pay_estimate_cents: int) -> int:
    """PRD §3.7 PROVISIONAL projection: 15% of estimated disposable pay, rounded
    half up; the statutory floor is deliberately NOT applied at projection."""
    return round_half_up_cents(AWG_DISPOSABLE_PCT * disposable_pay_estimate_cents)


def expected_awg_garnishment_cents(disposable_pay_cents: int) -> int:
    """PRD §3.7 STATUTORY_FINAL: min(round_half_up(0.15 * D), max(0, D - 21750))."""
    return min(
        round_half_up_cents(AWG_DISPOSABLE_PCT * disposable_pay_cents),
        max(0, disposable_pay_cents - AWG_WEEKLY_FLOOR_CENTS),
    )


def expected_priority_rank(debt_type: str) -> int:
    """PRD §3.3: CHILD_SUPPORT 10, FEDERAL_TAX 20, FEDERAL_NONTAX 30,
    STATE_TAX 40, STATE_OTHER 50; lower ranks offset first."""
    return PRIORITY_RANKS[debt_type]


# --- Envelope / listing helpers (PRD §2.2, §2.3, §2.5, §2.7) ---------------------

def assert_common_fields(data: dict):
    """PRD §2.5: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_created_at_ascending(items: list):
    """PRD §2.3: list endpoints sort by created_at ascending."""
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), f"list not sorted by created_at asc: {stamps}"


def assert_payment_decomposition(payment: dict):
    """PRD §3.5: at EXECUTED, amount_cents == total_offset_cents + disbursed_cents."""
    assert payment["amount_cents"] == (
        payment["total_offset_cents"] + payment["disbursed_cents"]
    ), (
        f"payment decomposition broken: {payment['amount_cents']} != "
        f"{payment['total_offset_cents']} + {payment['disbursed_cents']}"
    )


def assert_refund_conservation(claim: dict):
    """PRD §3.6: refund_amount_cents == clawback_cents + treasury_absorbed_cents,
    and clawback_cents == min(claimed_amount_cents, offset net remittance)."""
    assert claim["refund_amount_cents"] == (
        claim["clawback_cents"] + claim["treasury_absorbed_cents"]
    ), (
        f"refund does not conserve: {claim['refund_amount_cents']} != "
        f"{claim['clawback_cents']} + {claim['treasury_absorbed_cents']}"
    )


def assert_file_totals(payment_file: dict, payments: list):
    """PRD §2.6 / §3.4: file totals are the plain sums of the per-payment
    already-rounded values; payment_count counts the file's payments."""
    assert payment_file["payment_count"] == len(payments)
    assert payment_file["total_offset_cents"] == sum(
        p["total_offset_cents"] for p in payments
    ), "file total_offset_cents must equal the sum of per-payment rounded offsets"
    assert payment_file["total_disbursed_cents"] == sum(
        p["disbursed_cents"] for p in payments
    )


# --- Per-entity shape assertions -------------------------------------------------

def assert_creditor_agency(data: dict):
    assert_common_fields(data)
    assert isinstance(data["creditor_code"], str) and data["creditor_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["creditor_type"] in ("FEDERAL", "STATE")
    if data["creditor_type"] == "STATE":
        assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["remitted_gross_ytd_cents"], int)
    assert data["remitted_ytd_year"] is None or isinstance(data["remitted_ytd_year"], int)
    assert isinstance(data["remitted_net_total_cents"], int)
    assert isinstance(data["outstanding_receivable_cents"], int)


def assert_payee(data: dict):
    assert_common_fields(data)
    assert isinstance(data["tin"], str) and data["tin"]
    assert data["tin_type"] in ("SSN", "EIN")
    assert isinstance(data["legal_name"], str) and data["legal_name"]


def assert_exemption_policy(data: dict):
    assert_common_fields(data)
    assert data["payment_type"] in (
        "VENDOR", "SALARY", "BENEFIT_RETIREMENT",
        "BENEFIT_DISABILITY", "TAX_REFUND", "GRANT",
    )
    assert data["exemption_class"] in ("EXEMPT", "PARTIAL", "FULL")
    if data["exemption_class"] == "PARTIAL":
        assert isinstance(data["protected_minimum_cents"], int)
        assert data["protected_minimum_cents"] >= 0
        assert 0 < data["max_offset_pct"] <= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_debt(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("creditor_agency_id", ""))
    assert isinstance(data["debtor_tin"], str) and data["debtor_tin"]
    assert data["debt_type"] in (
        "CHILD_SUPPORT", "FEDERAL_TAX", "FEDERAL_NONTAX", "STATE_TAX", "STATE_OTHER",
    )
    assert data["priority_rank"] == PRIORITY_RANKS[data["debt_type"]]
    assert isinstance(data["original_amount_cents"], int)
    assert data["original_amount_cents"] > 0
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["returned_count"], int)
    assert isinstance(data["due_process_completed"], bool)
    assert data["status"] in (
        "REFERRED", "NOTICED", "ACTIVE", "IN_COLLECTION", "PAID_IN_FULL", "RETURNED",
    )


def assert_payment_file(data: dict):
    assert_common_fields(data)
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert is_iso8601_timestamp(data.get("settlement_date", ""))
    assert data["status"] in ("RECEIVED", "PROCESSING", "COMPLETED")
    assert isinstance(data["payment_count"], int) and data["payment_count"] >= 0
    assert isinstance(data["total_offset_cents"], int)
    assert isinstance(data["total_disbursed_cents"], int)


def assert_payment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("payment_file_id", ""))
    assert is_valid_uuid(data.get("payee_id", ""))
    assert isinstance(data["payee_tin"], str) and data["payee_tin"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["payment_type"] in (
        "VENDOR", "SALARY", "BENEFIT_RETIREMENT",
        "BENEFIT_DISABILITY", "TAX_REFUND", "GRANT",
    )
    assert data["payment_method"] in ("EFT", "CHECK")
    assert data["processing_status"] in (
        "VERIFIED", "HELD", "EVALUATED", "EXECUTED", "SETTLED", "REVERSED",
    )
    assert data["integrity_status"] in ("CLEAR", "FLAGGED")
    assert isinstance(data["projected_offset_cents"], int)
    assert isinstance(data["total_offset_cents"], int)
    assert isinstance(data["disbursed_cents"], int)


def assert_offset(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("payment_id", ""))
    assert is_valid_uuid(data.get("debt_id", ""))
    assert data["priority_rank"] in PRIORITY_RANKS.values()
    assert isinstance(data["offset_amount_cents"], int)
    assert data["offset_amount_cents"] > 0
    assert data["status"] in ("PROPOSED", "APPLIED", "REVERSED", "REFUNDED", "DROPPED")
    if data["status"] in ("APPLIED", "REVERSED", "REFUNDED"):
        # PRD §3.4/§3.5: fee_cents, net_remittance_cents, applied_at are fixed
        # only at application; they stay null while PROPOSED.
        assert isinstance(data["fee_cents"], int)
        assert isinstance(data["net_remittance_cents"], int)
        assert data["net_remittance_cents"] == data["offset_amount_cents"] - data["fee_cents"]
        assert is_iso8601_timestamp(data.get("applied_at", ""))


def assert_refund_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("offset_id", ""))
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] > 0
    assert data["reason"] in (
        "DEBT_NOT_OWED", "AMOUNT_INCORRECT", "PAYMENT_DUPLICATED", "DEBTOR_MISIDENTIFIED",
    )
    assert data["status"] in ("FILED", "UNDER_REVIEW", "PAID", "DENIED", "APPEALED")
    assert isinstance(data["appeal_count"], int) and 0 <= data["appeal_count"] <= 1


def assert_collection_agency(data: dict):
    assert_common_fields(data)
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_max_active"], int)
    assert data["capacity_max_active"] >= 0


def assert_collection_action(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("debt_id", ""))
    assert data["action_type"] in ("AWG", "CROSS_SERVICING")
    if data["action_type"] == "AWG":
        assert data["collection_agency_id"] is None
        assert is_iso8601_timestamp(data.get("notice_sent_at", ""))
        assert isinstance(data["projected_per_period_cents"], int)
    else:
        assert data["notice_sent_at"] is None
        assert data["projected_per_period_cents"] is None
    assert isinstance(data["collected_total_cents"], int)
    assert data["status"] in ("INITIATED", "ACTIVE", "COMPLETED", "TERMINATED")


def assert_reverse_offset_request(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["payee_tin"], str) and data["payee_tin"]
    assert isinstance(data["requested_amount_cents"], int)
    assert data["requested_amount_cents"] > 0
    assert data["status"] in ("MATCHED", "NO_MATCH", "CONFIRMED", "EXPIRED")
    assert isinstance(data["matches"], list)
    for match in data["matches"]:
        assert is_valid_uuid(match.get("debt_id", ""))
        assert isinstance(match["matched_amount_cents"], int)
        assert match["matched_amount_cents"] > 0
    assert isinstance(data["matched_total_cents"], int)
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_reciprocal_agreement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert data["direction"] in ("FED_TO_STATE", "STATE_TO_FED", "BIDIRECTIONAL")
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_until", ""))
    assert data["effective_from"] < data["effective_until"]
    assert data["status"] in ("DRAFT", "ACTIVE")


def assert_do_not_pay_record(data: dict):
    assert_common_fields(data)
    assert isinstance(data["tin"], str) and data["tin"]
    assert data["list_source"] in (
        "DEATH_MASTER_FILE", "SAM_EXCLUSION", "DEBARMENT_LIST",
    )
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_until", ""))
    assert data["effective_from"] <= data["effective_until"]
    assert data["status"] in ("ACTIVE", "REMOVED")


__all__ = [name for name in dir() if name.startswith(("assert_", "expected_", "round_"))]
