"""Composite setup helpers for the book-mailing domain (PRD §3).

The server is relaunched before every test, so every fixture builds its
preconditions from scratch through PRD-declared endpoints. Setup calls use the
lenient ``get_success_data`` validator and raise ``AssertionError`` prefixed
with "Setup failed" so a broken precondition never masquerades as a failed
assertion under test.

Identity threading: every ownership-gated call is made with entity-backed
headers built from the real entity id (AffiliateCoordinator -> Affiliate.id,
StateProgramOfficer -> StateProgram.id), per PRD §2.1.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    ACM_APPROVER_ID,
    ACM_PROPOSER_ID,
    AGE_BANDS,
    CLOCK_START,
    DEFAULT_PRINT_QUANTITY,
    DEFAULT_TITLE_FROM_MONTH,
    DEFAULT_TITLE_UNTIL_MONTH,
    DEFAULT_WAVE_MONTH,
)
from .factories import (
    DEFAULT_CHILD_SPECS,
    create_address_change_payload,
    create_affiliate_payload,
    create_agreement_payload,
    create_child_payload,
    create_population_stat_payload,
    create_print_order_payload,
    create_selection_payload,
    create_state_program_payload,
    create_title_payload,
    create_wave_payload,
    decide_address_change_payload,
    dispute_invoice_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_advisory_committee_member_headers,
    make_affiliate_coordinator_headers,
    make_state_program_officer_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_MAIL_OPS = TEST_USERS["mail_ops_headers"]
_PUBLISHER = TEST_USERS["publisher_ops_headers"]


def _ok(resp, what):
    """Lenient setup validator: any 2xx is fine, anything else is a fixture bug."""
    if resp.status_code >= 300:
        raise AssertionError(f"Setup failed ({what}): {resp.status_code} {resp.text}")
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Month arithmetic (PRD §2.4: calendar-month arithmetic, YYYY-MM strings)
# ---------------------------------------------------------------------------
def add_months(month: str, n: int) -> str:
    """Return the YYYY-MM month ``n`` calendar months after ``month``."""
    year, mon = int(month[0:4]), int(month[5:7])
    total = year * 12 + (mon - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


# ---------------------------------------------------------------------------
# Tier 1: state progression — one helper per endpoint-level step
# ---------------------------------------------------------------------------
def set_logical_clock(current_utc=CLOCK_START):
    """Advance the logical clock; returns the sweep report (PRD §2.4)."""
    resp = api_client.set_clock(set_clock_payload(current_utc), _ADMIN)
    return _ok(resp, f"set clock to {current_utc}")


def create_state_program(**overrides):
    """Create a state/provincial funding program. Returns the program."""
    resp = api_client.create_state_program(create_state_program_payload(**overrides), _ADMIN)
    return _ok(resp, "create state program")


def create_affiliate(program_id, **overrides):
    """Create a local affiliate (non-operative until an ACTIVE agreement
    fully covers the current logical month). Returns the affiliate."""
    resp = api_client.create_affiliate(create_affiliate_payload(program_id, **overrides), _ADMIN)
    return _ok(resp, "create affiliate")


def create_agreement(affiliate, expected_affiliate_version=None, **overrides):
    """Create a PENDING_APPROVAL agreement for ``affiliate`` (a dict carrying
    at least id/version/state_program_id) as that affiliate's coordinator.
    The OCC token defaults to the affiliate's current version (PRD §2.7)."""
    affiliate_id = affiliate["id"]
    version = expected_affiliate_version
    if version is None:
        version = affiliate["version"]
    payload = create_agreement_payload(version, **overrides)
    resp = api_client.create_agreement(
        affiliate_id, payload, make_affiliate_coordinator_headers(affiliate_id)
    )
    return _ok(resp, f"create agreement for affiliate {affiliate_id}")


