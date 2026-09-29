"""The global validation precedence ladder of PRD §2.6.

Every test here drives a single request that breaks two or more rules at once and
pins the identifier the ladder says must answer, then removes the higher-ranked
violation and pins the identifier that surfaces underneath it.
"""
from test_helpers import factories, fixtures
from test_helpers.constants import (DEFAULT_CLOCK_UTC, clock_plus,
                                    parse_instant, shift)
from test_helpers.test_users import (DISTRIBUTION_PLANNER, EMPTY_ROLE_HEADERS,
                                     EMPTY_USER_ID_HEADERS,
                                     MISSING_ROLE_HEADERS,
                                     MISSING_USER_ID_HEADERS, NO_AUTH_HEADERS,
                                     PRODUCTION_OPERATOR,
                                     QA_RELEASER, QA_RELEASER_2,
                                     QA_RELEASER_USER_ID, QC_ANALYST,
                                     QC_ANALYST_2, QC_ANALYST_USER_ID,
                                     REGULATORY_AFFAIRS,
                                     REGULATORY_AFFAIRS_USER_ID,
                                     headers_for_role,
                                     make_qa_releaser_headers,
                                     make_qc_analyst_headers)
from prd_bench_local_runner.testing import (NON_EXISTENT_UUID, validate_error,
                                            validate_paginated,
                                            validate_success)

# The clock's documented starting instant, restated as the literals the
# boundary arithmetic below is built on.
CLOCK_START = DEFAULT_CLOCK_UTC                      # 2026-08-01T00:00:00.000Z
ONE_SECOND_BEFORE_START = shift(CLOCK_START, seconds=-1)


def _dispense(api, lot_id, material_lot_id, component_role, quantity_used):
    """One dispensing call with the concurrency guard read fresh, returned raw
    so a negative case can be inspected."""
    expected = fixtures.reagent_lot_version(api, lot_id)
    return api.add_reagent_lot_component(
        lot_id,
        factories.lot_component_payload(material_lot_id, component_role,
                                        expected, quantity_used=quantity_used),
        PRODUCTION_OPERATOR)


def _release(api, lot_id, headers=QA_RELEASER, **overrides):
    """A RELEASE disposition returned raw."""
    return api.disposition_reagent_lot(
        lot_id, factories.reagent_lot_disposition_payload("RELEASE",
                                                          **overrides),
        headers)


def _lot(api, lot_id):
    return validate_success(api.get_reagent_lot(lot_id, QA_RELEASER))


class TestAuthenticationOutranksEverything:
    """Rung 10 against the rungs below it."""

    def test_unauthenticated_creation_outranks_the_body_and_its_foreign_key(self, api):
        """PRD §2.1: "Every request to every endpoint — reads included — must carry
        two headers: `X-User-ID`, identifying the acting operator, and
        `X-User-Role`, naming that operator's role."
        PRD §2.1: "If either header is absent, or is present but empty, the request
        is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD §2.1: "Authentication is checked before authorization, and both are
        checked before the request body is examined at all."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."

        Design: Corner/validations/priority_10_unauthenticated_wins_over_role_existence_and_body_checks
        """
        payload = factories.material_lot_payload(NON_EXISTENT_UUID,
                                                 received_quantity_units=-5.0)
        validate_error(api.create_material_lot(payload, NO_AUTH_HEADERS),
                       "ERR_UNAUTHENTICATED", 401)

    def test_unauthenticated_read_outranks_path_existence(self, api):
        """PRD §2.1: "Every request to every endpoint — reads included — must carry
        two headers: `X-User-ID`, identifying the acting operator, and
        `X-User-Role`, naming that operator's role."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."
        PRD §2.6: "**Rung 10 — authentication (all endpoints).** `X-User-ID` and
        `X-User-Role` are both present and non-empty, otherwise
        `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/priority_10_unauthenticated_wins_over_role_existence_and_body_checks
        """
        validate_error(api.get_material_lot(NON_EXISTENT_UUID, NO_AUTH_HEADERS),
                       "ERR_UNAUTHENTICATED", 401)
        validate_error(api.get_reagent_lot(NON_EXISTENT_UUID, NO_AUTH_HEADERS),
                       "ERR_UNAUTHENTICATED", 401)

    def test_an_empty_header_value_is_as_unauthenticated_as_a_missing_one(self, api):
        """PRD §2.1: "If either header is absent, or is present but empty, the
        request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."

        Design: Corner/validations/priority_10_unauthenticated_wins_over_role_existence_and_body_checks
        """
        payload = factories.material_lot_disposition_payload("NOT_A_DECISION")
        for headers in (MISSING_USER_ID_HEADERS, MISSING_ROLE_HEADERS,
                        EMPTY_USER_ID_HEADERS, EMPTY_ROLE_HEADERS):
            validate_error(
                api.disposition_material_lot(NON_EXISTENT_UUID, payload,
                                             headers),
                "ERR_UNAUTHENTICATED", 401)

    def test_unauthenticated_listing_outranks_a_broken_page_window(self, api):
        """PRD §2.1: "Every request to every endpoint — reads included — must carry
        two headers: `X-User-ID`, identifying the acting operator, and
        `X-User-Role`, naming that operator's role."
        PRD §2.1: "Authentication is checked before authorization, and both are
        checked before the request body is examined at all."
        PRD §2.6: "**Rung 10 — authentication (all endpoints).** `X-User-ID` and
        `X-User-Role` are both present and non-empty, otherwise
        `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/priority_10_unauthenticated_wins_over_role_existence_and_body_checks
        """
        validate_error(
            api.list_material_lots(EMPTY_USER_ID_HEADERS,
                                   params={"limit": 0, "offset": -1}),
            "ERR_UNAUTHENTICATED", 401)


class TestForbiddenRoleOutranksNotFoundAndBody:
    """Rung 20 against the rungs below it."""

    def test_forbidden_role_outranks_an_invalid_body(self, api):
        """PRD §2.1: "Authentication is checked before authorization, and both are
        checked before the request body is examined at all."
        PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD §2.6: "**Rung 20 — authorization (all endpoints).** `X-User-Role` is
        one of the six declared role names and is among the roles the endpoint
        grants, otherwise `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/validations/priority_20_forbidden_role_wins_over_not_found_and_invalid_request
        """
        payload = factories.material_specification_payload(
            material_type="NOT_A_MATERIAL_TYPE",
            potency_min_pct=110.0,
            potency_max_pct=90.0,
            required_test_codes=[])
        validate_error(api.create_material_specification(payload, QC_ANALYST),
                       "ERR_FORBIDDEN_ROLE", 403)

    def test_forbidden_role_outranks_path_existence(self, api):
        """PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."
        PRD §2.6: "**Rung 40 — path existence (every endpoint with a path
        parameter).** Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/validations/priority_20_forbidden_role_wins_over_not_found_and_invalid_request
        """
        validate_error(
            api.disposition_material_lot(
                NON_EXISTENT_UUID,
                factories.material_lot_disposition_payload("QUALIFY"),
                DISTRIBUTION_PLANNER),
            "ERR_FORBIDDEN_ROLE", 403)

    def test_a_role_name_outside_the_enumeration_is_forbidden_not_unauthenticated(self, api):
        """PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD §2.6: "**Rung 20 — authorization (all endpoints).** `X-User-Role` is
        one of the six declared role names and is among the roles the endpoint
        grants, otherwise `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/validations/priority_20_forbidden_role_wins_over_not_found_and_invalid_request
        """
        auditor = headers_for_role("Auditor", "user-auditor-001")
        payload = factories.reagent_lot_payload(NON_EXISTENT_UUID,
                                                planned_units=0)
        validate_error(api.create_reagent_lot(payload, auditor),
                       "ERR_FORBIDDEN_ROLE", 403)
        validate_error(api.get_reagent_lot(NON_EXISTENT_UUID, auditor),
                       "ERR_FORBIDDEN_ROLE", 403)


class TestRequestShapeOutranksForeignKeys:
    """Rung 30 against rung 45."""

    def test_a_zero_received_quantity_outranks_the_missing_specification(self, api):
        """PRD §2.6: "The body parses as JSON, every required input field is
        present, every enum-typed value is a declared member of its enumeration,
        `limit` lies between 1 and 100 inclusive and `offset` is at least 0, and
        every numeric bound holds: `received_quantity_units` is greater than 0,
        `quantity_used` is greater than 0, `requested_units` is greater than 0,
        `planned_units` is greater than 0, `planned_fill_units` is greater than 0,
        `potency_min_pct` is greater than 0 and strictly less than
        `potency_max_pct`, `endotoxin_max_eu_per_ml` is greater than 0,
        `max_retests` is at least 0, `shelf_life_months_claim` is greater than 0,
        `baseline_value` is greater than 0, `scheduled_end` is strictly later than
        `scheduled_start`, `protocol_end` is strictly later than `protocol_start`,
        `required_min_shelf_life_days` is at least 0, `result_value` is at least 0,
        and `reference_measured_value` is greater than 0 whenever it is present."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."
        PRD §2.6: "**Rung 45 — body foreign-key existence.** Every foreign key
        carried in a request body resolves to an existing row, checked in the order
        the fields are declared on the owning entity, otherwise the matching
        not-found code (404)."

        Design: Corner/validations/priority_30_invalid_request_wins_over_foreign_key_existence
        """
        payload = factories.material_lot_payload(NON_EXISTENT_UUID,
                                                 received_quantity_units=0.0)
        validate_error(api.create_material_lot(payload, PRODUCTION_OPERATOR),
                       "ERR_INVALID_REQUEST", 400)

    def test_an_inverted_potency_window_is_rejected_at_the_shape_rung(self, api):
        """PRD §2.6: "The body parses as JSON, every required input field is
        present, every enum-typed value is a declared member of its enumeration,
        `limit` lies between 1 and 100 inclusive and `offset` is at least 0, and
        every numeric bound holds: `received_quantity_units` is greater than 0,
        `quantity_used` is greater than 0, `requested_units` is greater than 0,
        `planned_units` is greater than 0, `planned_fill_units` is greater than 0,
        `potency_min_pct` is greater than 0 and strictly less than
        `potency_max_pct`, `endotoxin_max_eu_per_ml` is greater than 0,
        `max_retests` is at least 0, `shelf_life_months_claim` is greater than 0,
        `baseline_value` is greater than 0, `scheduled_end` is strictly later than
        `scheduled_start`, `protocol_end` is strictly later than `protocol_start`,
        `required_min_shelf_life_days` is at least 0, `result_value` is at least 0,
        and `reference_measured_value` is greater than 0 whenever it is present."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/priority_30_invalid_request_wins_over_foreign_key_existence
        """
        inverted = factories.material_specification_payload(
            potency_min_pct=110.0, potency_max_pct=90.0)
        validate_error(
            api.create_material_specification(inverted, REGULATORY_AFFAIRS),
            "ERR_INVALID_REQUEST", 400)
        # The bound is strict, so an equal pair is refused on the same rung.
        equal = factories.material_specification_payload(
            potency_min_pct=100.0, potency_max_pct=100.0)
        validate_error(
            api.create_material_specification(equal, REGULATORY_AFFAIRS),
            "ERR_INVALID_REQUEST", 400)

    def test_an_inverted_schedule_outranks_the_missing_finished_lot(self, api):
        """PRD §2.6: "The body parses as JSON, every required input field is
        present, every enum-typed value is a declared member of its enumeration,
        `limit` lies between 1 and 100 inclusive and `offset` is at least 0, and
        every numeric bound holds: `received_quantity_units` is greater than 0,
        `quantity_used` is greater than 0, `requested_units` is greater than 0,
        `planned_units` is greater than 0, `planned_fill_units` is greater than 0,
        `potency_min_pct` is greater than 0 and strictly less than
        `potency_max_pct`, `endotoxin_max_eu_per_ml` is greater than 0,
        `max_retests` is at least 0, `shelf_life_months_claim` is greater than 0,
        `baseline_value` is greater than 0, `scheduled_end` is strictly later than
        `scheduled_start`, `protocol_end` is strictly later than `protocol_start`,
        `required_min_shelf_life_days` is at least 0, `result_value` is at least 0,
        and `reference_measured_value` is greater than 0 whenever it is present."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."
        PRD §2.6: "**Rung 45 — body foreign-key existence.** Every foreign key
        carried in a request body resolves to an existing row, checked in the order
        the fields are declared on the owning entity, otherwise the matching
        not-found code (404)."

        Design: Corner/validations/priority_30_invalid_request_wins_over_foreign_key_existence
        """
        payload = factories.fill_run_payload(
            NON_EXISTENT_UUID,
            scheduled_start=clock_plus(days=2),
            scheduled_end=clock_plus(days=1))
        validate_error(api.create_fill_run(payload, PRODUCTION_OPERATOR),
                       "ERR_INVALID_REQUEST", 400)

    def test_a_broken_timepoint_sequence_outranks_the_missing_parents(self, api):
        """PRD §2.6: "Array inputs `required_test_codes`,
        `required_material_codes`, `release_test_codes`, `paired_test_codes` and
        `planned_timepoints_months` must be non-empty, `material_code` must be
        between 3 and 32 characters long, and `planned_timepoints_months` must be a
        strictly increasing sequence of integers whose first element is 0."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."
        PRD §2.6: "**Rung 45 — body foreign-key existence.** Every foreign key
        carried in a request body resolves to an existing row, checked in the order
        the fields are declared on the owning entity, otherwise the matching
        not-found code (404)."

        Design: Corner/validations/priority_30_invalid_request_wins_over_foreign_key_existence
        """
        # First element is not 0.
        not_from_zero = factories.stability_study_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            planned_timepoints_months=[3, 6, 9])
        validate_error(
            api.create_stability_study(not_from_zero, REGULATORY_AFFAIRS),
            "ERR_INVALID_REQUEST", 400)
        # Not strictly increasing.
        repeated = factories.stability_study_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            planned_timepoints_months=[0, 3, 3])
        validate_error(
            api.create_stability_study(repeated, REGULATORY_AFFAIRS),
            "ERR_INVALID_REQUEST", 400)
        # Empty.
        empty = factories.stability_study_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, planned_timepoints_months=[])
        validate_error(api.create_stability_study(empty, REGULATORY_AFFAIRS),
                       "ERR_INVALID_REQUEST", 400)

    def test_order_unit_bounds_outrank_the_missing_product_specification(self, api):
        """PRD §2.6: "The body parses as JSON, every required input field is
        present, every enum-typed value is a declared member of its enumeration,
        `limit` lies between 1 and 100 inclusive and `offset` is at least 0, and
        every numeric bound holds: `received_quantity_units` is greater than 0,
        `quantity_used` is greater than 0, `requested_units` is greater than 0,
        `planned_units` is greater than 0, `planned_fill_units` is greater than 0,
        `potency_min_pct` is greater than 0 and strictly less than
        `potency_max_pct`, `endotoxin_max_eu_per_ml` is greater than 0,
        `max_retests` is at least 0, `shelf_life_months_claim` is greater than 0,
        `baseline_value` is greater than 0, `scheduled_end` is strictly later than
        `scheduled_start`, `protocol_end` is strictly later than `protocol_start`,
        `required_min_shelf_life_days` is at least 0, `result_value` is at least 0,
        and `reference_measured_value` is greater than 0 whenever it is present."
        PRD §2.6: "Any violation yields `ERR_INVALID_REQUEST` (400)."
        PRD §2.6: "**Rung 45 — body foreign-key existence.** Every foreign key
        carried in a request body resolves to an existing row, checked in the order
        the fields are declared on the owning entity, otherwise the matching
        not-found code (404)."

        Design: Corner/validations/priority_30_invalid_request_wins_over_foreign_key_existence
        """
        no_units = factories.distribution_order_payload(NON_EXISTENT_UUID,
                                                        requested_units=0)
        validate_error(
            api.create_distribution_order(no_units, DISTRIBUTION_PLANNER),
            "ERR_INVALID_REQUEST", 400)
        negative_floor = factories.distribution_order_payload(
            NON_EXISTENT_UUID, required_min_shelf_life_days=-1)
        validate_error(
            api.create_distribution_order(negative_floor, DISTRIBUTION_PLANNER),
            "ERR_INVALID_REQUEST", 400)


