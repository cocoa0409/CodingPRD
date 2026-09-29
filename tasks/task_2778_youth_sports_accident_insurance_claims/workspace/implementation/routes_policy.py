"""Policy quoting, lifecycle, loss experience and renewal pricing."""

from flask import Blueprint, g

import auth
import constants as C
import db
import guards
import response
import services
import util
import validation as v
from errors import ApiError

bp = Blueprint("policy", __name__)

POLICY_FIELDS_ZERO = {
    "paid_loss_cents": 0,
    "reserve_cents": 0,
    "incurred_loss_cents": 0,
    "open_claim_count": 0,
    "incurred_loss_ratio_bps": 0,
    "paid_loss_ratio_bps": 0,
    "experience_tier": "PREFERRED",
}


def _apply_premium(policy, sport):
    for key, value in services.rate_policy(policy, sport).items():
        policy[key] = value


@bp.post("/league-policies")
def create_policy():
    auth.require_roles(["ProgramAdministrator"])
    body = v.json_body()
    league_id = v.req_id(body, "league_id")
    sport_id = v.req_id(body, "sport_classification_id")
    effective = v.req_instant(body, "term_effective_date")
    expiration = v.req_instant(body, "term_expiration_date")
    count = v.req_int(body, "enrolled_participant_count", minimum=1)
    election = v.req_enum(
        body, "coverage_basis_election", C.COVERAGE_BASIS_ELECTIONS,
        required=False, default="EXCESS_ONLY",
    )
    cat_elected = v.req_bool(body, "cat_layer_elected", required=False, default=False)
    league = guards.resolve("league", league_id)
    sport = guards.resolve("sport_classification", sport_id)
    if expiration <= effective:
        raise ApiError("ERR_TERM_DATES_INVALID")
    row = db.new_row("league_policies", dict({
        "league_id": league["id"],
        "sport_classification_id": sport["id"],
        "term_effective_date": util.format_datetime(effective),
        "term_expiration_date": util.format_datetime(expiration),
        "enrolled_participant_count": count,
        "coverage_basis_election": election,
        "cat_layer_elected": cat_elected,
        "status": "QUOTED",
        "coverage_posture": "OPEN",
        "cancel_reason": None,
        "gross_premium_cents": 0,
        "cat_layer_charge_cents": 0,
        "premium_subtotal_cents": 0,
        "volume_credit_bps": 0,
        "volume_credit_cents": 0,
        "annual_premium_cents": 0,
        "deductible_cents": sport["deductible_cents"],
        "per_injury_limit_cents": sport["per_injury_limit_cents"],
        "cat_attachment_point_cents": sport["cat_attachment_point_cents"],
        "aggregate_limit_cents": sport["aggregate_limit_cents"],
        "cat_lifetime_max_cents": sport["cat_lifetime_max_cents"],
        "renewal_quote_status": "NONE",
        "renewal_loss_experience_basis": None,
        "renewal_quote_effective_date": None,
        "renewal_enrolled_participant_count": None,
        "renewal_loss_ratio_bps": None,
        "renewal_experience_tier": None,
        "renewal_experience_modifier_bps": None,
        "renewal_base_premium_cents": None,
        "renewal_quoted_premium_cents": None,
    }, **POLICY_FIELDS_ZERO))
    response.mark_fresh(row)
    _apply_premium(row, sport)
    services.recompute_policy(row)
    return response.respond_obj(row, 201)


@bp.get("/league-policies/<league_policy_id>")
def get_policy(league_policy_id):
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator", "ClaimsExaminer"])
    row = guards.resolve("league_policy", league_policy_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/league-policies")
def list_policies():
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator", "ClaimsExaminer"])
    limit, offset = v.pagination()
    league_id = v.query_str("league_id")
    sport_id = v.query_str("sport_classification_id")
    status = v.query_enum("status", C.POLICY_STATUSES)
    posture = v.query_enum("coverage_posture", C.POSTURES)
    rows = db.all_rows("league_policies")
    if league_id is not None:
        rows = [r for r in rows if r["league_id"] == league_id]
    if sport_id is not None:
        rows = [r for r in rows if r["sport_classification_id"] == sport_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if r["coverage_posture"] == posture]
    return response.respond_list(rows, limit, offset)


@bp.get("/league-policies/<league_policy_id>/loss-experience")
def loss_experience(league_policy_id):
    auth.require_roles(["ProgramAdministrator", "LeagueAdministrator", "ClaimsExaminer"])
    row = guards.resolve("league_policy", league_policy_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.post("/league-policies/<league_policy_id>/bind")
def bind_policy(league_policy_id):
    auth.require_roles(["ProgramAdministrator"])
    policy = guards.resolve("league_policy", league_policy_id)
    v.json_body()
    if policy["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_POLICY_STATE")
    guards.require_league_sanctioned(policy)
    effective = util.parse_datetime(policy["term_effective_date"])
    expiration = util.parse_datetime(policy["term_expiration_date"])
    for other in db.all_rows("league_policies"):
        if other["id"] == policy["id"]:
            continue
        if other["league_id"] != policy["league_id"]:
            continue
        if other["sport_classification_id"] != policy["sport_classification_id"]:
            continue
        if other["status"] not in C.IN_FORCE_COUNTED_STATUSES:
            continue
        other_eff = util.parse_datetime(other["term_effective_date"])
        other_exp = util.parse_datetime(other["term_expiration_date"])
        if effective < other_exp and other_eff < expiration:
            raise ApiError("ERR_POLICY_TERM_OVERLAP")
    sport = guards.sport_of_policy(policy)
    if policy["enrolled_participant_count"] < sport["minimum_participants"]:
        raise ApiError("ERR_MINIMUM_PARTICIPANTS_NOT_MET")
    premium = services.rate_policy(policy, sport)
    services.touch(policy, status="BOUND", **premium)
    services.recompute_league_in_force(db.get("leagues", policy["league_id"]))
    services.recompute_policy(policy)
    return response.respond_obj(policy)


@bp.post("/league-policies/<league_policy_id>/activate")
def activate_policy(league_policy_id):
    auth.require_roles(["ProgramAdministrator"])
    policy = guards.resolve("league_policy", league_policy_id)
    v.json_body()
    if policy["status"] != "BOUND":
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if db.now() < util.parse_datetime(policy["term_effective_date"]):
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "The logical clock has not reached the term effective date.",
        )
    services.touch(policy, status="ACTIVE")
    services.recompute_policy(policy)
    return response.respond_obj(policy)


@bp.post("/league-policies/<league_policy_id>/run-off")
def run_off_policy(league_policy_id):
    auth.require_roles(["ProgramAdministrator"])
    policy = guards.resolve("league_policy", league_policy_id)
    v.json_body()
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if db.now() < util.parse_datetime(policy["term_expiration_date"]):
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "The logical clock has not reached the term expiration date.",
        )
    services.touch(policy, status="RUN_OFF")
    services.recompute_policy(policy)
    return response.respond_obj(policy)


