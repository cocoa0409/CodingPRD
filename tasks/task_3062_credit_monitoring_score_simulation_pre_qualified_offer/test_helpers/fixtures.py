"""Composite setup helpers — multi-step preconditions built from PRD endpoints.

Every helper builds its preconditions from scratch: the harness restarts the API
server (and therefore clears the database) before every individual pytest test, so
no state can be carried over between tests.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_UTC
from .factories import (
    create_bureau_snapshot_payload,
    create_catalog_item_payload,
    create_consent_payload,
    create_consumer_payload,
    create_content_quality_facet_payload,
    create_lender_payload,
    create_lender_program_payload,
    create_referral_payload,
    create_score_tier_payload,
    create_targeting_criterion_payload,
)
from .test_users import TEST_USERS, make_consumer_headers

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
REFEREE = TEST_USERS["referee_headers"]
BUREAU_CONNECTOR = TEST_USERS["bureau_connector_headers"]
LENDER_OPS = TEST_USERS["lender_ops_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
DATA_PROTECTION_OFFICER = TEST_USERS["data_protection_officer_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

DEFAULT_PROGRAM_CODE = "NS-LOAN-01"
DEFAULT_LIMIT_CENTS = 1_200_000


def _ok(response, label="setup call"):
    """Lenient validator for setup calls — clear 'Setup failed' errors."""
    data = get_success_data(response)
    if response.status_code >= 400:
        raise AssertionError(f"Setup failed during {label}: {response.status_code} {data}")
    return data


# ---------------------------------------------------------------------------
# Tier 1 — State progression and clock
# ---------------------------------------------------------------------------

def reset_clock(api=None):
    """Pin the logical clock to its documented start instant (PRD §2.4)."""
    api = api or api_client
    _ok(api.set_clock(CLOCK_START_UTC, PLATFORM_ADMIN), "reset clock")
    return CLOCK_START_UTC


def advance_clock(current_utc, api=None):
    """Advance the logical clock; monotonic, so the instant must not be earlier."""
    api = api or api_client
    _ok(api.set_clock(current_utc, PLATFORM_ADMIN), f"advance clock to {current_utc}")
    return current_utc


def create_active_score_tier(tier_code="GOOD", min_score=670, max_score=739,
                             factor_catalog=None, api=None):
    """Create + activate one score tier threshold. Returns the ACTIVE tier."""
    api = api or api_client
    payload = create_score_tier_payload(
        tier_code=tier_code, min_score=min_score, max_score=max_score,
        factor_catalog=factor_catalog
        or ["high_utilization", "length_of_credit_history"],
    )
    tier = _ok(api.create_score_tier(payload, PLATFORM_ADMIN), "create score tier")
    return _ok(api.activate_score_tier(tier["id"], PLATFORM_ADMIN), "activate score tier")


def create_active_catalog_item(product_kind="LOAN", product_name="Personal Loan",
                               min_score=560, max_score=720, max_dti_pct=60.0, api=None):
    """Create + activate a product catalog item. Returns the ACTIVE item."""
    api = api or api_client
    payload = create_catalog_item_payload(
        product_kind=product_kind, product_name=product_name,
        min_score=min_score, max_score=max_score, max_dti_pct=max_dti_pct,
    )
    item = _ok(api.create_catalog_item(payload, PLATFORM_ADMIN), "create catalog item")
    return _ok(api.activate_catalog_item(item["id"], PLATFORM_ADMIN), "activate catalog item")


def create_active_lender(lender_name="Northstar Bank", states_served=None, api=None):
    """Register + activate a lender. Returns the ACTIVE lender."""
    api = api or api_client
    payload = create_lender_payload(
        lender_name=lender_name, states_served=states_served or ["CA", "NY", "TX"]
    )
    lender = _ok(api.create_lender(payload, PLATFORM_ADMIN), "create lender")
    return _ok(api.activate_lender(lender["id"], PLATFORM_ADMIN), "activate lender")


def create_active_program(lender_id=None, item_id=None, program_code=DEFAULT_PROGRAM_CODE,
                          annual_fee_cents=0, intro_apr_bps=1299, api=None, **overrides):
    """Create + activate a lender program. Creates its own ACTIVE lender and
    catalog item (and score tier) when none are supplied."""
    api = api or api_client
    if item_id is None:
        create_active_score_tier(api=api)
        item_id = create_active_catalog_item(api=api)["id"]
    if lender_id is None:
        lender_id = create_active_lender(api=api)["id"]
    payload = create_lender_program_payload(
        lender_id, item_id, program_code=program_code,
        annual_fee_cents=annual_fee_cents, intro_apr_bps=intro_apr_bps, **overrides,
    )
    program = _ok(api.create_lender_program(payload, PLATFORM_ADMIN), "create program")
    return _ok(api.activate_lender_program(program["id"], PLATFORM_ADMIN), "activate program")


def add_standard_criteria(program_id, api=None):
    """Attach the default hard UTILIZATION_PCT LTE 50 and soft DTI_PCT LTE 30."""
    api = api or api_client
    hard = _ok(
        api.create_targeting_criterion(
            program_id, create_targeting_criterion_payload(), LENDER_OPS
        ),
        "create hard criterion",
    )
    soft = _ok(
        api.create_targeting_criterion(
            program_id,
            create_targeting_criterion_payload(
                criterion_field="DTI_PCT", operator="LTE", criterion_value="30",
                is_hard_requirement=False,
            ),
            LENDER_OPS,
        ),
        "create soft criterion",
    )
    return hard, soft


# ---------------------------------------------------------------------------
# Tier 2 — Entity hierarchy
# ---------------------------------------------------------------------------

def create_consumer(full_name="Maya Chen", email="maya@example.com", state_code="CA",
                    bureau_pin="4821", dti_pct=35.0, api=None):
    api = api or api_client
    payload = create_consumer_payload(
        full_name=full_name, email=email, state_code=state_code,
        bureau_pin=bureau_pin, dti_pct=dti_pct,
    )
    return _ok(api.create_consumer(payload, make_consumer_headers("pending")), "create consumer")


def grant_consent(consumer_id, api=None):
    """Grant monitoring consent as the consumer themself."""
    api = api or api_client
    return _ok(
        api.grant_monitoring_consent(consumer_id, make_consumer_headers(consumer_id)),
        "grant monitoring consent",
    )


def read_consumer_version(consumer_id, api=None, headers=None):
    api = api or api_client
    return _ok(
        api.get_consumer(consumer_id, headers or make_consumer_headers(consumer_id)),
        "read consumer",
    )["version"]


def pull_bureau_snapshot(consumer_id, score=660, balance_cents=480_000,
                         limit_cents=DEFAULT_LIMIT_CENTS, factor_codes=None, api=None,
                         **overrides):
    """Read the consumer's current version, then refresh the bureau data."""
    api = api or api_client
    version = read_consumer_version(consumer_id, api=api)
    payload = create_bureau_snapshot_payload(
        version, score=score, total_revolving_balance_cents=balance_cents,
        credit_limit_total_cents=limit_cents,
        factor_codes=factor_codes or ["high_utilization", "length_of_credit_history"],
        **overrides,
    )
    return _ok(
        api.create_bureau_snapshot(consumer_id, payload, BUREAU_CONNECTOR), "pull snapshot"
    )


