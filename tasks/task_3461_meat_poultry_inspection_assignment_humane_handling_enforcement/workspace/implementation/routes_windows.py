"""Shift windows and coverage verification (PRD §3.2)."""
from flask import Blueprint, request

import calc
import store
from authz import require_ownership, require_roles
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SHIFT_WINDOW_NOT_FOUND
from guards import (
    establishment_or_404,
    entity_or_404,
    require_granted,
    require_not_suspended,
    require_not_withdrawn,
)
from store import insert, stamp_new, touch
from validate import SHIFT_TYPES, require_enum, require_int, require_string, require_timestamp

bp = Blueprint("shift_windows", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "SupervisoryReviewer", "DistrictManager", "ProgramAdministrator")


def _window_or_404(window_id):
    return entity_or_404("shift_windows", window_id, ERR_SHIFT_WINDOW_NOT_FOUND)


@bp.post("/inspection/shift-windows")
def create_shift_window():
    user_id, _ = require_roles("EstablishmentManager")
    body = get_body()
    establishment_id = require_string(body, "establishment_id")
    start_utc = require_timestamp(body, "start_utc")
    end_utc = require_timestamp(body, "end_utc")
    shift_type = require_enum(body, "shift_type", SHIFT_TYPES)
    planned_line_count = require_int(body, "planned_line_count", minimum=1)

    require_ownership(user_id, establishment_id)
    establishment = establishment_or_404(establishment_id)
    # Tier 5 establishment gates (PRD §2.5, §3.2).
    require_not_withdrawn(establishment)
    require_granted(establishment)
    require_not_suspended(establishment)
    # Tier 7 interval shape: the window is half-open [start_utc, end_utc).
    if not (end_utc > start_utc):
        raise_err(ERR_INVALID_REQUEST, "end_utc must be strictly after start_utc")

    window = {
        "establishment_id": establishment_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "shift_type": shift_type,
        "planned_line_count": planned_line_count,
        "status": "PLANNED",
        "provisional_gap_minutes": None,
        "final_gap_minutes": None,
    }
    stamp_new(window)
    insert("shift_windows", window)
    return success_object(window, status=201)


@bp.get("/inspection/establishments/<est_id>/shift-windows")
def list_shift_windows(est_id):
    require_roles(*READ_ROLES)
    establishment_or_404(est_id)
    status_filter = request.args.get("status")
    rows = [w for w in store.all_of("shift_windows") if w["establishment_id"] == est_id]
    if status_filter is not None:
        rows = [w for w in rows if w["status"] == status_filter]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/inspection/shift-windows/<window_id>")
def get_shift_window(window_id):
    require_roles(*READ_ROLES)
    return success_object(_window_or_404(window_id))


@bp.post("/inspection/shift-windows/<window_id>/verify-coverage")
def verify_coverage(window_id):
    user_id, _ = require_roles("Inspector")
    window = _window_or_404(window_id)
    if window["status"] not in ("PLANNED", "COVERAGE_GAP_FLAGGED"):
        raise_err(ERR_INVALID_STATE, "verify-coverage requires status PLANNED or COVERAGE_GAP_FLAGGED")

    provisional = calc.coverage_gap_minutes(window, ("SCHEDULED", "CONFIRMED"))
    final = calc.coverage_gap_minutes(window, ("CONFIRMED",))
    window["provisional_gap_minutes"] = provisional
    window["final_gap_minutes"] = final
    # The final gap drives the transition.
    if final == 0:
        window["status"] = "VERIFIED_COVERED"
    else:
        window["status"] = "COVERAGE_GAP_FLAGGED"
    touch(window)

    # A flagged SLAUGHTER window auto-receives an OTHER-family NR (PRD §3.2).
    if final > 0 and window["shift_type"] == "SLAUGHTER":
        nr = {
            "establishment_id": window["establishment_id"],
            "issued_by_inspector_id": user_id,
            "shift_window_id": None,
            "regulation_family": "OTHER",
            "description": "inspection presence gap",
            "observed_at": store.clock_now(),
            "issued_at": store.clock_now(),
            "status": "OPEN",
            "status_before_appeal": None,
            "response_text": None,
        }
        stamp_new(nr)
        insert("noncompliance_records", nr)

    return success_object(window)
