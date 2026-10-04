"""Resource temporal overlap: aggregate capacity over concurrent intervals,
and point-exclusion work windows with buffer days."""
from test_helpers import (
    ApiErrorId, TEST_USERS, create_agency, create_alteration,
    create_owned_building, create_owned_oa, estimate_alteration,
    set_clock, setup_active_leased_oa, validate_error, validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]


def test_owned_building_aggregate_capacity_overlapping_oas(api):
    """PRD §3.5: "on owned buildings the committed square feet across `DRAFT`
    and `ACTIVE` agreements must not exceed `total_sf`
    (`ERR_BUILDING_CAPACITY_EXCEEDED`)"
    PRD §2.9: "On a `FEDERALLY_OWNED` building, `available_sf` equals
    `total_sf` minus the sum of `assigned_sf` over that building's occupancy
    agreements in `DRAFT` or `ACTIVE` status — a draft agreement already
    reserves its space."

    Concurrent agreements on one owned building are window-blind inventory
    allocations: 30,000 + 25,000 > 50,000 is rejected even though each
    agreement is individually legal; 30,000 + 20,000 == 50,000 is exactly full
    and allowed.

    Design: Difficulty/resource_temporal_overlap/owned_building_aggregate_capacity_overlapping_oas
    """
    agency = create_agency(name="Park Service")
    building = create_owned_building()
    set_clock("2026-10-01T00:00:00Z")

    oa_a = create_owned_oa(building, agency, assigned_sf=30000,
                           start_date="2027-01-01", end_date="2030-12-31")
    assert oa_a["status"] == "DRAFT"
    mid = validate_success(api.get_building(building["id"], ADMIN), 200)
    assert mid["available_sf"] == 20000

    over = api.create_oa(
        {"building_id": building["id"], "agency_id": agency["id"],
         "assigned_sf": 25000, "start_date": "2028-06-01",
         "end_date": "2031-05-31",
         "shell_equivalent_rate_per_sf_yr_cents": 2800,
         "operating_rate_per_sf_yr_cents": 800}, OFFICER)
    validate_error(over, ApiErrorId.ERR_BUILDING_CAPACITY_EXCEEDED)

    exact = validate_success(api.create_oa(
        {"building_id": building["id"], "agency_id": agency["id"],
         "assigned_sf": 20000, "start_date": "2028-06-01",
         "end_date": "2031-05-31",
         "shell_equivalent_rate_per_sf_yr_cents": 2800,
         "operating_rate_per_sf_yr_cents": 800}, OFFICER), 201)
    assert exact["status"] == "DRAFT", "aggregate exactly 50,000 == total_sf is allowed"

    end = validate_success(api.get_building(building["id"], ADMIN), 200)
    assert end["available_sf"] == 0


def test_alteration_work_windows_buffer_exclusion(api):
    """PRD §3.6: "The proposed window must also leave at least fourteen clear
    days to every other non-`CANCELLED` alteration window on the same agreement
    — the clear-day gap being the days between the later window's start and the
    earlier window's end — and a gap shorter than that is rejected with
    `ERR_ALTERATION_WINDOW_CONFLICT`."

    A second window starting 10 days after the first window's end conflicts;
    a gap of exactly 14 clear days passes.

    Design: Difficulty/resource_temporal_overlap/alteration_work_windows_buffer_exclusion
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa, agency = bundle["oa"], bundle["agency"]

    alt1 = create_alteration(oa, agency, title="Phase one",
                             description="East wing", scope_sf=30000)
    estimate_alteration(alt1, estimated_cost_cents=5000000,
                        work_start_date="2028-03-01", work_end_date="2028-03-31")
    alt2 = create_alteration(oa, agency, title="Phase two",
                             description="West wing", scope_sf=30000)

    conflict = api.estimate_alteration(
        alt2["id"], {"estimated_cost_cents": 4000000,
                     "work_start_date": "2028-04-10",
                     "work_end_date": "2028-04-20"},
        TEST_USERS["gsa_property_manager_headers"])
    validate_error(conflict, ApiErrorId.ERR_ALTERATION_WINDOW_CONFLICT)

    alts, _ = validate_paginated(api.list_alterations(oa["id"], ADMIN))
    alt2_mid = next(a for a in alts if a["id"] == alt2["id"])
    assert alt2_mid["status"] == "REQUESTED", (
        "a failed validation does not transition the alteration")

    ok = validate_success(api.estimate_alteration(
        alt2["id"], {"estimated_cost_cents": 4000000,
                     "work_start_date": "2028-04-14",
                     "work_end_date": "2028-04-20"},
        TEST_USERS["gsa_property_manager_headers"]), 200)
    assert ok["status"] == "ESTIMATED", "a gap of exactly 14 clear days is allowed"
