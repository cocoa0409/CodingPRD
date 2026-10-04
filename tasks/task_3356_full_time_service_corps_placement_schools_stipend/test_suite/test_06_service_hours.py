"""Service hours: entry shape, logging gates, the verification window, the
daily cap, the fundraising cap's pinned evaluation order, the verified-only
ledger, and verify/void compensation."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    make_corps_member_headers,
)


def _active_member(api):
    site = fixtures.create_active_site(api)
    return fixtures.create_active_member(api, site["id"])


class TestEntryShapeAndCreation:
    def test_hour_entry_has_no_version_field(self, api):
        """PRD §2.5: "One resource deviates from this convention: a
        ServiceHourEntry carries only `id` and `created_at`. Both `updated_at`
        and `version` are absent from hour entries."

        Design: Corner/entities/hour_entry_has_no_version_field
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        entry = validate_success(
            api.create_hour_entry(
                factories.hour_entry_payload(member["id"], "2026-09-01", 2.5),
                make_corps_member_headers(member["id"]),
            ),
            201,
        )
        assert entry["id"] and entry["created_at"]
        assert "version" not in entry
        assert "updated_at" not in entry
        assert entry["status"] == "PENDING"

    def test_hour_entry_future_date_rejected(self, api):
        """PRD §3.6: "the date must fall on or after the site's
        `service_year_start` and on or before the logical clock date — a date
        outside that window is rejected with `ERR_SERVICE_DATE_INVALID`."

        Design: Corner/validations/hour_entry_future_date_rejected
        """
        fixtures.set_clock(api)  # 2026-09-01
        member = _active_member(api)
        resp = api.create_hour_entry(
            factories.hour_entry_payload(member["id"], "2026-09-02", 4.0),
            make_corps_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_INVALID.value)

    def test_invalid_enum_value_rejected(self, api):
        """PRD §2.8: "the request body is checked for shape: required fields
        present, enums in range, dates well-formed, hours a positive multiple
        of 0.25 not exceeding 12, monetary values non-negative integer cents,
        and any `period_end` on or after its `period_start` — violations
        surface as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/invalid_enum_value_rejected
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        resp = api.create_hour_entry(
            factories.hour_entry_payload(member["id"], "2026-09-01", 4.0, category="FUN_RUN"),
            make_corps_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_hours_not_quantum_rejected(self, api):
        """PRD §3.6: "The hours must be positive, no more than 12, and an exact
        multiple of 0.25; the date must fall on or after the site's
        `service_year_start` and on or before the logical clock date — a date
        outside that window is rejected with `ERR_SERVICE_DATE_INVALID`."

        Design: Corner/validations/hours_not_quantum_rejected"""
        fixtures.set_clock(api)
        member = _active_member(api)
        resp = api.create_hour_entry(
            factories.hour_entry_payload(member["id"], "2026-09-01", 1.3),
            make_corps_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_member_create_hours_for_other_member_rejected(self, api):
        """PRD §3.6: "A `CorpsMember` creates an hour entry with
        `corps_member_id` — which must equal the caller's `X-User-ID`, else
        `ERR_NOT_ENTITY_OWNER` — a `service_date`, the `hours` served, a
        `category` of `DIRECT_SERVICE`, `TRAINING`, or `FUNDRAISING`, and an
        optional free-text `description` that defaults to empty."

        Design: Corner/validations/member_create_hours_for_other_member_rejected"""
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member1 = fixtures.create_active_member(api, site["id"])
        member2 = fixtures.add_active_member(
            api, site["id"], "app-riley", "Riley Brooks",
            date_of_birth="2004-02-11", education_level="SOME_COLLEGE",
        )

        resp = api.create_hour_entry(
            factories.hour_entry_payload(member2["id"], "2026-09-01", 4.0),
            make_corps_member_headers(member1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ENTITY_OWNER.value)

        other = fixtures.get_member(api, member2["id"])
        assert other["verified_hours_total"] == 0.0
        entries = get_success_data(
            api.list_member_hour_entries(member2["id"], make_corps_member_headers(member2["id"]))
        )
        assert entries == []

    def test_hour_create_member_suspended_rejected(self, api):
        """PRD §3.6: "Logging requires the member to be actively serving: the
        member's `service_status` must be `ACTIVE`, else the creation is
        rejected with `ERR_MEMBER_NOT_ACTIVE`."

        Design: Corner/validations/hour_create_member_suspended_rejected
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        fixtures.suspend_member_service(api, member["id"])
        resp = api.create_hour_entry(
            factories.hour_entry_payload(member["id"], "2026-09-01", 4.0),
            make_corps_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)


