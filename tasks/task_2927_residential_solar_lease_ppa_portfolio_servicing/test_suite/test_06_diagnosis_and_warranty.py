"""Field diagnosis, cost allocation and the manufacturer warranty chain.

Closing out a dispatch is the single event that decides who pays for the visit,
whether the outage was excused, and whether a manufacturer may be billed at all;
the warranty claim that follows re-points that ownership exactly once.
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
    assert_credit_counters,
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
    make_claim,
    make_homeowner,
    make_tariff,
    open_outage,
    read_agreement,
    record_period,
    set_clock,
    submit_claim,
    triage,
)


def _active_ppa(api, clock):
    """An ACTIVE PPA on the standard pinned terms, with the clock already set."""
    set_clock(api, clock)
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(api, owner["id"], schedule["id"])
    activate(api, agreement["id"])
    return agreement


def _dispatched(api, agreement_id, detected_at, window_start, window_end, **roll):
    """Open an alarm, triage it, and send the first coordinator's technician."""
    event = triage(api, open_outage(api, agreement_id, detected_at)["id"])
    roll = dispatch(api, event, window_start, window_end, U.ops_headers(U.OPS_1), **roll)
    return event, roll


def _read_event(api, outage_event_id):
    return validate_success(
        api.get_outage_event(outage_event_id, U.ops_headers()), 200
    )


def _read_roll(api, truck_roll_id):
    return validate_success(api.get_truck_roll(truck_roll_id, U.ops_headers()), 200)


def _read_claim(api, warranty_claim_id):
    return validate_success(
        api.get_warranty_claim(warranty_claim_id, U.ops_headers()), 200
    )


def test_a_no_access_visit_bills_the_homeowner_and_hands_the_alarm_back(api):
    """Nobody got on site, so nothing was diagnosed and nothing was excused.

    §3.6: "A visit that could not get on site moves the roll `SCHEDULED →
    NO_ACCESS` instead. Its `completed_at` is stamped with the current clock
    instant, its `billable_to` is set to `HOMEOWNER` and its `labor_cost_cents` to
    12500 — a flat one-hundred-and-twenty-five-dollar no-access fee — while
    `diagnosed_by_user_id` stays null because nothing was diagnosed." §3.6: "The
    linked alarm falls back `DISPATCHED → TRIAGED` so that it can be dispatched
    again, meaning it never leaves the open set: `resolved_at` stays null, `excused`
    stays false, the agreement's `open_outage_count` is unchanged and its
    `excused_downtime_minutes` gains nothing".

    Design: Corner/state_machines/no_access_completion_returns_the_outage_to_triaged_and_bills_the_homeowner
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    event, roll = _dispatched(
        api,
        agreement["id"],
        "2026-07-30T00:00:00Z",
        "2026-08-01T09:00:00Z",
        "2026-08-01T13:00:00Z",
    )
    assert roll["dispatched_by_user_id"] == U.OPS_1

    closed = complete_roll(api, roll["id"], C.DISPOSITION_NO_ACCESS)

    assert closed["status"] == C.ROLL_NO_ACCESS
    assert closed["billable_to"] == C.BILLABLE_HOMEOWNER
    assert closed["labor_cost_cents"] == C.LABOR_NO_ACCESS_CENTS
    assert closed["root_cause"] is None
    assert closed["diagnosed_by_user_id"] is None
    assert closed["dispatched_by_user_id"] == U.OPS_1
    assert_instant_equals(closed["completed_at"], "2026-08-01T00:00:00Z")

    handed_back = _read_event(api, event["id"])
    assert handed_back["status"] == C.OUTAGE_TRIAGED
    assert handed_back["resolved_at"] is None
    assert handed_back["excused"] is False

    settled = read_agreement(api, agreement["id"])
    assert_monitoring_counters(settled, open_count=1, excused_minutes=0)
    assert_state_dimensions(
        settled,
        lifecycle_state=C.LIFECYCLE_ACTIVE,
        monitoring_status=C.MONITORING_OUTAGE_OPEN,
    )

    again = dispatch(
        api,
        handed_back,
        "2026-08-04T09:00:00Z",
        "2026-08-04T13:00:00Z",
        U.ops_headers(U.OPS_1),
    )
    assert again["status"] == C.ROLL_SCHEDULED
    assert _read_event(api, event["id"])["status"] == C.OUTAGE_DISPATCHED
    assert (
        read_agreement(api, agreement["id"])["monitoring_status"]
        == C.MONITORING_TRUCK_ROLL_DISPATCHED
    )


def test_an_inverter_fault_costs_52000_cents_and_excuses_nothing(api):
    """The manufacturer-owned cause resolves the alarm without excusing it.

    §3.6: "`INVERTER_FAULT` and `MODULE_DEFECT` both set `billable_to` to
    `PENDING_MANUFACTURER` with `labor_cost_cents` of 52000 and leave the outage
    unexcused". §3.6: "When — and only when — `excused` came out true, the
    agreement's `excused_downtime_minutes` is increased by that event's
    `downtime_minutes`."

    Design: Corner/calculations/inverter_fault_completion_applies_the_manufacturer_labor_constant
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    event, roll = _dispatched(
        api,
        agreement["id"],
        "2026-07-30T00:00:00Z",
        "2026-07-31T09:00:00Z",
        "2026-07-31T13:00:00Z",
    )

    closed = complete_roll(
        api, roll["id"], C.DISPOSITION_SERVICE_COMPLETE, C.CAUSE_INVERTER_FAULT
    )

    assert closed["status"] == C.ROLL_COMPLETED
    assert closed["root_cause"] == C.CAUSE_INVERTER_FAULT
    assert closed["billable_to"] == C.BILLABLE_PENDING_MANUFACTURER
    assert closed["labor_cost_cents"] == C.LABOR_MANUFACTURER_CENTS
    assert closed["diagnosed_by_user_id"] == U.OPS_2
    assert_instant_equals(closed["completed_at"], "2026-08-01T00:00:00Z")

    resolved = _read_event(api, event["id"])
    assert resolved["status"] == C.OUTAGE_RESOLVED
    assert_instant_equals(resolved["resolved_at"], "2026-08-01T00:00:00Z")
    assert resolved["downtime_minutes"] == 2880
    assert resolved["excused"] is False
    assert resolved["severity"] == C.SEVERITY_MEDIUM

    settled = read_agreement(api, agreement["id"])
    assert_monitoring_counters(settled, open_count=0, excused_minutes=0)
    assert settled["monitoring_status"] == C.MONITORING_OK


