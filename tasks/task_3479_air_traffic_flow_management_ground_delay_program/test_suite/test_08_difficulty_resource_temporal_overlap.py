"""Difficulty queue: resource temporal overlap.

Two interval regimes: half-open point-overlap for same-type constraint events
(adjacency allowed), and aggregate-capacity coexistence for initiatives (a
second GDP is hard-rejected while an AFP is only rate-gated).
"""

from test_helpers import (
    COMMAND_CENTER_HEADERS,
    FLOW_MANAGER_HEADERS,
    ApiErrorId,
    activate_tmi,
    at,
    constraint_event_payload,
    create_airport,
    create_published_forecast,
    gdp_payload,
    propose_gdp,
    propose_tmi,
    publish_tmi,
    report_constraint_event,
    set_clock,
    validate_error,
    validate_success,
)


class TestConstraintEventHalfOpenAdjacency:
    def test_adjacency_allowed_overlap_rejected_other_type_allowed(self, api):
        """PRD §2.9: "Every window in the system — constraint-event degradation
        windows, forecast windows, program windows, GA request windows — is
        half-open: the start instant is included and the end instant is
        excluded. Two windows overlap when they share at least one instant
        under this convention; two windows that merely touch, where one
        window's start equals the other's end, are adjacent and do not
        overlap."
        PRD §3.2: "it must not overlap any other non-`CLEARED` event of the
        same `event_type` on the same facility, where overlap is judged on
        half-open windows and mere adjacency is allowed; a conflicting report
        is rejected with `ERR_CONSTRAINT_EVENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/constraint_event_half_open_adjacency
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        report_constraint_event(
            api, facility["id"], event_type="WEATHER", severity=2,
            window_start=at("13:00"), window_end=at("15:00"),
        )

        # start == existing end: adjacent, not overlapping
        resp = api.create_constraint_event(
            facility["id"],
            constraint_event_payload(
                event_type="WEATHER", severity=3,
                window_start=at("15:00"), window_end=at("17:00"),
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_success(resp, 201)

        # one minute earlier intersects [13:00, 15:00) -> rejected
        resp = api.create_constraint_event(
            facility["id"],
            constraint_event_payload(
                event_type="WEATHER", severity=1,
                window_start=at("14:59"), window_end=at("17:00"),
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_EVENT_OVERLAP)

        # the rule is scoped to the same event_type only
        resp = api.create_constraint_event(
            facility["id"],
            constraint_event_payload(
                event_type="STAFFING", severity=2,
                window_start=at("14:00"), window_end=at("16:00"),
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_success(resp, 201)


class TestTmiAggregateCapacityCoexistence:
    def test_afp_gdp_coexist_but_second_gdp_rejected(self, api):
        """PRD §2.6 item 14: "No other
        `GROUND_DELAY_PROGRAM` or `GROUND_STOP` TMI on the same facility with
        status in `PROPOSED`, `PUBLISHED`, `ACTIVE` or `REVISING` may overlap
        the candidate's half-open program window; `AIRSPACE_FLOW_PROGRAM` and
        `REROUTE` initiatives are exempt from this hard rule and interact
        through aggregate capacity instead. Failure yields `ERR_TMI_OVERLAP`
        (HTTP 409). Checked at proposal and re-checked at activation, since
        another program may have activated in between."
        PRD §3.4: "Otherwise the gate forecast's `predicted_acceptance_rate` is
        taken, capped from above by the facility's `base_acceptance_rate`; from
        that, the aggregate load of every `AIRSPACE_FLOW_PROGRAM` on the
        facility in `PUBLISHED`, `ACTIVE`, or `REVISING` overlapping the
        candidate window — summed `controlled_rate` values, excluding the
        candidate itself — is subtracted; the result is floored at 0."

        Design: Difficulty/resource_temporal_overlap/tmi_aggregate_capacity_coexistence
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        create_published_forecast(
            api, facility["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("16:00"),
        )  # predicted 30 (no events)

        afp = propose_tmi(
            api, facility["id"], tmi_type="AIRSPACE_FLOW_PROGRAM",
            program_start=at("13:00"), program_end=at("16:00"), controlled_rate=4,
        )
        publish_tmi(api, afp["id"])
        afp = activate_tmi(api, afp["id"])
        assert afp["status"] == "ACTIVE"

        # coexistence: 6 <= max(0, min(30, 30) - 4) = 26
        gdp1 = propose_gdp(
            api, facility["id"], program_start=at("13:00"),
            program_end=at("15:00"), controlled_rate=6,
        )
        publish_tmi(api, gdp1["id"])
        gdp1 = activate_tmi(api, gdp1["id"])
        assert gdp1["status"] == "ACTIVE"

        # a second overlapping GDP is hard-rejected regardless of headroom
        resp = api.create_tmi(
            facility["id"],
            gdp_payload(
                program_start=at("14:00"), program_end=at("16:00"), controlled_rate=6
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_TMI_OVERLAP)

        # an AFP skips exclusivity but not the aggregate gate: 60 > 26
        afp2 = propose_tmi(
            api, facility["id"], tmi_type="AIRSPACE_FLOW_PROGRAM",
            program_start=at("14:00"), program_end=at("15:00"), controlled_rate=60,
        )
        resp = api.publish_tmi(afp2["id"], COMMAND_CENTER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_RATE_EXCEEDS_CAPACITY)
