"""Every derived figure in the PRD, at the scale the PRD assigns it.

PRD 2.9: "every rounding operation in this specification rounds half up. Where a
value is described as floored or ceilinged, that is stated explicitly and half-up
rounding does not apply."
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import constants as K

Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")
Q0 = Decimal("1")


def q(value, exponent):
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def q2(value):
    return q(value, Q2)


def q3(value):
    return q(value, Q3)


def q4(value):
    return q(value, Q4)


def round_int(value):
    return int(Decimal(value).quantize(Q0, rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(Decimal(value).quantize(Q0, rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(Decimal(value).quantize(Q0, rounding=ROUND_CEILING))


# --- lot biomass ------------------------------------------------------------

def to_lbs(count, grams_each):
    """count * grams / 453.592, two decimal places."""
    return q2(Decimal(count) * Decimal(grams_each) / K.GRAMS_PER_LB)


def lot_biomass_lbs(lot):
    return to_lbs(lot["count_on_hand"], lot["avg_weight_g"])


# --- station meters ---------------------------------------------------------

def density_index(biomass_on_hand_lbs, rearing_capacity_lbs):
    capacity = Decimal(rearing_capacity_lbs)
    if capacity <= 0:
        return q4(0)
    return q4(Decimal(biomass_on_hand_lbs) / capacity)


def operating_posture(exceedance_count_rolling, water_available_af, density):
    """Worst-first, so a frozen station never reads as merely restricted."""
    if exceedance_count_rolling >= K.EXCEEDANCE_FREEZE_COUNT or Decimal(water_available_af) <= 0:
        return "FROZEN"
    if exceedance_count_rolling == 1 or Decimal(density) >= K.DENSITY_RESTRICT_THRESHOLD:
        return "RESTRICTED"
    return "OPEN"


# --- feed conversion --------------------------------------------------------

def feed_conversion(cumulative_feed_lbs, biomass_lbs, initial_biomass_lbs,
                    cumulative_mortality_biomass_lbs):
    """Both variants, always; each is null while its denominator is <= 0."""
    feed = Decimal(cumulative_feed_lbs)
    biological_denominator = Decimal(biomass_lbs) - Decimal(initial_biomass_lbs)
    economic_denominator = (Decimal(biomass_lbs) + Decimal(cumulative_mortality_biomass_lbs)
                            - Decimal(initial_biomass_lbs))
    biological = q3(feed / biological_denominator) if biological_denominator > 0 else None
    economic = q3(feed / economic_denominator) if economic_denominator > 0 else None
    return biological, economic


def growth_rate_g_per_day(avg_weight_g_after, avg_weight_g_before, fed_at, previous_at):
    """Null when the span works out to zero whole days."""
    whole_days = int((fed_at - previous_at).total_seconds() / 86400)
    if whole_days == 0:
        return None
    delta = Decimal(avg_weight_g_after) - Decimal(avg_weight_g_before)
    return q4(delta / Decimal(whole_days))


# --- egg take projection ----------------------------------------------------

def density_derate(density):
    value = Decimal(density)
    if value >= K.DENSITY_DERATE_HIGH_FLOOR:
        return K.DENSITY_DERATE_HIGH
    if value >= K.DENSITY_DERATE_MID_FLOOR:
        return K.DENSITY_DERATE_MID
    return K.DENSITY_DERATE_LOW


def cumulative_survival(density):
    chained = (K.EGG_TO_FRY_SURVIVAL * K.FRY_TO_FINGERLING_SURVIVAL
               * K.FINGERLING_TO_RELEASE_SURVIVAL * density_derate(density))
    return q4(chained)


def required_eggs_for_target(target_release_count, survival):
    return ceil_int(Decimal(target_release_count) / survival)


def projected_release_count(planned_eggs, survival):
    return floor_int(Decimal(planned_eggs) * survival)


def water_af_for_eggs(egg_count):
    return q4(Decimal(egg_count) / Decimal(1000) * K.WATER_AF_PER_1000_EGGS)


# --- demand scoring ---------------------------------------------------------

def plan_gap_pct(plan_target_count, released_count_ytd, allocated_count_ytd):
    target = Decimal(plan_target_count)
    if target <= 0:
        return q2(0)
    gap = target - Decimal(released_count_ytd) - Decimal(allocated_count_ytd)
    if gap < 0:
        gap = Decimal(0)
    return q2(gap / target * Decimal(100))


def priority_score(water, species, requester_kind):
    gap_pct = plan_gap_pct(water["plan_target_count"], water["released_count_ytd"],
                           water["allocated_count_ytd"])
    base = (K.W_HABITAT * Decimal(water["habitat_suitability_score"])
            + K.W_DEMAND * Decimal(water["angler_demand_index"])
            + K.W_PLAN_GAP * gap_pct)
    weight = (K.REQUESTER_WEIGHT_BIOLOGIST if requester_kind == "BIOLOGIST"
              else K.REQUESTER_WEIGHT_PUBLIC)
    adjusted = base * weight
    if species == water["plan_species"]:
        adjusted += K.SPECIES_MATCH_BONUS
    if water["access_type"] == "REMOTE":
        adjusted -= K.REMOTE_ACCESS_PENALTY
    if adjusted < 0:
        adjusted = Decimal(0)
    if adjusted > 100:
        adjusted = Decimal(100)
    return q2(adjusted)


def plan_shortfall(plan_target_count, released_count_ytd, allocated_count_ytd):
    shortfall = plan_target_count - released_count_ytd - allocated_count_ytd
    return shortfall if shortfall > 0 else 0


def plan_fill_pct(plan_target_count, released_count_ytd, allocated_count_ytd):
    target = Decimal(plan_target_count)
    if target <= 0:
        return q2(0)
    filled = Decimal(released_count_ytd) + Decimal(allocated_count_ytd)
    return q2(filled / target * Decimal(100))


# --- transport --------------------------------------------------------------

def avg_weight_lbs(avg_weight_g):
    return Decimal(avg_weight_g) / K.GRAMS_PER_LB


def planned_load_lbs(fish_count, avg_weight_g):
    return to_lbs(fish_count, avg_weight_g)


def transport_cost_cents(load_lbs):
    per_pound = ceil_int(Decimal(load_lbs) * K.COST_PER_LB_CENTS)
    return K.TRANSPORT_BASE_CENTS + per_pound


def oxygen_flow_lpm(load_lbs):
    return q3(Decimal(load_lbs) * K.OXYGEN_LPM_PER_LB)


def load_plan(unit, avg_weight_g, load_water_temp_c):
    """The tightest of tank volume, oxygen delivery and the unit's rated load."""
    density = K.TRANSPORT_BASE_DENSITY_LB_PER_GAL
    if Decimal(load_water_temp_c) > K.WARM_WATER_TEMP_C:
        density = density * K.WARM_WATER_DERATE
    volume_limit_lbs = q2(Decimal(unit["tank_gallons"]) * density)
    oxygen_limit_lbs = q2(Decimal(unit["oxygen_lpm"]) / K.OXYGEN_LPM_PER_LB)
    mechanical_limit_lbs = Decimal(unit["max_load_lbs"])
    gross = min(volume_limit_lbs, oxygen_limit_lbs, mechanical_limit_lbs)
    per_fish = avg_weight_lbs(avg_weight_g)
    if per_fish <= 0:
        return None
    return floor_int(gross / per_fish)


