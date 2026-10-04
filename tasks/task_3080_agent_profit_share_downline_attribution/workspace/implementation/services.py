"""Business logic: cap split, rollover, replay, distribution waterfall,
sponsorship closure, dispute overturn cascade, vesting, departures.

All constants come from SCAFFOLD.yaml / PRD.md:
  COMPANY_DOLLAR_RATE = 0.30, ANNUAL_CAP = 20000.00,
  PROFIT_SHARE_POOL_RATE = 0.52, VESTING_DAYS = 1095, VESTING_MONTHS = 36,
  MAX_DEPTH = 7, DISPUTE_WINDOW_DAYS = 90,
  LEVEL_RATES = {1:.50, 2:.10, 3:.05, 4:.05, 5:.075, 6:.10, 7:.125}
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import db
from helpers import (
    ApiError, d2, invalid_state, new_entity, new_id, not_found, now_ts, touch,
)

COMPANY_DOLLAR_RATE = Decimal("0.30")
ANNUAL_CAP = Decimal("20000.00")
POOL_RATE = Decimal("0.52")
VESTING_DAYS = 1095
VESTING_MONTHS = 36
MAX_DEPTH = 7
DISPUTE_WINDOW_DAYS = 90
LEVEL_RATES = {
    1: Decimal("0.50"), 2: Decimal("0.10"), 3: Decimal("0.05"),
    4: Decimal("0.05"), 5: Decimal("0.075"), 6: Decimal("0.10"),
    7: Decimal("0.125"),
}


# ---------------------------------------------------------------- agents
def get_agent(agent_id):
    a = db.stores["agents"].get(agent_id)
    if a is None:
        raise not_found("ERR_AGENT_NOT_FOUND", "Agent not found: %s" % agent_id)
    return a


def get_center(center_id):
    c = db.stores["market_centers"].get(center_id)
    if c is None:
        raise not_found("ERR_MARKET_CENTER_NOT_FOUND",
                        "Market center not found: %s" % center_id)
    return c


def get_period(period_id):
    p = db.stores["periods"].get(period_id)
    if p is None:
        raise not_found("ERR_PERIOD_NOT_FOUND", "Period not found: %s" % period_id)
    return p


def get_dispute(dispute_id):
    d = db.stores["disputes"].get(dispute_id)
    if d is None:
        raise not_found("ERR_DISPUTE_NOT_FOUND", "Dispute not found: %s" % dispute_id)
    return d


def get_event(event_id):
    e = db.stores["commission_events"].get(event_id)
    if e is None:
        raise not_found("ERR_COMMISSION_EVENT_NOT_FOUND",
                        "Commission event not found: %s" % event_id)
    return e


def get_transfer(transfer_id):
    t = db.stores["transfer_requests"].get(transfer_id)
    if t is None:
        raise not_found("ERR_TRANSFER_NOT_FOUND",
                        "Transfer request not found: %s" % transfer_id)
    return t


def get_resolution(resolution_id):
    r = db.stores["resolutions"].get(resolution_id)
    if r is None:
        raise not_found("ERR_RESOLUTION_NOT_FOUND",
                        "Governance resolution not found: %s" % resolution_id)
    return r


def get_distribution(distribution_id):
    d = db.stores["distributions"].get(distribution_id)
    if d is None:
        raise not_found("ERR_DISTRIBUTION_NOT_FOUND",
                        "Distribution not found: %s" % distribution_id)
    return d


def get_document(document_id):
    d = db.stores["onboarding_documents"].get(document_id)
    if d is None:
        raise not_found("ERR_DOCUMENT_NOT_FOUND",
                        "Onboarding document not found: %s" % document_id)
    return d


def vesting_of(agent_id):
    for vs in db.stores["vesting_schedules"].values():
        if vs["agent_id"] == agent_id:
            return vs
    return None


def is_forfeited(agent_id):
    vs = vesting_of(agent_id)
    return vs is not None and vs["status"] == "FORFEITED"


# ---------------------------------------------------------- cap year / split
def add_years(dt, n):
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap years
        return dt.replace(year=dt.year + n, day=28)


def cap_split(gross, accrued):
    """Provisional split. Returns (company_dollar Decimal, agent_retained Decimal,
    cap_applied bool)."""
    raw = (Decimal(str(gross)) * COMPANY_DOLLAR_RATE).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    remaining = max(Decimal("0.00"), ANNUAL_CAP - Decimal(str(accrued)))
    company = min(raw, remaining)
    retained = (Decimal(str(gross)) - company).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    return company, retained, raw > remaining


def rollover_if_needed(agent, occurred_dt):
    """Advance the cap year while occurred_on >= cap_year_end; resets accrual."""
    while occurred_dt >= agent["_cap_year_end_dt"]:
        agent["_cap_year_start_dt"] = add_years(agent["_cap_year_start_dt"], 1)
        agent["_cap_year_end_dt"] = add_years(agent["_cap_year_end_dt"], 1)
        agent["cap_year_start"] = _iso(agent["_cap_year_start_dt"])
        agent["cap_year_end"] = _iso(agent["_cap_year_end_dt"])
        agent["accrued_company_dollar"] = 0.00
        agent["cap_status"] = "UNCAPPED"


def _iso(dt):
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def post_commission_split(agent, gross, occurred_dt):
    """Apply the provisional cap split to the agent; returns event fields."""
    rollover_if_needed(agent, occurred_dt)
    company, retained, cap_applied = cap_split(gross, agent["accrued_company_dollar"])
    agent["accrued_company_dollar"] = float(
        (Decimal(str(agent["accrued_company_dollar"])) + company).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    if Decimal(str(agent["accrued_company_dollar"])) >= ANNUAL_CAP:
        agent["cap_status"] = "CAPPED"
    return float(company), float(retained), cap_applied


# ---------------------------------------------------------- period math
def _month_bounds(period_month):
    y, m = int(period_month[:4]), int(period_month[5:7])
    start = date(y, m, 1)
    if m == 12:
        end = date(y + 1, 1, 1)
    else:
        end = date(y, m + 1, 1)
    return start, end


def events_of_period(period):
    start, end = _month_bounds(period["period_month"])
    out = []
    for ev in db.stores["commission_events"].values():
        if ev["market_center_id"] != period["market_center_id"]:
            continue
        d = ev["_occurred_dt"].date()
        if start <= d < end:
            out.append(ev)
    return out


def ledger_sums(period_id):
    expenses = Decimal("0.00")
    adjustments = Decimal("0.00")
    for le in db.stores["ledger_entries"].values():
        if le["period_id"] != period_id:
            continue
        if le["entry_type"] == "EXPENSE":
            expenses += Decimal(str(le["amount"]))
        else:
            adjustments += Decimal(str(le["amount"]))
    return expenses, adjustments


def compute_provisional_profit(period):
    """Forward-looking: company dollar of POSTED+SETTLED events in the month."""
    total = Decimal("0.00")
    for ev in events_of_period(period):
        if ev["status"] in ("POSTED", "SETTLED"):
            total += Decimal(str(ev["company_dollar"]))
    expenses, adjustments = ledger_sums(period["id"])
    return (total - expenses + adjustments).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def recompute_provisional_profit(period):
    period["provisional_profit"] = float(compute_provisional_profit(period))


def recompute_period_totals(period):
    """distributed_total = sum of this period's PROJECTION|PAYABLE amounts;
    center_retained_amount = current pool - distributed_total."""
    distributed = Decimal("0.00")
    for dist in db.stores["distributions"].values():
        if dist["period_id"] == period["id"] and dist["status"] in ("PROJECTION", "PAYABLE"):
            distributed += Decimal(str(dist["amount"]))
    if period["status"] == "FINAL_CLOSED" or period["profit_share_pool"] is not None:
        pool = period["profit_share_pool"]
    else:
        pool = period["provisional_pool"]
    pool_dec = Decimal(str(pool)) if pool is not None else Decimal("0.00")
    period["distributed_total"] = float(distributed.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))
    period["center_retained_amount"] = float((pool_dec - distributed).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------- replay (FINAL)
def final_replay(agent):
    """Replay the agent's SETTLED events across the cap year, occurred_on ASC,
    tie-break created_at ASC. Sets final_company_dollar on each event of the
    agent (SETTLED events get replayed values; others get 0.00)."""
    events = [ev for ev in db.stores["commission_events"].values()
              if ev["agent_id"] == agent["id"]]
    settled = [ev for ev in events if ev["status"] == "SETTLED"]
    settled.sort(key=lambda ev: (ev["_occurred_dt"], ev["created_at"]))
    cap_start = agent["_join_dt"]          # replay accrual resets at anniversaries
    cap_end = add_years(cap_start, 1)
    accrued = Decimal("0.00")
    for ev in settled:
        occ = ev["_occurred_dt"]
        while occ >= cap_end:
            cap_start = cap_end
            cap_end = add_years(cap_end, 1)
            accrued = Decimal("0.00")
        raw = (Decimal(str(ev["gross_commission"])) * COMPANY_DOLLAR_RATE).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        remaining = max(Decimal("0.00"), ANNUAL_CAP - accrued)
        final_cd = min(raw, remaining)
        accrued = (accrued + final_cd).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ev["final_company_dollar"] = float(final_cd)
    for ev in events:
        if ev["status"] != "SETTLED":
            ev["final_company_dollar"] = 0.00


def attributable_for_period(agent, period, basis):
    """Sum of the agent's own company dollar for the period under the basis."""
    start, end = _month_bounds(period["period_month"])
    total = Decimal("0.00")
    for ev in db.stores["commission_events"].values():
        if ev["agent_id"] != agent["id"]:
            continue
        d = ev["_occurred_dt"].date()
        if not (start <= d < end):
            continue
        if basis == "PROVISIONAL":
            if ev["status"] in ("POSTED", "SETTLED"):
                total += Decimal(str(ev["company_dollar"]))
        else:  # FINAL
            if ev["status"] == "SETTLED" and ev["final_company_dollar"] is not None:
                total += Decimal(str(ev["final_company_dollar"]))
    return total


