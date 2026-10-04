"""Business services: calculations, cascades, and cross-entity helpers."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from response import touch


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def add_days(d, days):
    return d + timedelta(days=days)


def months_between(aff, exit_d):
    """Whole calendar months from affiliation date to exit date."""
    months = (exit_d.year - aff.year) * 12 + (exit_d.month - aff.month)
    if exit_d.day < aff.day:
        months -= 1
    return months


def prev_month(period):
    y, m = period.split("-")
    y, m = int(y), int(m)
    if m == 1:
        return f"{y - 1:04d}-12"
    return f"{y:04d}-{m - 1:02d}"


# ---------------------------------------------------------------------------
# Money / rounding helpers
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal to integer cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value):
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round_half_up_6dp(value):
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Practice helpers
# ---------------------------------------------------------------------------

def recompute_active_provider_count(practice):
    count = sum(
        1
        for p in store.providers.values()
        if p["practice_id"] == practice["id"] and p["status"] == "ACTIVE"
    )
    practice["active_provider_count"] = count


def get_executed_agreement(practice_id):
    for ag in store.agreements.values():
        if ag["practice_id"] == practice_id and ag["status"] == "EXECUTED":
            return ag
    return None


# ---------------------------------------------------------------------------
# Shared-services fee (two modes)
# ---------------------------------------------------------------------------

def shared_services_fee(group, agreement, batches_with_amounts):
    """batches_with_amounts: list of (batch, amount_basis_int) in created_at ASC
    order. Returns integer-cent fee. Mode (a): agreement override flat rate.
    Mode (b): group tiered schedule with per-batch rounding then sum."""
    if agreement is not None and agreement.get("shared_services_rate_override") is not None:
        rate = Decimal(str(agreement["shared_services_rate_override"]))
        total = sum(amt for _b, amt in batches_with_amounts)
        return round_half_up_cents(Decimal(total) * rate)

    tier1_rate = Decimal(str(group["shared_services_tier1_rate"]))
    tier2_rate = Decimal(str(group["shared_services_tier2_rate"]))
    tier1_remaining = int(group["shared_services_tier1_cap_cents"])
    total_fee = 0
    for _b, amt in batches_with_amounts:
        t1 = min(amt, tier1_remaining)
        t2 = amt - t1
        batch_fee = Decimal(t1) * tier1_rate + Decimal(t2) * tier2_rate
        total_fee += round_half_up_cents(batch_fee)
        tier1_remaining -= t1
    return total_fee


# ---------------------------------------------------------------------------
# Distribution statement variants
# ---------------------------------------------------------------------------

def period_batches(practice_id, period):
    bs = [
        b
        for b in store.batches.values()
        if b["practice_id"] == practice_id and b["period"] == period
    ]
    bs.sort(key=lambda b: (b["created_at"], b["id"]))
    return bs


def compute_provisional(group, agreement, practice_id, period):
    bs = period_batches(practice_id, period)
    pairs = []
    gross = 0
    for b in bs:
        if b["status"] in ("SETTLED", "ADJUSTED"):
            amt = b["net_settled_cents"]
        else:  # POSTED
            amt = b["posted_amount_cents"]
        gross += amt
        pairs.append((b, amt))
    fee = shared_services_fee(group, agreement, pairs)
    return gross, fee, gross - fee


def compute_final(group, agreement, practice_id, period):
    bs = period_batches(practice_id, period)
    pairs = []
    gross = 0
    for b in bs:
        if b["status"] in ("SETTLED", "ADJUSTED"):
            gross += b["net_settled_cents"]
            pairs.append((b, b["net_settled_cents"]))
    fee = shared_services_fee(group, agreement, pairs)
    return gross, fee, gross - fee


def compute_hold_carry(group, practice_id, period, net_distribution_cents):
    carried_in = 0
    prev = prev_month(period)
    for s in store.statements.values():
        if (
            s["practice_id"] == practice_id
            and s["period"] == prev
            and s["status"] in ("FINAL_ISSUED", "REISSUED")
        ):
            carried_in = s["carried_forward_out_cents"] or 0
            break
    payable_total = net_distribution_cents + carried_in
    threshold = int(group["distribution_hold_threshold_cents"])
    if payable_total >= threshold:
        payout = payable_total
        carry_out = 0
    else:
        payout = 0
        carry_out = payable_total
    return carried_in, payable_total, payout, carry_out


# ---------------------------------------------------------------------------
# Departure penalty
# ---------------------------------------------------------------------------

def departure_penalty(group, practice, requested_exit, earliest_exit, exit_basis):
    aff = date.fromisoformat(practice["affiliation_effective_date"])
    tenure = months_between(aff, exit_basis)
    term = int(group["non_compete_term_months"])
    non_compete_applies = tenure < term
    penalty = 0
    if non_compete_applies:
        penalty += int(group["early_exit_base_penalty_cents"])
        penalty += (term - tenure) * int(group["early_exit_per_month_cents"])
    if requested_exit < earliest_exit:
        penalty += int(group["insufficient_notice_penalty_cents"])
    return penalty, non_compete_applies


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def enrollment_to_effective(enrollment):
    """Hop 3 side effects of an enrollment reaching EFFECTIVE."""
    enrollment["status"] = "EFFECTIVE"
    touch(enrollment)
    provider = store.providers.get(enrollment["provider_id"])
    if provider is not None and provider["status"] == "ROSTERED":
        provider["status"] = "ACTIVE"
        touch(provider)
        practice = store.practices.get(provider["practice_id"])
        if practice is not None:
            recompute_active_provider_count(practice)
            touch(practice)


def practice_affiliate(practice):
    """Hop 1: ONBOARDING -> AFFILIATED with hop 2/3 cascades."""
    practice["status"] = "AFFILIATED"
    practice["affiliation_effective_date"] = store.clock_date().isoformat()
    touch(practice)
    provider_ids = [
        p["id"] for p in store.providers.values() if p["practice_id"] == practice["id"]
    ]
    for en in list(store.enrollments.values()):
        if en["provider_id"] in provider_ids and en["status"] == "APPROVED":
            enrollment_to_effective(en)


def practice_depart(practice, actual_exit_date):
    """DEPARTING -> DEPARTED with full cascade."""
    practice["status"] = "DEPARTED"
    practice["departure_effective_date"] = actual_exit_date.isoformat()
    touch(practice)
    provider_ids = [
        p["id"] for p in store.providers.values() if p["practice_id"] == practice["id"]
    ]
    for p in store.providers.values():
        if p["practice_id"] == practice["id"] and p["status"] != "DEACTIVATED":
            p["status"] = "DEACTIVATED"
            touch(p)
    for en in store.enrollments.values():
        if en["provider_id"] in provider_ids and en["status"] in (
            "SUBMITTED",
            "APPROVED",
            "EFFECTIVE",
        ):
            en["status"] = "TERMINATED"
            en["termination_date"] = actual_exit_date.isoformat()
            touch(en)
    for ag in store.agreements.values():
        if ag["practice_id"] == practice["id"] and ag["status"] == "EXECUTED":
            ag["status"] = "TERMINATED"
            touch(ag)
    recompute_active_provider_count(practice)
    practice["active_provider_count"] = 0
    touch(practice)


def contract_terminate_cascade(contract):
    today = store.clock_date().isoformat()
    for en in store.enrollments.values():
        if en["payer_contract_id"] == contract["id"] and en["status"] in (
            "SUBMITTED",
            "APPROVED",
            "EFFECTIVE",
        ):
            en["status"] = "TERMINATED"
            en["termination_date"] = today
            touch(en)


# ---------------------------------------------------------------------------
# Enrollment linkage
# ---------------------------------------------------------------------------

def practice_has_effective_enrollment(practice_id, contract_id):
    provider_ids = {
        p["id"] for p in store.providers.values() if p["practice_id"] == practice_id
    }
    for en in store.enrollments.values():
        if (
            en["payer_contract_id"] == contract_id
            and en["provider_id"] in provider_ids
            and en["status"] == "EFFECTIVE"
        ):
            return True
    return False
