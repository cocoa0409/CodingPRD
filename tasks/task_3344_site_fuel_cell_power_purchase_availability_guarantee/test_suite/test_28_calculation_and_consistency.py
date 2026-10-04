"""Which accruals a settlement line reads, and what a refused or a reversed
step leaves behind on the ledger."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    ANALYST,
    approve_settlement_line,
    create_settlement_line,
    get_ppa,
    get_site,
    issue_allowance,
    post_accrual,
    reverse_settlement_line,
    setup_active_ppa,
    setup_applied_line,
    validate_settlement_line,
)

# The stop-loss is measured against the opening commitment less the floor, so
# these are the two figures the headroom is built from.
RESERVE_PRE_CENTS = 400000
LOSS_FLOOR_CENTS = 25000


def test_a_draft_line_tracks_the_open_accruals_and_a_decided_line_freezes_its_pool():
    """PRD §3.5: "Which accruals a line sees depends on where the line sits. A line in `SETTLEMENT_DRAFT` or
    `SETTLEMENT_VALIDATED` reads accruals that are still `ACCRUAL_OPEN` at the moment it is read,
    which means a later confirmation of a delivery changes a draft figure. A line in
    `SETTLEMENT_APPROVED` or `SETTLEMENT_APPLIED` freezes its pool at the value observed when the
    line left `SETTLEMENT_VALIDATED`, so subsequent accrual reconciliation does not move it and the
    same inputs produce a different total than the draft basis would."
    PRD §3.5: "The `loss_component_cents` is the `cap_side_pool_cents` multiplied by `LOSS_ALLOCATION_PCT`, which
    is 0.04, rounded to two decimal places."

    Design: Corner/calculations/revenue_variance_uses_the_forward_looking_index_basis
    """
    ctx = setup_active_ppa()
    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=100000)

    draft = create_settlement_line(ctx["ppa_id"])
    assert draft["cap_side_pool_cents"] == 100000, (
        "a draft reads the one open charge accrual; got "
        f"{draft['cap_side_pool_cents']}"
    )
    assert draft["loss_component_cents"] == 4000, (
        "the loss headroom is four percent of the pool; got "
        f"{draft['loss_component_cents']}"
    )

    # A later accrual post changes the draft figure, because the line is still
    # reading whatever is open at the moment it is read.
    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=50000)
    still_draft = validate_success(
        api_client.get_settlement_line(ctx["ppa_id"], draft["id"], ANALYST)
    )
    assert still_draft["cap_side_pool_cents"] == 150000, (
        "the draft basis tracks the open accruals; got "
        f"{still_draft['cap_side_pool_cents']}"
    )

    validate_settlement_line(ctx["ppa_id"], draft["id"])
    issue_allowance(ctx["ppa_id"], amount_cents=185000)
    approved = approve_settlement_line(ctx["ppa_id"], draft["id"])
    assert approved["status"] == "SETTLEMENT_APPROVED"
    assert approved["cap_side_pool_cents"] == 150000, (
        "the pool freezes at the value observed when the line left validation; got "
        f"{approved['cap_side_pool_cents']}"
    )

    post_accrual(ctx["ppa_id"], ctx["site_id"], amount_cents=25000)
    frozen = validate_success(
        api_client.get_settlement_line(ctx["ppa_id"], draft["id"], ANALYST)
    )
    assert frozen["cap_side_pool_cents"] == 150000, (
        "a decided line no longer moves with the accrual ledger, so the same evidence "
        f"now yields a different total than the draft basis; got {frozen['cap_side_pool_cents']}"
    )


def test_an_allowance_apply_past_the_headroom_leaves_no_partial_credit():
    """PRD §2.9: "The headroom
    is the opening commitment minus the floor. The evaluation is ordered: headroom is computed
    first, the entire accumulated credit figure is compared against it, and only if the comparison
    passes is the reserve written. Any write that would push accumulated credits past the headroom
    is refused outright with `ERR_GUARANTEE_FLOOR_BREACH` (HTTP 422) and nothing is persisted".

    Design: Corner/consistency_model/rejected_allowance_apply_leaves_no_partial_credit
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
    # PRD §3.6 reads the applied cap against "the target line's
    # `net_charge_cents`", so the period the allowances land in must exist.
    create_settlement_line(ctx["ppa_id"])
    for amount_cents in (50000, 75000, 125000):
        allowance = issue_allowance(ctx["ppa_id"], amount_cents=amount_cents)
        validate_success(api_client.apply_allowance(ctx["ppa_id"], allowance["id"], ANALYST))

    before = get_ppa(ctx["ppa_id"])
    holds_before = get_site(ctx["site_id"])["reserved_capacity_hold_count"]

    overdrawn = issue_allowance(ctx["ppa_id"], amount_cents=2000000)
    refused = api_client.apply_allowance(ctx["ppa_id"], overdrawn["id"], ANALYST)

    validate_error(refused, ApiErrorId.ERR_GUARANTEE_FLOOR_BREACH)
    assert refused.status_code == 422

    still_issued = validate_success(
        api_client.get_allowance(ctx["ppa_id"], overdrawn["id"], ANALYST)
    )
    assert still_issued["lifecycle_state"] == "ALLOWANCE_ISSUED", (
        "the refused allowance never entered the applied state; got "
        f"{still_issued['lifecycle_state']}"
    )
    assert still_issued["applied_direction"] is None, (
        "an issued allowance carries no applied direction, because the write was refused "
        "before any of the sequence was recorded"
    )

    after = get_ppa(ctx["ppa_id"])
    assert (
        after["capacity_reserve_credits_cents"] == before["capacity_reserve_credits_cents"]
    ), (
        "a refused apply leaves the accumulated credit figure exactly where it was; read "
        f"{after['capacity_reserve_credits_cents']} against {before['capacity_reserve_credits_cents']}"
    )
    assert after["capacity_guarantee_reserve_cents"] == (
        after["capacity_reserve_pre_cents"] - after["capacity_reserve_credits_cents"]
    )
    assert after["capacity_guarantee_reserve_cents"] >= after["loss_floor_cents"]
    assert (
        get_site(ctx["site_id"])["reserved_capacity_hold_count"] == holds_before
    ), "the site's hold counter is only advanced by an apply that actually lands"


