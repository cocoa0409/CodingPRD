"""Membership lifecycle: enrollment defaults, member_type derivation, LIFETIME
exemptions, lapse sweep, renewal, reminders, pagination, and enrollment
validation."""
import re

from test_helpers import (
    CLOCK_DEFAULT_UTC,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_record_item,
    create_member_payload,
    enroll_member,
    get_member,
    is_valid_uuid,
    list_member_reminders,
    make_member_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ZERO_UUID = NON_EXISTENT_UUID


class TestEnrollmentDefaults:
    def test_enroll_standard_adult_returns_active_with_minted_identifier(self, api, admin_headers):
        """PRD §3.1: "Enrollment immediately places the member in `ACTIVE` status,
        mints a public `identifier_code` in the format `MID-######` — unique, printed
        on the engraved products, and never used for ordering or tie-breaks — and
        computes `expires_on` as the enrollment date plus the tier's term: twelve
        months for `STANDARD`, twenty-four months for `PREMIUM`."
        PRD §3.1: "The base fee is 4000 cents for `STANDARD` per twelve-month term,
        7500 cents for `PREMIUM` per twenty-four-month term, and 50000 cents for
        `LIFETIME` as a one-time charge with no renewal."

        Design: Corner/entities/member_enroll_returns_defaults_and_mints_identifier
        """
        set_clock(api=api)
        resp = api.create_member(
            create_member_payload(
                full_name="Nina New",
                email="nina@x.com",
                membership_tier="STANDARD",
                date_of_birth="1990-05-05",
            ),
            admin_headers,
        )
        member = validate_success(resp, expected_status=201)
        assert is_valid_uuid(member["id"])
        assert member["status"] == "ACTIVE"
        assert member["version"] == 1
        assert member["member_type"] == "ADULT"
        assert member["balance_cents"] == 4000, (
            f"STANDARD enrollment fee is 4000, got {member['balance_cents']}"
        )
        assert member["wallet_credit_cents"] == 0
        assert member["record_revision"] == 0
        assert member["has_cognitive_condition"] is False
        assert member["first_lifetime_sync_order_consumed"] is False
        assert re.match(r"^MID-\d{6}$", member["identifier_code"]), (
            f"identifier_code must match MID-######, got {member['identifier_code']!r}"
        )
        assert member["expires_on"] == "2027-09-01"

    def test_enroll_standard_adult_computed_fields_not_client_supplied(self, api, admin_headers):
        """PRD §2.7: "Most resources in the system carry the standard four
        system-managed fields: `id`, a server-minted UUID with no type prefix;
        `created_at`, an ISO 8601 UTC timestamp with three fractional digits
        recorded at creation; `updated_at`, the same format, refreshed on every
        mutation; and `version`, an integer that starts at 1 and increments by 1
        on every mutation of the resource."

        Design: Corner/entities/member_enroll_returns_defaults_and_mints_identifier
        """
        set_clock(api=api)
        resp = api.create_member(create_member_payload(), admin_headers)
        member = validate_success(resp, expected_status=201)
        assert member["version"] == 1
        assert member["record_revision"] == 0
        assert member["has_cognitive_condition"] is False
        assert member["first_lifetime_sync_order_consumed"] is False
        assert member["status"] == "ACTIVE"
        # system-stamped timestamps present
        assert isinstance(member["created_at"], str) and member["created_at"]
        assert isinstance(member["updated_at"], str) and member["updated_at"]


class TestMemberTypeDerivation:
    def test_minor_enrollment_derives_member_type_minor(self, api, admin_headers):
        """PRD §3.1: "From `date_of_birth` and the current logical date, the system
        derives `member_type`: a person younger than 18 at enrollment becomes
        `MINOR`, otherwise `ADULT`."

        Design: Corner/entities/minor_enrollment_derives_member_type_minor
        """
        set_clock(api=api)
        member = enroll_member(tier="STANDARD", dob="2015-01-01", api=api)
        assert member["member_type"] == "MINOR"
        assert member["expires_on"] == "2027-09-01", (
            f"same term math as adults, got {member['expires_on']}"
        )

    def test_member_type_ignored_when_client_supplies_it(self, api, admin_headers):
        """PRD §3.1: "From `date_of_birth` and the current logical date, the system
        derives `member_type`: a person younger than 18 at enrollment becomes
        `MINOR`, otherwise `ADULT`."

        Design: Corner/entities/minor_enrollment_derives_member_type_minor
        """
        set_clock(api=api)
        payload = create_member_payload(date_of_birth="2015-01-01")
        payload["member_type"] = "ADULT"  # client attempt to override the derivation
        resp = api.create_member(payload, admin_headers)
        member = validate_success(resp, expected_status=201)
        assert member["member_type"] == "MINOR", (
            "member_type is derived from date_of_birth, not taken from the client"
        )


class TestLifetimeMember:
    def test_lifetime_member_has_null_expires_on(self, api, admin_headers):
        """PRD §3.1: "For `LIFETIME` members `expires_on` is null; their membership
        never expires, never lapses, and never renews."

        Design: Corner/entities/lifetime_member_has_null_expires_on_and_never_suspends
        """
        set_clock(api=api)
        member = enroll_member(tier="LIFETIME", dob="1970-01-01", api=api)
        assert member["expires_on"] is None
        assert member["balance_cents"] == 50000

    def test_lifetime_member_never_lapses_under_clock_advance(self, api, admin_headers):
        """PRD §2.4: "Every `Member` whose `status` is `ACTIVE`, whose
        `membership_tier` is anything other than `LIFETIME`, and whose `expires_on`
        is on or before the new logical date transitions to `SUSPENDED` per the
        member lifecycle (see §3.2). Members on the `LIFETIME` tier never lapse."

        Design: Corner/entities/lifetime_member_has_null_expires_on_and_never_suspends
        """
        set_clock(api=api)
        member = enroll_member(tier="LIFETIME", dob="1970-01-01", api=api)
        set_clock("2028-09-01T00:00:00Z", api=api)
        after = get_member(member["id"], api=api)
        assert after["status"] == "ACTIVE", "LIFETIME members never lapse"
        assert after["balance_cents"] == 50000, (
            "one-time LIFETIME enrollment fee, nothing more accrued"
        )


class TestMembersListing:
    def _three_members_one_cancelled(self, api, admin_headers):
        set_clock(api=api)
        p1 = enroll_member(full_name="P One", email="p1@x.com", dob="1980-01-01", api=api)
        enroll_member(full_name="P Two", email="p2@x.com", dob="1980-01-02", api=api)
        p3 = enroll_member(full_name="P Three", email="p3@x.com", dob="1980-01-03", api=api)
        validate_success(api.cancel_member(p3["id"], admin_headers), expected_status=200)
        return p1, p3

    def test_members_list_paginates_with_limit_offset(self, api, admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips that many items from the front of the result set and
        defaults to 0."

        Design: Corner/entities/members_list_paginates_with_filter_and_envelope
        """
        self._three_members_one_cancelled(api, admin_headers)
        data, meta = validate_paginated(api.list_members(admin_headers, params={"limit": 2, "offset": 0}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        data2, meta2 = validate_paginated(api.list_members(admin_headers, params={"limit": 2, "offset": 2}))
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_members_list_status_filter_narrows_total_count(self, api, admin_headers):
        """PRD §2.3: "Paginated list responses carry four fields in the `meta` block
        of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/members_list_paginates_with_filter_and_envelope
        """
        _p1, p3 = self._three_members_one_cancelled(api, admin_headers)
        data, meta = validate_paginated(api.list_members(admin_headers, params={"status": "CANCELLED"}))
        assert len(data) == 1
        assert data[0]["id"] == p3["id"]
        assert meta["total_count"] == 1
        # no parameters: defaults limit 10, offset 0
        data_all, meta_all = validate_paginated(api.list_members(admin_headers))
        assert len(data_all) == 3
        assert meta_all["limit"] == 10
        assert meta_all["offset"] == 0


class TestMemberNotFound:
    def test_get_unknown_member_returns_member_not_found(self, api, admin_headers):
        """PRD §2.5: "Any id segment equal to the zero UUID
        `00000000-0000-0000-0000-000000000000` is a deliberately unreachable test id."
        PRD §2.5: "For any nested path — for instance a record item addressed under
        a member — the parent segment is validated before the child, so a missing
        parent surfaces its 404 before the child is even looked up."

        Design: Corner/entities/get_unknown_member_returns_member_not_found
        """
        resp = api.get_member(ZERO_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


class TestEnrollmentValidation:
    def test_enroll_missing_email_returns_invalid_request(self, api, admin_headers):
        """PRD §2.5: "Payload shape — `ERR_INVALID_REQUEST` for missing required
        fields, enum values outside their declared sets, malformed ISO 8601 dates,
        or integers out of range."

        Design: Corner/entities/enroll_missing_email_returns_invalid_request
        """
        resp = api.create_member(
            {"full_name": "No Mail", "membership_tier": "STANDARD", "date_of_birth": "1990-01-01"},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_enroll_bad_tier_enum_returns_invalid_request(self, api, admin_headers):
        """PRD §2.5: "Payload shape — `ERR_INVALID_REQUEST` for missing required
        fields, enum values outside their declared sets, malformed ISO 8601 dates,
        or integers out of range."

        Design: Corner/entities/enroll_missing_email_returns_invalid_request
        """
        resp = api.create_member(
            create_member_payload(membership_tier="GOLD"),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestDuplicateEmail:
    def test_duplicate_email_rejected_on_enroll(self, api, admin_headers):
        """PRD §3.1: "The email must be unique across all members; a duplicate is
        rejected with `ERR_DUPLICATE_EMAIL`."

        Design: Corner/validations/duplicate_email_rejected_on_enroll
        """
        set_clock(api=api)
        enroll_member(full_name="First Dup", email="dup@x.com", dob="1980-01-01", api=api)
        resp = api.create_member(
            create_member_payload(
                full_name="Second Dup", email="dup@x.com",
                membership_tier="PREMIUM", date_of_birth="1990-01-01",
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value)


class TestEarlyRenewal:
    def test_early_renewal_extends_from_existing_expiry_not_now(self, api):
        """PRD §3.2: "An **early renewal** moves `ACTIVE` to `ACTIVE`: the new
        `expires_on` is the later of the current `expires_on` and the current
        logical date, plus the tier's term — so an early renewal never shortens
        the remaining term."

        Design: Corner/calculations/early_renewal_extends_from_existing_expiry_not_now
        """
        set_clock(api=api)
        member = enroll_member(full_name="Erin Early", email="erin@x.com", dob="1994-04-04", api=api)
        assert member["expires_on"] == "2027-09-01"
        renewed = validate_success(
            api.renew_member(member["id"], {"amount_paid_cents": 4000}, make_member_headers(member["id"])),
            expected_status=200,
        )
        assert renewed["status"] == "ACTIVE"
        assert renewed["expires_on"] == "2028-09-01", (
            f"old expiry + 12 months, not today + 12; got {renewed['expires_on']}"
        )
        assert renewed["balance_cents"] == 8000, (
            f"4000 enrollment + 4000 renewal, got {renewed['balance_cents']}"
        )


class TestRenewalInsufficientFunds:
    def test_renewal_one_cent_short_returns_402_and_stays_suspended(self, api):
        """PRD §3.2: "The funds test is the same in both directions: the member's
        `wallet_credit_cents` plus the supplied `amount_paid_cents` must cover the
        renewal fee for their tier — computed exactly as in §3.1, including the
        dependent factor when an active guardianship exists and the cognitive
        surcharge when the member's `has_cognitive_condition` flag is currently
        true. A shortfall is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402)."

        Design: Corner/validations/renewal_insufficient_funds_returns_402
        """
        set_clock(api=api)
        member = enroll_member(full_name="Ian Insufficient", email="ian@x.com", dob="1984-04-04", api=api)
        # Advance past expiry so the lapse sweep flips the member to SUSPENDED.
        set_clock("2027-09-02T00:00:00Z", api=api)
        assert get_member(member["id"], api=api)["status"] == "SUSPENDED"
        resp = api.renew_member(member["id"], {"amount_paid_cents": 3999}, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)
        assert get_member(member["id"], api=api)["status"] == "SUSPENDED"

    def test_reactivation_with_exact_fee_succeeds(self, api):
        """PRD §3.2: "A **reactivation** moves `SUSPENDED` back to `ACTIVE`: the new
        `expires_on` is the current logical date plus the tier's term."

        Design: Corner/validations/renewal_insufficient_funds_returns_402
        """
        set_clock(api=api)
        member = enroll_member(full_name="Ian Exact", email="ian2@x.com", dob="1984-04-04", api=api)
        set_clock("2027-09-02T00:00:00Z", api=api)
        renewed = validate_success(
            api.renew_member(member["id"], {"amount_paid_cents": 4000}, make_member_headers(member["id"])),
            expected_status=200,
        )
        assert renewed["status"] == "ACTIVE"
        assert renewed["expires_on"] == "2028-09-02", (
            f"reactivation: current logical date + 12 months, got {renewed['expires_on']}"
        )


class TestLapseSweep:
    def test_lapse_sweep_flips_status_and_cancels_pending_reminders(self, api):
        """PRD §3.2: "The sweep cancels every `PENDING` reminder on the member,
        generates a fresh `LAPSE_WARNING` reminder due on `expires_on`, and appends
        an `AuditEvent` with action `LAPSE`."

        Design: Corner/state_machines/member_lapse_sweep_flips_status_and_cancels_pending_reminders
        """
        set_clock(api=api)
        member = enroll_member(full_name="Lena Lapsed", email="lena2@x.com", dob="1988-08-08", api=api)
        # expires_on == today lapses the member (sweep uses on-or-before).
        set_clock("2027-09-01T00:00:00Z", api=api)
        assert get_member(member["id"], api=api)["status"] == "SUSPENDED"
        reminders = list_member_reminders(member["id"], api=api)
        renewals = [r for r in reminders if r["reminder_kind"] == "RENEWAL"]
        record_updates = [r for r in reminders if r["reminder_kind"] == "RECORD_UPDATE"]
        lapse_warnings = [r for r in reminders if r["reminder_kind"] == "LAPSE_WARNING"]
        assert renewals and all(r["status"] == "CANCELLED" for r in renewals)
        assert record_updates and all(r["status"] == "CANCELLED" for r in record_updates)
        assert len(lapse_warnings) == 1, f"expected exactly one LAPSE_WARNING, got {len(lapse_warnings)}"
        assert lapse_warnings[0]["due_on"] == "2027-09-01"
        assert lapse_warnings[0]["status"] == "PENDING"

    def test_member_active_the_day_before_expiry(self, api):
        """PRD §2.4: "Every `Member` whose `status` is `ACTIVE`, whose
        `membership_tier` is anything other than `LIFETIME`, and whose `expires_on`
        is on or before the new logical date transitions to `SUSPENDED` per the
        member lifecycle (see §3.2)."

        Design: Corner/state_machines/member_lapse_sweep_flips_status_and_cancels_pending_reminders
        """
        set_clock(api=api)
        member = enroll_member(full_name="Lena Before", email="lena3@x.com", dob="1988-08-08", api=api)
        set_clock("2027-08-31T00:00:00Z", api=api)
        assert get_member(member["id"], api=api)["status"] == "ACTIVE", (
            "expires_on not yet reached: the member stays ACTIVE"
        )


class TestRecordUpdateReminderReanchor:
    def test_record_update_reminder_reanchored_on_record_change(self, api):
        """PRD §3.7: "A `RECORD_UPDATE` reminder is due one hundred eighty days
        after the member's last record change, where the last record change is the
        latest `created_at` among the member's items whose status is `VERIFIED` or
        `PENDING_VERIFICATION`; it re-anchors whenever `record_revision` increments."

        Design: Corner/calculations/record_update_reminder_reanchored_on_record_change
        """
        set_clock(api=api)
        member = enroll_member(full_name="Ruth Remind", email="ruth@x.com", dob="1989-09-09", api=api)
        initial = [
            r for r in list_member_reminders(member["id"], api=api)
            if r["reminder_kind"] == "RECORD_UPDATE"
        ]
        assert len(initial) == 1
        assert initial[0]["due_on"] == "2027-02-28", (
            f"2026-09-01 + 180 days, got {initial[0]['due_on']}"
        )
        set_clock("2027-01-01T00:00:00Z", api=api)
        add_record_item(
            member["id"],
            api=api,
            item_kind="MEDICATION", label="Metformin", detail="500mg",
            severity="LOW", provider_document_ref="doc-mf",
        )
        reminders = [
            r for r in list_member_reminders(member["id"], api=api)
            if r["reminder_kind"] == "RECORD_UPDATE"
        ]
        cancelled = [r for r in reminders if r["status"] == "CANCELLED"]
        pending = [r for r in reminders if r["status"] == "PENDING"]
        assert any(r["id"] == initial[0]["id"] for r in cancelled), (
            "the original RECORD_UPDATE reminder must be cancelled by the re-anchor"
        )
        assert len(pending) == 1, f"expected one re-anchored PENDING reminder, got {len(pending)}"
        assert pending[0]["due_on"] == "2027-06-30", (
            f"2027-01-01 + 180 days, got {pending[0]['due_on']}"
        )


class TestReminderDispatch:
    def test_dispatch_boundary_due_today_is_sent_inclusive(self, api, admin_headers):
        """PRD §3.7: "Dispatch is an ops-run batch performed by a `PlatformAdmin`:
        it sends every reminder in `PENDING` whose `due_on` is on or before the
        current logical date — the boundary is inclusive, so a reminder due today
        is sent today — stamping `sent_on` with the current logical date and moving
        the reminder to `SENT`, and returns a `sent_count` alongside the
        `sent_reminder_ids`."

        Design: Difficulty/boundary_precision_check/reminder_dispatch_due_on_equal_today_is_sent_inclusive
        """
        set_clock(api=api)
        member = enroll_member(full_name="Bea Boundary", email="bea@x.com", dob="1991-03-03", api=api)
        # Enrolled 2026-09-01, STANDARD: expires 2027-09-01, RENEWAL due 2027-08-02.
        set_clock("2027-08-01T00:00:00Z", api=api)
        early = validate_success(api.dispatch_reminders(admin_headers))
        early_sent = early["sent_count"]
        early_ids = early["sent_reminder_ids"]
        # only reminders due <= 2027-08-01 are sent; the RENEWAL due 2027-08-02 is not.
        reminders_after_early = list_member_reminders(member["id"], api=api)
        renewal = next(r for r in reminders_after_early if r["reminder_kind"] == "RENEWAL")
        assert renewal["status"] == "PENDING", "due 2027-08-02 > today: not yet due"
        assert renewal["id"] not in early_ids

        set_clock("2027-08-02T00:00:00Z", api=api)
        boundary = validate_success(api.dispatch_reminders(admin_headers))
        assert renewal["id"] in boundary["sent_reminder_ids"], (
            "due_on == today is INCLUSIVE: the RENEWAL reminder is sent"
        )
        reminders_final = list_member_reminders(member["id"], api=api)
        renewal_final = next(r for r in reminders_final if r["id"] == renewal["id"])
        assert renewal_final["status"] == "SENT"
        assert renewal_final["sent_on"] == "2027-08-02"
        _ = early_sent  # earlier dispatch count is implementation-agnostic; boundary is the assertion

    def test_dispatch_due_tomorrow_is_not_sent(self, api, admin_headers):
        """PRD §3.7: "Dispatch is an ops-run batch performed by a `PlatformAdmin`:
        it sends every reminder in `PENDING` whose `due_on` is on or before the
        current logical date — the boundary is inclusive, so a reminder due today
        is sent today — stamping `sent_on` with the current logical date and moving
        the reminder to `SENT`, and returns a `sent_count` alongside the
        `sent_reminder_ids`."

        Design: Difficulty/boundary_precision_check/reminder_dispatch_due_on_equal_today_is_sent_inclusive
        """
        set_clock(api=api)
        member = enroll_member(full_name="Bea Tomorrow", email="bea2@x.com", dob="1991-03-03", api=api)
        # Enrolled 2026-09-01 STANDARD: RENEWAL due 2027-08-02; today is 2027-08-01.
        set_clock("2027-08-01T00:00:00Z", api=api)
        result = validate_success(api.dispatch_reminders(admin_headers))
        reminders = list_member_reminders(member["id"], api=api)
        renewal = next(r for r in reminders if r["reminder_kind"] == "RENEWAL")
        assert renewal["id"] not in result["sent_reminder_ids"], (
            "a reminder due tomorrow is NOT sent (due_on <= today only)"
        )
        assert renewal["status"] == "PENDING"

    def test_dispatch_sends_only_due_reminders_and_reports_count(self, api, admin_headers):
        """PRD §3.7: "Dispatch is an ops-run batch performed by a `PlatformAdmin`:
        it sends every reminder in `PENDING` whose `due_on` is on or before the
        current logical date — the boundary is inclusive, so a reminder due today
        is sent today — stamping `sent_on` with the current logical date and moving
        the reminder to `SENT`, and returns a `sent_count` alongside the
        `sent_reminder_ids`."

        Design: Corner/endpoints/dispatch_returns_sent_count_and_ids
        """
        set_clock(api=api)
        member = enroll_member(full_name="Deb Dispatch", email="deb@x.com", dob="1987-07-07", api=api)
        # RECORD_UPDATE due 2027-02-28; RENEWAL due 2027-08-02.
        set_clock("2027-03-01T00:00:00Z", api=api)
        result = validate_success(api.dispatch_reminders(admin_headers))
        assert result["sent_count"] == 1, (
            f"only the RECORD_UPDATE reminder is due; got {result['sent_count']}"
        )
        assert len(result["sent_reminder_ids"]) == 1
        reminders = list_member_reminders(member["id"], api=api)
        sent_id = result["sent_reminder_ids"][0]
        sent = next(r for r in reminders if r["id"] == sent_id)
        assert sent["reminder_kind"] == "RECORD_UPDATE"
        assert sent["status"] == "SENT"
        assert sent["sent_on"] == "2027-03-01"
        renewal = next(r for r in reminders if r["reminder_kind"] == "RENEWAL")
        assert renewal["status"] == "PENDING", "RENEWAL due 2027-08-02 is not yet due"
