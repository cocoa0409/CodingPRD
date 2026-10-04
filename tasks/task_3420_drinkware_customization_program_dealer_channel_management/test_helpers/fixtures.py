"""Composite setup helpers (PRD workflow preambles).

Every helper builds its preconditions from scratch against a fresh server
(the harness restarts the server before each test, so the logical clock
starts at 2026-09-01T00:00:00Z and the database is empty). Setup calls use
the lenient get_success_data() validator: a failed setup step surfaces as a
clear setup error, not a confusing assertion failure.

Identity threading (PRD section 2.1):
- Dealer-role calls pass make_dealer_headers(dealer["id"]) — the shared
  TEST_USERS["dealer_headers"] fallback is never used for ownership-gated
  calls.
- Buyer-role calls pass make_buyer_headers(buyer_ref) matching the order's
  buyer_ref.
- FieldInspector calls pass make_field_inspector_headers(inspector_id)
  matching the inspector_user_id being scheduled.
- Application decide uses a decider identity distinct from the inspection
  recorder and the docs reviewer (segregation of duties, PRD section 3.1).

Clock discipline: composite fixtures set the logical clock exactly where the
workflow requires it (boot, inspection window end, allocation window open,
allocation close). Default dates in factories are all reachable forward from
the clock start.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_BOOT_ISO
from .factories import (
    create_artwork_proof_payload,
    create_colorway_drop_payload,
    create_customization_order_payload,
    create_dealer_application_payload,
    create_dealer_payload,
    create_enforcement_case_payload,
    create_launch_allocation_payload,
    create_print_slot_payload,
    create_product_line_payload,
    create_warranty_claim_payload,
    decide_application_payload,
    decide_claim_payload,
    decide_return_payload,
    record_inspection_payload,
    request_return_payload,
    schedule_inspection_payload,
    verify_documents_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_channel_manager_headers,
    make_customer_care_headers,
    make_dealer_headers,
    make_field_inspector_headers,
    make_prepress_tech_headers,
    make_warranty_agent_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_CM = TEST_USERS["channel_manager_headers"]
_PREPRESS = TEST_USERS["prepress_tech_headers"]
_PRODUCTION = TEST_USERS["production_lead_headers"]
_WARRANTY = TEST_USERS["warranty_agent_headers"]
_CARE = TEST_USERS["customer_care_headers"]


# ===========================================================================
# Logical clock (PRD section 2.4)
# ===========================================================================
def set_clock(to_iso8601: str) -> dict:
    """Set the logical clock as PlatformAdmin. Lazy status transitions are
    re-evaluated from the new clock on subsequent reads and writes."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN)
    return get_success_data(resp)


def boot_clock() -> dict:
    """Move the clock off its 2026-09-01T00:00:00Z default to the conventional
    post-boot instant used before any domain writes."""
    return set_clock(CLOCK_BOOT_ISO)


# ===========================================================================
# Read-back helpers (refresh an entity after cascading writes)
# ===========================================================================
def get_dealer(dealer_id: str) -> dict:
    return get_success_data(api_client.get_dealer(dealer_id, _ADMIN))


def get_application(application_id: str) -> dict:
    # Application reads are not open to PlatformAdmin; use ChannelManager.
    return get_success_data(api_client.get_dealer_application(application_id, _CM))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_enforcement_case(case_id, _ADMIN))


def get_product_line(product_line_id: str) -> dict:
    return get_success_data(api_client.get_product_line(product_line_id, _ADMIN))


def get_drop(drop_id: str) -> dict:
    return get_success_data(api_client.get_colorway_drop(drop_id, _ADMIN))


def get_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_launch_allocation(allocation_id, _ADMIN))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_customization_order(order_id, _ADMIN))


def get_proof(proof_id: str) -> dict:
    return get_success_data(api_client.get_artwork_proof(proof_id, _ADMIN))


def get_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_print_slot(slot_id, _ADMIN))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, _ADMIN))


# ===========================================================================
# Tier 1/2 — Dealer registration and the authorization fork-join (PRD 3.1)
# ===========================================================================
def create_dealer(**overrides) -> dict:
    """Register a dealer as PlatformAdmin. Starts PENDING with
    storefront_verified false and brand_presentation_score 0."""
    resp = api_client.create_dealer(create_dealer_payload(**overrides), _ADMIN)
    return get_success_data(resp)


