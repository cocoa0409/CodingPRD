"""Entity assertions, instant comparison helpers and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Instant helpers ──────────────────────────────────────────────────────────

def normalize_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime.

    The API renders instants with three fractional-second digits; expected
    values in the tests may be written without them. Comparing parsed instants
    rather than raw strings keeps the two forms equivalent.
    """
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected, label="instant"):
    """Assert two ISO 8601 UTC instants denote the same moment."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_three_fractional_digits(value: str, label="timestamp"):
    """Assert a timestamp is an ISO 8601 UTC instant with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601 UTC, got {value!r}"
    assert "." in value, f"{label} must carry fractional seconds, got {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional-second digits, got {value!r}"
    )


# ─── Common resource properties ───────────────────────────────────────────────

def assert_common_fields(data: dict, entity_label="resource"):
    """Assert the id / created_at / updated_at / version quartet every resource
    except the escrow ledger row carries."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert_three_fractional_digits(data.get("created_at"), f"{entity_label}.created_at")
    assert_three_fractional_digits(data.get("updated_at"), f"{entity_label}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"
    assert data["version"] >= 1, f"{entity_label}.version starts at 1"


def assert_append_only_fields(data: dict, entity_label="ledger entry"):
    """Assert the immutable escrow ledger row carries id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert_three_fractional_digits(data.get("created_at"), f"{entity_label}.created_at")
    assert "updated_at" not in data, f"{entity_label} has no updated_at"
    assert "version" not in data, f"{entity_label} has no version"


