"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because the server is restarted before each individual test and therefore starts
against an empty database. Setup calls go through `get_success_data()` so a broken
precondition raises a clear "Setup failed" error instead of a confusing assertion
failure deep inside a test.

Identity threading: after a fixture creates an entity-backed resource it uses
`make_care_advocate_headers(advocate["id"])` / `make_clinic_coordinator_headers(
clinic["id"])` / `make_member_headers(member["id"])` for every ownership-gated call,
never the shared fallback constants.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (  # noqa: F401  (re-exported for fixture consumers)
    CRITERIA_SCORE_0,
    CRITERIA_BELOW_FLOOR,
    CRITERIA_SCORE_70,
    DEFAULT_CLOCK,
    NEUTRAL_CRITERIA,
    TEST_DEFAULTS,
)
from .factories import (
    create_bundle_entitlement_payload,
    create_care_advocate_payload,
    create_clinic_contract_payload,
    create_clinic_outcome_payload,
    create_clinic_payload,
    create_claim_payload,
    create_cycle_outcome_payload,
    create_employer_account_payload,
    create_medication_order_payload,
    create_member_payload,
    create_pathway_request_payload,
    create_preauthorization_payload,
    create_surrender_route_payload,
    create_treatment_cycle_payload,
    create_treatment_plan_payload,
)
from .test_users import (
    TEST_USERS,
    make_care_advocate_headers,
    make_claims_processor_headers,
    make_claims_reviewer_headers,
    make_clinic_coordinator_headers,
    make_clinical_reviewer_headers,
    make_member_headers,
    make_network_manager_headers,
)

