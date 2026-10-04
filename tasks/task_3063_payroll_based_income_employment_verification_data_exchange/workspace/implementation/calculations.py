"""Every calculation rule in the exchange."""
from decimal import Decimal, ROUND_HALF_UP

import clock
import domain
import store
from domain import (
    ALWAYS_RENDERED, CADENCE_INTERVAL_DAYS, CONTRIBUTOR_TIER1_RATE, CONTRIBUTOR_TIER2_MIN,
    CONTRIBUTOR_TIER2_RATE, CONTRIBUTOR_TIER3_MIN, CONTRIBUTOR_TIER3_RATE, DISCLOSURE_WINDOW_DAYS,
    DISPUTE_ESCALATION_PENALTY, EMPLOYMENT_STATUS_RANK, FEED_BASE_WEIGHT, FEED_DECAY_PER_DAY,
    FEED_RECENCY_WEIGHT, FEED_RESPONSIVENESS_WEIGHT, FEED_SCORE_CEILING, FEED_SCORE_FLOOR,
    FEED_STALLED_MULTIPLIER, FEED_STALL_PENALTY, MAX_HOURS_PER_WEEK, PERIODS_PER_YEAR,
    REVERSAL_PENALTY, STALL_STRIKE_THRESHOLD, TIER_DEPTH_SURCHARGE, TIER_HISTORY_DEPTH,
    VERIFIER_CONTAGION_FACTOR, VERIFIER_RESTRICT_SCORE, VERIFIER_SCORE_CEILING,
    DISPUTE_RESPONSE_WINDOW_DAYS, DEFAULT_HOURS_PER_WEEK, WEEKS_PER_YEAR,
)
from domain import (
    CANDIDATE_RECORD_STATES, FREEZE_LIVE_STATES, INCLUDED_RECORD_STATES,
    OPEN_DISPUTE_STATES,
)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def clamp(value, low, high):
    return max(low, min(high, value))


# ---------------------------------------------------------------- annualized income

def annualized_income(record, employer):
    """Returns (annualized_income_cents, tenure_months) for one record."""
    if record.get("record_state") == "IMMUTABLE":
        return record.get("annualized_income_cents", 0), record.get("tenure_months", 0)

    basis = record.get("pay_rate_basis")
    rate = Decimal(record.get("pay_rate_cents") or 0)
    if basis == "HOURLY":
        hours = record.get("standard_hours_per_week")
        if hours is None:
            hours = DEFAULT_HOURS_PER_WEEK
        eff_hours = min(Decimal(str(hours)), Decimal(MAX_HOURS_PER_WEEK))
        normalized = rate * eff_hours * Decimal(WEEKS_PER_YEAR)
    elif basis == "WEEKLY":
        normalized = rate * Decimal(52)
    elif basis == "BIWEEKLY":
        normalized = rate * Decimal(26)
    elif basis == "SEMIMONTHLY":
        normalized = rate * Decimal(24)
    elif basis == "MONTHLY":
        normalized = rate * Decimal(12)
    elif basis == "ANNUAL":
        normalized = rate
    else:
        normalized = rate

    final_period = record.get("final_pay_period_income_cents") or 0
    blended = (
        record.get("employment_status") == "TERMINATED"
        and record.get("separation_date") is not None
        and final_period > 0
    )
    if blended:
        periods = PERIODS_PER_YEAR.get(employer.get("payroll_frequency"), 12)
        prorated = normalized * Decimal(periods - 1) / Decimal(periods)
        annual = round_half_up(prorated + Decimal(final_period))
    else:
        annual = round_half_up(normalized)

    hire = record.get("hire_date")
    end = record.get("separation_date") or clock.today()
    tenure = clock.complete_months(hire, end) if hire else 0
    return annual, max(0, tenure)


def recompute_record(record, employer):
    annual, tenure = annualized_income(record, employer)
    record["annualized_income_cents"] = annual
    record["tenure_months"] = tenure
    return record


# ---------------------------------------------------------------- contributor rate tier

def contributor_rate(records_count):
    if records_count >= CONTRIBUTOR_TIER3_MIN:
        unit = CONTRIBUTOR_TIER3_RATE
    elif records_count >= CONTRIBUTOR_TIER2_MIN:
        unit = CONTRIBUTOR_TIER2_RATE
    else:
        unit = CONTRIBUTOR_TIER1_RATE
    return unit, records_count * unit


