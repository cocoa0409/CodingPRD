"""Domain constants, calculations, derived aggregates and cascades."""
from decimal import Decimal

from common import (add_days_iso, dec, parse_dt, rhu, rhu_float, rhu_int,
                    whole_days)
from store import db, touch

# --------------------------------------------------------------------------
# Constants (SCAFFOLD 1.3)
# --------------------------------------------------------------------------
AUM_DEMAND_LBS_PER_MONTH = Decimal("790")
DAILY_DEMAND_LBS = Decimal("26")
HISTORY_SAFETY_FACTOR = Decimal("0.85")
DAYS_PER_MONTH = Decimal("30.4")

DEATH_CREDIT_PCT = Decimal("60")
INFRA_SHARED_OWNER_PCT = Decimal("50")

DROUGHT_SEVERE_INDEX = 3
DROUGHT_CONSECUTIVE_REQUIRED = 2
DROUGHT_FORAGE_FLOOR_PCT = Decimal("20")
DROUGHT_RECOVERY_INDEX = 1
DROUGHT_NOTICE_DAYS = 15

REST_DAYS_BUFFER = 14
DISPUTE_WINDOW_DAYS = 10
MAX_DISPUTE_ROUNDS = 2

ADG_TIER_2_FLOOR = Decimal("1.50")
ADG_TIER_3_FLOOR = Decimal("2.25")
ADG_TIER_1_MULT = Decimal("1.00")
ADG_TIER_2_MULT = Decimal("1.10")
ADG_TIER_3_MULT = Decimal("1.20")
GAIN_CAP_LBS_PER_HEAD = Decimal("250")

DROUGHT_WAIVER_PCT = Decimal("5")
OWNER_EARLY_PENALTY_PCT = Decimal("8")
GRAZIER_EARLY_CREDIT_PCT = Decimal("10")
REBATE_TIER_1_FLOOR = 500000
REBATE_TIER_2_FLOOR = 1500000

DEFAULT_CREDIT_LIMIT_CENTS = 500000

COMMITTED_LIFECYCLES = ("PENDING_SIGNATURE", "ACTIVE", "EARLY_REMOVAL_PENDING")
LIVE_LIFECYCLES = ("PENDING_SIGNATURE", "SUSPENDED", "ACTIVE", "EARLY_REMOVAL_PENDING")
STOCKED_LOT_STATES = ("ON_FEED", "REMOVAL_SCHEDULED")
OPEN_TICKET_STATES = ("OPEN", "ASSIGNED_GRAZIER", "ASSIGNED_OWNER")
OPEN_BALANCE_STATES = ("ISSUED", "DISPUTED", "ADJUDICATED", "FINAL")


# --------------------------------------------------------------------------
# Graph helpers
# --------------------------------------------------------------------------
def sorted_records(records):
    return sorted(records, key=lambda r: r["_seq"])


def contracts_of_pasture(pasture_id):
    return sorted_records([c for c in db.contracts.values() if c["pasture_id"] == pasture_id])


def lots_of_contract(contract_id):
    return sorted_records([l for l in db.lots.values() if l["contract_id"] == contract_id])


def lots_of_pasture(pasture_id):
    out = []
    for contract in contracts_of_pasture(pasture_id):
        out.extend(lots_of_contract(contract["id"]))
    return sorted_records(out)


def treatments_of_lot(lot_id):
    return sorted_records([t for t in db.treatments.values() if t["lot_id"] == lot_id])


def deaths_of_lot(lot_id):
    return sorted_records([d for d in db.death_losses.values() if d["lot_id"] == lot_id])


def weight_events_of_lot(lot_id):
    return sorted_records([w for w in db.weight_events.values() if w["lot_id"] == lot_id])


def tickets_of_pasture(pasture_id):
    return sorted_records([t for t in db.tickets.values() if t["pasture_id"] == pasture_id])


def tickets_of_contract(contract_id):
    return sorted_records([t for t in db.tickets.values() if t["contract_id"] == contract_id])


def settlements_of_contract(contract_id):
    return sorted_records([s for s in db.settlements.values() if s["contract_id"] == contract_id])


def settlements_of_lot(lot_id):
    return sorted_records([s for s in db.settlements.values() if s["lot_id"] == lot_id])


def contract_of_lot(lot):
    return db.contracts.get(lot["contract_id"])


def pasture_of_contract(contract):
    return db.pastures.get(contract["pasture_id"])


def pasture_of_lot(lot):
    contract = contract_of_lot(lot)
    return pasture_of_contract(contract) if contract else None


