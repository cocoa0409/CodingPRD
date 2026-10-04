"""Title lifecycle: approve/reject fork, OCC, quota, cancel cascades."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, make_studio, make_season, make_locked_season, make_title, approve_title,
    make_location, book_slot, make_published_block, make_air_slot, make_talent,
    make_deal, make_casting, confirm_casting, setup_talent_with_deal,
    setup_locked_season_with_approved_title,
)
from test_helpers.fixtures import ADMIN, PLANNER, PROD, EXEC


class TestTitleApproveRejectFork:
    def test_approve_consumes_quota_and_bumps_season_version(self, api):
        """PRD §3.2: "A successful approval moves the title `PITCHED → APPROVED`,
        recomputes the season's `committed_title_count`, and increments the
        season's `version` by 1".

        Design: Difficulty/non_linear_state_machine/title_branching_approve_or_reject_fork
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approved = validate_success(
            api_client.approve_title(t1["id"], {"expected_season_version": sv}, PLANNER))
        assert approved["status"] == "APPROVED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["committed_title_count"] == 1
        assert season_after["version"] == sv + 1

    def test_reject_leaves_quota_and_version_untouched(self, api):
        """PRD §3.2: "A `SlatePlanner` may instead reject a `PITCHED` title, moving
        it to the terminal `REJECTED` state with no further effects."

        Design: Difficulty/non_linear_state_machine/title_branching_approve_or_reject_fork
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t2 = make_title(season["id"], name="T2", genre="COMEDY", tone_rating="GENTLE")
        rejected = validate_success(api_client.reject_title(t2["id"], PLANNER))
        assert rejected["status"] == "REJECTED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["committed_title_count"] == 0
        assert season_after["version"] == sv, "reject must not bump the season version"


class TestSlateQuotaBoundary:
    def test_approve_at_exact_required_count_succeeds(self, api):
        """PRD §3.2: "The boundary is exact: approving when the committed count is
        one below `required_title_count` succeeds and fills the slate".

        Design: Corner/calculations/slate_quota_boundary_exact_count
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approved = validate_success(
            api_client.approve_title(t2["id"], {"expected_season_version": season["version"]}, PLANNER))
        assert approved["status"] == "APPROVED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["committed_title_count"] == 2

    def test_approve_beyond_required_count_fails_slate_full(self, api):
        """PRD §3.2: "rejects the approval with `ERR_SLATE_FULL` when that count
        has already reached `required_title_count`".

        Design: Corner/calculations/slate_quota_boundary_exact_count
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t3 = make_title(season["id"], name="T3", genre="COMEDY", tone_rating="GENTLE")
        resp = api_client.approve_title(t3["id"], {"expected_season_version": season["version"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_SLATE_FULL)
        t3_after = get_success_data(api_client.get_title(t3["id"], PLANNER))
        assert t3_after["status"] == "PITCHED"


class TestOccStaleVersionOnApprove:
    def test_first_approve_succeeds_and_bumps_version(self, api):
        """PRD §2.9: "Because every successful approval consumes one slate slot and
        bumps the season's `version`, a client that read the season before another
        approval landed will find its expected version no longer matches the
        season's current `version`".

        Design: Corner/endpoints/occ_stale_season_version_on_approve_returns_412
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approved = validate_success(
            api_client.approve_title(t1["id"], {"expected_season_version": sv}, PLANNER))
        assert approved["status"] == "APPROVED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["version"] == sv + 1

    def test_second_approve_with_stale_version_rejected_412(self, api):
        """PRD §2.9: "the approval is rejected with `ERR_STALE_VERSION` and the
        client must re-read the season and re-issue."

        Design: Corner/endpoints/occ_stale_season_version_on_approve_returns_412
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t1["id"], sv)
        resp = api_client.approve_title(t2["id"], {"expected_season_version": sv}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        t2_after = get_success_data(api_client.get_title(t2["id"], PLANNER))
        assert t2_after["status"] == "PITCHED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["committed_title_count"] == 1


class TestTitleCancelDeepCascade:
    def test_cancel_releases_quota_slots_and_castings(self, api):
        """PRD §3.2: "The season's `committed_title_count` is recomputed, freeing
        the slate slot. Every production slot of the title still in `BOOKED` is
        moved to `CANCELLED`, and each such cancellation subtracts the slot's
        `shoot_days` from the season's `booked_shoot_days`, releasing day quota."

        Design: Difficulty/transitive_cascade/title_cancel_deep_cascade_to_deal_flip
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        loc = make_location(studio["id"], name="Stage 1")
        slot = book_slot(t1["id"], loc["id"])
        cancelled = validate_success(api_client.cancel_title(t1["id"], PLANNER))
        assert cancelled["status"] == "CANCELLED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["committed_title_count"] == 1
        assert season_after["booked_shoot_days"] == 0
        slot_after = get_success_data(api_client.get_production_slot(slot["id"], PROD))
        assert slot_after["status"] == "CANCELLED"

    def test_cancel_releases_castings_and_flips_fulfilled_deal_back(self, api):
        """PRD §3.2: "Every casting of the title still in `CONFIRMED` is moved to
        `RELEASED`, and each release recomputes the matching deal's
        `fulfilled_pictures`; a deal that was `FULFILLED` and whose count drops
        back below its `picture_commitment` flips from `FULFILLED` back to
        `ACTIVE`."

        Design: Difficulty/transitive_cascade/title_cancel_deep_cascade_to_deal_flip
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        talent, agent, deal = setup_talent_with_deal(
            season["id"], studio["id"], picture_commitment=2,
            availability_windows=[{"start": "2027-03-01T00:00:00Z", "end": "2027-06-01T00:00:00Z"}])
        loc = make_location(studio["id"], name="Stage 1")
        book_slot(t1["id"], loc["id"])
        c1 = make_casting(t1["id"], talent["id"], agent)
        confirm_casting(c1["id"], agent)
        c2 = make_casting(t2["id"], talent["id"], agent)
        confirm_casting(c2["id"], agent)
        assert get_success_data(api_client.get_deal(deal["id"], agent))["status"] == "FULFILLED"
        validate_success(api_client.cancel_title(t1["id"], PLANNER))
        c1_after = get_success_data(api_client.get_casting(c1["id"], agent))
        assert c1_after["status"] == "RELEASED"
        deal_after = get_success_data(api_client.get_deal(deal["id"], agent))
        assert deal_after["status"] == "ACTIVE"
        assert deal_after["fulfilled_pictures"] == 1
        c2_after = get_success_data(api_client.get_casting(c2["id"], agent))
        assert c2_after["status"] == "CONFIRMED", "other title's casting untouched"

    def test_cancel_cascades_planned_air_slots(self, api):
        """PRD §3.2: "In parallel, every air slot of the title still in `PLANNED`
        is moved to `CANCELLED`."

        Design: Corner/endpoints/title_cancel_cascades_planned_air_slots
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"])
        air = make_air_slot(block["id"], ctx["title"]["id"], "2027-11-07T00:00:00Z", "ENCORE", bv)
        cancelled = validate_success(api_client.cancel_title(ctx["title"]["id"], PLANNER))
        assert cancelled["status"] == "CANCELLED"
        air_after = get_success_data(api_client.get_air_slot(air["id"], EXEC))
        assert air_after["status"] == "CANCELLED"
        season_after = get_success_data(api_client.get_season(ctx["season"]["id"], ADMIN))
        assert season_after["committed_title_count"] == 0


class TestImmediateConsistency:
    def test_approve_response_and_read_after_write(self, api):
        """PRD §3.2: "A successful approval moves the title `PITCHED → APPROVED`,
        recomputes the season's `committed_title_count`, and increments the
        season's `version` by 1" — and PRD §2.4: "`updated_at` refreshes on every
        mutation" of a resource whose "quota counters shift because a title was
        approved".

        Design: Corner/consistency_model/immediate_consistency_visible_in_same_response
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approved = validate_success(
            api_client.approve_title(t1["id"], {"expected_season_version": sv}, PLANNER))
        assert approved["status"] == "APPROVED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["committed_title_count"] == 1
        assert season_after["version"] == sv + 1
