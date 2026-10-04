"""Content delivery, encore programming, feed contingency, settlement and the
operational test-driving capabilities (§3.4, §3.5, §3.6, §3.7, §3.8)."""
from flask import Blueprint, g

from core import (
    DELIVERY_METHODS,
    DELIVERY_STATUS,
    ENCORE_WINDOW_STATUS,
    FAILURE_TYPES,
    FEED_EVENT_STATE,
    RESOLUTION_OUTCOMES,
    SETTLEMENT_STATUS,
    ApiError,
    D,
    bad_request,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_enum,
    f_int,
    f_str,
    fmt_dt,
    new_row,
    now,
    parse_dt,
    q_enum,
    q_str,
    respond_object,
    segregation_of_duties,
    touch,
)
from calcs import (
    best_attendance_ratio,
    encore_price,
    per_screening_credit,
    settlement_split,
)
from booking_flow import (
    check_version_raw,
    on_sale_sweep,
    presale_checkpoint_sweep,
    ruined_screenings,
)
from services import (
    delivery_ok,
    rekey,
    revoke_screening_keys,
    rights_expiry_sweep,
)
from store import (
    booking_lines,
    booking_screenings,
    find,
    get_or_404,
    line_screenings,
    paginate,
    recompute_booking,
    recompute_encore_window,
    screening_keys,
    screenings_affected_by,
)

bp = Blueprint("operations", __name__)


# ---------------------------------------------------------------------------
# Content deliveries
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/content-deliveries", methods=["POST"])
@endpoint("PlatformOps", "ContentOfficer")
def create_delivery():
    payload = body()
    booking_id = f_str(payload, "booking_id")
    booking = get_or_404("bookings", booking_id)
    method = f_enum(payload, "delivery_method", DELIVERY_METHODS)
    checksum = f_str(payload, "content_checksum")
    scheduled = f_dt(payload, "scheduled_delivery_utc")
    check_version_raw(booking["version"], payload.get("expected_booking_version"))

    delivery = new_row(
        "ContentDelivery",
        booking_id=booking_id,
        title_id=booking["title_id"],
        delivery_method=method,
        content_checksum=checksum,
        scheduled_delivery_utc=scheduled,
        delivered_at_utc=None,
        status="SCHEDULED",
        delivered_checksum=None,
    )
    db.content_deliveries[delivery["id"]] = delivery
    touch(booking)
    return respond_object(dump(delivery), 201)


@bp.route("/event-cinema/content-deliveries/<delivery_id>", methods=["GET"])
@endpoint("PlatformOps", "ContentOfficer", "Theater")
def read_delivery(delivery_id):
    return respond_object(dump(get_or_404("content_deliveries", delivery_id)))


