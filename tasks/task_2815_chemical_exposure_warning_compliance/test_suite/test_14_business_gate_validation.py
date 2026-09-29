"""Layer 5 and Layer 7 refusals: submission gates, decision/evidence pairing,
placement channels, the bill-of-materials graph and determination uniqueness.

Every case in this file pairs a refusal with the neighbouring acceptance, so the
rule is shown to depend on the one condition under test and not on the fixture:
the identical request body succeeds once a component exists, once a
naturally-occurring claim is on file, once the decision matches the toxicology
record, once the channel is one the product actually sells through, once the
link sits behind an ACTIVE component, once the basis assessment reaches FINAL,
and once the predecessor determination is APPROVED rather than in flight.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_BASIS_ASSESSMENT_NOT_FINAL,
    ERR_CHANNEL_NOT_REQUIRED,
    ERR_EXPOSURE_ABOVE_SAFE_HARBOR,
    ERR_MATERIAL_CYCLE,
    ERR_NO_ACTIVE_COMPONENTS,
    ERR_NO_QUALIFYING_EXPOSURE,
    ERR_OPEN_DETERMINATION_EXISTS,
    ERR_REFORMULATION_LINK_MISMATCH,
    ERR_SUPPLIER_DATA_INCOMPLETE,
)
from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_exposure,
    assert_fields_null,
    assert_instant,
    assert_status,
    assert_warning_content,
)
from test_helpers.constants import (
    ASSESSMENT_DRAFT,
    ASSESSMENT_FINAL,
    ASSESSMENT_PEER_REVIEWED,
    ASSESSMENT_SUBMITTED,
    ASSESSMENT_SUPERSEDED,
    BPA_NAME,
    CHANNEL_RETAIL,
    COMPONENT_STATUS_ACTIVE,
    COMPONENT_STATUS_REMOVED,
    DECISION_NO_WARNING_REQUIRED,
    DECISION_WARNING_REQUIRED,
    DEFAULT_CLOCK,
    DETERMINATION_APPROVED,
    DETERMINATION_DRAFT,
    DETERMINATION_PENDING_APPROVAL,
    DETERMINATION_SUPERSEDED,
    DISCLOSURE_REFUSED,
    METHOD_LAB_TESTED,
    METHOD_MODELED,
    PLACEMENT_PLANNED,
    PROJECT_PLANNED,
    REQUIRED_CHANNEL_CATALOG,
    REQUIRED_CHANNEL_INTERNET_POS,
    REQUIRED_CHANNEL_LABEL,
    RESULT_AT_OR_ABOVE,
    RESULT_BELOW,
    ROUTE_DERMAL,
    WARNING_TYPE_LONG,
    WARNING_TYPE_NONE,
)
from test_helpers.fixtures import (
    add_component,
    approve_determination,
    make_approved_determination,
    make_assessment,
    make_bpa,
    make_determination,
    make_final_assessment,
    make_material,
    make_product,
    make_product_with_component,
    make_reformulation_project,
    make_supplied_material,
    make_supplier,
    peer_review_assessment,
    remove_component,
    report_lab_result,
    set_clock,
    submit_assessment,
)
from test_helpers.test_users import (
    CA_1,
    COMPLIANCE_ANALYST,
    LABELING_SPECIALIST,
    LS_1,
    RC_1,
    TOXICOLOGY_REVIEWER,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _submit(api, assessment_id):
    """The raw SUBMIT response, so a refusal can be inspected."""
    return api.assessment_transition(
        assessment_id, f.action_payload("SUBMIT"), COMPLIANCE_ANALYST
    )


def _read_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, COMPLIANCE_ANALYST))


def _read_determination(api, determination_id):
    return get_success_data(
        api.get_determination(determination_id, LABELING_SPECIALIST)
    )


def _open_determination(api, product_id, assessment_id, decision):
    """The raw create response, always carrying a freshly read product version."""
    return api.create_determination(
        f.determination_payload(
            product_id,
            assessment_id,
            decision,
            api.product_version(product_id, LABELING_SPECIALIST),
        ),
        LABELING_SPECIALIST,
    )


def _determination_rows(api, product_id):
    rows, meta = validate_paginated(
        api.list_determinations(LABELING_SPECIALIST, f.page(product_id=product_id))
    )
    return rows, meta


def _placement_count(api):
    _, meta = validate_paginated(api.list_placements(LABELING_SPECIALIST))
    return meta["total_count"]


def _material_count(api):
    _, meta = validate_paginated(api.list_materials(COMPLIANCE_ANALYST))
    return meta["total_count"]


def _project_count(api):
    _, meta = validate_paginated(api.list_reformulation_projects(COMPLIANCE_ANALYST))
    return meta["total_count"]


def _read_material(api, material_id):
    return get_success_data(api.get_material(material_id, COMPLIANCE_ANALYST))


def _staged(api, sku, declared_concentration_ppm=60.0, **product_overrides):
    """A LISTED-Bisphenol-A product carrying exactly one ACTIVE component.

    The component is 0.25 g/unit at contact_factor 0.5, so a DERMAL modelled
    assessment at one use per day reads 60.0 ppm as 0.750 ug/day.
    """
    chemical = make_bpa(api)
    overrides = {"annual_units": 1000}
    overrides.update(product_overrides)
    bundle = make_product_with_component(
        api,
        chemical["id"],
        sku=sku,
        declared_concentration_ppm=declared_concentration_ppm,
        product_overrides=overrides,
    )
    bundle["chemical"] = chemical
    return bundle


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def clocked(api):
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def componentless(api, clocked):
    """SKU-NOCOMP has no components at all; RM-100 waits alongside it."""
    chemical = make_bpa(api)
    supplied = make_supplied_material(api, chemical["id"], 60.0)
    product = make_product(
        api, "SKU-NOCOMP", product_name="Componentless", annual_units=1000
    )
    assessment = make_assessment(
        api, product["id"], chemical["id"], METHOD_MODELED, ROUTE_DERMAL, 1.0
    )
    return {
        "chemical": chemical,
        "material": supplied["material"],
        "product": product,
        "assessment": assessment,
    }


@pytest.fixture
def refused_disclosure(api, clocked):
    """SKU-REF's only material refused to disclose but was measured anyway.

    ``naturally_occurring_claim`` is false on create, so the laboratory-method
    submission has nothing to excuse the refusal with.
    """
    chemical = make_bpa(api)
    supplied = make_supplied_material(
        api,
        chemical["id"],
        60.0,
        supplier_legal_name="Silent Supply Co",
        disclosure_status=DISCLOSURE_REFUSED,
        naturally_occurring_claim=False,
    )
    report_lab_result(
        api, supplied["link"]["id"], 60.0, 1.0, lab_name="Harbor Analytical"
    )
    product = make_product(
        api, "SKU-REF", product_name="Refused Disclosure Widget", annual_units=1000
    )
    add_component(api, product["id"], supplied["material"]["id"], 0.25, 0.5)
    assessment = make_assessment(
        api, product["id"], chemical["id"], METHOD_LAB_TESTED, ROUTE_DERMAL, 1.0
    )
    return {
        "chemical": chemical,
        "material": supplied["material"],
        "link": supplied["link"],
        "product": product,
        "assessment": assessment,
    }


@pytest.fixture
def above_safe_harbor(api, clocked):
    """SKU-CONTRA carries a FINAL assessment at 0.750 ug/day, AT_OR_ABOVE."""
    bundle = _staged(api, "SKU-CONTRA", product_name="Contradiction Widget")
    bundle["assessment"] = make_final_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        1.0,
    )
    return bundle


@pytest.fixture
def below_safe_harbor(api, clocked):
    """SKU-CLEAN carries a FINAL assessment at 0.250 ug/day, BELOW."""
    bundle = _staged(
        api, "SKU-CLEAN", declared_concentration_ppm=40.0, product_name="Clean Widget"
    )
    bundle["assessment"] = make_final_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        0.5,
    )
    return bundle


@pytest.fixture
def retail_only(api, clocked):
    """SKU-RETONLY sells through RETAIL alone and holds an APPROVED warning."""
    bundle = _staged(
        api,
        "SKU-RETONLY",
        product_name="Retail Only Widget",
        distribution_channels=f.channels(CHANNEL_RETAIL),
    )
    assessment = make_final_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        1.0,
    )
    bundle["assessment"] = assessment
    bundle["determination"] = make_approved_determination(
        api, bundle["product"]["id"], assessment["id"], DECISION_WARNING_REQUIRED
    )
    return bundle


@pytest.fixture
def material_chain(api, clocked):
    """RM-L0 <- RM-L1 <- RM-L2 <- RM-L3 <- RM-L4, each child at fraction 0.5."""
    supplier = make_supplier(api, "Northgate Polymers")
    chain = [make_material(api, "RM-L0", supplier["id"])]
    for level in range(1, 5):
        chain.append(
            make_material(
                api,
                f"RM-L{level}",
                supplier["id"],
                parent_material_id=chain[-1]["id"],
                parent_mass_fraction=0.5,
            )
        )
    return {"supplier": supplier, "chain": chain}


@pytest.fixture
def reformulation_candidates(api, clocked):
    """SKU-REFORM's RM-100 sits behind its component; RM-OFF sits nowhere."""
    bundle = _staged(api, "SKU-REFORM", product_name="Reformulation Widget")
    off = make_supplied_material(
        api,
        bundle["chemical"]["id"],
        60.0,
        material_code="RM-OFF",
        supplier_id=bundle["supplier_id"],
    )
    bundle["off_link"] = off["link"]
    bundle["off_material"] = off["material"]
    bundle["assessment"] = make_final_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        1.0,
    )
    return bundle


