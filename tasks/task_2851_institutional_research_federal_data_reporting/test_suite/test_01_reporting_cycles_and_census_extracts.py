"""Opening a collection cycle and registering the census extracts beneath it."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_cycle_ledger,
    assert_cycle_posture,
    assert_instant_equals,
    assert_null,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)


class TestReportingCycleCreation:
    """Opening the year's work through POST /ir/reporting-cycles."""

    def test_new_cycle_echoes_its_calendar_and_starts_open_at_version_one(self, api, registrar):
        """A newly opened cycle begins at OPEN with every ledger at zero.

        PRD 3.1: "A newly opened cycle begins at `snapshot_posture` `OPEN`, with `reopen_count`
        at 0, `active_record_count` at 0, `frozen_file_count` at 0, `census_locked_at`,
        `frozen_at` and `reopen_reason` all null, and `version` 1."

        Design: Corner/entities/corner_cycle_creation_returns_declared_defaults_and_version_one
        """
        response = api.create_reporting_cycle(f.make_reporting_cycle_payload(), registrar)
        cycle = validate_success(response, 201)

        assert cycle["cycle_code"] == K.CYCLE_CODE
        assert cycle["collection_year"] == K.COLLECTION_YEAR
        assert cycle["census_date"] == K.CENSUS_DATE
        assert_instant_equals(
            cycle["collection_deadline"], K.COLLECTION_DEADLINE_ECHO, "collection_deadline"
        )
        assert_cycle_posture(cycle, K.POSTURE_OPEN)
        assert_cycle_ledger(cycle, frozen_file_count=0, active_record_count=0, reopen_count=0)
        assert_version(cycle, 1, "cycle")
        assert_null(cycle["census_locked_at"], "cycle.census_locked_at")
        assert_null(cycle["frozen_at"], "cycle.frozen_at")
        assert_null(cycle["reopen_reason"], "cycle.reopen_reason")
        assert_common_fields(cycle, "cycle")


class TestCensusExtractRegistration:
    """Registering one immutable census extract per source domain and window."""

    def test_extract_read_back_carries_exactly_what_was_registered(self, api, registrar, analyst):
        """The stored extract is the registered extract, not a projection of its cycle.

        PRD 3.1: "The server records the owning `cycle_id`, sets `snapshot_taken_at` from the
        logical clock, starts the row at `status` `ACTIVE` with `version` 1, and leaves
        `supersedes_frozen_file_id` null unless the registration replaced an incumbent."

        Design: Corner/entities/corner_frozen_file_retrieval_matches_registration
        """
        cycle = fx.create_cycle(api, registrar)
        payload = f.make_frozen_file_payload(
            cycle["version"],
            domain=K.DOMAIN_ENROLLMENT,
            record_count=1000,
            coverage_start_date="2026-09-01",
            coverage_end_date="2026-10-15",
            checksum="c1d2e3f4a5b60101",
        )
        created = validate_success(api.register_frozen_file(cycle["id"], payload, registrar), 201)

        extract = validate_success(api.get_frozen_file(created["id"], analyst))
        assert extract["cycle_id"] == cycle["id"]
        assert extract["domain"] == K.DOMAIN_ENROLLMENT
        assert extract["record_count"] == 1000
        assert extract["coverage_start_date"] == "2026-09-01"
        assert extract["coverage_end_date"] == "2026-10-15"
        assert extract["checksum"] == "c1d2e3f4a5b60101"
        assert extract["status"] == K.FROZEN_FILE_ACTIVE
        assert_version(extract, 1, "extract")

        refreshed = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_ledger(refreshed, active_record_count=1000)

    def test_snapshot_and_lock_instants_are_minted_from_the_logical_clock(self, api, registrar):
        """snapshot_taken_at and census_locked_at come from the clock, never from the client.

        PRD 2.5: "Every timestamp the server writes itself — `census_locked_at`, `frozen_at`,
        `snapshot_taken_at`, `submitted_at`, `locked_at`, `transmitted_at`, `screened_at` — is
        taken from the logical clock at the moment of the transition, not from wall-clock time."

        Design: Corner/entities/corner_system_fields_are_minted_from_the_logical_clock
        """
        cycle = fx.create_cycle(api, registrar)
        fx.move_clock(api, "2026-08-15T09:30:00Z", registrar)
        extract = validate_success(
            api.register_frozen_file(
                cycle["id"],
                f.make_frozen_file_payload(cycle["version"], checksum="c1d2e3f4a5b60109"),
                registrar,
            ),
            201,
        )
        assert_instant_equals(
            extract["snapshot_taken_at"], "2026-08-15T09:30:00.000Z", "snapshot_taken_at"
        )
        assert_null(extract["supersedes_frozen_file_id"], "supersedes_frozen_file_id")
        assert_common_fields(extract, "extract")

        fx.move_clock(api, K.CLOCK_AFTER_CENSUS, registrar)
        locked_cycle = validate_success(api.census_lock_cycle(cycle["id"], registrar))
        assert_instant_equals(
            locked_cycle["census_locked_at"], "2026-11-01T00:00:00.000Z", "census_locked_at"
        )
        assert_null(locked_cycle["frozen_at"], "cycle.frozen_at")

        relocked_extract = validate_success(api.get_frozen_file(extract["id"], registrar))
        assert relocked_extract["status"] == K.FROZEN_FILE_LOCKED


