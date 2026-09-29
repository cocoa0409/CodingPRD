"""Lifecycle transitions of the licence, the graph, the plan, the station and the bond.

Every test builds its own preconditions from a bare database and drives one
resource along the transitions the contract declares, asserting both the row
that moved and the rows the move cascaded into.
"""

from test_helpers import (
    ACTIVITY_LIGHT,
    ACTIVITY_MODERATE,
    ACTIVITY_NONE,
    BOND_LAPSED,
    BOND_TERMINATED,
    CLAIM_SUBMITTED,
    COMPLIANCE_ON_TIME,
    CONDUCIVE_EXCESS_MOISTURE,
    CONDUCIVE_WOOD_TO_GROUND,
    ERR_BOND_NOT_ACTIVE,
    ERR_INVALID_BOND_STATE,
    ERR_INVALID_INSPECTION_STATE,
    ERR_INVALID_INSPECTOR_STATE,
    ERR_INVALID_PLAN_STATE,
    ERR_LICENSE_REINSTATEMENT_UNMET,
    INSPECTION_DRAFT,
    INSPECTION_GRAPHED,
    INSPECTION_SUPERSEDED,
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_EXPIRED,
    LICENSE_STATUS_SUSPENDED,
    MANAGER_HEADERS,
    METHOD_BAIT_STATION,
    OFFICER_HEADERS,
    ORGANISM_FUNGUS,
    ORGANISM_SUBTERRANEAN_TERMITE,
    PLAN_ABANDONED,
    PLAN_APPROVED,
    PLAN_COMPLETED,
    PLAN_PROPOSED,
    PURPOSE_REINSTATEMENT,
    PURPOSE_RENEWAL,
    REPORT_ISSUED,
    REPORT_VOID,
    STATION_ACTIVE_HIT,
    STATION_INSTALLED,
    STATION_INTERVAL_DAYS,
    TIER_REPAIR_AND_RETREAT,
    add_finding,
    assert_bond_money,
    assert_conducive_counts_conserved,
    assert_entity_shape,
    assert_instant_equals,
    assert_money,
    assert_page,
    assert_repair_liability_conserved,
    assert_station_index_ascending,
    assert_status,
    assert_version,
    bait_plan_payload,
    bonded_property,
    clean_initial_graph,
    completed_bait_plan,
    completed_liquid_plan,
    conducive_finding_payload,
    damage_claim_payload,
    damage_finding_payload,
    expected_bond_money,
    expected_quoted_price,
    expected_station_grid_ref,
    expected_target_gallons,
    expected_target_station_count,
    infestation_finding_payload,
    inspection_payload,
    instant_plus_days,
    issue_wdo_report,
    lapse_bond,
    list_stations,
    make_field_inspector_headers,
    make_property_owner_headers,
    open_graph,
    open_wdo_report,
    propose_bait_plan,
    propose_plan,
    real_estate_graph,
    register_inspector,
    register_property_and_inspector,
    review_bond_term,
    service_station,
    set_clock,
    set_license_status,
    sign_empty_graph,
    sign_graph,
    station_service_payload,
    validate_error,
    validate_success,
)

CLOCK_START_RENDERED = "2026-08-01T00:00:00.000Z"


def _expired_licence(api):
    """A licence driven to EXPIRED, carrying a stale expiry and four CE credits."""
    inspector = register_inspector(
        api, license_expires_on="2026-09-30", ce_credits=4
    )
    return set_license_status(api, inspector["id"], LICENSE_STATUS_EXPIRED)


def _bait_plan_with_stations(api):
    """A COMPLETED BAIT_STATION plan on an FL slab, with the rows it installed."""
    prop, inspector = register_property_and_inspector(api)
    graph = clean_initial_graph(api, prop["id"], inspector["id"])
    plan = completed_bait_plan(api, prop["id"], graph["id"], inspector["id"])
    stations = list_stations(api, plan["id"], limit=20)
    return prop, inspector, plan, stations


def _active_hit_station(api):
    """One station moved to ACTIVE_HIT by a single MODERATE visit on 2026-09-01."""
    prop, inspector, plan, stations = _bait_plan_with_stations(api)
    station = stations[0]
    set_clock(api, "2026-09-01T00:00:00Z")
    service_station(api, station["id"], inspector["id"], ACTIVITY_MODERATE)
    return inspector, plan, station["id"]


def _terminated_bond(api):
    """A bond issued 2026-09-01, lapsed at its grace deadline and then terminated."""
    chain = bonded_property(api, issue_instant="2026-09-01T00:00:00Z")
    lapse_bond(api, chain["bond"])
    set_clock(api, "2027-12-31T00:00:00Z")
    return chain, review_bond_term(api, chain["bond"]["id"])


def test_licence_runs_the_suspension_loop_twice_and_ends_active(api):
    """Two ACTIVE -> SUSPENDED -> ACTIVE loops return the status to where it began.

    PRD 3.2: "`ACTIVE → SUSPENDED` requires the licence to be `ACTIVE` and
    simply sets it `SUSPENDED`. ... `SUSPENDED → ACTIVE` requires the licence to
    be `SUSPENDED` **and** its existing `license_expires_on` to fall on or after
    the logical clock's UTC date". "All four moves set the new `status` and raise
    the record's `version` by one."

    Design: Corner/state_machines/inspector_licence_suspend_and_reactivate_closes_the_cycle
    """
    inspector = register_inspector(api, ce_credits=12)
    assert_status(inspector, LICENSE_STATUS_ACTIVE, "inspector")
    assert_version(inspector, 1, "inspector")

    for expected_version, target in (
        (2, LICENSE_STATUS_SUSPENDED),
        (3, LICENSE_STATUS_ACTIVE),
        (4, LICENSE_STATUS_SUSPENDED),
        (5, LICENSE_STATUS_ACTIVE),
    ):
        moved = set_license_status(api, inspector["id"], target)
        assert_status(moved, target, "inspector")
        assert_version(moved, expected_version, "inspector")

    final = validate_success(api.get_inspector(inspector["id"], OFFICER_HEADERS))
    assert_status(final, LICENSE_STATUS_ACTIVE, "inspector")
    assert_version(final, 5, "inspector")


