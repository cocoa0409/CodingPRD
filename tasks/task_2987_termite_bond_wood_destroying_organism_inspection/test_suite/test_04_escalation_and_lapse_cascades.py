"""Three-level cascade chains: bait-station escalation and bond lapse.

Each hop of a chain is caused by the hop above it, never by the original
request, so every test below asserts one hop's outcome independently -- both
that the hop fires when its cause fired, and that it stays silent when its
cause did not.
"""

from test_helpers import (
    ACTIVITY_HEAVY,
    ACTIVITY_MODERATE,
    ADJUDICATOR_HEADERS,
    BOND_ACTIVE,
    BOND_LAPSED,
    CATEGORY_TERMITE_APPLICATOR,
    CATEGORY_WDO_INSPECTOR,
    CLAIM_DENIED,
    CLAIM_SUBMITTED,
    CLAIM_UNDER_ADJUDICATION,
    COMPLIANCE_ON_TIME,
    CONSTRUCTION_CRAWLSPACE,
    CONSTRUCTION_SLAB,
    DENIAL_BOND_LAPSED,
    EXCLUSION_FINDING_LEVEL,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    PURPOSE_INITIAL,
    RENEWAL_PENDING,
    RENEWAL_VOID,
    STATION_ACTIVE_HIT,
    STATION_ESCALATED,
    STATION_INSTALLED,
    TIER_REPAIR_AND_RETREAT,
    approve_plan,
    assert_bond_money,
    assert_claim_money,
    assert_conducive_counts_conserved,
    assert_instant_equals,
    assert_money,
    assert_repair_liability_conserved,
    assert_status,
    attach_verification,
    clean_initial_graph,
    complete_plan,
    completed_liquid_plan,
    damage_finding_payload,
    file_claim,
    issue_bond,
    list_stations,
    make_field_inspector_headers,
    next_license_number,
    open_renewal,
    propose_bait_plan,
    record_application,
    register_inspector,
    register_property,
    renewal_graph,
    service_station,
    set_clock,
    station_service_payload,
    validate_success,
)

# ---------------------------------------------------------------------------
# Chain A -- a bait plan, its 18 stations and the bond written over it
# ---------------------------------------------------------------------------


