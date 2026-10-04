"""Domain services: FK/path lookups, season resolution, the posture gate, the
patent-exposure engine with season contagion, factory capacity ledger, the
partner-suspension and retirement cascades, and the 11-step run-review."""

from datetime import timedelta
from decimal import Decimal

from constants import CONSTANTS
from errors import ApiError
from state import DB, bump, now, touch
from util import fmt_iso

# ---------------------------------------------------------------------------
# lookups (priority 3: path ids left-to-right, then body FKs)
# ---------------------------------------------------------------------------


def get_or_404(collection, key, error_id):
    obj = collection.get(key)
    if obj is None:
        raise ApiError(error_id, 404, "resource %s does not exist" % key)
    return obj


def req_fk(data, field, collection, error_id):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "field %r is required" % field)
    return get_or_404(collection, v, error_id)


# ---------------------------------------------------------------------------
# owning-season resolution (PRD §2.7 parent chains)
# ---------------------------------------------------------------------------


def season_of_category(cat):
    return DB.seasons.get(cat["season_id"]) if cat else None


def season_of_concept(concept):
    return season_of_category(DB.categories.get(concept["category_id"])) if concept else None


def season_of_variant(variant):
    return season_of_concept(DB.concepts.get(variant["concept_id"])) if variant else None


def season_of_via_variant(child):
    return season_of_variant(DB.variants.get(child["variant_id"])) if child else None


def season_of_agreement(agreement):
    return season_of_category(DB.categories.get(agreement["category_id"])) if agreement else None


# ---------------------------------------------------------------------------
# posture gate (priority 4). Patent-case endpoints, factory-partner endpoints,
# season admin endpoints and GETs are exempt and never call this. Category
# creation is exempt from FROZEN (admin repair path) but not from CLOSED.
# GUARDED throttles exactly one operation: media-test air.
# ---------------------------------------------------------------------------


def posture_gate(season, *, air=False, category_create=False):
    if season is None:
        return
    posture = season["posture"]
    if posture == "SEASON_CLOSED":
        raise ApiError("ERR_SEASON_CLOSED", 409, "season is SEASON_CLOSED")
    if posture == "SEASON_FROZEN" and not category_create:
        raise ApiError("ERR_SEASON_FROZEN", 409, "season is SEASON_FROZEN")
    if posture == "SEASON_GUARDED" and air:
        raise ApiError("ERR_SEASON_GUARDED", 409, "season is SEASON_GUARDED; airing is throttled")


# ---------------------------------------------------------------------------
# patent exposure engine + reserve ledger + season contagion (PRD §3.8)
# ---------------------------------------------------------------------------

SEVERITY_WEIGHTS = {
    "LOW": CONSTANTS["CASE_WEIGHT_LOW"],
    "MED": CONSTANTS["CASE_WEIGHT_MED"],
    "HIGH": CONSTANTS["CASE_WEIGHT_HIGH"],
}


def recompute_category(cat):
    """Recompute exposure_index / exposure_level / active_reserve_cents from the
    category's cases, then fire OPEN -> GUARDED contagion when landing on SEVERE."""
    index = cat["crowding_base"]
    reserve = 0
    for case in DB.cases.values():
        if case["category_id"] != cat["id"]:
            continue
        status = case["status"]
        if status in ("FILED", "ACTIVE"):
            index += SEVERITY_WEIGHTS[case["severity"]]
            reserve += case["provisional_reserve_cents"]
        elif status == "JUDGED_ADVERSE":
            index += CONSTANTS["ADVERSE_WEIGHT_MULTIPLIER"] * SEVERITY_WEIGHTS[case["severity"]]
            reserve += case["final_amount_cents"] or 0
        elif status == "SETTLED":
            reserve += case["final_amount_cents"] or 0
        # JUDGED_FAVORABLE contributes nothing to either ledger
    if index >= CONSTANTS["EXPOSURE_SEVERE_MIN"]:
        level = "SEVERE"
    elif index >= CONSTANTS["EXPOSURE_ELEVATED_MIN"]:
        level = "ELEVATED"
    else:
        level = "CLEAR"
    if (index, level, reserve) != (
        cat["exposure_index"], cat["exposure_level"], cat["active_reserve_cents"]
    ):
        cat["exposure_index"] = index
        cat["exposure_level"] = level
        cat["active_reserve_cents"] = reserve
        touch(cat)
    if level == "SEVERE":
        season = season_of_category(cat)
        if season is not None and season["posture"] == "SEASON_OPEN":
            season["posture"] = "SEASON_GUARDED"
            season["guarded_since_review_index"] = season["review_index"]
            touch(season)