def test_the_suspension_loop_leaves_the_licence_facts_untouched(api):
    """Lifting a suspension edits the status and the version and nothing else.

    PRD 3.2: "All four moves set the new `status` and raise the record's
    `version` by one." Only the reinstatement path rewrites the credential
    itself: "On a successful reinstatement the record's `license_expires_on`
    becomes the supplied date and its `ce_credits` becomes the supplied balance
    when one was supplied, remaining unchanged otherwise."

    Design: Corner/state_machines/inspector_licence_suspend_and_reactivate_closes_the_cycle
    """
    inspector = register_inspector(api, ce_credits=12)
    set_license_status(api, inspector["id"], LICENSE_STATUS_SUSPENDED)
    set_license_status(api, inspector["id"], LICENSE_STATUS_ACTIVE)
    set_license_status(api, inspector["id"], LICENSE_STATUS_SUSPENDED)
    reactivated = set_license_status(api, inspector["id"], LICENSE_STATUS_ACTIVE)

    assert_entity_shape(reactivated, "inspector")
    assert reactivated["license_expires_on"] == inspector["license_expires_on"]
    assert reactivated["license_number"] == inspector["license_number"]
    assert reactivated["license_categories"] == inspector["license_categories"]
    assert reactivated["ce_credits"] == 12


def test_reinstatement_is_refused_on_the_ce_balance_already_on_file(api):
    """An expired licence with four credits on file cannot be reinstated.

    PRD 3.2: "the **effective** continuing-education balance — the request's
    `ce_credits` when the request supplies one, otherwise the balance already on
    file — must be at least 8. ... a failure of either condition is
    `ERR_LICENSE_REINSTATEMENT_UNMET`."

    Design: Corner/state_machines/expired_licence_reinstatement_requires_future_expiry_and_eight_ce_credits
    """
    expired = _expired_licence(api)
    assert_status(expired, LICENSE_STATUS_EXPIRED, "inspector")
    assert_version(expired, 2, "inspector")

    response = api.set_license_status(
        expired["id"],
        {"status": LICENSE_STATUS_ACTIVE, "license_expires_on": "2027-06-30"},
        OFFICER_HEADERS,
    )
    validate_error(response, ERR_LICENSE_REINSTATEMENT_UNMET)


def test_reinstatement_is_refused_on_an_expiry_that_only_equals_the_clock_date(api):
    """An expiry landing exactly on the clock date is not strictly after it.

    PRD 3.2: "the request must carry a `license_expires_on` strictly after the
    logical clock's UTC date ... An expired licence is never reactivated on the
    strength of its own stale expiry date".

    Design: Corner/state_machines/expired_licence_reinstatement_requires_future_expiry_and_eight_ce_credits
    """
    expired = _expired_licence(api)

    response = api.set_license_status(
        expired["id"],
        {
            "status": LICENSE_STATUS_ACTIVE,
            "license_expires_on": "2026-08-01",
            "ce_credits": 8,
        },
        OFFICER_HEADERS,
    )
    validate_error(response, ERR_LICENSE_REINSTATEMENT_UNMET)


def test_a_refused_reinstatement_writes_nothing_to_the_licence(api):
    """Neither refused attempt moves the status, the version or the credential.

    PRD 3.2: "An expired licence is never reactivated on the strength of its own
    stale expiry date, and never on an unmet continuing-education balance; a
    failure of either condition is `ERR_LICENSE_REINSTATEMENT_UNMET`."

    Design: Corner/state_machines/expired_licence_reinstatement_requires_future_expiry_and_eight_ce_credits
    """
    expired = _expired_licence(api)

    validate_error(
        api.set_license_status(
            expired["id"],
            {"status": LICENSE_STATUS_ACTIVE, "license_expires_on": "2027-06-30"},
            OFFICER_HEADERS,
        ),
        ERR_LICENSE_REINSTATEMENT_UNMET,
    )
    validate_error(
        api.set_license_status(
            expired["id"],
            {
                "status": LICENSE_STATUS_ACTIVE,
                "license_expires_on": "2026-08-01",
                "ce_credits": 8,
            },
            OFFICER_HEADERS,
        ),
        ERR_LICENSE_REINSTATEMENT_UNMET,
    )

    unchanged = validate_success(api.get_inspector(expired["id"], OFFICER_HEADERS))
    assert_status(unchanged, LICENSE_STATUS_EXPIRED, "inspector")
    assert_version(unchanged, 2, "inspector")
    assert unchanged["license_expires_on"] == "2026-09-30"
    assert unchanged["ce_credits"] == 4


def test_reinstatement_succeeds_with_a_future_expiry_and_eight_credits(api):
    """Both conditions met together return the licence to ACTIVE.

    PRD 3.2: "On a successful reinstatement the record's `license_expires_on`
    becomes the supplied date and its `ce_credits` becomes the supplied balance
    when one was supplied ... All four moves set the new `status` and raise the
    record's `version` by one."

    Design: Corner/state_machines/expired_licence_reinstatement_requires_future_expiry_and_eight_ce_credits
    """
    expired = _expired_licence(api)

    reinstated = set_license_status(
        api,
        expired["id"],
        LICENSE_STATUS_ACTIVE,
        license_expires_on="2027-06-30",
        ce_credits=8,
    )
    assert_status(reinstated, LICENSE_STATUS_ACTIVE, "inspector")
    assert_version(reinstated, 3, "inspector")
    assert reinstated["license_expires_on"] == "2027-06-30"
    assert reinstated["ce_credits"] == 8


def test_suspended_licence_cannot_be_moved_straight_to_expired(api):
    """SUSPENDED -> EXPIRED is not one of the four declared paths.

    PRD 3.2: "Any other pairing — a second `ACTIVE → ACTIVE` request, a move
    from `SUSPENDED` straight to `EXPIRED` — is not a declared transition and is
    refused with `ERR_INVALID_INSPECTOR_STATE`."

    Design: Corner/state_machines/inspector_cannot_move_from_suspended_to_expired
    """
    inspector = register_inspector(api)
    suspended = set_license_status(api, inspector["id"], LICENSE_STATUS_SUSPENDED)
    assert_version(suspended, 2, "inspector")

    response = api.set_license_status(
        inspector["id"], {"status": LICENSE_STATUS_EXPIRED}, OFFICER_HEADERS
    )
    validate_error(response, ERR_INVALID_INSPECTOR_STATE)

    unchanged = validate_success(api.get_inspector(inspector["id"], OFFICER_HEADERS))
    assert_status(unchanged, LICENSE_STATUS_SUSPENDED, "inspector")
    assert_version(unchanged, 2, "inspector")


def test_suspended_licence_cannot_be_suspended_a_second_time(api):
    """A SUSPENDED -> SUSPENDED self-transition is not declared either.

    PRD 3.2: "Any other pairing — a second `ACTIVE → ACTIVE` request, a move
    from `SUSPENDED` straight to `EXPIRED` — is not a declared transition and is
    refused with `ERR_INVALID_INSPECTOR_STATE`."

    Design: Corner/state_machines/inspector_cannot_move_from_suspended_to_expired
    """
    inspector = register_inspector(api)
    set_license_status(api, inspector["id"], LICENSE_STATUS_SUSPENDED)

    response = api.set_license_status(
        inspector["id"], {"status": LICENSE_STATUS_SUSPENDED}, OFFICER_HEADERS
    )
    validate_error(response, ERR_INVALID_INSPECTOR_STATE)

    unchanged = validate_success(api.get_inspector(inspector["id"], OFFICER_HEADERS))
    assert_status(unchanged, LICENSE_STATUS_SUSPENDED, "inspector")
    assert_version(unchanged, 2, "inspector")


