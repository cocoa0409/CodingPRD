"""Rule-set arithmetic, registrar scope and the two uniqueness guards."""

import pytest

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as F
from test_helpers.api_errors import (
    ERR_DUPLICATE_MRN,
    ERR_MERGE_SELF_REFERENCE,
    ERR_PAIR_ALREADY_EXISTS,
    ERR_SEARCH_ATTEMPT_REQUIRED,
    ERR_SITE_SCOPE_VIOLATION,
    ERR_THRESHOLD_ORDER_INVALID,
    ERR_WEIGHTS_SUM_INVALID,
)
from test_helpers.constants import (
    IDENTITY_ACTIVE,
    QUEUE_NEW,
    SCORE_VARIANT_STRICT,
)
from test_helpers.test_users import (
    admin_headers,
    analyst_headers,
    registrar_headers,
)

SHORT_WEIGHTS = {
    "last_name": 25.00,
    "first_name": 15.00,
    "dob": 25.00,
    "ssn_last4": 15.00,
    "sex": 5.00,
    "postal_code": 9.00,
    "phone": 5.00,
}

FULL_WEIGHTS = {
    "last_name": 25.00,
    "first_name": 15.00,
    "dob": 25.00,
    "ssn_last4": 15.00,
    "sex": 5.00,
    "postal_code": 10.00,
    "phone": 5.00,
}


class TestRuleSetArithmetic:
    def test_weights_summing_to_ninety_nine_are_refused(self, api):
        """The seven declared weights must total exactly one hundred.

        PRD §2.8: "The seven `attribute_weights` values sum to exactly 100.00 —
        otherwise `ERR_WEIGHTS_SUM_INVALID`, HTTP 422."

        Design: Corner/validations/attribute_weights_that_do_not_sum_to_one_hundred_are_rejected
        """
        response = api.create_rule_set(
            f.rule_set_payload(
                name="Short Weights", version_label="V-BAD-1",
                attribute_weights=SHORT_WEIGHTS,
            ),
            admin_headers(),
        )

        error = A.assert_error_envelope(response, ERR_WEIGHTS_SUM_INVALID, 422)
        assert error["error_id"] == ERR_WEIGHTS_SUM_INVALID
        assert isinstance(error["message"], str) and error["message"] != ""

    def test_the_threshold_order_check_runs_after_the_weight_sum_check(self, api):
        """Valid weights let the request reach the later, lower-ranked rule.

        PRD §2.8: "`review_threshold` does not exceed `auto_link_threshold` —
        otherwise `ERR_THRESHOLD_ORDER_INVALID`, HTTP 422."

        Design: Corner/validations/review_threshold_above_auto_link_threshold_is_rejected
        """
        response = api.create_rule_set(
            f.rule_set_payload(
                name="Inverted Thresholds", version_label="V-BAD-2",
                attribute_weights=FULL_WEIGHTS, auto_link_threshold=85.00,
                review_threshold=90.00,
            ),
            admin_headers(),
        )

        A.assert_error_envelope(response, ERR_THRESHOLD_ORDER_INVALID, 422)


class TestRegistrarScope:
    def test_a_registrar_cannot_register_a_chart_at_a_foreign_site(self, api):
        """The scope rule outranks the registrar's own missing-search-attempt rule.

        PRD §2.8: "When the role is `SiteRegistrar`, `X-User-ID` equals the
        registration site in scope: the `{id}` path segment when recording a
        registration search attempt, and the body's `site_id` when creating a patient
        record — otherwise `ERR_SITE_SCOPE_VIOLATION`, HTTP 403."

        Design: Corner/validations/site_registrar_registering_at_a_foreign_site_is_rejected
        """
        home = F.create_site(
            api, "SITE-V3A", name="Home Site", region_code="US-OH",
            registrar_headcount=2,
        )
        foreign = F.create_site(
            api, "SITE-V3B", name="Foreign Site", region_code="US-OH",
            registrar_headcount=2,
        )

        response = api.create_record(
            f.record_payload(
                foreign["id"], "V3-1000", "Kowalczyk", "Irena", "1981-01-19", "F",
                clinical_element_count=1,
            ),
            registrar_headers(home["id"]),
        )

        A.assert_error_envelope(response, ERR_SITE_SCOPE_VIOLATION, 403)
        assert A.list_rows(api.list_records(admin_headers()), expected_total=0) == []
        A.assert_site_counters(
            F.get_site(api, foreign["id"]), active_record_count=0
        )

    def test_the_search_attempt_requirement_binds_only_the_registrar(self, api):
        """The identical body is refused for the registrar and accepted for the analyst.

        PRD §2.8: "When the role is `SiteRegistrar`, `origin_search_attempt_id` is
        present in the body — otherwise `ERR_SEARCH_ATTEMPT_REQUIRED`, HTTP 422."

        Design: Corner/validations/search_attempt_requirement_applies_only_to_the_site_registrar
        """
        site = F.create_site(
            api, "SITE-V4", name="Conditional Rule Clinic", region_code="US-MI",
            registrar_headcount=3,
        )
        payload = f.record_payload(
            site["id"], "V4-1000", "Bergqvist", "Sten", "1974-04-14", "M",
            clinical_element_count=2,
        )

        refused = api.create_record(payload, registrar_headers(site["id"]))
        accepted = api.create_record(payload, analyst_headers())

        A.assert_error_envelope(refused, ERR_SEARCH_ATTEMPT_REQUIRED, 422)
        created = A.assert_created(accepted)
        assert created["mrn"] == "V4-1000"
        assert created["origin_search_attempt_id"] is None
        rows = A.list_rows(api.list_records(admin_headers()), expected_total=1)
        assert len(rows) == 1
        A.assert_site_counters(F.get_site(api, site["id"]), active_record_count=1)


