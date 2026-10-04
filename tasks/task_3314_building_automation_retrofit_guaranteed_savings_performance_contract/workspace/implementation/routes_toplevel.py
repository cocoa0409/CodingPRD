"""Top-level filtered listings across the portfolio."""
from flask import Blueprint, request

import db
import domain
from errors import ApiError, ok
from util import paginate_args, paginate_list, require_roles

bp = Blueprint("toplevel", __name__)

ERRORS = {
    "baseline": "ERR_BASELINE_NOT_FOUND",
    "bundle": "ERR_BUNDLE_NOT_FOUND",
    "measure": "ERR_MEASURE_NOT_FOUND",
    "facility": "ERR_FACILITY_NOT_FOUND",
    "draw": "ERR_DRAW_NOT_FOUND",
    "phase": "ERR_PHASE_NOT_FOUND",
    "disruption": "ERR_REFERENCED_RESOURCE_NOT_FOUND",
    "report": "ERR_REPORT_NOT_FOUND",
    "adjustment": "ERR_ADJUSTMENT_NOT_FOUND",
    "dispute": "ERR_DISPUTE_NOT_FOUND",
}


def _list(store, ser, filters=()):
    require_roles()
    limit, offset = paginate_args()
    items = list(store.values())
    for param, field in filters:
        v = request.args.get(param)
        if v is not None:
            items = [x for x in items if str(x.get(field)) == v]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([ser(x) for x in page], response_type="array", pagination=meta)


def _get(store, ser, kind, rec_id):
    require_roles()
    rec = store.get(rec_id)
    if rec is None:
        raise ApiError(ERRORS[kind], 404, f"{kind} not found")
    return ok(ser(rec))


def _ser_phase_clean(p):
    out = domain.ser_phase(p)
    out.pop("_window_start", None)
    out.pop("_window_end", None)
    return out


def _ser_dispute_clean(d):
    out = domain.ser_dispute(d)
    out.pop("_pre_state", None)
    out.pop("_pre_attester", None)
    return out


@bp.route("/baselines", methods=["GET"])
def list_baselines():
    return _list(db.baselines, domain.ser_baseline, (("contract_id", "contract_id"),))


@bp.route("/baselines/<baselineId>", methods=["GET"])
def get_baseline(baselineId):
    return _get(db.baselines, domain.ser_baseline, "baseline", baselineId)


@bp.route("/bundles", methods=["GET"])
def list_bundles():
    return _list(db.bundles, domain.ser_bundle, (("contract_id", "contract_id"),))


@bp.route("/bundles/<bundleId>", methods=["GET"])
def get_bundle(bundleId):
    return _get(db.bundles, domain.ser_bundle, "bundle", bundleId)


@bp.route("/measures", methods=["GET"])
def list_measures():
    return _list(db.measures, domain.ser_measure,
                 (("bundle_id", "bundle_id"), ("contract_id", "contract_id")))


@bp.route("/measures/<measureId>", methods=["GET"])
def get_measure(measureId):
    return _get(db.measures, domain.ser_measure, "measure", measureId)


@bp.route("/financing-facilities", methods=["GET"])
def list_facilities():
    return _list(db.facilities, domain.ser_facility, (("contract_id", "contract_id"),))


@bp.route("/financing-facilities/<facilityId>", methods=["GET"])
def get_facility(facilityId):
    return _get(db.facilities, domain.ser_facility, "facility", facilityId)


@bp.route("/financing-draws", methods=["GET"])
def list_draws():
    return _list(db.draws, domain.ser_draw, (("facility_id", "facility_id"),))


@bp.route("/financing-draws/<drawId>", methods=["GET"])
def get_draw(drawId):
    return _get(db.draws, domain.ser_draw, "draw", drawId)


@bp.route("/phases", methods=["GET"])
def list_phases():
    return _list(db.phases, _ser_phase_clean, (("contract_id", "contract_id"),))


@bp.route("/phases/<phaseId>", methods=["GET"])
def get_phase(phaseId):
    return _get(db.phases, _ser_phase_clean, "phase", phaseId)


@bp.route("/disruptions", methods=["GET"])
def list_disruptions():
    return _list(db.disruptions, domain.ser_disruption, (("phase_id", "phase_id"),))


@bp.route("/disruptions/<disruptionId>", methods=["GET"])
def get_disruption(disruptionId):
    return _get(db.disruptions, domain.ser_disruption, "disruption", disruptionId)


@bp.route("/reports", methods=["GET"])
def list_reports():
    return _list(db.reports, domain.ser_report,
                 (("contract_id", "contract_id"),
                  ("attested_by_owner_rep_id", "attested_by_owner_rep_id")))


@bp.route("/reports/<reportId>", methods=["GET"])
def get_report(reportId):
    return _get(db.reports, domain.ser_report, "report", reportId)


@bp.route("/baseline-adjustments", methods=["GET"])
def list_adjustments():
    return _list(db.adjustments, domain.ser_adjustment,
                 (("contract_id", "contract_id"), ("baseline_id", "baseline_id"),
                  ("supersedes_adjustment_id", "supersedes_adjustment_id")))


@bp.route("/baseline-adjustments/<adjustmentId>", methods=["GET"])
def get_adjustment(adjustmentId):
    return _get(db.adjustments, domain.ser_adjustment, "adjustment", adjustmentId)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    return _list(db.disputes, _ser_dispute_clean,
                 (("contract_id", "contract_id"), ("report_id", "report_id")))


@bp.route("/disputes/<disputeId>", methods=["GET"])
def get_dispute(disputeId):
    return _get(db.disputes, _ser_dispute_clean, "dispute", disputeId)


@bp.route("/owner-reps/<ownerRepId>/attested-reports", methods=["GET"])
def attested_reports(ownerRepId):
    require_roles()
    if ownerRepId not in db.owner_reps:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", 404, "owner rep not found")
    limit, offset = paginate_args()
    items = [r for r in db.reports.values()
             if r.get("attested_by_owner_rep_id") == ownerRepId]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_report(r) for r in page], response_type="array", pagination=meta)
