"""Business logic: calculations, cascades, derived fields, ops run."""

from datetime import timedelta
from decimal import Decimal

from db import db
from helpers import (
    api_err, iso, round_half_up_cents, round_half_up_2dp, round_half_up_1dp,
    touch,
)

OPEN_CASE_STATES = {"OPEN", "TRIAGE", "SCHEDULED", "IN_SERVICE", "AWAITING_PART", "PENDING_CLOSE"}

# Labor time standards
BASE_HOURS_TABLE = {
    "SPN3216_FMI4": Decimal("4.0"),
    "SPN3226_FMI4": Decimal("3.5"),
    "SPN168_FMI4": Decimal("2.0"),
}
DEFAULT_BASE_HOURS = Decimal("2.5")
CLAIM_TYPE_MULTIPLIER = {
    "BASE_WARRANTY": Decimal("1.0"),
    "CAMPAIGN": Decimal("0.9"),
    "EXTENDED_COVERAGE": Decimal("1.1"),
    "GOODWILL": Decimal("0.0"),
}

FREIGHT_RATES = {
    "INTRA_REGION": (15000, 300),
    "CROSS_COUNTRY": (45000, 900),
    "INTERNATIONAL": (150000, 3000),
}

REPEAT_THRESHOLD = 3
REPEAT_WINDOW_DAYS = 90
REPEAT_PENALTY = 25
DOWNTIME_PENALTY_THRESHOLD_HOURS = Decimal("24.0")
DOWNTIME_PENALTY = 10
NOT_FIXED_PENALTY = 15
CAMPAIGN_OVERDUE_PENALTY = 5


# ---------------------------------------------------------------------------
# Derived counters
# ---------------------------------------------------------------------------

def refresh_dealer_derived(dealer):
    dealer["bay_count"] = sum(
        1 for b in db.bays.values()
        if b["dealer_id"] == dealer["id"] and b["bay_status"] != "DECOMMISSIONED"
    )
    dealer["active_case_count"] = sum(
        1 for c in db.cases.values()
        if c.get("dealer_id") == dealer["id"]
        and c["case_status"] in {"SCHEDULED", "IN_SERVICE", "AWAITING_PART"}
    )


# ---------------------------------------------------------------------------
# Reliability score
# ---------------------------------------------------------------------------

def record_penalty(fleet_id, kind, amount):
    fleet = db.fleets[fleet_id]
    fleet["reliability_score"] = max(0, fleet["reliability_score"] - amount)
    db.reliability_events.append((fleet_id, kind, amount))


def recompute_reliability_from_scratch(fleet):
    """Snapshot variant: recompute from full event history for this fleet."""
    score = 1000
    for fid, _kind, amount in db.reliability_events:
        if fid == fleet["id"]:
            score -= amount
    fleet["reliability_score"] = max(0, score)


# ---------------------------------------------------------------------------
# Repeat repair window
# ---------------------------------------------------------------------------

def repeat_repair_count(truck_id, fault_code):
    now = db.now()
    window_start = now - timedelta(days=REPEAT_WINDOW_DAYS)
    count = 0
    for c in db.cases.values():
        if c["truck_id"] != truck_id or c["fault_code"] != fault_code:
            continue
        if c["case_status"] == "CANCELLED":
            continue
        if c["opened_at_dt"] >= window_start:
            count += 1
    return count


def evaluate_repeat_repair(truck, fault_code):
    """Evaluate the window for one (truck, fault_code); apply/clear penalty."""
    fleet = db.fleets[truck["fleet_id"]]
    key = (truck["id"], fault_code)
    count = repeat_repair_count(truck["id"], fault_code)
    if count >= REPEAT_THRESHOLD:
        if key not in db.repeat_penalized:
            db.repeat_penalized.add(key)
            record_penalty(fleet["id"], "repeat_repair", REPEAT_PENALTY)
        truck["repeat_repair_flag"] = True
    else:
        if key in db.repeat_penalized:
            db.repeat_penalized.discard(key)
        # Clear flag only if no other fault code is still in repeat state
        truck["repeat_repair_flag"] = any(
            k[0] == truck["id"] for k in db.repeat_penalized
        )


