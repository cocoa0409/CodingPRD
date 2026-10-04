"""License agreements: creation, lifecycle, territory windows, amendments, expiry."""
from test_helpers import (
    AUDITOR,
    LICENSING,
    ApiErrorId,
    activate_agreement,
    create_active_agreement,
    create_agreement,
    create_audit,
    create_brand,
    create_facility_with_line,
    create_variety,
    get_success_data,
    make_brand_manager_headers,
    reserve_run,
    set_clock,
    validate_error,
    validate_success,
)


def test_agreement_created_in_draft_and_run_in_reserved(api, licensing_headers):
    """PRD §3.1: "A freshly created agreement carries `status` `DRAFT`, a null
    `amendment_of_id`, and `version` 1."
    PRD §3.4: "The run is born `RESERVED`, committing the window's capacity."
    PRD §2.5: "a production run's `actual_units` is null until the run
    completes"

    Design: Corner/state_machines/agreement_created_in_draft_and_run_in_reserved
    """
    licensed = create_brand(kind="LICENSED", name="Init Co")
    agreement = create_agreement(licensed["id"])
    assert agreement["status"] == "DRAFT"
    assert agreement["amendment_of_id"] is None
    assert agreement["version"] == 1

    owned = create_brand(kind="PLATFORM_OWNED", name="Init Owned")
    variety = create_variety(owned["id"], name="Init Var")
    _, line = create_facility_with_line()
    run = reserve_run(line["id"], variety["id"], planned_units=100)
    assert run["status"] == "RESERVED"
    assert run["actual_units"] is None


def test_agreement_for_non_licensed_brand_rejected(api):
    """PRD §3.1: "A `LicensingManager` opens the licensing relationship by
    creating a **LicenseAgreement** in `DRAFT`, supplying the `brand_id` of a
    brand whose `kind` is `LICENSED` (any other kind is rejected with
    `ERR_BRAND_NOT_LICENSED`, HTTP 422)"

    Design: Corner/validations/agreement_for_non_licensed_brand_rejected
    """
    owned = create_brand(kind="PLATFORM_OWNED", name="Owned House")
    unlicensed = create_brand(kind="UNLICENSED_COMPATIBLE", name="Pirate Pods")

    for brand in (owned, unlicensed):
        resp = api.create_license_agreement(
            {"brand_id": brand["id"], "territory_code": "US",
             "effective_start": "2026-01-01", "effective_end": "2026-12-31",
             "royalty_tiers": [{"up_to_units": None, "millicents_per_pod": 500}],
             "quality_min_cup_score": 80, "exclusive": False},
            LICENSING)
        validate_error(resp, ApiErrorId.ERR_BRAND_NOT_LICENSED)


