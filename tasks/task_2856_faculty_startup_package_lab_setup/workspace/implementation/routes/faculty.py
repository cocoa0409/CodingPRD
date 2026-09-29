"""Faculty endpoints and the departure / separation entry points (PRD 3.1, 3.9)."""

from flask import Blueprint

import authz
import cascades
import envelope
import ledger
import lookups
import serialize
import store
import validate
from errors import fail

bp = Blueprint("faculty", __name__)

RANKS = ("ASSISTANT", "ASSOCIATE", "FULL")
APPOINTMENT_STATUSES = (
    "CANDIDATE",
    "ACTIVE",
    "DEPARTURE_NOTICE",
    "DEPARTED",
    "TRANSFERRED_INTERNAL",
)
DEPARTURE_INTENTS = ("DEPARTURE", "INTERNAL_TRANSFER", "OUTSIDE_OFFER")

READ_ROLES = (authz.ROLE_DEAN_OFFICE, authz.ROLE_DEAN, authz.ROLE_DEPARTMENT_CHAIR)


@bp.post("/faculty")
def create_faculty():
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    full_name = validate.string(payload, "full_name")
    rank = validate.enum(payload, "rank", RANKS)
    unit_id = validate.identifier(payload, "funding_unit_id")
    planned_start = validate.calendar_date(payload, "planned_start_date")
    lookups.get_unit_typed(unit_id, "DEPARTMENT", "funding_unit_id")
    record = {
        "id": store.new_id(),
        "full_name": full_name,
        "rank": rank,
        "funding_unit_id": unit_id,
        "appointment_status": "CANDIDATE",
        "planned_start_date": planned_start.isoformat(),
        "activated_on": None,
        "departure_intent": None,
        "departure_effective_on": None,
        "target_funding_unit_id": None,
        "separated_on": None,
        "retention_round": 0,
    }
    store.stamp_new(record)
    store.db.faculty[record["id"]] = record
    return envelope.created(serialize.faculty(record))


@bp.get("/faculty")
def list_faculty():
    authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    unit_filter = validate.filter_value("funding_unit_id")
    target_filter = validate.filter_value("target_funding_unit_id")
    status_filter = validate.filter_value("appointment_status", APPOINTMENT_STATUSES)
    records = store.by_created(list(store.db.faculty.values()))
    if unit_filter is not None:
        records = [f for f in records if f["funding_unit_id"] == unit_filter]
    if target_filter is not None:
        records = [f for f in records if f["target_funding_unit_id"] == target_filter]
    if status_filter is not None:
        records = [f for f in records if f["appointment_status"] == status_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.faculty(f) for f in page], limit, offset, total
    )


@bp.get("/faculty/<faculty_id>")
def read_faculty(faculty_id):
    act = authz.actor(READ_ROLES + (authz.ROLE_FACULTY,))
    record = lookups.get_faculty(faculty_id)
    authz.faculty_scope(act, record["id"])
    return envelope.object_response(serialize.faculty(record))


@bp.post("/faculty/<faculty_id>/activate")
def activate_faculty(faculty_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    record = lookups.get_faculty(faculty_id)
    if record["appointment_status"] != "CANDIDATE":
        fail(
            "ERR_FACULTY_NOT_ACTIVE",
            "only a CANDIDATE faculty record can record an arrival",
        )
    record["appointment_status"] = "ACTIVE"
    record["activated_on"] = ledger.clock_iso()
    store.touch(record)
    return envelope.object_response(serialize.faculty(record))


@bp.post("/faculty/<faculty_id>/departure-notice")
def departure_notice(faculty_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    intent = validate.enum(payload, "departure_intent", DEPARTURE_INTENTS)
    effective_on = validate.calendar_date(payload, "departure_effective_on")
    target_id = validate.identifier(payload, "target_funding_unit_id", required=False)
    record = lookups.get_faculty(faculty_id)
    if intent == "INTERNAL_TRANSFER":
        if target_id is None:
            fail(
                "ERR_TRANSFER_TARGET_REQUIRED",
                "target_funding_unit_id is required for an INTERNAL_TRANSFER",
            )
        target = store.db.funding_units.get(target_id)
        current = store.db.funding_units.get(record["funding_unit_id"])
        if (
            target is None
            or target["unit_type"] != "DEPARTMENT"
            or target_id == record["funding_unit_id"]
            or current is None
            or target["parent_unit_id"] != current["parent_unit_id"]
        ):
            fail(
                "ERR_TRANSFER_TARGET_REQUIRED",
                "target_funding_unit_id must be another DEPARTMENT of the same college",
            )
    elif target_id is not None:
        fail(
            "ERR_TRANSFER_TARGET_REQUIRED",
            "target_funding_unit_id is only accepted for an INTERNAL_TRANSFER",
        )
    if record["appointment_status"] != "ACTIVE":
        fail("ERR_FACULTY_NOT_ACTIVE", "only an ACTIVE faculty member may give notice")
    record["appointment_status"] = "DEPARTURE_NOTICE"
    record["departure_intent"] = intent
    record["departure_effective_on"] = effective_on.isoformat()
    record["target_funding_unit_id"] = target_id if intent == "INTERNAL_TRANSFER" else None
    store.touch(record)
    cascades.freeze_cascade(record)
    return envelope.object_response(serialize.faculty(record))


@bp.post("/faculty/<faculty_id>/separate")
def separate_faculty(faculty_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    record = lookups.get_faculty(faculty_id)
    if record["appointment_status"] != "DEPARTURE_NOTICE":
        fail(
            "ERR_FACULTY_NOT_ACTIVE",
            "separation requires a faculty member in DEPARTURE_NOTICE",
        )
    effective_on = record["departure_effective_on"]
    if effective_on is not None and ledger.clock_iso()[:10] < effective_on:
        fail(
            "ERR_SEPARATION_NOT_DUE",
            "the clock has not reached departure_effective_on",
        )
    cascades.separation_cascade(record)
    return envelope.object_response(serialize.faculty(record))
