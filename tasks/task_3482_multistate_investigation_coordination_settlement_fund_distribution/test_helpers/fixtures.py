"""Composite setup helpers for the Multistate Settlement Coordination API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: LeadStateAG / ParticipatingStateAG / StateLegislature are
entity-backed by StateOffice, so every ownership-gated call below is made
with make_<role>_headers(office["id"]) built from the real office record —
never the shared TEST_USERS fallback constants.

Canonical world (PRD-consistent reference scenario used by most composites):
  offices CA(pop 100, PREAPPROPRIATED), TX(300, PREAPPROPRIATED),
  NY(400, CERTIFICATION_REQUIRED), FL(200, GENERAL_FUND_ONLY);
  harms 50/150/200/100; leads CA and TX (tiers LEAD_ONLY / RESTRICTED);
  settlement total 100,000,000 / reserve 10,000,000 / POPULATION / 3 terms;
  sign-ons CA+TX+NY SIGNED, FL DECLINED; logical clock 2026-09-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CANONICAL_INJUNCTIVE_TERMS,
    CANONICAL_LEAD_CODES,
    CANONICAL_OFFICE_CODES,
    CANONICAL_OFFICES,
    CANONICAL_SIGN_ONS,
    CLOCK_DEFAULT,
    MONITORING_PERIOD_STARTS,
)
from .factories import (
    advance_payload,
    counter_settlement_payload,
    create_claimant_payload,
    create_demand_payload,
    create_disbursement_payload,
    create_finding_payload,
    create_investigation_payload,
    create_participation_payload,
    create_response_payload,
    create_settlement_payload,
    create_state_office_payload,
    deposit_payload,
    execute_cia_payload,
    revise_settlement_payload,
    set_clock_payload,
    sign_on_payload,
    validate_claimant_payload,
)
from .test_users import (
    TEST_USERS,
    make_lead_state_ag_headers,
    make_participating_state_ag_headers,
    make_state_legislature_headers,
)

CHAIR = TEST_USERS["committee_chair_headers"]
COUNSEL = TEST_USERS["defendant_counsel_headers"]
FUND_ADMIN = TEST_USERS["fund_administrator_headers"]
MONITOR = TEST_USERS["compliance_monitor_headers"]


def _ag_headers(office_id: str, is_lead: bool) -> dict:
    """Role header for an AG-office caller: LeadStateAG when the office is a
    designated lead of the matter, ParticipatingStateAG otherwise."""
    if is_lead:
        return make_lead_state_ag_headers(office_id)
    return make_participating_state_ag_headers(office_id)


def _participation_is_lead(participation: dict) -> bool:
    return participation.get("committee_role") == "LEAD"


# ── Tier 0: primitive creators ────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_DEFAULT) -> dict:
    """Set the logical clock (CommitteeChair test-driving capability, PRD §2.4)."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), CHAIR)
    )


def create_state_office(state_code: str = "CA", **overrides) -> dict:
    payload = create_state_office_payload(state_code=state_code, **overrides)
    return get_success_data(api_client.create_state_office(payload, CHAIR), 201)


def create_investigation(**overrides) -> dict:
    payload = create_investigation_payload(**overrides)
    return get_success_data(api_client.create_investigation(payload, CHAIR), 201)


def invite_participation(investigation_id: str, state_office_id: str) -> dict:
    payload = create_participation_payload(state_office_id)
    return get_success_data(
        api_client.create_participation(investigation_id, payload, CHAIR), 201,
    )


def execute_cia(participation: dict, confidentiality_tier: str = "STANDARD") -> dict:
    """Execute the CIA as the invited office itself (ownership-gated)."""
    headers = make_participating_state_ag_headers(participation["state_office_id"])
    payload = execute_cia_payload(confidentiality_tier=confidentiality_tier)
    return get_success_data(
        api_client.execute_cia(participation["id"], payload, headers)
    )


def designate_lead(participation_id: str) -> dict:
    return get_success_data(api_client.designate_lead(participation_id, CHAIR))


