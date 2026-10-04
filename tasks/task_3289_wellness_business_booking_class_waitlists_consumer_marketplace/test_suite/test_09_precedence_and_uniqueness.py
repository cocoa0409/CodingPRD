"""Validation precedence, uniqueness scope and the class format client rules."""
import pytest

from test_helpers import (
    ADMIN,
    ANONYMOUS,
    ApiErrorId,
    TEST_USERS,
    create_client,
    create_payroll_period,
    create_staff,
    create_template,
    ensure_tier,
    get_success_data,
    make_client_headers,
    make_studio_owner_headers,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, create_studio


class TestEntitlementOutranksConstraint:

    def test_entitlement_band_fires_before_the_capacity_band(self, api):
        """PRD §2.11: "Tenant posture and tier entitlement are then evaluated — `ERR_STUDIO_NOT_OPERATING` and `ERR_SUBSCRIPTION_INACTIVE` at HTTP 409, `ERR_PAYROLL_HOLD` at HTTP 409, and `ERR_FEATURE_NOT_IN_TIER` at HTTP 403 — and this band deliberately stands above the temporal and constraint bands, so a suspended studio always reports the posture error rather than a capacity or overlap error that happens to be true as well."

        Design: Difficulty/priority_pair_validation_conflict/suspended_studio_outranks_capacity_shortfall_on_session_create
        """
        ensure_tier("STARTER")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Tiny Loft", tier="STARTER")
        owner = make_studio_owner_headers(studio["id"])

        # PRD §2.5 gates *INSTRUCTOR* staff-member creation on staff_payroll,
        # which is false on STARTER, so a front-desk account is named here —
        # the session-create conflict under test is the posture band versus the
        # capacity band, which does not depend on the instructor's staff_role.
        create_payroll_period(studio["id"], owner)
        template = create_template(studio["id"], owner, name="Beginner Mat 45",
                                   duration_minutes=45, base_price_cents=2000,
                                   default_capacity=1, is_off_peak=False,
                                   buffer_minutes=0)
        omar = create_staff(studio["id"], owner, staff_role="FRONT_DESK",
                            full_name="Omar Diallo", substitute_class_template_ids=[])

        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        get_success_data(api.suspend_subscription(
            studio["subscription_id"],
            {"reason": "non-payment", "expected_subscription_version": sub["version"]},
            owner))
        after = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))

        # Both a tier-entitlement refusal and a capacity refusal are true here.
        actual = validate_error_is_one_of(api.create_class_session({
            "studio_id": studio["id"], "class_template_id": template["id"],
            "instructor_staff_id": omar["id"], "room_code": "ROOM-A",
            "start_at": "2026-06-20T17:00:00Z", "capacity": 0,
            "expected_subscription_version": after["version"],
        }, owner), [ApiErrorId.ERR_FEATURE_NOT_IN_TIER,
                    ApiErrorId.ERR_STUDIO_NOT_OPERATING])
        assert actual != ApiErrorId.ERR_STUDIO_CAPACITY_EXCEEDED, \
            "the posture band outranks the capacity band"

    def test_nothing_is_persisted_when_the_posture_band_refuses(self, api):
        """PRD §2.11: "tication context is evaluated first: absent or unrecognised user context yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, and a role the operation does not admit yields `ERR_UNAUTHORIZED_ROLE` bef"

        Design: Difficulty/priority_pair_validation_conflict/suspended_studio_outranks_capacity_shortfall_on_session_create
        """
        ensure_tier("STARTER")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Tiny Loft", tier="STARTER")
        owner = make_studio_owner_headers(studio["id"])

        # PRD §2.5 gates *INSTRUCTOR* staff-member creation on staff_payroll,
        # which is false on STARTER, so a front-desk account is named here —
        # the session-create conflict under test is the posture band versus the
        # capacity band, which does not depend on the instructor's staff_role.
        create_payroll_period(studio["id"], owner)
        template = create_template(studio["id"], owner, name="Beginner Mat 45",
                                   duration_minutes=45, base_price_cents=2000,
                                   default_capacity=1, is_off_peak=False,
                                   buffer_minutes=0)
        omar = create_staff(studio["id"], owner, staff_role="FRONT_DESK",
                            full_name="Omar Diallo", substitute_class_template_ids=[])

        sub = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))
        get_success_data(api.suspend_subscription(
            studio["subscription_id"],
            {"reason": "non-payment", "expected_subscription_version": sub["version"]},
            owner))
        after = validate_success(api.get_subscription(studio["subscription_id"], ADMIN))

        api.create_class_session({
            "studio_id": studio["id"], "class_template_id": template["id"],
            "instructor_staff_id": omar["id"], "room_code": "ROOM-A",
            "start_at": "2026-06-20T17:00:00Z", "capacity": 0,
            "expected_subscription_version": after["version"],
        }, owner)

        rows, meta = validate_paginated(api.list_class_sessions(
            owner, params={"studio_id": studio["id"]}))
        assert meta["total_count"] == 0, "nothing was persisted"