def assert_money(value, label="amount"):
    """Assert a monetary amount is an integer count of whole cents, not a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of whole cents, got {value!r}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_county(data: dict):
    assert_common_fields(data, "County")
    assert isinstance(data["county_code"], str) and 2 <= len(data["county_code"]) <= 8
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper()
    assert isinstance(data["quota_licenses_total"], int) and data["quota_licenses_total"] >= 1
    assert isinstance(data["permitted_zoning_codes"], list)
    assert isinstance(data["distance_min_feet_school"], int)
    assert isinstance(data["distance_min_feet_church"], int)
    assert isinstance(data["posting_period_days"], int)
    assert isinstance(data["protest_window_days"], int)
    assert isinstance(data["transfer_fee_bps"], int)
    assert data["default_valuation_basis"] in ("COMPARABLE_SALES", "INCOME_MULTIPLE")
    assert_county_quota_invariants(data)


def assert_county_quota_invariants(data: dict):
    """quota_available is quota_licenses_total minus the counted figure, floored
    at zero; the utilization is an integer basis-point value."""
    assert isinstance(data["quota_licenses_counted"], int)
    assert isinstance(data["quota_available"], int)
    assert isinstance(data["quota_utilization_bps"], int)
    assert isinstance(data["escrow_committed_count"], int)
    assert data["quota_available"] >= 0, "quota_available is floored at zero"
    assert data["quota_available"] == max(
        0, data["quota_licenses_total"] - data["quota_licenses_counted"]
    ), (
        "quota_available must be quota_licenses_total minus quota_licenses_counted, "
        "floored at zero"
    )
    assert data["escrow_committed_count"] >= 0


def assert_seller_profile(data: dict):
    assert_common_fields(data, "SellerProfile")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert data["tax_clearance_status"] in ("PENDING", "CLEARED", "DELINQUENT")


def assert_buyer_profile(data: dict):
    assert_common_fields(data, "BuyerProfile")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["entity_type"] in ("INDIVIDUAL", "LLC", "CORP")
    assert isinstance(data["residency_state"], str) and len(data["residency_state"]) == 2
    assert isinstance(data["felony_disclosure"], bool)
    assert isinstance(data["prior_revocation_count"], int)
    assert data["prior_revocation_count"] >= 0
    assert isinstance(data["citizenship_verified"], bool)
    assert data["qualification_status"] in (
        "NOT_REVIEWED", "QUALIFIED", "PROVISIONALLY_QUALIFIED",
        "UNQUALIFIED", "DISQUALIFIED",
    )
    if data["qualification_score"] is not None:
        assert isinstance(data["qualification_score"], int)
        assert 0 <= data["qualification_score"] <= 100, (
            "qualification_score is clamped into the range 0 through 100 inclusive"
        )
    assert data["qualification_mode"] in (None, "PRE_CHECK", "FINAL_REVIEW")


def assert_brokerage(data: dict):
    assert_common_fields(data, "Brokerage")
    assert isinstance(data["firm_name"], str) and len(data["firm_name"]) > 0
    assert isinstance(data["state_broker_license_no"], str)
    assert isinstance(data["commission_rate_bps"], int)
    assert 100 <= data["commission_rate_bps"] <= 1500
    assert data["dual_agency_policy"] in ("PROHIBITED", "ALLOWED_WITH_DISCLOSURE")


def assert_license(data: dict):
    assert_common_fields(data, "License")
    assert is_valid_uuid(data["county_id"])
    assert is_valid_uuid(data["owner_seller_id"])
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert data["license_class"] in (
        "CLASS_47_ONSALE_GENERAL", "CLASS_21_OFFSALE_GENERAL",
        "CLASS_41_ONSALE_BEER_WINE",
    )
    assert_money(data["annual_gross_receipts_cents"], "License.annual_gross_receipts_cents")
    assert data["annual_gross_receipts_cents"] >= 0
    assert isinstance(data["last_active_date"], str) and len(data["last_active_date"]) == 10
    if data["last_transfer_price_cents"] is not None:
        assert_money(data["last_transfer_price_cents"], "License.last_transfer_price_cents")
    assert isinstance(data["counts_against_quota"], bool)
    assert data["status"] in ("ACTIVE", "IN_ESCROW", "SAFEKEEPING", "TRANSFERRED")
    assert isinstance(data["safekeeping_extensions_count"], int)
    assert isinstance(data["safekeeping_filing_pending"], bool)


def assert_premises(data: dict):
    assert_common_fields(data, "Premises")
    assert is_valid_uuid(data["buyer_id"])
    assert is_valid_uuid(data["county_id"])
    assert isinstance(data["address_line"], str) and len(data["address_line"]) > 0
    assert isinstance(data["zoning_code"], str) and len(data["zoning_code"]) > 0
    assert isinstance(data["distance_to_nearest_school_feet"], int)
    assert data["distance_to_nearest_school_feet"] >= 0
    assert isinstance(data["distance_to_nearest_church_feet"], int)
    assert data["distance_to_nearest_church_feet"] >= 0
    assert isinstance(data["census_tract_undue_concentration"], bool)
    assert data["conditional_use_permit_status"] in (
        "NOT_REQUIRED", "REQUIRED_NOT_FILED", "PENDING", "GRANTED", "DENIED",
    )
    assert data["landlord_consent_status"] in (
        "NOT_REQUIRED", "PENDING", "GRANTED", "REFUSED",
    )
    assert data["suitability_status"] in ("SUITABLE", "CONDITIONAL", "UNSUITABLE")
    assert data["suitability_reason_code"] in (
        "NONE", "SCHOOL_DISTANCE", "CHURCH_DISTANCE", "CUP_DENIED",
        "ZONING_NOT_PERMITTED", "LANDLORD_REFUSED", "CUP_OUTSTANDING",
        "UNDUE_CONCENTRATION", "LANDLORD_PENDING",
    )


def assert_listing(data: dict):
    assert_common_fields(data, "Listing")
    assert is_valid_uuid(data["license_id"])
    assert is_valid_uuid(data["brokerage_id"])
    assert_money(data["ask_price_cents"], "Listing.ask_price_cents")
    assert data["ask_price_cents"] >= 100000
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_CONTRACT", "WITHDRAWN", "SOLD")
    assert isinstance(data["open_offer_count"], int) and data["open_offer_count"] >= 0
    if data["market_price_cents"] is not None:
        assert_money(data["market_price_cents"], "Listing.market_price_cents")
    assert data["valuation_basis"] in (None, "COMPARABLE_SALES", "INCOME_MULTIPLE")


def assert_draft_listing(data: dict):
    """A draft listing carries open_offer_count of 0 and has no valuation."""
    assert_listing(data)
    assert data["status"] == "DRAFT", f"Expected DRAFT, got {data['status']}"
    assert data["open_offer_count"] == 0
    assert data["valuation_basis"] is None
    assert data["market_price_cents"] is None
    assert data["scarcity_bps_at_activation"] is None
    assert data["comp_count_at_activation"] is None
    assert data["activated_at"] is None


def assert_purchase_agreement(data: dict):
    assert_common_fields(data, "PurchaseAgreement")
    for key in ("listing_id", "buyer_id", "premises_id", "brokerage_id",
                "license_id", "seller_id"):
        assert is_valid_uuid(data[key]), f"PurchaseAgreement.{key} must be a UUID"
    assert_money(data["purchase_price_cents"], "PurchaseAgreement.purchase_price_cents")
    assert data["purchase_price_cents"] >= 100000
    assert isinstance(data["deposit_pct_bps"], int)
    assert 500 <= data["deposit_pct_bps"] <= 3500
    assert_money(data["required_deposit_cents"], "PurchaseAgreement.required_deposit_cents")
    assert 500000 <= data["required_deposit_cents"] <= 7500000, (
        "required_deposit_cents is clamped to at least 500000 and at most 7500000 cents"
    )
    assert isinstance(data["contingency_days"], int)
    assert 30 <= data["contingency_days"] <= 365
    assert data["agreement_status"] in ("DRAFT", "EXECUTED", "CLOSED", "TERMINATED")
    assert data["escrow_status"] in (
        "AWAITING_DEPOSIT", "HELD", "RELEASED", "REFUNDED", "FORFEITED",
    )
    assert_money(data["escrow_balance_cents"], "PurchaseAgreement.escrow_balance_cents")
    assert data["commission_mode"] in (None, "SINGLE_AGENCY", "DUAL_AGENCY")


def assert_disclosure(data: dict):
    assert_common_fields(data, "DualAgencyDisclosure")
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["represents_seller"], bool)
    assert isinstance(data["represents_buyer"], bool)
    assert data["status"] in ("PENDING_ACKS", "FULLY_ACKED", "VOID")


def assert_transfer_application(data: dict):
    assert_common_fields(data, "TransferApplication")
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["license_id"])
    assert is_valid_uuid(data["premises_id"])
    assert_money(data["filing_fee_cents"], "TransferApplication.filing_fee_cents")
    assert_money(data["fee_paid_total_cents"], "TransferApplication.fee_paid_total_cents")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "DEFICIENT", "POSTED", "PROTESTED",
        "APPROVED", "DENIED",
    )
    assert isinstance(data["deficiency_round_count"], int)
    assert 0 <= data["deficiency_round_count"] <= 2, (
        "At most two deficiency rounds are permitted"
    )
    assert data["decision"] in (None, "APPROVED", "DENIED")


def assert_protest(data: dict):
    assert_common_fields(data, "Protest")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["protestant_name"], str) and len(data["protestant_name"]) > 0
    assert data["grounds"] in (
        "UNDUE_CONCENTRATION", "DISTANCE_RESTRICTION", "PUBLIC_WELFARE", "ZONING",
    )
    assert data["status"] in ("OPEN", "RESPONDED", "SUSTAINED", "OVERRULED")
    assert_three_fractional_digits(data["filed_at"], "Protest.filed_at")
    assert_three_fractional_digits(data["response_due_at"], "Protest.response_due_at")


def assert_safekeeping_filing(data: dict):
    assert_common_fields(data, "SafekeepingFiling")
    assert is_valid_uuid(data["license_id"])
    assert data["filing_type"] in ("INITIAL", "EXTENSION")
    assert isinstance(data["requested_months"], int)
    assert 1 <= data["requested_months"] <= 24
    assert isinstance(data["granted_months"], int)
    assert isinstance(data["extension_index"], int)
    assert 0 <= data["extension_index"] <= 2
    assert_money(data["fee_cents"], "SafekeepingFiling.fee_cents")
    assert data["status"] in ("PENDING", "GRANTED", "DENIED")
    assert_three_fractional_digits(data["effective_from"], "SafekeepingFiling.effective_from")
    assert_three_fractional_digits(data["expires_at"], "SafekeepingFiling.expires_at")


def assert_ledger_entry(data: dict):
    assert_append_only_fields(data, "EscrowLedgerEntry")
    assert is_valid_uuid(data["agreement_id"])
    assert data["entry_type"] in (
        "DEPOSIT", "RELEASE_COUNTY_FEE", "RELEASE_COMMISSION", "RELEASE_SELLER",
        "REFUND_BUYER", "FORFEIT_SELLER",
    )
    assert_money(data["amount_cents"], "EscrowLedgerEntry.amount_cents")
    assert_money(data["balance_after_cents"], "EscrowLedgerEntry.balance_after_cents")
    assert_three_fractional_digits(data["occurred_at"], "EscrowLedgerEntry.occurred_at")
    if data["entry_type"] == "DEPOSIT":
        assert data["amount_cents"] > 0, "amount_cents is positive only for a deposit"
    else:
        assert data["amount_cents"] < 0, (
            "amount_cents is negative for every disbursement, refund and forfeiture row"
        )


# ─── Domain invariant checkers ────────────────────────────────────────────────

def assert_ledger_balance_projection(rows: list):
    """A running total accumulated across the rows in order sets each row's
    balance_after_cents."""
    running = 0
    for index, row in enumerate(rows):
        running += row["amount_cents"]
        assert row["balance_after_cents"] == running, (
            f"Row {index} ({row['entry_type']}) balance_after_cents should be "
            f"{running}, got {row['balance_after_cents']}"
        )


def assert_ledger_sums_to_balance(rows: list, agreement: dict):
    """The sum of amount_cents over an agreement's ledger rows always equals that
    agreement's escrow_balance_cents."""
    total = sum(row["amount_cents"] for row in rows)
    assert total == agreement["escrow_balance_cents"], (
        f"Ledger rows sum to {total} but escrow_balance_cents is "
        f"{agreement['escrow_balance_cents']}"
    )


def assert_ledger_entry_types(rows: list, expected_types: list):
    actual = [row["entry_type"] for row in rows]
    assert actual == expected_types, (
        f"Expected ledger entry types {expected_types}, got {actual}"
    )


def assert_settlement_buckets_null(agreement: dict):
    """On a refund or a forfeiture the three settlement buckets all stay null."""
    for key in ("county_transfer_fee_cents", "commission_total_cents", "seller_net_cents"):
        assert agreement[key] is None, (
            f"{key} must stay null on a failed transfer, got {agreement[key]}"
        )


def assert_waterfall_conserves_deposit(agreement: dict, held_balance: int):
    """The county fee, the commission total and the seller net exhaust the held
    balance exactly."""
    total = (agreement["county_transfer_fee_cents"]
             + agreement["commission_total_cents"]
             + agreement["seller_net_cents"])
    assert total == held_balance, (
        f"The three buckets sum to {total} but the held balance was {held_balance}"
    )


def assert_error_payload_shape(error_data: dict):
    """An error payload carries exactly error_id and message."""
    assert set(error_data.keys()) == {"error_id", "message"}, (
        f"Error data must carry exactly error_id and message, got {sorted(error_data)}"
    )