def create_open_application(dealer: dict = None, application_creator_id: str = "cm-admin",
                            dealer_overrides: dict = None,
                            **application_overrides) -> dict:
    """A PENDING dealer plus its SUBMITTED application.

    Returns {"dealer": ..., "application": ...}.
    """
    if dealer is None:
        dealer = create_dealer(**(dealer_overrides or {}))
    payload = create_dealer_application_payload(dealer["id"], **application_overrides)
    resp = api_client.create_dealer_application(
        payload, make_channel_manager_headers(application_creator_id))
    application = get_success_data(resp)
    return {"dealer": dealer, "application": application}


def schedule_inspection(application_id: str, inspector_id: str = "fi-1",
                        window_start: str = "2026-09-02T09:00:00Z",
                        window_end: str = "2026-09-02T11:00:00Z") -> dict:
    """Schedule the site-visit window. inspector_user_id equals the acting
    inspector's X-User-ID. Moves the application SUBMITTED -> VETTING."""
    payload = schedule_inspection_payload(
        inspector_user_id=inspector_id,
        window_start=window_start,
        window_end=window_end,
    )
    resp = api_client.schedule_inspection(
        application_id, payload, make_field_inspector_headers(inspector_id))
    return get_success_data(resp)


def record_inspection(application_id: str, inspector_id: str = "fi-1",
                      outcome: str = "PASSED",
                      brand_presentation_score: int = 85) -> dict:
    """Record the inspection outcome. Requires the logical clock to have
    reached the scheduled window's end (callers set the clock first)."""
    resp = api_client.record_inspection(
        application_id,
        record_inspection_payload(outcome, brand_presentation_score),
        make_field_inspector_headers(inspector_id))
    return get_success_data(resp)


def verify_documents(application_id: str, reviewer_id: str = "cm-docs",
                     outcome: str = "VERIFIED") -> dict:
    """Verify (or reject) the documents leg as a ChannelManager."""
    resp = api_client.verify_documents(
        application_id, verify_documents_payload(outcome),
        make_channel_manager_headers(reviewer_id))
    return get_success_data(resp)


def decide_application(application_id: str, decider_id: str = "cm-1",
                       decision: str = "APPROVE",
                       decision_reason: str = "ok") -> dict:
    """Decide an application as a ChannelManager. For APPROVE the decider must
    differ from both the inspection recorder and the docs reviewer."""
    resp = api_client.decide_application(
        application_id, decide_application_payload(decision, decision_reason),
        make_channel_manager_headers(decider_id))
    return get_success_data(resp)


def create_authorized_dealer(inspector_id: str = "fi-1",
                             docs_reviewer_id: str = "cm-docs",
                             decider_id: str = "cm-1",
                             application_creator_id: str = "cm-admin",
                             brand_score: int = 85,
                             window_start: str = "2026-09-02T09:00:00Z",
                             window_end: str = "2026-09-02T11:00:00Z",
                             dealer_overrides: dict = None,
                             application_overrides: dict = None) -> dict:
    """Drive a dealer through the full authorization fork-join:
    register -> apply -> schedule inspection -> clock to window end ->
    record PASSED inspection -> verify documents -> decide APPROVE.

    Returns {"dealer": <refreshed, AUTHORIZED>, "application": <APPROVED>}.

    When authorizing several dealers in one test, give each a distinct
    inspector_id, or disjoint windows honoring the 60-minute travel buffer
    between one inspector's consecutive visits (PRD section 3.1).
    """
    boot_clock()
    pair = create_open_application(
        dealer=None,
        application_creator_id=application_creator_id,
        dealer_overrides=dealer_overrides,
        **(application_overrides or {}),
    )
    dealer, application = pair["dealer"], pair["application"]
    schedule_inspection(application["id"], inspector_id, window_start, window_end)
    set_clock(window_end)
    record_inspection(application["id"], inspector_id, "PASSED", brand_score)
    verify_documents(application["id"], docs_reviewer_id, "VERIFIED")
    decided = decide_application(application["id"], decider_id, "APPROVE")
    return {"dealer": get_dealer(dealer["id"]), "application": decided}


def suspend_dealer(dealer_id: str, reason: str = "policy violation",
                   manager_id: str = "cm-1") -> dict:
    resp = api_client.suspend_dealer(
        dealer_id, {"reason": reason}, make_channel_manager_headers(manager_id))
    return get_success_data(resp)


