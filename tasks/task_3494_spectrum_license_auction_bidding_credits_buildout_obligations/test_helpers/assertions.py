"""Entity assertions and domain invariant checkers.

Timestamp rendering has two families (PRD resource-identity section), and
they must not be normalized into one validator:
- created_at / updated_at / meta.api_request_timestamp: ISO 8601 UTC with
  EXACTLY three fractional digits -> assert_millisecond_timestamp.
- Domain datetimes (application_deadline, grant_date, term_end,
  payment_deadline, due_date, lease windows, transition windows): render
  EXACTLY as the logical clock reads. All fixtures set the clock in
  'YYYY-MM-DDTHH:MM:SSZ' form, so assert_clock_timestamp pins that shape.
"""
import re

from prd_bench_local_runner.testing import is_valid_uuid

from .constants import (
    UPFRONT_CENTS_PER_ELIGIBILITY_UNIT,
    expected_credit_amount_cents,
    expected_net_price_cents,
    expected_provisional_net_price_cents,
)
from .types import (
    ApplicantStatus,
    AssignmentBidStatus,
    AuctionStatus,
    BandPlanStatus,
    BidStatus,
    BlockCategory,
    BuildoutMilestoneStatus,
    ClockRoundStatus,
    IncumbentStatus,
    LicenseStatus,
    MilestoneType,
    RenewalStatus,
    TransferStatus,
    TransferType,
)

_MILLI_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_CLOCK_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def assert_millisecond_timestamp(value: str, field: str = "timestamp"):
    """Housekeeping family: exactly three fractional digits, UTC 'Z'."""
    assert isinstance(value, str) and _MILLI_TS.match(value), (
        f"{field} must render ISO 8601 UTC with exactly 3 fractional digits, got {value!r}"
    )


def assert_clock_timestamp(value: str, field: str = "timestamp"):
    """Domain family: exactly as the logical clock reads (fixtures always set
    whole-second 'Z' instants, so no fractional digits may appear)."""
    assert isinstance(value, str) and _CLOCK_TS.match(value), (
        f"{field} must render exactly as the logical clock reads "
        f"(YYYY-MM-DDTHH:MM:SSZ, no fractional normalization), got {value!r}"
    )


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a dashed UUID"
    assert "-" in data["id"], f"{label}.id must be dashed UUID string form"
    assert_millisecond_timestamp(data.get("created_at", ""), f"{label}.created_at")
    assert_millisecond_timestamp(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_band_plan(data: dict):
    _assert_common_fields(data, "BandPlan")
    assert isinstance(data["band_name"], str) and data["band_name"]
    assert data["frequency_start_mhz"] < data["frequency_end_mhz"], (
        "lower band edge must be strictly below the upper edge"
    )
    assert isinstance(data["technical_rules"], str)
    assert data["status"] in [s.value for s in BandPlanStatus]


def assert_license_area(data: dict):
    _assert_common_fields(data, "LicenseArea")
    assert is_valid_uuid(data.get("band_plan_id", "")), "band_plan_id must be a UUID"
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["population"], int) and data["population"] >= 1


def assert_license_block(data: dict):
    _assert_common_fields(data, "LicenseBlock")
    assert is_valid_uuid(data.get("band_plan_id", "")), "band_plan_id must be a UUID"
    assert data["category"] in [c.value for c in BlockCategory]
    assert isinstance(data["mhz_size"], int) and data["mhz_size"] >= 1
    assert isinstance(data["supply_per_area"], int) and data["supply_per_area"] >= 1
    assert isinstance(data["price_per_mhz_pop_cents"], int) and data["price_per_mhz_pop_cents"] >= 0


def assert_auction(data: dict):
    _assert_common_fields(data, "Auction")
    assert is_valid_uuid(data.get("band_plan_id", "")), "band_plan_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert_clock_timestamp(data["application_deadline"], "Auction.application_deadline")
    assert data["status"] in [s.value for s in AuctionStatus]
    assert isinstance(data["current_round_number"], int) and data["current_round_number"] >= 0
    assert isinstance(data["total_proceeds_cents"], int) and data["total_proceeds_cents"] >= 0
    assert isinstance(data["forfeited_deposits_cents"], int) and data["forfeited_deposits_cents"] >= 0
    assert isinstance(data["available_supply"], list)
    for entry in data["available_supply"]:
        assert set(entry) >= {"area_code", "category", "available"}
        assert isinstance(entry["available"], int) and entry["available"] >= 0


