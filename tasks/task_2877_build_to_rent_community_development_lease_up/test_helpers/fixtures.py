"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints only —
the harness restarts the API server against an empty database before every test.

Setup calls go through get_success_data() (the lenient validator) so that a broken
precondition surfaces as a setup failure rather than as a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    absorption_review_payload,
    cancellation_payload,
    clock_payload,
    concession_credit_payload,
    concession_decision_payload,
    concession_request_payload,
    create_amenity_phase_payload,
    create_community_payload,
    create_concession_program_payload,
    create_homesite_payload,
    create_household_payload,
    create_lease_payload,
    create_phase_payload,
    create_turn_work_order_payload,
    halt_payload,
    notice_payload,
    occupancy_certificate_payload,
    plat_decision_payload,
    plat_submission_payload,
    pm_transition_payload,
    publish_schedule_payload,
    section_release_payload,
    signature_payload,
    unique_suffix,
)
from .test_users import (
    TEST_USERS,
    make_household_headers,
)

DEVELOPER = TEST_USERS["developer_principal_headers"]
ENTITLEMENT = TEST_USERS["entitlement_officer_headers"]
CONSTRUCTION = TEST_USERS["construction_manager_headers"]
LEASING = TEST_USERS["leasing_agent_headers"]
ASSET = TEST_USERS["asset_manager_headers"]
PROPERTY = TEST_USERS["property_manager_headers"]


def _data(response) -> dict:
    return get_success_data(response)


# --- Single-step wrappers ---------------------------------------------------


def set_clock(current_utc: str, headers=None) -> dict:
    """POST /_clock/set_current_utc — any role may drive the logical clock."""
    return _data(api_client.set_clock(clock_payload(current_utc), headers or ASSET))


def read_community(community_id: str, headers=None) -> dict:
    return _data(api_client.get_community(community_id, headers or ASSET))


def community_version(community_id: str) -> int:
    """The value a client sends as expected_community_version (PRD §2.7)."""
    return read_community(community_id)["version"]


def read_phase(phase_id: str, headers=None) -> dict:
    return _data(api_client.get_phase(phase_id, headers or CONSTRUCTION))


def read_homesite(homesite_id: str, headers=None) -> dict:
    return _data(api_client.get_homesite(homesite_id, headers or CONSTRUCTION))


def read_lease(lease_id: str, headers=None) -> dict:
    return _data(api_client.get_lease(lease_id, headers or LEASING))


def read_household(household_id: str, headers=None) -> dict:
    return _data(api_client.get_household(household_id, headers or LEASING))


def read_schedule(schedule_id: str, headers=None) -> dict:
    return _data(api_client.get_market_rent_schedule(schedule_id, headers or ASSET))


def read_program(program_id: str, headers=None) -> dict:
    return _data(api_client.get_concession_program(program_id, headers or ASSET))


def read_turn_work_order(order_id: str, headers=None) -> dict:
    return _data(api_client.get_turn_work_order(order_id, headers or PROPERTY))


def read_valuation(community_id: str, basis: str, headers=None) -> dict:
    return _data(
        api_client.get_community_valuation(community_id, headers or ASSET, {"basis": basis})
    )


def create_community(**overrides) -> dict:
    """POST /communities as the DeveloperPrincipal."""
    return _data(api_client.create_community(create_community_payload(**overrides), DEVELOPER))


def submit_plat(community_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.submit_plat(community_id, plat_submission_payload(**overrides), headers or DEVELOPER)
    )


def decide_plat(community_id: str, decision="APPROVE", headers=None, **overrides) -> dict:
    """The deciding EntitlementOfficer's X-User-ID differs from plat_submitted_by_user_id."""
    return _data(
        api_client.decide_plat(
            community_id, plat_decision_payload(decision, **overrides), headers or ENTITLEMENT
        )
    )


def create_plat_approved_community(**overrides) -> dict:
    """Community whose plat_status is APPROVED — the point at which posture first leaves FROZEN."""
    community = create_community(**overrides)
    submit_plat(community["id"])
    decide_plat(community["id"], "APPROVE")
    return read_community(community["id"])


