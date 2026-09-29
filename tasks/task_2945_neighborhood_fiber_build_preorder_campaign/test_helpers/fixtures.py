"""Composite setup helpers.

Every helper here builds its preconditions from an empty database, because each
test runs against a freshly started server. Setup calls go through
`get_success_data()` so a broken precondition reports as a setup failure rather
than as a confusing assertion failure.
"""

from typing import Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_AFTER_DEADLINE, CLOCK_EPOCH
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_mdu_owner_headers,
    make_subscriber_headers,
)

PM = TEST_USERS["program_manager_headers"]
PERMIT_OFFICE = TEST_USERS["permit_office_headers"]
UTILITY = TEST_USERS["utility_operator_headers"]
COORDINATOR = TEST_USERS["install_coordinator_headers"]
ASSESSOR = TEST_USERS["claims_assessor_headers"]
APPROVER = TEST_USERS["claims_approver_headers"]

STREET_ADDRESSES = [
    "1 Elm St",
    "3 Elm St",
    "5 Elm St",
    "7 Elm St",
    "9 Elm St",
    "11 Elm St",
]

ACCOUNT_SPECS = [
    ("Ann Reyes", "ann@example.com", "+13035550101"),
    ("Ben Ortiz", "ben@example.com", "+13035550102"),
    ("Cara Lin", "cara@example.com", "+13035550103"),
    ("Dan Fox", "dan@example.com", "+13035550104"),
    ("Eve Kim", "eve@example.com", "+13035550105"),
]


# --- Primitives --------------------------------------------------------------
def set_clock(instant: str = CLOCK_EPOCH) -> None:
    """Pin the logical clock, which drives every deadline, expiry and SLA rule."""
    get_success_data(api_client.set_clock(instant, PM))


def make_campaign(**overrides) -> dict:
    return get_success_data(api_client.create_campaign(f.campaign_payload(**overrides), PM))


def make_zone(campaign_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_build_zone(f.build_zone_payload(campaign_id, **overrides), PM)
    )


def make_address(build_zone_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_address(
            f.service_address_payload(build_zone_id, **overrides), PM
        )
    )


def make_mdu_address(build_zone_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_address(
            f.mdu_address_payload(build_zone_id, **overrides), PM
        )
    )


def set_serviceability(
    service_address_id: str, serviceability: str = "SERVICEABLE", **extra
) -> dict:
    return get_success_data(
        api_client.determine_serviceability(
            service_address_id, f.serviceability_payload(serviceability, **extra), PM
        )
    )


def make_account(index: int = 0, **overrides) -> dict:
    full_name, email, phone = ACCOUNT_SPECS[index]
    payload = f.account_payload(full_name=full_name, email=email, phone=phone)
    payload.update(overrides)
    return get_success_data(api_client.create_account(payload, PM))


def make_owner_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_account(f.owner_account_payload(**overrides), PM)
    )


def read_zone(build_zone_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_build_zone(build_zone_id, headers or PM))


def read_zone_version(build_zone_id: str) -> int:
    return read_zone(build_zone_id)["version"]


def read_crew(crew_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_install_crew(crew_id, headers or COORDINATOR))


def read_crew_version(crew_id: str) -> int:
    return read_crew(crew_id)["version"]


def read_preorder(preorder_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_preorder(preorder_id, headers or PM))


def read_address(service_address_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_service_address(service_address_id, headers or PM)
    )


def read_account(account_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_account(account_id, headers or PM))


def read_appointment(appointment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_install_appointment(appointment_id, headers or COORDINATOR)
    )


def read_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_damage_claim(claim_id, headers or PM))


def make_preorder(
    build_zone_id: str, service_address_id: str, account_id: str, **overrides
) -> dict:
    """Sign a preorder up, re-reading the zone's version immediately beforehand."""
    expected_version = overrides.pop(
        "expected_build_zone_version", read_zone_version(build_zone_id)
    )
    payload = f.preorder_payload(
        build_zone_id, service_address_id, account_id, expected_version, **overrides
    )
    return get_success_data(
        api_client.create_preorder(payload, make_subscriber_headers(account_id))
    )


