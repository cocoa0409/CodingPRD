"""Calculations, rollups and derived-field recomputation.

All money and fraction arithmetic uses decimal.Decimal with ROUND_HALF_UP;
never float (PRD 2.5).
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import store
from constants import (
    ANNUAL_MDF_CAP_CENTS, BASE_MARGIN_PCT, CERT_CREDIT_TARGET, CERT_CREDIT_WEIGHT,
    CERT_FLOOR_BY_TIER, COVERAGE_HORIZON_DAYS, ENTITLEMENT_LADDER, GOLD_CERT_MIN,
    GOLD_SCORE_MIN, MARGIN_FLOOR_PCT, MATCH_RATE_PCT, MDF_ACCRUAL_RATE,
    MDF_BASE_GRANT_CENTS, MDF_PERIOD_CAP_CENTS, PLATINUM_CERT_MIN,
    PLATINUM_REVENUE_MIN_CENTS, PLATINUM_SCORE_MIN, PROTECTION_DAYS_BY_TIER,
    REGISTRATION_UPLIFT_AFTER_WINDOW_PCT, REGISTRATION_UPLIFT_IN_WINDOW_PCT,
    REVENUE_TARGET_CENTS, SILVER_CERT_MIN, SILVER_SCORE_MIN,
    STOCKING_ALLOWANCE_PCT, TIER_ENTITLEMENT_INDEX, TIER_MARGIN_CEILING_PCT,
    VOLUME_BAND_HIGH_MIN_CENTS, VOLUME_BAND_MID_MIN_CENTS, VOLUME_UPLIFT_PCT,
    WEIGHT_CERT, WEIGHT_MARKETING, WEIGHT_REVENUE,
)

ONE = Decimal(1)
FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc)


def q4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    """Convert a stored JSON-ish number into an exact Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(repr(value))


# ---------------------------------------------------------------------------
# rollups over the partner's own rows
# ---------------------------------------------------------------------------
def certification_credit_rollup(partner_id):
    total = 0
    for rec in store.all_rows("certifications"):
        if rec["partner_id"] == partner_id and rec["status"] == "ACTIVE":
            total += rec["credit_weight"]
    return total


def partner_revenue_rollup(partner_id):
    total = 0
    for order in store.all_rows("orders"):
        if order["partner_id"] == partner_id and order["status"] in ("INVOICED", "CREDITED"):
            total += order["invoice_amount_cents"]
    return total


def qualified_marketing_spend(partner_id):
    """Verified proofs on VALIDATED claims of this partner's fund periods."""
    allocation_ids = set()
    for allocation in store.all_rows("allocations"):
        if allocation["partner_id"] == partner_id:
            allocation_ids.add(allocation["id"])
    claim_ids = set()
    for claim in store.all_rows("claims"):
        if claim["allocation_id"] in allocation_ids and claim["validation_state"] == "VALIDATED":
            claim_ids.add(claim["id"])
    total = 0
    for proof in store.all_rows("proofs"):
        if proof["claim_id"] in claim_ids and proof["verified"]:
            total += proof["spend_amount_cents"]
    return total


def marketing_attainment_pct(commitment_cents, qualified_cents):
    if commitment_cents == 0:
        return q4(ONE)
    ratio = Decimal(qualified_cents) / Decimal(commitment_cents)
    if ratio > ONE:
        ratio = ONE
    value = q4(ratio)
    if value > ONE:
        value = q4(ONE)
    return value


def open_conflict_count(partner_id):
    count = 0
    for case in store.all_rows("conflicts"):
        if case["status"] not in ("OPEN", "ESCALATED_TIER1", "ESCALATED_TIER2"):
            continue
        subject = store.get("registrations", case["subject_registration_id"])
        if subject is not None and subject["partner_id"] == partner_id:
            count += 1
    return count


