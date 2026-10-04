"""FundingAgreement endpoints."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_date,
    f_str,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)
import svc

bp = Blueprint("funding", __name__, url_prefix="/rail/funding-agreements")


def _serialize(row):
    out = dict(row)
    out["period_start"] = out["period_start"].isoformat()
    out["period_end"] = out["period_end"].isoformat()
    return out


@bp.post("")
@endpoint("StateSponsor")
def create_funding():
    payload = body()
    corridor_id = f_str(payload, "corridor_id")
    state_code = f_str(payload, "state_code")
    period_start = f_date(payload, "period_start")
    period_end = f_date(payload, "period_end")
    corridor = svc.need_corridor(corridor_id)
    if period_end < period_start:
        raise ApiError("ERR_VALIDATION", "period_end must be on or after period_start.")
    # state_code must match at least one segment's state_code
    segments = svc.corridor_segments(corridor_id)
    if not any(s["state_code"] == state_code for s in segments):
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            "state_code does not match any segment on the corridor.",
        )
    row = new_row(
        "funding_agreement",
        corridor_id=corridor_id,
        state_code=state_code,
        period_start=period_start,
        period_end=period_end,
        allocated_cost_cents=None,
        status="DRAFT",
    )
    db.funding_agreements[row["id"]] = row
    return respond_object(dump(_serialize(row)), status=201)


@bp.get("")
@endpoint()
def list_funding():
    rows = list(db.funding_agreements.values())
    corridor_id = q_str("corridor_id")
    state_code = q_str("state_code")
    status = q_enum("status", svc.FUNDING_STATUSES)
    if corridor_id is not None:
        rows = [r for r in rows if r["corridor_id"] == corridor_id]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows), dumper=lambda r: dump(_serialize(r)))


@bp.get("/<rid>")
@endpoint()
def get_funding(rid):
    row = svc.need_funding(rid)
    return respond_object(dump(_serialize(row)))


@bp.post("/<rid>/commit")
@endpoint("StateSponsor")
def commit_funding(rid):
    row = svc.need_funding(rid)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Funding agreement is not DRAFT.")
    # Overlap check
    for other in db.funding_agreements.values():
        if other["id"] == row["id"]:
            continue
        if other["corridor_id"] != row["corridor_id"]:
            continue
        if other["state_code"] != row["state_code"]:
            continue
        if other["status"] != "COMMITTED":
            continue
        # overlap of [start, end] inclusive
        if not (
            other["period_end"] < row["period_start"]
            or other["period_start"] > row["period_end"]
        ):
            raise ApiError(
                "ERR_FUNDING_PERIOD_OVERLAP",
                "Another COMMITTED funding agreement overlaps this period.",
            )
    corridor = svc.need_corridor(row["corridor_id"])
    row["allocated_cost_cents"] = svc.funding_allocated_cost(
        corridor, row["state_code"], row["period_start"], row["period_end"]
    )
    row["status"] = "COMMITTED"
    touch(row)
    return respond_object(dump(_serialize(row)))


@bp.post("/<rid>/settle")
@endpoint("StateSponsor")
def settle_funding(rid):
    row = svc.need_funding(rid)
    if row["status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_STATE", "Funding agreement is not COMMITTED.")
    row["status"] = "SETTLED"
    touch(row)
    return respond_object(dump(_serialize(row)))
