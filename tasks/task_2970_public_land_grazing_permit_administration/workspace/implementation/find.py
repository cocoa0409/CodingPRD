"""Path and body foreign-key resolution (PRD 2.6 priorities 5 and 6) plus the
exact-equality list filters of PRD 2.3."""

from flask import request

from errors import ApiError
import store

NOT_FOUND = {
    "allotments": "ERR_ALLOTMENT_NOT_FOUND",
    "pastures": "ERR_PASTURE_NOT_FOUND",
    "permittees": "ERR_PERMITTEE_NOT_FOUND",
    "base_properties": "ERR_BASE_PROPERTY_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "aois": "ERR_AOI_NOT_FOUND",
    "use_records": "ERR_USE_RECORD_NOT_FOUND",
    "bills": "ERR_BILL_NOT_FOUND",
    "assessments": "ERR_ASSESSMENT_NOT_FOUND",
    "decisions": "ERR_DECISION_NOT_FOUND",
    "appeals": "ERR_APPEAL_NOT_FOUND",
    "closure_orders": "ERR_CLOSURE_ORDER_NOT_FOUND",
    "trespass_incidents": "ERR_TRESPASS_NOT_FOUND",
    "projects": "ERR_PROJECT_NOT_FOUND",
}


def need(collection, record_id):
    record = store.get(collection, record_id)
    if record is None:
        raise ApiError(NOT_FOUND[collection], "%s does not exist" % record_id)
    return record


def need_optional(collection, record_id):
    if record_id is None:
        return None
    return need(collection, record_id)


# ----------------------------------------------------------------- list filters


def _as_bool(text):
    lowered = text.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def apply_filters(records, spec):
    """spec is a list of (query_param, record_field, kind) triples. A filter value
    that cannot possibly match simply matches nothing."""
    out = records
    for param, field, kind in spec:
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind == "int":
            try:
                wanted = int(raw.strip())
            except (TypeError, ValueError):
                return []
        elif kind == "bool":
            wanted = _as_bool(raw)
            if wanted is None:
                return []
        else:
            wanted = raw
        out = [record for record in out if record.get(field) == wanted]
    return out
