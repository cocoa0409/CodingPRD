"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .types import (
    DisputeStatus,
    EscrowStatus,
    GuaranteeKind,
    GuaranteeStatus,
    InspectionReportStatus,
    LeaseDisclosureStatus,
    LeaseTenancyStatus,
    ListingKind,
    ListingStatus,
    OfferStatus,
    ReferralStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"


def _assert_mutable(data: dict, entity: str):
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_seller(data: dict):
    _assert_common(data, "Seller")
    _assert_mutable(data, "Seller")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["seller_state"], str) and len(data["seller_state"]) == 2
    assert data["seller_type"] in ("INDIVIDUAL", "LLC", "TRUST")
    assert isinstance(data["listed_count"], int) and data["listed_count"] >= 0
    assert isinstance(data["bulk_discount_bps"], int) and data["bulk_discount_bps"] >= 0


def assert_buyer(data: dict):
    _assert_common(data, "Buyer")
    _assert_mutable(data, "Buyer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["buyer_state"], str) and len(data["buyer_state"]) == 2
    assert data["entity_type"] in ("INDIVIDUAL", "LLC", "TRUST")
    assert isinstance(data["proof_of_funds_cents"], int)


def assert_listing(data: dict):
    _assert_common(data, "Listing")
    _assert_mutable(data, "Listing")
    assert is_valid_uuid(data.get("seller_id", "")), "Listing.seller_id must be a valid UUID"
    assert isinstance(data["address_line"], str)
    assert isinstance(data["listing_state"], str) and len(data["listing_state"]) == 2
    assert isinstance(data["asking_price_cents"], int) and data["asking_price_cents"] > 0
    assert data["status"] in [s.value for s in ListingStatus]
    assert data["listing_kind"] in [k.value for k in ListingKind]
    assert isinstance(data["seller_asks_confidential"], bool)


def assert_inspection_report(data: dict):
    _assert_common(data, "InspectionReport")
    _assert_mutable(data, "InspectionReport")
    assert data["status"] in [s.value for s in InspectionReportStatus]
    assert data["title_grade"] in ("A", "B", "C")


def assert_lease(data: dict):
    _assert_common(data, "Lease")
    _assert_mutable(data, "Lease")
    assert data["status"] in [s.value for s in LeaseTenancyStatus]
    assert data["disclosure_status"] in [s.value for s in LeaseDisclosureStatus]
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] > 0


def assert_payment_record(data: dict):
    _assert_common(data, "PaymentRecord")
    # Append-only ledger: no updated_at, no version.
    assert "updated_at" not in data, "PaymentRecord must not carry updated_at"
    assert "version" not in data, "PaymentRecord must not carry version"
    assert isinstance(data["late"], bool)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_underwriting_report(data: dict):
    _assert_common(data, "UnderwritingReport")
    assert isinstance(data["projected_noi_cents"], int)
    assert isinstance(data["projected_yield_bps"], int)
    assert isinstance(data["disclosure_limited"], bool)


def assert_offer(data: dict):
    _assert_common(data, "Offer")
    _assert_mutable(data, "Offer")
    assert data["status"] in [s.value for s in OfferStatus]
    assert data["financing_type"] in ("CASH", "CONVENTIONAL", "HARD_MONEY")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["is_out_of_state"], bool)


def assert_escrow(data: dict):
    _assert_common(data, "Escrow")
    _assert_mutable(data, "Escrow")
    assert data["status"] in [s.value for s in EscrowStatus]
    assert isinstance(data["remote_signing_required"], bool)


def assert_property_manager(data: dict):
    _assert_common(data, "PropertyManager")
    _assert_mutable(data, "PropertyManager")
    assert isinstance(data["markets"], list)


def assert_management_referral(data: dict):
    _assert_common(data, "ManagementReferral")
    _assert_mutable(data, "ManagementReferral")
    assert data["status"] in [s.value for s in ReferralStatus]


def assert_guarantee(data: dict):
    _assert_common(data, "Guarantee")
    _assert_mutable(data, "Guarantee")
    assert data["status"] in [s.value for s in GuaranteeStatus]
    assert data["guarantee_kind"] in [k.value for k in GuaranteeKind]


def assert_dispute(data: dict):
    _assert_common(data, "Dispute")
    _assert_mutable(data, "Dispute")
    assert data["status"] in [s.value for s in DisputeStatus]
    assert data["opened_by"] in ("BUYER", "SELLER")


def assert_instants_equal(actual: str, expected_iso: str, what: str = "instant"):
    assert canonical_instant(actual) == canonical_instant(expected_iso), (
        f"{what}: expected {expected_iso}, got {actual}"
    )
