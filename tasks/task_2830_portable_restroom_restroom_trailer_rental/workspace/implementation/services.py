"""Derived-field recomputation, state cascades and shared lookups."""
import calculations as calc
import clock
import constants as C
from db import db, insert, ordered, serialize, touch


# ------------------------------------------------------------------- lookups

def contracts_of_account(account_id):
    return ordered([c for c in db.rental_contracts.values()
                    if c["account_id"] == account_id])


def contracts_of_site(site_id):
    return ordered([c for c in db.rental_contracts.values()
                    if c["site_id"] == site_id])


def schedules_of_contract(contract_id):
    return ordered([s for s in db.service_schedules.values()
                    if s["contract_id"] == contract_id])


def schedules_of_route(route_id):
    return ordered([s for s in db.service_schedules.values()
                    if s["route_id"] == route_id])


def visits_of_schedule(schedule_id):
    return ordered([v for v in db.service_visits.values()
                    if v["schedule_id"] == schedule_id])


def deployments_of_contract(contract_id):
    return ordered([d for d in db.unit_deployments.values()
                    if d["contract_id"] == contract_id])


def deployments_of_unit(asset_unit_id):
    return ordered([d for d in db.unit_deployments.values()
                    if d["asset_unit_id"] == asset_unit_id])


def charges_of_contract(contract_id):
    return ordered([c for c in db.charge_events.values()
                    if c["contract_id"] == contract_id])


def quote_lines_of_contract(contract_id):
    return ordered([q for q in db.quote_lines.values()
                    if q["contract_id"] == contract_id])


def active_quote_lines(contract_id):
    return [q for q in quote_lines_of_contract(contract_id) if not q["is_superseded"]]


def manifests_of_route_date(route_id, manifest_date):
    return ordered([m for m in db.waste_manifests.values()
                    if m["route_id"] == route_id
                    and m["manifest_date"] == manifest_date])


def serviced_visits(route_id, scheduled_date):
    return ordered([v for v in db.service_visits.values()
                    if v["route_id"] == route_id
                    and v["scheduled_date"] == scheduled_date
                    and v["state"] == "SERVICED"])


# --------------------------------------------------- site permit posture (2.5)

def _site_permit_status(site):
    required_kinds = ["PLACEMENT"]
    if site["right_of_way_required"]:
        required_kinds.append("RIGHT_OF_WAY")
    kind_statuses = []
    for kind in required_kinds:
        candidates = ordered([p for p in db.placement_permits.values()
                              if p["site_id"] == site["id"]
                              and p["permit_kind"] == kind])
        if not candidates:
            kind_statuses.append("NONE")
        else:
            latest = candidates[-1]          # created_at DESC, first row
            kind_statuses.append(C.PERMIT_STATUS_MAP[latest["status"]])
    for candidate in C.PERMIT_STATUS_PRECEDENCE:
        if candidate in kind_statuses:
            return candidate
    return "NONE"


def _open_tip_over(site):
    site_contract_ids = set(c["id"] for c in contracts_of_site(site["id"]))
    for charge in db.charge_events.values():
        if (charge["charge_kind"] == "TIP_OVER"
                and charge["state"] in ("ASSESSED", "DISPUTED")
                and charge["contract_id"] in site_contract_ids):
            return True
    return False


def recompute_site_posture(site, allow_cascade=True):
    """Returns {'became_blocked': bool, 'suspended': int}."""
    permit_status = _site_permit_status(site)
    if permit_status in ("REJECTED", "EXPIRED"):
        posture = "BLOCKED"
    elif permit_status in ("NONE", "PENDING"):
        posture = "RESTRICTED"
    elif _open_tip_over(site):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"

    previous_posture = site["site_posture"]
    if permit_status != site["permit_status"] or posture != previous_posture:
        site["permit_status"] = permit_status
        site["site_posture"] = posture
        touch(site)

    result = {
        "became_blocked": posture == "BLOCKED" and previous_posture != "BLOCKED",
        "suspended": 0,
    }
    if allow_cascade and posture == "BLOCKED":
        result["suspended"] = blocked_site_cascade(site)
    return result


def blocked_site_cascade(site):
    """LINK 2 / 3 / 2b: suspend active schedules of the site's contracts."""
    contract_ids = set(c["id"] for c in contracts_of_site(site["id"]))
    schedules = ordered([s for s in db.service_schedules.values()
                         if s["contract_id"] in contract_ids
                         and s["state"] == "ACTIVE"])
    for schedule in schedules:
        suspend_schedule(schedule)
    return len(schedules)


def suspend_schedule(schedule):
    """ACTIVE -> SUSPENDED, identical for hand-driven and cascade-driven."""
    schedule["state"] = "SUSPENDED"
    touch(schedule)
    route = db.routes.get(schedule["route_id"])
    if route is not None:
        recompute_route_planned(route)
    today = clock.today()
    for visit in visits_of_schedule(schedule["id"]):
        if visit["state"] == "PLANNED" and visit["scheduled_date"] >= today:
            visit["state"] = "CANCELLED"
            touch(visit)


