"""Composite setup helpers.

Every helper builds its state from scratch through PRD endpoints only, because each test
runs against an empty database.  Setup calls use the lenient validator so a broken
precondition reports as a setup failure rather than as a confusing assertion error.

Identity threading: the Partner role is resolved from X-User-ID, so every partner-owned
call below passes make_partner_headers(partner["id"]).
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_mapping_payload,
    create_account_payload,
    create_certification_payload,
    create_deal_registration_payload,
    create_mdf_allocation_payload,
    create_mdf_claim_payload,
    create_order_invoice_payload,
    create_partner_payload,
    create_performance_review_payload,
    create_proof_payload,
    create_special_pricing_request_payload,
    decide_registration_payload,
    decide_review_payload,
    decide_special_pricing_payload,
    resolve_conflict_payload,
    respond_account_mapping_payload,
    review_registration_payload,
    update_partner_payload,
    validate_claim_payload,
)
from .test_users import (
    ANALYST,
    DIRECTOR,
    DIRECT_REP,
    make_partner_headers,
)

# --------------------------------------------------------------------------- clock


def set_clock(current_utc: str) -> None:
    """Pin the logical clock.  Every window, deadline and cooldown reads only this clock."""
    resp = api_client.set_current_utc(current_utc, ANALYST)
    assert 200 <= resp.status_code < 300, (
        f"Setup step failed: could not set the logical clock to {current_utc}: {resp.text}"
    )


# --------------------------------------------------------------------------- primitives


def create_partner(
    company_name: str = "Northwind Distribution",
    partner_type: str = "DISTRIBUTOR",
    marketing_commitment_cents: int = 0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    resp = api_client.create_partner(
        create_partner_payload(
            company_name=company_name,
            partner_type=partner_type,
            marketing_commitment_cents=marketing_commitment_cents,
        ),
        headers or ANALYST,
    )
    return get_success_data(resp)


def add_certification(
    partner_id: str,
    engineer_name: str = "Ada Lin",
    track: str = "TECH_EXPERT",
    issued_at: str = "2025-06-01T00:00:00.000Z",
    expires_at: str = "2028-06-01T00:00:00.000Z",
) -> Dict[str, Any]:
    resp = api_client.create_certification(
        partner_id,
        create_certification_payload(
            engineer_name=engineer_name,
            track=track,
            issued_at=issued_at,
            expires_at=expires_at,
        ),
        ANALYST,
    )
    return get_success_data(resp)


def create_account(
    account_name: str = "Granite Health", region_code: str = "NA"
) -> Dict[str, Any]:
    resp = api_client.create_account(
        create_account_payload(account_name=account_name, region_code=region_code), ANALYST
    )
    return get_success_data(resp)


def read_partner(partner_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_partner(partner_id, ANALYST))


def read_account(account_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_account(account_id, ANALYST))


def read_registration(registration_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_deal_registration(registration_id, ANALYST))


def read_allocation(allocation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_mdf_allocation(allocation_id, ANALYST))


def read_claim(claim_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_mdf_claim(claim_id, ANALYST))


def read_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_order_invoice(invoice_id, ANALYST))


def read_review(review_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_performance_review(review_id, ANALYST))


def read_conflict_case(case_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_conflict_case(case_id, ANALYST))


def read_proof(proof_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_proof(proof_id, ANALYST))


# --------------------------------------------------------------------------- orders


def create_order(
    partner_id: str,
    order_type: str = "STOCKING",
    list_amount_cents: int = 10_000_000,
    registration_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_order_invoice_payload(
        partner_id, order_type=order_type, list_amount_cents=list_amount_cents
    )
    if registration_id is not None:
        payload["registration_id"] = registration_id
    return get_success_data(api_client.create_order_invoice(payload, ANALYST))


def create_and_invoice_order(
    partner_id: str,
    order_type: str = "STOCKING",
    list_amount_cents: int = 10_000_000,
    registration_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Price an order and move it to INVOICED, which is what turns it into program revenue."""
    order = create_order(
        partner_id,
        order_type=order_type,
        list_amount_cents=list_amount_cents,
        registration_id=registration_id,
    )
    return get_success_data(api_client.invoice_order(order["id"], ANALYST))


# --------------------------------------------------------------------------- reviews


