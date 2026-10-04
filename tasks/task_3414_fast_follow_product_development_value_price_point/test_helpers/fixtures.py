"""Composite setup helpers.

Every fixture builds preconditions from scratch against a fresh server using
only PRD-declared endpoints, and returns validated response data (setup
failures surface as clear "Setup step failed" errors via get_success_data).

Identity threading: quote submission/withdrawal and formula-sample
submission are ownership-gated on the ManufacturerRep's X-User-ID equalling
the ContractManufacturer id, so those calls always use
make_manufacturer_rep_headers(cm_id) — never a shared constant.

OCC threading: create_quote / create_slot re-read the parent's live version
when the caller does not pin expected_product_version /
expected_line_review_version, which is exactly the "version as last
observed" a well-behaved client supplies.

Clock discipline: every composite starts by setting the logical clock to
2026-09-01T00:00:00Z and only ever advances it; window/occupancy instants
used by the retail-side helpers are derived from the review's own fields so
custom windows stay consistent.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_START
from .factories import (
    create_compliance_dossier_payload,
    create_concept_payload,
    create_cost_quote_payload,
    create_discontinuation_review_payload,
    create_dossier_review_payload,
    create_formula_project_payload,
    create_launch_plan_payload,
    create_line_review_payload,
    create_manufacturer_payload,
    create_planogram_slot_payload,
    create_product_payload,
    create_retail_partner_payload,
    create_sample_distribution_payload,
    create_trend_signal_payload,
)
from .test_users import (
    PRODUCT_MANAGER_USER_ID,
    RETAIL_PLANNER_USER_ID,
    TEST_USERS,
    make_manufacturer_rep_headers,
    make_product_manager_headers,
    make_retail_planner_headers,
)

__all__ = [
    # clock + reads
    "set_clock",
    "read_concept",
    "read_product",
    "read_manufacturer",
    "read_formula_project",
    "read_cost_quote",
    "read_dossier",
    "read_partner",
    "read_line_review",
    "read_planogram_slot",
    "read_launch_plan",
    "read_discontinuation_review",
    # granular: trends / concepts
    "create_trend",
    "transition_trend",
    "create_selected_trend",
    "create_concept",
    "transition_concept",
    "create_selected_concept",
    # granular: manufacturers
    "create_manufacturer",
    "transition_manufacturer",
    "set_manufacturer_capacity",
    # granular: products
    "create_product",
    "transition_product",
    "set_packaging_ready",
    # granular: formula projects
    "create_formula_project",
    "submit_formula_sample",
    "approve_formula",
    "reject_formula_sample",
    "abandon_formula",
    "create_approved_formula",
    # granular: cost quotes
    "create_quote",
    "evaluate_quote",
    "accept_quote",
    "create_accepted_quote",
    "reject_quote",
    "withdraw_quote",
    "settle_quote",
    # granular: compliance dossiers
    "open_dossier",
    "submit_dossier_review",
    "certify_dossier",
    "make_dossier_compliant",
    # granular: retail partners / line reviews / slots
    "create_partner",
    "update_partner_capacities",
    "create_line_review",
    "transition_line_review",
    "open_line_review",
    "advance_line_review_to_reviewing",
    "advance_line_review_to_decided",
    "create_slot",
    "commit_slot",
    "withdraw_slot",
    # granular: launch plans / sampling
    "create_launch_plan",
    "lock_plan",
    "approve_plan",
    "execute_plan",
    "set_sampling_status",
    "set_sample_budget",
    "record_sample_event",
    # granular: discontinuation
    "propose_discontinuation",
    "approve_discontinuation",
    "reject_discontinuation",
    # composites (each returns a ctx dict of created entities)
    "setup_product_with_approved_formula",
    "setup_sourcing_product",
    "setup_accepted_quote_product",
    "setup_compliance_gate_product",
    "setup_compliant_gate_product",
    "setup_launch_ready_product",
    "setup_open_review_with_slot",
    "setup_draft_plan",
    "setup_decided_review_with_slot",
    "setup_committed_slot_scenario",
    "setup_locked_plan",
    "setup_approved_plan",
    "setup_executed_plan",
    "setup_executed_plan_with_sampling",
]

_ADMIN = TEST_USERS["platform_admin_headers"]
_SCOUT = TEST_USERS["trend_scout_headers"]
_PM = TEST_USERS["product_manager_headers"]
_SOURCING = TEST_USERS["sourcing_lead_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]
_PLANNER = TEST_USERS["retail_planner_headers"]
_MARKETING = TEST_USERS["marketing_lead_headers"]


# ---------------------------------------------------------------------------
# Clock and read-through helpers
# ---------------------------------------------------------------------------

def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_clock(now: str = LOGICAL_CLOCK_START) -> dict:
    """Advance the server's logical clock (PlatformAdmin only)."""
    return get_success_data(api_client.set_clock(now, headers=_ADMIN))