ADMIN = TEST_USERS["plan_administrator_headers"]
NETWORK = TEST_USERS["network_manager_headers"]
# The CareAdvocate capacity is entity-backed, but enroling a member is not
# ownership-gated, so the shared constant is the canonical form for that call.
CARE_ADVOCATE_FALLBACK = TEST_USERS["care_advocate_headers"]
PHARMACIST = TEST_USERS["specialty_pharmacist_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]
CLAIMS_REVIEW = TEST_USERS["claims_reviewer_headers"]

# Operator identities used for administrative calls that are not ownership-gated.
REVIEWER_ID = "rev-1"
REVIEWER_2_ID = "rev-2"
CLAIMS_OPERATOR_ID = "clm-processor-1"
CLAIMS_REVIEWER_ID = "clm-reviewer-1"

_npi_counter = itertools.count(1)


def fresh_npi() -> str:
    """A ten-digit provider identifier unique within the running test process."""
    return f"3{next(_npi_counter):09d}"


# ─── Tier 1: clock and single-entity state progression ─────────────────────────

def setup_clock(current_utc: str = DEFAULT_CLOCK) -> dict:
    """Adopt a logical instant. The service never reads wall-clock time."""
    return get_success_data(api_client.set_current_utc({"current_utc": current_utc}, ADMIN))


def tick_clock():
    """Advance the logical clock to the earliest pending deadline and fire it."""
    return get_success_data(api_client.tick(ADMIN))


def create_employer(allocation_method: str = "CONCURRENT_BUNDLE", **overrides) -> dict:
    payload = create_employer_account_payload(allocation_method=allocation_method, **overrides)
    return get_success_data(api_client.create_employer_account(payload, ADMIN))


def create_bundle(employer_account_id: str, activate: bool = True, **overrides) -> dict:
    payload = create_bundle_entitlement_payload(employer_account_id, **overrides)
    bundle = get_success_data(api_client.create_bundle_entitlement(payload, ADMIN))
    if activate:
        bundle = get_success_data(api_client.activate_bundle_entitlement(bundle["id"], ADMIN))
    return bundle


def create_advocate(**overrides) -> dict:
    return get_success_data(api_client.create_care_advocate(create_care_advocate_payload(**overrides), ADMIN))


def create_clinic(**overrides) -> dict:
    payload = create_clinic_payload(npi=overrides.pop("npi", None) or fresh_npi(), **overrides)
    return get_success_data(api_client.create_clinic(payload, NETWORK))


def create_contract(clinic: dict, activate: bool = True, **overrides) -> dict:
    payload = create_clinic_contract_payload(**overrides)
    contract = get_success_data(api_client.create_clinic_contract(clinic["id"], payload, NETWORK))
    if activate:
        current = get_success_data(api_client.get_clinic(clinic["id"], NETWORK))
        contract = get_success_data(api_client.activate_clinic_contract(
            contract["id"], {"expected_clinic_version": current["version"]}, NETWORK))
    return contract


def create_member(employer_account_id: str, assign_advocate: bool = True,
                  complete_intake: bool = True, advocate: dict = None, **overrides) -> dict:
    # `member_overrides` is the documented kwarg; a bare kwarg (`external_ref=...`)
    # is merged too so both call styles reach the member payload.
    member_overrides = dict(overrides.pop("member_overrides", None) or {})
    payload = create_member_payload(employer_account_id, **member_overrides)
    payload.update(overrides)
    member = get_success_data(api_client.create_member(payload, TEST_USERS["care_advocate_headers"]))
    if assign_advocate:
        get_success_data(api_client.assign_advocate(
            member["id"], NETWORK, {"allocation_strategy": "ROUND_ROBIN"}))
        member = get_success_data(api_client.get_member(member["id"], NETWORK))
    if complete_intake:
        if advocate is None:
            raise ValueError("complete_intake=True requires the assigned advocate record")
        get_success_data(api_client.complete_intake(member["id"], make_care_advocate_headers(advocate["id"])))
        member = get_success_data(api_client.get_member(member["id"], NETWORK))
    return member


def create_plan(member: dict, bundle: dict, advocate: dict, **overrides) -> dict:
    payload = create_treatment_plan_payload(member["id"], bundle["id"], **overrides)
    return get_success_data(api_client.create_treatment_plan(
        payload, make_care_advocate_headers(advocate["id"])))


def select_clinic_for_plan(plan: dict, clinic: dict, advocate: dict) -> dict:
    """Commit a plan to a clinic. Carries the member's freshly observed version."""
    member = get_success_data(api_client.get_member(plan["member_id"], NETWORK))
    return get_success_data(api_client.select_plan_clinic(
        plan["id"], {"clinic_id": clinic["id"], "expected_member_version": member["version"]},
        make_care_advocate_headers(advocate["id"])))


def create_preauthorization(plan: dict, advocate: dict, cycle_sequence_index: int = 1,
                            **overrides) -> dict:
    payload = create_preauthorization_payload(cycle_sequence_index=cycle_sequence_index, **overrides)
    return get_success_data(api_client.create_preauthorization(
        plan["id"], payload, make_care_advocate_headers(advocate["id"])))


def approve_preauthorization(preauth: dict, plan: dict, reviewer_id: str = REVIEWER_ID) -> dict:
    """Begin clinical review then render an approving decision on the current plan version."""
    headers = make_clinical_reviewer_headers(reviewer_id)
    get_success_data(api_client.begin_clinical_review(preauth["id"], headers))
    current_plan = get_success_data(api_client.get_treatment_plan(plan["id"], NETWORK))
    return get_success_data(api_client.decide_preauthorization(
        preauth["id"], {"decision": "APPROVE",
                        "expected_treatment_plan_version": current_plan["version"]}, headers))


def create_cycle(plan: dict, preauth: dict, clinic: dict, **overrides) -> dict:
    payload = create_treatment_cycle_payload(preauth["id"], **overrides)
    return get_success_data(api_client.create_treatment_cycle(
        plan["id"], payload, make_clinic_coordinator_headers(clinic["id"])))


def drive_cycle_to_transfer(cycle: dict, clinic: dict, transfer_date: str = "2026-09-10T00:00:00Z",
                            embryos_transferred: int = 1) -> dict:
    """SCHEDULED → STIMULATION → RETRIEVAL → FERTILIZATION → TRANSFER."""
    headers = make_clinic_coordinator_headers(clinic["id"])
    get_success_data(api_client.start_stimulation(cycle["id"], headers))
    get_success_data(api_client.record_retrieval(cycle["id"], headers))
    get_success_data(api_client.record_fertilization(cycle["id"], headers))
    return get_success_data(api_client.record_transfer(
        cycle["id"], {"transfer_date": transfer_date, "embryos_transferred": embryos_transferred},
        headers))


def drive_cycle_to_outcome_recorded(cycle: dict, clinic: dict, at_clock: str = "2026-09-26T00:00:00Z",
                                    transfer_date: str = "2026-09-10T00:00:00Z",
                                    outcome: dict = None) -> dict:
    """Drive a cycle all the way to OUTCOME_RECORDED, consuming its bundle slot."""
    drive_cycle_to_transfer(cycle, clinic, transfer_date=transfer_date)
    setup_clock(at_clock)
    get_success_data(api_client.tick(ADMIN))
    headers = make_clinic_coordinator_headers(clinic["id"])
    recorded = get_success_data(api_client.record_cycle_outcome(
        cycle["id"], outcome or create_cycle_outcome_payload(), headers))
    return recorded


def report_clinic_outcome(clinic: dict, cycle: dict, **overrides) -> dict:
    """Report a clinic-side outcome record for a cycle already at OUTCOME_RECORDED."""
    current = get_success_data(api_client.get_treatment_cycle(cycle["id"], NETWORK))
    payload = create_clinic_outcome_payload(
        cycle["id"], current["version"], **overrides)
    return get_success_data(api_client.report_outcome(
        clinic["id"], payload, make_clinic_coordinator_headers(clinic["id"])))


# ─── Tier 2: entity hierarchy ──────────────────────────────────────────────────

def setup_employer_bundle(allocation_method: str = "CONCURRENT_BUNDLE",
                          bundle_overrides: dict = None,
                          employer_overrides: dict = None) -> tuple:
    """Activated employer account plus one activated bundle. Returns (employer, bundle)."""
    setup_clock()
    employer = create_employer(allocation_method=allocation_method, **(employer_overrides or {}))
    bundle = create_bundle(employer["id"], **(bundle_overrides or {}))
    return employer, bundle


def setup_advocate_and_member(employer: dict, advocate_overrides: dict = None,
                              member_overrides: dict = None,
                              complete_intake: bool = True) -> tuple:
    """Registered advocate plus an enrolled member assigned and taken CARE_ACTIVE."""
    advocate = create_advocate(**(advocate_overrides or {}))
    member = create_member(employer["id"], advocate=advocate,
                           complete_intake=complete_intake, **(member_overrides or {}))
    return advocate, member


def setup_contracted_clinic(rate: int = TEST_DEFAULTS["BUNDLE_RATE_IVF"],
                            clinic_overrides: dict = None,
                            contract_overrides: dict = None,
                            activate: bool = True) -> tuple:
    """Clinic in CONTRACTED posture on an ACTIVE contract. Returns (clinic, contract)."""
    clinic = create_clinic(**(clinic_overrides or {}))
    contract = create_contract(
        clinic,
        bundle_rates={"IVF_RETRIEVAL_TRANSFER": rate},
        activate=activate,
        **(contract_overrides or {}),
    )
    return clinic, contract


def setup_member_with_plan(employer: dict, bundle: dict, advocate: dict = None,
                           member_overrides: dict = None,
                           plan_overrides: dict = None,
                           advocate_overrides: dict = None) -> tuple:
    """CARE_ACTIVE member plus a treatment plan against the bundle."""
    if advocate is None:
        advocate = create_advocate(**(advocate_overrides or {}))
    member = create_member(employer["id"], advocate=advocate, **(member_overrides or {}))
    plan = create_plan(member, bundle, advocate, **(plan_overrides or {}))
    return advocate, member, plan


def setup_member_plan_clinic(allocation_method: str = "CONCURRENT_BUNDLE",
                             rate: int = TEST_DEFAULTS["BUNDLE_RATE_IVF"],
                             bundle_overrides: dict = None,
                             plan_overrides: dict = None,
                             clinic_overrides: dict = None,
                             select_clinic: bool = True) -> dict:
    """The common opening scenario: employer, bundle, advocate, CARE_ACTIVE member,
    CONTRACTED clinic with an ACTIVE contract, and a plan committed to that clinic.

    Returns a dict of every created row.
    """
    employer, bundle = setup_employer_bundle(
        allocation_method=allocation_method, bundle_overrides=bundle_overrides)
    advocate, member, plan = setup_member_with_plan(
        employer, bundle, plan_overrides=plan_overrides)
    clinic, contract = setup_contracted_clinic(rate=rate, clinic_overrides=clinic_overrides)
    if select_clinic:
        plan = select_clinic_for_plan(plan, clinic, advocate)
    return {
        "employer": employer,
        "bundle": bundle,
        "advocate": advocate,
        "member": member,
        "plan": plan,
        "clinic": clinic,
        "contract": contract,
    }


def setup_approved_authorization(sequence_index: int = 1, reviewer_id: str = REVIEWER_ID,
                                 preauth_overrides: dict = None,
                                 **scenario_overrides) -> dict:
    """The opening scenario plus one APPROVED authorization on its plan."""
    scenario = setup_member_plan_clinic(**scenario_overrides)
    preauth = create_preauthorization(scenario["plan"], scenario["advocate"],
                                      cycle_sequence_index=sequence_index,
                                      **(preauth_overrides or {}))
    preauth = approve_preauthorization(preauth, scenario["plan"], reviewer_id=reviewer_id)
    scenario["preauthorization"] = preauth
    scenario["plan"] = get_success_data(
        api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK))
    # The bundle-entitlement read is not open to NetworkManager (PRD section 4);
    # SpecialtyPharmacist is permitted and returns the same row.
    scenario["bundle"] = get_success_data(
        api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST))
    return scenario


