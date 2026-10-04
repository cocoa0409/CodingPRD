"""The capacity-guarantee stop-loss: the opening commitment less the credits
accumulated against it, held at or above the contract's floor."""
from test_helpers import api_client, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    ANALYST,
    create_settlement_line,
    get_ppa,
    issue_allowance,
    post_accrual,
    setup_active_ppa,
)

# The contract opens with a 400,000-cent commitment and a 25,000-cent floor, so the
# headroom the accumulated credits are compared against is 375,000 cents.
RESERVE_PRE_CENTS = 400000
LOSS_FLOOR_CENTS = 25000


def test_capacity_reserve_is_the_opening_commitment_less_accumulated_credits():
    """PRD §2.9: "Credits that draw against the reserve accumulate in `capacity_reserve_credits_cents`,
    which is the sum of every applied allowance amount charged to this contract plus every
    true-up accrual amount recorded against it".
    PRD §2.9: "`capacity_guarantee_reserve_cents`, which is the opening commitment minus the accumulated
    credits, can never fall below the contract's floor."

    Design: Difficulty/combinatorial_formula/capacity_guarantee_reserve_load_bearing_inner_min
    """
    ctx = setup_active_ppa(
        ppa_overrides={
            "capacity_reserve_pre_cents": RESERVE_PRE_CENTS,
            "loss_floor_cents": LOSS_FLOOR_CENTS,
        }
    )
    # The issuance gate requires an open accrual against the contract; a capacity
    # accrual is not a credit against the reserve, only a true-up accrual is.
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CAPACITY_ACCRUAL", amount_cents=400000
    )
    # PRD §3.6 reads the applied cap against "the target line's
    # `net_charge_cents`", so the period the allowances land in must exist.
    create_settlement_line(ctx["ppa_id"])

    for amount_cents in (50000, 75000, 125000):
        allowance = issue_allowance(ctx["ppa_id"], amount_cents=amount_cents)
        api_client.apply_allowance(ctx["ppa_id"], allowance["id"], ANALYST)

    ppa = get_ppa(ctx["ppa_id"])
    assert ppa["capacity_reserve_credits_cents"] > 0, (
        "three applied allowances must leave a positive accumulated credit figure"
    )
    assert ppa["capacity_guarantee_reserve_cents"] == (
        ppa["capacity_reserve_pre_cents"] - ppa["capacity_reserve_credits_cents"]
    ), (
        "the reserve is the opening commitment less the accumulated credits; read "
        f"{ppa['capacity_guarantee_reserve_cents']} against a commitment of "
        f"{ppa['capacity_reserve_pre_cents']} and credits of "
        f"{ppa['capacity_reserve_credits_cents']}"
    )
    assert ppa["capacity_guarantee_reserve_cents"] >= ppa["loss_floor_cents"], (
        "the inner floor binds first, so the reserve can never read below the contract's "
        f"floor; got {ppa['capacity_guarantee_reserve_cents']} against a floor of "
        f"{ppa['loss_floor_cents']}"
    )


def test_an_allowance_past_the_headroom_is_refused_and_persists_nothing():
    """PRD §2.9: "Any write that would push accumulated credits past the headroom
    is refused outright with `ERR_GUARANTEE_FLOOR_BREACH` (HTTP 422) and nothing is persisted".
    PRD §2.9: "The headroom
    is the opening commitment minus the floor."

    Design: Difficulty/combinatorial_formula/capacity_guarantee_reserve_load_bearing_inner_min
    """
    ctx = setup_active_ppa(
        ppa_overrides={
            "capacity_reserve_pre_cents": RESERVE_PRE_CENTS,
            "loss_floor_cents": LOSS_FLOOR_CENTS,
        }
    )
    post_accrual(
        ctx["ppa_id"], ctx["site_id"], accrual_type="CAPACITY_ACCRUAL", amount_cents=400000
    )
    create_settlement_line(ctx["ppa_id"])
    for amount_cents in (50000, 75000, 125000):
        allowance = issue_allowance(ctx["ppa_id"], amount_cents=amount_cents)
        api_client.apply_allowance(ctx["ppa_id"], allowance["id"], ANALYST)

    before = get_ppa(ctx["ppa_id"])
    # Headroom is 375,000 cents; any further credit of this size passes it.
    overdrawn = issue_allowance(ctx["ppa_id"], amount_cents=1000000)
    response = api_client.apply_allowance(ctx["ppa_id"], overdrawn["id"], ANALYST)

    validate_error(response, ApiErrorId.ERR_GUARANTEE_FLOOR_BREACH)
    after = get_ppa(ctx["ppa_id"])
    assert after["capacity_reserve_credits_cents"] == before["capacity_reserve_credits_cents"], (
        "nothing is persisted from a refused write, so the accumulated credits cannot move"
    )
    assert after["capacity_guarantee_reserve_cents"] == (
        before["capacity_guarantee_reserve_cents"]
    ), "the persisted reserve must not be written by a refused apply"
    assert after["capacity_guarantee_reserve_cents"] >= after["loss_floor_cents"]