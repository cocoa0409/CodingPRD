"""The audit certificate, the tamper-evident chain and envelope listing."""
import hashlib


from test_helpers import (
    HASH_HEX_LENGTH,
    TEST_USERS,
    api_client,
    create_and_complete_envelope,
    make_account_headers,
    make_recipient_headers,
    setup_bulk_send_batch,
    setup_sent_single_signer,
    setup_single_signer_envelope,
    validate_error,
    validate_paginated,
    validate_success,
)


def _event_hash(event: dict) -> str:
    """Recompute an event's hash exactly as §2.11 defines it."""
    prev = event.get("prev_hash") or ""
    material = "|".join(
        [str(event["sequence_number"]), event["event_type"], event["event_at"], prev]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class TestAuditChain:
    """§2.11: the per-envelope event chain."""

    def test_certificate_hash_is_stable_across_reads(self, api):
        """PRD §2.11: "A certificate hash is the SHA-256 digest over the ordered
        `event_hash` chain joined by the pipe character. Hashes are hexadecimal
        digest strings of sixty-four characters."
        PRD §3.6: "Reading the audit certificate returns the `certificate_hash`,
        the `seal_hash` and an `event_count`, recomputing the chain on every read."

        Design: Corner/calculations/audit_chain_hash_is_deterministic_over_event_order
        """
        ctx = create_and_complete_envelope(subject="Chain envelope")
        account, envelope = ctx["account"], ctx["envelope"]
        account_headers = make_account_headers(account["id"])
        assert envelope["status"] == "COMPLETED"

        first = validate_success(
            api_client.get_audit_certificate(envelope["id"], account_headers), 200
        )
        second = validate_success(
            api_client.get_audit_certificate(envelope["id"], account_headers), 200
        )

        assert isinstance(first["certificate_hash"], str), "the certificate hash must be a string"
        assert len(first["certificate_hash"]) == HASH_HEX_LENGTH, (
            f"the certificate hash is a {HASH_HEX_LENGTH}-character digest, "
            f"got {len(first['certificate_hash'])}"
        )
        assert first["certificate_hash"] == second["certificate_hash"], (
            "recomputing the chain on every read must yield the same certificate_hash"
        )

    def test_certificate_hash_reproduces_the_event_chain(self, api):
        """PRD §2.11: "The audit chain is a separate structure maintained per envelope:
        each `AuditEvent` carries a `prev_hash` equal to the `event_hash` of the
        event immediately before it in the chain".
        PRD §2.11: "A certificate hash is the SHA-256 digest over the ordered
        `event_hash` chain joined by the pipe character."

        Design: Corner/calculations/audit_chain_hash_is_deterministic_over_event_order
        """
        ctx = create_and_complete_envelope(subject="Chain envelope two")
        account, envelope = ctx["account"], ctx["envelope"]
        account_headers = make_account_headers(account["id"])

        events = validate_success(
            api_client.list_audit_events(
                account_headers, {"envelope_id": envelope["id"], "limit": 100}
            ),
            200,
        )
        ordered = sorted(events, key=lambda e: e["sequence_number"])
        assert len(ordered) >= 2, "a sealed envelope carries several audit events"

        # The chain is contiguous from 1 and each link points at its predecessor.
        assert [e["sequence_number"] for e in ordered] == list(range(1, len(ordered) + 1)), (
            "sequence_number is contiguous starting at 1"
        )
        assert ordered[0]["prev_hash"] is None, "the first event's prev_hash is null"
        for previous, current in zip(ordered, ordered[1:]):
            assert current["prev_hash"] == previous["event_hash"], (
                "each event's prev_hash equals the previous event's event_hash"
            )

        expected = hashlib.sha256(
            "|".join(e["event_hash"] for e in ordered).encode("utf-8")
        ).hexdigest()
        certificate = validate_success(
            api_client.get_audit_certificate(envelope["id"], account_headers), 200
        )
        assert certificate["certificate_hash"] == expected, (
            "the certificate hash is the digest over the ordered event hash chain"
        )
        assert certificate["event_count"] == len(ordered), (
            f"the chain covers every audit event: expected {len(ordered)}, "
            f"got {certificate['event_count']}"
        )


def test_patching_a_null_field_appends_one_completed_event(api):
    """PRD §3.5: "when a field transitions from null to a non-null value the
    system appends a `FIELD_COMPLETED` audit event."
    PRD §3.5: "A recipient or its sender may supply or update a field's `value`".
    PRD §2.5: "An `AuditEvent` is append-only and immutable".
    PRD §4: `PATCH /esign/fields/{id}` is listed with Authorized Roles
    `Recipient, Account`.

    Design: Corner/endpoints/field_patch_supplying_value_emits_field_completed_event
    """
    ctx = setup_single_signer_envelope(subject="Field patch envelope")
    account, envelope, recipient = ctx["account"], ctx["envelope"], ctx["recipient"]
    account_headers = make_account_headers(account["id"])

    document = ctx["document"]
    field = validate_success(
        api_client.place_field(
            envelope["id"],
            {
                "envelope_document_id": document["id"],
                "recipient_id": recipient["id"],
                "field_type": "TEXT",
                "required": False,
                "page_number": 1,
                "tab_order": 1,
            },
            account_headers,
        ),
        201,
    )
    assert field["value"] is None, f"the TEXT field starts null, got {field['value']!r}"

    events_before = validate_success(
        api_client.list_audit_events(account_headers, {"envelope_id": envelope["id"]}), 200
    )

    res = api_client.update_field_value(
        field["id"],
        {"value": "filled by test"},
        make_recipient_headers(recipient["id"]),
    )
    updated = validate_success(res, 200)

    assert updated["value"] == "filled by test", (
        f"the supplied value must be recorded, got {updated['value']!r}"
    )
    assert updated["value"] is not None

    events_after = validate_success(
        api_client.list_audit_events(account_headers, {"envelope_id": envelope["id"]}), 200
    )
    assert len(events_after) == len(events_before) + 1, (
        "the null-to-non-null transition appends exactly one FIELD_COMPLETED event: "
        f"expected {len(events_before) + 1} events, got {len(events_after)}"
    )
    ids_before = {event["id"] for event in events_before}
    new_events = [event for event in events_after if event["id"] not in ids_before]
    assert len(new_events) == 1, "exactly one new audit event must be appended"
    assert new_events[0]["event_type"] == "FIELD_COMPLETED", (
        f"the appended event is FIELD_COMPLETED, got {new_events[0]['event_type']}"
    )
    assert new_events[0]["recipient_id"] == recipient["id"], (
        "the field work is attributed to the acting recipient"
    )


def test_bulk_send_partial_success_sets_partial(api):
    """PRD §3.8: "When some rows succeed and some are rejected, the batch closes
    as `PARTIAL` with `succeeded_count` set to the number of rows that produced
    an envelope and `failed_count` set to the number rejected."
    PRD §3.8: "a row that lacks a resolvable `email` or that does not carry the
    role slots the template declares is rejected with `ERR_BULK_ROW_INVALID`
    (HTTP 422)".

    Design: Corner/endpoints/bulk_send_partial_success_sets_partial
    """
    ctx = setup_bulk_send_batch(total_rows=2, template_name="Partial Template")
    account, batch = ctx["account"], ctx["batch"]

    res = api_client.process_bulk_send(
        batch["id"],
        {"rows": [{"email": "ok@example.com"}, {"email": "bad-email"}]},
        make_account_headers(account["id"]),
    )
    processed = validate_success(res, 200)

    assert processed["status"] == "PARTIAL", (
        f"one valid and one rejected row yields PARTIAL, got {processed['status']}"
    )
    assert processed["succeeded_count"] == 1, (
        f"one row produced an envelope, got {processed['succeeded_count']}"
    )
    assert processed["failed_count"] == 1, (
        f"one row was rejected, got {processed['failed_count']}"
    )


def test_stale_version_void_is_rejected(api):
    """PRD §2.8: "Voiding an in-flight envelope, declaring an in-flight
    envelope expired, sealing a fully-signed envelope, and purging an expired
    envelope each take a non-optional `expected_envelope_version` input carrying
    the client's last-observed `version` of the target envelope. If that value
    does not equal the envelope's current `version`, the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and the envelope is not modified."
    PRD §3.7: "a void whose snapshot is out of date is refused with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/stale_envelope_version_rejects_void
    """
    ctx = setup_sent_single_signer(subject="OCC envelope")
    account, envelope = ctx["account"], ctx["envelope"]
    account_headers = make_account_headers(account["id"])

    sent_version = envelope["version"]
    delivered = validate_success(
        api_client.feed_envelope(
            envelope["id"], {"feed_event": "DELIVERED"}, account_headers
        ),
        200,
    )
    assert delivered["version"] != sent_version, (
        "the delivery feed advances the envelope version past the observed snapshot"
    )

    res = api_client.void_envelope(
        envelope["id"],
        {
            "expected_envelope_version": sent_version - 1,
            "void_reason": "stale client",
            "refund_credit": False,
        },
        account_headers,
    )
    validate_error(res, "ERR_STALE_VERSION")
    assert res.status_code == 412

    after = validate_success(api_client.get_envelope(envelope["id"], account_headers), 200)
    assert after["status"] != "VOIDED", (
        f"the stale void did not apply, got {after['status']}"
    )


def test_envelope_listing_paginates_with_has_more(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/cross_cutting_complexity_layers/pagination_limit_offset_returns_has_more
    """
    account = validate_success(
        api.create_account(
            {"name": "Acme Signing", "state_code": "CA", "tier": "STANDARD", "page_allowance": 25},
            TEST_USERS["admin_headers"],
        ),
        201,
    )
    policy = validate_success(
        api.create_retention_policy(
            {
                "name": "Std Retention",
                "scope": "GLOBAL",
                "retention_years": 3,
                "purge_mode": "ANONYMIZE_METADATA",
                "purge_grace_days": 0,
            },
            TEST_USERS["admin_headers"],
        ),
        201,
    )
    account_headers = make_account_headers(account["id"])
    for subject in ("Page A", "Page B"):
        validate_success(
            api.create_envelope(
                {
                    "sender_account_id": account["id"],
                    "subject": subject,
                    "routing_mode": "SEQUENTIAL",
                    "expires_after_days": 120,
                    "sender_visible_window_days": 30,
                    "retention_policy_id": policy["id"],
                },
                account_headers,
            ),
            201,
        )

    data, meta = validate_paginated(
        api.list_envelopes(
            account_headers, {"sender_account_id": account["id"], "limit": 1, "offset": 0}
        )
    )

    assert meta["total_count"] == 2, (
        f"both envelopes belong to the account: expected total_count 2, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, (
        f"one of two items is withheld, so has_more must be true, got {meta['has_more']}"
    )
    assert len(data) == 1, f"limit 1 must return a single item, got {len(data)}"
    assert data[0]["sender_account_id"] == account["id"], (
        "the returned envelope must belong to the filtered account"
    )