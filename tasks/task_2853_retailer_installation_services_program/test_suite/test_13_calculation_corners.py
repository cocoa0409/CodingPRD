"""Where two pricing rules bind at once, and where the two scorecard variants
disagree over the same ledger.

The labour charge is built in six fixed steps, the tier ladder is marginal rather
than average, the change-order price is rounded line by line, and the deposit
waterfall fills its buckets in a fixed order. These tests pin the arithmetic at
the points where a plausible shortcut gives a different answer.
"""

import pytest

from test_helpers import (
    BASE_SCORE,
    MIN_LABOR_CHARGE_CENTS,
    PROJECT_COORDINATOR,
    ChangeOrderDecision,
    ChangeOrderOrigin,
    ChangeOrderStatus,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    PermitStatus,
    TradeCode,
    assert_deposit_buckets,
    assert_money,
    assert_project_dimensions,
    assert_score,
    assert_scorecard_dimensions,
    assert_units,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_customer_headers,
    make_installer_headers,
)

# A 20.00-unit job on SMALL-FIX: the units floor lifts the billable quantity to
# 100.00 units at 50 cents each, which is 5000 cents, and the programme minimum
# then lifts the answer to 15000.
SMALL_FIX_DEPOSIT = 4500

# FLOOR-DIRECT at 425 cents: band B is round_half_up(425 * 0.92) = 391 and band C
# is round_half_up(425 * 0.85) = 361.
BAND_B_RATE = 391
BAND_C_RATE = 361


def _small_fix_baseline(api):
    """The low-rate catalogue entry in a jurisdiction whose multiplier is exactly
    1.00, so step five is a no-op and the two floors are observable alone."""
    return fx.program_baseline(api, f.small_fix_category_payload(),
                               f.plain_jurisdiction_payload())


def test_the_units_floor_and_the_programme_minimum_bind_in_sequence(api):
    """Twenty units are billed as one hundred, and the 5000-cent result is then
    raised to the programme minimum, with the deposit taken on the raised figure.

    PRD 3.3: "Sixth and last, the answer is the greater of that figure and the
    programme minimum labour charge of 15000 cents — one hundred and fifty
    dollars."

    Design: Corner/calculations/program_minimum_and_billable_units_floor_both_bind_the_quote
    """
    base = _small_fix_baseline(api)
    project = fx.sell_project(api, base, estimated_units=20.00,
                              site_address="3 Alder Court")

    assert_money(project["quoted_labor_cents"], MIN_LABOR_CHARGE_CENTS,
                 "quoted_labor_cents")
    # round_half_up(15000 * 0.30): the deposit is a fraction of the floored quote,
    # not of the 5000 cents the ladder produced.
    assert_money(project["deposit_required_cents"], SMALL_FIX_DEPOSIT,
                 "deposit_required_cents")
    assert project["deposit_required_cents"] != 1500


def test_the_billable_floor_never_rewrites_the_units_on_site(api):
    """The floor is a pricing device: `effective_units` still reports the twenty
    units the household expects to have installed.

    PRD 3.3: "Second, the billable quantity is the greater of that unit quantity
    and the category's `minimum_billable_units`."

    Design: Corner/calculations/program_minimum_and_billable_units_floor_both_bind_the_quote
    """
    base = _small_fix_baseline(api)
    project = fx.sell_project(api, base, estimated_units=20.00,
                              site_address="3 Alder Court")

    assert_units(project["effective_units"], 20.00, "effective_units")
    assert_units(base["category"]["minimum_billable_units"], 100.00,
                 "minimum_billable_units")
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.QUOTED,
                              permit=PermitStatus.NOT_REQUIRED)
    assert_deposit_buckets(project, paid=0, held=0, applied=0, refunded=0,
                           forfeited=0)


