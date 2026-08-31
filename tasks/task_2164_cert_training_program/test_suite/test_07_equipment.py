"""The equipment cabinet: the issuance selector, the fiscal ceiling and loss settlement."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_asset,
    assert_equipment_issuance,
    current_program_version,
    issue_kit,
    read_asset,
    read_program,
    read_trainee,
    set_clock,
    setup_credentialed_trainees,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
ISSUER = TEST_USERS["issuer_coordinator_headers"]
TWO_TRAINEES = (("tara", "Tara Nolan"), ("dev", "Dev Okafor"))


def _two_kits_on_issue():
    """A graduate holding a 17700-cent backpack and an 8300-cent radio kit, both 36 days old."""
    ctx = setup_credentialed_trainees(mint_at="2026-08-05T16:00:00Z")
    add_asset(ctx, "backpack", "BP-0001", "BACKPACK_STANDARD", 17700)
    add_asset(ctx, "radio", "RK-0001", "RADIO_KIT", 8300)
    ctx["issuance_backpack"] = issue_kit(ctx, "tara", "BACKPACK_STANDARD",
                                         store_as="backpack")
    ctx["issuance_radio"] = issue_kit(ctx, "tara", "RADIO_KIT", store_as="radio")
    set_clock("2026-09-10T16:00:00Z")
    return ctx


# ---------------------------------------------------------------------------
# The two settlement variants
# ---------------------------------------------------------------------------

def test_a_live_credential_settles_a_lost_kit_at_its_depreciated_value(api):
    """PRD §3.7: "`months_held` is the number of whole days between `issued_on` and
    `lost_reported_on`, divided by 30 and rounded down to a whole number, so a kit held 89
    days counts as 2 months and one held exactly 90 days counts as 3. `residual_pct` is 1.00
    reduced by 0.015 for each such month, floored at 0.40 so that no kit ever settles below
    40% of its value however long it was held, and the result is rounded half-up to four
    decimal places."
    PRD §3.7: "When the trainee's credential stands at `ACTIVE`, `GRACE`, or `EXPIRED`,
    `settlement_variant` is `DEPRECIATED_WRITEOFF` and `settlement_cents` is the asset's
    `unit_value_cents` multiplied by `residual_pct`, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/equipment_settlement_depreciated_vs_full_replacement
    """
    ctx = _two_kits_on_issue()

    lost = validate_success(
        api.report_lost_equipment_issuance(
            ctx["issuance_backpack"]["id"], {"note": "Kit lost during storm response"},
            LOGISTICS,
        )
    )
    assert_equipment_issuance(lost)
    assert lost["status"] == "LOST_WRITTEN_OFF"
    assert lost["months_held"] == 1
    assert round(float(lost["residual_pct"]), 4) == 0.9850
    assert lost["settlement_variant"] == "DEPRECIATED_WRITEOFF"
    assert lost["settlement_cents"] == 17435

    asset = read_asset(ctx, "backpack")
    assert asset["status"] == "LOST"
    assert asset["condition"] == "WRITTEN_OFF"


def test_a_suspended_credential_settles_the_same_kit_at_full_replacement(api):
    """PRD §3.7: "When the trainee has no credential at all, or their credential stands at
    `SUSPENDED` or `REVOKED`, `settlement_variant` is `FULL_REPLACEMENT`, depreciation is not
    applied at all, and `settlement_cents` is simply the asset's full `unit_value_cents`."
    PRD §3.7: "Finally the volunteer's `equipment_liability_cents` is recomputed as the sum
    of `settlement_cents` over every one of that trainee's issuances standing at
    `LOST_WRITTEN_OFF`, taken in `created_at` order for audit; returned and outstanding
    issuances contribute nothing."

    Design: Difficulty/dual_variant_calc/equipment_settlement_depreciated_vs_full_replacement
    """
    ctx = _two_kits_on_issue()
    validate_success(
        api.report_lost_equipment_issuance(
            ctx["issuance_backpack"]["id"], {"note": "Kit lost during storm response"},
            LOGISTICS,
        )
    )
    validate_success(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "SUSPEND"}, COORD
        )
    )

    lost = validate_success(
        api.report_lost_equipment_issuance(
            ctx["issuance_radio"]["id"], {"note": "Radio kit lost with the same kit bag"},
            LOGISTICS,
        )
    )
    assert lost["months_held"] == 1
    assert lost["settlement_variant"] == "FULL_REPLACEMENT"
    assert lost["settlement_cents"] == 8300, (
        "depreciation is not applied at all under full replacement"
    )

    assert read_trainee(ctx, "tara")["equipment_liability_cents"] == 25735
    assert read_program(ctx)["equipment_committed_cents"] == 0


# ---------------------------------------------------------------------------
# Per-line rounding before summation
# ---------------------------------------------------------------------------

def test_each_settlement_line_is_rounded_to_whole_cents_on_its_own(api):
    """PRD §2.9: "Where a monetary result is derived from a percentage, the multiplication
    is performed per line and each line is rounded to whole cents using round-half-up
    **before** the lines are summed."
    PRD §3.7: "When the trainee's credential stands at `ACTIVE`, `GRACE`, or `EXPIRED`,
    `settlement_variant` is `DEPRECIATED_WRITEOFF` and `settlement_cents` is the asset's
    `unit_value_cents` multiplied by `residual_pct`, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/equipment_liability_rounds_per_line_before_summation
    """
    ctx = _two_kits_on_issue()

    backpack = validate_success(
        api.report_lost_equipment_issuance(
            ctx["issuance_backpack"]["id"], {"note": "Backpack lost"}, LOGISTICS
        )
    )
    radio = validate_success(
        api.report_lost_equipment_issuance(
            ctx["issuance_radio"]["id"], {"note": "Radio kit lost"}, LOGISTICS
        )
    )

    # 17700 * 0.9850 is exactly 17434.5 and 8300 * 0.9850 is exactly 8175.5.
    assert backpack["settlement_cents"] == 17435
    assert radio["settlement_cents"] == 8176
    assert backpack["settlement_variant"] == "DEPRECIATED_WRITEOFF"
    assert radio["settlement_variant"] == "DEPRECIATED_WRITEOFF"


def test_the_trainee_liability_sums_the_rounded_lines_not_the_raw_products(api):
    """PRD §2.9: "Summing unrounded products and rounding the total once is expressly
    forbidden: two lines that each land on a half-cent differ by a full cent between the two
    orders, and the per-line order is the contractual one."
    PRD §3.7: "As §2.9 insists, each line is rounded to whole cents first and the rounded
    lines are then added — two lines that each fall on a half cent produce a total one cent
    different from the forbidden alternative of summing the raw products and rounding once."

    Design: Difficulty/combinatorial_formula/equipment_liability_rounds_per_line_before_summation
    """
    ctx = _two_kits_on_issue()
    validate_success(
        api.report_lost_equipment_issuance(
            ctx["issuance_backpack"]["id"], {"note": "Backpack lost"}, LOGISTICS
        )
    )
    validate_success(
        api.report_lost_equipment_issuance(
            ctx["issuance_radio"]["id"], {"note": "Radio kit lost"}, LOGISTICS
        )
    )

    liability = read_trainee(ctx, "tara")["equipment_liability_cents"]
    assert liability == 25611, (
        f"17435 + 8176 must total 25611, not the 25610 that summing raw products gives; "
        f"got {liability}"
    )
    assert read_program(ctx)["equipment_committed_cents"] == 0


# ---------------------------------------------------------------------------
# The committed-value ledger is conserved
# ---------------------------------------------------------------------------

def test_issuing_a_kit_commits_exactly_its_replacement_value(api):
    """PRD §3.7: "On commit, the chosen asset moves to `ISSUED`, its `issue_count` grows by
    1, the program's `equipment_committed_cents` grows by the asset's `unit_value_cents`, and
    the program's `version` is incremented."
    PRD §3.1: "Three derived tallies open at 0 on a new program and are maintained thereafter
    by the server: `equipment_committed_cents`, the summed replacement value of every asset
    currently out on an active issuance; `active_member_count`, the number of trainees in the
    program whose enrollment standing is either enrolled or graduated; and
    `pending_graduation_count`, the number of the program's cohorts currently sitting in
    graduation review."

    Design: Difficulty/compensating_invariant/kit_issue_then_return_conserves_program_committed_cents
    """
    ctx = setup_credentialed_trainees()
    add_asset(ctx, "backpack", "BP-0001", "BACKPACK_STANDARD", 17700)
    assert read_program(ctx)["equipment_committed_cents"] == 0

    issuance = issue_kit(ctx, "tara", "BACKPACK_STANDARD", store_as="backpack")
    assert issuance["status"] == "ISSUED"
    assert issuance["asset_id"] == ctx["assets"]["backpack"]["id"]
    assert read_program(ctx)["equipment_committed_cents"] == 17700

    asset = read_asset(ctx, "backpack")
    assert asset["status"] == "ISSUED"
    assert asset["issue_count"] == 1


def test_returning_the_kit_restores_the_committed_ledger_without_drift(api):
    """PRD §3.7: "Either way the program's `equipment_committed_cents` falls by the asset's
    `unit_value_cents` and the program's `version` is incremented."
    PRD §3.7: "`returned_on` is stamped from the logical clock, the asset's `condition` is
    set to the supplied value, and the asset's `status` becomes `IN_STOCK` when the condition
    is `SERVICEABLE` — putting it back in the candidate pool — or `RETIRED` when the condition
    is `DAMAGED`, permanently removing it."
    PRD §2.9: "Each is defined as an aggregate over primary rows, and every operation that
    changes those rows must leave the counter equal to that aggregate — which is what makes an
    increment on one path and a decrement on the reverse path mandatory rather than cosmetic."

    Design: Difficulty/compensating_invariant/kit_issue_then_return_conserves_program_committed_cents
    """
    ctx = setup_credentialed_trainees()
    add_asset(ctx, "backpack", "BP-0001", "BACKPACK_STANDARD", 17700)
    issuance = issue_kit(ctx, "tara", "BACKPACK_STANDARD", store_as="backpack")
    assert read_program(ctx)["equipment_committed_cents"] == 17700

    returned = validate_success(
        api.return_equipment_issuance(
            issuance["id"], {"condition": "SERVICEABLE"}, LOGISTICS
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["returned_on"] is not None

    assert read_program(ctx)["equipment_committed_cents"] == 0, "no drift after the return"
    asset = read_asset(ctx, "backpack")
    assert asset["status"] == "IN_STOCK"
    assert asset["condition"] == "SERVICEABLE"
    assert asset["issue_count"] == 1
    assert read_trainee(ctx, "tara")["equipment_liability_cents"] == 0


# ---------------------------------------------------------------------------
# Issuance is gated by a credential the request never names
# ---------------------------------------------------------------------------

def test_issuing_to_a_volunteer_without_a_live_credential_is_refused(api):
    """PRD §3.7: "The volunteer must hold a live credential — a trainee whose credential
    standing is not `ACTIVE` or `GRACE`, including a trainee with no credential at all, is
    refused with `ERR_CREDENTIAL_NOT_ACTIVE` — and a trainee may hold at most one outstanding
    issuance per `kit_type`, a second live one being refused with
    `ERR_TRAINEE_ALREADY_ISSUED_KIT`."

    Design: Difficulty/cross_entity_state_dependency/kit_issuance_requires_a_live_credential_on_the_trainee
    """
    ctx = setup_credentialed_trainees()
    add_asset(ctx, "backpack", "BP-0001", "BACKPACK_STANDARD", 17700)
    validate_success(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "SUSPEND"}, COORD
        )
    )

    version = current_program_version(ctx)
    validate_error(
        api.create_equipment_issuance(
            {
                "trainee_id": ctx["trainees"]["tara"]["id"],
                "kit_type": "BACKPACK_STANDARD",
                "expected_program_version": version,
            },
            LOGISTICS,
        ),
        ApiErrorId.ERR_CREDENTIAL_NOT_ACTIVE.value,
    )
    assert read_program(ctx)["equipment_committed_cents"] == 0
    assert read_asset(ctx, "backpack")["status"] == "IN_STOCK"


def test_reinstating_the_credential_unblocks_the_identical_issuance(api):
    """PRD §3.6: "**Reinstatement** closes that loop with `SUSPENDED → ACTIVE`, requiring
    the trainee to stand at `GRADUATED` and to hold a `passed_core_count` exactly equal to the
    number of core active curriculum modules; it moves the trainee's `currency_status` `LAPSED
    → CURRENT` and recomputes their `readiness_score`."
    PRD §3.7: "On commit, the chosen asset moves to `ISSUED`, its `issue_count` grows by 1,
    the program's `equipment_committed_cents` grows by the asset's `unit_value_cents`, and the
    program's `version` is incremented."

    Design: Difficulty/cross_entity_state_dependency/kit_issuance_requires_a_live_credential_on_the_trainee
    """
    ctx = setup_credentialed_trainees()
    add_asset(ctx, "backpack", "BP-0001", "BACKPACK_STANDARD", 17700)
    credential_id = ctx["credentials"]["tara"]["id"]
    validate_success(api.credential_status_action(credential_id, {"action": "SUSPEND"}, COORD))

    reinstated = validate_success(
        api.credential_status_action(credential_id, {"action": "REINSTATE"}, COORD)
    )
    assert reinstated["status"] == "ACTIVE"
    assert read_trainee(ctx, "tara")["currency_status"] == "CURRENT"

    issuance = issue_kit(ctx, "tara", "BACKPACK_STANDARD", store_as="backpack")
    assert issuance["asset_id"] == ctx["assets"]["backpack"]["id"]
    asset = read_asset(ctx, "backpack")
    assert asset["status"] == "ISSUED"
    assert asset["issue_count"] == 1
    assert read_program(ctx)["equipment_committed_cents"] == 17700


# ---------------------------------------------------------------------------
# The state gate is reported ahead of the fiscal ceiling
# ---------------------------------------------------------------------------

def test_credential_gate_is_reported_ahead_of_the_equipment_budget_ceiling(api):
    """PRD §2.6: "Cross-entity state preconditions, in this relative order: cohort accepting
    enrollments (`ERR_COHORT_NOT_ACCEPTING`), cohort in graduation review
    (`ERR_COHORT_NOT_IN_REVIEW`), session delivered (`ERR_SESSION_NOT_DELIVERED`), credential
    live (`ERR_CREDENTIAL_NOT_ACTIVE`), activation rostered
    (`ERR_ACTIVATION_NOT_ROSTERED`) — all 409."
    PRD §2.6: "Fiscal ceilings last of all: the equipment budget ceiling
    (`ERR_EQUIPMENT_BUDGET_EXCEEDED`, 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_fiscal_check_on_kit_issuance
    """
    ctx = setup_credentialed_trainees(budget_cents=1000)
    add_asset(ctx, "backpack", "BP-0001", "BACKPACK_STANDARD", 17700)
    validate_success(
        api.credential_status_action(
            ctx["credentials"]["tara"]["id"], {"action": "SUSPEND"}, COORD
        )
    )

    version = current_program_version(ctx)
    validate_error(
        api.create_equipment_issuance(
            {
                "trainee_id": ctx["trainees"]["tara"]["id"],
                "kit_type": "BACKPACK_STANDARD",
                "expected_program_version": version,
            },
            LOGISTICS,
        ),
        ApiErrorId.ERR_CREDENTIAL_NOT_ACTIVE.value,
    )

    _, meta = validate_paginated(
        api.list_equipment_issuances(
            AUDITOR, {"trainee_id": ctx["trainees"]["tara"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_repairing_the_credential_surfaces_the_masked_budget_ceiling(api):
    """PRD §3.7: "The fiscal gate is evaluated **after** the asset has been chosen and
    **before** it is committed: the program's `equipment_committed_cents` plus the chosen
    asset's `unit_value_cents` must be less than or equal to the program's
    `equipment_budget_cents`. A total landing exactly on the ceiling is allowed; only a total
    strictly above it is refused, with `ERR_EQUIPMENT_BUDGET_EXCEEDED`, and again no issuance
    row is created."

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_fiscal_check_on_kit_issuance
    """
    ctx = setup_credentialed_trainees(budget_cents=1000)
    add_asset(ctx, "backpack", "BP-0001", "BACKPACK_STANDARD", 17700)
    credential_id = ctx["credentials"]["tara"]["id"]
    validate_success(api.credential_status_action(credential_id, {"action": "SUSPEND"}, COORD))
    validate_success(api.credential_status_action(credential_id, {"action": "REINSTATE"}, COORD))

    version = current_program_version(ctx)
    validate_error(
        api.create_equipment_issuance(
            {
                "trainee_id": ctx["trainees"]["tara"]["id"],
                "kit_type": "BACKPACK_STANDARD",
                "expected_program_version": version,
            },
            LOGISTICS,
        ),
        ApiErrorId.ERR_EQUIPMENT_BUDGET_EXCEEDED.value,
    )

    asset = read_asset(ctx, "backpack")
    assert asset["status"] == "IN_STOCK"
    assert asset["issue_count"] == 0
    assert read_program(ctx)["equipment_committed_cents"] == 0


# ---------------------------------------------------------------------------
# Selector determinism, the guard set and optimistic concurrency
# ---------------------------------------------------------------------------

def test_the_issuance_selector_ranks_by_circulation_then_value_then_age(api):
    """PRD §3.7: "Candidates are ranked by `issue_count` ascending, so the least-circulated
    item goes out first; ties are broken by `unit_value_cents` ascending, and any remaining
    tie by `created_at` ascending. The asset's `id` is never a sort input, not even as a last
    resort."
    PRD §3.7: "The candidate pool is every asset belonging to the trainee's program whose
    `kit_type` matches the request, whose `status` is `IN_STOCK`, and whose `condition` is
    `NEW` or `SERVICEABLE`; assets that are issued, retired, or lost are excluded outright."

    Design: Corner/calculations/equipment_selector_ranks_by_issue_count_then_value_then_created_at
    """
    ctx = setup_credentialed_trainees()
    add_asset(ctx, "x", "BP-X", "BACKPACK_STANDARD", 20000)
    add_asset(ctx, "y", "BP-Y", "BACKPACK_STANDARD", 15000)
    add_asset(ctx, "z", "BP-Z", "BACKPACK_STANDARD", 15000)

    picked = []
    for round_index in range(4):
        issuance = issue_kit(ctx, "tara", "BACKPACK_STANDARD", store_as=f"r{round_index}")
        picked.append(issuance["asset_id"])
        if round_index < 3:
            validate_success(
                api.return_equipment_issuance(
                    issuance["id"], {"condition": "SERVICEABLE"}, LOGISTICS
                )
            )

    assert picked[0] == ctx["assets"]["y"]["id"], (
        "the cheapest of the two 15000-cent assets created first must go out first"
    )
    assert picked[1] == ctx["assets"]["z"]["id"], "issue_count 0 outranks issue_count 1"
    assert picked[2] == ctx["assets"]["x"]["id"], "the last untouched asset is next"
    assert picked[3] == ctx["assets"]["y"]["id"], (
        "with every asset at issue_count 1, 15000 beats 20000 and the earlier row wins"
    )

    assert read_asset(ctx, "y")["issue_count"] == 2
    assert read_asset(ctx, "z")["issue_count"] == 1
    assert read_asset(ctx, "x")["issue_count"] == 1
    assert read_program(ctx)["equipment_committed_cents"] == 15000


def test_issuance_guards_cover_the_pool_the_duplicate_and_the_budget(api):
    """PRD §3.7: "An empty candidate pool is refused with `ERR_NO_ASSET_AVAILABLE`, in which
    case no issuance row is created and the program's `equipment_committed_cents` is
    untouched."
    PRD §3.7: "The volunteer must hold a live credential — a trainee whose credential
    standing is not `ACTIVE` or `GRACE`, including a trainee with no credential at all, is
    refused with `ERR_CREDENTIAL_NOT_ACTIVE` — and a trainee may hold at most one outstanding
    issuance per `kit_type`, a second live one being refused with
    `ERR_TRAINEE_ALREADY_ISSUED_KIT`."
    PRD §2.6: "And the equipment budget ceiling is evaluated after every selection,
    eligibility, and duplication rule, so a request that both exceeds the budget and names an
    already-kitted trainee reports the duplicate-kit condition, not the budget one."

    Design: Corner/validations/issuance_guards_cover_pool_duplicate_and_budget_paths
    """
    ctx = setup_credentialed_trainees(trainees=TWO_TRAINEES, budget_cents=30000)
    add_asset(ctx, "a1", "BP-0001", "BACKPACK_STANDARD", 17700)
    add_asset(ctx, "a2", "BP-0002", "BACKPACK_STANDARD", 17700)

    issue_kit(ctx, "tara", "BACKPACK_STANDARD", store_as="tara_bp")
    assert read_program(ctx)["equipment_committed_cents"] == 17700

    version = current_program_version(ctx)
    validate_error(
        api.create_equipment_issuance(
            {"trainee_id": ctx["trainees"]["tara"]["id"],
             "kit_type": "BACKPACK_STANDARD", "expected_program_version": version},
            LOGISTICS,
        ),
        ApiErrorId.ERR_TRAINEE_ALREADY_ISSUED_KIT.value,
    )
    validate_error(
        api.create_equipment_issuance(
            {"trainee_id": ctx["trainees"]["tara"]["id"],
             "kit_type": "RADIO_KIT", "expected_program_version": version},
            LOGISTICS,
        ),
        ApiErrorId.ERR_NO_ASSET_AVAILABLE.value,
    )
    validate_error(
        api.create_equipment_issuance(
            {"trainee_id": ctx["trainees"]["dev"]["id"],
             "kit_type": "BACKPACK_STANDARD", "expected_program_version": version},
            LOGISTICS,
        ),
        ApiErrorId.ERR_EQUIPMENT_BUDGET_EXCEEDED.value,
    )

    assert read_program(ctx)["equipment_committed_cents"] == 17700
    remaining = read_asset(ctx, "a2")
    assert remaining["status"] == "IN_STOCK"
    assert remaining["issue_count"] == 0


def test_a_stale_program_version_blocks_a_second_issuance(api):
    """PRD §2.8: "Issuing an equipment kit requires a non-optional `expected_program_version`
    field in the request payload, carrying the client's last observed `version` of the
    `Program` that owns the inventory. If that value does not equal the program's current
    `version`, the request is rejected with `ERR_STALE_PROGRAM_VERSION` and HTTP 412, and no
    issuance row is created."

    Design: Corner/cross_cutting_layers/stale_program_version_on_kit_issuance_returns_412
    """
    ctx = setup_credentialed_trainees()
    add_asset(ctx, "a1", "BP-1", "BACKPACK_STANDARD", 17700)
    add_asset(ctx, "a2", "RK-1", "RADIO_KIT", 8300)

    stale_version = current_program_version(ctx)
    first = validate_success(
        api.create_equipment_issuance(
            {"trainee_id": ctx["trainees"]["tara"]["id"],
             "kit_type": "BACKPACK_STANDARD", "expected_program_version": stale_version},
            LOGISTICS,
        ),
        201,
    )
    assert first["status"] == "ISSUED"
    assert read_program(ctx)["equipment_committed_cents"] == 17700

    validate_error(
        api.create_equipment_issuance(
            {"trainee_id": ctx["trainees"]["tara"]["id"],
             "kit_type": "RADIO_KIT", "expected_program_version": stale_version},
            LOGISTICS,
        ),
        ApiErrorId.ERR_STALE_PROGRAM_VERSION.value,
    )
    assert read_program(ctx)["equipment_committed_cents"] == 17700
    assert read_asset(ctx, "a2")["status"] == "IN_STOCK"

    fresh_version = current_program_version(ctx)
    second = validate_success(
        api.create_equipment_issuance(
            {"trainee_id": ctx["trainees"]["tara"]["id"],
             "kit_type": "RADIO_KIT", "expected_program_version": fresh_version},
            LOGISTICS,
        ),
        201,
    )
    assert second["status"] == "ISSUED"
    assert read_program(ctx)["equipment_committed_cents"] == 26000
    assert read_asset(ctx, "a2")["status"] == "ISSUED"
