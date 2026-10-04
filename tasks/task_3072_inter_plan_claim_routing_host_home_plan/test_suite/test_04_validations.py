"""Business-rule validations: same-plan, license gating, duplicate keys, window overlap, amounts."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    ApiClient,
    create_licensed_plan,
    create_priced_claim,
    create_rate_schedule,
    get_success_data,
    set_clock,
    setup_paid_claim_world,
    setup_two_plan_world,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.test_users import make_home_plan_operator_headers


class TestSamePlanClaim:
    def test_claim_with_host_equal_to_home_plan_rejected(self, api: ApiClient):
        """PRD §3.5: "the named `host_plan_id` must differ from the member's home plan; a claim whose host equals the home plan is a local claim, not an inter-plan claim, and is rejected with `ERR_SAME_PLAN_CLAIM` (HTTP 422)."

        Design: Corner/validations/claim_with_host_equal_to_home_plan_rejected
        """
        set_clock(api)
        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA", "TX"])
        member = get_success_data(
            api.create_member(f.member_payload(home["id"], member_number="M1"), make_home_plan_operator_headers(home["id"]))
        )
        from test_helpers.test_users import make_host_plan_operator_headers

        res = api.create_claim(
            f.claim_payload(member["id"], home["id"], service_state="TX"),
            make_host_plan_operator_headers(home["id"]),
        )
        validate_error(res, "ERR_SAME_PLAN_CLAIM", 422)

    def test_claim_with_different_host_accepted(self, api: ApiClient):
        """PRD §3.5: "the named `host_plan_id` must differ from the member's home plan; a claim whose host equals the home plan is a local claim, not an inter-plan claim, and is rejected with `ERR_SAME_PLAN_CLAIM` (HTTP 422)."

        A claim whose host differs from the member's home plan is accepted.

        Design: Corner/validations/claim_with_host_equal_to_home_plan_rejected
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        claim = validate_success(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            ),
            201,
        )
        assert claim["host_plan_id"] == world["host"]["id"]
        assert claim["home_plan_id"] == world["home"]["id"]


class TestRouteWithoutFeeSchedule:
    def test_route_without_fee_schedule_rejected(self, api: ApiClient):
        """PRD §3.5: "locates the access fee schedule for the home-host pair whose closed window covers the claim's `service_date`; when none exists, routing fails with `ERR_FEE_SCHEDULE_MISSING` (HTTP 422)."

        Design: Corner/validations/route_without_fee_schedule_rejected
        """
        world = setup_two_plan_world(api, with_fee_schedule=False)
        claim = create_priced_claim(api, world)
        res = api.route_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_FEE_SCHEDULE_MISSING", 422)
        after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert after["status"] == "PRICED"

    def test_route_with_fee_schedule_succeeds(self, api: ApiClient):
        """PRD §3.5: "locates the access fee schedule for the home-host pair whose closed window covers the claim's `service_date`; when none exists, routing fails with `ERR_FEE_SCHEDULE_MISSING` (HTTP 422)."

        With a covering fee schedule in place, routing succeeds.

        Design: Corner/validations/route_without_fee_schedule_rejected
        """
        world = setup_two_plan_world(api, with_fee_schedule=True)
        claim = create_priced_claim(api, world)
        routed = validate_success(api.route_claim(claim["id"], world["host_headers"]), 200)
        assert routed["status"] == "ROUTED"


