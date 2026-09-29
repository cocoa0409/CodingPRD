"""Entity contracts: creation echoes, retrieval fidelity, listing windows, derived
and system-owned fields, boundary type rules, immutable records and the
retailer/grant junction topology.

Every test in this module pins one breadth claim about how a single entity's
fields are accepted, derived or rendered.
"""
import re

from test_helpers import (
    ADMIN,
    CONSUMER_HEADERS,
    ApiErrorId,
    api_client,
    assert_bench_hour_ledger,
    assert_common_fields,
    assert_immutable_common_fields,
    assert_instant_equals,
    assert_pagination_meta,
    assert_penalty_ledger,
    assert_score,
    assert_status,
    assert_version_is,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    validate_unpaginated,
)

TIER_INPUTS = {
    "tier_code": "TIER_1",
    "required_route": "SELF_ATTESTATION",
    "label_validity_days": 365,
    "min_overall_score": 70.00,
    "unverified_weight_factor": 0.60,
    "issuance_base_fee_cents": 40000,
    "max_deficiency_rounds": 2,
}

# One criterion per practice area; only DAT-1 is lab-verifiable.
FOUR_AREA_CRITERIA = [
    {
        "criterion_code": "AUTH-1",
        "practice_area": "AUTHENTICATION",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Unique per-device credentials",
    },
    {
        "criterion_code": "UPD-1",
        "practice_area": "SOFTWARE_UPDATE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Signed firmware updates",
    },
    {
        "criterion_code": "DAT-1",
        "practice_area": "DATA_PROTECTION",
        "weight": 10,
        "requires_lab_verification": True,
        "criterion_text": "Encryption of data at rest",
    },
    {
        "criterion_code": "VLN-1",
        "practice_area": "VULN_DISCLOSURE",
        "weight": 10,
        "requires_lab_verification": False,
        "criterion_text": "Published disclosure contact",
    },
]

UNKNOWN_ASSESSMENT_ID = "00000000-0000-4000-8000-000000000404"
UNKNOWN_PARENT_ASSESSMENT_ID = "00000000-0000-4000-8000-0000000004a5"


