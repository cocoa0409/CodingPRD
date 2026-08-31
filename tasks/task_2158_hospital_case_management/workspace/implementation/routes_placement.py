"""Post-acute placement: referrals, broadcast rounds, bed offers and the
documentation of the patient's choice (PRD 3.4, 3.5)."""

from flask import Blueprint

import calc
import cascade
import derive
from envelope import created, filter_eq, list_response, ok
from errors import ApiError
from store import base_row, db, ordered, parse_dt, touch
from validate import (CHOICE_BASES, LEVELS_OF_CARE, actor, body, present,
                      req_dt, req_enum, req_int, req_str, req_str_array,
                      require_roles)

bp = Blueprint("placement", __name__)

TERMINAL_NON_ACCEPTED = {"DECLINED_BY_PATIENT", "WITHDRAWN", "EXPIRED"}


# --------------------------------------------------------------------------
# referrals
# --------------------------------------------------------------------------
@bp.post("/episodes/<eid>/referrals")
def create_referral(eid):
    require_roles("CaseManager")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    b = body()
    level = req_enum(b, "requested_level_of_care", LEVELS_OF_CARE)
    stay_days = req_int(b, "projected_stay_days", minimum=1)
    needed_raw, needed_dt = req_dt(b, "needed_by")
    if needed_dt <= db.now():
        raise ApiError("ERR_INVALID_INTERVAL", "needed_by must be later than the clock")
    row = base_row()
    row.update({
        "episode_id": episode["id"],
        "requested_level_of_care": level,
        "projected_stay_days": stay_days,
        "needed_by": needed_raw,
        "round_index": 0,
        "broadcast_provider_ids": [],
        "status": "DRAFT",
        "chosen_bed_offer_id": None,
        "choice_basis": None,
        "patient_choice_attested": False,
    })
    db.referrals[row["id"]] = row
    if cascade.advance_to_planning(episode):
        touch(episode)
    return created(derive.ser_referral(row))


@bp.post("/referrals/<rid>/broadcast")
def broadcast(rid):
    require_roles("CaseManager")
    referral = derive.get_referral(rid)
    derive.sweep_referral(referral)
    episode = derive.get_episode(referral["episode_id"])
    b = body()
    provider_ids = req_str_array(b, "provider_ids")
    providers = [derive.get_provider(pid) for pid in provider_ids]

    if referral["status"] not in ("DRAFT", "CHOICE_PENDING"):
        raise ApiError("ERR_INVALID_REFERRAL_STATE",
                       "referral status %s does not admit a broadcast" % referral["status"])
    if referral["status"] == "DRAFT" and episode["case_status"] != "PLANNING":
        raise ApiError("ERR_INVALID_EPISODE_STATE", "episode is not in PLANNING")

    level = referral["requested_level_of_care"]
    eligible = set()
    for provider in providers:
        if provider["status"] == "ACTIVE" and provider["provider_type"] == level:
            eligible.add(provider["id"])
    if len(eligible) < calc.MIN_BROADCAST_PROVIDERS:
        raise ApiError("ERR_INSUFFICIENT_PROVIDER_CHOICE",
                       "at least %d active providers of the requested level of care are required"
                       % calc.MIN_BROADCAST_PROVIDERS)

    payer = derive.episode_payer(episode)
    if payer is not None:
        slate = set(provider_ids)
        for provider in db.providers.values():
            if provider["status"] != "ACTIVE" or provider["provider_type"] != level:
                continue
            contract = derive.contract_for(payer["id"], provider["id"])
            if contract is not None and contract.get("in_network") and provider["id"] not in slate:
                raise ApiError("ERR_REFERRAL_FAIRNESS_VIOLATION",
                               "the slate omits an active in-network provider")

    for provider in providers:
        if provider["status"] != "ACTIVE":
            raise ApiError("ERR_RESOURCE_UNAVAILABLE",
                           "provider %s is SUSPENDED" % provider["id"])

    if referral["status"] == "CHOICE_PENDING":
        for offer in derive.offers_of(referral["id"]):
            if offer["round_index"] == referral["round_index"] and \
                    offer["status"] not in TERMINAL_NON_ACCEPTED:
                raise ApiError("ERR_ROUND_STILL_OPEN",
                               "an offer of the current round is not yet terminal")

    referral["round_index"] += 1
    referral["broadcast_provider_ids"] = list(provider_ids)
    referral["status"] = "BROADCAST"
    counted = set()
    for provider in providers:
        if provider["id"] in counted:
            continue
        counted.add(provider["id"])
        provider["offers_received_count"] = provider.get("offers_received_count", 0) + 1
        touch(provider)
    touch(referral)
    return ok(derive.ser_referral(referral))


