"""Every derived quantity in the API (PRD sections 2.7, 3.3, 3.4, 3.5, 3.6, 3.8, 3.9).

All money is integer cents carried through exact Decimal arithmetic and rounded
half up only at the points the PRD names.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

from errors import ApiError
from store import parse_date, store

getcontext().prec = 60

# ------------------------------------------------------------------- constants

COLOR_UPLIFT_PCT = Decimal("0.07")
FREIGHT_BASE_CENTS = 48000
FREIGHT_PER_UNIT_CENTS = 1250
DISCOUNT_TIER_1_MIN_CENTS = 2000000
DISCOUNT_TIER_1_PCT = Decimal("0.03")
DISCOUNT_TIER_2_MIN_CENTS = 5000000
DISCOUNT_TIER_2_PCT = Decimal("0.06")

TODDLER_UPLIFT_CM = 5
CLAY_SOIL_UPLIFT_CM = 3
MIN_SURFACING_DEPTH_CM = 15
MAX_CRITICAL_FALL_HEIGHT_CM = 305

SLIDE_EXIT_EXTRA_CM = 122

MIN_REVIEW_VOTES = 25
APPROVAL_THRESHOLD_PCT = Decimal("60.0")

DAYS_PER_YEAR = 365
STEP_LATE_PCT = 50
PRORATED_CATEGORIES = ("POST", "DECK", "METAL_CLIMBER")
STEP_CATEGORIES = ("PLASTIC_SLIDE", "HARDWARE_KIT")

SURFACING_SHARE_PCT = Decimal("0.20")

JOB_EXCLUDED_STATUSES = ("AUDIT_PASSED", "AUDIT_FAILED", "CANCELLED")
TRAVEL_BUFFER_DAYS = 1

MAX_REWORK_CYCLES = 2
AUDIT_FAILURE_SUSPENSION_THRESHOLD = 1

LEGACY_SURCHARGE_PCT = Decimal("0.18")
HANDLING_BASE_CENTS = 3500
FREE_HANDLING_LINE_THRESHOLD_CENTS = 250000

AGE_GROUPS = ("TODDLER_6_23M", "PRESCHOOL_2_5", "SCHOOL_AGE_5_12")
CATEGORIES = ("POST", "DECK", "PLASTIC_SLIDE", "METAL_CLIMBER", "HARDWARE_KIT")
SURFACING_MATERIALS = ("ENGINEERED_WOOD_FIBER", "POURED_RUBBER")
SOIL_TYPES = ("SANDY_LOAM", "GRAVEL", "CLAY")

FALL_HEIGHT_FIELD = {
    "TODDLER_6_23M": "max_fall_height_cm_toddler",
    "PRESCHOOL_2_5": "max_fall_height_cm_preschool",
    "SCHOOL_AGE_5_12": "max_fall_height_cm_school_age",
}

DESIGN_EDITABLE_STATUSES = ("CONSULTATION", "REVISION_REQUESTED")


def round_half_up(value):
    """Round an exact Decimal to a whole unit, half away from zero."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------- use-zone geometry

def use_zone_extent(model, x_start_cm):
    start = x_start_cm - model["use_zone_footprint_cm"]
    end = x_start_cm + model["use_zone_footprint_cm"]
    if model["category"] == "PLASTIC_SLIDE":
        end += SLIDE_EXIT_EXTRA_CM
    return start, end


def zones_overlap(a_start, a_end, b_start, b_end):
    """Closed intervals: touching at a single coordinate counts as overlapping."""
    return a_start <= b_end and b_start <= a_end


def clear_separation(a_start, a_end, b_start, b_end):
    """Whole centimetres strictly between two closed intervals."""
    if a_end <= b_start:
        return b_start - a_end - 1
    if b_end <= a_start:
        return a_start - b_end - 1
    return -1


# ------------------------------------------- play-area derived surfacing numbers

def area_critical_fall_height(area):
    best = 0
    for placement in store.area_placements(area["id"]):
        if placement["status"] not in ("DRAFT", "VALIDATED"):
            continue
        model = store.get("model", placement["component_model_id"])
        if model is None:
            continue
        if model["deck_height_cm"] > best:
            best = model["deck_height_cm"]
    return best


def surfacing_depth_requirement(area, project, cfh):
    if cfh == 0:
        base = 0
    elif area["surfacing_material"] == "ENGINEERED_WOOD_FIBER":
        base = 23 if cfh <= 150 else (30 if cfh <= 200 else 38)
    else:
        base = 5 if cfh <= 150 else (8 if cfh <= 200 else 13)
    toddler_candidate = base + (TODDLER_UPLIFT_CM if area["age_group"] == "TODDLER_6_23M" else 0)
    soil_candidate = base + (CLAY_SOIL_UPLIFT_CM if project["site_soil_type"] == "CLAY" else 0)
    return max(toddler_candidate, soil_candidate, MIN_SURFACING_DEPTH_CM)