@pytest.mark.parametrize(
    "estimated_units,quoted,deposit",
    [
        (200.00, 85000, 25500),
        (201.00, 85391, 25617),
        (500.00, 202300, 60690),
        (501.00, 202661, 60798),
    ],
)
def test_the_tier_ladder_prices_each_band_at_its_own_rate(api, estimated_units,
                                                          quoted, deposit):
    """Two hundred units cost the base rate throughout; the two hundred and first
    is charged at the band-B rate and the five hundred and first at band C.

    PRD 3.3: "Third, the billable quantity is spread across three marginal tiers:
    the first 200.00 units are charged at the category's
    `base_labor_rate_cents_per_unit`; the next 300.00 units — that is, the portion
    above 200.00 and up to 500.00 — are charged at the base rate multiplied by
    0.92, rounded half up to a whole number of cents before it is used; and every
    unit beyond 500.00 is charged at the base rate multiplied by 0.85, likewise
    rounded half up to whole cents before use."

    Design: Corner/calculations/tier_ladder_boundaries_at_two_hundred_and_five_hundred_billable_units
    """
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=estimated_units,
                              site_address="1 Band Way")

    assert_money(project["quoted_labor_cents"], quoted, "quoted_labor_cents")
    assert_money(project["deposit_required_cents"], deposit,
                 "deposit_required_cents")
    assert_units(project["effective_units"], estimated_units, "effective_units")


def test_the_two_band_steps_differ_so_an_average_rate_cannot_fit_both(api):
    """One more unit costs 391 cents at the first boundary and 361 cents at the
    second, on the same category and the same customer.

    PRD 3.3: "Each of the three band amounts is computed as its unit count
    multiplied by its band rate and **rounded half up to whole cents
    individually**, and only then are the three rounded band amounts added
    together to give the base amount."

    Design: Corner/calculations/tier_ladder_boundaries_at_two_hundred_and_five_hundred_billable_units
    """
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    quotes = {}
    for units, address in ((200.00, "1 Band Way"), (201.00, "2 Band Way"),
                           (500.00, "3 Band Way"), (501.00, "4 Band Way")):
        project = fx.sell_project(api, base, estimated_units=units,
                                  site_address=address)
        quotes[units] = project["quoted_labor_cents"]

    assert quotes[201.00] - quotes[200.00] == BAND_B_RATE, (
        "the marginal unit above 200.00 must be priced at the rounded band-B rate"
    )
    assert quotes[501.00] - quotes[500.00] == BAND_C_RATE, (
        "the marginal unit above 500.00 must be priced at the rounded band-C rate"
    )
    assert BAND_B_RATE != BAND_C_RATE

    customer = get_success_data(
        api.get_customer(base["customer"]["id"], PROJECT_COORDINATOR)
    )
    assert customer["project_count"] == 4


def _surveyed_firm(api):
    """One active firm carrying three customer surveys, all inside the rolling
    window and all in the undecayed lifetime band."""
    return fx.installer_with_events(
        api,
        [
            f.csat_event_payload(5, "2026-07-10T00:00:00.000Z"),
            f.csat_event_payload(1, "2026-07-17T00:00:00.000Z"),
            f.csat_event_payload(4, "2026-07-24T00:00:00.000Z"),
        ],
        jurisdiction_payload=f.plain_jurisdiction_payload(),
    )


def test_a_survey_writes_points_onto_the_satisfaction_dimension_alone(api):
    """Ratings of 5, 1 and 4 freeze satisfaction deltas of +10.00, -10.00 and
    +5.00 onto their ledger rows, and leave quality and timeliness at zero.

    PRD 3.9: "`CSAT_SURVEY` contributes 0.00 to quality and 0.00 to timeliness,
    and to satisfaction the quantity `csat_score` minus 3, multiplied by a step of
    5.00 — so a rating of 1 gives -10.00, 2 gives -5.00, 3 gives exactly 0.00, 4
    gives +5.00 and 5 gives +10.00."

    Design: Corner/calculations/csat_survey_points_move_only_the_satisfaction_dimension
    """
    network = _surveyed_firm(api)
    first, second, third = network["events"]

    assert_score(first["satisfaction_delta"], 10.00, "satisfaction_delta at 5")
    assert_score(second["satisfaction_delta"], -10.00, "satisfaction_delta at 1")
    assert_score(third["satisfaction_delta"], 5.00, "satisfaction_delta at 4")
    for event in (first, second, third):
        assert_score(event["quality_delta"], 0.00, "quality_delta")
        assert_score(event["timeliness_delta"], 0.00, "timeliness_delta")
        assert event["csat_score"] in (1, 4, 5)


