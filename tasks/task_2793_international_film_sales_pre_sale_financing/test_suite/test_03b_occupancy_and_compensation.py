"""The compensating edges: reversing a receipt and lapsing a contract must put
every derived quantity back exactly where the forward operation found it.

Every test builds all of its own preconditions through the declared endpoints,
because each test runs against an empty database.
"""

from test_helpers import (
    COLLECTION_AGENT_USER,
    COLLECTION_AGENT_USER_ALT,
    FILM_BUDGET,
    assert_account_counters,
    assert_allocations,
    assert_buyer_exposure,
    assert_contract_axes,
    assert_created,
    assert_film_counters,
    assert_money,
    assert_object_response,
    assert_tier,
    contract_payload,
    distribute_payload,
    executed_contract_environment,
    find_by,
    get_success_data,
    lapse_payload,
    make_buyer_headers,
    make_collection_agent_headers,
    make_fr_territory,
    make_head_of_sales_headers,
    make_sales_agent_headers,
    make_tiers,
    milestone_by_label,
    read_account,
    read_agreement,
    read_buyer,
    read_contract,
    read_film,
    read_milestones,
    read_tiers,
    receipt_payload,
    reversal_payload,
    slate_with_published_valuation,
)

RECEIPT_SIGNATURE = 900000.00
RECEIPT_DELIVERY = 400000.00
COMMISSION_AFTER_BOTH = 130000.00
COMMISSION_AFTER_REVERSAL = 90000.00
COMMISSION_IF_RECOMPUTED = 97500.00
ACCRUED_ON_DELIVERY = 40000.00
COLLECTION_FEE_ALLOCATION = 6250.00
DISTRIBUTED = 136250.00
RESIDUAL = 363750.00
BALANCE_BEFORE_REVERSAL = 1163750.00
BALANCE_AFTER_REVERSAL = 763750.00


# ==========================================================================
# Reversing a receipt: cash and tiered commission restored with zero drift
# ==========================================================================
def _cash_env(api):
    """An EXECUTED contract with its four milestones and an OPEN account carrying a
    capped collection fee and an uncapped sales-commission tier, then two receipts
    in arrival order and one distribution of 500000.00."""
    env = executed_contract_environment(api)
    env["tiers"] = make_tiers(
        api,
        env["account"]["id"],
        [
            (1, "COLLECTION_FEE", 0.0125, 25000.00),
            (2, "SALES_COMMISSION", 1.00, 0.01),
        ],
    )
    env["milestone_signature"] = milestone_by_label(env, "ON_SIGNATURE")
    env["milestone_delivery"] = milestone_by_label(env, "ON_DELIVERY")
    get_success_data(
        api.post_receipt(
            env["milestone_signature"]["id"],
            receipt_payload(RECEIPT_SIGNATURE, "2026-08-05T00:00:00Z"),
            make_collection_agent_headers(COLLECTION_AGENT_USER),
        )
    )
    get_success_data(
        api.post_receipt(
            env["milestone_delivery"]["id"],
            receipt_payload(RECEIPT_DELIVERY, "2026-08-06T00:00:00Z"),
            make_collection_agent_headers(COLLECTION_AGENT_USER),
        )
    )
    env["run"] = get_success_data(
        api.distribute(
            env["account"]["id"],
            distribute_payload(500000.00),
            make_collection_agent_headers(COLLECTION_AGENT_USER),
        )
    )
    return env


def _reverse_delivery_receipt(api, env, as_user_id=COLLECTION_AGENT_USER_ALT):
    return api.reverse_receipt(
        env["milestone_delivery"]["id"],
        reversal_payload(),
        make_collection_agent_headers(as_user_id),
    )


def _repost_delivery_receipt(api, env, received_at="2026-08-07T00:00:00Z"):
    return api.post_receipt(
        env["milestone_delivery"]["id"],
        receipt_payload(RECEIPT_DELIVERY, received_at),
        make_collection_agent_headers(COLLECTION_AGENT_USER),
    )


def _commission_tier(api, account_id):
    return find_by(read_tiers(api, account_id), tier_type="SALES_COMMISSION")


def _agreement(api, env):
    return read_agreement(api, env["film"]["id"], env["agreement"]["id"])


