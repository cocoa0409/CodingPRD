"""The ride lifecycle, its invalid transitions and its cyclic re-dispatch.

A ride is a cyclic machine, not a linear one: a matched ride whose vehicle
accumulates three dispatch attempts is unwound back to REQUESTED rather than
being left holding a car that has failed it three times.
"""

from test_helpers import constants as c
from test_helpers.api_errors import ERR_INVALID_STATE
from test_helpers.assertions import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_ride,
    match_ride,
    read_ride,
    read_vehicle,
    ready_ride_stack,
    set_clock,
)
from test_helpers.test_users import ASSIST, FLEET
from test_helpers import factories as f


class TestRideInvalidTransitions:
    """Ride transitions are only legal from the status that permits them."""

    def test_complete_from_requested_is_refused(self, api):
        """COMPLETED is reachable only from PICKED_UP.

        PRD 3.4: "Cancelling a ride outright is permitted from `REQUESTED` or
        from `MATCHED`; any other status — including `PICKED_UP`, which has
        already collected a rider — is refused with `ERR_INVALID_STATE`
        (HTTP 409)."
        PRD 3.7: "State-transition validity is evaluated after all of these, and
        a transition attempted from a status that does not permit it is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/if_match_ride_complete_from_requested_invalid_state
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-inv-1")
        assert stack["ride"]["status"] == c.RIDE_REQUESTED

        resp = api.complete_ride(stack["territory"]["id"], stack["ride"]["id"], headers=FLEET)
        validate_error(resp, ERR_INVALID_STATE, 409)
        assert read_ride(api, stack["territory"]["id"], stack["ride"]["id"])["status"] == c.RIDE_REQUESTED

    def test_pickup_from_requested_is_refused(self, api):
        """Pickup requires MATCHED even with a well-formed body.

        PRD 3.4: "Pickup confirmation is the next step, and it carries two
        fields. The operator supplies the chosen `dropoff_location_id` and an
        `expected_vehicle_version`. The ride must currently be `MATCHED`."

        Design: Corner/state_machines/if_match_ride_pickup_from_requested_invalid_state
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-inv-2")
        resp = api.pickup_ride(
            stack["territory"]["id"],
            stack["ride"]["id"],
            {
                "dropoff_location_id": stack["pickup_location"]["id"],
                "expected_vehicle_version": stack["vehicle"]["version"],
            },
            headers=FLEET,
        )
        validate_error(resp, ERR_INVALID_STATE, 409)

        after = read_ride(api, stack["territory"]["id"], stack["ride"]["id"])
        assert after["status"] == c.RIDE_REQUESTED
        assert after["dropoff_location_id"] is None

    def test_cancel_from_picked_up_is_refused(self, api):
        """A ride that has collected its rider can no longer be cancelled.

        PRD 3.4: "Cancelling a ride outright is permitted from `REQUESTED` or
        from `MATCHED`; any other status — including `PICKED_UP`, which has
        already collected a rider — is refused with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/if_match_ride_complete_from_requested_invalid_state
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-inv-3")
        validate_success(
            match_ride(api, stack["territory"]["id"], stack["ride"]["id"],
                       stack["pickup_location"]["id"], stack["vehicle"]["version"])
        )
        matched = read_vehicle(api, stack["vehicle"]["id"])
        validate_success(
            api.pickup_ride(
                stack["territory"]["id"],
                stack["ride"]["id"],
                {
                    "dropoff_location_id": stack["pickup_location"]["id"],
                    "expected_vehicle_version": matched["version"],
                },
                headers=FLEET,
            )
        )
        assert read_ride(api, stack["territory"]["id"], stack["ride"]["id"])["status"] == c.RIDE_PICKED_UP

        resp = api.cancel_ride(
            stack["territory"]["id"], stack["ride"]["id"], {"credit_cents": 0},
            headers=FLEET,
        )
        validate_error(resp, ERR_INVALID_STATE, 409)
        assert read_ride(api, stack["territory"]["id"], stack["ride"]["id"])["status"] == c.RIDE_PICKED_UP

    def test_no_show_requires_requested(self, api):
        """Marking a no-show works only from REQUESTED.

        PRD 3.4: "Marking a no-show is the narrower operation and works only
        from `REQUESTED`; it takes the ride to `CANCELLED_NO_SHOW` and recomputes
        the vehicle's readiness."

        Design: Corner/state_machines/if_match_ride_complete_from_requested_invalid_state
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-inv-4")
        validate_success(
            match_ride(api, stack["territory"]["id"], stack["ride"]["id"],
                       stack["pickup_location"]["id"], stack["vehicle"]["version"])
        )
        resp = api.cancel_ride_no_show(
            stack["territory"]["id"], stack["ride"]["id"], headers=FLEET
        )
        validate_error(resp, ERR_INVALID_STATE, 409)


