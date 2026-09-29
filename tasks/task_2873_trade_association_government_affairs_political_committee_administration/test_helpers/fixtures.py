"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints only,
because each test runs against an empty database. Setup calls use the lenient
validator so that a broken precondition reports as a setup failure.
"""
from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    cast_vote_payload,
    create_activity_payload,
    create_campaign_payload,
    create_candidate_payload,
    create_committee_payload,
    create_contribution_payload,
    create_fund_payload,
    create_member_payload,
    create_policy_position_payload,
    create_prior_approval_payload,
    create_receipt_payload,
    create_registration_payload,
    create_report_payload,
    create_seat_payload,
    dispatch_alert_payload,
    filing_cycle_payload,
    grant_prior_approval_payload,
    void_payload,
)
from .test_users import TEST_USERS, make_member_delegate_headers

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
COMPLIANCE_2 = TEST_USERS["compliance_headers_2"]
TRUSTEE = TEST_USERS["trustee_headers"]
TRUSTEE_2 = TEST_USERS["trustee_headers_2"]


# ---------------------------------------------------------------- logical clock

def set_clock(to_iso8601: str) -> str:
    """Move the logical clock and return the resulting current_utc."""
    data = get_success_data(api_client.set_clock(to_iso8601, COMPLIANCE))
    return data.get("current_utc")


# ------------------------------------------------------- tier 1: single entities

def enroll_member(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_member(create_member_payload(**overrides), ADMIN)
    )


def create_committee(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_committee(create_committee_payload(**overrides), DIRECTOR)
    )


def seat_member(committee_id: str, member_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_committee_seat(
            committee_id, create_seat_payload(member_id, **overrides), DIRECTOR
        )
    )


def draft_position(committee_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_policy_position(
            create_policy_position_payload(committee_id, **overrides), DIRECTOR
        )
    )


def open_ballot_round(position_id: str, **payload) -> Dict[str, Any]:
    return get_success_data(api_client.open_ballot(position_id, DIRECTOR, payload or {}))


def cast_ballot(
    position_id: str, member_id: str, ballot: str = "SUPPORT", **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.cast_vote(
            position_id,
            cast_vote_payload(ballot, **overrides),
            make_member_delegate_headers(member_id),
        )
    )


def tally_round(position_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.tally_position(position_id, DIRECTOR))


def adopt_position(position_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.adopt_position(position_id, headers or TRUSTEE))


def register_candidate(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_candidate(create_candidate_payload(**overrides), DIRECTOR)
    )


def open_fund(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_segregated_fund(create_fund_payload(**overrides), COMPLIANCE)
    )


def request_prior_approval(member_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_prior_approval(
            create_prior_approval_payload(member_id, **overrides), COMPLIANCE
        )
    )


def grant_prior_approval(approval_id: str, member_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.grant_prior_approval(
            approval_id,
            grant_prior_approval_payload(**overrides),
            make_member_delegate_headers(member_id),
        )
    )


def credit_receipt(fund_id: str, member_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_fund_receipt(
            fund_id, create_receipt_payload(member_id, **overrides), COMPLIANCE
        )
    )


def run_filing_cycle(fund_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.run_filing_cycle(fund_id, filing_cycle_payload(**overrides), COMPLIANCE)
    )


def draft_registration(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_lobbying_registration(
            create_registration_payload(**overrides), COMPLIANCE
        )
    )


def file_registration(registration_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.file_registration(registration_id, COMPLIANCE))


def read_registration(registration_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_lobbying_registration(registration_id, COMPLIANCE)
    )


def registration_version(registration_id: str) -> int:
    return read_registration(registration_id)["version"]


def log_activity(registration_id: str, position_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_lobbying_activity(
            create_activity_payload(registration_id, position_id, **overrides), DIRECTOR
        )
    )


def void_activity(activity_id: str, void_reason: str = "Recorded in error") -> Dict[str, Any]:
    return get_success_data(
        api_client.void_lobbying_activity(activity_id, void_payload(void_reason), DIRECTOR)
    )


def open_report(
    registration_id: str,
    period_code: str = "2026Q3",
    basis: str = "METHOD_A",
    expected_registration_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open an expenditure report, reading the registration version when not given."""
    if expected_registration_version is None:
        expected_registration_version = registration_version(registration_id)
    return get_success_data(
        api_client.create_expenditure_report(
            create_report_payload(
                registration_id,
                expected_registration_version,
                period_code=period_code,
                basis=basis,
            ),
            headers or COMPLIANCE,
        )
    )


