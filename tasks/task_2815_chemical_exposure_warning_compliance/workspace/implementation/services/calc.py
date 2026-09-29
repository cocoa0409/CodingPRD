"""Concentration roll-up, exposure, verdicts, loads and the posture ladder."""
from decimal import Decimal

from errors import fail
from util import D, rhu
import db

MODELED_DEFAULT_PPM = D("250.0")
DISCLOSURE_GAP = ("NOT_REQUESTED", "REQUESTED", "INCOMPLETE", "REFUSED")
ROUTE_ABSORPTION = {"ORAL": D("1.00"), "DERMAL": D("0.10"), "INHALATION": D("0.25")}
CONCENTRATION_DP = 4
EXPOSURE_DP = 3
LOAD_DP = 3
MARGIN_DP = 4
QUALIFYING_RESULTS = ("AT_OR_ABOVE_SAFE_HARBOR", "NO_SAFE_HARBOR")
OPEN_NOTICE_STATUSES = (
    "RECEIVED", "UNDER_EVALUATION", "CURE_ELECTED", "CURE_FAILED",
    "SETTLEMENT_NEGOTIATION", "LITIGATION",
)
RECOMPUTABLE_ASSESSMENT_STATUSES = ("DRAFT", "SUBMITTED", "PEER_REVIEWED")


# --------------------------------------------------------------------------
# graph helpers
# --------------------------------------------------------------------------
def link_for(material_id, chemical_id):
    for link in db.rows("material_chemicals"):
        if link["material_id"] == material_id and link["chemical_id"] == chemical_id:
            return link
    return None


def children_of(material_id):
    return [m for m in db.rows("materials") if m.get("parent_material_id") == material_id]


def subtree(material):
    """The material and every material below it, breadth-first."""
    out = [material]
    queue = [material]
    while queue:
        current = queue.pop(0)
        for child in children_of(current["id"]):
            if child["id"] not in [m["id"] for m in out]:
                out.append(child)
                queue.append(child)
    return out


def ancestor_ids(material):
    """The material's own id plus every ancestor id up the parent chain."""
    out = [material["id"]]
    current = material
    guard = 0
    while current.get("parent_material_id") and guard < 16:
        parent = db.get("materials", current["parent_material_id"])
        if parent is None or parent["id"] in out:
            break
        out.append(parent["id"])
        current = parent
        guard += 1
    return out


def descendants(material):
    return [m for m in subtree(material) if m["id"] != material["id"]]


def active_components(product_id):
    return [c for c in db.rows("product_components")
            if c["product_id"] == product_id and c["status"] == "ACTIVE"]


def components_of(product_id):
    return [c for c in db.rows("product_components") if c["product_id"] == product_id]


def products_reaching(material):
    """Products holding this material directly or through the material tree."""
    reach = set(ancestor_ids(material))
    out = []
    for component in db.rows("product_components"):
        if component["status"] != "ACTIVE" or component["material_id"] not in reach:
            continue
        product = db.get("products", component["product_id"])
        if product is not None and product not in out:
            out.append(product)
    return out


def assessments_of(product_id, chemical_id=None):
    out = []
    for row in db.rows("exposure_assessments"):
        if row["product_id"] != product_id:
            continue
        if chemical_id is not None and row["chemical_id"] != chemical_id:
            continue
        out.append(row)
    return out


def determinations_of(product_id):
    return [d for d in db.rows("warning_determinations") if d["product_id"] == product_id]


def placements_of(determination_id):
    return [p for p in db.rows("warning_placements")
            if p["determination_id"] == determination_id]


def notices_of(product_id):
    return [n for n in db.rows("notices") if n["product_id"] == product_id]


def settlements_of(notice_id):
    return [s for s in db.rows("settlements") if s["notice_id"] == notice_id]


