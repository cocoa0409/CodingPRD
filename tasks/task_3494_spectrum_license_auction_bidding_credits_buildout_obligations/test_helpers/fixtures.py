"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server
(the harness restarts the API before every test) using only PRD-declared
endpoints. Setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors.

Identity threading: after creating an entity-backed Applicant or Incumbent,
every ownership-gated call uses make_bidder_headers(applicant["id"]) /
make_incumbent_operator_headers(incumbent["id"]) — never the shared
bootstrap constants.

Clock discipline: the logical clock starts at CLOCK_EPOCH_ISO (2026-09-01).
Fixtures advance it only via the clock endpoint and only forward. Callers
that need a specific instant (grant day, milestone sweep, renewal window)
call set_clock() themselves between composite steps.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH_ISO,
    iso_after_days,
)
from .factories import (
    CANONICAL_AREAS,
    CANONICAL_BLOCKS,
    UPFRONT_10M_UNITS,
    create_applicant_payload,
    create_auction_payload,
    create_band_plan_payload,
    create_bid_payload,
    create_assignment_bid_payload,
    create_incumbent_payload,
    create_incumbent_transition_payload,
    create_license_area_payload,
    create_license_block_payload,
    create_transfer_application_payload,
    create_transfer_review_payload,
)
from .test_users import TEST_USERS, make_bidder_headers, make_incumbent_operator_headers
from .types import (
    ApplicantReviewAction,
    AuctionPhaseAction,
    IncumbentTransitionAction,
    MilestoneDecision,
    RenewalDecision,
    TransferReviewAction,
)

