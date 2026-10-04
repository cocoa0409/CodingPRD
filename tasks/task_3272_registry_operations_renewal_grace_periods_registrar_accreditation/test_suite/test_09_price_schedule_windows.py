"""Price-schedule effectiveness windows and notice fan-out (PRD §2.7, §3.7)."""
from test_helpers import (
    get_success_data,
    make_admin_headers,
    make_finance_headers,
    make_operator_headers,
    set_clock,
    validate_paginated,
)


class TestEffectivenessWindowBoundary:
    def test_boundary_instant_belongs_to_new_schedule(self, api):
        """PRD §2.7: "A schedule is born `PROPOSED`, becomes `EFFECTIVE` when
        the logical clock reaches `effective_on`, and becomes `SUPERSEDED`
        when a later schedule takes effect; the previously `EFFECTIVE`
        schedule flips to `SUPERSEDED` at the same instant."
        PRD §3.3: "The effective schedule used by every lifecycle invoice is
        the `PriceSchedule` whose status is `EFFECTIVE` at the invoice-minting
        instant — the one with the greatest `effective_on` at or before that
        instant among effective rows".

        Design: Difficulty/resource_temporal_overlap/price_schedule_effectiveness_windows_partition_time
        """
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 700,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-03-01T00:00:00Z",
            },
            make_admin_headers(),
        )
        s1 = get_success_data(resp, expected_status=201)
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 750,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-12-31T00:00:00Z",
                "supersedes_schedule_id": s1["id"],
            },
            make_admin_headers(),
        )
        s2 = get_success_data(resp, expected_status=201)
        resp = api.create_registrar(
            {
                "iana_number": 8604,
                "legal_name": "Window Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        get_success_data(
            api.accredit_registrar(registrar["id"], make_admin_headers()))
        set_clock("2027-03-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])

        set_clock("2027-12-30T23:59:59Z")
        resp = api.create_domain(
            {"name": "before-boundary", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        dom_before = get_success_data(resp, expected_status=201)

        set_clock("2027-12-31T00:00:00Z")
        resp = api.create_domain(
            {"name": "at-boundary", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        dom_at = get_success_data(resp, expected_status=201)

        resp = api.list_invoices(
            make_finance_headers(),
            params={"domain_id": dom_before["id"], "kind": "CREATE"},
        )
        rows, _meta = validate_paginated(resp)
        assert len(rows) == 1
        assert rows[0]["price_schedule_id"] == s1["id"]
        assert rows[0]["base_cents"] == 700

        resp = api.list_invoices(
            make_finance_headers(),
            params={"domain_id": dom_at["id"], "kind": "CREATE"},
        )
        rows, _meta = validate_paginated(resp)
        assert len(rows) == 1
        assert rows[0]["price_schedule_id"] == s2["id"]
        assert rows[0]["base_cents"] == 750

        s1_after = get_success_data(
            api.get_price_schedule(s1["id"], make_admin_headers()))
        s2_after = get_success_data(
            api.get_price_schedule(s2["id"], make_admin_headers()))
        assert s1_after["status"] == "SUPERSEDED"
        assert s2_after["status"] == "EFFECTIVE"

    def test_window_before_boundary_uses_old_schedule(self, api):
        """PRD §3.3: "The effective schedule used by every lifecycle invoice
        is the `PriceSchedule` whose status is `EFFECTIVE` at the
        invoice-minting instant — the one with the greatest `effective_on` at
        or before that instant among effective rows".
        PRD §2.7: "A schedule is born `PROPOSED`, becomes `EFFECTIVE` when
        the logical clock reaches `effective_on`".

        Design: Difficulty/resource_temporal_overlap/price_schedule_effectiveness_windows_partition_time
        """
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 700,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-03-01T00:00:00Z",
            },
            make_admin_headers(),
        )
        s1 = get_success_data(resp, expected_status=201)
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 750,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-12-31T00:00:00Z",
                "supersedes_schedule_id": s1["id"],
            },
            make_admin_headers(),
        )
        s2 = get_success_data(resp, expected_status=201)
        resp = api.create_registrar(
            {
                "iana_number": 8604,
                "legal_name": "Window Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        get_success_data(
            api.accredit_registrar(registrar["id"], make_admin_headers()))
        set_clock("2027-03-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])

        # One second before the new window opens: the old schedule still
        # prices the invoice.
        set_clock("2027-12-30T23:59:59Z")
        resp = api.create_domain(
            {"name": "just-before", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        dom = get_success_data(resp, expected_status=201)
        resp = api.list_invoices(
            make_finance_headers(),
            params={"domain_id": dom["id"], "kind": "CREATE"},
        )
        rows, _meta = validate_paginated(resp)
        assert rows[0]["price_schedule_id"] == s1["id"]
        assert rows[0]["base_cents"] == 700

        # At the boundary the new schedule takes over (and only then).
        s2_now = get_success_data(
            api.get_price_schedule(s2["id"], make_admin_headers()))
        assert s2_now["status"] == "PROPOSED"
        set_clock("2027-12-31T00:00:00Z")
        s2_now = get_success_data(
            api.get_price_schedule(s2["id"], make_admin_headers()))
        assert s2_now["status"] == "EFFECTIVE"


class TestPriceIncreaseNotices:
    def test_announced_and_effective_notices_emitted(self, api):
        """PRD §3.7: "A schedule that passes both gates is stored as
        `PROPOSED`, and the registry immediately emits a
        `PRICE_INCREASE_ANNOUNCED` notice to every registrar in `ACTIVE` or
        `SUSPENDED` status, recording the announced `price_schedule_id` and
        the logical-clock `sent_at` on each notice."
        PRD §3.7: "When the logical clock reaches a proposed schedule's
        `effective_on`, the schedule becomes `EFFECTIVE`, the schedule it
        replaces becomes `SUPERSEDED`, and the registry emits
        `PRICE_INCREASE_EFFECTIVE` notices — but only to `ACTIVE` or
        `SUSPENDED` registrars whose `accredited_version` is less than the
        new schedule's `version`."

        Design: Corner/cross_cutting_complexity_layers/price_increase_notice_emitted_and_version_pinned
        """
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 700,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-03-01T00:00:00Z",
            },
            make_admin_headers(),
        )
        s1 = get_success_data(resp, expected_status=201)
        resp = api.create_registrar(
            {
                "iana_number": 9152,
                "legal_name": "Notice Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        accredited = get_success_data(resp)
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 750,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-12-31T00:00:00Z",
                "supersedes_schedule_id": s1["id"],
            },
            make_admin_headers(),
        )
        s2 = get_success_data(resp, expected_status=201)

        set_clock("2027-12-31T00:00:00Z")
        s1_after = get_success_data(
            api.get_price_schedule(s1["id"], make_admin_headers()))
        s2_after = get_success_data(
            api.get_price_schedule(s2["id"], make_admin_headers()))
        assert s1_after["status"] == "SUPERSEDED"
        assert s2_after["status"] == "EFFECTIVE"

        resp = api.list_registrar_accreditation_notices(
            registrar["id"], make_admin_headers())
        rows, _meta = validate_paginated(resp)
        kinds_for_s2 = sorted(
            n["notice_kind"] for n in rows
            if n["price_schedule_id"] == s2["id"]
        )
        assert kinds_for_s2 == [
            "PRICE_INCREASE_ANNOUNCED", "PRICE_INCREASE_EFFECTIVE"], (
            f"expected both ANNOUNCED and EFFECTIVE notices, got "
            f"{kinds_for_s2}"
        )
        effective_notice = next(
            n for n in rows
            if n["price_schedule_id"] == s2["id"]
            and n["notice_kind"] == "PRICE_INCREASE_EFFECTIVE"
        )
        assert effective_notice["sent_at"] == "2027-12-31T00:00:00.000Z"
