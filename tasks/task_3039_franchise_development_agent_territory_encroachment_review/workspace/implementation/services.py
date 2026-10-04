"""Domain services: serializers, calculations, cascades."""
from decimal import Decimal, ROUND_HALF_UP

from core import DB, clock_now, fmt_dt, base_fields, touch

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_territory(t):
    d = base_fields(t)
    d.update({
        "code": t["code"],
        "region": t["region"],
        "royalty_rate_pct": t["royalty_rate_pct"],
        "development_quota_stores": t["development_quota_stores"],
        "assigned_agent_id": t["assigned_agent_id"],
        "status": t["status"],
        "open_store_count": compute_open_store_count(t["id"]),
    })
    return d


def ser_agent(a):
    d = base_fields(a)
    d.update({
        "legal_name": a["legal_name"],
        "contact_email": a["contact_email"],
        "agreement_start": fmt_dt(a["agreement_start"]),
        "agreement_end": fmt_dt(a["agreement_end"]),
        "status": a["status"],
        "underperformance_strikes": a["underperformance_strikes"],
        "performance_score": compute_performance_score(a["id"]),
    })
    return d


def ser_franchisee(f):
    d = base_fields(f)
    d.update({
        "legal_name": f["legal_name"],
        "contact_email": f["contact_email"],
        "status": f["status"],
    })
    return d


def ser_store(s):
    d = base_fields(s)
    d.update({
        "store_number": s["store_number"],
        "territory_id": s["territory_id"],
        "franchisee_id": s["franchisee_id"],
        "address": s["address"],
        "geo_lat": s["geo_lat"],
        "geo_lng": s["geo_lng"],
        "opened_on": fmt_dt(s["opened_on"]),
        "estimated_weekly_sales_cents": s["estimated_weekly_sales_cents"],
        "actual_avg_weekly_sales_cents": s["actual_avg_weekly_sales_cents"],
        "status": s["status"],
        "consecutive_failed_inspections": s["consecutive_failed_inspections"],
        "source_site_application_id": s["source_site_application_id"],
    })
    return d


def ser_application(ap):
    d = base_fields(ap)
    d.update({
        "territory_id": ap["territory_id"],
        "applicant_franchisee_id": ap["applicant_franchisee_id"],
        "proposed_address": ap["proposed_address"],
        "proposed_lat": ap["proposed_lat"],
        "proposed_lng": ap["proposed_lng"],
        "proposed_open_date": fmt_dt(ap["proposed_open_date"]),
        "store_id": ap["store_id"],
        "status": ap["status"],
        "revision_count": ap["revision_count"],
        "approved_on": fmt_dt(ap["approved_on"]),
    })
    return d


def ser_impact_study(st):
    d = base_fields(st)
    d.update({
        "site_application_id": st["site_application_id"],
        "radius_miles": st["radius_miles"],
        "affected_store_count": st["affected_store_count"],
        "provisional_impact_cents": st["provisional_impact_cents"],
        "final_impact_cents": st["final_impact_cents"],
        "status": st["status"],
    })
    return d


def ser_protest(p):
    d = base_fields(p)
    d.update({
        "site_application_id": p["site_application_id"],
        "protesting_store_id": p["protesting_store_id"],
        "protesting_franchisee_id": p["protesting_franchisee_id"],
        "grounds": p["grounds"],
        "filed_on": fmt_dt(p["filed_on"]),
        "mediator_ref": p["mediator_ref"],
        "mediation_deadline": fmt_dt(p["mediation_deadline"]),
        "resolution": p["resolution"],
        "status": p["status"],
    })
    return d


def ser_transfer(tr):
    d = base_fields(tr)
    d.update({
        "store_id": tr["store_id"],
        "seller_franchisee_id": tr["seller_franchisee_id"],
        "buyer_franchisee_id": tr["buyer_franchisee_id"],
        "sale_price_cents": tr["sale_price_cents"],
        "transfer_fee_cents": tr["transfer_fee_cents"],
        "status": tr["status"],
    })
    return d


def ser_enrollment(e):
    d = base_fields(e)
    d.update({
        "franchisee_id": e["franchisee_id"],
        "program_code": e["program_code"],
        "expires_on": fmt_dt(e["expires_on"]),
        "score": e["score"],
        "completed_on": fmt_dt(e["completed_on"]),
        "status": e["status"],
    })
    return d