ADMIN = TEST_USERS["auction_admin_headers"]
REVIEWER = TEST_USERS["transfer_reviewer_headers"]
BOOTSTRAP_BIDDER = TEST_USERS["bidder_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (AuctionAdmin-only, unprefixed endpoint).
    Runs the payment-deadline, milestone-MISSED, and lease sweeps."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def reset_clock() -> dict:
    """Pin the clock to the epoch instant. On a fresh server this is the
    startup default already; the call is explicit so fixtures never depend
    on wall-clock behavior."""
    return set_clock(CLOCK_EPOCH_ISO)


# ---------------------------------------------------------------------------
# Band planning
# ---------------------------------------------------------------------------

def create_draft_plan(**overrides) -> dict:
    """Create a BandPlan in DRAFT (201)."""
    return get_success_data(api_client.create_band_plan(create_band_plan_payload(**overrides), ADMIN))


def add_area(plan_id: str, area_code: str = "PEA001", **overrides) -> dict:
    """Add a LicenseArea to a DRAFT plan (201)."""
    return get_success_data(
        api_client.create_license_area(
            create_license_area_payload(plan_id, area_code=area_code, **overrides), ADMIN
        )
    )


def add_block(plan_id: str, category: str = "CATEGORY_A", **overrides) -> dict:
    """Add a LicenseBlock category to a DRAFT plan (201)."""
    return get_success_data(
        api_client.create_license_block(
            create_license_block_payload(plan_id, category=category, **overrides), ADMIN
        )
    )


def publish_plan(plan_id: str) -> dict:
    """Publish a DRAFT plan (200); requires >= 1 area and >= 1 block."""
    return get_success_data(api_client.publish_band_plan(plan_id, ADMIN))


def create_published_plan(area_codes=("PEA001",), block_categories=("CATEGORY_A",)) -> dict:
    """Draft plan + canonical areas/blocks + publish.

    Returns {"plan", "areas": {area_code: area}, "blocks": {category: block}}.
    Canonical shapes come from factories.CANONICAL_AREAS / CANONICAL_BLOCKS.
    """
    plan = create_draft_plan()
    areas = {}
    for code in area_codes:
        spec = dict(CANONICAL_AREAS[code])
        areas[code] = add_area(plan["id"], **spec)
    blocks = {}
    for cat in block_categories:
        spec = dict(CANONICAL_BLOCKS[cat])
        blocks[cat] = add_block(plan["id"], **spec)
    plan = publish_plan(plan["id"])
    return {"plan": plan, "areas": areas, "blocks": blocks}


# ---------------------------------------------------------------------------
# Auction lifecycle
# ---------------------------------------------------------------------------

def create_auction(plan_id: str, **overrides) -> dict:
    """Create an Auction (DRAFT) against a PUBLISHED plan (201)."""
    return get_success_data(api_client.create_auction(create_auction_payload(plan_id, **overrides), ADMIN))


def get_auction(auction_id: str) -> dict:
    return get_success_data(api_client.get_auction(auction_id, ADMIN))


def drive_phase(auction_id: str, action) -> dict:
    """Drive the auction phase machine; returns the updated Auction."""
    action_value = action.value if hasattr(action, "value") else action
    return get_success_data(api_client.auction_phase(auction_id, action_value, ADMIN))


def open_applications(auction_id: str) -> dict:
    return drive_phase(auction_id, AuctionPhaseAction.OPEN_APPLICATIONS)


def create_open_auction(area_codes=("PEA001",), block_categories=("CATEGORY_A",), **auction_overrides) -> dict:
    """Published plan + auction in APPLICATION_OPEN.

    Returns {"plan", "areas", "blocks", "auction"}.
    """
    ctx = create_published_plan(area_codes, block_categories)
    auction = create_auction(ctx["plan"]["id"], **auction_overrides)
    auction = open_applications(auction["id"])
    ctx["auction"] = auction
    return ctx


def begin_quiet_period(auction_id: str, deadline_iso: str = None, at_iso: str = None) -> dict:
    """Advance the clock at/past the application deadline, then
    BEGIN_QUIET_PERIOD. at_iso defaults to one day after the deadline (the
    deadline itself is inclusive; a day past is unambiguous)."""
    if at_iso is None:
        at_iso = iso_after_days(deadline_iso or get_application_deadline(auction_id), 1)
    set_clock(at_iso)
    return drive_phase(auction_id, AuctionPhaseAction.BEGIN_QUIET_PERIOD)


def get_application_deadline(auction_id: str) -> str:
    return get_auction(auction_id)["application_deadline"]


def postpone(auction_id: str) -> dict:
    """QUIET_PERIOD -> APPLICATION_OPEN (lifts the anti-collusion freeze)."""
    return drive_phase(auction_id, AuctionPhaseAction.POSTPONE)


def start_clock(auction_id: str) -> dict:
    """QUIET_PERIOD -> CLOCK_ACTIVE. Creates round 1 with opening prices,
    initializes available_supply, snapshots initial_eligibility_units."""
    return drive_phase(auction_id, AuctionPhaseAction.START_CLOCK)


def pause_clock(auction_id: str) -> dict:
    return drive_phase(auction_id, AuctionPhaseAction.PAUSE_CLOCK)


def resume_clock(auction_id: str) -> dict:
    return drive_phase(auction_id, AuctionPhaseAction.RESUME_CLOCK)


def complete_assignment(auction_id: str) -> dict:
    """ASSIGNMENT_PHASE -> CLOSED. Requires a SUBMITTED AssignmentBid from
    every winner; creates one PENDING_PAYMENT License per won unit."""
    return drive_phase(auction_id, AuctionPhaseAction.COMPLETE_ASSIGNMENT)


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------

def register_applicant(auction_id: str, **overrides) -> dict:
    """Self-register (201). Uses the bootstrap Bidder identity; the returned
    applicant id becomes that bidder's X-User-ID from here on."""
    return get_success_data(
        api_client.create_applicant(create_applicant_payload(auction_id, **overrides), BOOTSTRAP_BIDDER)
    )


def get_applicant(applicant_id: str) -> dict:
    return get_success_data(api_client.get_applicant(applicant_id, ADMIN))


def pay_upfront(applicant_id: str, amount_cents: int) -> dict:
    """Add to the deposit (200); recomputes eligibility = floor(held/2500).
    Ownership-gated: caller is the applicant itself."""
    return get_success_data(
        api_client.add_upfront_payment(applicant_id, amount_cents, make_bidder_headers(applicant_id))
    )


def review_applicant(applicant_id: str, action) -> dict:
    action_value = action.value if hasattr(action, "value") else action
    return get_success_data(api_client.review_applicant(applicant_id, action_value, ADMIN))


def start_review(applicant_id: str) -> dict:
    return review_applicant(applicant_id, ApplicantReviewAction.START_REVIEW)


def qualify_applicant(applicant_id: str) -> dict:
    """START_REVIEW + QUALIFY. Computes attributable revenue and credit_pct.
    Requires eligibility_units >= 1 (pay upfront first)."""
    start_review(applicant_id)
    return review_applicant(applicant_id, ApplicantReviewAction.QUALIFY)


def create_qualified_applicant(auction_id: str, upfront_cents: int = UPFRONT_10M_UNITS, **overrides) -> dict:
    """Register + upfront payment + START_REVIEW + QUALIFY. Returns the
    QUALIFIED applicant."""
    applicant = register_applicant(auction_id, **overrides)
    applicant = pay_upfront(applicant["id"], upfront_cents)
    return qualify_applicant(applicant["id"])


def patch_disclosure(applicant_id: str, expected_applicant_version: int, **fields) -> dict:
    """OCC-guarded disclosure update (200); increments version by 1.
    Legal only while the applicant is SUBMITTED or NEEDS_CORRECTION and the
    auction is still APPLICATION_OPEN."""
    payload = {"expected_applicant_version": expected_applicant_version}
    payload.update(fields)
    return get_success_data(
        api_client.patch_disclosure(applicant_id, payload, make_bidder_headers(applicant_id))
    )


def resubmit_applicant(applicant_id: str, expected_applicant_version: int) -> dict:
    """NEEDS_CORRECTION -> UNDER_REVIEW (OCC-guarded); increments version."""
    return get_success_data(
        api_client.resubmit_applicant(
            applicant_id, expected_applicant_version, make_bidder_headers(applicant_id)
        )
    )


def withdraw_applicant(applicant_id: str) -> dict:
    """Withdraw while APPLICATION_OPEN; held deposit is refunded in full."""
    return get_success_data(
        api_client.withdraw_applicant(applicant_id, make_bidder_headers(applicant_id))
    )


# ---------------------------------------------------------------------------
# Clock rounds and bids
# ---------------------------------------------------------------------------

def list_rounds(auction_id: str) -> list:
    data, _meta = _paginated(api_client.list_rounds(auction_id, ADMIN, params={"limit": 100}))
    return data


def current_round(auction_id: str) -> dict:
    """The most recently created round (rounds list is created_at ASC)."""
    rounds = list_rounds(auction_id)
    assert rounds, f"no clock rounds exist for auction {auction_id}"
    return rounds[-1]


def get_round(round_id: str) -> dict:
    return get_success_data(api_client.get_round(round_id, ADMIN))


def open_next_round(auction_id: str) -> dict:
    """Open the next round (201); requires CLOCK_ACTIVE and previous round
    CLOSED. Prices come from the tiered increment rule; closed products are
    excluded."""
    return get_success_data(api_client.open_round(auction_id, ADMIN))


def close_round(round_id: str) -> dict:
    """Close an OPEN round (200): bids -> PROCESSED, demand finalized,
    activity rule applied; may advance the auction to ASSIGNMENT_PHASE."""
    return get_success_data(api_client.close_round(round_id, ADMIN))


def place_bid(round_id: str, applicant_id: str, area_code: str, category: str, quantity: int) -> dict:
    """Place a clock bid (201). The bidder identity IS the applicant id."""
    return get_success_data(
        api_client.place_bid(
            round_id,
            create_bid_payload(area_code, category, quantity),
            make_bidder_headers(applicant_id),
        )
    )


def run_round(auction_id: str, bids: list) -> dict:
    """Place `bids` in the current OPEN round, then close it.

    bids: list of (applicant_id, area_code, category, quantity) tuples.
    Returns the closed round."""
    round_ = current_round(auction_id)
    for applicant_id, area_code, category, quantity in bids:
        place_bid(round_["id"], applicant_id, area_code, category, quantity)
    return close_round(round_["id"])


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


# ---------------------------------------------------------------------------
# Assignment phase
# ---------------------------------------------------------------------------

def file_assignment_bid(
    auction_id: str, applicant_id: str, area_code: str, category: str, amount_cents: int
) -> dict:
    """Sealed assignment bid (201); one per (bidder, product); the caller
    must be a recorded winner of the product."""
    return get_success_data(
        api_client.create_assignment_bid(
            auction_id,
            create_assignment_bid_payload(area_code, category, amount_cents),
            make_bidder_headers(applicant_id),
        )
    )


# ---------------------------------------------------------------------------
# Licenses and settlement
# ---------------------------------------------------------------------------

def list_licenses(**filters) -> list:
    data, _meta = _paginated(api_client.list_licenses(ADMIN, params={k: v for k, v in filters.items() if v is not None}))
    return data


def get_license(license_id: str) -> dict:
    return get_success_data(api_client.get_license(license_id, ADMIN))


def settle_license(license_id: str, holder_applicant_id: str, amount_cents: int) -> dict:
    """One settlement payment (200). The completing payment requires every
    incumbent in the license's area to be RELOCATING or CLEARED."""
    return get_success_data(
        api_client.add_settlement_payment(
            license_id, amount_cents, make_bidder_headers(holder_applicant_id)
        )
    )


def settle_license_in_full(license: dict) -> dict:
    """Pay exactly the remaining balance (net_price_cents - paid_cents).
    On completion: license -> ACTIVE, grant_date stamped with the CURRENT
    logical instant, term_end = grant + 3650 days, two PENDING milestones
    created (INTERIM before FINAL in listings)."""
    remaining = license["net_price_cents"] - license["paid_cents"]
    return settle_license(license["id"], license["holder_applicant_id"], remaining)


# ---------------------------------------------------------------------------
# Buildout milestones
# ---------------------------------------------------------------------------

def list_milestones(license_id: str) -> list:
    """Milestones of a license, created_at ASC (INTERIM before FINAL)."""
    data, _meta = _paginated(api_client.list_buildout_milestones(license_id, ADMIN, params={"limit": 100}))
    return data


def milestones_by_type(license_id: str) -> dict:
    """{"INTERIM": milestone, "FINAL": milestone} for a granted license."""
    result = {}
    for ms in list_milestones(license_id):
        result[ms["milestone_type"]] = ms
    return result


def file_milestone_notice(
    milestone_id: str, holder_applicant_id: str, covered_population: int, expected_milestone_version: int
) -> dict:
    """OCC-guarded coverage filing (200); PENDING/REJECTED -> FILED and
    increments the milestone version. License must be ACTIVE/RENEWAL_REVIEW."""
    return get_success_data(
        api_client.file_milestone_notice(
            milestone_id,
            {
                "covered_population": covered_population,
                "expected_milestone_version": expected_milestone_version,
            },
            make_bidder_headers(holder_applicant_id),
        )
    )


def review_milestone(milestone_id: str, decision) -> dict:
    """ACCEPT requires covered*100 >= required_pct * area population; REJECT
    moves FILED -> REJECTED (re-filing allowed)."""
    decision_value = decision.value if hasattr(decision, "value") else decision
    return get_success_data(api_client.review_milestone(milestone_id, decision_value, ADMIN))


def file_and_accept_milestone(milestone: dict, holder_applicant_id: str, covered_population: int) -> dict:
    """File with the milestone's CURRENT version, then ACCEPT. Use for
    deep-future clock jumps (renewal windows): accepted milestones cannot go
    MISSED in a sweep."""
    filed = file_milestone_notice(
        milestone["id"], holder_applicant_id, covered_population, milestone["version"]
    )
    return review_milestone(filed["id"], MilestoneDecision.ACCEPT)


# ---------------------------------------------------------------------------
# Incumbents
# ---------------------------------------------------------------------------

def register_incumbent(band_plan_id: str, area_id: str, **overrides) -> dict:
    """Register an Incumbent (201, AuctionAdmin). Starts NOTIFIED with null
    windows and empty share arrays."""
    return get_success_data(
        api_client.create_incumbent(create_incumbent_payload(band_plan_id, area_id, **overrides), ADMIN)
    )


def get_incumbent(incumbent_id: str) -> dict:
    return get_success_data(api_client.get_incumbent(incumbent_id, ADMIN))


def incumbent_submit_plan(incumbent_id: str) -> dict:
    """NOTIFIED -> PLAN_SUBMITTED (owner action)."""
    return get_success_data(
        api_client.transition_incumbent(
            incumbent_id,
            create_incumbent_transition_payload(IncumbentTransitionAction.SUBMIT_PLAN.value),
            make_incumbent_operator_headers(incumbent_id),
        )
    )


def incumbent_dispute(incumbent_id: str) -> dict:
    """PLAN_SUBMITTED -> DISPUTED (owner action)."""
    return get_success_data(
        api_client.transition_incumbent(
            incumbent_id,
            create_incumbent_transition_payload(IncumbentTransitionAction.DISPUTE.value),
            make_incumbent_operator_headers(incumbent_id),
        )
    )


def incumbent_resubmit_plan(incumbent_id: str) -> dict:
    """DISPUTED -> PLAN_SUBMITTED (owner action)."""
    return get_success_data(
        api_client.transition_incumbent(
            incumbent_id,
            create_incumbent_transition_payload(IncumbentTransitionAction.RESUBMIT_PLAN.value),
            make_incumbent_operator_headers(incumbent_id),
        )
    )


def incumbent_begin_relocation(
    incumbent_id: str, transition_window_start: str, transition_window_end: str
) -> dict:
    """PLAN_SUBMITTED -> RELOCATING (AuctionAdmin). End must be strictly
    after start; the window must keep a 30-day buffer against every other
    RELOCATING window in the same area (closed-interval comparison)."""
    return get_success_data(
        api_client.transition_incumbent(
            incumbent_id,
            create_incumbent_transition_payload(
                IncumbentTransitionAction.BEGIN_RELOCATION.value,
                transition_window_start=transition_window_start,
                transition_window_end=transition_window_end,
            ),
            ADMIN,
        )
    )


def incumbent_confirm_cleared(incumbent_id: str) -> dict:
    """RELOCATING -> CLEARED (owner action) once the clock has reached the
    window end. Computes shares_proportional/shares_equal over the area's
    ACTIVE licenses and posts the proportional shares onto the licenses."""
    return get_success_data(
        api_client.transition_incumbent(
            incumbent_id,
            create_incumbent_transition_payload(IncumbentTransitionAction.CONFIRM_CLEARED.value),
            make_incumbent_operator_headers(incumbent_id),
        )
    )


def walk_incumbent_to_relocating(incumbent_id: str, window_start: str, window_end: str) -> dict:
    """SUBMIT_PLAN then BEGIN_RELOCATION. Returns the RELOCATING incumbent."""
    incumbent_submit_plan(incumbent_id)
    return incumbent_begin_relocation(incumbent_id, window_start, window_end)


# ---------------------------------------------------------------------------
# Transfers and leases
# ---------------------------------------------------------------------------

def file_transfer(
    license: dict,
    transferee_applicant_id: str,
    transfer_type: str = "FULL_ASSIGNMENT",
    lease_start: str = None,
    lease_end: str = None,
) -> dict:
    """File a transfer application (201); caller is the license holder. The
    license must be ACTIVE. Computes unjust_enrichment_cents at filing from
    the logical clock. LEASE requires lease_start/lease_end (end > start)
    and a non-overlapping window under half-open [start, end) semantics."""
    return get_success_data(
        api_client.create_transfer_application(
            license["id"],
            create_transfer_application_payload(
                transferee_applicant_id,
                transfer_type,
                lease_start=lease_start,
                lease_end=lease_end,
            ),
            make_bidder_headers(license["holder_applicant_id"]),
        )
    )


def get_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_transfer_application(transfer_id, ADMIN))


