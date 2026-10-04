"""Calculation rules (PRD 3.3, 3.5, 3.8, 3.9): risk quotients, amendment
timelines, renewal fees, existing-stocks deadlines, registration numbers."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants
from db import store


def _dec(value):
    """JSON number -> exact Decimal via its shortest repr."""
    return Decimal(str(value))


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _product_tolerances(product_id, statuses):
    return [
        t
        for t in store["tolerances"].values()
        if t["product_id"] == product_id and t["status"] in statuses
    ]


def _product_use_sites(product_id, statuses):
    return [
        s
        for s in store["use_sites"].values()
        if s["product_id"] == product_id and s["status"] in statuses
    ]


def compute_risk(product, application, tier, pct_crop_treated):
    """Dietary/occupational/ecological quotients + level of concern (PRD 3.3).

    Rounding order pinned: per-commodity terms to 4 dp, sum, then 3 dp;
    quotients 3 dp; LOC compares the ROUNDED stored values.
    """
    ai = store["active_ingredients"][product["active_ingredient_id"]]
    rfd = _dec(ai["reference_dose_mg_kg_day"])
    lc50 = _dec(ai["aquatic_lc50_ppm"])

    # --- Dietary ---
    tolerances = _product_tolerances(product["id"], ("PROPOSED", "ESTABLISHED"))
    terms = []
    for tol in tolerances:
        commodity = tol["commodity_code"]
        consumption = constants.CONSUMPTION_G_DAY[commodity]
        if tier == "REFINED":
            studies = [
                s
                for s in store["studies"].values()
                if s.get("application_id") == application["id"]
                and s["study_type"] == "RESIDUE_CHEMISTRY"
                and s["status"] == "ACCEPTED"
                and s.get("commodity_code") == commodity
            ]
            if studies:
                residues = [_dec(s["field_trial_residue_ppm"]) for s in studies]
                mean_residue = round_half_up(sum(residues) / Decimal(len(residues)), 4)
                term = round_half_up(
                    mean_residue * consumption * _dec(pct_crop_treated), 4
                )
            else:
                term = round_half_up(_dec(tol["tolerance_ppm"]) * consumption, 4)
        else:
            term = round_half_up(_dec(tol["tolerance_ppm"]) * consumption, 4)
        terms.append(term)
    if terms:
        dietary_exposure = round_half_up(sum(terms), 3)
    else:
        dietary_exposure = Decimal("0.000")
    dietary_rq = round_half_up(dietary_exposure / (rfd * constants.BODY_WEIGHT_KG), 3)

    # --- Occupational (identical across tiers) ---
    sites = _product_use_sites(product["id"], ("PROPOSED", "ACTIVE"))
    if sites:
        max_rate = max(_dec(s["max_application_rate_lbs_acre"]) for s in sites)
    else:
        max_rate = Decimal("0")
    occupational_rq = round_half_up(
        max_rate * constants.OCC_EXPOSURE_FACTOR / (rfd * constants.BODY_WEIGHT_KG), 3
    )

    # --- Ecological (identical across tiers) ---
    if sites:
        eec = max(
            _dec(s["max_application_rate_lbs_acre"])
            * constants.RUNOFF_FACTOR[s["application_method"]]
            for s in sites
        )
    else:
        eec = Decimal("0")
    ecological_rq = round_half_up(eec / lc50, 3)

    loc_exceeded = (
        dietary_rq >= constants.LOC_DIETARY
        or occupational_rq >= constants.LOC_OCCUPATIONAL
        or ecological_rq >= constants.LOC_ECOLOGICAL
    )

    return {
        "dietary_exposure_mg_day": dietary_exposure,
        "dietary_rq": dietary_rq,
        "occupational_rq": occupational_rq,
        "ecological_rq": ecological_rq,
        "level_of_concern_exceeded": loc_exceeded,
    }


def amendment_review_days(amendment_type, payload, product):
    """Statutory amendment review timeline in whole days (PRD 3.5).

    Returns (total_days, halved) where halved marks the expedited METHOD_CHANGE.
    """
    total = constants.AMENDMENT_BASE_DAYS[amendment_type]
    if product["classification"] == "RESTRICTED_USE":
        total += constants.RUP_ADDER_DAYS
    if amendment_type == "NEW_USE" and payload.get("tolerance_ppm") is not None:
        total += constants.NEW_FOOD_USE_ADDER_DAYS
    has_bulletin = any(
        b["product_id"] == product["id"] and b["status"] == "IN_EFFECT"
        for b in store["bulletins"].values()
    )
    if has_bulletin:
        total += constants.BULLETIN_ADDER_DAYS
    halved = amendment_type == "METHOD_CHANGE" and payload.get("expedited") is True
    if halved:
        total = math.ceil(total / 2)
    return total, halved


def renewal_fee_cents(state_registration, now):
    """Fee due at renewal (PRD 3.9): subtotal + 10%/month-overdue late penalty.

    months_overdue = 0 when clock <= renewal_due_at, else floor(days/30) + 1.
    The due date is an input here and is advanced only AFTER the fee is fixed.
    """
    due = state_registration["renewal_due_at"]
    if now <= due:
        months_overdue = 0
    else:
        months_overdue = (now - due).days // 30 + 1
    subtotal = state_registration["annual_fee_cents"]
    penalty = round_half_up(
        Decimal(subtotal) * constants.LATE_MONTHLY_RATE * Decimal(months_overdue), 0
    )
    return int(subtotal) + int(penalty)


def existing_stocks_deadlines(effective_at, stocks_method, authorized_units, depletion_rate):
    """allow_sale_until / allow_use_until per stocks_method (PRD 3.8)."""
    if stocks_method == "FIXED":
        sale_days = constants.FIXED_SALE_DAYS
        use_days = constants.FIXED_USE_DAYS
    else:  # DEPLETION
        sale_days = math.ceil(authorized_units / depletion_rate * 30)
        use_days = 2 * sale_days
    return (
        effective_at + timedelta(days=sale_days),
        effective_at + timedelta(days=use_days),
    )


def mint_registration_number(exclude_application_id=None):
    """'EPA-RR-' + zero-padded 6-digit (count of previously APPROVED
    applications + 1). The application being approved is not 'previously'
    approved, so it is excluded from the count."""
    approved = sum(
        1
        for a in store["applications"].values()
        if a["status"] == "APPROVED" and a["id"] != exclude_application_id
    )
    return "EPA-RR-" + str(approved + 1).zfill(6)


def bulletin_month_set(start_month, end_month):
    """Closed wrap-around month set: 11 -> 2 means {11, 12, 1, 2} (PRD 3.6)."""
    months = set()
    month = start_month
    while True:
        months.add(month)
        if month == end_month:
            break
        month = month % 12 + 1
    return months