def portal_entitlement(tier, tier_status, cert_credit_total):
    """PRD 3.1 portal ladder; pure function of the partner's own three fields."""
    if tier_status == "SUSPENDED":
        return "BASIC"
    index = TIER_ENTITLEMENT_INDEX[tier]
    demotions = 0
    if tier_status == "PROBATION":
        demotions += 1
    if cert_credit_total < CERT_FLOOR_BY_TIER[tier]:
        demotions += 1
    index = index - demotions
    if index < 0:
        index = 0
    return ENTITLEMENT_LADDER[index]


def recompute_entitlement(partner):
    partner["portal_entitlement_level"] = portal_entitlement(
        partner["tier"], partner["tier_status"], partner["cert_credit_total"])


def recompute_cert_credits(partner):
    partner["cert_credit_total"] = certification_credit_rollup(partner["id"])
    recompute_entitlement(partner)


def recompute_revenue(partner):
    partner["trailing_revenue_cents"] = partner_revenue_rollup(partner["id"])


def recompute_marketing(partner):
    partner["marketing_qualified_spend_cents"] = qualified_marketing_spend(partner["id"])
    partner["marketing_attainment_pct"] = marketing_attainment_pct(
        partner["marketing_commitment_cents"],
        partner["marketing_qualified_spend_cents"])


def recompute_conflicts(partner):
    partner["open_conflict_count"] = open_conflict_count(partner["id"])


# ---------------------------------------------------------------------------
# partner standing transitions
# ---------------------------------------------------------------------------
def apply_conflict_probation(partner):
    """Cascade A hop 4 / cascade D hop 3: two open cases put a partner on probation."""
    before = (partner["tier_status"], partner["standing_reason"],
              partner["open_conflict_count"], partner["portal_entitlement_level"])
    recompute_conflicts(partner)
    if partner["open_conflict_count"] >= 2 and partner["tier_status"] == "COMPLIANT":
        partner["tier_status"] = "PROBATION"
        partner["standing_reason"] = "OPEN_CONFLICT_THRESHOLD"
    recompute_entitlement(partner)
    after = (partner["tier_status"], partner["standing_reason"],
             partner["open_conflict_count"], partner["portal_entitlement_level"])
    if before != after:
        store.touch(partner)


def clear_conflict_probation(partner):
    """PRD 3.5: resolution recomputes the count and may clear the probation."""
    before = (partner["tier_status"], partner["standing_reason"],
              partner["open_conflict_count"], partner["portal_entitlement_level"])
    recompute_conflicts(partner)
    if (partner["open_conflict_count"] < 2
            and partner["tier_status"] == "PROBATION"
            and partner["standing_reason"] == "OPEN_CONFLICT_THRESHOLD"):
        partner["tier_status"] = "COMPLIANT"
    recompute_entitlement(partner)
    after = (partner["tier_status"], partner["standing_reason"],
             partner["open_conflict_count"], partner["portal_entitlement_level"])
    if before != after:
        store.touch(partner)


def apply_marketing_standing(partner, direction):
    """direction 'down' is cascade B hop 4; 'up' is the validation recovery."""
    before = (partner["tier_status"], partner["standing_reason"],
              partner["marketing_qualified_spend_cents"],
              partner["marketing_attainment_pct"],
              partner["portal_entitlement_level"])
    recompute_marketing(partner)
    attainment = dec(partner["marketing_attainment_pct"])
    if direction == "down":
        if attainment < Decimal("0.75") and partner["tier_status"] == "COMPLIANT":
            partner["tier_status"] = "PROBATION"
            partner["standing_reason"] = "MARKETING_ATTAINMENT_SHORTFALL"
    else:
        if (attainment >= Decimal("0.75")
                and partner["tier_status"] == "PROBATION"
                and partner["standing_reason"] == "MARKETING_ATTAINMENT_SHORTFALL"):
            partner["tier_status"] = "COMPLIANT"
    recompute_entitlement(partner)
    after = (partner["tier_status"], partner["standing_reason"],
             partner["marketing_qualified_spend_cents"],
             partner["marketing_attainment_pct"],
             partner["portal_entitlement_level"])
    if before != after:
        store.touch(partner)


