"""Supply forecasts: variance/coverage dual variants, weekly cold-chain
capacity aggregation, horizon validation, OCC freeze, freeze supersede
cascade (PRD sections 2.8, 3.9).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    create_account,
    create_forecast,
    create_frozen_forecast,
    create_kit,
    create_lot,
    create_order,
    create_passed_lot,
    create_submitted_forecast,
    create_supply_forecast_payload,
    deliver_order,
    forecast_advance_payload,
    forecast_line,
    freeze_forecast,
    order_line,
    ship_order,
    submit_forecast,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers import api_client

WEEK_2026_09_07 = "2026-09-07T00:00:00Z"  # Monday
WEEK_2026_09_14 = "2026-09-14T00:00:00Z"  # Monday


def _setup_variance_scenario():
    """Account; kit (16 samples/kit, FROZEN_20, 60d shelf); lot LP 80 units
    QC_PASSED; lot LQ 40 units still PENDING_QC; SUBMITTED forecast of 75
    units for ISO week 2026-09-07; 50 units delivered during that week."""
    account = create_account()
    kit = create_kit()
    lot_p = create_passed_lot(
        kit_id=kit["id"], lot_number="LP", quantity_units=80
    )
    lot_q = create_lot(kit_id=kit["id"], lot_number="LQ", quantity_units=40)
    forecast = create_submitted_forecast(
        account_id=account["id"],
        lines=[forecast_line(kit["kit_code"], WEEK_2026_09_07, 75)],
    )
    order = create_order(
        account["id"], [order_line(kit["kit_code"], 50)]
    )
    submit_order(order["id"], account["id"])
    ship_order(order["id"])
    advance_clock("2026-09-08T00:00:00Z")
    deliver_order(order["id"])
    return {"account": account, "kit": kit, "lot_p": lot_p, "lot_q": lot_q,
            "forecast": forecast}


def _read_variance(forecast_id: str) -> dict:
    return validate_success(
        api_client.get_supply_forecast(
            forecast_id,
            TEST_USERS["supply_planner_headers"],
            params={"include_variance": "true"},
        )
    )


class TestForecastCoverageDualVariants:
    def test_variance_line_reports_actuals_against_forecast(self, api):
        """The variance view reports forecast 75, actual delivered 50,
        variance -25 for the ISO week of the delivery.

        PRD §3.9: "Each entry carries the line's `kit_code` and `week_start`, the `forecast_quantity` from the line, and the `actual_delivered_units` — the units of that kit from the account's `DELIVERED` orders whose `delivered_at` falls inside the half-open ISO week starting at `week_start`."
        PRD §3.9: "The `variance` is actual minus forecast."

        Design: Difficulty/dual_variant_calc/forecast_coverage_optimistic_vs_conservative
        """
        bag = _setup_variance_scenario()
        data = _read_variance(bag["forecast"]["id"])
        assert len(data["variance_lines"]) == 1
        line = data["variance_lines"][0]
        assert line["kit_code"] == bag["kit"]["kit_code"]
        assert line["forecast_quantity"] == 75
        assert line["actual_delivered_units"] == 50
        assert line["variance"] == -25

    def test_optimistic_counts_pending_lots_conservative_does_not(self, api):
        """On identical data the conservative coverage counts only the
        QC_PASSED lot (80 - 50 delivered = 30) while the optimistic variant
        also counts the PENDING_QC lot's 40 units (70).

        PRD §3.9: "Two coverage figures accompany it: `coverage_conservative_units` sums `available_units` over the kit's usable lots — `QC_PASSED`, `INTACT`, and unexpired — while `coverage_optimistic_units` adds the available units of lots still in `PENDING_QC` that are `INTACT` and unexpired, so the two numbers diverge exactly when usable pending lots exist."

        Design: Difficulty/dual_variant_calc/forecast_coverage_optimistic_vs_conservative
        """
        bag = _setup_variance_scenario()
        data = _read_variance(bag["forecast"]["id"])
        line = data["variance_lines"][0]
        assert line["coverage_conservative_units"] == 30
        assert line["coverage_optimistic_units"] == 70
        assert (
            line["coverage_optimistic_units"] - line["coverage_conservative_units"]
            == 40
        ), "the delta must be exactly the un-released lot's usable units"


class TestColdChainWeeklyCapacity:
    def _setup_two_accounts_two_frozen_kits(self):
        account_a = create_account(name="Lab Upsilon A")
        account_b = create_account(name="Lab Upsilon B")
        kit_f1 = create_kit()  # defaults: FROZEN_20
        kit_f2 = create_kit(run_type="STD_LONG", flow_cell_version="FC_MID",
                            chemistry_version="V2")  # still FROZEN_20
        return account_a, account_b, kit_f1, kit_f2

    def test_aggregate_demand_above_capacity_rejected(self, api):
        """400 units already SUBMITTED by account A plus a 150-unit submission
        by account B push the (week, FROZEN_20) bucket to 550 > 500; the whole
        submission is rejected and B's forecast stays DRAFT.

        PRD §3.9: "For every ISO week the forecast touches and for each `cold_chain_class`, demand is the aggregate quantity of this forecast's lines in that week and class plus the lines of every other forecast in `SUBMITTED` or `FROZEN` state — across all accounts — in the same week and class; two forecasts touching the same week always aggregate."
        PRD §3.9: "Demand exactly equal to a bucket's capacity is allowed; any bucket pushed above capacity rejects the whole submission with `ERR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/cold_chain_week_aggregate_capacity
        """
        account_a, account_b, kit_f1, kit_f2 = (
            self._setup_two_accounts_two_frozen_kits()
        )
        forecast_a = create_submitted_forecast(
            account_id=account_a["id"],
            lines=[forecast_line(kit_f1["kit_code"], WEEK_2026_09_07, 400)],
        )
        assert forecast_a["forecast_state"] == "SUBMITTED"
        forecast_b = create_forecast(
            account_id=account_b["id"],
            lines=[forecast_line(kit_f2["kit_code"], WEEK_2026_09_07, 150)],
        )
        resp = api_client.advance_supply_forecast(
            forecast_b["id"],
            forecast_advance_payload("SUBMIT"),
            TEST_USERS["supply_planner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        after = validate_success(
            api_client.get_supply_forecast(
                forecast_b["id"], TEST_USERS["supply_planner_headers"]
            )
        )
        assert after["forecast_state"] == "DRAFT"

    def test_demand_exactly_equal_to_capacity_allowed(self, api):
        """400 + 100 == 500: demand exactly equal to the FROZEN_20 weekly
        capacity is allowed (the rejection is strict excess).

        PRD §3.9: "Weekly capacity is 500 units for `FROZEN_20` and 1,000 units for `REFRIGERATED_4`."
        PRD §3.9: "Demand exactly equal to a bucket's capacity is allowed; any bucket pushed above capacity rejects the whole submission with `ERR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/cold_chain_week_aggregate_capacity
        """
        account_a, account_b, kit_f1, kit_f2 = (
            self._setup_two_accounts_two_frozen_kits()
        )
        create_submitted_forecast(
            account_id=account_a["id"],
            lines=[forecast_line(kit_f1["kit_code"], WEEK_2026_09_07, 400)],
        )
        forecast_b = create_submitted_forecast(
            account_id=account_b["id"],
            lines=[forecast_line(kit_f2["kit_code"], WEEK_2026_09_07, 100)],
        )
        assert forecast_b["forecast_state"] == "SUBMITTED"


class TestForecastHorizonAndFreeze:
    def test_non_monday_week_start_rejected(self, api):
        """A line whose week_start is a Tuesday (2026-09-08) violates the
        Monday-00:00:00Z horizon rule at creation.

        PRD §3.9: "Every `week_start` must be a Monday at 00:00:00Z, must not fall before the current week, and must lie within twenty-six weeks of the current logical clock; the horizon rule is enforced both at creation and again at submission, and a violation is `ERR_FORECAST_HORIZON_INVALID` (HTTP 422)."

        Design: Corner/validations/forecast_horizon_invalid_rejected
        """
        account = create_account()
        kit = create_kit()
        resp = api_client.create_supply_forecast(
            create_supply_forecast_payload(
                account["id"],
                [forecast_line(kit["kit_code"], "2026-09-08T00:00:00Z", 10)],
            ),
            TEST_USERS["supply_planner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORECAST_HORIZON_INVALID)

    def test_occ_stale_version_on_freeze(self, api):
        """FREEZE carrying the pre-submit version is rejected 412; retrying
        with the observed post-submit version freezes the forecast.

        PRD §2.8: "Freezing a supply forecast likewise requires `expected_forecast_version` holding the forecast's `version` as last observed; a freeze legitimately supersedes the account's prior `FROZEN` forecast and advances the version, so a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_forecast_freeze
        """
        account = create_account()
        kit = create_kit()
        forecast = create_forecast(
            account_id=account["id"],
            lines=[forecast_line(kit["kit_code"], WEEK_2026_09_07, 10)],
        )
        submitted = submit_forecast(forecast["id"])
        observed_version = submitted["version"]
        resp = api_client.advance_supply_forecast(
            forecast["id"],
            forecast_advance_payload(
                "FREEZE", expected_forecast_version=observed_version - 1
            ),
            TEST_USERS["supply_planner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        frozen = freeze_forecast(forecast["id"], observed_version)
        assert frozen["forecast_state"] == "FROZEN"

    def test_freeze_supersedes_prior_frozen_forecast(self, api):
        """Freezing forecast B cascades the account's earlier FROZEN forecast
        A to SUPERSEDED with no direct call on A.

        PRD §3.9: "A successful freeze moves `SUBMITTED` to `FROZEN` and, in the same operation, supersedes every other `FROZEN` forecast belonging to the same account — each of those transitions `FROZEN` to `SUPERSEDED` with its own version increment."

        Design: Corner/cross_cutting_layers/forecast_freeze_supersedes_prior_frozen
        """
        account = create_account()
        kit = create_kit()
        forecast_a = create_frozen_forecast(
            account_id=account["id"],
            lines=[forecast_line(kit["kit_code"], WEEK_2026_09_07, 10)],
        )
        forecast_b = create_submitted_forecast(
            account_id=account["id"],
            lines=[forecast_line(kit["kit_code"], WEEK_2026_09_14, 20)],
        )
        frozen_b = freeze_forecast(forecast_b["id"], forecast_b["version"])
        assert frozen_b["forecast_state"] == "FROZEN"
        after_a = validate_success(
            api_client.get_supply_forecast(
                forecast_a["id"], TEST_USERS["supply_planner_headers"]
            )
        )
        assert after_a["forecast_state"] == "SUPERSEDED"