def blended_rate(records_count):
    """Blended average rate over the tiers the count straddles."""
    tier1 = min(records_count, CONTRIBUTOR_TIER2_MIN)
    tier2 = 0
    tier3 = 0
    if records_count > CONTRIBUTOR_TIER2_MIN:
        tier2 = min(records_count, CONTRIBUTOR_TIER3_MIN) - CONTRIBUTOR_TIER2_MIN
    if records_count > CONTRIBUTOR_TIER3_MIN:
        tier3 = records_count - CONTRIBUTOR_TIER3_MIN
    amount = (tier1 * CONTRIBUTOR_TIER1_RATE
              + tier2 * CONTRIBUTOR_TIER2_RATE
              + tier3 * CONTRIBUTOR_TIER3_RATE)
    if records_count <= 0:
        return 0
    return round_half_up(Decimal(amount) / Decimal(records_count))


# ---------------------------------------------------------------- verification fee

def verification_fee(projected_count, resolved_tier, base_fee_cents):
    surcharge = TIER_DEPTH_SURCHARGE.get(resolved_tier, 0)
    if projected_count < 2:
        multiplier = Decimal("1.00")
    elif projected_count < 5:
        multiplier = Decimal("0.90")
    else:
        multiplier = Decimal("0.75")
    return round_half_up(Decimal(base_fee_cents + surcharge) * multiplier)


# ---------------------------------------------------------------- feed currency

def feed_currency_state(employer):
    if employer.get("freeze_state") == "ACTIVE":
        return employer.get("feed_status")
    base = employer.get("last_feed_received_date") or employer.get("created_at")
    staleness = clock.days_elapsed(base)
    interval = CADENCE_INTERVAL_DAYS.get(employer.get("payroll_frequency"), 30)
    if staleness <= interval:
        return "CURRENT"
    if staleness <= interval * FEED_STALLED_MULTIPLIER:
        return "DELAYED"
    return "STALLED"


def refresh_employer_feed_status(employer):
    if employer.get("freeze_state") == "ACTIVE":
        return employer.get("feed_status")
    status = feed_currency_state(employer)
    employer["feed_status"] = status
    return status


def _responsiveness_ratio(employer_id):
    answered = 0
    late = 0
    for dispute in store.all_rows("record_disputes"):
        record = store.get("employment_records", dispute.get("employment_record_id"))
        if not record or record.get("employer_id") != employer_id:
            continue
        if dispute.get("resolved_at") is None:
            continue
        answered += 1
        if dispute["resolved_at"] > dispute.get("response_due_date"):
            late += 1
    if answered == 0 or late == 0:
        return Decimal("1.0")
    return Decimal("0.25")


def feed_currency_score(review, employer):
    expected = review.get("expected_periods") or 0
    distinct = review.get("distinct_pay_periods_in_window") or 0
    coverage = Decimal(distinct) / Decimal(max(1, expected))
    status = employer.get("feed_status")
    if status == "CURRENT":
        recency = Decimal("1.0")
    elif status == "DELAYED":
        recency = Decimal("0.5")
    else:
        recency = Decimal("0.0")
    responsiveness = _responsiveness_ratio(employer["id"])
    # Decay runs from the most recent validated feed date in the window, falling
    # back to the review's own last feed date and then the creation instant.
    base = (employer.get("last_feed_received_date")
            or review.get("last_feed_date_in_window")
            or employer.get("created_at"))
    decay_days = clock.days_elapsed(base)
    raw = (Decimal(FEED_BASE_WEIGHT) * coverage
           + Decimal(FEED_RECENCY_WEIGHT) * recency
           + Decimal(FEED_RESPONSIVENESS_WEIGHT) * responsiveness
           - Decimal(FEED_DECAY_PER_DAY) * Decimal(decay_days))
    return clamp(round_half_up(raw), FEED_SCORE_FLOOR, FEED_SCORE_CEILING)


def missing_periods_for(review):
    return max(0, (review.get("expected_periods") or 0)
               - (review.get("distinct_pay_periods_in_window") or 0))


# ---------------------------------------------------------------- verifier negative score

def _attributed_events(verifier_id):
    events = []
    for dispute in store.all_rows("record_disputes"):
        if dispute.get("dispute_state") != "ESCALATED" or dispute.get("_escalated_at") is None:
            continue
        record = store.get("employment_records", dispute.get("employment_record_id"))
        if not record:
            continue
        employer_id = record.get("employer_id")
        for request in store.all_rows("verification_requests"):
            if (request.get("verifier_id") == verifier_id
                    and request.get("request_state") == "RESPONDED"
                    and request.get("current_employer_id") == employer_id):
                events.append((dispute["_escalated_at"], DISPUTE_ESCALATION_PENALTY))
                break
    for review in store.all_rows("data_currency_reviews"):
        if review.get("review_state") != "ESCALATED" or review.get("_escalated_at") is None:
            continue
        for request in store.all_rows("verification_requests"):
            if (request.get("verifier_id") == verifier_id
                    and request.get("current_employer_id") == review.get("employer_id")):
                events.append((review["_escalated_at"], FEED_STALL_PENALTY))
                break
    for request in store.all_rows("verification_requests"):
        if (request.get("verifier_id") == verifier_id
                and request.get("request_state") == "REVERSED_RECONSENT_REQUIRED"
                and request.get("_reversed_at") is not None):
            events.append((request["_reversed_at"], REVERSAL_PENALTY))
    events.sort(key=lambda item: item[0])
    return events


