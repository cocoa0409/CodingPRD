"""Cross-cutting layers: stale-parent guards, cascade depth, escalation
thresholds, and the immediate visibility of every derived value.

Every test builds its own preconditions from an empty database.
"""

from test_helpers import (
    ACTIVITY_HEAVY,
    ACTIVITY_MODERATE,
    BOND_ACTIVE,
    BOND_LAPSED,
    CATEGORY_TERMITE_APPLICATOR,
    CATEGORY_WDO_INSPECTOR,
    CLAIM_DENIED,
    CLAIM_SUBMITTED,
    CLAIM_TYPE_RETREAT,
    CLAIM_UNDER_ADJUDICATION,
    CLOCK_STARTUP_INSTANT,
    COMPLIANCE_ON_TIME,
    CONDUCIVE_EXCESS_MOISTURE,
    CONDUCIVE_WOOD_TO_GROUND,
    CONSTRUCTION_SLAB,
    DENIAL_BOND_LAPSED,
    ERR_INVALID_BOND_STATE,
    ERR_STALE_VERSION,
    EXCLUSION_AGGREGATE_PRORATION,
    GRACE_PERIOD_DAYS,
    MANAGER_HEADERS,
    METHOD_BAIT_STATION,
    METHOD_LIQUID_BARRIER,
    OFFICER_HEADERS,
    ORGANISM_SUBTERRANEAN_TERMITE,
    PLAN_APPROVED,
    RENEWAL_PENDING,
    RENEWAL_VOID,
    STATION_ACTIVE_HIT,
    STATION_ESCALATED,
    STATION_INSTALLED,
    STATION_INTERVAL_DAYS,
    TIER_REPAIR_AND_RETREAT,
    application_payload,
    approve_plan,
    assert_bond_money,
    assert_claim_money,
    assert_conducive_counts_conserved,
    assert_envelope_meta,
    assert_instant_equals,
    assert_money,
    assert_repair_liability_conserved,
    assert_station_index_ascending,
    assert_status,
    assert_version,
    attach_verification,
    bond_payload,
    clean_initial_graph,
    complete_plan,
    conducive_finding_payload,
    damage_claim_payload,
    damage_finding_payload,
    date_plus_days,
    escalate_station,
    expected_bond_money,
    expected_deductible_rate,
    expected_escalation_threshold,
    expected_quoted_price,
    expected_station_grid_ref,
    expected_target_gallons,
    expected_target_station_count,
    file_claim,
    graphed_inspection,
    instant_plus_days,
    issue_bond,
    list_stations,
    make_applicator_headers,
    make_field_inspector_headers,
    make_property_owner_headers,
    open_renewal,
    propose_bait_plan,
    record_application,
    register_inspector,
    register_property,
    round_half_up,
    service_station,
    set_clock,
    treatment_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
)

BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"

# The slab structure every liquid-barrier chain in this file is built on.
SLAB_SQUARE_FOOTAGE = 2000
SLAB_LINEAR_FOOTAGE = 180

EXPECTED_TARGET_GALLONS = expected_target_gallons(
    CONSTRUCTION_SLAB, METHOD_LIQUID_BARRIER, SLAB_SQUARE_FOOTAGE, SLAB_LINEAR_FOOTAGE
)
EXPECTED_QUOTED_PRICE = expected_quoted_price(
    SLAB_SQUARE_FOOTAGE, METHOD_LIQUID_BARRIER, CONSTRUCTION_SLAB, False
)
(
    EXPECTED_BASE_PREMIUM,
    EXPECTED_REPAIR_CAP,
    EXPECTED_ANNUAL_PREMIUM,
) = expected_bond_money(EXPECTED_QUOTED_PRICE, TIER_REPAIR_AND_RETREAT)


# ---------------------------------------------------------------------------
# Local composition of the shared helpers
# ---------------------------------------------------------------------------


def _slab_property_and_licensees(api, linear_footage=SLAB_LINEAR_FOOTAGE, **overrides):
    """Register the structure, the signing inspector and the applicator."""
    set_clock(api, CLOCK_STARTUP_INSTANT)
    prop = register_property(
        api,
        address_line1="411 Cypress Row",
        state_code="FL",
        construction_type=CONSTRUCTION_SLAB,
        square_footage=SLAB_SQUARE_FOOTAGE,
        linear_footage=linear_footage,
        year_built=1995,
        **overrides
    )
    signer = register_inspector(
        api,
        full_name="Rosa Vance",
        license_state="FL",
        license_categories=[CATEGORY_WDO_INSPECTOR],
    )
    applicator = register_inspector(
        api,
        full_name="Dale Ortiz",
        license_state="FL",
        license_categories=[CATEGORY_TERMITE_APPLICATOR],
    )
    return prop, signer, applicator


def _approved_liquid_plan(api):
    """A structure with a signed zero-finding graph and an APPROVED liquid plan."""
    prop, signer, applicator = _slab_property_and_licensees(api)
    graph = clean_initial_graph(api, prop["id"], signer["id"])
    plan = validate_success(
        api.create_treatment_plan(
            treatment_plan_payload(prop["id"], graph["id"], applicator["id"]),
            MANAGER_HEADERS,
        ),
        201,
    )
    plan = approve_plan(api, plan["id"])
    return {
        "property": prop,
        "signer": signer,
        "applicator": applicator,
        "inspection": graph,
        "plan": plan,
    }


def _bonded_slab_chain(api, issue_instant=BOND_ISSUE_INSTANT):
    """Carry the slab structure all the way to an ACTIVE REPAIR_AND_RETREAT bond."""
    chain = _approved_liquid_plan(api)
    plan = chain["plan"]
    record_application(
        api,
        plan["id"],
        chain["applicator"]["id"],
        plan["version"],
        gallons_applied=EXPECTED_TARGET_GALLONS,
    )
    chain["plan"] = complete_plan(api, plan["id"], chain["applicator"]["id"])
    set_clock(api, issue_instant)
    chain["bond"] = issue_bond(
        api,
        chain["property"]["id"],
        plan["id"],
        coverage_tier=TIER_REPAIR_AND_RETREAT,
    )
    return chain


