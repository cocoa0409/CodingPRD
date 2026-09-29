"""Entity shape assertions and domain invariant checkers.

Shape assertions confirm every field the PRD declares for a resource is present
with the declared JSON type.  Two resource kinds are immutable and carry only
``id`` and ``created_at``; ``assert_surveillance_reading`` and
``assert_recovery_observation`` therefore also assert that ``updated_at`` and
``version`` are absent from the body entirely.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

_CALENDAR_DATE_LEN = 10


# ─── Primitive helpers ────────────────────────────────────────────────────────

def assert_uuid(value: Any, field: str) -> None:
    assert isinstance(value, str), f"{field} must be a string, got {type(value)}"
    assert is_valid_uuid(value), f"{field} must be a UUID, got {value!r}"


def assert_instant(value: Any, field: str) -> None:
    assert isinstance(value, str), f"{field} must be a string, got {type(value)}"
    assert is_iso8601_timestamp(value), (
        f"{field} must be an ISO 8601 UTC instant ending in Z, got {value!r}"
    )


def assert_calendar_date(value: Any, field: str) -> None:
    assert isinstance(value, str), f"{field} must be a string, got {type(value)}"
    assert len(value) == _CALENDAR_DATE_LEN and value[4] == "-" and value[7] == "-", (
        f"{field} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_instant_equals(actual: Any, expected: str, field: str) -> None:
    """Compare instants at whole-second precision, ignoring a zero fraction."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field} expected {expected!r}, got {actual!r}"
    )


