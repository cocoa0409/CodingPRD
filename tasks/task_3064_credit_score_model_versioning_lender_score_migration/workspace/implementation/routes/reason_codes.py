"""Reason-code catalogue endpoints: minting, archiving and restoration."""

from decimal import Decimal

from flask import Blueprint, request

from core import (
    DB, new_record, store, touch, ok, ok_list, resolve_actor, score_variant,
    reason_code, body_of, reject_unknown, require_fields, as_str, as_enum, as_number,
    read_pagination, paginate, ordered_rows, dec_out, half_up,
)
from errors import ApiError
from calculations import composite_code_for, weight_effective
from services import (
    recompute_reason_code_weights,
    c10_affected_reference_sets, freeze_plan_for_archive, apply_c10,
    append_ledger_entry,
)

bp = Blueprint("reason_codes", __name__)

ALL_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ReasonCodeAdministrator", "ScoreConsumer",
]

DEPTH_TIERS = {"PRIMARY", "SECONDARY", "TERTIARY"}


@bp.post("/reason-codes")
def create_reason_code():
    resolve_actor(request, ["ReasonCodeAdministrator"])
    body = body_of(request)
    reject_unknown(body, {"score_variant_id", "depth_tier", "trigger_feature_code",
                          "code_label", "weight_pct", "parent_reason_code_id"})
    require_fields(body, ["score_variant_id", "depth_tier", "trigger_feature_code",
                          "code_label", "weight_pct"])

    variant = score_variant(as_str(body["score_variant_id"], "score_variant_id"))
    depth_tier = as_enum(body["depth_tier"], DEPTH_TIERS, "depth_tier")
    trigger_feature_code = as_str(body["trigger_feature_code"], "trigger_feature_code")
    code_label = as_str(body["code_label"], "code_label")
    weight_pct = as_number(body["weight_pct"])
    parent_reason_code_id = body.get("parent_reason_code_id")

    if weight_pct <= 0 or weight_pct > 1:
        raise ApiError("ERR_INVALID_REQUEST", "weight_pct must be greater than 0 and at most 1.")
    if weight_pct < Decimal("0.0001"):
        raise ApiError("ERR_INVALID_REQUEST", "weight_pct must be expressible to four decimal places.")

    parent = None
    if parent_reason_code_id is not None:
        parent = reason_code(as_str(parent_reason_code_id, "parent_reason_code_id"))

    for existing in DB["reason_codes"].values():
        if existing["score_variant_id"] == variant["id"] and existing["code_label"] == code_label:
            raise ApiError("ERR_DUPLICATE_CODE_LABEL")

    if parent is not None and parent["score_variant_id"] != variant["id"]:
        raise ApiError("ERR_REASON_CODE_VARIANT_MISMATCH")

    model = DB["score_models"][variant["score_model_id"]]
    composite_code = composite_code_for(variant, model, trigger_feature_code, depth_tier)

    for existing in DB["reason_codes"].values():
        if (existing["score_variant_id"] == variant["id"]
                and existing["composite_code"] == composite_code
                and existing["status"] != "ARCHIVED"):
            raise ApiError("ERR_COMPOSITE_CODE_DUPLICATE")

    rec = new_record()
    rec.update({
        "score_variant_id": variant["id"],
        "depth_tier": depth_tier,
        "trigger_feature_code": trigger_feature_code,
        "code_label": code_label,
        "composite_code": composite_code,
        "weight_pct": float(weight_pct),
        "weight_received_pct": 0.0,
        "weight_effective_pct": 0.0,
        "parent_reason_code_id": parent["id"] if parent else None,
        "status": "ACTIVE",
        "bind_count": 0,
        "archived_consumed_entitlement_snapshot": 0,
    })
    store("reason_codes", rec)
    recompute_reason_code_weights(rec)
    if parent is not None:
        recompute_reason_code_weights(parent)
    return ok(rec, 201)


@bp.get("/reason-codes/<reason_code_id>")
def get_reason_code(reason_code_id):
    resolve_actor(request, ALL_ROLES)
    return ok(reason_code(reason_code_id))


