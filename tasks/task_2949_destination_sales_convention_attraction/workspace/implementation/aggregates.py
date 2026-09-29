"""Derived aggregates and the numbered cascade hops of PRD 2.9, 3.4, 3.5 and 3.8.

No derived figure is ever supplied by a client and none is ever left stale:
whenever a primary record changes every aggregate downstream of it is recomputed
in the same request.  Every hop that mutates a versioned row bumps that row's
`version` and refreshes its `updated_at`; a hop whose condition is unmet does
not fire and leaves no trace.
"""

import datetime
from decimal import Decimal

import calc
import domain
import queries
from store import db, touch
from util import money, nights_of


# ==========================================================================
# MeetingPlanner
# ==========================================================================
def set_last_touch(planner):
    """Qualification, submission and the planner's own answer count as a touch."""
    if planner is None:
        return
    planner["last_touch_at"] = db.clock


def set_engaged(planner):
    if planner is not None:
        planner["engagement_status"] = "ENGAGED"


def recompute_planner(planner):
    """Re-derive the raw counters, both relationship scores and the tier."""
    if planner is None:
        return
    opportunities = queries.opportunities_of_planner(planner["id"])
    definite = [o for o in opportunities
                if o["sales_stage"] in ("DEFINITE", "SERVICED")]
    lost = [o for o in opportunities if o["sales_stage"] == "LOST"]

    definite_count = len(definite)
    lost_count = len(lost)
    lifetime_room_nights = (planner["legacy_definite_room_nights"]
                            + sum(o["definite_room_nights"] for o in definite))
    score_lifetime = calc.relationship_score(
        planner["legacy_definite_count"] + definite_count,
        lifetime_room_nights,
        lost_count,
    )

    window_start = calc.rolling_window_start()
    rolling_definite = [o for o in definite
                        if o["definite_at"] is not None
                        and o["definite_at"] >= window_start]
    rolling_lost = [o for o in lost if o["updated_at"] >= window_start]
    score_rolling = calc.relationship_score(
        len(rolling_definite),
        sum(o["definite_room_nights"] for o in rolling_definite),
        len(rolling_lost),
    )

    planner["definite_count"] = definite_count
    planner["lost_count"] = lost_count
    planner["lifetime_definite_room_nights"] = lifetime_room_nights
    planner["relationship_score_lifetime"] = score_lifetime
    planner["relationship_score_rolling_24m"] = score_rolling
    planner["tier"] = calc.tier_for(score_lifetime)


# ==========================================================================
# Hotel
# ==========================================================================
def opportunity_nights(opportunity):
    return nights_of(opportunity["arrival_date"], opportunity["departure_date"])


def hotel_night_loads(hotel_id):
    """Per-night occupied load from this property's COMMITTED commitments."""
    loads = {}
    for commitment in queries.commitments_of_hotel(hotel_id):
        if commitment["status"] != "COMMITTED":
            continue
        opportunity = db.opportunities.get(commitment["opportunity_id"])
        if opportunity is None:
            continue
        for night in opportunity_nights(opportunity):
            loads[night] = loads.get(night, 0) + commitment["rooms_peak_committed"]
    return loads


def recompute_hotel(hotel):
    """committed_peak_rooms is the MAXIMUM over every night of that night's
    occupied load -- an aggregate over dates, never a sum across them; while
    committed_room_nights is the plain sum over the COMMITTED commitments."""
    if hotel is None:
        return
    loads = hotel_night_loads(hotel["id"])
    peak = max(loads.values()) if loads else 0
    room_nights = sum(c["committed_room_nights"]
                      for c in queries.commitments_of_hotel(hotel["id"])
                      if c["status"] == "COMMITTED")
    if (hotel["committed_peak_rooms"] != peak
            or hotel["committed_room_nights"] != room_nights):
        hotel["committed_peak_rooms"] = peak
        hotel["committed_room_nights"] = room_nights
        touch(hotel)


def add_hotel_pickup(hotel, rooms):
    if hotel is None or not rooms:
        return
    hotel["pickup_room_nights"] += rooms
    touch(hotel)


