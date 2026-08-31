"""Composite setup helpers.

Every helper builds its preconditions from scratch through published endpoints,
because each test starts against an empty database with the logical clock at its
2026-08-01T00:00:00Z start position.
"""

from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LONG_TERM_END, LONG_TERM_START, TRUSTEE_ROSTER
from .factories import (
    agenda_item_payload,
    board_member_payload,
    committee_assignment_payload,
    committee_payload,
    conflict_disclosure_payload,
    legal_mandate_payload,
    manual_publication_payload,
    meeting_payload,
    policy_payload,
    policy_version_payload,
    public_comment_payload,
    superintendent_evaluation_payload,
    evaluation_rating_payload,
    vote_payload,
    waiver_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_board_member_headers,
    make_board_president_headers,
)

CLERK = TEST_USERS["board_clerk_headers"]
ANALYST = TEST_USERS["policy_analyst_headers"]
SUPT = TEST_USERS["superintendent_headers"]
PRINCIPAL = TEST_USERS["school_principal_headers"]
LUS = TEST_USERS["legal_update_service_headers"]
PUBLIC = TEST_USERS["public_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock. Mutates no entity."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, CLERK))


# ---------------------------------------------------------------------------
# Roster and committees
# ---------------------------------------------------------------------------


def seat_trustee(
    full_name: str,
    seat_number: int,
    office: Optional[str] = None,
    term_start_date: str = LONG_TERM_START,
    term_end_date: str = LONG_TERM_END,
    employer_name: str = "Independent",
) -> dict:
    payload = board_member_payload(
        full_name=full_name,
        seat_number=seat_number,
        term_start_date=term_start_date,
        term_end_date=term_end_date,
        employer_name=employer_name,
    )
    if office is not None:
        payload["office"] = office
    return get_success_data(api_client.create_board_member(payload, CLERK))


def seat_board(count: int = 3, term_end_dates: Optional[List[str]] = None) -> List[dict]:
    """Seat `count` trustees; the first holds office PRESIDENT.

    `term_end_dates`, when supplied, overrides the term end of the trustee at
    the same index so term-expiry scenarios can be built.
    """
    members = []
    for index in range(count):
        name, employer = TRUSTEE_ROSTER[index]
        term_end = LONG_TERM_END
        if term_end_dates and index < len(term_end_dates) and term_end_dates[index]:
            term_end = term_end_dates[index]
        members.append(
            seat_trustee(
                full_name=name,
                seat_number=index + 1,
                office="PRESIDENT" if index == 0 else None,
                term_end_date=term_end,
                employer_name=employer,
            )
        )
    return members


def resign_trustee(member_id: str) -> dict:
    return get_success_data(api_client.resign_board_member(member_id, CLERK))


def charter_committee(
    name: str = "Policy Committee",
    charter_type: str = "POLICY",
    seat_capacity: int = 3,
    quorum_size: int = 2,
) -> dict:
    return get_success_data(
        api_client.create_committee(
            committee_payload(
                name=name,
                charter_type=charter_type,
                seat_capacity=seat_capacity,
                quorum_size=quorum_size,
            ),
            CLERK,
        )
    )


def seat_on_committee(committee_id: str, board_member_id: str, role_on_committee: Optional[str] = None) -> dict:
    payload = committee_assignment_payload(committee_id, board_member_id)
    if role_on_committee is not None:
        payload["role_on_committee"] = role_on_committee
    return get_success_data(api_client.create_committee_assignment(payload, CLERK))


def change_assignment_status(assignment_id: str, action: str) -> dict:
    return get_success_data(
        api_client.set_committee_assignment_status(assignment_id, {"action": action}, CLERK)
    )


def read_committee(committee_id: str) -> dict:
    return get_success_data(api_client.get_committee(committee_id, CLERK))


