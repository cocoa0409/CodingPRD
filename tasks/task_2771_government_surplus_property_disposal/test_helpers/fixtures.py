"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints only —
each test starts against an empty database. Setup calls go through the lenient
``get_success_data`` so a broken precondition reports as a setup failure rather
than as a confusing assertion mismatch.

Identity threading: the two roles the PRD resolves against a stored row —
AgencyOfficer against Agency.id and Bidder against Bidder.id — always get their
headers from ``make_agency_officer_headers`` / ``make_bidder_headers`` with the
real row id, never from the shared header constants.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH, TEST_DEFAULTS
from .factories import (
    create_agency_payload,
    create_asset_payload,
    create_auction_lot_payload,
    create_bid_payload,
    create_bidder_payload,
    create_clearance_certificate_payload,
    create_condition_assessment_payload,
    create_it_asset_payload,
    create_proceeds_distribution_payload,
    create_restricted_asset_payload,
    create_screening_cycle_payload,
    create_screening_request_payload,
    create_transfer_order_payload,
    create_turn_in_payload,
    create_venue_payload,
    create_vehicle_asset_payload,
)
from .test_users import (
    ASSESSOR_USER_ID,
    FINANCE_USER_ID,
    OFFICER_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    make_agency_officer_headers,
    make_bidder_headers,
    make_clearance_technician_headers,
    make_disposal_officer_headers,
    make_finance_controller_headers,
    make_surplus_assessor_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["disposal_officer_headers"]
ASSESSOR = TEST_USERS["surplus_assessor_headers"]
TECHNICIAN = TEST_USERS["clearance_technician_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


# ─── Tier 1: logical clock and registry rows ──────────────────────────────

def set_clock(current_utc: str = CLOCK_EPOCH, headers: Optional[Dict] = None) -> None:
    """Move the logical clock. Open to every role; driven here as ProgramAdmin."""
    get_success_data(api_client.set_current_utc(current_utc, headers or ADMIN))


def register_agency(**overrides) -> dict:
    """Create one organization. Returns the Agency row."""
    payload = create_agency_payload(**overrides)
    return get_success_data(api_client.create_agency(payload, ADMIN))


def register_state_agency(**overrides) -> dict:
    defaults = {
        "name": "State Department of Transportation",
        "agency_code": "DOT-01",
        "agency_type": "STATE_AGENCY",
    }
    defaults.update(overrides)
    return register_agency(**defaults)


def register_local_government(**overrides) -> dict:
    defaults = {
        "name": "City of Cedar Park",
        "agency_code": "CITY-77",
        "agency_type": "LOCAL_GOVERNMENT",
    }
    defaults.update(overrides)
    return register_agency(**defaults)


def register_nonprofit(**overrides) -> dict:
    """An ELIGIBLE_NONPROFIT. Transfers to nonprofits need a CERTIFIED donee
    status with an unexpired certification date, so that is the default here."""
    defaults = {
        "name": "Hill Country Food Relief",
        "agency_code": "NPO-12",
        "agency_type": "ELIGIBLE_NONPROFIT",
        "federal_donee_status": "CERTIFIED",
        "donee_certification_expires_on": "2027-06-30",
    }
    defaults.update(overrides)
    return register_agency(**defaults)


def suspend_agency(agency_id: str) -> dict:
    return get_success_data(api_client.set_agency_status(agency_id, "SUSPENDED", ADMIN))


def register_venue(**overrides) -> dict:
    payload = create_venue_payload(**overrides)
    return get_success_data(api_client.create_venue(payload, ADMIN))


def close_venue(venue_id: str) -> dict:
    return get_success_data(api_client.set_venue_status(venue_id, "CLOSED", ADMIN))


def register_bidder(
    status: str = "REGISTERED",
    deposit_cents: Optional[int] = None,
    end_use_certificate_expires_on: Optional[str] = None,
    **overrides,
) -> dict:
    """Create a bidder and walk it to ``status``. A bidder starts PENDING; only a
    REGISTERED bidder may lodge a deposit, so deposits are recorded after the
    status walk and before any later suspension.
    """
    bidder = get_success_data(
        api_client.create_bidder(create_bidder_payload(**overrides), ADMIN)
    )
    bidder_id = bidder["id"]
    if status != "PENDING":
        bidder = get_success_data(
            api_client.set_bidder_status(bidder_id, "REGISTERED", ADMIN)
        )
    if end_use_certificate_expires_on is not None:
        bidder = get_success_data(
            api_client.set_bidder_end_use_certificate(
                bidder_id, end_use_certificate_expires_on, ADMIN
            )
        )
    if deposit_cents:
        bidder = get_success_data(
            api_client.record_deposit(
                bidder_id, deposit_cents, make_bidder_headers(bidder_id)
            )
        )
    if status not in ("PENDING", "REGISTERED"):
        bidder = get_success_data(
            api_client.set_bidder_status(bidder_id, status, ADMIN)
        )
    return bidder


def lodge_deposit(bidder_id: str, amount_cents: int) -> dict:
    """Record a deposit as the bidder itself, which the PRD scopes to its own row."""
    return get_success_data(
        api_client.record_deposit(
            bidder_id, amount_cents, make_bidder_headers(bidder_id)
        )
    )


# ─── Tier 2: turn-in and asset hierarchy ──────────────────────────────────

def create_draft_turn_in(agency_id: str, **overrides) -> dict:
    payload = create_turn_in_payload(agency_id, **overrides)
    return get_success_data(
        api_client.create_turn_in(payload, make_agency_officer_headers(agency_id))
    )


def add_asset(agency_id: str, turn_in_id: str, **overrides) -> dict:
    """Add one asset to a DRAFT turn-in, filed by the turning-in organization."""
    payload = create_asset_payload(turn_in_id, **overrides)
    return get_success_data(
        api_client.create_asset(payload, make_agency_officer_headers(agency_id))
    )


def add_asset_with_payload(agency_id: str, payload: dict) -> dict:
    return get_success_data(
        api_client.create_asset(payload, make_agency_officer_headers(agency_id))
    )


def submit_turn_in(agency_id: str, turn_in_id: str) -> dict:
    return get_success_data(
        api_client.submit_turn_in(turn_in_id, make_agency_officer_headers(agency_id))
    )


def assess_asset(
    asset_id: str,
    expected_asset_version: int,
    assessor_user_id: str = ASSESSOR_USER_ID,
    **overrides,
) -> dict:
    """File one condition assessment. Returns the ConditionAssessment row."""
    payload = create_condition_assessment_payload(expected_asset_version, **overrides)
    return get_success_data(
        api_client.create_condition_assessment(
            asset_id, payload, make_surplus_assessor_headers(assessor_user_id)
        )
    )


def review_turn_in(
    turn_in_id: str, decision: str = "ACCEPT",
    officer_user_id: str = OFFICER_USER_ID, **overrides,
) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(
        api_client.review_turn_in(
            turn_in_id, payload, make_disposal_officer_headers(officer_user_id)
        )
    )


def read_asset(asset_id: str) -> dict:
    return get_success_data(api_client.get_asset(asset_id, OFFICER))


def read_turn_in(turn_in_id: str, agency_id: Optional[str] = None) -> dict:
    headers = make_agency_officer_headers(agency_id) if agency_id else OFFICER
    return get_success_data(api_client.get_turn_in(turn_in_id, headers))


def read_agency(agency_id: str) -> dict:
    return get_success_data(api_client.get_agency(agency_id, ADMIN))


def read_venue(venue_id: str) -> dict:
    return get_success_data(api_client.get_venue(venue_id, ADMIN))


def read_bidder(bidder_id: str) -> dict:
    return get_success_data(api_client.get_bidder(bidder_id, ADMIN))


def read_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_auction_lot(lot_id, OFFICER))


def read_cycle(cycle_id: str) -> dict:
    return get_success_data(api_client.get_screening_cycle(cycle_id, OFFICER))


def read_request(request_id: str) -> dict:
    return get_success_data(api_client.get_screening_request(request_id, OFFICER))


def read_transfer_order(order_id: str) -> dict:
    return get_success_data(api_client.get_transfer_order(order_id, OFFICER))


def read_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_sale_invoice(invoice_id, FINANCE))


