"""Transport cooler checkout windows and the sixty-minute redispatch buffer."""
from test_helpers import (
    ApiErrorId,
    assert_seconds_between,
    book_checkout,
    create_cooler_checkout_payload,
    get_cooler,
    get_success_data,
    make_cooler,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TECH_A,
    api_client,
)


class TestCheckoutBufferSemantics:
    def _setup_booked_cooler(self, api):
        set_clock("2026-08-10T09:00:00Z")
        cooler = make_cooler("C-1")
        first = book_checkout(cooler["id"], "2026-08-10T10:00:00Z",
                              "2026-08-10T12:00:00Z")
        return cooler, first

    def test_checkout_starting_at_exact_end_conflicts(self, api):
        """PRD §3.9: "a conflict exists when the new `planned_start` falls strictly
        before the existing checkout's effective end — that is, its
        `actual_returned_at` if it has returned, otherwise its `planned_end`, plus
        sixty minutes — and the existing checkout's `planned_start` falls strictly
        before the new `planned_end` plus sixty minutes; touching boundaries, where
        an endpoint coincides exactly, do not conflict. A conflicting booking meets
        `ERR_COOLER_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/cooler_checkout_buffer_gap_semantics
        """
        cooler, _first = self._setup_booked_cooler(api)
        resp = api.create_cooler_checkout(
            create_cooler_checkout_payload(cooler["id"], "2026-08-10T12:00:00Z",
                                           "2026-08-10T13:00:00Z"), TECH_A)
        # 12:00 < 12:00 + 60min buffer — the buffered intervals collide.
        validate_error(resp, ApiErrorId.ERR_COOLER_WINDOW_CONFLICT)

    def test_checkout_starting_at_end_plus_buffer_accepted(self, api):
        """PRD §3.9: "touching boundaries, where an endpoint coincides exactly, do
        not conflict."
        PRD §3.9: "Cooler status never gates booking — the interval-conflict rule
        alone decides — so several non-conflicting future windows may coexist on
        one cooler."

        Design: Difficulty/resource_temporal_overlap/cooler_checkout_buffer_gap_semantics
        """
        cooler, _first = self._setup_booked_cooler(api)
        second = validate_success(api.create_cooler_checkout(
            create_cooler_checkout_payload(cooler["id"], "2026-08-10T13:00:00Z",
                                           "2026-08-10T15:00:00Z"), TECH_A), 201)
        assert second["status"] == "OPEN", (
            "13:00 == planned_end + 60min exactly — strict < means equality passes"
        )
        _data, meta = validate_paginated(api.list_cooler_checkouts(
            TECH_A, params={"cooler_id": cooler["id"]}))
        assert meta["total_count"] == 2


class TestCheckoutWindowValidation:
    def test_cooler_checkout_window_invalid_returns_400(self, api):
        """PRD §3.9: "The window must be well-formed — `planned_end` strictly after
        `planned_start` and the duration no more than twelve hours — or the booking
        is rejected with `ERR_CHECKOUT_WINDOW_INVALID` (HTTP 400)."

        Design: Corner/entities/cooler_checkout_window_invalid_returns_400
        """
        cooler = make_cooler("C-9")
        resp = api.create_cooler_checkout(
            create_cooler_checkout_payload(cooler["id"], "2026-08-10T10:00:00Z",
                                           "2026-08-10T10:00:00Z"), TECH_A)
        validate_error(resp, ApiErrorId.ERR_CHECKOUT_WINDOW_INVALID)

        resp = api.create_cooler_checkout(
            create_cooler_checkout_payload(cooler["id"], "2026-08-10T10:00:00Z",
                                           "2026-08-10T22:00:01Z"), TECH_A)
        # 12h00m01s exceeds the twelve-hour cap.
        validate_error(resp, ApiErrorId.ERR_CHECKOUT_WINDOW_INVALID)


class TestCheckoutReturn:
    def test_error_checkout_not_returnable(self, api):
        """PRD §3.9: "Returning a checkout requires `OPEN`
        (`ERR_CHECKOUT_NOT_RETURNABLE`), stamps `actual_returned_at`, settles it in
        terminal `RETURNED`, and moves the cooler from `CHECKED_OUT` to
        `RESTOCKING` with `restock_until` set sixty minutes after the return — the
        redispatch buffer."
        PRD §3.9: "when a created checkout's window already covers the current time
        — `planned_start` at or before now, now at or before `planned_end` — the
        cooler moves from `AVAILABLE` to `CHECKED_OUT` immediately"

        Design: Corner/errors/error_checkout_not_returnable
        """
        set_clock("2026-08-10T09:00:00Z")
        cooler = make_cooler("C-1")
        checkout = book_checkout(cooler["id"], "2026-08-10T08:00:00Z",
                                 "2026-08-10T12:00:00Z")
        assert get_cooler(cooler["id"])["status"] == "CHECKED_OUT"

        returned = validate_success(api.return_cooler_checkout(checkout["id"],
                                                               TECH_A))
        assert returned["status"] == "RETURNED"
        cooler = get_cooler(cooler["id"])
        assert cooler["status"] == "RESTOCKING"
        assert_seconds_between(returned["actual_returned_at"],
                               cooler["restock_until"], 3600,
                               "restock buffer")

        resp = api.return_cooler_checkout(checkout["id"], TECH_A)
        validate_error(resp, ApiErrorId.ERR_CHECKOUT_NOT_RETURNABLE)
