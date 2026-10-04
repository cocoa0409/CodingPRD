"""Child registration claims: derived fields, guards, duplicates (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    BOGUS_UUID,
    DEFAULT_CHILD_SPECS,
    EnrollmentStatus,
    TEST_USERS,
    api_client,
    assert_child,
    create_child_payload,
    get_affiliate,
    get_child,
    make_affiliate_coordinator_headers,
    register_child,
    register_children,
    set_logical_clock,
    setup_operative_affiliate,
    setup_second_affiliate,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_MAIL_OPS = TEST_USERS["mail_ops_headers"]


class TestRegistrationShape:
    def test_child_registration_missing_birth_date_returns_invalid_request(self, api):
        """PRD §2.8: "**Body well-formedness** — required fields are present,
        types are correct, enum values are in range, ... and no unknown,
        system, or computed fields were supplied; any violation is
        `ERR_INVALID_REQUEST`."
        PRD §3.3: registration submits "`affiliate_id`, the child's
        `full_name` and `family_name`, the `birth_date`, and a
        `mailing_address`".

        Design: Corner/entities/child_registration_missing_birth_date_returns_invalid_request
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        payload = create_child_payload(affiliate["id"])
        del payload["birth_date"]
        resp = api.create_child(
            payload, make_affiliate_coordinator_headers(affiliate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_child_computed_fields_on_registration(self, api):
        """PRD §3.3: "The system derives three fields at creation:
        `postal_prefix`, the first three characters of the uppercased postal
        code; `registered_month`, the logical month of registration; and
        `expected_final_mailing_month`, the birth month plus fifty-nine months
        — the last month a book can mail to this child. A new child starts
        `ACTIVE` with `consecutive_returns` at zero, and the affiliate's
        `enrolled_count` increases by one."

        Design: Corner/entities/child_computed_fields_on_registration
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        child = register_child(
            affiliate["id"],
            full_name="Leap Day",
            family_name="Day",
            birth_date="2024-02-29T00:00:00Z",
            mailing_address={
                "line1": "5 Leap Ln", "city": "Nashville", "region": "TN",
                "postal_code": "37206", "country": "US",
            },
        )
        assert_child(child)
        assert child["postal_prefix"] == "372"
        assert child["registered_month"] == "2026-09"
        # Birth month 2024-02 plus fifty-nine months is 2029-01.
        assert child["expected_final_mailing_month"] == "2029-01"
        assert child["enrollment_status"] == EnrollmentStatus.ACTIVE.value
        assert child["consecutive_returns"] == 0
        assert child.get("unenroll_reason") is None
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 1

    def test_created_child_immediately_readable_with_identical_fields(self, api):
        """PRD §3.3: "The system derives three fields at creation:
        `postal_prefix`, the first three characters of the uppercased postal
        code; `registered_month`, the logical month of registration; and
        `expected_final_mailing_month`, the birth month plus fifty-nine months
        — the last month a book can mail to this child."
        PRD §2.1: "every role may call every retrieval and list endpoint".

        Design: Corner/consistency_model/created_child_immediately_readable_with_identical_fields
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        payload = create_child_payload(
            affiliate["id"],
            full_name="Read Me",
            family_name="Me",
            birth_date="2025-12-25T00:00:00Z",
            mailing_address={
                "line1": "7 Read Rd", "city": "Nashville", "region": "TN",
                "postal_code": "37204", "country": "US",
            },
        )
        created = validate_success(
            api.create_child(payload, make_affiliate_coordinator_headers(affiliate["id"])),
            201,
        )
        read_back = validate_success(api.get_child(created["id"], _MAIL_OPS), 200)
        assert_child(read_back)
        assert read_back["full_name"] == "Read Me"
        assert read_back["postal_prefix"] == "372"
        assert read_back["enrollment_status"] == EnrollmentStatus.ACTIVE.value
        # Birth month 2025-12 plus fifty-nine months is 2030-11.
        assert read_back["expected_final_mailing_month"] == "2030-11"
        assert read_back["registered_month"] == "2026-09"
        rows, meta = validate_paginated(
            api.list_children(_ADMIN, params={"affiliate_id": affiliate["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == created["id"]


class TestRegistrationReads:
    def test_get_child_with_unknown_id_returns_child_not_found(self, api):
        """PRD §2.8: "identifiers in the URL are resolved strictly left to
        right; the first identifier that does not exist yields that entity's
        specific 404. The entity-specific not-found codes are
        `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_AFFILIATE_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_CHILD_NOT_FOUND`,
        `ERR_ADDRESS_CHANGE_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`,
        `ERR_SELECTION_NOT_FOUND`, `ERR_PRINT_ORDER_NOT_FOUND`,
        `ERR_WAVE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, and
        `ERR_INVOICE_NOT_FOUND`."

        Design: Corner/entities/get_child_with_unknown_id_returns_child_not_found
        """
        set_logical_clock()
        resp = api.get_child(BOGUS_UUID, _ADMIN)
        validate_error(resp, ApiErrorId.ERR_CHILD_NOT_FOUND)

    def test_children_list_paginates_and_filters(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter states how many items to skip and defaults to 0."
        and "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."
        PRD §3.3: "Children can be listed with `affiliate_id`,
        `enrollment_status`, and `transfer_source_child_id` filters".

        Design: Corner/entities/children_list_paginates_and_filters
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        register_children(affiliate["id"])
        rows, meta = validate_paginated(
            api.list_children(
                _ADMIN, params={"affiliate_id": affiliate["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        rows, meta = validate_paginated(
            api.list_children(
                _ADMIN, params={"affiliate_id": affiliate["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        rows, meta = validate_paginated(
            api.list_children(
                _ADMIN,
                params={"affiliate_id": affiliate["id"], "enrollment_status": "ACTIVE"},
            )
        )
        assert len(rows) == 3
        rows, meta = validate_paginated(
            api.list_children(
                _ADMIN,
                params={"affiliate_id": affiliate["id"], "enrollment_status": "GRADUATED"},
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        rows, meta = validate_paginated(api.list_children(_ADMIN))
        assert len(rows) == 3, "default limit 10 / offset 0 returns all three"
        assert meta["has_more"] is False


class TestRegistrationGuards:
    def test_duplicate_registration_rejected(self, api):
        """PRD §3.3: "no non-terminal child in the same affiliate may share the
        same birth date, the same postal prefix, and the same family name
        compared case-insensitively — a match is `ERR_DUPLICATE_REGISTRATION`".

        Design: Corner/validations/duplicate_registration_rejected
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        register_children(affiliate["id"], DEFAULT_CHILD_SPECS[:1])
        duplicate = create_child_payload(
            affiliate["id"],
            full_name="Ada BARNES",
            family_name="barnes",
            birth_date="2026-05-10T00:00:00Z",
            mailing_address={
                "line1": "99 Other St", "city": "Nashville", "region": "TN",
                "postal_code": "37201", "country": "US",
            },
        )
        resp = api.create_child(
            duplicate, make_affiliate_coordinator_headers(affiliate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 1

    def test_registration_address_outside_geography_rejected(self, api):
        """PRD §3.3: "The child's derived `postal_prefix` must appear in the
        affiliate's `postal_prefixes`, else `ERR_ADDRESS_NOT_COVERED`."

        Design: Corner/validations/registration_address_outside_geography_rejected
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        payload = create_child_payload(
            affiliate["id"],
            full_name="Far Away",
            family_name="Away",
            birth_date="2026-03-01T00:00:00Z",
            mailing_address={
                "line1": "1 Far St", "city": "Nowhere", "region": "AK",
                "postal_code": "99999", "country": "US",
            },
        )
        resp = api.create_child(
            payload, make_affiliate_coordinator_headers(affiliate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ADDRESS_NOT_COVERED)

    def test_registration_without_active_agreement_rejected(self, api):
        """PRD §3.3: "The registering affiliate must be operative in the
        current logical month, else `ERR_AFFILIATE_NOT_OPERATIVE`."
        PRD §3.1: "Operability is a derived flag, `operative`, that turns true
        only when an `ACTIVE` agreement fully covers the current logical
        month".

        Design: Corner/validations/registration_without_active_agreement_rejected
        """
        base = setup_operative_affiliate(approve=False)
        affiliate = base["affiliate"]
        assert affiliate["operative"] is False
        payload = create_child_payload(
            affiliate["id"],
            full_name="Too Early",
            family_name="Early",
            birth_date="2026-03-01T00:00:00Z",
        )
        resp = api.create_child(
            payload, make_affiliate_coordinator_headers(affiliate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AFFILIATE_NOT_OPERATIVE)
        assert get_affiliate(affiliate["id"])["operative"] is False

    def test_coordinator_cannot_register_into_other_affiliate(self, api):
        """PRD §2.1: "When `X-User-Role` is `AffiliateCoordinator`, `X-User-ID`
        is the `id` of the `Affiliate` that coordinator runs; ownership checks
        on any resource that references an affiliate — children, address
        changes, population stats, invoice payment and dispute, and
        affiliate-scoped reads — compare the resource's affiliate reference to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/coordinator_cannot_register_into_other_affiliate
        """
        base = setup_operative_affiliate()
        program, affiliate_a = base["program"], base["affiliate"]
        second = setup_second_affiliate(
            program, ["371"], approve=False,
            name="Memphis Shelby Books", contact_email="coord@msb.org",
        )
        affiliate_b = second["affiliate"]
        payload = create_child_payload(
            affiliate_a["id"],
            full_name="Cross Town",
            family_name="Town",
            birth_date="2026-03-01T00:00:00Z",
        )
        resp = api.create_child(
            payload, make_affiliate_coordinator_headers(affiliate_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_affiliate(affiliate_a["id"])["enrolled_count"] == 0


class TestRegistrationAgeBoundary:
    def test_registration_at_59_months_succeeds(self, api):
        """PRD §3.3: "The child's age in whole months at the registration month
        must be at most 59; a child who is already 60 months or older in that
        month is too old for the program and is rejected with
        `ERR_CHILD_AGE_INELIGIBLE`".
        PRD §2.4: "A child's age at any reference month is measured in whole
        months: take the reference month's year times twelve plus its month
        number, subtract the birth date's year times twelve plus its month
        number, and ignore the day of the month entirely."

        Design: Difficulty/boundary_precision_check/registration_age_boundary_59_vs_60_months
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        payload = create_child_payload(
            affiliate["id"],
            full_name="Gi Hale",
            family_name="Hale",
            birth_date="2021-10-15T00:00:00Z",
            mailing_address={
                "line1": "8 Vine St", "city": "Nashville", "region": "TN",
                "postal_code": "37211", "country": "US",
            },
        )
        resp = api.create_child(
            payload, make_affiliate_coordinator_headers(affiliate["id"])
        )
        child = validate_success(resp, 201)
        assert_child(child)
        assert child["enrollment_status"] == EnrollmentStatus.ACTIVE.value
        # Born 2021-10, age at registration month 2026-09 is exactly 59;
        # expected_final_mailing_month is the birth month plus 59 months.
        assert child["expected_final_mailing_month"] == "2026-09"
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 1

    def test_registration_at_60_months_rejected(self, api):
        """PRD §3.3: "The child's age in whole months at the registration month
        must be at most 59; a child who is already 60 months or older in that
        month is too old for the program and is rejected with
        `ERR_CHILD_AGE_INELIGIBLE`".

        Design: Difficulty/boundary_precision_check/registration_age_boundary_59_vs_60_months
        """
        base = setup_operative_affiliate()
        affiliate = base["affiliate"]
        payload = create_child_payload(
            affiliate["id"],
            full_name="Hu Irwin",
            family_name="Irwin",
            birth_date="2021-09-15T00:00:00Z",
            mailing_address={
                "line1": "10 Rose St", "city": "Nashville", "region": "TN",
                "postal_code": "37212", "country": "US",
            },
        )
        resp = api.create_child(
            payload, make_affiliate_coordinator_headers(affiliate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CHILD_AGE_INELIGIBLE)
        assert get_affiliate(affiliate["id"])["enrolled_count"] == 0, (
            "the rejected 60-month registration must not enroll anyone"
        )
