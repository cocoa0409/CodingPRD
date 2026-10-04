"""Composite setup builders and the pytest fixtures that expose them.

Every builder drives the public API only — there is no direct database access
anywhere in this suite.  Builders use ``get_success_data`` so that a setup
step which the PRD allows to answer 200 or 201 does not have to be pinned to
one of the two at every call site.

Identity threading: ``DistrictManager`` and ``FieldRep`` are entity-backed
roles (PRD section 2.1), so any ownership-gated call in a builder uses
``make_field_rep_headers(rep["id"])`` / ``make_district_manager_headers(...)``
with the actual representative id, never the shared fallback constants.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .constants import CLOCK_DEFAULT_ISO
from .test_users import (
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    QA_HEADERS,
    make_district_manager_headers,
    make_field_rep_headers,
)

# ─── pytest fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def client():
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def api(client):
    """Alias kept so a test can read either name."""
    return client


# ─── Logical clock ────────────────────────────────────────────────────────


def set_clock(client, to_iso8601, headers=None):
    response = client.set_clock(to_iso8601, headers=headers or ADMIN_HEADERS)
    return get_success_data(response)


def reset_clock(client):
    return set_clock(client, CLOCK_DEFAULT_ISO)


# ─── Tier 1: commercial hierarchy ─────────────────────────────────────────


def create_region(client, **overrides):
    return get_success_data(
        client.create_region(f.create_region_payload(**overrides), headers=ADMIN_HEADERS)
    )


def create_territory(client, region_id, **overrides):
    return get_success_data(
        client.create_territory(
            region_id, f.create_territory_payload(**overrides), headers=ADMIN_HEADERS
        )
    )


def create_representative(client, territory_id, **overrides):
    return get_success_data(
        client.create_representative(
            territory_id,
            f.create_representative_payload(**overrides),
            headers=ADMIN_HEADERS,
        )
    )


def create_prescriber(client, **overrides):
    return get_success_data(
        client.create_prescriber(
            f.create_prescriber_payload(**overrides), headers=ADMIN_HEADERS
        )
    )


def verify_prescriber(client, prescriber_id, outcome="PASS"):
    return get_success_data(
        client.verify_prescriber_eligibility(
            prescriber_id, outcome, headers=COMPLIANCE_HEADERS
        )
    )


def create_eligible_prescriber(client, **overrides):
    prescriber = create_prescriber(client, **overrides)
    verify_prescriber(client, prescriber["id"], outcome="PASS")
    return get_success_data(
        client.get_prescriber(prescriber["id"], headers=COMPLIANCE_HEADERS)
    )


def create_product(client, **overrides):
    return get_success_data(
        client.create_product(
            f.create_product_payload(**overrides), headers=ADMIN_HEADERS
        )
    )


def create_sample_lot(client, product_id, **overrides):
    return get_success_data(
        client.create_sample_lot(
            product_id, f.create_sample_lot_payload(**overrides), headers=ADMIN_HEADERS
        )
    )


def issue_lot_to_rep(client, rep_id, lot_id, quantity):
    return get_success_data(
        client.issue_lot_balance(
            rep_id,
            f.issue_lot_balance_payload(lot_id, quantity),
            headers=ADMIN_HEADERS,
        )
    )


# ─── Tier 2: territory + rep composition ──────────────────────────────────


def setup_region_with_territories(client, num_territories=1, **territory_overrides):
    """A region plus N territories.  Returns (region, [territory, ...])."""
    region = create_region(client)
    territories = [
        create_territory(client, region["id"], **territory_overrides)
        for _ in range(num_territories)
    ]
    return region, territories


def setup_two_reps_with_lot(
    client,
    sender_issued=50,
    lot_quantity=500,
    receiver_issued=0,
    **product_overrides,
):
    """Two ACTIVE territories, one sender rep (with issued stock) and one
    receiver rep, one product and one RELEASED lot.

    Returns a dict with region, t_sender, t_receiver, sender, receiver,
    product, lot, sender_balance (and receiver_balance when issued > 0).
    """
    region, (t_sender, t_receiver) = setup_region_with_territories(client, 2)
    sender = create_representative(client, t_sender["id"])
    receiver = create_representative(client, t_receiver["id"])
    product = create_product(client, **product_overrides)
    lot = create_sample_lot(
        client, product["id"], quantity_received=lot_quantity
    )
    sender_balance = issue_lot_to_rep(client, sender["id"], lot["id"], sender_issued)
    result = {
        "region": region,
        "t_sender": t_sender,
        "t_receiver": t_receiver,
        "sender": sender,
        "receiver": receiver,
        "product": product,
        "lot": lot,
        "sender_balance": sender_balance,
        "receiver_balance": None,
    }
    if receiver_issued:
        result["receiver_balance"] = issue_lot_to_rep(
            client, receiver["id"], lot["id"], receiver_issued
        )
    return result


def fresh_lot_version(client, lot_id):
    """Re-read the lot and return its current version (OCC guard helper)."""
    lot = get_success_data(client.get_sample_lot(lot_id, headers=COMPLIANCE_HEADERS))
    return lot["version"]


# ─── Tier 3: planning (target entries, plans, visits) ─────────────────────


def setup_manager_territory(client, budget=200):
    """Region, territory, and a manager rep whose id drives DistrictManager
    calls.  Returns (region, territory, manager)."""
    region = create_region(client)
    territory = create_territory(
        client, region["id"], cycle_sample_budget_units=budget
    )
    manager = create_representative(client, territory["id"])
    return region, territory, manager


def add_target_entry(client, territory_id, prescriber_id, product_id, manager, **overrides):
    return get_success_data(
        client.create_target_list_entry(
            territory_id,
            f.create_target_list_entry_payload(prescriber_id, product_id, **overrides),
            headers=make_district_manager_headers(manager["id"]),
        )
    )


def create_plan(client, territory_id, territory_version, manager, **overrides):
    return get_success_data(
        client.create_call_plan(
            f.create_call_plan_payload(
                territory_id, territory_version, **overrides
            ),
            headers=make_district_manager_headers(manager["id"]),
        )
    )


def publish_plan(client, plan_id, manager):
    return get_success_data(
        client.publish_call_plan(
            plan_id, headers=make_district_manager_headers(manager["id"])
        )
    )


def schedule_visit(client, plan_id, entry_id, rep, **overrides):
    return get_success_data(
        client.create_call_visit(
            f.create_call_visit_payload(plan_id, entry_id, **overrides),
            headers=make_field_rep_headers(rep["id"]),
        )
    )


def complete_visit(client, visit_id, rep):
    return get_success_data(
        client.complete_call_visit(
            visit_id, headers=make_field_rep_headers(rep["id"])
        )
    )


def setup_published_plan_with_rep(
    client,
    tier="B",
    planned_sample_units=20,
    budget=200,
    rep_issue_qty=None,
    lot_quantity=100,
    **product_overrides,
):
    """Full planning spine: region, territory (with budget), manager rep,
    field rep, ELIGIBLE prescriber, product, a target entry, and a PUBLISHED
    call plan.  Optionally issues stock to the rep.

    Returns a dict of every created entity.
    """
    region, territory, manager = setup_manager_territory(client, budget=budget)
    rep = create_representative(client, territory["id"])
    prescriber = create_eligible_prescriber(client)
    product = create_product(client, **product_overrides)
    lot = create_sample_lot(client, product["id"], quantity_received=lot_quantity)
    balance = None
    if rep_issue_qty:
        balance = issue_lot_to_rep(client, rep["id"], lot["id"], rep_issue_qty)
    entry = add_target_entry(
        client,
        territory["id"],
        prescriber["id"],
        product["id"],
        manager,
        tier=tier,
        planned_sample_units=planned_sample_units,
    )
    plan = create_plan(client, territory["id"], territory["version"], manager)
    publish_plan(client, plan["id"], manager)
    plan = get_success_data(
        client.get_call_plan(plan["id"], headers=make_district_manager_headers(manager["id"]))
    )
    return {
        "region": region,
        "territory": territory,
        "manager": manager,
        "rep": rep,
        "prescriber": prescriber,
        "product": product,
        "lot": lot,
        "balance": balance,
        "entry": entry,
        "plan": plan,
    }


def setup_completed_visit_with_disbursement(
    client,
    disbursement_qty=4,
    rep_issue_qty=20,
    planned_sample_units=40,
    tier="B",
    lot_quantity=100,
    **product_overrides,
):
    """Published plan + one COMPLETED visit + one PENDING_SIGNATURE
    disbursement.  Returns the context dict plus ``visit`` and
    ``disbursement`` keys."""
    ctx = setup_published_plan_with_rep(
        client,
        tier=tier,
        planned_sample_units=planned_sample_units,
        rep_issue_qty=rep_issue_qty,
        lot_quantity=lot_quantity,
        **product_overrides,
    )
    visit = schedule_visit(client, ctx["plan"]["id"], ctx["entry"]["id"], ctx["rep"])
    complete_visit(client, visit["id"], ctx["rep"])
    visit = get_success_data(
        client.get_call_visit(
            visit["id"], headers=make_field_rep_headers(ctx["rep"]["id"])
        )
    )
    disbursement = get_success_data(
        client.create_sample_disbursement(
            f.create_sample_disbursement_payload(
                visit["id"], ctx["lot"]["id"], disbursement_qty
            ),
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
    )
    ctx["visit"] = visit
    ctx["disbursement"] = disbursement
    return ctx


def sign_disbursement(client, disbursement_id, rep, payload=None):
    return get_success_data(
        client.capture_signature(
            disbursement_id,
            payload or "A" * 40,
            headers=make_field_rep_headers(rep["id"]),
        )
    )


# ─── Tier 4: transfers ────────────────────────────────────────────────────


def request_transfer(client, sender, receiver, lot, quantity, **overrides):
    """Create a REQUESTED transfer with a fresh OCC version for the lot."""
    lot_version = fresh_lot_version(client, lot["id"])
    return get_success_data(
        client.create_sample_transfer(
            f.create_sample_transfer_payload(
                receiver["id"],
                lot["id"],
                quantity,
                lot_version,
                **overrides,
            ),
            headers=make_field_rep_headers(sender["id"]),
        )
    )


def setup_accepted_transfer(client, quantity=10, sender_issued=40, **kwargs):
    """Two reps, sender holds stock, transfer REQUESTED then ACCEPTED.
    Returns the two-rep context plus the ``transfer`` key."""
    ctx = setup_two_reps_with_lot(client, sender_issued=sender_issued, **kwargs)
    transfer = request_transfer(
        client, ctx["sender"], ctx["receiver"], ctx["lot"], quantity
    )
    get_success_data(
        client.accept_transfer(
            transfer["id"], headers=make_field_rep_headers(ctx["receiver"]["id"])
        )
    )
    ctx["transfer"] = get_success_data(
        client.get_sample_transfer(transfer["id"], headers=COMPLIANCE_HEADERS)
    )
    return ctx


# ─── Tier 5: count sessions ───────────────────────────────────────────────


def setup_count_session_cast(client, custodian_issue_qty=0, lot_quantity=100, **product_overrides):
    """Custodian (with manager M), independent counter in another territory,
    and optionally stock issued to the custodian.

    Returns dict with region, t_custodian, t_counter, manager, custodian,
    counter, product, lot, balance.
    """
    region, (t_custodian, t_counter) = setup_region_with_territories(client, 2)
    manager = create_representative(client, t_custodian["id"])
    custodian = create_representative(
        client, t_custodian["id"], manager_rep_id=manager["id"]
    )
    counter = create_representative(client, t_counter["id"])
    product = create_product(client, **product_overrides)
    lot = create_sample_lot(client, product["id"], quantity_received=lot_quantity)
    balance = None
    if custodian_issue_qty:
        balance = issue_lot_to_rep(
            client, custodian["id"], lot["id"], custodian_issue_qty
        )
    return {
        "region": region,
        "t_custodian": t_custodian,
        "t_counter": t_counter,
        "manager": manager,
        "custodian": custodian,
        "counter": counter,
        "product": product,
        "lot": lot,
        "balance": balance,
    }


def open_count_session(client, custodian, counter, manager, **overrides):
    return get_success_data(
        client.create_count_session(
            f.create_count_session_payload(
                custodian["id"], counter["id"], **overrides
            ),
            headers=make_district_manager_headers(manager["id"]),
        )
    )


def submit_full_count(client, session_id, counter, counted_by_lot):
    """Submit a count covering every lot the session auto-created lines for."""
    lines = [
        {"lot_id": lot_id, "counted_qty": qty}
        for lot_id, qty in counted_by_lot.items()
    ]
    return get_success_data(
        client.submit_count(
            session_id, lines, headers=make_field_rep_headers(counter["id"])
        )
    )


def reconcile_session(client, session_id, manager):
    return get_success_data(
        client.reconcile_count_session(
            session_id, headers=make_district_manager_headers(manager["id"])
        )
    )


def setup_reconciled_session(
    client,
    custodian_issue_qty=20,
    counted_qty=20,
    window_start="2026-09-05T00:00:00Z",
    window_end="2026-09-06T00:00:00Z",
    **product_overrides,
):
    """A count session walked to RECONCILED.  Returns the cast context plus
    ``session``."""
    ctx = setup_count_session_cast(
        client, custodian_issue_qty=custodian_issue_qty, **product_overrides
    )
    session = open_count_session(
        client,
        ctx["custodian"],
        ctx["counter"],
        ctx["manager"],
        window_start=window_start,
        window_end=window_end,
    )
    counted = {ctx["lot"]["id"]: counted_qty} if custodian_issue_qty else {}
    if counted:
        submit_full_count(client, session["id"], ctx["counter"], counted)
    reconcile_session(client, session["id"], ctx["manager"])
    ctx["session"] = get_success_data(
        client.get_count_session(session["id"], headers=COMPLIANCE_HEADERS)
    )
    return ctx


# ─── Tier 6: excursions and returns ───────────────────────────────────────


def report_excursion(client, rep, product_id, **overrides):
    return get_success_data(
        client.create_temperature_excursion(
            f.create_temperature_excursion_payload(product_id, **overrides),
            headers=make_field_rep_headers(rep["id"]),
        )
    )


def assess_excursion(client, excursion_id):
    return get_success_data(
        client.assess_temperature_excursion(excursion_id, headers=QA_HEADERS)
    )


def create_draft_return(client, rep, lot_id, quantity, **overrides):
    return get_success_data(
        client.create_sample_return(
            f.create_sample_return_payload(lot_id, quantity, **overrides),
            headers=make_field_rep_headers(rep["id"]),
        )
    )


def submit_return(client, return_id, rep):
    return get_success_data(
        client.submit_sample_return(
            return_id, headers=make_field_rep_headers(rep["id"])
        )
    )


def setup_submitted_return(client, quantity=2, rep_issue_qty=10, **overrides):
    """Rep with issued stock and one SUBMITTED DAMAGED return.
    Returns the two-rep context (sender is the returning rep) plus
    ``return``."""
    ctx = setup_two_reps_with_lot(client, sender_issued=rep_issue_qty)
    ret = create_draft_return(
        client, ctx["sender"], ctx["lot"]["id"], quantity, **overrides
    )
    submit_return(client, ret["id"], ctx["sender"])
    ctx["return"] = get_success_data(
        client.get_sample_return(ret["id"], headers=COMPLIANCE_HEADERS)
    )
    return ctx
