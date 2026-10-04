"""Difficulty queue A, rule 7: cross_entity_state_dependency — both instances."""
from test_helpers import (
    ADMIN,
    RIGHTS,
    create_active_agreement,
    create_eligible_athlete,
    create_athlete_payload,
    create_live_season,
    create_roster_batch_payload,
    create_roster_entry_payload,
    create_season_payload,
    create_published_batch,
    get_success_data,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS, make_roster_operator_headers

LIVEOPS = TEST_USERS["liveops_manager_headers"]


class TestRosterValidateDependsOnAthleteEligibility:
    def test_add_entry_for_ineligible_athlete_rejected(self, api):
        """PRD §3.3: "every athlete referenced by an ADD or UPDATE_ATTRIBUTE
        entry must currently be ELIGIBLE (an ineligible athlete surfaces
        ERR_ATHLETE_NOT_ELIGIBLE)."

        Design: Difficulty/cross_entity_state_dependency/roster_entry_validation_depends_on_athlete_eligibility
        """
        agreement = create_active_agreement()
        season = get_success_data(
            api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
        )
        athlete = get_success_data(
            api_client.create_athlete(
                create_athlete_payload(full_name="No Grant"), RIGHTS
            )
        )  # no likeness grant => INELIGIBLE
        op = make_roster_operator_headers("op-1")
        batch = get_success_data(
            api_client.create_roster_batch(
                create_roster_batch_payload(season["id"], batch_label="B"), op
            )
        )
        get_success_data(
            api_client.add_roster_entry(
                batch["id"],
                create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                            overall_rating=80),
                op,
            )
        )
        resp = api_client.validate_roster_batch(batch["id"], op)
        validate_error(resp, ApiErrorId.ERR_ATHLETE_NOT_ELIGIBLE.value)

    def test_batch_remains_draft_after_ineligible_rejection(self, api):
        """PRD §3.3: "A newly registered athlete has athlete_status of
        INELIGIBLE and a null current_overall_rating; only roster publication
        populates the rating."

        Design: Difficulty/cross_entity_state_dependency/roster_entry_validation_depends_on_athlete_eligibility
        """
        agreement = create_active_agreement()
        season = get_success_data(
            api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
        )
        athlete = get_success_data(
            api_client.create_athlete(
                create_athlete_payload(full_name="No Grant"), RIGHTS
            )
        )
        assert athlete["athlete_status"] == "INELIGIBLE"
        op = make_roster_operator_headers("op-1")
        batch = get_success_data(
            api_client.create_roster_batch(
                create_roster_batch_payload(season["id"], batch_label="B"), op
            )
        )
        get_success_data(
            api_client.add_roster_entry(
                batch["id"],
                create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                            overall_rating=80),
                op,
            )
        )
        api_client.validate_roster_batch(batch["id"], op)
        batch_after = get_success_data(api_client.get_roster_batch(batch["id"], op))
        assert batch_after["batch_status"] == "DRAFT"


class TestSeasonLaunchDependsOnAgreementActive:
    def test_launch_blocked_when_agreement_suspended(self, api):
        """PRD §3.3: "Launching moves a PRELAUNCH season to LIVE and requires
        the governing agreement to be ACTIVE (otherwise ERR_REFERENCE_STATE)."

        Design: Difficulty/cross_entity_state_dependency/season_launch_depends_on_agreement_active
        """
        agreement = create_active_agreement()
        athlete, _ = create_eligible_athlete(agreement["id"])
        season = get_success_data(
            api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
        )
        create_published_batch(
            season["id"],
            [create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                         overall_rating=80)],
        )
        get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))

        resp = api_client.launch_season(season["id"], LIVEOPS)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_STATE.value)

    def test_season_remains_prelaunch_after_blocked_launch(self, api):
        """PRD §3.3: "The new season is PRELAUNCH with roster_epoch at 0."

        Design: Difficulty/cross_entity_state_dependency/season_launch_depends_on_agreement_active
        """
        agreement = create_active_agreement()
        athlete, _ = create_eligible_athlete(agreement["id"])
        season = get_success_data(
            api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
        )
        create_published_batch(
            season["id"],
            [create_roster_entry_payload(athlete["id"], entry_kind="ADD",
                                         overall_rating=80)],
        )
        get_success_data(api_client.suspend_agreement(agreement["id"], ADMIN))
        api_client.launch_season(season["id"], LIVEOPS)

        season_after = get_success_data(api_client.get_season(season["id"], LIVEOPS))
        assert season_after["season_status"] == "PRELAUNCH"
        assert season_after["roster_epoch"] == 1, (
            "the published batch is still there; only the launch was blocked"
        )
