"""Composite setup helpers for the driver-incentives workflow.

Every helper builds its preconditions from scratch through the PRD's own
endpoints, because each test starts against an empty database. Setup calls go
through the lenient success validator so a broken precondition surfaces as a
clear "Setup failed" instead of a confusing assertion inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import CLOCK_START, WEEK_MID, WEEK_START
from .factories import (
    create_appeal_payload,
    create_challenge_program_payload,
    create_driver_payload,
    create_forecast_payload,
    create_fraud_flag_payload,
    create_guarantee_program_payload,
    create_market_payload,
    create_ride_payload,
    create_streak_program_payload,
    create_supply_shortfall_payload,
    create_zone_program_payload,
    enroll_payload,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["incentive_ops_headers"]
PAY = TEST_USERS["payments_officer_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]

LIST_ALL = {"limit": 100, "offset": 0}


# ==========================================================================
# Tier 0 -- single-call helpers
# ==========================================================================
def set_clock(to_iso8601: str = CLOCK_START) -> dict:
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_market(**overrides) -> dict:
    return get_success_data(api.create_market(create_market_payload(**overrides), ADMIN))


def create_driver(market_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_driver(create_driver_payload(market_id, **overrides), OPS)
    )


def create_streak_program(market_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_program(create_streak_program_payload(market_id, **overrides), OPS)
    )


def create_zone_program(market_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_program(create_zone_program_payload(market_id, **overrides), OPS)
    )


def create_challenge_program(market_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_program(create_challenge_program_payload(market_id, **overrides), OPS)
    )


def create_guarantee_program(market_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_program(create_guarantee_program_payload(market_id, **overrides), OPS)
    )


def activate_program(program_id: str) -> dict:
    return get_success_data(api.activate_program(program_id, OPS))


def pause_program(program_id: str) -> dict:
    return get_success_data(api.pause_program(program_id, OPS))


def resume_program(program_id: str) -> dict:
    return get_success_data(api.resume_program(program_id, OPS))


def enroll(program_id: str, driver_id: str) -> dict:
    return get_success_data(api.enroll_driver(program_id, enroll_payload(driver_id), OPS))


def read_market(market_id: str) -> dict:
    return get_success_data(api.get_market(market_id, ADMIN))


def read_program(program_id: str) -> dict:
    return get_success_data(api.get_program(program_id, OPS))


def read_driver(driver_id: str) -> dict:
    return get_success_data(api.get_driver(driver_id, FRAUD))


def read_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api.get_enrollment(enrollment_id, OPS))


def read_settlement(settlement_id: str) -> dict:
    return get_success_data(api.get_settlement(settlement_id, PAY))


def read_statement(statement_id: str) -> dict:
    return get_success_data(api.get_statement(statement_id, PAY))


def read_ride(ride_id: str) -> dict:
    return get_success_data(api.get_ride(ride_id, FRAUD))


def read_appeal(appeal_id: str) -> dict:
    return get_success_data(api.get_appeal(appeal_id, PAY))


def read_fraud_flag(flag_id: str) -> dict:
    return get_success_data(api.get_fraud_flag(flag_id, FRAUD))


# ==========================================================================
# Tier 1 -- market + driver + program scaffolding
# ==========================================================================
def create_market_with_driver(
    market_code: str = "TST",
    budget: int = 1_000_000,
    cells=("cellA",),
    driver_name: str = "Test Driver",
):
    """Market + one onboarded driver. Returns (market, driver)."""
    market = create_market(market_code=market_code, incentive_budget_cents=budget,
                           geo_cells=list(cells))
    driver = create_driver(market["id"], display_name=driver_name)
    return market, driver


def create_active_streak_program(market_id: str, **overrides) -> dict:
    program = create_streak_program(market_id, **overrides)
    return activate_program(program["id"])


def create_active_zone_program(market_id: str, **overrides) -> dict:
    program = create_zone_program(market_id, **overrides)
    return activate_program(program["id"])


def create_active_challenge_program(market_id: str, **overrides) -> dict:
    program = create_challenge_program(market_id, **overrides)
    return activate_program(program["id"])


def create_active_guarantee_program(market_id: str, **overrides) -> dict:
    program = create_guarantee_program(market_id, **overrides)
    return activate_program(program["id"])


# ==========================================================================
# Tier 2 -- ride lifecycle shortcuts (driver identity threaded through)
# ==========================================================================
def create_offered_ride(driver: dict, market_id: str, **overrides) -> dict:
    headers = make_driver_headers(driver["id"])
    return get_success_data(
        api.create_ride(create_ride_payload(driver["id"], market_id, **overrides), headers)
    )


def accept_ride(driver: dict, ride_id: str) -> dict:
    return get_success_data(api.accept_ride(ride_id, make_driver_headers(driver["id"])))


def decline_ride(driver: dict, ride_id: str) -> dict:
    return get_success_data(api.decline_ride(ride_id, make_driver_headers(driver["id"])))


def complete_ride(driver: dict, ride_id: str) -> dict:
    return get_success_data(api.complete_ride(ride_id, make_driver_headers(driver["id"])))


def cancel_ride(driver: dict, ride_id: str, cancelled_by: str) -> dict:
    return get_success_data(
        api.cancel_ride(ride_id, {"cancelled_by": cancelled_by},
                        make_driver_headers(driver["id"]))
    )


def complete_ride_end_to_end(driver: dict, market_id: str, **overrides) -> dict:
    """Offer + accept + complete one ride. Returns the COMPLETED ride."""
    ride = create_offered_ride(driver, market_id, **overrides)
    accept_ride(driver, ride["id"])
    return complete_ride(driver, ride["id"])


def complete_rides(driver: dict, market_id: str, count: int, **overrides) -> list:
    return [complete_ride_end_to_end(driver, market_id, **overrides) for _ in range(count)]


# ==========================================================================
# Tier 3 -- guarantee / settlement lifecycle shortcuts
# ==========================================================================
def setup_guarantee_scenario(
    market_code: str = "GTN",
    budget: int = 10_000_000,
    guaranteed_weekly_cents: int = 500_000,
    guaranteed_min_rides: int = 1,
    driver_name: str = "Guarantee Driver",
):
    """Clock at start, market, driver, ACTIVE guarantee program, driver enrolled.
    Returns (market, driver, program, enrollment)."""
    set_clock(CLOCK_START)
    market, driver = create_market_with_driver(
        market_code=market_code, budget=budget, driver_name=driver_name
    )
    program = create_active_guarantee_program(
        market["id"],
        guaranteed_weekly_cents=guaranteed_weekly_cents,
        guaranteed_min_rides=guaranteed_min_rides,
    )
    enrollment = enroll(program["id"], driver["id"])
    return market, driver, program, enrollment


def setup_guarantee_with_rides(
    ride_fares_cents=(100_000,),
    tips_cents: int = 0,
    **kwargs,
):
    """Guarantee scenario with N completed STANDARD rides inside the week.
    Returns (market, driver, program, enrollment, rides)."""
    market, driver, program, enrollment = setup_guarantee_scenario(**kwargs)
    set_clock(WEEK_MID)
    rides = [
        complete_ride_end_to_end(
            driver, market["id"], base_fare_cents=fare, tips_cents=tips_cents
        )
        for fare in ride_fares_cents
    ]
    return market, driver, program, enrollment, rides


def compute_settlement(driver_id: str, program_id: str, week_start: str = WEEK_START) -> dict:
    return get_success_data(
        api.compute_settlement(
            {"driver_id": driver_id, "program_id": program_id,
             "week_start_utc": week_start},
            PAY,
        )
    )


def finalize_settlement(settlement_id: str) -> dict:
    return get_success_data(api.finalize_settlement(settlement_id, PAY))


def pay_settlement(settlement_id: str) -> dict:
    return get_success_data(api.pay_settlement(settlement_id, PAY))


def setup_finalized_settlement(**kwargs):
    """Guarantee scenario with one 100000-cent ride and a FINALIZED settlement.
    Returns (market, driver, program, enrollment, rides, settlement)."""
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(**kwargs)
    settlement = compute_settlement(driver["id"], program["id"])
    settlement = finalize_settlement(settlement["id"])
    return market, driver, program, enrollment, rides, settlement


def setup_paid_settlement(**kwargs):
    """Finalized settlement pushed through to PAID."""
    market, driver, program, enrollment, rides, settlement = setup_finalized_settlement(**kwargs)
    settlement = pay_settlement(settlement["id"])
    return market, driver, program, enrollment, rides, settlement


def compute_statement(driver_id: str, week_start: str = WEEK_START) -> dict:
    return get_success_data(
        api.compute_statement({"driver_id": driver_id, "week_start_utc": week_start}, PAY)
    )


def setup_published_statement(**kwargs):
    """Paid settlement + published statement for the same driver/week."""
    market, driver, program, enrollment, rides, settlement = setup_paid_settlement(**kwargs)
    statement = compute_statement(driver["id"])
    statement = get_success_data(api.publish_statement(statement["id"], PAY))
    return market, driver, program, enrollment, rides, settlement, statement


# ==========================================================================
# Tier 4 -- appeal helpers
# ==========================================================================
def file_eligibility_appeal(driver: dict, reason: str = "rate mis-measured") -> dict:
    return get_success_data(
        api.create_appeal(
            create_appeal_payload(driver["id"], subject_type="ELIGIBILITY",
                                  reason=reason),
            make_driver_headers(driver["id"]),
        )
    )


def file_statement_appeal(driver: dict, statement_id: str, reason: str = "wrong total") -> dict:
    return get_success_data(
        api.create_appeal(
            create_appeal_payload(driver["id"], subject_type="STATEMENT",
                                  statement_id=statement_id, reason=reason),
            make_driver_headers(driver["id"]),
        )
    )


def setup_appeal_under_review(driver: dict):
    """ELIGIBILITY appeal moved FILED -> UNDER_REVIEW."""
    appeal = file_eligibility_appeal(driver)
    appeal = get_success_data(api.start_appeal_review(appeal["id"], PAY))
    return appeal


# ==========================================================================
# Tier 5 -- fraud helpers
# ==========================================================================
def open_fraud_flag(driver_id: str, ride_id: str, severity: int = 5,
                    signal_type: str = "INFLATED_RIDE", **overrides) -> dict:
    return get_success_data(
        api.create_fraud_flag(
            create_fraud_flag_payload(driver_id, ride_id, signal_type=signal_type,
                                      severity=severity, **overrides),
            FRAUD,
        )
    )


def confirm_flag(flag_id: str) -> dict:
    return get_success_data(api.confirm_fraud_flag(flag_id, FRAUD))


# ==========================================================================
# Misc
# ==========================================================================
def create_supply_shortfall(market_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_supply_shortfall(create_supply_shortfall_payload(market_id, **overrides), OPS)
    )


def create_forecast(program_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_forecast(program_id, create_forecast_payload(**overrides), OPS)
    )
