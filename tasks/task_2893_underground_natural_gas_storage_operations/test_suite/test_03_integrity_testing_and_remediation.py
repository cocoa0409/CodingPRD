"""Mechanical integrity testing, the three asymmetric outcomes, remediation and
the service-state edges that integrity work leaves behind."""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_INVALID_WELL_STATE,
    ERR_MIT_WINDOW_CONFLICT,
    ERR_MIT_WINDOW_IN_PAST,
    ERR_MIT_WINDOW_NOT_ELAPSED,
)
from test_helpers.assertions import (
    assert_created,
    assert_error_envelope,
    assert_field_derived_block,
    assert_instant_equals,
    assert_ledger_entry,
    assert_ok,
)
from test_helpers.constants import (
    DIRECTION_INJECTION,
    INTEGRITY_MIT_CURRENT,
    INTEGRITY_MIT_DUE,
    INTEGRITY_MIT_FAILED,
    INTEGRITY_REMEDIATED,
    LEDGER_CURTAILMENT_CREDIT,
    MIT_FAILED,
    MIT_OUTCOME_FAIL,
    MIT_OUTCOME_INCONCLUSIVE,
    MIT_OUTCOME_PASS,
    MIT_PASSED,
    MIT_SCHEDULED,
    MIT_TEST_TYPE_NOISE_LOG,
    MIT_TEST_TYPE_TEMPERATURE_LOG,
    NOMINATION_CONFIRMED,
    NOMINATION_CURTAILED,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    REMEDIATION_COMPLETED,
    REMEDIATION_OPEN,
    SERVICE_CLASS_FIRM,
    SERVICE_CLASS_INTERRUPTIBLE,
    SHUT_IN_REASON_MIT_FAILURE,
    SHUT_IN_REASON_OPERATOR_REQUEST,
    TICKET_PENDING,
    WELL_IN_SERVICE,
    WELL_PLUGGED,
    WELL_SHUT_IN,
)
from test_helpers.fixtures import (
    build_mini_world,
    confirmed_nomination,
    create_active_contract,
    create_field,
    create_shipper,
    create_std_field,
    create_well,
    fail_mit_on_well,
    ledger_entries,
    only_program_on_well,
    open_ticket,
    read_contract,
    read_field,
    read_nomination,
    read_ticket,
    read_well,
    record_mit,
    remediate_well,
    schedule_mit,
    set_clock,
)
from test_helpers.test_users import (
    FIELD_OPERATOR,
    INTEGRITY_ENGINEER,
    INTEGRITY_ENGINEER_B,
    STAFF_USER_IDS,
    make_shipper_headers,
)