def read_distribution(distribution_id: str) -> dict:
    return get_success_data(api_client.get_proceeds_distribution(distribution_id, FINANCE))


def find_invoice_for_lot(lot_id: str) -> Optional[dict]:
    """The close cascade issues the invoice; tests locate it by its lot."""
    body = get_success_data(
        api_client.list_sale_invoices(FINANCE, params={"auction_lot_id": lot_id})
    )
    rows = body if isinstance(body, list) else []
    return rows[0] if rows else None


def list_lot_bids(lot_id: str) -> List[dict]:
    body = get_success_data(api_client.list_lot_bids(lot_id, OFFICER))
    return body if isinstance(body, list) else []


# ─── Tier 3: asset lifecycle shortcuts ────────────────────────────────────

ASSET_BUILDERS = {
    "furniture": create_asset_payload,
    "vehicle": create_vehicle_asset_payload,
    "it_equipment": create_it_asset_payload,
    "heavy_equipment": lambda turn_in_id, **kw: {
        **{
            "turn_in_id": turn_in_id,
            "category": "HEAVY_EQUIPMENT",
            "description": "Nine-ton vibratory road roller",
            "acquisition_cost_cents": TEST_DEFAULTS["ROLLER_COST_CENTS"],
            "acquisition_date": TEST_DEFAULTS["ROLLER_ACQUISITION_DATE"],
        },
        **kw,
    },
    "restricted": create_restricted_asset_payload,
}