# ==========================================================================
# Opportunity block readiness
# ==========================================================================
def recompute_block(opportunity):
    """Re-derived from commitments in status COMMITTED only (PRD 3.5)."""
    committed = [c for c in queries.commitments_of_opportunity(opportunity["id"])
                 if c["status"] == "COMMITTED"]
    peak = sum(c["rooms_peak_committed"] for c in committed)
    opportunity["committed_peak_rooms"] = peak
    opportunity["block_coverage_pct"] = money(
        Decimal(peak) * Decimal(100) / Decimal(opportunity["peak_rooms_requested"]))
    cutoffs = [c["cutoff_days_before_arrival"] for c in committed
               if c["cutoff_days_before_arrival"] is not None]
    opportunity["citywide_cutoff_days_before_arrival"] = max(cutoffs) if cutoffs else 0
    opportunity["cutoff_alignment_spread_days"] = (
        max(cutoffs) - min(cutoffs)) if len(cutoffs) >= 2 else 0


def set_posture(opportunity, posture):
    if opportunity["hold_posture"] != posture:
        opportunity["hold_posture"] = posture
        touch(opportunity)


def set_posture_released(opportunity):
    """hold_posture becomes RELEASED once no hold of that opportunity remains in
    status HELD or CHALLENGED.  The PRD attaches no precondition on the previous
    posture: a superseded lead whose only hold was a SECOND-rank option sits at
    NONE and still lands on RELEASED once that option is gone (PRD 3.4)."""
    if opportunity["hold_posture"] != "RELEASED":
        opportunity["hold_posture"] = "RELEASED"
        touch(opportunity)


# ==========================================================================
# IncentiveFund -- the conserved identity of PRD 2.10
# ==========================================================================
def recompute_fund(fund):
    """budget = uncommitted + committed + disbursed, then the derived posture."""
    fund["uncommitted_amount"] = money(
        fund["budget_amount"] - fund["committed_amount"] - fund["disbursed_amount"])
    residual = fund["uncommitted_amount"]
    if residual == 0:
        fund["posture"] = "EXHAUSTED"
    elif residual < fund["budget_amount"] * domain.FUND_CONSTRAINED_FRACTION:
        fund["posture"] = "CONSTRAINED"
    else:
        fund["posture"] = "OPEN"


def fund_commit(fund, amount):
    fund["committed_amount"] = money(fund["committed_amount"] + amount)
    recompute_fund(fund)
    touch(fund)


def fund_decommit(fund, amount):
    fund["committed_amount"] = money(fund["committed_amount"] - amount)
    recompute_fund(fund)
    touch(fund)


def fund_disburse(fund, amount):
    """committed falls and disbursed rises by the same amount, leaving budget and
    uncommitted untouched so the conservation identity still holds."""
    fund["committed_amount"] = money(fund["committed_amount"] - amount)
    fund["disbursed_amount"] = money(fund["disbursed_amount"] + amount)
    recompute_fund(fund)
    touch(fund)


def fund_post_receipt(fund, amount):
    fund["lodging_tax_receipts_total"] = money(
        fund["lodging_tax_receipts_total"] + amount)
    fund["budget_amount"] = money(fund["budget_amount"] + amount)
    recompute_fund(fund)
    touch(fund)


def decommit_charge(package):
    """The bid's live fund charge leaves the committed pool."""
    if package is None or not package.get("_charge_live"):
        return
    fund = db.funds.get(package.get("_fund_id"))
    amount = package["total_fund_charge_amount"]
    package["_charge_live"] = False
    if fund is not None and amount:
        fund_decommit(fund, amount)


def disburse_charge(package):
    if package is None or not package.get("_charge_live"):
        return
    fund = db.funds.get(package.get("_fund_id"))
    amount = package["total_fund_charge_amount"]
    package["_charge_live"] = False
    if fund is not None and amount:
        fund_disburse(fund, amount)


