"""Sponsor agreement endpoints: create (under a sponsor), read, list, amend
(supersede-with-new, OCC-guarded, temporal overlap before pool floor)."""

from datetime import date

from flask import Blueprint, g, request

import constants as C
from errors import err
from helpers import (
    apply_filters,
    bad,
    body,
    check_date_string,
    check_int_field,
    created_key,
    is_int,
    paginate,
    require_present,
    require_roles,
    resp_object,
)
from serializers import ser_agreement
from store import base_record, db, touch

bp = Blueprint("agreements", __name__)


def _get_agreement_or_404(agreement_id):
    rec = db["agreements"].get(agreement_id)
    if rec is None:
        err("ERR_NOT_FOUND", "sponsor agreement not found")
    return rec


def _windows_overlap(start1, end1, start2, end2):
    """Half-open [start, end): adjacency (a.end == b.start) is allowed."""
    return start1 < end2 and start2 < end1


def _check_window_overlap(sponsor_id, cycle_id, start, end, exclude_id=None):
    """Same sponsor + same cycle, non-superseded agreements only."""
    for other in db["agreements"].values():
        if other["sponsor_id"] != sponsor_id or other["cycle_id"] != cycle_id:
            continue
        if other["status"] == "SUPERSEDED":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        other_start = date.fromisoformat(other["effective_start_date"])
        other_end = date.fromisoformat(other["effective_end_date"])
        if _windows_overlap(start, end, other_start, other_end):
            err("ERR_AGREEMENT_WINDOW_OVERLAP", "effective window overlaps another agreement")


def _validate_agreement_shape(values):
    """Field-shape validation for a merged agreement payload."""
    if not is_int(values["award_amount_cents"]) or values["award_amount_cents"] <= 0:
        bad("award_amount_cents must be an integer > 0")
    if not is_int(values["max_awards"]) or values["max_awards"] < 1:
        bad("max_awards must be an integer >= 1")
    if not is_int(values["pool_total_cents"]) or values["pool_total_cents"] < 0:
        bad("pool_total_cents must be a non-negative integer")
    if values["pool_total_cents"] < values["award_amount_cents"]:
        bad("pool_total_cents must be at least award_amount_cents")
    if not isinstance(values["employee_children_only"], bool):
        bad("employee_children_only must be a boolean")
    if values["min_selection_index"] is not None and not is_int(values["min_selection_index"]):
        bad("min_selection_index must be an integer or null")
    start = check_date_string(values["effective_start_date"], "effective_start_date")
    end = check_date_string(values["effective_end_date"], "effective_end_date")
    if not start < end:
        bad("effective_start_date must be strictly before effective_end_date")
    return start, end


def _agreement_record(values, sponsor_id, cycle_id, supersedes_id):
    rec = base_record()
    rec.update(
        {
            "sponsor_id": sponsor_id,
            "cycle_id": cycle_id,
            "supersedes_agreement_id": supersedes_id,
            "award_amount_cents": values["award_amount_cents"],
            "max_awards": values["max_awards"],
            "pool_total_cents": values["pool_total_cents"],
            "employee_children_only": values["employee_children_only"],
            "min_selection_index": values["min_selection_index"],
            "effective_start_date": values["effective_start_date"],
            "effective_end_date": values["effective_end_date"],
            "pool_committed_cents": 0,
            "pool_paid_cents": 0,
            "pool_available_reserved_cents": values["pool_total_cents"],
            "pool_available_cash_cents": values["pool_total_cents"],
            "status": "ACTIVE",
        }
    )
    return rec


@bp.route("/api/corporate-sponsors/<sponsor_id>/agreements", methods=["POST"])
@require_roles(C.ROLE_SPONSOR_ADMIN)
def create_agreement(sponsor_id):
    # Priority 3, ownership: acting sponsor == path sponsor (string compare).
    if g.user_id != sponsor_id:
        err("ERR_FORBIDDEN_OWNERSHIP", "sponsors may only administer their own agreements")
    # Priority 4, existence: path sponsor, then body-referenced cycle.
    if sponsor_id not in db["sponsors"]:
        err("ERR_NOT_FOUND", "corporate sponsor not found")
    b = body()
    if b.get("cycle_id") is not None and b["cycle_id"] not in db["cycles"]:
        bad("referenced cycle_id does not exist")
    require_present(
        b,
        "cycle_id",
        "award_amount_cents",
        "max_awards",
        "pool_total_cents",
        "effective_start_date",
        "effective_end_date",
    )
    values = {
        "award_amount_cents": b.get("award_amount_cents"),
        "max_awards": b.get("max_awards"),
        "pool_total_cents": b.get("pool_total_cents"),
        "employee_children_only": b.get("employee_children_only", True),
        "min_selection_index": b.get("min_selection_index"),
        "effective_start_date": b.get("effective_start_date"),
        "effective_end_date": b.get("effective_end_date"),
    }
    # Priority 8, temporal overlap (parseable windows only; malformed dates
    # fall through to the priority-10 shape check).
    start, end = None, None
    try:
        start = date.fromisoformat(str(values["effective_start_date"]))
        end = date.fromisoformat(str(values["effective_end_date"]))
    except (ValueError, TypeError):
        pass
    if start is not None and end is not None:
        _check_window_overlap(sponsor_id, b["cycle_id"], start, end)
    # Priority 10, field shape.
    _validate_agreement_shape(values)
    rec = _agreement_record(values, sponsor_id, b["cycle_id"], None)
    db["agreements"][rec["id"]] = rec
    return resp_object(ser_agreement(rec), code=201)


