"""Role surfaces, the two two-person rules and the franchisee ownership check."""

from test_helpers import (
    BSD_HEADERS,
    FDM_DECIDER_HEADERS,
    FDM_HEADERS,
    QA_HEADERS,
    QA_SECOND_HEADERS,
    ApiErrorId,
    assert_instant,
    assert_integer,
    assert_money,
    factories,
    fixtures,
    get_success_data,
    make_owner_headers,
    validate_error,
    validate_paginated_list,
)

LIFE_SAFETY_CRITICAL_LINE = {
    "category": "LIFE_SAFETY",
    "priority": "CRITICAL",
    "description": "Stairwell pressurisation and emergency lighting",
    "estimated_cost": 480_000.00,
}


def test_no_role_may_reach_across_into_another_roles_exclusive_operations(api):
    """PRD §2.1 and §4: the endpoint table is the authoritative role list, and a
    request whose role is not on it is refused before anything else happens - the
    brand registry is closed to the development officer, entity registration to
    the inspector, review opening to the franchisee, the market study to the
    inspector, and even the application read to the inspector, whose authority
    stops at inspections and cures.  No refused write left a trace: the brand
    code the first attempt carried is still free.

    Design: Corner/rbac/each_roles_exclusive_operations_cannot_be_performed_by_another_role
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)
    owner = fixtures.create_strong_owner(api)
    application = fixtures.create_application(api, owner["id"], brand["id"])
    version_at_intake = application["version"]

    aurora = factories.build_brand_payload(
        code="AURORA",
        name="Aurora Hotels",
        tier="UPSCALE",
        base_royalty_rate_pct=5.50,
        marketing_fund_rate_pct=2.00,
        protected_radius_miles=4.00,
        min_room_count=100,
        standard_term_years=15,
    )
    attempts = (
        api.create_brand(aurora, FDM_HEADERS),
        api.create_owner(factories.build_owner_payload(), QA_HEADERS),
        api.start_application_review(application["id"], {}, make_owner_headers(owner["id"])),
        api.run_impact_analysis(application["id"], {}, QA_HEADERS),
        api.get_application(application["id"], QA_HEADERS),
    )
    for response in attempts:
        validate_error(response, ApiErrorId.UNAUTHORIZED)
        assert response.status_code == 403

    _, meta = validate_paginated_list(api.list_applications(FDM_HEADERS))
    assert_integer(meta["total_count"], 1, "total_count")

    stored = get_success_data(api.get_application(application["id"], FDM_HEADERS))
    assert stored["status"] == "SUBMITTED"
    assert stored["financial_review_status"] == "NOT_STARTED"
    assert stored["impact_study_status"] == "NOT_STARTED"
    assert_integer(stored["version"], version_at_intake, "version")

    assert get_success_data(api.get_brand(brand["id"], BSD_HEADERS))["code"] == "SOLARIS"
    accepted = get_success_data(api.create_brand(aurora, BSD_HEADERS), 201)
    assert accepted["code"] == "AURORA", (
        "the refused registration must not have consumed the brand code"
    )


def test_the_inspector_who_scored_the_inspection_may_not_review_its_cure(api):
    """PRD §2.10: the second of the two two-person rules is expressed against the
    identifier stored when the inspection was scored, so the scoring inspector's
    own cure review is refused while a colleague's identical review is accepted.
    The passed cure is the only route back to COMPLIANT, and it leaves both
    identifiers on the record side by side.

    Design: Corner/rbac/the_inspector_who_scored_the_inspection_cannot_review_its_cure
    """
    world = fixtures.setup_open_agreement(api)
    fixtures.set_clock(api, "2026-11-15T00:00:00Z")
    inspection = fixtures.score_inspection(
        api, world["agreement_id"], QA_HEADERS,
        cleanliness_score=60, condition_score=60,
        brand_standard_score=60, guest_experience_score=60,
    )
    assert_money(inspection["total_score"], 60.00, "total_score")
    assert inspection["grade"] == "FAIL"
    assert_instant(inspection["cure_deadline"], "2026-12-15T00:00:00.000Z", "cure_deadline")
    assert inspection["inspector_user_id"] == "qai-first-01"

    fixtures.set_clock(api, "2026-12-01T00:00:00Z")
    fixtures.submit_cure(api, inspection["id"], world["owner_id"])

    self_review = api.review_inspection_cure(
        inspection["id"],
        factories.build_cure_review_payload("PASS", review_notes="Reviewing my own inspection."),
        QA_HEADERS,
    )
    validate_error(self_review, ApiErrorId.SEGREGATION_OF_DUTIES)
    assert self_review.status_code == 403
    still = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert still["compliance_status"] == "CURE_PERIOD", (
        "the refused review may not rehabilitate the agreement"
    )

    rows, _ = validate_paginated_list(
        api.list_agreement_qa_inspections(world["agreement_id"], QA_HEADERS, {"limit": 10})
    )
    assert rows[0]["status"] == "CURE_SUBMITTED"
    assert rows[0]["cure_reviewer_user_id"] is None

    reviewed = fixtures.review_cure(api, inspection["id"], "PASS", QA_SECOND_HEADERS)
    assert reviewed["status"] == "CURE_PASSED"
    assert reviewed["cure_reviewer_user_id"] == "qai-second-02"
    assert reviewed["inspector_user_id"] == "qai-first-01"
    assert_money(reviewed["total_score"], 60.00, "total_score")
    assert reviewed["grade"] == "FAIL"
    assert_instant(reviewed["cure_deadline"], "2026-12-15T00:00:00.000Z", "cure_deadline")
    assert_instant(
        reviewed["cure_submitted_at"], "2026-12-01T00:00:00.000Z", "cure_submitted_at"
    )

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert agreement["compliance_status"] == "COMPLIANT"
    assert_integer(
        agreement["consecutive_qa_failure_count"], 0, "consecutive_qa_failure_count"
    )


def test_the_operator_who_recorded_the_review_may_not_decide_the_same_file(api):
    """PRD §2.10: both steps are development-officer actions, so the role check
    passes on each and the identity comparison carries the whole rule - the
    recorded reviewer's own approval is refused, and a colleague's identical
    approval is accepted.  The refusal leaves no actor of record on the file, and
    the accepted decision stores the two identifiers separately.

    Design: Corner/rbac/the_financial_reviewer_cannot_issue_the_same_applications_decision
    """
    world = fixtures.setup_reviewed_application(api)
    assert world["application"]["financial_reviewer_user_id"] == "fdm-review-01"
    assert world["application"]["encroachment_verdict"] == "CLEAR"

    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    response = api.decide_application(
        world["application_id"],
        factories.build_decision_payload(
            "APPROVE", decision_notes="Approving the file I reviewed."
        ),
        FDM_HEADERS,
    )
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES)
    assert response.status_code == 403

    blocked = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert blocked["status"] == "UNDER_REVIEW"
    assert blocked["decision_user_id"] is None
    assert blocked["decided_at"] is None

    approved = get_success_data(
        api.decide_application(
            world["application_id"],
            factories.build_decision_payload("APPROVE", decision_notes="Independent approval."),
            FDM_DECIDER_HEADERS,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["decision_user_id"] == "fdm-decision-02"
    assert approved["financial_reviewer_user_id"] == "fdm-review-01"
    assert_instant(approved["decided_at"], "2026-09-01T00:00:00.000Z", "decided_at")
    assert approved["financial_review_status"] == "PASSED"
    assert_money(approved["capacity_score_at_review"], 100.00, "capacity_score_at_review")
    assert approved["capacity_band_at_review"] == "STRONG"

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 0, "open_application_count")


def test_a_franchisee_reaches_only_the_estate_behind_its_own_application(api):
    """PRD §2.1: the franchisee identity is entity-backed, and a plan is reached
    back to an ownership entity through its agreement's application - so a
    bystander entity may neither accept the plan nor even read the license, while
    the entity named on the application accepts it and stamps the acceptance
    clock, which is what gives every scope line its deadline.

    Design: Corner/rbac/an_owner_cannot_accept_another_owners_improvement_plan
    """
    world = fixtures.setup_scoped_plan(api, scope_lines=[LIFE_SAFETY_CRITICAL_LINE])
    bystander = fixtures.create_second_owner(api)
    assert bystander["id"] != world["owner_id"]
    bystander_headers = make_owner_headers(bystander["id"])

    fixtures.set_clock(api, "2026-10-05T00:00:00Z")
    foreign_accept = api.accept_pip(
        world["plan_id"], factories.build_pip_accept_payload(), bystander_headers
    )
    validate_error(foreign_accept, ApiErrorId.FORBIDDEN_RESOURCE_OWNER)
    assert foreign_accept.status_code == 403
    blocked = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert blocked["status"] == "SCOPED"
    assert blocked["accepted_at"] is None

    foreign_read = api.get_agreement(world["agreement_id"], bystander_headers)
    validate_error(foreign_read, ApiErrorId.FORBIDDEN_RESOURCE_OWNER)
    assert foreign_read.status_code == 403

    accepted = get_success_data(
        api.accept_pip(
            world["plan_id"],
            factories.build_pip_accept_payload(),
            make_owner_headers(world["owner_id"]),
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert_instant(accepted["accepted_at"], "2026-10-05T00:00:00.000Z", "accepted_at")
    assert_integer(accepted["items_pending_count"], 1, "items_pending_count")

    rows, _ = validate_paginated_list(api.list_pip_items(world["plan_id"], BSD_HEADERS))
    assert rows[0]["status"] == "PENDING"
    assert_instant(
        rows[0]["due_date"],
        "2026-11-19T00:00:00.000Z",
        "due_date (45 category days beating 90 priority days)",
    )