def test_terminated_agreement_accepts_no_transitions(api, licensing_headers):
    """PRD §2.9: "Terminal states are absorbing — a resource in a terminal
    state accepts no further transitions, and any attempt to drive one is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.1: "`TERMINATED`, `EXPIRED`, and `SUPERSEDED` are the terminal
    states."

    Design: Corner/state_machines/terminated_agreement_accepts_no_transitions
    """
    brand = create_brand(kind="LICENSED", name="Lockdown Co")
    agreement = create_active_agreement(brand["id"])
    get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "TERMINATED"}, LICENSING))

    for target in ("ACTIVE", "SUSPENDED", "TERMINATED"):
        resp = api.transition_license_agreement(
            agreement["id"], {"target_state": target}, LICENSING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    read_back = get_success_data(
        api.get_license_agreement(agreement["id"], licensing_headers))
    assert read_back["status"] == "TERMINATED"


def test_suspend_twice_is_rejected(api):
    """PRD §2.10: "**State-machine precondition** — after the lazy evaluations
    of §2.4 have been applied, the requested (current, target) pair must be a
    declared transition of the entity's state machine and the current state
    must not be terminal (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/suspend_twice_is_rejected
    """
    brand = create_brand(kind="LICENSED", name="Twice Co")
    agreement = create_active_agreement(brand["id"])
    variety = create_variety(brand["id"], name="Twice Var")

    get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "SUSPENDED"}, LICENSING))
    resp = api.transition_license_agreement(
        agreement["id"], {"target_state": "SUSPENDED"}, LICENSING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    read_back = get_success_data(api.get_pod_variety(
        variety["id"], make_brand_manager_headers(brand["id"])))
    assert read_back["status"] == "SUPPLY_BLOCKED"


def test_agreement_expires_lazily_after_effective_end(api, licensing_headers):
    """PRD §2.4: "on every agreement-scoped read or write, an agreement in
    `ACTIVE` whose `effective_end` date has been passed by the logical clock's
    current date becomes `EXPIRED`; a read simply reports the expired state,
    while the write that observes the expiry fails with `ERR_AGREEMENT_EXPIRED`
    (HTTP 409)."

    Design: Corner/validations/agreement_expires_lazily_after_effective_end
    """
    brand = create_brand(kind="LICENSED", name="Expiring Co")
    agreement = create_active_agreement(
        brand["id"], effective_start="2026-01-01", effective_end="2026-09-15")

    set_clock("2026-09-16T00:00:00Z")

    read_back = get_success_data(
        api.get_license_agreement(agreement["id"], licensing_headers))
    assert read_back["status"] == "EXPIRED"

    resp = api.transition_license_agreement(
        agreement["id"], {"target_state": "SUSPENDED"}, LICENSING)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXPIRED)


def test_occ_license_amend_stale_version(api, licensing_headers):
    """PRD §2.7: "Amending a license agreement requires the request to carry
    `expected_license_agreement_version`, equal to the target agreement's
    current `version`; if another writer has advanced the agreement's version
    since the client last read it, the amend is rejected with
    `ERR_STALE_VERSION` (HTTP 412)"
    PRD §3.1: "A successful amend increments the **source** agreement's
    `version` by one and produces a brand-new agreement in `DRAFT` whose
    `amendment_of_id` is the source's `id`, whose `brand_id` is copied from
    the source, and whose own `version` starts at 1."

    Design: Corner/cross_cutting_layers/occ_license_amend_stale_version
    """
    brand = create_brand(kind="LICENSED", name="OCC License Co")
    agreement = create_active_agreement(brand["id"])
    observed_version = agreement["version"]  # 1 (create) + 1 (activate) == 2
    assert observed_version == 2

    amendment = validate_success(api.amend_license_agreement(
        agreement["id"],
        {"expected_license_agreement_version": observed_version,
         "territory_code": "US", "effective_start": "2027-01-01",
         "effective_end": "2027-12-31",
         "royalty_tiers": [{"up_to_units": None, "millicents_per_pod": 550}],
         "quality_min_cup_score": 82, "exclusive": False},
        LICENSING), 201)
    assert amendment["status"] == "DRAFT"
    assert amendment["amendment_of_id"] == agreement["id"]
    assert amendment["brand_id"] == brand["id"]
    assert amendment["version"] == 1

    source = get_success_data(
        api.get_license_agreement(agreement["id"], licensing_headers))
    assert source["version"] == 3

    stale = api.amend_license_agreement(
        agreement["id"],
        {"expected_license_agreement_version": observed_version,
         "territory_code": "US", "effective_start": "2027-01-01",
         "effective_end": "2027-12-31",
         "royalty_tiers": [{"up_to_units": None, "millicents_per_pod": 600}],
         "quality_min_cup_score": 82, "exclusive": False},
        LICENSING)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


