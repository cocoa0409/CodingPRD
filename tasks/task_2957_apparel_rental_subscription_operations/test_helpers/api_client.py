"""Typed HTTP surface for the apparel rental subscription API.

One method per published endpoint, so a test never has to spell a URL, and the
authorized-role headers travel with the call rather than being reconstructed at
each call site.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Params = Dict[str, Any]
Body = Dict[str, Any]


class ApparelRentalClient:
    """Thin, explicit wrapper over the shared generic HTTP client."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._client = GenericApiClient(base_url)

    # -- plumbing ----------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._client.base_url

    def _get(self, path: str, headers: Headers, params: Optional[Params] = None):
        return self._client.get(path, headers=headers, params=params)

    def _post(self, path: str, headers: Headers, body: Optional[Body] = None):
        return self._client.post(path, json=body if body is not None else {}, headers=headers)

    def _patch(self, path: str, headers: Headers, body: Optional[Body] = None):
        return self._client._request(
            "PATCH", path, payload=body if body is not None else {}, headers=headers
        )

    # -- logical clock -----------------------------------------------------

    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._post("/_clock/set_current_utc", headers, {"current_utc": current_utc})

    # -- membership plans --------------------------------------------------

    def create_membership_plan(self, body: Body, headers: Headers) -> requests.Response:
        return self._post("/membership-plans", headers, body)

    def get_membership_plan(self, plan_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/membership-plans/{plan_id}", headers)

    def list_membership_plans(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/membership-plans", headers, params)

    # -- technicians -------------------------------------------------------

    def create_technician(self, body: Body, headers: Headers) -> requests.Response:
        return self._post("/technicians", headers, body)

    def update_technician(
        self, technician_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._patch(f"/technicians/{technician_id}", headers, body)

    def get_technician(self, technician_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/technicians/{technician_id}", headers)

    def list_technicians(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/technicians", headers, params)

    # -- styles ------------------------------------------------------------

    def create_style(self, body: Body, headers: Headers) -> requests.Response:
        return self._post("/styles", headers, body)

    def update_depth_plan(
        self, style_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._patch(f"/styles/{style_id}/depth-plan", headers, body)

    def get_style(self, style_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/styles/{style_id}", headers)

    def list_styles(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/styles", headers, params)

    def get_unit_economics(
        self, style_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get(f"/styles/{style_id}/unit-economics", headers, params)

    # -- rental units ------------------------------------------------------

    def create_rental_unit(
        self, style_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/styles/{style_id}/rental-units", headers, body)

    def get_rental_unit(self, unit_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/rental-units/{unit_id}", headers)

    def list_rental_units(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/rental-units", headers, params)

    def retire_rental_unit(
        self, unit_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/rental-units/{unit_id}/retirement", headers, body)

    # -- members -----------------------------------------------------------

    def create_member(self, body: Body, headers: Headers) -> requests.Response:
        return self._post("/members", headers, body)

    def get_member(self, member_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/members/{member_id}", headers)

    def list_members(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/members", headers, params)

    def update_style_preferences(
        self, member_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._patch(f"/members/{member_id}/style-preferences", headers, body)

    def pause_member(
        self, member_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/members/{member_id}/pause", headers, body)

    def resume_member(
        self, member_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/members/{member_id}/resume", headers, body)

    def settle_fees(
        self, member_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/members/{member_id}/fee-settlements", headers, body)

    def cancel_member(
        self, member_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/members/{member_id}/cancellation", headers, body)

    def get_damage_risk(
        self, member_id: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get(f"/members/{member_id}/damage-risk", headers, params)

    def get_personalization_summary(
        self, member_id: str, headers: Headers
    ) -> requests.Response:
        return self._get(f"/members/{member_id}/personalization-summary", headers)

    # -- reservations ------------------------------------------------------

    def create_reservation(self, body: Body, headers: Headers) -> requests.Response:
        return self._post("/reservations", headers, body)

    def get_reservation(self, reservation_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/reservations/{reservation_id}", headers)

    def list_reservations(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/reservations", headers, params)

    def release_reservation(
        self, reservation_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/reservations/{reservation_id}/release", headers, body)

    def swap_reservation(
        self, reservation_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/reservations/{reservation_id}/swap", headers, body)

    def initiate_return(
        self, reservation_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/reservations/{reservation_id}/return-initiation", headers, body)

    def file_fit_feedback(
        self, reservation_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/reservations/{reservation_id}/fit-feedback", headers, body)

    def get_fit_feedback(self, feedback_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/fit-feedback/{feedback_id}", headers)

    def list_fit_feedback(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/fit-feedback", headers, params)

    # -- shipment legs -----------------------------------------------------

    def create_shipment(self, body: Body, headers: Headers) -> requests.Response:
        return self._post("/shipments", headers, body)

    def get_shipment(self, shipment_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/shipments/{shipment_id}", headers)

    def list_shipments(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/shipments", headers, params)

    def dispatch_shipment(
        self, shipment_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/shipments/{shipment_id}/dispatch", headers, body)

    def deliver_shipment(
        self, shipment_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/shipments/{shipment_id}/delivery", headers, body)

    def record_shipment_exception(
        self, shipment_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/shipments/{shipment_id}/exception", headers, body)

    def receive_shipment(
        self, shipment_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/shipments/{shipment_id}/receipt", headers, body)

    # -- reverse logistics -------------------------------------------------

    def get_job(self, job_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/reverse-logistics-jobs/{job_id}", headers)

    def list_jobs(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/reverse-logistics-jobs", headers, params)

    def file_inspection(
        self, job_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/reverse-logistics-jobs/{job_id}/inspections", headers, body)

    def get_inspection(self, inspection_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/inspections/{inspection_id}", headers)

    def list_inspections(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/inspections", headers, params)

    def complete_cleaning(
        self, job_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/reverse-logistics-jobs/{job_id}/cleaning-completion", headers, body)

    def complete_repair(
        self, job_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/reverse-logistics-jobs/{job_id}/repair-completion", headers, body)

    def clear_quarantine(
        self, job_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/reverse-logistics-jobs/{job_id}/quarantine-clearance", headers, body)

    def photograph(
        self, job_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/reverse-logistics-jobs/{job_id}/photography", headers, body)

    def restock(
        self, job_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/reverse-logistics-jobs/{job_id}/restock", headers, body)

    # -- damage claims and ledger -----------------------------------------

    def get_damage_claim(self, claim_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/damage-claims/{claim_id}", headers)

    def list_damage_claims(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/damage-claims", headers, params)

    def assess_claim(
        self, claim_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/damage-claims/{claim_id}/assessment", headers, body)

    def waive_claim(
        self, claim_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/damage-claims/{claim_id}/waiver", headers, body)

    def charge_claim(
        self, claim_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/damage-claims/{claim_id}/charge", headers, body)

    def dispute_claim(
        self, claim_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/damage-claims/{claim_id}/disputes", headers, body)

    def resolve_dispute(
        self, claim_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/damage-claims/{claim_id}/dispute-resolution", headers, body)

    def get_fee_ledger_entry(self, entry_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/fee-ledger-entries/{entry_id}", headers)

    def list_fee_ledger_entries(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/fee-ledger-entries", headers, params)

    # -- resale listings ---------------------------------------------------

    def create_resale_listing(self, body: Body, headers: Headers) -> requests.Response:
        return self._post("/resale-listings", headers, body)

    def get_resale_listing(self, listing_id: str, headers: Headers) -> requests.Response:
        return self._get(f"/resale-listings/{listing_id}", headers)

    def list_resale_listings(
        self, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get("/resale-listings", headers, params)

    def expire_resale_listing(
        self, listing_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/resale-listings/{listing_id}/expiration", headers, body)

    def reprice_resale_listing(
        self, listing_id: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(f"/resale-listings/{listing_id}/reprice", headers, body)

    def sell_resale_listing(
        self, listing_id: str, body: Body, headers: Headers
    ) -> requests.Response:
        return self._post(f"/resale-listings/{listing_id}/sale", headers, body)

    # -- raw escape hatches ------------------------------------------------

    def raw_get(
        self, path: str, headers: Headers, params: Optional[Params] = None
    ) -> requests.Response:
        return self._get(path, headers, params)

    def raw_post(
        self, path: str, headers: Headers, body: Optional[Body] = None
    ) -> requests.Response:
        return self._post(path, headers, body)
