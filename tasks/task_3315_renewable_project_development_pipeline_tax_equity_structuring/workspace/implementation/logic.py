"""Business logic: calculations, cascades, shared lookups."""
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err
from helpers import iso_from_epoch, dec2

DAY = 86400.0
SAFE_HARBOR_WINDOW_DAYS = 183
FOUR_YEAR_WINDOW_DAYS = 1461
MAX_WORK_GAP_DAYS = 365
CURE_WINDOW_DAYS = 90
STUDY_BUFFER_DAYS = 5
PRICE_FLOOR = Decimal("20.00")
MIN_DSCR = Decimal("1.30")
MAX_ADVANCE_RATE = Decimal("0.80")
LD_PER_POINT = Decimal("25000")
LD_CAP = Decimal("500000.00")
BASE_RATE = Decimal("30.00")
DC_ADDER = Decimal("10.00")
EC_ADDER = Decimal("10.00")

TCQ_ANCHORED_STATES = {"SAFE_HARBOR_ESTABLISHED", "CONTINUITY_MAINTAINED", "CURED", "QUALIFIED"}
ORDER_CREDIT_STATES = {"SAFE_HARBOR_QUALIFIED", "DELIVERED", "ACCEPTED"}
SA_ACTIVE_STATES = {"EXECUTED", "AMENDMENT_PENDING", "DELIVERING", "FULFILLED"}


def _q2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _f2(d):
    return float(_q2(d))


# ---- lookups ----

def get_project(pid):
    p = db.projects.get(pid)
    if p is None:
        raise_err("ERR_NOT_FOUND", "Project not found")
    return p


def get_sci(sid):
    s = db.site_control_instruments.get(sid)
    if s is None:
        raise_err("ERR_NOT_FOUND", "Site control instrument not found")
    return s


def get_ir(rid):
    r = db.interconnection_requests.get(rid)
    if r is None:
        raise_err("ERR_NOT_FOUND", "Interconnection request not found")
    return r


def get_study(sid):
    s = db.interconnection_studies.get(sid)
    if s is None:
        raise_err("ERR_NOT_FOUND", "Interconnection study not found")
    return s


def get_offtake(oid):
    o = db.offtake_agreements.get(oid)
    if o is None:
        raise_err("ERR_NOT_FOUND", "Offtake agreement not found")
    return o


def get_sa(sid):
    s = db.supply_agreements.get(sid)
    if s is None:
        raise_err("ERR_NOT_FOUND", "Supply agreement not found")
    return s


def get_po(oid):
    o = db.procurement_orders.get(oid)
    if o is None:
        raise_err("ERR_NOT_FOUND", "Procurement order not found")
    return o


def get_milestone(mid):
    m = db.construction_milestones.get(mid)
    if m is None:
        raise_err("ERR_NOT_FOUND", "Construction milestone not found")
    return m


def get_tcq(tid):
    t = db.tax_credit_qualifications.get(tid)
    if t is None:
        raise_err("ERR_NOT_FOUND", "Tax credit qualification not found")
    return t


def get_partnership(pid):
    p = db.tax_equity_partnerships.get(pid)
    if p is None:
        raise_err("ERR_NOT_FOUND", "Tax equity partnership not found")
    return p


def get_ledger(eid):
    e = db.partnership_ledger_entries.get(eid)
    if e is None:
        raise_err("ERR_NOT_FOUND", "Partnership ledger entry not found")
    return e


def get_df(fid):
    f = db.debt_facilities.get(fid)
    if f is None:
        raise_err("ERR_NOT_FOUND", "Debt facility not found")
    return f


def tcq_for_project(project_id):
    for t in db.tax_credit_qualifications.values():
        if t["project_id"] == project_id:
            return t
    return None


def orders_for_project(project_id):
    out = []
    for o in db.procurement_orders.values():
        sa = db.supply_agreements.get(o["supply_agreement_id"])
        if sa and sa["project_id"] == project_id:
            out.append(o)
    return out


def project_eligible_basis(project_id):
    total = Decimal("0")
    for o in orders_for_project(project_id):
        if o["status"] in ORDER_CREDIT_STATES:
            total += dec2(o["order_amount_usd"])
    return total


# ---- upgrade allocation / queue reseat ----