@bp.get("/referrals/<rid>")
def read_referral(rid):
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin",
                  "PostAcuteLiaison")
    referral = derive.get_referral(rid)
    derive.sweep_referral(referral)
    return ok(derive.ser_referral(referral))


@bp.get("/referrals")
def list_referrals():
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin")
    rows = ordered(db.referrals.values())
    for row in rows:
        derive.sweep_referral(row)
    rows = filter_eq(rows, "episode_id", "episode_id")
    rows = filter_eq(rows, "chosen_bed_offer_id", "chosen_bed_offer_id")
    rows = filter_eq(rows, "status", "status")
    return list_response(rows, derive.ser_referral)


# --------------------------------------------------------------------------
# bed offers
# --------------------------------------------------------------------------
@bp.post("/referrals/<rid>/offers")
def create_offer(rid):
    require_roles("PostAcuteLiaison")
    provider = db.providers.get(actor())
    if provider is None:
        raise ApiError("ERR_NOT_OWNER", "X-User-ID does not identify a post-acute provider")
    referral = derive.get_referral(rid)
    derive.sweep_referral(referral)
    derive.sweep_provider(provider)
    b = body()
    expected_version = req_int(b, "expected_referral_version")
    bed_unit_code = req_str(b, "bed_unit_code")
    from_raw, from_dt = req_dt(b, "bed_available_from")
    until_raw, until_dt = req_dt(b, "hold_expires_at")
    daily_rate = req_int(b, "daily_rate_cents", minimum=1)

    if expected_version != referral["version"]:
        raise ApiError("ERR_STALE_REFERRAL_VERSION",
                       "expected_referral_version does not match the referral version")
    if referral["status"] not in ("BROADCAST", "CHOICE_PENDING"):
        raise ApiError("ERR_INVALID_REFERRAL_STATE",
                       "referral status %s does not admit an offer" % referral["status"])
    if provider["provider_type"] != referral["requested_level_of_care"]:
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH",
                       "provider type does not match the requested level of care")
    if provider["id"] not in (referral["broadcast_provider_ids"] or []):
        raise ApiError("ERR_PROVIDER_NOT_IN_BROADCAST",
                       "provider was not invited to this round")
    if bed_unit_code not in (provider["bed_unit_codes"] or []):
        raise ApiError("ERR_UNKNOWN_BED_UNIT", "bed_unit_code is unknown for this provider")
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_RESOURCE_UNAVAILABLE", "provider is SUSPENDED")
    if until_dt <= from_dt:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "hold_expires_at must be strictly after bed_available_from")

    for other in db.offers.values():
        if other["provider_id"] != provider["id"] or other["bed_unit_code"] != bed_unit_code:
            continue
        if other["status"] not in ("OFFERED", "ACCEPTED_BY_PATIENT"):
            continue
        other_from = parse_dt(other["bed_available_from"])
        other_until = parse_dt(other["hold_expires_at"])
        if other_from is None or other_until is None:
            continue
        if from_dt < other_until and other_from < until_dt:
            raise ApiError("ERR_BED_HOLD_OVERLAP", "the bed hold intersects a live hold")

    row = base_row()
    row.update({
        "referral_id": referral["id"],
        "provider_id": provider["id"],
        "round_index": referral["round_index"],
        "bed_unit_code": bed_unit_code,
        "bed_available_from": from_raw,
        "hold_expires_at": until_raw,
        "daily_rate_cents": daily_rate,
        "status": "OFFERED",
    })
    db.offers[row["id"]] = row
    if referral["status"] == "BROADCAST":
        referral["status"] = "CHOICE_PENDING"
    touch(referral)
    return created(derive.ser_offer(row))