@pytest.fixture
def peer_reviewed_basis(api, clocked):
    """Two products whose candidate basis assessment stops short of FINAL.

    SKU-BASIS also holds a genuinely FINAL qualifying assessment, so the layer-5
    decision/evidence rules are both satisfied there and the layer-7 basis rule
    is the only rule left that can fire.  SKU-BASIS-2 holds nothing but the
    PEER_REVIEWED row, which is what puts the two layers in conflict.
    """
    bundle = _staged(api, "SKU-BASIS", product_name="Basis Widget")
    bundle["final_assessment"] = make_final_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        1.0,
    )
    pending = make_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        1.0,
    )
    submit_assessment(api, pending["id"])
    bundle["assessment"] = peer_review_assessment(api, pending["id"])

    bare = make_product(
        api, "SKU-BASIS-2", product_name="Bare Basis Widget", annual_units=1000
    )
    add_component(api, bare["id"], bundle["material"]["id"], 0.25, 0.5)
    bare_assessment = make_assessment(
        api, bare["id"], bundle["chemical"]["id"], METHOD_MODELED, ROUTE_DERMAL, 1.0
    )
    submit_assessment(api, bare_assessment["id"])
    bundle["bare_product"] = bare
    bundle["bare_assessment"] = peer_review_assessment(api, bare_assessment["id"])
    return bundle


@pytest.fixture
def in_flight_determination(api, clocked):
    """SKU-SUCC already holds one determination sitting in DRAFT."""
    bundle = _staged(api, "SKU-SUCC", product_name="Successor Widget")
    assessment = make_final_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        1.0,
    )
    bundle["assessment"] = assessment
    bundle["determination"] = make_determination(
        api, bundle["product"]["id"], assessment["id"], DECISION_WARNING_REQUIRED
    )
    return bundle


# ─────────────────────────────────────────────────────────────────────────────
# Priority 50 — submission over an empty component set
# ─────────────────────────────────────────────────────────────────────────────


