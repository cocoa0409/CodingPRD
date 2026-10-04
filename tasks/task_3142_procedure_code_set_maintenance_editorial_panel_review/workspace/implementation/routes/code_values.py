"""Code values: the per-descriptor payment figures and their RVU components."""

from datetime import datetime, timezone

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import ERR_INVALID_STATE, ApiError
from response import object_response
from routes.common import guard, list_response, one
from services import valuation as VA

bp = Blueprint("code_values", __name__)

OFFICER = (auth.LICENSING_OFFICER,)
READERS = (auth.LICENSING_OFFICER, auth.EDITORIAL_STAFF, auth.LICENSEE)
CHANGE_VALUE_READERS = (auth.LICENSING_OFFICER, auth.EDITORIAL_STAFF)


def _default_effective_date(release_id):
    """January 1 of the release year the value belongs to.

    When the value names a cycle, that is January 1 of the cycle's own year.
    A value created directly, with no cycle and no change to date it from, is
    dated to January 1 of the year the logical clock currently reads.
    """
    cycle = store.release_cycles.get(release_id) if release_id else None
    if cycle is not None and cycle.get("year"):
        return datetime(int(cycle["year"]), 1, 1, tzinfo=timezone.utc)
    return datetime(logical_now().year, 1, 1, tzinfo=timezone.utc)


@bp.post("/code-values")
@guard(OFFICER)
def create_code_value(actor):
    data = P.body()
    specialty_id = P.text_or_none(data.get("specialty_id"))
    if specialty_id is not None:
        R.fk(store.societies, specialty_id, "SpecialtySociety")
    change_id = P.text_or_none(data.get("change_id"))
    if change_id is not None:
        R.fk(store.code_changes, change_id, "CodeChange")
    release_id = P.text_or_none(data.get("release_id"))
    if release_id is not None:
        R.fk(store.release_cycles, release_id, "ReleaseCycle")

    value = store.create(store.code_values, {
        "code": P.text(data.get("code")),
        "change_id": change_id,
        "release_id": release_id,
        "work_rvu": P.number(data.get("work_rvu"), 0),
        "facility_pe_rvu": P.number(data.get("facility_pe_rvu"), 0),
        "nonfacility_pe_rvu": P.number(data.get("nonfacility_pe_rvu"), 0),
        "mp_rvu": P.number(data.get("mp_rvu"), 0),
        "conversion_factor": (
            float(P.number(data.get("conversion_factor"), "32.99"))
            if data.get("conversion_factor") not in (None, "")
            else float(VA.DEFAULT_CONVERSION_FACTOR)
        ),
        "specialty_id": specialty_id,
        "rounding_variant": P.text(data.get("rounding_variant"), "AGGREGATE_ROUNDING"),
        "facility_payment_cents": 0,
        "nonfacility_payment_cents": 0,
        "component_round_total_cents": 0,
        "aggregate_round_total_cents": 0,
        "dollar_split_shortfall_cents": 0,
        "release_month": None,
        "effective_date": _default_effective_date(release_id),
        "value_status": "DRAFT",
        "superseded_by_code_value_id": None,
    })
    VA.recompute_code_value(value)
    return object_response(one(value), 201)


@bp.get("/code-values")
@guard(READERS)
def list_code_values(actor):
    rows = store.sorted_rows(store.code_values)
    args = request.args
    for field in ("code", "change_id", "release_id", "specialty_id",
                  "superseded_by_code_value_id", "value_status"):
        wanted = args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    minimum = args.get("min_payment_cents")
    if minimum not in (None, ""):
        rows = [r for r in rows if int(r.get("facility_payment_cents") or 0) >= int(minimum)]
    maximum = args.get("max_payment_cents")
    if maximum not in (None, ""):
        rows = [r for r in rows if int(r.get("facility_payment_cents") or 0) <= int(maximum)]
    return list_response(rows)


@bp.get("/code-values/<value_id>")
@guard(READERS)
def read_code_value(actor, value_id):
    return object_response(one(R.code_value(value_id)))


@bp.get("/code-changes/<change_id>/code-values")
@guard(CHANGE_VALUE_READERS)
def list_change_code_values(actor, change_id):
    change = R.code_change(change_id)
    rows = [v for v in store.sorted_rows(store.code_values)
            if v.get("change_id") == change["id"]]
    return list_response(rows)


@bp.post("/code-values/<value_id>/effective-dates")
@guard(OFFICER)
def restamp_effective_date(actor, value_id):
    value = R.code_value(value_id)
    data = P.body()
    effective = P.dt(data.get("effective_date"))
    if effective is None:
        raise ApiError(ERR_INVALID_STATE, "an effective_date must be supplied")
    value["effective_date"] = effective
    # Restamping re-derives the proration basis and recomputes the payments.
    VA.recompute_code_value(value)
    store.bump(value)
    return object_response(one(value), 200)


@bp.post("/code-values/<value_id>/supersessions")
@guard(OFFICER)
def supersede_code_value(actor, value_id):
    value = R.code_value(value_id)
    data = P.body()
    successor_id = P.text_or_none(data.get("superseded_by_code_value_id"))
    if successor_id is None:
        raise ApiError(ERR_INVALID_STATE, "a successor code value must be named")
    R.code_value(successor_id)
    reason = data.get("reason")
    if reason in (None, ""):
        raise ApiError(ERR_INVALID_STATE, "a supersession must supply a reason")

    value["superseded_by_code_value_id"] = successor_id
    value["supersession_reason"] = P.text(reason)
    value["value_status"] = "SUPERSEDED"
    store.bump(value)
    return object_response(one(value), 200)