def _completed_bait_plan(api, linear_footage):
    """A COMPLETED BAIT_STATION plan whose stations were installed by completion."""
    prop, signer, applicator = _slab_property_and_licensees(
        api, linear_footage=linear_footage, has_attached_structures=False
    )
    graph = clean_initial_graph(api, prop["id"], signer["id"])
    plan = propose_bait_plan(api, prop["id"], graph["id"], applicator["id"])
    plan = approve_plan(api, plan["id"])
    record_application(
        api, plan["id"], applicator["id"], plan["version"], gallons_applied=0.10
    )
    plan = complete_plan(api, plan["id"], applicator["id"])
    return {
        "property": prop,
        "signer": signer,
        "applicator": applicator,
        "inspection": graph,
        "plan": plan,
    }


def _read_plan(api, plan_id):
    return validate_success(api.get_treatment_plan(plan_id, MANAGER_HEADERS))


def _read_bond(api, bond_id):
    return validate_success(api.get_bond(bond_id, MANAGER_HEADERS))


# ---------------------------------------------------------------------------
# The stale-parent guard on POST /treatment-plans/{id}/applications
# ---------------------------------------------------------------------------


def test_application_accepted_at_the_plans_current_version_bumps_the_plan(api):
    """An application quoting the plan's live version is accepted and mutates it.

    PRD 3.6: "The plan's `gallons_applied_total` -- the running sum of
    `gallons_applied` over the plan's records -- is increased by the gallons
    just discharged, and the plan's `version` rises by one."

    Design: Corner/cross_cutting_complexity_layers/stale_plan_version_conflicts_while_the_refreshed_version_succeeds
    """
    chain = _approved_liquid_plan(api)
    plan = chain["plan"]
    assert_version(plan, 2, "treatment_plan")

    response = api.create_application(
        plan["id"],
        application_payload(plan["version"], gallons_applied=10.00),
        make_applicator_headers(chain["applicator"]["id"]),
    )
    record = validate_success(response, 201)
    assert_envelope_meta(response)
    assert_money(record["gallons_applied"], 10.00)

    refreshed = _read_plan(api, plan["id"])
    assert_version(refreshed, 3, "treatment_plan")
    assert_money(refreshed["gallons_applied_total"], 10.00)
    assert_status(refreshed, PLAN_APPROVED, "treatment_plan")


def test_replaying_the_same_expected_plan_version_is_refused_with_412(api):
    """The version that worked one call earlier is stale on the second call.

    PRD 2.7: "If that value does not equal the plan's current `version`, the
    application is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_plan_version_conflicts_while_the_refreshed_version_succeeds
    """
    chain = _approved_liquid_plan(api)
    plan = chain["plan"]
    applicator_headers = make_applicator_headers(chain["applicator"]["id"])
    approved_version = plan["version"]

    validate_success(
        api.create_application(
            plan["id"],
            application_payload(approved_version, gallons_applied=10.00),
            applicator_headers,
        ),
        201,
    )

    replay = api.create_application(
        plan["id"],
        application_payload(approved_version, gallons_applied=10.00),
        applicator_headers,
    )
    validate_error(replay, ERR_STALE_VERSION, 412)


def test_a_refused_application_writes_nothing_to_the_plan_or_its_record_list(api):
    """The refused replay leaves the gallons total, the version and the list alone.

    PRD 2.4: "`version`, an integer that starts at 1 when the row is created and
    increases by exactly 1 on every mutation of that row."

    Design: Corner/cross_cutting_complexity_layers/stale_plan_version_conflicts_while_the_refreshed_version_succeeds
    """
    chain = _approved_liquid_plan(api)
    plan = chain["plan"]
    applicator_headers = make_applicator_headers(chain["applicator"]["id"])
    approved_version = plan["version"]

    validate_success(
        api.create_application(
            plan["id"],
            application_payload(approved_version, gallons_applied=10.00),
            applicator_headers,
        ),
        201,
    )
    validate_error(
        api.create_application(
            plan["id"],
            application_payload(approved_version, gallons_applied=10.00),
            applicator_headers,
        ),
        ERR_STALE_VERSION,
    )

    after_refusal = _read_plan(api, plan["id"])
    assert_money(after_refusal["gallons_applied_total"], 10.00)
    assert_version(after_refusal, 3, "treatment_plan")

    rows, meta = validate_paginated(
        api.list_applications(plan["id"], MANAGER_HEADERS, limit=10, offset=0)
    )
    assert meta["total_count"] == 1, (
        "the refused application must not have created a record: total_count %r"
        % meta["total_count"]
    )
    assert len(rows) == 1


def test_the_refreshed_plan_version_is_accepted_after_the_stale_one_was_refused(api):
    """Version rises once per accepted write, never once per attempted write.

    PRD 2.7: "A plan accepts several applications by design, so nothing about the
    plan's status blocks a later one; the version guard is what stops an
    applicator from adding gallons on top of a plan view that no longer reflects
    the true `gallons_applied_total`."

    Design: Corner/cross_cutting_complexity_layers/stale_plan_version_conflicts_while_the_refreshed_version_succeeds
    """
    chain = _approved_liquid_plan(api)
    plan = chain["plan"]
    applicator_headers = make_applicator_headers(chain["applicator"]["id"])
    approved_version = plan["version"]

    validate_success(
        api.create_application(
            plan["id"],
            application_payload(approved_version, gallons_applied=10.00),
            applicator_headers,
        ),
        201,
    )
    validate_error(
        api.create_application(
            plan["id"],
            application_payload(approved_version, gallons_applied=10.00),
            applicator_headers,
        ),
        ERR_STALE_VERSION,
    )

    fresh_version = _read_plan(api, plan["id"])["version"]
    validate_success(
        api.create_application(
            plan["id"],
            application_payload(fresh_version, gallons_applied=10.00),
            applicator_headers,
        ),
        201,
    )

    final = _read_plan(api, plan["id"])
    assert_version(final, 4, "treatment_plan")
    assert_money(final["gallons_applied_total"], 20.00)
    assert_status(final, PLAN_APPROVED, "treatment_plan")
    assert_money(final["target_gallons"], EXPECTED_TARGET_GALLONS)


