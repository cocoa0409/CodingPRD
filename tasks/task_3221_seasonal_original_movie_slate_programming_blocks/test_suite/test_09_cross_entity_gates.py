"""Cross-entity state gates: approve vs season lock, availability containment,
validation priority pairs."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, make_studio, make_season, make_locked_season, make_title, approve_title,
    make_location, book_slot, make_talent, make_deal, make_casting, confirm_casting,
    setup_talent_with_deal,
)
from test_helpers.fixtures import ADMIN, PLANNER, PROD, EXEC


class TestTitleApproveRequiresSeasonLocked:
    def test_approve_against_draft_season_rejected(self, api):
        """PRD §3.1: "Locking is the gate that arms title approval and block
        publication; attempting either against a season that is not `LOCKED`
        fails with `ERR_SEASON_NOT_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/title_approve_requires_season_locked
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season = make_season(studio["id"], required_title_count=1)
        t1 = make_title(season["id"], name="T1")
        resp = api_client.approve_title(
            t1["id"], {"expected_season_version": season["version"]}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_LOCKED)

    def test_approve_after_lock_succeeds(self, api):
        """PRD §3.1: "When the plan is ready, a `ProgrammingExec` locks the season,
        transitioning `DRAFT → LOCKED`" and PRD §3.2: "A successful approval
        moves the title `PITCHED → APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/title_approve_requires_season_locked
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season = make_season(studio["id"], required_title_count=1)
        t1 = make_title(season["id"], name="T1")
        locked = validate_success(api_client.lock_season(season["id"], EXEC))
        approved = validate_success(
            api_client.approve_title(t1["id"], {"expected_season_version": locked["version"]}, PLANNER))
        assert approved["status"] == "APPROVED"


class TestStateVsBrandSafetyOnApprove:
    def test_rejected_title_with_forbidden_flag_reports_invalid_state(self, api):
        """PRD §2.7: "When a request fails several rules at once, the error the
        caller observes is determined by a fixed priority order" with "6.
        **State legality**" listed before "7. **Brand consistency**".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_brand_safety_on_approve
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="Gory Christmas", genre="MYSTERY",
                        tone_rating="WARM", content_flags=["VIOLENCE"])
        validate_success(api_client.reject_title(t1["id"], PLANNER))
        resp = api_client.approve_title(t1["id"], {"expected_season_version": sv}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        title_after = get_success_data(api_client.get_title(t1["id"], PLANNER))
        assert title_after["status"] == "REJECTED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["committed_title_count"] == 0

    def test_pitched_title_with_forbidden_flag_reports_brand_violation(self, api):
        """PRD §3.2: "the title's `content_flags` must not include any of
        `VIOLENCE`, `GAMBLING`, or `HORROR` (`ALCOHOL` is permitted)" and "Either
        violation is rejected with `ERR_BRAND_VIOLATION` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_brand_safety_on_approve
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="Gory Christmas", genre="MYSTERY",
                        tone_rating="WARM", content_flags=["VIOLENCE"])
        resp = api_client.approve_title(t1["id"], {"expected_season_version": sv}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_BRAND_VIOLATION)


class TestTalentAvailabilitySingleWindowContainment:
    def _setup_shot_titles(self):
        """Two approved titles, each with a BOOKED slot 03-10..03-20 on its own
        location."""
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        loc_a = make_location(studio["id"], name="Stage A")
        loc_b = make_location(studio["id"], name="Stage B")
        book_slot(t1["id"], loc_a["id"], "2027-03-10T00:00:00Z", "2027-03-20T00:00:00Z", 10)
        book_slot(t2["id"], loc_b["id"], "2027-03-10T00:00:00Z", "2027-03-20T00:00:00Z", 10)
        return {"studio": studio, "season": season, "t1": t1, "t2": t2}

    def test_adjacent_window_union_does_not_satisfy_containment(self, api):
        """PRD §3.4: "requires that single slot's entire shoot interval to be fully
        contained within one single availability window; coverage pieced together
        across multiple windows does not count, and a failure is rejected with
        `ERR_TALENT_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/talent_availability_single_window_containment
        """
        ctx = self._setup_shot_titles()
        talent_a, agent_a = make_talent(
            ctx["studio"]["id"], stage_name="Star A",
            availability_windows=[{"start": "2027-03-01T00:00:00Z", "end": "2027-03-15T00:00:00Z"},
                                  {"start": "2027-03-15T00:00:00Z", "end": "2027-04-01T00:00:00Z"}])
        make_deal(talent_a["id"], ctx["season"]["id"], agent_a, picture_commitment=1)
        cast_a = make_casting(ctx["t1"]["id"], talent_a["id"], agent_a)
        resp = api_client.confirm_casting(cast_a["id"], agent_a)
        validate_error(resp, ApiErrorId.ERR_TALENT_UNAVAILABLE)
        casting_after = get_success_data(api_client.get_casting(cast_a["id"], agent_a))
        assert casting_after["status"] == "ATTACHED"

    def test_exact_inclusive_bound_containment_passes(self, api):
        """PRD §3.4: "Containment against these windows is endpoint-inclusive: a
        shoot that begins exactly at a window's start or ends exactly at its end
        is contained."

        Design: Difficulty/resource_temporal_overlap/talent_availability_single_window_containment
        """
        ctx = self._setup_shot_titles()
        talent_b, agent_b = make_talent(
            ctx["studio"]["id"], stage_name="Star B",
            availability_windows=[{"start": "2027-03-10T00:00:00Z", "end": "2027-03-20T00:00:00Z"}])
        make_deal(talent_b["id"], ctx["season"]["id"], agent_b, picture_commitment=1)
        cast_b = make_casting(ctx["t2"]["id"], talent_b["id"], agent_b)
        confirmed = validate_success(api_client.confirm_casting(cast_b["id"], agent_b))
        assert confirmed["status"] == "CONFIRMED"
