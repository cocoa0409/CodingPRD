"""Offer negotiation, acceptance and the contract read/wellness surface.

PRD sections 3.3, 3.4 and the contract half of 3.6.
"""

from flask import Blueprint

import calc
import cascade
import db
import response
import serializers as ser
import validation as v
from auth import endpoint, caller, require_org_owner, require_player_owner
from db import store
from errors import fail

bp = Blueprint("offers", __name__)

OFFER_STATES = ("SENT", "COUNTERED", "ACCEPTED", "DECLINED", "EXPIRED", "SUPERSEDED")
CONTRACT_STATES = ("ACTIVE", "SUSPENDED", "TERMINATED")
OBLIGATION_STATES = ("COMPLIANT", "WARNED", "BREACH")
OPEN_OFFER_STATES = ("SENT", "COUNTERED")


# --------------------------------------------------------------------------------------
# lazy expiry -- PRD section 3.3
# --------------------------------------------------------------------------------------

def apply_lazy_expiry(offer):
    """Runs at the start of every operation that reads or mutates an offer.  Returns True
    when the offer is (now) EXPIRED."""
    if offer["offer_status"] in OPEN_OFFER_STATES and calc.offer_expired(offer):
        offer["offer_status"] = "EXPIRED"
        db.touch(offer)
    return offer["offer_status"] == "EXPIRED"


def _guard_open(offer, allowed_states):
    """Band 8: lazy expiry is evaluated BEFORE the offer's own status guard."""
    if apply_lazy_expiry(offer):
        fail("ERR_OFFER_EXPIRED")
    if offer["offer_status"] not in allowed_states:
        fail("ERR_OFFER_NOT_OPEN")


def _association_terms(league, player, prize_split_bp, streaming_hours):
    """Band 13, in the §2.6 internal order.  Only association members are bound."""
    if not player["association_member"]:
        return
    if prize_split_bp is not None and prize_split_bp < league["association_min_prize_split_bp"]:
        fail("ERR_PRIZE_SPLIT_BELOW_ASSOCIATION_MIN")
    if (streaming_hours is not None
            and streaming_hours > league["association_max_streaming_hours_per_week"]):
        fail("ERR_STREAMING_HOURS_EXCEED_ASSOCIATION_MAX")


def _minimum_salary(league, base_salary_cents):
    if base_salary_cents < league["minimum_salary_cents"]:
        fail("ERR_BELOW_MINIMUM_SALARY")


# ======================================================================================
# offer creation
# ======================================================================================

@bp.post("/contract-offers")
@endpoint(["GeneralManager"])
def create_offer():
    payload = v.body()
    # Band 4 runs before band 5, so the raw body value decides ownership.
    raw_org = payload.get("organization_id")
    if isinstance(raw_org, str):
        require_org_owner(raw_org)

    organization_id = v.req_str(payload, "organization_id")
    player_id = v.req_str(payload, "player_id")
    supersedes_offer_id = v.opt_str(payload, "supersedes_offer_id")
    base_salary_cents = v.req_int(payload, "base_salary_cents", 0)
    term_months = v.req_int(payload, "term_months", 1, 60)
    prize_split_bp = v.req_bp(payload, "prize_split_player_pct_bp")
    streaming_hours = v.req_int(payload, "streaming_hours_per_week", 0, 80)
    tax_residency_code = v.req_str(payload, "tax_residency_code", 2, 8, upper=True)
    signing_bonus_cents = v.opt_int(payload, "signing_bonus_cents", 0, 0)
    buyout_multiplier_bp = v.opt_int(payload, "buyout_multiplier_bp", 5000, 0, 30000)

    organization = v.find_organization(organization_id)
    player = v.find_player(player_id)
    superseded = None
    if supersedes_offer_id is not None:
        superseded = store.offers.get(supersedes_offer_id)
        if (superseded is None
                or superseded["player_id"] != player_id
                or superseded["organization_id"] != organization_id):
            fail("ERR_OFFER_NOT_FOUND")

    league = calc.league_of_organization(organization)
    _minimum_salary(league, base_salary_cents)
    _association_terms(league, player, prize_split_bp, streaming_hours)

    sent_at = db.now()
    record = {
        "organization_id": organization_id,
        "player_id": player_id,
        "supersedes_offer_id": supersedes_offer_id,
        "offer_status": "SENT",
        "round_number": 1,
        "base_salary_cents": base_salary_cents,
        "term_months": term_months,
        "prize_split_player_pct_bp": prize_split_bp,
        "streaming_hours_per_week": streaming_hours,
        "signing_bonus_cents": signing_bonus_cents,
        "buyout_multiplier_bp": buyout_multiplier_bp,
        "tax_residency_code": tax_residency_code,
        "counter_base_salary_cents": None,
        "counter_prize_split_player_pct_bp": None,
        "counter_streaming_hours_per_week": None,
        "counter_note": None,
        "decline_note": None,
        "sent_at": sent_at,
        "expires_at": db.add_hours(sent_at, league["offer_response_window_hours"]),
    }
    db.insert(store.offers, record)

    if superseded is not None:
        apply_lazy_expiry(superseded)
        if superseded["offer_status"] in OPEN_OFFER_STATES:
            superseded["offer_status"] = "SUPERSEDED"
            db.touch(superseded)
    return response.object_response(ser.offer(record), 201)


