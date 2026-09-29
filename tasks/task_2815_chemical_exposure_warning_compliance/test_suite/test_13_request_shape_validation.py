"""Layer 1 refusals: page windows, computed fields, CAS shapes and intervals.

Every rule here is paired with the nearest accepted request, so the boundary is
pinned on both sides rather than merely somewhere. One pair also pins the order
in which two simultaneously violated rules are reported.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_FIELD_NOT_WRITABLE,
    ERR_INVALID_CAS_NUMBER,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_SAFE_HARBOR_BASIS_MISMATCH,
)
from test_helpers.assertions import assert_fields_null, assert_lifecycle, assert_posture
from test_helpers.constants import (
    BENZENE_CAS,
    BENZENE_LEVEL,
    BENZENE_NAME,
    BPA_CAS,
    BPA_LEVEL,
    CADMIUM_CAS,
    CADMIUM_NAME,
    CHANNEL_INTERNET,
    CHANNEL_RETAIL,
    DEFAULT_CLOCK,
    ENDPOINT_TYPE_CANCER,
    ENDPOINT_TYPE_REPRODUCTIVE_FEMALE,
    ENDPOINT_TYPE_REPRODUCTIVE_MALE,
    HARM_CLASS_CANCER,
    LIFECYCLE_DEVELOPMENT,
    POSTURE_EXPOSURE_UNKNOWN,
    SAFE_HARBOR_BASIS_MADL,
    SAFE_HARBOR_BASIS_NONE,
    SAFE_HARBOR_BASIS_NSRL,
    WARRANTY_SCOPE_ALL_MATERIALS,
    WARRANTY_STATUS_NONE,
)
from test_helpers.fixtures import make_product, set_clock
from test_helpers.test_users import COMPLIANCE_ANALYST, REGISTRY_ADMIN


@pytest.fixture
def clocked(api):
    """One logical clock for every shape probe in this file."""
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


def _register(api, name, cas, endpoint, basis, level=f.OMIT):
    return api.create_listed_chemical(
        f.listed_chemical_payload(name, cas, endpoint, basis, level), REGISTRY_ADMIN
    )


def _chemical_count(api):
    _, meta = validate_paginated(api.list_listed_chemicals(REGISTRY_ADMIN))
    return meta["total_count"]


def _product_count(api):
    _, meta = validate_paginated(api.list_products(REGISTRY_ADMIN))
    return meta["total_count"]


def _onboard_supplier(api, legal_name, email, **warranty):
    return api.create_supplier(
        f.supplier_payload(
            legal_name,
            contact_email=email,
            warranty_scope=WARRANTY_SCOPE_ALL_MATERIALS,
            **warranty,
        ),
        COMPLIANCE_ANALYST,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Page windows
# ─────────────────────────────────────────────────────────────────────────────


class TestPaginationBounds:
    def test_the_three_out_of_range_page_windows_are_refused(self, api, clocked):
        """limit 201, limit 0 and offset -1 are refused rather than clamped into range.

        PRD: "A `limit` below 1, a `limit` above 200, or a negative `offset` is refused with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/validations/val_pagination_limit_above_maximum_rejected
        """
        make_product(api, "SKU-PAG", product_name="Pagination Probe", annual_units=1000)
        for window in ({"limit": 201, "offset": 0}, {"limit": 0, "offset": 0},
                       {"limit": 1, "offset": -1}):
            validate_error(
                api.list_products(REGISTRY_ADMIN, window),
                ERR_INVALID_PAGINATION,
                400,
            )

    def test_the_inclusive_upper_bound_of_two_hundred_is_accepted(self, api, clocked):
        """200 is the largest accepted limit, and the envelope echoes it back unchanged.

        PRD: "`limit` defaults to 10 when omitted, has a minimum accepted value of 1 and a maximum accepted value of 200."

        Design: Corner/validations/val_pagination_limit_above_maximum_rejected
        """
        make_product(api, "SKU-PAG", product_name="Pagination Probe", annual_units=1000)
        rows, meta = validate_paginated(
            api.list_products(REGISTRY_ADMIN, {"limit": 200, "offset": 0})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert meta["limit"] == 200
        assert meta["has_more"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Computed fields are not inputs
# ─────────────────────────────────────────────────────────────────────────────


class TestComputedFieldsAreNotWritable:
    def test_offering_a_compliance_posture_is_refused_outright(self, api, clocked):
        """The key is neither honoured nor ignored: the whole create fails and no row lands.

        PRD: "**Layer 4 — state legality.** In order: (1) the requested action is not a declared transition out of the entity's current state — including every action attempted from a terminal state — → `ERR_INVALID_STATE_TRANSITION`; (2) a child write is attempted under a parent in a blocking state → `ERR_PARENT_STATE_FORBIDS_WRITE`; (3) an update targets a row that has become immutable → `ERR_ENTITY_IMMUTABLE`; (4) a request body supplies a field whose value the server computes or stamps → `ERR_FIELD_NOT_WRITABLE`; (5) a bill-of-materials write is attempted while the product is under enforcement hold → `ERR_ENFORCEMENT_HOLD_FREEZE`."

        Design: Corner/validations/val_computed_field_supplied_in_body_rejected
        """
        validate_error(
            api.create_product(
                f.product_payload(
                    "SKU-CFW",
                    product_name="Computed Field Writer",
                    annual_units=1000,
                    compliance_posture="CLEAR",
                ),
                REGISTRY_ADMIN,
            ),
            ERR_FIELD_NOT_WRITABLE,
            422,
        )
        assert _product_count(api) == 0

    def test_the_same_body_without_the_key_derives_the_posture_itself(
        self, api, clocked
    ):
        """A componentless product is EXPOSURE_UNKNOWN, not the CLEAR that was offered.

        PRD: "A newly created product has `lifecycle_state` set to `DEVELOPMENT`, `compliance_posture` set to `EXPOSURE_UNKNOWN`, and every derived counter — `open_notice_count`, `accrued_penalty_cents` and `total_listed_chemical_load_ug` — set to 0."

        Design: Corner/validations/val_computed_field_supplied_in_body_rejected
        """
        product = get_success_data(
            api.create_product(
                f.product_payload(
                    "SKU-CFW", product_name="Computed Field Writer", annual_units=1000
                ),
                REGISTRY_ADMIN,
            )
        )
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)
        assert_lifecycle(product, LIFECYCLE_DEVELOPMENT)
        assert product["open_notice_count"] == 0
        assert product["accrued_penalty_cents"] == 0
        assert product["total_listed_chemical_load_ug"] == pytest.approx(0.0, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# The CAS registry shape
# ─────────────────────────────────────────────────────────────────────────────


class TestCasNumberPattern:
    def test_a_missing_and_a_one_digit_middle_group_are_both_refused(
        self, api, clocked
    ):
        """The value 8005-7 has no middle group and 80-5-7 has a one-digit one; both fail.

        PRD: "**Layer 1 — envelope, authorisation and shape.** In order: (1) the `X-User-Role` header is absent or is not one of the six declared roles → `ERR_UNAUTHORIZED`; (2) the caller's role is not among the roles the target endpoint authorises → `ERR_UNAUTHORIZED`; (3) on every create and every update, a required input field is absent, explicitly null, of the wrong JSON type, or carries an enum member that is not declared → `ERR_INVALID_REQUEST`; (4) on every list read, `limit` is below 1 or above 200, or `offset` is negative → `ERR_INVALID_PAGINATION`; (5) a numeric input is negative, or zero where the domain requires strictly positive → `ERR_VALUE_OUT_OF_RANGE`; (6) `contact_factor` falls outside the range from 0.0 through 1.0 inclusive, or `parent_mass_fraction` falls outside the range greater than 0.0 through 1.0 inclusive → `ERR_VALUE_OUT_OF_RANGE`; (7) `cas_number` does not match the CAS registry shape of two to seven digits, a hyphen, two digits, a hyphen and one final digit → `ERR_INVALID_CAS_NUMBER`; (8) the safe-harbor basis and level disagree → `ERR_SAFE_HARBOR_BASIS_MISMATCH`; (9) the safe-harbor basis contradicts the toxicological endpoint → `ERR_SAFE_HARBOR_BASIS_MISMATCH`; (10) an interval's end is not strictly after its start → `ERR_INVALID_INTERVAL`; (11) the `action` supplied to a transition surface or to the disclosure surface is not a declared trigger of that entity's state machine at all → `ERR_UNKNOWN_ACTION`; (12) `distribution_channels` is an empty array or contains a value outside the declared set → `ERR_INVALID_REQUEST`."

        Design: Corner/validations/val_cas_number_pattern_rejected
        """
        for name, cas in (("Bad CAS One", "8005-7"), ("Bad CAS Two", "80-5-7")):
            validate_error(
                _register(
                    api,
                    name,
                    cas,
                    ENDPOINT_TYPE_REPRODUCTIVE_FEMALE,
                    SAFE_HARBOR_BASIS_MADL,
                    BPA_LEVEL,
                ),
                ERR_INVALID_CAS_NUMBER,
                422,
            )
        assert _chemical_count(api) == 0

    def test_the_two_hyphen_shape_is_accepted_and_stored_verbatim(self, api, clocked):
        """80-05-7 matches two-to-seven digits, two digits and a check digit.

        PRD: "A `RegistryAdmin` registers a chemical by supplying its `chemical_name` — one to one hundred and twenty characters, used verbatim in warning label text and unique across the registry by exact case-sensitive match — its `cas_number` of one to twenty characters, its `endpoint_type`, its `safe_harbor_basis`, and, when a safe harbor exists, its `safe_harbor_level_ug_per_day`."

        Design: Corner/validations/val_cas_number_pattern_rejected
        """
        chemical = get_success_data(
            _register(
                api,
                "Bisphenol A",
                BPA_CAS,
                ENDPOINT_TYPE_REPRODUCTIVE_FEMALE,
                SAFE_HARBOR_BASIS_MADL,
                BPA_LEVEL,
            )
        )
        assert chemical["cas_number"] == "80-05-7"
        assert _chemical_count(api) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Basis, level and endpoint must agree
# ─────────────────────────────────────────────────────────────────────────────


class TestSafeHarborBasisAndLevel:
    def test_the_arithmetic_rule_runs_in_both_directions(self, api, clocked):
        """NSRL with no level and NONE with a level are both incoherent shapes.

        PRD: "The first is arithmetic: when the basis is `NSRL` or `MADL` the level must be present and strictly greater than zero, and when the basis is `NONE` the level must be null."

        Design: Corner/validations/val_safe_harbor_basis_and_level_must_agree
        """
        validate_error(
            _register(
                api,
                "Missing Level",
                BENZENE_CAS,
                ENDPOINT_TYPE_CANCER,
                SAFE_HARBOR_BASIS_NSRL,
            ),
            ERR_SAFE_HARBOR_BASIS_MISMATCH,
            422,
        )
        validate_error(
            _register(
                api,
                "Spurious Level",
                CADMIUM_CAS,
                ENDPOINT_TYPE_CANCER,
                SAFE_HARBOR_BASIS_NONE,
                0.05,
            ),
            ERR_SAFE_HARBOR_BASIS_MISMATCH,
            422,
        )
        assert _chemical_count(api) == 0

    def test_a_basis_of_none_with_no_level_is_the_coherent_shape(self, api, clocked):
        """NONE declares the absence of a safe harbour, so the level must stay null.

        PRD: "`safe_harbor_basis` is one of `NSRL`, `MADL` or `NONE`, where `NONE` declares that no safe harbor exists for this chemical at all."

        Design: Corner/validations/val_safe_harbor_basis_and_level_must_agree
        """
        chemical = get_success_data(
            _register(
                api,
                CADMIUM_NAME,
                CADMIUM_CAS,
                ENDPOINT_TYPE_CANCER,
                SAFE_HARBOR_BASIS_NONE,
            )
        )
        assert chemical["safe_harbor_basis"] == SAFE_HARBOR_BASIS_NONE
        assert_fields_null(chemical, ["safe_harbor_level_ug_per_day"])


class TestEndpointAndBasisAlignment:
    def test_each_endpoint_admits_only_its_own_basis(self, api, clocked):
        """CANCER may not carry a MADL and REPRODUCTIVE_MALE may not carry an NSRL.

        PRD: "The second is toxicological: an `endpoint_type` of `CANCER` may not be paired with a basis of `MADL`, and an `endpoint_type` of `REPRODUCTIVE_FEMALE`, `REPRODUCTIVE_MALE` or `DEVELOPMENTAL` may not be paired with a basis of `NSRL`."

        Design: Corner/validations/val_harm_class_and_basis_alignment_rejected
        """
        validate_error(
            _register(
                api,
                "Cancer With MADL",
                BENZENE_CAS,
                ENDPOINT_TYPE_CANCER,
                SAFE_HARBOR_BASIS_MADL,
                BENZENE_LEVEL,
            ),
            ERR_SAFE_HARBOR_BASIS_MISMATCH,
            422,
        )
        validate_error(
            _register(
                api,
                "Repro With NSRL",
                BPA_CAS,
                ENDPOINT_TYPE_REPRODUCTIVE_MALE,
                SAFE_HARBOR_BASIS_NSRL,
                BPA_LEVEL,
            ),
            ERR_SAFE_HARBOR_BASIS_MISMATCH,
            422,
        )
        assert _chemical_count(api) == 0

    def test_a_cancer_endpoint_with_an_nsrl_registers_as_the_cancer_class(
        self, api, clocked
    ):
        """The aligned pair is accepted and the harm class follows the endpoint.

        PRD: "From it the server derives `harm_class`, which is `CANCER` when `endpoint_type` is `CANCER` and `REPRODUCTIVE` for all three of the other endpoints; `harm_class` is therefore always one of `CANCER` or `REPRODUCTIVE`, and it is what later drives named-chemical grouping and harm-clause wording on labels."

        Design: Corner/validations/val_harm_class_and_basis_alignment_rejected
        """
        chemical = get_success_data(
            _register(
                api,
                BENZENE_NAME,
                BENZENE_CAS,
                ENDPOINT_TYPE_CANCER,
                SAFE_HARBOR_BASIS_NSRL,
                BENZENE_LEVEL,
            )
        )
        assert chemical["harm_class"] == HARM_CLASS_CANCER
        assert chemical["safe_harbor_basis"] == SAFE_HARBOR_BASIS_NSRL


class TestCasFormatOutranksAlignment:
    def test_the_lower_priority_number_decides_which_identifier_comes_back(
        self, api, clocked
    ):
        """One body breaks rule 7 and rule 9 at once, and rule 7 is the one reported.

        PRD: "When more than one rule is violated by a single request, the rule with the lowest priority number in the validation ladder of Section 2.8 decides which identifier is returned."

        Design: Corner/validations/val_cas_format_reported_before_basis_alignment
        """
        validate_error(
            _register(
                api,
                "Double Fault",
                "8005-7",
                ENDPOINT_TYPE_CANCER,
                SAFE_HARBOR_BASIS_MADL,
                BENZENE_LEVEL,
            ),
            ERR_INVALID_CAS_NUMBER,
            422,
        )

    def test_fixing_only_the_cas_surfaces_the_alignment_error_underneath(
        self, api, clocked
    ):
        """The second rule was always broken; it was simply outranked until now.

        PRD: "The second is toxicological: an `endpoint_type` of `CANCER` may not be paired with a basis of `MADL`, and an `endpoint_type` of `REPRODUCTIVE_FEMALE`, `REPRODUCTIVE_MALE` or `DEVELOPMENTAL` may not be paired with a basis of `NSRL`."

        Design: Corner/validations/val_cas_format_reported_before_basis_alignment
        """
        validate_error(
            _register(
                api,
                "Double Fault",
                "8005-7",
                ENDPOINT_TYPE_CANCER,
                SAFE_HARBOR_BASIS_MADL,
                BENZENE_LEVEL,
            ),
            ERR_INVALID_CAS_NUMBER,
            422,
        )
        validate_error(
            _register(
                api,
                "Double Fault",
                BPA_CAS,
                ENDPOINT_TYPE_CANCER,
                SAFE_HARBOR_BASIS_MADL,
                BENZENE_LEVEL,
            ),
            ERR_SAFE_HARBOR_BASIS_MISMATCH,
            422,
        )
        assert _chemical_count(api) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Strict intervals and the declared channel set
# ─────────────────────────────────────────────────────────────────────────────


class TestWarrantyIntervalOrdering:
    def test_a_zero_length_and_a_backwards_window_are_both_refused(self, api, clocked):
        """An end equal to the start is not a zero-length window, it is an invalid one.

        PRD: "When `warranty_effective_to` is supplied it must be strictly later than `warranty_effective_from`."

        Design: Corner/validations/val_supplier_warranty_interval_ordering_rejected
        """
        validate_error(
            _onboard_supplier(
                api,
                "Zero Window Chemicals",
                "zero@window.example",
                warranty_effective_from="2026-06-01T00:00:00Z",
                warranty_effective_to="2026-06-01T00:00:00Z",
            ),
            ERR_INVALID_INTERVAL,
            422,
        )
        validate_error(
            _onboard_supplier(
                api,
                "Backwards Chemicals",
                "back@window.example",
                warranty_effective_from="2026-06-01T00:00:00Z",
                warranty_effective_to="2026-05-31T23:59:59Z",
            ),
            ERR_INVALID_INTERVAL,
            422,
        )

    def test_one_second_of_width_is_enough_and_stays_dormant(self, api, clocked):
        """The nearest accepted window is one second wide, and it executes nothing.

        PRD: "Warranty terms may be supplied at onboarding but stay dormant: `warranty_scope`, `pass_through_warning_obligation`, `indemnity_cap_cents`, `warranty_effective_from` and `warranty_effective_to` are all optional at create time, and `warranty_status` is always set to `NONE` regardless of what was supplied."

        Design: Corner/validations/val_supplier_warranty_interval_ordering_rejected
        """
        supplier = get_success_data(
            _onboard_supplier(
                api,
                "One Second Chemicals",
                "one@window.example",
                warranty_effective_from="2026-06-01T00:00:00Z",
                warranty_effective_to="2026-06-01T00:00:01Z",
            )
        )
        assert supplier["warranty_status"] == WARRANTY_STATUS_NONE
        assert supplier["warranty_scope"] == WARRANTY_SCOPE_ALL_MATERIALS


class TestDistributionChannels:
    def test_an_empty_array_and_an_undeclared_member_are_both_refused(
        self, api, clocked
    ):
        """An empty array is type-valid JSON and still cannot describe a distributed product.

        PRD: "Products are created by a `RegistryAdmin` from a `sku` of one to forty characters unique across all products, a `product_name` of one to one hundred and sixty characters, a `product_category`, a non-empty `distribution_channels` array with no duplicates, a strictly positive `label_area_sq_in` measured in square inches, and a non-negative `annual_units` count of units sold into California per year."

        Design: Corner/validations/val_empty_distribution_channels_rejected
        """
        for channels in ([], ["WHOLESALE"]):
            validate_error(
                api.create_product(
                    f.product_payload(
                        "SKU-NOCH",
                        product_name="No Channels",
                        distribution_channels=channels,
                        annual_units=1000,
                    ),
                    REGISTRY_ADMIN,
                ),
                ERR_INVALID_REQUEST,
                400,
            )
        assert _product_count(api) == 0

    def test_two_declared_channels_are_accepted_and_stored_in_order(self, api, clocked):
        """RETAIL and INTERNET are both members of the declared set, so the create lands.

        PRD: "`distribution_channels` is a subset of `RETAIL`, `CATALOG` and `INTERNET`."

        Design: Corner/validations/val_empty_distribution_channels_rejected
        """
        product = get_success_data(
            api.create_product(
                f.product_payload(
                    "SKU-NOCH",
                    product_name="No Channels",
                    distribution_channels=f.channels(CHANNEL_RETAIL, CHANNEL_INTERNET),
                    annual_units=1000,
                ),
                REGISTRY_ADMIN,
            )
        )
        assert product["distribution_channels"] == [CHANNEL_RETAIL, CHANNEL_INTERNET]
