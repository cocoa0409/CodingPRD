"""Request validation, authorization gating and the rejection-priority ladder."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ALLOCATION_RUN_IN_USE,
    ERR_BATCH_HAS_OPEN_TRANSACTIONS,
    ERR_CREDIT_INSUFFICIENT,
    ERR_DELIVERY_BELOW_MINIMUM,
    ERR_DUPLICATE_CODE,
    ERR_INVALID_REQUEST,
    ERR_LIMITS_NOT_DERIVED,
    ERR_NOT_RESOURCE_OWNER,
    ERR_NO_COMPLIANCE_GAP,
    ERR_REPORTING_YEAR_MISMATCH,
    ERR_SOURCE_NOT_POINT,
    ERR_STALE_BATCH_VERSION,
    ERR_UNAUTHENTICATED,
    ERR_WATERSHED_MISMATCH,
    ERR_WLA_NOT_ALLOCATED,
)
from test_helpers.assertions import (
    assert_batch_buckets,
    assert_integer,
    assert_is_null,
    assert_load,
    assert_pagination_meta,
    assert_pct,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    PERMITTEE_1,
    PERMITTEE_2,
    PERMIT_WRITER,
    REGISTRY,
    make_producer_headers,
    make_raw_headers,
)
from test_helpers.types import ROLE_PROGRAM_ADMINISTRATOR


def test_blank_or_unrecognised_authentication_headers_are_all_unauthenticated(api):
    """A blank role, a blank user id and an unknown role are the same 401.

    "A request whose `X-User-ID` or `X-User-Role` header is missing, blank or
    unrecognised is rejected with `ERR_UNAUTHENTICATED` before any other
    consideration."

    Design: Corner/validations/request_with_blank_auth_headers_is_unauthenticated
    """
    fx.pin_clock(api)
    payload = f.watershed_payload(
        name="Scioto Headwaters",
        state_code="OH",
        watershed_code="SCR",
        pollutant="TOTAL_PHOSPHORUS",
        baseline_year=2020,
        baseline_load_lbs_yr=120000.00,
        eligible_zone_codes=["Z1", "Z2"],
    )

    blank_role = api.create_watershed(payload, make_raw_headers("admin-1", ""))
    blank_user = api.create_watershed(payload, make_raw_headers("", ROLE_PROGRAM_ADMINISTRATOR))
    unknown_role = api.create_watershed(payload, make_raw_headers("admin-1", "WatershedCzar"))

    validate_error(blank_role, ERR_UNAUTHENTICATED, 401)
    validate_error(blank_user, ERR_UNAUTHENTICATED, 401)
    validate_error(unknown_role, ERR_UNAUTHENTICATED, 401)

    accepted = validate_success(api.create_watershed(payload, ADMIN), 201)
    assert accepted["watershed_code"] == "SCR", accepted
    assert_integer(accepted["version"], 1, "version of the first accepted write")


def test_an_unknown_body_field_a_range_violation_and_an_oversized_limit_are_rejected(api):
    """Shape validation covers unknown keys, out-of-range values and query bounds.

    "every required field present, no unknown fields, every value of the declared
    type and within its declared range" and "`limit` defaults to 10 and is capped
    at 100"

    Design: Corner/validations/unknown_body_field_and_out_of_range_pagination_are_rejected
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)

    unknown_field = api.create_reach(
        f.reach_payload(
            watershed["id"],
            "R_MID",
            trading_zone_code="Z2",
            reach_class="MAINSTEM",
            delivery_factor=0.9000,
            stream_order=3,
        ),
        ANALYST,
    )
    out_of_range = api.create_reach(
        f.reach_payload(
            watershed["id"],
            "R_MID",
            trading_zone_code="Z2",
            reach_class="MAINSTEM",
            delivery_factor=1.5000,
        ),
        ANALYST,
    )
    oversized_limit = api.list_reaches(ANALYST, {"watershed_id": watershed["id"], "limit": 101})

    validate_error(unknown_field, ERR_INVALID_REQUEST, 422)
    validate_error(out_of_range, ERR_INVALID_REQUEST, 422)
    validate_error(oversized_limit, ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(api.list_reaches(ANALYST, {"watershed_id": watershed["id"]}))
    assert_pagination_meta(meta, 10, 0, 0, False)


def test_watershed_codes_are_global_while_reach_codes_are_only_watershed_unique(api):
    """The same reach code lives in two watersheds, but a watershed code cannot repeat.

    "`watershed_code` ... is unique across the whole system" and a reach's
    "`reach_code` unique within its watershed"

    Design: Corner/validations/duplicate_watershed_code_is_rejected_while_reach_code_uniqueness_stays_watershed_scoped
    """
    fx.pin_clock(api)
    scr = fx.scr_watershed(api)
    fx.make_reach(
        api,
        scr["id"],
        "R_OUT",
        trading_zone_code="Z2",
        reach_class="COMPLIANCE_POINT",
        delivery_factor=1.0000,
    )
    mad = fx.make_watershed(
        api,
        name="Mad River",
        state_code="OH",
        watershed_code="MAD",
        pollutant="TOTAL_PHOSPHORUS",
        baseline_year=2020,
        baseline_load_lbs_yr=90000.00,
        eligible_zone_codes=["Z1", "Z2"],
    )

    duplicate_watershed = api.create_watershed(
        f.watershed_payload(
            name="Scioto Headwaters Duplicate",
            state_code="OH",
            watershed_code="SCR",
            pollutant="TOTAL_PHOSPHORUS",
            baseline_year=2021,
            baseline_load_lbs_yr=100000.00,
            eligible_zone_codes=["Z1"],
        ),
        ADMIN,
    )

    validate_error(duplicate_watershed, ERR_DUPLICATE_CODE, 409)

    reused_in_other_watershed = validate_success(
        api.create_reach(
            f.reach_payload(
                mad["id"],
                "R_OUT",
                trading_zone_code="Z2",
                reach_class="COMPLIANCE_POINT",
                delivery_factor=1.0000,
            ),
            ANALYST,
        ),
        201,
    )
    assert reused_in_other_watershed["watershed_id"] == mad["id"], reused_in_other_watershed

    duplicate_reach = api.create_reach(
        f.reach_payload(
            scr["id"],
            "R_OUT",
            trading_zone_code="Z1",
            reach_class="HEADWATER",
            delivery_factor=0.8000,
        ),
        ANALYST,
    )

    validate_error(duplicate_reach, ERR_DUPLICATE_CODE, 409)

    _, scr_meta = validate_paginated(api.list_reaches(ANALYST, {"watershed_id": scr["id"]}))
    assert_pagination_meta(scr_meta, 10, 0, 1, False)
    _, mad_meta = validate_paginated(api.list_reaches(ANALYST, {"watershed_id": mad["id"]}))
    assert_pagination_meta(mad_meta, 10, 0, 1, False)


def test_a_source_assessment_may_not_reference_another_watersheds_reach(api):
    """A cross-watershed reach is a mismatch, not a missing row.

    "The referenced reach must belong to the same watershed as the assessment,
    otherwise the request is rejected with `ERR_WATERSHED_MISMATCH`."

    Design: Corner/validations/source_assessment_pointing_at_another_watersheds_reach_is_rejected
    """
    fx.pin_clock(api)
    scr = fx.scr_watershed(api)
    r_scr = fx.make_reach(
        api,
        scr["id"],
        "R_MID",
        trading_zone_code="Z2",
        reach_class="MAINSTEM",
        delivery_factor=0.9000,
    )
    assessment = fx.make_assessment(api, scr["id"])
    mad = fx.make_watershed(
        api,
        name="Mad River",
        state_code="OH",
        watershed_code="MAD",
        pollutant="TOTAL_PHOSPHORUS",
        baseline_year=2020,
        baseline_load_lbs_yr=90000.00,
        eligible_zone_codes=["Z1", "Z2"],
    )
    r_mad = fx.make_reach(
        api,
        mad["id"],
        "R_FOREIGN",
        trading_zone_code="Z2",
        reach_class="MAINSTEM",
        delivery_factor=1.0000,
    )

    refused = api.create_source_assessment(
        f.source_assessment_payload(
            assessment["id"], r_mad["id"], "Foreign WWTP", "POINT", 20000.00, 0.8000
        ),
        ANALYST,
    )

    validate_error(refused, ERR_WATERSHED_MISMATCH, 422)

    accepted = validate_success(
        api.create_source_assessment(
            f.source_assessment_payload(
                assessment["id"], r_scr["id"], "City WWTP", "POINT", 20000.00, 0.8000
            ),
            ANALYST,
        ),
        201,
    )
    assert accepted["reach_id"] == r_scr["id"], accepted
    assert accepted["status"] == "INVENTORIED", accepted

    _, meta = validate_paginated(
        api.list_source_assessments(ANALYST, {"tmdl_assessment_id": assessment["id"]})
    )
    assert_pagination_meta(meta, 10, 0, 1, False)


def test_a_permit_may_not_be_written_against_a_nonpoint_source(api):
    """Only a POINT source assessment can carry an effluent limit.

    "The referenced source assessment must have `source_type` of `POINT` — a
    nonpoint source has no effluent limit to write — otherwise the request is
    rejected with `ERR_SOURCE_NOT_POINT`."

    Design: Corner/validations/permit_on_a_nonpoint_source_assessment_is_rejected
    """
    world = fx.scr_base(api)

    refused = api.create_permit(
        f.permit_payload(
            world["watershed_id"],
            world["sa_n1"]["id"],
            "OH-9999",
            "user-permittee-1",
            design_flow_mgd=4.5000,
            current_annual_load_lbs=30000.00,
        ),
        PERMIT_WRITER,
    )

    validate_error(refused, ERR_SOURCE_NOT_POINT, 422)

    accepted = validate_success(
        api.create_permit(
            f.permit_payload(
                world["watershed_id"],
                world["sa_p2"]["id"],
                "OH-0002",
                "user-permittee-2",
                design_flow_mgd=1.2000,
                current_annual_load_lbs=6000.00,
            ),
            PERMIT_WRITER,
        ),
        201,
    )
    assert accepted["limit_status"] == "DRAFT_LIMITS", accepted
    assert accepted["compliance_status"] == "NOT_REPORTED", accepted
    assert accepted["source_assessment_id"] == world["sa_p2"]["id"], accepted

    _, meta = validate_paginated(
        api.list_permits(PERMIT_WRITER, {"watershed_id": world["watershed_id"]})
    )
    assert_pagination_meta(meta, 10, 0, 1, False)
    _, nonpoint_meta = validate_paginated(
        api.list_permits(PERMIT_WRITER, {"source_assessment_id": world["sa_n1"]["id"]})
    )
    assert_pagination_meta(nonpoint_meta, 10, 0, 0, False)


def test_limits_and_reporting_are_both_refused_until_a_run_has_allocated_the_source(api):
    """Derivation needs an allocation and reporting needs a derivation.

    "If the source assessment has no `allocated_load_lbs_yr` ... the request is
    rejected with `ERR_WLA_NOT_ALLOCATED`" and reporting "requires the permit's
    `limit_status` to be `INTERIM` or `FINAL`, failing with `ERR_LIMITS_NOT_DERIVED`"

    Design: Corner/validations/derive_limits_before_any_allocation_run_is_rejected
    """
    world = fx.scr_base(api)
    permit = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p1"]["id"],
        permit_number="OH-0001",
        permittee_user_id="user-permittee-1",
        design_flow_mgd=4.5000,
        current_annual_load_lbs=30000.00,
    )

    too_early = api.derive_limits(permit["id"], PERMIT_WRITER)

    validate_error(too_early, ERR_WLA_NOT_ALLOCATED, 409)

    no_limits = api.file_annual_report(
        permit["id"], f.annual_report_payload(25000.00, 2026), PERMITTEE_1
    )

    validate_error(no_limits, ERR_LIMITS_NOT_DERIVED, 409)

    still_draft = validate_success(api.get_permit(permit["id"], PERMIT_WRITER))
    assert still_draft["limit_status"] == "DRAFT_LIMITS", still_draft
    assert still_draft["compliance_status"] == "NOT_REPORTED", still_draft
    assert_is_null(still_draft["reported_annual_load_lbs"], "reported_annual_load_lbs")
    assert_is_null(still_draft["wla_lbs_yr"], "wla_lbs_yr")

    fx.make_allocation_run(api, world["assessment_id"], "RUN-1")

    derived = validate_success(api.derive_limits(permit["id"], PERMIT_WRITER))

    assert derived["limit_status"] == "INTERIM", derived
    assert_load(derived["wla_lbs_yr"], 21888.00, "wla_lbs_yr")
    assert_load(derived["final_limit_lbs_yr"], 21888.00, "final_limit_lbs_yr")
    assert_pct(derived["required_reduction_pct"], 27.04, "required_reduction_pct")
    assert derived["schedule_tier"] == "TIER_B", derived
    assert_load(derived["interim_limit_lbs_yr"], 23916.00, "interim_limit_lbs_yr")
    assert_load(derived["applicable_limit_lbs_yr"], 23916.00, "applicable_limit_lbs_yr")
    assert derived["compliance_schedule_end_date"] == "2029-03-01", derived


