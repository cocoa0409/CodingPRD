"""Entity assertions and domain invariant checkers.

All field names follow PRD.md exactly. Append-only entities (ContactEvent,
LedgerEntry, VisitRecord) are asserted WITHOUT updated_at / version per PRD
§2.4.
"""
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict, entity_name: str, with_version: bool = True):
    assert isinstance(data, dict), f"{entity_name} must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"{entity_name}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"{entity_name}.version must be a positive int, got {data.get('version')!r}"
        )
    else:
        # Append-only entities must NOT carry updated_at / version at all.
        assert "updated_at" not in data, f"{entity_name} is append-only and must not carry updated_at"
        assert "version" not in data, f"{entity_name} is append-only and must not carry version"


def assert_practice(data: dict):
    _assert_common_fields(data, "Practice")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["billing_mode"] in ("PER_BOOKING", "SUBSCRIPTION")
    assert isinstance(data["subscription_fee_cents"], int)
    assert isinstance(data["new_patient_lead_time_hours"], int)
    assert isinstance(data["existing_patient_lead_time_hours"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "DELISTED")


def assert_provider(data: dict):
    _assert_common_fields(data, "Provider")
    assert is_valid_uuid(data.get("practice_id", "")), "Provider.practice_id must be a UUID"
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["specialty"], str) and data["specialty"]
    assert data["lead_time_override_hours"] is None or isinstance(data["lead_time_override_hours"], int)
    assert isinstance(data["insurance_mismatch_count"], int)
    assert isinstance(data["bookable_in_directory"], bool)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "DELISTED")


def assert_slot(data: dict):
    _assert_common_fields(data, "Slot")
    assert is_valid_uuid(data.get("provider_id", "")), "Slot.provider_id must be a UUID"
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ("OPEN", "BOOKED", "CLOSED")
    assert data["close_reason"] in (None, "PROVIDER_CLOSED", "AUDIT_SWEEP", "PROVIDER_SUSPENDED")
    assert data["current_booking_id"] is None or is_valid_uuid(data["current_booking_id"])


