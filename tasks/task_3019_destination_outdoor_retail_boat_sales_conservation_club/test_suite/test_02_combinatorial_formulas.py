"""Depth tests: combinatorial formulas across different modes."""
from test_helpers import (
    CLUB_CARD_SPECIALIST,
    CREDIT_OFFICER,
    CREDIT_UNDERWRITER,
    PLATFORM_ADMIN,
    STORE_MANAGER,
    accept_appraisal,
    contract_deal,
    create_appraisal,
    create_boat_unit,
    create_deal,
    create_member,
    create_store,
    get_success_data,
    set_clock,
)


# ===========================================================================
# trade_in_credit_waterfall_branch  (queue A / combinatorial_formula)
# ===========================================================================

def _two_trade_units_identical_offers(api):
    """One member, two USED units of the same model, one carrying a prior title."""
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_ti@x.com",
                           full_name="Tate Inwood")
    unit_a = create_boat_unit(
        api, store["id"], stock_no="BU-TR-A", model_name="Bay 170",
        unit_price_cents=4_000_000, unit_condition="USED",
        hull_id_no="HINTRADEA001", prior_title_no="MO-TTL-OLD-0091",
        motor_price_cents=0, trailer_price_cents=0,
    )
    unit_b = create_boat_unit(
        api, store["id"], stock_no="BU-TR-B", model_name="Bay 170",
        unit_price_cents=4_000_000, unit_condition="USED",
        hull_id_no="HINTRADEB001", motor_price_cents=0, trailer_price_cents=0,
    )
    appraisal_a = create_appraisal(api, store["id"], member["id"], unit_a["id"],
                                   offer_amount_cents=50_000)
    appraisal_b = create_appraisal(api, store["id"], member["id"], unit_b["id"],
                                   offer_amount_cents=50_000)
    return store, member, unit_a, unit_b, appraisal_a, appraisal_b


def test_prior_title_penalty_subtracts_two_percent_on_an_identical_offer(api):
    """PRD §2.8.1: "The credited value is the offer amount, plus the rounded
    rebate, minus the rounded penalty."
    PRD §2.8.1: "the penalty rate is zero" when the trade unit carries no
    `prior_title_no`, and "when it does carry one the offer is multiplied by two
    hundred basis points."

    Design: Difficulty/combinatorial_formula/trade_in_credit_waterfall_branch
    """
    store, member, unit_a, unit_b, appraisal_a, appraisal_b = (
        _two_trade_units_identical_offers(api)
    )

    accepted_a = accept_appraisal(api, appraisal_a["id"])
    assert accepted_a["status"] == "ACCEPTED"
    assert accepted_a["accepted_credit_cents"] == 49_000, (
        "a 50000-cent offer on a unit with a prior title credits the offer minus "
        f"the 1000-cent penalty; got {accepted_a['accepted_credit_cents']}"
    )

    accepted_b = accept_appraisal(api, appraisal_b["id"])
    assert accepted_b["status"] == "ACCEPTED"
    assert accepted_b["accepted_credit_cents"] == 50_000, (
        "the identical offer on a unit with a null prior_title_no takes the "
        f"zero-penalty branch; got {accepted_b['accepted_credit_cents']}"
    )
    assert appraisal_a["offer_amount_cents"] == appraisal_b["offer_amount_cents"], (
        "both appraisals carry an identical 50000-cent offer"
    )


