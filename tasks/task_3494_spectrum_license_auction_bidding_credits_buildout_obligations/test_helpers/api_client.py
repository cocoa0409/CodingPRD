"""API client: one method per endpoint defined in the PRD.

All business endpoints live under the /spectrum-auctions prefix. The single
test-driving clock endpoint lives OUTSIDE the prefix (bare origin) — see
PRD: "POST /_clock/set_current_utc, restricted to AuctionAdmin".

Success codes (PRD endpoint table): resource-creating POSTs return 201;
reads, modifications, and state-transition drivers — including the clock —
return 200. Methods return raw requests.Response; callers validate with
validate_success(resp, expected_status) / validate_error(resp, error_id).
"""
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (UNPREFIXED — outside /spectrum-auctions). 200.
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Band plans
    # ------------------------------------------------------------------
    def create_band_plan(self, payload, headers):
        """201"""
        return self._request("POST", f"{API_PREFIX}/band-plans", payload, headers)

    def get_band_plan(self, plan_id, headers):
        return self._request("GET", f"{API_PREFIX}/band-plans/{plan_id}", headers=headers)

    def publish_band_plan(self, plan_id, headers):
        return self._request("POST", f"{API_PREFIX}/band-plans/{plan_id}/publish", {}, headers)

    # ------------------------------------------------------------------
    # License areas / blocks
    # ------------------------------------------------------------------
    def create_license_area(self, payload, headers):
        """201"""
        return self._request("POST", f"{API_PREFIX}/license-areas", payload, headers)

    def list_license_areas(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/band-plans/{plan_id}/license-areas", headers=headers, params=params
        )

    def create_license_block(self, payload, headers):
        """201"""
        return self._request("POST", f"{API_PREFIX}/license-blocks", payload, headers)

    def list_license_blocks(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/band-plans/{plan_id}/license-blocks", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Auctions
    # ------------------------------------------------------------------
    def create_auction(self, payload, headers):
        """201"""
        return self._request("POST", f"{API_PREFIX}/auctions", payload, headers)

    def get_auction(self, auction_id, headers):
        return self._request("GET", f"{API_PREFIX}/auctions/{auction_id}", headers=headers)

    def list_auctions_of_plan(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/band-plans/{plan_id}/auctions", headers=headers, params=params
        )

    def auction_phase(self, auction_id, action, headers):
        """Phase machine driver. action in OPEN_APPLICATIONS / BEGIN_QUIET_PERIOD /
        POSTPONE / START_CLOCK / PAUSE_CLOCK / RESUME_CLOCK / COMPLETE_ASSIGNMENT. 200"""
        return self._request(
            "POST", f"{API_PREFIX}/auctions/{auction_id}/phase", {"action": action}, headers
        )

    # ------------------------------------------------------------------
    # Applicants
    # ------------------------------------------------------------------
    def create_applicant(self, payload, headers):
        """Self-registration; caller role Bidder. 201"""
        return self._request("POST", f"{API_PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{API_PREFIX}/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, auction_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/auctions/{auction_id}/applicants", headers=headers, params=params
        )

    def patch_disclosure(self, applicant_id, payload, headers):
        """OCC-guarded; payload must carry expected_applicant_version. 200"""
        return self._request(
            "PATCH", f"{API_PREFIX}/applicants/{applicant_id}/disclosure", payload, headers
        )

    def add_upfront_payment(self, applicant_id, amount_cents, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/applicants/{applicant_id}/upfront-payments",
            {"amount_cents": amount_cents},
            headers,
        )

    def review_applicant(self, applicant_id, action, headers):
        """action in START_REVIEW / QUALIFY / REJECT / REQUEST_CORRECTION / DISQUALIFY. 200"""
        return self._request(
            "POST", f"{API_PREFIX}/applicants/{applicant_id}/review", {"action": action}, headers
        )

    def resubmit_applicant(self, applicant_id, expected_applicant_version, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/applicants/{applicant_id}/resubmit",
            {"expected_applicant_version": expected_applicant_version},
            headers,
        )

    def withdraw_applicant(self, applicant_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/applicants/{applicant_id}/withdraw", {}, headers
        )

    # ------------------------------------------------------------------
    # Clock rounds and bids
    # ------------------------------------------------------------------
    def open_round(self, auction_id, headers):
        """Open the next clock round. 201"""
        return self._request("POST", f"{API_PREFIX}/auctions/{auction_id}/rounds", {}, headers)

    def list_rounds(self, auction_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/auctions/{auction_id}/rounds", headers=headers, params=params
        )

    def get_round(self, round_id, headers):
        return self._request("GET", f"{API_PREFIX}/rounds/{round_id}", headers=headers)

    def close_round(self, round_id, headers):
        return self._request("POST", f"{API_PREFIX}/rounds/{round_id}/close", {}, headers)

    def place_bid(self, round_id, payload, headers):
        """payload: area_code, category, quantity. 201"""
        return self._request("POST", f"{API_PREFIX}/rounds/{round_id}/bids", payload, headers)

    def list_round_bids(self, round_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/rounds/{round_id}/bids", headers=headers, params=params
        )

    def list_applicant_bids(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/applicants/{applicant_id}/bids", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Assignment bids
    # ------------------------------------------------------------------
    def create_assignment_bid(self, auction_id, payload, headers):
        """payload: area_code, category, amount_cents. 201"""
        return self._request(
            "POST", f"{API_PREFIX}/auctions/{auction_id}/assignment-bids", payload, headers
        )

    def list_assignment_bids(self, auction_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/auctions/{auction_id}/assignment-bids", headers=headers, params=params
        )

    def list_applicant_assignment_bids(self, applicant_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/applicants/{applicant_id}/assignment-bids",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Licenses and settlement
    # ------------------------------------------------------------------
    def list_licenses(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"{API_PREFIX}/licenses/{license_id}", headers=headers)

    def add_settlement_payment(self, license_id, amount_cents, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/licenses/{license_id}/settlement-payments",
            {"amount_cents": amount_cents},
            headers,
        )

    # ------------------------------------------------------------------
    # Buildout milestones
    # ------------------------------------------------------------------
    def list_buildout_milestones(self, license_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/licenses/{license_id}/buildout-milestones",
            headers=headers,
            params=params,
        )

    def file_milestone_notice(self, milestone_id, payload, headers):
        """OCC-guarded; payload must carry covered_population and
        expected_milestone_version. 200"""
        return self._request(
            "POST",
            f"{API_PREFIX}/buildout-milestones/{milestone_id}/file-notice",
            payload,
            headers,
        )

    def review_milestone(self, milestone_id, decision, headers):
        """decision in ACCEPT / REJECT. 200"""
        return self._request(
            "POST",
            f"{API_PREFIX}/buildout-milestones/{milestone_id}/review",
            {"decision": decision},
            headers,
        )

    # ------------------------------------------------------------------
    # Transfer applications
    # ------------------------------------------------------------------
    def create_transfer_application(self, license_id, payload, headers):
        """payload: transfer_type, transferee_applicant_id, lease_start?, lease_end?. 201"""
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/transfer-applications", payload, headers
        )

    def list_license_transfers(self, license_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/licenses/{license_id}/transfer-applications",
            headers=headers,
            params=params,
        )

    def list_applicant_transfers(self, applicant_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/applicants/{applicant_id}/transfer-applications",
            headers=headers,
            params=params,
        )

    def get_transfer_application(self, transfer_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/transfer-applications/{transfer_id}", headers=headers
        )

    def review_transfer_application(self, transfer_id, payload, headers):
        """payload: action (+ confirm_unjust_enrichment_repayment? for APPROVE).
        BEGIN_REVIEW/REQUEST_INFO/APPROVE/DENY are TransferReviewer-only;
        PROVIDE_INFO is the transferor Bidder only. 200"""
        return self._request(
            "POST", f"{API_PREFIX}/transfer-applications/{transfer_id}/review", payload, headers
        )

    def withdraw_transfer_application(self, transfer_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/transfer-applications/{transfer_id}/withdraw", {}, headers
        )

    # ------------------------------------------------------------------
    # Incumbents
    # ------------------------------------------------------------------
    def create_incumbent(self, payload, headers):
        """201"""
        return self._request("POST", f"{API_PREFIX}/incumbents", payload, headers)

    def list_incumbents(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/incumbents", headers=headers, params=params)

    def get_incumbent(self, incumbent_id, headers):
        return self._request("GET", f"{API_PREFIX}/incumbents/{incumbent_id}", headers=headers)

    def transition_incumbent(self, incumbent_id, payload, headers):
        """payload: action (+ transition_window_start/end for BEGIN_RELOCATION).
        SUBMIT_PLAN/DISPUTE/RESUBMIT_PLAN/CONFIRM_CLEARED are IncumbentOperator-only;
        BEGIN_RELOCATION is AuctionAdmin-only. 200"""
        return self._request(
            "POST", f"{API_PREFIX}/incumbents/{incumbent_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Renewal applications
    # ------------------------------------------------------------------
    def create_renewal_application(self, license_id, headers):
        """File for renewal; moves license ACTIVE -> RENEWAL_REVIEW. 201"""
        return self._request(
            "POST", f"{API_PREFIX}/licenses/{license_id}/renewal-applications", {}, headers
        )

    def list_renewal_applications(self, license_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/licenses/{license_id}/renewal-applications",
            headers=headers,
            params=params,
        )

    def decide_renewal(self, renewal_id, decision, headers):
        """decision in GRANT / DENY; TransferReviewer only. 200"""
        return self._request(
            "POST",
            f"{API_PREFIX}/renewal-applications/{renewal_id}/decide",
            {"decision": decision},
            headers,
        )


api_client = ApiClient()
