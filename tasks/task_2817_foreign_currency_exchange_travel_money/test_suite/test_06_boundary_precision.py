"""Edges probed one step either side.

PRD 3.5: "if settled_usd_gross_cents has reached 1,000,000 cents (ten thousand
dollars), one regulatory report of type THRESHOLD_REPORT is created in DRAFT" - a
reached-or-exceeded edge, with the near-threshold band running from 800000 cents up
to 999999 inclusive.  PRD 3.3: a submitted plan "must end up carrying at least one
target line, since submitting an empty plan is refused with
ERR_PLAN_NO_TARGET_LINES".
"""

from test_helpers import (
    ApiErrorId,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

CHF_SELL_RATE_MICROS = 902_500
CHF_MIX = [f.denom(500, 20), f.denom(20000, 100)]
EXACT_HIT = [f.denom(20000, 45), f.denom(500, 5)]
ONE_STEP_BELOW = [f.denom(20000, 45)]


def _chf_world(api):
    """BR-ZRH selling CHF at 902500 micros with a deep note stock and two
    document-complete customers."""
    world = fx.trading_world(
        api,
        vault_limit_usd_cents=20_000_000,
        branch_overrides={"code": "BR-ZRH", "name": "Zurich Bahnhofstrasse"},
        currency_payload=f.chf_currency_payload(
            standard_denominations=[500, 1000, 5000, 10000, 20000],
            buyback_eligible=False,
        ),
        mid_rate_micros=950_000,
        card_overrides={"sell_spread_bps": 500, "board_display_label": "CHF Franc"},
        position_mix=CHF_MIX,
        customer_overrides={
            "full_name": "Hana Sato",
            "nationality_code": "JP",
            "id_document_number": "JP-30012",
            "id_document_expiry": "2027-01-01T00:00:00Z",
        },
    )
    assert world["card"]["sell_rate_micros"] == CHF_SELL_RATE_MICROS
    world["second_customer"] = fx.identified_customer(
        api,
        full_name="Ivan Petrov",
        nationality_code="BG",
        id_document_number="BG-77120",
        id_document_expiry="2027-01-01T00:00:00Z",
    )
    return world


def _dual_control_settle(api, world, denominations, teller_headers, manager_headers, customer_id=None):
    """Quote and authorize as the teller, settle as the manager."""
    txn = fx.quote_deal(
        api, world, denominations=denominations, headers=teller_headers, customer_id=customer_id
    )
    fx.authorize_deal(api, txn["id"], teller_headers)
    return fx.settle_deal(api, txn["id"], manager_headers)


def test_a_settlement_landing_exactly_on_the_reporting_threshold_files_a_report(
    api, teller_headers, manager_headers, compliance_headers
):
    """45 x 20000 CHF converts to 997230 cents and the 5 x 500 line contributes the
    missing 2770, so the settled gross is exactly 1000000 and one DRAFT
    THRESHOLD_REPORT is raised citing that aggregate over a single transaction.

    Design: Difficulty/boundary_precision_check/threshold_report_fires_at_exactly_one_million_cents_and_not_one_step_below
    """
    world = _chf_world(api)

    settled = _dual_control_settle(api, world, EXACT_HIT, teller_headers, manager_headers)

    assert settled["fx_gross_minor_units"] == 902500
    assert settled["settled_usd_gross_cents"] == 1000000
    assert a.usd_cents_from_minor(900000, CHF_SELL_RATE_MICROS) == 997230
    assert a.usd_cents_from_minor(2500, CHF_SELL_RATE_MICROS) == 2770

    rows, meta = validate_paginated(
        api.list_compliance_reports(
            compliance_headers,
            {"customer_id": world["customer"]["id"], "report_type": "THRESHOLD_REPORT"},
        )
    )
    assert meta["total_count"] == 1
    report = rows[0]
    a.assert_compliance_report(report)
    assert report["aggregate_usd_cents"] == 1000000
    assert report["transaction_count"] == 1
    assert report["status"] == "DRAFT"
    assert report["triggering_transaction_id"] == settled["id"]

    customer = fx.read_customer(api, world["customer"]["id"], compliance_headers)
    assert customer["near_threshold_txn_count"] == 0


def test_a_settlement_one_step_below_the_threshold_files_nothing(
    api, teller_headers, manager_headers, compliance_headers
):
    """997230 cents is 2770 short of the edge: no THRESHOLD_REPORT exists for that
    customer, yet the settlement does clear the 800000-cent near-threshold floor and
    is counted as one near-threshold deal.

    Design: Difficulty/boundary_precision_check/threshold_report_fires_at_exactly_one_million_cents_and_not_one_step_below
    """
    world = _chf_world(api)
    other = world["second_customer"]

    settled = _dual_control_settle(
        api, world, ONE_STEP_BELOW, teller_headers, manager_headers, customer_id=other["id"]
    )

    assert settled["fx_gross_minor_units"] == 900000
    assert settled["settled_usd_gross_cents"] == 997230

    _, meta = validate_paginated(
        api.list_compliance_reports(
            compliance_headers,
            {"customer_id": other["id"], "report_type": "THRESHOLD_REPORT"},
        )
    )
    assert meta["total_count"] == 0

    customer = fx.read_customer(api, other["id"], compliance_headers)
    assert customer["near_threshold_txn_count"] == 1
    assert customer["rolling_30d_settled_usd_cents"] == 997230


def _empty_plan(api):
    """A DRAFT plan created with target_lines omitted."""
    branch = fx.register_branch(api, vault_limit_usd_cents=5_000_000)
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    corridor = fx.register_corridor(
        api,
        code="LHR-CMN-SUMMER",
        destination_country_code="MA",
        destination_currency_code="EUR",
        season="SUMMER",
        season_start_date="2026-06-01T00:00:00Z",
        season_end_date="2026-09-01T00:00:00Z",
        demand_index_bps=13500,
    )
    return fx.draft_plan(api, branch["id"], corridor["id"], season_days=92)


def test_submitting_a_plan_with_no_target_lines_is_refused(api, manager_headers):
    """Cardinality zero is below the edge: the submit is refused with
    ERR_PLAN_NO_TARGET_LINES and the plan is left in DRAFT with no submitter
    recorded, no target lines and no computed targets.

    Design: Difficulty/boundary_precision_check/submit_plan_with_zero_target_lines_rejected
    """
    plan = _empty_plan(api)
    assert plan["target_lines"] == []

    validate_error(
        api.submit_inventory_plan(plan["id"], {}, manager_headers),
        ApiErrorId.ERR_PLAN_NO_TARGET_LINES,
    )

    unchanged = fx.read_plan(api, plan["id"])
    a.assert_inventory_plan(unchanged)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_by_user_id"] is None
    assert unchanged["target_lines"] == []
    assert unchanged["computed_targets"] == []


def test_one_target_line_is_the_first_accepted_cardinality(api, manager_headers):
    """The same plan resubmitted with exactly one EUR line of 2000 baseline daily
    minor units is accepted, moves to SUBMITTED and computes a 250000-unit target -
    so the refusal above was about the empty array, not about the plan.

    Design: Difficulty/boundary_precision_check/submit_plan_with_zero_target_lines_rejected
    """
    plan = _empty_plan(api)
    validate_error(
        api.submit_inventory_plan(plan["id"], {}, manager_headers),
        ApiErrorId.ERR_PLAN_NO_TARGET_LINES,
    )

    submitted = validate_success(
        api.submit_inventory_plan(
            plan["id"], {"target_lines": [f.target_line("EUR", 2000)]}, manager_headers
        )
    )

    assert submitted["status"] == "SUBMITTED"
    assert len(submitted["computed_targets"]) == 1
    assert submitted["computed_targets"][0]["target_minor_units"] == 250000
