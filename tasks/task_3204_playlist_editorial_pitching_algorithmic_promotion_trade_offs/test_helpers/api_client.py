"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/catalog/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---- artists --------------------------------------------------------
    def create_artist(self, payload, headers):
        return self._request("POST", "/catalog/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/catalog/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", "/catalog/artists", headers=headers, params=params)

    def suspend_artist(self, artist_id, headers):
        return self._request("POST", f"/catalog/artists/{artist_id}/suspend", {}, headers)

    def reinstate_artist(self, artist_id, headers):
        return self._request("POST", f"/catalog/artists/{artist_id}/reinstate", {}, headers)

    # ---- releases -------------------------------------------------------
    def create_release(self, payload, headers):
        return self._request("POST", "/catalog/releases", payload, headers)

    def get_release(self, release_id, headers):
        return self._request("GET", f"/catalog/releases/{release_id}", headers=headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", "/catalog/releases", headers=headers, params=params)

    def change_release_date(self, release_id, payload, headers):
        return self._request(
            "POST", f"/catalog/releases/{release_id}/change-date", payload, headers
        )

    def remove_release(self, release_id, headers):
        return self._request("POST", f"/catalog/releases/{release_id}/remove", {}, headers)

    # ---- tracks ---------------------------------------------------------
    def create_track(self, payload, headers):
        return self._request("POST", "/catalog/tracks", payload, headers)

    def get_track(self, track_id, headers):
        return self._request("GET", f"/catalog/tracks/{track_id}", headers=headers)

    def list_tracks(self, headers, params=None):
        return self._request("GET", "/catalog/tracks", headers=headers, params=params)

    def signal_rollup(self, track_id, payload, headers):
        return self._request(
            "POST", f"/catalog/tracks/{track_id}/signal-rollup", payload, headers
        )

    # ---- playlists ------------------------------------------------------
    def create_playlist(self, payload, headers):
        return self._request("POST", "/catalog/playlists", payload, headers)

    def get_playlist(self, playlist_id, headers):
        return self._request("GET", f"/catalog/playlists/{playlist_id}", headers=headers)

    def list_playlists(self, headers, params=None):
        return self._request("GET", "/catalog/playlists", headers=headers, params=params)

    def retire_playlist(self, playlist_id, headers):
        return self._request(
            "POST", f"/catalog/playlists/{playlist_id}/retire", {}, headers
        )

    # ---- pitches --------------------------------------------------------
    def create_pitch(self, payload, headers):
        return self._request("POST", "/catalog/pitches", payload, headers)

    def get_pitch(self, pitch_id, headers):
        return self._request("GET", f"/catalog/pitches/{pitch_id}", headers=headers)

    def list_pitches(self, headers, params=None):
        return self._request("GET", "/catalog/pitches", headers=headers, params=params)

    def claim_pitch(self, pitch_id, team, headers):
        return self._request(
            "POST", f"/catalog/pitches/{pitch_id}/claim", {"team": team}, headers
        )

    def request_revision(self, pitch_id, headers):
        return self._request(
            "POST", f"/catalog/pitches/{pitch_id}/request-revision", {}, headers
        )

    def revise_pitch(self, pitch_id, pitch_text, headers):
        return self._request(
            "POST", f"/catalog/pitches/{pitch_id}/revise", {"pitch_text": pitch_text}, headers
        )

    def decide_pitch(self, pitch_id, decision, headers):
        return self._request(
            "POST", f"/catalog/pitches/{pitch_id}/decide", {"decision": decision}, headers
        )

    def withdraw_pitch(self, pitch_id, headers):
        return self._request(
            "POST", f"/catalog/pitches/{pitch_id}/withdraw", {}, headers
        )

    # ---- placements -----------------------------------------------------
    def get_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/catalog/placements/{placement_id}", headers=headers
        )

    def list_placements(self, headers, params=None):
        return self._request("GET", "/catalog/placements", headers=headers, params=params)

    def activate_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/catalog/placements/{placement_id}/activate", {}, headers
        )

    def rotate_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/catalog/placements/{placement_id}/rotate", {}, headers
        )

    def reinstate_placement(self, placement_id, headers):
        return self._request(
            "POST", f"/catalog/placements/{placement_id}/reinstate", {}, headers
        )

    # ---- promotions -----------------------------------------------------
    def create_promotion(self, payload, headers):
        return self._request("POST", "/catalog/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/catalog/promotions/{promotion_id}", headers=headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/catalog/promotions", headers=headers, params=params)

    def suspend_promotion(self, promotion_id, disclosure_token, headers):
        return self._request(
            "POST",
            f"/catalog/promotions/{promotion_id}/suspend",
            {"disclosure_token": disclosure_token},
            headers,
        )

    def resume_promotion(self, promotion_id, headers):
        return self._request(
            "POST", f"/catalog/promotions/{promotion_id}/resume", {}, headers
        )

    def terminate_promotion(self, promotion_id, headers):
        return self._request(
            "POST", f"/catalog/promotions/{promotion_id}/terminate", {}, headers
        )

    # ---- streams --------------------------------------------------------
    def create_stream(self, payload, headers):
        return self._request("POST", "/catalog/streams", payload, headers)

    def get_stream(self, stream_id, headers):
        return self._request("GET", f"/catalog/streams/{stream_id}", headers=headers)

    def list_streams(self, headers, params=None):
        return self._request("GET", "/catalog/streams", headers=headers, params=params)

    # ---- fraud cases ----------------------------------------------------
    def create_fraud_case(self, payload, headers):
        return self._request("POST", "/catalog/fraud-cases", payload, headers)

    def get_fraud_case(self, case_id, headers):
        return self._request("GET", f"/catalog/fraud-cases/{case_id}", headers=headers)

    def list_fraud_cases(self, headers, params=None):
        return self._request("GET", "/catalog/fraud-cases", headers=headers, params=params)

    def adjudicate_fraud_case(self, case_id, verdict, headers):
        return self._request(
            "POST", f"/catalog/fraud-cases/{case_id}/adjudicate", {"verdict": verdict}, headers
        )

    # ---- royalty periods / statements -----------------------------------
    def create_royalty_period(self, payload, headers):
        return self._request("POST", "/catalog/royalty-periods", payload, headers)

    def get_royalty_period(self, period_id, headers):
        return self._request(
            "GET", f"/catalog/royalty-periods/{period_id}", headers=headers
        )

    def list_royalty_periods(self, headers, params=None):
        return self._request(
            "GET", "/catalog/royalty-periods", headers=headers, params=params
        )

    def close_royalty_period(self, period_id, payload, headers):
        return self._request(
            "POST", f"/catalog/royalty-periods/{period_id}/close", payload, headers
        )

    def settle_royalty_period(self, period_id, headers):
        return self._request(
            "POST", f"/catalog/royalty-periods/{period_id}/settle", {}, headers
        )

    def get_royalty_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/catalog/royalty-statements/{statement_id}", headers=headers
        )

    def list_royalty_statements(self, headers, params=None):
        return self._request(
            "GET", "/catalog/royalty-statements", headers=headers, params=params
        )

    # ---- profile modules ------------------------------------------------
    def create_profile_module(self, payload, headers):
        return self._request("POST", "/catalog/profile-modules", payload, headers)

    def get_profile_module(self, module_id, headers):
        return self._request(
            "GET", f"/catalog/profile-modules/{module_id}", headers=headers
        )

    def list_profile_modules(self, headers, params=None):
        return self._request(
            "GET", "/catalog/profile-modules", headers=headers, params=params
        )

    def disable_profile_module(self, module_id, headers):
        return self._request(
            "POST", f"/catalog/profile-modules/{module_id}/disable", {}, headers
        )

    # ---- presaves -------------------------------------------------------
    def create_presave(self, payload, headers):
        return self._request("POST", "/catalog/presaves", payload, headers)

    def get_presave(self, presave_id, headers):
        return self._request("GET", f"/catalog/presaves/{presave_id}", headers=headers)

    def list_presaves(self, headers, params=None):
        return self._request("GET", "/catalog/presaves", headers=headers, params=params)

    def cancel_presave(self, presave_id, headers):
        return self._request(
            "POST", f"/catalog/presaves/{presave_id}/cancel", {}, headers
        )


api_client = ApiClient()
