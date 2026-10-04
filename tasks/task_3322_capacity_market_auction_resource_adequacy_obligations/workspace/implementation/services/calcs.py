"""Business calculations per SCAFFOLD calculations table and PRD §3."""
from decimal import Decimal

from db import db
from util import (dec, q2, q3, q4, stamp, new_id, base_entity, base_ledger_entity, touch)
from errors import err_forecast_shares

NET_CONE = Decimal("390.00")
ACR_BASE = Decimal("60.00")
ACR_CREDIT_SLOPE = Decimal("0.10")
MITIGATION_FLOOR_FRACTION = Decimal("0.10")
HOURS_PER_DAY = Decimal("24.0")
SHORTAGE_PRICE = Decimal("390.00")


def _zone_children(zone):
    return [z for z in db.zones.values()
            if z["delivery_year_id"] == zone["delivery_year_id"]
            and z.get("parent_zone_id") == zone["id"]]


def _zone_depth(zone):
    depth = 0
    cur = zone
    while cur.get("parent_zone_id"):
        parent = db.zones.get(cur["parent_zone_id"])
        if parent is None:
            break
        depth += 1
        cur = parent
    return depth


def peak_load_requirement(dy, forecast):
    """calc peak_load_requirement — runs at lock-forecast."""
    ici = dec(forecast["rto_peak_load_mw"]) * (Decimal(1) + dec(forecast["reserve_margin_pct"]))
    rto_req = ici * (Decimal(1) - dec(forecast["pool_wide_avg_eford"]))
    shares = forecast["zonal_peak_shares"]

    zones = [z for z in db.zones.values() if z["delivery_year_id"] == dy["id"]]
    tops = [z for z in zones if z.get("parent_zone_id") is None]

    def assign(zone, parent_req):
        if parent_req is None:
            share = dec(shares.get(zone["zone_code"], "0"))
            req = q3(rto_req * share)
        else:
            children = _zone_children(db.zones[zone["parent_zone_id"]])
            code = zone["zone_code"]
            if code in shares:
                lda_share = dec(shares[code])
            elif len(children) == 1:
                lda_share = Decimal(1)
            else:
                raise err_forecast_shares(
                    f"No LDA share for zone {code} and it is not the only child of its parent")
            req = q3(dec(parent_req) * lda_share)
        zone["zonal_requirement_mw"] = req
        touch(zone)
        for child in _zone_children(zone):
            assign(child, req)

    for t in tops:
        assign(t, None)

    dy["reliability_requirement_mw"] = q3(rto_req)
    dy["forecast_version"] = forecast["revision"]


def locked_or_draft_eford(delivery_year_id):
    """pool_wide_avg_eford from the LOCKED forecast, else highest-revision DRAFT."""
    locked = [f for f in db.forecasts.values()
              if f["delivery_year_id"] == delivery_year_id and f["status"] == "LOCKED"]
    if locked:
        return dec(max(locked, key=lambda f: f["revision"])["pool_wide_avg_eford"])
    drafts = [f for f in db.forecasts.values()
              if f["delivery_year_id"] == delivery_year_id and f["status"] == "DRAFT"]
    if drafts:
        return dec(max(drafts, key=lambda f: f["revision"])["pool_wide_avg_eford"])
    return None


def accreditation_ucap(acc, resource):
    """calc accreditation_ucap — returns (factor: Decimal 4dp, ucap: Decimal 3dp)."""
    if acc["method"] == "CLASS_AVG":
        factor = dec(acc["class_avg_factor"])
    else:
        base = dec(acc["unit_elcc_factor"])
        pool_eford = locked_or_draft_eford(acc["delivery_year_id"])
        if pool_eford is None:
            pool_eford = Decimal(0)
        denom = Decimal(1) - pool_eford
        if denom <= 0:
            outage_derate = Decimal(1)
        else:
            outage_derate = (Decimal(1) - dec(acc["forced_outage_rate"])) / denom
        sample_confidence = min(Decimal(1), dec(acc["scarcity_hours_sampled"]) / Decimal(100))
        factor = base * outage_derate * sample_confidence
    factor = min(factor, Decimal(1))
    factor = q4(factor)
    ucap = q3(dec(resource["nameplate_mw"]) * factor)
    return factor, ucap


