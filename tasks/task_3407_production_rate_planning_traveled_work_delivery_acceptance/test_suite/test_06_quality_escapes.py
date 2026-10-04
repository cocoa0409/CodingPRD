"""Quality escapes: notification discipline, segregated disposition, cycles (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_quality_inspector_headers,
    api_client,
    report_escape_payload, begin_root_cause_payload, disposition_payload,
    setup_aircraft, add_work_package, complete_work_package, set_clock,
    create_open_escape, create_escape_in_root_cause,
    create_dispositioned_escape, create_closed_escape,
    assert_quality_escape,
)

QI1 = make_quality_inspector_headers("insp-1")
QI2 = make_quality_inspector_headers("insp-2")


def test_escape_late_notification_flag_computed_against_clock(api):
    """PRD §3.6: "Regulator notification comes next in practice: notifying stamps
    `regulator_notified_at` with the current logical clock, and the escape's
    `is_late_notification` reads true exactly when that stamp is later than the escape's
    `created_at` plus 24 hours."
    PRD §2.4: "the stamp written by regulator notification is the clock's reading at that
    moment".

    Design: Corner/entities/escape_late_notification_flag_computed_against_clock
    """
    _program, _customer, aircraft = setup_aircraft(line_number=1002)
    escape = create_open_escape(
        aircraft["id"], severity="CRITICAL", description="Wire chafe"
    )
    # Escape created at the startup clock 2026-09-01T00:00:00Z; move ahead 26 hours.
    set_clock("2026-09-02T02:00:00Z")
    escape = validate_success(api_client.notify_regulator(escape["id"], QI1))
    assert escape["regulator_notified_at"] is not None
    assert escape["regulator_notified_at"].startswith("2026-09-02T02:00:00"), (
        "the stamp is the logical clock reading"
    )
    assert escape["is_late_notification"] is True, "26h after creation exceeds the 24h window"


def test_escape_close_from_open_rejected(api):
    """PRD §3.6: "Closing (`DISPOSITIONED` → `CLOSED`) demands that every rework order
    spawned from this escape — every order whose `escape_id` points here — already sits in
    `CLOSED` or `CREDITED`."
    PRD §2.8: "the requested transition must exist from the resource's current state,
    including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)".

    Design: Corner/state_machines/escape_close_from_open_rejected
    """
    _program, _customer, aircraft = setup_aircraft(line_number=1005)
    escape = create_open_escape(aircraft["id"], severity="MAJOR", description="Dent")
    assert escape["status"] == "OPEN"
    resp = api_client.close_escape(escape["id"], QI2)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_begin_root_cause_without_regulator_notification_rejected(api, admin_headers):
    """PRD §3.6: "Root-cause work (`OPEN` → `ROOT_CAUSE`) cannot begin before that
    notification exists — the attempt is rejected with
    `ERR_REGULATOR_NOTIFICATION_REQUIRED` (HTTP 422) — and it requires a `conformance_refs`
    payload carrying at least one reference; a successful call appends those references and
    flips `conformance_documented` to true."
    PRD §3.6: "`conformance_documented` starts false, and `conformance_refs` starts empty —
    an append-only list for the rest of the escape's life."

    Design: Corner/validations/begin_root_cause_without_regulator_notification_rejected
    """
    _program, _customer, aircraft = setup_aircraft(line_number=1019)
    escape = create_open_escape(
        aircraft["id"], severity="CRITICAL", description="Wire chafe"
    )
    resp = api_client.begin_root_cause(
        escape["id"], begin_root_cause_payload(["DOC-1"]), QI1
    )
    validate_error(resp, ApiErrorId.ERR_REGULATOR_NOTIFICATION_REQUIRED)
    escape = validate_success(api_client.get_quality_escape(escape["id"], admin_headers))
    assert escape["status"] == "OPEN"
    assert escape["conformance_documented"] is False
    assert escape["conformance_refs"] == []


def test_disposition_by_reporting_inspector_rejected(api, admin_headers):
    """PRD §3.6: "Disposition (`ROOT_CAUSE` → `DISPOSITIONED`) is segregated from reporting:
    the acting inspector's `X-User-ID` must differ from the escape's `reported_by_id`, and
    a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/disposition_by_reporting_inspector_rejected
    """
    _program, _customer, aircraft = setup_aircraft(line_number=1020)
    escape = create_escape_in_root_cause(
        aircraft["id"], severity="MAJOR", description="Dent", reporter_id="insp-1"
    )
    assert escape["status"] == "ROOT_CAUSE"
    resp = api_client.disposition_escape(
        escape["id"], disposition_payload("REWORK"),
        make_quality_inspector_headers("insp-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    escape = validate_success(api_client.get_quality_escape(escape["id"], admin_headers))
    assert escape["status"] == "ROOT_CAUSE"
    assert escape["dispositioned_by_id"] is None


def test_escape_severity_unknown_enum_rejected(api):
    """PRD §3.6: "A `QualityInspector` reports an escape against an aircraft with a
    `severity` of `MAJOR` or `CRITICAL` and a `description`"
    PRD §2.8: "field presence, types, enum membership, and integer lower bounds are
    validated only after every rule above has passed: `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/escape_severity_unknown_enum_rejected
    """
    _program, _customer, aircraft = setup_aircraft(line_number=1022)
    resp = api_client.report_quality_escape(
        aircraft["id"],
        report_escape_payload(severity="MINOR", description="Scratch"),
        QI1,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_escape_reopen_clears_disposition_and_cycle_repeats(api):
    """PRD §3.6: "A successful disposition records the actor as `dispositioned_by_id` and
    the payload's `disposition_code` — one of `USE_AS_IS`, `REWORK`, or `SCRAP`. Reopening
    (`DISPOSITIONED` → `ROOT_CAUSE`) nulls both fields and lets the investigation resume;
    the cycle may repeat."

    Design: Difficulty/non_linear_state_machine/escape_disposition_reopen_cycle_clears_disposition
    """
    _program, _customer, aircraft = setup_aircraft(line_number=3002)
    escape = create_dispositioned_escape(
        aircraft["id"], severity="MAJOR", description="Skin dent at station 3",
        reporter_id="insp-1", dispositioner_id="insp-2", disposition_code="REWORK",
    )
    assert escape["status"] == "DISPOSITIONED"
    assert escape["dispositioned_by_id"] == "insp-2"
    assert escape["disposition_code"] == "REWORK"

    escape = validate_success(api_client.reopen_escape(escape["id"], QI2))
    assert escape["status"] == "ROOT_CAUSE"
    assert escape["dispositioned_by_id"] is None, "the prior disposition is erased"
    assert escape["disposition_code"] is None

    escape = validate_success(
        api_client.disposition_escape(escape["id"], disposition_payload("USE_AS_IS"), QI2)
    )
    assert escape["status"] == "DISPOSITIONED"
    assert escape["disposition_code"] == "USE_AS_IS"
    assert escape["dispositioned_by_id"] == "insp-2"


def test_escape_reopen_preserves_append_only_conformance_refs(api):
    """PRD §3.6: "`conformance_documented` starts false, and `conformance_refs` starts
    empty — an append-only list for the rest of the escape's life."
    PRD §3.6: "a successful call appends those references and flips `conformance_documented`
    to true."
    PRD §3.6: "Reopening (`DISPOSITIONED` → `ROOT_CAUSE`) nulls both fields and lets the
    investigation resume; the cycle may repeat."

    Design: Difficulty/non_linear_state_machine/escape_disposition_reopen_cycle_clears_disposition
    """
    _program, _customer, aircraft = setup_aircraft(line_number=3006)
    escape = create_dispositioned_escape(
        aircraft["id"], severity="MAJOR", description="Sealant void",
        reporter_id="insp-1", dispositioner_id="insp-2",
        disposition_code="USE_AS_IS",
    )
    assert escape["conformance_refs"] == ["DOC-1"]
    assert escape["conformance_documented"] is True

    escape = validate_success(api_client.reopen_escape(escape["id"], QI2))
    assert escape["status"] == "ROOT_CAUSE"
    assert escape["dispositioned_by_id"] is None
    assert escape["disposition_code"] is None
    assert escape["conformance_refs"] == ["DOC-1"], (
        "the append-only conformance list survives a reopen"
    )
    assert escape["conformance_documented"] is True


def test_production_advances_while_quality_holds(api, line_manager_headers):
    """PRD §3.1: "Three independent state dimensions — production, quality, and delivery —
    ride on every aircraft; each evolves on its own triggers, and only a handful of gates
    (delivery acceptance reads all three) cross dimensions."
    PRD §3.6: "the escape lands in `OPEN`, the aircraft's `quality_status` moves immediately
    to `HOLD`, and the program's `open_escape_count` and `posture` are recomputed."
    PRD §3.4: "the moment every work package of an aircraft — at least one must exist —
    sits in `COMPLETE` or `TRAVELED`, the aircraft's `production_status` bubbles up from
    `IN_PRODUCTION` to `ASSEMBLY_COMPLETE` and the program's `undelivered_inventory_count`
    is recomputed."
    PRD §3.6: "The close recomputes the program's `open_escape_count`, returns the
    aircraft's `quality_status` to `CLEAR` when no escape on it remains in `OPEN`,
    `ROOT_CAUSE`, or `DISPOSITIONED`, and recomputes the program's `posture`."

    Design: Difficulty/non_linear_state_machine/aircraft_dimensions_production_advances_while_quality_holds
    """
    _program, _customer, aircraft = setup_aircraft(line_number=3003)
    work_package = add_work_package(aircraft["id"], planned_hours=5)
    escape = create_open_escape(
        aircraft["id"], severity="MAJOR", description="Fastener mismatch"
    )

    complete_work_package(work_package["id"])
    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], line_manager_headers))
    assert aircraft["production_status"] == "ASSEMBLY_COMPLETE", (
        "production advanced while the escape held quality"
    )
    assert aircraft["quality_status"] == "HOLD"
    assert aircraft["delivery_status"] == "NOT_STARTED"

    get_success_data(api_client.notify_regulator(escape["id"], QI1))
    get_success_data(api_client.begin_root_cause(escape["id"], begin_root_cause_payload(["DOC-9"]), QI1))
    get_success_data(api_client.disposition_escape(escape["id"], disposition_payload("USE_AS_IS"), QI2))
    get_success_data(api_client.close_escape(escape["id"], QI2))

    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], line_manager_headers))
    assert aircraft["quality_status"] == "CLEAR", "last open escape closed"
    assert aircraft["production_status"] == "ASSEMBLY_COMPLETE", "production undisturbed"
    assert aircraft["delivery_status"] == "NOT_STARTED"


def test_escape_report_holds_quality_before_production_moves(api, line_manager_headers):
    """PRD §3.6: "the escape lands in `OPEN`, the aircraft's `quality_status` moves
    immediately to `HOLD`, and the program's `open_escape_count` and `posture` are
    recomputed."
    PRD §3.1: "A new unit starts with `production_status` `IN_PRODUCTION`, `quality_status`
    `CLEAR`, `delivery_status` `NOT_STARTED`, a `rework_cost_total_cents` of zero, and a
    null `scheduled_delivery_date` that only a successful delivery negotiation fills."
    PRD §3.4: "the moment every work package of an aircraft — at least one must exist —
    sits in `COMPLETE` or `TRAVELED`, the aircraft's `production_status` bubbles up from
    `IN_PRODUCTION` to `ASSEMBLY_COMPLETE` and the program's `undelivered_inventory_count`
    is recomputed."

    Design: Difficulty/non_linear_state_machine/aircraft_dimensions_production_advances_while_quality_holds
    """
    _program, _customer, aircraft = setup_aircraft(line_number=3007)
    work_package = add_work_package(aircraft["id"], planned_hours=5)
    create_open_escape(aircraft["id"], severity="MAJOR", description="Fastener mismatch")

    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], line_manager_headers))
    assert aircraft["production_status"] == "IN_PRODUCTION", "work package still open"
    assert aircraft["quality_status"] == "HOLD"
    assert aircraft["delivery_status"] == "NOT_STARTED"

    complete_work_package(work_package["id"])
    aircraft = validate_success(api_client.get_aircraft_unit(aircraft["id"], line_manager_headers))
    assert aircraft["production_status"] == "ASSEMBLY_COMPLETE"
    assert aircraft["quality_status"] == "HOLD", "the open escape still holds quality"


def test_disposition_on_closed_escape_by_reporter_reports_state_violation(api):
    """PRD §2.8: "Where several rungs could fire on a single request, the lower-numbered
    rung's error is the one returned."
    PRD §2.8: "5. **State gates** — the requested transition must exist from the resource's
    current state, including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)"
    PRD §2.8: "6. **Safety gates** — regulator notification must precede root-cause work
    (`ERR_REGULATOR_NOTIFICATION_REQUIRED`, 422), and disposition must be segregated from
    reporting (`ERR_SEGREGATION_OF_DUTIES`, 403)."

    Design: Difficulty/priority_pair_validation_conflict/disposition_on_closed_escape_by_reporter_state_beats_segregation
    """
    _program, _customer, aircraft = setup_aircraft(line_number=3005)
    escape = create_closed_escape(
        aircraft["id"], severity="MAJOR", description="Sealant void",
        reporter_id="insp-1", dispositioner_id="insp-2", disposition_code="USE_AS_IS",
    )
    assert escape["status"] == "CLOSED"
    # The reporter (insp-1) attempts a disposition: both the state gate (CLOSED is
    # terminal for disposition) and the segregation rule are violated; the state
    # rung is lower-numbered and wins.
    resp = api_client.disposition_escape(
        escape["id"], disposition_payload("SCRAP"),
        make_quality_inspector_headers("insp-1"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)


def test_disposition_on_open_escape_by_reporter_reports_state_violation(api):
    """PRD §2.8: "Where several rungs could fire on a single request, the lower-numbered
    rung's error is the one returned."
    PRD §3.6: "Disposition (`ROOT_CAUSE` → `DISPOSITIONED`) is segregated from reporting:
    the acting inspector's `X-User-ID` must differ from the escape's `reported_by_id`, and
    a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.8: "5. **State gates** — the requested transition must exist from the resource's
    current state, including terminal-state lockdown and the delivery-pipeline stage gates
    (`ERR_INVALID_TRANSITION`, 409)"

    Design: Difficulty/priority_pair_validation_conflict/disposition_on_closed_escape_by_reporter_state_beats_segregation
    """
    _program, _customer, aircraft = setup_aircraft(line_number=3008)
    escape = create_open_escape(
        aircraft["id"], severity="MAJOR", description="Dent", reporter_id="insp-1"
    )
    assert escape["status"] == "OPEN"
    # OPEN has no disposition transition (ROOT_CAUSE -> DISPOSITIONED only), and the
    # actor is the reporter: state gate (rung 5) precedes segregation (rung 6).
    resp = api_client.disposition_escape(
        escape["id"], disposition_payload("REWORK"),
        make_quality_inspector_headers("insp-1"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION)
