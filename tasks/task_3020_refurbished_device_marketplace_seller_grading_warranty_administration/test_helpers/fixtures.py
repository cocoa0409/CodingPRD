"""Composite setup helpers.

Each helper drives the API from an empty database to the state a test needs.
All of them use the lenient setup validator so a broken precondition surfaces
as a clear "Setup step failed" rather than a confusing assertion error, and all
ownership-gated calls carry the seller row's id as the acting Seller identity.
"""
from .api_client import api_client
from .constants import (
    COUNTERFEIT_DEVICE_BLOCKLIST,
    DEFAULT_CLOCK,
    MODEL_CATALOG,
    MODEL_CATALOG_FLOOR_CENTS,
    STOLEN_DEVICE_BLOCKLIST,
)
from .factories import (
    EVIDENCE_DIGEST,
    audit_transition_payload,
    blocklist_payload,
    model_catalog_floor,
    next_imei,
    create_audit_record_payload,
    create_grading_definition_payload,
    create_listing_payload,
    create_reservation_payload,
    create_seller_payload,
    create_verification_payload,
    disclose_verification_payload,
    evidence_payload,
    file_claim_payload,
    adjudicate_payload,
    route_return_payload,
    service_score_payload,
)
from .test_users import (
    TEST_USERS,
    make_seller_headers,
)
from prd_bench_local_runner.testing import get_success_data, validate_paginated

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]
ADJUDICATOR = TEST_USERS["claim_adjudicator_headers"]
INSPECTOR = TEST_USERS["trade_in_inspector_headers"]
CONSUMER = TEST_USERS["consumer_headers"]
SYSTEM = TEST_USERS["system_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

# The most recent instant a test set the logical clock to.  The clock is not
# exposed on a read endpoint, and every fixture that books an audit sets the
# clock explicitly first, so this mirror is exact for defaulting purposes.
_LAST_CLOCK = [DEFAULT_CLOCK]


def _data(response, label):
    try:
        return get_success_data(response)
    except AssertionError as exc:  # pragma: no cover - diagnostics only
        raise AssertionError(f"{label}: {exc}") from exc


def set_clock(instant: str = DEFAULT_CLOCK):
    resp = api_client.set_clock(instant, ADMIN)
    assert 200 <= resp.status_code < 300, f"Setting the clock to {instant} failed: {resp.text}"
    _LAST_CLOCK[0] = instant
    return instant


# ---------------------------------------------------------------------------
# Seller onboarding
# ---------------------------------------------------------------------------

def bootstrap_marketplace():
    """File the marketplace's standing policy inputs through the API.

    PRD §3.2 makes an IMEI admissible only while it is absent from both
    blocklists and a submission admissible only while its `model_code` is in the
    supported-model catalog.  Those catalogs are operator-owned policy, not test
    entities: the harness files them through the declared catalogue endpoints so
    every test starts from the same marketplace configuration.
    """
    for model_code in sorted(MODEL_CATALOG):
        api_client.register_supported_model(
            {"model_code": model_code, "catalog_floor_cents": MODEL_CATALOG_FLOOR_CENTS.get(model_code, 0)},
            ADMIN,
        )
    for imei in sorted(STOLEN_DEVICE_BLOCKLIST):
        api_client.add_blocklist_entry("stolen", imei, ADMIN)
    for imei in sorted(COUNTERFEIT_DEVICE_BLOCKLIST):
        api_client.add_blocklist_entry("counterfeit", imei, ADMIN)


def register_seller(**overrides) -> dict:
    bootstrap_marketplace()
    return _data(api_client.create_seller(create_seller_payload(**overrides), ADMIN), "create seller")


def verify_seller(seller_id: str) -> dict:
    return _data(api_client.verify_documents(seller_id, REVIEWER), "verify documents")


def book_audit(seller_id: str, **overrides) -> dict:
    """Book the on-site audit, defaulting the visit to a date the clock admits.

    PRD §3.1: "The reviewer supplies `audit_scheduled_for`, the date the visit
    is booked for, which must be strictly later than the current logical clock
    instant".  Tests move the clock to many different instants, so the default
    visit date is derived from the clock actually in force rather than pinned
    to one calendar date.
    """
    if "audit_scheduled_for" not in overrides:
        overrides["audit_scheduled_for"] = _audit_visit_after_clock()
    return _data(
        api_client.create_audit_record(seller_id, create_audit_record_payload(**overrides), REVIEWER),
        "book audit",
    )


def _audit_visit_after_clock() -> str:
    """The current logical clock instant plus one day, ISO 8601 UTC."""
    from datetime import datetime, timedelta

    current = _LAST_CLOCK[0] or DEFAULT_CLOCK
    instant = datetime.strptime(current.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    return (instant + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_audit_outcome(audit_id: str, **overrides) -> dict:
    return _data(
        api_client.transition_audit_record(audit_id, audit_transition_payload(**overrides), REVIEWER),
        "record audit outcome",
    )


def create_approved_seller(clock: str = DEFAULT_CLOCK, **overrides) -> dict:
    """Register a seller and drive it through verify -> audit PASSED to APPROVED.

    Returns the SELLER row (re-read after the audit transition), because every
    caller uses its `id` as the acting Seller identity for ownership-gated
    calls; PRD §2.1: "When `X-User-Role` is `Seller`, `X-User-ID` is the `id`
    of the acting `Seller`".
    """
    set_clock(clock)
    seller = register_seller(**overrides)
    seller = verify_seller(seller["id"])
    audit = book_audit(seller["id"])
    record_audit_outcome(audit["id"])
    return _data(api_client.get_seller(seller["id"], ADMIN), "read approved seller")


def create_verified_seller(clock: str = DEFAULT_CLOCK, **overrides) -> dict:
    """Register and verify a seller but do not book or record an audit."""
    set_clock(clock)
    seller = register_seller(**overrides)
    return verify_seller(seller["id"])


def create_seller_in_audit(seller_id: str, **overrides) -> tuple:
    """Book an audit for an already-verified seller. Returns (seller, audit)."""
    audit = book_audit(seller_id, **overrides)
    seller = _data(api_client.get_seller(seller_id, ADMIN), "read seller")
    return seller, audit


# ---------------------------------------------------------------------------
# Grading definitions
# ---------------------------------------------------------------------------

def active_definition_or_none():
    """The ACTIVE grading definition, or None when the marketplace has none.

    PRD §2.6: publishing a definition — `DRAFT` to `ACTIVE` — sets its
    `binding_definition_id` to its own `id`, and a submission binds to whichever
    definition is `ACTIVE` at that instant.  Only one definition may be ACTIVE
    at a given `effective_from`, so a fixture that merely needs *a* binding
    reuses the one already published rather than opening a second.
    """
    rows, _ = validate_paginated(api_client.list_grading_definitions(ADMIN))
    for row in rows:
        if row["definition_state"] == "ACTIVE":
            return row
    return None


def create_active_definition(**overrides) -> dict:
    definition = _data(
        api_client.create_grading_definition(create_grading_definition_payload(**overrides), REVIEWER),
        "create grading definition",
    )
    return _data(
        api_client.activate_grading_definition(definition["id"], REVIEWER), "activate grading definition"
    )


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

def create_listing(seller_id: str, **overrides) -> dict:
    """Submit a listing for an approved seller; lands in UNDER_REVIEW."""
    return _data(
        api_client.create_listing(seller_id, create_listing_payload(**overrides), make_seller_headers(seller_id)),
        "create listing",
    )


def list_seller_listings(seller_id: str, params=None) -> tuple:
    return validate_paginated(api_client.list_seller_listings(seller_id, ADMIN, params))


def approve_listing(listing_id: str, reviewer_user_id: str = "op_reviewer") -> dict:
    return _data(
        api_client.review_listing(
            listing_id, {"decision": "APPROVED", "reviewer_user_id": reviewer_user_id}, REVIEWER
        ),
        "review listing",
    )


def reject_listing(listing_id: str, reviewer_user_id: str = "op_reviewer") -> dict:
    return _data(
        api_client.review_listing(
            listing_id, {"decision": "REJECTED", "reviewer_user_id": reviewer_user_id}, REVIEWER
        ),
        "review listing",
    )


def delist_listing(listing_id: str, reason_code: str = "BATTERY_DEGRADED", **overrides):
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return api_client.suspend_listing(listing_id, payload, REVIEWER)


def setup_listed_device(clock: str = DEFAULT_CLOCK, active_definition: bool = True, **listing_overrides) -> dict:
    """Approved seller + one LISTED device.

    Returns a dict with the seller, the definition (or None), the listing, the
    servicing reservation id and the reservation row created on approval.
    """
    set_clock(clock)
    definition = None
    if active_definition:
        definition = active_definition_or_none()
        if definition is None:
            definition = create_active_definition()
    seller = create_approved_seller(clock=clock)
    listing = create_listing(seller["id"], **listing_overrides)
    listed = approve_listing(listing["id"])
    reservations, _ = validate_paginated(
        api_client.list_listing_reservations(listed["id"], ADMIN)
    )
    return {
        "seller": seller,
        "definition": definition,
        "listing": listed,
        "servicing_reservation_id": listed.get("servicing_reservation_id"),
        "reservation": reservations[0] if reservations else None,
    }


def setup_second_listing(seller_id: str, **overrides) -> dict:
    """An extra listing for a seller that is already APPROVED."""
    return create_listing(seller_id, **overrides)


def withdraw_listing(listing_id: str, seller_id: str, reason: str = "seller requested removal"):
    return api_client.withdraw_listing(
        listing_id, {"withdrawal_reason": reason}, make_seller_headers(seller_id)
    )


def resubmit_listing(listing_id: str, seller_id: str, expected_seller_version: int):
    return api_client.submit_listing(
        listing_id,
        {"expected_seller_version": expected_seller_version},
        make_seller_headers(seller_id),
    )


def current_seller_version(seller_id: str) -> int:
    return _data(api_client.get_seller(seller_id, ADMIN), "read seller")["version"]


# ---------------------------------------------------------------------------
# Warranty claims
# ---------------------------------------------------------------------------

def file_claim(seller_id: str, listing_id: str, **overrides) -> dict:
    return _data(
        api_client.file_claim(seller_id, file_claim_payload(listing_id, **overrides), CONSUMER),
        "file claim",
    )


def attach_evidence(claim_id: str, digest: str = EVIDENCE_DIGEST):
    return api_client.attach_evidence(claim_id, evidence_payload(digest), ADJUDICATOR)


def uphold_claim(claim_id: str, **overrides):
    return api_client.adjudicate_claim(claim_id, adjudicate_payload(**overrides), ADJUDICATOR)


def reject_claim(claim_id: str):
    return api_client.adjudicate_claim(
        claim_id,
        {"decision": "REJECTED", "adjudicator_user_id": "op_adjudicator"},
        ADJUDICATOR,
    )


def route_claim_return(claim_id: str, expected_claim_version=None, **overrides):
    payload = route_return_payload(**overrides)
    if expected_claim_version is not None:
        payload["expected_claim_version"] = expected_claim_version
    return api_client.route_return(claim_id, payload, ADJUDICATOR)


def create_claim_under_review(seller_id: str, listing_id: str, **claim_overrides) -> dict:
    """File a claim and attach evidence so it rests in UNDER_REVIEW."""
    claim = file_claim(seller_id, listing_id, **claim_overrides)
    return _data(attach_evidence(claim["id"]), "attach evidence")


def create_upheld_claim(seller_id: str, listing_id: str, resolution_type: str = "REPAIR",
                        obligation_cents: int = 18000, **claim_overrides) -> dict:
    """File -> evidence -> uphold. Rests in APPROVED awaiting return routing."""
    claim = create_claim_under_review(seller_id, listing_id, **claim_overrides)
    return _data(
        uphold_claim(
            claim["id"], resolution_type=resolution_type, resolution_obligation_cents=obligation_cents
        ),
        "uphold claim",
    )


def create_resolved_claim(seller_id: str, listing_id: str, **route_overrides) -> dict:
    """File -> evidence -> uphold -> route-return. Rests in RESOLVED."""
    claim = create_upheld_claim(seller_id, listing_id)
    return _data(route_claim_return(claim["id"], **route_overrides), "route return")


def create_repairing_reservation(seller_id: str, listing_id: str, **route_overrides) -> dict:
    """Uphold a REPAIR claim and route it, leaving the servicing reservation REPAIRING."""
    create_resolved_claim(seller_id, listing_id, **route_overrides)
    reservations, _ = validate_paginated(api_client.list_listing_reservations(listing_id, ADMIN))
    return reservations[0]


def create_replaced_reservation(seller_id: str, listing_id: str, obligation_cents: int = 90000):
    """Uphold a REPLACE claim, leaving the servicing reservation REPLACED."""
    claim = create_upheld_claim(
        seller_id, listing_id, resolution_type="REPLACE", obligation_cents=obligation_cents
    )
    reservations, _ = validate_paginated(api_client.list_listing_reservations(listing_id, ADMIN))
    return claim, reservations[0]


def add_reservation(listing_id: str, **overrides) -> dict:
    return _data(
        api_client.create_reservation(listing_id, create_reservation_payload(**overrides), REVIEWER),
        "create reservation",
    )


def remediate_reservation(reservation_id: str, **overrides):
    payload = dict(overrides)
    return api_client.remediate_reservation(reservation_id, payload, ADJUDICATOR)


def get_exposure_floor(seller_id: str) -> dict:
    return _data(api_client.get_exposure_floor(seller_id, ADMIN), "read exposure floor")


def servicing_reservation(listing_id: str) -> dict:
    """The reservation PRD §3.5 ranks as the listing's current servicer.

    Approval already opens one reservation against the listing, so the selector
    — `activated_on` descending, `created_at` ascending — is applied here rather
    than assuming a single row exists.
    """
    rows, _ = validate_paginated(api_client.list_listing_reservations(listing_id, ADMIN))
    selectable = [row for row in rows if row["warranty_state"] in ("ACTIVE", "REPAIRING", "REPLACED")]
    assert selectable, "the listing must carry at least one selectable reservation"
    selectable.sort(key=lambda row: row["created_at"])
    selectable.sort(key=lambda row: row["activated_on"], reverse=True)
    return selectable[0]


# ---------------------------------------------------------------------------
# Mystery-shop verifications
# ---------------------------------------------------------------------------

# Successive default verification windows are shifted apart so that two
# opens against the same listing never strictly overlap (PRD §3.4).
_VERIFICATION_WINDOW_SEQ = [0]


def open_verification(seller_id: str, listing_id: str, **overrides):
    """Open a mystery-shop verification.

    When the caller names neither boundary, the fixture supplies a window that
    is disjoint from every earlier default window, because PRD §3.4 forbids
    strict overlap between two still-`OPEN` windows on one listing.
    """
    if "verification_start" not in overrides and "verification_end" not in overrides:
        from datetime import datetime, timedelta

        offset = _VERIFICATION_WINDOW_SEQ[0] * 14
        _VERIFICATION_WINDOW_SEQ[0] += 1
        base = datetime(2026, 9, 5) + timedelta(days=offset)
        overrides["verification_start"] = base.strftime("%Y-%m-%dT00:00:00Z")
        overrides["verification_end"] = (base + timedelta(days=5)).strftime("%Y-%m-%dT00:00:00Z")
    return api_client.create_verification(
        create_verification_payload(seller_id, listing_id, **overrides), REVIEWER
    )


def disclose_verification(verification_id: str, **overrides):
    return api_client.disclose_verification(
        verification_id, disclose_verification_payload(**overrides), REVIEWER
    )


def setup_disclosed_verification(seller_id: str, listing_id: str, **disclose_overrides):
    """Open a verification and disclose it, recording one violation unit."""
    verification = _data(
        open_verification(seller_id, listing_id), "open verification"
    )
    return _data(
        disclose_verification(verification["id"], **disclose_overrides), "disclose verification"
    )


# ---------------------------------------------------------------------------
# Service-score sections
# ---------------------------------------------------------------------------

def open_section(seller_id: str, section_opened_on: str = "2026-01-05T00:00:00Z") -> dict:
    return _data(
        api_client.create_service_score(
            service_score_payload(seller_id, section_opened_on=section_opened_on), ADMIN
        ),
        "open service-score section",
    )


def close_section(section_id: str, expected_seller_version: int):
    return api_client.close_service_score(
        section_id, {"expected_seller_version": expected_seller_version}, SYSTEM
    )


def read_section(section_id: str) -> dict:
    return _data(api_client.get_service_score(section_id, ADMIN), "read service score")


# ---------------------------------------------------------------------------
# Trade-in channel
# ---------------------------------------------------------------------------

def submit_trade_in(**overrides) -> dict:
    from .factories import trade_in_payload

    return _data(api_client.create_trade_in(trade_in_payload(**overrides), CONSUMER), "submit trade-in")


def inspect_trade_in(trade_in_id: str, **overrides):
    from .factories import inspection_payload

    return api_client.inspect_trade_in(trade_in_id, inspection_payload(**overrides), INSPECTOR)


def revise_trade_in(trade_in_id: str, payload=None):
    return api_client.revise_trade_in(trade_in_id, payload or {}, INSPECTOR)


def accept_trade_in(trade_in_id: str):
    return api_client.accept_trade_in(trade_in_id, CONSUMER)


def read_trade_in(trade_in_id: str) -> dict:
    return _data(api_client.get_trade_in(trade_in_id, ADMIN), "read trade-in")


# ---------------------------------------------------------------------------
# Scenario composites reused across concerns
# ---------------------------------------------------------------------------

def setup_scored_seller_with_section(clock: str = DEFAULT_CLOCK, section_opened_on: str = "2026-01-05T00:00:00Z"):
    """Approved seller + LISTED device + one OPEN section. Returns (seller, listing, section)."""
    scenario = setup_listed_device(clock=clock)
    section = open_section(scenario["seller"]["id"], section_opened_on=section_opened_on)
    return scenario, section


def setup_routed_claimed_listing(clock: str = DEFAULT_CLOCK, section_opened_on: str = None):
    """Approved seller + LISTED device + one section + one claim routed to the seller.

    Returns a dict with the seller, listing, section and claim.
    """
    scenario = setup_listed_device(clock=clock)
    section = open_section(scenario["seller"]["id"], section_opened_on=section_opened_on or "2026-01-05T00:00:00Z")
    claim = create_claim_under_review(scenario["seller"]["id"], scenario["listing"]["id"])
    scenario["section"] = section
    scenario["claim"] = claim
    return scenario