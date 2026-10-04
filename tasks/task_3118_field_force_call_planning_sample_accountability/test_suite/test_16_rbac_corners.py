"""RBAC corner coverage: exclusive-operation denial across roles and the
identity-based destruction-confirmation segregation rule.

Queue B — corner design section ``rbac``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_compliance_headers,
    make_field_rep_headers,
    validate_error,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import COMPLIANCE_HEADERS


class TestFieldRepDeniedCatalogAdmin:
    def test_field_rep_cannot_create_products(self, api):
        """PRD section 4: "POST /field-force/products — Register a Product —
        PlatformAdmin." PRD section 2.1: "A request whose role is authenticated but
        not authorized for the target endpoint is rejected with
        ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

        Design: Corner/rbac/field_rep_cannot_create_products_or_lots_or_issue_inventory
        """
        region = fx.create_region(api)
        territory = fx.create_territory(api, region["id"])
        rep = fx.create_representative(api, territory["id"])
        response = api.create_product(
            f.create_product_payload(),
            headers=make_field_rep_headers(rep["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_field_rep_cannot_create_sample_lots(self, api):
        """PRD section 4: "POST /field-force/products/{productId}/sample-lots —
        Receive a Sample Lot — PlatformAdmin." PRD section 2.1: "A request whose role
        is authenticated but not authorized for the target endpoint is rejected with
        ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

        Design: Corner/rbac/field_rep_cannot_create_products_or_lots_or_issue_inventory
        """
        region = fx.create_region(api)
        territory = fx.create_territory(api, region["id"])
        rep = fx.create_representative(api, territory["id"])
        product = fx.create_product(api)
        response = api.create_sample_lot(
            product["id"],
            f.create_sample_lot_payload(),
            headers=make_field_rep_headers(rep["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_field_rep_cannot_issue_inventory(self, api):
        """PRD section 4: "POST /field-force/representatives/{repId}/lot-balances —
        Issue sample units from a lot to a rep — PlatformAdmin." PRD section 2.1: "A
        request whose role is authenticated but not authorized for the target
        endpoint is rejected with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

        Design: Corner/rbac/field_rep_cannot_create_products_or_lots_or_issue_inventory
        """
        region = fx.create_region(api)
        territory = fx.create_territory(api, region["id"])
        rep = fx.create_representative(api, territory["id"])
        product = fx.create_product(api)
        lot = fx.create_sample_lot(api, product["id"])
        response = api.issue_lot_balance(
            rep["id"],
            f.issue_lot_balance_payload(lot["id"], 1),
            headers=make_field_rep_headers(rep["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestComplianceOfficerDeniedOtherRoles:
    def _setup(self, api):
        region, territory, manager = fx.setup_manager_territory(api, budget=100)
        rep = fx.create_representative(api, territory["id"])
        prescriber = fx.create_prescriber(api)
        product = fx.create_product(api)
        fx.add_target_entry(
            api,
            territory["id"],
            prescriber["id"],
            product["id"],
            manager,
            tier="C",
            planned_sample_units=10,
        )
        plan = fx.create_plan(api, territory["id"], territory["version"], manager)
        excursion = fx.report_excursion(
            api,
            rep,
            product["id"],
            location_type="VEHICLE",
            observed_temp_c=9.0,
            excursion_minutes=10,
        )
        return {"plan": plan, "excursion": excursion}

    def test_compliance_cannot_publish_plan(self, api):
        """PRD section 4: "POST /field-force/call-plans/{id}/publish — Publish a DRAFT
        plan — DistrictManager." PRD section 2.1: "A request whose role is
        authenticated but not authorized for the target endpoint is rejected with
        ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

        Design: Corner/rbac/compliance_officer_cannot_publish_plans_or_assess_excursions
        """
        ctx = self._setup(api)
        response = api.publish_call_plan(
            ctx["plan"]["id"], headers=COMPLIANCE_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_compliance_cannot_assess_excursion(self, api):
        """PRD section 4: "POST /field-force/temperature-excursions/{id}/assess — QA
        assesses an excursion — QualityAssurance." PRD section 2.1: "A request whose
        role is authenticated but not authorized for the target endpoint is rejected
        with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

        Design: Corner/rbac/compliance_officer_cannot_publish_plans_or_assess_excursions
        """
        ctx = self._setup(api)
        response = api.assess_temperature_excursion(
            ctx["excursion"]["id"], headers=COMPLIANCE_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        excursion = get_success_data(
            api.get_temperature_excursion(
                ctx["excursion"]["id"], headers=COMPLIANCE_HEADERS
            )
        )
        assert excursion["status"] == "REPORTED"


class TestSelfConfirmSegregation:
    def test_returning_rep_cannot_confirm_own_destruction(self, api):
        """PRD section 3.7: "Destruction is then confirmed by a ComplianceOfficer —
        who, per segregation of duties, must not be the returning representative; a
        self-confirmation is rejected with ERR_SELF_CONFIRM_FORBIDDEN."

        Design: Corner/rbac/self_destruction_confirmation_forbidden_for_returning_rep
        """
        ctx = fx.setup_submitted_return(api, quantity=2, rep_issue_qty=10)
        # The confirming ComplianceOfficer carries the returning rep's id.
        response = api.confirm_destruction(
            ctx["return"]["id"],
            headers=make_compliance_headers(ctx["sender"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SELF_CONFIRM_FORBIDDEN)
        ret = get_success_data(
            api.get_sample_return(ctx["return"]["id"], headers=COMPLIANCE_HEADERS)
        )
        assert ret["status"] == "SUBMITTED"