@bp.post("/offers/<oid>/withdraw")
def withdraw_offer(oid):
    require_roles("PostAcuteLiaison")
    if db.providers.get(actor()) is None:
        raise ApiError("ERR_NOT_OWNER", "X-User-ID does not identify a post-acute provider")
    offer = derive.get_offer(oid)
    if offer["provider_id"] != actor():
        raise ApiError("ERR_NOT_OWNER", "a liaison may only withdraw its own offers")
    derive.sweep_offer(offer)
    if offer["status"] == "EXPIRED":
        raise ApiError("ERR_OFFER_EXPIRED", "the bed hold has run out")
    if offer["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_OFFER_STATE", "the offer is no longer OFFERED")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return ok(derive.ser_offer(offer))


@bp.post("/referrals/<rid>/document-choice")
def document_choice(rid):
    require_roles("CaseManager")
    referral = derive.get_referral(rid)
    derive.sweep_referral(referral)
    episode = derive.get_episode(referral["episode_id"])
    derive.sweep_episode(episode)
    b = body()
    chosen_id = req_str(b, "chosen_bed_offer_id")
    choice_basis = req_enum(b, "choice_basis", CHOICE_BASES)
    attested = b.get("patient_choice_attested")

    if referral["status"] != "CHOICE_PENDING":
        raise ApiError("ERR_INVALID_REFERRAL_STATE",
                       "referral status %s does not admit a choice" % referral["status"])
    offer = db.offers.get(chosen_id)
    if offer is None or offer["referral_id"] != referral["id"]:
        raise ApiError("ERR_BED_OFFER_NOT_FOUND", "chosen_bed_offer_id does not resolve")
    derive.sweep_offer(offer)
    if offer["status"] == "EXPIRED":
        raise ApiError("ERR_OFFER_EXPIRED", "the bed hold has run out")
    if offer["round_index"] != referral["round_index"] or offer["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_OFFER_STATE", "the offer is not an open offer of this round")
    if attested is not True:
        raise ApiError("ERR_CHOICE_NOT_ATTESTED", "patient_choice_attested must be true")

    payer = derive.episode_payer(episode)
    level = referral["requested_level_of_care"]
    requires_auth = False
    if payer is not None:
        if level in ("SNF", "IRF", "LTACH"):
            requires_auth = bool(payer["snf_auth_required"])
        elif level == "HOME_HEALTH":
            requires_auth = bool(payer["hh_auth_required"])
    if requires_auth:
        now = db.now()
        live = []
        for auth in derive.authorizations_of(episode["id"]):
            if auth["provider_id"] != offer["provider_id"]:
                continue
            if auth["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
                continue
            expires = parse_dt(auth.get("expires_at"))
            if expires is None or expires <= now:
                continue
            live.append(auth)
        if not live:
            raise ApiError("ERR_AUTHORIZATION_REQUIRED",
                           "a live authorization is required for this level of care")
        if not any((a.get("approved_days") or 0) >= referral["projected_stay_days"] for a in live):
            raise ApiError("ERR_AUTHORIZATION_INSUFFICIENT",
                           "approved_days is below the referral's projected_stay_days")

    offer["status"] = "ACCEPTED_BY_PATIENT"
    touch(offer)
    for sibling in derive.offers_of(referral["id"]):
        if sibling["id"] == offer["id"]:
            continue
        if sibling["round_index"] == referral["round_index"] and sibling["status"] == "OFFERED":
            sibling["status"] = "DECLINED_BY_PATIENT"
            touch(sibling)
    referral["status"] = "PLACED"
    referral["chosen_bed_offer_id"] = offer["id"]
    referral["choice_basis"] = choice_basis
    referral["patient_choice_attested"] = True
    touch(referral)
    cascade.resolve_barriers_with_code(episode, "BED_AVAILABILITY")
    return ok(derive.ser_referral(referral))


@bp.get("/offers/<oid>")
def read_offer(oid):
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin",
                  "PostAcuteLiaison")
    offer = derive.get_offer(oid)
    derive.sweep_offer(offer)
    return ok(derive.ser_offer(offer))


@bp.get("/offers")
def list_offers():
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin",
                  "PostAcuteLiaison")
    rows = ordered(db.offers.values())
    for row in rows:
        derive.sweep_offer(row)
    rows = filter_eq(rows, "referral_id", "referral_id")
    rows = filter_eq(rows, "provider_id", "provider_id")
    rows = filter_eq(rows, "status", "status")
    return list_response(rows, derive.ser_offer)
