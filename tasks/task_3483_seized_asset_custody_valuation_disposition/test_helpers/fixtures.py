"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD endpoints only —
the harness restarts the server before every test, so each test starts against
an empty database with the logical clock at 2026-09-01T00:00:00Z. Setup calls
go through the lenient ``get_success_data`` so a broken precondition reports
as a setup failure rather than as a confusing assertion mismatch.

Identity threading: the Claimant role's X-User-ID must equal the interest's
petitioner_ref, so filings and appeals always go through
``make_claimant_headers(ref)``. The two segregation-of-duties pairs (ISR
requester vs adjudicator, distribution creator vs approver) are crossed by
passing distinct user ids, never by reusing one identity on both sides.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import create_api_client

# Module-local client instance; the api_client module itself stays importable
# as a plain module (no singleton shadowing its name).
_api = create_api_client()
from .constants import CLOCK_EPOCH, TEST_DEFAULTS, condition_adjusted_value
from .factories import (
    create_asset_payload,
    create_case_payload,
    create_custody_transfer_payload,
    create_distribution_payload,
    create_expense_entry_payload,
    create_innocent_owner_payload,
    create_isr_payload,
    create_lien_payload,
    create_sale_event_payload,
    create_valuation_payload,
    unique_petitioner_ref,
)
from .test_users import (
    ASSET_MANAGER_USER_ID,
    COURT_OFFICIAL_USER_ID,
    FUND_ADMINISTRATOR_USER_ID,
    SECOND_FUND_ADMINISTRATOR_USER_ID,
    TEST_USERS,
    make_asset_manager_headers,
    make_claimant_headers,
    make_court_official_headers,
    make_fund_administrator_headers,
)

# Shared role headers (all roles are opaque per PRD §2.1).
CASE_AGENT = TEST_USERS["case_agent_headers"]
COURT = TEST_USERS["court_official_headers"]
CUSTODIAN = TEST_USERS["asset_custodian_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
MANAGER = TEST_USERS["asset_manager_headers"]
AUCTIONEER = TEST_USERS["auction_coordinator_headers"]
FUND = TEST_USERS["fund_administrator_headers"]
FUND2 = TEST_USERS["second_fund_administrator_headers"]
SYSOP = TEST_USERS["system_operator_headers"]


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ─── Tier 0: logical clock and fresh reads ───────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_EPOCH) -> None:
    """Advance the logical clock (SystemOperator-only test-driving endpoint,
    mounted outside the business prefix)."""
    get_success_data(_api.set_clock(to_iso8601, SYSOP))


def get_asset(asset_id: str) -> dict:
    return get_success_data(_api.get_asset(asset_id, MANAGER))


def get_case(case_id: str) -> dict:
    return get_success_data(_api.get_case(case_id, MANAGER))


def fresh_asset_version(asset_id: str) -> int:
    """Re-read the asset and return its current version for OCC-guarded writes."""
    return get_asset(asset_id)["version"]


# ─── Tier 1: case lifecycle (PRD §3.1) ───────────────────────────────────────

def create_case(**overrides) -> dict:
    """Open a case. Returns the SeizureCase in status OPEN."""
    return get_success_data(_api.create_case(create_case_payload(**overrides),
                                                   CASE_AGENT))


def file_forfeiture(case_id: str) -> dict:
    return get_success_data(_api.file_forfeiture(case_id, CASE_AGENT))


def forfeit_case(case_id: str) -> dict:
    return get_success_data(_api.forfeit_case(case_id, COURT))


def dismiss_case(case_id: str) -> dict:
    return get_success_data(_api.dismiss_case(case_id, COURT))


def create_case_in_state(status: str = "OPEN", **overrides) -> dict:
    """Walk a fresh case to OPEN, FORFEITURE_PENDING, FORFEITED or DISMISSED.
    DISMISSED is reachable only while the case has no SOLD asset."""
    case = create_case(**overrides)
    if status == "OPEN":
        return case
    case = file_forfeiture(case["id"])
    if status == "FORFEITURE_PENDING":
        return case
    if status == "FORFEITED":
        return forfeit_case(case["id"])
    if status == "DISMISSED":
        return dismiss_case(case["id"])
    raise ValueError(f"Unknown case status {status!r}")


