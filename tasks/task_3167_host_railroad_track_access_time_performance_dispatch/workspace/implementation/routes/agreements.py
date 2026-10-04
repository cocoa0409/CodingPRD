"""OperatingAgreement endpoints and lifecycle."""
from flask import Blueprint, g

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_int,
    f_num,
    f_str,
    forbid_unless_owner_host,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)
import svc

bp = Blueprint("agreements", __name__, url_prefix="/rail/operating-agreements")


@bp.post("")
@endpoint("PassengerOperator")
def create_agreement():
    payload = body()
    host_railroad_id = f_str(payload, "host_railroad_id")
    corridor_id = f_str(payload, "corridor_id")
    effective_from = f_dt(payload, "effective_from")
    effective_to = f_dt(payload, "effective_to")
    on_time_threshold_minutes = f_int(payload, "on_time_threshold_minutes", minimum=0)
    penalty_rate_cents_per_minute = f_int(payload, "penalty_rate_cents_per_minute", minimum=0)
    incentive_rate_cents_per_train_mile = f_int(
        payload, "incentive_rate_cents_per_train_mile", minimum=0
    )
    otp_target_pct = f_num(payload, "otp_target_pct")
    running_time_allowance_pct = f_num(payload, "running_time_allowance_pct")
    svc.need_host(host_railroad_id)
    svc.need_corridor(corridor_id)
    row = new_row(
        "operating_agreement",
        host_railroad_id=host_railroad_id,
        corridor_id=corridor_id,
        effective_from=effective_from,
        effective_to=effective_to,
        on_time_threshold_minutes=on_time_threshold_minutes,
        penalty_rate_cents_per_minute=penalty_rate_cents_per_minute,
        incentive_rate_cents_per_train_mile=incentive_rate_cents_per_train_mile,
        otp_target_pct=float(otp_target_pct),
        running_time_allowance_pct=float(running_time_allowance_pct),
        status="DRAFT",
        amendment_seq=0,
    )
    db.operating_agreements[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.get("")
@endpoint()
def list_agreements():
    rows = list(db.operating_agreements.values())
    host_railroad_id = q_str("host_railroad_id")
    corridor_id = q_str("corridor_id")
    status = q_enum("status", svc.AGREEMENT_STATUSES)
    if host_railroad_id is not None:
        rows = [r for r in rows if r["host_railroad_id"] == host_railroad_id]
    if corridor_id is not None:
        rows = [r for r in rows if r["corridor_id"] == corridor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.get("/<rid>")
@endpoint()
def get_agreement(rid):
    row = svc.need_agreement(rid)
    return respond_object(dump(row))


@bp.post("/<rid>/activate")
@endpoint("HostRailroadRep")
def activate_agreement(rid):
    row = svc.need_agreement(rid)
    forbid_unless_owner_host(row["host_railroad_id"])
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not DRAFT.")
    row["status"] = "ACTIVE"
    touch(row)
    return respond_object(dump(row))


@bp.post("/<rid>/amend")
@endpoint("PassengerOperator")
def amend_agreement(rid):
    payload = body()
    expected = f_int(payload, "expected_operating_agreement_version")
    penalty = f_int(payload, "penalty_rate_cents_per_minute", required=False, minimum=0)
    incentive = f_int(
        payload, "incentive_rate_cents_per_train_mile", required=False, minimum=0
    )
    otp_target = f_num(payload, "otp_target_pct", required=False)
    allowance = f_num(payload, "running_time_allowance_pct", required=False)

    row = svc.need_agreement(rid)
    # OCC check (priority 5, before state)
    if expected != row["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_operating_agreement_version does not match current version.",
        )
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not ACTIVE.")
    if penalty is not None:
        row["penalty_rate_cents_per_minute"] = penalty
    if incentive is not None:
        row["incentive_rate_cents_per_train_mile"] = incentive
    if otp_target is not None:
        row["otp_target_pct"] = float(otp_target)
    if allowance is not None:
        row["running_time_allowance_pct"] = float(allowance)
    row["amendment_seq"] += 1
    touch(row)
    # Cascade: in-flight timetables back to DRAFT
    for tt in db.timetables.values():
        if tt["operating_agreement_id"] == row["id"] and tt["status"] in (
            "PROPOSED",
            "UNDER_REVIEW",
        ):
            tt["status"] = "DRAFT"
            touch(tt)
    return respond_object(dump(row))


@bp.post("/<rid>/suspend")
@endpoint("HostRailroadRep")
def suspend_agreement(rid):
    row = svc.need_agreement(rid)
    forbid_unless_owner_host(row["host_railroad_id"])
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Agreement is not ACTIVE.")
    row["status"] = "SUSPENDED"
    touch(row)
    # Cascade link 1: PUBLISHED timetables -> SUSPENDED
    suspended_tt_ids = set()
    for tt in db.timetables.values():
        if tt["operating_agreement_id"] == row["id"] and tt["status"] == "PUBLISHED":
            tt["status"] = "SUSPENDED"
            touch(tt)
            suspended_tt_ids.add(tt["id"])
    # Cascade link 2: their SCHEDULED TrainRuns -> CANCELLED (AGREEMENT_SUSPENDED)
    for run in db.train_runs.values():
        if run["timetable_id"] in suspended_tt_ids and run["status"] == "SCHEDULED":
            run["status"] = "CANCELLED"
            run["cancellation_reason"] = "AGREEMENT_SUSPENDED"
            touch(run)
    return respond_object(dump(row))
