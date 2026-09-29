"""Derived counters, ledgers and the two explicit cascades (PRD 2.9, 3.6-3.9)."""

from datetime import date

from db import by_creation, db, fmt_date, make_record, now_iso, today, touch
from services import calc

CONFIG_KEYS = (
    "seat_capacity",
    "emergency_exit_count",
    "mirror_config",
    "lap_shoulder_belts",
    "eight_lamp_system",
    "crossing_arm",
    "rollover_reinforcement",
)


def to_date(value):
    """Parse a stored ISO date or the date part of a stored ISO instant."""
    text = value[0:10]
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def config_from(record, prefix=""):
    return dict((key, record[prefix + key]) for key in CONFIG_KEYS)


def offered_config(bid):
    return dict((key, bid["offered_" + key if key != "rollover_reinforcement" else "offered_rollover_reinforcement"])
                for key in CONFIG_KEYS)


# ------------------------------------------------------------------- selectors

def units_of_order(order_id):
    return [u for u in db.units.values() if u.get("contract_order_id") == order_id]


def tests_of_unit(unit_id):
    return [t for t in db.tests.values() if t["bus_unit_id"] == unit_id]


def slots_of_unit(unit_id):
    return [s for s in db.slots.values() if s["bus_unit_id"] == unit_id]


def slots_of_line(line_id):
    return [s for s in db.slots.values() if s["production_line_id"] == line_id]


def tasks_of_campaign(campaign_id):
    return [t for t in db.tasks.values() if t["recall_campaign_id"] == campaign_id]


def tasks_of_unit(unit_id):
    return [t for t in db.tasks.values() if t["bus_unit_id"] == unit_id]


def tasks_of_dealer(dealer_id):
    return [t for t in db.tasks.values() if t["dealer_id"] == dealer_id]


def revisions_of_bid(bid_id):
    return [r for r in db.revisions.values() if r["bid_id"] == bid_id]


def published_profile(state_code, school_year):
    for profile in by_creation(list(db.profiles.values())):
        if (
            profile["status"] == "PUBLISHED"
            and profile["state_code"] == state_code
            and profile["school_year"] == school_year
        ):
            return profile
    return None


def live_slot_of_unit(unit_id):
    """The unit's slot that is COMMITTED or IN_PROGRESS, if any."""
    for slot in by_creation(slots_of_unit(unit_id)):
        if slot["status"] in ("COMMITTED", "IN_PROGRESS"):
            return slot
    return None


# ---------------------------------------------------------- contract order math

def recompute_order(order):
    """at_risk_unit_count, delivery_posture, damages, counters and FULFILLED."""
    if order is None:
        return
    units = units_of_order(order["id"])
    unit_count = int(order["unit_count"])
    created = len(units)
    delivered = len([u for u in units if u["production_status"] == "DELIVERED"])
    planned = len([u for u in units if u["production_status"] == "PLANNED"])
    at_risk = (unit_count - created) + planned

    order["created_unit_count"] = created
    order["delivered_unit_count"] = delivered
    order["at_risk_unit_count"] = at_risk

    clock_date = today()
    promised = to_date(order["promised_delivery_date"])
    if order["delivery_posture"] == "BREACHED":
        posture = "BREACHED"
    elif clock_date > promised and delivered < unit_count:
        posture = "BREACHED"
    elif at_risk >= 1 and (promised - clock_date).days < calc.REPLAN_LEAD_DAYS:
        posture = "AT_RISK"
    else:
        posture = "ON_TRACK"
    order["delivery_posture"] = posture

    if posture == "BREACHED":
        days_late = (clock_date - promised).days
        if days_late < 0:
            days_late = 0
        order["liquidated_damages_cents"] = calc.liquidated_damages_cents(
            at_risk, days_late, order["total_contract_cents"]
        )
    else:
        order["liquidated_damages_cents"] = 0

    if order["status"] == "ACTIVE" and created == unit_count and delivered == unit_count:
        order["status"] = "FULFILLED"

    touch(order)


def order_of_unit(unit):
    order_id = unit.get("contract_order_id")
    if not order_id:
        return None
    return db.orders.get(order_id)