def setup_cycle_under_authorization(sequence_index: int = 1, **scenario_overrides) -> dict:
    """An approved authorization plus one scheduled cycle created under it."""
    scenario = setup_approved_authorization(sequence_index=sequence_index, **scenario_overrides)
    cycle = create_cycle(scenario["plan"], scenario["preauthorization"], scenario["clinic"])
    scenario["cycle"] = cycle
    return scenario


def setup_recorded_outcome_cycle(sequence_index: int = 1, at_clock: str = "2026-09-26T00:00:00Z",
                                 transfer_date: str = "2026-09-10T00:00:00Z",
                                 outcome: dict = None, **scenario_overrides) -> dict:
    """A cycle driven to OUTCOME_RECORDED, with the clinic workset still empty."""
    scenario = setup_cycle_under_authorization(sequence_index=sequence_index,
                                               **scenario_overrides)
    recorded = drive_cycle_to_outcome_recorded(
        scenario["cycle"], scenario["clinic"], at_clock=at_clock,
        transfer_date=transfer_date, outcome=outcome)
    scenario["cycle"] = recorded
    scenario["plan"] = get_success_data(
        api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK))
    scenario["bundle"] = get_success_data(
        api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST))
    return scenario


def setup_reported_outcome_cycle(outcome: dict = None, **scenario_overrides) -> dict:
    """A recorded cycle whose outcome has also been reported to the clinic."""
    scenario = setup_recorded_outcome_cycle(outcome=outcome, **scenario_overrides)
    record = report_clinic_outcome(scenario["clinic"], scenario["cycle"], **(outcome or {}))
    scenario["outcome_record"] = record
    scenario["clinic"] = get_success_data(api_client.get_clinic(scenario["clinic"]["id"], NETWORK))
    scenario["member"] = get_success_data(api_client.get_member(scenario["member"]["id"], NETWORK))
    return scenario


