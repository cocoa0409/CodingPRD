"""Who may act: role lists, and the duty wall that role authority cannot climb.

Two of these probe the authorization rung — the refusals a wrong role collects and
the successes the right roles are owed, including two operations that are shared
between two roles rather than owned by one. The other two probe the layer above it,
where the role is correct and the acting user is the wrong human.
"""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ACTUARY_1,
    ADMIN_1,
    ANALYST_1,
    ANALYST_2,
    BILLING_1,
    COMPLIANCE_1,
    COUNSELOR_1,
    COUNSELOR_2,
    make_actuary_headers,
    make_benefits_admin_headers,
    make_billing_clerk_headers,
    make_compliance_officer_headers,
    make_eligibility_analyst_headers,
    make_enrollment_counselor_headers,
    make_retiree_headers,
)


def test_no_role_may_reach_past_its_own_endpoint_list(api):
    """Six operations refused for the same reason, and one read that is not.

    PRD 2.8 rung 2 is the whole of it: "Authorization — the caller's role appears
    in the target endpoint's role list → `ERR_UNAUTHORIZED` (403), on every
    endpoint." The lists it consults are the ones PRD 4 publishes, and they are
    narrow: "Register a plan year in DRAFT with its HRA credit schedule, billing
    calendar parameters and actuarial assumptions. | `BenefitsAdmin`", "Record the
    actuary's attested prescription-drug values and run the actuarial equivalence
    gross and net tests. | `Actuary`", "Compliance decision on the retiree drug
    subsidy (RDS) or employer group waiver plan (EGWP) election for an already
    attested option. | `ComplianceOfficer`", "Certify a DRAFT determination so it
    can gate elections, HRA funding and liability valuation. |
    `EligibilityAnalyst`, `ComplianceOfficer`", "Run the retiree-medical
    eligibility rules for one retiree and plan year and record a DRAFT
    determination. Guarded by optimistic concurrency on the retiree. |
    `EligibilityAnalyst`" and "List retirees with filtering and pagination. | All
    roles except `Retiree`". The `BenefitsAdmin` that owns the catalogue is
    therefore no more entitled to attest than the `Retiree` is to register a plan
    year, and a role that is merely permitted to certify determinations gains
    nothing on the subsidy path. Because PRD 2.8 makes the ladder total — "When a
    single request violates more than one rule, the rule that appears earliest in
    the following ladder produces the response, and no later rule is evaluated or
    reported." — the un-attested option's state never enters the answer. The
    `Retiree` is not blocked outright, though: PRD 4 opens the by-id read to "Read
    one retiree including its derived grandfathered_group and eligibility_points.
    | All roles". No refused call may leave a trace, PRD 2.4 having tied any trace
    to a counter that "increases by exactly 1 on every mutation of that row".

    Design: Corner/rbac/role_cannot_perform_another_roles_exclusive_operation_unauthorized
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    option = fx.make_med_wrap(
        api, plan_year["id"], activate=False, attest=False, certify=False
    )
    assert option["subsidy_certification_status"] == "NOT_STARTED"

    retiree = fx.make_retiree(api, f.retiree_r1_payload())
    determination = fx.make_determination(
        api, retiree, plan_year["id"], certify=False, creator_user_id=ANALYST_1
    )
    assert determination["status"] == "DRAFT"

    retiree_headers = make_retiree_headers(retiree["id"])

    refused_plan_year = validate_error(
        api.create_plan_year(
            f.plan_year_payload(
                2028,
                overrides={
                    "open_enrollment_start": "2027-10-15T00:00:00Z",
                    "open_enrollment_end": "2027-11-15T00:00:00Z",
                    "coverage_start": "2028-01-01T00:00:00Z",
                },
            ),
            retiree_headers,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )
    assert refused_plan_year["error_id"] == ApiErrorId.ERR_UNAUTHORIZED.value

    refused_certify = validate_error(
        api.certify_determination(
            determination["id"], make_billing_clerk_headers(BILLING_1)
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )
    assert refused_certify["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value

    validate_error(
        api.attest_plan_option(
            option["id"], f.attest_payload(), make_benefits_admin_headers(ADMIN_1)
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )

    refused_subsidy = validate_error(
        api.certify_subsidy(
            option["id"],
            f.subsidy_certification_payload("CERTIFY"),
            make_eligibility_analyst_headers(ANALYST_1),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )
    assert refused_subsidy["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

    validate_error(
        api.create_determination(
            f.determination_payload(
                retiree["id"], plan_year["id"], retiree["version"]
            ),
            make_enrollment_counselor_headers(COUNSELOR_1),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )

    validate_error(
        api.list_retirees(retiree_headers, {"limit": 10, "offset": 0}),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )

    own_record = validate_success(api.get_retiree(retiree["id"], retiree_headers))
    assert own_record["id"] == retiree["id"]
    assert own_record["grandfathered_group"] == "GRANDFATHERED_A"

    years, years_meta = validate_paginated(
        api.list_plan_years(make_benefits_admin_headers(ADMIN_1))
    )
    assert years_meta["total_count"] == 1
    assert [row["year"] for row in years] == [2027]

    untouched_determination = fx.reload_determination(api, determination["id"])
    assert untouched_determination["status"] == "DRAFT"
    assert untouched_determination["certified_by_user_id"] is None
    assert untouched_determination["version"] == determination["version"]

    untouched_option = fx.reload_plan_option(api, option["id"])
    assert untouched_option["subsidy_certification_status"] == "NOT_STARTED"
    # PRD 3.2: the Actuary's attested values "overwrite whatever the option
    # carried before", so a refused attest leaves the option carrying exactly the
    # rx_gross_value_bps it was created with (PRD 3.1) - not zero.
    assert untouched_option["rx_gross_value_bps"] == option["rx_gross_value_bps"]
    assert untouched_option["attested_by_user_id"] is None
    assert untouched_option["version"] == option["version"]


def test_the_roles_that_own_an_operation_and_the_two_that_share_one(api):
    """The actuary's exclusive attest, then the same review-and-decide pair driven
    by each of the two roles entitled to it.

    PRD 4 gives attestation a single owner — "Record the actuary's attested
    prescription-drug values and run the actuarial equivalence gross and net tests.
    | `Actuary`" — and adjudication two: "Take a SUBMITTED election into
    enrollment-support review. | `EnrollmentCounselor`, `BenefitsAdmin`" and
    "Approve or deny an election under review. APPROVE materialises the Enrollment;
    DENY records a denial reason code. | `EnrollmentCounselor`, `BenefitsAdmin`".
    PRD 3.5 says the same in prose, "An `EnrollmentCounselor` or a `BenefitsAdmin`
    first takes a `SUBMITTED` election into review, which requires the plan year to
    still be `OPEN`, moves `status` to `UNDER_REVIEW`, and records
    `reviewed_by_user_id` as the acting user's `X-User-ID`.", so a shared operation
    implemented as single-role would refuse one of these two paths. What the attest
    writes is fixed by PRD 3.2: "A successful attestation writes
    `gross_test_passed`, `net_test_passed` and `equivalence_margin_bps`, records
    `attested_by_user_id` as the acting `Actuary`'s `X-User-ID`, and moves
    `subsidy_certification_status` to `ATTESTED`." with "`equivalence_margin_bps`
    records the attested net value minus the 7450-basis-point benchmark, and may
    therefore be negative." — 7800 less 7450 is 350. Each approval then pays out
    once, PRD 3.5: "A surviving approval moves `status` from `UNDER_REVIEW` to
    `APPROVED` and materialises exactly one enrollment.", with "`coverage_status`
    is `ACTIVE` when the logical clock has already reached that
    `coverage_effective_date` and `PENDING` when it has not" and "The requested
    option's `enrolled_count` increments by 1".

    Design: Corner/rbac/authorized_roles_perform_their_exclusive_and_shared_operations
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    pre65_core = fx.make_pre65_core(api, plan_year["id"])
    med_wrap = fx.make_med_wrap(
        api, plan_year["id"], activate=False, attest=False, certify=False
    )
    assert pre65_core["status"] == "ACTIVE"
    assert med_wrap["subsidy_certification_status"] == "NOT_STARTED"

    first_retiree = fx.make_retiree(api, f.retiree_r1_payload())
    first_draft = fx.make_determination(
        api, first_retiree, plan_year["id"], certify=False, creator_user_id=ANALYST_1
    )
    first_determination = validate_success(
        api.certify_determination(
            first_draft["id"], make_compliance_officer_headers(COMPLIANCE_1)
        )
    )
    assert first_determination["status"] == "CERTIFIED"
    assert first_determination["outcome"] == "ELIGIBLE"

    second = fx.make_certified_retiree(
        api,
        plan_year["id"],
        f.retiree_r5_payload(),
        creator_user_id=ANALYST_1,
        certifier_user_id=ANALYST_2,
    )
    assert second["determination"]["certified_by_user_id"] == ANALYST_2
    assert second["determination"]["outcome"] == "ELIGIBLE"

    first_election = fx.make_election_event(
        api,
        first_retiree["id"],
        plan_year["id"],
        pre65_core["id"],
        creator_user_id=COUNSELOR_1,
    )
    second_election = fx.make_election_event(
        api,
        second["retiree"]["id"],
        plan_year["id"],
        pre65_core["id"],
        creator_user_id=COUNSELOR_1,
    )
    assert first_election["status"] == "SUBMITTED"
    assert second_election["status"] == "SUBMITTED"

    attested = validate_success(
        api.attest_plan_option(
            med_wrap["id"],
            f.attest_payload(rx_gross_value_bps=10500, rx_net_value_bps=7800),
            make_actuary_headers(ACTUARY_1),
        )
    )
    assert attested["subsidy_certification_status"] == "ATTESTED"
    assert attested["attested_by_user_id"] == ACTUARY_1
    assert attested["rx_gross_value_bps"] == 10500
    assert attested["rx_net_value_bps"] == 7800
    assert attested["equivalence_margin_bps"] == 350
    assert attested["gross_test_passed"] is True
    assert attested["net_test_passed"] is True

    counselor_review = validate_success(
        api.review_election_event(
            first_election["id"], make_enrollment_counselor_headers(COUNSELOR_2)
        )
    )
    assert counselor_review["status"] == "UNDER_REVIEW"
    counselor_decision = validate_success(
        api.decide_election_event(
            first_election["id"],
            f.election_decision_payload("APPROVE"),
            make_enrollment_counselor_headers(COUNSELOR_2),
        )
    )
    assert counselor_decision["status"] == "APPROVED"
    assert counselor_decision["reviewed_by_user_id"] == COUNSELOR_2

    admin_review = validate_success(
        api.review_election_event(
            second_election["id"], make_benefits_admin_headers(ADMIN_1)
        )
    )
    assert admin_review["status"] == "UNDER_REVIEW"
    admin_decision = validate_success(
        api.decide_election_event(
            second_election["id"],
            f.election_decision_payload("APPROVE"),
            make_benefits_admin_headers(ADMIN_1),
        )
    )
    assert admin_decision["status"] == "APPROVED"
    assert admin_decision["reviewed_by_user_id"] == ADMIN_1

    assert fx.reload_plan_option(api, pre65_core["id"])["enrolled_count"] == 2

    for decision in (counselor_decision, admin_decision):
        enrollment = fx.reload_enrollment(api, decision["resulting_enrollment_id"])
        assert enrollment["coverage_status"] == "PENDING"
        assert enrollment["plan_option_id"] == pre65_core["id"]


