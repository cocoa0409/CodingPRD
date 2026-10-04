"""API client: one method per endpoint defined in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── League ───────────────────────────────────────
    def create_league(self, payload, headers):
        return self._request("POST", "/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/leagues/{league_id}", headers=headers)

    def list_leagues(self, headers, params=None):
        return self._request("GET", "/leagues", headers=headers, params=params)

    # ─── Charter renewal ──────────────────────────────
    def create_charter_renewal(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/charter-renewals",
                             payload, headers)

    def list_charter_renewals(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/charter-renewals",
                             headers=headers, params=params)

    def decide_charter_renewal(self, league_id, renewal_id, payload, headers):
        return self._request(
            "POST",
            f"/leagues/{league_id}/charter-renewals/{renewal_id}/decide",
            payload, headers)

    # ─── Division ─────────────────────────────────────
    def list_divisions(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/divisions",
                             headers=headers, params=params)

    def patch_division(self, league_id, division_id, payload, headers):
        return self._request("PATCH",
                             f"/leagues/{league_id}/divisions/{division_id}",
                             payload, headers)

    # ─── Player ───────────────────────────────────────
    def create_player(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/players",
                             payload, headers)

    def list_players(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/players",
                             headers=headers, params=params)

    def create_eligibility_document(self, league_id, player_id, payload, headers):
        return self._request(
            "POST",
            f"/leagues/{league_id}/players/{player_id}/eligibility-documents",
            payload, headers)

    def list_eligibility_documents(self, league_id, player_id, headers, params=None):
        return self._request(
            "GET",
            f"/leagues/{league_id}/players/{player_id}/eligibility-documents",
            headers=headers, params=params)

    def verify_eligibility(self, league_id, player_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leagues/{league_id}/players/{player_id}/verify-eligibility",
            payload or {}, headers)

    def revoke_eligibility(self, league_id, player_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leagues/{league_id}/players/{player_id}/revoke-eligibility",
            payload or {}, headers)

    # ─── Boundary waiver ──────────────────────────────
    def create_boundary_waiver(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/boundary-waivers",
                             payload, headers)

    def list_boundary_waivers(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/boundary-waivers",
                             headers=headers, params=params)

    def decide_boundary_waiver(self, league_id, waiver_id, payload, headers):
        return self._request(
            "POST",
            f"/leagues/{league_id}/boundary-waivers/{waiver_id}/decide",
            payload, headers)

    # ─── Volunteer / screening ────────────────────────
    def create_volunteer(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/volunteers",
                             payload, headers)

    def list_volunteers(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/volunteers",
                             headers=headers, params=params)

    def create_screening(self, league_id, volunteer_id, payload, headers):
        return self._request(
            "POST",
            f"/leagues/{league_id}/volunteers/{volunteer_id}/screenings",
            payload, headers)

    def list_screenings(self, league_id, volunteer_id, headers, params=None):
        return self._request(
            "GET",
            f"/leagues/{league_id}/volunteers/{volunteer_id}/screenings",
            headers=headers, params=params)

    def adjudicate_screening(self, league_id, volunteer_id, screening_id,
                             payload, headers):
        return self._request(
            "POST",
            f"/leagues/{league_id}/volunteers/{volunteer_id}/screenings/{screening_id}/adjudicate",
            payload, headers)

    # ─── Insurance certificate ────────────────────────
    def create_insurance_certificate(self, league_id, payload, headers):
        return self._request("POST",
                             f"/leagues/{league_id}/insurance-certificates",
                             payload, headers)

    def list_insurance_certificates(self, league_id, headers, params=None):
        return self._request("GET",
                             f"/leagues/{league_id}/insurance-certificates",
                             headers=headers, params=params)

    # ─── All-star roster ──────────────────────────────
    def create_all_star_roster(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/all-star-rosters",
                             payload, headers)

    def list_all_star_rosters(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/all-star-rosters",
                             headers=headers, params=params)

    def add_roster_selection(self, league_id, roster_id, payload, headers):
        return self._request(
            "POST",
            f"/leagues/{league_id}/all-star-rosters/{roster_id}/selections",
            payload, headers)

    def submit_roster(self, league_id, roster_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leagues/{league_id}/all-star-rosters/{roster_id}/submit",
            payload or {}, headers)

    # ─── Tournament entry ─────────────────────────────
    def create_tournament_entry(self, league_id, payload, headers):
        return self._request("POST", f"/leagues/{league_id}/tournament-entries",
                             payload, headers)

    def list_tournament_entries(self, league_id, headers, params=None):
        return self._request("GET", f"/leagues/{league_id}/tournament-entries",
                             headers=headers, params=params)

    def advance_entry(self, entry_id, headers, payload=None):
        return self._request("POST", f"/tournament-entries/{entry_id}/advance",
                             payload or {}, headers)

    # ─── Tournament game ──────────────────────────────
    def create_game(self, entry_id, headers, payload=None):
        return self._request("POST", f"/tournament-entries/{entry_id}/games",
                             payload or {}, headers)

    def list_games(self, entry_id, headers, params=None):
        return self._request("GET", f"/tournament-entries/{entry_id}/games",
                             headers=headers, params=params)

    def finalize_game(self, entry_id, game_id, payload, headers):
        return self._request(
            "POST",
            f"/tournament-entries/{entry_id}/games/{game_id}/finalize",
            payload, headers)

    # ─── Pitching appearance ──────────────────────────
    def record_pitching_appearance(self, entry_id, game_id, payload, headers):
        return self._request(
            "POST",
            f"/tournament-entries/{entry_id}/games/{game_id}/pitching-appearances",
            payload, headers)

    def list_pitching_appearances(self, entry_id, game_id, headers, params=None):
        return self._request(
            "GET",
            f"/tournament-entries/{entry_id}/games/{game_id}/pitching-appearances",
            headers=headers, params=params)

    # ─── Protest ──────────────────────────────────────
    def file_protest(self, entry_id, game_id, payload, headers):
        return self._request(
            "POST",
            f"/tournament-entries/{entry_id}/games/{game_id}/protests",
            payload, headers)

    def list_protests(self, entry_id, game_id, headers, params=None):
        return self._request(
            "GET",
            f"/tournament-entries/{entry_id}/games/{game_id}/protests",
            headers=headers, params=params)

    def resolve_protest(self, entry_id, game_id, protest_id, payload, headers):
        return self._request(
            "POST",
            f"/tournament-entries/{entry_id}/games/{game_id}/protests/{protest_id}/resolve",
            payload, headers)

    # ─── Cross-league filtered collections ────────────
    def list_all_charter_renewals(self, headers, params=None):
        return self._request("GET", "/leagues/charter-renewals",
                             headers=headers, params=params)

    def list_all_divisions(self, headers, params=None):
        return self._request("GET", "/leagues/divisions",
                             headers=headers, params=params)

    def list_all_players(self, headers, params=None):
        return self._request("GET", "/leagues/players",
                             headers=headers, params=params)

    def list_all_eligibility_documents(self, headers, params=None):
        return self._request("GET", "/leagues/eligibility-documents",
                             headers=headers, params=params)

    def list_all_boundary_waivers(self, headers, params=None):
        return self._request("GET", "/leagues/boundary-waivers",
                             headers=headers, params=params)

    def list_all_volunteers(self, headers, params=None):
        return self._request("GET", "/leagues/volunteers",
                             headers=headers, params=params)

    def list_all_screenings(self, headers, params=None):
        return self._request("GET", "/leagues/screenings",
                             headers=headers, params=params)

    def list_all_insurance_certificates(self, headers, params=None):
        return self._request("GET", "/leagues/insurance-certificates",
                             headers=headers, params=params)

    def list_all_all_star_rosters(self, headers, params=None):
        return self._request("GET", "/leagues/all-star-rosters",
                             headers=headers, params=params)

    def list_all_tournament_entries(self, headers, params=None):
        return self._request("GET", "/leagues/tournament-entries",
                             headers=headers, params=params)

    def list_all_games(self, headers, params=None):
        return self._request("GET", "/leagues/games",
                             headers=headers, params=params)

    def list_all_pitching_appearances(self, headers, params=None):
        return self._request("GET", "/leagues/pitching-appearances",
                             headers=headers, params=params)

    def list_all_protests(self, headers, params=None):
        return self._request("GET", "/leagues/protests",
                             headers=headers, params=params)

    # ─── Detail reads ─────────────────────────────────
    def get_charter_renewal_detail(self, renewal_id, headers):
        return self._request("GET", f"/leagues/charter-renewals/{renewal_id}",
                             headers=headers)

    def get_division_detail(self, division_id, headers):
        return self._request("GET", f"/leagues/divisions/{division_id}",
                             headers=headers)

    def get_player_detail(self, player_id, headers):
        return self._request("GET", f"/leagues/players/{player_id}",
                             headers=headers)

    def get_boundary_waiver_detail(self, waiver_id, headers):
        return self._request("GET", f"/leagues/boundary-waivers/{waiver_id}",
                             headers=headers)

    def get_volunteer_detail(self, volunteer_id, headers):
        return self._request("GET", f"/leagues/volunteers/{volunteer_id}",
                             headers=headers)

    def get_screening_detail(self, screening_id, headers):
        return self._request("GET", f"/leagues/screenings/{screening_id}",
                             headers=headers)

    def get_insurance_certificate_detail(self, certificate_id, headers):
        return self._request(
            "GET", f"/leagues/insurance-certificates/{certificate_id}",
            headers=headers)

    def get_all_star_roster_detail(self, roster_id, headers):
        return self._request("GET", f"/leagues/all-star-rosters/{roster_id}",
                             headers=headers)

    def get_tournament_entry_detail(self, entry_id, headers):
        return self._request("GET", f"/leagues/tournament-entries/{entry_id}",
                             headers=headers)

    def get_game_detail(self, game_id, headers):
        return self._request("GET", f"/leagues/games/{game_id}",
                             headers=headers)

    def get_pitching_appearance_detail(self, appearance_id, headers):
        return self._request("GET",
                             f"/leagues/pitching-appearances/{appearance_id}",
                             headers=headers)

    def get_protest_detail(self, protest_id, headers):
        return self._request("GET", f"/leagues/protests/{protest_id}",
                             headers=headers)


api_client = ApiClient()