class TestCensusExtractListing:
    """Paging the extract register."""

    def test_extract_pages_report_the_filtered_total_not_the_page_size(self, api, registrar, analyst):
        """total_count counts the filtered set while has_more describes the window.

        PRD 2.3: "Both values are echoed in the response envelope's `meta` object alongside
        `total_count` (the number of items matching the filter, ignoring pagination) and
        `has_more` (true when items remain beyond the current window)."

        Design: Corner/entities/corner_frozen_file_listing_paginates_with_total_count_and_has_more
        """
        cycle = fx.create_cycle(api, registrar)
        fx.register_extract(
            api, cycle["id"], cycle["version"], registrar,
            domain=K.DOMAIN_ENROLLMENT, record_count=1000, checksum="c1d2e3f4a5b60102",
        )
        fx.register_extract(
            api, cycle["id"], None, registrar,
            domain=K.DOMAIN_COMPLETIONS, record_count=250, checksum="c1d2e3f4a5b60103",
        )
        fx.register_extract(
            api, cycle["id"], None, registrar,
            domain=K.DOMAIN_FINANCE, record_count=4,
            coverage_start_date=K.REPORTING_YEAR_FLOOR, coverage_end_date=K.REPORTING_YEAR_CEILING,
            checksum="c1d2e3f4a5b60104",
        )

        first_page, first_meta = validate_paginated(
            api.list_frozen_files(analyst, cycle_id=cycle["id"], limit=2, offset=0)
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api.list_frozen_files(analyst, cycle_id=cycle["id"], limit=2, offset=2)
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2

        finance_page, finance_meta = validate_paginated(
            api.list_frozen_files(analyst, cycle_id=cycle["id"], domain=K.DOMAIN_FINANCE)
        )
        assert len(finance_page) == 1
        assert finance_meta["total_count"] == 1
        assert finance_meta["has_more"] is False

        first_ids = {row["id"] for row in first_page}
        assert first_ids.isdisjoint({row["id"] for row in second_page})

        refreshed = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_ledger(refreshed, active_record_count=1254)


class TestCoverageWindowValidity:
    """The coverage window is validated before anything else about it."""

    def test_inverted_and_out_of_year_windows_share_one_error_and_cost_no_version(
        self, api, registrar
    ):
        """One error identifier covers both an inverted window and one outside the reporting year.

        PRD 3.1: "`coverage_start_date` must be on or before `coverage_end_date`, and both dates
        must fall inside the cycle's reporting year — the closed span running from 1 July of the
        year before `collection_year` through 30 June of `collection_year` itself."

        Design: Corner/validations/corner_val_coverage_window_must_be_ordered_and_inside_the_reporting_year
        """
        cycle = fx.create_cycle(api, registrar)

        inverted = api.register_frozen_file(
            cycle["id"],
            f.make_frozen_file_payload(
                cycle["version"],
                coverage_start_date="2026-10-15",
                coverage_end_date="2026-09-01",
                checksum="c1d2e3f4a5b60151",
            ),
            registrar,
        )
        validate_error(inverted, ApiErrorId.INVALID_COVERAGE_WINDOW, 422)

        before_the_year = api.register_frozen_file(
            cycle["id"],
            f.make_frozen_file_payload(
                cycle["version"],
                coverage_start_date="2026-06-01",
                coverage_end_date="2026-08-01",
                checksum="c1d2e3f4a5b60152",
            ),
            registrar,
        )
        validate_error(before_the_year, ApiErrorId.INVALID_COVERAGE_WINDOW, 422)

        untouched = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_version(untouched, 1, "cycle")
        assert_cycle_ledger(untouched, frozen_file_count=0, active_record_count=0)

        accepted = validate_success(
            api.register_frozen_file(
                cycle["id"],
                f.make_frozen_file_payload(
                    cycle["version"],
                    coverage_start_date="2026-09-01",
                    coverage_end_date="2026-10-15",
                    checksum="c1d2e3f4a5b60153",
                ),
                registrar,
            ),
            201,
        )
        assert accepted["status"] == K.FROZEN_FILE_ACTIVE
        after = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_version(after, 2, "cycle")
        assert_cycle_ledger(after, frozen_file_count=1)


class TestClosedCoverageWindowGeometry:
    """A coverage window is a closed date interval, so adjacency collides."""

    @staticmethod
    def _incumbent(api, registrar):
        cycle = fx.create_cycle(api, registrar)
        first = fx.register_extract(
            api, cycle["id"], cycle["version"], registrar,
            domain=K.DOMAIN_ENROLLMENT, record_count=1000,
            coverage_start_date="2026-09-01", coverage_end_date="2026-10-15",
            checksum="a1b2c3d4e5f60017",
        )
        return cycle, first

    def test_second_enrollment_extract_starting_on_the_incumbents_end_date_is_an_overlap(
        self, api, registrar
    ):
        """A peer ending on the new extract's start date occupies that day too.

        PRD 2.11: "An extract that ends on 2026-10-15 covers 2026-10-15, so a second extract for
        the same domain starting on 2026-10-15 double-counts that day and is an overlap."

        Design: Difficulty/resource_temporal_overlap/frozen_file_closed_coverage_windows_reject_shared_end_date
        """
        cycle, first = self._incumbent(api, registrar)
        refreshed = validate_success(api.get_reporting_cycle(cycle["id"], registrar))

        clash = api.register_frozen_file(
            cycle["id"],
            f.make_frozen_file_payload(
                refreshed["version"],
                domain=K.DOMAIN_ENROLLMENT,
                record_count=100,
                coverage_start_date="2026-10-15",
                coverage_end_date="2026-11-30",
                checksum="c3d4e5f6a7b80018",
            ),
            registrar,
        )
        validate_error(clash, ApiErrorId.COVERAGE_WINDOW_OVERLAP, 409)

        incumbent = validate_success(api.get_frozen_file(first["id"], registrar))
        assert incumbent["status"] == K.FROZEN_FILE_ACTIVE
        still_open = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_posture(still_open, K.POSTURE_OPEN)
        assert_cycle_ledger(still_open, active_record_count=1000, frozen_file_count=1)

    def test_one_day_gap_is_accepted_and_another_domain_may_hold_the_same_window(
        self, api, registrar
    ):
        """A one-day gap clears the closed interval, and the scan is scoped to one domain.

        PRD 2.11: "Adjacency therefore collides: `[2026-09-01, 2026-10-15]` and
        `[2026-10-15, 2026-11-30]` conflict, while a one-day gap — `[…, 2026-10-14]` followed by
        `[2026-10-15, …]` — is accepted."

        Design: Difficulty/resource_temporal_overlap/frozen_file_closed_coverage_windows_reject_shared_end_date
        """
        cycle, first = self._incumbent(api, registrar)
        second_version = validate_success(api.get_reporting_cycle(cycle["id"], registrar))["version"]

        gapped = validate_success(
            api.register_frozen_file(
                cycle["id"],
                f.make_frozen_file_payload(
                    second_version,
                    domain=K.DOMAIN_ENROLLMENT,
                    record_count=100,
                    coverage_start_date="2026-10-16",
                    coverage_end_date="2026-11-30",
                    checksum="d4e5f6a7b8c90019",
                ),
                registrar,
            ),
            201,
        )
        assert gapped["coverage_start_date"] == "2026-10-16"
        assert gapped["status"] == K.FROZEN_FILE_ACTIVE
        assert_null(gapped["supersedes_frozen_file_id"], "supersedes_frozen_file_id")

        third_version = validate_success(api.get_reporting_cycle(cycle["id"], registrar))["version"]
        other_domain = validate_success(
            api.register_frozen_file(
                cycle["id"],
                f.make_frozen_file_payload(
                    third_version,
                    domain=K.DOMAIN_COMPLETIONS,
                    record_count=50,
                    coverage_start_date="2026-09-01",
                    coverage_end_date="2026-10-15",
                    checksum="e5f6a7b8c9d00020",
                ),
                registrar,
            ),
            201,
        )
        assert other_domain["domain"] == K.DOMAIN_COMPLETIONS
        assert other_domain["status"] == K.FROZEN_FILE_ACTIVE

        incumbent = validate_success(api.get_frozen_file(first["id"], registrar))
        assert incumbent["status"] == K.FROZEN_FILE_ACTIVE

        rows, _meta = validate_paginated(api.list_frozen_files(registrar, cycle_id=cycle["id"]))
        assert len(rows) == 3
        final = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_ledger(final, active_record_count=1150)
        assert_cycle_posture(final, K.POSTURE_OPEN)


class TestActiveRecordLedger:
    """The two derived ledgers on the cycle, rewritten on every extract status change."""

    def test_a_superseded_extract_leaves_the_record_total_as_its_replacement_enters(
        self, api, registrar
    ):
        """Re-registering the identical window supersedes the incumbent instead of double counting.

        PRD 3.1: "`active_record_count` is the sum of `record_count` over the cycle's extracts
        whose `status` is either `ACTIVE` or `LOCKED`, with an empty set yielding 0 — so a
        superseded extract's records leave the total at the very moment its replacement is
        created, and the replacement's records enter it."

        Design: Corner/calculations/corner_calc_active_record_ledger_excludes_superseded_extracts
        """
        cycle = fx.create_cycle(api, registrar)
        first = fx.register_extract(
            api, cycle["id"], cycle["version"], registrar,
            domain=K.DOMAIN_ENROLLMENT, record_count=1000,
            coverage_start_date="2026-09-01", coverage_end_date="2026-10-15",
            checksum="c1d2e3f4a5b60137",
        )
        second = fx.register_extract(
            api, cycle["id"], None, registrar,
            domain=K.DOMAIN_COMPLETIONS, record_count=1500,
            coverage_start_date="2026-09-01", coverage_end_date="2026-10-15",
            checksum="c1d2e3f4a5b60138",
        )
        current_version = validate_success(api.get_reporting_cycle(cycle["id"], registrar))["version"]

        replacement = validate_success(
            api.register_frozen_file(
                cycle["id"],
                f.make_frozen_file_payload(
                    current_version,
                    domain=K.DOMAIN_ENROLLMENT,
                    record_count=1100,
                    coverage_start_date="2026-09-01",
                    coverage_end_date="2026-10-15",
                    checksum="c1d2e3f4a5b60139",
                ),
                registrar,
            ),
            201,
        )

        superseded = validate_success(api.get_frozen_file(first["id"], registrar))
        assert superseded["status"] == K.FROZEN_FILE_SUPERSEDED
        assert_version(superseded, 2, "superseded extract")
        assert replacement["supersedes_frozen_file_id"] == first["id"]
        assert replacement["status"] == K.FROZEN_FILE_ACTIVE
        assert_version(replacement, 1, "replacement extract")

        untouched = validate_success(api.get_frozen_file(second["id"], registrar))
        assert untouched["status"] == K.FROZEN_FILE_ACTIVE

        final = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_cycle_ledger(final, active_record_count=2600, frozen_file_count=2)

        _rows, superseded_meta = validate_paginated(
            api.list_frozen_files(registrar, cycle_id=cycle["id"], status=K.FROZEN_FILE_SUPERSEDED)
        )
        assert superseded_meta["total_count"] == 1
        _rows, chain_meta = validate_paginated(
            api.list_frozen_files(registrar, supersedes_frozen_file_id=first["id"])
        )
        assert chain_meta["total_count"] == 1


class TestOptimisticConcurrencyOnExtractRegistration:
    """expected_cycle_version guards the one write that can discard unseen governance state."""

    def test_a_stale_expected_cycle_version_is_refused_and_the_refreshed_retry_lands(
        self, api, registrar
    ):
        """The token must equal the cycle's current version, and the refusal stores nothing.

        PRD 2.8: "If `expected_cycle_version` does not equal the reporting cycle's current
        `version`, the request is rejected with `ERR_STALE_CYCLE_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_stale_expected_cycle_version_is_refused_then_the_refreshed_write_lands
        """
        cycle = fx.create_cycle(api, registrar)
        assert_version(cycle, 1, "cycle")
        fx.register_extract(
            api, cycle["id"], cycle["version"], registrar,
            domain=K.DOMAIN_ENROLLMENT, record_count=1000, checksum="c1d2e3f4a5b60169",
        )
        after_first = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_version(after_first, 2, "cycle")

        stale_payload = f.make_frozen_file_payload(
            cycle["version"], domain=K.DOMAIN_HR, record_count=400, checksum="c1d2e3f4a5b60170"
        )
        stale = api.register_frozen_file(cycle["id"], stale_payload, registrar)
        validate_error(stale, ApiErrorId.STALE_CYCLE_VERSION, 412)

        unchanged = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_version(unchanged, 2, "cycle")
        assert_cycle_ledger(unchanged, frozen_file_count=1, active_record_count=1000)
        rows, _meta = validate_paginated(api.list_frozen_files(registrar, cycle_id=cycle["id"]))
        assert [row["checksum"] for row in rows] == ["c1d2e3f4a5b60169"]

        refreshed_payload = dict(stale_payload, expected_cycle_version=unchanged["version"])
        accepted = validate_success(
            api.register_frozen_file(cycle["id"], refreshed_payload, registrar), 201
        )
        assert accepted["status"] == K.FROZEN_FILE_ACTIVE
        assert_null(accepted["supersedes_frozen_file_id"], "supersedes_frozen_file_id")

        final = validate_success(api.get_reporting_cycle(cycle["id"], registrar))
        assert_version(final, 3, "cycle")
        assert_cycle_ledger(final, frozen_file_count=2, active_record_count=1400)


class TestDeclaredTypeConstraints:
    """The schema band refuses undeclared enum members and negative counts alike."""

    def test_an_undeclared_outcome_and_a_negative_record_count_both_store_nothing(
        self, api, registrar
    ):
        """Both violations resolve to the same schema error and leave the store untouched.

        PRD 2.12: "Request-body schema: every field the endpoint marks required is present, JSON
        types match, enum fields carry a declared member, calendar dates are `YYYY-MM-DD`,
        instants are ISO 8601 UTC, counts and cent amounts are non-negative integers, and
        declared free-text length bounds hold — `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/corner_type_constraints_reject_bad_enum_negative_count_and_out_of_range
        """
        scenario = fx.census_locked_cycle(api, record_count=2, checksum="c1d2e3f4a5b60110")
        scenario = fx.cohort_on_scenario(api, scenario)

        bad_enum = api.add_cohort_member(
            scenario.cohort_id,
            f.make_member_payload("S009", outcome="GRADUATED"),
            registrar,
        )
        validate_error(bad_enum, ApiErrorId.INVALID_REQUEST, 400)

        current_version = validate_success(
            api.get_reporting_cycle(scenario.cycle_id, registrar)
        )["version"]
        negative_count = api.register_frozen_file(
            scenario.cycle_id,
            f.make_frozen_file_payload(
                current_version,
                domain=K.DOMAIN_COMPLETIONS,
                record_count=-5,
                checksum="c1d2e3f4a5b60111",
            ),
            registrar,
        )
        validate_error(negative_count, ApiErrorId.INVALID_REQUEST, 400)

        cohort = validate_success(api.get_cohort(scenario.cohort_id, registrar))
        assert cohort["initial_count"] == 0
        _rows, meta = validate_paginated(
            api.list_frozen_files(
                registrar, cycle_id=scenario.cycle_id, domain=K.DOMAIN_COMPLETIONS
            )
        )
        assert meta["total_count"] == 0
        final = validate_success(api.get_reporting_cycle(scenario.cycle_id, registrar))
        assert_cycle_ledger(final, active_record_count=2)
