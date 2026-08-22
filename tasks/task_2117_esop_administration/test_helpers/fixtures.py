"""Composite setup helpers.

Every test starts against an empty database and a logical clock parked at
2026-08-01T00:00:00Z, so these helpers rebuild whole precondition chains out of
PRD-declared endpoints only:

    clock -> plan -> [loan] -> participants -> close-year -> valuation ->
    approve -> allocation run -> finalize -> terminate -> election ->
    commence -> pay installment -> put option exercise -> reserve funding

Identity threading: `Participant` is the one entity-backed role, so every
ownership-gated call made here uses `make_participant_headers(participant["id"])`
with the real participant id — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_allocation_run_payload,
    create_distribution_election_payload,
    create_loan_payload,
    create_loan_payment_payload,
    create_participant_payload,
    create_plan_payload,
    create_put_option_exercise_payload,
    create_valuation_payload,
    terminate_payload,
)
from .test_users import TEST_USERS, make_participant_headers

SPONSOR = TEST_USERS["sponsor_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
TRUSTEE_ALT = TEST_USERS["trustee_alt_headers"]
ADMIN = TEST_USERS["admin_headers"]
ADMIN_ALT = TEST_USERS["admin_alt_headers"]

DEFAULT_CLOCK = "2026-03-02T00:00:00Z"

# Named scenario profiles reused across the suite.
CEDAR_VALLEY_PLAN = {
    "plan_name": "Cedar Valley Foods ESOP",
    "sponsor_name": "Cedar Valley Foods LLC",
    "vesting_schedule": "CLIFF_3YR",
    "distribution_policy": "LUMP_SUM",
}
CEDAR_VALLEY_PARTICIPANT = {
    "employee_number": "E-100",
    "date_of_birth": "1975-07-04",
    "hire_date": "2012-02-01",
    "eligible_compensation_cents": 34_500_000,
}
NORTHGATE_PLAN = {
    "plan_name": "Northgate Tooling ESOP",
    "sponsor_name": "Northgate Tooling Inc.",
    "vesting_schedule": "GRADED_6YR",
    "service_measurement_method": "TERMINATION_DATE_MEASURE",
    "annual_additions_limit_cents": 6_900_000,
}
NORTHGATE_PARTICIPANT = {
    "employee_number": "E-201",
    "date_of_birth": "1985-06-10",
    "hire_date": "2021-03-01",
    "eligible_compensation_cents": 34_500_000,
}
IRONWOOD_PLAN = {
    "plan_name": "Ironwood Manufacturing ESOP",
    "sponsor_name": "Ironwood Manufacturing Inc.",
    "vesting_schedule": "GRADED_6YR",
    "service_measurement_method": "TERMINATION_DATE_MEASURE",
    "distribution_policy": "FIVE_YEAR_INSTALLMENT",
    "annual_compensation_limit_cents": 34_500_000,
    "annual_additions_limit_cents": 6_900_000,
}
IRONWOOD_PARTICIPANTS = [
    {"employee_number": "E-001", "date_of_birth": "1980-04-11",
     "hire_date": "2015-01-05", "eligible_compensation_cents": 40_000_000},
    {"employee_number": "E-002", "date_of_birth": "1982-09-23",
     "hire_date": "2016-06-01", "eligible_compensation_cents": 20_000_000},
    {"employee_number": "E-003", "date_of_birth": "1990-02-14",
     "hire_date": "2019-03-15", "eligible_compensation_cents": 10_000_000},
]


# ---------------------------------------------------------------------------
# Tier 0: single-call helpers and reads
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=ADMIN):
    """Reposition the logical clock. Mutates no entity."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


def create_plan(**overrides):
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), SPONSOR))


def get_plan(plan_id, headers=SPONSOR):
    return get_success_data(api_client.get_plan(plan_id, headers))


def close_year(plan_id):
    return get_success_data(api_client.close_year(plan_id, SPONSOR))


def rollover_plan(plan_id):
    return get_success_data(api_client.rollover_plan(plan_id, SPONSOR))


def freeze_plan(plan_id, reason="Fiduciary review."):
    return get_success_data(api_client.freeze_plan(plan_id, {"reason": reason}, TRUSTEE))


def create_participant(plan_id, **overrides):
    return get_success_data(
        api_client.create_participant(create_participant_payload(plan_id, **overrides), SPONSOR)
    )


def get_participant(participant_id, headers=SPONSOR):
    return get_success_data(api_client.get_participant(participant_id, headers))


