"""Whole-operation contracts: the clock a fresh server reads, the figures an
evaluation reports, and what a batch run is allowed to move."""
from test_helpers import api_client, validate_success
from test_helpers.factories import create_site_payload
from test_helpers.fixtures import (
    ANALYST,
    OPERATOR,
    create_settlement_line,
    create_site,
    get_ppa,
    get_site,
    set_clock,
    setup_active_ppa,
    setup_approved_line,
)


def test_a_resource_created_before_any_clock_call_carries_the_startup_instant():
    """PRD §2.10: "A `SiteOperator` may set the clock to any supplied
    `current_utc` instant, and the server starts, before any such call, at exactly
    `2026-09-01T00:00:00Z`; it never falls back to the host machine's wall-clock time, and every
    comparison the system makes against "now" — cure deadlines, confirmation gates, reversal
    windows, escalation ladders, stale-accrual ages, deferred revert timers — is made against the
    logical clock."
    PRD §2.4: "`created_at` is the instant the row was first persisted,
    rendered as an ISO 8601 timestamp in UTC with exactly three fractional digits."

    Design: Corner/endpoints/logical_clock_defaults_to_the_startup_instant_before_any_set
    """
    # No clock call is made anywhere in this test: the server has just been
    # restarted by the harness, so it still reads its own startup instant.
    response = api_client.create_site(create_site_payload(), OPERATOR)
    site = validate_success(response, expected_status=201)

    assert site["created_at"] == "2026-09-01T00:00:00.000Z", (
        "the first row written by a freshly started server is stamped with the startup "
        f"instant, not the wall-clock instant of the request; got {site['created_at']}"
    )
    assert site["updated_at"] == site["created_at"], (
        "nothing has modified the row since it was written"
    )
    assert site["version"] == 1


def test_evaluating_a_site_reports_its_standby_and_exit_fee_exposure():
    """PRD §3.1: "The first is the `standby_charge_cents` the utility will levy on the
    interconnection, which is the total contracted capacity at the site multiplied by
    `standby_charge_cents_per_kw_month` and again by twelve, since standby is billed monthly and
    the evaluation states it annually. The second is the `exit_fee_cents` exposure if the
    interconnection is abandoned, which is the same total contracted capacity multiplied by the
    site's `interconnect_exit_fee_cents_per_kw`."
    PRD §3.1: "A site with no contracts reports both figures as zero. The evaluation records what
    it read, advancing the facility's `version` by one even though no new row is created."

    Design: Corner/endpoints/site_evaluation_computes_standby_charge_and_exit_fee_exposure
    """
    ctx = setup_active_ppa()
    bare = create_site(name="Russian River Vintners")
    version_before = get_site(ctx["site_id"])["version"]

    evaluated = validate_success(api_client.evaluate_site(ctx["site_id"], OPERATOR))

    # 500 contracted kW at 1.80 cents per kW-month billed over twelve months,
    # and the same capacity at the 95.00-cent interconnect exit fee per kW.
    assert evaluated["standby_charge_cents"] == 10800, (
        "standby is the contracted capacity times the monthly rate times twelve; got "
        f"{evaluated['standby_charge_cents']}"
    )
    assert evaluated["exit_fee_cents"] == 47500, (
        "the exit exposure is the same capacity times the per-kW exit fee; got "
        f"{evaluated['exit_fee_cents']}"
    )
    assert get_site(ctx["site_id"])["version"] == version_before + 1, (
        "the evaluation records what it read even though it creates no resource"
    )

    empty = validate_success(api_client.evaluate_site(bare["id"], OPERATOR))
    assert empty["standby_charge_cents"] == 0
    assert empty["exit_fee_cents"] == 0


def test_the_rollover_batch_advances_only_the_approved_lines():
    """PRD §3.4: "A `SiteOperator` may also drive the period forward in bulk. The rollover process selects the
    contract's lines that are in `SETTLEMENT_APPROVED` and whose `period_anchor_iso8601` is at or
    before the current logical clock, then walks them in a pinned order — by
    `period_anchor_iso8601` ascending, then by `created_at` ascending, then by allocation weight
    descending — and settles each one against a running pool that opens at `POOL_OPENING_CENTS`,
    which is 500,000 cents."
    PRD §3.4: "For each row in that order the pool is reduced by the row's settled amount; if the pool would
    go negative, the row's settled amount is clamped downward by exactly the shortfall and the pool is
    set to zero, so the shortfall carries forward rather than landing as a negative balance. Each row
    is then moved to `SETTLEMENT_APPLIED`."

    Design: Corner/endpoints/rollover_batch_advances_only_approved_lines_and_reports_a_count
    """
    ctx = setup_approved_line()
    draft = create_settlement_line(
        ctx["ppa_id"],
        period_start="2026-04-11T00:00:00Z",
        period_end="2026-05-11T00:00:00Z",
    )
    assert draft["status"] == "SETTLEMENT_DRAFT"

    # Move the clock past the whole settlement period so that the eligible row
    # is at or before it on either reading of the period anchor.
    set_clock("2026-05-11T00:00:00Z")

    response = api_client.rollover_period(OPERATOR, {"site_id": ctx["site_id"]})
    validate_success(response)

    advanced = validate_success(
        api_client.get_settlement_line(ctx["ppa_id"], ctx["line_id"], ANALYST)
    )
    assert advanced["status"] == "SETTLEMENT_APPLIED", (
        f"an approved line is settled by the batch; got {advanced['status']}"
    )

    untouched = validate_success(
        api_client.get_settlement_line(ctx["ppa_id"], draft["id"], ANALYST)
    )
    assert untouched["status"] == "SETTLEMENT_DRAFT", (
        "a line that was never approved is not eligible for the batch; got "
        f"{untouched['status']}"
    )
    assert get_site(ctx["site_id"])["lifetime_customer_billable_cents"] != 0, (
        "the settled line moves the site's billable aggregate"
    )
    assert get_ppa(ctx["ppa_id"])["state"] == "PPA_ACTIVE"