def setup_dispensed_medication_order(acquisition_cost_cents: int = 420000,
                                     preauth_overrides: dict = None,
                                     bundle_overrides: dict = None,
                                     **scenario_overrides) -> dict:
    """An approved authorization plus a specialty order already at DISPENSING."""
    scenario = setup_approved_authorization(
        preauth_overrides=preauth_overrides, bundle_overrides=bundle_overrides,
        **scenario_overrides)
    order = get_success_data(api_client.create_medication_order(
        create_medication_order_payload(
            scenario["member"]["id"], scenario["preauthorization"]["id"],
            acquisition_cost_cents=acquisition_cost_cents),
        PHARMACIST))
    bundle_now = get_success_data(
        api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST))
    order = get_success_data(api_client.dispense_medication_order(
        order["id"], {"expected_bundle_entitlement_version": bundle_now["version"]}, PHARMACIST))
    scenario["medication_order"] = order
    scenario["bundle"] = get_success_data(
        api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST))
    return scenario


def setup_claim_for_authorization(service_category: str = "CLINIC_BUNDLE",
                                  billed_cents: int = None, claim_overrides: dict = None,
                                  **scenario_overrides) -> dict:
    """An approved authorization plus one claim in RECEIVED status."""
    scenario = setup_approved_authorization(**scenario_overrides)
    payload = create_claim_payload(
        scenario["member"]["id"], scenario["preauthorization"]["id"],
        service_category=service_category,
        billed_cents=(billed_cents if billed_cents is not None
                      else (TEST_DEFAULTS["BUNDLE_RATE_IVF"] if service_category == "CLINIC_BUNDLE"
                            else 200000)),
        **(claim_overrides or {}))
    claim = get_success_data(api_client.create_claim(payload, CLAIMS))
    scenario["claim"] = claim
    return scenario


