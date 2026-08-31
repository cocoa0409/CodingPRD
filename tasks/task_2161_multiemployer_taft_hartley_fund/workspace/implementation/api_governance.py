"""Joint board governance, motions, votes and reciprocity with sister funds."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import serialize
import validate as v
from authz import endpoint
from envelope import created, ok
from errors import ApiError
from store import db, new_row, touch

bp = Blueprint("governance", __name__)

SUBJECT_TYPES = ("LD_WAIVER", "AUDIT_SETTLEMENT", "RECIPROCITY_AGREEMENT")


def acting_trustee():
    trustee = db.trustees.get(g.user_id)
    if trustee is None:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return trustee


def subject_row(subject_type, subject_ref_id):
    if subject_type == "LD_WAIVER":
        return db.assessments.get(subject_ref_id)
    if subject_type == "AUDIT_SETTLEMENT":
        return db.audits.get(subject_ref_id)
    fund = db.funds.get(subject_ref_id)
    if fund is not None and fund["fund_role"] == "SISTER":
        return fund
    return None


@bp.post("/board-motions")
@endpoint(["Trustee"])
def move_motion():
    data = v.body()
    v.body_ref(data, "fund_id", db.funds, "ERR_FUND_NOT_FOUND")
    v.check_keys(data, ["fund_id", "subject_type", "subject_ref_id"])
    fund_id = v.as_string(data, "fund_id")
    subject_type = v.as_enum(data, "subject_type", SUBJECT_TYPES)
    subject_ref_id = v.as_string(data, "subject_ref_id")

    trustee = acting_trustee()
    fund = db.funds[fund_id]
    calc.recompute_governance(fund)

    if trustee["seat_status"] != "ACTIVE":
        raise ApiError("ERR_TRUSTEE_SEAT_INACTIVE")
    if fund["governance_posture"] != "OPEN":
        raise ApiError("ERR_FUND_GOVERNANCE_NOT_OPEN")
    if subject_row(subject_type, subject_ref_id) is None:
        raise ApiError("ERR_MOTION_SUBJECT_INVALID")

    motion = new_row(
        db.motions,
        {
            "fund_id": fund_id,
            "moved_by_trustee_id": trustee["id"],
            "subject_type": subject_type,
            "subject_ref_id": subject_ref_id,
            "union_bloc_position": None,
            "employer_bloc_position": None,
            "tallied_on": None,
            "arbitration_award": None,
            "status": "OPEN",
        },
    )
    return created(serialize.motion(motion))


@bp.post("/motion-votes")
@endpoint(["Trustee"])
def cast_vote():
    data = v.body()
    v.body_ref(data, "motion_id", db.motions, "ERR_MOTION_NOT_FOUND")
    v.check_keys(data, ["motion_id", "position"])
    motion_id = v.as_string(data, "motion_id")
    position = v.as_enum(data, "position", ("FOR", "AGAINST", "ABSTAIN"))

    trustee = acting_trustee()
    motion = db.motions[motion_id]

    if motion["status"] != "OPEN":
        raise ApiError("ERR_MOTION_INVALID_STATE")
    if motion["moved_by_trustee_id"] == trustee["id"]:
        raise ApiError("ERR_MOVER_CANNOT_VOTE")
    if trustee["seat_status"] != "ACTIVE":
        raise ApiError("ERR_TRUSTEE_SEAT_INACTIVE")
    if trustee["fund_id"] != motion["fund_id"]:
        raise ApiError("ERR_TRUSTEE_FUND_MISMATCH")
    for existing in db.votes.values():
        if existing["motion_id"] == motion_id and existing["trustee_id"] == trustee["id"]:
            raise ApiError("ERR_DUPLICATE_VOTE")

    vote = new_row(
        db.votes,
        {"motion_id": motion_id, "trustee_id": trustee["id"], "position": position},
        common=False,
    )
    return created(serialize.vote(vote))


def _fire_subject_cascade(motion):
    if motion["subject_type"] == "LD_WAIVER":
        assessment = db.assessments.get(motion["subject_ref_id"])
        if assessment is None:
            return
        assessment["waived_cents"] = assessment["total_cents"]
        assessment["status"] = "WAIVED"
        touch(assessment)
        report = db.reports.get(assessment["report_id"])
        if report is not None:
            calc.ledger_cascade(db.employers[report["employer_id"]])
    elif motion["subject_type"] == "RECIPROCITY_AGREEMENT":
        sister = db.funds.get(motion["subject_ref_id"])
        if sister is not None and sister["reciprocity_agreement_status"] != "EXECUTED":
            sister["reciprocity_agreement_status"] = "EXECUTED"
            touch(sister)


@bp.post("/board-motions/<motion_id>/tally")
@endpoint(["FundAdministrator"])
def tally(motion_id):
    motion = v.get_motion(motion_id)
    data = v.body()
    v.check_keys(data, ["arbitration_award"])
    award = v.as_enum(data, "arbitration_award", ("CARRIED", "FAILED"), required=False, default=None)

    if motion["status"] == "OPEN":
        union_counted, union_pos = calc.bloc_position(motion["id"], "UNION")
        employer_counted, employer_pos = calc.bloc_position(motion["id"], "EMPLOYER")
        if union_counted < calc.QUORUM_PER_PARTY or employer_counted < calc.QUORUM_PER_PARTY:
            raise ApiError("ERR_QUORUM_NOT_MET")
        motion["union_bloc_position"] = union_pos
        motion["employer_bloc_position"] = employer_pos
        motion["tallied_on"] = db.today.isoformat()
        if union_pos == "FOR" and employer_pos == "FOR":
            motion["status"] = "CARRIED"
        elif union_pos == "AGAINST" and employer_pos == "AGAINST":
            motion["status"] = "FAILED"
        else:
            motion["status"] = "DEADLOCKED"
        touch(motion)
        if motion["status"] == "CARRIED":
            _fire_subject_cascade(motion)
        return ok(serialize.motion(motion))

    if motion["status"] == "DEADLOCKED":
        if award is None:
            raise ApiError("ERR_MOTION_INVALID_STATE")
        motion["arbitration_award"] = award
        motion["tallied_on"] = db.today.isoformat()
        motion["status"] = "ARBITRATION_CARRIED" if award == "CARRIED" else "ARBITRATION_FAILED"
        touch(motion)
        if award == "CARRIED":
            _fire_subject_cascade(motion)
        return ok(serialize.motion(motion))

    raise ApiError("ERR_MOTION_INVALID_STATE")


TRANSFER_FIELDS = [
    "participant_id",
    "sister_fund_id",
    "transfer_type",
    "work_period",
    "hours",
    "amount_cents",
]


@bp.post("/reciprocity-transfers")
@endpoint(["FundAdministrator"])
def record_transfer():
    data = v.body()
    v.body_ref(data, "participant_id", db.participants, "ERR_PARTICIPANT_NOT_FOUND")
    v.body_ref(data, "sister_fund_id", db.funds, "ERR_FUND_NOT_FOUND")
    v.check_keys(data, TRANSFER_FIELDS)
    participant_id = v.as_string(data, "participant_id")
    sister_fund_id = v.as_string(data, "sister_fund_id")
    transfer_type = v.as_enum(data, "transfer_type", ("MONEY_FOLLOWS_MAN", "PRO_RATA"))
    work_period = v.as_month(data, "work_period")
    hours = v.as_hours(data, "hours")
    amount_cents = v.as_int(data, "amount_cents", minimum=0)

    participant = db.participants[participant_id]
    sister = db.funds[sister_fund_id]
    if sister["fund_role"] == "HOME" or sister["id"] == participant["fund_id"]:
        raise ApiError("ERR_SISTER_FUND_INVALID")

    transfer = new_row(
        db.transfers,
        {
            "participant_id": participant_id,
            "sister_fund_id": sister_fund_id,
            "transfer_type": transfer_type,
            "work_period": work_period,
            "hours": hours,
            "amount_cents": amount_cents,
            "applied_coverage_months": 0,
            "status": "PENDING",
        },
    )
    return created(serialize.transfer(transfer))


@bp.post("/reciprocity-transfers/<transfer_id>/decision")
@endpoint(["FundAdministrator"])
def decide_transfer(transfer_id):
    transfer = v.get_transfer(transfer_id)
    data = v.body()
    v.check_keys(data, ["decision"])
    decision = v.as_enum(data, "decision", ("ACCEPT", "REJECT"))

    if transfer["status"] != "PENDING":
        raise ApiError("ERR_TRANSFER_INVALID_STATE")

    if decision == "REJECT":
        transfer["status"] = "REJECTED"
        touch(transfer)
        return ok(serialize.transfer(transfer))

    participant = db.participants[transfer["participant_id"]]
    fund = db.funds[participant["fund_id"]]
    sister = db.funds[transfer["sister_fund_id"]]

    if sister["reciprocity_agreement_status"] != "EXECUTED":
        raise ApiError("ERR_RECIPROCITY_AGREEMENT_NOT_EXECUTED")
    if participant["status"] != "ACTIVE":
        raise ApiError("ERR_TRANSFER_INVALID_STATE")

    hpcm = Decimal(fund["hours_per_coverage_month"])
    available = calc.dec(participant["hour_bank_hours"]) + calc.dec(transfer["hours"])
    wanted = int(available // hpcm) if hpcm > 0 else 0
    outstanding = calc.outstanding_advance_months(participant["id"])
    if wanted > fund["max_advance_coverage_months"] - outstanding:
        raise ApiError("ERR_COVERAGE_HORIZON_EXCEEDED")

    transfer["status"] = "ACCEPTED"
    granted = calc.eligibility_replay(participant)
    transfer["applied_coverage_months"] = granted.get(transfer["id"], 0)
    touch(transfer)
    calc.recompute_accruals(participant)
    touch(participant)
    calc.recompute_reciprocal_receipts(fund)
    touch(fund)
    return ok(serialize.transfer(transfer))