def _claimable_roll(api, agreement_id, cause, detected_at, window_start, window_end,
                    technician_code="TECH-4471"):
    """A COMPLETED roll left in `PENDING_MANUFACTURER` by the named cause."""
    _, roll = _dispatched(
        api,
        agreement_id,
        detected_at,
        window_start,
        window_end,
        technician_code=technician_code,
    )
    return complete_roll(api, roll["id"], C.DISPOSITION_SERVICE_COMPLETE, cause)


def test_a_claim_one_day_past_the_inverter_window_may_not_be_submitted(api):
    """Ten years less a day from an August install closes the window on 31 July.

    §3.6: "`warranty_expires_on` is the `component_install_date` advanced by that
    many years and then pulled back one day, so the expiry date itself is still
    inside the window." §3.6: "Both paths refuse a claim whose warranty window has
    closed: if the current clock date is strictly after `warranty_expires_on`, the
    submission is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`."

    Design: Corner/validations/warranty_claim_submitted_one_day_after_the_inverter_window_is_rejected
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    roll = _claimable_roll(
        api,
        agreement["id"],
        C.CAUSE_INVERTER_FAULT,
        "2026-07-30T00:00:00Z",
        "2026-07-31T09:00:00Z",
        "2026-07-31T13:00:00Z",
    )

    claim = make_claim(
        api,
        roll["id"],
        component_type=C.COMPONENT_INVERTER,
        component_install_date="2016-08-01",
    )
    assert claim["warranty_term_years"] == 10
    assert claim["warranty_expires_on"] == "2026-07-31"
    assert claim["status"] == C.CLAIM_DRAFT
    assert claim["revision_count"] == 0
    assert claim["submitted_by_user_id"] is None
    assert claim["approved_amount_cents"] is None

    validate_error(
        api.submit_warranty_claim(claim["id"], U.ops_headers(U.OPS_1)),
        E.ERR_WARRANTY_WINDOW_EXPIRED,
        422,
    )

    unchanged = _read_claim(api, claim["id"])
    assert unchanged["status"] == C.CLAIM_DRAFT
    assert unchanged["submitted_by_user_id"] is None


def test_the_expiry_date_itself_is_still_inside_the_window(api):
    """One day later on the install date buys the whole claim, and modules get 25 years.

    §3.6: "`warranty_term_years` is 25 for a `MODULE` claim, running against the
    module manufacturer's twenty-five-year warranty, and 10 for an `INVERTER`
    claim". §3.6: "A `DRAFT` claim moves `DRAFT → SUBMITTED`, stamping
    `submitted_by_user_id` with the acting `X-User-ID`."

    Design: Corner/validations/warranty_claim_submitted_one_day_after_the_inverter_window_is_rejected
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    inverter_roll = _claimable_roll(
        api,
        agreement["id"],
        C.CAUSE_INVERTER_FAULT,
        "2026-07-30T00:00:00Z",
        "2026-07-31T09:00:00Z",
        "2026-07-31T13:00:00Z",
    )
    module_roll = _claimable_roll(
        api,
        agreement["id"],
        C.CAUSE_MODULE_DEFECT,
        "2026-07-31T00:00:00Z",
        "2026-07-31T14:00:00Z",
        "2026-07-31T18:00:00Z",
        technician_code="TECH-5500",
    )

    inverter_claim = make_claim(
        api,
        inverter_roll["id"],
        component_type=C.COMPONENT_INVERTER,
        component_install_date="2016-08-02",
    )
    assert inverter_claim["warranty_term_years"] == 10
    assert inverter_claim["warranty_expires_on"] == "2026-08-01"

    submitted = submit_claim(api, inverter_claim["id"])
    assert submitted["status"] == C.CLAIM_SUBMITTED
    assert submitted["revision_count"] == 0
    assert submitted["submitted_by_user_id"] == U.OPS_1
    assert submitted["decided_by_user_id"] is None

    module_claim = make_claim(
        api,
        module_roll["id"],
        component_type=C.COMPONENT_MODULE,
        component_install_date="2016-08-01",
    )
    assert module_claim["warranty_term_years"] == 25
    assert module_claim["warranty_expires_on"] == "2041-07-31"
    assert module_claim["agreement_id"] == agreement["id"]


