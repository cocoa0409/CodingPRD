"""Role-based access control: exclusive operations enforced per role."""

from test_helpers import (
    ApiClient,
    create_routed_claim,
    get_success_data,
    setup_two_plan_world,
    validate_error,
)
from test_helpers import factories as f
from test_helpers.test_users import ASSOCIATION_ADMIN_HEADERS


class TestHomePlanOperatorCannotPrice:
    def test_home_plan_operator_cannot_price_claim(self, api: ApiClient):
        """PRD §4: "POST `/v1/claims/{id}/price` | RECEIVED → PRICED; final pricing variant keyed on the logical clock date | HostPlanOperator"
        PRD §2.1: "A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/home_plan_operator_cannot_price_claim
        """
        world = setup_two_plan_world(api, with_fee_schedule=False)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        res = api.price_claim(claim["id"], world["home_headers"])
        validate_error(res, "ERR_UNAUTHORIZED", 403)

    def test_home_plan_operator_from_other_plan_also_rejected(self, api: ApiClient):
        """PRD §2.1: "A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/home_plan_operator_cannot_price_claim
        """
        world = setup_two_plan_world(api, with_fee_schedule=False)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        from test_helpers.test_users import make_home_plan_operator_headers

        res = api.price_claim(claim["id"], make_home_plan_operator_headers(world["host"]["id"]))
        validate_error(res, "ERR_UNAUTHORIZED", 403)


class TestHostPlanOperatorCannotDetermineBenefit:
    def test_host_plan_operator_cannot_determine_benefit(self, api: ApiClient):
        """PRD §4: "POST `/v1/claims/{id}/determine-benefit` | ROUTED → BENEFIT_DETERMINED by the home plan | HomePlanOperator"
        PRD §2.1: "A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/host_plan_operator_cannot_determine_benefit
        """
        world = setup_two_plan_world(api)
        claim = create_routed_claim(api, world)
        res = api.determine_benefit(claim["id"], world["host_headers"])
        validate_error(res, "ERR_UNAUTHORIZED", 403)

    def test_host_plan_operator_cannot_deny(self, api: ApiClient):
        """PRD §4: "POST `/v1/claims/{id}/deny` | ROUTED → DENIED by the home plan (terminal) | HomePlanOperator"
        PRD §2.1: "A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/host_plan_operator_cannot_determine_benefit
        """
        world = setup_two_plan_world(api)
        claim = create_routed_claim(api, world)
        res = api.deny_claim(claim["id"], world["host_headers"])
        validate_error(res, "ERR_UNAUTHORIZED", 403)


class TestAssociationAdminCannotSubmitClaim:
    def test_association_admin_cannot_submit_claim(self, api: ApiClient):
        """PRD §4: "POST `/v1/claims` | Submit an inter-plan claim; provisional pricing runs immediately | HostPlanOperator"
        PRD §2.1: "A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/association_admin_cannot_submit_claim
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        res = api.create_claim(
            f.claim_payload(world["member"]["id"], world["host"]["id"]),
            ASSOCIATION_ADMIN_HEADERS,
        )
        validate_error(res, "ERR_UNAUTHORIZED", 403)

    def test_association_admin_cannot_price_claim(self, api: ApiClient):
        """PRD §4: "POST `/v1/claims/{id}/price` | RECEIVED → PRICED; final pricing variant keyed on the logical clock date | HostPlanOperator"
        PRD §2.1: "A request whose role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/association_admin_cannot_submit_claim
        """
        world = setup_two_plan_world(api, with_fee_schedule=False)
        claim = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            )
        )
        res = api.price_claim(claim["id"], ASSOCIATION_ADMIN_HEADERS)
        validate_error(res, "ERR_UNAUTHORIZED", 403)