def seller_offer_cap(owner):
    """calc seller_offer_cap — returns Decimal 2dp."""
    acr = ACR_BASE + ACR_CREDIT_SLOPE * (Decimal(1000) - dec(owner["credit_score"]))
    cap = max(MITIGATION_FLOOR_FRACTION * NET_CONE, acr)
    cap = min(cap, NET_CONE)
    return q2(cap)


def _offer_zone(offer):
    res = db.resources.get(offer["resource_id"])
    return db.zones.get(res["zone_id"]) if res else None


def auction_clearing(run):
    """calc auction_clearing. Mutates zones, offers; creates commitments."""
    dy = db.delivery_years[run["delivery_year_id"]]
    zones = [z for z in db.zones.values() if z["delivery_year_id"] == dy["id"]]
    sealed = [o for o in db.offers.values()
              if o["auction_run_id"] == run["id"] and o["status"] == "SEALED"]

    # merit order: effective_price ASC, sealed_at ASC, created_at ASC
    sealed_dt = run.get("_sealed_dt")
    sealed.sort(key=lambda o: (dec(o["effective_price_per_mw_day"]),
                               sealed_dt if sealed_dt else o["_created_dt"],
                               o["_created_dt"]))

    zone_by_id = {z["id"]: z for z in zones}
    top_zone = next((z for z in zones if z.get("parent_zone_id") is None), None)

    remaining = {}   # offer_id -> Decimal offer_mw left
    for o in sealed:
        remaining[o["id"]] = q3(dec(o["offer_mw"]))

    # remaining requirement per zone (LDA and RTO)
    zone_req = {}
    for z in zones:
        zone_req[z["id"]] = q3(dec(z["zonal_requirement_mw"]))

    marginal_price = {}  # zone_id -> Decimal or None

    def clear_offers(zone, candidate_offers, req_amount):
        """Clear candidate offers (merit order) against req_amount within zone.
        Returns (cleared_total, marginal_price_or_None)."""
        cleared_total = Decimal(0)
        marg = None
        remaining_req = req_amount
        for o in candidate_offers:
            if remaining_req <= 0:
                break
            avail = remaining[o["id"]]
            if avail <= 0:
                continue
            take = min(avail, remaining_req)
            take = q3(take)
            remaining[o["id"]] = q3(avail - take)
            cleared_total = q3(cleared_total + take)
            remaining_req = q3(remaining_req - take)
            o["cleared_mw"] = q3(dec(o["cleared_mw"]) + take)
            marg = dec(o["effective_price_per_mw_day"])
        return cleared_total, marg

    # Clear nested LDAs deepest-first
    nested = sorted([z for z in zones if z.get("parent_zone_id") is not None],
                    key=_zone_depth, reverse=True)
    for z in nested:
        req = zone_req[z["id"]]
        if req <= 0:
            marginal_price[z["id"]] = None
            continue
        internal = [o for o in sealed
                    if remaining[o["id"]] > 0 and _offer_zone(o) and _offer_zone(o)["id"] == z["id"]]
        internal_supply = sum((remaining[o["id"]] for o in internal), Decimal(0))
        import_need = max(Decimal(0), req - internal_supply)
        limit = z.get("import_limit_mw")
        if limit is None:
            importable = import_need
        else:
            importable = min(import_need, dec(limit))

        cleared = Decimal(0)
        marg = None
        # internal first (cheapest-first within zone)
        c, m = clear_offers(z, internal, req)
        cleared = q3(cleared + c)
        if m is not None:
            marg = m
        # then imports up to importable
        if importable > 0 and cleared < req:
            imported = [o for o in sealed
                        if remaining[o["id"]] > 0 and _offer_zone(o)
                        and _offer_zone(o)["id"] != z["id"]]
            c2, m2 = clear_offers(z, imported, min(importable, q3(req - cleared)))
            cleared = q3(cleared + c2)
            if m2 is not None:
                marg = m2
        if cleared < req:
            marg = SHORTAGE_PRICE  # shortage pricing
        marginal_price[z["id"]] = marg
        zone_req[z["id"]] = q3(req - cleared) if cleared < req else Decimal(0)

    # RTO-wide zone: requirement minus MW counted toward nested LDA requirements
    if top_zone is not None:
        lda_cleared_total = Decimal(0)
        for z in nested:
            orig = q3(dec(z["zonal_requirement_mw"]))
            left = zone_req[z["id"]]
            lda_cleared_total = q3(lda_cleared_total + (orig - left))
        rto_req = q3(dec(dy["reliability_requirement_mw"]) - lda_cleared_total)
        if rto_req < 0:
            rto_req = Decimal(0)
        candidates = [o for o in sealed if remaining[o["id"]] > 0]
        cleared, marg = clear_offers(top_zone, candidates, rto_req)
        # PRD §3.4: the RTO-wide zone's price is the marginal offer's
        # effective price; the 390.00 shortage price is named only for
        # nested LDAs whose requirement is not fully met.
        marginal_price[top_zone["id"]] = marg

    # Step 3: price separation upward — child price = max(child, parent)
    for z in zones:
        if z.get("parent_zone_id") is not None:
            parent_price = marginal_price.get(z["parent_zone_id"])
            own = marginal_price.get(z["id"])
            if parent_price is not None:
                if own is None or own < parent_price:
                    marginal_price[z["id"]] = parent_price

    # Step 4: finalize offers — statuses, zone prices, commitments
    for z in zones:
        z["clearing_price_per_mw_day"] = marginal_price.get(z["id"])
        touch(z)
    # zone cleared_mw: total cleared from offers located in the zone
    for z in zones:
        total = Decimal(0)
        for o in sealed:
            oz = _offer_zone(o)
            if oz and oz["id"] == z["id"]:
                total = q3(total + dec(o["cleared_mw"]))
        z["cleared_mw"] = total

    for o in sealed:
        cm = dec(o["cleared_mw"])
        om = dec(o["offer_mw"])
        if cm <= 0:
            o["status"] = "REJECTED"
        elif cm >= om:
            o["status"] = "CLEARED"
        else:
            o["status"] = "PARTIALLY_CLEARED"
        touch(o)
        if cm > 0:
            res = db.resources[o["resource_id"]]
            z = db.zones[res["zone_id"]]
            price = z["clearing_price_per_mw_day"]
            commit = base_entity()
            commit.update({
                "resource_id": res["id"],
                "offer_id": o["id"],
                "delivery_year_id": dy["id"],
                "committed_mw": cm,
                "clearing_price_per_mw_day": price,
                "daily_revenue_dollars": q2(cm * dec(price)),
                "status": "ACTIVE",
                "cumulative_performance_score": Decimal("0"),
            })
            db.commitments[commit["id"]] = commit