class TestSubjectFieldCoherenceOutranksForeignKeys:
    """Rung 35 against rungs 40 and 45."""

    def test_a_material_lot_result_may_not_carry_a_finished_lot(self, api):
        """PRD §3.1: "A `MATERIAL_LOT` measurement must carry `material_lot_id` and
        must **not** carry `reagent_lot_id`, `stability_study_id`, `month_index` or
        `reference_measured_value`; a payload that violates that shape is refused
        with `ERR_SUBJECT_FIELD_MISMATCH`."
        PRD §2.6: "**Rung 35 — subject-field coherence, on `POST /test-results`
        only.** The record carries exactly the subject fields its `subject_type`
        demands, otherwise `ERR_SUBJECT_FIELD_MISMATCH` (400)."
        PRD §2.6: "**Rung 45 — body foreign-key existence.** Every foreign key
        carried in a request body resolves to an existing row, checked in the order
        the fields are declared on the owning entity, otherwise the matching
        not-found code (404)."

        Design: Corner/validations/priority_35_subject_field_mismatch_rejects_each_wrong_test_result_shape
        """
        payload = factories.material_test_result_payload(
            NON_EXISTENT_UUID, "POTENCY", 100.0,
            reagent_lot_id=NON_EXISTENT_UUID)
        validate_error(api.create_test_result(payload, QC_ANALYST),
                       "ERR_SUBJECT_FIELD_MISMATCH", 400)

    def test_a_material_lot_result_may_not_carry_a_reference_value(self, api):
        """PRD §3.1: "A `MATERIAL_LOT` measurement must carry `material_lot_id` and
        must **not** carry `reagent_lot_id`, `stability_study_id`, `month_index` or
        `reference_measured_value`; a payload that violates that shape is refused
        with `ERR_SUBJECT_FIELD_MISMATCH`."
        PRD §2.6: "**Rung 35 — subject-field coherence, on `POST /test-results`
        only.** The record carries exactly the subject fields its `subject_type`
        demands, otherwise `ERR_SUBJECT_FIELD_MISMATCH` (400)."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."

        Design: Corner/validations/priority_35_subject_field_mismatch_rejects_each_wrong_test_result_shape
        """
        payload = factories.material_test_result_payload(
            NON_EXISTENT_UUID, "POTENCY", 100.0, reference_measured_value=100.0)
        validate_error(api.create_test_result(payload, QC_ANALYST),
                       "ERR_SUBJECT_FIELD_MISMATCH", 400)

    def test_a_material_lot_result_may_not_carry_a_stability_timepoint(self, api):
        """PRD §3.1: "A `MATERIAL_LOT` measurement must carry `material_lot_id` and
        must **not** carry `reagent_lot_id`, `stability_study_id`, `month_index` or
        `reference_measured_value`; a payload that violates that shape is refused
        with `ERR_SUBJECT_FIELD_MISMATCH`."
        PRD §2.6: "**Rung 35 — subject-field coherence, on `POST /test-results`
        only.** The record carries exactly the subject fields its `subject_type`
        demands, otherwise `ERR_SUBJECT_FIELD_MISMATCH` (400)."

        Design: Corner/validations/priority_35_subject_field_mismatch_rejects_each_wrong_test_result_shape
        """
        payload = factories.material_test_result_payload(
            NON_EXISTENT_UUID, "POTENCY", 100.0,
            stability_study_id=NON_EXISTENT_UUID, month_index=0)
        validate_error(api.create_test_result(payload, QC_ANALYST),
                       "ERR_SUBJECT_FIELD_MISMATCH", 400)

    def test_a_release_result_may_not_carry_a_raw_material_lot(self, api):
        """PRD §3.5: "A `REAGENT_LOT` measurement must carry both `reagent_lot_id`
        and `reference_measured_value` and must **not** carry `material_lot_id`,
        `stability_study_id` or `month_index`; violating that shape yields
        `ERR_SUBJECT_FIELD_MISMATCH`, and a `reference_measured_value` that is
        present but not greater than 0 yields `ERR_INVALID_REQUEST`."
        PRD §2.6: "**Rung 35 — subject-field coherence, on `POST /test-results`
        only.** The record carries exactly the subject fields its `subject_type`
        demands, otherwise `ERR_SUBJECT_FIELD_MISMATCH` (400)."
        PRD §2.6: "**Rung 45 — body foreign-key existence.** Every foreign key
        carried in a request body resolves to an existing row, checked in the order
        the fields are declared on the owning entity, otherwise the matching
        not-found code (404)."

        Design: Corner/validations/priority_35_subject_field_mismatch_rejects_each_wrong_test_result_shape
        """
        payload = factories.release_test_result_payload(
            NON_EXISTENT_UUID, "ACTIVITY", 100.0, 100.0,
            material_lot_id=NON_EXISTENT_UUID)
        validate_error(api.create_test_result(payload, QC_ANALYST),
                       "ERR_SUBJECT_FIELD_MISMATCH", 400)
        month = factories.release_test_result_payload(
            NON_EXISTENT_UUID, "ACTIVITY", 100.0, 100.0, month_index=0)
        validate_error(api.create_test_result(month, QC_ANALYST),
                       "ERR_SUBJECT_FIELD_MISMATCH", 400)

    def test_a_stability_timepoint_may_not_carry_a_reference_value_or_a_lot(self, api):
        """PRD §3.6: "Such a record must carry both `stability_study_id` and
        `month_index` and must **not** carry `material_lot_id`, `reagent_lot_id` or
        `reference_measured_value`, on pain of `ERR_SUBJECT_FIELD_MISMATCH`."
        PRD §2.6: "**Rung 35 — subject-field coherence, on `POST /test-results`
        only.** The record carries exactly the subject fields its `subject_type`
        demands, otherwise `ERR_SUBJECT_FIELD_MISMATCH` (400)."
        PRD §2.6: "**Rung 45 — body foreign-key existence.** Every foreign key
        carried in a request body resolves to an existing row, checked in the order
        the fields are declared on the owning entity, otherwise the matching
        not-found code (404)."

        Design: Corner/validations/priority_35_subject_field_mismatch_rejects_each_wrong_test_result_shape
        """
        with_reference = factories.stability_test_result_payload(
            NON_EXISTENT_UUID, 0, "ACTIVITY", 95.0,
            reference_measured_value=100.0)
        validate_error(api.create_test_result(with_reference, QC_ANALYST),
                       "ERR_SUBJECT_FIELD_MISMATCH", 400)
        with_material_lot = factories.stability_test_result_payload(
            NON_EXISTENT_UUID, 0, "ACTIVITY", 95.0,
            material_lot_id=NON_EXISTENT_UUID)
        validate_error(api.create_test_result(with_material_lot, QC_ANALYST),
                       "ERR_SUBJECT_FIELD_MISMATCH", 400)