class TestProgramTierCreationPersistsDeclaredInputs:
    """POST /labeling/program-tiers keeps every declared input field."""

    def test_every_declared_input_field_is_echoed_unchanged(self):
        """All seven declared ProgramTier input fields come back exactly as sent.

        PRD: "A tier is the policy bundle that decides how demanding the program is for whatever sits underneath it, and it is identified by a `tier_code` — unique across all tiers, between 3 and 32 characters long, and composed only of uppercase letters, digits and the underscore character."
        Design: Corner/entities/creation_program_tier_persists_every_declared_input_field
        """
        fixtures.reset_clock()

        tier = validate_success(
            api_client.create_program_tier(dict(TIER_INPUTS), ADMIN), 201
        )

        assert tier["tier_code"] == "TIER_1"
        assert tier["required_route"] == "SELF_ATTESTATION"
        assert tier["label_validity_days"] == 365
        assert_score(tier["min_overall_score"], 70.00, "min_overall_score")
        assert_score(tier["unverified_weight_factor"], 0.60, "unverified_weight_factor")
        assert tier["issuance_base_fee_cents"] == 40000
        assert isinstance(tier["issuance_base_fee_cents"], int)
        assert tier["max_deficiency_rounds"] == 2

    def test_created_tier_carries_the_system_owned_common_fields(self):
        """The new row is minted with version 1 and both audit timestamps.

        PRD: "`version` (integer): a counter that begins at 1 and increments by one on every accepted mutation of the row."
        Design: Corner/entities/creation_program_tier_persists_every_declared_input_field
        """
        fixtures.reset_clock()

        tier = validate_success(
            api_client.create_program_tier(dict(TIER_INPUTS), ADMIN), 201
        )

        assert_common_fields(tier)
        assert_version_is(tier, 1)
        assert is_valid_uuid(tier["id"])
        assert is_iso8601_timestamp(tier["created_at"])
        assert is_iso8601_timestamp(tier["updated_at"])

    def test_creation_response_uses_the_object_envelope(self):
        """The 201 body carries the standard meta pair and response_type object.

        PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        Design: Corner/entities/creation_program_tier_persists_every_declared_input_field
        """
        fixtures.reset_clock()

        response = api_client.create_program_tier(dict(TIER_INPUTS), ADMIN)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestProductRetrievalReturnsStoredRepresentation:
    """GET /labeling/products/{id} replays what was stored, not a recomputation."""

    @staticmethod
    def _registered_product():
        fixtures.reset_clock()
        tier = validate_success(
            api_client.create_program_tier(dict(TIER_INPUTS), ADMIN), 201
        )
        category = validate_success(
            api_client.create_device_category(
                factories.create_device_category_payload(
                    tier["id"], min_support_period_days=180
                ),
                ADMIN,
            ),
            201,
        )
        sponsor = fixtures.enrol_manufacturer(
            legal_name="Acme Devices",
            contact_email="ops@acme.example",
            enterprise_class="SMALL",
            annual_us_revenue_cents=900000000,
        )
        payload = factories.create_product_payload(
            sponsor.id,
            category["id"],
            model_name="Speaker One",
            sku="SPK-001",
            firmware_version="1.0.0",
            declared_support_period_end="2029-08-01T00:00:00Z",
            update_policy_disclosed=True,
            retail_units_shipped=1000,
        )
        created = validate_success(
            api_client.create_product(payload, sponsor.headers), 201
        )
        return sponsor, category, created

    def test_read_returns_every_stored_input_field_unchanged(self):
        """model_name, sku, firmware_version and the parents survive the round trip.

        PRD: "Registration supplies the sponsoring `manufacturer_id`, the `device_category_id` placing the model inside the program's scope, the consumer-facing `model_name` that will appear on the registry page, the retail `sku` (unique across all products), the `firmware_version` the current conformance claim describes, the `declared_support_period_end` instant through which the manufacturer commits to shipping security updates, an `update_policy_disclosed` boolean asserting that a public update policy exists, and `retail_units_shipped`, a non-negative count of units shipped into US retail that the program records for evaluation and enforcement context."
        Design: Corner/entities/retrieval_product_returns_stored_representation_after_create
        """
        sponsor, category, created = self._registered_product()

        product = validate_success(
            api_client.get_product(created["id"], sponsor.headers)
        )

        assert product["model_name"] == "Speaker One"
        assert product["sku"] == "SPK-001"
        assert product["firmware_version"] == "1.0.0"
        assert product["update_policy_disclosed"] is True
        assert product["retail_units_shipped"] == 1000
        assert product["manufacturer_id"] == sponsor.id
        assert product["device_category_id"] == category["id"]

    def test_read_renders_the_declared_support_period_as_a_utc_instant(self):
        """declared_support_period_end reads back as the supplied instant.

        PRD: "Every ISO 8601 instant the API emits — `created_at`, `updated_at`, `submitted_at`, `decided_at`, `completed_at`, `published_at`, `adjudicated_at`, `valid_from`, `valid_until`, `support_period_end`, `window_start`, `window_end`, `display_from`, `display_until`, `survey_period_end` and `declared_support_period_end` — uses UTC with three fractional digits."
        Design: Corner/entities/retrieval_product_returns_stored_representation_after_create
        """
        sponsor, _category, created = self._registered_product()

        product = validate_success(
            api_client.get_product(created["id"], sponsor.headers)
        )

        assert is_iso8601_timestamp(product["declared_support_period_end"])
        assert_instant_equals(
            product["declared_support_period_end"],
            "2029-08-01T00:00:00Z",
            "declared_support_period_end",
        )


class TestTierDeviceCategoryListingPagination:
    """The per-tier category list windows a three-row collection."""

    CATEGORY_SPECS = (
        ("SMART_SPEAKER", "Smart Speaker", 180),
        ("SMART_LOCK", "Smart Lock", 180),
        ("SMART_CAMERA", "Smart Camera", 365),
    )

    @classmethod
    def _tier_with_three_categories(cls):
        fixtures.reset_clock()
        tier = validate_success(
            api_client.create_program_tier(dict(TIER_INPUTS), ADMIN), 201
        )
        for code, display_name, support_days in cls.CATEGORY_SPECS:
            validate_success(
                api_client.create_device_category(
                    factories.create_device_category_payload(
                        tier["id"],
                        category_code=code,
                        display_name=display_name,
                        min_support_period_days=support_days,
                    ),
                    ADMIN,
                ),
                201,
            )
        return tier

    def test_first_page_reports_the_full_total_and_more_to_come(self):
        """limit=2&offset=0 returns two rows, total_count 3 and has_more true.

        PRD: "Every list response repeats `limit` and `offset` inside the `meta` object alongside `total_count`, the number of rows matching the filter before pagination, and `has_more`, which is true exactly when rows remain beyond the current page."
        Design: Corner/entities/listing_device_categories_of_a_tier_paginates_with_total_count_and_has_more
        """
        tier = self._tier_with_three_categories()

        response = api_client.list_tier_device_categories(
            tier["id"], ADMIN, params={"limit": 2, "offset": 0}
        )

        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert len(rows) == 2
        assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)

    def test_second_page_completes_the_set_without_duplication(self):
        """limit=2&offset=2 returns the last row with has_more false, and the two
        pages together cover each category code exactly once.

        PRD: "Every list response repeats `limit` and `offset` inside the `meta` object alongside `total_count`, the number of rows matching the filter before pagination, and `has_more`, which is true exactly when rows remain beyond the current page."
        Design: Corner/entities/listing_device_categories_of_a_tier_paginates_with_total_count_and_has_more
        """
        tier = self._tier_with_three_categories()

        first_rows, _first_meta = validate_paginated(
            api_client.list_tier_device_categories(
                tier["id"], ADMIN, params={"limit": 2, "offset": 0}
            )
        )
        second_rows, second_meta = validate_paginated(
            api_client.list_tier_device_categories(
                tier["id"], ADMIN, params={"limit": 2, "offset": 2}
            )
        )

        assert len(second_rows) == 1
        assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
        union = [row["category_code"] for row in first_rows + second_rows]
        assert sorted(union) == ["SMART_CAMERA", "SMART_LOCK", "SMART_SPEAKER"]


