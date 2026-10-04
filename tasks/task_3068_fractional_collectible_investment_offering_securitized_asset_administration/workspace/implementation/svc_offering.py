"""Offering establishment, qualification, allocation, waitlist (§3.3, §3.5)."""
from envelope import ApiError, invalid_request, invalid_state, not_found, stale
from catalog import QUALIFICATION_DEADLINE_DAYS, RESCISSION_WINDOW_DAYS
from store import DB, parse_dt, to_ms, add_days
from models import (make_offering, make_subscription, refresh_overview,
                    insert_index, sort_by_creation)
from svc_common import (body, require, as_int, enum_value, recompute_offering_shares,
                        recompute_offering_cash, investor_holding, refund_subscription)
from calc import share_cap
import views


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _occ(payload, offering):
    expected = as_int(payload, "expected_offering_version")
    if expected is not None and int(expected) != int(offering["version"]):
        raise stale("expected_offering_version does not match the offering's version.")


def _require_offering(offering_id):
    row = DB.offerings.get(offering_id)
    if row is None:
        raise not_found("Offering %s does not exist." % offering_id)
    return row


def _artwork_of(offering):
    return DB.artworks.get(offering["artwork_id"])


def offering_subs(offering_id):
    return [s for s in DB.subscriptions.values() if s["offering_id"] == offering_id]


def rank_order(subs):
    return sorted(subs, key=lambda s: (s.get("created_at") or "", s.get("created_at_seq") or 0))


def rerank(offering_id):
    waiting = [s for s in offering_subs(offering_id) if s["status"] == "WAITLISTED"]
    for i, sub in enumerate(rank_order(waiting)):
        sub["waitlist_rank"] = i + 1
        sub["updated_at"] = to_ms(DB.now())
    return waiting


# ---------------------------------------------------------------------------
# Offering
# ---------------------------------------------------------------------------

def create_offering(artwork_id):
    artwork = DB.artworks.get(artwork_id)
    if artwork is None:
        raise not_found("Artwork %s does not exist." % artwork_id)
    data = body()
    require(data, ["total_shares", "price_per_share_cents", "exemption_type",
                   "registration_cap_pct", "liquidity_ratio_bps", "hold_period_days",
                   "management_fee_bps", "profit_participation_bps",
                   "cost_pass_through_bps", "preferred_return_bps"])
    as_int(data, "total_shares", minimum=1)
    as_int(data, "price_per_share_cents", minimum=1)
    enum_value(data, "exemption_type", "exemption_type")
    if not (artwork.get("artifacts_overview") or {}).get("is_authenticated"):
        raise invalid_state("The artwork has not cleared its authentication and "
                           "provenance trust chain.")
    if artwork["status"] != "AUTHENTICATED":
        raise invalid_state("Artwork is not in AUTHENTICATED.")
    row = make_offering(artwork, data)
    artwork["status"] = "OFFERING_PENDING"
    refresh_overview(artwork, bump=True)
    return views.offering(row), 201


def get_offering(offering_id):
    offering = _require_offering(offering_id)
    return views.offering(offering)


def list_offerings(query):
    rows = DB.ordered("offerings")
    artwork_id = query.get("artwork_id")
    if artwork_id:
        rows = [r for r in rows if r["artwork_id"] == artwork_id]
    status = query.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def qualification_filing(offering_id):
    offering = _require_offering(offering_id)
    data = body()
    require(data, ["circular_reference"])
    if offering["status"] != "DRAFT" or offering.get("circular_filed_at") is not None:
        raise invalid_state("The offering is not a DRAFT with no circular on file.")
    _occ(data, offering)
    if int(offering["total_shares"]) < 1 or int(offering["price_per_share_cents"]) < 1:
        raise invalid_request("total_shares and price_per_share_cents must be at least 1.")
    artwork = _artwork_of(offering)
    if not (artwork.get("artifacts_overview") or {}).get("is_authenticated"):
        raise invalid_state("The artwork is not authenticated.")
    now = to_ms(DB.now())
    offering["circular_filed_at"] = now
    offering["qualification_deadline_at"] = add_days(now, QUALIFICATION_DEADLINE_DAYS)
    offering["circular_reference"] = data.get("circular_reference")
    offering["status"] = "QUALIFICATION_FILED"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    artwork["status"] = "UNDER_OFFERING"
    refresh_overview(artwork, bump=True)
    return views.offering(offering)


def _clamp_pass(offering, subs):
    """The per-investor, per-subscription clamp in ALLOCATED_SUBSCRIPTION_RANK_ORDER."""
    cap = share_cap(offering["total_shares"], offering["registration_cap_pct"])
    by_investor = {}
    for sub in subs:
        by_investor.setdefault(sub["investor_id"], []).append(sub)
    ordered = []
    for investor_id, group in by_investor.items():
        group.sort(key=lambda s: (s.get("created_at") or "", s.get("created_at_seq") or 0))
        ordered.append(group)
    ordered.sort(key=lambda g: (g[0].get("created_at") or "", g[0].get("created_at_seq") or 0))
    results = []
    for group in ordered:
        running = 0
        for sub in group:
            room = max(0, cap - running)
            accepted = min(int(sub["requested_shares"]), room)
            running += accepted
            results.append((sub, accepted))
    return results


