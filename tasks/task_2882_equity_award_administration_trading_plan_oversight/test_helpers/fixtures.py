"""Composite setup helpers.

Every test starts against an empty database, so every helper here builds its
preconditions from scratch through the endpoints the PRD declares. All helpers
use the lenient ``get_success_data`` validator so a broken precondition reads as
a setup failure rather than as a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    annual_rollover_payload,
    approve_grant_payload,
    cancel_grant_payload,
    certify_payload,
    create_approval_authority_payload,
    create_equity_plan_payload,
    create_grant_payload,
    create_mobility_assignment_payload,
    create_participant_payload,
    create_performance_cycle_payload,
    create_preclearance_request_payload,
    create_trading_plan_payload,
    create_trading_window_payload,
    create_vesting_tranche_payload,
    decide_payload,
    execute_payload,
    plan_status_payload,
    request_changes_payload,
    resubmit_payload,
    reverse_payload,
    revise_grant_payload,
    share_reserve_adjustment_payload,
    terminate_participant_payload,
    unique_employee_number,
    unique_metric_code,
    unique_quarter_label,
    vest_tranche_payload,
    window_status_payload,
)
from .test_users import (
    ADMIN,
    BOARD,
    COMPLIANCE,
    make_officer_headers,
    make_participant_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: single-step primitives
# ---------------------------------------------------------------------------
def set_clock(current_utc, headers=ADMIN):
    """Move the deterministic logical clock and return the echoed payload."""
    return get_success_data(api_client.set_clock(current_utc, headers))


def create_plan(headers=ADMIN, **overrides):
    """Register a share plan. It is ACTIVE at version 1."""
    payload = create_equity_plan_payload(**overrides)
    return get_success_data(api_client.create_equity_plan(payload, headers))


def read_plan(plan_id, headers=ADMIN):
    return get_success_data(api_client.get_equity_plan(plan_id, headers))


def freeze_plan(plan_id, headers=ADMIN, **overrides):
    payload = plan_status_payload("FREEZE", **overrides)
    return get_success_data(api_client.set_equity_plan_status(plan_id, payload, headers))


def unfreeze_plan(plan_id, headers=ADMIN):
    payload = plan_status_payload("UNFREEZE")
    return get_success_data(api_client.set_equity_plan_status(plan_id, payload, headers))


def terminate_plan(plan_id, headers=ADMIN, **overrides):
    payload = plan_status_payload("TERMINATE", **overrides)
    return get_success_data(api_client.set_equity_plan_status(plan_id, payload, headers))


def adjust_reserve(plan_id, delta_shares, expected_plan_version, headers=ADMIN,
                   **overrides):
    payload = share_reserve_adjustment_payload(
        delta_shares, expected_plan_version, **overrides
    )
    return get_success_data(api_client.adjust_share_reserve(plan_id, payload, headers))


def run_rollover(plan_id, fiscal_year_label="FY2027", headers=ADMIN):
    payload = annual_rollover_payload(fiscal_year_label)
    return get_success_data(api_client.run_annual_rollover(plan_id, payload, headers))


def create_authority(plan_id, headers=BOARD, **overrides):
    """Delegate grant-approval authority. It is ACTIVE with consumed_shares 0."""
    payload = create_approval_authority_payload(plan_id, **overrides)
    return get_success_data(api_client.create_approval_authority(payload, headers))


def read_authority(authority_id, headers=BOARD):
    return get_success_data(api_client.get_approval_authority(authority_id, headers))


def create_participant(headers=ADMIN, **overrides):
    """Enrol an award recipient. ACTIVE at version 1."""
    payload = create_participant_payload(**overrides)
    return get_success_data(api_client.create_participant(payload, headers))


def read_participant(participant_id, headers=ADMIN):
    return get_success_data(api_client.get_participant(participant_id, headers))


def reclassify_participant(participant_id, insider_status, headers=COMPLIANCE):
    return get_success_data(
        api_client.set_insider_status(
            participant_id, {"insider_status": insider_status}, headers
        )
    )


def terminate_participant(participant_id, termination_date, termination_reason,
                          headers=ADMIN, **overrides):
    payload = terminate_participant_payload(
        termination_date, termination_reason, **overrides
    )
    return get_success_data(
        api_client.terminate_participant(participant_id, payload, headers)
    )


def create_mobility_assignment(participant_id, headers=ADMIN, **overrides):
    payload = create_mobility_assignment_payload(participant_id, **overrides)
    return get_success_data(api_client.create_mobility_assignment(payload, headers))


def create_window(plan_id, headers=COMPLIANCE, **overrides):
    """Schedule a trading window. It is SCHEDULED with approved_shares_cumulative 0."""
    payload = create_trading_window_payload(plan_id, **overrides)
    return get_success_data(api_client.create_trading_window(payload, headers))


def drive_window(window_id, action, headers=COMPLIANCE, **overrides):
    payload = window_status_payload(action, **overrides)
    return get_success_data(
        api_client.set_trading_window_status(window_id, payload, headers)
    )


def create_open_window(plan_id, headers=COMPLIANCE, **overrides):
    """Schedule a window and move it to OPEN."""
    window = create_window(plan_id, headers=headers, **overrides)
    return drive_window(window["id"], "OPEN", headers=headers)


def read_window(window_id, headers=COMPLIANCE):
    return get_success_data(api_client.get_trading_window(window_id, headers))


def create_cycle(plan_id, headers=ADMIN, **overrides):
    """Open a performance measurement cycle. It is OPEN with a null multiplier."""
    payload = create_performance_cycle_payload(plan_id, **overrides)
    return get_success_data(api_client.create_performance_cycle(payload, headers))


def certify_cycle(cycle_id, actual_value, headers=BOARD, **overrides):
    payload = certify_payload(actual_value, **overrides)
    return get_success_data(
        api_client.certify_performance_cycle(cycle_id, payload, headers)
    )


def read_cycle(cycle_id, headers=ADMIN):
    return get_success_data(api_client.get_performance_cycle(cycle_id, headers))


def read_grant(grant_id, headers=ADMIN):
    return get_success_data(api_client.get_grant(grant_id, headers))


def read_tranche(tranche_id, headers=ADMIN):
    return get_success_data(api_client.get_vesting_tranche(tranche_id, headers))


def read_event(event_id, headers=ADMIN):
    return get_success_data(api_client.get_vesting_event(event_id, headers))


def read_preclearance(request_id, headers=COMPLIANCE):
    return get_success_data(api_client.get_preclearance_request(request_id, headers))


def read_trading_plan(trading_plan_id, headers=COMPLIANCE):
    return get_success_data(api_client.get_trading_plan(trading_plan_id, headers))


def read_report(report_id, headers=COMPLIANCE):
    return get_success_data(api_client.get_transaction_report(report_id, headers))


# ---------------------------------------------------------------------------
# Tier 2: grant construction
# ---------------------------------------------------------------------------
def create_draft_grant(plan_id, participant_id, headers=ADMIN, tranches=None,
                       **overrides):
    """Draft a grant and append the requested tranches while it is still DRAFT.

    ``tranches`` is a list of keyword dicts handed to the tranche factory. When it
    is None a single TIME tranche carrying the grant's whole target_shares is
    appended. Returns ``(grant, [tranche, ...])``.
    """
    payload = create_grant_payload(plan_id, participant_id, **overrides)
    grant = get_success_data(api_client.create_grant(payload, headers))
    if tranches is None:
        tranches = [{"tranche_index": 1, "target_shares": payload["target_shares"]}]
    rows = []
    for index, spec in enumerate(tranches, start=1):
        spec = dict(spec)
        spec.setdefault("tranche_index", index)
        tranche_payload = create_vesting_tranche_payload(**spec)
        rows.append(
            get_success_data(
                api_client.create_vesting_tranche(grant["id"], tranche_payload, headers)
            )
        )
    return get_success_data(api_client.get_grant(grant["id"], headers)), rows


def submit_grant(grant_id, headers=ADMIN):
    return get_success_data(api_client.submit_grant(grant_id, headers))


def request_grant_changes(grant_id, headers=BOARD, change_note="Please resize."):
    payload = request_changes_payload(change_note)
    return get_success_data(api_client.request_grant_changes(grant_id, payload, headers))


def revise_grant(grant_id, target_shares, headers=ADMIN, **overrides):
    payload = revise_grant_payload(target_shares, **overrides)
    return get_success_data(api_client.revise_grant(grant_id, payload, headers))


def approve_grant_by_board(grant_id, headers=BOARD):
    payload = approve_grant_payload("BOARD")
    return get_success_data(api_client.approve_grant(grant_id, payload, headers))


def approve_grant_by_delegate(grant_id, authority_id, delegate_user_id="officer-1"):
    payload = approve_grant_payload("DELEGATED", authority_id=authority_id)
    return get_success_data(
        api_client.approve_grant(
            grant_id, payload, make_officer_headers(delegate_user_id)
        )
    )


def issue_grant(grant_id, headers=ADMIN):
    return get_success_data(api_client.issue_grant(grant_id, headers))


def cancel_grant(grant_id, headers=ADMIN, cancel_reason="Superseded."):
    payload = cancel_grant_payload(cancel_reason)
    return get_success_data(api_client.cancel_grant(grant_id, payload, headers))


def create_approved_grant(plan_id, participant_id, tranches=None,
                          admin_headers=ADMIN, approver_headers=BOARD, **overrides):
    """Draft, tranche, submit and board-approve a grant. Returns ``(grant, tranches)``.

    Submission and approval are performed by different identities so the
    four-eyes control is satisfied.
    """
    grant, rows = create_draft_grant(
        plan_id, participant_id, headers=admin_headers, tranches=tranches, **overrides
    )
    submit_grant(grant["id"], headers=admin_headers)
    grant = approve_grant_by_board(grant["id"], headers=approver_headers)
    return grant, rows


def create_granted_grant(plan_id, participant_id, tranches=None,
                         admin_headers=ADMIN, approver_headers=BOARD, **overrides):
    """Carry a grant all the way to GRANTED. The plan must already own a window
    from which a grant date can be determined. Returns ``(grant, tranches)``."""
    grant, rows = create_approved_grant(
        plan_id, participant_id, tranches=tranches,
        admin_headers=admin_headers, approver_headers=approver_headers, **overrides
    )
    grant = issue_grant(grant["id"], headers=admin_headers)
    refreshed = [read_tranche(t["id"], admin_headers) for t in rows]
    return grant, refreshed


# ---------------------------------------------------------------------------
# Tier 3: standing scenarios
# ---------------------------------------------------------------------------
def setup_plan_and_participant(clock="2026-01-05T09:00:00Z", plan_overrides=None,
                               participant_overrides=None):
    """Set the clock, register one ACTIVE plan and enrol one ACTIVE participant.

    Returns ``(plan, participant)``.
    """
    if clock is not None:
        set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    participant = create_participant(**(participant_overrides or {}))
    return plan, participant


def setup_plan_participant_and_open_window(clock="2026-01-05T09:00:00Z",
                                          plan_overrides=None,
                                          participant_overrides=None,
                                          window_overrides=None):
    """Clock, ACTIVE plan, ACTIVE participant and one OPEN trading window whose
    interval contains the clock. Returns ``(plan, participant, window)``."""
    plan, participant = setup_plan_and_participant(
        clock=clock, plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
    )
    window = create_open_window(plan["id"], **(window_overrides or {}))
    return plan, participant, window


def setup_granted_scenario(clock="2026-01-05T09:00:00Z", plan_overrides=None,
                           participant_overrides=None, window_overrides=None,
                           grant_overrides=None, tranches=None):
    """The most common preamble: an OPEN window, and one GRANTED award over it.

    Returns a dict with ``plan``, ``participant``, ``window``, ``grant`` and
    ``tranches``.
    """
    plan, participant, window = setup_plan_participant_and_open_window(
        clock=clock, plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
        window_overrides=window_overrides,
    )
    grant, rows = create_granted_grant(
        plan["id"], participant["id"], tranches=tranches, **(grant_overrides or {})
    )
    return {
        "plan": read_plan(plan["id"]),
        "participant": participant,
        "window": window,
        "grant": grant,
        "tranches": rows,
    }


# ---------------------------------------------------------------------------
# Tier 4: vesting, tax sourcing and settlement
# ---------------------------------------------------------------------------
def vest_tranche(tranche_id, fmv_per_share_cents=5000, headers=ADMIN, **overrides):
    """Vest a tranche and return the settlement it creates."""
    payload = vest_tranche_payload(fmv_per_share_cents, **overrides)
    return get_success_data(api_client.vest_tranche(tranche_id, payload, headers))


def allocate_taxes(event_id, headers=ADMIN):
    return get_success_data(api_client.allocate_taxes(event_id, headers))


def settle_event(event_id, headers=ADMIN):
    return get_success_data(api_client.settle_vesting_event(event_id, headers))


def reverse_event(event_id, headers=ADMIN, reversal_reason="Administrative correction."):
    payload = reverse_payload(reversal_reason)
    return get_success_data(api_client.reverse_vesting_event(event_id, payload, headers))


def list_tax_allocations(event_id, headers=ADMIN):
    response = api_client.list_event_tax_allocations(event_id, headers)
    return get_success_data(response)


def setup_vested_event(clock="2026-01-05T09:00:00Z", vest_clock="2026-07-01T12:00:00Z",
                       fmv_per_share_cents=5000, withholding_method=None,
                       target_shares=1000, scheduled_vest_date="2026-07-01",
                       plan_overrides=None, participant_overrides=None,
                       window_overrides=None, grant_overrides=None):
    """Carry one TIME tranche through to VESTED and return its fresh settlement.

    Returns a dict with ``plan``, ``participant``, ``window``, ``grant``,
    ``tranche`` and ``event``. The settlement is PENDING_ALLOCATION /
    PENDING_TAX, so callers can allocate and settle from here.
    """
    grant_overrides = dict(grant_overrides or {})
    grant_overrides.setdefault("target_shares", target_shares)
    scenario = setup_granted_scenario(
        clock=clock, plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
        window_overrides=window_overrides, grant_overrides=grant_overrides,
        tranches=[{
            "tranche_index": 1,
            "vest_type": "TIME",
            "scheduled_vest_date": scheduled_vest_date,
            "target_shares": target_shares,
        }],
    )
    if vest_clock is not None:
        set_clock(vest_clock)
    extra = {}
    if withholding_method is not None:
        extra["withholding_method"] = withholding_method
    event = vest_tranche(
        scenario["tranches"][0]["id"], fmv_per_share_cents=fmv_per_share_cents, **extra
    )
    scenario["tranche"] = read_tranche(scenario["tranches"][0]["id"])
    scenario["event"] = event
    scenario["plan"] = read_plan(scenario["plan"]["id"])
    return scenario


def setup_allocated_event(jurisdictions=None, **kwargs):
    """A VESTED settlement whose taxes have been allocated.

    ``jurisdictions`` is a list of mobility-assignment keyword dicts recorded for
    the participant before the allocation runs; each must be fully contained in
    the sourcing period. When it is None a single US-CA period covering the whole
    sourcing window is recorded. Returns the ``setup_vested_event`` dict plus
    ``assignments`` and a refreshed ``event``.
    """
    scenario = setup_vested_event(**kwargs)
    if jurisdictions is None:
        jurisdictions = [{
            "jurisdiction_code": "US-CA",
            "tax_rate_bps": 4000,
            "start_date": scenario["event"]["sourcing_start_date"],
            "end_date": scenario["event"]["vest_date"],
            "workdays": 100,
        }]
    assignments = [
        create_mobility_assignment(scenario["participant"]["id"], **spec)
        for spec in jurisdictions
    ]
    scenario["assignments"] = assignments
    scenario["event"] = allocate_taxes(scenario["event"]["id"])
    return scenario


def setup_settled_event(**kwargs):
    """A settlement carried all the way to SETTLED, with its tranche at SETTLED."""
    scenario = setup_allocated_event(**kwargs)
    scenario["event"] = settle_event(scenario["event"]["id"])
    scenario["tranche"] = read_tranche(scenario["tranche"]["id"])
    scenario["grant"] = read_grant(scenario["grant"]["id"])
    scenario["plan"] = read_plan(scenario["plan"]["id"])
    return scenario


def setup_performance_scenario(clock="2026-01-05T09:00:00Z", target_value=100,
                               tranche_target_shares=1000, award_type="PSU",
                               scheduled_vest_date="2027-03-01",
                               plan_overrides=None, participant_overrides=None,
                               window_overrides=None, issue=True,
                               cycle_creator_headers=ADMIN):
    """An OPEN performance cycle with one bound PERFORMANCE tranche on an award.

    The award is carried to GRANTED when ``issue`` is true, otherwise it stops at
    APPROVED. Returns a dict with ``plan``, ``participant``, ``window``,
    ``cycle``, ``grant`` and ``tranches``.
    """
    plan, participant, window = setup_plan_participant_and_open_window(
        clock=clock, plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
        window_overrides=window_overrides,
    )
    cycle = create_cycle(
        plan["id"], headers=cycle_creator_headers, target_value=target_value
    )
    tranches = [{
        "tranche_index": 1,
        "vest_type": "PERFORMANCE",
        "scheduled_vest_date": scheduled_vest_date,
        "target_shares": tranche_target_shares,
        "performance_cycle_id": cycle["id"],
    }]
    builder = create_granted_grant if issue else create_approved_grant
    grant, rows = builder(
        plan["id"], participant["id"], tranches=tranches,
        award_type=award_type, target_shares=tranche_target_shares,
    )
    return {
        "plan": read_plan(plan["id"]),
        "participant": participant,
        "window": window,
        "cycle": cycle,
        "grant": grant,
        "tranches": rows,
    }


# ---------------------------------------------------------------------------
# Tier 5: the trading calendar, preclearance and pre-established plans
# ---------------------------------------------------------------------------
def create_preclearance(participant_id, window_id, as_participant=True, **overrides):
    """File a preclearance request. When ``as_participant`` is true the acting
    identity is the participant's own row id, which is what the ownership check
    compares against."""
    payload = create_preclearance_request_payload(
        participant_id, window_id, **overrides
    )
    headers = (
        make_participant_headers(participant_id) if as_participant else COMPLIANCE
    )
    return get_success_data(api_client.create_preclearance_request(payload, headers))


def decide_preclearance(request_id, decision, headers=COMPLIANCE, **overrides):
    payload = decide_payload(decision, **overrides)
    return get_success_data(
        api_client.decide_preclearance_request(request_id, payload, headers)
    )


def resubmit_preclearance(request_id, requested_shares, intended_trade_date,
                          headers=COMPLIANCE):
    payload = resubmit_payload(requested_shares, intended_trade_date)
    return get_success_data(
        api_client.resubmit_preclearance_request(request_id, payload, headers)
    )


def execute_preclearance(request_id, executed_shares, price_per_share_cents,
                         headers=COMPLIANCE):
    payload = execute_payload(executed_shares, price_per_share_cents)
    return get_success_data(
        api_client.execute_preclearance_request(request_id, payload, headers)
    )


def setup_preclearance_scenario(clock="2026-01-06T10:00:00Z",
                               insider_status="DESIGNATED_INSIDER",
                               window_overrides=None, request_overrides=None,
                               plan_overrides=None, participant_overrides=None,
                               decision=None):
    """An OPEN window plus one preclearance request filed by the participant.

    ``decision`` optionally drives the request through ``POST /decide`` with that
    decision, taken by a compliance identity different from the requester so the
    four-eyes control is satisfied. Returns a dict with ``plan``, ``participant``,
    ``window`` and ``request``.
    """
    participant_overrides = dict(participant_overrides or {})
    participant_overrides.setdefault("insider_status", insider_status)
    window_overrides = dict(window_overrides or {})
    window_overrides.setdefault("open_at", "2026-01-05T00:00:00Z")
    window_overrides.setdefault("close_at", "2026-03-31T00:00:00Z")
    plan, participant, window = setup_plan_participant_and_open_window(
        clock=clock, plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
        window_overrides=window_overrides,
    )
    request_overrides = dict(request_overrides or {})
    request_overrides.setdefault("intended_trade_date", "2026-01-09")
    request = create_preclearance(
        participant["id"], window["id"], **request_overrides
    )
    if decision is not None:
        request = decide_preclearance(request["id"], decision)
    return {
        "plan": read_plan(plan["id"]),
        "participant": participant,
        "window": read_window(window["id"]),
        "request": request,
    }


def adopt_trading_plan(participant_id, expected_participant_version,
                       as_participant=True, **overrides):
    """Adopt a Rule 10b5-1 pre-established plan. The optimistic-concurrency field
    is mandatory, so callers must quote the participant's observed version."""
    payload = create_trading_plan_payload(
        participant_id, expected_participant_version, **overrides
    )
    headers = (
        make_participant_headers(participant_id) if as_participant else COMPLIANCE
    )
    return get_success_data(api_client.create_trading_plan(payload, headers))