def _recipient_eligible(agent):
    """A recipient must be ACTIVE, or a DEPARTED agent whose vesting schedule
    is VESTED (a vested leaver keeps earning)."""
    if agent["membership_status"] == "ACTIVE":
        return True
    if agent["membership_status"] == "DEPARTED":
        vs = vesting_of(agent["id"])
        return vs is not None and vs["status"] == "VESTED"
    return False


# ---------------------------------------------------------- waterfall
def run_waterfall(period, pool, basis):
    """Build entitlement lines for the period under `basis`, scale against
    `pool` when over-subscribed, remainder-adjust, and create one distribution
    per surviving recipient. Returns list of created distributions."""
    pool_dec = Decimal(str(pool))
    # ---- entitlement lines (rounded per line first, per PRD §3.8)
    lines = []  # each: dict(recipient_id, source_id, depth_level, entitlement Decimal)
    for recipient in db.stores["agents"].values():
        if not _recipient_eligible(recipient):
            continue
        for edge in db.stores["sponsorship_edges"].values():
            if edge["parent_agent_id"] != recipient["id"] or edge["status"] != "ACTIVE":
                continue
            child = db.stores["agents"].get(edge["child_agent_id"])
            if child is None or is_forfeited(child["id"]):
                continue
            attributable = attributable_for_period(child, period, basis)
            entitlement = (LEVEL_RATES[edge["depth_level"]] * attributable).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            if entitlement <= Decimal("0.00"):
                continue  # zero-entitlement lines are omitted
            lines.append({
                "recipient_id": recipient["id"],
                "source_agent_id": child["id"],
                "depth_level": edge["depth_level"],
                "entitlement": entitlement,
            })
    if not lines:
        return []
    gross_total = sum(l["entitlement"] for l in lines)
    # ---- scaling (factor at full precision until per-line rounding)
    if gross_total > pool_dec:
        factor = pool_dec / gross_total
        for line in lines:
            scaled_exact = line["entitlement"] * factor
            line["scaled_exact"] = scaled_exact
            line["scaled"] = scaled_exact.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            line["frac"] = scaled_exact - line["scaled"]
        scaled_sum = sum(l["scaled"] for l in lines)
        delta = (pool_dec - scaled_sum).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if delta != Decimal("0.00"):
            def tie_key(line):
                rec = db.stores["agents"][line["recipient_id"]]
                src = db.stores["agents"][line["source_agent_id"]]
                return (-line["frac"], line["depth_level"],
                        rec["created_at"], rec["id"],
                        src["created_at"], src["id"])
            target = min(lines, key=tie_key)
            target["scaled"] = target["scaled"] + delta
    else:
        for line in lines:
            line["scaled"] = line["entitlement"]
            line["scaled_exact"] = line["entitlement"]
            line["frac"] = Decimal("0.00")
    # ---- one distribution per recipient with positive lines
    by_recipient = {}
    for line in lines:
        by_recipient.setdefault(line["recipient_id"], []).append(line)
    created = []
    for recipient_id, rlines in by_recipient.items():
        amount = sum(l["scaled"] for l in rlines).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount <= Decimal("0.00"):
            continue  # recipients with no positive amount get no row
        breakdown = [{
            "source_agent_id": l["source_agent_id"],
            "depth_level": l["depth_level"],
            "entitlement": float(l["entitlement"]),
            "scaled_amount": float(l["scaled"]),
        } for l in rlines]
        dist = new_entity({
            "period_id": period["id"],
            "agent_id": recipient_id,
            "basis": basis,
            "amount": float(amount),
            "level_breakdown": breakdown,
            "status": "PROJECTION",
        })
        db.stores["distributions"][dist["id"]] = dist
        created.append(dist)
    return created


