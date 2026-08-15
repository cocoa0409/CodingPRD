"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. WastageRecord is the append-only exception
to the common resource properties: it must NOT expose updated_at or version.
"""
import re
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# The PRD common-resource-properties section pins created_at/updated_at as
# "an ISO 8601 UTC timestamp with three fractional digits".
THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Two timestamps denote the same instant (PRD timestamp arithmetic is
    exact to the second with no rounding)."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_seconds_between(earlier: str, later: str, seconds: int, label: str = ""):
    delta = (parse_instant(later) - parse_instant(earlier)).total_seconds()
    assert delta == seconds, (
        f"{label}: expected {seconds}s between {earlier} and {later}, got {delta}s"
    )


def assert_three_fractional_digits(value: str, label: str = "timestamp"):
    assert THREE_FRACTIONAL_DIGITS.match(value or ""), (
        f"{label} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["special_requirements"], list)
    assert data["current_abo_type"] in ("O", "A", "B", "AB", "UNKNOWN")
    assert data["current_rh_type"] in ("POS", "NEG", "UNKNOWN")
    assert data["antibody_status"] in ("NEGATIVE", "POSITIVE", "UNKNOWN")
    assert isinstance(data["identified_antibodies"], list)
    assert isinstance(data["abo_confirmed"], bool)
    assert isinstance(data["has_active_type_and_screen"], bool)
    assert isinstance(data["active_mtp"], bool)
    assert isinstance(data["total_units_transfused"], int)


def assert_supplier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_supplier_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["lines"], list) and data["lines"]
    for line in data["lines"]:
        assert line["product_type"] in (
            "RBC", "WHOLE_BLOOD", "PLT_APHERESIS", "PLT_POOL", "FFP", "CRYO")
        assert line["abo_type"] in ("O", "A", "B", "AB")
        assert line["rh_type"] in ("POS", "NEG")
        assert isinstance(line["quantity"], int) and line["quantity"] >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED", "RECEIVING",
                              "CLOSED", "CANCELLED")
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["total_units_received"], int)
    assert isinstance(data["backordered"], bool)


def assert_blood_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["donor_id"], str)
    assert isinstance(data["lot_number"], str)
    assert data["product_type"] in (
        "RBC", "WHOLE_BLOOD", "PLT_APHERESIS", "PLT_POOL", "FFP", "CRYO")
    assert data["abo_type"] in ("O", "A", "B", "AB")
    assert data["rh_type"] in ("POS", "NEG")
    assert isinstance(data["volume_ml"], int) and data["volume_ml"] > 0
    assert is_iso8601_timestamp(data["collected_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["antigen_negative"], list)
    assert isinstance(data["irradiated"], bool)
    assert isinstance(data["cmv_negative"], bool)
    assert isinstance(data["washed"], bool)
    assert data["status"] in (
        "QUARANTINED", "AVAILABLE", "RESERVED", "ISSUED", "TRANSFUSED", "EXPIRED",
        "DISCARDED", "REJECTED", "RETURNED_TO_SUPPLIER", "QUARANTINED_HOLD")


def assert_type_and_screen(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["patient_id"], str)
    assert is_iso8601_timestamp(data["specimen_collected_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("COLLECTED", "RESULTED", "ACTIVE", "EXPIRED",
                              "SUPERSEDED", "REJECTED")


def assert_transfusion_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["ordering_physician_id"], str)
    assert data["product_type"] in (
        "RBC", "WHOLE_BLOOD", "PLT_APHERESIS", "PLT_POOL", "FFP", "CRYO")
    assert isinstance(data["units_requested"], int) and 1 <= data["units_requested"] <= 20
    assert data["urgency"] in ("ROUTINE", "URGENT", "EMERGENCY")
    assert data["type_restriction"] in ("NONE", "O_ONLY", "AB_ONLY")
    assert isinstance(data["requires_crossmatch"], bool)
    assert isinstance(data["units_crossmatched"], int)
    assert isinstance(data["units_issued_net"], int)
    assert isinstance(data["units_transfused"], int)
    assert data["status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "AWAITING_CROSSMATCH", "READY",
        "PARTIALLY_ISSUED", "ON_HOLD", "COMPLETED", "CANCELLED", "REJECTED")


def assert_crossmatch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["patient_id"], str)
    assert data["method"] in ("ELECTRONIC", "SEROLOGIC_AHG")
    assert isinstance(data["auto_selected"], bool)
    assert data["status"] in ("PENDING", "COMPATIBLE", "INCOMPATIBLE", "EXPIRED",
                              "CANCELLED", "CONSUMED")


def assert_issue_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["verified_by_user_id"], str)
    assert isinstance(data["issued_by_user_id"], str)
    assert isinstance(data["is_emergency_release"], bool)
    assert isinstance(data["ack_overdue"], bool)
    assert isinstance(data["lookback_notified"], bool)
    assert data["status"] in ("ISSUED", "TRANSFUSION_STARTED", "TRANSFUSED",
                              "RETURNED", "TRANSFUSION_STOPPED")


def assert_mtp_activation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["activated_by_physician_id"], str)
    assert isinstance(data["activation_reason"], str)
    assert isinstance(data["packs_dispatched"], int)
    assert isinstance(data["units_issued_total"], int)
    assert data["status"] in ("ACTIVATED", "STANDING_DOWN", "DEACTIVATED")


def assert_transfusion_reaction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["issue_record_id"], str)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["unit_id"], str)
    assert data["reaction_type"] in (
        "FEBRILE_NON_HEMOLYTIC", "ALLERGIC_MILD", "ALLERGIC_ANAPHYLAXIS",
        "HEMOLYTIC_ACUTE", "HEMOLYTIC_DELAYED", "TRALI", "TACO", "SEPTIC", "OTHER")
    assert data["severity"] in ("MILD", "MODERATE", "SEVERE", "LIFE_THREATENING")
    assert isinstance(data["reported_by_user_id"], str)
    assert data["status"] in ("REPORTED", "INVESTIGATING", "CONFIRMED",
                              "RULED_OUT", "CLOSED")


def assert_recall_case(data: dict):
    _assert_common_fields(data)
    assert data["scope_type"] in ("DONOR", "LOT", "UNIT")
    assert data["disposition"] in ("DESTRUCTION", "MARKET_WITHDRAWAL")
    assert isinstance(data["auto_created"], bool)
    assert isinstance(data["implicated_unit_ids"], list)
    assert isinstance(data["implicated_unit_count"], int)
    assert isinstance(data["quarantined_count"], int)
    assert isinstance(data["transfused_issue_count"], int)
    assert isinstance(data["notifications_sent_count"], int)
    assert data["status"] in ("OPEN", "UNITS_IDENTIFIED", "QUARANTINE_COMPLETE",
                              "NOTIFICATION_COMPLETE", "CLOSED", "VOIDED")


def assert_wastage_record(data: dict):
    """Append-only log shape: id + created_at present; updated_at and version
    absent by design (PRD common-resource-properties section)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "WastageRecord must not expose updated_at"
    assert "version" not in data, "WastageRecord must not expose version"
    assert isinstance(data["unit_id"], str)
    assert data["product_type"] in (
        "RBC", "WHOLE_BLOOD", "PLT_APHERESIS", "PLT_POOL", "FFP", "CRYO")
    assert data["abo_type"] in ("O", "A", "B", "AB")
    assert data["rh_type"] in ("POS", "NEG")
    assert data["reason"] in (
        "EXPIRED", "RETURNED_OVER_30MIN", "RETURNED_COMPROMISED",
        "PARTIAL_TRANSFUSION", "REACTION_INVESTIGATION", "RECALL_DESTRUCTION",
        "MANUAL")
    assert data["quantity_units"] == 1
    assert isinstance(data["recorded_by_user_id"], str)