# ==========================================================================
# SpaceHold -- promotion, release, expiry and confirmation
# ==========================================================================
def promote_second_hold(departing, hall):
    """PRD 3.4: candidates are the holds on the same hall in status HELD with
    hold_rank SECOND whose buffered window conflicts with the departing hold's;
    the winner is the one whose opportunity has the largest
    peak_rooms_requested, ties broken by the hold's own created_at ascending."""
    if hall is None:
        return None
    candidates = [h for h in queries.holds_of_hall(hall["id"])
                  if h["id"] != departing["id"]
                  and h["status"] == "HELD"
                  and h["hold_rank"] == "SECOND"
                  and calc.holds_conflict(h, departing, hall)]
    if not candidates:
        return None

    def rank_key(hold):
        opportunity = db.opportunities.get(hold["opportunity_id"])
        peak = opportunity["peak_rooms_requested"] if opportunity else 0
        return (-peak, hold["created_at"], hold["_seq"])

    winner = sorted(candidates, key=rank_key)[0]
    winner["hold_rank"] = "FIRST"
    winner["expires_at"] = db.clock + datetime.timedelta(
        days=domain.PROMOTION_HOLD_DAYS)
    touch(winner)
    opportunity = db.opportunities.get(winner["opportunity_id"])
    if opportunity is not None:
        set_posture(opportunity, "TENTATIVE")
    return winner


def deactivate_hold(hold, new_status, release_reason, promote=True, bump_hall=True):
    """Hop 1 plus hop 2 (promotion) and hop 3 (the promoted lead's posture).
    The releasing opportunity's own posture is applied by the caller."""
    hold["status"] = new_status
    hold["release_reason"] = release_reason
    touch(hold)
    hall = db.halls.get(hold["center_hall_id"])
    promoted = promote_second_hold(hold, hall) if promote else None
    if bump_hall and hall is not None:
        touch(hall)
    return promoted


def after_hold_left_active_set(opportunity, allow_lost=True):
    """Hop 2 prime and hop 3 prime: the releasing lead's posture becomes
    RELEASED once no hold of its own remains in HELD or CHALLENGED, and a lead
    that was in BIDDING when it lost its last active hold falls to LOST with
    lost_reason SPACE_UNAVAILABLE."""
    if opportunity is None:
        return
    if queries.active_holds_of_opportunity(opportunity["id"]):
        return
    set_posture_released(opportunity)
    if allow_lost and opportunity["sales_stage"] == "BIDDING":
        lose_opportunity(opportunity, "SPACE_UNAVAILABLE")


def confirm_first_hold(opportunity):
    """The lead's FIRST-rank hold in HELD or CHALLENGED moves to CONFIRMED, the
    hall's confirmed_hold_count is incremented, and every other conflicting hold
    on that hall is superseded (PRD 3.4)."""
    target = None
    for hold in queries.holds_of_opportunity(opportunity["id"]):
        if hold["hold_rank"] == "FIRST" and hold["status"] in domain.ACTIVE_HOLD_STATUSES:
            target = hold
            break
    if target is None:
        return None
    if (target["status"] == "CHALLENGED"
            and target["challenge_deadline"] is not None
            and db.clock > target["challenge_deadline"]):
        # a lead that lets the fortnight run out cannot rescue the space
        return None
    hall = db.halls.get(target["center_hall_id"])
    target["status"] = "CONFIRMED"
    target["challenge_deadline"] = None
    target["challenged_by_space_hold_id"] = None
    touch(target)
    if hall is not None:
        hall["confirmed_hold_count"] += 1
        touch(hall)
        for other in queries.holds_of_hall(hall["id"]):
            if other["id"] == target["id"]:
                continue
            if other["status"] not in domain.ACTIVE_HOLD_STATUSES:
                continue
            if not calc.holds_conflict(other, target, hall):
                continue
            deactivate_hold(other, "RELEASED", "SUPERSEDED_BY_CONFIRMED",
                            promote=False, bump_hall=False)
            after_hold_left_active_set(
                db.opportunities.get(other["opportunity_id"]), allow_lost=False)
    set_posture(opportunity, "CONFIRMED")
    return target