def test_the_two_receipts_and_the_distribution_leave_the_account_conserved(api):
    """The second receipt accrues wholly at the first band and the account still balances.

    PRD: "A receipt of 400,000.00 posted when the prior total is 900,000.00 is charged entirely at the first-band rate; it is not treated as 100,000.00 at the first band plus 300,000.00 at the second."

    Design: Difficulty/compensating_invariant/reverse_receipt_restores_cash_and_tiered_commission_with_zero_drift
    """
    env = _cash_env(api)

    agreement = _agreement(api, env)
    assert_money(agreement["gross_collected_usd"], 1300000.00, "gross_collected_usd")
    assert_money(
        agreement["commission_earned_usd"], COMMISSION_AFTER_BOTH, "commission_earned_usd"
    )

    tier = _commission_tier(api, env["account"]["id"])
    assert_tier(tier, cap=COMMISSION_AFTER_BOTH)

    assert_allocations(
        env["run"], [COLLECTION_FEE_ALLOCATION, COMMISSION_AFTER_BOTH], tier_count=2
    )
    assert_money(env["run"]["amount_allocated_usd"], DISTRIBUTED, "amount_allocated_usd")
    assert_money(env["run"]["residual_usd"], RESIDUAL, "residual_usd")

    account = read_account(api, env["account"]["id"])
    assert_account_counters(
        account,
        receipts=1300000.00,
        distributed=DISTRIBUTED,
        balance=BALANCE_BEFORE_REVERSAL,
        run_count=1,
    )


def test_the_reversal_subtracts_the_stored_accrued_commission_not_a_recomputed_one(api):
    """Commission falls by the milestone's stored 40000.00, never by a fresh 32500.00.

    PRD: "The agreement's `gross_collected_usd` falls by the reversed amount, and its `commission_earned_usd` falls by exactly the milestone's stored `accrued_commission_usd` — not by a freshly recomputed figure, because the rate band in force at the time of the original receipt may no longer be the band a recomputation would pick."

    Design: Difficulty/compensating_invariant/reverse_receipt_restores_cash_and_tiered_commission_with_zero_drift
    """
    env = _cash_env(api)
    before = _agreement(api, env)
    assert_money(
        milestone_by_label(read_milestones(api, env["contract"]["id"]), "ON_DELIVERY")[
            "accrued_commission_usd"
        ],
        ACCRUED_ON_DELIVERY,
        "accrued_commission_usd",
    )

    reversed_milestone = assert_object_response(_reverse_delivery_receipt(api, env))
    assert reversed_milestone["status"] == "INVOICED"
    assert_money(reversed_milestone["received_amount_usd"], 0.00, "received_amount_usd")
    assert reversed_milestone["received_at"] is None
    assert reversed_milestone["received_by_user_id"] is None
    assert_money(
        reversed_milestone["accrued_commission_usd"], 0.00, "accrued_commission_usd"
    )

    after = _agreement(api, env)
    assert_money(after["gross_collected_usd"], RECEIPT_SIGNATURE, "gross_collected_usd")
    assert_money(
        after["commission_earned_usd"],
        COMMISSION_AFTER_REVERSAL,
        "commission_earned_usd",
    )
    assert abs(after["commission_earned_usd"] - COMMISSION_IF_RECOMPUTED) > 0.01, (
        "commission must fall by the stored accrual, not by a recomputed band figure"
    )
    assert_money(
        before["commission_earned_usd"] - after["commission_earned_usd"],
        ACCRUED_ON_DELIVERY,
        "commission removed by the reversal",
    )


def test_the_reversal_leaves_distributed_cash_alone_and_keeps_the_account_conserved(api):
    """Receipts fall, distributions do not, and the conservation identity still holds.

    PRD: "At every observable moment, `total_receipts_usd` minus `total_distributed_usd` minus `balance_usd` is exactly zero."

    Design: Difficulty/compensating_invariant/reverse_receipt_restores_cash_and_tiered_commission_with_zero_drift
    """
    env = _cash_env(api)
    assert_object_response(_reverse_delivery_receipt(api, env))

    account = read_account(api, env["account"]["id"])
    assert_account_counters(
        account,
        receipts=RECEIPT_SIGNATURE,
        distributed=DISTRIBUTED,
        balance=BALANCE_AFTER_REVERSAL,
        run_count=1,
    )

    tier = _commission_tier(api, env["account"]["id"])
    assert_tier(
        tier,
        recouped=COMMISSION_AFTER_BOTH,
        cap=COMMISSION_AFTER_REVERSAL,
        status="SATISFIED",
    )

    film = read_film(api, env["film"]["id"])
    assert_film_counters(film, collected=RECEIPT_SIGNATURE)

    contract = read_contract(api, env["contract"]["id"])
    assert_contract_axes(contract, collection="PARTIALLY_PAID")