# Assessments chosen so each canonical asset lands on a known fair market value.
DEFAULT_ASSESSMENTS = {
    # 3217467 depreciated to 2019 vintage, C4, functional, less 185000 repair.
    "vehicle": {
        "condition_code": "C4", "functional": True,
        "repair_cost_estimate_cents": 185000, "assessed_on": "2026-07-28",
    },
    # 104500 at C6 functional -> 12540, below the de minimis screening threshold.
    "furniture": {
        "condition_code": "C6", "functional": True,
        "repair_cost_estimate_cents": 0, "assessed_on": "2026-07-30",
    },
    # 1449920 at C2 functional -> 985946.
    "it_equipment": {
        "condition_code": "C2", "functional": True,
        "repair_cost_estimate_cents": 0, "assessed_on": "2026-07-30",
    },
    # 870401 at C5 non-functional -> 62669.
    "heavy_equipment": {
        "condition_code": "C5", "functional": False,
        "repair_cost_estimate_cents": 0, "assessed_on": "2026-07-30",
    },
    "restricted": {
        "condition_code": "C5", "functional": False,
        "repair_cost_estimate_cents": 0, "assessed_on": "2026-07-30",
    },
}


def build_asset_payload(kind: str, turn_in_id: str, **overrides) -> dict:
    builder = ASSET_BUILDERS[kind]
    return builder(turn_in_id, **overrides)


def setup_assessed_assets(
    specs: List[dict],
    clock: str = CLOCK_EPOCH,
    agency_overrides: Optional[dict] = None,
    accept: bool = True,
    assessor_user_id: str = ASSESSOR_USER_ID,
    officer_user_id: str = OFFICER_USER_ID,
) -> dict:
    """Walk one organization's turn-in from DRAFT to ACCEPTED with every asset
    appraised.

    ``specs`` is a list of ``{"kind": ..., "overrides": {...},
    "assessment": {...} | None}`` entries. ``assessment: None`` leaves the asset
    unappraised, which is what a turn-in acceptance test needs.

    Returns ``{"agency", "officer_headers", "turn_in", "assets", "assessments"}``
    where ``assets`` holds the freshly re-read asset rows.
    """
    set_clock(clock)
    agency = register_state_agency(**(agency_overrides or {}))
    officer_headers = make_agency_officer_headers(agency["id"])
    turn_in = create_draft_turn_in(agency["id"])

    created = []
    for spec in specs:
        payload = build_asset_payload(
            spec.get("kind", "furniture"), turn_in["id"], **spec.get("overrides", {})
        )
        created.append(add_asset_with_payload(agency["id"], payload))

    submit_turn_in(agency["id"], turn_in["id"])

    assessments = []
    for spec, asset in zip(specs, created):
        overrides = spec.get("assessment", "default")
        if overrides is None:
            assessments.append(None)
            continue
        if overrides == "default":
            overrides = DEFAULT_ASSESSMENTS[spec.get("kind", "furniture")]
        assessments.append(
            assess_asset(
                asset["id"], asset["version"],
                assessor_user_id=assessor_user_id, **overrides,
            )
        )

    if accept:
        review_turn_in(turn_in["id"], "ACCEPT", officer_user_id=officer_user_id)

    return {
        "clock": clock,
        "agency": agency,
        "officer_headers": officer_headers,
        "turn_in": read_turn_in(turn_in["id"], agency["id"]),
        "assets": [read_asset(a["id"]) for a in created],
        "assessments": assessments,
    }


