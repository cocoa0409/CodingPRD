"""One incident history, two liability windows, two different verdicts."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.fixtures import (
    add_sample_kit,
    book_consultation,
    charter_territory,
    checkout_kit,
    hire_designer,
    intake_lead,
    read_designer,
    return_kit,
    set_clock,
)
from test_helpers.test_users import franchisee_headers


def _three_late_returns(api, liability_window, postal_code, legal_name,
                        designer_name, kit_code, customer_name, source):
    """Book, return late, and re-book one kit three times for a single designer.

    Two returns are stamped in August 2026 and the third on 2027-03-06, so the
    180-day window that opens on 2026-09-07 contains only the last of the three.
    """
    territory = charter_territory(api, legal_name=legal_name,
                                 postal_codes=[postal_code],
                                 royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window=liability_window)
    designer = hire_designer(api, territory, full_name=designer_name,
                             home_postal_code=postal_code)
    kit = add_sample_kit(api, territory, kit_code=kit_code,
                         replacement_value_cents=50000)
    lead = intake_lead(api, territory, customer_name=customer_name,
                       postal_code=postal_code, source=source,
                       requested_at="2026-08-03T00:00:00.000Z")
    consultation = book_consultation(api, designer, lead,
                                     service_postal_code=postal_code)
    return {"territory": territory, "designer": designer, "kit": kit,
            "consultation": consultation}


HOLDS = (
    ("2026-08-01T09:00:00.000Z", "2026-08-05T17:00:00.000Z",
     "2026-08-10T10:00:00.000Z"),
    ("2026-08-11T09:00:00.000Z", "2026-08-15T17:00:00.000Z",
     "2026-08-20T10:00:00.000Z"),
    ("2027-03-01T10:00:00.000Z", "2027-03-03T17:00:00.000Z",
     "2027-03-06T12:00:00.000Z"),
)


def _run_identical_histories(api, worlds):
    """Drive both designers through the same three hold-and-late-return cycles.

    The two designers move in lockstep on one logical clock, so their incident
    histories are identical in every respect except the owning territory's window.
    Returns each designer's final check-out.
    """
    finals = []
    for index, (hold_start_at, hold_end_at, return_clock) in enumerate(HOLDS):
        if hold_start_at.startswith("2027"):
            set_clock(api, "2027-03-01T09:00:00.000Z")
        checkouts = [
            checkout_kit(api, world["designer"], world["kit"],
                         world["consultation"], hold_start_at, hold_end_at)
            for world in worlds
        ]
        set_clock(api, return_clock)
        returned = [return_kit(api, world["designer"], checkout)
                    for world, checkout in zip(worlds, checkouts)]
        if index == len(HOLDS) - 1:
            finals = returned
    return finals


def _both_designers(api):
    """One rolling-window territory and one lifetime-window territory, side by side."""
    rolling = _three_late_returns(api, "ROLLING_180D", "30301",
                                  "Northgate Blinds LLC", "Dana Reed",
                                  "SHEERS-A", "Ana Ruiz", "WEB_FORM")
    lifetime = _three_late_returns(api, "LIFETIME", "30401",
                                   "Southgate Blinds LLC", "Milo Vance",
                                   "SHEERS-B", "Bo Chen", "REFERRAL")
    return rolling, lifetime


def test_the_two_windows_disagree_by_eighteen_points_on_one_history(api):
    """Three late returns, two of them stale: 91 and ACTIVE against 73 and SUSPENDED.

    "Which rows count depends on the owning territory's `liability_window`. Under
    `ROLLING_180D` a row counts only when its own stamp is at or after the logical
    clock minus 180 days; under `LIFETIME` every row counts however old it is."

    "The window choice can be decisive on its own: three late sample returns of
    which two are older than 180 days score 73 under `LIFETIME` and suspend the
    designer, where `ROLLING_180D` scores 91 and does not."

    Design: Difficulty/dual_variant_calc/liability_window_variant_diverges_on_two_designers_with_identical_incident_history
    """
    rolling, lifetime = _both_designers(api)
    _run_identical_histories(api, [rolling, lifetime])

    windowed = read_designer(api, rolling["territory"],
                             rolling["designer"]["id"])
    assert windowed["late_sample_return_count"] == 1
    assert windowed["remeasure_liability_score"] == 91
    assert windowed["status"] == "ACTIVE"

    forever = read_designer(api, lifetime["territory"],
                            lifetime["designer"]["id"])
    assert forever["late_sample_return_count"] == 3
    assert forever["remeasure_liability_score"] == 73
    assert forever["status"] == "SUSPENDED"

    assert (windowed["remeasure_liability_score"]
            - forever["remeasure_liability_score"]) == 18


def test_the_third_return_is_priced_identically_for_both_designers(api):
    """The fee that drives the divergence is itself the same 2250 cents on both rows.

    "When `days_late` is at most fourteen, the kit is fined rather than written off:
    `late_fee_cents` is 750 cents per day late, capped at the kit's
    `replacement_value_cents` so that a fine can never exceed the asset."

    "Otherwise `days_late` is the elapsed time from `due_at` to `returned_at` divided
    by one day and rounded **up** to the next whole number, so one millisecond past
    the due instant is already one day late and a return exactly on the due instant
    is free."

    Design: Difficulty/dual_variant_calc/liability_window_variant_diverges_on_two_designers_with_identical_incident_history
    """
    rolling, lifetime = _both_designers(api)
    last_rolling, last_lifetime = _run_identical_histories(
        api, [rolling, lifetime])

    for final in (last_rolling, last_lifetime):
        assert final["status"] == "RETURNED"
        assert final["days_late"] == 3
        assert final["late_fee_cents"] == 2250

    # Identical histories: the same three loans on each kit, none of them lost.
    for world in (rolling, lifetime):
        kit = validate_success(api.get_sample_kit(
            world["kit"]["id"], franchisee_headers(world["territory"]["id"])))
        assert kit["status"] == "AVAILABLE"
        assert kit["loan_count"] == 3
        assert kit["open_loan_count"] == 0


def test_a_past_dated_appointment_survives_the_suspension_cascade(api):
    """The lifetime designer is suspended, yet the appointment already behind them stands.

    "Every consultation of that designer that is still `SCHEDULED` and whose
    `scheduled_start_at` is at or after the logical clock moves `SCHEDULED →
    CANCELLED`, and every install job of that designer that is still `SCHEDULED` and
    whose `scheduled_start_at` is at or after the logical clock moves
    `install_status` `SCHEDULED → CANCELLED`."

    Design: Difficulty/dual_variant_calc/liability_window_variant_diverges_on_two_designers_with_identical_incident_history
    """
    rolling, lifetime = _both_designers(api)
    _run_identical_histories(api, [rolling, lifetime])

    assert read_designer(api, lifetime["territory"],
                         lifetime["designer"]["id"])["status"] == "SUSPENDED"

    stale_appointment = validate_success(api.get_consultation(
        lifetime["consultation"]["id"],
        franchisee_headers(lifetime["territory"]["id"])))
    assert stale_appointment["status"] == "SCHEDULED"
