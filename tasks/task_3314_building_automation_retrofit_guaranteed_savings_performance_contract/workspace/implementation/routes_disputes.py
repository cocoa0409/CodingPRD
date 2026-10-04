"""DisputeNotice routes."""
from flask import Blueprint

import db
import domain
from errors import ApiError, ok
from util import (body, paginate_args, paginate_list, req_int, require_roles, touch)

bp = Blueprint("disputes", __name__)


def _ser(d):
    out = domain.ser_dispute(d)
    out.pop("_pre_state", None)
    out.pop("_pre_attester", None)
    return out


@bp.route("/performance-contracts/<contractId>/disputes", methods=["GET"])
def list_disputes(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    limit, offset = paginate_args()
    items = [d for d in db.disputes.values() if d["contract_id"] == c["id"]]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([_ser(d) for d in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/disputes/<disputeId>", methods=["GET"])
def get_dispute(contractId, disputeId):
    require_roles()
    _, d = domain.get_dispute(contractId, disputeId)
    return ok(_ser(d))


@bp.route("/performance-contracts/<contractId>/disputes/<disputeId>/escalate", methods=["POST"])
def escalate_dispute(contractId, disputeId):
    require_roles("OwnerRep")
    _, d = domain.get_dispute(contractId, disputeId)
    if d["status"] != "OPEN":
        raise ApiError("ERR_DISPUTE_NOT_OPEN", 409, "dispute must be in OPEN")
    d["status"] = "ESCALATED"
    touch(d)
    return ok(_ser(d))


@bp.route("/performance-contracts/<contractId>/disputes/<disputeId>/resolve", methods=["POST"])
def resolve_dispute(contractId, disputeId):
    require_roles("LenderOfficer")
    c, d = domain.get_dispute(contractId, disputeId)
    if d["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_DISPUTE_NOT_OPEN", 409, "dispute must be in OPEN or ESCALATED")
    data = body()
    resolution = req_int(data, "resolution_savings_cents", min_v=0)
    d["resolution_savings_cents"] = resolution
    d["status"] = "RESOLVED"
    touch(d)
    report = db.reports.get(d["report_id"])
    if report is not None and report["status"] == "DISPUTED":
        report["verified_savings_cents"] = resolution
        report["shortfall_cents"] = max(
            0, c["guaranteed_annual_savings_cents"] - resolution)
        # PRD §3.7: the report returns to ATTESTED with the resolution figure.
        # The recorded attester is the report's pre-dispute attester, if any.
        report["status"] = "ATTESTED"
        if d.get("_pre_attester") is not None:
            report["attested_by_owner_rep_id"] = d["_pre_attester"]
        touch(report)
    return ok(_ser(d))


@bp.route("/performance-contracts/<contractId>/disputes/<disputeId>/withdraw", methods=["POST"])
def withdraw_dispute(contractId, disputeId):
    uid, role = require_roles("OwnerRep", "ESCOEngineer")
    _, d = domain.get_dispute(contractId, disputeId)
    expected_role = "OwnerRep" if d["filed_by_role"] == "OWNER" else "ESCOEngineer"
    if role != expected_role:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "only the filer's side may withdraw the dispute")
    if d["status"] != "OPEN":
        raise ApiError("ERR_DISPUTE_NOT_OPEN", 409, "dispute must be in OPEN")
    d["status"] = "WITHDRAWN"
    touch(d)
    report = db.reports.get(d["report_id"])
    if report is not None and report["status"] == "DISPUTED":
        # PRD §3.7: the report returns to the state it held before the dispute.
        report["status"] = d.get("_pre_state", "SUBMITTED")
        if d.get("_pre_attester") is not None:
            report["attested_by_owner_rep_id"] = d["_pre_attester"]
        touch(report)
    return ok(_ser(d))
