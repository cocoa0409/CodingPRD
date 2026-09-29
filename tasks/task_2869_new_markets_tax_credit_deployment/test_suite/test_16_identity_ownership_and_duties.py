"""Who may act, on whose records, and who may never measure their own work.

The identity ladder is answered from the top: authentication before role,
role before referential wiring, ownership before business rules, and
segregation of duties before the sequence of the compliance years.
"""
from test_helpers import (
    AGENCY_USER_ID,
    ApiErrorId,
    CLOCK_DEFAULT_UTC,
    REVIEWER_ANNUAL_USER_ID,
    REVIEWER_ELIGIBILITY_USER_ID,
    SETUP_CLOCK,
    SPONSOR_DELTA_USER_ID,
    agency_report_payload,
    annual_test_payload,
    assert_cents,
    assert_pct,
    create_cba,
    create_cde,
    create_qei_payload,
    create_qlici_payload,
    get_success_data,
    issue_qei,
    make_agency_headers,
    make_cde_sponsor_headers,
    make_headers,
    make_reviewer_headers,
    read_award,
    read_qei,
    set_clock,
    setup_active_award,
    setup_certified_project_company,
    setup_deployed_investment,
    setup_funded_fund,
    setup_two_entities,
    validate_error,
    validate_paginated,
    validate_success,
    void_qei_payload,
)

UNKNOWN_AWARD_ID = "00000000-0000-4000-8000-0000000000d1"