def setup_active_committee(members: List[dict], **overrides) -> dict:
    """Charter a committee and seat two trustees on it (first as CHAIR), so it is ACTIVE.

    Returns {"committee", "chair_assignment", "member_assignment", "chair", "member"}.
    """
    committee = charter_committee(**overrides)
    chair_assignment = seat_on_committee(committee["id"], members[1]["id"], "CHAIR")
    member_assignment = seat_on_committee(committee["id"], members[2]["id"], "MEMBER")
    return {
        "committee": read_committee(committee["id"]),
        "chair_assignment": chair_assignment,
        "member_assignment": member_assignment,
        "chair": members[1],
        "member": members[2],
    }


# ---------------------------------------------------------------------------
# Policies, versions, mandates, disclosures
# ---------------------------------------------------------------------------


def register_policy(
    code: str = "BP-4119",
    title: str = "Employee Conflict of Interest",
    category: str = "PERSONNEL",
    legal_requirement_level: str = "REQUIRED_BY_LAW",
    manual_section: str = "4000.19",
) -> dict:
    return get_success_data(
        api_client.create_policy(
            policy_payload(
                code=code,
                title=title,
                category=category,
                legal_requirement_level=legal_requirement_level,
                manual_section=manual_section,
            ),
            ANALYST,
        )
    )


def read_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_policy(policy_id, ANALYST))


def draft_version(
    policy_id: str,
    expected_policy_version: int,
    body_text: str = "Version one text.",
    summary_of_change: str = "Initial adoption draft",
    headers=None,
) -> dict:
    return get_success_data(
        api_client.create_policy_version(
            policy_id,
            policy_version_payload(
                expected_policy_version,
                body_text=body_text,
                summary_of_change=summary_of_change,
            ),
            headers or ANALYST,
        )
    )


def setup_policy_with_draft(
    code: str = "BP-4119",
    title: str = "Employee Conflict of Interest",
    category: str = "PERSONNEL",
    legal_requirement_level: str = "REQUIRED_BY_LAW",
    manual_section: str = "4000.19",
    body_text: str = "Version one text.",
    summary_of_change: str = "Initial adoption draft",
):
    """Register a policy and draft its first version. Returns (policy, version)."""
    policy = register_policy(code, title, category, legal_requirement_level, manual_section)
    version = draft_version(
        policy["id"], policy["version"], body_text=body_text, summary_of_change=summary_of_change
    )
    return policy, version


def read_policy_version(version_id: str) -> dict:
    return get_success_data(api_client.get_policy_version(version_id, ANALYST))


def withdraw_version(version_id: str, withdrawn_reason: str = "Counsel asked for a rewrite.") -> dict:
    return get_success_data(
        api_client.withdraw_policy_version(version_id, {"withdrawn_reason": withdrawn_reason}, ANALYST)
    )


def file_mandate(
    policy_id: str,
    notice_code: str = "LUS-2026-014",
    citation: str = "EC 35291",
    issued_on: str = "2026-08-01T00:00:00Z",
    compliance_deadline: str = "2026-12-01T00:00:00Z",
    required_action: str = "REVISE_EXISTING",
) -> dict:
    return get_success_data(
        api_client.create_legal_mandate(
            legal_mandate_payload(
                policy_id,
                notice_code=notice_code,
                citation=citation,
                issued_on=issued_on,
                compliance_deadline=compliance_deadline,
                required_action=required_action,
            ),
            LUS,
        )
    )


def read_mandate(mandate_id: str) -> dict:
    return get_success_data(api_client.get_legal_mandate(mandate_id, LUS))


def file_disclosure(
    board_member_id: str,
    policy_id: str,
    nature: str = "FINANCIAL",
    narrative: str = "Spouse holds equity in the benefits vendor named in this policy.",
) -> dict:
    return get_success_data(
        api_client.create_conflict_disclosure(
            conflict_disclosure_payload(
                board_member_id, policy_id, nature=nature, narrative=narrative
            ),
            make_board_member_headers(board_member_id),
        )
    )


