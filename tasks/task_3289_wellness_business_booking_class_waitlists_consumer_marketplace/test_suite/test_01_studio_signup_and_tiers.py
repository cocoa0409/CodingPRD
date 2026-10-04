"""Studio sign-up, derived tier gates and resolution/auth precedence."""
import pytest

from test_helpers import (
    ADMIN,
    ANONYMOUS,
    ApiErrorId,
    TEST_USERS,
    ensure_tier,
    get_success_data,
    make_operator_headers,
    make_studio_owner_headers,
    nonexistent_id,
    set_clock,
    validate_error,
    validate_success,
)


class TestStudioSignUp:

    def test_signup_returns_derived_gates_and_system_fields(self, api):
        """PRD §3.1: "The new studio starts in `TRIAL`, and its subscription starts in `TRIAL` with `renewal_epoch` 0, `dunning_stage` `CURRENT`, a `renewal_due_at` 30 days ahead, a matching `grace_until`, and a `monthly_fee_cents_snapshot` captured from the requested tier."
        PRD §3.1: "The studio's `subscription_id`, `subscription_tier` and `feature_gates` are stamped from that subscription, and `data_ownership_state` begins as `OWNED`."

        Design: Corner/entities/studio_signup_returns_derived_tier_gates_and_system_fields
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")

        before = api.list_studios(ADMIN)
        get_success_data(before)  # the collection read is reachable

        created = api.create_studio({
            "legal_name": "Prana Loft", "home_state_code": "CA",
            "owner_full_name": "Nadia Okafor", "tier": "GROWTH",
            "billing_period": "MONTHLY", "payroll_cap_mode": "BONUS_OUTSIDE_CAP",
        }, ANONYMOUS)
        studio = validate_success(created, expected_status=201)

        assert studio["status"] == "TRIAL", "a new studio begins in TRIAL"
        assert studio["version"] == 1, "version begins at 1"
        assert studio["data_ownership_state"] == "OWNED"
        assert studio["client_roster_count"] == 0
        assert studio["outstanding_balance_cents"] == 0
        assert studio["subscription_tier"] == "GROWTH"
        assert studio["feature_gates"]["marketplace_listing"] is True
        assert studio["feature_gates"]["staff_payroll"] is True
        assert studio["feature_gates"]["client_portability_export"] is True

        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        assert sub["status"] == "TRIAL"
        assert sub["dunning_stage"] == "CURRENT"
        assert sub["renewal_epoch"] == 0
        assert sub["monthly_fee_cents_snapshot"] == 9900
        assert sub["billing_period"] == "MONTHLY"

    def test_new_studio_supplies_only_five_client_fields(self, api):
        """PRD §3.1: "The caller supplies the studio's `legal_name`, its two-letter `home_state_code` drawn from the fixed five-value vocabulary of `CA`, `NY`, `TX`, `WA` and `CO`, an owner name under `owner_full_name`, the requested `tier`, the `billing_period` the subscription will bill on, and the studio's `payroll_cap_mode`."

        Design: Corner/entities/studio_signup_returns_derived_tier_gates_and_system_fields
        """
        ensure_tier("ENTERPRISE")
        set_clock("2026-06-01T00:00:00Z")

        studio = validate_success(api.create_studio({
            "legal_name": "Prana Collective", "home_state_code": "CO",
            "owner_full_name": "Rue Bennet", "tier": "ENTERPRISE",
            "billing_period": "ANNUAL", "payroll_cap_mode": "BONUS_INSIDE_CAP",
        }, ANONYMOUS), expected_status=201)

        assert studio["legal_name"] == "Prana Collective"
        assert studio["home_state_code"] == "CO"
        assert studio["payroll_cap_mode"] == "BONUS_INSIDE_CAP"
        assert studio["subscription_tier"] == "ENTERPRISE"
        # The gates are re-derived from the ENTERPRISE row, not echoed.
        assert studio["feature_gates"]["marketplace_listing"] is True
        assert studio["feature_gates"]["instructor_substitution"] is True
        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        assert sub["billing_period"] == "ANNUAL"
        assert sub["monthly_fee_cents_snapshot"] == 24900


class TestResolutionAndAuthPrecedence:

    def test_unknown_subscription_id_returns_subscription_not_found(self, api):
        """PRD §2.10: "an unresolvable studio, subscription, client, class session, booking, waitlist entry, membership, class pack, staff member, payroll period, portability request and benefit network are reported respectively as `ERR_STUDIO_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_CLASS_SESSION_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_WAITLIST_ENTRY_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_CLASS_PACK_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_PAYROLL_PERIOD_NOT_FOUND`, `ERR_PORTABILITY_REQUEST_NOT_FOUND` and `ERR_BENEFIT_NETWORK_NOT_FOUND`, each at HTTP 404."

        Design: Corner/entities/class_session_get_with_an_unknown_id_returns_class_session_not_found
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        ensure_tier("GROWTH")

        error = validate_error(
            api.get_subscription(nonexistent_id(), ADMIN),
            ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND)
        assert error["message"], "an error response carries a human-readable message"

    def test_unknown_class_session_id_returns_class_session_not_found(self, api):
        """PRD §2.10: "an unresolvable studio, subscription, client, class
        session, booking, waitlist entry, membership, class pack, staff member,
        payroll period, portability request and benefit network are reported
        respectively as ... ERR_CLASS_SESSION_NOT_FOUND ... each at HTTP 404."

        Design: Corner/entities/class_session_get_with_an_unknown_id_returns_class_session_not_found
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")

        validate_error(api.get_class_session(nonexistent_id(), ADMIN),
                       ApiErrorId.ERR_CLASS_SESSION_NOT_FOUND)
        validate_error(api.get_studio(nonexistent_id(), ADMIN),
                       ApiErrorId.ERR_STUDIO_NOT_FOUND)

    def test_missing_user_context_is_refused_before_existence(self, api):
        """PRD §2.11: "Authentication context is evaluated first: absent or unrecognised user context yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, and a role the operation does not admit yields `ERR_UNAUTHORIZED_ROLE` before anything else is considered."
        PRD §2.11: "oes a staff member; a booking exposes the waitlist holds promoted into it and the commission entri"

        Design: Corner/validations/a_bounded_request_without_user_context_is_refused_before_existence
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")

        # No headers at all, and a path id that does not resolve: the header
        # failure must pre-empt the lookup.
        error = validate_error(
            api.get_subscription(nonexistent_id(), {}),
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert error["error_id"] != ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND, \
            "the header failure pre-empted the lookup"

    def test_unrecognised_role_value_is_refused_at_the_same_band(self, api):
        """PRD §2.11: "Authentication context is evaluated first: absent or
        unrecognised user context yields
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
        PRD §2.1: "A request that omits either header, or that names a role outside the declared roster, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/a_bounded_request_without_user_context_is_refused_before_existence
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")

        from prd_bench_local_runner.testing import build_user_headers
        bogus = build_user_headers("test-opaque-1", "NotARole")
        validate_error(api.get_subscription(nonexistent_id(), bogus),
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)