def run_expiry_checkpoint():
    """The operations checkpoint of PRD 3.4, processing candidate holds in order
    of expires_at ascending with created_at ascending as the tiebreaker."""
    candidates = sorted(
        db.space_holds.values(),
        key=lambda h: (h["expires_at"] or db.clock, h["created_at"], h["_seq"]))
    expired_count = 0
    lapsed_count = 0
    promoted_ids = []
    for hold in candidates:
        promoted = None
        if (hold["status"] == "HELD" and hold["expires_at"] is not None
                and db.clock >= hold["expires_at"]):
            promoted = deactivate_hold(hold, "EXPIRED", "HOLD_EXPIRED")
            expired_count += 1
        elif (hold["status"] == "CHALLENGED"
              and hold["challenge_deadline"] is not None
              and db.clock > hold["challenge_deadline"]):
            promoted = deactivate_hold(hold, "RELEASED", "CHALLENGE_LAPSED")
            lapsed_count += 1
        else:
            continue
        if promoted is not None:
            promoted_ids.append(promoted["id"])
        after_hold_left_active_set(db.opportunities.get(hold["opportunity_id"]))
    return {
        "expired_count": expired_count,
        "lapsed_challenge_count": lapsed_count,
        "promoted_count": len(promoted_ids),
        "promoted_space_hold_ids": promoted_ids,
    }


# ==========================================================================
# RoomBlockCommitment cascades
# ==========================================================================
def recompute_commitment_attrition(commitment):
    shortfall, damages = calc.attrition_for_commitment(commitment)
    commitment["attrition_shortfall_nights"] = shortfall
    commitment["attrition_damages_amount"] = damages


def recompute_settlement(opportunity):
    """The lead's attrition_settlement_amount, recomputed on every pickup filed
    and frozen when the lead reaches SERVICED."""
    total = calc.settlement_amount(opportunity["id"])
    if opportunity["attrition_settlement_amount"] != total:
        opportunity["attrition_settlement_amount"] = total
        return True
    return False


def system_end_commitment(commitment, reason):
    """The fourth way a commitment ends (PRD 3.5): the owning lead reached
    SERVICED or LOST.  A COMMITTED commitment is RELEASED and its attrition
    figures are frozen; an INVITED or OFFERED one is WITHDRAWN."""
    if commitment["status"] == "COMMITTED":
        commitment["status"] = "RELEASED"
        commitment["withdraw_reason"] = reason
        recompute_commitment_attrition(commitment)
        touch(commitment)
        recompute_hotel(db.hotels.get(commitment["hotel_id"]))
    else:
        commitment["status"] = "WITHDRAWN"
        commitment["withdraw_reason"] = reason
        touch(commitment)


def apply_coverage_drop(opportunity):
    """Hops 3 and 4 of a COMMITTED withdrawal: a SUBMITTED bid of this lead
    returns to DRAFT when block_coverage_pct drops below 85.00, and its live fund
    charge is decommitted.  The caller bumps the opportunity once."""
    if opportunity["block_coverage_pct"] >= domain.BLOCK_COVERAGE_FLOOR:
        return
    package = None
    for row in queries.packages_of_opportunity(opportunity["id"]):
        if row["status"] == "SUBMITTED":
            package = row
            break
    if package is None:
        return
    package["status"] = "DRAFT"
    package["round_number"] += 1
    package["submitted_at"] = None
    package["response_due_at"] = None
    touch(package)
    opportunity["sales_stage"] = "QUALIFIED"
    decommit_charge(package)


# ==========================================================================
# Losing a lead -- one fixed set of consequences (PRD 3.8)
# ==========================================================================
def mapped_decline_reason(lost_reason):
    if lost_reason in ("RATE_TOO_HIGH", "INSUFFICIENT_INCENTIVE", "LOST_TO_COMPETITOR"):
        return lost_reason
    return "LOST_TO_COMPETITOR"