def certify_report(report_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_expenditure_report(report_id, headers or COMPLIANCE_2)
    )


def launch_campaign(position_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_grassroots_campaign(
            create_campaign_payload(position_id, **overrides), DIRECTOR
        )
    )


def dispatch_alert(campaign_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.dispatch_alert(campaign_id, dispatch_alert_payload(**overrides), DIRECTOR)
    )


def propose_contribution(
    fund_id: str,
    candidate_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pac_contribution(
            create_contribution_payload(fund_id, candidate_id, **overrides),
            headers or DIRECTOR,
        )
    )


def board_approve(contribution_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.board_approve_contribution(contribution_id, headers or TRUSTEE)
    )


def disburse(contribution_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.disburse_contribution(contribution_id, COMPLIANCE))


def void_contribution(
    contribution_id: str, void_reason: str = "Returned check"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.void_pac_contribution(contribution_id, void_payload(void_reason), COMPLIANCE)
    )


def read_committee(committee_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_committee(committee_id, DIRECTOR))


def read_position(position_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_policy_position(position_id, DIRECTOR))


def read_member(member_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def read_candidate(candidate_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_candidate(candidate_id, DIRECTOR))


def read_fund(fund_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_segregated_fund(fund_id, COMPLIANCE))


def read_contribution(contribution_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_pac_contribution(contribution_id, COMPLIANCE))


def read_campaign(campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_grassroots_campaign(campaign_id, DIRECTOR))


def read_seat(committee_id: str, seat_id: str) -> Dict[str, Any]:
    """Read one seat back off the committee roster listing."""
    data, _meta = _paginated(api_client.list_committee_seats(committee_id, DIRECTOR,
                                                            params={"limit": 100}))
    for row in data:
        if row["id"] == seat_id:
            return row
    raise AssertionError(f"Setup failed: seat {seat_id} is not on committee {committee_id}")


def read_vote(position_id: str, vote_id: str) -> Dict[str, Any]:
    data, _meta = _paginated(api_client.list_position_votes(position_id, DIRECTOR,
                                                            params={"limit": 100}))
    for row in data:
        if row["id"] == vote_id:
            return row
    raise AssertionError(f"Setup failed: vote {vote_id} is not on position {position_id}")


def read_report(registration_id: str, report_id: str) -> Dict[str, Any]:
    data, _meta = _paginated(
        api_client.list_registration_expenditure_reports(
            registration_id, COMPLIANCE, params={"limit": 100}
        )
    )
    for row in data:
        if row["id"] == report_id:
            return row
    raise AssertionError(f"Setup failed: report {report_id} not listed on {registration_id}")


def read_activity(registration_id: str, activity_id: str) -> Dict[str, Any]:
    data, _meta = _paginated(
        api_client.list_registration_activities(
            registration_id, COMPLIANCE, params={"limit": 100}
        )
    )
    for row in data:
        if row["id"] == activity_id:
            return row
    raise AssertionError(f"Setup failed: activity {activity_id} not listed on {registration_id}")


def read_notice(member_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_deductibility_notice(member_id, COMPLIANCE))


def _paginated(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    body = response.json()
    if not (200 <= response.status_code < 300):
        raise AssertionError(f"Setup listing failed with HTTP {response.status_code}: {body}")
    return body["data"], body["meta"]


# --------------------------------------------- tier 2: committees with a roster

CANONICAL_MEMBER_NAMES = (
    "Alpha Manufacturing Inc",
    "Beta Fabrication LLC",
    "Gamma Components Co",
    "Delta Tooling Group",
    "Echo Castings Ltd",
    "Foxtrot Alloys Inc",
)


def setup_committee_with_roster(
    tiers: Sequence[str] = ("PREMIER", "FULL", "ASSOCIATE"),
    engagement_scores: Optional[Sequence[int]] = None,
    restricted_class_sizes: Optional[Sequence[int]] = None,
    seat_roles: Optional[Sequence[Optional[str]]] = None,
    home_jurisdiction_code: str = "FEDERAL",
    home_district_code: str = "CA-12",
    annual_dues_cents: int = 400_000,
    dues_year: int = 2026,
    jurisdiction_scope: Optional[str] = None,
    quorum_threshold_pct: float = 60.00,
    consensus_threshold_pct: float = 66.67,
    committee_name: str = "Federal Tax Policy Committee",
) -> Dict[str, Any]:
    """Enroll one member per tier and seat each of them on a new committee.

    The default roster is PREMIER, FULL and ASSOCIATE — three seats carrying
    three, two and one unit of weight, so six units in total and a QUORATE
    roster. Returns {"committee", "members", "seats"}.
    """
    engagement_scores = engagement_scores or [90, 70, 50, 40, 30, 20][: len(tiers)]
    restricted_class_sizes = restricted_class_sizes or [25, 15, 5, 5, 5, 5][: len(tiers)]
    seat_roles = seat_roles or (["CHAIR"] + [None] * (len(tiers) - 1))

    committee = create_committee(
        name=committee_name,
        jurisdiction_scope=jurisdiction_scope or home_jurisdiction_code,
        quorum_threshold_pct=quorum_threshold_pct,
        consensus_threshold_pct=consensus_threshold_pct,
    )
    members: List[Dict[str, Any]] = []
    seats: List[Dict[str, Any]] = []
    for index, tier in enumerate(tiers):
        member = enroll_member(
            legal_name=CANONICAL_MEMBER_NAMES[index],
            membership_tier=tier,
            home_jurisdiction_code=home_jurisdiction_code,
            home_district_code=home_district_code,
            annual_dues_cents=annual_dues_cents,
            dues_year=dues_year,
            restricted_class_size=restricted_class_sizes[index],
            engagement_score=engagement_scores[index],
        )
        members.append(member)
        role = seat_roles[index] if index < len(seat_roles) else None
        overrides = {"seat_role": role} if role else {}
        seats.append(seat_member(committee["id"], member["id"], **overrides))
    return {"committee": read_committee(committee["id"]), "members": members, "seats": seats}


def setup_quorate_committee(**overrides) -> Dict[str, Any]:
    """PREMIER + FULL + ASSOCIATE: three seats, six units of weight, QUORATE."""
    return setup_committee_with_roster(**overrides)


def setup_impaired_committee(**overrides) -> Dict[str, Any]:
    """Three ASSOCIATE members: three seats but only three units of weight."""
    overrides.setdefault("tiers", ("ASSOCIATE", "ASSOCIATE", "ASSOCIATE"))
    return setup_committee_with_roster(**overrides)


def setup_forming_committee(**overrides) -> Dict[str, Any]:
    """Two seats only, so the roster is still FORMING."""
    overrides.setdefault("tiers", ("PREMIER", "FULL"))
    return setup_committee_with_roster(**overrides)


# ------------------------------- tier 3: the ballot cycle through to adoption

def setup_position_in_balloting(
    roster: Optional[Dict[str, Any]] = None,
    position_overrides: Optional[Dict[str, Any]] = None,
    ballot_deadline_date: Optional[str] = None,
    **roster_overrides,
) -> Dict[str, Any]:
    """Quorate roster + a drafted position with its first round open."""
    roster = roster or setup_quorate_committee(**roster_overrides)
    position = draft_position(roster["committee"]["id"], **(position_overrides or {}))
    payload = {"ballot_deadline_date": ballot_deadline_date} if ballot_deadline_date else {}
    position = open_ballot_round(position["id"], **payload)
    return {**roster, "position": position}


def cast_ballots(
    position_id: str,
    members: Sequence[Dict[str, Any]],
    ballots: Sequence[str],
    dissent_statements: Optional[Sequence[Optional[str]]] = None,
) -> List[Dict[str, Any]]:
    """Cast one ballot per member, in the order given."""
    votes: List[Dict[str, Any]] = []
    for index, ballot in enumerate(ballots):
        overrides: Dict[str, Any] = {}
        if dissent_statements and index < len(dissent_statements) and dissent_statements[index]:
            overrides["dissent_statement"] = dissent_statements[index]
        votes.append(cast_ballot(position_id, members[index]["id"], ballot, **overrides))
    return votes


def setup_position_at_consensus(
    ballots: Sequence[str] = ("SUPPORT", "SUPPORT", "OPPOSE"),
    dissent_statements: Optional[Sequence[Optional[str]]] = None,
    roster: Optional[Dict[str, Any]] = None,
    position_overrides: Optional[Dict[str, Any]] = None,
    **roster_overrides,
) -> Dict[str, Any]:
    """Open a round, cast the given ballots and tally into CONSENSUS_REACHED.

    With the default roster and ballots the participation is the full six units
    of weight and support is five of the six that took a side, so the round
    reaches consensus. Returns the roster keys plus "position" and "votes".
    """
    state = setup_position_in_balloting(
        roster=roster, position_overrides=position_overrides, **roster_overrides
    )
    votes = cast_ballots(state["position"]["id"], state["members"], ballots, dissent_statements)
    position = tally_round(state["position"]["id"])
    return {**state, "position": position, "votes": votes}


def setup_adopted_position(
    ballots: Sequence[str] = ("SUPPORT", "SUPPORT", "OPPOSE"),
    dissent_statements: Optional[Sequence[Optional[str]]] = None,
    roster: Optional[Dict[str, Any]] = None,
    position_overrides: Optional[Dict[str, Any]] = None,
    adopt_headers: Optional[Dict[str, str]] = None,
    **roster_overrides,
) -> Dict[str, Any]:
    """Carry a position all the way to ADOPTED, which is what unlocks the
    outward-facing work: lobbying activity and grassroots campaigns."""
    state = setup_position_at_consensus(
        ballots=ballots,
        dissent_statements=dissent_statements,
        roster=roster,
        position_overrides=position_overrides,
        **roster_overrides,
    )
    position = adopt_position(state["position"]["id"], adopt_headers)
    return {**state, "position": position}


# ------------------------------- tier 3: registrations, activities and reports

def setup_active_registration(**overrides) -> Dict[str, Any]:
    """Draft a registration and file it, so that activity may be logged."""
    registration = draft_registration(**overrides)
    return file_registration(registration["id"])


def setup_registration_with_adopted_position(
    registration_overrides: Optional[Dict[str, Any]] = None,
    position_jurisdiction_code: str = "FEDERAL",
    **adopted_overrides,
) -> Dict[str, Any]:
    """An ACTIVE registration plus an ADOPTED position under a quorate committee.

    This is the shared preamble of every lobbying-activity scenario. Returns the
    adopted-position keys plus "registration".
    """
    overrides = dict(registration_overrides or {})
    overrides.setdefault("jurisdiction_code", position_jurisdiction_code)
    position_overrides = adopted_overrides.pop("position_overrides", {}) or {}
    position_overrides.setdefault("jurisdiction_code", position_jurisdiction_code)
    adopted_overrides.setdefault("home_jurisdiction_code", position_jurisdiction_code)
    state = setup_adopted_position(position_overrides=position_overrides, **adopted_overrides)
    registration = setup_active_registration(**overrides)
    return {**state, "registration": registration}


def setup_registration_with_activities(
    activities: Sequence[Dict[str, Any]],
    registration_overrides: Optional[Dict[str, Any]] = None,
    position_jurisdiction_code: str = "FEDERAL",
    **adopted_overrides,
) -> Dict[str, Any]:
    """ACTIVE registration + ADOPTED position + one logged activity per spec."""
    state = setup_registration_with_adopted_position(
        registration_overrides=registration_overrides,
        position_jurisdiction_code=position_jurisdiction_code,
        **adopted_overrides,
    )
    logged = [
        log_activity(state["registration"]["id"], state["position"]["id"], **spec)
        for spec in activities
    ]
    return {**state, "activities": logged,
            "registration": read_registration(state["registration"]["id"])}


def setup_open_report_with_activities(
    activities: Sequence[Dict[str, Any]],
    period_code: str = "2026Q3",
    basis: str = "METHOD_A",
    registration_overrides: Optional[Dict[str, Any]] = None,
    position_jurisdiction_code: str = "FEDERAL",
    **adopted_overrides,
) -> Dict[str, Any]:
    """Log the activities first, then open a report over their period."""
    state = setup_registration_with_activities(
        activities,
        registration_overrides=registration_overrides,
        position_jurisdiction_code=position_jurisdiction_code,
        **adopted_overrides,
    )
    report = open_report(state["registration"]["id"], period_code=period_code, basis=basis)
    return {**state, "report": report,
            "registration": read_registration(state["registration"]["id"])}


# ------------------------- tier 4: PAC eligibility, the fund and contributions

def setup_granted_prior_approval(
    member: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    authorized_by_name: str = "Dana Reyes, General Counsel",
    **approval_overrides,
) -> Dict[str, Any]:
    """Enroll a member, request its PAC prior approval and have the member grant it.

    Only the member itself can grant, so the grant call is made with the
    member's own identity. Returns {"member", "approval"}.
    """
    member = member or enroll_member(**(member_overrides or {}))
    approval = request_prior_approval(member["id"], **approval_overrides)
    approval = grant_prior_approval(
        approval["id"], member["id"], authorized_by_name=authorized_by_name
    )
    return {"member": member, "approval": approval}


def setup_funded_fund(
    min_reserve_cents: int = 100_000,
    receipt_amount_cents: int = 600_000,
    received_date: str = "2026-08-01",
    fund_overrides: Optional[Dict[str, Any]] = None,
    member: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    solicitable_class_size: int = 5,
) -> Dict[str, Any]:
    """A fund holding one credited receipt from a member whose approval is GRANTED.

    Returns {"fund", "member", "approval"}.
    """
    approved = setup_granted_prior_approval(
        member=member,
        member_overrides=member_overrides,
        solicitable_class_size=solicitable_class_size,
    )
    fund = open_fund(**{"min_reserve_cents": min_reserve_cents, **(fund_overrides or {})})
    fund = credit_receipt(
        fund["id"],
        approved["member"]["id"],
        amount_cents=receipt_amount_cents,
        received_date=received_date,
    )
    return {"fund": fund, "member": approved["member"], "approval": approved["approval"]}


def setup_pending_contribution(
    amount_cents: int = 250_000,
    min_reserve_cents: int = 400_000,
    receipt_amount_cents: int = 600_000,
    candidate_overrides: Optional[Dict[str, Any]] = None,
    fund_overrides: Optional[Dict[str, Any]] = None,
    propose_headers: Optional[Dict[str, str]] = None,
    **contribution_overrides,
) -> Dict[str, Any]:
    """A funded fund, a registered candidate and one PENDING_BOARD contribution.

    Returns {"fund", "member", "approval", "candidate", "contribution"}.
    """
    funded = setup_funded_fund(
        min_reserve_cents=min_reserve_cents,
        receipt_amount_cents=receipt_amount_cents,
        fund_overrides=fund_overrides,
    )
    candidate = register_candidate(**(candidate_overrides or {}))
    contribution = propose_contribution(
        funded["fund"]["id"],
        candidate["id"],
        headers=propose_headers,
        amount_cents=amount_cents,
        **contribution_overrides,
    )
    return {
        **funded,
        "candidate": candidate,
        "contribution": contribution,
        "fund": read_fund(funded["fund"]["id"]),
    }


def setup_board_approved_contribution(**overrides) -> Dict[str, Any]:
    """Carry one contribution through board approval."""
    approve_headers = overrides.pop("approve_headers", None)
    state = setup_pending_contribution(**overrides)
    contribution = board_approve(state["contribution"]["id"], approve_headers)
    return {**state, "contribution": contribution, "fund": read_fund(state["fund"]["id"])}


def setup_disbursed_contribution(**overrides) -> Dict[str, Any]:
    """Carry one contribution through board approval and disbursement."""
    state = setup_board_approved_contribution(**overrides)
    contribution = disburse(state["contribution"]["id"])
    return {**state, "contribution": contribution, "fund": read_fund(state["fund"]["id"])}


def setup_suspended_contribution(
    first_amount_cents: int = 250_000,
    second_amount_cents: int = 250_000,
    min_reserve_cents: int = 400_000,
    receipt_amount_cents: int = 600_000,
) -> Dict[str, Any]:
    """Two pending contributions on one fund; approving the first restricts the
    fund's posture, which suspends the second.

    Returns {"fund", "member", "approval", "candidate_a", "candidate_b",
    "contribution_x", "contribution_y"}.
    """
    funded = setup_funded_fund(
        min_reserve_cents=min_reserve_cents, receipt_amount_cents=receipt_amount_cents
    )
    candidate_a = register_candidate(name="Jordan Ellis")
    candidate_b = register_candidate(name="Rowan Pierce")
    contribution_x = propose_contribution(
        funded["fund"]["id"], candidate_a["id"], amount_cents=first_amount_cents
    )
    contribution_y = propose_contribution(
        funded["fund"]["id"], candidate_b["id"], amount_cents=second_amount_cents
    )
    contribution_x = board_approve(contribution_x["id"])
    return {
        **funded,
        "fund": read_fund(funded["fund"]["id"]),
        "candidate_a": candidate_a,
        "candidate_b": candidate_b,
        "contribution_x": contribution_x,
        "contribution_y": read_contribution(contribution_y["id"]),
    }


# ------------------------------------- tier 5: grassroots campaigns and alerts

def setup_campaign_on_adopted_position(
    campaign_overrides: Optional[Dict[str, Any]] = None,
    **adopted_overrides,
) -> Dict[str, Any]:
    """An ADOPTED position plus a PLANNED campaign advancing it.

    The roster members share the committee and a home district, so an alert
    aimed at that district matches them all. Returns the adopted-position keys
    plus "campaign".
    """
    jurisdiction = adopted_overrides.pop("jurisdiction_code", "FEDERAL")
    position_overrides = adopted_overrides.pop("position_overrides", {}) or {}
    position_overrides.setdefault("jurisdiction_code", jurisdiction)
    adopted_overrides.setdefault("home_jurisdiction_code", jurisdiction)
    state = setup_adopted_position(position_overrides=position_overrides, **adopted_overrides)
    overrides = dict(campaign_overrides or {})
    overrides.setdefault("target_jurisdiction_code", jurisdiction)
    campaign = launch_campaign(state["position"]["id"], **overrides)
    return {**state, "campaign": campaign}


def setup_live_campaign(
    alert_overrides: Optional[Dict[str, Any]] = None,
    campaign_overrides: Optional[Dict[str, Any]] = None,
    **adopted_overrides,
) -> Dict[str, Any]:
    """A campaign whose first alert matched, so the campaign has moved to LIVE.

    Returns the campaign keys plus "alert".
    """
    state = setup_campaign_on_adopted_position(
        campaign_overrides=campaign_overrides, **adopted_overrides
    )
    alert = dispatch_alert(state["campaign"]["id"], **(alert_overrides or {}))
    return {**state, "alert": alert, "campaign": read_campaign(state["campaign"]["id"])}


def setup_certified_report(
    activities: Sequence[Dict[str, Any]],
    period_code: str = "2026Q3",
    basis: str = "METHOD_A",
    certify_on: str = "2026-10-01T00:00:00Z",
    certify_headers: Optional[Dict[str, str]] = None,
    registration_overrides: Optional[Dict[str, Any]] = None,
    position_jurisdiction_code: str = "FEDERAL",
    **adopted_overrides,
) -> Dict[str, Any]:
    """Open a report, move the clock past the period end and certify it.

    Certification is performed by a different compliance officer than the one
    that opened the report. Returns the report keys plus the certified "report".
    """
    state = setup_open_report_with_activities(
        activities,
        period_code=period_code,
        basis=basis,
        registration_overrides=registration_overrides,
        position_jurisdiction_code=position_jurisdiction_code,
        **adopted_overrides,
    )
    set_clock(certify_on)
    report = certify_report(state["report"]["id"], certify_headers)
    return {**state, "report": report}
