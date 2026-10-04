"""Entity-level corner coverage: creation defaults, uniqueness, payload
constraints, 404s, and audit-entity immutability (PRD §2.5, §2.8, §3.1-3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_club,
    create_club_payload,
    create_membership_payload,
    create_provider_payload,
    create_tier_payload,
    get_success_data,
    setup_club_and_tiers,
    setup_membership_scenario,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClubCreationDefaults:
    def test_club_without_billing_policy_defaults_to_schedule_and_active(self, api, club_admin_headers):
        """PRD §3.1: "an optional `billing_policy` of `SCHEDULE` or `ACTUAL` that
        defaults to `SCHEDULE`." PRD §3.1: "Clubs begin life `ACTIVE`".

        Design: Corner/entities/club_creation_defaults_and_duplicate_code
        """
        resp = api.create_club(create_club_payload(), club_admin_headers)
        club = validate_success(resp, expected_status=201)
        assert_club(club)
        assert club["billing_policy"] == "SCHEDULE"
        assert club["status"] == "ACTIVE"

    def test_duplicate_club_code_rejected(self, api, club_admin_headers):
        """PRD §3.1: "A `ClubAdmin` registers a federation `Club` with a unique
        `club_code`". PRD §2.8 step 4: violations of payload constraints surface
        as `ERR_INVALID_REQUEST`.

        Design: Corner/entities/club_creation_defaults_and_duplicate_code
        """
        api.create_club(create_club_payload(club_code="NCA"), club_admin_headers)
        resp = api.create_club(
            create_club_payload(club_code="NCA", name="Duplicate", territory_state_codes=["OR"],
                                default_arrival_target_minutes=30),
            club_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestClubGet:
    def test_get_nonexistent_club_returns_not_found(self, api, club_admin_headers):
        """PRD §2.8 step 3: "path identifiers resolve to existing entities,
        validated strictly left-to-right along the URL. A nested request fails
        on the first path identifier that does not resolve, with `ERR_NOT_FOUND`."

        Design: Corner/entities/club_get_not_found
        """
        resp = api.get_club(NON_EXISTENT_UUID, club_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestTierPayloadConstraints:
    def test_tier_missing_required_included_tow_miles_rejected(self, api, club_admin_headers):
        """PRD §2.8 step 4: "required fields are present, enum members are
        valid, and numeric ranges are respected".

        Design: Corner/entities/tier_required_fields_missing
        """
        payload = create_tier_payload("CLASSIC")
        payload.pop("included_tow_miles")
        resp = api.create_tier(payload, club_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestMembershipUniqueness:
    def test_duplicate_primary_member_email_rejected(self, api, member_services_rep_headers):
        """PRD §3.2: "the `primary_member_email` (unique across all memberships)".

        Design: Corner/entities/membership_duplicate_email_rejected
        """
        base = setup_club_and_tiers(["CLASSIC"])
        email = unique_email()
        resp1 = api.create_membership(
            create_membership_payload(base["club"]["id"], "CLASSIC", primary_member_email=email),
            member_services_rep_headers,
        )
        validate_success(resp1, expected_status=201)
        resp2 = api.create_membership(
            create_membership_payload(base["club"]["id"], "CLASSIC",
                                      primary_member_name="Other Person",
                                      primary_member_email=email),
            member_services_rep_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestProviderPayloadConstraints:
    def test_sla_multiplier_above_range_rejected(self, api, club_admin_headers):
        """PRD §2.8 step 4: "a provider's `sla_multiplier` between 0.5 and 3.0
        inclusive".

        Design: Corner/entities/provider_sla_multiplier_range_enforced
        """
        club = validate_success(api.create_club(create_club_payload(), club_admin_headers), expected_status=201)
        resp = api.create_provider(
            create_provider_payload(club["id"], sla_multiplier=3.5, max_concurrent_dispatches=1),
            club_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestMembershipEventImmutability:
    def test_enrollment_event_shape_and_reverse_lookup(self, api, member_services_rep_headers):
        """PRD §2.5: "The audit entity `MembershipEvent` is the exception: it is
        immutable after creation and therefore carries only `id` and `created_at` —
        both `updated_at` and `version` are absent from it." PRD §3.2: "an
        `ENROLLMENT` entry is appended to its `MembershipEvent` audit trail."

        Design: Corner/entities/membership_event_immutability_and_reverse_lookup
        """
        base = setup_membership_scenario("CLASSIC", with_primary=False)
        membership = base["membership"]
        resp = api.list_membership_events_for(membership["id"], member_services_rep_headers)
        events, _meta = validate_paginated(resp)
        enrollment_events = [e for e in events if e["event_type"] == "ENROLLMENT"]
        assert len(enrollment_events) == 1, f"expected exactly one ENROLLMENT event, got {enrollment_events}"
        event = enrollment_events[0]
        assert event["membership_id"] == membership["id"]
        assert "version" not in event, "MembershipEvent must not carry version"
        assert "updated_at" not in event, "MembershipEvent must not carry updated_at"
        assert event.get("from_tier") is None
        assert event.get("to_tier") == "CLASSIC"
