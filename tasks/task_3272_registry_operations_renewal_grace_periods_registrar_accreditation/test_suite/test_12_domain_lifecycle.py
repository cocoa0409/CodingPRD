"""Domain lifecycle corner tests (PRD §2.9, §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_domain_nameserver_link,
    find_invoice,
    get_domain,
    get_success_data,
    list_invoices,
    make_admin_headers,
    make_operator_headers,
    set_clock,
    setup_active_domain,
    setup_active_registrar,
    validate_error,
    validate_paginated,
)


class TestDomainRequiredFields:
    def test_missing_years_returns_invalid_request(self, api):
        """PRD §2.9: "A malformed body or a missing required input field is
        rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "A `RegistrarOperator` registers a second-level domain by
        supplying its `name`, the sponsoring `registrar_id`, an initial
        `years` term, and an optional `premium` flag (defaulting to false)."

        Design: Corner/entities/domain_create_missing_years_returns_invalid_request
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-04-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])

        resp = api.create_domain(
            {"name": "missing-years", "registrar_id": registrar["id"]},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api.list_domains(
            make_admin_headers(), params={"registrar_id": registrar["id"]})
        rows, _meta = validate_paginated(resp)
        assert rows == []


class TestDomainPremiumDefault:
    def test_omitting_premium_defaults_false_and_no_surcharge(self, api):
        """PRD §3.2: "A `RegistrarOperator` registers a second-level domain
        by supplying its `name`, the sponsoring `registrar_id`, an initial
        `years` term, and an optional `premium` flag (defaulting to false)."
        PRD §2.6: "Non-premium domains and all accreditation invoices carry a
        surcharge of zero."

        Design: Corner/entities/domain_create_omitting_premium_defaults_false_and_no_surcharge
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-04-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])

        resp = api.create_domain(
            {"name": "default-premium", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        domain = get_success_data(resp, expected_status=201)
        assert domain["premium"] is False

        invoice = find_invoice(domain_id=domain["id"], kind="CREATE")
        assert invoice["base_cents"] == 700
        assert invoice["premium_surcharge_cents"] == 0
        assert invoice["total_cents"] == 700


class TestDomainNameUniqueness:
    def test_name_uniqueness_excludes_deleted_rows(self, api):
        """PRD §3.2: "The `name` must be unique among all non-`DELETED`
        domains — a clash is rejected with `ERR_DOMAIN_NAME_TAKEN`".
        PRD §3.2: "When a name is eventually purged from `DELETED`, the
        uniqueness constraint no longer sees it, so the same `name` may be
        registered again by anyone."

        Design: Corner/entities/domain_name_uniqueness_excludes_deleted_rows
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-03-15T00:00:00Z", name="recyclable")
        headers = make_operator_headers(registrar["id"])

        resp = api.create_domain(
            {"name": "recyclable", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DOMAIN_NAME_TAKEN)

        # ACTIVE -> REDEMPTION_GRACE at 2026-01-15; PENDING_DELETE after 30
        # days (2026-02-14); DELETED after 35 days (2026-02-19).
        get_success_data(api.delete_domain(domain["id"], headers))
        set_clock("2027-04-20T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "DELETED"

        resp = api.create_domain(
            {"name": "recyclable", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        recycled = get_success_data(resp, expected_status=201)
        assert recycled["id"] != domain["id"]


class TestNameserverLinkImmutability:
    def test_link_carries_no_version_or_updated_at(self, api):
        """PRD §2.4: "Two resource types are intentionally lighter.
        `DomainNameserverLink` and `RegistrarAccreditationNotice` carry only
        `id` and `created_at`; both `updated_at` and `version` are absent
        from them, and they are never the target of OCC checks."
        PRD §3.4: "A `RegistrarOperator` links a nameserver to a domain they
        sponsor by submitting the `nameserver_id`; the resulting
        `DomainNameserverLink` records the `domain_id` and `nameserver_id`
        pair, and links are listable per domain or filterable globally by
        `domain_id` or `nameserver_id`."

        Design: Corner/entities/domain_nameserver_link_is_immutable_no_version
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-01T00:00:00Z", name="link-domain")
        resp = api.create_nameserver(
            {"hostname": "ns1.link-domain.example",
             "ip_addresses": ["192.0.2.1"], "capacity_qps": 3000},
            make_admin_headers(),
        )
        nameserver = get_success_data(resp, expected_status=201)

        resp = api.link_nameserver(
            domain["id"], nameserver["id"],
            make_operator_headers(registrar["id"]),
        )
        link = get_success_data(resp, expected_status=201)
        assert_domain_nameserver_link(link)
        assert link["domain_id"] == domain["id"]
        assert link["nameserver_id"] == nameserver["id"]

        resp = api.list_domain_nameservers(domain["id"], make_admin_headers())
        rows, _meta = validate_paginated(resp)
        assert len(rows) == 1
        assert rows[0]["id"] == link["id"]


class TestPendingDeleteLockdown:
    def test_renew_and_restore_from_pending_delete_invalid_state(self, api):
        """PRD §2.9: "Only then does the system evaluate whether the target
        resource is in a state from which the requested transition exists
        (`ERR_INVALID_STATE`)".
        PRD §3.3: "If thirty days pass with no restore, the domain enters
        `PENDING_DELETE` and `delete_scheduled_on` is set to the date
        thirty-five days after redemption entry; five days later — that is,
        once the clock passes thirty-five days past redemption entry — the
        name is purged to `DELETED`".

        Design: Corner/state_machines/renew_from_pending_delete_is_invalid_state_terminal_lockdown
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-03-15T00:00:00Z", name="terminal-domain")
        headers = make_operator_headers(registrar["id"])
        invoices_before = len(list_invoices(domain_id=domain["id"]))

        # ACTIVE -> REDEMPTION_GRACE at 2026-01-15; +30 days -> PENDING_DELETE
        # at 2026-02-14; observe from 2026-02-16.
        get_success_data(api.delete_domain(domain["id"], headers))
        set_clock("2027-04-15T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "PENDING_DELETE"

        resp = api.renew_domain(domain["id"], 1, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        resp = api.restore_domain(domain["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_domain(domain["id"])
        assert after["status"] == "PENDING_DELETE"
        assert len(list_invoices(domain_id=domain["id"])) == invoices_before

    def test_deleted_domain_accepts_no_transitions(self, api):
        """PRD §3.3: "once the clock passes thirty-five days past redemption
        entry — the name is purged to `DELETED`, its uniqueness constraint
        lapses, and the label becomes available for fresh registration."
        PRD §2.9: "Only then does the system evaluate whether the target
        resource is in a state from which the requested transition exists
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/renew_from_pending_delete_is_invalid_state_terminal_lockdown
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-03-15T00:00:00Z", name="terminal-domain")
        headers = make_operator_headers(registrar["id"])

        get_success_data(api.delete_domain(domain["id"], headers))
        set_clock("2027-04-20T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "DELETED"

        resp = api.renew_domain(domain["id"], 1, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        resp = api.restore_domain(domain["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_domain(domain["id"])["status"] == "DELETED"
