"""CertificationCampaign endpoints and conformity scoring (PRD 3.2).

Two stored score variants recomputed on every mutation; the FINAL_AUDIT
variant is additionally evaluated fresh at certify time against the logical
clock and is the only gate (>= CONFORMITY_PASS_BP).
"""
from flask import Blueprint

from auth import auth_context, peek_to_state, require_role, require_transition_actor
from constants import (
    BP_SCALE,
    CONFORMITY_PASS_BP,
    FINAL_AGING_BP_PER_WEEK,
    FINAL_CRITICAL_WEIGHT,
    FINAL_MAJOR_WEIGHT,
    FINAL_MINOR_WEIGHT,
    FINAL_RESUBMISSION_PENALTY,
    SCREEN_CRITICAL_WEIGHT,
    SCREEN_MAJOR_WEIGHT,
    SCREEN_MINOR_WEIGHT,
    SCREEN_RESUBMISSION_PENALTY,
)
from domains.certificates import mint_certificate
from envelope import apply_filters, list_page, ok_object
from errors import err_forbidden_ownership, err_invalid_state, err_not_found, raise_err
from store import db
from util import now, stamp_new, touch
from validation import body_json, no_extra, opt_state_code, req_enum, req_int, req_str

bp = Blueprint("campaigns", __name__)

GUIDELINES = {"VVSG_1_1", "VVSG_2_0"}
CAMPAIGN_STATES = {"SUBMITTED", "IN_TEST", "DEFICIENCIES_FILED", "CERTIFIED", "DENIED", "WITHDRAWN"}
CAMPAIGN_ACTORS = {
    "IN_TEST": {"LabAgent"},
    "DEFICIENCIES_FILED": {"LabAgent"},
    "SUBMITTED": {"VendorRep"},
    "CERTIFIED": {"CertificationAuthority"},
    "DENIED": {"CertificationAuthority"},
    "WITHDRAWN": {"VendorRep"},
}
CAMPAIGN_FROM = {
    "IN_TEST": {"SUBMITTED"},
    "DEFICIENCIES_FILED": {"IN_TEST"},
    "SUBMITTED": {"DEFICIENCIES_FILED"},
    "CERTIFIED": {"IN_TEST"},
    "DENIED": {"DEFICIENCIES_FILED"},
    "WITHDRAWN": {"SUBMITTED", "DEFICIENCIES_FILED"},
}
ACTIVE_CAMPAIGN_STATES = {"SUBMITTED", "IN_TEST", "DEFICIENCIES_FILED"}