class TestUniquenessGuards:
    def test_an_mrn_is_unique_within_its_site_and_free_at_the_next_one(self, api):
        """Uniqueness is on the site and mrn combination, not the mrn alone.

        PRD §2.8: "No existing patient record already holds the requested combination
        of `site_id` and `mrn` — otherwise `ERR_DUPLICATE_MRN`, HTTP 409."

        Design: Corner/validations/duplicate_mrn_is_rejected_per_site_not_globally
        """
        site_a = F.create_site(
            api, "SITE-V5A", name="MRN Clinic A", region_code="US-PA",
            registrar_headcount=2,
        )
        site_b = F.create_site(
            api, "SITE-V5B", name="MRN Clinic B", region_code="US-PA",
            registrar_headcount=2,
        )
        first = F.create_record(
            api, site_a["id"], "V5-1000", "Petrosyan", "Anahit", "1993-07-23", "F",
            clinical_element_count=2,
        )
        assert first["enterprise_id"] == "EID-SITE-V5A-V5-1000"

        clash = api.create_record(
            f.record_payload(
                site_a["id"], "V5-1000", "Petrosyan", "Anahit", "1993-07-23", "F",
                clinical_element_count=1,
            ),
            analyst_headers(),
        )
        elsewhere = api.create_record(
            f.record_payload(
                site_b["id"], "V5-1000", "Petrosyan", "Anahit", "1993-07-23", "F",
                clinical_element_count=1,
            ),
            analyst_headers(),
        )

        A.assert_error_envelope(clash, ERR_DUPLICATE_MRN, 409)
        second = A.assert_created(elsewhere)
        assert second["enterprise_id"] == "EID-SITE-V5B-V5-1000"
        rows = A.list_rows(api.list_records(admin_headers()), expected_total=2)
        assert len(rows) == 2
        A.assert_site_counters(F.get_site(api, site_a["id"]), active_record_count=1)
        A.assert_site_counters(F.get_site(api, site_b["id"]), active_record_count=1)

    def test_swapping_the_members_does_not_escape_the_live_pair_check(self, api):
        """The set of members is unordered, so the reversed request collides too.

        PRD §2.8: "No existing candidate pair over the same unordered set of
        `record_a_id` and `record_b_id` has a `queue_state` other than
        `RESOLVED_DISTINCT` or `RESOLVED_MERGED` — otherwise `ERR_PAIR_ALREADY_EXISTS`,
        HTTP 409."

        Design: Corner/validations/second_open_pair_over_the_same_two_records_is_rejected
        """
        site = F.create_site(
            api, "SITE-V6", name="Pair Uniqueness Clinic", region_code="US-VA",
            registrar_headcount=2,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record_a = F.create_record(
            api, site["id"], "V6-1000", "Halvorsen", "Ingrid", "1986-06-16", "F",
            ssn_last4="2020", postal_code="23219", phone="8045550101",
            clinical_element_count=3,
        )
        record_b = F.create_record(
            api, site["id"], "V6-2000", "Halvorsen", "Ingrid", "1986-06-16", "F",
            clinical_element_count=1,
        )
        first = F.create_pair(
            api, record_a["id"], record_b["id"], rule_set["id"],
            score_variant=SCORE_VARIANT_STRICT,
        )

        response = api.create_pair(
            f.pair_payload(
                record_b["id"], record_a["id"], rule_set["id"], SCORE_VARIANT_STRICT
            ),
            analyst_headers(),
        )

        A.assert_error_envelope(response, ERR_PAIR_ALREADY_EXISTS, 409)
        rows = A.list_rows(api.list_pairs(admin_headers()), expected_total=1)
        assert A.ids(rows) == [first["id"]]
        unchanged = F.get_pair(api, first["id"])
        assert unchanged["queue_state"] == QUEUE_NEW
        A.assert_version(unchanged, 1)

    def test_a_record_cannot_be_paired_with_itself(self, api):
        """The self-reference guard fires before any score is computed.

        PRD §2.8: "`survivor_record_id` differs from `subsumed_record_id`, and
        `record_a_id` differs from `record_b_id` — otherwise
        `ERR_MERGE_SELF_REFERENCE`, HTTP 422."

        Design: Corner/validations/pairing_a_record_with_itself_is_rejected
        """
        site = F.create_site(
            api, "SITE-V7", name="Self Reference Clinic", region_code="US-TN",
            registrar_headcount=1,
        )
        rule_set = F.create_rule_set(api, activate=False)
        record = F.create_record(
            api, site["id"], "V7-1000", "Aronsson", "Elias", "1997-12-02", "M",
            clinical_element_count=2,
        )

        response = api.create_pair(
            f.pair_payload(
                record["id"], record["id"], rule_set["id"], SCORE_VARIANT_STRICT
            ),
            analyst_headers(),
        )

        A.assert_error_envelope(response, ERR_MERGE_SELF_REFERENCE, 422)
        assert A.list_rows(api.list_pairs(admin_headers()), expected_total=0) == []
        assert F.get_record(api, record["id"])["identity_state"] == IDENTITY_ACTIVE
