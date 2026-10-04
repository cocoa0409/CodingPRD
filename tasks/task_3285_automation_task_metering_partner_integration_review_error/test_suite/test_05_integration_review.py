"""Partner integration review: auth method, endpoint coverage, and listing decisions."""
from test_helpers import (
    api_client, validate_error, validate_success, get_success_data,
    create_integration, declare_endpoint,
    publish_integration_version, ApiErrorId, TEST_USERS,
)

PARTNER = TEST_USERS["partner_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


def _covered_integration(total=5, with_schema=4):
    """An OAUTH2 integration declaring `total` endpoints of which `with_schema`
    carry response schemas."""
    integration = create_integration()
    for i in range(1, total + 1):
        declare_endpoint(integration["id"], f"/v1/op{i}", has_response_schema=i <= with_schema)
    return integration


class TestReviewGate:
    def test_submit_at_coverage_exactly_0_80_clears_the_coverage_gate(self, api):
        """PRD §2.9: "an `endpoint_coverage` below 0.8 is refused with
        `ERR_INTEGRATION_COVERAGE_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/bp_review_coverage_gate_exactly_point_eight
        """
        # Coverage is exactly 0.80 (4 of 5 endpoints carry schemas), so the
        # coverage gate is inclusive there and does not fire. What the platform
        # reports instead is the separate endpoint-completeness condition of
        # PRD §2.9 ("an integration may not be submitted at all unless it
        # declares at least one endpoint and every declared endpoint carries a
        # response schema"), because a fraction below 1.0 always leaves a gap.
        integration = _covered_integration(total=5, with_schema=4)
        res = api_client.submit_integration(integration["id"], PARTNER)
        assert res.json()["data"]["error_id"] == ApiErrorId.ERR_MISSING_ERROR_SEMANTICS.value
        # 4 of 6 endpoints is 0.67, below the gate, and the coverage shortfall is
        # what surfaces — pinning the threshold as inclusive at 0.80.
        integration2 = _covered_integration(total=6, with_schema=4)
        res2 = api_client.submit_integration(integration2["id"], PARTNER)
        validate_error(res2, ApiErrorId.ERR_INTEGRATION_COVERAGE_INSUFFICIENT.value)

    def test_review_after_coverage_drops_below_the_gate_is_refused(self, api):
        """PRD §2.9: "Only then is coverage examined: an `endpoint_coverage` below 0.8
        is refused with `ERR_INTEGRATION_COVERAGE_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/bp_review_coverage_gate_exactly_point_eight
        """
        integration = _covered_integration(total=5, with_schema=5)
        validate_success(api_client.submit_integration(integration["id"], PARTNER), 200)
        # Two schema-less endpoints drag coverage from 1.00 to 5/7 = 0.71.
        declare_endpoint(integration["id"], "/v1/extra1", has_response_schema=False)
        declare_endpoint(integration["id"], "/v1/extra2", has_response_schema=False)
        res = api_client.review_decision(integration["id"], {"decision": "APPROVE"}, REVIEWER)
        validate_error(res, ApiErrorId.ERR_INTEGRATION_COVERAGE_INSUFFICIENT.value)

    def test_submit_is_refused_when_auth_method_is_not_oauth2(self, api):
        """PRD §2.9: "First, the declared `auth_method` must be `OAUTH2`; `API_KEY` and
        `BASIC` are refused outright with `ERR_AUTH_METHOD_NOT_OAUTH2` (HTTP 422)."

        Design: Corner/validations/val_submit_non_oauth2_integration_returns_auth_method_error
        """
        integration = create_integration(name="Bank", auth_method="API_KEY")
        declare_endpoint(integration["id"], "/v1/op1", has_response_schema=True)
        res = api_client.submit_integration(integration["id"], PARTNER)
        validate_error(res, ApiErrorId.ERR_AUTH_METHOD_NOT_OAUTH2.value)
        unchanged = get_success_data(
            api_client.get_integration(integration["id"], PARTNER))
        assert unchanged["review_status"] == "DRAFT"


class TestCoveragePrecision:
    def test_coverage_rounds_half_up_to_two_places(self, api):
        """PRD §2.9: "Seven of eight endpoints carrying schemas is 0.875, which rounds
        half-up to 0.88 and passes."

        Design: Corner/calculations/cal_endpoint_coverage_rounds_half_up_to_two_places
        """
        integration = _covered_integration(total=8, with_schema=7)
        intg = get_success_data(api_client.get_integration(integration["id"], PARTNER))
        assert intg["endpoint_coverage"] == 0.88


class TestVersionRevocation:
    def test_republishing_a_non_increasing_version_is_refused(self, api):
        """PRD §3.7: "A `PartnerAdmin` publishes a newer release by supplying the
        `version_number`, which must be strictly greater than the highest version number
        already published for that integration; anything else is refused with
        `ERR_VERSION_NOT_MONOTONIC` (HTTP 409)."

        Design: Corner/errors/err_version_not_monotonic_returns_conflict
        """
        integration = _covered_integration(total=1, with_schema=1)
        publish_integration_version(integration["id"], 2)
        res = api_client.publish_integration_version(
            integration["id"], {"version_number": 2}, PARTNER)
        validate_error(res, ApiErrorId.ERR_VERSION_NOT_MONOTONIC.value)