def read_disclosure(disclosure_id: str) -> dict:
    return get_success_data(api_client.get_conflict_disclosure(disclosure_id, PUBLIC))


def clear_disclosure(disclosure_id: str, president_id: str) -> dict:
    return get_success_data(
        api_client.clear_conflict_disclosure(
            disclosure_id, make_board_president_headers(president_id)
        )
    )


def read_board_member(member_id: str) -> dict:
    return get_success_data(api_client.get_board_member(member_id, CLERK))


# ---------------------------------------------------------------------------
# Meetings, agendas, notices, votes
# ---------------------------------------------------------------------------


def schedule_meeting(
    title: str = "September Regular Meeting",
    scope: str = "FULL_BOARD",
    meeting_type: str = "REGULAR",
    scheduled_start_utc: str = "2026-09-10T18:00:00Z",
    committee_id: Optional[str] = None,
    public_comment_rule: Optional[str] = None,
) -> dict:
    payload = meeting_payload(
        title=title,
        scope=scope,
        meeting_type=meeting_type,
        scheduled_start_utc=scheduled_start_utc,
    )
    if committee_id is not None:
        payload["committee_id"] = committee_id
    if public_comment_rule is not None:
        payload["public_comment_rule"] = public_comment_rule
    return get_success_data(api_client.create_meeting(payload, CLERK))


def read_meeting(meeting_id: str) -> dict:
    return get_success_data(api_client.get_meeting(meeting_id, CLERK))


def add_agenda_item(
    meeting_id: str,
    expected_meeting_version: int,
    item_type: str = "CONSENT",
    title: str = "Approve warrants",
    policy_version_id: Optional[str] = None,
    waiver_request_id: Optional[str] = None,
) -> dict:
    payload = agenda_item_payload(
        meeting_id, expected_meeting_version, item_type=item_type, title=title
    )
    if policy_version_id is not None:
        payload["policy_version_id"] = policy_version_id
    if waiver_request_id is not None:
        payload["waiver_request_id"] = waiver_request_id
    return get_success_data(api_client.create_agenda_item(payload, CLERK))


def read_agenda_item(item_id: str) -> dict:
    return get_success_data(api_client.get_agenda_item(item_id, CLERK))


def post_notice(meeting_id: str) -> dict:
    return get_success_data(api_client.post_meeting_notice(meeting_id, CLERK))


def open_meeting(meeting_id: str, attending_member_ids: List[str], president_id: str) -> dict:
    return get_success_data(
        api_client.open_meeting(
            meeting_id,
            {"attending_member_ids": list(attending_member_ids)},
            make_board_president_headers(president_id),
        )
    )


def adjourn_meeting(meeting_id: str) -> dict:
    return get_success_data(api_client.adjourn_meeting(meeting_id, CLERK))


def draft_minutes(meeting_id: str) -> dict:
    return get_success_data(api_client.advance_minutes(meeting_id, {"action": "DRAFT"}, CLERK))


def approve_minutes(meeting_id: str, approving_meeting_id: str) -> dict:
    return get_success_data(
        api_client.advance_minutes(
            meeting_id,
            {"action": "APPROVE", "approving_meeting_id": approving_meeting_id},
            CLERK,
        )
    )


def record_vote(
    item_id: str,
    president_id: str,
    yes_member_ids=None,
    no_member_ids=None,
    abstain_member_ids=None,
) -> dict:
    return get_success_data(
        api_client.record_vote(
            item_id,
            vote_payload(yes_member_ids, no_member_ids, abstain_member_ids),
            make_board_president_headers(president_id),
        )
    )


def file_speaker_card(
    item_id: str,
    speaker_name: str,
    speaker_affiliation: str = "PARENT",
    requested_minutes: int = 3,
    headers=None,
) -> dict:
    return get_success_data(
        api_client.create_public_comment(
            item_id,
            public_comment_payload(
                speaker_name=speaker_name,
                speaker_affiliation=speaker_affiliation,
                requested_minutes=requested_minutes,
            ),
            headers or PUBLIC,
        )
    )


