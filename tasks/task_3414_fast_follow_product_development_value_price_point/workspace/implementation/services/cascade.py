"""Multi-entity cascades and lazy clock-driven transitions (scaffold 1.2 side
effects, PRD 2.4 / 2.9 / 3.3 / 3.6 / 3.7 / 3.9). Every cascaded record gets
its own version increment and updated_at stamp (PRD 2.5).
"""
from datetime import timedelta

from core import clock
from core.constants import CERT_VALIDITY_DAYS
from core.errors import err
from core.store import store, touch
from services import calc


# ---------------------------------------------------------------------------
# Product reformulation (manual PATCH -> FORMULATION, or cert DENIED/LAPSED)
# ---------------------------------------------------------------------------
def reformulate_product(product):
    """Side effects of a product returning to FORMULATION (PRD 3.3): every
    ACCEPTED quote -> INVALIDATED (releasing its quarterly production slot);
    every APPROVED formula project reopens to IN_DEVELOPMENT with round_count
    incremented. The caller sets product.status and touches the product."""
    for quote in store.cost_quotes.values():
        if quote["product_id"] == product["id"] and quote["status"] == "ACCEPTED":
            quote["status"] = "INVALIDATED"
            touch(quote)
    for project in store.formula_projects.values():
        if project["product_id"] == product["id"] and project["status"] == "APPROVED":
            project["status"] = "IN_DEVELOPMENT"
            project["round_count"] += 1
            touch(project)


def kill_product(product):
    """Side effects of killing a product (PRD 3.3): linked concept returns to
    SELECTED (revision loop); every non-terminal quote (SUBMITTED,
    UNDER_EVALUATION, ACCEPTED) -> SUPERSEDED."""
    concept = store.concepts.get(product["concept_id"])
    if concept is not None and concept["status"] == "IN_DEVELOPMENT":
        concept["status"] = "SELECTED"
        touch(concept)
    for quote in store.cost_quotes.values():
        if quote["product_id"] == product["id"] and quote["status"] in (
            "SUBMITTED",
            "UNDER_EVALUATION",
            "ACCEPTED",
        ):
            quote["status"] = "SUPERSEDED"
            touch(quote)


# ---------------------------------------------------------------------------
# Compliance cascades: cert DENIED / lazy LAPSED (PRD 3.6)
# ---------------------------------------------------------------------------
def cert_reversion_cascade(dossier):
    """If the dossier's product is in COMPLIANCE_GATE or LAUNCH_READY it
    reverts directly to FORMULATION (no intermediate state), which in turn
    invalidates accepted quotes and reopens approved formula projects. A
    LAUNCHED product stays LAUNCHED."""
    product = store.products.get(dossier["product_id"])
    if product is None:
        return
    if product["status"] in ("COMPLIANCE_GATE", "LAUNCH_READY"):
        product["status"] = "FORMULATION"
        touch(product)
        reformulate_product(product)


def eval_cert_lapse(dossier):
    """Lazy cert lapse (PRD 2.4): any read or write of the dossier once the
    logical clock has passed cert_expires_at moves cert_status to LAPSED and
    fires the same product-reversion cascade as DENIED."""
    if (
        dossier["cert_status"] == "CERTIFIED"
        and dossier["cert_expires_at"] is not None
        and clock.now() > dossier["cert_expires_at"]
    ):
        dossier["cert_status"] = "LAPSED"
        touch(dossier)
        cert_reversion_cascade(dossier)


def dossier_compliant(product_id):
    """The derived compliance verdict (PRD 3.6): ingredient CLEARED, claim
    SUBSTANTIATED, cert CERTIFIED and not lazily LAPSED, registration
    REGISTERED. Reading the dossier applies the lazy lapse first."""
    for dossier in store.dossiers.values():
        if dossier["product_id"] == product_id:
            eval_cert_lapse(dossier)
            return (
                dossier["ingredient_status"] == "CLEARED"
                and dossier["claim_status"] == "SUBSTANTIATED"
                and dossier["cert_status"] == "CERTIFIED"
                and dossier["registration_status"] == "REGISTERED"
            )
    return False


def certify(dossier):
    dossier["cert_status"] = "CERTIFIED"
    dossier["cert_expires_at"] = clock.now() + timedelta(days=CERT_VALIDITY_DAYS)


# ---------------------------------------------------------------------------
# CostQuote lazy expiry (PRD 2.4): any read or attempted transition once the
# clock has passed valid_until moves a still-pending quote to EXPIRED.
# ---------------------------------------------------------------------------
def eval_quote_expiry(quote):
    if quote["status"] in ("SUBMITTED", "UNDER_EVALUATION") and clock.now() > quote[
        "valid_until"
    ]:
        quote["status"] = "EXPIRED"
        touch(quote)
        return True
    return False


