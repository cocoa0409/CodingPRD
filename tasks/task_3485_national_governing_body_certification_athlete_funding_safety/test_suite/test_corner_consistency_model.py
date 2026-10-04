"""Corner tests: consistency_model section — writes are reconciled inside
the same operation, so a create response already carries the fully computed
values and an immediate read returns them identically."""
import pytest

from test_helpers import (
    add_verified_result,
    create_funding_agreement_payload,
    read_funding_agreement,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    validate_success,
)


def test_immediate_consistency_create_read(api, committee_admin_headers):
    """PRD §3.5: "Creation computes `trailing_points`, `season_points`, the
    `tier`, and `monthly_stipend_cents` from the athlete's verified results as
    of the current logical clock, per §3.4."
    PRD §2.9: "State in this system propagates immediately: when a
    transition's preconditions are met, every dependent resource the
    transition touches is reconciled inside the same operation, with no
    deferred work."
    PRD §3.4: "The tier fixes `monthly_stipend_cents`: 300000 cents monthly
    for `TIER_A`, 200000 for `TIER_B`, 100000 for `TIER_C`, and 0 for `NONE`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/immediate_consistency_create_read
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Immediate Test", date_of_birth="2000-01-01"
    )
    # One VERIFIED 1st/A result: 40 * 1.5 = 60.00 points.
    add_verified_result(
        athlete["id"],
        event_grade="A",
        placing=1,
        event_date="2026-08-01T00:00:00Z",
        event_name="August Cup",
        api=api,
    )
    set_logical_clock("2026-10-01T00:00:00Z", api=api)

    create_resp = api.create_funding_agreement(
        athlete["id"],
        create_funding_agreement_payload(
            coverage_start="2026-10-01T00:00:00Z",
            coverage_end="2027-04-01T00:00:00Z",
            points_method="TRAILING_365",
        ),
        committee_admin_headers,
    )
    created = validate_success(create_resp, 201)
    # Computed synchronously on the create response, not deferred to a read.
    assert created["trailing_points"] == pytest.approx(60.0, abs=1e-9)
    assert created["tier"] == "TIER_B"
    assert created["monthly_stipend_cents"] == 200000

    reread = read_funding_agreement(created["id"], api=api)
    assert reread["trailing_points"] == created["trailing_points"]
    assert reread["tier"] == created["tier"]
    assert reread["monthly_stipend_cents"] == created["monthly_stipend_cents"]
