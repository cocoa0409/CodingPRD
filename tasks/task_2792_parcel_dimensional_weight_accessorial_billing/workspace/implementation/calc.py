"""Measurement, billable-weight, tolerance and accessorial calculations.

PRD 3.3 (preliminary determination), PRD 3.4 (tolerance + final determination),
PRD 2.6 (rounding disciplines).  All money is integer cents; every decimal
figure is produced with decimal.Decimal, never float arithmetic.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# ---- accessorial geometry constants (PRD 3.3) ----------------------------
OVERSIZE_LONGEST_IN = 96
OVERSIZE_LENGTH_PLUS_GIRTH_IN = 130
AH_WEIGHT_LBS = 50
AH_LONGEST_IN = 48
OVERSIZE_MIN_BILLABLE_LBS = 90

# ---- tolerance constants (PRD 3.4) --------------------------------------
DIM_VARIANCE_TOLERANCE_PCT = Decimal("5.00")
WEIGHT_VARIANCE_ABS_LBS = Decimal("0.5")
WEIGHT_VARIANCE_PCT = Decimal("2.00")

# ---- window constants (PRD 3.7, 3.9) -----------------------------------
CLAIM_WINDOW_DAYS = 15
DISPUTE_WINDOW_DAYS = 90
MAX_EVIDENCE_ROUNDS = 2

# ---- accessorial catalogue (PRD 3.3, 3.5) ------------------------------
ACCESSORIAL_CODES = (
    "RESIDENTIAL",
    "DELIVERY_AREA",
    "OVERSIZE",
    "ADDITIONAL_HANDLING",
    "ADDRESS_CORRECTION",
    "RETURN_UNDELIVERABLE",
    "REFUSAL",
)

DEFAULT_RATE_CENTS = {
    "RESIDENTIAL": 590,
    "OVERSIZE": 12500,
    "ADDITIONAL_HANDLING": 2450,
    "ADDRESS_CORRECTION": 2200,
    "RETURN_UNDELIVERABLE": 1800,
    "REFUSAL": 1350,
}

DAS_RATE_CENTS = {
    "NONE": 0,
    "DAS": 425,
    "EXTENDED": 650,
}

DELIVERY_AREA_CLASSES = ("NONE", "DAS", "EXTENDED")
BASIS_VALUES = ("ACTUAL", "DIMENSIONAL", "OVERSIZE_FLOOR")


# --------------------------------------------------------------------------
# rounding primitives (PRD 2.6)
# --------------------------------------------------------------------------

def dec(value):
    return Decimal(str(value))


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_inch(value):
    """Round half up to a whole inch.  Runs BEFORE any multiplication."""
    return int(round_half_up(value, 0))


def ceil_pounds(value):
    """Round up (ceiling) to a whole pound."""
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def cube_of(length_in, width_in, height_in):
    """Each dimension rounded half up to a whole inch first, then multiplied."""
    return round_inch(length_in) * round_inch(width_in) * round_inch(height_in)


def dim_pounds(cube_in3, divisor):
    """Exact rational divide first, ceiling second (PRD 3.3 step 2)."""
    if divisor <= 0:
        return 0
    return -((-cube_in3) // divisor)


def as_number(value):
    """Render a Decimal for JSON as an int when integral, else as a float."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def fmt_measure(value):
    """Human-facing number rendering for assessed_basis notes."""
    d = dec(value)
    if d == d.to_integral_value():
        return str(int(d))
    return str(d.normalize())


# --------------------------------------------------------------------------
# geometry / accessorial flags (PRD 3.3)
# --------------------------------------------------------------------------

def geometry(length_in, width_in, height_in):
    """The three rounded whole-inch dimensions plus derived geometry."""
    dims = sorted([round_inch(length_in), round_inch(width_in), round_inch(height_in)],
                  reverse=True)
    longest = dims[0]
    mid = dims[1]
    smallest = dims[2]
    length_plus_girth = longest + 2 * (mid + smallest)
    return {
        "dims": dims,
        "longest": longest,
        "mid": mid,
        "smallest": smallest,
        "length_plus_girth": length_plus_girth,
        "cube_in3": dims[0] * dims[1] * dims[2],
    }