# ---------------------------------------------------------------------------
# PlanogramSlot release / vacate helpers
# ---------------------------------------------------------------------------
def revert_plan_to_draft(slot):
    """A released slot's QUANTITY_LOCKED or APPROVED launch plan reverts to
    DRAFT with the locked quantity and locked landed cost cleared."""
    for plan in store.launch_plans.values():
        if plan["planogram_slot_id"] == slot["id"] and plan["status"] in (
            "QUANTITY_LOCKED",
            "APPROVED",
        ):
            plan["status"] = "DRAFT"
            plan["qty_locked_units"] = None
            plan["landed_locked_cents"] = None
            plan["locked_variant"] = None
            touch(plan)


def release_slot(slot):
    slot["status"] = "RELEASED"
    touch(slot)
    revert_plan_to_draft(slot)


def partner_slots(partner_id):
    review_partner = {r["id"]: r["retail_partner_id"] for r in store.line_reviews.values()}
    return [
        s
        for s in store.planogram_slots.values()
        if review_partner.get(s["line_review_id"]) == partner_id
    ]


def committed_facings(partner_id, category):
    return sum(
        s["facings"]
        for s in partner_slots(partner_id)
        if s["category"] == category and s["status"] in ("COMMITTED", "ACTIVE")
    )


# ---------------------------------------------------------------------------
# capacity_eviction (calculations.capacity_eviction): atomic — either the
# reduction fits after evicting newest COMMITTED slots, or nothing changes.
# ---------------------------------------------------------------------------
def apply_capacity_revision(partner, new_caps):
    """Apply a category_capacities revision, evicting COMMITTED slots
    (committed_at DESC, created_at DESC — insertion order breaks same-instant
    ties) until each category fits. If ACTIVE slots alone still overflow a
    category after every COMMITTED slot is evicted, reject the whole revision
    with ERR_CAPACITY_EXCEEDED and change nothing."""
    # Categories are the union of old and new keys; a key absent from the new
    # map is treated as capacity 0.
    categories = set(new_caps) | set(partner["category_capacities"])
    eviction_plan = []
    for category in categories:
        new_capacity = new_caps.get(category, 0)
        slots = [
            s
            for s in partner_slots(partner["id"])
            if s["category"] == category and s["status"] in ("COMMITTED", "ACTIVE")
        ]
        total = sum(s["facings"] for s in slots)
        if total <= new_capacity:
            continue
        committed_newest_first = sorted(
            (s for s in slots if s["status"] == "COMMITTED"),
            key=lambda s: (s["committed_at"], s["created_at"], s["_seq"]),
            reverse=True,
        )
        evicting = []
        remaining = total
        for slot in committed_newest_first:
            if remaining <= new_capacity:
                break
            evicting.append(slot)
            remaining -= slot["facings"]
        if remaining > new_capacity:
            raise err(
                "ERR_CAPACITY_EXCEEDED",
                "ACTIVE planogram slots still exceed the revised capacity for "
                "category %s" % category,
            )
        eviction_plan.extend(evicting)
    for slot in eviction_plan:
        release_slot(slot)
    partner["category_capacities"] = dict(new_caps)
    touch(partner)


# ---------------------------------------------------------------------------
# Discontinuation cascade (PRD 3.9)
# ---------------------------------------------------------------------------
def reconcile_plan(plan):
    """EXECUTED -> RECONCILED: markdown_units := retail_units_available and
    markdown_exposure_cents from the product's age depth tier."""
    product = store.products.get(plan["product_id"])
    retail_available = (
        plan["qty_locked_units"]
        - plan["samples_committed"]
        - plan["samples_distributed"]
        - plan["markdown_units"]
    )
    plan["markdown_units"] = retail_available
    plan["markdown_exposure_cents"] = calc.markdown_exposure_cents(
        retail_available,
        plan["landed_locked_cents"],
        product["launched_at"],
        clock.now(),
    )
    plan["status"] = "RECONCILED"
    touch(plan)


def discontinue_product(product, successor_product_id):
    """Approval cascade, four entities deep: product LAUNCHED -> DISCONTINUED
    with successor set from the review; its COMMITTED/ACTIVE slots -> VACATED
    (freeing facings; partner facing availability is recomputed on read); its
    EXECUTED launch plans -> RECONCILED."""
    product["status"] = "DISCONTINUED"
    product["successor_product_id"] = successor_product_id
    touch(product)
    for slot in store.planogram_slots.values():
        if slot["product_id"] == product["id"] and slot["status"] in (
            "COMMITTED",
            "ACTIVE",
        ):
            slot["status"] = "VACATED"
            touch(slot)
    for plan in store.launch_plans.values():
        if plan["product_id"] == product["id"] and plan["status"] == "EXECUTED":
            reconcile_plan(plan)
