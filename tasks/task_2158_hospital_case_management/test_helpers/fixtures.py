"""Composite setup helpers.

Every test starts against an empty database with the logical clock reading
2026-08-01T00:00:00Z, so each helper builds its preconditions from scratch using
only endpoints the PRD declares. Setup calls use the lenient `get_success_data`
validator so a broken precondition reads as a setup failure rather than as a
confusing assertion failure inside the test body.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    authorization_payload,
    barrier_payload,
    dme_order_payload,
    document_choice_payload,
    episode_payload,
    network_contract_payload,
    offer_payload,
    patient_payload,
    payer_payload,
    provider_payload,
    referral_payload,
    screening_payload,
    transport_order_payload,
    vehicle_payload,
)
from .test_users import (
    CASE_MANAGER,
    CM_ALPHA_ID,
    DISCHARGE_COORDINATOR,
    PLATFORM_ADMIN,
    UR_NURSE,
    make_liaison_headers,
    make_payer_rep_headers,
)


# ==========================================================================
# Tier 0 — single-call primitives
# ==========================================================================
def set_logical_clock(to_iso8601: str) -> dict:
    """PRD §2.6: a PlatformAdmin replaces the logical clock; no rows are mutated."""
    return get_success_data(api_client.set_clock(to_iso8601, PLATFORM_ADMIN))


def seed_payer(**overrides) -> dict:
    return get_success_data(api_client.create_payer(payer_payload(**overrides), PLATFORM_ADMIN))


def seed_patient(payer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_patient(patient_payload(payer_id, **overrides), PLATFORM_ADMIN)
    )


def seed_provider(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider(provider_payload(**overrides), PLATFORM_ADMIN)
    )


def seed_snf_slate() -> list:
    """The three ACTIVE skilled-nursing facilities every placement search uses."""
    cedar = seed_provider(
        name="Cedar SNF", provider_type="SNF", quality_star_rating=4,
        distance_miles_from_hospital=6, bed_unit_codes=["UNIT-A", "UNIT-B"],
    )
    birch = seed_provider(
        name="Birch SNF", provider_type="SNF", quality_star_rating=5,
        distance_miles_from_hospital=22, bed_unit_codes=["UNIT-A"],
    )
    alder = seed_provider(
        name="Alder SNF", provider_type="SNF", quality_star_rating=3,
        distance_miles_from_hospital=12, bed_unit_codes=["UNIT-A"],
    )
    return [cedar, birch, alder]


def seed_dme_supplier(**overrides) -> dict:
    defaults = {
        "name": "Summit DME", "provider_type": "DME_SUPPLIER", "quality_star_rating": 4,
        "distance_miles_from_hospital": 3, "bed_unit_codes": [],
    }
    defaults.update(overrides)
    return seed_provider(**defaults)


def seed_vehicle(**overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(vehicle_payload(**overrides), PLATFORM_ADMIN)
    )


def seed_network_contract(payer_id: str, provider_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_network_contract(
            network_contract_payload(payer_id, provider_id, **overrides), PLATFORM_ADMIN
        )
    )


def open_episode(patient_id: str, headers=CASE_MANAGER, **overrides) -> dict:
    return get_success_data(
        api_client.create_episode(episode_payload(patient_id, **overrides), headers)
    )


def create_screening_draft(episode_id: str, headers=CASE_MANAGER, **overrides) -> dict:
    return get_success_data(
        api_client.create_screening(episode_id, screening_payload(**overrides), headers)
    )


def submit_screening_row(screening_id: str, headers=CASE_MANAGER) -> dict:
    return get_success_data(api_client.submit_screening(screening_id, headers))


def open_barrier(episode_id: str, headers=CASE_MANAGER, **overrides) -> dict:
    return get_success_data(
        api_client.create_barrier(episode_id, barrier_payload(**overrides), headers)
    )


def move_barrier(barrier_id: str, to_status: str, headers=CASE_MANAGER, note=None) -> dict:
    payload = {"to_status": to_status}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.change_barrier_status(barrier_id, payload, headers))


def read_episode(episode_id: str, headers=CASE_MANAGER) -> dict:
    return get_success_data(api_client.get_episode(episode_id, headers))


def read_episode_version(episode_id: str, headers=CASE_MANAGER) -> int:
    return read_episode(episode_id, headers)["version"]


def read_referral(referral_id: str, headers=CASE_MANAGER) -> dict:
    return get_success_data(api_client.get_referral(referral_id, headers))


def read_referral_version(referral_id: str, headers=CASE_MANAGER) -> int:
    return read_referral(referral_id, headers)["version"]


def read_provider(provider_id: str, headers=CASE_MANAGER) -> dict:
    return get_success_data(api_client.get_provider(provider_id, headers))


def read_offer(offer_id: str, headers=CASE_MANAGER) -> dict:
    return get_success_data(api_client.get_offer(offer_id, headers))


def read_authorization(authorization_id: str, headers=CASE_MANAGER) -> dict:
    return get_success_data(api_client.get_authorization(authorization_id, headers))


def read_logistics_order(order_id: str, headers=CASE_MANAGER) -> dict:
    return get_success_data(api_client.get_logistics_order(order_id, headers))


def read_barriers(episode_id: str, headers=CASE_MANAGER, params=None) -> list:
    return get_success_data(api_client.list_barriers(episode_id, headers, params))


def record_bundle(episode_id: str, headers=CASE_MANAGER, **flags) -> dict:
    return get_success_data(
        api_client.record_readmission_bundle(episode_id, dict(flags), headers)
    )


# ==========================================================================
# Tier 1 — episode state progression
# ==========================================================================
def setup_screened_episode(payer=None, patient=None, episode=None, screening=None) -> dict:
    """Payer + patient + episode + a SUBMITTED ADMISSION screening.

    With the default patient (has_pcp true, lives_alone false) and the default
    scores (functional 8) neither screening derivation rule fires, so the episode
    lands at SCREENED with barrier_posture CLEAR and no barrier rows.
    """
    payer_row = seed_payer(**(payer or {}))
    patient_row = seed_patient(payer_row["id"], **(patient or {}))
    episode_row = open_episode(patient_row["id"], **(episode or {}))
    screening_row = create_screening_draft(episode_row["id"], **(screening or {}))
    submitted = submit_screening_row(screening_row["id"])
    return {
        "payer": payer_row,
        "patient": patient_row,
        "episode": read_episode(episode_row["id"]),
        "screening": submitted,
    }


def setup_planning_episode(bundle=None, **kwargs) -> dict:
    """A SCREENED episode advanced to PLANNING by recording a readmission-risk
    intervention, which is a planning artifact (PRD §3.8)."""
    env = setup_screened_episode(**kwargs)
    flags = bundle if bundle is not None else {"pcp_followup_booked": True}
    env["episode"] = record_bundle(env["episode"]["id"], **flags)
    return env


# ==========================================================================
# Tier 2 — placement search
# ==========================================================================
def setup_broadcast_referral(referral=None, contracts=None, **kwargs) -> dict:
    """Screened episode + three ACTIVE SNF providers + a referral broadcast to all
    three, so round_index is 1 and the referral sits at BROADCAST."""
    env = setup_screened_episode(**kwargs)
    providers = seed_snf_slate()
    for spec in contracts or []:
        seed_network_contract(
            env["payer"]["id"], providers[spec["index"]]["id"],
            in_network=spec.get("in_network", True),
            negotiated_daily_rate_cents=spec.get("negotiated_daily_rate_cents", 30000),
        )
    referral_row = get_success_data(
        api_client.create_referral(
            env["episode"]["id"], referral_payload(**(referral or {})), CASE_MANAGER
        )
    )
    broadcast = get_success_data(
        api_client.broadcast_referral(
            referral_row["id"], {"provider_ids": [p["id"] for p in providers]}, CASE_MANAGER
        )
    )
    env.update(
        providers=providers,
        provider_a=providers[0],
        provider_b=providers[1],
        provider_c=providers[2],
        referral=broadcast,
        referral_version=broadcast["version"],
    )
    return env


def place_offer(referral_id: str, provider_id: str, expected_referral_version: int, **overrides) -> dict:
    """A liaison answers a round. X-User-ID must be the offering provider's id."""
    return get_success_data(
        api_client.create_offer(
            referral_id,
            offer_payload(expected_referral_version, **overrides),
            make_liaison_headers(provider_id),
        )
    )