class TestDutySeparationOutranksStateAndClearance:
    """Rung 50 against rungs 60 and 130, over all three guarded comparisons."""

    def test_the_analyst_who_measured_may_not_release_but_a_clean_releaser_reaches_clearance(self, api):
        """PRD §2.9: "When a finished lot is dispositioned — whether the decision is
        `RELEASE` or `REJECT` — the acting `X-User-ID` must differ from
        `performed_by_user_id` on **every** release measurement recorded against
        that lot."
        PRD §2.6: "**Rung 50 — segregation of duties.** Exactly three endpoints are
        guarded: `POST /reagent-lots/{id}/disposition`,
        `POST /complaints/{id}/field-action` and
        `POST /design-control-records/{id}/approve`."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."
        PRD §3.5: "For a release the remaining gates are evaluated in this exact
        order, so an operator always learns about the most serious defect first: no
        run of the lot may have `environmental_state` `DISQUALIFIED`
        (`ERR_ENVIRONMENTAL_NONCONFORMANCE`); every code in `release_test_codes`
        must have a measurement on the lot whose `outcome` is `PASS`
        (`ERR_RELEASE_TESTS_INCOMPLETE`); `release_bias_max_pct` must be at most
        `max_reference_bias_pct`, inclusively (`ERR_REFERENCE_BIAS_EXCEEDED`); every
        code in the product's `required_material_codes` must appear as the
        `material_code_snapshot` of a dispensing row of this lot whose `status` is
        `CONSUMED` (`ERR_BOM_INCOMPLETE`); when `bridging_required` is true a
        bridging study naming this lot as its candidate must exist in `status`
        `APPROVED` (`ERR_BRIDGING_REQUIRED`); when the requested `shelf_life_basis`
        is `REAL_TIME` or `ACCELERATED` a stability study on this product with that
        `study_type`, `status` `COMPLETE` and a non-null
        `established_shelf_life_months` must exist (`ERR_STABILITY_DATA_MISSING`);
        and last of all, the product's `clearance_status` must be `CLEARED`
        (`ERR_PRODUCT_NOT_CLEARED`)."

        Design: Corner/validations/priority_50_segregation_of_duties_blocks_the_tester_from_releasing_and_the_author_from_approving
        """
        bundle = fixtures.lot_under_release_test(api, cleared=False)
        lot_id = bundle["lot"]["id"]
        # The releasing identity collides with the analyst who produced the data.
        colliding = make_qa_releaser_headers(QC_ANALYST_USER_ID)
        validate_error(_release(api, lot_id, headers=colliding),
                       "ERR_SEGREGATION_OF_DUTIES", 403)
        # Remove only the duty-separation violation: the clearance gate answers.
        validate_error(_release(api, lot_id, headers=QA_RELEASER),
                       "ERR_PRODUCT_NOT_CLEARED", 409)
        assert _lot(api, lot_id)["disposition_status"] == "UNDER_RELEASE_TEST"

    def test_a_rejection_is_bound_by_duty_separation_as_well(self, api):
        """PRD §2.9: "When a finished lot is dispositioned — whether the decision is
        `RELEASE` or `REJECT` — the acting `X-User-ID` must differ from
        `performed_by_user_id` on **every** release measurement recorded against
        that lot."
        PRD §3.5: "A `REJECT` decision needs only the `UNDER_RELEASE_TEST` state and
        the duty separation check."
        PRD §3.5: "It sets `disposition_status` to the terminal `REJECTED`, forces
        `available_units` to 0, leaves `distribution_status` at `WITHHELD`, and
        increases `version` by 1."

        Design: Corner/validations/priority_50_segregation_of_duties_blocks_the_tester_from_releasing_and_the_author_from_approving
        """
        bundle = fixtures.lot_under_release_test(api)
        lot_id = bundle["lot"]["id"]
        reject = factories.reagent_lot_disposition_payload("REJECT")
        validate_error(
            api.disposition_reagent_lot(
                lot_id, reject, make_qa_releaser_headers(QC_ANALYST_USER_ID)),
            "ERR_SEGREGATION_OF_DUTIES", 403)
        rejected = validate_success(
            api.disposition_reagent_lot(lot_id, reject, QA_RELEASER))
        assert rejected["disposition_status"] == "REJECTED"
        assert rejected["distribution_status"] == "WITHHELD"

    def test_one_matching_release_measurement_is_enough_to_refuse_the_disposition(self, api):
        """PRD §2.9: "One matching measurement is enough to refuse the disposition;
        the analyst who generated the release data may not be the releaser who signs
        it off."
        PRD §2.9: "When a finished lot is dispositioned — whether the decision is
        `RELEASE` or `REJECT` — the acting `X-User-ID` must differ from
        `performed_by_user_id` on **every** release measurement recorded against
        that lot."

        Design: Corner/validations/priority_50_segregation_of_duties_blocks_the_tester_from_releasing_and_the_author_from_approving
        """
        bundle = fixtures.filled_reagent_lot(api)
        lot_id = bundle["lot"]["id"]
        codes = bundle["product"]["release_test_codes"]
        # Only the second of the two measurements shares the releaser's identity.
        fixtures.record_release_measurement(api, lot_id, codes[0],
                                            headers=QC_ANALYST_2)
        fixtures.record_release_measurement(
            api, lot_id, codes[1],
            headers=make_qc_analyst_headers(QA_RELEASER_USER_ID))
        validate_error(_release(api, lot_id, headers=QA_RELEASER),
                       "ERR_SEGREGATION_OF_DUTIES", 403)
        # A third releaser shares no identity with either analyst and gets through.
        released = validate_success(_release(api, lot_id, headers=QA_RELEASER_2))
        assert released["disposition_status"] == "RELEASED"

    def test_an_author_may_not_approve_their_own_controlled_document(self, api):
        """PRD §2.9: "When a design-control record is approved, the acting
        `X-User-ID` must differ from that record's `authored_by_user_id`."
        PRD §2.9: "An author may not approve their own controlled document."
        PRD §2.6: "**Rung 50 — segregation of duties.** Exactly three endpoints are
        guarded: `POST /reagent-lots/{id}/disposition`,
        `POST /complaints/{id}/field-action` and
        `POST /design-control-records/{id}/approve`."

        Design: Corner/validations/priority_50_segregation_of_duties_blocks_the_tester_from_releasing_and_the_author_from_approving
        """
        product = fixtures.create_product_specification(api)
        record = fixtures.file_design_record(api, product["id"], "DESIGN_INPUT",
                                             headers=REGULATORY_AFFAIRS)
        validate_error(
            api.approve_design_control_record(
                record["id"],
                make_qa_releaser_headers(REGULATORY_AFFAIRS_USER_ID)),
            "ERR_SEGREGATION_OF_DUTIES", 403)
        approved = validate_success(
            api.approve_design_control_record(record["id"], QA_RELEASER))
        assert approved["status"] == "APPROVED"

    def test_the_releaser_of_a_lot_may_not_decide_its_field_action(self, api):
        """PRD §2.9: "When a complaint's field action is decided, the acting
        `X-User-ID` must differ from `released_by_user_id` on the implicated
        finished lot."
        PRD §2.9: "The releaser who put a lot on the market may not be the person
        who decides whether to correct or remove it from the field."

        Design: Corner/validations/priority_50_segregation_of_duties_blocks_the_tester_from_releasing_and_the_author_from_approving
        """
        bundle = fixtures.complaint_on_released_lot(api,
                                                    releaser_headers=QA_RELEASER)
        complaint_id = bundle["complaint"]["id"]
        assert bundle["lot"]["released_by_user_id"] == QA_RELEASER_USER_ID
        validate_error(
            api.decide_field_action(
                complaint_id, factories.field_action_payload("ADVISORY"),
                make_qa_releaser_headers(QA_RELEASER_USER_ID)),
            "ERR_SEGREGATION_OF_DUTIES", 403)
        decided = validate_success(
            api.decide_field_action(complaint_id,
                                    factories.field_action_payload("ADVISORY"),
                                    QA_RELEASER_2))
        assert decided["field_action"] == "ADVISORY"

    def test_duty_separation_answers_before_the_state_check_on_an_approved_record(self, api):
        """PRD §2.9: "When a design-control record is approved, the acting
        `X-User-ID` must differ from that record's `authored_by_user_id`."
        PRD §2.6: "Because this rung sits above the state rung, an operator who is
        disqualified by duty separation is told so even when the target resource is
        also in the wrong state."

        Design: Corner/validations/priority_50_segregation_of_duties_blocks_the_tester_from_releasing_and_the_author_from_approving
        """
        product = fixtures.create_product_specification(api)
        record = fixtures.file_design_record(api, product["id"], "DESIGN_INPUT",
                                             headers=REGULATORY_AFFAIRS)
        fixtures.approve_design_record(api, record["id"], QA_RELEASER)
        # Already APPROVED, so the state rung would also refuse this request.
        validate_error(
            api.approve_design_control_record(
                record["id"],
                make_qa_releaser_headers(REGULATORY_AFFAIRS_USER_ID)),
            "ERR_SEGREGATION_OF_DUTIES", 403)

    def test_duty_separation_answers_before_the_state_check_on_a_released_lot(self, api):
        """PRD §3.5: "Both decisions require the lot's `disposition_status` to be
        `UNDER_RELEASE_TEST` and both are bound by the duty separation of §2.9,
        which is answered before the state check."
        PRD §2.6: "Because this rung sits above the state rung, an operator who is
        disqualified by duty separation is told so even when the target resource is
        also in the wrong state."

        Design: Corner/validations/priority_50_segregation_of_duties_blocks_the_tester_from_releasing_and_the_author_from_approving
        """
        bundle = fixtures.released_reagent_lot(api)
        lot_id = bundle["lot"]["id"]
        assert bundle["lot"]["disposition_status"] == "RELEASED"
        validate_error(
            _release(api, lot_id,
                     headers=make_qa_releaser_headers(QC_ANALYST_USER_ID)),
            "ERR_SEGREGATION_OF_DUTIES", 403)
        # With a clean identity the same request falls through to the state rung.
        validate_error(_release(api, lot_id, headers=QA_RELEASER_2),
                       "ERR_REAGENT_LOT_STATE_INVALID", 409)


class TestScopedUniqueness:
    """Rung 70, one test per declared uniqueness scope."""

    def test_a_material_code_is_unique_across_the_whole_catalogue(self, api):
        """PRD §3.1: "A `RegulatoryAffairs` user (or a `PlatformAdmin` maintaining
        reference data) registers one specification per raw material, identified by a
        `material_code` between 3 and 32 characters long that must be unique across
        the whole catalogue — a repeat registration is refused with
        `ERR_DUPLICATE_MATERIAL_CODE`."
        PRD §2.6: "**Rung 70 — scoped uniqueness.** `material_code` is unique across
        all raw material specifications (`ERR_DUPLICATE_MATERIAL_CODE`);
        `product_code` is unique across all product specifications
        (`ERR_DUPLICATE_PRODUCT_CODE`); the pair of `material_specification_id` and
        `vendor_lot_code` is unique across raw material lots
        (`ERR_DUPLICATE_VENDOR_LOT`); the pair of `product_specification_id` and
        `lot_code` is unique across finished lots (`ERR_DUPLICATE_LOT_CODE`); and the
        triple of `stability_study_id`, `month_index` and `test_code` is unique
        across test results (`ERR_DUPLICATE_TIMEPOINT`)."

        Design: Corner/validations/priority_70_duplicate_business_keys_are_rejected_in_their_declared_scopes
        """
        first = fixtures.create_material_specification(api)
        duplicate = factories.material_specification_payload(
            material_code=first["material_code"], material_type="ENZYME")
        validate_error(
            api.create_material_specification(duplicate, REGULATORY_AFFAIRS),
            "ERR_DUPLICATE_MATERIAL_CODE", 409)

    def test_a_product_code_is_unique_across_the_catalogue(self, api):
        """PRD §3.2: "Its `product_code` is unique across the catalogue and a repeat
        is refused with `ERR_DUPLICATE_PRODUCT_CODE`."
        PRD §2.6: "**Rung 70 — scoped uniqueness.** `material_code` is unique across
        all raw material specifications (`ERR_DUPLICATE_MATERIAL_CODE`);
        `product_code` is unique across all product specifications
        (`ERR_DUPLICATE_PRODUCT_CODE`); the pair of `material_specification_id` and
        `vendor_lot_code` is unique across raw material lots
        (`ERR_DUPLICATE_VENDOR_LOT`); the pair of `product_specification_id` and
        `lot_code` is unique across finished lots (`ERR_DUPLICATE_LOT_CODE`); and the
        triple of `stability_study_id`, `month_index` and `test_code` is unique
        across test results (`ERR_DUPLICATE_TIMEPOINT`)."

        Design: Corner/validations/priority_70_duplicate_business_keys_are_rejected_in_their_declared_scopes
        """
        first = fixtures.create_product_specification(api)
        duplicate = factories.product_specification_payload(
            product_code=first["product_code"])
        validate_error(
            api.create_product_specification(duplicate, REGULATORY_AFFAIRS),
            "ERR_DUPLICATE_PRODUCT_CODE", 409)

    def test_a_vendor_lot_code_is_unique_only_inside_one_specification(self, api):
        """PRD §3.1: "A `vendor_lot_code` may repeat across different specifications
        but not within one — the pairing is unique, and a collision is refused with
        `ERR_DUPLICATE_VENDOR_LOT`."

        Design: Corner/validations/priority_70_duplicate_business_keys_are_rejected_in_their_declared_scopes
        """
        spec_a = fixtures.create_material_specification(api)
        spec_b = fixtures.create_material_specification(api)
        shared = factories.unique_vendor_lot_code()
        fixtures.create_material_lot(api, spec_a["id"], vendor_lot_code=shared)
        collision = factories.material_lot_payload(spec_a["id"],
                                                   vendor_lot_code=shared)
        validate_error(
            api.create_material_lot(collision, PRODUCTION_OPERATOR),
            "ERR_DUPLICATE_VENDOR_LOT", 409)
        # The same vendor code under a different specification is a fresh pairing.
        elsewhere = fixtures.create_material_lot(api, spec_b["id"],
                                                 vendor_lot_code=shared)
        assert elsewhere["vendor_lot_code"] == shared

    def test_a_lot_code_is_unique_only_inside_one_product(self, api):
        """PRD §3.3: "A `lot_code` may be reused across different products but not
        twice within one product; a collision on that pairing is refused with
        `ERR_DUPLICATE_LOT_CODE`."

        Design: Corner/validations/priority_70_duplicate_business_keys_are_rejected_in_their_declared_scopes
        """
        product_a = fixtures.create_product_specification(api)
        product_b = fixtures.create_product_specification(api)
        shared = factories.unique_lot_code()
        fixtures.create_reagent_lot(api, product_a["id"], lot_code=shared)
        collision = factories.reagent_lot_payload(product_a["id"],
                                                  lot_code=shared)
        validate_error(api.create_reagent_lot(collision, PRODUCTION_OPERATOR),
                       "ERR_DUPLICATE_LOT_CODE", 409)
        elsewhere = fixtures.create_reagent_lot(api, product_b["id"],
                                                lot_code=shared)
        assert elsewhere["lot_code"] == shared


def _approved_study(api, months=(0, 3, 6)):
    """A stability protocol in APPROVED over the requested planned months."""
    product = fixtures.create_product_specification(api)
    lot = fixtures.create_reagent_lot(api, product["id"])
    study = fixtures.create_stability_study(
        api, product["id"], lot["id"],
        planned_timepoints_months=list(months))
    return fixtures.approve_stability_protocol(api, study["id"])


