"""Windowing a collection: the page, the count behind it and the ordering.

A list endpoint answers with the rows inside the requested window while reporting
how many rows matched the filters before the window was applied, so a caller can
tell an exhausted collection from a truncated one.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_ascending_by_created_at,
    assert_bps,
    assert_money,
    assert_page_ids,
)
from test_helpers.constants import ADDR_FARM
from test_helpers.test_users import (
    ANALYST,
    CLERK,
    HEARING_CLERK,
    INVESTIGATOR,
    REVIEWER,
)


def _three_draft_applications(api):
    """One claimant with a draft application on each of three parcels.

    None of the three is submitted, so no duplicate-application rule can fire and
    all three rows stay in ``DRAFT`` for the whole test.
    """
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    parcels = [
        fx.create_parcel(api, f.parcel()),
        fx.create_parcel(
            api,
            f.parcel(
                apn="P-0002",
                situs_address_normalized="2 BIRCH LN NORTHFIELD ST 10002",
                base_year_value_cents=20000000,
                market_value_cents=25000000,
            ),
        ),
        fx.create_parcel(
            api,
            f.parcel(
                apn="P-0003",
                situs_address_normalized="3 CEDAR CT NORTHFIELD ST 10003",
                base_year_value_cents=10000000,
                market_value_cents=12000000,
            ),
        ),
    ]
    applications = [
        validate_success(
            api.create_application(
                f.application(
                    parcel["id"],
                    taxpayer["id"],
                    program["id"],
                    claimed_address_normalized=parcel["situs_address_normalized"],
                ),
                CLERK,
            ),
            expected_status=201,
        )
        for parcel in parcels
    ]
    return {
        "program": program,
        "taxpayer": taxpayer,
        "parcels": parcels,
        "applications": applications,
    }


def test_a_window_of_two_over_three_applications_reports_the_full_count(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` in the `meta` object of the envelope, where `total_count` is the
    number of rows matching the filters before the window is applied and `has_more`
    indicates whether rows remain beyond it." PRD §2.3 also fixes the ordering:
    "Unless a specific endpoint states otherwise, every list endpoint returns its
    rows ordered by `created_at` ascending."

    Design: Corner/entities/application_list_paginates_with_total_count_and_has_more
    """
    world = _three_draft_applications(api)
    taxpayer_id = world["taxpayer"]["id"]
    first, second, third = world["applications"]

    rows, meta = validate_paginated(
        api.list_applications(CLERK, taxpayer_id=taxpayer_id, limit=2, offset=0)
    )
    assert len(rows) == 2, f"a limit of two returns two rows, got {len(rows)}"
    assert meta["limit"] == 2, f"the window is echoed, got limit {meta['limit']}"
    assert meta["offset"] == 0, f"the window is echoed, got offset {meta['offset']}"
    assert meta["total_count"] == 3, (
        f"three rows match the filter before windowing, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, (
        f"a third row remains beyond the window, got {meta['has_more']!r}"
    )
    assert_page_ids(rows, [first["id"], second["id"]])
    assert_ascending_by_created_at(rows)
    for row in rows:
        assert row["status"] == "DRAFT", (
            f"an unsubmitted application is still a draft, got {row['status']}"
        )
        assert row["taxpayer_id"] == taxpayer_id, (
            f"the filter must not admit another claimant's row, got {row['taxpayer_id']}"
        )

    # The second window exhausts the collection.
    tail, tail_meta = validate_paginated(
        api.list_applications(CLERK, taxpayer_id=taxpayer_id, limit=2, offset=2)
    )
    assert len(tail) == 1, f"only one row remains, got {len(tail)}"
    assert tail_meta["offset"] == 2, (
        f"the skipped-row count is echoed, got {tail_meta['offset']}"
    )
    assert tail_meta["total_count"] == 3, (
        f"the count behind the window is unchanged, got {tail_meta['total_count']}"
    )
    assert tail_meta["has_more"] is False, (
        f"nothing remains beyond the last row, got {tail_meta['has_more']!r}"
    )
    assert_page_ids(tail, [third["id"]])



