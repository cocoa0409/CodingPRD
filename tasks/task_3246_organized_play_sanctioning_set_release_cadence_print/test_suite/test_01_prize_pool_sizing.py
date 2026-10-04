"""Prize-pool sizing: tier base, digital-member supplement and pool-mode forks."""
from test_helpers import (
    get_allocation,
    mint_code,
    redeem_code,
    setup_application,
)


def test_bundled_mode_absorbs_the_first_four_digital_members(api):
    """PRD §3.5: "The pool starts from a tier base: a `LOCAL` event's pool begins
    at sixteen points, a `QUALIFIER` event's at forty-eight, and a
    `CHAMPIONSHIP` event's at ninety-six."
    PRD §3.5: "Under `BUNDLED` mode, the first four redeemed digital members are
    absorbed by the tier base and add nothing; only the fifth and each member
    after it adds a per-member bundle value for the tier — three points at
    `LOCAL`, six at `QUALIFIER`, and twelve at `CHAMPIONSHIP`."

    Design: Difficulty/dual_variant_calc/bundled_vs_unbundled_pod_pool_diverges
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER", members=4, pool_mode="BUNDLED", code_prefix="QOPA"
    )

    assert application["prize_allocation_id"] == allocation["id"]
    assert allocation["tier"] == "QUALIFIER"
    assert allocation["base_tp"] == 48, (
        "four bundled digital members are absorbed by the QUALIFIER base of 48"
    )
    assert allocation["remaining_tp"] == 48
    assert allocation["total_drawn_tp"] == 0
    assert allocation["total_restored_tp"] == 0


def test_unbundled_mode_pays_for_every_digital_member_including_the_first_four(api):
    """PRD §3.5: "Under `UNBUNDLED` mode, every redeemed digital member adds four
    points, including the first four, so for any event with at least one redeemed
    digital member the unbundled pool is strictly larger than the bundled pool
    for identical inputs, and an event with no redeemed digital members gets the
    same pool under either mode."
    PRD §3.5: "The pool starts from a tier base: a `LOCAL` event's pool begins at
    sixteen points, a `QUALIFIER` event's at forty-eight, and a `CHAMPIONSHIP`
    event's at ninety-six."

    Design: Difficulty/dual_variant_calc/bundled_vs_unbundled_pod_pool_diverges
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER", members=4, pool_mode="UNBUNDLED", code_prefix="QOPB"
    )

    assert allocation["base_tp"] == 64, (
        "48 base plus four members at four points each is 64"
    )
    assert allocation["remaining_tp"] == 64
    assert allocation["total_drawn_tp"] == 0
    assert allocation["total_restored_tp"] == 0


def test_available_invitation_is_excluded_from_the_member_count(api):
    """PRD §3.5: "The server counts the code redemptions bound to this
    application that are in the `REDEEMED` status and were redeemed as a
    `DIGITAL` entitlement; redemptions still in `AVAILABLE`, redemptions that
    were `DECLINED`, and every redemption of kind `PHYSICAL` are excluded from
    the count entirely."

    Design: Difficulty/combinatorial_formula/championship_pool_tier_and_member_threshold_interaction
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="CHAMPIONSHIP", members=4, invitation=True,
        pool_mode="BUNDLED", code_prefix="CHM4"
    )

    assert allocation["base_tp"] == 96, (
        "the AVAILABLE invitation does not enter the count, so the pool sizes on "
        "exactly four absorbed members"
    )
    assert allocation["remaining_tp"] == allocation["base_tp"]


def test_championship_pool_moves_twelve_points_at_the_fifth_member(api):
    """PRD §3.5: "Under `BUNDLED` mode, the first four redeemed digital members
    are absorbed by the tier base and add nothing; only the fifth and each member
    after it adds a per-member bundle value for the tier — three points at
    `LOCAL`, six at `QUALIFIER`, and twelve at `CHAMPIONSHIP`."
    PRD §3.5: "The pool starts from a tier base: a `LOCAL` event's pool begins at
    sixteen points, a `QUALIFIER` event's at forty-eight, and a `CHAMPIONSHIP`
    event's at ninety-six."

    Design: Difficulty/combinatorial_formula/championship_pool_tier_and_member_threshold_interaction
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="CHAMPIONSHIP", members=5, invitation=True,
        pool_mode="BUNDLED", code_prefix="CHM5"
    )

    assert allocation["base_tp"] == 108, (
        "96 base plus exactly one member beyond the fourth at twelve points is 108"
    )
    assert allocation["base_tp"] - 96 == 12
    assert allocation["remaining_tp"] == allocation["base_tp"]


def test_redeeming_a_code_after_approval_does_not_enlarge_the_pool(api):
    """PRD §3.5: "The count is taken fresh at each approval and is never revisited
    afterwards, so a player redeeming a code after the event has been sanctioned
    does not enlarge an allocation that already exists."

    Design: Difficulty/dual_variant_calc/bundled_vs_unbundled_pod_pool_diverges
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER", members=1, pool_mode="BUNDLED", code_prefix="LATE"
    )
    assert allocation["base_tp"] == 48

    # Mint and redeem a further digital card against the already-approved event.
    mint_code(application["id"], redemption_code="LATE-EXTRA", code_kind="DIGITAL")
    redeem_code(application["id"], "LATE-EXTRA", store["id"])

    reread = get_allocation(allocation["id"])
    assert reread["base_tp"] == 48, (
        "a redemption after approval must not enlarge the existing pool"
    )
    assert reread["remaining_tp"] == 48

def test_the_store_balance_tracks_the_pool_remaining_and_moves_on_a_void(api):
    """PRD §2.7: "The store's `tp_balance` is the sum of `remaining_tp` across
    every prize allocation the store owns, so it falls as prizes are drawn and
    rises again as points are restored."
    PRD §3.5: "Points come back by voiding a passed distribution, by filing a
    report that declares unclaimed prizes, and by disbursing a physical prize
    grant."

    Design: Corner/entities/store_derived_tp_balance_matches_open_allocation_remaining
    """
    from test_helpers import (
        current_store,
        pass_distribution,
        propose_distribution,
        void_distribution,
    )

    store, _set_release, _fmt, application, allocation = setup_application(
        tier="CHAMPIONSHIP", members=6, invitation=True, code_prefix="CHM"
    )
    assert allocation["base_tp"] == 120

    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=25, recipient_ref="PLAYER-25"
    )
    pass_distribution(distribution["id"])

    pool = get_allocation(allocation["id"])
    assert pool["remaining_tp"] == 95
    listed = current_store(store["id"])
    assert listed["tp_balance"] == 95, (
        "the store's rolled-up balance matches the allocation's remaining points"
    )
    assert listed["reporting_violation_points"] == 0

    void_distribution(distribution["id"])
    assert current_store(store["id"])["tp_balance"] == 120