@bp.route("/api/sponsor-agreements/<agreement_id>", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_SPONSOR_ADMIN)
def get_agreement(agreement_id):
    rec = _get_agreement_or_404(agreement_id)
    if g.user_role == C.ROLE_SPONSOR_ADMIN and g.user_id != rec["sponsor_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "sponsors may only read their own agreements")
    return resp_object(ser_agreement(rec))


@bp.route("/api/sponsor-agreements", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_SPONSOR_ADMIN)
def list_agreements():
    records = sorted(db["agreements"].values(), key=created_key)
    records = apply_filters(
        records,
        [
            ("sponsor_id", request.args.get("sponsor_id")),
            ("cycle_id", request.args.get("cycle_id")),
            ("supersedes_agreement_id", request.args.get("supersedes_agreement_id")),
            ("status", request.args.get("status")),
        ],
    )
    return paginate(records, ser_agreement)


@bp.route("/api/sponsor-agreements/<agreement_id>/amend", methods=["POST"])
@require_roles(C.ROLE_SPONSOR_ADMIN)
def amend_agreement(agreement_id):
    rec = _get_agreement_or_404(agreement_id)
    # Priority 3, ownership: X-User-ID against the agreement's sponsor_id.
    if g.user_id != rec["sponsor_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "sponsors may only amend their own agreements")
    b = body()
    # Priority 5, optimistic concurrency.
    if "expected_sponsor_agreement_version" in b and b["expected_sponsor_agreement_version"] is not None:
        if b["expected_sponsor_agreement_version"] != rec["version"]:
            err("ERR_STALE_VERSION", "agreement version has advanced")
    # Priority 6, entity state: only ACTIVE or EXHAUSTED may be amended.
    if rec["status"] not in ("ACTIVE", "EXHAUSTED"):
        err("ERR_INVALID_STATE", "only ACTIVE or EXHAUSTED agreements may be amended")
    # Merge: unchanged fields are copied.
    values = {
        "award_amount_cents": b.get("award_amount_cents", rec["award_amount_cents"]),
        "max_awards": b.get("max_awards", rec["max_awards"]),
        "pool_total_cents": b.get("pool_total_cents", rec["pool_total_cents"]),
        "employee_children_only": b.get("employee_children_only", rec["employee_children_only"]),
        "min_selection_index": (
            b["min_selection_index"] if "min_selection_index" in b else rec["min_selection_index"]
        ),
        "effective_start_date": b.get("effective_start_date", rec["effective_start_date"]),
        "effective_end_date": b.get("effective_end_date", rec["effective_end_date"]),
    }
    # Priority 8, temporal overlap — before the pool floor; the agreement
    # being superseded is excluded from the check.
    start, end = None, None
    try:
        start = date.fromisoformat(str(values["effective_start_date"]))
        end = date.fromisoformat(str(values["effective_end_date"]))
    except (ValueError, TypeError):
        pass
    if start is not None and end is not None:
        _check_window_overlap(rec["sponsor_id"], rec["cycle_id"], start, end, exclude_id=rec["id"])
    # Priority 9, fiscal guard: obligations are preserved across amendment.
    if values["pool_total_cents"] is not None and is_int(values["pool_total_cents"]):
        if values["pool_total_cents"] < rec["pool_committed_cents"] + rec["pool_paid_cents"]:
            err("ERR_POOL_BELOW_COMMITTED", "pool_total_cents below committed plus paid")
    # Priority 10, field shape of the merged payload; the OCC field is required.
    _validate_agreement_shape(values)
    if "expected_sponsor_agreement_version" not in b or b["expected_sponsor_agreement_version"] is None:
        bad("expected_sponsor_agreement_version is required")
    # Supersede: the new agreement starts with fresh ledgers; obligations
    # already incurred stay on the old agreement.
    new_rec = _agreement_record(values, rec["sponsor_id"], rec["cycle_id"], rec["id"])
    db["agreements"][new_rec["id"]] = new_rec
    rec["status"] = "SUPERSEDED"
    touch(rec)
    return resp_object(ser_agreement(new_rec), code=201)