class TestSuspendedPlanSubmission:
    def test_claim_submission_to_suspended_home_plan_rejected(self, api: ApiClient):
        """PRD §3.5: "both the home plan and the host plan must hold `brand_license_status` of `LICENSED` at submission; a `PENDING`, `SUSPENDED`, or `REVOKED` plan on either side yields `ERR_PLAN_LICENSE_SUSPENDED`."

        Design: Corner/validations/claim_submission_to_suspended_plan_rejected
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        get_success_data(api.suspend_license(world["home"]["id"], ASSOCIATION_ADMIN_HEADERS))
        res = api.create_claim(
            f.claim_payload(world["member"]["id"], world["host"]["id"]),
            world["host_headers"],
        )
        validate_error(res, "ERR_PLAN_LICENSE_SUSPENDED", 409)

    def test_claim_submission_with_suspended_host_plan_rejected(self, api: ApiClient):
        """PRD §3.5: "both the home plan and the host plan must hold `brand_license_status` of `LICENSED` at submission; a `PENDING`, `SUSPENDED`, or `REVOKED` plan on either side yields `ERR_PLAN_LICENSE_SUSPENDED`."

        Design: Corner/validations/claim_submission_to_suspended_plan_rejected
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        get_success_data(api.suspend_license(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        res = api.create_claim(
            f.claim_payload(world["member"]["id"], world["host"]["id"]),
            world["host_headers"],
        )
        validate_error(res, "ERR_PLAN_LICENSE_SUSPENDED", 409)


class TestAdjustmentAmountValidation:
    def test_zero_delta_adjustment_rejected(self, api: ApiClient):
        """PRD §3.7: "a signed non-zero `delta_allowed_cents` describing the change to the allowed amount (a zero delta is rejected with `ERR_INVALID_AMOUNT`)"

        Design: Corner/validations/zero_delta_adjustment_rejected
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        res = api.create_adjustment(
            claim["id"],
            f.adjustment_payload(claim["version"], delta_allowed_cents=0),
            world["host_headers"],
        )
        validate_error(res, "ERR_INVALID_AMOUNT", 422)
        after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert after["status"] == "PAID"

    def test_nonzero_delta_adjustment_accepted(self, api: ApiClient):
        """PRD §3.7: "a signed non-zero `delta_allowed_cents` describing the change to the allowed amount (a zero delta is rejected with `ERR_INVALID_AMOUNT`)"

        A non-zero delta is accepted.

        Design: Corner/validations/zero_delta_adjustment_rejected
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        adjustment = validate_success(
            api.create_adjustment(
                claim["id"],
                f.adjustment_payload(claim["version"], delta_allowed_cents=-5000),
                world["host_headers"],
            ),
            201,
        )
        assert adjustment["delta_allowed_cents"] == -5000
        assert adjustment["status"] == "INITIATED"


class TestNegativeAllowedGuard:
    def test_adjustment_driving_allowed_negative_rejected(self, api: ApiClient):
        """PRD §3.7: "an applied downward adjustment must never drive the claim's allowed amount negative, so when the claim's `current_allowed_cents` plus the signed `delta_allowed_cents` would fall below zero, the application is rejected outright with `ERR_NEGATIVE_ALLOWED` (HTTP 422) and nothing changes."

        Design: Corner/validations/adjustment_driving_allowed_negative_rejected
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        from test_helpers import create_propagated_adjustment

        adjustment = create_propagated_adjustment(api, world, claim, delta=-25000, reason="over-recovery")
        res = api.apply_adjustment(adjustment["id"], world["host_headers"])
        validate_error(res, "ERR_NEGATIVE_ALLOWED", 422)

        adj_after = get_success_data(api.get_adjustment(adjustment["id"], world["host_headers"]))
        assert adj_after["status"] == "PROPAGATED"
        host_after = get_success_data(api.get_plan(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS))
        assert host_after["claims_paid_balance_cents"] == 20000

    def test_adjustment_to_exactly_zero_allowed_accepted(self, api: ApiClient):
        """PRD §3.7: "when the claim's `current_allowed_cents` plus the signed `delta_allowed_cents` would fall below zero, the application is rejected outright with `ERR_NEGATIVE_ALLOWED` (HTTP 422)"

        A downward delta that lands exactly on zero does not fall below zero, so it applies.

        Design: Corner/validations/adjustment_driving_allowed_negative_rejected
        """
        world = setup_paid_claim_world(api)
        claim = world["claim"]
        from test_helpers import create_propagated_adjustment

        adjustment = create_propagated_adjustment(api, world, claim, delta=-20000, reason="full takeback")
        applied = validate_success(api.apply_adjustment(adjustment["id"], world["host_headers"]), 200)
        assert applied["status"] == "APPLIED"
        claim_after = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
        assert claim_after["current_allowed_cents"] == 0


class TestDuplicateMemberNumber:
    def test_duplicate_member_number_within_home_plan_rejected(self, api: ApiClient):
        """PRD §3.2: "The `member_number` is unique within its home plan: registering a second member with the same `member_number` under the same `home_plan_id` is rejected with `ERR_DUPLICATE_MEMBER_NUMBER` (HTTP 409)."

        Design: Corner/validations/duplicate_member_number_within_home_plan_rejected
        """
        set_clock(api)
        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        home2 = create_licensed_plan(api, plan_code="HNY", legal_name="Home Plan NY", service_area_states=["NY"])

        get_success_data(
            api.create_member(f.member_payload(home["id"], member_number="DUP"), make_home_plan_operator_headers(home["id"]))
        )
        res = api.create_member(
            f.member_payload(home["id"], member_number="DUP", full_name="Pat Two"),
            make_home_plan_operator_headers(home["id"]),
        )
        validate_error(res, "ERR_DUPLICATE_MEMBER_NUMBER", 409)

        ok = validate_success(
            api.create_member(
                f.member_payload(home2["id"], member_number="DUP", full_name="Pat Three"),
                make_home_plan_operator_headers(home2["id"]),
            ),
            201,
        )
        assert ok["member_number"] == "DUP"

    def test_different_member_number_same_home_plan_accepted(self, api: ApiClient):
        """PRD §3.2: "The `member_number` is unique within its home plan: registering a second member with the same `member_number` under the same `home_plan_id` is rejected with `ERR_DUPLICATE_MEMBER_NUMBER` (HTTP 409)."

        Design: Corner/validations/duplicate_member_number_within_home_plan_rejected
        """
        set_clock(api)
        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        get_success_data(
            api.create_member(f.member_payload(home["id"], member_number="M1"), make_home_plan_operator_headers(home["id"]))
        )
        ok = validate_success(
            api.create_member(f.member_payload(home["id"], member_number="M2", full_name="Pat Two"), make_home_plan_operator_headers(home["id"])),
            201,
        )
        assert ok["member_number"] == "M2"


class TestRevokeWithOpenClaims:
    def test_revoke_with_open_claims_rejected(self, api: ApiClient):
        """PRD §3.1: "Revocation moves a `LICENSED` plan to the terminal `REVOKED` state, but only when no claim hosted or owned by the plan is in any non-terminal state — that is, no such claim may be in `RECEIVED`, `PRICED`, `ROUTED`, `BENEFIT_DETERMINED`, or `ADJUSTMENT_PENDING` at the moment of revocation; when such a claim exists, the revocation is refused with `ERR_INVALID_STATE` because its precondition is unmet."

        Design: Corner/validations/revoke_with_open_claims_rejected
        """
        world = setup_two_plan_world(api)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        get_success_data(api.price_claim(claim["id"], world["host_headers"]))
        get_success_data(api.route_claim(claim["id"], world["host_headers"]))

        res = api.revoke_license(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS)
        validate_error(res, "ERR_INVALID_STATE", 409)

        get_success_data(api.deny_claim(claim["id"], world["home_headers"]))
        revoked = validate_success(api.revoke_license(world["host"]["id"], ASSOCIATION_ADMIN_HEADERS), 200)
        assert revoked["brand_license_status"] == "REVOKED"

    def test_revoke_with_no_claims_succeeds(self, api: ApiClient):
        """PRD §3.1: "Revocation moves a `LICENSED` plan to the terminal `REVOKED` state, but only when no claim hosted or owned by the plan is in any non-terminal state"

        With no claims at all, revocation succeeds immediately.

        Design: Corner/validations/revoke_with_open_claims_rejected
        """
        set_clock(api)
        plan = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        revoked = validate_success(api.revoke_license(plan["id"], ASSOCIATION_ADMIN_HEADERS), 200)
        assert revoked["brand_license_status"] == "REVOKED"


class TestNationalAccountWindowOverlap:
    def test_closed_window_overlap_rejected(self, api: ApiClient):
        """PRD §3.3: "for the same pair of controlling plan and employer group identifier, no two national account windows may overlap, and because the windows are closed intervals, adjacency that shares an endpoint date already counts as overlap; a violating creation is rejected with `ERR_ACCOUNT_WINDOW_OVERLAP` (HTTP 422)."

        Design: Corner/validations/national_account_closed_window_overlap_rejected
        """
        set_clock(api)
        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        get_success_data(
            api.create_national_account(
                f.national_account_payload(home["id"], effective_start="2026-01-01", effective_end="2026-06-30"),
                ASSOCIATION_ADMIN_HEADERS,
            )
        )
        res = api.create_national_account(
            f.national_account_payload(
                home["id"], account_name="Acme Corp West", effective_start="2026-06-30", effective_end="2026-12-31"
            ),
            ASSOCIATION_ADMIN_HEADERS,
        )
        validate_error(res, "ERR_ACCOUNT_WINDOW_OVERLAP", 422)

        ok = validate_success(
            api.create_national_account(
                f.national_account_payload(
                    home["id"],
                    account_name="Other Co",
                    employer_group_id="OTHER-1",
                    effective_start="2026-06-30",
                    effective_end="2026-12-31",
                ),
                ASSOCIATION_ADMIN_HEADERS,
            ),
            201,
        )
        assert ok["employer_group_id"] == "OTHER-1"

    def test_non_touching_window_same_employer_accepted(self, api: ApiClient):
        """PRD §3.3: "for the same pair of controlling plan and employer group identifier, no two national account windows may overlap, and because the windows are closed intervals, adjacency that shares an endpoint date already counts as overlap"

        A window starting the day after the inclusive end does not share an endpoint.

        Design: Corner/validations/national_account_closed_window_overlap_rejected
        """
        set_clock(api)
        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        get_success_data(
            api.create_national_account(
                f.national_account_payload(home["id"], effective_start="2026-01-01", effective_end="2026-06-30"),
                ASSOCIATION_ADMIN_HEADERS,
            )
        )
        ok = validate_success(
            api.create_national_account(
                f.national_account_payload(home["id"], account_name="Acme Corp West", effective_start="2026-07-01", effective_end="2026-12-31"),
                ASSOCIATION_ADMIN_HEADERS,
            ),
            201,
        )
        assert ok["employer_group_id"] == "ACME-1"
