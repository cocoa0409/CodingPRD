"""The eleven calculations of PRD 2.6 / 3.x.

All arithmetic is integral: basis points (10000 bps == 100%), whole cents and
millicents (1000 millicents == 1 cent). No floats anywhere; the single
non-truncating rounding (batch cost, half-up) uses decimal.Decimal.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import (ACCEPTED_BATCH_STATUSES, CREDIBILITY_FLOOR_BPS,
                MAX_CURE_PERIODS, MIN_ASSUMED_VALIDITY_BPS,
                PROVISIONAL_OPEN_REFERRAL_PENALTY_BPS, PROVISIONAL_WEIGHT_BPS,
                SUBSTANTIATED_STRIKE_PENALTY_BPS, TIER_A_DISCOUNT_BPS,
                TIER_A_FLOOR_CENTS, TIER_B_DISCOUNT_BPS, TIER_B_FLOOR_CENTS,
                batches_of_circulator, batches_of_petition, county_code_of_batch,
                db, records_of_batch, records_of_petition,
                referrals_of_circulator, rounds_of_petition)


# ---------------------------------------------------------------------------
# integer helpers
# ---------------------------------------------------------------------------
def ceil_div(numerator, denominator):
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)


def floor_div(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator // denominator


def round_half_up(numerator, denominator):
    if denominator == 0:
        return 0
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# 1. required_valid_signature_threshold
# ---------------------------------------------------------------------------
def required_valid_signature_threshold(standard):
    return ceil_div(standard["gubernatorial_vote_total"] * standard["signature_pct_bps"],
                    10000)


# ---------------------------------------------------------------------------
# 2. petition_raw_and_accepted_counts
# ---------------------------------------------------------------------------
def recompute_petition_counts(petition):
    raw = 0
    accepted = 0
    for batch in batches_of_petition(petition["id"]):
        if batch["status"] != "INVALIDATED":
            raw += batch["raw_count"]
        if batch["status"] in ACCEPTED_BATCH_STATUSES:
            accepted += batch["accepted_raw_count"]
    voided = sum(1 for r in records_of_petition(petition["id"])
                 if r["validation_status"] == "VOIDED")
    petition["raw_signature_count"] = raw
    petition["accepted_raw_total"] = accepted
    petition["voided_signature_count"] = voided


def accepted_raw_total_of_county(petition_id, county_id):
    total = 0
    for batch in batches_of_petition(petition_id):
        if batch["county_id"] == county_id and batch["status"] in ACCEPTED_BATCH_STATUSES:
            total += batch["accepted_raw_count"]
    return total


def face_value_valid_count(petition_id):
    """Count of VALID lines sitting in batches that still count."""
    total = 0
    for batch in batches_of_petition(petition_id):
        if batch["status"] not in ACCEPTED_BATCH_STATUSES:
            continue
        for record in records_of_batch(batch["id"]):
            if record["validation_status"] == "VALID":
                total += 1
    return total


# ---------------------------------------------------------------------------
# 3. sample_selection
# ---------------------------------------------------------------------------
def _pool_sort_key(record):
    batch = db.batches[record["batch_id"]]
    return (record["_signed_on_dt"], county_code_of_batch(batch),
            batch["_filed_at_dt"], record["line_number"])


def eligible_pool(petition, round_type):
    pool = []
    for batch in batches_of_petition(petition["id"]):
        if batch["status"] not in ACCEPTED_BATCH_STATUSES:
            continue
        if round_type in ("RANDOM_SAMPLE", "FULL_CHECK") and batch["is_supplemental"]:
            continue
        for record in records_of_batch(batch["id"]):
            if record["validation_status"] == "PENDING" \
                    and record["validated_in_round_id"] is None:
                pool.append(record)
    pool.sort(key=_pool_sort_key)
    return pool


def _draw_size(pool_size, standard, round_type):
    if round_type == "RANDOM_SAMPLE":
        target = max(standard["sample_min_count"],
                     ceil_div(pool_size * standard["sample_pct_bps"], 10000))
        return min(pool_size, target)
    return pool_size


def _systematic(pool, size):
    n = len(pool)
    if size <= 0 or n == 0:
        return []
    interval = n // size
    if interval < 1:
        interval = 1
    return [pool[i * interval] for i in range(size) if i * interval < n]


def select_sample(petition, standard, round_type):
    """Returns (eligible_pool_size, selected records in draw order)."""
    pool = eligible_pool(petition, round_type)
    pool_size = len(pool)
    if standard["stratification_mode"] == "STRATIFIED":
        strata = {}
        for record in pool:
            code = county_code_of_batch(db.batches[record["batch_id"]])
            strata.setdefault(code, []).append(record)
        selected = []
        for code in sorted(strata):
            stratum = strata[code]
            selected.extend(_systematic(stratum,
                                        _draw_size(len(stratum), standard, round_type)))
        return pool_size, selected
    return pool_size, _systematic(pool, _draw_size(pool_size, standard, round_type))


# ---------------------------------------------------------------------------
# 4. sample_projection
# ---------------------------------------------------------------------------
def selected_records(rnd):
    return [db.signature_records[rid] for rid in rnd.get("_selected_ids", [])
            if rid in db.signature_records]


def round_county_stats(rnd):
    """county_code -> {county_id, size, valid} across the round's selected lines."""
    stats = {}
    for record in selected_records(rnd):
        batch = db.batches[record["batch_id"]]
        code = county_code_of_batch(batch)
        entry = stats.setdefault(code, {"county_id": batch["county_id"],
                                        "size": 0, "valid": 0})
        entry["size"] += 1
        if record["validation_status"] == "VALID":
            entry["valid"] += 1
    return stats


