"""Authorisation: endpoint role lists, header shape, row scoping, action scoping
and segregation of duties.

Four different mechanisms all end in a refusal, and they are not the same
mechanism. An endpoint's role list is checked before any body validation; the
`X-User-Role` header itself can be missing or name a role that does not exist; the
supplier portal's authority is scoped to the rows it owns and to the actions it may
take; and segregation of duties is keyed on `X-User-ID` rather than on the role, so
it produces a different error code entirely.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_concentration,
    assert_exposure,
    assert_instant,
    assert_margin,
    assert_status,
)
from test_helpers.constants import (
    ASSESSMENT_FINAL,
    ASSESSMENT_PEER_REVIEWED,
    ASSESSMENT_SUBMITTED,
    BASIS_SUPPLIER_DECLARED,
    COMPLETENESS_COMPLETE,
    DECISION_WARNING_REQUIRED,
    DEFAULT_CLOCK,
    DETERMINATION_APPROVED,
    DETERMINATION_DRAFT,
    DETERMINATION_PENDING_APPROVAL,
    DISCLOSURE_RECEIVED,
    DISCLOSURE_REQUESTED,
    LINK_STATUS_DECLARED,
    METHOD_MODELED,
    RESULT_AT_OR_ABOVE,
    ROLE_REGULATORY_COUNSEL,
    ROLE_TOXICOLOGY_REVIEWER,
    ROUTE_ORAL,
)
from test_helpers.fixtures import (
    add_component,
    advance_disclosure,
    make_assessment,
    make_benzene,
    make_bpa,
    make_determination,
    make_material,
    make_product,
    make_supplied_material,
    make_supplier,
    set_clock,
    submit_assessment,
)
from test_helpers.test_users import (
    CA_1,
    COMPLIANCE_ANALYST,
    DUAL_1,
    LABELING_SPECIALIST,
    LS_1,
    RC_1,
    REGISTRY_ADMIN,
    REGULATORY_COUNSEL,
    TOX_1,
    TOXICOLOGY_REVIEWER,
    UNKNOWN_ROLE,
    headers_with_unknown_role,
    headers_without_role,
    make_compliance_analyst_headers,
    make_headers_for_role,
    make_supplier_portal_user_headers,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _create_product_as(api, headers, **overrides):
    """The raw product create, so a denial can be inspected."""
    return api.create_product(
        f.product_payload("SKU-RB1", product_name="Role Widget", **overrides), headers
    )


def _product_count(api):
    _, meta = validate_paginated(api.list_products(REGISTRY_ADMIN, f.page()))
    return meta["total_count"]


def _read_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, COMPLIANCE_ANALYST))


def _read_determination(api, determination_id):
    return get_success_data(
        api.get_determination(determination_id, LABELING_SPECIALIST)
    )


def _move_assessment(api, assessment_id, action, headers):
    return api.assessment_transition(assessment_id, f.action_payload(action), headers)


def _move_determination(api, determination_id, action, headers):
    return api.determination_transition(
        determination_id, f.action_payload(action), headers
    )


def _link_count(api, material_id):
    _, meta = validate_paginated(
        api.list_material_chemicals(COMPLIANCE_ANALYST, f.page(material_id=material_id))
    )
    return meta["total_count"]


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def clocked(api):
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def one_product(api, clocked):
    """A single product, readable by five of the six roles."""
    return make_product(
        api, "SKU-RB2", product_name="Header Widget", annual_units=100
    )


@pytest.fixture
def portal(api, clocked):
    """Two suppliers with one material each, plus a product the portal may not see.

    Northgate's RM-N has already been asked for data, so a portal response is due;
    Southbay's RM-S belongs to somebody else entirely.
    """
    chemical = make_bpa(api)
    northgate = make_supplier(api, "Northgate Polymers")
    southbay = make_supplier(api, "Southbay Resins")
    mat_n = make_material(api, "RM-N", northgate["id"])
    mat_s = make_material(api, "RM-S", southbay["id"])
    advance_disclosure(api, mat_n["id"], DISCLOSURE_REQUESTED)
    product = make_product(
        api, "SKU-RB3", product_name="Portal Widget", annual_units=100
    )
    return {
        "chemical": chemical,
        "northgate": northgate,
        "southbay": southbay,
        "mat_n": mat_n,
        "mat_s": mat_s,
        "product": product,
        "headers": make_supplier_portal_user_headers(northgate["id"]),
    }


def _benzene_product(api, sku, product_name, material_code):
    """One product carrying 800.0 ppm of Benzene in a VERIFIED material.

    0.25 g/unit at contact_factor 0.5 gives a 100.000 ug/day modelled ORAL exposure
    against Benzene's 6.4 ug/day NSRL.
    """
    benzene = make_benzene(api)
    supplied = make_supplied_material(
        api, benzene["id"], 800.0, material_code=material_code
    )
    product = make_product(api, sku, product_name=product_name, annual_units=100)
    add_component(api, product["id"], supplied["material"]["id"], 0.25, 0.5)
    return {"chemical": benzene, "material": supplied["material"], "product": product}


@pytest.fixture
def submitted(api, clocked):
    """SKU-RB4 with an assessment that ca_1 has already taken to SUBMITTED."""
    bundle = _benzene_product(api, "SKU-RB4", "Action Scope Widget", "RM-RB4")
    assessment = make_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_ORAL,
        1.0,
    )
    submit_assessment(api, assessment["id"], COMPLIANCE_ANALYST)
    bundle["assessment"] = assessment
    return bundle


@pytest.fixture
def dual_submitted(api, clocked):
    """SKU-SOD with an assessment submitted by dual_1 wearing the analyst role.

    The same human then presents the ToxicologyReviewer role, which is exactly the
    case segregation of duties exists to refuse.
    """
    bundle = _benzene_product(api, "SKU-SOD", "Duties Widget", "RM-SOD")
    dual_analyst = make_compliance_analyst_headers(DUAL_1)
    assessment = make_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_ORAL,
        1.0,
        headers=dual_analyst,
    )
    submit_assessment(api, assessment["id"], dual_analyst)
    bundle["assessment"] = assessment
    bundle["dual_analyst"] = dual_analyst
    return bundle


# ─────────────────────────────────────────────────────────────────────────────
# 1 — POST /products declares exactly one role
# ─────────────────────────────────────────────────────────────────────────────


class TestProductCreateIsRegistryAdminExclusive:
    """One endpoint, one role, and the role check runs before the body check."""

    def test_compliance_analyst_cannot_create_a_product(self, api, clocked):
        """The role that owns the whole bill of materials still cannot open a product.

        PRD: "`sku` is unique, `lifecycle_state` starts at `DEVELOPMENT` and `compliance_posture` at `EXPOSURE_UNKNOWN`. | RegistryAdmin |"
        PRD: "(2) the caller's role is not among the roles the target endpoint authorises → `ERR_UNAUTHORIZED`;"

        Design: Corner/rbac/rbac_product_create_is_registry_admin_exclusive_and_rejects_every_other_role
        """
        response = _create_product_as(api, COMPLIANCE_ANALYST)

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_labeling_specialist_cannot_create_a_product(self, api, clocked):
        """A second non-admin role is refused by the same endpoint role list.

        PRD: "`sku` is unique, `lifecycle_state` starts at `DEVELOPMENT` and `compliance_posture` at `EXPOSURE_UNKNOWN`. | RegistryAdmin |"

        Design: Corner/rbac/rbac_product_create_is_registry_admin_exclusive_and_rejects_every_other_role
        """
        response = _create_product_as(api, LABELING_SPECIALIST)

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_role_denial_outranks_the_empty_channel_check(self, api, clocked):
        """An empty `distribution_channels` array from the wrong role still reads
        ERR_UNAUTHORIZED, because item 2 of layer 1 fires before item 12.

        PRD: "Rules are evaluated in ascending priority order; the first rule whose condition holds short-circuits the request and returns its error, and no later rule is evaluated."
        PRD: "(2) the caller's role is not among the roles the target endpoint authorises → `ERR_UNAUTHORIZED`;"
        PRD: "(12) `distribution_channels` is an empty array or contains a value outside the declared set → `ERR_INVALID_REQUEST`."

        Design: Corner/rbac/rbac_product_create_is_registry_admin_exclusive_and_rejects_every_other_role
        """
        response = _create_product_as(
            api, REGULATORY_COUNSEL, distribution_channels=[]
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_only_the_registry_admin_create_persists_a_row(self, api, clocked):
        """Three denied creates leave the catalogue empty; the admin's create is the
        one row that survives.

        PRD: "`sku` is unique, `lifecycle_state` starts at `DEVELOPMENT` and `compliance_posture` at `EXPOSURE_UNKNOWN`. | RegistryAdmin |"
        PRD: "`total_count` (the number of rows matching the filters before the page window is applied)"

        Design: Corner/rbac/rbac_product_create_is_registry_admin_exclusive_and_rejects_every_other_role
        """
        validate_error(_create_product_as(api, COMPLIANCE_ANALYST), ERR_UNAUTHORIZED, 403)
        validate_error(_create_product_as(api, LABELING_SPECIALIST), ERR_UNAUTHORIZED, 403)
        validate_error(
            _create_product_as(api, REGULATORY_COUNSEL, distribution_channels=[]),
            ERR_UNAUTHORIZED,
            403,
        )

        product = get_success_data(_create_product_as(api, REGISTRY_ADMIN))

        assert product["sku"] == "SKU-RB1"
        assert _product_count(api) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2 — the header itself, not the endpoint's role list
# ─────────────────────────────────────────────────────────────────────────────


class TestAbsentOrUnknownRoleHeader:
    """Item 1 of layer 1 covers the two authentication-shaped failures."""

    def test_no_role_header_at_all_is_unauthorized(self, api, one_product):
        """A caller that sends an identity but no role is refused on a read that
        five of the six roles may call.

        PRD: "(1) the `X-User-Role` header is absent or is not one of the six declared roles → `ERR_UNAUTHORIZED`;"

        Design: Corner/rbac/rbac_absent_or_unknown_role_header_is_unauthorized
        """
        response = api.raw_get(
            f"/products/{one_product['id']}", headers_without_role()
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_undeclared_role_name_is_unauthorized(self, api, one_product):
        """`AuditorGeneral` is not one of the six declared roles, so it never reaches
        the endpoint's own role list.

        PRD: "The six roles are `RegistryAdmin`, `ComplianceAnalyst`, `ToxicologyReviewer`, `LabelingSpecialist`, `RegulatoryCounsel` and `SupplierPortalUser`."
        PRD: "(1) the `X-User-Role` header is absent or is not one of the six declared roles → `ERR_UNAUTHORIZED`;"

        Design: Corner/rbac/rbac_absent_or_unknown_role_header_is_unauthorized
        """
        assert UNKNOWN_ROLE == "AuditorGeneral"

        response = api.raw_get(
            f"/products/{one_product['id']}", headers_with_unknown_role()
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_the_same_read_succeeds_with_a_declared_role(self, api, one_product):
        """Only the header was at fault: the endpoint itself is reachable.

        PRD: "Read one product including both state dimensions and the derived counters `open_notice_count`, `accrued_penalty_cents` and `total_listed_chemical_load_ug`. | ComplianceAnalyst, ToxicologyReviewer, RegulatoryCounsel, LabelingSpecialist, RegistryAdmin |"

        Design: Corner/rbac/rbac_absent_or_unknown_role_header_is_unauthorized
        """
        product = get_success_data(api.get_product(one_product["id"], COMPLIANCE_ANALYST))

        assert product["id"] == one_product["id"]
        assert product["sku"] == "SKU-RB2"

    def test_even_the_clock_endpoint_checks_the_header(self, api, one_product):
        """The clock surface declares a role of its own, so it is not exempt.

        PRD: "Set the server's logical clock to the supplied `current_utc` and return an object containing `current_utc` and `previous_utc`; no stored entity is modified, and every later window, deadline and stamp reads the new instant. | RegistryAdmin |"
        PRD: "(1) the `X-User-Role` header is absent or is not one of the six declared roles → `ERR_UNAUTHORIZED`;"

        Design: Corner/rbac/rbac_absent_or_unknown_role_header_is_unauthorized
        """
        response = api.set_clock(DEFAULT_CLOCK, headers_without_role())

        validate_error(response, ERR_UNAUTHORIZED, 403)


# ─────────────────────────────────────────────────────────────────────────────
# 3 — the one entity-backed role: row scoping and action scoping
# ─────────────────────────────────────────────────────────────────────────────


class TestSupplierPortalUserIsRowScoped:
    """The portal's authority follows the rows it owns, not the endpoint."""

    def test_portal_cannot_declare_on_another_suppliers_material(self, api, portal):
        """RM-S belongs to Southbay while the caller's `X-User-ID` is Northgate's id.

        PRD: "Concretely, when a `SupplierPortalUser` files a disclosure response on a material or declares a chemical present in a material, the material's `supplier_id` must equal the caller's `X-User-ID`, and a mismatch is refused with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/rbac_supplier_portal_user_cannot_reach_other_suppliers_materials_or_product_data
        """
        response = api.create_material_chemical(
            portal["mat_s"]["id"],
            f.material_chemical_payload(portal["chemical"]["id"], 12.0),
            portal["headers"],
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_portal_may_not_raise_a_data_request(self, api, portal):
        """The portal shares the disclosure surface but not the REQUEST action: raising
        a request belongs to the ComplianceAnalyst.

        PRD: "It may only file disclosure responses and declare chemical content for materials it ships, and it may read only supplier-facing resources — it can see no product, assessment, determination, notice or settlement at all."
        PRD: "A `ComplianceAnalyst` opens the process by requesting data, taking the material `NOT_REQUESTED → REQUESTED` and stamping `data_request_sent_at` with the current logical clock."
        PRD: "(2) the caller's role is not among the roles the target endpoint authorises → `ERR_UNAUTHORIZED`;"

        Design: Corner/rbac/rbac_supplier_portal_user_cannot_reach_other_suppliers_materials_or_product_data
        """
        response = api.material_disclosure(
            portal["mat_n"]["id"], f.action_payload("REQUEST"), portal["headers"]
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_portal_can_see_no_product_at_all(self, api, portal):
        """Product reads are closed to the portal even though five other roles hold them.

        PRD: "It may only file disclosure responses and declare chemical content for materials it ships, and it may read only supplier-facing resources — it can see no product, assessment, determination, notice or settlement at all."
        PRD: "Read one product including both state dimensions and the derived counters `open_notice_count`, `accrued_penalty_cents` and `total_listed_chemical_load_ug`. | ComplianceAnalyst, ToxicologyReviewer, RegulatoryCounsel, LabelingSpecialist, RegistryAdmin |"

        Design: Corner/rbac/rbac_supplier_portal_user_cannot_reach_other_suppliers_materials_or_product_data
        """
        response = api.get_product(portal["product"]["id"], portal["headers"])

        validate_error(response, ERR_UNAUTHORIZED, 403)

    def test_the_identical_declaration_succeeds_on_its_own_material(self, api, portal):
        """Same endpoint, same payload, own row: the write is accepted and the new link
        starts SUPPLIER_DECLARED / DECLARED.

        PRD: "Concretely, when a `SupplierPortalUser` files a disclosure response on a material or declares a chemical present in a material, the material's `supplier_id` must equal the caller's `X-User-ID`, and a mismatch is refused with `ERR_UNAUTHORIZED`."
        PRD: "Declare a listed chemical present in this material from `chemical_id` and `declared_concentration_ppm`; the material and chemical pair is unique, `measurement_basis` starts at `SUPPLIER_DECLARED` and `status` at `DECLARED`. | ComplianceAnalyst, SupplierPortalUser |"

        Design: Corner/rbac/rbac_supplier_portal_user_cannot_reach_other_suppliers_materials_or_product_data
        """
        response = api.create_material_chemical(
            portal["mat_n"]["id"],
            f.material_chemical_payload(portal["chemical"]["id"], 12.0),
            portal["headers"],
        )

        link = get_success_data(response, 201)
        assert_concentration(link["declared_concentration_ppm"], 12.0)
        assert link["measurement_basis"] == BASIS_SUPPLIER_DECLARED
        assert_status(link, LINK_STATUS_DECLARED)

    def test_portal_files_the_disclosure_response_it_owes(self, api, portal):
        """Filing the response is exactly what the portal exists for, and it stamps
        `data_received_at` from the logical clock.

        PRD: "Recording a response requires `response_completeness`, and its value forks the outcome: `COMPLETE` takes the material `REQUESTED → RECEIVED`, while `INCOMPLETE` takes it `REQUESTED → INCOMPLETE`."
        PRD: "Both stamp `data_received_at` with the current logical clock, and both may be filed either by the supplier itself acting as a `SupplierPortalUser` — in which case the caller's `X-User-ID` must equal the material's `supplier_id` — or transcribed by a `ComplianceAnalyst`."

        Design: Corner/rbac/rbac_supplier_portal_user_cannot_reach_other_suppliers_materials_or_product_data
        """
        material = get_success_data(
            api.material_disclosure(
                portal["mat_n"]["id"],
                f.record_response_action(COMPLETENESS_COMPLETE),
                portal["headers"],
            )
        )

        assert material["disclosure_status"] == DISCLOSURE_RECEIVED
        assert_instant(material["data_received_at"], DEFAULT_CLOCK, "data_received_at")

    def test_the_denied_cross_supplier_write_left_no_row(self, api, portal):
        """A refusal is not a partial write: Southbay's material still has no links.

        PRD: "Concretely, when a `SupplierPortalUser` files a disclosure response on a material or declares a chemical present in a material, the material's `supplier_id` must equal the caller's `X-User-ID`, and a mismatch is refused with `ERR_UNAUTHORIZED`."
        PRD: "`total_count` (the number of rows matching the filters before the page window is applied)"

        Design: Corner/rbac/rbac_supplier_portal_user_cannot_reach_other_suppliers_materials_or_product_data
        """
        validate_error(
            api.create_material_chemical(
                portal["mat_s"]["id"],
                f.material_chemical_payload(portal["chemical"]["id"], 12.0),
                portal["headers"],
            ),
            ERR_UNAUTHORIZED,
            403,
        )

        assert _link_count(api, portal["mat_s"]["id"]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4 — shared endpoints, unshared actions
# ─────────────────────────────────────────────────────────────────────────────


def _to_peer_reviewed(api, assessment_id):
    return get_success_data(
        _move_assessment(api, assessment_id, "PEER_REVIEW", TOXICOLOGY_REVIEWER)
    )


def _to_final(api, assessment_id):
    _to_peer_reviewed(api, assessment_id)
    return get_success_data(
        _move_assessment(api, assessment_id, "FINALIZE", TOXICOLOGY_REVIEWER)
    )


class TestSharedTransitionEndpointsAreActionScoped:
    """Both roles hold the endpoint; the actions on it are split between them."""

    def test_submit_is_the_analysts_action_on_a_shared_endpoint(self, api, submitted):
        """SUBMIT is the ComplianceAnalyst's half of the assessment transition surface.

        PRD: "A `ComplianceAnalyst` submits, taking the assessment `DRAFT → SUBMITTED`; submission recomputes `daily_exposure_ug`, `margin_ratio`, `result` and `contribution_count` from current data and stamps `submitted_by_user_id` with the acting `X-User-ID`."
        PRD: "Peer-review lifecycle by `action`: SUBMIT, PEER_REVIEW, REJECT, REOPEN or FINALIZE, with optional `review_note`; review and finalization require a reviewer other than the submitter. | ComplianceAnalyst, ToxicologyReviewer |"

        Design: Corner/rbac/rbac_shared_transition_endpoints_are_action_scoped_and_reject_the_wrong_role
        """
        assessment = _read_assessment(api, submitted["assessment"]["id"])

        assert_status(assessment, ASSESSMENT_SUBMITTED)
        assert assessment["submitted_by_user_id"] == CA_1

    def test_analyst_cannot_peer_review(self, api, submitted):
        """PEER_REVIEW is ToxicologyReviewer work even on an endpoint the analyst may
        otherwise call, and the refusal leaves the status alone.

        PRD: "Peer review takes the assessment `SUBMITTED → PEER_REVIEWED` and stamps `reviewed_by_user_id` with the acting `X-User-ID`; it is refused with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals the assessment's `submitted_by_user_id`."
        PRD: "Peer-review lifecycle by `action`: SUBMIT, PEER_REVIEW, REJECT, REOPEN or FINALIZE, with optional `review_note`; review and finalization require a reviewer other than the submitter. | ComplianceAnalyst, ToxicologyReviewer |"

        Design: Corner/rbac/rbac_shared_transition_endpoints_are_action_scoped_and_reject_the_wrong_role
        """
        response = _move_assessment(
            api, submitted["assessment"]["id"], "PEER_REVIEW", COMPLIANCE_ANALYST
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_status(
            _read_assessment(api, submitted["assessment"]["id"]), ASSESSMENT_SUBMITTED
        )

    def test_toxicology_reviewer_peer_reviews_the_same_call(self, api, submitted):
        """The identical action from the right role is accepted and stamps the reviewer.

        PRD: "Peer review takes the assessment `SUBMITTED → PEER_REVIEWED` and stamps `reviewed_by_user_id` with the acting `X-User-ID`; it is refused with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals the assessment's `submitted_by_user_id`."

        Design: Corner/rbac/rbac_shared_transition_endpoints_are_action_scoped_and_reject_the_wrong_role
        """
        assessment = _to_peer_reviewed(api, submitted["assessment"]["id"])

        assert_status(assessment, ASSESSMENT_PEER_REVIEWED)
        assert assessment["reviewed_by_user_id"] == TOX_1

    def test_analyst_cannot_finalize_either(self, api, submitted):
        """Finalization is the reviewer's action, so the analyst is refused from
        PEER_REVIEWED as well.

        PRD: "Finalization is performed by a `ToxicologyReviewer` and is reachable from two states with the same effect."

        Design: Corner/rbac/rbac_shared_transition_endpoints_are_action_scoped_and_reject_the_wrong_role
        """
        _to_peer_reviewed(api, submitted["assessment"]["id"])

        response = _move_assessment(
            api, submitted["assessment"]["id"], "FINALIZE", COMPLIANCE_ANALYST
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_status(
            _read_assessment(api, submitted["assessment"]["id"]),
            ASSESSMENT_PEER_REVIEWED,
        )

    def test_toxicology_reviewer_finalizes_with_the_recomputed_verdict(
        self, api, submitted
    ):
        """800.0 ppm x 0.25 g x 0.5 x 1.00 x 1.0 = 100.000 ug/day against a 6.4 ug/day
        NSRL, so the margin is 15.6250 and the verdict is at or above.

        PRD: "Otherwise the server multiplies together five factors — the effective concentration, the component's `quantity_grams_per_unit`, the component's `contact_factor`, the absorption factor for the assessment's `route`, and the assessment's `uses_per_day` — and rounds that product half up to three decimal places, giving one per-component contribution."
        PRD: "The absorption factors are 1.00 for the `ORAL` route, 0.10 for the `DERMAL` route and 0.25 for the `INHALATION` route."
        PRD: "Otherwise `margin_ratio` is `daily_exposure_ug` divided by `safe_harbor_level_ug_per_day`, rounded half up to four decimal places, and `result` is `AT_OR_ABOVE_SAFE_HARBOR` when `daily_exposure_ug` is greater than or equal to the level and `BELOW_SAFE_HARBOR` when it is strictly less."
        PRD: "Both arms carry exactly the same side-effect set: `daily_exposure_ug`, `margin_ratio`, `result` and `contribution_count` are recomputed one final time, `finalized_at` is stamped with the current logical clock, any other assessment of the same product and chemical whose status is `FINAL` transitions `FINAL → SUPERSEDED`, and `compliance_posture` is recomputed."

        Design: Corner/rbac/rbac_shared_transition_endpoints_are_action_scoped_and_reject_the_wrong_role
        """
        assessment = _to_final(api, submitted["assessment"]["id"])

        assert_status(assessment, ASSESSMENT_FINAL)
        assert_exposure(assessment["daily_exposure_ug"], 100.000)
        assert_margin(assessment["margin_ratio"], 15.6250)
        assert assessment["result"] == RESULT_AT_OR_ABOVE
        assert_instant(assessment["finalized_at"], DEFAULT_CLOCK, "finalized_at")

    def test_regulatory_counsel_cannot_submit_a_determination_for_approval(
        self, api, submitted
    ):
        """SUBMIT_FOR_APPROVAL belongs to the LabelingSpecialist even though counsel
        shares the determination transition surface.

        PRD: "A `LabelingSpecialist` submits for approval, taking the determination `DRAFT → PENDING_APPROVAL`."
        PRD: "Approval lifecycle by `action`: SUBMIT_FOR_APPROVAL, RETURN_FOR_REVISION, APPROVE or REVOKE, with optional `review_note`; approval requires an approver other than the preparer. | LabelingSpecialist, RegulatoryCounsel |"

        Design: Corner/rbac/rbac_shared_transition_endpoints_are_action_scoped_and_reject_the_wrong_role
        """
        _to_final(api, submitted["assessment"]["id"])
        determination = make_determination(
            api, submitted["product"]["id"], submitted["assessment"]["id"]
        )

        response = _move_determination(
            api, determination["id"], "SUBMIT_FOR_APPROVAL", REGULATORY_COUNSEL
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_status(
            _read_determination(api, determination["id"]), DETERMINATION_DRAFT
        )

    def test_labeling_specialist_may_submit_for_approval_but_not_approve(
        self, api, submitted
    ):
        """The preparer's role moves the determination to PENDING_APPROVAL and stops
        there: APPROVE is counsel's action.

        PRD: "A `LabelingSpecialist` submits for approval, taking the determination `DRAFT → PENDING_APPROVAL`."
        PRD: "Approval, also by a `RegulatoryCounsel`, takes it `PENDING_APPROVAL → APPROVED` and requires two things beyond the state: the acting `X-User-ID` must differ from `prepared_by_user_id`, otherwise the request is refused with `ERR_SEGREGATION_OF_DUTIES`, and the assessment named by `assessment_id` must still be in status `FINAL`."

        Design: Corner/rbac/rbac_shared_transition_endpoints_are_action_scoped_and_reject_the_wrong_role
        """
        _to_final(api, submitted["assessment"]["id"])
        determination = make_determination(
            api, submitted["product"]["id"], submitted["assessment"]["id"]
        )

        pending = get_success_data(
            _move_determination(
                api, determination["id"], "SUBMIT_FOR_APPROVAL", LABELING_SPECIALIST
            )
        )
        assert_status(pending, DETERMINATION_PENDING_APPROVAL)

        response = _move_determination(
            api, determination["id"], "APPROVE", LABELING_SPECIALIST
        )

        validate_error(response, ERR_UNAUTHORIZED, 403)
        assert_status(
            _read_determination(api, determination["id"]),
            DETERMINATION_PENDING_APPROVAL,
        )

    def test_regulatory_counsel_approves_and_is_stamped(self, api, submitted):
        """The action that was refused for the specialist succeeds for counsel.

        PRD: "Approval, also by a `RegulatoryCounsel`, takes it `PENDING_APPROVAL → APPROVED` and requires two things beyond the state: the acting `X-User-ID` must differ from `prepared_by_user_id`, otherwise the request is refused with `ERR_SEGREGATION_OF_DUTIES`, and the assessment named by `assessment_id` must still be in status `FINAL`."

        Design: Corner/rbac/rbac_shared_transition_endpoints_are_action_scoped_and_reject_the_wrong_role
        """
        _to_final(api, submitted["assessment"]["id"])
        determination = make_determination(
            api, submitted["product"]["id"], submitted["assessment"]["id"]
        )
        get_success_data(
            _move_determination(
                api, determination["id"], "SUBMIT_FOR_APPROVAL", LABELING_SPECIALIST
            )
        )

        approved = get_success_data(
            _move_determination(api, determination["id"], "APPROVE", REGULATORY_COUNSEL)
        )

        assert_status(approved, DETERMINATION_APPROVED)
        assert approved["approved_by_user_id"] == RC_1


# ─────────────────────────────────────────────────────────────────────────────
# 5 — segregation of duties is keyed on the user id, not the role
# ─────────────────────────────────────────────────────────────────────────────


class TestSegregationOfDutiesBlocksTheIdentity:
    """The role check has already passed, so the refusal is a different error."""

    def test_the_submitting_user_id_is_recorded(self, api, dual_submitted):
        """The opaque operator id is stamped where the transition records an actor.

        PRD: "When `X-User-Role` is `RegistryAdmin`, `ComplianceAnalyst`, `ToxicologyReviewer`, `LabelingSpecialist` or `RegulatoryCounsel`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity: the server records it where a transition stamps an actor — as `submitted_by_user_id` and `reviewed_by_user_id` on an exposure assessment, as `prepared_by_user_id` and `approved_by_user_id` on a warning determination, as `implemented_by_user_id` on a placement, and as `proposed_by_user_id` and `executed_by_user_id` on a settlement — but it never compares that value against any entity's `id`."
        PRD: "A `ComplianceAnalyst` submits, taking the assessment `DRAFT → SUBMITTED`; submission recomputes `daily_exposure_ug`, `margin_ratio`, `result` and `contribution_count` from current data and stamps `submitted_by_user_id` with the acting `X-User-ID`."

        Design: Corner/rbac/rbac_segregation_of_duties_blocks_reviewer_and_approver_reuse
        """
        assessment = _read_assessment(api, dual_submitted["assessment"]["id"])

        assert assessment["submitted_by_user_id"] == DUAL_1
        assert_status(assessment, ASSESSMENT_SUBMITTED)

    def test_the_submitter_cannot_peer_review_even_wearing_the_reviewer_role(
        self, api, dual_submitted
    ):
        """dual_1 presents ToxicologyReviewer, which the endpoint allows, so the
        refusal is ERR_SEGREGATION_OF_DUTIES at 409 rather than ERR_UNAUTHORIZED.

        PRD: "The value is compared against the recorded actor of an earlier, incompatible step on the same row, never against an entity identifier."
        PRD: "Peer review takes the assessment `SUBMITTED → PEER_REVIEWED` and stamps `reviewed_by_user_id` with the acting `X-User-ID`; it is refused with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals the assessment's `submitted_by_user_id`."

        Design: Corner/rbac/rbac_segregation_of_duties_blocks_reviewer_and_approver_reuse
        """
        response = _move_assessment(
            api,
            dual_submitted["assessment"]["id"],
            "PEER_REVIEW",
            make_headers_for_role(ROLE_TOXICOLOGY_REVIEWER, DUAL_1),
        )

        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)
        assessment = _read_assessment(api, dual_submitted["assessment"]["id"])
        assert_status(assessment, ASSESSMENT_SUBMITTED)
        assert assessment["submitted_by_user_id"] == DUAL_1

    def test_the_same_role_under_a_different_user_id_succeeds(
        self, api, dual_submitted
    ):
        """Identical payload, identical role, different identity: the block was the
        identity and nothing else.

        PRD: "Peer review takes the assessment `SUBMITTED → PEER_REVIEWED` and stamps `reviewed_by_user_id` with the acting `X-User-ID`; it is refused with `ERR_SEGREGATION_OF_DUTIES` when the acting `X-User-ID` equals the assessment's `submitted_by_user_id`."

        Design: Corner/rbac/rbac_segregation_of_duties_blocks_reviewer_and_approver_reuse
        """
        validate_error(
            _move_assessment(
                api,
                dual_submitted["assessment"]["id"],
                "PEER_REVIEW",
                make_headers_for_role(ROLE_TOXICOLOGY_REVIEWER, DUAL_1),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )

        assessment = _to_peer_reviewed(api, dual_submitted["assessment"]["id"])

        assert_status(assessment, ASSESSMENT_PEER_REVIEWED)
        assert assessment["reviewed_by_user_id"] == TOX_1

    def test_finalization_proceeds_after_the_blocked_review(self, api, dual_submitted):
        """The refused attempt cost the assessment nothing: it still finalizes with the
        800.0 ppm exposure of 100.000 ug/day.

        PRD: "Otherwise the server multiplies together five factors — the effective concentration, the component's `quantity_grams_per_unit`, the component's `contact_factor`, the absorption factor for the assessment's `route`, and the assessment's `uses_per_day` — and rounds that product half up to three decimal places, giving one per-component contribution."
        PRD: "Both arms carry exactly the same side-effect set: `daily_exposure_ug`, `margin_ratio`, `result` and `contribution_count` are recomputed one final time, `finalized_at` is stamped with the current logical clock, any other assessment of the same product and chemical whose status is `FINAL` transitions `FINAL → SUPERSEDED`, and `compliance_posture` is recomputed."

        Design: Corner/rbac/rbac_segregation_of_duties_blocks_reviewer_and_approver_reuse
        """
        assessment = _to_final(api, dual_submitted["assessment"]["id"])

        assert_status(assessment, ASSESSMENT_FINAL)
        assert_exposure(assessment["daily_exposure_ug"], 100.000)

    def test_the_preparer_cannot_approve_even_wearing_counsel(
        self, api, dual_submitted
    ):
        """ls_1 prepared the determination, so ls_1 cannot approve it however the role
        header reads, and the approval stamp stays null.

        PRD: "The value is compared against the recorded actor of an earlier, incompatible step on the same row, never against an entity identifier."
        PRD: "Approval, also by a `RegulatoryCounsel`, takes it `PENDING_APPROVAL → APPROVED` and requires two things beyond the state: the acting `X-User-ID` must differ from `prepared_by_user_id`, otherwise the request is refused with `ERR_SEGREGATION_OF_DUTIES`, and the assessment named by `assessment_id` must still be in status `FINAL`."

        Design: Corner/rbac/rbac_segregation_of_duties_blocks_reviewer_and_approver_reuse
        """
        _to_final(api, dual_submitted["assessment"]["id"])
        determination = make_determination(
            api, dual_submitted["product"]["id"], dual_submitted["assessment"]["id"]
        )
        assert determination["prepared_by_user_id"] == LS_1
        assert determination["decision"] == DECISION_WARNING_REQUIRED
        get_success_data(
            _move_determination(
                api, determination["id"], "SUBMIT_FOR_APPROVAL", LABELING_SPECIALIST
            )
        )

        response = _move_determination(
            api,
            determination["id"],
            "APPROVE",
            make_headers_for_role(ROLE_REGULATORY_COUNSEL, LS_1),
        )

        validate_error(response, ERR_SEGREGATION_OF_DUTIES, 409)
        after = _read_determination(api, determination["id"])
        assert_status(after, DETERMINATION_PENDING_APPROVAL)
        assert after["approved_by_user_id"] is None

    def test_a_different_counsel_identity_approves(self, api, dual_submitted):
        """rc_1 holds the same role as the refused caller and is accepted.

        PRD: "Approval, also by a `RegulatoryCounsel`, takes it `PENDING_APPROVAL → APPROVED` and requires two things beyond the state: the acting `X-User-ID` must differ from `prepared_by_user_id`, otherwise the request is refused with `ERR_SEGREGATION_OF_DUTIES`, and the assessment named by `assessment_id` must still be in status `FINAL`."

        Design: Corner/rbac/rbac_segregation_of_duties_blocks_reviewer_and_approver_reuse
        """
        _to_final(api, dual_submitted["assessment"]["id"])
        determination = make_determination(
            api, dual_submitted["product"]["id"], dual_submitted["assessment"]["id"]
        )
        get_success_data(
            _move_determination(
                api, determination["id"], "SUBMIT_FOR_APPROVAL", LABELING_SPECIALIST
            )
        )
        validate_error(
            _move_determination(
                api,
                determination["id"],
                "APPROVE",
                make_headers_for_role(ROLE_REGULATORY_COUNSEL, LS_1),
            ),
            ERR_SEGREGATION_OF_DUTIES,
            409,
        )

        approved = get_success_data(
            _move_determination(api, determination["id"], "APPROVE", REGULATORY_COUNSEL)
        )

        assert_status(approved, DETERMINATION_APPROVED)
        assert approved["approved_by_user_id"] == RC_1
