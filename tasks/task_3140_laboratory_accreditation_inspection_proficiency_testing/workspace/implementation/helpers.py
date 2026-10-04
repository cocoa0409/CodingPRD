from flask import request

import store
from errors import ApiError
from util import fmt_ts, new_id
from datetime import timedelta

ALL_READERS = [
    "PlatformAdmin",
    "AccreditationOfficer",
    "LaboratoryDirector",
    "PTCoordinator",
    "Inspector",
]

DISCIPLINES = {
    "CHEMISTRY",
    "HEMATOLOGY",
    "MICROBIOLOGY",
    "IMMUNOLOGY",
    "MOLECULAR",
    "TRANSFUSION",
}


def body():
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing required field: {f}")


def get_or_404(store_name, rid, err_id):
    rec = store.STORES[store_name].get(rid)
    if rec is None:
        raise ApiError(err_id, 404, err_id)
    return rec


def new_record(extra):
    seq = store.next_seq()
    # Bump the creation timestamp by seq microseconds so created_at ordering
    # is total even when many records are created at the same logical instant.
    ts = fmt_ts(store.now() + timedelta(microseconds=seq % 1000))
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec["_seq"] = seq
    rec.update(extra)
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
