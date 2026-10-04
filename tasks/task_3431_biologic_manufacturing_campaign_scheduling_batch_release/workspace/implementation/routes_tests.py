"""In-process test endpoints (PRD 3.4): record (OCC), list, verify."""
from decimal import Decimal

from flask import Blueprint, request

import envelope
import posture
import serialize
import store
from auth import require_auth
from constants import SYSTEM_USER, TEST_PHASES, TEST_TYPES
from errors import err
from validate import body, must_get, opt_str, paginate, req_enum, req_num, req_present, req_str

bp = Blueprint("tests", __name__)


@bp.route("/batches/<bid>/tests", methods=["POST"])
def record_test(bid):
    user = require_auth(("ManufacturingOperator",))
    batch = must_get("batch", bid)
    d = body()
    # Body-supplied reference existence (stage 3) precedes well-formedness (stage 4).
    raw_supersedes = d.get("supersedes_test_id")
    if isinstance(raw_supersedes, str):
        must_get("test", raw_supersedes)
    test_type = req_enum(d, "test_type", TEST_TYPES)
    phase = req_enum(d, "phase", TEST_PHASES)
    measured = req_num(d, "measured_value")
    unit = req_str(d, "unit")
    spec_min = req_num(d, "spec_min")
    spec_max = req_num(d, "spec_max")
    if not Decimal(str(spec_min)) < Decimal(str(spec_max)):
        err("ERR_INVALID_SPEC_BOUNDS", "spec_min must be < spec_max")
    expected = req_present(d, "expected_batch_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        err("ERR_INVALID_REQUEST", "expected_batch_version must be an integer")
    supersedes_id = opt_str(d, "supersedes_test_id")
    # OCC (stage 5) runs before any business rule of this endpoint.
    if expected != batch["version"]:
        err("ERR_STALE_BATCH_VERSION", "expected_batch_version does not match")
    # Business order (PRD 3.4): supersession validity, then phase alignment.
    if supersedes_id is not None:
        target = store.get("tests", supersedes_id)
        if target is None:
            err("ERR_TEST_NOT_FOUND", "supersedes_test_id does not resolve")
        if target["status"] != "INVALIDATED" or target["batch_lot_id"] != batch["id"] \
                or target["test_type"] != test_type or target["phase"] != phase:
            err("ERR_SUPERSEDE_TARGET_NOT_INVALIDATED",
                "supersedes_test_id must reference an INVALIDATED test of the same batch, type and phase")
    if batch["process_status"] not in ("UPSTREAM", "DOWNSTREAM") \
            or phase != batch["process_status"]:
        err("ERR_TEST_PHASE_MISMATCH",
            "Test phase differs from the batch's current process phase")
    in_spec = Decimal(str(spec_min)) <= Decimal(str(measured)) <= Decimal(str(spec_max))
    rec = store.create_rec("tests", {
        "batch_lot_id": batch["id"],
        "test_type": test_type,
        "phase": phase,
        "measured_value": measured,
        "unit": unit,
        "spec_min": spec_min,
        "spec_max": spec_max,
        "is_in_spec": in_spec,
        "supersedes_test_id": supersedes_id,
        "status": "RECORDED",
        "recorded_by_user_id": user,
        "verified_by_user_id": None,
    })
    store.touch(batch)  # recording a test increments the batch version (PRD 2.8)
    return envelope.ok(serialize.test(rec), 201)


@bp.route("/batches/<bid>/tests", methods=["GET"])
def list_tests(bid):
    require_auth(("Any",))
    must_get("batch", bid)
    recs = [t for t in store.all_recs("tests") if t["batch_lot_id"] == bid]
    status_f = request.args.get("status")
    phase_f = request.args.get("phase")
    if status_f is not None:
        recs = [t for t in recs if t["status"] == status_f]
    if phase_f is not None:
        recs = [t for t in recs if t["phase"] == phase_f]
    page, total, limit, offset = paginate(recs)
    return envelope.ok_list([serialize.test(t) for t in page], total, limit, offset)


@bp.route("/tests/<tid>/verify", methods=["POST"])
def verify_test(tid):
    user = require_auth(("QualityControlAnalyst",))
    rec = must_get("test", tid)
    if rec["status"] != "RECORDED":
        err("ERR_TEST_NOT_RECORDED", "verify requires RECORDED")
    if user == rec["recorded_by_user_id"]:
        err("ERR_FOUR_EYES_VIOLATION", "Verifier must differ from recorder")
    rec["verified_by_user_id"] = user
    if rec["is_in_spec"]:
        rec["status"] = "VERIFIED"
        store.touch(rec)
        return envelope.ok(serialize.test(rec), 200)
    rec["status"] = "OOS_SUSPECT"
    store.touch(rec)
    batch = store.get("batches", rec["batch_lot_id"])
    severity = "CRITICAL" if rec["phase"] == "DOWNSTREAM" else "MAJOR"
    deviation = store.create_rec("deviations", {
        "batch_lot_id": batch["id"],
        "kind": "OOS",
        "severity": severity,
        "description": f"Out-of-spec {rec['test_type']} result on test {rec['id']}",
        "linked_test_id": rec["id"],
        "status": "OPEN",
        "conclusion": None,
        "capa_summary": None,
        "opened_by_user_id": SYSTEM_USER,
        "closed_by_user_id": None,
    })
    if severity == "CRITICAL":
        if batch["quality_status"] in ("READY_FOR_REVIEW", "PENDING_DISPOSITION"):
            batch["quality_hold_return_status"] = batch["quality_status"]
            batch["quality_status"] = "UNDER_INVESTIGATION"
            store.touch(batch)
        posture.recompute_site(posture.site_of_batch(batch))
    return envelope.ok(serialize.test(rec), 200)
