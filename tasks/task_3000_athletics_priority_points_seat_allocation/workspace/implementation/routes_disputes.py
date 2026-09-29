"""Point disputes: filing, review, information rounds and the decision (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import enums
import num
import serial
import validation as v
from errors import err, invalid_state
from store import DB, by_created_at, get_body_ref, get_path, new_row, touch

bp = Blueprint("disputes", __name__)


@bp.get("/athletics/point-disputes")
def list_disputes():
    auth.require(auth.DISPUTE_READERS)
    donor_id = v.q_str("donor_id")
    recalculation_id = v.q_str("recalculation_id")
    status = v.q_enum("status", enums.DISPUTE_STATUSES)
    rows = list(DB.disputes.values())
    if donor_id is not None:
        rows = [r for r in rows if r["donor_id"] == donor_id]
    if recalculation_id is not None:
        rows = [r for r in rows if r["recalculation_id"] == recalculation_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.paginated(by_created_at(rows), serial.dispute)


@bp.get("/athletics/point-disputes/<dispute_id>")
def get_dispute(dispute_id):
    auth.require(auth.DISPUTE_READERS)
    return envelope.ok(serial.dispute(get_path("dispute", dispute_id)))


@bp.post("/athletics/point-disputes")
def create_dispute():
    caller = auth.require(auth.DONOR_AND_OFFICER)
    body = v.body_dict()
    claimed_owner = body.get("donor_id") if isinstance(body, dict) else None
    if caller.is_donor and isinstance(claimed_owner, str) and claimed_owner != caller.user_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "a donor may only file a dispute against their own record")
    donor_id = v.id_field(body, "donor_id")
    recalculation_id = v.id_field(body, "recalculation_id")
    claimed_delta = v.num_field(body, "claimed_points_delta", exclusive_minimum=0)
    basis_note = v.str_field(body, "basis_note", min_len=1, max_len=500)
    donor = get_body_ref("donor", donor_id)
    recalc = get_body_ref("recalculation", recalculation_id)
    if clock.now() >= recalc["dispute_window_end"]:
        raise err("ERR_DISPUTE_WINDOW_CLOSED",
                  "the dispute window for this recalculation has closed")
    row = new_row(
        donor_id=donor["id"],
        recalculation_id=recalc["id"],
        claimed_points_delta=claimed_delta,
        basis_note=basis_note,
        status="SUBMITTED",
        info_request_rounds=0,
        reviewed_by_user_id=None,
        decided_by_user_id=None,
        granted_points_delta=None,
        decided_at=None,
        info_note=None,
    )
    DB.disputes[row["id"]] = row
    return envelope.created(serial.dispute(row))


@bp.post("/athletics/point-disputes/<dispute_id>/review")
def review_dispute(dispute_id):
    caller = auth.require(auth.ANALYST_ONLY)
    dispute = get_path("dispute", dispute_id)
    v.body_dict()
    if dispute["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED dispute may be taken under review")
    recalc = DB.recalculations.get(dispute["recalculation_id"])
    if recalc is None or recalc["status"] != "COMMUNICATED":
        raise invalid_state(
            "the parent recalculation must be in COMMUNICATED to review a dispute")
    dispute["status"] = "UNDER_REVIEW"
    if dispute["reviewed_by_user_id"] is None:
        dispute["reviewed_by_user_id"] = caller.user_id
    touch(dispute)
    return envelope.ok(serial.dispute(dispute))


@bp.post("/athletics/point-disputes/<dispute_id>/request-info")
def request_dispute_info(dispute_id):
    auth.require(auth.ANALYST_ONLY)
    dispute = get_path("dispute", dispute_id)
    body = v.body_dict()
    info_note = v.str_field(body, "info_note", min_len=1, max_len=None)
    if dispute["status"] != "UNDER_REVIEW":
        raise invalid_state(
            "information may only be requested on a dispute in UNDER_REVIEW")
    if int(dispute["info_request_rounds"]) >= calc.INFO_REQUEST_ROUND_CAP:
        raise err("ERR_INFO_REQUEST_LIMIT_REACHED",
                  "this dispute has already completed %d information rounds"
                  % calc.INFO_REQUEST_ROUND_CAP)
    dispute["status"] = "INFO_REQUESTED"
    dispute["info_note"] = info_note
    touch(dispute)
    return envelope.ok(serial.dispute(dispute))


@bp.post("/athletics/point-disputes/<dispute_id>/provide-info")
def provide_dispute_info(dispute_id):
    caller = auth.require(auth.DONOR_ONLY)
    dispute = get_path("dispute", dispute_id)
    auth.require_owner(caller, dispute["donor_id"])
    body = v.body_dict()
    v.str_field(body, "response_note", min_len=1, max_len=None)
    if dispute["status"] != "INFO_REQUESTED":
        raise invalid_state(
            "only a dispute in INFO_REQUESTED may receive the donor's response")
    dispute["status"] = "UNDER_REVIEW"
    dispute["info_request_rounds"] = int(dispute["info_request_rounds"]) + 1
    touch(dispute)
    return envelope.ok(serial.dispute(dispute))


@bp.post("/athletics/point-disputes/<dispute_id>/decide")
def decide_dispute(dispute_id):
    caller = auth.require(auth.COMMITTEE_ONLY)
    dispute = get_path("dispute", dispute_id)
    auth.require_segregation(caller, dispute["reviewed_by_user_id"],
                             "analyst who took this dispute under review")
    body = v.body_dict()
    decision = v.enum_field(body, "decision", enums.DISPUTE_DECISIONS)
    granted = v.num_field(body, "granted_points_delta", required=False, minimum=0,
                          default=None)
    if dispute["status"] != "UNDER_REVIEW":
        raise invalid_state("only a dispute in UNDER_REVIEW may be decided")
    recalc = DB.recalculations.get(dispute["recalculation_id"])
    if recalc is not None and clock.now() >= recalc["dispute_window_end"]:
        raise err("ERR_DISPUTE_WINDOW_CLOSED",
                  "the dispute window for this recalculation has closed")
    dispute["decided_by_user_id"] = caller.user_id
    dispute["decided_at"] = clock.now()
    if decision == "UPHOLD":
        delta = granted if granted is not None else Decimal("0.00")
        dispute["status"] = "UPHELD"
        dispute["granted_points_delta"] = num.round2(delta)
        donor = DB.donors.get(dispute["donor_id"])
        if donor is not None:
            donor["dispute_adjustment_points"] = num.round2(
                num.dec(donor["dispute_adjustment_points"]) + num.round2(delta))
            derive.recompute_certified_points(donor)
            touch(donor)
    else:
        dispute["status"] = "DENIED"
        dispute["granted_points_delta"] = Decimal("0.00")
    touch(dispute)
    return envelope.ok(serial.dispute(dispute))
