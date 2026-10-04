"""Composite setup helpers.

The PRD's interesting claims require the system to be in a specific state that
takes 5-20 API calls to reach (e.g. a case in PENDING_CLOSE with an APPROVED
BASE_WARRANTY claim and an INSPECTED_OK part return). These fixtures
encapsulate the multi-step sequences so tests focus on assertions.

All setup calls use get_success_data() so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Ownership threading: FleetManager calls use headers bound to the created
fleet's id; DealerAdvisor calls use headers bound to the created dealer's id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_bay_payload,
    create_campaign_payload,
    create_case_payload,
    create_claim_payload,
    create_coverage_contract_payload,
    create_dealer_payload,
    create_fleet_payload,
    create_part_order_payload,
    create_recovery_payload,
    create_truck_payload,
    schedule_case_payload,
)
from .test_users import (
    make_dealer_advisor_headers,
    make_fleet_manager_headers,
    make_parts_manager_headers,
    make_supplier_manager_headers,
    make_uptime_coordinator_headers,
    make_warranty_admin_headers,
)

CLOCK_START = "2026-09-01T00:00:00Z"


def setup_clock(to_iso8601: str = CLOCK_START) -> None:
    """Advance the logical clock. Any role may do this."""
    get_success_data(api_client.set_clock(to_iso8601, make_uptime_coordinator_headers()))


def setup_fleet(fleet_name="Test Fleet", home_region="SE") -> dict:
    """Create one ACTIVE fleet. Returns (fleet, fm_headers)."""
    fm = make_fleet_manager_headers("fm-bootstrap")
    fleet = get_success_data(
        api_client.create_fleet(create_fleet_payload(fleet_name=fleet_name, home_region=home_region), fm)
    )
    return fleet, make_fleet_manager_headers(fleet["id"])


def setup_fleet_with_truck(
    fleet_name="Test Fleet",
    home_region="SE",
    truck_overrides=None,
) -> tuple:
    """Fleet + one IN_SERVICE truck. Returns (fleet, truck, fm_headers)."""
    fleet, fm = setup_fleet(fleet_name=fleet_name, home_region=home_region)
    truck = get_success_data(
        api_client.create_truck(
            fleet["id"], create_truck_payload(**(truck_overrides or {})), fm
        )
    )
    return fleet, truck, fm


def setup_dealer_with_bay(
    fm_headers,
    dealer_name="Test Freightliner",
    region="SE",
    hourly_labor_rate_cents=18500,
    bay_code="B1",
) -> tuple:
    """Dealer + one AVAILABLE bay. Returns (dealer, bay, da_headers)."""
    dealer = get_success_data(
        api_client.create_dealer(
            create_dealer_payload(
                dealer_name=dealer_name,
                region=region,
                hourly_labor_rate_cents=hourly_labor_rate_cents,
            ),
            fm_headers,
        )
    )
    da = make_dealer_advisor_headers(dealer["id"])
    bay = get_success_data(
        api_client.create_bay(dealer["id"], create_bay_payload(bay_code=bay_code), da)
    )
    return dealer, bay, da


def setup_full_environment(
    fleet_name="Test Fleet",
    home_region="SE",
    dealer_region="SE",
    hourly_labor_rate_cents=18500,
    truck_overrides=None,
) -> dict:
    """Fleet + truck + dealer + bay, all in matching regions.

    Returns a dict: {fleet, truck, dealer, bay, fm, da, uc, pm, wa, sm}.
    """
    fleet, truck, fm = setup_fleet_with_truck(
        fleet_name=fleet_name, home_region=home_region, truck_overrides=truck_overrides
    )
    dealer, bay, da = setup_dealer_with_bay(
        fm, region=dealer_region, hourly_labor_rate_cents=hourly_labor_rate_cents
    )
    return {
        "fleet": fleet,
        "truck": truck,
        "dealer": dealer,
        "bay": bay,
        "fm": fm,
        "da": da,
        "uc": make_uptime_coordinator_headers(),
        "pm": make_parts_manager_headers(),
        "wa": make_warranty_admin_headers(),
        "sm": make_supplier_manager_headers(),
    }


def open_case(env: dict, fault_code="SPN3216_FMI4", **case_overrides) -> dict:
    """Open a case on the env's truck. Returns the case."""
    return get_success_data(
        api_client.create_case(
            env["fleet"]["id"],
            env["truck"]["id"],
            create_case_payload(fault_code=fault_code, **case_overrides),
            env["uc"],
        )
    )


