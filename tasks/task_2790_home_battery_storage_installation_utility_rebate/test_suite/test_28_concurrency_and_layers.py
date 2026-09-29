"""
The two guarded aggregates, and the one write that reaches four entities at once.

A bank and a dispatch event are the only parents a client must have observed before writing
to them, and each guard is proved by the same request failing on a stale view and then
behaving quite differently on a fresh one. The last case is the widest single write in the
system: adding units to a dispatching bank retires it, suspends its season and hands the
capacity it had promised back to the event that was counting on it.
"""

from test_helpers import (
    UTILITY_REVIEWER_HEADERS,
    ApiErrorId,
    BuildStatus,
    EnrollmentStatus,
    EventStatus,
    GridStatus,
    InverterModel,
    PerformanceStatus,
    WarrantyStatus,
    assert_cents,
    assert_program_ledger,
    assert_quantity,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_POOL = dict(total_budget_cents=2000000)

EXPANSION = dict(
    additional_unit_count=2,
    inverter_model=InverterModel.GW2_HOME,
    firmware_version="24.6.0",
    installed_cost_cents=2600000,
)


class TestTheBankVersionGuardOnASiblingReservation:
    """Reserving is itself a write, so one reservation invalidates the view for the next."""

    def test_the_version_read_before_the_first_claim_is_already_stale_for_the_second(
        self, api
    ):
        """The same request is refused with the old view and accepted with the new one.

        Two pools are funded and the bank's version is read once, before either claim. The first
        reservation succeeds against that view and, in succeeding, advances the bank's version by
        one — so the caller's held value is now one behind. Re-using it for the second pool is
        refused as a stale view, and the refusal writes nothing at all: the second pool is still
        untouched at that moment. Re-reading the bank gives a value exactly one higher than the
        one first held, and the identical request then goes through, reserving 133200 cents: the
        second pool bills the first 10 kilowatt-hours of the 27.0 basis at its own first-tier rate
        and the remaining 17 at its second, a raw award of 148000 cents, of which the
        limited-export posture pays nine tenths. The ceiling that applies is the tighter of the
        two pools' stacking percentages against the 3200000-cent installed cost, 1280000 cents,
        which this award is nowhere near. Two successful reservations later the bank's version is
        two above the value first read.

        PRD 2.6: "Reserving a rebate claim requires `expected_battery_system_version`, carrying the client's last observed `version` of the target `BatterySystem`. If that value does not equal the system's current `version`, the reservation is rejected with `ERR_STALE_SYSTEM_VERSION` (HTTP 412)."
        PRD 2.6: "Any prior write to the bank invalidates that view, including a sibling claim reservation, since reserving a claim itself advances the bank's `version`."
        PRD 3.7: "The raw award is the first-tier energy multiplied by `tier1_rate_cents_per_kwh` plus the second-tier energy multiplied by `tier2_rate_cents_per_kwh`."
        PRD 3.7: "The tightest `max_stack_pct_of_cost_bp` among those programs is taken, multiplied by the bank's `installed_cost_cents`, divided by 10000, and floored to a whole number of cents; that figure is the claim's `stack_ceiling_cents`."
        PRD 2.5: "`version` (integer): a counter that increases by exactly one on every mutation of that resource."

        Design: Corner/cross_cutting_complexity_layers/stale_battery_system_version_on_a_second_claim_returns_412_then_succeeds_when_refreshed
        """
        project = fixtures.installed_project(api)
        state_id = fixtures.create_state_program(api, project)
        utility_id = fixtures.create_utility_program(api, project, **SECOND_POOL)
        held_version = fixtures.system_version(api, project)

        first = validate_success(
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id, state_id, held_version
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )
        assert_cents(first, "reserved_amount_cents", 423000)

        validate_error(
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id, utility_id, held_version
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_STALE_SYSTEM_VERSION,
            expected_status=412,
        )
        assert_program_ledger(
            fixtures.read_program(api, utility_id),
            remaining=2000000,
            reserved=0,
            paid=0,
        )

        fresh_version = fixtures.system_version(api, project)
        assert fresh_version == held_version + 1

        second = validate_success(
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id, utility_id, fresh_version
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert_quantity(second, "basis_kwh_reserved", 27.0)
        assert_cents(second, "stack_ceiling_cents", 1280000)
        assert_cents(second, "reserved_amount_cents", 133200)
        assert_program_ledger(
            fixtures.read_program(api, utility_id),
            remaining=1866800,
            reserved=133200,
            paid=0,
        )
        assert fixtures.system_version(api, project) == held_version + 2


class TestTheEventVersionGuardOnParticipation:
    """The stale view is reported before the duplicate the request also is."""

    def test_the_version_guard_speaks_first_and_the_uniqueness_rule_only_afterwards(
        self, api
    ):
        """One enrollment, one event, and the second call is wrong in two ways at once.

        The event's version is read before anyone is called into it, and the first call advances
        it by one. Re-using the held value for a second call on the same enrollment is wrong
        twice over: the view is stale and the enrollment is already in this event. The version
        objection is decided first, so that is what comes back, and it comes back before the
        uniqueness rule can speak. With the version refreshed, the second objection finally
        surfaces as the duplicate it always was. Neither refusal changed anything: the event holds
        exactly one participation, its committed capacity is still the single 5.0 kilowatt pledge,
        and its version has not moved since the one successful call.

        PRD 2.6: "Calling an enrolled battery into a dispatch event requires `expected_dispatch_event_version`, carrying the client's last observed `version` of the target `DispatchEvent`. A mismatch with the event's current `version` is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)."
        PRD 3.9: "Doing so creates a participation in `PENDING`, copies the enrollment's current `pledged_kw` into the participation's immutable `pledged_kw_snapshot`, adds that snapshot to the event's `enrolled_pledged_kw`, and advances the event's `version` by one — which is precisely why the next caller must re-read the event."
        PRD 3.9: "and an enrollment may appear in a given event only once, so a repeat is rejected with `ERR_PARTICIPATION_DUPLICATE`."
        PRD 2.12: "**Optimistic concurrency.** The supplied expected parent version matches, else `ERR_STALE_SYSTEM_VERSION` or `ERR_STALE_EVENT_VERSION`. This applies to claim reservation, bank expansion and event participation."

        Design: Corner/cross_cutting_complexity_layers/stale_dispatch_event_version_on_participation_returns_412_then_duplicate_on_fresh_version
        """
        project = fixtures.enrolled_project(api)
        event = fixtures.create_event(api, project)
        held_version = event["version"]
        performance = fixtures.call_into_event(api, project)
        assert_quantity(performance, "pledged_kw_snapshot", 5.0)

        validate_error(
            api.create_participation(
                event["id"],
                factories.participation_payload(project.enrollment_id, held_version),
                headers=UTILITY_REVIEWER_HEADERS,
            ),
            ApiErrorId.ERR_STALE_EVENT_VERSION,
            expected_status=412,
        )

        fresh_version = fixtures.event_version(api, project)
        assert fresh_version == held_version + 1

        validate_error(
            api.create_participation(
                event["id"],
                factories.participation_payload(project.enrollment_id, fresh_version),
                headers=UTILITY_REVIEWER_HEADERS,
            ),
            ApiErrorId.ERR_PARTICIPATION_DUPLICATE,
            expected_status=409,
        )

        performances, meta = validate_paginated(
            api.list_performances(
                {"dispatch_event_id": event["id"]}, headers=UTILITY_REVIEWER_HEADERS
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in performances] == [performance["id"]]
        called = get_success_data(
            api.get_dispatch_event(event["id"], headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(called, "enrolled_pledged_kw", 5.0)
        assert called["status"] == EventStatus.SCHEDULED
        assert called["version"] == fresh_version


class TestOneWriteThatReachesFourEntities:
    """Adding units retires the bank, and everything that depended on it follows."""

    def test_expanding_a_dispatching_bank_supersedes_suspends_cancels_and_returns_capacity(
        self, api
    ):
        """The event's committed capacity is back to zero, and nobody asked it for that.

        The household's bank is energized, enrolled for the season and already called into a
        scheduled event, so 5.0 kilowatts of its capacity are committed. Adding two units creates
        a fresh four-unit row, catalog-sized to 54.0 kilowatt-hours and 20.0 kilowatts and
        starting at the very beginning of the build lifecycle with nothing warranted on it. The
        write then propagates: the bank it replaces is retired, the season enrolment on a retired
        bank is suspended because it can no longer answer a call, the participation that suspended
        enrolment had pending is cancelled, and the cancelled pledge is subtracted from the
        event's committed-capacity ledger, which returns to exactly the zero it held before the
        call. The event itself is untouched in status and is still scheduled.

        PRD 3.8: "On success a new bank row is created. Its `expands_system_id` points at the base bank's `id`, its `unit_count` is the base count plus `additional_unit_count`, its `installed_cost_cents` is the base bank's installed cost plus the supplied additional cost, and its `site_id`, `installer_id`, `load_calculation_id` and `model_code` are copied from the base bank while its `inverter_model` and `firmware_version` come from the request."
        PRD 3.8: "The new row starts fresh: `build_status` of `DESIGN_DRAFT`, `grid_status` of `NOT_APPLIED`, `warranty_status` of `UNREGISTERED`, and no `verified_capacity_kwh`, `commissioned_at`, `warranty_deadline_at`, `warranty_registered_at`, `warranty_coverage_years` or `serial_numbers` — the expanded bank must be permitted, approved, installed, commissioned and registered on its own account."
        PRD 3.8: "Its first hop sets the base bank's `build_status` to `SUPERSEDED`. Caused by that, the second hop moves every BYOD enrollment of the base bank whose `status` is `ENROLLED` to `SUSPENDED` — a superseded bank cannot answer a dispatch call. Caused by the second hop, the third hop cancels, for each such enrollment, every dispatch participation still in `PENDING` whose event is still `SCHEDULED`, subtracting each cancelled participation's `pledged_kw_snapshot` from its event's `enrolled_pledged_kw` so the event's committed-capacity ledger returns to exactly its pre-participation value."
        PRD 2.11: "A bank's `usable_kwh` is its `unit_count` multiplied by the per-unit usable energy of its model, and its `continuous_kw` is its `unit_count` multiplied by the per-unit continuous power of its model, each rounded half up to two decimals."

        Design: Corner/cross_cutting_complexity_layers/expansion_supersedes_the_base_suspends_the_enrollment_and_cancels_the_performance
        """
        project = fixtures.event_with_participation(api)
        base_id = project.battery_system_id
        called = get_success_data(
            api.get_dispatch_event(project.event_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(called, "enrolled_pledged_kw", 5.0)

        expanded = validate_success(
            api.expand_system(
                base_id,
                factories.expansion_payload(
                    fixtures.system_version(api, project), **EXPANSION
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert expanded["expands_system_id"] == base_id
        assert expanded["unit_count"] == 4
        assert_quantity(expanded, "usable_kwh", 54.0)
        assert_quantity(expanded, "continuous_kw", 20.0)
        assert expanded["build_status"] == BuildStatus.DESIGN_DRAFT
        assert expanded["grid_status"] == GridStatus.NOT_APPLIED
        assert expanded["warranty_status"] == WarrantyStatus.UNREGISTERED
        assert_unset(expanded, "verified_capacity_kwh", "commissioned_at")

        base = fixtures.read_system(api, project)
        assert base["build_status"] == BuildStatus.SUPERSEDED
        enrollment = get_success_data(
            api.get_enrollment(project.enrollment_id, headers=project.installer_headers)
        )
        assert enrollment["status"] == EnrollmentStatus.SUSPENDED
        performance = get_success_data(
            api.get_performance(project.performance_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert performance["status"] == PerformanceStatus.CANCELLED
        event_after = get_success_data(
            api.get_dispatch_event(project.event_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(event_after, "enrolled_pledged_kw", 0.0)
        assert event_after["status"] == EventStatus.SCHEDULED
