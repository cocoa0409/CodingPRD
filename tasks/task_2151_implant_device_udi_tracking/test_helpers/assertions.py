"""Entity assertions and domain invariant checkers.

Every one of the fourteen persisted resource types carries `id`, `created_at`,
`updated_at` and `version`; `assert_common_fields` covers that shared shape and
each `assert_<entity>` adds the resource's own fields.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    BillingState,
    BillingTrigger,
    CaptureVariant,
    CaseStatus,
    CatalogCategory,
    ChargeStatus,
    CustodyState,
    ExplantStatus,
    FieldActionStatus,
    ImplantRecordStatus,
    InvoiceStatus,
    Laterality,
    LotStatus,
    NotificationStatus,
    Ownership,
    ReadinessStatus,
    ReconciliationMethod,
    RegistryConsent,
    RegistrySubmissionStatus,
    VendorStanding,
)


def _members(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, label: str = "resource") -> None:
    """`id` is a bare UUID with no type prefix; timestamps are ISO 8601 UTC;
    `version` is an integer that begins at 1."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a bare UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{label}.version must begin at 1, got {data['version']}"


def assert_vendor(data: dict) -> None:
    assert_common_fields(data, "Vendor")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["vendor_code"], str) and data["vendor_code"]
    assert data["standing"] in _members(VendorStanding)
    assert isinstance(data["open_consignment_liability_cents"], int)
    assert isinstance(data["recall_open_count"], int)


def assert_consignment_agreement(data: dict) -> None:
    assert_common_fields(data, "ConsignmentAgreement")
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["agreement_code"], str) and data["agreement_code"]
    assert data["status"] in _members(AgreementStatus)
    assert data["billing_trigger"] in _members(BillingTrigger)
    assert data["reconciliation_method"] in _members(ReconciliationMethod)
    assert isinstance(data["invoice_tolerance_bps"], int)
    assert 0 <= data["invoice_tolerance_bps"] <= 10000
    assert isinstance(data["price_list_version"], int) and data["price_list_version"] >= 1
    assert isinstance(data["period_start_utc"], str)
    assert isinstance(data["period_end_utc"], str)
    assert isinstance(data["replenishment_days"], int)


def assert_catalog_item(data: dict) -> None:
    assert_common_fields(data, "CatalogItem")
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["device_identifier"], str) and data["device_identifier"]
    assert isinstance(data["description"], str)
    assert data["category"] in _members(CatalogCategory)
    assert isinstance(data["list_charge_cents"], int) and data["list_charge_cents"] > 0
    assert isinstance(data["charge_code"], str)
    assert isinstance(data["registry_required"], bool)
    assert isinstance(data["shelf_life_days"], int)
    assert isinstance(data["on_hand_available_qty"], int)


def assert_lot(data: dict) -> None:
    assert_common_fields(data, "Lot")
    assert is_valid_uuid(data["catalog_item_id"])
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["expiration_date"], str) and len(data["expiration_date"]) == 10
    assert data["status"] in _members(LotStatus)
    assert is_iso8601_timestamp(data["received_at_utc"])
    assert isinstance(data["received_by_user_id"], str) and data["received_by_user_id"]
    assert isinstance(data["received_qty"], int)
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["consumed_qty"], int)
    assert_lot_conservation(data)


def assert_lot_conservation(lot: dict) -> None:
    """`on_hand_qty` plus `consumed_qty` always equals `received_qty`."""
    assert lot["on_hand_qty"] + lot["consumed_qty"] == lot["received_qty"], (
        "Lot conservation broken: on_hand_qty "
        f"{lot['on_hand_qty']} + consumed_qty {lot['consumed_qty']} != "
        f"received_qty {lot['received_qty']}"
    )
    assert lot["on_hand_qty"] >= 0 and lot["consumed_qty"] >= 0