def read_speaker_card(item_id: str, card_id: str) -> dict:
    cards, _meta = _paginated(api_client.list_public_comments(item_id, PUBLIC, {"limit": 100}))
    for card in cards:
        if card["id"] == card_id:
            return card
    raise AssertionError(f"speaker card {card_id} not found on agenda item {item_id}")


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------


def file_waiver(
    policy_id: str,
    reviewing_committee_id: str,
    requesting_school_code: str = "HS-01",
    justification: str = "Block schedule pilot",
    requested_start_date: str = "2026-10-01T00:00:00Z",
    requested_end_date: str = "2026-11-01T00:00:00Z",
) -> dict:
    return get_success_data(
        api_client.create_waiver_request(
            waiver_request_payload(
                policy_id,
                reviewing_committee_id,
                requesting_school_code=requesting_school_code,
                justification=justification,
                requested_start_date=requested_start_date,
                requested_end_date=requested_end_date,
            ),
            PRINCIPAL,
        )
    )


def read_waiver(waiver_id: str) -> dict:
    return get_success_data(api_client.get_waiver_request(waiver_id, PUBLIC))


def recommend_waiver(waiver_id: str, chair_id: str, recommendation: str = "RECOMMEND_GRANT") -> dict:
    return get_success_data(
        api_client.record_committee_recommendation(
            waiver_id, {"recommendation": recommendation}, make_board_member_headers(chair_id)
        )
    )


def revoke_waiver(waiver_id: str, headers=None) -> dict:
    return get_success_data(api_client.revoke_waiver_request(waiver_id, headers or SUPT))


# ---------------------------------------------------------------------------
# Superintendent evaluation
# ---------------------------------------------------------------------------


def open_evaluation(cycle_year: int = 2027, **overrides) -> dict:
    payload = superintendent_evaluation_payload(cycle_year=cycle_year, **overrides)
    return get_success_data(api_client.create_superintendent_evaluation(payload, CLERK))


def read_evaluation(evaluation_id: str) -> dict:
    return get_success_data(api_client.get_superintendent_evaluation(evaluation_id, CLERK))


def advance_evaluation(evaluation_id: str, president_id: str, action: str) -> dict:
    return get_success_data(
        api_client.advance_superintendent_evaluation(
            evaluation_id, {"action": action}, make_board_president_headers(president_id)
        )
    )


def submit_rating(
    evaluation_id: str,
    board_member_id: str,
    domain: str,
    score: int,
    comments: Optional[str] = None,
) -> dict:
    payload = evaluation_rating_payload(
        evaluation_id, board_member_id, domain=domain, score=score
    )
    if comments is not None:
        payload["comments"] = comments
    return get_success_data(
        api_client.create_evaluation_rating(payload, make_board_member_headers(board_member_id))
    )


def setup_evaluation_in_goals_set(members: List[dict], cycle_year: int = 2027, **overrides) -> dict:
    """Open a cycle and advance it to GOALS_SET so ratings are accepted."""
    evaluation = open_evaluation(cycle_year=cycle_year, **overrides)
    advance_evaluation(evaluation["id"], members[0]["id"], "SET_GOALS")
    return read_evaluation(evaluation["id"])


# ---------------------------------------------------------------------------
# Manual publication and the compliance sweep
# ---------------------------------------------------------------------------


def start_edition(publication_label: str = "2026-FALL", as_of_date: str = "2026-08-01T00:00:00Z") -> dict:
    return get_success_data(
        api_client.create_manual_publication(
            manual_publication_payload(publication_label=publication_label, as_of_date=as_of_date),
            ANALYST,
        )
    )


