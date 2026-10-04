"""Hydropower revenue periods and repayment-credit settlement.

Covers the projected-vs-settled input-set divergence, the pinned
per-release-then-sum rounding order, the per-contract credit rounding with
the largest-outstanding remainder rule and the standing repayment
invariant, the period-month windowing, the terminal settle rejection, and
the (reservoir, month) uniqueness rule - PRD §2.10 and §3.7.
"""

from test_helpers import (
    ApiErrorId,
    FINANCE_OFFICER_HEADERS,
    assert_cents,
    assert_repayment_invariant,
    assert_two_dp,
    factories,
    fixtures,
    validate_error,
)

FINANCE = FINANCE_OFFICER_HEADERS


def test_revenue_projected_vs_settled_divergence(api):
    """Same month, same two releases: the projected figures include the
    still-SCHEDULED release (11,901.0 MWh) while the settled ones exclude it
    (9,917.5 MWh) - input-set filtering alone drives the delta.

    PRD §3.7: "take every release order of the reservoir whose
    `scheduled_start` falls within the period month — the window is inclusive
    of the first instant of the month and exclusive of the first instant of
    the next — and whose status is `SCHEDULED` or `EXECUTED`; sum their
    already-integer `volume_af` values; `projected_mwh` is that total volume
    multiplied by `power_conversion_mwh_per_af`, rounded half up to two
    decimal places; `projected_revenue_cents` is `projected_mwh` multiplied
    by `rate_cents_per_mwh`, rounded half up to whole cents."
    PRD §3.7: "Settlement reruns the same computation restricted to releases
    whose status is `EXECUTED` at settle time, yielding `settled_mwh` and
    `settled_revenue_cents` — so with identical underlying data the settled
    figures differ from the projected ones whenever any release in the month
    is still `SCHEDULED` at settle time, the input-set filter being the only
    difference."

    Design: Difficulty/dual_variant_calc/revenue_projected_vs_settled_divergence
    """
    outcome = fixtures.setup_revenue_scenario(api)
    world, releases, period = outcome["world"], outcome["releases"], outcome["period"]
    # R1 1,000 cfs x 10 d EXECUTED (19,835 af); R2 500 cfs x 4 d still
    # SCHEDULED (3,967 af); conversion 0.5 MWh/af; rate 4,500 cents/MWh.
    assert_two_dp(period["projected_mwh"], 11_901.0, "projected_mwh")  # (19,835+3,967)*0.5
    assert_cents(period["projected_revenue_cents"], 53_554_500, "projected_revenue_cents")
    assert period["status"] == "PROJECTED"

    settled = fixtures.settle_period(api, period["id"])

    assert_two_dp(settled["settled_mwh"], 9_917.5, "settled_mwh")  # 19,835*0.5, EXECUTED only
    assert_cents(settled["settled_revenue_cents"], 44_628_750, "settled_revenue_cents")
    assert settled["status"] == "SETTLED"
    assert settled["projected_revenue_cents"] != settled["settled_revenue_cents"], (
        "the still-SCHEDULED release is the only difference between the variants"
    )

    r2 = fixtures.find_release(api, world["reservoir"]["id"], releases[1]["id"])
    assert r2["status"] == "SCHEDULED", "R2 was never executed"


def test_per_release_rounding_order(api):
    """Per-release rounding happens before summation: two 333 cfs x 1 day
    releases each round to 661 af, so the period settles 661.0 MWh - the
    forbidden sum-then-round order would give 660.5.

    PRD §3.5: "its `volume_af` is derived once, at creation, as `release_cfs`
    multiplied by `duration_days` multiplied by 1.9835, rounded half up to
    whole acre-feet; this per-release rounding is never re-derived from other
    releases."
    PRD §3.7: "sum their already-integer `volume_af` values"

    Design: Difficulty/combinatorial_formula/per_release_rounding_order
    """
    outcome = fixtures.setup_revenue_scenario(
        api,
        releases=[
            (333, 1, "2027-02-01T00:00:00Z"),
            (333, 1, "2027-02-03T00:00:00Z"),
        ],
        executions=[(0, "2027-02-01T12:00:00Z"), (1, "2027-02-03T10:00:00Z")],
        rate_cents_per_mwh=100,
        settle=True,
    )
    world, releases, period = outcome["world"], outcome["releases"], outcome["period"]

    for release in releases:
        stored = fixtures.find_release(api, world["reservoir"]["id"], release["id"])
        assert stored["volume_af"] == 661, "round_half_up(333 * 1 * 1.9835) = round_half_up(660.5055)"

    # Per-release-then-sum: (661 + 661) * 0.5 = 661.0 MWh; sum-then-round on
    # raw cfs-days would yield 660.5 and is forbidden.
    assert_two_dp(period["settled_mwh"], 661.0, "settled_mwh")
    assert float(period["settled_mwh"]) != 660.5
    assert_cents(period["settled_revenue_cents"], 66_100, "settled_revenue_cents")  # 661.0 * 100


