"""Payload builders and state constructors.

Every test starts against an empty database, so all state is built from scratch
through the PRD's own endpoints.  Money is always sent as a JSON number of whole
cents; every instant is sent in the canonical three-fractional-digit UTC form.
"""
import itertools
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_success

from .api_client import ArbitrationApiClient
from .constants import (
    CLOCK_DEFAULT,
    FRAME_DAMAGE_POLICY,
    MECHANICAL_POLICY,
    TEST_DEFAULTS,
)
from .test_users import (
    admin_headers,
    buyer_rep_headers,
    clerk_headers,
    deciding_arbitrator_headers,
    inspector_headers,
    intake_arbitrator_headers,
    seller_rep_headers,
)

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def unique_license(prefix: str = "DL") -> str:
    """A dealer licence number in the 4..24 character band, globally unique."""
    return f"{prefix}{_next():06d}"


def unique_vin() -> str:
    """Exactly 17 uppercase alphanumeric characters."""
    return f"WAA{_next():014d}"


# --- Payload builders ---------------------------------------------------------


def seller_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": TEST_DEFAULTS["SELLER_NAME"],
        "dealer_license_no": unique_license("SL"),
    }
    payload.update(overrides)
    return payload


def buyer_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": TEST_DEFAULTS["BUYER_NAME"],
        "dealer_license_no": unique_license("BL"),
    }
    payload.update(overrides)
    return payload


