"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import FUNDING_SHARE_BP_MAX, PRICING_VARIANT_PER_LINE
from .types import (
    AddressChangeStatus,
    AgeBand,
    AgreementStatus,
    DisputeOutcome,
    EnrollmentStatus,
    InvoiceStatus,
    ItemStatus,
    PrintOrderStatus,
    SelectionStatus,
    UnenrollReason,
    WaveStatus,
)

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _assert_common_fields(data, entity_name):
    """PRD §2.5: every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_month(value, field):
    assert isinstance(value, str) and _MONTH_RE.match(value), (
        f"{field} must be a YYYY-MM month string, got {value!r}"
    )


def _assert_address(value, field):
    assert isinstance(value, dict), f"{field} must be an object, got {value!r}"
    for key in ("line1", "city", "region", "postal_code", "country"):
        assert isinstance(value.get(key), str) and value[key], (
            f"{field}.{key} must be a non-empty string, got {value.get(key)!r}"
        )


def assert_state_program(data: dict):
    _assert_common_fields(data, "StateProgram")
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["funding_share_bp"], int), "funding_share_bp must be int"
    assert 0 <= data["funding_share_bp"] <= FUNDING_SHARE_BP_MAX, (
        f"funding_share_bp must be within 0..{FUNDING_SHARE_BP_MAX}, got {data['funding_share_bp']}"
    )
    assert isinstance(data["max_state_share_per_book_cents"], int)
    assert data["max_state_share_per_book_cents"] > 0


def assert_affiliate(data: dict):
    _assert_common_fields(data, "Affiliate")
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data["state_program_id"]), "state_program_id must be a UUID"
    prefixes = data["postal_prefixes"]
    assert isinstance(prefixes, list) and len(prefixes) > 0, "postal_prefixes must be non-empty"
    for prefix in prefixes:
        assert isinstance(prefix, str) and 2 <= len(prefix) <= 5, (
            f"each postal prefix must be 2-5 chars, got {prefix!r}"
        )
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["operative"], bool), "operative is a computed boolean (PRD §3.1)"
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0


def assert_affiliate_agreement(data: dict):
    _assert_common_fields(data, "AffiliateAgreement")
    assert is_valid_uuid(data["affiliate_id"]), "affiliate_id must be a UUID"
    assert is_iso8601_timestamp(data["effective_from"]), "effective_from must be ISO 8601"
    assert is_iso8601_timestamp(data["effective_to"]), "effective_to must be ISO 8601"
    assert isinstance(data["local_fundraising_commitment_cents"], int)
    assert data["local_fundraising_commitment_cents"] >= 0, "commitment may be zero, never negative (PRD §3.2)"
    assert data["status"] in [s.value for s in AgreementStatus]
    assert data["decided_by"] is None or isinstance(data["decided_by"], str), (
        "decided_by is null until decided (PRD §3.2)"
    )
    if data["status"] in (AgreementStatus.ACTIVE.value, AgreementStatus.REJECTED.value,
                          AgreementStatus.EXPIRED.value):
        # EXPIRED agreements were ACTIVE first, so a decider was recorded.
        assert isinstance(data["decided_by"], str) and data["decided_by"], (
            "a decided agreement must record the officer X-User-ID"
        )


def assert_population_stat(data: dict):
    _assert_common_fields(data, "PopulationStat")
    assert is_valid_uuid(data["affiliate_id"]), "affiliate_id must be a UUID"
    assert isinstance(data["effective_year"], int)
    assert 2000 <= data["effective_year"] <= 2100, "effective_year within 2000..2100 (PRD §3.1)"
    assert isinstance(data["eligible_population"], int) and data["eligible_population"] > 0


def assert_child(data: dict):
    _assert_common_fields(data, "Child")
    assert is_valid_uuid(data["affiliate_id"]), "affiliate_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["family_name"], str) and data["family_name"]
    assert is_iso8601_timestamp(data["birth_date"]), "birth_date must be ISO 8601"
    _assert_address(data["mailing_address"], "mailing_address")
    assert isinstance(data["postal_prefix"], str) and len(data["postal_prefix"]) == 3, (
        "postal_prefix is the first 3 characters of the uppercased postal code (PRD §3.3)"
    )
    _assert_month(data["registered_month"], "registered_month")
    _assert_month(data["expected_final_mailing_month"], "expected_final_mailing_month")
    assert data["enrollment_status"] in [s.value for s in EnrollmentStatus]
    assert data["unenroll_reason"] is None or data["unenroll_reason"] in [
        r.value for r in UnenrollReason
    ]
    assert isinstance(data["consecutive_returns"], int) and data["consecutive_returns"] >= 0
    assert data["transfer_source_child_id"] is None or is_valid_uuid(
        data["transfer_source_child_id"]
    ), "transfer_source_child_id is null unless created by a transfer (PRD §3.4)"


def assert_address_change(data: dict):
    _assert_common_fields(data, "AddressChange")
    assert is_valid_uuid(data["child_id"]), "child_id must be a UUID"
    _assert_address(data["new_address"], "new_address")
    assert isinstance(data["new_postal_prefix"], str) and len(data["new_postal_prefix"]) == 3
    assert data["status"] in [s.value for s in AddressChangeStatus]
    assert data["decided_by"] is None or isinstance(data["decided_by"], str)
    assert data["resulting_child_id"] is None or is_valid_uuid(data["resulting_child_id"]), (
        "resulting_child_id is set only on APPLIED_TRANSFER (PRD §3.4)"
    )
    if data["status"] == AddressChangeStatus.APPLIED_TRANSFER.value:
        assert is_valid_uuid(data["resulting_child_id"]), (
            "APPLIED_TRANSFER must record the newly created enrollment"
        )


def assert_title(data: dict):
    _assert_common_fields(data, "Title")
    assert isinstance(data["title_name"], str) and data["title_name"]
    assert isinstance(data["author"], str) and data["author"]
    assert data["age_band"] in [b.value for b in AgeBand]
    _assert_month(data["available_from_month"], "available_from_month")
    _assert_month(data["available_until_month"], "available_until_month")
    assert data["available_from_month"] <= data["available_until_month"], (
        "availability end is never before the start (PRD §3.5)"
    )
    assert isinstance(data["stock_on_hand"], int) and data["stock_on_hand"] >= 0, (
        "stock_on_hand never goes negative (PRD §2.9)"
    )


def assert_age_band_selection(data: dict):
    _assert_common_fields(data, "AgeBandSelection")
    _assert_month(data["mailing_month"], "mailing_month")
    assert data["age_band"] in [b.value for b in AgeBand]
    assert is_valid_uuid(data["title_id"]), "title_id must be a UUID"
    assert data["status"] in [s.value for s in SelectionStatus]
    assert isinstance(data["proposed_by"], str) and data["proposed_by"], (
        "proposed_by records the proposer's X-User-ID (PRD §3.5)"
    )
    assert data["approved_by"] is None or isinstance(data["approved_by"], str)
    if data["status"] in (SelectionStatus.APPROVED.value, SelectionStatus.LOCKED.value):
        assert isinstance(data["approved_by"], str) and data["approved_by"], (
            "an approved/locked selection records approved_by"
        )
        assert data["approved_by"] != data["proposed_by"], (
            "segregation of duties: approver differs from proposer (PRD §3.5)"
        )


def assert_print_order(data: dict):
    _assert_common_fields(data, "PrintOrder")
    assert is_valid_uuid(data["selection_id"]), "selection_id must be a UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["is_reprint"], bool)
    _assert_month(data["production_month"], "production_month")
    assert data["status"] in [s.value for s in PrintOrderStatus]
    if data["status"] == PrintOrderStatus.SUBMITTED.value:
        assert data["unit_cents"] is None
        assert data["plate_fee_cents"] is None
        assert data["total_cents"] is None
    else:
        assert isinstance(data["unit_cents"], int) and data["unit_cents"] > 0
        assert isinstance(data["plate_fee_cents"], int) and data["plate_fee_cents"] >= 0
        assert isinstance(data["total_cents"], int) and data["total_cents"] > 0


def assert_mailing_wave(data: dict):
    _assert_common_fields(data, "MailingWave")
    _assert_month(data["mailing_month"], "mailing_month")
    assert data["status"] in [s.value for s in WaveStatus]
    assert isinstance(data["manifested_item_count"], int) and data["manifested_item_count"] >= 0
    assert isinstance(data["returned_item_count"], int) and data["returned_item_count"] >= 0
    assert data["returned_item_count"] <= data["manifested_item_count"], (
        "returns cannot exceed manifested pieces"
    )


def assert_mailing_item(data: dict):
    _assert_common_fields(data, "MailingItem")
    for field in ("wave_id", "child_id", "affiliate_id", "selection_id"):
        assert is_valid_uuid(data[field]), f"{field} must be a UUID"
    _assert_month(data["mailing_month"], "mailing_month")
    assert data["age_band"] in [b.value for b in AgeBand]
    assert data["status"] in [s.value for s in ItemStatus]
    assert isinstance(data["billable"], bool)
    # PRD §3.7: billable while MAILED or DELIVERED, false once RETURNED_UNDELIVERABLE.
    expected_billable = data["status"] in (ItemStatus.MAILED.value, ItemStatus.DELIVERED.value)
    assert data["billable"] == expected_billable, (
        f"billable must be {expected_billable} for status {data['status']}"
    )


def assert_affiliate_invoice(data: dict):
    _assert_common_fields(data, "AffiliateInvoice")
    assert is_valid_uuid(data["affiliate_id"]), "affiliate_id must be a UUID"
    assert is_valid_uuid(data["wave_id"]), "wave_id must be a UUID"
    _assert_month(data["billing_month"], "billing_month")
    assert data["status"] in [s.value for s in InvoiceStatus]
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0
    for field in ("gross_cents", "state_share_cents", "local_share_cents", "credit_memo_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents (PRD §2.6)"
    assert data["gross_cents"] >= 0
    assert data["state_share_cents"] >= 0
    assert data["credit_memo_cents"] >= 0, "a fresh invoice's credit_memo_cents is zero (PRD §3.8)"
    assert isinstance(data["pricing_variant"], str) and data["pricing_variant"]


def assert_penetration_report(data: dict):
    assert is_valid_uuid(data["affiliate_id"]), "affiliate_id must be a UUID"
    _assert_month(data["month"], "month")
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["eligible_population"], int) and data["eligible_population"] >= 0
    assert data["population_stat_year"] is None or isinstance(data["population_stat_year"], int)
    assert data["penetration_snapshot_bp"] is None or (
        isinstance(data["penetration_snapshot_bp"], int) and data["penetration_snapshot_bp"] >= 0
    )
    assert isinstance(data["trailing_12_unique_children"], int)
    assert data["trailing_12_unique_children"] >= 0
    assert data["penetration_trailing_12_bp"] is None or (
        isinstance(data["penetration_trailing_12_bp"], int)
        and data["penetration_trailing_12_bp"] >= 0
    )
    if data["eligible_population"] == 0:
        # PRD §3.8: no stats -> both rates null, never an error or a zero.
        assert data["penetration_snapshot_bp"] is None
        assert data["penetration_trailing_12_bp"] is None


def assert_clock_response(data: dict):
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"
    assert isinstance(data["graduated_child_ids"], list), "sweep reports graduated ids (PRD §2.4)"
    assert isinstance(data["expired_agreement_ids"], list), "sweep reports expired ids (PRD §2.4)"
    for child_id in data["graduated_child_ids"]:
        assert is_valid_uuid(child_id)
    for agreement_id in data["expired_agreement_ids"]:
        assert is_valid_uuid(agreement_id)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_invoice_invariants(invoice: dict):
    """PRD §3.8: gross == state + local + credit_memo, always; issued invoices
    are pinned to the PER_LINE variant."""
    assert (
        invoice["gross_cents"]
        == invoice["state_share_cents"]
        + invoice["local_share_cents"]
        + invoice["credit_memo_cents"]
    ), (
        f"invoice split must conserve gross: {invoice['gross_cents']} != "
        f"{invoice['state_share_cents']} + {invoice['local_share_cents']} + "
        f"{invoice['credit_memo_cents']}"
    )
    assert invoice["local_share_cents"] >= 0, "credits come out of the local share only"
    if invoice["status"] in (
        InvoiceStatus.ISSUED.value,
        InvoiceStatus.DISPUTED.value,
        InvoiceStatus.ADJUSTED.value,
        InvoiceStatus.PAID.value,
    ):
        assert invoice["pricing_variant"] == PRICING_VARIANT_PER_LINE, (
            "PER_LINE is the variant recorded on every issued invoice (PRD §3.8)"
        )


def assert_confirmed_print_order_pricing(order: dict):
    """PRD §3.6: total == quantity * unit + plate fee, locked at confirm."""
    assert order["status"] == PrintOrderStatus.CONFIRMED.value
    assert (
        order["total_cents"] == order["quantity"] * order["unit_cents"] + order["plate_fee_cents"]
    ), (
        f"total {order['total_cents']} != {order['quantity']} x {order['unit_cents']} "
        f"+ {order['plate_fee_cents']}"
    )


def assert_dispute_outcome(value: str):
    assert value in [o.value for o in DisputeOutcome], f"unknown dispute outcome {value!r}"


__all__ = [
    "assert_state_program",
    "assert_affiliate",
    "assert_affiliate_agreement",
    "assert_population_stat",
    "assert_child",
    "assert_address_change",
    "assert_title",
    "assert_age_band_selection",
    "assert_print_order",
    "assert_mailing_wave",
    "assert_mailing_item",
    "assert_affiliate_invoice",
    "assert_penetration_report",
    "assert_clock_response",
    "assert_invoice_invariants",
    "assert_confirmed_print_order_pricing",
    "assert_dispute_outcome",
]
