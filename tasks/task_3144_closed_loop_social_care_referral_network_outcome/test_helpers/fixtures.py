"""Composite setup helpers.

The server is restarted before every test, so every helper builds its
preconditions from scratch through the API; nothing is carried over.

Identity threading: CaseWorker / OrgAdmin / FunderAdmin are entity-backed by
Organization, so ownership-gated calls always use make_*_headers(<real org id>)
rather than the shared placeholder constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_case_worker_headers,
    make_org_admin_headers,
    make_funder_admin_headers,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock and primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_UTC):
    """Move the server's logical clock to a known instant."""
    return get_success_data(api_client.set_clock(to_iso8601, COORDINATOR))


def create_network(**overrides):
    return get_success_data(api_client.create_network(
        factories.create_network_payload(**overrides), COORDINATOR))


def create_category(code="FOOD", name=None):
    return get_success_data(api_client.create_taxonomy_category(
        factories.create_taxonomy_payload(code=code, name=name or code.title()),
        COORDINATOR))


def create_org(name, org_type, ein, funder_type=None, activate=True):
    """Register an organization and (by default) activate it."""
    overrides = {"name": name, "org_type": org_type, "ein": ein}
    if funder_type is not None:
        overrides["funder_type"] = funder_type
    org = get_success_data(api_client.create_organization(
        factories.create_organization_payload(**overrides), COORDINATOR))
    if activate:
        org = get_success_data(api_client.activate_organization(org["id"], COORDINATOR))
    return org


def create_offering(org_id, **overrides):
    """Declare an offering under an ACTIVE org as its OrgAdmin."""
    overrides.setdefault("category_code", TEST_DEFAULTS["CATEGORY_CODE"])
    return get_success_data(api_client.create_offering(
        org_id, factories.create_offering_payload(**overrides),
        make_org_admin_headers(org_id)))


def create_client(sender_org_id, **overrides):
    """Register a client as a CaseWorker of the sender org."""
    return get_success_data(api_client.create_client(
        factories.create_client_payload(**overrides),
        make_case_worker_headers(sender_org_id)))


def create_consent(client_id, sender_org_id, receiver_org_id, scope="FULL"):
    """Record a consent as a CaseWorker of the sender org."""
    return get_success_data(api_client.create_consent(
        client_id,
        factories.create_consent_payload(sender_org_id=sender_org_id,
                                         receiver_org_id=receiver_org_id,
                                         scope=scope),
        make_case_worker_headers(sender_org_id)))


def create_and_approve_agreement(party_a_org_id, party_b_org_id,
                                 effective_at=None):
    """Create a data-sharing agreement and approve it to ACTIVE."""
    agreement = get_success_data(api_client.create_agreement(
        factories.create_agreement_payload(
            party_a_org_id=party_a_org_id,
            party_b_org_id=party_b_org_id,
            effective_at=effective_at or TEST_DEFAULTS["EFFECTIVE_AT"]),
        COORDINATOR))
    return get_success_data(api_client.approve_agreement(agreement["id"], COORDINATOR))


def create_rate_card(funder_org_id, **overrides):
    """Publish a rate card as the funder's FunderAdmin."""
    overrides.setdefault("category_code", TEST_DEFAULTS["CATEGORY_CODE"])
    return get_success_data(api_client.create_rate_card(
        funder_org_id, factories.create_rate_card_payload(**overrides),
        make_funder_admin_headers(funder_org_id)))


def create_referral(sender_org_id, client_id, receiver_org_id, offering_id,
                    consent_id, category_code=None):
    """Create a DRAFT referral as a CaseWorker of the sender org."""
    return get_success_data(api_client.create_referral(
        factories.create_referral_payload(
            client_id=client_id,
            sender_org_id=sender_org_id,
            receiver_org_id=receiver_org_id,
            service_offering_id=offering_id,
            consent_id=consent_id,
            category_code=category_code or TEST_DEFAULTS["CATEGORY_CODE"]),
        make_case_worker_headers(sender_org_id)))