# ---------------------------------------------------------- agent derived totals
def recompute_agent_totals(agent_id):
    agent = db.stores["agents"][agent_id]
    pending = Decimal("0.00")
    lifetime = Decimal("0.00")
    for dist in db.stores["distributions"].values():
        if dist["agent_id"] != agent_id:
            continue
        if dist["status"] == "PAYABLE":
            pending += Decimal(str(dist["amount"]))
        elif dist["status"] == "PAID":
            lifetime += Decimal(str(dist["amount"]))
    agent["pending_payable_profit_share"] = float(pending.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))
    agent["lifetime_profit_share"] = float(lifetime.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))
    vs = vesting_of(agent_id)
    agent["vested"] = vs is not None and vs["status"] == "VESTED"


# ---------------------------------------------------------- sponsorship closure
def build_closure(child_agent):
    """Walk the sponsor chain upward from the child's sponsor; create ACTIVE
    edges depth 1..7. Cycle guard: if the chain contains the child, reject."""
    new_edges = []
    current_id = child_agent["sponsor_agent_id"]
    depth = 1
    seen = set()
    while current_id is not None and depth <= MAX_DEPTH:
        if current_id == child_agent["id"] or current_id in seen:
            raise ApiError("ERR_SPONSOR_CYCLE", 422,
                           "Sponsorship chain would create a cycle")
        seen.add(current_id)
        parent = db.stores["agents"].get(current_id)
        if parent is None:
            break
        edge = new_entity({
            "parent_agent_id": parent["id"],
            "child_agent_id": child_agent["id"],
            "depth_level": depth,
            "status": "ACTIVE",
        })
        db.stores["sponsorship_edges"][edge["id"]] = edge
        new_edges.append(edge)
        current_id = parent["sponsor_agent_id"]
        depth += 1
    return new_edges


