"""Deviation endpoints (PRD 3.5): raise/list/CLOSE/REOPEN with cascades."""
from flask import Blueprint, request

import envelope
import posture
import serialize
import store
from auth import require_auth
from constants import (
    CONCLUSIONS_BY_KIND,
    DEVIATION_ACTIONS,
    DEVIATION_KINDS_MANUAL,
    DEVIATION_SEVERITIES,
    OPEN_DEVIATION_STATUSES,
)
from errors import err
from validate import action_value, body, must_get, paginate, req_enum, req_str

bp = Blueprint("deviations", __name__)

_DEVIATION_CREATORS = ("ManufacturingOperator", "QualityControlAnalyst", "QualityAssuranceReviewer")


def _open_hold(batch):
    """CRITICAL deviation opens on a batch in review -> UNDER_INVESTIGATION."""
    if batch["quality_status"] in ("READY_FOR_REVIEW", "PENDING_DISPOSITION"):
        batch["quality_hold_return_status"] = batch["quality_status"]
        batch["quality_status"] = "UNDER_INVESTIGATION"
        store.touch(batch)


@bp.route("/batches/<bid>/deviations", methods=["POST"])
def create_deviation(bid):
    user = require_auth(_DEVIATION_CREATORS)
    batch = must_get("batch", bid)
    d = body()
    kind = req_str(d, "kind")
    if kind not in DEVIATION_KINDS_MANUAL:
        # OOS deviations are system-created only; anything else is not a kind.
        err("ERR_INVALID_REQUEST", "kind must be PROCESS or COMPLAINT")
    severity = req_enum(d, "severity", DEVIATION_SEVERITIES)
    description = req_str(d, "description")
    rec = store.create_rec("deviations", {
        "batch_lot_id": batch["id"],
        "kind": kind,
        "severity": severity,
        "description": description,
        "linked_test_id": None,
        "status": "OPEN",
        "conclusion": None,
        "capa_summary": None,
        "opened_by_user_id": user,
        "closed_by_user_id": None,
    })
    if severity == "CRITICAL":
        posture.recompute_site(posture.site_of_batch(batch))
        _open_hold(batch)
    return envelope.ok(serialize.deviation(rec), 201)


@bp.route("/batches/<bid>/deviations", methods=["GET"])
def list_deviations(bid):
    require_auth(("Any",))
    must_get("batch", bid)
    recs = [v for v in store.all_recs("deviations") if v["batch_lot_id"] == bid]
    kind_f = request.args.get("kind")
    status_f = request.args.get("status")
    severity_f = request.args.get("severity")
    if kind_f is not None:
        recs = [v for v in recs if v["kind"] == kind_f]
    if status_f is not None:
        recs = [v for v in recs if v["status"] == status_f]
    if severity_f is not None:
        recs = [v for v in recs if v["severity"] == severity_f]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.deviation(v) for v in page], total, limit, offset)


def _close(rec, user, d):
    conclusion = req_str(d, "conclusion")
    if conclusion not in CONCLUSIONS_BY_KIND[rec["kind"]]:
        err("ERR_INVALID_REQUEST", f"conclusion inadmissible for kind {rec['kind']}")
    capa = d.get("capa_summary")
    if rec["severity"] == "CRITICAL" and (capa is None or not isinstance(capa, str)):
        err("ERR_INVALID_REQUEST", "capa_summary is required for a CRITICAL close")
    if rec["status"] not in OPEN_DEVIATION_STATUSES:
        err("ERR_DEVIATION_NOT_OPEN", "CLOSE requires OPEN or REOPENED")
    rec["status"] = "CLOSED"
    rec["conclusion"] = conclusion
    rec["capa_summary"] = capa
    rec["closed_by_user_id"] = user
    store.touch(rec)
    batch = store.get("batches", rec["batch_lot_id"])
    if rec["kind"] == "OOS" and rec["linked_test_id"]:
        test = store.get("tests", rec["linked_test_id"])
        if test is not None and test["status"] == "OOS_SUSPECT":
            if conclusion == "INVALIDATED_TEST":
                test["status"] = "INVALIDATED"
            else:  # CONFIRMED_OOS
                test["status"] = "OOS_CONFIRMED"
            store.touch(test)
        if conclusion == "CONFIRMED_OOS":
            _open_hold(batch)
    if rec["kind"] == "COMPLAINT" and rec["severity"] == "CRITICAL" \
            and conclusion == "CONFIRMED" and batch["quality_status"] == "RELEASED":
        batch["quality_status"] = "QUARANTINED"
        store.touch(batch)
        for s in store.all_recs("shipments"):
            if s["batch_lot_id"] == batch["id"] \
                    and s["status"] in ("PLANNED", "IN_TRANSIT", "EXCURSION_HOLD"):
                s["status"] = "QUARANTINED"  # PLANNED occupancy released
                store.touch(s)
    if rec["severity"] == "CRITICAL":
        posture.recompute_site(posture.site_of_batch(batch))
    _maybe_release_hold(batch)


def _maybe_release_hold(batch):
    """Last open deviation closed -> restore held quality status."""
    open_left = any(
        v["batch_lot_id"] == batch["id"] and v["status"] in OPEN_DEVIATION_STATUSES
        for v in store.all_recs("deviations"))
    if not open_left and batch["quality_status"] == "UNDER_INVESTIGATION":
        batch["quality_status"] = batch["quality_hold_return_status"]
        batch["quality_hold_return_status"] = None
        store.touch(batch)


def _reopen(rec, d):
    justification = d.get("justification")
    if justification is None or not isinstance(justification, str):
        err("ERR_INVALID_REQUEST", "justification is required for REOPEN")
    if rec["status"] != "CLOSED":
        err("ERR_DEVIATION_NOT_OPEN", "REOPEN requires CLOSED")
    rec["status"] = "REOPENED"
    rec["conclusion"] = None
    rec["closed_by_user_id"] = None
    store.touch(rec)
    if rec["severity"] == "CRITICAL":
        posture.recompute_site(posture.site_of_batch(store.get("batches", rec["batch_lot_id"])))


@bp.route("/deviations/<did>/action", methods=["POST"])
def deviation_action(did):
    user = require_auth(("QualityAssuranceReviewer",))
    rec = must_get("deviation", did)
    d = body()
    act = action_value(d, "action", DEVIATION_ACTIONS)
    if act == "CLOSE":
        _close(rec, user, d)
    else:
        _reopen(rec, d)
    return envelope.ok(serialize.deviation(rec), 200)