def terminate_schedule(schedule):
    """Reached only from contract demobilization (PRD 3.5)."""
    previous_state = schedule["state"]
    schedule["state"] = "TERMINATED"
    touch(schedule)
    if previous_state == "ACTIVE":
        route = db.routes.get(schedule["route_id"])
        if route is not None:
            recompute_route_planned(route)
        for visit in visits_of_schedule(schedule["id"]):
            if visit["state"] == "PLANNED":
                visit["state"] = "CANCELLED"
                touch(visit)


# --------------------------------------------------------- route density (3.5)

def recompute_route_planned(route):
    committed = 0
    for schedule in schedules_of_route(route["id"]):
        if schedule["state"] == "ACTIVE":
            committed += schedule["units_on_route"]
    density = calc.density_pct(committed, route["truck_capacity_units"])
    if committed != route["committed_units"] or density != route["density_planned_pct"]:
        route["committed_units"] = committed
        route["density_planned_pct"] = density
        touch(route)


def recompute_route_realized(route):
    if route["last_run_date"] is None:
        density = 0
    else:
        serviced_units = sum(v["units_serviced"]
                             for v in serviced_visits(route["id"], route["last_run_date"]))
        density = calc.density_pct(serviced_units, route["truck_capacity_units"])
    if density != route["density_realized_pct"]:
        route["density_realized_pct"] = density
        touch(route)


# ----------------------------------------------------------- placement counts

def recompute_deployed_unit_count(site_id):
    site = db.service_sites.get(site_id)
    if site is None:
        return
    count = 0
    for deployment in db.unit_deployments.values():
        if deployment["site_id"] == site_id and deployment["state"] == "DEPLOYED":
            count += 1
    if count != site["deployed_unit_count"]:
        site["deployed_unit_count"] = count
        touch(site)


# --------------------------------------------------------- contract ledger 2.7

def recompute_contract_ledger(contract):
    debits = 0
    credits = 0
    for charge in charges_of_contract(contract["id"]):
        if charge["state"] not in ("ASSESSED", "UPHELD"):
            continue
        if charge["charge_kind"] == "MISSED_SERVICE_CREDIT":
            credits += charge["amount_cents"]
        else:
            debits += charge["amount_cents"]
    net = contract["invoice_subtotal_cents"] + debits - credits
    if (debits != contract["charge_debits_cents"]
            or credits != contract["credit_accrued_cents"]
            or net != contract["net_billable_cents"]):
        contract["charge_debits_cents"] = debits
        contract["credit_accrued_cents"] = credits
        contract["net_billable_cents"] = net
        touch(contract)


def recompute_net_billable(contract):
    net = (contract["invoice_subtotal_cents"] + contract["charge_debits_cents"]
           - contract["credit_accrued_cents"])
    if net != contract["net_billable_cents"]:
        contract["net_billable_cents"] = net
        touch(contract)


def flag_rebill_required(contract):
    if contract["billing_state"] == "INVOICED":
        contract["billing_state"] = "REBILL_REQUIRED"
        touch(contract)


def recompute_account(account):
    balance = 0
    for contract in contracts_of_account(account["id"]):
        for charge in charges_of_contract(contract["id"]):
            if (charge["charge_kind"] == "MISSED_SERVICE_CREDIT"
                    and charge["state"] in ("ASSESSED", "UPHELD")):
                balance += charge["amount_cents"]
    hold = balance >= C.ACCOUNT_CREDIT_HOLD_THRESHOLD_CENTS
    if (balance != account["open_credit_balance_cents"]
            or hold != account["billing_hold"]):
        account["open_credit_balance_cents"] = balance
        account["billing_hold"] = hold
        touch(account)


def recompute_asset_strikes(unit):
    damage = 0
    tip_over = 0
    for charge in db.charge_events.values():
        if charge["asset_unit_id"] != unit["id"]:
            continue
        if charge["state"] not in ("ASSESSED", "UPHELD"):
            continue
        if charge["charge_kind"] == "DAMAGE":
            damage += 1
        elif charge["charge_kind"] == "TIP_OVER":
            tip_over += 1
    if damage != unit["damage_strikes"] or tip_over != unit["tip_over_count"]:
        unit["damage_strikes"] = damage
        unit["tip_over_count"] = tip_over
        touch(unit)


