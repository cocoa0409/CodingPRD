"""Activation, the frozen export rate, grandfathering and the savings projection.

Activation is the moment two values are pinned for the life of the deal, and the
savings projection is the read that shows which net-metering terms actually
apply afterwards.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import assert_state_dimensions
from test_helpers.fixtures import (
    activate,
    book_ppa,
    book_lease,
    make_homeowner,
    make_successor_tariff,
    make_tariff,
    read_agreement,
    record_period,
    reconcile,
    set_clock,
)

PROJECTION_KEYS = [
    "agreement_id",
    "contract_year",
    "self_consumed_kwh",
    "exported_kwh",
    "effective_export_rate_millicents",
    "avoided_import_cents",
    "export_credit_cents",
    "utility_fixed_cents",
    "solar_cost_cents",
    "annual_savings_cents",
    "tariff_grandfathered",
]


def test_activation_freezes_the_export_rate_and_a_later_move_never_refreezes_it(api):
    """The rate snapshotted at activation survives a move onto a successor.

    §3.2: "`grandfathered_export_rate_millicents` is snapshotted from the
    attached tariff's `export_credit_rate_per_kwh_millicents` and never changes
    again, and `contract_end_date` is (re)computed from `contract_start_date` and
    `term_years`." §3.2 on the move: "The agreement's `tariff_id` is replaced,
    `tariff_grandfathered` is re-evaluated by the same three-part test against
    the new schedule, and the agreement's `version` advances. Crucially,
    `grandfathered_export_rate_millicents` is **not** re-snapshotted".

    Design: Corner/state_machines/activation_freezes_the_grandfathered_export_rate_forever
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    legacy = make_tariff(api)
    successor = make_successor_tariff(
        api,
        tariff_code="NEM3-SUCCESSOR",
        effective_from_date="2026-04-15",
        grandfathers_predecessors=True,
    )
    agreement = book_ppa(api, owner["id"], legacy["id"])

    activated = activate(api, agreement["id"])

    assert activated["grandfathered_export_rate_millicents"] == 28000
    assert activated["tariff_grandfathered"] is False
    assert activated["contract_end_date"] == "2044-12-31"
    assert activated["version"] == 2
    assert_state_dimensions(activated, lifecycle_state=C.LIFECYCLE_ACTIVE)

    moved = validate_success(
        api.apply_tariff(
            agreement["id"], {"tariff_id": successor["id"]}, U.admin_headers()
        ),
        200,
    )

    assert moved["tariff_id"] == successor["id"]
    assert moved["tariff_grandfathered"] is True
    assert moved["grandfathered_export_rate_millicents"] == 28000
    assert moved["version"] == 3