def evaluate_flags(length_in, width_in, height_in, weight_lbs, non_conveyable):
    """oversize_flag / additional_handling_flag plus their trigger notes.

    Both oversize comparisons are strict.  OVERSIZE absorbs
    ADDITIONAL_HANDLING: the two flags are mutually exclusive.
    """
    geo = geometry(length_in, width_in, height_in)
    longest = geo["longest"]
    lpg = geo["length_plus_girth"]

    oversize_reason = None
    if longest > OVERSIZE_LONGEST_IN:
        oversize_reason = "longest_in=%d>%d" % (longest, OVERSIZE_LONGEST_IN)
    elif lpg > OVERSIZE_LENGTH_PLUS_GIRTH_IN:
        oversize_reason = "length_plus_girth=%d>%d" % (lpg, OVERSIZE_LENGTH_PLUS_GIRTH_IN)
    oversize_flag = oversize_reason is not None

    ah_reason = None
    if not oversize_flag:
        if dec(weight_lbs) > Decimal(AH_WEIGHT_LBS):
            ah_reason = "weight_lbs=%s>%d" % (fmt_measure(weight_lbs), AH_WEIGHT_LBS)
        elif longest > AH_LONGEST_IN:
            ah_reason = "longest_in=%d>%d" % (longest, AH_LONGEST_IN)
        elif non_conveyable:
            ah_reason = "non_conveyable=true"
    ah_flag = ah_reason is not None

    return {
        "geometry": geo,
        "oversize_flag": oversize_flag,
        "oversize_basis": oversize_reason,
        "additional_handling_flag": ah_flag,
        "additional_handling_basis": ah_reason,
    }


# --------------------------------------------------------------------------
# billable weight (PRD 3.3 steps 1-5, both variants)
# --------------------------------------------------------------------------

def billable_weight(length_in, width_in, height_in, weight_lbs, divisor,
                    non_conveyable):
    """The five pinned steps; identical shape for PRELIMINARY and FINAL."""
    flags = evaluate_flags(length_in, width_in, height_in, weight_lbs, non_conveyable)
    cube_in3 = flags["geometry"]["cube_in3"]
    dim_weight_lbs = dim_pounds(cube_in3, divisor)
    actual_billable_lbs = ceil_pounds(weight_lbs)
    oversize_floor_lbs = OVERSIZE_MIN_BILLABLE_LBS if flags["oversize_flag"] else 0

    billable = max(actual_billable_lbs, dim_weight_lbs, oversize_floor_lbs)

    if oversize_floor_lbs > actual_billable_lbs and oversize_floor_lbs > dim_weight_lbs:
        basis = "OVERSIZE_FLOOR"
    elif actual_billable_lbs >= dim_weight_lbs:
        basis = "ACTUAL"
    else:
        basis = "DIMENSIONAL"

    result = dict(flags)
    result.update({
        "cube_in3": cube_in3,
        "dim_weight_lbs": dim_weight_lbs,
        "actual_billable_lbs": actual_billable_lbs,
        "oversize_floor_lbs": oversize_floor_lbs,
        "billable_weight_lbs": billable,
        "basis": basis,
    })
    return result


# --------------------------------------------------------------------------
# scan tolerance evaluation (PRD 3.4)
# --------------------------------------------------------------------------

def tolerance_verdict(scanned_cube_in3, declared_cube_in3,
                      scanned_weight_lbs, declared_weight_lbs):
    """Compare a capture against the shipper's DECLARED figures."""
    if declared_cube_in3:
        raw_pct = (Decimal(abs(scanned_cube_in3 - declared_cube_in3)) * Decimal(100)
                   / Decimal(declared_cube_in3))
        dim_variance_pct = round_half_up(raw_pct, 2)
    else:
        dim_variance_pct = Decimal("0.00")

    weight_variance_lbs = round_half_up(
        abs(dec(scanned_weight_lbs) - dec(declared_weight_lbs)), 1)

    pct_allowance = round_half_up(
        dec(declared_weight_lbs) * WEIGHT_VARIANCE_PCT / Decimal(100), 1)
    weight_allowance = max(WEIGHT_VARIANCE_ABS_LBS, pct_allowance)

    cube_breach = dim_variance_pct >= DIM_VARIANCE_TOLERANCE_PCT
    weight_breach = weight_variance_lbs >= weight_allowance

    return {
        "dim_variance_pct": dim_variance_pct,
        "weight_variance_lbs": weight_variance_lbs,
        "weight_allowance": weight_allowance,
        "tolerance_status": ("EXCEEDS_TOLERANCE" if (cube_breach or weight_breach)
                            else "WITHIN_TOLERANCE"),
    }


# --------------------------------------------------------------------------
# accessorial rate resolution (PRD 3.3)
# --------------------------------------------------------------------------

def resolve_accessorial_rate(contract, code, delivery_area_class):
    """Overrides first, then the class table for DELIVERY_AREA, then defaults."""
    overrides = (contract or {}).get("accessorial_rate_overrides") or {}
    if code in overrides:
        return int(overrides[code])
    if code == "DELIVERY_AREA":
        return DAS_RATE_CENTS.get(delivery_area_class or "NONE", 0)
    return DEFAULT_RATE_CENTS.get(code, 0)
