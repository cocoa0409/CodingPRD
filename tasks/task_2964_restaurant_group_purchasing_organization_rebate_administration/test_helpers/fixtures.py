"""Composite setup helpers built exclusively out of PRD endpoints.

The database is empty before every test, so every precondition here is created
by calling the API. Helpers are layered:

  tier 1  thin wrappers that call one endpoint and return its ``data``
  tier 2  entity creators that fill in the canonical literals
  tier 3  state-advanced entities (an ACTIVE member with an ACTIVE letter, an
          ACTIVE deal with an APPROVED rate card)
  tier 4  batch pipelines (ingest, normalize, accrue, audit)
  tier 5  named scenario composites returned as a context dict

Every helper is phased: it performs one hop and returns, so a caller can
interleave its own calls between two hops without a bundled helper invalidating
a state gate it depended on.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from . import factories as F
from .api_client import api_client
from .test_users import (
    make_analyst_headers,
    make_arbiter_headers,
    make_distributor_feed_headers,
    make_gpo_admin_headers,
    make_member_operator_headers,
    make_rep_headers,
)
from .types import (
    CountersignDecision,
    DisputeDecision,
    RateType,
    RecoveryOutcome,
)

ADMIN = make_gpo_admin_headers()
ANALYST = make_analyst_headers()
ARBITER = make_arbiter_headers()
REP = make_rep_headers()

WIDE = {"limit": C.MAX_LIMIT}


# =========================================================== tier 1/2 ======

def set_clock(current_utc: str = C.CLOCK_EPOCH, headers: dict = None) -> dict:
    """Move the logical clock. The server starts at exactly the epoch."""
    return get_success_data(api_client.set_clock(current_utc, headers or ADMIN))


def create_tier(headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_program_tier(F.program_tier_payload(**overrides), headers or ADMIN)
    )


def create_distributor(headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_distributor(F.distributor_payload(**overrides), headers or ADMIN)
    )


def create_member(tier_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_member(F.member_payload(tier_id, **overrides), headers or ADMIN)
    )


def activate_member(member_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.activate_member(member_id, headers or ADMIN))


def terminate_member(member_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.terminate_member(member_id, headers or ADMIN))


def read_member(member_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_member(member_id, headers or ADMIN))


def read_distributor(distributor_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_distributor(distributor_id, headers or ADMIN))


def submit_letter(member_id: str, distributor_id: str, headers: dict = None, **overrides) -> dict:
    """A MemberOperator submits its own letter (X-User-ID is the member id)."""
    return get_success_data(
        api_client.create_authorization_letter(
            F.authorization_letter_payload(member_id, distributor_id, **overrides),
            headers or make_member_operator_headers(member_id),
        )
    )


def countersign_letter(
    letter_id: str,
    distributor_id: str,
    decision: str = CountersignDecision.ACCEPT.value,
    headers: dict = None,
) -> dict:
    """A DistributorFeed countersigns (X-User-ID is the distributor id)."""
    return get_success_data(
        api_client.countersign_letter(
            letter_id,
            {"decision": decision},
            headers or make_distributor_feed_headers(distributor_id),
        )
    )


def revoke_letter(letter_id: str, member_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.revoke_letter(
            letter_id, headers or make_member_operator_headers(member_id)
        )
    )


def create_deal(headers: dict = None, **overrides) -> dict:
    return get_success_data(api_client.create_deal(F.deal_payload(**overrides), headers or ADMIN))


def create_second_deal(headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_deal(F.second_deal_payload(**overrides), headers or ADMIN)
    )


def activate_deal(deal_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.activate_deal(deal_id, headers or ADMIN))


def suspend_deal(deal_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.suspend_deal(deal_id, headers or ADMIN))


def resume_deal(deal_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.resume_deal(deal_id, headers or ADMIN))


def read_deal(deal_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_deal(deal_id, headers or ADMIN))


def deal_version(deal_id: str) -> int:
    """Read the deal's live version for expected_deal_version."""
    return read_deal(deal_id)["version"]


def close_period(
    deal_id: str,
    period_start: str = C.JUNE_START,
    period_end: str = C.JUNE_END,
    headers: dict = None,
) -> dict:
    return get_success_data(
        api_client.close_period(
            deal_id,
            {"period_start": period_start, "period_end": period_end},
            headers or ADMIN,
        )
    )