def read_concept(concept_id: str) -> dict:
    return get_success_data(api_client.get_concept(concept_id, headers=_ADMIN))


def read_product(product_id: str) -> dict:
    return get_success_data(api_client.get_product(product_id, headers=_ADMIN))


def read_manufacturer(manufacturer_id: str) -> dict:
    return get_success_data(api_client.get_manufacturer(manufacturer_id, headers=_ADMIN))


def read_formula_project(project_id: str) -> dict:
    return get_success_data(api_client.get_formula_project(project_id, headers=_ADMIN))


def read_cost_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_cost_quote(quote_id, headers=_ADMIN))


def read_dossier(dossier_id: str) -> dict:
    return get_success_data(api_client.get_compliance_dossier(dossier_id, headers=_ADMIN))


def read_partner(partner_id: str) -> dict:
    return get_success_data(api_client.get_retail_partner(partner_id, headers=_ADMIN))


def read_line_review(review_id: str) -> dict:
    return get_success_data(api_client.get_line_review(review_id, headers=_ADMIN))


def read_planogram_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_planogram_slot(slot_id, headers=_ADMIN))


def read_launch_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_launch_plan(plan_id, headers=_ADMIN))


def read_discontinuation_review(review_id: str) -> dict:
    return get_success_data(api_client.get_discontinuation_review(review_id, headers=_ADMIN))


# ---------------------------------------------------------------------------
# Trends and concepts (TrendScout)
# ---------------------------------------------------------------------------

def create_trend(**overrides) -> dict:
    """Register a trend signal (starts DISCOVERED, momentum_score null)."""
    return get_success_data(
        api_client.create_trend_signal(create_trend_signal_payload(**overrides), headers=_SCOUT)
    )


def transition_trend(trend_id: str, status: str) -> dict:
    return get_success_data(
        api_client.patch_trend_signal(trend_id, {"status": status}, headers=_SCOUT)
    )


def create_selected_trend(**overrides) -> dict:
    """Trend walked DISCOVERED -> EVALUATING (score computed) -> SELECTED.
    Default inputs score exactly 70.0, the inclusive selection threshold."""
    trend = create_trend(**overrides)
    transition_trend(trend["id"], "EVALUATING")
    return transition_trend(trend["id"], "SELECTED")


def create_concept(trend_id: str, **overrides) -> dict:
    """Pitch a concept against a SELECTED trend (starts PITCHED)."""
    return get_success_data(
        api_client.create_concept(
            create_concept_payload(trend_signal_id=trend_id, **overrides), headers=_SCOUT
        )
    )


def transition_concept(concept_id: str, status: str) -> dict:
    return get_success_data(
        api_client.patch_concept(concept_id, {"status": status}, headers=_SCOUT)
    )


def create_selected_concept(trend_id: str, **overrides) -> dict:
    """Concept walked to SELECTED; target_unit_cost_cents computed from the
    fixed price point (floor): 300->84, 600->168, 1000->260, 1500->360,
    2000->440."""
    concept = create_concept(trend_id, **overrides)
    return transition_concept(concept["id"], "SELECTED")


# ---------------------------------------------------------------------------
# Contract manufacturers (SourcingLead)
# ---------------------------------------------------------------------------

def create_manufacturer(**overrides) -> dict:
    """Onboard a contract manufacturer (starts ACTIVE). Default: MOQ 500,
    4 production slots per quarter, STANDARD tier, EYES+LIPS capabilities."""
    return get_success_data(
        api_client.create_manufacturer(create_manufacturer_payload(**overrides), headers=_SOURCING)
    )


