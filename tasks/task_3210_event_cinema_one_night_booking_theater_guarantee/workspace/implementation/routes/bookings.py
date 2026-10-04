"""Booking CRUD, booking lines, presale sales and the negotiation verbs."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from core import (
    BOOKING_STATUS,
    EXHIBIT_STATE,
    ApiError,
    D,
    bad_request,
    body,
    db,
    dump,
    endpoint,
    f_int,
    f_str,
    new_row,
    parse_dt,
    q_enum,
    q_str,
    respond_object,
    touch,
)
from booking_flow import (
    apply_makegood,
    approve,
    cancel,
    cancel_with_compensation,
    check_version,
    close,
    confirm,
    counter,
    presale_checkpoint,
    re_propose,
    recompute_ceiling,
    release_screens,
    reopen,
    resume,
    submit,
    suspend,
)
from store import (
    booking_lines,
    find,
    get_or_404,
    paginate,
    recompute_booking,
    recompute_line,
    recompute_title,
)

bp = Blueprint("bookings", __name__)


# ---------------------------------------------------------------------------
# Showtime-plan shape validation (PRD §3.1)
# ---------------------------------------------------------------------------
_PLAN_KEYS = ("index", "date_utc", "start_minute_utc", "auditorium")


def _validate_plan(payload, title, require_all=True):
    """Validate showtime_count / showtime_plan; returns the normalized plan."""
    showtime_count = payload.get("showtime_count")
    plan = payload.get("showtime_plan")
    if require_all and showtime_count is None:
        bad_request("Field 'showtime_count' is required.")
    if require_all and plan is None:
        bad_request("Field 'showtime_plan' is required.")
    if showtime_count is None and plan is None:
        return None, None

    if showtime_count is not None:
        if isinstance(showtime_count, bool) or not isinstance(showtime_count, int):
            raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
        if showtime_count not in (1, 2):
            raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
    if plan is not None:
        if not isinstance(plan, list):
            raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
        if showtime_count is not None and len(plan) != showtime_count:
            raise ApiError("ERR_SHOWTIME_PLAN_INVALID")

    normalized = None
    if plan is not None:
        normalized = []
        seen = set()
        for element in plan:
            if not isinstance(element, dict):
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
            if any(k not in element for k in _PLAN_KEYS):
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
            index = element["index"]
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
            if index in seen:
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
            seen.add(index)
            date = parse_dt(element["date_utc"])
            if date is None:
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
            start_minute = element["start_minute_utc"]
            if isinstance(start_minute, bool) or not isinstance(start_minute, int):
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
            if start_minute < 0 or start_minute >= 24 * 60:
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
            auditorium = element["auditorium"]
            if not isinstance(auditorium, str) or not auditorium.strip():
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")
            if title is not None:
                showtime = date + timedelta(minutes=start_minute)
                if showtime < title["rights_start_utc"] or showtime >= title["rights_end_utc"]:
                    raise ApiError("ERR_RIGHTS_WINDOW_VIOLATION")
            normalized.append(
                {
                    "index": index,
                    "date_utc": date,
                    "start_minute_utc": start_minute,
                    "auditorium": auditorium,
                }
            )
    return showtime_count, normalized


def _validate_share(payload, key, required):
    value = payload.get(key)
    if value is None:
        if required:
            bad_request("Field '%s' is required." % key)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad_request("Field '%s' must be a number." % key)
    dec = D(value)
    if dec < 0 or dec > 1:
        bad_request("Field '%s' must be a fraction in [0, 1]." % key)
    return dec


def _validate_on_sale(payload, plan, required):
    value = payload.get("on_sale_at")
    if value is None:
        if required:
            bad_request("Field 'on_sale_at' is required.")
        return None
    on_sale = parse_dt(value)
    if on_sale is None:
        bad_request("Field 'on_sale_at' must be an ISO-8601 UTC timestamp.")
    if plan:
        first = min(
            e["date_utc"] + timedelta(minutes=e["start_minute_utc"]) for e in plan
        )
        if on_sale >= first:
            raise ApiError("ERR_RIGHTS_WINDOW_VIOLATION")
    return on_sale


# ---------------------------------------------------------------------------
# Booking CRUD
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/bookings", methods=["POST"])
@endpoint("Exhibitor")
def create_booking():
    payload = body()
    title_id = f_str(payload, "title_id")
    title = get_or_404("titles", title_id)
    from services import evaluate_title_expiry

    evaluate_title_expiry(title)
    circuit_id = f_str(payload, "circuit_id")
    circuit = get_or_404("circuits", circuit_id)

    showtime_count, plan = _validate_plan(payload, title)
    on_sale = _validate_on_sale(payload, plan, required=True)
    if on_sale is None:
        bad_request("Field 'on_sale_at' is required.")
    guarantee = f_int(payload, "guarantee_cents", minimum=0)
    share = _validate_share(payload, "revenue_share_pct", required=True)
    min_screens = f_int(payload, "min_screens", minimum=1)
    threshold = f_int(payload, "pre_sale_threshold", minimum=0)
    if min_screens > int(title["max_screen_commitment"]):
        raise ApiError("ERR_MAX_SCREEN_COMMITMENT_EXCEEDED")
    # PRD §3.1: the floor is checked "not only when a booking is first opened but
    # again when it is submitted, when the licensor counters with new terms, and
    # when the exhibitor re-proposes after a counter".
    distributor = find("distributors", title["distributor_id"])
    if distributor is not None and guarantee < int(distributor["guarantee_floor_cents"]):
        raise ApiError("ERR_GUARANTEE_BELOW_FLOOR")

    row = new_row(
        "Booking",
        title_id=title_id,
        circuit_id=circuit_id,
        negotiating_user_id=getattr(g, "user_id", None),
        showtime_count=showtime_count,
        showtime_plan=plan,
        on_sale_at=on_sale,
        guarantee_cents=guarantee,
        revenue_share_pct=share,
        min_screens=min_screens,
        pre_sale_threshold=threshold,
        status="DRAFT",
        committed_screens_total=0,
        guarantee_ceiling_cents=0,
        pre_sale_tickets=0,
        live_feed_event_count=0,
        makegood_credit_cents=0,
        feed_failure_credit_cents=0,
        settled_at=None,
        _counter_count=0,
        _pre_sale_ledger_total=0,
    )
    db.bookings[row["id"]] = row
    recompute_ceiling(row)
    recompute_booking(row)
    recompute_title(title)
    touch(title)
    return respond_object(dump(row), 201)


@bp.route("/event-cinema/bookings/<booking_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Distributor", "Theater")
def read_booking(booking_id):
    row = get_or_404("bookings", booking_id)
    recompute_booking(row)
    recompute_ceiling(row)
    return respond_object(dump(row))


@bp.route("/event-cinema/bookings", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Distributor")
def list_bookings():
    title_id = q_str("title_id")
    circuit_id = q_str("circuit_id")
    status = q_enum("status", BOOKING_STATUS)
    rows = [
        r
        for r in db.bookings.values()
        if (title_id is None or r["title_id"] == title_id)
        and (circuit_id is None or r["circuit_id"] == circuit_id)
        and (status is None or r["status"] == status)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/bookings/<booking_id>", methods=["PUT"])
@endpoint("Exhibitor")
def update_booking(booking_id):
    row = get_or_404("bookings", booking_id)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    title = find("titles", row["title_id"])
    payload = body()

    if "showtime_count" in payload or "showtime_plan" in payload:
        count, plan = _validate_plan(payload, title, require_all=False)
        if count is not None:
            row["showtime_count"] = count
        if plan is not None:
            row["showtime_plan"] = plan
        if count is not None and row["showtime_plan"] is not None:
            if len(row["showtime_plan"]) != count:
                raise ApiError("ERR_SHOWTIME_PLAN_INVALID")

    if "on_sale_at" in payload and payload["on_sale_at"] is not None:
        on_sale = _validate_on_sale(payload, row["showtime_plan"], required=False)
        if on_sale is not None:
            row["on_sale_at"] = on_sale

    if "guarantee_cents" in payload and payload["guarantee_cents"] is not None:
        row["guarantee_cents"] = f_int(payload, "guarantee_cents", minimum=0)
    if "revenue_share_pct" in payload and payload["revenue_share_pct"] is not None:
        row["revenue_share_pct"] = _validate_share(payload, "revenue_share_pct", required=False)
    if "min_screens" in payload and payload["min_screens"] is not None:
        min_screens = f_int(payload, "min_screens", minimum=1)
        if min_screens > int(title["max_screen_commitment"]):
            raise ApiError("ERR_MAX_SCREEN_COMMITMENT_EXCEEDED")
        row["min_screens"] = min_screens
    if "pre_sale_threshold" in payload and payload["pre_sale_threshold"] is not None:
        row["pre_sale_threshold"] = f_int(payload, "pre_sale_threshold", minimum=0)

    check_version(row, payload)
    recompute_ceiling(row)
    touch(row)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Booking lines
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/bookings/<booking_id>/lines", methods=["POST"])
@endpoint("Exhibitor")
def create_line(booking_id):
    row = get_or_404("bookings", booking_id)
    title = find("titles", row["title_id"])
    payload = body()
    theater_id = f_str(payload, "theater_id")
    theater = get_or_404("theaters", theater_id)
    committed_screens = f_int(payload, "committed_screens", minimum=1)
    expected_attendance = f_int(payload, "expected_attendance", minimum=0)

    # PRD §2.4 fixes the observable layer order: existence, then state, then the
    # business constraints. A line may only be proposed while the negotiation is
    # still open (§3.1: "With the negotiation open, the exhibitor proposes venue
    # commitments"), so the state gate is decided before the duplicate-venue,
    # territory and max-screen rules -- otherwise a wrong-state request would be
    # answered with a constraint error it also happens to trip.
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    # priority 24 -- a venue commits to the run once and only once
    if any(ln["theater_id"] == theater_id for ln in booking_lines(row)):
        raise ApiError("ERR_DUPLICATE_BOOKING_LINE")
    # priority 13 -- territory
    if theater["state_code"] not in (title["territory_state_codes"] or []):
        raise ApiError("ERR_TERRITORY_UNLICENSED")
    # priority 21 -- max screen commitment
    recompute_booking(row)
    if int(row["committed_screens_total"]) + committed_screens > int(
        title["max_screen_commitment"]
    ):
        raise ApiError("ERR_MAX_SCREEN_COMMITMENT_EXCEEDED")

    check_version(row, payload)

    line = new_row(
        "BookingLine",
        booking_id=booking_id,
        theater_id=theater_id,
        committed_screens=committed_screens,
        exhibit_state="PROPOSED",
        expected_attendance=expected_attendance,
        sold_tickets=0,
        guarantee_applied_cents=0,
        credit_issued_cents=0,
    )
    db.booking_lines[line["id"]] = line
    recompute_booking(row)
    touch(row)
    return respond_object(dump(line), 201)


@bp.route("/event-cinema/bookings/<booking_id>/lines", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Distributor", "Theater")
def list_booking_lines(booking_id):
    row = get_or_404("bookings", booking_id)
    exhibit_state = q_enum("exhibit_state", EXHIBIT_STATE)
    rows = [
        ln
        for ln in booking_lines(row)
        if exhibit_state is None or ln["exhibit_state"] == exhibit_state
    ]
    return paginate(rows)


@bp.route("/event-cinema/booking-lines/<line_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Distributor", "Theater")
def read_line(line_id):
    line = get_or_404("booking_lines", line_id)
    recompute_line(line)
    return respond_object(dump(line))


@bp.route("/event-cinema/booking-lines", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "Exhibitor", "Theater")
def list_lines():
    booking_id = q_str("booking_id")
    theater_id = q_str("theater_id")
    exhibit_state = q_enum("exhibit_state", EXHIBIT_STATE)
    rows = [
        r
        for r in db.booking_lines.values()
        if (booking_id is None or r["booking_id"] == booking_id)
        and (theater_id is None or r["theater_id"] == theater_id)
        and (exhibit_state is None or r["exhibit_state"] == exhibit_state)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows)


# ---------------------------------------------------------------------------
# Presale sales and the negotiation verbs
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/bookings/<booking_id>/presale-sales", methods=["POST"])
@endpoint("Theater", "PlatformOps")
def record_presale(booking_id):
    row = get_or_404("bookings", booking_id)
    payload = body()
    quantity = f_int(payload, "quantity", minimum=0)
    row["_pre_sale_ledger_total"] = int(row.get("_pre_sale_ledger_total", 0)) + quantity
    recompute_booking(row)
    touch(row)
    return respond_object(dump(row))


@bp.route("/event-cinema/bookings/<booking_id>/submit", methods=["POST"])
@endpoint("Exhibitor")
def submit_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(submit(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/counter", methods=["POST"])
@endpoint("Distributor")
def counter_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(counter(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/re-propose", methods=["POST"])
@endpoint("Exhibitor")
def re_propose_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(re_propose(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/approve", methods=["POST"])
@endpoint("Distributor")
def approve_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(approve(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/cancel", methods=["POST"])
@endpoint("Exhibitor", "Distributor")
def cancel_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(cancel(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/cancel-with-compensation", methods=["POST"])
@endpoint("Distributor")
def cancel_with_compensation_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(cancel_with_compensation(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/suspend", methods=["POST"])
@endpoint("Distributor")
def suspend_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(suspend(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/resume", methods=["POST"])
@endpoint("Distributor")
def resume_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(resume(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/confirm", methods=["POST"])
@endpoint("PlatformOps")
def confirm_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(confirm(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/presale-checkpoint", methods=["POST"])
@endpoint("PlatformOps")
def presale_checkpoint_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(presale_checkpoint(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/release-screens", methods=["POST"])
@endpoint("Distributor")
def release_screens_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(release_screens(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/apply-makegood", methods=["POST"])
@endpoint("PlatformOps")
def apply_makegood_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(apply_makegood(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/reopen", methods=["POST"])
@endpoint("PlatformOps")
def reopen_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(reopen(row, body())))


@bp.route("/event-cinema/bookings/<booking_id>/close", methods=["POST"])
@endpoint("PlatformOps")
def close_route(booking_id):
    row = get_or_404("bookings", booking_id)
    return respond_object(dump(close(row, body())))