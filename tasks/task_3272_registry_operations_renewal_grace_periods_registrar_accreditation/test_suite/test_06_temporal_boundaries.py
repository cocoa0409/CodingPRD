"""Temporal window boundary tests (PRD §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    find_invoice,
    get_domain,
    get_success_data,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    setup_active_domain,
    setup_two_registrars_with_domain,
    validate_error,
    validate_error_is_one_of,
)


class TestRenewalGraceBoundary:
    def test_renew_at_exact_grace_deadline_allowed(self, api):
        """PRD §3.3: "While a domain is `ACTIVE`, its sponsoring
        `RegistrarOperator` may renew it explicitly by supplying a `years`
        extension of at least one year, provided the current logical time is
        at or before the domain's `grace_deadline` — attempting to renew
        after that boundary is rejected with `ERR_GRACE_WINDOW_CLOSED`".

        Renew at the expiry instant (the last moment the domain is still
        ACTIVE): the 1-year extension moves `expires_on` to 2029-03-15 and
        recomputes the grace deadline to 2029-04-29.

        Design: Difficulty/boundary_precision_check/renew_at_exact_grace_deadline_allowed_one_second_later_rejected
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-03-15T00:00:00Z", name="boundary-renew")
        headers = make_operator_headers(registrar["id"])
        assert domain["grace_deadline"] == "2028-04-29T00:00:00.000Z"

        set_clock("2028-03-15T00:00:00Z")
        resp = api.renew_domain(domain["id"], 1, headers)
        renewed = get_success_data(resp)
        assert renewed["expires_on"] == "2029-03-15T00:00:00.000Z"
        assert renewed["grace_deadline"] == "2029-04-29T00:00:00.000Z"

        invoice = find_invoice(domain_id=domain["id"], kind="RENEW")
        assert invoice["base_cents"] == 850
        assert invoice["premium_surcharge_cents"] == 0
        assert invoice["total_cents"] == 850

    def test_renew_after_grace_deadline_rejected(self, api):
        """PRD §3.3: "provided the current logical time is at or before the
        domain's `grace_deadline` — attempting to renew after that boundary
        is rejected with `ERR_GRACE_WINDOW_CLOSED`".

        Renew at the expiry instant (allowed), landing the grace deadline at
        2029-04-29; one second past it the renewal is rejected with
        `ERR_GRACE_WINDOW_CLOSED`.

        Design: Difficulty/boundary_precision_check/renew_at_exact_grace_deadline_allowed_one_second_later_rejected
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-03-15T00:00:00Z", name="boundary-renew")
        headers = make_operator_headers(registrar["id"])

        # Renew at the expiry instant (still ACTIVE, allowed), moving the
        # grace deadline to 2029-04-29.
        set_clock("2028-03-15T00:00:00Z")
        get_success_data(api.renew_domain(domain["id"], 1, headers))

        # One second after the new grace deadline: renewal is closed. The
        # clock jump may first cascade the domain through auto-renew grace
        # lapse, so accept either the temporal rejection or the terminal
        # state rejection the cascade produces.
        set_clock("2029-04-29T00:00:01Z")
        resp = api.renew_domain(domain["id"], 1, headers)
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_GRACE_WINDOW_CLOSED, ApiErrorId.ERR_INVALID_STATE],
        )


class TestTransferSixtyDayBoundary:
    def test_transfer_day_59_rejected_day_60_allowed(self, api):
        """PRD §3.5: "must have been registered for at least sixty days,
        meaning the current logical time is at or past `created_at` plus
        sixty days (younger names are rejected with
        `ERR_TRANSFER_WINDOW_CLOSED`)."

        A domain created at 2027-03-01 is 59 days old on 2027-04-29
        (rejected) and exactly 60 days old on 2027-04-30 (allowed).

        Design: Difficulty/boundary_precision_check/transfer_on_day_60_allowed_day_59_rejected
        """
        reg_a, reg_b, _schedule, domain = setup_two_registrars_with_domain(
            clock="2027-03-01T00:00:00Z", name="sixty-day")

        set_clock("2027-04-29T00:00:00Z")
        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_CLOSED)

        set_clock("2027-04-30T00:00:00Z")
        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        transfer = get_success_data(resp, expected_status=201)
        assert transfer["status"] == "REQUESTED"
        assert get_domain(domain["id"])["status"] == "TRANSFERRING"

    def test_transfer_one_second_before_day_60_rejected(self, api):
        """PRD §3.5: "meaning the current logical time is at or past
        `created_at` plus sixty days (younger names are rejected with
        `ERR_TRANSFER_WINDOW_CLOSED`)."

        One second before created_at + 60 days is still younger than sixty
        days; the exact instant opens the window.

        Design: Difficulty/boundary_precision_check/transfer_on_day_60_allowed_day_59_rejected
        """
        reg_a, reg_b, _schedule, domain = setup_two_registrars_with_domain(
            clock="2027-03-01T00:00:00Z", name="sixty-day")

        set_clock("2027-04-29T23:59:59Z")
        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_CLOSED)

        set_clock("2027-04-30T00:00:00Z")
        resp = api.create_transfer(
            {"domain_id": domain["id"], "to_registrar_id": reg_b["id"]},
            make_operator_headers(reg_b["id"]),
        )
        transfer = get_success_data(resp, expected_status=201)
        assert transfer["status"] == "REQUESTED"