class TestReviewMachine:
    def test_hour_entry_reject_then_verify_rejected(self, api):
        """PRD §3.6: "Rejection — `PENDING` to `REJECTED` — requires a
        `reason` (else `ERR_INVALID_REQUEST`), which is recorded as
        `review_reason` alongside `reviewed_by`."
        PRD §3.6: "`REJECTED` and `VOIDED` are terminal."

        Design: Corner/state_machines/hour_entry_reject_then_verify_rejected
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        entry = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 3.0, "TRAINING")

        rejected = fixtures.review_entry(api, entry["id"], "REJECT", "unverifiable activity")
        assert rejected["status"] == "REJECTED"
        assert rejected["review_reason"] == "unverifiable activity"

        blocked = api.review_hour_entry(entry["id"], {"decision": "VERIFY"}, PROGRAM_MANAGER_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

        member_after = fixtures.get_member(api, member["id"])
        assert member_after["verified_hours_total"] == 0.0

    def test_verification_window_30_ok_31_expired(self, api):
        """PRD §3.6: "The verification window: the gap between the clock date
        and the entry's `service_date` must not exceed 30 days, else
        `ERR_VERIFICATION_WINDOW_EXPIRED`."

        Design: Corner/validations/verification_window_30_ok_31_expired
        """
        fixtures.set_clock(api)  # 2026-09-01
        member = _active_member(api)
        w1 = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 4.0)
        fixtures.review_entry(api, w1["id"], "VERIFY")

        # Exactly 30 days after the service date: inside the window.
        fixtures.set_clock(api, "2026-10-01T00:00:00Z")
        w2 = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 4.0)
        w3 = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 4.0)
        verified = fixtures.review_entry(api, w2["id"], "VERIFY")
        assert verified["status"] == "VERIFIED"

        # 31 days: closed. The daily cap is not breached (4+4+4 == 12.0).
        fixtures.set_clock(api, "2026-10-02T00:00:00Z")
        blocked = api.review_hour_entry(w3["id"], {"decision": "VERIFY"}, PROGRAM_MANAGER_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_VERIFICATION_WINDOW_EXPIRED.value)

    def test_daily_cap_12_ok_then_quarter_rejected(self, api):
        """PRD §3.6: "The daily cap: summing the member's entries on the same
        `service_date` across both `PENDING` and `VERIFIED`, the candidate
        included, must not exceed 12.0 hours, else
        `ERR_DAILY_HOUR_CAP_EXCEEDED`."

        Design: Corner/validations/daily_cap_12_ok_then_quarter_rejected
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        fixtures.set_clock(api, "2026-09-02T00:00:00Z")
        full = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 12.0)
        verified = fixtures.review_entry(api, full["id"], "VERIFY")
        assert verified["status"] == "VERIFIED"

        quarter = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 0.25)
        blocked = api.review_hour_entry(quarter["id"], {"decision": "VERIFY"}, PROGRAM_MANAGER_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_DAILY_HOUR_CAP_EXCEEDED.value)


