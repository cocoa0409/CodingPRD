"""All GET endpoints plus the logical-clock control."""
from flask import Blueprint

import calc
import derive
import responses
import store
import validators as V
from auth import endpoint
from constants import API_PREFIX

ALL = ["ResidenceDirector", "ResidentAssistant", "ConductOfficer",
       "BursarOfficer", "Student"]

bp = Blueprint("reads", __name__)


def _single(kind, path_name):
    def make(row_id):
        return responses.obj(V.must_get(kind, row_id))
    return make


# ------------------------------------------------------- single resources
SINGLES = [
    ("buildings", "building_id", "Building"),
    ("floors", "floor_id", "Floor"),
    ("rooms", "room_id", "Room"),
    ("students", "student_id", "Student"),
    ("ra-applications", "application_id", "RAApplication"),
    ("ras", "ra_id", "RA"),
    ("duty-shifts", "shift_id", "DutyShift"),
    ("incident-reports", "report_id", "IncidentReport"),
    ("conduct-cases", "case_id", "ConductCase"),
    ("room-inspections", "inspection_id", "RoomInspection"),
    ("damage-charges", "charge_id", "DamageCharge"),
    ("room-change-cases", "case_id", "RoomChangeCase"),
    ("program-events", "event_id", "ProgramEvent"),
    ("break-housing-requests", "request_id", "BreakHousingRequest"),
]

for _segment, _param, _kind in SINGLES:
    def _make_single(kind=_kind, param=_param):
        @endpoint(ALL, mutating=False)
        def view(**kwargs):
            return responses.obj(V.must_get(kind, kwargs[param]))
        return view
    bp.add_url_rule(
        "%s/%s/<%s>" % (API_PREFIX, _segment, _param),
        endpoint="get_%s" % _kind,
        view_func=_make_single(),
        methods=["GET"],
    )


# ----------------------------------------------------------- collections
COLLECTIONS = [
    ("buildings", "buildings", {"posture": "posture"}),
    ("floors", "floors", {"building_id": "building_id",
                          "programming_compliance_status": "programming_compliance_status"}),
    ("rooms", "rooms", {"floor_id": "floor_id", "status": "status"}),
    ("students", "students", {"current_room_id": "current_room_id",
                              "conduct_standing": "conduct_standing",
                              "housing_status": "housing_status"}),
    ("ra-applications", "applications", {"applicant_student_id": "applicant_student_id",
                                         "created_ra_id": "created_ra_id",
                                         "status": "status",
                                         "term_code": "term_code"}),
    ("ras", "ras", {"student_id": "student_id", "application_id": "application_id",
                    "assigned_floor_id": "assigned_floor_id",
                    "employment_status": "employment_status",
                    "certification_status": "certification_status"}),
    ("duty-shifts", "shifts", {"floor_id": "floor_id",
                               "assigned_ra_id": "assigned_ra_id",
                               "swap_requested_ra_id": "swap_requested_ra_id",
                               "status": "status"}),
    ("incident-reports", "incidents", {"filed_by_ra_id": "filed_by_ra_id",
                                       "room_id": "room_id",
                                       "subject_student_id": "subject_student_id",
                                       "conduct_case_id": "conduct_case_id",
                                       "status": "status"}),
    ("conduct-cases", "conduct_cases", {"incident_report_id": "incident_report_id",
                                        "respondent_student_id": "respondent_student_id",
                                        "status": "status"}),
    ("room-inspections", "inspections", {"room_id": "room_id",
                                         "inspector_ra_id": "inspector_ra_id",
                                         "responsible_student_id": "responsible_student_id",
                                         "damage_charge_id": "damage_charge_id",
                                         "status": "status"}),
    ("damage-charges", "charges", {"inspection_id": "inspection_id",
                                   "student_id": "student_id", "status": "status"}),
    ("room-change-cases", "rc_cases", {"student_id": "student_id",
                                       "roommate_student_id": "roommate_student_id",
                                       "from_room_id": "from_room_id",
                                       "to_room_id": "to_room_id",
                                       "reverted_from_room_id": "reverted_from_room_id",
                                       "superseded_case_id": "superseded_case_id",
                                       "placement_status": "placement_status",
                                       "mediation_status": "mediation_status"}),
    ("program-events", "events", {"floor_id": "floor_id",
                                  "organizer_ra_id": "organizer_ra_id",
                                  "category": "category", "status": "status"}),
    ("break-housing-requests", "breaks", {"student_id": "student_id",
                                          "room_id": "room_id",
                                          "break_code": "break_code",
                                          "status": "status"}),
]

for _segment, _table, _spec in COLLECTIONS:
    def _make_list(table=_table, spec=_spec):
        @endpoint(ALL, mutating=False)
        def view():
            rows, total, limit, offset = V.listing(table, spec)
            return responses.page(rows, total, limit, offset)
        return view
    bp.add_url_rule(
        "%s/%s" % (API_PREFIX, _segment),
        endpoint="list_%s" % _table,
        view_func=_make_list(),
        methods=["GET"],
    )


# ------------------------------------------------------- computed reads
@bp.route("%s/buildings/<building_id>/census" % API_PREFIX, methods=["GET"])
@endpoint(ALL, mutating=False)
def census(building_id):
    building = V.must_get("Building", building_id)
    return responses.raw(derive.occupancy_census(building))


@bp.route("%s/floors/<floor_id>/programming-summary" % API_PREFIX, methods=["GET"])
@endpoint(ALL, mutating=False)
def programming_summary(floor_id):
    floor = V.must_get("Floor", floor_id)
    held, status, has_edu, has_well = derive.floor_compliance(floor)
    budget = floor["programming_budget_cents"]
    encumbered = derive.floor_encumbered(floor)
    spent = derive.floor_spent(floor)
    return responses.raw({
        "budget_cents": budget,
        "encumbered_cents": encumbered,
        "spent_cents": spent,
        "available_cents": budget - encumbered - spent,
        "held_program_count": held,
        "compliance_status": status,
        "has_educational": has_edu,
        "has_wellness": has_well,
    })


@bp.route("%s/ras/<ra_id>/duty-load" % API_PREFIX, methods=["GET"])
@endpoint(ALL, mutating=False)
def duty_load(ra_id):
    ra = V.must_get("RA", ra_id)
    forward = calc.forward_28_shifts(ra)
    return responses.raw({
        "term_to_date_score": calc.term_to_date_score(ra),
        "forward_28_score": sum(
            __import__("constants").DUTY_POINTS[s["shift_type"]] for s in forward
        ),
        "missed_shift_count": derive.ra_missed(ra),
        "upcoming_shift_count": len(forward),
    })


# ------------------------------------------------------------- the clock
@bp.route("%s/_clock/set_current_utc" % API_PREFIX, methods=["POST"])
@endpoint(["ResidenceDirector"], mutating=False)
def set_clock():
    body = V.body()
    instant = V.s_dt(body, "to_iso8601")
    previous = store.set_clock(instant)
    return responses.raw({
        "current_utc": store.fmt_iso(instant),
        "previous_utc": store.fmt_iso(previous),
    })