def publish_schedule(community_id: str, headers=None, **overrides) -> dict:
    """POST /market-rent-schedules, always carrying the community's current version."""
    payload = publish_schedule_payload(community_id, community_version(community_id), **overrides)
    return _data(api_client.publish_market_rent_schedule(payload, headers or ASSET))


def create_concession_program(community_id: str, headers=None, **overrides) -> dict:
    """POST /concession-programs, always carrying the community's current version."""
    payload = create_concession_program_payload(
        community_id, community_version(community_id), **overrides
    )
    return _data(api_client.create_concession_program(payload, headers or ASSET))


def create_phase(community_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.create_phase(create_phase_payload(community_id, **overrides), headers or DEVELOPER)
    )


def create_amenity_phase(community_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.create_phase(
            create_amenity_phase_payload(community_id, **overrides), headers or DEVELOPER
        )
    )


def start_construction(phase_id: str, headers=None) -> dict:
    return _data(api_client.start_construction(phase_id, {}, headers or CONSTRUCTION))


def create_homesite(phase_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.create_homesite(
            create_homesite_payload(phase_id, **overrides), headers or CONSTRUCTION
        )
    )


def record_occupancy_certificate(homesite_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.record_occupancy_certificate(
            homesite_id, occupancy_certificate_payload(**overrides), headers or CONSTRUCTION
        )
    )


def release_section(phase_id: str, homesite_ids, headers=None) -> dict:
    return _data(
        api_client.release_section(
            phase_id, section_release_payload(homesite_ids), headers or CONSTRUCTION
        )
    )


def complete_phase(phase_id: str, headers=None) -> dict:
    return _data(api_client.complete_phase(phase_id, {}, headers or CONSTRUCTION))


def halt_phase(phase_id: str, headers=None, **overrides) -> dict:
    return _data(api_client.halt_phase(phase_id, halt_payload(**overrides), headers or CONSTRUCTION))


def resume_phase(phase_id: str, headers=None) -> dict:
    return _data(api_client.resume_phase(phase_id, {}, headers or CONSTRUCTION))


def create_household(**overrides) -> dict:
    return _data(api_client.create_household(create_household_payload(**overrides), LEASING))


def draft_lease(homesite_id: str, household_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.create_lease(
            create_lease_payload(homesite_id, household_id, **overrides), headers or LEASING
        )
    )


def request_concession(lease_id: str, program_id: str, headers=None) -> dict:
    return _data(
        api_client.request_concession(
            lease_id, concession_request_payload(program_id), headers or LEASING
        )
    )


def decide_concession(lease_id: str, decision="APPROVE", headers=None, **overrides) -> dict:
    """The deciding AssetManager's X-User-ID differs from concession_requested_by_user_id."""
    return _data(
        api_client.decide_concession(
            lease_id, concession_decision_payload(decision, **overrides), headers or ASSET
        )
    )


def submit_lease(lease_id: str, headers=None) -> dict:
    return _data(api_client.submit_lease(lease_id, {}, headers or LEASING))


def sign_lease(lease_id: str, household_id: str, signed_by_name="Ada Vance") -> dict:
    """Signature is ownership-gated: X-User-ID must equal the lease's household_id."""
    return _data(
        api_client.sign_lease(
            lease_id,
            signature_payload(signed_by_name),
            make_household_headers(household_id),
        )
    )


def activate_lease(lease_id: str, headers=None) -> dict:
    return _data(api_client.activate_lease(lease_id, {}, headers or PROPERTY))


def apply_concession_credit(lease_id: str, period_index: int, headers=None) -> dict:
    return _data(
        api_client.apply_concession_credit(
            lease_id, concession_credit_payload(period_index), headers or PROPERTY
        )
    )


def give_notice(lease_id: str, household_id: str, **overrides) -> dict:
    """Notice is ownership-gated: X-User-ID must equal the lease's household_id."""
    return _data(
        api_client.give_notice(
            lease_id, notice_payload(**overrides), make_household_headers(household_id)
        )
    )


