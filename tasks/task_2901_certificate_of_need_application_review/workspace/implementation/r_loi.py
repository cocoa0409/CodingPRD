"""Letters of intent and the review-threshold determination (PRD §3.3)."""

from flask import Blueprint

import auth
import calc
import clock
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("loi", __name__)

READ_ROLES = ["ProgramAdmin", "IntakeAnalyst", "ReviewAnalyst", "DecisionOfficer", "Applicant"]
LIST_ROLES = READ_ROLES + ["PublicParticipant"]
AGGREGATING_STATUSES = ("FILED", "CONVERTED")
BLOCKING_STATUSES = ("FILED", "CONVERTED")


def _priors(applicant_id, hsa_id, self_id, filed_at):
    """The qualifying 24-calendar-month lookback set: [window_open, filed_at)."""
    window_open = clock.minus_months(filed_at, calc.LOOKBACK_MONTHS)
    result = []
    for row in store.rows("letters_of_intent"):
        if row["id"] == self_id:
            continue
        if row["applicant_id"] != applicant_id or row["hsa_id"] != hsa_id:
            continue
        if row["status"] not in AGGREGATING_STATUSES:
            continue
        moment = clock.parse_instant(row["filed_at"])
        if moment is None:
            continue
        if moment >= window_open and moment < filed_at:
            result.append(row)
    return result


@bp.post("/letters-of-intent")
def file_loi():
    user_id, _role = auth.identity(["Applicant"])
    body = shape.body()
    applicant_id = shape.string_field(body, "applicant_id")
    hsa_id = shape.string_field(body, "hsa_id")
    cycle_id = shape.string_field(body, "batching_cycle_id")
    service_type = shape.enum_field(body, "service_type", shape.SERVICE_TYPES)
    description = shape.string_field(body, "project_description")
    capital_cost = shape.int_field(body, "capital_cost_cents", minimum=0)
    bed_delta = shape.int_field(body, "bed_delta", minimum=0)

    applicant_row = services.applicant(applicant_id)
    services.hsa(hsa_id)
    cycle_row = services.cycle(cycle_id)

    services.require_owner(user_id, applicant_id)

    if service_type != cycle_row["service_type"]:
        raise ApiError("ERR_SERVICE_TYPE_MISMATCH",
                       "The letter's service_type must equal the cycle's service_type.")

    services.require_standing_good(applicant_row)

    filed_at = clock.now()
    if cycle_row["status"] != "OPEN_FOR_LOI":
        raise ApiError("ERR_LOI_WINDOW_CLOSED", "The cycle is no longer open for letters.")
    if filed_at > clock.parse_instant(cycle_row["loi_deadline_at"]):
        raise ApiError("ERR_LOI_WINDOW_CLOSED", "The letter-of-intent window has closed.")

    for row in store.rows("letters_of_intent"):
        if (row["applicant_id"] == applicant_id
                and row["batching_cycle_id"] == cycle_id
                and row["status"] in BLOCKING_STATUSES):
            raise ApiError("ERR_DUPLICATE_LOI",
                           "This applicant already has a live letter in this cycle.")

    determination = calc.review_threshold_determination(
        service_type, capital_cost, bed_delta, filed_at,
        _priors(applicant_id, hsa_id, None, filed_at))

    fields = {
        "applicant_id": applicant_id,
        "hsa_id": hsa_id,
        "batching_cycle_id": cycle_id,
        "service_type": service_type,
        "project_description": description,
        "capital_cost_cents": capital_cost,
        "bed_delta": bed_delta,
        "filed_at": clock.fmt(filed_at),
    }
    fields.update(determination)
    fields["status"] = "FILED"
    record = store.create("letters_of_intent", fields)
    return envelope.ok(record, 201)


@bp.get("/letters-of-intent/<record_id>")
def read_loi(record_id):
    auth.identity(READ_ROLES)
    return envelope.ok(services.loi(record_id))


@bp.get("/letters-of-intent")
def list_loi():
    auth.identity(LIST_ROLES)
    limit, offset = shape.pagination()
    picked = shape.filters("applicant_id", "hsa_id", "batching_cycle_id", "status")
    rows = shape.apply_filters(store.sort_created(store.rows("letters_of_intent")), picked)
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/letters-of-intent/<record_id>/withdraw")
def withdraw_loi(record_id):
    user_id, _role = auth.identity(["Applicant"])
    body = shape.body()
    shape.string_field(body, "reason", required=False, default=None)
    record = services.loi(record_id)
    services.require_owner(user_id, record["applicant_id"])
    record["status"] = "WITHDRAWN"
    store.touch(record)
    return envelope.ok(record)
