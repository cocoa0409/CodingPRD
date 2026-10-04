"""SettlementStatement endpoints."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_date,
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

bp = Blueprint("settlements", __name__, url_prefix="/rail/settlement-statements")


def _serialize(row):
    out = dict(row)
    out["period_start"] = out["period_start"].isoformat()
    out["period_end"] = out["period_end"].isoformat()
    return out


@bp.post("")
@endpoint("PassengerOperator")
def create_statement():
    payload = body()
    operating_agreement_id = f_str(payload, "operating_agreement_id")
    period_start = f_date(payload, "period_start")
    period_end = f_date(payload, "period_end")
    if period_end < period_start:
        raise ApiError("ERR_VALIDATION", "period_end must be on or after period_start.")
    agreement = svc.need_agreement(operating_agreement_id)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "Operating agreement is not ACTIVE.")
    # Period must lie within effective range and not overlap existing ISSUED/PAID
    if period_start < agreement["effective_from"].date() or period_end > agreement[
        "effective_to"
    ].date():
        raise ApiError(
            "ERR_SETTLEMENT_PERIOD_INVALID",
            "Statement period lies outside the agreement's effective range.",
        )
    for other in db.settlement_statements.values():
        if other["operating_agreement_id"] != operating_agreement_id:
            continue
        if other["status"] not in ("ISSUED", "PAID"):
            continue
        if not (
            other["period_end"] < period_start or other["period_start"] > period_end
        ):
            raise ApiError(
                "ERR_SETTLEMENT_PERIOD_INVALID",
                "Statement period overlaps an existing ISSUED/PAID statement.",
            )
    corridor = svc.need_corridor(agreement["corridor_id"])
    row = new_row(
        "settlement_statement",
        operating_agreement_id=operating_agreement_id,
        period_start=period_start,
        period_end=period_end,
        computation_variant="GROSS",
        completed_run_count=0,
        train_miles=0,
        otp_pct=None,
        host_delay_minutes=0,
        penalty_cents=0,
        incentive_cents=0,
        net_cents=0,
        status="DRAFT",
    )
    db.settlement_statements[row["id"]] = row
    fields = svc.compute_statement_fields(row, agreement, corridor, "GROSS")
    row.update(fields)
    return respond_object(dump(_serialize(row)), status=201)


@bp.get("")
@endpoint()
def list_statements():
    rows = list(db.settlement_statements.values())
    operating_agreement_id = q_str("operating_agreement_id")
    status = q_enum("status", svc.STATEMENT_STATUSES)
    if operating_agreement_id is not None:
        rows = [r for r in rows if r["operating_agreement_id"] == operating_agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows), dumper=lambda r: dump(_serialize(r)))


@bp.get("/<rid>")
@endpoint()
def get_statement(rid):
    row = svc.need_statement(rid)
    return respond_object(dump(_serialize(row)))


@bp.post("/<rid>/issue")
@endpoint("PassengerOperator")
def issue_statement(rid):
    row = svc.need_statement(rid)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Statement is not DRAFT.")
    row["status"] = "ISSUED"
    touch(row)
    return respond_object(dump(_serialize(row)))


@bp.post("/<rid>/dispute")
@endpoint("HostRailroadRep")
def dispute_statement(rid):
    body()  # optional reason
    row = svc.need_statement(rid)
    forbid_unless_owner_host(svc.host_for_statement(row))
    if row["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Statement is not ISSUED.")
    row["status"] = "DISPUTED"
    touch(row)
    return respond_object(dump(_serialize(row)))


@bp.post("/<rid>/reissue")
@endpoint("PassengerOperator")
def reissue_statement(rid):
    row = svc.need_statement(rid)
    if row["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", "Statement is not DISPUTED.")
    agreement = svc.need_agreement(row["operating_agreement_id"])
    corridor = svc.need_corridor(agreement["corridor_id"])
    row["computation_variant"] = "NET"
    fields = svc.compute_statement_fields(row, agreement, corridor, "NET")
    row.update(fields)
    row["status"] = "REISSUED"
    touch(row)
    return respond_object(dump(_serialize(row)))


@bp.post("/<rid>/pay")
@endpoint("HostRailroadRep")
def pay_statement(rid):
    row = svc.need_statement(rid)
    forbid_unless_owner_host(svc.host_for_statement(row))
    if row["status"] not in ("ISSUED", "REISSUED"):
        raise ApiError("ERR_INVALID_STATE", "Statement is not ISSUED or REISSUED.")
    row["status"] = "PAID"
    touch(row)
    return respond_object(dump(_serialize(row)))