@bp.post("/league-policies/<league_policy_id>/cancel")
def cancel_policy(league_policy_id):
    auth.require_roles(["ProgramAdministrator"])
    policy = guards.resolve("league_policy", league_policy_id)
    body = v.json_body()
    cancel_reason = v.req_str(body, "cancel_reason")
    status = policy["status"]
    if status not in ("QUOTED", "BOUND", "ACTIVE"):
        raise ApiError("ERR_INVALID_POLICY_STATE")
    if status in ("BOUND", "ACTIVE") and len(services.open_claims_of_policy(policy)) > 0:
        raise ApiError("ERR_OPEN_CLAIMS_ON_POLICY")
    services.touch(policy, status="CANCELLED", cancel_reason=cancel_reason)
    if status in ("BOUND", "ACTIVE"):
        services.recompute_league_in_force(db.get("leagues", policy["league_id"]))
    services.recompute_policy(
        policy, force_activity_sweep=(status == "ACTIVE"), allow_auto_close=False
    )
    return response.respond_obj(policy)


@bp.post("/league-policies/<league_policy_id>/renewal-quote")
def renewal_quote(league_policy_id):
    auth.require_roles(["ProgramAdministrator"])
    policy = guards.resolve("league_policy", league_policy_id)
    body = v.json_body()
    basis = v.req_enum(body, "loss_experience_basis", C.LOSS_EXPERIENCE_BASES)
    renewal_effective = v.req_instant(body, "renewal_effective_date")
    renewal_count = v.req_int(body, "renewal_enrolled_participant_count", minimum=1)
    expected_version = v.req_int(body, "expected_league_policy_version", minimum=1)
    if policy["status"] not in ("ACTIVE", "RUN_OFF"):
        raise ApiError("ERR_INVALID_POLICY_STATE")
    guards.require_league_sanctioned(policy)
    guards.require_not_frozen(policy)
    if expected_version != policy["version"]:
        raise ApiError("ERR_STALE_POLICY_VERSION")
    if renewal_effective < util.parse_datetime(policy["term_expiration_date"]):
        raise ApiError("ERR_TERM_DATES_INVALID")
    ratio = (
        policy["incurred_loss_ratio_bps"] if basis == "INCURRED"
        else policy["paid_loss_ratio_bps"]
    )
    tier = services.experience_tier_for(ratio)
    modifier = C.EXPERIENCE_MODIFIER_BPS[tier]
    sport = guards.sport_of_policy(policy)
    base_premium = services.rate_policy(policy, sport, renewal_count)["annual_premium_cents"]
    quoted = max(
        C.MIN_ANNUAL_PREMIUM_CENTS,
        util.apply_bps(base_premium, 10000 + modifier),
    )
    services.touch(
        policy,
        renewal_quote_status="QUOTED",
        renewal_loss_experience_basis=basis,
        renewal_quote_effective_date=util.format_datetime(renewal_effective),
        renewal_enrolled_participant_count=renewal_count,
        renewal_loss_ratio_bps=ratio,
        renewal_experience_tier=tier,
        renewal_experience_modifier_bps=modifier,
        renewal_base_premium_cents=base_premium,
        renewal_quoted_premium_cents=quoted,
    )
    return response.respond_obj(policy)


@bp.post("/league-policies/<league_policy_id>/renewal-acceptance")
def renewal_acceptance(league_policy_id):
    auth.require_roles(["LeagueAdministrator"])
    policy = guards.resolve("league_policy", league_policy_id)
    auth.check_ownership(policy)
    v.json_body()
    if policy["renewal_quote_status"] != "QUOTED":
        raise ApiError("ERR_INVALID_POLICY_STATE")
    services.touch(policy, renewal_quote_status="ACCEPTED")
    return response.respond_obj(policy)
