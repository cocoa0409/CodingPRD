"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the server is restarted with an empty database before each
test). Helpers use get_success_data() so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Ownership threading: CenterCoordinator calls that are ownership-gated are
always issued with make_center_coordinator_headers(<center id>) — never
with the shared TEST_USERS fallback.
"""
from datetime import datetime, timedelta
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_center_payload,
    create_claim_payload,
    create_chain_run_payload,
    create_crossmatch_review_payload,
    create_donor_payload,
    create_itinerary_payload,
    create_outcome_payload,
    create_pair_payload,
    create_recipient_payload,
    create_shipment_payload,
    create_slot_payload,
)
from .test_users import (
    TEST_USERS,
    make_center_coordinator_headers,
)

ADMIN = TEST_USERS["registry_admin_headers"]
OPERATOR = TEST_USERS["match_operator_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str) -> datetime:
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1]
    if "." in ts:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f")
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")


def reset_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    """Set the logical clock to a known time (PRD §1: startup default is
    2026-09-01T00:00:00Z; tests reset it explicitly for determinism)."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def create_center(**overrides) -> dict:
    """Create an ACTIVE TransplantCenter. Returns the center object."""
    resp = api_client.create_center(create_center_payload(**overrides), ADMIN)
    return get_success_data(resp, expected_status=201)


def create_donor(center: dict, **overrides) -> dict:
    """Register a Donor at the given center (coordinator of that center)."""
    payload = create_donor_payload(center["id"], **overrides)
    resp = api_client.create_donor(payload, make_center_coordinator_headers(center["id"]))
    return get_success_data(resp, expected_status=201)


