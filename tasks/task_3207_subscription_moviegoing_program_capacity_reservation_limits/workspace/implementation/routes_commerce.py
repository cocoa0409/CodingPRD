from flask import request

from core import (
    STORE, now, parse_dt, fmt_dt, get_auth, require_role, check_member_identity,
    parse_body, get_pagination, paginate, lookup, envelope_ok, ApiError,
    err_not_found, err_invalid_state, err_invalid_request, stamp_new,
    stamp_new_lean, touch, POINTS_PER_DOLLAR,
)
import engine


# ================= Serializers =================

def serialize_purchase(p):
    return dict(p)


def serialize_ledger_entry(e):
    return dict(e)


def serialize_report(r):
    return engine.report_view(r)


def serialize_line(l):
    return dict(l)


# ================= Concession purchases =================

def create_concession_purchase():
    user_id, role = get_auth(request)
    require_role(role, "Member", "TheaterStaff")
    body = parse_body(request, {
        "member_id": ("str", True, None),
        "theater_id": ("str", True, None),
        "pre_discount_cents": ("int", True, None),
    })
    # Priority 3: existence of body FKs, left to right
    member = lookup("members", body["member_id"])
    theater = lookup("theaters", body["theater_id"])
    # Priority 4: entity-backed identity
    check_member_identity(user_id, role, member["id"])
    # Priority 7: member-level gate
    if member["status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409,
                       "SUSPENDED members may not make concession purchases")
    if member["status"] != "ACTIVE":
        raise err_invalid_state("Member account is not ACTIVE")
    # concession_discount: floor discount first, then subtract
    plan = engine.active_subscription_plan(member["id"])
    discount_pct = plan["concession_discount_pct"] if plan else 0
    pre = body["pre_discount_cents"]
    discount_cents = (pre * discount_pct) // 100
    charged_cents = pre - discount_cents
    # loyalty_points_earn: base from charged_cents, tier multiplier, floor once
    base_points = (charged_cents // 100) * POINTS_PER_DOLLAR
    multiplier = plan["loyalty_points_multiplier_pct"] if plan else 100
    points_earned = (base_points * multiplier) // 100
    purchase = {
        "member_id": member["id"],
        "theater_id": theater["id"],
        "pre_discount_cents": pre,
        "discount_cents": discount_cents,
        "charged_cents": charged_cents,
        "points_earned": points_earned,
    }
    stamp_new(purchase)
    STORE["purchases"][purchase["id"]] = purchase
    engine.append_ledger(member["id"], "EARN_CONCESSION", points_earned,
                         source_id=purchase["id"])
    return envelope_ok(serialize_purchase(purchase), "object", 201)


def get_concession_purchase(purchase_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "TheaterStaff", "ProgramAdmin")
    purchase = lookup("purchases", purchase_id)
    check_member_identity(user_id, role, purchase["member_id"])
    return envelope_ok(serialize_purchase(purchase), "object", 200)


def list_concession_purchases():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices", "TheaterStaff")
    limit, offset = get_pagination(request)
    member_id = request.args.get("member_id")
    theater_id = request.args.get("theater_id")
    items = list(STORE["purchases"].values())
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    if theater_id is not None:
        items = [p for p in items if p["theater_id"] == theater_id]
    page, meta = paginate([serialize_purchase(p) for p in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_member_concession_purchases(member_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "ProgramAdmin")
    member = lookup("members", member_id)
    check_member_identity(user_id, role, member["id"])
    limit, offset = get_pagination(request)
    items = [p for p in STORE["purchases"].values() if p["member_id"] == member_id]
    page, meta = paginate([serialize_purchase(p) for p in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_theater_concession_purchases(theater_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff", "ProgramAdmin", "MemberServices")
    theater = lookup("theaters", theater_id)
    limit, offset = get_pagination(request)
    member_id = request.args.get("member_id")
    items = [p for p in STORE["purchases"].values() if p["theater_id"] == theater_id]
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    page, meta = paginate([serialize_purchase(p) for p in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


# ================= Loyalty ledger (reads) =================

def list_ledger():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices")
    limit, offset = get_pagination(request)
    member_id = request.args.get("member_id")
    kind = request.args.get("kind")
    items = list(STORE["ledger"].values())
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    page, meta = paginate([serialize_ledger_entry(e) for e in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def get_ledger_entry(entry_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices", "Member")
    entry = lookup("ledger", entry_id)
    check_member_identity(user_id, role, entry["member_id"])
    return envelope_ok(serialize_ledger_entry(entry), "object", 200)


# ================= Settlement =================

def create_settlement_report(theater_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff")
    theater = lookup("theaters", theater_id)
    body = parse_body(request, {
        "studio_code": ("str", True, None),
        "period_start": ("dt", True, None),
        "period_end": ("dt", True, None),
    })
    if body["period_end"] <= body["period_start"]:
        raise err_invalid_request("period_end must be after period_start")
    report = {
        "theater_id": theater["id"],
        "studio_code": body["studio_code"],
        "period_start": fmt_dt(body["period_start"]),
        "period_end": fmt_dt(body["period_end"]),
        "status": "DRAFT",
        "dispute_note": None,
        "frozen_total_admissions": None,
        "frozen_total_subscription_admissions": None,
        "frozen_total_gross_cents": None,
    }
    stamp_new(report)
    STORE["reports"][report["id"]] = report
    return envelope_ok(serialize_report(report), "object", 201)


def get_settlement_report(report_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff", "StudioRep", "ProgramAdmin", "MemberServices")
    report = lookup("reports", report_id)
    return envelope_ok(serialize_report(report), "object", 200)


def list_settlement_reports():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices", "TheaterStaff", "StudioRep")
    limit, offset = get_pagination(request)
    theater_id = request.args.get("theater_id")
    studio_code = request.args.get("studio_code")
    status = request.args.get("status")
    items = list(STORE["reports"].values())
    if theater_id is not None:
        items = [r for r in items if r["theater_id"] == theater_id]
    if studio_code is not None:
        items = [r for r in items if r["studio_code"] == studio_code]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate([serialize_report(r) for r in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_theater_settlement_reports(theater_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff", "StudioRep", "ProgramAdmin")
    theater = lookup("theaters", theater_id)
    limit, offset = get_pagination(request)
    studio_code = request.args.get("studio_code")
    status = request.args.get("status")
    items = [r for r in STORE["reports"].values() if r["theater_id"] == theater_id]
    if studio_code is not None:
        items = [r for r in items if r["studio_code"] == studio_code]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate([serialize_report(r) for r in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def add_settlement_line(report_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff")
    report = lookup("reports", report_id)
    body = parse_body(request, {"reservation_id": ("str", True, None)})
    reservation = lookup("reservations", body["reservation_id"])
    # Priority 5: report must be DRAFT (line set locked after submit)
    if report["status"] != "DRAFT":
        raise err_invalid_state("Lines may only be added to a DRAFT report")
    # Duplicate within this report
    for line in STORE["lines"].values():
        if line["report_id"] == report_id and line["reservation_id"] == reservation["id"]:
            raise ApiError("ERR_DUPLICATE_LINE", 422,
                           "Same reservation added twice to one report")
    # Priority 16: settleability
    showtime = STORE["showtimes"].get(reservation["showtime_id"])
    auditorium = STORE["auditoriums"].get(showtime["auditorium_id"]) if showtime else None
    if (
        reservation["status"] not in ("CHECKED_IN", "NO_SHOW")
        or reservation.get("settlement_reported")
        or showtime is None
        or auditorium is None
        or auditorium["theater_id"] != report["theater_id"]
        or showtime["studio_code"] != report["studio_code"]
        or not (parse_dt(report["period_start"]) <= parse_dt(showtime["starts_at"])
                < parse_dt(report["period_end"]))
    ):
        raise ApiError("ERR_LINE_NOT_SETTLEABLE", 422,
                       "Reservation is not settleable for this report")
    line = {
        "report_id": report["id"],
        "reservation_id": reservation["id"],
        "showtime_id": showtime["id"],
        "line_kind": "SUBSCRIPTION",
        "reported_value_cents": engine.line_valuation(showtime, "SUBSCRIPTION"),
    }
    stamp_new_lean(line)
    STORE["lines"][line["id"]] = line
    touch(report)
    return envelope_ok(serialize_line(line), "object", 201)


def list_report_lines(report_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff", "StudioRep", "ProgramAdmin")
    report = lookup("reports", report_id)
    limit, offset = get_pagination(request)
    line_kind = request.args.get("line_kind")
    items = [l for l in STORE["lines"].values() if l["report_id"] == report_id]
    if line_kind is not None:
        items = [l for l in items if l["line_kind"] == line_kind]
    page, meta = paginate([serialize_line(l) for l in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def get_settlement_line(line_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff", "StudioRep", "ProgramAdmin", "MemberServices")
    line = lookup("lines", line_id)
    return envelope_ok(serialize_line(line), "object", 200)


def list_settlement_lines():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices", "TheaterStaff", "StudioRep")
    limit, offset = get_pagination(request)
    report_id = request.args.get("report_id")
    reservation_id = request.args.get("reservation_id")
    showtime_id = request.args.get("showtime_id")
    line_kind = request.args.get("line_kind")
    items = list(STORE["lines"].values())
    if report_id is not None:
        items = [l for l in items if l["report_id"] == report_id]
    if reservation_id is not None:
        items = [l for l in items if l["reservation_id"] == reservation_id]
    if showtime_id is not None:
        items = [l for l in items if l["showtime_id"] == showtime_id]
    if line_kind is not None:
        items = [l for l in items if l["line_kind"] == line_kind]
    page, meta = paginate([serialize_line(l) for l in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_reservation_settlement_lines(reservation_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff", "StudioRep", "ProgramAdmin")
    reservation = lookup("reservations", reservation_id)
    limit, offset = get_pagination(request)
    items = [l for l in STORE["lines"].values() if l["reservation_id"] == reservation_id]
    page, meta = paginate([serialize_line(l) for l in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_showtime_settlement_lines(showtime_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff", "StudioRep", "ProgramAdmin")
    showtime = lookup("showtimes", showtime_id)
    limit, offset = get_pagination(request)
    items = [l for l in STORE["lines"].values() if l["showtime_id"] == showtime_id]
    page, meta = paginate([serialize_line(l) for l in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def submit_settlement_report(report_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff")
    report = lookup("reports", report_id)
    if report["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT report can be submitted")
    lines = engine.report_lines(report_id)
    if len(lines) < 1:
        raise ApiError("ERR_EMPTY_REPORT", 422,
                       "Submit requires at least one settlement line")
    report["frozen_total_admissions"] = len(lines)
    report["frozen_total_subscription_admissions"] = sum(
        1 for l in lines if l["line_kind"] == "SUBSCRIPTION")
    report["frozen_total_gross_cents"] = sum(l["reported_value_cents"] for l in lines)
    report["status"] = "SUBMITTED"
    touch(report)
    for line in lines:
        reservation = STORE["reservations"].get(line["reservation_id"])
        if reservation is not None and not reservation.get("settlement_reported"):
            reservation["settlement_reported"] = True
            touch(reservation)
    return envelope_ok(serialize_report(report), "object", 200)


def acknowledge_settlement_report(report_id):
    user_id, role = get_auth(request)
    require_role(role, "StudioRep")
    report = lookup("reports", report_id)
    if report["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED report can be acknowledged")
    report["status"] = "ACKNOWLEDGED"
    touch(report)
    return envelope_ok(serialize_report(report), "object", 200)


def dispute_settlement_report(report_id):
    user_id, role = get_auth(request)
    require_role(role, "StudioRep")
    report = lookup("reports", report_id)
    body = parse_body(request, {"dispute_note": ("str", True, None)})
    if report["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED report can be disputed")
    report["status"] = "DISPUTED"
    report["dispute_note"] = body["dispute_note"]
    touch(report)
    for line in engine.report_lines(report_id):
        reservation = STORE["reservations"].get(line["reservation_id"])
        if reservation is not None and reservation.get("settlement_reported"):
            reservation["settlement_reported"] = False
            touch(reservation)
    return envelope_ok(serialize_report(report), "object", 200)


def revise_settlement_report(report_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff")
    report = lookup("reports", report_id)
    if report["status"] != "DISPUTED":
        raise err_invalid_state("Only a DISPUTED report can be revised")
    report["status"] = "DRAFT"
    touch(report)
    return envelope_ok(serialize_report(report), "object", 200)
