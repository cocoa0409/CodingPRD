"""Reusable assertion helpers: entity shape checks and domain invariants."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# Fields every versioned resource carries (PRD §2.4).
_COMMON_VERSIONED = ("id", "created_at", "updated_at", "version")


def assert_common_fields(entity: dict) -> None:
    """id is a server-minted UUID, the two timestamps are ISO 8601 instants and
    version is a positive integer."""
    for field in _COMMON_VERSIONED:
        assert field in entity, f"missing common field {field!r}: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and not isinstance(
        entity["version"], bool
    ), f"version must be an integer: {entity['version']!r}"
    assert entity["version"] >= 1, f"version must start at 1: {entity['version']}"


def assert_append_only_fields(entity: dict) -> None:
    """The two append-only configuration resources carry id and created_at only:
    they have no updated_at and no version at all."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "append-only resource must not carry updated_at"
    assert "version" not in entity, "append-only resource must not carry version"


def assert_fields_present(entity: dict, fields) -> None:
    missing = [f for f in fields if f not in entity]
    assert not missing, f"response is missing fields {missing}: {sorted(entity)}"


def assert_money(entity: dict, field: str, expected: int) -> None:
    """A money field is an integer number of cents, never a string or a float."""
    actual = entity.get(field)
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} cents, got {actual}"


def assert_bps(entity: dict, field: str, expected: int) -> None:
    """A rate field is an integer number of basis points."""
    actual = entity.get(field)
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of basis points, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected} bps, got {actual}"


def assert_int_field(entity: dict, field: str, expected: int) -> None:
    actual = entity.get(field)
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{field}: expected {expected}, got {actual}"


def assert_status(entity: dict, expected: str) -> None:
    assert entity.get("status") == expected, (
        f"expected status {expected}, got {entity.get('status')!r}"
    )


def assert_version(entity: dict, expected: int) -> None:
    assert entity.get("version") == expected, (
        f"expected version {expected}, got {entity.get('version')!r}"
    )


# --- Per-resource shape assertions ------------------------------------------

PROGRAM_FIELDS = (
    "program_code",
    "name",
    "incentive_type",
    "status",
    "effective_from",
    "effective_to",
    "per_unit_amount_cents",
    "apr_buydown_bps",
    "residual_support_bps",
    "projected_take_rate_bps",
    "budget_cents",
    "stack_group",
    "priority_rank",
    "tier_bonus_mode",
    "accrual_method",
    "supersedes_program_id",
    "submitted_by_user_id",
    "approved_by_user_id",
    "committed_cents",
    "paid_cents",
    "accrued_budget_cents",
    "claimed_units",
    "per_unit_spend_cents",
    "residual_impact_bps",
)


def assert_program_shape(program: dict) -> None:
    assert_common_fields(program)
    assert_fields_present(program, PROGRAM_FIELDS)
    assert is_iso8601_timestamp(program["effective_from"]), program["effective_from"]
    assert is_iso8601_timestamp(program["effective_to"]), program["effective_to"]


DEALER_FIELDS = (
    "dealer_code",
    "name",
    "region_code",
    "status",
    "historical_volume_units",
    "market_opportunity_bps",
    "paid_cents",
    "open_chargeback_cents",
)


def assert_dealer_shape(dealer: dict) -> None:
    assert_common_fields(dealer)
    assert_fields_present(dealer, DEALER_FIELDS)


OBJECTIVE_FIELDS = (
    "program_id",
    "dealer_id",
    "status",
    "basis_units",
    "stretch_bps",
    "objective_units",
    "achieved_units",
    "attainment_bps",
    "tier_attained",
    "payout_cents",
    "paid_payout_cents",
    "protest_round",
)


def assert_objective_shape(objective: dict) -> None:
    assert_common_fields(objective)
    assert_fields_present(objective, OBJECTIVE_FIELDS)


PROTEST_FIELDS = (
    "objective_id",
    "round_index",
    "status",
    "claimed_basis_units",
    "reason",
    "resolved_units",
    "resolved_by_user_id",
)


def assert_protest_shape(protest: dict) -> None:
    assert_common_fields(protest)
    assert_fields_present(protest, PROTEST_FIELDS)


DELIVERY_FIELDS = (
    "dealer_id",
    "vin",
    "model_code",
    "trim_code",
    "build_date",
    "msrp_cents",
    "sale_date",
    "customer_region_code",
    "deal_type",
    "status",
    "reported_at",
    "reporting_lag_days",
    "back_dated_flag",
    "validated_by_user_id",
    "unwound_at",
)


