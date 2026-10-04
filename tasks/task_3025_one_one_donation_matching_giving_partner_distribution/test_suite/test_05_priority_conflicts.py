"""The adjudication ladder: which rejection wins when several rules could fire (PRD §2.4)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    build_user_headers,
    commit_allocation,
    create_active_product,
    create_approved_partner,
    create_season,
    declare_capacity,
    get_partner,
    get_profile,
    register_claim,
    set_clock,
    validate_error,
)


class TestAuthPrecedesExistence:
    """Difficulty/priority_pair_validation_conflict — rung 1 beats rung 3."""

    def test_unauthenticated_call_beats_the_missing_product(self, api):
        """PRD §2.4: "The presence and validity of `X-User-Role` and `X-User-ID` is checked first (`ERR_MISSING_AUTH_CONTEXT`), so an unauthenticated request that names a product which does not exist reports the authentication failure rather than `ERR_PRODUCT_NOT_FOUND`."
        PRD §2.4: "Authentication leads."
        PRD §2.1: "A request missing either header, or naming a role that the system does not recognize, is rejected before any path or body inspection with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401)."

        Design: Difficulty/priority_pair_validation_conflict/auth_precedes_existence_on_a_bogus_product_path
        """
        bogus = api.get_donation_product(
            "00000000-0000-4000-8000-000000000000", build_user_headers("x", "NotARole")
        )
        validate_error(bogus, "ERR_MISSING_AUTH_CONTEXT", expected_status=401)

    def test_the_same_path_resolves_to_the_product_error_once_authenticated(self, api):
        """PRD §2.4: "The presence and validity of `X-User-Role` and `X-User-ID` is checked first (`ERR_MISSING_AUTH_CONTEXT`), so an unauthenticated request that names a product which does not exist reports the authentication failure rather than `ERR_PRODUCT_NOT_FOUND`."
        PRD §2.4: "Authentication leads."

        Design: Difficulty/priority_pair_validation_conflict/auth_precedes_existence_on_a_bogus_product_path
        """
        resolved = api.get_donation_product(
            "00000000-0000-4000-8000-000000000000", TEST_USERS["auditor_headers"]
        )
        validate_error(resolved, "ERR_PRODUCT_NOT_FOUND", expected_status=404)

        missing_headers = api.get_donation_product(
            "00000000-0000-4000-8000-000000000000", {}
        )
        validate_error(missing_headers, "ERR_MISSING_AUTH_CONTEXT", expected_status=401)


class TestTemporalPrecedesFiscal:
    """Difficulty/priority_pair_validation_conflict — rung 12 beats rung 15."""

    def _over_capacity_frozen_scenario(self):
        set_clock("2026-09-01T00:00:00Z")
        season = create_season(freezes_at="2026-09-15T00:00:00Z")
        product = create_active_product(
            product_name="Scarce Crew Sock",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=1900,
            unit_cost_cents=1150,
            # PRD §3.4 gates activation at design_weight_score >= 60; this fixture
            # must clear the gate, so the sock is declared reusable (40 + 20 = 60).
            is_reusable=True,
        )
        partner = create_approved_partner(
            legal_name="Theta Warm Line",
            partner_type="DOMESTIC_VIOLENCE_SHELTER",
            operating_region="WEST",
            operating_state_code="CA",
            registry_id="CA-CHR-800008",
            ein="888999000",
            unduplicated_recipients_per_facility=12000,
            need_tier="HIGH",
        )
        profile = declare_capacity(partner["id"], max_allocatable_units=1)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=1, priority_tier="CRITICAL",
        )
        # Roll past freezes_at so the season is FROZEN at the trigger instant.
        set_clock("2026-09-20T00:00:00Z")
        return season, product, partner, profile, claim, allocation

    def test_frozen_season_error_wins_over_the_capacity_breach(self, api):
        """PRD §2.4: "*Temporal precedes fiscal*: a post-freeze commit that is also over capacity reports `ERR_SEASON_FROZEN` rather than `ERR_CAPACITY_EXCEEDED`."
        PRD §2.11: "No write may fall after the resolved season's `freezes_at` instant, and no write may mutate a season whose status is `FINALIZED`; a violation of either is rejected with `ERR_SEASON_FROZEN` (HTTP 409)."
        PRD §2.6: "The governing fiscal rule of the surface is that `capacity_utilization_units` must not exceed `max_allocatable_units` for the resolved partner-and-season profile, and that a shortage of exactly zero units passes."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_capacity_on_a_frozen_season_commit
        """
        season, product, partner, profile, claim, allocation = (
            self._over_capacity_frozen_scenario()
        )
        current_version = get_partner(partner["id"])["version"]

        res = api_client.commit_allocation_plan(
            season["id"],
            {
                "giving_partner_id": partner["id"],
                "claim_id": claim["id"],
                "donation_product_id": product["id"],
                "allocated_units": 5,
                "priority_tier": "CRITICAL",
                "liquidity_cap": 10,
                "expected_partner_version": current_version,
            },
            TEST_USERS["planner_headers"],
        )
        validate_error(res, "ERR_SEASON_FROZEN", expected_status=409)

    def test_the_losing_check_never_mutated_capacity(self, api):
        """PRD §2.6: "The governing fiscal rule of the surface is that `capacity_utilization_units` must not exceed `max_allocatable_units` for the resolved partner-and-season profile, and that a shortage of exactly zero units passes."
        PRD §2.4: "*Temporal precedes fiscal*: a post-freeze commit that is also over capacity reports `ERR_SEASON_FROZEN` rather than `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_precedes_capacity_on_a_frozen_season_commit
        """
        season, product, partner, profile, claim, allocation = (
            self._over_capacity_frozen_scenario()
        )
        current_version = get_partner(partner["id"])["version"]

        api_client.commit_allocation_plan(
            season["id"],
            {
                "giving_partner_id": partner["id"],
                "claim_id": claim["id"],
                "donation_product_id": product["id"],
                "allocated_units": 5,
                "priority_tier": "CRITICAL",
                "liquidity_cap": 10,
                "expected_partner_version": current_version,
            },
            TEST_USERS["planner_headers"],
        )

        assert get_profile(profile["id"])["committed_units"] == 1