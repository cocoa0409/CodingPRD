"""Endpoint mechanics: partial update, the clock, the idle sweep and list filters.

These four exercise the endpoint contract rather than any single business rule —
what a PATCH is allowed to touch, what the clock endpoint returns, what the daily
sweep reports when there is nothing to do, and how the list filters resolve the
wiring an approval creates.
"""
from test_helpers import (
    assert_millis_instant_format,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_1,
    ANALYST_1,
    COUNSELOR_1,
    make_benefits_admin_headers,
    make_eligibility_analyst_headers,
    make_enrollment_counselor_headers,
)


def test_patching_a_retiree_touches_only_the_keys_it_names(api):
    """Two partial edits, two version bumps, and the frozen columns stay frozen.

    PRD 3.3 lists exactly what an update may reach: "A `BenefitsAdmin` or
    `EligibilityAnalyst` may update `medicare_status`,
    `medicare_part_b_effective_date`, `other_group_coverage_employer_size`,
    `active_employment_flag`, `esrd_flag`, `esrd_entitlement_date`,
    `disability_entitlement_flag` and `credited_service_months`. `hire_date` and
    the `grandfathered_group` derived from it are immutable, and
    `eligibility_status` is never written by an update". `eligibility_points` is
    not frozen, though, because PRD 3.3 pins the three moments that write it: it
    "is computed when the retiree record is created, rewritten whenever
    `credited_service_months` changes, and rewritten again whenever a new
    determination is run for that retiree." — 143 months is 11 service years, so
    the second edit takes it from 75 to 74 while the determination keeps the
    figure it froze. PRD 2.4 charges each accepted write one increment, since
    `version` "increases by exactly 1 on every mutation of that row".

    Design: Corner/endpoints/retiree_patch_updates_only_named_mutable_fields
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    certified = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    retiree = certified["retiree"]
    determination = certified["determination"]
    assert retiree["version"] == 3
    assert retiree["eligibility_points"] == 75
    assert retiree["grandfathered_group"] == "GRANDFATHERED_A"

    first = validate_success(
        api.patch_retiree(
            retiree["id"],
            f.retiree_patch_payload(
                overrides={"medicare_status": "MEDICARE_ELIGIBLE_NOT_ENROLLED"}
            ),
            make_benefits_admin_headers(ADMIN_1),
        )
    )
    assert first["medicare_status"] == "MEDICARE_ELIGIBLE_NOT_ENROLLED"
    assert first["version"] == 4
    assert first["credited_service_months"] == 150
    assert first["other_group_coverage_employer_size"] == 0
    assert first["active_employment_flag"] is False

    second = validate_success(
        api.patch_retiree(
            retiree["id"],
            f.retiree_patch_payload(
                overrides={
                    "credited_service_months": 143,
                    "other_group_coverage_employer_size": 250,
                    "active_employment_flag": True,
                }
            ),
            make_eligibility_analyst_headers(ANALYST_1),
        )
    )
    assert second["credited_service_months"] == 143
    assert second["other_group_coverage_employer_size"] == 250
    assert second["active_employment_flag"] is True
    assert second["version"] == 5
    assert second["medicare_status"] == "MEDICARE_ELIGIBLE_NOT_ENROLLED"
    assert second["grandfathered_group"] == "GRANDFATHERED_A"
    assert second["hire_date"] == "1990-06-01"
    assert second["eligibility_status"] == "ELIGIBLE"
    assert second["determination_sequence"] == 1
    assert second["eligibility_points"] == 74

    reread = fx.reload_retiree(api, retiree["id"])
    assert reread == second

    frozen = fx.reload_determination(api, determination["id"])
    assert frozen["points"] == 75
    assert frozen["status"] == "CERTIFIED"


def test_the_clock_endpoint_echoes_the_new_reading_and_mutates_nothing(api):
    """A single-field body back, twice, and no row rewritten in between.

    PRD 2.4: "A `BenefitsAdmin` may reposition it by calling
    `POST /_clock/set_current_utc` with a `to_iso8601` instant; the response body
    is an object carrying a single `current_utc` field holding the new clock
    reading. Setting the clock mutates no entity — it changes only what every
    subsequent request sees as "now"." Because no entity is mutated, the row
    created before the move must come back byte for byte afterwards, PRD 2.4
    having already tied any rewrite to a counter: `version` "increases by exactly
    1 on every mutation of that row". Its stamps keep the declared rendering:
    "`created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with
    exactly three fractional digits."

    Design: Corner/endpoints/clock_endpoint_moves_logical_time_for_subsequent_writes
    """
    admin = make_benefits_admin_headers(ADMIN_1)

    first_reading = validate_success(api.set_clock_to("2026-10-20T00:00:00Z", admin))
    assert list(first_reading) == ["current_utc"]

    year_2027 = validate_success(
        api.create_plan_year(f.plan_year_payload(2027), admin), expected_status=201
    )
    assert_millis_instant_format(year_2027["created_at"], "created_at")
    assert_millis_instant_format(year_2027["updated_at"], "updated_at")

    second_reading = validate_success(api.set_clock_to("2027-03-09T12:34:56Z", admin))
    assert list(second_reading) == ["current_utc"]
    assert second_reading["current_utc"] != first_reading["current_utc"]

    year_2028 = validate_success(
        api.create_plan_year(
            f.plan_year_payload(
                2028,
                overrides={
                    "open_enrollment_start": "2027-10-15T00:00:00Z",
                    "open_enrollment_end": "2027-11-15T00:00:00Z",
                    "coverage_start": "2028-01-01T00:00:00Z",
                },
            ),
            admin,
        ),
        expected_status=201,
    )
    assert_millis_instant_format(year_2028["created_at"], "created_at")

    untouched = fx.reload_plan_year(api, year_2027["id"])
    assert untouched["created_at"] == year_2027["created_at"]
    assert untouched["updated_at"] == year_2027["updated_at"]
    assert untouched["status"] == "DRAFT"
    assert untouched["version"] == 1


def test_the_daily_sweep_on_an_idle_system_reports_six_zeros(api):
    """Nothing to age, so every counter is present and zero, twice over.

    PRD 3.9: "It runs across every invoice, enrollment, plan option,
    reimbursement account and claim in the system with no plan-year filter, and it
    reports six counters in its response body: `processed_invoice_count`,
    `activated_enrollment_count`, `suspended_enrollment_count`,
    `lapsed_enrollment_count`, `applied_plan_change_count` and
    `recomputed_msp_count`." With no enrollment and no invoice there is nothing
    for the phases to select, and phase 3 selects nothing either because it takes
    "Every plan option whose `change_notice_issued_at` is non-null and whose
    `pending_change_effective_date` is at or before the clock" and no notice was
    issued. An untouched option therefore keeps its `version`, which PRD 2.4 says
    "increases by exactly 1 on every mutation of that row".

    Design: Corner/endpoints/daily_run_on_quiet_system_returns_all_zero_counts
    """
    program = fx.standard_program(api)
    option = program["pre65_core"]

    fx.set_clock(api, "2027-02-01T00:00:00Z")
    counters = ("processed_invoice_count", "activated_enrollment_count",
                "suspended_enrollment_count", "lapsed_enrollment_count",
                "applied_plan_change_count", "recomputed_msp_count")

    for _run in range(2):
        summary = validate_success(api.daily_run(make_benefits_admin_headers(ADMIN_1)))
        for counter in counters:
            assert counter in summary, counter
            assert summary[counter] == 0, counter
            assert isinstance(summary[counter], int)
            assert not isinstance(summary[counter], bool)

    quiet = fx.reload_plan_option(api, option["id"])
    assert quiet["status"] == "ACTIVE"
    assert quiet["version"] == option["version"]


def test_the_list_filters_resolve_the_wiring_an_approval_creates(api):
    """Forward and reverse lookups, and a conjunctive filter that matches nothing.

    PRD 3.5: "That enrollment carries `retiree_id` and `plan_year_id` from the
    election, `plan_option_id` copied from the election's
    `requested_plan_option_id`, and `election_event_id` pointing back at the
    election that produced it." and "The election records
    `resulting_enrollment_id`". PRD 4 exposes both directions: enrollments are
    listed with a "filter by retiree_id, plan_year_id, plan_option_id or
    election_event_id to reach every enrollment referencing a given parent" and
    election events with a "filter by retiree_id, plan_year_id,
    requested_plan_option_id or resulting_enrollment_id to reach every event
    referencing a given parent". Filters compose, and PRD 2.3 reads the count off
    the filtered set: "`total_count` reports the number of rows matching the
    filters before the page window is applied".

    Design: Corner/endpoints/enrollment_listing_filtered_by_foreign_keys_cross_reference
    """
    program = fx.standard_program(api)
    plan_year = program["plan_year"]
    pre65_core = program["pre65_core"]
    exch_hra = fx.make_exch_hra(api, plan_year["id"])

    first = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    second = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r5_payload())

    first_pair = fx.make_enrollment(
        api, first["retiree"]["id"], plan_year["id"], pre65_core["id"]
    )
    second_pair = fx.make_enrollment(
        api, second["retiree"]["id"], plan_year["id"], exch_hra["id"]
    )
    counselor = make_enrollment_counselor_headers(COUNSELOR_1)

    by_retiree, by_retiree_meta = validate_paginated(
        api.list_enrollments(counselor, {"retiree_id": first["retiree"]["id"]})
    )
    assert by_retiree_meta["total_count"] == 1
    assert by_retiree_meta["has_more"] is False
    assert by_retiree[0]["id"] == first_pair["enrollment"]["id"]
    assert by_retiree[0]["plan_option_id"] == pre65_core["id"]
    assert by_retiree[0]["election_event_id"] == first_pair["election"]["id"]

    by_option, by_option_meta = validate_paginated(
        api.list_enrollments(counselor, {"plan_option_id": exch_hra["id"]})
    )
    assert by_option_meta["total_count"] == 1
    assert by_option[0]["id"] == second_pair["enrollment"]["id"]
    assert by_option[0]["retiree_id"] == second["retiree"]["id"]

    crossed, crossed_meta = validate_paginated(
        api.list_enrollments(
            counselor,
            {"retiree_id": first["retiree"]["id"], "plan_option_id": exch_hra["id"]},
        )
    )
    assert crossed == []
    assert crossed_meta["total_count"] == 0
    assert crossed_meta["has_more"] is False

    reverse, reverse_meta = validate_paginated(
        api.list_election_events(
            counselor, {"resulting_enrollment_id": first_pair["enrollment"]["id"]}
        )
    )
    assert reverse_meta["total_count"] == 1
    assert reverse[0]["id"] == first_pair["election"]["id"]
    assert reverse[0]["status"] == "APPROVED"

    assert (
        first_pair["election"]["resulting_enrollment_id"]
        == first_pair["enrollment"]["id"]
    )
    assert (
        second_pair["election"]["resulting_enrollment_id"]
        == second_pair["enrollment"]["id"]
    )
    assert fx.reload_plan_option(api, pre65_core["id"])["enrolled_count"] == 1
    assert fx.reload_plan_option(api, exch_hra["id"])["enrolled_count"] == 1