def transfer_action(transfer_id: str, action, headers, confirm_unjust_enrichment_repayment=None) -> dict:
    """Drive the transfer review driver. BEGIN_REVIEW/REQUEST_INFO/APPROVE/
    DENY are TransferReviewer-only; PROVIDE_INFO is the transferor only."""
    action_value = action.value if hasattr(action, "value") else action
    payload = create_transfer_review_payload(action_value)
    if confirm_unjust_enrichment_repayment is not None:
        payload["confirm_unjust_enrichment_repayment"] = confirm_unjust_enrichment_repayment
    return get_success_data(api_client.review_transfer_application(transfer_id, payload, headers))


def transfer_begin_review(transfer_id: str) -> dict:
    return transfer_action(transfer_id, TransferReviewAction.BEGIN_REVIEW, REVIEWER)


def transfer_request_info(transfer_id: str) -> dict:
    return transfer_action(transfer_id, TransferReviewAction.REQUEST_INFO, REVIEWER)


def transfer_provide_info(transfer_id: str, transferor_applicant_id: str) -> dict:
    return transfer_action(
        transfer_id, TransferReviewAction.PROVIDE_INFO, make_bidder_headers(transferor_applicant_id)
    )


def transfer_approve(transfer_id: str, confirm_unjust_enrichment_repayment=None) -> dict:
    """APPROVE from UNDER_REVIEW. When unjust_enrichment_cents > 0 the
    request must carry confirm_unjust_enrichment_repayment=True."""
    return transfer_action(
        transfer_id,
        TransferReviewAction.APPROVE,
        REVIEWER,
        confirm_unjust_enrichment_repayment=confirm_unjust_enrichment_repayment,
    )


