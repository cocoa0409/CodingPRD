"""Return-rate snapshots: return_rate_computation plus the automatic
InquiryCase opening for breached classes (PRD section 3.7)."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, request

from auth import ROLES, require_roles
from clock import CLOCK, is_valid_period, period_of_date, period_of_datetime, render_ts3
from envelope import ok
from errors import fail
from store import DB, add_record
from validation import get_body, list_response, require_str

bp = Blueprint("returns_rates", __name__)

# return_rate_computation constants
UNAUTH_THRESHOLD_PCT = 10
ADMIN_THRESHOLD_PCT = 20
OVERALL_THRESHOLD_PCT = 25
INQUIRY_RESPONSE_DAYS = 14


def _rate(numerator, denominator):
    """4 decimal places, round half-up; 0.0 when the denominator is zero."""
    if denominator == 0:
        return 0.0
    return float(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    )


def serialize_snapshot(s):
    return {
        "id": s["id"],
        "participant_id": s["participant_id"],
        "period": s["period"],
        "forward_count": s["forward_count"],
        "origination_forward_count": s["origination_forward_count"],
        "unauth_return_count": s["unauth_return_count"],
        "admin_return_count": s["admin_return_count"],
        "other_return_count": s["other_return_count"],
        "origination_unauth_count": s["origination_unauth_count"],
        "origination_admin_count": s["origination_admin_count"],
        "settlement_unauth_rate": s["settlement_unauth_rate"],
        "settlement_admin_rate": s["settlement_admin_rate"],
        "settlement_overall_rate": s["settlement_overall_rate"],
        "origination_unauth_rate": s["origination_unauth_rate"],
        "origination_admin_rate": s["origination_admin_rate"],
        "unauth_breach": s["unauth_breach"],
        "admin_breach": s["admin_breach"],
        "overall_breach": s["overall_breach"],
        "status": s["status"],
        "created_at": render_ts3(s["created_at"]),
        "updated_at": render_ts3(s["updated_at"]),
        "version": s["version"],
    }


@bp.post("/return-rate-snapshots")
@require_roles("PlatformAdmin")
def create_return_rate_snapshot():
    body = get_body()
    participant_id = require_str(body, "participant_id")
    period = require_str(body, "period")
    if not is_valid_period(period):
        fail("ERR_INVALID_REQUEST", "period must be in YYYY-MM form")
    if participant_id not in DB.participants:
        fail("ERR_NOT_FOUND", "Participant %s not found" % participant_id)
    for s in DB.return_rate_snapshots.values():
        if s["participant_id"] == participant_id and s["period"] == period:
            fail(
                "ERR_DUPLICATE_RESOURCE",
                "A snapshot already exists for this participant and period",
            )

    entries = [
        e
        for e in DB.payment_entries.values()
        if e["originating_participant_id"] == participant_id
    ]
    # Settlement-basis denominator: entries settled in the period.
    forward_count = sum(
        1
        for e in entries
        if e["settled_date"] is not None and period_of_date(e["settled_date"]) == period
    )
    # Origination-basis denominator: entries created in the period.
    origination_forward_count = sum(
        1 for e in entries if period_of_datetime(e["created_at"]) == period
    )

    period_returns = [
        r
        for r in DB.return_records.values()
        if DB.payment_entries[r["payment_entry_id"]]["originating_participant_id"]
        == participant_id
        and period_of_datetime(r["returned_at"]) == period
    ]
    unauth_return_count = sum(
        1 for r in period_returns if r["reason_class"] == "UNAUTHORIZED"
    )
    admin_return_count = sum(
        1 for r in period_returns if r["reason_class"] == "ADMINISTRATIVE"
    )
    other_return_count = sum(1 for r in period_returns if r["reason_class"] == "OTHER")
    origination_unauth_count = sum(
        1
        for r in period_returns
        if r["reason_class"] == "UNAUTHORIZED"
        and period_of_datetime(DB.payment_entries[r["payment_entry_id"]]["created_at"])
        == period
    )
    origination_admin_count = sum(
        1
        for r in period_returns
        if r["reason_class"] == "ADMINISTRATIVE"
        and period_of_datetime(DB.payment_entries[r["payment_entry_id"]]["created_at"])
        == period
    )

    settlement_unauth_rate = _rate(unauth_return_count, forward_count)
    settlement_admin_rate = _rate(admin_return_count, forward_count)
    settlement_overall_rate = _rate(
        unauth_return_count + admin_return_count + other_return_count, forward_count
    )
    origination_unauth_rate = _rate(origination_unauth_count, origination_forward_count)
    origination_admin_rate = _rate(origination_admin_count, origination_forward_count)

    # Breach flags: exact integer cross-multiplication, strictly greater than.
    unauth_breach = (
        forward_count > 0
        and unauth_return_count * 100 > forward_count * UNAUTH_THRESHOLD_PCT
    )
    admin_breach = (
        forward_count > 0
        and admin_return_count * 100 > forward_count * ADMIN_THRESHOLD_PCT
    )
    overall_breach = (
        forward_count > 0
        and (unauth_return_count + admin_return_count + other_return_count) * 100
        > forward_count * OVERALL_THRESHOLD_PCT
    )

    rec = add_record(
        "return_rate_snapshots",
        {
            "participant_id": participant_id,
            "period": period,
            "forward_count": forward_count,
            "origination_forward_count": origination_forward_count,
            "unauth_return_count": unauth_return_count,
            "admin_return_count": admin_return_count,
            "other_return_count": other_return_count,
            "origination_unauth_count": origination_unauth_count,
            "origination_admin_count": origination_admin_count,
            "settlement_unauth_rate": settlement_unauth_rate,
            "settlement_admin_rate": settlement_admin_rate,
            "settlement_overall_rate": settlement_overall_rate,
            "origination_unauth_rate": origination_unauth_rate,
            "origination_admin_rate": origination_admin_rate,
            "unauth_breach": unauth_breach,
            "admin_breach": admin_breach,
            "overall_breach": overall_breach,
            "status": "COMPUTED",
        },
    )

    # Supervisory follow-up: one OPEN inquiry per breached class unless an
    # OPENED / RESPONSE_SUBMITTED inquiry already exists for the same
    # (participant, period, class).
    breached_classes = []
    if unauth_breach:
        breached_classes.append("UNAUTHORIZED")
    if admin_breach:
        breached_classes.append("ADMINISTRATIVE")
    if overall_breach:
        breached_classes.append("OVERALL")
    for return_class in breached_classes:
        already_open = False
        for inquiry in DB.inquiry_cases.values():
            if (
                inquiry["participant_id"] != participant_id
                or inquiry["return_class"] != return_class
                or inquiry["status"] not in ("OPENED", "RESPONSE_SUBMITTED")
            ):
                continue
            source = DB.return_rate_snapshots.get(inquiry["return_rate_snapshot_id"])
            if source is not None and source["period"] == period:
                already_open = True
                break
        if not already_open:
            add_record(
                "inquiry_cases",
                {
                    "participant_id": participant_id,
                    "return_rate_snapshot_id": rec["id"],
                    "return_class": return_class,
                    "response_deadline": CLOCK.now()
                    + timedelta(days=INQUIRY_RESPONSE_DAYS),
                    "response_text": None,
                    "status": "OPENED",
                },
            )

    return ok(serialize_snapshot(rec), 201)


@bp.get("/return-rate-snapshots/<snapshot_id>")
@require_roles(*ROLES)
def get_return_rate_snapshot(snapshot_id):
    s = DB.return_rate_snapshots.get(snapshot_id)
    if s is None:
        fail("ERR_NOT_FOUND", "Return rate snapshot %s not found" % snapshot_id)
    return ok(serialize_snapshot(s))


@bp.get("/return-rate-snapshots")
@require_roles(*ROLES)
def list_return_rate_snapshots():
    filters = []
    participant_id = request.args.get("participant_id")
    if participant_id is not None:
        filters.append(("participant_id", participant_id))
    period = request.args.get("period")
    if period is not None:
        filters.append(("period", period))
    return list_response(DB.return_rate_snapshots.values(), serialize_snapshot, filters)