# ------------------------------------------------------------------ line ledger

def recompute_line_ledger(line):
    total = 0
    for slot in slots_of_line(line["id"]):
        if slot["status"] in ("COMMITTED", "IN_PROGRESS", "COMPLETED"):
            total += int(slot["slot_days"])
    line["committed_slot_days"] = total


# ---------------------------------------------------------------- campaign kits

def recompute_campaign(campaign, mark=True):
    tasks = tasks_of_campaign(campaign["id"])
    reserved = sum(int(t["kits_reserved"]) for t in tasks if t["status"] in ("OPEN", "IN_PROGRESS"))
    consumed = sum(int(t["kits_reserved"]) for t in tasks if t["status"] == "COMPLETED")
    campaign["reserved_kits"] = reserved
    campaign["consumed_kits"] = consumed
    campaign["available_kits"] = int(campaign["total_kits"]) - reserved - consumed
    campaign["escalated_task_count"] = len(
        [t for t in tasks if t["escalation_level"] == "FACTORY_DIRECTED"]
    )
    if mark:
        touch(campaign)


def close_campaign_if_complete(campaign):
    tasks = tasks_of_campaign(campaign["id"])
    if campaign["status"] != "LAUNCHED" or not tasks:
        return
    if all(t["status"] in ("COMPLETED", "CANCELLED") for t in tasks):
        campaign["status"] = "COMPLETED"
        recompute_campaign(campaign)


# ------------------------------------------------------- dealer exposure (hop 2)

def recompute_dealer(dealer, allow_escalation=True):
    if dealer is None:
        return
    delivered = len(
        [u for u in db.units.values()
         if u.get("dealer_id") == dealer["id"] and u["production_status"] == "DELIVERED"]
    )
    open_units = set()
    for task in tasks_of_dealer(dealer["id"]):
        if task["status"] in ("OPEN", "IN_PROGRESS"):
            open_units.add(task["bus_unit_id"])
    previous = dealer["certification_standing"]
    standing = calc.dealer_standing(len(open_units))
    dealer["delivered_unit_count"] = delivered
    dealer["open_recall_unit_count"] = len(open_units)
    dealer["certification_standing"] = standing
    touch(dealer)
    if (
        allow_escalation
        and calc.STANDING_RANK[standing] > calc.STANDING_RANK[previous]
        and standing != "GOOD"
    ):
        escalate_dealer_tasks(dealer)


def escalate_dealer_tasks(dealer):
    """CASCADE-B hops 3 and 4."""
    candidates = [
        t for t in tasks_of_dealer(dealer["id"])
        if t["status"] in ("OPEN", "IN_PROGRESS") and t["escalation_level"] == "DEALER_DIRECTED"
    ]
    for task in by_creation(candidates):
        task["escalation_level"] = "FACTORY_DIRECTED"
        touch(task)
        campaign = db.campaigns.get(task["recall_campaign_id"])
        if campaign is None:
            continue
        recompute_campaign(campaign)
        if int(campaign["available_kits"]) >= 1:
            task["kits_reserved"] = int(task["kits_reserved"]) + calc.FACTORY_ESCALATION_EXTRA_KITS
        else:
            campaign["kit_shortfall_count"] = int(campaign["kit_shortfall_count"]) + 1
        recompute_campaign(campaign)


# --------------------------------------------------------------- test/slot hops

def void_scheduled_tests(unit_id, skip_test_id=None):
    for test in by_creation(tests_of_unit(unit_id)):
        if test["status"] == "SCHEDULED" and test["id"] != skip_test_id:
            test["status"] = "VOIDED"
            touch(test)


def release_slot(slot, skip_test_id=None):
    """Release transition shared by the operator release and CASCADE-A hop 2/3."""
    previous = slot["status"]
    slot["status"] = "RELEASED"
    touch(slot)

    line = db.lines.get(slot["production_line_id"])
    if line is not None:
        if previous in ("COMMITTED", "IN_PROGRESS"):
            recompute_line_ledger(line)
        touch(line)

    unit = db.units.get(slot["bus_unit_id"])
    if unit is not None:
        if previous in ("COMMITTED", "IN_PROGRESS") and unit["production_status"] in (
            "SLOTTED",
            "BODY_JOINED",
            "BUILT",
        ):
            unit["production_status"] = "PLANNED"
            touch(unit)
        void_scheduled_tests(unit["id"], skip_test_id=skip_test_id)
        recompute_order(order_of_unit(unit))


