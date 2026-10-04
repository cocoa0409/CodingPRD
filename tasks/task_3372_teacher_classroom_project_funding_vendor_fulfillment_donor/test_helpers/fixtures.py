"""Composite fixtures that walk the API to a wanted state.

The harness restarts the server before every test, so each test builds the
world it needs from scratch through the public API. These helpers do that
walking and return the rows, headers and identifiers the test asserts against.

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error.

Tiers:
  1. clock, sweep and single-resource creation
  2. the canonical school / teacher / vendor / catalog world
  3. project lifecycle walks (DRAFT -> FUNDING -> FUNDED -> FULFILLED)
  4. expiry / donor-choice worlds
  5. fraud and suspension worlds
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient
from . import factories as f
from .constants import BASE_CLOCK, REVIEWER_SCREENER, REVIEWER_VETTER
from .test_users import (
    ADMIN_HEADERS,
    ANON_HEADERS,
    make_donor_headers,
    make_teacher_headers,
    make_vendor_headers,
    reviewer_headers,
)

# An item line in a project fixture: (catalog item payload, quantity).
ItemSpec = Tuple[Dict[str, Any], int]


# ═══ Tier 1: clock, sweep, single-resource creation ════════════════════════

def set_clock(api: ApiClient, current_utc: str = BASE_CLOCK) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ADMIN_HEADERS))


def run_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run the expiration sweep and return its five-list summary."""
    return get_success_data(api.run_expiration_sweep(ADMIN_HEADERS))


def create_school(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_school(f.school_payload(**overrides), ADMIN_HEADERS))


