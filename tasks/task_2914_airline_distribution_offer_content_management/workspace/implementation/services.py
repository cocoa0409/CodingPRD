"""Domain services: derived state, pricing, ledgers and cascades."""
from datetime import timedelta

import calc
from store import bump, db, now, sort_key


# ---------------------------------------------------------------------------
# Derived / clock-dependent state
# ---------------------------------------------------------------------------
def contract_validity_state(contract):
    """PENDING / IN_EFFECT / LAPSED against the logical clock (half-open)."""
    clock = now()
    if clock < contract["effective_from"]:
        return "PENDING"
    if clock < contract["effective_to"]:
        return "IN_EFFECT"
    return "LAPSED"


def lazy_expire_offer(offer):
    """PRD 3.5: at-or-after expires_at, a live offer becomes EXPIRED first."""
    if offer["status"] in ("CONSTRUCTED", "PUBLISHED") and now() >= offer["expires_at"]:
        offer["status"] = "EXPIRED"
        bump(offer)
    return offer


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def surcharge_rules_for(channel_id):
    rules = [r for r in db.surcharge_rules.values() if r["channel_id"] == channel_id]
    rules.sort(key=lambda r: (r["threshold_cents"], r["created_at"], r["_seq"]))
    return rules


def ancillary_by_code(code):
    for product in db.ancillaries.values():
        if product["ancillary_code"] == code:
            return product
    return None


def bundle_by_code(code):
    for bundle in db.bundles.values():
        if bundle["bundle_code"] == code:
            return bundle
    return None


def offer_items_for(offer_id):
    items = [i for i in db.offer_items.values() if i["offer_id"] == offer_id]
    items.sort(key=lambda i: i["sequence"])
    return items


def signed_agreement_for(partner_id, channel_id):
    matches = [
        a for a in db.agreements.values()
        if a["partner_id"] == partner_id
        and a["channel_id"] == channel_id
        and a["status"] == "SIGNED"
    ]
    matches.sort(key=sort_key)
    return matches[-1] if matches else None


def agreements_for_pair(partner_id, channel_id, statuses):
    matches = [
        a for a in db.agreements.values()
        if a["partner_id"] == partner_id
        and a["channel_id"] == channel_id
        and a["status"] in statuses
    ]
    matches.sort(key=sort_key)
    return matches


def tests_for_certification(certification_id):
    tests = [t for t in db.connectivity_tests.values()
             if t["certification_id"] == certification_id]
    tests.sort(key=sort_key)
    return tests


def scheduled_tests_on_env(env_code, exclude_certification=None):
    result = []
    for test in db.connectivity_tests.values():
        if test["status"] != "SCHEDULED":
            continue
        cert = db.certifications.get(test["certification_id"])
        if cert is None or cert["env_code"] != env_code:
            continue
        result.append(test)
    result.sort(key=sort_key)
    return result


# ---------------------------------------------------------------------------
# Offer pricing (C1 + C2)
# ---------------------------------------------------------------------------
def price_offer_lines(channel, filing, bundle, alacarte_codes):
    """Returns (lines, subtotal_cents, surcharge_cents, total_cents).

    Lines are returned in final `sequence` order: FARE, BUNDLE_ANCILLARY by
    item_code ASC, ANCILLARY by item_code ASC, then SURCHARGE in evaluation
    order. Every line is rounded to whole cents BEFORE any summation.
    """
    markup = channel["content_markup_pct"]
    lines = []

    lines.append({
        "item_type": "FARE",
        "item_code": filing["fare_basis_code"],
        "list_amount_cents": filing["base_amount_cents"],
        "net_amount_cents": calc.line_net_amount(
            filing["base_amount_cents"], None, markup),
        "refundable": filing["refundable"],
    })

    if bundle is not None:
        for code in sorted(bundle["ancillary_codes"]):
            product = ancillary_by_code(code)
            lines.append({
                "item_type": "BUNDLE_ANCILLARY",
                "item_code": code,
                "list_amount_cents": product["list_amount_cents"],
                "net_amount_cents": calc.line_net_amount(
                    product["list_amount_cents"],
                    bundle["bundle_discount_pct"], markup),
                "refundable": product["refundable"],
            })

    for code in sorted(alacarte_codes or []):
        product = ancillary_by_code(code)
        lines.append({
            "item_type": "ANCILLARY",
            "item_code": code,
            "list_amount_cents": product["list_amount_cents"],
            "net_amount_cents": calc.line_net_amount(
                product["list_amount_cents"], None, markup),
            "refundable": product["refundable"],
        })

    subtotal = sum(line["net_amount_cents"] for line in lines)
    fare_base = lines[0]["net_amount_cents"]
    ancillary_base = sum(
        line["net_amount_cents"] for line in lines
        if line["item_type"] in ("ANCILLARY", "BUNDLE_ANCILLARY"))

    surcharge_total = 0
    for rule in surcharge_rules_for(channel["id"]):
        if rule["item_scope"] == "FARE":
            scope_base = fare_base
        elif rule["item_scope"] == "ANCILLARY":
            scope_base = ancillary_base
        else:
            scope_base = subtotal
        emitted = calc.surcharge_line(scope_base, rule)
        if emitted is None:
            continue
        raw, clamped = emitted
        lines.append({
            "item_type": "SURCHARGE",
            "item_code": rule["surcharge_code"],
            "list_amount_cents": raw,
            "net_amount_cents": clamped,
            "refundable": False,
        })
        surcharge_total += clamped

    return lines, subtotal, surcharge_total, subtotal + surcharge_total


