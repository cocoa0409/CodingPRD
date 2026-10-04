"""Composite setup helpers for the dealer-survey test suite.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Helpers use
the lenient get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_region_payload,
    create_dealer_payload,
    create_department_payload,
    create_customer_payload,
    create_question_set_payload,
    create_wave_payload,
    create_transaction_payload,
    create_appeal_payload,
    create_flag_payload,
    create_statement_payload,
    create_action_plan_payload,
)
from .test_users import (
    TEST_USERS,
    make_dealer_principal_headers,
    make_customer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
VENDOR = TEST_USERS["survey_vendor_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
RM = TEST_USERS["regional_manager_headers"]
FC = TEST_USERS["field_consultant_headers"]

CLOCK_START = "2026-09-01T00:00:00Z"
PERIOD_START = "2026-09-01T00:00:00Z"
PERIOD_END = "2026-10-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: basic network skeleton
# ---------------------------------------------------------------------------

def reset_clock(current_utc=CLOCK_START):
    get_success_data(api_client.set_clock(current_utc, ADMIN))


def setup_region(code="NE", name="Northeast"):
    return get_success_data(api_client.create_region(
        create_region_payload(code=code, name=name), ADMIN
    ))


def setup_dealer(region_id, code="D1", name="Dealer"):
    return get_success_data(api_client.create_dealer(
        create_dealer_payload(region_id, dealer_code=code, name=name), ADMIN
    ))


def setup_department(dealer_id, kind="SALES", name="Sales"):
    return get_success_data(api_client.create_department(
        create_department_payload(dealer_id, kind=kind, name=name), ADMIN
    ))


def setup_customer(full_name="Cust", email="c@x.com", phone="5551234567", **kw):
    return get_success_data(api_client.create_customer(
        create_customer_payload(full_name=full_name, email=email, phone=phone, **kw),
        ADMIN,
    ))


def setup_active_question_set(code="QS-A", questions=None, comparability_factor=1.0):
    qs = get_success_data(api_client.create_question_set(
        create_question_set_payload(
            code=code,
            questions=questions or [{"question_code": "q1", "prompt": "A", "weight": 1}],
            comparability_factor=comparability_factor,
        ),
        ADMIN,
    ))
    get_success_data(api_client.activate_question_set(qs["id"], ADMIN))
    return qs


def setup_draft_question_set(code="QS-A", questions=None, comparability_factor=1.0):
    return get_success_data(api_client.create_question_set(
        create_question_set_payload(
            code=code,
            questions=questions or [{"question_code": "q1", "prompt": "A", "weight": 1}],
            comparability_factor=comparability_factor,
        ),
        ADMIN,
    ))


def setup_wave(question_set_id, period_start=PERIOD_START, period_end=PERIOD_END):
    return get_success_data(api_client.create_wave(
        create_wave_payload(
            question_set_id, period_start=period_start, period_end=period_end
        ),
        ADMIN,
    ))


# ---------------------------------------------------------------------------
# Tier 2: one-dealer environment
# ---------------------------------------------------------------------------

def setup_dealer_env(dealer_code="D1", region_code="NE", questions=None,
                     comparability_factor=1.0, customers=1, activate_qs=True,
                     create_wave=True, period_start=PERIOD_START,
                     period_end=PERIOD_END, region=None):
    """Region + dealer + SALES department + N customers + question set
    (activated unless activate_qs=False) + optional DRAFT wave.

    Returns dict with keys: region, dealer, dept, qs, wave (or None),
    customers (list of Customer dicts).
    """
    region = region or setup_region(code=region_code)
    dealer = setup_dealer(region["id"], code=dealer_code)
    dept = setup_department(dealer["id"])
    custs = [
        setup_customer(
            full_name=f"C{i}", email=f"c{i}@x.com", phone=f"55500000{i:02d}"
        )
        for i in range(customers)
    ]
    if activate_qs:
        qs = setup_active_question_set(
            questions=questions, comparability_factor=comparability_factor
        )
    else:
        qs = setup_draft_question_set(
            questions=questions, comparability_factor=comparability_factor
        )
    wave = (
        setup_wave(qs["id"], period_start=period_start, period_end=period_end)
        if create_wave else None
    )
    return {
        "region": region,
        "dealer": dealer,
        "dept": dept,
        "qs": qs,
        "wave": wave,
        "customers": custs,
    }


# ---------------------------------------------------------------------------
# Tier 3: transactions, sampling, send/respond
# ---------------------------------------------------------------------------

def create_tx(env, customer, kind="SALE", completed_at="2026-09-05T00:00:00Z",
              margin_cents=100000, department=None):
    dept = department or env["dept"]
    return get_success_data(api_client.create_transaction(
        create_transaction_payload(
            env["dealer"]["id"], dept["id"], customer["id"],
            kind=kind, completed_at=completed_at, margin_cents=margin_cents,
        ),
        ADMIN,
    ))


def find_invitation_for_transaction(tx_id):
    data = get_success_data(api_client.list_invitations(
        ADMIN, params={"transaction_id": tx_id}
    ))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one invitation for transaction {tx_id}, got {data}"
    )
    return data[0]


def list_wave_invitations(wave_id, params=None):
    merged = {"limit": 100}
    if params:
        merged.update(params)
    data = get_success_data(api_client.list_wave_invitations(
        wave_id, ADMIN, params=merged
    ))
    return data


def open_wave_and_get_invitations(env):
    """Open the env's wave; returns list of invitation dicts (empty allowed)."""
    get_success_data(api_client.open_wave(env["wave"]["id"], ADMIN))
    return list_wave_invitations(env["wave"]["id"])