class TestSecurityCriteriaFilterAndPaginationInteract:
    """Catalogue filters narrow total_count before the page window applies."""

    @staticmethod
    def _catalogue():
        fixtures.reset_clock()
        return validate_success(
            api_client.create_security_criteria(
                factories.create_security_criteria_payload(FOUR_AREA_CRITERIA), ADMIN
            ),
            201,
        )

    def test_practice_area_filter_narrows_the_catalogue_to_one_row(self):
        """practice_area=AUTHENTICATION reports total_count 1 for AUTH-1.

        PRD: "The catalogue can be browsed with filters on `practice_area` and `requires_lab_verification`."
        Design: Corner/entities/listing_security_criteria_filter_and_pagination_interact
        """
        self._catalogue()

        rows, meta = validate_paginated(
            api_client.list_security_criteria(
                CONSUMER_HEADERS, params={"practice_area": "AUTHENTICATION"}
            )
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["criterion_code"] == "AUTH-1"

    def test_lab_verification_filter_selects_a_different_single_row(self):
        """requires_lab_verification=true reports total_count 1 for DAT-1.

        PRD: "The catalogue can be browsed with filters on `practice_area` and `requires_lab_verification`."
        Design: Corner/entities/listing_security_criteria_filter_and_pagination_interact
        """
        self._catalogue()

        rows, meta = validate_paginated(
            api_client.list_security_criteria(
                CONSUMER_HEADERS, params={"requires_lab_verification": "true"}
            )
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["criterion_code"] == "DAT-1"
        assert rows[0]["requires_lab_verification"] is True

    def test_unfiltered_page_window_reports_the_whole_catalogue(self):
        """limit=3 over the unfiltered catalogue returns 3 of 4 rows with more left.

        PRD: "Every list response repeats `limit` and `offset` inside the `meta` object alongside `total_count`, the number of rows matching the filter before pagination, and `has_more`, which is true exactly when rows remain beyond the current page."
        Design: Corner/entities/listing_security_criteria_filter_and_pagination_interact
        """
        self._catalogue()

        rows, meta = validate_paginated(
            api_client.list_security_criteria(
                CONSUMER_HEADERS, params={"limit": 3, "offset": 0}
            )
        )

        assert len(rows) == 3
        assert_pagination_meta(meta, limit=3, offset=0, total_count=4, has_more=True)


class TestUnknownAssessmentIdOnRead:
    """A valid-but-unknown assessment id is a 404, not an empty 200."""

    def test_read_of_an_unknown_assessment_id_reports_not_found(self):
        """GET on an unresolvable assessment id returns ERR_ASSESSMENT_NOT_FOUND.

        PRD: "The reported code is the not-found code of whichever entity failed to resolve first — `ERR_PROGRAM_CONFIG_NOT_FOUND` for an unknown program tier or device category, `ERR_MANUFACTURER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CRITERION_NOT_FOUND`, `ERR_TEST_LAB_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND` or `ERR_REGISTRY_CODE_NOT_FOUND`."
        Design: Corner/entities/not_found_unknown_assessment_id_on_read
        """
        fixtures.reset_clock()

        response = api_client.get_assessment(UNKNOWN_ASSESSMENT_ID, ADMIN)

        validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value)
        assert response.json()["response_type"] == "error"


class TestProductRequiresDeclaredSupportPeriodEnd:
    """declared_support_period_end is required at the request boundary."""

    @staticmethod
    def _sponsor_and_category():
        fixtures.reset_clock()
        tier = validate_success(
            api_client.create_program_tier(dict(TIER_INPUTS), ADMIN), 201
        )
        category = validate_success(
            api_client.create_device_category(
                factories.create_device_category_payload(
                    tier["id"], min_support_period_days=180
                ),
                ADMIN,
            ),
            201,
        )
        sponsor = fixtures.enrol_manufacturer(
            legal_name="Acme Devices",
            contact_email="ops@acme.example",
            enterprise_class="SMALL",
            annual_us_revenue_cents=900000000,
        )
        return sponsor, category

    @classmethod
    def _post_product_without_support_period(cls):
        sponsor, category = cls._sponsor_and_category()
        payload = factories.create_product_payload(
            sponsor.id,
            category["id"],
            model_name="Speaker One",
            sku="SPK-001",
            firmware_version="1.0.0",
            declared_support_period_end=None,
            update_policy_disclosed=True,
            retail_units_shipped=1000,
        )
        return sponsor, api_client.create_product(payload, sponsor.headers)

    def test_explicit_null_support_period_is_a_request_shape_failure(self):
        """An explicit null for the required instant is rejected, not defaulted.

        PRD: "**Request shape.** The body parses, every non-optional field of the endpoint is present, and every supplied value matches its declared JSON type, enum membership, string format and sign — otherwise `ERR_INVALID_REQUEST`."
        Design: Corner/entities/required_fields_missing_declared_support_period_end_on_product_create
        """
        _sponsor, response = self._post_product_without_support_period()

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_the_rejected_create_leaves_no_product_row_behind(self):
        """The sponsor's product collection is still empty after the rejection.

        PRD: "When more than one condition is violated by a single request, the identifier returned is the one belonging to the highest-priority rung of the rejection ladder in §2.6, and the request has no partial effect: a rejected request writes nothing, mutates no derived quantity and advances no state machine."
        Design: Corner/entities/required_fields_missing_declared_support_period_end_on_product_create
        """
        sponsor, response = self._post_product_without_support_period()
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        rows, meta = validate_paginated(
            api_client.list_products(
                sponsor.headers, params={"manufacturer_id": sponsor.id}
            )
        )

        assert meta["total_count"] == 0
        assert rows == []


class TestOptionalExclusionReasonAndPaginationDefaults:
    """Omitted optionals stay null and omitted page params take their defaults."""

    @staticmethod
    def _tier_with_one_eligible_category():
        fixtures.reset_clock()
        tier = validate_success(
            api_client.create_program_tier(dict(TIER_INPUTS), ADMIN), 201
        )
        category = validate_success(
            api_client.create_device_category(
                factories.create_device_category_payload(
                    tier["id"], min_support_period_days=180
                ),
                ADMIN,
            ),
            201,
        )
        return tier, category

    def test_eligible_category_leaves_exclusion_reason_null(self):
        """An ELIGIBLE category created without exclusion_reason reads back null.

        PRD: "`exclusion_reason` records the regulatory basis for an exclusion: it is required when `eligibility_status` is `EXCLUDED` and must be omitted entirely when the category is `ELIGIBLE`, where it stays null."
        Design: Corner/entities/defaults_optional_exclusion_reason_and_pagination_defaults
        """
        _tier, category = self._tier_with_one_eligible_category()

        assert category["eligibility_status"] == "ELIGIBLE"
        assert category["exclusion_reason"] is None

        stored = validate_success(api_client.get_device_category(category["id"], ADMIN))
        assert stored["exclusion_reason"] is None

    def test_omitted_page_parameters_apply_the_declared_defaults(self):
        """A list read with no limit or offset reports limit 10 and offset 0.

        PRD: "`limit` caps the number of rows returned; it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100."
        Design: Corner/entities/defaults_optional_exclusion_reason_and_pagination_defaults
        """
        tier, _category = self._tier_with_one_eligible_category()

        rows, meta = validate_paginated(
            api_client.list_tier_device_categories(tier["id"], ADMIN)
        )

        assert len(rows) == 1
        assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)


