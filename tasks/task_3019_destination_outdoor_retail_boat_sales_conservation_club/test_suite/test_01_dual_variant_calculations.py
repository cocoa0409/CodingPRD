"""Depth tests: dual-variant calculations across different entity domains."""
from test_helpers import (
    AGENCY_OPERATOR,
    DEAL_DESK_CLERK,
    REMIT_ADMIN,
    execute_recipe,
    get_success_data,
    setup_delivered_deal,
)


# ===========================================================================
# permit_fee_rounding_order_divergence  (queue A / dual_variant_calc)
# ===========================================================================

_PERMIT_FEE_CHAIN = [
    {
        "call": "POST /stores",
        "payload": {
            "name": "Ozark Flagship",
            "state_code": "MO",
            "dealer_license_no": "MO-DLR-4417",
            "dwell_capacity_minutes": 60000,
            "load_bays_total": 4,
        },
        "as": "PlatformAdmin",
        "captures": {"st_id": "$.data.id"},
    },
    {
        "call": "POST /_clock/set_current_utc",
        "payload": {"to_iso8601": "2026-09-10T00:00:00Z"},
        "as": "PlatformAdmin",
    },
    {
        "call": "POST /stores/${st_id}/members",
        "payload": {
            "email": "m_pf@x.com",
            "full_name": "Perry Fisher",
            "donation_opt_in": False,
        },
        "as": "Anonymous",
        "captures": {"m_id": "$.data.id"},
    },
    {
        "call": "POST /stores/${st_id}/permit-remit-batches",
        "payload": {
            "window_start_utc": "2026-09-01T00:00:00Z",
            "window_end_utc": "2026-09-30T00:00:00Z",
        },
        "as": "RemitAdmin",
        "captures": {"b_id": "$.data.id", "b_v": "$.data.version"},
    },
    {
        "call": "POST /stores/${st_id}/permit-sales",
        "payload": {
            "member_id": "${m_id}",
            "permit_type": "FISHING",
            "residency_class": "RESIDENT",
            "term_days": 7,
            "land_access_units": 3,
            "agent_user_id": "clerk_4471",
            "permit_remit_batch_id": "${b_id}",
            "expected_remit_batch_version": "${b_v}",
        },
        "as": "PermitClerk",
        "captures": {"sA_id": "$.data.id"},
    },
    {
        "call": "GET /stores/permit-remit-batches/${b_id}",
        "as": "RemitAdmin",
        "captures": {"b_v2": "$.data.version"},
    },
    {
        "call": "POST /stores/${st_id}/permit-sales",
        "payload": {
            "member_id": "${m_id}",
            "permit_type": "FISHING",
            "residency_class": "RESIDENT",
            "term_days": 7,
            "land_access_units": 35000,
            "agent_user_id": "clerk_4471",
            "permit_remit_batch_id": "${b_id}",
            "expected_remit_batch_version": "${b_v2}",
        },
        "as": "PermitClerk",
        "captures": {"sB_id": "$.data.id"},
    },
    {
        "call": "POST /stores/permit-remit-batches/${b_id}/seal",
        "payload": {"remitter_admin_user_id": "remit_9001"},
        "as": "RemitAdmin",
    },
    {
        "call": "POST /stores/permit-remit-batches/${b_id}/transmit",
        "payload": {},
        "as": "RemitAdmin",
    },
]


def _sealed_permit_batch(api):
    """Two FISHING/RESIDENT seven-day sales in one window, batch sealed and
    transmitted (the state from which a correction is permitted).

    Sale A carries 3 land-access units (3.75 cents of fractional add-on), so a
    revised fee moves it by exactly one cent between the two variants.
    """
    ctx = execute_recipe(api, _PERMIT_FEE_CHAIN)
    pre_batch = get_success_data(api.get_remit_batch(ctx["b_id"], REMIT_ADMIN), 200)
    return ctx, pre_batch


def test_correction_overwrites_the_sale_fee_and_leaves_the_frozen_snapshot_untouched(api):
    """PRD §2.8.1: "the add-on is rounded per unit before summation; a fishing,
    resident, seven-day sale with three land-access units prices at thirty-two
    hundred three cents under the per-unit variant against thirty-two hundred
    four under the exact-rational variant."
    PRD §2.8.1: "`gross_fee_cents` is the sum of those sales' `fee_cents` at
    the instant of sealing, and it never moves again."
    PRD §3.7: "for each sale whose revised fee was supplied the sale's
    `fee_cents` is overwritten with the revised figure and the sale moves from
    `REMITTED` to `CORRECTED`."

    Design: Difficulty/dual_variant_calc/permit_fee_rounding_order_divergence
    """
    ctx, pre_batch = _sealed_permit_batch(api)
    # PRD §2.8.1 pins the worked example: a FISHING/RESIDENT/seven-day sale with
    # three land-access units "prices at thirty-two hundred three cents under the
    # per-unit variant against thirty-two hundred four under the exact-rational
    # variant". Sale A therefore seals at 3204.
    frozen = pre_batch["gross_fee_cents"]
    sale_a = get_success_data(api.get_permit_sale(ctx["sA_id"], REMIT_ADMIN), 200)
    assert sale_a["fee_cents"] == 3204, (
        "the three-land-access-unit sale prices at 3204 under the exact-rational "
        f"variant; got {sale_a['fee_cents']}"
    )

    corrected = get_success_data(
        api.reject_correction_remit_batch(
            ctx["b_id"], {"sale_id": ctx["sA_id"], "revised_fee_cents": 3239},
            AGENCY_OPERATOR,
        ),
        200,
    )
    assert corrected["status"] == "CORRECTED"

    sale = get_success_data(api.get_permit_sale(ctx["sA_id"], REMIT_ADMIN), 200)
    assert sale["fee_cents"] == 3239, f"Expected 3239, got {sale['fee_cents']}"
    assert sale["status"] == "CORRECTED"

    batch = get_success_data(api.get_remit_batch(ctx["b_id"], REMIT_ADMIN), 200)
    assert batch["gross_fee_cents"] == frozen, (
        "gross_fee_cents is frozen at seal time and never moves again; got "
        f"{batch['gross_fee_cents']} against {frozen}"
    )
    assert batch["interpretative_gross_cents"] == frozen + (3239 - 3204), (
        "the live total is recomputed over the corrected fee; got "
        f"{batch['interpretative_gross_cents']}"
    )


