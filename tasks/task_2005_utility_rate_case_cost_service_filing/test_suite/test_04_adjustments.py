"""Adjustment lifecycle: segregation of duties, terminal states, the
conserved adjusted-amount invariant, and status filtering (PRD §3.2, §4)."""
from test_helpers import (
    ApiErrorId,
    add_adjustment,
    add_entry,
    create_case,
    get_adjustment,
    get_entry,
    submit_entry,
    validate_error,
    validate_paginated,
    validate_success,
    verify_adjustment,
    TEST_USERS,
    make_utility_filer_headers,
)

UF = TEST_USERS["utility_filer_alice"]
STAFF = TEST_USERS["commission_staff"]
ALICE = make_utility_filer_headers("uf_alice")
BOB = make_utility_filer_headers("uf_bob")


def _case_with_entry():
    case = create_case()
    e1 = add_entry(case["id"], "900", "O_AND_M", 1000000000)
    return case, e1


def test_verify_withdrawn_adjustment_rejected(api):
    """PRD §3.2: "the adjustment must be in `PROPOSED` or `DISPUTED` (otherwise
    `ERR_INVALID_ADJUSTMENT_STATE`)" and "`ACCEPTED`, `REJECTED`, and `WITHDRAWN`
    are terminal states."

    Design: Corner/state_machines/verify_withdrawn_adjustment_rejected
    """
    case, e1 = _case_with_entry()
    a1 = add_adjustment(case["id"], e1["id"], 50000000, proposer_headers=ALICE)
    validate_success(api.withdraw_adjustment(a1["id"], ALICE), 200)
    # A different verifier rules out the segregation-of-duties check; the state
    # check is the deciding rule.
    res = api.verify_adjustment(a1["id"], BOB)
    validate_error(res, ApiErrorId.ERR_INVALID_ADJUSTMENT_STATE, expected_status=409)
    assert get_adjustment(a1["id"])["status"] == "WITHDRAWN"


def test_segregation_of_duties_on_verify(api):
    """PRD §3.2: "the verifier's `X-User-ID` must differ from
    `proposed_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)" and "On success
    the server sets `verified_by_user_id` to the caller, moves the adjustment to
    `VERIFIED`, and recomputes the entry's `adjusted_amount_cents`"
    PRD §3.2: "The server records the caller's `X-User-ID` into
    `proposed_by_user_id`, sets the status to `PROPOSED`"

    Design: Corner/validations/segregation_of_duties_on_verify
    """
    case, e1 = _case_with_entry()
    a1 = add_adjustment(case["id"], e1["id"], 50000000, proposer_headers=ALICE)
    assert a1["proposed_by_user_id"] == "uf_alice", "server-stamped from X-User-ID"
    res = api.verify_adjustment(a1["id"], ALICE)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    verified = validate_success(api.verify_adjustment(a1["id"], BOB), 200)
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == "uf_bob"


def test_list_status_filter_on_adjustments(api):
    """PRD §4: "List adjustments; filterable by rate_case_id, test_year_entry_id,
    status".

    Design: Corner/endpoints/list_status_filter_on_adjustments
    """
    case, e1 = _case_with_entry()
    submit_entry(e1["id"])
    a1 = add_adjustment(case["id"], e1["id"], 50000000,
                        reason="Annualize pension cost", proposer_headers=ALICE)
    verify_adjustment(a1["id"], BOB)
    a2 = add_adjustment(case["id"], e1["id"], -3000000,
                        reason="Normalize mild winter", proposer_headers=ALICE)
    validate_success(api.withdraw_adjustment(a2["id"], ALICE), 200)

    data, meta = validate_paginated(api.list_adjustments(
        UF, params={"rate_case_id": case["id"], "status": "VERIFIED"}))
    assert meta["total_count"] == 1 and data[0]["id"] == a1["id"]
    data, meta = validate_paginated(api.list_adjustments(
        UF, params={"rate_case_id": case["id"], "status": "WITHDRAWN"}))
    assert meta["total_count"] == 1 and data[0]["id"] == a2["id"]
    data, meta = validate_paginated(api.list_adjustments(
        UF, params={"rate_case_id": case["id"], "status": "PROPOSED"}))
    assert meta["total_count"] == 0
    data, meta = validate_paginated(api.list_adjustments(
        UF, params={"rate_case_id": case["id"]}))
    assert meta["total_count"] == 2


# ─── Difficulty: compensating_invariant / adjusted amount ────────────────────

def _setup_verified_adjustment_on_submitted_entry():
    case, e1 = _case_with_entry()
    submit_entry(e1["id"])
    a1 = add_adjustment(case["id"], e1["id"], 50000000, proposer_headers=ALICE)
    verify_adjustment(a1["id"], BOB)
    return case, e1, a1


def test_proposed_adjustment_counts_toward_adjusted_amount(api):
    """PRD §3.2: "The entry's adjusted amount is the booked amount plus the sum
    of `amount_cents` over all adjustments of that entry whose status is
    `PROPOSED`, `VERIFIED`, `DISPUTED`, or `ACCEPTED`; `WITHDRAWN` and `REJECTED`
    adjustments are excluded."

    Design: Difficulty/compensating_invariant/adjustment_propose_withdraw_conserves_adjusted_amount
    """
    case, e1, a1 = _setup_verified_adjustment_on_submitted_entry()
    assert get_entry(e1["id"])["adjusted_amount_cents"] == 1050000000, (
        "1,000,000,000 booked + 50,000,000 VERIFIED"
    )
    a2 = add_adjustment(case["id"], e1["id"], 10000000,
                        reason="Normalize storm O&M", proposer_headers=ALICE)
    assert get_entry(e1["id"])["adjusted_amount_cents"] == 1060000000, (
        "PROPOSED adjustment counts toward the entry total"
    )
    assert get_adjustment(a2["id"])["status"] == "PROPOSED"


def test_withdraw_restores_adjusted_amount_exactly(api):
    """PRD §3.2: "This recomputation is triggered by adjustment creation,
    verification, rejection, and withdrawal, and by the submit-filing acceptance
    cascade described in §3.3." and "`WITHDRAWN` and `REJECTED` adjustments are
    excluded."

    Design: Difficulty/compensating_invariant/adjustment_propose_withdraw_conserves_adjusted_amount
    """
    case, e1, a1 = _setup_verified_adjustment_on_submitted_entry()
    a2 = add_adjustment(case["id"], e1["id"], 10000000,
                        reason="Normalize storm O&M", proposer_headers=ALICE)
    assert get_entry(e1["id"])["adjusted_amount_cents"] == 1060000000
    withdrawn = validate_success(api.withdraw_adjustment(a2["id"], ALICE), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_entry(e1["id"])["adjusted_amount_cents"] == 1050000000, (
        "forward propose + compensating withdraw leave the conserved quantity "
        "unchanged — no drift"
    )