def subtree_agents(root_id):
    """The root plus all descendants via ACTIVE depth-1 edges."""
    members = {root_id}
    frontier = [root_id]
    while frontier:
        next_frontier = []
        for edge in db.stores["sponsorship_edges"].values():
            if (edge["status"] == "ACTIVE" and edge["depth_level"] == 1
                    and edge["parent_agent_id"] in frontier
                    and edge["child_agent_id"] not in members):
                members.add(edge["child_agent_id"])
                next_frontier.append(edge["child_agent_id"])
        frontier = next_frontier
    return members


def overturn_sponsor_tree(dispute):
    """Re-point the sponsored agent to the filer; supersede the old subtree
    closure and rebuild it along the new sponsor chain. Clawback + regenerate
    PROJECTION distributions that reference superseded edges."""
    sponsored = get_agent(dispute["sponsored_agent_id"])
    filer = get_agent(dispute["filer_agent_id"])
    # Cycle guard BEFORE any mutation: walk the filer's chain; it must not
    # contain the sponsored agent (would loop) and the filer must not be the
    # sponsored agent.
    if filer["id"] == sponsored["id"]:
        raise ApiError("ERR_SPONSOR_CYCLE", 422,
                       "Sponsorship would create a self-cycle")
    seen = set()
    cur = filer["id"]
    chain = []
    while cur is not None:
        if cur == sponsored["id"] or cur in seen:
            raise ApiError("ERR_SPONSOR_CYCLE", 422,
                           "New sponsor chain loops through the sponsored agent")
        seen.add(cur)
        chain.append(cur)
        nxt = db.stores["agents"].get(cur)
        cur = nxt["sponsor_agent_id"] if nxt is not None else None

    members = subtree_agents(sponsored["id"])

    # Supersede every ACTIVE edge whose child is in the re-pointed subtree.
    superseded_ids = set()
    for edge in db.stores["sponsorship_edges"].values():
        if edge["status"] == "ACTIVE" and edge["child_agent_id"] in members:
            edge["status"] = "SUPERSEDED"
            touch(edge)
            superseded_ids.add(edge["id"])

    # Re-point and rebuild the closure bottom-up: parent (root) first so each
    # child's chain sees updated ancestors. Order by current depth from the
    # root so descendants rebuild only after their (updated) parent.
    sponsored["sponsor_agent_id"] = filer["id"]
    touch(sponsored)
    build_closure(sponsored)
    ordered = []
    frontier = [sponsored["id"]]
    rest = members - {sponsored["id"]}
    while frontier:
        nxt = []
        for edge in db.stores["sponsorship_edges"].values():
            if (edge["status"] == "SUPERSEDED" and edge["depth_level"] == 1
                    and edge["parent_agent_id"] in frontier
                    and edge["child_agent_id"] in rest):
                cid = edge["child_agent_id"]
                ordered.append(cid)
                nxt.append(cid)
                rest.discard(cid)
        frontier = nxt
    ordered.extend(sorted(rest, key=lambda m: db.stores["agents"][m]["id"]))
    for member_id in ordered:
        build_closure(db.stores["agents"][member_id])

    # Clawback: PROVISIONAL PROJECTION distributions whose level_breakdown
    # references the re-pointed subtree -> CLAWED_BACK; the regenerated
    # PROJECTION set for that period is exactly the waterfall over the new
    # closure (distributions not referencing the subtree are replaced by their
    # recomputed equivalents, so totals conserve against the pool).
    affected_periods = {}
    for dist in list(db.stores["distributions"].values()):
        if dist["basis"] != "PROVISIONAL" or dist["status"] != "PROJECTION":
            continue
        period = db.stores["periods"].get(dist["period_id"])
        if period is None:
            continue
        hit = any(l.get("source_agent_id") in members
                  for l in dist["level_breakdown"])
        if hit:
            dist["status"] = "CLAWED_BACK"
            touch(dist)
            affected_periods[period["id"]] = period

    for period in affected_periods.values():
        for dist in list(db.stores["distributions"].values()):
            if (dist["period_id"] == period["id"]
                    and dist["basis"] == "PROVISIONAL"
                    and dist["status"] == "PROJECTION"):
                del db.stores["distributions"][dist["id"]]
        if period["provisional_pool"] is not None:
            run_waterfall(period, period["provisional_pool"], "PROVISIONAL")
        recompute_period_totals(period)
        touch(period)