def create_monitored_consumer(score=660, balance_cents=480_000, limit_cents=DEFAULT_LIMIT_CENTS,
                              factor_codes=None, email="maya@example.com", state_code="CA",
                              dti_pct=35.0, bureau_pin="4821", full_name="Maya Chen", api=None):
    """Consented consumer with one ACTIVE snapshot. Returns (consumer, snapshot)."""
    api = api or api_client
    consumer = create_consumer(
        full_name=full_name, email=email, state_code=state_code, bureau_pin=bureau_pin,
        dti_pct=dti_pct, api=api,
    )
    grant_consent(consumer["id"], api=api)
    snapshot = pull_bureau_snapshot(
        consumer["id"], score=score, balance_cents=balance_cents, limit_cents=limit_cents,
        factor_codes=factor_codes, api=api,
    )
    consumer = _ok(
        api.get_consumer(consumer["id"], make_consumer_headers(consumer["id"])),
        "re-read consumer",
    )
    return consumer, snapshot


def setup_catalog_scenario(program_code=DEFAULT_PROGRAM_CODE, tier_code="GOOD",
                           api=None, program_overrides=None):
    """ACTIVE tier + ACTIVE catalog item + ACTIVE lender + ACTIVE program with the
    standard hard/soft criteria. Returns a dict of every seeded row."""
    api = api or api_client
    tier = create_active_score_tier(tier_code=tier_code, api=api)
    item = create_active_catalog_item(api=api)
    lender = create_active_lender(api=api)
    program = create_active_program(
        lender_id=lender["id"], item_id=item["id"], program_code=program_code, api=api,
        **(program_overrides or {}),
    )
    hard, soft = add_standard_criteria(program["id"], api=api)
    return {
        "tier": tier, "item": item, "lender": lender, "program": program,
        "hard_criterion": hard, "soft_criterion": soft,
    }


