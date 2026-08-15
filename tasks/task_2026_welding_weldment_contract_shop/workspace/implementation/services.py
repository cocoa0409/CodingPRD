"""Business logic: cascades, derived posture, continuity sweeps, shared gates."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from errors import ApiError, ERR_NOT_FOUND
from helpers import wall_timestamp, new_id

CONTINUITY_WINDOW_DAYS = 183
SMAW_EXPOSURE_LIMIT_MINUTES = 240
FROZEN_DISTORTION_THRESHOLD = 2
REPAIR_CYCLE_HARD_CAP = 2
CLOCK_INIT = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------

def stamp_new(rec):
    """Assign id, wall-clock created_at/updated_at, insertion seq."""
    rec["id"] = new_id()
    rec["created_at"] = wall_timestamp()
    rec["_created_wall"] = rec["created_at"]
    rec["_seq"] = next(db.seq)
    return rec


def make_versioned(rec):
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    return rec


def mutate(rec):
    """Refresh updated_at and bump version (PRD §2.4: every mutation)."""
    rec["updated_at"] = wall_timestamp()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Path resolution (left-to-right, ERR_NOT_FOUND at first unresolved id)
# ---------------------------------------------------------------------------

def get_shop(shop_id):
    shop = db.shops.get(shop_id)
    if shop is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Shop not found")
    return shop


def get_child(table, child_id, shop_id, what):
    rec = table.get(child_id)
    if rec is None or rec.get("shop_id") != shop_id:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what} not found")
    return rec


def get_welder(shop_id, welder_id):
    return get_child(db.welders, welder_id, shop_id, "Welder")


def get_oven(shop_id, oven_id):
    return get_child(db.ovens, oven_id, shop_id, "Oven")


def get_pqr(shop_id, pqr_id):
    return get_child(db.pqrs, pqr_id, shop_id, "PQR")


def get_wps(shop_id, wps_id):
    return get_child(db.wps, wps_id, shop_id, "WPS")


def get_qual(shop_id, qual_id):
    return get_child(db.qualifications, qual_id, shop_id, "WelderQualification")


def get_lot(shop_id, lot_id):
    return get_child(db.lots, lot_id, shop_id, "ConsumableLot")


def get_issue(shop_id, issue_id):
    return get_child(db.issues, issue_id, shop_id, "ConsumableIssue")


def get_fixture(shop_id, fixture_id):
    return get_child(db.fixtures, fixture_id, shop_id, "Fixture")


def get_order(shop_id, order_id):
    return get_child(db.orders, order_id, shop_id, "ShopOrder")


def get_weldment(shop_id, weldment_id):
    return get_child(db.weldments, weldment_id, shop_id, "Weldment")


def get_joint(shop_id, joint_id):
    return get_child(db.joints, joint_id, shop_id, "Joint")


def get_report(shop_id, report_id):
    return get_child(db.distortion_reports, report_id, shop_id, "DistortionReport")


def get_inspection(shop_id, inspection_id):
    return get_child(db.inspections, inspection_id, shop_id, "Inspection")


def get_signoff(shop_id, signoff_id):
    return get_child(db.sign_offs, signoff_id, shop_id, "TravelerSignOff")


# ---------------------------------------------------------------------------
# Welder qualification continuity
# ---------------------------------------------------------------------------

def compute_continuity_expiry(qualified_at, last_weld_at):
    baseline = max(qualified_at, last_weld_at)
    return baseline + timedelta(days=CONTINUITY_WINDOW_DAYS)


def recompute_welder_status(welder):
    """ACTIVE if any QUALIFIED qualification remains, else SUSPENDED.
    TERMINATED is never system-assigned and never system-cleared."""
    if welder["status"] == "TERMINATED":
        return
    has_qualified = any(
        q["welder_id"] == welder["id"] and q["status"] == "QUALIFIED"
        for q in db.qualifications.values()
    )
    new_status = "ACTIVE" if has_qualified else "SUSPENDED"
    if new_status != welder["status"]:
        welder["status"] = new_status
        mutate(welder)


def lapse_if_expired(qual, current_utc):
    """Lapse boundary is inclusive: lapsed AT the expiry instant (>=)."""
    if qual["status"] != "QUALIFIED":
        return False
    if current_utc >= qual["continuity_expires_at_utc"]:
        qual["status"] = "LAPSED"
        mutate(qual)
        welder = db.welders.get(qual["welder_id"])
        if welder is not None:
            recompute_welder_status(welder)
        return True
    return False


def continuity_sweep(shop):
    for qual in list(db.qualifications.values()):
        if qual["shop_id"] == shop["id"]:
            lapse_if_expired(qual, shop["current_utc"])


# ---------------------------------------------------------------------------
# Weldment derived posture
# ---------------------------------------------------------------------------

def joints_of_weldment(weldment_id):
    return [j for j in db.joints.values() if j["weldment_id"] == weldment_id]


def reports_of_weldment(weldment_id):
    return [r for r in db.distortion_reports.values() if r["weldment_id"] == weldment_id]


def derive_posture_open_restricted(wm, touch=True):
    """OPEN <-> RESTRICTED derivation (ON_HOLD joints or PENDING reports).
    Latched postures (REPAIR_REVIEW, FROZEN) and terminals are untouched.
    Callers that already mutate the weldment in the same request pass
    touch=False and bump the version once themselves."""
    if wm["posture"] not in ("OPEN", "RESTRICTED"):
        return False
    has_hold = any(
        j["fabrication_status"] == "ON_HOLD" for j in joints_of_weldment(wm["id"])
    )
    has_pending = any(
        r["disposition"] == "PENDING" for r in reports_of_weldment(wm["id"])
    )
    new_posture = "RESTRICTED" if (has_hold or has_pending) else "OPEN"
    if new_posture != wm["posture"]:
        wm["posture"] = new_posture
        if touch:
            mutate(wm)
        return True
    return False


def void_inflight_inspections(weldment_id):
    """Freezing / cancellation discards scheduled-but-unresulted inspections."""
    joint_ids = {j["id"] for j in joints_of_weldment(weldment_id)}
    doomed = [
        iid
        for iid, ins in db.inspections.items()
        if ins["joint_id"] in joint_ids and ins["result"] is None
    ]
    for iid in doomed:
        del db.inspections[iid]


def check_frozen_gate(wm):
    """FROZEN derives only on an OPEN weldment: some joint NDT_FAILED and
    distortion_count >= 2 (boundary inclusive). Voids in-flight inspections."""
    if wm["posture"] != "OPEN":
        return False
    has_failed = any(
        j["inspection_status"] == "NDT_FAILED" for j in joints_of_weldment(wm["id"])
    )
    if has_failed and wm["distortion_count"] >= FROZEN_DISTORTION_THRESHOLD:
        wm["posture"] = "FROZEN"
        void_inflight_inspections(wm["id"])
        return True
    return False


def check_repair_review_gate(wm, shop):
    """REPAIR_REVIEW derives only on an OPEN weldment: rate >= limit (>= boundary)."""
    if wm["posture"] != "OPEN":
        return False
    if wm["repair_rate_pct"] >= Decimal(str(shop["repair_rate_limit_pct"])):
        wm["posture"] = "REPAIR_REVIEW"
        return True
    return False


def recompute_repair_rate(wm):
    total = wm["total_pass_count"]
    if total == 0:
        wm["repair_rate_pct"] = Decimal("0")
    else:
        rate = (Decimal("100") * Decimal(wm["repair_pass_count"])) / Decimal(total)
        wm["repair_rate_pct"] = rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_fixture_on_terminal(wm):
    """When the last non-terminal weldment on a fixture reaches SHIPPED/CANCELLED,
    an IN_USE fixture returns to AVAILABLE."""
    fixture = db.fixtures.get(wm["fixture_id"])
    if fixture is None or fixture["status"] != "IN_USE":
        return
    remaining = any(
        w["fixture_id"] == fixture["id"] and w["posture"] not in ("SHIPPED", "CANCELLED")
        for w in db.weldments.values()
    )
    if not remaining:
        fixture["status"] = "AVAILABLE"
        mutate(fixture)


def cascade_order_on_ship(wm):
    """When every weldment on the parent order is SHIPPED: IN_PROGRESS -> COMPLETE."""
    order = db.orders.get(wm["shop_order_id"])
    if order is None or order["status"] != "IN_PROGRESS":
        return
    weldments = [w for w in db.weldments.values() if w["shop_order_id"] == order["id"]]
    if weldments and all(w["posture"] == "SHIPPED" for w in weldments):
        order["status"] = "COMPLETE"
        mutate(order)


def cancel_weldment_cascade(wm):
    """Shared by weldment cancel and distortion SCRAP: cancel non-terminal
    joints, void in-flight inspections, run the fixture cascade."""
    wm["posture"] = "CANCELLED"
    mutate(wm)
    for joint in joints_of_weldment(wm["id"]):
        if joint["fabrication_status"] != "CANCELLED":
            joint["fabrication_status"] = "CANCELLED"
            mutate(joint)
    void_inflight_inspections(wm["id"])
    cascade_fixture_on_terminal(wm)


def wps_supersession_cascade(shop, new_wps):
    """Prior APPROVED revisions of the same (shop, wps_number) -> SUPERSEDED;
    their PENDING joints -> ON_HOLD; their QUALIFIED quals lapse-re-evaluated."""
    superseded = [
        w
        for w in db.wps.values()
        if w["shop_id"] == shop["id"]
        and w["wps_number"] == new_wps["wps_number"]
        and w["revision"] < new_wps["revision"]
        and w["status"] == "APPROVED"
        and w["id"] != new_wps["id"]
    ]
    for old in superseded:
        old["status"] = "SUPERSEDED"
        old["superseded_by_id"] = new_wps["id"]
        mutate(old)
        affected_weldments = set()
        for joint in db.joints.values():
            if (
                joint["wps_id"] == old["id"]
                and joint["fabrication_status"] == "PENDING"
            ):
                joint["fabrication_status"] = "ON_HOLD"
                mutate(joint)
                affected_weldments.add(joint["weldment_id"])
        for wm_id in affected_weldments:
            wm = db.weldments.get(wm_id)
            if wm is not None:
                derive_posture_open_restricted(wm)
        for qual in db.qualifications.values():
            if qual["wps_id"] == old["id"] and qual["status"] == "QUALIFIED":
                lapse_if_expired(qual, shop["current_utc"])


def oven_offline_cascade(oven):
    """Lots in this oven that are ISSUED with an OPEN issue -> QUARANTINED;
    those open issues -> VOID."""
    for lot in db.lots.values():
        if lot["oven_id"] != oven["id"] or lot["status"] != "ISSUED":
            continue
        open_issues = [
            i
            for i in db.issues.values()
            if i["lot_id"] == lot["id"] and i["status"] == "OPEN"
        ]
        if not open_issues:
            continue
        for issue in open_issues:
            issue["status"] = "VOID"
        lot["status"] = "QUARANTINED"
        mutate(lot)


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------

def effective_required_methods(joint):
    """VT is always implicitly required whether listed or not."""
    return set(joint["required_ndt_methods"]) | {"VT"}


def joint_welder_ids(joint_id):
    return {
        p["welder_id"] for p in db.weld_passes.values() if p["joint_id"] == joint_id
    }


def apply_inspection_pass(joint, inspection):
    """PASS: joint -> NDT_PASSED once every required method has a passing row;
    the completing inspection releases the hold point."""
    required = effective_required_methods(joint)
    passing_methods = set()
    for ins in db.inspections.values():
        if ins["joint_id"] == joint["id"] and ins["result"] == "PASS":
            passing_methods.add(ins["method"])
    passing_methods.add(inspection["method"])
    if required <= passing_methods:
        joint["inspection_status"] = "NDT_PASSED"
        inspection["hold_point_released"] = True
    elif inspection["method"] == "VT":
        joint["inspection_status"] = "VT_PASSED"
    # else: UT/RT pass with other methods outstanding -> stays NDT_IN_PROGRESS