def setup_adjudicated_claim(**scenario_overrides) -> dict:
    """An approved authorization plus one adjudicated claim."""
    scenario = setup_claim_for_authorization(**scenario_overrides)
    claim = get_success_data(api_client.adjudicate_claim(scenario["claim"]["id"], CLAIMS))
    scenario["claim"] = claim
    return scenario


def setup_paid_claim(**scenario_overrides) -> dict:
    """An approved authorization plus one paid claim."""
    scenario = setup_adjudicated_claim(**scenario_overrides)
    preauth = get_success_data(
        api_client.get_preauthorization(scenario["preauthorization"]["id"], CLAIMS))
    claim = get_success_data(api_client.pay_claim(
        scenario["claim"]["id"], {"expected_preauthorization_version": preauth["version"]}, CLAIMS))
    scenario["claim"] = claim
    return scenario


def setup_denied_claim(billed_cents: int = 2000000, deny_at: str = "2027-04-01T00:00:00Z",
                       authorization_effective_to: str = "2027-01-01T00:00:00Z",
                       **scenario_overrides) -> dict:
    """A claim denied after its authorization's validity has closed.

    The authorization window is derived by the service at approval, so callers that
    need the denial gate open must pass a clock past `authorization_effective_to`.
    """
    scenario = setup_claim_for_authorization(billed_cents=billed_cents, **scenario_overrides)
    setup_clock(deny_at)
    claim = get_success_data(api_client.deny_claim(scenario["claim"]["id"], CLAIMS))
    scenario["claim"] = claim
    return scenario


# ─── Tier 3: full lifecycle shortcuts ─────────────────────────────────────────

def setup_plan_completed(**scenario_overrides) -> dict:
    """A plan driven to COMPLETED by its single cycle's recorded outcome."""
    return setup_recorded_outcome_cycle(**scenario_overrides)


def setup_cycle_outcome_pending(clinic: dict, cycle: dict, transfer_date: str,
                                at_clock: str) -> dict:
    """Advance a transferred cycle to OUTCOME_PENDING through the clock sweep."""
    drive_cycle_to_transfer(cycle, clinic, transfer_date=transfer_date)
    setup_clock(at_clock)
    tick_clock()
    return get_success_data(api_client.get_treatment_cycle(cycle["id"], NETWORK))