def test_only_the_recorded_permittee_may_file_the_annual_report(api):
    """A second permittee is refused ownership of the first permittee's permit.

    "The acting `X-User-ID` must equal the permit's `permittee_user_id`, otherwise
    the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/annual_report_by_a_different_permittee_is_rejected_as_not_resource_owner
    """
    world = fx.scr_allocated(api)
    permit = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p1"]["id"],
        permit_number="OH-0001",
        permittee_user_id="user-permittee-1",
        design_flow_mgd=4.5000,
        current_annual_load_lbs=30000.00,
    )
    fx.derive_limits(api, permit["id"])

    intruder = api.file_annual_report(
        permit["id"], f.annual_report_payload(25000.00, 2026), PERMITTEE_2
    )

    validate_error(intruder, ERR_NOT_RESOURCE_OWNER, 403)

    untouched = validate_success(api.get_permit(permit["id"], PERMIT_WRITER))
    assert_is_null(untouched["reported_annual_load_lbs"], "reported_annual_load_lbs")
    assert untouched["compliance_status"] == "NOT_REPORTED", untouched
    assert_load(untouched["compliance_gap_lbs"], 0.00, "compliance_gap_lbs")

    owned = validate_success(
        api.file_annual_report(permit["id"], f.annual_report_payload(25000.00, 2026), PERMITTEE_1)
    )

    assert_load(owned["reported_annual_load_lbs"], 25000.00, "reported_annual_load_lbs")
    assert_load(owned["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")
    assert owned["compliance_status"] == "SHORTFALL", owned


def test_one_producer_cannot_register_a_project_under_another_producers_id(api):
    """The acting producer must be the producer named in the body.

    "A `Producer` may register a practice project only for its own `producer_id`,
    otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/practice_project_registered_for_another_producer_is_rejected
    """
    fx.pin_clock(api)
    watershed = fx.scr_watershed(api)
    reaches = fx.scr_reaches(api, watershed["id"])
    producer_a = fx.make_producer(api)
    producer_b = fx.make_producer(
        api,
        legal_name="Riverbend Acres LLC",
        county_code="OH-049",
        contact_email="ops@riverbend.example",
    )
    payload = f.practice_project_payload(
        producer_b["id"],
        reaches["r_up"]["id"],
        "T-777",
        practice_type="NUTRIENT_MANAGEMENT",
        enrolled_acres=40.00,
        pre_load_lbs_yr=400.00,
        post_load_lbs_yr=150.00,
    )

    impersonated = api.create_practice_project(payload, make_producer_headers(producer_a["id"]))

    validate_error(impersonated, ERR_NOT_RESOURCE_OWNER, 403)

    _, meta = validate_paginated(
        api.list_practice_projects(REGISTRY, {"producer_id": producer_b["id"]})
    )
    assert_pagination_meta(meta, 10, 0, 0, False)

    owned = validate_success(
        api.create_practice_project(payload, make_producer_headers(producer_b["id"])), 201
    )

    assert owned["producer_id"] == producer_b["id"], owned
    assert owned["status"] == "REGISTERED", owned
    assert owned["tract_code"] == "T-777", owned
    assert owned["practice_type"] == "NUTRIENT_MANAGEMENT", owned
    assert_load(owned["enrolled_acres"], 40.00, "enrolled_acres")
    assert_load(owned["pre_load_lbs_yr"], 400.00, "pre_load_lbs_yr")
    assert_load(owned["post_load_lbs_yr"], 150.00, "post_load_lbs_yr")


def test_a_run_relied_on_by_a_derived_permit_cannot_be_rescinded(api):
    """One derived permit is enough to freeze the whole allocation run.

    "if any permit whose `source_assessment_id` points at a source assessment
    carrying this run's `allocation_run_id` has a `limit_status` of `INTERIM` or
    `FINAL`, the request is rejected with `ERR_ALLOCATION_RUN_IN_USE`"

    Design: Corner/validations/rescinding_an_allocation_run_relied_on_by_a_derived_permit_is_rejected
    """
    world = fx.scr_allocated(api)
    relying_permit = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p1"]["id"],
        permit_number="OH-0001",
        permittee_user_id="user-permittee-1",
        design_flow_mgd=4.5000,
        current_annual_load_lbs=30000.00,
    )
    fx.derive_limits(api, relying_permit["id"])
    idle_permit = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p2"]["id"],
        permit_number="OH-0002",
        permittee_user_id="user-permittee-2",
        design_flow_mgd=1.2000,
        current_annual_load_lbs=6000.00,
    )
    assert idle_permit["limit_status"] == "DRAFT_LIMITS", idle_permit

    refused = api.rescind_allocation_run(
        world["run_id"],
        f.rescind_payload("Re-opening the allocation after a comment period."),
        ANALYST,
    )

    validate_error(refused, ERR_ALLOCATION_RUN_IN_USE, 409)

    run = get_success_data(api.get_allocation_run(world["run_id"], ANALYST))
    assert run["status"] == "ACTIVE", run
    assert_is_null(run["rescinded_at"], "rescinded_at")

    source = get_success_data(api.get_source_assessment(world["sa_p1"]["id"], ANALYST))
    assert_load(source["allocated_load_lbs_yr"], 21888.00, "allocated_load_lbs_yr")
    assert source["allocation_run_id"] == world["run_id"], source

    still_derived = validate_success(api.get_permit(relying_permit["id"], PERMIT_WRITER))
    assert still_derived["limit_status"] == "INTERIM", still_derived
    assert_load(still_derived["applicable_limit_lbs_yr"], 23916.00, "applicable_limit_lbs_yr")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2400.00, "reserve_pool_lbs")
    assert_load(watershed["allocated_wla_total_lbs_yr"], 27360.00, "allocated_wla_total_lbs_yr")