def assert_device_unit(data: dict) -> None:
    assert_common_fields(data, "DeviceUnit")
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["udi_serial"], str) and data["udi_serial"]
    assert isinstance(data["udi_di_snapshot"], str) and data["udi_di_snapshot"]
    assert data["custody_state"] in _members(CustodyState)
    assert data["billing_state"] in _members(BillingState)
    assert data["ownership"] in _members(Ownership)
    assert isinstance(data["acquisition_cost_cents"], int)
    assert data["acquisition_cost_cents"] > 0
    assert_unit_reservation_coherent(data)


def assert_unit_reservation_coherent(unit: dict) -> None:
    """`reserved_case_id` is non-null exactly while `custody_state` is RESERVED."""
    if unit["custody_state"] == CustodyState.RESERVED.value:
        assert unit.get("reserved_case_id"), (
            "A RESERVED unit must carry a reserved_case_id"
        )
    else:
        assert unit.get("reserved_case_id") is None, (
            f"A {unit['custody_state']} unit must have reserved_case_id null, "
            f"got {unit.get('reserved_case_id')!r}"
        )


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["display_name"], str)
    assert data["registry_consent"] in _members(RegistryConsent)
    assert isinstance(data["implant_count"], int) and data["implant_count"] >= 0


def assert_surgical_case(data: dict) -> None:
    assert_common_fields(data, "SurgicalCase")
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert isinstance(data["or_room_code"], str) and data["or_room_code"]
    assert isinstance(data["scheduled_start_utc"], str)
    assert isinstance(data["scheduled_end_utc"], str)
    assert data["scheduled_end_utc"] > data["scheduled_start_utc"]
    assert isinstance(data["surgeon_code"], str)
    assert data["status"] in _members(CaseStatus)
    assert data["readiness_status"] in _members(ReadinessStatus)
    assert isinstance(data["blocked_reservation_count"], int)
    assert data["blocked_reservation_count"] >= 0
    assert isinstance(data["total_posted_charge_cents"], int)
    assert isinstance(data["implant_record_count"], int)


def assert_implant_record(data: dict) -> None:
    assert_common_fields(data, "ImplantRecord")
    assert is_valid_uuid(data["surgical_case_id"])
    assert is_valid_uuid(data["device_unit_id"])
    assert is_valid_uuid(data["patient_id"])
    assert data["status"] in _members(ImplantRecordStatus)
    assert isinstance(data["udi_di"], str) and data["udi_di"]
    assert isinstance(data["udi_pi_serial"], str) and data["udi_pi_serial"]
    assert isinstance(data["anatomic_site"], str)
    assert data["laterality"] in _members(Laterality)
    assert isinstance(data["documented_by_user_id"], str) and data["documented_by_user_id"]
    assert is_iso8601_timestamp(data["documented_at_utc"])
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0


