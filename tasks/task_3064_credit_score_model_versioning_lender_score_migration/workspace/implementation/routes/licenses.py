"""Lending licence endpoints: pricing, entitlement and termination."""

from flask import Blueprint, request

from core import (
    DB, new_record, store, touch, ok, ok_list, resolve_actor, score_variant,
    body_of, reject_unknown, require_fields, as_int, as_str, as_enum,
    read_pagination, paginate, ordered_rows, check_occ, authenticate, authorize,
    month_tuple, MONTH_MIN, LICENSE_WINDOW_MAX,
)
from errors import ApiError
from calculations import marginal_fee_cents, blended_fee_cents, tier_index, fee_through
from services import (
    recompute_license, append_ledger_entry, postings_of_license,
)

bp = Blueprint("licenses", __name__)

ALL_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ScoreConsumer",
]

VOLUME_TIERS = {"VOLUME_TIER_1", "VOLUME_TIER_2", "VOLUME_TIER_3"}

LICENSE_INPUTS = {"lender_name", "lender_code", "score_variant_id", "volume_tier",
                  "entitled_count", "window_start_month", "window_end_month"}


def _model_for_license(license_rec):
    variant = DB["score_variants"][license_rec["score_variant_id"]]
    return DB["score_models"][variant["score_model_id"]]


def _doc_gate_satisfied(license_rec):
    """PRD §2.10: an ADVERSE_ACTION_MAP carrying the licensed model's
    version_label must be FILED or SUPPLEMENTED before termination."""
    model = _model_for_license(license_rec)
    for document in DB["model_documentation"].values():
        if (document["doc_type"] == "ADVERSE_ACTION_MAP"
                and document["required_version_label"] == model["version_label"]
                and document["status"] in ("FILED", "SUPPLEMENTED")):
            return True
    return False


def _terms_overlap(a_start, a_end, b_start, b_end):
    """Half-open month semantics: adjacency is allowed, positive overlap is not."""
    return a_start < b_end and b_start < a_end


@bp.post("/licenses")
def create_license():
    resolve_actor(request, ["ComplianceOfficer"])
    body = body_of(request)
    reject_unknown(body, LICENSE_INPUTS)
    require_fields(body, list(LICENSE_INPUTS))

    lender_name = as_str(body["lender_name"], "lender_name")
    lender_code = as_str(body["lender_code"], "lender_code")
    variant = score_variant(as_str(body["score_variant_id"], "score_variant_id"))
    volume_tier = as_enum(body["volume_tier"], VOLUME_TIERS, "volume_tier")
    entitled_count = as_int(body["entitled_count"])
    window_start_month = as_str(body["window_start_month"], "window_start_month")
    window_end_month = as_str(body["window_end_month"], "window_end_month")

    start = month_tuple(window_start_month)
    end = month_tuple(window_end_month)

    model = DB["score_models"][variant["score_model_id"]]
    if model["status"] == "SUPERSEDED":
        raise ApiError("ERR_MODEL_SUPERSEDED")
    if model["status"] == "RETIRED":
        raise ApiError("ERR_MODEL_RETIRED")
    if model["status"] == "DEPRECATED":
        raise ApiError("ERR_MODEL_DEPRECATED")

    if entitled_count < 0:
        raise ApiError("ERR_INVALID_REQUEST", "entitled_count must be zero or greater.")
    if start < MONTH_MIN:
        raise ApiError("ERR_INVALID_REQUEST", "window_start_month must be no earlier than 2015-01.")
    if not (start < end):
        raise ApiError("ERR_INVALID_REQUEST", "window_start_month must be strictly before window_end_month.")
    if end > LICENSE_WINDOW_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "window_end_month must be no later than 2032-12.")

    for existing in DB["licenses"].values():
        if existing["score_variant_id"] != variant["id"]:
            continue
        # PRD §3.7: "Licence terms for the same lender and variant may not
        # overlap: adjacency is allowed, but any positive overlap is refused with
        # ERR_LICENSE_WINDOW_CONFLICT." The key is the (lender_code, variant)
        # pair, so a different lender is free to open a term inside another
        # lender's window.
        if existing["lender_code"] != lender_code:
            continue
        if _terms_overlap(start, end,
                          month_tuple(existing["window_start_month"]),
                          month_tuple(existing["window_end_month"])):
            raise ApiError("ERR_LICENSE_WINDOW_CONFLICT")

    rec = new_record()
    rec.update({
        "lender_name": lender_name,
        "lender_code": lender_code,
        "score_variant_id": variant["id"],
        "volume_tier": volume_tier,
        "entitled_count": entitled_count,
        "status": "PENDING",
        "entitlement_status": "NOT_SET",
        "cumulative_score_count": 0,
        "cumulative_fee_cents": 0,
        "window_start_month": window_start_month,
        "window_end_month": window_end_month,
        "window_credited_delta_bps": 0,
        "window_outcome_mixture_ratio_ppm": 0,
    })
    store("licenses", rec)
    return ok(rec, 201)