def test_three_surveys_move_the_composite_by_a_quarter_of_their_net(api):
    """Satisfaction rises to 90.00 while the other two dimensions stay at the base
    score, so the composite moves by 0.25 of the five net points.

    PRD 3.9: "The composite is likewise pinned: it uses the **already-rounded**
    dimension scores, multiplying quality by 0.45, timeliness by 0.30 and
    satisfaction by 0.25, summing, and rounding half up once to two decimals."

    Design: Corner/calculations/csat_survey_points_move_only_the_satisfaction_dimension
    """
    network = _surveyed_firm(api)
    installer = network["installer"]

    assert_scorecard_dimensions(installer, quality=BASE_SCORE,
                                timeliness=BASE_SCORE, satisfaction=90.00,
                                composite=86.25)
    # Every event sits in the undecayed band, so the reporting score agrees.
    assert_score(installer["lifetime_composite_score"], 86.25,
                 "lifetime_composite_score")
    assert installer["rolling_event_count"] == 3
    assert installer["rolling_no_show_count"] == 0
    assert installer["status"] == InstallerStatus.ACTIVE
    assert installer["removal_eligible"] is False


def _aged_no_shows(api):
    """Two identical no-shows, one exactly 270 whole days old and one exactly 271,
    against the programme's default clock."""
    return fx.installer_with_events(
        api,
        [
            f.scorecard_event_payload("NO_SHOW", "2025-11-04T00:00:00.000Z"),
            f.scorecard_event_payload("NO_SHOW", "2025-11-03T00:00:00.000Z"),
        ],
        jurisdiction_payload=f.plain_jurisdiction_payload(),
    )


def test_the_rolling_variant_is_blind_to_both_aged_no_shows(api):
    """Both events are far outside the ninety-day window, so the governing score
    is an unblemished base score with no events and no no-shows counted.

    PRD 3.9: "The rolling variant considers only the events whose `occurred_at` is
    at or after the logical clock minus 90 days, an **inclusive** lower bound, so
    an event exactly 90 days old is still inside the window; every event inside it
    counts at full weight 1.00 and every event outside it counts for nothing at
    all."

    Design: Corner/calculations/decay_band_switches_at_two_hundred_seventy_whole_days_of_age
    """
    network = _aged_no_shows(api)
    older, oldest = network["events"]

    # The stored deltas are undecayed; attenuation happens only at scoring time.
    for event in (older, oldest):
        assert_score(event["timeliness_delta"], -20.00, "timeliness_delta")
        assert_score(event["quality_delta"], -4.00, "quality_delta")

    scorecard = fx.read_scorecard(api, network["installer"]["id"])
    assert_score(scorecard["rolling_composite_score"], BASE_SCORE,
                 "rolling_composite_score")
    assert_score(scorecard["rolling_quality_score"], BASE_SCORE,
                 "rolling_quality_score")
    assert scorecard["rolling_event_count"] == 0
    assert scorecard["rolling_no_show_count"] == 0
    assert scorecard["removal_eligible"] is False
    assert scorecard["probation_active"] is False


def test_one_day_of_age_moves_the_second_no_show_into_a_weaker_band(api):
    """At 270 whole days the event still weighs 0.60 and at 271 it weighs 0.30, so
    the reporting composite lands at 75.73 while the gating fields read 85.00.

    PRD 3.9: "The lifetime variant considers **every** event ever recorded, with
    no cut-off, attenuated by age: an age of 90 whole days or fewer weighs 1.00,
    more than 90 and up to 270 weighs 0.60, more than 270 and up to 540 weighs
    0.30, and beyond 540 weighs 0.10, the age being the whole days between
    `occurred_at` and the clock, floored."

    Design: Corner/calculations/decay_band_switches_at_two_hundred_seventy_whole_days_of_age
    """
    network = _aged_no_shows(api)
    installer = network["installer"]
    scorecard = fx.read_scorecard(api, installer["id"])

    # 85.00 - 4.00*0.60 - 4.00*0.30, and likewise on the other two dimensions.
    assert_score(scorecard["lifetime_quality_score"], 81.40,
                 "lifetime_quality_score")
    assert_score(scorecard["lifetime_timeliness_score"], 67.00,
                 "lifetime_timeliness_score")
    assert_score(scorecard["lifetime_satisfaction_score"], 76.00,
                 "lifetime_satisfaction_score")
    assert_score(scorecard["lifetime_composite_score"], 75.73,
                 "lifetime_composite_score")
    assert scorecard["lifetime_event_count"] == 2

    # The reporting figure gates nothing: two lifetime no-shows leave the firm
    # active because the removal counter only ever looks at the rolling window.
    assert_score(installer["quality_score"], BASE_SCORE, "quality_score")
    assert_score(installer["composite_score"], BASE_SCORE, "composite_score")
    assert_score(installer["lifetime_composite_score"], 75.73,
                 "lifetime_composite_score")
    assert installer["status"] == InstallerStatus.ACTIVE
    assert installer["removal_eligible"] is False


