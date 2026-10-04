"""Concert loan endpoints (PRD 3.6): request, confirm, return."""
from datetime import timedelta

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import GRADE_RANK, TECH_BUFFER_SECONDS, loan_fee_cents, tour_weeks
from db import STORE, clock_now, new_entity, touch
from envelope import ok, paged
from errors import raise_err
from serialize import loan as ser_loan
from validate import get_body, opt_fk, req_dt, req_enum

bp = Blueprint("loans", __name__, url_prefix="/piano-works")

MODELS = ("MODEL_D", "MODEL_B", "MODEL_O", "ART_CASE")
GRADES = ("A", "B", "C", "D")
LIAISON = ("ArtistLiaison",)
TECH_BUFFER = timedelta(seconds=TECH_BUFFER_SECONDS)


def _get_loan(lid):
    l = STORE["loans"].get(lid)
    if l is None:
        raise_err("ERR_NOT_FOUND", "concert loan %s not found" % lid)
    return l


def _instrument_window_free(inst_id, start, end, exclude_loan_id=None):
    """Half-open overlap: adjacency (end == start) is allowed."""
    for x in STORE["loans"].values():
        if x["status"] != "ON_TOUR" or x["instrument_id"] != inst_id or x["id"] == exclude_loan_id:
            continue
        if not (x["tour_end"] <= start or end <= x["tour_start"]):
            return False
    return True


def _technician_free(tech_id, start, end):
    """Closed intervals plus one buffer day on both sides."""
    for x in STORE["loans"].values():
        if x["status"] != "ON_TOUR" or x["technician_id"] != tech_id:
            continue
        if not (start > x["tour_end"] + TECH_BUFFER or x["tour_start"] > end + TECH_BUFFER):
            return False
    return True


def _eligible_instrument(inst, model):
    return (
        inst["status"] in ("BANK", "ON_LOAN")
        and inst["certified_authentic"]
        and inst["condition_grade"] in ("A", "B")
        and inst["model"] == model
    )


@bp.post("/concert-loans")
def create_loan():
    caller = authenticate(("Artist",))
    body = get_body()
    desired_model = req_enum(body, "desired_model", MODELS)
    tour_start = req_dt(body, "tour_start")
    tour_end = req_dt(body, "tour_end")
    if tour_end <= tour_start:
        raise_err("ERR_LOAN_WINDOW_INVALID", "tour_end must be strictly after tour_start")
    if tour_start.date() < clock_now().date():
        raise_err("ERR_LOAN_WINDOW_INVALID", "tour_start is before the current clock date")
    artist = STORE["artists"][caller["id"]]
    if artist["status"] != "ACTIVE":
        raise_err("ERR_ARTIST_NOT_ACTIVE", "artist must be ACTIVE to request a loan")
    l = new_entity()
    l.update({
        "artist_id": caller["id"],
        "desired_model": desired_model,
        "tour_start": tour_start,
        "tour_end": tour_end,
        "instrument_id": None,
        "technician_id": None,
        "status": "REQUESTED",
        "fee_cents": None,
    })
    STORE["loans"][l["id"]] = l
    return ok(ser_loan(l), 201)


