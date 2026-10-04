"""Cross-entity state dependency and parallel-dimension tests (PRD §2.9,
§3.1, §3.4, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    get_domain,
    get_success_data,
    make_abuse_headers,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    setup_active_domain,
    setup_active_registrar,
    setup_two_registrars_with_domain,
    validate_error,
)


class TestDomainCreateGatedOnRegistrarStatus:
    def test_create_allowed_while_active_rejected_after_suspend(self, api):
        """PRD §3.2: "The sponsoring registrar must be `ACTIVE`
        (`ERR_REGISTRAR_NOT_ACTIVE` otherwise) and free of a credit hold."
        PRD §3.1: "Suspending an `ACTIVE` registrar moves it to `SUSPENDED`;
        from that moment the registrar fails the active-registrar
        precondition on domain creation, renewal, restore, and transfer
        requests, surfacing as `ERR_REGISTRAR_NOT_ACTIVE` on those
        operations."

        Design: Difficulty/cross_entity_state_dependency/domain_create_gated_on_registrar_active_status
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-04-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])

        resp = api.create_domain(
            {"name": "gate-open", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        opened = get_success_data(resp, expected_status=201)
        assert opened["status"] == "ACTIVE"

        resp = api.suspend_registrar(registrar["id"], make_admin_headers())
        get_success_data(resp)

        resp = api.create_domain(
            {"name": "gate-closed", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRAR_NOT_ACTIVE)

    def test_create_rejected_while_suspended_allowed_after_reinstate(self, api):
        """PRD §3.1: "Suspending an `ACTIVE` registrar moves it to
        `SUSPENDED`; from that moment the registrar fails the
        active-registrar precondition on domain creation, renewal, restore,
        and transfer requests, surfacing as `ERR_REGISTRAR_NOT_ACTIVE` on
        those operations."
        PRD §3.1: "Reinstating a `SUSPENDED` registrar returns it to
        `ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/domain_create_gated_on_registrar_active_status
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-04-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])

        resp = api.suspend_registrar(registrar["id"], make_admin_headers())
        get_success_data(resp)
        resp = api.create_domain(
            {"name": "gate-closed", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRAR_NOT_ACTIVE)

        resp = api.reinstate_registrar(registrar["id"], make_admin_headers())
        get_success_data(resp)
        resp = api.create_domain(
            {"name": "gate-reopened", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        reopened = get_success_data(resp, expected_status=201)
        assert reopened["status"] == "ACTIVE"


class TestTransferGatedOnDomainLock:
    def test_registry_lock_blocks_transfer_request(self, api):
        """PRD §3.5: "The domain must be `ACTIVE`, unsuspended, and unlocked
        — a `CLIENT_LOCK` or `REGISTRY_LOCK` fails with `ERR_DOMAIN_LOCKED`".

        Design: Difficulty/cross_entity_state_dependency/transfer_request_gated_on_domain_lock_status
        """
        reg_a, reg_b, _schedule, domain = setup_two_registrars_with_domain(
            clock="2027-03-01T00:00:01Z", name="locked-gate")
        set_clock("2027-05-08T00:00:00Z")
        resp = api.lock_domain(
            domain["id"],
            {"lock_action": "REGISTRY_LOCK",
             "expected_domain_version": domain["version"],
             "lock_token": "s3cret"},
            make_admin_headers(),
        )
        locked = get_success_data(resp)
        assert locked["lock_status"] == "REGISTRY_LOCK"

        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOMAIN_LOCKED)

        after = get_domain(domain["id"])
        assert after["status"] == "ACTIVE"
        assert after["registrar_id"] == reg_a["id"]

    def test_client_lock_blocks_transfer_request(self, api):
        """PRD §3.5: "The domain must be `ACTIVE`, unsuspended, and unlocked
        — a `CLIENT_LOCK` or `REGISTRY_LOCK` fails with `ERR_DOMAIN_LOCKED`".

        Design: Difficulty/cross_entity_state_dependency/transfer_request_gated_on_domain_lock_status
        """
        reg_a, reg_b, _schedule, domain = setup_two_registrars_with_domain(
            clock="2027-03-01T00:00:01Z", name="locked-gate")
        set_clock("2027-05-08T00:00:00Z")
        resp = api.lock_domain(
            domain["id"],
            {"lock_action": "CLIENT_LOCK",
             "expected_domain_version": domain["version"]},
            make_operator_headers(reg_a["id"]),
        )
        locked = get_success_data(resp)
        assert locked["lock_status"] == "CLIENT_LOCK"

        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOMAIN_LOCKED)
        assert get_domain(domain["id"])["status"] == "ACTIVE"


class TestParallelDimensions:
    def test_lock_and_suspension_move_independently(self, api):
        """PRD §3.4: "Security locks form an independent dimension on every
        domain."
        PRD §3.4: "Suspension is the orthogonal legal dimension, recorded in
        `suspension_status` as `NONE` or `HOLD`, and is driven by abuse
        resolution and court orders rather than by the lock endpoint."
        PRD §3.6: "Resolving as `ACTIONED` is the enforcement path — it sets
        the domain's `suspension_status` to `HOLD`".

        Design: Difficulty/non_linear_state_machine/domain_parallel_dimensions_lock_and_suspension_independent
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-01T00:00:00Z", name="parallel-dims", years=2)

        resp = api.lock_domain(
            domain["id"],
            {"lock_action": "REGISTRY_LOCK",
             "expected_domain_version": domain["version"],
             "lock_token": "s3cret"},
            make_admin_headers(),
        )
        locked = get_success_data(resp)
        assert locked["lock_status"] == "REGISTRY_LOCK"
        assert locked["status"] == "ACTIVE"
        assert locked["suspension_status"] == "NONE"

        abuse = make_abuse_headers()
        resp = api.create_abuse_report(
            {"domain_id": domain["id"], "reporter_contact": "le@agency.example",
             "category": "PHISHING", "detail": "phishing kit hosted"},
            abuse,
        )
        report = get_success_data(resp, expected_status=201)
        resp = api.review_abuse_report(report["id"], abuse)
        get_success_data(resp)
        resp = api.resolve_abuse_report(report["id"], "ACTIONED", abuse)
        resolved = get_success_data(resp)
        assert resolved["status"] == "ACTIONED"

        final = get_domain(domain["id"])
        assert final["status"] == "ACTIVE", (
            "lifecycle dimension untouched by lock and suspension"
        )
        assert final["lock_status"] == "REGISTRY_LOCK", (
            "lock dimension unchanged by the abuse action"
        )
        assert final["suspension_status"] == "HOLD", (
            "suspension dimension set by the abuse action alone"
        )

    def test_suspension_blocks_renew_without_touching_lock(self, api):
        """PRD §3.6: "Resolving as `ACTIONED` is the enforcement path — it
        sets the domain's `suspension_status` to `HOLD`, which immediately
        blocks renewals, deletes, restores, and new transfer requests on that
        name with `ERR_DOMAIN_SUSPENDED`."
        PRD §3.4: "Security locks form an independent dimension on every
        domain."

        Design: Difficulty/non_linear_state_machine/domain_parallel_dimensions_lock_and_suspension_independent
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-01T00:00:00Z", name="parallel-dims")
        headers = make_operator_headers(registrar["id"])

        abuse = make_abuse_headers()
        resp = api.create_abuse_report(
            {"domain_id": domain["id"], "reporter_contact": "le@agency.example",
             "category": "MALWARE", "detail": "malware dropper"},
            abuse,
        )
        report = get_success_data(resp, expected_status=201)
        get_success_data(api.review_abuse_report(report["id"], abuse))
        get_success_data(api.resolve_abuse_report(report["id"], "ACTIONED",
                                                  abuse))

        resp = api.renew_domain(domain["id"], 1, headers)
        validate_error(resp, ApiErrorId.ERR_DOMAIN_SUSPENDED)

        final = get_domain(domain["id"])
        assert final["lock_status"] == "NONE"
        assert final["suspension_status"] == "HOLD"
        assert final["status"] == "ACTIVE"