# ---------------------------------------------------------- vesting
def evaluate_vesting(agent, departure_dt):
    vs = vesting_of(agent["id"])
    if vs is None:
        return
    join = agent["_join_dt"]
    # Provisional variant: whole calendar months between join and departure.
    months = ((departure_dt.year * 12 + departure_dt.month)
              - (join.year * 12 + join.month))
    if departure_dt.day < join.day:
        months -= 1
    vs["service_months_provisional"] = months
    if months <= 0:
        ratio_p = Decimal("0")
    else:
        ratio_p = Decimal(months) / Decimal(VESTING_MONTHS)
        if ratio_p > Decimal("1"):
            ratio_p = Decimal("1")
    vs["vested_ratio_provisional"] = float(ratio_p.quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP))
    # Final variant: exact days.
    days = (departure_dt - join).days
    if days < 0:
        days = 0
    vs["service_days_final"] = days
    ratio_f = Decimal(days) / Decimal(VESTING_DAYS)
    if ratio_f > Decimal("1"):
        ratio_f = Decimal("1")
    if ratio_f < Decimal("0"):
        ratio_f = Decimal("0")
    vs["vested_ratio_final"] = float(ratio_f.quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP))
    # Adjudication uses the final variant only; 1095 days vests (inclusive).
    if days >= VESTING_DAYS:
        vs["status"] = "VESTED"
    else:
        vs["status"] = "FORFEITED"
    touch(vs)
    agent["vested"] = (vs["status"] == "VESTED")


