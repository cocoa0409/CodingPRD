"""Abandonment applications, interim trail use, and the mileage ledger (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    api_client,
    assert_mileage_conserved,
    create_abandonment_payload,
    decide_abandonment_payload,
    file_abandonment,
    get_abandonment_data,
    get_carrier_data,
    grant_abandonment,
    make_carrier_operator_headers,
    register_carrier,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

BOARD = TEST_USERS["board_adjudicator_headers"]


class TestTrailUseWindowBoundary:
    def test_trail_use_window_boundary_precision(self):
        """PRD §3.7: "conversion requires the `TRAIL_PENDING` state
        (`ERR_ABANDONMENT_NOT_TRAIL_PENDING`, HTTP 409) and a logical clock
        reading no later than `nitu_expires_at` — a conversion attempted after
        the deadline is rejected with `ERR_TRAIL_USE_NOTICE_EXPIRED`
        (HTTP 409), while a conversion at exactly the deadline still
        succeeds."
        PRD §3.7: "From `TRAIL_PENDING`, consummation carries a temporal
        guard: the logical clock must be **strictly later** than
        `nitu_expires_at`, and a consummation attempted at or before the
        deadline — at equality the window is still open — is rejected with
        `ERR_TRAIL_USE_WINDOW_OPEN` (HTTP 409)."

        Design: Corner/errors/trail_use_window_boundary_precision
        """
        carrier = register_carrier()
        ab1 = file_abandonment(
            carrier["id"], line_segment_ref="MP 0.0-MP 50.0", segment_miles=50)
        ab2 = file_abandonment(
            carrier["id"], line_segment_ref="MP 100.0-MP 220.0",
            segment_miles=120)
        grant_abandonment(ab1["id"])
        grant_abandonment(ab2["id"])
        # NITU issued at the 2026-09-01T00:00:00Z clock default; +180 days.
        nitu1 = validate_success(
            api_client.issue_trail_use_notice(ab1["id"], {}, BOARD))
        nitu2 = validate_success(
            api_client.issue_trail_use_notice(ab2["id"], {}, BOARD))
        assert nitu1["status"] == "TRAIL_PENDING"
        assert nitu1["nitu_expires_at"] == "2027-02-28T00:00:00Z"
        assert nitu2["nitu_expires_at"] == "2027-02-28T00:00:00Z"

        # At exactly the deadline: convert succeeds (<=), consummate fails.
        set_clock("2027-02-28T00:00:00Z")
        converted = validate_success(
            api_client.convert_to_trail_use(ab1["id"], {}, BOARD))
        assert converted["status"] == "TRAIL_CONVERTED"
        resp = api_client.consummate_abandonment(ab2["id"], {}, BOARD)
        validate_error(resp, ApiErrorId.ERR_TRAIL_USE_WINDOW_OPEN)

        # After the deadline: convert fails, consummate succeeds.
        set_clock("2027-03-01T00:00:00Z")
        resp2 = api_client.convert_to_trail_use(ab2["id"], {}, BOARD)
        validate_error(resp2, ApiErrorId.ERR_TRAIL_USE_NOTICE_EXPIRED)
        consummated = validate_success(
            api_client.consummate_abandonment(ab2["id"], {}, BOARD))
        assert consummated["status"] == "CONSUMMATED"

        carrier_after = get_carrier_data(carrier["id"])
        assert carrier_after["active_route_miles"] == 830
        assert carrier_after["trail_use_route_miles"] == 50
        assert carrier_after["abandoned_route_miles"] == 120
        assert_mileage_conserved(carrier_after)


class TestMileageLedger:
    def test_carrier_mileage_reconciles_across_convert_and_consummate(self):
        """PRD §2.9: "`active_route_miles` equals the carrier's
        `base_route_miles` minus `abandoned_route_miles` minus
        `trail_use_route_miles`."
        PRD §3.7: "Conversion moves the application to `TRAIL_CONVERTED`, a
        terminal state, and moves the mileage: the carrier's
        `active_route_miles` decreases by `segment_miles` and its
        `trail_use_route_miles` increases by `segment_miles`."
        PRD §3.7: "the carrier's `active_route_miles` decreases by
        `segment_miles` and its `abandoned_route_miles` increases by
        `segment_miles`." (consummation)

        Design: Corner/cross_cutting_layers/carrier_mileage_reconciles_across_convert_and_consummate
        """
        carrier = register_carrier()
        ab1 = file_abandonment(
            carrier["id"], line_segment_ref="MP 100.0-MP 220.0",
            segment_miles=120)
        ab2 = file_abandonment(
            carrier["id"], line_segment_ref="MP 0.0-MP 50.0", segment_miles=50)
        grant_abandonment(ab1["id"])
        grant_abandonment(ab2["id"])
        validate_success(api_client.issue_trail_use_notice(ab2["id"], {}, BOARD))

        consummated = validate_success(
            api_client.consummate_abandonment(ab1["id"], {}, BOARD))
        assert consummated["status"] == "CONSUMMATED"
        converted = validate_success(
            api_client.convert_to_trail_use(ab2["id"], {}, BOARD))
        assert converted["status"] == "TRAIL_CONVERTED"

        carrier_after = get_carrier_data(carrier["id"])
        assert carrier_after["active_route_miles"] == 830
        assert carrier_after["abandoned_route_miles"] == 120
        assert carrier_after["trail_use_route_miles"] == 50
        assert_mileage_conserved(carrier_after)

    def test_consummate_after_trail_converted_rejected(self):
        """PRD §3.7: "an application in any state other than `GRANTED` or
        `TRAIL_PENDING` is rejected with `ERR_ABANDONMENT_NOT_GRANTED`
        (HTTP 409)" — consummation's state gate.

        Design: Corner/state_machines/consummate_after_trail_converted_rejected
        """
        carrier = register_carrier()
        ab = file_abandonment(carrier["id"])
        grant_abandonment(ab["id"])
        validate_success(api_client.issue_trail_use_notice(ab["id"], {}, BOARD))
        validate_success(api_client.convert_to_trail_use(ab["id"], {}, BOARD))

        resp = api_client.consummate_abandonment(ab["id"], {}, BOARD)
        validate_error(resp, ApiErrorId.ERR_ABANDONMENT_NOT_GRANTED)
        carrier_after = get_carrier_data(carrier["id"])
        # Mileage moved exactly once — no double move.
        assert carrier_after["active_route_miles"] == 980
        assert carrier_after["trail_use_route_miles"] == 20
        assert carrier_after["abandoned_route_miles"] == 0


class TestAbandonmentGuards:
    def test_duplicate_active_abandonment_same_segment_rejected(self):
        """PRD §3.7: "A line may carry at most one live application: a filing
        whose `line_segment_ref` already appears on an application in
        `UNDER_REVIEW`, `GRANTED`, or `TRAIL_PENDING` is rejected with
        `ERR_DUPLICATE_ACTIVE_ABANDONMENT` (HTTP 409)."

        Design: Corner/validations/duplicate_active_abandonment_same_segment_rejected
        """
        carrier = register_carrier()
        operator = make_carrier_operator_headers(carrier["id"])
        ab1 = file_abandonment(carrier["id"])
        assert ab1["status"] == "UNDER_REVIEW"

        resp = api_client.create_abandonment_application(
            create_abandonment_payload(carrier_id=carrier["id"]), operator)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_ABANDONMENT)

        denied = validate_success(api_client.decide_abandonment(
            ab1["id"], decide_abandonment_payload("DENIED", "NOT_SERVED"), BOARD))
        assert denied["status"] == "DENIED"
        ab2 = file_abandonment(carrier["id"])
        assert ab2["status"] == "UNDER_REVIEW"

    def test_abandonment_decide_not_found_returns_404(self):
        """PRD §2.6: "a missing abandonment application
        `ERR_ABANDONMENT_APPLICATION_NOT_FOUND`" (HTTP 404, path existence
        check)."

        Design: Corner/entities/abandonment_decide_not_found_returns_404
        """
        resp = api_client.decide_abandonment(
            NON_EXISTENT_ID, decide_abandonment_payload("GRANTED", "SERVED"),
            BOARD)
        validate_error(resp, ApiErrorId.ERR_ABANDONMENT_APPLICATION_NOT_FOUND)