def test_an_operator_owned_cause_is_never_claimable_against_a_manufacturer(api):
    """A string fault is Sunrun's own bill, so no manufacturer claim may open.

    §3.6: "`STRING_FAULT` and `COMMS_ONLY` both set `billable_to` to `SUNRUN_OM`
    with `labor_cost_cents` of 38000 and mark the outage excused, because those two
    causes are the operator's own". §3.6: "Four separate conditions make a roll
    claimable, and failing any one of them yields `ERR_TRUCK_ROLL_NOT_CLAIMABLE`:
    the roll's `status` must be `COMPLETED`; its `root_cause` must be
    `INVERTER_FAULT` or `MODULE_DEFECT`; the claim's `component_type` must agree
    with that cause, so a `MODULE` claim requires `MODULE_DEFECT` and an `INVERTER`
    claim requires `INVERTER_FAULT`; and no claim that is not `DENIED` may already
    exist against that roll."

    Design: Corner/validations/warranty_claim_on_a_roll_that_is_not_manufacturer_owned_is_rejected
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    roll = _claimable_roll(
        api,
        agreement["id"],
        C.CAUSE_STRING_FAULT,
        "2026-07-30T00:00:00Z",
        "2026-07-31T09:00:00Z",
        "2026-07-31T13:00:00Z",
    )
    assert roll["billable_to"] == C.BILLABLE_SUNRUN_OM
    assert roll["labor_cost_cents"] == C.LABOR_OM_CENTS

    validate_error(
        api.create_warranty_claim(
            F.warranty_claim_payload(
                roll["id"], component_type=C.COMPONENT_INVERTER
            ),
            U.ops_headers(U.OPS_1),
        ),
        E.ERR_TRUCK_ROLL_NOT_CLAIMABLE,
        422,
    )

    unchanged = _read_roll(api, roll["id"])
    assert unchanged["billable_to"] == C.BILLABLE_SUNRUN_OM
    assert unchanged["labor_cost_cents"] == C.LABOR_OM_CENTS

    rows, meta = validate_paginated(api.list_warranty_claims(U.ops_headers()))
    assert rows == []
    assert meta["total_count"] == 0


def test_an_unfinished_visit_and_a_mismatched_component_are_both_unclaimable(api):
    """Status, cause and component all have to line up before a claim exists.

    §3.6: "Four separate conditions make a roll claimable, and failing any one of
    them yields `ERR_TRUCK_ROLL_NOT_CLAIMABLE`: the roll's `status` must be
    `COMPLETED`; its `root_cause` must be `INVERTER_FAULT` or `MODULE_DEFECT`; the
    claim's `component_type` must agree with that cause, so a `MODULE` claim
    requires `MODULE_DEFECT` and an `INVERTER` claim requires `INVERTER_FAULT`; and
    no claim that is not `DENIED` may already exist against that roll." §3.6: "Only
    the two manufacturer-owned causes are claimable against a manufacturer, and only
    they leave `billable_to` in the `PENDING_MANUFACTURER` state that a warranty
    decision is later allowed to move."

    Design: Corner/validations/warranty_claim_on_a_roll_that_is_not_manufacturer_owned_is_rejected
    """
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    _, scheduled = _dispatched(
        api,
        agreement["id"],
        "2026-07-30T00:00:00Z",
        "2026-07-31T09:00:00Z",
        "2026-07-31T13:00:00Z",
    )
    assert scheduled["status"] == C.ROLL_SCHEDULED
    assert scheduled["billable_to"] is None
    assert scheduled["labor_cost_cents"] == 0

    validate_error(
        api.create_warranty_claim(
            F.warranty_claim_payload(
                scheduled["id"], component_type=C.COMPONENT_INVERTER
            ),
            U.ops_headers(U.OPS_1),
        ),
        E.ERR_TRUCK_ROLL_NOT_CLAIMABLE,
        422,
    )

    completed = _claimable_roll(
        api,
        agreement["id"],
        C.CAUSE_INVERTER_FAULT,
        "2026-07-31T00:00:00Z",
        "2026-07-31T14:00:00Z",
        "2026-07-31T18:00:00Z",
        technician_code="TECH-5500",
    )
    assert completed["billable_to"] == C.BILLABLE_PENDING_MANUFACTURER

    validate_error(
        api.create_warranty_claim(
            F.warranty_claim_payload(
                completed["id"], component_type=C.COMPONENT_MODULE
            ),
            U.ops_headers(U.OPS_1),
        ),
        E.ERR_TRUCK_ROLL_NOT_CLAIMABLE,
        422,
    )

    accepted = make_claim(
        api, completed["id"], component_type=C.COMPONENT_INVERTER
    )
    assert accepted["status"] == C.CLAIM_DRAFT
    assert accepted["truck_roll_id"] == completed["id"]

    _, meta = validate_paginated(api.list_warranty_claims(U.ops_headers()))
    assert meta["total_count"] == 1


def _submitted_claim_for_52000(api):
    """A SUBMITTED 52000-cent inverter claim on a manufacturer-owned roll."""
    agreement = _active_ppa(api, "2026-08-01T00:00:00Z")
    roll = _claimable_roll(
        api,
        agreement["id"],
        C.CAUSE_INVERTER_FAULT,
        "2026-07-30T00:00:00Z",
        "2026-07-31T09:00:00Z",
        "2026-07-31T13:00:00Z",
    )
    claim = make_claim(
        api,
        roll["id"],
        component_type=C.COMPONENT_INVERTER,
        component_install_date="2020-06-01",
        claim_amount_cents=52000,
    )
    return roll, submit_claim(api, claim["id"])


def test_one_cent_over_the_claim_is_refused_and_the_exact_amount_is_allowed(api):
    """The bound is strictly greater, and only the approval re-points the roll.

    §3.6: "An approval carries `approved_amount_cents`, the amount the manufacturer
    allowed, which may equal but may not exceed `claim_amount_cents`; a larger
    figure is rejected with `ERR_APPROVED_AMOUNT_EXCEEDS_CLAIM`." §3.6: "Approval
    moves the claim `SUBMITTED → APPROVED`, stores the allowed amount, stamps
    `decided_by_user_id`, and re-points the linked roll's `billable_to` from
    `PENDING_MANUFACTURER` to `WARRANTY`."

    Design: Corner/validations/approving_more_than_the_claim_amount_is_rejected_while_the_exact_amount_passes
    """
    roll, claim = _submitted_claim_for_52000(api)
    assert claim["claim_amount_cents"] == 52000
    assert claim["submitted_by_user_id"] == U.OPS_1

    validate_error(
        api.approve_warranty_claim(
            claim["id"], {"approved_amount_cents": 52001}, U.ops_headers(U.OPS_2)
        ),
        E.ERR_APPROVED_AMOUNT_EXCEEDS_CLAIM,
        422,
    )

    still_submitted = _read_claim(api, claim["id"])
    assert still_submitted["status"] == C.CLAIM_SUBMITTED
    assert still_submitted["approved_amount_cents"] is None
    assert still_submitted["decided_by_user_id"] is None
    assert _read_roll(api, roll["id"])["billable_to"] == C.BILLABLE_PENDING_MANUFACTURER
    assert _read_roll(api, roll["id"])["labor_cost_cents"] == C.LABOR_MANUFACTURER_CENTS

    approved = validate_success(
        api.approve_warranty_claim(
            claim["id"], {"approved_amount_cents": 52000}, U.ops_headers(U.OPS_2)
        ),
        200,
    )
    assert approved["status"] == C.CLAIM_APPROVED
    assert approved["approved_amount_cents"] == 52000
    assert approved["decided_by_user_id"] == U.OPS_2

    repointed = _read_roll(api, roll["id"])
    assert repointed["billable_to"] == C.BILLABLE_WARRANTY
    assert repointed["labor_cost_cents"] == C.LABOR_MANUFACTURER_CENTS


NOTES = [
    "Send the inverter event log for 2026-08-04.",
    "Log is truncated; resend the full day.",
    "Attach the replacement invoice.",
    "One more time: itemise the labour.",
]


def _claim_ready_for_questions(api):
    """A DRAFT inverter claim whose window stays open for the whole cycle."""
    agreement = _active_ppa(api, "2026-08-05T00:00:00Z")
    roll = _claimable_roll(
        api,
        agreement["id"],
        C.CAUSE_INVERTER_FAULT,
        "2026-08-03T00:00:00Z",
        "2026-08-04T09:00:00Z",
        "2026-08-04T13:00:00Z",
    )
    claim = make_claim(
        api,
        roll["id"],
        component_type=C.COMPONENT_INVERTER,
        component_install_date="2019-05-20",
    )
    return roll, claim


def _ask_for_information(api, claim_id, note):
    """The adjuster's question comes from the second coordinator."""
    return validate_success(
        api.request_claim_info(
            claim_id, F.info_request_payload(note), U.ops_headers(U.OPS_2)
        ),
        200,
    )