def setup_choice_pending_referral(offer=None, offering_index=0, **kwargs) -> dict:
    """A broadcast referral answered by one provider, so the referral has moved
    BROADCAST -> CHOICE_PENDING and one bed offer is OFFERED."""
    env = setup_broadcast_referral(**kwargs)
    offering = env["providers"][offering_index]
    env["offer"] = place_offer(
        env["referral"]["id"], offering["id"], env["referral_version"], **(offer or {})
    )
    env["offering_provider"] = offering
    env["referral"] = read_referral(env["referral"]["id"])
    env["referral_version"] = env["referral"]["version"]
    return env


def setup_placed_referral(choice=None, **kwargs) -> dict:
    """A choice-pending referral driven all the way to PLACED."""
    env = setup_choice_pending_referral(**kwargs)
    env["referral"] = get_success_data(
        api_client.document_choice(
            env["referral"]["id"],
            document_choice_payload(env["offer"]["id"], **(choice or {})),
            CASE_MANAGER,
        )
    )
    env["offer"] = read_offer(env["offer"]["id"])
    env["episode"] = read_episode(env["episode"]["id"])
    return env


# ==========================================================================
# Tier 3 — authorization
# ==========================================================================
def submit_authorization(episode_id: str, provider_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_authorization(
            episode_id, authorization_payload(provider_id, **overrides), CASE_MANAGER
        )
    )


