"""Resource shapes, lifecycle fields, listing envelopes and not-found paths.

Covers what a freshly created row looks like on each aggregate: which inputs are
echoed, which optional inputs materialise a default, which fields the server
assigns for itself, which two aggregates are immutable event records carrying no
revision counter, how a paginated collection reports its window, and which
not-found identifier each endpoint answers with when a path subject or a body
foreign key names nothing.

The harness restarts the server and empties the database before every individual
test, so every test builds all of the state it needs.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.test_users import (
    DISTRIBUTION_PLANNER,
    PLATFORM_ADMIN,
    PRODUCTION_OPERATOR,
    QA_RELEASER,
    QC_ANALYST,
    QC_ANALYST_USER_ID,
    REGULATORY_AFFAIRS,
)

HTTP_CREATED = 201
HTTP_OK = 200

# The four optional settings of a raw material specification and the default the
# PRD declares for each, so a body that omits them is still fully populated.
SPEC_OPTIONAL_DEFAULTS = {
    "is_critical": False,
    "acceptance_mode": "ALL_PASS",
    "max_retests": 1,
    "retest_window_days": 30,
}


def _all_material_specifications(api, headers=REGULATORY_AFFAIRS):
    """Every raw material specification currently registered."""
    return validate_paginated(
        api.list_material_specifications(headers, params={"limit": 100}))


def _all_material_lots(api, spec_id, headers=PRODUCTION_OPERATOR):
    """Every raw material lot booked in against one specification."""
    return validate_paginated(api.list_material_lots(
        headers, params={"material_specification_id": spec_id, "limit": 100}))


class TestMaterialSpecificationResourceShape:
    """Creation echo, declared defaults and the shape rung on reference data."""

    def test_material_specification_create_echoes_every_declared_input(self, api):
        """PRD §3.1: "The specification declares its `material_type` as one of
        `ANTIBODY`, `ENZYME`, `CALIBRATOR_MATERIAL` or `BUFFER`, and it declares
        the acceptance bounds the laboratory will test against: `potency_min_pct`
        and `potency_max_pct` as the lower and upper percent-of-label window,
        `purity_min_pct` as the percent-purity floor, and
        `endotoxin_max_eu_per_ml` as the endotoxin ceiling in EU per millilitre."
        PRD §3.1: "The `required_test_codes` array names which acceptance tests
        must all be on file before anybody may take a decision, drawn from
        `POTENCY`, `PURITY`, `ENDOTOXIN` and `IDENTITY`."
        PRD §3.1: "Four further settings on the specification are optional and
        each has a default that matters."

        Design: Corner/entities/material_specification_create_returns_every_declared_field
        """
        payload = factories.material_specification_payload(
            material_type="CALIBRATOR_MATERIAL",
            is_critical=True,
            potency_min_pct=95.0,
            potency_max_pct=105.0,
            endotoxin_max_eu_per_ml=1.5,
            purity_min_pct=98.0,
            required_test_codes=["POTENCY", "IDENTITY"],
            acceptance_mode="WEIGHTED_SCORE",
            max_retests=2,
            retest_window_days=45,
        )
        # All eleven declared inputs are supplied, so nothing may be dropped.
        assert len(payload) == 11

        spec = validate_success(
            api.create_material_specification(payload, REGULATORY_AFFAIRS),
            HTTP_CREATED)
        for field, expected in payload.items():
            assert spec[field] == expected, (
                f"the created specification must echo {field}: expected "
                f"{expected!r}, got {spec.get(field)!r}")
        assertions.assert_material_specification(spec)

        fetched = validate_success(
            api.get_material_specification(spec["id"], PLATFORM_ADMIN), HTTP_OK)
        assert fetched["id"] == spec["id"]
        for field, expected in payload.items():
            assert fetched[field] == expected, (
                f"the persisted specification must still carry {field} as "
                f"{expected!r}, got {fetched.get(field)!r}")

    def test_material_specification_create_stamps_the_four_common_fields(self, api):
        """PRD §2.4: "Every resource this API returns carries a server-minted
        `id`: a UUID string with no type prefix and no embedded meaning."
        PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC
        timestamp rendered with exactly three fractional digits."
        PRD §2.4: "Twelve of the fourteen aggregates additionally carry
        `updated_at` — same format as `created_at`, refreshed on every mutation
        of the row — and `version`, an integer that starts at 1 when the row is
        created and increases by exactly 1 on every mutation of that row,
        including mutations reached indirectly through a cascade."

        Design: Corner/entities/material_specification_create_returns_every_declared_field
        """
        spec = fixtures.create_material_specification(api)
        assertions.assert_common_fields(spec, "material_specification")
        assert spec["version"] == 1, (
            "version starts at 1 when the row is created, got "
            f"{spec['version']}")
        assertions.assert_three_fractional_digits(spec["created_at"], "created_at")
        assertions.assert_three_fractional_digits(spec["updated_at"], "updated_at")

        fetched = validate_success(
            api.get_material_specification(spec["id"], REGULATORY_AFFAIRS),
            HTTP_OK)
        assert fetched["version"] == 1
        assertions.assert_same_instant(fetched["created_at"], spec["created_at"],
                                       "created_at")
        assertions.assert_same_instant(fetched["updated_at"], spec["updated_at"],
                                       "updated_at")

    def test_material_specification_omitted_optional_inputs_take_their_defaults(self, api):
        """PRD §3.1: "Four further settings on the specification are optional and
        each has a default that matters."
        PRD §3.1: "`is_critical` defaults to false; when it is true, a change of
        vendor lot for this material forces a bridging study on the next finished
        lot, which is the subject of §3.7."
        PRD §3.1: "`acceptance_mode` defaults to `ALL_PASS` and may instead be
        `WEIGHTED_SCORE`; it selects which of two acceptance algorithms decides
        the lot's fate, and it is fixed on the specification rather than chosen
        per request."
        PRD §3.1: "`max_retests` defaults to 1 and says how many retest cycles a
        lot may run after an out-of-specification result."
        PRD §3.1: "`retest_window_days` defaults to 30 and bounds how long after
        the first failure a retest may still be recorded."

        Design: Corner/entities/material_specification_omitted_optional_fields_apply_declared_defaults
        """
        payload = factories.material_specification_payload()
        for field in SPEC_OPTIONAL_DEFAULTS:
            assert field not in payload, (
                f"{field} must be omitted from the body for this test")

        spec = validate_success(
            api.create_material_specification(payload, REGULATORY_AFFAIRS),
            HTTP_CREATED)
        for field, expected in SPEC_OPTIONAL_DEFAULTS.items():
            assert spec[field] is not None, (
                f"the omitted optional {field} must materialise its declared "
                "default rather than null")
            assert spec[field] == expected, (
                f"{field} should default to {expected!r}, got {spec[field]!r}")
        assert spec["is_critical"] is False, (
            "is_critical defaults to false, not to a falsy substitute")

        fetched = validate_success(
            api.get_material_specification(spec["id"], REGULATORY_AFFAIRS),
            HTTP_OK)
        for field, expected in SPEC_OPTIONAL_DEFAULTS.items():
            assert fetched[field] == expected

    def test_material_specification_undeclared_material_type_is_rejected(self, api):
        """PRD §3.1: "The specification declares its `material_type` as one of
        `ANTIBODY`, `ENZYME`, `CALIBRATOR_MATERIAL` or `BUFFER`, and it declares
        the acceptance bounds the laboratory will test against: `potency_min_pct`
        and `potency_max_pct` as the lower and upper percent-of-label window,
        `purity_min_pct` as the percent-purity floor, and
        `endotoxin_max_eu_per_ml` as the endotoxin ceiling in EU per millilitre."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/material_specification_undeclared_enum_and_violated_numeric_bound_are_rejected
        """
        payload = factories.material_specification_payload(
            material_type="PLASMID")
        validate_error(
            api.create_material_specification(payload, REGULATORY_AFFAIRS),
            "ERR_INVALID_REQUEST", 400)

        rows, meta = _all_material_specifications(api)
        assertions.assert_paginated_meta(meta, expected_total=0)
        assert rows == [], "a rejected creation must persist no row"

    def test_material_specification_inverted_potency_window_is_rejected(self, api):
        """PRD §2.6: "The body parses as JSON, every required input field is
        present, every enum-typed value is a declared member of its enumeration,
        `limit` lies between 1 and 100 inclusive and `offset` is at least 0, and
        every numeric bound holds: `received_quantity_units` is greater than 0,
        `quantity_used` is greater than 0, `requested_units` is greater than 0,
        `planned_units` is greater than 0, `planned_fill_units` is greater than
        0, `potency_min_pct` is greater than 0 and strictly less than
        `potency_max_pct`, `endotoxin_max_eu_per_ml` is greater than 0,
        `max_retests` is at least 0, `shelf_life_months_claim` is greater than 0,
        `baseline_value` is greater than 0, `scheduled_end` is strictly later
        than `scheduled_start`, `protocol_end` is strictly later than
        `protocol_start`, `required_min_shelf_life_days` is at least 0,
        `result_value` is at least 0, and `reference_measured_value` is greater
        than 0 whenever it is present."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/material_specification_undeclared_enum_and_violated_numeric_bound_are_rejected
        """
        payload = factories.material_specification_payload(
            potency_min_pct=110.0, potency_max_pct=90.0)
        validate_error(
            api.create_material_specification(payload, REGULATORY_AFFAIRS),
            "ERR_INVALID_REQUEST", 400)

        rows, meta = _all_material_specifications(api)
        assertions.assert_paginated_meta(meta, expected_total=0)
        assert rows == [], "a rejected creation must persist no row"


class TestMaterialLotCreationAndShapeRung:
    """The goods-in ledger, and the two shapes of a malformed booking-in."""

    def test_material_lot_create_opens_the_quantity_ledger(self, api):
        """PRD §3.1: "The lot is created in `qualification_status` `RECEIVED`,
        with `available_quantity_units` initialised to `received_quantity_units`,
        `consumed_quantity_units` initialised to 0, `retest_count` at 0, and
        `first_oos_at`, `acceptance_score`, `dispositioned_by_user_id`,
        `dispositioned_at` and `quarantine_reason` all null."
        PRD §2.8: "The invariant is that `received_quantity_units` always equals
        `available_quantity_units` plus `consumed_quantity_units`."

        Design: Corner/entities/material_lot_create_initialises_the_quantity_ledger_and_qualification_state
        """
        spec = fixtures.create_material_specification(
            api, material_type="ENZYME", required_test_codes=["POTENCY"])
        payload = factories.material_lot_payload(spec["id"],
                                                 received_quantity_units=1000.0)
        lot = validate_success(
            api.create_material_lot(payload, PRODUCTION_OPERATOR), HTTP_CREATED)

        assert lot["qualification_status"] == "RECEIVED"
        assert lot["received_quantity_units"] == 1000.0
        assert lot["available_quantity_units"] == 1000.0, (
            "available_quantity_units is initialised to received_quantity_units")
        assert lot["consumed_quantity_units"] == 0, (
            "consumed_quantity_units is initialised to 0")
        assertions.assert_material_quantity_conservation(lot)
        assert lot["retest_count"] == 0
        for field in ("first_oos_at", "acceptance_score",
                      "dispositioned_by_user_id", "dispositioned_at",
                      "quarantine_reason"):
            assertions.assert_absent_or_none(lot, field, "material_lot")
        assert lot["version"] == 1
        assertions.assert_material_lot(lot)

        fetched = validate_success(api.get_material_lot(lot["id"], QC_ANALYST),
                                   HTTP_OK)
        assert fetched["qualification_status"] == "RECEIVED"
        assert fetched["available_quantity_units"] == 1000.0
        assert fetched["consumed_quantity_units"] == 0
        assertions.assert_absent_or_none(fetched, "acceptance_score",
                                         "material_lot")

    def test_material_lot_missing_expiry_date_is_rejected(self, api):
        """PRD §3.1: "The booking-in payload carries the
        `material_specification_id`, the `vendor_lot_code` printed on the
        supplier's certificate of analysis, the `received_quantity_units` in
        specification units, and the vendor's `expiry_date` as an ISO 8601 UTC
        instant."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/material_lot_missing_required_expiry_date_returns_invalid_request
        """
        spec = fixtures.create_material_specification(
            api, material_type="ENZYME", required_test_codes=["POTENCY"])
        payload = factories.material_lot_payload(spec["id"])
        payload.pop("expiry_date")
        assert "expiry_date" not in payload
        # The specification foreign key is valid, so only the omitted instant
        # can be the reason for the rejection.
        validate_error(api.create_material_lot(payload, PRODUCTION_OPERATOR),
                       "ERR_INVALID_REQUEST", 400)

        rows, meta = _all_material_lots(api, spec["id"])
        assertions.assert_paginated_meta(meta, expected_total=0)
        assert rows == [], "a rejected booking-in must persist no lot"

    def test_material_lot_zero_received_quantity_is_rejected(self, api):
        """PRD §2.6: "The body parses as JSON, every required input field is
        present, every enum-typed value is a declared member of its enumeration,
        `limit` lies between 1 and 100 inclusive and `offset` is at least 0, and
        every numeric bound holds: `received_quantity_units` is greater than 0,
        `quantity_used` is greater than 0, `requested_units` is greater than 0,
        `planned_units` is greater than 0, `planned_fill_units` is greater than
        0, `potency_min_pct` is greater than 0 and strictly less than
        `potency_max_pct`, `endotoxin_max_eu_per_ml` is greater than 0,
        `max_retests` is at least 0, `shelf_life_months_claim` is greater than 0,
        `baseline_value` is greater than 0, `scheduled_end` is strictly later
        than `scheduled_start`, `protocol_end` is strictly later than
        `protocol_start`, `required_min_shelf_life_days` is at least 0,
        `result_value` is at least 0, and `reference_measured_value` is greater
        than 0 whenever it is present."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/material_specification_undeclared_enum_and_violated_numeric_bound_are_rejected
        """
        spec = fixtures.create_material_specification(
            api, material_type="ANTIBODY", required_test_codes=["POTENCY"])
        payload = factories.material_lot_payload(spec["id"],
                                                 received_quantity_units=0.0)
        validate_error(api.create_material_lot(payload, PRODUCTION_OPERATOR),
                       "ERR_INVALID_REQUEST", 400)

        rows, meta = _all_material_lots(api, spec["id"])
        assertions.assert_paginated_meta(meta, expected_total=0)
        assert rows == [], "a rejected booking-in must persist no lot"


class TestReagentLotServerAssignedFields:
    """A finished lot opens on both axes with every counter and every piece of
    release evidence assigned by the server, not by the caller."""

    def test_reagent_lot_opens_planned_and_withheld_with_zeroed_counters(self, api):
        """PRD §3.3: "A `ProductionOperator` opens a finished-goods lot by naming
        its `product_specification_id`, a manufacturer `lot_code`, and the
        `planned_units` the lot is expected to yield."
        PRD §3.3: "The new lot starts with `disposition_status` `PLANNED` on the
        quality axis and `distribution_status` `WITHHELD` on the availability
        axis, with all five unit counters — `filled_units`, `available_units`,
        `allocated_units`, `shipped_units` and `quarantined_units` — initialised
        to 0, which satisfies the finished-goods ledger of §2.8 trivially."
        PRD §3.3: "`em_excursion_count` starts at 0 and `bridging_required`
        starts false."
        PRD §3.3: "The evidence fields that only a release can fill —
        `fill_completed_at`, `assigned_shelf_life_months`, `shelf_life_basis`,
        `shelf_life_basis_study_id`, `expiry_date`, `release_bias_max_pct`,
        `release_bias_sum_pct`, `bioburden_cfu_per_ml`, `released_by_user_id` and
        `released_at` — all start null."

        Design: Corner/entities/reagent_lot_system_fields_are_server_assigned_and_client_values_ignored
        """
        product = fixtures.create_product_specification(api)
        assert product["clearance_status"] == "DESIGN"

        payload = factories.reagent_lot_payload(product["id"], planned_units=400)
        # The create declares exactly three inputs.
        assert sorted(payload) == ["lot_code", "planned_units",
                                   "product_specification_id"]
        lot = validate_success(api.create_reagent_lot(payload,
                                                     PRODUCTION_OPERATOR),
                               HTTP_CREATED)

        assert lot["disposition_status"] == "PLANNED"
        assert lot["distribution_status"] == "WITHHELD"
        for field in ("filled_units", "available_units", "allocated_units",
                      "shipped_units", "quarantined_units"):
            assert lot[field] == 0, (
                f"{field} is initialised to 0, got {lot[field]!r}")
        assertions.assert_reagent_lot_unit_conservation(lot)
        assert lot["em_excursion_count"] == 0
        assert lot["bridging_required"] is False
        for field in ("fill_completed_at", "assigned_shelf_life_months",
                      "shelf_life_basis", "shelf_life_basis_study_id",
                      "expiry_date", "release_bias_max_pct",
                      "release_bias_sum_pct", "bioburden_cfu_per_ml",
                      "released_by_user_id", "released_at"):
            assertions.assert_absent_or_none(lot, field, "reagent_lot")
        assert lot["version"] == 1
        assertions.assert_reagent_lot(lot)

        fetched = validate_success(api.get_reagent_lot(lot["id"], QA_RELEASER),
                                   HTTP_OK)
        assert fetched["disposition_status"] == "PLANNED"
        assert fetched["distribution_status"] == "WITHHELD"
        assert fetched["available_units"] == 0
        assert fetched["bridging_required"] is False

    def test_reagent_lot_ignores_a_client_supplied_identifier(self, api):
        """PRD §2.4: "Every resource this API returns carries a server-minted
        `id`: a UUID string with no type prefix and no embedded meaning."
        PRD §2.4: "Clients never supply an `id`; a client-supplied `id` in a
        creation body is ignored."

        Design: Corner/entities/reagent_lot_system_fields_are_server_assigned_and_client_values_ignored
        """
        product = fixtures.create_product_specification(api)
        planted_id = "11111111-1111-1111-1111-111111111111"
        payload = factories.reagent_lot_payload(product["id"], id=planted_id)

        lot = validate_success(api.create_reagent_lot(payload,
                                                     PRODUCTION_OPERATOR),
                               HTTP_CREATED)
        assert lot["id"] != planted_id, (
            "a client-supplied id in a creation body is ignored, so the server "
            "must mint its own")
        assertions.assert_common_fields(lot, "reagent_lot")

        # The server-minted identifier is the only one that resolves.
        validate_success(api.get_reagent_lot(lot["id"], PRODUCTION_OPERATOR),
                         HTTP_OK)
        validate_error(api.get_reagent_lot(planted_id, PRODUCTION_OPERATOR),
                       "ERR_REAGENT_LOT_NOT_FOUND", 404)


class TestImmutableEventRecords:
    """The two aggregates that carry no revision counter at all."""

    def test_monitoring_sample_carries_no_updated_at_and_no_version(self, api):
        """PRD §2.4: "Two aggregates are deliberately immutable event records and
        carry **only** `id` and `created_at`: a monitoring sample and a test
        result."
        PRD §2.4: "For those two, `updated_at` and `version` are absent from the
        payload entirely — not null, absent — because once a measurement has been
        recorded it is never edited; a superseding measurement is a new record,
        not a revision of an old one."
        PRD §3.4: "Monitoring samples are immutable event records: they carry
        `id` and `created_at` but no `updated_at` and no `version`."

        Design: Corner/entities/monitoring_sample_is_an_immutable_event_with_no_version_and_no_write_back
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        run = fixtures.schedule_fill_run(api, lot["id"])

        sample = fixtures.record_monitoring_sample(api, run["id"], "SURFACE", 4.0)
        assertions.assert_event_record_fields(sample, "monitoring_sample")
        assert "updated_at" not in sample, (
            "updated_at must be absent from the payload entirely, not null")
        assert "version" not in sample, (
            "version must be absent from the payload entirely, not null")
        assert sample["fill_run_id"] == run["id"]

        rows, meta = validate_paginated(
            api.list_monitoring_samples(run["id"], QC_ANALYST))
        assertions.assert_paginated_meta(meta, expected_total=1)
        assert len(rows) == 1
        assertions.assert_event_record_fields(rows[0], "monitoring_sample")
        assert "version" not in rows[0]
        assert "updated_at" not in rows[0]

    def test_monitoring_sample_correction_is_a_second_row_not_an_edit(self, api):
        """PRD §2.4: "For those two, `updated_at` and `version` are absent from
        the payload entirely — not null, absent — because once a measurement has
        been recorded it is never edited; a superseding measurement is a new
        record, not a revision of an old one."
        PRD §3.4: "Monitoring samples are immutable event records: they carry
        `id` and `created_at` but no `updated_at` and no `version`."

        Design: Corner/entities/monitoring_sample_is_an_immutable_event_with_no_version_and_no_write_back
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        run = fixtures.schedule_fill_run(api, lot["id"])

        first = fixtures.record_monitoring_sample(api, run["id"], "SURFACE", 4.0,
                                                  location_code="BENCH-1")
        second = fixtures.record_monitoring_sample(api, run["id"], "SURFACE", 3.0,
                                                   location_code="BENCH-1")
        assert second["id"] != first["id"], (
            "a superseding measurement is a new record, not a revision")

        rows, meta = validate_paginated(
            api.list_monitoring_samples(run["id"], QC_ANALYST))
        assertions.assert_paginated_meta(meta, expected_total=2)
        assertions.assert_sorted_by_created_at(rows)
        stored_first = [row for row in rows if row["id"] == first["id"]]
        assert len(stored_first) == 1, "the first sample row must still be on file"
        assert stored_first[0] == first, (
            "recording a second sample must leave the first row untouched")

    def test_test_result_get_returns_the_measurement_and_its_derived_outcome(self, api):
        """PRD §3.1: "A `POTENCY` measurement passes when `measured_value` is at
        least `potency_min_pct` and at most `potency_max_pct`."
        PRD §3.1: "The `outcome` of a raw-material measurement is `PASS` or
        `FAIL`, decided against the specification bound that governs its
        `test_code`, and every bound is inclusive so a value landing exactly on
        the bound passes."
        PRD §3.1: "The server stamps `performed_by_user_id` from the acting
        operator's identity and `performed_at` from the logical clock, and it
        computes `outcome` itself — clients never supply it."
        PRD §3.5: "Measurements of all three subject kinds are readable
        individually and listable together, filterable by `subject_type`, by
        `material_lot_id`, by `reagent_lot_id`, by `stability_study_id`, by
        `test_code` and by `is_retest`; like monitoring samples they are immutable
        event records carrying `id` and `created_at` but no `updated_at` and no
        `version`."

        Design: Corner/entities/test_result_retrieval_returns_the_stored_measurement_and_its_derived_outcome
        """
        performed_instant = constants.clock_plus(days=2)
        fixtures.set_clock(api, performed_instant)

        spec = fixtures.create_material_specification(
            api, potency_min_pct=90.0, potency_max_pct=110.0,
            required_test_codes=["POTENCY"])
        lot = fixtures.create_material_lot(api, spec["id"])
        # 90.0 lands exactly on potency_min_pct, and every bound is inclusive.
        recorded = fixtures.record_material_measurement(api, lot["id"],
                                                        "POTENCY", 90.0)

        fetched = validate_success(
            api.get_test_result(recorded["id"], QA_RELEASER), HTTP_OK)
        assert fetched["id"] == recorded["id"]
        assert fetched["subject_type"] == "MATERIAL_LOT"
        assert fetched["material_lot_id"] == lot["id"]
        assert fetched["test_code"] == "POTENCY"
        assert fetched["measured_value"] == 90.0
        assert fetched["outcome"] == "PASS", (
            "a measurement landing exactly on its inclusive bound passes")
        assert fetched["performed_by_user_id"] == QC_ANALYST_USER_ID
        assertions.assert_same_instant(fetched["performed_at"],
                                       performed_instant, "performed_at")
        assertions.assert_absent_or_none(fetched, "bias_pct", "test_result")
        assertions.assert_absent_or_none(fetched, "recovery_pct", "test_result")
        assertions.assert_event_record_fields(fetched, "test_result")
        assertions.assert_test_result(fetched)


class TestReagentLotPaginatedListing:
    """Twelve finished lots against a default page size of ten."""

    @staticmethod
    def _twelve_lots(api):
        """One product specification with twelve finished lots opened in order.

        Returns ``(product_specification, [lot, ...])`` in creation order.
        """
        product = fixtures.create_product_specification(api)
        lots = [fixtures.create_reagent_lot(api, product["id"],
                                            lot_code=f"ENT-P-{index:02d}",
                                            planned_units=100)
                for index in range(1, 13)]
        return product, lots

    def test_reagent_lot_listing_first_page_reports_the_full_total(self, api):
        """PRD §2.3: "Every list endpoint accepts two optional query parameters."
        PRD §2.3: "`limit` controls page size: its default is 10, its minimum
        accepted value is 1, and its maximum accepted value is 100."
        PRD §2.3: "Every list response populates four pagination fields inside
        `meta`: `limit` and `offset` echo the effective values used for the page,
        `total_count` reports how many rows matched the filters before the page
        window was applied, and `has_more` is true exactly when rows matching the
        filters remain beyond the current window."
        PRD §2.3: "Unless a subsection of §3 states a different ordering for a
        particular collection, list results are sorted by `created_at` ascending."

        Design: Corner/entities/reagent_lot_listing_is_paginated_with_total_count_and_has_more
        """
        product, lots = self._twelve_lots(api)
        assert len(lots) == 12

        rows, meta = validate_paginated(api.list_reagent_lots(
            DISTRIBUTION_PLANNER,
            params={"product_specification_id": product["id"]}))
        # Twelve matching rows against the declared default page size of 10.
        assertions.assert_paginated_meta(meta, expected_limit=10,
                                        expected_offset=0, expected_total=12,
                                        expected_has_more=True)
        assert len(rows) == 10, (
            f"the default window holds ten rows, got {len(rows)}")
        assertions.assert_sorted_by_created_at(rows)
        for row in rows:
            assert row["product_specification_id"] == product["id"]

    def test_reagent_lot_listing_offset_page_completes_the_collection(self, api):
        """PRD §2.3: "`offset` controls the starting position: its default is 0
        and its minimum accepted value is 0, with no upper bound."
        PRD §2.3: "Every list response populates four pagination fields inside
        `meta`: `limit` and `offset` echo the effective values used for the page,
        `total_count` reports how many rows matched the filters before the page
        window was applied, and `has_more` is true exactly when rows matching the
        filters remain beyond the current window."

        Design: Corner/entities/reagent_lot_listing_is_paginated_with_total_count_and_has_more
        """
        product, lots = self._twelve_lots(api)
        listing_filter = {"product_specification_id": product["id"]}

        first_rows, first_meta = validate_paginated(api.list_reagent_lots(
            DISTRIBUTION_PLANNER, params=dict(listing_filter, limit=10, offset=0)))
        second_rows, second_meta = validate_paginated(api.list_reagent_lots(
            DISTRIBUTION_PLANNER, params=dict(listing_filter, limit=10, offset=10)))

        assertions.assert_paginated_meta(first_meta, expected_limit=10,
                                        expected_offset=0, expected_total=12,
                                        expected_has_more=True)
        # Two rows remain beyond offset 10, so nothing is left after them.
        assertions.assert_paginated_meta(second_meta, expected_limit=10,
                                        expected_offset=10, expected_total=12,
                                        expected_has_more=False)
        assert len(second_rows) == 2, (
            f"the offset page holds the remaining two rows, got {len(second_rows)}")
        assertions.assert_sorted_by_created_at(second_rows)

        first_ids = [row["id"] for row in first_rows]
        second_ids = [row["id"] for row in second_rows]
        assert set(first_ids).isdisjoint(second_ids), (
            "offset paging must not repeat a row")
        assert set(first_ids) | set(second_ids) == {lot["id"] for lot in lots}, (
            "the two pages together must cover all twelve lots")

    def test_reagent_lot_listing_rejects_a_limit_outside_the_declared_range(self, api):
        """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a
        malformed request and is rejected with `ERR_INVALID_REQUEST` and HTTP 400
        rather than silently clamped."

        Design: Corner/entities/reagent_lot_listing_is_paginated_with_total_count_and_has_more
        """
        product, _lots = self._twelve_lots(api)
        listing_filter = {"product_specification_id": product["id"]}

        # 0 is below the declared minimum of 1.
        validate_error(api.list_reagent_lots(
            DISTRIBUTION_PLANNER, params=dict(listing_filter, limit=0)),
            "ERR_INVALID_REQUEST", 400)
        # 101 is above the declared maximum of 100.
        validate_error(api.list_reagent_lots(
            DISTRIBUTION_PLANNER, params=dict(listing_filter, limit=101)),
            "ERR_INVALID_REQUEST", 400)

        # The boundary values themselves are accepted, so the range is inclusive.
        _rows, meta = validate_paginated(api.list_reagent_lots(
            DISTRIBUTION_PLANNER, params=dict(listing_filter, limit=1)))
        assertions.assert_paginated_meta(meta, expected_limit=1,
                                        expected_total=12,
                                        expected_has_more=True)
        rows, meta = validate_paginated(api.list_reagent_lots(
            DISTRIBUTION_PLANNER, params=dict(listing_filter, limit=100)))
        assertions.assert_paginated_meta(meta, expected_limit=100,
                                        expected_total=12,
                                        expected_has_more=False)
        assert len(rows) == 12


class TestLotComponentJunction:
    """The dispensing row hangs off both of its parents."""

    def test_lot_component_is_listable_from_the_finished_lot_and_the_material_lot(self, api):
        """PRD §3.3: "Each successful call creates a dispensing row whose
        `reagent_lot_id` points at the finished lot, whose `status` starts as
        `CONSUMED`, and whose two snapshot fields are copied at creation time:
        `material_code_snapshot` takes the `material_code` of the consumed lot's
        specification, and `vendor_lot_code_snapshot` takes the consumed lot's
        `vendor_lot_code`."
        PRD §3.3: "The dispensing rows of a finished lot are listable and
        filterable by `status` and by `component_role`."
        PRD §3.2: "Every dispensing record ever drawn from a raw material lot
        remains readable against that lot, `CONSUMED` and `RETURNED` rows alike,
        filterable by `status`."

        Design: Corner/entities/lot_component_junction_is_reachable_from_both_of_its_parents
        """
        bundle = fixtures.reagent_lot_with_bom(
            api, material_types=("ANTIBODY",), cleared=False,
            lot_overrides={"lot_code": "ENT-LOT-3", "planned_units": 300},
            quantity_used=250.0)
        material_spec = bundle["materials"][0]["spec"]
        material_lot = bundle["materials"][0]["lot"]
        dispensed = bundle["components"][0]

        from_finished_lot, finished_meta = validate_paginated(
            api.list_reagent_lot_components(bundle["lot"]["id"], QA_RELEASER))
        from_material_lot, material_meta = validate_paginated(
            api.list_material_lot_components(material_lot["id"], QA_RELEASER))

        assertions.assert_paginated_meta(finished_meta, expected_total=1)
        assertions.assert_paginated_meta(material_meta, expected_total=1)
        assert len(from_finished_lot) == 1 and len(from_material_lot) == 1
        row_from_finished_lot = from_finished_lot[0]
        row_from_material_lot = from_material_lot[0]
        assert row_from_finished_lot["id"] == dispensed["id"]
        assert row_from_material_lot["id"] == dispensed["id"], (
            "both parents must reach the same dispensing row")
        assert row_from_finished_lot == row_from_material_lot, (
            "the same row read from either side must carry the same fields")

        for row in (row_from_finished_lot, row_from_material_lot):
            assertions.assert_lot_component(row)
            assert row["reagent_lot_id"] == bundle["lot"]["id"]
            assert row["material_lot_id"] == material_lot["id"]
            assert row["component_role"] == "ANTIBODY"
            assert row["quantity_used"] == 250.0
            assert row["status"] == "CONSUMED"
            assert row["material_code_snapshot"] == material_spec["material_code"]
            assert row["vendor_lot_code_snapshot"] == material_lot["vendor_lot_code"]


class TestPathSubjectNotFound:
    """A syntactically valid but unknown path identifier answers with the
    aggregate's own not-found code."""

    def test_material_specification_get_with_unknown_id_returns_its_own_code(self, api):
        """PRD §2.6: "All not-found conditions carry HTTP 404."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/material_specification_not_found_on_get_returns_404
        """
        validate_error(
            api.get_material_specification(NON_EXISTENT_UUID, REGULATORY_AFFAIRS),
            "ERR_MATERIAL_SPECIFICATION_NOT_FOUND", 404)

    def test_material_lot_disposition_with_unknown_id_precedes_the_state_check(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/material_lot_not_found_on_disposition_returns_404
        """
        # Path existence sits at rung 40 and the lot state check at rung 60, so
        # the unknown subject is reported rather than the state.
        validate_error(
            api.disposition_material_lot(
                NON_EXISTENT_UUID,
                factories.material_lot_disposition_payload("QUALIFY"),
                QA_RELEASER),
            "ERR_MATERIAL_LOT_NOT_FOUND", 404)

    def test_design_control_record_approve_with_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "All not-found conditions carry HTTP 404."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/design_control_record_not_found_on_approve_returns_404
        """
        validate_error(
            api.approve_design_control_record(NON_EXISTENT_UUID, QA_RELEASER),
            "ERR_DESIGN_CONTROL_RECORD_NOT_FOUND", 404)

    def test_reagent_lot_components_add_with_unknown_lot_precedes_the_version_guard(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/reagent_lot_not_found_on_components_add_returns_404
        """
        spec = fixtures.create_material_specification(api)
        material_lot = fixtures.create_material_lot(api, spec["id"])
        product = fixtures.create_product_specification(api)
        real_lot = fixtures.create_reagent_lot(api, product["id"])

        # The version guard is well formed and matches the real lot, so only the
        # path subject is unknown: rung 40 answers before the rung 65 guard.
        payload = factories.lot_component_payload(
            material_lot["id"], "ANTIBODY", real_lot["version"],
            quantity_used=10.0)
        validate_error(
            api.add_reagent_lot_component(NON_EXISTENT_UUID, payload,
                                          PRODUCTION_OPERATOR),
            "ERR_REAGENT_LOT_NOT_FOUND", 404)

        untouched = validate_success(
            api.get_reagent_lot(real_lot["id"], PRODUCTION_OPERATOR), HTTP_OK)
        assert untouched["version"] == real_lot["version"]
        rows, meta = validate_paginated(
            api.list_reagent_lot_components(real_lot["id"], PRODUCTION_OPERATOR))
        assertions.assert_paginated_meta(meta, expected_total=0)
        assert rows == [], "a rejected dispensing call must persist no row"

    def test_fill_run_start_with_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "All not-found conditions carry HTTP 404."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/fill_run_not_found_on_start_returns_404
        """
        validate_error(
            api.start_fill_run(NON_EXISTENT_UUID, PRODUCTION_OPERATOR),
            "ERR_FILL_RUN_NOT_FOUND", 404)

    def test_test_result_get_with_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "All not-found conditions carry HTTP 404."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/test_result_not_found_on_get_returns_404
        """
        validate_error(api.get_test_result(NON_EXISTENT_UUID, QC_ANALYST),
                       "ERR_TEST_RESULT_NOT_FOUND", 404)


class TestActionSubjectNotFound:
    """Action endpoints answer with their subject's not-found code rather than
    with the state or data error their own gates would raise."""

    def test_bridging_study_decision_with_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/bridging_study_not_found_on_decision_returns_404
        """
        # The body is complete, so nothing above rung 40 can fire first.
        validate_error(
            api.decide_bridging_study(
                NON_EXISTENT_UUID,
                factories.bridging_decision_payload("APPROVE"), QA_RELEASER),
            "ERR_BRIDGING_STUDY_NOT_FOUND", 404)

    def test_complaint_triage_with_unknown_id_creates_nothing(self, api):
        """PRD §2.6: "All not-found conditions carry HTTP 404."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/complaint_not_found_on_triage_returns_404
        """
        validate_error(
            api.triage_complaint(NON_EXISTENT_UUID,
                                 factories.triage_payload("HIGH", True),
                                 REGULATORY_AFFAIRS),
            "ERR_COMPLAINT_NOT_FOUND", 404)

        rows, meta = validate_paginated(
            api.list_complaints(REGULATORY_AFFAIRS, params={"limit": 100}))
        assertions.assert_paginated_meta(meta, expected_total=0)
        assert rows == [], "triaging an unknown id must not create a complaint"

    def test_distribution_order_allocate_with_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/distribution_order_not_found_on_allocate_returns_404
        """
        validate_error(
            api.allocate_distribution_order(NON_EXISTENT_UUID,
                                            DISTRIBUTION_PLANNER),
            "ERR_DISTRIBUTION_ORDER_NOT_FOUND", 404)

    def test_allocation_ship_with_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/entities/allocation_not_found_on_ship_returns_404
        """
        validate_error(api.ship_allocation(NON_EXISTENT_UUID,
                                           DISTRIBUTION_PLANNER),
                       "ERR_ALLOCATION_NOT_FOUND", 404)


class TestBodyForeignKeyNotFound:
    """A foreign key carried in the body is resolved with the same
    entity-specific not-found code as a path subject."""

    def test_reagent_lot_create_with_unknown_product_specification_returns_not_found(self, api):
        """PRD §2.6: "Every foreign key carried in a request body resolves to an
        existing row, checked in the order the fields are declared on the owning
        entity, otherwise the matching not-found code (404)."
        PRD §2.6: "The codes reachable here are
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND` and
        `ERR_STABILITY_STUDY_NOT_FOUND`."

        Design: Corner/entities/product_specification_not_found_on_reagent_lot_create_returns_404
        """
        payload = factories.reagent_lot_payload(NON_EXISTENT_UUID,
                                                lot_code="ENT-NF-1",
                                                planned_units=100)
        validate_error(api.create_reagent_lot(payload, PRODUCTION_OPERATOR),
                       "ERR_PRODUCT_SPECIFICATION_NOT_FOUND", 404)

        rows, meta = validate_paginated(
            api.list_reagent_lots(PRODUCTION_OPERATOR, params={"limit": 100}))
        assertions.assert_paginated_meta(meta, expected_total=0)
        assert rows == [], "a rejected create must persist no finished lot"

    def test_test_result_create_with_unknown_stability_study_returns_its_code(self, api):
        """PRD §3.6: "A `QCAnalyst` pulls a timepoint by recording a measurement
        with `subject_type` `STABILITY_TIMEPOINT`, the `stability_study_id`, the
        `month_index` of the timepoint, the `test_code` and the `measured_value`."
        PRD §2.6: "Every foreign key carried in a request body resolves to an
        existing row, checked in the order the fields are declared on the owning
        entity, otherwise the matching not-found code (404)."
        PRD §2.6: "The codes reachable here are
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND` and
        `ERR_STABILITY_STUDY_NOT_FOUND`."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."

        Design: Corner/entities/stability_study_not_found_on_timepoint_result_returns_404
        """
        # The subject kind selects which foreign key is resolved, so the study's
        # own code is expected rather than a raw-material or finished-lot code,
        # and rung 45 answers before the planned-timepoint check further down.
        payload = factories.stability_test_result_payload(
            NON_EXISTENT_UUID, 3, "ACTIVITY", 99.0)
        validate_error(api.create_test_result(payload, QC_ANALYST),
                       "ERR_STABILITY_STUDY_NOT_FOUND", 404)

        rows, meta = validate_paginated(
            api.list_test_results(QC_ANALYST, params={"limit": 100}))
        assertions.assert_paginated_meta(meta, expected_total=0)
        assert rows == [], "a rejected measurement must persist no row"
