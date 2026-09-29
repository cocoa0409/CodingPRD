"""Sealing the census snapshot: initial states, the date gate and the lock's side effects."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_component_status,
    assert_cycle_ledger,
    assert_cycle_posture,
    assert_instant_equals,
    assert_null,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)


class TestDeclaredInitialStates:
    """Every state dimension opens on the value the contract declares for it."""

    def test_every_newly_created_row_opens_on_its_declared_initial_state(
        self, api, registrar, analyst, steward
    ):
        """A component starts NOT_RUN rather than CLEARED because no preparation has run.

        PRD 3.3: "A new component starts with `prep_status` `DRAFT`, `edit_status` `NOT_RUN`,
        `fatal_open_count` 0, `mapping_coverage_pct` and `core_expense_per_fte_cents` null,
        `prepared_by_user_id`, `certified_by_user_id`, `certification_statement` and
        `submitted_at` all null, and `version` 1."

        Design: Corner/state_machines/corner_sm_newly_created_rows_start_in_their_declared_initial_state
        """
        definition = fx.create_definition(
            api,
            steward,
            definition_code="ENR_LEVEL",
            survey_component=K.DOMAIN_ENROLLMENT,
            value_domain=["UNDERGRAD", "GRADUATE"],
            required=False,
            unit_of_measure="code",
        )

        cycle = validate_success(
            api.create_reporting_cycle(f.make_reporting_cycle_payload(), registrar), 201
        )
        assert_cycle_posture(cycle, K.POSTURE_OPEN)

        extract = fx.register_extract(
            api,
            cycle["id"],
            cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=3,
            checksum="c1d2e3f4a5b60114",
        )
        assert extract["status"] == K.FROZEN_FILE_ACTIVE

        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)
        validate_success(api.census_lock_cycle(cycle["id"], registrar))

        component = validate_success(
            api.create_survey_component(
                f.make_survey_component_payload(cycle["id"], extract["id"], K.DOMAIN_ENROLLMENT),
                analyst,
            ),
            201,
        )
        assert_component_status(
            component, prep_status=K.PREP_DRAFT, edit_status=K.EDIT_NOT_RUN, fatal_open_count=0
        )
        assert_null(component["prepared_by_user_id"], "component.prepared_by_user_id")
        assert_null(component["mapping_coverage_pct"], "component.mapping_coverage_pct")
        assert_null(component["certified_by_user_id"], "component.certified_by_user_id")
        assert_null(component["submitted_at"], "component.submitted_at")
        assert_version(component, 1, "component")
        assert_common_fields(component, "component")

        cohort = validate_success(
            api.create_cohort(
                cycle["id"],
                f.make_cohort_payload(
                    cohort_type=K.COHORT_RETENTION_FT,
                    entry_term="FALL2025",
                    publication_metric_key="RETENTION_FT_FALL2025",
                ),
                registrar,
            ),
            201,
        )
        assert cohort["status"] == K.COHORT_DRAFT

        member = validate_success(
            api.add_cohort_member(
                cohort["id"],
                f.make_member_payload(
                    "S001", entry_status=K.ENTRY_FULL_TIME, outcome=K.OUTCOME_STILL_ENROLLED
                ),
                registrar,
            ),
            201,
        )
        assert member["exclusion_status"] == K.EXCLUSION_NONE
        assert_version(member, 1, "member")

        mapping = validate_success(
            api.propose_element_mapping(
                f.make_element_mapping_payload(
                    cycle["id"],
                    definition["id"],
                    local_system_code=K.LOCAL_SYSTEM_SIS,
                    local_field_path="sis.student.level",
                    transform_expression="upper(level_code)",
                    value_map={"UG": "UNDERGRAD"},
                ),
                analyst,
            ),
            201,
        )
        assert mapping["status"] == K.MAPPING_PROPOSED
        assert mapping["revision_round"] == 0

        stored_cohort = validate_success(api.get_cohort(cohort["id"], registrar))
        assert stored_cohort["status"] == K.COHORT_DRAFT
        sealed_extract = validate_success(api.get_frozen_file(extract["id"], registrar))
        assert sealed_extract["status"] == K.FROZEN_FILE_LOCKED


class TestCensusLockSideEffects:
    """One lock call performs every declared effect at once."""

    def test_one_lock_seals_the_cycle_and_flips_every_active_extract(self, api, registrar, analyst):
        """The lock walks the extracts itself and leaves the record total untouched.

        PRD 3.1: "The lock then sets `snapshot_posture` to `CENSUS_LOCKED`, writes
        `census_locked_at` from the logical clock, increments the cycle's `version`, walks the
        cycle's `ACTIVE` extracts in `created_at` ascending order flipping each one
        `ACTIVE → LOCKED` with its own `version` incremented, and recomputes
        `active_record_count` and `frozen_file_count` — the record total is unchanged in value,
        because locked extracts remain inside the sum."

        Design: Corner/state_machines/corner_sm_census_lock_side_effects_lock_every_active_extract
        """
        cycle = fx.create_cycle(api, registrar)
        enrollment = fx.register_extract(
            api,
            cycle["id"],
            cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1000,
            checksum="c1d2e3f4a5b60115",
        )
        completions = fx.register_extract(
            api,
            cycle["id"],
            None,
            registrar,
            domain=K.DOMAIN_COMPLETIONS,
            record_count=250,
            checksum="c1d2e3f4a5b60116",
        )

        fx.move_clock(api, K.CLOCK_ON_CENSUS_DATE, registrar)
        locked = validate_success(api.census_lock_cycle(cycle["id"], registrar))

        assert_cycle_posture(locked, K.POSTURE_CENSUS_LOCKED)
        assert_instant_equals(
            locked["census_locked_at"], K.CLOCK_ON_CENSUS_DATE_ECHO, "cycle.census_locked_at"
        )
        assert_version(locked, 4, "cycle")
        assert_cycle_ledger(locked, frozen_file_count=2, active_record_count=1250)

        for extract, label in ((enrollment, "enrollment"), (completions, "completions")):
            stored = validate_success(api.get_frozen_file(extract["id"], analyst))
            assert stored["status"] == K.FROZEN_FILE_LOCKED, label
            assert_version(stored, 2, "extract %s" % label)

        rows, meta = validate_paginated(
            api.list_frozen_files(analyst, cycle_id=cycle["id"], status=K.FROZEN_FILE_LOCKED)
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

    def test_a_cycle_with_no_active_extract_cannot_seal_its_snapshot(self, api, registrar):
        """An empty snapshot is a distinct refusal from an unreached census date.

        PRD 3.1: "The logical clock's date must have reached `census_date`, with equality passing
        and any earlier date giving `ERR_CENSUS_DATE_NOT_REACHED`; and at least one extract of the
        cycle must currently be `ACTIVE`, failing which the lock reports
        `ERR_NO_ACTIVE_SNAPSHOT`."

        Design: Corner/state_machines/corner_sm_census_lock_requires_an_active_snapshot
        """
        cycle = fx.create_cycle(api, registrar)
        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)

        refused = api.census_lock_cycle(cycle["id"], registrar)
        validate_error(refused, ApiErrorId.NO_ACTIVE_SNAPSHOT, 409)

        untouched = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_posture(untouched, K.POSTURE_OPEN)
        assert_null(untouched["census_locked_at"], "cycle.census_locked_at")
        assert_version(untouched, 1, "cycle")

        extract = fx.register_extract(
            api,
            cycle["id"],
            untouched["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1000,
            checksum="c1d2e3f4a5b60117",
        )
        locked = validate_success(api.census_lock_cycle(cycle["id"], registrar))
        assert_cycle_posture(locked, K.POSTURE_CENSUS_LOCKED)
        assert_cycle_ledger(locked, active_record_count=1000)

        stored = validate_success(api.get_frozen_file(extract["id"], registrar))
        assert stored["status"] == K.FROZEN_FILE_LOCKED


class TestCensusLockIsNotIdempotent:
    """A second lock is a posture error, never a replay."""

    def test_replaying_the_lock_is_refused_and_never_restamps_the_seal(self, api, registrar):
        """The seal instant belongs to the first lock and the refused replay costs no version.

        PRD 2.6: "That covers component work attempted while the cycle is still `OPEN`; a cycle
        transition fired from the wrong posture (a census lock attempted from `CENSUS_LOCKED` or
        `FROZEN`, a freeze attempted from `OPEN` or `REOPENED`, a reopen attempted from anything
        other than `FROZEN`); and any mutation of any child of an `ARCHIVED` cycle."

        Design: Corner/state_machines/corner_sm_second_census_lock_is_rejected_not_replayed
        """
        cycle = fx.create_cycle(api, registrar)
        fx.register_extract(
            api,
            cycle["id"],
            cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1000,
            checksum="c1d2e3f4a5b60118",
        )
        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)
        first = validate_success(api.census_lock_cycle(cycle["id"], registrar))
        assert_version(first, 3, "cycle")

        fx.move_clock(api, "2026-12-01T00:00:00Z", registrar)
        replay = api.census_lock_cycle(cycle["id"], registrar)
        validate_error(replay, ApiErrorId.INVALID_CYCLE_STATE, 409)

        stored = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_instant_equals(
            stored["census_locked_at"], K.CLOCK_AFTER_CENSUS_ECHO, "cycle.census_locked_at"
        )
        assert_version(stored, 3, "cycle")
        assert_cycle_posture(stored, K.POSTURE_CENSUS_LOCKED)


class TestCensusDateGate:
    """The gate compares the clock's date with census_date and equality passes."""

    def test_the_lock_is_refused_the_day_before_and_accepted_on_the_census_date(
        self, api, registrar
    ):
        """A refusal one second before midnight runs no cascade at all.

        PRD 2.5: "`census_date` is an ISO 8601 calendar date (`YYYY-MM-DD`) naming the official
        snapshot day; the census snapshot may not be sealed until the logical clock's date has
        reached it, and equality passes — a lock attempted on the census date itself is legal,
        while a lock attempted on any strictly earlier date is refused with
        `ERR_CENSUS_DATE_NOT_REACHED` (HTTP 422)."

        Design: Corner/validations/corner_val_census_lock_refused_before_the_census_date_and_allowed_on_it
        """
        cycle = fx.create_cycle(api, registrar)
        extract = fx.register_extract(
            api,
            cycle["id"],
            cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1000,
            checksum="c1d2e3f4a5b60144",
        )

        fx.move_clock(api, K.CLOCK_BEFORE_CENSUS_DATE, registrar)
        too_early = api.census_lock_cycle(cycle["id"], registrar)
        validate_error(too_early, ApiErrorId.CENSUS_DATE_NOT_REACHED, 422)

        held = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_posture(held, K.POSTURE_OPEN)
        assert_null(held["census_locked_at"], "cycle.census_locked_at")
        assert_version(held, 2, "cycle")

        untouched = validate_success(api.get_frozen_file(extract["id"], registrar))
        assert untouched["status"] == K.FROZEN_FILE_ACTIVE
        assert_version(untouched, 1, "extract")

        fx.move_clock(api, K.CLOCK_ON_CENSUS_DATE, registrar)
        sealed = validate_success(api.census_lock_cycle(cycle["id"], registrar))
        assert_cycle_posture(sealed, K.POSTURE_CENSUS_LOCKED)
        assert_instant_equals(
            sealed["census_locked_at"], K.CLOCK_ON_CENSUS_DATE_ECHO, "cycle.census_locked_at"
        )
        assert_version(sealed, 3, "cycle")

        cascaded = validate_success(api.get_frozen_file(extract["id"], registrar))
        assert cascaded["status"] == K.FROZEN_FILE_LOCKED
        assert_version(cascaded, 2, "extract")


