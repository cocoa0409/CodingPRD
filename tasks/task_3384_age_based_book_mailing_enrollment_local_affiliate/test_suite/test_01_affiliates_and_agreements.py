"""Affiliate and partner-agreement claims (PRD §3.1-3.2, §2.7 OCC)."""
import pytest

from test_helpers import (
    ApiErrorId,
    AgreementStatus,
    BOGUS_UUID,
    DEFAULT_AGREEMENT_EFFECTIVE_FROM,
    DEFAULT_AGREEMENT_EFFECTIVE_TO,
    DEFAULT_FUNDRAISING_COMMITMENT_CENTS,
    TEST_USERS,
    api_client,
    approve_agreement,
    assert_affiliate,
    assert_affiliate_agreement,
    create_affiliate,
    create_affiliate_payload,
    create_agreement,
    create_agreement_payload,
    create_state_program,
    get_affiliate,
    make_affiliate_coordinator_headers,
    make_state_program_officer_headers,
    reject_agreement,
    set_logical_clock,
    setup_operative_affiliate,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


class TestAffiliateCreation:
    def test_affiliate_create_applies_computed_defaults(self, api):
        """PRD §3.1: "A freshly created affiliate starts with `enrolled_count`
        at zero and is **not** operative."
        PRD §4: "Operations that create new resources return a `201 Created`
        status code."

        Design: Corner/entities/affiliate_create_applies_computed_defaults
        """
        set_logical_clock()
        program = create_state_program()
        resp = api.create_affiliate(create_affiliate_payload(program["id"]), _ADMIN)
        data = validate_success(resp, 201)
        assert_affiliate(data)
        assert data["enrolled_count"] == 0, "fresh affiliate starts at enrolled_count 0"
        assert data["operative"] is False, "no ACTIVE agreement yet -> not operative"
        assert data["state_program_id"] == program["id"]
        assert data["postal_prefixes"] == ["372", "370"]

    def test_affiliate_create_with_extra_system_fields_rejected(self, api):
        """PRD §2.5: "A request body that supplies `id`, `version`, or any other
        system or computed field (for instance `enrolled_count` on an affiliate)
        is malformed and rejected under the body well-formedness check of §2.8."

        Design: Corner/entities/affiliate_create_with_extra_system_fields_rejected
        """
        set_logical_clock()
        program = create_state_program()
        payload = create_affiliate_payload(
            program["id"],
            name="Sneaky Affiliate",
            postal_prefixes=["375"],
            id=BOGUS_UUID,
            version=9,
            enrolled_count=50,
        )
        resp = api.create_affiliate(payload, _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAgreementLifecycle:
    def test_agreement_get_round_trips_window_fields(self, api):
        """PRD §3.2: "A coordinator (for their own affiliate) or a
        `PlatformAdmin` proposes one by supplying `effective_from`,
        `effective_to`, and `local_fundraising_commitment_cents`" and "A new
        agreement starts in `PENDING_APPROVAL`".
        PRD §2.2: "operations that create or modify a resource will return the
        created or updated resource object in the data field."

        Design: Corner/entities/agreement_get_round_trips_window_fields
        """
        base = setup_operative_affiliate(approve=False)
        affiliate, agreement = base["affiliate"], base["agreement"]
        rows, meta = validate_paginated(api.list_agreements(affiliate["id"], _ADMIN))
        assert meta["total_count"] == 1
        row = rows[0]
        assert_affiliate_agreement(row)
        assert row["id"] == agreement["id"]
        assert row["affiliate_id"] == affiliate["id"]
        assert row["effective_from"].startswith("2026-01-01"), (
            f"effective_from must round-trip the submitted window start, got {row['effective_from']!r}"
        )
        assert row["effective_to"].startswith("2028-01-01"), (
            f"effective_to must round-trip the submitted window end, got {row['effective_to']!r}"
        )
        assert row["local_fundraising_commitment_cents"] == DEFAULT_FUNDRAISING_COMMITMENT_CENTS
        assert row["status"] == AgreementStatus.PENDING_APPROVAL.value
        assert row.get("decided_by") is None, "decided_by is null until the officer decides"

    def test_agreement_window_inverted_rejected(self, api):
        """PRD §3.2: "The coverage window is half-open: it runs from
        `effective_from` inclusive to `effective_to` exclusive, and
        `effective_to` must be strictly after `effective_from` or the request
        fails with `ERR_AGREEMENT_WINDOW_INVALID`."
        PRD §3.2: "creating it increments the owning affiliate's `version` by
        one" — a rejected create creates nothing and bumps nothing.

        Design: Corner/validations/agreement_window_inverted_rejected
        """
        set_logical_clock()
        program = create_state_program()
        affiliate = create_affiliate(program["id"])
        version_before = affiliate["version"]
        payload = create_agreement_payload(
            version_before,
            effective_from="2027-01-01T00:00:00Z",
            effective_to="2026-01-01T00:00:00Z",
            local_fundraising_commitment_cents=100,
        )
        resp = api.create_agreement(
            affiliate["id"], payload, make_affiliate_coordinator_headers(affiliate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_INVALID)
        assert get_affiliate(affiliate["id"])["version"] == version_before, (
            "a failed create must not advance the affiliate's version"
        )

    def test_approve_unknown_agreement_returns_not_found(self, api):
        """PRD §2.8: "identifiers in the URL are resolved strictly left to
        right; the first identifier that does not exist yields that entity's
        specific 404."
        PRD §2.8: "The entity-specific not-found codes are
        `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_AFFILIATE_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_CHILD_NOT_FOUND`,
        `ERR_ADDRESS_CHANGE_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`,
        `ERR_SELECTION_NOT_FOUND`, `ERR_PRINT_ORDER_NOT_FOUND`,
        `ERR_WAVE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, and
        `ERR_INVOICE_NOT_FOUND`."

        Design: Corner/validations/approve_unknown_agreement_returns_not_found
        """
        set_logical_clock()
        program = create_state_program()
        resp = api.approve_agreement(
            BOGUS_UUID, make_state_program_officer_headers(program["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_FOUND)

    def test_coordinator_approve_unknown_agreement_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN`."
        PRD §2.8: "When a request violates several rules at once, the earliest
        applicable check in this order produces the error, and later checks are
        not consulted" — role authorization (check 2) precedes path existence
        (check 3), and agreement approval lists only `StateProgramOfficer`.

        Design: Corner/validations/coordinator_approve_unknown_agreement_returns_forbidden
        """
        set_logical_clock()
        program = create_state_program()
        affiliate = create_affiliate(program["id"])
        resp = api.approve_agreement(
            BOGUS_UUID, make_affiliate_coordinator_headers(affiliate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_officer_cannot_approve_cross_program_agreement(self, api):
        """PRD §2.1: "When `X-User-Role` is `StateProgramOfficer`, `X-User-ID`
        is the `id` of the `StateProgram` the officer serves; the officer may
        act only on agreements whose affiliate belongs to that program, again
        with `ERR_FORBIDDEN` on mismatch."

        Design: Corner/rbac/officer_cannot_approve_cross_program_agreement
        """
        set_logical_clock()
        program_tn = create_state_program()
        program_ga = create_state_program(
            state_code="GA", name="GA Books Across", funding_share_bp=5000
        )
        affiliate_ga = create_affiliate(
            program_ga["id"],
            name="Atlanta Early Books",
            postal_prefixes=["303"],
            contact_email="coord@aeb.org",
        )
        agreement_ga = create_agreement(affiliate_ga)
        resp = api.approve_agreement(
            agreement_ga["id"], make_state_program_officer_headers(program_tn["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rows, _meta = validate_paginated(api.list_agreements(affiliate_ga["id"], _ADMIN))
        assert rows[0]["status"] == AgreementStatus.PENDING_APPROVAL.value
        assert rows[0].get("decided_by") is None

    def test_approve_rejected_agreement_returns_invalid_state(self, api):
        """PRD §3.2: "it moves the agreement to `REJECTED`, records
        `decided_by`, and is terminal — a rejected agreement cannot be
        resubmitted, so the parties create a fresh one instead."
        PRD §2.8: "**State preconditions** — the target resource's state
        permits the requested transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/approve_rejected_agreement_returns_invalid_state
        """
        base = setup_operative_affiliate(approve=False)
        program, affiliate, agreement = (
            base["program"],
            base["affiliate"],
            base["agreement"],
        )
        reject_agreement(agreement["id"], program["id"])
        resp = api.approve_agreement(
            agreement["id"], make_state_program_officer_headers(program["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows, _meta = validate_paginated(api.list_agreements(affiliate["id"], _ADMIN))
        assert rows[0]["status"] == AgreementStatus.REJECTED.value
        assert rows[0]["decided_by"] == program["id"], (
            "decided_by keeps the rejecting officer's X-User-ID"
        )


class TestAgreementConcurrency:
    def test_agreement_create_with_stale_version_returns_412(self, api):
        """PRD §2.7: "The request must carry `expected_affiliate_version`, a
        non-optional field holding the affiliate `version` the client last
        observed. If that value does not match the affiliate's current
        `version` — because another writer has advanced the affiliate since,
        for example by creating an agreement of their own — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "creating it increments the owning affiliate's `version` by
        one".

        Design: Corner/cross_cutting_complexity_layers/agreement_create_with_stale_version_returns_412
        """
        set_logical_clock()
        program = create_state_program()
        affiliate = create_affiliate(program["id"])
        version_at_create = affiliate["version"]
        first = create_agreement(affiliate)
        assert first["status"] == AgreementStatus.PENDING_APPROVAL.value
        version_after_first = get_affiliate(affiliate["id"])["version"]
        assert version_after_first == version_at_create + 1, (
            "creating an agreement increments the affiliate's version by one"
        )
        stale_payload = create_agreement_payload(
            version_at_create,
            effective_from="2028-01-01T00:00:00Z",
            effective_to="2029-01-01T00:00:00Z",
        )
        resp = api.create_agreement(
            affiliate["id"], stale_payload,
            make_affiliate_coordinator_headers(affiliate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        retry_payload = create_agreement_payload(
            version_after_first,
            effective_from="2028-01-01T00:00:00Z",
            effective_to="2029-01-01T00:00:00Z",
        )
        resp = api.create_agreement(
            affiliate["id"], retry_payload,
            make_affiliate_coordinator_headers(affiliate["id"]),
        )
        retried = validate_success(resp, 201)
        assert retried["status"] == AgreementStatus.PENDING_APPROVAL.value
        assert get_affiliate(affiliate["id"])["version"] == version_after_first + 1


class TestAgreementGeographyOverlap:
    def test_overlapping_window_on_shared_prefix_rejected(self, api):
        """PRD §3.2: "no other `PENDING_APPROVAL` or `ACTIVE` agreement whose
        postal-prefix set intersects this affiliate's `postal_prefixes` may
        have a window overlapping this one, where overlap is judged on the
        half-open intervals".
        PRD §3.2: "A violation is rejected with
        `ERR_AGREEMENT_GEOGRAPHY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_window_half_open_adjacency
        """
        base = setup_operative_affiliate()
        program = base["program"]
        affiliate_c = create_affiliate(
            program["id"],
            name="Chattanooga Reads",
            postal_prefixes=["373", "372"],
            contact_email="coord@cr.org",
        )
        agreement_c = create_agreement(
            affiliate_c,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z",
        )
        resp = api.approve_agreement(
            agreement_c["id"], make_state_program_officer_headers(program["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_GEOGRAPHY_OVERLAP)
        rows, _meta = validate_paginated(api.list_agreements(affiliate_c["id"], _ADMIN))
        assert rows[0]["status"] == AgreementStatus.PENDING_APPROVAL.value, (
            "a rejected overlap leaves the agreement PENDING_APPROVAL"
        )

    def test_adjacent_window_approves_and_create_bumps_version(self, api):
        """PRD §3.2: "two windows that merely touch, one's `effective_to` equal
        to the other's `effective_from`, do **not** overlap and are allowed."
        PRD §3.2: "creating it increments the owning affiliate's `version` by
        one".

        Design: Difficulty/resource_temporal_overlap/agreement_window_half_open_adjacency
        """
        base = setup_operative_affiliate()
        program = base["program"]
        affiliate_c = create_affiliate(
            program["id"],
            name="Chattanooga Reads",
            postal_prefixes=["373", "372"],
            contact_email="coord@cr.org",
        )
        version_at_create = affiliate_c["version"]
        # Overlapping window is refused; the officer then rejects it (terminal).
        agreement_c1 = create_agreement(
            affiliate_c,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z",
        )
        version_after_first_create = get_affiliate(affiliate_c["id"])["version"]
        assert version_after_first_create == version_at_create + 1
        resp = api.approve_agreement(
            agreement_c1["id"], make_state_program_officer_headers(program["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_GEOGRAPHY_OVERLAP)
        reject_agreement(agreement_c1["id"], program["id"])
        # Adjacent window starting exactly at A's effective_to is allowed.
        affiliate_c_now = get_affiliate(affiliate_c["id"])
        agreement_c2 = create_agreement(
            affiliate_c_now,
            effective_from="2028-01-01T00:00:00Z",
            effective_to="2029-01-01T00:00:00Z",
        )
        approved = approve_agreement(agreement_c2["id"], program["id"])
        assert approved["status"] == AgreementStatus.ACTIVE.value
        assert approved["decided_by"] == program["id"]
        assert get_affiliate(affiliate_c["id"])["version"] == (
            affiliate_c_now["version"] + 1
        ), "each successful agreement create bumps the affiliate version by one"