def approve_agreement(agreement_id, state_program_id):
    """Officer of the affiliate's program approves a PENDING_APPROVAL
    agreement. Returns the ACTIVE agreement."""
    resp = api_client.approve_agreement(
        agreement_id, make_state_program_officer_headers(state_program_id)
    )
    return _ok(resp, f"approve agreement {agreement_id}")


def reject_agreement(agreement_id, state_program_id):
    """Officer rejects a PENDING_APPROVAL agreement (terminal REJECTED)."""
    resp = api_client.reject_agreement(
        agreement_id, make_state_program_officer_headers(state_program_id)
    )
    return _ok(resp, f"reject agreement {agreement_id}")


def create_population_stat(affiliate_id, **overrides):
    """Record an eligible-population census estimate (own-affiliate
    coordinator). Returns the stat."""
    resp = api_client.create_population_stat(
        affiliate_id,
        create_population_stat_payload(**overrides),
        make_affiliate_coordinator_headers(affiliate_id),
    )
    return _ok(resp, f"create population stat for affiliate {affiliate_id}")


def create_title(age_band, **overrides):
    """Catalog a title for one age band. Returns the title."""
    resp = api_client.create_title(create_title_payload(age_band, **overrides), _ADMIN)
    return _ok(resp, f"create title ({age_band})")


def propose_selection(mailing_month, age_band, title_id, proposer_id=ACM_PROPOSER_ID):
    """Committee member proposes the title for a (month, band) slot.
    Returns the PROPOSED selection."""
    resp = api_client.create_selection(
        create_selection_payload(mailing_month, age_band, title_id),
        make_advisory_committee_member_headers(proposer_id),
    )
    return _ok(resp, f"propose selection {mailing_month}/{age_band}")


def approve_selection(selection_id, approver_id=ACM_APPROVER_ID):
    """A DIFFERENT committee member approves a PROPOSED selection
    (segregation of duties, PRD §3.5). Returns the APPROVED selection."""
    resp = api_client.approve_selection(
        selection_id, make_advisory_committee_member_headers(approver_id)
    )
    return _ok(resp, f"approve selection {selection_id}")


def reopen_selection(selection_id, reason=None, member_id=ACM_APPROVER_ID):
    """Send an APPROVED selection back to PROPOSED (rework cycle)."""
    payload = {} if reason is None else {"reason": reason}
    resp = api_client.reopen_selection(
        selection_id, payload, make_advisory_committee_member_headers(member_id)
    )
    return _ok(resp, f"reopen selection {selection_id}")


def create_print_order(selection_id, quantity=DEFAULT_PRINT_QUANTITY, is_reprint=False,
                       **overrides):
    """PublisherOps submits a print order. Returns the SUBMITTED order
    (pricing fields null until confirmation, PRD §3.6)."""
    resp = api_client.create_print_order(
        create_print_order_payload(selection_id, quantity, is_reprint, **overrides),
        _PUBLISHER,
    )
    return _ok(resp, f"create print order for selection {selection_id}")


def confirm_print_order(print_order_id):
    """Confirm a SUBMITTED order: capacity check, pricing lock, selection
    lock, stock credit (PRD §3.6). Returns the CONFIRMED order."""
    resp = api_client.confirm_print_order(print_order_id, _PUBLISHER)
    return _ok(resp, f"confirm print order {print_order_id}")


def register_child(affiliate_id, **overrides):
    """Coordinator registers a child into their own affiliate (PRD §3.3).
    Returns the ACTIVE child."""
    resp = api_client.create_child(
        create_child_payload(affiliate_id, **overrides),
        make_affiliate_coordinator_headers(affiliate_id),
    )
    return _ok(resp, f"register child on affiliate {affiliate_id}")


def create_address_change(child_id, affiliate_id, new_address):
    """Coordinator submits an address change for a non-terminal child of
    their own affiliate. Returns the PENDING AddressChange."""
    resp = api_client.create_address_change(
        child_id,
        create_address_change_payload(new_address),
        make_affiliate_coordinator_headers(affiliate_id),
    )
    return _ok(resp, f"create address change for child {child_id}")