def stratum_rate_bps(entry):
    if not entry or entry["size"] == 0:
        return 0
    return floor_div(entry["valid"] * 10000, entry["size"])


def sampled_valid_count(rnd):
    return sum(1 for r in selected_records(rnd) if r["validation_status"] == "VALID")


def validity_rate_bps(rnd):
    if rnd["sample_size"] == 0:
        return 0
    return floor_div(rnd["sampled_valid_count"] * 10000, rnd["sample_size"])


def projection_for_round(rnd, petition, standard):
    if rnd["round_type"] == "RANDOM_SAMPLE":
        if standard["stratification_mode"] == "STRATIFIED":
            total = 0
            stats = round_county_stats(rnd)
            for code in sorted(stats):
                entry = stats[code]
                rate = stratum_rate_bps(entry)
                accepted = accepted_raw_total_of_county(petition["id"], entry["county_id"])
                total += floor_div(accepted * rate, 10000)
            return total
        return floor_div(petition["accepted_raw_total"] * rnd["validity_rate_bps"], 10000)
    return face_value_valid_count(petition["id"])


def latest_closed_round(petition):
    closed = [r for r in rounds_of_petition(petition["id"]) if r["status"] == "CLOSED"]
    if not closed:
        return None
    closed.sort(key=lambda r: (r["round_index"], r["created_at"], r["_seq"]))
    return closed[-1]


def refresh_petition_projection(petition):
    """projected_valid_count / verified_valid_count from the latest closed round."""
    standard = db.standards.get(petition["standard_id"])
    rnd = latest_closed_round(petition)
    if rnd is None or standard is None:
        petition["projected_valid_count"] = 0
        petition["verified_valid_count"] = 0
        return
    if rnd["round_type"] == "RANDOM_SAMPLE":
        petition["projected_valid_count"] = projection_for_round(rnd, petition, standard)
        petition["verified_valid_count"] = 0
    else:
        face = face_value_valid_count(petition["id"])
        petition["projected_valid_count"] = face
        petition["verified_valid_count"] = face


# ---------------------------------------------------------------------------
# 5. sufficiency_band_determination
# ---------------------------------------------------------------------------
def determination_for(rnd, projected, petition, standard):
    required = petition["required_valid_signatures"]
    if rnd["round_type"] == "RANDOM_SAMPLE":
        upper_gate = ceil_div(required * standard["sufficiency_upper_bps"], 10000)
        lower_gate = floor_div(required * standard["sufficiency_lower_bps"], 10000)
        if projected >= upper_gate:
            return "SUFFICIENT"
        if projected <= lower_gate:
            return "INSUFFICIENT"
        return "FULL_CHECK_REQUIRED"
    return "SUFFICIENT" if projected >= required else "INSUFFICIENT"


