"""Domain assertions built on the framework's primitive validators."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .time_utils import iso_equal

# ── Generic shape helpers (PRD §2.5) ────────────────────────────────────────

MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")


def assert_common_fields(entity, label="resource"):
    """`id`, `created_at`, `updated_at` and `version` per PRD §2.5."""
    for field in MUTABLE_COMMON_FIELDS:
        assert field in entity, f"{label} is missing the common field {field}"
    assert is_valid_uuid(entity["id"]), f"{label}.id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label}.created_at is not ISO-8601: {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"{label}.updated_at is not ISO-8601: {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int) and not isinstance(entity["version"], bool), (
        f"{label}.version must be an integer, got {entity['version']!r}"
    )
    assert entity["version"] >= 1, f"{label}.version must start at 1 or above"


def assert_append_only_record(record, label="append-only record"):
    """A negotiation round or ledger entry carries only `id` and `created_at`."""
    for field in APPEND_ONLY_COMMON_FIELDS:
        assert field in record, f"{label} is missing {field}"
    assert is_valid_uuid(record["id"]), f"{label}.id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), (
        f"{label}.created_at is not ISO-8601: {record['created_at']!r}"
    )
    assert "updated_at" not in record, f"{label} must not expose updated_at"
    assert "version" not in record, f"{label} must not expose version"


def assert_fields(entity, expected, label="resource"):
    """Assert an exact value for every key of `expected`."""
    for field, value in expected.items():
        assert field in entity, f"{label} is missing field {field}"
        assert entity[field] == value, (
            f"{label}.{field}: expected {value!r}, got {entity[field]!r}"
        )


def assert_nulls(entity, fields, label="resource"):
    for field in fields:
        assert field in entity, f"{label} is missing field {field}"
        assert entity[field] is None, (
            f"{label}.{field} should be null, got {entity[field]!r}"
        )


def assert_iso_equals(actual, expected, label="timestamp"):
    assert iso_equal(actual, expected), (
        f"{label}: expected instant {expected!r}, got {actual!r}"
    )


def assert_version_is(entity, expected_version, label="resource"):
    assert entity["version"] == expected_version, (
        f"{label}.version: expected {expected_version}, got {entity['version']}"
    )


# ── Per-entity shapes ───────────────────────────────────────────────────────

MERCHANT_FIELDS = (
    "legal_name", "contact_email", "primary_category", "region_codes", "status",
    "fault_event_count", "last_fault_at", "fulfillment_failure_score",
    "suspended_at", "accrued_commission_payable_cents", "active_agreement_count",
)

AGREEMENT_FIELDS = (
    "merchant_id", "category", "region_code", "status", "round_count",
    "commission_rate_bps", "placement_fee_base_cents", "employer_revenue_share_bps",
    "exclusivity_requested", "exclusivity_granted", "exclusivity_window_start",
    "exclusivity_window_end", "accepted_by_role", "activated_at", "terminated_reason",
)

NEGOTIATION_ROUND_FIELDS = (
    "agreement_id", "round_number", "proposer_role", "commission_rate_bps",
    "placement_fee_base_cents", "employer_revenue_share_bps",
    "exclusivity_window_start", "exclusivity_window_end", "note",
)

EMPLOYER_FIELDS = (
    "name", "region_code", "employee_count_declared", "integration_status",
    "storefront_status", "program_posture", "brand_color_hex", "logo_url",
    "hero_headline", "featured_categories", "revenue_share_enabled",
    "privacy_min_cohort_size", "eligible_headcount", "accrued_share_cents",
    "last_sync_at", "suspension_reason",
)

ELIGIBILITY_FILE_FIELDS = (
    "employer_id", "status", "effective_from", "checksum", "record_count",
    "valid_record_count", "invalid_record_count", "rejection_reason",
    "created_membership_count", "updated_membership_count",
    "suspended_membership_count", "applied_at",
)

MEMBERSHIP_FIELDS = (
    "employer_id", "external_employee_ref", "status", "employment_status",
    "region_code", "eligibility_valid_from", "eligibility_valid_until",
    "source_file_id", "last_employment_change_at", "redemption_count_7d",
    "redemption_count_30d",
)

OFFER_FIELDS = (
    "merchant_id", "agreement_id", "title", "category", "discount_type",
    "discount_value_bps", "discount_value_cents", "min_spend_cents",
    "region_codes", "window_start", "window_end", "status", "inventory_limit",
    "inventory_reserved", "inventory_redeemed", "sold_out", "per_member_limit",
    "review_note", "paused_reason", "expired_at",
)

PLACEMENT_SLOT_FIELDS = (
    "offer_id", "employer_id", "placement_tier", "slot_window_start",
    "slot_window_end", "status", "slot_duration_days", "base_fee_cents",
    "reach_surcharge_bps", "reach_surcharge_cents", "gross_fee_cents",
    "volume_discount_bps", "volume_discount_cents", "placement_fee_cents",
    "confirmed_at", "released_at", "release_reason",
)

REDEMPTION_FIELDS = (
    "offer_id", "membership_id", "employer_id", "merchant_id",
    "intended_gross_amount_cents", "gross_amount_cents", "discount_amount_cents",
    "net_charged_cents", "commission_amount_cents", "employer_share_cents",
    "provider_net_cents", "verification_status", "fulfillment_status",
    "verification_expires_at", "verified_at", "fulfilled_at", "refunded_at",
    "voided_at", "void_reason", "screening_risk_score", "audit_risk_score",
    "risk_block_reason", "statement_id",
)

DISPUTE_FIELDS = (
    "redemption_id", "raised_by_membership_id", "merchant_id", "reason",
    "description", "status", "response_deadline_at", "response_note",
    "remedy_offered_cents", "info_request_count", "outcome_credit_cents",
    "default_judged", "resolved_at",
)

STATEMENT_FIELDS = (
    "employer_id", "period_start", "period_end", "basis", "status",
    "included_redemption_count", "gross_commission_cents", "employer_share_cents",
    "provider_retained_cents", "reversal_adjustment_cents", "finalized_at",
    "reopened_at", "reopen_reason", "paid_at", "payment_reference",
)

LEDGER_ENTRY_FIELDS = (
    "entry_type", "amount_cents", "merchant_id", "employer_id", "redemption_id",
    "placement_slot_id", "statement_id", "memo",
)


def _assert_has_fields(entity, fields, label):
    missing = [field for field in fields if field not in entity]
    assert not missing, f"{label} is missing fields: {missing}"


def assert_merchant_shape(merchant):
    assert_common_fields(merchant, "merchant")
    _assert_has_fields(merchant, MERCHANT_FIELDS, "merchant")


def assert_agreement_shape(agreement):
    assert_common_fields(agreement, "agreement")
    _assert_has_fields(agreement, AGREEMENT_FIELDS, "agreement")


def assert_negotiation_round_shape(round_row):
    assert_append_only_record(round_row, "negotiation round")
    _assert_has_fields(round_row, NEGOTIATION_ROUND_FIELDS, "negotiation round")


def assert_employer_shape(employer):
    assert_common_fields(employer, "employer")
    _assert_has_fields(employer, EMPLOYER_FIELDS, "employer")


def assert_eligibility_file_shape(file_row):
    assert_common_fields(file_row, "eligibility file")
    _assert_has_fields(file_row, ELIGIBILITY_FILE_FIELDS, "eligibility file")


def assert_membership_shape(membership):
    assert_common_fields(membership, "membership")
    _assert_has_fields(membership, MEMBERSHIP_FIELDS, "membership")


def assert_offer_shape(offer):
    assert_common_fields(offer, "offer")
    _assert_has_fields(offer, OFFER_FIELDS, "offer")


def assert_placement_slot_shape(slot):
    assert_common_fields(slot, "placement slot")
    _assert_has_fields(slot, PLACEMENT_SLOT_FIELDS, "placement slot")


def assert_redemption_shape(redemption):
    assert_common_fields(redemption, "redemption")
    _assert_has_fields(redemption, REDEMPTION_FIELDS, "redemption")


def assert_dispute_shape(dispute):
    assert_common_fields(dispute, "dispute")
    _assert_has_fields(dispute, DISPUTE_FIELDS, "dispute")


def assert_statement_shape(statement):
    assert_common_fields(statement, "statement")
    _assert_has_fields(statement, STATEMENT_FIELDS, "statement")


def assert_ledger_entry_shape(entry):
    assert_append_only_record(entry, "ledger entry")
    _assert_has_fields(entry, LEDGER_ENTRY_FIELDS, "ledger entry")


# ── Calculation assertions ──────────────────────────────────────────────────

def assert_line_economics(redemption, gross_amount_cents, discount_amount_cents,
                          net_charged_cents, commission_amount_cents,
                          employer_share_cents, provider_net_cents):
    """The five ordered steps of PRD §3.7."""
    assert_fields(redemption, {
        "gross_amount_cents": gross_amount_cents,
        "discount_amount_cents": discount_amount_cents,
        "net_charged_cents": net_charged_cents,
        "commission_amount_cents": commission_amount_cents,
        "employer_share_cents": employer_share_cents,
        "provider_net_cents": provider_net_cents,
    }, "redemption")
    assert redemption["net_charged_cents"] == (
        redemption["gross_amount_cents"] - redemption["discount_amount_cents"]
    ), "net_charged_cents must be gross less discount"
    assert redemption["provider_net_cents"] == (
        redemption["commission_amount_cents"] - redemption["employer_share_cents"]
    ), "provider_net_cents must be commission less employer share"


def assert_placement_fee_breakdown(slot, slot_duration_days, base_fee_cents,
                                   reach_surcharge_bps, reach_surcharge_cents,
                                   gross_fee_cents, volume_discount_bps,
                                   volume_discount_cents, placement_fee_cents):
    """The five ordered steps of PRD §3.6."""
    assert_fields(slot, {
        "slot_duration_days": slot_duration_days,
        "base_fee_cents": base_fee_cents,
        "reach_surcharge_bps": reach_surcharge_bps,
        "reach_surcharge_cents": reach_surcharge_cents,
        "gross_fee_cents": gross_fee_cents,
        "volume_discount_bps": volume_discount_bps,
        "volume_discount_cents": volume_discount_cents,
        "placement_fee_cents": placement_fee_cents,
    }, "placement slot")
    assert slot["gross_fee_cents"] == (
        slot["base_fee_cents"] + slot["reach_surcharge_cents"]
    ), "gross_fee_cents must be base plus reach surcharge"
    assert slot["placement_fee_cents"] == (
        slot["gross_fee_cents"] - slot["volume_discount_cents"]
    ), "placement_fee_cents must be gross less volume discount"


def assert_integral_cents(entity, fields, label="resource"):
    for field in fields:
        value = entity.get(field)
        if value is None:
            continue
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{label}.{field} must be an integer number of cents, got {value!r}"
        )


# ── Ledger assertions (PRD §3.9) ────────────────────────────────────────────

def ledger_signature(entries):
    """The ordered `(entry_type, amount_cents)` pairs of a ledger listing."""
    return [(entry["entry_type"], entry["amount_cents"]) for entry in entries]


def assert_ledger_signature(entries, expected):
    actual = ledger_signature(entries)
    assert actual == expected, f"ledger entries: expected {expected}, got {actual}"


def assert_ledger_nets_to_zero(entries):
    total = sum(entry["amount_cents"] for entry in entries)
    assert total == 0, (
        f"ledger entries should net to zero, got {total} from {ledger_signature(entries)}"
    )


def ledger_total(entries, entry_types=None):
    return sum(
        entry["amount_cents"] for entry in entries
        if entry_types is None or entry["entry_type"] in entry_types
    )


# ── Pagination (PRD §2.3) ───────────────────────────────────────────────────

def assert_pagination_meta(meta, limit=None, offset=None, total_count=None,
                           has_more=None):
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination meta is missing {field}"
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"meta.offset: expected {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']}"
        )


def assert_ordered_by(rows, field, ascending=True):
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=not ascending)
    assert values == expected, f"rows are not ordered by {field}: {values}"


# ── Privacy and cohort suppression (PRD §2.10) ──────────────────────────────

def category_row(payload, category):
    for row in payload["category_rows"]:
        if row["category"] == category:
            return row
    raise AssertionError(
        f"no category_rows entry for {category}; got "
        f"{[row['category'] for row in payload['category_rows']]}"
    )


def assert_row_suppressed(row, cohort_field):
    assert row["suppressed"] is True, f"row {row['category']} should be suppressed"
    for field in ("redemption_count", "discount_amount_cents", cohort_field):
        assert row[field] is None, (
            f"suppressed row {row['category']}.{field} must be null, got {row[field]!r}"
        )


def assert_row_visible(row, cohort_field, redemption_count=None,
                       discount_amount_cents=None, cohort_value=None):
    assert row["suppressed"] is False, f"row {row['category']} should not be suppressed"
    if redemption_count is not None:
        assert row["redemption_count"] == redemption_count, (
            f"row {row['category']}.redemption_count: expected {redemption_count}, "
            f"got {row['redemption_count']}"
        )
    if discount_amount_cents is not None:
        assert row["discount_amount_cents"] == discount_amount_cents, (
            f"row {row['category']}.discount_amount_cents: expected "
            f"{discount_amount_cents}, got {row['discount_amount_cents']}"
        )
    if cohort_value is not None:
        assert row[cohort_field] == cohort_value, (
            f"row {row['category']}.{cohort_field}: expected {cohort_value}, "
            f"got {row[cohort_field]}"
        )


# ── Epoch sweep (PRD §2.4) ──────────────────────────────────────────────────

SWEEP_COUNTERS = (
    "expired_offer_count", "completed_slot_count", "voided_redemption_count",
    "stale_employer_count", "default_judged_dispute_count",
)


def assert_sweep_counts(sweep, **expected):
    for field in SWEEP_COUNTERS:
        assert field in sweep, f"sweep report is missing {field}"
    for field, value in expected.items():
        assert sweep[field] == value, (
            f"sweep.{field}: expected {value}, got {sweep[field]}"
        )


def assert_sweep_idle(sweep):
    for field in SWEEP_COUNTERS:
        assert sweep[field] == 0, (
            f"an idempotent re-run must report 0 for {field}, got {sweep[field]}"
        )