def assert_cents(value: Any, field: str) -> None:
    """Money crosses the wire as an integer count of cents, never a decimal or string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r} ({type(value)})"
    )
    assert value >= 0, f"{field} must not be negative, got {value}"


def assert_one_decimal(value: Any, field: str) -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a number, got {value!r} ({type(value)})"
    )
    assert round(float(value), 1) == float(value), (
        f"{field} carries at most one decimal place, got {value!r}"
    )


def assert_enum_member(value: Any, allowed: List[str], field: str) -> None:
    assert value in allowed, f"{field} must be one of {allowed}, got {value!r}"


def assert_field_absent(body: Dict[str, Any], field: str) -> None:
    assert field not in body, (
        f"{field} must be absent from this response body, found {body.get(field)!r}"
    )


def assert_nullable(body: Dict[str, Any], field: str, checker, *, label: str) -> None:
    assert field in body, f"{label} must expose {field} (null when unset)"
    if body[field] is not None:
        checker(body[field], f"{label}.{field}")


def _assert_mutable_common_fields(body: Dict[str, Any], label: str) -> None:
    assert_uuid(body.get("id"), f"{label}.id")
    assert_instant(body.get("created_at"), f"{label}.created_at")
    assert_instant(body.get("updated_at"), f"{label}.updated_at")
    version = body.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}.version must be an integer, got {version!r}"
    )
    assert version >= 1, f"{label}.version starts at 1, got {version}"


def _assert_immutable_common_fields(body: Dict[str, Any], label: str) -> None:
    assert_uuid(body.get("id"), f"{label}.id")
    assert_instant(body.get("created_at"), f"{label}.created_at")
    assert_field_absent(body, "updated_at")
    assert_field_absent(body, "version")


def _assert_int(body: Dict[str, Any], field: str, label: str, minimum: Optional[int] = 0) -> None:
    value = body.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label}.{field} must be an integer, got {value!r} ({type(value)})"
    )
    if minimum is not None:
        assert value >= minimum, f"{label}.{field} must be >= {minimum}, got {value}"


def _assert_bool(body: Dict[str, Any], field: str, label: str) -> None:
    assert isinstance(body.get(field), bool), (
        f"{label}.{field} must be a boolean, got {body.get(field)!r}"
    )


def _assert_str(body: Dict[str, Any], field: str, label: str) -> None:
    assert isinstance(body.get(field), str) and body[field] != "", (
        f"{label}.{field} must be a non-empty string, got {body.get(field)!r}"
    )


# ─── Entity shape assertions ──────────────────────────────────────────────────

CONTRACT_STATUSES = ["ACTIVE", "PROBATION", "SUSPENDED"]
PARTNERSHIP_TIERS = ["GOLD", "SILVER", "WATCH"]
DIALYSIS_MODALITIES = ["IN_CENTER_HD", "HOME_HD", "PD"]
PAYER_PROGRAMS = ["BUNDLED_ESRD", "FEE_FOR_SERVICE"]
ACCESS_TYPES = ["TUNNELED_CATHETER", "AVF", "AVG"]
LATERALITIES = ["LEFT", "RIGHT"]
ACCESS_SITES = ["FOREARM", "UPPER_ARM", "THIGH", "INTERNAL_JUGULAR", "SUBCLAVIAN"]
ACCESS_STATUSES = ["PLANNED", "PLACED", "MATURING", "IN_USE", "DYSFUNCTIONAL", "ABANDONED"]
READING_KINDS = ["ROUTINE", "URGENT"]
SUSPECTED_PROBLEMS = ["STENOSIS", "THROMBOSIS", "CATHETER_DYSFUNCTION", "MATURATION_FAILURE"]
REFERRAL_STATUSES = ["SUBMITTED", "INFO_REQUESTED", "TRIAGED", "SCHEDULED", "COMPLETED", "DECLINED"]
TRIAGE_VARIANTS = ["TREND_BASED", "ABSOLUTE_BASED"]
URGENCIES = ["SAME_DAY", "NEXT_DAY", "ROUTINE"]
HOLD_REASONS = ["COORDINATOR_REQUEST", "FACILITY_POSTURE_HOLD"]
ROOM_TYPES = ["ANGIO_SUITE", "PROCEDURE_ROOM"]
CLINICIAN_ROLES = ["INTERVENTIONALIST", "SEDATION_RN", "RECOVERY_RN", "CODER"]
PROCEDURE_TYPES = [
    "ANGIOPLASTY",
    "THROMBECTOMY",
    "CATHETER_EXCHANGE",
    "FISTULA_MATURATION_INTERVENTION",
]
SEDATION_LEVELS = ["NONE", "MODERATE"]
CLINICAL_STATUSES = ["SCHEDULED", "IN_ROOM", "RECOVERY", "DISCHARGED", "ABORTED", "CANCELLED"]
CODING_STATUSES = ["UNCODED", "CODED", "ATTESTED", "BILLED", "DENIED", "REBILLED"]
CANCEL_REASONS = ["COORDINATOR_CANCEL", "FACILITY_POSTURE_HOLD"]
DENIAL_REASONS = ["MEDICAL_NECESSITY", "BUNDLING", "DOCUMENTATION", "TIMELY_FILING"]
CODE_FAMILIES = ["ANGIOPLASTY", "THROMBECTOMY", "CATH_EXCHANGE", "IMAGING", "ACCESS_MAINTENANCE_BUNDLE"]
CODE_MODIFIERS = ["NONE", "M59", "M52"]
DEVICE_TYPES = ["SHEATH", "BALLOON", "STENT"]
DEVICE_LOT_STATUSES = ["AVAILABLE", "QUARANTINED", "EXPIRED", "DEPLETED"]
DEVICE_USAGE_STATES = ["RESERVED", "CONSUMED", "RELEASED"]
TARGET_ACCESS_TYPES = ["AVF", "AVG"]
PLAN_STATUSES = ["DRAFT", "ACTIVE", "MATURATION_HOLD", "CONVERTED", "ABANDONED"]
INFECTION_EVENT_TYPES = ["ACCESS_SITE_INFECTION", "BACTEREMIA"]
READINESS_FAILURE_REASONS = ["DEPTH", "DIAMETER", "FLOW", "MATURATION_DAYS", "SURVEILLANCE_COUNT"]


def assert_dialysis_facility(body: Dict[str, Any]) -> None:
    label = "DialysisFacility"
    _assert_mutable_common_fields(body, label)
    _assert_str(body, "name", label)
    _assert_str(body, "facility_code", label)
    assert_enum_member(body.get("contract_status"), CONTRACT_STATUSES, f"{label}.contract_status")
    assert_enum_member(body.get("partnership_tier"), PARTNERSHIP_TIERS, f"{label}.partnership_tier")
    _assert_int(body, "partnership_score", label)
    _assert_int(body, "referral_volume_window", label)
    _assert_int(body, "raw_missed_count_window", label)
    _assert_int(body, "grace_credit_window", label)
    _assert_int(body, "adjusted_missed_count_window", label)
    _assert_int(body, "same_day_honored_window", label)
    assert_nullable(body, "last_scored_at", assert_instant, label=label)


def assert_patient(body: Dict[str, Any]) -> None:
    label = "Patient"
    _assert_mutable_common_fields(body, label)
    _assert_str(body, "mrn", label)
    _assert_str(body, "full_name", label)
    assert_uuid(body.get("dialysis_facility_id"), f"{label}.dialysis_facility_id")
    assert_enum_member(body.get("dialysis_modality"), DIALYSIS_MODALITIES, f"{label}.dialysis_modality")
    assert_enum_member(body.get("payer_program"), PAYER_PROGRAMS, f"{label}.payer_program")
    _assert_int(body, "access_count", label)


def assert_vascular_access(body: Dict[str, Any]) -> None:
    label = "VascularAccess"
    _assert_mutable_common_fields(body, label)
    assert_uuid(body.get("patient_id"), f"{label}.patient_id")
    assert_enum_member(body.get("access_type"), ACCESS_TYPES, f"{label}.access_type")
    assert_enum_member(body.get("laterality"), LATERALITIES, f"{label}.laterality")
    assert_enum_member(body.get("site"), ACCESS_SITES, f"{label}.site")
    assert_calendar_date(body.get("placed_on"), f"{label}.placed_on")
    assert_nullable(body, "predecessor_access_id", assert_uuid, label=label)
    assert_enum_member(body.get("status"), ACCESS_STATUSES, f"{label}.status")
    for counter in (
        "angioplasty_count",
        "thrombectomy_count",
        "catheter_exchange_count",
        "maturation_intervention_count",
        "attributable_infection_count",
        "intervention_burden_score",
    ):
        _assert_int(body, counter, label)
    assert_nullable(body, "abandoned_at", assert_instant, label=label)


def assert_surveillance_reading(body: Dict[str, Any]) -> None:
    label = "SurveillanceReading"
    _assert_immutable_common_fields(body, label)
    assert_uuid(body.get("access_id"), f"{label}.access_id")
    assert_uuid(body.get("reported_by_facility_id"), f"{label}.reported_by_facility_id")
    assert_instant(body.get("reading_at"), f"{label}.reading_at")
    _assert_int(body, "access_flow_ml_min", label)
    _assert_int(body, "venous_pressure_mmhg", label)
    assert_one_decimal(body.get("recirculation_pct"), f"{label}.recirculation_pct")
    assert_enum_member(body.get("kind"), READING_KINDS, f"{label}.kind")


def assert_referral(body: Dict[str, Any]) -> None:
    label = "Referral"
    _assert_mutable_common_fields(body, label)
    assert_uuid(body.get("access_id"), f"{label}.access_id")
    assert_uuid(body.get("referring_facility_id"), f"{label}.referring_facility_id")
    assert_enum_member(body.get("suspected_problem"), SUSPECTED_PROBLEMS, f"{label}.suspected_problem")
    _assert_str(body, "clinical_narrative", label)
    _assert_int(body, "missed_treatment_count", label)
    assert_enum_member(body.get("status"), REFERRAL_STATUSES, f"{label}.status")
    assert "triage_score" in body, f"{label} must expose triage_score (null before triage)"
    if body["triage_score"] is not None:
        _assert_int(body, "triage_score", label)
    assert "triage_variant" in body, f"{label} must expose triage_variant"
    if body["triage_variant"] is not None:
        assert_enum_member(body["triage_variant"], TRIAGE_VARIANTS, f"{label}.triage_variant")
    assert "urgency" in body, f"{label} must expose urgency"
    if body["urgency"] is not None:
        assert_enum_member(body["urgency"], URGENCIES, f"{label}.urgency")
    assert_nullable(body, "triaged_at", assert_instant, label=label)
    assert_nullable(body, "completed_at", assert_instant, label=label)
    _assert_int(body, "info_request_count", label)
    assert "hold_reason" in body, f"{label} must expose hold_reason"
    if body["hold_reason"] is not None:
        assert_enum_member(body["hold_reason"], HOLD_REASONS, f"{label}.hold_reason")
    assert "decline_reason" in body, f"{label} must expose decline_reason"


def assert_procedure_room(body: Dict[str, Any]) -> None:
    label = "ProcedureRoom"
    _assert_mutable_common_fields(body, label)
    _assert_str(body, "room_code", label)
    assert_enum_member(body.get("room_type"), ROOM_TYPES, f"{label}.room_type")
    _assert_int(body, "turnover_buffer_min", label)
    _assert_int(body, "daily_case_cap", label, minimum=1)
    _assert_int(body, "recovery_bay_count", label, minimum=1)


def assert_clinician(body: Dict[str, Any]) -> None:
    label = "Clinician"
    _assert_mutable_common_fields(body, label)
    _assert_str(body, "full_name", label)
    assert_enum_member(body.get("clinician_role"), CLINICIAN_ROLES, f"{label}.clinician_role")
    _assert_str(body, "npi", label)
    assert len(body["npi"]) == 10 and body["npi"].isdigit(), (
        f"{label}.npi must be exactly 10 digits, got {body['npi']!r}"
    )
    _assert_bool(body, "moderate_sedation_credentialed", label)
    # The PRD names a server-side default only for `moderate_sedation_credentialed`
    # ("defaults to `false` when omitted") and `max_concurrent_sedation_cases` ("defaults
    # to 2 when omitted").  It states no default for `credential_expires_on`, so a
    # clinician registered without one legitimately carries null.
    assert_nullable(body, "credential_expires_on", assert_calendar_date, label=label)
    _assert_int(body, "max_concurrent_sedation_cases", label)


def assert_procedure(body: Dict[str, Any]) -> None:
    label = "Procedure"
    _assert_mutable_common_fields(body, label)
    assert_uuid(body.get("referral_id"), f"{label}.referral_id")
    assert_uuid(body.get("access_id"), f"{label}.access_id")
    assert_uuid(body.get("room_id"), f"{label}.room_id")
    assert_uuid(body.get("primary_operator_id"), f"{label}.primary_operator_id")
    assert_nullable(body, "sedation_rn_id", assert_uuid, label=label)
    assert_nullable(body, "attested_by_id", assert_uuid, label=label)
    assert_nullable(body, "supporting_reading_id", assert_uuid, label=label)
    assert_enum_member(body.get("procedure_type"), PROCEDURE_TYPES, f"{label}.procedure_type")
    assert_enum_member(body.get("sedation_level"), SEDATION_LEVELS, f"{label}.sedation_level")
    assert_instant(body.get("scheduled_start"), f"{label}.scheduled_start")
    assert_instant(body.get("scheduled_end"), f"{label}.scheduled_end")
    assert body["scheduled_end"] > body["scheduled_start"], (
        f"{label}.scheduled_end must be strictly after scheduled_start"
    )
    assert_enum_member(body.get("clinical_status"), CLINICAL_STATUSES, f"{label}.clinical_status")
    assert_enum_member(body.get("coding_status"), CODING_STATUSES, f"{label}.coding_status")
    assert_nullable(body, "sedation_end_at", assert_instant, label=label)
    assert_nullable(body, "discharged_at", assert_instant, label=label)
    assert "reimbursement_variant" in body, f"{label} must expose reimbursement_variant"
    if body["reimbursement_variant"] is not None:
        assert_enum_member(
            body["reimbursement_variant"], PAYER_PROGRAMS, f"{label}.reimbursement_variant"
        )
    for money in (
        "allowed_amount_cents",
        "billed_amount_cents",
        "denied_amount_cents",
        "net_receivable_cents",
    ):
        assert_cents(body.get(money), f"{label}.{money}")
    _assert_int(body, "rebill_count", label)
    for nullable_text in (
        "medical_necessity_statement",
        "abort_reason",
        "denial_code",
    ):
        assert nullable_text in body, f"{label} must expose {nullable_text}"
    assert "cancel_reason" in body, f"{label} must expose cancel_reason"
    if body["cancel_reason"] is not None:
        assert_enum_member(body["cancel_reason"], CANCEL_REASONS, f"{label}.cancel_reason")
    assert "denial_reason" in body, f"{label} must expose denial_reason"
    if body["denial_reason"] is not None:
        assert_enum_member(body["denial_reason"], DENIAL_REASONS, f"{label}.denial_reason")


def assert_procedure_code(body: Dict[str, Any]) -> None:
    label = "ProcedureCode"
    _assert_mutable_common_fields(body, label)
    assert_uuid(body.get("procedure_id"), f"{label}.procedure_id")
    _assert_str(body, "hcpcs_code", label)
    assert_enum_member(body.get("code_family"), CODE_FAMILIES, f"{label}.code_family")
    assert_cents(body.get("base_allowed_cents"), f"{label}.base_allowed_cents")
    assert_enum_member(body.get("modifier"), CODE_MODIFIERS, f"{label}.modifier")
    _assert_int(body, "rank", label, minimum=1)
    _assert_bool(body, "is_bundled", label)
    _assert_int(body, "reduction_factor_pct", label)
    assert_cents(body.get("allowed_cents"), f"{label}.allowed_cents")


def assert_recovery_observation(body: Dict[str, Any]) -> None:
    label = "RecoveryObservation"
    _assert_immutable_common_fields(body, label)
    assert_uuid(body.get("procedure_id"), f"{label}.procedure_id")
    assert_instant(body.get("observed_at"), f"{label}.observed_at")
    _assert_int(body, "aldrete_score", label)
    assert 0 <= body["aldrete_score"] <= 10, (
        f"{label}.aldrete_score must be between 0 and 10, got {body['aldrete_score']}"
    )
    _assert_bool(body, "on_room_air", label)


def assert_device_lot(body: Dict[str, Any]) -> None:
    label = "DeviceLot"
    _assert_mutable_common_fields(body, label)
    assert_enum_member(body.get("device_type"), DEVICE_TYPES, f"{label}.device_type")
    _assert_str(body, "catalog_code", label)
    _assert_str(body, "lot_number", label)
    assert_calendar_date(body.get("expires_on"), f"{label}.expires_on")
    _assert_int(body, "received_quantity", label, minimum=1)
    _assert_int(body, "quantity_on_hand", label)
    _assert_int(body, "quantity_reserved", label)
    assert_cents(body.get("unit_cost_cents"), f"{label}.unit_cost_cents")
    assert_enum_member(body.get("status"), DEVICE_LOT_STATUSES, f"{label}.status")
    assert "quarantine_reason" in body, f"{label} must expose quarantine_reason"


def assert_device_usage(body: Dict[str, Any]) -> None:
    label = "DeviceUsage"
    _assert_mutable_common_fields(body, label)
    assert_uuid(body.get("procedure_id"), f"{label}.procedure_id")
    assert_uuid(body.get("device_lot_id"), f"{label}.device_lot_id")
    _assert_int(body, "quantity", label, minimum=1)
    assert_enum_member(body.get("state"), DEVICE_USAGE_STATES, f"{label}.state")
    _assert_int(body, "wasted_quantity", label)
    assert_nullable(body, "consumed_at", assert_instant, label=label)
    assert_nullable(body, "released_at", assert_instant, label=label)


def assert_access_conversion_plan(body: Dict[str, Any]) -> None:
    label = "AccessConversionPlan"
    _assert_mutable_common_fields(body, label)
    assert_uuid(body.get("patient_id"), f"{label}.patient_id")
    assert_uuid(body.get("from_access_id"), f"{label}.from_access_id")
    assert_nullable(body, "target_access_id", assert_uuid, label=label)
    assert_enum_member(body.get("target_access_type"), TARGET_ACCESS_TYPES, f"{label}.target_access_type")
    assert_calendar_date(body.get("target_conversion_date"), f"{label}.target_conversion_date")
    assert_enum_member(body.get("status"), PLAN_STATUSES, f"{label}.status")
    _assert_int(body, "maturation_check_count", label)
    assert_nullable(body, "last_check_at", assert_instant, label=label)
    assert_nullable(body, "last_diameter_mm", assert_one_decimal, label=label)
    assert "last_flow_ml_min" in body, f"{label} must expose last_flow_ml_min"
    assert "last_depth_mm" in body, f"{label} must expose last_depth_mm"
    if body["last_depth_mm"] is not None:
        assert_one_decimal(body["last_depth_mm"], f"{label}.last_depth_mm")
    assert "days_since_placement" in body, f"{label} must expose days_since_placement"
    _assert_bool(body, "readiness_met", label)
    reasons = body.get("readiness_failure_reasons")
    assert isinstance(reasons, list), (
        f"{label}.readiness_failure_reasons must be an array, got {reasons!r}"
    )
    for reason in reasons:
        assert_enum_member(reason, READINESS_FAILURE_REASONS, f"{label}.readiness_failure_reasons[]")
    assert_nullable(body, "converted_at", assert_instant, label=label)


def assert_infection_event(body: Dict[str, Any]) -> None:
    label = "InfectionEvent"
    _assert_mutable_common_fields(body, label)
    assert_uuid(body.get("procedure_id"), f"{label}.procedure_id")
    assert_uuid(body.get("access_id"), f"{label}.access_id")
    assert_enum_member(body.get("event_type"), INFECTION_EVENT_TYPES, f"{label}.event_type")
    _assert_str(body, "organism", label)
    assert_instant(body.get("onset_at"), f"{label}.onset_at")
    _assert_int(body, "days_post_procedure", label, minimum=None)
    _assert_bool(body, "attributable", label)


# ─── Derived read models ──────────────────────────────────────────────────────

def assert_partnership_metrics(body: Dict[str, Any]) -> None:
    """The metrics view echoes the facility id, the nine persisted values, two
    integer-scaled rates and the two window endpoints."""
    label = "PartnershipMetrics"
    assert_uuid(body.get("facility_id"), f"{label}.facility_id")
    assert_enum_member(body.get("contract_status"), CONTRACT_STATUSES, f"{label}.contract_status")
    assert_enum_member(body.get("partnership_tier"), PARTNERSHIP_TIERS, f"{label}.partnership_tier")
    for counter in (
        "partnership_score",
        "referral_volume_window",
        "raw_missed_count_window",
        "grace_credit_window",
        "adjusted_missed_count_window",
        "same_day_honored_window",
        "missed_treatments_per_referral_x100",
        "same_day_honor_rate_pct",
    ):
        _assert_int(body, counter, label)
    assert "last_scored_at" in body, f"{label} must expose last_scored_at"
    assert_instant(body.get("window_start"), f"{label}.window_start")
    assert_instant(body.get("window_end"), f"{label}.window_end")


def assert_reimbursement_preview(body: Dict[str, Any]) -> None:
    """The preview reports both variant totals, their delta and the per-line items."""
    label = "ReimbursementPreview"
    assert_uuid(body.get("procedure_id"), f"{label}.procedure_id")
    assert_enum_member(body.get("applicable_variant"), PAYER_PROGRAMS, f"{label}.applicable_variant")
    assert_cents(body.get("bundled_esrd_total_cents"), f"{label}.bundled_esrd_total_cents")
    assert_cents(body.get("fee_for_service_total_cents"), f"{label}.fee_for_service_total_cents")
    delta = body.get("variant_delta_cents")
    assert isinstance(delta, int) and not isinstance(delta, bool), (
        f"{label}.variant_delta_cents must be an integer, got {delta!r}"
    )
    assert delta == body["fee_for_service_total_cents"] - body["bundled_esrd_total_cents"], (
        "variant_delta_cents must be the fee-for-service total minus the bundled total"
    )
    assert isinstance(body.get("line_items"), list), (
        f"{label}.line_items must be an array, got {body.get('line_items')!r}"
    )


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_version_bumped(before: Dict[str, Any], after: Dict[str, Any], by: int = 1) -> None:
    """A mutated row -- including one touched only as a cascade victim -- advances
    its version by one and refreshes updated_at."""
    assert after["version"] == before["version"] + by, (
        f"version expected {before['version'] + by}, got {after['version']}"
    )
    assert after["updated_at"] >= before["updated_at"], (
        "updated_at must be refreshed, never moved backwards"
    )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A rejected request must leave the subject row's version untouched."""
    assert after["version"] == before["version"], (
        f"version must be unchanged, was {before['version']} now {after['version']}"
    )