@bp.get("/contract-offers/<offer_id>")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent"])
def read_offer(offer_id):
    record = v.find_offer(offer_id)
    require_org_owner(record["organization_id"])
    require_player_owner(record["player_id"])
    apply_lazy_expiry(record)
    return response.object_response(ser.offer(record))


@bp.get("/contract-offers")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent"])
def list_offers():
    limit, offset = response.pagination()
    organization_id = v.str_filter("organization_id")
    player_id = v.str_filter("player_id")
    supersedes_offer_id = v.str_filter("supersedes_offer_id")
    status = v.enum_filter("offer_status", OFFER_STATES)
    for record in list(store.offers.values()):
        apply_lazy_expiry(record)
    records = list(store.offers.values())
    if organization_id is not None:
        records = [o for o in records if o["organization_id"] == organization_id]
    if player_id is not None:
        records = [o for o in records if o["player_id"] == player_id]
    if supersedes_offer_id is not None:
        records = [o for o in records if o["supersedes_offer_id"] == supersedes_offer_id]
    if status is not None:
        records = [o for o in records if o["offer_status"] == status]
    return response.paginated(db.in_creation_order(records), ser.offer, limit, offset)


# ======================================================================================
# counter / revise / decline
# ======================================================================================

@bp.post("/contract-offers/<offer_id>/counter")
@endpoint(["PlayerAgent"])
def counter_offer(offer_id):
    record = v.find_offer(offer_id)
    require_player_owner(record["player_id"])
    payload = v.body()
    counter_base = v.req_int(payload, "counter_base_salary_cents", 0)
    counter_split = v.req_bp(payload, "counter_prize_split_player_pct_bp")
    counter_streaming = v.req_int(payload, "counter_streaming_hours_per_week", 0, 80)
    counter_note = v.free_text(payload, "counter_note")

    _guard_open(record, ("SENT",))
    league = calc.league_of_offer(record)
    if record["round_number"] >= league["max_negotiation_rounds"]:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

    # The two association-membership terms are deliberately NOT checked on a counter.
    _minimum_salary(league, counter_base)

    record["counter_base_salary_cents"] = counter_base
    record["counter_prize_split_player_pct_bp"] = counter_split
    record["counter_streaming_hours_per_week"] = counter_streaming
    record["counter_note"] = counter_note
    record["offer_status"] = "COUNTERED"
    db.touch(record)
    return response.object_response(ser.offer(record))


@bp.post("/contract-offers/<offer_id>/revise")
@endpoint(["GeneralManager"])
def revise_offer(offer_id):
    record = v.find_offer(offer_id)
    require_org_owner(record["organization_id"])
    payload = v.body()
    base_salary_cents = v.req_int(payload, "base_salary_cents", 0)
    prize_split_bp = v.req_bp(payload, "prize_split_player_pct_bp")
    streaming_hours = v.req_int(payload, "streaming_hours_per_week", 0, 80)

    _guard_open(record, ("COUNTERED",))
    league = calc.league_of_offer(record)
    if record["round_number"] >= league["max_negotiation_rounds"]:
        fail("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")

    player = store.players.get(record["player_id"])
    _minimum_salary(league, base_salary_cents)
    _association_terms(league, player, prize_split_bp, streaming_hours)

    sent_at = db.now()
    record["base_salary_cents"] = base_salary_cents
    record["prize_split_player_pct_bp"] = prize_split_bp
    record["streaming_hours_per_week"] = streaming_hours
    record["counter_base_salary_cents"] = None
    record["counter_prize_split_player_pct_bp"] = None
    record["counter_streaming_hours_per_week"] = None
    record["counter_note"] = None
    record["round_number"] = record["round_number"] + 1
    record["offer_status"] = "SENT"
    record["sent_at"] = sent_at
    record["expires_at"] = db.add_hours(sent_at, league["offer_response_window_hours"])
    db.touch(record)
    return response.object_response(ser.offer(record))