def withdraw_participation(participation: dict, as_chair: bool = False) -> dict:
    """Withdraw as the owning office (default) or as the CommitteeChair."""
    if as_chair:
        headers = CHAIR
    else:
        headers = _ag_headers(
            participation["state_office_id"], _participation_is_lead(participation)
        )
    return get_success_data(api_client.withdraw_participation(participation["id"], headers))


def advance_investigation(investigation_id: str, to_phase: str) -> dict:
    payload = advance_payload(to_phase)
    return get_success_data(
        api_client.advance_investigation(investigation_id, payload, CHAIR)
    )


def issue_demand(participation: dict, scope_text: str = "Pricing documents") -> dict:
    """Issue a demand as the owning office; role follows its committee_role."""
    headers = _ag_headers(
        participation["state_office_id"], _participation_is_lead(participation)
    )
    payload = create_demand_payload(scope_text=scope_text)
    return get_success_data(
        api_client.create_demand(participation["id"], payload, headers), 201,
    )


def submit_response(investigation_id: str, demand_ids, **overrides) -> dict:
    payload = create_response_payload(demand_ids, **overrides)
    return get_success_data(
        api_client.create_response(investigation_id, payload, COUNSEL), 201,
    )


def accept_response(response_id: str, lead_office: dict) -> dict:
    """Accept a consolidated response as a lead office of the investigation."""
    headers = make_lead_state_ag_headers(lead_office["id"])
    return get_success_data(api_client.accept_response(response_id, headers))


def fulfill_response(response_id: str) -> dict:
    return get_success_data(api_client.fulfill_response(response_id, COUNSEL))


def propose_settlement(investigation_id: str, lead_office: dict, **overrides) -> dict:
    """Propose a settlement as a lead office (lead-gated, ownership-checked)."""
    headers = make_lead_state_ag_headers(lead_office["id"])
    payload = create_settlement_payload(**overrides)
    return get_success_data(
        api_client.create_settlement(investigation_id, payload, headers), 201,
    )


def counter_settlement(settlement: dict, **overrides) -> dict:
    """Counter a settlement; re-reads the current version for the OCC field."""
    fresh = get_success_data(api_client.get_settlement(settlement["id"], CHAIR))
    payload = counter_settlement_payload(fresh["version"], **overrides)
    return get_success_data(api_client.counter_settlement(fresh["id"], payload, COUNSEL))


def revise_settlement(settlement: dict, lead_office: dict, **overrides) -> dict:
    """Revise a countered settlement as a lead office; re-reads the version."""
    fresh = get_success_data(api_client.get_settlement(settlement["id"], CHAIR))
    payload = revise_settlement_payload(fresh["version"], **overrides)
    headers = make_lead_state_ag_headers(lead_office["id"])
    return get_success_data(api_client.revise_settlement(fresh["id"], payload, headers))


def agree_terms(settlement_id: str) -> dict:
    return get_success_data(api_client.agree_terms(settlement_id, COUNSEL))


def open_sign_on(settlement_id: str) -> dict:
    return get_success_data(api_client.open_sign_on(settlement_id, CHAIR))


def record_sign_on(settlement_id: str, participation: dict, decision: str) -> dict:
    """Record a sign-on decision as the deciding office (ownership-gated)."""
    headers = _ag_headers(
        participation["state_office_id"], _participation_is_lead(participation)
    )
    payload = sign_on_payload(decision)
    return get_success_data(
        api_client.record_sign_on(settlement_id, payload, headers), 201,
    )


def execute_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.execute_settlement(settlement_id, CHAIR))


def deposit_funds(settlement_id: str, amount_cents: int) -> dict:
    payload = deposit_payload(amount_cents)
    return get_success_data(api_client.deposit_settlement(settlement_id, payload, COUNSEL))