@bp.route("/event-cinema/content-deliveries", methods=["GET"])
@endpoint("PlatformOps", "ContentOfficer")
def list_deliveries():
    booking_id = q_str("booking_id")
    title_id = q_str("title_id")
    status = q_enum("status", DELIVERY_STATUS)
    rows = [
        r
        for r in db.content_deliveries.values()
        if (booking_id is None or r["booking_id"] == booking_id)
        and (title_id is None or r["title_id"] == title_id)
        and (status is None or r["status"] == status)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/content-deliveries/<delivery_id>/mark-delivered", methods=["POST"])
@endpoint("PlatformOps", "ContentOfficer")
def mark_delivered(delivery_id):
    delivery = get_or_404("content_deliveries", delivery_id)
    if delivery["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    payload = body()
    delivered_checksum = f_str(payload, "delivered_checksum")
    delivery["status"] = "DELIVERED"
    delivery["delivered_at_utc"] = now()
    delivery["delivered_checksum"] = delivered_checksum
    touch(delivery)
    return respond_object(dump(delivery))


@bp.route("/event-cinema/content-deliveries/<delivery_id>/mark-failed", methods=["POST"])
@endpoint("PlatformOps", "ContentOfficer")
def mark_failed(delivery_id):
    delivery = get_or_404("content_deliveries", delivery_id)
    if delivery["status"] == "VERIFIED":
        raise ApiError("ERR_INVALID_STATE")
    if delivery["status"] == "FAILED":
        raise ApiError("ERR_INVALID_STATE")
    if delivery["status"] == "DELIVERED":
        if delivery["delivered_checksum"] == delivery["content_checksum"]:
            raise ApiError("ERR_INVALID_STATE")
    delivery["status"] = "FAILED"
    touch(delivery)
    return respond_object(dump(delivery))


@bp.route("/event-cinema/content-deliveries/<delivery_id>/verify", methods=["POST"])
@endpoint("PlatformOps", "ContentOfficer")
def verify_delivery(delivery_id):
    delivery = get_or_404("content_deliveries", delivery_id)
    if delivery["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE")
    if delivery["delivered_checksum"] != delivery["content_checksum"]:
        raise ApiError("ERR_INVALID_STATE")
    booking = get_or_404("bookings", delivery["booking_id"])
    title = find("titles", booking["title_id"])
    if not delivery_ok(booking, delivery, title):
        raise ApiError("ERR_DELIVERY_LEAD_VIOLATION")
    delivery["status"] = "VERIFIED"
    touch(delivery)
    return respond_object(dump(delivery))


# ---------------------------------------------------------------------------
# Encore windows
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/encore-windows", methods=["POST"])
@endpoint("Distributor", "ProgrammingManager")
def create_encore_window():
    payload = body()
    booking_id = f_str(payload, "booking_id")
    booking = get_or_404("bookings", booking_id)
    title = find("titles", booking["title_id"])
    title_id = payload.get("title_id")
    if title_id is not None:
        if not isinstance(title_id, str):
            bad_request("Field 'title_id' must be a string.")
        if find("titles", title_id) is None:
            raise ApiError("ERR_TITLE_NOT_FOUND")
        if title_id != booking["title_id"]:
            bad_request("Field 'title_id' must equal the parent booking's title.")

    window_start = f_dt(payload, "window_start_utc")
    window_end = f_dt(payload, "window_end_utc")
    standard = f_int(payload, "standard_ticket_price_cents", minimum=0)
    encore = f_int(payload, "encore_ticket_price_cents", minimum=0)
    planned = f_int(payload, "planned_screen_count", minimum=1)

    # priority 14 -- the window must fall inside the rights window
    if window_start < title["rights_start_utc"] or window_start >= title["rights_end_utc"]:
        raise ApiError("ERR_RIGHTS_WINDOW_VIOLATION")
    # priority 33 -- denominator
    if best_attendance_ratio(booking_lines(booking)) is None:
        if not any(
            ln["exhibit_state"] == "COMMITTED" and int(ln["expected_attendance"]) > 0
            for ln in booking_lines(booking)
        ):
            raise ApiError("ERR_ENCORE_DENOMINATOR_ZERO")
    # priority 34 -- window shape
    if window_end <= window_start:
        raise ApiError("ERR_ENCORE_WINDOW_INVALID")
    if window_end > title["rights_end_utc"]:
        raise ApiError("ERR_ENCORE_WINDOW_INVALID")
    if encore >= standard:
        raise ApiError("ERR_ENCORE_WINDOW_INVALID")

    check_version_raw(booking["version"], payload.get("expected_booking_version"))

    window = new_row(
        "EncoreWindow",
        booking_id=booking_id,
        title_id=booking["title_id"],
        window_start_utc=window_start,
        window_end_utc=window_end,
        standard_ticket_price_cents=standard,
        encore_ticket_price_cents=encore,
        planned_screen_count=planned,
        status="DRAFT",
        derived_encore_price_cents=encore_price(standard),
        encore_screening_count=0,
    )
    db.encore_windows[window["id"]] = window
    touch(booking)
    return respond_object(dump(window), 201)


@bp.route("/event-cinema/encore-windows/<window_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps", "Exhibitor", "Distributor")
def read_encore_window(window_id):
    window = get_or_404("encore_windows", window_id)
    recompute_encore_window(window)
    return respond_object(dump(window))


@bp.route("/event-cinema/encore-windows", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "FinanceOps")
def list_encore_windows():
    booking_id = q_str("booking_id")
    title_id = q_str("title_id")
    status = q_enum("status", ENCORE_WINDOW_STATUS)
    rows = [
        r
        for r in db.encore_windows.values()
        if (booking_id is None or r["booking_id"] == booking_id)
        and (title_id is None or r["title_id"] == title_id)
        and (status is None or r["status"] == status)
    ]
    rows.sort(key=lambda r: (r["window_start_utc"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/encore-windows/<window_id>/schedule", methods=["POST"])
@endpoint("ProgrammingManager")
def schedule_encore_window(window_id):
    window = get_or_404("encore_windows", window_id)
    if window["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    booking = get_or_404("bookings", window["booking_id"])
    lines = booking_lines(booking)
    if not any(
        ln["exhibit_state"] == "COMMITTED" and int(ln["expected_attendance"]) > 0
        for ln in lines
    ):
        raise ApiError("ERR_ENCORE_DENOMINATOR_ZERO")
    if booking["status"] not in ("CONFIRMED", "SETTLED"):
        raise ApiError("ERR_ENCORE_NOT_ELIGIBLE")
    ratio = best_attendance_ratio(lines)
    if ratio is None or ratio < D("0.5"):
        raise ApiError("ERR_ENCORE_NOT_ELIGIBLE")
    window["status"] = "SCHEDULED"
    touch(window)
    return respond_object(dump(window))


@bp.route("/event-cinema/encore-windows/<window_id>/withdraw", methods=["POST"])
@endpoint("ProgrammingManager")
def withdraw_encore_window(window_id):
    window = get_or_404("encore_windows", window_id)
    if window["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    window["status"] = "WITHDRAWN"
    touch(window)
    for screening in db.screenings.values():
        if screening.get("encore_window_id") != window["id"]:
            continue
        if screening["state"] != "SCHEDULED":
            continue
        screening["state"] = "SKIPPED_CANCELLED"
        touch(screening)
        revoke_screening_keys(screening, "CONTENT_FAILURE")
        booking = find("bookings", screening["booking_id"])
        if booking is not None:
            recompute_booking(booking)
    recompute_encore_window(window)
    return respond_object(dump(window))


# ---------------------------------------------------------------------------
# Feed events
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/feed-events", methods=["POST"])
@endpoint("PlatformOps", "Theater")
def create_feed_event():
    payload = body()
    booking_id = f_str(payload, "booking_id")
    booking = get_or_404("bookings", booking_id)
    screening_id = payload.get("screening_id")
    if screening_id is not None:
        if not isinstance(screening_id, str):
            bad_request("Field 'screening_id' must be a string.")
        screening = find("screenings", screening_id)
        if screening is None:
            raise ApiError("ERR_SCREENING_NOT_FOUND")
        if screening["booking_id"] != booking_id or screening["state"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")
    failure_type = f_enum(payload, "failure_type", FAILURE_TYPES)
    detected_at = f_dt(payload, "detected_at_utc")
    outage = f_int(payload, "outage_minutes", minimum=0)

    event = new_row(
        "FeedEvent",
        booking_id=booking_id,
        screening_id=screening_id,
        failure_type=failure_type,
        detected_at_utc=detected_at,
        outage_minutes=outage,
        state="DETECTED",
        resolution_outcome=None,
        affected_screening_count=0,
        _filed_by=getattr(g, "user_id", None),
        _revoked_key_ids=[],
    )
    event["affected_screening_count"] = len(
        [
            s
            for s in booking_screenings(booking)
            if s["state"] in ("SCHEDULED", "SCREENED") and s["starts_at"] <= detected_at
        ]
    )
    db.feed_events[event["id"]] = event
    recompute_booking(booking)
    touch(booking)
    return respond_object(dump(event), 201)


@bp.route("/event-cinema/feed-events/<event_id>", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager", "Distributor")
def read_feed_event(event_id):
    return respond_object(dump(get_or_404("feed_events", event_id)))


@bp.route("/event-cinema/feed-events", methods=["GET"])
@endpoint("PlatformOps", "ProgrammingManager")
def list_feed_events():
    booking_id = q_str("booking_id")
    screening_id = q_str("screening_id")
    state = q_enum("state", FEED_EVENT_STATE)
    rows = [
        r
        for r in db.feed_events.values()
        if (booking_id is None or r["booking_id"] == booking_id)
        and (screening_id is None or r.get("screening_id") == screening_id)
        and (state is None or r["state"] == state)
    ]
    rows.sort(key=lambda r: (r["detected_at_utc"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/feed-events/<event_id>/confirm", methods=["POST"])
@endpoint("PlatformOps")
def confirm_feed_event(event_id):
    event = get_or_404("feed_events", event_id)
    if event["state"] != "DETECTED":
        raise ApiError("ERR_INVALID_STATE")
    booking = get_or_404("bookings", event["booking_id"])
    if int(event["outage_minutes"]) < 5:
        raise ApiError("ERR_FEED_OUTAGE_TOO_SHORT")
    candidates = [
        s
        for s in booking_screenings(booking)
        if s["state"] in ("SCHEDULED", "SCREENED")
        and s["starts_at"] <= event["detected_at_utc"]
    ]
    if not candidates:
        raise ApiError("ERR_INVALID_STATE")
    segregation_of_duties(event.get("_filed_by"))

    affected = screenings_affected_by(booking, event)
    event["affected_screening_count"] = len(affected)
    event["state"] = "CONFIRMED"
    touch(event)
    for screening in affected:
        for key in screening_keys(screening):
            if key["issuance_status"] == "REVOKED":
                continue
            key["issuance_status"] = "REVOKED"
            key["revocation_reason"] = "FEED_LOSS"
            touch(key)
            theater = find("theaters", screening["theater_id"])
            if theater is not None:
                theater["pending_rekey_count"] = int(theater["pending_rekey_count"]) + 1
                touch(theater)
            event["_revoked_key_ids"].append(key["id"])
    recompute_booking(booking)
    touch(booking)
    return respond_object(dump(event))


@bp.route("/event-cinema/feed-events/<event_id>/void", methods=["POST"])
@endpoint("PlatformOps")
def void_feed_event(event_id):
    event = get_or_404("feed_events", event_id)
    if event["state"] != "DETECTED":
        raise ApiError("ERR_INVALID_STATE")
    if event.get("_revoked_key_ids"):
        raise ApiError("ERR_INVALID_STATE")
    booking = get_or_404("bookings", event["booking_id"])
    revoked_feed_loss = any(
        k["revocation_reason"] == "FEED_LOSS"
        for k in db.encryption_keys.values()
        if k["screening_id"] in {s["id"] for s in booking_screenings(booking)}
    )
    if revoked_feed_loss:
        raise ApiError("ERR_INVALID_STATE")
    event["state"] = "VOIDED"
    touch(event)
    recompute_booking(booking)
    touch(booking)
    return respond_object(dump(event))


@bp.route("/event-cinema/feed-events/<event_id>/resolve", methods=["POST"])
@endpoint("PlatformOps")
def resolve_feed_event(event_id):
    event = get_or_404("feed_events", event_id)
    payload = body()
    outcome = f_enum(payload, "resolution_outcome", RESOLUTION_OUTCOMES)
    booking = get_or_404("bookings", event["booking_id"])
    if event["state"] == "CONFIRMED":
        affected_ids = {s["id"] for s in screenings_affected_by(booking, event)}
        if any(
            s["state"] == "SCHEDULED"
            for s in booking_screenings(booking)
            if s["starts_at"] <= event["detected_at_utc"]
            or (event.get("screening_id") and s["id"] == event["screening_id"])
        ):
            raise ApiError("ERR_INVALID_STATE")
        if not affected_ids and not booking_lines(booking):
            raise ApiError("ERR_INVALID_STATE")
        recompute_booking(booking)
        if int(booking["makegood_credit_cents"]) <= 0:
            raise ApiError("ERR_INVALID_STATE")
    elif event["state"] == "VOIDED":
        if outcome != "RECOVERED":
            raise ApiError("ERR_INVALID_STATE")
    else:
        raise ApiError("ERR_INVALID_STATE")

    event["state"] = "RESOLVED"
    event["resolution_outcome"] = outcome
    touch(event)
    return respond_object(dump(event))


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------
def _compute_settlement(settlement, booking):
    circuit = find("circuits", booking["circuit_id"])
    recompute_booking(booking)
    makegood = int(booking.get("makegood_credit_cents", 0))
    distributor_net, exhibitor_net, drift = settlement_split(
        settlement, booking, circuit, makegood
    )
    settlement["makegood_credit_cents"] = makegood
    settlement["feed_failure_credit_cents"] = int(
        booking.get("feed_failure_credit_cents", 0)
    )
    settlement["distributor_net_cents"] = distributor_net
    settlement["exhibitor_net_cents"] = exhibitor_net
    settlement["invariant_drift_cents"] = drift
    return settlement


@bp.route("/event-cinema/settlements", methods=["POST"])
@endpoint("FinanceOps", "PlatformOps")
def create_settlement():
    payload = body()
    booking_id = f_str(payload, "booking_id")
    booking = get_or_404("bookings", booking_id)
    gross = f_int(payload, "gross_box_office_cents", minimum=0)
    reported_line_count = f_int(payload, "reported_line_count", minimum=1)
    topup = f_int(payload, "topup_paid_cents", required=False, default=0)
    adjustment = f_int(payload, "adjustment_cents", required=False, default=0)

    if booking["status"] not in ("CONFIRMED", "SETTLED"):
        raise ApiError("ERR_INVALID_STATE")
    lines = booking_lines(booking)
    if not lines:
        raise ApiError("ERR_UNREPORTED_ATTENDANCE")
    for line in lines:
        screenings = line_screenings(line)
        if not screenings or any(s["state"] == "SCHEDULED" for s in screenings):
            raise ApiError("ERR_UNREPORTED_ATTENDANCE")

    segregation_of_duties(
        booking.get("_approved_by"),
        booking.get("_countered_by"),
        booking.get("_submitted_by"),
    )

    settlement = new_row(
        "Settlement",
        booking_id=booking_id,
        gross_box_office_cents=gross,
        reported_line_count=reported_line_count,
        topup_paid_cents=topup,
        adjustment_cents=adjustment,
        feed_failure_credit_cents=0,
        makegood_credit_cents=0,
        distributor_net_cents=0,
        exhibitor_net_cents=0,
        invariant_drift_cents=0,
        status="OPEN",
        closed_at_utc=None,
    )
    db.settlements[settlement["id"]] = settlement
    _compute_settlement(settlement, booking)

    # Every line has reported, so the settlement closes in the same request.
    settlement["status"] = "CLOSED"
    settlement["closed_at_utc"] = now()
    touch(settlement)
    booking["status"] = "SETTLED"
    booking["settled_at"] = now()
    touch(booking)
    return respond_object(dump(settlement), 201)


@bp.route("/event-cinema/settlements/<settlement_id>", methods=["GET"])
@endpoint("FinanceOps", "PlatformOps", "Distributor", "ProgrammingManager")
def read_settlement(settlement_id):
    return respond_object(dump(get_or_404("settlements", settlement_id)))


@bp.route("/event-cinema/settlements", methods=["GET"])
@endpoint("FinanceOps", "PlatformOps")
def list_settlements():
    booking_id = q_str("booking_id")
    status = q_enum("status", SETTLEMENT_STATUS)
    rows = [
        r
        for r in db.settlements.values()
        if (booking_id is None or r["booking_id"] == booking_id)
        and (status is None or r["status"] == status)
    ]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows)


@bp.route("/event-cinema/settlements/<settlement_id>/close", methods=["POST"])
@endpoint("FinanceOps")
def close_settlement(settlement_id):
    settlement = get_or_404("settlements", settlement_id)
    if settlement["status"] == "CLOSED":
        raise ApiError("ERR_SETTLEMENT_ALREADY_CLOSED")
    booking = get_or_404("bookings", settlement["booking_id"])
    settlement["status"] = "CLOSED"
    settlement["closed_at_utc"] = now()
    touch(settlement)
    booking["status"] = "SETTLED"
    booking["settled_at"] = now()
    touch(booking)
    return respond_object(dump(settlement))


@bp.route("/event-cinema/settlements/<settlement_id>/reopen", methods=["POST"])
@endpoint("FinanceOps")
def reopen_settlement(settlement_id):
    settlement = get_or_404("settlements", settlement_id)
    if settlement["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    booking = get_or_404("bookings", settlement["booking_id"])
    settlement["status"] = "REOPENED"
    settlement["closed_at_utc"] = None
    touch(settlement)
    if booking["status"] == "SETTLED":
        booking["status"] = "CONFIRMED"
        booking["settled_at"] = None
        touch(booking)
    return respond_object(dump(settlement))


@bp.route("/event-cinema/settlements/<settlement_id>/apply-makegood", methods=["POST"])
@endpoint("FinanceOps")
def settlement_apply_makegood(settlement_id):
    settlement = get_or_404("settlements", settlement_id)
    payload = body()
    line_id = f_str(payload, "line_id")
    feed_event_id = f_str(payload, "feed_event_id")
    event = find("feed_events", feed_event_id)
    if event is None:
        raise ApiError("ERR_FEED_EVENT_NOT_FOUND")
    booking = get_or_404("bookings", settlement["booking_id"])
    line = find("booking_lines", line_id)
    if line is None or line["booking_id"] != booking["id"]:
        raise ApiError("ERR_LINE_NOT_FOUND")
    if event["state"] != "CONFIRMED" or event["booking_id"] != booking["id"]:
        raise ApiError("ERR_INVALID_STATE")
    if line["exhibit_state"] != "COMMITTED":
        raise ApiError("ERR_BOOKING_LINE_NOT_COMMITTED")
    title = find("titles", booking["title_id"])
    theater = get_or_404("theaters", line["theater_id"])
    ruined = ruined_screenings(line, event)
    if not ruined:
        raise ApiError("ERR_MAKEGOOD_LINE_NOT_APPLICABLE")

    price = int(title["ticket_price_cents"]) if title.get("ticket_price_cents") is not None else int(
        find("distributors", title["distributor_id"])["ticket_price_default_cents"]
    )
    gained = 0
    for screening in ruined:
        if event["id"] in screening.get("_credited_events", []):
            continue
        credit = per_screening_credit(
            int(event["outage_minutes"]),
            price,
            int(screening["reported_attendance"] or 0),
            int(title["duration_minutes"]),
            int(theater["seats_total"]),
        )
        screening.setdefault("_credited_events", []).append(event["id"])
        screening["_credited_cents"] = int(screening.get("_credited_cents", 0)) + credit
        if event["failure_type"] == "FEED_LOSS":
            screening["_credited_feed_loss_cents"] = (
                int(screening.get("_credited_feed_loss_cents", 0)) + credit
            )
        gained += credit

    line["credit_issued_cents"] = int(line.get("credit_issued_cents", 0)) + gained
    touch(line)
    recompute_booking(booking)
    booking["feed_failure_credit_cents"] = sum(
        int(s.get("_credited_feed_loss_cents", 0)) for s in booking_screenings(booking)
    )
    touch(booking)

    _compute_settlement(settlement, booking)
    touch(settlement)
    return respond_object(dump(settlement))


# ---------------------------------------------------------------------------
# Operational capabilities
# ---------------------------------------------------------------------------
@bp.route("/event-cinema/_clock/set_current_utc", methods=["POST"])
@endpoint("PlatformOps")
def set_current_utc():
    payload = body()
    value = payload.get("to_iso8601")
    instant = parse_dt(value) if isinstance(value, str) else None
    if instant is None:
        bad_request("Field 'to_iso8601' must be an ISO-8601 UTC timestamp.")
    db.clock = instant
    return respond_object({"current_utc": fmt_dt(instant)})


@bp.route("/event-cinema/_ops/run-on-sale-sweep", methods=["POST"])
@endpoint("PlatformOps")
def run_on_sale_sweep():
    advanced = on_sale_sweep()
    return respond_object(
        {"advanced_count": len(advanced), "booking_ids": [b["id"] for b in advanced]}
    )


@bp.route("/event-cinema/_ops/run-presale-checkpoints", methods=["POST"])
@endpoint("PlatformOps")
def run_presale_checkpoints():
    cancelled = presale_checkpoint_sweep()
    return respond_object(
        {"cancelled_count": len(cancelled), "booking_ids": [b["id"] for b in cancelled]}
    )


@bp.route("/event-cinema/_ops/run-rights-expiry-sweep", methods=["POST"])
@endpoint("PlatformOps")
def run_rights_expiry_sweep():
    expired, cancelled = rights_expiry_sweep()
    return respond_object(
        {"expired_title_count": expired, "cancelled_booking_count": cancelled}
    )


@bp.route("/event-cinema/_ops/rekey-sweep", methods=["POST"])
@endpoint("PlatformOps")
def run_rekey_sweep():
    payload = body()
    theater_id = f_str(payload, "theater_id")
    theater = get_or_404("theaters", theater_id)
    return respond_object(dump(rekey(theater)))