def test_re_posting_the_identical_receipt_restores_every_figure_without_drift(api):
    """The round trip lands back on 1300000.00 and 130000.00 to the cent.

    PRD: "The `SALES_COMMISSION` tier's `cap_usd` is set to the agreement's new `commission_earned_usd`."

    Design: Difficulty/compensating_invariant/reverse_receipt_restores_cash_and_tiered_commission_with_zero_drift
    """
    env = _cash_env(api)
    assert_object_response(_reverse_delivery_receipt(api, env))

    reposted = assert_object_response(_repost_delivery_receipt(api, env))
    assert reposted["status"] == "RECEIVED"
    assert_money(reposted["received_amount_usd"], RECEIPT_DELIVERY, "received_amount_usd")
    assert_money(
        reposted["accrued_commission_usd"], ACCRUED_ON_DELIVERY, "accrued_commission_usd"
    )

    agreement = _agreement(api, env)
    assert_money(agreement["gross_collected_usd"], 1300000.00, "gross_collected_usd")
    assert_money(
        agreement["commission_earned_usd"], COMMISSION_AFTER_BOTH, "commission_earned_usd"
    )

    tier = _commission_tier(api, env["account"]["id"])
    assert_tier(tier, cap=COMMISSION_AFTER_BOTH, recouped=COMMISSION_AFTER_BOTH)

    account = read_account(api, env["account"]["id"])
    assert_account_counters(
        account,
        receipts=1300000.00,
        distributed=DISTRIBUTED,
        balance=BALANCE_BEFORE_REVERSAL,
        run_count=1,
    )


# ==========================================================================
# Lapsing a contract: exposure and commitment restored to their pre-offer values
# ==========================================================================
MG_DE = 2000000.00
MG_FR = 500000.00
GAP_AFTER_ACCEPT = 23500000.00
LIVE_NEGOTIATION_STATUSES = ("OFFERED", "COUNTERED", "ACCEPTED", "EXECUTED")


def _lapse_env(api):
    """An IN_MARKET picture with a PUBLISHED DE valuation, one AAA buyer with no
    contracts at all, and a second territory FR so both offers can coexist."""
    env = slate_with_published_valuation(api)
    env["territory_fr"] = make_fr_territory(api)
    return env


def _open_offer(api, env, territory_id, minimum_guarantee_usd):
    return api.create_contract(
        contract_payload(
            env["film"]["id"],
            env["buyer"]["id"],
            territory_id,
            read_buyer(api, env["buyer"]["id"])["version"],
            minimum_guarantee_usd=minimum_guarantee_usd,
        ),
        make_sales_agent_headers(),
    )


def _lapse(api, contract_id, reason):
    return api.lapse_contract(
        contract_id, lapse_payload(reason), make_head_of_sales_headers()
    )


def _live_pipeline_sum(api, contract_ids):
    """The gross pipeline recomputed from the contracts themselves, so the buyer's
    stored figure can be checked against its own definition."""
    total = 0.0
    for contract_id in contract_ids:
        contract = read_contract(api, contract_id)
        if contract["negotiation_status"] in LIVE_NEGOTIATION_STATUSES:
            total += contract["minimum_guarantee_usd"]
    return round(total, 2)


def test_an_offered_contract_loads_exposure_but_leaves_commitment_at_zero(api):
    """Two live offers build gross exposure while the picture's commitment stays 0.00.

    PRD: "`total_mg_committed_usd` is the sum of `minimum_guarantee_usd` across every pre-sale contract of this picture whose `negotiation_status` is either `ACCEPTED` or `EXECUTED`."

    Design: Difficulty/compensating_invariant/lapse_restores_buyer_exposure_and_film_commitment_to_their_pre_offer_values
    """
    env = _lapse_env(api)
    assert_buyer_exposure(read_buyer(api, env["buyer"]["id"]), gross=0.00, net=0.00)
    assert_film_counters(
        read_film(api, env["film"]["id"]), committed=0.00, gap=FILM_BUDGET
    )

    contract_de = assert_created(_open_offer(api, env, env["territory"]["id"], MG_DE))
    assert_buyer_exposure(read_buyer(api, env["buyer"]["id"]), gross=MG_DE)
    assert_film_counters(
        read_film(api, env["film"]["id"]), committed=0.00, gap=FILM_BUDGET
    )

    contract_fr = assert_created(_open_offer(api, env, env["territory_fr"]["id"], MG_FR))
    buyer = read_buyer(api, env["buyer"]["id"])
    assert_buyer_exposure(buyer, gross=MG_DE + MG_FR)
    assert_money(
        buyer["outstanding_exposure_usd"],
        _live_pipeline_sum(api, [contract_de["id"], contract_fr["id"]]),
        "outstanding_exposure_usd",
    )
    assert_film_counters(
        read_film(api, env["film"]["id"]), committed=0.00, gap=FILM_BUDGET
    )


