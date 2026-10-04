"""Score posting endpoints: settlement, the cut-off snapshot and discrepancy reads."""

from flask import Blueprint, request

from core import (
    DB, ORDER, new_record, store, touch, ok, ok_list, resolve_actor, consumer,
    score_variant, bureau as get_bureau, license_rec as get_license, score_result,
    body_of, reject_unknown, require_fields, as_int, as_str, read_pagination,
    paginate, ordered_rows, check_occ, authenticate, authorize,
)
from errors import ApiError
from calculations import bureau_discrepancy_scan
from services import (
    derive_posting, latest_reference_set, lowest_composite_primary_reason_code,
    accrue_marginal, recompute_consumer, recompute_license_window,
    recompute_license_ledger, append_ledger_entry, recompute_reason_code_weights,
)

bp = Blueprint("score_results", __name__)

ALL_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ScoreConsumer",
]

DISCREPANCY_ROLES = [
    "BureauAdministrator", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ScoreConsumer",
]


def _eligible_migration_event(license_id, lender_code, variant):
    """The earliest unconsumed, unvoided event for this lender on this variant."""
    candidates = [
        e for e in ordered_rows("migration_events")
        if e["lender_code"] == lender_code
        and e["to_score_variant_id"] == variant["id"]
        and e.get("_consumed_by_license_id") is None
        and e["voided_at"] is None
    ]
    if not candidates:
        return None
    return candidates[0]


@bp.post("/score-results")
def create_score_result():
    role, user_id = authenticate(request)
    authorize(role, ["ScoreConsumer"])

    body = body_of(request)
    reject_unknown(body, {"consumer_id", "score_variant_id", "bureau_id", "license_id",
                          "raw_posted_score", "expected_license_version",
                          "discovery_tag", "migration_event_id"})
    require_fields(body, ["consumer_id", "score_variant_id", "bureau_id", "license_id",
                          "raw_posted_score", "expected_license_version"])

    license_id = as_str(body["license_id"], "license_id")
    consumer_id = as_str(body["consumer_id"], "consumer_id")
    variant_id = as_str(body["score_variant_id"], "score_variant_id")
    bureau_id = as_str(body["bureau_id"], "bureau_id")

    # Priority 3 (role-identity binding) is subsumed by priority 9 for this
    # endpoint: X-User-ID must be the licence that covers the write.
    # Priority 5: every foreign key in the body resolves.
    consumer_rec = consumer(consumer_id)
    variant = score_variant(variant_id)
    bureau_rec = get_bureau(bureau_id)
    license_owned = get_license(license_id)

    # Priority 7: a posting against a SUPERSEDED or RETIRED version is refused.
    model = DB["score_models"][variant["score_model_id"]]

    discovery_tag = body.get("discovery_tag")
    tag_record = None
    if discovery_tag is not None:
        as_str(discovery_tag, "discovery_tag")
        for candidate in DB["score_discovery_requests"].values():
            if candidate["tag"] == discovery_tag and candidate["status"] == "REGISTERED":
                tag_record = candidate
                break

    if model["status"] == "SUPERSEDED" and tag_record is None:
        raise ApiError("ERR_MODEL_SUPERSEDED")
    if model["status"] == "RETIRED":
        raise ApiError("ERR_MODEL_RETIRED")
    if license_owned["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_SUSPENDED")

    # PRD §3.8: a discovery tag "becomes consumable by exactly one later posting"
    # and a second posting carrying the same tag is refused with
    # ERR_DISCOVERY_TAG_UNKNOWN because the slot is terminal. Checked before the
    # posting is stored so a refused attempt never leaves a half-written posting.
    if discovery_tag is not None and tag_record is None:
        raise ApiError("ERR_DISCOVERY_TAG_UNKNOWN")

    # Priority 9: referential pairings.
    if license_owned["score_variant_id"] != variant["id"]:
        raise ApiError("ERR_LICENSE_VARIANT_MISMATCH")
    if license_owned["id"] != user_id:
        raise ApiError("ERR_LICENSE_NOT_OWNED")

    # Priority 14: magnitude and format bounds.
    raw_posted_score = as_int(body["raw_posted_score"])
    if raw_posted_score < 300 or raw_posted_score > 850:
        raise ApiError("ERR_INVALID_REQUEST", "raw_posted_score must lie between 300 and 850.")

    # Priority 20: optimistic concurrency against the licence.
    check_occ(license_owned, body, "expected_license_version")

    # --- settlement ---------------------------------------------------------
    # PRD §3.8: "A supplied migration_event_id must match ... the earliest
    # unconsumed eligible event for this lender"; an eligible anchor is consumed
    # automatically when none is supplied. Resolution happens before the record
    # is written so an ineligible id rejects the request outright.
    migration_event_id = body.get("migration_event_id")
    anchor = _eligible_migration_event(license_owned["id"], license_owned["lender_code"], variant)
    if migration_event_id is not None:
        if anchor is None or anchor["id"] != as_str(migration_event_id, "migration_event_id"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "migration_event_id does not match the earliest unconsumed eligible event.")

    rec = new_record()
    rec.update({
        "consumer_id": consumer_rec["id"],
        "score_variant_id": variant["id"],
        "bureau_id": bureau_rec["id"],
        "reference_set_id": None,
        "license_id": license_owned["id"],
        "raw_posted_score": raw_posted_score,
        "effective_score": None,
        "odds_at_posted_score": None,
        "decision": None,
        "decision_reason_code_id": None,
        "migration_event_id": None,
    })

    # PRD §3.8: "a second posting carrying the same [terminal] tag is refused with
    # ERR_DISCOVERY_TAG_UNKNOWN because the slot is terminal". Checked before the
    # posting is stored so the refused attempt writes nothing.
    if discovery_tag is not None and tag_record is None:
        raise ApiError("ERR_DISCOVERY_TAG_UNKNOWN")

    rec["migration_event_id"] = anchor["id"] if anchor else None
    store("score_results", rec)
    derive_posting(rec)

    refset = latest_reference_set(consumer_rec["id"], model["id"])
    rec["reference_set_id"] = refset["id"] if refset else None

    # PRD §3.5: "A child whose weight_pct is below 0.05 routes its entire weight
    # to its parent_reason_code_id, and that parent's weight_received_pct becomes
    # the sum of every such child's weight_pct." The routing is a property of the
    # catalogue, so the effective variant's codes are re-derived at post time.
    for code in DB["reason_codes"].values():
        if code["score_variant_id"] == variant["id"]:
            recompute_reason_code_weights(code)

    cutoff_score = variant["cutoff_baseline"]
    if anchor is not None and anchor["event_type"] == "RECALIBRATED":
        cutoff_score = anchor.get("_recalibration_echoes", {}).get(
            "new_cutoff_score_preserving", cutoff_score)

    if rec["effective_score"] > cutoff_score:
        rec["decision"] = "APPROVE"
        rec["decision_reason_code_id"] = None
    elif rec["effective_score"] < cutoff_score:
        rec["decision"] = "DECLINE"
        primary = lowest_composite_primary_reason_code(variant)
        rec["decision_reason_code_id"] = primary["id"] if primary else None
    else:
        rec["decision"] = "UNDECIDED"
        rec["decision_reason_code_id"] = None

    if anchor is not None:
        anchor["_consumed_by_license_id"] = license_owned["id"]

    if tag_record is not None:
        tag_record["status"] = "CONSUMED"
        tag_record["consumed_score_result_id"] = rec["id"]
        touch(tag_record)

    accrue_marginal(license_owned, rec)
    recompute_license_window(license_owned)
    touch(license_owned)

    recompute_consumer(consumer_rec)
    return ok(rec, 201)


