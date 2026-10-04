"""Corner coverage: error catalog triggers reachable only through a cascade."""
from test_helpers import (
    ApiErrorId, TEST_USERS, create_agency, create_leased_building,
    create_offer_payload, get_success_data, set_clock, validate_error,
    validate_success, walk_requirement_to_soliciting,
)

OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


def test_error_requirement_not_soliciting_on_select_trigger(api):
    """PRD §3.3: "Simultaneously, the requirement transitions from `SOLICITING`
    to `AWARDED`; every sibling offer on the same requirement still in
    `SUBMITTED` or `UNDER_EVALUATION` is moved to `REJECTED` with
    `rejection_reason` set to `AUTO_NOT_SELECTED` (sibling offers already in a
    terminal state are untouched); and the building's `available_sf` decreases
    by `leased_sf`, committing the space per §2.9."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."
    PRD §2.10: "7. Cross-entity state gates — `ERR_REQUIREMENT_NOT_SOLICITING`,
    `ERR_LEASE_NOT_COMMENCED`, `ERR_OA_NOT_ACTIVE`, or `ERR_LEASE_NOT_EXPIRING`
    (all 409)."

    Selecting while the requirement is not SOLICITING is unreachable on a live
    offer: award auto-rejects every sibling first, so the observable failure on
    the losing sibling is the terminal-state error (existence/state precedence
    makes the solicitation gate unreachable at that point).

    Design: Corner/errors/error_requirement_not_soliciting_on_select_trigger
    """
    agency = create_agency()
    bld1 = create_leased_building(building_name="Metro Tower")
    bld2 = create_leased_building(building_name="Riverside Annex",
                                  address="200 River Rd")
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
    get_success_data(api.evaluate_offer(off1["id"], OFFICER))
    get_success_data(api.evaluate_offer(off2["id"], OFFICER))
    get_success_data(api.select_offer(off1["id"], OFFICER))

    off2_mid = validate_success(api.get_offer(off2["id"], OFFICER), 200)
    assert off2_mid["status"] == "REJECTED", "cascade hit the sibling first"

    resp = api.select_offer(off2["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