class TestStabilityTimepointGates:
    """Rungs 70 and 121 on a stability timepoint, and the state rung above them."""

    def test_a_month_index_outside_the_protocol_is_refused(self, api):
        """PRD §3.6: "The `month_index` must be a member of the study's
        `planned_timepoints_months`, otherwise `ERR_TIMEPOINT_NOT_PLANNED` with HTTP
        422, and the combination of `stability_study_id`, `month_index` and
        `test_code` must not already exist, otherwise `ERR_DUPLICATE_TIMEPOINT`."
        PRD §3.6: "The first timepoint advances the study from `APPROVED` to
        `IN_PROGRESS`; each subsequent timepoint is a self-loop on `IN_PROGRESS` and
        additionally requires that no measurement with the same `stability_study_id`,
        `month_index` and `test_code` already exists."

        Design: Corner/validations/stability_timepoint_gates_reject_an_unplanned_month_and_a_duplicate_measurement
        """
        study = _approved_study(api, months=(0, 3, 6))
        unplanned = factories.stability_test_result_payload(
            study["id"], 4, "ACTIVITY", 100.0)
        validate_error(api.create_test_result(unplanned, QC_ANALYST),
                       "ERR_TIMEPOINT_NOT_PLANNED", 422)
        # A planned month is accepted and moves the study on.
        fixtures.record_timepoint(api, study["id"], 0, 100.0, "ACTIVITY")
        in_progress = validate_success(
            api.get_stability_study(study["id"], REGULATORY_AFFAIRS))
        assert in_progress["status"] == "IN_PROGRESS"
        # The gate applies to the self-loop exactly as it did to the first hop.
        validate_error(api.create_test_result(unplanned, QC_ANALYST),
                       "ERR_TIMEPOINT_NOT_PLANNED", 422)

    def test_the_study_month_and_code_triple_is_unique_but_a_second_code_is_free(self, api):
        """PRD §3.6: "The `month_index` must be a member of the study's
        `planned_timepoints_months`, otherwise `ERR_TIMEPOINT_NOT_PLANNED` with HTTP
        422, and the combination of `stability_study_id`, `month_index` and
        `test_code` must not already exist, otherwise `ERR_DUPLICATE_TIMEPOINT`."
        PRD §2.6: "**Rung 70 — scoped uniqueness.** `material_code` is unique across
        all raw material specifications (`ERR_DUPLICATE_MATERIAL_CODE`);
        `product_code` is unique across all product specifications
        (`ERR_DUPLICATE_PRODUCT_CODE`); the pair of `material_specification_id` and
        `vendor_lot_code` is unique across raw material lots
        (`ERR_DUPLICATE_VENDOR_LOT`); the pair of `product_specification_id` and
        `lot_code` is unique across finished lots (`ERR_DUPLICATE_LOT_CODE`); and the
        triple of `stability_study_id`, `month_index` and `test_code` is unique
        across test results (`ERR_DUPLICATE_TIMEPOINT`)."
        PRD §3.6: "Both hops recompute `timepoint_count` — the count of measurements
        carrying this `stability_study_id` — and `last_conforming_month`, and both
        increase the study's `version` by 1."

        Design: Corner/validations/stability_timepoint_gates_reject_an_unplanned_month_and_a_duplicate_measurement
        """
        study = _approved_study(api, months=(0, 3, 6))
        fixtures.record_timepoint(api, study["id"], 0, 100.0, "ACTIVITY")
        repeat = factories.stability_test_result_payload(
            study["id"], 0, "ACTIVITY", 99.0)
        validate_error(api.create_test_result(repeat, QC_ANALYST),
                       "ERR_DUPLICATE_TIMEPOINT", 409)
        # Only the whole triple is claimed, so a second code at month 0 is free.
        fixtures.record_timepoint(api, study["id"], 0, 97.0, "PRECISION")
        after = validate_success(
            api.get_stability_study(study["id"], REGULATORY_AFFAIRS))
        assert after["timepoint_count"] == 2

    def test_the_state_rung_answers_before_the_unplanned_month_gate(self, api):
        """PRD §3.6: "A `QAReleaser` approves the protocol, which moves `status` from
        `PROTOCOL_DRAFT` to `APPROVED`, records `protocol_approved_by_user_id`, and
        increases `version` by 1."
        PRD §3.6: "Only then may timepoints be pulled; a timepoint against a study
        still in `PROTOCOL_DRAFT` is refused with `ERR_STABILITY_STUDY_STATE_INVALID`."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."

        Design: Corner/validations/stability_timepoint_gates_reject_an_unplanned_month_and_a_duplicate_measurement
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        study = fixtures.create_stability_study(
            api, product["id"], lot["id"], planned_timepoints_months=[0, 3, 6])
        assert study["status"] == "PROTOCOL_DRAFT"
        unplanned = factories.stability_test_result_payload(
            study["id"], 4, "ACTIVITY", 100.0)
        validate_error(api.create_test_result(unplanned, QC_ANALYST),
                       "ERR_STABILITY_STUDY_STATE_INVALID", 409)
        # Approving the protocol lets the same request reach the month gate.
        fixtures.approve_stability_protocol(api, study["id"])
        validate_error(api.create_test_result(unplanned, QC_ANALYST),
                       "ERR_TIMEPOINT_NOT_PLANNED", 422)


def _qualify(api, spec, lot):
    """Carry one raw material lot to QUALIFIED on passing acceptance data."""
    fixtures.record_passing_material_tests(api, lot["id"], spec)
    return fixtures.ok(api.disposition_material_lot(
        lot["id"], factories.material_lot_disposition_payload("QUALIFY"),
        QA_RELEASER))


def _dispensing_bench(api):
    """A finished lot whose bill of materials names one antibody code, plus four
    raw material lots each breaking a different dispensing gate."""
    antibody = fixtures.create_material_specification(api,
                                                      material_type="ANTIBODY")
    enzyme = fixtures.create_material_specification(api, material_type="ENZYME")
    product = fixtures.create_product_specification(
        api, required_material_codes=[antibody["material_code"]])
    lot = fixtures.create_reagent_lot(api, product["id"])
    yesterday = shift(CLOCK_START, days=-1)          # 2026-07-31T00:00:00.000Z
    received = fixtures.create_material_lot(api, antibody["id"],
                                            received_quantity_units=100.0,
                                            expiry_date=yesterday)
    expired = _qualify(api, antibody, fixtures.create_material_lot(
        api, antibody["id"], received_quantity_units=100.0,
        expiry_date=yesterday))
    at_clock = _qualify(api, antibody, fixtures.create_material_lot(
        api, antibody["id"], received_quantity_units=100.0,
        expiry_date=CLOCK_START))
    good = _qualify(api, antibody, fixtures.create_material_lot(
        api, antibody["id"], received_quantity_units=100.0,
        expiry_date=clock_plus(days=365)))
    off_bom = _qualify(api, enzyme, fixtures.create_material_lot(
        api, enzyme["id"], received_quantity_units=100.0,
        expiry_date=clock_plus(days=365)))
    return {"product": product, "lot": lot, "received": received,
            "expired": expired, "at_clock": at_clock, "good": good,
            "off_bom": off_bom}


class TestDispensingGateOrder:
    """Rungs 75, 76, 78 and 123 in the order §3.3 pins."""

    def test_the_qualification_gate_answers_before_expiry_sufficiency_and_the_slot(self, api):
        """PRD §3.3: "The raw material lot must be in `qualification_status`
        `QUALIFIED`, otherwise `ERR_MATERIAL_NOT_QUALIFIED`."
        PRD §3.3: "Because the structural check sits last, a request that dispenses
        an unqualified lot into the wrong slot is told about the qualification
        failure, not the slot."
        PRD §3.3: "Four safety gates guard every dispensing call, and their order is
        deliberate."

        Design: Corner/validations/material_dispensing_gates_at_priorities_75_76_78_and_123_fire_in_the_declared_order
        """
        bench = _dispensing_bench(api)
        assert bench["received"]["qualification_status"] == "RECEIVED"
        # Unqualified, expired, over-drawn and dispensed into the wrong slot.
        validate_error(_dispense(api, bench["lot"]["id"],
                                 bench["received"]["id"], "ENZYME", 500.0),
                       "ERR_MATERIAL_NOT_QUALIFIED", 409)

    def test_the_expiry_gate_answers_before_sufficiency_and_the_slot(self, api):
        """PRD §3.3: "Its `expiry_date` must be strictly after the logical clock at
        the moment of dispensing — an expiry instant equal to the clock is already
        expired — otherwise `ERR_MATERIAL_EXPIRED`."
        PRD §3.3: "Four safety gates guard every dispensing call, and their order is
        deliberate."

        Design: Corner/validations/material_dispensing_gates_at_priorities_75_76_78_and_123_fire_in_the_declared_order
        """
        bench = _dispensing_bench(api)
        lot_id = bench["lot"]["id"]
        # Qualified but expired, over-drawn and in the wrong slot at once.
        validate_error(_dispense(api, lot_id, bench["expired"]["id"], "ENZYME",
                                 500.0),
                       "ERR_MATERIAL_EXPIRED", 409)
        # An expiry instant equal to the clock is already past.
        validate_error(_dispense(api, lot_id, bench["at_clock"]["id"],
                                 "ANTIBODY", 10.0),
                       "ERR_MATERIAL_EXPIRED", 409)

    def test_the_sufficiency_gate_answers_before_the_structural_check(self, api):
        """PRD §3.3: "The `quantity_used` must be no greater than the raw lot's
        `available_quantity_units`, and an inclusive equality is fine; exceeding it
        yields `ERR_INSUFFICIENT_MATERIAL`."
        PRD §3.3: "Finally the structural check: the `component_role` supplied must
        equal the `material_type` of the dispensed lot's specification, **and** that
        specification's `material_code` must be a member of the product's
        `required_material_codes`; a mismatch on either half yields
        `ERR_COMPONENT_ROLE_NOT_IN_BOM` with HTTP 422."

        Design: Corner/validations/material_dispensing_gates_at_priorities_75_76_78_and_123_fire_in_the_declared_order
        """
        bench = _dispensing_bench(api)
        lot_id = bench["lot"]["id"]
        # 500 exceeds the 100 available, and the slot is wrong as well.
        validate_error(_dispense(api, lot_id, bench["good"]["id"], "ENZYME",
                                 500.0),
                       "ERR_INSUFFICIENT_MATERIAL", 409)

    def test_the_structural_check_covers_both_the_role_and_the_catalogue_half(self, api):
        """PRD §3.3: "Finally the structural check: the `component_role` supplied
        must equal the `material_type` of the dispensed lot's specification, **and**
        that specification's `material_code` must be a member of the product's
        `required_material_codes`; a mismatch on either half yields
        `ERR_COMPONENT_ROLE_NOT_IN_BOM` with HTTP 422."

        Design: Corner/validations/material_dispensing_gates_at_priorities_75_76_78_and_123_fire_in_the_declared_order
        """
        bench = _dispensing_bench(api)
        lot_id = bench["lot"]["id"]
        # Role matches the material type, but the code is not in this product's
        # bill of materials.
        validate_error(_dispense(api, lot_id, bench["off_bom"]["id"], "ENZYME",
                                 10.0),
                       "ERR_COMPONENT_ROLE_NOT_IN_BOM", 422)
        # Code is in the bill of materials, but the role names another type.
        validate_error(_dispense(api, lot_id, bench["good"]["id"], "BUFFER",
                                 10.0),
                       "ERR_COMPONENT_ROLE_NOT_IN_BOM", 422)

    def test_dispensing_exactly_the_available_quantity_is_accepted(self, api):
        """PRD §3.3: "The `quantity_used` must be no greater than the raw lot's
        `available_quantity_units`, and an inclusive equality is fine; exceeding it
        yields `ERR_INSUFFICIENT_MATERIAL`."
        PRD §3.3: "A successful dispensing call moves quantity across the raw
        material ledger: the raw lot's `consumed_quantity_units` increases by
        `quantity_used` and its `available_quantity_units` decreases by the same
        amount, keeping `received_quantity_units` equal to the sum of the two."

        Design: Corner/validations/material_dispensing_gates_at_priorities_75_76_78_and_123_fire_in_the_declared_order
        """
        bench = _dispensing_bench(api)
        row = validate_success(_dispense(api, bench["lot"]["id"],
                                         bench["good"]["id"], "ANTIBODY",
                                         100.0), 201)
        assert row["status"] == "CONSUMED"
        drawn = validate_success(api.get_material_lot(bench["good"]["id"],
                                                      QC_ANALYST))
        assert float(drawn["available_quantity_units"]) == 0.0
        assert float(drawn["consumed_quantity_units"]) == 100.0
        # Nothing is left, so a further draw of any size is now insufficient.
        validate_error(_dispense(api, bench["lot"]["id"], bench["good"]["id"],
                                 "ANTIBODY", 1.0),
                       "ERR_INSUFFICIENT_MATERIAL", 409)


def _uncleared_release_bench(api):
    """A FILLED lot of a two-material, two-test product whose specification has
    never been cleared, so the clearance gate waits at the bottom of the chain."""
    setup = fixtures.manufacturing_setup(
        api, material_types=("ANTIBODY", "ENZYME"), cleared=False,
        product_overrides={"release_test_codes": ["ACTIVITY", "PRECISION"],
                           "max_reference_bias_pct": 5.0})
    bundle = fixtures.filled_reagent_lot(api, setup)
    return bundle


class TestReleaseGateOrder:
    """Rungs 82, 84, 86 and 90 ahead of the rung 130 clearance gate."""

    def test_release_test_completeness_is_reported_before_the_clearance_gate(self, api):
        """PRD §3.5: "For a release the remaining gates are evaluated in this exact
        order, so an operator always learns about the most serious defect first: no
        run of the lot may have `environmental_state` `DISQUALIFIED`
        (`ERR_ENVIRONMENTAL_NONCONFORMANCE`); every code in `release_test_codes`
        must have a measurement on the lot whose `outcome` is `PASS`
        (`ERR_RELEASE_TESTS_INCOMPLETE`); `release_bias_max_pct` must be at most
        `max_reference_bias_pct`, inclusively (`ERR_REFERENCE_BIAS_EXCEEDED`); every
        code in the product's `required_material_codes` must appear as the
        `material_code_snapshot` of a dispensing row of this lot whose `status` is
        `CONSUMED` (`ERR_BOM_INCOMPLETE`); when `bridging_required` is true a
        bridging study naming this lot as its candidate must exist in `status`
        `APPROVED` (`ERR_BRIDGING_REQUIRED`); when the requested `shelf_life_basis`
        is `REAL_TIME` or `ACCELERATED` a stability study on this product with that
        `study_type`, `status` `COMPLETE` and a non-null
        `established_shelf_life_months` must exist (`ERR_STABILITY_DATA_MISSING`);
        and last of all, the product's `clearance_status` must be `CLEARED`
        (`ERR_PRODUCT_NOT_CLEARED`)."
        PRD §2.6: "This gate sits deliberately **below** every quality gate on the
        release decision: a lot with a failing bias, an incomplete bill of materials
        or missing bridging evidence reports that quality defect first, and only a
        lot that is otherwise releasable is told that its product has no clearance."

        Design: Corner/validations/release_gates_at_priorities_82_84_86_and_90_run_ahead_of_the_priority_130_clearance_gate
        """
        bundle = _uncleared_release_bench(api)
        lot_id = bundle["lot"]["id"]
        # Only one of the two required codes has been measured.
        fixtures.record_release_measurement(api, lot_id, "ACTIVITY")
        assert _lot(api, lot_id)["disposition_status"] == "UNDER_RELEASE_TEST"
        validate_error(_release(api, lot_id), "ERR_RELEASE_TESTS_INCOMPLETE",
                       409)

    def test_the_bias_gate_is_reported_once_completeness_is_satisfied(self, api):
        """PRD §3.5: "For a release the remaining gates are evaluated in this exact
        order, so an operator always learns about the most serious defect first: no
        run of the lot may have `environmental_state` `DISQUALIFIED`
        (`ERR_ENVIRONMENTAL_NONCONFORMANCE`); every code in `release_test_codes`
        must have a measurement on the lot whose `outcome` is `PASS`
        (`ERR_RELEASE_TESTS_INCOMPLETE`); `release_bias_max_pct` must be at most
        `max_reference_bias_pct`, inclusively (`ERR_REFERENCE_BIAS_EXCEEDED`); every
        code in the product's `required_material_codes` must appear as the
        `material_code_snapshot` of a dispensing row of this lot whose `status` is
        `CONSUMED` (`ERR_BOM_INCOMPLETE`); when `bridging_required` is true a
        bridging study naming this lot as its candidate must exist in `status`
        `APPROVED` (`ERR_BRIDGING_REQUIRED`); when the requested `shelf_life_basis`
        is `REAL_TIME` or `ACCELERATED` a stability study on this product with that
        `study_type`, `status` `COMPLETE` and a non-null
        `established_shelf_life_months` must exist (`ERR_STABILITY_DATA_MISSING`);
        and last of all, the product's `clearance_status` must be `CLEARED`
        (`ERR_PRODUCT_NOT_CLEARED`)."
        PRD §3.5: "For each code in the product's `release_test_codes`, the system
        takes the single latest release measurement on this lot bearing that code,
        ranked by `performed_at` descending and then by `created_at` descending;
        codes with no measurement are skipped, and measurements whose `test_code` is
        outside `release_test_codes` never enter."

        Design: Corner/validations/release_gates_at_priorities_82_84_86_and_90_run_ahead_of_the_priority_130_clearance_gate
        """
        bundle = _uncleared_release_bench(api)
        lot_id = bundle["lot"]["id"]
        fixtures.record_release_measurement(api, lot_id, "ACTIVITY")
        fixtures.record_release_measurement(api, lot_id, "PRECISION")
        # A later PRECISION measurement biased 10.00% becomes the latest for that
        # code: |110 - 100| / 100 * 100 = 10.00, above the product's 5.0 ceiling.
        fixtures.set_clock(api, clock_plus(hours=1))
        fixtures.record_release_measurement(api, lot_id, "PRECISION", 110.0,
                                            100.0)
        lot = _lot(api, lot_id)
        assert float(lot["release_bias_max_pct"]) == 10.00
        validate_error(_release(api, lot_id), "ERR_REFERENCE_BIAS_EXCEEDED", 409)

    def test_stability_evidence_and_then_clearance_answer_last(self, api):
        """PRD §3.5: "For a release the remaining gates are evaluated in this exact
        order, so an operator always learns about the most serious defect first: no
        run of the lot may have `environmental_state` `DISQUALIFIED`
        (`ERR_ENVIRONMENTAL_NONCONFORMANCE`); every code in `release_test_codes`
        must have a measurement on the lot whose `outcome` is `PASS`
        (`ERR_RELEASE_TESTS_INCOMPLETE`); `release_bias_max_pct` must be at most
        `max_reference_bias_pct`, inclusively (`ERR_REFERENCE_BIAS_EXCEEDED`); every
        code in the product's `required_material_codes` must appear as the
        `material_code_snapshot` of a dispensing row of this lot whose `status` is
        `CONSUMED` (`ERR_BOM_INCOMPLETE`); when `bridging_required` is true a
        bridging study naming this lot as its candidate must exist in `status`
        `APPROVED` (`ERR_BRIDGING_REQUIRED`); when the requested `shelf_life_basis`
        is `REAL_TIME` or `ACCELERATED` a stability study on this product with that
        `study_type`, `status` `COMPLETE` and a non-null
        `established_shelf_life_months` must exist (`ERR_STABILITY_DATA_MISSING`);
        and last of all, the product's `clearance_status` must be `CLEARED`
        (`ERR_PRODUCT_NOT_CLEARED`)."
        PRD §3.5: "A successful release is a two-hop cascade."

        Design: Corner/validations/release_gates_at_priorities_82_84_86_and_90_run_ahead_of_the_priority_130_clearance_gate
        """
        bundle = _uncleared_release_bench(api)
        lot_id = bundle["lot"]["id"]
        fixtures.record_release_measurement(api, lot_id, "ACTIVITY")
        fixtures.record_release_measurement(api, lot_id, "PRECISION")
        # |101 - 100| / 100 * 100 = 1.00, so the bias gate is satisfied.
        fixtures.set_clock(api, clock_plus(hours=1))
        fixtures.record_release_measurement(api, lot_id, "PRECISION", 101.0,
                                            100.0)
        assert float(_lot(api, lot_id)["release_bias_max_pct"]) == 1.00
        # No stability study exists, so a real-time basis stops at that gate.
        validate_error(_release(api, lot_id, shelf_life_basis="REAL_TIME"),
                       "ERR_STABILITY_DATA_MISSING", 409)
        # The claim basis skips that gate and reaches the clearance gate last.
        validate_error(_release(api, lot_id, shelf_life_basis="CLAIM"),
                       "ERR_PRODUCT_NOT_CLEARED", 409)
        assert _lot(api, lot_id)["disposition_status"] == "UNDER_RELEASE_TEST"

    def test_an_incomplete_bill_of_materials_outranks_the_clearance_gate(self, api):
        """PRD §3.5: "For a release the remaining gates are evaluated in this exact
        order, so an operator always learns about the most serious defect first: no
        run of the lot may have `environmental_state` `DISQUALIFIED`
        (`ERR_ENVIRONMENTAL_NONCONFORMANCE`); every code in `release_test_codes`
        must have a measurement on the lot whose `outcome` is `PASS`
        (`ERR_RELEASE_TESTS_INCOMPLETE`); `release_bias_max_pct` must be at most
        `max_reference_bias_pct`, inclusively (`ERR_REFERENCE_BIAS_EXCEEDED`); every
        code in the product's `required_material_codes` must appear as the
        `material_code_snapshot` of a dispensing row of this lot whose `status` is
        `CONSUMED` (`ERR_BOM_INCOMPLETE`); when `bridging_required` is true a
        bridging study naming this lot as its candidate must exist in `status`
        `APPROVED` (`ERR_BRIDGING_REQUIRED`); when the requested `shelf_life_basis`
        is `REAL_TIME` or `ACCELERATED` a stability study on this product with that
        `study_type`, `status` `COMPLETE` and a non-null
        `established_shelf_life_months` must exist (`ERR_STABILITY_DATA_MISSING`);
        and last of all, the product's `clearance_status` must be `CLEARED`
        (`ERR_PRODUCT_NOT_CLEARED`)."
        PRD §2.6: "This gate sits deliberately **below** every quality gate on the
        release decision: a lot with a failing bias, an incomplete bill of materials
        or missing bridging evidence reports that quality defect first, and only a
        lot that is otherwise releasable is told that its product has no clearance."

        Design: Corner/validations/release_gates_at_priorities_82_84_86_and_90_run_ahead_of_the_priority_130_clearance_gate
        """
        setup = fixtures.manufacturing_setup(
            api, material_types=("ANTIBODY", "ENZYME"), cleared=False,
            product_overrides={"release_test_codes": ["ACTIVITY", "PRECISION"],
                               "max_reference_bias_pct": 5.0})
        lot = fixtures.create_reagent_lot(api, setup["product"]["id"])
        # Only the antibody half of the bill of materials is ever dispensed.
        fixtures.dispense_component(api, lot["id"],
                                    setup["materials"][0]["lot"]["id"],
                                    "ANTIBODY")
        run = fixtures.schedule_fill_run(api, lot["id"])
        fixtures.start_fill_run(api, run["id"])
        fixtures.record_bioburden_sample(api, run["id"])
        fixtures.complete_fill_run(api, run["id"], 1000)
        fixtures.record_release_measurement(api, lot["id"], "ACTIVITY")
        fixtures.record_release_measurement(api, lot["id"], "PRECISION")
        validate_error(_release(api, lot["id"]), "ERR_BOM_INCOMPLETE", 409)


def _complaint(api, complaint_id):
    return validate_success(api.get_complaint(complaint_id, REGULATORY_AFFAIRS))


def _field_action(api, complaint_id, field_action, headers=QA_RELEASER_2):
    return api.decide_field_action(
        complaint_id, factories.field_action_payload(field_action), headers)


class TestComplaintCloseAndFieldActionGates:
    """The two complaint rungs, 95 on the close and 96 on the field action, and
    the state rung that sits above both of them."""

    def test_a_reportable_complaint_cannot_close_before_the_report_is_filed(self, api):
        """PRD §3.8: "And when `reportable` is true, `reported_at` must not be
        null, so the reporting branch must also have run; a close attempted on a
        reportable complaint whose `reported_at` is still null is refused with
        `ERR_MALFUNCTION_REPORT_PENDING`."
        PRD §3.8: "A reportable complaint therefore closes only once **both**
        branches have run, in whichever order they ran."
        PRD §3.8: "The complaint's `status` becomes `MALFUNCTION_REPORTED` when
        it was `TRIAGED`, and **stays** `FIELD_ACTION_DECIDED` when the other
        branch has already run, so the field-action outcome is never overwritten
        by the report."

        Design: Corner/validations/complaint_close_and_field_action_gates_at_priorities_95_and_96_and_the_state_gate_ahead_of_them
        """
        bundle = fixtures.complaint_on_released_lot(api, severity="HIGH",
                                                    malfunction_suspected=True)
        complaint = bundle["complaint"]
        assert complaint["reportable"] is True
        # The field-action branch runs first; an ADVISORY stops before the recall.
        decided = fixtures.decide_field_action(api, complaint["id"], "ADVISORY")
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        assert decided["reported_at"] is None
        validate_error(api.close_complaint(complaint["id"], REGULATORY_AFFAIRS),
                       "ERR_MALFUNCTION_REPORT_PENDING", 409)
        assert _complaint(api, complaint["id"])["status"] == "FIELD_ACTION_DECIDED"

        reported = fixtures.file_malfunction_report(api, complaint["id"])
        assert reported["status"] == "FIELD_ACTION_DECIDED"
        assert reported["field_action"] == "ADVISORY"
        assert reported["reported_at"] is not None
        closed = validate_success(
            api.close_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert closed["status"] == "CLOSED"
        assert _complaint(api, complaint["id"])["status"] == "CLOSED"

    def test_the_close_gate_on_a_null_field_action_answers_before_the_pending_report(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §3.8: "The `field_action` must not be null, so the field-action
        branch must have run; a close attempted while `field_action` is still
        null is refused with `ERR_COMPLAINT_STATE_INVALID`."
        PRD §3.8: "And when `reportable` is true, `reported_at` must not be
        null, so the reporting branch must also have run; a close attempted on a
        reportable complaint whose `reported_at` is still null is refused with
        `ERR_MALFUNCTION_REPORT_PENDING`."

        Design: Corner/validations/complaint_close_and_field_action_gates_at_priorities_95_and_96_and_the_state_gate_ahead_of_them
        """
        bundle = fixtures.complaint_on_released_lot(api, severity="HIGH",
                                                    malfunction_suspected=True)
        complaint = bundle["complaint"]
        assert complaint["reportable"] is True
        assert complaint["field_action"] is None
        assert complaint["reported_at"] is None
        # Both close conditions are broken at once; the state code wins.
        validate_error(api.close_complaint(complaint["id"], REGULATORY_AFFAIRS),
                       "ERR_COMPLAINT_STATE_INVALID", 409)
        fixtures.decide_field_action(api, complaint["id"], "NONE")
        # Only the outstanding report is left, so now the later rung answers.
        validate_error(api.close_complaint(complaint["id"], REGULATORY_AFFAIRS),
                       "ERR_MALFUNCTION_REPORT_PENDING", 409)
        after = _complaint(api, complaint["id"])
        assert after["status"] == "FIELD_ACTION_DECIDED"
        assert after["field_action"] == "NONE"

    def test_a_removal_below_high_severity_is_refused_but_an_advisory_stands(self, api):
        """PRD §3.8: "It requires the complaint's `status` to be either
        `TRIAGED` or `MALFUNCTION_REPORTED`; it requires the acting `X-User-ID`
        to differ from the implicated lot's `released_by_user_id`, per §2.9, on
        pain of `ERR_SEGREGATION_OF_DUTIES`; and a `field_action` of `REMOVAL`
        additionally requires `severity` to be `HIGH`, failing which the request
        is refused with `ERR_FIELD_ACTION_NOT_JUSTIFIED`."
        PRD §3.8: "A `field_action` of `NONE` or `ADVISORY` stops there."
        PRD §3.8: "A suspected malfunction on a `LOW` or `MEDIUM` complaint with
        no alleged death or injury is therefore not reportable, and neither is a
        `HIGH`-severity complaint whose triage found no malfunction."

        Design: Corner/validations/complaint_close_and_field_action_gates_at_priorities_95_and_96_and_the_state_gate_ahead_of_them
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        complaint = fixtures.triaged_complaint(api, lot["id"], "MEDIUM", True)
        assert complaint["status"] == "TRIAGED"
        assert complaint["reportable"] is False
        validate_error(_field_action(api, complaint["id"], "REMOVAL"),
                       "ERR_FIELD_ACTION_NOT_JUSTIFIED", 409)
        refused = _complaint(api, complaint["id"])
        assert refused["status"] == "TRIAGED"
        assert refused["field_action"] is None

        decided = validate_success(_field_action(api, complaint["id"], "ADVISORY"))
        assert decided["field_action"] == "ADVISORY"
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        # Not reportable, so the close needs no report at all.
        closed = validate_success(
            api.close_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert closed["status"] == "CLOSED"

    def test_the_state_gate_answers_before_the_removal_justification_gate(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §3.8: "It requires the complaint's `status` to be either `TRIAGED`
        or `MALFUNCTION_REPORTED`; it requires the acting `X-User-ID` to differ
        from the implicated lot's `released_by_user_id`, per §2.9, on pain of
        `ERR_SEGREGATION_OF_DUTIES`; and a `field_action` of `REMOVAL`
        additionally requires `severity` to be `HIGH`, failing which the request
        is refused with `ERR_FIELD_ACTION_NOT_JUSTIFIED`."

        Design: Corner/validations/complaint_close_and_field_action_gates_at_priorities_95_and_96_and_the_state_gate_ahead_of_them
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        complaint = fixtures.create_complaint(api, lot["id"])
        assert complaint["status"] == "RECEIVED"
        assert complaint["severity"] is None
        # Untriaged and asking for a removal it could never justify: state wins.
        validate_error(_field_action(api, complaint["id"], "REMOVAL"),
                       "ERR_COMPLAINT_STATE_INVALID", 409)
        fixtures.triage_complaint(api, complaint["id"], "MEDIUM", True)
        # The state is admissible now, so the justification rung answers.
        validate_error(_field_action(api, complaint["id"], "REMOVAL"),
                       "ERR_FIELD_ACTION_NOT_JUSTIFIED", 409)
        assert _complaint(api, complaint["id"])["field_action"] is None

    def test_a_high_severity_removal_passes_the_justification_gate(self, api):
        """PRD §3.8: "It requires the complaint's `status` to be either
        `TRIAGED` or `MALFUNCTION_REPORTED`; it requires the acting `X-User-ID`
        to differ from the implicated lot's `released_by_user_id`, per §2.9, on
        pain of `ERR_SEGREGATION_OF_DUTIES`; and a `field_action` of `REMOVAL`
        additionally requires `severity` to be `HIGH`, failing which the request
        is refused with `ERR_FIELD_ACTION_NOT_JUSTIFIED`."

        Design: Corner/validations/complaint_close_and_field_action_gates_at_priorities_95_and_96_and_the_state_gate_ahead_of_them
        """
        bundle = fixtures.complaint_on_released_lot(api, severity="HIGH",
                                                    malfunction_suspected=True)
        complaint = bundle["complaint"]
        assert complaint["severity"] == "HIGH"
        decided = validate_success(_field_action(api, complaint["id"], "REMOVAL"))
        assert decided["field_action"] == "REMOVAL"
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        assert _complaint(api, complaint["id"])["field_action"] == "REMOVAL"


# The specification defaults are 1 retest and a 30-day window, so a lot whose
# first failure lands on the default clock instant may still be retested at
# 2026-08-31T00:00:00.000Z and no later.
RETEST_BOUNDARY = clock_plus(days=30)
PAST_RETEST_BOUNDARY = clock_plus(days=30, seconds=1)


def _material_lot(api, lot_id):
    return validate_success(api.get_material_lot(lot_id, QC_ANALYST))


def _retest(api, spec, lot_id, value=None, headers=QC_ANALYST):
    if value is None:
        value = fixtures.failing_value_for(spec, "PURITY")
    return api.create_test_result(
        factories.material_test_result_payload(lot_id, "PURITY", value,
                                               is_retest=True),
        headers)


def _investigate(api, lot_id):
    return validate_success(api.disposition_material_lot(
        lot_id, factories.material_lot_disposition_payload("INVESTIGATE"),
        QA_RELEASER))


def _oos_lot(api):
    bundle = fixtures.material_lot_in_oos_investigation(api)
    assert bundle["lot"]["qualification_status"] == "OOS_INVESTIGATION"
    assert bundle["lot"]["retest_count"] == 0
    assert parse_instant(bundle["lot"]["first_oos_at"]) == parse_instant(CLOCK_START)
    return bundle


class TestRetestWindowAheadOfRetestBudget:
    """Rung 104, the retest window, against rung 106, the retest budget."""

    def test_a_retest_on_the_window_boundary_instant_is_still_accepted(self, api):
        """PRD §3.1: "Three preconditions apply: the lot must actually be in
        `OOS_INVESTIGATION`, its `retest_count` must still be strictly below the
        specification's `max_retests`, and the logical clock must be no later
        than `first_oos_at` plus `retest_window_days` days — the boundary instant
        is still inside the window."
        PRD §3.1: "`retest_window_days` defaults to 30 and bounds how long after
        the first failure a retest may still be recorded."
        PRD §3.1: "A successful retest creates the measurement with `is_retest`
        true, increases `retest_count` by 1, returns `qualification_status` to
        `UNDER_TEST`, recomputes `acceptance_score` over the latest record per
        `test_code`, and increases the lot's `version` by 1."

        Design: Corner/validations/retest_window_at_priority_104_is_evaluated_before_the_retest_count_limit_at_priority_106
        """
        bundle = _oos_lot(api)
        lot_id = bundle["lot"]["id"]
        before = _material_lot(api, lot_id)
        fixtures.set_clock(api, RETEST_BOUNDARY)
        record = validate_success(
            _retest(api, bundle["spec"], lot_id,
                    fixtures.passing_value_for(bundle["spec"], "PURITY")), 201)
        assert record["is_retest"] is True
        after = _material_lot(api, lot_id)
        assert after["qualification_status"] == "UNDER_TEST"
        assert after["retest_count"] == 1
        assert after["version"] == before["version"] + 1

    def test_a_retest_one_second_past_the_window_is_refused(self, api):
        """PRD §3.1: "A retest recorded past that instant is refused with
        `ERR_RETEST_WINDOW_EXPIRED`; a retest attempted when `retest_count` has
        already reached `max_retests` is refused with
        `ERR_MAX_RETESTS_EXCEEDED`; and because the window rung sits above the
        budget rung, a retest that is both late and over budget is reported as
        out of window."
        PRD §3.1: "On each such record the server sets `first_oos_at` to that
        record's `performed_at` when the record's `outcome` is `FAIL` and
        `first_oos_at` was still null — the earliest failure anchors the retest
        clock and is never overwritten by a later failure."

        Design: Corner/validations/retest_window_at_priority_104_is_evaluated_before_the_retest_count_limit_at_priority_106
        """
        bundle = _oos_lot(api)
        lot_id = bundle["lot"]["id"]
        before = _material_lot(api, lot_id)
        assert before["retest_count"] == 0
        fixtures.set_clock(api, PAST_RETEST_BOUNDARY)
        validate_error(_retest(api, bundle["spec"], lot_id),
                       "ERR_RETEST_WINDOW_EXPIRED", 409)
        after = _material_lot(api, lot_id)
        assert after["qualification_status"] == "OOS_INVESTIGATION"
        assert after["retest_count"] == 0
        assert after["version"] == before["version"]

    def test_the_window_rung_answers_before_the_exhausted_retest_budget(self, api):
        """PRD §2.6: "Note the order: an out-of-window retest is reported as such
        even when the retest budget is also exhausted."
        PRD §3.1: "A retest recorded past that instant is refused with
        `ERR_RETEST_WINDOW_EXPIRED`; a retest attempted when `retest_count` has
        already reached `max_retests` is refused with
        `ERR_MAX_RETESTS_EXCEEDED`; and because the window rung sits above the
        budget rung, a retest that is both late and over budget is reported as
        out of window."
        PRD §3.1: "The cycle from `OOS_INVESTIGATION` to `UNDER_TEST` and back
        may repeat until `retest_count` reaches `max_retests`, at which point
        only `REJECT` remains available."

        Design: Corner/validations/retest_window_at_priority_104_is_evaluated_before_the_retest_count_limit_at_priority_106
        """
        bundle = _oos_lot(api)
        spec, lot_id = bundle["spec"], bundle["lot"]["id"]
        assert spec["max_retests"] == 1
        fixtures.set_clock(api, RETEST_BOUNDARY)
        # One retest spends the whole budget; it fails again, so the lot may go
        # back into investigation.
        validate_success(_retest(api, spec, lot_id), 201)
        spent = _material_lot(api, lot_id)
        assert spent["retest_count"] == 1
        assert spent["qualification_status"] == "UNDER_TEST"
        assert _investigate(api, lot_id)["qualification_status"] == "OOS_INVESTIGATION"

        # The clock still sits exactly on the boundary, so only the budget is
        # broken and the budget rung answers.
        validate_error(_retest(api, spec, lot_id),
                       "ERR_MAX_RETESTS_EXCEEDED", 409)
        fixtures.set_clock(api, PAST_RETEST_BOUNDARY)
        # Now the request is late as well as over budget, and the window wins.
        validate_error(_retest(api, spec, lot_id),
                       "ERR_RETEST_WINDOW_EXPIRED", 409)
        after = _material_lot(api, lot_id)
        assert after["retest_count"] == 1
        assert after["qualification_status"] == "OOS_INVESTIGATION"

    def test_the_state_rung_answers_before_the_retest_window(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §3.1: "From `OOS_INVESTIGATION`, a `QCAnalyst` closes the
        investigation by recording a measurement with `is_retest` set true, which
        returns the lot to `UNDER_TEST`."
        PRD §3.1: "A retest recorded past that instant is refused with
        `ERR_RETEST_WINDOW_EXPIRED`; a retest attempted when `retest_count` has
        already reached `max_retests` is refused with
        `ERR_MAX_RETESTS_EXCEEDED`; and because the window rung sits above the
        budget rung, a retest that is both late and over budget is reported as
        out of window."

        Design: Corner/validations/retest_window_at_priority_104_is_evaluated_before_the_retest_count_limit_at_priority_106
        """
        spec = fixtures.create_material_specification(api)
        lot = fixtures.create_material_lot(api, spec["id"])
        fixtures.record_material_measurement(
            api, lot["id"], "PURITY", fixtures.failing_value_for(spec, "PURITY"))
        under_test = _material_lot(api, lot["id"])
        assert under_test["qualification_status"] == "UNDER_TEST"
        assert parse_instant(under_test["first_oos_at"]) == parse_instant(CLOCK_START)

        fixtures.set_clock(api, PAST_RETEST_BOUNDARY)
        # Late and in the wrong state at once: the state rung answers.
        validate_error(_retest(api, spec, lot["id"]),
                       "ERR_MATERIAL_LOT_STATE_INVALID", 409)
        _investigate(api, lot["id"])
        validate_error(_retest(api, spec, lot["id"]),
                       "ERR_RETEST_WINDOW_EXPIRED", 409)
        assert _material_lot(api, lot["id"])["retest_count"] == 0


