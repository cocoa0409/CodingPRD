"""Drought-contingency shortage-sharing agreements.

Covers the dual allocation bases diverging on identical inputs across
activation, the pinned evaluation order of the sharing formula (rounded
shares before the junior-only cap), the ratification quorum flip, the
RATIFIED precondition on activation, the shortage-tier precondition, and
the duplicate-ratify rejection - PRD §3.3 and §3.4.
"""

from test_helpers import (
    ApiErrorId,
    REGIONAL_DIRECTOR_HEADERS,
    factories,
    fixtures,
    make_district_manager_headers,
    validate_error,
)

DIRECTOR = REGIONAL_DIRECTOR_HEADERS


def _shortage_world(api):
    """An announced year in real shortage: declared 5,000 (snowpack 50,
    runoff 3,000 on the small reservoir, January publish), tier TIER_1, and
    waterfall lines 5,000 senior / 0 junior."""
    return fixtures.setup_announced_year(api, snowpack=50, runoff=3_000)


def test_alloc_waterfall_vs_sharing_dual_basis(api):
    """Identical inputs under two bases diverge: at declared 5,000 the
    priority waterfall gives senior 5,000 / junior 0, while the activated
    70/40 shortage-sharing agreement recomputes the same lines in place to
    senior 4,200 / junior 800.

    PRD §3.3: "Under the priority waterfall, contracts are served with all
    `SENIOR` contracts before any `JUNIOR` contract, and within a class by
    contract `created_at` ascending with ties broken by `contract_number`
    ascending; walking that order, each contract's `allocated_af` is the
    lesser of its `max_annual_quantity_af` and the supply still remaining"
    PRD §3.4: "Activation stamps `activated_water_year_label` — null until
    activation — with the supplied label and immediately re-bases the year:
    the current `PUBLISHED` announcement's `allocation_basis` becomes
    `SHORTAGE_SHARING`, its allocation lines are recomputed in place under
    the sharing formula with their carried delivery and transfer totals
    preserved, the affected lines' `remaining_af` is recomputed, and the
    curtailment cascade then runs exactly as it does at publish."
    PRD §3.4: "The contrast with the priority waterfall is real: given the
    same year, the same contracts, and the same declared supply,
    guarantee-percentage sharing and strict priority generally produce
    different per-contract allocations."

    Design: Difficulty/dual_variant_calc/alloc_waterfall_vs_sharing_dual_basis
    """
    world = _shortage_world(api)
    announcement = world["announcement"]
    assert announcement["declared_supply_af"] == 5_000
    assert announcement["shortage_tier"] == "TIER_1"
    assert announcement["allocation_basis"] == "PRIORITY_WATERFALL"

    senior_waterfall = world["line_sr"]["allocated_af"]
    junior_waterfall = world["line_jr"]["allocated_af"]
    assert senior_waterfall == 5_000, "waterfall: min(6,000, 5,000)"
    assert junior_waterfall == 0, "waterfall: min(4,000, 0)"

    agreement = fixtures.setup_shortage_agreement(api, world, activate=True)
    assert agreement["status"] == "ACTIVATED"
    assert agreement["activated_water_year_label"] == 2_027

    announcement_after = world["announcement"]  # refreshed after activation
    assert announcement_after["allocation_basis"] == "SHORTAGE_SHARING"
    assert announcement_after["declared_supply_af"] == 5_000, (
        "activation recomputes lines, not the declared supply"
    )
    assert announcement_after["shortage_tier"] == "TIER_1"

    # TIER_1 guarantees 70% senior / 40% junior: raw shares 4,200 and 1,600
    # total 5,800, so the junior line absorbs the whole 800 excess.
    assert world["line_sr"]["allocated_af"] == 4_200
    assert world["line_jr"]["allocated_af"] == 800
    assert world["line_sr"]["allocated_af"] != senior_waterfall
    assert world["line_jr"]["allocated_af"] != junior_waterfall


def test_tier_share_cap_evaluation_order(api):
    """The sharing formula's order is pinned: declared supply and tier are
    fixed first, per-contract shares are round-half-up computed before any
    cap, and only JUNIOR lines absorb the excess - the senior share of 4,200
    is never reduced and the cap never feeds back into the tier.

    PRD §3.4: "Each `ACTIVE` contract's raw share is then its
    `max_annual_quantity_af` multiplied by the agreement's guarantee
    percentage for the classified tier and the contract's `priority_class`,
    rounded half up to whole acre-feet per contract — this per-contract
    rounding happens before any cap is applied. If the raw shares total more
    than `declared_supply_af`, `JUNIOR` lines are reduced newest-first
    (contract `created_at` descending, ties broken by `contract_number`
    descending), each reduced by the outstanding excess but never below zero,
    until the total fits; `SENIOR` lines are never reduced."

    Design: Difficulty/combinatorial_formula/tier_share_cap_evaluation_order
    """
    world = _shortage_world(api)
    announcement_id = world["announcement"]["id"]
    fixtures.setup_shortage_agreement(api, world, activate=True)

    # Senior raw share round_half_up(6,000 * 0.70) = 4,200 survives the cap.
    assert world["line_sr"]["allocated_af"] == 4_200
    # Junior raw share round_half_up(4,000 * 0.40) = 1,600 absorbs exactly
    # the 800 excess (raw total 5,800 - declared 5,000).
    assert world["line_jr"]["allocated_af"] == 800

    announcement = fixtures.find_announcement(api, world["year"]["id"], announcement_id)
    assert announcement["shortage_tier"] == "TIER_1", "the cap does not reclassify the tier"
    assert announcement["declared_supply_af"] == 5_000, "the cap consumes supply, not recomputes it"
    assert announcement["allocation_basis"] == "SHORTAGE_SHARING"