def test_a_reversal_reopens_the_accruals_the_settle_had_reconciled():
    """PRD §3.4: "Every accrual that this line reconciled — the ones now sitting in
    `ACCRUAL_RECONCILED` whose creation instant is at or before this line's creation instant —
    returns to `ACCRUAL_OPEN`, restoring the pool to exactly its pre-application value. The
    contract's `lifetime_settled_cents` is reduced by the line's `net_charge_cents` and its
    `committed_kwh_remaining` is increased by the line's `metered_kwh`, because the period is
    being un-delivered."
    PRD §3.4: "The consumed allowance is handed back to `ALLOWANCE_ISSUED` when its `applied_direction` was
    `ALLOWANCE_APPLIED_AS_TIME`."

    Design: Corner/consistency_model/reverse_restores_the_pool_the_settle_had_drained
    """
    ctx = setup_applied_line()
    assert ctx["line"]["status"] == "SETTLEMENT_APPLIED"
    assert (
        validate_success(api_client.get_accrual(ctx["accrual"]["id"], ANALYST))[
            "lifecycle_state"
        ]
        == "ACCRUAL_RECONCILED"
    ), "the settle drained the accrual out of the open pool"

    reversed_line = reverse_settlement_line(ctx["ppa_id"], ctx["line_id"])

    assert reversed_line["status"] == "SETTLEMENT_REVERSED", (
        f"the reversal moves the line to its terminal state; got {reversed_line['status']}"
    )
    assert (
        validate_success(api_client.get_accrual(ctx["accrual"]["id"], ANALYST))[
            "lifecycle_state"
        ]
        == "ACCRUAL_OPEN"
    ), "the reversal restores the pool the settle had drained"
    assert (
        validate_success(
            api_client.get_allowance(ctx["ppa_id"], ctx["allowance"]["id"], ANALYST)
        )["lifecycle_state"]
        == "ALLOWANCE_ISSUED"
    ), "the consumed allowance is handed back"

    # The restored pool is what a fresh line for the same period now reads; the
    # reversed line is excluded from the overlap rule.
    restored = create_settlement_line(ctx["ppa_id"])
    assert restored["cap_side_pool_cents"] == 100000, (
        "a line created after the reversal reads exactly the pre-application pool; got "
        f"{restored['cap_side_pool_cents']}"
    )
    assert get_site(ctx["site_id"])["lifetime_customer_billable_cents"] == 0, (
        "with the only applied line reversed, the site's billable aggregate lands on zero"
    )
    assert get_ppa(ctx["ppa_id"])["state"] == "PPA_ACTIVE"