def cure_eligible(petition, standard, best_valid):
    if not standard.get("cure_allowed"):
        return False
    if petition["cure_period_count"] >= MAX_CURE_PERIODS:
        return False
    return best_valid * 10000 >= petition["required_valid_signatures"] \
        * standard["cure_eligibility_floor_bps"]


# ---------------------------------------------------------------------------
# 6. duplicate_keeper_selection
# ---------------------------------------------------------------------------
def _effective_matched_voter(record):
    """A PENDING line stakes a claim on the voter its number resolves to."""
    if record["matched_voter_record_id"]:
        return record["matched_voter_record_id"]
    for voter in db.voter_records.values():
        if voter["voter_id_number"] == record["claimed_voter_id_number"]:
            return voter["id"]
    return None


def duplicate_keeper(record):
    """The earliest signature staking the same voter; None when unopposed."""
    target = record["matched_voter_record_id"]
    if not target:
        return None
    petition_id = db.batches[record["batch_id"]]["petition_id"]
    candidates = []
    for other in records_of_petition(petition_id):
        batch = db.batches[other["batch_id"]]
        if batch["status"] in ("REJECTED_FORMAT", "INVALIDATED"):
            continue
        if other["validation_status"] not in ("PENDING", "VALID"):
            continue
        if _effective_matched_voter(other) != target:
            continue
        candidates.append(other)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["_signed_on_dt"],
                                   db.batches[r["batch_id"]]["_filed_at_dt"],
                                   r["line_number"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# 7. county_distribution_compliance
# ---------------------------------------------------------------------------
def county_distribution(petition, standard):
    rnd = latest_closed_round(petition)
    stats = round_county_stats(rnd) if rnd else {}
    participating = {}
    for batch in batches_of_petition(petition["id"]):
        if batch["status"] in ACCEPTED_BATCH_STATUSES:
            participating[batch["county_id"]] = True
    entries = []
    for county_id in participating:
        county = db.counties.get(county_id)
        if county is None:
            continue
        minimum = ceil_div(
            county["registered_voter_count"] * standard["county_distribution_pct_bps"],
            10000)
        if rnd is None:
            credited = 0
        elif rnd["round_type"] == "RANDOM_SAMPLE":
            if standard["stratification_mode"] == "STRATIFIED":
                rate = stratum_rate_bps(stats.get(county["county_code"]))
            else:
                rate = rnd["validity_rate_bps"]
            credited = floor_div(
                accepted_raw_total_of_county(petition["id"], county_id) * rate, 10000)
        else:
            credited = 0
            for batch in batches_of_petition(petition["id"]):
                if batch["county_id"] != county_id:
                    continue
                if batch["status"] not in ACCEPTED_BATCH_STATUSES:
                    continue
                credited += sum(1 for r in records_of_batch(batch["id"])
                                if r["validation_status"] == "VALID")
        entries.append({
            "county_code": county["county_code"],
            "distribution_minimum": minimum,
            "credited_count": credited,
            "qualifies": credited >= minimum,
        })
    entries.sort(key=lambda e: e["county_code"])
    return entries


def recompute_qualifying_counties(petition):
    standard = db.standards.get(petition["standard_id"])
    if standard is None:
        return
    entries = county_distribution(petition, standard)
    petition["qualifying_county_count"] = sum(1 for e in entries if e["qualifies"])


# ---------------------------------------------------------------------------
# 8. batch_verification_cost
# ---------------------------------------------------------------------------
def batch_checked_count(batch):
    return sum(1 for r in records_of_batch(batch["id"])
               if r["validation_status"] not in ("PENDING", "INVALID_FORMAT_DEFECT"))


def batch_cost_cents(checked_count, standard):
    return round_half_up(
        checked_count * standard["verification_rate_millicents_per_signature"], 1000)


# ---------------------------------------------------------------------------
# 9. county_reimbursement_invoice
# ---------------------------------------------------------------------------
def verification_invoice(petition, standard):
    gross = 0
    for batch in batches_of_petition(petition["id"]):
        if batch["status"] in ("SAMPLED", "FULLY_CHECKED"):
            gross += batch["verification_cost_cents"]
    if gross >= TIER_B_FLOOR_CENTS:
        tier, discount_bps = "TIER_B", TIER_B_DISCOUNT_BPS
    elif gross >= TIER_A_FLOOR_CENTS:
        tier, discount_bps = "TIER_A", TIER_A_DISCOUNT_BPS
    else:
        tier, discount_bps = "TIER_NONE", 0
    discount = floor_div(gross * discount_bps, 10000)
    subtotal = gross - discount
    surcharge = ceil_div(subtotal * standard["county_surcharge_bps"], 10000)
    return {
        "petition_id": petition["id"],
        "gross_cents": gross,
        "tier": tier,
        "discount_bps": discount_bps,
        "discount_cents": discount,
        "subtotal_cents": subtotal,
        "surcharge_cents": surcharge,
        "total_cents": subtotal + surcharge,
    }


# ---------------------------------------------------------------------------
# 10. cure_target_computation
# ---------------------------------------------------------------------------
def cure_target(petition, rnd):
    if rnd is None:
        best_valid = 0
        rate = 0
    elif rnd["round_type"] == "RANDOM_SAMPLE":
        best_valid = rnd["projected_valid_count"]
        rate = rnd["validity_rate_bps"]
    else:
        best_valid = petition["verified_valid_count"]
        rate = rnd["validity_rate_bps"]
    shortfall = max(0, petition["required_valid_signatures"] - best_valid)
    assumed = min(10000, max(MIN_ASSUMED_VALIDITY_BPS, rate))
    target = ceil_div(shortfall * 10000, assumed)
    return shortfall, assumed, target


def best_valid_for_cure(petition):
    rnd = latest_closed_round(petition)
    if rnd is None:
        return 0
    if rnd["round_type"] == "RANDOM_SAMPLE":
        return rnd["projected_valid_count"]
    return petition["verified_valid_count"]


def supplemental_raw_count(cure_period):
    total = 0
    for batch in batches_of_petition(cure_period["petition_id"]):
        if batch["cure_period_id"] != cure_period["id"]:
            continue
        if batch["status"] in ("REJECTED_FORMAT", "INVALIDATED"):
            continue
        total += batch["raw_count"]
    return total


# ---------------------------------------------------------------------------
# 11. circulator_credibility_score
# ---------------------------------------------------------------------------
def recompute_credibility(circulator):
    checked = 0
    invalid = 0
    for batch in batches_of_circulator(circulator["id"]):
        for record in records_of_batch(batch["id"]):
            if record["validation_status"] == "VOIDED":
                effective = record["status_before_void"]
            else:
                effective = record["validation_status"]
            if not effective or effective in ("PENDING", "INVALID_FORMAT_DEFECT"):
                continue
            checked += 1
            if effective.startswith("INVALID_"):
                invalid += 1
    invalid_rate = 0 if checked == 0 else floor_div(invalid * 10000, checked)
    strikes = circulator["misconduct_strike_count"]
    if strikes == 0:
        open_referrals = sum(1 for r in referrals_of_circulator(circulator["id"])
                             if r["status"] in ("OPENED", "REFERRED_TO_AG"))
        raw = 10000 - floor_div(invalid_rate * PROVISIONAL_WEIGHT_BPS, 10000) \
            - PROVISIONAL_OPEN_REFERRAL_PENALTY_BPS * open_referrals
    else:
        raw = 10000 - floor_div(invalid_rate * 10000, 10000) \
            - SUBSTANTIATED_STRIKE_PENALTY_BPS * strikes
    circulator["credibility_score_bps"] = min(10000, max(CREDIBILITY_FLOOR_BPS, raw))
