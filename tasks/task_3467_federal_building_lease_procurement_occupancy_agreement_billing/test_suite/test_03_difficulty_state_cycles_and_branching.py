"""Non-linear state machines: revision cycles and branching forks."""
from test_helpers import (
    TEST_USERS, approve_alteration, assert_lease, create_agency,
    create_alteration, create_leased_building, create_offer_payload,
    estimate_alteration, get_success_data, make_agency_manager_headers,
    set_clock, setup_active_leased_oa, validate_success,
    walk_requirement_to_soliciting,
)

OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


def test_alteration_revision_cycle_with_occ_version_progression(api):
    """PRD §3.6: "If the tenant dislikes the estimate, revision sends the
    alteration from `ESTIMATED` back to `REQUESTED`"
    PRD §2.7: "Revising an alteration request requires the request to carry
    `expected_alteration_version` holding the alteration's last observed
    `version`."
    PRD §3.6: "A revision increments the alteration's `version`, replaces
    `description` and `scope_sf` when supplied, and clears the pending estimate
    — `estimated_cost_cents` and both work dates return to null. The
    estimate-and-revise cycle may repeat."
    PRD §3.6: "Choosing `LUMP_SUM` arms the one-time charge: the alteration's
    `lump_charge_status` — `NONE` until now — becomes `PENDING`."

    ESTIMATED -> REQUESTED -> ESTIMATED -> APPROVED: the OCC token captured
    after the first estimate authorizes the revise, and the cycle leaves no
    trace of the cleared estimate.

    Design: Difficulty/non_linear_state_machine/alteration_revision_cycle_with_occ_version_progression
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa, agency = bundle["oa"], bundle["agency"]
    agency_h = make_agency_manager_headers(agency["id"])

    alt = create_alteration(oa, agency)
    estimated = estimate_alteration(alt, estimated_cost_cents=800000,
                                    work_start_date="2028-03-01",
                                    work_end_date="2028-03-31")
    est_version = estimated["version"]

    revised = validate_success(api.revise_alteration(
        alt["id"],
        {"expected_alteration_version": est_version,
         "description": "Expanded scope: two floors", "scope_sf": 900},
        agency_h), 200)
    assert revised["status"] == "REQUESTED"
    assert revised["estimated_cost_cents"] is None, (
        "the revision clears the pending estimate")
    assert revised["version"] == est_version + 1, (
        "the OCC mutation bumped the version by exactly 1")

    re_estimated = estimate_alteration(alt, estimated_cost_cents=1500000,
                                       work_start_date="2028-05-01",
                                       work_end_date="2028-05-31")
    approved = approve_alteration(re_estimated, agency, funding_method="LUMP_SUM")
    assert approved["status"] == "APPROVED"
    assert approved["estimated_cost_cents"] == 1500000
    assert approved["scope_sf"] == 900
    assert approved["lump_charge_status"] == "PENDING"


def test_offer_award_branching_auto_rejects_siblings(api):
    """PRD §3.3: "A lease springs into existence in `AWARDED` status: the
    shell, operating, and base-year tax rates, the `escalation_method`, and the
    `free_rent_months` are copied from the offer; `term_months` is twelve times
    the offer's `term_years`; `leased_sf` equals the requirement's
    `required_usable_sf`; `ti_allowance_total_cents` is the offer's
    `ti_allowance_per_sf_cents` multiplied by `leased_sf`; and `awarded_date`
    is stamped from the logical clock."
    PRD §3.3: "Simultaneously, the requirement transitions from `SOLICITING` to
    `AWARDED`; every sibling offer on the same requirement still in `SUBMITTED`
    or `UNDER_EVALUATION` is moved to `REJECTED` with `rejection_reason` set to
    `AUTO_NOT_SELECTED` (sibling offers already in a terminal state are
    untouched); and the building's `available_sf` decreases by `leased_sf`,
    committing the space per §2.9."
    PRD §3.3: "A `LessorRep` may withdraw an offer that is still in `SUBMITTED`
    or still in `UNDER_EVALUATION`; either way the offer lands in `WITHDRAWN`
    with `rejection_reason` set to `WITHDRAWN_BY_LESSOR`."

    Selecting one UNDER_EVALUATION offer forks the siblings: the evaluated one
    is auto-rejected, the already-withdrawn one keeps its own terminal branch.

    Design: Difficulty/non_linear_state_machine/offer_award_branching_auto_rejects_siblings
    """
    agency = create_agency()
    bld1 = create_leased_building(building_name="Metro Tower",
                                  address="100 Federal Plaza")
    bld2 = create_leased_building(building_name="Riverside Annex",
                                  address="200 River Rd")
    bld3 = create_leased_building(building_name="Depot Lofts",
                                  address="300 Rail St")
    set_clock("2026-10-01T00:00:00Z")
    req = walk_requirement_to_soliciting(agency)

    off1 = get_success_data(api.create_offer(
        req["id"], create_offer_payload(bld1["id"]), LESSOR))
    off2 = get_success_data(api.create_offer(
        req["id"], create_offer_payload(
            bld2["id"], lessor_name="River Properties Inc",
            shell_rate_per_sf_yr_cents=3100, operating_rate_per_sf_yr_cents=880,
            base_year_tax_per_sf_yr_cents=410, ti_allowance_per_sf_cents=4500,
            free_rent_months=2), LESSOR))
    off3 = get_success_data(api.create_offer(
        req["id"], create_offer_payload(
            bld3["id"], lessor_name="Depot Holdings",
            shell_rate_per_sf_yr_cents=2900, operating_rate_per_sf_yr_cents=950,
            base_year_tax_per_sf_yr_cents=390, ti_allowance_per_sf_cents=5500,
            free_rent_months=4), LESSOR))
    get_success_data(api.evaluate_offer(off1["id"], OFFICER))
    get_success_data(api.evaluate_offer(off2["id"], OFFICER))
    get_success_data(api.withdraw_offer(off3["id"], LESSOR))

    lease = validate_success(api.select_offer(off1["id"], OFFICER), 201)
    assert_lease(lease)
    assert lease["status"] == "AWARDED"
    assert lease["leased_sf"] == 68300
    assert lease["ti_allowance_total_cents"] == 341500000
    assert lease["building_id"] == bld1["id"]
    assert lease["offer_id"] == off1["id"]

    off1_after = validate_success(api.get_offer(off1["id"], OFFICER), 200)
    assert off1_after["status"] == "SELECTED"

    off2_after = validate_success(api.get_offer(off2["id"], OFFICER), 200)
    assert off2_after["status"] == "REJECTED"
    assert off2_after["rejection_reason"] == "AUTO_NOT_SELECTED", (
        "the conditional cascade hit a non-terminal sibling")

    off3_after = validate_success(api.get_offer(off3["id"], OFFICER), 200)
    assert off3_after["status"] == "WITHDRAWN"
    assert off3_after["rejection_reason"] == "WITHDRAWN_BY_LESSOR", (
        "a terminal sibling is untouched by the cascade")

    req_after = validate_success(api.get_space_requirement(req["id"], OFFICER), 200)
    assert req_after["status"] == "AWARDED"