# ---------------------------------------------------------------------------
# windows
# ---------------------------------------------------------------------------
def window_live(registration, instant):
    """PRD 2.6: [exclusivity_start_at, exclusivity_end_at) - half-open."""
    start = registration.get("exclusivity_start_at")
    end = registration.get("exclusivity_end_at")
    if start is None or end is None:
        return False
    return start <= instant < end


def protection_days_for(tier, halved=False):
    days = PROTECTION_DAYS_BY_TIER[tier]
    if halved:
        return days // 2
    return days


def mapping_covers_product_line(mapping, product_line):
    return mapping["exclusivity_scope"] == "FULL" or mapping["product_line"] == product_line


def scopes_overlap(candidate, incumbent):
    """PRD 3.2: either agreement FULL, or both naming the same product line."""
    if candidate["exclusivity_scope"] == "FULL" or incumbent["exclusivity_scope"] == "FULL":
        return True
    return candidate["product_line"] == incumbent["product_line"]


def mapping_window_conflict(candidate, statuses, cooldown_days):
    """The inclusive window test of PRD 3.2 against non-terminated incumbents."""
    from store import plus_days
    cand_from = candidate["effective_from"]
    cand_until = candidate["effective_until"]
    for incumbent in store.all_rows("mappings"):
        if incumbent["id"] == candidate.get("id"):
            continue
        if incumbent["account_id"] != candidate["account_id"]:
            continue
        if incumbent["mapping_status"] not in statuses:
            continue
        if not scopes_overlap(candidate, incumbent):
            continue
        blocked_from = incumbent["effective_from"]
        blocked_until = plus_days(incumbent["effective_until"], cooldown_days)
        clears = cand_from > blocked_until or cand_until < blocked_from
        if not clears:
            return incumbent
    return None


# ---------------------------------------------------------------------------
# conflict recommendations (both doctrines, always stored)
# ---------------------------------------------------------------------------
def recommendation_registration_first(subject, counter, account, detected_at):
    claimants = []
    claimants.append(("GRANT_SUBJECT",
                      subject.get("submitted_at") or FAR_FUTURE,
                      subject["created_at"]))
    if counter is not None:
        claimants.append(("GRANT_COUNTER",
                          counter.get("submitted_at") or FAR_FUTURE,
                          counter["created_at"]))
    if account.get("direct_pursuit_owner_id") is not None:
        claimants.append(("RELEASE_TO_DIRECT",
                          account.get("direct_pursuit_declared_at") or FAR_FUTURE,
                          account["created_at"]))
    best = None
    for label, claim_instant, tiebreak in claimants:
        if best is None:
            best = (label, claim_instant, tiebreak)
            continue
        if claim_instant < best[1]:
            best = (label, claim_instant, tiebreak)
        elif claim_instant == best[1] and tiebreak < best[2]:
            best = (label, claim_instant, tiebreak)
    return best[0]


def recommendation_coverage_first(subject, counter, account, detected_at):
    if (account["coverage_state"] == "CHANNEL_PROTECTED"
            and account.get("protected_until") is not None
            and detected_at < account["protected_until"]):
        holder = account.get("protected_partner_id")
        if holder == subject["partner_id"]:
            return "GRANT_SUBJECT"
        if counter is not None and holder == counter["partner_id"]:
            return "GRANT_COUNTER"
        return "DISMISS"
    if account.get("direct_pursuit_owner_id") is not None:
        return "RELEASE_TO_DIRECT"
    if subject["status"] == "APPROVED":
        return "GRANT_SUBJECT"
    return "DISMISS"


def conflict_recommendations(subject, counter, account, detected_at, conflict_type):
    reg_first = recommendation_registration_first(subject, counter, account, detected_at)
    cov_first = recommendation_coverage_first(subject, counter, account, detected_at)
    applied = "REGISTRATION_FIRST" if conflict_type == "PARTNER_VS_PARTNER" else "COVERAGE_FIRST"
    chosen = reg_first if applied == "REGISTRATION_FIRST" else cov_first
    return applied, chosen, reg_first, cov_first