def recompute_area_geometry(area, bump=False):
    """Re-derive critical_fall_height_cm and required_surfacing_depth_cm."""
    project = store.get("project", area["project_id"])
    cfh = area_critical_fall_height(area)
    if cfh > MAX_CRITICAL_FALL_HEIGHT_CM:
        raise ApiError("ERR_FALL_HEIGHT_EXCEEDS_STANDARD")
    area["critical_fall_height_cm"] = cfh
    area["required_surfacing_depth_cm"] = surfacing_depth_requirement(area, project, cfh)
    if bump:
        store.touch(area)
    return area


def recompute_area_geometry_quiet(area):
    """Re-derive both numbers without raising on the 305 cm ceiling (cascades)."""
    project = store.get("project", area["project_id"])
    cfh = area_critical_fall_height(area)
    area["critical_fall_height_cm"] = cfh
    area["required_surfacing_depth_cm"] = surfacing_depth_requirement(area, project, cfh)
    return area


# ----------------------------------------------------------- accessible route

def accessible_route_demanded(project, standard):
    if project.get("accessible_route_required"):
        return True
    return bool(standard is not None and standard.get("requires_accessible_route"))


def accessible_route_satisfied(project):
    for area in store.project_areas(project["id"]):
        found = False
        for placement in store.area_placements(area["id"]):
            if placement["status"] not in ("DRAFT", "VALIDATED"):
                continue
            model = store.get("model", placement["component_model_id"])
            if model is not None and model.get("accessible_transfer_ready"):
                found = True
                break
        if not found:
            return False
    return True


# ---------------------------------------------------------------- quote pricing

def quote_pricing(project_id, variant):
    """Six-step pricing (PRD section 3.5).  Returns a dict of frozen amounts."""
    included = ("DRAFT", "VALIDATED") if variant == "PROVISIONAL" else ("VALIDATED",)
    placements = [p for p in store.project_placements(project_id) if p["status"] in included]
    placements.sort(key=lambda r: (r["created_at"], r["_seq"]))
    if not placements:
        raise ApiError("ERR_QUOTE_EMPTY_SCOPE")

    raw_lines = []
    priced_unit_count = 0
    for placement in placements:
        model = store.get("model", placement["component_model_id"])
        base_line = Decimal(model["unit_price_cents"]) * Decimal(placement["quantity"])
        if placement["color_choice"] != model["color_options"][0]:
            raw = base_line * (Decimal(1) + COLOR_UPLIFT_PCT)
        else:
            raw = base_line
        raw_lines.append(raw)
        priced_unit_count += placement["quantity"]

    if variant == "PROVISIONAL":
        subtotal_cents = sum(round_half_up(line) for line in raw_lines)
    else:
        subtotal_cents = round_half_up(sum(raw_lines, Decimal(0)))

    freight_cents = FREIGHT_BASE_CENTS + FREIGHT_PER_UNIT_CENTS * priced_unit_count

    if subtotal_cents >= DISCOUNT_TIER_2_MIN_CENTS:
        rate = DISCOUNT_TIER_2_PCT
    elif subtotal_cents >= DISCOUNT_TIER_1_MIN_CENTS:
        rate = DISCOUNT_TIER_1_PCT
    else:
        rate = Decimal(0)
    discount_cents = round_half_up(Decimal(subtotal_cents) * rate)

    total_cents = subtotal_cents + freight_cents - discount_cents
    return {
        "subtotal_cents": subtotal_cents,
        "freight_cents": freight_cents,
        "discount_cents": discount_cents,
        "total_cents": total_cents,
        "priced_unit_count": priced_unit_count,
        "line_count": len(placements),
        "placements": placements,
    }


# ------------------------------------------------------------- community voting

