"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CARRIER_STATUSES = ["ACTIVE", "SUSPENDED"]
AGREEMENT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED"]
PERIOD_STATUSES = ["OPEN", "CLOSED", "SETTLED"]
PRORATION_STATUSES = ["UNPRORATED", "PROVISIONAL", "FINAL", "REPRORATION_REQUIRED"]
BILLING_STATUSES = ["UNBILLED", "BILLED", "SETTLED", "DISPUTED"]
COUPON_STATUSES = ["OPEN", "FLOWN", "VOID", "ADJUSTED"]
ALLOCATION_BASES = ["UNALLOCATED", "STRAIGHT_RATE", "SPA_FLAT", "SPA_PERCENT"]
FFP_TIERS = ["NONE", "TIER_A", "TIER_B", "TIER_C"]
INVOICE_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "CLEARED",
    "PARTIALLY_REJECTED",
    "FULLY_REJECTED",
    "SETTLED",
]
MEMO_STATUSES = [
    "RAISED",
    "COUNTERED",
    "ACCEPTED",
    "WITHDRAWN",
    "ARBITRATION",
    "RESOLVED_UPHELD",
    "RESOLVED_DENIED",
]
AGING_BUCKETS = ["CURRENT", "AGED_30", "AGED_60", "AGED_90"]
SAMPLE_STATUSES = [
    "DRAWN",
    "IN_REVIEW",
    "CLOSED_IMMATERIAL",
    "CLAIM_RAISED",
    "CLAIM_ACCEPTED",
    "CLAIM_DENIED",
]
CURRENCIES = ["USD", "EUR", "GBP", "JPY"]


# --------------------------------------------------------------------------- #
# Shared system-field helpers
# --------------------------------------------------------------------------- #
def assert_versioned_row(data):
    """A row that carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_row(data):
    """A ledger row: id + created_at only, with no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only rows must not expose updated_at"
    assert "version" not in data, "append-only rows must not expose version"


