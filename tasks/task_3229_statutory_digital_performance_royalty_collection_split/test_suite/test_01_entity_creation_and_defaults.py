"""Entity creation, field validation, defaults, and envelope claims (queue B)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_active_licensee,
    create_licensee_payload,
    create_play_line_payload,
    create_pool,
    create_rate_schedule_payload,
    create_recording_payload,
    create_report_with_lines,
    create_verified_artist,
    create_verified_rights_owner,
    make_admin_headers,
    make_licensee_headers,
    make_payee_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = TEST_USERS["royalty_ops_headers"]
PAYEE = make_payee_admin_headers()


class TestLicenseeCreation:
    def test_create_licensee_with_required_fields_returns_draft(self, api):
        """PRD §3.1: "A freshly registered licensee starts in `DRAFT` status,
        recorded in its `license_status` field, and cannot file usage reports
        until activated."
        PRD §2.4: "Every resource in this system carries a server-minted `id`
        in UUID form with no type prefix, a `created_at` timestamp in ISO 8601
        UTC with three fractional digits, an `updated_at` timestamp in the same
        format, and an integer `version` starting at 1 that increments on every
        mutation of the resource."

        Design: Corner/entities/create_licensee_with_required_fields_returns_201
        """
        resp = api.create_licensee(
            create_licensee_payload(
                legal_name="NewCo",
                service_category="BUSINESS_ESTABLISHMENT",
                notice_date="2026-01-01T00:00:00Z",
            ),
            ADMIN,
        )
        created = validate_success(resp, expected_status=201)
        got = validate_success(api.get_licensee(created["id"], ADMIN))
        assert got["license_status"] == "DRAFT"
        assert got["version"] == 1
        import re
        assert re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            got["id"],
        ), "id must be a UUID with no type prefix"

    def test_create_licensee_missing_service_category_rejected(self, api):
        """PRD §2.8: "fifth, field-level validity — required fields present,
        types valid, enum members valid, numeric ranges respected ...
        (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/create_licensee_missing_service_category_returns_invalid_request
        """
        resp = api.create_licensee({"legal_name": "NoCat"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_licensee_invalid_enum_service_category_rejected(self, api):
        """PRD §3.1: "its `service_category` — exactly one of
        `PREEXISTING_SUBSCRIPTION`, `NONSUBSCRIPTION_AD_SUPPORTED`, or
        `BUSINESS_ESTABLISHMENT`, which determines the applicable statutory
        rate schedule"
        PRD §2.8: "fifth, field-level validity — required fields present, types
        valid, enum members valid, numeric ranges respected ...
        (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/create_licensee_invalid_enum_service_category_rejected
        """
        resp = api.create_licensee(
            {
                "legal_name": "BadCat",
                "service_category": "INTERACTIVE",
                "notice_date": "2026-01-01T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_licensee_computed_annual_minimum_fee_input_ignored(self, api):
        """PRD §2.6: "A licensee's `annual_minimum_fee_cents` is likewise sourced
        from the EFFECTIVE RateSchedule for the licensee's category at the time
        of the liability run, and is a computed field of value zero or greater."

        Design: Corner/entities/licensee_computed_annual_minimum_fee_input_ignored_returns_201
        """
        resp = api.create_licensee(
            create_licensee_payload(
                legal_name="FirmCo", annual_minimum_fee_cents=999999999,
            ),
            ADMIN,
        )
        created = validate_success(resp, expected_status=201)
        got = validate_success(api.get_licensee(created["id"], ADMIN))
        assert got["annual_minimum_fee_cents"] != 999999999, (
            "client-supplied value of a computed field must be ignored"
        )
        assert got["annual_minimum_fee_cents"] >= 0


class TestCatalogAndValidation:
    def test_get_nonexistent_recording_returns_not_found(self, api):
        """PRD §2.11: "a nonexistent id anywhere in the chain yields
        `ERR_NOT_FOUND` (HTTP 404) at the first position that fails to resolve."

        Design: Corner/entities/get_nonexistent_recording_returns_not_found
        """
        resp = api.get_recording(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_recording_duplicate_isrc_rejected(self, api):
        """PRD §3.7: "An `Admin` registers a Recording with its `isrc` — the
        International Standard Recording Code, unique across all recordings;
        registering a duplicate ISRC is rejected with `ERR_DUPLICATE_ISRC`
        (HTTP 409)"

        Design: Corner/entities/recording_duplicate_isrc_rejected
        """
        ro = create_verified_rights_owner(legal_name="LD", contact_email="ld@x.com")
        fa = create_verified_artist(stage_name="AD", contact_email="ad2@x.com")
        first = api.create_recording(
            create_recording_payload(ro["id"], fa["id"], isrc="ISRC-DUP",
                                     track_title="one"),
            ADMIN,
        )
        validate_success(first, expected_status=201)
        dup = api.create_recording(
            create_recording_payload(ro["id"], fa["id"], isrc="ISRC-DUP",
                                     track_title="two"),
            ADMIN,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_ISRC.value)

    def test_rate_schedule_end_before_start_rejected(self, api):
        """PRD §3.2: "the inclusive window from `effective_start` through
        `effective_end` (the end must be strictly after the start)"
        PRD §2.8: "fifth, field-level validity — required fields present, types
        valid, enum members valid, numeric ranges respected ...
        (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/rate_schedule_end_before_start_rejected
        """
        resp = api.create_rate_schedule(
            create_rate_schedule_payload(
                proceeding_ref="D-X",
                effective_start="2026-06-01T00:00:00Z",
                effective_end="2026-06-01T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_play_line_zero_performances_rejected(self, api):
        """PRD §2.8: "such as `performance_count` being strictly positive,
        `claimed_share_pct` being greater than 0 and at most 100,
        `effective_end` strictly after `effective_start`, and `period_end` on or
        after `period_start` (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/play_line_zero_performances_rejected
        """
        lic = create_active_licensee(legal_name="ZC")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(lic["id"], [], "2026-01-01T00:00:00Z",
                                             "2026-01-31T00:00:00Z")
        resp = api.add_play_line(
            report["id"],
            create_play_line_payload(isrc="X", track_title="t", artist_name="a",
                                     performance_count=0),
            lh,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_unclaimed_pool_created_with_zero_accrual_defaults(self, api):
        """PRD §3.9: "The pool's `pool_status` starts as `ACCRUING`, with
        `accrued_unmatched_cents` at 0, `distributed_cents` at 0, and
        `campaign_count` at 0."

        Design: Corner/entities/unclaimed_pool_created_with_zero_accrual_defaults
        """
        pool = create_pool()
        assert pool["pool_status"] == "ACCRUING"
        assert pool["accrued_unmatched_cents"] == 0
        assert pool["campaign_count"] == 0


class TestListEnvelope:
    def test_list_licensees_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept the query parameters `limit` and
        `offset`. The default `limit` is 10; the smallest accepted value is 1
        and the largest is 100."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/entities/list_licensees_pagination_envelope
        """
        api.create_licensee(create_licensee_payload(legal_name="P1"), ADMIN)
        api.create_licensee(create_licensee_payload(legal_name="P2"), ADMIN)
        resp = api.list_licensees(ADMIN)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 2