# ---------------------------------------------------------------------------
# factory capacity ledger (conservation invariant, PRD §2.9 — computed live so
# every compensating pair leaves the identity exact by construction)
# ---------------------------------------------------------------------------


def allocated_units(partner_id):
    total = 0
    for c in DB.commitments.values():
        if c["status"] == "OPEN":
            v = DB.variants.get(c["variant_id"])
            if v and v.get("factory_partner_id") == partner_id:
                total += c["committed_units"]
    for r in DB.replenishments.values():
        if r["status"] == "OPEN":
            v = DB.variants.get(r["variant_id"])
            if v and v.get("factory_partner_id") == partner_id:
                total += r["quantity_units"]
    return total


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------


def expire_round(rnd):
    """Run-review step 2: expiry consumes prototype budget exactly as a
    completion does — the rounds_used increment is unconditional (PRD §3.2);
    hitting the 4-round budget reverts the concept (scoped to
    PROTOTYPE_CYCLING, per the PRD's 'reverts from PROTOTYPE_CYCLING')."""
    rnd["status"] = "EXPIRED"
    touch(rnd)
    concept = DB.concepts.get(rnd["concept_id"])
    if concept is not None:
        concept["rounds_used"] += 1
        if (concept["status"] == "PROTOTYPE_CYCLING"
                and concept["rounds_used"] >= CONSTANTS["MAX_ROUNDS_PER_CYCLE"]):
            concept["rounds_used"] = 0
            concept["status"] = "RESEARCHING"
        touch(concept)


def suspend_partner_cascade(partner):
    """OPEN commitments on variants tooled here -> SHORTFALL_PENALIZED with the
    per-unit penalty accrued into the owning season; OPEN replenishments ->
    CANCELLED. Penalty accrual is applied once, at cascade time, never recomputed."""
    for c in DB.commitments.values():
        if c["status"] != "OPEN":
            continue
        v = DB.variants.get(c["variant_id"])
        if v is None or v.get("factory_partner_id") != partner["id"]:
            continue
        c["status"] = "SHORTFALL_PENALIZED"
        c["penalty_cents"] = c["committed_units"] * CONSTANTS["SHORTFALL_PENALTY_CENTS"]
        touch(c)
        season = season_of_variant(v)
        if season is not None:
            season["penalty_accrual_cents"] += c["penalty_cents"]
            touch(season)
    for r in DB.replenishments.values():
        if r["status"] != "OPEN":
            continue
        v = DB.variants.get(r["variant_id"])
        if v is None or v.get("factory_partner_id") != partner["id"]:
            continue
        r["status"] = "CANCELLED"
        touch(r)


def retire_variant(v):
    """Run-review step 10: retirement cascades to OPEN commitments and OPEN
    replenishments (both CANCELLED, releasing allocated capacity)."""
    ts = now()
    v["lifecycle"] = "RETIRED"
    v["retired_at"] = fmt_iso(ts)
    v["retired_dt"] = ts
    touch(v)
    for c in DB.commitments.values():
        if c["variant_id"] == v["id"] and c["status"] == "OPEN":
            c["status"] = "CANCELLED"
            touch(c)
    for r in DB.replenishments.values():
        if r["variant_id"] == v["id"] and r["status"] == "OPEN":
            r["status"] = "CANCELLED"
            touch(r)


# ---------------------------------------------------------------------------
# run-review checkpoint (PRD §3.9): review_index += 1, then 11 ordered steps
# ---------------------------------------------------------------------------


def _season_scopes(season):
    cat_ids = {c["id"] for c in DB.categories.values() if c["season_id"] == season["id"]}
    concept_ids = {c["id"] for c in DB.concepts.values() if c["category_id"] in cat_ids}
    variant_ids = {v["id"] for v in DB.variants.values() if v["concept_id"] in concept_ids}
    return cat_ids, concept_ids, variant_ids