def setup_assessed_asset(
    kind: str = "furniture",
    asset_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    clock: str = CLOCK_EPOCH,
    agency_overrides: Optional[dict] = None,
    accept: bool = True,
    assessor_user_id: str = ASSESSOR_USER_ID,
) -> dict:
    """One appraised asset on one ACCEPTED turn-in. Adds an ``asset`` key holding
    the single asset row."""
    assessment = dict(DEFAULT_ASSESSMENTS[kind])
    assessment.update(assessment_overrides or {})
    scenario = setup_assessed_assets(
        [{
            "kind": kind,
            "overrides": asset_overrides or {},
            "assessment": assessment,
        }],
        clock=clock,
        agency_overrides=agency_overrides,
        accept=accept,
        assessor_user_id=assessor_user_id,
    )
    scenario["asset"] = scenario["assets"][0]
    scenario["assessment"] = scenario["assessments"][0]
    return scenario


# ─── Screening ladder shortcuts (PRD §3.4) ────────────────────────────────

def open_screening_cycle(asset_id: str, **overrides) -> dict:
    payload = create_screening_cycle_payload(asset_id, **overrides)
    return get_success_data(api_client.create_screening_cycle(payload, OFFICER))


def advance_tier(cycle_id: str, times: int = 1) -> dict:
    cycle = None
    for _ in range(times):
        cycle = get_success_data(api_client.advance_screening_tier(cycle_id, OFFICER))
    return cycle if cycle is not None else read_cycle(cycle_id)


def file_screening_request(
    cycle_id: str, requesting_agency_id: str, **overrides
) -> dict:
    """Filed by the requesting organization's own officer."""
    payload = create_screening_request_payload(
        cycle_id, requesting_agency_id, **overrides
    )
    return get_success_data(
        api_client.create_screening_request(
            payload, make_agency_officer_headers(requesting_agency_id)
        )
    )


def setup_screened_asset_at_tier(
    tier: str = "LOCAL_GOVERNMENT",
    kind: str = "vehicle",
    tier_window_days: int = 5,
    clock: str = CLOCK_EPOCH,
    asset_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
) -> dict:
    """An ASSESSED asset pushed into SCREENING and advanced until the cycle's
    current_tier is ``tier``. Advancing with no open requests is permitted at any
    point inside the window, so the walk needs no clock movement.
    """
    order = [
        "STATE_AGENCY", "LOCAL_GOVERNMENT", "ELIGIBLE_NONPROFIT", "PUBLIC_SALE",
    ]
    scenario = setup_assessed_asset(
        kind=kind, asset_overrides=asset_overrides,
        assessment_overrides=assessment_overrides, clock=clock,
    )
    cycle = open_screening_cycle(
        scenario["asset"]["id"], opens_at=clock, tier_window_days=tier_window_days
    )
    steps = order.index(tier)
    if steps:
        cycle = advance_tier(cycle["id"], steps)
    scenario["cycle"] = read_cycle(cycle["id"])
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    return scenario


def setup_auction_eligible_asset(
    kind: str = "vehicle",
    tier_window_days: int = 5,
    clock: str = CLOCK_EPOCH,
    asset_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
) -> dict:
    """An asset carried through all four screening tiers so the exhausted cycle
    leaves it AUCTION_ELIGIBLE."""
    scenario = setup_assessed_asset(
        kind=kind, asset_overrides=asset_overrides,
        assessment_overrides=assessment_overrides, clock=clock,
    )
    cycle = open_screening_cycle(
        scenario["asset"]["id"], opens_at=clock, tier_window_days=tier_window_days
    )
    advance_tier(cycle["id"], 4)
    scenario["cycle"] = read_cycle(cycle["id"])
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    return scenario