# --------------------------------------------------------------------------
# calculations.capacity_assessment_rating
# --------------------------------------------------------------------------
def capacity_rating(pasture, method, forage_dm, utilization_pct):
    if method == "DRY_MATTER":
        usable = dec(pasture["acres"]) * dec(forage_dm) * (dec(utilization_pct) / Decimal(100))
        rated_aum = rhu(usable / AUM_DEMAND_LBS_PER_MONTH, 2)
        rated_head_days = int((usable / DAILY_DEMAND_LBS).to_integral_value(rounding="ROUND_FLOOR"))
    else:  # STOCKING_HISTORY
        prior = dec(pasture.get("prior_season_head_days") or 0)
        rated_head_days = int((prior * HISTORY_SAFETY_FACTOR).to_integral_value(rounding="ROUND_FLOOR"))
        rated_aum = rhu(prior * HISTORY_SAFETY_FACTOR / DAYS_PER_MONTH, 2)
    return float(rated_aum), rated_head_days


def select_effective_assessment(pasture):
    """Greatest assessment_date wins; the later-created row breaks the tie."""
    rows = [a for a in db.assessments.values() if a["pasture_id"] == pasture["id"]]
    if not rows:
        return None
    rows.sort(key=lambda a: (parse_dt(a["assessment_date"]), a["_seq"]))
    return rows[-1]


def apply_effective_assessment(pasture):
    effective = select_effective_assessment(pasture)
    if effective is None:
        pasture["effective_assessment_id"] = None
        pasture["rated_aum"] = 0
        pasture["rated_head_days"] = 0
    else:
        pasture["effective_assessment_id"] = effective["id"]
        pasture["rated_aum"] = effective["rated_aum"]
        pasture["rated_head_days"] = effective["rated_head_days"]


# --------------------------------------------------------------------------
# calculations.pasture_grazing_posture + derived aggregates (PRD 2.9 / 2.10)
# --------------------------------------------------------------------------
def compute_posture(operational_status, destock_flag, critical_count, utilization_pct):
    if operational_status == "CLOSED":
        return "CLOSED"
    if destock_flag:
        return "DESTOCK_ORDERED"
    if critical_count > 0 or dec(utilization_pct) > Decimal(100):
        return "RESTRICTED"
    return "OPEN"


def recompute_pasture(pasture):
    """Recompute every derived field of a pasture; cascade posture to lots."""
    if pasture is None:
        return
    before = (
        pasture.get("committed_head_days"),
        pasture.get("capacity_utilization_pct"),
        pasture.get("stocked_head_count"),
        pasture.get("open_critical_ticket_count"),
        pasture.get("grazing_posture"),
        pasture.get("effective_assessment_id"),
        pasture.get("rated_aum"),
        pasture.get("rated_head_days"),
    )
    old_posture = pasture.get("grazing_posture")

    committed = 0
    for contract in contracts_of_pasture(pasture["id"]):
        if contract["lifecycle_status"] in COMMITTED_LIFECYCLES:
            committed += contract["committed_head_days"]
    pasture["committed_head_days"] = committed

    rated = pasture.get("rated_head_days") or 0
    if rated == 0:
        pasture["capacity_utilization_pct"] = 0
    else:
        pasture["capacity_utilization_pct"] = rhu_float(dec(committed) / dec(rated) * Decimal(100), 2)

    stocked = 0
    for lot in lots_of_pasture(pasture["id"]):
        if lot["status"] in STOCKED_LOT_STATES:
            stocked += (lot["head_count_received"] or 0) - (lot["confirmed_death_head"] or 0)
    pasture["stocked_head_count"] = stocked

    critical = 0
    for ticket in tickets_of_pasture(pasture["id"]):
        if ticket["severity"] == "CRITICAL" and ticket["status"] in OPEN_TICKET_STATES:
            critical += 1
    pasture["open_critical_ticket_count"] = critical

    pasture["grazing_posture"] = compute_posture(
        pasture["operational_status"],
        pasture.get("drought_destock_flag", False),
        critical,
        pasture["capacity_utilization_pct"],
    )

    after = (
        pasture.get("committed_head_days"),
        pasture.get("capacity_utilization_pct"),
        pasture.get("stocked_head_count"),
        pasture.get("open_critical_ticket_count"),
        pasture.get("grazing_posture"),
        pasture.get("effective_assessment_id"),
        pasture.get("rated_aum"),
        pasture.get("rated_head_days"),
    )
    if before != after:
        touch(pasture)

    new_posture = pasture["grazing_posture"]
    if old_posture != new_posture:
        if new_posture != "OPEN":
            for lot in lots_of_pasture(pasture["id"]):
                if lot["status"] == "SCHEDULED":
                    lot["status"] = "RECEIVING_HELD"
                    touch(lot)
        else:
            for lot in lots_of_pasture(pasture["id"]):
                if lot["status"] == "RECEIVING_HELD":
                    lot["status"] = "SCHEDULED"
                    touch(lot)