def assert_lot_headroom(lot: Dict[str, Any], expected_headroom: int) -> None:
    """Headroom is quantity_on_hand minus quantity_reserved."""
    headroom = lot["quantity_on_hand"] - lot["quantity_reserved"]
    assert headroom == expected_headroom, (
        f"headroom expected {expected_headroom}, got {headroom} "
        f"(on_hand={lot['quantity_on_hand']}, reserved={lot['quantity_reserved']})"
    )


def assert_device_unit_conservation(lot: Dict[str, Any], usages: List[Dict[str, Any]]) -> None:
    """quantity_on_hand plus every consumed reservation equals received_quantity, and
    quantity_reserved equals the sum of the reservations still outstanding."""
    consumed = sum(u["quantity"] for u in usages if u["state"] == "CONSUMED")
    outstanding = sum(u["quantity"] for u in usages if u["state"] == "RESERVED")
    assert lot["quantity_on_hand"] + consumed == lot["received_quantity"], (
        f"conservation broken: on_hand {lot['quantity_on_hand']} + consumed {consumed} "
        f"!= received_quantity {lot['received_quantity']}"
    )
    assert lot["quantity_reserved"] == outstanding, (
        f"quantity_reserved {lot['quantity_reserved']} != outstanding reservations {outstanding}"
    )