def _order(api, order_id):
    return validate_success(
        api.get_distribution_order(order_id, DISTRIBUTION_PLANNER))


def _reservations(api, order_id):
    rows, _meta = validate_paginated(
        api.list_distribution_order_allocations(order_id, DISTRIBUTION_PLANNER))
    return rows


class TestShipByDeadlineOnAllocation:
    """Rung 108, the ship-by deadline, and the rungs on either side of it."""

    def test_a_ship_by_on_the_clock_instant_is_still_allocatable(self, api):
        """PRD §3.9: "Two further gates precede the waterfall: the order's
        `ship_by` must not be earlier than the logical clock, failing which the
        answer is `ERR_SHIP_BY_PASSED`, and the product's `clearance_status` must
        be `CLEARED`, failing which the answer is `ERR_PRODUCT_NOT_CLEARED`."
        PRD §2.7: "Comparison boundaries are inclusive unless a rule explicitly
        says the comparison is strict."

        Design: Corner/validations/priority_108_allocate_rejects_a_passed_ship_by_and_treats_the_boundary_instant_as_valid
        """
        bundle = fixtures.released_reagent_lot(api)
        assert bundle["lot"]["disposition_status"] == "RELEASED"
        assert bundle["lot"]["distribution_status"] == "AVAILABLE"
        # The clock has not been moved, so a ship_by of the starting instant is
        # exactly on the boundary: not earlier than the clock.
        order = fixtures.create_distribution_order(api, bundle["product"]["id"],
                                                   requested_units=10,
                                                   ship_by=CLOCK_START)
        assert order["status"] == "DRAFT"
        allocated = validate_success(
            api.allocate_distribution_order(order["id"], DISTRIBUTION_PLANNER))
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_units"] == 10
        assert allocated["shortfall_units"] == 0
        rows = _reservations(api, order["id"])
        assert len(rows) == 1
        assert rows[0]["allocated_units"] == 10
        assert rows[0]["status"] == "RESERVED"

    def test_a_ship_by_one_second_behind_the_clock_is_refused(self, api):
        """PRD §3.9: "Two further gates precede the waterfall: the order's
        `ship_by` must not be earlier than the logical clock, failing which the
        answer is `ERR_SHIP_BY_PASSED`, and the product's `clearance_status` must
        be `CLEARED`, failing which the answer is `ERR_PRODUCT_NOT_CLEARED`."
        PRD §3.9: "Orders are created in `status` `DRAFT` with `allocated_units`
        and `shortfall_units` both 0 and `planner_user_id` stamped from the acting
        operator."

        Design: Corner/validations/priority_108_allocate_rejects_a_passed_ship_by_and_treats_the_boundary_instant_as_valid
        """
        bundle = fixtures.released_reagent_lot(api)
        order = fixtures.create_distribution_order(api, bundle["product"]["id"],
                                                   requested_units=10,
                                                   ship_by=CLOCK_START)
        fixtures.set_clock(api, shift(CLOCK_START, seconds=1))
        validate_error(
            api.allocate_distribution_order(order["id"], DISTRIBUTION_PLANNER),
            "ERR_SHIP_BY_PASSED", 409)
        after = _order(api, order["id"])
        assert after["status"] == "DRAFT"
        assert after["allocated_units"] == 0
        assert after["shortfall_units"] == 0
        assert _reservations(api, order["id"]) == []
        lot = _lot(api, bundle["lot"]["id"])
        assert lot["allocated_units"] == 0
        assert lot["distribution_status"] == "AVAILABLE"

    def test_the_ship_by_gate_answers_before_the_clearance_gate(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §3.9: "Two further gates precede the waterfall: the order's
        `ship_by` must not be earlier than the logical clock, failing which the
        answer is `ERR_SHIP_BY_PASSED`, and the product's `clearance_status` must
        be `CLEARED`, failing which the answer is `ERR_PRODUCT_NOT_CLEARED`."

        Design: Corner/validations/priority_108_allocate_rejects_a_passed_ship_by_and_treats_the_boundary_instant_as_valid
        """
        product = fixtures.create_product_specification(api)
        assert product["clearance_status"] == "DESIGN"
        # Neither order can ever be filled — the product has no released lot —
        # and neither product is cleared, so several rungs are broken at once.
        stale = fixtures.create_distribution_order(api, product["id"],
                                                    requested_units=10,
                                                    ship_by=CLOCK_START)
        fresh = fixtures.create_distribution_order(api, product["id"],
                                                    requested_units=10,
                                                    ship_by=clock_plus(days=60))
        fixtures.set_clock(api, clock_plus(days=1))
        validate_error(
            api.allocate_distribution_order(stale["id"], DISTRIBUTION_PLANNER),
            "ERR_SHIP_BY_PASSED", 409)
        # Same order shape, only the deadline is honoured: the next gate answers.
        validate_error(
            api.allocate_distribution_order(fresh["id"], DISTRIBUTION_PLANNER),
            "ERR_PRODUCT_NOT_CLEARED", 409)
        assert _order(api, stale["id"])["status"] == "DRAFT"
        assert _order(api, fresh["id"])["status"] == "DRAFT"

    def test_the_order_state_rung_answers_before_the_ship_by_gate(self, api):
        """PRD §3.9: "Allocation takes no request payload — everything it needs
        is already on the order — and is admitted only when the order's `status`
        is `DRAFT`, so a second allocation on an already `ALLOCATED` order is
        refused with `ERR_ORDER_STATE_INVALID`."
        PRD §3.9: "Two further gates precede the waterfall: the order's
        `ship_by` must not be earlier than the logical clock, failing which the
        answer is `ERR_SHIP_BY_PASSED`, and the product's `clearance_status` must
        be `CLEARED`, failing which the answer is `ERR_PRODUCT_NOT_CLEARED`."

        Design: Corner/validations/priority_108_allocate_rejects_a_passed_ship_by_and_treats_the_boundary_instant_as_valid
        """
        bundle = fixtures.released_reagent_lot(api)
        order = fixtures.create_distribution_order(api, bundle["product"]["id"],
                                                   requested_units=10,
                                                   ship_by=clock_plus(days=10))
        allocated = validate_success(
            api.allocate_distribution_order(order["id"], DISTRIBUTION_PLANNER))
        assert allocated["status"] == "ALLOCATED"
        fixtures.set_clock(api, clock_plus(days=11))
        # The deadline has passed as well, but the state rung sits above it.
        validate_error(
            api.allocate_distribution_order(order["id"], DISTRIBUTION_PLANNER),
            "ERR_ORDER_STATE_INVALID", 409)
        after = _order(api, order["id"])
        assert after["status"] == "ALLOCATED"
        assert after["allocated_units"] == 10
        assert len(_reservations(api, order["id"])) == 1


def _bridge_bench(api, candidate_measurements=(("ACTIVITY", 100.0),
                                               ("PRECISION", 100.0))):
    """A released predicate lot and a filled candidate lot of the same product,
    the candidate built from a second vendor lot of the same critical material,
    carrying exactly the release measurements the caller asks for."""
    setup = fixtures.manufacturing_setup(api, critical_types=("ANTIBODY",))
    predicate = fixtures.released_reagent_lot(api, setup=setup)["lot"]
    changed = fixtures.qualified_material_lot_for_spec(
        api, setup["materials"][0]["spec"])
    candidate = fixtures.create_reagent_lot(api, setup["product"]["id"])
    fixtures.dispense_component(api, candidate["id"], changed["id"], "ANTIBODY")
    run = fixtures.schedule_fill_run(api, candidate["id"])
    fixtures.start_fill_run(api, run["id"])
    fixtures.record_bioburden_sample(api, run["id"])
    fixtures.complete_fill_run(api, run["id"], run["planned_fill_units"])
    for code, value in candidate_measurements:
        fixtures.record_release_measurement(api, candidate["id"], code, value)
    return {"product": setup["product"], "predicate": predicate,
            "candidate": _lot(api, candidate["id"]), "changed": changed}


def _study(api, study_id):
    return validate_success(api.get_bridging_study(study_id, QA_RELEASER))


def _decide(api, study_id, decision, headers=QA_RELEASER):
    return api.decide_bridging_study(
        study_id, factories.bridging_decision_payload(decision), headers)


class TestBridgingApprovalGates:
    """Rung 125, paired data availability, against rung 127, equivalence."""

    def test_an_approval_with_no_paired_data_at_all_is_refused(self, api):
        """PRD §3.7: "Every code in `paired_test_codes` must have a latest release
        measurement on **both** the predicate and the candidate lot, so that
        `equivalence_verdict` is not `PENDING`; a gap yields
        `ERR_PAIRED_DATA_MISSING` with HTTP 422."
        PRD §3.7: "If either side is missing for any code, `equivalence_verdict`
        is `PENDING` and no bias figures are established."
        PRD §3.7: "The study is created in `status` `DRAFT` with
        `equivalence_verdict` `PENDING`, `decided_by_user_id` and `decided_at`
        null, and `mean_bias_pct` and `max_bias_pct` computed immediately from
        whatever data both lots already carry."

        Design: Corner/validations/bridging_decision_rejects_approval_while_the_paired_data_is_still_missing
        """
        bench = _bridge_bench(api, candidate_measurements=())
        study = fixtures.create_bridging_study(
            api, bench["predicate"]["id"], bench["candidate"]["id"],
            bench["changed"]["id"], paired_test_codes=["ACTIVITY"])
        assert study["status"] == "DRAFT"
        assert study["equivalence_verdict"] == "PENDING"
        assert study["mean_bias_pct"] is None
        assert study["max_bias_pct"] is None
        validate_error(_decide(api, study["id"], "APPROVE"),
                       "ERR_PAIRED_DATA_MISSING", 422)
        after = _study(api, study["id"])
        assert after["status"] == "DRAFT"
        assert after["equivalence_verdict"] == "PENDING"
        assert after["decided_by_user_id"] is None
        assert after["decided_at"] is None

    def test_a_half_paired_code_blocks_the_approval_until_the_pair_is_complete(self, api):
        """PRD §3.7: "Every code in `paired_test_codes` must have a latest release
        measurement on **both** the predicate and the candidate lot, so that
        `equivalence_verdict` is not `PENDING`; a gap yields
        `ERR_PAIRED_DATA_MISSING` with HTTP 422."
        PRD §3.7: "`equivalence_verdict` becomes `EQUIVALENT` when
        `mean_bias_pct` is at most 3.00 **and** `max_bias_pct` is at most 5.00,
        both boundaries inclusive, and `NOT_EQUIVALENT` when either threshold is
        exceeded."
        PRD §3.7: "On success the study's `status` becomes the terminal
        `APPROVED`, `decided_by_user_id` and `decided_at` are recorded, and the
        study's `version` increases by 1."

        Design: Corner/validations/bridging_decision_rejects_approval_while_the_paired_data_is_still_missing
        """
        # The predicate carries both codes at 100.00; the candidate only one.
        bench = _bridge_bench(api, candidate_measurements=(("ACTIVITY", 100.0),))
        study = fixtures.create_bridging_study(
            api, bench["predicate"]["id"], bench["candidate"]["id"],
            bench["changed"]["id"],
            paired_test_codes=["ACTIVITY", "PRECISION"])
        assert study["equivalence_verdict"] == "PENDING"
        validate_error(_decide(api, study["id"], "APPROVE"),
                       "ERR_PAIRED_DATA_MISSING", 422)

        fixtures.record_release_measurement(api, bench["candidate"]["id"],
                                            "PRECISION", 100.0)
        paired = _study(api, study["id"])
        # Both codes now match the predicate exactly, so every bias is 0.00.
        assert paired["equivalence_verdict"] == "EQUIVALENT"
        assert float(paired["mean_bias_pct"]) == 0.00
        assert float(paired["max_bias_pct"]) == 0.00
        approved = validate_success(_decide(api, study["id"], "APPROVE"))
        assert approved["status"] == "APPROVED"
        assert approved["version"] == paired["version"] + 1
        assert approved["decided_at"] is not None
        assert _study(api, study["id"])["status"] == "APPROVED"

    def test_missing_paired_data_is_reported_before_non_equivalence(self, api):
        """PRD §3.7: "Missing data is reported before non-equivalence, because an
        incomplete comparison is not evidence of inequivalence."
        PRD §3.7: "Otherwise the paired bias for that code is the absolute
        difference between the candidate's `measured_value` and the predicate's
        `measured_value`, divided by the predicate's `measured_value`, multiplied
        by 100, and rounded half-up to two decimal places."
        PRD §3.7: "Then `equivalence_verdict` must actually be `EQUIVALENT`; a
        verdict of `NOT_EQUIVALENT` yields `ERR_NOT_EQUIVALENT` with HTTP 409."

        Design: Corner/validations/bridging_decision_rejects_approval_while_the_paired_data_is_still_missing
        """
        # The candidate's ACTIVITY is 110.00 against the predicate's 100.00, and
        # its PRECISION is missing altogether.
        bench = _bridge_bench(api, candidate_measurements=(("ACTIVITY", 110.0),))
        study = fixtures.create_bridging_study(
            api, bench["predicate"]["id"], bench["candidate"]["id"],
            bench["changed"]["id"],
            paired_test_codes=["ACTIVITY", "PRECISION"])
        assert study["equivalence_verdict"] == "PENDING"
        # Divergent and incomplete at once: the availability rung answers.
        validate_error(_decide(api, study["id"], "APPROVE"),
                       "ERR_PAIRED_DATA_MISSING", 422)

        fixtures.record_release_measurement(api, bench["candidate"]["id"],
                                            "PRECISION", 100.0)
        paired = _study(api, study["id"])
        # ACTIVITY bias 10.00, PRECISION bias 0.00, so the mean is 5.00 and the
        # maximum 10.00 — both thresholds are exceeded.
        assert float(paired["max_bias_pct"]) == 10.00
        assert float(paired["mean_bias_pct"]) == 5.00
        assert paired["equivalence_verdict"] == "NOT_EQUIVALENT"
        validate_error(_decide(api, study["id"], "APPROVE"),
                       "ERR_NOT_EQUIVALENT", 409)
        assert _study(api, study["id"])["status"] == "DRAFT"

    def test_the_state_rung_answers_before_the_paired_data_rung(self, api):
        """PRD §3.7: "Either way the study must be in `DRAFT`; a study that has
        already reached `APPROVED` or `FAILED` is terminal and a further decision
        is refused with `ERR_BRIDGING_STUDY_STATE_INVALID`."
        PRD §3.7: "A `REJECT` decision carries no extra gates beyond the `DRAFT`
        state and fires a three-hop cascade."
        PRD §3.7: "Hop 1: the study's `status` becomes the terminal `FAILED`,
        `decided_by_user_id` and `decided_at` are recorded, and the study's
        `version` increases by 1."

        Design: Corner/validations/bridging_decision_rejects_approval_while_the_paired_data_is_still_missing
        """
        bench = _bridge_bench(api, candidate_measurements=())
        study = fixtures.create_bridging_study(
            api, bench["predicate"]["id"], bench["candidate"]["id"],
            bench["changed"]["id"], paired_test_codes=["ACTIVITY"])
        # A rejection needs no paired data whatsoever.
        rejected = validate_success(_decide(api, study["id"], "REJECT"))
        assert rejected["status"] == "FAILED"
        assert rejected["version"] == study["version"] + 1
        assert rejected["decided_at"] is not None
        # The paired data is still missing, but the terminal state answers first.
        validate_error(_decide(api, study["id"], "APPROVE"),
                       "ERR_BRIDGING_STUDY_STATE_INVALID", 409)
        assert _study(api, study["id"])["status"] == "FAILED"


# A three-month claim pinned on a lot filled at 2026-08-31T10:00:00.000Z expires
# at 2026-11-30T10:00:00.000Z: the 31st does not exist in November, so the date
# clamps to the 30th and the time of day survives.  Against a product floor of 87
# days, shipping on 2026-09-04 leaves 87 whole days (87 days and 10 hours, floored)
# and shipping a day later leaves only 86.
FILL_COMPLETED_AT = "2026-08-31T10:00:00.000Z"
EXPIRY_AT_THREE_MONTHS = "2026-11-30T10:00:00.000Z"
SHELF_LIFE_FLOOR_DAY = "2026-09-04T00:00:00.000Z"
ONE_DAY_PAST_THE_FLOOR = "2026-09-05T00:00:00.000Z"
SHIP_BY_INSTANT = "2026-12-01T00:00:00.000Z"


def _shelf_life_bench(api):
    """A released lot with a three-month claim and a product floor of 87 days,
    with ten of its units reserved for a customer."""
    setup = fixtures.manufacturing_setup(
        api, product_overrides={"shelf_life_months_claim": 3,
                                "min_shelf_life_days_at_ship": 87})
    bundle = fixtures.running_fill_run(api, setup)
    fixtures.set_clock(api, FILL_COMPLETED_AT)
    fixtures.record_bioburden_sample(api, bundle["run"]["id"])
    fixtures.complete_fill_run(api, bundle["run"]["id"], 100)
    lot_id = bundle["lot"]["id"]
    fixtures.record_passing_release_tests(api, lot_id, setup["product"])
    released = fixtures.disposition_reagent_lot(api, lot_id, "RELEASE")
    assert released["assigned_shelf_life_months"] == 3
    assert parse_instant(released["expiry_date"]) == \
        parse_instant(EXPIRY_AT_THREE_MONTHS)
    order = fixtures.create_distribution_order(api, setup["product"]["id"],
                                               requested_units=10,
                                               ship_by=SHIP_BY_INSTANT)
    order = validate_success(
        api.allocate_distribution_order(order["id"], DISTRIBUTION_PLANNER))
    assert order["status"] == "ALLOCATED"
    rows = _reservations(api, order["id"])
    assert len(rows) == 1
    return {"product": setup["product"], "lot": _lot(api, lot_id),
            "order": order, "reservation": rows[0]}


class TestShelfLifeFloorAtShipping:
    """Rung 110, the remaining-shelf-life floor re-checked at shipping."""

    def test_shipping_on_exactly_the_floor_day_is_accepted(self, api):
        """PRD §3.9: "It requires the reservation to be `RESERVED` — shipping a
        `CANCELLED` or already-`SHIPPED` row is refused with
        `ERR_ALLOCATION_STATE_INVALID` — requires the drawn lot's
        `distribution_status` to still be `AVAILABLE`, and re-checks shelf life at
        the moment of shipment: the drawn lot's remaining shelf life in whole days
        must be at least the product's `min_shelf_life_days_at_ship`, inclusively,
        otherwise the answer is `ERR_SHELF_LIFE_TOO_SHORT`."
        PRD §2.7: "Remaining shelf life in days is likewise floored to whole days
        from an exact difference of instants divided by 86,400 seconds per day."
        PRD §3.9: "On success `shipped_at` is stored, the lot's `allocated_units`
        decreases and its `shipped_units` increases by that reservation's
        `allocated_units`, and the reservation's `version` increases by 1."
        PRD §3.9: "When no reservation of the parent order is left in `status`
        `RESERVED` after the call, the order advances from `ALLOCATED` or
        `PARTIALLY_ALLOCATED` to `SHIPPED` and its `version` increases by 1."

        Design: Corner/validations/priority_110_ship_enforces_the_product_shelf_life_floor_inclusively_at_the_boundary_day
        """
        bench = _shelf_life_bench(api)
        fixtures.set_clock(api, SHELF_LIFE_FLOOR_DAY)
        shipped = validate_success(
            api.ship_allocation(bench["reservation"]["id"], DISTRIBUTION_PLANNER))
        assert shipped["status"] == "SHIPPED"
        assert shipped["shipped_at"] is not None
        assert shipped["version"] == bench["reservation"]["version"] + 1
        lot = _lot(api, bench["lot"]["id"])
        assert lot["shipped_units"] == 10
        assert lot["allocated_units"] == 0
        assert _order(api, bench["order"]["id"])["status"] == "SHIPPED"

    def test_shipping_one_day_past_the_floor_is_refused(self, api):
        """PRD §3.9: "It requires the reservation to be `RESERVED` — shipping a
        `CANCELLED` or already-`SHIPPED` row is refused with
        `ERR_ALLOCATION_STATE_INVALID` — requires the drawn lot's
        `distribution_status` to still be `AVAILABLE`, and re-checks shelf life at
        the moment of shipment: the drawn lot's remaining shelf life in whole days
        must be at least the product's `min_shelf_life_days_at_ship`, inclusively,
        otherwise the answer is `ERR_SHELF_LIFE_TOO_SHORT`."
        PRD §3.5: "From those, `expiry_date` is computed as `fill_completed_at`
        advanced by `assigned_shelf_life_months` calendar months: the day-of-month
        is preserved, and where the source day does not exist in the target month
        the date clamps to the last day of that month; the time-of-day is
        preserved and the instant is rendered in ISO 8601 UTC with three
        fractional digits."
        PRD §3.5: "When `shelf_life_basis` is `CLAIM`,
        `assigned_shelf_life_months` takes the product's `shelf_life_months_claim`
        and `shelf_life_basis_study_id` stays null."

        Design: Corner/validations/priority_110_ship_enforces_the_product_shelf_life_floor_inclusively_at_the_boundary_day
        """
        bench = _shelf_life_bench(api)
        fixtures.set_clock(api, ONE_DAY_PAST_THE_FLOOR)
        validate_error(
            api.ship_allocation(bench["reservation"]["id"], DISTRIBUTION_PLANNER),
            "ERR_SHELF_LIFE_TOO_SHORT", 409)
        reservation = validate_success(
            api.get_allocation(bench["reservation"]["id"], DISTRIBUTION_PLANNER))
        assert reservation["status"] == "RESERVED"
        assert reservation["shipped_at"] is None
        lot = _lot(api, bench["lot"]["id"])
        assert lot["allocated_units"] == 10
        assert lot["shipped_units"] == 0
        assert _order(api, bench["order"]["id"])["status"] == "ALLOCATED"

    def test_the_allocation_state_rung_answers_before_the_shelf_life_floor(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error is returned: the one belonging to the lowest-numbered rung of the
        ladder below."
        PRD §3.9: "It requires the reservation to be `RESERVED` — shipping a
        `CANCELLED` or already-`SHIPPED` row is refused with
        `ERR_ALLOCATION_STATE_INVALID` — requires the drawn lot's
        `distribution_status` to still be `AVAILABLE`, and re-checks shelf life at
        the moment of shipment: the drawn lot's remaining shelf life in whole days
        must be at least the product's `min_shelf_life_days_at_ship`, inclusively,
        otherwise the answer is `ERR_SHELF_LIFE_TOO_SHORT`."

        Design: Corner/validations/priority_110_ship_enforces_the_product_shelf_life_floor_inclusively_at_the_boundary_day
        """
        bench = _shelf_life_bench(api)
        fixtures.set_clock(api, SHELF_LIFE_FLOOR_DAY)
        validate_success(
            api.ship_allocation(bench["reservation"]["id"], DISTRIBUTION_PLANNER))
        fixtures.set_clock(api, ONE_DAY_PAST_THE_FLOOR)
        # The row is spent and the shelf life is now short: the state rung wins.
        validate_error(
            api.ship_allocation(bench["reservation"]["id"], DISTRIBUTION_PLANNER),
            "ERR_ALLOCATION_STATE_INVALID", 409)
        reservation = validate_success(
            api.get_allocation(bench["reservation"]["id"], DISTRIBUTION_PLANNER))
        assert reservation["status"] == "SHIPPED"
        lot = _lot(api, bench["lot"]["id"])
        assert lot["shipped_units"] == 10
        assert lot["allocated_units"] == 0