def test_replaying_activation_on_an_active_agreement_is_rejected(api):
    """Activation is not idempotent and a replay changes nothing.

    §2.10 rung 8: "HTTP 409 on every action endpoint whose target is not in a
    state from which the requested transition exists." §3.2 defines the only legal
    activation: "Activation moves the contract from `DRAFT` to `ACTIVE`".

    Design: Corner/state_machines/second_activate_on_an_active_agreement_is_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(api, owner["id"], schedule["id"])

    first = activate(api, agreement["id"])
    assert first["version"] == 2

    validate_error(
        api.activate_agreement(agreement["id"], U.agent_headers()),
        E.ERR_INVALID_STATE_TRANSITION,
    )

    unchanged = read_agreement(api, agreement["id"])
    assert unchanged["version"] == 2
    assert unchanged["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert unchanged["grandfathered_export_rate_millicents"] == 28000


def test_projection_imports_at_the_current_rate_and_exports_at_the_frozen_one(api):
    """A grandfathered site re-prices imports but keeps the legacy export rate.

    §3.2: "The export rate that applies — `effective_export_rate_millicents` — is
    the frozen `grandfathered_export_rate_millicents` when `tariff_grandfathered`
    is true, and the current tariff's `export_credit_rate_per_kwh_millicents`
    otherwise; the import side always uses the *current* tariff regardless of
    grandfathering." §3.2 also pins the split: "`self_consumed_kwh` is the annual
    production multiplied by 0.42 and rounded to a whole kilowatt-hour, and
    `exported_kwh` is simply the remainder of the annual production after
    subtracting it".

    Design: Corner/calculations/savings_projection_uses_current_retail_but_grandfathered_export_rate
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    legacy = make_tariff(api)
    successor = make_successor_tariff(
        api,
        tariff_code="NEM3-SUCCESSOR",
        effective_from_date="2026-04-15",
        grandfathers_predecessors=True,
    )
    agreement = book_ppa(api, owner["id"], legacy["id"])
    activate(api, agreement["id"])
    validate_success(
        api.apply_tariff(
            agreement["id"], {"tariff_id": successor["id"]}, U.admin_headers()
        ),
        200,
    )

    projection = validate_success(
        api.savings_projection(agreement["id"], U.homeowner_headers(owner["id"])), 200
    )

    assert projection["contract_year"] == 2
    assert projection["tariff_grandfathered"] is True
    assert projection["self_consumed_kwh"] == 4032
    assert projection["exported_kwh"] == 5568
    assert projection["self_consumed_kwh"] + projection["exported_kwh"] == 9600
    assert projection["effective_export_rate_millicents"] == 28000
    assert projection["avoided_import_cents"] == 153216
    assert projection["export_credit_cents"] == 155904
    assert projection["utility_fixed_cents"] == 28800
    assert projection["solar_cost_cents"] == 145704
    assert projection["annual_savings_cents"] == 134616


def test_projection_may_go_negative_on_a_successor_that_does_not_grandfather(api):
    """Equality of dates is not protection, and the disclosure may be negative.

    §3.2: "A system whose `contract_start_date` is the very same day as the
    tariff's `effective_from_date` is not grandfathered, and protection lapses on
    the exact anniversary rather than the day after it." §3.2 on the bottom line:
    "`annual_savings_cents` is `avoided_import_cents` plus `export_credit_cents`,
    minus `utility_fixed_cents`, minus `solar_cost_cents` — a figure that is
    allowed to come out negative".

    Design: Corner/calculations/savings_projection_goes_negative_on_a_successor_that_does_not_grandfather
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api, full_name="Iris Kwan", fico_score=705, dti_ratio=0.31,
                           monthly_income_cents=980000)
    legacy = make_tariff(api, effective_from_date="2020-04-01")
    successor = make_successor_tariff(
        api,
        tariff_code="NEM3-NOGF",
        effective_from_date="2026-04-15",
        grandfathers_predecessors=False,
    )
    agreement = book_lease(
        api,
        owner["id"],
        legacy["id"],
        site_address="51 Marsh Ln, Hayward CA",
        contract_start_date="2020-04-01",
    )

    activated = activate(api, agreement["id"])
    assert activated["tariff_grandfathered"] is False

    before = validate_success(
        api.savings_projection(agreement["id"], U.agent_headers()), 200
    )
    assert before["contract_year"] == 7
    assert before["self_consumed_kwh"] == 3528
    assert before["exported_kwh"] == 4872
    assert before["effective_export_rate_millicents"] == 28000
    assert before["solar_cost_cents"] == 173304
    assert before["annual_savings_cents"] == 59772

    validate_success(
        api.apply_tariff(
            agreement["id"], {"tariff_id": successor["id"]}, U.admin_headers()
        ),
        200,
    )

    after = validate_success(
        api.savings_projection(agreement["id"], U.agent_headers()), 200
    )
    assert after["tariff_grandfathered"] is False
    assert after["effective_export_rate_millicents"] == 7500
    assert after["avoided_import_cents"] == 134064
    assert after["export_credit_cents"] == 36540
    assert after["utility_fixed_cents"] == 28800
    assert after["annual_savings_cents"] == -31500


def test_savings_projection_returns_every_declared_key_and_writes_nothing(api):
    """The projection is a computed read: same answer twice, no version movement.

    §3.2 declares the shape: the projection "reports `agreement_id`, the projected
    `contract_year`, `self_consumed_kwh`, `exported_kwh`,
    `effective_export_rate_millicents`, `avoided_import_cents`,
    `export_credit_cents`, `utility_fixed_cents`, `solar_cost_cents`,
    `annual_savings_cents` and `tariff_grandfathered`". §2.4: "`version`, an
    integer that begins at 1 and increases by exactly one on every mutation of that
    resource."

    Design: Corner/endpoints/savings_projection_computed_read_returns_the_derived_object_without_mutating
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(api, owner["id"], schedule["id"])
    activated = activate(api, agreement["id"])

    response = api.savings_projection(agreement["id"], U.homeowner_headers(owner["id"]))
    projection = validate_success(response, 200)

    assert response.json()["response_type"] == "object"
    for key in PROJECTION_KEYS:
        assert key in projection, f"the projection must report {key}"
    assert projection["agreement_id"] == agreement["id"]
    assert projection["contract_year"] == 2
    assert projection["self_consumed_kwh"] == 4032
    assert projection["exported_kwh"] == 5568
    assert projection["effective_export_rate_millicents"] == 28000
    assert projection["avoided_import_cents"] == 131040
    assert projection["export_credit_cents"] == 155904
    assert projection["utility_fixed_cents"] == 18000
    assert projection["solar_cost_cents"] == 145704
    assert projection["annual_savings_cents"] == 123240
    assert projection["tariff_grandfathered"] is False

    again = validate_success(
        api.savings_projection(agreement["id"], U.homeowner_headers(owner["id"])), 200
    )
    assert again == projection
    assert read_agreement(api, agreement["id"])["version"] == activated["version"]