def allocate(offering_id):
    offering = _require_offering(offering_id)
    data = body()
    if offering["status"] != "QUALIFICATION_FILED":
        raise invalid_state("Allocation requires an offering in QUALIFICATION_FILED.")
    _occ(data, offering)
    now = to_ms(DB.now())
    deadline = parse_dt(offering.get("qualification_deadline_at"))
    if deadline is not None and now >= deadline:
        raise ApiError("ERR_QUALIFICATION_LAPSED",
                       "The qualification deadline has passed.")

    subs = offering_subs(offering_id)
    clampable = [s for s in subs if s["status"] in ("SUBSCRIBED", "REALLOCATED")]
    planned = _clamp_pass(offering, clampable)
    if sum(a for _, a in planned) < 1:
        raise ApiError("ERR_MINIMUM_NOT_MET",
                       "The offering has attracted no accepted shares.")

    artwork = _artwork_of(offering)
    for sub, accepted in planned:
        sub["accepted_shares"] = accepted
        sub["amount_due_cents"] = accepted * int(offering["price_per_share_cents"])
        sub["status"] = "SUBSCRIBED" if accepted >= 1 else "WAITLISTED"
        sub["waitlist_rank"] = None if accepted >= 1 else 0
        sub["updated_at"] = now
        sub["version"] = int(sub.get("version") or 1) + 1
        if accepted >= 1:
            investor = DB.investors.get(sub["investor_id"])
            if investor is not None:
                investor["lifetime_invested_cents"] = (
                    int(investor.get("lifetime_invested_cents") or 0)
                    + sub["amount_due_cents"])
                investor["updated_at"] = now
                investor["version"] = int(investor.get("version") or 1) + 1

    # subscriptions still RECEIVED past the deadline expire with their funds returned
    for sub in subs:
        if sub["status"] == "RECEIVED" and deadline is not None and now > deadline:
            sub["status"] = "EXPIRED"
            refund_subscription(sub)
            sub["updated_at"] = now
            sub["version"] = int(sub.get("version") or 1) + 1

    rerank(offering_id)
    offering["status"] = "ALLOCATED"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_offering_shares(offering)
    recompute_offering_cash(offering)
    artwork["status"] = "HELD"
    refresh_overview(artwork, bump=True)
    return views.offering(offering)

def waitlist_promotion(offering_id):
    offering = _require_offering(offering_id)
    data = body()
    _occ(data, offering)
    now = to_ms(DB.now())
    deadline = parse_dt(offering.get("qualification_deadline_at"))
    if deadline is not None and now >= deadline:
        raise ApiError("ERR_QUALIFICATION_LAPSED",
                       "The qualification deadline has passed.")
    waiting = [s for s in offering_subs(offering_id) if s["status"] == "WAITLISTED"]
    if not waiting:
        raise ApiError("ERR_WAITLIST_EMPTY",
                       "There is no subscription in WAITLISTED status.")
    rerank(offering_id)
    candidate = None
    for sub in waiting:
        if int(sub.get("waitlist_rank") or 0) == 1:
            candidate = sub
            break
    if candidate is None:
        raise invalid_state("No waiting subscription holds rank 1.")
    if int(offering["unsubscribed_shares"]) < 1:
        raise ApiError("ERR_OFFERING_FULL", "No unsubscribed share remains.")

    cap = share_cap(offering["total_shares"], offering["registration_cap_pct"])
    held = investor_holding(offering_id, candidate["investor_id"])
    held -= int(candidate.get("accepted_shares") or 0)
    room = max(0, cap - held)
    promoted = min(int(offering["unsubscribed_shares"]),
                   int(candidate["requested_shares"]), room)
    candidate["accepted_shares"] = promoted
    candidate["amount_due_cents"] = promoted * int(offering["price_per_share_cents"])
    candidate["status"] = "REALLOCATED"
    candidate["waitlist_rank"] = None
    candidate["updated_at"] = now
    candidate["version"] = int(candidate.get("version") or 1) + 1
    investor = DB.investors.get(candidate["investor_id"])
    if investor is not None and promoted >= 1:
        investor["lifetime_invested_cents"] = (
            int(investor.get("lifetime_invested_cents") or 0)
            + candidate["amount_due_cents"])
        investor["updated_at"] = now
        investor["version"] = int(investor.get("version") or 1) + 1
    rerank(offering_id)
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_offering_shares(offering)
    return views.offering(offering)