class TestManufacturerLedgerDefaults:
    """Enrolment writes the penalty ledger explicitly rather than leaving it null."""

    @staticmethod
    def _enrolled():
        fixtures.reset_clock()
        return validate_success(
            api_client.create_manufacturer(
                factories.create_manufacturer_payload(
                    legal_name="Acme Devices",
                    contact_email="ops@acme.example",
                    enterprise_class="SMALL",
                    annual_us_revenue_cents=900000000,
                ),
                ADMIN,
            ),
            201,
        )

    def test_new_manufacturer_starts_good_with_every_counter_at_zero(self):
        """standing GOOD and all five counters 0 without appearing in the body.

        PRD: "Enrolment initialises the penalty ledger explicitly: `standing` starts at `GOOD`, and `outstanding_penalty_cents`, `paid_penalty_cents`, `vacated_penalty_cents`, `total_assessed_penalty_cents` and `upheld_case_count` all start at 0."
        Design: Corner/entities/defaults_manufacturer_penalty_ledger_zeroed_with_standing_good
        """
        manufacturer = self._enrolled()

        assert_status(manufacturer, "standing", "GOOD")
        assert manufacturer["outstanding_penalty_cents"] == 0
        assert manufacturer["paid_penalty_cents"] == 0
        assert manufacturer["vacated_penalty_cents"] == 0
        assert manufacturer["total_assessed_penalty_cents"] == 0
        assert manufacturer["upheld_case_count"] == 0

    def test_the_ledger_identity_already_holds_at_enrolment(self):
        """outstanding + paid + vacated equals total_assessed on the fresh row.

        PRD: "For every `Manufacturer`, the sum of `outstanding_penalty_cents`, `paid_penalty_cents` and `vacated_penalty_cents` equals `total_assessed_penalty_cents` at all times, including immediately after a vacate has compensated an adjudication."
        Design: Corner/entities/defaults_manufacturer_penalty_ledger_zeroed_with_standing_good
        """
        manufacturer = self._enrolled()

        assert_penalty_ledger(manufacturer, outstanding=0, paid=0, vacated=0)

        stored = validate_success(api_client.get_manufacturer(manufacturer["id"], ADMIN))
        assert_penalty_ledger(stored, outstanding=0, paid=0, vacated=0)


