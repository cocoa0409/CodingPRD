"""Corner — cross-cutting layers: logical-clock lazy re-evaluation.

Design: Corner/cross_cutting_complexity_layers
"""
from test_helpers import (
    TEST_USERS, create_offer_payload, get_success_data, setup_film,
    setup_film_with_offer, validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ACQ = TEST_USERS["acq_exec_headers"]


class TestClockLazyTransitions:
    def test_clock_set_re_evaluates_lazy_transitions(self, api):
        """PRD §2.6: "Advancing the clock is an admin-only operation that
        takes a single `current_utc` instant and re-evaluates every lazily
        clock-dependent transition — offers whose `expiry_at` has been passed
        flip to `EXPIRED`".
        PRD §3.3: "if, after the transition, no `OPEN` offer remains on the
        film and no `EXECUTED` or `IN_RELEASE` deal exists, the film's
        `acquisition_status` collapses `UNDER_NEGOTIATION → SHOPPING`".

        Design: Corner/cross_cutting_complexity_layers/clock_set_re_evaluates_lazy_transitions
        """
        film, offer = setup_film_with_offer(
            offer_overrides={"expiry_at": "2026-10-01T00:00:00Z"},
        )
        film_id = film["id"]

        film_mid = get_success_data(api.get_film(film_id, ACQ))
        assert film_mid["acquisition_status"] == "UNDER_NEGOTIATION"

        validate_success(api.set_clock("2026-10-02T00:00:00Z", ADMIN))

        offer_after = get_success_data(api.get_offer(film_id, offer["id"], ACQ))
        assert offer_after["status"] == "EXPIRED"

        film_after = get_success_data(api.get_film(film_id, ACQ))
        assert film_after["acquisition_status"] == "SHOPPING"