def publish_edition(publication_id: str) -> dict:
    return get_success_data(api_client.publish_manual_publication(publication_id, ANALYST))


def read_edition(publication_id: str) -> dict:
    return get_success_data(api_client.get_manual_publication(publication_id, ANALYST))


def run_sweep(headers=None) -> dict:
    return get_success_data(api_client.run_compliance_sweep(headers or CLERK))


# ---------------------------------------------------------------------------
# Composite scenarios reused across many tests
# ---------------------------------------------------------------------------


def setup_meeting_with_item_and_cards(
    item_type: str = "POLICY_FIRST_READING",
    item_title: str = "First reading",
    policy_version_id: Optional[str] = None,
    waiver_request_id: Optional[str] = None,
    meeting_title: str = "September Regular Meeting",
    meeting_type: str = "REGULAR",
    scheduled_start_utc: str = "2026-09-10T18:00:00Z",
    public_comment_rule: Optional[str] = None,
    cards: Optional[List[dict]] = None,
    post_the_notice: bool = True,
):
    """Schedule a meeting, list one item on it, file speaker cards, then notice it.

    Each entry in `cards` is {"speaker_name", "speaker_affiliation",
    "requested_minutes", "clock_before"}; `clock_before`, when present, moves the
    logical clock first so the card's submitted_at is strictly later than the
    previous card's. Returns (meeting, item, card_rows).
    """
    meeting = schedule_meeting(
        title=meeting_title,
        meeting_type=meeting_type,
        scheduled_start_utc=scheduled_start_utc,
        public_comment_rule=public_comment_rule,
    )
    item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type=item_type,
        title=item_title,
        policy_version_id=policy_version_id,
        waiver_request_id=waiver_request_id,
    )
    card_rows = []
    for card in cards or []:
        if card.get("clock_before"):
            set_clock(card["clock_before"])
        card_rows.append(
            file_speaker_card(
                item["id"],
                card["speaker_name"],
                card.get("speaker_affiliation", "PARENT"),
                card.get("requested_minutes", 3),
            )
        )
    if post_the_notice:
        post_notice(meeting["id"])
    return read_meeting(meeting["id"]), item, card_rows


def setup_open_meeting_with_first_reading(
    members: List[dict],
    policy_version_id: str,
    meeting_type: str = "REGULAR",
    scheduled_start_utc: str = "2026-09-10T18:00:00Z",
    meeting_title: str = "September Regular Meeting",
    item_title: str = "First reading",
    attending: Optional[List[str]] = None,
):
    """Notice a meeting carrying one first-reading item, move the clock to its
    start instant and call it to order. Returns (meeting, item)."""
    meeting, item, _cards = setup_meeting_with_item_and_cards(
        item_type="POLICY_FIRST_READING",
        item_title=item_title,
        policy_version_id=policy_version_id,
        meeting_title=meeting_title,
        meeting_type=meeting_type,
        scheduled_start_utc=scheduled_start_utc,
    )
    set_clock(scheduled_start_utc)
    attending_ids = attending if attending is not None else [m["id"] for m in members]
    opened = open_meeting(meeting["id"], attending_ids, members[0]["id"])
    return opened, item


def setup_emergency_adoption(
    members: List[dict],
    policy_version_id: str,
    scheduled_start_utc: str = "2026-08-02T18:00:00Z",
    meeting_title: str = "Emergency Board Meeting",
    item_title: str = "Emergency first reading",
):
    """Adopt a DRAFT version outright at an EMERGENCY meeting by unanimous vote.

    Returns (meeting, item). The clock is left at the meeting's start instant.
    """
    meeting, item = setup_open_meeting_with_first_reading(
        members,
        policy_version_id,
        meeting_type="EMERGENCY",
        scheduled_start_utc=scheduled_start_utc,
        meeting_title=meeting_title,
        item_title=item_title,
    )
    record_vote(item["id"], members[0]["id"], yes_member_ids=[m["id"] for m in members])
    return read_meeting(meeting["id"]), read_agenda_item(item["id"])


