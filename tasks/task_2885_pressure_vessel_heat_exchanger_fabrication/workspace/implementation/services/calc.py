"""Pure calculation rules (PRD sections 2.6, 3.1, 3.3, 3.6, 3.8, 3.9).

Every rounding step is round half up, applied at the scale the owning rule
declares.
"""

import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP, localcontext

ZERO = Decimal(0)


def scaled(places):
    return Decimal(1).scaleb(-places)


def q(value, places):
    """Round half up at `places` decimal places."""
    return Decimal(value).quantize(scaled(places), rounding=ROUND_HALF_UP)


def ratio_round(numerator, denominator, places):
    """Exact half-up rounding of numerator/denominator at `places` places."""
    numerator = int(numerator)
    denominator = int(denominator)
    if denominator == 0:
        raise ZeroDivisionError
    factor = 10 ** places
    scaled_num = numerator * factor
    whole, remainder = divmod(scaled_num, denominator)
    if remainder * 2 >= denominator:
        whole += 1
    return (Decimal(whole) / Decimal(factor)).quantize(scaled(places))


def parse_date(text):
    if text is None:
        return None
    return _dt.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


# ---------------------------------------------------------------------------
# 3.3 Joint efficiency and dual-variant wall sizing
# ---------------------------------------------------------------------------
JOINT_EFFICIENCY = {
    "FULL": Decimal("1.00"),
    "SPOT": Decimal("0.85"),
    "NONE": Decimal("0.70"),
}


def joint_efficiency(rt_extent_declared):
    return JOINT_EFFICIENCY[rt_extent_declared]


def wall_thickness(pressure, radius, stress, efficiency, corrosion_allowance):
    """Return (circ_4dp, long_4dp, required_4dp, governing_variant)."""
    with localcontext() as ctx:
        ctx.prec = 60
        pressure = Decimal(pressure)
        radius = Decimal(radius)
        stress = Decimal(stress)
        efficiency = Decimal(efficiency)
        circ_denominator = stress * efficiency - Decimal("0.6") * pressure
        long_denominator = 2 * stress * efficiency + Decimal("0.4") * pressure
        circ_raw = (pressure * radius) / circ_denominator if circ_denominator != 0 else None
        long_raw = (pressure * radius) / long_denominator if long_denominator != 0 else None
        if circ_raw is None or long_raw is None:
            return None, None, None, None
        governing = "CIRCUMFERENTIAL" if circ_raw >= long_raw else "LONGITUDINAL"
        greater = circ_raw if circ_raw >= long_raw else long_raw
        required = q(greater + Decimal(corrosion_allowance), 4)
    return q(circ_raw, 4), q(long_raw, 4), required, governing


# ---------------------------------------------------------------------------
# 3.4 Material specification properties
# ---------------------------------------------------------------------------
SPEC_PROPERTIES = {
    "SA-516-70": ("FERRITIC", 1, Decimal("38"), Decimal("70")),
    "SA-240-304L": ("AUSTENITIC", 8, Decimal("25"), Decimal("70")),
    "SA-105": ("FERRITIC", 1, Decimal("36"), Decimal("70")),
    "SA-179": ("FERRITIC", 1, Decimal("26"), Decimal("47")),
}

FORM_FOR_COMPONENT = {
    "SHELL": ("PLATE",),
    "HEAD": ("PLATE",),
    "NOZZLE": ("PIPE",),
    "TUBESHEET": ("FORGING", "PLATE"),
    "FLANGE": ("FORGING",),
}


# ---------------------------------------------------------------------------
# 3.6 Examination coverage resolution
# ---------------------------------------------------------------------------

def required_volumetric_pct(weld, job, declared_extent):
    """`declared_extent` is the rt_extent_declared of the APPROVED sheet whose
    component matches the component_type of the joint's part_a (None when no
    such sheet exists)."""
    if weld.get("repair_of_weld_id") is not None:
        return 100
    category = weld["joint_category"]
    if job["design_code"] == "DIV2" and category in ("A", "B"):
        return 100
    if declared_extent is None:
        return 0
    thickness = q(weld["thickness_in"], 3)
    if category == "A":
        return {"FULL": 100, "SPOT": 25, "NONE": 0}[declared_extent]
    if category == "B":
        if declared_extent == "FULL":
            return 100 if thickness >= Decimal("1.500") else 25
        if declared_extent == "SPOT":
            return 25
        return 0
    return 0


def volumetric_method(weld, coverage_pct):
    if coverage_pct == 0:
        return None
    thickness = q(weld["thickness_in"], 3)
    if thickness >= Decimal("2.000") and weld["joint_type"] == "BUTT":
        return "UT"
    return "RT"


def required_surface_method(weld, material_classes):
    """`material_classes` are the material_class values of the joined pieces."""
    if "AUSTENITIC" in material_classes:
        return "PT"
    if weld["joint_category"] in ("C", "D") or weld["joint_type"] in ("FILLET", "CORNER"):
        return "MT"
    return None


def selection_count(group_size, requirement):
    """Number of joints a 25 percent group contributes, rounded up."""
    if requirement == 100:
        return group_size
    if requirement == 25:
        return -((-group_size * 25) // 100)
    return 0


EXAM_CLASS = {"RT": "VOLUMETRIC", "UT": "VOLUMETRIC", "PT": "SURFACE", "MT": "SURFACE"}


# ---------------------------------------------------------------------------
# 3.8 Soak requirement and test parameters
# ---------------------------------------------------------------------------

def required_soak_minutes(governing_thickness_in):
    product = q(Decimal(governing_thickness_in) * Decimal(60), 0)
    minutes = int(product)
    return minutes if minutes > 15 else 15


TEST_PARAMETERS = {
    "HYDROSTATIC": (Decimal("1.3"), 30, Decimal(30)),
    "PNEUMATIC": (Decimal("1.1"), 60, Decimal(60)),
}


def test_parameters(test_type, mawp_psi, stress_ratio, mdmt_f):
    multiplier, min_hold, temp_margin = TEST_PARAMETERS[test_type]
    pressure = q(multiplier * Decimal(mawp_psi) * Decimal(stress_ratio), 1)
    return pressure, min_hold, Decimal(mdmt_f) + temp_margin


# ---------------------------------------------------------------------------
# 3.9 Data package completeness
# ---------------------------------------------------------------------------
SECTION_ORDER = ("DESIGN", "MATERIAL", "WELDING", "NDE", "PWHT", "TEST")
SECTION_WEIGHTS = {
    "DESIGN": 25, "MATERIAL": 20, "WELDING": 20,
    "NDE": 15, "PWHT": 10, "TEST": 10,
}


def section_points(section, numerator, denominator):
    weight = SECTION_WEIGHTS[section]
    if denominator == 0:
        return Decimal(weight).quantize(scaled(2)), True
    points = ratio_round(weight * numerator, denominator, 2)
    return points, numerator >= denominator


def parse_instant(text):
    if text is None:
        return None
    return _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