def request_disbursement(line: dict, office: dict, is_lead: bool, **overrides) -> dict:
    """Request a disbursement as the line's owning office (ownership-gated)."""
    headers = _ag_headers(office["id"], is_lead)
    payload = create_disbursement_payload(**overrides)
    return get_success_data(
        api_client.create_disbursement(line["id"], payload, headers), 201,
    )


def certify_disbursement(disbursement_id: str, office: dict) -> dict:
    """Certify a disbursement as the legislature of the line's own state."""
    headers = make_state_legislature_headers(office["id"])
    return get_success_data(api_client.certify_disbursement(disbursement_id, headers))


def release_disbursement(disbursement_id: str) -> dict:
    return get_success_data(api_client.release_disbursement(disbursement_id, FUND_ADMIN))


def register_claimant(settlement_id: str, **overrides) -> dict:
    payload = create_claimant_payload(**overrides)
    return get_success_data(
        api_client.create_claimant(settlement_id, payload, FUND_ADMIN), 201,
    )


def adjudicate_claimant(claimant_id: str, decision: str, **overrides) -> dict:
    payload = validate_claimant_payload(decision, **overrides)
    return get_success_data(api_client.validate_claimant(claimant_id, payload, FUND_ADMIN))


def compute_restitution(settlement_id: str) -> dict:
    return get_success_data(api_client.restitution_compute(settlement_id, FUND_ADMIN))


def open_monitoring_period(settlement_id: str) -> dict:
    return get_success_data(
        api_client.create_monitoring_period(settlement_id, CHAIR), 201,
    )


def file_finding(period_id: str, term_index: int, outcome: str, **overrides) -> dict:
    payload = create_finding_payload(term_index=term_index, outcome=outcome, **overrides)
    return get_success_data(api_client.file_finding(period_id, payload, MONITOR), 201)


def get_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.get_settlement(settlement_id, CHAIR))


def get_investigation(investigation_id: str) -> dict:
    return get_success_data(api_client.get_investigation(investigation_id, CHAIR))


def get_allocation_line(line_id: str) -> dict:
    return get_success_data(api_client.get_allocation_line(line_id, CHAIR))


def list_allocation_lines(settlement_id: str) -> list:
    resp = api_client.list_settlement_allocation_lines(settlement_id, CHAIR)
    if not (200 <= resp.status_code < 300):
        raise AssertionError(
            f"Setup failed listing allocation lines: HTTP {resp.status_code}"
        )
    return resp.json()["data"]


# ── Tier 1-3: composite world builders ────────────────────────────────────
# Each returns a World dict: offices/participations keyed by state code,
# plus the investigation (freshly re-read), and settlement/lines when built.

def setup_offices(office_codes=CANONICAL_OFFICE_CODES, office_specs=None) -> dict:
    """Create one StateOffice per code. office_specs overrides the canonical
    per-office registration inputs (keyed by state code)."""
    specs = office_specs or CANONICAL_OFFICES
    offices = {}
    for code in office_codes:
        spec = dict(specs[code])
        spec.pop("cia_tier", None)
        spec.pop("is_lead", None)
        offices[code] = create_state_office(**spec)
    return offices


def setup_draft_world(office_codes=CANONICAL_OFFICE_CODES,
                      lead_codes=CANONICAL_LEAD_CODES,
                      office_specs=None, **inv_overrides) -> dict:
    """Offices + investigation + INVITED participations + executed CIAs +
    lead designations. Investigation stays in DRAFT (designation is lawful
    in DRAFT or OPEN; leads must exist before advancing to OPEN)."""
    offices = setup_offices(office_codes, office_specs)
    investigation = create_investigation(**inv_overrides)
    specs = office_specs or CANONICAL_OFFICES
    participations = {}
    for code in office_codes:
        part = invite_participation(investigation["id"], offices[code]["id"])
        tier = specs.get(code, {}).get("cia_tier", "STANDARD")
        participations[code] = execute_cia(part, tier)
    for code in lead_codes:
        participations[code] = designate_lead(participations[code]["id"])
    return {
        "offices": offices,
        "investigation": get_investigation(investigation["id"]),
        "participations": participations,
    }