def _four_cell_draft_graph(api):
    """A DRAFT graph carrying two EXCESS_MOISTURE cells, one damage and one hit."""
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api,
        graph["id"],
        inspector["id"],
        conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE),
    )
    add_finding(
        api,
        graph["id"],
        inspector["id"],
        conducive_finding_payload("B2", CONDUCIVE_EXCESS_MOISTURE),
    )
    add_finding(
        api,
        graph["id"],
        inspector["id"],
        damage_finding_payload("C3", 1200.00, severity=2, organism=ORGANISM_FUNGUS),
    )
    add_finding(
        api,
        graph["id"],
        inspector["id"],
        infestation_finding_payload("D4", ORGANISM_SUBTERRANEAN_TERMITE, severity=3),
    )
    return prop, inspector, graph


def test_signing_freezes_the_four_rollups_counted_per_row(api):
    """Signing stamps the completion instant and counts conducive cells per row.

    PRD 3.3: "`findings_count` is the number of notations on the graph.
    `conducive_condition_count` is the number of notations whose `finding_type`
    is `CONDUCIVE_CONDITION`, counted **per row rather than per distinct code**
    ... `active_infestation_found` is true when at least one notation has
    `finding_type` equal to `ACTIVE_INFESTATION`. `damage_estimate_total_usd` is
    the sum of `damage_estimate_usd` over the graph's `DAMAGE` notations".

    Design: Corner/state_machines/graph_complete_recomputes_rollups_and_the_property_ledger
    """
    _prop, inspector, graph = _four_cell_draft_graph(api)

    signed = sign_graph(api, graph["id"], inspector["id"])
    assert_status(signed, INSPECTION_GRAPHED, "inspection")
    assert_version(signed, 2, "inspection")
    assert_instant_equals(signed["graph_completed_at"], CLOCK_START_RENDERED)
    assert signed["findings_count"] == 4
    assert signed["conducive_condition_count"] == 2
    assert signed["active_infestation_found"] is True
    assert_money(signed["damage_estimate_total_usd"], 1200.00)
    assert signed["no_findings_attested"] is False


def test_signing_recomputes_the_property_ledger_over_distinct_codes(api):
    """The structure's ledger counts distinct codes where the graph counted rows.

    PRD 3.1: "the distinct `conducive_code` values are collected over that
    graph's cell notations whose `finding_type` is `CONDUCIVE_CONDITION` and
    whose `conducive_code` is something other than `NONE`; the number of
    distinct codes found is `total_conducive_condition_count`". "Two
    `EXCESS_MOISTURE` notations in different grid cells raise the graph's row
    count by two but the structure's distinct-code count by one."

    Design: Corner/state_machines/graph_complete_recomputes_rollups_and_the_property_ledger
    """
    prop, inspector, graph = _four_cell_draft_graph(api)

    sign_graph(api, graph["id"], inspector["id"])

    ledger = validate_success(api.get_property(prop["id"], MANAGER_HEADERS))
    assert ledger["total_conducive_condition_count"] == 1
    assert ledger["waived_conducive_condition_count"] == 0
    assert ledger["open_conducive_condition_count"] == 1
    assert ledger["active_infestation_on_record"] is True
    assert_conducive_counts_conserved(ledger)


def _issued_report_on_a_real_estate_graph(api):
    """A signed REAL_ESTATE graph with one conducive cell and an ISSUED report."""
    prop, inspector = register_property_and_inspector(api)
    graph = real_estate_graph(
        api,
        prop["id"],
        inspector["id"],
        findings=[conducive_finding_payload("A1", CONDUCIVE_WOOD_TO_GROUND)],
    )
    report = open_wdo_report(api, graph["id"])
    return prop, inspector, graph, issue_wdo_report(api, report["id"])


def _renewal_successor(api, property_id, inspector_id, prior_inspection_id):
    """Open a RENEWAL graph naming the graph it replaces, on a free diary slot."""
    return api.create_inspection(
        inspection_payload(
            property_id,
            inspector_id,
            purpose=PURPOSE_RENEWAL,
            supersedes_inspection_id=prior_inspection_id,
            scheduled_start_at="2026-08-02T13:00:00Z",
            scheduled_end_at="2026-08-02T15:00:00Z",
        ),
        make_field_inspector_headers(inspector_id),
    )


def test_the_superseding_graph_is_itself_created_as_a_draft(api):
    """The replacement graph opens in DRAFT and takes the next sequence number.

    PRD 3.3: "The new graph is created in status `DRAFT` and is stamped with a
    `sequence_no`: a 1-based counter that is one greater than the highest
    `sequence_no` yet issued for that structure".

    Design: Corner/state_machines/superseding_a_graph_cascades_into_voiding_its_wdo_report
    """
    prop, inspector, graph, _issued = _issued_report_on_a_real_estate_graph(api)

    successor = validate_success(
        _renewal_successor(api, prop["id"], inspector["id"], graph["id"]), 201
    )
    assert_status(successor, INSPECTION_DRAFT, "inspection")
    assert successor["sequence_no"] == 2
    assert successor["supersedes_inspection_id"] == graph["id"]
    assert successor["graph_completed_at"] is None
    assert_version(successor, 1, "inspection")


def test_naming_a_prior_graph_retires_it_immediately(api):
    """Hop one of the chain moves the named graph to the terminal SUPERSEDED state.

    PRD 3.3: "Supplying `supersedes_inspection_id` retires the prior graph
    immediately, and does so as a three-level chain. The first hop moves the
    named graph to `SUPERSEDED`, whether it was `GRAPHED` or still `DRAFT`."

    Design: Corner/state_machines/superseding_a_graph_cascades_into_voiding_its_wdo_report
    """
    prop, inspector, graph, _issued = _issued_report_on_a_real_estate_graph(api)

    _renewal_successor(api, prop["id"], inspector["id"], graph["id"])

    retired = validate_success(api.get_inspection(graph["id"], OFFICER_HEADERS))
    assert_status(retired, INSPECTION_SUPERSEDED, "inspection")
    assert_version(retired, 3, "inspection")
    assert_instant_equals(retired["graph_completed_at"], CLOCK_START_RENDERED)


