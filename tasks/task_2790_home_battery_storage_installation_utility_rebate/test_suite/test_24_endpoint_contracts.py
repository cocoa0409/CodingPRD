"""
What each endpoint promises to hand back: the round trip, the action, the computed read.

A create and its read must agree field for field; a payload-free action endpoint must still
write everything the transition declares; a plain read must show ledger movement caused by an
entirely different endpoint; and a cross-referencing create must write both sides of the link.
"""

from test_helpers import (
    REBATE_ADMIN_HEADERS,
    UTILITY_REVIEWER_HEADERS,
    WARRANTY_AGENT_HEADERS,
    AlertCode,
    AlertSeverity,
    AlertStatus,
    ClaimStatus,
    PerformanceStatus,
    assert_cents,
    assert_common_fields,
    assert_ledger_conserved,
    assert_program_ledger,
    assert_quantity,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    validate_paginated,
    validate_success,
)

ROUND_TRIP_PROGRAM = dict(
    name="Round-Trip Storage Adder",
    total_budget_cents=750000,
    tier1_limit_kwh=12,
    tier1_rate_cents_per_kwh=6000,
    tier2_rate_cents_per_kwh=3000,
    per_project_cap_cents=300000,
    stack_priority=2,
    max_stack_pct_of_cost_bp=2500,
    requires_export_commitment=True,
    min_capacity_commitment_kw=4.0,
)

COMMISSIONING_INSTANT = "2026-08-10T17:00:00Z"


class TestTheProgramRoundTrip:
    """Eleven declared inputs in, the same eleven back out, plus an opened ledger."""

    def test_the_read_agrees_with_the_create_on_every_declared_field(self, api):
        """Nothing supplied is dropped, renamed or rounded away between write and read.

        The administrator funds a program with all eleven of its declared inputs, and both the
        creation response and the subsequent read carry every one of them unchanged, including
        the boolean flag and the two rate figures that no arithmetic has touched yet. The pool
        opens fully unencumbered: the whole budget sits in the unencumbered bucket, not in the
        encumbered or disbursed ones.

        PRD 3.7: "A `RebateAdministrator` stands up a funded program by supplying its `name`, its `program_type` — `STATE_CAPACITY`, `UTILITY_UPFRONT` or `FEDERAL_ADDER` — and its `total_budget_cents`, which must be greater than zero and which is immutable thereafter."
        PRD 3.7: "A new program opens with `remaining_budget_cents` equal to `total_budget_cents`, and with `reserved_budget_cents` and `paid_budget_cents` both at zero."
        PRD 4: "An operation that brings a new resource into existence answers with HTTP 201 and the created resource in `data`; that includes the expansion endpoint, which creates a new battery system, and the participation endpoint, which creates a new dispatch performance."

        Design: Corner/endpoints/create_then_read_incentive_program_round_trips_every_declared_field
        """
        payload = factories.federal_program_payload(**ROUND_TRIP_PROGRAM)

        created = validate_success(
            api.create_program(payload, headers=REBATE_ADMIN_HEADERS), expected_status=201
        )
        program = validate_success(
            api.get_program(created["id"], headers=REBATE_ADMIN_HEADERS)
        )

        assert program["id"] == created["id"]
        for field, value in payload.items():
            if isinstance(value, float):
                assert_quantity(program, field, value)
            else:
                assert program[field] == value, "{} did not round-trip".format(field)
            assert created[field] == program[field], "{} disagrees with the read".format(
                field
            )
        assert_program_ledger(program, remaining=750000, reserved=0, paid=0)
        assert_ledger_conserved(program)
        assert_common_fields(program)