def ser_mandate(m):
    d = base_fields(m)
    d.update({
        "store_id": m["store_id"],
        "due_by": fmt_dt(m["due_by"]),
        "financing_option": m["financing_option"],
        "estimated_cost_cents": m["estimated_cost_cents"],
        "closure_start": fmt_dt(m["closure_start"]),
        "closure_end": fmt_dt(m["closure_end"]),
        "downtime_days": m["downtime_days"],
        "downtime_charge_cents": m["downtime_charge_cents"],
        "status": m["status"],
    })
    return d


def ser_inspection(i):
    d = base_fields(i)
    d.update({
        "store_id": i["store_id"],
        "inspector_ref": i["inspector_ref"],
        "scheduled_on": fmt_dt(i["scheduled_on"]),
        "food_safety_score": i["food_safety_score"],
        "cleanliness_score": i["cleanliness_score"],
        "operations_score": i["operations_score"],
        "critical_violations": i["critical_violations"],
        "final_score": i["final_score"],
        "outcome": i["outcome"],
        "status": i["status"],
    })
    return d


def ser_promotion(p):
    d = base_fields(p)
    d.update({
        "name": p["name"],
        "voting_open": fmt_dt(p["voting_open"]),
        "voting_close": fmt_dt(p["voting_close"]),
        "active_start": fmt_dt(p["active_start"]),
        "active_end": fmt_dt(p["active_end"]),
        "base_cost_per_store_cents": p["base_cost_per_store_cents"],
        "eligible_voter_count": p["eligible_voter_count"],
        "votes_for": p["votes_for"],
        "votes_against": p["votes_against"],
        "votes_abstain": p["votes_abstain"],
        "participating_store_count": p["participating_store_count"],
        "store_share_cents": p["store_share_cents"],
        "total_pool_cents": p["total_pool_cents"],
        "status": p["status"],
    })
    return d


def ser_vote(v):
    d = base_fields(v)
    d.update({
        "promotion_id": v["promotion_id"],
        "store_id": v["store_id"],
        "franchisee_id": v["franchisee_id"],
        "ballot": v["ballot"],
        "retracted": v["retracted"],
    })
    return d


def ser_dispute(dsp):
    d = base_fields(dsp)
    d.update({
        "promotion_id": dsp["promotion_id"],
        "store_id": dsp["store_id"],
        "disputed_amount_cents": dsp["disputed_amount_cents"],
        "reason": dsp["reason"],
        "resolution": dsp["resolution"],
        "status": dsp["status"],
    })
    return d


def ser_statement(fs):
    d = base_fields(fs)
    d.update({
        "development_agent_id": fs["development_agent_id"],
        "territory_id": fs["territory_id"],
        "period_start": fmt_dt(fs["period_start"]),
        "period_end": fmt_dt(fs["period_end"]),
        "gross_fees_cents": fs["gross_fees_cents"],
        "da_share_cents": fs["da_share_cents"],
        "franchisor_share_cents": fs["franchisor_share_cents"],
        "variant": fs["variant"],
        "status": fs["status"],
    })
    return d


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round2(x):
    """Round half up to 2 decimal places; returns a float with 2dp value."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round0(x):
    """Round half up to whole units; returns an int."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Derived fields / calculations
# ---------------------------------------------------------------------------
OPEN_COUNT_STATUSES = {"OPEN", "CLOSED_FOR_REMODEL", "PROBATION", "TERMINATION_PENDING"}


def compute_open_store_count(territory_id):
    return sum(1 for s in DB["stores"].values()
               if s["territory_id"] == territory_id and s["status"] in OPEN_COUNT_STATUSES)


DEGREES_PER_MILE = Decimal("0.0145")
BAND_NEAR = Decimal("0.01")
BAND_MID = Decimal("0.02")
BAND_FAR = Decimal("0.04")


def bucket_pct(dist_deg):
    if dist_deg < BAND_NEAR:
        return Decimal("0.12")
    if dist_deg < BAND_MID:
        return Decimal("0.07")
    if dist_deg < BAND_FAR:
        return Decimal("0.03")
    return Decimal("0")