def setup_awarded_transfer_candidate(
    recipient_kind: str = "local_government",
    kind: str = "vehicle",
    tier_window_days: int = 5,
    clock: str = CLOCK_EPOCH,
    asset_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
    recipient_overrides: Optional[dict] = None,
) -> dict:
    """An asset whose screening cycle awarded a recipient's request, leaving the
    asset AWARDED_TRANSFER and the request APPROVED.

    ``recipient_kind`` picks the tier the cycle must be standing on, because the
    PRD admits a request only from an organization whose agency_type equals the
    cycle's current_tier.
    """
    tier_for = {
        "state_agency": "STATE_AGENCY",
        "local_government": "LOCAL_GOVERNMENT",
        "nonprofit": "ELIGIBLE_NONPROFIT",
    }
    tier = tier_for[recipient_kind]
    scenario = setup_screened_asset_at_tier(
        tier=tier, kind=kind, tier_window_days=tier_window_days, clock=clock,
        asset_overrides=asset_overrides, assessment_overrides=assessment_overrides,
    )
    if recipient_kind == "state_agency":
        recipient = register_agency(
            **{
                "name": "Department of Public Safety",
                "agency_code": "DPS-02",
                "agency_type": "STATE_AGENCY",
                **(recipient_overrides or {}),
            }
        )
    elif recipient_kind == "local_government":
        recipient = register_local_government(**(recipient_overrides or {}))
    else:
        recipient = register_nonprofit(**(recipient_overrides or {}))

    request = file_screening_request(scenario["cycle"]["id"], recipient["id"])
    get_success_data(
        api_client.award_screening_cycle(
            scenario["cycle"]["id"], request["id"], OFFICER
        )
    )
    scenario["recipient"] = read_agency(recipient["id"])
    scenario["request"] = read_request(request["id"])
    scenario["cycle"] = read_cycle(scenario["cycle"]["id"])
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    return scenario


def setup_issued_transfer_order(**kwargs) -> dict:
    """As above, then issue the transfer order (status ISSUED)."""
    scenario = setup_awarded_transfer_candidate(**kwargs)
    order = get_success_data(
        api_client.create_transfer_order(
            create_transfer_order_payload(
                scenario["asset"]["id"], scenario["recipient"]["id"],
                scenario["request"]["id"],
            ),
            OFFICER,
        )
    )
    scenario["transfer_order"] = order
    return scenario


def setup_acknowledged_transfer_order(**kwargs) -> dict:
    """As above, then acknowledge as the recipient organization's own officer."""
    scenario = setup_issued_transfer_order(**kwargs)
    get_success_data(
        api_client.acknowledge_transfer_order(
            scenario["transfer_order"]["id"],
            make_agency_officer_headers(scenario["recipient"]["id"]),
        )
    )
    scenario["transfer_order"] = read_transfer_order(scenario["transfer_order"]["id"])
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    return scenario


# ─── Tier 4: auction, bidding and invoicing (PRD §3.6–§3.7) ───────────────

def create_lot(asset_id: str, venue_id: str, **overrides) -> dict:
    payload = create_auction_lot_payload(asset_id, venue_id, **overrides)
    return get_success_data(api_client.create_auction_lot(payload, OFFICER))


def setup_listed_lot(
    kind: str = "furniture",
    route: str = "de_minimis",
    clock: str = CLOCK_EPOCH,
    opens_at: str = "2026-09-01T00:00:00Z",
    closes_at: str = "2026-09-05T00:00:00Z",
    lot_overrides: Optional[dict] = None,
    venue_overrides: Optional[dict] = None,
    asset_overrides: Optional[dict] = None,
    assessment_overrides: Optional[dict] = None,
) -> dict:
    """One DRAFT lot with its asset LISTED.

    ``route="de_minimis"`` relies on the PRD's exemption for an asset whose fair
    market value falls below the screening threshold, which may be listed
    straight out of ASSESSED. ``route="screening"`` carries the asset through all
    four tiers to AUCTION_ELIGIBLE first.
    """
    if route == "de_minimis":
        scenario = setup_assessed_asset(
            kind=kind, asset_overrides=asset_overrides,
            assessment_overrides=assessment_overrides, clock=clock,
        )
    else:
        scenario = setup_auction_eligible_asset(
            kind=kind, clock=clock, asset_overrides=asset_overrides,
            assessment_overrides=assessment_overrides,
        )
    venue = register_venue(**(venue_overrides or {}))
    lot = create_lot(
        scenario["asset"]["id"], venue["id"],
        opens_at=opens_at, closes_at=closes_at, **(lot_overrides or {}),
    )
    scenario["venue"] = read_venue(venue["id"])
    scenario["lot"] = lot
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    return scenario