@bp.get("/reason-codes")
def list_reason_codes():
    resolve_actor(request, ALL_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("reason_codes")

    for param in ("score_variant_id", "parent_reason_code_id", "depth_tier", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


def _fee_accruing_count_for_variant(variant_id):
    """Non-VOIDED postings accruing fees under licences licensed on this variant."""
    license_ids = {lic["id"] for lic in DB["licenses"].values()
                   if lic["score_variant_id"] == variant_id}
    count = 0
    for posting in DB["score_results"].values():
        if posting.get("_voided"):
            continue
        if posting["license_id"] in license_ids:
            count += 1
    return count


@bp.post("/reason-codes/<reason_code_id>/archive")
def archive_reason_code(reason_code_id):
    resolve_actor(request, ["ReasonCodeAdministrator"])
    code = reason_code(reason_code_id)
    body = body_of(request)
    reject_unknown(body, set())

    if code["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    for child in DB["reason_codes"].values():
        if child.get("parent_reason_code_id") == code["id"] and child["status"] == "ACTIVE":
            raise ApiError("ERR_REASON_CODE_ARCHIVED")
    if code["bind_count"] >= 2:
        raise ApiError("ERR_REASON_CODE_REUSE_LIMIT")

    refsets = c10_affected_reference_sets(code["id"])
    frozen = freeze_plan_for_archive(refsets)

    code["status"] = "ARCHIVED"
    code["archived_consumed_entitlement_snapshot"] = _fee_accruing_count_for_variant(code["score_variant_id"])
    touch(code)

    # Bubble-up: this node's weight routes to its parent when it is below the floor.
    parent = DB["reason_codes"].get(code.get("parent_reason_code_id"))
    if parent is not None:
        recompute_reason_code_weights(parent)

    apply_c10(refsets, frozen)
    return ok(code)


@bp.post("/reason-codes/<reason_code_id>/restore")
def restore_reason_code(reason_code_id):
    resolve_actor(request, ["ReasonCodeAdministrator"])
    code = reason_code(reason_code_id)
    body = body_of(request)
    reject_unknown(body, set())

    if code["status"] != "ARCHIVED":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    for existing in DB["reason_codes"].values():
        if (existing["id"] != code["id"]
                and existing["score_variant_id"] == code["score_variant_id"]
                and existing["composite_code"] == code["composite_code"]
                and existing["status"] == "ACTIVE"):
            raise ApiError("ERR_COMPOSITE_CODE_DUPLICATE")
    parent = DB["reason_codes"].get(code.get("parent_reason_code_id"))
    if parent is not None and parent["status"] != "ACTIVE":
        raise ApiError("ERR_REASON_CODE_ARCHIVED")

    code["status"] = "ACTIVE"
    touch(code)

    # weight_received_pct re-derived from ARCHIVED descendants below the floor.
    recompute_reason_code_weights(code)
    if parent is not None:
        recompute_reason_code_weights(parent)
    for ancestor in DB["reason_codes"].values():
        if ancestor.get("parent_reason_code_id") == code["id"]:
            recompute_reason_code_weights(ancestor)

    # Hop 2 of C11: re-consume the archived snapshot on each licence for this variant.
    current = _fee_accruing_count_for_variant(code["score_variant_id"])
    snapshot = code["archived_consumed_entitlement_snapshot"]
    variant_licenses = [lic for lic in DB["licenses"].values()
                        if lic["score_variant_id"] == code["score_variant_id"]]
    if variant_licenses:
        total = sum(lic["cumulative_score_count"] for lic in variant_licenses)
        if current != snapshot or total != snapshot:
            for lic in variant_licenses:
                if lic["cumulative_score_count"] != snapshot:
                    append_ledger_entry(
                        lic, None, "VOID_REVERSAL",
                        lic["cumulative_score_count"], 0,
                        f"Settlement-level entitlement reversal for reason code {code['id']}.",
                    )
                    recompute_from_ledger(lic)
                    touch(lic)
    return ok(code)


def recompute_from_ledger(lic):
    from services import recompute_license_ledger
    recompute_license_ledger(lic)