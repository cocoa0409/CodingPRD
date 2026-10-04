"""Partner colleges, agreements, mentors and renewal review (PRD §2.6, §3.3,
§3.4, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_agreement,
    api_client,
    assert_cohort,
    assert_partner_agreement,
    assert_partner_college,
    create_cohort_payload,
    create_mentor,
    create_partner_agreement_payload,
    draft_agreement,
    get_college,
    renewal_review,
    setup_city_program,
    setup_cohort_foundation,
    setup_college,
    setup_completed_cohort_all_graduated,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]


class TestAgreementDrafting:
    def test_cohort_size_outside_bounds_rejected(self, api):
        """PRD §3.3: "The `cohort_size` must be at least 3 and at most 6
        inclusive; a size outside that range is rejected with
        `ERR_COHORT_SIZE_INVALID` — deliberately a business-rule rejection at
        tier 10 rather than a shape error."

        Design: Corner/validations/cohort_size_outside_bounds_rejected
        """
        college = setup_college()
        version = college["version"]
        resp2 = api.create_partner_agreement(
            create_partner_agreement_payload(college["id"], version, cohort_size=2), _ADMIN
        )
        validate_error(resp2, ApiErrorId.ERR_COHORT_SIZE_INVALID)
        resp7 = api.create_partner_agreement(
            create_partner_agreement_payload(college["id"], version, cohort_size=7), _ADMIN
        )
        validate_error(resp7, ApiErrorId.ERR_COHORT_SIZE_INVALID)
        # The rejections consumed no version: the same observed version still
        # drafts successfully at the inclusive upper bound (PRD §2.6:
        # "Successfully drafting an agreement itself increments the college's
        # `version` by exactly 1").
        ok = api.create_partner_agreement(
            create_partner_agreement_payload(college["id"], version, cohort_size=6), _ADMIN
        )
        data = validate_success(ok, 201)
        assert_partner_agreement(data)
        assert data["cohort_size"] == 6

    def test_new_agreement_supersedes_existing_draft(self, api):
        """PRD §3.3: "Drafting an agreement for a college and admissions cycle
        that already has a `DRAFT` agreement supersedes the older draft: the
        existing agreement moves from `DRAFT` to `SUPERSEDED`."
        PRD §2.6: "Successfully drafting an agreement itself increments the
        college's `version` by exactly 1."

        Design: Corner/endpoints/new_agreement_supersedes_existing_draft
        """
        college = setup_college()
        v1 = college["version"]
        aga = draft_agreement(college, cohort_size=3, expected_college_version=v1)
        v2 = get_college(college["id"])["version"]
        assert v2 == v1 + 1, "first successful draft bumps the college version by exactly 1"

        agb = draft_agreement(college, cohort_size=4, expected_college_version=v2)
        assert agb["status"] == "DRAFT"
        v3 = get_college(college["id"])["version"]
        assert v3 == v2 + 1, "second successful draft bumps it again"

        agreements, meta = validate_paginated(
            api.list_college_agreements(college["id"], _ADMIN)
        )
        assert meta["total_count"] == 2
        # List order is created_at ascending (PRD §2.3).
        by_id = {a["id"]: a for a in agreements}
        assert by_id[aga["id"]]["status"] == "SUPERSEDED"
        assert by_id[agb["id"]]["status"] == "DRAFT"

    def test_agreement_create_stale_college_version_rejected(self, api):
        """PRD §2.6: "If the supplied value does not equal the college's
        current `version` — meaning another writer has advanced the college's
        version since the client last read it ... the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), forcing the client to refresh its view
        of the college before terms are drafted."

        Design: Corner/cross_cutting_layers/agreement_create_stale_college_version_rejected
        """
        college = setup_college()
        v1 = college["version"]
        aga = draft_agreement(college, expected_college_version=v1)
        stale = api.create_partner_agreement(
            create_partner_agreement_payload(
                college["id"], v1, admissions_cycle="2028"
            ),
            _ADMIN,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        agreements, meta = validate_paginated(
            api.list_college_agreements(college["id"], _ADMIN)
        )
        assert meta["total_count"] == 1
        assert agreements[0]["id"] == aga["id"], "the stale draft created nothing"


class TestAgreementActivation:
    def test_second_active_agreement_same_cycle_rejected(self, api):
        """PRD §3.3: "And no other `ACTIVE` agreement may exist for the same
        college and admissions cycle — otherwise the activation is rejected
        with `ERR_ACTIVE_AGREEMENT_EXISTS`."

        Design: Corner/validations/second_active_agreement_same_cycle_rejected
        """
        college = setup_college()
        aga = draft_agreement(college, cohort_size=3)
        activate_agreement(aga["id"])
        agb = draft_agreement(college, cohort_size=4)
        resp = api.activate_agreement(agb["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_AGREEMENT_EXISTS)
        agreements, _ = validate_paginated(api.list_college_agreements(college["id"], _ADMIN))
        by_id = {a["id"]: a for a in agreements}
        assert by_id[aga["id"]]["status"] == "ACTIVE", (
            "supersede touches only DRAFTs, so the ACTIVE agreement survived"
        )
        assert by_id[agb["id"]]["status"] == "DRAFT"


class TestCohortCreationGates:
    def test_cohort_create_with_draft_agreement_rejected(self, api):
        """PRD §3.4: "The agreement must be `ACTIVE`; creating against a
        `DRAFT`, `SUPERSEDED`, `FULFILLED`, or `EXPIRED` agreement is rejected
        with `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Corner/validations/cohort_create_with_draft_agreement_rejected
        """
        program = setup_city_program()
        college = setup_college()
        agreement = draft_agreement(college, cohort_size=3)  # never activated
        mentor = create_mentor(college["id"])
        resp = api.create_cohort(
            create_cohort_payload(agreement["id"], program["id"], mentor["id"]), _ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        cohorts, meta = validate_paginated(
            api.list_cohorts(_ADMIN, params={"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 0 and cohorts == []

    def test_second_cohort_for_same_agreement_rejected(self, api):
        """PRD §3.4: "At most one cohort may exist per agreement; a second
        attempt is rejected with `ERR_COHORT_EXISTS`."

        Design: Corner/validations/second_cohort_for_same_agreement_rejected
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        resp = api.create_cohort(
            create_cohort_payload(
                ctx["agreement"]["id"], ctx["program"]["id"], ctx["mentor"]["id"]
            ),
            _ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_COHORT_EXISTS)
        cohorts, meta = validate_paginated(
            api.list_cohorts(_ADMIN, params={"agreement_id": ctx["agreement"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_mentor_from_other_college_rejected_at_cohort_create(self, api):
        """PRD §3.4: "And the mentor must belong to the agreement's college: a
        `mentor_id` naming a mentor whose `partner_college_id` differs from the
        agreement's is rejected with `ERR_MENTOR_COLLEGE_MISMATCH`."

        Design: Corner/validations/mentor_from_other_college_rejected_at_cohort_create
        """
        program = setup_city_program()
        college_x = setup_college("Elm College X")
        college_y = setup_college("Elm College Y")
        mentor_x = create_mentor(college_x["id"], full_name="Prof X")
        agreement_y = draft_agreement(college_y, cohort_size=3)
        activate_agreement(agreement_y["id"])
        resp = api.create_cohort(
            create_cohort_payload(agreement_y["id"], program["id"], mentor_x["id"]), _ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_MENTOR_COLLEGE_MISMATCH)
        cohorts, meta = validate_paginated(
            api.list_cohorts(_ADMIN, params={"agreement_id": agreement_y["id"]})
        )
        assert meta["total_count"] == 0


class TestRenewalReview:
    def test_renewal_renew_gate_null_then_lapse_is_terminal(self, api):
        """PRD §3.9: "A `RENEW` decision is threshold-gated on the census
        variant: it requires census retention of at least 8000 basis points and
        census graduation of at least 6000 basis points, and failing either
        threshold — including a null rate, which always fails the gate — is
        rejected with `ERR_RENEWAL_THRESHOLDS_NOT_MET`."
        PRD §3.9: "A `LAPSE` decision is terminal: the college moves to
        `LAPSED`, every `DRAFT` agreement of the college expires to `EXPIRED`,
        and both agreement creation and agreement activation against the
        college are blocked from then on with `ERR_COLLEGE_NOT_ACTIVE`."

        Design: Corner/state_machines/renewal_renew_gate_null_then_lapse_is_terminal
        """
        college = setup_college()
        agreement = draft_agreement(college, cohort_size=3)

        resp_renew = api.renewal_review(college["id"], {"decision": "RENEW"}, _ADMIN)
        validate_error(resp_renew, ApiErrorId.ERR_RENEWAL_THRESHOLDS_NOT_MET)

        resp_lapse = api.renewal_review(college["id"], {"decision": "LAPSE"}, _ADMIN)
        lapsed = validate_success(resp_lapse)
        assert lapsed["status"] == "LAPSED"
        assert lapsed["renewed_cycles_count"] == 0

        agreements, _ = validate_paginated(api.list_college_agreements(college["id"], _ADMIN))
        assert agreements[0]["id"] == agreement["id"]
        assert agreements[0]["status"] == "EXPIRED", "the DRAFT agreement expired on lapse"

        resp_renew2 = api.renewal_review(college["id"], {"decision": "RENEW"}, _ADMIN)
        validate_error(resp_renew2, ApiErrorId.ERR_INVALID_STATE)

        fresh_version = get_college(college["id"])["version"]
        resp_draft = api.create_partner_agreement(
            create_partner_agreement_payload(
                college["id"], fresh_version, admissions_cycle="2028"
            ),
            _ADMIN,
        )
        validate_error(resp_draft, ApiErrorId.ERR_COLLEGE_NOT_ACTIVE)

    def test_renewal_renew_succeeds_on_strong_census(self, api):
        """PRD §3.9: "A successful renewal increments the college's
        `renewed_cycles_count` by one and the college becomes, or stays,
        `ACTIVE`."
        PRD §3.7: "when the count of the cohort's scholars whose
        `enrollment_status` is non-terminal reaches zero — meaning every
        scholar is `GRADUATED`, `WITHDRAWN`, or `DISMISSED` — the cohort moves
        from `MATRICULATED` to `COMPLETED`, its agreement moves from `ACTIVE`
        to `FULFILLED`, and the partner college's census outcome rates are
        recomputed".

        Design: Corner/endpoints/renewal_renew_succeeds_on_strong_census
        """
        ctx = setup_completed_cohort_all_graduated()
        college = ctx["college"]

        outcomes = validate_success(api.get_college_outcomes(college["id"], _ADMIN))
        assert outcomes["retention_bps_census"] == 10000, "3 of 3 RETAINED-or-GRADUATED"
        assert outcomes["graduation_bps_census"] == 10000, "3 of 3 GRADUATED"
        assert outcomes["college_status"] == "ACTIVE", (
            "a 3/3 cohort never trips the 7000 probation floor"
        )
        assert ctx["cohort_after"]["status"] == "COMPLETED", (
            "the cohort auto-completed after the third graduation"
        )
        agreements, _ = validate_paginated(
            api.list_college_agreements(
                college["id"], _ADMIN, params={"status": "FULFILLED"}
            )
        )
        assert any(a["id"] == ctx["agreement"]["id"] for a in agreements), (
            "the cohort's agreement is FULFILLED"
        )

        renewed = renewal_review(college["id"], "RENEW")
        assert renewed["status"] == "ACTIVE"
        assert renewed["renewed_cycles_count"] == 1