# ---------------------------------------------------------------------------
# Tier 3 — Full lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_decision(consumer_id, program_id, api=None):
    api = api or api_client
    return _ok(
        api.create_prequalification(
            consumer_id, {"lender_program_id": program_id},
            make_consumer_headers(consumer_id),
        ),
        "create pre-qualification decision",
    )


def qualify_decision(decision_id, api=None):
    api = api or api_client
    return _ok(api.qualify_decision(decision_id, REFEREE), "qualify decision")


def complete_render_facets(consumer_id, run_key="seed-facet-rollup", api=None):
    """Author both scorable content topics at a passing score and roll the posture up."""
    api = api or api_client
    _ok(
        api.create_content_quality_facet(
            consumer_id, create_content_quality_facet_payload(topic="factor_explanations"),
            REFEREE,
        ),
        "create factor_explanations facet",
    )
    _ok(
        api.create_content_quality_facet(
            consumer_id,
            create_content_quality_facet_payload(topic="accuracy_education"), REFEREE,
        ),
        "create accuracy_education facet",
    )
    return _ok(api.run_ops({"run_key": run_key}, PLATFORM_ADMIN), "roll up facets")


def present_decision(decision_id, consumer_id, channel="WEB", api=None):
    api = api or api_client
    return _ok(
        api.present_decision(decision_id, {"channel": channel},
                             make_consumer_headers(consumer_id)),
        "present decision",
    )


def render_offer(offer_id, consumer_id, api=None):
    api = api or api_client
    return _ok(
        api.render_offer(offer_id, make_consumer_headers(consumer_id)), "render offer"
    )


def complete_consent(consumer_id, decision_id, api=None):
    api = api or api_client
    version = read_consumer_version(consumer_id, api=api)
    return _ok(
        api.complete_consent(
            consumer_id, decision_id, create_consent_payload(version),
            make_consumer_headers(consumer_id),
        ),
        "complete consent",
    )


def setup_prequalified_scenario(score=660, balance_cents=480_000, run_key="seed-decision",
                                api=None, program_overrides=None):
    """Consumer with an ACTIVE snapshot plus an ELIGIBLE decision on a program whose
    hard/soft criteria match the snapshot. Returns a dict of seeded rows."""
    api = api or api_client
    reset_clock(api=api)
    catalog = setup_catalog_scenario(api=api, program_overrides=program_overrides)
    consumer, snapshot = create_monitored_consumer(
        score=score, balance_cents=balance_cents, api=api
    )
    decision = create_decision(consumer["id"], catalog["program"]["id"], api=api)
    return {
        "consumer": consumer, "snapshot": snapshot, "decision": decision,
        **catalog,
    }