def allocate_upgrade_costs(cluster_id, total_usd):
    """Pro-rata allocation over non-WITHDRAWN cluster requests, ordered by
    queue_position ASC; remainder to largest capacity (earliest created_at tie-break)."""
    pool = [r for r in db.interconnection_requests.values()
            if r["cluster_id"] == cluster_id and r["status"] != "WITHDRAWN"]
    pool.sort(key=lambda r: (r["queue_position"], r["created_at"]))
    if not pool:
        return
    total_cap = sum(dec2(r["requested_capacity_mw"]) for r in pool)
    total = dec2(total_usd)
    shares = []
    for r in pool:
        if total_cap == 0:
            share = Decimal("0")
        else:
            share = _q2(total * dec2(r["requested_capacity_mw"]) / total_cap)
        shares.append(share)
    remainder = total - sum(shares)
    if remainder != 0:
        # largest capacity, earliest created_at tie-break
        best = max(range(len(pool)), key=lambda i: (dec2(pool[i]["requested_capacity_mw"]), ))
        # max picks last on ties; do explicit tie-break by created_at
        best_cap = dec2(pool[best]["requested_capacity_mw"])
        candidates = [i for i in range(len(pool)) if dec2(pool[i]["requested_capacity_mw"]) == best_cap]
        candidates.sort(key=lambda i: pool[i]["created_at"])
        shares[candidates[0]] += remainder
    for r, share in zip(pool, shares):
        r["upgrade_cost_share_usd"] = float(share)
        r["upgrade_allocated"] = True
        r["last_upgrade_total_usd"] = float(total)


def withdraw_request(r, touch_fn):
    """Withdraw an interconnection request with reseat + reallocation cascade."""
    from helpers import touch  # late import to avoid cycle
    withdrawn_pos = r["queue_position"]
    r["status"] = "WITHDRAWN"
    r["queue_position"] = 0
    touch(r)
    cluster = r["cluster_id"]
    higher = [x for x in db.interconnection_requests.values()
              if x["cluster_id"] == cluster and x["status"] != "WITHDRAWN"
              and x["queue_position"] > withdrawn_pos]
    higher.sort(key=lambda x: x["queue_position"])
    for x in higher:
        x["queue_position"] -= 1
        touch(x)
    # Re-allocation using mirrored last_upgrade_total_usd (skip when 0)
    last_total = r["last_upgrade_total_usd"]
    if last_total and dec2(last_total) != 0:
        allocate_upgrade_costs(cluster, last_total)


# ---- clawback cascade ----

def clawback_order(order):
    """SAFE_HARBOR_QUALIFIED -> CANCELLED clawback cascade."""
    order["safe_harbor_qualified"] = False
    sa = db.supply_agreements.get(order["supply_agreement_id"])
    if not sa:
        return
    project = db.projects.get(sa["project_id"])
    if not project:
        return
    remaining = [o for o in orders_for_project(project["id"])
                 if o["id"] != order["id"] and o["status"] in ORDER_CREDIT_STATES]
    tcq = tcq_for_project(project["id"])
    if tcq is not None and not remaining and tcq["status"] == "SAFE_HARBOR_ESTABLISHED":
        tcq["status"] = "NOT_ELIGIBLE"
        from helpers import touch
        touch(tcq)
        project["tax_credit_anchored"] = False


# ---- COD cascade ----

def cod_cascade(project):
    """Project COMMISSIONING -> COMMERCIAL_OPERATION cascade."""
    from helpers import touch
    project["status"] = "COMMERCIAL_OPERATION"
    project["cod_date"] = iso_from_epoch(db.clock_now())
    touch(project)
    tcq = tcq_for_project(project["id"])
    if tcq is not None and tcq["status"] in ("CONTINUITY_MAINTAINED", "CURED"):
        tcq["status"] = "QUALIFIED"
        compute_itc(project, tcq)
        touch(tcq)
    recompute_project_derived(project)
    for f in db.debt_facilities.values():
        if f["project_id"] == project["id"] and f["status"] == "CONSTRUCTION_DRAWING":
            f["status"] = "CONVERSION_PENDING"
            touch(f)
    for p in db.tax_equity_partnerships.values():
        if p["project_id"] == project["id"] and p["status"] == "FULLY_FUNDED":
            p["status"] = "PRE_FLIP_OPERATING"
            touch(p)


# ---- abandon cascade ----

