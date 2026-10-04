"""Optimistic concurrency control tests (PRD §2.8)."""
from test_helpers import (
    ApiErrorId,
    get_domain,
    get_registrar,
    get_success_data,
    make_admin_headers,
    make_operator_headers,
    setup_active_domain,
    setup_active_registrar,
    validate_error,
)


class TestRegistrarPatchOcc:
    def test_stale_version_after_first_patch_rejected(self, api):
        """PRD §2.8: "Patching a registrar's mutable fields requires a
        non-optional `expected_registrar_version` carrying the client's last
        observed `version` of that registrar; if the registrar's current
        `version` has advanced — for instance, another writer has flipped
        `credit_hold` since the client read the record — the patch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "A successful OCC-guarded mutation increments the parent
        entity's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_registrar_version_rejected_with_412
        """
        resp = api.create_registrar(
            {
                "iana_number": 9150,
                "legal_name": "OCC Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        observed_version = registrar["version"]
        legal_name_before = registrar["legal_name"]

        resp = api.patch_registrar(
            registrar["id"],
            {"expected_registrar_version": observed_version,
             "credit_hold": True},
            make_admin_headers(),
        )
        patched = get_success_data(resp)
        assert patched["version"] == observed_version + 1
        assert patched["credit_hold"] is True

        resp = api.patch_registrar(
            registrar["id"],
            {"expected_registrar_version": observed_version,
             "legal_name": "OCC Registrar Renamed"},
            make_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        current = get_registrar(registrar["id"])
        assert current["legal_name"] == legal_name_before, (
            "the rejected PATCH must not mutate the registrar"
        )
        assert current["version"] == observed_version + 1

    def test_patch_with_fresh_version_succeeds(self, api):
        """PRD §2.8: "Patching a registrar's mutable fields requires a
        non-optional `expected_registrar_version` carrying the client's last
        observed `version` of that registrar; if the registrar's current
        `version` has advanced — for instance, another writer has flipped
        `credit_hold` since the client read the record — the patch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "A successful OCC-guarded mutation increments the parent
        entity's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_registrar_version_rejected_with_412
        """
        resp = api.create_registrar(
            {
                "iana_number": 9150,
                "legal_name": "OCC Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)

        resp = api.patch_registrar(
            registrar["id"],
            {"expected_registrar_version": registrar["version"],
             "legal_name": "OCC Registrar Renamed"},
            make_admin_headers(),
        )
        patched = get_success_data(resp)
        assert patched["legal_name"] == "OCC Registrar Renamed"
        assert patched["version"] == registrar["version"] + 1

        # A stale replay of the original version now fails.
        resp = api.patch_registrar(
            registrar["id"],
            {"expected_registrar_version": registrar["version"],
             "legal_name": "OCC Registrar Twice Renamed"},
            make_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_registrar(registrar["id"])["legal_name"] == (
            "OCC Registrar Renamed"
        )


class TestDomainLockOcc:
    def test_stale_domain_version_on_lock_rejected(self, api):
        """PRD §2.8: "Engaging or releasing a lock on a domain requires a
        non-optional `expected_domain_version` carrying the client's last
        observed `version` of that domain; a mismatch against the domain's
        current `version` — for instance, after a cascaded lifecycle mutation
        bumped it — is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_domain_version_on_lock_rejected_with_412
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-01T00:00:00Z", name="occ-domain")
        headers = make_operator_headers(registrar["id"])
        observed_version = domain["version"]

        # A lifecycle mutation bumps Domain.version as a side effect.
        resp = api.renew_domain(domain["id"], 1, headers)
        get_success_data(resp)

        resp = api.lock_domain(
            domain["id"],
            {"lock_action": "CLIENT_LOCK",
             "expected_domain_version": observed_version},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_domain(domain["id"])["lock_status"] == "NONE"

    def test_lock_with_fresh_version_succeeds_and_bumps(self, api):
        """PRD §2.8: "Engaging or releasing a lock on a domain requires a
        non-optional `expected_domain_version` carrying the client's last
        observed `version` of that domain; a mismatch against the domain's
        current `version` — for instance, after a cascaded lifecycle mutation
        bumped it — is likewise rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §2.8: "A successful OCC-guarded mutation increments the parent
        entity's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_domain_version_on_lock_rejected_with_412
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-01T00:00:00Z", name="occ-domain")
        headers = make_operator_headers(registrar["id"])

        resp = api.lock_domain(
            domain["id"],
            {"lock_action": "CLIENT_LOCK",
             "expected_domain_version": domain["version"]},
            headers,
        )
        locked = get_success_data(resp)
        assert locked["lock_status"] == "CLIENT_LOCK"
        assert locked["version"] == domain["version"] + 1

        # Replaying the pre-lock version is now stale.
        resp = api.lock_domain(
            domain["id"],
            {"lock_action": "NONE",
             "expected_domain_version": domain["version"]},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_domain(domain["id"])["lock_status"] == "CLIENT_LOCK"