class TestVerifiedLedger:
    def test_hour_totals_exclude_nonverified(self, api):
        """PRD §3.6: "The member's hour ledger is a pure aggregation over
        entry states: `verified_hours_total` sums `hours` across the member's
        `VERIFIED` entries, and `verified_fundraising_hours` sums only those
        `VERIFIED` entries in the `FUNDRAISING` category, with `PENDING`,
        `REJECTED`, and `VOIDED` entries excluded from both."

        Design: Corner/calculations/hour_totals_exclude_nonverified"""
        fixtures.set_clock(api)
        member = _active_member(api)
        fixtures.set_clock(api, "2026-09-09T00:00:00Z")

        # Two verified DIRECT_SERVICE entries build an 18.0-hour base (large
        # enough that the 10% fundraising cap admits the 2.0 entry below).
        e1 = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 12.0)
        fixtures.review_entry(api, e1["id"], "VERIFY")
        e2 = fixtures.log_pending_entry(api, member["id"], "2026-09-02", 6.0)
        fixtures.review_entry(api, e2["id"], "VERIFY")

        # PENDING: never reviewed.
        fixtures.log_pending_entry(api, member["id"], "2026-09-03", 4.0, "TRAINING")

        # REJECTED.
        e4 = fixtures.log_pending_entry(api, member["id"], "2026-09-04", 3.0)
        fixtures.review_entry(api, e4["id"], "REJECT", "unverifiable")

        # VERIFIED then VOIDED: at 18.0 verified the cap is floor(20.0 x 0.10
        # x 4) / 4 = 2.0, so the 2.0 FUNDRAISING entry verifies exactly at the
        # cap; the void then removes it again.
        e5 = fixtures.log_pending_entry(api, member["id"], "2026-09-05", 2.0, "FUNDRAISING")
        fixtures.review_entry(api, e5["id"], "VERIFY")
        fixtures.review_entry(api, e5["id"], "VOID", "logged to wrong member")

        after = fixtures.get_member(api, member["id"])
        assert after["verified_hours_total"] == 18.0  # 12.0 + 6.0 only
        assert after["verified_fundraising_hours"] == 0.0

    def test_fundraising_cap_boundary_accept(self, api):
        """PRD §3.6: "First, form the member's post-verification total: the
        current `verified_hours_total` plus the candidate entry's hours.
        Second, compute the cap as ten percent of that post-verification
        total, floored down to the nearest quarter hour. Third, accept the
        entry only if `verified_fundraising_hours` plus the candidate's hours
        stays at or under that cap."

        Design: Difficulty/combinatorial_formula/fundraising_cap_circular_order
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        fixtures.set_clock(api, "2026-09-09T00:00:00Z")
        fixtures.log_verified_hours(
            api,
            member["id"],
            [("2026-09-01", 12.0, "DIRECT_SERVICE"), ("2026-09-02", 5.0, "DIRECT_SERVICE"),
             ("2026-09-02", 1.0, "FUNDRAISING")],
            "2026-09-09T00:00:00Z",
        )

        # T_new = 18.75, cap = floor(18.75 x 0.10 x 4) / 4 = 1.75; the new
        # fundraising total 1.75 lands exactly on the cap: boundary accept.
        candidate = fixtures.log_pending_entry(api, member["id"], "2026-09-02", 0.75, "FUNDRAISING")
        verified = fixtures.review_entry(api, candidate["id"], "VERIFY")
        assert verified["status"] == "VERIFIED"

        after = fixtures.get_member(api, member["id"])
        assert after["verified_hours_total"] == 18.75
        assert after["verified_fundraising_hours"] == 1.75

    def test_fundraising_cap_boundary_reject(self, api):
        """PRD §3.6: "Computing the cap against the pre-verification total
        instead would yield a strictly smaller cap and wrongly reject entries
        this order accepts."
        PRD §3.6: "And for a `FUNDRAISING` entry, the fundraising cap
        described below, else `ERR_FUNDRAISING_CAP_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/fundraising_cap_circular_order
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        fixtures.set_clock(api, "2026-09-09T00:00:00Z")
        fixtures.log_verified_hours(
            api,
            member["id"],
            [("2026-09-01", 12.0, "DIRECT_SERVICE"), ("2026-09-02", 5.0, "DIRECT_SERVICE"),
             ("2026-09-02", 1.0, "FUNDRAISING"), ("2026-09-02", 0.75, "FUNDRAISING")],
            "2026-09-09T00:00:00Z",
        )

        # T_new = 19.0, cap = floor(19.0 x 0.10 x 4) / 4 = 1.75; the new
        # fundraising total would be 2.0 > 1.75: rejected.
        candidate = fixtures.log_pending_entry(api, member["id"], "2026-09-02", 0.25, "FUNDRAISING")
        blocked = api.review_hour_entry(candidate["id"], {"decision": "VERIFY"}, PROGRAM_MANAGER_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_FUNDRAISING_CAP_EXCEEDED.value)

        after = fixtures.get_member(api, member["id"])
        assert after["verified_hours_total"] == 18.75
        assert after["verified_fundraising_hours"] == 1.75

    def test_verify_void_compensates_exactly(self, api):
        """PRD §3.6: "The ledger is self-reconciling — verifying an entry and
        later voiding it returns both totals to exactly their prior values."

        Design: Difficulty/compensating_invariant/hour_verify_void_reverify_ledger_conservation
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        fixtures.set_clock(api, "2026-09-09T00:00:00Z")
        entry = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 8.0)

        verified = fixtures.review_entry(api, entry["id"], "VERIFY")
        assert verified["status"] == "VERIFIED"
        assert fixtures.get_member(api, member["id"])["verified_hours_total"] == 8.0

        voided = fixtures.review_entry(api, entry["id"], "VOID", "duplicate submission")
        assert voided["status"] == "VOIDED"
        assert voided["review_reason"] == "duplicate submission"
        after = fixtures.get_member(api, member["id"])
        assert after["verified_hours_total"] == 0.0

    def test_verify_void_reverify_restores_total(self, api):
        """PRD §3.6: "Voiding — `VERIFIED` to `VOIDED` — is the compensating
        action for an entry verified in error: it likewise requires a
        `reason`, records `review_reason`, and recomputes the member's totals
        downward."

        Design: Difficulty/compensating_invariant/hour_verify_void_reverify_ledger_conservation
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        fixtures.set_clock(api, "2026-09-09T00:00:00Z")
        entry = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 8.0)
        fixtures.review_entry(api, entry["id"], "VERIFY")
        fixtures.review_entry(api, entry["id"], "VOID", "duplicate submission")
        assert fixtures.get_member(api, member["id"])["verified_hours_total"] == 0.0

        # A replacement entry restores the total; the voided one stays out.
        replacement = fixtures.log_pending_entry(api, member["id"], "2026-09-02", 8.0)
        verified = fixtures.review_entry(api, replacement["id"], "VERIFY")
        assert verified["status"] == "VERIFIED"
        after = fixtures.get_member(api, member["id"])
        assert after["verified_hours_total"] == 8.0


class TestVerifyOrdering:
    def test_temporal_beats_constraint_on_hour_verify(self, api):
        """PRD §3.6: "Verification — `PENDING` to `VERIFIED` — is gated by
        three checks evaluated in this order. The verification window: the gap
        between the clock date and the entry's `service_date` must not exceed
        30 days, else `ERR_VERIFICATION_WINDOW_EXPIRED`. The daily cap:
        summing the member's entries on the same `service_date` across both
        `PENDING` and `VERIFIED`, the candidate included, must not exceed 12.0
        hours, else `ERR_DAILY_HOUR_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_hour_verify"""
        fixtures.set_clock(api)  # 2026-09-01
        member = _active_member(api)
        full = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 12.0)
        fixtures.review_entry(api, full["id"], "VERIFY")
        candidate = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 0.25)

        # 31 days later the window is closed AND 12.0 + 0.25 > 12.0 breaches
        # the daily cap; the temporal error is evaluated first and wins.
        fixtures.set_clock(api, "2026-10-02T00:00:00Z")
        blocked = api.review_hour_entry(candidate["id"], {"decision": "VERIFY"}, PROGRAM_MANAGER_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_VERIFICATION_WINDOW_EXPIRED.value)

        entries = get_success_data(
            api.list_member_hour_entries(member["id"], make_corps_member_headers(member["id"]))
        )
        states = {e["id"]: e["status"] for e in entries}
        assert states[candidate["id"]] == "PENDING"

    def test_constraint_fires_when_temporal_passes(self, api):
        """PRD §3.6: "The daily cap: summing the member's entries on the same
        `service_date` across both `PENDING` and `VERIFIED`, the candidate
        included, must not exceed 12.0 hours, else
        `ERR_DAILY_HOUR_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_hour_verify
        """
        fixtures.set_clock(api)
        member = _active_member(api)
        # One day after the service date: the window passes, so the
        # constraint layer is reached and reports the cap breach.
        fixtures.set_clock(api, "2026-09-02T00:00:00Z")
        full = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 12.0)
        fixtures.review_entry(api, full["id"], "VERIFY")
        candidate = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 0.25)

        blocked = api.review_hour_entry(candidate["id"], {"decision": "VERIFY"}, PROGRAM_MANAGER_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_DAILY_HOUR_CAP_EXCEEDED.value)
        assert fixtures.get_member(api, member["id"])["verified_hours_total"] == 12.0