def setup_surrender_route(member: dict, advocate: dict, **overrides) -> dict:
    """File a surrender route for a member, carrying the member's current version."""
    current = get_success_data(api_client.get_member(member["id"], NETWORK))
    payload = create_surrender_route_payload(
        current["version"],
        **overrides)
    return get_success_data(api_client.create_surrender_route(
        member["id"], payload, make_care_advocate_headers(advocate["id"])))


def setup_routed_surrender_route(member: dict, advocate: dict, **overrides) -> dict:
    """File a surrender route and let the clock sweep move it to ROUTED."""
    route = setup_surrender_route(member, advocate, **overrides)
    tick_clock()
    # The route row is read back through the member's own nested collection, whose
    # role set is the widest; the standing collection read is narrower and does not
    # admit the roles the overlapping scenarios go on to use.
    return _find_route_on_member(member["id"], advocate["id"], route["id"])


def _find_route_on_member(member_id: str, advocate_id: str, route_id: str) -> dict:
    rows = get_success_data(api_client.list_member_surrender_routes(
        member_id, make_care_advocate_headers(advocate_id)))
    for row in rows:
        if row["id"] == route_id:
            return row
    raise AssertionError(f"Surrender route {route_id} did not resolve on its member.")


def setup_pathway_request(member: dict, advocate: dict, **overrides) -> dict:
    payload = create_pathway_request_payload(member["id"], **overrides)
    return get_success_data(api_client.create_pathway_request(
        payload, make_care_advocate_headers(advocate["id"])))


def setup_approved_pathway_request(reviewer_id: str = "rev-path", **pathway_overrides) -> dict:
    """Member intake base plus one APPROVED pathway request."""
    employer, bundle = setup_employer_bundle()
    advocate, member = setup_advocate_and_member(employer)
    request = setup_pathway_request(member, advocate, **pathway_overrides)
    headers = make_clinical_reviewer_headers(reviewer_id)
    get_success_data(api_client.begin_pathway_review(request["id"], headers))
    request = get_success_data(api_client.decide_pathway_request(
        request["id"], {"decision": "APPROVE"}, headers))
    return {"employer": employer, "advocate": advocate, "member": member, "pathway": request}


# ─── Tier 4: accumulation / threshold targeting ────────────────────────────────

def setup_authorization_near_score_floor(score_profile: str = "69", **scenario_overrides) -> dict:
    """A plan with an authorization already moved into CLINICAL_REVIEW.

    `score_profile` selects one of the criteria profiles the clinical gate's bands
    produce: "69" (one band under the floor), "70" (exactly at the floor), "100"
    (all-neutral) or "0" (every penalty band at maximum).
    """
    profiles = {"0": CRITERIA_SCORE_0, "69": CRITERIA_BELOW_FLOOR,
                "70": CRITERIA_SCORE_70, "100": NEUTRAL_CRITERIA}
    scenario = setup_member_plan_clinic(**scenario_overrides)
    preauth = create_preauthorization(
        scenario["plan"], scenario["advocate"], cycle_sequence_index=1,
        criteria_inputs=profiles[score_profile])
    get_success_data(api_client.begin_clinical_review(
        preauth["id"], make_clinical_reviewer_headers(REVIEWER_ID)))
    scenario["preauthorization"] = get_success_data(
        api_client.get_preauthorization(preauth["id"], CLAIMS))
    scenario["plan"] = get_success_data(
        api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK))
    return scenario