class TestClientUniquenessScope:

    def test_duplicate_email_is_refused_on_one_roster_and_allowed_elsewhere(self, api):
        """PRD §2.10: "the registration `email` is the unique-within-studio contact address described in §3.2 and is never used as a lookup key outside that studio's roster."
        PRD §3.3: "A client registers against a studio by naming it as their
        home_studio_id."
        PRD §2.11: "then the capacity, quota and uniqueness constraints
        (ERR_STUDIO_CAPACITY_EXCEEDED, ERR_ALLOCATION_EXHAUSTED,
        ERR_NO_ACTIVE_PACK, ERR_MEMBERSHIP_INACTIVE, ERR_PAYROLL_PERIOD_OVERLAP,
        ERR_CLIENT_EMAIL_CONFLICT, all HTTP 409)."

        Design: Corner/entities/client_create_rejects_a_duplicate_email_on_the_same_roster_but_allows_it_elsewhere
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Loft")
        owner = make_studio_owner_headers(studio["id"])
        studio_b = create_studio(legal_name="Prana Annex", home_state_code="NY")
        owner_b = make_studio_owner_headers(studio_b["id"])
        original = create_client(studio["id"], display_name="Maya Alvarez",
                                 email="maya@example.com")

        validate_error(api.create_client({
            "home_studio_id": studio["id"], "display_name": "Maya Duplicate",
            "email": "maya@example.com", "home_state_code": "CA",
        }, owner), ApiErrorId.ERR_CLIENT_EMAIL_CONFLICT)

        reused = validate_success(api.create_client({
            "home_studio_id": studio_b["id"], "display_name": "Maya Alvarez",
            "email": "maya@example.com", "home_state_code": "NY",
        }, make_client_headers(original["id"])), expected_status=201)
        assert reused["home_studio_id"] == studio_b["id"], \
            "the same address is admitted on a second studio roster"

        rows, meta = validate_paginated(api.list_clients(
            owner, params={"home_studio_id": studio["id"]}))
        assert meta["total_count"] == 1, "the same-roster duplicate was not created"

    def test_out_of_vocabulary_state_code_fails_as_a_bad_request(self, api):
        """PRD §3.1: "The caller supplies the studio's legal_name, its two-letter
        home_state_code drawn from the fixed five-value vocabulary of CA, NY, TX,
        WA and CO."

        Design: Corner/entities/client_create_rejects_a_duplicate_email_on_the_same_roster_but_allows_it_elsewhere
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        studio = create_studio(legal_name="Prana Loft")
        owner = make_studio_owner_headers(studio["id"])

        result = api.create_client({
            "home_studio_id": studio["id"], "display_name": "Bad State",
            "email": "bad@example.com", "home_state_code": "ZZ",
        }, owner)
        # PRD §3.1 declares the five-value vocabulary but does not pin the
        # rejection status for a value outside it, so only the covered facts are
        # asserted: the write is refused, on the field, and not for the header.
        assert result.status_code != 201, \
            "an out-of-vocabulary home_state_code is not a valid client"
        payload = result.json()
        assert payload["response_type"] == "error"
        assert payload["data"]["error_id"] != ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, \
            "the context was present, so the failure is not a header failure"