def reinstate_dealer(dealer_id: str, manager_id: str = "cm-1") -> dict:
    resp = api_client.reinstate_dealer(
        dealer_id, make_channel_manager_headers(manager_id))
    return get_success_data(resp)


def terminate_dealer(dealer_id: str, reason: str = "fraudulent paperwork",
                     manager_id: str = "cm-1") -> dict:
    resp = api_client.terminate_dealer(
        dealer_id, {"reason": reason}, make_channel_manager_headers(manager_id))
    return get_success_data(resp)


# ===========================================================================
# Tier 4 — Enforcement and dealer standing accumulation (PRD 3.2)
# ===========================================================================
def create_enforcement_case(matched_dealer_id: str = None,
                            creator_id: str = "cm-enf", **overrides) -> dict:
    """Open an enforcement case (UNDER_REVIEW). Pass matched_dealer_id to
    trace the listing to an authorized dealer."""
    if matched_dealer_id is not None:
        overrides.setdefault("matched_dealer_id", matched_dealer_id)
    resp = api_client.create_enforcement_case(
        create_enforcement_case_payload(**overrides),
        make_channel_manager_headers(creator_id))
    return get_success_data(resp)


def resolve_case_confirmed(case_id: str, dealer_id: str,
                           infraction_category: str,
                           decider_id: str = "cm-1",
                           resolution_notes: str = None) -> dict:
    """Resolve a matched case as CONFIRMED_VIOLATION, reading the dealer's
    current version first for the optimistic-concurrency field."""
    dealer = get_dealer(dealer_id)
    payload = {
        "outcome": "CONFIRMED_VIOLATION",
        "infraction_category": infraction_category,
        "expected_dealer_version": dealer["version"],
    }
    if resolution_notes is not None:
        payload["resolution_notes"] = resolution_notes
    resp = api_client.resolve_enforcement_case(
        case_id, payload, make_channel_manager_headers(decider_id))
    return get_success_data(resp)


def add_infraction_points(dealer_id: str, categories,
                          case_creator_id: str = "cm-enf",
                          decider_id: str = "cm-1") -> list:
    """Confirm one enforcement case per category (in order) against the
    dealer; each confirmation recomputes standing and bumps the dealer's
    version. Returns the confirmed case dicts."""
    cases = []
    for i, category in enumerate(categories, start=1):
        case = create_enforcement_case(
            matched_dealer_id=dealer_id,
            creator_id=case_creator_id,
            seller_handle=f"reseller-{dealer_id[:8]}-{i}",
            listing_url=f"https://marketplace.example.com/listing/{dealer_id[:8]}-{i}",
        )
        cases.append(resolve_case_confirmed(
            case["id"], dealer_id, category, decider_id=decider_id))
    return cases


def create_probation_dealer(categories=("MAP_VIOLATION", "MAP_VIOLATION"),
                            **kwargs) -> dict:
    """An AUTHORIZED dealer driven to PROBATION (default: 4 + 4 = 8 points,
    exactly the probation threshold).

    Returns {"dealer", "application", "cases"}.
    """
    pair = create_authorized_dealer(**kwargs)
    cases = add_infraction_points(pair["dealer"]["id"], list(categories))
    return {"dealer": get_dealer(pair["dealer"]["id"]),
            "application": pair["application"], "cases": cases}


def create_suspended_dealer(categories=("UNAUTHORIZED_MARKETPLACE",
                                        "UNAUTHORIZED_MARKETPLACE"),
                            **kwargs) -> dict:
    """An AUTHORIZED dealer driven to SUSPENDED by infraction points
    (default: 6 + 6 = 12, exactly the suspension threshold).

    Returns {"dealer", "application", "cases"}.
    """
    pair = create_authorized_dealer(**kwargs)
    cases = add_infraction_points(pair["dealer"]["id"], list(categories))
    return {"dealer": get_dealer(pair["dealer"]["id"]),
            "application": pair["application"], "cases": cases}


# ===========================================================================
# Tier 1/2 — Catalog: product lines and colorway drops (PRD 3.3)
# ===========================================================================
def create_product_line(**overrides) -> dict:
    resp = api_client.create_product_line(create_product_line_payload(**overrides),
                                          _ADMIN)
    return get_success_data(resp)