# --------------------------------------------------------------------------
# calculations.owner_open_balance (PRD 3.1)
# --------------------------------------------------------------------------
def recompute_owner_credit(owner):
    """Recompute balance/standing; cascade a standing flip onto contracts."""
    if owner is None:
        return
    before_status = owner.get("credit_status")
    before_balance = owner.get("open_settlement_balance_cents")

    balance = 0
    for settlement in db.settlements.values():
        if settlement["status"] not in OPEN_BALANCE_STATES:
            continue
        contract = db.contracts.get(settlement["contract_id"])
        if contract is None or contract["cattle_owner_id"] != owner["id"]:
            continue
        balance += settlement["total_due_cents"]

    owner["open_settlement_balance_cents"] = balance
    owner["credit_status"] = "DELINQUENT" if balance > owner["credit_limit_cents"] else "GOOD_STANDING"

    if (owner["open_settlement_balance_cents"] != before_balance
            or owner["credit_status"] != before_status):
        touch(owner)

    if before_status == "GOOD_STANDING" and owner["credit_status"] == "DELINQUENT":
        _cascade_credit(owner, "PENDING_SIGNATURE", "SUSPENDED")
    elif before_status == "DELINQUENT" and owner["credit_status"] == "GOOD_STANDING":
        _cascade_credit(owner, "SUSPENDED", "PENDING_SIGNATURE")


def _cascade_credit(owner, from_state, to_state):
    affected = []
    for contract in sorted_records(db.contracts.values()):
        if contract["cattle_owner_id"] != owner["id"]:
            continue
        if contract["lifecycle_status"] != from_state:
            continue
        contract["lifecycle_status"] = to_state
        touch(contract)
        affected.append(contract)
    for pasture in _unique_pastures(affected):
        recompute_pasture(pasture)


def _unique_pastures(contracts):
    seen = {}
    for contract in contracts:
        pasture = pasture_of_contract(contract)
        if pasture is not None:
            seen[pasture["id"]] = pasture
    return list(seen.values())


# --------------------------------------------------------------------------
# calculations.shrunk_weight (PRD 3.4) — pinned lot-level rounding order
# --------------------------------------------------------------------------
def shrunk_weight(gross_weight_lbs, shrink_pct):
    return rhu_int(dec(gross_weight_lbs) * (Decimal(1) - dec(shrink_pct) / Decimal(100)))


# --------------------------------------------------------------------------
# calculations.treatment_cost_allocation (PRD 3.5)
# --------------------------------------------------------------------------
def treatment_allocation(classification, total_cost_cents, treatment_cost_split_pct):
    if classification == "ROUTINE_PROTOCOL":
        owner_pct = Decimal(100) - dec(treatment_cost_split_pct)
    elif classification == "THERAPEUTIC":
        owner_pct = Decimal(100)
    else:  # PREVENTIVE_EMERGENCY
        owner_pct = Decimal(0)
    owner_share = rhu_int(dec(total_cost_cents) * owner_pct / Decimal(100))
    return owner_share, total_cost_cents - owner_share


# --------------------------------------------------------------------------
# calculations.death_loss_liability (PRD 3.6)
# --------------------------------------------------------------------------
def death_loss_sweep(lot):
    """Re-run the chronological liability sweep over the lot's CONFIRMED rows."""
    contract = contract_of_lot(lot)
    reports = deaths_of_lot(lot["id"])

    for report in reports:
        if report["status"] != "CONFIRMED":
            if (report["owner_liable_head"], report["grazier_liable_head"], report["credit_cents"]) != (0, 0, 0):
                report["owner_liable_head"] = 0
                report["grazier_liable_head"] = 0
                report["credit_cents"] = 0
                touch(report)

    confirmed = [r for r in reports if r["status"] == "CONFIRMED"]
    confirmed.sort(key=lambda r: (parse_dt(r["death_date"]), r["_seq"]))

    threshold_head = int(
        (dec(lot["head_count_received"] or 0) * dec(contract["death_loss_threshold_pct"]) / Decimal(100))
        .to_integral_value(rounding="ROUND_FLOOR")
    )
    running_head = 0
    for report in confirmed:
        head_lost = report["head_lost"]
        if report["cause"] == "INFRASTRUCTURE_FAILURE":
            owner_head = 0
            grazier_head = head_lost
        elif contract["death_loss_terms"] == "OWNER_BEARS_ALL":
            owner_head = head_lost
            grazier_head = 0
        else:
            owner_head = min(head_lost, max(0, threshold_head - running_head))
            grazier_head = head_lost - owner_head
        credit = rhu_int(dec(grazier_head) * dec(contract["head_value_cents"]) * DEATH_CREDIT_PCT / Decimal(100))
        if (report["owner_liable_head"], report["grazier_liable_head"], report["credit_cents"]) != \
                (owner_head, grazier_head, credit):
            report["owner_liable_head"] = owner_head
            report["grazier_liable_head"] = grazier_head
            report["credit_cents"] = credit
            touch(report)
        running_head += head_lost

    total_dead = sum(r["head_lost"] for r in confirmed)
    if lot["confirmed_death_head"] != total_dead:
        lot["confirmed_death_head"] = total_dead
        touch(lot)