def test_each_resubmission_increments_the_counter_and_clears_the_question(api):
    """The cycle runs three times and only the re-submissions are counted.

    §3.6: "An adjuster's question is recorded by a `FieldOpsCoordinator` or
    `PortfolioAdmin`, moving the claim `SUBMITTED → INFO_REQUESTED` and storing the
    mandatory `info_request_note` (between 1 and 500 characters) that explains what
    is required." §3.6: "A claim that came back with questions moves
    `INFO_REQUESTED → SUBMITTED`, incrementing `revision_count` by one, re-stamping
    `submitted_by_user_id`, and clearing `info_request_note` back to null."

    Design: Difficulty/non_linear_state_machine/warranty_claim_info_request_cycle_capped_at_three_revisions
    """
    _, claim = _claim_ready_for_questions(api)
    assert claim["warranty_term_years"] == 10
    assert claim["warranty_expires_on"] == "2029-05-19"
    assert claim["revision_count"] == 0
    assert claim["info_request_note"] is None

    first = submit_claim(api, claim["id"])
    assert first["status"] == C.CLAIM_SUBMITTED
    assert first["revision_count"] == 0
    assert first["submitted_by_user_id"] == U.OPS_1

    for expected_count, note in enumerate(NOTES[:3], start=1):
        asked = _ask_for_information(api, claim["id"], note)
        assert asked["status"] == C.CLAIM_INFO_REQUESTED
        assert asked["info_request_note"] == note
        assert asked["revision_count"] == expected_count - 1

        resubmitted = submit_claim(api, claim["id"])
        assert resubmitted["status"] == C.CLAIM_SUBMITTED
        assert resubmitted["revision_count"] == expected_count
        assert resubmitted["info_request_note"] is None
        assert resubmitted["submitted_by_user_id"] == U.OPS_1

    assert _read_claim(api, claim["id"])["revision_count"] == C.CLAIM_REVISION_LIMIT