def create_item(deal_id: str, payload: dict = None, headers: dict = None, **overrides) -> dict:
    body = payload if payload is not None else F.contracted_item_payload(deal_id, **overrides)
    return get_success_data(api_client.create_contracted_item(body, headers or ADMIN))


def read_item(item_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_contracted_item(item_id, headers or ADMIN))


def item_version(item_id: str) -> int:
    """Read the item's live version for expected_contracted_item_version."""
    return read_item(item_id)["version"]


def create_card(
    item_id: str,
    rate_type: str = RateType.PER_CASE.value,
    headers: dict = None,
    **overrides,
) -> dict:
    """Propose a rate card, reading the item's own version for the OCC token."""
    version = overrides.pop("expected_version", None)
    if version is None:
        version = item_version(item_id)
    if rate_type == RateType.PER_CASE.value:
        body = F.flat_rate_card_payload(item_id, version, **overrides)
    elif rate_type == RateType.PERCENT_OF_SPEND.value:
        body = F.percent_rate_card_payload(item_id, version, **overrides)
    else:
        body = F.tiered_rate_card_payload(item_id, version, **overrides)
    return get_success_data(api_client.create_rate_card(body, headers or ADMIN))


def approve_card(rate_card_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.approve_rate_card(rate_card_id, headers or ADMIN))


def approved_card(item_id: str, rate_type: str = RateType.PER_CASE.value, **overrides) -> dict:
    """Propose then approve one card in two phased hops."""
    card = create_card(item_id, rate_type, **overrides)
    return approve_card(card["id"])


# ============================================================= tier 3/4 ======

def create_batch(distributor_id: str, headers: dict = None, **overrides) -> dict:
    """A DistributorFeed opens its own feed (X-User-ID is the distributor id)."""
    return get_success_data(
        api_client.create_purchase_batch(
            F.purchase_batch_payload(distributor_id, **overrides),
            headers or make_distributor_feed_headers(distributor_id),
        )
    )


def create_july_batch(distributor_id: str, headers: dict = None, **overrides) -> dict:
    return get_success_data(
        api_client.create_purchase_batch(
            F.july_batch_payload(distributor_id, **overrides),
            headers or make_distributor_feed_headers(distributor_id),
        )
    )


def read_batch(batch_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_purchase_batch(batch_id, headers or ANALYST))


def create_line(
    batch_id: str,
    member_id: str,
    distributor_id: str,
    payload: dict = None,
    headers: dict = None,
    **overrides,
) -> dict:
    """Ingest one invoice line. Only DistributorFeed may ingest."""
    body = payload if payload is not None else F.purchase_line_payload(
        batch_id, member_id, **overrides
    )
    return get_success_data(
        api_client.create_purchase_line(
            body, headers or make_distributor_feed_headers(distributor_id)
        )
    )


def create_line_b(batch_id: str, member_id: str, distributor_id: str, **overrides) -> dict:
    """The second beef line of the canonical June feed: 40 cases."""
    return create_line(
        batch_id,
        member_id,
        distributor_id,
        cases_shipped=C.LINE_B_CASES,
        distributor_base_cost_cents=C.LINE_B_BASE_COST_CENTS,
        invoice_date=C.LINE_B_INVOICE_DATE,
        **overrides,
    )


def read_line(line_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_purchase_line(line_id, headers or ANALYST))


def normalize(batch_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.normalize_batch(batch_id, headers or ANALYST))


def renormalize(batch_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.renormalize_batch(batch_id, headers or ANALYST))


def accrue(batch_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.accrue_batch(batch_id, headers or ANALYST))


def audit_markup(batch_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.audit_markup(batch_id, headers or ANALYST))


def request_recovery(batch_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.request_recovery(batch_id, headers or ANALYST))


def settle_recovery(
    batch_id: str,
    outcome: str = RecoveryOutcome.RECOVERED.value,
    recovered_cents: int = None,
    headers: dict = None,
) -> dict:
    """recovered_cents is required for RECOVERED and must be omitted otherwise."""
    payload = {"outcome": outcome}
    if recovered_cents is not None:
        payload["recovered_cents"] = recovered_cents
    return get_success_data(api_client.settle_recovery(batch_id, payload, headers or ADMIN))


def map_line(line_id: str, contracted_item_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.map_purchase_line(
            line_id, {"contracted_item_id": contracted_item_id}, headers or ANALYST
        )
    )


def list_accruals(headers: dict = None, **params) -> list:
    """Every accrual, newest first, read with a wide page."""
    query = dict(WIDE)
    query.update(params)
    return get_success_data(api_client.list_accruals(headers or ANALYST, query))