def transfer_deny(transfer_id: str) -> dict:
    return transfer_action(transfer_id, TransferReviewAction.DENY, REVIEWER)


def transfer_withdraw(transfer_id: str, transferor_applicant_id: str) -> dict:
    """Withdraw a FILED or INFO_REQUESTED application (transferor only)."""
    return get_success_data(
        api_client.withdraw_transfer_application(
            transfer_id, make_bidder_headers(transferor_applicant_id)
        )
    )


# ---------------------------------------------------------------------------
# Renewals
# ---------------------------------------------------------------------------

def file_renewal(license: dict) -> dict:
    """File for renewal (201) inside [term_end - 365 days, term_end]; the
    license moves ACTIVE -> RENEWAL_REVIEW and the application lands in
    UNDER_REVIEW within the same request. Caller is the license holder."""
    return get_success_data(
        api_client.create_renewal_application(
            license["id"], make_bidder_headers(license["holder_applicant_id"])
        )
    )


def decide_renewal(renewal_id: str, decision) -> dict:
    """GRANT: license back to ACTIVE, term_end += 3650 days. DENY: license
    -> TERMINATED with cascades (pending transfers denied, supply +1)."""
    decision_value = decision.value if hasattr(decision, "value") else decision
    return get_success_data(api_client.decide_renewal(renewal_id, decision_value, REVIEWER))