def decide_authorization(authorization_id: str, payer_id: str, **payload) -> dict:
    return get_success_data(
        api_client.decide_authorization(
            authorization_id, dict(payload), make_payer_rep_headers(payer_id)
        )
    )


def setup_approved_authorization(auth=None, decision=None, **kwargs) -> dict:
    """A screened episode with one provider and an APPROVED authorization."""
    env = setup_screened_episode(**kwargs)
    provider = seed_provider()
    authorization = submit_authorization(env["episode"]["id"], provider["id"], **(auth or {}))
    env["provider"] = provider
    env["authorization"] = decide_authorization(
        authorization["id"], env["payer"]["id"], **(decision or {"decision": "APPROVE"})
    )
    return env


# ==========================================================================
# Tier 4 — logistics
# ==========================================================================
def create_transport_order(episode_id: str, vehicle_id: str, **overrides) -> dict:
    version = read_episode_version(episode_id)
    return get_success_data(
        api_client.create_logistics_order(
            episode_id, transport_order_payload(version, vehicle_id, **overrides), CASE_MANAGER
        )
    )


def create_dme_order(episode_id: str, supplier_provider_id: str, **overrides) -> dict:
    version = read_episode_version(episode_id)
    return get_success_data(
        api_client.create_logistics_order(
            episode_id,
            dme_order_payload(version, supplier_provider_id, **overrides),
            CASE_MANAGER,
        )
    )


def confirm_order(order_id: str, headers=DISCHARGE_COORDINATOR) -> dict:
    return get_success_data(api_client.confirm_logistics_order(order_id, headers))


def setup_confirmed_transport(vehicle=None, order=None, **kwargs) -> dict:
    """A screened episode with one CONFIRMED PATIENT_TRANSPORT order, so
    logistics_committed_cents carries that order's cost."""
    env = setup_screened_episode(**kwargs)
    vehicle_row = seed_vehicle(**(vehicle or {}))
    order_row = create_transport_order(env["episode"]["id"], vehicle_row["id"], **(order or {}))
    env["vehicle"] = vehicle_row
    env["order"] = confirm_order(order_row["id"])
    env["episode"] = read_episode(env["episode"]["id"])
    return env


# ==========================================================================
# Tier 5 — readiness and discharge
# ==========================================================================
def mark_episode_ready(episode_id: str, discharge_disposition="HOME_SELF_CARE",
                       headers=CASE_MANAGER) -> dict:
    return get_success_data(
        api_client.mark_ready(
            episode_id, {"discharge_disposition": discharge_disposition}, headers
        )
    )


def setup_ready_episode(discharge_disposition="HOME_SELF_CARE", bundle=None, **kwargs) -> dict:
    """A PLANNING episode with a complete bundle and no open barriers, driven to
    READY_FOR_DISCHARGE by cm-alpha."""
    env = setup_planning_episode(bundle=bundle, **kwargs)
    env["episode"] = mark_episode_ready(env["episode"]["id"], discharge_disposition)
    env["marked_ready_by"] = CM_ALPHA_ID
    return env


def waive_barrier(barrier_id: str, headers=UR_NURSE) -> dict:
    """Only a UtilizationReviewNurse other than the opener may waive (PRD §2.10)."""
    return move_barrier(barrier_id, "WAIVED", headers)