def decide_address_change(change_id, affiliate_id, outcome="APPROVE"):
    """Coordinator of the child's current (source) affiliate decides a
    PENDING change; APPROVE forks IN_AREA / TRANSFER / UNENROLLED by
    coverage of the new prefix (PRD §3.4). Returns the decided change."""
    resp = api_client.decide_address_change(
        change_id,
        decide_address_change_payload(outcome),
        make_affiliate_coordinator_headers(affiliate_id),
    )
    return _ok(resp, f"decide address change {change_id} ({outcome})")


def create_wave(mailing_month=DEFAULT_WAVE_MONTH):
    """MailOps schedules the wave for a month. Returns the SCHEDULED wave."""
    resp = api_client.create_wave(create_wave_payload(mailing_month), _MAIL_OPS)
    return _ok(resp, f"create wave {mailing_month}")


def manifest_wave(wave_id):
    """Manifest a SCHEDULED wave (requires all five band selections LOCKED
    and per-band stock >= demand, PRD §3.7). Returns the MANIFESTED wave."""
    resp = api_client.manifest_wave(wave_id, _MAIL_OPS)
    return _ok(resp, f"manifest wave {wave_id}")


def reconcile_wave(wave_id):
    """Reconcile a MANIFESTED wave: unreturned items auto-deliver and DRAFT
    invoices are created per affiliate with billable items (PRD §3.7-3.8).
    Returns the RECONCILED wave."""
    resp = api_client.reconcile_wave(wave_id, _MAIL_OPS)
    return _ok(resp, f"reconcile wave {wave_id}")


def mark_item_returned(item_id):
    """MailOps records an undeliverable return; cascades child hold /
    auto-unenroll / affiliate recount (PRD §3.4). Returns the item."""
    resp = api_client.mark_item_returned(item_id, _MAIL_OPS)
    return _ok(resp, f"mark item {item_id} returned")


def issue_invoice(invoice_id):
    """PlatformAdmin issues a DRAFT invoice. Returns the ISSUED invoice."""
    resp = api_client.issue_invoice(invoice_id, _ADMIN)
    return _ok(resp, f"issue invoice {invoice_id}")


def pay_invoice(invoice_id, affiliate_id):
    """Coordinator pays their own affiliate's invoice (from ISSUED or
    ADJUSTED). Returns the PAID invoice."""
    resp = api_client.pay_invoice(
        invoice_id, make_affiliate_coordinator_headers(affiliate_id)
    )
    return _ok(resp, f"pay invoice {invoice_id}")


def open_invoice_dispute(invoice_id, affiliate_id):
    """Coordinator opens a dispute on their own affiliate's ISSUED invoice.
    Returns the DISPUTED invoice."""
    resp = api_client.dispute_invoice(
        invoice_id,
        dispute_invoice_payload("OPEN"),
        make_affiliate_coordinator_headers(affiliate_id),
    )
    return _ok(resp, f"open dispute on invoice {invoice_id}")


def resolve_dispute_overruled(invoice_id):
    """PlatformAdmin overrules a dispute: invoice returns to ISSUED
    unchanged (PRD §3.8). Returns the invoice."""
    resp = api_client.dispute_invoice(
        invoice_id, dispute_invoice_payload("RESOLVE_OVERRULED"), _ADMIN
    )
    return _ok(resp, f"overrule dispute on invoice {invoice_id}")