def test_the_fourth_resubmission_is_capped_and_leaves_the_question_standing(api):
    """Termination is a counter, not a state, so the claim stays INFO_REQUESTED.

    §3.6: "The revision path is additionally capped — a claim sitting in
    `INFO_REQUESTED` whose `revision_count` has already reached 3 cannot be
    re-submitted, and the attempt is rejected with `ERR_CLAIM_REVISION_LIMIT`."
    §3.6: "Nothing re-points a second time, `labor_cost_cents` is never re-priced by
    a warranty decision, and the outage's `excused` flag is never revised by one
    either."

    Design: Difficulty/non_linear_state_machine/warranty_claim_info_request_cycle_capped_at_three_revisions
    """
    roll, claim = _claim_ready_for_questions(api)
    submit_claim(api, claim["id"])
    for note in NOTES[:3]:
        _ask_for_information(api, claim["id"], note)
        submit_claim(api, claim["id"])

    fourth_question = _ask_for_information(api, claim["id"], NOTES[3])
    assert fourth_question["status"] == C.CLAIM_INFO_REQUESTED
    assert fourth_question["revision_count"] == 3

    validate_error(
        api.submit_warranty_claim(claim["id"], U.ops_headers(U.OPS_1)),
        E.ERR_CLAIM_REVISION_LIMIT,
        422,
    )

    stuck = _read_claim(api, claim["id"])
    assert stuck["status"] == C.CLAIM_INFO_REQUESTED
    assert stuck["revision_count"] == 3
    assert stuck["info_request_note"] == NOTES[3]
    assert stuck["approved_amount_cents"] is None
    assert stuck["decided_by_user_id"] is None

    untouched = _read_roll(api, roll["id"])
    assert untouched["billable_to"] == C.BILLABLE_PENDING_MANUFACTURER
    assert untouched["labor_cost_cents"] == C.LABOR_MANUFACTURER_CENTS