# ---------------------------------------------------------------------------
# The stale-parent guard on POST /damage-claims
# ---------------------------------------------------------------------------


def _bond_with_third_party_verifier(api):
    """An ACTIVE bond plus a signed zero-finding graph owned by a third party."""
    chain = _bonded_slab_chain(api)
    verifier = register_inspector(
        api,
        full_name="Ivan Reyes",
        license_state="FL",
        license_categories=[CATEGORY_WDO_INSPECTOR],
    )
    chain["verifier"] = verifier
    chain["verifying_inspection"] = clean_initial_graph(
        api, chain["property"]["id"], verifier["id"]
    )
    return chain


def test_filing_and_a_third_party_verification_each_bump_the_bond_by_one(api):
    """The owner's own filing and the inspector's verification both mutate the bond.

    PRD 3.10: "Filing also raises the bond's `version` by one, which is what makes
    a second blind filing against the same bond fail its version check."

    Design: Corner/cross_cutting_complexity_layers/stale_bond_version_conflicts_on_claim_creation
    """
    chain = _bond_with_third_party_verifier(api)
    bond = chain["bond"]
    assert_version(bond, 1, "bond")

    claim = file_claim(api, bond, chain["property"]["id"], 5000.00)
    assert_status(claim, CLAIM_SUBMITTED, "damage_claim")
    assert_version(_read_bond(api, bond["id"]), 2, "bond")

    verified = attach_verification(
        api,
        claim["id"],
        chain["verifying_inspection"]["id"],
        chain["verifier"]["id"],
    )
    assert_status(verified, CLAIM_UNDER_ADJUDICATION, "damage_claim")
    assert_version(_read_bond(api, bond["id"]), 3, "bond")


def test_replaying_the_pre_filing_bond_version_is_refused_with_412(api):
    """A third party's write invalidates the homeowner's copy of the bond version.

    PRD 2.7: "If that value does not equal the bond's current `version`, the
    filing is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_bond_version_conflicts_on_claim_creation
    """
    chain = _bond_with_third_party_verifier(api)
    bond = chain["bond"]
    stale_version = bond["version"]

    claim = file_claim(api, bond, chain["property"]["id"], 5000.00)
    attach_verification(
        api,
        claim["id"],
        chain["verifying_inspection"]["id"],
        chain["verifier"]["id"],
    )

    replay = api.create_damage_claim(
        damage_claim_payload(
            bond["id"], stale_version, 100.00, claim_type=CLAIM_TYPE_RETREAT
        ),
        make_property_owner_headers(chain["property"]["id"]),
    )
    validate_error(replay, ERR_STALE_VERSION, 412)


def test_the_refreshed_bond_version_files_a_claim_that_coexists_with_the_first(api):
    """One reserved claim plus any number of submitted ones is a legal ledger.

    PRD 3.10: "A bond may hold only one claim in `UNDER_ADJUDICATION` at a time,
    so a second verification while one claim still holds a reserve is
    `ERR_CLAIM_ALREADY_RESERVED`."

    Design: Corner/cross_cutting_complexity_layers/stale_bond_version_conflicts_on_claim_creation
    """
    chain = _bond_with_third_party_verifier(api)
    bond = chain["bond"]

    first = file_claim(api, bond, chain["property"]["id"], 5000.00)
    attach_verification(
        api,
        first["id"],
        chain["verifying_inspection"]["id"],
        chain["verifier"]["id"],
    )

    refreshed = _read_bond(api, bond["id"])
    second = validate_success(
        api.create_damage_claim(
            damage_claim_payload(
                bond["id"],
                refreshed["version"],
                100.00,
                claim_type=CLAIM_TYPE_RETREAT,
            ),
            make_property_owner_headers(chain["property"]["id"]),
        ),
        201,
    )
    assert_status(second, CLAIM_SUBMITTED, "damage_claim")

    rows, meta = validate_paginated(
        api.list_damage_claims(MANAGER_HEADERS, bond_id=bond["id"], limit=10, offset=0)
    )
    assert meta["total_count"] == 2, (
        "both claims must survive on the bond: total_count %r" % meta["total_count"]
    )
    by_id = {row["id"]: row["status"] for row in rows}
    assert by_id[first["id"]] == CLAIM_UNDER_ADJUDICATION
    assert by_id[second["id"]] == CLAIM_SUBMITTED


def test_a_zero_reserve_verification_still_bumps_the_bond_version(api):
    """The bump is unconditional, not money-driven: a 0.00 delta bumps too.

    PRD 3.10: "the bond reserves the money: `reserved_claim_amount_usd` rises by
    `projected_payout_usd` and `remaining_repair_cap_usd` falls by exactly the
    same amount, leaving the conservation law of 2.8 satisfied and raising the
    bond's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_bond_version_conflicts_on_claim_creation
    """
    chain = _bond_with_third_party_verifier(api)
    bond = chain["bond"]

    claim = file_claim(api, bond, chain["property"]["id"], 5000.00)
    before = _read_bond(api, bond["id"])

    verified = attach_verification(
        api,
        claim["id"],
        chain["verifying_inspection"]["id"],
        chain["verifier"]["id"],
    )
    assert_claim_money(
        verified,
        eligible_damage_usd=0.00,
        deductible_usd=0.00,
        projected_payout_usd=0.00,
    )

    after = _read_bond(api, bond["id"])
    assert after["version"] == before["version"] + 1, (
        "the verification must bump the bond even with a 0.00 reserve delta: %r -> %r"
        % (before["version"], after["version"])
    )
    assert_bond_money(
        after,
        repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
    )


# ---------------------------------------------------------------------------
# A refused cascade origin performs no partial cascade
# ---------------------------------------------------------------------------


def _bond_with_pending_renewal_and_submitted_claim(api):
    """An ACTIVE bond carrying one PENDING renewal and one SUBMITTED claim."""
    chain = _bonded_slab_chain(api)
    bond = chain["bond"]
    set_clock(api, "%sT00:00:00Z" % bond["renewal_window_opens_on"])
    chain["renewal"] = open_renewal(api, bond["id"])
    chain["claim"] = file_claim(
        api, _read_bond(api, bond["id"]), chain["property"]["id"], 5000.00
    )
    return chain


