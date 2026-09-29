"""Every derived figure in the system (PRD 2.7, 2.8 and section 3).

Rounding is half-up to two decimal places unless a rule says otherwise, it
happens once at the point the specification names, and where a rule aggregates
per-test figures each per-test figure is rounded before the aggregate.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from store import db, rows

TWO_PLACES = Decimal("0.01")
ONE_PLACE = Decimal("0.1")

# PRD 3.4: the four monitoring channels and their action limits.
MONITORING_LIMITS = {
    "VIABLE_AIR": Decimal("10.0"),
    "SURFACE": Decimal("5.0"),
    "NONVIABLE_PARTICLE": Decimal("3520.0"),
    "BIOBURDEN_BULK": Decimal("10.0"),
}

# PRD 3.1: weights of the weighted acceptance score.
ACCEPTANCE_WEIGHTS = {
    "POTENCY": Decimal("0.45"),
    "PURITY": Decimal("0.30"),
    "ENDOTOXIN": Decimal("0.15"),
    "IDENTITY": Decimal("0.10"),
}
POTENCY_TOLERANCE = Decimal("5.0")

# PRD 3.6: reference temperature of the accelerated model.
REFERENCE_TEMPERATURE = {
    "TWO_TO_EIGHT_C": Decimal("5.0"),
    "MINUS_TWENTY_C": Decimal("-20.0"),
}

STABILITY_RECOVERY_FLOOR = Decimal("90.00")
WEIGHTED_SCORE_FLOOR = Decimal("85.00")
BRIDGING_MEAN_LIMIT = Decimal("3.00")
BRIDGING_MAX_LIMIT = Decimal("5.00")
COLD_CHAIN_TEMP_LIMIT = Decimal("15.0")
COLD_CHAIN_MINUTES_LIMIT = Decimal("240")
SECONDS_PER_DAY = 86400


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=2):
    """Round half-up to `places` decimal places."""
    if value is None:
        return None
    quantum = TWO_PLACES if places == 2 else Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Measurement selection
# ---------------------------------------------------------------------------

def _latest_key(record):
    return (record["performed_at"], record["created_at"], record["_seq"])


def material_results(material_lot_id):
    return [r for r in rows(db.test_results)
            if r["subject_type"] == "MATERIAL_LOT"
            and r["material_lot_id"] == material_lot_id]


def reagent_results(reagent_lot_id):
    return [r for r in rows(db.test_results)
            if r["subject_type"] == "REAGENT_LOT"
            and r["reagent_lot_id"] == reagent_lot_id]


def stability_results(stability_study_id):
    return [r for r in rows(db.test_results)
            if r["subject_type"] == "STABILITY_TIMEPOINT"
            and r["stability_study_id"] == stability_study_id]


def latest_by_code(records, code):
    """The single latest measurement bearing `code`, ranked by performed_at
    descending and then created_at descending."""
    matching = [r for r in records if r["test_code"] == code]
    if not matching:
        return None
    return sorted(matching, key=_latest_key, reverse=True)[0]


# ---------------------------------------------------------------------------
# PRD 3.1 - raw material acceptance
# ---------------------------------------------------------------------------

def material_outcome(spec, test_code, measured_value):
    """PASS or FAIL against the specification bound governing test_code; every
    bound is inclusive."""
    value = dec(measured_value)
    if test_code == "POTENCY":
        return "PASS" if (value >= spec["potency_min_pct"]
                          and value <= spec["potency_max_pct"]) else "FAIL"
    if test_code == "PURITY":
        return "PASS" if value >= spec["purity_min_pct"] else "FAIL"
    if test_code == "ENDOTOXIN":
        return "PASS" if value <= spec["endotoxin_max_eu_per_ml"] else "FAIL"
    if test_code == "IDENTITY":
        return "PASS" if value >= Decimal("1.0") else "FAIL"
    return "FAIL"


def _sub_score(spec, test_code, measured_value):
    value = dec(measured_value)
    if test_code == "POTENCY":
        low = dec(spec["potency_min_pct"])
        high = dec(spec["potency_max_pct"])
        if low <= value <= high:
            return Decimal(1)
        distance = (low - value) if value < low else (value - high)
        return max(Decimal(0), Decimal(1) - (distance / POTENCY_TOLERANCE))
    if test_code == "PURITY":
        return min(Decimal(1), value / Decimal(100))
    if test_code == "ENDOTOXIN":
        return max(Decimal(0), Decimal(1) - (value / dec(spec["endotoxin_max_eu_per_ml"])))
    if test_code == "IDENTITY":
        return Decimal(1) if value >= Decimal("1.0") else Decimal(0)
    return Decimal(0)


def acceptance_score(spec, material_lot_id):
    """Returns (score, any_zero_subscore).  Sub-scores are never rounded; only
    the final percentage is.  The denominator counts present codes only."""
    records = material_results(material_lot_id)
    numerator = Decimal(0)
    denominator = Decimal(0)
    any_zero = False
    for code in spec["required_test_codes"]:
        latest = latest_by_code(records, code)
        if latest is None:
            continue
        weight = ACCEPTANCE_WEIGHTS.get(code, Decimal(0))
        sub = _sub_score(spec, code, latest["measured_value"])
        if sub == 0:
            any_zero = True
        numerator += sub * weight
        denominator += weight
    if denominator == 0:
        return None, any_zero
    return rhu(numerator / denominator * Decimal(100), 2), any_zero


def acceptance_verdict(spec, lot):
    """ACCEPT or REJECT over the latest-per-code measurement set (PRD 3.1)."""
    records = material_results(lot["id"])
    if spec["acceptance_mode"] == "ALL_PASS":
        for code in spec["required_test_codes"]:
            latest = latest_by_code(records, code)
            if latest is None or latest["outcome"] != "PASS":
                return "REJECT"
        return "ACCEPT"
    score, any_zero = acceptance_score(spec, lot["id"])
    if score is None or any_zero:
        return "REJECT"
    return "ACCEPT" if score >= WEIGHTED_SCORE_FLOOR else "REJECT"


def every_required_code_measured(spec, material_lot_id):
    records = material_results(material_lot_id)
    for code in spec["required_test_codes"]:
        if latest_by_code(records, code) is None:
            return False
    return True


# ---------------------------------------------------------------------------
# PRD 3.5 - release testing against the reference material
# ---------------------------------------------------------------------------

def bias_pct(measured_value, reference_measured_value):
    measured = dec(measured_value)
    reference = dec(reference_measured_value)
    return rhu(abs(measured - reference) / reference * Decimal(100), 2)


def release_bias_rollups(product, reagent_lot_id):
    """Returns (release_bias_max_pct, release_bias_sum_pct).  Each per-test bias
    is already rounded; the aggregate is never re-rounded."""
    records = reagent_results(reagent_lot_id)
    biases = []
    for code in product["release_test_codes"]:
        latest = latest_by_code(records, code)
        if latest is None:
            continue
        biases.append(dec(latest["bias_pct"]))
    if not biases:
        return None, Decimal("0.00")
    total = Decimal(0)
    for value in biases:
        total += value
    return max(biases), total


def release_tests_all_pass(product, reagent_lot_id):
    """Every code in release_test_codes has a measurement on the lot whose
    outcome is PASS."""
    records = reagent_results(reagent_lot_id)
    for code in product["release_test_codes"]:
        if not any(r["test_code"] == code and r["outcome"] == "PASS" for r in records):
            return False
    return True


# ---------------------------------------------------------------------------
# PRD 3.4 - environmental monitoring
# ---------------------------------------------------------------------------

def sample_derivations(sample_type, result_value):
    """Returns (limit_value, excursion, excursion_grade)."""
    limit = MONITORING_LIMITS[sample_type]
    value = dec(result_value)
    excursion = value > limit
    if value >= (limit * 2):
        grade = "MAJOR"
    elif excursion:
        grade = "MINOR"
    else:
        grade = "NONE"
    return limit, excursion, grade


def environmental_state(minor_count, major_count):
    if major_count >= 1 or minor_count >= 3:
        return "DISQUALIFIED"
    if minor_count >= 1:
        return "EXCURSION"
    return "CONFORMING"


def run_samples(fill_run_id):
    return [s for s in rows(db.monitoring_samples) if s["fill_run_id"] == fill_run_id]


def lot_runs(reagent_lot_id):
    return [r for r in rows(db.fill_runs) if r["reagent_lot_id"] == reagent_lot_id]


# ---------------------------------------------------------------------------
# PRD 3.2 - design control
# ---------------------------------------------------------------------------

def design_trace_complete(product_specification_id):
    records = [r for r in rows(db.design_control_records)
               if r["product_specification_id"] == product_specification_id
               and r["status"] == "APPROVED"]
    has_verification = any(r["record_type"] == "VERIFICATION" and r["trace_depth"] == 3
                           for r in records)
    has_validation = any(r["record_type"] == "VALIDATION" and r["trace_depth"] == 3
                         for r in records)
    return has_verification and has_validation


# ---------------------------------------------------------------------------
# PRD 3.7 - bridging
# ---------------------------------------------------------------------------

def lot_components(reagent_lot_id, status=None):
    result = [c for c in rows(db.lot_components) if c["reagent_lot_id"] == reagent_lot_id]
    if status is not None:
        result = [c for c in result if c["status"] == status]
    return result


def predicate_lot(lot):
    """The most recently released other lot of the same product."""
    candidates = [l for l in rows(db.reagent_lots)
                  if l["product_specification_id"] == lot["product_specification_id"]
                  and l["id"] != lot["id"]
                  and l["disposition_status"] == "RELEASED"]
    if not candidates:
        return None
    candidates.sort(key=lambda l: (l["released_at"], l["created_at"], l["_seq"]),
                    reverse=True)
    return candidates[0]


def bridging_required(lot):
    predicate = predicate_lot(lot)
    if predicate is None:
        return False
    predicate_rows = lot_components(predicate["id"], "CONSUMED")
    for component in lot_components(lot["id"], "CONSUMED"):
        material_lot = db.material_lots.get(component["material_lot_id"])
        if material_lot is None:
            continue
        spec = db.material_specifications.get(material_lot["material_specification_id"])
        if spec is None or not spec["is_critical"]:
            continue
        counterparts = [c for c in predicate_rows
                        if c["component_role"] == component["component_role"]]
        if not counterparts:
            return True
        if any(c["vendor_lot_code_snapshot"] != component["vendor_lot_code_snapshot"]
               for c in counterparts):
            return True
    return False


def bridging_equivalence(study):
    """Returns (mean_bias_pct, max_bias_pct, equivalence_verdict)."""
    predicate_records = reagent_results(study["predicate_lot_id"])
    candidate_records = reagent_results(study["candidate_lot_id"])
    biases = []
    for code in study["paired_test_codes"]:
        predicate = latest_by_code(predicate_records, code)
        candidate = latest_by_code(candidate_records, code)
        if predicate is None or candidate is None:
            return None, None, "PENDING"
        predicate_value = dec(predicate["measured_value"])
        candidate_value = dec(candidate["measured_value"])
        biases.append(rhu(abs(candidate_value - predicate_value)
                          / predicate_value * Decimal(100), 2))
    if not biases:
        return None, None, "PENDING"
    total = Decimal(0)
    for value in biases:
        total += value
    max_bias = max(biases)
    mean_bias = rhu(total / Decimal(len(biases)), 2)
    if mean_bias <= BRIDGING_MEAN_LIMIT and max_bias <= BRIDGING_MAX_LIMIT:
        verdict = "EQUIVALENT"
    else:
        verdict = "NOT_EQUIVALENT"
    return mean_bias, max_bias, verdict


# ---------------------------------------------------------------------------
# PRD 3.6 - stability
# ---------------------------------------------------------------------------

def recovery_pct(measured_value, baseline_value):
    return rhu(dec(measured_value) / dec(baseline_value) * Decimal(100), 2)


def last_conforming_month(study):
    records = stability_results(study["id"])
    conforming_months = set()
    for record in records:
        if record["recovery_pct"] is not None and \
                dec(record["recovery_pct"]) >= STABILITY_RECOVERY_FLOOR:
            conforming_months.add(record["month_index"])
    answer = None
    for month in study["planned_timepoints_months"]:
        if month in conforming_months:
            answer = month
        else:
            break
    return answer


def established_shelf_life(study, product):
    """Returns (established_shelf_life_months, shelf_life_method)."""
    claim = product["shelf_life_months_claim"]
    months = study["last_conforming_month"]
    if study["study_type"] == "REAL_TIME":
        return min(months, claim), "REAL_TIME_LAST_CONFORMING"
    reference = REFERENCE_TEMPERATURE[product["storage_condition"]]
    exponent = (dec(study["storage_temp_c"]) - reference) / Decimal(10)
    factor = Decimal(str(2.0 ** float(exponent)))
    extrapolated = dec(months) * factor
    floored = int(math.floor(float(extrapolated) + 1e-9))
    return min(floored, claim), "ACCELERATED_Q10"


# ---------------------------------------------------------------------------
# PRD 3.9 - distribution
# ---------------------------------------------------------------------------

def remaining_shelf_life_days(lot, clock):
    if lot["expiry_date"] is None:
        return None
    seconds = (lot["expiry_date"] - clock).total_seconds()
    return int(math.floor(seconds / SECONDS_PER_DAY))


def cold_chain_verdict(cumulative_minutes, max_temp):
    """Both comparisons are strictly greater-than (PRD 3.9)."""
    if max_temp is not None and dec(max_temp) > COLD_CHAIN_TEMP_LIMIT:
        return "EXCURSION_REJECTED"
    if dec(cumulative_minutes) > COLD_CHAIN_MINUTES_LIMIT:
        return "EXCURSION_REJECTED"
    if dec(cumulative_minutes) > 0:
        return "EXCURSION_ACCEPTABLE"
    return "INTACT"


def allocation_rows(distribution_order_id=None, reagent_lot_id=None):
    result = rows(db.allocations)
    if distribution_order_id is not None:
        result = [a for a in result
                  if a["distribution_order_id"] == distribution_order_id]
    if reagent_lot_id is not None:
        result = [a for a in result if a["reagent_lot_id"] == reagent_lot_id]
    return result


# ---------------------------------------------------------------------------
# PRD 3.8 - complaints
# ---------------------------------------------------------------------------

def complaint_reportable(malfunction_suspected, device_related_death_or_injury, severity):
    if not malfunction_suspected:
        return False
    return bool(device_related_death_or_injury) or severity == "HIGH"