# ─── Tier 1: assets and the valuation pipeline (PRD §3.2, §3.3) ──────────────

def intake_asset(case_id: str, **overrides) -> dict:
    """Intake one asset. Returns it in (custody INTAKE, legal SEIZED)."""
    return get_success_data(
        _api.create_asset(create_asset_payload(case_id, **overrides),
                                CUSTODIAN)
    )


def submit_valuation(
    asset_id: str,
    method: str = "CERTIFIED_APPRAISAL",
    expected_asset_version: Optional[int] = None,
    **overrides,
) -> dict:
    """Submit a valuation (Appraiser-only, OCC-guarded). When the version is
    not supplied the asset is re-read so the guard always matches."""
    if expected_asset_version is None:
        expected_asset_version = fresh_asset_version(asset_id)
    payload = create_valuation_payload(
        asset_id, expected_asset_version, method=method, **overrides
    )
    return get_success_data(_api.create_valuation(payload, APPRAISER))


def accept_valuation(valuation_id: str) -> dict:
    return get_success_data(_api.adjudicate_valuation(valuation_id, "ACCEPT",
                                                            COURT))


def reject_valuation(valuation_id: str) -> dict:
    return get_success_data(_api.adjudicate_valuation(valuation_id, "REJECT",
                                                            COURT))


def create_valued_asset(
    case_id: str,
    raw_value_cents: int = 1_000_000,
    grade: str = "EXCELLENT",
    method: str = "CERTIFIED_APPRAISAL",
    **asset_overrides,
) -> Tuple[dict, dict]:
    """Intake + submit + accept. Returns (asset, valuation) with the asset
    re-read after acceptance: legal VALUED, appraised_value_cents set."""
    asset = intake_asset(case_id, **asset_overrides)
    valuation = submit_valuation(
        asset["id"], method=method, raw_value_cents=raw_value_cents,
        assessed_condition_grade=grade,
    )
    accept_valuation(valuation["id"])
    return get_asset(asset["id"]), valuation


# ─── Tier 1: expense ledger (PRD §3.4) ───────────────────────────────────────

def post_expense(
    asset_id: str,
    amount_cents: int,
    entry_kind: str = "COST",
    expense_type: str = "STORAGE",
    incurred_on: Optional[str] = None,
) -> dict:
    """Post one ledger entry. ``incurred_on=None`` lets the server default it
    to the current logical clock time."""
    overrides: dict = {"entry_kind": entry_kind, "expense_type": expense_type,
                       "amount_cents": amount_cents}
    if incurred_on is not None:
        overrides["incurred_on"] = incurred_on
    return get_success_data(
        _api.create_expense_entry(
            create_expense_entry_payload(asset_id, **overrides), CUSTODIAN
        )
    )


def post_accumulated_cost(
    asset_id: str, total_cents: int, expense_type: str = "STORAGE"
) -> dict:
    """Post a single COST entry building the accumulator to ``total_cents``."""
    return post_expense(asset_id, total_cents, entry_kind="COST",
                        expense_type=expense_type)


# ─── Tier 1: custody transfers (PRD §3.2) ────────────────────────────────────

def next_contiguous_window(asset_id: str, hours: int = 24) -> Tuple[str, str]:
    """The next lawful custody window for an asset: chained contiguously, the
    new window_start must equal the greatest window_end among the asset's
    non-CANCELLED transfers; the first transfer is exempt."""
    rows = get_success_data(
        _api.list_asset_custody_transfers(asset_id, CUSTODIAN)
    )
    live = [r for r in rows if r.get("status") != "CANCELLED"]
    if not live:
        return TEST_DEFAULTS["WINDOW_START"], TEST_DEFAULTS["WINDOW_END"]
    start = max(_parse(r["window_end"]) for r in live)
    return _iso(start), _iso(start + timedelta(hours=hours))


