"""The layers over the domain: two version guards, one page, one threshold band.

These four tests exercise machinery that is not itself part of any workflow — the
optimistic-concurrency parameters carried on two different creations, the
composition of a filter with a limit and an offset, and the inclusive edge of a
derived posture band — each in the one place the contract puts it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_STALE_CAPITAL_PROJECT_VERSION,
    ERR_STALE_ENTRY_POINT_VERSION,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_is_null,
    assert_money_cents,
    assert_page,
    assert_status,
    assert_total_count,
)
from test_helpers.fixtures import (
    accepted_quarter,
    apply_for_funding,
    award_funding,
    build_registry,
    collect_sample,
    entry_point_version,
    read_entry_point,
    read_lab_result,
    read_project,
    register_entry_point,
    selected_project,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, FINANCE_OFFICER_HEADERS


def test_a_determination_built_on_a_stale_entry_point_version_is_refused(api):
    """The version guard rides on a creation, not on an update.

    The accepted 3.00 reading has already advanced the entry point's version, so an
    officer who kept the earlier number is refused at 412 and no determination row
    comes into being — the collection is still empty and the refused attempt did not
    itself advance the version. Re-reading and resubmitting the identical body then
    freezes exactly the numbers the first attempt would have frozen: a single
    quarter and an average of 3.00, which sits at three quarters of the limit and is
    therefore no exceedance, so the one quarter of data on a quarterly entry point
    is reported as the monitoring violation the first branch of the walk names.

    PRD: "If that value differs from the entry point's current `version`, the create
    is rejected with `ERR_STALE_ENTRY_POINT_VERSION` (HTTP 412) and the client must
    re-read the entry point before trying again."

    Design: Corner/complexity_layers/a_determination_built_on_a_stale_entry_point_version_is_rejected
    """
    registry = build_registry(api)
    accepted_quarter(api, registry, "2026Q2", 3.00)
    current = entry_point_version(api, registry["entry_point_id"])

    validate_error(
        api.create_determination(
            f.determination_payload(
                registry["entry_point_id"],
                registry["contaminant_id"],
                current - 1,
                period_end="2026Q2",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        ERR_STALE_ENTRY_POINT_VERSION,
        412,
    )
    assert_total_count(
        api.list_determinations(
            COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": registry["entry_point_id"]}
        ),
        0,
    )
    assert_equals(read_entry_point(api, registry["entry_point_id"]), "version", current)

    determination = validate_success(
        api.create_determination(
            f.determination_payload(
                registry["entry_point_id"],
                registry["contaminant_id"],
                current,
                period_end="2026Q2",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        201,
    )
    assert_status(determination, "DRAFT")
    assert_decimal(determination["lraa_ng_per_l"], 3.00, label="lraa_ng_per_l")
    assert_equals(determination, "quarters_used", 1)
    assert_equals(determination, "determination", "MONITORING_VIOLATION")
    assert_entry_point_posture(
        read_entry_point(api, registry["entry_point_id"]),
        posture="TRIGGERED",
        max_compliance_ratio=0.7500,
    )


def test_a_funding_application_against_a_stale_project_version_is_refused(api):
    """A second parent, a second parameter name, a second code.

    The first application is filed against the version the project carried at
    selection and awarded in full, and that award is exactly what moves the project
    on, so the finance officer's cached number is now stale. The second application
    is refused at 412 with the capital-project code and not the entry-point one, and
    the refusal leaves the applications collection at one row and the awarded total
    at 100000000 cents. Re-reading the project and resubmitting the same body is
    accepted as an ordinary submission with nothing awarded yet.

    PRD: "A mismatch with the project's current `version` is rejected with
    `ERR_STALE_CAPITAL_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/a_funding_application_against_a_stale_project_version_is_rejected
    """
    entry_point = register_entry_point(api)
    selected = selected_project(api, entry_point["id"], residuals_budget_cents=500000)
    project = selected["project"]
    stale_version = project["version"]

    first = apply_for_funding(
        api,
        project["id"],
        program="SRF_LOAN",
        amount_requested_cents=100000000,
        disadvantaged_community=False,
    )
    award_funding(api, first["id"], 100000000)
    moved_on = read_project(api, project["id"])
    assert moved_on["version"] != stale_version, (
        "the award must have advanced the project version"
    )

    body = f.funding_application_payload(
        stale_version,
        program="EC_GRANT",
        amount_requested_cents=200000000,
        disadvantaged_community=False,
    )
    stale_attempt = api.create_funding_application(
        project["id"], body, FINANCE_OFFICER_HEADERS
    )
    validate_error(stale_attempt, ERR_STALE_CAPITAL_PROJECT_VERSION, 412)
    assert stale_attempt.json()["data"]["error_id"] != ERR_STALE_ENTRY_POINT_VERSION, (
        "the two concurrency rules carry distinct codes"
    )
    assert_total_count(
        api.list_funding_applications(
            FINANCE_OFFICER_HEADERS, params={"capital_project_id": project["id"]}
        ),
        1,
    )
    assert_money_cents(
        read_project(api, project["id"])["funding_awarded_cents"],
        100000000,
        "funding_awarded_cents",
    )

    retry = validate_success(
        api.create_funding_application(
            project["id"],
            f.funding_application_payload(
                read_project(api, project["id"])["version"],
                program="EC_GRANT",
                amount_requested_cents=200000000,
                disadvantaged_community=False,
            ),
            FINANCE_OFFICER_HEADERS,
        ),
        201,
    )
    assert_status(retry, "SUBMITTED")
    assert_equals(retry, "program", "EC_GRANT")
    assert_is_null(retry, "awarded_cents", "forgiven_cents")


def test_sample_filtering_and_paging_compose_without_leaking_rows(api):
    """Three of five rows are in scope, and the count must describe the three.

    Five samples exist, three of them at the entry point under the filter. Read two
    at a time, the pages carry a total of three and never five, the first page
    promises more and the second does not, and an offset past the end is an empty
    page rather than an error. The two out-of-scope samples appear on none of the
    three pages, and the three in-scope rows come back once each in creation order.

    PRD: "The `meta` object of every list response carries `limit` and `offset` as
    they were applied, `total_count` as the number of rows matching the filters
    before pagination, and `has_more` as a boolean indicating whether rows remain
    beyond the current page."

    Design: Corner/complexity_layers/sample_filtering_and_paging_compose_without_leaking_rows
    """
    registry = build_registry(api)
    other = register_entry_point(api, label="EPTDS-02")
    in_scope = [
        collect_sample(
            api,
            registry["entry_point_id"],
            [registry["contaminant_id"]],
            collected_at=collected_at,
            preservative_lot=lot,
        )
        for collected_at, lot in (
            ("2026-05-10T08:00:00.000Z", "LOT-A1"),
            ("2026-05-15T08:00:00.000Z", "LOT-A2"),
            ("2026-05-20T08:00:00.000Z", "LOT-A3"),
        )
    ]
    out_of_scope = [
        collect_sample(
            api,
            other["id"],
            [registry["contaminant_id"]],
            collected_at=collected_at,
            preservative_lot=lot,
        )
        for collected_at, lot in (
            ("2026-05-11T08:00:00.000Z", "LOT-B1"),
            ("2026-05-16T08:00:00.000Z", "LOT-B2"),
        )
    ]

    assert_total_count(api.list_samples(COMPLIANCE_OFFICER_HEADERS), 5)

    scoped = {"entry_point_id": registry["entry_point_id"], "limit": 2, "offset": 0}
    first_page = assert_page(
        api.list_samples(COMPLIANCE_OFFICER_HEADERS, params=scoped),
        3,
        True,
        [in_scope[0]["id"], in_scope[1]["id"]],
    )
    second_page = assert_page(
        api.list_samples(
            COMPLIANCE_OFFICER_HEADERS,
            params={**scoped, "offset": 2},
        ),
        3,
        False,
        [in_scope[2]["id"]],
    )
    assert_page(
        api.list_samples(
            COMPLIANCE_OFFICER_HEADERS,
            params={**scoped, "offset": 4},
        ),
        3,
        False,
        [],
    )

    walked = first_page + second_page
    assert_created_at_ascending(walked)
    for row in walked:
        assert_equals(row, "entry_point_id", registry["entry_point_id"])
    excluded = {sample["id"] for sample in out_of_scope}
    assert excluded.isdisjoint({row["id"] for row in walked}), (
            f"The filter leaked rows from another entry point: {excluded}"
    )


def test_the_triggered_posture_band_opens_at_exactly_one_half_of_the_mcl(api):
    """One hundredth of a nanogram separates two entry points and two verdicts.

    Against a limit of 4.00 a reading of exactly 2.00 is a ratio of exactly 0.5000
    and lands inside the triggered band, while 1.99 is 0.4975 and stays compliant.
    The same two numbers straddle the qualifying-quarter rule the other way round,
    because qualifying demands a value strictly below the 2.00 trigger: the
    triggered entry point has a streak of zero and the compliant one a streak of
    one. Neither reading is censored at a detection limit of 1.00 and neither entry
    point has a violation open, and both are on quarterly monitoring off their first
    accepted result.

    PRD: "Failing that, it is `TRIGGERED` when `max_compliance_ratio` is at least
    0.5 and at most 1.0."

    Design: Corner/complexity_layers/the_triggered_posture_band_opens_at_exactly_one_half_of_the_mcl
    """
    at_the_band = build_registry(api, entry_point_overrides={"label": "EPTDS-06"})
    below_the_band = register_entry_point(api, label="EPTDS-07")
    inside = accepted_quarter(
        api, at_the_band, "2026Q2", 2.00, preservative_lot="LOT-EP6"
    )
    outside = accepted_quarter(
        api,
        {**at_the_band, "entry_point_id": below_the_band["id"]},
        "2026Q2",
        1.99,
        preservative_lot="LOT-EP7",
    )

    triggered_result = read_lab_result(api, inside["result_id"])
    assert_equals(triggered_result, "censored", False)
    assert_decimal(
        triggered_result["compliance_value_ng_per_l"], 2.00, label="compliance_value_ng_per_l"
    )
    assert_entry_point_posture(
        read_entry_point(api, at_the_band["entry_point_id"]),
        posture="TRIGGERED",
        monitoring_status="QUARTERLY",
        accepted_result_count=1,
        max_compliance_ratio=0.5000,
        consecutive_qualifying_quarters=0,
        open_violation_count=0,
    )

    compliant_result = read_lab_result(api, outside["result_id"])
    assert_equals(compliant_result, "censored", False)
    assert_decimal(
        compliant_result["compliance_value_ng_per_l"], 1.99, label="compliance_value_ng_per_l"
    )
    assert_entry_point_posture(
        read_entry_point(api, below_the_band["id"]),
        posture="COMPLIANT",
        monitoring_status="QUARTERLY",
        accepted_result_count=1,
        max_compliance_ratio=0.4975,
        consecutive_qualifying_quarters=1,
        open_violation_count=0,
    )