def _two_permit_trading_world(api):
    """An ACTIVE program, a LISTED 520 lb batch, one permit short and one in compliance.

    OH-0001 (permittee-1, City WWTP) reports 25000.00 against an applicable limit of
    23916.00 and is in SHORTFALL by 1084.00; OH-0002 (permittee-2, Village WWTP)
    reports 4000.00 against 5472.00 and is IN_COMPLIANCE with a gap of exactly 0.00.
    """
    world = fx.scr_active_program(api)
    world["permit_1"] = fx.permit_in_shortfall(
        api,
        world["watershed_id"],
        world["sa_p1"]["id"],
        permit_number="OH-0001",
        permittee_user_id="user-permittee-1",
        reported_annual_load_lbs=25000.00,
        design_flow_mgd=4.5000,
        current_annual_load_lbs=30000.00,
    )
    world["permit_1_id"] = world["permit_1"]["id"]
    assert_load(world["permit_1"]["compliance_gap_lbs"], 1084.00, "OH-0001 compliance_gap_lbs")

    permit_2 = fx.make_permit(
        api,
        world["watershed_id"],
        world["sa_p2"]["id"],
        permit_number="OH-0002",
        permittee_user_id="user-permittee-2",
        design_flow_mgd=1.2000,
        current_annual_load_lbs=6000.00,
    )
    fx.derive_limits(api, permit_2["id"])
    world["permit_2"] = fx.file_annual_report(
        api, permit_2["id"], 4000.00, permittee_headers=PERMITTEE_2
    )
    world["permit_2_id"] = permit_2["id"]
    assert world["permit_2"]["compliance_status"] == "IN_COMPLIANCE", world["permit_2"]

    world["producer_id"] = fx.make_producer(api)["id"]
    project = fx.implemented_project(
        api, world["producer_id"], world["reaches"]["r_up"]["id"], "T-101"
    )
    issued = fx.certify_project(api, project["id"])
    world["batch_id"] = issued["id"]
    world["version_at_issue"] = issued["version"]
    assert_integer(issued["version"], 1, "credit batch version at issue")
    world["batch"] = fx.list_batch(api, issued["id"])
    world["version_listed"] = world["batch"]["version"]
    assert_integer(world["batch"]["version"], 2, "credit batch version once LISTED")
    assert world["batch"]["status"] == "LISTED", world["batch"]
    assert_integer(world["batch"]["issued_lbs"], 520, "issued_lbs")
    assert_batch_buckets(
        world["batch"], available=520.00, reserved=0.00, retired=0.00, invalidated=0.00
    )
    return world


