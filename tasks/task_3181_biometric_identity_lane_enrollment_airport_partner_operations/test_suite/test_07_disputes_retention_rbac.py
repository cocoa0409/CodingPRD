"""Identity disputes, suspension, termination, biometric retention, RBAC, and
consistency: dispute-confirmed cascade, segregation of duties, retention
sweep boundary, retention log immutability, RBAC denial, auth failure, and
immediate consistency of the enrollment completion cascade."""
from test_helpers import (
    ApiErrorId,
    capture_biometric,
    complete_enrollment,
    create_active_member,
    create_enrollment_center,
    create_subscription,
    enroll_member_at_center,
    make_compliance_officer_headers,
    make_member_headers,
    open_dispute,
    open_enrollment,
    register_member,
    set_clock,
    setup_airport_with_active_agreement,
    submit_document,
    cancel_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPS, CO, PM


class TestDisputeConfirmedCascade:
    def _setup_member_with_dispute(self):
        airport, _ = setup_airport_with_active_agreement("ATL")
        center = create_enrollment_center(airport["id"], name="ATL Center")
        member, enrollment = enroll_member_at_center(
            center, email="victim@x.com", full_name="Vic Tim",
            date_of_birth="1985-07-07", document_number="P9999999",
        )
        sub = create_subscription(member, plan="INDIVIDUAL", billing_cycle_day=1)
        dispute = open_dispute(member, enrollment, officer_user_id="co-open")
        return member, enrollment, sub, dispute

    def test_resolve_confirmed_terminates_member_and_cancels_subscription(self, api):
        """PRD §3.7: "A confirmed outcome — `RESOLVED_CONFIRMED` — moves the member to
        `TERMINATED` and triggers the full termination cascade: the member's
        subscription (if any) is cancelled with the same semantics as a voluntary
        cancel, the member is detached from any family group with `slots_used`
        decremented, `deletion_due_at` is set to the logical clock plus the retention
        period, and a `BiometricRetentionLog` entry of type `DELETION_SCHEDULED` is
        appended."
        PRD §3.8: "Biometric data lives under a thirty-day retention clock."

        Design: Difficulty/transitive_cascade/dispute_confirmed_cascades_member_termination_then_retention_log
        """
        member, _, sub, dispute = self._setup_member_with_dispute()
        validate_success(api.investigate_dispute(
            dispute["id"], make_compliance_officer_headers("co-resolve")
        ))
        resolved = validate_success(api.resolve_dispute(
            dispute["id"], "RESOLVED_CONFIRMED",
            "Document fraud confirmed via issuer check",
            make_compliance_officer_headers("co-resolve"),
        ))
        assert resolved["status"] == "RESOLVED_CONFIRMED"
        member_after = validate_success(api.get_member(member["id"], CO))
        assert member_after["status"] == "TERMINATED"
        sub_after = validate_success(api.get_subscription(sub["id"], OPS))
        assert sub_after["status"] == "CANCELLED", "cascade hop: subscription cancelled"

    def test_resolve_confirmed_schedules_retention_and_logs(self, api):
        """PRD §3.8: "Whenever a subscription cancels or a member is terminated, the member's
        `deletion_due_at` is set to the trigger instant plus thirty days and a
        `DELETION_SCHEDULED` entry lands in the retention audit log."

        Design: Difficulty/transitive_cascade/dispute_confirmed_cascades_member_termination_then_retention_log
        """
        member, _, sub, dispute = self._setup_member_with_dispute()
        validate_success(api.resolve_dispute(
            dispute["id"], "RESOLVED_CONFIRMED", "Confirmed via issuer",
            make_compliance_officer_headers("co-resolve"),
        ))
        member_after = validate_success(api.get_member(member["id"], CO))
        assert member_after["deletion_due_at"] == "2026-10-01T00:00:00.000Z", (
            f"trigger 2026-09-01 plus 30 days, got {member_after['deletion_due_at']}"
        )
        logs, _ = validate_paginated(
            api.list_retention_logs(CO, params={"member_id": member["id"]})
        )
        actions = [entry["action"] for entry in logs]
        assert "DELETION_SCHEDULED" in actions, f"expected DELETION_SCHEDULED, got {actions}"


class TestSegregationOfDuties:
    def _setup_dispute(self, opener="co-1"):
        airport, _ = setup_airport_with_active_agreement("GRR")
        center = create_enrollment_center(airport["id"], name="GRR Center")
        member, enrollment = enroll_member_at_center(
            center, email="sod@x.com", full_name="Sod Member",
            date_of_birth="1990-01-01", document_number="PS000700",
        )
        dispute = open_dispute(member, enrollment, officer_user_id=opener,
                               reason="DATA_ERROR")
        return member, dispute

    def test_opener_cannot_resolve(self, api):
        """PRD §3.7: "Segregation of duties is enforced on resolution: the resolving officer's
        `X-User-ID` must differ from the opener's, and a self-resolution is refused
        with `ERR_SEGREGATION_OF_DUTIES`; the resolver is recorded as `resolved_by`."

        Design: Corner/roles/dispute_resolver_must_differ_from_opener
        """
        _, dispute = self._setup_dispute(opener="co-1")
        resp = api.resolve_dispute(
            dispute["id"], "RESOLVED_CLEAR", "Self-resolution attempt",
            make_compliance_officer_headers("co-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_independent_officer_resolves_and_member_recovers(self, api):
        """PRD §3.7: "A clear outcome — `RESOLVED_CLEAR` — returns the suspended member to
        `ACTIVE`, leaving the member's `verification_level` (`NONE`, `BIOMETRIC_ID`,
        or `FEDERAL_TRUSTED`) untouched."

        Design: Corner/roles/dispute_resolver_must_differ_from_opener
        """
        member, dispute = self._setup_dispute(opener="co-1")
        resolved = validate_success(api.resolve_dispute(
            dispute["id"], "RESOLVED_CLEAR", "Independent review clears the member",
            make_compliance_officer_headers("co-2"),
        ))
        assert resolved["status"] == "RESOLVED_CLEAR"
        assert resolved.get("resolved_by") == "co-2"
        member_after = validate_success(api.get_member(member["id"], CO))
        assert member_after["status"] == "ACTIVE"


class TestRetentionSweepBoundary:
    def _setup_cancelled_member(self):
        airport, _ = setup_airport_with_active_agreement("BOI")
        center = create_enrollment_center(airport["id"], name="BOI Center")
        member, _ = enroll_member_at_center(
            center, email="ret@x.com", full_name="Ret Subject",
            date_of_birth="1990-01-01", document_number="PR000001",
        )
        sub = create_subscription(member, plan="INDIVIDUAL", billing_cycle_day=1)
        cancel_subscription(sub, member)
        return member

    def test_at_due_instant_no_purge(self, api):
        """PRD §3.8: "The daily sweep purges biometric data only when the logical clock is
        strictly after `deletion_due_at` — exactly at the due instant is not yet due —
        and appends a `DELETED` entry with `actor_user_id` recorded as system."

        Design: Corner/calculations/retention_purge_only_strictly_after_due_date
        """
        member = self._setup_cancelled_member()
        set_clock("2026-10-01T00:00:00Z")  # exactly deletion_due_at
        logs, _ = validate_paginated(
            api.list_retention_logs(CO, params={"member_id": member["id"]})
        )
        actions = [entry["action"] for entry in logs]
        assert actions == ["DELETION_SCHEDULED"], (
            f"strictly-after semantics: no purge at the exact due instant, got {actions}"
        )

    def test_after_due_instant_purged(self, api):
        """PRD §3.8: "The daily sweep purges biometric data only when the logical clock is
        strictly after `deletion_due_at` — exactly at the due instant is not yet due —
        and appends a `DELETED` entry with `actor_user_id` recorded as system."

        Design: Corner/calculations/retention_purge_only_strictly_after_due_date
        """
        member = self._setup_cancelled_member()
        set_clock("2026-10-02T00:00:01Z")  # strictly after deletion_due_at
        logs, _ = validate_paginated(
            api.list_retention_logs(CO, params={"member_id": member["id"]})
        )
        actions = [entry["action"] for entry in logs]
        assert "DELETED" in actions, f"expected a DELETED entry, got {actions}"
        assert len(logs) == 2


class TestRetentionLogImmutability:
    def test_log_entry_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "`BiometricRetentionLog` carries only `id` and `created_at` — both
        `updated_at` and `version` are absent on retention log entries, since audit
        rows are append-only."

        Design: Corner/entities/biometric_retention_log_immutable_no_version
        """
        airport, _ = setup_airport_with_active_agreement("ABQ")
        center = create_enrollment_center(airport["id"], name="ABQ Center")
        member, _ = enroll_member_at_center(
            center, email="log@x.com", full_name="Log Subject",
            date_of_birth="1990-09-09", document_number="PL000001",
        )
        sub = create_subscription(member, plan="INDIVIDUAL", billing_cycle_day=1)
        cancel_subscription(sub, member)
        logs, _ = validate_paginated(
            api.list_retention_logs(CO, params={"member_id": member["id"]})
        )
        assert len(logs) >= 1
        entry = logs[0]
        assert entry["action"] == "DELETION_SCHEDULED"
        assert entry["member_id"] == member["id"]
        assert "id" in entry and "created_at" in entry
        assert "version" not in entry, "append-only rows carry no version"
        assert "updated_at" not in entry, "append-only rows carry no updated_at"


class TestMemberRbacDenial:
    def test_member_cannot_create_airports(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." — the Member role is
        not permitted on POST /airports (see the endpoint table: POST /airports is
        OpsAdmin-only).

        Design: Corner/roles/member_cannot_manage_airports_or_agreements
        """
        member = register_member(
            email="rbac@x.com", full_name="Rbac Member", date_of_birth="1990-01-01"
        )
        resp = api.create_airport(
            {"iata_code": "RBX", "name": "Rbac One", "city": "X", "state_code": "TX"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_member_cannot_create_agreements(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." — the Member role is
        not permitted on POST /partner-agreements (PartnerManager-only per the
        endpoint table).

        Design: Corner/roles/member_cannot_manage_airports_or_agreements
        """
        member = register_member(
            email="rbac@x.com", full_name="Rbac Member", date_of_birth="1990-01-01"
        )
        airport = validate_success(api.create_airport(
            {"iata_code": "RBY", "name": "Rbac Two", "city": "X", "state_code": "TX"}, OPS
        ), expected_status=201)
        resp = api.create_agreement(
            {"airport_id": airport["id"], "rev_share_rate": 0.10,
             "subscription_share_rate": 0.02, "monthly_minimum_cents": 10000,
             "federal_integration": False, "staffing_footprint_seats": 4,
             "term_months": 12, "effective_from": "2026-09-01T00:00:00Z"},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestUnauthenticated:
    def test_missing_role_header_rejected_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role string the platform
        does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)." and
        "These two checks precede all other validation on every endpoint."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api._request(
            "POST", "/airports",
            {"iata_code": "XXX", "name": "No Auth", "city": "Nowhere",
             "state_code": "ZZ"},
            {"X-User-ID": "some-user"},  # X-User-Role absent
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unrecognized_role_rejected_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role string the platform
        does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api._request(
            "POST", "/airports",
            {"iata_code": "XXY", "name": "Bad Role", "city": "Nowhere",
             "state_code": "ZZ"},
            {"X-User-ID": "some-user", "X-User-Role": "Superuser"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestImmediateConsistency:
    def test_member_active_in_next_request_after_completion(self, api):
        """PRD §3.3: "On completion three cascades run: the member moves from
        `PENDING_ENROLLMENT` to `ACTIVE` with `version` incremented" — the flip is
        visible on the very next read.

        Design: Corner/consistency_model/enrollment_completion_visible_immediately_on_member_read
        """
        airport, _ = setup_airport_with_active_agreement("BTV")
        center = create_enrollment_center(airport["id"], name="BTV Center")
        member = register_member(
            email="imm@x.com", full_name="Imm Member", date_of_birth="1990-01-01"
        )
        enrollment = open_enrollment(
            member, "ENROLLMENT_CENTER", center["id"],
            document_number="PI001000", biometric_capture_ok=True,
        )
        enrollment = submit_document(enrollment, member)
        enrollment = capture_biometric(enrollment, member)
        completed = complete_enrollment(enrollment, member)
        assert completed["status"] == "COMPLETED"
        member_after = validate_success(api.get_member(member["id"], CO))
        assert member_after["status"] == "ACTIVE", (
            "no eventual-consistency lag: ACTIVE in the very next request"
        )
