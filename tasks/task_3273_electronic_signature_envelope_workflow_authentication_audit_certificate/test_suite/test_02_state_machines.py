"""State machine transitions: templates, bulk send and the envelope fork-join."""

from test_helpers import (
    ADMIN_HEADERS,
    api_client,
    assert_instant_equals,
    get_recipient,
    make_account_headers,
    make_recipient_headers,
    parse_instant,
    setup_bulk_send_batch,
    setup_draft_template,
    setup_expiry_pending_envelope,
    setup_sent_single_signer,
    setup_signing_recipient,
    sign_recipient,
    validate_error,
    validate_success,
)


def test_template_publish_transitions_draft_to_published(api):
    """PRD §3.8: "A draft template is made usable by publishing it, which
    requires both a `page_count` and a `role_slot_count` of at least one and
    moves it from `DRAFT` to `PUBLISHED`".
    PRD §3.8: "Both transitions advance the template's version."

    Design: Corner/state_machines/template_publish_transitions_draft_to_published
    """
    ctx = setup_draft_template(name="NDA Template", page_count=4, role_slot_count=2)
    account, template = ctx["account"], ctx["template"]
    assert template["status"] == "DRAFT"
    version_before = template["version"]

    res = api_client.publish_template(template["id"], make_account_headers(account["id"]))
    published = validate_success(res, 200)

    assert published["status"] == "PUBLISHED", (
        f"publishing a draft template must yield PUBLISHED, got {published['status']}"
    )
    assert published["version"] == version_before + 1, (
        f"publish must advance the template version from {version_before}, "
        f"got {published['version']}"
    )


def test_template_archive_from_draft_is_rejected(api):
    """PRD §3.8: "a published template may later be archived, moving it to the
    `ARCHIVED` terminal status."

    A template that has never been published is not published, so it admits no
    archive transition; the PRD's error catalogue maps an envelope or template
    that is not in a status the transition accepts to `ERR_INVALID_ENVELOPE_STATE`.

    Design: Corner/state_machines/template_archive_from_draft_rejected
    """
    ctx = setup_draft_template(name="Draft Template", page_count=2, role_slot_count=1)
    account, template = ctx["account"], ctx["template"]

    res = api_client.archive_template(template["id"], make_account_headers(account["id"]))
    assert res.status_code >= 400, (
        f"archiving a DRAFT template must be refused, got {res.status_code}"
    )

    after = validate_success(
        api_client.get_template(template["id"], make_account_headers(account["id"])), 200
    )
    assert after["status"] == "DRAFT", (
        f"a rejected archive must leave the template in DRAFT, got {after['status']}"
    )


def test_bulk_send_all_rows_invalid_sets_failed(api):
    """PRD §3.8: "a row that lacks a resolvable `email` or that does not carry
    the role slots the template declares is rejected with `ERR_BULK_ROW_INVALID`
    (HTTP 422)".
    PRD §3.8: "When every row is rejected the batch closes as `FAILED` with
    `succeeded_count` zero and `failed_count` equal to `total_rows`."

    Design: Corner/state_machines/bulk_send_all_rows_invalid_sets_failed
    """
    ctx = setup_bulk_send_batch(total_rows=2, template_name="Bulk Template")
    account, batch = ctx["account"], ctx["batch"]

    res = api_client.process_bulk_send(
        batch["id"],
        {"rows": [{"email": "not-an-email"}, {"email": ""}]},
        make_account_headers(account["id"]),
    )
    processed = validate_success(res, 200)

    assert processed["status"] == "FAILED", (
        f"a batch whose every row is rejected must close FAILED, got {processed['status']}"
    )
    assert processed["succeeded_count"] == 0, (
        f"no row produced an envelope, got succeeded_count {processed['succeeded_count']}"
    )
    assert processed["failed_count"] == 2, (
        f"both rows were rejected, got failed_count {processed['failed_count']}"
    )