def reevaluate_repeat_repair_all(truck):
    """Re-evaluate every fault code seen on this truck (window slide at ops run)."""
    fault_codes = {c["fault_code"] for c in db.cases.values() if c["truck_id"] == truck["id"]}
    for fc in fault_codes:
        evaluate_repeat_repair(truck, fc)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def labor_time_standard(fault_code, claim_type):
    base = BASE_HOURS_TABLE.get(fault_code, DEFAULT_BASE_HOURS)
    mult = CLAIM_TYPE_MULTIPLIER[claim_type]
    hours = round_half_up_2dp(base * mult)
    return hours


def compute_labor_amount_cents(labor_hours_allowed, rate_cents_per_hour):
    return round_half_up_cents(Decimal(str(labor_hours_allowed)) * Decimal(rate_cents_per_hour))


def coverage_proration(contract, truck, cancel_at):
    """Two bases, take smaller credit; rationals; round once at end."""
    premium = Decimal(contract["premium_cents"])
    total_days = (contract["ends_on_dt"] - contract["starts_on_dt"]).days
    elapsed_days = (cancel_at - contract["starts_on_dt"]).days
    if elapsed_days < 0:
        elapsed_days = 0
    if elapsed_days > total_days:
        elapsed_days = total_days
    if total_days > 0:
        time_credit = premium * Decimal(total_days - elapsed_days) / Decimal(total_days)
    else:
        time_credit = Decimal(0)

    total_miles = Decimal(contract["max_miles"])
    used_miles = truck["odometer_miles"] - contract.get("odometer_at_start_miles", 0)
    if used_miles < 0:
        used_miles = 0
    if used_miles > contract["max_miles"]:
        used_miles = contract["max_miles"]
    if total_miles > 0:
        mileage_credit = premium * Decimal(total_miles - used_miles) / Decimal(total_miles)
    else:
        mileage_credit = Decimal(0)

    credit = min(time_credit, mileage_credit)
    return round_half_up_cents(credit)


def parts_cap_pct(claim, truck):
    ct = claim["claim_type"]
    if ct == "BASE_WARRANTY":
        return Decimal("1.0") if truck["odometer_miles"] <= truck["base_warranty_until_miles"] else Decimal("0.0")
    if ct == "CAMPAIGN":
        return Decimal("1.0")
    if ct == "EXTENDED_COVERAGE":
        # Active coverage contract on the truck; use its proration fraction
        contracts = [c for c in db.coverage_contracts.values()
                     if c["truck_id"] == truck["id"] and c["contract_status"] == "ACTIVE"]
        if not contracts:
            return Decimal("0.0")
        contract = contracts[0]
        if contract["premium_cents"] <= 0:
            return Decimal("0.0")
        credit = coverage_proration(contract, truck, db.now())
        pct = Decimal(credit) / Decimal(contract["premium_cents"])
        return min(Decimal("1.0"), pct)
    # GOODWILL
    return Decimal("0.5")


def parts_allowance(claim, truck):
    pct = parts_cap_pct(claim, truck)
    return round_half_up_cents(Decimal(claim["parts_claimed_cents"]) * pct)


def expedite_freight_cost(quantity, weight_per_unit, distance_band):
    """Returns (overnight_cents, standard_cents, total_weight_kg)."""
    weight_total = Decimal(str(quantity)) * Decimal(str(weight_per_unit))
    weight_total = round_half_up_1dp(weight_total)
    if weight_total <= 0:
        raise api_err("ERR_INVALID_REQUEST", "total weight must be greater than 0.0 kg")
    base, per_kg = FREIGHT_RATES[distance_band]
    overnight = base + round_half_up_cents(Decimal(per_kg) * Decimal(str(weight_total)))
    standard = round_half_up_cents(Decimal("0.4") * Decimal(overnight))
    return overnight, standard, weight_total


def expedite_decision_calc(dealer_repair_hours_est, downtime_rate_cents_per_hour,
                           overnight_cents, standard_cents):
    downtime_cost = round_half_up_cents(
        Decimal(str(dealer_repair_hours_est)) * Decimal(str(downtime_rate_cents_per_hour)))
    overnight_gain = downtime_cost - overnight_cents
    standard_gain = round_half_up_cents(Decimal("0.6") * Decimal(downtime_cost)) - standard_cents
    if overnight_gain >= 0 and overnight_gain >= standard_gain:
        return "EXPEDITE_OVERNIGHT", overnight_cents, downtime_cost
    if standard_gain >= 0:
        return "EXPEDITE_STANDARD", standard_cents, downtime_cost
    return "DENIED", 0, downtime_cost