def assert_delivery_shape(delivery: dict) -> None:
    assert_common_fields(delivery)
    assert_fields_present(delivery, DELIVERY_FIELDS)
    assert isinstance(delivery["back_dated_flag"], bool), (
        f"back_dated_flag must be a boolean, got {delivery['back_dated_flag']!r}"
    )
    assert is_iso8601_timestamp(delivery["reported_at"]), delivery["reported_at"]


CLAIM_FIELDS = (
    "delivery_id",
    "program_id",
    "dealer_id",
    "claim_type",
    "claimed_amount_cents",
    "snapshot_per_unit_cents",
    "approved_amount_cents",
    "rate_basis",
    "validation_status",
    "payment_status",
    "payment_batch_id",
    "rejection_error_id",
    "adjudicated_by_user_id",
    "paid_at",
)


def assert_claim_shape(claim: dict) -> None:
    assert_common_fields(claim)
    assert_fields_present(claim, CLAIM_FIELDS)


BATCH_FIELDS = (
    "batch_code",
    "region_code",
    "period_start",
    "period_end",
    "scheduled_pay_date",
    "status",
    "claim_count",
    "total_cents",
    "held_claim_count",
    "disbursed_at",
)


def assert_batch_shape(batch: dict) -> None:
    assert_common_fields(batch)
    assert_fields_present(batch, BATCH_FIELDS)


CHARGEBACK_FIELDS = (
    "claim_id",
    "reason",
    "amount_cents",
    "status",
    "created_by_user_id",
    "recovered_at",
)


def assert_chargeback_shape(chargeback: dict) -> None:
    assert_common_fields(chargeback)
    assert_fields_present(chargeback, CHARGEBACK_FIELDS)


ACCRUAL_FIELDS = (
    "program_id",
    "period_month",
    "entry_type",
    "accrual_method",
    "accrued_cents",
    "reversal_cents",
    "unit_basis",
    "source_reference",
)


def assert_accrual_shape(accrual: dict) -> None:
    assert_common_fields(accrual)
    assert_fields_present(accrual, ACCRUAL_FIELDS)


REPRICING_FIELDS = (
    "program_id",
    "mode",
    "previous_per_unit_amount_cents",
    "new_per_unit_amount_cents",
    "effective_at",
    "month_start",
    "affected_claim_count",
    "net_adjustment_cents",
)


def assert_repricing_shape(repricing: dict) -> None:
    assert_common_fields(repricing)
    assert_fields_present(repricing, REPRICING_FIELDS)


ELIGIBILITY_RULE_FIELDS = (
    "program_id",
    "model_code",
    "trim_code",
    "region_code",
    "build_date_from",
    "build_date_to",
    "min_msrp_cents",
    "max_msrp_cents",
    "allowed_deal_types",
)


def assert_eligibility_rule_shape(rule: dict) -> None:
    assert_append_only_fields(rule)
    assert_fields_present(rule, ELIGIBILITY_RULE_FIELDS)


STACK_CONSTRAINT_FIELDS = ("program_a_id", "program_b_id", "mode", "cap_amount_cents")


def assert_stack_constraint_shape(constraint: dict) -> None:
    assert_append_only_fields(constraint)
    assert_fields_present(constraint, STACK_CONSTRAINT_FIELDS)


# --- Domain invariants -------------------------------------------------------


def assert_program_money(program: dict, committed_cents: int, paid_cents: int,
                         claimed_units: int) -> None:
    """The three derived money and unit counters of a program at once."""
    assert_money(program, "committed_cents", committed_cents)
    assert_money(program, "paid_cents", paid_cents)
    assert_int_field(program, "claimed_units", claimed_units)


def assert_dealer_money(dealer: dict, paid_cents: int,
                        open_chargeback_cents: int) -> None:
    assert_money(dealer, "paid_cents", paid_cents)
    assert_money(dealer, "open_chargeback_cents", open_chargeback_cents)


def assert_objective_attainment(objective: dict, achieved_units: int,
                                attainment_bps: int, tier_attained: int,
                                payout_cents: int) -> None:
    assert_int_field(objective, "achieved_units", achieved_units)
    assert_bps(objective, "attainment_bps", attainment_bps)
    assert_int_field(objective, "tier_attained", tier_attained)
    assert_money(objective, "payout_cents", payout_cents)