def accrual_for_line(line_id: str, headers: dict = None) -> dict:
    """The single accrual that monetizes one purchase line."""
    rows = [a for a in list_accruals(headers) if a["purchase_line_id"] == line_id]
    assert len(rows) == 1, f"expected exactly one accrual for line {line_id}, got {len(rows)}"
    return rows[0]


def accruals_for_member(member_id: str, headers: dict = None) -> list:
    return [a for a in list_accruals(headers) if a["member_id"] == member_id]


def read_accrual(accrual_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_accrual(accrual_id, headers or ANALYST))


def create_claim(
    deal_id: str,
    claimed_units: int,
    claimed_amount_cents: int,
    headers: dict = None,
    **overrides,
) -> dict:
    """File a claim, reading the deal's live version for the OCC token."""
    expected = overrides.pop("expected_deal_version", None)
    if expected is None:
        expected = deal_version(deal_id)
    body = F.claim_payload(deal_id, expected, claimed_units, claimed_amount_cents, **overrides)
    return get_success_data(api_client.create_claim(body, headers or REP))


def reconcile_claim(claim_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.reconcile_claim(claim_id, headers or ANALYST))


def read_claim(claim_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers or ANALYST))


def validate_accrual(accrual_id: str, claim_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.validate_accrual(accrual_id, {"claim_id": claim_id}, headers or ANALYST)
    )


def open_dispute(
    accrual_id: str,
    member_id: str,
    disputed_amount_cents: int,
    reason_code: str,
    claim_id: str = None,
    headers: dict = None,
) -> dict:
    """Only the owning MemberOperator may file (X-User-ID is the member id)."""
    return get_success_data(
        api_client.create_dispute(
            F.dispute_payload(accrual_id, disputed_amount_cents, reason_code, claim_id),
            headers or make_member_operator_headers(member_id),
        )
    )


def request_evidence(dispute_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.request_evidence(dispute_id, headers or ARBITER))


def submit_evidence(
    dispute_id: str, member_id: str, evidence_note: str = "Invoice copies attached",
    headers: dict = None,
) -> dict:
    return get_success_data(
        api_client.submit_evidence(
            dispute_id,
            {"evidence_note": evidence_note},
            headers or make_member_operator_headers(member_id),
        )
    )


def decide_dispute(
    dispute_id: str,
    decision: str = DisputeDecision.UPHOLD.value,
    decision_note: str = "Arbiter ruling recorded",
    headers: dict = None,
) -> dict:
    return get_success_data(
        api_client.decide_dispute(
            dispute_id,
            {"decision": decision, "decision_note": decision_note},
            headers or ARBITER,
        )
    )


def read_dispute(dispute_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_dispute(dispute_id, headers or ARBITER))


def create_review(
    member_id: str, deal_id: str, window_start: str, window_end: str, headers: dict = None
) -> dict:
    return get_success_data(
        api_client.create_compliance_review(
            F.compliance_review_payload(member_id, deal_id, window_start, window_end),
            headers or ADMIN,
        )
    )


def savings_report(
    member_id: str,
    period_start: str = C.JUNE_START,
    period_end: str = C.JUNE_END,
    basis: str = None,
    headers: dict = None,
) -> dict:
    return get_success_data(
        api_client.get_savings_report(
            member_id,
            headers or ADMIN,
            F.savings_report_params(period_start, period_end, basis),
        )
    )


# =============================================================== tier 5 ======
# Scenario composites. Each returns a mutable context dict whose keys are the
# records as the server last returned them, so a test can keep reading versions
# and counters off it. Each stage is a separate function: a test that needs to
# interpose a call (revoke a letter, suspend a deal) stops at the stage before.


def setup_program(
    rate_type: str = RateType.PER_CASE.value,
    tier_overrides: dict = None,
    item_overrides: dict = None,
    card_overrides: dict = None,
) -> dict:
    """An ACTIVE member with an ACTIVE letter and an ACTIVE deal whose item
    carries one APPROVED rate card."""
    tier = create_tier(**(tier_overrides or {}))
    distributor = create_distributor()
    member = create_member(tier["id"])
    letter = submit_letter(member["id"], distributor["id"])
    letter = countersign_letter(letter["id"], distributor["id"])
    member = activate_member(member["id"])
    deal = create_deal()
    item = create_item(deal["id"], **(item_overrides or {}))
    card = approved_card(item["id"], rate_type, **(card_overrides or {}))
    deal = activate_deal(deal["id"])
    return {
        "tier": tier,
        "distributor": distributor,
        "member": member,
        "letter": letter,
        "deal": deal,
        "item": item,
        "card": card,
        "member_headers": make_member_operator_headers(member["id"]),
        "distributor_headers": make_distributor_feed_headers(distributor["id"]),
        "member_id": member["id"],
        "distributor_id": distributor["id"],
        "deal_id": deal["id"],
        "item_id": item["id"],
        "tier_id": tier["id"],
    }


