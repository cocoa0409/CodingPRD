"""Domain logic: size tiers, live-derived counters, dues pricing, the rating
methodology, snapshot generation, and the daily-close sweeps.

Derived counters (PRD 3.4/3.6/3.8) are computed live from source rows so their
values always match the definitional windows; state-transition side effects
still bump `version`/`updated_at` on the touched resources per PRD 2.5.
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import db
from constants import (
    AGE_CAP,
    AGE_FREE_YEARS,
    AGE_POINTS_PER_YEAR_UNDER_FREE,
    ADVERTISING_REFERRED_POINTS,
    ADVERTISING_UNDER_REVIEW_POINTS,
    ARBITRATION_ADVERSE_POINTS_EACH,
    ARBITRATION_CAP,
    COMPLAINT_CLOSED_STATES,
    COMPLAINT_OPEN_STATES,
    COMPLAINT_OUTCOME_STATES,
    COMPLAINT_PENDING_STATES,
    COMPLAINT_UNRESOLVED_STATES,
    DUES_BASE_CENTS,
    GRADE_F,
    GRADE_FLOORS,
    INVOICE_DUE_DAYS,
    INVOICE_VOID_GRACE_DAYS,
    PENDING_CAP,
    PENDING_POINTS_EACH,
    QUARTERLY_INSTALLMENT_COUNT,
    QUARTERLY_SURCHARGE_MULTIPLIER,
    ANNUAL_PREPAID_MULTIPLIER,
    RATING_WINDOW_DAYS,
    REINSTATE_SCORE_THRESHOLD,
    REVOKE_SUSPENSION_COUNT,
    SCAM_PATTERN_MIN_REPORTS,
    SCAM_PATTERN_POINTS,
    SCAM_PATTERN_WINDOW_DAYS,
    SUSPEND_SCORE_THRESHOLD,
    SUSPENSION_WINDOW_DAYS,
    TIER_MEDIUM_MAX_EMPLOYEES,
    TIER_MICRO_MAX_EMPLOYEES,
    TIER_SMALL_MAX_EMPLOYEES,
    TIER_LARGE,
    TIER_MEDIUM,
    TIER_MICRO,
    TIER_SMALL,
    UNANSWERED_CAP,
    UNANSWERED_POINTS_EACH,
    UNRESOLVED_CAP,
    UNRESOLVED_POINTS_EACH,
    VOLUME_CAP,
    VOLUME_POINTS_PER_EXCESS,
    VOLUME_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# Size tiers (PRD 3.1)
# ---------------------------------------------------------------------------
def size_tier_of(employee_count):
    if employee_count <= TIER_MICRO_MAX_EMPLOYEES:
        return TIER_MICRO
    if employee_count <= TIER_SMALL_MAX_EMPLOYEES:
        return TIER_SMALL
    if employee_count <= TIER_MEDIUM_MAX_EMPLOYEES:
        return TIER_MEDIUM
    return TIER_LARGE


# ---------------------------------------------------------------------------
# Live-derived counters
# ---------------------------------------------------------------------------
def business_complaints(business_id):
    return [c for c in db.STORE.complaints.values() if c["business_id"] == business_id]


def _in_trailing_window(instant, now, window_days):
    if instant is None:
        return False
    return now - timedelta(days=window_days) <= instant <= now


def complaint_counters(business_id, now):
    """Return the five complaint counters exactly as PRD 3.4 defines them:
    the *_36m counters windowed over trailing 1095 days; open/closed totals
    not windowed."""
    complaints = business_complaints(business_id)
    windowed = [
        c for c in complaints
        if _in_trailing_window(c["filed_at"], now, RATING_WINDOW_DAYS)
    ]
    received_36m = sum(1 for c in windowed if c["status"] in COMPLAINT_OUTCOME_STATES)
    unanswered_36m = sum(1 for c in windowed if c["status"] == "UNANSWERED")
    unresolved_36m = sum(
        1 for c in windowed if c["status"] in COMPLAINT_UNRESOLVED_STATES
    )
    open_count = sum(1 for c in complaints if c["status"] in COMPLAINT_OPEN_STATES)
    closed_count = sum(1 for c in complaints if c["status"] in COMPLAINT_CLOSED_STATES)
    return {
        "complaints_received_36m": received_36m,
        "complaints_unanswered_36m": unanswered_36m,
        "complaints_unresolved_36m": unresolved_36m,
        "complaints_open_count": open_count,
        "complaints_closed_count": closed_count,
    }


def published_scam_count(business_id, now):
    return sum(
        1
        for report in db.STORE.scam_reports.values()
        if report["business_id"] == business_id
        and report["status"] == "PUBLISHED"
        and _in_trailing_window(report["published_at"], now, SCAM_PATTERN_WINDOW_DAYS)
    )


def consumer_complaints_filed_count(consumer_id):
    return sum(
        1 for c in db.STORE.complaints.values() if c["consumer_id"] == consumer_id
    )


def bureau_dues_collected_cents(bureau_id):
    """Sum over all non-VOID DuesInvoice rows of businesses assigned to this
    bureau of (paid_cents - refunded_cents)."""
    business_ids = {
        b["id"] for b in db.STORE.businesses.values() if b["bureau_id"] == bureau_id
    }
    total = 0
    for invoice in db.STORE.invoices.values():
        if invoice["business_id"] in business_ids and invoice["status"] != "VOID":
            total += invoice["paid_cents"] - invoice["refunded_cents"]
    return total


def refresh_derived(entity_kind, entity):
    """Overlay live-derived computed fields onto a stored row (mutates the
    stored dict so reads and gates agree; values are definitional)."""
    now = db.now()
    if entity_kind == "business":
        entity.update(complaint_counters(entity["id"], now))
        entity["published_scam_count_12m"] = published_scam_count(entity["id"], now)
    elif entity_kind == "consumer":
        entity["complaints_filed_count"] = consumer_complaints_filed_count(entity["id"])
    elif entity_kind == "bureau":
        entity["dues_collected_cents"] = bureau_dues_collected_cents(entity["id"])
    elif entity_kind == "invoice":
        entity["balance_cents"] = invoice_balance_cents(entity)


# ---------------------------------------------------------------------------
# Dues pricing (PRD 3.3 / scaffold dues_amount)
# ---------------------------------------------------------------------------
def _round_half_up_cents(decimal_value):
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_dues(size_tier, local_fee_cents, billing_plan):
    """Return (base_amount_cents, amount_due_cents, installments). Rounding
    happens only at the two pinned points: once at the plan total, and for
    quarterly plans once at the per-installment amount, with the rounding
    remainder absorbed by the fourth installment."""
    base = DUES_BASE_CENTS[size_tier]
    subtotal = base + local_fee_cents
    if billing_plan == "ANNUAL_PREPAID":
        amount_due = _round_half_up_cents(Decimal(subtotal) * ANNUAL_PREPAID_MULTIPLIER)
        installments = [{"installment": 1, "amount_cents": amount_due}]
    else:  # QUARTERLY
        total = _round_half_up_cents(Decimal(subtotal) * QUARTERLY_SURCHARGE_MULTIPLIER)
        per = _round_half_up_cents(Decimal(total) / Decimal(QUARTERLY_INSTALLMENT_COUNT))
        installments = [
            {"installment": i + 1, "amount_cents": per}
            for i in range(QUARTERLY_INSTALLMENT_COUNT - 1)
        ]
        installments.append(
            {
                "installment": QUARTERLY_INSTALLMENT_COUNT,
                "amount_cents": total - (QUARTERLY_INSTALLMENT_COUNT - 1) * per,
            }
        )
        amount_due = total
    return base, amount_due, installments


def invoice_balance_cents(invoice):
    balance = invoice["amount_due_cents"] - (
        invoice["paid_cents"] - invoice["refunded_cents"]
    )
    return max(0, balance)


# ---------------------------------------------------------------------------
# Rating methodology (PRD 3.6 / scaffold rating_score)
# ---------------------------------------------------------------------------
def full_calendar_years(founded_on, now):
    """Full calendar years elapsed: a year counts once the calendar
    anniversary of the founding date has been reached."""
    years = now.year - founded_on.year
    try:
        anniversary = founded_on.replace(year=now.year)
    except ValueError:
        # February 29 founding: anniversary in a non-leap year is Feb 28
        anniversary = founded_on.replace(year=now.year, day=28)
    if now.date() < anniversary.date():
        years -= 1
    return max(0, years)


def grade_of(score):
    for floor, grade in GRADE_FLOORS:
        if score >= floor:
            return grade
    return GRADE_F


def compute_rating_components(business, variant, now, excluded_complaint_id=None):
    """Compute the eight deduction components, total, score, and grade for a
    RatingSnapshot. Window: complaints with filed_at in [now - 1095d, now]
    inclusive at both ends. The excluded complaint (an OVERRULED dispute) is
    removed from every input set."""
    window_start = now - timedelta(days=RATING_WINDOW_DAYS)
    complaints = [
        c
        for c in business_complaints(business["id"])
        if window_start <= c["filed_at"] <= now
        and c["id"] != excluded_complaint_id
    ]
    outcome = [c for c in complaints if c["status"] in COMPLAINT_OUTCOME_STATES]
    pending = [c for c in complaints if c["status"] in COMPLAINT_PENDING_STATES]

    threshold = VOLUME_THRESHOLDS[business["size_tier"]]
    if variant == "PUBLISHED":
        volume_input = len(outcome)
        pending_deduction = 0
    else:  # PROVISIONAL
        volume_input = len(outcome) + len(pending)
        pending_deduction = min(
            PENDING_CAP, PENDING_POINTS_EACH * len(pending)
        )
    volume_deduction = min(
        VOLUME_CAP, VOLUME_POINTS_PER_EXCESS * max(0, volume_input - threshold)
    )
    unanswered_deduction = min(
        UNANSWERED_CAP,
        UNANSWERED_POINTS_EACH
        * sum(1 for c in complaints if c["status"] == "UNANSWERED"),
    )
    unresolved_deduction = min(
        UNRESOLVED_CAP,
        UNRESOLVED_POINTS_EACH
        * sum(1 for c in complaints if c["status"] in COMPLAINT_UNRESOLVED_STATES),
    )
    arbitration_deduction = min(
        ARBITRATION_CAP,
        ARBITRATION_ADVERSE_POINTS_EACH
        * sum(
            1
            for c in complaints
            if c["status"] == "ARBITRATED"
            and c["resolution_outcome"] == "ARBITRATION_ADVERSE"
        ),
    )
    age_years = full_calendar_years(db.parse_iso(business["founded_on"]) if isinstance(business["founded_on"], str) else business["founded_on"], now)
    age_deduction = min(
        AGE_CAP,
        AGE_POINTS_PER_YEAR_UNDER_FREE * max(0, AGE_FREE_YEARS - age_years),
    )
    ad_status = business["advertising_compliance_status"]
    if ad_status == "REFERRED_TO_REGULATOR":
        advertising_deduction = ADVERTISING_REFERRED_POINTS
    elif ad_status == "UNDER_AD_REVIEW":
        advertising_deduction = ADVERTISING_UNDER_REVIEW_POINTS
    else:
        advertising_deduction = 0
    scam_deduction = (
        SCAM_PATTERN_POINTS
        if published_scam_count(business["id"], now) >= SCAM_PATTERN_MIN_REPORTS
        else 0
    )
    total = (
        volume_deduction
        + unanswered_deduction
        + unresolved_deduction
        + arbitration_deduction
        + age_deduction
        + advertising_deduction
        + scam_deduction
        + pending_deduction
    )
    score = max(0, 100 - total)
    return {
        "volume_deduction": volume_deduction,
        "unanswered_deduction": unanswered_deduction,
        "unresolved_deduction": unresolved_deduction,
        "arbitration_deduction": arbitration_deduction,
        "age_deduction": age_deduction,
        "advertising_deduction": advertising_deduction,
        "scam_deduction": scam_deduction,
        "pending_deduction": pending_deduction,
        "total_deductions": total,
        "score": score,
        "grade": grade_of(score),
    }


def create_snapshot(business, variant, excluded_complaint_id=None):
    """Compute and persist a RatingSnapshot of the given variant, updating the
    business's mirrored current_* fields. Does not bump the business version;
    callers apply the side-effect semantics of their workflow."""
    now = db.now()
    components = compute_rating_components(
        business, variant, now, excluded_complaint_id=excluded_complaint_id
    )
    snapshot = db.new_entity(
        "rating_snapshots",
        {
            "business_id": business["id"],
            "variant": variant,
            "volume_deduction": components["volume_deduction"],
            "unanswered_deduction": components["unanswered_deduction"],
            "unresolved_deduction": components["unresolved_deduction"],
            "arbitration_deduction": components["arbitration_deduction"],
            "age_deduction": components["age_deduction"],
            "advertising_deduction": components["advertising_deduction"],
            "scam_deduction": components["scam_deduction"],
            "pending_deduction": components["pending_deduction"],
            "total_deductions": components["total_deductions"],
            "score": components["score"],
            "grade": components["grade"],
            "window_start_at": now - timedelta(days=RATING_WINDOW_DAYS),
            "computed_at": now,
            "published_at": now if variant == "PUBLISHED" else None,
            "excluded_complaint_id": excluded_complaint_id,
            "superseded_by_id": None,
        },
    )
    if variant == "PUBLISHED":
        business["current_published_score"] = snapshot["score"]
        business["current_published_grade"] = snapshot["grade"]
    else:
        business["current_provisional_score"] = snapshot["score"]
        business["current_provisional_grade"] = snapshot["grade"]
    return snapshot


def regenerate_provisional(business):
    """Auto-regeneration hook (PRD 3.6): write a fresh PROVISIONAL snapshot
    and bump the business (its mirrored provisional fields mutated)."""
    create_snapshot(business, "PROVISIONAL")
    db.touch(business)


def latest_published_snapshot(business_id):
    """Latest PUBLISHED snapshot by published_at DESC, tie-break created_at
    DESC, then insertion order (later wins)."""
    candidates = [
        s
        for s in db.STORE.rating_snapshots.values()
        if s["business_id"] == business_id and s["variant"] == "PUBLISHED"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s["published_at"], s["created_at"], s["_seq"]))


# ---------------------------------------------------------------------------
# Daily close (PRD 2.4)
# ---------------------------------------------------------------------------
def run_daily_close(bureau):
    """Advance the bureau's operations day. Sweeps, in pinned order:
    1. complaint response-window expiries (FORWARDED -> UNANSWERED)
    2. mediation offer expiries (OFFERED -> DECLINED_EXPIRED)
    3. invoice OVERDUE then VOID (cascading the application to EXPIRED)
    4. the suspension scan over the bureau's territory
    """
    now = db.now()
    bureau["ops_day_index"] += 1
    db.touch(bureau)

    business_ids = {
        b["id"] for b in db.STORE.businesses.values() if b["bureau_id"] == bureau["id"]
    }
    businesses = {b["id"]: b for b in db.STORE.businesses.values()}

    # --- Sweep 1: unanswered complaints -----------------------------------
    for complaint in list(db.STORE.complaints.values()):
        if complaint["business_id"] not in business_ids:
            continue
        if complaint["status"] != "FORWARDED":
            continue
        deadline = complaint["response_deadline_at"]
        if deadline is not None and now > deadline:
            complaint["status"] = "UNANSWERED"
            complaint["resolution_outcome"] = "AUTO_UNANSWERED"
            complaint["closed_at"] = now
            db.touch(complaint)
            regenerate_provisional(businesses[complaint["business_id"]])

    # --- Sweep 2: mediation offer expiries --------------------------------
    for case in list(db.STORE.mediation_cases.values()):
        if case["status"] != "OFFERED":
            continue
        complaint = db.STORE.complaints.get(case["complaint_id"])
        if complaint is None or complaint["business_id"] not in business_ids:
            continue
        if now > case["offer_deadline_at"]:
            case["status"] = "DECLINED_EXPIRED"
            db.touch(case)
            complaint["status"] = "UNRESOLVED"
            # last_unresolved_at is NOT refreshed (PRD 3.5)
            db.touch(complaint)
            regenerate_provisional(businesses[complaint["business_id"]])

    # --- Sweep 3: invoice overdue then void -------------------------------
    for invoice in list(db.STORE.invoices.values()):
        if invoice["business_id"] not in business_ids:
            continue
        if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
            continue
        due_date = invoice["due_date"]
        if now > due_date + timedelta(days=INVOICE_VOID_GRACE_DAYS):
            invoice["status"] = "VOID"
            invoice["voided_at"] = now
            db.touch(invoice)
            application = db.STORE.applications.get(invoice["application_id"])
            if application is not None and application["status"] == "APPROVED_PENDING_DUES":
                application["status"] = "EXPIRED"
                db.touch(application)
        elif now > due_date:
            if invoice["status"] != "OVERDUE":
                invoice["status"] = "OVERDUE"
                db.touch(invoice)

    # --- Sweep 4: suspension scan ------------------------------------------
    for business in db.STORE.businesses.values():
        if business["bureau_id"] != bureau["id"]:
            continue
        if business["accreditation_status"] not in ("ACCREDITED", "SUSPENDED"):
            continue
        # suspensions older than 730 days drop out before the check
        events = [
            t
            for t in db.STORE.suspension_events.get(business["id"], [])
            if now - t <= timedelta(days=SUSPENSION_WINDOW_DAYS)
        ]
        db.STORE.suspension_events[business["id"]] = events
        business["suspension_count_24m"] = len(events)

        latest = latest_published_snapshot(business["id"])
        if latest is None:
            continue
        status = business["accreditation_status"]
        if status == "ACCREDITED" and latest["score"] < SUSPEND_SCORE_THRESHOLD:
            events.append(now)
            business["suspension_count_24m"] = len(events)
            business["last_suspension_at"] = now
            if len(events) >= REVOKE_SUSPENSION_COUNT:
                business["accreditation_status"] = "REVOKED"
            else:
                business["accreditation_status"] = "SUSPENDED"
            db.touch(business)
        elif status == "SUSPENDED" and latest["score"] >= REINSTATE_SCORE_THRESHOLD:
            business["accreditation_status"] = "ACCREDITED"
            db.touch(business)
        elif (
            status == "SUSPENDED"
            and latest["score"] < SUSPEND_SCORE_THRESHOLD
            and len(events) >= REVOKE_SUSPENSION_COUNT
        ):
            business["accreditation_status"] = "REVOKED"
            db.touch(business)
