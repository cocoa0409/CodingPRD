"""Composite setup helpers for the peer-group microlending domain.

Every helper builds its preconditions from scratch against a freshly restarted
server: the runner re-launches the API before every test, so the database is
empty and the logical clock starts at exactly 2026-09-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import TEST_DEFAULTS
from .factories import (
    create_attendance_payload,
    create_branch_payload,
    create_center_manager_payload,
    create_center_meeting_payload,
    create_center_payload,
    create_collection_payload,
    create_expansion_plan_payload,
    create_loan_application_payload,
    create_member_payload,
    create_peer_group_payload,
    create_training_session_payload,
    create_vote_payload,
)
from .test_users import TEST_USERS, make_center_manager_headers, make_member_headers

PA = TEST_USERS["program_admin_headers"]
BM = TEST_USERS["branch_manager_headers"]
BM_B = TEST_USERS["branch_manager_b_headers"]
FO = TEST_USERS["field_officer_headers"]

CLOCK_START = "2026-09-01T00:00:00Z"
MEETING_START = "2026-09-08T10:00:00Z"  # Tuesday, matches meeting_day_of_week 1
MEETING_END = "2026-09-08T11:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_branch(**overrides):
    return get_success_data(api.create_branch(create_branch_payload(**overrides), PA))


def create_center_manager(branch_id, **overrides):
    return get_success_data(
        api.create_center_manager(create_center_manager_payload(branch_id, **overrides), PA)
    )


def create_center(branch_id, manager_id, **overrides):
    return get_success_data(
        api.create_center(create_center_payload(branch_id, manager_id, **overrides), PA)
    )


def create_peer_group(center_id, **overrides):
    return get_success_data(
        api.create_peer_group(create_peer_group_payload(center_id, **overrides), FO)
    )


def recruit_member(branch_id, **overrides):
    return get_success_data(
        api.create_member(create_member_payload(branch_id, **overrides), FO)
    )


def set_clock(to_iso8601):
    return get_success_data(api.set_clock(to_iso8601, PA))


# ---------------------------------------------------------------------------
# Tier 2: org / group composition
# ---------------------------------------------------------------------------

def setup_org(**overrides):
    """Branch + manager + center. Returns (branch, manager, center)."""
    branch = create_branch(**overrides)
    manager = create_center_manager(branch["id"])
    center = create_center(branch["id"], manager["id"])
    return branch, manager, center


def recruit_member_batch(branch_id, count):
    return [recruit_member(branch_id) for _ in range(count)]


def setup_group_forming(center_id, member_count=5, member_names=None, prefix=None):
    """A peer group in FORMING holding `member_count` freshly recruited members.

    Returns (group, members) where members[0] is the designated applicant and
    members[1:] are its peers.
    """
    group = create_peer_group(center_id)
    members = []
    for i in range(member_count):
        label = f"{prefix or 'gm'}{i}"
        member = recruit_member(
            _branch_id_for(center_id), full_name=label, national_id=f"NID-{label}-{_nonce()}"
        )
        get_success_data(api.add_group_member(group["id"], {"member_id": member["id"]}, FO))
        members.append(member)
    return group, members


_branch_cache = {}


def _branch_id_for(center_id):
    if center_id not in _branch_cache:
        center = get_success_data(api.get_center(center_id, PA))
        _branch_cache[center_id] = center["branch_id"]
    return _branch_cache[center_id]


def _nonce():
    import uuid

    return uuid.uuid4().hex[:8].upper()


def schedule_and_complete_training(group, manager, session_windows=None):
    """Schedule + complete the two formation sessions; the group goes ACTIVE."""
    mgr_headers = make_center_manager_headers(manager["id"])
    windows = session_windows or [
        ("2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"),
        ("2026-09-03T09:00:00Z", "2026-09-03T10:00:00Z"),
    ]
    sessions = []
    for start, end in windows:
        session = get_success_data(
            api.create_training_session(
                create_training_session_payload(
                    group["id"], manager["id"], start_time=start, end_time=end
                ),
                mgr_headers,
            )
        )
        sessions.append(
            get_success_data(api.complete_training_session(session["id"], mgr_headers))
        )
    return sessions


def setup_active_group(prefix="ag"):
    """Branch + manager + center + one ACTIVE 5-member group (all ELIGIBLE).

    Returns dict(branch, manager, center, group, applicant, peers).
    """
    branch, manager, center = setup_org()
    group = create_peer_group(center["id"])
    members = []
    for i in range(5):
        member = recruit_member(
            branch["id"],
            full_name=f"{prefix} Member {i}",
            national_id=f"NID-{prefix}-{i}-{_nonce()}",
        )
        get_success_data(api.add_group_member(group["id"], {"member_id": member["id"]}, FO))
        members.append(member)
    schedule_and_complete_training(group, manager)
    return {
        "branch": branch,
        "manager": manager,
        "center": center,
        "group": group,
        "applicant": members[0],
        "peers": members[1:],
    }


def setup_two_active_groups(prefix="tg"):
    """One center hosting two ACTIVE groups. Returns ctx with groups g1, g2 and
    members m1 (+peers p1..p4) in g1 and m2 (+peers q1..q4) in g2."""
    branch, manager, center = setup_org()
    mgr_headers = make_center_manager_headers(manager["id"])

    def build_group(name, applicant_label, peer_label, windows):
        group = create_peer_group(center["id"], name=name)
        applicant = recruit_member(
            branch["id"],
            full_name=f"{applicant_label}",
            national_id=f"NID-{applicant_label}-{_nonce()}",
        )
        get_success_data(api.add_group_member(group["id"], {"member_id": applicant["id"]}, FO))
        peers = []
        for i in range(4):
            peer = recruit_member(
                branch["id"],
                full_name=f"{peer_label} {i}",
                national_id=f"NID-{peer_label}-{i}-{_nonce()}",
            )
            get_success_data(api.add_group_member(group["id"], {"member_id": peer["id"]}, FO))
            peers.append(peer)
        schedule_and_complete_training(group, manager, session_windows=windows)
        return group, applicant, peers

    g1, m1, peers1 = build_group(
        "G1",
        f"{prefix}-M1",
        f"{prefix}-P",
        [("2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"),
         ("2026-09-03T09:00:00Z", "2026-09-03T10:00:00Z")],
    )
    # Same-manager sessions are padded by 30 minutes on both sides, so the
    # second group's windows start 90 minutes after the first group's to stay
    # clear of the padded interval.
    g2, m2, peers2 = build_group(
        "G2",
        f"{prefix}-M2",
        f"{prefix}-Q",
        [("2026-09-02T11:30:00Z", "2026-09-02T12:30:00Z"),
         ("2026-09-03T11:30:00Z", "2026-09-03T12:30:00Z")],
    )
    return {
        "branch": branch, "manager": manager, "center": center,
        "g1": g1, "m1": m1, "peers1": peers1,
        "g2": g2, "m2": m2, "peers2": peers2,
        "mgr_headers": mgr_headers,
    }


# ---------------------------------------------------------------------------
# Tier 3: application lifecycle shortcuts
# ---------------------------------------------------------------------------

def draft_application(group_id, member_id, amount_cents=100_000):
    return get_success_data(
        api.create_loan_application(
            group_id, create_loan_application_payload(member_id, amount_cents), FO
        )
    )


def submit_application(application_id):
    return get_success_data(api.submit_loan_application(application_id, FO))


def cast_approve(application_id, voter_member_id):
    return get_success_data(
        api.cast_vote(
            application_id,
            create_vote_payload("APPROVE"),
            make_member_headers(voter_member_id),
        )
    )


def approve_application(application_id, applicant_id, peer_ids):
    """Cast APPROVE for every non-applicant peer. Returns the vote payloads."""
    votes = []
    for peer_id in peer_ids:
        assert peer_id != applicant_id, "applicant may not vote on their own application"
        votes.append(cast_approve(application_id, peer_id))
    return votes


def disburse_application(application_id):
    """Disburse an APPROVED application; returns the created Loan."""
    return get_success_data(api.disburse_loan_application(application_id, BM))


def disburse_member(group_id, member, peers, amount_cents=100_000):
    """Draft -> submit -> unanimous approve -> disburse. Returns (application, loan)."""
    application = draft_application(group_id, member["id"], amount_cents)
    submit_application(application["id"])
    approve_application(application["id"], member["id"], [p["id"] for p in peers])
    loan = disburse_application(application["id"])
    return application, loan


# ---------------------------------------------------------------------------
# Tier 4: meeting / attendance / collection helpers
# ---------------------------------------------------------------------------

def schedule_meeting(center_id, manager, start=MEETING_START, end=MEETING_END):
    return get_success_data(
        api.create_center_meeting(
            create_center_meeting_payload(center_id, scheduled_start=start, scheduled_end=end),
            make_center_manager_headers(manager["id"]),
        )
    )


def open_meeting(meeting_id, manager):
    return get_success_data(
        api.open_meeting(meeting_id, make_center_manager_headers(manager["id"]))
    )


def mark_attendance(meeting_id, manager, member_ids, present=True):
    mgr_headers = make_center_manager_headers(manager["id"])
    rows = []
    for member_id in member_ids:
        rows.append(
            get_success_data(
                api.record_attendance(
                    meeting_id,
                    create_attendance_payload(member_id, present),
                    mgr_headers,
                )
            )
        )
    return rows


def post_collection(meeting_id, manager, member_id, loan_id, amount_cents):
    return get_success_data(
        api.post_collection(
            meeting_id,
            create_collection_payload(member_id, loan_id, amount_cents),
            make_center_manager_headers(manager["id"]),
        )
    )


def close_meeting(meeting_id, manager):
    return get_success_data(
        api.close_meeting(meeting_id, make_center_manager_headers(manager["id"]))
    )


def setup_open_meeting_with_loan(
    amount_cents=None,
    prefix="om",
    meeting_start=MEETING_START,
    meeting_end=MEETING_END,
):
    """ACTIVE group; the applicant holds an ACTIVE loan; a meeting is OPEN with
    every group member recorded PRESENT. No collection posted yet.

    Returns ctx dict(branch, manager, center, group, applicant, peers,
    application, loan, meeting).
    """
    amount_cents = amount_cents or TEST_DEFAULTS["CYCLE1_PRINCIPAL_CENTS"]
    ctx = setup_active_group(prefix=prefix)
    application, loan = disburse_member(
        ctx["group"]["id"], ctx["applicant"], ctx["peers"], amount_cents
    )
    meeting = schedule_meeting(
        ctx["center"]["id"], ctx["manager"], start=meeting_start, end=meeting_end
    )
    open_meeting(meeting["id"], ctx["manager"])
    mark_attendance(
        meeting["id"],
        ctx["manager"],
        [ctx["applicant"]["id"]] + [p["id"] for p in ctx["peers"]],
    )
    ctx.update({"application": application, "loan": loan, "meeting": meeting})
    return ctx


def payoff_loan(ctx, meeting=None):
    """Post a full-payoff collection (savings + outstanding) for ctx's loan."""
    meeting = meeting or ctx["meeting"]
    loan = ctx["loan"]
    total = loan["savings_required_cents"] + loan["principal_outstanding_cents"]
    return post_collection(
        meeting["id"], ctx["manager"], ctx["applicant"]["id"], loan["id"], total
    )


def get_loan(loan_id):
    return get_success_data(api.get_loan(loan_id, PA))


def get_member(member_id):
    return get_success_data(api.get_member(member_id, PA))


def get_peer_group(group_id):
    return get_success_data(api.get_peer_group(group_id, PA))


def get_application(application_id):
    return get_success_data(api.get_loan_application(application_id, PA))


def get_meeting(meeting_id):
    return get_success_data(api.get_center_meeting(meeting_id, PA))


def get_savings_account(member_id):
    rows, _meta = _list(api.get_member_savings_account(member_id, PA))
    return rows[0] if rows else None


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)
