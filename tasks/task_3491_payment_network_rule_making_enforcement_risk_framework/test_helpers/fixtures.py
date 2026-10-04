"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints (the server is restarted before every test, so each test starts
empty). All time-dependent fixtures drive the logical clock explicitly via
POST /_clock/set_current_utc — nothing here ever assumes wall-clock "now".
Setup calls use get_success_data so a broken precondition surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

Identity threading: any ownership-gated call (originator lifecycle, entry
origination/cancellation, returns, ballot cast/recast, inquiry respond,
attestation submit) is made with per-instance headers built from the OWNING
participant's id — never the shared fallback constants.
"""

from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import default_client
from .test_users import (
    AUDITOR_PRIMARY_ID,
    TEST_USERS,
    make_auditor_headers,
    make_participant_officer_headers,
    make_platform_admin_headers,
    make_voting_delegate_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_failed(step: str, response) -> str:
    return f"Setup failed at {step}: {response.status_code} {response.text}"


# =============================================================================
# Logical clock (platform endpoint, outside /network)
# =============================================================================


def set_clock(to_iso8601) -> dict:
    """Drive the logical clock (PRD §2.4). Returns {"current_utc": ...}."""
    resp = default_client.set_clock(F.clock_payload(to_iso8601), _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("set_clock", resp)
    return data


# =============================================================================
# Participants
# =============================================================================


def create_participant(**overrides) -> dict:
    """Register a Participant (ONBOARDING)."""
    resp = default_client.create_participant(F.create_participant_payload(**overrides), _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_participant", resp)
    return data


def transition_participant(participant_id, to_state) -> dict:
    resp = default_client.transition_participant(
        participant_id, F.transition_payload(to_state), _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed(f"transition_participant->{to_state}", resp)
    return data


def create_active_participant(**overrides) -> dict:
    """Participant walked ONBOARDING -> ACTIVE (ballot-eligible, operational)."""
    participant = create_participant(**overrides)
    return transition_participant(participant["id"], "ACTIVE")


# =============================================================================
# Transaction codes and settlement windows
# =============================================================================


def create_transaction_code(**overrides) -> dict:
    resp = default_client.create_transaction_code(
        F.create_transaction_code_payload(**overrides), _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_transaction_code", resp)
    return data


def create_web_transaction_code(**overrides) -> dict:
    """Internet-initiated debit class: account validation required (PRD §3.5)."""
    defaults = {
        "code": "WEB",
        "entry_class": "DEBIT",
        "authorization_requirement": "ORAL_RECORDED",
        "account_validation_required": True,
    }
    defaults.update(overrides)
    return create_transaction_code(**defaults)


def create_settlement_window(**overrides) -> dict:
    resp = default_client.create_settlement_window(
        F.create_settlement_window_payload(**overrides), _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_settlement_window", resp)
    return data


# =============================================================================
# Originators (ownership-gated on the owning participant)
# =============================================================================


def create_originator(participant, **overrides) -> dict:
    """Register an Originator under `participant` (PENDING_DUE_DILIGENCE)."""
    headers = make_participant_officer_headers(participant["id"])
    resp = default_client.create_originator(F.create_originator_payload(**overrides), headers)
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_originator", resp)
    return data


def transition_originator(originator, to_state) -> dict:
    headers = make_participant_officer_headers(originator["participant_id"])
    resp = default_client.transition_originator(
        originator["id"], F.transition_payload(to_state), headers
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed(f"transition_originator->{to_state}", resp)
    return data


def approve_originator(originator) -> dict:
    return transition_originator(originator, "APPROVED")


def create_approved_originator(participant, **overrides) -> dict:
    """Originator walked PENDING_DUE_DILIGENCE -> APPROVED under `participant`."""
    return approve_originator(create_originator(participant, **overrides))


def patch_exposure_limit(originator_id, participant_id, exposure_limit_cents, expected_originator_version) -> dict:
    """OCC exposure-limit update (PRD §2.7)."""
    headers = make_participant_officer_headers(participant_id)
    resp = default_client.update_exposure_limit(
        originator_id,
        F.exposure_limit_payload(exposure_limit_cents, expected_originator_version),
        headers,
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("patch_exposure_limit", resp)
    return data


def get_originator(originator_id) -> dict:
    resp = default_client.get_originator(originator_id, _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("get_originator", resp)
    return data


def get_transaction_code(transaction_code_id) -> dict:
    resp = default_client.get_transaction_code(transaction_code_id, _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("get_transaction_code", resp)
    return data


# =============================================================================
# Composite: origination stack (the most common multi-step preamble)
# =============================================================================


def setup_origination_stack(
    *,
    clock_iso=F.DEFAULT_CLOCK_ISO,
    participant_type="ODFI",
    receiver_type="RDFI",
    with_receiver=True,
    code_overrides=None,
    window_overrides=None,
    originator_overrides=None,
) -> dict:
    """Set the clock, then build: ACTIVE originating participant, (optionally) an
    ACTIVE receiving participant, one transaction code, one settlement window,
    and one APPROVED originator under the originating participant.

    Returns {"participant", "receiver", "transaction_code", "window", "originator"}.
    """
    set_clock(clock_iso)
    participant = create_active_participant(participant_type=participant_type)
    receiver = create_active_participant(participant_type=receiver_type) if with_receiver else None
    transaction_code = create_transaction_code(**(code_overrides or {}))
    window = create_settlement_window(**(window_overrides or {}))
    originator = create_approved_originator(participant, **(originator_overrides or {}))
    return {
        "participant": participant,
        "receiver": receiver,
        "transaction_code": transaction_code,
        "window": window,
        "originator": originator,
    }


# =============================================================================
# Payment entries: origination, settlement, cancellation, returns
# =============================================================================


def create_payment_entry(originator, transaction_code, *, at_iso=None, **overrides) -> dict:
    """Originate an entry (ORIGINATED). Officer headers of the owning participant.

    When at_iso is given the logical clock is set first (same-day cutoff checks
    and period bucketing are clock-sensitive).
    """
    if at_iso is not None:
        set_clock(at_iso)
    headers = make_participant_officer_headers(originator["participant_id"])
    payload = F.create_payment_entry_payload(originator["id"], transaction_code["id"], **overrides)
    resp = default_client.create_payment_entry(payload, headers)
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_payment_entry", resp)
    return data


def originate_entries(originator, transaction_code, amounts, *, at_iso=None, **overrides) -> list:
    """Originate one entry per amount (distinct receiver hashes by default)."""
    if at_iso is not None:
        set_clock(at_iso)
    return [
        create_payment_entry(originator, transaction_code, amount_cents=amount, **overrides)
        for amount in amounts
    ]


def run_settlement(settlement_window_id, *, at_iso=None) -> dict:
    """Run a settlement window (entries ORIGINATED -> SETTLED).

    When at_iso is given the clock is set first — the run requires the logical
    time to be at or after the window's cutoff on the current logical date
    (PRD §3.6). Returns {"settled_count", "settled_entry_ids"}.
    """
    if at_iso is not None:
        set_clock(at_iso)
    resp = default_client.run_settlement(settlement_window_id, _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("run_settlement", resp)
    return data


def get_payment_entry(payment_entry_id) -> dict:
    resp = default_client.get_payment_entry(payment_entry_id, _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("get_payment_entry", resp)
    return data


def settle_entries(window, entries=None, *, at_iso) -> list:
    """Run the window at at_iso and return the freshly-read SETTLED entries.

    When `entries` is omitted, the caller tracks ids via the run response.
    """
    run_settlement(window["id"], at_iso=at_iso)
    if entries is None:
        return []
    return [get_payment_entry(e["id"]) for e in entries]


def create_and_settle_entry(
    originator,
    transaction_code,
    window,
    *,
    amount_cents=1000,
    entry_iso=F.DEFAULT_CLOCK_ISO,
    settle_iso=None,
    **overrides,
) -> dict:
    """Originate one entry at entry_iso, then settle it (re-GET afterwards).

    settle_iso defaults to the entry's own date at 18:00 UTC — after the
    default 17:00 window cutoff.
    """
    if settle_iso is None:
        settle_iso = C.iso_on_date(C.iso_date_of(entry_iso), "18:00:00")
    entry = create_payment_entry(
        originator, transaction_code, amount_cents=amount_cents, at_iso=entry_iso, **overrides
    )
    run_settlement(window["id"], at_iso=settle_iso)
    return get_payment_entry(entry["id"])


def cancel_entry(entry) -> dict:
    """Cancel an ORIGINATED entry as the originating participant's officer."""
    headers = make_participant_officer_headers(entry["originating_participant_id"])
    resp = default_client.cancel_payment_entry(entry["id"], headers)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("cancel_entry", resp)
    return data