def test_lapsing_from_accepted_reverses_both_ledgers_exactly(api):
    """Acceptance loads the commitment ledger and the lapse unloads it to the cent.

    PRD: "From `ACCEPTED` it additionally recomputes the picture's `total_mg_committed_usd` and `financing_gap_usd` and increments the picture's `version`, because an accepted commitment is being withdrawn."

    Design: Difficulty/compensating_invariant/lapse_restores_buyer_exposure_and_film_commitment_to_their_pre_offer_values
    """
    env = _lapse_env(api)
    assert_created(_open_offer(api, env, env["territory"]["id"], MG_DE))
    contract_fr = assert_created(_open_offer(api, env, env["territory_fr"]["id"], MG_FR))

    accepted = assert_object_response(
        api.accept_contract(contract_fr["id"], make_buyer_headers(env["buyer"]["id"]))
    )
    assert_contract_axes(accepted, negotiation="ACCEPTED")
    film_after_accept = read_film(api, env["film"]["id"])
    assert_film_counters(film_after_accept, committed=MG_FR, gap=GAP_AFTER_ACCEPT)

    lapsed = assert_object_response(
        _lapse(api, contract_fr["id"], "buyer withdrew after acceptance")
    )
    assert_contract_axes(lapsed, negotiation="LAPSED")

    film_after_lapse = read_film(api, env["film"]["id"])
    assert_film_counters(film_after_lapse, committed=0.00, gap=FILM_BUDGET)
    assert film_after_lapse["version"] > film_after_accept["version"], (
        "withdrawing an accepted commitment increments the picture's version"
    )
    assert_buyer_exposure(read_buyer(api, env["buyer"]["id"]), gross=MG_DE)


def test_lapsing_from_offered_clears_exposure_and_a_fresh_offer_rebuilds_it(api):
    """Both ledgers return to their pre-offer values and a new offer starts from there.

    PRD: "From `OFFERED` or from `COUNTERED` it simply ends the negotiation; the buyer's `outstanding_exposure_usd` and `net_unpaid_exposure_usd` are recomputed and the buyer's `version` increments."

    Design: Difficulty/compensating_invariant/lapse_restores_buyer_exposure_and_film_commitment_to_their_pre_offer_values
    """
    env = _lapse_env(api)
    contract_de = assert_created(_open_offer(api, env, env["territory"]["id"], MG_DE))
    contract_fr = assert_created(_open_offer(api, env, env["territory_fr"]["id"], MG_FR))
    get_success_data(
        api.accept_contract(contract_fr["id"], make_buyer_headers(env["buyer"]["id"]))
    )
    assert_object_response(_lapse(api, contract_fr["id"], "buyer withdrew after acceptance"))

    buyer_before = read_buyer(api, env["buyer"]["id"])
    lapsed_de = assert_object_response(
        _lapse(api, contract_de["id"], "offer expired unanswered")
    )
    assert_contract_axes(lapsed_de, negotiation="LAPSED")

    buyer_after = read_buyer(api, env["buyer"]["id"])
    assert_buyer_exposure(buyer_after, gross=0.00, net=0.00)
    assert buyer_after["version"] > buyer_before["version"], (
        "the lapse increments the buyer's version"
    )
    assert_film_counters(
        read_film(api, env["film"]["id"]), committed=0.00, gap=FILM_BUDGET
    )
    assert read_contract(api, contract_fr["id"])["negotiation_status"] == "LAPSED"

    fresh = assert_created(_open_offer(api, env, env["territory_fr"]["id"], MG_FR))
    assert_contract_axes(fresh, negotiation="OFFERED")
    buyer_final = read_buyer(api, env["buyer"]["id"])
    assert_buyer_exposure(buyer_final, gross=MG_FR)
    assert_money(
        buyer_final["outstanding_exposure_usd"],
        _live_pipeline_sum(
            api, [contract_de["id"], contract_fr["id"], fresh["id"]]
        ),
        "outstanding_exposure_usd",
    )
