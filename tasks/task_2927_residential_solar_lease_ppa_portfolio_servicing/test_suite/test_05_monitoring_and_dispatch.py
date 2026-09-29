"""Alarms, severity grading, dispatch and the compensating cancel.

The monitoring dimension is a projection over the open alarm set rather than a
stored flag, so every test here reads the agreement back and checks what the
projection says about the alarms that are actually open.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import (
    assert_identity_fields,
    assert_instant_equals,
    assert_monitoring_counters,
    assert_state_dimensions,
)
from test_helpers.fixtures import (
    activate,
    book_lease,
    book_ppa,
    complete_roll,
    dispatch,
    make_homeowner,
    make_tariff,
    open_outage,
    read_agreement,
    set_clock,
    triage,
)

CLOCK = "2026-08-01T00:00:00Z"


def _active_agreement(api, clock=CLOCK):
    """An ACTIVE PPA on the shared terms, ready to carry alarms."""
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(
        api,
        owner["id"],
        schedule["id"],
        contract_start_date="2025-01-01",
        escalator_pct=0.029,
        base_ppa_rate_per_kwh_millicents=14750,
        guaranteed_annual_kwh=9600,
        guarantee_band_pct=0.05,
    )
    activate(api, agreement["id"])
    return agreement


def _read_event(api, outage_event_id):
    return validate_success(api.get_outage_event(outage_event_id, U.ops_headers()), 200)


def test_a_new_alarm_lands_open_and_only_the_monitoring_dimension_moves(api):
    """The alarm opens, the contract and the asset dimensions stay where they were.

    §3.5: "A new alarm lands in `status` `OPEN` with `resolved_at` null and
    `excused` false, its `severity` graded immediately, and the agreement's
    `open_outage_count` incremented, its `monitoring_status` re-derived, and its
    `version` advanced." §2.8: "A roof suspension therefore does not disturb the
    contract lifecycle, an open alarm does not block a transfer".

    Design: Corner/state_machines/new_outage_event_starts_open_and_opens_the_monitoring_dimension
    """
    agreement = _active_agreement(api)

    event = open_outage(
        api,
        agreement["id"],
        "2026-07-31T12:00:00Z",
        inverter_serial="INV-7781-A",
        outage_type=C.OUTAGE_TYPE_COMMS_LOSS,
    )

    assert_identity_fields(event)
    assert event["status"] == C.OUTAGE_OPEN
    assert event["version"] == 1
    assert event["resolved_at"] is None
    assert event["excused"] is False
    assert event["downtime_minutes"] == 720
    assert event["severity"] == C.SEVERITY_LOW
    assert event["agreement_id"] == agreement["id"]

    parent = read_agreement(api, agreement["id"])
    assert_monitoring_counters(parent, open_count=1, excused_minutes=0)
    assert_state_dimensions(
        parent,
        lifecycle_state=C.LIFECYCLE_ACTIVE,
        monitoring_status=C.MONITORING_OUTAGE_OPEN,
        service_status=C.SERVICE_IN_SERVICE,
    )


def test_triage_confirms_the_alarm_and_regrades_it_against_the_clock(api):
    """Two days of elapsed downtime grades MEDIUM, and the alarm stays open.

    §3.5: "Triage is exclusive to the `FieldOpsCoordinator` and confirms that an
    alarm is real and dispatchable: the event moves `OPEN → TRIAGED`, its `severity`
    is recomputed against the clock, and its `version` advances." §3.5: "from 1440
    minutes up to but not including 10080 minutes — one full day up to seven full
    days — grades `MEDIUM`".

    Design: Corner/state_machines/triage_moves_open_outage_to_triaged_and_grades_severity
    """
    agreement = _active_agreement(api)
    event = open_outage(api, agreement["id"], "2026-07-30T00:00:00Z")

    triaged = triage(api, event["id"])

    assert triaged["status"] == C.OUTAGE_TRIAGED
    assert triaged["version"] == 2
    assert triaged["severity"] == C.SEVERITY_MEDIUM
    assert triaged["downtime_minutes"] == 2880
    assert triaged["resolved_at"] is None

    parent = read_agreement(api, agreement["id"])
    assert_monitoring_counters(parent, open_count=1, excused_minutes=0)
    assert_state_dimensions(parent, monitoring_status=C.MONITORING_OUTAGE_OPEN)


def test_the_severity_bands_include_their_lower_bounds(api):
    """1439 minutes is LOW, exactly 1440 is MEDIUM and exactly 10080 is HIGH.

    §3.5: "fewer than 1440 elapsed minutes — that is, less than one full day —
    grades `LOW`; from 1440 minutes up to but not including 10080 minutes — one full
    day up to seven full days — grades `MEDIUM`; and 10080 elapsed minutes or more
    grades `HIGH`. The lower bound of each band is inclusive and the upper bound
    exclusive, so exactly 1440 minutes is `MEDIUM` and exactly 10080 minutes is
    `HIGH`."

    Design: Corner/calculations/outage_severity_boundaries_are_inclusive_at_1440_and_10080_minutes
    """
    agreement = _active_agreement(api)
    cases = [
        ("2026-07-31T00:01:00Z", 1439, C.SEVERITY_LOW),
        ("2026-07-31T00:00:00Z", 1440, C.SEVERITY_MEDIUM),
        ("2026-07-25T00:00:00Z", 10080, C.SEVERITY_HIGH),
    ]

    for index, (detected_at, minutes, severity) in enumerate(cases):
        event = open_outage(
            api, agreement["id"], detected_at, inverter_serial=f"INV-900{index}"
        )
        triaged = triage(api, event["id"])
        assert triaged["downtime_minutes"] == minutes
        assert triaged["severity"] == severity, (
            f"{minutes} elapsed minutes must grade {severity}"
        )
        assert triaged["status"] == C.OUTAGE_TRIAGED

    parent = read_agreement(api, agreement["id"])
    assert_monitoring_counters(parent, open_count=3, excused_minutes=0)
    assert_state_dimensions(parent, monitoring_status=C.MONITORING_OUTAGE_OPEN)


def test_an_alarm_detected_after_the_clock_is_refused_but_one_at_the_clock_is_not(api):
    """The comparison against the logical clock is strict.

    §3.5: "A `detected_at` strictly after the current logical clock instant is
    refused with `ERR_DETECTED_AT_IN_FUTURE`." §2.5: "every temporal decision —
    contract-year arithmetic, due dates, election windows, warranty expiry, outage
    downtime, roof-work window enforcement, closing-date staleness — reads that
    logical clock and never the host's wall clock."

    Design: Corner/validations/outage_detected_one_second_after_the_clock_is_rejected
    """
    agreement = _active_agreement(api)

    validate_error(
        api.create_outage_event(
            F.outage_event_payload(
                agreement["id"],
                "2026-08-01T00:00:01Z",
                inverter_serial="INV-7781-A",
                outage_type=C.OUTAGE_TYPE_COMMS_LOSS,
            ),
            U.ops_headers(),
        ),
        E.ERR_DETECTED_AT_IN_FUTURE,
        422,
    )

    parent = read_agreement(api, agreement["id"])
    assert_monitoring_counters(parent, open_count=0, excused_minutes=0)
    assert_state_dimensions(parent, monitoring_status=C.MONITORING_OK)

    accepted = open_outage(
        api,
        agreement["id"],
        CLOCK,
        inverter_serial="INV-7781-A",
        outage_type=C.OUTAGE_TYPE_COMMS_LOSS,
    )
    assert accepted["status"] == C.OUTAGE_OPEN
    assert accepted["downtime_minutes"] == 0
    assert accepted["severity"] == C.SEVERITY_LOW


def _two_open_alarms(api):
    """One 360-minute alarm and one exactly-10080-minute alarm on one agreement."""
    agreement = _active_agreement(api)
    minor = open_outage(
        api, agreement["id"], "2026-07-31T18:00:00Z", inverter_serial="INV-7781-A"
    )
    major = open_outage(
        api, agreement["id"], "2026-07-25T00:00:00Z", inverter_serial="INV-7781-A"
    )
    return agreement, minor, major


def test_a_false_positive_resolves_the_alarm_without_excusing_a_minute(api):
    """The clock stamps `resolved_at`, yet nothing is excused and nothing pro-rates.

    §3.5: "Closing an alarm as a false positive stamps `resolved_at` with the
    current clock instant, freezes `downtime_minutes` at 0, leaves `excused` false,
    decrements the agreement's `open_outage_count`, and advances both the event's and
    the agreement's `version`". §2.9: "`excused_downtime_minutes` on the agreement
    equals the sum of `downtime_minutes` over the agreement's outage events that are
    both excused and resolved — an event still open, an event closed as a false
    positive, and an event whose dispatch ended without access all contribute
    nothing."

    Design: Corner/endpoints/marking_an_alarm_false_positive_closes_it_without_excusing_downtime
    """
    agreement, minor, major = _two_open_alarms(api)

    assert minor["downtime_minutes"] == 360
    assert minor["severity"] == C.SEVERITY_LOW
    assert major["downtime_minutes"] == 10080
    assert major["severity"] == C.SEVERITY_HIGH
    before = read_agreement(api, agreement["id"])
    assert_monitoring_counters(before, open_count=2, excused_minutes=0)

    dismissed = validate_success(
        api.mark_false_positive(minor["id"], U.ops_headers()), 200
    )

    assert dismissed["status"] == C.OUTAGE_FALSE_POSITIVE
    assert_instant_equals(dismissed["resolved_at"], CLOCK, "resolved_at")
    assert dismissed["downtime_minutes"] == 0
    assert dismissed["excused"] is False
    assert dismissed["severity"] == C.SEVERITY_LOW

    parent = read_agreement(api, agreement["id"])
    assert_monitoring_counters(parent, open_count=1, excused_minutes=0)
    assert_state_dimensions(parent, monitoring_status=C.MONITORING_OUTAGE_OPEN)
    assert parent["version"] == before["version"] + 1


def test_the_false_positive_edge_exists_only_while_the_alarm_is_open(api):
    """A dismissed alarm and a triaged alarm are both too late to dismiss.

    §3.5: "An alarm that was never a real fault is instead closed out by a
    `FieldOpsCoordinator` or `PortfolioAdmin`, moving `OPEN → FALSE_POSITIVE`, which
    is only possible while no truck roll exists for the event at all — an attempt
    after a dispatch has ever been created reports `ERR_INVALID_STATE_TRANSITION`."
    §2.10 rung 8: "**State-transition legality.** HTTP 409 on every action endpoint
    whose target is not in a state from which the requested transition exists."

    Design: Corner/endpoints/marking_an_alarm_false_positive_closes_it_without_excusing_downtime
    """
    agreement, minor, major = _two_open_alarms(api)
    validate_success(api.mark_false_positive(minor["id"], U.ops_headers()), 200)

    validate_error(
        api.mark_false_positive(minor["id"], U.ops_headers()),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    assert_monitoring_counters(
        read_agreement(api, agreement["id"]), open_count=1, excused_minutes=0
    )

    triaged = triage(api, major["id"])
    assert triaged["severity"] == C.SEVERITY_HIGH
    assert_state_dimensions(
        read_agreement(api, agreement["id"]),
        monitoring_status=C.MONITORING_OUTAGE_OPEN,
    )

    validate_error(
        api.mark_false_positive(major["id"], U.ops_headers()),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.mark_false_positive(major["id"], U.agent_headers()),
        E.ERR_UNAUTHORIZED,
        403,
    )

    listed, meta = validate_paginated(
        api.list_outage_events(
            U.ops_headers(),
            {
                "agreement_id": agreement["id"],
                "status": C.OUTAGE_FALSE_POSITIVE,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [minor["id"]]


def test_only_operator_caused_causes_add_to_the_excused_downtime_total(api):
    """A string fault contributes its full 2880 minutes; a homeowner cause adds none.

    §3.6: "its `excused` flag is set to true when the diagnosed `root_cause` is
    `STRING_FAULT` or `COMMS_ONLY` and to false for every other cause. When — and
    only when — `excused` came out true, the agreement's `excused_downtime_minutes`
    is increased by that event's `downtime_minutes`." §3.6: "`STRING_FAULT` and
    `COMMS_ONLY` both set `billable_to` to `SUNRUN_OM` with `labor_cost_cents` of
    38000 and mark the outage excused, because those two causes are the operator's
    own; and `HOMEOWNER_CAUSED` sets `billable_to` to `HOMEOWNER` with
    `labor_cost_cents` of 12500 and leaves the outage unexcused."

    Design: Corner/calculations/excused_downtime_aggregates_only_operator_caused_outages
    """
    agreement = _active_agreement(api)
    operator_event = triage(
        api,
        open_outage(api, agreement["id"], "2026-07-30T00:00:00Z")["id"],
    )
    homeowner_event = triage(
        api,
        open_outage(
            api, agreement["id"], "2026-07-31T00:00:00Z", inverter_serial="INV-7781-B"
        )["id"],
    )
    operator_roll = dispatch(
        api,
        operator_event,
        "2026-08-02T09:00:00Z",
        "2026-08-02T13:00:00Z",
        technician_code="TECH-A100",
    )
    homeowner_roll = dispatch(
        api,
        homeowner_event,
        "2026-08-02T09:00:00Z",
        "2026-08-02T13:00:00Z",
        technician_code="TECH-B200",
    )

    serviced = complete_roll(
        api,
        operator_roll["id"],
        C.DISPOSITION_SERVICE_COMPLETE,
        C.CAUSE_STRING_FAULT,
    )
    billed = complete_roll(
        api,
        homeowner_roll["id"],
        C.DISPOSITION_SERVICE_COMPLETE,
        C.CAUSE_HOMEOWNER_CAUSED,
    )

    assert serviced["billable_to"] == C.BILLABLE_SUNRUN_OM
    assert serviced["labor_cost_cents"] == 38000
    assert billed["billable_to"] == C.BILLABLE_HOMEOWNER
    assert billed["labor_cost_cents"] == 12500

    resolved_operator = _read_event(api, operator_event["id"])
    assert resolved_operator["status"] == C.OUTAGE_RESOLVED
    assert resolved_operator["downtime_minutes"] == 2880
    assert resolved_operator["excused"] is True

    resolved_homeowner = _read_event(api, homeowner_event["id"])
    assert resolved_homeowner["status"] == C.OUTAGE_RESOLVED
    assert resolved_homeowner["downtime_minutes"] == 1440
    assert resolved_homeowner["excused"] is False

    parent = read_agreement(api, agreement["id"])
    assert_monitoring_counters(parent, open_count=0, excused_minutes=2880)
    assert_state_dimensions(parent, monitoring_status=C.MONITORING_OK)


def test_a_stale_outage_event_version_refuses_the_dispatch_with_its_own_code(api):
    """Triage bumped the parent, so the version read at creation is one behind.

    §2.7: "Dispatching a truck roll must carry `expected_outage_event_version`, a
    mandatory field holding the `version` of the parent outage event as the client
    last observed it, because the dispatch consumes the triage decision recorded on
    that event. If it does not equal the outage event's current `version`, the
    dispatch is refused with `ERR_STALE_OUTAGE_EVENT_VERSION` (HTTP 412)." §3.5: "The
    linked event moves `TRIAGED → DISPATCHED` and its `version` advances".

    Design: Corner/cross_cutting_complexity_layers/stale_expected_outage_event_version_on_a_dispatch_returns_412
    """
    agreement = _active_agreement(api)
    created = open_outage(api, agreement["id"], "2026-07-30T00:00:00Z")
    open_outage(
        api, agreement["id"], "2026-07-31T00:00:00Z", inverter_serial="INV-7781-B"
    )
    triaged = triage(api, created["id"])
    assert triaged["version"] == created["version"] + 1

    stale = F.truck_roll_payload(
        created["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
        created["version"],
        technician_code="TECH-A100",
    )
    validate_error(
        api.create_truck_roll(stale, U.ops_headers()),
        E.ERR_STALE_OUTAGE_EVENT_VERSION,
        412,
    )

    after_refusal = _read_event(api, created["id"])
    assert after_refusal["status"] == C.OUTAGE_TRIAGED
    assert after_refusal["version"] == triaged["version"]
    assert_state_dimensions(
        read_agreement(api, agreement["id"]),
        monitoring_status=C.MONITORING_OUTAGE_OPEN,
    )

    roll = dispatch(
        api,
        triaged,
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
        technician_code="TECH-A100",
    )
    assert roll["status"] == C.ROLL_SCHEDULED
    assert _read_event(api, created["id"])["version"] == triaged["version"] + 1

    parent = read_agreement(api, agreement["id"])
    assert_monitoring_counters(parent, open_count=2, excused_minutes=0)
    assert_state_dimensions(
        parent, monitoring_status=C.MONITORING_TRUCK_ROLL_DISPATCHED
    )


def test_an_open_alarm_reports_the_state_error_rather_than_the_version_error(api):
    """Rung 8 outranks rung 9, so an OPEN parent answers 409 and not 412.

    §2.7: "Both checks sit below the state ladder described in §2.10, so a stale
    version presented against a parent that is also in the wrong state reports the
    state error instead — the client's whole premise is wrong, and the state is the
    more useful thing to learn." §3.5: "Dispatching a technician is exclusive to the
    `FieldOpsCoordinator` and answers a `TRIAGED` alarm."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_outage_event_version_on_a_dispatch_returns_412
    """
    agreement = _active_agreement(api)
    still_open = open_outage(api, agreement["id"], "2026-07-31T00:00:00Z")

    response = api.create_truck_roll(
        F.truck_roll_payload(
            still_open["id"],
            "2026-08-04T08:00:00Z",
            "2026-08-04T12:00:00Z",
            still_open["version"] + 1,
            technician_code="TECH-B200",
        ),
        U.ops_headers(),
    )

    validate_error(response, E.ERR_INVALID_STATE_TRANSITION, 409)
    assert response.status_code != 412

    unchanged = _read_event(api, still_open["id"])
    assert unchanged["status"] == C.OUTAGE_OPEN
    assert unchanged["version"] == still_open["version"]
    _, meta = validate_paginated(
        api.list_truck_rolls(U.ops_headers(), {"outage_event_id": still_open["id"]})
    )
    assert meta["total_count"] == 0


def _three_triaged_alarms(api):
    """Three agreements, each carrying one TRIAGED alarm detected at the clock."""
    set_clock(api, CLOCK)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreements, events = [], []
    for index, address in enumerate(
        ("14 Quail Rd, Fremont CA", "16 Quail Rd, Fremont CA", "18 Quail Rd, Fremont CA")
    ):
        agreement = book_ppa(
            api,
            owner["id"],
            schedule["id"],
            site_address=address,
            contract_start_date="2025-01-01",
            escalator_pct=0.029,
            base_ppa_rate_per_kwh_millicents=14750,
            guaranteed_annual_kwh=9600,
            guarantee_band_pct=0.05,
        )
        activate(api, agreement["id"])
        event = triage(
            api,
            open_outage(
                api, agreement["id"], CLOCK, inverter_serial=f"INV-770{index}"
            )["id"],
        )
        assert event["severity"] == C.SEVERITY_LOW
        agreements.append(agreement)
        events.append(event)
    return agreements, events


def test_an_adjacent_technician_window_is_accepted_and_an_overlapping_one_is_not(api):
    """The window is half-open with no buffer, so 12:00 may follow 12:00.

    §3.5: "Technician windows are half-open, running from `scheduled_window_start` up
    to but not including `scheduled_window_end`, and no buffer is applied: if another
    truck roll in `status` `SCHEDULED` carries the same `technician_code` and its
    window overlaps the requested one, the dispatch is refused with
    `ERR_TECHNICIAN_WINDOW_CONFLICT`, while a window beginning at the exact instant
    another ends does not conflict".

    Design: Difficulty/resource_temporal_overlap/technician_half_open_window_adjacency_allowed_overlap_rejected
    """
    agreements, events = _three_triaged_alarms(api)

    booked = dispatch(
        api,
        events[0],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
        technician_code="TECH-4471",
    )
    assert booked["status"] == C.ROLL_SCHEDULED
    assert _read_event(api, events[0]["id"])["status"] == C.OUTAGE_DISPATCHED

    adjacent = dispatch(
        api,
        events[1],
        "2026-08-03T12:00:00Z",
        "2026-08-03T16:00:00Z",
        technician_code="TECH-4471",
    )
    assert adjacent["status"] == C.ROLL_SCHEDULED

    validate_error(
        api.create_truck_roll(
            F.truck_roll_payload(
                events[2]["id"],
                "2026-08-03T07:00:00Z",
                "2026-08-03T11:59:00Z",
                events[2]["version"],
                technician_code="TECH-4471",
            ),
            U.ops_headers(),
        ),
        E.ERR_TECHNICIAN_WINDOW_CONFLICT,
        409,
    )

    rejected_parent = _read_event(api, events[2]["id"])
    assert rejected_parent["status"] == C.OUTAGE_TRIAGED
    assert rejected_parent["version"] == events[2]["version"]
    assert_state_dimensions(
        read_agreement(api, agreements[2]["id"]),
        monitoring_status=C.MONITORING_OUTAGE_OPEN,
    )


def test_cancelling_the_first_roll_frees_the_window_for_the_rejected_request(api):
    """A CANCELLED roll never conflicts, and 11:59 still clears the 12:00 booking.

    §3.5: "rolls that are `CANCELLED`, `COMPLETED` or `NO_ACCESS` never conflict at
    all." §3.5: "The roll moves `SCHEDULED → CANCELLED`, its `billable_to` stays null
    and its `labor_cost_cents` stays 0, and the technician's window is freed for
    reuse. The linked event falls back `DISPATCHED → TRIAGED`".

    Design: Difficulty/resource_temporal_overlap/technician_half_open_window_adjacency_allowed_overlap_rejected
    """
    agreements, events = _three_triaged_alarms(api)
    booked = dispatch(
        api,
        events[0],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
        technician_code="TECH-4471",
    )
    dispatch(
        api,
        events[1],
        "2026-08-03T12:00:00Z",
        "2026-08-03T16:00:00Z",
        technician_code="TECH-4471",
    )
    validate_error(
        api.create_truck_roll(
            F.truck_roll_payload(
                events[2]["id"],
                "2026-08-03T07:00:00Z",
                "2026-08-03T11:59:00Z",
                events[2]["version"],
                technician_code="TECH-4471",
            ),
            U.ops_headers(),
        ),
        E.ERR_TECHNICIAN_WINDOW_CONFLICT,
        409,
    )

    cancelled = validate_success(
        api.cancel_truck_roll(booked["id"], U.ops_headers()), 200
    )
    assert cancelled["status"] == C.ROLL_CANCELLED
    assert cancelled["billable_to"] is None
    assert cancelled["labor_cost_cents"] == 0
    assert _read_event(api, events[0]["id"])["status"] == C.OUTAGE_TRIAGED

    retried = validate_success(
        api.create_truck_roll(
            F.truck_roll_payload(
                events[2]["id"],
                "2026-08-03T07:00:00Z",
                "2026-08-03T11:59:00Z",
                events[2]["version"],
                technician_code="TECH-4471",
            ),
            U.ops_headers(),
        ),
        201,
    )
    assert retried["status"] == C.ROLL_SCHEDULED

    freed = read_agreement(api, agreements[0]["id"])
    assert_monitoring_counters(freed, open_count=1, excused_minutes=0)
    assert_state_dimensions(freed, monitoring_status=C.MONITORING_OUTAGE_OPEN)
    assert_state_dimensions(
        read_agreement(api, agreements[2]["id"]),
        monitoring_status=C.MONITORING_TRUCK_ROLL_DISPATCHED,
    )


def _lease_with_a_dispatched_alarm(api):
    """A LEASE site whose single alarm has a technician already on the books."""
    set_clock(api, CLOCK)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_lease(
        api,
        owner["id"],
        schedule["id"],
        contract_start_date="2025-01-01",
        escalator_pct=0.019,
        base_monthly_lease_cents=12900,
        guaranteed_annual_kwh=8400,
        system_dc_kw=6.4,
        guarantee_band_pct=0.05,
    )
    activate(api, agreement["id"])
    event = triage(api, open_outage(api, agreement["id"], CLOCK)["id"])
    roll = dispatch(
        api,
        event,
        "2026-08-02T09:00:00Z",
        "2026-08-02T13:00:00Z",
        technician_code="TECH-9002",
    )
    return agreement, event, roll


def test_cancelling_a_dispatch_returns_the_monitoring_projection_to_outage_open(api):
    """The count returns to 1 — not 0 and not 2 — and nothing is excused.

    §3.5: "The linked event falls back `DISPATCHED → TRIAGED` and therefore stays
    inside the open set, so the agreement's `open_outage_count` is unchanged; the
    agreement's `monitoring_status` is re-derived, which returns it
    `TRUCK_ROLL_DISPATCHED → OUTAGE_OPEN` when no other event of that agreement
    remains `DISPATCHED`". §3.5: "An agreement's `monitoring_status` is never toggled
    incrementally; it is re-derived from scratch after every event that adds to or
    removes from the agreement's open alarm set".

    Design: Difficulty/compensating_invariant/cancelled_truck_roll_leaves_outage_counters_untouched
    """
    agreement, event, roll = _lease_with_a_dispatched_alarm(api)

    before = read_agreement(api, agreement["id"])
    assert_monitoring_counters(before, open_count=1, excused_minutes=0)
    assert_state_dimensions(
        before, monitoring_status=C.MONITORING_TRUCK_ROLL_DISPATCHED
    )

    cancelled = validate_success(
        api.cancel_truck_roll(roll["id"], U.ops_headers()), 200
    )
    assert cancelled["status"] == C.ROLL_CANCELLED

    reopened = _read_event(api, event["id"])
    assert reopened["status"] == C.OUTAGE_TRIAGED
    assert reopened["resolved_at"] is None
    assert reopened["downtime_minutes"] == 0
    assert reopened["excused"] is False

    after = read_agreement(api, agreement["id"])
    assert_monitoring_counters(after, open_count=1, excused_minutes=0)
    assert_state_dimensions(after, monitoring_status=C.MONITORING_OUTAGE_OPEN)


def test_the_replacement_visit_excuses_exactly_one_outage_worth_of_minutes(api):
    """2880 minutes arrive once, from the roll that actually happened.

    §3.6: "The linked alarm moves `DISPATCHED → RESOLVED`: its `resolved_at` is
    stamped with the same clock instant, its `downtime_minutes` is frozen at the whole
    minutes between `detected_at` and `resolved_at`". §2.9: "Because both counters are
    defined by these sums, dispatching a technician and then cancelling the dispatch is
    a compensating pair that leaves both counters exactly where they started."

    Design: Difficulty/compensating_invariant/cancelled_truck_roll_leaves_outage_counters_untouched
    """
    agreement, event, roll = _lease_with_a_dispatched_alarm(api)
    validate_success(api.cancel_truck_roll(roll["id"], U.ops_headers()), 200)

    replacement = dispatch(
        api,
        _read_event(api, event["id"]),
        "2026-08-02T09:00:00Z",
        "2026-08-02T13:00:00Z",
        technician_code="TECH-9002",
    )
    assert replacement["status"] == C.ROLL_SCHEDULED

    set_clock(api, "2026-08-03T00:00:00Z")
    completed = complete_roll(
        api,
        replacement["id"],
        C.DISPOSITION_SERVICE_COMPLETE,
        C.CAUSE_STRING_FAULT,
    )

    assert completed["status"] == C.ROLL_COMPLETED
    assert completed["billable_to"] == C.BILLABLE_SUNRUN_OM
    assert completed["labor_cost_cents"] == 38000
    assert completed["diagnosed_by_user_id"] == U.OPS_2
    assert_instant_equals(completed["completed_at"], "2026-08-03T00:00:00Z")

    resolved = _read_event(api, event["id"])
    assert resolved["status"] == C.OUTAGE_RESOLVED
    assert_instant_equals(resolved["resolved_at"], "2026-08-03T00:00:00Z")
    assert resolved["downtime_minutes"] == 2880
    assert resolved["excused"] is True
    assert resolved["severity"] == C.SEVERITY_MEDIUM

    parent = read_agreement(api, agreement["id"])
    assert_monitoring_counters(parent, open_count=0, excused_minutes=2880)
    assert_state_dimensions(parent, monitoring_status=C.MONITORING_OK)