def setup_second_reading_stage(
    members: List[dict],
    policy: dict,
    version: dict,
    first_meeting_start: str = "2026-09-10T18:00:00Z",
    second_meeting_start: str = "2026-09-24T18:00:00Z",
    first_yes=None,
    first_no=None,
    first_abstain=None,
    approve_first_minutes: bool = True,
):
    """Walk a version through a passing first reading at meeting M1, adjourn M1,
    draft its minutes, then open meeting M2 carrying the POSTED second-reading
    item -- optionally approving M1's minutes at M2.

    Returns {"m1", "ai1", "m2", "ai2"}. The clock is left at M2's start instant.
    """
    ids = [m["id"] for m in members]
    m1, ai1 = setup_open_meeting_with_first_reading(
        members,
        version["id"],
        scheduled_start_utc=first_meeting_start,
        meeting_title="September Regular Meeting",
        item_title=f"First reading {policy['code']}",
    )
    record_vote(
        ai1["id"],
        members[0]["id"],
        yes_member_ids=first_yes if first_yes is not None else ids[:2],
        no_member_ids=first_no if first_no is not None else ids[2:3],
        abstain_member_ids=first_abstain or [],
    )
    adjourn_meeting(m1["id"])
    draft_minutes(m1["id"])

    m2 = schedule_meeting(
        title="Late September Regular Meeting", scheduled_start_utc=second_meeting_start
    )
    ai2 = add_agenda_item(
        m2["id"],
        m2["version"],
        item_type="POLICY_SECOND_READING",
        title=f"Second reading {policy['code']}",
        policy_version_id=version["id"],
    )
    post_notice(m2["id"])
    set_clock(second_meeting_start)
    open_meeting(m2["id"], ids, members[0]["id"])
    if approve_first_minutes:
        approve_minutes(m1["id"], m2["id"])
    return {
        "m1": read_meeting(m1["id"]),
        "ai1": read_agenda_item(ai1["id"]),
        "m2": read_meeting(m2["id"]),
        "ai2": read_agenda_item(ai2["id"]),
    }


def setup_granted_waiver(
    members: List[dict],
    policy: dict,
    committee: dict,
    chair_id: str,
    requested_start_date: str = "2026-10-01T00:00:00Z",
    requested_end_date: str = "2026-11-01T00:00:00Z",
    requesting_school_code: str = "HS-01",
    decision_meeting_start: str = "2026-09-10T18:00:00Z",
    extra_items: Optional[List[dict]] = None,
):
    """File a waiver, carry it through committee recommendation, then grant it by
    a passing board vote at a REGULAR meeting.

    `extra_items` entries are dicts describing further agenda items to list on
    other meetings before the decision; each carries "meeting" and "item" keys on
    the way back out. Returns {"waiver", "meeting", "item"}.
    """
    waiver = file_waiver(
        policy["id"],
        committee["id"],
        requesting_school_code=requesting_school_code,
        requested_start_date=requested_start_date,
        requested_end_date=requested_end_date,
    )
    recommend_waiver(waiver["id"], chair_id, "RECOMMEND_GRANT")
    meeting = schedule_meeting(scheduled_start_utc=decision_meeting_start)
    item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type="WAIVER_DECISION",
        title=f"Waiver {requesting_school_code} decision",
        waiver_request_id=waiver["id"],
    )
    post_notice(meeting["id"])
    set_clock(decision_meeting_start)
    ids = [m["id"] for m in members]
    open_meeting(meeting["id"], ids, members[0]["id"])
    record_vote(item["id"], members[0]["id"], yes_member_ids=ids[:2], no_member_ids=ids[2:3])
    return {
        "waiver": read_waiver(waiver["id"]),
        "meeting": read_meeting(meeting["id"]),
        "item": read_agenda_item(item["id"]),
    }
