"""Engine family certification lifecycle (PRD §3.2) + family-scoped lists."""
from flask import Blueprint, request

import calculations
import clock
import store
from cascade import OPEN_CAMPAIGN_STATES
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_num, f_enum, get_or_404, page_args, slice_page,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("engine_families", __name__)

ARCHITECTURES = ("DOC_DPF_SCR", "DOC_DPF_SCR_ASC", "EGR_DOC_DPF_SCR")


def _fam(fid):
    return get_or_404(store.families, fid, "EngineFamily")


def _accepted_coverage(fid):
    """For each of FTP/RMC/SET at least one ACCEPTED run exists."""
    accepted = {t: False for t in calculations.REQUIRED_TEST_TYPES}
    for r in store.test_runs.values():
        if r["engine_family_id"] == fid and r["status"] == "ACCEPTED":
            if r["test_type"] in accepted:
                accepted[r["test_type"]] = True
    return all(accepted.values())


@bp.post("/emissions/engine-families")
def create_family():
    auth(("CertificationEngineer",))
    b = body()
    family_code = f_str(b, "family_code")
    model_year = f_int(b, "model_year")
    std_id = f_str(b, "regulation_standard_id")
    displacement = f_num(b, "displacement_liters")
    architecture = f_enum(b, "architecture", ARCHITECTURES)
    std = get_or_404(store.standards, std_id, "RegulationStandard")
    # state gate (priority 7)
    if std["status"] != "PUBLISHED":
        raise ApiError("ERR_STANDARD_NOT_PUBLISHED", 409,
                       "Referenced standard is not PUBLISHED")
    # referential (priority 10)
    if not (std["effective_model_year_first"] <= model_year
            <= std["effective_model_year_last"]):
        raise ApiError("ERR_MODEL_YEAR_OUTSIDE_STANDARD_WINDOW", 422,
                       "model_year outside the standard's effective window")
    # uniqueness (priority 11): family_code unique per model_year
    for f in store.families.values():
        if f["family_code"] == family_code and f["model_year"] == model_year:
            raise ApiError("ERR_DUPLICATE_FAMILY_CODE", 409,
                           "family_code already exists for model_year %s" % model_year)
    ent = new_entity()
    ent.update({
        "family_code": family_code,
        "model_year": model_year,
        "regulation_standard_id": std["id"],
        "displacement_liters": displacement,
        "architecture": architecture,
        "certification_status": "DESIGN",
        "production_entered": False,
        "in_use_compliance_status": "NOT_TESTED",
        "submitted_by_user_id": None,
        "certified_at": None,
    })
    store.families[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/engine-families")
def list_families():
    auth(ANY)
    limit, offset = page_args()
    items = list(store.families.values())
    std_id = request.args.get("regulation_standard_id")
    if std_id is not None:
        items = [f for f in items if f["regulation_standard_id"] == std_id]
    status = request.args.get("certification_status")
    if status is not None:
        items = [f for f in items if f["certification_status"] == status]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.get("/emissions/engine-families/<fid>")
def get_family(fid):
    auth(ANY)
    return envelope_ok(ser(_fam(fid)), 200)


@bp.post("/emissions/engine-families/<fid>/begin-testing")
def begin_testing(fid):
    auth(("CertificationEngineer",))
    fam = _fam(fid)
    if fam["certification_status"] != "DESIGN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "begin-testing requires DESIGN")
    if not any(s["engine_family_id"] == fid and s["status"] == "ACTIVE"
               for s in store.specs.values()):
        raise ApiError("ERR_NO_ACTIVE_AFTERTREATMENT_SPEC", 409,
                       "An ACTIVE aftertreatment spec is required")
    fam["certification_status"] = "TESTING"
    touch(fam)
    return envelope_ok(ser(fam), 200)


@bp.post("/emissions/engine-families/<fid>/submit-review")
def submit_review(fid):
    uid, _ = auth(("CertificationEngineer",))
    fam = _fam(fid)
    if fam["certification_status"] != "TESTING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "submit-review requires TESTING")
    if not _accepted_coverage(fid):
        raise ApiError("ERR_REQUIRED_TEST_MISSING", 409,
                       "An ACCEPTED run is required for each of FTP, RMC, SET")
    fam["certification_status"] = "UNDER_REVIEW"
    fam["submitted_by_user_id"] = uid
    touch(fam)
    return envelope_ok(ser(fam), 200)


@bp.post("/emissions/engine-families/<fid>/return-to-testing")
def return_to_testing(fid):
    auth(("CertificationEngineer",))
    fam = _fam(fid)
    if fam["certification_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "return-to-testing requires UNDER_REVIEW")
    fam["certification_status"] = "TESTING"
    touch(fam)
    return envelope_ok(ser(fam), 200)


@bp.post("/emissions/engine-families/<fid>/certify")
def certify(fid):
    uid, _ = auth(("RegulatoryOfficer",))
    fam = _fam(fid)
    # segregation of duties (priority 6); passes when submitted_by_user_id is null
    if fam["submitted_by_user_id"] is not None and fam["submitted_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The certifier must differ from the submitter")
    # state gates (priority 7)
    if fam["certification_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "certify requires UNDER_REVIEW")
    std = store.standards.get(fam["regulation_standard_id"])
    if std is None or std["status"] != "PUBLISHED":
        raise ApiError("ERR_STANDARD_NOT_PUBLISHED", 409,
                       "The family's standard is no longer PUBLISHED")
    # accepted coverage still holds at this instant (priority 11)
    if not _accepted_coverage(fid):
        raise ApiError("ERR_REQUIRED_TEST_MISSING", 409,
                       "ACCEPTED coverage for FTP, RMC, SET no longer holds")
    fam["certification_status"] = "CERTIFIED"
    fam["certified_at"] = clock.now_dt()
    touch(fam)
    return envelope_ok(ser(fam), 200)


@bp.post("/emissions/engine-families/<fid>/enter-production")
def enter_production(fid):
    auth(("RegulatoryOfficer",))
    fam = _fam(fid)
    if fam["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "enter-production requires CERTIFIED")
    fam["certification_status"] = "IN_PRODUCTION"
    fam["production_entered"] = True
    touch(fam)
    return envelope_ok(ser(fam), 200)


@bp.post("/emissions/engine-families/<fid>/phase-out")
def phase_out(fid):
    auth(("RegulatoryOfficer",))
    fam = _fam(fid)
    if fam["certification_status"] not in ("IN_PRODUCTION", "COMPLIANCE_HOLD"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "phase-out requires IN_PRODUCTION or COMPLIANCE_HOLD")
    if any(c["engine_family_id"] == fid and c["status"] in OPEN_CAMPAIGN_STATES
           for c in store.campaigns.values()):
        raise ApiError("ERR_CAMPAIGN_STILL_OPEN", 409,
                       "An open campaign blocks phase-out")
    fam["certification_status"] = "PHASED_OUT"
    touch(fam)
    return envelope_ok(ser(fam), 200)


# --- family-scoped list endpoints ---

def _scoped_list(fid, mapping, key):
    auth(ANY)
    limit, offset = page_args()
    _fam(fid)
    items = [e for e in mapping.values() if e[key] == fid]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.get("/emissions/engine-families/<fid>/aftertreatment-specs")
def family_specs(fid):
    return _scoped_list(fid, store.specs, "engine_family_id")


@bp.get("/emissions/engine-families/<fid>/test-runs")
def family_test_runs(fid):
    return _scoped_list(fid, store.test_runs, "engine_family_id")


@bp.get("/emissions/engine-families/<fid>/engine-units")
def family_units(fid):
    return _scoped_list(fid, store.units, "engine_family_id")


@bp.get("/emissions/engine-families/<fid>/field-campaigns")
def family_campaigns(fid):
    return _scoped_list(fid, store.campaigns, "engine_family_id")


@bp.get("/emissions/engine-families/<fid>/in-use-results")
def family_in_use_results(fid):
    return _scoped_list(fid, store.in_use_results, "engine_family_id")