def test_each_faulty_credit_proposal_trips_exactly_its_own_gate(api):
    """Five proposals fault on the year, the delivery floor, the balance, the gap and the version.

    "the transaction's `reporting_period_year` must equal the permit's ... otherwise
    `ERR_REPORTING_YEAR_MISMATCH`", "`ERR_DELIVERY_BELOW_MINIMUM`", "the batch's
    `available_lbs` must be at least the requested gross ... `ERR_CREDIT_INSUFFICIENT`",
    "`ERR_NO_COMPLIANCE_GAP`" and "`ERR_STALE_BATCH_VERSION`"

    Design: Corner/validations/credit_transaction_proposals_are_rejected_for_year_delivery_balance_gap_and_version_faults
    """
    world = _two_permit_trading_world(api)
    batch_id = world["batch_id"]
    permit_1_id = world["permit_1_id"]
    listed_version = world["version_listed"]

    wrong_year = api.propose_credit_transaction(
        f.credit_transaction_payload(batch_id, permit_1_id, 500.00, 2025, listed_version),
        PERMITTEE_1,
    )
    validate_error(wrong_year, ERR_REPORTING_YEAR_MISMATCH, 422)

    below_minimum = api.propose_credit_transaction(
        f.credit_transaction_payload(batch_id, permit_1_id, 0.01, 2026, listed_version),
        PERMITTEE_1,
    )
    validate_error(below_minimum, ERR_DELIVERY_BELOW_MINIMUM, 422)

    too_many_pounds = api.propose_credit_transaction(
        f.credit_transaction_payload(batch_id, permit_1_id, 600.00, 2026, listed_version),
        PERMITTEE_1,
    )
    validate_error(too_many_pounds, ERR_CREDIT_INSUFFICIENT, 409)

    no_gap = api.propose_credit_transaction(
        f.credit_transaction_payload(
            batch_id, world["permit_2_id"], 100.00, 2026, listed_version
        ),
        PERMITTEE_2,
    )
    validate_error(no_gap, ERR_NO_COMPLIANCE_GAP, 409)

    stale_version = api.propose_credit_transaction(
        f.credit_transaction_payload(
            batch_id, permit_1_id, 500.00, 2026, world["version_at_issue"]
        ),
        PERMITTEE_1,
    )
    validate_error(stale_version, ERR_STALE_BATCH_VERSION, 412)

    _, meta = validate_paginated(api.list_credit_transactions(REGISTRY, {"credit_batch_id": batch_id}))
    assert_pagination_meta(meta, 10, 0, 0, False)

    untouched = get_success_data(api.get_credit_batch(batch_id, REGISTRY))
    assert_batch_buckets(untouched, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)
    assert_integer(untouched["version"], listed_version, "version after five rejected proposals")
    assert untouched["status"] == "LISTED", untouched

    permit_1 = validate_success(api.get_permit(permit_1_id, PERMITTEE_1))
    assert_load(permit_1["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")
    assert_load(permit_1["credit_applied_lbs"], 0.00, "credit_applied_lbs")
    permit_2 = validate_success(api.get_permit(world["permit_2_id"], PERMITTEE_2))
    assert_load(permit_2["compliance_gap_lbs"], 0.00, "compliance_gap_lbs")
    assert permit_2["compliance_status"] == "IN_COMPLIANCE", permit_2

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2400.40, "reserve_pool_lbs")