def _lease_with_an_excused_string_fault(api):
    """A LEASE whose four-day July outage is closed out as the operator's own."""
    set_clock(api, "2026-07-05T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_lease(
        api, owner["id"], schedule["id"], site_address="14 Quail Rd, Fremont, CA"
    )
    activate(api, agreement["id"])
    event, roll = _dispatched(
        api,
        agreement["id"],
        "2026-07-05T00:00:00Z",
        "2026-07-08T09:00:00Z",
        "2026-07-08T13:00:00Z",
    )
    set_clock(api, "2026-07-09T00:00:00Z")
    closed = complete_roll(
        api, roll["id"], C.DISPOSITION_SERVICE_COMPLETE, C.CAUSE_STRING_FAULT
    )
    return owner, schedule, agreement, event, closed


def test_one_closeout_moves_the_roll_the_alarm_and_the_agreement_together(api):
    """Three levels of the cascade fall out of a single completion call.

    §3.6: "The linked alarm moves `DISPATCHED → RESOLVED`: its `resolved_at` is
    stamped with the same clock instant, its `downtime_minutes` is frozen at the
    whole minutes between `detected_at` and `resolved_at`, and its `excused` flag is
    set to true when the diagnosed `root_cause` is `STRING_FAULT` or `COMMS_ONLY`
    and to false for every other cause." §3.6: "The agreement's `open_outage_count`
    is decremented and its `monitoring_status` re-derived, which takes it
    `TRUCK_ROLL_DISPATCHED → MONITORING_OK` once the count reaches 0".

    Design: Difficulty/transitive_cascade/truck_roll_completion_cascades_to_excused_production_month
    """
    _, _, agreement, event, closed = _lease_with_an_excused_string_fault(api)

    assert closed["status"] == C.ROLL_COMPLETED
    assert closed["billable_to"] == C.BILLABLE_SUNRUN_OM
    assert closed["labor_cost_cents"] == C.LABOR_OM_CENTS
    assert closed["diagnosed_by_user_id"] == U.OPS_2
    assert closed["dispatched_by_user_id"] == U.OPS_1
    assert_instant_equals(closed["completed_at"], "2026-07-09T00:00:00Z")

    resolved = _read_event(api, event["id"])
    assert resolved["status"] == C.OUTAGE_RESOLVED
    assert_instant_equals(resolved["resolved_at"], "2026-07-09T00:00:00Z")
    assert resolved["downtime_minutes"] == 5760
    assert resolved["excused"] is True
    assert resolved["severity"] == C.SEVERITY_MEDIUM

    settled = read_agreement(api, agreement["id"])
    assert_monitoring_counters(settled, open_count=0, excused_minutes=5760)
    assert_state_dimensions(
        settled,
        lifecycle_state=C.LIFECYCLE_ACTIVE,
        monitoring_status=C.MONITORING_OK,
        service_status=C.SERVICE_IN_SERVICE,
    )


