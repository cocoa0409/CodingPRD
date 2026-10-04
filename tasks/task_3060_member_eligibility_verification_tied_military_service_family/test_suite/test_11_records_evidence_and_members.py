"""Service-record computed fields, evidence uniqueness, and member list
pagination defaults."""
from test_helpers import ApiErrorId, validate_error, validate_paginated
from test_helpers import fixtures
from test_helpers.fixtures import (
    ADMIN,
    APPLICANT,
    add_evidence,
    build_case,
    add_service_record,
)


class TestServiceRecordComputation:
    def test_service_days_computed_from_dates(self, api):
        """PRD §3.2: "From these the system computes `service_days` as the
        calendar-day count from `service_start_date` to the `service_end_date`
        when one is set, or to the current logical-clock date when the period
        is open; a zero-length period yields 0." and "Every record begins
        with `service_verified` set to `false`..."

        Design: Corner/entities/service_record_computed_service_days
        """
        case = build_case(api, applicant_legal_name="Day Counter")
        record = add_service_record(
            api, case["id"], service_start_date="2000-01-01",
            service_end_date="2000-01-11",
        )
        assert record["service_days"] == 10
        assert record["service_verified"] is False


class TestEvidenceUniqueness:
    def test_same_case_duplicate_hash_rejected(self, api):
        """PRD §3.2: "Within a case, the pair of case and `content_hash` is a
        uniqueness anchor: a second upload with a digest already present on
        that case is rejected with `ERR_DUPLICATE_EVIDENCE` (HTTP 409)."

        Design: Corner/validations/duplicate_evidence_content_hash_conflict
        """
        case = build_case(api, applicant_legal_name="Dup One")
        add_evidence(api, case["id"], content_hash="dup1")
        resp = api.upload_evidence(
            case["id"],
            {"doc_type": "NGB22", "issuing_authority": "NGB",
             "issued_on": "2011-01-01", "content_hash": "dup1"},
            APPLICANT,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EVIDENCE, 409)

    def test_same_hash_on_different_case_legal(self, api):
        """PRD §3.2: "Within a case, the pair of case and `content_hash` is a
        uniqueness anchor: a second upload with a digest already present on
        that case is rejected with `ERR_DUPLICATE_EVIDENCE` (HTTP 409)." —
        the anchor is scoped to the case, so another case accepts the hash.

        Design: Corner/validations/duplicate_evidence_content_hash_conflict
        """
        case_a = build_case(api, applicant_legal_name="Dup One A")
        add_evidence(api, case_a["id"], content_hash="dup1")
        case_b = build_case(api, applicant_legal_name="Dup Two B")
        doc = add_evidence(api, case_b["id"], content_hash="dup1")
        assert doc["case_id"] == case_b["id"]


class TestMemberListing:
    def test_members_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned
        items; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter skips a number of items and defaults to 0...
        and every list response carries the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."

        Design: Corner/entities/members_list_pagination_defaults
        """
        fixtures.approve_direct_member(api, name="List One")
        fixtures.approve_direct_member(api, name="List Two")
        data, meta = validate_paginated(api.list_members(ADMIN))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(data) == 2