def policy_payload(preset: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    payload = dict(preset if preset is not None else MECHANICAL_POLICY)
    payload.update(overrides)
    return payload


def sale_payload(seller_id: str, buyer_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "vin": unique_vin(),
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "sale_price_cents": TEST_DEFAULTS["SALE_PRICE_CENTS"],
        "hammer_time_utc": CLOCK_DEFAULT,
        "announced_odometer_miles": TEST_DEFAULTS["ANNOUNCED_ODOMETER_MILES"],
        "light_channel": "GREEN",
        "title_status": "CLEAN",
    }
    payload.update(overrides)
    return payload


def announcement_payload(defect_class: str, **overrides) -> Dict[str, Any]:
    payload = {
        "defect_class": defect_class,
        "disclosure_text": f"Announced {defect_class} at the block.",
    }
    payload.update(overrides)
    return payload


def inspection_payload(sale_id: str, program_tier: str = "STANDARD", **overrides):
    payload = {"sale_id": sale_id, "program_tier": program_tier}
    payload.update(overrides)
    return payload


def case_payload(
    sale_id: str,
    defect_class: str = "MECHANICAL",
    claim_amount_cents: int = 285000,
    odometer_at_claim: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "sale_id": sale_id,
        "defect_class": defect_class,
        "claim_amount_cents": claim_amount_cents,
        "odometer_at_claim": (
            odometer_at_claim
            if odometer_at_claim is not None
            else TEST_DEFAULTS["ANNOUNCED_ODOMETER_MILES"] + 40
        ),
        "complaint_text": f"Undisclosed {defect_class} found after the sale.",
    }
    payload.update(overrides)
    return payload


def evidence_payload(
    evidence_type: str = "INSPECTION_REPORT",
    repair_estimate_cents: Optional[int] = None,
    odometer_reading: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_type": evidence_type,
        "provider_name": "Bayside Diagnostics",
        "document_reference": f"DOC-{_next():06d}",
    }
    if repair_estimate_cents is not None:
        payload["repair_estimate_cents"] = repair_estimate_cents
    if odometer_reading is not None:
        payload["odometer_reading"] = odometer_reading
    payload.update(overrides)
    return payload


def transport_leg_payload(
    expected_case_version: int,
    miles: int,
    leg_type: str = "INBOUND_TO_AUCTION",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "leg_type": leg_type,
        "miles": miles,
        "carrier_name": "Longhaul Transit",
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def decision_payload(
    outcome: str,
    fault_party: str = "SELLER",
    requested_allowance_cents: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "fault_party": fault_party,
        "rationale": f"Decision rendered: {outcome} with fault on {fault_party}.",
    }
    if requested_allowance_cents is not None:
        payload["requested_allowance_cents"] = requested_allowance_cents
    payload.update(overrides)
    return payload


# --- State constructors -------------------------------------------------------


def create_seller(client: ArbitrationApiClient, **overrides) -> Dict[str, Any]:
    response = client.create_seller(seller_payload(**overrides), admin_headers())
    return validate_success(response, 201)


def create_buyer(client: ArbitrationApiClient, **overrides) -> Dict[str, Any]:
    response = client.create_buyer(buyer_payload(**overrides), admin_headers())
    return validate_success(response, 201)


def create_policy(
    client: ArbitrationApiClient, preset: Optional[Dict[str, Any]] = None, **overrides
) -> Dict[str, Any]:
    response = client.create_policy(policy_payload(preset, **overrides), admin_headers())
    return validate_success(response, 201)


def create_sale(
    client: ArbitrationApiClient, seller_id: str, buyer_id: str, **overrides
) -> Dict[str, Any]:
    response = client.create_sale(
        sale_payload(seller_id, buyer_id, **overrides), clerk_headers()
    )
    return validate_success(response, 201)


def create_announcement(
    client: ArbitrationApiClient, sale_id: str, defect_class: str, **overrides
) -> Dict[str, Any]:
    response = client.create_announcement(
        sale_id, announcement_payload(defect_class, **overrides), clerk_headers()
    )
    return validate_success(response, 201)


def settle_sale(client: ArbitrationApiClient, sale_id: str) -> Dict[str, Any]:
    return validate_success(client.settle_sale(sale_id, {}, admin_headers()), 200)


def create_inspection(
    client: ArbitrationApiClient,
    sale_id: str,
    buyer_id: str,
    program_tier: str = "STANDARD",
    **overrides,
) -> Dict[str, Any]:
    response = client.create_inspection(
        inspection_payload(sale_id, program_tier, **overrides),
        buyer_rep_headers(buyer_id),
    )
    return validate_success(response, 201)


def complete_inspection(
    client: ArbitrationApiClient, inspection_id: str, findings: List[str]
) -> Dict[str, Any]:
    response = client.complete_inspection(
        inspection_id, {"findings": findings}, inspector_headers()
    )
    return validate_success(response, 200)


def create_case(
    client: ArbitrationApiClient, sale_id: str, buyer_id: str, **overrides
) -> Dict[str, Any]:
    response = client.create_case(
        case_payload(sale_id, **overrides), buyer_rep_headers(buyer_id)
    )
    return validate_success(response, 201)


def create_evidence(
    client: ArbitrationApiClient, case_id: str, buyer_id: str, **overrides
) -> Dict[str, Any]:
    response = client.create_evidence(
        case_id, evidence_payload(**overrides), buyer_rep_headers(buyer_id)
    )
    return validate_success(response, 201)


def open_review(client: ArbitrationApiClient, case_id: str) -> Dict[str, Any]:
    response = client.open_review(case_id, {}, intake_arbitrator_headers())
    return validate_success(response, 200)


def seller_response(
    client: ArbitrationApiClient,
    case_id: str,
    seller_id: str,
    response_type: str,
    seller_offer_cents: Optional[int] = None,
    note: str = "Consignor response filed.",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "response_type": response_type,
        "response_note": note,
    }
    if seller_offer_cents is not None:
        payload["seller_offer_cents"] = seller_offer_cents
    response = client.seller_response(case_id, payload, seller_rep_headers(seller_id))
    return validate_success(response, 201)


def counter_round(
    client: ArbitrationApiClient,
    case_id: str,
    round_id: str,
    buyer_id: str,
    buyer_demand_cents: int,
    note: str = "Buyer counters the standing offer.",
) -> Dict[str, Any]:
    response = client.counter_round(
        case_id,
        round_id,
        {"buyer_demand_cents": buyer_demand_cents, "counter_note": note},
        buyer_rep_headers(buyer_id),
    )
    return validate_success(response, 200)


def accept_round(
    client: ArbitrationApiClient, case_id: str, round_id: str, buyer_id: str
) -> Dict[str, Any]:
    response = client.accept_round(case_id, round_id, {}, buyer_rep_headers(buyer_id))
    # PRD 3.6 Hop 2: accepting an offer brings an `ArbitrationDecision` row into
    # existence, and PRD 4: "Requests that bring a new record into existence answer
    # `201 Created` and return the created row in `data`".
    return validate_success(response, 201)


def create_transport_leg(
    client: ArbitrationApiClient,
    case_id: str,
    expected_case_version: int,
    miles: int,
    leg_type: str = "INBOUND_TO_AUCTION",
    **overrides,
) -> Dict[str, Any]:
    response = client.create_transport_leg(
        case_id,
        transport_leg_payload(expected_case_version, miles, leg_type, **overrides),
        admin_headers(),
    )
    return validate_success(response, 201)


def escalate_case(
    client: ArbitrationApiClient, case_id: str, note: str = "Negotiation exhausted."
) -> Dict[str, Any]:
    response = client.escalate_case(
        case_id, {"escalation_note": note}, intake_arbitrator_headers()
    )
    return validate_success(response, 200)


def decide_case(
    client: ArbitrationApiClient,
    case_id: str,
    outcome: str,
    fault_party: str = "SELLER",
    requested_allowance_cents: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    response = client.create_decision(
        case_id,
        decision_payload(outcome, fault_party, requested_allowance_cents, **overrides),
        deciding_arbitrator_headers(),
    )
    return validate_success(response, 201)


def withdraw_case(
    client: ArbitrationApiClient,
    case_id: str,
    buyer_id: str,
    reason: str = "Buyer abandons the claim.",
) -> Dict[str, Any]:
    response = client.withdraw_case(
        case_id, {"withdraw_reason": reason}, buyer_rep_headers(buyer_id)
    )
    return validate_success(response, 200)


def reinstate_seller(
    client: ArbitrationApiClient, seller_id: str, note: str = "Reinstated after review."
) -> Dict[str, Any]:
    response = client.reinstate_seller(
        seller_id, {"reinstate_note": note}, admin_headers()
    )
    return validate_success(response, 200)


def pay_fee(
    client: ArbitrationApiClient,
    buyer_id: str,
    amount_cents: int,
    expected_buyer_version: int,
) -> Dict[str, Any]:
    response = client.pay_buyer_fee(
        buyer_id,
        {
            "amount_cents": amount_cents,
            "expected_buyer_version": expected_buyer_version,
        },
        buyer_rep_headers(buyer_id),
    )
    return validate_success(response, 200)


def set_clock(client: ArbitrationApiClient, to_iso8601: str) -> Dict[str, Any]:
    return validate_success(client.set_clock(to_iso8601, admin_headers()), 200)


def run_sweep(client: ArbitrationApiClient) -> Dict[str, Any]:
    return validate_success(client.run_sweep(admin_headers()), 200)


# --- Composite scenario builders ---------------------------------------------


def build_registry(
    client: ArbitrationApiClient,
    policy_presets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A seller, a buyer and one policy per requested preset."""
    seller = create_seller(client)
    buyer = create_buyer(client)
    presets = policy_presets if policy_presets is not None else [MECHANICAL_POLICY]
    policies = {}
    for preset in presets:
        policy = create_policy(client, preset)
        policies[policy["defect_class"]] = policy
    return {"seller": seller, "buyer": buyer, "policies": policies}


def build_sale_world(
    client: ArbitrationApiClient,
    policy_presets: Optional[List[Dict[str, Any]]] = None,
    **sale_overrides,
) -> Dict[str, Any]:
    """Registry plus one recorded sale."""
    world = build_registry(client, policy_presets)
    world["sale"] = create_sale(
        client, world["seller"]["id"], world["buyer"]["id"], **sale_overrides
    )
    return world


def build_case_world(
    client: ArbitrationApiClient,
    policy_presets: Optional[List[Dict[str, Any]]] = None,
    sale_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Registry, sale and a filed claim in SUBMITTED."""
    world = build_sale_world(client, policy_presets, **(sale_overrides or {}))
    world["case"] = create_case(
        client,
        world["sale"]["id"],
        world["buyer"]["id"],
        **(case_overrides or {}),
    )
    return world


def build_under_review_world(
    client: ArbitrationApiClient,
    policy_presets: Optional[List[Dict[str, Any]]] = None,
    sale_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
    repair_estimate_cents: int = 285000,
    extra_evidence_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A case carried to UNDER_REVIEW with a verified inspection report on file."""
    world = build_case_world(client, policy_presets, sale_overrides, case_overrides)
    create_evidence(
        client,
        world["case"]["id"],
        world["buyer"]["id"],
        evidence_type="INSPECTION_REPORT",
        repair_estimate_cents=repair_estimate_cents,
    )
    for evidence_type in extra_evidence_types or []:
        create_evidence(
            client,
            world["case"]["id"],
            world["buyer"]["id"],
            evidence_type=evidence_type,
        )
    world["case"] = open_review(client, world["case"]["id"])
    return world


def build_negotiation_world(
    client: ArbitrationApiClient,
    seller_offer_cents: int = 200000,
    policy_presets: Optional[List[Dict[str, Any]]] = None,
    sale_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
    repair_estimate_cents: int = 285000,
    extra_evidence_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A case in NEGOTIATION with one OPEN allowance offer on the table."""
    world = build_under_review_world(
        client,
        policy_presets,
        sale_overrides,
        case_overrides,
        repair_estimate_cents=repair_estimate_cents,
        extra_evidence_types=extra_evidence_types,
    )
    world["round"] = seller_response(
        client,
        world["case"]["id"],
        world["seller"]["id"],
        "OFFER_REPAIR_ALLOWANCE",
        seller_offer_cents=seller_offer_cents,
    )
    world["case"] = validate_success(
        client.get_case(world["case"]["id"], admin_headers()), 200
    )
    return world


def build_arbitrator_review_world(
    client: ArbitrationApiClient,
    policy_presets: Optional[List[Dict[str, Any]]] = None,
    sale_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
    repair_estimate_cents: int = 285000,
    extra_evidence_types: Optional[List[str]] = None,
    response_type: str = "DISPUTE",
) -> Dict[str, Any]:
    """A case in ARBITRATOR_REVIEW via an outright dispute or a conceded unwind."""
    world = build_under_review_world(
        client,
        policy_presets,
        sale_overrides,
        case_overrides,
        repair_estimate_cents=repair_estimate_cents,
        extra_evidence_types=extra_evidence_types,
    )
    world["round"] = seller_response(
        client, world["case"]["id"], world["seller"]["id"], response_type
    )
    world["case"] = validate_success(
        client.get_case(world["case"]["id"], admin_headers()), 200
    )
    return world


FRAME_PRESETS = [MECHANICAL_POLICY, FRAME_DAMAGE_POLICY]
