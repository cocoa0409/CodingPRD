"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only the public
API, because the server restarts (empty database, logical clock back at
2026-09-01T00:00:00Z) before every test.

Setup-call failures surface as plain AssertionError("Setup failed: ...")
via the _setup helper so a broken fixture is distinguishable from a broken
assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START,
    DEFAULT_LANGUAGE,
    DEFAULT_PERIOD,
    DEFAULT_PROGRAM,
    FAR_FUTURE_VALID_UNTIL,
)
from .factories import (
    complete_course_payload,
    create_agent_payload,
    create_call_payload,
    create_contract_payload,
    create_invoice_payload,
    create_knowledge_article_payload,
    create_quality_review_payload,
    create_queue_payload,
    create_service_level_payload,
    create_surge_window_payload,
    create_training_course_payload,
)
from .test_users import TEST_USERS, make_agent_headers

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
SUP = TEST_USERS["supervisor_headers"]
QA = TEST_USERS["quality_analyst_headers"]
KM = TEST_USERS["knowledge_manager_headers"]
SEC = TEST_USERS["security_officer_headers"]
BILL = TEST_USERS["billing_analyst_headers"]


def _setup(response, what):
    assert 200 <= response.status_code < 300, (
        f"Setup failed for {what}: HTTP {response.status_code} "
        f"{response.text[:400]}"
    )
    return get_success_data(response)


# ---------------------------------------------------------------- clock

