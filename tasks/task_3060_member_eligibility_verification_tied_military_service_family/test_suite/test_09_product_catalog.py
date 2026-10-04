"""Product catalog: category gate on entitlement opens and the 24-facet
availability matrix."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures
from test_helpers.fixtures import (
    OFFICER_A,
    build_offering,
    make_member_headers,
    open_entitlement,
)


class TestCategoryGate:
    def _veteran_and_child(self, api):
        _, sponsor_id = fixtures.approve_direct_member(
            api, name="Gate Gary", dob="1974-01-01",
            start="1994-01-01", end="2000-01-01",
        )
        _, child_id = fixtures.approve_family_member(
            api, sponsor_id, "CHILD", name="Gate Kid", dob="2001-01-01",
            doc_type="BIRTH_CERTIFICATE",
        )
        return sponsor_id, child_id

    def test_open_outside_allowed_categories_rejected(self, api):
        """PRD §3.7: "The category gate enforces that the offering's
        `allowed_categories` contains the member's current
        `eligibility_category` and that the offering's `is_active_flag` is
        true; otherwise the open is rejected with
        `ERR_PRODUCT_CATEGORY_FORBIDDEN`."

        Design: Corner/validations/product_category_gate_on_entitlement_open
        """
        _, child_id = self._veteran_and_child(api)
        vet_only = build_offering(
            api, categories=["VETERAN_HONORABLE"], product_line="INVESTMENT",
            product_code="VET_ONLY", product_name="Veteran Brokerage",
        )
        resp = api.create_entitlement(
            child_id, {"product_offering_id": vet_only["id"]},
            make_member_headers(child_id),
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_CATEGORY_FORBIDDEN)

    def test_open_inside_allowed_categories_succeeds(self, api):
        """PRD §3.7: "A successful open creates the entitlement in `OPEN`
        status, stamps `opened_at` from the logical clock, and leaves
        `closure_reason` null and `grandfathered` false."

        Design: Corner/validations/product_category_gate_on_entitlement_open
        """
        _, child_id = self._veteran_and_child(api)
        all_cats = build_offering(
            api, product_line="BANKING", product_code="ALL_CAT",
            product_name="Everyday Checking",
        )
        entitlement = open_entitlement(api, child_id, all_cats["id"])
        assert entitlement["status"] == "OPEN"
        assert entitlement["grandfathered"] is False


class TestAvailabilityMatrix:
    def test_matrix_reflects_category_gate(self, api):
        """PRD §3.7: "The rule: for each offering whose `is_active_flag` is
        true, the offering's base availability holds when its
        `allowed_categories` contains the member's `eligibility_category`...
        A base-available offering turns all six facets of its `product_line`
        group to `AVAILABLE`. The `DEPLOYMENT` group's six facets are
        `AVAILABLE` only when there exists an active, base-available,
        `deployment_enhanced` offering and the member's `deployment_posture`
        is `DEPLOYED`." and "The matrix response exposes the member's
        `member_id`, `eligibility_category`, `status`, `deployment_posture`,
        `available_facet_count`, and the per-group `facets` detail..."

        Design: Corner/endpoints/product_matrix_computed_read
        """
        _, member_id = fixtures.approve_direct_member(
            api, name="Mat Mary", dob="1982-02-02",
            start="2002-01-01", end="2008-01-01",
        )
        build_offering(
            api, categories=["VETERAN_HONORABLE"], product_line="BANKING",
            product_code="CK_VET", product_name="Veteran Checking",
        )
        matrix = validate_success(
            api.get_product_matrix(member_id, make_member_headers(member_id))
        )
        # PRD §3.7: one base-available BANKING offering turns all six facets
        # of its group AVAILABLE; available_facet_count is six times the
        # number of fully available groups, and the response exposes the
        # member's identity fields plus the per-group `facets` detail
        # (the PRD does not pin the facets representation, only that the
        # per-group detail exists).
        assert matrix["available_facet_count"] == 6
        assert "facets" in matrix
        assert matrix["eligibility_category"] == "VETERAN_HONORABLE"
        assert matrix["status"] == "ACTIVE"
        assert matrix["deployment_posture"] == "NONE"
