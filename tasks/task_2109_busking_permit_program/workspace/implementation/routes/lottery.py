"""Rotation draws for premium pitches (PRD section 3.7)."""
from flask import Blueprint, request

import db
from body import Body
from errors import invalid_request, invalid_state, raise_err
from gates import (P_BODY, P_BODY_FK, P_DUP_ENTRY, P_ENTRY_DEADLINE,
                   P_ENTRY_DEADLINE_NOT, P_INVOICE_PAST_DUE, P_NOT_PREMIUM,
                   P_NO_ENTRIES, P_OWNER, P_PATH, P_PERMIT_ACTIVE,
                   P_PERMIT_SUSPENDED, P_PITCH_CLOSED, P_QUIET_HOURS,
                   P_SESSION_TOO_LONG, P_SLOT_OVERLAP, P_STATE, resolve,
                   resolve_body_fk, run_gates)
from listing import listing
from middleware import PERFORMER, PERMIT_OFFICER, require_owner, require_roles
from response import ok_object
from services import calc, domain
from services.serializers import serialize
from utils import new_entity, touch, whole_minutes

bp = Blueprint("lottery", __name__, url_prefix="/busking")


@bp.post("/lottery-draws")
def create_draw():
    require_roles([PERMIT_OFFICER])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        ctx["pitch"] = resolve_body_fk("pitches", raw, "pitch_id")

    def check_body():
        body.req_id("pitch_id")
        ctx["season_year"] = body.req_int("season_year", 2026, 2035)
        slot_start = body.req_dt("slot_start_at")
        slot_end = body.req_dt("slot_end_at")
        deadline = body.req_dt("entry_deadline_at")
        if not slot_end > slot_start:
            invalid_request("slot_end_at must be strictly after slot_start_at")
        if not deadline < slot_start:
            invalid_request("entry_deadline_at must be strictly before slot_start_at")
        ctx["slot_start"] = slot_start
        ctx["slot_end"] = slot_end
        ctx["deadline"] = deadline
        ctx["duration"] = whole_minutes(slot_start, slot_end)
        ctx["zone"] = db.get("zones", ctx["pitch"]["zone_id"])

    def check_quiet():
        if calc.violates_quiet_window(ctx["zone"], ctx["slot_start"], ctx["slot_end"]):
            raise_err("ERR_QUIET_HOURS_VIOLATION",
                      "The slot falls inside the district's quiet window")

    def check_pitch_open():
        if ctx["pitch"]["availability_status"] != "OPEN":
            raise_err("ERR_PITCH_CLOSED", "The pitch is closed")

    def check_duration():
        if ctx["duration"] > ctx["pitch"]["max_session_minutes"]:
            raise_err("ERR_SESSION_TOO_LONG", "The slot exceeds the pitch's session ceiling")

    def check_overlap():
        if domain.has_slot_conflict(ctx["pitch"]["id"], ctx["slot_start"], ctx["slot_end"]):
            raise_err("ERR_PITCH_SLOT_OVERLAP",
                      "The slot conflicts with an existing occupation on this pitch")

    def check_premium():
        if ctx["pitch"]["tier"] != "PREMIUM":
            raise_err("ERR_PITCH_NOT_PREMIUM", "Draws are only opened on PREMIUM pitches")

    run_gates([
        (P_BODY_FK, check_fks),
        (P_BODY, check_body),
        (P_QUIET_HOURS, check_quiet),
        (P_PITCH_CLOSED, check_pitch_open),
        (P_SESSION_TOO_LONG, check_duration),
        (P_SLOT_OVERLAP, check_overlap),
        (P_NOT_PREMIUM, check_premium),
    ])

    draw = new_entity("draws", {
        "pitch_id": ctx["pitch"]["id"],
        "season_year": ctx["season_year"],
        "slot_start_at": ctx["slot_start"],
        "slot_end_at": ctx["slot_end"],
        "entry_deadline_at": ctx["deadline"],
        "winner_slots": ctx["pitch"]["premium_slots_per_draw"],
        "entry_count": 0,
        "winner_count": 0,
        "status": "OPEN",
        "executed_at": None,
    })
    return ok_object(serialize(draw), status=201)


@bp.get("/lottery-draws/<draw_id>")
def read_draw(draw_id):
    require_roles([PERMIT_OFFICER, PERFORMER])
    ctx = {}
    run_gates([(P_PATH, lambda: ctx.update(draw=resolve("draws", draw_id)))])
    return ok_object(serialize(ctx["draw"]))


@bp.get("/lottery-draws")
def list_draws():
    require_roles([PERMIT_OFFICER, PERFORMER])
    return listing("draws", ["pitch_id", "status", "season_year"], request.args)