def cancel_lease(lease_id: str, cancellation_reason="OPERATOR_CANCELLED", headers=None) -> dict:
    return _data(
        api_client.cancel_lease(
            lease_id, cancellation_payload(cancellation_reason), headers or ASSET
        )
    )


def create_turn_work_order(homesite_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.create_turn_work_order(
            create_turn_work_order_payload(homesite_id, **overrides), headers or PROPERTY
        )
    )


def complete_turn_work_order(order_id: str, headers=None) -> dict:
    return _data(api_client.complete_turn_work_order(order_id, {}, headers or PROPERTY))


def create_absorption_review(community_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.create_absorption_review(
            community_id, absorption_review_payload(**overrides), headers or ASSET
        )
    )


def create_pm_transition(community_id: str, headers=None, **overrides) -> dict:
    return _data(
        api_client.create_pm_transition(
            community_id, pm_transition_payload(**overrides), headers or DEVELOPER
        )
    )


# --- Composite scenarios ----------------------------------------------------

_HOMESITE_SHAPES = {
    "DETACHED": {"bedrooms": 4, "square_feet": 2200},
    "COTTAGE": {"bedrooms": 2, "square_feet": 1200},
    "TOWNHOME": {"bedrooms": 3, "square_feet": 1600},
}


def _mix_for(product_type: str, total: int) -> dict:
    mix = {"DETACHED": 0, "COTTAGE": 0, "TOWNHOME": 0}
    mix[product_type] = total
    return mix


def setup_released_community(
    homesite_count: int = 1,
    product_type: str = "DETACHED",
    asking_rent_cents: int = 285_000,
    total_planned_units=None,
    product_mix=None,
    asking_rents=None,
    homesite_specs=None,
    release: bool = True,
    schedule_effective_from: str = "2026-08-01T00:00:00Z",
    phase_overrides=None,
    **community_overrides,
) -> dict:
    """Plat-approved community with one HOUSING phase whose homesites are certificated and
    released to leasing.

    Chain: POST /communities -> plat-submissions -> plat-decisions(APPROVE) ->
    market-rent-schedules (one PUBLISHED schedule per product type) -> phases ->
    construction-start -> homesites -> occupancy-certificates -> section-releases.

    Returns {"community", "phase", "homesites", "schedules"} where "community" is re-read
    after the release so that its counters and posture are current.
    """
    specs = homesite_specs
    if specs is None:
        specs = [{"product_type": product_type} for _ in range(homesite_count)]
    specs = [dict(spec) for spec in specs]
    for index, spec in enumerate(specs, start=1):
        spec.setdefault("product_type", product_type)
        spec.setdefault("lot_number", f"L{unique_suffix()}")
        for key, value in _HOMESITE_SHAPES[spec["product_type"]].items():
            spec.setdefault(key, value)

    planned = total_planned_units if total_planned_units is not None else max(len(specs), 1)
    mix = product_mix if product_mix is not None else _mix_for(product_type, planned)

    rents = dict(asking_rents or {})
    for spec in specs:
        rents.setdefault(spec["product_type"], asking_rent_cents)
    if not rents:
        rents[product_type] = asking_rent_cents

    community = create_plat_approved_community(
        total_planned_units=planned, product_mix=mix, **community_overrides
    )

    schedules = {}
    for schedule_product_type, rent in rents.items():
        schedules[schedule_product_type] = publish_schedule(
            community["id"],
            product_type=schedule_product_type,
            asking_rent_cents=rent,
            effective_from=schedule_effective_from,
        )

    phase_payload = {"planned_unit_count": max(len(specs), 1)}
    phase_payload.update(phase_overrides or {})
    phase = create_phase(community["id"], **phase_payload)
    start_construction(phase["id"])

    homesites = []
    for spec in specs:
        homesite = create_homesite(phase["id"], **spec)
        record_occupancy_certificate(homesite["id"])
        homesites.append(homesite)

    if release and homesites:
        release_section(phase["id"], [h["id"] for h in homesites])
        homesites = [read_homesite(h["id"]) for h in homesites]

    return {
        "community": read_community(community["id"]),
        "phase": read_phase(phase["id"]),
        "homesites": homesites,
        "schedules": schedules,
    }