def prepare_review(
    partner_id: str,
    period_start: str = "2026-01-01T00:00:00.000Z",
    period_end: str = "2026-01-31T23:59:59.999Z",
    findings_count: int = 0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    resp = api_client.create_performance_review(
        create_performance_review_payload(
            partner_id,
            period_start=period_start,
            period_end=period_end,
            findings_count=findings_count,
        ),
        headers or ANALYST,
    )
    return get_success_data(resp)


def decide_review(review_id: str, decision: str = "APPROVE", headers=None) -> Dict[str, Any]:
    resp = api_client.decide_performance_review(
        review_id, decide_review_payload(decision), headers or DIRECTOR
    )
    return get_success_data(resp)


def prepare_and_approve_review(
    partner_id: str,
    period_start: str = "2026-01-01T00:00:00.000Z",
    period_end: str = "2026-01-31T23:59:59.999Z",
) -> Dict[str, Any]:
    """Prepare a review and have the director approve it - the only writer of Partner.tier."""
    review = prepare_review(
        partner_id, period_start=period_start, period_end=period_end, findings_count=0
    )
    return decide_review(review["id"], "APPROVE")


# --------------------------------------------------------------------------- registrations


def draft_registration(
    partner_id: str,
    account_id: str,
    product_line: str = "ANALYTICS_ADDON",
    expected_amount_cents: int = 600_000,
    expected_close_date: str = "2026-08-31T00:00:00.000Z",
    supersedes_registration_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_deal_registration_payload(
        partner_id,
        account_id,
        product_line=product_line,
        expected_amount_cents=expected_amount_cents,
        expected_close_date=expected_close_date,
    )
    if supersedes_registration_id is not None:
        payload["supersedes_registration_id"] = supersedes_registration_id
    resp = api_client.create_deal_registration(payload, make_partner_headers(partner_id))
    return get_success_data(resp)


def submit_registration(registration_id: str, partner_id: str) -> Dict[str, Any]:
    resp = api_client.submit_deal_registration(registration_id, make_partner_headers(partner_id))
    return get_success_data(resp)


def start_review(registration_id: str) -> Dict[str, Any]:
    resp = api_client.review_deal_registration(
        registration_id, review_registration_payload("START_REVIEW"), ANALYST
    )
    return get_success_data(resp)


def request_changes(registration_id: str, reviewer_note: str = "clarify the deal size") -> Dict[str, Any]:
    resp = api_client.review_deal_registration(
        registration_id,
        review_registration_payload("REQUEST_CHANGES", reviewer_note=reviewer_note),
        ANALYST,
    )
    return get_success_data(resp)


def decide_registration(registration_id: str, decision: str = "APPROVE", **extra) -> Dict[str, Any]:
    resp = api_client.decide_deal_registration(
        registration_id, decide_registration_payload(decision, **extra), DIRECTOR
    )
    return get_success_data(resp)


def submit_review_and_approve(registration_id: str, partner_id: str) -> Dict[str, Any]:
    """Walk a DRAFT registration through submit, START_REVIEW and APPROVE."""
    submit_registration(registration_id, partner_id)
    start_review(registration_id)
    return decide_registration(registration_id, "APPROVE")


def create_approved_registration(
    partner_id: str,
    account_id: str,
    product_line: str = "ANALYTICS_ADDON",
    expected_amount_cents: int = 600_000,
    expected_close_date: str = "2026-08-31T00:00:00.000Z",
) -> Dict[str, Any]:
    registration = draft_registration(
        partner_id,
        account_id,
        product_line=product_line,
        expected_amount_cents=expected_amount_cents,
        expected_close_date=expected_close_date,
    )
    return submit_review_and_approve(registration["id"], partner_id)


# --------------------------------------------------------------------------- mappings


def propose_mapping(
    partner_id: str,
    account_id: str,
    expected_account_version: int,
    effective_from: str = "2026-03-01T00:00:00.000Z",
    effective_until: str = "2026-06-30T23:59:59.999Z",
    product_line: str = "ANALYTICS_ADDON",
    exclusivity_scope: str = "PRODUCT_LINE",
) -> Dict[str, Any]:
    resp = api_client.create_account_mapping(
        create_account_mapping_payload(
            partner_id,
            account_id,
            expected_account_version,
            product_line=product_line,
            exclusivity_scope=exclusivity_scope,
            effective_from=effective_from,
            effective_until=effective_until,
        ),
        ANALYST,
    )
    return get_success_data(resp)


def respond_mapping(
    mapping_id: str, action: str, headers: Dict[str, str], **extra
) -> Dict[str, Any]:
    resp = api_client.respond_account_mapping(
        mapping_id, respond_account_mapping_payload(action, **extra), headers
    )
    return get_success_data(resp)


def create_active_mapping(
    partner_id: str,
    account_id: str,
    effective_from: str = "2026-03-01T00:00:00.000Z",
    effective_until: str = "2026-06-30T23:59:59.999Z",
    product_line: str = "ANALYTICS_ADDON",
) -> Dict[str, Any]:
    """Propose a mapping and have the partner accept it, so it reaches ACTIVE."""
    account = read_account(account_id)
    mapping = propose_mapping(
        partner_id,
        account_id,
        account["version"],
        effective_from=effective_from,
        effective_until=effective_until,
        product_line=product_line,
    )
    return respond_mapping(mapping["id"], "ACCEPT", make_partner_headers(partner_id))


# --------------------------------------------------------------------------- special pricing


def create_spr(
    registration_id: str,
    partner_id: str,
    requested_extra_margin_pct: float = 0.02,
    expected_registration_version: Optional[int] = None,
    justification: str = "competitive displacement pricing",
) -> Dict[str, Any]:
    if expected_registration_version is None:
        expected_registration_version = read_registration(registration_id)["version"]
    resp = api_client.create_special_pricing_request(
        create_special_pricing_request_payload(
            registration_id,
            expected_registration_version,
            requested_extra_margin_pct=requested_extra_margin_pct,
            justification=justification,
        ),
        make_partner_headers(partner_id),
    )
    return get_success_data(resp)


def decide_spr(spr_id: str, decision: str, approved_extra_margin_pct=None) -> Dict[str, Any]:
    payload = decide_special_pricing_payload(decision)
    if approved_extra_margin_pct is not None:
        payload["approved_extra_margin_pct"] = approved_extra_margin_pct
    return get_success_data(api_client.decide_special_pricing_request(spr_id, payload, DIRECTOR))


# --------------------------------------------------------------------------- funds


def open_allocation(
    partner_id: str,
    period_start: str = "2026-02-01T00:00:00.000Z",
    period_end: str = "2026-06-30T23:59:59.999Z",
) -> Dict[str, Any]:
    resp = api_client.create_mdf_allocation(
        create_mdf_allocation_payload(
            partner_id, period_start=period_start, period_end=period_end
        ),
        ANALYST,
    )
    return get_success_data(resp)


def create_claim(
    allocation_id: str,
    partner_id: str,
    activity_type: str = "EVENT",
    requested_cents: int = 20_000,
) -> Dict[str, Any]:
    resp = api_client.create_mdf_claim(
        create_mdf_claim_payload(
            allocation_id, activity_type=activity_type, requested_cents=requested_cents
        ),
        make_partner_headers(partner_id),
    )
    return get_success_data(resp)


def attach_proof(
    claim_id: str,
    partner_id: str,
    spend_amount_cents: int = 12_000,
    doc_type: str = "ATTENDEE_LIST",
    audience_reach: Optional[int] = 140,
) -> Dict[str, Any]:
    payload = create_proof_payload(
        doc_type=doc_type, spend_amount_cents=spend_amount_cents
    )
    if audience_reach is None:
        payload.pop("audience_reach", None)
    else:
        payload["audience_reach"] = audience_reach
    resp = api_client.create_proof(claim_id, payload, make_partner_headers(partner_id))
    return get_success_data(resp)


def verify_proof(claim_id: str, proof_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.verify_proof(claim_id, proof_id, ANALYST))


def attach_and_verify_proof(
    claim_id: str,
    partner_id: str,
    spend_amount_cents: int = 12_000,
    doc_type: str = "ATTENDEE_LIST",
    audience_reach: Optional[int] = 140,
) -> Dict[str, Any]:
    proof = attach_proof(
        claim_id,
        partner_id,
        spend_amount_cents=spend_amount_cents,
        doc_type=doc_type,
        audience_reach=audience_reach,
    )
    return verify_proof(claim_id, proof["id"])


def validate_claim(claim_id: str, decision: str = "VALIDATE", headers=None, **extra) -> Dict[str, Any]:
    resp = api_client.validate_mdf_claim(
        claim_id, validate_claim_payload(decision, **extra), headers or ANALYST
    )
    return get_success_data(resp)


def settle_claim(claim_id: str, action: str, headers=None) -> Dict[str, Any]:
    from .factories import settle_claim_payload

    resp = api_client.settle_mdf_claim(claim_id, settle_claim_payload(action), headers or DIRECTOR)
    return get_success_data(resp)


def close_allocation(allocation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.close_mdf_allocation(allocation_id, ANALYST))


# --------------------------------------------------------------------------- composite seeds


def seed_registered_distributor(
    clock: str = "2026-01-05T00:00:00.000Z",
    company_name: str = "Northwind Distribution",
    marketing_commitment_cents: int = 0,
    expert_count: int = 3,
) -> Dict[str, Any]:
    """A freshly enrolled DISTRIBUTOR holding ``expert_count`` active TECH_EXPERT certifications."""
    set_clock(clock)
    partner = create_partner(
        company_name=company_name,
        partner_type="DISTRIBUTOR",
        marketing_commitment_cents=marketing_commitment_cents,
    )
    engineers = ["Ada Lin", "Bo Reyes", "Cy Duarte", "Dee Vance", "Eli Marsh"]
    for index in range(expert_count):
        add_certification(partner["id"], engineer_name=engineers[index % len(engineers)])
    return read_partner(partner["id"])


def seed_gold_distributor(
    clock: str = "2026-01-05T00:00:00.000Z",
    company_name: str = "Northwind Distribution",
    marketing_commitment_cents: int = 0,
    seed_list_amount_cents: int = 10_000_000,
) -> Dict[str, Any]:
    """A DISTRIBUTOR promoted to GOLD by an approved January review.

    Twelve certification credits from three TECH_EXPERT engineers plus one invoiced STOCKING
    order of ``seed_list_amount_cents`` produce a January review whose approval writes
    Partner.tier = GOLD.  Returns {"partner", "seed_invoice", "review"}.
    """
    partner = seed_registered_distributor(
        clock=clock,
        company_name=company_name,
        marketing_commitment_cents=marketing_commitment_cents,
    )
    seed_invoice = create_and_invoice_order(
        partner["id"], order_type="STOCKING", list_amount_cents=seed_list_amount_cents
    )
    review = prepare_review(partner["id"], findings_count=0)
    decided = decide_review(review["id"], "APPROVE")
    return {
        "partner": read_partner(partner["id"]),
        "seed_invoice": seed_invoice,
        "review": decided,
    }


def seed_gold_distributor_with_allocation(
    allocation_clock: str = "2026-02-10T00:00:00.000Z",
    period_start: str = "2026-02-01T00:00:00.000Z",
    period_end: str = "2026-06-30T23:59:59.999Z",
    marketing_commitment_cents: int = 0,
    seed_list_amount_cents: int = 10_000_000,
) -> Dict[str, Any]:
    """The GOLD distributor plus one open market development fund period.

    Returns {"partner", "seed_invoice", "review", "allocation"}.
    """
    seed = seed_gold_distributor(
        marketing_commitment_cents=marketing_commitment_cents,
        seed_list_amount_cents=seed_list_amount_cents,
    )
    set_clock(allocation_clock)
    allocation = open_allocation(
        seed["partner"]["id"], period_start=period_start, period_end=period_end
    )
    seed["allocation"] = allocation
    seed["partner"] = read_partner(seed["partner"]["id"])
    return seed


def seed_gold_claim_with_verified_proof(
    requested_cents: int = 20_000,
    spend_amount_cents: int = 12_000,
    activity_type: str = "EVENT",
    doc_type: str = "ATTENDEE_LIST",
) -> Dict[str, Any]:
    """The GOLD distributor's fund period with one claim carrying a single verified proof.

    Returns {"partner", "allocation", "claim", "proof"}.
    """
    seed = seed_gold_distributor_with_allocation()
    partner_id = seed["partner"]["id"]
    claim = create_claim(
        seed["allocation"]["id"],
        partner_id,
        activity_type=activity_type,
        requested_cents=requested_cents,
    )
    proof = attach_proof(
        claim["id"], partner_id, spend_amount_cents=spend_amount_cents, doc_type=doc_type
    )
    verified = verify_proof(claim["id"], proof["id"])
    return {
        "partner": read_partner(partner_id),
        "allocation": read_allocation(seed["allocation"]["id"]),
        "claim": read_claim(claim["id"]),
        "proof": verified,
    }


def seed_two_resellers_with_accounts(
    clock: str = "2026-04-01T00:00:00.000Z",
    account_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Two RESELLER partners, each holding one TECH_ASSOCIATE certification, plus N accounts.

    Two certification credits clear the registration eligibility floor for ANALYTICS_ADDON
    without clearing the PLATFORM_SUITE gate.  Returns
    {"incumbent", "challenger", "accounts"} where accounts is a list of Account rows.
    """
    if account_names is None:
        account_names = ["Granite Health"]
    set_clock(clock)
    incumbent = create_partner(
        company_name="Solstice Partners", partner_type="RESELLER", marketing_commitment_cents=0
    )
    add_certification(
        incumbent["id"], engineer_name="Gia Nolan", track="TECH_ASSOCIATE"
    )
    challenger = create_partner(
        company_name="Meridian Partners", partner_type="RESELLER", marketing_commitment_cents=0
    )
    add_certification(
        challenger["id"], engineer_name="Hal Ortiz", track="TECH_ASSOCIATE"
    )
    accounts = [create_account(account_name=name) for name in account_names]
    return {
        "incumbent": read_partner(incumbent["id"]),
        "challenger": read_partner(challenger["id"]),
        "accounts": accounts,
    }


def seed_protected_account(
    clock: str = "2026-04-01T00:00:00.000Z",
    product_line: str = "ANALYTICS_ADDON",
) -> Dict[str, Any]:
    """Two RESELLERs and one account the incumbent already protects with an APPROVED registration.

    Returns {"incumbent", "challenger", "account", "incumbent_registration"}.
    """
    seed = seed_two_resellers_with_accounts(clock=clock)
    account = seed["accounts"][0]
    incumbent_registration = create_approved_registration(
        seed["incumbent"]["id"], account["id"], product_line=product_line
    )
    return {
        "incumbent": read_partner(seed["incumbent"]["id"]),
        "challenger": read_partner(seed["challenger"]["id"]),
        "account": read_account(account["id"]),
        "incumbent_registration": incumbent_registration,
    }


def seed_partner_vs_direct_conflict(
    clock: str = "2026-04-01T00:00:00.000Z",
    product_line: str = "ANALYTICS_ADDON",
    pursuit_clock: Optional[str] = None,
    pursuit_note: str = "field sales owns this renewal",
) -> Dict[str, Any]:
    """A direct sales representative declares pursuit of a channel-protected account.

    ``pursuit_clock`` advances the logical clock before the declaration, which separates the
    subject's ``submitted_at`` from the account's ``direct_pursuit_declared_at`` so the
    registration-order doctrine never needs its tiebreaker.

    Returns {"incumbent", "challenger", "account", "incumbent_registration", "case"}.
    """
    seed = seed_protected_account(clock=clock, product_line=product_line)
    from .factories import direct_pursuit_payload

    if pursuit_clock is not None:
        set_clock(pursuit_clock)

    get_success_data(
        api_client.declare_direct_pursuit(
            seed["account"]["id"],
            direct_pursuit_payload(pursuit_note=pursuit_note),
            DIRECT_REP,
        )
    )
    cases, _ = _list_rows(
        api_client.list_conflict_cases(
            ANALYST,
            params={"account_id": seed["account"]["id"], "conflict_type": "PARTNER_VS_DIRECT"},
        )
    )
    assert cases, "Setup step failed: no PARTNER_VS_DIRECT conflict case was raised"
    seed["case"] = cases[0]
    seed["account"] = read_account(seed["account"]["id"])
    return seed


def seed_direct_locked_account(
    clock: str = "2026-04-01T00:00:00.000Z",
    product_line: str = "ANALYTICS_ADDON",
) -> Dict[str, Any]:
    """The partner-versus-direct case resolved in favour of direct sales, locking the account.

    Returns {"incumbent", "challenger", "account", "incumbent_registration", "case"}.
    """
    seed = seed_partner_vs_direct_conflict(clock=clock, product_line=product_line)
    get_success_data(
        api_client.resolve_conflict_case(
            seed["case"]["id"],
            resolve_conflict_payload("DIRECT", resolution_note="account awarded to direct sales"),
            DIRECTOR,
        )
    )
    seed["account"] = read_account(seed["account"]["id"])
    seed["case"] = read_conflict_case(seed["case"]["id"])
    seed["incumbent_registration"] = read_registration(seed["incumbent_registration"]["id"])
    return seed


def seed_partner_vs_partner_conflict(
    clock: str = "2026-04-01T00:00:00.000Z",
    product_line: str = "ANALYTICS_ADDON",
) -> Dict[str, Any]:
    """Two rivals submit on the same account and product line; approving one holds the other.

    Both registrations are submitted before either is approved, so the approval's cascade is
    what raises the partner-versus-partner case.  Returns
    {"incumbent", "challenger", "account", "subject_registration", "counter_registration", "case"}.
    """
    seed = seed_two_resellers_with_accounts(clock=clock)
    account = seed["accounts"][0]
    subject = draft_registration(
        seed["incumbent"]["id"], account["id"], product_line=product_line
    )
    counter = draft_registration(
        seed["challenger"]["id"],
        account["id"],
        product_line=product_line,
        expected_amount_cents=400_000,
        expected_close_date="2026-09-30T00:00:00.000Z",
    )
    submit_registration(subject["id"], seed["incumbent"]["id"])
    submit_registration(counter["id"], seed["challenger"]["id"])
    start_review(subject["id"])
    approved = decide_registration(subject["id"], "APPROVE")
    cases, _ = _list_rows(
        api_client.list_conflict_cases(ANALYST, params={"account_id": account["id"]})
    )
    return {
        "incumbent": read_partner(seed["incumbent"]["id"]),
        "challenger": read_partner(seed["challenger"]["id"]),
        "account": read_account(account["id"]),
        "subject_registration": approved,
        "counter_registration": read_registration(counter["id"]),
        "case": cases[0] if cases else None,
    }


def _list_rows(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read a list endpoint's rows during setup without asserting paging shape."""
    body = get_success_data(response)
    if isinstance(body, list):
        return body, {}
    return body, {}


def seed_dual_variant_scoring_partner(
    clock: str = "2026-01-05T00:00:00.000Z",
    short_cert_expires_at: str = "2026-03-01T00:00:00.000Z",
    invoiced_list_amount_cents: int = 10_000_000,
    pending_list_amount_cents: int = 4_000_000,
) -> Dict[str, Any]:
    """A partner whose rows score differently under the two scoring variants.

    Three TECH_EXPERT certifications, one of which lapses before the coverage horizon, plus
    one INVOICED and one PENDING order.  Returns
    {"partner", "cert_short", "invoiced_order", "pending_order"}.
    """
    set_clock(clock)
    partner = create_partner(
        company_name="Northwind Distribution",
        partner_type="DISTRIBUTOR",
        marketing_commitment_cents=0,
    )
    add_certification(partner["id"], engineer_name="Ada Lin")
    add_certification(partner["id"], engineer_name="Bo Reyes")
    cert_short = add_certification(
        partner["id"], engineer_name="Cy Duarte", expires_at=short_cert_expires_at
    )
    invoiced_order = create_and_invoice_order(
        partner["id"], order_type="STOCKING", list_amount_cents=invoiced_list_amount_cents
    )
    pending_order = create_order(
        partner["id"], order_type="STOCKING", list_amount_cents=pending_list_amount_cents
    )
    return {
        "partner": read_partner(partner["id"]),
        "cert_short": cert_short,
        "invoiced_order": invoiced_order,
        "pending_order": pending_order,
    }


def seed_sequential_rival_submissions(
    first_clock: str = "2026-02-01T00:00:00.000Z",
    second_clock: str = "2026-02-02T00:00:00.000Z",
    product_line: str = "ANALYTICS_ADDON",
) -> Dict[str, Any]:
    """Two rivals submit on the same account one day apart; the later one is under review.

    Partner A submits first, partner B submits a day later and channel operations starts the
    review of B's claim, so approving B raises the case on A's claim.  Returns
    {"partner_a", "partner_b", "account", "registration_a", "registration_b"}.
    """
    set_clock(first_clock)
    partner_a = create_partner(
        company_name="Aurora Resellers", partner_type="RESELLER", marketing_commitment_cents=0
    )
    add_certification(partner_a["id"], engineer_name="Dee Park", track="TECH_ASSOCIATE")
    partner_b = create_partner(
        company_name="Borealis Resellers", partner_type="RESELLER", marketing_commitment_cents=0
    )
    add_certification(partner_b["id"], engineer_name="Eli Frost", track="TECH_ASSOCIATE")
    account = create_account(account_name="Helios Manufacturing")
    registration_a = draft_registration(
        partner_a["id"],
        account["id"],
        product_line=product_line,
        expected_amount_cents=500_000,
        expected_close_date="2026-06-30T00:00:00.000Z",
    )
    submit_registration(registration_a["id"], partner_a["id"])
    set_clock(second_clock)
    registration_b = draft_registration(
        partner_b["id"],
        account["id"],
        product_line=product_line,
        expected_amount_cents=700_000,
        expected_close_date="2026-07-31T00:00:00.000Z",
    )
    submit_registration(registration_b["id"], partner_b["id"])
    start_review(registration_b["id"])
    return {
        "partner_a": read_partner(partner_a["id"]),
        "partner_b": read_partner(partner_b["id"]),
        "account": read_account(account["id"]),
        "registration_a": read_registration(registration_a["id"]),
        "registration_b": read_registration(registration_b["id"]),
    }


def find_conflict_cases(**params) -> List[Dict[str, Any]]:
    """Read the conflict case list, the only discovery channel for cascade-created cases."""
    rows, _ = _list_rows(api_client.list_conflict_cases(ANALYST, params=params or None))
    return rows


def seed_gold_pinned_margin_context(
    clock: str = "2026-01-05T00:00:00.000Z",
    expected_amount_cents: int = 28_000_000,
    requested_extra_margin_pct: float = 0.02,
) -> Dict[str, Any]:
    """A GOLD DISTRIBUTOR with a live APPROVED PLATFORM_SUITE registration and granted extra margin.

    Twelve certification credits clear the PLATFORM_SUITE gate; approval at the 2026-01-05 clock
    opens the half-open window [2026-01-05, 2026-04-05) so the registration uplift is the
    in-window 0.06, and the granted request adds a further 0.02.  Returns
    {"partner", "account", "registration", "spr", "seed_invoice"}.
    """
    seed = seed_gold_distributor(clock=clock)
    partner_id = seed["partner"]["id"]
    account = create_account(account_name="Vertex Aerospace", region_code="NA")
    registration = draft_registration(
        partner_id,
        account["id"],
        product_line="PLATFORM_SUITE",
        expected_amount_cents=expected_amount_cents,
        expected_close_date="2026-03-31T00:00:00.000Z",
    )
    approved = submit_review_and_approve(registration["id"], partner_id)
    request = create_spr(
        registration["id"],
        partner_id,
        requested_extra_margin_pct=requested_extra_margin_pct,
        expected_registration_version=approved["version"],
        justification="competitive displacement bid",
    )
    granted = decide_spr(request["id"], "APPROVE")
    return {
        "partner": read_partner(partner_id),
        "account": read_account(account["id"]),
        "registration": read_registration(registration["id"]),
        "spr": granted,
        "seed_invoice": seed["seed_invoice"],
    }


THREE_PROOF_LINES = [
    ("INVOICE", 12_345, 0),
    ("ATTENDEE_LIST", 6_789, 140),
    ("LEAD_REPORT", 1_111, 12),
]


def seed_gold_claim_with_three_verified_proofs(
    requested_cents: int = 20_000,
    activity_type: str = "EVENT",
) -> Dict[str, Any]:
    """A GOLD fund period carrying one claim whose three documents are all verified.

    All three documents are attached while the claim is SUBMITTED, which is the self-loop that
    consumes no proof round.  Returns {"partner", "allocation", "claim", "proofs"} where proofs
    is the list of verified documents in attachment order.
    """
    seed = seed_gold_distributor_with_allocation()
    partner_id = seed["partner"]["id"]
    claim = create_claim(
        seed["allocation"]["id"],
        partner_id,
        activity_type=activity_type,
        requested_cents=requested_cents,
    )
    attached = [
        attach_proof(
            claim["id"],
            partner_id,
            spend_amount_cents=spend,
            doc_type=doc_type,
            audience_reach=reach,
        )
        for doc_type, spend, reach in THREE_PROOF_LINES
    ]
    verified = [verify_proof(claim["id"], proof["id"]) for proof in attached]
    return {
        "partner": read_partner(partner_id),
        "allocation": read_allocation(seed["allocation"]["id"]),
        "claim": read_claim(claim["id"]),
        "proofs": verified,
    }


def seed_reseller_draft_registration(
    clock: str = "2026-03-01T00:00:00.000Z",
    company_name: str = "Cobalt Systems",
    engineer_name: str = "Fay Ito",
    account_name: str = "Riverbend Logistics",
    region_code: str = "EMEA",
    product_line: str = "ANALYTICS_ADDON",
    expected_amount_cents: int = 800_000,
    expected_close_date: str = "2026-09-30T00:00:00.000Z",
) -> Dict[str, Any]:
    """One RESELLER at the two-credit registration floor, one OPEN_CHANNEL account, one DRAFT.

    Returns {"partner", "account", "registration"}.
    """
    set_clock(clock)
    partner = create_partner(
        company_name=company_name, partner_type="RESELLER", marketing_commitment_cents=0
    )
    add_certification(partner["id"], engineer_name=engineer_name, track="TECH_ASSOCIATE")
    account = create_account(account_name=account_name, region_code=region_code)
    registration = draft_registration(
        partner["id"],
        account["id"],
        product_line=product_line,
        expected_amount_cents=expected_amount_cents,
        expected_close_date=expected_close_date,
    )
    return {
        "partner": read_partner(partner["id"]),
        "account": account,
        "registration": registration,
    }


def run_revision_loop(
    registration_id: str,
    partner_id: str,
    submit_at: Optional[str] = None,
    reviewer_note: str = "add competitive landscape detail",
) -> Dict[str, Any]:
    """One full trip round the revision cycle: submit, START_REVIEW, REQUEST_CHANGES."""
    if submit_at is not None:
        set_clock(submit_at)
    submit_registration(registration_id, partner_id)
    start_review(registration_id)
    return request_changes(registration_id, reviewer_note=reviewer_note)


def seed_validated_gold_claim(
    requested_cents: int = 20_000,
    spend_amount_cents: int = 20_000,
    activity_type: str = "DIGITAL_CAMPAIGN",
    doc_type: str = "SCREENSHOT",
    audience_reach: int = 9_000,
) -> Dict[str, Any]:
    """A GOLD fund period whose single claim is already VALIDATED by the analyst.

    Returns {"partner", "allocation", "claim", "proof"}.
    """
    seed = seed_gold_distributor_with_allocation()
    partner_id = seed["partner"]["id"]
    claim = create_claim(
        seed["allocation"]["id"],
        partner_id,
        activity_type=activity_type,
        requested_cents=requested_cents,
    )
    proof = attach_proof(
        claim["id"],
        partner_id,
        spend_amount_cents=spend_amount_cents,
        doc_type=doc_type,
        audience_reach=audience_reach,
    )
    verify_proof(claim["id"], proof["id"])
    validate_claim(claim["id"], "VALIDATE")
    return {
        "partner": read_partner(partner_id),
        "allocation": read_allocation(seed["allocation"]["id"]),
        "claim": read_claim(claim["id"]),
        "proof": read_proof(proof["id"]),
    }


def seed_cascade_a_two_account_conflict(
    clock: str = "2026-04-01T00:00:00.000Z",
    product_line: str = "ANALYTICS_ADDON",
) -> Dict[str, Any]:
    """Two rivals on two accounts, poised one decision short of the rival's second conflict.

    The rival holds a SUBMITTED registration on each account.  On the first account the other
    partner is already APPROVED, so the rival already carries exactly one OPEN case; on the second
    account the other partner sits in UNDER_REVIEW awaiting the decision under test.  Returns
    {"approver", "rival", "account_one", "account_two", "approver_registration_one",
    "approver_registration_two", "rival_registration_one", "rival_registration_two"}.
    """
    seed = seed_two_resellers_with_accounts(
        clock=clock, account_names=["Granite Health", "Lakeside Utilities"]
    )
    approver_id = seed["incumbent"]["id"]
    rival_id = seed["challenger"]["id"]
    account_one, account_two = seed["accounts"]

    rival_one = draft_registration(
        rival_id, account_one["id"], product_line=product_line, expected_amount_cents=400_000
    )
    submit_registration(rival_one["id"], rival_id)
    rival_two = draft_registration(
        rival_id, account_two["id"], product_line=product_line, expected_amount_cents=450_000
    )
    submit_registration(rival_two["id"], rival_id)

    approver_one = draft_registration(
        approver_id, account_one["id"], product_line=product_line, expected_amount_cents=600_000
    )
    submit_registration(approver_one["id"], approver_id)
    start_review(approver_one["id"])
    decide_registration(approver_one["id"], "APPROVE")

    approver_two = draft_registration(
        approver_id, account_two["id"], product_line=product_line, expected_amount_cents=650_000
    )
    submit_registration(approver_two["id"], approver_id)
    start_review(approver_two["id"])

    return {
        "approver": read_partner(approver_id),
        "rival": read_partner(rival_id),
        "account_one": read_account(account_one["id"]),
        "account_two": read_account(account_two["id"]),
        "approver_registration_one": read_registration(approver_one["id"]),
        "approver_registration_two": read_registration(approver_two["id"]),
        "rival_registration_one": read_registration(rival_one["id"]),
        "rival_registration_two": read_registration(rival_two["id"]),
    }


def seed_cascade_b_validated_claim(
    marketing_commitment_cents: int = 1_000_000,
    requested_cents: int = 20_000,
    spend_amount_cents: int = 2_000_000,
) -> Dict[str, Any]:
    """A GOLD distributor at full marketing attainment, carried there by one VALIDATED claim.

    The marketing commitment is raised only after the review has been decided, so the review
    scored against a vacuous attainment while the live figure depends entirely on the verified
    spend the claim carries.  Returns {"partner", "allocation", "claim", "proof"}.
    """
    seed = seed_gold_distributor()
    partner_id = seed["partner"]["id"]
    get_success_data(
        api_client.update_partner(
            partner_id,
            update_partner_payload(marketing_commitment_cents=marketing_commitment_cents),
            ANALYST,
        )
    )
    set_clock("2026-02-10T00:00:00.000Z")
    allocation = open_allocation(partner_id)
    claim = create_claim(
        allocation["id"], partner_id, activity_type="EVENT", requested_cents=requested_cents
    )
    proof = attach_proof(
        claim["id"],
        partner_id,
        spend_amount_cents=spend_amount_cents,
        doc_type="INVOICE",
        audience_reach=500,
    )
    verify_proof(claim["id"], proof["id"])
    validate_claim(claim["id"], "VALIDATE")
    return {
        "partner": read_partner(partner_id),
        "allocation": read_allocation(allocation["id"]),
        "claim": read_claim(claim["id"]),
        "proof": read_proof(proof["id"]),
    }


def seed_gold_with_overdue_audit(
    findings_count: int = 3,
    findings_clock: str = "2026-02-10T00:00:00.000Z",
    overdue_clock: str = "2026-03-13T00:00:00.000Z",
) -> Dict[str, Any]:
    """A GOLD distributor with an open fund period and an un-remediated audit past its deadline.

    The findings review is prepared at ``findings_clock`` so its remediation deadline lands 30 days
    later, and the clock is then pushed past it without any remediation.  Returns
    {"partner", "allocation", "findings_review"}.
    """
    seed = seed_gold_distributor_with_allocation(allocation_clock=findings_clock)
    partner_id = seed["partner"]["id"]
    findings_review = prepare_review(
        partner_id,
        period_start="2026-02-01T00:00:00.000Z",
        period_end="2026-02-28T23:59:59.999Z",
        findings_count=findings_count,
    )
    set_clock(overdue_clock)
    return {
        "partner": read_partner(partner_id),
        "allocation": read_allocation(seed["allocation"]["id"]),
        "findings_review": read_review(findings_review["id"]),
    }


def seed_gold_claim_with_unverified_proofs(
    requested_cents: int = 20_000,
    activity_type: str = "EVENT",
) -> Dict[str, Any]:
    """A GOLD fund period whose claim carries two attached documents, neither of them verified.

    The smaller document evidences a single cent, which is the smallest spend the matching rule can
    still round up to a non-zero figure.  Returns {"partner", "allocation", "claim",
    "tiny_proof", "unverified_proof"}.
    """
    seed = seed_gold_distributor_with_allocation()
    partner_id = seed["partner"]["id"]
    claim = create_claim(
        seed["allocation"]["id"],
        partner_id,
        activity_type=activity_type,
        requested_cents=requested_cents,
    )
    tiny = attach_proof(
        claim["id"], partner_id, spend_amount_cents=1, doc_type="INVOICE", audience_reach=0
    )
    other = attach_proof(
        claim["id"], partner_id, spend_amount_cents=4_000, doc_type="LEAD_REPORT", audience_reach=25
    )
    return {
        "partner": read_partner(partner_id),
        "allocation": read_allocation(seed["allocation"]["id"]),
        "claim": read_claim(claim["id"]),
        "tiny_proof": tiny,
        "unverified_proof": other,
    }


def seed_gold_distributor_with_two_orders(
    second_list_amount_cents: int = 20_000_000,
    allocation_clock: str = "2026-02-10T00:00:00.000Z",
    period_start: str = "2026-02-01T00:00:00.000Z",
    period_end: str = "2026-06-30T23:59:59.999Z",
) -> Dict[str, Any]:
    """A GOLD distributor whose revenue was booked in two tranches, plus one open fund period.

    The first order was priced while the partner was still REGISTERED and the second after the
    promotion, so the two invoices carry different margins and the period's basis is their sum.
    Returns {"partner", "seed_invoice", "gold_invoice", "allocation"}.
    """
    seed = seed_gold_distributor()
    partner_id = seed["partner"]["id"]
    gold_invoice = create_and_invoice_order(
        partner_id, order_type="STOCKING", list_amount_cents=second_list_amount_cents
    )
    set_clock(allocation_clock)
    allocation = open_allocation(partner_id, period_start=period_start, period_end=period_end)
    return {
        "partner": read_partner(partner_id),
        "seed_invoice": read_invoice(seed["seed_invoice"]["id"]),
        "gold_invoice": gold_invoice,
        "allocation": allocation,
    }
