"""Perks: state locking, hard caps, clawback quote variants and rounding."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_perk_payload,
    create_open_requisition, create_candidate_recruited, create_standard_peers,
    create_draft_offer, create_offer_with_perks,
)

HM = TEST_USERS["hm_headers"]
REC = TEST_USERS["recruiter_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


def _draft_offer(api, base_cents=18000000):
    req = create_open_requisition(HM)
    cand = create_candidate_recruited(REC)
    offer = create_draft_offer(req, cand, REC, base_cents=base_cents)
    return req, cand, offer


def test_perk_locked_after_submit_rejected(api):
    """PRD §3.4: "Perks attach to an offer while it is still malleable — in
    `DRAFT` or `RETURNED` only; an attempt in any other status is rejected with
    `ERR_PERK_STATE_LOCKED`."
    PRD §3.4: "Submission locks `DRAFT` perks to `LOCKED`".

    Design: Corner/validations/perk_locked_after_submit_rejected
    """
    req = create_open_requisition(HM)
    create_standard_peers()
    cand = create_candidate_recruited(REC, full_name="Cand PL")
    offer, perks = create_offer_with_perks(
        req, cand,
        [{"kind": "RELOCATION", "amount_cents": 500000, "clawback_months": 12, "clawback_variant": "PRORATED_MONTHLY"}],
        REC, base_cents=18000000,
    )
    validate_success(api.submit_offer(offer["id"], REC))
    resp = api.create_perk(
        offer["id"],
        create_perk_payload(kind="SIGN_ON", amount_cents=100000, clawback_months=6),
        REC,
    )
    validate_error(resp, ApiErrorId.ERR_PERK_STATE_LOCKED)
    perks_after = validate_success(api.list_perks(offer["id"], REC))
    assert perks_after[0]["id"] == perks[0]["id"]
    assert perks_after[0]["status"] == "LOCKED"


def test_signon_hard_cap_rejected(api):
    """PRD §3.4: "A single sign-on perk may not exceed 2,500,000 cents
    (twenty-five thousand dollars); a larger amount is rejected with
    `ERR_SIGNON_EXCEEDS_HARD_CAP`."

    Design: Corner/validations/signon_hard_cap_rejected
    """
    req, cand, offer = _draft_offer(api)
    resp = api.create_perk(
        offer["id"], create_perk_payload(kind="SIGN_ON", amount_cents=2500001), REC
    )
    validate_error(resp, ApiErrorId.ERR_SIGNON_EXCEEDS_HARD_CAP)
    ok = validate_success(
        api.create_perk(offer["id"], create_perk_payload(kind="SIGN_ON", amount_cents=2500000), REC),
        expected_status=201,
    )
    assert ok["amount_cents"] == 2500000


def test_clawback_full_cliff_vs_prorated_divergence(api):
    """PRD §3.4: "Under `FULL_CLIFF`, departure before completing the full
    `clawback_months` window repays the entire `amount_cents`" and "In between,
    the calculation is installment-first: the per-month installment is
    `amount_cents` divided by `clawback_months` rounded half up to whole cents,
    and the repayment is that rounded installment multiplied by the number of
    unworked months."

    Design: Difficulty/dual_variant_calc/clawback_full_cliff_vs_prorated_divergence
    """
    req, cand, offer = _draft_offer(api)
    offer, perks = create_offer_with_perks(
        req, cand,
        [
            {"kind": "SIGN_ON", "amount_cents": 1000100, "clawback_months": 3, "clawback_variant": "FULL_CLIFF"},
            {"kind": "RELOCATION", "amount_cents": 1000100, "clawback_months": 3, "clawback_variant": "PRORATED_MONTHLY"},
        ],
        REC, base_cents=18000000,
    )
    cliff_id, prorated_id = perks[0]["id"], perks[1]["id"]
    q_cliff = validate_success(api.get_clawback_quote(cliff_id, ADMIN, months_worked=1))
    q_prorated = validate_success(api.get_clawback_quote(prorated_id, ADMIN, months_worked=1))
    assert q_cliff["repayment_cents"] == 1000100
    assert q_prorated["repayment_cents"] == 666734
    assert q_cliff["repayment_cents"] != q_prorated["repayment_cents"]


def test_clawback_variants_converge_at_window_completion(api):
    """PRD §3.4: "Under `FULL_CLIFF`, departure before completing the full
    `clawback_months` window repays the entire `amount_cents`; at or beyond the
    window the repayment is zero — there is no proration." and "Under
    `PRORATED_MONTHLY`, the repayment is zero once `months_worked` reaches
    `clawback_months`" — the two variants diverge inside the window but agree
    at zero once it completes.

    Design: Difficulty/dual_variant_calc/clawback_full_cliff_vs_prorated_divergence
    """
    req, cand, offer = _draft_offer(api)
    offer, perks = create_offer_with_perks(
        req, cand,
        [
            {"kind": "SIGN_ON", "amount_cents": 1000100, "clawback_months": 3, "clawback_variant": "FULL_CLIFF"},
            {"kind": "RELOCATION", "amount_cents": 1000100, "clawback_months": 3, "clawback_variant": "PRORATED_MONTHLY"},
        ],
        REC, base_cents=18000000,
    )
    cliff_id, prorated_id = perks[0]["id"], perks[1]["id"]
    # inside the window the variants diverge
    q_cliff_1 = validate_success(api.get_clawback_quote(cliff_id, ADMIN, months_worked=1))
    q_pro_1 = validate_success(api.get_clawback_quote(prorated_id, ADMIN, months_worked=1))
    assert q_cliff_1["repayment_cents"] == 1000100
    assert q_pro_1["repayment_cents"] == 666734
    # at window completion both are zero
    q_cliff_3 = validate_success(api.get_clawback_quote(cliff_id, ADMIN, months_worked=3))
    q_pro_3 = validate_success(api.get_clawback_quote(prorated_id, ADMIN, months_worked=3))
    assert q_cliff_3["repayment_cents"] == 0
    assert q_pro_3["repayment_cents"] == 0


def test_clawback_installment_rounding_order(api):
    """PRD §3.4: "Under `PRORATED_MONTHLY`, the repayment is zero once
    `months_worked` reaches `clawback_months`, and it is the full `amount_cents`
    when `months_worked` is zero — a special case that skips the installment
    math entirely." and "a 1,000,100-cent perk over a three-month window quoted
    after one month of service yields an installment of 333,367 cents and a
    repayment of 666,734 cents, whereas rounding only at the end would yield
    666,733 cents — the installment-first result is authoritative."

    Design: Difficulty/combinatorial_formula/clawback_installment_rounding_order
    """
    req, cand, offer = _draft_offer(api)
    offer, perks = create_offer_with_perks(
        req, cand,
        [{"kind": "RELOCATION", "amount_cents": 1000100, "clawback_months": 3, "clawback_variant": "PRORATED_MONTHLY"}],
        REC, base_cents=18000000,
    )
    perk_id = perks[0]["id"]
    q0 = validate_success(api.get_clawback_quote(perk_id, ADMIN, months_worked=0))
    q1 = validate_success(api.get_clawback_quote(perk_id, ADMIN, months_worked=1))
    q3 = validate_success(api.get_clawback_quote(perk_id, ADMIN, months_worked=3))
    assert q0["repayment_cents"] == 1000100
    assert q1["repayment_cents"] == 666734
    assert q3["repayment_cents"] == 0


def test_clawback_full_cliff_window_boundary(api):
    """PRD §3.4: "Under `FULL_CLIFF`, departure before completing the full
    `clawback_months` window repays the entire `amount_cents`; at or beyond the
    window the repayment is zero — there is no proration."

    Design: Difficulty/combinatorial_formula/clawback_installment_rounding_order
    """
    req, cand, offer = _draft_offer(api)
    offer, perks = create_offer_with_perks(
        req, cand,
        [{"kind": "SIGN_ON", "amount_cents": 1000100, "clawback_months": 3, "clawback_variant": "FULL_CLIFF"}],
        REC, base_cents=18000000,
    )
    perk_id = perks[0]["id"]
    q2 = validate_success(api.get_clawback_quote(perk_id, ADMIN, months_worked=2))
    q3 = validate_success(api.get_clawback_quote(perk_id, ADMIN, months_worked=3))
    assert q2["repayment_cents"] == 1000100
    assert q3["repayment_cents"] == 0
