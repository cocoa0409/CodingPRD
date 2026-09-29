"""Typed client with one method per endpoint published by the PRD."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ZooTransferApiClient(GenericApiClient):
    """One method per PRD endpoint. Returns the raw response every time."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --------------------------------------------------------- institutions
    def create_institution(self, payload: Dict[str, Any],
                           headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/institutions", payload, headers)

    def patch_institution(self, institution_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "PATCH", f"/institutions/{institution_id}", payload, headers
        )

    def get_institution(self, institution_id: str,
                        headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/institutions/{institution_id}", None, headers)

    def list_institutions(self, headers: Dict[str, str],
                          params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/institutions", None, headers, params)

    # ------------------------------------------------------ species programs
    def create_species_program(self, payload: Dict[str, Any],
                               headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/species-programs", payload, headers)

    def publish_plan(self, species_program_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request(
            "POST",
            f"/species-programs/{species_program_id}/publish-plan",
            payload if payload is not None else {},
            headers,
        )

    def get_species_program(self, species_program_id: str,
                            headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/species-programs/{species_program_id}", None, headers
        )

    def list_species_programs(self, headers: Dict[str, str],
                              params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/species-programs", None, headers, params)

    # ------------------------------------------------------- veterinarians
    def create_veterinarian(self, payload: Dict[str, Any],
                            headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/veterinarians", payload, headers)

    def get_veterinarian(self, veterinarian_id: str,
                         headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/veterinarians/{veterinarian_id}", None, headers)

    def list_veterinarians(self, headers: Dict[str, str],
                           params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/veterinarians", None, headers, params)

    # -------------------------------------------------------------- animals
    def create_animal(self, payload: Dict[str, Any],
                      headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/animals", payload, headers)

    def create_crate_training_session(self, animal_id: str, payload: Dict[str, Any],
                                      headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/animals/{animal_id}/crate-training-sessions", payload, headers
        )

    def dispose_animal(self, animal_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/animals/{animal_id}/disposition", payload, headers
        )

    def get_animal(self, animal_id: str,
                   headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/animals/{animal_id}", None, headers)

    def list_animals(self, headers: Dict[str, str],
                     params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/animals", None, headers, params)

    # ------------------------------------------- population recommendations
    def create_recommendation(self, payload: Dict[str, Any],
                              headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/population-recommendations", payload, headers)

    def endorse_recommendation(self, recommendation_id: str, headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None
                               ) -> requests.Response:
        return self._request(
            "POST",
            f"/population-recommendations/{recommendation_id}/endorse",
            payload if payload is not None else {},
            headers,
        )

    def get_recommendation(self, recommendation_id: str,
                           headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/population-recommendations/{recommendation_id}", None, headers
        )

    def list_recommendations(self, headers: Dict[str, str],
                             params: Optional[Dict] = None) -> requests.Response:
        return self._request(
            "GET", "/population-recommendations", None, headers, params
        )

    # --------------------------------------------------- transfer agreements
    def create_agreement(self, payload: Dict[str, Any],
                         headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/transfer-agreements", payload, headers)

    def offer_agreement(self, agreement_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None
                        ) -> requests.Response:
        return self._request(
            "POST",
            f"/transfer-agreements/{agreement_id}/offer",
            payload if payload is not None else {},
            headers,
        )

    def counter_agreement(self, agreement_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None
                          ) -> requests.Response:
        return self._request(
            "POST",
            f"/transfer-agreements/{agreement_id}/counter",
            payload if payload is not None else {},
            headers,
        )

    def accept_agreement(self, agreement_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None
                         ) -> requests.Response:
        return self._request(
            "POST",
            f"/transfer-agreements/{agreement_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def execute_agreement(self, agreement_id: str, headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None
                          ) -> requests.Response:
        return self._request(
            "POST",
            f"/transfer-agreements/{agreement_id}/execute",
            payload if payload is not None else {},
            headers,
        )

    def terminate_agreement(self, agreement_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None
                            ) -> requests.Response:
        return self._request(
            "POST",
            f"/transfer-agreements/{agreement_id}/terminate",
            payload if payload is not None else {},
            headers,
        )

    def get_agreement(self, agreement_id: str,
                      headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/transfer-agreements/{agreement_id}", None, headers
        )

    def list_agreements(self, headers: Dict[str, str],
                        params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/transfer-agreements", None, headers, params)

    # -------------------------------------------------- compliance documents
    def create_document(self, payload: Dict[str, Any],
                        headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/compliance-documents", payload, headers)

    def decide_document(self, document_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/compliance-documents/{document_id}/decision", payload, headers
        )

    def get_document(self, document_id: str,
                     headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/compliance-documents/{document_id}", None, headers
        )

    def list_documents(self, headers: Dict[str, str],
                       params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/compliance-documents", None, headers, params)

    # -------------------------------------------------- pre-shipment tests
    def create_pre_shipment_test(self, payload: Dict[str, Any],
                                 headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/pre-shipment-tests", payload, headers)

    def get_pre_shipment_test(self, test_id: str,
                              headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/pre-shipment-tests/{test_id}", None, headers)

    def list_pre_shipment_tests(self, headers: Dict[str, str],
                                params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/pre-shipment-tests", None, headers, params)

    # ----------------------------------------------- quarantine occupancies
    def create_quarantine_occupancy(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/quarantine-occupancies", payload, headers)

    def clear_quarantine(self, occupancy_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None
                         ) -> requests.Response:
        return self._request(
            "POST",
            f"/quarantine-occupancies/{occupancy_id}/clear",
            payload if payload is not None else {},
            headers,
        )

    def fail_quarantine(self, occupancy_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None
                        ) -> requests.Response:
        return self._request(
            "POST",
            f"/quarantine-occupancies/{occupancy_id}/fail",
            payload if payload is not None else {},
            headers,
        )

    def get_quarantine_occupancy(self, occupancy_id: str,
                                 headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/quarantine-occupancies/{occupancy_id}", None, headers
        )

    def list_quarantine_occupancies(self, headers: Dict[str, str],
                                    params: Optional[Dict] = None
                                    ) -> requests.Response:
        return self._request("GET", "/quarantine-occupancies", None, headers, params)

    # -------------------------------------------------- shipment bookings
    def create_booking(self, payload: Dict[str, Any],
                       headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/shipment-bookings", payload, headers)

    def confirm_booking(self, booking_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None
                        ) -> requests.Response:
        return self._request(
            "POST",
            f"/shipment-bookings/{booking_id}/confirm",
            payload if payload is not None else {},
            headers,
        )

    def depart_booking(self, booking_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None
                       ) -> requests.Response:
        return self._request(
            "POST",
            f"/shipment-bookings/{booking_id}/depart",
            payload if payload is not None else {},
            headers,
        )

    def deliver_booking(self, booking_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/shipment-bookings/{booking_id}/deliver", payload, headers
        )

    def get_booking(self, booking_id: str,
                    headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/shipment-bookings/{booking_id}", None, headers)

    def list_bookings(self, headers: Dict[str, str],
                      params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/shipment-bookings", None, headers, params)

    # ---------------------------------------------- introduction protocols
    def create_protocol(self, payload: Dict[str, Any],
                        headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/introduction-protocols", payload, headers)

    def create_observation(self, protocol_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/introduction-protocols/{protocol_id}/observations",
            payload, headers,
        )

    def get_protocol(self, protocol_id: str,
                     headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/introduction-protocols/{protocol_id}", None, headers
        )

    def list_protocols(self, headers: Dict[str, str],
                       params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/introduction-protocols", None, headers, params)

    # ---------------------------------------------- studbook submissions
    def create_studbook_submission(self, payload: Dict[str, Any],
                                   headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/studbook-submissions", payload, headers)

    def review_studbook_submission(self, submission_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/studbook-submissions/{submission_id}/review", payload, headers
        )

    def get_studbook_submission(self, submission_id: str,
                                headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/studbook-submissions/{submission_id}", None, headers
        )

    def list_studbook_submissions(self, headers: Dict[str, str],
                                  params: Optional[Dict] = None
                                  ) -> requests.Response:
        return self._request("GET", "/studbook-submissions", None, headers, params)


ApiClient = ZooTransferApiClient
