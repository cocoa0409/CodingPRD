"""Household lifecycle, device trust, confidence score, and travel passes."""
from test_helpers import (
    assert_revenue_invariants,
    create_account,
    create_account_with_assigned_slot,
    create_account_with_device,
    get_account,
    get_success_data,
    purchase_slot,
    purchase_slot_payload,
    set_clock,
)


def test_extra_member_fee_prospective_vs_prorated_anchor_day(api):
    """PRD §3.6: "When the purchase lands exactly on the account's billing anchor
    day — the day-of-month equals `billing_anchor_day`, i.e. cycle day index 0 —
    the prospective full-cycle variant charges the full-cycle fee with no
    proration. On any other cycle day, the mid-cycle prorated variant charges the
    full-cycle fee multiplied by the number of days remaining in the 30-day cycle
    and divided by 30, rounded half-up to integer cents".

    Design: Difficulty/dual_variant_calc/extra_member_fee_prospective_vs_prorated
    """
    # PREMIUM allows two slots (STANDARD's cap of 1 would reject the second).
    account, owner_h = create_account(email="dv1@x.com", plan_tier="PREMIUM")  # anchor day 1 (2026-09-01)
    slot_a = purchase_slot(account, owner_h)
    assert slot_a["price_cents_snapshot"] == 599, "NA PREMIUM first slot on anchor day: round_half_up(799*0.75)=599"

    set_clock("2026-09-16T00:00:00Z")  # cycle day index 15
    fresh = get_account(account["id"])
    slot_b = get_success_data(
        api.purchase_slot(
            account["id"],
            purchase_slot_payload(account["owner_member_id"], fresh["version"]),
            owner_h,
        )
    )
    assert slot_b["price_cents_snapshot"] == 400, "prorated: full-cycle (599+200 surcharge)=799; round_half_up(799*15/30)=400"
    assert slot_b["price_cents_snapshot"] != slot_a["price_cents_snapshot"]

    after = get_account(account["id"])
    assert after["extra_member_billed_cents"] == 999


def test_extra_member_fee_prospective_vs_prorated_index(api):
    """PRD §3.6: "`slot_index` is 1 plus the count of the account's slots in
    `OFFERED` or `ACTIVE` immediately before this purchase — so the first slot
    pays no surcharge, the second pays 200, and so on." On the anchor day the
    prospective full-cycle variant charges the full-cycle fee with no proration.

    Design: Difficulty/dual_variant_calc/extra_member_fee_prospective_vs_prorated
    """
    # PREMIUM allows two slots so the slot-index surcharge is observable.
    account, owner_h = create_account(email="dv1b@x.com", plan_tier="PREMIUM")
    slot_a = purchase_slot(account, owner_h)
    slot_b = purchase_slot(account, owner_h)
    assert slot_a["slot_index"] == 1
    assert slot_a["price_cents_snapshot"] == 599, "round_half_up(799*0.75)=599, no surcharge"
    assert slot_b["slot_index"] == 2
    assert slot_b["price_cents_snapshot"] == 799, "599 + 200 surcharge"


def test_household_confidence_strict_vs_lenient_no_network(api):
    """PRD §3.3: "The strict variant caps the total at 50 when the network
    fingerprint does not match — so without a network match, geo plus fresh
    recency alone can never exceed 50 — and applies no cap otherwise. The lenient
    variant applies no cap at all, so geo plus fresh recency can reach 60."

    Design: Difficulty/dual_variant_calc/household_confidence_strict_vs_lenient
    """
    account, household, device, owner_h = create_account_with_device(
        email="dv2@x.com",
        device_network="fp-away-9",
        device_geo="geo-home-1",
        trust=False,
    )
    conf = get_success_data(api.get_device_confidence(device["id"], owner_h))
    assert conf["network_match"] is False
    assert conf["geo_match"] is True
    assert conf["recency_score"] == 30
    assert conf["strict_pct"] == 50
    assert conf["lenient_pct"] == 60
    assert conf["strict_pct"] != conf["lenient_pct"]


def test_household_confidence_full_match_both_variants(api):
    """PRD §3.3: "A device whose `network_fingerprint` equals the household's
    `network_fingerprint` contributes 40 points; a device whose `geo_cell` equals
    the household's `geo_cell` contributes 30 points. Recency contributes a
    further 30 points when the last signal is at most 7 days old". With all three
    matching, both variants total 100 (the strict cap only applies without a
    network match).

    Design: Difficulty/dual_variant_calc/household_confidence_strict_vs_lenient
    """
    account, household, device, owner_h = create_account_with_device(
        email="dv2b@x.com", trust=False
    )
    conf = get_success_data(api.get_device_confidence(device["id"], owner_h))
    assert conf["network_match"] is True
    assert conf["geo_match"] is True
    assert conf["recency_score"] == 30
    assert conf["strict_pct"] == 100
    assert conf["lenient_pct"] == 100