def _grace_deadline_instant(bond):
    """Midnight on the day after the bond's grace deadline."""
    return "%sT00:00:00Z" % date_plus_days(
        bond["current_term_end"], GRACE_PERIOD_DAYS + 1
    )


def test_a_term_review_inside_the_term_is_refused_with_invalid_bond_state(api):
    """Neither review transition's date precondition holds inside the term.

    PRD 3.8: "A review that finds neither deadline passed changes nothing and is
    refused with `ERR_INVALID_BOND_STATE`."

    Design: Corner/cross_cutting_complexity_layers/a_refused_cascade_origin_leaves_every_downstream_hop_untouched
    """
    chain = _bond_with_pending_renewal_and_submitted_claim(api)
    bond_before = _read_bond(api, chain["bond"]["id"])
    assert_status(bond_before, BOND_ACTIVE, "bond")

    refused = api.term_review(chain["bond"]["id"], {}, OFFICER_HEADERS)
    validate_error(refused, ERR_INVALID_BOND_STATE, 409)

    bond_after = _read_bond(api, chain["bond"]["id"])
    assert_status(bond_after, BOND_ACTIVE, "bond")
    assert bond_after["lapse_date"] is None, (
        "a refused review must not stamp lapse_date: %r" % bond_after["lapse_date"]
    )
    assert bond_after["version"] == bond_before["version"], (
        "a refused origin must not mutate the bond: %r -> %r"
        % (bond_before["version"], bond_after["version"])
    )


def test_a_refused_term_review_leaves_the_renewal_and_the_claim_untouched(api):
    """A hop that does not fire cannot cause the hop beneath it.

    PRD 2.11: "Where they do, the changes form a **chain**: each hop is caused by
    the hop before it, not by the original request, and a hop that does not fire
    cannot cause the hop beneath it."

    Design: Corner/cross_cutting_complexity_layers/a_refused_cascade_origin_leaves_every_downstream_hop_untouched
    """
    chain = _bond_with_pending_renewal_and_submitted_claim(api)
    validate_error(
        api.term_review(chain["bond"]["id"], {}, OFFICER_HEADERS),
        ERR_INVALID_BOND_STATE,
    )

    renewal = validate_success(api.get_renewal(chain["renewal"]["id"], OFFICER_HEADERS))
    assert_status(renewal, RENEWAL_PENDING, "bond_renewal")
    assert_version(renewal, 1, "bond_renewal")

    claim = validate_success(
        api.get_damage_claim(chain["claim"]["id"], OFFICER_HEADERS)
    )
    assert_status(claim, CLAIM_SUBMITTED, "damage_claim")
    assert_version(claim, 1, "damage_claim")
    assert claim["denial_reason_code"] is None, (
        "an untouched claim carries no denial reason: %r" % claim["denial_reason_code"]
    )


def test_a_review_past_the_grace_deadline_lapses_the_bond_on_the_missed_date(api):
    """The recorded lapse_date is the deadline missed, not the day of the sweep.

    PRD 3.8: "The bond's `lapse_date` is set to `current_term_end` plus 30 days --
    the grace deadline that was actually missed, **not** the date on which the
    review happened to run, so a review three weeks late still records the true
    deadline."

    Design: Corner/cross_cutting_complexity_layers/a_refused_cascade_origin_leaves_every_downstream_hop_untouched
    """
    chain = _bond_with_pending_renewal_and_submitted_claim(api)
    bond = chain["bond"]
    before = _read_bond(api, bond["id"])

    set_clock(api, _grace_deadline_instant(bond))
    reviewed = validate_success(api.term_review(bond["id"], {}, OFFICER_HEADERS))

    assert_status(reviewed, BOND_LAPSED, "bond")
    assert reviewed["lapse_date"] == date_plus_days(
        bond["current_term_end"], GRACE_PERIOD_DAYS
    ), (
        "lapse_date must be current_term_end plus 30 days, got %r"
        % reviewed["lapse_date"]
    )
    assert reviewed["version"] == before["version"] + 1, (
        "the whole cascade advances the bond by exactly 1: %r -> %r"
        % (before["version"], reviewed["version"])
    )


def test_the_lapse_cascade_voids_the_renewal_and_denies_the_claim_in_one_call(api):
    """Hop 2 fires on both children of the lapsed bond at once.

    PRD 3.8: "every renewal invoice of that bond still in `PENDING` moves to
    `VOID`, and every damage claim of that bond in `SUBMITTED` or
    `UNDER_ADJUDICATION` moves to `DENIED` with `denial_reason_code` set to
    `BOND_LAPSED`."

    Design: Corner/cross_cutting_complexity_layers/a_refused_cascade_origin_leaves_every_downstream_hop_untouched
    """
    chain = _bond_with_pending_renewal_and_submitted_claim(api)
    set_clock(api, _grace_deadline_instant(chain["bond"]))
    validate_success(api.term_review(chain["bond"]["id"], {}, OFFICER_HEADERS))

    renewal = validate_success(api.get_renewal(chain["renewal"]["id"], OFFICER_HEADERS))
    assert_status(renewal, RENEWAL_VOID, "bond_renewal")
    assert_version(renewal, 2, "bond_renewal")

    claim = validate_success(
        api.get_damage_claim(chain["claim"]["id"], OFFICER_HEADERS)
    )
    assert_status(claim, CLAIM_DENIED, "damage_claim")
    assert claim["denial_reason_code"] == DENIAL_BOND_LAPSED, (
        "a lapse denial names BOND_LAPSED, got %r" % claim["denial_reason_code"]
    )
    assert_version(claim, 2, "damage_claim")


def test_a_claim_denied_out_of_submitted_releases_no_reserve(api):
    """Hop 3 is data-dependent: a claim that never reserved releases nothing.

    PRD 3.8: "The third hop is caused only by those claim denials that came from
    `UNDER_ADJUDICATION` ... A claim denied out of `SUBMITTED` had reserved
    nothing and releases nothing."

    Design: Corner/cross_cutting_complexity_layers/a_refused_cascade_origin_leaves_every_downstream_hop_untouched
    """
    chain = _bond_with_pending_renewal_and_submitted_claim(api)
    set_clock(api, _grace_deadline_instant(chain["bond"]))
    lapsed = validate_success(api.term_review(chain["bond"]["id"], {}, OFFICER_HEADERS))

    assert_bond_money(
        lapsed,
        repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
    )
    assert_money(lapsed["remaining_repair_cap_usd"], lapsed["repair_liability_cap_usd"])


