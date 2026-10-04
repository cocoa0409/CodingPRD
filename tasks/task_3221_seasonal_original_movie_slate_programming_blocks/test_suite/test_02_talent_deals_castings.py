"""Talent deals and castings: cyclic fulfillment loop, confirm guards."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, make_studio, make_season, make_locked_season, make_title, approve_title,
    make_location, book_slot, setup_locked_season_with_approved_title,
    setup_talent_with_deal, make_talent, make_deal, make_casting, confirm_casting,
)
from test_helpers.fixtures import ADMIN, PLANNER, PROD, EXEC, ADS, STREAM, LIC


def _two_approved_titles_season():
    """LOCKED season (required 2) with two approved titles. Returns ctx dict."""
    set_clock("2027-03-01T00:00:00Z")
    studio = make_studio()
    season, sv = make_locked_season(studio["id"], required_title_count=2)
    t1 = make_title(season["id"], name="T1", genre="ROMANCE", tone_rating="WARM")
    approve_title(t1["id"], sv)
    season = get_success_data(api_client.get_season(season["id"], ADMIN))
    t2 = make_title(season["id"], name="T2", genre="FAMILY", tone_rating="GENTLE")
    approve_title(t2["id"], season["version"])
    season = get_success_data(api_client.get_season(season["id"], ADMIN))
    return {"studio": studio, "season": season, "season_version": season["version"],
            "t1": t1, "t2": t2}


class TestTalentDealCyclicFulfilledActiveLoop:
    def test_two_confirms_flip_deal_to_fulfilled(self, api):
        """PRD §3.4: "A successful confirm moves the casting `ATTACHED → CONFIRMED`
        and recomputes the deal's `fulfilled_pictures` as the count of distinct
        `CONFIRMED` castings for the deal's talent whose titles belong to the
        deal's season; when the count reaches the `picture_commitment`, the deal
        flips `ACTIVE → FULFILLED` automatically."

        Design: Difficulty/non_linear_state_machine/talent_deal_cyclic_fulfilled_active_loop
        """
        ctx = _two_approved_titles_season()
        talent, agent, deal = setup_talent_with_deal(
            ctx["season"]["id"], ctx["studio"]["id"], picture_commitment=2,
            availability_windows=[{"start": "2027-03-01T00:00:00Z", "end": "2027-05-01T00:00:00Z"}])
        c1 = make_casting(ctx["t1"]["id"], talent["id"], agent)
        confirm_casting(c1["id"], agent)
        c2 = make_casting(ctx["t2"]["id"], talent["id"], agent)
        confirm_casting(c2["id"], agent)
        deal_after = get_success_data(api_client.get_deal(deal["id"], agent))
        assert deal_after["status"] == "FULFILLED"
        assert deal_after["fulfilled_pictures"] == 2

    def test_release_flips_fulfilled_deal_back_to_active(self, api):
        """PRD §3.4: "Releasing a `CONFIRMED` casting — whether directly by a
        `TalentAgent` or through the title-cancel cascade — moves it to the
        terminal `RELEASED` state and recomputes the same counter in the other
        direction: if the deal was `FULFILLED` and the count drops below the
        commitment, the deal flips `FULFILLED → ACTIVE`."

        Design: Difficulty/non_linear_state_machine/talent_deal_cyclic_fulfilled_active_loop
        """
        ctx = _two_approved_titles_season()
        talent, agent, deal = setup_talent_with_deal(
            ctx["season"]["id"], ctx["studio"]["id"], picture_commitment=2,
            availability_windows=[{"start": "2027-03-01T00:00:00Z", "end": "2027-05-01T00:00:00Z"}])
        c1 = make_casting(ctx["t1"]["id"], talent["id"], agent)
        confirm_casting(c1["id"], agent)
        c2 = make_casting(ctx["t2"]["id"], talent["id"], agent)
        confirm_casting(c2["id"], agent)
        assert get_success_data(api_client.get_deal(deal["id"], agent))["status"] == "FULFILLED"
        released = validate_success(api_client.release_casting(c2["id"], agent))
        assert released["status"] == "RELEASED"
        deal_after = get_success_data(api_client.get_deal(deal["id"], agent))
        assert deal_after["status"] == "ACTIVE"
        assert deal_after["fulfilled_pictures"] == 1


class TestCastingConfirmGuards:
    def test_confirm_from_confirmed_is_invalid_state(self, api):
        """PRD §3.4: "Confirming an `ATTACHED` casting requires the title to be
        `APPROVED` or `IN_PRODUCTION` (otherwise `ERR_INVALID_STATE`)" — and the
        casting resource itself must be in a state from which the requested
        transition exists (PRD §2.7 item 6, `ERR_INVALID_STATE`).

        Design: Corner/state_machines/casting_confirm_from_confirmed_is_invalid_state
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        talent, agent, deal = setup_talent_with_deal(ctx["season"]["id"], ctx["studio"]["id"])
        c1 = make_casting(ctx["title"]["id"], talent["id"], agent)
        confirm_casting(c1["id"], agent)
        # deal is now FULFILLED with fulfilled_pictures == 1
        resp = api_client.confirm_casting(c1["id"], agent)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        deal_after = get_success_data(api_client.get_deal(deal["id"], agent))
        assert deal_after["fulfilled_pictures"] == 1, "confirm must not double-count"
        assert deal_after["status"] == "FULFILLED"

    def test_confirm_without_active_deal_returns_talent_unavailable(self, api):
        """PRD §3.4: "it requires an `ACTIVE` deal to exist for this talent in the
        title's season — if no such deal exists the confirm is rejected with
        `ERR_TALENT_UNAVAILABLE`".

        Design: Corner/errors/casting_confirm_without_active_deal_returns_talent_unavailable
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        talent, agent = make_talent(
            ctx["studio"]["id"],
            availability_windows=[{"start": "2027-01-01T00:00:00Z", "end": "2027-12-01T00:00:00Z"}])
        c1 = make_casting(ctx["title"]["id"], talent["id"], agent)
        resp = api_client.confirm_casting(c1["id"], agent)
        validate_error(resp, ApiErrorId.ERR_TALENT_UNAVAILABLE)
        casting_after = get_success_data(api_client.get_casting(c1["id"], agent))
        assert casting_after["status"] == "ATTACHED"