def create_colorway_drop(product_line_id: str, **overrides) -> dict:
    resp = api_client.create_colorway_drop(
        create_colorway_drop_payload(product_line_id, **overrides), _ADMIN)
    return get_success_data(resp)


def setup_catalog(line_overrides: dict = None, drop_overrides: dict = None) -> dict:
    """One ACTIVE product line plus one ANNOUNCED drop on it.

    Returns {"line": ..., "drop": ...}.
    """
    line = create_product_line(**(line_overrides or {}))
    drop = create_colorway_drop(line["id"], **(drop_overrides or {}))
    return {"line": line, "drop": drop}


def setup_open_drop(open_clock: str = "2026-09-06T00:00:00Z",
                    line_overrides: dict = None,
                    drop_overrides: dict = None) -> dict:
    """Catalog + clock advanced inside the allocation window + open-allocation.

    Returns {"line": ..., "drop": <ALLOCATION_OPEN, refreshed>}.
    """
    pair = setup_catalog(line_overrides, drop_overrides)
    set_clock(open_clock)
    api_client.open_allocation(pair["drop"]["id"], _ADMIN)
    pair["drop"] = get_drop(pair["drop"]["id"])
    return pair


def create_allocation_request(dealer_id: str, drop_id: str,
                              requested_units: int = 5,
                              **overrides) -> dict:
    """A dealer requests units from an ALLOCATION_OPEN drop; dealer_id equals
    the acting Dealer identity."""
    resp = api_client.create_launch_allocation(
        create_launch_allocation_payload(dealer_id, drop_id, requested_units,
                                         **overrides),
        make_dealer_headers(dealer_id))
    return get_success_data(resp)


def setup_locked_drop(allocation_requests: list = None,
                      open_clock: str = "2026-09-06T00:00:00Z",
                      lock_clock: str = "2026-09-21T00:00:00Z",
                      line_overrides: dict = None,
                      drop_overrides: dict = None) -> dict:
    """Open drop, place allocation requests, advance past the close, and lock
    with the drop's current version (the distribution runs here).

    allocation_requests: list of {"dealer_id": ..., "requested_units": ...}.
    lock_clock must be at or after the drop's allocation_closes_at (the
    default pairs with the factory default closes of 2026-09-20).

    Returns {"line", "drop" (ALLOCATION_LOCKED, refreshed), "allocations"}.
    """
    pair = setup_open_drop(open_clock, line_overrides, drop_overrides)
    drop_id = pair["drop"]["id"]
    allocations = []
    for req in (allocation_requests or []):
        allocations.append(create_allocation_request(
            req["dealer_id"], drop_id, req.get("requested_units", 5)))
    set_clock(lock_clock)
    current = get_drop(drop_id)
    resp = api_client.lock_allocation(
        drop_id, {"expected_drop_version": current["version"]}, _ADMIN)
    pair["drop"] = get_success_data(resp)
    pair["allocations"] = allocations
    return pair


def setup_authorized_dealer_with_open_drop(dealer_kwargs: dict = None,
                                           open_clock: str = "2026-09-06T00:00:00Z",
                                           line_overrides: dict = None,
                                           drop_overrides: dict = None) -> dict:
    """Authorized dealer plus an ALLOCATION_OPEN drop — the standing preamble
    for allocation-request tests.

    Returns {"dealer", "application", "line", "drop"}.
    """
    pair = create_authorized_dealer(**(dealer_kwargs or {}))
    opened = setup_open_drop(open_clock, line_overrides, drop_overrides)
    return {**pair, **opened}


def setup_allocated_dealer(requested_units: int = 5,
                           dealer_kwargs: dict = None,
                           lock_clock: str = "2026-09-21T00:00:00Z",
                           line_overrides: dict = None,
                           drop_overrides: dict = None) -> dict:
    """Authorized dealer with an ALLOCATED allocation on a locked drop
    (request fits the pool, so it grants in full).

    Returns {"dealer", "application", "line", "drop", "allocation"}.
    """
    base = setup_authorized_dealer_with_open_drop(
        dealer_kwargs=dealer_kwargs, line_overrides=line_overrides,
        drop_overrides=drop_overrides)
    dealer_id = base["dealer"]["id"]
    allocation = create_allocation_request(dealer_id, base["drop"]["id"],
                                           requested_units)
    set_clock(lock_clock)
    current = get_drop(base["drop"]["id"])
    api_client.lock_allocation(
        base["drop"]["id"], {"expected_drop_version": current["version"]}, _ADMIN)
    return {**base,
            "drop": get_drop(base["drop"]["id"]),
            "allocation": get_allocation(allocation["id"])}


