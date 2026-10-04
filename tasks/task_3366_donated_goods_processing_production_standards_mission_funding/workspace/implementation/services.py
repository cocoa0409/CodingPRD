"""Domain services: entity factory, org resolution, and all calculations."""
import math
import uuid
from decimal import Decimal, ROUND_HALF_UP

from clock import iso, now
from db import next_seq, store

# ---------------------------------------------------------------------------
# Constants (PRD section 3)
# ---------------------------------------------------------------------------
CONDITION_MULTIPLIER = {
    "A": Decimal("1.0"),
    "B": Decimal("0.75"),
    "C": Decimal("0.5"),
    "UNSALABLE": Decimal("0"),
}
ROTATION_WEEKS = 4
MARKDOWN_PCT = [0, 25, 50, 75]

TEXTILE_RATE = 12
MIN_BALE_LBS = 50
EWASTE_FEE = 150
OUTLET_T1_LBS = 100
OUTLET_R1 = 45
OUTLET_R2 = 30

DISPOSAL_RATES = {"MIXED_UNSALABLE": 9, "HAZARD": 40, "FURNITURE": 15}

CHANNEL_CATEGORIES = {
    "TEXTILE_BALE": {"TEXTILES"},
    "EWASTE": {"EWASTE"},
    "OUTLET_BIN": {"TEXTILES", "HOUSEWARES", "MEDIA"},
}

CATEGORIES = {"TEXTILES", "HOUSEWARES", "MEDIA", "FURNITURE", "EWASTE"}
GRADES = {"A", "B", "C", "UNSALABLE"}


def D(x):
    """Exact decimal from an int/float input."""
    return Decimal(str(x))


def rhu(d):
    """Round half-up (ties away from zero) to an integer."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(d):
    """Round half-up to 2 decimal places (returns Decimal)."""
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Entity factory / mutation
# ---------------------------------------------------------------------------

def new_entity():
    """Common fields: id, created_at, updated_at, version (starts at 0)."""
    ts = iso(now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 0,
        "_seq": next_seq(),
    }


def new_light_entity():
    """Territory / DonationSite / DisposalTicket: id + created_at only."""
    return {"id": str(uuid.uuid4()), "created_at": iso(now()), "_seq": next_seq()}


def touch(e):
    """Refresh updated_at and bump version on a common-fields entity."""
    e["updated_at"] = iso(now())
    e["version"] += 1


# ---------------------------------------------------------------------------
# Org resolution (flat topology, joined by foreign keys)
# ---------------------------------------------------------------------------

def org_of_site(site):
    return store.member_orgs.get(site["member_org_id"])


def org_of_donation(donation):
    site = store.donation_sites.get(donation["site_id"])
    return store.member_orgs.get(site["member_org_id"]) if site else None


def org_of_item(item):
    donation = store.donations.get(item["donation_id"])
    return org_of_donation(donation) if donation else None


def org_of_run(run):
    site = store.donation_sites.get(run["site_id"])
    return org_of_site(site) if site else None


def org_of_program(program):
    return store.member_orgs.get(program["member_org_id"])


def org_of_allocation(alloc):
    program = store.mission_programs.get(alloc["mission_program_id"])
    return org_of_program(program) if program else None


def org_of_contract(contract):
    return store.member_orgs.get(contract["member_org_id"])


def org_of_milestone(milestone):
    contract = store.workforce_contracts.get(milestone["contract_id"])
    return org_of_contract(contract) if contract else None


# ---------------------------------------------------------------------------
# Computed ledgers
# ---------------------------------------------------------------------------

def recompute_margin_health(org):
    org["margin_health"] = (
        "HEALTHY"
        if org["retail_margin_pool_cents"] >= org["reserve_floor_cents"]
        else "LOW"
    )


def recompute_diversion(org):
    dv = org["total_diverted_lbs"]
    dp = org["total_disposed_lbs"]
    if dv + dp == 0:
        rate = 10000
    else:
        rate = math.floor((dv * 10000) / (dv + dp))
    org["diversion_rate_bps"] = rate
    org["diversion_compliant"] = rate >= org["diversion_floor_bps"]


def recompute_posture(contract):
    ms = [m for m in store.milestones.values() if m["contract_id"] == contract["id"]]
    total = len(ms)
    missed = sum(1 for m in ms if m["status"] == "MISSED")
    contract["missed_count"] = missed
    if missed == 0:
        contract["compliance_posture"] = "COMPLIANT"
    elif missed * 4 > total:
        contract["compliance_posture"] = "BREACH"
    else:
        contract["compliance_posture"] = "AT_RISK"


def maybe_auto_close_contract(contract):
    """CLOSED once every milestone is terminal (ATTESTED or MISSED)."""
    if contract["status"] == "CLOSED":
        return
    ms = [m for m in store.milestones.values() if m["contract_id"] == contract["id"]]
    if all(m["status"] in ("ATTESTED", "MISSED") for m in ms):
        contract["status"] = "CLOSED"


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def active_standard_for(org_id, category):
    for s in store.production_standards.values():
        if (
            s["member_org_id"] == org_id
            and s["category"] == category
            and s["status"] == "ACTIVE"
        ):
            return s
    return None


def receipt_fmv(items):
    """Round EACH item's value first, then sum (pinned order, mode b)."""
    total = 0
    for _cat, grade, ev, _wt in items:
        total += rhu(D(ev) * CONDITION_MULTIPLIER[grade])
    return total


def unit_cost(org, category, standard):
    """STANDARD vs ACTUAL variant; ACTUAL falls back when no CLOSED runs."""
    if org["costing_method"] == "ACTUAL":
        runs = [
            r
            for r in store.processing_runs.values()
            if r["status"] == "CLOSED"
            and org_of_run(r)["id"] == org["id"]
            and r["category"] == category
        ]
        labor = sum(r["labor_cost_cents"] for r in runs)
        processed = sum(r["item_count_processed"] for r in runs)
        if runs and processed:
            return rhu(D(labor) / D(processed))
    return rhu(D(standard["hourly_cost_cents"]) / D(standard["target_items_per_hour"]))


def salvage_revenue(lot):
    w = lot["total_weight_lbs"]
    if lot["channel"] == "TEXTILE_BALE":
        return rhu(D(w) * TEXTILE_RATE)
    if lot["channel"] == "EWASTE":
        return lot["item_count"] * EWASTE_FEE
    # OUTLET_BIN: first 100 lbs at 45, the rest at 30.
    return rhu(
        min(w, D(OUTLET_T1_LBS)) * OUTLET_R1
        + max(Decimal("0"), w - D(OUTLET_T1_LBS)) * OUTLET_R2
    )


def disposal_cost(material, weight_lbs):
    return rhu(D(weight_lbs) * DISPOSAL_RATES[material])