@bp.get("/score-results/<score_result_id>")
def get_score_result(score_result_id):
    role, user_id = authenticate(request)
    authorize(role, ALL_ROLES)
    if role == "ScoreConsumer" and user_id not in DB["licenses"]:
        raise ApiError("ERR_UNAUTHORIZED")
    rec = score_result(score_result_id)
    if role == "ScoreConsumer" and rec["license_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED")
    return ok(rec)


@bp.get("/score-results")
def list_score_results():
    role, user_id = authenticate(request)
    authorize(role, ALL_ROLES)
    if role == "ScoreConsumer" and user_id not in DB["licenses"]:
        raise ApiError("ERR_UNAUTHORIZED")
    limit, offset = read_pagination(request)
    rows = ordered_rows("score_results")

    for param in ("consumer_id", "score_variant_id", "bureau_id", "reference_set_id",
                  "license_id", "decision_reason_code_id", "migration_event_id", "decision"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]

    if role == "ScoreConsumer":
        rows = [r for r in rows if r["license_id"] == user_id]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/score-results/<score_result_id>/bureau-discrepancies")
def bureau_discrepancies(score_result_id):
    resolve_actor(request, DISCREPANCY_ROLES)
    poster = score_result(score_result_id)
    poster_variant = score_variant(poster["score_variant_id"])
    model_id = poster_variant["score_model_id"]

    same_model_variant_ids = {v["id"] for v in DB["score_variants"].values()
                              if v["score_model_id"] == model_id}

    peers = []
    for posting in ordered_rows("score_results"):
        if posting["id"] == poster["id"]:
            continue
        if posting.get("_voided"):
            continue
        if posting["consumer_id"] != poster["consumer_id"]:
            continue
        if posting["score_variant_id"] not in same_model_variant_ids:
            continue
        peers.append(posting)

    for peer in peers:
        peer["bureau_code"] = DB["bureaus"][peer["bureau_id"]]["bureau_code"]

    peers.sort(key=lambda p: (p["bureau_code"], p["created_at"]))

    result = bureau_discrepancy_scan(poster, peers)
    return ok(result)


@bp.post("/score-results/<score_result_id>/void")
def void_score_result(score_result_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = score_result(score_result_id)
    body = body_of(request)
    reject_unknown(body, {"expected_license_version"})

    license_owned = get_license(rec["license_id"])

    if rec.get("_voided"):
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    # Priority 20: OCC against the licence.
    check_occ(license_owned, body, "expected_license_version")

    fee = rec.get("_marginal_fee_cents", 0)
    cb = rec.get("_cumulative_count_before", license_owned["cumulative_score_count"] - 1)

    append_ledger_entry(
        license_owned,
        rec["id"],
        "VOID_REVERSAL",
        cb,
        -fee,
        f"Void reversal for score posting {rec['id']} at cumulative count {cb + 1}.",
    )
    rec["_voided"] = True
    license_owned["cumulative_score_count"] = max(0, license_owned["cumulative_score_count"] - 1)
    recompute_license_ledger(license_owned)
    recompute_license_window(license_owned)
    touch(license_owned)

    consumer_rec = DB["consumers"].get(rec["consumer_id"])
    if consumer_rec is not None:
        recompute_consumer(consumer_rec)
    return ok(rec)