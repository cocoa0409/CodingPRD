"""Petition filing, accordance, and the institution decision (PRD 3.3, 3.4).

Filing runs the full validation ladder: auth -> role -> body FK existence ->
ownership -> schema -> OCC -> patent state -> one-year time bar -> fee.
"""

from flask import Blueprint

from db import store, strip_internal, format_iso
from calculations import (
    fintiv_score, is_time_barred, petition_required_fee, merits_evaluation,
    panel_active_load, fwd_dates, refresh_pending_petitions_for_patent,
    INSTITUTION_WINDOW_DAYS, FINTIV_DENIAL_THRESHOLD, PANEL_LEAD_CAPACITY,
)
from datetime import timedelta
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_RESOURCE_OWNER, ERR_PARTY_NOT_FOUND,
    ERR_PATENT_NOT_FOUND, ERR_STALE_PATENT_VERSION, ERR_INVALID_STATE,
    ERR_PETITION_TIME_BARRED, ERR_FEE_INSUFFICIENT, ERR_PETITION_WRONG_STATE,
    ERR_GROUND_NOT_PERMITTED, ERR_PRIOR_ART_TYPE_NOT_PERMITTED,
    ERR_INSTITUTION_WINDOW_LAPSED, ERR_PANEL_CAPACITY_EXCEEDED,
)
from helpers import (
    require_roles, get_body, req_string, req_int, req_enum, req_array, is_int,
    success_object, list_response, request_arg, ALL_ROLES,
)
from lookups import get_patent, get_party, get_petition

bp = Blueprint("petitions", __name__)

REVIEW_TYPES = ("IPR", "PGR")
ALL_BASES = ("ANTICIPATION_102", "OBVIOUSNESS_103", "PUBLIC_USE", "ON_SALE",
             "OTHER_STATUTORY")
IPR_BASES = ("ANTICIPATION_102", "OBVIOUSNESS_103")
ALL_REFERENCE_TYPES = ("PATENT", "PRINTED_PUBLICATION", "PRODUCT", "TESTIMONY")
IPR_REFERENCE_TYPES = ("PATENT", "PRINTED_PUBLICATION")


@bp.post("/ptab/petitions")
def create_petition():
    user_id, _ = require_roles("Petitioner")
    body = get_body()

    # Priority 3: existence of body-referenced entities that are present.
    raw_patent_id = body.get("patent_id")
    raw_petitioner_id = body.get("petitioner_id")
    patent = None
    petitioner = None
    if isinstance(raw_patent_id, str):
        patent = get_patent(raw_patent_id)
    if isinstance(raw_petitioner_id, str):
        petitioner = get_party(raw_petitioner_id)

    # Priority 4: ownership — petitioner_id must equal the caller.
    if isinstance(raw_petitioner_id, str) and raw_petitioner_id != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER,
                  "petitioner_id must equal the caller's X-User-ID")

    # Priority 5: schema.
    patent_id = req_string(body, "patent_id")
    petitioner_id = req_string(body, "petitioner_id")
    if patent is None:
        raise_err(ERR_PATENT_NOT_FOUND, f"patent {patent_id} does not exist")
    if petitioner is None:
        raise_err(ERR_PARTY_NOT_FOUND, f"party {petitioner_id} does not exist")
    if petitioner["party_type"] != "PETITIONER":
        raise_err(ERR_VALIDATION,
                  "petitioner_id must reference a PETITIONER party")
    review_type = req_enum(body, "review_type", REVIEW_TYPES)

    challenged_claims = req_array(body, "challenged_claims")
    for claim in challenged_claims:
        if not is_int(claim):
            raise_err(ERR_VALIDATION, "challenged_claims must be integers")
    if len(set(challenged_claims)) != len(challenged_claims):
        raise_err(ERR_VALIDATION, "challenged_claims must be unique")
    for claim in challenged_claims:
        if claim < 1 or claim > patent["total_claims"]:
            raise_err(ERR_VALIDATION,
                      "challenged_claims must be within 1..total_claims")

    grounds = req_array(body, "grounds")
    for ground in grounds:
        if not isinstance(ground, dict):
            raise_err(ERR_VALIDATION, "grounds entries must be objects")
        if ground.get("basis") not in ALL_BASES:
            raise_err(ERR_VALIDATION, f"basis must be one of {list(ALL_BASES)}")
        if ground.get("claim_number") not in challenged_claims:
            raise_err(ERR_VALIDATION,
                      "every ground's claim_number must be in challenged_claims")

    prior_art = req_array(body, "prior_art")
    for art in prior_art:
        if not isinstance(art, dict):
            raise_err(ERR_VALIDATION, "prior_art entries must be objects")
        if art.get("reference_type") not in ALL_REFERENCE_TYPES:
            raise_err(ERR_VALIDATION,
                      f"reference_type must be one of {list(ALL_REFERENCE_TYPES)}")
        if not isinstance(art.get("citation"), str) or art.get("citation") == "":
            raise_err(ERR_VALIDATION, "prior_art citation must be a string")

    req_string(body, "real_party_in_interest")
    fee_paid_cents = req_int(body, "fee_paid_cents")
    expected_patent_version = req_int(body, "expected_patent_version")

    # Priority 6: OCC against the patent.
    if expected_patent_version != patent["version"]:
        raise_err(ERR_STALE_PATENT_VERSION,
                  "expected_patent_version does not match the patent's "
                  "current version")

    # Priority 7: patent state.
    if patent["status"] == "FULLY_CANCELLED":
        raise_err(ERR_INVALID_STATE,
                  "a fully cancelled patent admits no new petitions")

    # Priority 8: one-year time bar (strictly more than 365 days).
    filing_dt = store.clock.now()
    if is_time_barred(patent["id"], petitioner_id, filing_dt):
        raise_err(ERR_PETITION_TIME_BARRED,
                  "a complaint naming the petitioner was served more than "
                  "365 days before filing")

    # Priority 10: fee sufficiency.
    required = petition_required_fee(len(challenged_claims))
    if fee_paid_cents < required:
        raise_err(ERR_FEE_INSUFFICIENT,
                  f"fee_paid_cents {fee_paid_cents} below required {required}")

    petition = store.new_common()
    petition.update({
        "patent_id": patent["id"],
        "petitioner_id": petitioner_id,
        "review_type": review_type,
        "challenged_claims": list(challenged_claims),
        "grounds": grounds,
        "prior_art": prior_art,
        "real_party_in_interest": body["real_party_in_interest"],
        "fee_paid_cents": fee_paid_cents,
        "filing_date": format_iso(filing_dt),
        "accorded_date": None,
        "status": "FILED",
        "fintiv_score": 0,
        "merits_max_score": None,
        "advisory_aggregate_score": None,
        "_filing_dt": filing_dt,
    })
    store.petitions[petition["id"]] = petition
    petition["fintiv_score"] = fintiv_score(petition)
    # A successful filing increments the patent's version by one.
    store.touch(patent)
    return success_object(strip_internal(petition), status=201)