def assert_claim_amounts(claim: dict, claimed_amount_cents: int,
                         snapshot_per_unit_cents: int,
                         approved_amount_cents=None) -> None:
    assert_money(claim, "claimed_amount_cents", claimed_amount_cents)
    assert_money(claim, "snapshot_per_unit_cents", snapshot_per_unit_cents)
    if approved_amount_cents is None:
        assert claim.get("approved_amount_cents") is None, (
            f"approved_amount_cents should be null, got "
            f"{claim.get('approved_amount_cents')!r}"
        )
    else:
        assert_money(claim, "approved_amount_cents", approved_amount_cents)


def assert_claim_dimensions(claim: dict, validation_status: str,
                            payment_status: str) -> None:
    """The validation dimension and the payment dimension advance independently."""
    assert claim.get("validation_status") == validation_status, (
        f"expected validation_status {validation_status}, "
        f"got {claim.get('validation_status')!r}"
    )
    assert claim.get("payment_status") == payment_status, (
        f"expected payment_status {payment_status}, "
        f"got {claim.get('payment_status')!r}"
    )


SPEND_SUMMARY_FIELDS = (
    "program_id",
    "claimed_units",
    "committed_cents",
    "paid_cents",
    "accrued_budget_cents",
    "per_unit_spend_cents",
    "residual_impact_bps",
    "budget_remaining_cents",
)


def assert_spend_summary(summary: dict, program_id: str, claimed_units: int,
                         committed_cents: int, paid_cents: int,
                         accrued_budget_cents: int, per_unit_spend_cents: int,
                         residual_impact_bps: int,
                         budget_remaining_cents: int) -> None:
    """The whole computed financial picture of one program, field by field."""
    assert_fields_present(summary, SPEND_SUMMARY_FIELDS)
    assert summary["program_id"] == program_id, (
        f"program_id: expected {program_id}, got {summary['program_id']!r}"
    )
    assert_int_field(summary, "claimed_units", claimed_units)
    assert_money(summary, "committed_cents", committed_cents)
    assert_money(summary, "paid_cents", paid_cents)
    assert_money(summary, "accrued_budget_cents", accrued_budget_cents)
    assert_money(summary, "per_unit_spend_cents", per_unit_spend_cents)
    assert_bps(summary, "residual_impact_bps", residual_impact_bps)
    assert_money(summary, "budget_remaining_cents", budget_remaining_cents)


def assert_null_fields(entity: dict, fields) -> None:
    for field in fields:
        assert field in entity, f"missing field {field!r}: {sorted(entity)}"
        assert entity[field] is None, (
            f"{field} should be null, got {entity[field]!r}"
        )


def assert_list_length(rows, expected: int, label: str = "rows") -> None:
    assert len(rows) == expected, (
        f"expected exactly {expected} {label}, got {len(rows)}: {rows}"
    )


def assert_ids_equal(rows, expected_ids, label: str = "rows") -> None:
    """Compare a listing's ids as an unordered set."""
    actual = {row["id"] for row in rows}
    assert actual == set(expected_ids), (
        f"{label}: expected ids {sorted(set(expected_ids))}, got {sorted(actual)}"
    )


def assert_id_order(rows, expected_ids, label: str = "rows") -> None:
    """Compare a listing's ids as an ordered sequence."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"{label}: expected id order {list(expected_ids)}, got {actual}"
    )


def assert_pagination_meta(meta: dict, total_count: int, limit: int, offset: int,
                           has_more=None) -> None:
    """The four pagination meta fields of a listing envelope."""
    assert meta.get("total_count") == total_count, (
        f"meta.total_count: expected {total_count}, got {meta!r}"
    )
    assert meta.get("limit") == limit, f"meta.limit: expected {limit}, got {meta!r}"
    assert meta.get("offset") == offset, f"meta.offset: expected {offset}, got {meta!r}"
    if has_more is not None:
        assert meta.get("has_more") is has_more, (
            f"meta.has_more: expected {has_more}, got {meta!r}"
        )


def assert_echoes(written: dict, read: dict, fields) -> None:
    """Every write response already equals the read that follows it."""
    for field in fields:
        assert written.get(field) == read.get(field), (
            f"{field} diverged: write returned {written.get(field)!r} but the "
            f"following read returned {read.get(field)!r}"
        )


def assert_identical_entity(written: dict, read: dict) -> None:
    """The whole payload of a write is byte-for-byte the payload of the read."""
    assert written == read, (
        "write response and subsequent read differ:\n"
        f"  keys only in write: {sorted(set(written) - set(read))}\n"
        f"  keys only in read: {sorted(set(read) - set(written))}\n"
        f"  differing values: "
        f"{ {k: (written[k], read[k]) for k in set(written) & set(read) if written[k] != read[k]} }"
    )
