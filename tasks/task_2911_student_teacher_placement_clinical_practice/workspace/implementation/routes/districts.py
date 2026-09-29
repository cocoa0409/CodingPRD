"""District endpoints (PRD 3.3)."""

import re

from flask import Blueprint, request

import envelope
import shapes
import store
import views
from auth import endpoint
from errors import ApiError

bp = Blueprint("districts", __name__)

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

READERS = ["ProgramAdmin", "PlacementCoordinator", "SupervisionLead",
           "CredentialAnalyst"]


@bp.post("/epp/districts")
@endpoint(["ProgramAdmin"])
def create_district():
    body = shapes.body_of(request)
    name = shapes.req_str(body, "name", 1, 120)
    district_code = shapes.req_str(body, "district_code", 1, 32)
    state_code = shapes.req_str(body, "state_code", 2, 2)
    if not _STATE_CODE_RE.match(state_code):
        raise shapes.bad("Field 'state_code' must be two uppercase letters.")
    fingerprint = shapes.opt_bool(body, "requires_district_fingerprint", False)
    travel = shapes.opt_bool(body, "travel_reimbursement_enabled", True)

    for existing in store.DISTRICTS.values():
        if existing["district_code"] == district_code:
            raise ApiError("ERR_DISTRICT_CODE_TAKEN",
                           "district_code is already registered.")

    row = store.new_row({
        "name": name,
        "district_code": district_code,
        "state_code": state_code,
        "requires_district_fingerprint": fingerprint,
        "travel_reimbursement_enabled": travel,
    })
    store.DISTRICTS[row["id"]] = row
    return envelope.created(views.dump(row, views.DISTRICT))


@bp.get("/epp/districts/<district_id>")
@endpoint(READERS)
def read_district(district_id):
    row = store.get_district(district_id)
    return envelope.ok(views.dump(row, views.DISTRICT))


@bp.get("/epp/districts")
@endpoint(READERS)
def list_districts():
    page, page_size = shapes.pagination(request.args)
    state_code = request.args.get("state_code") or None
    fingerprint = shapes.query_bool(request.args,
                                    "requires_district_fingerprint")
    rows = []
    for row in store.all_of(store.DISTRICTS):
        if state_code is not None and row["state_code"] != state_code:
            continue
        if (fingerprint is not None
                and row["requires_district_fingerprint"] != fingerprint):
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.DISTRICT),
                            page, page_size, total)
