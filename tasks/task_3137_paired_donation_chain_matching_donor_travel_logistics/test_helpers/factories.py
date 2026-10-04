"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


# --- TransplantCenter ---

def create_center_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "center_code": f"XX-TST-{i:03d}",
        "name": f"Test Center {i}",
        "region_code": "TST",
        "tier": "STANDARD",
        "max_concurrent_chains": 4,
    }
    defaults.update(overrides)
    return defaults


# --- Donor ---

def create_donor_payload(home_center_id: str, **overrides) -> dict:
    i = _n()
    defaults = {
        "external_ref": f"D-{i}",
        "home_center_id": home_center_id,
        "abo_type": "O",
        "hla_a": "A02,A24",
        "hla_b": "B07,B44",
        "hla_drb1": "DRB1*04,DRB1*07",
        "kdri_score": 80,
        "age_at_registration": 30,
        "donor_kind": "PAIRED",
    }
    defaults.update(overrides)
    return defaults


# --- Recipient ---

def create_recipient_payload(home_center_id: str, **overrides) -> dict:
    i = _n()
    defaults = {
        "external_ref": f"R-{i}",
        "home_center_id": home_center_id,
        "abo_type": "A",
        "cpra_percent": 20,
        "unacceptable_antigens": [],
    }
    defaults.update(overrides)
    return defaults


# --- DonorRecipientPair ---

def create_pair_payload(donor_id: str, recipient_id: str, registered_center_id: str,
                        **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "recipient_id": recipient_id,
        "registered_center_id": registered_center_id,
    }
    defaults.update(overrides)
    return defaults


# --- ChainRun ---

def create_chain_run_payload(**overrides) -> dict:
    i = _n()
    defaults = {"run_label": f"run-{i}"}
    defaults.update(overrides)
    return defaults


# --- SurgeryScheduleSlot ---

def create_slot_payload(center_id: str, slot_start_utc: str, slot_end_utc: str,
                        **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "slot_start_utc": slot_start_utc,
        "slot_end_utc": slot_end_utc,
        "room_kind": "NEPHRECTOMY_OR",
    }
    defaults.update(overrides)
    return defaults


# --- OrganShipment ---

def create_shipment_payload(match_offer_id: str, **overrides) -> dict:
    defaults = {
        "match_offer_id": match_offer_id,
        "shipment_mode": "COMMERCIAL_FLIGHT",
        "scheduled_departure_utc": "2026-09-10T08:00:00Z",
        "scheduled_arrival_utc": "2026-09-10T16:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# --- TravelItinerary ---

def create_itinerary_payload(donor_id: str, **overrides) -> dict:
    defaults = {
        "donor_id": donor_id,
        "origin_airport_code": "SFO",
        "destination_airport_code": "JFK",
        "depart_utc": "2026-09-10T08:00:00Z",
        "arrive_utc": "2026-09-10T16:00:00Z",
        "segment_miles": 2586,
        "lodging_nights": 0,
    }
    defaults.update(overrides)
    return defaults


# --- CrossmatchReview ---

def create_crossmatch_review_payload(**overrides) -> dict:
    defaults = {
        "virtual_result": "NEGATIVE",
        "flow_cytometry_channel_shift": 100,
        "dsa_mfi_max": 0,
        "review_notes": "routine review",
    }
    defaults.update(overrides)
    return defaults


# --- DonorProtectionClaim ---

def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_kind": "COMPLICATION",
        "requested_amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


# --- TransplantOutcome ---

def create_outcome_payload(match_offer_id: str, **overrides) -> dict:
    defaults = {
        "match_offer_id": match_offer_id,
        "outcome_kind": "SUCCESS",
        "followup_days": 30,
    }
    defaults.update(overrides)
    return defaults