@bp.post("/contract-offers/<offer_id>/decline")
@endpoint(["PlayerAgent"])
def decline_offer(offer_id):
    record = v.find_offer(offer_id)
    require_player_owner(record["player_id"])
    payload = v.body()
    decline_note = v.free_text(payload, "decline_note")
    _guard_open(record, OPEN_OFFER_STATES)
    record["decline_note"] = decline_note
    record["offer_status"] = "DECLINED"
    db.touch(record)
    return response.object_response(ser.offer(record))


# ======================================================================================
# acceptance -- PRD section 3.4
# ======================================================================================

@bp.post("/contract-offers/<offer_id>/accept")
@endpoint(["PlayerAgent"])
def accept_offer(offer_id):
    offer = v.find_offer(offer_id)
    require_player_owner(offer["player_id"])
    payload = v.body()
    effective_at = v.opt_instant(payload, "effective_at", None)
    if effective_at is None:
        effective_at = db.now()

    # ---- band 8 ----------------------------------------------------------------
    _guard_open(offer, ("SENT",))
    player = store.players[offer["player_id"]]
    organization = store.organizations[offer["organization_id"]]
    league = calc.league_of_organization(organization)
    if calc.contract_of_player(player["id"]) is not None:
        fail("ERR_PLAYER_ALREADY_SIGNED")

    # ---- band 9 ----------------------------------------------------------------
    if calc.guardian_consent_status(player, organization, league) == "REQUIRED":
        fail("ERR_GUARDIAN_CONSENT_REQUIRED")

    # ---- band 10 ---------------------------------------------------------------
    if calc.roster_lock_active(league):
        fail("ERR_ROSTER_LOCK_ACTIVE")
    if calc.free_agency_cooldown_hit(player, organization["id"]):
        fail("ERR_FREE_AGENCY_COOLDOWN")
    if not (league["season_start_at"] <= effective_at < league["season_end_at"]):
        fail("ERR_EFFECTIVE_AT_OUTSIDE_SEASON")

    # ---- band 11 ---------------------------------------------------------------
    if league["tryout_required_before_offer"] and player["player_status"] != "TRYOUT_COMPLETED":
        fail("ERR_TRYOUT_REQUIRED")
    if not calc.active_roster_count(organization) < league["max_roster_size"]:
        fail("ERR_ROSTER_SIZE_EXCEEDED")

    # ---- band 13 ---------------------------------------------------------------
    _minimum_salary(league, offer["base_salary_cents"])
    _association_terms(league, player, offer["prize_split_player_pct_bp"],
                       offer["streaming_hours_per_week"])
    provisional = calc.prorated_cap_charge(
        offer["base_salary_cents"], offer["signing_bonus_cents"], effective_at, league)
    if provisional > calc.uncommitted_salary_cents(organization):
        fail("ERR_SALARY_CAP_EXCEEDED")

    # ---- the four-link cascade -------------------------------------------------
    user_id, _role = caller()
    offer["offer_status"] = "ACCEPTED"
    db.touch(offer)

    contract = {
        "offer_id": offer["id"],
        "player_id": offer["player_id"],
        "organization_id": offer["organization_id"],
        "contract_status": "ACTIVE",
        "obligation_status": "COMPLIANT",
        "base_salary_cents": offer["base_salary_cents"],
        "term_months": offer["term_months"],
        "signing_bonus_cents": offer["signing_bonus_cents"],
        "prize_split_player_pct_bp": offer["prize_split_player_pct_bp"],
        "streaming_hours_per_week": offer["streaming_hours_per_week"],
        "buyout_multiplier_bp": offer["buyout_multiplier_bp"],
        "tax_residency_code": offer["tax_residency_code"],
        "effective_at": effective_at,
        "ends_at": db.add_days(effective_at, offer["term_months"] * db.MONTH_DAYS),
        "provisional_cap_charge_cents": provisional,
        "season_practice_minutes": 0,
        "last_self_reported_load": 0,
        "reported_streaming_minutes_7d": 0,
        "burnout_score": 0,
        "wellness_hold_until": None,
        "suspension_reason": None,
        "signed_by_user_id": user_id,
    }
    db.insert(store.contracts, contract)

    player["player_status"] = "SIGNED"
    player["current_organization_id"] = organization["id"]
    player["free_agency_window_ends_at"] = None
    player["last_release_organization_id"] = None
    db.touch(player)

    # committed / uncommitted / active_roster_count are derived from the contract set;
    # the organization is still versioned because the cascade touched it.
    db.touch(organization)

    for sibling in db.in_creation_order(list(store.offers.values())):
        if sibling["id"] == offer["id"]:
            continue
        if sibling["player_id"] != offer["player_id"]:
            continue
        if sibling["offer_status"] not in OPEN_OFFER_STATES:
            continue
        sibling["offer_status"] = "SUPERSEDED"
        db.touch(sibling)

    return response.object_response(ser.contract(contract), 201)