def test_the_report_of_a_superseded_graph_is_voided_with_its_measurements_intact(api):
    """Hop two voids the statutory report without rewriting its service measures.

    PRD 3.3: "every statutory report transcribed from the now-superseded graph,
    in status `DRAFT`, `ISSUED` or `AMENDED`, is moved to `VOID`, because a
    filing whose underlying graph has been replaced can no longer be relied on
    at a closing."

    Design: Corner/state_machines/superseding_a_graph_cascades_into_voiding_its_wdo_report
    """
    prop, inspector, graph, issued = _issued_report_on_a_real_estate_graph(api)
    assert_status(issued, REPORT_ISSUED, "wdo_report")

    _renewal_successor(api, prop["id"], inspector["id"], graph["id"])

    voided = validate_success(api.get_wdo_report(issued["id"], OFFICER_HEADERS))
    assert_status(voided, REPORT_VOID, "wdo_report")
    assert_version(voided, 3, "wdo_report")
    assert_instant_equals(voided["issued_at"], issued["issued_at"])
    assert voided["turnaround_hours"] == issued["turnaround_hours"]
    assert voided["sla_breached"] == issued["sla_breached"]


def test_a_voided_report_is_still_a_readable_row(api):
    """Voiding is a status change rather than a delete, so the row still lists.

    PRD 3.4: "`VOID` is the report lifecycle's terminal state and is only ever
    reached from outside: as the second hop of the supersession chain in §3.3,
    every report of a graph that becomes `SUPERSEDED` is voided wherever it
    stood — `DRAFT`, `ISSUED` or `AMENDED`."

    Design: Corner/state_machines/superseding_a_graph_cascades_into_voiding_its_wdo_report
    """
    prop, inspector, graph, issued = _issued_report_on_a_real_estate_graph(api)

    _renewal_successor(api, prop["id"], inspector["id"], graph["id"])

    rows, _meta = assert_page(api.list_wdo_reports(OFFICER_HEADERS), 1)
    assert rows[0]["id"] == issued["id"]
    assert rows[0]["status"] == REPORT_VOID


def test_supersession_recomputes_the_ledger_down_to_zero(api):
    """Hop three leaves the structure with no signed graph, so every counter is 0.

    PRD 3.1: "Graphs still in `DRAFT`, and graphs already `SUPERSEDED`,
    contribute nothing at all. ... the number of distinct codes found is
    `total_conducive_condition_count`, and it is 0 when the structure has no
    signed graph."

    Design: Corner/state_machines/superseding_a_graph_cascades_into_voiding_its_wdo_report
    """
    prop, inspector, graph, _issued = _issued_report_on_a_real_estate_graph(api)
    before = validate_success(api.get_property(prop["id"], OFFICER_HEADERS))
    assert before["total_conducive_condition_count"] == 1

    _renewal_successor(api, prop["id"], inspector["id"], graph["id"])

    after = validate_success(api.get_property(prop["id"], OFFICER_HEADERS))
    assert after["total_conducive_condition_count"] == 0
    assert after["waived_conducive_condition_count"] == 0
    assert after["open_conducive_condition_count"] == 0
    assert after["active_infestation_on_record"] is False


def _superseded_draft_graph(api):
    """A DRAFT graph retired by a REINSTATEMENT graph that names it."""
    prop, inspector = register_property_and_inspector(api)
    prior = open_graph(api, prop["id"], inspector["id"])
    successor = open_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_REINSTATEMENT,
        supersedes_inspection_id=prior["id"],
    )
    return prop, inspector, prior, successor


def test_a_superseded_graph_accepts_no_further_notations(api):
    """A retired graph is closed to cell notations and nothing is written.

    PRD 3.3: "Cell notations are added one at a time to a graph while it is
    still `DRAFT`; adding one to a graph in any other status is
    `ERR_INVALID_INSPECTION_STATE`."

    Design: Corner/state_machines/superseded_inspection_rejects_findings_and_graph_complete
    """
    _prop, inspector, prior, _successor = _superseded_draft_graph(api)

    response = api.create_finding(
        prior["id"],
        conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE),
        make_field_inspector_headers(inspector["id"]),
    )
    validate_error(response, ERR_INVALID_INSPECTION_STATE)

    retired = validate_success(api.get_inspection(prior["id"], OFFICER_HEADERS))
    assert_status(retired, INSPECTION_SUPERSEDED, "inspection")
    assert retired["findings_count"] == 0
    assert_version(retired, 2, "inspection")
    assert_page(api.list_findings(prior["id"], OFFICER_HEADERS), 0, expected_rows=0)


def test_a_superseded_graph_can_never_be_signed(api):
    """A retired graph is not evidence and never returns to service.

    PRD 3.3: "`SUPERSEDED` is terminal — a retired graph never returns to
    service, and it is not evidence for anything."

    Design: Corner/state_machines/superseded_inspection_rejects_findings_and_graph_complete
    """
    _prop, inspector, prior, _successor = _superseded_draft_graph(api)

    response = api.graph_complete(
        prior["id"], {}, make_field_inspector_headers(inspector["id"])
    )
    validate_error(response, ERR_INVALID_INSPECTION_STATE)

    retired = validate_success(api.get_inspection(prior["id"], OFFICER_HEADERS))
    assert_status(retired, INSPECTION_SUPERSEDED, "inspection")
    assert retired["graph_completed_at"] is None
    assert_version(retired, 2, "inspection")


def test_the_replacement_graph_is_unaffected_and_still_signable(api):
    """The cascade touches the graph that was named, not the one that named it.

    PRD 3.3: "A graph with no cell notations at all may only be signed when the
    request sets `no_findings_attested` to true, which is the inspector's formal
    attestation that the structure was examined and nothing was found."

    Design: Corner/state_machines/superseded_inspection_rejects_findings_and_graph_complete
    """
    _prop, inspector, _prior, successor = _superseded_draft_graph(api)
    assert_status(successor, INSPECTION_DRAFT, "inspection")

    signed = sign_empty_graph(api, successor["id"], inspector["id"])
    assert_status(signed, INSPECTION_GRAPHED, "inspection")
    assert signed["no_findings_attested"] is True
    assert_version(signed, 2, "inspection")


def _signed_graph_with_one_conducive_cell(api):
    """A signed INITIAL graph carrying a single EXCESS_MOISTURE cell."""
    prop, inspector = register_property_and_inspector(api)
    graph = open_graph(api, prop["id"], inspector["id"])
    add_finding(
        api,
        graph["id"],
        inspector["id"],
        conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE),
    )
    return prop, inspector, sign_graph(api, graph["id"], inspector["id"])