def setup_draft_lease(
    household_overrides=None,
    lease_overrides=None,
    **scenario_overrides,
) -> dict:
    """Released community + registered household + one DRAFT lease on the first homesite."""
    scenario = setup_released_community(**scenario_overrides)
    household = create_household(**(household_overrides or {}))
    lease = draft_lease(
        scenario["homesites"][0]["id"], household["id"], **(lease_overrides or {})
    )
    scenario.update({"household": household, "lease": lease})
    return scenario


def setup_lease_with_approved_concession(
    program_overrides=None,
    household_overrides=None,
    lease_overrides=None,
    **scenario_overrides,
) -> dict:
    """DRAFT lease carrying an APPROVED concession, with the ACTIVE program that priced it."""
    scenario = setup_draft_lease(
        household_overrides=household_overrides,
        lease_overrides=lease_overrides,
        **scenario_overrides,
    )
    program = create_concession_program(
        scenario["community"]["id"], **(program_overrides or {})
    )
    request_concession(scenario["lease"]["id"], program["id"])
    decide_concession(scenario["lease"]["id"], "APPROVE")
    scenario["program"] = read_program(program["id"])
    scenario["lease"] = read_lease(scenario["lease"]["id"])
    scenario["community"] = read_community(scenario["community"]["id"])
    return scenario


def setup_executed_lease(
    with_concession: bool = False,
    program_overrides=None,
    household_overrides=None,
    lease_overrides=None,
    **scenario_overrides,
) -> dict:
    """Lease walked DRAFT -> PENDING_SIGNATURE -> EXECUTED by its own household."""
    if with_concession:
        scenario = setup_lease_with_approved_concession(
            program_overrides=program_overrides,
            household_overrides=household_overrides,
            lease_overrides=lease_overrides,
            **scenario_overrides,
        )
    else:
        scenario = setup_draft_lease(
            household_overrides=household_overrides,
            lease_overrides=lease_overrides,
            **scenario_overrides,
        )
    submit_lease(scenario["lease"]["id"])
    sign_lease(
        scenario["lease"]["id"],
        scenario["household"]["id"],
        scenario["household"]["primary_applicant_name"],
    )
    scenario["lease"] = read_lease(scenario["lease"]["id"])
    scenario["community"] = read_community(scenario["community"]["id"])
    scenario["homesites"] = [read_homesite(h["id"]) for h in scenario["homesites"]]
    return scenario


def setup_active_lease(**kwargs) -> dict:
    """Lease walked through to ACTIVE; an attached concession becomes AMORTIZING."""
    scenario = setup_executed_lease(**kwargs)
    activate_lease(scenario["lease"]["id"])
    scenario["lease"] = read_lease(scenario["lease"]["id"])
    scenario["community"] = read_community(scenario["community"]["id"])
    if scenario.get("program"):
        scenario["program"] = read_program(scenario["program"]["id"])
    return scenario


def setup_amortizing_lease(program_overrides=None, **kwargs) -> dict:
    """ACTIVE lease whose concession_status is AMORTIZING, ready for credit postings."""
    return setup_active_lease(
        with_concession=True, program_overrides=program_overrides, **kwargs
    )


def setup_homesite_on_notice(**kwargs) -> dict:
    """ACTIVE lease taken to ENDING by a resident notice, leaving the home NOTICE_GIVEN."""
    scenario = setup_active_lease(**kwargs)
    give_notice(scenario["lease"]["id"], scenario["household"]["id"])
    scenario["lease"] = read_lease(scenario["lease"]["id"])
    scenario["homesites"] = [read_homesite(h["id"]) for h in scenario["homesites"]]
    scenario["community"] = read_community(scenario["community"]["id"])
    return scenario