def assert_par_level_policy(data: dict):
    _assert_common_fields(data)
    assert data["product_type"] in (
        "RBC", "WHOLE_BLOOD", "PLT_APHERESIS", "PLT_POOL", "FFP", "CRYO")
    assert data["abo_type"] in ("O", "A", "B", "AB")
    assert data["rh_type"] in ("POS", "NEG")
    assert isinstance(data["watch_threshold"], int) and data["watch_threshold"] >= 0
    assert isinstance(data["shortage_threshold"], int) and data["shortage_threshold"] >= 0
    assert isinstance(data["critical_threshold"], int) and data["critical_threshold"] >= 0
    assert (data["watch_threshold"] >= data["shortage_threshold"]
            >= data["critical_threshold"]), "threshold ladder must be non-increasing"
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_posture_read(data: dict):
    """The posture read's eight pinned fields (PRD posture-surveillance text)."""
    for key in ("product_type", "abo_type", "rh_type", "usable_units",
                "inbound_units_24h", "physical_posture", "prospective_posture",
                "excessive_wastage"):
        assert key in data, f"posture read must carry {key}"
    assert isinstance(data["usable_units"], int)
    assert isinstance(data["inbound_units_24h"], int)
    assert data["physical_posture"] in ("NORMAL", "WATCH", "SHORTAGE", "CRITICAL")
    assert data["prospective_posture"] in ("NORMAL", "WATCH", "SHORTAGE", "CRITICAL")
    assert isinstance(data["excessive_wastage"], bool)


def assert_transport_cooler(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cooler_tag"], str) and data["cooler_tag"]
    assert data["status"] in ("AVAILABLE", "CHECKED_OUT", "RESTOCKING")


def assert_cooler_checkout(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cooler_id"], str)
    assert is_iso8601_timestamp(data["planned_start"])
    assert is_iso8601_timestamp(data["planned_end"])
    assert isinstance(data["checked_out_by_user_id"], str)
    assert isinstance(data["overdue"], bool)
    assert data["status"] in ("OPEN", "RETURNED")
