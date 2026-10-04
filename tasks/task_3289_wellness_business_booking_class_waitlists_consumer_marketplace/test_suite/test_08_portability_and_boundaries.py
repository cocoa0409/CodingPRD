"""Client portability, the export lifecycle and the OCC / RBAC boundaries."""
import pytest

from test_helpers import (
    ADMIN,
    ANONYMOUS,
    ApiErrorId,
    OPERATOR,
    TEST_USERS,
    create_client,
    create_payroll_period,
    create_session,
    create_staff,
    create_template,
    ensure_tier,
    get_success_data,
    make_client_headers,
    make_studio_owner_headers,
    set_clock,
    setup_studio_roster,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, create_studio


class TestPortabilityDecisionLockdown:

    def test_withdrawing_an_already_decided_request_is_refused(self, api):
        """PRD §3.10: "Attempting an objection, a release or a denial against a request that already carries a decision is refused with `ERR_PORTABILITY_ALREADY_DECIDED`."

        Design: Corner/state_machines/withdrawing_an_already_decided_portability_request_returns_already_decided
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Loft")
        owner = make_studio_owner_headers(studio["id"])
        maya = create_client(studio["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        request = validate_success(api.create_portability_request({
            "studio_id": studio["id"], "requesting_client_id": maya["id"],
            "dispute_reason": "relocating"}, make_client_headers(maya["id"])),
            expected_status=201)
        denied = validate_success(api.resolve_portability_deny(
            request["id"], {"dispute_reason": "outstanding contract term"}, owner))
        assert denied["status"] == "RESOLVED_DENIED"

        validate_error(api.withdraw_portability_request(
            request["id"], make_client_headers(maya["id"])),
            ApiErrorId.ERR_PORTABILITY_ALREADY_DECIDED)

        after = validate_success(api.get_portability_request(request["id"], owner))
        assert after["status"] == "RESOLVED_DENIED"
        assert validate_success(api.get_studio(studio["id"], owner))[
            "data_ownership_state"] == "OWNED"

    def test_a_denial_returns_the_studio_ownership_state_to_owned(self, api):
        """PRD §3.10: "Denial is the studio's other option and it requires a basis: a denial is admitted while the request is `PENDING` and only when `dispute_reason` is non-empty; it moves the request to `RESOLVED_DENIED` and returns the studio's `data_ownership_state` to `OWNED`."

        Design: Corner/state_machines/withdrawing_an_already_decided_portability_request_returns_already_decided
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Loft")
        owner = make_studio_owner_headers(studio["id"])
        maya = create_client(studio["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        request = validate_success(api.create_portability_request({
            "studio_id": studio["id"], "requesting_client_id": maya["id"],
            "dispute_reason": "relocating"}, make_client_headers(maya["id"])),
            expected_status=201)
        pending_studio = validate_success(api.get_studio(studio["id"], owner))
        assert pending_studio["data_ownership_state"] == "PORTABILITY_PENDING"

        validate_success(api.resolve_portability_deny(
            request["id"], {"dispute_reason": "unserved contract term"}, owner))
        after = validate_success(api.get_studio(studio["id"], owner))
        assert after["data_ownership_state"] == "OWNED"


