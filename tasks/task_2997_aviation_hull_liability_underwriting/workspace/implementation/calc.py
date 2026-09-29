"""Every arithmetic rule of PRD section 3, with the pinned rounding order."""

import constants as C
import util


# --- depreciation -------------------------------------------------------------

def residual_ppm(manufacture_year, reference_year):
    age = reference_year - manufacture_year
    if age < 0:
        age = 0
    residual = C.FULL_PPM - age * C.DEPRECIATION_PER_YEAR_PPM
    if residual < C.RESIDUAL_FLOOR_PPM:
        residual = C.RESIDUAL_FLOOR_PPM
    return residual


def depreciated_hull_value(aircraft, reference_year):
    """Straight-line decay of hull_new_value_cents with a 40% residual floor."""
    ppm = residual_ppm(aircraft["manufacture_year"], reference_year)
    return util.ifloor(aircraft["hull_new_value_cents"] * ppm, C.FULL_PPM)


def over_insurance_ceiling(aircraft, reference_year):
    """The largest agreed value admissible against the airframe (120% of depreciated)."""
    depreciated = depreciated_hull_value(aircraft, reference_year)
    return util.ifloor(depreciated * C.OVER_INSURANCE_CAP_PPM, C.FULL_PPM)


# --- pilot qualification ------------------------------------------------------

def band_from_score(score):
    if score >= C.BAND_A_MIN:
        return "BAND_A"
    if score >= C.BAND_B_MIN:
        return "BAND_B"
    if score >= C.BAND_C_MIN:
        return "BAND_C"
    return "BAND_D"


def qualification_score(total_hours, hours_on_type, instrument_rated,
                        license_type, last_training_completed_at, now):
    hours_component = util.ifloor(total_hours * C.HOURS_COMPONENT_CAP, C.HOURS_SATURATION)
    if hours_component > C.HOURS_COMPONENT_CAP:
        hours_component = C.HOURS_COMPONENT_CAP
    type_component = util.ifloor(hours_on_type * C.TYPE_COMPONENT_CAP, C.TYPE_SATURATION)
    if type_component > C.TYPE_COMPONENT_CAP:
        type_component = C.TYPE_COMPONENT_CAP
    rating_component = C.INSTRUMENT_RATING_POINTS if instrument_rated else 0
    licence_component = C.LICENCE_POINTS[license_type]
    score = hours_component + type_component + rating_component + licence_component
    if util.day_diff(last_training_completed_at, now) > C.TRAINING_RECURRENCY_DAYS:
        score -= C.RECURRENCY_PENALTY_POINTS
    if score < C.SCORE_MIN:
        score = C.SCORE_MIN
    if score > C.SCORE_MAX:
        score = C.SCORE_MAX
    return score


def pilot_logged_score(pilot, now):
    return qualification_score(
        pilot["total_logged_hours"], pilot["hours_on_type"], pilot["instrument_rated"],
        pilot["license_type"], pilot["last_training_completed_at"], now,
    )


def pilot_verified_score(pilot, now):
    if pilot.get("verified_at") is None:
        return None
    return qualification_score(
        pilot["verified_total_hours"], pilot["verified_hours_on_type"], pilot["instrument_rated"],
        pilot["license_type"], pilot["last_training_completed_at"], now,
    )


def pilot_band(pilot, basis, now):
    """The band that rates a hull under the given warranty basis."""
    if basis == "VERIFIED_HOURS":
        score = pilot_verified_score(pilot, now)
        if score is None:
            score = pilot_logged_score(pilot, now)
    else:
        score = pilot_logged_score(pilot, now)
    return band_from_score(score)


# --- hull rating --------------------------------------------------------------

def hull_rate_ppm(base_hull_rate_ppm, use_class, territorial_limit_code, rated_pilot_band):
    """Three successive multiplications, the fraction discarded after each, then clamped."""
    rate = util.ifloor(base_hull_rate_ppm * C.USE_CLASS_FACTOR_PPM[use_class], C.FULL_PPM)
    rate = util.ifloor(rate * C.TERRITORY_FACTOR_PPM[territorial_limit_code], C.FULL_PPM)
    rate = util.ifloor(rate * C.PILOT_BAND_FACTOR_PPM[rated_pilot_band], C.FULL_PPM)
    if rate < C.MIN_RATE_PPM:
        rate = C.MIN_RATE_PPM
    if rate > C.MAX_RATE_PPM:
        rate = C.MAX_RATE_PPM
    return rate


def annual_hull_premium(agreed_value_cents, rate_ppm, policy_type, live_schedule_count):
    """Gross annual premium, less the separately-rounded 5% fleet credit when earned."""
    gross = util.ifloor(agreed_value_cents * rate_ppm, C.FULL_PPM)
    if policy_type == "FLEET" and live_schedule_count >= C.FLEET_CREDIT_MIN_SCHEDULES:
        credit = util.ifloor(gross * C.FLEET_CREDIT_PPM, C.FULL_PPM)
        return gross - credit
    return gross


# --- endorsement pricing ------------------------------------------------------

def pro_rata_up(annual_cents, unexpired_days, term_days):
    return util.iceil(annual_cents * unexpired_days, term_days)


def short_rate_return(hull_premium_cents, unexpired_days, term_days):
    """Nested double floor: pro-rata first, then the 90% short-rate factor."""
    unearned = util.ifloor(hull_premium_cents * unexpired_days, term_days)
    return util.ifloor(unearned * C.SHORT_RATE_RETURN_PPM, C.FULL_PPM)


def exposure_base_annual(exposure_type, member_count, per_seat_limit_cents):
    product = member_count * per_seat_limit_cents
    return util.ifloor(product * C.EXPOSURE_RATE_PPM[exposure_type], C.FULL_PPM)


# --- fleet declarations -------------------------------------------------------

def declaration_line(hull_premium_cents, schedule_from, policy_to, term_days):
    days = util.day_diff(schedule_from, policy_to)
    return util.iceil(hull_premium_cents * days, term_days)


def late_loading(lines_total_cents):
    return util.iceil(lines_total_cents * C.LATE_LOADING_PPM, C.FULL_PPM)


# --- war risk -----------------------------------------------------------------

def war_risk_premium(war_hull_line_cents, perils_scope, territorial_limit_code):
    """Floor on the perils step, then round up on the territory step."""
    base = util.ifloor(war_hull_line_cents * C.PERILS_RATE_PPM[perils_scope], C.FULL_PPM)
    return util.iceil(base * C.TERRITORY_FACTOR_PPM[territorial_limit_code], C.FULL_PPM)


# --- claims -------------------------------------------------------------------

def ctl_ratio_ppm(repair_cost_estimate_cents, agreed_value_cents):
    return util.ifloor(repair_cost_estimate_cents * C.FULL_PPM, agreed_value_cents)


def deductible_on_gross(gross_cents, hull_deductible_ppm):
    deductible = util.ifloor(gross_cents * hull_deductible_ppm, C.FULL_PPM)
    if deductible < C.MIN_DEDUCTIBLE_CENTS:
        deductible = C.MIN_DEDUCTIBLE_CENTS
    return deductible


def settlement_return(hull_premium_cents, loss_date, policy_to, term_days):
    """Unearned hull premium on a total loss: no short-rate penalty applies."""
    days = util.day_diff(loss_date, policy_to)
    return util.ifloor(hull_premium_cents * days, term_days)