class TestThePayloadFreeActionEndpoint:
    """Acknowledgement sends nothing and still writes a status and an identity."""

    def test_acknowledgement_stamps_the_calling_installer_and_nothing_else(self, api):
        """An empty body still moves the alert and records who took it on.

        The manufacturer's cloud raised the alert; triage belongs to the accountable installer,
        whose own identity is what the endpoint records. The transition writes exactly two
        things beyond the bookkeeping fields: the new status and the acknowledging identity. No
        warranty claim has been filed, so the claim counter is still zero and the claimed
        component is still unset, and the alert's version has advanced by exactly one mutation.

        PRD 3.8: "An alert opens in `OPEN` with `claim_round_count` at zero and with `acknowledged_by_user_id`, `claimed_component` and `resolution_notes` all unset."
        PRD 3.8: "Triage begins with acknowledgement, which moves the alert `OPEN → ACKNOWLEDGED` and records the acting caller's `X-User-ID` in `acknowledged_by_user_id`."
        PRD 3.8: "That counter tracks how many times the alert has entered `UNDER_REVIEW`, so it advances on the initial filing and again on every re-filing."
        PRD 2.5: "`version` (integer): a counter that increases by exactly one on every mutation of that resource."

        Design: Corner/endpoints/acknowledge_alert_action_endpoint_transitions_and_stamps_the_operator
        """
        project = fixtures.commissioned_project(api)
        opened = validate_success(
            api.create_alert(
                factories.alert_payload(project.battery_system_id),
                headers=WARRANTY_AGENT_HEADERS,
            ),
            expected_status=201,
        )
        assert opened["alert_code"] == AlertCode.CELL_IMBALANCE
        assert opened["severity"] == AlertSeverity.WARNING
        assert opened["status"] == AlertStatus.OPEN

        acknowledged = validate_success(
            api.acknowledge_alert(opened["id"], headers=project.installer_headers)
        )

        assert acknowledged["status"] == AlertStatus.ACKNOWLEDGED
        assert acknowledged["acknowledged_by_user_id"] == project.installer_id
        assert acknowledged["claim_round_count"] == 0
        assert_unset(acknowledged, "claimed_component")
        assert acknowledged["version"] == opened["version"] + 1


class TestTheComputedProgramRead:
    """A read on one collection showing a movement caused by a write on another."""

    def test_the_pool_read_shows_the_hold_taken_out_by_a_claim(self, api):
        """Four hundred and twenty-three thousand cents moved bucket without touching the pool.

        Nothing was ever written to the program endpoint after its creation; the movement came
        from the claim endpoint reserving against it. The read shows the encumbrance sitting in
        the held bucket, the unencumbered balance reduced by exactly that figure, nothing
        disbursed, and the immutable total unchanged and still equal to the sum of the three.

        PRD 2.10: "Each `IncentiveProgram` holds a three-bucket ledger in integer cents: `total_budget_cents` is the immutable size of the pool, `remaining_budget_cents` is the unencumbered balance, `reserved_budget_cents` is the sum held for claims that are still in flight, and `paid_budget_cents` is the sum actually disbursed."
        PRD 2.10: "After every single claim transition the following must hold exactly: `total_budget_cents` equals `remaining_budget_cents` plus `reserved_budget_cents` plus `paid_budget_cents`."
        PRD 3.7: "At reservation the results are written as `basis_kwh_reserved`, `stack_ceiling_cents` and `reserved_amount_cents`, and the program pool is then encumbered: if the program's `remaining_budget_cents` is at least the reserved amount — exact equality succeeds — that amount moves out of `remaining_budget_cents` and into `reserved_budget_cents`."

        Design: Corner/endpoints/program_read_reflects_the_encumbrance_created_by_a_claim
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project)
        claim = fixtures.reserve_claim(api, project, program_id)
        assert_cents(claim, "reserved_amount_cents", 423000)

        program = validate_success(
            api.get_program(program_id, headers=project.installer_headers)
        )

        assert_cents(program, "total_budget_cents", 5000000)
        assert_program_ledger(program, remaining=4577000, reserved=423000, paid=0)
        assert_ledger_conserved(program)


class TestTheDecisionEndpointsDenialArm:
    """One endpoint, two arms; the denial arm is the one that moves money back."""

    def test_denial_returns_the_effective_hold_and_keeps_the_reservation_on_record(self, api):
        """The pool ends holding nothing, and the claim keeps both award figures.

        The claim reserved 423000 cents while the bank was merely installed. Commissioning
        re-priced it against the measured 25.65 kilowatt-hours — the smaller of the design and
        measured energies — to 410850 cents and handed the 12150-cent difference back, so the
        effective hold at decision time is the final figure rather than the reservation. Denial
        releases exactly that hold: the encumbered bucket empties and the whole 5000000-cent
        budget is unencumbered again. The claim keeps its reserved figure for audit and was
        never approved, so no approving identity is on it.

        PRD 3.7: "At commissioning the basis is the smaller of the bank's design `usable_kwh` and its measured `verified_capacity_kwh`."
        PRD 3.7: "At commissioning the results are written as `basis_kwh_final` and `final_amount_cents`, and the final figure is clamped to the `reserved_amount_cents` already held, because the reservation is a ceiling and never a floor."
        PRD 3.7: "`DENY` moves the claim `SUBMITTED → DENIED` and releases the claim's effective hold: that amount leaves `reserved_budget_cents` and returns to `remaining_budget_cents`."
        PRD 2.10: "Every ledger move in the claim lifecycle is expressed in terms of the claim's **effective hold**, which is its `final_amount_cents` when that field has been written and its `reserved_amount_cents` while it has not."

        Design: Corner/endpoints/claim_denial_releases_the_whole_encumbrance_back_to_remaining_budget
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project)
        claim = fixtures.reserve_claim(api, project, program_id)
        project = fixtures.schedule_four_tests(api, project)
        project = fixtures.record_four_results(api, project)
        project = fixtures.pass_inspection(api, project)
        project = fixtures.advance_clock(api, project, COMMISSIONING_INSTANT)
        validate_success(
            api.commission(project.battery_system_id, headers=project.installer_headers)
        )
        project = fixtures.grant_pto(api, project)
        project = fixtures.register_warranty(api, project)
        fixtures.submit_claim(api, project, claim["id"])

        denied = validate_success(
            api.decide_claim(
                claim["id"], factories.claim_denial_payload(), headers=REBATE_ADMIN_HEADERS
            )
        )

        assert denied["status"] == ClaimStatus.DENIED
        assert_quantity(denied, "basis_kwh_final", 25.65)
        assert_cents(denied, "reserved_amount_cents", 423000)
        assert_cents(denied, "final_amount_cents", 410850)
        assert_unset(denied, "approved_by_user_id")
        program = fixtures.read_program(api, program_id)
        assert_program_ledger(program, remaining=5000000, reserved=0, paid=0)
        assert_ledger_conserved(program)


