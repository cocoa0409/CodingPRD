"""Production-line lifecycle: commissioning gate, ramp promotion, re-ramp
cycle, suspension edges, and decommissioning."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    close_quarter,
    create_customer,
    create_module_series,
    create_production_line,
    create_promoted_line,
    create_ramping_line,
    create_reservation,
    get_line,
    post_production_run,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]


def test_commission_without_first_article_rejected(api):
    """PRD §3.2: "A line is commissionable only after at least one production
    run — the first-article run — has been posted against it; attempting to
    commission earlier is rejected with `ERR_LINE_NOT_COMMISSIONABLE`
    (HTTP 422)."

    Design: Corner/state_machines/commission_without_first_article_rejected
    """
    line = create_production_line()
    resp = api.commission_line(line["id"], PM)
    validate_error(resp, ApiErrorId.ERR_LINE_NOT_COMMISSIONABLE)
    assert get_line(line["id"])["status"] == "COMMISSIONING"


def test_suspend_from_commissioning_rejected(api):
    """PRD §3.2: "A `PlantManager` may suspend a line from either `RAMPING` or
    `AT_CAPACITY`, moving it to `SUSPENDED`."
    PRD §2.5: "A request whose target resource is not in a state from which the
    requested transition is defined is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/suspend_from_commissioning_rejected
    """
    line = create_production_line()
    resp = api.suspend_line(line["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_line(line["id"])["status"] == "COMMISSIONING"


def test_decommission_with_open_reservation_rejected(api):
    """PRD §3.2: "It is permitted only when no reservation on the line is in
    `PENDING`, `DEPOSIT_HELD`, `ACTIVE`, or `CONSTRAINED` status; otherwise the
    request is rejected with `ERR_LINE_HAS_OPEN_RESERVATIONS` (HTTP 422)."

    Design: Corner/state_machines/decommission_with_open_reservation_rejected
    """
    customer = create_customer()
    series = create_module_series()
    line = create_production_line()
    create_reservation(customer, line, series, deposit_usd=125000.0)

    resp = api.decommission_line(line["id"], PM)
    validate_error(resp, ApiErrorId.ERR_LINE_HAS_OPEN_RESERVATIONS)
    assert get_line(line["id"])["status"] == "COMMISSIONING"


def test_decommission_terminal_lockdown(api):
    """PRD §3.2: "Decommissioning moves a line from `COMMISSIONING`, `RAMPING`,
    `AT_CAPACITY`, or `SUSPENDED` to the terminal `DECOMMISSIONED`."
    PRD §2.5: "A request whose target resource is not in a state from which the
    requested transition is defined is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/decommission_terminal_lockdown
    """
    line = create_production_line()
    resp = api.decommission_line(line["id"], PM)
    data = validate_success(resp, 200)
    assert data["status"] == "DECOMMISSIONED"

    resp = api.suspend_line(line["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_line(line["id"])["status"] == "DECOMMISSIONED"


class TestRampExitGate:
    """Ramp promotion needs BOTH the yield floor and the quarter gate."""

    def test_ramp_exit_promotion_requires_quarter_gate(self, api):
        """PRD §3.2: "If the just-closed quarter's `actual_yield_rate` is at
        least 0.85 and the pre-increment `ramp_quarter_index` is at least 2, the
        line is promoted `RAMPING → AT_CAPACITY`, making it eligible for new
        reservation activation of any size and incrementing its `version`."
        PRD §3.2: "The operation returns the `closed_quarter` index plus counts
        of `lines_promoted` and `reservations_completed` (the close-out sweep of
        §3.4 runs in the same operation)."

        Design: Difficulty/combinatorial_formula/ramp_exit_requires_yield_and_quarter_gate
        """
        bundle = create_ramping_line(good_modules=90, input_modules=100)
        line = bundle["line"]
        series = bundle["series"]

        # Close quarter 0 (first-article 0.9000 yield, pre-increment index 0).
        close_quarter()
        post_production_run(line["id"], series["id"], quarter=1, good_modules=90)

        # Close quarter 1: yield 0.9000 >= 0.85 but pre-increment index 1 < 2.
        close2 = close_quarter()
        assert close2["lines_promoted"] == 0, (
            f"quarter gate not met: lines_promoted must be 0, got {close2['lines_promoted']}"
        )
        line_after = get_line(line["id"])
        assert line_after["status"] == "RAMPING"
        assert line_after["actual_yield_rate"] == pytest.approx(0.9000, abs=1e-6)

        post_production_run(line["id"], series["id"], quarter=2, good_modules=90)

        # Close quarter 2: yield 0.9000 and pre-increment index 2 >= 2.
        close3 = close_quarter()
        assert close3["lines_promoted"] == 1, (
            f"gate met at index 2: lines_promoted must be 1, got {close3['lines_promoted']}"
        )
        assert get_line(line["id"])["status"] == "AT_CAPACITY"

    def test_ramp_empty_quarter_still_advances_index(self, api):
        """PRD §3.2: "If the closed quarter has no runs at all,
        `actual_yield_rate` stays null and the line does not promote — but the
        quarter index still advances by 1."

        Design: Difficulty/combinatorial_formula/ramp_exit_requires_yield_and_quarter_gate
        """
        bundle = create_ramping_line(good_modules=70, input_modules=100)
        line = bundle["line"]

        # Close quarter 0 (has the first-article run, yield 0.7000 < 0.85).
        close1 = close_quarter()
        assert close1["lines_promoted"] == 0
        # Close quarter 1 with no runs posted: no promotion, index advances.
        close2 = close_quarter()
        assert close2["lines_promoted"] == 0

        line_after = get_line(line["id"])
        assert line_after["status"] == "RAMPING"
        assert line_after["ramp_quarter_index"] == 2, (
            "empty quarter must still advance the quarter index by 1"
        )


class TestReintroduceCycle:
    """AT_CAPACITY -> RAMPING re-ramp cycle on a new module series."""

    def test_reintroduce_cycles_line_back_to_ramping(self, api):
        """PRD §3.2: "A line at `AT_CAPACITY` can be sent back to `RAMPING` when
        a new module series is introduced on it. Reintroduction requires a
        `series_id` in the payload that is `ACTIVE` and differs from the series
        of the line's most recent production run; it resets `ramp_quarter_index`
        to 0 and `actual_yield_rate` to null, and increments the line's
        `version`."

        Design: Difficulty/non_linear_state_machine/line_capacity_to_ramping_reintroduce_cycle
        """
        bundle = create_promoted_line()
        line = bundle["line"]
        assert line["status"] == "AT_CAPACITY"

        series7 = create_module_series(
            series_code="S7",
            technology="CDTE_THIN_FILM_CUTE",
            nominal_wattage=490.0,
            bin_profile=[
                {"bin_code": "C1", "wattage": 490.0, "fraction": 0.6},
                {"bin_code": "C2", "wattage": 480.0, "fraction": 0.4},
            ],
            temp_coefficient=-0.0026,
        )
        resp = api.reintroduce_line(line["id"], {"series_id": series7["id"]}, PM)
        data = validate_success(resp, 200)
        assert data["status"] == "RAMPING", "line must cycle back to RAMPING"
        assert data["ramp_quarter_index"] == 0
        assert data["actual_yield_rate"] is None

    def test_reintroduce_from_ramping_rejected(self, api):
        """PRD §3.2: "A line at `AT_CAPACITY` can be sent back to `RAMPING` when
        a new module series is introduced on it."
        PRD §2.5: "A request whose target resource is not in a state from which
        the requested transition is defined is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/line_capacity_to_ramping_reintroduce_cycle
        """
        bundle = create_ramping_line()
        line = bundle["line"]
        series7 = create_module_series(series_code="S7")
        resp = api.reintroduce_line(line["id"], {"series_id": series7["id"]}, PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_line(line["id"])["status"] == "RAMPING"