class TestLogicalClockAuthority:
    """The clock is the only time source and nothing about it is monotonic."""

    def test_the_clock_may_be_wound_back_and_later_rows_carry_the_earlier_instant(
        self, api, registrar, analyst, disclosure
    ):
        """An extract registered after the clock is wound back predates its own parent cycle.

        PRD 2.5: "All temporal rules in this system read a **logical clock** rather than
        wall-clock time, and a dedicated test-driving capability sets it: a caller in any of the
        five roles supplies a `to_iso8601` instant and the server answers with the clock's new
        reading in a `current_utc` field."

        Design: Corner/endpoints/corner_ep_clock_endpoint_is_authoritative_and_not_monotonic
        """
        forward = validate_success(api.set_clock("2026-12-15T08:30:00Z", disclosure))
        assert_instant_equals(forward["current_utc"], "2026-12-15T08:30:00.000Z", "current_utc")

        cycle = validate_success(
            api.create_reporting_cycle(f.make_reporting_cycle_payload(), registrar), 201
        )
        assert_instant_equals(cycle["created_at"], "2026-12-15T08:30:00.000Z", "cycle.created_at")
        assert_instant_equals(cycle["updated_at"], "2026-12-15T08:30:00.000Z", "cycle.updated_at")

        backward = validate_success(api.set_clock(K.CLOCK_AFTER_CENSUS, analyst))
        assert_instant_equals(backward["current_utc"], K.CLOCK_AFTER_CENSUS_ECHO, "current_utc")

        extract = fx.register_extract(
            api,
            cycle["id"],
            cycle["version"],
            registrar,
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1000,
            checksum="c1d2e3f4a5b60155",
        )
        assert_instant_equals(
            extract["snapshot_taken_at"], K.CLOCK_AFTER_CENSUS_ECHO, "extract.snapshot_taken_at"
        )
        assert extract["snapshot_taken_at"] < cycle["created_at"]

    def test_before_any_set_call_the_clock_reports_its_declared_startup_instant(
        self, api, registrar
    ):
        """The startup reading is a fixed instant, never a wall-clock fallback.

        PRD 2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`; until the first set
        call it must report that instant and must never silently fall back to real wall-clock
        time."

        Design: Corner/endpoints/corner_ep_clock_endpoint_is_authoritative_and_not_monotonic
        """
        cycle = validate_success(
            api.create_reporting_cycle(f.make_reporting_cycle_payload(), registrar), 201
        )
        assert_instant_equals(cycle["created_at"], K.CLOCK_STARTUP_UTC_ECHO, "cycle.created_at")

        echoed = validate_success(api.set_clock(K.CLOCK_STARTUP_UTC, registrar))
        assert_instant_equals(echoed["current_utc"], K.CLOCK_STARTUP_UTC_ECHO, "current_utc")
