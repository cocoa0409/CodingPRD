"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/licensing/_clock/set_current_utc", payload, headers)

    # --- LicenseAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/licensing/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/licensing/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/licensing/agreements", headers=headers, params=params)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/activate", {}, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/suspend", {}, headers)

    def reinstate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/reinstate", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/licensing/agreements/{agreement_id}/terminate", {}, headers)

    def list_agreement_royalty_statements(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/royalty-statements", headers=headers, params=params)

    def list_agreement_audit_cases(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/audit-cases", headers=headers, params=params)

    def list_agreement_likeness_grants(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/likeness-grants", headers=headers, params=params)

    def list_agreement_seasons(self, agreement_id, headers, params=None):
        return self._request("GET", f"/licensing/agreements/{agreement_id}/seasons", headers=headers, params=params)

    # --- Athlete ---
    def create_athlete(self, payload, headers):
        return self._request("POST", "/licensing/athletes", payload, headers)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"/licensing/athletes/{athlete_id}", headers=headers)

    def list_athletes(self, headers, params=None):
        return self._request("GET", "/licensing/athletes", headers=headers, params=params)

    def list_athlete_likeness_grants(self, athlete_id, headers, params=None):
        return self._request("GET", f"/licensing/athletes/{athlete_id}/likeness-grants", headers=headers, params=params)

    def list_athlete_roster_entries(self, athlete_id, headers, params=None):
        return self._request("GET", f"/licensing/athletes/{athlete_id}/roster-entries", headers=headers, params=params)

    def list_athlete_content_drops(self, athlete_id, headers, params=None):
        return self._request("GET", f"/licensing/athletes/{athlete_id}/content-drops", headers=headers, params=params)

    # --- LikenessGrant ---
    def create_likeness_grant(self, payload, headers):
        return self._request("POST", "/licensing/likeness-grants", payload, headers)

    def get_likeness_grant(self, grant_id, headers):
        return self._request("GET", f"/licensing/likeness-grants/{grant_id}", headers=headers)

    def grant_likeness(self, grant_id, headers):
        return self._request("POST", f"/licensing/likeness-grants/{grant_id}/grant", {}, headers)

    def suspend_likeness_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/licensing/likeness-grants/{grant_id}/suspend", payload, headers)

    def reinstate_likeness_grant(self, grant_id, headers):
        return self._request("POST", f"/licensing/likeness-grants/{grant_id}/reinstate", {}, headers)

    def revoke_likeness_grant(self, grant_id, headers):
        return self._request("POST", f"/licensing/likeness-grants/{grant_id}/revoke", {}, headers)

    # --- LiveSeason ---
    def create_season(self, payload, headers):
        return self._request("POST", "/licensing/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/licensing/seasons/{season_id}", headers=headers)

    def launch_season(self, season_id, headers):
        return self._request("POST", f"/licensing/seasons/{season_id}/launch", {}, headers)

    def sunset_season(self, season_id, headers):
        return self._request("POST", f"/licensing/seasons/{season_id}/sunset", {}, headers)

    def archive_season(self, season_id, headers):
        return self._request("POST", f"/licensing/seasons/{season_id}/archive", {}, headers)

    def list_season_roster_batches(self, season_id, headers, params=None):
        return self._request("GET", f"/licensing/seasons/{season_id}/roster-batches", headers=headers, params=params)

    def list_season_content_drops(self, season_id, headers, params=None):
        return self._request("GET", f"/licensing/seasons/{season_id}/content-drops", headers=headers, params=params)

    def list_season_wallets(self, season_id, headers, params=None):
        return self._request("GET", f"/licensing/seasons/{season_id}/wallets", headers=headers, params=params)

    def list_season_tournaments(self, season_id, headers, params=None):
        return self._request("GET", f"/licensing/seasons/{season_id}/tournaments", headers=headers, params=params)

    def list_season_editions(self, season_id, headers, params=None):
        return self._request("GET", f"/licensing/seasons/{season_id}/editions", headers=headers, params=params)

    # --- RosterBatch / RosterEntry ---
    def create_roster_batch(self, payload, headers):
        return self._request("POST", "/licensing/roster-batches", payload, headers)

    def get_roster_batch(self, batch_id, headers):
        return self._request("GET", f"/licensing/roster-batches/{batch_id}", headers=headers)

    def list_roster_batches(self, headers, params=None):
        return self._request("GET", "/licensing/roster-batches", headers=headers, params=params)

    def add_roster_entry(self, batch_id, payload, headers):
        return self._request("POST", f"/licensing/roster-batches/{batch_id}/entries", payload, headers)

    def list_roster_entries(self, batch_id, headers, params=None):
        return self._request("GET", f"/licensing/roster-batches/{batch_id}/entries", headers=headers, params=params)

    def validate_roster_batch(self, batch_id, headers):
        return self._request("POST", f"/licensing/roster-batches/{batch_id}/validate", {}, headers)

    def reject_roster_batch(self, batch_id, headers):
        return self._request("POST", f"/licensing/roster-batches/{batch_id}/reject", {}, headers)

    def publish_roster_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/licensing/roster-batches/{batch_id}/publish", payload, headers)

    def rollback_roster_batch(self, batch_id, headers):
        return self._request("POST", f"/licensing/roster-batches/{batch_id}/rollback", {}, headers)

    # --- ContentDrop ---
    def create_content_drop(self, payload, headers):
        return self._request("POST", "/licensing/content-drops", payload, headers)

    def get_content_drop(self, drop_id, headers):
        return self._request("GET", f"/licensing/content-drops/{drop_id}", headers=headers)

    def release_content_drop(self, drop_id, headers):
        return self._request("POST", f"/licensing/content-drops/{drop_id}/release", {}, headers)

    def cancel_content_drop(self, drop_id, headers):
        return self._request("POST", f"/licensing/content-drops/{drop_id}/cancel", {}, headers)

    def purchase_content_drop(self, drop_id, payload, headers):
        return self._request("POST", f"/licensing/content-drops/{drop_id}/purchase", payload, headers)

    # --- PlayerWallet / WalletLedgerEntry ---
    def create_wallet(self, payload, headers):
        return self._request("POST", "/licensing/wallets", payload, headers)

    def get_wallet(self, wallet_id, headers):
        return self._request("GET", f"/licensing/wallets/{wallet_id}", headers=headers)

    def freeze_wallet(self, wallet_id, headers):
        return self._request("POST", f"/licensing/wallets/{wallet_id}/freeze", {}, headers)

    def unfreeze_wallet(self, wallet_id, headers):
        return self._request("POST", f"/licensing/wallets/{wallet_id}/unfreeze", {}, headers)

    def post_ledger_entry(self, wallet_id, payload, headers):
        return self._request("POST", f"/licensing/wallets/{wallet_id}/ledger-entries", payload, headers)

    def list_ledger_entries(self, wallet_id, headers, params=None):
        return self._request("GET", f"/licensing/wallets/{wallet_id}/ledger-entries", headers=headers, params=params)

    def list_wallet_tournament_entries(self, wallet_id, headers, params=None):
        return self._request("GET", f"/licensing/wallets/{wallet_id}/tournament-entries", headers=headers, params=params)

    # --- TournamentProgram / Entry / Prize ---
    def create_tournament(self, payload, headers):
        return self._request("POST", "/licensing/tournaments", payload, headers)

    def get_tournament(self, program_id, headers):
        return self._request("GET", f"/licensing/tournaments/{program_id}", headers=headers)

    def open_registration(self, program_id, headers):
        return self._request("POST", f"/licensing/tournaments/{program_id}/open-registration", {}, headers)

    def register_tournament_entry(self, program_id, payload, headers):
        return self._request("POST", f"/licensing/tournaments/{program_id}/entries", payload, headers)

    def list_tournament_entries(self, program_id, headers, params=None):
        return self._request("GET", f"/licensing/tournaments/{program_id}/entries", headers=headers, params=params)

    def add_prize_row(self, program_id, payload, headers):
        return self._request("POST", f"/licensing/tournaments/{program_id}/prizes", payload, headers)

    def list_prize_rows(self, program_id, headers, params=None):
        return self._request("GET", f"/licensing/tournaments/{program_id}/prizes", headers=headers, params=params)

    def close_registration(self, program_id, headers):
        return self._request("POST", f"/licensing/tournaments/{program_id}/close-registration", {}, headers)

    def record_results(self, program_id, payload, headers):
        return self._request("POST", f"/licensing/tournaments/{program_id}/record-results", payload, headers)

    def finalize_payout(self, program_id, payload, headers):
        return self._request("POST", f"/licensing/tournaments/{program_id}/finalize-payout", payload, headers)

    def cancel_tournament(self, program_id, headers):
        return self._request("POST", f"/licensing/tournaments/{program_id}/cancel", {}, headers)

    # --- AudioAsset / AudioLicense ---
    def create_audio_asset(self, payload, headers):
        return self._request("POST", "/licensing/audio-assets", payload, headers)

    def get_audio_asset(self, asset_id, headers):
        return self._request("GET", f"/licensing/audio-assets/{asset_id}", headers=headers)

    def retire_audio_asset(self, asset_id, headers):
        return self._request("POST", f"/licensing/audio-assets/{asset_id}/retire", {}, headers)

    def list_asset_licenses(self, asset_id, headers, params=None):
        return self._request("GET", f"/licensing/audio-assets/{asset_id}/licenses", headers=headers, params=params)

    def create_audio_license(self, payload, headers):
        return self._request("POST", "/licensing/audio-licenses", payload, headers)

    def get_audio_license(self, license_id, headers):
        return self._request("GET", f"/licensing/audio-licenses/{license_id}", headers=headers)

    def terminate_audio_license(self, license_id, headers):
        return self._request("POST", f"/licensing/audio-licenses/{license_id}/terminate", {}, headers)

    # --- RegionalEdition ---
    def create_edition(self, payload, headers):
        return self._request("POST", "/licensing/editions", payload, headers)

    def get_edition(self, edition_id, headers):
        return self._request("GET", f"/licensing/editions/{edition_id}", headers=headers)

    def submit_edition_review(self, edition_id, headers):
        return self._request("POST", f"/licensing/editions/{edition_id}/submit-review", {}, headers)

    def approve_edition(self, edition_id, headers):
        return self._request("POST", f"/licensing/editions/{edition_id}/approve", {}, headers)

    def return_edition_to_draft(self, edition_id, headers):
        return self._request("POST", f"/licensing/editions/{edition_id}/return-to-draft", {}, headers)

    def release_edition(self, edition_id, headers):
        return self._request("POST", f"/licensing/editions/{edition_id}/release", {}, headers)

    def withdraw_edition(self, edition_id, headers):
        return self._request("POST", f"/licensing/editions/{edition_id}/withdraw", {}, headers)

    # --- RoyaltyStatement ---
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/licensing/royalty-statements", payload, headers)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/licensing/royalty-statements/{statement_id}", headers=headers)

    def compute_provisional(self, statement_id, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/compute-provisional", {}, headers)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/finalize", {}, headers)

    def pay_statement(self, statement_id, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/pay", {}, headers)

    def list_statement_audit_cases(self, statement_id, headers, params=None):
        return self._request("GET", f"/licensing/royalty-statements/{statement_id}/audit-cases", headers=headers, params=params)

    # --- AuditCase ---
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/licensing/audit-cases", payload, headers)

    def get_audit_case(self, case_id, headers):
        return self._request("GET", f"/licensing/audit-cases/{case_id}", headers=headers)

    def file_audit_findings(self, case_id, payload, headers):
        return self._request("POST", f"/licensing/audit-cases/{case_id}/file-findings", payload, headers)

    def settle_audit_case(self, case_id, headers):
        return self._request("POST", f"/licensing/audit-cases/{case_id}/settle", {}, headers)

    def close_audit_case(self, case_id, headers):
        return self._request("POST", f"/licensing/audit-cases/{case_id}/close", {}, headers)


api_client = ApiClient()