def open_wave_and_get_invitations_by_customer(env):
    """Open the env's wave; returns {customer_id: invitation} dict.

    Use this when the test needs to act on a specific customer's invitation
    rather than relying on list ordering (which is by created_at, id and can
    tie-break arbitrarily when multiple invitations share the same logical
    creation timestamp).
    """
    invs = open_wave_and_get_invitations(env)
    return {inv["customer_id"]: inv for inv in invs}


def send_invitation(invitation_id):
    return get_success_data(api_client.send_invitation(invitation_id, VENDOR))


def respond(invitation, customer, scores_by_code):
    """Submit a response; returns the created SurveyResponse dict."""
    payload = {
        "answers": [
            {"question_code": code, "score": score}
            for code, score in scores_by_code.items()
        ]
    }
    return get_success_data(api_client.submit_response(
        invitation["id"], payload, make_customer_headers(customer["id"])
    ))


# ---------------------------------------------------------------------------
# Tier 4: full wave lifecycle — closed wave with known dealer score
# ---------------------------------------------------------------------------

def run_wave_with_responses(env, tx_specs, response_specs, close_clock=PERIOD_END):
    """Create transactions, open wave, send + respond selected invitations,
    advance clock, close the wave.

    tx_specs: list of dicts {customer (index into env['customers']), kind,
                              completed_at, margin_cents}
    response_specs: list of dicts {tx (index into tx_specs), score (int) or
                                   answers (dict)}
    Returns dict: {transactions, invitations, responses, wave_after}.
    """
    txs = []
    for spec in tx_specs:
        cust = env["customers"][spec.get("customer", 0)]
        txs.append(create_tx(
            env, cust,
            kind=spec.get("kind", "SALE"),
            completed_at=spec.get("completed_at", "2026-09-05T00:00:00Z"),
            margin_cents=spec.get("margin_cents", 100000),
            department=spec.get("department"),
        ))
    get_success_data(api_client.open_wave(env["wave"]["id"], ADMIN))
    invitations = [find_invitation_for_transaction(tx["id"]) for tx in txs]

    responses = []
    for rspec in response_specs:
        tx_index = rspec.get("tx", 0)
        cust_index = tx_specs[tx_index].get("customer", 0)
        inv = invitations[tx_index]
        send_invitation(inv["id"])
        answers = rspec.get("answers") or {"q1": rspec["score"]}
        responses.append(respond(inv, env["customers"][cust_index], answers))

    get_success_data(api_client.set_clock(close_clock, ADMIN))
    get_success_data(api_client.close_wave(env["wave"]["id"], ADMIN))
    wave_after = get_success_data(api_client.get_wave(env["wave"]["id"], ADMIN))
    return {
        "transactions": txs,
        "invitations": invitations,
        "responses": responses,
        "wave_after": wave_after,
    }


# ---------------------------------------------------------------------------
# Tier 5: flags, appeals, statements, plans
# ---------------------------------------------------------------------------

def confirm_flag(dealer_id, kind="COACHING", evidence="ev", response_id=None):
    """Open and immediately CONFIRM a manipulation flag. Returns the flag."""
    payload = create_flag_payload(dealer_id, kind=kind, evidence=evidence)
    if response_id is not None:
        payload["response_id"] = response_id
    flag = get_success_data(api_client.create_flag(payload, AUDITOR))
    return get_success_data(api_client.resolve_flag(
        flag["id"], {"outcome": "CONFIRMED"}, AUDITOR
    ))


def file_appeal(dealer_id, response, reason="contested"):
    """File an appeal as the owning DealerPrincipal. Returns the Appeal."""
    payload = create_appeal_payload(
        response["id"], response["version"], reason=reason
    )
    return get_success_data(api_client.create_appeal(
        payload, make_dealer_principal_headers(dealer_id)
    ))


def current_wave_version(wave_id):
    return get_success_data(api_client.get_wave(wave_id, ADMIN))["version"]


def create_statement(dealer_id, wave_id):
    """Create a statement using the wave's current version. Returns statement."""
    version = current_wave_version(wave_id)
    return get_success_data(api_client.create_statement(
        create_statement_payload(dealer_id, wave_id, version), ADMIN
    ))


def create_draft_plan(dealer_id, wave_id, title="Plan", due_date="2026-12-01T00:00:00Z"):
    return get_success_data(api_client.create_action_plan(
        create_action_plan_payload(dealer_id, wave_id, title=title, due_date=due_date),
        make_dealer_principal_headers(dealer_id),
    ))


def setup_in_progress_plan(dealer_id, wave_id, due_date="2026-09-15T00:00:00Z"):
    """Plan walked DRAFT -> SUBMITTED -> APPROVED -> IN_PROGRESS."""
    plan = create_draft_plan(dealer_id, wave_id, due_date=due_date)
    dp = make_dealer_principal_headers(dealer_id)
    get_success_data(api_client.submit_action_plan(plan["id"], dp))
    get_success_data(api_client.review_action_plan(
        plan["id"], {"outcome": "APPROVED", "review_note": "ok"}, FC
    ))
    get_success_data(api_client.start_action_plan(plan["id"], dp))
    return get_success_data(api_client.get_action_plan(plan["id"], ADMIN))
