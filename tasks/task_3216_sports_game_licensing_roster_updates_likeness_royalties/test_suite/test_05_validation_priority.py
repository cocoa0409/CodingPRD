"""Difficulty queue A, rule 5: priority_pair_validation_conflict — both instances."""
from test_helpers import (
    ADMIN,
    RIGHTS,
    create_active_agreement,
    create_eligible_athlete,
    create_funded_wallet,
    create_live_season,
    create_roster_batch_payload,
    create_roster_entry_payload,
    set_clock,
    get_success_data,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_content_drop_payload
from test_helpers.test_users import (
    TEST_USERS,
    make_roster_operator_headers,
    make_roster_reviewer_headers,
)

LIVEOPS = TEST_USERS["liveops_manager_headers"]


class TestStateBeatsTemporalOnDropRelease:
    def test_release_of_canceled_drop_reports_invalid_state_not_window(self, api):
        """PRD §2.10: "A request that fails on both an invalid state and an
        insufficient balance therefore reports the state error" and the fixed
        order places "target-state legality for the requested transition
        (ERR_INVALID_STATE)" at fifth, ahead of "temporal windows such as term
        containment, embargo, or audit-window (ERR_TEMPORAL_CONFLICT)" at
        eighth.

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_temporal_window_on_drop_release
        """
        ctx = _live_season_ctx(api)
        drop = get_success_data(
            api_client.create_content_drop(
                create_content_drop_payload(
                    ctx["season"]["id"], drop_kind="VANITY",
                    drop_label="Vanity Drop", price_vc=50,
                    scheduled_start_at="2026-10-01T00:00:00Z",
                    scheduled_end_at="2026-10-31T23:59:59Z",
                ),
                LIVEOPS,
            )
        )
        get_success_data(api_client.cancel_content_drop(drop["id"], LIVEOPS))
        set_clock("2026-11-15T00:00:00Z")  # outside the drop window

        resp = api_client.release_content_drop(drop["id"], LIVEOPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_release_of_healthy_drop_outside_window_reports_window_error(self, api):
        """PRD §3.4: "Releasing a drop moves it to RELEASED and requires the
        parent season to be LIVE, the clock datetime to fall at or after
        scheduled_start_at and strictly before scheduled_end_at — outside that
        half-open window the release is rejected with ERR_DROP_WINDOW."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_temporal_window_on_drop_release
        """
        ctx = _live_season_ctx(api)
        drop = get_success_data(
            api_client.create_content_drop(
                create_content_drop_payload(
                    ctx["season"]["id"], drop_kind="VANITY",
                    drop_label="Window Drop", price_vc=50,
                    scheduled_start_at="2026-10-01T00:00:00Z",
                    scheduled_end_at="2026-10-31T23:59:59Z",
                ),
                LIVEOPS,
            )
        )
        # clock stays at startup 2026-09-01, before the window
        resp = api_client.release_content_drop(drop["id"], LIVEOPS)
        validate_error(resp, ApiErrorId.ERR_DROP_WINDOW.value)


class TestSoDBeatsOCCOnPublish:
    def _two_batch_setup(self, api, second_operator_id, second_submitted_by):
        """Season PRELAUNCH with batch B1 already PUBLISHED and batch B2
        VALIDATED; returns (season, b2_id, stale_version_from_before_b1_publish).
        """
        agreement = create_active_agreement(exclusivity_scope="NONE")
        athlete, _ = create_eligible_athlete(agreement["id"])
        season = get_success_data(
            api_client.create_season(
                {"title_code": "PIGSKIN26", "sport_category": "AMFOOT_PRO",
                 "season_label": "2026-27", "agreement_id": agreement["id"],
                 "season_opens_on": "2026-08-01", "season_closes_on": "2027-02-01"},
                LIVEOPS,
            )
        )
        op1 = make_roster_operator_headers("op-1")
        b1 = get_success_data(
            api_client.create_roster_batch(
                create_roster_batch_payload(season["id"], batch_label="B1",
                                            submitted_by="op-1"),
                op1,
            )
        )
        get_success_data(
            api_client.add_roster_entry(
                b1["id"], create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                                      overall_rating=80), op1
            )
        )
        get_success_data(api_client.validate_roster_batch(b1["id"], op1))
        stale_version = get_success_data(api_client.get_season(season["id"], LIVEOPS))["version"]
        get_success_data(
            api_client.publish_roster_batch(
                b1["id"], {"expected_season_version": stale_version},
                make_roster_reviewer_headers("reviewer-1"),
            )
        )
        op2 = make_roster_operator_headers(second_operator_id)
        b2 = get_success_data(
            api_client.create_roster_batch(
                create_roster_batch_payload(season["id"], batch_label="B2",
                                            submitted_by=second_submitted_by),
                op2,
            )
        )
        get_success_data(
            api_client.add_roster_entry(
                b2["id"],
                create_roster_entry_payload(athlete["id"], entry_kind="UPDATE_ATTRIBUTE",
                                            overall_rating=81),
                op2,
            )
        )
        get_success_data(api_client.validate_roster_batch(b2["id"], op2))
        return season, b2["id"], stale_version

    def test_self_publish_with_stale_version_reports_sod(self, api):
        """PRD §2.10: "the order is: ... sixth, segregation of duties
        (ERR_SEGREGATION_OF_DUTIES); ... tenth, optimistic-concurrency staleness
        (ERR_STALE_SEASON_VERSION or ERR_STALE_PROGRAM_VERSION)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_occ_stale_version_on_publish
        """
        _, b2_id, stale_version = self._two_batch_setup(api, "op-42", "op-42")
        resp = api_client.publish_roster_batch(
            b2_id, {"expected_season_version": stale_version},
            make_roster_reviewer_headers("op-42"),  # same id as submitted_by
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_distinct_reviewer_with_stale_version_reports_occ(self, api):
        """PRD §2.8: "If the season's current version no longer matches — for
        example because another reviewer has just published a different batch,
        which legitimately superseded the prior published batch and advanced
        the season — the publish is rejected with ERR_STALE_SEASON_VERSION
        (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_occ_stale_version_on_publish
        """
        _, b2_id, stale_version = self._two_batch_setup(api, "op-42", "op-42")
        resp = api_client.publish_roster_batch(
            b2_id, {"expected_season_version": stale_version},
            make_roster_reviewer_headers("reviewer-2"),  # SoD clean; OCC stale
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SEASON_VERSION.value)


def _live_season_ctx(api):
    agreement = create_active_agreement(licensor_name="L", exclusivity_scope="NONE")
    athlete, grant = create_eligible_athlete(agreement["id"])
    season = create_live_season(agreement["id"], athlete["id"], initial_rating=70)
    return {"agreement": agreement, "athlete": athlete, "grant": grant,
            "season": season}