# ---------------------------------------------------------------------------
# Composite scenario chains
# ---------------------------------------------------------------------------

def setup_clock_active_auction(
    area_codes=("PEA001",),
    block_categories=("CATEGORY_A",),
    bidder_specs=None,
    application_deadline: str = None,
    quiet_advance_to: str = None,
) -> dict:
    """Full chain: published plan -> auction -> APPLICATION_OPEN -> qualified
    bidders -> clock past deadline -> QUIET_PERIOD -> START_CLOCK.

    bidder_specs: list of dicts, each with optional "upfront_cents" (default
    UPFRONT_10M_UNITS = 10,000,000 eligibility units) plus any applicant
    payload overrides (claims_small_business, service_population, ...).
    Defaults to one no-credit bidder.

    Returns {"plan", "areas", "blocks", "auction", "applicants", "round"} —
    auction read AFTER START_CLOCK, round is round 1 (OPEN).
    """
    if bidder_specs is None:
        bidder_specs = [{}]
    ctx = create_published_plan(area_codes, block_categories)
    auction_overrides = {}
    if application_deadline is not None:
        auction_overrides["application_deadline"] = application_deadline
    auction = create_auction(ctx["plan"]["id"], **auction_overrides)
    open_applications(auction["id"])
    applicants = []
    for spec in bidder_specs:
        spec = dict(spec)
        upfront_cents = spec.pop("upfront_cents", UPFRONT_10M_UNITS)
        applicants.append(create_qualified_applicant(auction["id"], upfront_cents, **spec))
    begin_quiet_period(auction["id"], auction["application_deadline"], at_iso=quiet_advance_to)
    auction = start_clock(auction["id"])
    ctx.update(
        {
            "auction": auction,
            "applicants": applicants,
            "round": current_round(auction["id"]),
        }
    )
    return ctx