def compute_impact(study, variant):
    """Compute (affected_store_count, impact_cents) for the study."""
    ap = DB["site_applications"][study["site_application_id"]]
    radius_deg = Decimal(str(study["radius_miles"])) * DEGREES_PER_MILE
    total = Decimal("0")
    affected = 0
    stores = sorted(
        (s for s in DB["stores"].values()
         if s["territory_id"] == ap["territory_id"]
         and s["status"] in ("OPEN", "CLOSED_FOR_REMODEL", "PROBATION")),
        key=lambda s: s["_seq"],
    )
    for s in stores:
        dist = Decimal(str(abs(s["geo_lat"] - ap["proposed_lat"]))) + \
               Decimal(str(abs(s["geo_lng"] - ap["proposed_lng"])))
        if not (dist < radius_deg):
            continue
        pct = bucket_pct(dist)
        if pct == 0:
            continue
        affected += 1
        base = (s["estimated_weekly_sales_cents"] if variant == "provisional"
                else s["actual_avg_weekly_sales_cents"])
        line = (Decimal(str(base)) * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += line
    return affected, float(total)


def compute_transfer_fee(sale_price_cents, opened_on, now):
    age_days = (now - opened_on).days
    age_years = age_days // 365
    if sale_price_cents < 25_000_000:
        fee = Decimal("500000")
    elif sale_price_cents < 75_000_000:
        fee = (Decimal(str(sale_price_cents)) * Decimal("0.02")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
    else:
        fee = (Decimal(str(sale_price_cents)) * Decimal("0.015")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
    if age_years >= 10:
        fee = (fee * Decimal("0.90")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(fee)


ALLOWANCE_DAYS = {"SELF_FINANCED": 21, "DA_LOAN": 28, "FRANCHISOR_DEFERRAL": 14}
OVERAGE_PER_DAY_CENTS = 150000


def downtime_allowance(financing_option):
    return ALLOWANCE_DAYS[financing_option]


def compute_downtime_charge(mandate):
    if mandate["downtime_days"] is None:
        return 0
    overage = max(0, mandate["downtime_days"] - downtime_allowance(mandate["financing_option"]))
    return overage * OVERAGE_PER_DAY_CENTS


def compute_final_score(ins):
    fs = (Decimal(str(ins["food_safety_score"])) * Decimal("0.40")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    cs = (Decimal(str(ins["cleanliness_score"])) * Decimal("0.30")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    os_ = (Decimal(str(ins["operations_score"])) * Decimal("0.30")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    penalty = Decimal(str(ins["critical_violations"])) * Decimal("2.50")
    total = (fs + cs + os_ - penalty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if total < 0:
        total = Decimal("0.00")
    return float(total)


def compute_performance_score(agent_id):
    territories = [t for t in DB["territories"].values()
                   if t["assigned_agent_id"] == agent_id]
    tids = {t["id"] for t in territories}
    # approval rate
    apps = [a for a in DB["site_applications"].values()
            if a["territory_id"] in tids and a["status"] != "DRAFT"]
    if apps:
        approved = sum(1 for a in apps
                       if a["status"] in ("APPROVED", "PROTESTED"))
        approval_rate = Decimal(approved) / Decimal(len(apps))
    else:
        approval_rate = Decimal("0")
    # inspection pass rate
    store_ids = {s["id"] for s in DB["stores"].values() if s["territory_id"] in tids}
    finals = [i for i in DB["inspections"].values()
              if i["store_id"] in store_ids and i["status"] == "FINALIZED"]
    if finals:
        passes = sum(1 for i in finals if i["outcome"] == "PASS")
        pass_rate = Decimal(passes) / Decimal(len(finals))
    else:
        pass_rate = Decimal("0")
    # remodel on-time rate
    completed = [m for m in DB["mandates"].values()
                 if m["store_id"] in store_ids and m["status"] == "COMPLETED"]
    if completed:
        on_time = sum(
            1 for m in completed
            if (m["downtime_days"] is not None
                and m["downtime_days"] <= downtime_allowance(m["financing_option"])))
        on_time_rate = Decimal(on_time) / Decimal(len(completed))
    else:
        on_time_rate = Decimal("0")
    score = (Decimal("100") * (Decimal("0.30") * approval_rate
                               + Decimal("0.40") * pass_rate
                               + Decimal("0.30") * on_time_rate)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(score)


def compute_fee_split(territory, period_start, period_end, variant):
    """Returns (gross, da_share, franchisor_share) in whole cents."""
    weeks = round0(Decimal(str((period_end - period_start).total_seconds()))
                   / Decimal(str(7 * 86400)))
    t_stores = [s for s in DB["stores"].values()
                if s["territory_id"] == territory["id"]]
    store_count = sum(1 for s in t_stores
                      if s["status"] in ("PIPELINE", "OPEN", "CLOSED_FOR_REMODEL", "PROBATION"))
    tier_pct = Decimal("0.45") if store_count >= 5 else Decimal("0.40")
    rate = Decimal(str(territory["royalty_rate_pct"]))
    gross = Decimal("0")
    for s in sorted(t_stores, key=lambda s: s["_seq"]):
        if variant == "PROVISIONAL_ESTIMATE":
            if s["status"] not in ("OPEN", "PIPELINE"):
                continue
            base = s["estimated_weekly_sales_cents"]
        else:
            if s["status"] != "OPEN":
                continue
            base = s["actual_avg_weekly_sales_cents"]
        line = (Decimal(str(base)) * rate * Decimal(weeks)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        gross += line
    da_share = (gross * tier_pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    franchisor_share = gross - da_share
    return int(gross), int(da_share), int(franchisor_share)


# ---------------------------------------------------------------------------
# Shared cascades
# ---------------------------------------------------------------------------
def cancel_inflight_transfers(store_id):
    for tr in DB["transfer_requests"].values():
        if tr["store_id"] == store_id and \
                tr["status"] in ("PENDING", "BUYER_TRAINING", "PENDING_APPROVAL"):
            tr["status"] = "CANCELLED"
            touch(tr)


def void_provisional_studies(application_id, also_final=False):
    for st in DB["impact_studies"].values():
        if st["site_application_id"] != application_id:
            continue
        if st["status"] == "PROVISIONAL" or \
                (also_final and st["status"] == "FINAL"):
            st["status"] = "VOID"
            touch(st)


def suspend_territory_applications(territory_id):
    for ap in DB["site_applications"].values():
        if ap["territory_id"] == territory_id and \
                ap["status"] in ("SUBMITTED", "IMPACT_REVIEW"):
            ap["status"] = "SUSPENDED"
            touch(ap)
            void_provisional_studies(ap["id"])


def resume_territory_applications(territory_id):
    for ap in DB["site_applications"].values():
        if ap["territory_id"] == territory_id and ap["status"] == "SUSPENDED":
            ap["status"] = "SUBMITTED"
            touch(ap)


def franchisee_activate_if_prospect(franchisee_id):
    f = DB["franchisees"].get(franchisee_id)
    if f is not None and f["status"] == "PROSPECT":
        f["status"] = "ACTIVE"
        touch(f)


def terminate_store(store):
    """Shared terminal cascade for a store entering TERMINATED."""
    store["status"] = "TERMINATED"
    touch(store)
    for m in DB["mandates"].values():
        if m["store_id"] == store["id"] and \
                m["status"] in ("ISSUED", "SCHEDULED", "OVERDUE"):
            m["status"] = "WAIVED"
            touch(m)


def finalize_protest_resolution(protest, resolution):
    """Apply terminal resolution and cross-entity side effects."""
    protest["resolution"] = resolution
    protest["status"] = "RESOLVED_UPHELD" if resolution == "UPHELD" else "RESOLVED_REJECTED"
    touch(protest)
    ap = DB["site_applications"].get(protest["site_application_id"])
    if ap is None or ap["status"] != "PROTESTED":
        return
    if resolution == "UPHELD":
        ap["status"] = "REJECTED"
        touch(ap)
        # Void PROVISIONAL/FINAL study
        for st in DB["impact_studies"].values():
            if st["site_application_id"] == ap["id"] and \
                    st["status"] in ("PROVISIONAL", "FINAL"):
                st["status"] = "VOID"
                touch(st)
        # Terminate the PIPELINE store created at approval
        if ap["store_id"]:
            store = DB["stores"].get(ap["store_id"])
            if store is not None and store["status"] == "PIPELINE":
                terminate_store(store)
    else:  # REJECTED
        live = [p for p in DB["protests"].values()
                if p["site_application_id"] == ap["id"]
                and p["id"] != protest["id"]
                and p["status"] not in ("RESOLVED_UPHELD", "RESOLVED_REJECTED")]
        if not live:
            ap["status"] = "APPROVED"
            touch(ap)


def recompute_vote_tallies(promotion):
    votes = [v for v in DB["votes"].values()
             if v["promotion_id"] == promotion["id"] and not v["retracted"]]
    promotion["votes_for"] = sum(1 for v in votes if v["ballot"] == "FOR")
    promotion["votes_against"] = sum(1 for v in votes if v["ballot"] == "AGAINST")
    promotion["votes_abstain"] = sum(1 for v in votes if v["ballot"] == "ABSTAIN")