def waitlist_demotion(offering_id):
    offering = _require_offering(offering_id)
    data = body()
    require(data, ["subscription_id"])
    sub = DB.subscriptions.get(data.get("subscription_id"))
    if sub is None or sub["offering_id"] != offering_id:
        raise not_found("Subscription %s does not exist under this offering."
                        % data.get("subscription_id"))
    if sub["status"] != "REALLOCATED":
        raise invalid_state("Only a REALLOCATED subscription can be demoted.")
    _occ(data, offering)
    now = to_ms(DB.now())
    sub["accepted_shares"] = 0
    sub["amount_due_cents"] = 0
    sub["status"] = "WAITLISTED"
    sub["updated_at"] = now
    sub["version"] = int(sub.get("version") or 1) + 1
    rerank(offering_id)
    waiting = [s for s in offering_subs(offering_id) if s["status"] == "WAITLISTED"]
    sub["waitlist_rank"] = len(waiting)
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_offering_shares(offering)
    return views.subscription(sub)


def withdraw_offering(offering_id):
    offering = _require_offering(offering_id)
    data = body()
    require(data, ["reason"])
    status = offering["status"]
    if status not in ("QUALIFICATION_FILED", "ALLOCATED"):
        raise invalid_state("Only a filed or allocated offering may be withdrawn.")
    _occ(data, offering)
    now = to_ms(DB.now())
    deadline = parse_dt(offering.get("qualification_deadline_at"))
    if status == "QUALIFICATION_FILED":
        if int(offering.get("accepted_shares") or 0) != 0:
            raise invalid_state("A filed offering may be withdrawn only with zero "
                                "accepted shares.")
        artwork_status = "AUTHENTICATED"
    else:
        end = parse_dt(offering.get("holding_period_end_at"))
        if end is None or now >= end:
            raise ApiError("ERR_HOLD_PERIOD_ACTIVE",
                           "The holding period has run; the offering can only be sold.")
        artwork_status = "HELD"

    for sub in offering_subs(offering_id):
        refund_subscription(sub)
        sub["updated_at"] = now
        sub["version"] = int(sub.get("version") or 1) + 1
    offering["cash_ledger_cents"] = 0
    offering["status"] = "WITHDRAWN"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    artwork = _artwork_of(offering)
    artwork["status"] = artwork_status
    refresh_overview(artwork, bump=True)
    return views.offering(offering)


def abandon_offering(offering_id):
    offering = _require_offering(offering_id)
    data = body()
    require(data, ["reason"])
    if offering["status"] != "QUALIFICATION_FILED":
        raise invalid_state("Only a QUALIFICATION_FILED offering may be abandoned.")
    artwork = _artwork_of(offering)
    for other in DB.offerings.values():
        if other["id"] != offering["id"] and other["artwork_id"] == artwork["id"] \
                and other["status"] == "QUALIFICATION_FILED":
            raise invalid_state("The artwork carries another filed offering.")
    now = to_ms(DB.now())
    offering["status"] = "OFFERING_ABANDONED"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    artwork["status"] = "AUTHENTICATED"
    refresh_overview(artwork, bump=True)
    return views.offering(offering)


def list_subscriptions_of_offering(offering_id, query):
    _require_offering(offering_id)
    rows = sort_by_creation(offering_subs(offering_id))
    status = query.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def share_ledger(offering_id):
    offering = _require_offering(offering_id)
    accepted = [s for s in offering_subs(offering_id) if int(s.get("accepted_shares") or 0) > 0]
    by_investor = {}
    for sub in accepted:
        by_investor.setdefault(sub["investor_id"], []).append(sub)
    groups = []
    for investor_id, subs in by_investor.items():
        subs.sort(key=lambda s: (s.get("created_at") or "", s.get("created_at_seq") or 0))
        groups.append((subs[0], investor_id, subs))
    groups.sort(key=lambda g: (g[0].get("created_at") or "",
                               g[0].get("created_at_seq") or 0))
    price = int(offering["price_per_share_cents"])
    rows = []
    total_accepted = 0
    for first, investor_id, subs in groups:
        shares = sum(int(s["accepted_shares"]) for s in subs)
        investor = DB.investors.get(investor_id)
        rows.append({
            "investor_id": investor_id,
            "legal_name": investor.get("legal_name") if investor else None,
            "accepted_shares": shares,
            "accepted_cents": shares * price,
            "subscription_ids": [s["id"] for s in subs],
        })
        total_accepted += shares
    paid = sum(int(d["investor_residual_cents"]) for d in DB.distributions.values()
               if d["offering_id"] == offering_id and d["status"] == "PAID")
    return {
        "rows": rows,
        "total_accepted_shares": total_accepted,
        "total_accepted_cents": total_accepted * price,
        "total_distributed_cents": paid,
    }


def valuation(offering_id):
    offering = _require_offering(offering_id)
    return views.valuation(offering)