def test_signing_a_graph_twice_is_refused_and_never_restamps_it(api):
    """The replay is refused and the first completion instant survives.

    PRD 3.3: "Signing the graph advances it `DRAFT → GRAPHED` and is the point
    at which every rollup is computed." Adding to or signing a graph that is not
    `DRAFT` is `ERR_INVALID_INSPECTION_STATE`.

    Design: Corner/state_machines/graph_complete_twice_returns_409_on_the_second_call
    """
    _prop, inspector, signed = _signed_graph_with_one_conducive_cell(api)
    assert_instant_equals(signed["graph_completed_at"], CLOCK_START_RENDERED)

    set_clock(api, "2026-08-03T09:00:00Z")
    response = api.graph_complete(
        signed["id"], {}, make_field_inspector_headers(inspector["id"])
    )
    validate_error(response, ERR_INVALID_INSPECTION_STATE)

    unchanged = validate_success(api.get_inspection(signed["id"], OFFICER_HEADERS))
    assert_status(unchanged, INSPECTION_GRAPHED, "inspection")
    assert_instant_equals(unchanged["graph_completed_at"], CLOCK_START_RENDERED)
    assert_version(unchanged, 2, "inspection")
    assert_instant_equals(unchanged["updated_at"], signed["updated_at"])


def test_the_refused_replay_does_not_recompute_the_ledger(api):
    """A refused second signing leaves the structure's ledger exactly as it was.

    PRD 3.1: the four ledger values "are a **ledger**, recomputed from scratch
    whenever a graph is signed, a bond is issued, or a bond terminates."

    Design: Corner/state_machines/graph_complete_twice_returns_409_on_the_second_call
    """
    prop, inspector, signed = _signed_graph_with_one_conducive_cell(api)

    set_clock(api, "2026-08-03T09:00:00Z")
    validate_error(
        api.graph_complete(
            signed["id"], {}, make_field_inspector_headers(inspector["id"])
        ),
        ERR_INVALID_INSPECTION_STATE,
    )

    ledger = validate_success(api.get_property(prop["id"], OFFICER_HEADERS))
    assert ledger["total_conducive_condition_count"] == 1
    assert ledger["waived_conducive_condition_count"] == 0
    assert ledger["open_conducive_condition_count"] == 1


def _structure_with_a_proposed_liquid_plan(api):
    """An FL slab carrying a signed graph and one PROPOSED liquid-barrier plan."""
    prop, inspector = register_property_and_inspector(api)
    applicator = register_inspector(api, license_state="FL")
    graph = clean_initial_graph(api, prop["id"], inspector["id"])
    plan = propose_plan(api, prop["id"], graph["id"], applicator["id"])
    return prop, applicator, graph, plan


def test_the_second_proposal_is_created_proposed_with_its_own_sizing(api):
    """A bait proposal on a structure that already has a liquid proposal is accepted.

    PRD 3.5: "The station target, `target_station_count`, is the number of bait
    stations to install and is 0 for any method other than `BAIT_STATION`. For a
    bait plan it is the structure's `linear_footage` divided by a station spacing
    of 10 feet, raised to the next whole number if not already whole".

    Design: Corner/state_machines/proposing_a_second_plan_abandons_the_still_proposed_first_plan
    """
    prop, applicator, graph, _plan_a = _structure_with_a_proposed_liquid_plan(api)

    response = api.create_treatment_plan(
        bait_plan_payload(prop["id"], graph["id"], applicator["id"]), MANAGER_HEADERS
    )
    plan_b = validate_success(response, 201)
    assert_status(plan_b, PLAN_PROPOSED, "treatment_plan")
    assert plan_b["target_station_count"] == expected_target_station_count(
        METHOD_BAIT_STATION, prop["linear_footage"], False
    )
    assert plan_b["target_station_count"] == 18
    assert_money(plan_b["target_gallons"], 0.00)
    assert plan_b["inspection_id"] == graph["id"]


def test_the_new_proposal_abandons_the_still_proposed_sibling(api):
    """The sweep retires the earlier proposal without touching its frozen numbers.

    PRD 3.5: "the act of proposing retires competition: every other plan on that
    same structure still sitting in `PROPOSED` is moved to `ABANDONED`, each such
    row taking a `version` increment of its own."

    Design: Corner/state_machines/proposing_a_second_plan_abandons_the_still_proposed_first_plan
    """
    prop, applicator, graph, plan_a = _structure_with_a_proposed_liquid_plan(api)
    assert_status(plan_a, PLAN_PROPOSED, "treatment_plan")

    propose_bait_plan(api, prop["id"], graph["id"], applicator["id"])

    retired = validate_success(api.get_treatment_plan(plan_a["id"], MANAGER_HEADERS))
    assert_status(retired, PLAN_ABANDONED, "treatment_plan")
    assert_version(retired, 2, "treatment_plan")
    assert_money(
        retired["target_gallons"],
        expected_target_gallons(
            prop["construction_type"],
            retired["method"],
            prop["square_footage"],
            prop["linear_footage"],
        ),
    )
    assert_money(retired["target_gallons"], 190.00)
    assert_money(
        retired["quoted_price_usd"],
        expected_quoted_price(
            prop["square_footage"], retired["method"], prop["construction_type"], False
        ),
    )
    assert_money(retired["quoted_price_usd"], 1080.00)


def test_only_the_surviving_proposal_can_still_be_approved(api):
    """The abandoned plan is terminal while its sibling approves normally.

    PRD 3.5: "Plans already `APPROVED`, `COMPLETED` or `ABANDONED` are untouched
    by this sweep." "Approval, also a `BranchManager` action, advances the plan
    `PROPOSED → APPROVED`. ... Approving a plan that is not `PROPOSED` is
    `ERR_INVALID_PLAN_STATE`."

    Design: Corner/state_machines/proposing_a_second_plan_abandons_the_still_proposed_first_plan
    """
    prop, applicator, graph, plan_a = _structure_with_a_proposed_liquid_plan(api)
    plan_b = propose_bait_plan(api, prop["id"], graph["id"], applicator["id"])

    validate_error(
        api.approve_treatment_plan(plan_a["id"], {}, MANAGER_HEADERS),
        ERR_INVALID_PLAN_STATE,
    )

    approved = validate_success(api.approve_treatment_plan(
        plan_b["id"], {}, MANAGER_HEADERS
    ))
    assert_status(approved, PLAN_APPROVED, "treatment_plan")
    assert_version(approved, 2, "treatment_plan")