def _two_registry_records_and_a_three_row_check_log(api):
    """Two occupancy records of different kinds and one claim with three cross-matches.

    The residence record comes from the deed registry and the rental record from a
    taxpayer affidavit, so the two differ in owner, parcel, occupancy kind and trust
    at once. The claimant also carries a 2025 and a 2026 income certification, and
    the claim's log holds a voter match, a deed match and a postal check with no
    registry row behind it.
    """
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    residence = fx.create_parcel(api, f.parcel())
    let_parcel = fx.create_parcel(api, f.farm_parcel())
    owner = fx.create_taxpayer(api, f.taxpayer_account())
    landlord = fx.create_taxpayer(
        api,
        f.taxpayer_account(
            full_name="NORMAN NEIGHBOR",
            date_of_birth="1960-07-22",
            ssn_last4="8765",
            mailing_address_normalized=ADDR_FARM,
        ),
    )
    residence_record = fx.add_ownership(api, residence["id"], owner["id"])
    rental_record = fx.add_ownership(
        api,
        let_parcel["id"],
        landlord["id"],
        ownership_pct_bps=5000,
        deed_recorded_date="2020-01-01",
        occupancy_type="RENTAL",
        occupancy_start_date="2020-01-01",
        source_system="TAXPAYER_AFFIDAVIT",
    )
    older_certification = fx.create_certification(
        api,
        owner["id"],
        certification_year=2025,
        household_income_cents=4000000,
        countable_asset_cents=1000000,
        household_size=2,
        recertification_due_date="2026-06-30",
    )
    newer_certification = fx.create_certification(
        api,
        owner["id"],
        certification_year=2026,
        household_income_cents=5000000,
        countable_asset_cents=1200000,
        household_size=2,
        recertification_due_date="2027-06-30",
    )
    fx.inject_matching_residency(api, owner["id"])
    application = fx.submitted_application(
        api, residence["id"], owner["id"], program["id"]
    )
    checks = fx.run_checks(
        api, application["id"], ["VOTER_REGISTRY", "DEED_REGISTRY", "USPS_NCOA"]
    )
    return {
        "owner": owner,
        "landlord": landlord,
        "residence_record": residence_record,
        "rental_record": rental_record,
        "older_certification": older_certification,
        "newer_certification": newer_certification,
        "application": application,
        "checks": checks,
    }


def _assert_default_window(meta, label):
    """Assert an unwindowed read reports the default page and nothing beyond it."""
    assert meta["limit"] == 10, f"{label}: omitted limit defaults to 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"{label}: omitted offset defaults to 0, got {meta['offset']}"
    assert meta["has_more"] is False, (
        f"{label}: the filtered row fits in one page, got {meta['has_more']!r}"
    )


def test_each_declared_filter_narrows_its_collection_instead_of_being_ignored(api):
    """PRD §2.3: "Each list endpoint also accepts a set of equality filters over its
    own columns ... ownership records may be narrowed by `parcel_id`, `taxpayer_id`,
    `occupancy_type` and `status` ... verification checks by `source` and `result`;
    income certifications by `certification_year` and `status` ... Every filter is
    optional and filters combine conjunctively." PRD §2.3 also fixes the window:
    "when it is omitted it defaults to 10 ... The `offset` parameter is the number of
    items to skip and defaults to 0."

    Design: Corner/endpoints/ownership_verification_and_certification_list_reads_honour_their_query_filters
    """
    world = _two_registry_records_and_a_three_row_check_log(api)
    residence_record = world["residence_record"]
    rental_record = world["rental_record"]
    assert residence_record["status"] == "VERIFIED", (
        f"a deed-registry record is trusted on sight, got {residence_record['status']}"
    )
    assert rental_record["status"] == "UNVERIFIED", (
        f"an affidavit record is not, got {rental_record['status']}"
    )

    by_owner, owner_meta = validate_paginated(
        api.list_ownership_records(ANALYST, taxpayer_id=world["owner"]["id"])
    )
    assert owner_meta["total_count"] == 1, (
        f"only one of the two records belongs to the owner, got {owner_meta['total_count']}"
    )
    assert_page_ids(by_owner, [residence_record["id"]])
    assert by_owner[0]["occupancy_type"] == "PRIMARY_RESIDENCE", (
        f"the owner's record is the residence, got {by_owner[0]['occupancy_type']}"
    )
    _assert_default_window(owner_meta, "ownership by taxpayer")

    by_kind, kind_meta = validate_paginated(
        api.list_ownership_records(REVIEWER, occupancy_type="RENTAL")
    )
    assert kind_meta["total_count"] == 1, (
        f"only one record is a letting, got {kind_meta['total_count']}"
    )
    assert_page_ids(by_kind, [rental_record["id"]])
    assert by_kind[0]["taxpayer_id"] == world["landlord"]["id"], (
        f"the letting belongs to the landlord, got {by_kind[0]['taxpayer_id']}"
    )
    _assert_default_window(kind_meta, "ownership by occupancy type")

    single = validate_success(
        api.get_ownership_record(residence_record["id"], REVIEWER)
    )
    assert_bps(single, "ownership_pct_bps", 10000)
    assert single["occupancy_end_date"] is None, (
        f"the residence interval is still open-ended, got {single['occupancy_end_date']}"
    )

    application_id = world["application"]["id"]
    by_source, source_meta = validate_paginated(
        api.list_verification_checks(application_id, CLERK, source="VOTER_REGISTRY")
    )
    assert source_meta["total_count"] == 1, (
        f"one of the three cross-matches read the voter roll, got {source_meta['total_count']}"
    )
    assert by_source[0]["source"] == "VOTER_REGISTRY", (
        f"the source filter must not admit another registry, got {by_source[0]['source']}"
    )
    assert by_source[0]["result"] == "MATCH", (
        f"the seeded voter row agrees with the claim, got {by_source[0]['result']}"
    )
    _assert_default_window(source_meta, "checks by source")

    by_result, result_meta = validate_paginated(
        api.list_verification_checks(application_id, CLERK, result="NO_RECORD")
    )
    assert result_meta["total_count"] == 1, (
        "only the postal check had no registry row behind it, got "
        f"{result_meta['total_count']}"
    )
    assert by_result[0]["source"] == "USPS_NCOA", (
        f"the fruitless check was the postal one, got {by_result[0]['source']}"
    )
    assert by_result[0]["result"] == "NO_RECORD", (
        f"the result filter must not admit a match, got {by_result[0]['result']}"
    )
    _assert_default_window(result_meta, "checks by result")

    by_year, year_meta = validate_paginated(
        api.list_income_certifications(
            world["owner"]["id"], REVIEWER, certification_year=2025
        )
    )
    assert year_meta["total_count"] == 1, (
        f"one of the two certifications is for 2025, got {year_meta['total_count']}"
    )
    assert_page_ids(by_year, [world["older_certification"]["id"]])
    assert by_year[0]["certification_year"] == 2025, (
        f"the year filter must not admit 2026, got {by_year[0]['certification_year']}"
    )
    assert_money(by_year[0], "household_income_cents", 4000000)
    _assert_default_window(year_meta, "certifications by year")