def setup_offer_scenario(score=660, balance_cents=480_000, run_key="seed-offer",
                         api=None, program_overrides=None):
    """Everything through PREQUALIFIED + rendered offer, consent still outstanding."""
    api = api or api_client
    ctx = setup_prequalified_scenario(
        score=score, balance_cents=balance_cents, api=api,
        program_overrides=program_overrides,
    )
    decision = qualify_decision(ctx["decision"]["id"], api=api)
    complete_render_facets(ctx["consumer"]["id"], run_key=run_key, api=api)
    offer = present_decision(decision["id"], ctx["consumer"]["id"], api=api)
    offer = render_offer(offer["id"], ctx["consumer"]["id"], api=api)
    ctx["decision"] = decision
    ctx["offer"] = offer
    return ctx


def setup_consented_scenario(score=660, balance_cents=480_000, run_key="seed-consented",
                             api=None, program_overrides=None):
    """Offer funnel plus a PENDING consent record. Returns the same dict plus consent."""
    api = api or api_client
    ctx = setup_offer_scenario(
        score=score, balance_cents=balance_cents, run_key=run_key, api=api,
        program_overrides=program_overrides,
    )
    consent = complete_consent(ctx["consumer"]["id"], ctx["decision"]["id"], api=api)
    ctx["decision"] = _ok(
        api.get_prequalification_decision(ctx["decision"]["id"], REFEREE), "re-read decision"
    )
    ctx["consent"] = consent
    return ctx


def create_referral_for(ctx, external_referral_ref="NS-L-9001", api=None):
    api = api or api_client
    return _ok(
        api.create_referral(
            create_referral_payload(ctx["offer"]["id"], external_referral_ref=external_referral_ref),
            LENDER_OPS,
        ),
        "create referral",
    )


def fund_referral(referral_id, funded_amount_cents=900_000, api=None):
    api = api or api_client
    return _ok(
        api.fund_referral(referral_id, {"funded_amount_cents": funded_amount_cents}, LENDER_OPS),
        "fund referral",
    )


def setup_funded_referral(funded_amount_cents=900_000, external_referral_ref="NS-L-9001",
                          api=None, career=None):
    """Full funnel through a FUNDED referral. Returns the scenario dict + referral."""
    ctx = career if career is not None else setup_consented_scenario(api=api)
    referral = create_referral_for(ctx, external_referral_ref=external_referral_ref, api=api)
    referral = fund_referral(referral["id"], funded_amount_cents=funded_amount_cents, api=api)
    ctx["referral"] = referral
    return ctx


