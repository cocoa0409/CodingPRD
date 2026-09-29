"""Authorisation: the two identity headers, the endpoint role lists and the finer rules.

Each denial is paired with the permitted call that differs in exactly one respect —
the role, the acting identity or a single payload value — so a blanket refusal
cannot satisfy the test. The denials that outrank identifier resolution are aimed at
identifiers that do not exist, which is what proves the ordering.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    COMMITTEE_BUSINESS,
    COMMITTEE_CREATIVE,
    COMMITTEE_FINANCE,
    CONTINGENCY_CASTING,
    CONTINGENCY_LOCATION,
    CONTINGENCY_PENDING,
    CONTINGENCY_SATISFIED,
    CONTINGENCY_WAIVED,
    DECISION_APPROVED,
    DECISION_PENDING,
    DEV_SERIES_ORDERED,
    GL_APPROVED,
    GL_OPEN,
    NEG_AGREED,
    PRODUCTION_GREEN_TO_SHOOT,
    PRODUCTION_ORDERED,
    SCREENING_CERTIFIED,
    VERDICT_FEASIBLE,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    USER_BA_9,
    USER_SHARED_1,
    agency_rep_headers,
    blank_auth_headers,
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
    no_auth_headers,
    platform_admin_headers,
    research_analyst_headers,
    studio_partner_headers,
)


def test_a_pilot_order_with_no_identity_headers_is_refused_before_anything_else(api):
    """No role and no user id, an unknown project and a body missing every other field.

    PRD 2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined."

    Design: Corner/rbac/a_pilot_order_with_missing_auth_headers_returns_unauthenticated
    """
    anonymous = api.create_pilot_order(
        {"project_id": NON_EXISTENT_UUID}, no_auth_headers()
    )
    validate_error(anonymous, e.ERR_UNAUTHENTICATED, 401)
    a.assert_response_type(anonymous, "error")
    a.assert_error_meta_present(anonymous)

    blank = api.create_pilot_order(
        {"project_id": NON_EXISTENT_UUID}, blank_auth_headers()
    )
    validate_error(blank, e.ERR_UNAUTHENTICATED, 401)
    a.assert_error_meta_present(blank)


def test_a_research_analyst_cannot_order_a_pilot_though_it_may_read_one(api):
    """The role gate is endpoint-scoped: the same role reads pilot orders happily.

    PRD 2.1: "If the supplied role is not one of the seven roles below, or is a
    valid role that is not authorised for the endpoint being called, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/a_research_analyst_ordering_a_pilot_returns_unauthorized
    """
    refused = api.create_pilot_order(
        f.pilot_order_payload(NON_EXISTENT_UUID), research_analyst_headers()
    )
    validate_error(refused, e.ERR_UNAUTHORIZED, 403)

    ctx = build_scenario(api, "pilot_ordered")
    readable = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, research_analyst_headers())
    )
    assert readable["id"] == ctx.pilot_order_id, (
        "the role is authenticated and usable on the read surface"
    )
    assert readable["production_status"] == PRODUCTION_ORDERED


def test_the_feasibility_projection_is_withheld_from_the_platform_admin(api):
    """The admin reads every other entity, and the projection alone is carved out.

    PRD 2.1: "`PlatformAdmin` - network operations administrator. Registers agencies
    and opens slates, and is the only role permitted to drive the logical clock.
    Holds read access across every entity except the feasibility computation."

    Design: Corner/rbac/platform_admin_cannot_read_the_feasibility_projection
    """
    ctx = build_scenario(api, "script_complete")

    refused = api.get_feasibility(NON_EXISTENT_UUID, platform_admin_headers())
    validate_error(refused, e.ERR_UNAUTHORIZED, 403)

    projection = validate_success(
        api.get_feasibility(ctx.project_id, finance_controller_headers())
    )
    assert projection["verdict"] == VERDICT_FEASIBLE, (
        "the identical read from the finance officer is served"
    )

    slate = validate_success(api.get_slate(ctx.slate_id, platform_admin_headers()))
    assert slate["id"] == ctx.slate_id, "only the projection is withheld from the admin"


def test_one_agencys_rep_may_not_submit_under_another_agencys_banner(api):
    """Both agencies are packaging-enabled and the body is complete, so only identity fails.

    PRD 2.1: "ownership checks compare the `agency_id` on the resource being touched
    to `X-User-ID`: the `agency_id` in a pitch submission payload ... A mismatch is
    rejected with `ERR_AGENCY_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/an_agency_rep_pitching_on_behalf_of_a_rival_agency_returns_agency_scope_violation
    """
    ctx = fx.bootstrap(api)
    rival = validate_success(
        api.create_agency(f.rival_agency_payload(), platform_admin_headers()), 201
    )
    assert rival["packaging_allowed"] is True

    body = f.pitch_payload(rival["id"], ctx.slate_id)
    refused = api.create_pitch(body, agency_rep_headers(ctx.agency_id))
    validate_error(refused, e.ERR_AGENCY_SCOPE_VIOLATION, 403)

    rows, meta = validate_paginated(
        api.list_pitches(
            agency_rep_headers(rival["id"]),
            {"agency_id": rival["id"], "limit": 10, "offset": 0},
        )
    )
    assert rows == [], "nothing was written under the rival's banner"
    a.assert_pagination_meta(meta, total_count=0)

    untouched = validate_success(
        api.get_agency(rival["id"], business_affairs_headers())
    )
    assert untouched["submissions_used_count"] == 0

    accepted = validate_success(
        api.create_pitch(body, agency_rep_headers(rival["id"])), 201
    )
    assert accepted["agency_id"] == rival["id"], "only the acting identity was wrong"


def test_the_finance_officer_may_not_cast_the_creative_vote(api):
    """The role is on the decisions endpoint, so the refusal is the committee pairing.

    PRD 2.1: "A greenlight decision naming the `CREATIVE` committee is only accepted
    from `DevelopmentExec`, `BUSINESS` only from `BusinessAffairs`, and `FINANCE`
    only from `FinanceController`; a mismatch is an `ERR_UNAUTHORIZED` rejection."

    Design: Corner/rbac/a_finance_controller_voting_the_creative_committee_returns_unauthorized
    """
    wrong_committee = api.record_decision(
        NON_EXISTENT_UUID,
        f.decision_payload(COMMITTEE_CREATIVE, DECISION_APPROVED),
        finance_controller_headers(),
    )
    validate_error(wrong_committee, e.ERR_UNAUTHORIZED, 403)

    own_committee = api.record_decision(
        NON_EXISTENT_UUID,
        f.decision_payload(COMMITTEE_FINANCE, DECISION_APPROVED),
        finance_controller_headers(),
    )
    validate_error(own_committee, e.ERR_GREENLIGHT_NOT_FOUND, 404)


def test_only_business_affairs_may_waive_a_contingency_the_exec_may_satisfy_one(api):
    """The same endpoint, the same pilot and the same role: only the WAIVED value is barred.

    PRD 2.1: "on a pilot contingency clearance, the `WAIVED` resolution is reserved
    to `BusinessAffairs` - a `DevelopmentExec` may record `SATISFIED` or `FAILED`
    only, and an attempt to waive is likewise `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/a_development_exec_waiving_a_casting_contingency_returns_unauthorized
    """
    ctx = build_scenario(api, "pilot_ordered")

    refused = api.clear_contingency(
        ctx.pilot_order_id,
        f.contingency_payload(CONTINGENCY_CASTING, CONTINGENCY_WAIVED),
        development_exec_headers(),
    )
    validate_error(refused, e.ERR_UNAUTHORIZED, 403)

    unchanged = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, development_exec_headers())
    )
    assert unchanged["casting_status"] == CONTINGENCY_PENDING
    assert unchanged["location_status"] == CONTINGENCY_PENDING
    assert unchanged["production_status"] == PRODUCTION_ORDERED

    waived = validate_success(
        api.clear_contingency(
            ctx.pilot_order_id,
            f.contingency_payload(CONTINGENCY_CASTING, CONTINGENCY_WAIVED),
            business_affairs_headers(),
        )
    )
    assert waived["casting_status"] == CONTINGENCY_WAIVED
    assert waived["production_status"] == PRODUCTION_ORDERED, "one dimension is a self-loop"

    satisfied = validate_success(
        api.clear_contingency(
            ctx.pilot_order_id,
            f.contingency_payload(CONTINGENCY_LOCATION, CONTINGENCY_SATISFIED),
            development_exec_headers(),
        )
    )
    assert satisfied["location_status"] == CONTINGENCY_SATISFIED
    # A waiver on one dimension and a satisfaction on the other is as green as two.
    assert satisfied["production_status"] == PRODUCTION_GREEN_TO_SHOOT


def test_one_identity_may_carry_only_one_committee_on_a_single_request(api):
    """u-shared-1 decided CREATIVE, so both of its later votes are barred by identity.

    PRD 2.1: "One opaque identifier may record at most one committee decision on any
    single greenlight request; an attempt to record a second is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/one_user_id_recording_two_committee_decisions_returns_segregation_of_duties
    """
    ctx = build_scenario(api, "greenlight")
    fx.record_creative_decision(api, ctx.greenlight_id, DECISION_APPROVED, USER_SHARED_1)

    refused = api.record_decision(
        ctx.greenlight_id,
        f.decision_payload(COMMITTEE_BUSINESS, DECISION_APPROVED),
        business_affairs_headers(USER_SHARED_1),
    )
    validate_error(refused, e.ERR_SEGREGATION_OF_DUTIES, 403)

    request = validate_success(
        api.get_greenlight_request(ctx.greenlight_id, finance_controller_headers())
    )
    assert request["status"] == GL_OPEN
    assert request["creative_decision"] == DECISION_APPROVED
    assert request["creative_decided_by_user_id"] == USER_SHARED_1
    assert request["business_decision"] == DECISION_PENDING

    accepted = validate_success(
        api.record_decision(
            ctx.greenlight_id,
            f.decision_payload(COMMITTEE_BUSINESS, DECISION_APPROVED),
            business_affairs_headers(USER_BA_9),
        )
    )
    assert accepted["business_decision"] == DECISION_APPROVED
    assert accepted["business_decided_by_user_id"] == USER_BA_9

    third = api.record_decision(
        ctx.greenlight_id,
        f.decision_payload(COMMITTEE_FINANCE, DECISION_APPROVED),
        finance_controller_headers(USER_SHARED_1),
    )
    # The bar is on any second committee, not only on the adjacent one.
    validate_error(third, e.ERR_SEGREGATION_OF_DUTIES, 403)


def test_every_role_performs_its_own_exclusive_write_along_one_greenlit_path(api):
    """Seven roles, one walk, no refusal: the positive half of the role model.

    PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the function that
    principal is acting in."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_write_along_one_greenlit_path
    """
    # The walk itself is the assertion: the admin opens the agency and slate and drives
    # the clock, the rep registers the writer and pitches, business affairs files the
    # clearance, the deal, the step exercise, the term sheet and the request, the exec
    # covers, advances, reviews, orders, clears and wraps, the analyst screens and
    # certifies, and the studio accepts. Any refusal raises inside the fixture.
    ctx = build_scenario(api, "greenlight")
    fx.record_creative_decision(api, ctx.greenlight_id)
    fx.record_business_decision(api, ctx.greenlight_id)

    approved = validate_success(
        api.record_decision(
            ctx.greenlight_id,
            f.decision_payload(COMMITTEE_FINANCE, DECISION_APPROVED),
            finance_controller_headers(),
        )
    )
    assert approved["status"] == GL_APPROVED
    assert approved["creative_decision"] == DECISION_APPROVED
    assert approved["business_decision"] == DECISION_APPROVED
    assert approved["finance_decision"] == DECISION_APPROVED
    deciders = {
        approved["creative_decided_by_user_id"],
        approved["business_decided_by_user_id"],
        approved["finance_decided_by_user_id"],
    }
    assert len(deciders) == 3, f"three distinct deciders are required, got {deciders}"

    project = validate_success(api.get_project(ctx.project_id, finance_controller_headers()))
    assert project["dev_status"] == DEV_SERIES_ORDERED

    negotiations = validate_success(
        api.list_project_negotiations(ctx.project_id, studio_partner_headers())
    )
    assert [row["id"] for row in negotiations] == [ctx.negotiation_id]
    assert negotiations[0]["status"] == NEG_AGREED
    assert negotiations[0]["episode_count"] == 10

    screenings, screening_meta = validate_paginated(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    a.assert_ids(screenings, [ctx.screening_id])
    assert screenings[0]["status"] == SCREENING_CERTIFIED
    a.assert_score(screenings[0]["norm_adjusted_score"], 63.8, "norm_adjusted_score")
    a.assert_pagination_meta(screening_meta, total_count=1)

    pitches, pitch_meta = validate_paginated(
        api.list_pitches(
            agency_rep_headers(ctx.agency_id),
            {"agency_id": ctx.agency_id, "limit": 10, "offset": 0},
        )
    )
    a.assert_ids(pitches, [ctx.pitch_id])
    a.assert_pagination_meta(pitch_meta, total_count=1)
