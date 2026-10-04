"""ResponseRecord endpoints: create on an OPEN wave, list by wave, list by
participant."""
from flask import Blueprint

import store
from calc import MAX_TOTAL_BURDEN_MINUTES, billed_minutes
from errors import raise_err
from serialize import record_out
from services import (COUNTED_PARTICIPANT_STATUSES, recompute_burden,
                      records_of_participant, records_of_wave)
from util import new_entity, ok_list, ok_obj, paginate, sort_created
from validation import (ROLE_DATA_MANAGER, STAFF_ROLES, authenticate,
                        authorize, check_schema, get_json_body)

bp = Blueprint("records", __name__)


@bp.post("/evaluation/waves/<wave_id>/records")
def create_record(wave_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_DATA_MANAGER])
    wave = store.waves.get(wave_id)
    if wave is None:
        raise_err("ERR_NOT_FOUND", "Wave not found")
    body = get_json_body()
    check_schema(body, {
        "participant_id": ("str", True),
        "instrument_minutes": ("int", True),
        "payload_ref": ("str", True),
    })
    if body["instrument_minutes"] < 1:
        raise_err("ERR_INVALID_REQUEST", "instrument_minutes must be >= 1")
    participant = store.participants.get(body["participant_id"])
    if participant is None:
        raise_err("ERR_NOT_FOUND", "Participant not found")
    if wave["status"] != "OPEN":
        raise_err("ERR_WAVE_NOT_OPEN",
                  "Records may only be added to an OPEN wave")
    billed = billed_minutes(body["instrument_minutes"], wave["wave_type"])
    if (participant["burden_total_minutes"] + billed
            > MAX_TOTAL_BURDEN_MINUTES):
        raise_err("ERR_BURDEN_CAP_EXCEEDED",
                  "Record would push the participant's billed burden above "
                  "%d minutes" % MAX_TOTAL_BURDEN_MINUTES)
    if participant["status"] not in COUNTED_PARTICIPANT_STATUSES:
        raise_err("ERR_PARTICIPANT_NOT_CONSENTED",
                  "Participant must be CONSENTED or randomized to contribute "
                  "records")
    record = new_entity({
        "wave_id": wave_id,
        "participant_id": body["participant_id"],
        "instrument_minutes": body["instrument_minutes"],
        "payload_ref": body["payload_ref"],
        "billed_minutes": billed,
        "linkage_key": None,
        "status": "RECEIVED",
    })
    store.records[record["id"]] = record
    recompute_burden(participant)
    return ok_obj(record_out(record), 201)


@bp.get("/evaluation/waves/<wave_id>/records")
def list_records_of_wave(wave_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if wave_id not in store.waves:
        raise_err("ERR_NOT_FOUND", "Wave not found")
    items = sort_created(records_of_wave(wave_id))
    page, limit, offset, total = paginate(items)
    return ok_list([record_out(r) for r in page], limit, offset, total)


@bp.get("/evaluation/participants/<participant_id>/records")
def list_records_of_participant(participant_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if participant_id not in store.participants:
        raise_err("ERR_NOT_FOUND", "Participant not found")
    items = sort_created(records_of_participant(participant_id))
    page, limit, offset, total = paginate(items)
    return ok_list([record_out(r) for r in page], limit, offset, total)