def make_permit(
    build_zone_id: str,
    permit_type: str = "ROW",
    target_status: str = "APPROVED",
    **overrides,
) -> dict:
    """Open a permit application and walk it to `target_status`."""
    application = get_success_data(
        api_client.create_permit_application(
            f.permit_application_payload(
                build_zone_id, permit_type=permit_type, **overrides
            ),
            PM,
        )
    )
    if target_status == "DRAFT":
        return application
    application = get_success_data(
        api_client.submit_permit_application(application["id"], PM)
    )
    if target_status == "SUBMITTED":
        return application
    decision = "APPROVE" if target_status == "APPROVED" else "REJECT"
    payload = f.permit_decision_payload(decision)
    if decision == "REJECT":
        payload["rejection_reason"] = "Missing the detour drawing."
    return get_success_data(
        api_client.decide_permit_application(application["id"], payload, PERMIT_OFFICE)
    )


def make_pole_request(
    build_zone_id: str,
    target_status: str = "ATTACHED",
    make_ready_cost_cents: int = 12000,
    denial_reason: str = "CAPACITY_FULL",
    decision_headers=None,
    **overrides,
) -> dict:
    """Raise a pole-attachment request and walk it to `target_status`."""
    request = get_success_data(
        api_client.create_pole_attachment_request(
            f.pole_attachment_request_payload(build_zone_id, **overrides), PM
        )
    )
    if target_status == "REQUESTED":
        return request
    request = get_success_data(
        api_client.survey_pole_attachment_request(
            request["id"], f.pole_survey_payload(make_ready_cost_cents), UTILITY
        )
    )
    if target_status == "SURVEYED":
        return request
    if target_status == "DENIED":
        return get_success_data(
            api_client.decide_pole_attachment_request(
                request["id"],
                f.pole_decision_payload("DENY", denial_reason=denial_reason),
                decision_headers or UTILITY,
            )
        )
    request = get_success_data(
        api_client.decide_pole_attachment_request(
            request["id"], f.pole_decision_payload("ACCEPT"), decision_headers or PM
        )
    )
    if target_status == "ACCEPTED":
        return request
    return get_success_data(
        api_client.attach_pole_attachment_request(request["id"], UTILITY)
    )


def make_crew(name: str = "Bury Crew 1", crew_type: str = "BURY", **overrides) -> dict:
    payload = f.install_crew_payload(name=name, crew_type=crew_type, **overrides)
    return get_success_data(api_client.create_install_crew(payload, COORDINATOR))


def make_appointment(
    preorder_id: str,
    crew_id: str,
    window_start_at: str,
    window_end_at: str,
    appointment_type: str = "DROP_BURY",
    **overrides,
) -> dict:
    expected_version = overrides.pop("expected_crew_version", read_crew_version(crew_id))
    payload = f.install_appointment_payload(
        preorder_id,
        crew_id,
        window_start_at,
        window_end_at,
        expected_version,
        appointment_type=appointment_type,
        **overrides,
    )
    return get_success_data(api_client.create_install_appointment(payload, COORDINATOR))


def record_outcome(appointment_id: str, outcome: str, **extra) -> dict:
    return get_success_data(
        api_client.record_appointment_outcome(
            appointment_id, f.appointment_outcome_payload(outcome, **extra), COORDINATOR
        )
    )


def make_mdu_agreement(
    service_address_id: str,
    owner_account_id: str,
    target_status: str = "SIGNED",
    access_fee_cents: int = 250000,
    expires_at: str = "2026-12-01T00:00:00Z",
    **overrides,
) -> dict:
    """Open an owner agreement and walk it to `target_status`."""
    agreement = get_success_data(
        api_client.create_mdu_agreement(
            f.mdu_agreement_payload(
                service_address_id,
                owner_account_id,
                access_fee_cents=access_fee_cents,
                expires_at=expires_at,
                **overrides,
            ),
            PM,
        )
    )
    if target_status == "DRAFT":
        return agreement
    agreement = get_success_data(
        api_client.create_mdu_offer(
            agreement["id"], f.mdu_offer_payload(access_fee_cents), PM
        )
    )
    if target_status == "SENT":
        return agreement
    owner_headers = make_mdu_owner_headers(owner_account_id)
    if target_status == "COUNTERED":
        return get_success_data(
            api_client.mdu_owner_response(
                agreement["id"],
                f.owner_response_payload(
                    "COUNTER", countered_fee_cents=access_fee_cents - 50000
                ),
                owner_headers,
            )
        )
    response = "SIGN" if target_status == "SIGNED" else "DECLINE"
    return get_success_data(
        api_client.mdu_owner_response(
            agreement["id"], f.owner_response_payload(response), owner_headers
        )
    )