def performance_ratio(assessment):
    expected = dec(assessment["expected_mw"])
    actual = dec(assessment["actual_mw"])
    if expected == 0:
        return Decimal("1.0000")
    r = actual / expected
    if r > Decimal("1.5"):
        r = Decimal("1.5")
    return q4(r)


def nonperformance_charge(assessment, commitment, event):
    """Returns Decimal 2dp signed amount (negative = charge owed)."""
    expected = dec(assessment["expected_mw"])
    actual = dec(assessment["actual_mw"])
    if expected == 0:
        return Decimal("0.00")
    start = assessment["_event_start"]
    end = assessment["_event_end"]
    H = dec(str((end - start).total_seconds())) / Decimal(3600)
    P = dec(commitment["clearing_price_per_mw_day"])
    BR = P / HOURS_PER_DAY
    shortfall = max(Decimal(0), expected - actual)
    over = max(Decimal(0), actual - expected)
    r = actual / expected  # unrounded ratio for tier boundary
    if r >= Decimal("0.6"):
        mult = Decimal("1.0")
    elif r >= Decimal("0.3"):
        mult = Decimal("1.5")
    else:
        mult = Decimal("2.0")
    charge = shortfall * BR * H * mult
    bonus = Decimal(0)
    if shortfall == 0 and expected > 0:
        bonus = min(over, Decimal("0.5") * expected) * BR * H
    return q2(bonus - charge)