def verifier_negative_score(verifier):
    events = _attributed_events(verifier["id"])
    running = Decimal(0)
    for index, (_created, penalty) in enumerate(events):
        compounded = round_half_up(Decimal(penalty) * (Decimal(str(VERIFIER_CONTAGION_FACTOR)) ** index))
        running = Decimal(clamp(int(running) + compounded, 0, VERIFIER_SCORE_CEILING))
    verifier["negative_escalation_count"] = int(running)
    verifier["posture"] = "RESTRICTED" if int(running) >= VERIFIER_RESTRICT_SCORE else "NORMAL"
    return verifier["negative_escalation_count"]


def refresh_verifiers_for_employer(employer_id):
    seen = set()
    for request in store.all_rows("verification_requests"):
        if request.get("current_employer_id") == employer_id:
            seen.add(request.get("verifier_id"))
    for verifier_id in seen:
        verifier = store.get("verifiers", verifier_id)
        if verifier is not None:
            verifier_negative_score(verifier)


# ---------------------------------------------------------------- employer match selection

def _batch_sequence(record):
    batch = store.get("payroll_feed_batches", record.get("payroll_feed_batch_id"))
    if batch is None:
        return 0
    return batch.get("batch_sequence") or 0


def candidate_records(covered_worker_id):
    pool = []
    for record in store.all_rows("employment_records"):
        if record.get("covered_worker_id") != covered_worker_id:
            continue
        if record.get("record_state") not in CANDIDATE_RECORD_STATES:
            continue
        if record.get("currency_state") not in ("CURRENT", "STALE"):
            continue
        employer = store.get("employers", record.get("employer_id"))
        if employer is None or employer.get("freeze_state") in FREEZE_LIVE_STATES:
            continue
        pool.append(record)
    return pool


def nearest_span_record(covered_worker_id):
    """The most recent span for a worker regardless of state, used only so a
    freeze decline can name the employer the request concerns (PRD §2.10)."""
    pool = [record for record in store.all_rows("employment_records")
            if record.get("covered_worker_id") == covered_worker_id
            and record.get("hire_date") is not None]
    if not pool:
        return None
    return sorted(pool, key=lambda record: (
        -record["hire_date"].timestamp(),
        EMPLOYMENT_STATUS_RANK.get(record.get("employment_status"), 9),
        record.get("created_at"),
    ))[0]


def employer_match_selection(covered_worker_id):
    pool = candidate_records(covered_worker_id)
    if not pool:
        return None
    def rank(record):
        return (
            -record["hire_date"].timestamp() if record.get("hire_date") else 0,
            EMPLOYMENT_STATUS_RANK.get(record.get("employment_status"), 9),
            record.get("created_at"),
            _batch_sequence(record),
        )
    return sorted(pool, key=rank)[0]


# ---------------------------------------------------------------- tier resolution

def available_history_months(employer_id, covered_worker_id=None):
    earliest = None
    for record in store.all_rows("employment_records"):
        if record.get("employer_id") != employer_id:
            continue
        if covered_worker_id is not None and record.get("covered_worker_id") != covered_worker_id:
            continue
        if record.get("record_state") not in CANDIDATE_RECORD_STATES:
            continue
        if record.get("currency_state") not in ("CURRENT", "STALE"):
            continue
        hire = record.get("hire_date")
        if hire is None:
            continue
        if earliest is None or hire < earliest:
            earliest = hire
    if earliest is None:
        return 0
    return clock.complete_months(earliest, clock.today())


def tier_resolution(product, employer_id, covered_worker_id=None):
    requested_tier = product.get("tier")
    months = available_history_months(employer_id, covered_worker_id) if employer_id else 0
    if (product.get("history_months_included") or 0) > months:
        return "EMPLOYMENT_INCOME" if months >= 12 else "EMPLOYMENT_ONLY"
    return requested_tier


# ---------------------------------------------------------------- response projection

def resolved_nominal_depth(resolved_tier, product):
    if resolved_tier == product.get("tier"):
        return product.get("history_months_included") or 0
    return TIER_HISTORY_DEPTH.get(resolved_tier, 0)