def make_fallback_option(campaign_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fallback_option(
            f.fallback_option_payload(campaign_id, **overrides), PM
        )
    )


def grant_unserved_exception(service_address_id: str, exception_reason=None) -> dict:
    """Walk an address's exception path NONE to REQUESTED to GRANTED."""
    payload = f.unserved_exception_payload("REQUEST")
    if exception_reason is not None:
        payload["exception_reason"] = exception_reason
    get_success_data(api_client.unserved_exception(service_address_id, payload, PM))
    return get_success_data(
        api_client.unserved_exception(
            service_address_id, f.unserved_exception_payload("GRANT"), PM
        )
    )


def make_offer(
    service_address_id: str,
    account_id: str,
    expires_at: str = "2026-12-01T00:00:00Z",
) -> dict:
    return get_success_data(
        api_client.create_fallback_offer(
            service_address_id, f.fallback_offer_payload(account_id, expires_at), PM
        )
    )


def list_ledger_for_preorder(preorder_id: str, headers=None):
    response = api_client.list_ledger_entries(headers or PM, {"preorder_id": preorder_id})
    return get_success_data(response), response


def list_ledger_for_account(account_id: str, headers=None):
    response = api_client.list_ledger_entries(headers or PM, {"account_id": account_id})
    return get_success_data(response), response


# --- Composite scenarios -----------------------------------------------------
def setup_campaign_with_zone(
    campaign_overrides: Optional[dict] = None,
    zone_overrides: Optional[dict] = None,
) -> Dict[str, dict]:
    """Clock at the epoch, one campaign, one zone inside its open window."""
    set_clock()
    campaign = make_campaign(**(campaign_overrides or {}))
    zone = make_zone(campaign["id"], **(zone_overrides or {}))
    return {"campaign": campaign, "zone": zone}


def setup_serviceable_address(
    campaign_overrides: Optional[dict] = None,
    zone_overrides: Optional[dict] = None,
    address_overrides: Optional[dict] = None,
    account_index: int = 0,
) -> Dict[str, dict]:
    """Campaign, zone, one SERVICEABLE address and one account."""
    base = setup_campaign_with_zone(campaign_overrides, zone_overrides)
    address = make_address(base["zone"]["id"], **(address_overrides or {}))
    address = set_serviceability(address["id"], "SERVICEABLE")
    account = make_account(account_index)
    base.update({"address": address, "account": account})
    return base


def setup_zone_with_preorders(
    preorder_count: int = 1,
    household_count: int = 10,
    threshold_pct: Optional[float] = None,
    campaign_overrides: Optional[dict] = None,
    zone_overrides: Optional[dict] = None,
    plan_tiers: Sequence[str] = ("BASIC_300",),
    serviceability: str = "SERVICEABLE",
) -> Dict[str, object]:
    """One open zone holding `preorder_count` PENDING preorders.

    Each preorder sits at its own address and belongs to its own account, so
    ownership-gated calls always have a distinct acting identity available.
    """
    zone_kwargs = dict(household_count=household_count)
    if threshold_pct is not None:
        zone_kwargs["threshold_pct"] = threshold_pct
    zone_kwargs.update(zone_overrides or {})
    base = setup_campaign_with_zone(campaign_overrides, zone_kwargs)
    zone_id = base["zone"]["id"]

    addresses: List[dict] = []
    accounts: List[dict] = []
    preorders: List[dict] = []
    for index in range(preorder_count):
        address = make_address(
            zone_id,
            street_address=STREET_ADDRESSES[index],
            distance_to_node_m=100 + 5 * index,
        )
        if serviceability != "UNDETERMINED":
            address = set_serviceability(address["id"], serviceability)
        account = make_account(index)
        tier = plan_tiers[index] if index < len(plan_tiers) else plan_tiers[-1]
        preorder = make_preorder(
            zone_id, address["id"], account["id"], plan_tier=tier
        )
        addresses.append(address)
        accounts.append(account)
        preorders.append(preorder)

    base.update(
        {
            "addresses": addresses,
            "accounts": accounts,
            "preorders": preorders,
            "zone": read_zone(zone_id),
        }
    )
    return base


