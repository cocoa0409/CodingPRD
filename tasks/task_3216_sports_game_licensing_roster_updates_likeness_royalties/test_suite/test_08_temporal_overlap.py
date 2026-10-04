"""Difficulty queue A, rule 8: resource_temporal_overlap — both instances."""
from test_helpers import (
    ADMIN,
    create_active_agreement,
    create_agreement_payload,
    create_approved_edition,
    create_eligible_athlete,
    create_live_season,
    set_clock,
    get_success_data,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

LIVEOPS = TEST_USERS["liveops_manager_headers"]


class TestExclusiveAgreementOverlap:
    def test_shared_single_day_conflicts(self, api):
        """PRD §3.1: "Two terms that abut — one ending on a given date and the
        other starting the next day — do not conflict; two terms that share
        even a single calendar date do, because both bounds are inclusive. A
        conflict is rejected with ERR_EXCLUSIVITY_CONFLICT (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/exclusive_agreement_overlap_shared_single_day_conflicts
        """
        a = create_active_agreement(
            licensor_name="League A", exclusivity_scope="CATEGORY",
            term_start_on="2026-01-01", term_end_on="2026-09-01",
        )
        b = get_success_data(
            api_client.create_agreement(
                create_agreement_payload(
                    licensor_name="League B", exclusivity_scope="CATEGORY",
                    term_start_on="2026-09-01", term_end_on="2026-12-31",
                    royalty_rate_bps=1100,
                ),
                ADMIN,
            )
        )
        resp = api_client.activate_agreement(b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value)

    def test_adjacent_terms_do_not_conflict(self, api):
        """PRD §3.1: "Two terms that abut — one ending on a given date and the
        other starting the next day — do not conflict."

        Design: Difficulty/resource_temporal_overlap/exclusive_agreement_overlap_shared_single_day_conflicts
        """
        create_active_agreement(
            licensor_name="League A", exclusivity_scope="CATEGORY",
            term_start_on="2026-01-01", term_end_on="2026-09-01",
        )
        # Advance the clock past A's term end so C's abutting term contains
        # the clock date at activation (PRD §3.1 term-containment gate).
        set_clock("2026-09-02T00:00:00Z")
        c = get_success_data(
            api_client.create_agreement(
                create_agreement_payload(
                    licensor_name="League C", exclusivity_scope="CATEGORY",
                    term_start_on="2026-09-02", term_end_on="2026-12-31",
                    royalty_rate_bps=1100,
                ),
                ADMIN,
            )
        )
        activated = get_success_data(api_client.activate_agreement(c["id"], ADMIN))
        assert activated["agreement_status"] == "ACTIVE"


class TestEditionEmbargoThreshold:
    def _setup_approved_edition(self, api):
        agreement = create_active_agreement(
            licensor_name="L", sport_category="BASKET_PRO",
            exclusivity_scope="NONE",
        )
        athlete, _ = create_eligible_athlete(agreement["id"])
        season = create_live_season(
            agreement["id"], athlete["id"], initial_rating=80,
            title_code="HOOPS26", sport_category="BASKET_PRO",
        )
        edition = create_approved_edition(
            season["id"], region_code="CN",
            censorship_flags=["NO_REAL_PLAYER_NAMES"],
            embargo_until_on="2026-10-01",
        )
        return season, edition

    def test_release_before_embargo_rejected(self, api):
        """PRD §3.6: "An APPROVED edition may be released once the clock date is
        on or after embargo_until_on — the threshold is inclusive, so releasing
        exactly on the embargo date is permitted — and only while the parent
        season is LIVE."

        Design: Difficulty/resource_temporal_overlap/edition_release_embargo_threshold_semantics
        """
        _, edition = self._setup_approved_edition(api)
        set_clock("2026-09-30T00:00:00Z")  # one day before embargo
        resp = api_client.release_edition(edition["id"], LIVEOPS)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_CONFLICT.value)

    def test_release_exactly_on_embargo_day_succeeds(self, api):
        """PRD §3.6: "the threshold is inclusive, so releasing exactly on the
        embargo date is permitted."

        Design: Difficulty/resource_temporal_overlap/edition_release_embargo_threshold_semantics
        """
        _, edition = self._setup_approved_edition(api)
        set_clock("2026-10-01T00:00:00Z")  # exactly the embargo date
        released = get_success_data(api_client.release_edition(edition["id"], LIVEOPS))
        assert released["edition_status"] == "RELEASED"