def offer_expiry(created_at):
    return created_at + timedelta(minutes=calc.OFFER_TTL_MINUTES)


# ---------------------------------------------------------------------------
# Ledgers (C3 + C4)
# ---------------------------------------------------------------------------
def paid_orders_on_channel(channel_id):
    return [o for o in db.orders.values()
            if o["channel_id"] == channel_id and o["payment_status"] == "PAID"]


def recompute_booking_count(channel):
    channel["booking_count"] = len(paid_orders_on_channel(channel["id"]))
    bump(channel)
    return channel


def recompute_channel_costs(channel):
    """Both distribution-cost variants, on the current PAID population."""
    paid = paid_orders_on_channel(channel["id"])
    channel["booking_count"] = len(paid)
    signed = [a for a in db.agreements.values()
              if a["channel_id"] == channel["id"] and a["status"] == "SIGNED"]
    channel["activity_cost_cents"] = calc.activity_cost(channel, paid, signed)
    channel["cost_per_booking_flat_cents"] = calc.cost_per_booking_flat(
        channel["monthly_platform_fee_cents"], channel["booking_count"])
    channel["cost_per_booking_activity_cents"] = calc.cost_per_booking_activity(
        channel["activity_cost_cents"], channel["booking_count"])
    bump(channel)
    return channel


def recompute_agreement_accrual(agreement, count_downgrade):
    channel = db.channels[agreement["channel_id"]]
    accrued, tier = calc.agency_incentive_accrual(
        agreement["cumulative_net_revenue_cents"],
        agreement["agreed_incentive_pct"],
        channel["incentive_multiplier"],
        agreement["incentive_cap_cents"],
    )
    previous_tier = agreement["incentive_tier"]
    agreement["incentive_accrued_cents"] = accrued
    agreement["incentive_tier"] = tier
    if count_downgrade and calc.tier_ranks_below(tier, previous_tier):
        agreement["tier_downgrade_count"] = agreement["tier_downgrade_count"] + 1
    bump(agreement)
    return agreement


# ---------------------------------------------------------------------------
# Certification scoring (C5)
# ---------------------------------------------------------------------------
def refresh_readiness(cert):
    tests = tests_for_certification(cert["id"])
    strict, provisional = calc.readiness_scores(tests, cert["mandatory_failed_count"])
    cert["readiness_score_strict"] = strict
    cert["readiness_score_provisional"] = provisional
    return cert


def recompute_reserved_minutes(cert):
    total = 0
    for test in tests_for_certification(cert["id"]):
        if test["status"] == "SCHEDULED":
            total += test["duration_minutes"]
    cert["reserved_test_minutes"] = total
    return cert


# ---------------------------------------------------------------------------
# Cascades (PRD 2.9): destructive downward, never resurrecting upward
# ---------------------------------------------------------------------------
LIVE_OFFER_STATES = ("CONSTRUCTED", "PUBLISHED")


def withdraw_offers_for_filing(filing_id):
    withdrawn = []
    for offer in sorted(db.offers.values(), key=sort_key):
        if offer["fare_filing_id"] == filing_id and offer["status"] in LIVE_OFFER_STATES:
            offer["status"] = "WITHDRAWN"
            bump(offer)
            withdrawn.append(offer)
    return withdrawn


def withdraw_offers_for_pair(partner_id, channel_id):
    withdrawn = []
    for offer in sorted(db.offers.values(), key=sort_key):
        if (offer["partner_id"] == partner_id
                and offer["channel_id"] == channel_id
                and offer["status"] in LIVE_OFFER_STATES):
            offer["status"] = "WITHDRAWN"
            bump(offer)
            withdrawn.append(offer)
    return withdrawn


def suspend_agreements_for_pair(partner_id, channel_id):
    """SIGNED -> SUSPENDED plus the offer withdrawal hop it causes."""
    for agreement in agreements_for_pair(partner_id, channel_id, ("SIGNED",)):
        agreement["status"] = "SUSPENDED"
        bump(agreement)
        withdraw_offers_for_pair(agreement["partner_id"], agreement["channel_id"])


def reinstate_agreements_for_pair(partner_id, channel_id):
    """SUSPENDED -> SIGNED; withdrawn offers are NOT resurrected."""
    for agreement in agreements_for_pair(partner_id, channel_id, ("SUSPENDED",)):
        agreement["status"] = "SIGNED"
        bump(agreement)


def set_partner_certification_status(partner, status):
    partner["certification_status"] = status
    bump(partner)
    return partner