def get_referral(referral_id, headers=None):
    return get_success_data(api_client.get_referral(
        referral_id, headers or COORDINATOR))


def get_offering(offering_id, headers=None):
    return get_success_data(api_client.get_offering(
        offering_id, headers or COORDINATOR))


def get_client(client_id, headers=None):
    return get_success_data(api_client.get_client(
        client_id, headers or COORDINATOR))


def get_org(org_id, headers=None):
    return get_success_data(api_client.get_organization(
        org_id, headers or COORDINATOR))


def get_claim(claim_id, headers=None):
    return get_success_data(api_client.get_claim(
        claim_id, headers or COORDINATOR))


def get_consent(consent_id, headers=None):
    return get_success_data(api_client.get_consent(
        consent_id, headers or COORDINATOR))


# ---------------------------------------------------------------------------
# Tier 1/2: composite scenario builders
# ---------------------------------------------------------------------------

def setup_referral_scenario(category_code="FOOD", capacity_total=5,
                            network_overrides=None, offering_overrides=None,
                            client_overrides=None, with_funder=False,
                            rate_card_overrides=None, funder_type="HEALTH_PLAN"):
    """Build the canonical sender -> receiver referral scenario.

    Creates (all orgs ACTIVE): sender S (CLINIC), receiver R (CBO) with one
    offering; an ACTIVE agreement S<->R; a client with an ACTIVE consent for
    (S, R); and a DRAFT referral. When with_funder=True, also creates an ACTIVE
    FUNDER org with an ACTIVE agreement to R and a rate card for the category.

    Returns a dict with ids, rows, and entity-backed headers for each actor.
    """
    set_clock()
    network = create_network(**(network_overrides or {}))
    create_category(code=category_code, name=category_code.title())

    sender = create_org("Sender S", "CLINIC", factories._uniq("EIN-S"))
    receiver = create_org("Receiver R", "CBO", factories._uniq("EIN-R"))

    ctx = {
        "network": network,
        "network_id": network["id"],
        "category_code": category_code,
        "sender": sender,
        "sender_id": sender["id"],
        "receiver": receiver,
        "receiver_id": receiver["id"],
        "case_worker": make_case_worker_headers(sender["id"]),
        "receiver_admin": make_org_admin_headers(receiver["id"]),
        "coordinator": COORDINATOR,
    }

    offering = create_offering(
        receiver["id"], capacity_total=capacity_total,
        category_code=category_code, **(offering_overrides or {}))
    ctx["offering"] = offering
    ctx["offering_id"] = offering["id"]

    agreement = create_and_approve_agreement(sender["id"], receiver["id"])
    ctx["agreement"] = agreement
    ctx["agreement_id"] = agreement["id"]

    client = create_client(sender["id"], **(client_overrides or {}))
    ctx["client"] = client
    ctx["client_id"] = client["id"]

    consent = create_consent(client["id"], sender["id"], receiver["id"])
    ctx["consent"] = consent
    ctx["consent_id"] = consent["id"]

    if with_funder:
        funder = create_org("Funder F", "FUNDER", factories._uniq("EIN-F"),
                            funder_type=funder_type)
        ctx["funder"] = funder
        ctx["funder_id"] = funder["id"]
        ctx["funder_admin"] = make_funder_admin_headers(funder["id"])
        ctx["funder_admin_rev1"] = make_funder_admin_headers(funder["id"], "rev1")
        ctx["funder_admin_rev2"] = make_funder_admin_headers(funder["id"], "rev2")
        rate_card = create_rate_card(funder["id"], **(rate_card_overrides or {}))
        ctx["rate_card"] = rate_card
        ctx["rate_card_id"] = rate_card["id"]
        funder_agreement = create_and_approve_agreement(funder["id"], receiver["id"])
        ctx["funder_agreement"] = funder_agreement
        ctx["funder_agreement_id"] = funder_agreement["id"]

    return ctx