def schedule_transfer(
    asset_id: str,
    to_location_kind: str = "STORAGE",
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    **overrides,
) -> dict:
    """Schedule a transfer. When no window is given it chains contiguously off
    the asset's existing transfers."""
    if window_start is None or window_end is None:
        window_start, window_end = next_contiguous_window(asset_id)
    payload = create_custody_transfer_payload(
        asset_id, to_location_kind=to_location_kind,
        window_start=window_start, window_end=window_end, **overrides,
    )
    return get_success_data(_api.create_custody_transfer(payload, CUSTODIAN))


def complete_transfer(transfer_id: str, condition_on_arrival: str = "GOOD") -> dict:
    return get_success_data(
        _api.complete_custody_transfer(transfer_id, condition_on_arrival,
                                             CUSTODIAN)
    )


def move_asset(
    asset_id: str,
    to_location_kind: str = "STORAGE",
    condition_on_arrival: str = "GOOD",
) -> dict:
    """Schedule + complete one transfer at the next contiguous window. Returns
    the COMPLETED transfer."""
    transfer = schedule_transfer(asset_id, to_location_kind=to_location_kind)
    return complete_transfer(transfer["id"], condition_on_arrival)


def move_asset_to_storage(asset_id: str, condition_on_arrival: str = "EXCELLENT") -> dict:
    """Custody -> IN_STORAGE (in scope for the monthly accrual sweep)."""
    return move_asset(asset_id, "STORAGE", condition_on_arrival)


# ─── Tier 1: retention, authorization, return track (PRD §3.3, §3.8) ─────────

def decide_retention(asset_id: str, decision: str) -> dict:
    return get_success_data(_api.decide_retention(asset_id, decision, MANAGER))


def authorize_sale(asset_id: str) -> dict:
    return get_success_data(_api.authorize_sale(asset_id, MANAGER))


def initiate_return(asset_id: str) -> dict:
    return get_success_data(_api.initiate_return(asset_id, MANAGER))


def complete_return(asset_id: str, return_condition_grade: str) -> dict:
    return get_success_data(
        _api.complete_return(asset_id, return_condition_grade, MANAGER)
    )


def dispute_return(
    asset_id: str, claimed_depreciation_cents: int, claimant_user_id: str
) -> dict:
    return get_success_data(
        _api.dispute_return(asset_id, claimed_depreciation_cents,
                                  make_claimant_headers(claimant_user_id))
    )


def resolve_return_dispute(asset_id: str, final_depreciation_cents: int) -> dict:
    return get_success_data(
        _api.resolve_return_dispute(asset_id, final_depreciation_cents, COURT)
    )


# ─── Tier 2: sale authorization (PRD §3.3) ───────────────────────────────────

def create_sell_authorized_asset(
    case_id: str,
    raw_value_cents: int = 1_000_000,
    grade: str = "EXCELLENT",
    **asset_overrides,
) -> dict:
    """Valued asset taken through SELL and authorization. The owning case must
    be FORFEITED. Returns the asset re-read at (legal SALE_AUTHORIZED, custody
    RELEASED_FOR_SALE)."""
    asset, _valuation = create_valued_asset(
        case_id, raw_value_cents=raw_value_cents, grade=grade, **asset_overrides
    )
    decide_retention(asset["id"], "SELL")
    return authorize_sale(asset["id"])


# ─── Tier 2: liens and innocent-owner claims (PRD §3.5) ──────────────────────

def file_lien(
    asset_id: str,
    petitioner_ref: Optional[str] = None,
    amount_cents: int = 100_000,
    priority_position: int = 1,
    kind: str = "LIEN_MORTGAGE",
    lienholder_name: str = "Meridian Bank",
) -> dict:
    """File a LIEN_* interest; the caller's X-User-ID equals petitioner_ref."""
    ref = petitioner_ref or unique_petitioner_ref()
    payload = create_lien_payload(
        asset_id, ref, kind=kind, amount_cents=amount_cents,
        priority_position=priority_position, lienholder_name=lienholder_name,
    )
    return get_success_data(
        _api.create_third_party_interest(payload, make_claimant_headers(ref))
    )


