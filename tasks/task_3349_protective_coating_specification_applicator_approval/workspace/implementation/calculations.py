"""The eight scaffold calculation rules, with exact constants and rounding."""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from errors import ApiError
from storage import store

THINNER_HARD_CAP = Decimal('0.25')
SPOT_FLOOR_FRACTION = Decimal('0.8')
HOLIDAY_LIMIT_DEFAULT = Decimal('0.1')
HOLIDAY_LIMIT_TANK_INTERIOR = Decimal('0')
SALT_LIMIT_DEFAULT = Decimal('10.0')
SALT_LIMIT_TANK_INTERIOR = Decimal('5.0')
DEW_POINT_SPREAD_MIN_C = Decimal('3.0')


def D(x):
    return Decimal(str(x))


def round1(x):
    """Round half-up to exactly 1 decimal place; returned as a float for JSON."""
    return float(D(x).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


# --- voc_compliance ---
def voc_as_supplied(system):
    return round1(system['base_voc_gpl'])


def voc_as_applied(system, thinner_pct_used):
    t = D(thinner_pct_used)
    if t > D(system['max_thinner_pct']) or t > THINNER_HARD_CAP:
        raise ApiError('ERR_THINNER_LIMIT_EXCEEDED', 422,
                       'thinner_pct_used exceeds the permitted maximum')
    return round1(D(system['base_voc_gpl']) * (1 - t) + D(system['thinner_voc_gpl']) * t)


def find_regulation(jurisdiction_code, application_method, at):
    """ACTIVE regulation whose half-open [from, to) window contains `at`."""
    for r in store.voc_regulations.values():
        if r['status'] != 'ACTIVE':
            continue
        if r['jurisdiction_code'] != jurisdiction_code:
            continue
        if r['application_method'] != application_method:
            continue
        if r['_from'] <= at < r['_to']:
            return r
    return None


# --- dft_acceptance ---
def dft_verdict(system, readings):
    spec_min = D(system['total_dft_min_mils'])
    spec_max = D(system['total_dft_max_mils'])
    if system['surface_prep_standard'] == 'SSPC_SP11_POWER_TOOL':
        # GAGE_80_20: count-based, no average comparison
        passing = sum(1 for r in readings if spec_min <= D(r) <= spec_max)
        needed = int((SPOT_FLOOR_FRACTION * len(readings)).to_integral_value(
            rounding=ROUND_CEILING))
        return 'PASS' if passing >= needed else 'FAIL'
    # SPOT_AVERAGE: average rounded half-up to 1dp BEFORE comparison
    avg = (sum(D(r) for r in readings) / len(readings)).quantize(
        Decimal('0.1'), rounding=ROUND_HALF_UP)
    floor = SPOT_FLOOR_FRACTION * spec_min
    ok = (avg >= spec_min and avg <= spec_max
          and min(D(r) for r in readings) >= floor)
    return 'PASS' if ok else 'FAIL'


# --- adhesion verdict (part of InspectionReport filing) ---
def adhesion_verdict(system, readings):
    return ('PASS' if min(D(r) for r in readings) >= D(system['adhesion_min_psi'])
            else 'FAIL')


# --- holiday_density ---
def holiday_verdict(asset_type, holiday_count, tested_area_m2):
    limit = (HOLIDAY_LIMIT_TANK_INTERIOR if asset_type == 'TANK_INTERIOR'
             else HOLIDAY_LIMIT_DEFAULT)
    density = D(holiday_count) / D(tested_area_m2)  # full precision, exact compare
    return 'PASS' if density <= limit else 'FAIL'


# --- surface_prep_verdict ---
def prep_verdict(system, asset_type, observed_standard, profile_mils, salt, dew_spread):
    reasons = []
    if observed_standard != system['surface_prep_standard']:
        reasons.append('PREP_STANDARD_MISMATCH')
    if not (D(system['min_surface_profile_mils']) <= D(profile_mils)
            <= D(system['max_surface_profile_mils'])):
        reasons.append('PROFILE_OUT_OF_RANGE')
    salt_limit = (SALT_LIMIT_TANK_INTERIOR if asset_type == 'TANK_INTERIOR'
                  else SALT_LIMIT_DEFAULT)
    if D(salt) > salt_limit:
        reasons.append('SALT_EXCEEDED')
    if D(dew_spread) < DEW_POINT_SPREAD_MIN_C:
        reasons.append('DEW_POINT_SPREAD_TOO_SMALL')
    return ('PASSED' if not reasons else 'FAILED'), reasons


# --- warranty_liability_split ---
def warranty_split(exposure_cents, fault_pct):
    material = int((Decimal(exposure_cents) * Decimal(fault_pct) / Decimal(100))
                   .quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return material, exposure_cents - material


# --- work_order_window_conflict (closed intervals: touching endpoints conflict) ---
def windows_conflict(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


# --- regulation_window_uniqueness (half-open: abutment is legal) ---
def regulation_overlap(a_from, a_to, b_from, b_to):
    return a_from < b_to and b_from < a_to