def abandon_project(project):
    from helpers import touch
    project["status"] = "ABANDONED"
    touch(project)
    for s in db.site_control_instruments.values():
        if s["project_id"] == project["id"] and s["status"] in ("DRAFT", "EXECUTED", "EXERCISED"):
            s["status"] = "TERMINATED"
            touch(s)
    # withdraw non-terminal interconnection requests (process in queue_position order)
    reqs = [r for r in db.interconnection_requests.values()
            if r["project_id"] == project["id"] and r["status"] not in ("IN_SERVICE", "WITHDRAWN")]
    reqs.sort(key=lambda r: r["queue_position"])
    for r in reqs:
        withdraw_request(r, touch)
    for o in db.offtake_agreements.values():
        if o["project_id"] == project["id"] and o["status"] not in ("EXPIRED", "TERMINATED"):
            o["status"] = "TERMINATED"
            touch(o)
            touch(project)
    for sa in db.supply_agreements.values():
        if sa["project_id"] == project["id"] and sa["status"] not in ("FULFILLED", "TERMINATED"):
            sa["status"] = "TERMINATED"
            touch(sa)
            for po in db.procurement_orders.values():
                if po["supply_agreement_id"] == sa["id"] and po["status"] not in ("DELIVERED", "ACCEPTED", "CANCELLED"):
                    was_qualified = po["status"] == "SAFE_HARBOR_QUALIFIED"
                    po["status"] = "CANCELLED"
                    if was_qualified:
                        clawback_order(po)
                    touch(po)
    # cancel any remaining project orders not ACCEPTED (orders under already-terminal SAs)
    for po in orders_for_project(project["id"]):
        if po["status"] not in ("ACCEPTED", "CANCELLED"):
            was_qualified = po["status"] == "SAFE_HARBOR_QUALIFIED"
            po["status"] = "CANCELLED"
            if was_qualified:
                clawback_order(po)
            touch(po)


# ---- continuity assessment ----

def assess_continuity(tcq, project):
    """Return True if the continuity assessment passes for the pinned variant."""
    if tcq["continuity_variant"] == "FOUR_YEAR_SAFE_HARBOR":
        established = tcq["_established_epoch"]
        if db.clock_now() <= established + FOUR_YEAR_WINDOW_DAYS * DAY:
            return True
        return project["status"] in ("COMMERCIAL_OPERATION", "OPERATIONAL")
    # FACTS_AND_CIRCUMSTANCES
    works = [m for m in db.construction_milestones.values()
             if m["project_id"] == project["id"]
             and m["milestone_type"] == "CONTINUOUS_WORK"
             and m["status"] == "CERTIFIED"]
    works.sort(key=lambda m: (m["_work_epoch"], m["created_at"]))
    series = [tcq["_established_epoch"]] + [m["_work_epoch"] for m in works] + [db.clock_now()]
    for a, b in zip(series, series[1:]):
        if (b - a) > MAX_WORK_GAP_DAYS * DAY:
            return False
    return True

def recompute_project_derived(project):
    tcq = tcq_for_project(project["id"])
    anchored = tcq is not None and tcq["status"] in TCQ_ANCHORED_STATES
    project["tax_credit_anchored"] = anchored
    if tcq is not None and tcq["status"] == "QUALIFIED":
        project["total_itc_credits_usd"] = tcq["qualified_credit_usd"]
    else:
        project["total_itc_credits_usd"] = 0.0


def compute_itc(project, tcq):
    rate = BASE_RATE
    if project["domestic_content_certified"]:
        has_dc_sa = any(
            sa["project_id"] == project["id"]
            and sa["domestic_content_certified"]
            and sa["status"] in SA_ACTIVE_STATES
            for sa in db.supply_agreements.values()
        )
        if has_dc_sa:
            rate += DC_ADDER
    if project["energy_community_eligible"]:
        rate += EC_ADDER
    basis = project_eligible_basis(project["id"])
    tcq["credit_rate_pct"] = float(rate)
    tcq["qualified_credit_usd"] = _f2(rate / Decimal("100") * basis)


def partnership_computed(p):
    contrib = Decimal("0")
    dist_inv = Decimal("0")
    dist_dev = Decimal("0")
    cred_inv = Decimal("0")
    for e in db.partnership_ledger_entries.values():
        if e["partnership_id"] != p["id"]:
            continue
        amt = dec2(e["amount_usd"])
        if e["entry_type"] == "CONTRIBUTION":
            contrib += amt
        elif e["entry_type"] == "DISTRIBUTION_INVESTOR":
            dist_inv += amt
        elif e["entry_type"] == "DISTRIBUTION_DEVELOPER":
            dist_dev += amt
        elif e["entry_type"] == "CREDIT_ALLOCATION_INVESTOR":
            cred_inv += amt
    retained = contrib - dist_inv - dist_dev
    if contrib == 0:
        irr = Decimal("0")
    else:
        irr = ((dist_inv + cred_inv) / contrib - 1) * Decimal("100")
        irr = _q2(irr)
    return {
        "contributed_usd": _f2(contrib),
        "retained_cash_usd": _f2(retained),
        "investor_irr_pct": float(irr),
    }
