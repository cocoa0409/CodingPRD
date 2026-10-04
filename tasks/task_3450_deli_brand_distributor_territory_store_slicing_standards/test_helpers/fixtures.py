"""Composite setup helpers — multi-step preconditions built from PRD-declared
endpoints only.

Identity threading: after creating an entity-backed resource, every
ownership-gated call uses make_<role>_headers(entity["id"]) — never the
shared TEST_USERS fallback (PRD §2.1).

All helpers use get_success_data() so a setup failure surfaces as a clear
"Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_DELIVERY_WEEK,
    TRAINING_MIN_CERTS,
)
from .factories import (
    create_account_payload,
    create_authorization_payload,
    create_certification_payload,
    create_delivery_payload,
    create_distributor_payload,
    create_grant_payload,
    create_incident_payload,
    create_opened_log_payload,
    create_order_payload,
    create_plant_payload,
    create_production_run_payload,
    create_product_payload,
    create_promo_program_payload,
    create_service_visit_payload,
    create_slicer_payload,
    create_submit_visit_payload,
    create_territory_payload,
    delivery_line,
    order_line_request,
)
from .test_users import (
    TEST_USERS,
    make_distributor_rep_headers,
    make_plant_scheduler_headers,
    make_retail_manager_headers,
)

ADMIN = TEST_USERS["brand_admin_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


# ---------------- logical clock ----------------

def set_clock(to_iso8601):
    """BrandAdmin-only logical clock set (PRD §2.5, unprefixed endpoint)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup step failed setting clock: {resp.text}"
    return resp


# ---------------- network: distributors, territories, accounts ----------------

def create_distributor(**overrides):
    return get_success_data(api_client.create_distributor(create_distributor_payload(**overrides), ADMIN))


def create_territory(**overrides):
    return get_success_data(api_client.create_territory(create_territory_payload(**overrides), ADMIN))


def grant_territory(territory, distributor_id):
    """Grant using the territory's CURRENT version (OCC, PRD §2.6). Also flips
    a PROSPECT distributor to ACTIVE (PRD §3.1). Returns the granted territory."""
    return get_success_data(api_client.grant_territory(
        territory["id"],
        create_grant_payload(distributor_id, territory["version"]),
        ADMIN,
    ))


def setup_active_distributor(tier=None, **distributor_overrides):
    """Distributor + territory + grant -> distributor ACTIVE.

    Returns {"distributor": ..., "territory": ...} (territory post-grant).
    """
    if tier is not None:
        distributor_overrides["service_level_tier"] = tier
    distributor = create_distributor(**distributor_overrides)
    territory = create_territory()
    territory = grant_territory(territory, distributor["id"])
    distributor = get_success_data(api_client.get_distributor(distributor["id"], ADMIN))
    return {"distributor": distributor, "territory": territory}


def create_product(**overrides):
    return get_success_data(api_client.create_product(create_product_payload(**overrides), ADMIN))


def propose_account(distributor, territory, **overrides):
    """DistributorRep proposes an account in a territory it holds."""
    return get_success_data(api_client.create_account(
        create_account_payload(territory["id"], **overrides),
        make_distributor_rep_headers(distributor["id"]),
    ))


def review_account(account_id, decision="APPROVE"):
    return get_success_data(api_client.review_account(account_id, decision, ADMIN))


def approve_account(account_id):
    return review_account(account_id, "APPROVE")


def setup_approved_account(channel="INDEPENDENT_GROCER", **distributor_overrides):
    """ACTIVE distributor holding a territory + one APPROVED account in it.

    Returns {"distributor", "territory", "account"}.
    """
    net = setup_active_distributor(**distributor_overrides)
    account = propose_account(net["distributor"], net["territory"], channel=channel)
    account = approve_account(account["id"])
    return {**net, "account": account}


def create_authorization(account_id, product_id):
    """AUTHORIZED at once when the account is APPROVED, else REQUESTED (PRD §3.2)."""
    return get_success_data(api_client.create_authorization(
        create_authorization_payload(account_id, product_id), ADMIN,
    ))


# ---------------- supply: plants, runs, lots ----------------

def create_plant(**overrides):
    return get_success_data(api_client.create_plant(create_plant_payload(**overrides), ADMIN))