def _truck_version(env: dict) -> int:
    """Fetch the truck's current version for OCC schedule calls."""
    truck = get_success_data(
        api_client.get_truck(env["fleet"]["id"], env["truck"]["id"], env["fm"])
    )
    return truck["version"]


def _case_version(env: dict, case_id: str) -> int:
    case = get_success_data(
        api_client.get_case(env["fleet"]["id"], env["truck"]["id"], case_id, env["uc"])
    )
    return case["version"]


def setup_case_in_state(
    env: dict,
    target_state: str,
    fault_code="SPN3216_FMI4",
    diagnostic_minutes_authorized=30,
    scheduled_start_at="2026-09-01T13:00:00Z",
    scheduled_end_at="2026-09-01T17:00:00Z",
    labor_minutes_actual=60,
    repair_outcome="FIXED",
) -> dict:
    """Walk a case from OPEN to the requested state.

    Supported states: OPEN, TRIAGE, SCHEDULED, IN_SERVICE, AWAITING_PART,
    PENDING_CLOSE, CLOSED.

    Returns a dict: {case, work_order, part_order}. work_order is the DRAFT
    auto-created at schedule (populated from SCHEDULED onwards); part_order is
    populated for AWAITING_PART only.
    """
    fid = env["fleet"]["id"]
    tid = env["truck"]["id"]

    case = open_case(env, fault_code=fault_code)
    result = {"case": case, "work_order": None, "part_order": None}
    if target_state == "OPEN":
        return result

    case = get_success_data(api_client.triage_case(fid, tid, case["id"], env["uc"]))
    result["case"] = case
    if target_state == "TRIAGE":
        return result

    case = get_success_data(
        api_client.schedule_case(
            fid,
            tid,
            case["id"],
            schedule_case_payload(
                env["dealer"]["id"],
                env["bay"]["id"],
                _truck_version(env),
                scheduled_start_at=scheduled_start_at,
                scheduled_end_at=scheduled_end_at,
            ),
            env["uc"],
        )
    )
    result["case"] = case
    work_orders = get_success_data(
        api_client.list_work_orders(fid, tid, case["id"], env["uc"])
    )
    wo = work_orders[0]
    result["work_order"] = wo
    if target_state == "SCHEDULED":
        return result

    wo = get_success_data(
        api_client.authorize_work_order(
            fid,
            tid,
            case["id"],
            wo["id"],
            {"diagnostic_minutes_authorized": diagnostic_minutes_authorized},
            env["uc"],
        )
    )
    result["work_order"] = wo
    case = get_success_data(api_client.start_service(fid, tid, case["id"], env["da"]))
    result["case"] = case
    if target_state == "IN_SERVICE":
        return result

    if target_state == "AWAITING_PART":
        po = get_success_data(
            api_client.create_part_order(
                fid, tid, case["id"], create_part_order_payload(), env["pm"]
            )
        )
        result["part_order"] = po
        case = get_success_data(api_client.get_case(fid, tid, case["id"], env["uc"]))
        result["case"] = case
        return result

    wo = get_success_data(
        api_client.complete_work_order(
            fid,
            tid,
            case["id"],
            wo["id"],
            {"labor_minutes_actual": labor_minutes_actual, "repair_outcome": repair_outcome},
            env["da"],
        )
    )
    result["work_order"] = wo
    case = get_success_data(api_client.request_close(fid, tid, case["id"], env["da"]))
    result["case"] = case
    if target_state == "PENDING_CLOSE":
        return result

    case = get_success_data(api_client.close_case(fid, tid, case["id"], env["uc"]))
    result["case"] = case
    if target_state == "CLOSED":
        return result

    raise ValueError(f"Unsupported target_state: {target_state}")


def setup_claim_on_case(
    env: dict,
    case_id: str,
    claim_type="BASE_WARRANTY",
    labor_minutes_claimed=100,
    parts_claimed_cents=50000,
    submit=True,
) -> dict:
    """Create a claim on the case and (optionally) submit it with a fresh OCC
    version. Returns the claim."""
    fid = env["fleet"]["id"]
    tid = env["truck"]["id"]
    claim = get_success_data(
        api_client.create_claim(
            fid,
            tid,
            case_id,
            create_claim_payload(
                claim_type=claim_type,
                labor_minutes_claimed=labor_minutes_claimed,
                parts_claimed_cents=parts_claimed_cents,
            ),
            env["wa"],
        )
    )
    if submit:
        claim = get_success_data(
            api_client.submit_claim(
                fid,
                tid,
                case_id,
                claim["id"],
                {"expected_case_version": _case_version(env, case_id)},
                env["wa"],
            )
        )
    return claim


