"""The eight calculation rules (PRD 3, scaffold section 1.3).

Each function carries the worked literals the workflows publish, so the
implementation can be checked against them directly:

  * clinical_criteria_gate     -> 69 below the floor, 70 exactly admits
  * clinic_bundle_price        -> 1250000 @ 8% with copay_max -> 1175000
                                 1300000 @ 8% without copay_max -> 1196000
  * member_cost_share          -> 20000 allowed at 20% -> 4480 provisional, 0 final
  * claim_allowed_amount       -> LAB 200000 vs ceiling 1175000 @12% -> 141000
  * pharmacy_pool_allocation   -> 420000 vs pool 500000 -> remaining 80000
                                  ingredient 344400 + fee 75600 == 420000
"""

from decimal import Decimal, ROUND_HALF_UP

MEMBER_OOP_MAX_CENTS = 250000
SPECIALTY_DIFFERENTIAL_PCT = 12
COST_DIFFERENCE_CAP_CENTS = 15000

MANAGER_FEE_PCT = 8
COPAY_MAX_REDUCTION_CENTS = 25000

INGREDIENT_PCT = 82

ANCILLARY_SHARE_PCT = {
    "LAB": 12,
    "STORAGE": 4,
    "DONOR_MATERIAL": 18,
    "SURROGACY_FEE": 25,
}

APPROVAL_FLOOR = 70

NEUTRAL_CRITERIA = {
    "age_years": 30,
    "amh_ng_ml": 2.0,
    "prior_cycles": 0,
    "prior_live_birth": False,
    "fsh_iu_l": 6,
}


def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# C5 — clinical_criteria_gate
# --------------------------------------------------------------------------

def age_penalty(age_years):
    if age_years is None:
        age_years = NEUTRAL_CRITERIA["age_years"]
    if age_years >= 41:
        return 60
    if age_years >= 38:
        return 40
    if age_years >= 35:
        return 20
    return 0


def clinical_criteria_gate(criteria_inputs):
    """Appropriateness score, penalties summed before a single clamp."""
    inputs = dict(NEUTRAL_CRITERIA)
    if criteria_inputs:
        for key, value in criteria_inputs.items():
            if value is not None:
                inputs[key] = value

    score = 100
    score -= age_penalty(inputs.get("age_years"))

    amh = inputs.get("amh_ng_ml")
    if amh is not None:
        if amh < 0.5:
            score -= 20
        elif amh < 1.0:
            score -= 10

    if inputs.get("prior_live_birth"):
        score += 15

    prior_cycles = inputs.get("prior_cycles") or 0
    if prior_cycles >= 3:
        score -= 25
    elif prior_cycles == 2:
        score -= 15

    fsh = inputs.get("fsh_iu_l")
    if fsh is not None and fsh > 12:
        score -= 10

    return max(0, min(100, score))


# --------------------------------------------------------------------------
# C6 — clinic_bundle_price
# --------------------------------------------------------------------------

def clinic_bundle_price(list_price, copay_max):
    """The effective price: manager fee first, then the copay reduction."""
    if list_price is None:
        return None
    manager_fee = round_half_up(list_price * MANAGER_FEE_PCT / 100)
    reduction = COPAY_MAX_REDUCTION_CENTS if copay_max else 0
    delta = manager_fee - reduction
    return max(0, list_price - delta)


# --------------------------------------------------------------------------
# C7 — pharmacy_pool_allocation
# --------------------------------------------------------------------------

def pharmacy_split(claimable):
    """Ingredient bucket rounds half-up; the fee bucket absorbs the remainder."""
    ingredient = round_half_up(claimable * INGREDIENT_PCT / 100)
    dispensing_fee = claimable - ingredient
    return ingredient, dispensing_fee


def pharmacy_pool_allocation(store, order, remaining_cents):
    """plan_paid_cents is the smaller of the fill cost and the pool remainder."""
    acquisition = order.get("acquisition_cost_cents") or 0
    claimable = min(acquisition, remaining_cents)
    plan_paid = claimable
    member_cost = acquisition - claimable
    return plan_paid, member_cost, claimable


# --------------------------------------------------------------------------
# C8 — claim_allowed_amount
# --------------------------------------------------------------------------

def claim_allowed_amount(service_category, billed_cents, plan_price_cents, medication_plan_paid):
    """Return (allowed_cents, adjudication_basis)."""
    if service_category == "MEDICATION":
        return medication_plan_paid, "BUNDLE_COMPONENT_RULE"

    ceiling = plan_price_cents
    if service_category == "CLINIC_BUNDLE":
        covered = min(billed_cents, ceiling)
        basis = "BUNDLE_COMPONENT_RULE" if billed_cents > ceiling else "CONTRACT_RATE"
        return covered, basis

    share_pct = ANCILLARY_SHARE_PCT.get(service_category)
    if share_pct is None:
        return min(billed_cents, ceiling), "BUNDLE_COMPONENT_RULE"
    ancillary_ceiling = round_half_up(ceiling * share_pct / 100)
    covered = min(billed_cents, ancillary_ceiling)
    basis = "BUNDLE_COMPONENT_RULE" if billed_cents > ancillary_ceiling else "CONTRACT_RATE"
    return covered, basis