def file_innocent_owner_claim(
    asset_id: str, petitioner_ref: Optional[str] = None
) -> dict:
    ref = petitioner_ref or unique_petitioner_ref()
    payload = create_innocent_owner_payload(asset_id, ref)
    return get_success_data(
        _api.create_third_party_interest(payload, make_claimant_headers(ref))
    )


def adjudicate_interest(interest_id: str, outcome: str) -> dict:
    return get_success_data(
        _api.adjudicate_third_party_interest(interest_id, outcome, COURT)
    )


def verify_lien(asset_id: str, **kwargs) -> dict:
    """File + VERIFY a lien. Returns the VERIFIED interest."""
    lien = file_lien(asset_id, **kwargs)
    return adjudicate_interest(lien["id"], "VERIFY")


def appeal_interest(interest_id: str, petitioner_ref: str) -> dict:
    """DENIED -> APPEALED, petitioner only."""
    return get_success_data(
        _api.appeal_third_party_interest(
            interest_id, make_claimant_headers(petitioner_ref)
        )
    )


# ─── Tier 2: interlocutory sale requests (PRD §3.4) ──────────────────────────

def create_isr(
    asset_id: str,
    justification: str = "holding costs threaten to consume the asset's value",
    expected_asset_version: Optional[int] = None,
    requester_user_id: str = ASSET_MANAGER_USER_ID,
) -> dict:
    """File an interlocutory sale request (OCC-guarded); the requester is
    recorded as the segregation-of-duties anchor."""
    if expected_asset_version is None:
        expected_asset_version = fresh_asset_version(asset_id)
    payload = create_isr_payload(asset_id, expected_asset_version,
                                 justification=justification)
    return get_success_data(
        _api.create_interlocutory_sale_request(
            payload, make_asset_manager_headers(requester_user_id)
        )
    )


def adjudicate_isr(
    request_id: str,
    outcome: str,
    adjudicator_user_id: str = COURT_OFFICIAL_USER_ID,
) -> dict:
    """CourtOfficial adjudication; the adjudicator must differ from the
    requester recorded on the request."""
    return get_success_data(
        _api.adjudicate_interlocutory_sale_request(
            request_id, outcome, make_court_official_headers(adjudicator_user_id)
        )
    )


def create_isr_eligible_asset(
    case_id: str,
    asset_type: str = "VEHICLE",
    raw_value_cents: int = 500_000,
    grade: str = "EXCELLENT",
    accumulated_cost_cents: int = 75_000,
) -> dict:
    """A VALUED asset whose projected burden meets the thirty-percent line by
    default (75000 + 3 x 25000 == 30% of 500000). Returns the fresh asset."""
    asset, _valuation = create_valued_asset(
        case_id, raw_value_cents=raw_value_cents, grade=grade,
        asset_type=asset_type,
    )
    if accumulated_cost_cents:
        post_accumulated_cost(asset["id"], accumulated_cost_cents)
    return get_asset(asset["id"])


# ─── Tier 3: sale events and settlement (PRD §3.6) ───────────────────────────

def schedule_sale_event(
    asset_id: str,
    reserve_price_cents: Optional[int] = None,
    slot_start: Optional[str] = None,
    slot_end: Optional[str] = None,
    auctioneer_ref: str = TEST_DEFAULTS["AUCTIONEER_REF"],
    sale_method: str = "PUBLIC_AUCTION",
) -> dict:
    """Schedule an auction. Default slot is the shared 2026-09-06 morning slot;
    default reserve is the asset's current appraised value."""
    if reserve_price_cents is None:
        reserve_price_cents = get_asset(asset_id)["appraised_value_cents"]
    payload = create_sale_event_payload(
        asset_id, sale_method=sale_method, auctioneer_ref=auctioneer_ref,
        slot_start=slot_start or TEST_DEFAULTS["SLOT_START"],
        slot_end=slot_end or TEST_DEFAULTS["SLOT_END"],
        reserve_price_cents=reserve_price_cents,
    )
    return get_success_data(_api.create_sale_event(payload, AUCTIONEER))