def return_entry(entry, returning_participant, reason_code="UNAUTHORIZED_DEBIT", *, at_iso=None) -> dict:
    """Return a SETTLED entry as the RECEIVING participant's officer (201).

    at_iso sets the logical clock first — the banking-day return window is
    measured from the entry's settled_date to the logical date.
    """
    if at_iso is not None:
        set_clock(at_iso)
    headers = make_participant_officer_headers(returning_participant["id"])
    resp = default_client.create_return(entry["id"], F.create_return_payload(reason_code), headers)
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("return_entry", resp)
    return data


def return_entries(entries, returning_participant, reason_codes, *, at_iso=None) -> list:
    """Return several entries. reason_codes is one code applied to all, or a
    list parallel to entries. Returns the created ReturnRecords."""
    if at_iso is not None:
        set_clock(at_iso)
    if isinstance(reason_codes, str):
        reason_codes = [reason_codes] * len(entries)
    assert len(reason_codes) == len(entries)
    return [
        return_entry(entry, returning_participant, code)
        for entry, code in zip(entries, reason_codes)
    ]


# =============================================================================
# Account validations
# =============================================================================


def create_account_validation(originator, account_number_hash=None, method="MICRO_DEPOSIT", *, at_iso=None) -> dict:
    """Record an account validation (VALID while logical date <= validated_until)."""
    if at_iso is not None:
        set_clock(at_iso)
    headers = make_participant_officer_headers(originator["participant_id"])
    payload = F.create_account_validation_payload(originator["id"], account_number_hash, method=method)
    resp = default_client.create_account_validation(payload, headers)
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_account_validation", resp)
    return data