def run_review(season):
    ts_now = now()
    season["review_index"] += 1
    season["last_review_at"] = fmt_iso(ts_now)
    bump(season)  # the endpoint's own version increment
    review_index = season["review_index"]
    cat_ids, concept_ids, variant_ids = _season_scopes(season)

    # Step 1: FILED patent cases in linked categories -> ACTIVE
    for case in DB.cases.values():
        if case["category_id"] in cat_ids and case["status"] == "FILED":
            case["status"] = "ACTIVE"
            touch(case)

    # Step 2: stale OPEN rounds -> EXPIRED (budget consumption may revert concept)
    for rnd in DB.rounds.values():
        if (rnd["status"] == "OPEN" and rnd["concept_id"] in concept_ids
                and (ts_now - rnd["opened_dt"]) > timedelta(days=CONSTANTS["ROUND_MAX_OPEN_DAYS"])):
            expire_round(rnd)

    # Step 3: concept deadline — not ENGINEERING_LOCKED/killed and older than
    # CONCEPT_MAX_AGE_DAYS -> LAUNCH_KILLED; any OPEN round expires in the sweep
    for concept in DB.concepts.values():
        if (concept["category_id"] in cat_ids
                and concept["status"] not in ("ENGINEERING_LOCKED", "LAUNCH_KILLED")
                and (ts_now - concept["created_dt"]) > timedelta(days=CONSTANTS["CONCEPT_MAX_AGE_DAYS"])):
            concept["status"] = "LAUNCH_KILLED"
            concept["killed_reason"] = "DEADLINE_EXCEEDED"
            touch(concept)
            for rnd in DB.rounds.values():
                if rnd["concept_id"] == concept["id"] and rnd["status"] == "OPEN":
                    rnd["status"] = "EXPIRED"
                    touch(rnd)

    # Step 4: AIRING media tests past MEDIA_DECISION_MAX_DAYS -> KILLED
    for mt in DB.media_tests.values():
        if (mt["variant_id"] in variant_ids and mt["status"] == "AIRING"
                and (ts_now - mt["aired_dt"]) > timedelta(days=CONSTANTS["MEDIA_DECISION_MAX_DAYS"])):
            mt["status"] = "KILLED"
            touch(mt)

    # Step 5: OPEN commitments with need_by_date < now -> FULFILLED
    for c in DB.commitments.values():
        if (c["variant_id"] in variant_ids and c["status"] == "OPEN"
                and c["need_by_dt"] < ts_now):
            c["status"] = "FULFILLED"
            touch(c)

    # Step 6: every OPEN replenishment order -> FULFILLED
    for r in DB.replenishments.values():
        if r["variant_id"] in variant_ids and r["status"] == "OPEN":
            r["status"] = "FULFILLED"
            touch(r)

    # Step 7: SIGNED agreements whose window_end <= now -> EXPIRED
    for a in DB.agreements.values():
        if (a["category_id"] in cat_ids and a["status"] == "SIGNED"
                and a["window_end_dt"] <= ts_now):
            a["status"] = "EXPIRED"
            touch(a)

    # Step 8: DR_TESTING variants with an OPEN or FULFILLED commitment -> RETAIL_LIVE
    for v in DB.variants.values():
        if v["id"] in variant_ids and v["lifecycle"] == "DR_TESTING":
            has_commitment = any(
                c["variant_id"] == v["id"] and c["status"] in ("OPEN", "FULFILLED")
                for c in DB.commitments.values()
            )
            if has_commitment:
                v["lifecycle"] = "RETAIL_LIVE"
                v["retail_live_at"] = fmt_iso(ts_now)
                v["retail_live_dt"] = ts_now
                touch(v)

    # Step 9: RETAIL_LIVE variants older than MODEL_MAX_AGE_DAYS -> REFRESH_CANDIDATE
    for v in DB.variants.values():
        if (v["id"] in variant_ids and v["lifecycle"] == "RETAIL_LIVE"
                and (ts_now - v["retail_live_dt"]) > timedelta(days=CONSTANTS["MODEL_MAX_AGE_DAYS"])):
            v["lifecycle"] = "REFRESH_CANDIDATE"
            v["refresh_candidate_at"] = fmt_iso(ts_now)
            v["refresh_candidate_dt"] = ts_now
            touch(v)

    # Step 10: REFRESH_CANDIDATE variants past REFRESH_GRACE_DAYS -> RETIRED + cascade
    for v in DB.variants.values():
        if (v["id"] in variant_ids and v["lifecycle"] == "REFRESH_CANDIDATE"
                and (ts_now - v["refresh_candidate_dt"]) > timedelta(days=CONSTANTS["REFRESH_GRACE_DAYS"])):
            retire_variant(v)

    # Step 11: exposure/posture reconciliation
    for cat in DB.categories.values():
        if cat["id"] in cat_ids:
            recompute_category(cat)
    if season["posture"] == "SEASON_GUARDED":
        any_severe = any(
            c["exposure_level"] == "SEVERE"
            for c in DB.categories.values() if c["id"] in cat_ids
        )
        if not any_severe:
            season["posture"] = "SEASON_OPEN"
            season["guarded_since_review_index"] = None
            touch(season)
        else:
            guarded_since = season["guarded_since_review_index"]
            if guarded_since is None:
                guarded_since = review_index
            if review_index - guarded_since >= CONSTANTS["GUARDED_GRACE_REVIEWS"]:
                season["posture"] = "SEASON_FROZEN"
                season["frozen_at_review_index"] = review_index
                touch(season)