def activate_trading_plan(trading_plan_id, headers=COMPLIANCE):
    return get_success_data(api_client.activate_trading_plan(trading_plan_id, headers))


def setup_adopted_trading_plan(clock="2026-01-06T10:00:00Z",
                              insider_status="DESIGNATED_INSIDER",
                              plan_overrides=None, participant_overrides=None,
                              trading_plan_overrides=None):
    """One participant holding a freshly adopted plan in PENDING_COOLING_OFF.

    Returns a dict with ``plan``, ``participant`` and ``trading_plan``.
    """
    participant_overrides = dict(participant_overrides or {})
    participant_overrides.setdefault("insider_status", insider_status)
    plan, participant = setup_plan_and_participant(
        clock=clock, plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
    )
    trading_plan = adopt_trading_plan(
        participant["id"], participant["version"], **(trading_plan_overrides or {})
    )
    return {
        "plan": plan,
        "participant": read_participant(participant["id"]),
        "trading_plan": trading_plan,
    }


def setup_effective_trading_plan(activation_clock, **kwargs):
    """An adopted plan carried through its cooling-off period to EFFECTIVE."""
    scenario = setup_adopted_trading_plan(**kwargs)
    set_clock(activation_clock, COMPLIANCE)
    scenario["trading_plan"] = activate_trading_plan(scenario["trading_plan"]["id"])
    scenario["participant"] = read_participant(scenario["participant"]["id"])
    return scenario


