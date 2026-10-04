"""Declared field domains, defaults, serialization and row construction."""

import copy

import core

COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "schools": [
        "name", "school_code", "country_code", "program_label_authorized",
        "center_code", "seat_capacity", "seal_required", "test_center_status",
        "accrued_fee_cents", "designation_slots_used", "designated_course_count",
    ],
    "course_audits": [
        "school_id", "course_title", "syllabus_hash", "status", "review_round",
        "syllabus_revision_count", "approval_term_end_utc", "decision_notes",
        "designated_course_count",
    ],
    "students": [
        "full_name", "school_id", "student_code", "grade_level",
        "accommodation_eligible", "enrolled",
    ],
    "exam_orders": [
        "school_id", "course_audit_id", "administration_year", "ordering_window",
        "status", "registration_count", "order_fee_cents",
        "provisional_order_fee_cents", "unused_exam_charge_cents", "materials_sealed",
    ],
    "exam_registrations": [
        "exam_order_id", "student_id", "exam_subject", "registration_tier",
        "status", "late_fee_cents", "refundable_cents", "fees_paid_cents",
        "fee_waived", "accommodation_flag",
    ],
    "accommodation_requests": [
        "student_id", "exam_subject", "accommodation_type",
        "documentation_completeness", "extended_time_multiplier", "status",
        "review_round", "weight_sum", "provisioned_minutes",
    ],
    "alternate_exam_requests": [
        "exam_registration_id", "alternate_date_utc", "reason_code", "form_code",
        "status", "seat_block_conflict",
    ],
    "exam_scores": [
        "exam_registration_id", "raw_composite", "reader_id", "ap_score",
        "reader_reliability_index", "status", "release_blocked",
    ],
    "readers": [
        "full_name", "subject_expertise", "calibration_status", "reliability_index",
        "calibration_round_count", "calibration_sample_count",
        "calibration_agreement_rate", "calibration_index", "assigned_score_count",
        "load_status",
    ],
    "material_shipments": [
        "school_id", "exam_order_id", "carrier_tracking_id", "seal_number",
        "seal_verified", "status", "storage_checkpoint_count",
        "custody_event_types", "custody_sequence_count",
    ],
    "score_sends": [
        "exam_score_id", "recipient_type", "recipient_code", "designation_year",
        "fee_cents", "status", "credit_back_cents",
    ],
    "irregularity_cases": [
        "exam_registration_id", "test_center_id", "irregularity_type", "status",
        "finding_code", "investigation_round",
    ],
}

DEFAULTS = {
    "schools": {
        "program_label_authorized": False, "seal_required": True,
        "test_center_status": "ACTIVE", "accrued_fee_cents": 0,
        "designation_slots_used": 0, "designated_course_count": 0,
    },
    "course_audits": {
        "status": "SUBMITTED", "review_round": 0, "syllabus_revision_count": 0,
        "approval_term_end_utc": None, "decision_notes": None,
        "designated_course_count": 0,
    },
    "students": {"accommodation_eligible": False, "enrolled": True},
    "exam_orders": {
        "ordering_window": "NOT_OPEN", "status": "DRAFT", "registration_count": 0,
        "order_fee_cents": 0, "provisional_order_fee_cents": 0,
        "unused_exam_charge_cents": 0, "materials_sealed": False,
    },
    "exam_registrations": {
        "registration_tier": "REGULAR", "status": "REGISTERED", "late_fee_cents": 0,
        "refundable_cents": 0, "fees_paid_cents": 0, "fee_waived": False,
        "accommodation_flag": False,
    },
    "accommodation_requests": {
        "extended_time_multiplier": 1.0, "status": "SUBMITTED", "review_round": 0,
    },
    "alternate_exam_requests": {"status": "FILED", "seat_block_conflict": False},
    "exam_scores": {
        "ap_score": 0, "reader_reliability_index": 0.0, "status": "NOT_SCORED",
        "release_blocked": False,
    },
    "readers": {
        "calibration_status": "RECRUITED", "reliability_index": 0.0,
        "calibration_round_count": 0, "calibration_index": 0.0,
        "assigned_score_count": 0, "load_status": "AVAILABLE",
    },
    "material_shipments": {
        "seal_verified": False, "status": "CREATED", "storage_checkpoint_count": 0,
        "custody_event_types": [], "custody_sequence_count": 0,
    },
    "score_sends": {
        "fee_cents": 0, "status": "PENDING", "credit_back_cents": 0,
    },
    "irregularity_cases": {
        "status": "OPEN", "finding_code": None, "investigation_round": 0,
    },
}


def make(store_key, **values):
    """Build (but do not store) a row carrying the declared defaults.

    The defaults are deep-copied so mutable members (the custody log) are never
    shared between rows.
    """
    row = copy.deepcopy(DEFAULTS[store_key])
    row.update(values)
    for field in FIELDS[store_key]:
        row.setdefault(field, None)
    return row


def serialize(store_key, row):
    out = {}
    for field in COMMON:
        out[field] = row.get(field)
    for field in FIELDS[store_key]:
        out[field] = row.get(field)
    return out


def get_serialized(store_key, rid):
    row = core.get(store_key, rid)
    return serialize(store_key, row) if row is not None else None