def setup_open_world(**kwargs) -> dict:
    """Draft world advanced DRAFT -> OPEN (activation quorum satisfied)."""
    world = setup_draft_world(**kwargs)
    world["investigation"] = advance_investigation(
        world["investigation"]["id"], "OPEN"
    )
    return world


def setup_negotiation_world(demand_by: str = None, **kwargs) -> dict:
    """Open world advanced to NEGOTIATION: DISCOVERY, one demand issued by a
    lead office, consolidated response submitted and accepted, then advance
    (the ACCEPTED response satisfies the negotiation gate)."""
    world = setup_open_world(**kwargs)
    inv_id = world["investigation"]["id"]
    # Default demander is the world's own first lead office (custom worlds may
    # not contain the canonical CA lead at all).
    demander = demand_by or kwargs.get("lead_codes", CANONICAL_LEAD_CODES)[0]
    world["investigation"] = advance_investigation(inv_id, "DISCOVERY")
    demand = issue_demand(world["participations"][demander])
    world["demands"] = {demander: demand}
    response = submit_response(inv_id, [demand["id"]])
    world["response"] = accept_response(
        response["id"], world["offices"][demander]
    )
    world["investigation"] = advance_investigation(inv_id, "NEGOTIATION")
    return world


def setup_proposed_world(lead: str = None, **settlement_overrides) -> dict:
    """Negotiation world with a PROPOSED settlement (provisional allocation
    computed; investigation.active_settlement_id set)."""
    office_codes = settlement_overrides.pop("office_codes", CANONICAL_OFFICE_CODES)
    lead_codes = settlement_overrides.pop("lead_codes", CANONICAL_LEAD_CODES)
    office_specs = settlement_overrides.pop("office_specs", None)
    world = setup_negotiation_world(
        office_codes=office_codes, lead_codes=lead_codes, office_specs=office_specs,
    )
    proposer = lead or lead_codes[0]
    world["settlement"] = propose_settlement(
        world["investigation"]["id"], world["offices"][proposer],
        **settlement_overrides,
    )
    world["investigation"] = get_investigation(world["investigation"]["id"])
    return world


def setup_sign_on_open_world(**settlement_overrides) -> dict:
    """Proposed world moved to the sign-on campaign: defendant agrees terms,
    investigation advances NEGOTIATION -> SETTLEMENT_PENDING, sign-on opened
    (deadline = now + 45 days)."""
    world = setup_proposed_world(**settlement_overrides)
    world["settlement"] = agree_terms(world["settlement"]["id"])
    world["investigation"] = advance_investigation(
        world["investigation"]["id"], "SETTLEMENT_PENDING"
    )
    world["settlement"] = open_sign_on(world["settlement"]["id"])
    return world


def record_sign_ons(world: dict, decisions: dict = None) -> dict:
    """Record one sign-on decision per listed office code, in dict order
    (decided_at ordering follows call order under the frozen clock)."""
    decisions = CANONICAL_SIGN_ONS if decisions is None else decisions
    stl_id = world["settlement"]["id"]
    for code, decision in decisions.items():
        world["settlement"] = record_sign_on(
            stl_id, world["participations"][code], decision,
        )
    return world


def setup_executed_world(decisions: dict = None, **settlement_overrides) -> dict:
    """Sign-on-open world with all decisions recorded, then executed.
    Returns the world with a freshly read EXECUTED settlement and its
    allocation lines in API list order (created_at ASC == decided_at ASC)."""
    world = setup_sign_on_open_world(**settlement_overrides)
    record_sign_ons(world, decisions)
    world["settlement"] = execute_settlement(world["settlement"]["id"])
    world["lines"] = list_allocation_lines(world["settlement"]["id"])
    world["investigation"] = get_investigation(world["investigation"]["id"])
    return world


def fund_world(world: dict, amount_cents: int = None) -> dict:
    """Deposit funds (default: the settlement's full monetary total)."""
    amount = amount_cents if amount_cents is not None else world["settlement"][
        "monetary_total_cents"
    ]
    world["settlement"] = deposit_funds(world["settlement"]["id"], amount)
    return world