def test_settle_conserves_repayment_dollars(api):
    """A 1-cent settle over obligations 7M / 5M / 3M rounds every per-contract
    credit to 0 and assigns the 1-cent remainder to the largest outstanding
    balance; repaid credits plus unrecovered balance equal the total
    obligation before and after, with zero drift.

    PRD §3.7: "The remainder — the settled revenue minus the summed credits —
    is assigned, when nonzero, to the contract with the largest outstanding
    balance (`repayment_obligation_cents` minus `repaid_credits_cents`), ties
    broken by `contract_number` ascending"
    PRD §3.7: "Each contract's `repaid_credits_cents` then increases by its
    credit, and the reservoir's `unrecovered_balance_cents` decreases by
    exactly the sum of the credits, preserving the standing invariant of
    §2.10."
    PRD §2.10: "The invariant that the summed `repaid_credits_cents` over all
    contracts plus the reservoir's `unrecovered_balance_cents` exactly equals
    the total repayment obligation holds at all times."

    Design: Difficulty/compensating_invariant/settle_conserves_repayment_dollars
    """
    outcome = fixtures.setup_revenue_scenario(
        api,
        releases=[(1, 1, "2027-02-01T00:00:00Z")],
        executions=[(0, "2027-02-01T12:00:00Z")],
        rate_cents_per_mwh=1,
        contract_plan="settlement",
    )
    world, period = outcome["world"], outcome["period"]

    reservoir = fixtures.get_reservoir(api, world["reservoir"]["id"])
    assert reservoir["total_repayment_obligation_cents"] == 15_000_000
    assert reservoir["unrecovered_balance_cents"] == 15_000_000
    for key in ("contract_sr", "contract_jr", "contract_tp"):
        assert world[key]["repaid_credits_cents"] == 0

    settled = fixtures.settle_period(api, period["id"])
    # The 1 cfs x 1 day release rounds to 2 af -> 1.0 MWh at 1 cent/MWh.
    assert_cents(settled["settled_revenue_cents"], 1, "settled_revenue_cents")
    assert_two_dp(settled["settled_mwh"], 1.0, "settled_mwh")

    contracts = {
        key: fixtures.get_contract(api, world[key]["id"])
        for key in ("contract_sr", "contract_jr", "contract_tp")
    }
    # C-A (contract_sr, 7M) holds the largest outstanding balance.
    assert contracts["contract_sr"]["repaid_credits_cents"] == 1
    assert contracts["contract_jr"]["repaid_credits_cents"] == 0
    assert contracts["contract_tp"]["repaid_credits_cents"] == 0

    reservoir = fixtures.get_reservoir(api, world["reservoir"]["id"])
    assert reservoir["unrecovered_balance_cents"] == 14_999_999
    assert_repayment_invariant(reservoir, contracts.values())


def test_revenue_period_excludes_releases_outside_the_month(api):
    """Month windowing is inclusive of the 1st and exclusive of the next 1st:
    an EXECUTED March release contributes nothing to the February period.

    PRD §3.7: "take every release order of the reservoir whose
    `scheduled_start` falls within the period month — the window is inclusive
    of the first instant of the month and exclusive of the first instant of
    the next — and whose status is `SCHEDULED` or `EXECUTED`"

    Design: Corner/calculations/revenue_period_excludes_releases_outside_the_month
    """
    outcome = fixtures.setup_revenue_scenario(
        api,
        releases=[
            (1_000, 10, "2027-02-01T00:00:00Z"),
            (200, 2, "2027-03-01T00:00:00Z"),
        ],
        executions=[(0, "2027-02-03T00:00:00Z"), (1, "2027-03-02T00:00:00Z")],
        period_month="2027-02",
        rate_cents_per_mwh=4_500,
    )
    world, releases, period = outcome["world"], outcome["releases"], outcome["period"]

    # Only the February release's 19,835 af count: 19,835 * 0.5 MWh.
    assert_two_dp(period["projected_mwh"], 9_917.5, "projected_mwh")
    assert_cents(period["projected_revenue_cents"], 44_628_750, "projected_revenue_cents")

    march = fixtures.find_release(api, world["reservoir"]["id"], releases[1]["id"])
    assert march["status"] == "EXECUTED", "exclusion is by month window, not release state"


def test_settle_already_settled_period_returns_invalid_state(api):
    """SETTLED is terminal: a second settle returns 409 ERR_INVALID_STATE and
    no contract is credited twice.

    PRD §3.7: "Settlement is the FinanceOfficer's month-end act, moving the
    period from `PROJECTED` to `SETTLED`; settling a period that is not
    `PROJECTED` fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/settle_already_settled_period_returns_invalid_state
    """
    outcome = fixtures.setup_revenue_scenario(
        api,
        releases=[(1_000, 10, "2027-02-01T00:00:00Z")],
        executions=[(0, "2027-02-03T00:00:00Z")],
        settle=True,
    )
    world, period = outcome["world"], outcome["period"]
    assert period["status"] == "SETTLED"
    credits_after_first = world["contract_sr"]["repaid_credits_cents"]

    validate_error(
        api.settle_revenue_period(period["id"], FINANCE),
        ApiErrorId.ERR_INVALID_STATE,
    )

    contract = fixtures.get_contract(api, world["contract_sr"]["id"])
    assert contract["repaid_credits_cents"] == credits_after_first, (
        "a rejected settle must not double-credit"
    )


def test_duplicate_revenue_period_rejected(api):
    """Uniqueness is per (reservoir, period_month): a second 2027-02 period
    fails 409 ERR_DUPLICATE_REVENUE_PERIOD while 2027-03 is accepted.

    PRD §3.7: "There is at most one period per reservoir and month: a
    duplicate is refused with `ERR_DUPLICATE_REVENUE_PERIOD`."

    Design: Corner/validations/duplicate_revenue_period_rejected
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan="standard")
    reservoir_id = world["reservoir"]["id"]
    fixtures.create_revenue_period(api, reservoir_id)

    validate_error(
        api.create_revenue_period(
            factories.revenue_period_payload(reservoir_id, "2027-02", 4_600), FINANCE
        ),
        ApiErrorId.ERR_DUPLICATE_REVENUE_PERIOD,
    )

    march = fixtures.create_revenue_period(api, reservoir_id, "2027-03", 4_600)
    assert march["period_month"] == "2027-03"
    assert march["status"] == "PROJECTED"