def setup_assignment_phase(
    bids: list,
    area_codes=("PEA001",),
    block_categories=("CATEGORY_A",),
    bidder_specs=None,
    **kwargs,
) -> dict:
    """Clock-active auction + one round of bids + close, landing in
    ASSIGNMENT_PHASE. `bids` is a list of (applicant_index, area_code,
    category, quantity) referring to ctx["applicants"]; every open product's
    demand must be <= supply or the auction stays CLOCK_ACTIVE.

    Returns ctx additionally carrying "final_round" (the CLOSED round) and
    "auction" refreshed (status ASSIGNMENT_PHASE).
    """
    ctx = setup_clock_active_auction(area_codes, block_categories, bidder_specs, **kwargs)
    round_ = ctx["round"]
    for applicant_index, area_code, category, quantity in bids:
        place_bid(round_["id"], ctx["applicants"][applicant_index]["id"], area_code, category, quantity)
    final_round = close_round(round_["id"])
    ctx["final_round"] = final_round
    ctx["auction"] = get_auction(ctx["auction"]["id"])
    return ctx


def setup_closed_auction_with_licenses(
    bids: list,
    assignment_amounts: dict = None,
    area_codes=("PEA001",),
    block_categories=("CATEGORY_A",),
    bidder_specs=None,
    **kwargs,
) -> dict:
    """Assignment phase + one assignment bid per winning (bidder, product)
    tuple + COMPLETE_ASSIGNMENT -> CLOSED auction with PENDING_PAYMENT
    licenses.

    assignment_amounts: {(applicant_index, area_code, category): amount_cents};
    defaults to 0 for every winner tuple.

    Returns ctx additionally carrying "licenses" (all licenses of the
    auction, created_at ASC) and "auction" refreshed (status CLOSED).
    """
    ctx = setup_assignment_phase(bids, area_codes, block_categories, bidder_specs, **kwargs)
    auction_id = ctx["auction"]["id"]
    amounts = assignment_amounts or {}
    seen = set()
    for applicant_index, area_code, category, _quantity in bids:
        key = (applicant_index, area_code, category)
        if key in seen:
            continue
        seen.add(key)
        file_assignment_bid(
            auction_id,
            ctx["applicants"][applicant_index]["id"],
            area_code,
            category,
            amounts.get(key, 0),
        )
    ctx["auction"] = complete_assignment(auction_id)
    ctx["licenses"] = list_licenses(auction_id=auction_id)
    return ctx


