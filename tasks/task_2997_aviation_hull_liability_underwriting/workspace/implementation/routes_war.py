"""War, hijacking and terrorism: markets, placements and cancellation.

Placement intervals use CLOSED-interval arithmetic throughout, which is the
deliberate contrast with the half-open windows of aircraft coverage.
"""

from flask import Blueprint, request

import auth
import calc
import constants as C
import derive
import envelope
import serialize
import services
import validate as V
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("war", __name__)

ALL = C.ALL_ROLES


def _closed_overlap(a_from, a_to, b_from, b_to):
    """Two placements that merely touch at an endpoint DO overlap."""
    return b_from <= a_to and a_from <= b_to


def _scopes_overlap(left, right):
    """Perils scopes are nested sets, so any two of them share the war peril."""
    return True


# --- markets ------------------------------------------------------------------

@bp.route("/aviation/war-markets", methods=["POST"])
@auth.endpoint(["Underwriter"])
def create_market():
    body = V.json_body()
    market_name = V.get_str(body, "market_name")
    aggregate_line_cents = V.get_int(body, "aggregate_line_cents")
    perils_offered = V.get_str(body, "perils_offered")

    V.check_len(market_name, "market_name", 1, 80, non_blank=True)
    V.check_range(aggregate_line_cents, "aggregate_line_cents", 1)
    V.check_enum(perils_offered, "perils_offered", C.PERILS)

    for other in db.markets.values():
        if other["market_name"] == market_name:
            raise V.invalid("Field 'market_name' must be unique across all markets.")

    rec = new_record(db.markets, {
        "market_name": market_name,
        "aggregate_line_cents": aggregate_line_cents,
        "perils_offered": perils_offered,
    })
    return envelope.ok(serialize.market(rec), 201)


@bp.route("/aviation/war-markets/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_market(row_id):
    rec = services.get_market(row_id)
    return envelope.ok(serialize.market(rec))


# --- placements ---------------------------------------------------------------

@bp.route("/aviation/war-placements", methods=["POST"])
@auth.endpoint(["Underwriter"])
def create_placement():
    body = V.json_body()
    policy = services.resolve_fk(body, "policy_id", services.get_policy)
    services.scope_policy(policy)
    market = services.resolve_fk(body, "market_id", services.get_market)

    war_hull_line_cents = V.get_int(body, "war_hull_line_cents")
    perils_scope = V.get_str(body, "perils_scope")
    coverage_from = V.get_instant(body, "coverage_from")
    coverage_to = V.get_instant(body, "coverage_to")
    expected_policy_version = V.get_int(body, "expected_policy_version")

    V.check_range(war_hull_line_cents, "war_hull_line_cents", 1)
    V.check_enum(perils_scope, "perils_scope", C.PERILS)
    V.check_before(coverage_from, coverage_to, "coverage_from must precede coverage_to.")

    # Rank 12, relaxed: the war slip is arranged before inception, so DRAFT is
    # accepted here. EXPIRED still refuses, as every write on an expired policy does.
    if policy["status"] not in ("DRAFT", "BOUND"):
        raise ApiError("ERR_POLICY_NOT_BOUND")

    if expected_policy_version != policy["version"]:
        raise ApiError("ERR_STALE_POLICY_VERSION")

    if coverage_from < policy["effective_from"] or coverage_to > policy["effective_to"]:
        raise ApiError("ERR_PLACEMENT_WINDOW_INVALID")
    for other in derive.placements_of_policy(policy["id"]):
        if other["status"] != "BOUND":
            continue
        if not _scopes_overlap(perils_scope, other["perils_scope"]):
            continue
        if _closed_overlap(coverage_from, coverage_to,
                           other["coverage_from"], other["coverage_to"]):
            raise ApiError("ERR_PLACEMENT_WINDOW_INVALID")

    if C.PERILS_ORDER[perils_scope] > C.PERILS_ORDER[market["perils_offered"]]:
        raise ApiError("ERR_PERILS_NOT_OFFERED")

    peak = 0
    for other in derive.placements_of_market(market["id"]):
        if other["status"] != "BOUND":
            continue
        if _closed_overlap(coverage_from, coverage_to,
                           other["coverage_from"], other["coverage_to"]):
            peak += other["war_hull_line_cents"]
    if peak + war_hull_line_cents > market["aggregate_line_cents"]:
        raise ApiError("ERR_MARKET_LINE_EXCEEDED")

    premium = calc.war_risk_premium(war_hull_line_cents, perils_scope,
                                    policy["territorial_limit_code"])

    rec = new_record(db.placements, {
        "policy_id": policy["id"],
        "market_id": market["id"],
        "war_hull_line_cents": war_hull_line_cents,
        "perils_scope": perils_scope,
        "coverage_from": coverage_from,
        "coverage_to": coverage_to,
        "status": "BOUND",
        "premium_cents": premium,
        "cancellation_reason": None,
    })
    services.append_transaction(policy["id"], "WAR_RISK_PREMIUM", premium,
                                coverage_from, "ANNUAL",
                                "war risk placement %s" % rec["id"])
    touch(policy)
    return envelope.ok(serialize.placement(rec), 201)


@bp.route("/aviation/war-placements", methods=["GET"])
@auth.endpoint(ALL)
def list_placements():
    limit, offset = V.pagination()
    rows = ordered(db.placements)
    visible = services.visible_policy_ids()
    if visible is not None:
        rows = [r for r in rows if r["policy_id"] in visible]
    rows = V.filter_eq(rows, "policy_id", request.args.get("policy_id"))
    rows = V.filter_eq(rows, "market_id", request.args.get("market_id"))
    rows = V.filter_eq(rows, "perils_scope", request.args.get("perils_scope"))
    rows = V.filter_eq(rows, "status", request.args.get("status"))
    total = len(rows)
    window = V.page(rows, limit, offset)
    return envelope.ok_list(serialize.many(serialize.placement, window), limit, offset, total)


@bp.route("/aviation/war-placements/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_placement(row_id):
    rec = services.get_placement(row_id)
    services.scope_via_policy(rec["policy_id"])
    return envelope.ok(serialize.placement(rec))


@bp.route("/aviation/war-placements/<row_id>/cancellation", methods=["POST"])
@auth.endpoint(["Underwriter"])
def cancel_placement(row_id):
    rec = services.get_placement(row_id)
    body = V.json_body()
    cancellation_reason = V.get_str(body, "cancellation_reason")

    if rec["status"] != "BOUND":
        raise ApiError("ERR_PLACEMENT_NOT_BOUND")

    for endorsement in derive.endorsements_of_policy(rec["policy_id"]):
        if endorsement["status"] != "BOUND":
            continue
        if endorsement["endorsement_type"] != "TERRITORY_EXTENSION":
            continue
        if endorsement["territory_code"] != "WAR_ZONE_A":
            continue
        if rec["coverage_from"] <= endorsement["effective_date"] <= rec["coverage_to"]:
            raise ApiError(
                "ERR_WAR_RISK_NOT_PLACED",
                "The placement supports a bound war-zone extension and cannot be withdrawn.")

    policy = db.policies[rec["policy_id"]]
    rec["status"] = "CANCELLED"
    rec["cancellation_reason"] = cancellation_reason
    touch(rec)
    services.append_transaction(policy["id"], "RETURN_PREMIUM", -rec["premium_cents"],
                                db.clock, "PRO_RATA",
                                "cancellation of war risk placement %s" % rec["id"])
    touch(policy)
    return envelope.ok(serialize.placement(rec))
