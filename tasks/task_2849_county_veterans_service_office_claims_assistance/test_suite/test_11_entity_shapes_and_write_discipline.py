"""
Entity defaults, single reads, paginated listings and write-body discipline.

Every test here starts from the empty database the harness hands over, so the
counters and sequence numbers observed are the first ones the office issues.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    INTAKE_CLERK_HEADERS,
    NON_EXISTENT_UUID,
    SYSTEM_ADMIN_HEADERS,
    assert_append_only_shape,
    assert_cents,
    assert_exact_whole,
    assert_fresh_row,
    assert_pagination_mirror_response,
    assert_representative_defaults,
    assert_screen_categories,
    assert_single_read_has_no_pagination_response,
    assert_veteran_intake_defaults,
    claim_payload,
    conditions,
    create_active_representative,
    create_represented_veteran,
    create_veteran,
    create_verified_veteran,
    discharge_document_payload,
    make_county_officer_headers,
    read_screens,
    read_veteran,
    representative_payload,
    screen_veteran,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    veteran_payload,
)

MEANS_TESTED = {
    "household_income_cents": 1500000,
    "net_worth_cents": 2000000,
    "dependent_count": 2,
    "homeless_status": "NOT_HOMELESS",
    "referral_source": "WALK_IN",
}


@pytest.fixture(autouse=True)
def _clock(api):
    """Every test in this module runs at the start of the logical clock."""
    set_clock(api, CLOCK_START_INSTANT)


class TestFreshRowDefaults:
    """A creation response carries every computed field at its declared default."""

    def test_a_new_roster_row_lands_pending_with_three_counters_at_zero(self, api):
        """
        "A fresh row lands in `accreditation_status` `PENDING` with `ce_credits_earned` at 0, `active_poa_count` at 0, `caseload_weight` at 0, and `revocation_reason` unset."

        Design: Corner/entities/corner_representative_creation_returns_declared_fields_with_pending_accreditation
        """
        created = validate_success(
            api.create_representative(
                representative_payload(
                    full_name="Dana Reyes",
                    accreditation_number="ACC-2849-301",
                    accreditation_type="COUNTY_CVSO",
                    accreditation_expires_on="2029-12-31",
                ),
                SYSTEM_ADMIN_HEADERS,
            ),
            201,
        )
        assert_representative_defaults(created)
        assert_fresh_row(created)

    def test_a_single_read_returns_the_stored_intake_row(self, api):
        """
        "A brand-new intake record starts with `intake_status` at `INTAKE_STARTED`, `discharge_doc_status` at `NOT_SUBMITTED`, `character_of_service` at the placeholder `UNCHARACTERIZED` (meaning no verified document has yet established it), `wartime_service_days` at 0, `combined_rating_pct` at 0, `priority_group` at `P4`, `assigned_representative_id` unset and `date_of_death` unset."
        "`county_case_number` takes the form `CVSO-` followed by the four-digit year, another hyphen, and a six-digit zero-padded sequence"

        Design: Corner/entities/corner_veteran_retrieval_returns_the_stored_row
        """
        created = create_veteran(api, **MEANS_TESTED)
        response = api.get_veteran(created["id"], INTAKE_CLERK_HEADERS)
        veteran = validate_success(response, 200)
        assert veteran["id"] == created["id"]
        assert_veteran_intake_defaults(veteran)
        assert isinstance(veteran["county_case_number"], str)
        assert veteran["county_case_number"]
        assert_single_read_has_no_pagination_response(response)


class TestCollectionPaginationFields:
    """The window fields describe the filtered set, not the returned page."""

    def test_the_first_page_reports_the_whole_set_and_more_to_come(self, api):
        """
        "The four pagination fields are `limit` (the effective page size actually applied), `offset` (the effective starting position actually applied), `total_count` (the number of rows matching the filter before the page window is applied) and `has_more` (true when `offset` plus the number of returned rows is strictly less than `total_count`)."

        Design: Corner/entities/corner_representative_listing_is_paginated_with_total_count_and_has_more
        """
        for _ in range(3):
            create_active_representative(api)
        response = api.list_representatives(
            SYSTEM_ADMIN_HEADERS, params={"limit": 2, "offset": 0}
        )
        assert_pagination_mirror_response(
            response,
            expected_limit=2,
            expected_offset=0,
            expected_total=3,
            expected_has_more=True,
        )
        rows, _meta = validate_paginated(response)
        assert len(rows) == 2

    def test_the_last_page_reports_the_same_total_and_no_more(self, api):
        """
        "Unless a subsection below states otherwise, list results are returned in ascending `created_at` order, so the oldest row of the filtered set appears first and the ordering is stable across pages."

        Design: Corner/entities/corner_representative_listing_is_paginated_with_total_count_and_has_more
        """
        for _ in range(3):
            create_active_representative(api)
        response = api.list_representatives(
            SYSTEM_ADMIN_HEADERS, params={"limit": 2, "offset": 2}
        )
        assert_pagination_mirror_response(
            response,
            expected_limit=2,
            expected_offset=2,
            expected_total=3,
            expected_has_more=False,
        )
        rows, _meta = validate_paginated(response)
        assert len(rows) == 1


class TestNotFoundResolution:
    """A path or nested-path identifier is resolved before anything else."""

    def test_an_unused_veteran_id_is_the_entity_specific_not_found(self, api):
        """
        "A `veteran_id` in the path or body resolves to an existing veteran, else `ERR_VETERAN_NOT_FOUND` (404), on `GET /cvso/veterans/{id}`"

        Design: Corner/entities/corner_get_veteran_with_unknown_id_returns_veteran_not_found
        """
        error = validate_error(
            api.get_veteran(NON_EXISTENT_UUID, INTAKE_CLERK_HEADERS),
            "ERR_VETERAN_NOT_FOUND",
            404,
        )
        assert isinstance(error["message"], str)
        assert error["message"]

    def test_a_nested_create_resolves_its_parent_before_the_body(self, api):
        """
        "Every `{id}` path segment is resolved in left-to-right path order, and each identifier reference in the request body is resolved after the path."

        Design: Corner/entities/corner_discharge_document_creation_under_unknown_veteran_returns_not_found
        """
        validate_error(
            api.create_discharge_document(
                NON_EXISTENT_UUID, discharge_document_payload(), INTAKE_CLERK_HEADERS
            ),
            "ERR_VETERAN_NOT_FOUND",
            404,
        )
        _rows, meta = validate_paginated(
            api.list_discharge_documents(INTAKE_CLERK_HEADERS)
        )
        assert_exact_whole(meta["total_count"], 0, "total_count")


class TestRequestShapeDiscipline:
    """A body that is wrong in shape creates nothing at all."""

    def test_an_omitted_required_input_is_a_validation_error(self, api):
        """
        "Every field the addressed endpoint declares without a default is present and non-null, else `ERR_VALIDATION` (422), on every POST and PATCH endpoint."

        Design: Corner/entities/corner_veteran_creation_missing_required_service_start_date_returns_validation
        """
        body = veteran_payload(full_name="Alex Rivera", **MEANS_TESTED)
        body.pop("service_start_date")
        validate_error(
            api.create_veteran(body, INTAKE_CLERK_HEADERS), "ERR_VALIDATION", 422
        )
        _rows, meta = validate_paginated(api.list_veterans(INTAKE_CLERK_HEADERS))
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_an_undeclared_enum_value_is_a_validation_error(self, api):
        """
        "Every enum-typed field carries one of the values declared for it, else `ERR_VALIDATION` (422), on every POST and PATCH endpoint."

        Design: Corner/entities/corner_veteran_creation_with_unknown_homeless_status_enum_is_rejected
        """
        body = veteran_payload(full_name="Alex Rivera", **MEANS_TESTED)
        body["homeless_status"] = "COUCH_SURFING"
        validate_error(
            api.create_veteran(body, INTAKE_CLERK_HEADERS), "ERR_VALIDATION", 422
        )
        _rows, meta = validate_paginated(api.list_veterans(INTAKE_CLERK_HEADERS))
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_a_dependent_count_beyond_twelve_is_the_same_error_id(self, api):
        """
        "Integer fields respect their declared ranges, else `ERR_VALIDATION` (422), on every POST and PATCH endpoint"
        and the range declared for this one is "`dependent_count` is from 0 through 12".

        Design: Corner/entities/corner_veteran_creation_with_unknown_homeless_status_enum_is_rejected
        """
        body = veteran_payload(full_name="Alex Rivera", **MEANS_TESTED)
        body["dependent_count"] = 13
        validate_error(
            api.create_veteran(body, INTAKE_CLERK_HEADERS), "ERR_VALIDATION", 422
        )
        _rows, meta = validate_paginated(api.list_veterans(INTAKE_CLERK_HEADERS))
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_a_computed_band_supplied_by_the_caller_is_refused(self, api):
        """
        "No server-owned field appears in a write body, else `ERR_READONLY_FIELD` (422), on every POST and PATCH endpoint."

        Design: Corner/entities/corner_veteran_priority_group_supplied_in_the_write_body_is_rejected
        """
        body = veteran_payload(full_name="Alex Rivera", **MEANS_TESTED)
        body["priority_group"] = "P1"
        validate_error(
            api.create_veteran(body, INTAKE_CLERK_HEADERS), "ERR_READONLY_FIELD", 422
        )
        _rows, meta = validate_paginated(api.list_veterans(INTAKE_CLERK_HEADERS))
        assert_exact_whole(meta["total_count"], 0, "total_count")

    def test_the_band_the_caller_may_not_send_is_derived_by_the_screen(self, api):
        """
        "`income_limit_applied_cents` is the countable-income ceiling in force at screen time: eighteen thousand eight hundred forty dollars — 1884000 cents — plus four thousand eight hundred thirty dollars, or 483000 cents, for each dependent claimed."
        "Failing that, they land in `P3` when `household_income_cents` is at most the income ceiling for their dependent count."

        Design: Corner/entities/corner_veteran_priority_group_supplied_in_the_write_body_is_rejected
        """
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        built = create_verified_veteran(api, officer_headers, **MEANS_TESTED)
        screen = screen_veteran(api, built["veteran"]["id"], officer_headers)
        assert_cents(screen["income_limit_applied_cents"], 2850000)
        assert screen["priority_group_assigned"] == "P3"
        assert read_veteran(api, built["veteran"]["id"])["priority_group"] == "P3"

    def test_a_system_owned_claim_status_may_not_be_pre_set(self, api):
        """
        A claim's own `status` is server-owned, so the same rule applies:
        "No server-owned field appears in a write body, else `ERR_READONLY_FIELD` (422), on every POST and PATCH endpoint."

        Design: Corner/entities/corner_claim_system_fields_supplied_in_the_write_body_are_rejected
        """
        base = create_represented_veteran(api)
        body = claim_payload(
            base["veteran"]["id"],
            base["poa"]["id"],
            claimed_conditions=conditions("tinnitus"),
        )
        body["status"] = "FILED"
        validate_error(
            api.create_claim(body, base["officer_headers"]),
            "ERR_READONLY_FIELD",
            422,
        )
        _rows, meta = validate_paginated(api.list_claims(base["officer_headers"]))
        assert_exact_whole(meta["total_count"], 0, "total_count")


class TestAppendOnlyScreenHistory:
    """A re-screen appends a row; it never rewrites the one already written."""

    @pytest.fixture
    def rescreened_veteran(self, api):
        """One screen at the original income and a second after a correction."""
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        officer_headers = make_county_officer_headers(officer["id"])
        built = create_verified_veteran(api, officer_headers, **MEANS_TESTED)
        veteran_id = built["veteran"]["id"]
        first = screen_veteran(api, veteran_id, officer_headers)
        validate_success(
            api.update_veteran(
                veteran_id, {"household_income_cents": 9000000}, INTAKE_CLERK_HEADERS
            )
        )
        second = screen_veteran(api, veteran_id, officer_headers)
        return {
            "veteran_id": veteran_id,
            "first": first,
            "second": second,
        }

    def test_the_second_screen_takes_the_next_sequence_number(
        self, api, rescreened_veteran
    ):
        """
        "Each screen record carries the `veteran_id` it belongs to and a `screen_sequence`, the 1-based ordinal of this screen among that veteran's screens ordered by `created_at` ascending — so the first is 1 and every later screen is the previous maximum plus 1, with the value never below 1."

        Design: Corner/entities/corner_eligibility_screen_is_immutable_and_exposes_no_update_endpoint
        """
        assert_exact_whole(
            rescreened_veteran["first"]["screen_sequence"], 1, "screen_sequence"
        )
        assert_exact_whole(
            rescreened_veteran["second"]["screen_sequence"], 2, "screen_sequence"
        )
        assert rescreened_veteran["second"]["id"] != rescreened_veteran["first"]["id"]
        screens = read_screens(api, rescreened_veteran["veteran_id"])
        assert len(screens) == 2

    def test_the_first_screen_keeps_the_numbers_it_froze(self, api, rescreened_veteran):
        """
        "Screens are append-only and are never mutated once written, which is why (per §2.5) they carry no `updated_at` and no `version`."

        Design: Corner/entities/corner_eligibility_screen_is_immutable_and_exposes_no_update_endpoint
        """
        screens = read_screens(api, rescreened_veteran["veteran_id"])
        stored_first = [
            row for row in screens if row["id"] == rescreened_veteran["first"]["id"]
        ][0]
        assert_append_only_shape(stored_first)
        assert_cents(stored_first["income_limit_applied_cents"], 2850000)
        assert stored_first["priority_group_assigned"] == "P3"
        assert_screen_categories(stored_first)

    def test_the_correction_moves_the_band_on_the_new_screen_only(
        self, api, rescreened_veteran
    ):
        """
        "Failing all three, they land in `P4`, which is also the value a brand-new intake starts at."
        A re-screen exists "so that a corrected income, net worth, dependent count or housing posture can be re-evaluated".

        Design: Corner/entities/corner_eligibility_screen_is_immutable_and_exposes_no_update_endpoint
        """
        assert rescreened_veteran["second"]["priority_group_assigned"] == "P4"
        assert read_veteran(api, rescreened_veteran["veteran_id"])["priority_group"] == "P4"


class TestReferentialAgreementOnClaimCreation:
    """Both identifiers resolve, and the claim is still refused."""

    def test_a_designation_of_another_veteran_is_refused(self, api):
        """
        "The designation named by `poa_id` belongs to the same veteran as the claim, else `ERR_POA_VETERAN_MISMATCH` (409), on `POST /cvso/claims`."

        Design: Corner/entities/corner_claim_rejects_a_designation_belonging_to_another_veteran
        """
        officer = create_active_representative(
            api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
        )
        first = create_represented_veteran(api, designee=officer)
        second = create_represented_veteran(api, designee=officer)
        response = api.create_claim(
            claim_payload(
                first["veteran"]["id"],
                second["poa"]["id"],
                claimed_conditions=conditions("tinnitus"),
            ),
            first["officer_headers"],
        )
        validate_error(response, "ERR_POA_VETERAN_MISMATCH", 409)
        assert second["poa"]["veteran_id"] == second["veteran"]["id"]
        _rows, meta = validate_paginated(api.list_claims(first["officer_headers"]))
        assert_exact_whole(meta["total_count"], 0, "total_count")
