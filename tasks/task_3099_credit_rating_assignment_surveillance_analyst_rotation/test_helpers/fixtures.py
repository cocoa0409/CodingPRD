"""Composite setup helpers for multi-step test prerequisites.

Setup helpers use get_success_data() (a lenient validator) so a failed
precondition produces a clear "Setup failed" error instead of a confusing
assertion failure deep inside a test.

RatingAnalyst is entity-backed: every ownership-gated call made on behalf of
an analyst threads that analyst's real id through make_rating_analyst_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT, CLOCK_AFTER_COOLING_OFF, TEST_DEFAULTS
from .factories import (
    methodology_payload,
    rated_entity_payload,
    engagement_letter_payload,
    rating_request_payload,
    analyst_payload,
    team_assignment_payload,
    conflict_screening_payload,
    committee_payload,
    vote_payload,
    decide_payload,
    appeal_payload,
    surveillance_review_payload,
    review_slot_payload,
    compensation_payload,
    appearance_reconciliation_payload,
)
from .test_users import TEST_USERS, make_rating_analyst_headers

EM = TEST_USERS["engagement_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CC = TEST_USERS["committee_chair_headers"]
COMP = TEST_USERS["compensation_committee_headers"]
ANON = TEST_USERS["anonymous_headers"]
PA = TEST_USERS["platform_admin_headers"]
ANY = CO  # any authenticated caller is fine for GET reads

SCREENING_TO_VOTE = [100_000_000, 100_000_000, 100_000_000]


# ─── Tier 0: clock ───

def _set_clock(value: str):
    get_success_data(api_client.set_clock(value, PA))


# ─── Tier 1: single-entity creators ───

_methodology_serial = 0


def create_published_methodology(**overrides) -> dict:
    """Author a Methodology and publish it, so it is citable.

    PRD §2.9 rejects publishing a second methodology that claims the same
    `methodology_code` in the same sector, so each fixture-authored version gets
    its own code unless the caller pins one explicitly.
    """
    global _methodology_serial
    if "methodology_code" not in overrides:
        _methodology_serial += 1
        overrides["methodology_code"] = f"CF-SENIOR-2026.{_methodology_serial}"
    payload = methodology_payload(**overrides)
    methodology = get_success_data(api_client.create_methodology(payload, CO))
    return get_success_data(api_client.publish_methodology(methodology["id"], CO))


def create_draft_methodology(**overrides) -> dict:
    """Author a Methodology but leave it in DRAFT."""
    return get_success_data(api_client.create_methodology(methodology_payload(**overrides), CO))


def create_entity(methodology_id: str, **overrides) -> dict:
    """Register a RatedEntity pinned to a methodology."""
    return get_success_data(
        api_client.create_rated_entity(rated_entity_payload(methodology_id, **overrides), EM)
    )


def onboarding_analyst(tier: str = "LEAD", **overrides) -> dict:
    overrides.setdefault("analyst_tier", tier)
    return get_success_data(api_client.create_analyst(analyst_payload(**overrides), CO))


def onboard_lead(**overrides) -> dict:
    return onboarding_analyst(tier="LEAD", **overrides)


def onboard_support(**overrides) -> dict:
    return onboarding_analyst(tier="SUPPORT", full_name="Tomas Beck", **overrides)


def onboard_committee_member(name: str = "Dana Okafor", **overrides) -> dict:
    return onboarding_analyst(tier="COMMITTEE_ELIGIBLE", full_name=name, **overrides)


# ─── Tier 2: engagement + request hierarchy ───

def create_engagement(rated_entity_id: str, activate: bool = True,
                      activate_clock: str = CLOCK_AFTER_COOLING_OFF, **overrides) -> dict:
    """Draft an engagement letter, sign it, and (optionally) activate it.

    Activation requires the logical clock to be past cooling_off_end_at; when
    activate is True the clock is advanced to activate_clock first.
    """
    letter = get_success_data(
        api_client.create_engagement_letter(engagement_letter_payload(rated_entity_id, **overrides), EM)
    )
    letter = get_success_data(api_client.submit_engagement_letter(letter["id"], EM))
    if activate:
        _set_clock(activate_clock)
        letter = get_success_data(api_client.activate_engagement_letter(letter["id"], EM))
    return letter


def setup_rated_entity_with_active_engagement(fee_amount_cents: int = None, **entity_overrides):
    """Published methodology + rated entity + ACTIVE engagement letter."""
    _set_clock(CLOCK_DEFAULT)
    methodology = create_published_methodology()
    entity = create_entity(methodology["id"], **entity_overrides)
    fee = TEST_DEFAULTS["FEE_AMOUNT_CENTS"] if fee_amount_cents is None else fee_amount_cents
    engagement = create_engagement(entity["id"], fee_amount_cents=fee)
    return entity, engagement, methodology


def create_request(engagement_id: str, entity_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rating_request(rating_request_payload(engagement_id, entity_id, **overrides), EM)
    )


def setup_engagement_with_requests(instruments, fee_amount_cents: int = 10_000_000,
                                   notional_cents: int = 100_000_000, **entity_overrides):
    """ACTIVE engagement plus one SUBMITTED request per (instrument_type, scale) pair.

    `instruments` is a list of instrument_type strings; every request uses the
    same notional unless notional_cents is overridden per call.
    """
    entity, engagement, methodology = setup_rated_entity_with_active_engagement(
        fee_amount_cents=fee_amount_cents, **entity_overrides
    )
    requests = []
    for idx, instrument in enumerate(instruments):
        scale = "GLOBAL_LONG_TERM" if instrument != "SHORT_TERM" else "GLOBAL_SHORT_TERM"
        requests.append(create_request(
            engagement["id"], entity["id"],
            instrument_type=instrument,
            instrument_notional_cents=notional_cents,
            requested_rating_scale=scale,
        ))
    return entity, engagement, requests


# ─── Tier 3: team proposal, screening and confirmation ───

def propose_team(request_id: str, lead_id: str, support_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_team_assignment(
            team_assignment_payload(request_id, lead_id, support_id, **overrides), CC
        )
    )


def record_screening(assignment_id: str, analyst_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_conflict_screening(
            conflict_screening_payload(assignment_id, analyst_id, **overrides), CO
        )
    )


def record_clear_screenings(assignment_id: str, lead_id: str, support_id: str) -> None:
    record_screening(assignment_id, lead_id, screening_result="CLEAR", conflict_type="NONE")
    record_screening(assignment_id, support_id, screening_result="CLEAR", conflict_type="NONE")


def screen_team(assignment_id: str) -> dict:
    return get_success_data(api_client.screen_team_assignment(assignment_id, CO))


def confirm_team(assignment_id: str, request_id: str) -> dict:
    """Confirm a screened assignment, supplying the observed request version."""
    version = get_success_data(api_client.get_rating_request(request_id, ANY))["version"]
    return get_success_data(
        api_client.confirm_team_assignment(
            assignment_id, {"expected_rating_request_version": version}, CC
        )
    )


def setup_screened_team(request_id: str, lead_id: str, support_id: str, **overrides) -> dict:
    """Propose + screen a team, leaving it SCREENED."""
    assignment = propose_team(request_id, lead_id, support_id, **overrides)
    record_clear_screenings(assignment["id"], lead_id, support_id)
    return screen_team(assignment["id"])


def setup_confirmed_team(request_id: str, lead_id: str, support_id: str, **overrides) -> dict:
    """Propose + screen + confirm a team, leaving it CONFIRMED."""
    assignment = setup_screened_team(request_id, lead_id, support_id, **overrides)
    return confirm_team(assignment["id"], request_id)


def setup_request_ready_for_committee(fee_amount_cents: int = 10_000_000, **entity_overrides):
    """The full compliance + analytical branch: ACTIVE engagement, screened
    request, CONFIRMED team, request TEAM_CONFIRMED.

    Returns (entity, engagement, request, assignment, methodology).
    """
    entity, engagement, methodology = setup_rated_entity_with_active_engagement(
        fee_amount_cents=fee_amount_cents, **entity_overrides
    )
    request = create_request(engagement["id"], entity["id"])
    get_success_data(api_client.open_screening(request["id"], CO))
    lead = onboard_lead()
    support = onboard_support()
    assignment = setup_confirmed_team(request["id"], lead["id"], support["id"])
    request = get_success_data(api_client.confirm_request_team(request["id"], CO))
    return entity, engagement, request, assignment, methodology


# ─── Tier 4: committee lifecycle ───

def convene_committee(request_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rating_committee(committee_payload(request_id, **overrides), CC)
    )


def open_session(committee_id: str) -> dict:
    return get_success_data(api_client.open_committee_session(committee_id, CC))


def cast_vote(committee_id: str, analyst: dict, vote_value: str = "AFFIRM",
              assigned_grade: str = "BAA", **overrides) -> dict:
    payload = vote_payload(analyst["id"], vote_value=vote_value,
                           assigned_grade=assigned_grade, **overrides)
    return get_success_data(
        api_client.cast_committee_vote(
            committee_id, payload, make_rating_analyst_headers(analyst["id"])
        )
    )


def decide_committee(committee_id: str, **overrides) -> dict:
    return get_success_data(api_client.decide_committee(committee_id, decide_payload(**overrides), CC))


def setup_committee_with_voters(required_voting_members: int = 2, committee_date: str = "2026-12-15T00:00:00Z",
                                fee_amount_cents: int = 10_000_000, **entity_overrides):
    """A TEAM_CONFIRMED request, an opened-session committee, and a cast of
    COMMITTEE_ELIGIBLE voters.

    Returns (entity, engagement, request, committee, voters, methodology).
    """
    entity, engagement, request, assignment, methodology = setup_request_ready_for_committee(
        fee_amount_cents=fee_amount_cents, **entity_overrides
    )
    voters = [onboard_committee_member("Dana Okafor"), onboard_committee_member("Marek Nowak")]
    committee = convene_committee(
        request["id"], committee_date=committee_date,
        required_voting_members=required_voting_members,
    )
    open_session(committee["id"])
    return entity, engagement, request, committee, voters, methodology


def setup_decided_committee(assigned_grade: str = "BAA", vote_value: str = "AFFIRM",
                            voter_grade: str = "BAA", decide_overrides=None, **entity_overrides):
    """Full pipeline through a committee DECISION.

    `decide_overrides` carries the decision payload fields (outlook,
    watch_status, rationale); `entity_overrides` are forwarded to the issuer
    registration only.

    Returns (entity, engagement, request, committee, voters, decision).
    """
    entity, engagement, request, committee, voters, _ = setup_committee_with_voters(**entity_overrides)
    cast_vote(committee["id"], voters[0], vote_value=vote_value, assigned_grade=voter_grade)
    cast_vote(committee["id"], voters[1], vote_value=vote_value, assigned_grade=voter_grade)
    decision = decide_committee(committee["id"], assigned_grade=assigned_grade, **(decide_overrides or {}))
    return entity, engagement, request, committee, voters, decision


def setup_decision_in_appeal_window(**overrides):
    """A decided committee whose decision sits inside its open appeal window.

    The appeal window is exclusive of its closing instant, and the logical clock
    stays at its default 2026-09-01 until a fixture moves it, so the window is
    opened and the clock then advanced a couple of days into it — that is what
    puts the decision genuinely inside the five-day interval an appeal is
    admissible in (PRD §3.5/§3.6).

    Returns (entity, engagement, request, committee, decision).
    """
    entity, engagement, request, committee, voters, decision = setup_decided_committee(**overrides)
    get_success_data(api_client.set_clock("2026-12-18T00:00:00Z", PA))
    decision = get_success_data(api_client.open_appeal_window(decision["id"], CC))
    return entity, engagement, request, committee, decision


def publish_decision(decision_id: str, request_id: str, **overrides) -> dict:
    """Publish a decision in APPEAL_WINDOW, supplying the observed request version."""
    version = get_success_data(api_client.get_rating_request(request_id, ANY))["version"]
    payload = {"expected_rating_request_version": version}
    payload.update(overrides)
    return get_success_data(api_client.publish_decision(decision_id, payload, CC))


def setup_published_rating(**overrides):
    """A fully published rating on an ACTIVE engagement.

    Returns (entity, engagement, request, committee, decision) with the entity
    carrying its grade and its auto-created SurveillanceReview.
    """
    entity, engagement, request, committee, decision = setup_decision_in_appeal_window(**overrides)
    decision = publish_decision(decision["id"], request["id"])
    return entity, engagement, request, committee, decision


# ─── Tier 5: surveillance and downstream artifacts ───

def create_review_for_entity(entity_id: str, analyst: dict, **overrides) -> dict:
    return get_success_data(
        api_client.create_surveillance_review(
            surveillance_review_payload(entity_id, **overrides),
            make_rating_analyst_headers(analyst["id"]),
        )
    )


def book_slot(analyst: dict, review_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_review_slot(
            review_slot_payload(analyst["id"], review_id, **overrides),
            make_rating_analyst_headers(analyst["id"]),
        )
    )


def create_compensation(analyst_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_compensation_record(compensation_payload(analyst_id, **overrides), COMP)
    )


def record_appearance(analyst_id: str, decision_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_appearance_reconciliation(
            appearance_reconciliation_payload(analyst_id, decision_id, **overrides), CO
        )
    )