def community_approval_pct(yes_votes, no_votes):
    total = yes_votes + no_votes
    if total == 0:
        return 0.0
    exact = Decimal(100) * Decimal(yes_votes) / Decimal(total)
    return float(exact.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# -------------------------------------------------------- fundraising waterfall

def recompute_fundraising(project):
    """Full recompute of funds_collected_cents and the four buckets."""
    collected = 0
    for pledge in store.project_pledges(project["id"]):
        if pledge["status"] == "COLLECTED":
            collected += pledge["amount_cents"]
    project["funds_collected_cents"] = collected

    candidates = [q for q in store.project_quotes(project["id"])
                  if q["status"] in ("ISSUED", "ACCEPTED")]
    quote = candidates[-1] if candidates else None

    if quote is None:
        target_1 = 0
        target_2 = 0
        target_3 = 0
    else:
        target_1 = quote["freight_cents"]
        target_2 = round_half_up(Decimal(quote["subtotal_cents"]) * SURFACING_SHARE_PCT)
        target_3 = quote["subtotal_cents"] - target_2

    remaining = collected
    bucket_1 = min(remaining, target_1)
    remaining -= bucket_1
    bucket_2 = min(remaining, target_2)
    remaining -= bucket_2
    bucket_3 = min(remaining, target_3)
    remaining -= bucket_3
    project["alloc_permit_freight_cents"] = bucket_1
    project["alloc_surfacing_cents"] = bucket_2
    project["alloc_structure_cents"] = bucket_3
    project["alloc_contingency_cents"] = remaining
    return project


# ----------------------------------------------------------- warranty coverage

def warranty_coverage(model, category, quantity, installed_on, failure_date):
    days = (failure_date - parse_date(installed_on)).days
    elapsed_years = days // DAYS_PER_YEAR
    wy = model["warranty_years"]
    if category in PRORATED_CATEGORIES:
        variant = "PRORATED"
        if elapsed_years >= wy:
            covered_pct = 0
        else:
            covered_pct = round_half_up(Decimal(100) * Decimal(wy - elapsed_years) / Decimal(wy))
    else:
        variant = "STEP"
        half = -((-wy) // 2)
        if elapsed_years <= half:
            covered_pct = 100
        elif elapsed_years < wy:
            covered_pct = STEP_LATE_PCT
        else:
            covered_pct = 0
    reimbursement_cents = round_half_up(
        Decimal(model["unit_price_cents"]) * Decimal(quantity) * Decimal(covered_pct) / Decimal(100)
    )
    return {
        "elapsed_years": elapsed_years,
        "coverage_variant": variant,
        "covered_pct": covered_pct,
        "reimbursement_cents": reimbursement_cents,
    }


# ------------------------------------------------------------ installer ledger

def inclusive_days(start_date, end_date):
    return (end_date - start_date).days + 1


def booked_crew_days(crew_size, start_date, end_date):
    return crew_size * inclusive_days(start_date, end_date)


def recompute_committed_crew_days(installer):
    total = 0
    for job in store.installer_jobs(installer["id"]):
        if job["status"] in JOB_EXCLUDED_STATUSES:
            continue
        total += job["booked_crew_days"]
    installer["committed_crew_days"] = total
    return installer


def recompute_open_audit_failures(installer):
    count = 0
    for job in store.installer_jobs(installer["id"]):
        if job["status"] == "AUDIT_FAILED":
            count += 1
    installer["open_audit_failures"] = count
    return installer


def booking_conflicts(installer, new_start, new_end, exclude_job_id=None):
    """True when the closed window intersects, or fails the clear travel day."""
    for job in store.installer_jobs(installer["id"]):
        if job["id"] == exclude_job_id:
            continue
        if job["status"] in JOB_EXCLUDED_STATUSES:
            continue
        other_start = parse_date(job["scheduled_start_date"])
        other_end = parse_date(job["scheduled_end_date"])
        gap_after = (new_start - other_end).days
        gap_before = (other_start - new_end).days
        if gap_after >= 1 + TRAVEL_BUFFER_DAYS:
            continue
        if gap_before >= 1 + TRAVEL_BUFFER_DAYS:
            continue
        return True
    return False


# ------------------------------------------------------------ production floor

def priced_placements_for_order(order):
    """The VALIDATED placement set the order's FIRM quote priced."""
    quote = store.get("quote", order["quote_id"])
    if quote is None:
        return []
    placements = [p for p in store.project_placements(quote["project_id"])
                  if p["status"] == "VALIDATED"]
    placements.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return placements


def hardware_bag_total(order):
    total = 0
    for placement in priced_placements_for_order(order):
        model = store.get("model", placement["component_model_id"])
        if model is None:
            continue
        total += model["hardware_bag_count"] * placement["quantity"]
    return total


# ------------------------------------------------------- retrofit / spare parts

def replacement_retrofit_pricing(model, quantity):
    if model["lifecycle_status"] == "LEGACY":
        unit_price = model["unit_price_cents"] + round_half_up(
            Decimal(model["unit_price_cents"]) * LEGACY_SURCHARGE_PCT
        )
        legacy_applied = True
    else:
        unit_price = model["unit_price_cents"]
        legacy_applied = False
    line_cents = unit_price * quantity
    handling = 0 if line_cents >= FREE_HANDLING_LINE_THRESHOLD_CENTS else HANDLING_BASE_CENTS
    return {
        "retrofit_unit_price_cents": unit_price,
        "retrofit_handling_cents": handling,
        "retrofit_total_cents": line_cents + handling,
        "legacy_surcharge_applied": legacy_applied,
    }
