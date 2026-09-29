"""Temporal occupancy: closed billing periods, buffered service windows, window-scoped capacity."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_null, assert_same_instant


def _billed_matter(api):
    """One matter with a single August invoice already submitted."""
    S.create_jurisdictions(api, ["CA", "TX"])
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["CA", "TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    applicant = S.create_applicant(api)
    assessment = S.create_approved_assessment(api, applicant["id"], plan_id)
    policy = S.bind_policy(api, assessment["id"])
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=9000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-01T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=10000000,
        panel_firm_id=firm["id"],
    )
    invoice = S.submit_invoice(
        api,
        assignment["id"],
        firm["id"],
        period_start="2026-08-01T00:00:00.000Z",
        period_end="2026-08-31T00:00:00.000Z",
        partner_hours=None,
        associate_hours=20.0,
        paralegal_hours=None,
        block_billed_hours=None,
        expenses_cents=None,
    )
    return {
        "firm_id": firm["id"],
        "assignment_id": assignment["id"],
        "invoice_id": invoice["id"],
    }


def test_billing_periods_that_touch_at_an_endpoint_collide(api):
    """A new start equal to the incumbent's inclusive end is a collision.

    PRD: "Because billing periods are closed intervals, a new period collides
    with an existing invoice on the same assignment when the new start is at or
    before the existing end and the existing start is at or before the new end;
    touching endpoints therefore do collide, and a collision with any invoice
    that is not `VOIDED` and not `REJECTED` is `ERR_INVOICE_PERIOD_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/invoice_billing_period_closed_interval_single_occupancy
    """
    world = _billed_matter(api)
    counsel = U.panel_counsel(world["firm_id"])
    validate_error(
        api.submit_invoice(
            world["assignment_id"],
            F.invoice(
                period_start="2026-08-31T00:00:00.000Z",
                period_end="2026-09-30T00:00:00.000Z",
                partner_hours=None,
                associate_hours=10.0,
                paralegal_hours=None,
                block_billed_hours=None,
                expenses_cents=None,
            ),
            counsel,
        ),
        E.ERR_INVOICE_PERIOD_OVERLAP,
        409,
    )

    _, meta = validate_paginated(
        api.list_invoices(U.ADJUSTER, {"defense_assignment_id": world["assignment_id"]})
    )
    assert meta["total_count"] == 1

    audited = get_success_data(api.audit_invoice(world["invoice_id"], U.ADJUSTER))
    assert_fields(
        audited,
        {
            "billed_fees_cents": 1020000,
            "rate_cap_excess_cents": 120000,
            "allowed_amount_cents": 900000,
        },
    )


def test_a_period_starting_a_day_past_the_incumbent_is_disjoint(api):
    """The next period may open one day after the incumbent's inclusive end.

    PRD: "Invoices are created in `SUBMITTED` with every audit output field
    unpopulated."

    Design: Difficulty/resource_temporal_overlap/invoice_billing_period_closed_interval_single_occupancy
    """
    world = _billed_matter(api)
    counsel = U.panel_counsel(world["firm_id"])
    second = get_success_data(
        api.submit_invoice(
            world["assignment_id"],
            F.invoice(
                period_start="2026-09-01T00:00:00.000Z",
                period_end="2026-09-30T00:00:00.000Z",
                partner_hours=None,
                associate_hours=10.0,
                paralegal_hours=None,
                block_billed_hours=None,
                expenses_cents=None,
            ),
            counsel,
        ),
        201,
    )
    assert second["status"] == T.INVOICE_SUBMITTED
    assert_null(second, ["billed_fees_cents", "allowed_amount_cents", "audited_by_user_id"])

    audited = get_success_data(api.audit_invoice(second["id"], U.ADJUSTER))
    assert_fields(
        audited,
        {
            "billed_fees_cents": 510000,
            "rate_cap_excess_cents": 60000,
            "allowed_amount_cents": 450000,
            "disallowed_amount_cents": 60000,
        },
    )

    _, meta = validate_paginated(
        api.list_invoices(U.ADJUSTER, {"defense_assignment_id": world["assignment_id"]})
    )
    assert meta["total_count"] == 2

    assignment = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert assignment["budget_spent_cents"] == 0


def _serviced_applicant(api):
    """A CA applicant with one ACTIVE hotline subscription running to 2026-10-01."""
    S.create_jurisdiction(api, "CA")
    applicant = S.create_applicant(
        api,
        jurisdiction_headcounts=[{"code": "CA", "headcount": 400}],
        primary_jurisdiction_code="CA",
    )
    service = S.create_active_risk_service(
        api,
        applicant["id"],
        service_type=T.SERVICE_HOTLINE,
        credit_pct=0.08,
        effective_from="2026-07-01T00:00:00.000Z",
        effective_to="2026-10-01T00:00:00.000Z",
    )
    return {"applicant_id": applicant["id"], "service_id": service["id"], "service": service}


def test_the_thirty_day_buffer_refuses_a_merely_touching_service_window(api):
    """A window opening at the incumbent's end still sits inside the buffered tail.

    PRD: "A new service may not conflict with an existing non-`REVOKED` service
    of the **same** `service_type` on the same applicant, and the conflict test
    deliberately pads the existing window: a thirty-day gap buffer is added to
    the high side of the existing window, so the new service collides when its
    start falls strictly before thirty days past the existing end and the
    existing start falls strictly before the new end."

    Design: Difficulty/resource_temporal_overlap/risk_service_half_open_window_with_thirty_day_buffer
    """
    world = _serviced_applicant(api)
    assert_fields(world["service"], {"status": T.SERVICE_ACTIVE, "credit_pct": 0.08})

    validate_error(
        api.create_risk_service(
            world["applicant_id"],
            F.risk_service(
                service_type=T.SERVICE_HOTLINE,
                credit_pct=0.08,
                effective_from="2026-10-01T00:00:00.000Z",
                effective_to="2027-10-01T00:00:00.000Z",
            ),
            U.UNDERWRITER,
        ),
        E.ERR_SERVICE_WINDOW_CONFLICT,
        409,
    )


def test_the_buffered_comparison_is_half_open_and_scoped_per_service_type(api):
    """A window opening exactly at the buffered tail is free, as is another type.

    PRD: "Services of different types may overlap freely."

    Design: Difficulty/resource_temporal_overlap/risk_service_half_open_window_with_thirty_day_buffer
    """
    world = _serviced_applicant(api)
    validate_error(
        api.create_risk_service(
            world["applicant_id"],
            F.risk_service(
                service_type=T.SERVICE_HOTLINE,
                credit_pct=0.08,
                effective_from="2026-10-01T00:00:00.000Z",
                effective_to="2027-10-01T00:00:00.000Z",
            ),
            U.UNDERWRITER,
        ),
        E.ERR_SERVICE_WINDOW_CONFLICT,
        409,
    )

    at_tail = get_success_data(
        api.create_risk_service(
            world["applicant_id"],
            F.risk_service(
                service_type=T.SERVICE_HOTLINE,
                credit_pct=0.08,
                effective_from="2026-10-31T00:00:00.000Z",
                effective_to="2027-10-31T00:00:00.000Z",
            ),
            U.UNDERWRITER,
        ),
        201,
    )
    assert at_tail["status"] == T.SERVICE_PENDING
    assert_same_instant(at_tail["effective_from"], "2026-10-31T00:00:00.000Z", "effective_from")

    other_type = get_success_data(
        api.create_risk_service(
            world["applicant_id"],
            F.risk_service(
                service_type=T.SERVICE_HANDBOOK,
                credit_pct=0.05,
                effective_from="2026-10-01T00:00:00.000Z",
                effective_to="2027-10-01T00:00:00.000Z",
            ),
            U.UNDERWRITER,
        ),
        201,
    )
    assert other_type["service_type"] == T.SERVICE_HANDBOOK
    assert_same_instant(other_type["effective_from"], "2026-10-01T00:00:00.000Z", "effective_from")

    _, meta = validate_paginated(
        api.list_risk_services(U.UNDERWRITER, {"applicant_id": world["applicant_id"]})
    )
    assert meta["total_count"] == 3

    applicant = get_success_data(api.get_applicant(world["applicant_id"], U.UNDERWRITER))
    assert applicant["risk_credit_pct"] == 0.08


def _two_overlapping_matters(api):
    """A REGIONAL firm of capacity two already holding two overlapping matters."""
    S.create_jurisdictions(api, ["CA", "TX"])
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Bellweather Rowe LLP",
        tier=T.TIER_REGIONAL,
        jurisdiction_codes=["CA"],
        partner_rate_cents_per_hour=70000,
        associate_rate_cents_per_hour=43000,
        paralegal_rate_cents_per_hour=16000,
        capacity_open_matters=2,
    )
    applicant = S.create_applicant(api)
    assessment = S.create_approved_assessment(api, applicant["id"], plan_id)
    policy = S.bind_policy(api, assessment["id"])
    claims = []
    for day in ("2026-08-01", "2026-08-02", "2026-08-03"):
        claims.append(
            S.accepted_claim(
                api,
                policy["id"],
                claim_type=T.CLAIM_TYPE_DISCRIMINATION,
                claimant_class=T.CLAIMANT_EMPLOYEE,
                notice_type=T.NOTICE_LAWSUIT,
                first_notice_at=f"{day}T00:00:00.000Z",
                alleged_damages_cents=8000000,
            )
        )
    first = S.create_assignment(
        api,
        claims[0]["id"],
        engagement_from="2026-08-01T00:00:00.000Z",
        engagement_to="2026-10-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=firm["id"],
    )
    second = S.create_assignment(
        api,
        claims[1]["id"],
        engagement_from="2026-09-01T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=firm["id"],
    )
    return {
        "firm_id": firm["id"],
        "first": first,
        "second": second,
        "third_claim_id": claims[2]["id"],
    }


def test_a_third_overlapping_window_exceeds_the_firms_capacity(api):
    """Two concurrent matters already fill the window-scoped ceiling of two.

    PRD: "and a named firm already holding `capacity_open_matters`
    window-overlapping assignments in `ACTIVE` or `SUSPENDED_FUNDING` is
    `ERR_PANEL_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/panel_firm_window_scoped_capacity_of_two
    """
    world = _two_overlapping_matters(api)
    assert world["first"]["status"] == T.ASSIGNMENT_ACTIVE
    assert world["second"]["status"] == T.ASSIGNMENT_ACTIVE

    validate_error(
        api.create_assignment(
            world["third_claim_id"],
            F.assignment(
                engagement_from="2026-09-15T00:00:00.000Z",
                engagement_to="2026-10-15T00:00:00.000Z",
                budget_cap_cents=3000000,
                panel_firm_id=world["firm_id"],
            ),
            U.ADJUSTER,
        ),
        E.ERR_PANEL_CAPACITY_EXCEEDED,
        409,
    )

    claim = get_success_data(api.get_claim(world["third_claim_id"], U.ADJUSTER))
    assert claim["status"] == T.CLAIM_COVERAGE_ACCEPTED

    _, meta = validate_paginated(
        api.list_assignments(U.ADJUSTER, {"claim_id": world["third_claim_id"]})
    )
    assert meta["total_count"] == 0


def test_capacity_constrains_overlap_not_the_lifetime_open_matter_count(api):
    """A disjoint window is engaged even though open_matter_count then exceeds capacity.

    PRD: "That matter count is window-scoped rather than global: it counts the
    firm's defense assignments whose status is `ACTIVE` or `SUSPENDED_FUNDING`
    and whose engagement window overlaps the requested one under the half-open
    rule, meaning the existing window begins strictly before the requested
    window ends and the requested window begins strictly before the existing one
    ends."

    Design: Difficulty/resource_temporal_overlap/panel_firm_window_scoped_capacity_of_two
    """
    world = _two_overlapping_matters(api)
    third = S.create_assignment(
        api,
        world["third_claim_id"],
        engagement_from="2026-11-01T00:00:00.000Z",
        engagement_to="2026-12-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=world["firm_id"],
    )
    assert_fields(
        third,
        {
            "status": T.ASSIGNMENT_ACTIVE,
            "panel_firm_id": world["firm_id"],
            "selection_reason": T.SELECTION_CLIENT_DIRECTED,
            "budget_remaining_cents": 3000000,
        },
    )

    firm = get_success_data(api.get_panel_firm(world["firm_id"], U.ADMIN))
    assert firm["open_matter_count"] == 3
