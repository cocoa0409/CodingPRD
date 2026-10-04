"""Derived-field recomputation and the cascades that propagate through it.

Every recomputation is whole: the value is re-derived from current rows and the
previous value is discarded (PRD 2.10).  A recomputation that actually changes a
field counts as a modification, so the row is refreshed and its version bumped.
"""

import calc
import clock
import store


def _set(row, field, value):
    if row.get(field) != value:
        row[field] = value
        return True
    return False


def _commit(row, changed):
    if changed:
        store.touch(row)
    return row


# --- lookups -----------------------------------------------------------------
def projects_of_developer(developer_id):
    return [p for p in store.projects.values() if p["developer_id"] == developer_id]


def projects_of_fund(fund_id):
    return [p for p in store.projects.values() if p["fund_id"] == fund_id]


def allocations_of_project(project_id):
    return [a for a in store.allocations.values() if a["project_id"] == project_id]


def calls_of_project(project_id):
    return [c for c in store.calls.values() if c["project_id"] == project_id]


def guarantees_of_project(project_id):
    return [g for g in store.guarantees.values() if g["project_id"] == project_id]


def reviews_of_project(project_id):
    return [r for r in store.reviews.values() if r["project_id"] == project_id]


def exits_of_project(project_id):
    return [e for e in store.exits.values() if e["project_id"] == project_id]


def subscriptions_of_fund(fund_id):
    return [s for s in store.subscriptions.values() if s["fund_id"] == fund_id]


def subscriptions_of_investor(investor_id):
    return [s for s in store.subscriptions.values() if s["investor_id"] == investor_id]


def committed_allocations(project_id):
    return [a for a in allocations_of_project(project_id)
            if a["status"] in ("COMMITTED", "CLOSED")]


def fund_priced_allocations(fund_id):
    """COMMITTED/CLOSED allocations of the fund's non-EXITED projects."""
    rows = []
    for project in projects_of_fund(fund_id):
        if project["status"] == "EXITED":
            continue
        rows.extend(committed_allocations(project["id"]))
    return rows


def latest_review(project_id):
    rows = store.ordered(reviews_of_project(project_id))
    return rows[-1] if rows else None


def fund_shortfall_cents(fund_id):
    """Crisis shortfall carried by every subscription of a fund."""
    total = 0
    for call in store.calls.values():
        project = store.projects.get(call["project_id"])
        if project is None or project["fund_id"] != fund_id:
            continue
        if call["status"] in ("DEFICIENT", "ADJUSTED"):
            total += max(0, int(call["called_amount_cents"]) - int(call["settled_amount_cents"]))
    return total


# --- Developer ---------------------------------------------------------------
def developer_exposure_cents(developer_id):
    total = 0
    for project in projects_of_developer(developer_id):
        for guarantee in guarantees_of_project(project["id"]):
            if guarantee["status"] != "RELEASED":
                total += int(guarantee["guaranteed_amount_cents"])
    return total


def developer_escalated_count(developer_id):
    count = 0
    for project in projects_of_developer(developer_id):
        if project["status"] == "EXITED":
            continue
        count += sum(1 for r in reviews_of_project(project["id"]) if r["status"] == "ESCALATED")
    return count


def developer_distressed_count(developer_id):
    return sum(1 for p in projects_of_developer(developer_id) if p["status"] == "DISTRESSED")


def recompute_developer(developer_id):
    developer = store.developers.get(developer_id)
    if developer is None:
        return None
    exposure = developer_exposure_cents(developer_id)
    active = sum(1 for p in projects_of_developer(developer_id) if p["status"] != "EXITED")
    status = calc.sponsor_eligibility(
        int(developer["net_worth_cents"]), exposure,
        int(developer["sponsor_experience_months"]), int(developer["projects_completed"]),
        developer_escalated_count(developer_id), developer_distressed_count(developer_id))
    changed = False
    changed |= _set(developer, "guarantee_exposure_cents", exposure)
    changed |= _set(developer, "active_project_count", active)
    changed |= _set(developer, "status", status)
    return _commit(developer, changed)


# --- Investor ----------------------------------------------------------------
def recompute_investor(investor_id):
    investor = store.investors.get(investor_id)
    if investor is None:
        return None
    subs = subscriptions_of_investor(investor_id)
    outstanding = sum(int(s["committed_cents"]) for s in subs if s["status"] != "DEFAULTED")
    funded = sum(int(s["paid_in_cents"]) for s in subs)
    status = "SUSPENDED" if any(s["status"] == "DEFAULTED" for s in subs) else "ACTIVE"
    changed = False
    changed |= _set(investor, "outstanding_commitment_cents", outstanding)
    changed |= _set(investor, "funded_cents", funded)
    changed |= _set(investor, "status", status)
    return _commit(investor, changed)


# --- FundSubscription --------------------------------------------------------
def default_band_cents(subscription):
    return calc.rhu_int(calc.dec(subscription["committed_cents"]) * calc.DEFAULT_BAND_PCT)