# ===========================================================================
# Tier 3 — Customization order lifecycle (PRD 3.5-3.8)
# ===========================================================================
def create_order(product_line_id: str, colorway_drop_id: str,
                 buyer_ref: str = "buyer-std", **overrides) -> dict:
    """Create a customization order as the Buyer; buyer_ref equals the acting
    X-User-ID. All four axes start at rest and quote_variant is NONE."""
    overrides["buyer_ref"] = buyer_ref
    resp = api_client.create_customization_order(
        create_customization_order_payload(product_line_id, colorway_drop_id,
                                           **overrides),
        make_buyer_headers(buyer_ref))
    return get_success_data(resp)


def submit_order(order_id: str, buyer_ref: str) -> dict:
    """Submit the order: PROVISIONAL quote, payment UNPAID -> AUTHORIZED."""
    resp = api_client.submit_order(order_id, make_buyer_headers(buyer_ref))
    return get_success_data(resp)


def create_submitted_order(buyer_ref: str = "buyer-std",
                           line_overrides: dict = None,
                           drop_overrides: dict = None,
                           **order_overrides) -> dict:
    """Catalog + order + submit.

    Returns {"line", "drop", "order" (payment AUTHORIZED)}.
    """
    pair = setup_catalog(line_overrides, drop_overrides)
    order = create_order(pair["line"]["id"], pair["drop"]["id"],
                         buyer_ref=buyer_ref, **order_overrides)
    order = submit_order(order["id"], buyer_ref)
    return {**pair, "order": order}


def create_print_slot(**overrides) -> dict:
    """Open a print slot as ProductionLead (starts OPEN; peak_overlap computed
    against the peak window)."""
    resp = api_client.create_print_slot(create_print_slot_payload(**overrides),
                                        _PRODUCTION)
    return get_success_data(resp)


def reserve_slot(order_id: str, slot_id: str, buyer_ref: str) -> dict:
    """Reserve print capacity. Lands HELD (schedule RESERVED) when the slot's
    available minutes cover the footprint — exact fit counts — else
    WAITLISTED with the schedule still UNSCHEDULED."""
    resp = api_client.reserve_slot(order_id, {"slot_id": slot_id},
                                   make_buyer_headers(buyer_ref))
    return get_success_data(resp)


def release_slot(order_id: str, buyer_ref: str) -> dict:
    """Release a HELD/CONFIRMED reservation or abandon a WAITLISTED spot;
    freed capacity runs waitlist promotion."""
    resp = api_client.release_slot(order_id, make_buyer_headers(buyer_ref))
    return get_success_data(resp)


def create_reserved_order(buyer_ref: str = "buyer-std",
                          line_overrides: dict = None,
                          drop_overrides: dict = None,
                          slot_overrides: dict = None,
                          **order_overrides) -> dict:
    """Submitted order with a HELD reservation on an OPEN off-peak slot
    (artwork still pending — allowed off peak).

    Returns {"line", "drop", "slot", "order"}.
    """
    trio = create_submitted_order(buyer_ref, line_overrides, drop_overrides,
                                  **order_overrides)
    slot = create_print_slot(**(slot_overrides or {}))
    order = reserve_slot(trio["order"]["id"], slot["id"], buyer_ref)
    return {**trio, "slot": slot, "order": order}


# --- Artwork proofing (PRD 3.6) ---
def submit_proof(order_id: str, buyer_ref: str, **proof_overrides) -> dict:
    """Submit a proof round as the Buyer; increments the order's proof_round
    and supersedes a CHANGES_REQUESTED predecessor."""
    resp = api_client.create_artwork_proof(
        create_artwork_proof_payload(order_id, **proof_overrides),
        make_buyer_headers(buyer_ref))
    return get_success_data(resp)


def approve_proof(proof_id: str, reviewer_id: str = "pp-1") -> dict:
    """Approve the latest proof as PrepressTech: computes the FINAL quote and
    confirms a HELD reservation atomically."""
    resp = api_client.approve_proof(proof_id, make_prepress_tech_headers(reviewer_id))
    return get_success_data(resp)