def recompute_conformity(camp):
    screen = (
        BP_SCALE
        - SCREEN_CRITICAL_WEIGHT * camp["open_critical_count"]
        - SCREEN_MAJOR_WEIGHT * camp["open_major_count"]
        - SCREEN_MINOR_WEIGHT * camp["open_minor_count"]
        - SCREEN_RESUBMISSION_PENALTY * camp["resubmission_count"]
    )
    camp["conformity_screen_bp"] = max(0, screen)
    days_open = int((now() - camp["last_submitted_at"]).total_seconds() // 86400)
    aging = FINAL_AGING_BP_PER_WEEK * (days_open // 7)
    final = (
        BP_SCALE
        - FINAL_CRITICAL_WEIGHT * camp["open_critical_count"]
        - FINAL_MAJOR_WEIGHT * camp["open_major_count"]
        - FINAL_MINOR_WEIGHT * camp["open_minor_count"]
        - FINAL_RESUBMISSION_PENALTY * camp["resubmission_count"]
        - aging
    )
    camp["conformity_final_bp"] = max(0, final)


@bp.post("/evote/certification-campaigns")
def create_campaign():
    _, role = auth_context()
    require_role(role, {"VendorRep"})
    body = body_json()
    no_extra(body, {"voting_system_id", "lab_id", "guidelines_baseline", "state_code"})
    system_id = req_str(body, "voting_system_id")
    lab_id = req_str(body, "lab_id")
    baseline = req_enum(body, "guidelines_baseline", GUIDELINES)
    state_code = opt_state_code(body, "state_code")
    system = db.voting_systems.get(system_id)
    if system is None:
        raise_err("ERR_SYSTEM_NOT_FOUND", 404, "voting_system_id does not resolve")
    lab = db.test_laboratories.get(lab_id)
    if lab is None:
        raise_err("ERR_LAB_NOT_FOUND", 404, "lab_id does not resolve")
    for c in db.certification_campaigns.values():
        if c["voting_system_id"] == system_id and c["status"] in ACTIVE_CAMPAIGN_STATES:
            raise_err("ERR_CAMPAIGN_ALREADY_ACTIVE", 409, "system already has an active campaign")
    if lab["status"] != "ACCREDITED":
        raise_err("ERR_LAB_SUSPENDED", 422, "laboratory is not ACCREDITED")
    if state_code is not None:
        if lab["accreditation_scope"] not in {"STATE", "DUAL"}:
            raise_err("ERR_LAB_SCOPE_MISMATCH", 422, "lab scope does not cover a state campaign")
    else:
        if lab["accreditation_scope"] not in {"FEDERAL", "DUAL"}:
            raise_err("ERR_LAB_SCOPE_MISMATCH", 422, "lab scope does not cover a federal campaign")
    if system["status"] == "RETIRED":
        raise_err("ERR_SYSTEM_RETIRED", 422, "voting system is RETIRED")
    rec = stamp_new({})
    rec.update({
        "voting_system_id": system_id,
        "lab_id": lab_id,
        "guidelines_baseline": baseline,
        "state_code": state_code,
        "status": "SUBMITTED",
        "resubmission_count": 0,
        "open_critical_count": 0,
        "open_major_count": 0,
        "open_minor_count": 0,
        "conformity_screen_bp": BP_SCALE,
        "conformity_final_bp": BP_SCALE,
        "last_submitted_at": now(),
        "completed_at": None,
    })
    db.certification_campaigns[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/evote/certification-campaigns")
def list_campaigns():
    auth_context()
    items = apply_filters(
        list(db.certification_campaigns.values()),
        {"voting_system_id", "lab_id", "status"},
    )
    return list_page(items)


def get_campaign_or_404(campaign_id):
    camp = db.certification_campaigns.get(campaign_id)
    if camp is None:
        err_not_found("certification campaign not found")
    return camp


@bp.get("/evote/certification-campaigns/<campaign_id>")
def get_campaign(campaign_id):
    auth_context()
    return ok_object(get_campaign_or_404(campaign_id), 200)


@bp.post("/evote/certification-campaigns/<campaign_id>/transitions")
def campaign_transition(campaign_id):
    uid, role = auth_context()
    require_role(role, {"LabAgent", "VendorRep", "CertificationAuthority"})
    ts = peek_to_state()
    require_transition_actor(role, ts, CAMPAIGN_ACTORS)
    camp = get_campaign_or_404(campaign_id)
    body = body_json()
    no_extra(body, {
        "to_state",
        "critical_count", "major_count", "minor_count",
        "resolved_critical", "resolved_major", "resolved_minor",
    })
    to_state = req_enum(body, "to_state", CAMPAIGN_STATES)
    crit = maj = mnr = rc = rm = rn = None
    if to_state == "DEFICIENCIES_FILED":
        crit = req_int(body, "critical_count", minv=0)
        maj = req_int(body, "major_count", minv=0)
        mnr = req_int(body, "minor_count", minv=0)
    elif to_state == "SUBMITTED":
        rc = req_int(body, "resolved_critical", minv=0)
        rm = req_int(body, "resolved_major", minv=0)
        rn = req_int(body, "resolved_minor", minv=0)
    lab = db.test_laboratories.get(camp["lab_id"])
    # Priority 6: entity-backed LabAgent ownership.
    if CAMPAIGN_ACTORS[to_state] == {"LabAgent"} and uid != camp["lab_id"]:
        err_forbidden_ownership("X-User-ID must equal the campaign's lab_id")
    # Priority 8: state legality.
    if camp["status"] not in CAMPAIGN_FROM[to_state]:
        err_invalid_state("campaign cannot transition from %s to %s" % (camp["status"], to_state))
    # Priority 14: lab aggregate capacity.
    if to_state == "IN_TEST":
        in_test = sum(
            1 for c in db.certification_campaigns.values()
            if c["lab_id"] == camp["lab_id"] and c["status"] == "IN_TEST"
        )
        if in_test >= lab["max_concurrent_campaigns"]:
            raise_err("ERR_LAB_CAPACITY_EXCEEDED", 409, "lab has no free IN_TEST capacity")
    # Priority 15: deficiency arithmetic.
    if to_state == "DEFICIENCIES_FILED" and crit + maj + mnr < 1:
        raise_err("ERR_DEFICIENCY_COUNTS_INVALID", 422, "deficiency total must be at least 1")
    if to_state == "SUBMITTED" and not (
        rc == camp["open_critical_count"]
        and rm == camp["open_major_count"]
        and rn == camp["open_minor_count"]
    ):
        raise_err("ERR_DEFICIENCY_COUNTS_INVALID", 422, "resolved counts must equal open counts")
    if to_state == "DENIED" and camp["open_critical_count"] < 1:
        raise_err("ERR_DEFICIENCY_COUNTS_INVALID", 422, "denial requires an open critical deficiency")
    # Priority 19: referenced-entity state.
    if to_state in {"IN_TEST", "CERTIFIED"} and lab["status"] != "ACCREDITED":
        raise_err("ERR_LAB_SUSPENDED", 422, "laboratory is not ACCREDITED")
    if to_state == "CERTIFIED":
        recompute_conformity(camp)  # fresh FINAL_AUDIT evaluation at the clock
        if camp["open_critical_count"] or camp["open_major_count"] or camp["open_minor_count"]:
            raise_err("ERR_CONFORMITY_BELOW_THRESHOLD", 422, "open deficiencies remain")
        if camp["conformity_final_bp"] < CONFORMITY_PASS_BP:
            raise_err("ERR_CONFORMITY_BELOW_THRESHOLD", 422, "final-audit conformity below 8000 bp")
    # Apply.
    if to_state == "DEFICIENCIES_FILED":
        camp["open_critical_count"] += crit
        camp["open_major_count"] += maj
        camp["open_minor_count"] += mnr
        recompute_conformity(camp)
    elif to_state == "SUBMITTED":
        camp["open_critical_count"] = 0
        camp["open_major_count"] = 0
        camp["open_minor_count"] = 0
        camp["resubmission_count"] += 1
        camp["last_submitted_at"] = now()
        recompute_conformity(camp)
    elif to_state == "CERTIFIED":
        camp["completed_at"] = now()
        mint_certificate(camp)
        system = db.voting_systems.get(camp["voting_system_id"])
        if system is not None and system["status"] == "REGISTERED":
            system["status"] = "FIELDED"
            touch(system)
        recompute_conformity(camp)
    elif to_state in {"DENIED", "WITHDRAWN"}:
        camp["completed_at"] = now()
    camp["status"] = to_state
    recompute_conformity(camp)  # PRD 3.2: both variants recomputed on every campaign mutation
    touch(camp)
    return ok_object(camp, 200)
