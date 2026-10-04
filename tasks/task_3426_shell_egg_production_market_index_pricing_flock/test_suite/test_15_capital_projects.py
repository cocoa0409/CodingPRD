"""Capital projects: the approval gates, run-ops promotion into construction,
the commission two-link cascade onto the house and the sponsoring
commitment, and the derived transition-progress fields.
"""

from test_helpers import (
    PLANNER,
    api_client,
    assert_capital_project,
    assert_instant_equal,
    create_active_commitment,
    create_capital_project,
    create_commitment,
    create_complex,
    create_customer,
    create_house,
    read_commitment,
    read_house,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def _setup_committable_project(api):
    """Complex 'Conversion Site' (WEST) with CAGE_FREE-targeted house H3, an
    ACTIVE transition commitment (50000 dozen/week, pct 1.0, deadline
    2027-06-01), and a project APPROVED then promoted at the 2026-09-02
    checkpoint."""
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(name="Conversion Site", region_code="WEST")
    house = create_house(
        complex_["id"], house_code="H3", housing_style="CONVENTIONAL",
        capacity_hens=100_000,
    )
    customer = create_customer(name="GreenShelf")
    commitment = create_active_commitment(
        customer["id"], program="CAGE_FREE", region_code="WEST",
        weekly_dozen_committed=50_000, price_adjustment_cents_per_dozen=20,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-09-01T00:00:00Z",
        cage_free_transition_deadline="2027-06-01T00:00:00Z",
        required_cage_free_pct=1.0,
    )
    project = create_capital_project(
        commitment["id"], house["id"], construction_weeks=6,
    )
    approved = validate_success(api.approve_capital_project(project["id"],
                                                            PLANNER))
    assert approved["status"] == "APPROVED"
    set_clock("2026-09-02T00:00:00Z")
    run_ops(complex_["id"])
    return complex_, house, customer, commitment, project


def test_commission_flips_house_and_completes_project(api):
    """Commissioning mutates the house (link 1) and lands the project in
    COMMISSIONED at the >= construction boundary.

    PRD §3.5: "Commissioning requires `IN_CONSTRUCTION` (else
    `ERR_INVALID_STATE`) and a clock at least `construction_weeks` times
    seven days past `construction_started_at` (else
    `ERR_CONSTRUCTION_INCOMPLETE`); it stamps `commissioned_at`, flips the
    house's `housing_style` to `target_style`, and recomputes the
    commitment's `achieved_conversion_hens` and `transition_on_track`".
    PRD §3.5: "The first operations checkpoint on any complex after approval
    promotes the project `APPROVED` → `IN_CONSTRUCTION` and stamps
    `construction_started_at` with that checkpoint's clock."

    Design: Difficulty/transitive_cascade/capital_commission_two_link_cascade
    """
    complex_, house, _, _, project = _setup_committable_project(api)

    # Precondition: promoted to IN_CONSTRUCTION at the 2026-09-02 checkpoint.
    projects, _ = _list_projects(api, project)
    in_construction = projects[0]
    assert in_construction["status"] == "IN_CONSTRUCTION"
    assert_instant_equal(
        in_construction["construction_started_at"], "2026-09-02T00:00:00Z",
        "construction_started_at",
    )

    set_clock("2026-10-14T00:00:00Z")  # exactly 42 days after start: >= 6 wks
    commissioned = validate_success(
        api.commission_capital_project(project["id"], PLANNER)
    )
    assert_capital_project(commissioned)
    assert commissioned["status"] == "COMMISSIONED"
    assert_instant_equal(
        commissioned["commissioned_at"], "2026-10-14T00:00:00Z",
        "commissioned_at",
    )

    # Link 1: the house flips.
    house_after = read_house(house["id"])
    assert house_after["housing_style"] == "CAGE_FREE"


def test_commission_recomputes_commitment_transition_progress(api):
    """Link 2: the house-style mutation recomputes the commitment's
    conversion progress — achieved meets required at exactly 100000.

    PRD §3.5: "`required_conversion_hens` is the committed weekly dozen times
    `required_cage_free_pct` times two support hens per weekly dozen, rounded
    half up to a whole bird. `achieved_conversion_hens` is the sum of
    `capacity_hens` over the houses converted by this commitment's capital
    projects that have reached `COMMISSIONED`. `transition_on_track` is true
    when the achieved figure meets or exceeds the required figure, or when a
    deadline is set and the logical clock is still before it."
    PRD §3.5: "The figures are recomputed — with a commitment `version` bump
    — whenever a linked project commissions."

    Design: Difficulty/transitive_cascade/capital_commission_two_link_cascade
    """
    _, house, _, commitment, project = _setup_committable_project(api)
    set_clock("2026-10-14T00:00:00Z")
    validate_success(api.commission_capital_project(project["id"],
                                                    PLANNER))

    progress = read_commitment(commitment["id"])
    assert progress["required_conversion_hens"] == 100_000  # 50000 * 1.0 * 2
    assert progress["achieved_conversion_hens"] == 100_000  # house capacity
    assert progress["transition_on_track"] is True


def test_capital_project_auto_starts_construction_at_next_run_ops(api):
    """The APPROVED -> IN_CONSTRUCTION promotion fires on the next checkpoint
    even when zero weeks elapsed.

    PRD §3.5: "The first operations checkpoint on any complex after approval
    promotes the project `APPROVED` → `IN_CONSTRUCTION` and stamps
    `construction_started_at` with that checkpoint's clock."
    PRD §2.4: "A checkpoint taken with zero elapsed weeks leaves flock state
    untouched but still runs every janitorial check and still advances the
    counter".

    Design: Corner/state_machines/capital_project_auto_starts_construction_at_next_run_ops
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], house_code="H3",
                         capacity_hens=100_000)
    customer = create_customer(name="GreenShelf")
    commitment = create_active_commitment(
        customer["id"], program="CAGE_FREE", region_code="MIDWEST",
        weekly_dozen_committed=50_000, price_adjustment_cents_per_dozen=20,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-09-01T00:00:00Z",
        cage_free_transition_deadline="2027-06-01T00:00:00Z",
        required_cage_free_pct=1.0,
    )
    project = create_capital_project(commitment["id"], house["id"])
    validate_success(api.approve_capital_project(project["id"],
                                                 PLANNER))

    # Zero elapsed weeks: the promotion still fires.
    run_ops(complex_["id"])

    projects, _ = _list_projects(api, project)
    promoted = projects[0]
    assert promoted["status"] == "IN_CONSTRUCTION"
    assert_instant_equal(
        promoted["construction_started_at"], "2026-09-01T00:00:00Z",
        "construction_started_at",
    )


def test_redundant_conversion_rejected_at_approve(api):
    """A project whose target_style already equals the house's style cannot
    be approved.

    PRD §3.5: "Approval requires the project `PROPOSED` and the commitment
    `ACTIVE` (either failure is `ERR_INVALID_STATE`), and rejects a redundant
    conversion — `target_style` equal to the house's current `housing_style`
    — with `ERR_CONVERSION_REDUNDANT`".

    Design: Corner/validations/redundant_conversion_rejected_at_approve
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(
        complex_["id"], house_code="H2", housing_style="CAGE_FREE",
        capacity_hens=80_000,
    )
    customer = create_customer(name="GreenShelf")
    commitment = create_active_commitment(
        customer["id"], program="CAGE_FREE",
        weekly_dozen_committed=50_000, price_adjustment_cents_per_dozen=20,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-09-01T00:00:00Z",
    )
    project = create_capital_project(
        commitment["id"], house["id"], investment_cents=1_000_000,
        target_style="CAGE_FREE", construction_weeks=4,
    )

    validate_error(
        api.approve_capital_project(project["id"], PLANNER),
        ERR.ERR_CONVERSION_REDUNDANT,
    )
    projects, _ = _list_projects(api, project)
    assert projects[0]["status"] == "PROPOSED"


def test_commission_before_construction_elapsed_returns_409(api):
    """Commissioning one day before the 42-day construction completes fails.

    PRD §3.5: "Commissioning requires `IN_CONSTRUCTION` (else
    `ERR_INVALID_STATE`) and a clock at least `construction_weeks` times
    seven days past `construction_started_at` (else
    `ERR_CONSTRUCTION_INCOMPLETE`)".

    Design: Corner/validations/commission_before_construction_elapsed_returns_409
    """
    _, house, _, _, project = _setup_committable_project(api)
    set_clock("2026-10-13T00:00:00Z")  # 41 days into the 42-day build

    validate_error(
        api.commission_capital_project(project["id"], PLANNER),
        ERR.ERR_CONSTRUCTION_INCOMPLETE,
    )
    projects, _ = _list_projects(api, project)
    assert projects[0]["status"] == "IN_CONSTRUCTION"
    assert read_house(house["id"])["housing_style"] == "CONVENTIONAL"


def test_commitment_transition_fields_computed_with_no_projects(api):
    """With zero capital projects the progress fields still compute:
    required from the formula, achieved zero, and on-track while the
    deadline is still ahead.

    PRD §3.5: "`required_conversion_hens` is the committed weekly dozen times
    `required_cage_free_pct` times two support hens per weekly dozen, rounded
    half up to a whole bird. `achieved_conversion_hens` is the sum of
    `capacity_hens` over the houses converted by this commitment's capital
    projects that have reached `COMMISSIONED`. `transition_on_track` is true
    when the achieved figure meets or exceeds the required figure, or when a
    deadline is set and the logical clock is still before it."
    PRD §3.5: "A commitment starts `PENDING` with `blocked_order_count`
    zero".

    Design: Corner/entities/commitment_transition_fields_computed_with_no_projects
    """
    set_clock("2026-09-01T00:00:00Z")
    customer = create_customer(name="GreenShelf")
    commitment = create_commitment(
        customer["id"], program="CAGE_FREE", region_code="WEST",
        weekly_dozen_committed=50_000, price_adjustment_cents_per_dozen=20,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-09-01T00:00:00Z",
        cage_free_transition_deadline="2027-06-01T00:00:00Z",
        required_cage_free_pct=1.0,
    )
    assert commitment["status"] == "PENDING"

    progress = read_commitment(commitment["id"])
    assert progress["required_conversion_hens"] == 100_000
    assert progress["achieved_conversion_hens"] == 0
    assert progress["transition_on_track"] is True
    assert progress["blocked_order_count"] == 0


def _list_projects(api, project):
    """Read back a project through its commitment's list endpoint."""
    return validate_paginated(
        api.list_capital_projects(project["commitment_id"], PLANNER)
    )