def test_completing_a_bait_plan_stamps_the_completion_instant(api):
    """A bait plan closes out once a cartridge has been loaded.

    PRD 3.6: "A `BAIT_STATION` plan may only be completed once at least one
    application record exists against it, since the cartridges have to have been
    loaded." "Completion stamps `completed_at` with the clock instant".

    Design: Corner/state_machines/completing_a_bait_station_plan_installs_the_station_rows
    """
    _prop, _inspector, plan, _stations = _bait_plan_with_stations(api)

    assert_status(plan, PLAN_COMPLETED, "treatment_plan")
    assert_instant_equals(plan["completed_at"], CLOCK_START_RENDERED)


def test_completion_installs_exactly_the_targeted_number_of_stations(api):
    """The listing returns one row per targeted station, ordered by index.

    PRD 3.6: "exactly `target_station_count` station rows are created, numbered
    by `station_index` from 1 upward ... These cascade-created stations are
    discoverable only through the station listing beneath their plan."

    Design: Corner/state_machines/completing_a_bait_station_plan_installs_the_station_rows
    """
    _prop, _inspector, plan, _stations = _bait_plan_with_stations(api)

    rows, _meta = assert_page(
        api.list_bait_stations(plan["id"], OFFICER_HEADERS, limit=20),
        18,
        expected_rows=18,
        expected_has_more=False,
    )
    assert_station_index_ascending(rows)
    assert rows[0]["station_index"] == 1
    assert rows[0]["grid_ref"] == expected_station_grid_ref(1)
    assert rows[0]["grid_ref"] == "A1"
    assert rows[10]["station_index"] == 11
    assert rows[10]["grid_ref"] == "B1"
    assert rows[17]["station_index"] == 18
    assert rows[17]["grid_ref"] == "B8"


def test_every_installed_station_starts_quiet_and_due_in_ninety_days(api):
    """Each fresh station is INSTALLED with zeroed counters and a 90-day horizon.

    PRD 3.6: "each in status `INSTALLED`, each with `last_serviced_at` set to the
    plan's `completed_at` and `next_due_at` set to 90 days after that instant."

    Design: Corner/state_machines/completing_a_bait_station_plan_installs_the_station_rows
    """
    _prop, _inspector, plan, stations = _bait_plan_with_stations(api)
    expected_due = instant_plus_days(
        plan["completed_at"], STATION_INTERVAL_DAYS[STATION_INSTALLED]
    )

    assert len(stations) == 18
    for station in stations:
        assert_entity_shape(station, "bait_station")
        assert_status(station, STATION_INSTALLED, "bait_station")
        assert station["treatment_plan_id"] == plan["id"]
        assert station["consecutive_activity_count"] == 0
        assert station["service_count"] == 0
        assert station["matrix_replacement_count"] == 0
        assert_version(station, 1, "bait_station")
        assert_instant_equals(station["last_serviced_at"], plan["completed_at"])
        assert_instant_equals(station["next_due_at"], expected_due)


def test_a_completed_liquid_plan_installs_no_hardware(api):
    """The installation cascade is conditional on the plan's method.

    PRD 3.6: "Completion stamps `completed_at` with the clock instant, and for a
    `BAIT_STATION` plan it also installs the hardware". PRD 3.5: the station
    target "is 0 for any method other than `BAIT_STATION`".

    Design: Corner/state_machines/completing_a_bait_station_plan_installs_the_station_rows
    """
    prop, inspector = register_property_and_inspector(api)
    graph = clean_initial_graph(api, prop["id"], inspector["id"])

    plan = completed_liquid_plan(api, prop["id"], graph["id"], inspector["id"])
    assert_status(plan, PLAN_COMPLETED, "treatment_plan")
    assert plan["target_station_count"] == 0
    assert_page(
        api.list_bait_stations(plan["id"], OFFICER_HEADERS), 0, expected_rows=0
    )


def test_a_light_visit_is_graded_against_the_interval_before_the_visit(api):
    """The visit row is immutable and graded against the ACTIVE_HIT interval.

    PRD 3.9: "`days_since_last_service` is the number of whole UTC days from the
    station's `last_serviced_at` **as it stood before this visit** to
    `serviced_at`, discarding any partial day. `interval_compliance` grades that
    gap against the interval belonging to the station's status **before** this
    visit, not after it: a gap no greater than the interval is `ON_TIME`".

    Design: Corner/state_machines/light_service_leaves_status_and_run_length_unchanged
    """
    inspector, _plan, station_id = _active_hit_station(api)

    set_clock(api, "2026-09-15T00:00:00Z")
    response = api.create_station_service(
        station_id,
        station_service_payload(ACTIVITY_LIGHT, matrix_replaced=True),
        make_field_inspector_headers(inspector["id"]),
    )
    visit = validate_success(response, 201)

    assert_entity_shape(visit, "station_service")
    assert visit["bait_station_id"] == station_id
    assert visit["activity_level"] == ACTIVITY_LIGHT
    assert visit["matrix_replaced"] is True
    assert_instant_equals(visit["serviced_at"], "2026-09-15T00:00:00.000Z")
    assert visit["days_since_last_service"] == 14
    assert visit["interval_compliance"] == COMPLIANCE_ON_TIME
    assert "version" not in visit
    assert "updated_at" not in visit


def test_a_light_visit_leaves_the_status_and_the_run_alone(api):
    """LIGHT activity neither advances nor resets the consecutive-activity run.

    PRD 3.9: "A `LIGHT` visit is recorded but changes nothing about the station's
    condition — `consecutive_activity_count` is left exactly as it was and the
    status is left exactly as it was."

    Design: Corner/state_machines/light_service_leaves_status_and_run_length_unchanged
    """
    inspector, _plan, station_id = _active_hit_station(api)

    set_clock(api, "2026-09-15T00:00:00Z")
    service_station(
        api, station_id, inspector["id"], ACTIVITY_LIGHT, matrix_replaced=True
    )

    station = validate_success(api.get_bait_station(station_id, OFFICER_HEADERS))
    assert_status(station, STATION_ACTIVE_HIT, "bait_station")
    assert station["consecutive_activity_count"] == 1
    assert station["service_count"] == 2
    assert station["matrix_replacement_count"] == 1


def test_a_light_visit_still_moves_the_thirty_day_horizon(api):
    """The next due instant is recomputed on the unchanged ACTIVE_HIT interval.

    PRD 3.9: "Whatever the outcome, `next_due_at` is recomputed as `serviced_at`
    plus the interval of the station's **new** status, `service_count` rises by
    one, and `matrix_replacement_count` rises by one as well when
    `matrix_replaced` was true."

    Design: Corner/state_machines/light_service_leaves_status_and_run_length_unchanged
    """
    inspector, _plan, station_id = _active_hit_station(api)

    set_clock(api, "2026-09-15T00:00:00Z")
    service_station(
        api, station_id, inspector["id"], ACTIVITY_LIGHT, matrix_replaced=True
    )

    station = validate_success(api.get_bait_station(station_id, OFFICER_HEADERS))
    assert_instant_equals(station["last_serviced_at"], "2026-09-15T00:00:00.000Z")
    assert_instant_equals(
        station["next_due_at"],
        instant_plus_days(
            "2026-09-15T00:00:00Z", STATION_INTERVAL_DAYS[STATION_ACTIVE_HIT]
        ),
    )
    assert_instant_equals(station["next_due_at"], "2026-10-15T00:00:00.000Z")