def campaign_completion_pct(campaign):
    rows = [c for c in db.campaign_completions.values()
            if c["campaign_id"] == campaign["id"] and c["completion_status"] != "EXEMPTED"]
    if not rows:
        return 0.0
    completed = sum(1 for r in rows if r["completion_status"] == "COMPLETED")
    return round_half_up_2dp(Decimal("100.0") * Decimal(completed) / Decimal(len(rows)))


def refresh_campaign_pct(campaign):
    campaign["completion_pct"] = campaign_completion_pct(campaign)
    touch(campaign)


# ---------------------------------------------------------------------------
# Case close / cancel cascades
# ---------------------------------------------------------------------------

def close_case_effects(case):
    """Side effects for PENDING_CLOSE -> CLOSED."""
    truck = db.trucks[case["truck_id"]]
    fleet = db.fleets[case["fleet_id"]]
    now = db.now()
    case["case_status"] = "CLOSED"
    case["closed_at_dt"] = now
    case["closed_at"] = iso(now)
    elapsed = now - case["opened_at_dt"]
    hours = Decimal(str(elapsed.total_seconds())) / Decimal("3600")
    downtime = round_half_up_2dp(hours)
    if downtime < 0:
        downtime = 0.0
    case["downtime_hours"] = downtime
    fleet["total_downtime_hours"] = round_half_up_2dp(
        Decimal(str(fleet["total_downtime_hours"])) + Decimal(str(downtime)))

    if Decimal(str(downtime)) > DOWNTIME_PENALTY_THRESHOLD_HOURS:
        record_penalty(fleet["id"], "downtime", DOWNTIME_PENALTY)

    # Release bay if still IN_USE for this case
    for wo in db.work_orders.values():
        if wo["case_id"] == case["id"] and wo.get("bay_id"):
            bay = db.bays.get(wo["bay_id"])
            if bay and bay["bay_status"] == "IN_USE":
                bay["bay_status"] = "AVAILABLE"
                touch(bay)

    truck["open_case_count"] = max(0, truck["open_case_count"] - 1)
    fleet["open_case_count"] = max(0, fleet["open_case_count"] - 1)
    touch(truck)
    touch(fleet)

    if truck["open_case_count"] == 0 and truck["truck_status"] == "DOWN":
        truck["truck_status"] = "IN_SERVICE"
        touch(truck)

    # Complete linked campaign completions
    for cc in db.campaign_completions.values():
        if cc.get("case_id") == case["id"] and cc["completion_status"] == "SCHEDULED":
            cc["completion_status"] = "COMPLETED"
            touch(cc)
            refresh_campaign_pct(db.campaigns[cc["campaign_id"]])

    # Repeat repair re-eval at close
    evaluate_repeat_repair(truck, case["fault_code"])
    refresh_dealer_derived_for_case(case)
    touch(case)


def cancel_case_effects(case):
    truck = db.trucks[case["truck_id"]]
    fleet = db.fleets[case["fleet_id"]]
    case["case_status"] = "CANCELLED"
    case["closed_at"] = None
    case["closed_at_dt"] = None

    for wo in db.work_orders.values():
        if wo["case_id"] == case["id"] and wo["work_order_status"] == "DRAFT":
            wo["work_order_status"] = "CANCELLED"
            touch(wo)
            if wo.get("bay_id"):
                bay = db.bays.get(wo["bay_id"])
                if bay and bay["bay_status"] == "RESERVED":
                    bay["bay_status"] = "AVAILABLE"
                    touch(bay)

    for po in db.part_orders.values():
        if po["case_id"] == case["id"] and po["part_order_status"] == "PENDING":
            if po.get("expedite_decision") == "EXPEDITE_OVERNIGHT":
                case["expedite_count"] = max(0, case["expedite_count"] - 1)
            po["part_order_status"] = "CANCELLED"
            touch(po)

    truck["open_case_count"] = max(0, truck["open_case_count"] - 1)
    fleet["open_case_count"] = max(0, fleet["open_case_count"] - 1)
    touch(truck)
    touch(fleet)

    # Campaign completions linked to this case revert SCHEDULED -> OPEN
    for cc in db.campaign_completions.values():
        if cc.get("case_id") == case["id"] and cc["completion_status"] == "SCHEDULED":
            cc["completion_status"] = "OPEN"
            cc["case_id"] = None
            touch(cc)

    refresh_dealer_derived_for_case(case)
    touch(case)