def _bait_chain(api):
    """A GA crawlspace with a COMPLETED bait plan and an ACTIVE bond over it.

    The plan is completed at exactly 2026-08-10T00:00:00Z so every installed
    station starts with that ``last_serviced_at``, and the bond is issued the
    following day so it is still ACTIVE when an escalation reaches it.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    prop = register_property(
        api,
        address_line1="77 Sweetgum Lane",
        state_code="GA",
        construction_type=CONSTRUCTION_CRAWLSPACE,
        square_footage=1800,
        linear_footage=175,
        year_built=1988,
        crawl_clearance_inches=18,
        has_attached_structures=False,
    )
    inspector = register_inspector(
        api,
        full_name="Ivy Marsh",
        license_number=next_license_number("GA"),
        license_state="GA",
        license_categories=[CATEGORY_WDO_INSPECTOR, CATEGORY_TERMITE_APPLICATOR],
        license_expires_on="2029-06-30",
    )
    graph = clean_initial_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_INITIAL,
        scheduled_start_at="2026-08-01T13:00:00Z",
        scheduled_end_at="2026-08-01T15:00:00Z",
    )
    plan = propose_bait_plan(api, prop["id"], graph["id"], inspector["id"])
    plan = approve_plan(api, plan["id"])
    record_application(
        api,
        plan["id"],
        inspector["id"],
        plan["version"],
        product_epa_number="9384-12",
        gallons_applied=0.50,
        concentration_pct=0.05,
    )
    set_clock(api, "2026-08-10T00:00:00Z")
    plan = complete_plan(api, plan["id"], inspector["id"])
    set_clock(api, "2026-08-11T00:00:00Z")
    bond = issue_bond(
        api,
        prop["id"],
        plan["id"],
        coverage_tier=TIER_REPAIR_AND_RETREAT,
        conducive_waiver_codes=[],
    )
    stations = list_stations(api, plan["id"], limit=100)
    return {
        "property": prop,
        "inspector": inspector,
        "plan": plan,
        "bond": bond,
        "stations": stations,
    }


def _two_activity_visits(api, chain):
    """Service station 1 twice with MODERATE activity, leaving the clock ready.

    Both visits land on the station's exact due date, so the run length reaches
    2 -- one short of the escalation threshold -- and the clock is left parked
    on the third due date.
    """
    station = chain["stations"][0]
    inspector_id = chain["inspector"]["id"]
    set_clock(api, "2026-11-08T00:00:00Z")
    service_station(
        api, station["id"], inspector_id, ACTIVITY_MODERATE, matrix_replaced=True
    )
    set_clock(api, "2026-12-08T00:00:00Z")
    service_station(
        api, station["id"], inspector_id, ACTIVITY_MODERATE, matrix_replaced=False
    )
    set_clock(api, "2027-01-07T00:00:00Z")
    return station


def _third_activity_visit(api, chain, station):
    """Record the HEAVY visit that takes the run length to three."""
    return validate_success(
        api.create_station_service(
            station["id"],
            station_service_payload(ACTIVITY_HEAVY, matrix_replaced=True),
            make_field_inspector_headers(chain["inspector"]["id"]),
        ),
        201,
    )


class TestStationEscalationCascade:
    """POST /bait-stations/{id}/services drives a station, its plan and the bond."""

    def test_two_activity_visits_leave_the_plan_and_bond_untouched(self, api):
        """Hops 2 and 3 stay silent while the run length is still short of three.

        PRD 3.9: "A MODERATE or HEAVY visit raises consecutive_activity_count by
        one; if the resulting run length is 3 or more the station becomes
        ESCALATED, and otherwise it becomes ACTIVE_HIT", and "The second hop
        fires only when a station newly enters ESCALATED from some other
        status".

        Design: Difficulty/transitive_cascade/station_escalation_propagates_to_plan_then_to_bond_coverage_watch
        """
        chain = _bait_chain(api)
        station = _two_activity_visits(api, chain)

        current = validate_success(api.get_bait_station(station["id"], OFFICER_HEADERS))
        assert_status(current, STATION_ACTIVE_HIT, "bait station")
        assert current["consecutive_activity_count"] == 2
        assert current["service_count"] == 2
        assert current["matrix_replacement_count"] == 1

        plan = validate_success(
            api.get_treatment_plan(chain["plan"]["id"], MANAGER_HEADERS)
        )
        assert plan["escalated_station_count"] == 0
        assert plan["retreat_required"] is False

        bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        assert bond["coverage_watch"] is False
        assert bond["retreat_required"] is False

    def test_third_activity_visit_escalates_the_station_and_grades_the_gap(self, api):
        """Hop 1: the run reaches three, the station escalates and the visit grades.

        PRD 3.9: "if the resulting run length is 3 or more the station becomes
        ESCALATED", and "next_due_at is recomputed as serviced_at plus the
        interval of the station's new status"; an ESCALATED station "every 14
        days".

        Design: Difficulty/transitive_cascade/station_escalation_propagates_to_plan_then_to_bond_coverage_watch
        """
        chain = _bait_chain(api)
        station = _two_activity_visits(api, chain)

        visit = _third_activity_visit(api, chain, station)
        assert visit["days_since_last_service"] == 30
        assert visit["interval_compliance"] == COMPLIANCE_ON_TIME
        assert_instant_equals(visit["serviced_at"], "2027-01-07T00:00:00Z")

        escalated = validate_success(
            api.get_bait_station(station["id"], OFFICER_HEADERS)
        )
        assert_status(escalated, STATION_ESCALATED, "bait station")
        assert escalated["consecutive_activity_count"] == 3
        assert escalated["service_count"] == 3
        assert escalated["matrix_replacement_count"] == 2
        assert_instant_equals(escalated["next_due_at"], "2027-01-21T00:00:00Z")

    def test_escalation_raises_the_plan_count_and_flips_retreat_required(self, api):
        """Hop 2 is caused by hop 1 and is keyed on the plan's frozen station count.

        PRD 3.9: "the installing plan's escalated_station_count rises by one,
        and the plan's retreat_required is then set true when
        escalated_station_count has reached the plan's escalation threshold,
        which is 5 percent of the plan's target_station_count raised to the next
        whole number".

        Design: Difficulty/transitive_cascade/station_escalation_propagates_to_plan_then_to_bond_coverage_watch
        """
        chain = _bait_chain(api)
        station = _two_activity_visits(api, chain)
        _third_activity_visit(api, chain, station)

        plan = validate_success(
            api.get_treatment_plan(chain["plan"]["id"], MANAGER_HEADERS)
        )
        assert plan["escalated_station_count"] == 1
        assert plan["retreat_required"] is True
        # The frozen sizing is the threshold's denominator: ceil(18 * 0.05) == 1.
        assert plan["target_station_count"] == 18
        assert_money(plan["quoted_price_usd"], 1293.75)

    def test_escalation_reaches_the_bond_and_raises_three_versions(self, api):
        """Hop 3 is caused by hop 2 alone, and all three rows take a version step.

        PRD 3.9: "the bond written against that same plan, if it is ACTIVE, has
        both coverage_watch and retreat_required set true, marking it for
        mandatory review at its next renewal. Each of the three rows touched
        takes its own version increment."

        Design: Difficulty/transitive_cascade/station_escalation_propagates_to_plan_then_to_bond_coverage_watch
        """
        chain = _bait_chain(api)
        station = _two_activity_visits(api, chain)

        before_station = validate_success(
            api.get_bait_station(station["id"], OFFICER_HEADERS)
        )
        before_plan = validate_success(
            api.get_treatment_plan(chain["plan"]["id"], MANAGER_HEADERS)
        )
        before_bond = validate_success(
            api.get_bond(chain["bond"]["id"], MANAGER_HEADERS)
        )
        assert_status(before_bond, BOND_ACTIVE, "bond")

        _third_activity_visit(api, chain, station)

        after_bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        assert after_bond["coverage_watch"] is True
        assert after_bond["retreat_required"] is True
        assert after_bond["version"] == before_bond["version"] + 1

        after_plan = validate_success(
            api.get_treatment_plan(chain["plan"]["id"], MANAGER_HEADERS)
        )
        assert after_plan["version"] == before_plan["version"] + 1

        after_station = validate_success(
            api.get_bait_station(station["id"], OFFICER_HEADERS)
        )
        assert after_station["version"] == before_station["version"] + 1

    def test_the_other_seventeen_stations_are_untouched_by_the_escalation(self, api):
        """The chain runs through one station only; its siblings never moved.

        PRD 2.11: "Where they do, the changes form a chain: each hop is caused
        by the hop before it, not by the original request, and a hop that does
        not fire cannot cause the hop beneath it."

        Design: Difficulty/transitive_cascade/station_escalation_propagates_to_plan_then_to_bond_coverage_watch
        """
        chain = _bait_chain(api)
        station = _two_activity_visits(api, chain)
        _third_activity_visit(api, chain, station)

        stations = list_stations(api, chain["plan"]["id"], limit=100)
        assert len(stations) == 18
        assert stations[0]["station_index"] == 1
        for sibling in stations[1:]:
            assert_status(sibling, STATION_INSTALLED, "sibling bait station")
            assert sibling["service_count"] == 0
            assert sibling["consecutive_activity_count"] == 0
            assert_instant_equals(sibling["next_due_at"], "2026-11-08T00:00:00Z")


# ---------------------------------------------------------------------------
# Chain B -- a bonded structure whose grace deadline is allowed to pass
# ---------------------------------------------------------------------------


def _bonded_structure(api):
    """An FL slab bonded REPAIR_AND_RETREAT on 2026-09-01.

    The graph signer and the plan's applicator are two different licensees, so
    the signer may later certify damage claimed against the treatment.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    prop = register_property(
        api,
        address_line1="411 Cypress Row",
        state_code="FL",
        construction_type=CONSTRUCTION_SLAB,
        square_footage=2000,
        linear_footage=180,
        year_built=1995,
        has_attached_structures=False,
    )
    signer = register_inspector(
        api,
        full_name="Rosa Vance",
        license_number=next_license_number("FL"),
        license_state="FL",
        license_categories=[CATEGORY_WDO_INSPECTOR],
        license_expires_on="2029-06-30",
    )
    applicator = register_inspector(
        api,
        full_name="Dale Ortiz",
        license_number=next_license_number("FL"),
        license_state="FL",
        license_categories=[CATEGORY_TERMITE_APPLICATOR],
        license_expires_on="2029-06-30",
    )
    graph = clean_initial_graph(
        api,
        prop["id"],
        signer["id"],
        purpose=PURPOSE_INITIAL,
        scheduled_start_at="2026-08-01T13:00:00Z",
        scheduled_end_at="2026-08-01T15:00:00Z",
    )
    plan = completed_liquid_plan(api, prop["id"], graph["id"], applicator["id"])
    set_clock(api, "2026-09-01T00:00:00Z")
    bond = issue_bond(
        api,
        prop["id"],
        plan["id"],
        coverage_tier=TIER_REPAIR_AND_RETREAT,
        conducive_waiver_codes=[],
    )
    return {
        "property": prop,
        "signer": signer,
        "applicator": applicator,
        "inspection": graph,
        "plan": plan,
        "bond": bond,
    }