def create_recipient(center: dict, **overrides) -> dict:
    payload = create_recipient_payload(center["id"], **overrides)
    resp = api_client.create_recipient(payload, make_center_coordinator_headers(center["id"]))
    return get_success_data(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Tier 2: pair progression
# ---------------------------------------------------------------------------

def create_in_pool_pair(
    donor_center: dict,
    recipient_center: dict,
    donor_abo: str = "A",
    recipient_abo: str = "B",
    donor_hla: dict = None,
    recipient_cpra: int = 20,
    recipient_unacceptable_antigens: list = None,
    donor_kdri: int = 80,
    compatible_pair_opt_in: bool = False,
    **donor_overrides,
) -> dict:
    """Register donor + recipient + pair, verify, and enter the pool.

    Defaults build an ABO-incompatible pair (donor A -> recipient B) so
    pool entry succeeds without the compatible-pair opt-in flag.
    Returns {"donor", "recipient", "pair"}.
    """
    donor_hla = donor_hla or {}
    donor = create_donor(
        donor_center, abo_type=donor_abo, kdri_score=donor_kdri, **donor_hla,
        **donor_overrides,
    )
    recipient = create_recipient(
        recipient_center,
        abo_type=recipient_abo,
        cpra_percent=recipient_cpra,
        unacceptable_antigens=recipient_unacceptable_antigens or [],
        paired_donor_id=donor["id"],
    )
    coord_dc = make_center_coordinator_headers(donor_center["id"])
    resp = api_client.create_pair(
        create_pair_payload(donor["id"], recipient["id"], donor_center["id"]),
        coord_dc,
    )
    pair = get_success_data(resp, expected_status=201)
    get_success_data(api_client.verify_pair(pair["id"], coord_dc))
    body = {"compatible_pair_opt_in": True} if compatible_pair_opt_in else {}
    get_success_data(api_client.enter_pool(pair["id"], body, coord_dc))
    return {"donor": donor, "recipient": recipient, "pair": pair}


def create_altruistic_donor(center: dict, abo_type: str = "O", **overrides) -> dict:
    """Register an ALTRUISTIC donor (a non-directed chain starter)."""
    return create_donor(center, abo_type=abo_type, donor_kind="ALTRUISTIC", **overrides)


# ---------------------------------------------------------------------------
# Tier 3: chain-run execution and offer discovery
# ---------------------------------------------------------------------------

def execute_chain_run(run_label: str = None) -> dict:
    """Create a chain run and execute it with the correct OCC version.
    Returns the executed ChainRun."""
    payload = create_chain_run_payload()
    if run_label is not None:
        payload["run_label"] = run_label
    run = get_success_data(api_client.create_chain_run(payload, OPERATOR), expected_status=201)
    resp = api_client.execute_chain_run(
        run["id"], {"expected_run_version": run["version"]}, OPERATOR
    )
    return get_success_data(resp)


def publish_chain_run(run: dict) -> dict:
    return get_success_data(api_client.publish_chain_run(run["id"], OPERATOR))


def list_offers(params: dict = None) -> list:
    data, _meta = _list_paginated(api_client.list_match_offers(OPERATOR, params=params))
    return data


def _list_paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def find_offer(donor_id: str, recipient_id: str) -> dict:
    """Locate the minted MatchOffer for a (donor, recipient) edge."""
    offers = list_offers()
    for offer in offers:
        if offer["donor_id"] == donor_id and offer["recipient_id"] == recipient_id:
            return offer
    raise AssertionError(
        f"Setup failed: no MatchOffer found for donor={donor_id} recipient={recipient_id}"
    )


def find_chain(chain_id: str) -> dict:
    return get_success_data(api_client.get_chain(chain_id, OPERATOR))


# ---------------------------------------------------------------------------
# Tier 4: offer progression (crossmatch / accept / lock / schedule)
# ---------------------------------------------------------------------------

def review_offer(offer: dict, virtual_result: str = "NEGATIVE", dsa_mfi_max: int = 0,
                 flow_shift: int = 100) -> dict:
    """Submit a passing crossmatch review from the recipient center's
    coordinator. Returns the CrossmatchReview."""
    headers = make_center_coordinator_headers(offer["recipient_center_id"])
    payload = create_crossmatch_review_payload(
        virtual_result=virtual_result,
        dsa_mfi_max=dsa_mfi_max,
        flow_cytometry_channel_shift=flow_shift,
    )
    resp = api_client.submit_crossmatch_review(offer["id"], payload, headers)
    return get_success_data(resp)


def accept_offer(offer: dict) -> dict:
    headers = make_center_coordinator_headers(offer["recipient_center_id"])
    return get_success_data(api_client.center_accept_offer(offer["id"], headers))


def setup_two_pair_chain(run_label: str = None):
    """Build the canonical two-pair ABO-crossed pool, seed an ALTRUISTIC donor
    to open the chain, execute a run, and publish it. Per PRD §3.3 Step 3,
    only ALTRUISTIC/BRIDGE donors start chains; pair donors never do.

    The deterministic chain produced is:
      offer[0]: altruistic donor (O, center A)  -> p1 recipient (B, center B)
      offer[1]: p1 donor (A, center A)          -> p2 recipient (A, center A)

    Returns a dict with centers, pairs (p1, p2), the altruistic starter donor,
    run, offers (list of two, position order), chain.
    """
    reset_clock()
    center_a = create_center()
    center_b = create_center()
    p1 = create_in_pool_pair(center_a, center_b, donor_abo="A", recipient_abo="B")
    p2 = create_in_pool_pair(center_b, center_a, donor_abo="B", recipient_abo="A")
    starter = create_altruistic_donor(center_a, abo_type="O")
    run = execute_chain_run(run_label or "canonical-run")
    publish_chain_run(run)
    offers = list_offers()
    assert len(offers) == 2, (
        f"Setup failed: expected exactly 2 offers from the canonical pool, got {len(offers)}"
    )
    offers.sort(key=lambda o: o["position_index"])
    chains, _meta = _list_paginated(api_client.list_chains(OPERATOR))
    assert len(chains) == 1, (
        f"Setup failed: expected exactly 1 chain, got {len(chains)}"
    )
    chain = chains[0]
    assert chain["chain_state"] == "ACCEPTING", (
        f"Setup failed: published chain must be ACCEPTING, got {chain['chain_state']}"
    )
    return {
        "center_a": center_a,
        "center_b": center_b,
        "p1": p1,
        "p2": p2,
        "starter": starter,
        "run": run,
        "offers": offers,
        "chain": chain,
    }


def setup_locked_chain():
    """Canonical two-pair chain walked to LOCKED: both offers
    crossmatch-passed and center-accepted, then lock with correct OCC
    version. Returns the scenario dict with refreshed chain."""
    ctx = setup_two_pair_chain()
    for offer in ctx["offers"]:
        review_offer(offer)
        accept_offer(offer)
    chain = find_chain(ctx["chain"]["id"])
    resp = api_client.lock_chain(
        chain["id"], {"expected_chain_version": chain["version"]}, OPERATOR
    )
    ctx["chain"] = get_success_data(resp)
    return ctx


def _future_window(now_iso: str, start_hours: int, end_hours: int) -> tuple:
    start = _parse(now_iso) + timedelta(hours=start_hours)
    end = _parse(now_iso) + timedelta(hours=end_hours)
    return _iso(start), _iso(end)


def setup_scheduled_chain():
    """Canonical chain walked to SCHEDULED: locked, then scheduled with one
    donor-center slot and one recipient-center slot per offer. Returns the
    scenario dict with refreshed chain and the reserved slot ids.

    Slots at the same center use non-overlapping windows: PRD §3.5 forbids
    two RESERVED/CONSUMED slots at one center from overlapping."""
    ctx = setup_locked_chain()
    slots = []
    seen_windows = {}  # center_id -> next start hour offset
    for i, offer in enumerate(ctx["offers"]):
        for center_id, room in (
            (offer["donor_center_id"], "NEPHRECTOMY_OR"),
            (offer["recipient_center_id"], "TRANSPLANT_OR"),
        ):
            base = 168 + i * 24
            offset = seen_windows.get(center_id, base)
            # Ensure this slot does not overlap an earlier one at the same center.
            offset = max(offset, base)
            start, end = _future_window(DEFAULT_CLOCK_ISO, offset, offset + 4)
            resp = api_client.create_slot(
                create_slot_payload(center_id, start, end, room_kind=room),
                make_center_coordinator_headers(center_id),
            )
            slots.append(get_success_data(resp, expected_status=201))
            seen_windows[center_id] = offset + 4
    chain = ctx["chain"]
    scheduled_date = _iso(_parse(DEFAULT_CLOCK_ISO) + timedelta(hours=168))
    resp = api_client.schedule_chain(
        chain["id"],
        {
            "expected_chain_version": chain["version"],
            "scheduled_date": scheduled_date,
            "slot_ids": [s["id"] for s in slots],
        },
        OPERATOR,
    )
    ctx["chain"] = get_success_data(resp)
    ctx["slots"] = slots
    return ctx


def setup_executing_chain():
    """Canonical chain walked to EXECUTING."""
    ctx = setup_scheduled_chain()
    get_success_data(api_client.start_chain_execution(ctx["chain"]["id"], OPERATOR))
    ctx["chain"] = find_chain(ctx["chain"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: surgery / shipment / transplant lifecycle
# ---------------------------------------------------------------------------

def complete_nephrectomy(donor: dict) -> dict:
    headers = make_center_coordinator_headers(donor["home_center_id"])
    return get_success_data(api_client.complete_nephrectomy(donor["id"], headers))


def create_shipment_for_offer(offer: dict, **overrides) -> dict:
    payload = create_shipment_payload(offer["id"], **overrides)
    resp = api_client.create_shipment(payload, LOGISTICS)
    return get_success_data(resp, expected_status=201)


def deliver_offer_end_to_end(offer: dict, donor: dict,
                             cold_ischemia_max_hours: Optional[int] = None) -> dict:
    """Complete the donor's nephrectomy, plan + depart + deliver a shipment.
    The clock is NOT advanced, so the actual cold ischemia is ~0 hours —
    safely under any positive cap. Returns the delivered OrganShipment."""
    overrides = {}
    if cold_ischemia_max_hours is not None:
        overrides["cold_ischemia_max_hours"] = cold_ischemia_max_hours
    complete_nephrectomy(donor)
    shipment = create_shipment_for_offer(offer, **overrides)
    get_success_data(api_client.depart_shipment(shipment["id"], LOGISTICS))
    return get_success_data(api_client.deliver_shipment(shipment["id"], LOGISTICS))


def complete_transplant(recipient: dict) -> dict:
    headers = make_center_coordinator_headers(recipient["home_center_id"])
    return get_success_data(api_client.complete_transplant(recipient["id"], headers))


def setup_broken_chain_after_first_transplant():
    """Canonical chain where position-1 recipient has been transplanted and
    the position-2 donor then withdraws, breaking the chain.

    Chain structure from the canonical pool (PRD §3.3: chains open from an
    ALTRUISTIC starter, never a pair donor):
      offer[0]: donor = starter (altruistic O, center A) -> recipient = p1 recipient (B, center B)
      offer[1]: donor = p1 donor (A, center A)           -> recipient = p2 recipient (A, center A)

    Returns (ctx, break_event) with refreshed entities.
    """
    ctx = setup_executing_chain()
    offer1, offer2 = ctx["offers"]
    # Position-1: starter donates, organ delivered, recipient p1 transplanted.
    deliver_offer_end_to_end(offer1, ctx["starter"])
    complete_transplant(ctx["p1"]["recipient"])
    # Position-2 donor (p1's paired donor) withdraws -> ChainBreakEvent.
    get_success_data(api_client.donor_withdraw(
        ctx["p1"]["donor"]["id"],
        make_center_coordinator_headers(ctx["center_a"]["id"]),
    ))
    events, _meta = _list_paginated(api_client.list_chain_breaks(OPERATOR))
    assert len(events) >= 1, "Setup failed: expected a chain break event after withdrawal"
    event = events[0]
    ctx["chain"] = find_chain(ctx["chain"]["id"])
    return ctx, event


# ---------------------------------------------------------------------------
# Tier 6: protection policy / claims
# ---------------------------------------------------------------------------

def setup_donor_with_policy():
    """Donor whose nephrectomy completed inside the canonical chain —
    a DonorProtectionPolicy has been minted. Returns (ctx, donor, policy).

    Position-1 donor in the canonical chain is the altruistic starter."""
    ctx = setup_executing_chain()
    offer1 = ctx["offers"][0]
    donor = ctx["starter"]
    complete_nephrectomy(donor)
    donor = get_success_data(api_client.get_donor(donor["id"], ADMIN))
    assert donor.get("protection_policy_id"), (
        "Setup failed: donor has no protection policy after nephrectomy"
    )
    policy = get_success_data(api_client.get_policy(donor["protection_policy_id"], ADMIN))
    return ctx, donor, policy


def setup_claim_under_review():
    """A COMPLICATION claim walked to UNDER_REVIEW.

    Submission is by the center coordinator; start-review by a distinct
    admin user; the adjudicating admin for later steps is a third identity
    so segregation-of-duties never trips in happy-path fixtures.

    Returns (ctx, donor, policy, claim, adjudicator_headers).
    """
    ctx, donor, policy = setup_donor_with_policy()
    coord = make_center_coordinator_headers(ctx["center_a"]["id"])
    resp = api_client.create_claim_for_donor(
        donor["id"], create_claim_payload(), coord
    )
    claim = get_success_data(resp, expected_status=201)
    reviewer = TEST_USERS["registry_admin_headers"]
    get_success_data(api_client.start_claim_review(claim["id"], reviewer))
    adjudicator = TEST_USERS["registry_admin_headers"]
    claim = get_success_data(api_client.get_claim(claim["id"], adjudicator))
    return ctx, donor, policy, claim, adjudicator


# ---------------------------------------------------------------------------
# Tier 7: outcome reporting
# ---------------------------------------------------------------------------

def setup_attributed_failed_outcome():
    """Canonical chain with the position-1 transplant completed, a FAILED
    outcome reported and attributed (default: recipient center of the
    offer). Returns (ctx, outcome).

    Position-1 donor is the altruistic starter; position-1 recipient is p1's
    recipient (at center B)."""
    ctx = setup_executing_chain()
    offer1 = ctx["offers"][0]
    deliver_offer_end_to_end(offer1, ctx["starter"])
    complete_transplant(ctx["p1"]["recipient"])
    offer1 = get_success_data(api_client.get_match_offer(offer1["id"], OPERATOR))
    resp = api_client.create_outcome(
        create_outcome_payload(offer1["id"], outcome_kind="FAILED"),
        make_center_coordinator_headers(ctx["center_b"]["id"]),
    )
    outcome = get_success_data(resp, expected_status=201)
    outcome = get_success_data(api_client.attribute_outcome(outcome["id"], {}, ADMIN))
    return ctx, outcome


# ---------------------------------------------------------------------------
# Tier 8: travel
# ---------------------------------------------------------------------------

def create_confirmed_itinerary(donor: dict, **overrides) -> dict:
    """Draft and confirm a travel itinerary; returns the CONFIRMED itinerary."""
    resp = api_client.create_itinerary(
        create_itinerary_payload(donor["id"], **overrides), LOGISTICS
    )
    itinerary = get_success_data(resp, expected_status=201)
    return get_success_data(api_client.confirm_itinerary(itinerary["id"], LOGISTICS))