def assert_bare_uuid(value):
    assert is_valid_uuid(value), f"expected a bare UUID with no type prefix, got {value!r}"
    assert len(value) == 36, f"expected a 36-character UUID, got {value!r}"


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #
def assert_carrier(data):
    assert_versioned_row(data)
    assert isinstance(data["iata_code"], str) and len(data["iata_code"]) == 2
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["base_currency"] in CURRENCIES
    assert isinstance(data["credit_limit_minor"], int) and data["credit_limit_minor"] >= 0
    assert data["status"] in CARRIER_STATUSES
    for field in (
        "pending_receivable_minor",
        "pending_payable_minor",
        "settled_receivable_minor",
        "settled_payable_minor",
        "net_position_minor",
        "period_accrued_miles",
        "period_ffp_cost_estimate_minor",
        "period_ffp_cost_trued_up_minor",
        "ffp_true_up_delta_minor",
        "open_reproration_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["audit_flag"], bool)
    assert_carrier_net_position(data)


def assert_carrier_net_position(data):
    """net_position_minor is the receivable sides less the payable sides."""
    expected = (
        data["pending_receivable_minor"] + data["settled_receivable_minor"]
    ) - (data["pending_payable_minor"] + data["settled_payable_minor"])
    assert data["net_position_minor"] == expected, (
        f"net_position_minor should be {expected}, got {data['net_position_minor']}"
    )


def assert_agreement(data):
    assert_versioned_row(data)
    assert is_valid_uuid(data["issuing_carrier_id"])
    assert is_valid_uuid(data["partner_carrier_id"])
    assert data["agreement_type"] in ["STRAIGHT_RATE", "SPA_FLAT", "SPA_PERCENT"]
    assert data["settlement_currency"] in CURRENCIES
    assert data["status"] in AGREEMENT_STATUSES
    assert data["suspension_reason"] in ["NONE", "OPERATOR_SUSPENDED", "CARRIER_SUSPENDED"]
    assert isinstance(data["factor_count"], int) and data["factor_count"] >= 0


def assert_factor(data):
    assert_versioned_row(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["origin"] == "*" or (len(data["origin"]) == 3 and data["origin"].isupper())
    assert data["destination"] == "*" or (
        len(data["destination"]) == 3 and data["destination"].isupper()
    )
    assert data["class_of_service"] in ["ECONOMY", "PREMIUM", "BUSINESS", "FIRST"]
    assert data["specificity_score"] in (0, 1, 2)


def assert_specificity_score(data):
    """specificity_score counts the concrete, non-wildcarded station fields."""
    expected = (1 if data["origin"] != "*" else 0) + (1 if data["destination"] != "*" else 0)
    assert data["specificity_score"] == expected, (
        f"specificity_score should be {expected} for "
        f"{data['origin']}/{data['destination']}, got {data['specificity_score']}"
    )


def assert_period(data):
    assert_versioned_row(data)
    assert isinstance(data["period_code"], str) and len(data["period_code"]) > 0
    assert data["settlement_currency"] in CURRENCIES
    assert data["status"] in PERIOD_STATUSES
    assert isinstance(data["cleared_invoice_count"], int)


def assert_ticket(data):
    assert_versioned_row(data)
    assert isinstance(data["ticket_number"], str)
    assert is_valid_uuid(data["validating_carrier_id"])
    assert data["sale_currency"] in CURRENCIES
    assert isinstance(data["total_fare_minor"], int) and data["total_fare_minor"] > 0
    assert data["proration_status"] in PRORATION_STATUSES
    assert data["billing_status"] in BILLING_STATUSES
    assert isinstance(data["coupon_count"], int) and data["coupon_count"] >= 0
    assert isinstance(data["unallocated_residual_minor"], int)
    assert data["last_run_type"] in ["NONE", "PROVISIONAL", "FINAL"]


def assert_coupon(data):
    assert_versioned_row(data)
    assert is_valid_uuid(data["ticket_id"])
    assert isinstance(data["coupon_number"], int) and data["coupon_number"] >= 1
    assert len(data["origin"]) == 3 and len(data["destination"]) == 3
    assert is_valid_uuid(data["operating_carrier_id"])
    assert data["class_of_service"] in ["ECONOMY", "PREMIUM", "BUSINESS", "FIRST"]
    assert isinstance(data["tpm_miles"], int) and data["tpm_miles"] > 0
    assert data["coupon_status"] in COUPON_STATUSES
    assert data["allocation_basis"] in ALLOCATION_BASES
    assert data["ffp_tier"] in FFP_TIERS
    for field in (
        "weight_units",
        "allocated_amount_minor",
        "ffp_miles_awarded",
        "ffp_accrual_cost_minor",
        "adjusted_amount_minor",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_invoice(data):
    assert_versioned_row(data)
    assert is_valid_uuid(data["settlement_period_id"])
    assert is_valid_uuid(data["billing_carrier_id"])
    assert is_valid_uuid(data["billed_carrier_id"])
    assert data["billing_currency"] in CURRENCIES
    assert data["status"] in INVOICE_STATUSES
    for field in (
        "coupon_count",
        "gross_billed_minor",
        "ich_fee_bp",
        "ich_handling_fee_minor",
        "late_submission_penalty_minor",
        "total_claim_minor",
        "provisional_rate_scaled",
        "provisional_settlement_minor",
        "fixed_rate_scaled",
        "final_settlement_minor",
        "fx_variance_minor",
        "disputed_amount_minor",
        "rejected_amount_minor",
        "net_billed_minor",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_memo(data):
    assert_versioned_row(data)
    assert is_valid_uuid(data["invoice_id"])
    assert is_valid_uuid(data["coupon_id"])
    assert is_valid_uuid(data["raised_by_carrier_id"])
    assert data["stage"] in (1, 2, 3)
    assert isinstance(data["amount_minor"], int) and data["amount_minor"] > 0
    assert data["reason_code"] in [
        "PRORATE_FACTOR_DISPUTE",
        "SPA_NOT_APPLIED",
        "FARE_BASIS_ERROR",
        "DUPLICATE_BILLING",
        "CURRENCY_ERROR",
    ]
    assert data["status"] in MEMO_STATUSES
    assert data["aging_bucket"] in AGING_BUCKETS
    assert isinstance(data["age_days"], int) and data["age_days"] >= 0
    assert is_iso8601_timestamp(data["raised_at"])


def assert_audit_sample(data):
    assert_versioned_row(data)
    assert is_valid_uuid(data["auditing_carrier_id"])
    assert is_valid_uuid(data["audited_carrier_id"])
    assert is_valid_uuid(data["settlement_period_id"])
    assert data["claim_currency"] in CURRENCIES
    assert data["status"] in SAMPLE_STATUSES
    for field in (
        "population_coupon_count",
        "population_allocated_minor",
        "sampled_coupon_count",
        "sampled_allocated_minor",
        "sampled_undercharge_minor",
        "findings_count",
        "undercharge_ratio_bp",
        "coverage_bp",
        "haircut_bp",
        "extrapolated_gross_minor",
        "claim_amount_minor",
        "claim_settlement_minor",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_proration_run(data):
    assert_append_only_row(data)
    assert is_valid_uuid(data["ticket_id"])
    assert data["run_type"] in ["PROVISIONAL", "FINAL"]
    for field in (
        "pool_minor",
        "spa_total_minor",
        "straight_rate_pool_minor",
        "total_weight_units",
        "included_coupon_count",
        "rounding_residual_minor",
        "allocated_total_minor",
        "unallocated_residual_minor",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_exchange_rate(data):
    assert_append_only_row(data)
    assert data["from_currency"] in CURRENCIES
    assert data["to_currency"] in CURRENCIES
    assert data["from_currency"] != data["to_currency"]
    assert isinstance(data["rate_scaled"], int) and data["rate_scaled"] > 0


# --------------------------------------------------------------------------- #
# Domain invariants
# --------------------------------------------------------------------------- #
def assert_fare_conservation(ticket, coupons):
    """Every coupon allocation plus the ticket's slack equals the whole fare."""
    allocated = sum(c["allocated_amount_minor"] for c in coupons)
    total = allocated + ticket["unallocated_residual_minor"]
    assert total == ticket["total_fare_minor"], (
        f"fare conservation broken: allocations {allocated} + residual "
        f"{ticket['unallocated_residual_minor']} != fare {ticket['total_fare_minor']}"
    )


def assert_clearinghouse_zero_sum(carriers):
    """Summed across every carrier row, net_position_minor is exactly zero."""
    total = sum(c["net_position_minor"] for c in carriers)
    assert total == 0, (
        "clearing-house zero-sum broken: net_position_minor sums to "
        f"{total} across {len(carriers)} carriers"
    )


def assert_iso_instant_equals(actual, expected_iso):
    """Compare a returned timestamp with an expected UTC instant, ignoring fraction style."""
    assert isinstance(actual, str), f"expected a timestamp string, got {actual!r}"
    got = actual.replace("Z", "").split(".")[0]
    want = expected_iso.replace("Z", "").split(".")[0]
    assert got == want, f"expected instant {expected_iso}, got {actual}"