def create_teacher(api: ApiClient, school_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register a teacher (starts PENDING_VERIFICATION)."""
    return get_success_data(api.create_teacher(f.teacher_payload(school_id, **overrides), ANON_HEADERS))


def verify_teacher(api: ApiClient, teacher_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.review_teacher_employment(teacher_id, f.employment_review_payload("VERIFY"), ADMIN_HEADERS)
    )


def create_verified_teacher(api: ApiClient, school_id: str, **overrides: Any) -> Dict[str, Any]:
    teacher = create_teacher(api, school_id, **overrides)
    return verify_teacher(api, teacher["id"])


def create_vendor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_vendor(f.vendor_payload(**overrides), ADMIN_HEADERS))


def create_catalog_item(api: ApiClient, vendor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_catalog_item(vendor_id, f.catalog_item_payload(**overrides), ADMIN_HEADERS)
    )


def create_donor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_donor(f.donor_payload(**overrides), ANON_HEADERS))


def create_match_campaign(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_match_campaign(f.match_campaign_payload(**overrides), ADMIN_HEADERS))


def create_equity_fund(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_equity_fund(f.equity_fund_payload(**overrides), ADMIN_HEADERS))


# ── Readers (PlatformAdmin can read everything) ────────────────────────────

def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_project(project_id, ADMIN_HEADERS))


def read_teacher(api: ApiClient, teacher_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_teacher(teacher_id, ADMIN_HEADERS))


def read_donor(api: ApiClient, donor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_donor(donor_id, ADMIN_HEADERS))


def read_donation(api: ApiClient, donation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_donation(donation_id, ADMIN_HEADERS))


def read_match_campaign(api: ApiClient, campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_match_campaign(campaign_id, ADMIN_HEADERS))


def read_equity_fund(api: ApiClient, fund_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_equity_fund(fund_id, ADMIN_HEADERS))


def read_purchase_order(api: ApiClient, po_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_purchase_order(po_id, ADMIN_HEADERS))


def read_vendor(api: ApiClient, vendor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vendor(vendor_id, ADMIN_HEADERS))


def project_items_for(api: ApiClient, project_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(
        api.list_project_items(ADMIN_HEADERS, {"project_id": project_id})
    )
    return rows


def purchase_orders_for(
    api: ApiClient, project_id: str, vendor_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"project_id": project_id}
    if vendor_id is not None:
        params["vendor_id"] = vendor_id
    rows, _ = validate_paginated(api.list_purchase_orders(ADMIN_HEADERS, params))
    return rows


def projects_for_teacher(api: ApiClient, teacher_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(api.list_projects(ADMIN_HEADERS, {"teacher_id": teacher_id}))
    return rows


def donations_for_donor(api: ApiClient, donor_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(api.list_donations(ADMIN_HEADERS, {"donor_id": donor_id}))
    return rows


def fraud_cases_for_teacher(api: ApiClient, teacher_id: str) -> List[Dict[str, Any]]:
    rows, _ = validate_paginated(api.list_fraud_cases(ADMIN_HEADERS, {"teacher_id": teacher_id}))
    return rows


# ═══ Tier 2: the canonical world ═══════════════════════════════════════════

def seed_school_teacher(
    api: ApiClient, school_overrides: Optional[Dict[str, Any]] = None,
    teacher_overrides: Optional[Dict[str, Any]] = None, verify: bool = True,
) -> Dict[str, Any]:
    """Clock + school + teacher (verified unless told otherwise)."""
    set_clock(api)
    school = create_school(api, **(school_overrides or {}))
    if verify:
        teacher = create_verified_teacher(api, school["id"], **(teacher_overrides or {}))
    else:
        teacher = create_teacher(api, school["id"], **(teacher_overrides or {}))
    return {
        "school": school,
        "teacher": teacher,
        "teacher_headers": make_teacher_headers(teacher["id"]),
    }


def seed_vendor_with_items(
    api: ApiClient, item_specs: Optional[Sequence[ItemSpec]] = None,
    vendor_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One vendor plus one catalog item per spec; returns vendor and the item rows."""
    vendor = create_vendor(api, **(vendor_overrides or {}))
    specs = item_specs if item_specs is not None else [(f.book_item_spec(), 4)]
    items = [create_catalog_item(api, vendor["id"], **spec) for spec, _qty in specs]
    return {
        "vendor": vendor,
        "vendor_headers": make_vendor_headers(vendor["id"]),
        "items": items,
    }


# ═══ Tier 3: project lifecycle walks ═══════════════════════════════════════

def create_project(api: ApiClient, teacher: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Create a DRAFT project as its owning teacher."""
    return get_success_data(
        api.create_project(f.project_payload(**overrides), make_teacher_headers(teacher["id"]))
    )


def current_project_version(api: ApiClient, project_id: str) -> int:
    return read_project(api, project_id)["version"]


def add_item(
    api: ApiClient, project_id: str, teacher: Dict[str, Any], catalog_item_id: str, quantity: int
) -> Dict[str, Any]:
    """Add an item with a fresh OCC version (read immediately before the write)."""
    version = current_project_version(api, project_id)
    return get_success_data(
        api.add_project_item(
            project_id,
            f.add_item_payload(catalog_item_id, quantity, version),
            make_teacher_headers(teacher["id"]),
        )
    )


def submit_project(api: ApiClient, project_id: str, teacher: Dict[str, Any]) -> Dict[str, Any]:
    """Submit with a fresh OCC version; returns the IN_REVIEW project."""
    version = current_project_version(api, project_id)
    return get_success_data(
        api.submit_project(project_id, f.submit_payload(version), make_teacher_headers(teacher["id"]))
    )


def review_project(
    api: ApiClient, project_id: str, stage: str, outcome: str, reviewer_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api.review_project(project_id, f.review_payload(stage, outcome), reviewer_headers(reviewer_id))
    )


def walk_project_to_funding(
    api: ApiClient,
    project_id: str,
    teacher: Dict[str, Any],
    screener: str = REVIEWER_SCREENER,
    vetter: str = REVIEWER_VETTER,
) -> Dict[str, Any]:
    """Submit, SCREEN APPROVE, VET APPROVE; returns the FUNDING project."""
    submit_project(api, project_id, teacher)
    review_project(api, project_id, "SCREEN", "APPROVE", screener)
    return review_project(api, project_id, "VET", "APPROVE", vetter)


def donate(
    api: ApiClient,
    project_id: str,
    donor: Dict[str, Any],
    amount_cents: int,
    match_campaign_id: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_donation(
            project_id,
            f.donation_payload(amount_cents, match_campaign_id),
            make_donor_headers(donor["id"]),
        )
    )


def setup_draft_project(
    api: ApiClient,
    item_specs: Optional[Sequence[ItemSpec]] = None,
    school_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """School + verified teacher + vendor + items + a DRAFT project holding them."""
    world = seed_school_teacher(api, school_overrides)
    vendor_world = seed_vendor_with_items(api, item_specs)
    world.update(vendor_world)
    specs = item_specs if item_specs is not None else [(f.book_item_spec(), 4)]
    project = create_project(api, world["teacher"], **(project_overrides or {}))
    for item, qty in zip(world["items"], [qty for _spec, qty in specs]):
        add_item(api, project["id"], world["teacher"], item["id"], qty)
    world["project"] = read_project(api, project["id"])
    return world


def setup_funding_project(
    api: ApiClient,
    item_specs: Optional[Sequence[ItemSpec]] = None,
    school_overrides: Optional[Dict[str, Any]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The draft world walked through screening and vetting into FUNDING."""
    world = setup_draft_project(api, item_specs, school_overrides, project_overrides)
    world["project"] = walk_project_to_funding(api, world["project"]["id"], world["teacher"])
    return world


def create_funding_project(
    api: ApiClient,
    teacher: Dict[str, Any],
    items: Sequence[Tuple[str, int]],
    **project_overrides: Any,
) -> Dict[str, Any]:
    """DRAFT project with the given (catalog_item_id, quantity) lines -> FUNDING."""
    project = create_project(api, teacher, **project_overrides)
    for item_id, qty in items:
        add_item(api, project["id"], teacher, item_id, qty)
    return walk_project_to_funding(api, project["id"], teacher)


def setup_funded_project(
    api: ApiClient,
    item_specs: Optional[Sequence[ItemSpec]] = None,
    donations: Optional[Sequence[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """A FUNDING world tipped to FUNDED.

    ``donations`` defaults to a single donation of the exact goal. Each entry
    carries ``amount_cents`` and optionally ``match_campaign_id``.
    """
    world = setup_funding_project(api, item_specs, **kwargs)
    donor = create_donor(api)
    world["donor"] = donor
    world["donor_headers"] = make_donor_headers(donor["id"])
    goal = read_project(api, world["project"]["id"])["goal_cents"]
    specs = list(donations) if donations is not None else [{"amount_cents": goal}]
    world["donations"] = [
        donate(api, world["project"]["id"], donor, d["amount_cents"], d.get("match_campaign_id"))
        for d in specs
    ]
    world["project"] = read_project(api, world["project"]["id"])
    world["purchase_orders"] = purchase_orders_for(api, world["project"]["id"])
    return world


def setup_two_vendor_funded_project(api: ApiClient) -> Dict[str, Any]:
    """SchoolMart book x4 plus RugCo rug x2 on one project, tipped to FUNDED.

    Goal: items 4*2500 + 2*1000 = 12000, shipping 959 + 959, total 13918.
    """
    world = seed_school_teacher(api)
    v1_world = seed_vendor_with_items(api, [(f.book_item_spec(), 4)])
    world.update(v1_world)
    vendor2 = create_vendor(api, name="RugCo", contact_email="ops@rugco.example")
    rug = create_catalog_item(api, vendor2["id"], **f.rug_item_spec())
    world["vendor2"] = vendor2
    world["vendor2_headers"] = make_vendor_headers(vendor2["id"])
    world["rug_item"] = rug
    world["project"] = create_funding_project(
        api, world["teacher"], [(world["items"][0]["id"], 4), (rug["id"], 2)]
    )
    donor = create_donor(api)
    world["donor"] = donor
    world["donor_headers"] = make_donor_headers(donor["id"])
    world["donations"] = [donate(api, world["project"]["id"], donor, 13918)]
    world["project"] = read_project(api, world["project"]["id"])
    world["po_book"] = purchase_orders_for(api, world["project"]["id"], world["vendor"]["id"])[0]
    world["po_rug"] = purchase_orders_for(api, world["project"]["id"], vendor2["id"])[0]
    return world


def ship_purchase_order(api: ApiClient, po: Dict[str, Any], tracking: str = "1Z999AA10123456784") -> Dict[str, Any]:
    """SHIP as the PO's owning vendor."""
    return get_success_data(
        api.advance_purchase_order(
            po["id"], f.po_advance_payload("SHIP", tracking_number=tracking),
            make_vendor_headers(po["vendor_id"]),
        )
    )


def deliver_purchase_order(api: ApiClient, po_id: str, teacher: Dict[str, Any]) -> Dict[str, Any]:
    """DELIVER as the project's owning teacher."""
    return get_success_data(
        api.advance_purchase_order(
            po_id, f.po_advance_payload("DELIVER"), make_teacher_headers(teacher["id"])
        )
    )


def report_diversion(api: ApiClient, po_id: str, reason: str = "Materials listed for resale online") -> Dict[str, Any]:
    return get_success_data(
        api.advance_purchase_order(po_id, f.po_advance_payload("REPORT_DIVERSION", reason=reason), ADMIN_HEADERS)
    )


def setup_fulfilled_project(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A FUNDED project whose every purchase order has been delivered."""
    world = setup_funded_project(api, **kwargs)
    for po in world["purchase_orders"]:
        ship_purchase_order(api, po)
        deliver_purchase_order(api, po["id"], world["teacher"])
    world["project"] = read_project(api, world["project"]["id"])
    return world


# ═══ Tier 4: expiry / donor-choice worlds ══════════════════════════════════

def setup_expired_project(
    api: ApiClient,
    amounts: Sequence[int] = (5000,),
    match_campaign_id: Optional[str] = None,
    with_equity_fund: bool = False,
    equity_fund_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A FUNDING project with donations, swept at its deadline.

    The project lands EXPIRED and every donation lands CHOICE_PENDING with a
    choice deadline fourteen days past the sweep instant.
    """
    world = setup_funding_project(api)
    donor = create_donor(api)
    world["donor"] = donor
    world["donor_headers"] = make_donor_headers(donor["id"])
    world["donations"] = [
        donate(api, world["project"]["id"], donor, amount, match_campaign_id)
        for amount in amounts
    ]
    fund = None
    if with_equity_fund:
        fund = create_equity_fund(api, **(equity_fund_overrides or {}))
        world["equity_fund"] = fund
    deadline = read_project(api, world["project"]["id"])["funding_deadline"]
    set_clock(api, deadline)
    world["sweep"] = run_sweep(api)
    world["project"] = read_project(api, world["project"]["id"])
    world["donations"] = [read_donation(api, d["id"]) for d in world["donations"]]
    return world


def donor_choice(
    api: ApiClient,
    donation: Dict[str, Any],
    donor: Dict[str, Any],
    choice: str,
    equity_fund_id: Optional[str] = None,
    version: Optional[int] = None,
):
    """Raw reallocation-choice response with the donation's current version."""
    if version is None:
        version = read_donation(api, donation["id"])["version"]
    return api.reallocation_choice(
        donation["id"],
        f.reallocation_choice_payload(choice, version, equity_fund_id),
        make_donor_headers(donor["id"]),
    )


# ═══ Tier 5: fraud and suspension worlds ═══════════════════════════════════

def setup_open_fraud_case(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """A FUNDED project whose single PO shipped and was diversion-reported."""
    world = setup_funded_project(api, **kwargs)
    po = world["purchase_orders"][0]
    ship_purchase_order(api, po)
    report_diversion(api, po["id"])
    world["purchase_orders"] = purchase_orders_for(api, world["project"]["id"])
    world["fraud_case"] = fraud_cases_for_teacher(api, world["teacher"]["id"])[0]
    return world


def setup_suspended_teacher(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """The fraud cascade run to CONFIRMED: teacher SUSPENDED, pipeline cancelled."""
    world = setup_open_fraud_case(api, **kwargs)
    get_success_data(
        api.resolve_fraud_case(world["fraud_case"]["id"], f.fraud_resolve_payload("CONFIRMED"), ADMIN_HEADERS)
    )
    world["teacher"] = read_teacher(api, world["teacher"]["id"])
    world["project"] = read_project(api, world["project"]["id"])
    return world