def add_referral(ctx, client_overrides=None):
    """Add a second (or later) DRAFT referral to an existing scenario, with its
    own client and consent. Returns (referral, client, consent)."""
    client = create_client(ctx["sender_id"], **(client_overrides or {}))
    consent = create_consent(client["id"], ctx["sender_id"], ctx["receiver_id"])
    referral = create_referral(ctx["sender_id"], client["id"], ctx["receiver_id"],
                               ctx["offering_id"], consent["id"],
                               ctx["category_code"])
    return referral, client, consent


def route_referral(ctx, referral_id):
    return get_success_data(api_client.route_referral(
        referral_id, make_case_worker_headers(ctx["sender_id"])))


def accept_referral(ctx, referral_id, receiver_id=None):
    return get_success_data(api_client.accept_referral(
        referral_id, make_org_admin_headers(receiver_id or ctx["receiver_id"])))


def decline_referral(ctx, referral_id, receiver_id=None, reason="no fit"):
    return get_success_data(api_client.decline_referral(
        referral_id, {"reason": reason},
        make_org_admin_headers(receiver_id or ctx["receiver_id"])))


def start_service(ctx, referral_id, receiver_id=None):
    return get_success_data(api_client.start_service(
        referral_id, make_org_admin_headers(receiver_id or ctx["receiver_id"])))


def confirm_outcome(ctx, referral_id, outcome_code="DELIVERED", delivered_units=1,
                    receiver_id=None):
    return get_success_data(api_client.confirm_outcome(
        referral_id, {"outcome_code": outcome_code, "delivered_units": delivered_units},
        make_org_admin_headers(receiver_id or ctx["receiver_id"])))


def setup_routed_referral(**scenario_kwargs):
    """Scenario + one ROUTED referral. Returns (ctx, referral)."""
    ctx = setup_referral_scenario(**scenario_kwargs)
    referral = create_referral(ctx["sender_id"], ctx["client_id"],
                               ctx["receiver_id"], ctx["offering_id"],
                               ctx["consent_id"], ctx["category_code"])
    referral = route_referral(ctx, referral["id"])
    ctx["referral"] = referral
    ctx["referral_id"] = referral["id"]
    return ctx, referral


def setup_completed_referral(outcome_code="DELIVERED", delivered_units=1,
                             **scenario_kwargs):
    """Scenario + one referral driven to OUTCOME_RECORDED. Returns (ctx, referral)."""
    scenario_kwargs.setdefault("with_funder", True)
    ctx, referral = setup_routed_referral(**scenario_kwargs)
    accept_referral(ctx, referral["id"])
    start_service(ctx, referral["id"])
    referral = confirm_outcome(ctx, referral["id"], outcome_code, delivered_units)
    ctx["referral"] = referral
    return ctx, referral


# ---------------------------------------------------------------------------
# Tier 3: billing pipeline shortcuts
# ---------------------------------------------------------------------------

def submit_claim(ctx, referral_id, claimed_units):
    """Submit a claim as the receiver's OrgAdmin."""
    return get_success_data(api_client.create_claim(
        factories.create_claim_payload(referral_id=referral_id,
                                       funder_org_id=ctx["funder_id"],
                                       claimed_units=claimed_units),
        make_org_admin_headers(ctx["receiver_id"])))


def review_claim(ctx, claim_id, staff_label="rev1"):
    """Move a claim to UNDER_REVIEW as the funder's reviewer."""
    return get_success_data(api_client.review_claim(
        claim_id, make_funder_admin_headers(ctx["funder_id"], staff_label)))


def approve_claim(ctx, claim_id, staff_label="rev2"):
    """Approve an UNDER_REVIEW claim with a fresh OCC version."""
    claim = get_claim(claim_id, make_funder_admin_headers(ctx["funder_id"]))
    return get_success_data(api_client.approve_claim(
        claim_id, {"expected_claim_version": claim["version"]},
        make_funder_admin_headers(ctx["funder_id"], staff_label)))