def _full_deposit_install(api):
    """A whole-quote deposit of 19200 against a job the measurement shrinks, taken
    all the way to the point where the installer is about to report it finished."""
    ctx = fx.deposited_project(
        api,
        category_payload=f.full_deposit_category_payload(),
        jurisdiction_payload=f.plain_jurisdiction_payload(),
        estimated_units=400.00,
        site_address="9 Cedar Row",
    )
    project_id = ctx["project"]["id"]
    booked = fx.book_measurement(api, project_id, "2026-08-05T14:00:00.000Z")
    ctx["measurement"] = fx.complete_measurement(api, booked["id"], 380.00)

    jurisdiction_id = ctx["jurisdiction"]["id"]
    ctx.update(fx.activated_installer(
        api, jurisdiction_id,
        installer_payload=f.installer_payload(
            legal_name="Northside Millwork LLC",
            primary_trade_code=TradeCode.MILLWORK),
        credential_payload=f.credential_payload(
            jurisdiction_id, trade_code=TradeCode.MILLWORK,
            license_number="MW-31007"),
    ))
    ctx["delivery"] = fx.plan_delivery(
        api, project_id, f.delivery_payload(sku_count=4, material_cost_cents=90000)
    )
    ctx["assignment"] = fx.hold_assignment(api, project_id, ctx["installer"]["id"])
    ctx["assignment"] = get_success_data(
        api.confirm_assignment(ctx["assignment"]["id"], PROJECT_COORDINATOR)
    )
    fx.set_clock(api, "2026-08-25T08:00:00.000Z")
    ctx["assignment"] = get_success_data(
        api.start_assignment(ctx["assignment"]["id"],
                             make_installer_headers(ctx["installer"]["id"]))
    )
    fx.set_clock(api, "2026-08-25T15:30:00.000Z")
    ctx["project"] = fx.read_project(api, project_id)
    return ctx


def _report_finished(api, ctx):
    return get_success_data(
        api.complete_assignment(
            ctx["assignment"]["id"],
            f.completion_payload("2026-08-25T15:30:00.000Z"),
            make_installer_headers(ctx["installer"]["id"]),
        )
    )


def test_a_deposit_larger_than_the_invoice_overflows_into_the_refund_bucket(api):
    """The waterfall fills the applied bucket to the whole 18280-cent invoice and
    only the 920-cent surplus reaches the refund bucket.

    PRD 3.6: "The deposit waterfall runs **once**, at the moment
    `final_labor_cents` is first written: the applied amount is the lesser of
    `deposit_held_cents` and `total_due_cents`, which is added to
    `deposit_applied_cents` and subtracted from `deposit_held_cents`; any surplus
    still held — which can only arise when the deposit exceeds the entire invoice —
    is moved into `deposit_refunded_cents`; and `deposit_held_cents` finishes at
    zero."

    Design: Corner/calculations/deposit_waterfall_refunds_the_surplus_when_the_deposit_exceeds_the_invoice
    """
    ctx = _full_deposit_install(api)
    assert_money(ctx["project"]["deposit_held_cents"], 19200, "deposit_held_cents")

    _report_finished(api, ctx)
    project = fx.read_project(api, ctx["project"]["id"])

    # FINAL bills the measured 380.00 units: 200.00 * 50 + 180.00 * 46.
    assert_money(project["final_labor_cents"], 18280, "final_labor_cents")
    assert_money(project["total_due_cents"], 18280, "total_due_cents")
    assert_deposit_buckets(project, paid=19200, held=0, applied=18280,
                           refunded=920, forfeited=0)