def lose_opportunity(opportunity, lost_reason, decline_live_package=False):
    # the stage change and the posture hop both land on the one opportunity row,
    # and the PRD pins the lead's version increment for a loss at exactly one
    before_version = opportunity["version"]
    opportunity["sales_stage"] = "LOST"
    opportunity["lost_reason"] = lost_reason
    touch(opportunity)

    live = queries.live_package(opportunity["id"])

    for hold in queries.holds_of_opportunity(opportunity["id"]):
        if hold["status"] in domain.ACTIVE_HOLD_STATUSES:
            deactivate_hold(hold, "RELEASED", "OPPORTUNITY_LOST")

    for commitment in queries.commitments_of_opportunity(opportunity["id"]):
        if commitment["status"] in domain.LIVE_COMMITMENT_STATUSES:
            system_end_commitment(commitment, "OPPORTUNITY_LOST")
    # no derived figure is ever left stale (PRD 2.9): the lead's citywide figures
    # are re-derived from the commitments that remain COMMITTED, of which the
    # lost cascade has left none.
    recompute_block(opportunity)

    decommit_charge(queries.charged_package(opportunity["id"]))

    for order in queries.servicing_orders_of_opportunity(opportunity["id"]):
        if order["status"] == "REQUESTED":
            order["status"] = "CANCELLED"
            touch(order)

    planner = db.planners.get(opportunity["planner_id"])
    if planner is not None:
        before = (planner["definite_count"], planner["lost_count"],
                  planner["lifetime_definite_room_nights"],
                  planner["relationship_score_lifetime"],
                  planner["relationship_score_rolling_24m"], planner["tier"])
        recompute_planner(planner)
        after = (planner["definite_count"], planner["lost_count"],
                 planner["lifetime_definite_room_nights"],
                 planner["relationship_score_lifetime"],
                 planner["relationship_score_rolling_24m"], planner["tier"])
        if before != after:
            touch(planner)

    if not queries.active_holds_of_opportunity(opportunity["id"]):
        set_posture_released(opportunity)

    if decline_live_package and live is not None:
        live["status"] = "DECLINED"
        live["decline_reason"] = mapped_decline_reason(lost_reason)
        touch(live)

    opportunity["version"] = before_version + 1
    opportunity["updated_at"] = db.clock


def refresh_planner_scores(opportunity):
    """Used when a lead enters DEFINITE or SERVICED."""
    planner = db.planners.get(opportunity["planner_id"])
    if planner is None:
        return
    before = (planner["definite_count"], planner["lost_count"],
              planner["lifetime_definite_room_nights"],
              planner["relationship_score_lifetime"],
              planner["relationship_score_rolling_24m"], planner["tier"])
    recompute_planner(planner)
    after = (planner["definite_count"], planner["lost_count"],
             planner["lifetime_definite_room_nights"],
             planner["relationship_score_lifetime"],
             planner["relationship_score_rolling_24m"], planner["tier"])
    if before != after:
        touch(planner)


# ==========================================================================
# Servicing bubble-up (PRD 3.9)
# ==========================================================================
def bubble_up_serviced(opportunity):
    """Whenever a delivery or a cancellation leaves no servicing order of the
    lead in REQUESTED or SCHEDULED, and at least one order is DELIVERED, the
    lead moves DEFINITE -> SERVICED."""
    if opportunity["sales_stage"] != "DEFINITE":
        return False
    orders = queries.servicing_orders_of_opportunity(opportunity["id"])
    if not orders:
        return False
    if any(o["status"] in domain.OPEN_SERVICING_STATUSES for o in orders):
        return False
    if not any(o["status"] == "DELIVERED" for o in orders):
        return False

    opportunity["sales_stage"] = "SERVICED"
    opportunity["attrition_settlement_amount"] = calc.settlement_amount(
        opportunity["id"])
    touch(opportunity)

    for commitment in queries.commitments_of_opportunity(opportunity["id"]):
        if commitment["status"] == "COMMITTED":
            system_end_commitment(commitment, "EVENT_SERVICED")
    opportunity["attrition_settlement_amount"] = calc.settlement_amount(
        opportunity["id"])

    disburse_charge(queries.charged_package(opportunity["id"]))

    for hold in queries.holds_of_opportunity(opportunity["id"]):
        if hold["status"] != "CONFIRMED":
            continue
        hold["status"] = "RELEASED"
        hold["release_reason"] = "EVENT_SERVICED"
        touch(hold)
        hall = db.halls.get(hold["center_hall_id"])
        if hall is not None:
            if hall["confirmed_hold_count"] > 0:
                hall["confirmed_hold_count"] -= 1
            touch(hall)

    refresh_planner_scores(opportunity)
    return True