class TestIntegrityTestOutcomes:
    """The three outcomes a recorded test can carry, and their side effects."""

    def test_a_passing_test_refreshes_the_cycle_from_the_recorded_instant(self, api):
        """A wellbore born overdue is lifted back to current by a pass, whose
        recorded instant — not the booked window — anchors the new 365-day deadline
        and refreshes the casing pressure.

        PRD §3.2: "The wellbore's `last_mit_passed_at` is set to the test's
        `recorded_at`, its `mit_due_at` is recomputed as that instant plus 365
        days, and its `casing_pressure_psig` is refreshed to the recorded
        `result_pressure_psig`."

        Design: Corner/state_machines/mit_pass_refreshes_the_due_date_and_lifts_the_well_out_of_mit_due
        """
        field = create_field(api)
        well = create_well(
            api, field["id"], well_name="MINI-1",
            last_mit_passed_at="2025-07-01T00:00:00Z",
        )
        assert well["integrity_state"] == INTEGRITY_MIT_DUE
        test = schedule_mit(
            api, well["id"],
            scheduled_start_at="2026-08-01T06:00:00Z",
            scheduled_end_at="2026-08-01T18:00:00Z",
        )
        set_clock(api, "2026-08-02T00:00:00Z")

        recorded = assert_ok(
            api.record_mit_result(
                test["id"], F.mit_result_payload(MIT_OUTCOME_PASS, 1450), INTEGRITY_ENGINEER
            )
        )
        assert recorded["status"] == MIT_PASSED
        assert recorded["outcome"] == MIT_OUTCOME_PASS
        assert recorded["result_pressure_psig"] == 1450
        assert recorded["recorded_by_user_id"] == STAFF_USER_IDS["IntegrityEngineer"]
        assert_instant_equals(recorded["recorded_at"], "2026-08-02T00:00:00Z")

        after = read_well(api, well["id"], INTEGRITY_ENGINEER)
        assert after["integrity_state"] == INTEGRITY_MIT_CURRENT
        assert_instant_equals(after["last_mit_passed_at"], "2026-08-02T00:00:00Z")
        assert_instant_equals(after["mit_due_at"], "2027-08-02T00:00:00Z")
        assert after["casing_pressure_psig"] == 1450
        assert after["operational_state"] == WELL_IN_SERVICE
        assert after["shut_in_reason"] is None
        assert after["service_change_count"] == 0

        assert_field_derived_block(
            read_field(api, field["id"]),
            posture=POSTURE_OPEN, withdrawal_rate=150000, injection_rate=150000,
        )

    def test_an_inconclusive_test_closes_failed_but_cascades_nothing(self, api):
        """An inconclusive log closes the test as FAILED yet leaves both wellbore
        dimensions, the 365-day deadline, the casing pressure and the reservoir
        exactly as they were, and opens no remediation program.

        PRD §3.2: "The test still closes at `status` `FAILED`, but with `outcome`
        `INCONCLUSIVE`: no remediation program is created, the wellbore is not shut
        in, and neither of its state dimensions changes."

        Design: Corner/state_machines/mit_inconclusive_closes_the_test_and_touches_neither_well_dimension
        """
        field = create_field(api)
        well = create_well(
            api, field["id"], well_name="MINI-1",
            last_mit_passed_at="2026-06-01T00:00:00Z",
        )
        test = schedule_mit(
            api, well["id"],
            test_type=MIT_TEST_TYPE_NOISE_LOG,
            scheduled_start_at="2026-08-01T06:00:00Z",
            scheduled_end_at="2026-08-01T18:00:00Z",
        )
        set_clock(api, "2026-08-02T00:00:00Z")

        recorded = record_mit(api, test["id"], MIT_OUTCOME_INCONCLUSIVE, 900)
        assert recorded["status"] == MIT_FAILED
        assert recorded["outcome"] == MIT_OUTCOME_INCONCLUSIVE
        assert recorded["result_pressure_psig"] == 900
        assert_instant_equals(recorded["recorded_at"], "2026-08-02T00:00:00Z")
        assert recorded["recorded_by_user_id"] == STAFF_USER_IDS["IntegrityEngineer"]

        after = read_well(api, well["id"], INTEGRITY_ENGINEER)
        assert after["integrity_state"] == INTEGRITY_MIT_CURRENT
        assert after["operational_state"] == WELL_IN_SERVICE
        assert after["shut_in_reason"] is None
        assert after["service_change_count"] == 0
        assert_instant_equals(after["last_mit_passed_at"], "2026-06-01T00:00:00Z")
        assert_instant_equals(after["mit_due_at"], "2027-06-01T00:00:00Z")
        assert after["casing_pressure_psig"] == 0

        _, meta = validate_paginated(
            api.list_remediation_programs(
                INTEGRITY_ENGINEER, {"well_id": well["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 0, "an inconclusive log opens no remediation program"
        assert_field_derived_block(
            read_field(api, field["id"]),
            posture=POSTURE_OPEN, wells_in_service=1,
            withdrawal_rate=150000, injection_rate=150000,
        )

    def test_the_window_gates_sit_on_opposite_endpoints_with_an_inclusive_end(self, api):
        """Booking a window that has already begun is refused at 422, recording a
        result before the window has elapsed is refused at 409, and a clock landing
        exactly on the window's end admits the result.

        PRD §2.11 rung 21: "The logical clock has reached or passed a test's
        `scheduled_end_at` before a result may be recorded — otherwise
        `ERR_MIT_WINDOW_NOT_ELAPSED` (409)."

        Design: Corner/state_machines/mit_result_recording_gated_by_the_window_with_an_inclusive_end_boundary
        """
        field = create_field(api)
        well = create_well(api, field["id"], well_name="MINI-1")

        assert_error_envelope(
            api.create_mit(
                F.mit_payload(
                    well["id"],
                    scheduled_start_at="2026-07-31T00:00:00Z",
                    scheduled_end_at="2026-08-01T12:00:00Z",
                ),
                INTEGRITY_ENGINEER,
            ),
            ERR_MIT_WINDOW_IN_PAST,
        )
        _, empty = validate_paginated(
            api.list_mits(INTEGRITY_ENGINEER, {"well_id": well["id"], "limit": 100})
        )
        assert empty["total_count"] == 0, "the refused booking left no test behind"

        booked = assert_created(
            api.create_mit(
                F.mit_payload(
                    well["id"],
                    scheduled_start_at="2026-08-01T06:00:00Z",
                    scheduled_end_at="2026-08-01T18:00:00Z",
                ),
                INTEGRITY_ENGINEER,
            )
        )
        assert booked["status"] == MIT_SCHEDULED
        assert booked["outcome"] is None
        assert booked["result_pressure_psig"] is None
        assert booked["recorded_at"] is None
        assert booked["recorded_by_user_id"] is None

        assert_error_envelope(
            api.record_mit_result(
                booked["id"], F.mit_result_payload(MIT_OUTCOME_PASS, 1200), INTEGRITY_ENGINEER
            ),
            ERR_MIT_WINDOW_NOT_ELAPSED,
        )

        set_clock(api, "2026-08-01T18:00:00Z")
        recorded = assert_ok(
            api.record_mit_result(
                booked["id"], F.mit_result_payload(MIT_OUTCOME_PASS, 1200), INTEGRITY_ENGINEER
            )
        )
        assert recorded["status"] == MIT_PASSED
        assert_instant_equals(recorded["recorded_at"], "2026-08-01T18:00:00Z")

        well_after = read_well(api, well["id"], INTEGRITY_ENGINEER)
        assert_instant_equals(well_after["last_mit_passed_at"], "2026-08-01T18:00:00Z")
        assert_instant_equals(well_after["mit_due_at"], "2027-08-01T18:00:00Z")
        assert well_after["casing_pressure_psig"] == 1200

        _, one = validate_paginated(
            api.list_mits(INTEGRITY_ENGINEER, {"well_id": well["id"], "limit": 100})
        )
        assert one["total_count"] == 1


class TestRemediationClosure:
    """Closing a cascaded program is a half recovery, and it is the only key
    that unlocks the wellbore's return to service."""

    def test_an_independent_engineer_closes_the_program_but_not_the_shut_in(self, api):
        """The program is stamped from the clock at the moment of failure, its
        deadline lands 45 days later, and completion by the second engineer clears
        the integrity failure while deliberately leaving the wellbore shut in.

        PRD §3.2: "The wellbore's integrity dimension moves from `MIT_FAILED` to
        `REMEDIATED` and its `shut_in_reason` is cleared to null — but its
        `operational_state` deliberately stays `SHUT_IN` until an operator performs
        an explicit service change."

        Design: Corner/state_machines/remediation_completion_by_an_independent_engineer_clears_the_failure
        """
        field = create_field(api)
        well = create_well(api, field["id"], well_name="MINI-1")
        create_well(api, field["id"], well_name="MINI-2")
        failure = fail_mit_on_well(
            api, well["id"],
            scheduled_start_at="2026-08-01T06:00:00Z",
            scheduled_end_at="2026-08-02T06:00:00Z",
            record_at="2026-08-02T06:00:00Z",
        )
        program = failure.program

        completed = assert_ok(
            api.complete_remediation_program(
                program["id"],
                F.remediation_completion_payload(
                    "casing patched, retest witnessed by third party"
                ),
                INTEGRITY_ENGINEER_B,
            )
        )
        assert completed["status"] == REMEDIATION_COMPLETED
        assert completed["triggering_mit_id"] == failure.test["id"]
        assert completed["well_id"] == well["id"]
        assert_instant_equals(completed["opened_at"], "2026-08-02T06:00:00Z")
        assert_instant_equals(completed["due_at"], "2026-09-16T06:00:00Z")
        assert completed["completed_by_user_id"] == STAFF_USER_IDS["IntegrityEngineerB"]
        assert_instant_equals(completed["completed_at"], "2026-08-02T06:00:00Z")
        assert completed["verification_notes"] == (
            "casing patched, retest witnessed by third party"
        )

        after = read_well(api, well["id"], INTEGRITY_ENGINEER_B)
        assert after["integrity_state"] == INTEGRITY_REMEDIATED
        assert after["shut_in_reason"] is None
        assert after["operational_state"] == WELL_SHUT_IN
        assert after["service_change_count"] == 0, (
            "an integrity shut-in is not an operator service change"
        )

        assert_field_derived_block(
            read_field(api, field["id"], FIELD_OPERATOR),
            wells_in_service=1, posture=POSTURE_OPEN,
            withdrawal_rate=150000, injection_rate=150000,
        )

        test_row = assert_ok(api.get_mit(failure.test["id"], INTEGRITY_ENGINEER))
        assert test_row["status"] == MIT_FAILED
        assert test_row["outcome"] == MIT_OUTCOME_FAIL
        assert test_row["recorded_by_user_id"] == STAFF_USER_IDS["IntegrityEngineer"]

    def test_return_to_service_waits_for_the_program_and_leaves_remediated_standing(self, api):
        """Both return-to-service guards are violated the instant a test fails and
        both clear together when the program closes; the accepted service change
        then counts once and does not restore a current integrity state.

        PRD §2.11 rung 25: "A wellbore returning to `IN_SERVICE` has
        `integrity_state` other than `MIT_FAILED` and carries no `RemediationProgram`
        in `OPEN` or `ESCALATED` — otherwise `ERR_INVALID_WELL_STATE` (409)."

        Design: Corner/state_machines/well_return_to_service_is_refused_until_the_remediation_program_closes
        """
        field = create_field(api)
        well = create_well(api, field["id"], well_name="MINI-1")
        create_well(api, field["id"], well_name="MINI-2")
        program = fail_mit_on_well(api, well["id"]).program

        assert_error_envelope(
            api.change_well_service(
                well["id"], F.service_change_payload(WELL_IN_SERVICE), FIELD_OPERATOR
            ),
            ERR_INVALID_WELL_STATE,
        )
        refused = read_well(api, well["id"])
        assert refused["operational_state"] == WELL_SHUT_IN
        assert refused["shut_in_reason"] == SHUT_IN_REASON_MIT_FAILURE
        assert refused["service_change_count"] == 0

        remediate_well(api, program["id"], notes="sleeve installed and pressure held")
        returned = assert_ok(
            api.change_well_service(
                well["id"], F.service_change_payload(WELL_IN_SERVICE), FIELD_OPERATOR
            )
        )
        assert returned["operational_state"] == WELL_IN_SERVICE
        assert returned["shut_in_reason"] is None
        assert returned["service_change_count"] == 1
        assert returned["integrity_state"] == INTEGRITY_REMEDIATED, (
            "only a fresh passing test restores MIT_CURRENT"
        )

        assert_field_derived_block(
            read_field(api, field["id"], FIELD_OPERATOR),
            wells_in_service=2, posture=POSTURE_OPEN,
            withdrawal_rate=150000, injection_rate=150000,
        )
        _, meta = validate_paginated(
            api.list_remediation_programs(
                INTEGRITY_ENGINEER,
                {"well_id": well["id"], "status": REMEDIATION_OPEN, "limit": 100},
            )
        )
        assert meta["total_count"] == 0


class TestUndeclaredServiceEdges:
    """Every move the operational dimension does not declare collapses to one
    code, and none of the refusals is counted as a service change."""

    def test_undeclared_service_moves_are_all_refused_without_counting(self, api):
        """A pending movement blocks a shut-in, a booked test blocks a plugging, and
        a plugged wellbore admits nothing at all — four refusals, one error code and
        no drift in either counter or the reservoir block.

        PRD §3.1: "Any other requested move — including `PLUGGED` to anything, or a
        repeat of the current state — is refused with `ERR_INVALID_WELL_STATE`
        (409)."

        Design: Corner/state_machines/well_service_change_edges_that_are_not_declared_are_all_rejected
        """
        world = build_mini_world(api, well_names=["MINI-1", "MINI-2", "MINI-3"])
        w1, w2, w3 = world.wells[0], world.wells[1], world.wells[2]
        nomination = confirmed_nomination(
            api, world.contract_id, world.shipper_id,
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
        )
        assert nomination["status"] == NOMINATION_CONFIRMED
        ticket = open_ticket(api, nomination["id"], w1["id"], 76000)

        assert_error_envelope(
            api.change_well_service(
                w1["id"], F.service_change_payload(WELL_SHUT_IN), FIELD_OPERATOR
            ),
            ERR_INVALID_WELL_STATE,
        )
        w1_after = read_well(api, w1["id"])
        assert w1_after["operational_state"] == WELL_IN_SERVICE
        assert w1_after["service_change_count"] == 0

        shut_in = assert_ok(
            api.change_well_service(
                w2["id"], F.service_change_payload(WELL_SHUT_IN), FIELD_OPERATOR
            )
        )
        assert shut_in["operational_state"] == WELL_SHUT_IN
        schedule_mit(
            api, w2["id"],
            test_type=MIT_TEST_TYPE_TEMPERATURE_LOG,
            scheduled_start_at="2026-08-05T00:00:00Z",
            scheduled_end_at="2026-08-05T06:00:00Z",
        )
        assert_error_envelope(
            api.change_well_service(
                w2["id"], F.service_change_payload(WELL_PLUGGED), FIELD_OPERATOR
            ),
            ERR_INVALID_WELL_STATE,
        )
        w2_after = read_well(api, w2["id"])
        assert w2_after["operational_state"] == WELL_SHUT_IN
        assert w2_after["shut_in_reason"] == SHUT_IN_REASON_OPERATOR_REQUEST
        assert w2_after["service_change_count"] == 1

        assert_ok(
            api.change_well_service(
                w3["id"], F.service_change_payload(WELL_SHUT_IN), FIELD_OPERATOR
            )
        )
        plugged = assert_ok(
            api.change_well_service(
                w3["id"], F.service_change_payload(WELL_PLUGGED), FIELD_OPERATOR
            )
        )
        assert plugged["operational_state"] == WELL_PLUGGED
        for target in (WELL_IN_SERVICE, WELL_PLUGGED):
            assert_error_envelope(
                api.change_well_service(
                    w3["id"], F.service_change_payload(target), FIELD_OPERATOR
                ),
                ERR_INVALID_WELL_STATE,
            )
        w3_after = read_well(api, w3["id"])
        assert w3_after["operational_state"] == WELL_PLUGGED
        assert w3_after["service_change_count"] == 2

        assert read_ticket(api, ticket["id"])["status"] == TICKET_PENDING
        assert_field_derived_block(
            read_field(api, world.field_id, FIELD_OPERATOR),
            wells_in_service=1, posture=POSTURE_OPEN,
            withdrawal_rate=150000, injection_rate=150000,
        )
        _, meta = validate_paginated(
            api.list_wells(FIELD_OPERATOR, {"storage_field_id": world.field_id, "limit": 100})
        )
        assert meta["total_count"] == 3


def _cascade_world(api):
    """Three wellbores rated 120000 + 120000 + 60000 on the F-AUR reservoir, plus a
    firm and an interruptible contract holding confirmed injections on one gas day."""
    field = create_std_field(api)
    wells = [
        create_well(api, field["id"], well_name=name, rated_rate_dth_per_day=rate,
                    last_mit_passed_at="2026-06-01T00:00:00Z")
        for name, rate in (("AUR-1", 120000), ("AUR-2", 120000), ("AUR-3", 60000))
    ]
    shipper = create_shipper(api)
    firm = create_active_contract(
        api, shipper["id"], field["id"], contract_code="CF-FIRM",
        service_class=SERVICE_CLASS_FIRM,
    )
    interruptible = create_active_contract(
        api, shipper["id"], field["id"], contract_code="CI-INTR",
        service_class=SERVICE_CLASS_INTERRUPTIBLE,
    )
    nf = confirmed_nomination(
        api, firm["id"], shipper["id"],
        gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=90000,
    )
    ni = confirmed_nomination(
        api, interruptible["id"], shipper["id"],
        gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=60000,
    )
    assert nf["confirmed_volume_dth"] == 90000
    assert ni["confirmed_volume_dth"] == 60000, (
        "60000 sits under the interruptible share of the 300000 injection ceiling"
    )
    test = schedule_mit(
        api, wells[0]["id"],
        scheduled_start_at="2026-08-10T00:00:00Z",
        scheduled_end_at="2026-08-10T06:00:00Z",
    )
    set_clock(api, "2026-08-10T12:00:00Z")
    return SimpleNamespace(
        field=field, wells=wells, shipper=shipper,
        shipper_headers=make_shipper_headers(shipper["id"]),
        firm=firm, interruptible=interruptible,
        nf=nf, ni=ni, test=test,
    )


class TestIntegrityFailureCascade:
    """One recorded failure travels test -> wellbore -> program -> reservoir
    posture -> the interruptible schedule of a different commercial entity."""

    def test_the_failure_reaches_the_program_and_re_derives_the_reservoir(self, api):
        """Recording the failure shuts the tested wellbore in, opens a dated
        remediation program, drops the in-service count and pulls both deliverability
        rates down to the surviving well capacity while the posture turns restricted.

        PRD §3.2: "A `FAIL` outcome is the cascade trigger. The test closes at
        `status` `FAILED`; the wellbore's `integrity_state` becomes `MIT_FAILED`, its
        `operational_state` becomes `SHUT_IN` and its `shut_in_reason` becomes
        `MIT_FAILURE`; a `RemediationProgram` is created for that wellbore with
        `status` `OPEN`, `triggering_mit_id` set to the test, `opened_at` at the
        current logical clock and `due_at` 45 days later."

        Design: Difficulty/transitive_cascade/mit_failure_cascades_through_well_remediation_posture_to_interruptible_curtailment
        """
        world = _cascade_world(api)
        w1, w2, w3 = world.wells

        recorded = record_mit(api, world.test["id"], MIT_OUTCOME_FAIL, 1200)
        assert recorded["status"] == MIT_FAILED
        assert recorded["outcome"] == MIT_OUTCOME_FAIL
        assert recorded["recorded_by_user_id"] == STAFF_USER_IDS["IntegrityEngineer"]
        assert_instant_equals(recorded["recorded_at"], "2026-08-10T12:00:00Z")

        failed = read_well(api, w1["id"])
        assert failed["integrity_state"] == INTEGRITY_MIT_FAILED
        assert failed["operational_state"] == WELL_SHUT_IN
        assert failed["shut_in_reason"] == SHUT_IN_REASON_MIT_FAILURE
        assert failed["service_change_count"] == 0
        assert read_well(api, w2["id"])["operational_state"] == WELL_IN_SERVICE
        assert read_well(api, w3["id"])["operational_state"] == WELL_IN_SERVICE

        program = only_program_on_well(api, w1["id"])
        assert program["status"] == REMEDIATION_OPEN
        assert program["triggering_mit_id"] == world.test["id"]
        assert_instant_equals(program["opened_at"], "2026-08-10T12:00:00Z")
        assert_instant_equals(program["due_at"], "2026-09-24T12:00:00Z")

        assert_field_derived_block(
            read_field(api, world.field["id"]),
            wells_in_service=2, posture=POSTURE_RESTRICTED,
            withdrawal_rate=180000, injection_rate=180000,
        )

    def test_the_restricted_sweep_takes_the_interruptible_schedule_only(self, api):
        """The last hop of the cascade reaches a different commercial entity: the
        interruptible nomination is curtailed to zero with a negative credit row
        while the firm nomination on the same gas day keeps its full schedule.

        PRD §2.8: "Phase A — when `field_posture` is `RESTRICTED`, only
        `INTERRUPTIBLE` contracts are swept; when it is `FROZEN`, both service
        classes are swept."

        Design: Difficulty/transitive_cascade/mit_failure_cascades_through_well_remediation_posture_to_interruptible_curtailment
        """
        world = _cascade_world(api)
        record_mit(api, world.test["id"], MIT_OUTCOME_FAIL, 1200)

        curtailed = read_nomination(api, world.ni["id"], world.shipper_headers)
        assert curtailed["status"] == NOMINATION_CURTAILED
        assert curtailed["confirmed_volume_dth"] == 0
        assert curtailed["curtailed_volume_dth"] == 60000

        spared = read_nomination(api, world.nf["id"], world.shipper_headers)
        assert spared["status"] == NOMINATION_CONFIRMED
        assert spared["confirmed_volume_dth"] == 90000

        assert read_contract(api, world.interruptible["id"])["scheduled_injection_dth"] == 0
        assert read_contract(api, world.firm["id"])["scheduled_injection_dth"] == 90000

        credits = [
            row for row in ledger_entries(api, world.interruptible["id"], limit=100)
            if row["entry_type"] == LEDGER_CURTAILMENT_CREDIT
        ]
        assert len(credits) == 1
        assert_ledger_entry(
            credits[0], entry_type=LEDGER_CURTAILMENT_CREDIT,
            volume_dth=-60000.000, amount_usd=0.00, gas_day="2026-08-20",
        )
        assert not [
            row for row in ledger_entries(api, world.firm["id"], limit=100)
            if row["entry_type"] == LEDGER_CURTAILMENT_CREDIT
        ], "the firm contract earns no curtailment credit"


def _well_with_one_booked_window(api):
    """One wellbore carrying a single scheduled window over
    2026-08-10T00:00Z..06:00Z, booked while the clock is still at the epoch."""
    field = create_std_field(api)
    well = create_well(
        api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=600000,
        last_mit_passed_at="2026-06-01T00:00:00Z",
    )
    booked = schedule_mit(
        api, well["id"],
        scheduled_start_at="2026-08-10T00:00:00Z",
        scheduled_end_at="2026-08-10T06:00:00Z",
    )
    return SimpleNamespace(field=field, well=well, booked=booked)


class TestIntegrityWindowClearanceBuffer:
    """Every booked window is padded by the clearance buffer on both sides, and
    the padded comparison is strict on both edges."""

    def test_windows_exactly_the_clearance_buffer_away_are_accepted_on_both_sides(self, api):
        """A window ending exactly twelve hours before the booked start and another
        starting exactly twelve hours after the booked end both land, because the
        padded intervals are half-open.

        PRD §2.11 rung 24: "Windows are half-open, so two windows separated by
        exactly twelve hours are accepted."

        Design: Difficulty/resource_temporal_overlap/mit_windows_padded_by_the_clearance_buffer_on_both_sides
        """
        world = _well_with_one_booked_window(api)

        before = assert_created(
            api.create_mit(
                F.mit_payload(
                    world.well["id"],
                    scheduled_start_at="2026-08-09T06:00:00Z",
                    scheduled_end_at="2026-08-09T12:00:00Z",
                ),
                INTEGRITY_ENGINEER,
            )
        )
        assert before["status"] == MIT_SCHEDULED
        after = assert_created(
            api.create_mit(
                F.mit_payload(
                    world.well["id"],
                    scheduled_start_at="2026-08-10T18:00:00Z",
                    scheduled_end_at="2026-08-10T22:00:00Z",
                ),
                INTEGRITY_ENGINEER,
            )
        )
        assert after["status"] == MIT_SCHEDULED

        rows, meta = validate_paginated(
            api.list_mits(INTEGRITY_ENGINEER, {"well_id": world.well["id"], "limit": 100})
        )
        assert meta["total_count"] == 3
        assert [row["status"] for row in rows] == [MIT_SCHEDULED] * 3

        untouched = read_well(api, world.well["id"], INTEGRITY_ENGINEER)
        assert untouched["integrity_state"] == INTEGRITY_MIT_CURRENT
        assert untouched["operational_state"] == WELL_IN_SERVICE
        assert read_field(api, world.field["id"])["field_posture"] == POSTURE_OPEN

    def test_one_minute_inside_the_padded_window_is_a_conflict(self, api):
        """Moving the accepted start one minute earlier puts it inside the padded
        interval, and the booking is refused rather than queued.

        PRD §2.11 rung 24: "A new test's window does not overlap any other
        `SCHEDULED` test on the same wellbore once each existing window is padded by
        twelve hours on **both** sides — otherwise `ERR_MIT_WINDOW_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/mit_windows_padded_by_the_clearance_buffer_on_both_sides
        """
        world = _well_with_one_booked_window(api)

        assert_error_envelope(
            api.create_mit(
                F.mit_payload(
                    world.well["id"],
                    scheduled_start_at="2026-08-10T17:59:00Z",
                    scheduled_end_at="2026-08-10T21:59:00Z",
                ),
                INTEGRITY_ENGINEER,
            ),
            ERR_MIT_WINDOW_CONFLICT,
        )

        rows, meta = validate_paginated(
            api.list_mits(INTEGRITY_ENGINEER, {"well_id": world.well["id"], "limit": 100})
        )
        assert meta["total_count"] == 1, "the refused booking left no test behind"
        assert rows[0]["id"] == world.booked["id"]
        assert rows[0]["status"] == MIT_SCHEDULED

        untouched = read_well(api, world.well["id"], INTEGRITY_ENGINEER)
        assert untouched["integrity_state"] == INTEGRITY_MIT_CURRENT
        assert untouched["operational_state"] == WELL_IN_SERVICE
        assert read_field(api, world.field["id"])["field_posture"] == POSTURE_OPEN