def apply_charge_state_effects(charge, with_strikes=False):
    """Shared cascade for any ChargeEvent state change (PRD 2.7, 3.8)."""
    contract = db.rental_contracts.get(charge["contract_id"])
    if contract is None:
        return
    recompute_contract_ledger(contract)
    account = db.rental_accounts.get(contract["account_id"])
    if account is not None:
        recompute_account(account)
    if with_strikes and charge["charge_kind"] in ("DAMAGE", "TIP_OVER"):
        unit = db.asset_units.get(charge["asset_unit_id"])
        if unit is not None:
            recompute_asset_strikes(unit)
            total = unit["damage_strikes"] + unit["tip_over_count"]
            if (total < C.UNIT_REPAIR_STRIKE_THRESHOLD
                    and unit["status"] == "IN_REPAIR"):
                unit["status"] = "IN_YARD"
                touch(unit)
    flag_rebill_required(contract)
    if charge["charge_kind"] == "TIP_OVER":
        site = db.service_sites.get(contract["site_id"])
        if site is not None:
            recompute_site_posture(site)


# ------------------------------------------------------------- quote lines

def supersede_lines(contract_id, variant=None):
    for line in quote_lines_of_contract(contract_id):
        if line["is_superseded"]:
            continue
        if variant is not None and line["quote_variant"] != variant:
            continue
        line["is_superseded"] = True


def create_quote_lines(contract, pairs, variant):
    total = 0
    for unit_class, quantity in pairs:
        rate = calc.unit_rate_cents(unit_class)
        extended = calc.extended_cents(quantity, rate)
        total += extended
        insert("quote_lines", {
            "contract_id": contract["id"],
            "unit_class": unit_class,
            "quantity": quantity,
            "unit_rate_cents": rate,
            "extended_cents": extended,
            "escalated_cents": 0,
            "quote_variant": variant,
            "is_superseded": False,
        }, common_fields=False)
    return total


# ------------------------------------------------------------ waste manifests

def manifest_rollup(route_id, manifest_date):
    return sum(v["gallons_pumped"] for v in serviced_visits(route_id, manifest_date))


def refresh_open_manifests(route_id, manifest_date):
    for manifest in manifests_of_route_date(route_id, manifest_date):
        if manifest["state"] != "OPEN":
            continue
        total = manifest_rollup(route_id, manifest_date)
        if total != manifest["gallons_total"]:
            manifest["gallons_total"] = total
            touch(manifest)


def committed_for_date(disposal_site_id, date, exclude_manifest_id=None):
    total = 0
    for manifest in db.waste_manifests.values():
        if manifest["disposal_site_id"] != disposal_site_id:
            continue
        if manifest["manifest_date"] != date:
            continue
        if manifest["state"] not in ("SEALED", "ACCEPTED"):
            continue
        if exclude_manifest_id is not None and manifest["id"] == exclude_manifest_id:
            continue
        total += manifest["gallons_total"]
    return total


def recompute_committed_gallons_today(disposal_site):
    total = committed_for_date(disposal_site["id"], clock.today())
    if total != disposal_site["committed_gallons_today"]:
        disposal_site["committed_gallons_today"] = total
        touch(disposal_site)


def disposal_view(disposal_site):
    """committed_gallons_today is always read against the current clock date."""
    payload = serialize(disposal_site)
    payload["committed_gallons_today"] = committed_for_date(
        disposal_site["id"], clock.today())
    return payload


# ------------------------------------------------------------- visit windows

def gate_window_contained(site, window_start_minute, window_end_minute):
    return (site["gate_open_minute"] <= window_start_minute
            and window_end_minute <= site["gate_close_minute"])


def route_window_conflict(route_id, scheduled_date, window_start_minute,
                          window_end_minute, exclude_visit_ids=()):
    buffer_minutes = C.ROUTE_TURNAROUND_BUFFER_MINUTES
    for visit in db.service_visits.values():
        if visit["route_id"] != route_id:
            continue
        if visit["scheduled_date"] != scheduled_date:
            continue
        if visit["id"] in exclude_visit_ids:
            continue
        if visit["state"] not in ("PLANNED", "EN_ROUTE", "SERVICED"):
            continue
        if (window_start_minute < visit["window_end_minute"] + buffer_minutes
                and visit["window_start_minute"] < window_end_minute + buffer_minutes):
            return True
    return False


def site_of_schedule(schedule):
    contract = db.rental_contracts.get(schedule["contract_id"])
    if contract is None:
        return None
    return db.service_sites.get(contract["site_id"])


# ------------------------------------------------------- permit expiry sweep

def expire_permits_sweep():
    today = clock.today()
    candidates = ordered([p for p in db.placement_permits.values()
                          if p["status"] == "APPROVED"
                          and p["effective_to"] < today])
    expired_permit_count = 0
    blocked_sites = set()
    suspended_schedule_count = 0
    for permit in candidates:
        permit["status"] = "EXPIRED"
        touch(permit)
        expired_permit_count += 1
        site = db.service_sites.get(permit["site_id"])
        if site is None:
            continue
        outcome = recompute_site_posture(site)
        if outcome["became_blocked"]:
            blocked_sites.add(site["id"])
        suspended_schedule_count += outcome["suspended"]
    return expired_permit_count, len(blocked_sites), suspended_schedule_count