# --------------------------------------------------------------------------
# calculations.infrastructure_cost_allocation (PRD 3.7)
# --------------------------------------------------------------------------
def infrastructure_allocation(ticket, contract, branch):
    if ticket["asset_type"] == "WATER":
        base_party = contract["water_responsibility"]
    else:
        base_party = contract["fence_responsibility"]

    cause = ticket["cause"]
    if cause == "LIVESTOCK_DAMAGE":
        responsible = "OWNER"
    elif cause == "NEGLECT":
        responsible = "GRAZIER"
    else:
        responsible = base_party

    cost = ticket["repair_cost_cents"]
    if responsible == "GRAZIER":
        raw_owner = 0
    elif responsible == "OWNER":
        raw_owner = cost
    else:
        raw_owner = rhu_int(dec(cost) * INFRA_SHARED_OWNER_PCT / Decimal(100))

    matrix_owner = min(raw_owner, contract["infrastructure_owner_cap_cents"])
    matrix_grazier = cost - matrix_owner

    if branch == "ASSIGNED_GRAZIER":
        owner_share = matrix_owner
    else:
        owner_share = -matrix_grazier

    ticket["responsible_party"] = responsible
    ticket["owner_share_cents"] = owner_share
    ticket["grazier_share_cents"] = matrix_grazier


# --------------------------------------------------------------------------
# calculations.grazing_window_conflict (PRD 3.3)
# --------------------------------------------------------------------------
def grazing_window_conflicts(contract):
    new_start = parse_dt(contract["start_date"])
    new_end = parse_dt(contract["end_date"])
    for other in contracts_of_pasture(contract["pasture_id"]):
        if other["id"] == contract["id"]:
            continue
        if other["lifecycle_status"] not in ("ACTIVE", "EARLY_REMOVAL_PENDING"):
            continue
        other_start = parse_dt(other["start_date"])
        other_end = parse_dt(other["end_date"])
        if new_start < other_end and other_start < new_end:
            return True
        gap_after = whole_days(new_start, other_end)
        gap_before = whole_days(other_start, new_end)
        if 0 <= gap_after < REST_DAYS_BUFFER:
            return True
        if 0 <= gap_before < REST_DAYS_BUFFER:
            return True
    return False


# --------------------------------------------------------------------------
# calculations.drought_trigger (PRD 3.8)
# --------------------------------------------------------------------------
def drought_run_length(pasture_id, new_reading):
    rows = [r for r in db.drought_readings.values() if r["pasture_id"] == pasture_id]
    rows.sort(key=lambda r: (parse_dt(r["reading_date"]), r["_seq"]), reverse=True)
    try:
        start = next(i for i, r in enumerate(rows) if r["id"] == new_reading["id"])
    except StopIteration:
        return 0
    count = 0
    for row in rows[start:]:
        if row["drought_index"] >= DROUGHT_SEVERE_INDEX:
            count += 1
        else:
            break
    return count


def apply_drought_cascade(pasture, reading):
    """Set the destock flag and cascade contracts / lots (PRD 3.8)."""
    pasture["drought_destock_flag"] = True
    touch(pasture)
    effective_date = add_days_iso(reading["reading_date"], DROUGHT_NOTICE_DAYS)
    for contract in contracts_of_pasture(pasture["id"]):
        if contract["lifecycle_status"] != "ACTIVE":
            continue
        contract["lifecycle_status"] = "EARLY_REMOVAL_PENDING"
        contract["early_removal_reason"] = "DROUGHT"
        contract["early_removal_effective_date"] = effective_date
        touch(contract)
        for lot in lots_of_contract(contract["id"]):
            if lot["status"] == "ON_FEED":
                lot["status"] = "REMOVAL_SCHEDULED"
                lot["scheduled_removal_date"] = effective_date
                touch(lot)
    recompute_pasture(pasture)
