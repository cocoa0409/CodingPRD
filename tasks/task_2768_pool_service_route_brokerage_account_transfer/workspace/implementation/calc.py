"""Every calculation of PRD sections 2.6 and 3, in Decimal with ROUND_HALF_UP."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants
QUARTERLY_DIVISOR = Decimal(3)
VERIFICATION_TRAILING_MONTHS = 3
VERIFY_TOLERANCE = Decimal("0.0500")

MRR_TIER_1_CENTS = 30000
MRR_TIER_2_CENTS = 100000
MULTIPLE_FLOOR = Decimal("6.0")
MULTIPLE_CAP = Decimal("12.0")
REPAIR_MULTIPLE = Decimal("3.0")

PRICE_TOLERANCE_PCT = Decimal("0.90")

MIN_DOWN_PCT = {
    "CASH": Decimal("1.00"),
    "SELLER_NOTE": Decimal("0.30"),
    "BANK_LOAN": Decimal("0.20"),
    "SBA": Decimal("0.10"),
}
HOLDBACK_PCT = Decimal("0.15")
HOLDBACK_MAX_CENTS = 200000

COMMISSION_TIER_1_CENTS = 1500000
COMMISSION_TIER_2_CENTS = 4000000
MIN_COMMISSION_CENTS = 50000

REPLACEMENT_CAP_PCT = Decimal("0.50")
FREE_ALLOWANCE_PCT = Decimal("0.05")
SOLICITATION_PENALTY_FACTOR = Decimal("1.5")
CLAWBACK_CAP_PCT = Decimal("0.20")

VERIFIED_MRR_FLOOR_PCT = Decimal("0.70")

INTRODUCTION_WINDOW_DAYS = 45
MAX_INTRODUCTIONS_PER_DATE = 2
REPLACEMENT_GRACE_DAYS = 14

ROUTE_DAY_RANK = {"MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5}

PERMIT_TYPES = ("PESTICIDE_APPLICATOR", "CONTRACTOR", "BUSINESS_TAX")
ROUTE_DAYS = ("MON", "TUE", "WED", "THU", "FRI")
CHEMICAL_METHODS = ("INCLUDED", "PASS_THROUGH")
BILLING_FREQUENCIES = ("MONTHLY", "QUARTERLY")
BILLING_SOURCES = ("SELLER_UPLOAD", "BANK_VERIFIED")
FINANCING_TYPES = ("CASH", "SELLER_NOTE", "BANK_LOAN", "SBA")
LICENSE_STATUSES = ("LICENSED", "PENDING", "NONE")
VALUATION_BASES = ("LISTED_BASIS", "VERIFIED_BASIS")
EVENT_TYPES = ("CANCELLED", "DOWNGRADED", "RECOVERED")
ATTRIBUTIONS = ("NATURAL", "SELLER_SOLICITATION", "BUYER_SERVICE_FAILURE")
REMEDY_BASES = ("REPLACEMENT_BASIS", "PRICE_ADJUSTMENT_BASIS")


# ---------------------------------------------------------------- rounding
def cents(value):
    """Round half up to a whole cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ratio4(numerator, denominator):
    """Four decimal places, rounded half up. Zero denominator yields 0.0000."""
    if denominator == 0:
        return Decimal("0.0000")
    value = Decimal(numerator) / Decimal(denominator)
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def one_dp(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def pct_of(amount, pct):
    return cents(Decimal(amount) * pct)


def num(value):
    """JSON number for a Decimal ratio or multiple."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------- dates
def parse_date(text):
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def fmt_date(value):
    return value.isoformat()


def add_days(value, days):
    return value + timedelta(days=days)


def month_label(year, month):
    return "%04d-%02d" % (year, month)


def shift_month(year, month, delta):
    index = (year * 12 + (month - 1)) + delta
    return index // 12, (index % 12) + 1


def trailing_month_labels(clock):
    """The three month labels immediately preceding the clock's own month,
    taken in ascending order (PRD section 3.3)."""
    labels = []
    for offset in range(VERIFICATION_TRAILING_MONTHS, 0, -1):
        year, month = shift_month(clock.year, clock.month, -offset)
        labels.append(month_label(year, month))
    return labels


def account_age_months(clock, service_start_date):
    """Whole months from service_start_date to the clock, floored at zero."""
    start = parse_date(service_start_date)
    months = 12 * (clock.year - start.year) + (clock.month - start.month)
    if clock.day < start.day:
        months -= 1
    return months if months > 0 else 0


# ---------------------------------------------------------------- account
def claimed_recurring_mrr(monthly_service_fee_cents, avg_monthly_chemical_cents,
                          chemical_billing_method, billing_frequency):
    """Normalised service component plus the chemical component."""
    if billing_frequency == "QUARTERLY":
        service = cents(Decimal(monthly_service_fee_cents) / QUARTERLY_DIVISOR)
    else:
        service = int(monthly_service_fee_cents)
    chemical = int(avg_monthly_chemical_cents) if chemical_billing_method == "INCLUDED" else 0
    return service + chemical


# ---------------------------------------------------------------- billing
def billing_derivations(billed_service, billed_chemical, billed_repair, collected,
                        chemical_billing_method):
    total_billed = billed_service + billed_chemical + billed_repair
    rate = ratio4(collected, total_billed) if total_billed > 0 else Decimal("0.0000")
    recurring_invoice = billed_service + (billed_chemical if chemical_billing_method == "INCLUDED" else 0)
    return {
        "collection_rate": rate,
        "recurring_collected_cents": cents(Decimal(recurring_invoice) * rate),
        "repair_collected_cents": cents(Decimal(billed_repair) * rate),
    }


def verification_figures(rows_by_month, labels, chemical_billing_method):
    """Rounding happens per month, before any averaging (PRD section 3.3)."""
    recurring_total = 0
    repair_total = 0
    for label in labels:
        row = rows_by_month[label]
        derived = billing_derivations(
            row["billed_service_cents"], row["billed_chemical_cents"],
            row["billed_repair_cents"], row["collected_cents"], chemical_billing_method)
        recurring_total += derived["recurring_collected_cents"]
        repair_total += derived["repair_collected_cents"]
    divisor = Decimal(VERIFICATION_TRAILING_MONTHS)
    return (cents(Decimal(recurring_total) / divisor), cents(Decimal(repair_total) / divisor))


def verification_variance(verified_recurring, claimed_recurring):
    if claimed_recurring == 0:
        return Decimal("0.0000") if verified_recurring == 0 else Decimal("1.0000")
    return ratio4(abs(verified_recurring - claimed_recurring), claimed_recurring)


def verification_outcome(variance):
    return "VERIFIED" if variance <= VERIFY_TOLERANCE else "DISPUTED"


# ---------------------------------------------------------------- valuation
def base_multiple_for(recurring_mrr_cents):
    if recurring_mrr_cents < MRR_TIER_1_CENTS:
        return Decimal("9.0")
    if recurring_mrr_cents < MRR_TIER_2_CENTS:
        return Decimal("10.0")
    return Decimal("11.0")


def age_adjustment_for(weighted_age_months):
    if weighted_age_months >= 60:
        return Decimal("1.0")
    if weighted_age_months >= 36:
        return Decimal("0.5")
    if weighted_age_months >= 24:
        return Decimal("0.0")
    return Decimal("-1.0")


def valuation_figures(inputs):
    """inputs: list of (recurring_cents, repair_cents, age_months)."""
    recurring_total = sum(item[0] for item in inputs)
    repair_total = sum(item[1] for item in inputs)
    account_count = len(inputs)
    if recurring_total == 0:
        weighted_age = 0
    else:
        weighted_sum = sum(Decimal(item[2]) * Decimal(item[0]) for item in inputs)
        weighted_age = int((weighted_sum / Decimal(recurring_total)).to_integral_value(rounding="ROUND_FLOOR"))
    base = base_multiple_for(recurring_total)
    adjustment = age_adjustment_for(weighted_age)
    effective = base + adjustment
    if effective < MULTIPLE_FLOOR:
        effective = MULTIPLE_FLOOR
    if effective > MULTIPLE_CAP:
        effective = MULTIPLE_CAP
    effective = one_dp(effective)
    recurring_component = cents(Decimal(recurring_total) * effective)
    repair_component = cents(Decimal(repair_total) * REPAIR_MULTIPLE)
    return {
        "recurring_mrr_cents": recurring_total,
        "repair_mrr_cents": repair_total,
        "account_count": account_count,
        "weighted_avg_account_age_months": weighted_age,
        "base_multiple": base,
        "age_adjustment": adjustment,
        "effective_multiple": effective,
        "recurring_component_cents": recurring_component,
        "repair_component_cents": repair_component,
        "valuation_cents": recurring_component + repair_component,
    }


def reprice_threshold(current_offer_price_cents):
    return pct_of(current_offer_price_cents, PRICE_TOLERANCE_PCT)


# ---------------------------------------------------------------- deal money
def minimum_down_payment(price_cents, financing_type):
    return pct_of(price_cents, MIN_DOWN_PCT[financing_type])


def holdback_for(price_cents):
    """Fifteen percent rounded half up first, then capped at 200,000 cents."""
    rounded = pct_of(price_cents, HOLDBACK_PCT)
    return rounded if rounded < HOLDBACK_MAX_CENTS else HOLDBACK_MAX_CENTS


def commission_for(gross_cents):
    if gross_cents < COMMISSION_TIER_1_CENTS:
        rate = Decimal("0.10")
    elif gross_cents < COMMISSION_TIER_2_CENTS:
        rate = Decimal("0.08")
    else:
        rate = Decimal("0.06")
    raw = cents(Decimal(gross_cents) * rate)
    return raw if raw > MIN_COMMISSION_CENTS else MIN_COMMISSION_CENTS


def clawback_cap_for(price_cents):
    return pct_of(price_cents, CLAWBACK_CAP_PCT)


def allowance_for(guaranteed_mrr_cents):
    return pct_of(guaranteed_mrr_cents, FREE_ALLOWANCE_PCT)


def verified_mrr_floor(listed_mrr_cents):
    return pct_of(listed_mrr_cents, VERIFIED_MRR_FLOOR_PCT)


# ---------------------------------------------------------------- ledger
def attrition_ledger(events, guaranteed_mrr_cents, replacement_mrr_cents):
    """PRD section 3.9: recoveries offset natural churn before solicited churn,
    then replacement credit is applied with the same priority."""
    natural = 0
    solicited = 0
    buyer_fault = 0
    recovered = 0
    for event in events:
        delta = event["mrr_delta_cents"]
        if event["event_type"] in ("CANCELLED", "DOWNGRADED"):
            magnitude = abs(delta)
            if event["attributed_to"] == "NATURAL":
                natural += magnitude
            elif event["attributed_to"] == "SELLER_SOLICITATION":
                solicited += magnitude
            else:
                buyer_fault += magnitude
        elif event["event_type"] == "RECOVERED":
            recovered += delta

    offset_natural = max(0, natural - recovered)
    recovery_residue = max(0, recovered - natural)
    offset_solicited = max(0, solicited - recovery_residue)

    attrited = offset_natural + offset_solicited + buyer_fault
    retained = guaranteed_mrr_cents - attrited

    credit_cap = pct_of(offset_natural + offset_solicited, REPLACEMENT_CAP_PCT)
    credit = replacement_mrr_cents if replacement_mrr_cents < credit_cap else credit_cap
    credited_natural = max(0, offset_natural - credit)
    credit_residue = max(0, credit - offset_natural)
    credited_solicited = max(0, offset_solicited - credit_residue)
    net = credited_natural + credited_solicited

    allowance = allowance_for(guaranteed_mrr_cents)
    pct = ratio4(net, guaranteed_mrr_cents)
    return {
        "natural_loss": natural,
        "solicited_loss": solicited,
        "buyer_fault_loss": buyer_fault,
        "recovered_total": recovered,
        "offset_natural": offset_natural,
        "offset_solicited": offset_solicited,
        "attrited_mrr_cents": attrited,
        "retained_mrr_cents": retained,
        "replacement_mrr_cents": replacement_mrr_cents,
        "replacement_credit_cap_cents": credit_cap,
        "replacement_credit_mrr_cents": credit,
        "credited_natural": credited_natural,
        "credited_solicited": credited_solicited,
        "net_attrition_mrr_cents": net,
        "allowance_mrr_cents": allowance,
        "attrition_pct": pct,
        "triggered": net > allowance,
    }


def settlement_figures(ledger, deal, escrow, remedy_basis):
    """The settlement derivation snapshot of PRD section 3.9."""
    allowance = deal.get("allowance_mrr_cents") or 0
    compensable_natural = max(0, ledger["credited_natural"] - allowance)
    compensable_solicited = ledger["credited_solicited"]
    guaranteed = deal.get("guaranteed_mrr_cents") or 0
    price = deal.get("current_offer_price_cents") or 0

    if remedy_basis == "REPLACEMENT_BASIS":
        multiple = deal.get("effective_multiple_at_close")
        multiple = Decimal(str(multiple)) if multiple is not None else Decimal("0")
        raw = (cents(Decimal(compensable_natural) * multiple)
               + cents(Decimal(compensable_solicited) * multiple * SOLICITATION_PENALTY_FACTOR))
    else:
        natural_pct = ratio4(compensable_natural, guaranteed)
        solicited_pct = ratio4(compensable_solicited, guaranteed)
        raw = (cents(Decimal(price) * natural_pct)
               + cents(Decimal(price) * solicited_pct * SOLICITATION_PENALTY_FACTOR))

    cap = deal.get("clawback_cap_cents")
    adjustment = raw if cap is None else (raw if raw < cap else cap)

    holdback_balance = escrow["holdback_balance_cents"] if escrow else 0
    note_principal = deal.get("note_principal_cents") or 0
    from_holdback = adjustment if adjustment < holdback_balance else holdback_balance
    remainder = adjustment - from_holdback
    from_note = remainder if remainder < note_principal else note_principal
    seller_direct = adjustment - from_holdback - from_note
    return {
        "guaranteed_mrr_cents": guaranteed,
        "lost_natural_mrr_cents": ledger["offset_natural"],
        "lost_solicited_mrr_cents": ledger["offset_solicited"],
        "lost_buyer_fault_mrr_cents": ledger["buyer_fault_loss"],
        "recovered_mrr_cents": ledger["recovered_total"],
        "replacement_credit_cap_cents": ledger["replacement_credit_cap_cents"],
        "replacement_credit_mrr_cents": ledger["replacement_credit_mrr_cents"],
        "allowance_mrr_cents": allowance,
        "compensable_natural_mrr_cents": compensable_natural,
        "compensable_solicited_mrr_cents": compensable_solicited,
        "raw_adjustment_cents": raw,
        "adjustment_cents": adjustment,
        "from_holdback_cents": from_holdback,
        "from_note_principal_cents": from_note,
        "seller_direct_due_cents": seller_direct,
        "holdback_release_to_seller_cents": holdback_balance - from_holdback,
    }