def setup_flat_program(**kwargs) -> dict:
    """PER_CASE program: 150 cents per case on the beef item."""
    return setup_program(RateType.PER_CASE.value, **kwargs)


def setup_tiered_program(**kwargs) -> dict:
    """TIERED_VOLUME program: the 0/50/200 case ladder on the beef item."""
    return setup_program(RateType.TIERED_VOLUME.value, **kwargs)


def ingest_june_feed(ctx: dict, second_line: bool = True) -> dict:
    """Open the June feed and ingest the 30-case line (and the 40-case line)."""
    batch = create_batch(ctx["distributor_id"])
    line_a = create_line(batch["id"], ctx["member_id"], ctx["distributor_id"])
    ctx["batch"] = batch
    ctx["batch_id"] = batch["id"]
    ctx["line_a"] = line_a
    if second_line:
        ctx["line_b"] = create_line_b(batch["id"], ctx["member_id"], ctx["distributor_id"])
    return ctx


def normalize_june_feed(ctx: dict) -> dict:
    ctx["batch"] = normalize(ctx["batch_id"])
    return ctx


def accrue_june_feed(ctx: dict) -> dict:
    ctx["batch"] = accrue(ctx["batch_id"])
    ctx["accrual_a"] = accrual_for_line(ctx["line_a"]["id"])
    if "line_b" in ctx:
        ctx["accrual_b"] = accrual_for_line(ctx["line_b"]["id"])
    ctx["member"] = read_member(ctx["member_id"])
    return ctx


def setup_june_normalized(rate_type: str = RateType.PER_CASE.value, **kwargs) -> dict:
    ctx = setup_program(rate_type, **kwargs)
    ingest_june_feed(ctx)
    return normalize_june_feed(ctx)


def setup_june_accrued(rate_type: str = RateType.PER_CASE.value, **kwargs) -> dict:
    """The canonical accrued state: two beef lines, 30 and 40 cases."""
    return accrue_june_feed(setup_june_normalized(rate_type, **kwargs))


def reconciled_claim_for_june(ctx: dict, claimed_units: int, claimed_amount_cents: int) -> dict:
    """File and reconcile one claim for the June period on the context's deal."""
    claim = create_claim(ctx["deal_id"], claimed_units, claimed_amount_cents)
    claim = reconcile_claim(claim["id"])
    ctx["claim"] = claim
    ctx["claim_id"] = claim["id"]
    ctx["deal"] = read_deal(ctx["deal_id"])
    return ctx


def validate_june_accruals(ctx: dict) -> dict:
    """Validate both June accruals against the context's reconciled claim."""
    ctx["accrual_a"] = validate_accrual(ctx["accrual_a"]["id"], ctx["claim_id"])
    if "accrual_b" in ctx:
        ctx["accrual_b"] = validate_accrual(ctx["accrual_b"]["id"], ctx["claim_id"])
    ctx["member"] = read_member(ctx["member_id"])
    return ctx


def open_dispute_on(ctx: dict, accrual: dict, reason_code: str,
                    disputed_amount_cents: int = None, claim_id: str = None) -> dict:
    """Open a dispute on one accrual for its full member share by default."""
    amount = (
        disputed_amount_cents
        if disputed_amount_cents is not None
        else accrual["member_share_cents"]
    )
    dispute = open_dispute(
        accrual["id"], ctx["member_id"], amount, reason_code, claim_id
    )
    ctx["dispute"] = dispute
    ctx["dispute_id"] = dispute["id"]
    return ctx


def audited_june_feed(ctx: dict) -> dict:
    """Run the markup audit on the accrued June feed."""
    ctx["batch"] = audit_markup(ctx["batch_id"])
    ctx["line_a"] = read_line(ctx["line_a"]["id"])
    if "line_b" in ctx:
        ctx["line_b"] = read_line(ctx["line_b"]["id"])
    return ctx