def assert_applicant(data: dict):
    _assert_common_fields(data, "Applicant")
    assert is_valid_uuid(data.get("auction_id", "")), "auction_id must be a UUID"
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["claims_small_business"], bool)
    assert isinstance(data["claims_rural_credit"], bool)
    assert isinstance(data["own_annual_revenue_cents"], int) and data["own_annual_revenue_cents"] >= 0
    assert isinstance(data["service_population"], int) and data["service_population"] >= 0
    assert isinstance(data["ownership_interests"], list)
    for oi in data["ownership_interests"]:
        assert set(oi) >= {"holder_name", "stake_pct", "holder_annual_revenue_cents"}
    for f in (
        "credit_pct",
        "upfront_paid_cents",
        "upfront_held_cents",
        "upfront_refunded_cents",
        "upfront_forfeited_cents",
        "eligibility_units",
        "initial_eligibility_units",
    ):
        assert isinstance(data[f], int) and data[f] >= 0, f"Applicant.{f} must be a non-negative int"
    # attributable_revenue_cents is computed by qualification (PRD §3.3) and is
    # absent from §3.2's zeroed-ledger list, so its pre-QUALIFY value is not
    # PRD-determined: accept None pre-QUALIFY, non-negative int once written.
    v = data["attributable_revenue_cents"]
    assert v is None or (isinstance(v, int) and v >= 0), (
        "Applicant.attributable_revenue_cents must be null or a non-negative int"
    )
    assert data["status"] in [s.value for s in ApplicantStatus]


def assert_clock_round(data: dict):
    _assert_common_fields(data, "ClockRound")
    assert is_valid_uuid(data.get("auction_id", "")), "auction_id must be a UUID"
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["stage"] in (1, 2)
    assert isinstance(data["prices"], list)
    for p in data["prices"]:
        assert set(p) >= {"area_code", "category", "price_cents"}
        assert isinstance(p["price_cents"], int) and p["price_cents"] >= 0
    assert isinstance(data["aggregate_demand"], list)
    for d in data["aggregate_demand"]:
        assert set(d) >= {"area_code", "category", "demand_quantity"}
        assert isinstance(d["demand_quantity"], int) and d["demand_quantity"] >= 0
    assert data["status"] in [s.value for s in ClockRoundStatus]


def assert_bid(data: dict):
    _assert_common_fields(data, "Bid")
    assert is_valid_uuid(data.get("round_id", "")), "round_id must be a UUID"
    assert is_valid_uuid(data.get("bidder_applicant_id", "")), "bidder_applicant_id must be a UUID"
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert data["category"] in [c.value for c in BlockCategory]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["units_snapshot"], int) and data["units_snapshot"] >= 1
    assert data["status"] in [s.value for s in BidStatus]


def assert_assignment_bid(data: dict):
    _assert_common_fields(data, "AssignmentBid")
    assert is_valid_uuid(data.get("auction_id", "")), "auction_id must be a UUID"
    assert is_valid_uuid(data.get("bidder_applicant_id", "")), "bidder_applicant_id must be a UUID"
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert data["category"] in [c.value for c in BlockCategory]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in [s.value for s in AssignmentBidStatus]


def assert_license(data: dict):
    _assert_common_fields(data, "License")
    assert is_valid_uuid(data.get("auction_id", "")), "auction_id must be a UUID"
    assert is_valid_uuid(data.get("area_id", "")), "area_id must be a UUID"
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert data["category"] in [c.value for c in BlockCategory]
    assert isinstance(data["frequency_block_index"], int) and data["frequency_block_index"] >= 0
    assert is_valid_uuid(data.get("holder_applicant_id", "")), "holder_applicant_id must be a UUID"
    for f in (
        "credit_pct",
        "gross_clock_price_cents",
        "assignment_bid_cents",
        "gross_final_price_cents",
        "provisional_net_price_cents",
        "net_price_cents",
        "credit_amount_cents",
        "paid_cents",
        "relocation_share_owed_cents",
    ):
        assert isinstance(data[f], int) and data[f] >= 0, f"License.{f} must be a non-negative int"
    assert_clock_timestamp(data["payment_deadline"], "License.payment_deadline")
    if data.get("grant_date") is not None:
        assert_clock_timestamp(data["grant_date"], "License.grant_date")
    if data.get("term_end") is not None:
        assert_clock_timestamp(data["term_end"], "License.term_end")
    for f in ("active_lease_start", "active_lease_end"):
        if data.get(f) is not None:
            assert_clock_timestamp(data[f], f"License.{f}")
    if data.get("leased_to_applicant_id") is not None:
        assert is_valid_uuid(data["leased_to_applicant_id"])
    assert data["status"] in [s.value for s in LicenseStatus]


def assert_buildout_milestone(data: dict):
    _assert_common_fields(data, "BuildoutMilestone")
    assert is_valid_uuid(data.get("license_id", "")), "license_id must be a UUID"
    assert data["milestone_type"] in [t.value for t in MilestoneType]
    assert_clock_timestamp(data["due_date"], "BuildoutMilestone.due_date")
    assert isinstance(data["required_coverage_pct"], int)
    if data.get("covered_population") is not None:
        assert isinstance(data["covered_population"], int) and data["covered_population"] >= 0
    assert data["status"] in [s.value for s in BuildoutMilestoneStatus]


def assert_transfer_application(data: dict):
    _assert_common_fields(data, "TransferApplication")
    assert is_valid_uuid(data.get("license_id", "")), "license_id must be a UUID"
    assert is_valid_uuid(data.get("transferor_applicant_id", "")), "transferor_applicant_id must be a UUID"
    assert is_valid_uuid(data.get("transferee_applicant_id", "")), "transferee_applicant_id must be a UUID"
    assert data["transfer_type"] in [t.value for t in TransferType]
    if data["transfer_type"] == TransferType.LEASE.value:
        assert_clock_timestamp(data["lease_start"], "TransferApplication.lease_start")
        assert_clock_timestamp(data["lease_end"], "TransferApplication.lease_end")
    assert isinstance(data["unjust_enrichment_cents"], int) and data["unjust_enrichment_cents"] >= 0
    assert data["status"] in [s.value for s in TransferStatus]