def test_an_open_proposal_blocks_retirement_until_it_is_voided(api):
    """Encumbered pounds cannot be retired out from under a live proposal.

    "A batch with any transaction in status `PROPOSED` against it may not be
    retired; the request is rejected with `ERR_BATCH_HAS_OPEN_TRANSACTIONS`."

    Design: Corner/validations/retiring_a_batch_with_an_open_proposed_transaction_is_rejected
    """
    world = _two_permit_trading_world(api)
    batch_id = world["batch_id"]
    proposed = fx.propose_transaction(
        api, batch_id, world["permit_1_id"], 500.00, expected_batch_version=world["version_listed"]
    )
    assert proposed["status"] == "PROPOSED", proposed
    encumbered = get_success_data(api.get_credit_batch(batch_id, REGISTRY))
    assert_batch_buckets(encumbered, available=20.00, reserved=500.00, retired=0.00, invalidated=0.00)

    blocked = api.retire_credit_batch(
        batch_id, f.retire_payload(100.00, "Retiring while a purchase is still open."), REGISTRY
    )

    validate_error(blocked, ERR_BATCH_HAS_OPEN_TRANSACTIONS, 409)

    unchanged = get_success_data(api.get_credit_batch(batch_id, REGISTRY))
    assert_batch_buckets(unchanged, available=20.00, reserved=500.00, retired=0.00, invalidated=0.00)
    assert unchanged["status"] == "LISTED", unchanged

    voided = fx.void_transaction(api, proposed["id"], "REGISTRY_ACTION")

    assert voided["status"] == "VOIDED", voided
    assert voided["void_reason"] == "REGISTRY_ACTION", voided
    released = get_success_data(api.get_credit_batch(batch_id, REGISTRY))
    assert_batch_buckets(released, available=520.00, reserved=0.00, retired=0.00, invalidated=0.00)

    retired = fx.retire_batch(api, batch_id, 100.00, "Registry retirement once the book is clear.")

    assert_batch_buckets(retired, available=420.00, reserved=0.00, retired=100.00, invalidated=0.00)
    assert retired["status"] == "LISTED", retired
    assert_integer(retired["issued_lbs"], 520, "issued_lbs")

    watershed = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    assert_load(watershed["reserve_pool_lbs"], 2500.40, "reserve_pool_lbs")

    permit = validate_success(api.get_permit(world["permit_1_id"], PERMITTEE_1))
    assert_load(permit["compliance_gap_lbs"], 1084.00, "compliance_gap_lbs")
    assert_load(permit["credit_applied_lbs"], 0.00, "credit_applied_lbs")
