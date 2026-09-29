"""Paid-miles determination and linehaul component pay (PRD section 3.4)."""
import constants
import db
import money
import queries


def guide_miles(load, guide):
    """The guide's own distance for this load."""
    if guide == "PRACTICAL":
        return load["practical_miles"]
    return load["hhg_miles"]


def apply_short_haul_floor(base_miles):
    """The floor is strict: it fires below 250 miles and not at exactly 250."""
    if base_miles < constants.MIN_PAID_MILES:
        return constants.MIN_PAID_MILES, True
    return base_miles, False


def per_mile_leg(paid_miles, rate_value):
    """Mileage band: the first 500 miles at the rate, every mile beyond at rate + 3."""
    banded = min(paid_miles, constants.MILEAGE_BAND_BREAK)
    excess = max(paid_miles - constants.MILEAGE_BAND_BREAK, 0)
    return banded * rate_value + excess * (rate_value + constants.LONG_HAUL_BUMP_CENTS)


def revenue_percent_leg(linehaul_revenue_cents, rate_value_bps):
    return money.bps(linehaul_revenue_cents, rate_value_bps)


def linehaul(load, paid_miles, components_by_type, driver_type):
    """Return (linehaul_pay_cents, linehaul_line_type).

    Each leg is rounded independently before the comparison; an exact tie is won
    by the per-mile leg; the team share is applied only after the comparison.
    """
    per_mile_component = components_by_type.get("PER_MILE")
    revenue_component = components_by_type.get("REVENUE_PERCENT")

    per_mile_amount = None
    if per_mile_component is not None:
        per_mile_amount = per_mile_leg(paid_miles, per_mile_component["rate_value"])

    revenue_amount = None
    if revenue_component is not None:
        revenue_amount = revenue_percent_leg(
            load["linehaul_revenue_cents"], revenue_component["rate_value"]
        )

    if per_mile_amount is None and revenue_amount is None:
        return 0, "NONE"
    if revenue_amount is None:
        amount, line_type = per_mile_amount, "LINEHAUL_PER_MILE"
    elif per_mile_amount is None:
        amount, line_type = revenue_amount, "LINEHAUL_PERCENT"
    elif per_mile_amount >= revenue_amount:
        amount, line_type = per_mile_amount, "LINEHAUL_PER_MILE"
    else:
        amount, line_type = revenue_amount, "LINEHAUL_PERCENT"

    if driver_type == "COMPANY_TEAM":
        amount = money.bps(amount, constants.TEAM_SHARE_BPS)
    return amount, line_type


def hourly_pay(load, components_by_type):
    component = components_by_type.get("HOURLY")
    if component is None:
        return 0
    minutes = load.get("hours_worked_minutes") or 0
    if minutes <= 0:
        return 0
    return money.round_half_up_div(minutes * component["rate_value"], 60)


def activity_pay(components_by_type):
    component = components_by_type.get("ACTIVITY")
    if component is None:
        return 0
    return component["rate_value"]


def rate_of(components_by_type, line_type):
    """The rate of the component that drives a given line type."""
    mapping = {
        "LINEHAUL_PER_MILE": "PER_MILE",
        "LINEHAUL_PERCENT": "REVENUE_PERCENT",
        "HOURLY": "HOURLY",
        "ACTIVITY": "ACTIVITY",
    }
    component = components_by_type.get(mapping.get(line_type))
    if component is None:
        return None
    return component["rate_value"]


def taxable_of(components_by_type, line_type):
    mapping = {
        "LINEHAUL_PER_MILE": "PER_MILE",
        "LINEHAUL_PERCENT": "REVENUE_PERCENT",
        "HOURLY": "HOURLY",
        "ACTIVITY": "ACTIVITY",
    }
    component = components_by_type.get(mapping.get(line_type))
    if component is None:
        return True
    return component["taxable"]


def recompute(load, guide, base_miles):
    """Write the whole pay block onto a load from a guide/miles pair."""
    paid_miles, floor_applied = apply_short_haul_floor(base_miles)
    package = db.pay_packages.get(load["pay_package_id_snapshot"])
    components = queries.components_by_type(package["id"]) if package else {}
    driver = db.drivers.get(load["driver_id"])
    driver_type = driver["driver_type"] if driver else None
    amount, line_type = linehaul(load, paid_miles, components, driver_type)

    load["applied_mileage_guide"] = guide
    load["base_guide_miles"] = base_miles
    load["paid_miles"] = paid_miles
    load["short_haul_floor_applied"] = floor_applied
    load["linehaul_pay_cents"] = amount
    load["linehaul_line_type"] = line_type
    return load


def recompute_from_snapshot(load):
    """Delivery-time computation: the guide comes from the snapshotted package."""
    package = db.pay_packages.get(load["pay_package_id_snapshot"])
    guide = package["mileage_guide"] if package else "PRACTICAL"
    return recompute(load, guide, guide_miles(load, guide))


def linehaul_for_claim(load, guide, base_miles):
    """Re-run the linehaul computation for a hypothetical guide/miles pair
    without touching the stored load (used for correction deltas)."""
    paid_miles, _ = apply_short_haul_floor(base_miles)
    package = db.pay_packages.get(load["pay_package_id_snapshot"])
    components = queries.components_by_type(package["id"]) if package else {}
    driver = db.drivers.get(load["driver_id"])
    driver_type = driver["driver_type"] if driver else None
    return linehaul(load, paid_miles, components, driver_type)
