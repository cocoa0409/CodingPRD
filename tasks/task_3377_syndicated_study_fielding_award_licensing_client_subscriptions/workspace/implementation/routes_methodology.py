"""MethodologyVersion + Factor endpoints: create, get, pin (OCC), factors list,
and per-study version listing."""
from flask import Blueprint, g

from db import store
from envelope import filter_params, ok_object, paginated
from errors import fail
from middleware import ALL_ROLES, require
from records import new_record, ser_factor, ser_methodology, touch
from services import factors_of
from validation import Body

bp = Blueprint("methodology", __name__, url_prefix="/research")

CHANGE_CLASSES = ("FULL_COMPARABLE", "ADJUSTED", "BREAK")


@bp.post("/methodology-versions")
@require("MethodologyLead")
def create_methodology():
    b = Body()
    study_id = b.str_("study_id")
    change_class = b.enum_("change_class", CHANGE_CLASSES)
    change_notes = b.str_("change_notes", required=False)
    min_duration = b.int_("min_duration_seconds")
    sl_items = b.int_("straightline_min_items")
    pooled_sd = b.num_("pooled_sd_1000")
    z_value = b.num_("z_value")
    tie_epsilon = b.num_("tie_epsilon")
    factors = b.list_("factors")
    # existence (priority 3)
    study = store.studies.get(study_id) if study_id is not None else None
    if study_id is not None and study is None:
        fail("ERR_NOT_FOUND", "study_id does not reference an existing study")
    # state (priority 5)
    if study is not None and study["status"] not in ("DRAFT", "DESIGN_LOCKED"):
        fail("ERR_METHODOLOGY_IMMUTABLE", "Methodology create requires study DRAFT or DESIGN_LOCKED")
    # domain (priority 8): per-factor weight bounds
    if factors:
        for f in factors:
            if not isinstance(f, dict):
                b.bad = True
                continue
            w = f.get("weight_bp")
            if isinstance(w, bool) or not isinstance(w, int):
                b.bad = True
            elif w <= 0 or w >= 10000:
                fail("ERR_FACTOR_WEIGHT_INVALID", "factor weight_bp must satisfy 0 < weight_bp < 10000")
    # syntactic (priority 11)
    b.finalize()
    if not factors:
        fail("ERR_INVALID_REQUEST", "factors array must be non-empty")
    if min_duration < 1 or sl_items < 1 or pooled_sd <= 0 or z_value <= 0 or tie_epsilon < 0:
        fail("ERR_INVALID_REQUEST", "methodology knob out of bounds")
    seen_codes = set()
    for f in factors:
        code = f.get("code")
        name = f.get("name")
        ordinal = f.get("ordinal")
        if not isinstance(code, str) or not code or not isinstance(name, str):
            fail("ERR_INVALID_REQUEST", "factor code/name must be strings")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            fail("ERR_INVALID_REQUEST", "factor ordinal must be >= 1")
        if code in seen_codes:
            fail("ERR_INVALID_REQUEST", "factor code duplicated within the methodology version")
        seen_codes.add(code)
    version_no = 1 + sum(1 for m in store.methodology_versions.values() if m["study_id"] == study_id)
    mv = new_record()
    mv.update({
        "study_id": study_id,
        "change_class": change_class,
        "change_notes": change_notes,
        "min_duration_seconds": min_duration,
        "straightline_min_items": sl_items,
        "pooled_sd_1000": pooled_sd,
        "z_value": z_value,
        "tie_epsilon": tie_epsilon,
        "version_no": version_no,
        "status": "DRAFT",
        "pinned_by_user_id": None,
    })
    store.methodology_versions[mv["id"]] = mv
    for f in factors:
        frec = new_record(common=False)
        frec.update({
            "methodology_version_id": mv["id"],
            "code": f["code"],
            "name": f["name"],
            "weight_bp": f["weight_bp"],
            "ordinal": f["ordinal"],
        })
        store.factors[frec["id"]] = frec
    return ok_object(ser_methodology(mv), 201)


@bp.get("/methodology-versions/<mid>")
@require(*ALL_ROLES)
def get_methodology(mid):
    mv = store.methodology_versions.get(mid)
    if mv is None:
        fail("ERR_NOT_FOUND", "Methodology version not found")
    return ok_object(ser_methodology(mv))


@bp.post("/methodology-versions/<mid>/pin")
@require("MethodologyLead")
def pin_methodology(mid):
    mv = store.methodology_versions.get(mid)
    if mv is None:
        fail("ERR_NOT_FOUND", "Methodology version not found")
    study = store.studies.get(mv["study_id"])
    b = Body()
    raw_expected = b.raw("expected_study_version")
    expected_ok = (
        raw_expected is not None
        and isinstance(raw_expected, int)
        and not isinstance(raw_expected, bool)
    )
    # OCC (priority 4)
    if expected_ok and raw_expected != study["version"]:
        fail("ERR_STALE_VERSION", "expected_study_version does not match the study's current version")
    # state (priority 5): parent study first, then the version itself
    if study["status"] not in ("DRAFT", "DESIGN_LOCKED"):
        fail("ERR_METHODOLOGY_IMMUTABLE", "Methodology pin requires study DRAFT or DESIGN_LOCKED")
    if mv["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT methodology version can be pinned")
    # domain (priority 8)
    factors = factors_of(mid)
    if not factors:
        fail("ERR_FACTOR_WEIGHT_INVALID", "Methodology version has no factors")
    for f in factors:
        if not (0 < f["weight_bp"] < 10000):
            fail("ERR_FACTOR_WEIGHT_INVALID", "factor weight_bp out of bounds")
    if sum(f["weight_bp"] for f in factors) != 10000:
        fail("ERR_WEIGHT_SUM_MISMATCH", "Factor weights must sum to exactly 10000")
    # syntactic (priority 11)
    if not expected_ok:
        fail("ERR_INVALID_REQUEST", "expected_study_version is required and must be an integer")
    # apply
    for m in store.methodology_versions.values():
        if m["study_id"] == study["id"] and m["status"] == "PINNED" and m["id"] != mv["id"]:
            m["status"] = "SUPERSEDED"
            touch(m)
    mv["status"] = "PINNED"
    mv["pinned_by_user_id"] = g.user_id
    touch(mv)
    study["active_methodology_id"] = mv["id"]
    if study["status"] == "DRAFT":
        study["status"] = "DESIGN_LOCKED"
    touch(study)  # Study.version += 1
    return ok_object(ser_methodology(mv), 200)


@bp.get("/methodology-versions/<mid>/factors")
@require(*ALL_ROLES)
def list_factors(mid):
    mv = store.methodology_versions.get(mid)
    if mv is None:
        fail("ERR_NOT_FOUND", "Methodology version not found")
    return paginated(factors_of(mid), ser_factor)


@bp.get("/studies/<sid>/methodology-versions")
@require(*ALL_ROLES)
def list_study_methodologies(sid):
    study = store.studies.get(sid)
    if study is None:
        fail("ERR_NOT_FOUND", "Study not found")
    items = [m for m in store.methodology_versions.values() if m["study_id"] == sid]
    items = filter_params(items, ("status",))
    return paginated(items, ser_methodology)