@bp.post("/lottery-draws/<draw_id>/entries")
def file_entry(draw_id):
    user_id, role = require_roles([PERFORMER])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        ctx["permit"] = resolve_body_fk("permits", raw, "permit_id")

    def check_owner():
        if ctx["permit"] is not None:
            require_owner(role, user_id, ctx["permit"]["performer_id"])

    def check_body():
        body.req_id("permit_id")

    def check_state():
        if ctx["draw"]["status"] != "OPEN":
            invalid_state("Entries are only accepted while the draw is OPEN")

    def check_active():
        if ctx["permit"]["lifecycle_status"] != "ACTIVE":
            raise_err("ERR_PERMIT_NOT_ACTIVE", "The permit is not ACTIVE")

    def check_suspended():
        if ctx["permit"]["compliance_status"] == "SUSPENDED":
            raise_err("ERR_PERMIT_SUSPENDED", "The permit is suspended")

    def check_deadline():
        if db.now() >= ctx["draw"]["entry_deadline_at"]:
            raise_err("ERR_ENTRY_DEADLINE_PASSED", "The draw's entry deadline has passed")

    def check_duplicate():
        for entry in domain.draw_entries(ctx["draw"]):
            if entry["permit_id"] == ctx["permit"]["id"]:
                raise_err("ERR_DUPLICATE_LOTTERY_ENTRY",
                          "This permit is already entered in the draw")

    def check_past_due():
        if domain.has_past_due_invoice(ctx["permit"]):
            raise_err("ERR_INVOICE_PAST_DUE", "The permit carries a past-due invoice")

    run_gates([
        (P_PATH, lambda: ctx.update(draw=resolve("draws", draw_id))),
        (P_BODY_FK, check_fks),
        (P_OWNER, check_owner),
        (P_BODY, check_body),
        (P_STATE, check_state),
        (P_PERMIT_ACTIVE, check_active),
        (P_PERMIT_SUSPENDED, check_suspended),
        (P_ENTRY_DEADLINE, check_deadline),
        (P_DUP_ENTRY, check_duplicate),
        (P_INVOICE_PAST_DUE, check_past_due),
    ])

    draw = ctx["draw"]
    entry = new_entity("entries", {
        "draw_id": draw["id"],
        "permit_id": ctx["permit"]["id"],
        "priority_band": None,
        "rank_position": None,
        "status": "SUBMITTED",
    })
    draw["entry_count"] += 1
    touch(draw)
    return ok_object(serialize(entry), status=201)


@bp.post("/lottery-draws/<draw_id>/execute")
def execute_draw(draw_id):
    require_roles([PERMIT_OFFICER])
    ctx = {}

    def check_state():
        if ctx["draw"]["status"] != "OPEN":
            invalid_state("Only an OPEN draw can be executed")

    def check_deadline():
        if not db.now() > ctx["draw"]["entry_deadline_at"]:
            raise_err("ERR_ENTRY_DEADLINE_NOT_PASSED",
                      "The draw may only be executed after its entry deadline")

    def check_entries():
        if ctx["draw"]["entry_count"] < 1:
            raise_err("ERR_NO_ELIGIBLE_ENTRIES", "The draw has attracted no entries")

    run_gates([
        (P_PATH, lambda: ctx.update(draw=resolve("draws", draw_id))),
        (P_STATE, check_state),
        (P_ENTRY_DEADLINE_NOT, check_deadline),
        (P_NO_ENTRIES, check_entries),
    ])

    draw = ctx["draw"]
    entries = domain.draw_entries(draw)
    submitted = [entry for entry in entries if entry["status"] == "SUBMITTED"]
    slot_minutes = calc.slot_duration_minutes(draw)

    candidates = []
    for entry in submitted:
        permit = db.get("permits", entry["permit_id"])
        performer = domain.performer_of(permit) if permit else None
        if permit is None or performer is None:
            continue
        if (permit["lifecycle_status"] == "ACTIVE"
                and permit["compliance_status"] == "CLEAR"
                and permit["season_year"] == draw["season_year"]
                and performer["standing"] in ("GOOD", "WATCH")
                and permit["season_minutes_used"] + slot_minutes <= calc.SEASON_MINUTES_CAP
                and not domain.has_past_due_invoice(permit)):
            candidates.append((entry, permit, performer))

    if not candidates:
        for entry in submitted:
            entry["status"] = "LOST"
            entry["rank_position"] = None
            touch(entry)
        draw["winner_count"] = 0
        draw["executed_at"] = db.now()
        draw["status"] = "VOID"
        touch(draw)
        return ok_object(serialize(draw))

    for entry, _permit, performer in candidates:
        entry["priority_band"] = calc.priority_band(performer["premium_wins_this_season"])

    ranked = sorted(
        candidates,
        key=lambda item: (item[0]["priority_band"], -item[2]["conduct_score"],
                          item[0]["created_at"], item[0]["_seq"]),
    )
    candidate_ids = {entry["id"] for entry, _p, _f in ranked}

    winners = 0
    for index, (entry, permit, performer) in enumerate(ranked):
        entry["rank_position"] = index + 1
        if index < draw["winner_slots"]:
            entry["status"] = "WON"
            winners += 1
            domain.mint_lottery_booking(draw, entry, permit)
            performer["premium_wins_this_season"] += 1
            touch(performer)
        else:
            entry["status"] = "LOST"
        touch(entry)

    for entry in submitted:
        if entry["id"] not in candidate_ids:
            entry["status"] = "LOST"
            entry["rank_position"] = None
            touch(entry)

    draw["winner_count"] = winners
    draw["executed_at"] = db.now()
    draw["status"] = "DRAWN"
    touch(draw)
    return ok_object(serialize(draw))


@bp.get("/lottery-entries/<entry_id>")
def read_entry(entry_id):
    user_id, role = require_roles([PERMIT_OFFICER, PERFORMER])
    ctx = {}

    def resolve_entry():
        ctx["entry"] = resolve("entries", entry_id)
        ctx["permit"] = db.get("permits", ctx["entry"]["permit_id"])

    run_gates([
        (P_PATH, resolve_entry),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["permit"]["performer_id"])),
    ])
    return ok_object(serialize(ctx["entry"]))


@bp.get("/lottery-entries")
def list_entries():
    require_roles([PERMIT_OFFICER, PERFORMER])
    return listing("entries", ["draw_id", "permit_id", "status"], request.args)