def test_active_card_rebate_moves_the_trade_credit_the_other_way(api):
    """PRD §2.8.1: "The first arc is a rebate on the offer: when the tendering
    member's card status is `ACTIVE` the offer is multiplied by three hundred
    basis points; for every other card status the rebate rate is zero."
    PRD §2.8.1: "the offered amount, plus the rounded rebate, minus the rounded
    penalty."

    Design: Difficulty/combinatorial_formula/trade_in_credit_waterfall_branch
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_ti_card@x.com",
                           full_name="Tate Cardholder")
    # Put the member's card into ACTIVE through the club card lifecycle.
    application = get_success_data(
        api.create_club_card_application(
            store["id"],
            {
                "member_id": member["id"],
                "card_product": "CLASSIC",
                "donation_match_bps": 2000,
                "underwriter_user_id": "uw_2201",
            },
            CLUB_CARD_SPECIALIST,
        ),
        201,
    )
    get_success_data(
        api.underwrite_club_card_application(
            application["id"], {"underwriter_user_id": "uw_2201"}, CREDIT_UNDERWRITER
        ),
        200,
    )
    get_success_data(
        api.decide_club_card_application(
            application["id"],
            {
                "decision_user_id": "off_7702",
                "decision": "APPROVED",
                "decision_reason": "independent review",
                "credit_limit_cents": 300_000,
            },
            CREDIT_OFFICER,
        ),
        200,
    )
    get_success_data(
        api.activate_club_card_application(application["id"], STORE_MANAGER), 200
    )
    active_member = get_success_data(api.get_member(member["id"], PLATFORM_ADMIN), 200)
    assert active_member["club_card_status"] == "ACTIVE"

    unit = create_boat_unit(
        api, store["id"], stock_no="BU-TR-C", model_name="Bay 170",
        unit_price_cents=4_000_000, unit_condition="USED",
        hull_id_no="HINTRADEC001", motor_price_cents=0, trailer_price_cents=0,
    )
    appraisal = create_appraisal(api, store["id"], member["id"], unit["id"],
                                 offer_amount_cents=50_000)
    accepted = accept_appraisal(api, appraisal["id"])
    assert accepted["accepted_credit_cents"] == 51_500, (
        "an ACTIVE card adds a rounded three percent rebate to the offer, so a "
        f"50000-cent offer credits 51500; got {accepted['accepted_credit_cents']}"
    )


# ===========================================================================
# boat_deal_priced_fee_nested_rounding_order  (queue A / combinatorial_formula)
# ===========================================================================

def _contracted_new_unit_deal(api):
    """Store, member, NEW 9000000/1800000/350000 unit and a CONTRACTED deal."""
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_rr@x.com",
                           full_name="Rae Rund")
    unit = create_boat_unit(api, store["id"], stock_no="BU-9001",
                            model_name="Angler 190", unit_price_cents=9_000_000,
                            motor_price_cents=1_800_000,
                            trailer_price_cents=350_000, unit_condition="NEW",
                            hull_id_no="HIN9001AA000")
    deal = create_deal(api, store["id"], member["id"], unit["id"])
    contracted = contract_deal(api, deal["id"], deal["version"])
    return store, member, unit, contracted


def test_contracted_price_restores_the_rigging_fee_and_the_full_tier_credit(api):
    """PRD §3.4: "The contract price is recomputed under the contracted variant — the rigging fee restored and the full tier credit applied — then the fee and tax relay runs on the settled price, and finally"

    Design: Difficulty/combinatorial_formula/boat_deal_priced_fee_nested_rounding_order
    """
    store, member, unit, deal = _contracted_new_unit_deal(api)
    assert deal["deal_stage"] == "CONTRACTED"
    assert deal["contract_price_cents"] == 11_220_000, (
        "the contracted settlement variant restores the 95000-cent rigging fee; "
        f"got {deal['contract_price_cents']}"
    )
    assert deal["total_fee_cents"] == 882_193, (
        "documentation fee 59900 plus the 4500-cent boat-title fee plus tax "
        f"817793; got {deal['total_fee_cents']}"
    )
    assert deal["balance_due_cents"] == 12_102_193, (
        "contract price plus total fee, with no funding or deposit yet; got "
        f"{deal['balance_due_cents']}"
    )


def test_contracted_balance_is_exactly_price_plus_fee_before_any_payment(api):
    """PRD §3.4: "`balance_due_cents` is recomputed as the contract price plus
    the total fee minus the funded amount minus the deposit, with the
    settlement variance excluded from the balance by design."

    Design: Difficulty/combinatorial_formula/boat_deal_priced_fee_nested_rounding_order
    """
    store, member, unit, deal = _contracted_new_unit_deal(api)
    assert deal["balance_due_cents"] == (
        deal["contract_price_cents"] + deal["total_fee_cents"]
        - deal["funded_amount_cents"] - deal["deposit_cents"]
    ), "the balance is the price plus the fee less the funded amount and deposit"
    assert deal["funded_amount_cents"] == 0, (
        "no funding record exists yet, so the funded amount reads zero"
    )
    assert deal["contract_price_cents"] == 11_220_000