def setup_bundle_pool_remainder(remaining_cents: int, acquisition_cost_cents: int = 300000,
                                pool_cents: int = 500000, allocation_method: str = "SEQUENTIAL_BUNDLE",
                                **scenario_overrides) -> dict:
    """Drive a bundle's specialty-pharmacy pool down to exactly `remaining_cents`.

    A first specialty order is created for exactly the cents the pool must shed and
    dispensed; the pool's remainder is then whatever `remaining_cents` names. The
    second order is returned in PRESCRIBED status for the boundary assertion.
    """
    drain = pool_cents - remaining_cents
    scenario = setup_member_plan_clinic(
        allocation_method=allocation_method,
        bundle_overrides={"pharmacy_pool_cents": pool_cents,
                          "lifetime_max_cycles": 4,
                          "max_cycles_per_year": 4,
                          **(scenario_overrides.pop("bundle_overrides", None) or {})},
        **scenario_overrides)
    preauth = create_preauthorization(scenario["plan"], scenario["advocate"],
                                      cycle_sequence_index=1,
                                      criteria_inputs=NEUTRAL_CRITERIA,
                                      member_cost_share_pct=0)
    preauth = approve_preauthorization(preauth, scenario["plan"], reviewer_id=REVIEWER_ID)
    scenario["preauthorization"] = preauth

    if drain > 0:
        order = get_success_data(api_client.create_medication_order(
            create_medication_order_payload(
                scenario["member"]["id"], preauth["id"],
                medication_code="DRAIN-FILL", acquisition_cost_cents=drain),
            PHARMACIST))
        current = get_success_data(api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST))
        get_success_data(api_client.dispense_medication_order(
            order["id"], {"expected_bundle_entitlement_version": current["version"]}, PHARMACIST))

    scenario["bundle"] = get_success_data(
        api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST))
    scenario["boundary_order"] = get_success_data(api_client.create_medication_order(
        create_medication_order_payload(
            scenario["member"]["id"], preauth["id"],
            medication_code="BOUNDARY-FILL", acquisition_cost_cents=acquisition_cost_cents),
        PHARMACIST))
    return scenario


def setup_approved_authorizations(count: int, allocation_method: str = "CONCURRENT_BUNDLE",
                                  bundle_overrides: dict = None, **scenario_overrides) -> dict:
    """One plan carrying `count` APPROVED authorizations at sequence 1..count."""
    overrides = dict(bundle_overrides or {})
    overrides.setdefault("lifetime_max_cycles", max(count, 3))
    overrides.setdefault("max_cycles_per_year", max(count, 3))
    scenario = setup_member_plan_clinic(
        allocation_method=allocation_method, bundle_overrides=overrides,
        plan_overrides={"planned_cycles": count}, **scenario_overrides)
    authorizations = []
    for index in range(1, count + 1):
        preauth = create_preauthorization(
            scenario["plan"], scenario["advocate"], cycle_sequence_index=index,
            criteria_inputs=NEUTRAL_CRITERIA)
        preauth = approve_preauthorization(preauth, scenario["plan"], reviewer_id=REVIEWER_ID)
        authorizations.append(preauth)
    scenario["preauthorizations"] = authorizations
    scenario["preauthorization"] = authorizations[0]
    scenario["plan"] = get_success_data(
        api_client.get_treatment_plan(scenario["plan"]["id"], NETWORK))
    scenario["bundle"] = get_success_data(
        api_client.get_bundle_entitlement(scenario["bundle"]["id"], PHARMACIST))
    return scenario