class TestCyclicRedispatch:
    """The third dispatch attempt unwinds a matched ride."""

    def test_third_dispatch_attempt_returns_the_ride_to_requested(self, api):
        """A matched ride is un-matched when dispatch_attempts reaches three.

        PRD 3.5: "When the attempt being recorded is the third attempt against a
        ride that is still `MATCHED` — that is, when `dispatch_attempts` reaches
        3 as a result of this recording — the system unwinds the pairing rather
        than leaving it in place: the matched vehicle's `credit_cents` is reduced
        by the `credit_cents` amount carried on the escalation request, bounded
        below at zero, the vehicle's readiness verdict is recomputed back out of
        `DISPATCHED`, the ride's `vehicle_id` is cleared to null, and the ride
        returns from `MATCHED` to `REQUESTED` so that it can be matched afresh."
        PRD 3.5: "A ride is therefore never stuck holding a vehicle that has
        failed it three times."

        Design: Difficulty/non_linear_state_machine/if_match_ride_three_attempt_redispatch_cycle
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cycle-1")
        validate_success(
            match_ride(api, stack["territory"]["id"], stack["ride"]["id"],
                       stack["pickup_location"]["id"], stack["vehicle"]["version"])
        )
        assert read_ride(api, stack["territory"]["id"], stack["ride"]["id"])["status"] == c.RIDE_MATCHED

        for _ in range(3):
            get_success_data(
                api.create_assistance_session(
                    stack["territory"]["id"], stack["ride"]["id"],
                    f.create_assistance_session_payload(reason="STUCK"), headers=ASSIST,
                ),
                expected_status=201,
            )

        after = read_ride(api, stack["territory"]["id"], stack["ride"]["id"])
        assert after["status"] == c.RIDE_REQUESTED, (
            "the ride re-enters the state it already occupied"
        )
        assert after["vehicle_id"] is None
        assert after["dispatch_attempts"] == 3

    def test_redispatch_leaves_the_vehicle_in_service(self, api):
        """The unwound ride's former vehicle is still IN_SERVICE.

        PRD 3.5: "the vehicle's readiness verdict is recomputed back out of
        `DISPATCHED`, the ride's `vehicle_id` is cleared to null"
        PRD 2.5: "otherwise a vehicle whose `status` is `IN_SERVICE` is
        `DISPATCHED`"

        Design: Difficulty/non_linear_state_machine/if_match_ride_three_attempt_redispatch_cycle
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cycle-2")
        validate_success(
            match_ride(api, stack["territory"]["id"], stack["ride"]["id"],
                       stack["pickup_location"]["id"], stack["vehicle"]["version"])
        )
        for _ in range(3):
            get_success_data(
                api.create_assistance_session(
                    stack["territory"]["id"], stack["ride"]["id"],
                    f.create_assistance_session_payload(reason="STUCK"), headers=ASSIST,
                ),
                expected_status=201,
            )

        vehicle = read_vehicle(api, stack["vehicle"]["id"])
        assert vehicle["status"] == c.VEHICLE_IN_SERVICE
        assert vehicle["service_status"] == c.SERVICE_DISPATCHED

    def test_two_attempts_leave_the_ride_matched(self, api):
        """Below the third attempt the pairing stands.

        PRD 3.5: "Escalation records a dispatch attempt against the ride: the
        ride's `dispatch_attempts` is incremented by one. This counter is what
        drives cyclic re-dispatch."

        Design: Difficulty/non_linear_state_machine/if_match_ride_three_attempt_redispatch_cycle
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cycle-3")
        validate_success(
            match_ride(api, stack["territory"]["id"], stack["ride"]["id"],
                       stack["pickup_location"]["id"], stack["vehicle"]["version"])
        )
        for _ in range(2):
            get_success_data(
                api.create_assistance_session(
                    stack["territory"]["id"], stack["ride"]["id"],
                    f.create_assistance_session_payload(reason="STUCK"), headers=ASSIST,
                ),
                expected_status=201,
            )
        after = read_ride(api, stack["territory"]["id"], stack["ride"]["id"])
        assert after["status"] == c.RIDE_MATCHED
        assert after["vehicle_id"] == stack["vehicle"]["id"]
        assert after["dispatch_attempts"] == 2


class TestRideCancellationArithmetic:
    """Cancelling a matched ride debits the vehicle, bounded below at zero."""

    def test_cancel_before_match_has_no_financial_consequence(self, api):
        """Cancelling a REQUESTED ride leaves the vehicle balance untouched.

        PRD 3.4: "Cancelling a `REQUESTED` ride has no financial consequence."

        Design: Corner/cross_cutting_complexity_layers/if_match_ride_list_filters_pagination_consistency
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cancel-1")
        before = read_vehicle(api, stack["vehicle"]["id"])
        cancelled = get_success_data(
            api.cancel_ride(
                stack["territory"]["id"], stack["ride"]["id"], {"credit_cents": 0},
                headers=FLEET,
            )
        )
        assert cancelled["status"] == c.RIDE_CANCELLED
        assert read_vehicle(api, stack["vehicle"]["id"])["credit_cents"] == before["credit_cents"]

    def test_cancel_after_match_debits_bounded_at_zero(self, api):
        """A debit larger than the balance leaves the vehicle at zero.

        PRD 3.4: "Cancelling a `MATCHED` ride carries a `credit_cents` value:
        the matched vehicle's readiness verdict is recomputed back out of
        `DISPATCHED`, and its `credit_cents` is reduced by the supplied amount,
        bounded below at zero so the balance can never go negative."

        Design: Corner/cross_cutting_complexity_layers/if_match_ride_list_filters_pagination_consistency
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-cancel-2")
        validate_success(
            match_ride(api, stack["territory"]["id"], stack["ride"]["id"],
                       stack["pickup_location"]["id"], stack["vehicle"]["version"])
        )
        matched_vehicle = read_vehicle(api, stack["vehicle"]["id"])
        assert matched_vehicle["service_status"] == c.SERVICE_DISPATCHED

        cancelled = get_success_data(
            api.cancel_ride(
                stack["territory"]["id"], stack["ride"]["id"],
                {"credit_cents": matched_vehicle["credit_cents"] + 100_000},
                headers=FLEET,
            )
        )
        assert cancelled["status"] == c.RIDE_CANCELLED
        after = read_vehicle(api, stack["vehicle"]["id"])
        assert after["credit_cents"] == 0, (
            "a debit larger than the balance leaves the vehicle at zero rather than negative"
        )

    def test_no_show_moves_the_ride_to_the_no_show_terminal(self, api):
        """A no-show is the narrower operation and works only from REQUESTED.

        PRD 3.4: "Marking a no-show is the narrower operation and works only
        from `REQUESTED`; it takes the ride to `CANCELLED_NO_SHOW` and recomputes
        the vehicle's readiness. The four terminal ride statuses are
        `COMPLETED`, `CANCELLED_NO_SHOW`, `CANCELLED`, and `FAILED`."

        Design: Corner/state_machines/if_match_ride_complete_from_requested_invalid_state
        """
        set_clock(api)
        stack = ready_ride_stack(api, idempotency_key="idem-noshow-1")
        no_show = get_success_data(
            api.cancel_ride_no_show(stack["territory"]["id"], stack["ride"]["id"], headers=FLEET)
        )
        assert no_show["status"] == c.RIDE_CANCELLED_NO_SHOW


class TestRideCreationIdempotency:
    """Ride creation is idempotent on the territory and key pair."""

    def test_replaying_the_key_returns_the_original_ride(self, api):
        """A retried submission hands back the original ride untouched.

        PRD 3.4: "Because idempotency is keyed on the pair of `territory_id` and
        `idempotency_key`, a retried submission must hand back the original ride
        untouched rather than opening a second one."
        PRD 2.11: "Ride request creation is idempotent on the pair of
        `territory_id` and `idempotency_key`; replaying a creation with the same
        pair must return the originally created ride and must not create a second
        row."

        Design: Corner/validations/if_match_ride_create_idempotency_key_replay
        """
        set_clock(api)
        territory = ready_ride_stack(api, idempotency_key="idem-replay")["territory"]
        original = create_ride(api, territory["id"], idempotency_key="idem-replay")

        replay = create_ride(api, territory["id"], idempotency_key="idem-replay")
        assert replay["id"] == original["id"], (
            "the replay must return the ride created by the first submission"
        )

        rows = get_success_data(api.list_territory_rides(territory["id"], headers=FLEET))
        assert len(rows) == 1

    def test_a_fresh_key_opens_a_second_ride(self, api):
        """The dedupe is scoped to the key pair, not to the territory alone.

        PRD 2.11: "Ride request creation is idempotent on the pair of
        `territory_id` and `idempotency_key`."

        Design: Corner/validations/if_match_ride_create_idempotency_key_replay
        """
        set_clock(api)
        territory = ready_ride_stack(api, idempotency_key="idem-replay-2")["territory"]
        original = create_ride(api, territory["id"], idempotency_key="idem-replay-2")
        fresh = create_ride(api, territory["id"], rider_name="Rider Two",
                            idempotency_key="idem-fresh")

        assert fresh["id"] != original["id"]
        rows = get_success_data(api.list_territory_rides(territory["id"], headers=FLEET))
        assert len(rows) == 2


class TestRideListingFilters:
    """The ride list narrows by status before pagination is applied."""

    def test_status_filter_excludes_the_cancelled_row(self, api):
        """Filtering by REQUESTED never surfaces the CANCELLED ride.

        PRD 2.3: "Filter parameters documented per endpoint — for example
        `status`, `route_class`, `window_code`, or `territory_id` — narrow the
        result set before pagination is applied."

        Design: Corner/cross_cutting_complexity_layers/if_match_ride_list_filters_pagination_consistency
        """
        set_clock(api)
        territory = ready_ride_stack(api, idempotency_key="idem-list-1")["territory"]
        create_ride(api, territory["id"], rider_name="Rider Two", idempotency_key="idem-list-2")
        third = create_ride(api, territory["id"], rider_name="Rider Three", idempotency_key="idem-list-3")
        get_success_data(
            api.cancel_ride(territory["id"], third["id"], {"credit_cents": 0}, headers=FLEET)
        )

        page_one = get_success_data(
            api.list_territory_rides(
                territory["id"], headers=FLEET,
                params={"status": c.RIDE_REQUESTED, "limit": 1, "offset": 0},
            )
        )
        assert len(page_one) == 1
        assert all(row["status"] == c.RIDE_REQUESTED for row in page_one)

        page_two = get_success_data(
            api.list_territory_rides(
                territory["id"], headers=FLEET,
                params={"status": c.RIDE_REQUESTED, "limit": 1, "offset": 1},
            )
        )
        assert len(page_two) == 1
        assert all(row["status"] != c.RIDE_CANCELLED for row in page_one + page_two)

    def test_status_filter_reports_the_filtered_total(self, api):
        """total_count reflects the narrowed set, not the full collection.

        PRD 2.3: "List responses are paginated through query parameters."

        Design: Corner/cross_cutting_complexity_layers/if_match_ride_list_filters_pagination_consistency
        """
        set_clock(api)
        territory = ready_ride_stack(api, idempotency_key="idem-list-4")["territory"]
        create_ride(api, territory["id"], rider_name="Rider Two", idempotency_key="idem-list-5")
        third = create_ride(api, territory["id"], rider_name="Rider Three", idempotency_key="idem-list-6")
        get_success_data(
            api.cancel_ride(territory["id"], third["id"], {"credit_cents": 0}, headers=FLEET)
        )

        resp = api.list_territory_rides(
            territory["id"], headers=FLEET,
            params={"status": c.RIDE_REQUESTED, "limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert all(row["status"] == c.RIDE_REQUESTED for row in data)