def setup_construction_ready_zone(
    preorder_count: int = 1,
    household_count: int = 10,
    threshold_pct: float = 10.0,
    required_permit_types: Sequence[str] = ("ROW",),
    pole_quote_cents: int = 12000,
    permit_valid_days: int = 200,
    plan_tiers: Sequence[str] = ("BASIC_300",),
    campaign_overrides: Optional[dict] = None,
    zone_overrides: Optional[dict] = None,
    qualification_clock: str = CLOCK_AFTER_DEADLINE,
    start_construction: bool = True,
) -> Dict[str, object]:
    """A zone carried all the way to IN_CONSTRUCTION.

    Preorders are signed while the window is open, every required permit type is
    approved, one pole request reaches ATTACHED on `pole_quote_cents`, then the
    clock passes the deadline and the qualification run, the sequencing run and
    the ground-break are driven in that order.
    """
    zone_kwargs = dict(
        household_count=household_count,
        threshold_pct=threshold_pct,
        required_permit_types=list(required_permit_types),
    )
    zone_kwargs.update(zone_overrides or {})
    base = setup_zone_with_preorders(
        preorder_count=preorder_count,
        campaign_overrides=campaign_overrides,
        zone_overrides=zone_kwargs,
        plan_tiers=plan_tiers,
    )
    zone_id = base["zone"]["id"]

    permits = [
        make_permit(zone_id, permit_type=permit_type, valid_days=permit_valid_days)
        for permit_type in required_permit_types
    ]
    pole = make_pole_request(
        zone_id, target_status="ATTACHED", make_ready_cost_cents=pole_quote_cents
    )

    set_clock(qualification_clock)
    get_success_data(api_client.qualification_run(base["campaign"]["id"], PM))
    get_success_data(api_client.sequencing_run(base["campaign"]["id"], PM))
    if start_construction:
        get_success_data(api_client.start_construction(zone_id, PM))

    base.update(
        {
            "permits": permits,
            "pole": pole,
            "zone": read_zone(zone_id),
            "preorders": [read_preorder(p["id"]) for p in base["preorders"]],
        }
    )
    return base


def setup_converted_preorder(
    drop_method: str = "BURY",
    preorder_index: int = 0,
    **kwargs,
) -> Dict[str, object]:
    """A zone IN_CONSTRUCTION with one preorder already CONVERTED."""
    base = setup_construction_ready_zone(**kwargs)
    preorder = base["preorders"][preorder_index]
    account = base["accounts"][preorder_index]
    converted = get_success_data(
        api_client.convert_preorder(
            preorder["id"],
            f.conversion_payload(drop_method),
            make_subscriber_headers(account["id"]),
        )
    )
    preorders = list(base["preorders"])
    preorders[preorder_index] = converted
    base["preorders"] = preorders
    base["converted"] = converted
    base["zone"] = read_zone(base["zone"]["id"])
    return base


def setup_scheduled_bury_appointment(
    window_start_at: str = "2026-10-05T09:00:00Z",
    window_end_at: str = "2026-10-05T11:00:00Z",
    crew_overrides: Optional[dict] = None,
    **kwargs,
) -> Dict[str, object]:
    """A CONVERTED preorder with one SCHEDULED DROP_BURY appointment."""
    base = setup_converted_preorder(drop_method="BURY", **kwargs)
    crew = make_crew(
        name="Bury Crew 1", crew_type="BURY", **(crew_overrides or {})
    )
    appointment = make_appointment(
        base["converted"]["id"],
        crew["id"],
        window_start_at,
        window_end_at,
        appointment_type="DROP_BURY",
    )
    base.update(
        {
            "crew": read_crew(crew["id"]),
            "appointment": appointment,
            "zone": read_zone(base["zone"]["id"]),
        }
    )
    return base