class TestProductDerivedFieldsAtCreation:
    """eligibility_status mirrors the category; the other derived fields start fixed."""

    @staticmethod
    def _two_products():
        fixtures.reset_clock()
        tier = validate_success(
            api_client.create_program_tier(dict(TIER_INPUTS), ADMIN), 201
        )
        eligible = validate_success(
            api_client.create_device_category(
                factories.create_device_category_payload(
                    tier["id"], min_support_period_days=180
                ),
                ADMIN,
            ),
            201,
        )
        excluded = validate_success(
            api_client.create_device_category(
                factories.create_excluded_category_payload(
                    tier["id"],
                    exclusion_reason="Regulated as a medical device outside program scope",
                    min_support_period_days=180,
                ),
                ADMIN,
            ),
            201,
        )
        sponsor = fixtures.enrol_manufacturer(
            legal_name="Acme Devices",
            contact_email="ops@acme.example",
            enterprise_class="SMALL",
            annual_us_revenue_cents=900000000,
        )
        common = {
            "firmware_version": "1.0.0",
            "declared_support_period_end": "2029-08-01T00:00:00Z",
            "update_policy_disclosed": True,
            "retail_units_shipped": 1000,
        }
        product_ok = validate_success(
            api_client.create_product(
                factories.create_product_payload(
                    sponsor.id,
                    eligible["id"],
                    model_name="Speaker One",
                    sku="SPK-001",
                    **common,
                ),
                sponsor.headers,
            ),
            201,
        )
        product_excluded = validate_success(
            api_client.create_product(
                factories.create_product_payload(
                    sponsor.id,
                    excluded["id"],
                    model_name="Pacer X",
                    sku="MED-001",
                    **common,
                ),
                sponsor.headers,
            ),
            201,
        )
        return product_ok, product_excluded

    def test_eligibility_status_mirrors_the_referenced_category(self):
        """Identical bodies in different categories yield ELIGIBLE and EXCLUDED.

        PRD: "Three fields are derived at creation and not supplied: `spec_revision` starts at 1 and thereafter only ever increases; `conformance_currency` starts at `CURRENT`; and `eligibility_status` mirrors the referenced device category's own `eligibility_status`, taking the value `ELIGIBLE` or `EXCLUDED` as the category dictates."
        Design: Corner/entities/computed_fields_product_eligibility_mirrors_category_and_spec_revision_starts_at_one
        """
        product_ok, product_excluded = self._two_products()

        assert product_ok["eligibility_status"] == "ELIGIBLE"
        assert product_excluded["eligibility_status"] == "EXCLUDED"

    def test_both_products_start_at_spec_revision_one_and_current(self):
        """spec_revision 1 and conformance_currency CURRENT on both new rows.

        PRD: "Three fields are derived at creation and not supplied: `spec_revision` starts at 1 and thereafter only ever increases; `conformance_currency` starts at `CURRENT`; and `eligibility_status` mirrors the referenced device category's own `eligibility_status`, taking the value `ELIGIBLE` or `EXCLUDED` as the category dictates."
        Design: Corner/entities/computed_fields_product_eligibility_mirrors_category_and_spec_revision_starts_at_one
        """
        product_ok, product_excluded = self._two_products()

        assert product_ok["spec_revision"] == 1
        assert product_excluded["spec_revision"] == 1
        assert product_ok["conformance_currency"] == "CURRENT"
        assert product_excluded["conformance_currency"] == "CURRENT"

    def test_last_change_summary_is_null_before_any_spec_change(self):
        """A freshly registered product has no change summary yet.

        PRD: "`last_change_summary` is null until the first spec-change notice."
        Design: Corner/entities/computed_fields_product_eligibility_mirrors_category_and_spec_revision_starts_at_one
        """
        product_ok, _product_excluded = self._two_products()

        assert product_ok["last_change_summary"] is None


