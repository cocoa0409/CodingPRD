"""Entity serialization plus the version/updated_at bookkeeping pass."""
import copy
import json

import derive
import store
from store import DB

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "Building": ("name", "code", "campus_zone", "break_housing_enabled", "posture",
                 "closure_reason", "last_posture_change_at"),
    "Floor": ("building_id", "floor_number", "required_programs_per_term",
              "programming_frozen"),
    "Room": ("floor_id", "room_number", "bed_capacity", "last_renovation_year",
             "status", "pre_closure_status"),
    "Student": ("full_name", "email", "class_year", "financial_hardship_flag",
                "current_room_id", "housing_status", "break_housing_eligible"),
    "RAApplication": ("applicant_student_id", "term_code", "essay_ref", "status",
                      "interview_score", "revision_count", "revision_notes",
                      "reviewed_by_user_id", "submitted_at", "created_ra_id"),
    "RA": ("student_id", "application_id", "assigned_floor_id", "employment_status",
           "certification_status", "completed_module_codes", "certified_at",
           "separation_reason"),
    "DutyShift": ("floor_id", "shift_type", "start_at", "end_at", "assigned_ra_id",
                  "swap_requested_ra_id", "status", "points_value", "checked_in_at",
                  "completed_at", "filled_by_selector"),
    "IncidentReport": ("filed_by_ra_id", "room_id", "subject_student_id", "occurred_at",
                       "severity", "policy_code", "narrative", "status", "return_count",
                       "submitted_at", "routed_by_user_id", "conduct_case_id"),
    "ConductCase": ("incident_report_id", "respondent_student_id", "severity", "status",
                    "opened_at", "hearing_at", "scheduled_by_user_id",
                    "decided_by_user_id", "prior_sanctioned_count", "sanction_points",
                    "outcome"),
    "RoomInspection": ("room_id", "inspector_ra_id", "inspection_type", "scheduled_for",
                       "status", "condition_score", "damage_lines",
                       "responsible_student_id", "damage_charge_id", "completed_at"),
    "DamageCharge": ("inspection_id", "student_id", "provisional_subtotal_cents",
                     "assessed_subtotal_cents", "depreciation_rate", "admin_fee_cents",
                     "hardship_relief_cents", "final_amount_cents", "status",
                     "billed_at", "appeal_deadline_at", "appeal_reason",
                     "appeal_outcome"),
    "RoomChangeCase": ("student_id", "roommate_student_id", "from_room_id", "to_room_id",
                       "origin", "mediation_status", "placement_status",
                       "mediation_round", "session_at", "opened_by_user_id",
                       "superseded_case_id", "reverted_from_room_id"),
    "ProgramEvent": ("floor_id", "organizer_ra_id", "title", "category", "scheduled_for",
                     "requested_amount_cents", "status", "encumbered_amount_cents",
                     "attendance_count", "receipt_lines", "reimbursed_amount_cents",
                     "decision_reason"),
    "BreakHousingRequest": ("student_id", "room_id", "break_code", "start_date",
                            "end_date", "reason", "status", "decided_by_user_id",
                            "revocation_cause", "checked_in_at"),
}

DERIVERS = {
    "Building": derive.building_derived,
    "Floor": derive.floor_derived,
    "Room": derive.room_derived,
    "Student": derive.student_derived,
    "RA": derive.ra_derived,
}


def serialize(row):
    kind = row["_type"]
    out = {}
    for key in COMMON:
        out[key] = row[key]
    for key in FIELDS[kind]:
        value = row.get(key)
        out[key] = copy.deepcopy(value) if isinstance(value, (list, dict)) else value
    deriver = DERIVERS.get(kind)
    if deriver:
        out.update(deriver(row))
    return out


def serialize_many(rows):
    return [serialize(r) for r in rows]


# ------------------------------------------------------------- versioning
def _fingerprint(row):
    data = serialize(row)
    data.pop("version", None)
    data.pop("updated_at", None)
    return json.dumps(data, sort_keys=True, default=str)


def snapshot():
    snap = {}
    for table in store.TABLE_NAMES:
        for row_id, row in DB[table].items():
            snap[row_id] = _fingerprint(row)
    return snap


def finalize(snap, already_touched=()):
    """Bump version/updated_at on every pre-existing row whose content changed."""
    if snap is None:
        return
    for table in store.TABLE_NAMES:
        for row_id, row in DB[table].items():
            before = snap.get(row_id)
            if before is None or row_id in already_touched:
                continue
            if _fingerprint(row) != before:
                store.touch(row)