def assert_money_ledger(procedure: Dict[str, Any]) -> None:
    """The four money fields are integers and the receivable is what remains after denial."""
    for money in (
        "allowed_amount_cents",
        "billed_amount_cents",
        "denied_amount_cents",
        "net_receivable_cents",
    ):
        assert_cents(procedure.get(money), f"Procedure.{money}")
    assert (
        procedure["net_receivable_cents"]
        == procedure["billed_amount_cents"] - procedure["denied_amount_cents"]
    ), (
        "net_receivable_cents must be billed_amount_cents minus denied_amount_cents "
        f"({procedure['billed_amount_cents']} - {procedure['denied_amount_cents']} "
        f"!= {procedure['net_receivable_cents']})"
    )


def assert_burden_score(access: Dict[str, Any]) -> None:
    """The burden score is the weighted sum of the five counters (2/3/1/1/5)."""
    expected = (
        2 * access["angioplasty_count"]
        + 3 * access["thrombectomy_count"]
        + 1 * access["catheter_exchange_count"]
        + 1 * access["maturation_intervention_count"]
        + 5 * access["attributable_infection_count"]
    )
    assert access["intervention_burden_score"] == expected, (
        f"intervention_burden_score expected {expected}, got {access['intervention_burden_score']}"
    )


def assert_ascii_sorted(values: List[str], field: str) -> None:
    """Reason lists are reported in ascending ASCII order."""
    assert values == sorted(values), f"{field} must be ASCII-sorted, got {values}"