def assert_appointment_type(data: dict):
    _assert_common_fields(data, "AppointmentType")
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["booked_copay_cents"], int)
    assert isinstance(data["accepts_new_patients"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_insurance_plan(data: dict):
    _assert_common_fields(data, "InsurancePlan")
    assert isinstance(data["carrier"], str) and data["carrier"]
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_attestation(data: dict):
    _assert_common_fields(data, "Attestation")
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ("ATTESTED", "VERIFIED", "REJECTED", "REVOKED", "EXPIRED")
    assert data["verified_by"] is None or isinstance(data["verified_by"], str)


def assert_patient(data: dict):
    _assert_common_fields(data, "Patient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["plan_id"] is None or is_valid_uuid(data["plan_id"])
    assert isinstance(data["reliability_score"], int)
    assert 0 <= data["reliability_score"] <= 100
    assert isinstance(data["provisional_score"], int)
    assert 0 <= data["provisional_score"] <= 100
    assert isinstance(data["strikes"], list)
    for s in data["strikes"]:
        assert isinstance(s["epoch"], int)
        assert isinstance(s["magnitude"], int)
        assert s["kind"] in ("NO_SHOW", "LATE_CANCEL")
    assert isinstance(data["recovery_count"], int) and data["recovery_count"] >= 0


def assert_contact_event(data: dict):
    _assert_common_fields(data, "ContactEvent", with_version=False)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("practice_id", ""))
    assert data["provider_id"] is None or is_valid_uuid(data["provider_id"])
    assert is_iso8601_timestamp(data["contacted_at"])
    assert data["channel"] in ("PHONE", "EMAIL", "PORTAL", "WALKIN")


def assert_booking(data: dict):
    _assert_common_fields(data, "Booking")
    assert is_valid_uuid(data.get("slot_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("practice_id", ""))
    assert is_valid_uuid(data.get("appointment_type_id", ""))
    assert data["insurance_plan_id"] is None or is_valid_uuid(data["insurance_plan_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["booked_copay_cents"], int)
    assert isinstance(data["is_new_patient"], bool)
    assert data["attribution_status"] in ("ATTRIBUTED", "ORGANIC")
    assert isinstance(data["late_cancel"], bool)
    assert data["cancel_reason"] in (None, "PATIENT", "PRACTICE", "RELIABILITY_GATE")
    assert data["status"] in ("CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_charge(data: dict):
    _assert_common_fields(data, "Charge")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("practice_id", ""))
    assert data["invoice_id"] is None or is_valid_uuid(data["invoice_id"])
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["marketplace_fee_cents"], int)
    assert isinstance(data["processing_cents"], int)
    assert isinstance(data["net_to_practice_cents"], int)
    assert data["status"] in ("BILLABLE", "INVOICED", "DISPUTED", "SETTLED", "REFUNDED")
    # Invariant: net = gross - fee - processing
    assert (
        data["net_to_practice_cents"]
        == data["gross_cents"] - data["marketplace_fee_cents"] - data["processing_cents"]
    ), "Charge.net_to_practice_cents must equal gross - fee - processing"


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data.get("practice_id", ""))
    assert isinstance(data["period"], str)
    assert isinstance(data["charge_count"], int) and data["charge_count"] >= 0
    assert isinstance(data["fee_total_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["payout_provisional_cents"], int)
    assert isinstance(data["payout_final_cents"], int)
    assert data["status"] in ("ISSUED", "DISPUTED", "PAID", "WRITTEN_OFF")


def assert_ledger_entry(data: dict):
    _assert_common_fields(data, "LedgerEntry", with_version=False)
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert data["charge_id"] is None or is_valid_uuid(data["charge_id"])
    assert data["entry_type"] in (
        "CHARGE_FEE",
        "TIER_DISCOUNT",
        "DISPUTE_CREDIT",
        "SUBSCRIPTION_FEE",
        "PAYMENT",
        "WRITE_OFF",
    )
    assert isinstance(data["amount_cents"], int)
    assert data["note"] is None or isinstance(data["note"], str)


def assert_complaint(data: dict):
    _assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data["complaint_type"] in ("INSURANCE_MISMATCH", "DIRECTORY_INACCURACY", "OTHER")
    assert data["description"] is None or isinstance(data["description"], str)
    assert data["response"] is None or isinstance(data["response"], str)
    assert data["outcome"] in (None, "UPHOLD", "DISMISS")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED_UPHELD", "RESOLVED_DISMISSED")


def assert_review(data: dict):
    _assert_common_fields(data, "Review")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert data["text"] is None or isinstance(data["text"], str)
    assert data["flag_reason"] is None or isinstance(data["flag_reason"], str)
    assert data["status"] in ("PUBLISHED", "FLAGGED", "REMOVED")


def assert_visit_record(data: dict):
    _assert_common_fields(data, "VisitRecord", with_version=False)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_iso8601_timestamp(data["completed_at"])
    assert data["verification"] == "VERIFIED"


def assert_audit_case(data: dict):
    _assert_common_fields(data, "AuditCase")
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data["scope"] in ("AVAILABILITY", "INSURANCE", "FULL")
    assert isinstance(data["sampled_count"], int)
    assert isinstance(data["mismatch_count"], int)
    assert isinstance(data["mismatch_rate"], (int, float))
    assert data["severity"] in ("CLEAN", "WARN", "CRITICAL")
    assert isinstance(data["findings"], list)
    for f in data["findings"]:
        assert isinstance(f["finding_index"], int)
        assert f["finding_type"] in ("TIME_TRAVEL_SLOT", "INSURANCE_STALE")
        assert isinstance(f["ref_id"], str)
        assert isinstance(f["resolved"], bool)
    assert data["status"] in ("OPEN", "FINDINGS_OPEN", "CLOSED_CLEAN", "CLOSED")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_invoice_ledger_conservation(invoice: dict, ledger_entries: list):
    """amount_due_cents must equal the sum of the invoice's ledger entries."""
    total = sum(e["amount_cents"] for e in ledger_entries)
    assert invoice["amount_due_cents"] == total, (
        f"Invoice.amount_due_cents ({invoice['amount_due_cents']}) must equal "
        f"sum of ledger amounts ({total})"
    )


def assert_payout_reconciliation(invoice: dict):
    """payout_final == payout_provisional + discount."""
    expected = invoice["payout_provisional_cents"] + invoice["discount_cents"]
    assert invoice["payout_final_cents"] == expected, (
        f"payout_final_cents ({invoice['payout_final_cents']}) must equal "
        f"payout_provisional_cents + discount_cents ({expected})"
    )
