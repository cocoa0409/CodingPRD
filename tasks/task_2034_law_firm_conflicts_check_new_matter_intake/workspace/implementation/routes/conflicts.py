"""Conflict check + conflict hit endpoints (PRD 3.4)."""

from flask import Blueprint, request

import db
from db import bump
from errors import (
    ApiError, invalid, ERR_MATTER_TERMINAL, ERR_HIT_NOT_PENDING,
    ERR_NOT_RESPONSIBLE_ATTORNEY,
)
from middleware import caller, admit, body
from response import ok_object, paginate, sort_by_created
from services.cascades import maybe_activate_lateral
from services.clearance import recompute_clearance, matter_checks
from services.matching import run_intake_check, sort_hits
from services.naming import DEFAULT_MATCH_THRESHOLD
from services.validate import SEARCH_VARIANTS, REVIEW_DECISIONS, resolve, is_int

bp = Blueprint("conflicts", __name__)

STAFF = ("FirmAdmin", "IntakeSpecialist", "ResponsibleAttorney",
         "ConflictsPartner", "BillingClerk")
HIT_READERS = ("FirmAdmin", "IntakeSpecialist", "ResponsibleAttorney",
               "ConflictsPartner")


@bp.get("/intake/matters/<mid>/conflict-checks")
def list_conflict_checks(mid):
    _, role = caller()
    admit(role, STAFF)
    resolve(db.store.matters, mid)
    return paginate(sort_by_created(matter_checks(mid)), request.args)


@bp.post("/intake/matters/<mid>/conflict-checks")
def create_conflict_check(mid):
    _, role = caller()
    admit(role, ("IntakeSpecialist", "ResponsibleAttorney"))
    matter = resolve(db.store.matters, mid)
    data = body()

    # Tier 6: conflict checks rejected on CLOSED/DECLINED matters.
    if matter["lifecycle_status"] in ("CLOSED", "DECLINED"):
        raise ApiError(ERR_MATTER_TERMINAL, 409,
                       "Cannot run conflict checks on a CLOSED or DECLINED "
                       "matter")

    # Tier 12: request shape.
    search_variant = data.get("search_variant")
    if search_variant not in SEARCH_VARIANTS:
        raise invalid("search_variant must be STRICT or PHONETIC")
    match_threshold = data.get("match_threshold", DEFAULT_MATCH_THRESHOLD)
    if not is_int(match_threshold) or not (0 <= match_threshold <= 100):
        raise invalid("match_threshold must be an integer in 0..100")

    check = run_intake_check(matter, search_variant, match_threshold)
    return ok_object(check, 201)


@bp.get("/intake/conflict-hits")
def list_conflict_hits():
    _, role = caller()
    admit(role, HIT_READERS)
    rows = list(db.store.conflict_hits.values())
    for param in ("check_id", "matched_party_id", "matched_matter_id",
                  "review_status"):
        value = request.args.get(param)
        if value is not None:
            rows = [h for h in rows if h[param] == value]
    # Deterministic hit ordering (PRD 3.4): score DESC, matched party
    # created_at ASC, matched matter created_at ASC.
    return paginate(sort_hits(rows), request.args)


@bp.get("/intake/conflict-hits/<hid>")
def get_conflict_hit(hid):
    _, role = caller()
    admit(role, HIT_READERS)
    hit = resolve(db.store.conflict_hits, hid)
    return ok_object(hit)


@bp.get("/intake/conflict-hits/<hid>/waiver-requests")
def list_hit_waivers(hid):
    _, role = caller()
    admit(role, ("ResponsibleAttorney", "ConflictsPartner", "FirmAdmin"))
    resolve(db.store.conflict_hits, hid)
    rows = [w for w in db.store.waiver_requests.values()
            if w["conflict_hit_id"] == hid]
    return paginate(sort_by_created(rows), request.args)


@bp.post("/intake/conflict-hits/<hid>/review")
def review_conflict_hit(hid):
    user_id, role = caller()
    admit(role, ("ResponsibleAttorney", "ConflictsPartner"))
    hit = resolve(db.store.conflict_hits, hid)
    data = body()

    check = db.store.conflict_checks.get(hit["check_id"])
    matter = db.store.matters.get(check["matter_id"]) if check else None

    # Tier 5 ownership: a ResponsibleAttorney caller must be the
    # responsible attorney of the check's matter.
    if (role == "ResponsibleAttorney" and matter is not None
            and user_id != matter["responsible_attorney_id"]):
        raise ApiError(ERR_NOT_RESPONSIBLE_ATTORNEY, 403,
                       "Caller is not the responsible attorney of the "
                       "check's matter")

    # Tier 6: the hit must still be PENDING.
    if hit["review_status"] != "PENDING":
        raise ApiError(ERR_HIT_NOT_PENDING, 409,
                       "Only a PENDING hit may be reviewed")

    # Tier 12: request shape.
    decision = data.get("decision")
    if decision not in REVIEW_DECISIONS:
        raise invalid("decision must be CONFIRMED or DISMISSED")
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise invalid("note must be a string")

    hit["review_status"] = decision
    hit["reviewed_by_attorney_id"] = user_id
    if note is not None:
        hit["review_note"] = note
    bump(hit)

    if matter is not None:
        recompute_clearance(matter)

    # Lateral activation gate: when this review resolved the attorney's
    # last PENDING sweep hit, flip LATERAL_PENDING -> ACTIVE and run the
    # imputation wall cascade.
    if hit["lateral_attorney_id"] is not None:
        maybe_activate_lateral(hit["lateral_attorney_id"])

    return ok_object(hit)
