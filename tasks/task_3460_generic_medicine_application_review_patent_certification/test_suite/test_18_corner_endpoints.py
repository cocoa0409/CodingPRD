"""Queue B / endpoints: supplement decision effectivity, award filters, foreign pass."""
from test_helpers import (
    api_client, validate_success, validate_paginated, TEST_USERS,
    set_clock, setup_approved, make_applicant, make_reference_product,
    make_application, add_be_study, make_listed_patent, add_certification,
    make_facility, schedule_and_pass_inspection, submit_application,
    list_awards, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_prior_approval_supplement_decision_sets_effective_on_decision_date():
    """PRD section 3.9: "A `PRIOR_APPROVAL` supplement, by contrast, becomes
    effective only upon approval, with `effective_date` equal to the decision
    date."

    Design: Corner/endpoints/prior_approval_supplement_decision_sets_effective_on_decision_date
    """
    ctx = setup_approved()
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]

    set_clock("2026-09-15T00:00:00Z")
    supp = validate_success(api_client.create_supplement(app_id, {
        "change_type": "MANUFACTURING_SITE", "pathway": "PRIOR_APPROVAL",
        "description": "add second manufacturing site"},
        make_applicant_headers(ac_id)), 201)
    assert supp["review_status"] == "SUBMITTED"
    assert supp["effectivity"] == "NOT_EFFECTIVE", (
        "the prior-approval pathway never self-effectuates")

    set_clock("2026-10-01T00:00:00Z")
    decided = validate_success(api_client.supplement_review_decision(
        supp["id"], {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided["review_status"] == "APPROVED"
    assert decided["effectivity"] == "EFFECTIVE"
    assert decided["effective_date"] == "2026-10-01"
    assert decided["decision_date"] == "2026-10-01"


def test_exclusivity_awards_filter_by_reference_product():
    """PRD section 2.3: list endpoints "additionally accept an optional
    `status` filter or reverse foreign-key filters such as `applicant_id`,
    `reference_product_id`, `application_id`, `patent_id`, or `facility_id`;
    these narrow the collection without changing the sort order."

    Design: Corner/endpoints/exclusivity_awards_filter_by_reference_product
    """
    ac = make_applicant(legal_name="Filter Award Co")
    owner = "innovator-ops-80"
    rld1 = make_reference_product(brand_name="AwardOne", rld_approval_date="2001-01-01",
                                  patent_owner_user_id=owner)
    rld2 = make_reference_product(brand_name="AwardTwo", rld_approval_date="2001-01-01",
                                  patent_owner_user_id=owner)
    pat1 = make_listed_patent(rld1, patent_number="US1616001")
    pat2 = make_listed_patent(rld2, patent_number="US1616002")

    app_ids = {}
    for rld, pat, analyte in ((rld1, pat1, "awardone"), (rld2, pat2, "awardtwo")):
        app = make_application(rld["id"], ac["id"])
        add_be_study(app["id"], ac["id"], analyte=analyte)
        add_certification(app["id"], ac["id"], pat["id"])
        app_ids[rld["id"]] = app["id"]
        submit_application(app["id"], ac["id"])

    rows = list_awards(reference_product_id=rld1["id"])
    assert len(rows) == 1
    assert rows[0]["application_id"] == app_ids[rld1["id"]]
    assert rows[0]["status"] == "ELIGIBLE"

    rows = list_awards(application_id=app_ids[rld2["id"]])
    assert len(rows) == 1 and rows[0]["application_id"] == app_ids[rld2["id"]]

    all_rows, meta = validate_paginated(api_client.list_exclusivity_awards(REVIEWER))
    assert len(all_rows) == 2


def test_foreign_site_passed_inspection_satisfies_clearance():
    """PRD section 3.6: "Clearance demands that every facility's latest
    outcome be `PASSED` or `WAIVED`, and additionally that every foreign
    facility have at least one `PASSED` inspection for this application — a
    waiver never clears a foreign site."

    Design: Corner/endpoints/foreign_site_passed_inspection_satisfies_clearance
    """
    applicant = make_applicant(legal_name="Foreign Pass Co", headquarters_country="IN")
    rld = make_reference_product(brand_name="Forexpass", rld_approval_date="2000-01-01")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"], analyte="forexpassol")
    facility = make_facility(applicant["id"], facility_name="Hyderabad Plant",
                             fei_number="FEI-IN-9", country_code="IN")
    assert facility["is_foreign"] is True
    schedule_and_pass_inspection(facility["id"], app["id"])
    submit_application(app["id"], applicant["id"])

    decided = validate_success(api_client.approval_decision(
        app["id"], {"decision": "APPROVE"}, REVIEWER), 200)
    assert decided["status"] == "APPROVED", (
        "a foreign site satisfies clearance only via a real PASSED inspection")