def setup_active_license(
    bids=None,
    grant_day_iso: str = None,
    area_codes=("PEA002",),
    block_categories=("CATEGORY_A",),
    bidder_specs=None,
    license_index: int = 0,
    **kwargs,
) -> dict:
    """Closed auction + one license settled in full -> ACTIVE.

    bids defaults to [(0, first_area, first_block, 1)] — one winner, one unit,
    demand == supply so round 1 closes into ASSIGNMENT_PHASE... note demand
    EQUALS supply here, so no other product may exist with demand 0 while
    supply > 0 (that product would stay open and block the transition).
    For multi-product plans pass explicit bids covering every product at
    exactly supply.

    grant_day_iso: when set, the clock is advanced there BEFORE the
    settlement payment, so grant_date renders as that instant.

    Returns ctx additionally carrying "license" (the ACTIVE license) and
    "milestones" ({"INTERIM": ..., "FINAL": ...}).
    """
    if bids is None:
        bids = [(0, area_codes[0], block_categories[0], 1)]
    ctx = setup_closed_auction_with_licenses(
        bids, area_codes=area_codes, block_categories=block_categories, bidder_specs=bidder_specs, **kwargs
    )
    license_ = ctx["licenses"][license_index]
    if grant_day_iso is not None:
        set_clock(grant_day_iso)
    license_ = settle_license_in_full(license_)
    ctx["license"] = license_
    ctx["milestones"] = milestones_by_type(license_["id"])
    return ctx
