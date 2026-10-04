"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints (the server restarts against an empty database before each test).
Setup calls use get_success_data() so a broken precondition raises a clear
"Setup step failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    create_agency_payload,
    create_agreement_payload,
    create_appointment_application_payload,
    create_campaign_payload,
    create_claim_payload,
    create_policy_payload,
    create_staff_payload,
    inject_agent_payload,
)
from .test_users import TEST_USERS, make_agency_principal_headers

ADMIN = TEST_USERS["platform_admin_headers"]
EXEC = TEST_USERS["appointing_executive_headers"]
FIELD = TEST_USERS["field_manager_headers"]
CLAIMS = TEST_USERS["claims_adjuster_headers"]


# ─── Tier 1: state progression ────────────────────────

def set_clock(to_iso8601: str = CLOCK_START):
    """Move the logical clock (PRD §2.11)."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_agency(**overrides) -> dict:
    """Create an agency in APPROVED status (PRD §3.9)."""
    return get_success_data(api_client.create_agency(create_agency_payload(**overrides), EXEC))


def create_agency_active(**overrides) -> dict:
    """Create an agency and move it to ACTIVE. Returns the activated agency."""
    agency = create_agency(**overrides)
    activate_agency(agency["id"], agency["version"])
    return read_agency(agency["id"])


def activate_agency(agency_id: str, expected_version: int) -> dict:
    """Activate an APPROVED agency (PRD §3.9)."""
    return get_success_data(
        api_client.activate_agency(
            agency_id, {"expected_agency_version": expected_version}, EXEC
        )
    )


def read_agency(agency_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_agency(agency_id, headers or EXEC))


def inject_agent(**overrides) -> dict:
    """Seed a raw agent record (PRD §3.2)."""
    return get_success_data(api_client.inject_agent(inject_agent_payload(**overrides), ADMIN))


def draft_agreement(agent_id: str, agency_id: str, **overrides) -> dict:
    """Draft an agreement; it lands UNDER_REVIEW (PRD §3.3)."""
    return get_success_data(
        api_client.create_agreement(
            create_agreement_payload(agent_id, agency_id, **overrides), FIELD
        )
    )


def create_policy(holder_agent_id: str, owner_agency_id: str, **overrides) -> dict:
    """Create a policy on an agent's book (PRD §3.8)."""
    return get_success_data(
        api_client.create_policy(
            create_policy_payload(holder_agent_id, owner_agency_id, **overrides), FIELD
        )
    )


def create_claim(policy_id: str, **overrides) -> dict:
    """File a claim against a policy (PRD §3.8)."""
    return get_success_data(
        api_client.create_claim(create_claim_payload(policy_id, **overrides), CLAIMS)
    )


def leverage_agency(agency_id: str, owners: int = 1, **overrides):
    """
    Build an ACTIVE agency whose `owners` owner-agents each carry an ACTIVE
    agreement, so `agency_level_units` reaches `owners`. Returns
    (agency, [(agent, agreement)]).
    """
    pairs = []
    for _ in range(owners):
        agent = inject_agent(
            full_name=f"Owner {len(pairs)}",
            status="TRANSITIONING",
            license_status="LICENSED",
            is_new_agent=False,
            **overrides,
        )
        agreement = draft_agreement(agent["id"], agency_id)
        get_success_data(
            api_client.transcribe_agreement(
                agreement["id"], {"expected_agent_version": agent["version"]}, FIELD
            )
        )
        pairs.append((agent, agreement))
    return pairs


# ─── Tier 2: entity hierarchy ─────────────────────────

def setup_agency_with_owner_agent(**overrides):
    """
    ACTIVE agency + one injected ACTIVE/LICENSED agent contracted to it via an
    ACTIVE agreement. Returns (agency, agent, agreement).
    """
    agency = create_agency_active(**overrides.get("agency_overrides", {}))
    pairs = leverage_agency(agency["id"], owners=1)
    agent, agreement = pairs[0]
    return read_agency(agency["id"]), agent, agreement


def setup_agency_with_policy(exposure_cents: int = 500_000, **overrides):
    """ACTIVE agency + one OPEN policy. Returns (agency, agent, policy)."""
    agency = create_agency_active(**overrides.get("agency_overrides", {}))
    agent = inject_agent(status="ACTIVE", license_status="LICENSED", is_new_agent=False)
    policy = create_policy(
        agent["id"],
        agency["id"],
        annual_premium_cents=exposure_cents,
        **overrides.get("policy_overrides", {}),
    )
    return read_agency(agency["id"]), agent, policy


def setup_agency_with_claim(
    exposure_cents: int = 500_000, claim_amount_cents: int = 40_000, **overrides
):
    """ACTIVE agency + one OPEN policy + one OPEN claim. Returns (agency, agent, policy, claim)."""
    agency, agent, policy = setup_agency_with_policy(
        exposure_cents=exposure_cents, **overrides
    )
    claim = create_claim(policy["id"], claim_amount_cents=claim_amount_cents)
    return read_agency(agency["id"]), agent, policy, claim


def setup_agency_at_staffing_cap(units: int = 12):
    """
    ACTIVE agency carrying exactly `units` agency-level units (one ACTIVE
    agreement per owner agent). Returns (agency, owner_pairs).
    """
    agency = create_agency_active()
    pairs = leverage_agency(agency["id"], owners=units)
    return read_agency(agency["id"]), pairs