# ---------------------------------------------------------------------------
# order pricing (PRD 3.6, six pinned steps)
# ---------------------------------------------------------------------------
def registration_uplift(registration, instant):
    if registration is None:
        return Decimal("0")
    if registration["status"] == "APPROVED" and window_live(registration, instant):
        return REGISTRATION_UPLIFT_IN_WINDOW_PCT
    if registration["status"] in ("APPROVED", "EXPIRED", "SUPERSEDED", "CONVERTED"):
        return REGISTRATION_UPLIFT_AFTER_WINDOW_PCT
    return Decimal("0")


def special_pricing_uplift(registration, instant):
    if registration is None:
        return Decimal("0")
    best = None
    for spr in store.all_rows("sprs"):
        if spr["registration_id"] != registration["id"]:
            continue
        if spr["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
            continue
        if spr["expires_at"] is None or not (spr["expires_at"] > instant):
            continue
        if best is None or (spr["created_at"], spr["_seq"]) > (best["created_at"], best["_seq"]):
            best = spr
    if best is None or best["approved_extra_margin_pct"] is None:
        return Decimal("0")
    return dec(best["approved_extra_margin_pct"])


def volume_band_for(preliminary_net_cents):
    if preliminary_net_cents >= VOLUME_BAND_HIGH_MIN_CENTS:
        return "HIGH"
    if preliminary_net_cents >= VOLUME_BAND_MID_MIN_CENTS:
        return "MID"
    return "NONE"


def resolve_margin(partner, order_type, list_amount_cents, registration, instant):
    """Returns (margin_pct, volume_band, invoice_amount_cents, margin_value_cents)."""
    tier = partner["tier"]
    preliminary = BASE_MARGIN_PCT[tier]
    preliminary += registration_uplift(registration, instant)
    preliminary += special_pricing_uplift(registration, instant)
    if partner["partner_type"] == "DISTRIBUTOR" and order_type == "STOCKING":
        preliminary += STOCKING_ALLOWANCE_PCT
    preliminary_net = cents(Decimal(list_amount_cents) * (ONE - preliminary))
    band = volume_band_for(preliminary_net)
    final = preliminary + VOLUME_UPLIFT_PCT[band]
    if final < MARGIN_FLOOR_PCT:
        final = MARGIN_FLOOR_PCT
    ceiling = TIER_MARGIN_CEILING_PCT[tier]
    if final > ceiling:
        final = ceiling
    margin_pct = q4(final)
    invoice_amount = cents(Decimal(list_amount_cents) * (ONE - margin_pct))
    margin_value = list_amount_cents - invoice_amount
    return margin_pct, band, invoice_amount, margin_value


def effective_margin_pct(list_amount_cents, invoice_amount_cents):
    value = Decimal(list_amount_cents - invoice_amount_cents) / Decimal(list_amount_cents)
    return q4(value)


# ---------------------------------------------------------------------------
# market development funds
# ---------------------------------------------------------------------------
def mdf_basis_revenue(partner_id, period_start):
    total = 0
    for order in store.all_rows("orders"):
        if order["partner_id"] != partner_id:
            continue
        if order["status"] not in ("INVOICED", "CREDITED"):
            continue
        if order["invoiced_at"] is None or not (order["invoiced_at"] < period_start):
            continue
        total += order["invoice_amount_cents"]
    return total


def mdf_allocation_sizing(tier, basis_revenue_cents):
    accrual = cents(Decimal(basis_revenue_cents) * MDF_ACCRUAL_RATE[tier])
    capped = min(accrual, MDF_PERIOD_CAP_CENTS[tier])
    return capped + MDF_BASE_GRANT_CENTS[tier]


def annual_cap_for(tier):
    return ANNUAL_MDF_CAP_CENTS[tier]


def periods_intersect(a_start, a_end, b_start, b_end):
    """Closed intervals: two periods that merely touch do intersect."""
    return a_start <= b_end and b_start <= a_end


def recompute_available(allocation):
    allocation["available_cents"] = (allocation["allocated_cents"]
                                     - allocation["committed_cents"]
                                     - allocation["paid_cents"]
                                     - allocation["expired_cents"])


def claim_matching(claim, tier):
    """Per-line rounding, then an exact sum of the rounded lines (PRD 3.7)."""
    rate = MATCH_RATE_PCT[tier]
    proofs = [p for p in store.all_rows("proofs") if p["claim_id"] == claim["id"]]
    proofs = store.ordered(proofs)
    matched_total = 0
    for proof in proofs:
        if proof["verified"]:
            line = cents(Decimal(proof["spend_amount_cents"]) * rate)
            proof["matched_line_cents"] = line
            matched_total += line
    approved = min(claim["requested_cents"], matched_total)
    return matched_total, approved


def claim_has_verified_proof(claim_id):
    for proof in store.all_rows("proofs"):
        if proof["claim_id"] == claim_id and proof["verified"]:
            return True
    return False


# ---------------------------------------------------------------------------
# tier scoring (PRD 3.9, two variants)
# ---------------------------------------------------------------------------
def scoring_cert_basis(partner_id, variant, period_end):
    from store import plus_days
    total = 0
    for rec in store.all_rows("certifications"):
        if rec["partner_id"] != partner_id or rec["status"] != "ACTIVE":
            continue
        if variant == "FINAL":
            horizon = plus_days(period_end, COVERAGE_HORIZON_DAYS)
            if not (rec["expires_at"] >= horizon):
                continue
        total += rec["credit_weight"]
    return total


def scoring_revenue(partner_id, variant, period_start, period_end):
    total = 0
    for order in store.all_rows("orders"):
        if order["partner_id"] != partner_id:
            continue
        if variant == "PROVISIONAL":
            if order["status"] not in ("PENDING", "INVOICED", "CREDITED"):
                continue
            instant = (order["invoiced_at"] if order["status"] in ("INVOICED", "CREDITED")
                       else order["created_at"])
        else:
            if order["status"] not in ("INVOICED", "CREDITED"):
                continue
            instant = order["invoiced_at"]
        if instant is None:
            continue
        if period_start <= instant <= period_end:
            total += order["invoice_amount_cents"]
    return total


def weighted_score(cert_basis, revenue_cents, marketing_pct):
    cert_component = Decimal(cert_basis) / CERT_CREDIT_TARGET
    if cert_component > ONE:
        cert_component = ONE
    revenue_component = Decimal(revenue_cents) / REVENUE_TARGET_CENTS
    if revenue_component > ONE:
        revenue_component = ONE
    marketing_component = dec(marketing_pct)
    exact = (WEIGHT_CERT * cert_component
             + WEIGHT_REVENUE * revenue_component
             + WEIGHT_MARKETING * marketing_component)
    return q2(exact)


def tier_from_gates(score, cert_basis, revenue_cents):
    if (score >= PLATINUM_SCORE_MIN and cert_basis >= PLATINUM_CERT_MIN
            and revenue_cents >= PLATINUM_REVENUE_MIN_CENTS):
        return "PLATINUM"
    if score >= GOLD_SCORE_MIN and cert_basis >= GOLD_CERT_MIN:
        return "GOLD"
    if score >= SILVER_SCORE_MIN and cert_basis >= SILVER_CERT_MIN:
        return "SILVER"
    return "REGISTERED"


def score_variant(partner, period_start, period_end, variant):
    cert_basis = scoring_cert_basis(partner["id"], variant, period_end)
    revenue = scoring_revenue(partner["id"], variant, period_start, period_end)
    recompute_marketing(partner)
    score = weighted_score(cert_basis, revenue, partner["marketing_attainment_pct"])
    tier = tier_from_gates(score, cert_basis, revenue)
    return cert_basis, revenue, score, tier