def response_field_projection(product, resolved_tier, records):
    fields = set(ALWAYS_RENDERED)
    if product.get("includes_employment_status"):
        fields.add("employment_status")
        fields.add("tenure_months")
    depth = resolved_nominal_depth(resolved_tier, product)
    if depth > 0:
        fields.add("income_history")
    if depth >= 12:
        fields.add("pay_rate")
        fields.add("pay_rate_basis")
    if depth >= 24:
        fields.add("separation_date")
        fields.add("final_pay_period_income_cents")
    if any(record.get("record_state") == "DISPUTED" for record in records):
        for name in ("employment_status", "tenure_months", "pay_rate", "pay_rate_basis",
                     "separation_date", "final_pay_period_income_cents", "income_history"):
            fields.discard(name)
    return sorted(fields)


def income_history_buckets(resolved_tier, product, records, months_available):
    depth = resolved_nominal_depth(resolved_tier, product)
    if depth <= 0:
        return []
    cap = 12 if depth < 24 else 24
    count = min(cap, months_available)
    count = max(0, count)
    monthly = 0
    for record in records:
        if record.get("record_state") == "IMMUTABLE":
            continue
        monthly = record.get("annualized_income_cents") or 0
        break
    per_month = round_half_up(Decimal(monthly) / Decimal(12)) if monthly else 0
    buckets = []
    cursor = clock.today()
    for _ in range(count):
        buckets.append({
            "bucket_month": "%04d-%02d" % (cursor.year, cursor.month),
            "income_cents": per_month,
        })
        month = cursor.month - 1
        year = cursor.year
        if month == 0:
            month = 12
            year -= 1
        cursor = cursor.replace(year=year, month=month, day=1)
    return buckets


def selected_employer_records(employer_id, covered_worker_id):
    rows = []
    for record in store.all_rows("employment_records"):
        if record.get("employer_id") != employer_id:
            continue
        if record.get("record_state") not in CANDIDATE_RECORD_STATES:
            continue
        if record.get("currency_state") not in ("CURRENT", "STALE"):
            continue
        rows.append(record)
    return rows


# ---------------------------------------------------------------- disclosure assembly

def disclosure_file_assembly(worker, disclosure):
    included = []
    held = []
    cutoff = clock.now()
    for record in store.all_rows("employment_records"):
        if record.get("covered_worker_id") != worker["id"]:
            continue
        inside = (
            record.get("record_state") in INCLUDED_RECORD_STATES
            and clock.days_elapsed(record.get("updated_at"), cutoff) <= DISCLOSURE_WINDOW_DAYS
            and record.get("currency_state") != "FROZEN"
        )
        if inside:
            included.append(record)
        else:
            held.append(record)
    included.sort(key=lambda r: (-(r["hire_date"].timestamp() if r.get("hire_date") else 0),
                                 r.get("created_at")))
    payload_records = []
    for record in included:
        employer = store.get("employers", record.get("employer_id")) or {}
        payload_records.append({
            "employment_record_id": record["id"],
            "employer_id": record.get("employer_id"),
            "employment_status": record.get("employment_status"),
            "hire_date": record.get("hire_date"),
            "separation_date": record.get("separation_date"),
            "pay_rate_cents": record.get("pay_rate_cents"),
            "pay_rate_basis": record.get("pay_rate_basis"),
            "annualized_income_cents": record.get("annualized_income_cents"),
            "tenure_months": record.get("tenure_months"),
            "provenance": {
                "employer_legal_name": employer.get("legal_name"),
                "employer_feed_status": employer.get("feed_status"),
                "last_feed_received_date": employer.get("last_feed_received_date"),
            },
        })
    disclosure["included_record_count"] = len(included)
    disclosure["held_record_count"] = len(held)
    disclosure["file_contents"] = {
        "covered_worker_id": worker["id"],
        "included_record_count": len(included),
        "held_record_count": len(held),
        "records": payload_records,
    }
    return disclosure


# ---------------------------------------------------------------- conserved counters

def employer_feed_counters_adjustment(employer):
    counted = 0
    for request in store.all_rows("verification_requests"):
        if request.get("request_state") != "RESPONDED":
            continue
        if request.get("current_employer_id") != employer["id"]:
            continue
        counted += request.get("records_matched_count") or 0
    employer["counted_verification_records"] = max(0, counted)
    return employer["counted_verification_records"]


def employer_compensation_balance(employer):
    settled = 0
    for accrual in store.all_rows("compensation_accruals"):
        if accrual.get("employer_id") != employer["id"]:
            continue
        if accrual.get("cycle_state") == "WAIVED":
            settled += accrual.get("waived_cents") or 0
        elif accrual.get("cycle_state") == "PAID":
            settled += accrual.get("paid_cents") or 0
    return settled