def test_a_light_visit_never_reaches_the_parent_plan(api):
    """No escalation happened, so the plan's escalation counters stay put.

    PRD 3.9: "The second hop fires only when a station newly enters `ESCALATED`
    from some other status: the installing plan's `escalated_station_count` rises
    by one".

    Design: Corner/state_machines/light_service_leaves_status_and_run_length_unchanged
    """
    inspector, plan, station_id = _active_hit_station(api)

    set_clock(api, "2026-09-15T00:00:00Z")
    service_station(
        api, station_id, inspector["id"], ACTIVITY_LIGHT, matrix_replaced=True
    )

    parent = validate_success(api.get_treatment_plan(plan["id"], MANAGER_HEADERS))
    assert parent["escalated_station_count"] == 0
    assert parent["retreat_required"] is False


def test_a_clean_visit_returns_the_station_to_installed(api):
    """NONE activity resets the run and drops the station back to INSTALLED.

    PRD 3.9: "A `NONE` visit resets `consecutive_activity_count` to 0 and returns
    the station to `INSTALLED`, which is the cyclic part of the design: a station
    that goes quiet drops back to the relaxed 90-day rhythm no matter how
    agitated it had become."

    Design: Corner/state_machines/clean_service_resets_the_run_and_restores_the_ninety_day_interval
    """
    inspector, _plan, station_id = _active_hit_station(api)

    set_clock(api, "2026-09-20T00:00:00Z")
    service_station(api, station_id, inspector["id"], ACTIVITY_NONE)

    station = validate_success(api.get_bait_station(station_id, OFFICER_HEADERS))
    assert_status(station, STATION_INSTALLED, "bait_station")
    assert station["consecutive_activity_count"] == 0
    assert_version(station, 3, "bait_station")


def test_a_clean_visit_restores_the_ninety_day_interval(api):
    """The relaxed rhythm is applied from the instant of the quiet visit.

    PRD 3.9: "`next_due_at` always states the current expectation, computed as
    `last_serviced_at` plus the interval belonging to the station's present
    status." An `INSTALLED` station "is due every 90 days".

    Design: Corner/state_machines/clean_service_resets_the_run_and_restores_the_ninety_day_interval
    """
    inspector, _plan, station_id = _active_hit_station(api)

    set_clock(api, "2026-09-20T00:00:00Z")
    service_station(api, station_id, inspector["id"], ACTIVITY_NONE)

    station = validate_success(api.get_bait_station(station_id, OFFICER_HEADERS))
    assert_instant_equals(station["last_serviced_at"], "2026-09-20T00:00:00.000Z")
    assert_instant_equals(
        station["next_due_at"],
        instant_plus_days(
            "2026-09-20T00:00:00Z", STATION_INTERVAL_DAYS[STATION_INSTALLED]
        ),
    )
    assert_instant_equals(station["next_due_at"], "2026-12-19T00:00:00.000Z")


def test_the_clean_visit_row_is_graded_against_the_active_hit_limit(api):
    """A nineteen-day gap is on time against the thirty-day ACTIVE_HIT interval.

    PRD 3.9: "a gap no greater than the interval is `ON_TIME`; a gap greater than
    the interval but no greater than the interval plus a 7-day grace is `LATE`;
    anything beyond that is `MISSED`."

    Design: Corner/state_machines/clean_service_resets_the_run_and_restores_the_ninety_day_interval
    """
    inspector, _plan, station_id = _active_hit_station(api)

    set_clock(api, "2026-09-20T00:00:00Z")
    visit = service_station(api, station_id, inspector["id"], ACTIVITY_NONE)

    assert visit["days_since_last_service"] == 19
    assert visit["interval_compliance"] == COMPLIANCE_ON_TIME
    assert visit["activity_level"] == ACTIVITY_NONE
    assert visit["matrix_replaced"] is False


def test_both_visits_are_listed_back_as_immutable_rows(api):
    """The visit history keeps both rows and neither carries a version.

    PRD 2.4: "Three record types are immutable by design and therefore carry
    neither `updated_at` nor `version`: a graph cell notation, a pesticide
    application record, and a bait-station service visit."

    Design: Corner/state_machines/clean_service_resets_the_run_and_restores_the_ninety_day_interval
    """
    inspector, _plan, station_id = _active_hit_station(api)

    set_clock(api, "2026-09-20T00:00:00Z")
    service_station(api, station_id, inspector["id"], ACTIVITY_NONE)

    rows, _meta = assert_page(
        api.list_station_services(station_id, OFFICER_HEADERS), 2, expected_rows=2
    )
    for row in rows:
        assert_entity_shape(row, "station_service")
        assert "version" not in row
        assert "updated_at" not in row

    station = validate_success(api.get_bait_station(station_id, OFFICER_HEADERS))
    assert station["service_count"] == 2
    assert station["matrix_replacement_count"] == 0


def _bond_with_one_fresh_claim(api):
    """An ACTIVE bond issued 2026-09-01 and the response to a first 4000.00 claim."""
    chain = bonded_property(api, issue_instant="2026-09-01T00:00:00Z")
    bond = chain["bond"]
    response = api.create_damage_claim(
        damage_claim_payload(bond["id"], bond["version"], 4000.00),
        make_property_owner_headers(chain["property"]["id"]),
    )
    return chain, response


def test_a_filed_claim_is_created_submitted_and_stamped_from_the_clock(api):
    """The filing lands in SUBMITTED with the clock's date as its report date.

    PRD 3.10: "The clock's UTC date, which stamps `reported_at`, must also fall
    inside the bond's current coverage window ... The claim is created in status
    `SUBMITTED`".

    Design: Corner/state_machines/damage_claim_starts_in_submitted_with_no_reserve_movement
    """
    _chain, response = _bond_with_one_fresh_claim(api)

    claim = validate_success(response, 201)
    assert_entity_shape(claim, "damage_claim")
    assert_status(claim, CLAIM_SUBMITTED, "damage_claim")
    assert_version(claim, 1, "damage_claim")
    assert_instant_equals(claim["reported_at"], "2026-09-01T00:00:00.000Z")
    assert_money(claim["claimed_damage_usd"], 4000.00)