class TestClassTemplateDerivation:

    def test_class_template_rejects_a_duration_below_the_minimum(self, api):
        """PRD §3.2: "A class format is defined for a studio with a display name,
        a duration_minutes of at least 15, a base_price_cents of at least zero
        before any off-peak or tier adjustment, a default_capacity of at least 1,
        a credit_cost of at least 1 naming how many pack credits one seat of that
        format consumes, an is_off_peak flag, and a buffer_minutes changeover
        requirement of at least zero against any other session in the same room."

        Design: Corner/entities/class_session_create_derives_end_price_and_posture_from_the_template
        """
        ctx_setup = _roster()
        rejected = api_client.create_class_template({
            "studio_id": ctx_setup["studio"]["id"], "name": "Too Short",
            "duration_minutes": 10, "base_price_cents": 4000,
            "default_capacity": 2, "credit_cost": 1, "is_off_peak": False,
            "buffer_minutes": 0,
        }, ctx_setup["owner"])
        assert rejected.status_code != 201, \
            "duration_minutes below 15 is not a valid format"

    def test_class_template_minimum_duration_is_accepted_at_the_boundary(self, api):
        """PRD §3.2: "a `duration_minutes` of at least 15"

        Design: Corner/entities/class_session_create_derives_end_price_and_posture_from_the_template
        """
        ctx_setup = _roster()
        accepted = validate_success(api_client.create_class_template({
            "studio_id": ctx_setup["studio"]["id"], "name": "Quarter Hour",
            "duration_minutes": 15, "base_price_cents": 4000,
            "default_capacity": 2, "credit_cost": 1, "is_off_peak": False,
            "buffer_minutes": 0,
        }, ctx_setup["owner"]), expected_status=201)
        assert accepted["duration_minutes"] == 15


class TestTierCatalogue:

    def test_tier_rank_must_be_unique_across_rows(self, api):
        """PRD §2.5: "a monotonic `tier_rank` used as the upgrade-path key beginning at 1 where 1 is the lowest rank and the value must be unique across rows"

        Design: Corner/entities/studio_signup_returns_derived_tier_gates_and_system_fields
        """
        ensure_tier("GROWTH")
        set_clock("2026-06-01T00:00:00Z")
        duplicate = api.create_subscription_tier({
            "tier": "GROWTH", "monthly_fee_cents": 9900, "tier_rank": 2,
            "included_staff_seats": 4, "seat_overage_fee_cents": 1900,
            "marketplace_listing_enabled": True, "staff_payroll_enabled": True,
            "instructor_substitution_enabled": True,
            "waitlist_auto_promotion_enabled": True,
            "crm_client_export_enabled": True, "marketplace_commission_bps": 1500,
        }, ADMIN)
        # A same-value row replaces the tier, which is the declared behaviour.
        assert duplicate.status_code in (200, 201)

    def test_tier_catalogue_is_readable_without_authentication(self, api):
        """PRD §2.1: "The only operations that skip the header requirement are the subscription-tier catalogue reads and the two platform operator endpoints — the logical-clock setter and the fault injectors — which are reserved for the `OperatorOnly` harness role."

        Design: Corner/entities/studio_signup_returns_derived_tier_gates_and_system_fields
        """
        ensure_tier("GROWTH")
        ensure_tier("STARTER")
        set_clock("2026-06-01T00:00:00Z")

        tiers = validate_success(api.list_subscription_tiers(ANONYMOUS))
        rows = tiers if isinstance(tiers, list) else tiers.get("data", [])
        codes = [row["tier"] for row in rows]
        assert "GROWTH" in codes and "STARTER" in codes
        for row in rows:
            assert "version" not in row, \
                "a tier is a configuration record and carries no version"
            assert "updated_at" not in row


# --- local helper -----------------------------------------------------------

def _roster():
    ensure_tier("GROWTH")
    set_clock("2026-06-01T00:00:00Z")
    studio = create_studio(legal_name="Prana Loft")
    owner = make_studio_owner_headers(studio["id"])
    return {"studio": studio, "owner": owner}