def refresh_dealer_derived_for_case(case):
    if case.get("dealer_id") and case["dealer_id"] in db.dealers:
        dealer = db.dealers[case["dealer_id"]]
        before_bays = dealer["bay_count"]
        before_cases = dealer["active_case_count"]
        refresh_dealer_derived(dealer)
        if (dealer["bay_count"], dealer["active_case_count"]) != (before_bays, before_cases):
            touch(dealer)


def maybe_back_in_service(case):
    """If all part orders on the case are terminal, AWAITING_PART -> IN_SERVICE."""
    if case["case_status"] != "AWAITING_PART":
        return
    open_pos = [p for p in db.part_orders.values()
                if p["case_id"] == case["id"]
                and p["part_order_status"] not in ("INSTALLED", "CANCELLED")]
    if not open_pos:
        case["case_status"] = "IN_SERVICE"
        touch(case)


# ---------------------------------------------------------------------------
# Ops run
# ---------------------------------------------------------------------------

def ops_run():
    db.ops_run_index += 1
    now = db.now()

    # (a) Overdue campaign sweep + repeat-repair window slide per truck
    for campaign in db.campaigns.values():
        overdue_rows = [cc for cc in db.campaign_completions.values()
                        if cc["campaign_id"] == campaign["id"]
                        and cc["completion_status"] == "OPEN"
                        and campaign["closes_on_dt"] < now]
        for cc in overdue_rows:
            truck = db.trucks.get(cc["truck_id"])
            if truck:
                record_penalty(truck["fleet_id"], "campaign_overdue", CAMPAIGN_OVERDUE_PENALTY)
        campaign["overdue_count"] = len(overdue_rows)
        touch(campaign)

    for truck in db.trucks.values():
        reevaluate_repeat_repair_all(truck)
        touch(truck)

    # (b) Coverage contract expiry
    for contract in db.coverage_contracts.values():
        if contract["contract_status"] != "ACTIVE":
            continue
        truck = db.trucks[contract["truck_id"]]
        if now >= contract["ends_on_dt"] or truck["odometer_miles"] >= contract["max_miles"]:
            contract["contract_status"] = "EXPIRED"
            touch(contract)

    # (c) Late part returns
    for pr in db.part_returns.values():
        if pr["part_return_status"] != "REQUESTED":
            continue
        deadline = pr["created_at_dt"] + timedelta(days=pr["return_window_days"])
        if now > deadline:
            pr["part_return_status"] = "LATE_REJECTED"
            touch(pr)
            claim = db.claims[pr["claim_id"]]
            claim["recovery_status"] = "RECOVERY_DENIED"
            touch(claim)

    # (d) Reliability recompute from scratch (audit)
    for fleet in db.fleets.values():
        recompute_reliability_from_scratch(fleet)
        touch(fleet)

    # (e) Snapshot per fleet
    import uuid
    for fleet in db.fleets.values():
        trucks = [t for t in db.trucks.values() if t["fleet_id"] == fleet["id"]]
        in_service = sum(1 for t in trucks if t["truck_status"] == "IN_SERVICE")
        down = sum(1 for t in trucks if t["truck_status"] == "DOWN")
        repeat_count = sum(1 for t in trucks if t["repeat_repair_flag"])
        # Weighted mean of OPEN campaigns' completion_pct weighted by in-scope count
        open_campaigns = [c for c in db.campaigns.values() if c["campaign_status"] == "OPEN"]
        num = Decimal(0)
        den = 0
        for camp in open_campaigns:
            scope = [cc for cc in db.campaign_completions.values()
                     if cc["campaign_id"] == camp["id"] and cc["completion_status"] != "EXEMPTED"]
            if scope:
                num += Decimal(str(camp["completion_pct"])) * Decimal(len(scope))
                den += len(scope)
        if den > 0:
            weighted = round_half_up_2dp(num / Decimal(den))
        else:
            weighted = 0.0
        rid = str(uuid.uuid4())
        ts = iso(now)
        db.reliability_reports[rid] = {
            "id": rid,
            "created_at": ts,
            "created_at_dt": now,
            "fleet_id": fleet["id"],
            "ops_run_index": db.ops_run_index,
            "computed_at": ts,
            "trucks_in_service": in_service,
            "trucks_down": down,
            "total_downtime_hours": fleet["total_downtime_hours"],
            "repeat_repair_truck_count": repeat_count,
            "campaign_completion_pct": weighted,
            "reliability_score": fleet["reliability_score"],
        }

    return db.ops_run_index, len(db.fleets)