def test_ratify_reaching_quorum_flips_agreement_ratified(api):
    """Ratification is cumulative: with quorum 2 the first ratify keeps the
    agreement PROPOSED and the second - by a different district - flips it to
    RATIFIED.

    PRD §3.4: "A `DistrictManager` ratifies the agreement; the caller's
    district — the district whose `id` is their `X-User-ID` — is appended to
    `signatory_district_ids`, and a district that has already ratified is
    refused with `ERR_ALREADY_RATIFIED`."
    PRD §3.4: "The moment the signatory count reaches
    `quorum_district_count`, the agreement's `status` flips from `PROPOSED`
    to `RATIFIED` automatically."

    Design: Corner/state_machines/ratify_reaching_quorum_flips_agreement_ratified
    """
    world = fixtures.setup_project(api, reservoir_profile=None, contract_plan=None)
    agreement = fixtures.create_agreement(api, quorum_district_count=2)
    assert agreement["status"] == "PROPOSED"
    assert agreement["signatory_district_ids"] == []

    senior_id = world["district_sr"]["id"]
    junior_id = world["district_jr"]["id"]

    agreement = fixtures.ratify_agreement(api, agreement["id"], senior_id)
    assert agreement["status"] == "PROPOSED", "one of two ratifications is below quorum"
    assert agreement["signatory_district_ids"] == [senior_id]

    agreement = fixtures.ratify_agreement(api, agreement["id"], junior_id)
    assert agreement["status"] == "RATIFIED", "quorum reached exactly at 2"
    assert agreement["signatory_district_ids"] == [senior_id, junior_id]


def test_activate_unratified_agreement_returns_invalid_state(api):
    """activate requires RATIFIED: a PROPOSED agreement fails 409
    ERR_INVALID_STATE. The named water year is opened first so the priority-4
    existence check passes and the priority-6 state gate is the rejecting
    check (PRD §2.9: "an earlier failure masks every later one").

    PRD §3.4: "A `RegionalDirector` activates a `RATIFIED` agreement —
    activating from any other status fails with `ERR_INVALID_STATE` — by
    naming a `water_year_label`."

    Design: Corner/state_machines/activate_unratified_agreement_returns_invalid_state
    """
    world = fixtures.setup_project(api, reservoir_profile=None, contract_plan=None)
    fixtures.open_year(api, world)  # label 2027 exists; only the state gate can reject
    agreement = fixtures.create_agreement(api, quorum_district_count=2)  # zero ratifications

    validate_error(
        api.activate_shortage_agreement(
            agreement["id"], factories.activate_agreement_payload(2_027), DIRECTOR
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )

    agreement = fixtures.get_agreement(api, agreement["id"])
    assert agreement["status"] == "PROPOSED"
    assert agreement["activated_water_year_label"] is None


def test_activate_against_normal_tier_year_returns_activation_conflict(api):
    """Activation is gated on real shortage: a RATIFIED agreement targeting a
    year whose current announcement is tier NONE fails 409
    ERR_ACTIVATION_CONFLICT.

    PRD §3.4: "that year's current published announcement must carry a
    `shortage_tier` of `TIER_1` or `TIER_2`, since sharing is meaningless in
    a non-shortage year (otherwise `ERR_ACTIVATION_CONFLICT`)"

    Design: Corner/state_machines/activate_against_normal_tier_year_returns_activation_conflict
    """
    world = fixtures.setup_announced_year(api)  # declared 7,500 -> tier NONE
    assert world["announcement"]["shortage_tier"] == "NONE"

    agreement = fixtures.setup_shortage_agreement(api, world, quorum=1, ratifiers=("sr",))
    assert agreement["status"] == "RATIFIED"

    validate_error(
        api.activate_shortage_agreement(
            agreement["id"], factories.activate_agreement_payload(2_027), DIRECTOR
        ),
        ApiErrorId.ERR_ACTIVATION_CONFLICT,
    )

    agreement = fixtures.get_agreement(api, agreement["id"])
    assert agreement["status"] == "RATIFIED", "a refused activation leaves the agreement RATIFIED"


def test_duplicate_ratify_same_district_returns_already_ratified(api):
    """Signatories are a set: the same district ratifying twice fails 409
    ERR_ALREADY_RATIFIED and the signatory list does not grow.

    PRD §3.4: "the caller's district — the district whose `id` is their
    `X-User-ID` — is appended to `signatory_district_ids`, and a district
    that has already ratified is refused with `ERR_ALREADY_RATIFIED`."

    Design: Corner/state_machines/duplicate_ratify_same_district_returns_already_ratified
    """
    world = fixtures.setup_project(api, reservoir_profile=None, contract_plan=None)
    agreement = fixtures.create_agreement(api, quorum_district_count=2)
    senior_id = world["district_sr"]["id"]
    fixtures.ratify_agreement(api, agreement["id"], senior_id)

    validate_error(
        api.ratify_shortage_agreement(
            agreement["id"], make_district_manager_headers(senior_id)
        ),
        ApiErrorId.ERR_ALREADY_RATIFIED,
    )

    agreement = fixtures.get_agreement(api, agreement["id"])
    assert agreement["signatory_district_ids"] == [senior_id]
    assert agreement["status"] == "PROPOSED"