def setup_clinic_with_reported_workset(outcomes: list, clinic_overrides: dict = None,
                                      members_needed: int = None, **scenario_overrides) -> dict:
    """Build a clinic whose reporting workset holds one record per entry in `outcomes`.

    Each entry is a dict of OutcomeRecord inputs (`live_birth`, `births_count`,
    `multiple_birth`, `gestational_weeks`). Each outcome gets its own member, plan,
    authorization and cycle, so the records land on the same clinic independently.
    Returns a dict whose `records` list is in the same order as `outcomes`.
    """
    employer, bundle = setup_employer_bundle(
        allocation_method="CONCURRENT_BUNDLE",
        bundle_overrides={"lifetime_max_cycles": max(len(outcomes) + 2, 4),
                          "max_cycles_per_year": max(len(outcomes) + 2, 4),
                          **(scenario_overrides.pop("bundle_overrides", None) or {})})
    advocate = create_advocate()
    clinic, contract = setup_contracted_clinic(clinic_overrides=clinic_overrides or {})

    records = []
    for index, outcome in enumerate(outcomes, start=1):
        # Each authorization is approved at the clock's start so the back-dated
        # service instants below fall inside its validity window.
        setup_clock()
        member = create_member(employer["id"], advocate=advocate,
                               member_overrides={"external_ref": f"WORKSET-{index}"})
        plan = create_plan(member, bundle, advocate, planned_cycles=1)
        plan = select_clinic_for_plan(plan, clinic, advocate)
        preauth = create_preauthorization(plan, advocate, cycle_sequence_index=1,
                                         criteria_inputs=NEUTRAL_CRITERIA)
        preauth = approve_preauthorization(preauth, plan, reviewer_id=REVIEWER_ID)
        cycle = create_cycle(plan, preauth, clinic,
                             retrieval_date="2026-09-05T00:00:00Z",
                             transfer_date="2026-09-10T00:00:00Z")
        cycle = drive_cycle_to_outcome_recorded(
            cycle, clinic, at_clock="2026-09-26T00:00:00Z",
            transfer_date="2026-09-10T00:00:00Z", outcome=outcome)
        record = report_clinic_outcome(clinic, cycle, **outcome)
        records.append(record)

    return {
        "employer": employer,
        "bundle": bundle,
        "advocate": advocate,
        "clinic": get_success_data(api_client.get_clinic(clinic["id"], NETWORK)),
        "records": records,
    }


def setup_clinic_report_one_short_of_maturity(clinic_overrides: dict = None, **scenario_overrides) -> dict:
    """A CONTRACTED clinic whose workset sits exactly one report below its maturity
    threshold, which is the third eligibility gate's condition."""
    overrides = {"maturity_report_threshold": 2, **(clinic_overrides or {})}
    return setup_clinic_with_reported_workset(
        [{"live_birth": False, "births_count": 0, "multiple_birth": False,
          "gestational_weeks": 0}],
        clinic_overrides=overrides,
        **scenario_overrides)


def setup_clinic_with_live_birth_meeting_floor(clinic_overrides: dict = None,
                                              **scenario_overrides) -> dict:
    """A CONTRACTED clinic holding exactly one live-birth record against a
    maturity threshold of one, so its live-birth rate reads the full 10000."""
    overrides = {"maturity_report_threshold": 1, "min_live_birth_rate_bps": 6000,
                 **(clinic_overrides or {})}
    return setup_clinic_with_reported_workset(
        [{"live_birth": True, "births_count": 1, "multiple_birth": False,
          "gestational_weeks": 38}],
        clinic_overrides=overrides,
        **scenario_overrides)


# ─── Tier 5: finalization / terminal states ───────────────────────────────────

def setup_abandoned_plan(**scenario_overrides) -> dict:
    """A plan walked away from before treatment began."""
    scenario = setup_member_plan_clinic(**scenario_overrides)
    plan = get_success_data(api_client.abandon_plan(
        scenario["plan"]["id"], make_care_advocate_headers(scenario["advocate"]["id"])))
    scenario["plan"] = plan
    return scenario


def setup_clinic_suspended(clinic: dict) -> dict:
    return get_success_data(api_client.suspend_clinic(clinic["id"], NETWORK))


def setup_clinic_terminated(clinic: dict) -> dict:
    get_success_data(api_client.suspend_clinic(clinic["id"], NETWORK))
    return get_success_data(api_client.terminate_clinic(clinic["id"], NETWORK))


def setup_exhausted_bundle_pool(**scenario_overrides) -> dict:
    """A bundle whose specialty-pharmacy pool has been drawn down to exactly zero."""
    return setup_bundle_pool_remainder(remaining_cents=0, **scenario_overrides)