# ---------------------------------------------------------------------------
# The activity run length and the plan-level escalation threshold
# ---------------------------------------------------------------------------

# 200 linear feet over a 10-foot spacing installs exactly 20 stations.
FOOTAGE_FOR_20_STATIONS = 200
# 205 linear feet rounds up to 21, which is the first count whose threshold is 2.
FOOTAGE_FOR_21_STATIONS = 205

VISIT_1_INSTANT = "2026-08-20T00:00:00Z"
VISIT_2_INSTANT = "2026-09-19T00:00:00Z"
VISIT_3_INSTANT = "2026-10-19T00:00:00Z"


def _stations_of(api, plan_id):
    """The station listing beneath one plan, station_index ascending."""
    stations = list_stations(api, plan_id, limit=100, offset=0)
    assert_station_index_ascending(stations)
    return stations


def _visit(api, station_id, applicator_id, instant, activity, matrix_replaced=True):
    """Park the clock and record one visit at that instant."""
    set_clock(api, instant)
    return service_station(
        api, station_id, applicator_id, activity, matrix_replaced=matrix_replaced
    )


def _read_station(api, station_id):
    return validate_success(api.get_bait_station(station_id, MANAGER_HEADERS))


def test_two_moderate_visits_extend_the_run_without_escalating_the_station(api):
    """A run of two leaves the station in ACTIVE_HIT on the 30-day rhythm.

    PRD 3.9: "A `MODERATE` or `HEAVY` visit raises `consecutive_activity_count` by
    one; if the resulting run length is 3 or more the station becomes
    `ESCALATED`, and otherwise it becomes `ACTIVE_HIT`."

    Design: Corner/cross_cutting_complexity_layers/three_consecutive_activity_hits_escalate_a_station_and_two_do_not
    """
    chain = _completed_bait_plan(api, FOOTAGE_FOR_20_STATIONS)
    station = _stations_of(api, chain["plan"]["id"])[0]
    assert_status(station, STATION_INSTALLED, "bait_station")
    applicator_id = chain["applicator"]["id"]

    first = _visit(api, station["id"], applicator_id, VISIT_1_INSTANT, ACTIVITY_MODERATE)
    assert first["days_since_last_service"] == 19, (
        "19 whole days from installation to the first visit, got %r"
        % first["days_since_last_service"]
    )
    assert first["interval_compliance"] == COMPLIANCE_ON_TIME, (
        "19 days against the 90-day INSTALLED interval is ON_TIME, got %r"
        % first["interval_compliance"]
    )
    after_first = _read_station(api, station["id"])
    assert_status(after_first, STATION_ACTIVE_HIT, "bait_station")
    assert after_first["consecutive_activity_count"] == 1, (
        "run length after one hit is 1, got %r"
        % after_first["consecutive_activity_count"]
    )
    assert_instant_equals(after_first["next_due_at"], VISIT_2_INSTANT)

    second = _visit(
        api, station["id"], applicator_id, VISIT_2_INSTANT, ACTIVITY_MODERATE
    )
    assert second["days_since_last_service"] == STATION_INTERVAL_DAYS[
        STATION_ACTIVE_HIT
    ], (
        "the second gap is exactly the 30-day ACTIVE_HIT interval, got %r"
        % second["days_since_last_service"]
    )
    assert second["interval_compliance"] == COMPLIANCE_ON_TIME, (
        "a gap of exactly the interval is ON_TIME, got %r"
        % second["interval_compliance"]
    )
    after_second = _read_station(api, station["id"])
    assert_status(after_second, STATION_ACTIVE_HIT, "bait_station")
    assert after_second["consecutive_activity_count"] == 2, (
        "run length after two hits is 2, got %r"
        % after_second["consecutive_activity_count"]
    )


def test_a_run_of_two_leaves_the_installing_plan_completely_untouched(api):
    """The plan-level hop fires only when a station newly enters ESCALATED.

    PRD 3.9: "The second hop fires only when a station newly enters `ESCALATED`
    from some other status: the installing plan's `escalated_station_count` rises
    by one."

    Design: Corner/cross_cutting_complexity_layers/three_consecutive_activity_hits_escalate_a_station_and_two_do_not
    """
    chain = _completed_bait_plan(api, FOOTAGE_FOR_20_STATIONS)
    plan = chain["plan"]
    assert plan["target_station_count"] == expected_target_station_count(
        METHOD_BAIT_STATION, FOOTAGE_FOR_20_STATIONS, False
    ) == 20, "200 feet over a 10-foot spacing installs 20 stations, got %r" % plan[
        "target_station_count"
    ]
    station = _stations_of(api, plan["id"])[0]

    _visit(api, station["id"], chain["applicator"]["id"], VISIT_1_INSTANT, ACTIVITY_MODERATE)
    _visit(api, station["id"], chain["applicator"]["id"], VISIT_2_INSTANT, ACTIVITY_MODERATE)

    after_two = _read_plan(api, plan["id"])
    assert after_two["escalated_station_count"] == 0, (
        "two hits are below the run threshold, got escalated_station_count %r"
        % after_two["escalated_station_count"]
    )
    assert after_two["retreat_required"] is False, (
        "no escalation means no retreat obligation, got %r"
        % after_two["retreat_required"]
    )