def temp_delta_c(site_water_temp_c, load_water_temp_c):
    return q2(abs(Decimal(site_water_temp_c) - Decimal(load_water_temp_c)))


def tempering_minutes_required(delta):
    steps = ceil_int(Decimal(delta) / K.ACCLIM_DEGREE_STEP)
    return steps * K.ACCLIM_MINUTES_PER_STEP


# --- marking and contribution ----------------------------------------------

def effective_marked_count(mark_type, marked_count):
    tag_loss = K.TAG_LOSS.get(mark_type)
    if tag_loss is None:
        return 0
    return round_int(Decimal(marked_count) * (Decimal(1) - tag_loss))


def contribution_indices(recovered_count, effective_marked, released_count, creel_fraction):
    if recovered_count <= 0:
        return None, None
    cohort = None
    if effective_marked and effective_marked > 0:
        cohort = q4(Decimal(recovered_count) / Decimal(effective_marked))
    harvest = None
    if released_count and Decimal(released_count) > 0 and Decimal(creel_fraction) > 0:
        expanded = Decimal(recovered_count) / Decimal(creel_fraction)
        harvest = q4(expanded / Decimal(released_count))
    return cohort, harvest


# --- effluent ---------------------------------------------------------------

def effluent_classification(tss_mg_l, total_phosphorus_mg_l, tss_permit_limit_mg_l):
    exceeded = (Decimal(tss_mg_l) > Decimal(tss_permit_limit_mg_l)
                or Decimal(total_phosphorus_mg_l) > K.TP_LIMIT_MG_L)
    overshoot = Decimal(tss_mg_l) - Decimal(tss_permit_limit_mg_l)
    if overshoot < 0:
        overshoot = Decimal(0)
    return ("EXCEEDANCE" if exceeded else "COMPLIANT"), q3(overshoot)