def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin)."""
    return _setup(api_client.set_clock(to_iso8601, ADMIN), "clock set")


# ---------------------------------------------------------------- contract / service level

def create_contract(cap_absolutes=False, agency_name="State Benefits Agency"):
    payload = create_contract_payload(
        agency_name=agency_name, cap_absolutes=cap_absolutes
    )
    return _setup(api_client.create_contract(payload, ADMIN), "contract create")


def get_contract(contract_id):
    return _setup(api_client.get_contract(contract_id, ADMIN), "contract get")


def create_draft_service_level(contract_id, metric="ASA", target=30, **overrides):
    payload = create_service_level_payload(
        contract_id, metric=metric, target=target, **overrides
    )
    return _setup(api_client.create_service_level(payload, OPS), "service level create")


def activate_service_level(contract, sl_id):
    """Activate a DRAFT service level, carrying the contract's current version
    as the OCC expectation. Returns the EFFECTIVE service level."""
    payload = {
        "to_status": "EFFECTIVE",
        "expected_contract_version": contract["version"],
    }
    return _setup(
        api_client.transition_service_level(sl_id, payload, OPS),
        "service level activation",
    )


def activate_contract(contract_id):
    return _setup(
        api_client.transition_contract(contract_id, {"to_status": "ACTIVE"}, OPS),
        "contract activation",
    )


def setup_active_contract(metric="ASA", target=30, cap_absolutes=False,
                          cap_pct_of_gross=1.0, remedy_fee_cents=1000,
                          agency_name="State Benefits Agency",
                          effective_from="2026-09-01T00:00:00Z",
                          program_code=DEFAULT_PROGRAM):
    """Contract + one service level, both fully activated.

    The first service-level activation bootstraps the parent contract to
    ACTIVE in the same write (the two activation preconditions are mutually
    recursive otherwise), so no separate contract-activation call is needed.
    Returns {"contract": <refreshed ACTIVE contract>, "sl": <EFFECTIVE sl>}.
    """
    contract = create_contract(cap_absolutes=cap_absolutes, agency_name=agency_name)
    sl = create_draft_service_level(
        contract["id"], metric=metric, target=target,
        cap_pct_of_gross=cap_pct_of_gross, remedy_fee_cents=remedy_fee_cents,
        effective_from=effective_from, program_code=program_code,
    )
    sl = activate_service_level(contract, sl["id"])
    contract = get_contract(contract["id"])
    return {"contract": contract, "sl": sl}


# ---------------------------------------------------------------- staffing

def create_agent(full_name="Agent One", languages=None):
    payload = create_agent_payload(
        full_name=full_name, languages=languages or [DEFAULT_LANGUAGE]
    )
    return _setup(api_client.create_agent(payload, OPS), "agent create")


def create_course(program_code=DEFAULT_PROGRAM, **overrides):
    payload = create_training_course_payload(program_code=program_code, **overrides)
    return _setup(api_client.create_training_course(payload, KM), "course create")


def certify_agent(agent_id, course_id, valid_until=FAR_FUTURE_VALID_UNTIL):
    """Record a completion; mints the certification. Returns the completion."""
    payload = complete_course_payload(agent_id, valid_until=valid_until)
    return _setup(
        api_client.complete_training_course(course_id, payload, KM),
        "course completion",
    )


def create_certified_agent(course_id=None, program_code=DEFAULT_PROGRAM,
                           full_name="Agent One", languages=None,
                           valid_until=FAR_FUTURE_VALID_UNTIL):
    """Agent + standing certification. Returns {"agent", "course", "completion"}."""
    agent = create_agent(full_name=full_name, languages=languages)
    if course_id is None:
        course = create_course(program_code=program_code)
        course_id = course["id"]
    else:
        course = _setup(api_client.get_training_course(course_id, KM), "course get")
    completion = certify_agent(agent["id"], course_id, valid_until=valid_until)
    return {"agent": agent, "course": course, "completion": completion}


def list_certifications(params):
    resp = api_client.list_certifications(OPS, params=params)
    return _setup(resp, "certification list")


def staff_to_target(course_id, target=10, already=1):
    """Certify additional agents for the course's program so the program's
    staffing_actual reaches `target` (the baseline staffing_target of PRD
    §3.9), removing the staffing-shortfall override from compliance math."""
    for i in range(already, target):
        create_certified_agent(course_id=course_id,
                               full_name=f"Staff Agent {i}")


# ---------------------------------------------------------------- queues / calls

def create_queue(contract_id, **overrides):
    payload = create_queue_payload(contract_id, **overrides)
    return _setup(api_client.create_queue(payload, OPS), "queue create")


def setup_routable(metric="ASA", target=30, program_code=DEFAULT_PROGRAM, **contract_kwargs):
    """ACTIVE contract + EFFECTIVE service level + one certified agent + one
    OPEN general queue. Returns dict with contract/sl/agent/course/completion/queue."""
    ctx = setup_active_contract(metric=metric, target=target,
                                program_code=program_code, **contract_kwargs)
    staffing = create_certified_agent(program_code=program_code)
    queue = create_queue(ctx["contract"]["id"], program_code=program_code)
    ctx.update(staffing)
    ctx["queue"] = queue
    return ctx


def register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z", **overrides):
    payload = create_call_payload(contract_id, enqueued_at=enqueued_at, **overrides)
    return _setup(api_client.create_call(payload, SUP), "call create")


def get_call(call_id):
    return _setup(api_client.get_call(call_id, SUP), "call get")


def route_call(call_id):
    resp = api_client.transition_call(call_id, {"to_status": "ASSIGNED"}, SUP)
    return _setup(resp, "call route")


def answer_call(call, agent_id, answer_at=None):
    """Answer an ASSIGNED call as its owning agent. answer_at sets the logical
    clock first so answer_seconds is deterministic."""
    if answer_at is not None:
        set_clock(answer_at)
    resp = api_client.transition_call(
        call["id"], {"to_status": "ANSWERED"}, make_agent_headers(agent_id)
    )
    return _setup(resp, "call answer")


def complete_call(call, agent_id, end_at=None):
    if end_at is not None:
        set_clock(end_at)
    resp = api_client.transition_call(
        call["id"], {"to_status": "COMPLETED"}, make_agent_headers(agent_id)
    )
    return _setup(resp, "call complete")


def abandon_call(call_id):
    resp = api_client.transition_call(call_id, {"to_status": "ABANDONED"}, SUP)
    return _setup(resp, "call abandon")


def setup_completed_call(enqueued_at="2026-09-05T09:00:00Z",
                         answer_at="2026-09-05T09:00:20Z",
                         end_at="2026-09-05T09:05:00Z",
                         metric="ASA", target=30, **contract_kwargs):
    """Routable scenario + one COMPLETED call handled by the certified agent.
    Returns ctx with keys contract/sl/agent/course/completion/queue/call."""
    ctx = setup_routable(metric=metric, target=target, **contract_kwargs)
    call = register_call(ctx["contract"]["id"], enqueued_at=enqueued_at)
    call = route_call(call["id"])
    call = answer_call(call, ctx["agent"]["id"], answer_at=answer_at)
    call = complete_call(call, ctx["agent"]["id"], end_at=end_at)
    ctx["call"] = call
    return ctx


# ---------------------------------------------------------------- reviews / coaching

def create_review(call_id, accuracy_score=80, compliance_score=80, **overrides):
    payload = create_quality_review_payload(
        call_id, accuracy_score=accuracy_score,
        compliance_score=compliance_score, **overrides,
    )
    return _setup(api_client.create_quality_review(payload, QA), "review create")


def get_review(review_id):
    return _setup(api_client.get_quality_review(review_id, QA), "review get")


def transition_review(review_id, to_status, headers):
    resp = api_client.transition_quality_review(review_id, {"to_status": to_status}, headers)
    return _setup(resp, f"review transition {to_status}")


def list_coaching_plans(params):
    resp = api_client.list_coaching_plans(SUP, params=params)
    assert resp.status_code == 200, f"Setup failed for plan list: {resp.text[:300]}"
    body = resp.json()
    return body["data"]


# ---------------------------------------------------------------- knowledge

def create_article(program_code=DEFAULT_PROGRAM, effective_at="2026-09-10T00:00:00Z",
                   **overrides):
    payload = create_knowledge_article_payload(
        program_code=program_code, effective_at=effective_at, **overrides
    )
    return _setup(api_client.create_knowledge_article(payload, KM), "article create")


def publish_article(article_id):
    resp = api_client.transition_knowledge_article(
        article_id, {"to_status": "PUBLISHED"}, KM
    )
    return _setup(resp, "article publish")


# ---------------------------------------------------------------- surge windows

def create_surge_window(contract_id, **overrides):
    payload = create_surge_window_payload(contract_id, **overrides)
    return _setup(api_client.create_surge_window(payload, OPS), "surge window create")


def get_surge_window(window_id):
    return _setup(api_client.get_surge_window(window_id, OPS), "surge window get")


# ---------------------------------------------------------------- invoices / lines / cures

def create_invoice(contract_id, period=DEFAULT_PERIOD):
    payload = create_invoice_payload(contract_id, period=period)
    return _setup(api_client.create_invoice(payload, BILL), "invoice create")


def get_invoice(invoice_id):
    return _setup(api_client.get_invoice(invoice_id, BILL), "invoice get")


def prepare_invoice(invoice_id, headers=None):
    resp = api_client.prepare_invoice(invoice_id, headers or BILL)
    return _setup(resp, "invoice prepare")


def recompute_invoice(invoice_id, headers=None):
    resp = api_client.recompute_invoice(invoice_id, headers or BILL)
    return _setup(resp, "invoice recompute")


def list_invoice_lines(invoice_id):
    resp = api_client.list_invoice_lines(invoice_id, BILL)
    assert resp.status_code == 200, f"Setup failed for line list: {resp.text[:300]}"
    return resp.json()["data"]


def get_invoice_line(line_id):
    return _setup(api_client.get_invoice_line(line_id, BILL), "invoice line get")


def list_cure_periods(line_id):
    resp = api_client.list_line_cure_periods(line_id, BILL)
    assert resp.status_code == 200, f"Setup failed for cure list: {resp.text[:300]}"
    return resp.json()["data"]


def pay_remedy(cure_period_id, headers=None):
    resp = api_client.pay_cure_remedy(cure_period_id, headers or BILL)
    return _setup(resp, "remedy payment")


def setup_breach_invoice(answer_seconds=40, metric="ASA", target=30,
                         period=DEFAULT_PERIOD, **contract_kwargs):
    """Routable scenario with one call answered in `answer_seconds`, then an
    invoice created and prepared for `period`.

    Returns ctx with contract/sl/agent/course/completion/queue/call/invoice/line
    and cure_periods (list; empty when the line is compliant).
    """
    ctx = setup_routable(metric=metric, target=target, **contract_kwargs)
    enqueued_at = "2026-09-05T09:00:00Z"
    call = register_call(ctx["contract"]["id"], enqueued_at=enqueued_at)
    set_clock(enqueued_at)
    call = route_call(call["id"])
    hh, mm, ss = 9, 0, answer_seconds
    mm += ss // 60
    ss = ss % 60
    answer_at = f"2026-09-05T{hh:02d}:{mm:02d}:{ss:02d}Z"
    call = answer_call(call, ctx["agent"]["id"], answer_at=answer_at)
    invoice = create_invoice(ctx["contract"]["id"], period=period)
    invoice = prepare_invoice(invoice["id"])
    lines = list_invoice_lines(invoice["id"])
    cures = list_cure_periods(lines[0]["id"]) if lines else []
    ctx.update({
        "call": call,
        "invoice": invoice,
        "line": lines[0] if lines else None,
        "cure_periods": cures,
    })
    return ctx