def _pending_renewal(api, chain):
    """Open a PENDING invoice on 2027-08-20, inside the window that opened 2027-07-03."""
    set_clock(api, "2027-08-20T09:00:00Z")
    return open_renewal(api, chain["bond"]["id"])


def _verified_claim(api, chain):
    """File a 6000.00 claim on 2027-08-25 and reserve against a superseding graph.

    The verifying graph supersedes the initial graph, so a cell-by-cell baseline
    exists and the FINDING_LEVEL exclusion basis governs.
    """
    set_clock(api, "2027-08-22T09:00:00Z")
    verifying = renewal_graph(
        api,
        chain["property"]["id"],
        chain["signer"]["id"],
        chain["inspection"]["id"],
        findings=[
            damage_finding_payload("A1", 3500.00, pre_existing=False, severity=3),
            damage_finding_payload("B2", 1600.00, pre_existing=False, severity=2),
            damage_finding_payload("C3", 2400.00, pre_existing=True, severity=4),
        ],
        scheduled_start_at="2027-08-22T09:00:00Z",
        scheduled_end_at="2027-08-22T11:00:00Z",
    )
    set_clock(api, "2027-08-25T09:00:00Z")
    bond_now = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    claim = file_claim(api, bond_now, chain["property"]["id"], 6000.00)
    verified = attach_verification(
        api, claim["id"], verifying["id"], chain["signer"]["id"]
    )
    return verified


