"""Validation priority-ordering conflict tests (PRD §2.9, §3.3, §3.1)."""
from test_helpers import (
    ApiErrorId,
    get_domain,
    get_success_data,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    setup_active_registrar,
    validate_error,
)


class TestStateBeatsTemporalOnRenew:
    def test_renew_from_redemption_grace_is_invalid_state(self, api):
        """PRD §2.9: "Incoming requests are validated in a fixed priority
        order, and the first failing check determines the error returned."
        PRD §2.9: "Only then does the system evaluate whether the target
        resource is in a state from which the requested transition exists
        (`ERR_INVALID_STATE`), followed by the business-safety checks
        (suspension holds and locks), the temporal-window checks".
        PRD §3.3: "While a domain is `ACTIVE`, its sponsoring
        `RegistrarOperator` may renew it explicitly by supplying a `years`
        extension of at least one year".

        Renewing a domain already in REDEMPTION_GRACE is a state failure, so
        the answer is ERR_INVALID_STATE even though the grace window is also
        long past.

        Design: Difficulty/priority_pair_validation_conflict/suspended_domain_and_stale_grace_window_state_beats_temporal
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-03-15T00:00:00Z")
        headers = make_operator_headers(registrar["id"])
        resp = api.create_domain(
            {"name": "conflict-one", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        domain = get_success_data(resp, expected_status=201)

        get_success_data(api.delete_domain(domain["id"], headers))
        # Far past every temporal window.
        set_clock("2028-08-27T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "DELETED"

        resp = api.renew_domain(domain["id"], 1, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_renew_from_pending_delete_is_state_not_temporal(self, api):
        """PRD §2.9: "Incoming requests are validated in a fixed priority
        order, and the first failing check determines the error returned."
        PRD §2.9: "Only then does the system evaluate whether the target
        resource is in a state from which the requested transition exists
        (`ERR_INVALID_STATE`), followed by the business-safety checks
        (suspension holds and locks), the temporal-window checks".
        PRD §3.3: "If thirty days pass with no restore, the domain enters
        `PENDING_DELETE`".

        In PENDING_DELETE the grace deadline has long passed too, but the
        state check is evaluated first, so the answer is ERR_INVALID_STATE,
        not ERR_GRACE_WINDOW_CLOSED.

        Design: Difficulty/priority_pair_validation_conflict/suspended_domain_and_stale_grace_window_state_beats_temporal
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-03-15T00:00:00Z")
        headers = make_operator_headers(registrar["id"])
        resp = api.create_domain(
            {"name": "conflict-one", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        domain = get_success_data(resp, expected_status=201)

        get_success_data(api.delete_domain(domain["id"], headers))
        # Deleted at 2026-01-15; PENDING_DELETE from 2026-02-14, not yet
        # DELETED until 2026-02-19.
        set_clock("2027-04-15T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "PENDING_DELETE"

        resp = api.renew_domain(domain["id"], 1, headers)
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] == "ERR_INVALID_STATE"


class TestReferentialBeatsFiscalOnCreate:
    def test_suspended_and_credit_hold_create_returns_not_active(self, api):
        """PRD §2.9: "Incoming requests are validated in a fixed priority
        order, and the first failing check determines the error returned."
        PRD §2.9: "followed by the business-safety checks (suspension holds
        and locks), the temporal-window checks, referential-integrity checks
        (registrar activity, nameserver linkage), constraint checks
        (uniqueness, pending-transfer exclusivity, authorization-code match),
        and finally the fiscal checks (credit holds, price cap, notice
        period, accreditation gates)."
        PRD §3.2: "The sponsoring registrar must be `ACTIVE`
        (`ERR_REGISTRAR_NOT_ACTIVE` otherwise) and free of a credit hold."

        A create whose registrar is both SUSPENDED and on credit hold fails
        the referential check first: ERR_REGISTRAR_NOT_ACTIVE.

        Design: Difficulty/priority_pair_validation_conflict/credit_hold_registrar_and_cap_breach_fiscal_vs_referential
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-04-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])

        resp = api.patch_registrar(
            registrar["id"],
            {"expected_registrar_version": registrar["version"],
             "credit_hold": True},
            make_admin_headers(),
        )
        get_success_data(resp)
        get_success_data(
            api.suspend_registrar(registrar["id"], make_admin_headers()))

        resp = api.create_domain(
            {"name": "conflict-two", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRAR_NOT_ACTIVE)

    def test_active_but_credit_hold_create_returns_credit_hold(self, api):
        """PRD §2.9: "referential-integrity checks (registrar activity,
        nameserver linkage), constraint checks (uniqueness, pending-transfer
        exclusivity, authorization-code match), and finally the fiscal checks
        (credit holds, price cap, notice period, accreditation gates)."
        PRD §3.1: "a registrar with `credit_hold` set is blocked from every
        billable mutation — new domain creates, renewals, restores, and
        transfer requests — with `ERR_REGISTRAR_CREDIT_HOLD`."

        When the referential check passes (registrar ACTIVE) and only the
        fiscal one fails, the answer is ERR_REGISTRAR_CREDIT_HOLD.

        Design: Difficulty/priority_pair_validation_conflict/credit_hold_registrar_and_cap_breach_fiscal_vs_referential
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-04-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])

        resp = api.patch_registrar(
            registrar["id"],
            {"expected_registrar_version": registrar["version"],
             "credit_hold": True},
            make_admin_headers(),
        )
        get_success_data(resp)

        resp = api.create_domain(
            {"name": "conflict-two", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRAR_CREDIT_HOLD)