def test_apply_tariff_reprices_the_projection_but_keeps_the_frozen_rate(api):
    """The move changes which export rate is applied, not the frozen snapshot.

    §3.2: "Only a `PortfolioAdmin` may move a host site onto a different
    published schedule — for instance onto a `NEM_3` successor after the utility
    retires the older generation." §3.2: "`avoided_import_cents` is
    `self_consumed_kwh` multiplied by the current tariff's
    `retail_rate_per_kwh_millicents`, divided by 1000 and rounded to a whole
    cent."

    Design: Corner/endpoints/apply_tariff_conditional_action_reprices_savings_but_keeps_the_frozen_rate
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    legacy = make_tariff(api)
    successor = make_successor_tariff(
        api,
        tariff_code="NEM3-NOGF",
        effective_from_date="2026-01-01",
        grandfathers_predecessors=False,
    )
    agreement = book_ppa(api, owner["id"], legacy["id"])
    activated = activate(api, agreement["id"])

    moved = validate_success(
        api.apply_tariff(
            agreement["id"], {"tariff_id": successor["id"]}, U.admin_headers()
        ),
        200,
    )

    assert moved["tariff_id"] == successor["id"]
    assert moved["tariff_grandfathered"] is False
    assert moved["version"] > activated["version"]
    assert moved["grandfathered_export_rate_millicents"] == 28000

    projection = validate_success(
        api.savings_projection(agreement["id"], U.agent_headers()), 200
    )
    assert projection["effective_export_rate_millicents"] == 7500
    assert projection["avoided_import_cents"] == 153216
    assert projection["export_credit_cents"] == 41760
    assert projection["utility_fixed_cents"] == 28800
    assert projection["solar_cost_cents"] == 145704
    assert projection["annual_savings_cents"] == 20472


def test_apply_tariff_is_admin_only_and_resolves_its_body_reference(api):
    """Only the admin may move the site, and the replacement must exist.

    §3.2: "Only a `PortfolioAdmin` may move a host site onto a different
    published schedule". §2.10 rung 5: "HTTP 404 with the not-found code of the
    collection named by the unresolvable foreign key in the body".

    Design: Corner/endpoints/apply_tariff_conditional_action_reprices_savings_but_keeps_the_frozen_rate
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    legacy = make_tariff(api)
    successor = make_successor_tariff(
        api,
        tariff_code="NEM3-NOGF",
        effective_from_date="2026-01-01",
        grandfathers_predecessors=False,
    )
    agreement = book_ppa(api, owner["id"], legacy["id"])
    activated = activate(api, agreement["id"])

    validate_error(
        api.apply_tariff(
            agreement["id"], {"tariff_id": successor["id"]}, U.agent_headers()
        ),
        E.ERR_UNAUTHORIZED,
    )
    validate_error(
        api.apply_tariff(
            agreement["id"],
            {"tariff_id": "00000000-0000-4000-8000-00000000000c"},
            U.admin_headers(),
        ),
        E.ERR_TARIFF_NOT_FOUND,
    )

    untouched = read_agreement(api, agreement["id"])
    assert untouched["tariff_id"] == legacy["id"]
    assert untouched["version"] == activated["version"]