class TestTestLabBenchLedgerInitialisation:
    """A new lab's bench ledger is derived from an empty reserving set."""

    @staticmethod
    def _registered_lab():
        fixtures.reset_clock()
        return validate_success(
            api_client.create_test_lab(
                factories.create_test_lab_payload(
                    lab_name="Northline Labs",
                    accreditation_status="ACCREDITED",
                    total_bench_hours=200,
                    concurrent_bench_capacity=2,
                ),
                ADMIN,
            ),
            201,
        )

    def test_new_lab_reserves_nothing_and_has_its_whole_bench_available(self):
        """reserved_bench_hours 0 and available_bench_hours 200 at registration.

        PRD: "Registration initialises the bench ledger so that `reserved_bench_hours` is 0 and `available_bench_hours` equals `total_bench_hours`."
        Design: Corner/entities/computed_fields_test_lab_bench_ledger_initialised_from_total_hours
        """
        lab = self._registered_lab()

        assert lab["total_bench_hours"] == 200
        assert lab["reserved_bench_hours"] == 0
        assert lab["available_bench_hours"] == 200

    def test_the_bench_ledger_identity_holds_on_the_fresh_row(self):
        """reserved plus available equals total on the newly registered lab.

        PRD: "For every `TestLab`, the sum of `reserved_bench_hours` and `available_bench_hours` equals `total_bench_hours` at all times."
        Design: Corner/entities/computed_fields_test_lab_bench_ledger_initialised_from_total_hours
        """
        lab = self._registered_lab()

        assert_bench_hour_ledger(lab, reserved=0)

        stored = validate_success(api_client.get_test_lab(lab["id"], ADMIN))
        assert_bench_hour_ledger(stored, reserved=0)


class TestLabelGrantSystemFieldsAreServerMinted:
    """Issuance mints the code, the two statuses and the audit fields itself."""

    @staticmethod
    def _issued_grant_response():
        fixtures.reset_clock()
        claim = fixtures.approved_claim()
        return api_client.create_label_grant(
            factories.create_label_grant_payload(claim.product_id, claim.assessment_id),
            claim.sponsor.headers,
        )

    def test_issuance_mints_a_sixteen_character_scannable_code(self):
        """The client supplies no code yet the grant carries a conforming one.

        PRD: "Issuance mints the `scannable_code` — a server-generated 16-character string, unique across all grants, composed only of uppercase letters, digits and hyphens — which is what gets printed on the label and what a shopper's scan resolves."
        Design: Corner/entities/system_fields_scannable_code_and_audit_timestamps_are_server_minted
        """
        grant = validate_success(self._issued_grant_response(), 201)

        code = grant["scannable_code"]
        assert isinstance(code, str)
        assert len(code) == 16, code
        assert re.fullmatch(r"[A-Z0-9-]{16}", code), code

    def test_the_new_grant_starts_pending_registry_on_draft(self):
        """Both status dimensions start at their declared initial values.

        PRD: "The new grant starts with `grant_status` at `PENDING_REGISTRY` and `registry_publication_status` at `DRAFT`, so it exists but is not yet publicly readable and may not yet be displayed."
        Design: Corner/entities/system_fields_scannable_code_and_audit_timestamps_are_server_minted
        """
        grant = validate_success(self._issued_grant_response(), 201)

        assert grant["grant_status"] == "PENDING_REGISTRY"
        assert grant["registry_publication_status"] == "DRAFT"

    def test_an_original_issuance_has_generation_zero_and_no_validity_window(self):
        """renewal_generation 0, a null validity window and version 1.

        PRD: "An originally issued grant has `renewal_generation` 0, and `suspension_reason`, `valid_from`, `valid_until` and `superseded_by_grant_id` all start null while `renewal_required` starts false."
        Design: Corner/entities/system_fields_scannable_code_and_audit_timestamps_are_server_minted
        """
        grant = validate_success(self._issued_grant_response(), 201)

        assert grant["renewal_generation"] == 0
        assert grant["valid_from"] is None
        assert grant["valid_until"] is None
        assert grant["suspension_reason"] is None
        assert grant["superseded_by_grant_id"] is None
        assert grant["renewal_required"] is False
        assert_common_fields(grant)
        assert_version_is(grant, 1)


