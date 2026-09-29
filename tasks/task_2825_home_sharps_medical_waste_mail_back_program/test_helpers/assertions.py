"""Domain assertions: per-entity field checks and the accounting / custody
invariants the PRD pins."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import ALLOWED_REBATE_PCTS


# --------------------------------------------------------------------------
# System field helpers (PRD 2.4)
# --------------------------------------------------------------------------
def assert_system_fields(entity: Dict[str, Any], expected_version: Optional[int] = None):
    """Assert the common system fields every versioned resource carries."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be an ISO 8601 instant: {entity['created_at']}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at must be an ISO 8601 instant: {entity['updated_at']}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_system_fields(entity: Dict[str, Any]):
    """Append-only records carry only `id` and `created_at`; `updated_at` and
    `version` must be absent entirely (PRD 2.4)."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be an ISO 8601 instant: {entity['created_at']}"
    )
    assert "updated_at" not in entity, (
        "append-only record must not carry updated_at"
    )
    assert "version" not in entity, "append-only record must not carry version"


def assert_calendar_date(value: str, field_name: str = "date"):
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field_name} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


# --------------------------------------------------------------------------
# Program accounting (PRD 2.9)
# --------------------------------------------------------------------------
def assert_program_balances(
    program: Dict[str, Any],
    reserved_cents: Optional[int] = None,
    committed_cents: Optional[int] = None,
    available_cents: Optional[int] = None,
    funding_ceiling_cents: Optional[int] = None,
    status: Optional[str] = None,
):
    """Assert the balance triple and the status that is a pure function of it."""
    for field, expected in (
        ("reserved_cents", reserved_cents),
        ("committed_cents", committed_cents),
        ("available_cents", available_cents),
        ("funding_ceiling_cents", funding_ceiling_cents),
        ("status", status),
    ):
        if expected is not None:
            assert program[field] == expected, (
                f"Expected program {field} {expected!r}, got {program[field]!r}"
            )
    assert isinstance(program["reserved_cents"], int)
    assert isinstance(program["committed_cents"], int)
    assert isinstance(program["available_cents"], int)
    assert (
        program["available_cents"]
        == program["funding_ceiling_cents"]
        - program["reserved_cents"]
        - program["committed_cents"]
    ), "available_cents must equal ceiling less reserved less committed"
    expected_status = "ACTIVE" if program["available_cents"] > 0 else "EXHAUSTED"
    assert program["status"] == expected_status, (
        f"available_cents {program['available_cents']} implies status "
        f"{expected_status}, got {program['status']}"
    )


def assert_ledger_entry(
    entry: Dict[str, Any],
    entry_type: Optional[str] = None,
    amount_cents: Optional[int] = None,
    sequence_no: Optional[int] = None,
    reserved_after_cents: Optional[int] = None,
    committed_after_cents: Optional[int] = None,
    available_after_cents: Optional[int] = None,
    kit_id: Optional[str] = None,
):
    assert_append_only_system_fields(entry)
    for field, expected in (
        ("entry_type", entry_type),
        ("amount_cents", amount_cents),
        ("sequence_no", sequence_no),
        ("reserved_after_cents", reserved_after_cents),
        ("committed_after_cents", committed_after_cents),
        ("available_after_cents", available_after_cents),
    ):
        if expected is not None:
            assert entry[field] == expected, (
                f"Expected ledger {field} {expected!r}, got {entry[field]!r}"
            )
    if kit_id is not None:
        assert entry["kit_id"] == kit_id, (
            f"Expected ledger kit_id {kit_id!r}, got {entry['kit_id']!r}"
        )


def assert_ledger_sequence(entries: List[Dict[str, Any]], expected: List[tuple]):
    """Assert the ledger listing, which is ordered by `sequence_no` ascending,
    matches a list of (sequence_no, entry_type, amount_cents) triples."""
    assert len(entries) == len(expected), (
        f"Expected {len(expected)} ledger entries, got {len(entries)}: "
        f"{[(e.get('sequence_no'), e.get('entry_type'), e.get('amount_cents')) for e in entries]}"
    )
    for entry, (sequence_no, entry_type, amount_cents) in zip(entries, expected):
        assert entry["sequence_no"] == sequence_no, (
            f"Expected sequence_no {sequence_no}, got {entry['sequence_no']}"
        )
        assert entry["entry_type"] == entry_type, (
            f"At sequence_no {sequence_no} expected {entry_type}, got {entry['entry_type']}"
        )
        assert entry["amount_cents"] == amount_cents, (
            f"At sequence_no {sequence_no} expected amount_cents {amount_cents}, "
            f"got {entry['amount_cents']}"
        )


def assert_ledger_sequence_numbers_start_at_one(entries: List[Dict[str, Any]]):
    """`sequence_no` is a per-program monotonic counter starting at 1."""
    assert [e["sequence_no"] for e in entries] == list(range(1, len(entries) + 1)), (
        f"sequence_no must run 1..n in order, got {[e['sequence_no'] for e in entries]}"
    )


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------
def assert_kit(
    kit: Dict[str, Any],
    status: Optional[str] = None,
    container_size: Optional[str] = None,
    required_units: Optional[int] = None,
    capacity_units: Optional[int] = None,
    volume_liters: Optional[float] = None,
    provisional_cost_cents: Optional[int] = None,
    fill_units: Any = "__SKIP__",
    seal_deadline_date: Optional[str] = None,
    void_reason: Any = "__SKIP__",
    supersedes_kit_id: Any = "__SKIP__",
    auto_ship_run_id: Any = "__SKIP__",
):
    for field, expected in (
        ("status", status),
        ("container_size", container_size),
        ("required_units", required_units),
        ("capacity_units", capacity_units),
        ("volume_liters", volume_liters),
        ("provisional_cost_cents", provisional_cost_cents),
        ("seal_deadline_date", seal_deadline_date),
    ):
        if expected is not None:
            assert kit[field] == expected, (
                f"Expected kit {field} {expected!r}, got {kit[field]!r}"
            )
    for field, expected in (
        ("fill_units", fill_units),
        ("void_reason", void_reason),
        ("supersedes_kit_id", supersedes_kit_id),
        ("auto_ship_run_id", auto_ship_run_id),
    ):
        if expected != "__SKIP__":
            assert kit[field] == expected, (
                f"Expected kit {field} {expected!r}, got {kit[field]!r}"
            )


def assert_shipment_axes(
    shipment: Dict[str, Any],
    transport_status: Optional[str] = None,
    conformance_status: Optional[str] = None,
    custody_units: Optional[int] = None,
    screened_by_user_id: Any = "__SKIP__",
):
    """Assert the two independent state dimensions of a shipment (PRD 2.8)."""
    if transport_status is not None:
        assert shipment["transport_status"] == transport_status, (
            f"Expected transport_status {transport_status}, got "
            f"{shipment['transport_status']}"
        )
    if conformance_status is not None:
        assert shipment["conformance_status"] == conformance_status, (
            f"Expected conformance_status {conformance_status}, got "
            f"{shipment['conformance_status']}"
        )
    if custody_units is not None:
        assert shipment["custody_units"] == custody_units, (
            f"Expected custody_units {custody_units}, got {shipment['custody_units']}"
        )
    if screened_by_user_id != "__SKIP__":
        assert shipment["screened_by_user_id"] == screened_by_user_id, (
            f"Expected screened_by_user_id {screened_by_user_id!r}, got "
            f"{shipment['screened_by_user_id']!r}"
        )


def assert_facility_counters(
    facility: Dict[str, Any],
    pending_intake_units: Optional[int] = None,
    destroyed_units_total: Optional[int] = None,
    certificates_issued_count: Optional[int] = None,
    status: Optional[str] = None,
):
    for field, expected in (
        ("pending_intake_units", pending_intake_units),
        ("destroyed_units_total", destroyed_units_total),
        ("certificates_issued_count", certificates_issued_count),
        ("status", status),
    ):
        if expected is not None:
            assert facility[field] == expected, (
                f"Expected facility {field} {expected!r}, got {facility[field]!r}"
            )


def assert_patient_risk(
    patient: Dict[str, Any],
    screening_risk_score: Optional[int] = None,
    audit_risk_score: Optional[int] = None,
    status: Optional[str] = None,
    suspended_at: Any = "__SKIP__",
):
    for field, expected in (
        ("screening_risk_score", screening_risk_score),
        ("audit_risk_score", audit_risk_score),
        ("status", status),
    ):
        if expected is not None:
            assert patient[field] == expected, (
                f"Expected patient {field} {expected!r}, got {patient[field]!r}"
            )
    if suspended_at != "__SKIP__":
        assert patient["suspended_at"] == suspended_at, (
            f"Expected suspended_at {suspended_at!r}, got {patient['suspended_at']!r}"
        )
    for field in ("screening_risk_score", "audit_risk_score"):
        assert isinstance(patient[field], int), f"{field} must be an integer"
        assert 0 <= patient[field] <= 100, f"{field} must fall in 0..100"


def assert_enrollment(
    enrollment: Dict[str, Any],
    status: Optional[str] = None,
    kits_issued: Optional[int] = None,
    next_autoship_due_date: Any = "__SKIP__",
    version: Optional[int] = None,
    activated_at: Any = "__SKIP__",
    sponsor_decision_note: Any = "__SKIP__",
):
    for field, expected in (("status", status), ("kits_issued", kits_issued)):
        if expected is not None:
            assert enrollment[field] == expected, (
                f"Expected enrollment {field} {expected!r}, got {enrollment[field]!r}"
            )
    for field, expected in (
        ("next_autoship_due_date", next_autoship_due_date),
        ("activated_at", activated_at),
        ("sponsor_decision_note", sponsor_decision_note),
    ):
        if expected != "__SKIP__":
            assert enrollment[field] == expected, (
                f"Expected enrollment {field} {expected!r}, got {enrollment[field]!r}"
            )
    if version is not None:
        assert enrollment["version"] == version, (
            f"Expected enrollment version {version}, got {enrollment['version']}"
        )


def assert_certificate(
    certificate: Dict[str, Any],
    certificate_number: Optional[str] = None,
    destroyed_units: Optional[int] = None,
    destruction_date: Optional[str] = None,
    retention_until_date: Optional[str] = None,
    final_kit_cost_cents: Optional[int] = None,
    rebate_pct_applied: Optional[float] = None,
    issued_by_user_id: Optional[str] = None,
    status: Optional[str] = None,
):
    for field, expected in (
        ("certificate_number", certificate_number),
        ("destroyed_units", destroyed_units),
        ("destruction_date", destruction_date),
        ("retention_until_date", retention_until_date),
        ("final_kit_cost_cents", final_kit_cost_cents),
        ("issued_by_user_id", issued_by_user_id),
        ("status", status),
    ):
        if expected is not None:
            assert certificate[field] == expected, (
                f"Expected certificate {field} {expected!r}, got {certificate[field]!r}"
            )
    if rebate_pct_applied is not None:
        assert certificate["rebate_pct_applied"] == rebate_pct_applied, (
            f"Expected rebate_pct_applied {rebate_pct_applied}, got "
            f"{certificate['rebate_pct_applied']}"
        )
    assert certificate["rebate_pct_applied"] in ALLOWED_REBATE_PCTS, (
        f"rebate_pct_applied must be one of {ALLOWED_REBATE_PCTS}, got "
        f"{certificate['rebate_pct_applied']}"
    )
    assert isinstance(certificate["final_kit_cost_cents"], int), (
        "final_kit_cost_cents must be an integer count of cents"
    )


def assert_auto_ship_run(
    run: Dict[str, Any],
    enrollments_evaluated: Optional[int] = None,
    kits_created: Optional[int] = None,
    kits_skipped_not_due: Optional[int] = None,
    kits_skipped_risk: Optional[int] = None,
    kits_skipped_unfilled: Optional[int] = None,
    kits_skipped_funding: Optional[int] = None,
    as_of_date: Optional[str] = None,
    created_kit_ids: Optional[List[str]] = None,
):
    for field, expected in (
        ("enrollments_evaluated", enrollments_evaluated),
        ("kits_created", kits_created),
        ("kits_skipped_not_due", kits_skipped_not_due),
        ("kits_skipped_risk", kits_skipped_risk),
        ("kits_skipped_unfilled", kits_skipped_unfilled),
        ("kits_skipped_funding", kits_skipped_funding),
        ("as_of_date", as_of_date),
    ):
        if expected is not None:
            assert run[field] == expected, (
                f"Expected run {field} {expected!r}, got {run[field]!r}"
            )
    if created_kit_ids is not None:
        assert run["created_kit_ids"] == created_kit_ids, (
            f"Expected created_kit_ids {created_kit_ids}, got {run['created_kit_ids']}"
        )


def assert_return_label(
    label: Dict[str, Any],
    status: Optional[str] = None,
    tracking_number: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    voided_at: Any = "__SKIP__",
    activated_at: Any = "__SKIP__",
    postal_service: Optional[str] = None,
):
    for field, expected in (
        ("status", status),
        ("tracking_number", tracking_number),
        ("valid_from", valid_from),
        ("valid_until", valid_until),
        ("postal_service", postal_service),
    ):
        if expected is not None:
            assert label[field] == expected, (
                f"Expected label {field} {expected!r}, got {label[field]!r}"
            )
    for field, expected in (("voided_at", voided_at), ("activated_at", activated_at)):
        if expected != "__SKIP__":
            assert label[field] == expected, (
                f"Expected label {field} {expected!r}, got {label[field]!r}"
            )


def assert_non_conformance_event(
    event: Dict[str, Any],
    status: Optional[str] = None,
    reason_code: Optional[str] = None,
    notification_deadline_at: Optional[str] = None,
    notified_at: Any = "__SKIP__",
    notification_channel: Any = "__SKIP__",
    remediation_action: Any = "__SKIP__",
):
    for field, expected in (
        ("status", status),
        ("reason_code", reason_code),
        ("notification_deadline_at", notification_deadline_at),
    ):
        if expected is not None:
            assert event[field] == expected, (
                f"Expected event {field} {expected!r}, got {event[field]!r}"
            )
    for field, expected in (
        ("notified_at", notified_at),
        ("notification_channel", notification_channel),
        ("remediation_action", remediation_action),
    ):
        if expected != "__SKIP__":
            assert event[field] == expected, (
                f"Expected event {field} {expected!r}, got {event[field]!r}"
            )


# --------------------------------------------------------------------------
# Listing helpers
# --------------------------------------------------------------------------
def assert_total_count(response, expected_total: int):
    """Assert a list endpoint reports `total_count` before pagination."""
    data, meta = validate_paginated(response)
    assert meta["total_count"] == expected_total, (
        f"Expected total_count {expected_total}, got {meta['total_count']}"
    )
    return data, meta


def assert_empty_listing(response):
    data, meta = validate_paginated(response)
    assert meta["total_count"] == 0, (
        f"Expected an empty listing, got total_count {meta['total_count']}"
    )
    assert data == [], f"Expected no rows, got {data}"
    assert meta["has_more"] is False
    return data, meta