class TestSubmitNeedsAnActiveComponent:
    """Staging a draft on a bare product is allowed; submitting it is not."""

    def test_submit_is_refused_while_the_product_has_no_active_components(
        self, api, componentless
    ):
        """The draft opens happily and reads zero, then SUBMIT is refused.

        PRD: "A newly created assessment has `status` `DRAFT`, `submitted_by_user_id`, `reviewed_by_user_id` and `finalized_at` all null, `rejection_count` 0 and `review_note` null; its numbers are computed immediately from the product's active components."

        PRD: "First, if the product has zero components in status `ACTIVE` the submission is refused with `ERR_NO_ACTIVE_COMPONENTS`, because the exposure sum would be over the empty set."

        Design: Corner/validations/val_assessment_submit_requires_active_component
        """
        assessment = componentless["assessment"]
        assert_status(assessment, ASSESSMENT_DRAFT)
        assert_fields_null(
            assessment,
            ["submitted_by_user_id", "reviewed_by_user_id", "finalized_at"],
        )
        assert assessment["rejection_count"] == 0
        assert_exposure(assessment["daily_exposure_ug"], 0.0)
        assert assessment["contribution_count"] == 0, (
            "A product with no components contributes nothing, so "
            f"contribution_count must be 0, got {assessment['contribution_count']!r}"
        )

        refusal = _submit(api, assessment["id"])
        validate_error(refusal, ERR_NO_ACTIVE_COMPONENTS, 409)
        assert_status(_read_assessment(api, assessment["id"]), ASSESSMENT_DRAFT)

    def test_adding_one_component_makes_the_identical_submit_succeed(
        self, api, componentless
    ):
        """The same call, unchanged, goes through once one ACTIVE component exists.

        PRD: "First, if the product has zero components in status `ACTIVE` the submission is refused with `ERR_NO_ACTIVE_COMPONENTS`, because the exposure sum would be over the empty set."

        PRD: "A `ComplianceAnalyst` submits, taking the assessment `DRAFT → SUBMITTED`; submission recomputes `daily_exposure_ug`, `margin_ratio`, `result` and `contribution_count` from current data and stamps `submitted_by_user_id` with the acting `X-User-ID`."

        Design: Corner/validations/val_assessment_submit_requires_active_component
        """
        assessment = componentless["assessment"]
        validate_error(_submit(api, assessment["id"]), ERR_NO_ACTIVE_COMPONENTS, 409)

        component = add_component(
            api,
            componentless["product"]["id"],
            componentless["material"]["id"],
            0.25,
            0.5,
        )
        assert_status(component, COMPONENT_STATUS_ACTIVE)

        submitted = get_success_data(_submit(api, assessment["id"]))
        assert_status(submitted, ASSESSMENT_SUBMITTED)
        assert_assessment_verdict(submitted, 0.750, 1.5000, RESULT_AT_OR_ABOVE, 1)
        assert submitted["submitted_by_user_id"] == CA_1, (
            "Submission stamps the acting X-User-ID, expected "
            f"{CA_1!r}, got {submitted['submitted_by_user_id']!r}"
        )

    def test_removing_the_last_component_re_arms_the_refusal(
        self, api, componentless
    ):
        """A REMOVEd component stops counting, so the next draft cannot submit.

        PRD: "Removing a component takes it `ACTIVE → REMOVED` and excludes it from every exposure and load calculation from that instant on; a product whose last `ACTIVE` component is removed falls back to `EXPOSURE_UNKNOWN` through clause 2 of the posture ladder."

        PRD: "First, if the product has zero components in status `ACTIVE` the submission is refused with `ERR_NO_ACTIVE_COMPONENTS`, because the exposure sum would be over the empty set."

        Design: Corner/validations/val_assessment_submit_requires_active_component
        """
        product_id = componentless["product"]["id"]
        component = add_component(
            api, product_id, componentless["material"]["id"], 0.25, 0.5
        )
        get_success_data(_submit(api, componentless["assessment"]["id"]))

        removed = remove_component(api, component["id"])
        assert_status(removed, COMPONENT_STATUS_REMOVED)

        successor = make_assessment(
            api,
            product_id,
            componentless["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_DERMAL,
            1.0,
        )
        assert successor["contribution_count"] == 0, (
            "The removed component is excluded from every calculation from that "
            f"instant on, got contribution_count {successor['contribution_count']!r}"
        )
        validate_error(_submit(api, successor["id"]), ERR_NO_ACTIVE_COMPONENTS, 409)


# ─────────────────────────────────────────────────────────────────────────────
# Priority 52 — a refused disclosure under the laboratory method
# ─────────────────────────────────────────────────────────────────────────────


class TestLabTestedSubmitAndRefusedDisclosure:
    """The gate bites only while `naturally_occurring_claim` is false."""

    def test_a_refused_disclosure_without_a_claim_blocks_the_submission(
        self, api, refused_disclosure
    ):
        """Measured data is on file, but the unexplained refusal still stops SUBMIT.

        PRD: "Third, if the assessment's `method` is `LAB_TESTED` and some contributing material has `disclosure_status` `REFUSED` while its `naturally_occurring_claim` is false, the submission is refused with `ERR_SUPPLIER_DATA_INCOMPLETE`; a naturally-occurring claim on file excuses the refusal."

        Design: Corner/validations/val_lab_tested_submit_with_refused_disclosure_rejected
        """
        material = _read_material(api, refused_disclosure["material"]["id"])
        assert material["disclosure_status"] == DISCLOSURE_REFUSED
        assert material["naturally_occurring_claim"] is False

        refusal = _submit(api, refused_disclosure["assessment"]["id"])
        validate_error(refusal, ERR_SUPPLIER_DATA_INCOMPLETE, 409)
        assert_status(
            _read_assessment(api, refused_disclosure["assessment"]["id"]),
            ASSESSMENT_DRAFT,
        )

    def test_the_naturally_occurring_claim_excuses_the_same_refusal(
        self, api, refused_disclosure
    ):
        """Flipping one flag on the material lets the identical SUBMIT through.

        PRD: "Third, if the assessment's `method` is `LAB_TESTED` and some contributing material has `disclosure_status` `REFUSED` while its `naturally_occurring_claim` is false, the submission is refused with `ERR_SUPPLIER_DATA_INCOMPLETE`; a naturally-occurring claim on file excuses the refusal."

        Design: Corner/validations/val_lab_tested_submit_with_refused_disclosure_rejected
        """
        assessment_id = refused_disclosure["assessment"]["id"]
        validate_error(_submit(api, assessment_id), ERR_SUPPLIER_DATA_INCOMPLETE, 409)

        patched = get_success_data(
            api.patch_material(
                refused_disclosure["material"]["id"],
                {"naturally_occurring_claim": True},
                COMPLIANCE_ANALYST,
            )
        )
        assert patched["naturally_occurring_claim"] is True
        assert patched["disclosure_status"] == DISCLOSURE_REFUSED, (
            "The claim excuses the refusal, it does not retract it; expected "
            f"{DISCLOSURE_REFUSED}, got {patched['disclosure_status']!r}"
        )

        submitted = get_success_data(_submit(api, assessment_id))
        assert_status(submitted, ASSESSMENT_SUBMITTED)

    def test_the_measured_value_survives_the_refusal_untouched(
        self, api, refused_disclosure
    ):
        """No worst-case substitution: the laboratory variant ignores the gap.

        PRD: "Under the **laboratory** variant the own contribution is decided differently, and `disclosure_status` is ignored entirely on the principle that measured data supersedes supplier gaps."

        Design: Corner/validations/val_lab_tested_submit_with_refused_disclosure_rejected
        """
        get_success_data(
            api.patch_material(
                refused_disclosure["material"]["id"],
                {"naturally_occurring_claim": True},
                COMPLIANCE_ANALYST,
            )
        )
        submitted = get_success_data(
            _submit(api, refused_disclosure["assessment"]["id"])
        )
        assert_assessment_verdict(submitted, 0.750, 1.5000, RESULT_AT_OR_ABOVE, 1)
        assert submitted["daily_exposure_ug"] != pytest.approx(3.125), (
            "3.125 would mean the modelled worst-case substitution had been "
            "applied to a laboratory-method assessment"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Priorities 53 and 54 — the decision must match the toxicology record
# ─────────────────────────────────────────────────────────────────────────────


class TestNoWarningCannotContradictTheEvidence:
    """A qualifying FINAL assessment forbids the no-warning position."""

    def test_no_warning_required_is_refused_while_an_exposure_qualifies(
        self, api, above_safe_harbor
    ):
        """The decision cannot deny an AT_OR_ABOVE_SAFE_HARBOR FINAL assessment.

        PRD: "A determination created with `decision` `NO_WARNING_REQUIRED` while the product has at least one `FINAL` assessment whose `result` is `AT_OR_ABOVE_SAFE_HARBOR` or `NO_SAFE_HARBOR` is refused with `ERR_EXPOSURE_ABOVE_SAFE_HARBOR`."

        Design: Corner/validations/val_no_warning_decision_with_qualifying_exposure_rejected
        """
        assert_assessment_verdict(
            above_safe_harbor["assessment"], 0.750, 1.5000, RESULT_AT_OR_ABOVE, 1
        )

        refusal = _open_determination(
            api,
            above_safe_harbor["product"]["id"],
            above_safe_harbor["assessment"]["id"],
            DECISION_NO_WARNING_REQUIRED,
        )
        validate_error(refusal, ERR_EXPOSURE_ABOVE_SAFE_HARBOR, 409)

        _, meta = _determination_rows(api, above_safe_harbor["product"]["id"])
        assert meta["total_count"] == 0, (
            "A refused create must leave no WarningDetermination row behind, "
            f"found {meta['total_count']}"
        )

    def test_the_other_decision_on_the_identical_body_is_accepted(
        self, api, above_safe_harbor
    ):
        """WARNING_REQUIRED passes and derives the long form for one chemical.

        PRD: "The second step selects `warning_type`, which is one of `NONE`, `PRODUCT_SPECIFIC_LONG`, `PRODUCT_SPECIFIC_SHORT` or `OCCUPANCY`, from a three-way branch taken in this order: if the product's `occupancy_type` is anything other than `NONE`, the type is `OCCUPANCY`; otherwise, if the product's `label_area_sq_in` is strictly less than five square inches, the type is `PRODUCT_SPECIFIC_SHORT`, the abbreviated format available to small labels; otherwise the type is `PRODUCT_SPECIFIC_LONG`."

        PRD: "The third step fills `named_chemicals`, which holds at most one chemical name per harm class."

        PRD: "`LABEL` is included when the product's `distribution_channels` contains `RETAIL`; `CATALOG` when it contains `CATALOG`; `INTERNET_POS` when it contains `INTERNET`; and `POSTED_SIGN` is appended when the product's `occupancy_type` is anything other than `NONE`."

        Design: Corner/validations/val_no_warning_decision_with_qualifying_exposure_rejected
        """
        product_id = above_safe_harbor["product"]["id"]
        validate_error(
            _open_determination(
                api,
                product_id,
                above_safe_harbor["assessment"]["id"],
                DECISION_NO_WARNING_REQUIRED,
            ),
            ERR_EXPOSURE_ABOVE_SAFE_HARBOR,
            409,
        )

        determination = get_success_data(
            _open_determination(
                api,
                product_id,
                above_safe_harbor["assessment"]["id"],
                DECISION_WARNING_REQUIRED,
            )
        )
        assert determination["decision"] == DECISION_WARNING_REQUIRED
        assert_status(determination, DETERMINATION_DRAFT)
        assert determination["warning_type"] == WARNING_TYPE_LONG
        assert determination["named_chemicals"] == [BPA_NAME], (
            "One reproductive-class chemical qualifies, so exactly one name is "
            f"listed; got {determination['named_chemicals']!r}"
        )
        assert determination["required_channels"] == [REQUIRED_CHANNEL_LABEL], (
            "A RETAIL-only product requires the LABEL channel and nothing else, "
            f"got {determination['required_channels']!r}"
        )
        assert determination["prepared_by_user_id"] == LS_1


class TestWarningRequiredNeedsAQualifyingExposure:
    """The mirror image: nothing to name means nothing to warn about."""

    def test_warning_required_is_refused_when_every_final_result_is_below(
        self, api, below_safe_harbor
    ):
        """A lone BELOW_SAFE_HARBOR assessment cannot support a warning.

        PRD: "A determination created with `decision` `WARNING_REQUIRED` while the product has **no** `FINAL` assessment whose `result` is `AT_OR_ABOVE_SAFE_HARBOR` or `NO_SAFE_HARBOR` is refused with `ERR_NO_QUALIFYING_EXPOSURE`, because the named-chemical selector would have nothing to name."

        Design: Corner/validations/val_warning_required_without_qualifying_exposure_rejected
        """
        assert_assessment_verdict(
            below_safe_harbor["assessment"], 0.250, 0.5000, RESULT_BELOW, 1
        )

        refusal = _open_determination(
            api,
            below_safe_harbor["product"]["id"],
            below_safe_harbor["assessment"]["id"],
            DECISION_WARNING_REQUIRED,
        )
        validate_error(refusal, ERR_NO_QUALIFYING_EXPOSURE, 409)

    def test_the_accepted_no_warning_determination_writes_the_empty_position(
        self, api, below_safe_harbor
    ):
        """Nulls and empty arrays, not an empty-string warning.

        PRD: "When the `decision` is `NO_WARNING_REQUIRED` the computation stops here and writes the empty position: `warning_type` is `NONE`, `symbol_required` is false, `named_chemicals` is the empty array, `website_url` is null, `warning_text` is null, and `required_channels` is the empty array."

        Design: Corner/validations/val_warning_required_without_qualifying_exposure_rejected
        """
        product_id = below_safe_harbor["product"]["id"]
        validate_error(
            _open_determination(
                api,
                product_id,
                below_safe_harbor["assessment"]["id"],
                DECISION_WARNING_REQUIRED,
            ),
            ERR_NO_QUALIFYING_EXPOSURE,
            409,
        )

        determination = get_success_data(
            _open_determination(
                api,
                product_id,
                below_safe_harbor["assessment"]["id"],
                DECISION_NO_WARNING_REQUIRED,
            )
        )
        assert_warning_content(
            determination, WARNING_TYPE_NONE, False, [], None, None, []
        )
        assert determination["covered_channel_count"] == 0
        assert_status(determination, DETERMINATION_DRAFT)


# ─────────────────────────────────────────────────────────────────────────────
# Priority 57 — a placement channel the product does not sell through
# ─────────────────────────────────────────────────────────────────────────────


class TestPlacementChannelMustBeRequired:
    """The legal channel set is derived from the product, not a free enum."""

    def test_channels_outside_required_channels_are_refused(self, api, retail_only):
        """INTERNET_POS and CATALOG are both refused on a RETAIL-only product.

        PRD: "`LABEL` is included when the product's `distribution_channels` contains `RETAIL`; `CATALOG` when it contains `CATALOG`; `INTERNET_POS` when it contains `INTERNET`; and `POSTED_SIGN` is appended when the product's `occupancy_type` is anything other than `NONE`."

        PRD: "The channel must be a member of the determination's computed `required_channels`, otherwise the create is refused with `ERR_CHANNEL_NOT_REQUIRED`."

        Design: Corner/validations/val_placement_channel_not_required_rejected
        """
        determination = retail_only["determination"]
        assert determination["required_channels"] == [REQUIRED_CHANNEL_LABEL]
        assert_status(determination, DETERMINATION_APPROVED)

        internet = api.create_placement(
            determination["id"],
            f.placement_payload(
                REQUIRED_CHANNEL_INTERNET_POS,
                "2026-07-01T00:00:00Z",
                placement_detail="Product detail page, above add-to-cart",
                internet_display_position="ON_PRODUCT_PAGE",
            ),
            LABELING_SPECIALIST,
        )
        validate_error(internet, ERR_CHANNEL_NOT_REQUIRED, 422)

        catalog = api.create_placement(
            determination["id"],
            f.placement_payload(
                REQUIRED_CHANNEL_CATALOG,
                "2026-07-01T00:00:00Z",
                placement_detail="Fall catalogue page 42",
                catalog_page_ref="p42",
            ),
            LABELING_SPECIALIST,
        )
        validate_error(catalog, ERR_CHANNEL_NOT_REQUIRED, 422)

        assert _placement_count(api) == 0, (
            "Neither refused create may leave a WarningPlacement row behind"
        )

    def test_the_one_required_channel_is_accepted_but_covers_nothing_yet(
        self, api, retail_only
    ):
        """A PLANNED placement is a row, not yet coverage.

        PRD: "A newly created placement has `status` `PLANNED`, `implemented_by_user_id` null and `remediation_count` 0, and its creation recomputes the determination's `covered_channel_count` and the product's `compliance_posture`."

        PRD: "`covered_channel_count` is the number of distinct entries of `required_channels` for which at least one placement of this determination has a `status` of `IMPLEMENTED` or `VERIFIED` and an effective window that covers the current logical clock."

        Design: Corner/validations/val_placement_channel_not_required_rejected
        """
        determination = retail_only["determination"]
        placement = get_success_data(
            api.create_placement(
                determination["id"],
                f.placement_payload(
                    REQUIRED_CHANNEL_LABEL,
                    "2026-07-01T00:00:00Z",
                    placement_detail="Back panel, 6 pt bold",
                ),
                LABELING_SPECIALIST,
            )
        )
        assert_status(placement, PLACEMENT_PLANNED)
        assert_fields_null(placement, ["effective_to", "implemented_by_user_id"])
        assert placement["remediation_count"] == 0

        assert _read_determination(api, determination["id"])[
            "covered_channel_count"
        ] == 0, "A PLANNED placement does not yet cover its channel"


# ─────────────────────────────────────────────────────────────────────────────
# Layer 7 rule 4 — the depth ceiling and the two graph corners
# ─────────────────────────────────────────────────────────────────────────────


class TestBomDepthCeilingAndCycles:
    """One error covers the ceiling, self-parenting and descendant-parenting."""

    def test_a_five_material_chain_is_legal_at_every_depth(
        self, api, material_chain
    ):
        """Depths 0 through 4 are all derived from the parent chain, never supplied.

        PRD: "`bom_depth` is derived, never supplied: it is 0 for a material whose `parent_material_id` is null, and otherwise one more than its parent's `bom_depth`."

        PRD: "The largest permitted value is 4, so the tree can be at most five levels tall counting the root."

        Design: Corner/validations/val_bom_depth_ceiling_and_cycle_rejected
        """
        for depth, material in enumerate(material_chain["chain"]):
            stored = _read_material(api, material["id"])
            assert stored["bom_depth"] == depth, (
                f"{stored['material_code']} sits {depth} edges below the root, so "
                f"bom_depth must be {depth}, got {stored['bom_depth']!r}"
            )

    def test_a_sixth_level_is_refused_at_the_ceiling(self, api, material_chain):
        """A child of the depth-4 material would be depth 5, which is one too far.

        PRD: "The largest permitted value is 4, so the tree can be at most five levels tall counting the root."

        Design: Corner/validations/val_bom_depth_ceiling_and_cycle_rejected
        """
        deepest = material_chain["chain"][4]
        refusal = api.create_material(
            f.material_payload(
                "RM-L5",
                material_chain["supplier"]["id"],
                parent_material_id=deepest["id"],
                parent_mass_fraction=0.5,
            ),
            COMPLIANCE_ANALYST,
        )
        validate_error(refusal, ERR_MATERIAL_CYCLE, 422)
        assert _material_count(api) == 5, (
            "The refused create must not persist RM-L5, so the chain is still "
            "five materials long"
        )

    def test_self_parenting_and_descendant_parenting_are_the_same_refusal(
        self, api, material_chain
    ):
        """Naming yourself, or naming your own descendant, is a cycle either way.

        PRD: "The same error, `ERR_MATERIAL_CYCLE`, also covers the cycle case: naming the material itself as its own parent, or naming any material that is already one of its own descendants."

        Design: Corner/validations/val_bom_depth_ceiling_and_cycle_rejected
        """
        chain = material_chain["chain"]
        level_zero, level_one, level_two, level_three = (
            chain[0],
            chain[1],
            chain[2],
            chain[3],
        )

        itself = api.patch_material(
            level_two["id"],
            {"parent_material_id": level_two["id"], "parent_mass_fraction": 0.5},
            COMPLIANCE_ANALYST,
        )
        validate_error(itself, ERR_MATERIAL_CYCLE, 422)
        assert (
            _read_material(api, level_two["id"])["parent_material_id"]
            == level_one["id"]
        ), "The refused re-parent must leave RM-L2 pointing at RM-L1"

        descendant = api.patch_material(
            level_zero["id"],
            {"parent_material_id": level_three["id"], "parent_mass_fraction": 0.5},
            COMPLIANCE_ANALYST,
        )
        validate_error(descendant, ERR_MATERIAL_CYCLE, 422)
        assert _read_material(api, level_zero["id"])["parent_material_id"] is None, (
            "RM-L3 is a descendant of RM-L0, so the root keeps its null parent"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Layer 7 rule 5 — the reformulation link must sit behind an ACTIVE component
# ─────────────────────────────────────────────────────────────────────────────


class TestReformulationLinkMustSitInTheBom:
    """A matching chemical is not enough; the material must be in the product."""

    def test_a_link_on_a_material_outside_the_bom_is_refused(
        self, api, reformulation_candidates
    ):
        """RM-OFF carries the right chemical but sits in no product at all.

        PRD: "The link must be coherent, and an incoherent one is refused with `ERR_REFORMULATION_LINK_MISMATCH`: the referenced material-chemical link's own `chemical_id` must equal the project's `chemical_id`, and the material carrying that link must be the material of some component of the project's product in status `ACTIVE`."

        Design: Corner/validations/val_reformulation_link_material_outside_active_components_rejected
        """
        refusal = api.create_reformulation_project(
            f.reformulation_payload(
                reformulation_candidates["product"]["id"],
                reformulation_candidates["chemical"]["id"],
                reformulation_candidates["off_link"]["id"],
                5.0,
                "2026-09-01T00:00:00Z",
                "2026-12-01T00:00:00Z",
            ),
            COMPLIANCE_ANALYST,
        )
        validate_error(refusal, ERR_REFORMULATION_LINK_MISMATCH, 422)
        assert _project_count(api) == 0, (
            "A refused create must leave no ReformulationProject row behind"
        )

    def test_the_in_bom_link_on_the_identical_body_is_accepted(
        self, api, reformulation_candidates
    ):
        """Swapping to RM-100's link opens the project and captures its baseline.

        PRD: "`baseline_daily_exposure_ug` is the `daily_exposure_ug` of the newest assessment in status `FINAL` for the same product and chemical pair, where "newest" means ranked by `finalized_at` descending and then by `created_at` descending as the tie-break; when the product has no `FINAL` assessment for that chemical the baseline is 0."

        PRD: "`verified_daily_exposure_ug` and `reduction_pct` both start null and `status` starts `PLANNED`."

        Design: Corner/validations/val_reformulation_link_material_outside_active_components_rejected
        """
        validate_error(
            api.create_reformulation_project(
                f.reformulation_payload(
                    reformulation_candidates["product"]["id"],
                    reformulation_candidates["chemical"]["id"],
                    reformulation_candidates["off_link"]["id"],
                    5.0,
                    "2026-09-01T00:00:00Z",
                    "2026-12-01T00:00:00Z",
                ),
                COMPLIANCE_ANALYST,
            ),
            ERR_REFORMULATION_LINK_MISMATCH,
            422,
        )

        project = make_reformulation_project(
            api,
            reformulation_candidates["product"]["id"],
            reformulation_candidates["chemical"]["id"],
            reformulation_candidates["link"]["id"],
            5.0,
            "2026-09-01T00:00:00Z",
            "2026-12-01T00:00:00Z",
        )
        assert_status(project, PROJECT_PLANNED)
        assert project["target_concentration_ppm"] == pytest.approx(5.0)
        assert_fields_null(project, ["verified_daily_exposure_ug", "reduction_pct"])
        assert_exposure(project["baseline_daily_exposure_ug"], 0.750)
        assert _project_count(api) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Layer 7 rule 6 — the cited basis assessment must be FINAL
# ─────────────────────────────────────────────────────────────────────────────


class TestBasisAssessmentMustBeFinal:
    """The basis rule sits between the evidence rules and the uniqueness rule."""

    def test_a_non_final_basis_is_refused_with_the_evidence_already_in_place(
        self, api, peer_reviewed_basis
    ):
        """SKU-BASIS has a qualifying FINAL row, so only the basis rule can fire.

        PRD: "The cited assessment must belong to the named product and must be in status `FINAL` at create time; if it belongs to a different product or is in any other status, the create is refused with `ERR_BASIS_ASSESSMENT_NOT_FINAL`."

        Design: Corner/validations/val_determination_basis_assessment_not_final_rejected
        """
        assert_status(peer_reviewed_basis["assessment"], ASSESSMENT_PEER_REVIEWED)
        assert_status(peer_reviewed_basis["final_assessment"], ASSESSMENT_FINAL)

        refusal = _open_determination(
            api,
            peer_reviewed_basis["product"]["id"],
            peer_reviewed_basis["assessment"]["id"],
            DECISION_WARNING_REQUIRED,
        )
        validate_error(refusal, ERR_BASIS_ASSESSMENT_NOT_FINAL, 409)

        _, meta = _determination_rows(api, peer_reviewed_basis["product"]["id"])
        assert meta["total_count"] == 0

    def test_finalizing_the_cited_assessment_makes_the_identical_body_succeed(
        self, api, peer_reviewed_basis
    ):
        """One FINALIZE turns the refused body into an accepted one.

        PRD: "Both arms carry exactly the same side-effect set: `daily_exposure_ug`, `margin_ratio`, `result` and `contribution_count` are recomputed one final time, `finalized_at` is stamped with the current logical clock, any other assessment of the same product and chemical whose status is `FINAL` transitions `FINAL → SUPERSEDED`, and `compliance_posture` is recomputed."

        PRD: "The cited assessment must belong to the named product and must be in status `FINAL` at create time; if it belongs to a different product or is in any other status, the create is refused with `ERR_BASIS_ASSESSMENT_NOT_FINAL`."

        Design: Corner/validations/val_determination_basis_assessment_not_final_rejected
        """
        product_id = peer_reviewed_basis["product"]["id"]
        assessment_id = peer_reviewed_basis["assessment"]["id"]
        validate_error(
            _open_determination(
                api, product_id, assessment_id, DECISION_WARNING_REQUIRED
            ),
            ERR_BASIS_ASSESSMENT_NOT_FINAL,
            409,
        )

        finalized = get_success_data(
            api.assessment_transition(
                assessment_id, f.action_payload("FINALIZE"), TOXICOLOGY_REVIEWER
            )
        )
        assert_status(finalized, ASSESSMENT_FINAL)
        assert_instant(finalized["finalized_at"], DEFAULT_CLOCK, "finalized_at")
        assert_status(
            _read_assessment(api, peer_reviewed_basis["final_assessment"]["id"]),
            ASSESSMENT_SUPERSEDED,
        )

        determination = get_success_data(
            _open_determination(
                api, product_id, assessment_id, DECISION_WARNING_REQUIRED
            )
        )
        assert determination["assessment_id"] == assessment_id
        assert_status(determination, DETERMINATION_DRAFT)

    def test_the_evidence_rule_outranks_the_basis_rule(
        self, api, peer_reviewed_basis
    ):
        """SKU-BASIS-2 violates both rules, and the lower layer number decides.

        Layer 5's warning-required rule and layer 7's basis rule are both broken by
        this request, so the strictly ordered ladder returns the layer-5 identifier.

        PRD: "Rules are evaluated in ascending priority order; the first rule whose condition holds short-circuits the request and returns its error, and no later rule is evaluated."

        PRD: "**Layer 5 — business safety.** In order: (1) submission of an exposure assessment whose product has zero active components → `ERR_NO_ACTIVE_COMPONENTS`; (2) submission of a laboratory-method assessment while some contributing link is not on a laboratory basis or lacks its laboratory figures → `ERR_LAB_RESULT_MISSING`; (3) submission of a laboratory-method assessment while a contributing material's disclosure was refused and no naturally-occurring claim is on file → `ERR_SUPPLIER_DATA_INCOMPLETE`; (4) a determination created with a no-warning decision while a qualifying exposure exists → `ERR_EXPOSURE_ABOVE_SAFE_HARBOR`; (5) a determination created with a warning-required decision while no qualifying exposure exists → `ERR_NO_QUALIFYING_EXPOSURE`; (6) finalization of an assessment that has no recorded peer reviewer → `ERR_PEER_REVIEW_REQUIRED`; (7) a segregation-of-duties violation → `ERR_SEGREGATION_OF_DUTIES`; (8) a placement whose channel is not required by its determination → `ERR_CHANNEL_NOT_REQUIRED`; (9) a reformulation target or verified exposure that is not strictly below its threshold → `ERR_TARGET_NOT_BELOW_THRESHOLD`."

        PRD: "**Layer 7 — referential business rules.** In order: (1) an exposure assessment opened for a chemical that is not currently listed → `ERR_CHEMICAL_NOT_LISTED`; (2) a placement created against a determination that is not approved → `ERR_DETERMINATION_NOT_APPROVED`; (3) a settlement created against a notice that is not in settlement negotiation → `ERR_NOTICE_NOT_NEGOTIABLE`; (4) a material parent that would create a cycle or exceed the depth ceiling → `ERR_MATERIAL_CYCLE`, guarding both material creation and material update; (5) a reformulation project whose named link is inconsistent → `ERR_REFORMULATION_LINK_MISMATCH`; (6) a determination whose basis assessment is not final or belongs to another product → `ERR_BASIS_ASSESSMENT_NOT_FINAL`."

        Design: Corner/validations/val_determination_basis_assessment_not_final_rejected
        """
        bare = peer_reviewed_basis["bare_product"]
        assert_status(peer_reviewed_basis["bare_assessment"], ASSESSMENT_PEER_REVIEWED)

        refusal = _open_determination(
            api,
            bare["id"],
            peer_reviewed_basis["bare_assessment"]["id"],
            DECISION_WARNING_REQUIRED,
        )
        validate_error(refusal, ERR_NO_QUALIFYING_EXPOSURE, 409)

    def test_the_basis_rule_outranks_the_in_flight_rule(
        self, api, peer_reviewed_basis
    ):
        """With a determination already in DRAFT, layer 7 still speaks before layer 8.

        PRD: "**Layer 7 — referential business rules.** In order: (1) an exposure assessment opened for a chemical that is not currently listed → `ERR_CHEMICAL_NOT_LISTED`; (2) a placement created against a determination that is not approved → `ERR_DETERMINATION_NOT_APPROVED`; (3) a settlement created against a notice that is not in settlement negotiation → `ERR_NOTICE_NOT_NEGOTIABLE`; (4) a material parent that would create a cycle or exceed the depth ceiling → `ERR_MATERIAL_CYCLE`, guarding both material creation and material update; (5) a reformulation project whose named link is inconsistent → `ERR_REFORMULATION_LINK_MISMATCH`; (6) a determination whose basis assessment is not final or belongs to another product → `ERR_BASIS_ASSESSMENT_NOT_FINAL`."

        PRD: "**Layer 8 — business constraints.** In order: (1) a determination created for a product that already has one in flight → `ERR_OPEN_DETERMINATION_EXISTS`; (2) a settlement created for a notice that already has a live one → `ERR_OPEN_SETTLEMENT_EXISTS`; (3) a counter or revision on a settlement already at the round ceiling → `ERR_SETTLEMENT_ROUND_LIMIT`; (4) a rejection on an assessment already at the rejection ceiling → `ERR_REJECTION_LIMIT_REACHED`; (5) marketing requested on a product whose compliance posture forbids it → `ERR_PRODUCT_ON_ENFORCEMENT_HOLD`."

        Design: Corner/validations/val_determination_basis_assessment_not_final_rejected
        """
        product_id = peer_reviewed_basis["product"]["id"]
        in_flight = get_success_data(
            _open_determination(
                api,
                product_id,
                peer_reviewed_basis["final_assessment"]["id"],
                DECISION_WARNING_REQUIRED,
            )
        )
        assert_status(in_flight, DETERMINATION_DRAFT)

        refusal = _open_determination(
            api,
            product_id,
            peer_reviewed_basis["assessment"]["id"],
            DECISION_WARNING_REQUIRED,
        )
        validate_error(refusal, ERR_BASIS_ASSESSMENT_NOT_FINAL, 409)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 8 rule 1 — one in-flight determination per product
# ─────────────────────────────────────────────────────────────────────────────


class TestOnlyOneInFlightDetermination:
    """Uniqueness is scoped to in-flight work, so APPROVED can be superseded."""

    def test_a_second_create_is_refused_from_draft_and_from_pending_approval(
        self, api, in_flight_determination
    ):
        """Both in-flight states block a successor.

        PRD: "A product may hold only one in-flight determination: if one already exists in status `DRAFT` or `PENDING_APPROVAL`, the create is refused with `ERR_OPEN_DETERMINATION_EXISTS`."

        PRD: "A `LabelingSpecialist` submits for approval, taking the determination `DRAFT → PENDING_APPROVAL`."

        Design: Corner/validations/val_second_in_flight_determination_rejected_successor_after_approval_allowed
        """
        product_id = in_flight_determination["product"]["id"]
        first = in_flight_determination["determination"]
        assert_status(first, DETERMINATION_DRAFT)

        validate_error(
            _open_determination(
                api,
                product_id,
                in_flight_determination["assessment"]["id"],
                DECISION_WARNING_REQUIRED,
            ),
            ERR_OPEN_DETERMINATION_EXISTS,
            409,
        )

        pending = get_success_data(
            api.determination_transition(
                first["id"],
                f.action_payload("SUBMIT_FOR_APPROVAL"),
                LABELING_SPECIALIST,
            )
        )
        assert_status(pending, DETERMINATION_PENDING_APPROVAL)

        validate_error(
            _open_determination(
                api,
                product_id,
                in_flight_determination["assessment"]["id"],
                DECISION_WARNING_REQUIRED,
            ),
            ERR_OPEN_DETERMINATION_EXISTS,
            409,
        )

        _, meta = _determination_rows(api, product_id)
        assert meta["total_count"] == 1, (
            "Neither refused create may persist a second determination"
        )

    def test_an_approved_predecessor_admits_a_successor_that_supersedes_it(
        self, api, in_flight_determination
    ):
        """APPROVED does not block, and it leaves APPROVED only when the successor lands.

        PRD: "An already-`APPROVED` determination does **not** block a successor — the successor is created in `DRAFT` alongside it and supersedes it only when the successor is itself approved."

        PRD: "Approval re-runs the whole content selection against current data, stamps `approved_by_user_id`, moves any other determination of the same product whose status is `APPROVED` to `SUPERSEDED`, recomputes `covered_channel_count`, and recomputes `compliance_posture` — which will read `WARNING_REQUIRED` or `WARNING_ACTIVE` depending on channel coverage."

        Design: Corner/validations/val_second_in_flight_determination_rejected_successor_after_approval_allowed
        """
        product_id = in_flight_determination["product"]["id"]
        first = in_flight_determination["determination"]
        approved = approve_determination(api, first["id"])
        assert_status(approved, DETERMINATION_APPROVED)
        assert approved["approved_by_user_id"] == RC_1

        successor = get_success_data(
            _open_determination(
                api,
                product_id,
                in_flight_determination["assessment"]["id"],
                DECISION_WARNING_REQUIRED,
            )
        )
        assert_status(successor, DETERMINATION_DRAFT)
        assert_status(
            _read_determination(api, first["id"]), DETERMINATION_APPROVED
        )

        second_approved = approve_determination(api, successor["id"])
        assert_status(second_approved, DETERMINATION_APPROVED)
        assert_status(
            _read_determination(api, first["id"]), DETERMINATION_SUPERSEDED
        )

        rows, meta = _determination_rows(api, product_id)
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows].count(DETERMINATION_APPROVED) == 1, (
            "Exactly one determination may stand APPROVED for a product, got "
            f"{[row['status'] for row in rows]!r}"
        )