def setup_submitted_claim(outcome_code="DELIVERED", delivered_units=1,
                          claimed_units=None, **scenario_kwargs):
    """Completed referral + SUBMITTED claim. Returns (ctx, referral, claim)."""
    ctx, referral = setup_completed_referral(outcome_code, delivered_units,
                                             **scenario_kwargs)
    claim = submit_claim(ctx, referral["id"],
                         claimed_units if claimed_units is not None else delivered_units)
    ctx["claim"] = claim
    ctx["claim_id"] = claim["id"]
    return ctx, referral, claim


def setup_approved_claim(outcome_code="DELIVERED", delivered_units=1,
                         claimed_units=None, **scenario_kwargs):
    """Completed referral + APPROVED claim (reviewer rev1, approver rev2).
    Returns (ctx, referral, claim)."""
    ctx, referral, claim = setup_submitted_claim(
        outcome_code, delivered_units, claimed_units, **scenario_kwargs)
    review_claim(ctx, claim["id"], "rev1")
    claim = approve_claim(ctx, claim["id"], "rev2")
    ctx["claim"] = claim
    return ctx, referral, claim


# ---------------------------------------------------------------------------
# Tier 4: multi-receiver reassignment builders
# ---------------------------------------------------------------------------

def setup_two_receiver_scenario(category_code="FOOD", network_overrides=None):
    """Sender S (CLINIC) plus receivers R1 and R2 (CBO), each with an ACTIVE
    offering, an ACTIVE agreement with S, and a consent from the shared client.

    Returns a dict with ids and rows for both receivers.
    """
    set_clock()
    network = create_network(**(network_overrides or {}))
    create_category(code=category_code, name=category_code.title())

    sender = create_org("Sender S", "CLINIC", factories._uniq("EIN-S"))
    r1 = create_org("Receiver R1", "CBO", factories._uniq("EIN-R1"))
    r2 = create_org("Receiver R2", "CBO", factories._uniq("EIN-R2"))

    o1 = create_offering(r1["id"], category_code=category_code,
                         description="Meals R1")
    o2 = create_offering(r2["id"], category_code=category_code,
                         description="Meals R2")

    agr1 = create_and_approve_agreement(sender["id"], r1["id"])
    agr2 = create_and_approve_agreement(sender["id"], r2["id"])

    client = create_client(sender["id"])
    c1 = create_consent(client["id"], sender["id"], r1["id"])
    c2 = create_consent(client["id"], sender["id"], r2["id"])

    referral = create_referral(sender["id"], client["id"], r1["id"],
                               o1["id"], c1["id"], category_code)

    return {
        "network": network,
        "network_id": network["id"],
        "category_code": category_code,
        "sender": sender,
        "sender_id": sender["id"],
        "case_worker": make_case_worker_headers(sender["id"]),
        "coordinator": COORDINATOR,
        "r1": r1, "r1_id": r1["id"], "r1_admin": make_org_admin_headers(r1["id"]),
        "r2": r2, "r2_id": r2["id"], "r2_admin": make_org_admin_headers(r2["id"]),
        "o1": o1, "o1_id": o1["id"],
        "o2": o2, "o2_id": o2["id"],
        "agr1": agr1, "agr2": agr2,
        "client": client, "client_id": client["id"],
        "c1": c1, "c2": c2,
        "referral": referral, "referral_id": referral["id"],
    }


def reassign_referral(headers, referral_id, new_receiver_org_id,
                      new_service_offering_id, expected_referral_version):
    return api_client.reassign_referral(
        referral_id,
        {"new_receiver_org_id": new_receiver_org_id,
         "new_service_offering_id": new_service_offering_id,
         "expected_referral_version": expected_referral_version},
        headers)


def suspend_org(org_id, reason="audit"):
    """Suspend an org with a fresh OCC version read."""
    org = get_org(org_id)
    return api_client.suspend_organization(
        org_id, {"suspension_reason": reason, "expected_org_version": org["version"]},
        COORDINATOR)