def _submitted_claim(api, chain):
    """File a 6000.00 claim on 2027-08-25 and leave it unverified in SUBMITTED."""
    set_clock(api, "2027-08-25T09:00:00Z")
    bond_now = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    return file_claim(api, bond_now, chain["property"]["id"], 6000.00)


def _run_term_review(api, chain):
    """Sweep the bond four days past its grace deadline of 2027-10-01."""
    set_clock(api, "2027-10-05T00:00:00Z")
    return validate_success(api.term_review(chain["bond"]["id"], {}, OFFICER_HEADERS))


class TestTermReviewLapseCascade:
    """POST /bonds/{id}/term-review fans out to a renewal and a claim, then back."""

    def test_before_the_sweep_nothing_in_the_chain_has_moved(self, api):
        """The chain's starting state: an ACTIVE bond holding a priced reserve.

        PRD 2.8: "repair_liability_cap_usd always equals claims_paid_to_date_usd
        plus reserved_claim_amount_usd plus remaining_repair_cap_usd", and PRD
        3.10: attaching a verifying graph "reserves the projected payout against
        the bond".

        Design: Difficulty/transitive_cascade/term_review_lapse_voids_renewal_denies_claim_and_releases_reserve
        """
        chain = _bonded_structure(api)
        renewal = _pending_renewal(api, chain)
        claim = _verified_claim(api, chain)

        bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        assert_status(bond, BOND_ACTIVE, "bond")
        assert_bond_money(
            bond,
            repair_liability_cap_usd=11664.00,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=4743.00,
            remaining_repair_cap_usd=6921.00,
        )
        assert_repair_liability_conserved(bond)

        assert_status(renewal, RENEWAL_PENDING, "bond renewal")
        assert_status(claim, CLAIM_UNDER_ADJUDICATION, "damage claim")
        assert_claim_money(
            claim,
            eligible_damage_usd=5100.00,
            excluded_pre_existing_usd=900.00,
            deductible_usd=357.00,
            projected_payout_usd=4743.00,
        )
        assert claim["exclusion_basis"] == EXCLUSION_FINDING_LEVEL

    def test_hop_one_lapses_the_bond_on_the_grace_deadline_not_the_review_date(
        self, api
    ):
        """The first hop dates the lapse from the term, not from when it was noticed.

        PRD 3.8: "a bond whose current_term_end plus the 30-day grace period has
        passed with no completed renewal becomes LAPSED, and its lapse_date is
        set to that grace deadline."

        Design: Difficulty/transitive_cascade/term_review_lapse_voids_renewal_denies_claim_and_releases_reserve
        """
        chain = _bonded_structure(api)
        _pending_renewal(api, chain)
        _verified_claim(api, chain)

        before = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        reviewed = _run_term_review(api, chain)

        assert_status(reviewed, BOND_LAPSED, "bond")
        assert reviewed["lapse_date"] == "2027-10-01"
        assert reviewed["current_term_end"] == "2027-09-01"
        assert reviewed["version"] == before["version"] + 1

    def test_hop_two_a_voids_the_pending_renewal_and_freezes_its_invoice(self, api):
        """A renewal cannot survive the lapse of the bond it was opened against.

        PRD 3.8: "every PENDING renewal on that bond becomes VOID", and PRD 3.5:
        the provisional invoice is repriced only when the renewal is completed.

        Design: Difficulty/transitive_cascade/term_review_lapse_voids_renewal_denies_claim_and_releases_reserve
        """
        chain = _bonded_structure(api)
        renewal = _pending_renewal(api, chain)
        _verified_claim(api, chain)
        _run_term_review(api, chain)

        voided = validate_success(
            api.get_renewal(renewal["id"], MANAGER_HEADERS)
        )
        assert_status(voided, RENEWAL_VOID, "bond renewal")
        assert_money(voided["invoice_total_usd"], 211.27)
        assert voided["version"] == renewal["version"] + 1

    def test_hop_two_b_denies_the_adjudicating_claim_with_the_lapse_reason(self, api):
        """The claim is denied by the lapse, so it pays nothing.

        PRD 3.8: "every claim on that bond still in SUBMITTED or
        UNDER_ADJUDICATION becomes DENIED with denial_reason_code BOND_LAPSED."

        Design: Difficulty/transitive_cascade/term_review_lapse_voids_renewal_denies_claim_and_releases_reserve
        """
        chain = _bonded_structure(api)
        _pending_renewal(api, chain)
        claim = _verified_claim(api, chain)
        _run_term_review(api, chain)

        denied = validate_success(
            api.get_damage_claim(claim["id"], ADJUDICATOR_HEADERS)
        )
        assert_status(denied, CLAIM_DENIED, "damage claim")
        assert denied["denial_reason_code"] == DENIAL_BOND_LAPSED
        assert_money(denied["approved_payout_usd"], 0.00)
        assert denied["version"] == claim["version"] + 1

    def test_hop_three_releases_exactly_the_denied_claim_s_reserve(self, api):
        """The release flows back up from the denial, not from the review call.

        PRD 3.8: "each claim denied out of UNDER_ADJUDICATION releases its
        reserved amount back to the bond, raising remaining_repair_cap_usd by
        the same figure."

        Design: Difficulty/transitive_cascade/term_review_lapse_voids_renewal_denies_claim_and_releases_reserve
        """
        chain = _bonded_structure(api)
        _pending_renewal(api, chain)
        _verified_claim(api, chain)
        _run_term_review(api, chain)

        bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        assert_bond_money(
            bond,
            repair_liability_cap_usd=11664.00,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=0.00,
            remaining_repair_cap_usd=11664.00,
        )
        assert_repair_liability_conserved(bond)

    def test_a_claim_that_never_reserved_is_denied_but_releases_nothing(self, api):
        """Hop 3 cannot fire for a claim whose hop 2b never held a reserve.

        PRD 3.8: only "each claim denied out of UNDER_ADJUDICATION releases its
        reserved amount back to the bond"; a SUBMITTED claim has no priced
        reserve to give back.

        Design: Difficulty/transitive_cascade/term_review_lapse_voids_renewal_denies_claim_and_releases_reserve
        """
        chain = _bonded_structure(api)
        claim = _submitted_claim(api, chain)
        assert_status(claim, CLAIM_SUBMITTED, "damage claim")

        before = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        assert_money(before["reserved_claim_amount_usd"], 0.00)
        assert_money(before["remaining_repair_cap_usd"], 11664.00)

        _run_term_review(api, chain)

        denied = validate_success(
            api.get_damage_claim(claim["id"], ADJUDICATOR_HEADERS)
        )
        assert_status(denied, CLAIM_DENIED, "damage claim")
        assert denied["denial_reason_code"] == DENIAL_BOND_LAPSED

        after = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
        assert_bond_money(
            after,
            reserved_claim_amount_usd=0.00,
            remaining_repair_cap_usd=11664.00,
            claims_paid_to_date_usd=0.00,
        )
        assert_repair_liability_conserved(after)

    def test_the_lapse_leaves_the_structure_s_conducive_ledger_alone(self, api):
        """No fourth hop fires: a LAPSED bond does not touch the structure.

        PRD 2.11: "a hop that does not fire cannot cause the hop beneath it",
        and PRD 3.2: the structure's conducive counters move only when a graph
        is signed.

        Design: Difficulty/transitive_cascade/term_review_lapse_voids_renewal_denies_claim_and_releases_reserve
        """
        chain = _bonded_structure(api)
        _pending_renewal(api, chain)
        _verified_claim(api, chain)

        before = validate_success(
            api.get_property(chain["property"]["id"], OFFICER_HEADERS)
        )
        _run_term_review(api, chain)
        after = validate_success(
            api.get_property(chain["property"]["id"], OFFICER_HEADERS)
        )

        assert after["version"] == before["version"]
        assert (
            after["open_conducive_condition_count"]
            == before["open_conducive_condition_count"]
        )
        assert_conducive_counts_conserved(after)
