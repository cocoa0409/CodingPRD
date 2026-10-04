"""Funding landscape: funders, programs and awards."""
from test_helpers import (
    api_client, validate_success, validate_paginated, create_funder, create_program,
    create_grant, open_outcome_report, record_in_kind, set_clock, assert_grant,
    INTAKE, PROGRAM, FINANCE, COMPLIANCE,
)


def test_program_create_initializes_capacity_counters_and_active_status():
    """PRD §3.1: "Registration initializes the program's `enrolled_slots` to 0
    and its `status` to `ACTIVE`; the program lifecycle admits `ACTIVE`,
    `SUSPENDED` and `CLOSED`."
    PRD §3.1: "`capacity_slots` sets the maximum number of concurrent open
    enrollments the program may carry and must be zero or greater."

    Design: Corner/entities/program_create_initializes_capacity_counters_and_active_status
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_program(
        {
            "name": "Housing First",
            "service_domain": "HOUSING",
            "faith_based_activity_offered": False,
            "nondiscrimination_attested": True,
            "capacity_slots": 3,
            "match_eligible": True,
        },
        COMPLIANCE,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE", "a newly registered program begins ACTIVE"
    assert data["capacity_slots"] == 3
    assert data["enrolled_slots"] == 0, "a new program never starts at capacity"
    assert data["match_eligible"] is True
    assert data["nondiscrimination_attested"] is True


def test_grant_create_initializes_zero_ledgers_and_open_posture():
    """PRD §3.1: "Registration sets `expended_cents` and `obligated_cents` to 0,
    computes `burn_ratio` through the posture rule of §2.12, and assigns
    `status` from that computation, so a grant whose configured award is already
    exhausted by other means opens in `THROTTLED` or `FROZEN` rather than
    `OPEN`."
    PRD §2.12: "Otherwise the posture is `OPEN`."

    Design: Corner/entities/grant_create_initializes_zero_ledgers_and_open_posture
    """
    set_clock("2026-09-01T00:00:00Z")
    funder = create_funder(name="Diocesan Fund", funder_type="DIOCESAN",
                           allow_faith_based_activity=True,
                           requires_time_and_effort_documentation=False,
                           max_admin_rate_pct=0.25, fiscal_year_start_month=1)
    program = create_program(name="Housing First")
    resp = api_client.create_grant(
        {
            "funder_id": funder["id"],
            "program_id": program["id"],
            "grant_code": "G-1",
            "total_award_cents": 200000,
            "admin_rate_pct": 0.10,
            "allocation_rank": 1,
            "max_in_kind_rate_cents": 3000,
            "matching_requirement_pct": 0.25,
            "cost_allocation_basis": "DIRECT_ONLY",
            "restricted_purpose": "HOUSING_ASSISTANCE",
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2027-08-31T23:59:59Z",
        },
        FINANCE,
    )
    data = validate_success(resp, expected_status=201)
    assert_grant(data)
    assert data["expended_cents"] == 0
    assert data["obligated_cents"] == 0
    assert data["burn_ratio"] == 0.0
    assert data["status"] == "OPEN", "a grant with no commitment is OPEN"
    assert data["funder_id"] == funder["id"]
    assert data["program_id"] == program["id"]


def test_grant_list_filters_by_funder_and_status_with_pagination_envelope():
    """PRD §3.1: "Grants are listed with optional filters on `funder_id`,
    `program_id` and `status`, and a single grant can be read back; that read
    returns the gating committed-basis `burn_ratio` used by every posture
    decision, the reporting-only cash-basis figure, and counts of the children
    hanging off the award."
    PRD §2.3: "`limit` caps how many rows are returned: it defaults to 10 when
    omitted, must be at least 1, and must not exceed 100. `offset` states how
    many rows to skip from the front of the result and defaults to 0."

    Design: Corner/entities/grant_list_filters_by_funder_and_status_with_pagination_envelope
    """
    set_clock("2026-09-01T00:00:00Z")
    f1 = create_funder(name="Diocesan Fund", funder_type="DIOCESAN",
                       allow_faith_based_activity=True)
    f2 = create_funder(name="County Human Services", funder_type="COUNTY",
                       allow_faith_based_activity=False,
                       requires_time_and_effort_documentation=True,
                       max_admin_rate_pct=0.10, fiscal_year_start_month=7)
    p1 = create_program(name="Housing First")
    g1 = create_grant(f1["id"], p1["id"], grant_code="G-1", total_award_cents=200000,
                      matching_requirement_pct=0.0, cost_allocation_basis="DIRECT_ONLY",
                      restricted_purpose="HOUSING_ASSISTANCE")
    create_grant(f2["id"], p1["id"], grant_code="G-2", total_award_cents=100000,
                 allocation_rank=2, matching_requirement_pct=0.0,
                 cost_allocation_basis="HEADCOUNT", restricted_purpose="GENERAL_OPERATING",
                 period_end="2027-06-30T23:59:59Z")

    scoped, scoped_meta = validate_paginated(
        api_client.list_grants(FINANCE, {"funder_id": f1["id"]})
    )
    assert len(scoped) == 1, "the funder filter scopes the list to one funder"
    assert scoped[0]["id"] == g1["id"]
    assert scoped_meta["limit"] == 10, "limit defaults to 10 when omitted"
    assert scoped_meta["offset"] == 0, "offset defaults to 0"
    assert scoped_meta["total_count"] == 1
    assert scoped_meta["has_more"] is False

    empty, empty_meta = validate_paginated(api_client.list_grants(FINANCE, {"status": "FROZEN"}))
    assert empty == [], "a filter matching nothing returns an empty array, not a 404"
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False


def test_grant_child_reads_are_scoped_to_the_named_grant():
    """PRD §3.1: "The outcome reports filed against a grant can be listed with
    filters on `measure_code` and `status`, and the in-kind donations credited
    against it can be listed with filters on `donor_type` and `status`."
    PRD §2.11: "listing the outcome reports or the in-kind donations credited
    against a grant resolves the grant first".

    Design: Corner/endpoints/grant_child_reads_are_scoped_to_the_named_grant
    """
    set_clock("2026-09-01T00:00:00Z")
    f1 = create_funder()
    p1 = create_program()
    g1 = create_grant(f1["id"], p1["id"], grant_code="G-1", matching_requirement_pct=0.25)
    g2 = create_grant(f1["id"], p1["id"], grant_code="G-2", total_award_cents=100000,
                      allocation_rank=2, matching_requirement_pct=0.0,
                      restricted_purpose="GENERAL_OPERATING")
    report = open_outcome_report(g1["id"], measure_code="HOUSING_PLACEMENTS",
                                 reporting_period_start="2026-09-01T00:00:00Z",
                                 reporting_period_end="2026-09-30T00:00:00Z",
                                 numerator=4, denominator=10)
    donation = record_in_kind(g1["id"], donor_reference="PARISH-01",
                              donation_date="2026-09-02T00:00:00Z", hours=5,
                              valuation_method="APPRAISAL", rate_cents=3000)

    first, _ = validate_paginated(api_client.list_grant_outcome_reports(g1["id"], COMPLIANCE))
    assert len(first) == 1 and first[0]["id"] == report["id"]

    second, second_meta = validate_paginated(
        api_client.list_grant_outcome_reports(g2["id"], COMPLIANCE)
    )
    assert second == [], "a report filed against g1 is invisible from g2"
    assert second_meta["total_count"] == 0

    third, _ = validate_paginated(api_client.list_grant_in_kind_donations(g1["id"], COMPLIANCE))
    assert len(third) == 1 and third[0]["id"] == donation["id"]
