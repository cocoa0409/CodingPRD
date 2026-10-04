"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` checks the shape the PRD promises: the common
system-managed fields plus the entity's own declared fields and enum sets.
Monetary values are asserted as integer cents.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BuyerStatus,
    Channel,
    CommissionTier,
    DisputeStatus,
    LicenseGrantStatus,
    LicenseType,
    ModerationStatus,
    OrderStatus,
    PayoutLineKind,
    PayoutStatus,
    ReRecordRequestStatus,
    SettlementStatus,
    TalentAvailability,
    TalentStatus,
    TaxDocumentStatus,
    UseType,
)


def _assert_common(data, label):
    assert is_valid_uuid(data.get("id", "")), "{0}.id must be a UUID".format(label)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "{0}.created_at must be ISO 8601".format(label)
    )
    assert isinstance(data.get("version"), int), "{0}.version must be an int".format(label)


def _assert_cents(data, field, label, minimum=0):
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        "{0}.{1} must be an integer number of cents".format(label, field)
    )
    assert value >= minimum, "{0}.{1} must be >= {2}, got {3}".format(
        label, field, minimum, value
    )


def assert_talent(data):
    _assert_common(data, "Talent")
    assert isinstance(data.get("stage_name"), str) and 1 <= len(data["stage_name"]) <= 80
    assert isinstance(data.get("legal_name"), str)
    assert isinstance(data.get("email"), str)
    assert data.get("status") in {s.value for s in TalentStatus}
    assert data.get("availability") in {a.value for a in TalentAvailability}
    assert data.get("commission_tier") in {t.value for t in CommissionTier}
    _assert_cents(data, "trailing_gmv_cents", "Talent")
    _assert_cents(data, "pending_balance_cents", "Talent")
    _assert_cents(data, "paid_out_balance_cents", "Talent")
    assert isinstance(data.get("availability_pause_count_30d"), int)


def assert_buyer(data):
    _assert_common(data, "Buyer")
    assert isinstance(data.get("email"), str)
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("is_business_account"), bool)
    assert data.get("status") in {s.value for s in BuyerStatus}
    _assert_cents(data, "wallet_credit_cents", "Buyer")


def assert_order(data):
    _assert_common(data, "Order")
    assert is_valid_uuid(data.get("talent_id", ""))
    assert is_valid_uuid(data.get("buyer_id", ""))
    assert data.get("use_type") in {u.value for u in UseType}
    assert data.get("status") in {s.value for s in OrderStatus}
    _assert_cents(data, "gross_amount_cents", "Order")
    assert isinstance(data.get("screening_flags"), list)
    assert isinstance(data.get("re_record_count"), int)
    _assert_cents(data, "refund_amount_cents", "Order")


def assert_video(data):
    _assert_common(data, "Video")
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data.get("content_url"), str)
    duration = data.get("duration_seconds")
    assert isinstance(duration, int) and 5 <= duration <= 600, (
        "Video.duration_seconds must lie within 5..600"
    )
    assert isinstance(data.get("version_no"), int) and data["version_no"] >= 1
    assert data.get("moderation_status") in {s.value for s in ModerationStatus}


def assert_rerecord_request(data):
    _assert_common(data, "ReRecordRequest")
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data.get("notes"), str) and 1 <= len(data["notes"]) <= 1000
    assert data.get("status") in {s.value for s in ReRecordRequestStatus}


def assert_license_grant(data):
    _assert_common(data, "LicenseGrant")
    assert is_valid_uuid(data.get("order_id", ""))
    assert data.get("license_type") in {t.value for t in LicenseType}
    channels = data.get("channels")
    assert isinstance(channels, list) and len(channels) >= 1
    assert set(channels) <= {c.value for c in Channel}
    _assert_cents(data, "fee_cents", "LicenseGrant")
    assert data.get("status") in {s.value for s in LicenseGrantStatus}


def assert_payout_line(data):
    _assert_common(data, "PayoutLine")
    assert is_valid_uuid(data.get("talent_id", ""))
    assert data.get("kind") in {k.value for k in PayoutLineKind}
    assert isinstance(data.get("amount_cents"), int) and not isinstance(
        data.get("amount_cents"), bool
    )
    assert data.get("settlement_status") in {s.value for s in SettlementStatus}


def assert_payout(data):
    _assert_common(data, "Payout")
    assert is_valid_uuid(data.get("talent_id", ""))
    assert data.get("status") in {s.value for s in PayoutStatus}
    _assert_cents(data, "total_cents", "Payout")


def assert_tax_document(data):
    _assert_common(data, "TaxDocument")
    assert is_valid_uuid(data.get("talent_id", ""))
    assert data.get("doc_type") in ("W9", "W8BEN")
    last4 = data.get("tax_id_last4")
    assert isinstance(last4, str) and len(last4) == 4 and last4.isalnum()
    assert data.get("status") in {s.value for s in TaxDocumentStatus}
    assert is_iso8601_timestamp(data.get("submitted_at", ""))


def assert_dispute(data):
    _assert_common(data, "Dispute")
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data.get("reason"), str) and 1 <= len(data["reason"]) <= 1000
    assert data.get("status") in {s.value for s in DisputeStatus}


# ─── Domain invariants ────────────────────────────────────────────────────


def assert_balance_conservation(pending_before, paid_before, pending_after, paid_after):
    """The sum pending + paid is invariant across a payout completion."""

    assert pending_after + paid_after == pending_before + paid_before, (
        "pending + paid must be conserved: {0}+{1} != {2}+{3}".format(
            pending_after, paid_after, pending_before, paid_before
        )
    )