def list_reports(participant_id, headers=COMPLIANCE, params=None):
    return get_success_data(
        api_client.list_participant_transaction_reports(
            participant_id, headers, params=params
        )
    )


def file_report(report_id, headers=COMPLIANCE):
    return get_success_data(api_client.file_transaction_report(report_id, headers))


def setup_insider_settlement_report(clock="2026-01-05T09:00:00Z",
                                   vest_clock="2026-07-01T12:00:00Z",
                                   insider_status="SECTION_16_OFFICER", **kwargs):
    """Settle one insider's vesting so the settlement mints a Section 16 report.

    Returns the ``setup_settled_event`` dict plus ``report``.
    """
    participant_overrides = dict(kwargs.pop("participant_overrides", None) or {})
    participant_overrides.setdefault("insider_status", insider_status)
    scenario = setup_settled_event(
        clock=clock, vest_clock=vest_clock,
        participant_overrides=participant_overrides, **kwargs
    )
    reports = list_reports(scenario["participant"]["id"])
    scenario["report"] = reports[0] if reports else None
    return scenario


def setup_authority_scenario(clock="2026-06-01T09:00:00Z", plan_overrides=None,
                            participant_overrides=None, authority_overrides=None,
                            delegate_user_id="officer-1"):
    """An ACTIVE plan, an ACTIVE participant and one ACTIVE delegation whose term
    contains the clock date. Returns ``(plan, participant, authority)``."""
    plan, participant = setup_plan_and_participant(
        clock=clock, plan_overrides=plan_overrides,
        participant_overrides=participant_overrides,
    )
    authority_overrides = dict(authority_overrides or {})
    authority_overrides.setdefault("delegate_user_id", delegate_user_id)
    authority = create_authority(plan["id"], **authority_overrides)
    return plan, participant, authority


def next_employee_number(prefix="E"):
    return unique_employee_number(prefix)


def next_metric_code(prefix="METRIC"):
    return unique_metric_code(prefix)


def next_quarter_label(prefix="Q"):
    return unique_quarter_label(prefix)