class TestBoundaryTypeConstraints:
    """Enum membership and strict interval ordering are enforced at the boundary."""

    @staticmethod
    def _grant_and_lab():
        fixtures.reset_clock()
        claim = fixtures.approved_claim()
        grant = fixtures.issue_grant(claim)
        lab = fixtures.register_lab(
            lab_name="Northline Labs",
            accreditation_status="ACCREDITED",
            total_bench_hours=200,
            concurrent_bench_capacity=2,
        )
        return claim, grant, lab

    def test_an_update_cadence_outside_the_enum_is_rejected(self):
        """MONTHLY is not one of the three declared cadences.

        PRD: "It carries the `update_policy_url` disclosing the product's software update policy, which must begin with the characters `https://`; the `update_cadence`, one of `AUTOMATIC`, `USER_INITIATED` or `NONE`; and the `vuln_disclosure_contact`, the public coordinated-vulnerability-disclosure address."
        Design: Corner/entities/type_constraints_bad_enum_and_inverted_window_rejected
        """
        claim, grant, _lab = self._grant_and_lab()

        response = api_client.create_registry_entry(
            grant.id,
            factories.registry_entry_payload(
                update_policy_url="https://acme.example/updates",
                update_cadence="MONTHLY",
                vuln_disclosure_contact="security@acme.example",
            ),
            claim.sponsor.headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_the_rejected_entry_leaves_the_grant_with_no_registry_entry(self):
        """The zero-or-one entry read is still an empty array after the rejection.

        PRD: "The entry backing a grant is readable as a zero-or-one element array, so a grant with no entry yet reads as an empty list rather than as a missing resource."
        Design: Corner/entities/type_constraints_bad_enum_and_inverted_window_rejected
        """
        claim, grant, _lab = self._grant_and_lab()
        response = api_client.create_registry_entry(
            grant.id,
            factories.registry_entry_payload(update_cadence="MONTHLY"),
            claim.sponsor.headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        entries = validate_unpaginated(
            api_client.get_registry_entry(grant.id, claim.sponsor.headers)
        )

        assert entries == []

    def test_a_zero_length_bench_window_is_rejected_and_reserves_nothing(self):
        """window_end equal to window_start fails and the ledger does not move.

        PRD: "The occupation window is **half-open**: `window_start` is inclusive and `window_end` is exclusive, and `window_end` must be strictly after `window_start`."
        Design: Corner/entities/type_constraints_bad_enum_and_inverted_window_rejected
        """
        claim, _grant, lab = self._grant_and_lab()

        response = api_client.create_test_engagement(
            factories.create_test_engagement_payload(
                claim.assessment_id,
                lab.id,
                window_start="2026-08-10T09:00:00Z",
                window_end="2026-08-10T09:00:00Z",
                bench_hours=8,
            ),
            claim.sponsor.headers,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        stored = lab.refresh()
        assert stored["reserved_bench_hours"] == 0
        assert stored["available_bench_hours"] == 200
        assert_bench_hour_ledger(stored, reserved=0)


class TestImmutableRecordsCarryNoVersion:
    """SecurityCriterion and RecognitionSurvey expose id and created_at only."""

    def test_a_registered_criterion_exposes_no_version_field(self):
        """The criterion read carries no version and keeps its registered weight.

        PRD: "Two resources are records rather than living rows and therefore carry only `id` and `created_at`: `SecurityCriterion`, whose catalogue entries are immutable once registered, and `RecognitionSurvey`, whose waves are closed historical observations."
        Design: Corner/entities/immutability_security_criterion_and_recognition_survey_have_no_version_or_mutator
        """
        fixtures.reset_clock()
        catalogue = validate_success(
            api_client.create_security_criteria(
                factories.create_security_criteria_payload(FOUR_AREA_CRITERIA), ADMIN
            ),
            201,
        )
        auth1_id = next(c["id"] for c in catalogue if c["criterion_code"] == "AUTH-1")

        criterion = validate_success(
            api_client.get_security_criterion(auth1_id, CONSUMER_HEADERS)
        )

        assert_immutable_common_fields(criterion)
        assert "version" not in criterion
        assert criterion["criterion_code"] == "AUTH-1"
        assert criterion["weight"] == 10

    def test_a_recorded_survey_wave_exposes_no_version_field(self):
        """The survey read carries no version and keeps both recorded counts.

        PRD: "For both of those, `updated_at` and `version` are absent from the response entirely — not null, absent."
        Design: Corner/entities/immutability_security_criterion_and_recognition_survey_have_no_version_or_mutator
        """
        fixtures.reset_clock()
        recorded = validate_success(
            api_client.create_recognition_survey(
                factories.create_recognition_survey_payload(
                    survey_period_label="2026-H1",
                    survey_period_end="2026-06-30T00:00:00Z",
                    respondents_count=400,
                    recognized_count=140,
                ),
                ADMIN,
            ),
            201,
        )

        survey = validate_success(
            api_client.get_recognition_survey(recorded["id"], CONSUMER_HEADERS)
        )

        assert_immutable_common_fields(survey)
        assert "version" not in survey
        assert survey["respondents_count"] == 400
        assert survey["recognized_count"] == 140


class TestCriterionResponseBatchRequiresExistingAssessment:
    """The parent path id is resolved before any body foreign key."""

    @staticmethod
    def _post_batch_under_unknown_assessment():
        fixtures.reset_clock()
        catalogue = validate_success(
            api_client.create_security_criteria(
                factories.create_security_criteria_payload(FOUR_AREA_CRITERIA), ADMIN
            ),
            201,
        )
        auth1_id = next(c["id"] for c in catalogue if c["criterion_code"] == "AUTH-1")
        sponsor = fixtures.enrol_manufacturer(
            legal_name="Acme Devices",
            contact_email="ops@acme.example",
            enterprise_class="SMALL",
            annual_us_revenue_cents=900000000,
        )
        payload = factories.criterion_responses_payload(
            [factories.response_item(auth1_id, True, evidence_ref="EV-AUTH-1")]
        )
        return api_client.create_criterion_responses(
            UNKNOWN_PARENT_ASSESSMENT_ID, payload, sponsor.headers
        )

    def test_unknown_parent_assessment_reports_assessment_not_found(self):
        """The unresolvable path id decides the response, not the body criterion_id.

        PRD: "Where a path does carry an identifier, and where a body then carries further foreign keys, resolution is strictly left to right and outside in — the path identifier is resolved before any body field, and body foreign keys are resolved in the order the endpoint declares them."
        Design: Corner/entities/parent_relationships_criterion_response_batch_requires_existing_assessment
        """
        response = self._post_batch_under_unknown_assessment()

        validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value)

    def test_the_rejected_batch_writes_no_criterion_response(self):
        """The criterion-response collection is still empty after the rejection.

        PRD: "When more than one condition is violated by a single request, the identifier returned is the one belonging to the highest-priority rung of the rejection ladder in §2.6, and the request has no partial effect: a rejected request writes nothing, mutates no derived quantity and advances no state machine."
        Design: Corner/entities/parent_relationships_criterion_response_batch_requires_existing_assessment
        """
        response = self._post_batch_under_unknown_assessment()
        validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value)

        rows, meta = validate_paginated(api_client.list_criterion_responses(ADMIN))

        assert meta["total_count"] == 0
        assert rows == []


class TestDisplayAuthorizationJunctionTopology:
    """One published grant carries three authorizations across two retailers."""

    DISPLAY_FROM = "2026-09-01T00:00:00Z"
    DISPLAY_UNTIL = "2026-12-31T00:00:00Z"

    @classmethod
    def _three_authorizations(cls):
        fixtures.reset_clock()
        grant = fixtures.published_grant()
        store_a = fixtures.register_retailer(retailer_name="MegaMart")
        store_b = fixtures.register_retailer(retailer_name="CornerShop")

        def authorize(store, channel):
            return api_client.create_display_authorization(
                factories.create_display_authorization_payload(
                    store.id,
                    grant.id,
                    cls.DISPLAY_FROM,
                    cls.DISPLAY_UNTIL,
                    channel=channel,
                ),
                store.headers,
            )

        responses = [
            authorize(store_a, "ONLINE"),
            authorize(store_a, "IN_STORE"),
            authorize(store_b, "ONLINE"),
        ]
        return grant, store_a, store_b, responses

    def test_three_authorizations_coexist_on_one_grant(self):
        """Two retailers and two channels all authorize the same label at once.

        PRD: "Because the check is scoped to the retailer-grant-channel combination, the same retailer may run an `IN_STORE` and an `ONLINE` display of the same label over identical dates without conflict."
        Design: Corner/entities/graph_topology_display_authorizations_form_a_retailer_grant_junction
        """
        grant, _store_a, _store_b, responses = self._three_authorizations()

        for response in responses:
            authorization = validate_success(response, 201)
            assert_status(authorization, "status", "AUTHORIZED")
            assert authorization["withdrawal_reason"] is None

        rows, meta = validate_paginated(
            api_client.list_display_authorizations(
                ADMIN, params={"label_grant_id": grant.id}
            )
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3

    def test_each_retailer_derives_its_own_count_and_tier(self):
        """The junction gives retailer A two active displays and retailer B one.

        PRD: "Then `participation_tier` is chosen: a retailer whose `education_materials_ack` is true and whose `active_display_count` is 5 or more is `PLATINUM`; failing that, a retailer whose `education_materials_ack` is true and whose `active_display_count` is 2 or more is `GOLD`; every other retailer is `BASELINE`."
        Design: Corner/entities/graph_topology_display_authorizations_form_a_retailer_grant_junction
        """
        _grant, store_a, store_b, responses = self._three_authorizations()
        for response in responses:
            validate_success(response, 201)

        retailer_a = store_a.refresh()
        retailer_b = store_b.refresh()

        assert retailer_a["active_display_count"] == 2
        assert_status(retailer_a, "participation_tier", "GOLD")
        assert retailer_b["active_display_count"] == 1
        assert_status(retailer_b, "participation_tier", "BASELINE")

    def test_the_grant_keeps_both_status_dimensions_through_the_authorizations(self):
        """Authorizing displays leaves the grant ACTIVE and PUBLISHED.

        PRD: "A `LabelGrant` has a `grant_status`, which governs whether the label may legally be displayed, and a `registry_publication_status`, which governs whether the public registry page resolves."
        Design: Corner/entities/graph_topology_display_authorizations_form_a_retailer_grant_junction
        """
        grant, _store_a, _store_b, responses = self._three_authorizations()
        for response in responses:
            validate_success(response, 201)

        stored = grant.refresh()

        assert stored["grant_status"] == "ACTIVE"
        assert stored["registry_publication_status"] == "PUBLISHED"
        assert_instant_equals(stored["valid_from"], "2026-08-01T00:00:00Z", "valid_from")