def terminate_participant(participant_id, termination_date="2026-01-15",
                          termination_reason="TERMINATION"):
    return get_success_data(
        api_client.terminate_participant(
            participant_id, terminate_payload(termination_date, termination_reason), SPONSOR
        )
    )


def create_loan(plan_id, **overrides):
    return get_success_data(api_client.create_loan(create_loan_payload(plan_id, **overrides), SPONSOR))


def get_loan(loan_id, headers=ADMIN):
    return get_success_data(api_client.get_loan(loan_id, headers))


def record_loan_payment(loan_id, payment_date="2026-06-30",
                        principal_cents=400_000_000, interest_cents=200_000_000):
    return get_success_data(
        api_client.create_loan_payment(
            create_loan_payment_payload(loan_id, payment_date, principal_cents, interest_cents),
            ADMIN,
        )
    )


def submit_valuation(plan_id, expected_plan_version=None, headers=APPRAISER, **overrides):
    """Submit an appraisal. Reads the plan's live version when none is supplied."""
    if expected_plan_version is None:
        expected_plan_version = get_plan(plan_id)["version"]
    payload = create_valuation_payload(plan_id, expected_plan_version, **overrides)
    return get_success_data(api_client.create_valuation(payload, headers))


def get_valuation(valuation_id, headers=TRUSTEE):
    return get_success_data(api_client.get_valuation(valuation_id, headers))


def approve_valuation(valuation_id, headers=TRUSTEE):
    return get_success_data(api_client.approve_valuation(valuation_id, headers))


def create_allocation_run(plan_id, valuation_id, contributed_shares=500, plan_year=2026,
                          expected_plan_version=None, headers=ADMIN):
    if expected_plan_version is None:
        expected_plan_version = get_plan(plan_id)["version"]
    payload = create_allocation_run_payload(
        plan_id, valuation_id, expected_plan_version,
        contributed_shares=contributed_shares, plan_year=plan_year,
    )
    return get_success_data(api_client.create_allocation_run(payload, headers))


def get_allocation_run(run_id, headers=ADMIN):
    return get_success_data(api_client.get_allocation_run(run_id, headers))


def finalize_run(run_id, headers=ADMIN_ALT):
    """Finalize under a different administrator than the one that opened the run."""
    return get_success_data(api_client.finalize_allocation_run(run_id, headers))


def void_run(run_id, reason="Restated appraisal, allocation withdrawn."):
    return get_success_data(api_client.void_allocation_run(run_id, {"reason": reason}, TRUSTEE))


def list_share_allocations(**params):
    return get_success_data(api_client.list_share_allocations(ADMIN, params=params))


def get_allocation_line(run_id, participant_id):
    """The single allocation line crediting `participant_id` in `run_id`."""
    rows = list_share_allocations(allocation_run_id=run_id, participant_id=participant_id)
    assert len(rows) == 1, (
        f"Setup expected exactly one allocation line for participant {participant_id} "
        f"in run {run_id}, found {len(rows)}"
    )
    return rows[0]


def list_forfeiture_events(**params):
    return get_success_data(api_client.list_forfeiture_events(ADMIN, params=params))


def list_statements(**params):
    return get_success_data(api_client.list_participant_statements(ADMIN, params=params))


def get_statement_for(run_id, participant_id=None):
    params = {"allocation_run_id": run_id}
    if participant_id is not None:
        params["participant_id"] = participant_id
    rows = list_statements(**params)
    assert rows, f"Setup expected a statement for run {run_id}"
    return rows[0]


def create_election(participant_id, election_type="TERMINATION", requested_shares=1,
                    headers=None):
    """Raise an election. Defaults to the owning participant's own identity."""
    if headers is None:
        headers = make_participant_headers(participant_id)
    payload = create_distribution_election_payload(
        participant_id, election_type=election_type, requested_shares=requested_shares
    )
    return get_success_data(api_client.create_distribution_election(payload, headers))


def get_election(election_id, headers=ADMIN):
    return get_success_data(api_client.get_distribution_election(election_id, headers))


def commence_election(election_id):
    return get_success_data(api_client.commence_distribution_election(election_id, ADMIN))


def list_installments(election_id):
    return get_success_data(
        api_client.list_installment_payments(
            ADMIN, params={"distribution_election_id": election_id}
        )
    )


def get_installment(installment_id, headers=ADMIN):
    return get_success_data(api_client.get_installment_payment(installment_id, headers))


def pay_installment(installment_id):
    return get_success_data(api_client.pay_installment_payment(installment_id, ADMIN))