def test_the_third_consecutive_hit_escalates_and_shortens_the_interval_to_14_days(api):
    """Escalation recomputes next_due_at on the 14-day rhythm, not the 30-day one.

    PRD 3.9: "Whatever the outcome, `next_due_at` is recomputed as `serviced_at`
    plus the interval of the station's **new** status, `service_count` rises by
    one, and `matrix_replacement_count` rises by one as well when
    `matrix_replaced` was true."

    Design: Corner/cross_cutting_complexity_layers/three_consecutive_activity_hits_escalate_a_station_and_two_do_not
    """
    chain = _completed_bait_plan(api, FOOTAGE_FOR_20_STATIONS)
    station = _stations_of(api, chain["plan"]["id"])[0]
    applicator_id = chain["applicator"]["id"]
    for instant in (VISIT_1_INSTANT, VISIT_2_INSTANT, VISIT_3_INSTANT):
        _visit(api, station["id"], applicator_id, instant, ACTIVITY_MODERATE)

    escalated = _read_station(api, station["id"])
    assert_status(escalated, STATION_ESCALATED, "bait_station")
    assert escalated["consecutive_activity_count"] == 3, (
        "the escalating run length is 3, got %r"
        % escalated["consecutive_activity_count"]
    )
    assert_instant_equals(
        escalated["next_due_at"],
        instant_plus_days(VISIT_3_INSTANT, STATION_INTERVAL_DAYS[STATION_ESCALATED]),
    )
    assert escalated["service_count"] == 3, (
        "three visits give service_count 3, got %r" % escalated["service_count"]
    )
    assert escalated["matrix_replacement_count"] == 3, (
        "three replacements give matrix_replacement_count 3, got %r"
        % escalated["matrix_replacement_count"]
    )


def test_one_escalation_meets_the_threshold_of_a_twenty_station_plan(api):
    """On 20 stations the ceiling of five percent is a single escalated station.

    PRD 3.9: "the plan's `retreat_required` is then set true when
    `escalated_station_count` has reached the plan's escalation threshold, which
    is 5 percent of the plan's `target_station_count` raised to the next whole
    number — a threshold that, for any station count from 1 to 20, evaluates to a
    single escalated station."

    Design: Corner/cross_cutting_complexity_layers/three_consecutive_activity_hits_escalate_a_station_and_two_do_not
    """
    chain = _completed_bait_plan(api, FOOTAGE_FOR_20_STATIONS)
    plan = chain["plan"]
    station = _stations_of(api, plan["id"])[0]
    escalate_station(api, station["id"], chain["applicator"]["id"], VISIT_1_INSTANT)

    assert expected_escalation_threshold(20) == 1, "ceil(20 * 0.05) is 1"
    after = _read_plan(api, plan["id"])
    assert after["escalated_station_count"] == 1, (
        "one station escalated, got %r" % after["escalated_station_count"]
    )
    assert after["retreat_required"] is True, (
        "1 escalation meets a threshold of 1, so retreat_required must be true"
    )


STATION_B_VISITS = (
    "2026-10-20T00:00:00Z",
    "2026-11-19T00:00:00Z",
    "2026-12-19T00:00:00Z",
)


def _escalate_with_heavy_hits(api, station_id, applicator_id, instants, matrix=True):
    """Three HEAVY visits at the given instants drive one station to ESCALATED."""
    return [
        _visit(api, station_id, applicator_id, instant, ACTIVITY_HEAVY, matrix)
        for instant in instants
    ]


def test_the_first_escalation_of_a_twenty_one_station_plan_leaves_retreat_false(api):
    """One extra station raises the ceiling to two, so one escalation is not enough.

    PRD 3.9: "the plan's `retreat_required` is then set true when
    `escalated_station_count` has reached the plan's escalation threshold, which
    is 5 percent of the plan's `target_station_count` raised to the next whole
    number."

    Design: Corner/cross_cutting_complexity_layers/plan_escalation_threshold_is_ceil_five_percent_of_the_installed_station_count
    """
    chain = _completed_bait_plan(api, FOOTAGE_FOR_21_STATIONS)
    plan = chain["plan"]
    assert plan["target_station_count"] == expected_target_station_count(
        METHOD_BAIT_STATION, FOOTAGE_FOR_21_STATIONS, False
    ) == 21, "205 feet over a 10-foot spacing installs 21 stations, got %r" % plan[
        "target_station_count"
    ]
    assert expected_escalation_threshold(21) == 2, "ceil(21 * 0.05) is 2, not 1"

    stations = _stations_of(api, plan["id"])
    _escalate_with_heavy_hits(
        api,
        stations[0]["id"],
        chain["applicator"]["id"],
        (VISIT_1_INSTANT, VISIT_2_INSTANT, VISIT_3_INSTANT),
    )

    assert_status(_read_station(api, stations[0]["id"]), STATION_ESCALATED, "bait_station")
    after_one = _read_plan(api, plan["id"])
    assert after_one["escalated_station_count"] == 1, (
        "one station escalated, got %r" % after_one["escalated_station_count"]
    )
    assert after_one["retreat_required"] is False, (
        "1 escalation is below a threshold of 2, so retreat_required stays false"
    )


def test_the_second_stations_first_visit_grades_on_time_at_eighty_days(api):
    """The 90-day INSTALLED interval is graded inclusively against the gap.

    PRD 3.9: "`interval_compliance` grades that gap against the interval
    belonging to the station's status **before** this visit, not after it: a gap
    no greater than the interval is `ON_TIME`."

    Design: Corner/cross_cutting_complexity_layers/plan_escalation_threshold_is_ceil_five_percent_of_the_installed_station_count
    """
    chain = _completed_bait_plan(api, FOOTAGE_FOR_21_STATIONS)
    stations = _stations_of(api, chain["plan"]["id"])

    first_visit = _visit(
        api,
        stations[1]["id"],
        chain["applicator"]["id"],
        STATION_B_VISITS[0],
        ACTIVITY_MODERATE,
        matrix_replaced=False,
    )
    assert first_visit["days_since_last_service"] == 80, (
        "80 whole days from installation to 2026-10-20, got %r"
        % first_visit["days_since_last_service"]
    )
    assert first_visit["interval_compliance"] == COMPLIANCE_ON_TIME, (
        "80 days against the 90-day INSTALLED interval is ON_TIME, got %r"
        % first_visit["interval_compliance"]
    )
    after = _read_station(api, stations[1]["id"])
    assert after["matrix_replacement_count"] == 0, (
        "a visit that replaced no matrix leaves the counter at 0, got %r"
        % after["matrix_replacement_count"]
    )