def recompute_subscription(subscription_id):
    subscription = store.subscriptions.get(subscription_id)
    if subscription is None:
        return None
    paid_in = int(subscription.get("paid_in_cents") or 0)
    committed = int(subscription["committed_cents"])
    shortfall = fund_shortfall_cents(subscription["fund_id"])
    changed = False
    changed |= _set(subscription, "unfunded_commitment_cents", max(0, committed - paid_in))
    changed |= _set(subscription, "shortfall_cents", shortfall)
    if subscription["status"] != "DEFAULTED" and shortfall > default_band_cents(subscription):
        subscription["status"] = "DEFAULTED"
        changed = True
    _commit(subscription, changed)
    recompute_investor(subscription["investor_id"])
    return subscription


# --- Allocation --------------------------------------------------------------
def recompute_allocation(allocation_id):
    allocation = store.allocations.get(allocation_id)
    if allocation is None:
        return None
    awarded = int(allocation["awarded_credit_dollars_cents"])
    delivered = int(allocation["delivered_credit_dollars_cents"])
    ratio = calc.rhu6(calc.dec(delivered) / calc.dec(awarded)) if awarded > 0 else 0.0
    return _commit(allocation, _set(allocation, "delivery_ratio", ratio))


# --- Project -----------------------------------------------------------------
def project_delivered_credit_dollars(project_id):
    return sum(int(a["delivered_credit_dollars_cents"]) for a in allocations_of_project(project_id)
               if a["status"] != "RESCINDED")


def project_committed_credit_dollars(project_id):
    return sum(int(a["awarded_credit_dollars_cents"]) for a in allocations_of_project(project_id)
               if a["status"] in ("COMMITTED", "CLOSED"))


def recompute_project(project_id):
    project = store.projects.get(project_id)
    if project is None:
        return None
    fund = store.funds.get(project["fund_id"])
    price = fund["price_per_credit_dollar"] if fund else 0
    changed = False

    preliminary = calc.preliminary_equity_cents(project)
    changed |= _set(project, "preliminary_equity_cents", preliminary)
    if project.get("underwriting_stage") == "FINAL":
        final = calc.final_equity_cents(project, price)
        changed |= _set(project, "final_equity_cents", final)
    else:
        changed |= _set(project, "final_equity_cents", None)
    changed |= _set(project, "underwritten_equity_cents", calc.underwritten_equity_cents(project))

    noi = int(project["operating_pro_forma_noi_cents"])
    debt_service = int(project["debt_service_cents"])
    # dscr is stored with four decimal places (PRD 2.7).
    dscr = float(calc.rhu(calc.dec(noi) / calc.dec(debt_service), 4)) if debt_service > 0 else 0.0
    changed |= _set(project, "dscr", dscr)
    changed |= _set(project, "operating_deficit_cents", max(0, debt_service - noi))

    gap = (int(project["construction_budget_cents"]) - int(project["construction_loan_cents"])
           - calc.underwritten_equity_cents(project))
    changed |= _set(project, "underwritten_gap_cents", max(0, gap))

    changed |= _set(project, "committed_credit_dollars_cents", project_committed_credit_dollars(project_id))
    changed |= _set(project, "delivered_credit_dollars_cents", project_delivered_credit_dollars(project_id))
    changed |= _set(project, "compliance_failure_count",
                    sum(1 for r in reviews_of_project(project_id) if r["status"] == "NONCOMPLIANT"))
    return _commit(project, changed)


def derive_exit_eligible(project):
    """COMPLIANCE_PERIOD -> EXIT_ELIGIBLE once the compliance clock has run."""
    if project["status"] != "COMPLIANCE_PERIOD":
        return False
    if not project.get("placed_in_service_at"):
        return False
    if int(project.get("compliance_failure_count") or 0) != 0:
        return False
    end = clock.add_months(clock._parse(project["placed_in_service_at"]),
                           int(project.get("compliance_period_months") or 180))
    if clock.now() >= end:
        project["status"] = "EXIT_ELIGIBLE"
        store.touch(project)
        return True
    return False


def distress_project(project_id):
    """Push a project into DISTRESSED, remembering where it came from."""
    project = store.projects.get(project_id)
    if project is None or project["status"] == "DISTRESSED":
        return project
    project["_pre_distress_status"] = project["status"]
    project["status"] = "DISTRESSED"
    store.touch(project)
    return project


def heal_project(project_id):
    """DISTRESSED -> COMPLIANCE_PERIOD once no review of it remains ESCALATED."""
    project = store.projects.get(project_id)
    if project is None or project["status"] != "DISTRESSED":
        return project
    if any(r["status"] == "ESCALATED" for r in reviews_of_project(project_id)):
        return project
    if project.get("_pre_distress_status") is None:
        return project
    project["status"] = "COMPLIANCE_PERIOD"
    project.pop("_pre_distress_status", None)
    store.touch(project)
    return project