def test_a_filed_claim_carries_no_adjudication_facts_yet(api):
    """Every field that only adjudication can fill is still null.

    PRD 3.10: "The claim is created in status `SUBMITTED` with
    `verifying_inspection_id` null, every money field at 0.00, `exclusion_basis`,
    `denial_reason_code` and `adjudicated_by_user_id` all null."

    Design: Corner/state_machines/damage_claim_starts_in_submitted_with_no_reserve_movement
    """
    _chain, response = _bond_with_one_fresh_claim(api)

    claim = validate_success(response, 201)
    assert claim["verifying_inspection_id"] is None
    assert claim["exclusion_basis"] is None
    assert claim["denial_reason_code"] is None
    assert claim["adjudicated_by_user_id"] is None


def test_a_filed_claim_prices_nothing_at_all(api):
    """No money is computed until a verifying graph is attached.

    PRD 3.10: "The claim is created in status `SUBMITTED` with
    `verifying_inspection_id` null, every money field at 0.00".

    Design: Corner/state_machines/damage_claim_starts_in_submitted_with_no_reserve_movement
    """
    _chain, response = _bond_with_one_fresh_claim(api)

    claim = validate_success(response, 201)
    assert_money(claim["excluded_pre_existing_usd"], 0.00)
    assert_money(claim["eligible_damage_usd"], 0.00)
    assert_money(claim["deductible_usd"], 0.00)
    assert_money(claim["projected_payout_usd"], 0.00)
    assert_money(claim["approved_payout_usd"], 0.00)


def test_filing_moves_the_bond_version_but_not_its_reserve(api):
    """The bond takes a version increment while every money field stands still.

    PRD 3.10: "Filing also raises the bond's `version` by one, which is what makes
    a second blind filing against the same bond fail its version check." The
    reserve only moves when a verifying graph is attached, which is when
    "`reserved_claim_amount_usd` rises by `projected_payout_usd`".

    Design: Corner/state_machines/damage_claim_starts_in_submitted_with_no_reserve_movement
    """
    chain, response = _bond_with_one_fresh_claim(api)
    validate_success(response, 201)
    _base, cap, _annual = expected_bond_money(
        chain["plan"]["quoted_price_usd"], TIER_REPAIR_AND_RETREAT
    )

    bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_version(bond, 2, "bond")
    assert_bond_money(
        bond,
        repair_liability_cap_usd=cap,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=cap,
    )
    assert_money(bond["remaining_repair_cap_usd"], 11664.00)
    assert_repair_liability_conserved(bond)


def test_the_second_review_past_the_reinstatement_deadline_terminates_the_bond(api):
    """A lapsed bond left unbought for ninety days is reviewed into TERMINATED.

    PRD 3.8: "Review of a bond that is already `LAPSED` and whose clock date has
    passed `lapse_date` plus 90 days moves it `LAPSED → TERMINATED`, which is
    terminal."

    Design: Corner/state_machines/terminated_bond_rejects_every_further_transition
    """
    chain = bonded_property(api, issue_instant="2026-09-01T00:00:00Z")
    lapsed = lapse_bond(api, chain["bond"])
    assert_status(lapsed, BOND_LAPSED, "bond")
    assert lapsed["lapse_date"] == "2027-10-01"

    set_clock(api, "2027-12-31T00:00:00Z")
    terminated = review_bond_term(api, chain["bond"]["id"])
    assert_status(terminated, BOND_TERMINATED, "bond")
    assert_version(terminated, 3, "bond")


def test_a_terminated_bond_cannot_be_reviewed_again(api):
    """No transition is declared out of the terminal bond state.

    PRD 3.8: "A review that finds neither deadline passed changes nothing and is
    refused with `ERR_INVALID_BOND_STATE`."

    Design: Corner/state_machines/terminated_bond_rejects_every_further_transition
    """
    chain, terminated = _terminated_bond(api)
    assert_status(terminated, BOND_TERMINATED, "bond")

    validate_error(
        api.term_review(chain["bond"]["id"], {}, OFFICER_HEADERS),
        ERR_INVALID_BOND_STATE,
    )

    unchanged = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_status(unchanged, BOND_TERMINATED, "bond")
    assert_version(unchanged, 3, "bond")


def test_a_terminated_bond_refuses_a_new_renewal_invoice(api):
    """The state check outranks the renewal-window check on a terminated bond.

    PRD 3.8: "The bond must also be `ACTIVE`; a lapsed bond that is additionally
    outside its window reports `ERR_INVALID_BOND_STATE`, because the state check
    outranks the window check."

    Design: Corner/state_machines/terminated_bond_rejects_every_further_transition
    """
    chain, _terminated = _terminated_bond(api)

    validate_error(
        api.create_renewal(chain["bond"]["id"], {}, MANAGER_HEADERS),
        ERR_INVALID_BOND_STATE,
    )


def test_a_terminated_bond_refuses_a_new_claim_on_a_freshly_read_version(api):
    """A terminated bond accepts no claim even when the version quoted is current.

    PRD 3.10: "The bond must be `ACTIVE`: `LAPSED` and `TERMINATED` bonds accept
    no new claims, and the refusal is `ERR_BOND_NOT_ACTIVE`."

    Design: Corner/state_machines/terminated_bond_rejects_every_further_transition
    """
    chain, _terminated = _terminated_bond(api)
    current = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))

    response = api.create_damage_claim(
        damage_claim_payload(current["id"], current["version"], 5000.00),
        make_property_owner_headers(chain["property"]["id"]),
    )
    validate_error(response, ERR_BOND_NOT_ACTIVE)


def test_termination_freezes_the_money_rather_than_zeroing_it(api):
    """The terminated bond keeps its cap, its payouts and its lapse date on record.

    PRD 3.8: "The bond's money fields — `repair_liability_cap_usd`,
    `claims_paid_to_date_usd`, `reserved_claim_amount_usd` and
    `remaining_repair_cap_usd` — are deliberately left frozen at their
    pre-termination values as a permanent record of what the bond did."

    Design: Corner/state_machines/terminated_bond_rejects_every_further_transition
    """
    chain, terminated = _terminated_bond(api)
    _base, cap, _annual = expected_bond_money(
        chain["plan"]["quoted_price_usd"], TIER_REPAIR_AND_RETREAT
    )

    assert terminated["lapse_date"] == "2027-10-01"
    assert_bond_money(
        terminated,
        repair_liability_cap_usd=cap,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=cap,
    )
    assert_money(terminated["repair_liability_cap_usd"], 11664.00)
    assert_money(terminated["remaining_repair_cap_usd"], 11664.00)
    assert_repair_liability_conserved(terminated)