# ======================================================================================
# contracts
# ======================================================================================

@bp.get("/contracts/<contract_id>")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent", "FinanceOfficer",
           "PerformanceSupport"])
def read_contract(contract_id):
    record = v.find_contract(contract_id)
    require_org_owner(record["organization_id"])
    require_player_owner(record["player_id"])
    return response.object_response(ser.contract(record))


@bp.get("/contracts")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent", "FinanceOfficer"])
def list_contracts():
    limit, offset = response.pagination()
    organization_id = v.str_filter("organization_id")
    player_id = v.str_filter("player_id")
    offer_id = v.str_filter("offer_id")
    contract_status = v.enum_filter("contract_status", CONTRACT_STATES)
    obligation_status = v.enum_filter("obligation_status", OBLIGATION_STATES)
    records = list(store.contracts.values())
    if organization_id is not None:
        records = [c for c in records if c["organization_id"] == organization_id]
    if player_id is not None:
        records = [c for c in records if c["player_id"] == player_id]
    if offer_id is not None:
        records = [c for c in records if c["offer_id"] == offer_id]
    if contract_status is not None:
        records = [c for c in records if c["contract_status"] == contract_status]
    if obligation_status is not None:
        records = [c for c in records if c["obligation_status"] == obligation_status]
    return response.paginated(db.in_creation_order(records), ser.contract, limit, offset)


@bp.post("/contracts/<contract_id>/suspend")
@endpoint(["LeagueAdmin"])
def suspend_contract(contract_id):
    record = v.find_contract(contract_id)
    payload = v.body()
    suspension_reason = v.req_str(payload, "suspension_reason", 1)
    if record["contract_status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE")
    record["suspension_reason"] = suspension_reason
    record["contract_status"] = "SUSPENDED"
    db.touch(record)
    organization = store.organizations.get(record["organization_id"])
    if organization is not None:
        # active_roster_count drops by one; committed_salary_cents is NOT released.
        db.touch(organization)
    cascade.cancel_future_blocks(record["player_id"], "CONTRACT_SUSPENDED")
    return response.object_response(ser.contract(record))


@bp.post("/contracts/<contract_id>/wellness-report")
@endpoint(["PerformanceSupport"])
def file_wellness_report(contract_id):
    record = v.find_contract(contract_id)
    payload = v.body()
    load = v.req_int(payload, "last_self_reported_load", 0, 10)
    streaming_minutes = v.opt_int(payload, "reported_streaming_minutes_7d", None, 0)
    if record["contract_status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE")
    record["last_self_reported_load"] = load
    if streaming_minutes is not None:
        record["reported_streaming_minutes_7d"] = streaming_minutes
    cascade.refresh_burnout_and_escalate(record)
    db.touch(record)
    return response.object_response(ser.contract(record))


@bp.get("/contracts/<contract_id>/obligation-summary")
@endpoint(["LeagueAdmin", "GeneralManager", "PerformanceSupport"])
def read_obligation_summary(contract_id):
    record = v.find_contract(contract_id)
    require_org_owner(record["organization_id"])
    return response.object_response(ser.obligation_summary(record))


@bp.get("/contracts/<contract_id>/prize-allocations")
@endpoint(["LeagueAdmin", "PlayerAgent", "FinanceOfficer"])
def list_contract_allocations(contract_id):
    record = v.find_contract(contract_id)
    require_player_owner(record["player_id"])
    limit, offset = response.pagination()
    records = [a for a in store.allocations.values() if a["contract_id"] == record["id"]]
    return response.paginated(db.in_creation_order(records), ser.allocation, limit, offset)