def test_only_the_second_escalated_station_flips_the_plans_retreat_flag(api):
    """The threshold is met by the second station, not by more visits on the first.

    PRD 3.9: "The second hop fires only when a station newly enters `ESCALATED`
    from some other status: the installing plan's `escalated_station_count` rises
    by one."

    Design: Corner/cross_cutting_complexity_layers/plan_escalation_threshold_is_ceil_five_percent_of_the_installed_station_count
    """
    chain = _completed_bait_plan(api, FOOTAGE_FOR_21_STATIONS)
    plan = chain["plan"]
    applicator_id = chain["applicator"]["id"]
    stations = _stations_of(api, plan["id"])

    _escalate_with_heavy_hits(
        api,
        stations[0]["id"],
        applicator_id,
        (VISIT_1_INSTANT, VISIT_2_INSTANT, VISIT_3_INSTANT),
    )
    for instant in STATION_B_VISITS:
        _visit(
            api,
            stations[1]["id"],
            applicator_id,
            instant,
            ACTIVITY_MODERATE,
            matrix_replaced=False,
        )

    assert_status(_read_station(api, stations[1]["id"]), STATION_ESCALATED, "bait_station")
    after_two = _read_plan(api, plan["id"])
    assert after_two["escalated_station_count"] == 2, (
        "escalated_station_count counts stations, and six visits escalated 2: %r"
        % after_two["escalated_station_count"]
    )
    assert after_two["retreat_required"] is True, (
        "2 escalations meet a threshold of 2, so retreat_required must be true"
    )


def test_every_station_grid_ref_is_derived_from_its_own_ordinal(api):
    """The column letter advances one place per complete block of ten stations.

    PRD 3.6: "stations 1 through 10 take column `A` with rows 1 through 10,
    stations 11 through 20 take column `B` with rows 1 through 10, and so on --
    the column letter advances one place in the alphabet for each complete block
    of ten stations, and the row is the position within the block."

    Design: Corner/cross_cutting_complexity_layers/plan_escalation_threshold_is_ceil_five_percent_of_the_installed_station_count
    """
    chain = _completed_bait_plan(api, FOOTAGE_FOR_21_STATIONS)
    stations = _stations_of(api, chain["plan"]["id"])
    assert len(stations) == 21, "21 stations were installed, got %d" % len(stations)

    by_index = {row["station_index"]: row for row in stations}
    assert by_index[1]["grid_ref"] == expected_station_grid_ref(1) == "A1", (
        "station 1 sits at A1, got %r" % by_index[1]["grid_ref"]
    )
    assert by_index[11]["grid_ref"] == expected_station_grid_ref(11) == "B1", (
        "station 11 opens the second block at B1, got %r" % by_index[11]["grid_ref"]
    )
    assert by_index[21]["grid_ref"] == expected_station_grid_ref(21) == "C1", (
        "station 21 opens the third block at C1, got %r" % by_index[21]["grid_ref"]
    )
    for row in stations:
        assert row["grid_ref"] == expected_station_grid_ref(row["station_index"]), (
            "station %r must sit at %r, got %r"
            % (
                row["station_index"],
                expected_station_grid_ref(row["station_index"]),
                row["grid_ref"],
            )
        )


# ---------------------------------------------------------------------------
# Every derived value is visible in the response that produced it
# ---------------------------------------------------------------------------

CLAIMED_DAMAGE = 3000.00
EXPECTED_DEDUCTIBLE = round_half_up(
    CLAIMED_DAMAGE * expected_deductible_rate(CLAIMED_DAMAGE), 2
)
EXPECTED_PROJECTED_PAYOUT = CLAIMED_DAMAGE - EXPECTED_DEDUCTIBLE


def _visible_derivation_chain(api):
    """Walk plan -> bond -> claim -> verification, keeping every raw response."""
    prop, signer, applicator = _slab_property_and_licensees(api)
    verifier = register_inspector(
        api,
        full_name="Ivan Reyes",
        license_state="FL",
        license_categories=[CATEGORY_WDO_INSPECTOR],
    )
    graph = graphed_inspection(
        api,
        prop["id"],
        signer["id"],
        findings=[
            conducive_finding_payload("A1", CONDUCIVE_WOOD_TO_GROUND, severity=2),
            conducive_finding_payload("A2", CONDUCIVE_EXCESS_MOISTURE, severity=2),
        ],
    )

    plan_response = api.create_treatment_plan(
        treatment_plan_payload(prop["id"], graph["id"], applicator["id"]),
        MANAGER_HEADERS,
    )
    plan = validate_success(plan_response, 201)
    plan = approve_plan(api, plan["id"])
    record_application(
        api,
        plan["id"],
        applicator["id"],
        plan["version"],
        gallons_applied=EXPECTED_TARGET_GALLONS,
    )
    complete_plan(api, plan["id"], applicator["id"])

    set_clock(api, BOND_ISSUE_INSTANT)
    bond_response = api.create_bond(
        bond_payload(
            prop["id"],
            plan["id"],
            coverage_tier=TIER_REPAIR_AND_RETREAT,
            conducive_waiver_codes=[CONDUCIVE_WOOD_TO_GROUND],
        ),
        MANAGER_HEADERS,
    )
    bond = validate_success(bond_response, 201)
    # Read the structure's ledger before any later graph replaces the evidence.
    property_response = api.get_property(prop["id"], MANAGER_HEADERS)

    damage_graph = graphed_inspection(
        api,
        prop["id"],
        verifier["id"],
        findings=[
            damage_finding_payload(
                "B3",
                CLAIMED_DAMAGE,
                pre_existing=False,
                severity=4,
                organism=ORGANISM_SUBTERRANEAN_TERMITE,
            )
        ],
    )
    claim = file_claim(
        api, _read_bond(api, bond["id"]), prop["id"], CLAIMED_DAMAGE
    )
    verification_response = api.attach_verification(
        claim["id"],
        verification_payload(damage_graph["id"]),
        make_field_inspector_headers(verifier["id"]),
    )
    bond_after_response = api.get_bond(bond["id"], MANAGER_HEADERS)
    return {
        "property": prop,
        "plan_response": plan_response,
        "bond_response": bond_response,
        "property_response": property_response,
        "claim": claim,
        "verification_response": verification_response,
        "bond_after_response": bond_after_response,
    }