def test_amendment_activation_supersedes_source_and_skips_territory_check(
        api, licensing_headers):
    """PRD §3.1: "if the agreement being activated is an amendment — its
    `amendment_of_id` points at a source agreement — and that source is
    currently `ACTIVE`, the source is driven to `SUPERSEDED` in the same
    operation."
    PRD §3.1: "Agreements joined by an amendment chain — where one was created
    as the amendment of the other — are exempt from this check, since an
    amendment is meant to replace its source on overlapping ground."

    Design: Corner/cross_cutting_layers/amendment_activation_supersedes_source_and_skips_territory_check
    """
    brand = create_brand(kind="LICENSED", name="Amend Co")
    source = create_active_agreement(brand["id"])

    amendment = validate_success(api.amend_license_agreement(
        source["id"],
        {"expected_license_agreement_version": source["version"],
         "territory_code": "US", "effective_start": "2026-06-01",
         "effective_end": "2027-05-31",
         "royalty_tiers": [{"up_to_units": None, "millicents_per_pod": 525}],
         "quality_min_cup_score": 81, "exclusive": False},
        LICENSING), 201)

    activated = validate_success(api.transition_license_agreement(
        amendment["id"], {"target_state": "ACTIVE"}, LICENSING))
    assert activated["status"] == "ACTIVE"

    source_after = get_success_data(
        api.get_license_agreement(source["id"], licensing_headers))
    assert source_after["status"] == "SUPERSEDED"

    resp = api.transition_license_agreement(
        source["id"], {"target_state": "TERMINATED"}, LICENSING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_territory_window_starting_day_after_end_is_legal(api):
    """PRD §3.1: "Territory windows are **closed intervals at day
    granularity**: two such agreements conflict whenever each one's start falls
    on or before the other's end, so an agreement whose first day is the day
    after another's last day is legal, while one starting on that final day
    itself conflicts and is rejected with `ERR_TERRITORY_WINDOW_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/territory_closed_day_intervals
    """
    brand = create_brand(kind="LICENSED", name="Territory Tea")
    # The incumbent's window must cover the startup clock (2026-09-01), else
    # lazy evaluation (PRD §2.4) expires it before the challenger arrives and
    # the territory check never engages.
    create_active_agreement(
        brand["id"], effective_start="2026-01-01", effective_end="2026-12-31")

    agreement_b = create_agreement(
        brand["id"], effective_start="2027-01-01", effective_end="2027-06-30")
    activated = activate_agreement(agreement_b["id"])
    assert activated["status"] == "ACTIVE"


def test_territory_window_sharing_end_day_conflicts(api):
    """PRD §3.1: "Territory windows are **closed intervals at day
    granularity**: two such agreements conflict whenever each one's start falls
    on or before the other's end, so an agreement whose first day is the day
    after another's last day is legal, while one starting on that final day
    itself conflicts and is rejected with `ERR_TERRITORY_WINDOW_CONFLICT`
    (HTTP 409)."
    PRD §3.1: "the brand-plus-territory pair must not collide with an existing
    `ACTIVE` or `SUSPENDED` agreement for the same brand and territory."

    Design: Difficulty/resource_temporal_overlap/territory_closed_day_intervals
    """
    brand = create_brand(kind="LICENSED", name="Boundary Tea")
    # Incumbent window covers the startup clock (2026-09-01) so it is still
    # ACTIVE — not lazily EXPIRED per PRD §2.4 — when the challenger arrives.
    create_active_agreement(
        brand["id"], effective_start="2026-01-01", effective_end="2026-12-31")

    # Starting ON the incumbent's inclusive end date collides at creation.
    resp = api.create_license_agreement(
        {"brand_id": brand["id"], "territory_code": "US",
         "effective_start": "2026-12-31", "effective_end": "2027-02-28",
         "royalty_tiers": [{"up_to_units": None, "millicents_per_pod": 500}],
         "quality_min_cup_score": 80, "exclusive": False},
        LICENSING)
    validate_error(resp, ApiErrorId.ERR_TERRITORY_WINDOW_CONFLICT)


def test_audit_on_terminated_agreement_rejected(api):
    """PRD §3.2: "The agreement must be `ACTIVE` or `SUSPENDED` to accept an
    audit; against any other status the creation is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/audit_requires_agreement_live
    """
    brand = create_brand(kind="LICENSED", name="Closed Books Co")
    agreement = create_active_agreement(brand["id"])
    get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "TERMINATED"}, LICENSING))

    resp = api.create_quality_audit(
        agreement["id"],
        {"audited_at": "2026-09-01T00:00:00Z", "cup_score": 95,
         "defect_rate_ppm": 10},
        AUDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_audit_on_suspended_agreement_accepted(api):
    """PRD §3.2: "The agreement must be `ACTIVE` or `SUSPENDED` to accept an
    audit; against any other status the creation is rejected with
    `ERR_INVALID_STATE`."
    PRD §3.2: "the audit `PASS`es when its `cup_score` reaches at least the
    agreement's `quality_min_cup_score` **and** its `defect_rate_ppm` is at
    most 500 defective pods per million; anything short of that bar is a
    `FAIL`."

    Design: Difficulty/cross_entity_state_dependency/audit_requires_agreement_live
    """
    brand = create_brand(kind="LICENSED", name="Remediation Co")
    agreement = create_active_agreement(brand["id"])
    get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "SUSPENDED"}, LICENSING))

    audit = create_audit(agreement["id"], audited_at="2026-09-01T00:00:00Z",
                         cup_score=95, defect_rate_ppm=10)
    assert audit["result"] == "PASS"

    # Recording evidence does not itself reinstate the agreement.
    read_back = get_success_data(
        api.get_license_agreement(agreement["id"], LICENSING))
    assert read_back["status"] == "SUSPENDED"


