"""Settlement endpoints."""
from flask import Blueprint, request

from clock import now
from constants import ALL_ROLES
from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
import calc
import helpers as H
import ticks

bp = Blueprint("settlements", __name__)
SETTLEMENT_READ_ROLES = ("TourManager", "VenueBooker", "BoxOfficeManager", "PlatformAdmin")


def _gross_for_engagement(e):
    return sum(sale["total_cents"] for sale in db.ticket_sales.values()
               if sale["engagement_id"] == e["id"])


def _recompute_settlement(s, e, t, venue):
    gross = s["gross_ticket_cents"]
    s["venue_share_cents"] = calc.compute_venue_share(e, venue, gross)
    s["royalty_withheld_cents"] = calc.compute_royalty_withheld(t, gross)
    s["labor_total_cents"] = calc.compute_labor_total(e["id"])
    s["promoter_net_cents"] = calc.compute_promoter_net(
        gross, s["venue_share_cents"], s["royalty_withheld_cents"], s["labor_total_cents"])


@bp.route("/tours/<tourId>/engagements/<engagementId>/settlement", methods=["GET"])
@require_roles(*SETTLEMENT_READ_ROLES)
def get_settlement(tourId, engagementId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    return success(H.get_settlement(engagementId))


@bp.route("/tours/<tourId>/engagements/<engagementId>/settlement/reconcile", methods=["POST"])
@require_roles("TourManager")
def reconcile(tourId, engagementId):
    t = H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    if e["status"] != "IN_PERFORMANCE":
        raise err("ERR_INVALID_STATE", "Engagement must be IN_PERFORMANCE to reconcile")
    for c in db.labor_calls.values():
        if c["engagement_id"] == e["id"] and c["status"] in ("DRAFT", "POSTED", "FILLED"):
            raise err("ERR_UNRESOLVED_LABOR_CALLS",
                      "LaborCall %s still %s" % (c["id"], c["status"]))
    existing = db.settlements_by_eng.get(e["id"])
    if existing:
        raise err("ERR_INVALID_STATE", "Settlement already exists for this engagement")
    venue = db.venues[e["venue_id"]]
    s = base_fields()
    s.update({
        "engagement_id": e["id"],
        "status": "OPEN",
        "gross_ticket_cents": _gross_for_engagement(e),
        "venue_share_cents": 0,
        "royalty_withheld_cents": 0,
        "labor_total_cents": 0,
        "promoter_net_cents": 0,
        "reconciled_at": None,
    })
    db.settlements[s["id"]] = s
    db.settlements_by_eng[e["id"]] = s["id"]
    _recompute_settlement(s, e, t, venue)
    s["status"] = "RECONCILED"
    s["reconciled_at"] = now()
    touch(s)
    e["status"] = "SETTLED"
    touch(e)
    ticks.recompute_tour_counters(t)
    ticks.tick_tour(t)
    return success(s)


@bp.route("/tours/<tourId>/engagements/<engagementId>/settlement/mark-paid", methods=["POST"])
@require_roles("TourManager")
def mark_paid(tourId, engagementId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    s = H.get_settlement(engagementId)
    data = H.body()
    if s["status"] != "RECONCILED":
        raise err("ERR_SETTLEMENT_NOT_RECONCILED", "Settlement must be RECONCILED")
    expected = data.get("expected_settlement_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_settlement_version must be an integer")
    if expected != s["version"]:
        raise err("ERR_STALE_SETTLEMENT_VERSION",
                  "expected_settlement_version %s != current %s" % (expected, s["version"]))
    s["status"] = "PAID"
    touch(s)
    return success(s)


@bp.route("/tours/<tourId>/engagements/<engagementId>/settlement/dispute", methods=["POST"])
@require_roles("VenueBooker")
def dispute(tourId, engagementId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    s = H.get_settlement(engagementId)
    if s["status"] != "RECONCILED":
        raise err("ERR_SETTLEMENT_NOT_RECONCILED", "Settlement must be RECONCILED to dispute")
    s["status"] = "DISPUTED"
    touch(s)
    return success(s)


@bp.route("/tours/<tourId>/engagements/<engagementId>/settlement/resolve-dispute", methods=["POST"])
@require_roles("TourManager")
def resolve_dispute(tourId, engagementId):
    t = H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    s = H.get_settlement(engagementId)
    if s["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Settlement must be DISPUTED to resolve")
    venue = db.venues[e["venue_id"]]
    _recompute_settlement(s, e, t, venue)
    s["status"] = "RECONCILED"
    touch(s)
    return success(s)
