"""Retention eligibility, purge and the legal-hold freeze."""

from test_helpers import (
    ADMIN_HEADERS,
    api_client,
    get_recipient,
    make_account_headers,
    setup_completed_then_ages,
    setup_recipient_with_one_reminder,
    validate_error,
    validate_success,
)


class TestReminderCooldown:
    """§3.7: reminders are rate-limited per recipient by a closed-open window."""

    def test_reminder_inside_the_cooldown_is_refused(self, api):
        """PRD §3.7: "Reminders are rate-limited per recipient by a closed-open
        cooldown window running from that recipient's `last_reminder_at` up to
        but not including `last_reminder_at` plus twenty-four hours: a reminder
        requested while the logical clock falls inside that window is refused
        with `ERR_REMINDER_COOLDOWN` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/reminder_cooldown_rejects_within_24h_buffer
        """
        ctx = setup_recipient_with_one_reminder(first_reminder_at="2026-09-02T00:00:00Z")
        account, envelope = ctx["account"], ctx["envelope"]

        # 23 hours and 59 minutes after the previous reminder: still inside.
        api_client.set_current_utc({"to_iso8601": "2026-09-02T23:59:00Z"}, ADMIN_HEADERS)

        res = api_client.send_reminders(
            envelope["id"], make_account_headers(account["id"])
        )
        validate_error(res, "ERR_REMINDER_COOLDOWN")
        assert res.status_code == 409

    def test_refused_reminder_does_not_stamp_a_new_reminder(self, api):
        """PRD §3.7: "each such recipient's `reminder_count` is incremented and
        its `last_reminder_at` is stamped from the logical clock".
        PRD §3.7: "a reminder requested while the logical clock falls inside
        that window is refused with `ERR_REMINDER_COOLDOWN` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/reminder_cooldown_rejects_within_24h_buffer
        """
        ctx = setup_recipient_with_one_reminder(first_reminder_at="2026-09-02T00:00:00Z")
        account, envelope, recipient = ctx["account"], ctx["envelope"], ctx["recipient"]
        assert recipient["reminder_count"] == 1, (
            f"the setup sent exactly one reminder, got {recipient['reminder_count']}"
        )

        api_client.set_current_utc({"to_iso8601": "2026-09-02T23:59:00Z"}, ADMIN_HEADERS)
        api_client.send_reminders(envelope["id"], make_account_headers(account["id"]))

        after = get_recipient(recipient["id"], account)
        assert after["reminder_count"] == 1, (
            "the refused reminder must not increment reminder_count, "
            f"got {after['reminder_count']}"
        )
        assert after["last_reminder_at"] == recipient["last_reminder_at"], (
            "the refused reminder must not restamp last_reminder_at, "
            f"got {after['last_reminder_at']!r}"
        )


class TestPurgeAgainstLegalHold:
    """§3.9: the legal-hold freeze overrides the purge path."""

    def test_overlapping_hold_blocked_the_purge(self, api):
        """PRD §3.9: "The envelope must not be frozen by an overlapping legal
        hold, or the purge is refused with `ERR_LEGAL_HOLD_FROZEN` (HTTP 409)."
        PRD §2.11: "Purging is blocked exactly when the retention window and the
        hold window overlap."
        PRD §2.7: "the legal-hold freeze (priority 12, `ERR_LEGAL_HOLD_FROZEN`,
        HTTP 409)".
        PRD §3.9: "a `GLOBAL` policy applies its own `retention_years` uniformly to
        every envelope it governs".

        Design: Difficulty/resource_temporal_overlap/purge_blocked_when_legal_hold_window_overlaps_retention_window
        """
        ctx = setup_completed_then_ages(
            anchor="2026-09-01T00:00:00Z",
            scope="GLOBAL",
            retention_years=3,
            purge_grace_days=0,
            subject="Overlap envelope",
            age_to="2027-01-01T00:00:00Z",
        )
        account, envelope = ctx["account"], ctx["envelope"]
        assert envelope["status"] == "COMPLETED"

        # The retention window runs [2026-09-01, 2029-09-01); the hold covers
        # [2027-01-01, 2029-12-31), so the two windows overlap.
        held = validate_success(
            api_client.set_legal_hold(
                envelope["id"],
                {"legal_hold": True, "hold_until": "2029-12-31T00:00:00Z"},
                ADMIN_HEADERS,
            ),
            200,
        )
        version_under_hold = held["version"]

        # Inside the overlap: the retention instant is still in the future and
        # the hold has not yet lapsed.
        api_client.set_current_utc({"to_iso8601": "2029-06-01T00:00:00Z"}, ADMIN_HEADERS)

        res = api_client.purge_envelope(
            envelope["id"], {"expected_envelope_version": version_under_hold}, ADMIN_HEADERS
        )
        validate_error(res, "ERR_LEGAL_HOLD_FROZEN")
        assert res.status_code == 409

    def test_blocked_purge_leaves_the_content_intact(self, api):
        """PRD §3.9: "While a hold is active in the interval terms described in
        §2.11, sending, voiding, sealing, expiring and purging the envelope are
        all frozen".
        PRD §3.9: "On success the envelope's `purged_at` is stamped from the
        logical clock, the certificate document is deleted when the governing
        policy's `purge_mode` is `DELETE_ALL`".
        PRD §2.11: "the hold window is the closed-open interval from
        `legal_hold_started_at` up to but not including `legal_hold_until`".

        Design: Difficulty/resource_temporal_overlap/purge_blocked_when_legal_hold_window_overlaps_retention_window
        """
        ctx = setup_completed_then_ages(
            anchor="2026-09-01T00:00:00Z",
            scope="GLOBAL",
            retention_years=3,
            purge_grace_days=0,
            subject="Overlap envelope two",
            age_to="2027-01-01T00:00:00Z",
        )
        account, envelope = ctx["account"], ctx["envelope"]
        account_headers = make_account_headers(account["id"])

        held = validate_success(
            api_client.set_legal_hold(
                envelope["id"],
                {"legal_hold": True, "hold_until": "2029-12-31T00:00:00Z"},
                ADMIN_HEADERS,
            ),
            200,
        )
        api_client.set_current_utc({"to_iso8601": "2029-06-01T00:00:00Z"}, ADMIN_HEADERS)

        api_client.purge_envelope(
            envelope["id"], {"expected_envelope_version": held["version"]}, ADMIN_HEADERS
        )

        after = validate_success(api_client.get_envelope(envelope["id"], account_headers), 200)
        assert after["purged_at"] is None, (
            f"a blocked purge must not stamp purged_at, got {after['purged_at']!r}"
        )
        documents = validate_success(
            api_client.list_documents(envelope["id"], account_headers), 200
        )
        assert any(d.get("is_certificate") for d in documents), (
            "the frozen envelope's certificate document must survive the blocked purge"
        )