def test_a_filter_naming_an_unreached_state_answers_with_an_empty_page(api):
    """PRD §2.3: "Each list endpoint also accepts a set of equality filters over its
    own columns ... fraud cases by `taxpayer_id`, `grant_id`, `investigation_status`
    and `recovery_status` ... and appeals by `notice_id`, `taxpayer_id`, `docket_id`
    and `status`. Every filter is optional and filters combine conjunctively." PRD
    §2.3 defines the count a filtered read reports: "`total_count` is the number of
    rows matching the filters before the window is applied".

    Design: Corner/endpoints/case_and_appeal_list_reads_honour_status_filters_and_return_empty_pages
    """
    world = fx.approved_homestead_world(api)
    taxpayer_id = world["taxpayer"]["id"]
    case = fx.open_fraud_case(
        api,
        world["grant_id"],
        taxpayer_id,
        improper_start_tax_year=2024,
        improper_end_tax_year=2025,
    )
    assert case["investigation_status"] == "OPEN", (
        f"a freshly opened case is under investigation, got {case['investigation_status']}"
    )

    notices, notice_meta = validate_paginated(
        api.list_notices(taxpayer_id, CLERK, notice_type="SUSPENSION")
    )
    assert notice_meta["total_count"] == 1, (
        f"opening the case mails one suspension notice, got {notice_meta['total_count']}"
    )
    notice = notices[0]
    assert notice["subject_id"] == world["grant_id"], (
        f"the notice is mailed against the suspended grant, got {notice['subject_id']}"
    )
    assert notice["appealable"] is True, (
        f"a suspension is an adverse action, got {notice['appealable']!r}"
    )
    appeal = fx.file_appeal(
        api,
        notice["id"],
        taxpayer_id,
        grounds="The occupancy claimed in 2024 and 2025 was continuous and genuine.",
    )

    open_cases, open_meta = validate_paginated(
        api.list_fraud_cases(INVESTIGATOR, taxpayer_id=taxpayer_id)
    )
    assert open_meta["total_count"] == 1, (
        f"the household has exactly one case, got {open_meta['total_count']}"
    )
    assert_page_ids(open_cases, [case["id"]])
    assert open_cases[0]["investigation_status"] == "OPEN", (
        f"the case is still open, got {open_cases[0]['investigation_status']}"
    )
    assert open_cases[0]["recovery_status"] == "NONE", (
        f"no recovery has been raised yet, got {open_cases[0]['recovery_status']}"
    )
    _assert_default_window(open_meta, "cases by taxpayer")

    # No investigation has been substantiated, so this filter matches nothing.
    no_cases, no_case_meta = validate_paginated(
        api.list_fraud_cases(INVESTIGATOR, investigation_status="SUBSTANTIATED")
    )
    assert no_cases == [], (
        f"a filter on an unreached state must match no rows, got {no_cases}"
    )
    assert no_case_meta["total_count"] == 0, (
        f"and must report a count of zero, got {no_case_meta['total_count']}"
    )
    _assert_default_window(no_case_meta, "cases by unreached status")

    filed, filed_meta = validate_paginated(api.list_appeals(HEARING_CLERK, status="FILED"))
    assert filed_meta["total_count"] == 1, (
        f"one appeal has been filed, got {filed_meta['total_count']}"
    )
    assert_page_ids(filed, [appeal["id"]])
    assert filed[0]["notice_id"] == notice["id"], (
        f"the appeal names the notice it contests, got {filed[0]['notice_id']}"
    )
    assert filed[0]["docket_id"] is None, (
        f"a filed appeal has not been docketed yet, got {filed[0]['docket_id']}"
    )
    _assert_default_window(filed_meta, "appeals by status")

    dismissed, dismissed_meta = validate_paginated(
        api.list_appeals(HEARING_CLERK, status="DISMISSED")
    )
    assert dismissed == [], (
        "nothing has been dismissed, so the page must be empty rather than fall "
        f"back to the unfiltered collection: {dismissed}"
    )
    assert dismissed_meta["total_count"] == 0, (
        f"and the count behind it must be zero, got {dismissed_meta['total_count']}"
    )
    _assert_default_window(dismissed_meta, "appeals by unreached status")