def fail_cascade(test, unit):
    """CASCADE-A hops 1-4."""
    if unit["certification_status"] == "PENDING":
        unit["certification_status"] = "NONCONFORMING"
        touch(unit)
    slot = live_slot_of_unit(unit["id"])
    if slot is None:
        return
    release_slot(slot, skip_test_id=test["id"])


def refresh_unit_service_status(unit):
    """After a remedy task closes: RECALL_CLOSED, or back to NONE."""
    tasks = tasks_of_unit(unit["id"])
    if any(t["status"] in ("OPEN", "IN_PROGRESS") for t in tasks):
        return
    if any(t["status"] == "COMPLETED" for t in tasks):
        target = "RECALL_CLOSED"
    else:
        target = "NONE"
    if unit["service_status"] != target:
        unit["service_status"] = target
        touch(unit)


# ------------------------------------------------------------------- bus units

def build_unit(fields):
    unit = make_record(fields)
    db.units[unit["id"]] = unit
    return unit


def vin_exists(vin):
    return any(u["vin"] == vin for u in db.units.values())


def code_exists(collection, field, value):
    return any(rec[field] == value for rec in collection.values())


def unit_range(unit_package, profile):
    return calc.range_validation(unit_package, profile)


def unit_config_fields(cfg):
    return dict(cfg)


def new_revision(bid, cfg, note, round_index, unit_price):
    revision = make_record(
        {
            "bid_id": bid["id"],
            "round_index": round_index,
            "offered_seat_capacity": cfg["seat_capacity"],
            "offered_emergency_exit_count": cfg["emergency_exit_count"],
            "offered_mirror_config": cfg["mirror_config"],
            "offered_lap_shoulder_belts": cfg["lap_shoulder_belts"],
            "offered_eight_lamp_system": cfg["eight_lamp_system"],
            "offered_crossing_arm": cfg["crossing_arm"],
            "offered_rollover_reinforcement": cfg["rollover_reinforcement"],
            "unit_price_cents": unit_price,
            "is_superseded": False,
            "note": note,
        },
        versioned=False,
    )
    db.revisions[revision["id"]] = revision
    return revision


def apply_offered_config(bid, cfg):
    bid["offered_seat_capacity"] = cfg["seat_capacity"]
    bid["offered_emergency_exit_count"] = cfg["emergency_exit_count"]
    bid["offered_mirror_config"] = cfg["mirror_config"]
    bid["offered_lap_shoulder_belts"] = cfg["lap_shoulder_belts"]
    bid["offered_eight_lamp_system"] = cfg["eight_lamp_system"]
    bid["offered_crossing_arm"] = cfg["crossing_arm"]
    bid["offered_rollover_reinforcement"] = cfg["rollover_reinforcement"]


def bid_offered_config(bid):
    return {
        "seat_capacity": bid["offered_seat_capacity"],
        "emergency_exit_count": bid["offered_emergency_exit_count"],
        "mirror_config": bid["offered_mirror_config"],
        "lap_shoulder_belts": bid["offered_lap_shoulder_belts"],
        "eight_lamp_system": bid["offered_eight_lamp_system"],
        "crossing_arm": bid["offered_crossing_arm"],
        "rollover_reinforcement": bid["offered_rollover_reinforcement"],
    }


def order_awarded_config(order):
    return {
        "seat_capacity": order["awarded_seat_capacity"],
        "emergency_exit_count": order["awarded_emergency_exit_count"],
        "mirror_config": order["awarded_mirror_config"],
        "lap_shoulder_belts": order["awarded_lap_shoulder_belts"],
        "eight_lamp_system": order["awarded_eight_lamp_system"],
        "crossing_arm": order["awarded_crossing_arm"],
        "rollover_reinforcement": order["awarded_rollover_reinforcement"],
    }