class TestExportLifecycle:

    def test_export_lapse_returns_the_grant_for_a_second_issue(self, api):
        """PRD §3.10: "If the export window lapses on a request that was issued but never downloaded a single time — the download count is still zero — the system moves the request from `EXPORT_ISSUED` back to `RESOLVED_RELEASE` and clears the `export_grant_id` and the `export_manifest`, so the export can be generated again; this is the cycle edge."

        Design: Difficulty/non_linear_state_machine/portability_export_lapse_returns_the_grant_for_a_second_issue
        """
        ensure_tier("ENTERPRISE")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Collective", tier="ENTERPRISE")
        owner = make_studio_owner_headers(studio["id"])
        maya = create_client(studio["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        request = validate_success(api.create_portability_request({
            "studio_id": studio["id"], "requesting_client_id": maya["id"],
            "dispute_reason": "moving to a competing studio"},
            make_client_headers(maya["id"])), expected_status=201)
        released = validate_success(api.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            owner))
        assert released["status"] == "RESOLVED_RELEASE"
        original_grant = released["export_grant_id"]
        assert original_grant, "the release mints a grant id"

        issued = validate_success(api.issue_portability_export(
            request["id"],
            {"expected_portability_request_version": released["version"]}, ADMIN))
        assert issued["status"] == "EXPORT_ISSUED"

        # The export window is 72 hours; a clock position five days out lapses
        # an export that was never downloaded.  The lapse is a system
        # transition that advances the request row, so the re-issue must
        # present the freshly observed version rather than the pre-lapse one.
        set_clock("2026-06-05T00:00:00Z")
        lapsed = validate_success(api.get_portability_request(request["id"], ADMIN))
        assert lapsed["status"] == "RESOLVED_RELEASE", \
            "the lapsed export is walked back to RESOLVED_RELEASE"
        reissued = validate_success(api.issue_portability_export(
            request["id"],
            {"expected_portability_request_version": lapsed["version"]}, ADMIN))
        assert reissued["status"] == "EXPORT_ISSUED", \
            "the re-issue succeeds rather than raising ERR_EXPORT_NOT_GRANTED"
        assert reissued["export_grant_id"] != original_grant, \
            "the re-issued grant id differs from the original"

    def test_issuing_while_not_granted_is_refused(self, api):
        """PRD §3.10: "It is refused with `ERR_EXPORT_NOT_GRANTED` while the request is not in `RESOLVED_RELEASE` — and that refusal is the mechanism of the cycle, because an `EXPORT_ISSUED` row whose export window lapsed must be walked back to `RESOLVED_RELEASE` before it can be issued again."

        Design: Difficulty/non_linear_state_machine/portability_export_lapse_returns_the_grant_for_a_second_issue
        """
        ensure_tier("ENTERPRISE")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Collective", tier="ENTERPRISE")
        owner = make_studio_owner_headers(studio["id"])
        maya = create_client(studio["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        request = validate_success(api.create_portability_request({
            "studio_id": studio["id"], "requesting_client_id": maya["id"],
            "dispute_reason": "relocating"},
            make_client_headers(maya["id"])), expected_status=201)

        # Still PENDING: no grant exists yet.
        validate_error(api.issue_portability_export(
            request["id"],
            {"expected_portability_request_version": request["version"]}, ADMIN),
            ApiErrorId.ERR_EXPORT_NOT_GRANTED)

    def test_a_release_with_an_outstanding_balance_is_refused(self, api):
        """PRD §3.10: "An explicit release is admitted while the request is
        PENDING and requires that the requesting client's outstanding_fee_cents
        is exactly zero — a release attempted while the client still owes fees is
        refused with ERR_CLIENT_BALANCE_OUTSTANDING."

        Design: Corner/rbac/a_studio_owner_cannot_issue_a_portability_export
        """
        from test_helpers import book
        ensure_tier("GROWTH")
        set_clock("2026-06-19T04:00:00Z")
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        booking = book(maya["id"], ctx["session"]["id"])
        set_clock("2026-06-20T06:00:00Z")
        get_success_data(api.cancel_booking(
            booking["id"], {"reason": "overslept"}, make_client_headers(maya["id"])))
        owing = validate_success(api.get_client(maya["id"], ctx["owner"]))
        assert owing["outstanding_fee_cents"] == 3360

        request = validate_success(api.create_portability_request({
            "studio_id": ctx["studio"]["id"], "requesting_client_id": maya["id"],
            "dispute_reason": "relocating"}, make_client_headers(maya["id"])),
            expected_status=201)
        validate_error(api.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            ctx["owner"]), ApiErrorId.ERR_CLIENT_BALANCE_OUTSTANDING)