def resolve_dispute_upheld(invoice_id, credit_amount_cents):
    """PlatformAdmin upholds a dispute with a credit memo against the local
    share: invoice moves to ADJUSTED (PRD §3.8). Returns the invoice."""
    resp = api_client.dispute_invoice(
        invoice_id,
        dispute_invoice_payload("RESOLVE_UPHELD", credit_amount_cents=credit_amount_cents),
        _ADMIN,
    )
    return _ok(resp, f"uphold dispute on invoice {invoice_id}")


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — the core bootstrap
# ---------------------------------------------------------------------------
def setup_operative_affiliate(program_overrides=None, affiliate_overrides=None,
                              agreement_overrides=None, clock=CLOCK_START,
                              approve=True, population_stat=None):
    """Core bootstrap: set the logical clock, create a state program, create
    an affiliate, and create + (optionally) approve its partner agreement.

    With ``approve=True`` and the default window (2026-01-01 .. 2028-01-01)
    the affiliate is operative for the default logical month 2026-09.

    ``population_stat``: None (no stat) or a dict of overrides for
    create_population_stat.

    Returns {"program", "affiliate", "agreement", "population_stat"} where
    ``affiliate`` is re-fetched after the decision so ``operative``,
    ``enrolled_count`` and ``version`` are current, and ``agreement`` /
    ``population_stat`` are None when not created.
    """
    set_logical_clock(clock)
    program = create_state_program(**(program_overrides or {}))
    affiliate = create_affiliate(program["id"], **(affiliate_overrides or {}))
    agreement = create_agreement(affiliate, **(agreement_overrides or {}))
    if approve:
        agreement = approve_agreement(agreement["id"], program["id"])
    stat = None
    if population_stat is not None:
        stat = create_population_stat(affiliate["id"], **population_stat)
    affiliate = _ok(api_client.get_affiliate(affiliate["id"], _ADMIN), "refetch affiliate")
    return {
        "program": program,
        "affiliate": affiliate,
        "agreement": agreement,
        "population_stat": stat,
    }


def setup_second_affiliate(program, postal_prefixes, agreement_overrides=None,
                           approve=True, **affiliate_overrides):
    """Create another affiliate under an existing program, with its own
    agreement — for transfer-branch and cross-affiliate tests. Same return
    shape as setup_operative_affiliate minus the program/clock steps."""
    affiliate = create_affiliate(program["id"], postal_prefixes=postal_prefixes,
                                 **affiliate_overrides)
    agreement = create_agreement(affiliate, **(agreement_overrides or {}))
    if approve:
        agreement = approve_agreement(agreement["id"], program["id"])
    affiliate = _ok(api_client.get_affiliate(affiliate["id"], _ADMIN), "refetch affiliate")
    return {"program": program, "affiliate": affiliate, "agreement": agreement,
            "population_stat": None}


def setup_five_titles(available_from_month=DEFAULT_TITLE_FROM_MONTH,
                      available_until_month=DEFAULT_TITLE_UNTIL_MONTH):
    """Catalog one title per age band. Returns {age_band: title}."""
    return {
        band: create_title(
            band,
            available_from_month=available_from_month,
            available_until_month=available_until_month,
        )
        for band in AGE_BANDS
    }


# ---------------------------------------------------------------------------
# Tier 3: full-lifecycle shortcuts — selections and print supply
# ---------------------------------------------------------------------------
def setup_approved_selection(mailing_month, age_band, title_id=None,
                             title_overrides=None, proposer_id=ACM_PROPOSER_ID,
                             approver_id=ACM_APPROVER_ID):
    """Create a title if needed, propose and approve one selection.
    Returns {"title", "selection"} with the selection APPROVED."""
    if title_id is None:
        title = create_title(age_band, **(title_overrides or {}))
        title_id = title["id"]
    else:
        title = _ok(api_client.get_title(title_id, _ADMIN), "get title")
    selection = propose_selection(mailing_month, age_band, title_id, proposer_id)
    selection = approve_selection(selection["id"], approver_id)
    return {"title": title, "selection": selection}


def setup_locked_selection(mailing_month, age_band, title_id=None,
                           quantity=DEFAULT_PRINT_QUANTITY, is_reprint=False,
                           title_overrides=None):
    """Approved selection plus a CONFIRMED print order — confirmation locks
    the selection and credits title stock (PRD §3.6).
    Returns {"title", "selection", "order"} with selection LOCKED."""
    ctx = setup_approved_selection(mailing_month, age_band, title_id, title_overrides)
    order = create_print_order(ctx["selection"]["id"], quantity, is_reprint)
    order = confirm_print_order(order["id"])
    selection = _ok(api_client.get_selection(ctx["selection"]["id"], _ADMIN), "get selection")
    return {"title": ctx["title"], "selection": selection, "order": order}