def raise_exercise(election_id, shares_tendered, participant_id):
    """Raise a put option exercise as the owning participant."""
    payload = create_put_option_exercise_payload(election_id, shares_tendered)
    return get_success_data(
        api_client.create_put_option_exercise(payload, make_participant_headers(participant_id))
    )


def get_exercise(exercise_id, headers=TRUSTEE):
    return get_success_data(api_client.get_put_option_exercise(exercise_id, headers))


def fund_exercise(exercise_id, headers=TRUSTEE):
    return get_success_data(api_client.fund_put_option_exercise(exercise_id, headers))


def settle_exercise(exercise_id, headers=TRUSTEE):
    return get_success_data(api_client.settle_put_option_exercise(exercise_id, headers))


def cancel_exercise(exercise_id, reason="Participant withdrew the tender.", headers=TRUSTEE):
    return get_success_data(
        api_client.cancel_put_option_exercise(exercise_id, {"reason": reason}, headers)
    )


def deposit_repurchase_funding(plan_id, amount_cents):
    return get_success_data(
        api_client.deposit_repurchase_funding(plan_id, {"amount_cents": amount_cents}, TRUSTEE)
    )


def run_repurchase_sweep(plan_id, headers=TRUSTEE):
    return get_success_data(api_client.run_repurchase_sweep(plan_id, headers))


# ---------------------------------------------------------------------------
# Tier 1 / 2: plan hierarchy with an approved price
# ---------------------------------------------------------------------------
def setup_plan_with_price(plan_overrides=None, participants=None, loan=None,
                          valuation_overrides=None, clock=DEFAULT_CLOCK,
                          approve=True):
    """clock -> plan -> [loan] -> participants -> close-year -> valuation -> approve.

    `participants` is a list of participant-payload override dicts (plan_id is
    supplied here). `loan` is an override dict — pass `{}` for the default
    600000-share pledge, or None for an unlevered plan.

    Returns dict(plan, participants, loan, valuation).
    """
    if clock:
        set_clock(clock, SPONSOR)
    plan = create_plan(**(plan_overrides or {}))
    loan_row = create_loan(plan["id"], **loan) if loan is not None else None
    people = [create_participant(plan["id"], **(p or {})) for p in (participants or [])]
    plan = close_year(plan["id"])
    valuation = submit_valuation(
        plan["id"], expected_plan_version=plan["version"], **(valuation_overrides or {})
    )
    if approve:
        valuation = approve_valuation(valuation["id"])
    return {
        "plan": get_plan(plan["id"]),
        "participants": people,
        "loan": loan_row,
        "valuation": valuation,
    }


def setup_draft_run(contributed_shares=500, plan_year=2026, **kwargs):
    """setup_plan_with_price plus one DRAFT allocation run opened by tpa-01."""
    ctx = setup_plan_with_price(**kwargs)
    ctx["run"] = create_allocation_run(
        ctx["plan"]["id"], ctx["valuation"]["id"],
        contributed_shares=contributed_shares, plan_year=plan_year,
        expected_plan_version=ctx["plan"]["version"],
    )
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    return ctx


def setup_finalized_run(contributed_shares=500, plan_year=2026, **kwargs):
    """setup_draft_run plus a finalize executed by tpa-02.

    Returns the same dict with `run`, `plan` and `participants` refreshed.
    """
    ctx = setup_draft_run(contributed_shares=contributed_shares, plan_year=plan_year, **kwargs)
    ctx["run"] = finalize_run(ctx["run"]["id"])
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    ctx["participants"] = [get_participant(p["id"]) for p in ctx["participants"]]
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: named scenario shortcuts
# ---------------------------------------------------------------------------
def setup_ironwood_draft_run(contributed_shares=2000, plan_overrides=None):
    """Three-participant Ironwood plan: a loan pledging 600000 shares gives the
    trust 6000 basis points of ownership and an approved price of 7875 cents.
    Returns dict(plan, participants, loan, valuation, run) with the run DRAFT."""
    overrides = dict(IRONWOOD_PLAN)
    overrides.update(plan_overrides or {})
    return setup_draft_run(
        contributed_shares=contributed_shares,
        plan_overrides=overrides,
        participants=IRONWOOD_PARTICIPANTS,
        loan={},
    )