@bp.get("/licenses/<license_id>")
def get_license(license_id):
    role, user_id = authenticate(request)
    authorize(role, ALL_ROLES)
    if role == "ScoreConsumer" and user_id not in DB["licenses"]:
        raise ApiError("ERR_UNAUTHORIZED")
    rec = DB["licenses"].get(license_id)
    if rec is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND")
    if role == "ScoreConsumer" and rec["id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED")
    return ok(rec)


@bp.get("/licenses")
def list_licenses():
    role, user_id = authenticate(request)
    authorize(role, ALL_ROLES)
    if role == "ScoreConsumer" and user_id not in DB["licenses"]:
        raise ApiError("ERR_UNAUTHORIZED")
    limit, offset = read_pagination(request)
    rows = ordered_rows("licenses")

    for param in ("score_variant_id", "status", "lender_code"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]

    if role == "ScoreConsumer":
        rows = [r for r in rows if r["id"] == user_id]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/licenses/<license_id>/activate")
def activate_license(license_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = DB["licenses"].get(license_id)
    if rec is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND")
    body = body_of(request)
    reject_unknown(body, {"expected_license_version"})

    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    model = _model_for_license(rec)
    if model["status"] == "SUPERSEDED":
        raise ApiError("ERR_MODEL_SUPERSEDED")
    if model["status"] == "RETIRED":
        raise ApiError("ERR_MODEL_RETIRED")
    if model["status"] not in ("RELEASED", "DEPRECATED"):
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    check_occ(rec, body, "expected_license_version")

    rec["status"] = "ACTIVE"
    recompute_license(rec, with_count=True)
    touch(rec)
    return ok(rec)


@bp.post("/licenses/<license_id>/suspend")
def suspend_license(license_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = DB["licenses"].get(license_id)
    if rec is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND")
    body = body_of(request)
    reject_unknown(body, {"expected_license_version"})

    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    if not (rec["cumulative_score_count"] > rec["entitled_count"]):
        raise ApiError("ERR_ENTITLEMENT_WITHIN_LIMIT")

    check_occ(rec, body, "expected_license_version")

    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok(rec)


@bp.post("/licenses/<license_id>/reactivate")
def reactivate_license(license_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = DB["licenses"].get(license_id)
    if rec is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND")
    body = body_of(request)
    reject_unknown(body, {"expected_license_version"})

    if rec["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    model = _model_for_license(rec)
    if model["status"] == "SUPERSEDED":
        raise ApiError("ERR_MODEL_SUPERSEDED")
    if model["status"] == "RETIRED":
        raise ApiError("ERR_MODEL_RETIRED")
    if model["status"] not in ("RELEASED", "DEPRECATED"):
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    check_occ(rec, body, "expected_license_version")

    rec["status"] = "ACTIVE"
    # The entitlement axis is left untouched by a reactivation.
    touch(rec)
    return ok(rec)


@bp.post("/licenses/<license_id>/fee-quotes")
def fee_quote(license_id):
    resolve_actor(request, ["ComplianceOfficer", "ScoreConsumer"])
    rec = DB["licenses"].get(license_id)
    if rec is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND")
    body = body_of(request)
    reject_unknown(body, {"prospective_count"})
    require_fields(body, ["prospective_count"])

    prospective_count = as_int(body["prospective_count"])
    if prospective_count < 0:
        raise ApiError("ERR_INVALID_REQUEST", "prospective_count must be zero or greater.")

    # PRD §3.7: "The cumulative charge through any count is the sum, over those
    # bands, of the units falling inside the band multiplied by the band's rate."
    # The what-if quote reports that cumulative charge through the prospective
    # count; it is a pricing-desk read and never a settled amount, so no
    # entitlement overage surcharge is applied.
    marginal = fee_through(prospective_count)

    return ok({
        "marginal_fee_cents": marginal,
        "blended_fee_cents": blended_fee_cents(prospective_count),
        "tier_index": tier_index(prospective_count),
    })


@bp.post("/licenses/<license_id>/terminate")
def terminate_license(license_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = DB["licenses"].get(license_id)
    if rec is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND")
    body = body_of(request)
    reject_unknown(body, {"expected_license_version"})

    if rec["status"] not in ("ACTIVE", "SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    if not _doc_gate_satisfied(rec):
        raise ApiError("ERR_LICENSE_DOC_MISSING")

    self_loop = rec["status"] == "TERMINATED"

    check_occ(rec, body, "expected_license_version")

    rec["status"] = "TERMINATED"
    if self_loop:
        append_ledger_entry(
            rec, None, "VOID_REVERSAL", rec["cumulative_score_count"], 0,
            "Settlement-level entitlement recomputation on licence re-termination.",
        )
    recompute_license(rec, with_count=True)
    rec["entitlement_status"] = ("WITHIN_ENTITLEMENT"
                                 if rec["cumulative_score_count"] <= rec["entitled_count"]
                                 else "OVER_ENTITLED")
    touch(rec)
    return ok(rec)