def setup_month_supply(mailing_month=DEFAULT_WAVE_MONTH, quantities=None,
                       titles=None, title_window=None, is_reprint=False):
    """Stand up the full five-band supply for one mailing month: one title
    per band (unless ``titles`` given), one APPROVED selection per band, one
    CONFIRMED print order per band — so every band's selection is LOCKED and
    manifest's selection-completeness gate passes (PRD §3.7).

    ``quantities``: None, a single int, or {age_band: qty}.
    ``title_window``: optional (from_month, until_month) override.

    Returns {"titles", "selections", "orders"} keyed by age band.
    """
    if titles is None:
        if title_window is None:
            titles = setup_five_titles()
        else:
            titles = setup_five_titles(*title_window)
    selections, orders = {}, {}
    for band in AGE_BANDS:
        qty = DEFAULT_PRINT_QUANTITY
        if isinstance(quantities, dict):
            qty = quantities.get(band, DEFAULT_PRINT_QUANTITY)
        elif isinstance(quantities, int):
            qty = quantities
        locked = setup_locked_selection(
            mailing_month, band, title_id=titles[band]["id"],
            quantity=qty, is_reprint=is_reprint,
        )
        selections[band] = locked["selection"]
        orders[band] = locked["order"]
    return {"titles": titles, "selections": selections, "orders": orders}


# ---------------------------------------------------------------------------
# Tier 4: accumulation / wave targeting
# ---------------------------------------------------------------------------
def register_children(affiliate_id, specs=None):
    """Register a batch of children on one affiliate. ``specs`` defaults to
    three distinct INFANT-band children eligible for the default 2026-10
    wave (registered 2026-09 < 2026-10, ages 5/4/3 months there).
    Returns the list of children in registration order."""
    children = []
    for spec in (specs if specs is not None else DEFAULT_CHILD_SPECS):
        children.append(register_child(affiliate_id, **spec))
    return children


def setup_wave_ready(mailing_month=DEFAULT_WAVE_MONTH, child_specs=None,
                     quantities=None, clock=CLOCK_START, program_overrides=None,
                     affiliate_overrides=None, agreement_overrides=None,
                     title_window=None, with_population_stat=False,
                     population_overrides=None):
    """Full bootstrap up to a SCHEDULED wave: operative affiliate, five
    LOCKED selections with CONFIRMED print orders for ``mailing_month``,
    children registered, wave created.

    Returns a context dict:
      {"program", "affiliate", "agreement", "population_stat",
       "titles", "selections", "orders", "children", "wave",
       "mailing_month"}
    """
    pop = population_overrides if with_population_stat else None
    if with_population_stat and pop is None:
        pop = {}
    base = setup_operative_affiliate(
        program_overrides=program_overrides,
        affiliate_overrides=affiliate_overrides,
        agreement_overrides=agreement_overrides,
        clock=clock,
        population_stat=pop,
    )
    supply = setup_month_supply(mailing_month, quantities=quantities,
                                title_window=title_window)
    children = register_children(base["affiliate"]["id"], child_specs)
    wave = create_wave(mailing_month)
    return {
        **base,
        **supply,
        "children": children,
        "wave": wave,
        "mailing_month": mailing_month,
    }


def setup_manifested_wave(**kwargs):
    """setup_wave_ready + manifest. Context's "wave" is the MANIFESTED wave
    and "items" lists the created mailing items."""
    ctx = setup_wave_ready(**kwargs)
    ctx["wave"] = manifest_wave(ctx["wave"]["id"])
    ctx["items"] = list_wave_items(ctx["wave"]["id"])
    return ctx