def test_revised_fee_leaves_the_batch_variance_a_positive_one_cent(api):
    """PRD §2.8.1: "`remit_variance_cents` is the live total minus the frozen
    total, a signed delta written from the institution's perspective."
    PRD §3.7: "The live total is recomputed over the corrected fees while the
    frozen total stays exactly where the seal left it, and the variance is
    recomputed as the difference."

    Design: Difficulty/dual_variant_calc/permit_fee_rounding_order_divergence
    """
    ctx, pre_batch = _sealed_permit_batch(api)
    frozen = pre_batch["gross_fee_cents"]
    get_success_data(
        api.reject_correction_remit_batch(
            ctx["b_id"], {"sale_id": ctx["sA_id"], "revised_fee_cents": 3239},
            AGENCY_OPERATOR,
        ),
        200,
    )

    batch = get_success_data(api.get_remit_batch(ctx["b_id"], REMIT_ADMIN), 200)
    assert batch["remit_variance_cents"] == batch["interpretative_gross_cents"] - frozen, (
        "the variance is the live total minus the frozen snapshot; got "
        f"{batch['remit_variance_cents']}"
    )
    assert batch["remit_variance_cents"] > 0, (
        "the institution's perspective on a fee raise is a positive delta, the "
        "opposite polarity of the boat-deal settlement variance"
    )


# ===========================================================================
# boat_deal_settlement_basis_divergence  (queue A / dual_variant_calc)
# ===========================================================================

def test_delivered_deal_stores_the_final_minus_provisional_settlement_variance(api):
    """PRD §2.8.1: "The stored value is the final side minus the provisional
    side, a signed delta reported separately from the deal's balance."
    PRD §3.4: "Delivery flips the hull from `DEAL_PENDING` to `SOLD`, which in
    turn obliges every work order attached to that hull to proceed toward
    delivery, recomputes `settlement_variance_cents` as the final basis minus
    the provisional basis, and advances the store's version."
    PRD §2.8.1: "The final side is the contracted-variant contract price plus
    the relayed fees and tax computed on the delivered-settlement basis."
    PRD §2.8.1: "The provisional side is the quote-variant contract price."

    Design: Difficulty/dual_variant_calc/boat_deal_settlement_basis_divergence
    """
    ctx = setup_delivered_deal(api)
    deal = get_success_data(api.get_deal(ctx["deal"]["id"], DEAL_DESK_CLERK), 200)
    assert deal["deal_stage"] == "DELIVERED", (
        f"the deal should be auto-delivered, got {deal['deal_stage']}"
    )
    # PRD §2.8.1 pins the derivation: the provisional side is the quote-variant
    # price (11125000 here — the rigging fee excluded, the accessory discount
    # 25000 applied), and the final side is that same contracted-variant price
    # plus the fees and tax recomputed on the delivered-settlement basis.
    taxable = deal["contract_price_cents"] + 25_000 + 59_900
    delivered_fee = 59_900 + 4_500 + int((taxable * 725 + 5_000) // 10_000)
    expected = deal["contract_price_cents"] + delivered_fee - 11_125_000
    assert deal["settlement_variance_cents"] == expected, (
        "the variance is the delivered-settlement basis minus the quote-variant "
        f"price 11125000; expected {expected}, got "
        f"{deal['settlement_variance_cents']}"
    )
    assert deal["settlement_variance_cents"] > 0, (
        "the final basis exceeds the provisional basis whenever the rigging fee "
        "and the delivered-prep charge land"
    )


def test_delivered_deal_balance_excludes_the_settlement_variance_and_is_zero_once_funded(api):
    """PRD §2.8.1: "The stored value is the final side minus the provisional
    side, a signed delta reported separately from the deal's balance."
    PRD §3.4: "the recorded `funded_amount_cents` is set to the amount
    presented, and the balance is recomputed down to zero."

    Design: Difficulty/dual_variant_calc/boat_deal_settlement_basis_divergence
    """
    ctx = setup_delivered_deal(api)
    deal = get_success_data(api.get_deal(ctx["deal"]["id"], DEAL_DESK_CLERK), 200)
    assert deal["funding_status"] == "FUNDED"
    assert deal["balance_due_cents"] == 0, (
        "the deal was funded in full, so the balance reads zero; got "
        f"{deal['balance_due_cents']}"
    )
    assert deal["settlement_variance_cents"] > 0, (
        "the variance is reported separately from the balance and is not "
        f"absorbed into it; got {deal['settlement_variance_cents']}"
    )
    assert deal["balance_due_cents"] != -deal["settlement_variance_cents"], (
        "the settlement variance is deliberately excluded from the balance"
    )