def request_proof_changes(proof_id: str, reviewer_id: str = "pp-1",
                          review_notes: str = "fix kerning") -> dict:
    """Request changes on the latest proof as PrepressTech; the third round
    lands the order's artwork axis in PROOF_EXHAUSTED."""
    resp = api_client.request_proof_changes(
        proof_id, {"review_notes": review_notes},
        make_prepress_tech_headers(reviewer_id))
    return get_success_data(resp)


def approve_order_art(order_id: str, buyer_ref: str,
                      reviewer_id: str = "pp-1", **proof_overrides) -> dict:
    """Submit one proof and approve it. Works with or without a reservation;
    the order's artwork axis lands ART_APPROVED with the FINAL quote stored.

    Returns {"order": <refreshed>, "proof": <APPROVED>}.
    """
    proof = submit_proof(order_id, buyer_ref, **proof_overrides)
    proof = approve_proof(proof["id"], reviewer_id)
    return {"order": get_order(order_id), "proof": proof}


def create_art_approved_order(buyer_ref: str = "buyer-std",
                              line_overrides: dict = None,
                              drop_overrides: dict = None,
                              slot_overrides: dict = None,
                              proof_overrides: dict = None,
                              **order_overrides) -> dict:
    """Reserved order whose artwork is approved — the reservation has
    auto-confirmed (reservation CONFIRMED, schedule CONFIRMED).

    Returns {"line", "drop", "slot", "order", "proof"}.
    """
    quad = create_reserved_order(buyer_ref, line_overrides, drop_overrides,
                                 slot_overrides, **order_overrides)
    approved = approve_order_art(quad["order"]["id"], buyer_ref,
                                 **(proof_overrides or {}))
    return {**quad, **approved}


def create_in_production_order(buyer_ref: str = "buyer-std",
                               pre_production_clock: str = None,
                               line_overrides: dict = None,
                               drop_overrides: dict = None,
                               slot_overrides: dict = None,
                               proof_overrides: dict = None,
                               **order_overrides) -> dict:
    """Art-approved order moved into production: slot LOCKED, schedule
    CONFIRMED -> IN_PRODUCTION. pre_production_clock pins the logical clock
    before the slot lock (must stay before the slot's window_end).

    Returns {"line", "drop", "slot", "order", "proof"}.
    """
    bundle = create_art_approved_order(buyer_ref, line_overrides, drop_overrides,
                                       slot_overrides, proof_overrides,
                                       **order_overrides)
    if pre_production_clock is not None:
        set_clock(pre_production_clock)
    api_client.lock_print_slot(bundle["slot"]["id"], _PRODUCTION)
    order = get_success_data(api_client.start_production(
        bundle["order"]["id"], _PRODUCTION))
    return {**bundle, "order": order,
            "slot": get_slot(bundle["slot"]["id"])}


def create_completed_order(buyer_ref: str = "buyer-std",
                           pre_production_clock: str = None,
                           complete_clock: str = None,
                           line_overrides: dict = None,
                           drop_overrides: dict = None,
                           slot_overrides: dict = None,
                           proof_overrides: dict = None,
                           **order_overrides) -> dict:
    """Order driven to schedule COMPLETE with payment CAPTURED: reservation
    CONSUMED (minutes stay booked) and completed_at stamped from the clock.
    complete_clock pins the clock immediately before completion, which fixes
    completed_at — the anchor for the 45-day return window and for
    order-anchored warranty claims.

    Returns {"line", "drop", "slot", "order", "proof"}.
    """
    bundle = create_in_production_order(buyer_ref, pre_production_clock,
                                        line_overrides, drop_overrides,
                                        slot_overrides, proof_overrides,
                                        **order_overrides)
    if complete_clock is not None:
        set_clock(complete_clock)
    order = get_success_data(api_client.complete_production(
        bundle["order"]["id"], {"qc_outcome": "PASS"}, _PRODUCTION))
    return {**bundle, "order": order}