def assert_charge_capture(data: dict) -> None:
    assert_common_fields(data, "ChargeCapture")
    assert is_valid_uuid(data["implant_record_id"])
    assert isinstance(data["charge_code"], str) and data["charge_code"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in _members(ChargeStatus)
    assert isinstance(data["provisional_charge_cents"], int)
    assert data["capture_variant"] in _members(CaptureVariant)
    assert_effective_charge_coherent(data)


def assert_effective_charge_coherent(charge: dict) -> None:
    """`effective_charge_cents` is `final_charge_cents` whenever that is
    non-null, and `provisional_charge_cents` otherwise."""
    expected = (
        charge["final_charge_cents"]
        if charge.get("final_charge_cents") is not None
        else charge["provisional_charge_cents"]
    )
    assert charge["effective_charge_cents"] == expected, (
        f"effective_charge_cents {charge['effective_charge_cents']} should be "
        f"{expected}"
    )


def assert_registry_submission(data: dict) -> None:
    assert_common_fields(data, "RegistrySubmission")
    assert is_valid_uuid(data["implant_record_id"])
    assert data["status"] in _members(RegistrySubmissionStatus)
    assert isinstance(data["completeness_score"], int)
    assert 0 <= data["completeness_score"] <= 100
    assert isinstance(data["resubmission_count"], int)
    assert is_iso8601_timestamp(data["deadline_utc"])


def assert_field_action(data: dict) -> None:
    assert_common_fields(data, "FieldAction")
    assert is_valid_uuid(data["vendor_id"])
    assert is_valid_uuid(data["catalog_item_id"])
    assert isinstance(data["action_code"], str) and data["action_code"]
    assert data["action_class"] in ("CLASS_I", "CLASS_II", "CLASS_III")
    assert data["scope_type"] in ("CATALOG", "LOT", "SERIAL_RANGE")
    assert data["status"] in _members(FieldActionStatus)
    assert isinstance(data["effective_from_utc"], str)
    assert isinstance(data["implanted_cohort_size"], int)
    assert isinstance(data["on_hand_cohort_size"], int)
    assert isinstance(data["notification_open_count"], int)


def assert_recall_notification(data: dict) -> None:
    assert_common_fields(data, "RecallNotification")
    assert is_valid_uuid(data["field_action_id"])
    assert is_valid_uuid(data["implant_record_id"])
    assert is_valid_uuid(data["patient_id"])
    assert data["status"] in _members(NotificationStatus)
    assert is_iso8601_timestamp(data["due_utc"])
    assert isinstance(data["escalation_level"], int) and data["escalation_level"] >= 0


def assert_vendor_invoice(data: dict) -> None:
    assert_common_fields(data, "VendorInvoice")
    assert is_valid_uuid(data["vendor_id"])
    assert is_valid_uuid(data["consignment_agreement_id"])
    assert isinstance(data["invoice_number"], str) and data["invoice_number"]
    assert isinstance(data["submitted_total_cents"], int)
    assert data["submitted_total_cents"] > 0
    assert isinstance(data["device_unit_ids"], list) and data["device_unit_ids"]
    assert data["status"] in _members(InvoiceStatus)


def assert_explant_record(data: dict) -> None:
    assert_common_fields(data, "ExplantRecord")
    assert is_valid_uuid(data["implant_record_id"])
    assert data["status"] in _members(ExplantStatus)
    assert data["reason"] in (
        "DEVICE_FAILURE",
        "INFECTION",
        "RECALL",
        "UPGRADE",
        "OTHER",
    )
    assert is_iso8601_timestamp(data["explanted_at_utc"])
    assert isinstance(data["credit_expected_cents"], int)
    assert data["credit_expected_cents"] >= 0


# ─── Envelope / listing helpers ───────────────────────────────────────────

def assert_object_envelope(body: dict) -> None:
    """The `meta` block of a single-resource read carries no pagination fields."""
    assert body["response_type"] == "object"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


def assert_created_at_ascending(rows: list) -> None:
    """List results are always ordered by `created_at` ascending."""
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), f"Rows are not ordered by created_at ascending: {stamps}"


def assert_readiness_payload(payload: dict) -> None:
    for key in (
        "readiness_status",
        "blocked_reservation_count",
        "unverified_record_count",
        "outstanding_registry_count",
        "unfinalized_charge_count",
        "total_posted_charge_cents",
    ):
        assert key in payload, f"Readiness read must carry {key}"
    assert payload["readiness_status"] in _members(ReadinessStatus)


def assert_ops_run_payload(payload: dict) -> None:
    for key in (
        "ops_run_index",
        "expired_agreement_count",
        "expired_lot_count",
        "expired_unit_count",
        "detached_reservation_count",
        "rotation_alert_count",
        "escalated_notification_count",
        "overdue_submission_count",
    ):
        assert key in payload, f"Operational checkpoint response must carry {key}"
        assert isinstance(payload[key], int)


def normalize_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant so `...T00:00:00Z` and
    `...T00:00:00.000Z` compare equal."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"Expected an ISO 8601 UTC instant ending in Z, got {value!r}"
    )
    body = value[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
