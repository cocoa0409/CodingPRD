"""Farm premium payments (PRD section 3.3, calculation farm_premium_payment).

tier_pct(B): 0 if B < 60; 5 if 60 <= B < 75; 8 if 75 <= B < 90; 12 if B >= 90
(lower bounds inclusive). eff_pct = max(0, tier - 2*non_conformance_count).
Below the program bar (tier 0): gross is 0, no premium and no excess bonus.
Otherwise base volume = min(V, baseline), excess = max(0, V - baseline), and
gross = round_half_up(base*P*eff/100 + excess*P*(eff+1)/100) — the excess
earns a marginal +1 percentage point bonus. PROVISIONAL uses declared volume
with zero deductions; FINAL uses metered volume and actual deductions.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from auth import authenticate, authorize
from db import STORE, new_resource, public, sorted_items, touch
from envelope import ok, ok_list, pagination_args
from errors import fail
from farms import get_enrollment
from validate import PAYMENT_PERIODS, get_body, req_enum, req_int

bp = Blueprint("payments", __name__)

TIER1_MIN, TIER1_PCT = 60, 5
TIER2_MIN, TIER2_PCT = 75, 8
TIER3_MIN, TIER3_PCT = 90, 12
NON_CONFORMANCE_DEDUCTION_PCT = 2
EXCESS_VOLUME_BONUS_PCT = 1

DPM_POC = ("DairyProgramManager", "ParentOpsController")


def get_payment(pid):
    p = STORE["payments"].get(pid)
    if p is None:
        fail("ERR_PAYMENT_NOT_FOUND", "PremiumPayment id does not exist")
    return p


def tier_pct(blended):
    if blended < TIER1_MIN:
        return 0
    if blended < TIER2_MIN:
        return TIER1_PCT
    if blended < TIER3_MIN:
        return TIER2_PCT
    return TIER3_PCT


def compute_premium(blended, baseline, volume, price, non_conformance):
    """Return (premium_pct, gross_amount_cents) for the given variant inputs."""
    tier = tier_pct(blended)
    eff = max(0, tier - NON_CONFORMANCE_DEDUCTION_PCT * non_conformance)
    if tier == 0:
        return eff, 0
    base = min(volume, baseline)
    excess = max(0, volume - baseline)
    raw = (Decimal(base) * price * eff / Decimal(100)
           + Decimal(excess) * price * (eff + EXCESS_VOLUME_BONUS_PCT)
           / Decimal(100))
    gross = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return eff, gross


@bp.post("/enrollments/<eid>/premium-payments")
def create_payment(eid):
    _, role = authenticate()
    authorize(role, ("DairyProgramManager",))
    enrollment = get_enrollment(eid)
    body = get_body()
    period = req_enum(body, "period", PAYMENT_PERIODS)
    declared = req_int(body, "declared_volume_liters", 0)
    price = req_int(body, "commodity_price_cents_per_liter", 0)
    if enrollment["status"] != "ASSESSED":
        fail("ERR_INVALID_STATE",
             "Premium payments require an ASSESSED enrollment")
    premium_pct, gross = compute_premium(
        enrollment["blended_score"], enrollment["baseline_volume_liters"],
        declared, price, 0)
    r = new_resource()
    r.update({
        "enrollment_id": eid,
        "period": period,
        "declared_volume_liters": declared,
        "metered_volume_liters": None,
        "non_conformance_count": 0,
        "commodity_price_cents_per_liter": price,
        "calc_variant": "PROVISIONAL",
        "premium_pct": premium_pct,
        "gross_amount_cents": gross,
        "status": "CALCULATED",
    })
    STORE["payments"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/enrollments/<eid>/premium-payments")
def list_payments(eid):
    _, role = authenticate()
    authorize(role, DPM_POC)
    get_enrollment(eid)
    items = [public(p) for p in sorted_items(
        p for p in STORE["payments"].values() if p["enrollment_id"] == eid)]
    limit, offset = pagination_args()
    return ok_list(items, limit, offset)


@bp.get("/premium-payments/<pid>")
def read_payment(pid):
    _, role = authenticate()
    authorize(role, DPM_POC)
    return ok(public(get_payment(pid)))


@bp.post("/premium-payments/<pid>/finalize")
def finalize_payment(pid):
    _, role = authenticate()
    authorize(role, ("DairyProgramManager",))
    p = get_payment(pid)
    body = get_body()
    metered = req_int(body, "metered_volume_liters", 0)
    non_conformance = req_int(body, "non_conformance_count", 0)
    if p["status"] != "CALCULATED" or p["calc_variant"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE",
             "Only a PROVISIONAL payment can be finalized")
    enrollment = get_enrollment(p["enrollment_id"])
    p["metered_volume_liters"] = metered
    p["non_conformance_count"] = non_conformance
    p["calc_variant"] = "FINAL"
    p["premium_pct"], p["gross_amount_cents"] = compute_premium(
        enrollment["blended_score"], enrollment["baseline_volume_liters"],
        metered, p["commodity_price_cents_per_liter"], non_conformance)
    touch(p)
    return ok(public(p))


@bp.post("/premium-payments/<pid>/approve")
def approve_payment(pid):
    _, role = authenticate()
    authorize(role, ("DairyProgramManager",))
    p = get_payment(pid)
    if p["status"] != "CALCULATED":
        fail("ERR_INVALID_STATE",
             "Only a CALCULATED payment can be approved")
    if p["calc_variant"] != "FINAL":
        fail("ERR_PAYMENT_NOT_FINAL",
             "Approve requires calc_variant == FINAL")
    enrollment = get_enrollment(p["enrollment_id"])
    p["status"] = "APPROVED"
    touch(p)
    enrollment["total_approved_cents"] += p["gross_amount_cents"]
    touch(enrollment)
    return ok(public(p))


@bp.post("/premium-payments/<pid>/pay")
def pay_payment(pid):
    _, role = authenticate()
    authorize(role, ("ParentOpsController",))
    p = get_payment(pid)
    if p["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED payment can be paid")
    p["status"] = "PAID"
    touch(p)
    return ok(public(p))


@bp.post("/premium-payments/<pid>/void")
def void_payment(pid):
    _, role = authenticate()
    authorize(role, ("DairyProgramManager",))
    p = get_payment(pid)
    if p["status"] not in ("CALCULATED", "APPROVED"):
        fail("ERR_INVALID_STATE",
             "Only a CALCULATED or APPROVED payment can be voided")
    if p["status"] == "APPROVED":
        # Compensating reversal of the enrollment's approved total.
        enrollment = get_enrollment(p["enrollment_id"])
        enrollment["total_approved_cents"] -= p["gross_amount_cents"]
        touch(enrollment)
    p["status"] = "VOIDED"
    touch(p)
    return ok(public(p))
