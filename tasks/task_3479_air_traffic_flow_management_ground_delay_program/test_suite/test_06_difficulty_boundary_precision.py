"""Difficulty queue: boundary precision.

Exact integer boundaries: the extension counter admits count 1 and rejects
count 2; the GA quota admits the first accommodation and waitlists the second.
"""

from test_helpers import (
    FLOW_MANAGER_HEADERS,
    GA_DESIGNATOR_ID_CHARS,
    GA_DESIGNATOR_PREFIX,
    ApiErrorId,
    adjudicate_ga_request,
    assert_instant,
    at,
    constraint_event_extend_payload,
    create_airport,
    create_ga_operator,
    create_ga_request,
    extend_event,
    get_flight,
    list_facility_events,
    report_constraint_event,
    set_clock,
    setup_active_gdp,
    validate_error,
)


class TestConstraintEventExtensionBoundary:
    def test_extension_count_boundary_at_cap(self, api):
        """PRD §3.2: "An event's window can be extended while it is `REPORTED`
        or `CONFIRMED`; extending from any other state fails with
        `ERR_INVALID_STATE`. The extension supplies a new `window_end` strictly
        later than the current one (otherwise `ERR_INVALID_WINDOW`) and may
        optionally update `severity`. The same-type overlap rule is re-checked
        against the widened window (`ERR_CONSTRAINT_EVENT_OVERLAP`), and the
        hard cap `CONSTRAINT_EVENT_MAX_EXTENSIONS` — 2 extensions per event —
        is enforced through `extension_count`: a third attempt is rejected with
        `ERR_EXTENSION_LIMIT_EXCEEDED` (HTTP 422). Each accepted extension
        increments `extension_count` by 1."

        Design: Difficulty/boundary_precision_check/constraint_event_extension_boundary
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        event = report_constraint_event(
            api, facility["id"], event_type="WEATHER", severity=2,
            window_start=at("13:00"), window_end=at("15:00"),
        )

        first = extend_event(api, event["id"], at("15:30"))
        assert first["extension_count"] == 1
        second = extend_event(api, event["id"], at("16:00"))
        assert second["extension_count"] == 2, "count 0 and 1 pass the < 2 rule"

        resp = api.extend_constraint_event(
            event["id"], constraint_event_extend_payload(at("16:30")),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_EXCEEDED)

        events, _ = list_facility_events(api, facility["id"])
        current = {e["id"]: e for e in events}[event["id"]]
        assert current["status"] == "REPORTED", "the rejected extension changed nothing"
        assert current["extension_count"] == 2


class TestGaReservedPoolBoundary:
    def test_reserved_pool_admits_one_then_waitlists(self, api):
        """PRD §3.4: "A reserved tail is carved out for general aviation: the
        count of reserved slots is `GA_QUOTA_PCT` (10) percent of the slot
        count rounded down, but never fewer than `GA_MIN_RESERVED` (1), and the
        last reserved-count slots carry `is_ga_reserved` true and are skipped
        by the initial carrier allocation."
        PRD §3.7: "Accommodation tests a quota predicate rather than erroring
        on scarcity: the number of reserved slots currently `ASSIGNED` to
        GA-created flights must be below the program's reserved-slot count — a
        cancelled GA flight frees its quota headroom — and an `OPEN` reserved
        slot must exist whose `slot_time` lies within the requested window.
        When either leg fails, the request moves to `WAITLISTED` instead of
        erroring; when both hold, accommodation grants the earliest in-window
        reserved `OPEN` slot and runs the full cascade: a new Flight is created
        for the requesting operator with a server-minted `designator` of the
        prefix `GA-` followed by the first eight characters of the request's
        `id`, `scheduled_arrival` equal to `requested_window_start`, and
        `arrival_facility_id` equal to the program's facility;"

        Design: Difficulty/boundary_precision_check/ga_reserved_pool_boundary
        """
        # rate 6 over two hours -> 12 slots; reserved = max(1, floor(12*10%)) = 1
        world = setup_active_gdp(
            api, carrier_names=("Alpha Air",), flight_specs=((0, "AAL1", "13:05"),)
        )
        tmi_id = world["tmi"]["id"]
        ga_operator, _ = create_ga_operator(api)

        first = create_ga_request(
            api, ga_operator, tmi_id,
            requested_window_start=at("14:30"), requested_window_end=at("15:00"),
            priority_class="STANDARD",
        )
        second = create_ga_request(
            api, ga_operator, tmi_id,
            requested_window_start=at("14:30"), requested_window_end=at("15:00"),
            priority_class="HIGH_PRIORITY",
        )

        granted = adjudicate_ga_request(api, first["id"], "ACCOMMODATE")
        assert granted["status"] == "ACCOMMODATED", "count 0 < 1 admits the first"
        assert_instant(granted["accommodated_slot_time"], at("14:50"), "granted slot")
        waitlisted = adjudicate_ga_request(api, second["id"], "ACCOMMODATE")
        assert waitlisted["status"] == "WAITLISTED", (
            "accommodated_count 1 == reserved_slots 1: the headroom predicate fails"
        )

        ga_flight = get_flight(api, granted["accommodated_flight_id"])
        assert ga_flight["designator"] == (
            GA_DESIGNATOR_PREFIX + first["id"][:GA_DESIGNATOR_ID_CHARS]
        )
        assert_instant(ga_flight["scheduled_arrival"], at("14:30"), "GA flight schedule")
        assert ga_flight["control_status"] == "SLOTTED"
        assert ga_flight["arrival_facility_id"] == world["facility"]["id"]