class TestEnvelopeForkJoin:
    """From DELIVERED the envelope forks to four terminals; the expire branch
    carries its own divergent side-effect set."""

    def test_in_flight_envelope_expires_once_clock_passes_deadline(self, api):
        """PRD §3.7: "Expiry ends an in-flight envelope that has run out of
        time. The envelope must be in `SENT` or `DELIVERED`, must not be under a
        legal hold, and the logical clock must have reached or passed the
        envelope's `expires_at`; the request must carry the observed
        `expected_envelope_version`."
        PRD §2.6: "When an envelope expires, the same in-flight recipients move
        to `EXPIRED` and open sessions move to `EXPIRED`."

        Design: Difficulty/non_linear_state_machine/envelope_fork_join_terminal_convergence
        """
        ctx = setup_expiry_pending_envelope()
        account, envelope = ctx["account"], ctx["envelope"]
        account_headers = make_account_headers(account["id"])

        delivered = validate_success(
            api_client.feed_envelope(
                envelope["id"], {"feed_event": "DELIVERED"}, account_headers
            ),
            200,
        )
        assert delivered["status"] == "DELIVERED"
        version_at_delivery = delivered["version"]

        # 120 calendar days after 2026-09-01 is 2026-12-30, pinned to 23:59:59Z.
        api_client.set_current_utc({"to_iso8601": "2026-12-31T00:00:00Z"}, ADMIN_HEADERS)

        res = api_client.expire_envelope(
            envelope["id"],
            {"expected_envelope_version": version_at_delivery},
            account_headers,
        )
        expired = validate_success(res, 200)

        assert expired["status"] == "EXPIRED", (
            f"the DELIVERED -> EXPIRED branch must be taken, got {expired['status']}"
        )
        recipient = validate_success(
            api_client.get_recipient(ctx["recipient"]["id"], account_headers), 200
        )
        assert recipient["status"] == "EXPIRED", (
            "the expire branch moves in-flight recipients to EXPIRED, "
            f"got {recipient['status']}"
        )
        assert expired["status"] != "COMPLETED"
        assert expired["version"] == version_at_delivery + 1, (
            f"the transition must advance the envelope version once from "
            f"{version_at_delivery}, got {expired['version']}"
        )

    def test_expire_branch_does_not_seal_the_envelope(self, api):
        """PRD §3.6: "A successful seal is the system's richest single side
        effect. The envelope's status becomes `COMPLETED` and `is_sealed`
        becomes true."
        PRD §3.6: "A successful seal is the system's richest single side effect. The
        envelope's status becomes `COMPLETED` and `is_sealed` becomes true." — a
        terminal reached by any other branch is not a seal.

        Design: Difficulty/non_linear_state_machine/envelope_fork_join_terminal_convergence
        """
        ctx = setup_expiry_pending_envelope(subject="Fork join envelope")
        account, envelope = ctx["account"], ctx["envelope"]
        account_headers = make_account_headers(account["id"])

        delivered = validate_success(
            api_client.feed_envelope(
                envelope["id"], {"feed_event": "DELIVERED"}, account_headers
            ),
            200,
        )
        api_client.set_current_utc({"to_iso8601": "2026-12-31T00:00:00Z"}, ADMIN_HEADERS)

        expired = validate_success(
            api_client.expire_envelope(
                envelope["id"],
                {"expected_envelope_version": delivered["version"]},
                account_headers,
            ),
            200,
        )
        assert expired["status"] == "EXPIRED"
        assert expired["is_sealed"] is False, (
            "the expire terminal is not a seal; is_sealed must remain false"
        )
        assert not expired.get("seal_hash"), (
            f"an expired envelope carries no seal_hash, got {expired.get('seal_hash')!r}"
        )


class TestRecipientParallelDimensions:
    """status and auth_status are independent dimensions on the same row."""

    def test_signing_leaves_terminal_status_beside_non_terminal_auth(self, api):
        """PRD §2.6: "Two independent dimensions live on a `Recipient`. Its
        `status` tracks the workflow position — `WAITING`, `SENT`, `DELIVERED`,
        `SIGNING`, and the terminal `SIGNED`, `APPROVED`, `DECLINED`, `VOIDED`,
        `EXPIRED` — while its `auth_status` tracks the parallel authentication
        dimension, `PENDING`, `AUTHENTICATED` or `FAILED`."
        PRD §3.5: "A `SIGNER` moves to `SIGNED`".
        PRD §3.4: "On success the recipient's `auth_status` becomes
        `AUTHENTICATED`".

        Design: Difficulty/non_linear_state_machine/recipient_parallel_status_and_auth_dimensions
        """
        ctx = setup_signing_recipient(auth_level="KBA", authenticate=True)
        recipient = ctx["recipient"]
        assert recipient["auth_status"] == "AUTHENTICATED"
        assert recipient["status"] in ("SENT", "DELIVERED", "SIGNING")

        signed = sign_recipient(recipient)

        assert signed["status"] == "SIGNED", (
            f"after signing the status dimension is terminal, got {signed['status']}"
        )
        assert signed["auth_status"] == "AUTHENTICATED", (
            "authentication is a parallel dimension and is not rewritten by the "
            f"signature, got {signed['auth_status']}"
        )

    def test_the_two_dimensions_hold_disjoint_value_sets(self, api):
        """PRD §2.6: "Authentication gates the workflow transitions; it does not
        replace them, and a change in one dimension never silently rewrites the
        other."
        PRD §3.4: "On success the recipient's `auth_status` becomes
        `AUTHENTICATED`; on failure it becomes `FAILED`."

        Design: Difficulty/non_linear_state_machine/recipient_parallel_status_and_auth_dimensions
        """
        ctx = setup_signing_recipient(auth_level="KBA", authenticate=True)
        signed = sign_recipient(ctx["recipient"])

        workflow_values = {
            "WAITING", "SENT", "DELIVERED", "SIGNING",
            "SIGNED", "APPROVED", "DECLINED", "VOIDED", "EXPIRED",
        }
        auth_values = {"PENDING", "AUTHENTICATED", "FAILED"}

        assert signed["status"] in workflow_values
        assert signed["auth_status"] in auth_values
        assert signed["auth_status"] != "SIGNED", (
            "the two dimensions are not the same field"
        )
        assert signed["status"] != "AUTHENTICATED", (
            "the two dimensions are not the same field"
        )

