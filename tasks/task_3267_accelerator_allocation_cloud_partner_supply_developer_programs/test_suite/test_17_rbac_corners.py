"""Corner coverage: role-based access denial on registration and commitment grant."""
from test_helpers import (
    api, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_partner_ops_headers, startup_clock,
    create_certified_blueprint, create_validated_partner, create_product,
    create_lifecycle_commitment, get_lifecycle_commitment, get_product,
    advance_product_lifecycle,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]


class TestPartnerRegistrationIsRoleBound:
    """Partner registration belongs to PartnerOps."""

    def test_support_account_manager_cannot_register_a_partner(self):
        """PRD §2.1: "The system recognises exactly seven roles, spelled as follows:
        `PlatformAdmin`, `SupplyPlanner`, `PartnerProgramManager`, `PartnerOps`,
        `SupportAccountManager`, `SupplyComplianceOfficer`, and
        `LifecycleProgramManager`."
        PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` and HTTP 403."

        Design: Corner/rbac/support_account_manager_cannot_register_a_partner
        """
        startup_clock()
        response = api.create_partner({
            "legal_name": "Rogue Integrators",
            "partner_type": "SYSTEM_BUILDER",
            "destination_country": "US",
            "export_restriction_tier": "LICENSE_EXCEPTION",
            "origin_epoch_index": 1,
        }, SUPPORT)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


class TestCommitmentGrantIsRoleBound:
    """Granting a lifecycle commitment is exclusive to LifecycleProgramManager."""

    def test_partner_ops_cannot_grant_a_lifecycle_commitment(self):
        """PRD §2.12: "The caller's role permitted for the endpoint, otherwise
        `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §3.9: "Granting it moves it to `GRANTED` and requires three conditions: the
        embedded partner is `QUALIFIED`; the requested horizon is at or after the logical
        clock plus the lifecycle grace period of 365 days".

        Design: Corner/rbac/partner_ops_cannot_grant_a_lifecycle_commitment
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(
            legal_name="Vector Embedded Ltd", partner_type="EMBEDDED_VENDOR",
            destination_country="SG", export_restriction_tier="LICENSE_REQUIRED",
            blueprint_id=blueprint["id"])
        product = create_product()
        product = advance_product_lifecycle(product["id"])
        commitment = create_lifecycle_commitment(
            product["id"], partner["id"], availability_through="2029-05-29T00:00:00Z",
            covered_units=500)
        version = get_product(product["id"])["version"]

        response = api.grant_lifecycle_commitment(
            commitment["id"], {"expected_product_version": version},
            make_partner_ops_headers(partner["id"]))
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        assert get_lifecycle_commitment(commitment["id"])["commitment_status"] == "REQUESTED"