class TestPortabilityRbac:

    def test_a_studio_owner_cannot_issue_a_portability_export(self, api):
        """PRD §2.1: "A request whose role is not one of the roles admitted by the target operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "PlatformAdmin` is the marketplace operator: it configures tiers and benefit networks, adjudicates portability disputes, issues exports, and may override any studio-scoped operation."

        Design: Corner/rbac/a_studio_owner_cannot_issue_a_portability_export
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Stillwater Studio", home_state_code="CO")
        owner = make_studio_owner_headers(studio["id"])
        maya = create_client(studio["id"], display_name="Maya Alvarez",
                             email="maya@example.com", home_state_code="CO")
        request = validate_success(api.create_portability_request({
            "studio_id": studio["id"], "requesting_client_id": maya["id"],
            "dispute_reason": "relocating"}, make_client_headers(maya["id"])),
            expected_status=201)
        released = validate_success(api.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            owner))

        validate_error(api.issue_portability_export(
            request["id"],
            {"expected_portability_request_version": released["version"]}, owner),
            ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        still = validate_success(api.get_portability_request(request["id"], owner))
        assert still["status"] == "RESOLVED_RELEASE"
        assert still["export_manifest"] is not None

        issued = validate_success(api.issue_portability_export(
            request["id"],
            {"expected_portability_request_version": still["version"]}, ADMIN))
        assert issued["status"] == "EXPORT_ISSUED", \
            "the identical call as PlatformAdmin succeeds"

    def test_an_anonymous_reader_cannot_read_a_studio_roster(self, api):
        """PRD §2.1: "Anonymous` is an unauthenticated marketplace browser that may read the tier catalogue, browse marketplace inventory, and sign a new studio up."

        Design: Corner/rbac/an_anonymous_reader_cannot_read_a_studio_roster
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Stillwater Studio", home_state_code="CO")
        create_client(studio["id"], display_name="Maya Alvarez",
                      email="maya@example.com", home_state_code="CO")

        validate_error(api.list_clients(ANONYMOUS, params={"home_studio_id": studio["id"]}),
                       ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        tiers = validate_success(api.list_subscription_tiers(ANONYMOUS))
        codes = [row["tier"] for row in (tiers if isinstance(tiers, list) else tiers.get("data", []))]
        assert "GROWTH" in codes, "the tier catalogue is readable while unauthenticated"

    def test_a_client_cannot_create_a_class_session(self, api):
        """PRD §2.5: "e_gates` map keyed as `marketplace_listing`, `staff_payroll`, `instructor_substitution`, `waitlist_auto_promotion`, `benefit_network_billing` and `client_portability_export`, whose boolean values are resolved from the effective tier's row pe"
        PRD §2.1: "A request whose role is not one of the roles admitted by the target operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/a_client_cannot_create_a_class_session
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-25T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")

        validate_error(api.create_class_session({
            "studio_id": ctx["studio"]["id"],
            "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-Z",
            "start_at": "2026-06-26T17:00:00Z", "capacity": 2,
            "expected_subscription_version": ctx["subscription_version"],
        }, make_client_headers(maya["id"])), ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        rows, meta = validate_paginated(api.list_class_sessions(
            ctx["owner"], params={"studio_id": ctx["studio"]["id"]}))
        assert meta["total_count"] == 1, \
            "only the fixture's own session exists; nothing was created"


class TestOptimisticConcurrency:

    def test_class_pack_create_with_a_stale_client_version_returns_412(self, api):
        """PRD §2.8: "Creating a class pack requires expected_client_version
        carrying the value of the target Client.version that the caller last
        observed; ... In both cases a value that does not match the parent
        entity's current version is rejected with ERR_STALE_VERSION (HTTP 412),
        and the write does not occur."

        Design: Corner/cross_cutting_complexity_layers/class_pack_create_with_a_stale_client_version_returns_412
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Stillwater Studio", home_state_code="CO")
        owner = make_studio_owner_headers(studio["id"])
        maya = create_client(studio["id"], display_name="Maya Alvarez",
                             email="maya@example.com", home_state_code="CO")

        first = validate_success(api.create_class_pack({
            "studio_id": studio["id"], "client_id": maya["id"], "pack_size": 5,
            "purchased_at": "2026-06-01T00:00:00Z", "expiry_scheme": "NONE",
            "expected_client_version": maya["version"],
        }, owner), expected_status=201)
        after_first = validate_success(api.get_client(maya["id"], owner))
        assert after_first["version"] == maya["version"] + 1

        second = validate_success(api.create_class_pack({
            "studio_id": studio["id"], "client_id": maya["id"], "pack_size": 5,
            "purchased_at": "2026-06-02T00:00:00Z", "expiry_scheme": "NONE",
            "expected_client_version": maya["version"] + 1,
        }, owner), expected_status=201)
        assert second["id"] != first["id"]

        # Replaying the pre-write version must be refused.
        validate_error(api.create_class_pack({
            "studio_id": studio["id"], "client_id": maya["id"], "pack_size": 5,
            "purchased_at": "2026-06-03T00:00:00Z", "expiry_scheme": "NONE",
            "expected_client_version": maya["version"] + 1,
        }, owner), ApiErrorId.ERR_STALE_VERSION)

        rows, meta = validate_paginated(api.list_class_packs(
            owner, params={"client_id": maya["id"]}))
        assert meta["total_count"] == 2, "the stale write created nothing"

    def test_class_session_create_with_a_stale_subscription_version_returns_412(self, api):
        """PRD §2.8: "Scheduling a class session requires the caller to supply
        expected_subscription_version carrying the value of the studio's
        BusinessSubscription.version that the caller last observed; ... a value
        that does not match the parent entity's current version is rejected with
        ERR_STALE_VERSION (HTTP 412), and the write does not occur."

        Design: Corner/cross_cutting_complexity_layers/class_session_create_with_a_stale_subscription_version_returns_412
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-20T17:00:00Z")

        second = validate_success(api.create_class_session({
            "studio_id": ctx["studio"]["id"],
            "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-B",
            "start_at": "2026-06-21T17:00:00Z", "capacity": 2,
            "expected_subscription_version": ctx["subscription_version"],
        }, ctx["owner"]), expected_status=201)
        assert second["id"]

        after = validate_success(api.get_subscription(ctx["studio"]["subscription_id"],
                                                       ADMIN))
        assert after["version"] > ctx["subscription_version"], \
            "the session create advanced the guarded subscription version"

        validate_error(api.create_class_session({
            "studio_id": ctx["studio"]["id"],
            "class_template_id": ctx["template"]["id"],
            "instructor_staff_id": ctx["instructor"]["id"], "room_code": "ROOM-C",
            "start_at": "2026-06-22T17:00:00Z", "capacity": 2,
            "expected_subscription_version": ctx["subscription_version"],
        }, ctx["owner"]), ApiErrorId.ERR_STALE_VERSION)

        rows, meta = validate_paginated(api.list_class_sessions(
            ctx["owner"], params={"studio_id": ctx["studio"]["id"]}))
        assert meta["total_count"] == 2, "the stale write created no session"


class TestMultiTenancy:

    def test_a_studio_owner_cannot_schedule_against_another_studios_template(self, api):
        """PRD §2.4: "hen rows remain beyond the returned page. Filter parameters that a given list endpoint declares (`status`, `channel`, `studio_id`, and the like) narrow `total_count` before pagination, never aft"

        Design: Corner/cross_cutting_complexity_layers/a_studio_owner_cannot_schedule_against_another_studios_template
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio_a = create_studio(legal_name="Prana Loft")
        owner_a = make_studio_owner_headers(studio_a["id"])
        sub_a = validate_success(api.get_subscription(studio_a["subscription_id"], ADMIN))
        create_payroll_period(studio_a["id"], owner_a)
        template_a = create_template(studio_a["id"], owner_a)
        create_staff(studio_a["id"], owner_a, template_id=template_a["id"])

        studio_b = create_studio(legal_name="Prana Annex", home_state_code="NY")
        owner_b = make_studio_owner_headers(studio_b["id"])
        create_payroll_period(studio_b["id"], owner_b)
        template_b = create_template(studio_b["id"], owner_b)
        noor = create_staff(studio_b["id"], owner_b, template_id=template_b["id"],
                            full_name="Noor Haddad")

        result = api.create_class_session({
            "studio_id": studio_a["id"], "class_template_id": template_b["id"],
            "instructor_staff_id": noor["id"], "room_code": "ROOM-A",
            "start_at": "2026-06-22T17:00:00Z", "capacity": 2,
            "expected_subscription_version": sub_a["version"],
        }, owner_a)
        assert result.status_code != 201, "the cross-tenant schedule is refused"

        for studio_id, owner in ((studio_a["id"], owner_a), (studio_b["id"], owner_b)):
            rows, meta = validate_paginated(api.list_class_sessions(
                owner, params={"studio_id": studio_id}))
            assert meta["total_count"] == 0, "no session leaked into either tenant"

    def test_marketplace_browsing_never_leaks_another_tenants_roster(self, api):
        """PRD §3.7: "Browsing the marketplace requires no authentication; only sessions whose studio is `ACTIVE` and whose tier has `marketplace_listing_enabled` set appear in the marketplace class list, which accepts optional filters for `studio_id`, `home_state_code`, `is_off_peak` and `start_after`."

        Design: Corner/cross_cutting_complexity_layers/marketplace_browsing_never_leaks_another_tenants_roster
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio_a = create_studio(legal_name="Prana Loft")
        owner_a = make_studio_owner_headers(studio_a["id"])
        ctx_a = _scheduled(studio_a, owner_a, "2026-06-20T17:00:00Z")
        create_client(studio_a["id"], display_name="Maya Alvarez",
                      email="maya@example.com")

        studio_b = create_studio(legal_name="Prana Annex", home_state_code="NY")
        owner_b = make_studio_owner_headers(studio_b["id"])
        ctx_b = _scheduled(studio_b, owner_b, "2026-06-21T17:00:00Z")

        rows, meta = validate_paginated(api.browse_marketplace_classes(
            ANONYMOUS, params={"studio_id": studio_a["id"], "limit": 10, "offset": 0}))
        assert meta["total_count"] == 1
        assert rows[0]["studio_id"] == studio_a["id"]
        assert ctx_b["session"]["id"] not in [row["id"] for row in rows]
        for row in rows:
            assert "client_id" not in row, "the marketplace view carries no client identity"
            assert "client_roster_count" not in row

        # The collection is public but the roster is not.
        validate_error(api.list_clients(ANONYMOUS, params={"home_studio_id": studio_a["id"]}),
                       ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestClientRosterListing:

    def test_clients_list_filters_by_roster_status_and_paginates(self, api):
        """PRD §2.3: "The meta object of a list response carries the four
        pagination fields: limit and offset echo the request, total_count reports
        the total number of rows matching the filter before pagination is
        applied."
        PRD §2.4: "it aggregates client_roster_count, outstanding_balance_cents,
        subscription_tier, feature_gates, data_ownership_state and status, and
        its suspension_reason is populated only when the tenant posture is
        SUSPENDED."

        Design: Corner/endpoints/clients_list_filters_by_roster_status_and_paginates
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Loft")
        owner = make_studio_owner_headers(studio["id"])
        maya = create_client(studio["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        create_client(studio["id"], display_name="Bea Tan", email="bea@example.com")
        cleo = create_client(studio["id"], display_name="Cleo Ruiz",
                             email="cleo@example.com")
        request = validate_success(api.create_portability_request({
            "studio_id": studio["id"], "requesting_client_id": cleo["id"],
            "dispute_reason": "relocating"}, make_client_headers(cleo["id"])),
            expected_status=201)
        get_success_data(api.resolve_portability_release(
            request["id"],
            {"include_booking_history": True, "include_financial_history": False},
            owner))

        rows, meta = validate_paginated(api.list_clients(
            owner, params={"home_studio_id": studio["id"], "limit": 2, "offset": 0}))
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        held, held_meta = validate_paginated(api.list_clients(
            owner, params={"home_studio_id": studio["id"], "status": "PORTABILITY_HOLD"}))
        assert held_meta["total_count"] == 1
        assert held[0]["id"] == cleo["id"]

        active, active_meta = validate_paginated(api.list_clients(
            owner, params={"home_studio_id": studio["id"], "status": "ACTIVE"}))
        assert active_meta["total_count"] == 2, \
            "the held client is no longer ACTIVE"

        after = validate_success(api.get_studio(studio["id"], owner))
        assert after["client_roster_count"] == 2, \
            "a client in PORTABILITY_HOLD is counted out of the roster"


# --- local helper -----------------------------------------------------------

def _scheduled(studio, owner, start_at):
    from test_helpers import api_client
    sub = validate_success(api_client.get_subscription(studio["subscription_id"], ADMIN))
    period = create_payroll_period(studio["id"], owner)
    template = create_template(studio["id"], owner)
    instructor = create_staff(studio["id"], owner, template_id=template["id"])
    session = create_session(studio["id"], owner, template["id"], instructor["id"],
                             capacity=2, start_at=start_at)
    return {"studio": studio, "owner": owner, "subscription": sub,
            "subscription_version": sub["version"], "period": period,
            "template": template, "instructor": instructor, "session": session}