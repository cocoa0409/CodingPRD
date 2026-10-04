"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed client over the /nkr API surface."""

    # --- Logical clock ---
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/nkr/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- TransplantCenter ---
    def create_center(self, payload, headers):
        return self._request("POST", "/nkr/centers", payload, headers)

    def list_centers(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/centers", headers=headers, params=params)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/nkr/centers/{center_id}", headers=headers)

    def probate_center(self, center_id, headers):
        return self._request("POST", f"/nkr/centers/{center_id}/probate", {}, headers)

    def suspend_center(self, center_id, payload, headers):
        return self._request("POST", f"/nkr/centers/{center_id}/suspend", payload, headers)

    def reinstate_center(self, center_id, headers):
        return self._request("POST", f"/nkr/centers/{center_id}/reinstate", {}, headers)

    # --- Donor ---
    def create_donor(self, payload, headers):
        return self._request("POST", "/nkr/donors", payload, headers)

    def list_donors(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/donors", headers=headers, params=params)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/nkr/donors/{donor_id}", headers=headers)

    def donor_medical_hold(self, donor_id, headers):
        return self._request("POST", f"/nkr/donors/{donor_id}/medical-hold", {}, headers)

    def donor_medical_release(self, donor_id, headers):
        return self._request("POST", f"/nkr/donors/{donor_id}/medical-release", {}, headers)

    def donor_withdraw(self, donor_id, headers):
        return self._request("POST", f"/nkr/donors/{donor_id}/withdraw", {}, headers)

    def donor_deceased(self, donor_id, headers):
        return self._request("POST", f"/nkr/donors/{donor_id}/deceased", {}, headers)

    def complete_nephrectomy(self, donor_id, headers):
        return self._request(
            "POST", f"/nkr/donors/{donor_id}/complete-nephrectomy", {}, headers
        )

    def donor_fail_preop(self, donor_id, headers):
        return self._request("POST", f"/nkr/donors/{donor_id}/fail-preop", {}, headers)

    def create_claim_for_donor(self, donor_id, payload, headers):
        return self._request("POST", f"/nkr/donors/{donor_id}/claims", payload, headers)

    # --- Recipient ---
    def create_recipient(self, payload, headers):
        return self._request("POST", "/nkr/recipients", payload, headers)

    def list_recipients(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/recipients", headers=headers, params=params)

    def get_recipient(self, recipient_id, headers):
        return self._request("GET", f"/nkr/recipients/{recipient_id}", headers=headers)

    def recipient_medical_hold(self, recipient_id, headers):
        return self._request(
            "POST", f"/nkr/recipients/{recipient_id}/medical-hold", {}, headers
        )

    def recipient_medical_release(self, recipient_id, headers):
        return self._request(
            "POST", f"/nkr/recipients/{recipient_id}/medical-release", {}, headers
        )

    def recipient_withdraw(self, recipient_id, headers):
        return self._request("POST", f"/nkr/recipients/{recipient_id}/withdraw", {}, headers)

    def recipient_deceased(self, recipient_id, headers):
        return self._request("POST", f"/nkr/recipients/{recipient_id}/deceased", {}, headers)

    def complete_transplant(self, recipient_id, headers):
        return self._request(
            "POST", f"/nkr/recipients/{recipient_id}/complete-transplant", {}, headers
        )

    # --- DonorRecipientPair ---
    def create_pair(self, payload, headers):
        return self._request("POST", "/nkr/pairs", payload, headers)

    def list_pairs(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/pairs", headers=headers, params=params)

    def get_pair(self, pair_id, headers):
        return self._request("GET", f"/nkr/pairs/{pair_id}", headers=headers)

    def verify_pair(self, pair_id, headers):
        return self._request("POST", f"/nkr/pairs/{pair_id}/verify", {}, headers)

    def enter_pool(self, pair_id, payload, headers):
        return self._request("POST", f"/nkr/pairs/{pair_id}/enter-pool", payload, headers)

    def dissolve_pair(self, pair_id, payload, headers):
        return self._request("POST", f"/nkr/pairs/{pair_id}/dissolve", payload, headers)

    # --- ChainRun ---
    def create_chain_run(self, payload, headers):
        return self._request("POST", "/nkr/chain-runs", payload, headers)

    def list_chain_runs(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/chain-runs", headers=headers, params=params)

    def get_chain_run(self, run_id, headers):
        return self._request("GET", f"/nkr/chain-runs/{run_id}", headers=headers)

    def execute_chain_run(self, run_id, payload, headers):
        return self._request("POST", f"/nkr/chain-runs/{run_id}/execute", payload, headers)

    def publish_chain_run(self, run_id, headers):
        return self._request("POST", f"/nkr/chain-runs/{run_id}/publish", {}, headers)

    def supersede_chain_run(self, run_id, headers):
        return self._request("POST", f"/nkr/chain-runs/{run_id}/supersede", {}, headers)

    # --- Chain ---
    def list_chains(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/chains", headers=headers, params=params)

    def get_chain(self, chain_id, headers):
        return self._request("GET", f"/nkr/chains/{chain_id}", headers=headers)

    def lock_chain(self, chain_id, payload, headers):
        return self._request("POST", f"/nkr/chains/{chain_id}/lock", payload, headers)

    def schedule_chain(self, chain_id, payload, headers):
        return self._request("POST", f"/nkr/chains/{chain_id}/schedule", payload, headers)

    def start_chain_execution(self, chain_id, headers):
        return self._request("POST", f"/nkr/chains/{chain_id}/start-execution", {}, headers)

    # --- MatchOffer ---
    def list_match_offers(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/match-offers", headers=headers, params=params)

    def get_match_offer(self, offer_id, headers):
        return self._request("GET", f"/nkr/match-offers/{offer_id}", headers=headers)

    def submit_crossmatch_review(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/nkr/match-offers/{offer_id}/crossmatch-review", payload, headers
        )

    def center_accept_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/nkr/match-offers/{offer_id}/center-accept", {}, headers
        )

    def center_decline_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/nkr/match-offers/{offer_id}/center-decline", {}, headers
        )

    # --- CrossmatchReview ---
    def list_crossmatch_reviews(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/crossmatch-reviews", headers=headers, params=params)

    def get_crossmatch_review(self, review_id, headers):
        return self._request("GET", f"/nkr/crossmatch-reviews/{review_id}", headers=headers)

    # --- SurgeryScheduleSlot ---
    def create_slot(self, payload, headers):
        return self._request("POST", "/nkr/slots", payload, headers)

    def list_slots(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/nkr/slots/{slot_id}", headers=headers)

    def release_slot(self, slot_id, headers):
        return self._request("POST", f"/nkr/slots/{slot_id}/release", {}, headers)

    # --- OrganShipment ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/nkr/shipments", payload, headers)

    def list_shipments(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/nkr/shipments/{shipment_id}", headers=headers)

    def depart_shipment(self, shipment_id, headers):
        return self._request("POST", f"/nkr/shipments/{shipment_id}/depart", {}, headers)

    def delay_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/nkr/shipments/{shipment_id}/delay", payload, headers)

    def reroute_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/nkr/shipments/{shipment_id}/reroute", payload, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/nkr/shipments/{shipment_id}/deliver", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/nkr/shipments/{shipment_id}/cancel", {}, headers)

    # --- TravelItinerary ---
    def create_itinerary(self, payload, headers):
        return self._request("POST", "/nkr/itineraries", payload, headers)

    def list_itineraries(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/itineraries", headers=headers, params=params)

    def get_itinerary(self, itinerary_id, headers):
        return self._request("GET", f"/nkr/itineraries/{itinerary_id}", headers=headers)

    def confirm_itinerary(self, itinerary_id, headers):
        return self._request("POST", f"/nkr/itineraries/{itinerary_id}/confirm", {}, headers)

    def cancel_itinerary(self, itinerary_id, payload, headers):
        return self._request(
            "POST", f"/nkr/itineraries/{itinerary_id}/cancel", payload, headers
        )

    def reimburse_itinerary(self, itinerary_id, headers):
        return self._request(
            "POST", f"/nkr/itineraries/{itinerary_id}/reimburse", {}, headers
        )

    # --- DonorProtectionPolicy ---
    def list_policies(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/nkr/policies/{policy_id}", headers=headers)

    # --- DonorProtectionClaim ---
    def list_claims(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/nkr/claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/nkr/claims/{claim_id}/start-review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/nkr/claims/{claim_id}/approve", {}, headers)

    def partial_approve_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/nkr/claims/{claim_id}/partial-approve", payload, headers
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/nkr/claims/{claim_id}/deny", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/nkr/claims/{claim_id}/pay", {}, headers)

    # --- TransplantOutcome ---
    def create_outcome(self, payload, headers):
        return self._request("POST", "/nkr/outcomes", payload, headers)

    def list_outcomes(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/outcomes", headers=headers, params=params)

    def get_outcome(self, outcome_id, headers):
        return self._request("GET", f"/nkr/outcomes/{outcome_id}", headers=headers)

    def attribute_outcome(self, outcome_id, payload, headers):
        return self._request(
            "POST", f"/nkr/outcomes/{outcome_id}/attribute", payload, headers
        )

    def appeal_outcome(self, outcome_id, headers):
        return self._request("POST", f"/nkr/outcomes/{outcome_id}/appeal", {}, headers)

    def resolve_outcome_appeal(self, outcome_id, payload, headers):
        return self._request(
            "POST", f"/nkr/outcomes/{outcome_id}/resolve-appeal", payload, headers
        )

    def finalize_outcome(self, outcome_id, headers):
        return self._request("POST", f"/nkr/outcomes/{outcome_id}/finalize", {}, headers)

    # --- ChainBreakEvent ---
    def list_chain_breaks(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/nkr/chain-breaks", headers=headers, params=params)

    def get_chain_break(self, event_id, headers):
        return self._request("GET", f"/nkr/chain-breaks/{event_id}", headers=headers)

    def reconstruct_chain_break(self, event_id, headers):
        return self._request(
            "POST", f"/nkr/chain-breaks/{event_id}/reconstruct", {}, headers
        )


api_client = ApiClient()