class TestTheCrossReferencingCreate:
    """One call that must find two parents and then write both sides of the link."""

    def test_calling_a_battery_in_writes_the_snapshot_and_the_event_ledger(self, api):
        """Five kilowatts are frozen onto the participation and added to the event.

        The reviewer names the enrollment and the event's current version, and the new
        participation carries both foreign keys and a snapshot of the pledge as it stands now,
        which no later change to the enrollment can move. Nothing has been metered yet, so the
        delivered figure is unset. On the event side the committed-capacity ledger rises from
        zero to the snapshot and the event's version advances by one, and the reverse lookup on
        the event finds precisely this one participation.

        PRD 3.9: "A new event opens in `SCHEDULED` with `enrolled_pledged_kw` and `total_net_payment_cents` at zero and `settled_at` unset."
        PRD 3.9: "Doing so creates a participation in `PENDING`, copies the enrollment's current `pledged_kw` into the participation's immutable `pledged_kw_snapshot`, adds that snapshot to the event's `enrolled_pledged_kw`, and advances the event's `version` by one — which is precisely why the next caller must re-read the event."
        PRD 3.9: "After the window has closed the reviewer reports metered `delivered_kwh` for a participation, which moves it `PENDING → REPORTED`."

        Design: Corner/endpoints/participation_links_event_and_enrollment_with_a_capacity_snapshot
        """
        project = fixtures.enrolled_project(api)
        event = fixtures.create_event(api, project)
        assert_quantity(event, "enrolled_pledged_kw", 0.0)

        performance = validate_success(
            api.create_participation(
                event["id"],
                factories.participation_payload(project.enrollment_id, event["version"]),
                headers=UTILITY_REVIEWER_HEADERS,
            ),
            expected_status=201,
        )

        assert performance["dispatch_event_id"] == event["id"]
        assert performance["byod_enrollment_id"] == project.enrollment_id
        assert_quantity(performance, "pledged_kw_snapshot", 5.0)
        assert performance["status"] == PerformanceStatus.PENDING
        assert_unset(performance, "delivered_kwh")

        called = get_success_data(
            api.get_dispatch_event(event["id"], headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(called, "enrolled_pledged_kw", 5.0)
        assert called["version"] == event["version"] + 1
        performances, _ = validate_paginated(
            api.list_performances(
                {"dispatch_event_id": event["id"]}, headers=UTILITY_REVIEWER_HEADERS
            )
        )
        assert [row["id"] for row in performances] == [performance["id"]]