def test_the_overflowing_waterfall_settles_without_a_balance_stage(api):
    """A zero balance sends the money dimension from DEPOSIT_HELD straight to
    SETTLED, and the frozen quote is left exactly as it was sold.

    PRD 3.6: "The money dimension moves `DEPOSIT_HELD → BALANCE_DUE` when
    `balance_due_cents` is above zero, or straight `DEPOSIT_HELD → SETTLED` when it
    is exactly zero."

    Design: Corner/calculations/deposit_waterfall_refunds_the_surplus_when_the_deposit_exceeds_the_invoice
    """
    ctx = _full_deposit_install(api)
    measurement = ctx["measurement"]
    # A 5.00% shrink is well under the ten per cent change-order trigger.
    assert_score(measurement["variance_pct"], 5.00, "variance_pct")
    assert measurement["change_order_triggered"] is False

    _report_finished(api, ctx)
    project = fx.read_project(api, ctx["project"]["id"])

    assert_money(project["balance_due_cents"], 0, "balance_due_cents")
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.INSTALL_COMPLETE,
                              financial=FinancialStatus.SETTLED,
                              permit=PermitStatus.NOT_REQUIRED)
    assert_money(project["quoted_labor_cents"], 19200, "quoted_labor_cents")
    assert_money(project["deposit_required_cents"], 19200,
                 "deposit_required_cents")
    assert_units(project["effective_units"], 380.00, "effective_units")
    assert_money(project["change_order_upcharge_cents"], 0,
                 "change_order_upcharge_cents")


def _variance_project(api):
    """A 420.00-unit sale re-measured at 500.00 units, so the measurement cascade
    mints the disclosure change order the household must answer."""
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.plain_jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    booked = fx.book_measurement(api, project["id"], "2026-08-05T14:00:00.000Z")
    base["measurement"] = fx.complete_measurement(api, booked["id"], 500.00)
    base["project"] = fx.read_project(api, project["id"])
    base["quoted_labor_cents"] = project["quoted_labor_cents"]
    base["variance"] = fx.variance_change_order(api, project["id"])
    return base


def _four_change_orders(api):
    """The disclosure, one accepted customer request, one declined site condition
    and one that never leaves the drawing board."""
    ctx = _variance_project(api)
    project_id = ctx["project"]["id"]
    customer_id = ctx["customer"]["id"]

    fx.accept_change_order(api, ctx["variance"]["id"], customer_id)
    ctx["after_variance"] = fx.read_project(api, project_id)

    accepted = fx.raise_change_order(api, project_id, [f.primary_line(10.00)])
    ctx["accepted_priced_at_draft"] = accepted["upcharge_cents"]
    get_success_data(api.submit_change_order(accepted["id"], PROJECT_COORDINATOR))
    ctx["accepted"] = fx.accept_change_order(api, accepted["id"], customer_id)
    ctx["after_accept"] = fx.read_project(api, project_id)

    declined = fx.raise_change_order(api, project_id, [f.trim_line(12.00)],
                                     origin=ChangeOrderOrigin.SITE_CONDITION)
    get_success_data(api.submit_change_order(declined["id"], PROJECT_COORDINATOR))
    ctx["declined"] = get_success_data(
        api.decide_change_order(declined["id"],
                                f.decision_payload(ChangeOrderDecision.DECLINE),
                                make_customer_headers(customer_id))
    )
    ctx["after_decline"] = fx.read_project(api, project_id)

    ctx["draft"] = fx.raise_change_order(api, project_id, [f.fixture_line(2.00)])
    ctx["project"] = fx.read_project(api, project_id)
    return ctx


def test_accepting_a_variance_disclosure_adds_nothing_to_the_upcharge(api):
    """The disclosure prices the re-measured job at 31280 cents above the frozen
    quote, and accepting it leaves the project's upcharge at zero.

    PRD 3.4: "It is a disclosure and nothing more: accepting such a change order
    adds **nothing** to `change_order_upcharge_cents`, because those same measured
    units are already charged by the final labour variant when the installer
    reports the work complete."

    Design: Corner/calculations/only_accepted_line_itemised_change_orders_feed_the_project_upcharge
    """
    ctx = _variance_project(api)
    variance = ctx["variance"]

    assert_money(ctx["quoted_labor_cents"], 171020, "quoted_labor_cents")
    assert_score(ctx["measurement"]["variance_pct"], 19.05, "variance_pct")
    assert ctx["measurement"]["change_order_triggered"] is True
    assert variance["origin"] == ChangeOrderOrigin.MEASUREMENT_VARIANCE
    # FINAL(500.00 units) is 202300, and the disclosure is the difference.
    assert_money(variance["upcharge_cents"], 31280, "upcharge_cents")
    assert variance["lines"] == []

    accepted = fx.accept_change_order(api, variance["id"], ctx["customer"]["id"])
    assert accepted["status"] == ChangeOrderStatus.ACCEPTED

    project = fx.read_project(api, ctx["project"]["id"])
    assert_money(project["change_order_upcharge_cents"], 0,
                 "change_order_upcharge_cents")
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.MEASURED)