def setup_ironwood_finalized_run(contributed_shares=2000, plan_overrides=None):
    """setup_ironwood_draft_run walked through finalize: awards are 876 / 749 / 375."""
    ctx = setup_ironwood_draft_run(contributed_shares, plan_overrides)
    ctx["run"] = finalize_run(ctx["run"]["id"])
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    ctx["participants"] = [get_participant(p["id"]) for p in ctx["participants"]]
    return ctx


def setup_forfeited_participant(plan_overrides=None, participant_overrides=None,
                                contributed_shares=968, clock="2026-02-01T00:00:00Z",
                                termination_date="2026-01-15",
                                termination_reason="TERMINATION", terminate=True):
    """Northgate plan (GRADED_6YR / TERMINATION_DATE_MEASURE): one participant
    hired 2021-03-01 takes the whole 968-share pool, then separates.

    A plain TERMINATION on 2026-01-15 measures 4 years of service and 60 percent
    vesting, forfeiting 388 of the 968 shares.

    Returns dict(plan, participant, valuation, run).
    """
    overrides = dict(NORTHGATE_PLAN)
    overrides.update(plan_overrides or {})
    person = dict(NORTHGATE_PARTICIPANT)
    person.update(participant_overrides or {})
    ctx = setup_finalized_run(
        contributed_shares=contributed_shares,
        plan_overrides=overrides,
        participants=[person],
        clock=clock,
    )
    if terminate:
        terminate_participant(ctx["participants"][0]["id"], termination_date, termination_reason)
        ctx["participants"] = [get_participant(ctx["participants"][0]["id"])]
        ctx["plan"] = get_plan(ctx["plan"]["id"])
    ctx["participant"] = ctx["participants"][0]
    return ctx


def setup_cedar_valley_distribution(plan_overrides=None, contributed_shares=900,
                                    clock="2026-04-01T00:00:00Z",
                                    termination_date="2026-03-31",
                                    requested_shares=None, commence=True, pay=True):
    """Cedar Valley LUMP_SUM plan at an approved price of 7125 cents.

    Its sole participant takes the whole pool, separates, raises a lump-sum
    election for the entire balance, has it commenced and its single installment
    paid — which opens a put option window on the payment date and closes it 59
    days later.

    Returns dict(plan, participant, participant_headers, valuation, run,
    election, installment).
    """
    overrides = dict(CEDAR_VALLEY_PLAN)
    overrides.update(plan_overrides or {})
    ctx = setup_finalized_run(
        contributed_shares=contributed_shares,
        plan_overrides=overrides,
        participants=[dict(CEDAR_VALLEY_PARTICIPANT)],
        clock=clock,
    )
    participant = ctx["participants"][0]
    terminate_participant(participant["id"], termination_date, "TERMINATION")
    participant = get_participant(participant["id"])
    shares = requested_shares if requested_shares is not None else participant["allocated_shares"]
    election = create_election(participant["id"], "TERMINATION", shares)
    installment = None
    if commence:
        election = commence_election(election["id"])
        installment = list_installments(election["id"])[0]
        if pay:
            installment = pay_installment(installment["id"])
    ctx["participant"] = get_participant(participant["id"])
    ctx["participants"] = [ctx["participant"]]
    ctx["participant_headers"] = make_participant_headers(participant["id"])
    ctx["election"] = get_election(election["id"])
    ctx["installment"] = installment
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    return ctx


def setup_two_pending_exercises(sweep_mode="STRICT_ORDER", reserve_floor_cents=0,
                                deposit_cents=3_000_000, big_shares=500, small_shares=400,
                                fund_first=False):
    """Cedar Valley distribution plus two PENDING put option exercises — the
    larger one raised first — and a reserve deposit.

    At 7125 cents a share the two exercises are worth 3562500 and 2850000 cents.

    Returns dict(plan, participant, election, ex_big, ex_small, ...).
    """
    ctx = setup_cedar_valley_distribution(
        plan_overrides={"sweep_mode": sweep_mode,
                        "repurchase_reserve_floor_cents": reserve_floor_cents}
    )
    ctx["ex_big"] = raise_exercise(ctx["election"]["id"], big_shares, ctx["participant"]["id"])
    ctx["ex_small"] = raise_exercise(ctx["election"]["id"], small_shares, ctx["participant"]["id"])
    if deposit_cents:
        deposit_repurchase_funding(ctx["plan"]["id"], deposit_cents)
    if fund_first:
        ctx["ex_big"] = fund_exercise(ctx["ex_big"]["id"])
        ctx["ex_small"] = get_exercise(ctx["ex_small"]["id"])
    ctx["participant"] = get_participant(ctx["participant"]["id"])
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    return ctx
