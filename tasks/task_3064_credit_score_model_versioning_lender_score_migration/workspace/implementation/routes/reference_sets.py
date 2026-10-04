"""Reference set endpoints: compilation, binding and the catalogue cascade entry."""

from flask import Blueprint, request

from core import (
    DB, new_record, store, touch, ok, ok_list, resolve_actor, consumer, score_model,
    reference_set, reason_code, score_result, body_of, reject_unknown, require_fields,
    as_str, read_pagination, paginate, ordered_rows, check_occ, score_variant,
)
from errors import ApiError
from services import derive_posting, postings_of_reference_set, variants_of_model

bp = Blueprint("reference_sets", __name__)

READ_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ScoreConsumer",
]


def _code_belongs_to_model(code, model_id):
    variant = DB["score_variants"].get(code["score_variant_id"])
    return variant is not None and variant["score_model_id"] == model_id


@bp.post("/reference-sets")
def create_reference_set():
    resolve_actor(request, ["FairLendingOfficer"])
    body = body_of(request)
    reject_unknown(body, {"consumer_id", "score_model_id", "score_result_id"})
    require_fields(body, ["consumer_id", "score_model_id"])

    consumer_rec = consumer(as_str(body["consumer_id"], "consumer_id"))
    model = score_model(as_str(body["score_model_id"], "score_model_id"))
    score_result_id = body.get("score_result_id")

    anchored = None
    if score_result_id is not None:
        anchored = score_result(as_str(score_result_id, "score_result_id"))
        if anchored["consumer_id"] != consumer_rec["id"]:
            raise ApiError("ERR_REFERENCE_SET_CONSUMER_MISMATCH")
        variant = score_variant(anchored["score_variant_id"])
        if variant["score_model_id"] != model["id"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "The posting's variant does not belong to the reference set's model version.")

    rec = new_record()
    rec.update({
        "consumer_id": consumer_rec["id"],
        "score_model_id": model["id"],
        "reason_code_id": None,
        "status": "COMPILED",
    })
    store("reference_sets", rec)

    if anchored is not None:
        anchored["reference_set_id"] = rec["id"]
        derive_posting(anchored)
        touch(anchored)
    return ok(rec, 201)


@bp.get("/reference-sets/<reference_set_id>")
def get_reference_set(reference_set_id):
    resolve_actor(request, READ_ROLES)
    return ok(reference_set(reference_set_id))


@bp.get("/reference-sets")
def list_reference_sets():
    resolve_actor(request, READ_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("reference_sets")

    for param in ("consumer_id", "score_model_id", "reason_code_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/reference-sets/<reference_set_id>/attach-reason-code")
def attach_reason_code(reference_set_id):
    resolve_actor(request, ["FairLendingOfficer"])
    refset = reference_set(reference_set_id)
    body = body_of(request)
    reject_unknown(body, {"reason_code_id", "expected_reference_set_version"})
    require_fields(body, ["reason_code_id"])

    # PRD §2.12: resource resolution (the named reason code in the body) precedes
    # every state and business rule, so a nameable-but-unallocated code surfaces
    # as ERR_REASON_CODE_NOT_FOUND rather than as the state conflict the target
    # set would otherwise provoke.
    code = reason_code(as_str(body["reason_code_id"], "reason_code_id"))

    # A RECONCILED set has already bound and unbound its code, so its bind_count
    # is spent: attaching the same code again is refused with
    # ERR_REASON_CODE_REUSE_LIMIT (PRD §3.6) rather than reopened.
    if refset["status"] == "BOUND" and code["id"] == refset["reason_code_id"]:
        raise ApiError("ERR_REASON_CODE_REUSE_LIMIT")

    # A RECONCILED set has already bound and unbound its code, so its bind_count
    # is spent: attaching the same code again is refused with
    # ERR_REASON_CODE_REUSE_LIMIT (PRD §3.6) rather than reopened.
    if refset["status"] == "BOUND" and code["id"] == refset["reason_code_id"]:
        raise ApiError("ERR_REASON_CODE_REUSE_LIMIT")

    if refset["status"] != "COMPILED":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    model = score_model(refset["score_model_id"])
    if model["status"] not in ("DEPRECATED", "RELEASED"):
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    if code["status"] != "ACTIVE":
        raise ApiError("ERR_REASON_CODE_ARCHIVED")
    if not _code_belongs_to_model(code, refset["score_model_id"]):
        raise ApiError("ERR_REASON_CODE_VARIANT_MISMATCH")
    if code["bind_count"] + 1 >= 2:
        raise ApiError("ERR_REASON_CODE_REUSE_LIMIT")

    check_occ(refset, body, "expected_reference_set_version")

    refset["status"] = "BOUND"
    refset["reason_code_id"] = code["id"]
    code["bind_count"] = code["bind_count"] + 1
    touch(code)

    # Hop 1 of C10
    for posting in postings_of_reference_set(refset["id"]):
        derive_posting(posting)
        touch(posting)

    touch(refset)
    return ok(refset)


@bp.post("/reference-sets/<reference_set_id>/detach-reason-code")
def detach_reason_code(reference_set_id):
    resolve_actor(request, ["FairLendingOfficer"])
    refset = reference_set(reference_set_id)
    body = body_of(request)
    reject_unknown(body, {"expected_reference_set_version"})

    if refset["status"] != "BOUND":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    check_occ(refset, body, "expected_reference_set_version")

    refset["status"] = "COMPILED"
    refset["reason_code_id"] = None
    for posting in postings_of_reference_set(refset["id"]):
        posting["decision"] = "UNDECIDED"
        posting["decision_reason_code_id"] = None
        touch(posting)
    touch(refset)
    return ok(refset)


@bp.post("/reference-sets/<reference_set_id>/reconcile")
def reconcile_reference_set(reference_set_id):
    resolve_actor(request, ["FairLendingOfficer"])
    refset = reference_set(reference_set_id)
    body = body_of(request)
    reject_unknown(body, {"expected_reference_set_version"})

    if refset["status"] != "BOUND":
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")
    code = DB["reason_codes"].get(refset["reason_code_id"])
    if code is None or code["status"] != "ARCHIVED":
        raise ApiError("ERR_REASON_CODE_ACTIVE")

    check_occ(refset, body, "expected_reference_set_version")

    refset["status"] = "RECONCILED"
    refset["reason_code_id"] = None
    for posting in postings_of_reference_set(refset["id"]):
        posting["decision"] = "UNDECIDED"
        posting["decision_reason_code_id"] = None
        touch(posting)
    touch(refset)
    return ok(refset)