# --- Fund --------------------------------------------------------------------
def recompute_fund(fund_id):
    fund = store.funds.get(fund_id)
    if fund is None:
        return None
    changed = False
    subs = subscriptions_of_fund(fund_id)
    subscribed = sum(int(s["committed_cents"]) for s in subs if s["status"] != "DEFAULTED")
    funded = sum(int(s["paid_in_cents"]) for s in subs)
    changed |= _set(fund, "subscribed_equity_cents", subscribed)
    changed |= _set(fund, "funded_equity_cents", funded)
    changed |= _set(fund, "subscription_count", len(subs))

    allocations_rows = fund_priced_allocations(fund_id)
    awarded_total, delivered_total, priced_value, realized_value = calc.fund_priced_fields(
        fund, allocations_rows)
    changed |= _set(fund, "awarded_credits_total_cents", awarded_total)
    changed |= _set(fund, "delivered_credits_total_cents", delivered_total)
    changed |= _set(fund, "priced_value_cents", priced_value)
    changed |= _set(fund, "realized_value_cents", realized_value)
    changed |= _set(fund, "priced_yield_pct", calc.priced_yield_pct(awarded_total, subscribed))
    changed |= _set(fund, "realized_yield_pct", calc.realized_yield_pct(delivered_total, funded))

    changed |= _sync_fund_status(fund, subs)
    changed |= _set(fund, "posture", calc.fund_posture(projects_of_fund(fund_id)))
    return _commit(fund, changed)


def _sync_fund_status(fund, subs):
    """The fund status machine, including the clock-driven close/terminate."""
    status = fund["status"]
    threshold = calc.rhu_int(calc.dec(fund["target_equity_cents"]) * calc.dec(fund["close_threshold_pct"]))
    close_at = clock._parse(fund["subscription_close_date"])
    changed = False

    if status in ("FORMING", "CLOSING"):
        if clock.now() >= close_at:
            if int(fund["subscribed_equity_cents"]) >= threshold:
                fund["status"] = "CLOSED"
                for sub in subs:
                    if sub["status"] == "PLEDGED":
                        sub["status"] = "SUBSCRIBED"
                        store.touch(sub)
            else:
                fund["status"] = "TERMINATED"
                for sub in subs:
                    if sub["status"] != "DEFAULTED":
                        sub["status"] = "DEFAULTED"
                        store.touch(sub)
                    recompute_investor(sub["investor_id"])
            return True
        new_status = "CLOSING" if int(fund["subscribed_equity_cents"]) >= threshold else "FORMING"
        if new_status != status:
            fund["status"] = new_status
            changed = True
        return changed

    if status == "CLOSED":
        if any(a["status"] == "COMMITTED"
               for project in projects_of_fund(fund["id"])
               for a in allocations_of_project(project["id"])):
            fund["status"] = "DEPLOYING"
            return True
        return False

    if status == "DEPLOYING":
        projects = projects_of_fund(fund["id"])
        if projects and all(p["status"] == "EXITED" for p in projects):
            fund["status"] = "WOUND_DOWN"
            return True
    return False


def fund_allows_subscription(fund):
    """FORMING or CLOSING only; TERMINATED/WOUND_DOWN/CLOSED are refused."""
    return fund["status"] in ("FORMING", "CLOSING")


def fund_allows_payin(fund):
    return fund["status"] in ("CLOSING", "CLOSED")


# --- composite cascades ------------------------------------------------------
def propagate(project_id):
    """Recompute everything a project-level change can reach."""
    project = store.projects.get(project_id)
    if project is None:
        return
    recompute_project(project_id)
    for allocation in allocations_of_project(project_id):
        recompute_allocation(allocation["id"])
    for subscription in subscriptions_of_fund(project["fund_id"]):
        recompute_subscription(subscription["id"])
    recompute_fund(project["fund_id"])
    recompute_developer(project["developer_id"])


def on_clock_advanced():
    """Deferred, clock-driven derivations evaluated when the clock moves."""
    for fund_id in list(store.funds.keys()):
        recompute_fund(fund_id)
    for project in list(store.projects.values()):
        if project["status"] == "COMPLIANCE_PERIOD":
            recompute_project(project["id"])
            derive_exit_eligible(project)
        recompute_developer(project["developer_id"])
    for event in list(store.exits.values()):
        # A notice whose window lapsed before it was ever opened lapses by
        # itself.  A window that WAS opened is left standing so that an
        # exercise attempt against it reports ERR_ROFR_WINDOW_EXPIRED rather
        # than being masked by a state change.
        if event["status"] == "OPTION_NOTICE_ISSUED":
            if clock.now() > clock._parse(event["rofr_expires_at"]):
                event["status"] = "DECLINED"
                store.touch(event)
                project = store.projects.get(event["project_id"])
                if project is not None and project["status"] == "EXIT_ELIGIBLE":
                    project["status"] = "COMPLIANCE_PERIOD"
                    store.touch(project)