def create_return_requested_order(reason: str = "DEFECT",
                                  affected_unit_count: int = 1,
                                  buyer_ref: str = "buyer-std",
                                  **completed_kwargs) -> dict:
    """Completed, captured order with a return requested
    (return_status RETURN_REQUESTED).

    Returns {"line", "drop", "slot", "order", "proof"}.
    """
    bundle = create_completed_order(buyer_ref=buyer_ref, **completed_kwargs)
    order = get_success_data(api_client.request_return(
        bundle["order"]["id"],
        request_return_payload(reason, affected_unit_count),
        make_buyer_headers(buyer_ref)))
    return {**bundle, "order": order}


def decide_return(order_id: str, decision: str, resolution: str = None,
                  care_id: str = "cc-1", decision_notes: str = None) -> dict:
    """Decide a return as CustomerCare: DENY lands RETURN_DENIED; APPROVE
    settles per the resolution (FULL_REFUND / PARTIAL_CREDIT / REMAKE)."""
    overrides = {}
    if resolution is not None:
        overrides["resolution"] = resolution
    if decision_notes is not None:
        overrides["decision_notes"] = decision_notes
    resp = api_client.decide_return(
        order_id, decide_return_payload(decision, **overrides),
        make_customer_care_headers(care_id))
    return get_success_data(resp)


def cancel_order(order_id: str, buyer_ref: str = "buyer-std") -> dict:
    """Cancel an order as its Buyer (cancellation fee applies once art is
    approved; any reservation is released with waitlist promotion)."""
    resp = api_client.cancel_order(order_id, make_buyer_headers(buyer_ref))
    return get_success_data(resp)


def create_proof_exhausted_order(buyer_ref: str = "buyer-std",
                                 line_overrides: dict = None,
                                 drop_overrides: dict = None,
                                 **order_overrides) -> dict:
    """Submitted order cycled through all three proof rounds with changes
    requested each time; the artwork axis lands PROOF_EXHAUSTED (terminal;
    only cancel remains).

    Returns {"line", "drop", "order", "proofs"}.
    """
    trio = create_submitted_order(buyer_ref, line_overrides, drop_overrides,
                                  **order_overrides)
    order_id = trio["order"]["id"]
    proofs = []
    for round_no in (1, 2, 3):
        proof = submit_proof(order_id, buyer_ref,
                             artwork_file_ref=f"s3://art/std-v{round_no}.ai")
        proof = request_proof_changes(proof["id"])
        proofs.append(proof)
    return {**trio, "order": get_order(order_id), "proofs": proofs}


# ===========================================================================
# Tier 3 — Warranty claims (PRD 3.9)
# ===========================================================================
def create_warranty_claim(headers: dict = None, **overrides) -> dict:
    """File a warranty claim. When headers is omitted the caller identity is
    derived from the payload: Dealer headers keyed on dealer_id for
    DEALER-source claims, Buyer headers keyed on buyer_ref for DTC."""
    payload = create_warranty_claim_payload(**overrides)
    if headers is None:
        if payload.get("claim_source") == "DEALER":
            headers = make_dealer_headers(payload["dealer_id"])
        else:
            headers = make_buyer_headers(payload.get("buyer_ref", "buyer-std"))
    resp = api_client.create_warranty_claim(payload, headers)
    return get_success_data(resp)


def file_dtc_claims(product_line_id: str, buyer_ref: str, count: int,
                    purchase_date: str = "2026-01-01T00:00:00Z",
                    component: str = "LID", serial_prefix: str = "S") -> list:
    """File `count` DTC claims for one buyer (distinct serials). The fraud
    flag turns true once the claimant has at least 3 other non-DENIED claims
    in the trailing 365 days — i.e. on the 4th claim in a fresh database."""
    claims = []
    for i in range(1, count + 1):
        claims.append(create_warranty_claim(
            claim_source="DTC",
            buyer_ref=buyer_ref,
            product_line_id=product_line_id,
            serial_number=f"{serial_prefix}-{i}",
            component=component,
            purchase_date=purchase_date,
        ))
    return claims


def start_claim_review(claim_id: str, agent_id: str = "wa-1") -> dict:
    resp = api_client.start_claim_review(
        claim_id, make_warranty_agent_headers(agent_id))
    return get_success_data(resp)


def decide_claim(claim_id: str, outcome: str = "APPROVE_REPAIR",
                 agent_id: str = "wa-1", decision_reason: str = "covered") -> dict:
    resp = api_client.decide_warranty_claim(
        claim_id, decide_claim_payload(outcome, decision_reason),
        make_warranty_agent_headers(agent_id))
    return get_success_data(resp)