def create_expired_account_validation(originator, account_number_hash=None, method="MICRO_DEPOSIT", *, created_iso=F.DEFAULT_CLOCK_ISO) -> dict:
    """Validation created at created_iso, then the clock advanced one day past
    validated_until (creation date + 365 days) so it reads EXPIRED."""
    validation = create_account_validation(
        originator, account_number_hash, method=method, at_iso=created_iso
    )
    set_clock(C.iso_on_date(C.date_add_days(validation["validated_until"], 1), "00:00:00"))
    return validation


# =============================================================================
# Rule proposals and ballots
# =============================================================================


def create_rule_proposal(transaction_code, *, at_iso=None, **overrides) -> dict:
    """File a RuleProposal (DRAFT). effective_date must be strictly after the
    creation date — override it together with at_iso when moving the clock."""
    if at_iso is not None:
        set_clock(at_iso)
    resp = default_client.create_rule_proposal(
        F.create_rule_proposal_payload(transaction_code["id"], **overrides), _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_rule_proposal", resp)
    return data


def transition_proposal(rule_proposal_id, to_state) -> dict:
    resp = default_client.transition_rule_proposal(
        rule_proposal_id, F.transition_payload(to_state), _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed(f"transition_proposal->{to_state}", resp)
    return data


def open_comment_period(proposal) -> dict:
    """DRAFT -> COMMENT_OPEN (stamps comment_opened_at from the logical clock)."""
    return transition_proposal(proposal["id"], "COMMENT_OPEN")


def open_balloting(proposal, *, comment_days=C.COMMENT_PERIOD_DAYS) -> dict:
    """COMMENT_OPEN -> BALLOTING after the 30-day comment period.

    The clock is moved to comment_opened_at + comment_days (date-level rule:
    logical date >= comment_opened_at date + 30 days), then the transition is
    issued. The proposal must carry a non-null comment_opened_at (pass the
    fresh dict returned by open_comment_period).
    """
    assert proposal.get("comment_opened_at"), "open_balloting needs comment_opened_at"
    set_clock(C.iso_add_days(proposal["comment_opened_at"], comment_days))
    return transition_proposal(proposal["id"], "BALLOTING")


def cast_ballot(proposal_id, participant, vote="YEA") -> dict:
    """Cast one ballot as the participant's VotingDelegate (entity-backed)."""
    headers = make_voting_delegate_headers(participant["id"])
    resp = default_client.cast_ballot(proposal_id, F.create_ballot_payload(vote), headers)
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("cast_ballot", resp)
    return data


def recast_ballot(ballot_id, participant, vote) -> dict:
    headers = make_voting_delegate_headers(participant["id"])
    resp = default_client.recast_ballot(ballot_id, F.create_ballot_payload(vote), headers)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("recast_ballot", resp)
    return data


def close_ballot(proposal, *, ballot_days=C.BALLOT_PERIOD_DAYS) -> dict:
    """Close balloting after the 14-day ballot period; computes the outcome,
    moves the proposal to PASSED or REJECTED and locks all CAST ballots."""
    assert proposal.get("ballot_opened_at"), "close_ballot needs ballot_opened_at"
    set_clock(C.iso_add_days(proposal["ballot_opened_at"], ballot_days))
    resp = default_client.close_ballot(proposal["id"], _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("close_ballot", resp)
    return data


def create_proposal_in_balloting(transaction_code, *, start_iso=F.DEFAULT_CLOCK_ISO, **overrides) -> dict:
    """Proposal walked DRAFT -> COMMENT_OPEN -> BALLOTING; the clock is left at
    ballot-open time (start date + 30 days)."""
    proposal = create_rule_proposal(transaction_code, at_iso=start_iso, **overrides)
    proposal = open_comment_period(proposal)
    return open_balloting(proposal)


def create_closed_proposal(transaction_code, votes, *, start_iso=F.DEFAULT_CLOCK_ISO, **overrides) -> dict:
    """Proposal run to a closed ballot. votes: list of (participant, vote);
    each participant casts during BALLOTING. The clock ends at ballot_opened_at
    + 14 days. Returns the closed proposal (PASSED or REJECTED)."""
    proposal = create_proposal_in_balloting(transaction_code, start_iso=start_iso, **overrides)
    for participant, vote in votes:
        cast_ballot(proposal["id"], participant, vote)
    return close_ballot(proposal)


def create_passed_proposal(transaction_code, *, votes=None, start_iso=F.DEFAULT_CLOCK_ISO, **overrides) -> dict:
    """Proposal closed with outcome PASSED_QUORUM.

    votes=None creates one fresh ACTIVE participant and casts a single YEA —
    quorum is 1 >= ceil(1/2) and 1*3 >= 1*2, a pass on any electorate of one.
    Callers with their own electorate MUST pass explicit votes.
    """
    if votes is None:
        voter = create_active_participant()
        votes = [(voter, "YEA")]
    proposal = create_closed_proposal(transaction_code, votes, start_iso=start_iso, **overrides)
    assert proposal["status"] == "PASSED", (
        f"Fixture expected PASSED, got {proposal['status']} ({proposal.get('outcome')})"
    )
    return proposal


def create_effective_rule(
    transaction_code,
    *,
    votes=None,
    effective_date="2026-10-01",
    start_iso=F.DEFAULT_CLOCK_ISO,
    **overrides,
) -> dict:
    """Full pipeline to EFFECTIVE: DRAFT -> COMMENT_OPEN -> BALLOTING -> PASSED
    -> EFFECTIVE. effective_date must be strictly after the start date and no
    later than the close date (start + 44 days) so the calendar gate passes.
    Default timeline: created 2026-09-01, balloting 2026-10-01, closed
    2026-10-15, promulgated 2026-10-15."""
    proposal = create_passed_proposal(
        transaction_code, votes=votes, start_iso=start_iso, effective_date=effective_date, **overrides
    )
    # The clock already reads close time (ballot_opened_at + 14 days), which is
    # on or after the default effective_date — the gate is satisfied.
    return transition_proposal(proposal["id"], "EFFECTIVE")


# =============================================================================
# Guidance documents
# =============================================================================


def publish_guidance(proposal, transaction_code, *, expected_transaction_code_version=None, **overrides) -> dict:
    """Publish a GuidanceDocument (OCC-checked, PRD §2.7). When the expected
    version is omitted the transaction code is re-read to obtain the current
    one."""
    if expected_transaction_code_version is None:
        expected_transaction_code_version = get_transaction_code(transaction_code["id"])["version"]
    payload = F.create_guidance_document_payload(
        proposal["id"], transaction_code["id"], expected_transaction_code_version, **overrides
    )
    resp = default_client.create_guidance_document(payload, _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("publish_guidance", resp)
    return data


# =============================================================================
# Return-rate snapshots and inquiry cases
# =============================================================================


def create_snapshot(participant_id, period) -> dict:
    resp = default_client.create_return_rate_snapshot(
        F.create_return_rate_snapshot_payload(participant_id, period), _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_snapshot", resp)
    return data


def find_inquiry_cases(*, participant_id=None, snapshot_id=None, status=None) -> list:
    params = {}
    if participant_id is not None:
        params["participant_id"] = participant_id
    if snapshot_id is not None:
        params["return_rate_snapshot_id"] = snapshot_id
    if status is not None:
        params["status"] = status
    params.setdefault("limit", 100)
    resp = default_client.list_inquiry_cases(_ADMIN, params=params)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("list_inquiry_cases", resp)
    return data


def setup_breaching_snapshot(
    *,
    period="2026-09",
    forward_count=4,
    unauth_returns=1,
    admin_returns=0,
    other_returns=0,
    amount_cents=1000,
    originate_iso=None,
    settle_iso=None,
    return_iso=None,
) -> dict:
    """Build a participant whose snapshot for `period` breaches exactly the
    classes requested (defaults: 4 settled entries, 1 unauthorized return —
    1*100 > 4*10 breaches UNAUTHORIZED; 1*100 > 4*20 and 1*100 > 4*25 do not
    breach ADMINISTRATIVE or OVERALL).

    All entries are originated and settled inside the period (settlement basis
    == origination basis); returns land one day after settlement, still inside
    the period and well inside the default 30-banking-day return window.

    Returns {"stack", "entries", "returns", "snapshot"}.
    """
    first_day = f"{period}-01"
    originate_iso = originate_iso or C.iso_on_date(first_day, "09:00:00")
    settle_iso = settle_iso or C.iso_on_date(first_day, "18:00:00")
    return_iso = return_iso or C.iso_on_date(C.date_add_days(first_day, 1), "10:00:00")

    stack = setup_origination_stack(clock_iso=originate_iso)
    originator = stack["originator"]
    transaction_code = stack["transaction_code"]
    window = stack["window"]
    receiver = stack["receiver"]

    entries = originate_entries(
        originator, transaction_code, [amount_cents] * forward_count
    )
    run_settlement(window["id"], at_iso=settle_iso)
    settled = [get_payment_entry(e["id"]) for e in entries]

    reason_codes = (
        ["UNAUTHORIZED_DEBIT"] * unauth_returns
        + ["INSUFFICIENT_FUNDS"] * admin_returns
        + ["STOP_PAYMENT"] * other_returns
    )
    returns = return_entries(settled[: len(reason_codes)], receiver, reason_codes, at_iso=return_iso)
    snapshot = create_snapshot(stack["participant"]["id"], period)
    return {"stack": stack, "entries": settled, "returns": returns, "snapshot": snapshot}


def setup_auto_opened_inquiry(*, return_class="UNAUTHORIZED", period="2026-09", **snapshot_kwargs) -> dict:
    """A breaching snapshot plus the InquiryCase it auto-opens (PRD §3.7).

    return_class selects the single breached class:
    UNAUTHORIZED (default), ADMINISTRATIVE, or OVERALL (two OTHER returns over
    four forward entries: 2*100 > 4*25 without touching the other classes).
    Returns {"stack", "entries", "returns", "snapshot", "inquiry"}.
    """
    if return_class == "ADMINISTRATIVE":
        snapshot_kwargs.setdefault("unauth_returns", 0)
        snapshot_kwargs.setdefault("admin_returns", 1)
    elif return_class == "OVERALL":
        snapshot_kwargs.setdefault("unauth_returns", 0)
        snapshot_kwargs.setdefault("other_returns", 2)
    elif return_class != "UNAUTHORIZED":
        raise ValueError(f"unknown return_class {return_class!r}")
    built = setup_breaching_snapshot(period=period, **snapshot_kwargs)
    inquiries = find_inquiry_cases(
        participant_id=built["stack"]["participant"]["id"], snapshot_id=built["snapshot"]["id"]
    )
    matching = [i for i in inquiries if i["return_class"] == return_class]
    assert len(matching) == 1, (
        f"Setup failed: expected exactly one {return_class} inquiry, got {len(matching)}"
    )
    built["inquiry"] = matching[0]
    return built


def respond_inquiry(inquiry, response_text="Remediation plan submitted") -> dict:
    """OPENED -> RESPONSE_SUBMITTED as the inquired participant's officer."""
    headers = make_participant_officer_headers(inquiry["participant_id"])
    resp = default_client.respond_inquiry(inquiry["id"], F.respond_payload(response_text), headers)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("respond_inquiry", resp)
    return data


def resolve_inquiry(inquiry_id) -> dict:
    resp = default_client.resolve_inquiry(inquiry_id, _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("resolve_inquiry", resp)
    return data


def advance_past_response_deadline(inquiry) -> None:
    """Move the clock strictly later than the inquiry's response_deadline
    (creation timestamp + 14 days, PRD §3.8) so OPENED -> ESCALATED is legal."""
    set_clock(C.iso_add_days(inquiry["response_deadline"], 1))


def escalate_inquiry(inquiry, *, admin_headers=None) -> dict:
    """Escalate an inquiry to an ISSUED EnforcementAction (200 returns the action).

    If the inquiry is still OPENED the clock is first moved past its response
    deadline. admin_headers defaults to the primary admin; pass
    make_platform_admin_headers(...) to control escalated_by_user_id.
    """
    if inquiry.get("status") == "OPENED":
        advance_past_response_deadline(inquiry)
    resp = default_client.escalate_inquiry(inquiry["id"], admin_headers or _ADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("escalate_inquiry", resp)
    return data


def setup_escalated_inquiry_action(*, escalating_admin_id="admin-escalator-1", **inquiry_kwargs) -> dict:
    """Auto-opened inquiry escalated by a NAMED admin: the created
    EnforcementAction carries escalated_by_user_id == escalating_admin_id, so
    segregation-of-duties tests can attempt the UPHELD with the same and with a
    different admin. Returns the inquiry fixture dict plus "action"."""
    built = setup_auto_opened_inquiry(**inquiry_kwargs)
    action = escalate_inquiry(
        built["inquiry"], admin_headers=make_platform_admin_headers(escalating_admin_id)
    )
    built["action"] = action
    return built


# =============================================================================
# Enforcement actions
# =============================================================================


def create_enforcement_action(participant, violation_code="EXCESSIVE_UNAUTHORIZED_RETURNS", **overrides) -> dict:
    """Directly file an EnforcementAction (ISSUED; escalated_by_user_id null)."""
    resp = default_client.create_enforcement_action(
        F.create_enforcement_action_payload(participant["id"], violation_code, **overrides),
        _ADMIN,
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_enforcement_action", resp)
    return data


def transition_enforcement(action_id, to_state, *, admin_headers=None) -> dict:
    resp = default_client.transition_enforcement_action(
        action_id, F.transition_payload(to_state), admin_headers or _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed(f"transition_enforcement->{to_state}", resp)
    return data


def create_upheld_actions(participant, n=C.SUSPENSION_STRIKE_COUNT, *, violation_code="EXCESSIVE_UNAUTHORIZED_RETURNS", admin_headers=None) -> list:
    """Create and uphold n direct actions against the participant (the n-th
    UPHELD is where the three-strike suspension cascade fires, PRD §3.8)."""
    actions = []
    for _ in range(n):
        action = create_enforcement_action(participant, violation_code)
        actions.append(transition_enforcement(action["id"], "UPHELD", admin_headers=admin_headers))
    return actions


def pay_enforcement(action_id, *, at_iso=None, admin_headers=None) -> dict:
    """Drive an action to PAID; at_iso sets the clock first (late accrual is
    measured from issued_date to the paid date, PRD §3.8)."""
    if at_iso is not None:
        set_clock(at_iso)
    return transition_enforcement(action_id, "PAID", admin_headers=admin_headers)


# =============================================================================
# Compliance attestations and audit reports
# =============================================================================


def create_attestation(participant, period_year=2026, **overrides) -> dict:
    """Open the year's ComplianceAttestation (PENDING; due_date (year+1)-03-01)."""
    resp = default_client.create_attestation(
        F.create_attestation_payload(participant["id"], period_year, **overrides), _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_attestation", resp)
    return data


def submit_attestation(attestation, attestation_text="We attest compliance with the operating rules") -> dict:
    """PENDING/OVERDUE/REJECTED -> SUBMITTED as the participant's officer."""
    headers = make_participant_officer_headers(attestation["participant_id"])
    resp = default_client.transition_attestation(
        attestation["id"], F.submit_attestation_payload(attestation_text), headers
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("submit_attestation", resp)
    return data


def transition_attestation(attestation_id, to_state) -> dict:
    """Admin disposition: SUBMITTED -> ACCEPTED | REJECTED."""
    resp = default_client.transition_attestation(
        attestation_id, F.transition_payload(to_state), _ADMIN
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed(f"transition_attestation->{to_state}", resp)
    return data


def create_audit(participant, start_date="2026-06-01", end_date="2026-06-30", *, auditor_headers=None) -> dict:
    """Schedule an AuditReport (SCHEDULED); created_by_user_id := the auditor's
    X-User-ID. Defaults to the primary auditor."""
    resp = default_client.create_audit(
        F.create_audit_payload(participant["id"], start_date=start_date, end_date=end_date),
        auditor_headers or TEST_USERS["auditor_headers"],
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, _setup_failed("create_audit", resp)
    return data


def start_audit(audit, *, at_iso=None, auditor_headers=None) -> dict:
    """SCHEDULED -> IN_PROGRESS. The logical date must be >= start_date; when
    at_iso is omitted the clock is set to the audit's start date at 09:00."""
    set_clock(at_iso or C.iso_on_date(audit["start_date"], "09:00:00"))
    resp = default_client.transition_audit(
        audit["id"], F.transition_payload("IN_PROGRESS"), auditor_headers or TEST_USERS["auditor_headers"]
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("start_audit", resp)
    return data


def complete_audit(audit, findings_count=0, *, at_iso=None, auditor_headers=None) -> dict:
    """IN_PROGRESS -> COMPLETED with segregation of duties: the completing
    auditor defaults to whoever did NOT create the engagement (primary vs
    alternate). Pass auditor_headers explicitly for custom creators."""
    if auditor_headers is None:
        if audit.get("created_by_user_id") == AUDITOR_PRIMARY_ID:
            auditor_headers = TEST_USERS["auditor_alt_headers"]
        else:
            auditor_headers = TEST_USERS["auditor_headers"]
    if at_iso is not None:
        set_clock(at_iso)
    resp = default_client.transition_audit(
        audit["id"], F.complete_audit_payload(findings_count), auditor_headers
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, _setup_failed("complete_audit", resp)
    return data


def create_completed_audit(participant, start_date="2026-06-01", end_date="2026-06-30", findings_count=0, *, creator_headers=None, completer_headers=None) -> dict:
    """Full audit lifecycle to COMPLETED (the attestation-acceptance evidence,
    PRD §3.9). The clock is set to start_date 09:00 for both transitions."""
    audit = create_audit(
        participant, start_date=start_date, end_date=end_date, auditor_headers=creator_headers
    )
    audit = start_audit(audit, auditor_headers=creator_headers or TEST_USERS["auditor_headers"])
    return complete_audit(audit, findings_count, auditor_headers=completer_headers)
