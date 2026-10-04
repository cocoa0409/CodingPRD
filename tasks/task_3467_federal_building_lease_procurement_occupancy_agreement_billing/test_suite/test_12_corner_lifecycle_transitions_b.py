"""Corner coverage: lifecycle transitions — alterations, service tickets,
utilization surveys, space reductions, and expiration plans."""
from test_helpers import (
    ApiErrorId, TEST_USERS, approve_alteration, complete_alteration,
    create_alteration, create_plan, create_survey, create_ticket,
    estimate_alteration, finalize_survey, list_reduction_actions,
    make_agency_manager_headers, select_plan_option, set_clock,
    setup_active_leased_oa, setup_active_owned_oa, setup_commenced_lease,
    validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
PM = TEST_USERS["gsa_property_manager_headers"]


def test_alteration_approve_before_estimate_rejected(api):
    """PRD §3.6: "Approval is the tenant's: an `AgencyManager` of the
    agreement's agency moves `ESTIMATED` to `APPROVED`, choosing a
    `funding_method` of `LUMP_SUM` or `AMORTIZED`, again requiring the
    agreement `ACTIVE`."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/alteration_approve_before_estimate_rejected
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa, agency = bundle["oa"], bundle["agency"]
    alt = create_alteration(oa, agency)

    resp = api.approve_alteration(
        alt["id"], {"funding_method": "LUMP_SUM"},
        make_agency_manager_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    alts, _ = validate_paginated(api.list_alterations(oa["id"], ADMIN))
    assert alts[0]["status"] == "REQUESTED"


def test_alteration_cancel_after_completion_rejected(api):
    """PRD §3.6: "Cancellation is the tenant's escape hatch from any
    non-terminal state, performed by the `AgencyManager` of the agreement's
    agency under the same scope check."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/alteration_cancel_after_completion_rejected
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa, agency = bundle["oa"], bundle["agency"]
    alt = create_alteration(oa, agency)
    estimate_alteration(alt)
    approve_alteration(alt, agency, funding_method="LUMP_SUM")
    complete_alteration(alt, "2028-03-30")

    resp = api.cancel_alteration(alt["id"], make_agency_manager_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    alts, _ = validate_paginated(api.list_alterations(oa["id"], ADMIN))
    assert alts[0]["status"] == "COMPLETED"


def test_ticket_verify_before_resolve_rejected(api):
    """PRD §3.7: "Verification belongs to the tenant: the `AgencyManager` of
    the reported agreement's agency moves `RESOLVED` to `VERIFIED`, stamping
    `verified_at`."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/ticket_verify_before_resolve_rejected
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa, agency, building = bundle["oa"], bundle["agency"], bundle["building"]
    ticket = create_ticket(building, oa, agency, category="SECURITY",
                           severity="CRITICAL", description="Turnstile fault")

    resp = api.verify_ticket(ticket["id"], make_agency_manager_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    tickets, _ = validate_paginated(api.list_service_tickets(building["id"], ADMIN))
    assert tickets[0]["status"] == "OPEN"


def test_survey_finalize_twice_rejected(api):
    """PRD §3.8: "Finalization moves `RECORDED` to `FINALIZED` and computes the
    utilization picture."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/survey_finalize_twice_rejected
    """
    bundle = setup_active_owned_oa(clock="2027-03-20T00:00:00Z")
    oa = bundle["oa"]
    survey = create_survey(oa, method="HEADCOUNT_BASED", measured_headcount=70,
                           utilized_sf=10500)
    finalize_survey(survey)

    resp = api.finalize_survey(survey["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    surveys, _ = validate_paginated(api.list_surveys(oa["id"], ADMIN))
    assert surveys[0]["status"] == "FINALIZED"
    actions = list_reduction_actions(oa)
    assert len(actions) == 1, "no second reduction action is created"


def test_reduction_execute_before_approve_rejected(api):
    """PRD §3.8: "It is deliberately segregated across three hands: only a
    `GSAAdmin` may approve it, moving `PROPOSED` to `APPROVED`, and only a
    `GSAPropertyManager` may execute an approved action, moving `APPROVED` to
    `EXECUTED` — and only while the agreement is still `ACTIVE`
    (`ERR_OA_NOT_ACTIVE`)."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/reduction_execute_before_approve_rejected
    """
    bundle = setup_active_owned_oa(clock="2027-03-20T00:00:00Z")
    oa = bundle["oa"]
    survey = create_survey(oa, method="HEADCOUNT_BASED", measured_headcount=70,
                           utilized_sf=10500)
    finalize_survey(survey)
    action = list_reduction_actions(oa)[0]
    assert action["status"] == "PROPOSED"

    resp = api.execute_reduction(action["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    actions = list_reduction_actions(oa)
    assert actions[0]["status"] == "PROPOSED", "approval cannot be skipped"
    oa_after = validate_success(api.get_oa(oa["id"], ADMIN), 200)
    assert oa_after["assigned_sf"] == 20000


def test_plan_execute_before_option_selected_rejected(api):
    """PRD §3.9: "Execution moves `OPTION_SELECTED` to `EXECUTED` and is gated
    on the lease actually being `EXPIRING` (`ERR_LEASE_NOT_EXPIRING`)."
    PRD §2.10: "6. State-transition validity: the requested transition must
    exist from the resource's current state, which covers terminal-state
    lockdown and repeated transitions — `ERR_INVALID_STATE_TRANSITION` (409)."

    Design: Corner/state_machines/plan_execute_before_option_selected_rejected
    """
    bundle = setup_commenced_lease()
    plan = create_plan(bundle["lease"])

    resp = api.execute_plan(plan["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    plans, _ = validate_paginated(api.list_expiration_plans(bundle["lease"]["id"],
                                                            ADMIN))
    assert plans[0]["status"] == "OPEN"


def test_plan_execute_requires_expiring_lease(api):
    """PRD §3.9: "Execution moves `OPTION_SELECTED` to `EXECUTED` and is gated
    on the lease actually being `EXPIRING` (`ERR_LEASE_NOT_EXPIRING`)."

    Even with an option selected, execute fails while the lease is merely
    COMMENCED.

    Design: Corner/state_machines/plan_execute_requires_expiring_lease
    """
    bundle = setup_commenced_lease()  # clock 2026-10-01: 122 whole months left
    plan = select_plan_option(create_plan(bundle["lease"]))
    assert plan["status"] == "OPTION_SELECTED"

    resp = api.execute_plan(plan["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_EXPIRING)

    plans, _ = validate_paginated(api.list_expiration_plans(bundle["lease"]["id"],
                                                            ADMIN))
    assert plans[0]["status"] == "OPTION_SELECTED"
    lease_after = validate_success(api.get_lease(bundle["lease"]["id"], ADMIN), 200)
    assert lease_after["status"] == "COMMENCED"
    assert lease_after["executed_option"] is None


def test_plan_auto_cancelled_when_lease_expires_unexecuted(api):
    """PRD §3.9: "Finally, every expiration plan of the lease still sitting in
    `OPEN` or `OPTION_SELECTED` is moved to `CANCELLED` — a plan that was not
    executed in time simply lapses."
    PRD §3.9: "When the current date passes an `EXPIRING` lease's `end_date`,
    the sweep moves it to `SUCCEEDED` if its `executed_option` is
    `SUCCEEDING_LEASE`, and to `EXPIRED` otherwise — including when no option
    was ever executed."

    Design: Corner/state_machines/plan_auto_cancelled_when_lease_expires_unexecuted
    """
    bundle = setup_commenced_lease()
    lease = bundle["lease"]
    set_clock("2035-07-01T00:00:00Z")  # lease swept into EXPIRING
    plan = create_plan(lease)

    set_clock("2037-01-01T00:00:00Z")
    lease_after = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert lease_after["status"] == "EXPIRED"
    plans, _ = validate_paginated(api.list_expiration_plans(lease["id"], ADMIN))
    assert plans[0]["id"] == plan["id"]
    assert plans[0]["status"] == "CANCELLED", "system transition, no direct call"