def transition_manufacturer(manufacturer_id: str, status: str) -> dict:
    """Suspend (ACTIVE -> SUSPENDED) or reactivate (SUSPENDED -> ACTIVE)."""
    return get_success_data(
        api_client.patch_manufacturer(manufacturer_id, {"status": status}, headers=_SOURCING)
    )


def set_manufacturer_capacity(manufacturer_id: str, capacity_slots_per_quarter: int) -> dict:
    return get_success_data(
        api_client.patch_manufacturer(
            manufacturer_id,
            {"capacity_slots_per_quarter": capacity_slots_per_quarter},
            headers=_SOURCING,
        )
    )


# ---------------------------------------------------------------------------
# Products (ProductManager)
# ---------------------------------------------------------------------------

def create_product(concept_id: str, **overrides) -> dict:
    """Commercialize a SELECTED concept (starts FORMULATION, PACK_SOURCING;
    concept moves to IN_DEVELOPMENT)."""
    return get_success_data(
        api_client.create_product(
            create_product_payload(concept_id=concept_id, **overrides), headers=_PM
        )
    )


def transition_product(product_id: str, status: str) -> dict:
    return get_success_data(
        api_client.patch_product(product_id, {"status": status}, headers=_PM)
    )


def set_packaging_ready(product_id: str) -> dict:
    """Move the parallel packaging dimension PACK_SOURCING -> PACK_READY."""
    return get_success_data(
        api_client.patch_product(product_id, {"packaging_status": "PACK_READY"}, headers=_PM)
    )


# ---------------------------------------------------------------------------
# Formula projects (SourcingLead; sample submission also ManufacturerRep)
# ---------------------------------------------------------------------------

def create_formula_project(product_id: str, manufacturer_id: str, **overrides) -> dict:
    """Open a formula project (starts IN_DEVELOPMENT, round_count 1,
    due_at = created_at + 6 weeks)."""
    return get_success_data(
        api_client.create_formula_project(
            create_formula_project_payload(
                product_id=product_id, contract_manufacturer_id=manufacturer_id, **overrides
            ),
            headers=_SOURCING,
        )
    )