def setup_completed_bury_appointment(
    completion_clock: str = "2026-10-05T11:00:00Z",
    restoration_required: bool = True,
    **kwargs,
) -> Dict[str, object]:
    """A DROP_BURY appointment COMPLETED at `completion_clock`.

    With `restoration_required` true the parent appointment carries a
    `restoration_due_by` and the zone's outstanding restoration count rises.
    """
    base = setup_scheduled_bury_appointment(**kwargs)
    set_clock(completion_clock)
    completed = record_outcome(
        base["appointment"]["id"],
        "COMPLETED",
        restoration_required=restoration_required,
    )
    base.update(
        {
            "appointment": completed,
            "crew": read_crew(base["crew"]["id"]),
            "zone": read_zone(base["zone"]["id"]),
        }
    )
    return base


def setup_filed_damage_claim(
    filing_clock: str = "2026-10-06T09:00:00Z",
    damage_type: str = "LAWN",
    claimed_amount_cents: int = 150000,
    claim_overrides: Optional[dict] = None,
    **kwargs,
) -> Dict[str, object]:
    """A FILED damage claim against a completed, restoration-owing appointment."""
    base = setup_completed_bury_appointment(**kwargs)
    set_clock(filing_clock)
    account = base["accounts"][0]
    payload = f.damage_claim_payload(
        base["appointment"]["id"],
        base["addresses"][0]["id"],
        account["id"],
        damage_type=damage_type,
        claimed_amount_cents=claimed_amount_cents,
    )
    payload.update(claim_overrides or {})
    claim = get_success_data(
        api_client.create_damage_claim(payload, make_subscriber_headers(account["id"]))
    )
    base["claim"] = claim
    return base


def setup_assessed_damage_claim(
    assessor_headers=None, **kwargs
) -> Dict[str, object]:
    """A damage claim priced by the assessor and standing in UNDER_ASSESSMENT."""
    base = setup_filed_damage_claim(**kwargs)
    assessed = get_success_data(
        api_client.assess_damage_claim(base["claim"]["id"], assessor_headers or ASSESSOR)
    )
    base["claim"] = assessed
    return base


def setup_not_serviceable_address_with_options(
    option_specs: Sequence[dict] = (),
    address_overrides: Optional[dict] = None,
    not_serviceable_reason: str = "NO_ROW_ACCESS",
    grant_exception: bool = True,
    campaign_overrides: Optional[dict] = None,
    zone_overrides: Optional[dict] = None,
) -> Dict[str, object]:
    """A NOT_SERVICEABLE address with a GRANTED exception and a pool of options."""
    base = setup_campaign_with_zone(campaign_overrides, zone_overrides)
    address = make_address(base["zone"]["id"], **(address_overrides or {}))
    address = set_serviceability(
        address["id"],
        "NOT_SERVICEABLE",
        not_serviceable_reason=not_serviceable_reason,
    )
    options = [make_fallback_option(base["campaign"]["id"], **spec) for spec in option_specs]
    if grant_exception:
        address = grant_unserved_exception(address["id"])
    base.update({"address": address, "options": options, "account": make_account(2)})
    return base


def setup_mdu_address_with_agreement(
    agreement_status: str = "SIGNED",
    access_fee_cents: int = 250000,
    expires_at: str = "2026-12-01T00:00:00Z",
    unit_count: int = 24,
    max_counter_rounds: Optional[int] = None,
    campaign_overrides: Optional[dict] = None,
    zone_overrides: Optional[dict] = None,
) -> Dict[str, object]:
    """An MDU address, its owner account and one agreement in the given status."""
    base = setup_campaign_with_zone(campaign_overrides, zone_overrides)
    address = make_mdu_address(base["zone"]["id"], unit_count=unit_count)
    owner = make_owner_account()
    extra = {}
    if max_counter_rounds is not None:
        extra["max_counter_rounds"] = max_counter_rounds
    agreement = make_mdu_agreement(
        address["id"],
        owner["id"],
        target_status=agreement_status,
        access_fee_cents=access_fee_cents,
        expires_at=expires_at,
        **extra,
    )
    base.update(
        {"address": read_address(address["id"]), "owner": owner, "agreement": agreement}
    )
    return base
