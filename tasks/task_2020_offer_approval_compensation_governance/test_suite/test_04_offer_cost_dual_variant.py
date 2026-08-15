"""Dual-variant offer cost: cash vs fully-loaded divergence and budget use."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_offer_payload,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_draft_offer, create_offer_with_perks,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]


def _setup_offer_with_perks(api):
    req = create_open_requisition(HM, annual_budget_cents=50000000, headcount_authorized=2)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand A")
    offer, perks = create_offer_with_perks(
        req, cand,
        [
            {"kind": "SIGN_ON", "amount_cents": 1000000, "clawback_months": 12, "clawback_variant": "FULL_CLIFF"},
            {"kind": "RELOCATION", "amount_cents": 500000, "clawback_months": 12, "clawback_variant": "PRORATED_MONTHLY"},
        ],
        REC,
        base_cents=20000000, bonus_target_pct=0.10, equity_shares=10000, equity_fmv_cents=2500,
    )
    return req, offer


def test_offer_cost_variants_diverge_on_identical_terms(api):
    """PRD §3.3: "The **cash view**, exposed as `cash_only_annual_cost_cents`,
    is base plus `bonus_target_cents` plus the sign-on total plus the relocation
    total ... The **budget view**, exposed as `fully_loaded_annual_cost_cents`,
    adds annualized equity and the benefits load on top of the cash view."

    Design: Difficulty/dual_variant_calc/offer_cost_cash_vs_fully_loaded_divergence
    """
    req, offer = _setup_offer_with_perks(api)
    fetched = validate_success(api.get_offer(offer["id"], REC))
    # cash = 20000000 + 2000000 bonus + 1000000 sign-on + 500000 relocation
    assert fetched["cash_only_annual_cost_cents"] == 23500000
    # loaded = cash + round_half_up(10000*2500/4)=6250000 equity + round_half_up(0.30*22000000)=6600000 benefits
    assert fetched["fully_loaded_annual_cost_cents"] == 36350000
    assert fetched["bonus_target_cents"] == 2000000


def test_committed_budget_consumes_fully_loaded_variant_only(api):
    """PRD §3.3: "The budget view is the only variant the requisition's
    `committed_budget_cents` aggregate and the submission budget gate ever
    consult."
    PRD §2.8: "`committed_budget_cents`, the sum of the fully loaded annual cost
    over exactly those of its offers in `PENDING_APPROVAL`, `APPROVED`,
    `LETTER_GENERATED`, `EXTENDED`, `COUNTERED`, `ACCEPTED`, or `HIRED` status".

    Design: Difficulty/dual_variant_calc/offer_cost_cash_vs_fully_loaded_divergence
    """
    req, offer = _setup_offer_with_perks(api)
    submitted = validate_success(api.submit_offer(offer["id"], REC))
    assert submitted["status"] == "PENDING_APPROVAL"
    req_after = validate_success(api.get_requisition(req["id"], REC))
    assert req_after["committed_budget_cents"] == 36350000, (
        f"committed budget must consume the fully_loaded variant (36350000), "
        f"not cash_only (23500000); got {req_after['committed_budget_cents']}"
    )