def create_production_run(plant, product, **overrides):
    return get_success_data(api_client.create_production_run(
        create_production_run_payload(plant["id"], product["id"], **overrides),
        make_plant_scheduler_headers(plant["id"]),
    ))


def complete_run(run, plant, actual_units, waste_units=0):
    return get_success_data(api_client.complete_production_run(
        run["id"], actual_units, waste_units,
        make_plant_scheduler_headers(plant["id"]),
    ))


def get_lot_for_run(run_id, headers=None):
    """Fetch the lot created by a completed run (exactly one per run, PRD §3.4)."""
    data = get_success_data(api_client.list_lots(headers or ADMIN, params={"production_run_id": run_id}))
    assert isinstance(data, list) and len(data) == 1, f"expected exactly one lot for run {run_id}"
    return data[0]


def setup_lot(product, actual_units=10, waste_units=0, plant=None, **run_overrides):
    """Plant + SCHEDULED run + completion -> one AVAILABLE lot.

    Returns {"plant", "run", "lot"} (run is post-completion).
    """
    plant = plant or create_plant()
    run_overrides.setdefault("capacity_units", max(100, actual_units + waste_units))
    run_overrides.setdefault("planned_units", actual_units + waste_units)
    run = create_production_run(plant, product, **run_overrides)
    run = complete_run(run, plant, actual_units, waste_units)
    lot = get_lot_for_run(run["id"])
    return {"plant": plant, "run": run, "lot": lot}


# ---------------- ordering ----------------

def create_order(distributor, lines, delivery_week=DEFAULT_DELIVERY_WEEK):
    """lines: list of (product_id, qty) tuples or order-line dicts."""
    norm = [
        ln if isinstance(ln, dict) else order_line_request(ln[0], ln[1])
        for ln in lines
    ]
    return get_success_data(api_client.create_order(
        create_order_payload(norm, delivery_week=delivery_week),
        make_distributor_rep_headers(distributor["id"]),
    ))


def allocate_week(plant, delivery_week=DEFAULT_DELIVERY_WEEK):
    return get_success_data(api_client.allocate_week(
        delivery_week, make_plant_scheduler_headers(plant["id"]),
    ))


def get_order(order_id, headers=None):
    return get_success_data(api_client.get_order(order_id, headers or ADMIN))


def setup_allocated_order(distributor, product, qty_requested=10, supply_units=None,
                          delivery_week=DEFAULT_DELIVERY_WEEK, plant=None):
    """Supply + order + allocate-week -> order with units allocated.

    Returns {"plant", "run", "lot", "order"} (order re-read after allocation).
    """
    supply = setup_lot(product, actual_units=supply_units or qty_requested, plant=plant)
    order = create_order(distributor, [(product["id"], qty_requested)], delivery_week)
    allocate_week(supply["plant"], delivery_week)
    order = get_order(order["id"])
    lot = get_lot_for_run(supply["run"]["id"])
    return {"plant": supply["plant"], "run": supply["run"], "lot": lot, "order": order}


# ---------------- training ----------------

def create_certification(account_id, distributor, associate_name="Associate",
                         slicing_module_passed=True, allergen_module_passed=True):
    return get_success_data(api_client.create_training_certification(
        create_certification_payload(
            account_id, associate_name,
            slicing_module_passed=slicing_module_passed,
            allergen_module_passed=allergen_module_passed,
        ),
        make_distributor_rep_headers(distributor["id"]),
    ))


def make_compliant_certs(account, distributor, count=TRAINING_MIN_CERTS):
    """Create `count` dual-module ACTIVE certifications -> account compliant (PRD §3.6)."""
    return [
        create_certification(account["id"], distributor, associate_name=f"Assoc {i + 1}")
        for i in range(count)
    ]


# ---------------- deliveries ----------------

def setup_delivery_chain(qty=10, product_overrides=None, with_authorization=True,
                         with_certs=True, supply_units=None,
                         shelf_life_unopened_days=None):
    """Full happy-path chain: ACTIVE distributor + APPROVED account + product
    (+ authorization) (+ 2 dual-module certs) + lot + ALLOCATED order.

    Returns {"distributor", "territory", "account", "product",
             "authorization"?, "certs"?, "plant", "run", "lot", "order"}.
    """
    overrides = dict(product_overrides or {})
    if shelf_life_unopened_days is not None:
        overrides["shelf_life_unopened_days"] = shelf_life_unopened_days
    ctx = setup_approved_account()
    product = create_product(**overrides)
    ctx["product"] = product
    if with_authorization:
        ctx["authorization"] = create_authorization(ctx["account"]["id"], product["id"])
    if with_certs:
        ctx["certs"] = make_compliant_certs(ctx["account"], ctx["distributor"])
    alloc = setup_allocated_order(ctx["distributor"], product, qty_requested=qty,
                                  supply_units=supply_units)
    ctx.update(alloc)
    return ctx