def setup_open_lot(**kwargs) -> dict:
    """As ``setup_listed_lot``, then move the clock to the lot's opens_at and open
    it, because the PRD admits the open only inside the lot's window."""
    scenario = setup_listed_lot(**kwargs)
    set_clock(scenario["lot"]["opens_at"])
    lot = get_success_data(
        api_client.open_auction_lot(scenario["lot"]["id"], OFFICER)
    )
    scenario["lot"] = lot
    scenario["clock"] = scenario["lot"]["opens_at"]
    return scenario


def place_bid(lot_id: str, bidder_id: str, amount_cents: int) -> dict:
    """Bid as the bidder itself, whose X-User-ID must be its own row id."""
    return get_success_data(
        api_client.place_bid(
            lot_id,
            create_bid_payload(bidder_id, amount_cents),
            make_bidder_headers(bidder_id),
        )
    )


def setup_open_lot_with_bidder(
    deposit_cents: Optional[int] = None,
    bidder_status: str = "REGISTERED",
    end_use_certificate_expires_on: Optional[str] = None,
    bidder_overrides: Optional[dict] = None,
    **kwargs,
) -> dict:
    """An OPEN lot plus a bidder positioned to bid on it."""
    scenario = setup_open_lot(**kwargs)
    scenario["bidder"] = register_bidder(
        status=bidder_status,
        deposit_cents=deposit_cents,
        end_use_certificate_expires_on=end_use_certificate_expires_on,
        **(bidder_overrides or {}),
    )
    return scenario


def setup_lot_with_active_bid(
    bid_amount_cents: int,
    deposit_cents: Optional[int] = None,
    **kwargs,
) -> dict:
    """An OPEN lot carrying one ACTIVE bid."""
    scenario = setup_open_lot_with_bidder(deposit_cents=deposit_cents, **kwargs)
    scenario["bid"] = place_bid(
        scenario["lot"]["id"], scenario["bidder"]["id"], bid_amount_cents
    )
    scenario["lot"] = read_lot(scenario["lot"]["id"])
    scenario["bidder"] = read_bidder(scenario["bidder"]["id"])
    return scenario


def setup_closed_met_lot(
    bid_amount_cents: int = 250000,
    deposit_cents: Optional[int] = None,
    officer_user_id: str = OFFICER_USER_ID,
    **kwargs,
) -> dict:
    """A lot closed with the reserve met: the winning bid, the issued invoice and
    the asset at SOLD. The close is driven by ``officer_user_id`` so a
    segregation-of-duties test can choose who is recorded as closing the lot."""
    scenario = setup_lot_with_active_bid(
        bid_amount_cents=bid_amount_cents, deposit_cents=deposit_cents, **kwargs
    )
    set_clock(scenario["lot"]["closes_at"])
    lot = get_success_data(
        api_client.close_auction_lot(
            scenario["lot"]["id"], make_disposal_officer_headers(officer_user_id)
        )
    )
    scenario["lot"] = lot
    scenario["clock"] = lot["closes_at"]
    scenario["invoice"] = find_invoice_for_lot(lot["id"])
    scenario["bid"] = list_lot_bids(lot["id"])[0] if list_lot_bids(lot["id"]) else None
    scenario["bidder"] = read_bidder(scenario["bidder"]["id"])
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    return scenario


def setup_closed_no_sale_lot(
    officer_user_id: str = OFFICER_USER_ID, **kwargs
) -> dict:
    """A lot closed with no qualifying bid: no invoice, and the asset returned to
    AUCTION_ELIGIBLE."""
    scenario = setup_open_lot(**kwargs)
    set_clock(scenario["lot"]["closes_at"])
    lot = get_success_data(
        api_client.close_auction_lot(
            scenario["lot"]["id"], make_disposal_officer_headers(officer_user_id)
        )
    )
    scenario["lot"] = lot
    scenario["clock"] = lot["closes_at"]
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    return scenario


