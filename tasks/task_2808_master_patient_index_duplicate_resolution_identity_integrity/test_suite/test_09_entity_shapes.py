"""The shapes the PRD declares for the resources it mints."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_RECORD_NOT_FOUND,
    ERR_RULE_SET_NOT_FOUND,
    ERR_SITE_NOT_FOUND,
)
from test_helpers.constants import (
    IDENTITY_ACTIVE,
    INTEGRITY_CLEAR,
    OUTCOME_INCONCLUSIVE,
    QUEUE_NEW,
    SCORE_VARIANT_STRICT,
)
from test_helpers.test_users import (
    admin_headers,
    analyst_headers,
    registrar_headers,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


class TestRegistrationSiteCreation:
    def test_a_new_site_opens_active_with_both_counters_at_zero(self, api):
        """The four supplied inputs come back beside three server-set values.

        PRD §3.1: "The new site opens with `status` set to `ACTIVE` and both derived
        counters, `active_record_count` and `flagged_record_count`, at 0."

        Design: Corner/entities/create_registration_site_returns_all_declared_fields
        """
        created = A.assert_created(
            api.create_site(
                f.site_payload(
                    "SITE-E1", name="Entity Claims Clinic", region_code="US-OR",
                    registrar_headcount=9,
                ),
                admin_headers(),
            )
        )

        assert created["site_code"] == "SITE-E1"
        assert created["name"] == "Entity Claims Clinic"
        assert created["region_code"] == "US-OR"
        A.assert_integer(created["registrar_headcount"], 9, "registrar_headcount")
        assert created["status"] == "ACTIVE"
        A.assert_integer(created["active_record_count"], 0, "active_record_count")
        A.assert_integer(created["flagged_record_count"], 0, "flagged_record_count")
        A.assert_system_fields(created, expected_version=1)
        A.assert_instant(created["created_at"], "2026-08-01T00:00:00Z", "created_at")
        A.assert_instant(created["updated_at"], "2026-08-01T00:00:00Z", "updated_at")


class TestPatientRecordRetrieval:
    def test_a_read_back_record_carries_every_stored_and_derived_field(self, api):
        """Nothing drifts between the create response and the retrieval.

        PRD §3.2: "Creating a patient record supplies the identifying core —
        `site_id`, `mrn`, `last_name`, `first_name`, `dob` and `sex` — plus a set of
        optional attributes: `ssn_last4`, `address_line`, `postal_code`, `phone`,
        `biometric_template_hash`, `insurance_member_id`, `clinical_element_count` and
        `origin_search_attempt_id`."

        Design: Corner/entities/get_patient_record_returns_stored_and_computed_fields
        """
        site = F.create_site(
            api, "SITE-E2", name="Retrieval Clinic", region_code="US-UT",
            registrar_headcount=2,
        )
        created = F.create_record(
            api, site["id"], "E2-1000", "Marchetti", "Giulia", "1979-10-12", "F",
            ssn_last4="5150", address_line="44 Cedar Way", postal_code="84101",
            phone="8015550101", biometric_template_hash="BIO-E2-1000",
            insurance_member_id="INS-E2-1000", clinical_element_count=13,
        )

        read_back = A.assert_ok(
            api.get_record(created["id"], registrar_headers(site["id"]))
        )

        assert read_back["site_id"] == site["id"]
        assert read_back["mrn"] == "E2-1000"
        assert read_back["last_name"] == "Marchetti"
        assert read_back["first_name"] == "Giulia"
        assert read_back["dob"] == "1979-10-12"
        assert read_back["sex"] == "F"
        assert read_back["ssn_last4"] == "5150"
        assert read_back["address_line"] == "44 Cedar Way"
        assert read_back["postal_code"] == "84101"
        assert read_back["phone"] == "8015550101"
        assert read_back["biometric_template_hash"] == "BIO-E2-1000"
        assert read_back["insurance_member_id"] == "INS-E2-1000"
        A.assert_integer(read_back["clinical_element_count"], 13, "clinical_element_count")
        assert read_back["enterprise_id"] == "EID-SITE-E2-E2-1000"
        A.assert_record_condition(
            read_back, identity_state=IDENTITY_ACTIVE, integrity_state=INTEGRITY_CLEAR
        )
        assert read_back["survivor_record_id"] is None
        A.assert_integer(read_back["subsumed_member_count"], 0, "subsumed_member_count")
        A.assert_version(read_back, 1)


class TestPatientRecordListing:
    def test_the_site_filter_and_the_page_window_apply_together(self, api):
        """total_count counts matches before the window; has_more closes on page two.

        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside `meta`, where `total_count` is the number of records matching the
        filters before the page window is applied and `has_more` states whether any
        matching record remains beyond the current window."

        Design: Corner/entities/list_patient_records_filters_by_site_and_paginates
        """
        site_a = F.create_site(
            api, "SITE-E3A", name="List Clinic A", region_code="US-KS",
            registrar_headcount=1,
        )
        site_b = F.create_site(
            api, "SITE-E3B", name="List Clinic B", region_code="US-KS",
            registrar_headcount=1,
        )
        first = F.create_record(
            api, site_a["id"], "E3-1000", "Nakamura", "Sora", "1995-01-20", "X",
            clinical_element_count=1,
        )
        second = F.create_record(
            api, site_a["id"], "E3-2000", "Silva", "Pedro", "1961-03-08", "M",
            clinical_element_count=2,
        )
        F.create_record(
            api, site_b["id"], "E3-3000", "Haddad", "Lina", "1988-08-08", "F",
            clinical_element_count=3,
        )

        page_one, meta_one = A.assert_list_meta(
            api.list_records(
                admin_headers(), {"site_id": site_a["id"], "limit": 1, "offset": 0}
            ),
            expected_total=2,
            expected_limit=1,
            expected_offset=0,
            expected_has_more=True,
        )
        page_two, meta_two = A.assert_list_meta(
            api.list_records(
                admin_headers(), {"site_id": site_a["id"], "limit": 1, "offset": 1}
            ),
            expected_total=2,
            expected_has_more=False,
        )
        unfiltered = A.list_rows(
            api.list_records(admin_headers(), {"limit": 10, "offset": 0}),
            expected_total=3,
        )

        assert A.ids(page_one) == [first["id"]]
        assert A.ids(page_two) == [second["id"]]
        assert len(unfiltered) == 3
        assert all(row["site_id"] != site_b["id"] for row in page_one + page_two)


class TestUnknownIdentifiers:
    def test_reading_an_unknown_record_id_returns_the_record_not_found_error(self, api):
        """A well-formed but unknown id is a 404, not an empty success.

        PRD §2.8: "Every `PatientRecord` named by a path segment or by the body's
        `record_id`, `record_a_id`, `record_b_id`, `survivor_record_id`,
        `subsumed_record_id` or `target_record_id` exists — otherwise
        `ERR_RECORD_NOT_FOUND`, HTTP 404."

        Design: Corner/entities/get_patient_record_by_unknown_id_returns_not_found
        """
        response = api.get_record(UNKNOWN_ID, admin_headers())

        error = A.assert_error_envelope(response, ERR_RECORD_NOT_FOUND, 404)
        assert error["error_id"] == ERR_RECORD_NOT_FOUND
        assert isinstance(error["message"], str) and error["message"] != ""

    def test_a_search_attempt_under_an_unknown_site_returns_the_site_not_found_error(
        self, api
    ):
        """The leading path segment is resolved before the body is considered.

        PRD §2.7: "Path parameters are resolved strictly left to right. The parent
        named by the leading `{id}` segment must exist before anything to its right is
        considered, so a request naming a nonexistent site under which a metric run is
        requested fails as a missing site rather than as a malformed window, and a
        request naming a nonexistent pair under which evidence is listed fails as a
        missing pair."

        Design: Corner/entities/create_search_attempt_under_unknown_site_returns_not_found
        """
        response = api.create_search_attempt(
            "00000000-0000-4000-8000-0000000000ff",
            f.search_attempt_payload("Ghost"),
            analyst_headers(),
        )

        A.assert_error_envelope(response, ERR_SITE_NOT_FOUND, 404)


class TestRequiredAndConstrainedInputs:
    def test_a_rule_set_missing_its_thresholds_is_malformed(self, api):
        """The required-field check runs before any weight or threshold arithmetic.

        PRD §3.1: "Defining one requires a `name`, an author-assigned `version_label`
        such as `v3.2`, an `attribute_weights` map, the two thresholds, and a penalty."

        Design: Corner/entities/create_match_rule_set_without_thresholds_returns_invalid_request
        """
        payload = f.rule_set_payload(name="Incomplete Rules", version_label="V-BAD-1")
        del payload["review_threshold"]
        del payload["conflict_penalty_points"]

        response = api.create_rule_set(payload, admin_headers())

        A.assert_error_envelope(response, ERR_INVALID_REQUEST, 400)
        A.assert_error_envelope(
            api.get_rule_set(UNKNOWN_ID, admin_headers()), ERR_RULE_SET_NOT_FOUND, 404
        )

    def test_a_sex_value_outside_the_declared_set_is_rejected(self, api):
        """The value MALE is not one of the four accepted codes, and nothing persists.

        PRD §3.2: "`dob` is an ISO date in `YYYY-MM-DD` form and `sex` is one of `M`,
        `F`, `X` or `U`."

        Design: Corner/entities/create_patient_record_with_invalid_enum_sex_is_rejected
        """
        site = F.create_site(
            api, "SITE-E7", name="Enum Clinic", region_code="US-ME",
            registrar_headcount=1,
        )

        response = api.create_record(
            f.record_payload(
                site["id"], "E7-1000", "Duarte", "Ines", "1990-09-09", "MALE"
            ),
            analyst_headers(),
        )

        A.assert_error_envelope(response, ERR_INVALID_REQUEST, 400)
        unchanged = F.get_site(api, site["id"])
        A.assert_site_counters(unchanged, active_record_count=0, version=1)


class TestDeclaredDefaults:
    def test_the_omitted_optional_attributes_read_back_as_explicit_nulls(self, api):
        """A minimal registration still opens in a fully specified condition.

        PRD §3.2: "A record that survives all of that opens in a well-defined
        condition. Its `identity_state` is `ACTIVE`, its `integrity_state` derives to
        `CLEAR`, its `survivor_record_id` is null, and its `subsumed_member_count` is
        0."

        Design: Corner/entities/patient_record_optional_fields_take_declared_defaults
        """
        site = F.create_site(
            api, "SITE-E4", name="Defaults Clinic", region_code="US-ID",
            registrar_headcount=1,
        )

        created = A.assert_created(
            api.create_record(
                f.record_payload(
                    site["id"], "E4-1000", "Osei", "Kwame", "1974-07-04", "M"
                ),
                analyst_headers(),
            )
        )

        A.assert_integer(created["clinical_element_count"], 0, "clinical_element_count")
        assert created["identity_state"] == IDENTITY_ACTIVE
        assert created["integrity_state"] == INTEGRITY_CLEAR
        assert created["survivor_record_id"] is None
        A.assert_integer(created["subsumed_member_count"], 0, "subsumed_member_count")
        assert created["ssn_last4"] is None
        assert created["address_line"] is None
        assert created["postal_code"] is None
        assert created["phone"] is None
        assert created["biometric_template_hash"] is None
        assert created["insurance_member_id"] is None
        assert created["origin_search_attempt_id"] is None
        assert created["enterprise_id"] == "EID-SITE-E4-E4-1000"


class TestComputedCounters:
    def test_the_site_record_counter_only_moves_because_records_are_created(self, api):
        """active_record_count is never an input; it tracks the registrations.

        PRD §3.2: "The registering site's `active_record_count` increases by 1."

        Design: Corner/entities/registration_site_active_record_count_is_computed_not_supplied
        """
        site = F.create_site(
            api, "SITE-E5", name="Counter Clinic", region_code="US-NM",
            registrar_headcount=4,
        )
        A.assert_integer(site["active_record_count"], 0, "active_record_count")

        F.create_record(
            api, site["id"], "E5-1000", "Abbas", "Yusra", "1992-11-11", "F",
            clinical_element_count=2,
        )
        after_one = F.get_site(api, site["id"])
        F.create_record(
            api, site["id"], "E5-2000", "Novak", "Jiri", "1955-02-02", "M",
            clinical_element_count=6,
        )
        after_two = F.get_site(api, site["id"])

        A.assert_site_counters(after_one, active_record_count=1, flagged_record_count=0)
        A.assert_site_counters(after_two, active_record_count=2, flagged_record_count=0)
        A.assert_integer(
            after_two["registrar_headcount"], 4, "registrar_headcount"
        )


class TestServerMintedMetadata:
    def test_the_record_metadata_comes_from_the_server_and_the_logical_clock(self, api):
        """version opens at 1 and the timestamps are the pinned clock, not host time.

        PRD §2.4: "Most resources additionally carry three audit fields: `created_at`
        and `updated_at`, both ISO 8601 UTC timestamps rendered with exactly three
        fractional-second digits, and `version`, an integer that starts at 1 on
        creation and increases by exactly 1 on every mutation of that resource."

        Design: Corner/entities/patient_record_system_fields_are_server_minted
        """
        site = F.create_site(
            api, "SITE-E6", name="System Fields Clinic", region_code="US-IA",
            registrar_headcount=1,
        )

        created = F.create_record(
            api, site["id"], "E6-1000", "Lindqvist", "Elsa", "1983-05-05", "F",
            clinical_element_count=4,
        )
        read_back = A.assert_ok(api.get_record(created["id"], admin_headers()))

        A.assert_system_fields(created, expected_version=1)
        A.assert_millisecond_timestamp(created["created_at"], "created_at")
        A.assert_instant(created["created_at"], "2026-08-01T00:00:00Z", "created_at")
        assert read_back["id"] == created["id"]
        assert read_back["created_at"] == created["created_at"]
        A.assert_instant(read_back["updated_at"], "2026-08-01T00:00:00Z", "updated_at")
        A.assert_version(read_back, 1)
        assert read_back["enterprise_id"] == "EID-SITE-E6-E6-1000"
        assert read_back["identity_state"] == IDENTITY_ACTIVE
        assert read_back["integrity_state"] == INTEGRITY_CLEAR


class TestImmutableEvidenceRows:
    def test_an_evidence_row_carries_no_version_and_no_updated_at(self, api):
        """The pair carries the version; the evidence entry is a write-once event.

        PRD §2.4: "Three resource kinds are write-once event records and deliberately
        carry **only** `id` and `created_at` — they have neither `updated_at` nor
        `version`, and no endpoint mutates them after creation."

        Design: Corner/entities/review_evidence_is_immutable_with_no_version_field
        """
        site = F.create_site(
            api, "SITE-E8", name="Evidence Immutability Clinic", region_code="US-VT",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "E8-1000", "Rasmussen", "Freja", "1981-03-14", "F",
            ssn_last4="4242", clinical_element_count=3,
        )
        record_b = F.create_record(
            api, site["id"], "E8-2000", "Rasmussen", "Freja", "1981-03-14", "F",
            clinical_element_count=1,
        )
        pair = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )
        assert pair["queue_state"] == QUEUE_NEW
        F.advance_to_under_review(api, pair["id"], "Immutability probe.")

        evidence = A.assert_created(
            api.add_evidence(
                pair["id"],
                f.evidence_payload(
                    "PHONE_VERIFICATION", OUTCOME_INCONCLUSIVE, 0.00,
                    note="Number disconnected.",
                ),
                analyst_headers(),
            )
        )

        A.assert_write_once_fields(evidence)
        A.assert_instant(evidence["created_at"], "2026-08-01T00:00:00Z", "created_at")
        assert evidence["pair_id"] == pair["id"]
        assert evidence["evidence_type"] == "PHONE_VERIFICATION"
        assert evidence["outcome"] == OUTCOME_INCONCLUSIVE
        A.assert_score(evidence["weight_points"], 0.00, "weight_points")
        assert evidence["submitted_by_user_id"] == "analyst-1"
        rows = A.list_rows(
            api.list_evidence(pair["id"], admin_headers(), {"limit": 10, "offset": 0}),
            expected_total=1,
        )
        assert len(rows) == 1
        final = F.get_pair(api, pair["id"])
        A.assert_score(final["evidence_points"], 0.00, "evidence_points")
        A.assert_score(final["evidence_adjustment"], 0.00, "evidence_adjustment")
        A.assert_version(final, 4)
