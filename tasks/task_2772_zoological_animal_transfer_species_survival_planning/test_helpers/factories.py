"""Request-payload builders.

Each builder returns a complete, PRD-legal payload with sensible defaults that
individual tests override by keyword. Monetary and ratio inputs are emitted as
JSON numbers, never as strings.
"""

from typing import Any, Dict, List, Optional


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override of None removes the key entirely."""
    for key, value in overrides.items():
        if value is None and key in payload:
            payload.pop(key)
        else:
            payload[key] = value
    return payload


# ----------------------------------------------------------- institutions
def institution_payload(name: str = "Cedar Ridge Zoo",
                        jurisdiction_code: str = "US-CA",
                        accreditation_status: str = "ACCREDITED",
                        accreditation_expires_on: str = "2028-12-31",
                        holding_capacity_slots: int = 40,
                        disposition_policy_on_file: bool = True,
                        **overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": name,
        "jurisdiction_code": jurisdiction_code,
        "accreditation_status": accreditation_status,
        "accreditation_expires_on": accreditation_expires_on,
        "holding_capacity_slots": holding_capacity_slots,
        "disposition_policy_on_file": disposition_policy_on_file,
    }
    return _merge(payload, overrides)


def sender_institution_payload(**overrides: Any) -> Dict[str, Any]:
    """Cedar Ridge Zoo, the sending institution in California."""
    payload = institution_payload(name="Cedar Ridge Zoo", jurisdiction_code="US-CA")
    return _merge(payload, overrides)


def receiver_institution_payload(**overrides: Any) -> Dict[str, Any]:
    """Harbor Bay Zoo, the receiving institution in Texas."""
    payload = institution_payload(name="Harbor Bay Zoo", jurisdiction_code="US-TX")
    return _merge(payload, overrides)


def outsider_institution_payload(**overrides: Any) -> Dict[str, Any]:
    """Northgate Wildlife Park, a third institution party to nothing."""
    payload = institution_payload(name="Northgate Wildlife Park",
                                  jurisdiction_code="US-OR")
    return _merge(payload, overrides)


# -------------------------------------------------------- species programs
def species_program_payload(taxon_name: str = "Panthera uncia",
                            program_type: str = "SSP_RED",
                            target_population_size: int = 300,
                            studbook_keeper_name: str = "K. Ahlgren",
                            **overrides: Any) -> Dict[str, Any]:
    payload = {
        "taxon_name": taxon_name,
        "program_type": program_type,
        "target_population_size": target_population_size,
        "studbook_keeper_name": studbook_keeper_name,
    }
    return _merge(payload, overrides)


# ---------------------------------------------------------- veterinarians
def veterinarian_payload(institution_id: str,
                         full_name: str = "Dr A Vega",
                         license_number: str = "CA-VET-1001",
                         license_jurisdiction: str = "US-CA",
                         license_status: str = "ACTIVE",
                         usda_accreditation_category: str = "CATEGORY_I",
                         **overrides: Any) -> Dict[str, Any]:
    payload = {
        "institution_id": institution_id,
        "full_name": full_name,
        "license_number": license_number,
        "license_jurisdiction": license_jurisdiction,
        "license_status": license_status,
        "usda_accreditation_category": usda_accreditation_category,
    }
    return _merge(payload, overrides)


# ----------------------------------------------------------------- animals
def animal_payload(species_program_id: str,
                   holding_institution_id: str,
                   owning_institution_id: Optional[str] = None,
                   local_id: str = "CR-101",
                   sex: str = "MALE",
                   birth_date: str = "2019-05-10",
                   founder_representation_pct: float = 12.45,
                   **overrides: Any) -> Dict[str, Any]:
    payload = {
        "species_program_id": species_program_id,
        "holding_institution_id": holding_institution_id,
        "owning_institution_id": owning_institution_id or holding_institution_id,
        "local_id": local_id,
        "sex": sex,
        "birth_date": birth_date,
        "founder_representation_pct": founder_representation_pct,
    }
    return _merge(payload, overrides)


def crate_training_session_payload(session_date: str = "2026-07-28",
                                   trainer_name: str = "T Rios",
                                   duration_minutes: int = 25,
                                   **overrides: Any) -> Dict[str, Any]:
    payload = {
        "session_date": session_date,
        "trainer_name": trainer_name,
        "duration_minutes": duration_minutes,
    }
    return _merge(payload, overrides)


def disposition_payload(disposition_method: str = "TRANSFER_TO_NON_AZA_HOLDER",
                        disposition_note: str = "Placed with an approved holder",
                        **overrides: Any) -> Dict[str, Any]:
    payload = {"disposition_method": disposition_method,
               "disposition_note": disposition_note}
    return _merge(payload, overrides)


# ------------------------------------------------ population recommendations
def recommendation_payload(species_program_id: str,
                           subject_animal_id: str,
                           expected_subject_animal_version: int,
                           recommendation_type: str = "BREED_WITH",
                           paired_animal_id: Optional[str] = None,
                           sending_institution_id: Optional[str] = None,
                           receiving_institution_id: Optional[str] = None,
                           analysis_mode: str = "PEDIGREE_ONLY",
                           priority_rank: int = 1,
                           expires_on: str = "2026-12-31",
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "species_program_id": species_program_id,
        "recommendation_type": recommendation_type,
        "subject_animal_id": subject_animal_id,
        "analysis_mode": analysis_mode,
        "priority_rank": priority_rank,
        "expires_on": expires_on,
        "expected_subject_animal_version": expected_subject_animal_version,
    }
    if paired_animal_id is not None:
        payload["paired_animal_id"] = paired_animal_id
    if sending_institution_id is not None:
        payload["sending_institution_id"] = sending_institution_id
    if receiving_institution_id is not None:
        payload["receiving_institution_id"] = receiving_institution_id
    return _merge(payload, overrides)


# --------------------------------------------------- transfer agreements
def agreement_payload(recommendation_id: str,
                      animal_id: str,
                      sending_institution_id: str,
                      receiving_institution_id: str,
                      ownership_disposition: str = "OWNERSHIP_TRANSFER",
                      offspring_disposition_rule: str = "SPLIT_50_50",
                      breeding_rights: str = "FULL",
                      transport_cost_share_pct: float = 51.0,
                      **overrides: Any) -> Dict[str, Any]:
    payload = {
        "recommendation_id": recommendation_id,
        "animal_id": animal_id,
        "sending_institution_id": sending_institution_id,
        "receiving_institution_id": receiving_institution_id,
        "ownership_disposition": ownership_disposition,
        "offspring_disposition_rule": offspring_disposition_rule,
        "breeding_rights": breeding_rights,
        "transport_cost_share_pct": transport_cost_share_pct,
    }
    return _merge(payload, overrides)


def terms_payload(transport_cost_share_pct: Optional[float] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """Negotiation terms for an offer or a counter."""
    payload: Dict[str, Any] = {}
    if transport_cost_share_pct is not None:
        payload["transport_cost_share_pct"] = transport_cost_share_pct
    return _merge(payload, overrides)


def termination_payload(reason: str = "Receiving institution withdrew the "
                                     "holding space",
                        **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    return _merge(payload, overrides)


# -------------------------------------------------- compliance documents
def document_payload(transfer_agreement_id: str,
                     document_type: str = "INTERSTATE_CVI",
                     issuing_veterinarian_id: Optional[str] = None,
                     issuing_authority_name: Optional[str] = None,
                     exam_date: Optional[str] = "2026-08-20",
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "transfer_agreement_id": transfer_agreement_id,
        "document_type": document_type,
    }
    if issuing_veterinarian_id is not None:
        payload["issuing_veterinarian_id"] = issuing_veterinarian_id
    if issuing_authority_name is not None:
        payload["issuing_authority_name"] = issuing_authority_name
    if exam_date is not None:
        payload["exam_date"] = exam_date
    return _merge(payload, overrides)


def cvi_payload(transfer_agreement_id: str, issuing_veterinarian_id: str,
                exam_date: str = "2026-08-20", **overrides: Any) -> Dict[str, Any]:
    """A health certificate: signed by a named veterinarian, no authority name."""
    return document_payload(
        transfer_agreement_id,
        document_type="INTERSTATE_CVI",
        issuing_veterinarian_id=issuing_veterinarian_id,
        exam_date=exam_date,
        **overrides,
    )


def permit_payload(transfer_agreement_id: str,
                   document_type: str = "STATE_IMPORT_PERMIT",
                   issuing_authority_name: str = "Texas Animal Health Commission",
                   **overrides: Any) -> Dict[str, Any]:
    """A permit application: named authority, no veterinarian and no exam date."""
    return document_payload(
        transfer_agreement_id,
        document_type=document_type,
        issuing_authority_name=issuing_authority_name,
        exam_date=None,
        **overrides,
    )


def document_decision_payload(outcome: str = "ISSUE",
                              document_number: Optional[str] = "DOC-2026-0001",
                              decision_note: Optional[str] = None,
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if document_number is not None:
        payload["document_number"] = document_number
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return _merge(payload, overrides)


# --------------------------------------------------- pre-shipment tests
def pre_shipment_test_payload(transfer_agreement_id: str,
                              animal_id: str,
                              collecting_veterinarian_id: str,
                              test_code: str = "TB",
                              collected_on: str = "2026-08-05",
                              result: str = "NEGATIVE",
                              lab_reference: str = "LAB-TB-0001",
                              **overrides: Any) -> Dict[str, Any]:
    payload = {
        "transfer_agreement_id": transfer_agreement_id,
        "animal_id": animal_id,
        "collecting_veterinarian_id": collecting_veterinarian_id,
        "test_code": test_code,
        "collected_on": collected_on,
        "result": result,
        "lab_reference": lab_reference,
    }
    return _merge(payload, overrides)


# ------------------------------------------------ quarantine occupancies
def quarantine_payload(transfer_agreement_id: str,
                       institution_id: str,
                       animal_id: str,
                       quarantine_room_code: str = "Q-ROOM-1",
                       scheduled_start_date: str = "2026-09-01",
                       scheduled_end_date: str = "2026-10-05",
                       **overrides: Any) -> Dict[str, Any]:
    payload = {
        "transfer_agreement_id": transfer_agreement_id,
        "institution_id": institution_id,
        "animal_id": animal_id,
        "quarantine_room_code": quarantine_room_code,
        "scheduled_start_date": scheduled_start_date,
        "scheduled_end_date": scheduled_end_date,
    }
    return _merge(payload, overrides)


def quarantine_clear_payload(clearance_note: str = "Cleared without incident",
                             **overrides: Any) -> Dict[str, Any]:
    payload = {"clearance_note": clearance_note}
    return _merge(payload, overrides)


def quarantine_fail_payload(failure_reason: str = "Clinical signs on day nineteen",
                            **overrides: Any) -> Dict[str, Any]:
    payload = {"failure_reason": failure_reason}
    return _merge(payload, overrides)


# --------------------------------------------------- shipment bookings
def booking_payload(transfer_agreement_id: str,
                    expected_transfer_agreement_version: int,
                    carrier_code: str = "AVI-CARGO-7",
                    crate_serial: str = "CR-CRATE-001",
                    departure_utc: str = "2026-09-01T08:00:00Z",
                    arrival_utc: str = "2026-09-01T20:00:00Z",
                    temp_min_c: float = 10.0,
                    temp_max_c: float = 24.0,
                    **overrides: Any) -> Dict[str, Any]:
    payload = {
        "transfer_agreement_id": transfer_agreement_id,
        "carrier_code": carrier_code,
        "crate_serial": crate_serial,
        "departure_utc": departure_utc,
        "arrival_utc": arrival_utc,
        "temp_min_c": temp_min_c,
        "temp_max_c": temp_max_c,
        "expected_transfer_agreement_version": expected_transfer_agreement_version,
    }
    return _merge(payload, overrides)


def delivery_payload(temperature_samples: Optional[List[float]] = None,
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "temperature_samples": (
            [18.0, 19.0, 18.5] if temperature_samples is None
            else temperature_samples
        )
    }
    return _merge(payload, overrides)


# ------------------------------------------------ introduction protocols
def protocol_payload(transfer_agreement_id: str,
                     animal_id: str,
                     institution_id: str,
                     resident_group_code: str = "SNOW-LEOPARD-A",
                     **overrides: Any) -> Dict[str, Any]:
    payload = {
        "transfer_agreement_id": transfer_agreement_id,
        "animal_id": animal_id,
        "institution_id": institution_id,
        "resident_group_code": resident_group_code,
    }
    return _merge(payload, overrides)


def observation_payload(aggression_level: str = "CALM",
                        observed_on: str = "2026-10-02",
                        observer_name: str = "M Solano",
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "aggression_level": aggression_level,
        "observer_name": observer_name,
        "observed_on": observed_on,
    }
    return _merge(payload, overrides)


# ------------------------------------------------ studbook submissions
def studbook_submission_payload(species_program_id: str,
                                institution_id: str,
                                submission_type: str = "BIRTH",
                                reporting_period_end: str = "2026-07-15",
                                **overrides: Any) -> Dict[str, Any]:
    payload = {
        "species_program_id": species_program_id,
        "institution_id": institution_id,
        "submission_type": submission_type,
        "reporting_period_end": reporting_period_end,
    }
    return _merge(payload, overrides)


def studbook_review_payload(outcome: str = "ACCEPT",
                            review_note: str = "clean",
                            **overrides: Any) -> Dict[str, Any]:
    payload = {"outcome": outcome, "review_note": review_note}
    return _merge(payload, overrides)