def close_sale_event(event_id: str, winning_bid_cents: int) -> dict:
    return get_success_data(
        _api.close_sale_event(event_id, winning_bid_cents, AUCTIONEER)
    )


def settle_sale_event(event_id: str) -> dict:
    return get_success_data(_api.settle_sale_event(event_id, FUND))


def create_settled_sale(
    case_id: Optional[str] = None,
    raw_value_cents: int = 1_000_000,
    grade: str = "EXCELLENT",
    asset_type: str = "VEHICLE",
    winning_bid_cents: Optional[int] = None,
    costs: Optional[List[dict]] = None,
    liens: Optional[List[dict]] = None,
    auctioneer_ref: str = TEST_DEFAULTS["AUCTIONEER_REF"],
    slot_start: Optional[str] = None,
    slot_end: Optional[str] = None,
    **asset_overrides,
) -> dict:
    """Full disposition chain: forfeited case -> valued asset -> optional cost
    postings -> optional verified liens -> SELL -> authorize -> auction ->
    close -> settle. Returns every participant, freshly re-read::

        {"case", "asset", "sale_event", "liens", "distributions"}
    """
    if case_id is None:
        case_id = create_case_in_state("FORFEITED")["id"]
    asset = create_sell_authorized_asset(
        case_id, raw_value_cents=raw_value_cents, grade=grade,
        asset_type=asset_type, **asset_overrides,
    )
    asset_id = asset["id"]
    # Costs and liens must exist before settlement to enter the waterfall.
    # (They are posted after authorization, which the ledger's legal-state gate
    # still permits, and before settle.)
    for cost in costs or []:
        post_expense(asset_id, **cost)
    verified = [verify_lien(asset_id, **lien) for lien in liens or []]
    event = schedule_sale_event(
        asset_id, auctioneer_ref=auctioneer_ref,
        slot_start=slot_start, slot_end=slot_end,
    )
    bid = winning_bid_cents if winning_bid_cents is not None else event[
        "reserve_price_cents"
    ]
    close_sale_event(event["id"], bid)
    settled = settle_sale_event(event["id"])
    distributions = get_success_data(
        _api.list_case_distributions(case_id, FUND)
    )
    return {
        "case": get_case(case_id),
        "asset": get_asset(asset_id),
        "sale_event": settled,
        "liens": verified,
        "distributions": distributions,
    }


# ─── Tier 4: distributions from the forfeiture fund (PRD §3.7) ───────────────

def create_distribution(
    case_id: str,
    amount_cents: int = 50_000,
    payee_ref: str = TEST_DEFAULTS["PAYEE_REF"],
    usage_restriction: str = "EQUIPMENT",
    creator_user_id: str = FUND_ADMINISTRATOR_USER_ID,
) -> dict:
    """Create a PENDING EQUITABLE_SHARE distribution; the creator is recorded
    as the segregation-of-duties anchor."""
    payload = create_distribution_payload(
        case_id, payee_ref=payee_ref, amount_cents=amount_cents,
        usage_restriction=usage_restriction,
    )
    return get_success_data(
        _api.create_distribution(
            payload, make_fund_administrator_headers(creator_user_id)
        )
    )


def approve_distribution(
    distribution_id: str,
    approver_user_id: str = SECOND_FUND_ADMINISTRATOR_USER_ID,
) -> dict:
    """PENDING -> PAID. The default approver differs from the default creator,
    satisfying segregation of duties."""
    return get_success_data(
        _api.approve_distribution(
            distribution_id, make_fund_administrator_headers(approver_user_id)
        )
    )


def rescind_distribution(
    distribution_id: str,
    user_id: str = FUND_ADMINISTRATOR_USER_ID,
) -> dict:
    return get_success_data(
        _api.rescind_distribution(
            distribution_id, make_fund_administrator_headers(user_id)
        )
    )


# ─── Tier 5: return track composites (PRD §3.8) ──────────────────────────────

