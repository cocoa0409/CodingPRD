"""Fine schedule endpoints: create/list/retire."""

from flask import Blueprint, request

from auth import require_roles
from db import store
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_SCHEDULE_OVERLAP, ERR_LAST_FINE_SCHEDULE)
from helpers import (body, mint_common, touch, get_association,
                     get_fine_schedule, page, parse_dt, _parse_iso)
from response import success_object, success_list
from routes.members import check_not_merged
from routes.citations import RULE_CODES

bp = Blueprint("fines", __name__)


@bp.route("/mls/associations/<assoc_id>/fine-schedules", methods=["POST"])
def create_schedule(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("rule_code", "fine_amount_cents", "effective_from"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    if data["rule_code"] not in RULE_CODES:
        raise_err(ERR_INVALID_REQUEST, "rule_code must be one of %s"
                  % ", ".join(RULE_CODES))
    amount = data["fine_amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "fine_amount_cents must be an integer > 0")
    eff_from = parse_dt(data["effective_from"], "effective_from")
    eff_to = None
    if data.get("effective_to") is not None:
        eff_to = parse_dt(data["effective_to"], "effective_to")
        if eff_to <= eff_from:
            raise_err(ERR_INVALID_REQUEST,
                      "effective_to must be after effective_from")
    # Half-open [effective_from, effective_to) non-overlap vs ACTIVE rows of
    # the same (association, rule_code).
    for row in store.fine_schedules.values():
        if row["association_id"] != assoc_id or row["rule_code"] != data["rule_code"]:
            continue
        if row["status"] != "ACTIVE":
            continue
        r_from = _parse_iso(row["effective_from"])
        r_to = _parse_iso(row["effective_to"]) if row.get("effective_to") else None
        new_end = eff_to
        row_end = r_to
        overlap = (eff_from < row_end if row_end is not None else True) and \
                  (r_from < new_end if new_end is not None else True)
        # precise half-open overlap: max(starts) < min(ends), None end = +inf
        start_max = max(eff_from, r_from)
        ends = [e for e in (new_end, row_end) if e is not None]
        if ends:
            end_min = min(ends)
            overlap = start_max < end_min
        else:
            overlap = True
        if overlap:
            raise_err(ERR_SCHEDULE_OVERLAP,
                      "FineSchedule row overlaps an existing ACTIVE row")
    row = {
        "association_id": assoc_id,
        "rule_code": data["rule_code"],
        "fine_amount_cents": amount,
        "effective_from": data["effective_from"],
        "effective_to": data.get("effective_to"),
        "status": "ACTIVE",
    }
    mint_common(row)
    store.fine_schedules[row["id"]] = row
    return success_object(row, 201)


@bp.route("/mls/associations/<assoc_id>/fine-schedules", methods=["GET"])
def list_schedules(assoc_id):
    require_roles("AssociationStaff")
    get_association(assoc_id)
    items = [r for r in store.fine_schedules.values()
             if r["association_id"] == assoc_id]
    rule_code = request.args.get("rule_code")
    if rule_code is not None:
        items = [r for r in items if r["rule_code"] == rule_code]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/fine-schedules/<schedule_id>/retire",
          methods=["POST"])
def retire_schedule(assoc_id, schedule_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    row = get_fine_schedule(schedule_id, assoc_id)
    check_not_merged(assoc)
    if row["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE schedule row may be retired")
    remaining = [r for r in store.fine_schedules.values()
                 if r["association_id"] == assoc_id
                 and r["rule_code"] == row["rule_code"]
                 and r["status"] == "ACTIVE"
                 and r["id"] != row["id"]]
    if not remaining:
        raise_err(ERR_LAST_FINE_SCHEDULE,
                  "Retiring the last ACTIVE FineSchedule row for this rule is forbidden")
    row["status"] = "RETIRED"
    touch(row)
    return success_object(row)