def assert_incumbent(data: dict):
    _assert_common_fields(data, "Incumbent")
    assert is_valid_uuid(data.get("band_plan_id", "")), "band_plan_id must be a UUID"
    assert is_valid_uuid(data.get("area_id", "")), "area_id must be a UUID"
    assert isinstance(data["callsign"], str) and data["callsign"]
    assert isinstance(data["relocation_cost_cents"], int) and data["relocation_cost_cents"] >= 0
    for f in ("transition_window_start", "transition_window_end"):
        if data.get(f) is not None:
            assert_clock_timestamp(data[f], f"Incumbent.{f}")
    for arr in ("shares_proportional", "shares_equal"):
        # PRD §3.1 says these "stay unset" until CONFIRM_CLEARED fills them in;
        # "unset" does not uniquely determine null vs [] pre-workflow, so both
        # renderings are accepted. Once filled, every entry is validated.
        if data[arr] is None:
            continue
        assert isinstance(data[arr], list)
        for share in data[arr]:
            assert is_valid_uuid(share.get("license_id", "")), "share.license_id must be a UUID"
            assert isinstance(share["amount_cents"], int) and share["amount_cents"] >= 0
    assert data["status"] in [s.value for s in IncumbentStatus]


def assert_renewal_application(data: dict):
    _assert_common_fields(data, "RenewalApplication")
    assert is_valid_uuid(data.get("license_id", "")), "license_id must be a UUID"
    assert data["status"] in [s.value for s in RenewalStatus]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_upfront_ledger_conserved(applicant: dict):
    """Conservation invariant: paid == held + refunded + forfeited, always."""
    total = (
        applicant["upfront_held_cents"]
        + applicant["upfront_refunded_cents"]
        + applicant["upfront_forfeited_cents"]
    )
    assert applicant["upfront_paid_cents"] == total, (
        f"upfront ledger violated: paid {applicant['upfront_paid_cents']} != "
        f"held+refunded+forfeited {total}"
    )


def assert_eligibility_from_held(applicant: dict):
    """eligibility_units == floor(held / 2500). Holds after any upfront
    payment and before any activity-rule reduction at a round close (the
    activity rule only ever mutates eligibility downward afterward)."""
    expected = applicant["upfront_held_cents"] // UPFRONT_CENTS_PER_ELIGIBILITY_UNIT
    assert applicant["eligibility_units"] == expected, (
        f"eligibility_units {applicant['eligibility_units']} != "
        f"floor(held {applicant['upfront_held_cents']} / 2500) = {expected}"
    )


def assert_license_price_invariants(license: dict):
    """The two settlement variants sharing one credit basis (PRD pricing):
    gross_final = gross_clock + assignment_bid; provisional excludes the
    assignment bid; net includes it; credit_amount = gross_final - net.
    Per-license round_half_up is applied BEFORE any summation."""
    g_clock = license["gross_clock_price_cents"]
    a_bid = license["assignment_bid_cents"]
    pct = license["credit_pct"]
    assert license["gross_final_price_cents"] == g_clock + a_bid
    assert license["provisional_net_price_cents"] == expected_provisional_net_price_cents(g_clock, pct)
    assert license["net_price_cents"] == expected_net_price_cents(g_clock, a_bid, pct)
    assert license["credit_amount_cents"] == expected_credit_amount_cents(g_clock, a_bid, pct)


def assert_shares_cover_cost(shares: list, relocation_cost_cents: int):
    """Largest-remainder allocation loses no cents: share amounts sum exactly
    to the relocation cost."""
    total = sum(s["amount_cents"] for s in shares)
    assert total == relocation_cost_cents, (
        f"shares sum {total} != relocation_cost_cents {relocation_cost_cents}"
    )


def get_supply_entry(auction: dict, area_code: str, category: str) -> dict:
    """Fetch the (area_code, category) entry of Auction.available_supply."""
    for entry in auction["available_supply"]:
        if entry["area_code"] == area_code and entry["category"] == category:
            return entry
    raise AssertionError(
        f"no available_supply entry for ({area_code}, {category}) in auction {auction.get('id')}"
    )


def get_price_entry(clock_round: dict, area_code: str, category: str) -> dict:
    for entry in clock_round["prices"]:
        if entry["area_code"] == area_code and entry["category"] == category:
            return entry
    raise AssertionError(
        f"no prices entry for ({area_code}, {category}) in round {clock_round.get('id')}"
    )


def get_demand_entry(clock_round: dict, area_code: str, category: str) -> dict:
    for entry in clock_round["aggregate_demand"]:
        if entry["area_code"] == area_code and entry["category"] == category:
            return entry
    raise AssertionError(
        f"no aggregate_demand entry for ({area_code}, {category}) in round {clock_round.get('id')}"
    )