def test_the_analyst_who_ran_a_determination_may_not_certify_it(api):
    """A permitted role, the wrong human; then the same role, a different human.

    PRD 2.7 states the wall and the comparison it makes: "the acting `X-User-ID` is
    compared against the operator identifier already recorded on the target record,
    and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)", the first
    of its six pairings being "Certifying an eligibility determination is compared
    against that determination's `created_by_user_id`." PRD 3.4 repeats it on the
    certify path, which "requires the acting `X-User-ID` to differ from the
    determination's `created_by_user_id`, a match being refused with
    `ERR_SEGREGATION_OF_DUTIES`", and says what the accepted call writes: "On
    success the determination records `certified_by_user_id` as the certifying
    user's `X-User-ID` and `certified_at` at the logical clock". The refusal cannot
    be an authorization failure, because PRD 4 lists the acting role among the
    permitted ones — "Certify a DRAFT determination so it can gate elections, HRA
    funding and liability valuation. | `EligibilityAnalyst`, `ComplianceOfficer`" —
    so the only difference between the refused call and the accepted one is the user
    id. The refused call writes nothing, PRD 2.4 having tied every write to a
    counter that "increases by exactly 1 on every mutation of that row".

    Design: Corner/rbac/same_user_cannot_certify_the_determination_they_created
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    retiree = fx.make_retiree(api, f.retiree_r1_payload())
    determination = fx.make_determination(
        api, retiree, plan_year["id"], certify=False, creator_user_id=ANALYST_1
    )
    assert determination["created_by_user_id"] == ANALYST_1
    assert determination["status"] == "DRAFT"

    refused = validate_error(
        api.certify_determination(
            determination["id"], make_eligibility_analyst_headers(ANALYST_1)
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )
    assert refused["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

    still_draft = fx.reload_determination(api, determination["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["certified_by_user_id"] is None
    assert still_draft["version"] == determination["version"]

    certified = validate_success(
        api.certify_determination(
            determination["id"], make_eligibility_analyst_headers(ANALYST_2)
        )
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == ANALYST_2
    assert certified["created_by_user_id"] == ANALYST_1


def test_the_actuary_who_attested_may_not_certify_under_a_compliance_header(api):
    """One user id wearing both hats is refused; a second officer is not.

    PRD 2.7 pairs the two halves of the actuarial control — "Certifying or
    rejecting a plan option's subsidy election is compared against that option's
    `attested_by_user_id`." — and states the structural version of the same rule:
    "an `Actuary` attests actuarial equivalence but may never certify it". PRD 3.2
    puts it on the endpoint: "The acting officer's `X-User-ID` must differ from the
    option's `attested_by_user_id`; if the actuary who attested the values comes
    back wearing the compliance hat, the decision is refused with
    `ERR_SEGREGATION_OF_DUTIES`." A refusal on state is ruled out by the fact that
    the very next call succeeds, and by what PRD 3.2 says that call does: "Both
    branches record `certified_by_user_id` as the acting officer's `X-User-ID` and
    increment the option's `version`; `CERTIFY` moves
    `subsidy_certification_status` from `ATTESTED` to `CERTIFIED`", while "Neither
    branch touches the option's availability `status`, its premium, or its attested
    values." — so the 350-basis-point margin the attestation computed against the
    7450 floor survives the certification untouched.

    Design: Corner/rbac/same_user_cannot_certify_the_subsidy_they_attested
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    option = fx.make_med_wrap(
        api, plan_year["id"], activate=False, attest=True, certify=False
    )
    assert option["subsidy_certification_status"] == "ATTESTED"
    assert option["attested_by_user_id"] == ACTUARY_1
    assert option["equivalence_margin_bps"] == 350

    refused = validate_error(
        api.certify_subsidy(
            option["id"],
            f.subsidy_certification_payload("CERTIFY"),
            make_compliance_officer_headers(ACTUARY_1),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        expected_status=403,
    )
    assert refused["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

    still_attested = fx.reload_plan_option(api, option["id"])
    assert still_attested["subsidy_certification_status"] == "ATTESTED"
    assert still_attested["certified_by_user_id"] is None
    assert still_attested["version"] == option["version"]

    certified = validate_success(
        api.certify_subsidy(
            option["id"],
            f.subsidy_certification_payload("CERTIFY"),
            make_compliance_officer_headers(COMPLIANCE_1),
        )
    )
    assert certified["subsidy_certification_status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == COMPLIANCE_1
    assert certified["attested_by_user_id"] == ACTUARY_1
    assert certified["equivalence_margin_bps"] == 350