def test_slot_fee_tiered_multi_input_emea_premium(api):
    """PRD §3.6: "Start from the regional base fee: 799 cents for `NA`, 299 for
    `LATAM`, 499 for `EMEA`, and 349 for `APAC`. Apply the tier multiplier —
    `STANDARD` accounts pay the base unchanged (multiplier 1.0), `PREMIUM`
    accounts pay three quarters of the base (multiplier 0.75) — rounding half-up
    to integer cents ... Then add a per-slot surcharge of 200 cents multiplied by
    one less than the slot's index".

    Design: Difficulty/combinatorial_formula/slot_fee_tiered_multi_input
    """
    account, owner_h = create_account(email="cf1@x.com", region_code="EMEA", plan_tier="PREMIUM")
    slot_1 = purchase_slot(account, owner_h)
    slot_2 = purchase_slot(account, owner_h)

    assert slot_1["price_cents_snapshot"] == 374, "round_half_up(499*0.75)=374"
    assert slot_1["slot_index"] == 1
    assert slot_2["price_cents_snapshot"] == 574, "374 + 200 surcharge"
    assert slot_2["slot_index"] == 2

    after = get_account(account["id"])
    assert after["extra_member_billed_cents"] == 948


def test_slot_fee_tiered_multi_input_region_bases(api):
    """PRD §3.6: "Start from the regional base fee: 799 cents for `NA`, 299 for
    `LATAM`, 499 for `EMEA`, and 349 for `APAC`. Apply the tier multiplier ...
    `PREMIUM` accounts pay three quarters of the base (multiplier 0.75)". First
    slot on the anchor day pays no surcharge, exposing the region/tier base.

    Design: Difficulty/combinatorial_formula/slot_fee_tiered_multi_input
    """
    latam, latam_h = create_account(email="cf1c@x.com", region_code="LATAM", plan_tier="PREMIUM")
    slot = purchase_slot(latam, latam_h)
    assert slot["price_cents_snapshot"] == 224, "round_half_up(299*0.75)=224"

    apac, apac_h = create_account(email="cf1d@x.com", region_code="APAC", plan_tier="STANDARD")
    slot = purchase_slot(apac, apac_h)
    assert slot["price_cents_snapshot"] == 349, "APAC STANDARD base unchanged"


def test_revoke_credit_per_day_rounding(api):
    """PRD §3.6: "first compute the per-day rate by dividing `price_cents_snapshot`
    by 30 and rounding half-up to integer cents, then multiply that per-day rate
    by the number of days remaining in the current cycle (30 minus the current
    cycle day index). The rounding order is pinned: the per-day rate is rounded to
    integer cents first, then multiplied — computing the unrounded product and
    rounding once at the end is a different, forbidden order."

    Design: Difficulty/combinatorial_formula/revoke_credit_per_day_rounding
    """
    account, owner_h = create_account(email="cf2@x.com")  # created 2026-09-01, anchor day 1
    set_clock("2026-09-16T00:00:00Z")  # cycle day index 15 at purchase
    slot = purchase_slot(account, owner_h)
    assert slot["price_cents_snapshot"] == 400, "mid-cycle: round_half_up(799*15/30)=400"
    get_success_data(
        api.assign_slot(slot["id"], {"email": "extra-cf2@x.com", "display_name": "Extra CF2", "member_region": "NA"}, owner_h)
    )

    set_clock("2026-09-24T00:00:00Z")  # day index 23; 23-15=8, outside the 7-day window
    revoked = get_success_data(api.revoke_slot(slot["id"], owner_h))
    assert revoked["status"] == "REVOKED"
    assert revoked["credit_cents"] == 91, "round_half_up(400/30)=13 per day; 13*(30-23)=13*7=91"

    after = get_account(account["id"])
    assert after["extra_member_credit_cents"] == 91
    assert after["extra_member_net_revenue_cents"] == 309
    assert_revenue_invariants(after)


def test_revoke_credit_full_window_returns_full_price(api):
    """PRD §3.6: "If the revocation occurs within 7 cycle-days of the slot's
    `purchased_day` — the current cycle day index minus `purchased_day` is at most
    7 — the credit equals the full `price_cents_snapshot`."

    Design: Difficulty/combinatorial_formula/revoke_credit_per_day_rounding
    """
    account, slot, extra_id, owner_h = create_account_with_assigned_slot(
        email="cf2b@x.com", extra_email="extra-cf2b@x.com"
    )
    set_clock("2026-09-05T00:00:00Z")  # day index 4, inside the full-credit window
    revoked = get_success_data(api.revoke_slot(slot["id"], owner_h))
    assert revoked["status"] == "REVOKED"
    assert revoked["credit_cents"] == 799

    after = get_account(account["id"])
    assert after["extra_member_billed_cents"] == 799
    assert after["extra_member_credit_cents"] == 799
    assert after["extra_member_net_revenue_cents"] == 0
