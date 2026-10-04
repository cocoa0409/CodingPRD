"""Colony lifecycle: the two independent state dimensions, founding gates
(barrier rank, immunocompromised housing), retirement lockdown, the
panel-due HOLD block, drift-forced phasing out, and immediate read-after-write
of creation defaults.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    CLOCK_DEFAULT_ISO,
    DEFAULT_GENERATION_NUMBER,
    DEFAULT_SNP_PANEL_INTERVAL_WEEKS,
    advance_clock,
    api_client,
    assert_colony,
    create_catalog_strain,
    create_colony_in_room,
    create_colony_payload,
    create_cohort_in_colony,
    hold_cohort,
    read_colony,
    read_cohort,
    record_snp_panel_result,
    setup_colony_with_cohorts,
    setup_production_site,
    transition_colony,
    transition_cohort,
    validate_error,
)

_FM = TEST_USERS["facility_manager_headers"]
_VET = TEST_USERS["veterinarian_headers"]


def test_clock_sweep_flips_genetic_only_not_lifecycle():
    """PRD Section 3.2: "When the clock sweep finds the logical clock strictly
    later than `last_snp_panel_at` plus `snp_panel_interval_weeks`, the colony
    slips to `PANEL_DUE` — surveillance is owed."
    PRD Section 3.2: "A colony evolves along two independent state dimensions."

    Design: Difficulty/non_linear_state_machine/colony_parallel_lifecycle_genetic_dimensions
    """
    bundle = setup_colony_with_cohorts(
        cohorts=[{"count_male": 10, "count_female": 10}]
    )
    colony = bundle["colony"]
    assert colony["lifecycle_status"] == "PRODUCTION"
    assert colony["genetic_status"] == "CLEAR"

    advance_clock("2026-11-25T00:00:00Z")

    colony = read_colony(colony["id"])
    # 12 weeks after the 2026-09-01 creation clock is 2026-11-24; the sweep
    # at 2026-11-25 is strictly later, so the panel is due.
    assert colony["genetic_status"] == "PANEL_DUE"
    assert colony["lifecycle_status"] == "PRODUCTION"
    assert_colony(colony)


def test_clear_panel_returns_genetic_clear_lifecycle_untouched():
    """PRD Section 3.2: "Recording `CLEAR` on a `PANEL_DUE` colony returns it
    to `CLEAR`" and "Every panel recording refreshes `last_snp_panel_at` to
    the current logical clock".

    Design: Difficulty/non_linear_state_machine/colony_parallel_lifecycle_genetic_dimensions
    """
    bundle = setup_colony_with_cohorts(
        cohorts=[{"count_male": 10, "count_female": 10}]
    )
    colony = bundle["colony"]
    advance_clock("2026-11-25T00:00:00Z")
    assert read_colony(colony["id"])["genetic_status"] == "PANEL_DUE"

    updated = record_snp_panel_result(colony["id"], "CLEAR")
    assert updated["genetic_status"] == "CLEAR"
    assert updated["lifecycle_status"] == "PRODUCTION"
    assert updated["last_snp_panel_at"].startswith("2026-11-25T00:00:00")


def test_immediate_read_after_write_colony():
    """PRD Section 3.2: "Two optional fields tune the stock:
    `generation_number`, the filial generation of the breeding stock,
    defaulting to 0; and `snp_panel_interval_weeks`, the number of weeks
    allowed between genetic-monitoring panels, defaulting to 12."
    PRD Section 3.2: "the colony's `last_snp_panel_at` is initialized to the
    current logical clock".

    Design: Corner/consistency_model/immediate_read_after_write_colony
    """
    site = setup_production_site()
    colony = create_colony_in_room(site, breeding_pair_count=10)
    data = read_colony(colony["id"])
    assert data["lifecycle_status"] == "FOUNDING"
    assert data["genetic_status"] == "CLEAR"
    assert data["generation_number"] == DEFAULT_GENERATION_NUMBER
    assert data["snp_panel_interval_weeks"] == DEFAULT_SNP_PANEL_INTERVAL_WEEKS
    assert data["last_snp_panel_at"].startswith("2026-09-01T00:00:00")
    assert data["breeding_pair_count"] == 10
    assert data["version"] == 1
    assert_colony(data)


def test_genetic_drift_forces_phasing_out():
    """PRD Section 3.2: "recording `DRIFT_DETECTED` — from either `CLEAR` or
    `PANEL_DUE` — moves the colony to the terminal `DRIFT_DETECTED` state, and
    if the colony's `lifecycle_status` was `EXPANDING` or `PRODUCTION` at that
    moment it is forced into `PHASING_OUT`, because drifted stock must not
    remain in production."

    Design: Corner/state_machines/genetic_drift_forces_phasing_out
    """
    bundle = setup_colony_with_cohorts(cohorts=[{"count_male": 5, "count_female": 5}])
    colony = bundle["colony"]
    assert colony["lifecycle_status"] == "PRODUCTION"

    updated = record_snp_panel_result(colony["id"], "DRIFT_DETECTED")
    assert updated["genetic_status"] == "DRIFT_DETECTED"
    assert updated["lifecycle_status"] == "PHASING_OUT"

    reread = read_colony(colony["id"])
    assert reread["genetic_status"] == "DRIFT_DETECTED"
    assert reread["lifecycle_status"] == "PHASING_OUT"


def test_colony_retired_terminal_lockdown():
    """PRD Section 3.2: "Retirement from `PHASING_OUT` requires that no cohort
    of the colony remain in one of those four live states and that no
    allocation in `RESERVED` exists on any of its cohorts".
    PRD Section 2.7: "And any transition or action requested against a
    resource whose current state does not declare that transition — including
    any further transition out of a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/colony_retired_terminal_lockdown
    """
    bundle = setup_colony_with_cohorts(cohorts=[{"count_male": 5, "count_female": 5}])
    colony = bundle["colony"]
    cohort = bundle["cohorts"][0]

    transition_colony(colony["id"], "PHASING_OUT")
    culled = transition_cohort(
        cohort["id"], "CULLED", _VET, cull_male=5, cull_female=5
    )
    assert culled["status"] == "CULLED"
    retired = transition_colony(colony["id"], "RETIRED")
    assert retired["lifecycle_status"] == "RETIRED"

    resp = api_client.transition_colony(colony["id"], {"target_state": "PRODUCTION"}, _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    colony = read_colony(colony["id"])
    assert colony["lifecycle_status"] == "RETIRED"
    cohort = read_cohort(cohort["id"])
    assert cohort["status"] == "CULLED"
    assert cohort["count_male"] == 0
    assert cohort["count_female"] == 0


def test_cohort_hold_blocked_when_panel_due():
    """PRD Section 3.3: "a `FacilityManager` moves a `WEANED` cohort to `HOLD`,
    but only while the colony's `lifecycle_status` is `EXPANDING` or
    `PRODUCTION` and its `genetic_status` is `CLEAR`."
    PRD Section 2.7: "And any transition or action requested against a
    resource whose current state does not declare that transition — including
    any further transition out of a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cohort_hold_blocked_when_panel_due
    """
    bundle = setup_colony_with_cohorts(
        cohorts=[{"count_male": 5, "count_female": 5}],
        advance_to_production=False,
    )
    colony = bundle["colony"]
    cohort = bundle["cohorts"][0]
    assert colony["lifecycle_status"] == "EXPANDING"

    advance_clock("2026-11-26T00:00:00Z")
    assert read_colony(colony["id"])["genetic_status"] == "PANEL_DUE"

    resp = api_client.transition_cohort(cohort["id"], {"target_state": "HOLD"}, _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_cohort(cohort["id"])["status"] == "WEANED"


def test_immunocompromised_second_strain_rejected():
    """PRD Section 3.2: "an `IMMUNOCOMPROMISED` strain may only be housed in a
    room of rank `VF` or higher, and a room hosts colonies of at most one
    `IMMUNOCOMPROMISED` strain, with violations rejected as
    `ERR_IMMUNOCOMPROMISED_MIXING` (HTTP 422)."

    Design: Corner/validations/immunocompromised_second_strain_rejected
    """
    site = setup_production_site(
        strain_overrides={"immune_class": "IMMUNOCOMPROMISED", "min_barrier_level": "VF"}
    )
    colony = create_colony_in_room(site, breeding_pair_count=5)
    assert colony["id"]

    strain_nog = create_catalog_strain(
        immune_class="IMMUNOCOMPROMISED", min_barrier_level="VF", base_price_cents=5200
    )
    payload = create_colony_payload(
        site["room"]["id"], strain_nog["id"], site["protocol"]["id"],
        breeding_pair_count=5,
    )
    resp = api_client.create_colony(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_IMMUNOCOMPROMISED_MIXING)


def test_colony_below_strain_barrier_rejected():
    """PRD Section 3.2: "the room's `barrier_level` rank must be at least the
    strain's `min_barrier_level` rank, else `ERR_BARRIER_LEVEL_INSUFFICIENT`
    (HTTP 422)".

    Design: Corner/validations/colony_below_strain_barrier_rejected
    """
    site = setup_production_site(
        room_overrides={"barrier_level": "MPF"},
        strain_overrides={"min_barrier_level": "VF"},
    )
    payload = create_colony_payload(
        site["room"]["id"], site["strain"]["id"], site["protocol"]["id"],
        breeding_pair_count=5,
    )
    resp = api_client.create_colony(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_BARRIER_LEVEL_INSUFFICIENT)