def setup_reconciled_wave(**kwargs):
    """setup_manifested_wave + reconcile. Adds "invoices": DRAFT invoices
    created for affiliates with billable items (PRD §3.7-3.8)."""
    ctx = setup_manifested_wave(**kwargs)
    ctx["wave"] = reconcile_wave(ctx["wave"]["id"])
    ctx["items"] = list_wave_items(ctx["wave"]["id"])
    ctx["invoices"] = get_wave_invoices(ctx["wave"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: invoicing lifecycle
# ---------------------------------------------------------------------------
def setup_issued_invoice(**kwargs):
    """Full lifecycle through reconcile plus issuing the wave's invoice.
    Adds "invoice" (ISSUED) to the reconciled-wave context."""
    ctx = setup_reconciled_wave(**kwargs)
    if not ctx["invoices"]:
        raise AssertionError("Setup failed: reconcile produced no invoice to issue")
    ctx["invoice"] = issue_invoice(ctx["invoices"][0]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Read-side lookup helpers (used to navigate manifest/reconcile results)
# ---------------------------------------------------------------------------
def list_wave_items(wave_id):
    """All mailing items of a wave (any status), as a list of dicts."""
    resp = api_client.list_items(_ADMIN, params={"wave_id": wave_id, "limit": 100})
    data, _meta = validate_paginated(resp)
    return data


def get_child_wave_item(wave_id, child_id):
    """The single mailing item for (wave, child); duplicate prevention makes
    the pair unique (PRD §3.7). Fails setup if absent or ambiguous."""
    resp = api_client.list_items(
        _ADMIN, params={"wave_id": wave_id, "child_id": child_id, "limit": 100}
    )
    data, _meta = validate_paginated(resp)
    if len(data) != 1:
        raise AssertionError(
            f"Setup failed: expected exactly 1 item for wave {wave_id} / child "
            f"{child_id}, got {len(data)}"
        )
    return data[0]


def get_wave_invoices(wave_id):
    """All invoices of a wave, as a list of dicts."""
    resp = api_client.list_invoices(_ADMIN, params={"wave_id": wave_id, "limit": 100})
    data, _meta = validate_paginated(resp)
    return data


def get_wave_invoice(wave_id):
    """The wave's single invoice. Fails setup if the count is not 1."""
    invoices = get_wave_invoices(wave_id)
    if len(invoices) != 1:
        raise AssertionError(
            f"Setup failed: expected exactly 1 invoice for wave {wave_id}, "
            f"got {len(invoices)}"
        )
    return invoices[0]


def get_affiliate(affiliate_id):
    """Fresh read of an affiliate (operative / enrolled_count / version)."""
    return _ok(api_client.get_affiliate(affiliate_id, _ADMIN), f"get affiliate {affiliate_id}")


def get_child(child_id):
    """Fresh read of a child."""
    return _ok(api_client.get_child(child_id, _ADMIN), f"get child {child_id}")


__all__ = [
    "add_months",
    "set_logical_clock",
    "create_state_program",
    "create_affiliate",
    "create_agreement",
    "approve_agreement",
    "reject_agreement",
    "create_population_stat",
    "create_title",
    "propose_selection",
    "approve_selection",
    "reopen_selection",
    "create_print_order",
    "confirm_print_order",
    "register_child",
    "create_address_change",
    "decide_address_change",
    "create_wave",
    "manifest_wave",
    "reconcile_wave",
    "mark_item_returned",
    "issue_invoice",
    "pay_invoice",
    "open_invoice_dispute",
    "resolve_dispute_overruled",
    "resolve_dispute_upheld",
    "setup_operative_affiliate",
    "setup_second_affiliate",
    "setup_five_titles",
    "setup_approved_selection",
    "setup_locked_selection",
    "setup_month_supply",
    "register_children",
    "setup_wave_ready",
    "setup_manifested_wave",
    "setup_reconciled_wave",
    "setup_issued_invoice",
    "list_wave_items",
    "get_child_wave_item",
    "get_wave_invoices",
    "get_wave_invoice",
    "get_affiliate",
    "get_child",
]
