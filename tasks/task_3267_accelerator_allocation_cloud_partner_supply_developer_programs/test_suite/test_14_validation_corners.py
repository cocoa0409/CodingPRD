"""Corner coverage: validation rules that refuse a request with a specific error."""
from test_helpers import (
    api, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_partner_ops_headers, startup_clock,
    NON_EXISTENT_UUID, create_certified_blueprint, create_validated_partner,
    create_partner, create_product, create_supply_node, create_stack_license,
    create_deployment, activate_deployment, create_membership,
    create_confidentiality_ack, create_and_commit_allocation_hold, create_validation,
    get_partner, get_product, get_subscription,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM = TEST_USERS["partner_program_manager_headers"]
SUPPORT = TEST_USERS["support_account_manager_headers"]


class TestMissingIdentityHeader:
    """A request with no identity header is refused at the first priority."""

    def test_missing_headers_return_the_context_header_error(self):
        """PRD §2.1: "Both headers are mandatory; if either is absent, or if
        `X-User-Role` carries a value that is not one of the roles enumerated below, the
        request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP
        400."

        Design: Corner/validations/missing_role_header_returns_context_header_error
        """
        startup_clock()
        response = api.create_partner({
            "legal_name": "Ghost Partner",
            "partner_type": "CLOUD_PROVIDER",
            "destination_country": "US",
            "export_restriction_tier": "LICENSE_EXCEPTION",
            "origin_epoch_index": 5,
        }, {})
        validate_error(response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRolePermission:
    """Role exclusivity is enforced before any state or existence check."""

    def test_partner_ops_cannot_qualify_a_partner(self):
        """PRD §2.1: "When the headers are well-formed but the declared role is not among
        the roles permitted for the targeted operation, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` and HTTP 403."

        Design: Corner/validations/partner_ops_cannot_qualify_a_partner
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_partner()
        create_validation(partner["id"], blueprint["id"])

        response = api.qualify_partner(partner["id"],
                                       make_partner_ops_headers(partner["id"]))
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        assert get_partner(partner["id"])["qualification_status"] == "IN_VALIDATION", (
            "the partner stays in IN_VALIDATION when the role is refused"
        )


class TestUnknownBlueprintReference:
    """A body-declared blueprint reference that does not resolve reports not-found."""

    def test_unknown_blueprint_is_reported_before_the_minute_threshold(self):
        """PRD §2.10: "A body-declared blueprint reference that does not resolve reports
        `ERR_BLUEPRINT_NOT_FOUND` with HTTP 404."

        Design: Corner/validations/validation_evidence_with_unknown_blueprint_returns_not_found
        """
        startup_clock()
        partner = create_partner()
        response = api.create_validation(partner["id"], {
            "validation_minutes": 240,
            "test_count": 6,
            "blueprint_id": NON_EXISTENT_UUID,
        }, PROGRAM)
        validate_error(response, ApiErrorId.ERR_BLUEPRINT_NOT_FOUND, 404)
        assert get_partner(partner["id"])["qualification_status"] == "APPLIED", (
            "the partner stays APPLIED when the evidence pack is never created"
        )


class TestPreviewGrantNdaGate:
    """A preview grant without a bound acknowledgement is refused."""

    def test_unknown_acknowledgement_returns_the_nda_error(self):
        """PRD §3.6: "a grant whose referenced stack carries the preview flag must be
        backed by a `BOUND` confidentiality acknowledgement, otherwise it is refused
        with `ERR_NDA_NOT_BOUND`."

        Design: Corner/validations/preview_grant_without_bound_nda_returns_nda_error
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        stack = create_stack_license(product["id"], license_code="SL-PREV-1",
                                     entitlement_units=25, min_package_version="2.0.0-preview",
                                     preview_stack_flag=True)
        membership = create_membership(partner["id"], requested_tier="PREFERRED")
        get_success_data(api.evaluate_membership(membership["id"], PROGRAM))

        response = api.create_preview_grant({
            "stack_license_id": stack["id"],
            "device_serial": "EVAL-9001",
            "commitment_boundary_at": "2026-09-01T00:00:00Z",
            "commitment_expires_at": "2026-10-31T00:00:00Z",
            "confidentiality_ack_id": NON_EXISTENT_UUID,
        }, PROGRAM)
        validate_error(response, ApiErrorId.ERR_NDA_NOT_BOUND, 403)


class TestExportControlGates:
    """Prohibited and licence-required destinations report distinct errors."""

    def test_prohibited_destination_is_refused_at_registration(self):
        """PRD §2.5: "A `TIER_3_PROHIBITED` classification blocks the operation outright
        with `ERR_EXPORT_CONTROL_RESTRICTED` and HTTP 403."

        Design: Corner/validations/prohibited_destination_deployment_returns_export_error
        """
        startup_clock()
        partner = create_validated_partner()
        product = create_product(tdp_watts=1350)

        response = api.create_deployment({
            "product_sku_id": product["id"],
            "partner_id": partner["id"],
            "destination_country_code": "CN",
            "stack_manifest": [],
        }, SUPPORT)
        validate_error(response, ApiErrorId.ERR_EXPORT_CONTROL_RESTRICTED, 403)

    def test_licence_required_destination_without_a_grant_is_refused(self):
        """PRD §2.5: "when no such grant is on file the request is refused with
        `ERR_EXPORT_LICENSE_REQUIRED` and HTTP 403."

        Design: Corner/validations/prohibited_destination_deployment_returns_export_error
        """
        startup_clock()
        partner = create_validated_partner()
        product = create_product(tdp_watts=1350)

        response = api.create_deployment({
            "product_sku_id": product["id"],
            "partner_id": partner["id"],
            "destination_country_code": "FR",
            "stack_manifest": [],
        }, SUPPORT)
        validate_error(response, ApiErrorId.ERR_EXPORT_LICENSE_REQUIRED, 403)


class TestRequestShapeValidation:
    """A zero-unit allocation is a malformed request."""

    def test_zero_quantity_is_refused_and_no_hold_is_created(self):
        """PRD §2.12: "The request shape is valid — required fields present, enum members
        known, integer fields non-negative, and `quantity_units` strictly positive —
        otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/validations/non_positive_allocation_quantity_returns_invalid_request
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        partner_state = get_partner(partner["id"])
        product_state = get_product(product["id"])

        response = api.create_allocation_hold({
            "product_sku_id": product["id"],
            "supply_node_id": node["id"],
            "quantity_units": 0,
            "hold_friction_tier": "COOL",
            "expected_partner_version": partner_state["version"],
            "expected_allocated_units": product_state["allocated_units"],
        }, make_partner_ops_headers(partner["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

        data, meta = validate_paginated(api.list_allocation_holds(
            make_partner_ops_headers(partner["id"]), params={"partner_id": partner["id"]}))
        assert meta["total_count"] == 0, "no hold is created for a malformed request"


class TestEntitlementCeiling:
    """Activation that would breach the entitlement ceiling is refused."""

    def test_second_activation_beyond_the_ceiling_is_refused(self):
        """PRD §3.7: "Activation is also refused with `ERR_ENTITLEMENT_UNITS_EXCEEDED`
        when adding those entitlement units would push the partner's held entitlement
        above the entitlement ceiling."

        Design: Corner/validations/entitlement_ceiling_breach_returns_entitlement_error
        """
        startup_clock()
        blueprint = create_certified_blueprint()
        partner = create_validated_partner(blueprint_id=blueprint["id"])
        product = create_product()
        node = create_supply_node(product["id"])
        create_and_commit_allocation_hold(product["id"], node["id"], 5, partner["id"])
        # The ceiling is 100000 units; a 60000-unit stack makes two activations breach it.
        stack = create_stack_license(product["id"], license_code="STACK-HUGE-1",
                                     entitlement_units=60000)
        deployment = create_deployment(
            product["id"],
            partner["id"],
            stack_manifest=[{"license_id": stack["id"], "entitlement_units": 60000}],
            destination_country_code="US")
        deployment = activate_deployment(deployment["id"])
        first = get_success_data(api.create_subscription({
            "deployment_id": deployment["id"], "support_tier": "ENTERPRISE",
            "seat_count": 100, "licence_group": [{"license_id": stack["id"]}],
            "trial_flag": True}, SUPPORT), 201)
        second = get_success_data(api.create_subscription({
            "deployment_id": deployment["id"], "support_tier": "ENTERPRISE",
            "seat_count": 100, "licence_group": [{"license_id": stack["id"]}],
            "trial_flag": True}, SUPPORT), 201)
        validate_success(api.activate_subscription(first["id"], SUPPORT))
        assert get_partner(partner["id"])["entitlement_units_held"] == 60000

        response = api.activate_subscription(second["id"], SUPPORT)
        validate_error(response, ApiErrorId.ERR_ENTITLEMENT_UNITS_EXCEEDED)
        assert get_success_data(api.get_subscription(second["id"], SUPPORT))["status"] == "DRAFT"
        assert get_partner(partner["id"])["entitlement_units_held"] == 60000