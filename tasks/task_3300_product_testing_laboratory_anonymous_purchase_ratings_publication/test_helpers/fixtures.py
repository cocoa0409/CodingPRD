"""Composite setup helpers — multi-step preconditions built only from public API calls.

Every fixture builds from scratch (the harness restarts the server before each test,
so the database is always empty at test start).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_product_category_payload,
    create_test_program_payload,
    create_lab_protocol_payload,
    create_test_sample_payload,
    create_po_line_payload,
    create_purchase_order_payload,
    create_measurement_payload,
    create_survey_wave_payload,
    create_rating_publication_payload,
    create_member_payload,
)
from .test_users import (
    make_member_headers,
    make_lab_manager_headers,
    make_editorial_director_headers,
    make_purchasing_agent_headers,
    TEST_USERS,
)

LM = TEST_USERS["lab_manager_headers"]
MO = TEST_USERS["methodology_officer_headers"]
PA = TEST_USERS["purchasing_agent_headers"]
CO = TEST_USERS["compliance_officer_headers"]
LT = TEST_USERS["lab_technician_headers"]
SD = TEST_USERS["survey_director_headers"]
CE = TEST_USERS["content_editor_headers"]
SO = TEST_USERS["safety_officer_headers"]
ED = TEST_USERS["editorial_director_headers"]


# ---------------------------------------------------------------------------
# Tier 1: simple creators / state progression
# ---------------------------------------------------------------------------

def create_category(**overrides):
    """Create a ProductCategory; returns the created category dict."""
    resp = api_client.create_product_category(create_product_category_payload(**overrides), LM)
    return get_success_data(resp)


def create_program(category_id, proposer_id="lm-1", **overrides):
    """Create a TestProgram (PROPOSED) under a category. Returns program dict."""
    headers = make_lab_manager_headers(proposer_id)
    resp = api_client.create_test_program(
        create_test_program_payload(category_id, **overrides), headers
    )
    return get_success_data(resp)


def create_active_protocol(category, **overrides):
    """Create a LabProtocol and walk it DRAFT -> IN_REVIEW -> ACTIVE.

    Bumps the category version as a side effect. Returns the ACTIVE protocol dict.
    """
    resp = api_client.create_lab_protocol(
        create_lab_protocol_payload(category["id"], **overrides), LM
    )
    proto = get_success_data(resp)
    api_client.transition_lab_protocol(proto["id"], {"action": "submit_review"}, LM)
    resp = api_client.transition_lab_protocol(
        proto["id"],
        {"action": "activate", "expected_category_version": category["version"]},
        MO,
    )
    return get_success_data(resp)


def approve_program(program, approver_id="ed-1"):
    """PROPOSED -> APPROVED. Returns approved program dict."""
    resp = api_client.transition_test_program(
        program["id"], {"action": "approve"}, make_editorial_director_headers(approver_id)
    )
    return get_success_data(resp)


def create_sample(program_id, **overrides):
    """Create a TestSample (PLANNED). Returns sample dict."""
    resp = api_client.create_test_sample(
        create_test_sample_payload(program_id, **overrides), LM
    )
    return get_success_data(resp)


def create_verified_po(program_id, lines, buyer_alias="alias-1",
                       placer_id="pa-1", verifier_id="co-1", **overrides):
    """Create a PO and walk it DRAFT -> PLACED -> RECEIVED -> VERIFIED.

    Returns the VERIFIED purchase order dict.
    """
    resp = api_client.create_purchase_order(
        create_purchase_order_payload(program_id, lines, buyer_alias=buyer_alias, **overrides),
        PA,
    )
    po = get_success_data(resp)
    api_client.transition_purchase_order(
        po["id"], {"action": "place"}, make_purchasing_agent_headers(placer_id)
    )
    api_client.transition_purchase_order(
        po["id"], {"action": "receive"}, make_purchasing_agent_headers(placer_id)
    )
    resp = api_client.transition_purchase_order(
        po["id"], {"action": "verify"},
        TEST_USERS["compliance_officer_headers"] if verifier_id == "co-1"
        else make_compliance_officer_headers(verifier_id),
    )
    return get_success_data(resp)


def make_compliance_officer_headers(user_id):
    from prd_bench_local_runner.testing import build_user_headers
    return build_user_headers(user_id, "ComplianceOfficer")


# ---------------------------------------------------------------------------
# Tier 2: hierarchy — category + program + protocol + sample
# ---------------------------------------------------------------------------

def setup_category_program_protocol_sample(
    category_name="Washers",
    protocol_code="WSH-01",
    model_label="WashA",
    required_units=1,
    repeat_min=1,
    perf_weight=60,
    reliability_weight=30,
    budget_cents=500000,
    measurement_value=90,
    **category_overrides,
):
    """Category + program APPROVED + ACTIVE protocol + one PLANNED sample.

    Returns dict with keys: category, protocol, program, sample.
    Note: protocol activation bumps the category version; the returned category
    dict is refreshed after activation.
    """
    category = create_category(name=category_name, **category_overrides)
    program = create_program(category["id"], budget_cents=budget_cents)
    protocol = create_active_protocol(
        category,
        protocol_code=protocol_code,
        measurement_repeat_min=repeat_min,
        perf_weight_pct=perf_weight,
        reliability_weight_pct=reliability_weight,
    )
    program = approve_program(program)
    sample = create_sample(program["id"], model_label=model_label, required_units=required_units)
    category = get_success_data(api_client.get_product_category(category["id"], LM))
    return {
        "category": category,
        "protocol": protocol,
        "program": program,
        "sample": sample,
    }


def setup_program_sourcing(**kwargs):
    """setup_category_program_protocol_sample + start_sourcing (samples -> SOURCING)."""
    ctx = setup_category_program_protocol_sample(**kwargs)
    resp = api_client.transition_test_program(
        ctx["program"]["id"], {"action": "start_sourcing"}, LM
    )
    ctx["program"] = get_success_data(resp)
    ctx["sample"] = get_success_data(api_client.get_test_sample(ctx["sample"]["id"], LM))
    return ctx


def setup_program_testing(measurement_value=90, metric_code="WASH", **kwargs):
    """Full pipeline to TESTING with sourcing satisfied and measurements recorded
    sufficient for testing_complete (repeat_min per unit, one metric)."""
    ctx = setup_program_sourcing(**kwargs)
    sample = ctx["sample"]
    program = ctx["program"]
    lines = [
        create_po_line_payload(sample["id"], unit_price_cents=50000, qty=sample["required_units"], tax_rate_bp=0)
    ]
    create_verified_po(program["id"], lines)
    resp = api_client.transition_test_program(program["id"], {"action": "start_testing"}, LM)
    ctx["program"] = get_success_data(resp)
    ctx["sample"] = get_success_data(api_client.get_test_sample(sample["id"], LM))
    # record repeat_min measurements per unit so testing_complete becomes true
    proto = get_success_data(api_client.get_lab_protocol(ctx["protocol"]["id"], LM))
    repeat_min = proto["measurement_repeat_min"]
    for unit_index in range(1, sample["required_units"] + 1):
        for _ in range(repeat_min):
            resp = api_client.create_measurement(
                create_measurement_payload(
                    sample["id"], unit_index=unit_index,
                    metric_code=metric_code, value_num=measurement_value,
                ),
                LT,
            )
            get_success_data(resp)
    ctx["sample"] = get_success_data(api_client.get_test_sample(sample["id"], LM))
    return ctx


def setup_program_scoring(**kwargs):
    """Full pipeline to SCORING (lab_score computed)."""
    ctx = setup_program_testing(**kwargs)
    resp = api_client.transition_test_program(
        ctx["program"]["id"], {"action": "start_scoring"}, LM
    )
    ctx["program"] = get_success_data(resp)
    ctx["sample"] = get_success_data(api_client.get_test_sample(ctx["sample"]["id"], LM))
    return ctx


def setup_program_ready(**kwargs):
    """Full pipeline to READY_FOR_PUBLICATION (samples SCORED)."""
    ctx = setup_program_scoring(**kwargs)
    resp = api_client.transition_test_program(
        ctx["program"]["id"], {"action": "ready"}, LM
    )
    ctx["program"] = get_success_data(resp)
    ctx["sample"] = get_success_data(api_client.get_test_sample(ctx["sample"]["id"], LM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: publication lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_publication_with_model(ctx, embargo_until="2026-09-01T00:00:00Z"):
    """On a READY_FOR_PUBLICATION context: create publication, add rated model.
    Returns the publication dict (DRAFT, model_count 1)."""
    resp = api_client.create_rating_publication(
        create_rating_publication_payload(ctx["program"]["id"], embargo_until=embargo_until),
        CE,
    )
    pub = get_success_data(resp)
    resp = api_client.transition_rating_publication(
        pub["id"], {"action": "add_rated_model", "sample_id": ctx["sample"]["id"]}, CE
    )
    return get_success_data(resp)


def create_under_review_publication(ctx, embargo_until="2026-09-01T00:00:00Z"):
    """Publication with one rated model, submitted (UNDER_REVIEW)."""
    pub = create_draft_publication_with_model(ctx, embargo_until=embargo_until)
    resp = api_client.transition_rating_publication(pub["id"], {"action": "submit"}, CE)
    return get_success_data(resp)


def create_approved_publication(ctx, embargo_until="2026-09-01T00:00:00Z"):
    """Publication UNDER_REVIEW -> APPROVED with fresh OCC version."""
    pub = create_under_review_publication(ctx, embargo_until=embargo_until)
    prog = get_success_data(api_client.get_test_program(ctx["program"]["id"], ED))
    resp = api_client.transition_rating_publication(
        pub["id"], {"action": "approve", "expected_program_version": prog["version"]}, ED
    )
    return get_success_data(resp)


def setup_published_publication(embargo_until="2026-09-01T00:00:00Z", **kwargs):
    """Full pipeline to a PUBLISHED publication.

    Returns ctx dict with keys category, protocol, program, sample, publication.
    Program is PUBLISHED after this."""
    ctx = setup_program_ready(**kwargs)
    pub = create_approved_publication(ctx, embargo_until=embargo_until)
    resp = api_client.transition_rating_publication(pub["id"], {"action": "publish"}, ED)
    ctx["publication"] = get_success_data(resp)
    ctx["program"] = get_success_data(api_client.get_test_program(ctx["program"]["id"], LM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: members / subscriptions / waves
# ---------------------------------------------------------------------------

def create_member_with_subscription(email="m1@x.com", full_name="M One",
                                    plan_tier="DIGITAL",
                                    term_start="2026-09-01T00:00:00Z",
                                    term_end="2027-09-01T00:00:00Z"):
    """Register a member and add one subscription. Returns the member dict."""
    resp = api_client.create_member(
        create_member_payload(email=email, full_name=full_name),
        make_member_headers("member-registrar"),
    )
    member = get_success_data(resp)
    resp = api_client.transition_member(
        member["id"],
        {"action": "add_subscription", "plan_tier": plan_tier,
         "term_start": term_start, "term_end": term_end},
        make_member_headers(member["id"]),
    )
    return get_success_data(resp)


def setup_open_wave(category_name="Dryers", min_responses=1,
                   field_start="2026-09-01T00:00:00Z",
                   field_end="2026-09-05T00:00:00Z"):
    """Create a category and an OPEN survey wave. Returns (category, wave)."""
    category = create_category(name=category_name, market_share_pct=20, member_interest_pct=20)
    resp = api_client.create_survey_wave(
        create_survey_wave_payload(
            category["id"], field_start=field_start,
            field_end=field_end, min_responses=min_responses,
        ),
        SD,
    )
    return category, get_success_data(resp)


def set_clock(to_iso8601):
    """Advance the logical clock. Returns response data."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, LM))
