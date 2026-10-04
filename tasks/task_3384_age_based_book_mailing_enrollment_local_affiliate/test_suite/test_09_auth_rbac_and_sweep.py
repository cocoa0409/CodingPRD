"""Authentication, role authorization, entity-specific 404s, uniqueness
constraints, and the logical-clock sweep (PRD §2.1, §2.4, §2.8, §3)."""
import pytest

from test_helpers import (
    ACM_APPROVER_ID,
    ACM_PROPOSER_ID,
    AgreementStatus,
    ApiErrorId,
    BOGUS_UUID,
    EnrollmentStatus,
    TEST_USERS,
    api_client,
    assert_clock_response,
    create_affiliate,
    create_affiliate_payload,
    create_agreement,
    create_child_payload,
    create_population_stat_payload,
    create_print_order,
    create_selection_payload,
    create_state_program,
    create_title,
    create_wave,
    create_wave_payload,
    decide_address_change_payload,
    get_affiliate,
    get_child,
    make_advisory_committee_member_headers,
    make_affiliate_coordinator_headers,
    propose_selection,
    register_child,
    set_clock_payload,
    set_logical_clock,
    setup_approved_selection,
    setup_operative_affiliate,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_MAIL_OPS = TEST_USERS["mail_ops_headers"]
_PUBLISHER = TEST_USERS["publisher_ops_headers"]


class TestErrorCatalog:
    def test_entity_specific_not_found_errors(self, api):
        """PRD §2.8: "identifiers in the URL are resolved strictly left to
        right; the first identifier that does not exist yields that entity's
        specific 404. The entity-specific not-found codes are
        `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_AFFILIATE_NOT_FOUND`,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_CHILD_NOT_FOUND`,
        `ERR_ADDRESS_CHANGE_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`,
        `ERR_SELECTION_NOT_FOUND`, `ERR_PRINT_ORDER_NOT_FOUND`,
        `ERR_WAVE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, and
        `ERR_INVOICE_NOT_FOUND`."
        PRD §3.1: the affiliate's `state_program_id` is "a reference that must
        resolve, else `ERR_STATE_PROGRAM_NOT_FOUND`".

        Design: Corner/errors/entity_specific_not_found_errors
        """
        set_logical_clock()
        program = create_state_program()
        affiliate = create_affiliate(program["id"])
        probes = [
            (
                api.get_title(BOGUS_UUID, _ADMIN),
                ApiErrorId.ERR_TITLE_NOT_FOUND,
            ),
            (
                api.get_print_order(BOGUS_UUID, _ADMIN),
                ApiErrorId.ERR_PRINT_ORDER_NOT_FOUND,
            ),
            (
                api.manifest_wave(BOGUS_UUID, _MAIL_OPS),
                ApiErrorId.ERR_WAVE_NOT_FOUND,
            ),
            (
                api.mark_item_returned(BOGUS_UUID, _MAIL_OPS),
                ApiErrorId.ERR_ITEM_NOT_FOUND,
            ),
            (
                api.issue_invoice(BOGUS_UUID, _ADMIN),
                ApiErrorId.ERR_INVOICE_NOT_FOUND,
            ),
            (
                api.decide_address_change(
                    BOGUS_UUID,
                    decide_address_change_payload("APPROVE"),
                    make_affiliate_coordinator_headers(affiliate["id"]),
                ),
                ApiErrorId.ERR_ADDRESS_CHANGE_NOT_FOUND,
            ),
            (
                api.get_affiliate(BOGUS_UUID, _ADMIN),
                ApiErrorId.ERR_AFFILIATE_NOT_FOUND,
            ),
            (
                api.create_affiliate(
                    create_affiliate_payload(
                        BOGUS_UUID,
                        name="Ghost Affiliate",
                        postal_prefixes=["372"],
                        contact_email="g@g.org",
                    ),
                    _ADMIN,
                ),
                ApiErrorId.ERR_STATE_PROGRAM_NOT_FOUND,
            ),
        ]
        for response, error_id in probes:
            validate_error(response, error_id)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        outside this set, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_affiliates({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_rbac_exclusive_operation_denials(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_FORBIDDEN`."
        PRD §4: child registration lists only `AffiliateCoordinator`;
        agreement approval lists only `StateProgramOfficer`; the clock lists
        only `PlatformAdmin`; print-order confirmation lists only
        `PublisherOps`.

        Design: Corner/rbac/rbac_exclusive_operation_denials
        """
        base = setup_operative_affiliate()
        program, affiliate = base["program"], base["affiliate"]
        title = create_title("INFANT")
        selection = setup_approved_selection("2026-10", "INFANT", title_id=title["id"])[
            "selection"
        ]
        order = create_print_order(selection["id"])
        # A committee member cannot register children.
        resp = api.create_child(
            create_child_payload(
                affiliate["id"],
                full_name="Role Test",
                family_name="Test",
                birth_date="2026-03-01T00:00:00Z",
            ),
            make_advisory_committee_member_headers(ACM_PROPOSER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        # A coordinator cannot approve agreements.
        agreement = create_agreement(
            get_affiliate(affiliate["id"]),
            effective_from="2028-01-01T00:00:00Z",
            effective_to="2029-01-01T00:00:00Z",
            local_fundraising_commitment_cents=100,
        )
        resp = api.approve_agreement(
            agreement["id"], make_affiliate_coordinator_headers(affiliate["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        # PublisherOps cannot drive the logical clock.
        resp = api.set_clock(set_clock_payload("2026-10-01T00:00:00Z"), _PUBLISHER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        # MailOps cannot confirm print orders.
        resp = api.confirm_print_order(order["id"], _MAIL_OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestUniquenessConstraints:
    def test_duplicate_constraint_errors(self, api):
        """PRD §3.5: "the pair of month and band must be unique, since a
        second selection for a slot that already has one is
        `ERR_SELECTION_EXISTS`".
        PRD §3.7: "Scheduling a wave takes only a `mailing_month`, which must
        be unique across waves (else `ERR_WAVE_MONTH_DUPLICATE`)".
        PRD §3.1: "One stat per affiliate per year: a second estimate for a
        year that already has one is rejected with
        `ERR_POPULATION_YEAR_DUPLICATE`."

        Design: Corner/validations/duplicate_constraint_errors
        """
        base = setup_operative_affiliate(population_stat={})
        affiliate = base["affiliate"]
        title = create_title("INFANT")
        propose_selection("2026-10", "INFANT", title["id"])
        create_wave("2026-10")
        resp = api.create_selection(
            create_selection_payload("2026-10", "INFANT", title["id"]),
            make_advisory_committee_member_headers(ACM_APPROVER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_SELECTION_EXISTS)
        resp = api.create_wave(create_wave_payload("2026-10"), _MAIL_OPS)
        validate_error(resp, ApiErrorId.ERR_WAVE_MONTH_DUPLICATE)
        resp = api.create_population_stat(
            affiliate["id"],
            create_population_stat_payload(eligible_population=12000),
            make_affiliate_coordinator_headers(affiliate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_POPULATION_YEAR_DUPLICATE)


class TestClockSweep:
    def test_clock_sweep_graduates_children_and_expires_agreements(self, api):
        """PRD §2.4: "its response reports the new `current_utc` together with
        `graduated_child_ids` and `expired_agreement_ids`, the two lists of
        entities the sweep touched."
        PRD §3.3: "When the sweep finds the current logical month has moved
        beyond a child's `expected_final_mailing_month`, the child becomes
        `GRADUATED` and the affiliate's `enrolled_count` is recomputed."
        PRD §3.2: "When the logical clock advances to a date on or after an
        agreement's `effective_to`, the sweep moves that agreement from
        `ACTIVE` to `EXPIRED` and recomputes the affiliate's `operative`,
        which may drop to false".

        Design: Corner/state_machines/clock_sweep_graduates_children_and_expires_agreements
        """
        base = setup_operative_affiliate(
            affiliate_overrides={
                "name": "Rural County Books",
                "postal_prefixes": ["375"],
                "contact_email": "coord@rcb.org",
            },
            agreement_overrides={"effective_to": "2026-11-01T00:00:00Z"},
        )
        affiliate, agreement = base["affiliate"], base["agreement"]
        kid = register_child(
            affiliate["id"],
            full_name="Sixty Mo",
            family_name="Mo",
            birth_date="2021-10-15T00:00:00Z",
            mailing_address={
                "line1": "1 Rural Rt", "city": "Crossville", "region": "TN",
                "postal_code": "37501", "country": "US",
            },
        )
        sweep = set_logical_clock("2026-11-01T00:00:00Z")
        assert_clock_response(sweep)
        assert kid["id"] in sweep["graduated_child_ids"], (
            "age 59 at registration; the month past 2026-09 (the birth month "
            "plus fifty-nine months) graduates the child"
        )
        assert agreement["id"] in sweep["expired_agreement_ids"], (
            "2026-11-01 is on the agreement's effective_to"
        )
        assert get_child(kid["id"])["enrollment_status"] == (
            EnrollmentStatus.GRADUATED.value
        )
        rows, _meta = validate_paginated(api.list_agreements(affiliate["id"], _ADMIN))
        assert rows[0]["status"] == AgreementStatus.EXPIRED.value
        after = get_affiliate(affiliate["id"])
        assert after["operative"] is False
        assert after["enrolled_count"] == 0