@bp.get("/concert-loans")
def list_loans():
    authenticate(ALL_ROLES)
    items = list(STORE["loans"].values())
    for field in ("instrument_id", "artist_id", "technician_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [l for l in items if l[field] == v]
    return paged(items, ser_loan)


@bp.get("/concert-loans/<lid>")
def get_loan(lid):
    authenticate(ALL_ROLES)
    return ok(ser_loan(_get_loan(lid)))


@bp.post("/concert-loans/<lid>/confirm")
def confirm_loan(lid):
    authenticate(LIAISON)
    l = _get_loan(lid)
    body = get_body()
    tech_id = opt_fk(body, "technician_id")
    if tech_id is None:
        raise_err("ERR_VALIDATION", "technician_id is required")
    tech = STORE["craftsmen"].get(tech_id)
    if tech is None:
        raise_err("ERR_NOT_FOUND", "technician %s not found" % tech_id)
    inst_id = opt_fk(body, "instrument_id")
    inst = None
    if inst_id is not None:
        inst = STORE["instruments"].get(inst_id)
        if inst is None:
            raise_err("ERR_NOT_FOUND", "instrument %s not found" % inst_id)
    # Priority 4: loan state, then artist standing re-check.
    if l["status"] != "REQUESTED":
        raise_err("ERR_INVALID_STATE", "only a REQUESTED loan can be confirmed")
    artist = STORE["artists"][l["artist_id"]]
    if artist["status"] != "ACTIVE":
        raise_err("ERR_ARTIST_NOT_ACTIVE", "artist must be ACTIVE at confirm")
    # Priority 6: technician qualification, then instrument eligibility / selector.
    if tech["specialty"] != "VOICING":
        raise_err("ERR_TECHNICIAN_NOT_QUALIFIED", "technician specialty must be VOICING")
    start, end = l["tour_start"], l["tour_end"]
    if inst is not None:
        if not _eligible_instrument(inst, l["desired_model"]):
            raise_err("ERR_INSTRUMENT_NOT_ELIGIBLE", "instrument fails eligibility")
    else:
        pool = [
            i for i in STORE["instruments"].values()
            if _eligible_instrument(i, l["desired_model"])
            and _instrument_window_free(i["id"], start, end)
        ]
        # Rank: grade A before B; ties broken by created_at ASC (never id).
        pool.sort(key=lambda i: (GRADE_RANK[i["condition_grade"]], i["created_at"], i["_seq"]))
        if not pool:
            raise_err("ERR_NO_ELIGIBLE_INSTRUMENT", "no eligible instrument for this window")
        inst = pool[0]
    # Priority 7: instrument half-open fence, then technician buffered fence.
    if not _instrument_window_free(inst["id"], start, end, exclude_loan_id=l["id"]):
        raise_err("ERR_LOAN_WINDOW_CONFLICT", "instrument tour window overlaps another ON_TOUR loan")
    if not _technician_free(tech_id, start, end):
        raise_err("ERR_TECHNICIAN_WINDOW_CONFLICT", "technician buffered window overlaps another ON_TOUR loan")
    l["instrument_id"] = inst["id"]
    l["technician_id"] = tech_id
    l["fee_cents"] = loan_fee_cents(inst["model"], artist["tier"], tour_weeks(start, end))
    l["status"] = "ON_TOUR"
    touch(l)
    # BANK -> ON_LOAN; a chained confirm on an ON_LOAN instrument stays ON_LOAN.
    if inst["status"] == "BANK":
        inst["status"] = "ON_LOAN"
    touch(inst)
    return ok(ser_loan(l))


@bp.post("/concert-loans/<lid>/return")
def return_loan(lid):
    authenticate(LIAISON)
    l = _get_loan(lid)
    body = get_body()
    grade = req_enum(body, "condition_grade_observed", GRADES)
    if l["status"] != "ON_TOUR":
        raise_err("ERR_INVALID_STATE", "only an ON_TOUR loan can be returned")
    inst = STORE["instruments"][l["instrument_id"]]
    # Cascade link 1: overwrite condition grade.
    inst["condition_grade"] = grade
    # Cascade link 2: re-route status.
    if grade in ("A", "B"):
        if inst["status"] == "ON_LOAN":
            others = any(
                x["status"] == "ON_TOUR" and x["instrument_id"] == inst["id"] and x["id"] != l["id"]
                for x in STORE["loans"].values()
            )
            inst["status"] = "ON_LOAN" if others else "BANK"
    else:
        if inst["status"] == "ON_LOAN":
            inst["status"] = "RESTORATION"
            # Cascade link 3: auto-create the LOAN_RETURN restoration case.
            case = new_entity()
            case.update({
                "instrument_id": inst["id"],
                "lead_craftsman_id": l["technician_id"],
                "origin": "LOAN_RETURN",
                "diagnosis": "post-tour condition %s" % grade,
                "status": "QUOTED",
                "authentic_parts_value_cents": 0,
                "total_parts_value_cents": 0,
                "waiver_accepted": False,
                "authenticity_pct": None,
                "final_authentic_value_cents": None,
                "final_total_parts_value_cents": None,
            })
            STORE["restorations"][case["id"]] = case
    touch(inst)
    l["status"] = "RETURNED"
    touch(l)
    return ok(ser_loan(l))
