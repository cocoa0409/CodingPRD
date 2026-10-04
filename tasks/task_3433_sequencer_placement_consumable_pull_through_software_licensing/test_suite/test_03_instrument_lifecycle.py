"""Instrument lifecycle: forward events, service-window cycle, terminal lockdown.

Covers the Instrument event machine of PRD section 3.2: the linear
ORDERED -> SHIPPED -> INSTALLED -> OPERATIONAL path, the cyclic
OPERATIONAL <-> DOWN_FOR_SERVICE service loop with its window bookkeeping,
and the terminal DECOMMISSIONED lockdown.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_account,
    create_instrument,
    create_model,
    create_operational_instrument,
    instrument_event_payload,
    make_account_manager_headers,
    make_field_service_engineer_headers,
    validate_error,
    validate_success,
)
from test_helpers import api_client


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime (format-free)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _event(instrument_id: str, action: str, role_headers: dict):
    return api_client.post_instrument_event(
        instrument_id, instrument_event_payload(action), role_headers
    )


class TestInstrumentEventGates:
    def test_install_before_ship_rejected(self, api):
        """INSTALL is defined only from SHIPPED; firing it on an ORDERED
        instrument is rejected and leaves the instrument ORDERED.

        PRD §3.2: "Installation moves `SHIPPED` to `INSTALLED`, and if `installed_at` was omitted at registration it is stamped with the current logical clock at that moment."
        PRD §3.2: "Each event increments the instrument's `version` by one, and any attempt to fire an event from the wrong state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/instrument_install_before_ship_rejected
        """
        account = create_account()
        model = create_model()
        instrument = create_instrument(
            account_id=account["id"], model_id=model["id"]
        )
        assert instrument["install_state"] == "ORDERED"

        resp = _event(
            instrument["id"], "INSTALL", make_field_service_engineer_headers("fse-1")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(
            api.get_instrument(instrument["id"], make_account_manager_headers("am-1"))
        )
        assert after["install_state"] == "ORDERED", (
            f"rejected INSTALL must not move the instrument, got {after['install_state']}"
        )

    def test_decommissioned_terminal_lockdown(self, api):
        """DECOMMISSIONED is terminal: a later SERVICE_OPEN is rejected and the
        instrument remains DECOMMISSIONED.

        PRD §3.2: "Decommissioning is an `AccountManager` action and requires the instrument to be `OPERATIONAL` or `DOWN_FOR_SERVICE`; from any other state the request is `ERR_INVALID_STATE`."
        PRD §3.2: "Each event increments the instrument's `version` by one, and any attempt to fire an event from the wrong state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/instrument_decommissioned_terminal_lockdown
        """
        instrument = create_operational_instrument()
        resp = _event(
            instrument["id"], "DECOMMISSION", make_account_manager_headers("am-1")
        )
        decommissioned = validate_success(resp)
        assert decommissioned["install_state"] == "DECOMMISSIONED"

        resp = _event(
            instrument["id"],
            "SERVICE_OPEN",
            make_field_service_engineer_headers("fse-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(
            api.get_instrument(instrument["id"], make_account_manager_headers("am-1"))
        )
        assert after["install_state"] == "DECOMMISSIONED"


class TestInstrumentServiceCycle:
    def _walk_two_service_loops(self, instrument_id: str) -> dict:
        """Drive OPERATIONAL -> DOWN_FOR_SERVICE -> OPERATIONAL twice with the
        logical clock advanced around each window; return the final instrument."""
        fse = make_field_service_engineer_headers("fse-1")
        states = []
        advance_clock("2026-09-01T10:00:00Z")
        states.append(validate_success(_event(instrument_id, "SERVICE_OPEN", fse)))
        advance_clock("2026-09-01T10:30:00Z")
        states.append(validate_success(_event(instrument_id, "SERVICE_CLOSE", fse)))
        advance_clock("2026-09-01T11:00:00Z")
        states.append(validate_success(_event(instrument_id, "SERVICE_OPEN", fse)))
        advance_clock("2026-09-01T11:15:00Z")
        states.append(validate_success(_event(instrument_id, "SERVICE_CLOSE", fse)))
        return states

    def test_service_cycle_loops_twice(self, api):
        """The service cycle is a loop, not a dead end: two full
        OPERATIONAL -> DOWN_FOR_SERVICE -> OPERATIONAL traversals succeed.

        PRD §3.2: "Opening a service window moves `OPERATIONAL` to `DOWN_FOR_SERVICE` and appends a `service_windows` entry whose `opened_at` is the current logical clock and whose `closed_at` is null."
        PRD §3.2: "Closing service moves `DOWN_FOR_SERVICE` back to `OPERATIONAL`, requires that an open window actually exist, and stamps `closed_at` with the current clock on the latest open window."

        Design: Difficulty/non_linear_state_machine/instrument_service_cycle
        """
        instrument = create_operational_instrument()
        states = self._walk_two_service_loops(instrument["id"])
        observed = [s["install_state"] for s in states]
        assert observed == [
            "DOWN_FOR_SERVICE",
            "OPERATIONAL",
            "DOWN_FOR_SERVICE",
            "OPERATIONAL",
        ], f"two full service loops must cycle, got {observed}"

    def test_service_cycle_appends_one_closed_window_per_loop(self, api):
        """Each service loop appends one window stamped from the logical clock;
        two loops leave exactly two windows, both closed, spanning
        10:00->10:30 and 11:00->11:15.

        PRD §3.2: "Opening a service window moves `OPERATIONAL` to `DOWN_FOR_SERVICE` and appends a `service_windows` entry whose `opened_at` is the current logical clock and whose `closed_at` is null."
        PRD §3.2: "Closing service moves `DOWN_FOR_SERVICE` back to `OPERATIONAL`, requires that an open window actually exist, and stamps `closed_at` with the current clock on the latest open window."

        Design: Difficulty/non_linear_state_machine/instrument_service_cycle
        """
        instrument = create_operational_instrument()
        final = self._walk_two_service_loops(instrument["id"])[-1]
        windows = final["service_windows"]
        assert len(windows) == 2, (
            f"two loops must produce exactly two windows, got {len(windows)}"
        )
        first, second = windows[0], windows[1]
        assert _parse_iso(first["opened_at"]) == datetime(
            2026, 9, 1, 10, 0, tzinfo=timezone.utc
        )
        assert _parse_iso(first["closed_at"]) == datetime(
            2026, 9, 1, 10, 30, tzinfo=timezone.utc
        )
        assert _parse_iso(second["opened_at"]) == datetime(
            2026, 9, 1, 11, 0, tzinfo=timezone.utc
        )
        assert _parse_iso(second["closed_at"]) == datetime(
            2026, 9, 1, 11, 15, tzinfo=timezone.utc
        )
