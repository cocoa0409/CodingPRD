"""Application lifecycle: creation defaults, tiered net-worth requirement,
revision cycle, threshold gates at submit."""
from test_helpers import (
    TEST_USERS,
    assert_issuer,
    assert_issuer_application,
    create_application_payload,
    create_draft_application,
    get_success_data,
    make_agency_reviewer_headers,
    make_applicant_officer_headers,
    review_application,
    setup_approved_issuer,
    submit_application,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestApplicationCreation:
    def test_create_returns_defaults_and_computed_requirement(self, api):
        """PRD §3.1: "unused_credit_lines_cents may be supplied and defaults to
        zero when omitted." PRD §3.1: "The requirement is the larger of two
        components — a branch component of two hundred fifty million cents
        (two and a half million dollars) plus twenty-five million cents (two
        hundred fifty thousand dollars) for each branch beyond the first, and
        a volume component equal to the applicant's prior-year origination
        volume multiplied by ten basis points (one tenth of one percent) and
        floored to integer cents."

        Design: Corner/entities/application_create_returns_defaults_and_computed_requirement
        """
        headers = make_applicant_officer_headers("officer-dc")
        resp = api.create_application(
            create_application_payload(
                legal_name="Default Check Lending",
                net_worth_cents=400000000,
                liquid_assets_cents=5000000,
                origination_experience_months=36,
                branch_count=2,
                annual_origination_volume_cents=1000000000,
            ),
            headers,
        )
        app = validate_success(resp, expected_status=201)
        assert_issuer_application(app)
        assert app["status"] == "DRAFT"
        assert app["version"] == 1
        assert app["unused_credit_lines_cents"] == 0
        # branch tier: 250000000 + (2-1)*25000000 = 275000000;
        # volume tier: floor(1000000000*10/10000) = 100000000 -> branch binds
        assert app["net_worth_requirement_cents"] == 275000000


class TestNetWorthRequirementTiers:
    def test_branch_tier_binds_when_branch_component_dominates(self, api):
        """PRD §3.1: "When the branch component dominates, the requirement is
        the base plus the per-branch add-on; when the volume component
        dominates, the requirement is the floored volume share — floor, not
        round."

        Design: Difficulty/combinatorial_formula/net_worth_requirement_branch_vs_volume_tiers
        """
        app = create_draft_application(
            "officer-a",
            legal_name="Three Branch Bank",
            net_worth_cents=400000000,
            liquid_assets_cents=5000000,
            origination_experience_months=36,
            branch_count=3,
            annual_origination_volume_cents=2500000000,
        )
        # branch: 250000000 + 2*25000000 = 300000000; volume: 250000000
        assert app["net_worth_requirement_cents"] == 300000000

    def test_volume_tier_binds_when_volume_component_dominates(self, api):
        """PRD §3.1: "When the branch component dominates, the requirement is
        the base plus the per-branch add-on; when the volume component
        dominates, the requirement is the floored volume share — floor, not
        round."

        Design: Difficulty/combinatorial_formula/net_worth_requirement_branch_vs_volume_tiers
        """
        app = create_draft_application(
            "officer-b",
            legal_name="High Volume Lender",
            net_worth_cents=400000000,
            liquid_assets_cents=5000000,
            origination_experience_months=36,
            branch_count=1,
            annual_origination_volume_cents=3600000000,
        )
        # branch: 250000000; volume: floor(3600000000*10/10000) = 360000000
        assert app["net_worth_requirement_cents"] == 360000000


class TestSubmitThresholds:
    def test_twenty_three_months_experience_rejected(self, api):
        """PRD §3.1: "`origination_experience_months` must be at least 24
        (else `ERR_INSUFFICIENT_EXPERIENCE`)"

        Design: Corner/validations/submit_missing_experience_returns_insufficient_experience
        """
        app = create_draft_application(
            "officer-jr",
            legal_name="Junior Lending",
            net_worth_cents=400000000,
            liquid_assets_cents=5000000,
            origination_experience_months=23,
            branch_count=1,
            annual_origination_volume_cents=1000000000,
        )
        resp = api.submit_application(app["id"], make_applicant_officer_headers("officer-jr"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_EXPERIENCE)

    def test_twenty_four_months_experience_accepted(self, api):
        """PRD §3.1: "`origination_experience_months` must be at least 24
        (else `ERR_INSUFFICIENT_EXPERIENCE`)"

        Design: Corner/validations/submit_missing_experience_returns_insufficient_experience
        """
        app = create_draft_application(
            "officer-sr",
            legal_name="Senior Lending",
            net_worth_cents=400000000,
            liquid_assets_cents=5000000,
            origination_experience_months=24,
            branch_count=1,
            annual_origination_volume_cents=1000000000,
        )
        resp = api.submit_application(app["id"], make_applicant_officer_headers("officer-sr"))
        submitted = validate_success(resp)
        assert submitted["status"] == "SUBMITTED"

    def test_double_submit_rejected_invalid_state(self, api):
        """PRD §3.1: "An application not in `DRAFT` cannot be submitted — the
        attempt fails with `ERR_APPLICATION_INVALID_STATE`."

        Design: Corner/state_machines/application_submit_from_submitted_returns_invalid_state
        """
        app = create_draft_application(
            "officer-ts",
            legal_name="Twice Submit Lending",
            net_worth_cents=400000000,
            liquid_assets_cents=5000000,
            origination_experience_months=36,
            branch_count=1,
            annual_origination_volume_cents=1000000000,
        )
        submit_application(app["id"], "officer-ts")
        resp = api.submit_application(app["id"], make_applicant_officer_headers("officer-ts"))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
        reread = get_success_data(api.get_application(app["id"], TEST_USERS["platform_admin_headers"]))
        assert reread["status"] == "SUBMITTED"
        assert reread["version"] == 2


class TestRevisionCycle:
    def test_revision_loop_returns_to_draft_and_resubmits(self, api):
        """PRD §3.1: "A request for revision moves it to `REVISION_REQUESTED`,
        from which the applicant's next patch returns it to `DRAFT` — the
        application may loop through draft, review, and revision repeatedly."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_loop
        """
        app = create_draft_application(
            "officer-loop",
            legal_name="Loop Cycle Funding",
            net_worth_cents=400000000,
            liquid_assets_cents=9000000,
            origination_experience_months=30,
            branch_count=1,
            annual_origination_volume_cents=2000000000,
        )
        submit_application(app["id"], "officer-loop")
        review_application(app["id"], "reviewer-1")
        rev = get_success_data(api.request_revision(app["id"], make_agency_reviewer_headers("reviewer-1")))
        assert rev["status"] == "REVISION_REQUESTED"
        patched = get_success_data(api.patch_application(
            app["id"],
            {"expected_application_version": rev["version"], "liquid_assets_cents": 8000000},
            make_applicant_officer_headers("officer-loop"),
        ))
        assert patched["status"] == "DRAFT"
        assert patched["liquid_assets_cents"] == 8000000
        resubmitted = submit_application(app["id"], "officer-loop")
        assert resubmitted["status"] == "SUBMITTED"
        rereviewed = review_application(app["id"], "reviewer-1")
        assert rereviewed["status"] == "UNDER_REVIEW"

    def test_revision_loop_version_advances_at_each_hop(self, api):
        """PRD §2.4: "The `version` field is an integer that starts at its
        initial value on creation and increments by exactly one on every
        modification, including modifications caused by system cascades rather
        than direct client writes."
        PRD §3.1: "the application may loop through draft, review, and
        revision repeatedly."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_loop
        """
        app = create_draft_application(
            "officer-loop2",
            legal_name="Loop Cycle Funding Two",
            net_worth_cents=400000000,
            liquid_assets_cents=9000000,
            origination_experience_months=30,
            branch_count=1,
            annual_origination_volume_cents=2000000000,
        )
        assert app["version"] == 1
        submit_application(app["id"], "officer-loop2")          # -> 2
        review_application(app["id"], "reviewer-1")             # -> 3
        rev = get_success_data(api.request_revision(app["id"], make_agency_reviewer_headers("reviewer-1")))  # -> 4
        assert rev["version"] == 4
        patched = get_success_data(api.patch_application(
            app["id"],
            {"expected_application_version": rev["version"], "liquid_assets_cents": 8000000},
            make_applicant_officer_headers("officer-loop2"),
        ))                                                        # -> 5
        assert patched["version"] == 5
        resubmitted = submit_application(app["id"], "officer-loop2")  # -> 6
        assert resubmitted["version"] == 6
        rereviewed = review_application(app["id"], "reviewer-1")      # -> 7
        assert rereviewed["version"] == 7


class TestApproval:
    def test_approve_creates_issuer_snapshot(self, api):
        """PRD §3.1: "Approval moves the application to `APPROVED` and, in the
        same action, creates an `Issuer` in `ACTIVE` status whose
        `application_id` points back to the application and whose
        `legal_name`, `net_worth_cents`, `liquid_assets_cents`, and
        `unused_credit_lines_cents` are copied from the approved application
        as a snapshot; the application's read-only `approved_issuer_id`, null
        until this moment, is set to the new issuer's id."

        Design: Corner/validations/segregation_of_duties_on_approve
        """
        app = create_draft_application(
            "officer-snap",
            legal_name="Snapshot Lending",
            net_worth_cents=400000000,
            liquid_assets_cents=5000000,
            unused_credit_lines_cents=1000000,
            origination_experience_months=36,
            branch_count=1,
            annual_origination_volume_cents=1000000000,
        )
        submit_application(app["id"], "officer-snap")
        review_application(app["id"], "reviewer-1")
        approved = get_success_data(api.approve_application(
            app["id"], make_agency_reviewer_headers("reviewer-1")))
        assert approved["status"] == "APPROVED"
        issuer_id = approved["approved_issuer_id"]
        assert issuer_id, "approved_issuer_id must be set at approval"
        issuer = get_success_data(api.get_issuer(issuer_id, TEST_USERS["platform_admin_headers"]))
        assert_issuer(issuer)
        assert issuer["status"] == "ACTIVE"
        assert issuer["application_id"] == app["id"]
        assert issuer["legal_name"] == "Snapshot Lending"
        assert issuer["net_worth_cents"] == 400000000
        assert issuer["liquid_assets_cents"] == 5000000
        assert issuer["unused_credit_lines_cents"] == 1000000

    def test_same_user_approve_rejected_segregation_of_duties(self, api):
        """PRD §3.1: "the acting reviewer's user id must differ from the id of
        the officer who submitted the application, and a same-user
        adjudication is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_on_approve
        """
        app = create_draft_application(
            "shared-officer",
            legal_name="SoD Lending",
            net_worth_cents=400000000,
            liquid_assets_cents=5000000,
            origination_experience_months=36,
            branch_count=1,
            annual_origination_volume_cents=1000000000,
        )
        submit_application(app["id"], "shared-officer")
        review_application(app["id"], "reviewer-9")
        resp = api.approve_application(app["id"], make_agency_reviewer_headers("shared-officer"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        reread = get_success_data(api.get_application(app["id"], TEST_USERS["platform_admin_headers"]))
        assert reread["status"] == "UNDER_REVIEW"

    def test_different_reviewer_approve_succeeds(self, api):
        """PRD §3.1: "the acting reviewer's user id must differ from the id of
        the officer who submitted the application, and a same-user
        adjudication is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_on_approve
        """
        issuer = setup_approved_issuer("officer-distinct", reviewer_id="reviewer-9")
        assert issuer["status"] == "ACTIVE"