class TestAdditionalRecipientLockdown:
    """A recipient already in a terminal status admits no further transition."""

    def test_signing_twice_is_refused_as_recipient_terminal(self, api):
        """PRD §3.5: "a required field or a signature field still left null is
        refused with `ERR_FIELD_REQUIRED` (HTTP 422); a recipient already in a
        terminal recipient status is refused with `ERR_RECIPIENT_TERMINAL`
        (HTTP 409)".
        PRD §2.6: "Its `status` tracks the workflow position — `WAITING`, `SENT`,
        `DELIVERED`, `SIGNING`, and the terminal `SIGNED`, `APPROVED`,
        `DECLINED`, `VOIDED`, `EXPIRED`".

        Design: Corner/state_machines/sign_from_already_signed_returns_recipient_terminal
        """
        ctx = setup_signing_recipient(subject="Idempotency envelope")
        account, recipient = ctx["account"], ctx["recipient"]
        first = sign_recipient(recipient)
        signed_at_first = first["signed_at"]
        assert first["status"] == "SIGNED"

        res = api_client.sign_recipient(
            recipient["id"], make_recipient_headers(recipient["id"])
        )
        validate_error(res, "ERR_RECIPIENT_TERMINAL")
        assert res.status_code == 409

        after = get_recipient(recipient["id"], account)
        assert after["signed_at"] == signed_at_first, (
            "the rejected second call must not restamp signed_at"
        )


class TestDeadlineArithmetic:
    """The send stamps two deadlines that advance by different day types."""

    def test_send_stamps_a_calendar_deadline_distinct_from_the_business_window(self, api):
        """PRD §3.2: "A successful send stamps `sent_at` with the logical clock
        instant, then computes `expires_at` as `sent_at` advanced by
        `expires_after_days` calendar days and pinned to `23:59:59Z`, and
        `sender_visible_expires_at` as `sent_at` advanced by
        `sender_visible_window_days` business days — skipping Saturday and
        Sunday — and likewise pinned to `23:59:59Z`."

        Design: Difficulty/dual_variant_calc/envelope_expiry_calendar_vs_business_days
        """
        ctx = setup_sent_single_signer(
            subject="Expiry window envelope",
            expires_after_days=30,
            sender_visible_window_days=30,
            pin_epoch=True,
        )
        envelope = ctx["envelope"]

        assert_instant_equals(envelope["sent_at"], "2026-09-01T00:00:00Z", "sent_at")
        # 30 calendar days after Tuesday 2026-09-01 with the pin.
        assert_instant_equals(envelope["expires_at"], "2026-10-01T23:59:59Z", "expires_at")
        # 30 business days, skipping the twelve weekend days, lands later.
        assert_instant_equals(
            envelope["sender_visible_expires_at"],
            "2026-10-13T23:59:59Z",
            "sender_visible_expires_at",
        )

    def test_the_two_deadlines_are_different_instants(self, api):
        """PRD §3.2: "A successful send stamps `sent_at` with the logical clock instant,
        then computes `expires_at` as `sent_at` advanced by `expires_after_days`
        calendar days and pinned to `23:59:59Z`, and
        `sender_visible_expires_at` as `sent_at` advanced by
        `sender_visible_window_days` business days — skipping Saturday and
        Sunday — and likewise pinned to `23:59:59Z`."

        Design: Difficulty/dual_variant_calc/envelope_expiry_calendar_vs_business_days
        """
        ctx = setup_sent_single_signer(
            subject="Expiry window envelope two",
            expires_after_days=30,
            sender_visible_window_days=30,
            pin_epoch=True,
        )
        envelope = ctx["envelope"]

        calendar_deadline = parse_instant(envelope["expires_at"])
        business_deadline = parse_instant(envelope["sender_visible_expires_at"])

        assert calendar_deadline != business_deadline, (
            "one deadline advances calendar days and the other business days, so "
            "they cannot coincide at 30 days"
        )
        assert business_deadline > calendar_deadline, (
            "skipping weekends pushes the business-day window past the calendar one"
        )
        assert (business_deadline - calendar_deadline).days == 12, (
            "thirty business days from 2026-09-01 cross twelve weekend days, so "
            f"the deadlines are twelve days apart, got {(business_deadline - calendar_deadline).days}"
        )