def test_the_excused_outage_then_pro_rates_july_and_shrinks_the_credit(api):
    """The fourth level: 5760 excused minutes cost four whole days of expectation.

    §3.3: "every outage event on the agreement whose `status` is `RESOLVED` and
    whose `excused` flag is true contributes the half-open instant interval from its
    `detected_at` up to but not including its `resolved_at`". §3.3: "`excused_days`
    is then the smaller of two figures: the number of calendar days in the period
    month, and the roof-day count plus the outage minutes converted to days by
    dividing by 1440 and rounding **up** to a whole day."

    Design: Difficulty/transitive_cascade/truck_roll_completion_cascades_to_excused_production_month
    """
    owner, schedule, agreement, _, _ = _lease_with_an_excused_string_fault(api)
    set_clock(api, "2026-08-01T00:00:00Z")

    july = record_period(
        api,
        agreement["id"],
        2026,
        7,
        760,
        auto_reconcile=True,
        auto_issue_credit=True,
    )

    assert july["contract_year"] == 2
    assert july["due_date"] == "2026-08-21"
    assert july["gross_expected_kwh"] == 949
    assert july["excused_days"] == 4
    assert july["adjusted_expected_kwh"] == 827
    assert july["guarantee_floor_kwh"] == 786
    assert july["shortfall_kwh"] == 26
    assert july["credit_rate_millicents"] == 32500
    assert july["credit_cents"] == 845
    assert july["escalated_monthly_rent_cents"] == 13145
    assert july["escalated_rate_millicents"] == 0
    assert july["gross_due_cents"] == 13145
    assert july["credit_applied_cents"] == 0
    assert july["net_due_cents"] == 13145
    assert july["late_fee_cents"] == 0
    assert july["total_invoiced_cents"] == 13145
    assert july["status"] == C.PERIOD_CREDIT_ISSUED

    assert_credit_counters(
        read_agreement(api, agreement["id"]), earned=845, applied=0, balance=845
    )

    # The same month on an identical site that never had an excused outage.
    twin = book_lease(
        api, owner["id"], schedule["id"], site_address="16 Quail Rd, Fremont, CA"
    )
    activate(api, twin["id"])
    unexcused = record_period(
        api, twin["id"], 2026, 7, 760, auto_reconcile=True, auto_issue_credit=True
    )

    assert unexcused["gross_expected_kwh"] == 949
    assert unexcused["excused_days"] == 0
    assert unexcused["adjusted_expected_kwh"] == 949
    assert unexcused["guarantee_floor_kwh"] == 902
    assert unexcused["shortfall_kwh"] == 142
    assert unexcused["credit_cents"] == 4615