def create_delivery(chain, qty=None, lot=None):
    """Ship `qty` units (default: the order's allocated qty on the lot)."""
    order = chain["order"]
    lot = lot or chain["lot"]
    if qty is None:
        lines = get_success_data(api_client.list_order_lines(
            ADMIN, params={"order_id": order["id"]}))
        line = next(ln for ln in lines if ln["product_id"] == lot["product_id"])
        qty = line["qty_allocated"]
    return get_success_data(api_client.create_delivery(
        create_delivery_payload(order["id"], chain["account"]["id"], [delivery_line(lot["id"], qty)]),
        make_distributor_rep_headers(chain["distributor"]["id"]),
    ))


def confirm_delivery(delivery, account):
    return get_success_data(api_client.confirm_delivery(
        delivery["id"], make_retail_manager_headers(account["id"])))


def reject_delivery(delivery, account):
    return get_success_data(api_client.reject_delivery(
        delivery["id"], make_retail_manager_headers(account["id"])))


def setup_confirmed_delivery(**chain_kwargs):
    """Full chain through DELIVERED. Returns chain dict plus "delivery"."""
    chain = setup_delivery_chain(**chain_kwargs)
    chain["delivery"] = create_delivery(chain)
    chain["delivery"] = confirm_delivery(chain["delivery"], chain["account"])
    return chain


# ---------------- service visits & slicers ----------------

def create_visit(account, distributor, window_start, window_end):
    return get_success_data(api_client.create_service_visit(
        create_service_visit_payload(account["id"], window_start=window_start, window_end=window_end),
        make_distributor_rep_headers(distributor["id"]),
    ))


def submit_visit(visit, distributor, score=90, rotation_compliant=True,
                 slicer_presentation_ok=True, cleaned_slicer_ids=None):
    return get_success_data(api_client.submit_service_visit(
        visit["id"],
        create_submit_visit_payload(score, rotation_compliant, slicer_presentation_ok,
                                    cleaned_slicer_ids=cleaned_slicer_ids),
        make_distributor_rep_headers(distributor["id"]),
    ))


def review_visit(visit, verdict="VERIFY"):
    return get_success_data(api_client.review_service_visit(visit["id"], verdict, SAFETY))


def create_slicer(account, **overrides):
    return get_success_data(api_client.create_slicer(
        create_slicer_payload(account["id"], **overrides),
        make_retail_manager_headers(account["id"]),
    ))


# ---------------- opened product logs / freshness ----------------

def create_opened_log(account, product, slicer, opened_at=None):
    return get_success_data(api_client.create_opened_product_log(
        create_opened_log_payload(product["id"], slicer["id"], opened_at=opened_at),
        make_retail_manager_headers(account["id"]),
    ))


def pull_log(log, account):
    return get_success_data(api_client.pull_opened_product_log(
        log["id"], make_retail_manager_headers(account["id"])))


def record_late_pull(account, product, slicer, opened_at, pull_at):
    """Open a log at `opened_at`, move the clock to `pull_at` (past the pull
    deadline), and pull — recording one PULLED_LATE. Returns the pulled log."""
    log = create_opened_log(account, product, slicer, opened_at=opened_at)
    set_clock(pull_at)
    return pull_log(log, account)


# ---------------- promo programs ----------------

def create_promo_program(account, distributor, product, **overrides):
    return get_success_data(api_client.create_promo_program(
        create_promo_program_payload(account["id"], product["id"], **overrides),
        make_distributor_rep_headers(distributor["id"]),
    ))


def authorize_promo(program_id, decision="APPROVE"):
    return get_success_data(api_client.authorize_promo_program(program_id, decision, ADMIN))


def settle_promo(program_id, redemption_lines):
    return get_success_data(api_client.settle_promo_program(program_id, redemption_lines, ADMIN))