def setup_restricted_community(amenity_weight: int = 10, **scenario_overrides) -> dict:
    """Released community that is then given an undelivered AMENITY phase, so
    released_unit_count >= 1 while amenity_delivery_ratio is 0.0000 and the posture is
    RESTRICTED. The amenity phase is created after the release because a release itself
    requires an OPEN posture.
    """
    scenario = setup_released_community(**scenario_overrides)
    amenity_phase = create_amenity_phase(
        scenario["community"]["id"], sequence_index=90, amenity_weight=amenity_weight
    )
    scenario["amenity_phase"] = amenity_phase
    scenario["community"] = read_community(scenario["community"]["id"])
    return scenario


def setup_frozen_community(**scenario_overrides) -> dict:
    """Released community whose HOUSING phase is then halted, freezing the posture."""
    scenario = setup_released_community(**scenario_overrides)
    halt_phase(scenario["phase"]["id"])
    scenario["phase"] = read_phase(scenario["phase"]["id"])
    scenario["community"] = read_community(scenario["community"]["id"])
    scenario["homesites"] = [read_homesite(h["id"]) for h in scenario["homesites"]]
    return scenario


def setup_stabilized_community(
    total_planned_units: int = 4,
    leased_count: int = 3,
    activate: bool = True,
    asking_rent_cents: int = 285_000,
    **community_overrides,
) -> dict:
    """Community whose occupancy_ratio has reached the 0.7500 stabilization threshold, so
    lifecycle_status is STABILIZED and facility_status is CONVERSION_PENDING.

    Returns the scenario dict plus "households" and "leases" lists in creation order.
    """
    scenario = setup_released_community(
        homesite_count=leased_count,
        total_planned_units=total_planned_units,
        product_mix=_mix_for("DETACHED", total_planned_units),
        asking_rent_cents=asking_rent_cents,
        **community_overrides,
    )
    households, leases = [], []
    for homesite in scenario["homesites"]:
        household = create_household()
        lease = draft_lease(homesite["id"], household["id"])
        submit_lease(lease["id"])
        sign_lease(lease["id"], household["id"], household["primary_applicant_name"])
        if activate:
            activate_lease(lease["id"])
        households.append(household)
        leases.append(read_lease(lease["id"]))
    scenario["households"] = households
    scenario["leases"] = leases
    scenario["community"] = read_community(scenario["community"]["id"])
    scenario["homesites"] = [read_homesite(h["id"]) for h in scenario["homesites"]]
    return scenario


def setup_pm_managed_stabilized_community(**kwargs) -> dict:
    """Stabilized community handed to a property manager with an effective_from at or
    before the clock, so management_mode is PM_MANAGED in the same request."""
    scenario = setup_stabilized_community(**kwargs)
    create_pm_transition(scenario["community"]["id"], effective_from="2026-08-01T00:00:00Z")
    scenario["community"] = read_community(scenario["community"]["id"])
    return scenario


def setup_absorption_review_scenario(
    executed_leases: int = 2,
    homesite_count: int = 5,
    total_planned_units: int = 8,
    product_type: str = "DETACHED",
    asking_rent_cents: int = 900_000,
    clock: str = "2026-08-08T00:00:00Z",
    household_income_cents: int = 3_500_000,
    **community_overrides,
) -> dict:
    """Released community with `executed_leases` EXECUTED leases and the clock advanced past
    the review window, so an absorption review over [2026-08-01, 2026-08-08) can be recorded.
    """
    scenario = setup_released_community(
        homesite_count=homesite_count,
        product_type=product_type,
        total_planned_units=total_planned_units,
        product_mix=_mix_for(product_type, total_planned_units),
        asking_rent_cents=asking_rent_cents,
        **community_overrides,
    )
    households, leases = [], []
    for homesite in scenario["homesites"][:executed_leases]:
        household = create_household(monthly_income_cents=household_income_cents)
        lease = draft_lease(homesite["id"], household["id"])
        submit_lease(lease["id"])
        sign_lease(lease["id"], household["id"], household["primary_applicant_name"])
        households.append(household)
        leases.append(read_lease(lease["id"]))
    if clock:
        set_clock(clock)
    scenario["households"] = households
    scenario["leases"] = leases
    scenario["community"] = read_community(scenario["community"]["id"])
    scenario["homesites"] = [read_homesite(h["id"]) for h in scenario["homesites"]]
    return scenario