def recompute_commitment_score(commitment):
    """Weighted average of performance_ratio over FINALIZED assessments, weighted by assessed_mwh."""
    finals = [a for a in db.assessments.values()
              if a["commitment_id"] == commitment["id"] and a["status"] == "FINALIZED"]
    if not finals:
        commitment["cumulative_performance_score"] = Decimal("0")
        return
    total_w = sum((dec(a["assessed_mwh"]) for a in finals), Decimal(0))
    if total_w == 0:
        # all weights zero: simple average
        avg = sum((dec(a["performance_ratio"]) for a in finals), Decimal(0)) / Decimal(len(finals))
        commitment["cumulative_performance_score"] = q4(avg)
        return
    s = sum((dec(a["performance_ratio"]) * dec(a["assessed_mwh"]) for a in finals), Decimal(0))
    commitment["cumulative_performance_score"] = q4(s / total_w)


def post_settlement_entry(delivery_year_id, commitment_id, emergency_event_id, entry_type, amount):
    entry = base_ledger_entity()
    entry.update({
        "delivery_year_id": delivery_year_id,
        "commitment_id": commitment_id,
        "emergency_event_id": emergency_event_id,
        "entry_type": entry_type,
        "amount_dollars": q2(dec(amount)),
    })
    db.settlement_entries[entry["id"]] = entry
    return entry


def redistribution_pool(event):
    """calc redistribution_pool for one ASSESSED event. Posts REDISTRIBUTION entries."""
    finals = [a for a in db.assessments.values()
              if a["emergency_event_id"] == event["id"] and a["status"] == "FINALIZED"]
    pool = Decimal(0)
    for a in finals:
        amt = dec(a["charge_or_credit_dollars"])
        if amt < 0:
            pool += -amt
        else:
            pool -= amt
    if pool <= 0:
        return
    performers = [a for a in finals if dec(a["performance_ratio"]) >= Decimal("1.0")]
    if not performers:
        return
    performers.sort(key=lambda a: (a["_created_dt"], a["id"]))
    total_w = sum((dec(a["assessed_mwh"]) for a in performers), Decimal(0))
    if total_w == 0:
        return
    running = Decimal(0)
    for i, a in enumerate(performers):
        if i < len(performers) - 1:
            share = q2(pool * dec(a["assessed_mwh"]) / total_w)
            running += share
        else:
            share = q2(pool - running)
        post_settlement_entry(event["delivery_year_id"], a["commitment_id"],
                              event["id"], "REDISTRIBUTION", share)


def mv_verified_ucap(report, resource):
    """calc mv_verified_ucap — returns Decimal 3dp."""
    start = report["_start_dt"]
    end = report["_end_dt"]
    window_hours = dec(str((end - start).total_seconds())) / Decimal(3600)
    if window_hours <= 0:
        window_hours = Decimal(1)
    delivered = min(dec(report["metered_mwh"]), dec(report["baseline_mwh"]))
    avg_mw = delivered / window_hours
    factor = Decimal(1)
    for acc in db.accreditations.values():
        if (acc["resource_id"] == resource["id"]
                and acc["delivery_year_id"] == report["delivery_year_id"]
                and acc["status"] == "EFFECTIVE"):
            factor = dec(acc["accreditation_factor"])
            break
    return q3(avg_mw * factor)


def recompute_must_offer(resource):
    """must_offer = True iff GEN resource has a commitment in the immediately prior delivery year."""
    if resource["resource_type"] != "GEN":
        resource["must_offer"] = False
        return
    # find the delivery year ordering by planning_period_start
    years = sorted(db.delivery_years.values(), key=lambda d: d["_start_dt"])
    prior_year_ids = set()
    for i, y in enumerate(years):
        if i > 0:
            prior_year_ids.add(years[i - 1]["id"])
    has_prior = any(
        c["resource_id"] == resource["id"] and c["delivery_year_id"] in prior_year_ids
        for c in db.commitments.values()
    )
    resource["must_offer"] = bool(has_prior)