def submit_formula_sample(project_id: str, manufacturer_id: str) -> dict:
    """IN_DEVELOPMENT -> SAMPLE_REVIEW as the owning ManufacturerRep
    (X-User-ID == contract_manufacturer_id). Stamps submitted_at, computes
    is_late."""
    return get_success_data(
        api_client.patch_formula_project(
            project_id,
            {"status": "SAMPLE_REVIEW"},
            headers=make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def approve_formula(project_id: str) -> dict:
    """SAMPLE_REVIEW -> APPROVED (SourcingLead); formula_version := round_count."""
    return get_success_data(
        api_client.patch_formula_project(project_id, {"status": "APPROVED"}, headers=_SOURCING)
    )


def reject_formula_sample(project_id: str) -> dict:
    """SAMPLE_REVIEW -> IN_DEVELOPMENT (SourcingLead); round_count += 1.
    At round 3 (the maximum) the project auto-transitions to ABANDONED."""
    return get_success_data(
        api_client.patch_formula_project(
            project_id, {"status": "IN_DEVELOPMENT"}, headers=_SOURCING
        )
    )


def abandon_formula(project_id: str) -> dict:
    """IN_DEVELOPMENT -> ABANDONED (SourcingLead)."""
    return get_success_data(
        api_client.patch_formula_project(project_id, {"status": "ABANDONED"}, headers=_SOURCING)
    )


def create_approved_formula(product_id: str, manufacturer_id: str, **overrides) -> dict:
    """Create + submit (owning rep) + approve. Returns the APPROVED project."""
    project = create_formula_project(product_id, manufacturer_id, **overrides)
    submit_formula_sample(project["id"], manufacturer_id)
    return approve_formula(project["id"])


# ---------------------------------------------------------------------------
# Cost quotes (ManufacturerRep submits; SourcingLead evaluates/accepts)
# ---------------------------------------------------------------------------

def create_quote(product_id: str, manufacturer_id: str, *, expected_product_version=None, **overrides) -> dict:
    """Submit a quote as the owning ManufacturerRep. Computes
    landed_provisional_cents (default terms yield 234) and bumps the
    product's version by one. When expected_product_version is not given,
    the product's live version is read first (the version the client last
    observed)."""
    if expected_product_version is None:
        expected_product_version = read_product(product_id)["version"]
    payload = create_cost_quote_payload(
        product_id=product_id,
        contract_manufacturer_id=manufacturer_id,
        expected_product_version=expected_product_version,
        **overrides,
    )
    return get_success_data(
        api_client.create_cost_quote(payload, headers=make_manufacturer_rep_headers(manufacturer_id))
    )


def evaluate_quote(quote_id: str) -> dict:
    """SUBMITTED -> UNDER_EVALUATION (SourcingLead)."""
    return get_success_data(
        api_client.patch_cost_quote(quote_id, {"status": "UNDER_EVALUATION"}, headers=_SOURCING)
    )


def accept_quote(quote_id: str) -> dict:
    """UNDER_EVALUATION -> ACCEPTED (SourcingLead); runs the evaluation step
    first when needed. Pins pinned_formula_version, consumes one quarterly
    production slot, supersedes sibling pending quotes, stamps accepted_at."""
    quote = read_cost_quote(quote_id)
    if quote["status"] == "SUBMITTED":
        evaluate_quote(quote_id)
    return get_success_data(
        api_client.patch_cost_quote(quote_id, {"status": "ACCEPTED"}, headers=_SOURCING)
    )


def create_accepted_quote(product_id: str, manufacturer_id: str, **overrides) -> dict:
    """Submit + evaluate + accept. Returns the ACCEPTED quote."""
    quote = create_quote(product_id, manufacturer_id, **overrides)
    return accept_quote(quote["id"])


def reject_quote(quote_id: str) -> dict:
    """UNDER_EVALUATION -> REJECTED (SourcingLead)."""
    return get_success_data(
        api_client.patch_cost_quote(quote_id, {"status": "REJECTED"}, headers=_SOURCING)
    )


def withdraw_quote(quote_id: str, manufacturer_id: str) -> dict:
    """SUBMITTED/UNDER_EVALUATION -> WITHDRAWN by the owning ManufacturerRep."""
    return get_success_data(
        api_client.patch_cost_quote(
            quote_id,
            {"status": "WITHDRAWN"},
            headers=make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def settle_quote(quote_id: str, actual_qty: int, actual_freight_total_cents: int) -> dict:
    """ACCEPTED -> SETTLED with actuals (SourcingLead; product must be
    LAUNCHED). Computes landed_settled_cents."""
    return get_success_data(
        api_client.patch_cost_quote(
            quote_id,
            {
                "status": "SETTLED",
                "actual_qty": actual_qty,
                "actual_freight_total_cents": actual_freight_total_cents,
            },
            headers=_SOURCING,
        )
    )


# ---------------------------------------------------------------------------
# Compliance dossiers (ComplianceOfficer)
# ---------------------------------------------------------------------------

def open_dossier(product_id: str) -> dict:
    """Open the product's single dossier (all four dimensions at their
    initial values)."""
    return get_success_data(
        api_client.create_compliance_dossier(
            create_compliance_dossier_payload(product_id=product_id), headers=_COMPLIANCE
        )
    )


def submit_dossier_review(dossier_id: str, dimension: str, outcome: str, **overrides) -> dict:
    """Advance exactly one compliance dimension with a review outcome."""
    return get_success_data(
        api_client.submit_dossier_review(
            dossier_id,
            create_dossier_review_payload(dimension, outcome, **overrides),
            headers=_COMPLIANCE,
        )
    )


def certify_dossier(dossier_id: str) -> dict:
    """Walk the certification dimension NOT_APPLIED -> APPLIED -> AUDITING ->
    CERTIFIED (stamps cert_expires_at = review instant + 365 days)."""
    submit_dossier_review(dossier_id, "CERTIFICATION", "APPLIED")
    submit_dossier_review(dossier_id, "CERTIFICATION", "AUDITING")
    return submit_dossier_review(dossier_id, "CERTIFICATION", "CERTIFIED")


def make_dossier_compliant(dossier_id: str) -> dict:
    """Green-light all four dimensions: INGREDIENT CLEARED, CLAIM
    SUBSTANTIATED, certification CERTIFIED, registration REGISTERED.
    Returns the dossier re-read afterwards (compliant == true)."""
    submit_dossier_review(dossier_id, "INGREDIENT", "CLEARED")
    submit_dossier_review(dossier_id, "CLAIM", "SUBSTANTIATED")
    certify_dossier(dossier_id)
    submit_dossier_review(dossier_id, "REGISTRATION", "FILED")
    submit_dossier_review(dossier_id, "REGISTRATION", "REGISTERED")
    return read_dossier(dossier_id)


# ---------------------------------------------------------------------------
# Retail partners, line reviews, planogram slots (RetailPlanner)
# ---------------------------------------------------------------------------

def create_partner(**overrides) -> dict:
    """Onboard a retail partner. Default capacities: EYES 10, LIPS 8."""
    return get_success_data(
        api_client.create_retail_partner(create_retail_partner_payload(**overrides), headers=_PLANNER)
    )


def update_partner_capacities(partner_id: str, category_capacities: dict) -> dict:
    """Revise category_capacities; a reduction below committed facings
    triggers the capacity-eviction cascade."""
    return get_success_data(
        api_client.patch_retail_partner(
            partner_id, {"category_capacities": category_capacities}, headers=_PLANNER
        )
    )


def create_line_review(partner_id: str, **overrides) -> dict:
    """Schedule a line review (starts SCHEDULED). Default window is the
    half-open interval [2026-10-01, 2026-10-15) with review date 2026-10-20."""
    return get_success_data(
        api_client.create_line_review(
            create_line_review_payload(retail_partner_id=partner_id, **overrides), headers=_PLANNER
        )
    )


def transition_line_review(review_id: str, status: str) -> dict:
    return get_success_data(
        api_client.patch_line_review(review_id, {"status": status}, headers=_PLANNER)
    )


def open_line_review(review_id: str, now: str = None) -> dict:
    """Move SCHEDULED -> SUBMISSION_OPEN with the clock inside the window.
    Defaults the clock to one day after the window start (the canonical
    2026-10-02 for the default window)."""
    review = read_line_review(review_id)
    if now is None:
        now = _iso(_parse_iso(review["submission_window_start"]) + timedelta(days=1))
    set_clock(now)
    return transition_line_review(review_id, "SUBMISSION_OPEN")


def advance_line_review_to_reviewing(review_id: str) -> dict:
    """Move SUBMISSION_OPEN -> REVIEWING with the clock at window end + 1 day
    (the canonical 2026-10-16)."""
    review = read_line_review(review_id)
    set_clock(_iso(_parse_iso(review["submission_window_end"]) + timedelta(days=1)))
    return transition_line_review(review_id, "REVIEWING")


def advance_line_review_to_decided(review_id: str) -> dict:
    """Move through REVIEWING to DECIDED with the clock at review_date + 1 day
    (the canonical 2026-10-21)."""
    review = advance_line_review_to_reviewing(review_id)
    set_clock(_iso(_parse_iso(review["review_date"]) + timedelta(days=1)))
    return transition_line_review(review_id, "DECIDED")


def create_slot(review_id: str, product_id: str, *, expected_line_review_version=None, **overrides) -> dict:
    """Propose a planogram slot while the review's window is open (starts
    PROPOSED; bumps the review's version by one). When
    expected_line_review_version is not given, the review's live version is
    read first. Default: category EYES, position EYES-A1, 10 facings,
    occupancy [2026-11-01, 2027-01-31]."""
    if expected_line_review_version is None:
        expected_line_review_version = read_line_review(review_id)["version"]
    payload = create_planogram_slot_payload(
        line_review_id=review_id,
        product_id=product_id,
        expected_line_review_version=expected_line_review_version,
        **overrides,
    )
    return get_success_data(api_client.create_planogram_slot(payload, headers=_PLANNER))


def commit_slot(slot_id: str) -> dict:
    """PROPOSED -> COMMITTED (capacity-checked; stamps committed_at and
    recomputes the partner's facing availability)."""
    return get_success_data(
        api_client.patch_planogram_slot(slot_id, {"status": "COMMITTED"}, headers=_PLANNER)
    )


def withdraw_slot(slot_id: str) -> dict:
    """PROPOSED -> WITHDRAWN."""
    return get_success_data(
        api_client.patch_planogram_slot(slot_id, {"status": "WITHDRAWN"}, headers=_PLANNER)
    )


# ---------------------------------------------------------------------------
# Launch plans and sampling (ProductManager; sampling MarketingLead)
# ---------------------------------------------------------------------------

def create_launch_plan(product_id: str, slot_id: str, **overrides) -> dict:
    """Create a launch plan (DRAFT). Computes capacity_units,
    markdown_risk_pct, and both quantity variants at creation. Default:
    demand 800, marketing 50000, cogs 200000, sample budget 20000."""
    return get_success_data(
        api_client.create_launch_plan(
            create_launch_plan_payload(product_id=product_id, planogram_slot_id=slot_id, **overrides),
            headers=_PM,
        )
    )


def lock_plan(plan_id: str, variant: str = "DEMAND") -> dict:
    """DRAFT -> QUANTITY_LOCKED with variant DEMAND or RISK_ADJUSTED
    (ProductManager). Sets qty_locked_units, locked_variant,
    landed_locked_cents via the single-pass budget clamp."""
    return get_success_data(
        api_client.patch_launch_plan(
            plan_id, {"status": "QUANTITY_LOCKED", "variant": variant}, headers=_PM
        )
    )


def approve_plan(plan_id: str) -> dict:
    """QUANTITY_LOCKED -> APPROVED (ProductManager). Requires the slot
    COMMITTED, the dossier compliant, and sample budget within marketing."""
    return get_success_data(
        api_client.patch_launch_plan(plan_id, {"status": "APPROVED"}, headers=_PM)
    )


def execute_plan(plan_id: str, now: str = None) -> dict:
    """APPROVED -> EXECUTED (ProductManager) with the clock at the slot's
    occupancy_start unless overridden. Fans out: product LAUNCHED (stamps
    launched_at), slot ACTIVE, concept COMMERCIALIZED."""
    plan = read_launch_plan(plan_id)
    slot = read_planogram_slot(plan["planogram_slot_id"])
    set_clock(now or slot["occupancy_start"])
    return get_success_data(
        api_client.patch_launch_plan(plan_id, {"status": "EXECUTED"}, headers=_PM)
    )


def set_sampling_status(plan_id: str, sampling_status: str) -> dict:
    """Drive the parallel sampling dimension (MarketingLead only):
    NONE -> PLANNED -> ACTIVE -> CLOSED."""
    return get_success_data(
        api_client.patch_launch_plan(
            plan_id, {"sampling_status": sampling_status}, headers=_MARKETING
        )
    )


def set_sample_budget(plan_id: str, sample_budget_cents: int) -> dict:
    """Update the sampling budget (MarketingLead only)."""
    return get_success_data(
        api_client.patch_launch_plan(
            plan_id, {"sample_budget_cents": sample_budget_cents}, headers=_MARKETING
        )
    )


def record_sample_event(plan_id: str, event_type: str, units: int, channel: str = None) -> dict:
    """Record a COMMIT / DISTRIBUTE / RELEASE sampling event (MarketingLead).
    Returns the mutated launch plan."""
    return get_success_data(
        api_client.create_sample_distribution(
            plan_id,
            create_sample_distribution_payload(event_type, units, channel=channel),
            headers=_MARKETING,
        )
    )


# ---------------------------------------------------------------------------
# Discontinuation reviews (ProductManager proposes; RetailPlanner decides)
# ---------------------------------------------------------------------------

def propose_discontinuation(
    product_id: str,
    reason: str = "TREND_DECAY",
    successor_product_id: str = None,
    proposer_user_id: str = PRODUCT_MANAGER_USER_ID,
) -> dict:
    """Propose discontinuing a LAUNCHED product (starts PROPOSED; records
    proposed_by_user_id from the caller's X-User-ID)."""
    return get_success_data(
        api_client.create_discontinuation_review(
            create_discontinuation_review_payload(
                product_id=product_id,
                reason=reason,
                successor_product_id=successor_product_id,
            ),
            headers=make_product_manager_headers(proposer_user_id),
        )
    )


def approve_discontinuation(review_id: str, approver_user_id: str = RETAIL_PLANNER_USER_ID) -> dict:
    """PROPOSED -> APPROVED (RetailPlanner; approver must differ from the
    proposer). Fires the four-entity discontinuation cascade."""
    return get_success_data(
        api_client.patch_discontinuation_review(
            review_id,
            {"status": "APPROVED"},
            headers=make_retail_planner_headers(approver_user_id),
        )
    )


def reject_discontinuation(review_id: str, approver_user_id: str = RETAIL_PLANNER_USER_ID) -> dict:
    """PROPOSED -> REJECTED (RetailPlanner; same segregation-of-duties gate)."""
    return get_success_data(
        api_client.patch_discontinuation_review(
            review_id,
            {"status": "REJECTED"},
            headers=make_retail_planner_headers(approver_user_id),
        )
    )


# ---------------------------------------------------------------------------
# Composite fixtures. Each returns a ctx dict keyed by entity name:
#   trend, concept, manufacturer, product, formula_project, quote, dossier,
#   partner, line_review, slot, plan
# Every composite accepts *_overrides dicts for the entities it creates and
# forwards the rest upstream.
# ---------------------------------------------------------------------------

def setup_product_with_approved_formula(
    *,
    trend_overrides: dict = None,
    concept_overrides: dict = None,
    manufacturer_overrides: dict = None,
    product_overrides: dict = None,
    formula_overrides: dict = None,
) -> dict:
    """Clock at the start instant; trend SELECTED; concept SELECTED;
    manufacturer ACTIVE; product FORMULATION; formula project APPROVED
    (round_count 1, formula_version 1)."""
    ctx = {}
    set_clock()
    ctx["trend"] = create_selected_trend(**(trend_overrides or {}))
    ctx["concept"] = create_selected_concept(ctx["trend"]["id"], **(concept_overrides or {}))
    ctx["manufacturer"] = create_manufacturer(**(manufacturer_overrides or {}))
    ctx["product"] = create_product(ctx["concept"]["id"], **(product_overrides or {}))
    ctx["formula_project"] = create_approved_formula(
        ctx["product"]["id"], ctx["manufacturer"]["id"], **(formula_overrides or {})
    )
    return ctx


def setup_sourcing_product(**kwargs) -> dict:
    """Above, plus product FORMULATION -> SOURCING (no quote yet)."""
    ctx = setup_product_with_approved_formula(**kwargs)
    ctx["product"] = transition_product(ctx["product"]["id"], "SOURCING")
    return ctx


def setup_accepted_quote_product(*, quote_overrides: dict = None, **kwargs) -> dict:
    """Above, plus a quote ACCEPTED (pinned_formula_version 1, one production
    slot consumed for the quote's quarter). Product remains SOURCING."""
    ctx = setup_sourcing_product(**kwargs)
    ctx["quote"] = create_accepted_quote(
        ctx["product"]["id"], ctx["manufacturer"]["id"], **(quote_overrides or {})
    )
    ctx["product"] = read_product(ctx["product"]["id"])  # version bumped by quote creation
    return ctx


def setup_compliance_gate_product(**kwargs) -> dict:
    """Above, plus product SOURCING -> COMPLIANCE_GATE. No dossier exists yet
    (dossier-free starting point for compliance tests)."""
    ctx = setup_accepted_quote_product(**kwargs)
    ctx["product"] = transition_product(ctx["product"]["id"], "COMPLIANCE_GATE")
    return ctx


def setup_compliant_gate_product(**kwargs) -> dict:
    """Above, plus a fully compliant dossier (all four dimensions green;
    certification CERTIFIED, expiring one year after the review instant).
    Product remains COMPLIANCE_GATE."""
    ctx = setup_compliance_gate_product(**kwargs)
    ctx["dossier"] = open_dossier(ctx["product"]["id"])
    ctx["dossier"] = make_dossier_compliant(ctx["dossier"]["id"])
    return ctx


def setup_launch_ready_product(**kwargs) -> dict:
    """Above, plus packaging PACK_READY and product COMPLIANCE_GATE ->
    LAUNCH_READY."""
    ctx = setup_compliant_gate_product(**kwargs)
    ctx["product"] = set_packaging_ready(ctx["product"]["id"])
    ctx["product"] = transition_product(ctx["product"]["id"], "LAUNCH_READY")
    return ctx


def setup_open_review_with_slot(
    *,
    partner_overrides: dict = None,
    line_review_overrides: dict = None,
    slot_overrides: dict = None,
    **kwargs,
) -> dict:
    """Above, plus a retail partner, a line review opened with the clock
    inside its window (canonical 2026-10-02), and a PROPOSED slot."""
    ctx = setup_launch_ready_product(**kwargs)
    ctx["partner"] = create_partner(**(partner_overrides or {}))
    ctx["line_review"] = create_line_review(ctx["partner"]["id"], **(line_review_overrides or {}))
    ctx["line_review"] = open_line_review(ctx["line_review"]["id"])
    ctx["slot"] = create_slot(
        ctx["line_review"]["id"], ctx["product"]["id"], **(slot_overrides or {})
    )
    ctx["line_review"] = read_line_review(ctx["line_review"]["id"])  # version bumped by slot creation
    return ctx


def setup_draft_plan(*, plan_overrides: dict = None, **kwargs) -> dict:
    """Above, plus a DRAFT launch plan created while the clock is still inside
    the submission window (canonical 2026-10-02), so markdown_risk_pct and
    both quantity variants are pinned to the default timeline."""
    ctx = setup_open_review_with_slot(**kwargs)
    ctx["plan"] = create_launch_plan(
        ctx["product"]["id"], ctx["slot"]["id"], **(plan_overrides or {})
    )
    return ctx


def setup_decided_review_with_slot(**kwargs) -> dict:
    """Above the open review, plus the review advanced SUBMISSION_OPEN ->
    REVIEWING -> DECIDED (clock lands on review_date + 1 day, canonical
    2026-10-21). The slot is still PROPOSED. No launch plan is created."""
    ctx = setup_open_review_with_slot(**kwargs)
    ctx["line_review"] = advance_line_review_to_decided(ctx["line_review"]["id"])
    return ctx


def setup_committed_slot_scenario(**kwargs) -> dict:
    """Above, plus the slot PROPOSED -> COMMITTED (committed_at stamped at the
    canonical 2026-10-21; partner facings recomputed). No launch plan."""
    ctx = setup_decided_review_with_slot(**kwargs)
    ctx["slot"] = commit_slot(ctx["slot"]["id"])
    return ctx


def setup_locked_plan(*, variant: str = "DEMAND", **kwargs) -> dict:
    """Full canonical chain through plan QUANTITY_LOCKED: draft plan created
    inside the window, review advanced to DECIDED, slot COMMITTED, then the
    quantity lock with the given variant. Default lock: DEMAND at 800 units,
    landed 237 cents."""
    ctx = setup_draft_plan(**kwargs)
    ctx["line_review"] = advance_line_review_to_decided(ctx["line_review"]["id"])
    ctx["slot"] = commit_slot(ctx["slot"]["id"])
    ctx["plan"] = lock_plan(ctx["plan"]["id"], variant=variant)
    return ctx


def setup_approved_plan(**kwargs) -> dict:
    """Above, plus the plan QUANTITY_LOCKED -> APPROVED."""
    ctx = setup_locked_plan(**kwargs)
    ctx["plan"] = approve_plan(ctx["plan"]["id"])
    return ctx


def setup_executed_plan(**kwargs) -> dict:
    """Above, plus the clock advanced to the slot's occupancy start
    (canonical 2026-11-01) and the plan APPROVED -> EXECUTED. Product is
    LAUNCHED (launched_at stamped), slot ACTIVE, concept COMMERCIALIZED.
    ctx entities are refreshed to their post-execution state."""
    ctx = setup_approved_plan(**kwargs)
    ctx["plan"] = execute_plan(ctx["plan"]["id"])
    ctx["product"] = read_product(ctx["product"]["id"])
    ctx["slot"] = read_planogram_slot(ctx["slot"]["id"])
    ctx["concept"] = read_concept(ctx["concept"]["id"])
    return ctx


def setup_executed_plan_with_sampling(**kwargs) -> dict:
    """Above, plus the sampling program moved NONE -> PLANNED -> ACTIVE
    (MarketingLead), so DISTRIBUTE events are accepted."""
    ctx = setup_executed_plan(**kwargs)
    set_sampling_status(ctx["plan"]["id"], "PLANNED")
    ctx["plan"] = set_sampling_status(ctx["plan"]["id"], "ACTIVE")
    return ctx
