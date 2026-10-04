"""Consumer restitution: estimated vs final payout variants, the empty
validated set, validation bounds, claimant terminal states, claim-window
boundaries, and the one-shot compute lock.
"""
from test_helpers import (
    ApiErrorId,
    PAST_APPROPRIATION_WINDOW,
    PAST_CLAIM_WINDOW,
    api_client,
    adjudicate_claimant,
    assert_line_gross_invariant,
    compute_restitution,
    create_claimant_payload,
    fund_world,
    get_allocation_line,
    get_settlement,
    register_and_validate_claimants,
    register_claimant,
    request_disbursement,
    set_clock,
    setup_executed_world,
    validate_claimant_payload,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
FUND_ADMIN = TEST_USERS["fund_administrator_headers"]


def _claimants_by_id(settlement_id):
    data, _ = validate_paginated(
        api_client.list_settlement_claimants(settlement_id, CHAIR)
    )
    return {c["id"]: c for c in data}


def test_estimated_vs_final_payout_divergence():
    """PRD section 3.6: "A `VALIDATED` decision carries
    `validated_loss_cents` ... and moves `REGISTERED` → `VALIDATED`, setting
    the claim's `estimated_payout_cents` equal to its `validated_loss_cents`."
    PRD section 3.6: "Otherwise each claimant's `payout_cents` is the pool
    multiplied by its `validated_loss_cents` and divided by the sum of
    validated losses, rounded down to a whole cent, and the leftover cents are
    distributed one at a time in order of `validated_loss_cents` descending,
    ties broken by `created_at` ascending, never by id."
    PRD section 3.6: "Every `VALIDATED` claimant transitions to `PAID` with
    its assigned `payout_cents`."

    Design: Difficulty/dual_variant_calc/estimated_vs_final_payout_divergence
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    claimants = register_and_validate_claimants(stl_id, [
        {"state_code": "CA", "contact_ref": "ref-k1",
         "claimed_loss_cents": 6000000, "validated_loss_cents": 6000000},
        {"state_code": "TX", "contact_ref": "ref-k2",
         "claimed_loss_cents": 5000000, "validated_loss_cents": 4000000},
        {"state_code": "NY", "contact_ref": "ref-k3",
         "claimed_loss_cents": 2000000, "validated_loss_cents": 2000000},
    ])
    k1, k2, k3 = claimants
    # Estimated variant: no proration assumed at validation time.
    assert k2["estimated_payout_cents"] == 4000000
    set_clock(PAST_CLAIM_WINDOW)  # strictly past executed_at + 90 days
    settlement = compute_restitution(stl_id)
    assert settlement["restitution_computed"] is True
    assert settlement["restitution_remainder_cents"] == 0
    paid = _claimants_by_id(stl_id)
    # Pool 10,000,000 oversubscribed by 12,000,000 of validated losses:
    # floors 5,000,000 / 3,333,333 / 1,666,666, remainder 1 cent to the
    # largest validated loss (k1).
    assert paid[k1["id"]]["payout_cents"] == 5000001
    assert paid[k2["id"]]["payout_cents"] == 3333333
    assert paid[k3["id"]]["payout_cents"] == 1666666
    assert paid[k2["id"]]["payout_cents"] < k2["estimated_payout_cents"], (
        "the final variant pays strictly below the estimate when the pool "
        "is oversubscribed"
    )
    for c in (k1, k2, k3):
        assert paid[c["id"]]["status"] == "PAID"


def test_zero_validated_claims_leaves_full_reserve():
    """PRD section 3.6: "Every claimant still `REGISTERED` after the window is
    lapsed to `LAPSED`; `DENIED` claimants are excluded; only `VALIDATED`
    claimants share the pool."
    PRD section 3.6: "When the dust settles, the remaining unclaimed balance
    is stored as the settlement's `restitution_remainder_cents`, the
    `restitution_reserve_balance_cents` equals that remainder, and
    `restitution_computed` is set true."

    Design: Difficulty/boundary_precision_check/zero_validated_claims_leaves_full_reserve
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    k1 = register_claimant(
        stl_id, state_code="CA", contact_ref="ref-k1", claimed_loss_cents=6000000,
    )
    adjudicate_claimant(k1["id"], "DENIED")
    set_clock(PAST_CLAIM_WINDOW)
    settlement = compute_restitution(stl_id)
    assert settlement["restitution_computed"] is True, (
        "the empty validated set computes without division by zero"
    )
    assert settlement["restitution_remainder_cents"] == 10000000
    assert settlement["restitution_reserve_balance_cents"] == 10000000
    final = _claimants_by_id(stl_id)
    assert final[k1["id"]]["status"] == "DENIED", (
        "the sweep leaves DENIED claimants untouched"
    )
    assert all(c["status"] != "PAID" for c in final.values())


def test_validation_exceeds_claim_rejected():
    """PRD section 3.6: "A `VALIDATED` decision carries
    `validated_loss_cents`, which must be greater than zero and no more than
    the claim's `claimed_loss_cents` — a validation exceeding the claim is
    rejected with `ERR_VALIDATION_EXCEEDS_CLAIM` (HTTP 422)."

    Design: Corner/errors/validation_exceeds_claim_rejected
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    k1 = register_claimant(
        stl_id, state_code="CA", contact_ref="ref-k1", claimed_loss_cents=100,
    )
    resp = api_client.validate_claimant(
        k1["id"],
        validate_claimant_payload("VALIDATED", validated_loss_cents=101),
        FUND_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_EXCEEDS_CLAIM)
    assert _claimants_by_id(stl_id)[k1["id"]]["status"] == "REGISTERED"


def test_validate_twice_returns_invalid_state():
    """PRD section 3.6: "A `DENIED` decision moves `REGISTERED` → `DENIED`
    outright." and "Either decision is lawful only from `REGISTERED` (else
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/validate_twice_returns_invalid_state
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    k1 = register_claimant(
        stl_id, state_code="CA", contact_ref="ref-k1", claimed_loss_cents=100,
    )
    adjudicate_claimant(k1["id"], "DENIED")
    resp = api_client.validate_claimant(
        k1["id"],
        validate_claimant_payload("VALIDATED", validated_loss_cents=100),
        FUND_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert _claimants_by_id(stl_id)[k1["id"]]["status"] == "DENIED"


def test_claim_window_boundaries_enforced():
    """PRD section 3.6: "The compute is lawful only strictly after the claim
    window — running it at or before `executed_at` plus 90 days is rejected
    with `ERR_CLAIM_WINDOW_CLOSED`."
    PRD section 3.6: "Claimants may be registered only against an `EXECUTED`
    settlement (else `ERR_INVALID_STATE`) and only within the claim window:
    the current logical time must be at or before `executed_at` plus 90 days,
    after which registration is rejected with `ERR_CLAIM_WINDOW_CLOSED`
    (HTTP 422)."

    Design: Corner/errors/claim_window_boundaries_enforced
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    # At the default clock (executed_at + 0 days) the window is still open,
    # so the compute is too early.
    resp_early = api_client.restitution_compute(stl_id, FUND_ADMIN)
    validate_error(resp_early, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED)
    settlement = get_settlement(stl_id)
    assert settlement["restitution_computed"] is False
    set_clock(PAST_CLAIM_WINDOW)  # executed_at + 91 days
    resp_late = api_client.create_claimant(
        stl_id,
        create_claimant_payload(
            state_code="CA", contact_ref="late-claim", claimed_loss_cents=1000,
        ),
        FUND_ADMIN,
    )
    validate_error(resp_late, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED)


def test_restitution_recompute_locked():
    """PRD section 3.6: "The compute is lawful only strictly after the claim
    window ... and only once: a settlement whose `restitution_computed` is
    already true rejects a second compute with `ERR_RESTITUTION_LOCKED`
    (HTTP 409)."

    Design: Corner/errors/restitution_recompute_locked
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    set_clock(PAST_CLAIM_WINDOW)
    first = compute_restitution(stl_id)
    assert first["restitution_computed"] is True
    assert first["restitution_remainder_cents"] == 10000000
    resp = api_client.restitution_compute(stl_id, FUND_ADMIN)
    validate_error(resp, ApiErrorId.ERR_RESTITUTION_LOCKED)
    settlement = get_settlement(stl_id)
    assert settlement["restitution_remainder_cents"] == 10000000


def test_line_gross_conservation_across_stale_request_revert():
    """PRD section 3.6: "every disbursement on the settlement's lines still
    sitting in `REQUESTED` whose certification deadline — the settlement's
    `executed_at` plus 180 days — lies in the past at compute time is moved
    `REQUESTED` → `REVERTED`" and "Each reversion adds the disbursement's
    amount to its line's `reverted_cents` and the settlement's
    `reverted_cents`, recomputes the line's `remaining_cents`, and adds the
    amount to `restitution_reserve_balance_cents`."
    PRD section 3.4: "every line maintains the invariant that
    `disbursed_cents`, `reverted_cents`, and `remaining_cents` always sum to
    `gross_share_cents`."

    Design: Difficulty/compensating_invariant/line_gross_conservation_across_stale_request_revert
    """
    world = setup_executed_world()
    stl_id = world["settlement"]["id"]
    fund_world(world)
    ny_line = {l["state_code"]: l for l in world["lines"]}["NY"]
    assert ny_line["gross_share_cents"] == 42750000
    disb = request_disbursement(
        ny_line, world["offices"]["NY"], False,
        amount_cents=1000000, use_code="PROGRAM",
    )
    assert disb["status"] == "REQUESTED"
    set_clock(PAST_APPROPRIATION_WINDOW)  # certification deadline now past
    settlement = compute_restitution(stl_id)
    assert settlement["reverted_cents"] == 1000000
    # No claimants: reserve 10,000,000 + swept 1,000,000 stays unclaimed.
    assert settlement["restitution_remainder_cents"] == 11000000
    line = get_allocation_line(ny_line["id"])
    assert line["disbursed_cents"] == 0
    assert line["reverted_cents"] == 1000000
    assert line["remaining_cents"] == 41750000
    assert_line_gross_invariant(line)
    disbs, _ = validate_paginated(
        api_client.list_allocation_line_disbursements(ny_line["id"], CHAIR)
    )
    assert disbs[0]["id"] == disb["id"]
    assert disbs[0]["status"] == "REVERTED"
