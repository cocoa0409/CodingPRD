"""Pricing and fee calculations. All money in integer cents; round-half-up."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_cents(value):
    """Round a Decimal/float to whole cents using ROUND_HALF_UP -> int."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_gross(line):
    return line["unit_charge_cents"] * line["quantity_units"]


def allowed_line_contracted(line, discount_percent):
    gross = line_gross(line)
    d = Decimal(str(gross)) * (Decimal("1") - Decimal(str(discount_percent)))
    return round_half_up_cents(d)


def allowed_line_percent_of_medicare(line, fee_entry, percent_of_medicare):
    base = Decimal(str(fee_entry["base_rate_cents"])) * \
        Decimal(str(fee_entry["geographic_adjustment_factor"])) * \
        Decimal(str(line["quantity_units"]))
    base_cents = round_half_up_cents(base)
    allowed = Decimal(str(base_cents)) * Decimal(str(percent_of_medicare))
    return round_half_up_cents(allowed)


def allowed_line_ucr(line, ucr_row, ucr_percentile):
    gross = line_gross(line)
    bench_per_unit = ucr_row["percentile_80_cents"] if ucr_percentile == 80 \
        else ucr_row["percentile_50_cents"]
    benchmark = bench_per_unit * line["quantity_units"]
    return min(gross, benchmark)


def allowed_line_reference_based(line, ucr_row, rbp_markup_percent):
    gross = line_gross(line)
    benchmark = ucr_row["percentile_80_cents"] * line["quantity_units"]
    marked = Decimal(str(rbp_markup_percent)) * Decimal(str(benchmark))
    marked_cents = round_half_up_cents(marked)
    return min(gross, marked_cents)


def rbp_amount(claim_billed, claim_allowed, benchmark_total, rbp_markup_percent):
    """rbp = min(billed, allowed + round_half_up(markup * max(0, benchmark - allowed)))"""
    gap = max(0, benchmark_total - claim_allowed)
    gap_markup = round_half_up_cents(Decimal(str(rbp_markup_percent)) * Decimal(str(gap)))
    return min(claim_billed, claim_allowed + gap_markup)


TIER1_CAP_CENTS = 20000
TIER1_RATE = Decimal("0.25")
TIER2_RATE = Decimal("0.20")


def per_claim_fee(savings_cents, fee_cap_cents_per_claim):
    tier1 = Decimal(str(min(savings_cents, TIER1_CAP_CENTS))) * TIER1_RATE
    tier2 = Decimal(str(max(0, savings_cents - TIER1_CAP_CENTS))) * TIER2_RATE
    fee = round_half_up_cents(tier1 + tier2)
    return min(fee_cap_cents_per_claim, fee)
