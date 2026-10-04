"""Registry configuration: LevelDefinition and StateAdoptionPolicy (PRD §3.1).
Both are configuration rows carrying only id + created_at (no version)."""

from flask import Blueprint, request

from db import STORE, base_entity, serialize
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, opt_bool,
                        opt_int, opt_list, req_enum, req_int, req_number, req_str)

bp = Blueprint("config", __name__)

LEVEL_CODES = ["EMR", "EMT", "AEMT", "PARAMEDIC"]
ADOPTION_MODES = ["NREMT_ACCEPTED", "STATE_EXAM", "HYBRID"]


# --- LevelDefinition -------------------------------------------------------

@bp.post("/registry/level-definitions")
def create_level():
    authn(["RegistryAdmin"])
    b = body()
    code = req_enum(b, "code", LEVEL_CODES)
    display_name = req_str(b, "display_name")
    scope_summary = req_str(b, "scope_summary")
    cut = req_number(b, "cognitive_cut_score")
    if not (0 <= float(cut) <= 1):
        raise_err("ERR_INVALID_REQUEST", "cognitive_cut_score must be between 0 and 1")
    ce_total = req_number(b, "ce_total_hours")
    ce_national = req_number(b, "ce_national_min_hours")
    ce_local = req_number(b, "ce_local_min_hours")
    ce_individual = req_number(b, "ce_individual_min_hours")
    hourly_total = req_number(b, "hourly_model_total_hours")
    remedial = req_number(b, "remedial_hours_required")
    refresher = req_number(b, "refresher_hours_required")
    initial_fee = req_int(b, "initial_application_fee_cents")
    recert_fee = req_int(b, "recert_application_fee_cents")

    for lv in STORE.levels.values():
        if lv["code"] == code:
            raise_err("ERR_DUPLICATE_LEVEL_CODE",
                      "A LevelDefinition with code %s already exists" % code)

    e = base_entity(common=False)
    e.update({
        "code": code,
        "display_name": display_name,
        "scope_summary": scope_summary,
        "cognitive_cut_score": cut,
        "ce_total_hours": ce_total,
        "ce_national_min_hours": ce_national,
        "ce_local_min_hours": ce_local,
        "ce_individual_min_hours": ce_individual,
        "hourly_model_total_hours": hourly_total,
        "remedial_hours_required": remedial,
        "refresher_hours_required": refresher,
        "initial_application_fee_cents": initial_fee,
        "recert_application_fee_cents": recert_fee,
    })
    STORE.levels[e["id"]] = e
    return ok_object(serialize(e), 201)


@bp.get("/registry/level-definitions")
def list_levels():
    authn(ALL_AUTHENTICATED_ROLES)
    code = request.args.get("code")
    items = [e for e in STORE.levels.values() if code is None or e["code"] == code]
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(e) for e in page], total, limit, offset)


# --- StateAdoptionPolicy ---------------------------------------------------

@bp.post("/registry/state-adoption-policies")
def create_policy():
    authn(["RegistryAdmin"])
    b = body()
    state_code = req_str(b, "state_code")
    adoption_mode = req_enum(b, "adoption_mode", ADOPTION_MODES)
    accepted = opt_list(b, "accepted_level_codes", None)
    if accepted is not None and not all(isinstance(x, str) for x in accepted):
        raise_err("ERR_INVALID_REQUEST", "accepted_level_codes must be an array of strings")
    jurisprudence = opt_bool(b, "jurisprudence_exam_required", False)
    base_fee = req_int(b, "base_license_fee_cents")
    surcharge = opt_int(b, "national_verification_surcharge_cents", 0)
    state_exam_fee = opt_int(b, "state_exam_fee_cents", 0)
    share_bps = opt_int(b, "registry_share_bps", 1500)

    for p in STORE.policies.values():
        if p["state_code"] == state_code:
            raise_err("ERR_DUPLICATE_STATE_POLICY",
                      "A StateAdoptionPolicy for %s already exists" % state_code)

    e = base_entity(common=False)
    e.update({
        "state_code": state_code,
        "adoption_mode": adoption_mode,
        "accepted_level_codes": accepted,
        "jurisprudence_exam_required": jurisprudence,
        "base_license_fee_cents": base_fee,
        "national_verification_surcharge_cents": surcharge,
        "state_exam_fee_cents": state_exam_fee,
        "registry_share_bps": share_bps,
    })
    STORE.policies[e["id"]] = e
    return ok_object(serialize(e), 201)


@bp.get("/registry/state-adoption-policies")
def list_policies():
    authn(ALL_AUTHENTICATED_ROLES)
    state_code = request.args.get("state_code")
    items = [e for e in STORE.policies.values()
             if state_code is None or e["state_code"] == state_code]
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(e) for e in page], total, limit, offset)