def _april_of_contract_year_two(api):
    """A PPA on the pinned terms with April 2026 recorded at 902 metered kWh."""
    set_clock(api, "2026-05-15T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(
        api,
        owner["id"],
        schedule["id"],
        escalator_pct=0.029,
        base_ppa_rate_per_kwh_millicents=14750,
        guaranteed_annual_kwh=9600,
        guarantee_band_pct=0.05,
        contract_start_date="2025-01-01",
    )
    activate(api, agreement["id"])
    month = record_period(api, agreement["id"], 2026, 4, 902)
    return agreement, month


def test_recording_april_derives_contract_year_two_expectation_before_any_money(api):
    """The month's expectation is derived from the seasonality curve alone.

    §3.3: "`gross_expected_kwh` is `guaranteed_annual_kwh` multiplied by the
    weight for the month's `period_month` and rounded to a whole kilowatt-hour —
    and that rounding happens **before** any availability adjustment is applied."
    §3.3 also pins the invoice date: "The `due_date` is the last calendar day of
    the period month advanced by twenty-one days."

    Design: Difficulty/combinatorial_formula/ppa_rate_rounded_before_multiplying_metered_kwh
    """
    _, month = _april_of_contract_year_two(api)

    assert month["contract_year"] == 2
    assert month["due_date"] == "2026-05-21"
    assert month["gross_expected_kwh"] == 941
    assert month["excused_days"] == 0
    assert month["adjusted_expected_kwh"] == 941
    assert month["status"] == C.PERIOD_RECORDED


def test_the_rounded_millicent_rate_is_what_multiplies_metered_kwh(api):
    """Rounding the rate first yields 13691; deferring it yields 13690.

    §3.2: "**This rounding order is pinned:** the per-kilowatt-hour rate is
    rounded to a whole millicent first, and it is the rounded rate that multiplies
    the energy figure." §3.3 step one: "`gross_due_cents` is, for a `PPA`, the
    month's `escalated_rate_millicents` multiplied by `metered_kwh`, divided by
    1000 and rounded to a whole cent".

    Design: Difficulty/combinatorial_formula/ppa_rate_rounded_before_multiplying_metered_kwh
    """
    _, month = _april_of_contract_year_two(api)

    settled = reconcile(api, month["id"], issue_credit=False)

    assert settled["escalated_rate_millicents"] == 15178
    assert settled["escalated_monthly_rent_cents"] == 0
    assert settled["guarantee_floor_kwh"] == 894
    assert settled["shortfall_kwh"] == 0
    assert settled["credit_cents"] == 0
    assert settled["gross_due_cents"] == 13691
    assert settled["gross_due_cents"] != 13690
    assert settled["credit_applied_cents"] == 0
    assert settled["net_due_cents"] == 13691
    assert settled["late_fee_cents"] == 0
    assert settled["total_invoiced_cents"] == 13691
    assert settled["status"] == C.PERIOD_RECONCILED