def test_license_suspension_blocks_brand_varieties(api, licensing_headers):
    """PRD §3.2: "The manual suspension path available to a `LicensingManager`
    produces the identical cascade."
    PRD §3.2: "Every pod variety of the agreement's brand that is currently
    `ACTIVE` flips to `SUPPLY_BLOCKED`"

    Design: Difficulty/non_linear_state_machine/license_suspend_reinstate_cycle
    """
    brand = create_brand(kind="LICENSED", name="Cycle Beans")
    agreement = create_active_agreement(brand["id"])
    variety = create_variety(brand["id"], name="Cycle House Blend")

    suspended = get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "SUSPENDED"}, LICENSING))
    assert suspended["status"] == "SUSPENDED"

    variety_after = get_success_data(api.get_pod_variety(
        variety["id"], make_brand_manager_headers(brand["id"])))
    assert variety_after["status"] == "SUPPLY_BLOCKED"


def test_license_reinstatement_restores_brand_varieties(api, licensing_headers):
    """PRD §3.2: "Driving `SUSPENDED → ACTIVE` requires the agreement's
    **latest** audit — latest by `audited_at` descending, ties broken by
    `created_at` descending — to be a `PASS`; without one the transition is
    rejected with `ERR_INVALID_STATE`."
    PRD §3.2: "On success, every variety of the brand sitting in
    `SUPPLY_BLOCKED` returns to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/license_suspend_reinstate_cycle
    """
    brand = create_brand(kind="LICENSED", name="Cycle Beans 2")
    agreement = create_active_agreement(brand["id"])
    variety = create_variety(brand["id"], name="Cycle House Blend 2")

    get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "SUSPENDED"}, LICENSING))

    # Reinstatement without a passing latest audit is refused.
    refused = api.transition_license_agreement(
        agreement["id"], {"target_state": "ACTIVE"}, LICENSING)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)

    # The PASS audit is creatable while SUSPENDED (the remediation path).
    create_audit(agreement["id"], audited_at="2026-09-01T00:00:00Z",
                 cup_score=91, defect_rate_ppm=50)

    reinstated = get_success_data(api.transition_license_agreement(
        agreement["id"], {"target_state": "ACTIVE"}, LICENSING))
    assert reinstated["status"] == "ACTIVE"

    variety_after = get_success_data(api.get_pod_variety(
        variety["id"], make_brand_manager_headers(brand["id"])))
    assert variety_after["status"] == "ACTIVE"