def test_a_business_sponsor_is_refused_before_the_award_is_ever_looked_up(api):
    """The role rung answers first, even for an award that does not exist.

    PRD: "If the headers are well-formed but the named role is not authorised
    for the target operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP
    403)."

    PRD: "The acting role is authorised for the target operation, on every
    operation — otherwise `ERR_ROLE_NOT_PERMITTED`."

    PRD: "Every foreign key in the body resolves, in input-declaration order, on
    award announcement, census-tract registration, business registration,
    investment issuance, sub-allocation deployment and agreement creation —
    otherwise the matching not-found code."

    PRD: "It registers the business, files its job reports, and holds the call
    option at unwind."

    Design: Corner/rbac/a_qalicb_sponsor_cannot_issue_a_qei_or_deploy_a_qlici
    """
    scenario = setup_active_award(
        api, clock=SETUP_CLOCK, certification_suffix=128
    )
    setup_certified_project_company(api, scenario)
    scenario.cba = create_cba(
        api, scenario.cde, scenario.qalicb, scenario.award
    )
    setup_funded_fund(api, scenario)
    assert scenario.qalicb["sponsor_user_id"] == SPONSOR_DELTA_USER_ID

    award = read_award(api, scenario.award["id"])
    issuance = create_qei_payload(
        award["id"], scenario.fund["id"], award["version"]
    )

    refused = api.create_qei(issuance, scenario.sponsor_headers)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    unknown_award = api.create_qei(
        create_qei_payload(
            UNKNOWN_AWARD_ID, scenario.fund["id"], award["version"]
        ),
        scenario.sponsor_headers,
    )
    validate_error(
        unknown_award,
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    qei = validate_success(
        api.create_qei(issuance, scenario.cde_headers), 201
    )
    assert qei["deployment_status"] == "ISSUED"
    assert_cents(qei["uninvested_cash_cents"], 95_000_000, "uninvested_cash_cents")

    own_business = api.create_qlici(
        create_qlici_payload(qei["id"], scenario.qalicb["id"]),
        scenario.sponsor_headers,
    )
    validate_error(own_business, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    after = read_qei(api, qei["id"])
    assert after["deployment_status"] == "ISSUED"
    assert_cents(
        after["uninvested_cash_cents"], 95_000_000, "uninvested_cash_cents"
    )


UNKNOWN_CDE_ID = "00000000-0000-4000-8000-0000000000e1"
UNDECLARED_ROLE = "Auditor"


def test_a_malformed_identity_is_never_a_forbidden_and_never_a_not_found(api):
    """Three broken identities, one answer, and it outranks the missing row.

    PRD: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the capacity in
    which it acts."

    PRD: "If either header is absent or empty, or if `X-User-Role` is not one of
    the five role names below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD: "`X-User-ID` and `X-User-Role` are both present and non-empty, on every
    operation — otherwise `ERR_UNAUTHENTICATED`."

    PRD: "`X-User-Role` names one of the five declared roles, on every operation
    — otherwise `ERR_UNAUTHENTICATED`."

    PRD: "Every path identifier resolves, left to right, on every operation that
    has one — otherwise the matching not-found code."

    Design: Corner/rbac/missing_or_unknown_identity_headers_return_unauthenticated
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    cde = create_cde(
        api, certification_number="CDE-2869-129", service_area_scope="STATEWIDE"
    )
    valid = make_agency_headers()

    baseline = validate_success(api.get_cde(cde["id"], valid))
    assert baseline["certification_status"] == "CERTIFIED"
    assert baseline["service_area_scope"] == "STATEWIDE"

    role_omitted = {
        name: value for name, value in valid.items() if name != "X-User-Role"
    }
    validate_error(
        api.get_cde(cde["id"], role_omitted),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    empty_user_id = dict(valid)
    empty_user_id["X-User-ID"] = ""
    validate_error(
        api.get_cde(cde["id"], empty_user_id),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    undeclared_role = make_headers(AGENCY_USER_ID, UNDECLARED_ROLE)
    validate_error(
        api.get_cde(cde["id"], undeclared_role),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    validate_error(
        api.get_cde(UNKNOWN_CDE_ID, valid),
        ApiErrorId.ERR_CDE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_cde(UNKNOWN_CDE_ID, role_omitted),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    _, meta = validate_paginated(api.list_cdes(valid))
    assert meta["total_count"] == 1, "no refused read created or removed anything"


VOID_REASON = {"void_reason": "Filed by an entity that does not own the award"}


def test_the_other_entitys_sponsor_may_read_the_award_but_never_write_it(api):
    """Correct role, wrong owner — and the investment inherits the refusal.

    PRD: "When `X-User-Role` is `CDESponsor`, `X-User-ID` is the `id` of the
    acting `CDE`; ownership checks on any resource that references a `CDE`
    compare the resource's foreign-key field to `X-User-ID`."

    PRD: "Ownership reaches through an allocation award's `cde_id`, and
    transitively from a qualified equity investment through its award to that
    award's CDE, and from a sub-allocation through its investment and award to
    that same CDE."

    PRD: "An acting `CDESponsor` that is not the owning CDE of the target chain
    is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD: "The acting user owns the target resource, on every write acted on by a
    `CDESponsor`, a `TaxCreditInvestor` or a `QALICBSponsor` — otherwise
    `ERR_NOT_RESOURCE_OWNER`."

    PRD: "Every read operation under `/nmtc` — every single-resource read and
    every list — is available to all five roles."

    PRD: "The `CDESponsor` supplies a single `report_year`, and the server
    answers with a snapshot: the `allocation_award_id` reported on, the
    `report_year`, `issued_qei_count` as the count of the award's investments
    whose `deployment_status` is anything other than `VOIDED`,
    `deployed_principal_cents` as the sum of `outstanding_principal_cents` over
    the sub-allocations of those investments whose `status` is `DEPLOYED` or
    `PARTIALLY_REPAID`, `qualifying_qalicb_count` as the number of *distinct*
    project companies funded by those same sub-allocations, the freshly
    recomputed `severe_distress_share_pct`, a `severe_distress_shortfall` flag
    that is true exactly when that share sits strictly below the award's
    `min_severe_distress_share_pct`, and the award's derived `at_risk_qei_count`,
    `recaptured_qei_count` and `cba_breach_count` copied across."

    Design: Corner/rbac/a_cde_sponsor_cannot_act_on_another_cdes_award
    """
    scenario = setup_two_entities(
        api, clock=SETUP_CLOCK, first_suffix=130, second_suffix=131
    )
    other_cde = scenario.extras["other_cde"]
    setup_funded_fund(api, scenario)
    scenario.award = read_award(api, scenario.award["id"])
    qei = issue_qei(api, scenario.cde, scenario.award, scenario.fund)

    stranger = make_cde_sponsor_headers(other_cde["id"])

    foreign_report = api.file_agency_report(
        scenario.award["id"], agency_report_payload(2026), stranger
    )
    validate_error(foreign_report, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    foreign_void = api.void_qei(
        qei["id"], void_qei_payload(**VOID_REASON), stranger
    )
    validate_error(foreign_void, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    shared_read = validate_success(
        api.get_allocation_award(scenario.award["id"], stranger)
    )
    assert shared_read["id"] == scenario.award["id"]
    assert shared_read["cde_id"] == scenario.cde["id"]

    owned_report = get_success_data(
        api.file_agency_report(
            scenario.award["id"], agency_report_payload(2026), scenario.cde_headers
        )
    )
    assert owned_report["issued_qei_count"] == 1
    assert_cents(
        owned_report["deployed_principal_cents"], 0, "deployed_principal_cents"
    )
    assert owned_report["qualifying_qalicb_count"] == 0

    assert read_qei(api, qei["id"])["deployment_status"] == "ISSUED"
    award = read_award(api, scenario.award["id"])
    assert award["issued_qei_count"] == 1
    assert award["last_agency_report_year"] == 2026


YEAR_ONE_WINDOW_END = "2027-09-01T00:00:00.000Z"
UNREACHED_YEAR = 2


def test_the_reviewer_who_certified_the_business_may_not_measure_the_money(api):
    """Same role, different identifier — and duties answer before the calendar.

    PRD: "The `ComplianceReviewer` user id recorded on the most recent
    eligibility test of any project company funded by a given qualified equity
    investment is barred from running that investment's annual compliance test."

    PRD: "Such an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403)."

    PRD: "Segregation of duties holds on an annual compliance test — otherwise
    `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "Years may not be skipped: the requested year must be no greater than
    the investment's `compliance_years_completed` plus one, and a request for a
    later year than the next one due is `ERR_TEST_SEQUENCE_INVALID`."

    PRD: "Rules are evaluated in ascending priority, the first violated rule
    alone decides the response, and a rejected request persists nothing at all —
    no partial cascade, no counter movement, no version increment."

    PRD: "The server records it — as `performed_by_user_id` on each eligibility
    test and on each annual compliance test — but never compares it to any
    entity's `id`."

    PRD: "The test copies the award's `substantially_all_method` into its own
    `governing_method`, and sets `governing_pct` to `measured_pct_direct` when
    that method is `DIRECT_TRACING` and to `measured_pct_aggregate` when it is
    `AGGREGATE_BALANCE`."

    PRD: "The `result` is `PASS` when the `governing_pct` is at least 85.00 *and*
    the test's `breached_obligation_count` is 0; otherwise it is `FAIL`."

    PRD: "That counter simply counts the annual test rows recorded against the
    investment, whether they passed or failed."

    Design: Corner/rbac/the_eligibility_reviewer_may_not_run_the_annual_test_of_a_qei_funding_that_business
    """
    scenario = setup_deployed_investment(
        api, clock=SETUP_CLOCK, certification_suffix=132
    )
    assert (
        scenario.eligibility_test["performed_by_user_id"]
        == REVIEWER_ELIGIBILITY_USER_ID
    )
    set_clock(api, YEAR_ONE_WINDOW_END)

    barred = make_reviewer_headers(REVIEWER_ELIGIBILITY_USER_ID)
    refused = api.run_annual_test(
        scenario.qei["id"], annual_test_payload(1), barred
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    out_of_sequence = api.run_annual_test(
        scenario.qei["id"], annual_test_payload(UNREACHED_YEAR), barred
    )
    validate_error(
        out_of_sequence, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403
    )

    passed = get_success_data(
        api.run_annual_test(
            scenario.qei["id"],
            annual_test_payload(1),
            make_reviewer_headers(REVIEWER_ANNUAL_USER_ID),
        )
    )
    assert passed["performed_by_user_id"] == REVIEWER_ANNUAL_USER_ID
    assert passed["compliance_year"] == 1
    assert passed["governing_method"] == "DIRECT_TRACING"
    assert_pct(passed["governing_pct"], 89.47, "governing_pct")
    assert passed["result"] == "PASS"

    _, meta = validate_paginated(
        api.list_annual_tests(scenario.qei["id"], make_agency_headers())
    )
    assert meta["total_count"] == 1, "the two refusals recorded no test row"
    assert read_qei(api, scenario.qei["id"])["compliance_years_completed"] == 1