@bp.get("/ptab/petitions")
def list_petitions():
    require_roles(*ALL_ROLES)
    patent_id = request_arg("patent_id")
    petitioner_id = request_arg("petitioner_id")
    status = request_arg("status")
    items = store.petitions.values()
    if patent_id is not None:
        items = [p for p in items if p["patent_id"] == patent_id]
    if petitioner_id is not None:
        items = [p for p in items if p["petitioner_id"] == petitioner_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(list(items))


@bp.get("/ptab/petitions/<petitionId>")
def get_petition_route(petitionId):
    require_roles(*ALL_ROLES)
    return success_object(strip_internal(get_petition(petitionId)))


@bp.post("/ptab/petitions/<petitionId>/accord-filing-date")
def accord_filing_date(petitionId):
    require_roles("BoardPanel")
    petition = get_petition(petitionId)
    if petition["status"] != "FILED":
        raise_err(ERR_PETITION_WRONG_STATE,
                  "accord-filing-date requires the petition to be FILED")
    # IPR statutory screens run at accordance (PRD 3.4).
    if petition["review_type"] == "IPR":
        for ground in petition["grounds"]:
            if ground["basis"] not in IPR_BASES:
                raise_err(ERR_GROUND_NOT_PERMITTED,
                          "IPR grounds are limited to ANTICIPATION_102 and "
                          "OBVIOUSNESS_103")
        for art in petition["prior_art"]:
            if art["reference_type"] not in IPR_REFERENCE_TYPES:
                raise_err(ERR_PRIOR_ART_TYPE_NOT_PERMITTED,
                          "IPR prior art is limited to PATENT and "
                          "PRINTED_PUBLICATION")
    petition["status"] = "NOTICE_ACCORDED"
    now = store.clock.now()
    petition["accorded_date"] = store.clock.now_iso()
    petition["_accorded_dt"] = now
    petition["fintiv_score"] = fintiv_score(petition)
    store.touch(petition)
    return success_object(strip_internal(petition), status=200)


@bp.post("/ptab/petitions/<petitionId>/decide-institution")
def decide_institution(petitionId):
    require_roles("BoardPanel")
    petition = get_petition(petitionId)
    body = get_body()

    # Schema (priority 5).
    per_ground_scores = req_array(body, "per_ground_scores")
    lead_judge_user_id = req_string(body, "lead_judge_user_id")
    scores = []
    for entry in per_ground_scores:
        if not isinstance(entry, dict):
            raise_err(ERR_VALIDATION,
                      "per_ground_scores entries must be objects")
        claim_number = entry.get("claim_number")
        if not is_int(claim_number) or claim_number not in petition["challenged_claims"]:
            raise_err(ERR_VALIDATION,
                      "every scored claim must lie among the petition's "
                      "challenged_claims")
        if not isinstance(entry.get("basis"), str) or entry.get("basis") == "":
            raise_err(ERR_VALIDATION, "each scored ground must name a basis")
        score = entry.get("score")
        if not is_int(score) or score < 0 or score > 100:
            raise_err(ERR_VALIDATION, "each score must be an integer 0..100")
        scores.append(score)

    # State (priority 7).
    if petition["status"] != "NOTICE_ACCORDED":
        raise_err(ERR_PETITION_WRONG_STATE,
                  "decide-institution requires the petition to be "
                  "NOTICE_ACCORDED")

    # Statutory window (priority 8): now <= accorded_date + 93 days.
    now = store.clock.now()
    accorded_dt = petition["_accorded_dt"]
    if now > accorded_dt + timedelta(days=INSTITUTION_WINDOW_DAYS):
        raise_err(ERR_INSTITUTION_WINDOW_LAPSED,
                  "the 93-day institution window has lapsed")

    merits_max, threshold, advisory, merits_met = merits_evaluation(
        scores, petition["review_type"])
    decision_fintiv = fintiv_score(petition)
    if not merits_met:
        outcome = "DENIED_MERITS"
    elif decision_fintiv >= FINTIV_DENIAL_THRESHOLD:
        outcome = "DENIED_DISCRETIONARY"
    else:
        outcome = "INSTITUTED"

    # Panel capacity (priority 9) applies only when instituting.
    if outcome == "INSTITUTED":
        if panel_active_load(lead_judge_user_id) >= PANEL_LEAD_CAPACITY:
            raise_err(ERR_PANEL_CAPACITY_EXCEEDED,
                      "panel lead already leads two active proceedings")

    now_iso = store.clock.now_iso()
    decision = {
        "id": store.new_id(),
        "created_at": now_iso,
        "_seq": store.next_seq(),
        "petition_id": petition["id"],
        "outcome": outcome,
        "merits_max_score": merits_max,
        "threshold_used": threshold,
        "advisory_aggregate_score": advisory,
        "fintiv_score": decision_fintiv,
        "lead_judge_user_id": lead_judge_user_id,
        "decided_at": now_iso,
    }
    store.decisions[decision["id"]] = decision

    petition["status"] = "INSTITUTED" if outcome == "INSTITUTED" else "DENIED"
    petition["merits_max_score"] = merits_max
    petition["advisory_aggregate_score"] = advisory
    store.touch(petition)

    proceeding_id = None
    if outcome == "INSTITUTED":
        proceeding_id = _fire_institution_cascade(
            petition, lead_judge_user_id, now, now_iso)

    return success_object({
        "decision_id": decision["id"],
        "outcome": outcome,
        "merits_max_score": merits_max,
        "advisory_aggregate_score": advisory,
        "threshold_used": threshold,
        "fintiv_score": decision_fintiv,
        "proceeding_id": proceeding_id,
    }, status=201)


def _fire_institution_cascade(petition, lead_judge_user_id, now, now_iso):
    """Cascade links 1-3 of PRD 2.10, applied atomically in-request."""
    fwd_dt, anniversary_dt = fwd_dates(now, extended=False)
    proceeding = store.new_common()
    proceeding.update({
        "petition_id": petition["id"],
        "patent_id": petition["patent_id"],
        "lead_judge_user_id": lead_judge_user_id,
        "instituted_claims": list(petition["challenged_claims"]),
        "phase": "INSTITUTED",
        "institution_date": now_iso,
        "cycle_anchor_date": now_iso,
        "fwd_due_date": format_iso(fwd_dt),
        "advisory_anniversary_date": format_iso(anniversary_dt),
        "extension_used": False,
        "estoppel_applied": False,
        "amendment_slots_available": 1,
        "briefing_cycle": 0,
        "total_overage_fee_cents": 0,
        "_anchor_dt": now,
        "_fwd_dt": fwd_dt,
    })
    store.proceedings[proceeding["id"]] = proceeding

    # Cascade link 2: patent -> IN_REVIEW (ISSUED / self-loop / post-decision
    # states). FULLY_CANCELLED is terminal and has no outgoing transition.
    patent = store.patents[petition["patent_id"]]
    if patent["status"] != "FULLY_CANCELLED":
        patent["status"] = "IN_REVIEW"
        store.touch(patent)

    # Cascade link 3: every ACTIVE matter for the patent auto-stays.
    for matter in store.matters.values():
        if matter["patent_id"] == patent["id"] and matter["status"] == "ACTIVE":
            matter["status"] = "STAYED"
            matter["stay_reason"] = "INSTITUTION_STAY"
            store.touch(matter)

    # The stay cascade refreshes the provisional fintiv score of every
    # petition against this patent that is still pending.
    refresh_pending_petitions_for_patent(patent["id"])
    return proceeding["id"]


@bp.get("/ptab/petitions/<petitionId>/institution-decision")
def get_institution_decision(petitionId):
    require_roles(*ALL_ROLES)
    petition = get_petition(petitionId)
    items = [d for d in store.decisions.values()
             if d["petition_id"] == petition["id"]]
    return list_response(items)