def disburse_line_in_full(world: dict, line: dict, use_code: str = "PROGRAM") -> dict:
    """Request, (if the office's rule requires it) certify, and release a
    single disbursement covering the line's full remaining gross share."""
    office = world["offices"][line["state_code"]]
    participation = world.get("participations", {}).get(line["state_code"], {})
    is_lead = participation.get("committee_role") == "LEAD"
    disbursement = request_disbursement(
        line, office, is_lead, amount_cents=line["remaining_cents"],
        use_code=use_code,
    )
    if disbursement["status"] == "REQUESTED":
        disbursement = certify_disbursement(disbursement["id"], office)
    return release_disbursement(disbursement["id"])


def setup_fully_disbursed_world(**settlement_overrides) -> dict:
    """Executed world, fully funded, investigation advanced to SETTLED, then
    every allocation line released in full (fund becomes DISBURSED)."""
    world = setup_executed_world(**settlement_overrides)
    fund_world(world)
    world["investigation"] = advance_investigation(
        world["investigation"]["id"], "SETTLED"
    )
    for line in world["lines"]:
        disburse_line_in_full(world, line)
    world["settlement"] = get_settlement(world["settlement"]["id"])
    world["lines"] = list_allocation_lines(world["settlement"]["id"])
    return world


def setup_monitoring_world(**settlement_overrides) -> dict:
    """Fully disbursed world advanced SETTLED -> MONITORING (fund DISBURSED
    satisfies the funding gate)."""
    world = setup_fully_disbursed_world(**settlement_overrides)
    world["investigation"] = advance_investigation(
        world["investigation"]["id"], "MONITORING"
    )
    return world


# ── Tier 4-5: monitoring periods, claimants, terminal states ─────────────

def run_compliant_period(world: dict, period_index: int,
                         term_count: int = None, outcome: str = "COMPLIANT",
                         set_clock_to_window_start: bool = True) -> dict:
    """Open period `period_index` (1-based) and file one finding per
    injunctive term with the same outcome, auto-closing the period. Assumes
    the settlement was executed at the default clock when moving time."""
    if set_clock_to_window_start and period_index > 1:
        set_clock(MONITORING_PERIOD_STARTS[period_index - 1])
    period = open_monitoring_period(world["settlement"]["id"])
    n_terms = term_count if term_count is not None else len(
        world["settlement"]["injunctive_terms"]
    )
    for term_index in range(n_terms):
        period = file_finding(period["id"], term_index, outcome)
    return period


def setup_all_periods_compliant_world(period_count: int = 6,
                                      **settlement_overrides) -> dict:
    """Monitoring world with `period_count` periods each closed COMPLIANT.
    At period_count == 6 with a DISBURSED fund, the final close cascades the
    settlement to CLOSED_OUT and the investigation to CLOSED."""
    world = setup_monitoring_world(**settlement_overrides)
    periods = []
    for idx in range(1, period_count + 1):
        periods.append(run_compliant_period(world, idx))
    world["periods"] = periods
    world["settlement"] = get_settlement(world["settlement"]["id"])
    world["investigation"] = get_investigation(world["investigation"]["id"])
    return world


def register_and_validate_claimants(settlement_id: str, specs: list) -> list:
    """Register then VALIDATE each spec {state_code, contact_ref,
    claimed_loss_cents, validated_loss_cents}; returns the validated
    claimants in creation order (created_at ASC)."""
    claimants = []
    for spec in specs:
        claimant = register_claimant(
            settlement_id,
            state_code=spec["state_code"],
            contact_ref=spec["contact_ref"],
            claimed_loss_cents=spec["claimed_loss_cents"],
        )
        claimants.append(adjudicate_claimant(
            claimant["id"], "VALIDATED",
            validated_loss_cents=spec["validated_loss_cents"],
        ))
    return claimants