def setup_approved_base_warranty_claim(
    env: dict,
    case_id: str,
    claim_type="BASE_WARRANTY",
    labor_minutes_claimed=100,
    parts_claimed_cents=100000,
) -> tuple:
    """Claim driven DRAFT -> SUBMITTED -> UNDER_REVIEW -> APPROVED; the approval
    creates a PartReturn in REQUESTED for BASE_WARRANTY/CAMPAIGN claims.

    Returns (claim, part_return_or_None).
    """
    fid = env["fleet"]["id"]
    tid = env["truck"]["id"]
    claim = setup_claim_on_case(
        env,
        case_id,
        claim_type=claim_type,
        labor_minutes_claimed=labor_minutes_claimed,
        parts_claimed_cents=parts_claimed_cents,
    )
    claim = get_success_data(
        api_client.begin_review_claim(fid, tid, case_id, claim["id"], env["wa"])
    )
    claim = get_success_data(
        api_client.approve_claim(fid, tid, case_id, claim["id"], {}, env["wa"])
    )
    part_return = None
    if claim.get("recovery_status") == "PART_RETURN_REQUESTED":
        prs = get_success_data(
            api_client.list_part_returns(fid, tid, case_id, claim["id"], env["sm"])
        )
        part_return = prs[0]
    return claim, part_return


def setup_part_return_inspected_ok(
    env: dict,
    case_id: str,
    claim_type="BASE_WARRANTY",
    labor_minutes_claimed=100,
    parts_claimed_cents=100000,
) -> tuple:
    """Full path to an INSPECTED_OK part return on an APPROVED claim.

    Returns (claim, part_return).
    """
    fid = env["fleet"]["id"]
    tid = env["truck"]["id"]
    claim, part_return = setup_approved_base_warranty_claim(
        env,
        case_id,
        claim_type=claim_type,
        labor_minutes_claimed=labor_minutes_claimed,
        parts_claimed_cents=parts_claimed_cents,
    )
    part_return = get_success_data(
        api_client.ship_part_return(fid, tid, case_id, claim["id"], part_return["id"], env["da"])
    )
    part_return = get_success_data(
        api_client.receive_part_return(fid, tid, case_id, claim["id"], part_return["id"], env["sm"])
    )
    part_return = get_success_data(
        api_client.inspect_part_return(
            fid,
            tid,
            case_id,
            claim["id"],
            part_return["id"],
            {"inspection_disposition": "OK"},
            env["sm"],
        )
    )
    claim = get_success_data(
        api_client.get_claim(fid, tid, case_id, claim["id"], env["wa"])
    )
    return claim, part_return


def setup_filed_recovery(
    env: dict,
    case_id: str,
    claimed_amount_cents=10000,
    parts_claimed_cents=100000,
) -> tuple:
    """Full path to a FILED supplier recovery.

    Returns (claim, part_return, recovery).
    """
    fid = env["fleet"]["id"]
    tid = env["truck"]["id"]
    claim, part_return = setup_part_return_inspected_ok(
        env, case_id, parts_claimed_cents=parts_claimed_cents
    )
    recovery = get_success_data(
        api_client.create_recovery(
            fid,
            tid,
            case_id,
            claim["id"],
            create_recovery_payload(
                part_return["id"], claimed_amount_cents=claimed_amount_cents
            ),
            env["sm"],
        )
    )
    return claim, part_return, recovery


def setup_campaign_with_completion(
    env: dict,
    campaign_overrides=None,
) -> tuple:
    """Create a campaign whose affected_model_codes cover the env truck, then
    return (campaign, completion_row_for_truck)."""
    campaign = get_success_data(
        api_client.create_campaign(
            create_campaign_payload(**(campaign_overrides or {})), env["uc"]
        )
    )
    completions = get_success_data(
        api_client.list_campaign_completions(
            campaign["id"], env["uc"], params={"truck_id": env["truck"]["id"]}
        )
    )
    completion = completions[0]
    return campaign, completion
