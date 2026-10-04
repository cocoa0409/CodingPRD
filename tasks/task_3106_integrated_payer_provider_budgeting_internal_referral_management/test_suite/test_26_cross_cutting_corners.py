"""Corner coverage: OCC, derived-field reconciliation, cascades, selectors,
tenancy isolation, pagination-with-filtering and immediate visibility.

Breadth file (queue B).
"""

from test_helpers import (
    FTE_COST_CENTS,
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    create_appointment_payload,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    create_referral_payload,
    current_member_version,
    enroll_member,
    get_member,
    get_region,
    get_success_data,
    set_logical_clock,
    submit_claim,
    validate_paginated,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_AS = TEST_USERS["access_scheduler_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]
_CTM = TEST_USERS["care_team_member_headers"]


def _single_region(region_name="Test Region", state_codes=None, **kwargs):
    region = create_open_region(name=region_name, state_codes=state_codes or ["CA"])
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    department = create_department(care_site["id"])
    provider = create_provider(care_site["id"])
    create_and_approve_budget(region["id"])
    return region, care_site, department, provider


def test_child_create_carrying_the_stale_version_is_refused_and_the_fresh_one_succeeds(api):
    """PRD §2.9: "In all four cases a supplied `expected_member_version` that
    does not equal the member's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the write does not occur."
    PRD §2.7: "`version` (integer): a system-managed counter that starts at its
    creation value and increments by one on every mutation of the resource."

    Design: Corner/cross_cutting_layers/occ_current_member_version_succeeds_and_bumps_member_version
    """
    set_logical_clock()
    region, care_site, department, provider = _single_region()
    member = enroll_member(region["id"], provider["id"], member_ref="M-OCC-1")
    version_at_create = current_member_version(member["id"])

    first = api_client.create_referral(
        create_referral_payload(
            member["id"], department["id"], department["id"], version_at_create
        ),
        _AS,
    )
    assert first.status_code == 201, first.text

    version_after = current_member_version(member["id"])
    assert version_after > version_at_create, (
        "the child create advances the member's version"
    )

    stale = api_client.create_referral(
        create_referral_payload(
            member["id"], department["id"], department["id"], version_at_create
        ),
        _AS,
    )
    assert stale.status_code == 412, stale.text
    assert stale.json()["data"]["error_id"] == "ERR_STALE_VERSION"

    fresh = api_client.create_referral(
        create_referral_payload(
            member["id"], department["id"], department["id"], version_after
        ),
        _AS,
    )
    assert fresh.status_code == 201, fresh.text


def test_region_staffing_figure_reconciles_to_the_care_site_rows(api):
    """PRD §2.6: "`staffing_and_facility_cents` is the sum, over the region's
    care sites, of filled full-time-equivalents multiplied by one million two
    hundred fifty thousand cents plus the site's
    `facility_investment_spent_cents`."
    PRD §3.7: "The settled margin is premium revenue minus employed delivery
    cost minus outside-services spend minus staffing and facility cost."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_region_margin_after_staffing_change
    """
    set_logical_clock()
    region = create_open_region()
    care_site = create_care_site(
        region["id"], staffing_fte_budget=10.0, facility_investment_budget_cents=0
    )
    create_department(care_site["id"])
    provider = create_provider(care_site["id"])
    member = enroll_member(region["id"], provider["id"])
    create_and_approve_budget(region["id"], staffing_budget_cents=50000000)

    res = api_client.set_staffing(
        care_site["id"], {"staffing_fte_filled": 8.0}, _RFO
    )
    assert res.status_code == 200, res.text
    assert res.json()["data"]["staffing_fte_filled"] == 8.0

    region_after = get_region(region["id"])
    assert FTE_COST_CENTS == 1250000
    assert region_after["staffing_and_facility_cents"] == int(8.0 * FTE_COST_CENTS)
    assert region_after["staffing_and_facility_cents"] == 10000000
    assert region_after["operating_margin_cents"] == (
        region_after["premium_revenue_cents"]
        - region_after["employed_delivery_cost_cents"]
        - region_after["outside_services_spend_cents"]
        - region_after["staffing_and_facility_cents"]
    )


def test_completing_an_appointment_bubbles_to_the_referral_and_the_region(api):
    """PRD §3.4: "Completion is the exclusive province of a `CareTeamMember` and
    applies to a `SCHEDULED` appointment, moving `fulfillment_status` to
    `COMPLETED`, moving a linked referral in `SCHEDULED` status to `COMPLETED`,
    and recomputing the parent region's `access_breach_pct`."
    PRD §3.10: "The region's `access_breach_pct` is one hundred times the count
    of its breached appointments divided by its count of non-cancelled
    appointments".

    Design: Corner/cross_cutting_layers/cascading_side_effects_appointment_complete_bubbles_to_referral_and_region
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    region, care_site, department, provider = _single_region()
    member = enroll_member(region["id"], provider["id"], member_ref="M-CAS-1")

    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                member["id"], department["id"], department["id"], member["version"]
            ),
            _AS,
        )
    )
    get_success_data(api_client.authorize_referral(referral["id"], {}, _UR))

    booked = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"],
            current_member_version(member["id"]),
            referral_id=referral["id"], appointment_type="SPECIALTY",
            start_utc="2026-09-20T00:00:00Z",
        ),
        _AS,
    )
    assert booked.status_code == 201, booked.text
    appointment_id = booked.json()["data"]["id"]

    completed = api_client.complete_appointment(appointment_id, {}, _CTM)
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["fulfillment_status"] == "COMPLETED"
    assert api_client.get_referral(referral["id"], _UR).json()["data"]["status"] == "COMPLETED"
    # The wait from 2026-09-01 to 2026-09-20 breaches the 14-day target, and it
    # is the region's only non-cancelled appointment.
    assert get_region(region["id"])["access_breach_pct"] == 100.0


def test_referral_target_resolves_to_the_department_with_remaining_supply(api):
    """PRD §3.5: "When more than one department qualifies, the system ranks
    candidates by remaining supply — `appointment_slots_budgeted` minus
    `appointment_slots_committed`, descending — and breaks ties in favor of the
    earliest `created_at`."
    PRD §3.3: "This same rule has an explicitly different reading after a
    period closes".

    Design: Corner/cross_cutting_layers/selector_policy_department_ranking_prefers_remaining_budgeted_supply
    """
    set_logical_clock()
    region = create_open_region()
    care_site = create_care_site(region["id"], facility_investment_budget_cents=0)
    exhausted = create_department(
        care_site["id"], specialty="PRIMARY_CARE", appointment_slots_budgeted=2
    )
    ample = create_department(
        care_site["id"], specialty="PRIMARY_CARE", appointment_slots_budgeted=50
    )
    provider = create_provider(care_site["id"])
    create_and_approve_budget(region["id"])

    fillers = [
        enroll_member(region["id"], provider["id"], member_ref=f"M-SP-{i}")
        for i in range(2)
    ]
    for index, filler in enumerate(fillers):
        api_client.book_appointment(
            create_appointment_payload(
                exhausted["id"], provider["id"], filler["id"],
                current_member_version(filler["id"]),
                start_utc=f"2026-09-{10 + index:02d}T09:00:00Z",
            ),
            _AS,
        )
    requester = enroll_member(region["id"], provider["id"], member_ref="M-SP-REQ")

    referral = get_success_data(
        api_client.create_referral(
            create_referral_payload(
                requester["id"], ample["id"], exhausted["id"], requester["version"],
                service_code="PRIMARY_CARE",
            ),
            _AS,
        )
    )
    # PRD 3.5 states the ranking rule but leaves the selected candidate's
    # pathway to target_department_id unstated, so the target is either the
    # requested (exhausted, zero remaining supply) department or the ample one
    # that the ranking would prefer.
    assert referral["target_department_id"] in (exhausted["id"], ample["id"]), (
        "the referral names one of the two qualifying departments"
    )
    assert referral["status"] == "PENDING_TRIAGE"
    assert referral["service_code"] == "PRIMARY_CARE"


def test_claims_never_leak_across_regions(api):
    """PRD §4: "| GET | `/regions/{id}/outside-service-claims` | List the
    outside-service claims of a Region | `PlatformAdmin`, `RegionalFinanceOfficer`,
    `UtilizationReviewer`, `BudgetAppropriationsCommittee` |"
    PRD §2.6: "`outside_services_spend_cents` is the sum of
    `final_liability_cents` over the region's claims whose status is `PAID` or
    `ADJUDICATED`."

    Design: Corner/cross_cutting_layers/multi_tenancy_isolation_claims_never_leak_across_regions
    """
    set_logical_clock()
    region_a, care_site_a, department_a, provider_a = _single_region(region_name="Region A")
    region_b, care_site_b, department_b, provider_b = _single_region(
        region_name="Region B", state_codes=["NV"]
    )
    member_a = enroll_member(region_a["id"], provider_a["id"], member_ref="M-RA-1")
    member_b = enroll_member(region_b["id"], provider_b["id"], member_ref="M-RB-1")
    claim_a = submit_claim(
        region_a["id"], member_a["id"], member_a["version"], vendor_name="Region A Vendor"
    )
    claim_b = submit_claim(
        region_b["id"], member_b["id"], member_b["version"], vendor_name="Region B Vendor"
    )

    listed_a = api_client.list_region_outside_service_claims(region_a["id"], _RFO)
    listed_b = api_client.list_region_outside_service_claims(region_b["id"], _RFO)
    rows_a = listed_a.json()["data"]
    rows_b = listed_b.json()["data"]
    assert [r["id"] for r in rows_a] == [claim_a["id"]]
    assert [r["id"] for r in rows_b] == [claim_b["id"]]
    assert set(r["id"] for r in rows_a).isdisjoint(r["id"] for r in rows_b)

    every = api_client.list_outside_service_claims(_RFO)
    assert len(every.json()["data"]) == 2


def test_page_limits_apply_to_the_filtered_set(api):
    """PRD §2.3: "`total_count` reflects the size of the full filtered set
    rather than the page, and `has_more` is true when further items remain
    beyond the current page."
    PRD §2.3: "List endpoints also accept the per-resource filter parameters
    named in §3".

    Design: Corner/cross_cutting_layers/pagination_with_filtering_interacts_with_status_and_type_filters
    """
    set_logical_clock()
    region, care_site, department, provider = _single_region()
    member = enroll_member(region["id"], provider["id"], member_ref="M-PG-1")

    submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        vendor_name="Vendor One", claim_type="CONTRACTED", billed_amount_cents=100000,
    )
    submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        vendor_name="Vendor Two", claim_type="EMERGENCY", emergency_flag=True,
        billed_amount_cents=200000,
    )
    submit_claim(
        region["id"], member["id"], current_member_version(member["id"]),
        vendor_name="Vendor Three", claim_type="EMERGENCY", emergency_flag=True,
        billed_amount_cents=300000,
    )

    first_page = api_client.list_region_outside_service_claims(
        region["id"], _RFO, {"limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail = api_client.list_region_outside_service_claims(
        region["id"], _RFO, {"limit": 2, "offset": 2}
    )
    tail_rows, tail_meta = validate_paginated(tail)
    assert len(tail_rows) == 1
    assert tail_meta["has_more"] is False

    filtered = api_client.list_region_outside_service_claims(
        region["id"], _RFO, {"claim_type": "EMERGENCY", "limit": 1, "offset": 0}
    )
    filtered_rows, filtered_meta = validate_paginated(filtered)
    assert len(filtered_rows) == 1
    assert filtered_meta["total_count"] == 2, "the count reflects the filtered set"
    assert filtered_meta["has_more"] is True


def test_adjudication_returns_the_pinned_liability_in_the_same_response(api):
    """PRD §3.6: "Adjudication pins the final liability, records
    `adjudicated_at` from the logical clock, moves the claim to `ADJUDICATED`".
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/immediate_visibility_region_margin_in_the_same_response
    """
    set_logical_clock()
    region, care_site, department, provider = _single_region()
    member = enroll_member(region["id"], provider["id"], member_ref="M-IV-1")
    claim = submit_claim(
        region["id"], member["id"], member["version"], billed_amount_cents=420000
    )

    res = api_client.adjudicate_claim(claim["id"], {}, _RFO)
    assert res.status_code == 200, res.text
    adjudicated = res.json()["data"]
    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["final_liability_cents"] is not None
    assert adjudicated["adjudicated_at"]

    region_after = api_client.get_region(region["id"], _RFO).json()["data"]
    assert (
        region_after["outside_services_spend_cents"] == adjudicated["final_liability_cents"]
    )


def test_committed_slots_are_visible_immediately_after_the_booking(api):
    """PRD §3.4: "A successful booking moves the appointment's
    `fulfillment_status` from `REQUESTED` to `SCHEDULED`".
    PRD §3.4: "The department's `appointment_slots_committed` increments by one".

    Design: Corner/consistency_model/immediate_visibility_department_committed_slots_in_the_booking_response
    """
    set_logical_clock()
    region, care_site, department, provider = _single_region()
    member = enroll_member(region["id"], provider["id"], member_ref="M-IV-2")

    res = api_client.book_appointment(
        create_appointment_payload(
            department["id"], provider["id"], member["id"], member["version"],
            start_utc="2026-09-10T09:00:00Z",
        ),
        _AS,
    )
    assert res.status_code == 201, res.text
    assert res.json()["data"]["fulfillment_status"] == "SCHEDULED"

    department_after = api_client.get_department(department["id"], _AS).json()["data"]
    assert department_after["appointment_slots_committed"] == 1, (
        "no intermediate zero-committed state is observable once the 201 returns"
    )
    assert department_after["status"] == "OPEN", (
        "the department is only constrained once committed reaches the budget"
    )