# --------------------------------------------------------------------------
# effective concentration (PRD 3.5)
# --------------------------------------------------------------------------
def own_concentration(material, chemical_id, variant, strict=False):
    link = link_for(material["id"], chemical_id)
    if variant == "MODELED":
        if material.get("disclosure_status") in DISCLOSURE_GAP:
            return MODELED_DEFAULT_PPM
        if link is None:
            return D("0.0")
        if link.get("measurement_basis") == "LAB_TESTED":
            result = link.get("lab_result_ppm")
            loq = link.get("lab_loq_ppm")
            if result is None or loq is None:
                return D(link.get("declared_concentration_ppm") or 0)
            if D(result) < D(loq):
                return D(loq) / D(2)
            return D(result)
        return D(link.get("declared_concentration_ppm") or 0)
    # laboratory variant: disclosure_status is ignored entirely
    if link is None:
        return D("0.0")
    result = link.get("lab_result_ppm")
    loq = link.get("lab_loq_ppm")
    if link.get("measurement_basis") != "LAB_TESTED" or result is None or loq is None:
        if strict:
            fail("ERR_LAB_RESULT_MISSING",
                 "a contributing link carries no admissible laboratory figure")
        return D("0.0")
    if D(result) < D(loq):
        return D("0.0")
    return D(result)


def effective_concentration(material, chemical_id, variant, strict=False):
    """Depth-first post-order roll-up; rounded once per tree level to 4 dp."""
    total = own_concentration(material, chemical_id, variant, strict=strict)
    for child in children_of(material["id"]):
        fraction = D(child.get("parent_mass_fraction") or 0)
        total = total + fraction * effective_concentration(
            child, chemical_id, variant, strict=strict)
    return rhu(total, CONCENTRATION_DP)


# --------------------------------------------------------------------------
# daily exposure and the safe-harbor verdict (PRD 3.6)
# --------------------------------------------------------------------------
def daily_exposure(product, chemical_id, method, route, uses_per_day, strict=False):
    contributions = []
    for component in active_components(product["id"]):
        material = db.get("materials", component["material_id"])
        if material is None:
            continue
        concentration = effective_concentration(material, chemical_id, method, strict=strict)
        if concentration == 0:
            continue
        raw = (concentration
               * D(component["quantity_grams_per_unit"])
               * D(component["contact_factor"])
               * ROUTE_ABSORPTION[route]
               * D(uses_per_day))
        contributions.append(rhu(raw, EXPOSURE_DP))
    total = sum(contributions, D(0))
    return rhu(total, EXPOSURE_DP), len(contributions)


def verdict(chemical, daily):
    if chemical is None or chemical.get("safe_harbor_basis") == "NONE" or \
            chemical.get("safe_harbor_level_ug_per_day") is None:
        return None, "NO_SAFE_HARBOR"
    level = D(chemical["safe_harbor_level_ug_per_day"])
    margin = rhu(D(daily) / level, MARGIN_DP)
    result = "AT_OR_ABOVE_SAFE_HARBOR" if D(daily) >= level else "BELOW_SAFE_HARBOR"
    return margin, result


def recompute_assessment_numbers(assessment):
    """Recompute the four derived numbers of one assessment in place."""
    product = db.get("products", assessment["product_id"])
    chemical = db.get("listed_chemicals", assessment["chemical_id"])
    if product is None:
        return False
    daily, count = daily_exposure(
        product, assessment["chemical_id"], assessment["method"],
        assessment["route"], assessment["uses_per_day"])
    margin, result = verdict(chemical, daily)
    before = (assessment.get("daily_exposure_ug"), assessment.get("margin_ratio"),
              assessment.get("result"), assessment.get("contribution_count"))
    assessment["daily_exposure_ug"] = daily
    assessment["margin_ratio"] = margin
    assessment["result"] = result
    assessment["contribution_count"] = count
    after = (daily, margin, result, count)
    return before != after


def recompute_verdict_only(assessment):
    chemical = db.get("listed_chemicals", assessment["chemical_id"])
    margin, result = verdict(chemical, assessment.get("daily_exposure_ug") or 0)
    assessment["margin_ratio"] = margin
    assessment["result"] = result


# --------------------------------------------------------------------------
# product chemical load (PRD 3.3) - round each term, sum, round the sum
# --------------------------------------------------------------------------
def chemical_load(product):
    listed = [c for c in db.rows("listed_chemicals") if c["status"] == "LISTED"]
    listed.sort(key=lambda c: c["chemical_name"])
    terms = []
    components = active_components(product["id"])
    for chemical in listed:
        for component in components:
            material = db.get("materials", component["material_id"])
            if material is None:
                continue
            concentration = effective_concentration(material, chemical["id"], "MODELED")
            terms.append(rhu(concentration * D(component["quantity_grams_per_unit"]), LOAD_DP))
    return rhu(sum(terms, D(0)), LOAD_DP)