def test_a_declined_change_order_is_filtered_out_of_the_upcharge(api):
    """The accepted customer request adds its 4505 cents; the declined site
    condition prices at 3765 and adds nothing.

    PRD 3.4: "A `DECLINE` sets `status` to `DECLINED` and stamps `decided_at`; on a
    `CUSTOMER_REQUEST` or `SITE_CONDITION` change order it simply returns the
    project to `MEASURED` with no money change, but on a `MEASUREMENT_VARIANCE`
    change order it means the household has refused the re-measured scope, and the
    project is driven `CHANGE_PENDING → CANCELLED` with the full cancellation
    cascade of §3.8 — settlement computed, scheduled measurement voided, delivery
    returned, assignment released."

    Design: Corner/calculations/only_accepted_line_itemised_change_orders_feed_the_project_upcharge
    """
    ctx = _four_change_orders(api)

    # 10.00 * 425 * 1.00 * 1.06 for the accepted request.
    assert_money(ctx["accepted"]["upcharge_cents"], 4505, "upcharge_cents")
    assert ctx["accepted"]["status"] == ChangeOrderStatus.ACCEPTED
    # 12.00 * 296 * 1.00 * 1.06 is 3765.12, which rounds to 3765.
    assert_money(ctx["declined"]["upcharge_cents"], 3765, "upcharge_cents")
    assert ctx["declined"]["status"] == ChangeOrderStatus.DECLINED
    assert ctx["declined"]["decided_at"] is not None

    assert_money(ctx["after_variance"]["change_order_upcharge_cents"], 0,
                 "change_order_upcharge_cents after the disclosure")
    assert_money(ctx["after_accept"]["change_order_upcharge_cents"], 4505,
                 "change_order_upcharge_cents after the accepted request")
    assert_money(ctx["after_decline"]["change_order_upcharge_cents"], 4505,
                 "change_order_upcharge_cents after the declined request")


def test_a_draft_change_order_is_priced_but_not_yet_in_force(api):
    """The fourth change order prices at 15582 cents while it sits at DRAFT, and
    the project's upcharge still reports only the one accepted request.

    PRD 3.4: "The new change order opens at `status` `DRAFT` with `upcharge_cents`
    and `net_primary_units_delta` computed, `revision_count` zero, and
    `revision_note` and `decided_at` null; the project's `version` increments; and
    if `supersedes_change_order_id` was supplied, that earlier change order is
    driven from `DRAFT`, `PENDING_CUSTOMER` or `REVISION_REQUESTED` to
    `SUPERSEDED`."

    Design: Corner/calculations/only_accepted_line_itemised_change_orders_feed_the_project_upcharge
    """
    ctx = _four_change_orders(api)
    draft = ctx["draft"]

    # 2.00 * 7350 * 1.00 * 1.06.
    assert_money(draft["upcharge_cents"], 15582, "upcharge_cents")
    assert draft["status"] == ChangeOrderStatus.DRAFT
    assert draft["decided_at"] is None
    assert draft["revision_count"] == 0
    assert_money(ctx["accepted_priced_at_draft"], 4505,
                 "upcharge_cents priced at DRAFT")

    project = ctx["project"]
    assert_money(project["change_order_upcharge_cents"], 4505,
                 "change_order_upcharge_cents")
    # No installer has reported the work finished, so there is no invoice yet.
    assert project["final_labor_cents"] is None
    assert_money(project["total_due_cents"], 0, "total_due_cents")
    assert_money(project["balance_due_cents"], 0, "balance_due_cents")