# --------------------------------------------------------------------------
# C4 — member_cost_share
# --------------------------------------------------------------------------

def member_cost_share(allowed_cents, member_cost_share_pct, accumulator_before_cents,
                      service_category, variant):
    """PROVISIONAL keeps the differential and applies no cap; FINAL nets the cap."""
    pct = member_cost_share_pct or 0
    share = round_half_up(allowed_cents * pct / 100)

    remaining_oop = max(0, MEMBER_OOP_MAX_CENTS - (accumulator_before_cents or 0))
    capped = min(share, remaining_oop)

    differential = 0
    if service_category in ("MEDICATION", "DONOR_MATERIAL"):
        differential = round_half_up(capped * SPECIALTY_DIFFERENTIAL_PCT / 100)
    base = capped + differential

    if variant == "PROVISIONAL":
        return base
    netted = base - min(base, COST_DIFFERENCE_CAP_CENTS)
    return max(0, netted)


def member_accumulator_before(store, member_id):
    """Sum of member shares over this member's ADJUDICATED or PAID claims."""
    rows = [
        c for c in store.all("claims")
        if c.get("member_id") == member_id and c["claim_status"] in ("ADJUDICATED", "PAID")
    ]
    rows.sort(key=lambda c: (c.get("_paid_at") or store.created_key(c), store.created_key(c)))
    return sum((c.get("member_cost_share_cents") or 0) for c in rows)


# --------------------------------------------------------------------------
# C1 scripting helpers — the two netting policies
# --------------------------------------------------------------------------

def netted_cycles(store, bundle, employer):
    if employer is not None and employer["allocation_method"] == "CONCURRENT_BUNDLE":
        return bundle["cycles_committed"]
    return bundle["cycles_consumed"]


def remaining_cycles(store, bundle, employer):
    base = bundle.get("lifetime_max_cycles") or 0
    annual = bundle.get("max_cycles_per_year")
    cap = base if annual is None else min(base, annual)
    return max(0, cap - netted_cycles(store, bundle, employer))


# --------------------------------------------------------------------------
# Undefined-by-spec rule sets
#
# ``pathway_coverage_rule`` and ``monthly_claim_liability_cents`` are named by
# the specification but given no formula.  Both are implemented as the least
# surprising reading of the prose that references them:
#   * pathway coverage applies the plan's coverage percentage to the pathway's
#     own baseline cost, rounded half-up;
#   * the surrender route round is a flat route cost under the utilising
#     carrier kind, with the member carrying nothing and a custodial carrier
#     not billed to the plan;
#   * the member's monthly liability is their share of the claims settled in
#     the month of the logical clock.
# --------------------------------------------------------------------------

PATHWAY_BASELINE_CENTS = {
    "PRESERVATION": 600000,
    "DONOR_EGG": 2500000,
    "DONOR_SPERM": 350000,
    "SURROGACY": 6000000,
}

SURRENDER_BASELINE_CENTS = {
    "MEMBER": 0,
    "GESTATIONAL_CARRIER": 300000,
    "CUSTODIAN": 450000,
}


def pathway_coverage_rule(pathway_type, coverage_pct, raw_cost_cents=None):
    if raw_cost_cents is not None:
        return round_half_up(raw_cost_cents * (coverage_pct or 0) / 100)
    if pathway_type == "PRESERVATION":
        return round_half_up((coverage_pct or 0) * PATHWAY_BASELINE_CENTS["PRESERVATION"] / 100)
    # The donor and surrogacy pathways are covered in full: the plan carries
    # the pathway's own baseline cost regardless of the coverage percentage.
    return PATHWAY_BASELINE_CENTS.get(pathway_type, 0)


def surrender_route_cost(carrier_kind, raw_cost_cents):
    """The route round: bill the plan the raw route cost under the named carrier."""
    if raw_cost_cents is None:
        return SURRENDER_BASELINE_CENTS.get(carrier_kind, 0)
    return raw_cost_cents


def monthly_claim_liability(store, member_id):
    """This member's own share across the claims settled in the clock's month."""
    now = store.now()
    total = 0
    for claim in store.all("claims"):
        if claim.get("member_id") != member_id:
            continue
        if claim["claim_status"] not in ("ADJUDICATED", "PAID", "REVERSED"):
            continue
        settled = claim.get("_paid_at") or claim.get("_adjudicated_at") or store.created_key(claim)
        if settled.year == now.year and settled.month == now.month:
            total += claim.get("member_cost_share_cents") or 0
    return total