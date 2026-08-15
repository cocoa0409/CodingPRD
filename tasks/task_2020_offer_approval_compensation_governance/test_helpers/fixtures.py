"""Composite setup helpers.

Every helper builds its preconditions from scratch against the running API
(the server restarts with an empty database before every test) and uses the
lenient get_success_data() validator so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_requisition_payload, create_candidate_payload,
    create_equity_snapshot_payload, create_offer_payload, create_perk_payload,
)
from .test_users import TEST_USERS, make_candidate_headers

HM = TEST_USERS["hm_headers"]
HM2 = TEST_USERS["hm2_headers"]
REC = TEST_USERS["recruiter_headers"]
CA = TEST_USERS["comp_analyst_headers"]
FIN = TEST_USERS["finance_headers"]
DIR = TEST_USERS["director_headers"]
VP = TEST_USERS["vp_headers"]
SCR = TEST_USERS["screener_headers"]
ADMIN = TEST_USERS["hr_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: State progression — requisition
# ---------------------------------------------------------------------------

def create_draft_requisition(hm_headers=None, **overrides):
    """Create a requisition in DRAFT. Returns the requisition dict."""
    resp = api_client.create_requisition(create_requisition_payload(**overrides), hm_headers or HM)
    return get_success_data(resp)


def create_open_requisition(hm_headers=None, **overrides):
    """Create a requisition and walk it DRAFT -> BUDGET_REVIEW -> RANGE_APPROVAL -> OPEN."""
    hm = hm_headers or HM
    req = create_draft_requisition(hm, **overrides)
    get_success_data(api_client.submit_requisition(req["id"], hm))
    get_success_data(api_client.review_decision_requisition(req["id"], {"decision": "APPROVE"}, FIN))
    req = get_success_data(api_client.review_decision_requisition(req["id"], {"decision": "APPROVE"}, CA))
    assert req["status"] == "OPEN", f"Setup failed: requisition not OPEN (got {req['status']})"
    return req


# ---------------------------------------------------------------------------
# Tier 2: supporting entities
# ---------------------------------------------------------------------------

def create_candidate_recruited(recruiter_headers=None, **overrides):
    resp = api_client.create_candidate(create_candidate_payload(**overrides), recruiter_headers or REC)
    return get_success_data(resp)


def create_peer_snapshots(role_level, geo_tier, base_list, ca_headers=None):
    """Create one InternalEquitySnapshot per entry of base_list. Returns the list."""
    out = []
    for base in base_list:
        resp = api_client.create_equity_snapshot(
            create_equity_snapshot_payload(role_level=role_level, geo_tier=geo_tier, base_cents=base),
            ca_headers or CA,
        )
        out.append(get_success_data(resp))
    return out


def create_standard_peers(base_list=(19000000, 19500000, 20000000), role_level="L5", geo_tier="T1"):
    return create_peer_snapshots(role_level, geo_tier, list(base_list))


def create_policy(min_band_severity, required_role, chain_position, admin_headers=None):
    from .factories import create_approval_policy_payload
    resp = api_client.create_approval_policy(
        create_approval_policy_payload(
            min_band_severity=min_band_severity,
            required_role=required_role,
            chain_position=chain_position,
        ),
        admin_headers or ADMIN,
    )
    return get_success_data(resp)


def setup_exception_policy_rows(admin_headers=None):
    """The canonical 3-row routing table used by EXCEPTION-band tests."""
    admin = admin_headers or ADMIN
    create_policy("ABOVE_BAND", "CompAnalyst", 1, admin)
    create_policy("EXCEPTION", "DepartmentDirector", 2, admin)
    create_policy("EXCEPTION", "VPPeople", 3, admin)


# ---------------------------------------------------------------------------
# Tier 3: offer lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_offer(req, cand, creator_headers=None, **overrides):
    """Create a DRAFT offer against an OPEN requisition. Returns the offer dict."""
    payload = create_offer_payload(requisition_id=req["id"], candidate_id=cand["id"], **overrides)
    resp = api_client.create_offer(payload, creator_headers or REC)
    return get_success_data(resp)


def create_submitted_offer(req, cand, creator_headers=None, **overrides):
    """Create + submit an offer. Returns (offer, steps) with steps ordered by sequence."""
    offer = create_draft_offer(req, cand, creator_headers, **overrides)
    return submit_offer_and_get_steps(offer, creator_headers or REC)


def submit_offer_and_get_steps(offer, headers=None):
    """Submit a DRAFT/RETURNED offer; return (submitted offer, ordered steps)."""
    h = headers or REC
    submitted = get_success_data(api_client.submit_offer(offer["id"], h))
    assert submitted["status"] == "PENDING_APPROVAL", (
        f"Setup failed: submit landed in {submitted['status']}"
    )
    steps = get_success_data(api_client.list_approval_steps(offer["id"], h))
    return submitted, steps


def approve_chain(steps, decider_headers_by_role=None, hm_headers=None):
    """Approve every step of the chain in sequence order.

    decider_headers_by_role maps required_role -> headers for steps beyond the
    HiringManager step (which uses hm_headers). Returns the final offer dict.
    """
    hm = hm_headers or HM
    role_headers = {"HiringManager": hm, "CompAnalyst": CA, "DepartmentDirector": DIR, "VPPeople": VP}
    if decider_headers_by_role:
        role_headers.update(decider_headers_by_role)
    offer_id = steps[0]["offer_id"]
    for step in sorted(steps, key=lambda s: s["sequence"]):
        get_success_data(
            api_client.decide_approval_step(step["id"], {"decision": "APPROVED"}, role_headers[step["required_role"]])
        )
    return get_success_data(api_client.get_offer(offer_id, REC))


def create_approved_offer(req, cand, creator_headers=None, hm_headers=None, **overrides):
    """Create + submit + fully approve. Returns the APPROVED offer dict."""
    offer, steps = create_submitted_offer(req, cand, creator_headers, **overrides)
    final = approve_chain(steps, hm_headers=hm_headers)
    assert final["status"] == "APPROVED", f"Setup failed: offer not APPROVED (got {final['status']})"
    return final


def create_lettered_offer(req, cand, creator_headers=None, hm_headers=None, **overrides):
    """Create through APPROVED, then generate the first letter. Returns (offer, letter)."""
    offer = create_approved_offer(req, cand, creator_headers, hm_headers, **overrides)
    letter = get_success_data(api_client.create_offer_letter(offer["id"], REC))
    offer = get_success_data(api_client.get_offer(offer["id"], REC))
    assert offer["status"] == "LETTER_GENERATED", f"Setup failed: offer is {offer['status']}"
    return offer, letter


def create_extended_offer(req, cand, creator_headers=None, hm_headers=None, **overrides):
    """Create through LETTER_GENERATED, then extend. Returns the EXTENDED offer dict."""
    offer, _letter = create_lettered_offer(req, cand, creator_headers, hm_headers, **overrides)
    offer = get_success_data(api_client.extend_offer(offer["id"], REC))
    assert offer["status"] == "EXTENDED", f"Setup failed: offer is {offer['status']}"
    return offer


def create_accepted_offer(req, cand, creator_headers=None, hm_headers=None, **overrides):
    """Create through EXTENDED, then candidate-accept. Returns the ACCEPTED offer dict."""
    offer = create_extended_offer(req, cand, creator_headers, hm_headers, **overrides)
    offer = get_success_data(api_client.accept_offer(offer["id"], make_candidate_headers(cand["id"])))
    assert offer["status"] == "ACCEPTED", f"Setup failed: offer is {offer['status']}"
    return offer


def record_rejected_round(offer, proposed_base_cents, recruiter_headers=None):
    """Record a negotiation round on an EXTENDED offer and reject it (back to EXTENDED).

    Returns the refreshed offer dict.
    """
    rec = recruiter_headers or REC
    current = get_success_data(api_client.get_offer(offer["id"], rec))
    rnd = get_success_data(api_client.create_negotiation_round(
        offer["id"],
        {"expected_offer_version": current["version"], "proposed_base_cents": proposed_base_cents},
        rec,
    ))
    get_success_data(api_client.decide_negotiation_round(rnd["id"], {"outcome": "REJECTED"}, rec))
    return get_success_data(api_client.get_offer(offer["id"], rec))


# ---------------------------------------------------------------------------
# Tier 4: threshold / accumulation targeting
# ---------------------------------------------------------------------------

def create_offer_with_perks(req, cand, perk_payloads, creator_headers=None, **offer_overrides):
    """Create a DRAFT offer plus a list of perks. Returns (offer, perks)."""
    rec = creator_headers or REC
    offer = create_draft_offer(req, cand, rec, **offer_overrides)
    perks = []
    for p in perk_payloads:
        perks.append(get_success_data(api_client.create_perk(offer["id"], create_perk_payload(**p), rec)))
    offer = get_success_data(api_client.get_offer(offer["id"], rec))
    return offer, perks


# ---------------------------------------------------------------------------
# Tier 5: finalization / terminal-state setups
# ---------------------------------------------------------------------------

def create_hired_offer(req, cand, creator_headers=None, hm_headers=None, perk_payloads=None, **overrides):
    """Full lifecycle through HIRED via two cleared checks. Returns (offer, perks)."""
    rec = creator_headers or REC
    perks = []
    if perk_payloads is not None:
        offer, perks = create_offer_with_perks(req, cand, perk_payloads, rec, **overrides)
        submitted, steps = submit_offer_and_get_steps(offer, rec)
    else:
        submitted, steps = create_submitted_offer(req, cand, rec, **overrides)
    final = approve_chain(steps, hm_headers=hm_headers)
    letter = get_success_data(api_client.create_offer_letter(final["id"], rec))
    offer = get_success_data(api_client.extend_offer(final["id"], rec))
    offer = get_success_data(api_client.accept_offer(offer["id"], make_candidate_headers(cand["id"])))
    bg = get_success_data(api_client.create_clearance_check(offer["id"], {"kind": "BACKGROUND"}, SCR))
    ref = get_success_data(api_client.create_clearance_check(offer["id"], {"kind": "REFERENCE"}, SCR))
    for chk in (bg, ref):
        get_success_data(api_client.transition_clearance_check(chk["id"], {"to": "IN_PROGRESS"}, SCR))
        get_success_data(api_client.transition_clearance_check(chk["id"], {"to": "CLEARED"}, SCR))
    offer = get_success_data(api_client.get_offer(offer["id"], rec))
    assert offer["status"] == "HIRED", f"Setup failed: offer is {offer['status']}"
    return offer, perks