def setup_agency_with_performance_data(agency_code="CA-900", need_score=60, **overrides):
    """
    ACTIVE agency with a settled claim deep enough to push loss_ratio above the
    flag threshold. Returns (agency, agent, policy, claim).
    """
    agency = create_agency_active(
        agency_code=agency_code, market_need_score=need_score,
        **overrides.get("agency_overrides", {}),
    )
    agent = inject_agent(status="ACTIVE", license_status="LICENSED", is_new_agent=False)
    policy = create_policy(
        agent["id"], agency["id"],
        annual_premium_cents=overrides.get("annual_premium_cents", 50_000_000),
        is_new_business=overrides.get("is_new_business", True),
    )
    claim = create_claim(policy["id"], claim_amount_cents=overrides.get("claim_amount_cents", 5_000_000))
    get_success_data(api_client.settle_claim(claim["id"], CLAIMS))
    return read_agency(agency["id"]), agent, policy, claim


# ─── Tier 3: full lifecycle shortcuts ─────────────────

def appoint_agent_via_application(
    market_need_score=55, candidate_assessment_score=80, market_odds_score=80,
    creation_channel="FIELD",
):
    """
    Full application pipeline: submit → assess → approve → appoint. Returns the
    minted Agent (status APPOINTED, license NOT_LICENSED).
    """
    application = get_success_data(
        api_client.create_application(
            create_appointment_application_payload(
                market_need_score=market_need_score,
                candidate_assessment_score=candidate_assessment_score,
                market_odds_score=market_odds_score,
                creation_channel=creation_channel,
            ),
            FIELD,
        )
    )
    get_success_data(api_client.assess_application(application["id"], FIELD))
    get_success_data(api_client.approve_application(application["id"], EXEC))
    return get_success_data(api_client.appoint_application(application["id"], FIELD))


def license_and_contract_agent(agent, agency_id: str):
    """
    Read the agent's license, then transition the new agent onto `agency_id`.
    Returns the refreshed Agent with `agency_id` bound.
    """
    licensed = get_success_data(
        api_client.read_license(
            agent["id"],
            {"license_expiry_date": "2028-01-01T00:00:00Z", "product_lines": ["AUTO", "HOME", "LIFE"]},
            FIELD,
        )
    )
    return get_success_data(
        api_client.transition_book(
            agent["id"],
            {"agency_id": agency_id, "expected_agent_version": licensed["version"]},
            FIELD,
        )
    )


def setup_transitioned_agent(agency=None):
    """
    ACTIVE agency + an agent minted through the application pipeline and
    transitioned onto the agency's book (status TRANSITIONING, LICENSED).
    Returns (agency, agent).
    """
    if agency is None:
        agency = create_agency_active()
    agent = appoint_agent_via_application()
    agent = license_and_contract_agent(agent, agency["id"])
    return agency, agent


def activate_agreement_for_agent(agency_id: str, agent_id: str, **overrides) -> dict:
    """
    Draft an agreement for a TRANSITIONING/LICENSED agent and transcribe it into
    ACTIVE force (PRD §3.3). Returns the ACTIVE agreement.
    """
    agreement = draft_agreement(agent_id, agency_id, **overrides)
    agent = get_success_data(api_client.get_agent(agent_id, FIELD))
    return get_success_data(
        api_client.transcribe_agreement(
            agreement["id"], {"expected_agent_version": agent["version"]}, FIELD
        )
    )


def setup_agency_with_live_agreement():
    """
    ACTIVE agency + an owner agent that is ACTIVE with an ACTIVE agreement
    (reached through the real transition + transcribe path). Returns
    (agency, agent, agreement).
    """
    agency = create_agency_active()
    agent = appoint_agent_via_application()
    agent = license_and_contract_agent(agent, agency["id"])
    agreement = activate_agreement_for_agent(agency["id"], agent["id"])
    return read_agency(agency["id"]), agent, agreement


def setup_active_staff_member():
    """
    ACTIVE agency + ACTIVE owner agent with an ACTIVE agreement + one ACTIVE
    staff member. Returns (agency, agent, agreement, staff).
    """
    agency, agent, agreement = setup_agency_with_live_agreement()
    staff = get_success_data(
        api_client.create_staff(
            create_staff_payload(agreement["id"], full_name="Otto Member", allocation_units=8),
            make_agency_principal_headers(agency["id"]),
        )
    )
    staff = get_success_data(
        api_client.appoint_staff(staff["id"], make_agency_principal_headers(agency["id"]))
    )
    return agency, agent, agreement, staff


# ─── Tier 4: accumulation / threshold targeting ───────

def setup_agency_with_allowance_pool(exposure_cents: int = 2_000_000, **overrides):
    """
    ACTIVE agency whose allowance pool base is `exposure_cents * 0.04` (capped at
    250,000.00), with no allowance spent yet. Returns (agency, agent, policy).
    """
    return setup_agency_with_policy(
        exposure_cents=exposure_cents,
        policy_overrides={"policy_number": "POOL-P1", "product_line": "AUTO"},
        **overrides,
    )


def create_campaign(agency_id: str, **overrides) -> dict:
    """Create a marketing campaign under an ACTIVE agency (PRD §3.4)."""
    return get_success_data(
        api_client.create_campaign(
            agency_id,
            create_campaign_payload(**overrides),
            make_agency_principal_headers(agency_id),
        )
    )


def participate_campaign(agency_id: str, campaign_id: str, expected_agency_version: int):
    """Participate a PLANNED campaign, carrying the observed agency version."""
    return api_client.participate_campaign(
        agency_id,
        campaign_id,
        {"expected_agency_version": expected_agency_version},
        make_agency_principal_headers(agency_id),
    )