def create_return_pending_asset(
    case_id: Optional[str] = None,
    valued: bool = False,
    raw_value_cents: int = 2_000_000,
    grade: str = "GOOD",
    **asset_overrides,
) -> Tuple[dict, dict]:
    """Case + asset, optionally valued, then the case is dismissed so the asset
    cascades to legal RETURN_PENDING. Returns (case, asset re-read)."""
    if case_id is None:
        case_id = create_case()["id"]
    if valued:
        asset, _valuation = create_valued_asset(
            case_id, raw_value_cents=raw_value_cents, grade=grade,
            **asset_overrides,
        )
    else:
        asset = intake_asset(case_id, **asset_overrides)
    case = dismiss_case(case_id)
    return case, get_asset(asset["id"])


def hand_over_to_claimant(
    asset_id: str, condition_on_arrival: str = "GOOD"
) -> dict:
    """Schedule + complete the CLAIMANT_PREMISES transfer that physically
    returns the asset (custody -> TRANSFERRED_OUT). Requires the asset to be
    RELEASED_FOR_RETURN."""
    return move_asset(asset_id, "CLAIMANT_PREMISES", condition_on_arrival)


def create_returned_asset(
    valued: bool = False,
    raw_value_cents: int = 2_000_000,
    seizure_grade: str = "GOOD",
    return_condition_grade: str = "GOOD",
    **asset_overrides,
) -> dict:
    """Full return track: dismiss -> initiate-return -> claimant-premises
    handover -> complete-return. Returns the asset re-read at legal RETURNED
    with returned_at and computed_depreciation_cents stamped."""
    _case, asset = create_return_pending_asset(
        valued=valued, raw_value_cents=raw_value_cents, grade=seizure_grade,
        **asset_overrides,
    )
    initiate_return(asset["id"])
    hand_over_to_claimant(asset["id"], condition_on_arrival=return_condition_grade)
    return get_success_data(
        _api.complete_return(asset["id"], return_condition_grade, MANAGER)
    )


def create_disputed_asset(
    claimed_depreciation_cents: int = 500_000,
    claimant_user_id: str = "cl-orma",
    **kwargs,
) -> dict:
    """A RETURNED asset disputed inside the window. Returns the asset re-read
    at legal DISPUTED."""
    asset = create_returned_asset(**kwargs)
    dispute_return(asset["id"], claimed_depreciation_cents, claimant_user_id)
    return get_asset(asset["id"])


# ─── Ops checkpoint (PRD §3.4) ───────────────────────────────────────────────

def run_holding_review() -> dict:
    """Run the monthly accrual sweep. Returns {assets_reviewed, accruals_posted}."""
    return get_success_data(_api.run_holding_review(FUND))


__all__ = [
    "set_clock",
    "get_asset",
    "get_case",
    "fresh_asset_version",
    "create_case",
    "file_forfeiture",
    "forfeit_case",
    "dismiss_case",
    "create_case_in_state",
    "intake_asset",
    "submit_valuation",
    "accept_valuation",
    "reject_valuation",
    "create_valued_asset",
    "post_expense",
    "post_accumulated_cost",
    "next_contiguous_window",
    "schedule_transfer",
    "complete_transfer",
    "move_asset",
    "move_asset_to_storage",
    "decide_retention",
    "authorize_sale",
    "initiate_return",
    "complete_return",
    "dispute_return",
    "resolve_return_dispute",
    "create_sell_authorized_asset",
    "file_lien",
    "file_innocent_owner_claim",
    "adjudicate_interest",
    "verify_lien",
    "appeal_interest",
    "create_isr",
    "adjudicate_isr",
    "create_isr_eligible_asset",
    "schedule_sale_event",
    "close_sale_event",
    "settle_sale_event",
    "create_settled_sale",
    "create_distribution",
    "approve_distribution",
    "rescind_distribution",
    "create_return_pending_asset",
    "hand_over_to_claimant",
    "create_returned_asset",
    "create_disputed_asset",
    "run_holding_review",
]