def pay_invoice(
    invoice_id: str, bidder_id: str, amount_cents: int,
    use_deposit: Optional[bool] = None,
) -> dict:
    payload = {"amount_cents": amount_cents}
    if use_deposit is not None:
        payload["use_deposit"] = use_deposit
    return get_success_data(
        api_client.pay_sale_invoice(
            invoice_id, payload, make_bidder_headers(bidder_id)
        )
    )


def setup_settled_lot(bid_amount_cents: int = 250000, **kwargs) -> dict:
    """A lot whose invoice is paid in full, moving the lot to SETTLED."""
    scenario = setup_closed_met_lot(bid_amount_cents=bid_amount_cents, **kwargs)
    invoice = scenario["invoice"]
    pay_invoice(
        invoice["id"], scenario["bidder"]["id"], invoice["balance_due_cents"]
    )
    scenario["invoice"] = read_invoice(invoice["id"])
    scenario["lot"] = read_lot(scenario["lot"]["id"])
    scenario["asset"] = read_asset(scenario["asset"]["id"])
    scenario["bidder"] = read_bidder(scenario["bidder"]["id"])
    return scenario


# ─── Tier 5: clearance, release and proceeds (PRD §3.8–§3.9) ─────────────

def certify_clearance(
    asset_id: str,
    technician_user_id: str = TECHNICIAN_USER_ID,
    **overrides,
) -> dict:
    """File one clearance certificate. The technician must differ from every
    assessor on the asset, so the caller may choose the technician identity."""
    payload = create_clearance_certificate_payload(**overrides)
    return get_success_data(
        api_client.create_clearance_certificate(
            asset_id, payload, make_clearance_technician_headers(technician_user_id)
        )
    )


def release_asset(asset_id: str, **payload) -> dict:
    return get_success_data(api_client.release_asset(asset_id, payload, OFFICER))


def calculate_distribution(
    lot_id: str, expected_auction_lot_version: int, basis: str = "ACCRUAL",
    finance_user_id: str = FINANCE_USER_ID,
) -> dict:
    payload = create_proceeds_distribution_payload(
        lot_id, expected_auction_lot_version, basis
    )
    return get_success_data(
        api_client.create_proceeds_distribution(
            payload, make_finance_controller_headers(finance_user_id)
        )
    )


def post_distribution(
    distribution_id: str, finance_user_id: str = FINANCE_USER_ID
) -> dict:
    return get_success_data(
        api_client.post_proceeds_distribution(
            distribution_id, make_finance_controller_headers(finance_user_id)
        )
    )


def setup_calculated_distribution(
    basis: str = "ACCRUAL",
    bid_amount_cents: int = 250000,
    finance_user_id: str = FINANCE_USER_ID,
    **kwargs,
) -> dict:
    """A CLOSED_MET lot with one CALCULATED distribution against it."""
    scenario = setup_closed_met_lot(bid_amount_cents=bid_amount_cents, **kwargs)
    scenario["distribution"] = calculate_distribution(
        scenario["lot"]["id"], scenario["lot"]["version"], basis,
        finance_user_id=finance_user_id,
    )
    scenario["lot"] = read_lot(scenario["lot"]["id"])
    return scenario


def setup_posted_distribution(
    basis: str = "ACCRUAL",
    finance_user_id: str = FINANCE_USER_ID,
    **kwargs,
) -> dict:
    """A posted distribution, with the beneficiary organization's ledger credited.

    The posting controller must differ from whoever closed the lot, so the close
    stays with the default disposal officer while the posting uses the finance
    identity supplied here.
    """
    scenario = setup_calculated_distribution(
        basis=basis, finance_user_id=finance_user_id, **kwargs
    )
    post_distribution(scenario["distribution"]["id"], finance_user_id)
    scenario["distribution"] = read_distribution(scenario["distribution"]["id"])
    scenario["agency"] = read_agency(scenario["agency"]["id"])
    return scenario