def test_the_plan_create_response_already_carries_its_sizing_and_its_quote(api):
    """Proposal computes both derived figures and returns them in the same body.

    PRD 3.5: "Proposal computes the treatment sizing and the price, and both are
    derived entirely from the structure and the chosen method."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_produced_it
    """
    chain = _visible_derivation_chain(api)
    created = validate_success(chain["plan_response"], 201)
    assert_envelope_meta(chain["plan_response"])

    assert_money(created["target_gallons"], EXPECTED_TARGET_GALLONS)
    assert_money(created["target_gallons"], 190.00)
    assert_money(created["quoted_price_usd"], EXPECTED_QUOTED_PRICE)
    assert_money(created["quoted_price_usd"], 1080.00)
    assert created["target_station_count"] == 0, (
        "a liquid-barrier plan installs no stations, got %r"
        % created["target_station_count"]
    )


def test_the_bond_create_response_already_carries_all_six_money_fields(api):
    """Issuance prices the bond and opens its ledger in one response.

    PRD 3.7: "`claims_paid_to_date_usd` and `reserved_claim_amount_usd` both
    start at 0.00 and `remaining_repair_cap_usd` starts equal to
    `repair_liability_cap_usd`."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_produced_it
    """
    chain = _visible_derivation_chain(api)
    created = validate_success(chain["bond_response"], 201)
    assert_envelope_meta(chain["bond_response"])

    assert_bond_money(
        created,
        base_premium_usd=EXPECTED_BASE_PREMIUM,
        repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
        annual_premium_usd=EXPECTED_ANNUAL_PREMIUM,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
    )
    assert_money(created["base_premium_usd"], 194.40)
    assert_money(created["repair_liability_cap_usd"], 11664.00)
    assert_money(created["annual_premium_usd"], 241.06)
    assert_repair_liability_conserved(created)


def test_the_structures_ledger_reflects_the_bond_waiver_on_the_very_next_read(api):
    """The waiver supplied in the bond write is already suppressing a condition.

    PRD 3.1: "`waived_conducive_condition_count` is the number of those notations
    whose `conducive_code` appears in the `conducive_waiver_codes` of the
    structure's bond of record, and `open_conducive_condition_count` is the
    remainder."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_produced_it
    """
    chain = _visible_derivation_chain(api)
    prop = validate_success(chain["property_response"])
    assert_envelope_meta(chain["property_response"])

    assert prop["total_conducive_condition_count"] == 2, (
        "two conducive notations were signed, got %r"
        % prop["total_conducive_condition_count"]
    )
    assert prop["waived_conducive_condition_count"] == 1, (
        "one of the two codes is waived by the bond, got %r"
        % prop["waived_conducive_condition_count"]
    )
    assert prop["open_conducive_condition_count"] == 1, (
        "the remainder stays open, got %r" % prop["open_conducive_condition_count"]
    )
    assert_conducive_counts_conserved(prop)


def test_the_verification_response_already_carries_the_priced_claim(api):
    """Attaching the verifying graph prices the claim in the same response.

    PRD 3.10: "Attaching the verifying graph is the moment the claim is priced.
    ... The deductible is then a percentage of the eligible amount, and
    `projected_payout_usd` is the eligible amount less the deductible."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_produced_it
    """
    chain = _visible_derivation_chain(api)
    verified = validate_success(chain["verification_response"])
    assert_envelope_meta(chain["verification_response"])

    assert verified["exclusion_basis"] == EXCLUSION_AGGREGATE_PRORATION, (
        "a verifying graph that supersedes nothing prices on the aggregate basis, got %r"
        % verified["exclusion_basis"]
    )
    assert_claim_money(
        verified,
        eligible_damage_usd=CLAIMED_DAMAGE,
        excluded_pre_existing_usd=0.00,
        deductible_usd=EXPECTED_DEDUCTIBLE,
        projected_payout_usd=EXPECTED_PROJECTED_PAYOUT,
    )
    assert_money(verified["deductible_usd"], 210.00)
    assert_money(verified["projected_payout_usd"], 2790.00)
    assert_status(verified, CLAIM_UNDER_ADJUDICATION, "damage_claim")


def test_the_bond_read_after_verification_shows_the_reserve_already_moved(api):
    """The reserve appears on the bond without a second triggering call.

    PRD 3.10: "the bond's `reserved_claim_amount_usd` is increased by
    `projected_payout_usd` and its `remaining_repair_cap_usd` is reduced by the
    same amount."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_produced_it
    """
    chain = _visible_derivation_chain(api)
    bond = validate_success(chain["bond_after_response"])
    assert_envelope_meta(chain["bond_after_response"])

    assert_bond_money(
        bond,
        repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=EXPECTED_PROJECTED_PAYOUT,
        remaining_repair_cap_usd=EXPECTED_REPAIR_CAP - EXPECTED_PROJECTED_PAYOUT,
    )
    assert_money(bond["reserved_claim_amount_usd"], 2790.00)
    assert_money(bond["remaining_repair_cap_usd"], 8874.00)
    assert_repair_liability_conserved(bond)


def test_single_row_reads_return_an_object_and_list_reads_return_an_array(api):
    """The envelope declares its own payload shape on every response in the chain.

    PRD 2.2: "`response_type` is `object` for a single resource, `array` for a
    collection."

    Design: Corner/consistency_model/every_derived_value_is_visible_in_the_response_that_produced_it
    """
    chain = _visible_derivation_chain(api)
    for label in ("plan_response", "bond_response", "property_response"):
        body = chain[label].json()
        assert body["response_type"] == "object", (
            "%s is a single-row response, got response_type %r"
            % (label, body["response_type"])
        )
        assert isinstance(body["data"], dict), (
            "%s must carry data as an object, got %r" % (label, type(body["data"]))
        )

    listing = api.list_damage_claims(MANAGER_HEADERS)
    rows, meta = validate_paginated(listing)
    assert_envelope_meta(listing)
    assert meta["total_count"] == 1, (
        "one claim was filed in the chain, got total_count %r" % meta["total_count"]
    )
    assert rows[0]["id"] == chain["claim"]["id"], (
        "the listing returns the claim just filed, got %r" % rows[0]["id"]
    )