def depart_agent_cascade(agent, departure_dt):
    """ACTIVE -> DEPARTED; evaluate vesting; FORFEITED forfeits outstanding
    PROJECTION/PAYABLE distributions with period-total recomputation."""
    agent["membership_status"] = "DEPARTED"
    agent["departure_date"] = _iso(departure_dt)
    evaluate_vesting(agent, departure_dt)
    vs = vesting_of(agent["id"])
    if vs is not None and vs["status"] == "FORFEITED":
        periods = set()
        for dist in db.stores["distributions"].values():
            if dist["agent_id"] == agent["id"] and dist["status"] in (
                    "PROJECTION", "PAYABLE"):
                dist["status"] = "FORFEITED"
                touch(dist)
                periods.add(dist["period_id"])
        for pid in periods:
            period = db.stores["periods"].get(pid)
            if period is not None:
                recompute_period_totals(period)
                touch(period)
        recompute_agent_totals(agent["id"])
    touch(agent)


# ---------------------------------------------------------- final close cascade
def ratification_cascade(period):
    """Compute final_profit via SETTLED-only chronological replay, the pool,
    FINAL distributions (PROJECTION -> PAYABLE), recipient totals, and period
    totals. Raises ERR_PROFIT_NOT_POSITIVE when final_profit <= 0."""
    # Replay every agent of this center (replay is per-agent across the cap year).
    agents = [a for a in db.stores["agents"].values()
              if a["market_center_id"] == period["market_center_id"]]
    for agent in agents:
        final_replay(agent)
    # final_profit: replayed company dollar over the month's SETTLED events.
    total = Decimal("0.00")
    for ev in events_of_period(period):
        if ev["status"] == "SETTLED":
            total += Decimal(str(ev["final_company_dollar"]))
    expenses, adjustments = ledger_sums(period["id"])
    final_profit = (total - expenses + adjustments).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    if final_profit <= Decimal("0.00"):
        raise ApiError("ERR_PROFIT_NOT_POSITIVE", 422,
                       "final_profit must be > 0 at ratification")
    period["final_profit"] = float(final_profit)
    pool = (POOL_RATE * final_profit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    period["profit_share_pool"] = float(pool)

    # Existing PROJECTION distributions of this period retire; replacement FINAL
    # rows are created under the new basis and land directly as PAYABLE.
    old_recipients = []
    for dist in list(db.stores["distributions"].values()):
        if dist["period_id"] == period["id"] and dist["status"] == "PROJECTION":
            old_recipients.append(dist["agent_id"])
            del db.stores["distributions"][dist["id"]]

    created = run_waterfall(period, float(pool), "FINAL")
    for dist in created:
        dist["status"] = "PAYABLE"
        touch(dist)

    touched = set(old_recipients)
    for dist in created:
        touched.add(dist["agent_id"])
    for agent_id in touched:
        recompute_agent_totals(agent_id)
        touch(db.stores["agents"][agent_id])
        # Departed recipients' vesting schedules re-evaluated for continuation.
        agent = db.stores["agents"][agent_id]
        if agent["membership_status"] == "DEPARTED" and agent.get("departure_date"):
            vs = vesting_of(agent_id)
            if vs is not None:
                touch(vs)

    recompute_period_totals(period)
    touch(period)