def setup_contained_context(consent_ctx, external_referral_ref="NS-L-9001", api=None):
    """Alias used by tests that need the consent funnel plus an open referral."""
    ctx = dict(consent_ctx)
    ctx["referral"] = create_referral_for(
        ctx, external_referral_ref=external_referral_ref, api=api
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — Accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_consumer_at_utilization(utilization_pct, limit_cents=DEFAULT_LIMIT_CENTS, score=660,
                                  api=None, **consumer_kwargs):
    """An ACTIVE snapshot whose derived utilization lands exactly on `utilization_pct`,
    built from a balance that makes the 2-decimal rounding exact."""
    api = api or api_client
    balance = round(utilization_pct * limit_cents / 100)
    consumer, snapshot = create_monitored_consumer(
        score=score, balance_cents=balance, limit_cents=limit_cents, api=api,
        **consumer_kwargs,
    )
    return consumer, snapshot


def setup_odds_probe_consumers(utilizations, limit_cents=DEFAULT_LIMIT_CENTS, score=660,
                               api=None):
    """One consented, pulled consumer per utilization value, against a shared program
    that carries a hard criterion the caller controls. Returns (program, consumers)."""
    api = api or api_client
    consumers = []
    for idx, util in enumerate(utilizations):
        balance = round(util * limit_cents / 100)
        consumer, snapshot = create_monitored_consumer(
            score=score, balance_cents=balance, limit_cents=limit_cents, api=api,
            email=f"probe{idx}@example.com", bureau_pin=f"48{idx:02d}",
        )
        consumers.append({"consumer": consumer, "snapshot": snapshot})
    return consumers


def setup_simulation_consumer(score, balance_cents, limit_cents=DEFAULT_LIMIT_CENTS, api=None,
                              **consumer_kwargs):
    """Consented consumer with an ACTIVE snapshot, ready for a score simulation."""
    api = api or api_client
    consumer, snapshot = create_monitored_consumer(
        score=score, balance_cents=balance_cents, limit_cents=limit_cents, api=api,
        **consumer_kwargs,
    )
    return consumer, snapshot


def create_simulation(consumer_id, actions, api=None):
    api = api or api_client
    version = read_consumer_version(consumer_id, api=api)
    return _ok(
        api.create_simulation(
            consumer_id, {"actions": actions, "expected_consumer_version": version},
            make_consumer_headers(consumer_id),
        ),
        "create simulation",
    )


# ---------------------------------------------------------------------------
# Tier 5 — Finalization / terminal state shortcuts
# ---------------------------------------------------------------------------

def reverse_referral(referral_id, reason_code="LENDER_RETURNED_FUNDS", api=None):
    api = api or api_client
    return _ok(
        api.reverse_referral(referral_id, {"reason_code": reason_code}, COMPLIANCE_OFFICER),
        "reverse referral",
    )


def decline_referral(referral_id, api=None):
    api = api or api_client
    return _ok(api.decline_referral(referral_id, LENDER_OPS), "decline referral")


def read_referral_entries(referral_id, api=None):
    api = api or api_client
    return _ok(
        api.list_referral_revenue_entries(referral_id, PLATFORM_ADMIN),
        "list referral revenue entries",
    )


def reopen_decision_count(consumer_id, api=None):
    """How many decisions for this consumer are still open (ELIGIBLE or PREQUALIFIED)."""
    api = api or api_client
    rows = _ok(
        api.list_consumer_decisions(consumer_id, PLATFORM_ADMIN), "list consumer decisions"
    )
    return [d for d in rows if d["decision_status"] in ("ELIGIBLE", "PREQUALIFIED")]


# ---------------------------------------------------------------------------
# Consumer read helpers used as setup steps
# ---------------------------------------------------------------------------

def read_consumer(consumer_id, api=None):
    api = api or api_client
    return _ok(
        api.get_consumer(consumer_id, make_consumer_headers(consumer_id)), "read consumer"
    )


def read_offer(offer_id, api=None):
    api = api or api_client
    return _ok(api.get_offer(offer_id, PLATFORM_ADMIN), "read offer")


def read_referral(referral_id, api=None):
    api = api or api_client
    return _ok(api.get_referral(referral_id, PLATFORM_ADMIN), "read referral")


def read_decision(decision_id, api=None):
    api = api or api_client
    return _ok(api.get_prequalification_decision(decision_id, REFEREE), "read decision")


def list_consumer_alerts(consumer_id, api=None, params=None):
    api = api or api_client
    return _ok(
        api.list_consumer_score_alerts(consumer_id, make_consumer_headers(consumer_id),
                                       params=params),
        "list consumer score alerts",
    )


def read_consent_record(consent_id, api=None):
    api = api or api_client
    return _ok(api.get_consent_record(consent_id, PLATFORM_ADMIN), "read consent record")

def setup_monitored(api=None, score=660, balance_cents=480_000, limit_cents=DEFAULT_LIMIT_CENTS,
                    factor_codes=None, **consumer_kwargs):
    """Consented consumer with one ACTIVE snapshot. Returns a dict of the seeded rows."""
    api = api or api_client
    consumer, snapshot = create_monitored_consumer(
        score=score, balance_cents=balance_cents, limit_cents=limit_cents,
        factor_codes=factor_codes, api=api, **consumer_kwargs,
    )
    return {"consumer": consumer, "snapshot": snapshot}