def setup_draft_promo(**program_overrides):
    """APPROVED account + product + DRAFT program.

    Returns {"distributor", "territory", "account", "product", "program"}.
    """
    ctx = setup_approved_account()
    ctx["product"] = create_product(base_price_cents=1000)
    ctx["program"] = create_promo_program(
        ctx["account"], ctx["distributor"], ctx["product"], **program_overrides)
    return ctx


def setup_authorized_promo(**program_overrides):
    """setup_draft_promo + APPROVE -> AUTHORIZED program with reserve locked."""
    ctx = setup_draft_promo(**program_overrides)
    ctx["program"] = authorize_promo(ctx["program"]["id"], "APPROVE")
    return ctx


# ---------------- incidents ----------------

def create_incident(plant, affected_run_ids=None, title="Test incident", severity="HIGH"):
    return get_success_data(api_client.create_incident(
        create_incident_payload(plant["id"], title=title, severity=severity,
                                affected_run_ids=affected_run_ids or []),
        SAFETY,
    ))


def transition_incident(incident_id, to, resolution_outcome=None):
    return get_success_data(api_client.transition_incident(
        incident_id, to, SAFETY, resolution_outcome=resolution_outcome))


def create_triaged_incident(plant, affected_run_ids=None, **kwargs):
    incident = create_incident(plant, affected_run_ids=affected_run_ids, **kwargs)
    return transition_incident(incident["id"], "TRIAGED")


def confirm_recall(incident):
    """TRIAGED -> CONFIRMED_RECALL: plant SHUTDOWN + quarantine cascade (PRD §3.8)."""
    return transition_incident(incident["id"], "CONFIRMED_RECALL")


# ---------------- the deep composite: performance scoring (PRD §3.9) ----------------

def setup_performance_score_scenario():
    """Distributor with a controlled 90-day activity footprint:

    - visits: 80 VERIFIED, 100 VERIFIED, 40 SUBMITTED (unverified)
    - pulls: 3 on time, 1 late  (on_time_pull_pct 75)
    - order: 20 requested, 18 allocated -> PARTIAL (fill_pct 90)

    Ends with the clock at 2026-09-05T00:00:00Z. Expected scores:
    provisional = mean(80,100,40) = 73.33; final = 0.5*90 + 0.3*75 + 0.2*90 = 85.5.
    Returns a dict with every entity created.
    """
    ctx = setup_approved_account()
    product = create_product(code="HAM", name="Ham", base_price_cents=5000,
                             shelf_life_opened_hours=72, shelf_life_unopened_days=30)
    ctx["product"] = product
    supply = setup_lot(product, actual_units=18, waste_units=0)
    ctx.update(supply)
    order = create_order(ctx["distributor"], [(product["id"], 20)])
    allocate_week(supply["plant"])
    ctx["order"] = get_order(order["id"])

    rep = make_distributor_rep_headers(ctx["distributor"]["id"])
    visits = []
    for start, end in (
        ("2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z"),
        ("2026-09-02T10:30:00Z", "2026-09-02T11:30:00Z"),
        ("2026-09-02T12:00:00Z", "2026-09-02T13:00:00Z"),
    ):
        visits.append(create_visit(ctx["account"], ctx["distributor"], start, end))
    submit_visit(visits[0], ctx["distributor"], score=80)
    submit_visit(visits[1], ctx["distributor"], score=100)
    submit_visit(visits[2], ctx["distributor"], score=40)
    visits[0] = review_visit(visits[0], "VERIFY")
    visits[1] = review_visit(visits[1], "VERIFY")
    visits[2] = get_success_data(api_client.get_service_visit(visits[2]["id"], rep))
    ctx["visits"] = visits

    slicer = create_slicer(ctx["account"], label="S1")
    ctx["slicer"] = slicer
    logs = [
        create_opened_log(ctx["account"], product, slicer, opened_at="2026-09-01T00:00:00Z")
        for _ in range(4)
    ]
    set_clock("2026-09-02T00:00:00Z")  # inside the 72h deadline -> on time
    for log in logs[:3]:
        pull_log(log, ctx["account"])
    set_clock("2026-09-05T00:00:00Z")  # past the deadline -> late
    logs[3] = pull_log(logs[3], ctx["account"])
    ctx["logs"] = logs
    return ctx
