"""Corner-case endpoint coverage (SCAFFOLD_CORNER_DESIGN.yaml, section ``endpoints``).

Each test translates exactly one design instance: the clock control endpoint's
monotonicity, a sub-resource list scoped by its path parent, a junction create
that must resolve both sides, a conditional action that only sometimes changes
status, a derived read that must reconcile with the audit ledger, and a list
whose declared filters must combine.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    INSPECTOR_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_workstation,
    assert_booth_rental_shape,
    assert_cents,
    assert_fine_breakdown,
    assert_finding_shape,
    assert_instants_equal,
    assert_ledger_entry_shape,
    assert_ledger_sum,
    assert_points,
    assert_sanitation_log_shape,
    assert_sorted_asc,
    booth_rental_payload,
    create_candidate,
    create_establishment,
    create_violation_code,
    file_sanitation_log,
    finding_payload,
    get_success_data,
    issue_citation,
    make_establishment_owner_headers,
    payment_payload,
    record_finding,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    refresh_workstation,
    setup_establishment_with_posted_practitioner,
    setup_finalized_inspection,
    setup_inspection_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_clock_set_must_advance_strictly_and_carries_no_entity_payload(api):
    """The logical clock is monotonic; re-sending its current value is refused.

    PRD 2.4: "the clock may only move forward, so a `to_iso8601` less than or
    equal to the current value is rejected with `ERR_CLOCK_MUST_ADVANCE` (HTTP
    422)". Per PRD section 4 this is the one write outside the `/cosmetology`
    prefix, and it returns no resource of its own.

    Design: Corner/endpoints/endpoint_clock_set_returns_null_data_and_must_advance_strictly
    """
    forward = api.set_clock("2026-08-05T00:00:00.000Z", BOARD_ADMIN_HEADERS)
    data = validate_success(forward)
    assert data in (None, {}), f"the clock endpoint returns no entity, got {data!r}"

    repeat = api.set_clock("2026-08-05T00:00:00.000Z", BOARD_ADMIN_HEADERS)
    validate_error(repeat, ApiErrorId.ERR_CLOCK_MUST_ADVANCE)

    backwards = api.set_clock("2026-08-04T23:59:59.999Z", BOARD_ADMIN_HEADERS)
    validate_error(backwards, ApiErrorId.ERR_CLOCK_MUST_ADVANCE)

    one_millisecond_on = api.set_clock("2026-08-05T00:00:00.001Z", BOARD_ADMIN_HEADERS)
    advanced = validate_success(one_millisecond_on)
    assert advanced in (None, {}), (
        f"the clock endpoint returns no entity, got {advanced!r}"
    )


def test_workstation_sanitation_log_listing_is_scoped_and_filters_within_scope(api):
    """The sub-resource list is bounded by its path workstation.

    PRD 2.3: "the sanitation logs of one workstation [are ordered] by
    `performed_at` ascending then `created_at` ascending", and "a workstation's
    sanitation logs filter on `log_type`" — the scope is the path station, per
    PRD section 4's `GET /cosmetology/workstations/{id}/sanitation-logs`.

    Design: Corner/endpoints/endpoint_sanitation_log_listing_is_scoped_to_its_own_workstation
    """
    salon = setup_establishment_with_posted_practitioner(api, station_type="FOOT_SPA")
    first_station = salon["workstation"]["id"]
    second_station = add_workstation(
        api,
        salon["establishment"]["id"],
        station_number=2,
        station_type="FOOT_SPA",
    )["id"]

    after_client = file_sanitation_log(
        api,
        first_station,
        log_type="FOOT_SPA_AFTER_CLIENT",
        performed_at="2026-07-29T09:00:00.000Z",
        contact_minutes=10.00,
    )
    end_of_day = file_sanitation_log(
        api,
        first_station,
        log_type="FOOT_SPA_END_OF_DAY",
        performed_at="2026-07-29T11:00:00.000Z",
        contact_minutes=10.00,
    )
    assert_sanitation_log_shape(end_of_day)
    assert end_of_day["workstation_id"] == first_station
    assert_instants_equal(
        end_of_day["occupancy_end_at"], "2026-07-29T11:10:00.000Z", "occupancy_end_at"
    )

    rows, meta = validate_paginated(
        api.list_workstation_sanitation_logs(first_station, BOARD_ADMIN_HEADERS)
    )
    assert meta["total_count"] == 2
    assert_sorted_asc(rows, "performed_at")
    assert [row["id"] for row in rows] == [after_client["id"], end_of_day["id"]]

    filtered, filtered_meta = validate_paginated(
        api.list_workstation_sanitation_logs(
            first_station, BOARD_ADMIN_HEADERS, {"log_type": "FOOT_SPA_AFTER_CLIENT"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert [row["id"] for row in filtered] == [after_client["id"]]

    empty, empty_meta = validate_paginated(
        api.list_workstation_sanitation_logs(second_station, BOARD_ADMIN_HEADERS)
    )
    assert empty == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    assert refresh_workstation(api, first_station)["last_biofilm_cycle_at"] is None


def test_booth_rental_create_needs_both_referenced_sides_to_resolve(api):
    """The junction row only persists once both endpoints of the link exist.

    PRD 3.3: a booth rental "names a `workstation_id` and a `practitioner_id`"
    and PRD section 5 registers `ERR_PRACTITIONER_NOT_FOUND` (HTTP 404) for an
    unresolvable practitioner reference; per PRD 2.9 that body-reference check
    runs before any version comparison, and per PRD 3.3 a `PROPOSED` rental on
    its own never satisfies the posting conditions.

    Design: Corner/endpoints/endpoint_booth_rental_link_requires_both_sides_of_the_association_to_exist
    """
    salon = create_establishment(
        api, station_capacity=4, county_code="ACX", legal_name="Link Salon"
    )
    station = add_workstation(
        api, salon["id"], station_number=1, station_type="STYLING_CHAIR"
    )
    practitioner = create_candidate(api, full_name="Basil Corte")

    unknown_side = api.create_booth_rental(
        booth_rental_payload(
            workstation_id=station["id"],
            practitioner_id=NON_EXISTENT_UUID,
            expected_workstation_version=station["version"],
            monthly_rent_cents=80000,
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(unknown_side, ApiErrorId.ERR_PRACTITIONER_NOT_FOUND)

    created = api.create_booth_rental(
        booth_rental_payload(
            workstation_id=station["id"],
            practitioner_id=practitioner["id"],
            expected_workstation_version=station["version"],
            monthly_rent_cents=80000,
        ),
        BOARD_ADMIN_HEADERS,
    )
    rental = validate_success(created, 201)
    assert_booth_rental_shape(rental)
    assert rental["workstation_id"] == station["id"]
    assert rental["practitioner_id"] == practitioner["id"]
    assert rental["status"] == "PROPOSED"
    assert rental["term_end_at"] is None
    assert rental["terminated_at"] is None
    assert_cents(rental["monthly_rent_cents"], 80000, "monthly_rent_cents")

    after = refresh_workstation(api, station["id"])
    assert after["posted_practitioner_id"] is None
    assert after["posting_status"] == "MISSING_POSTING"

    rows, meta = validate_paginated(
        api.list_booth_rentals(
            BOARD_ADMIN_HEADERS, {"practitioner_id": practitioner["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [rental["id"]]


def test_partial_payment_keeps_the_citation_issued_until_the_balance_closes(api):
    """Settlement is conditional on the outstanding balance reaching zero.

    PRD 3.8: "A valid payment appends a fine-ledger entry with `entry_reason` of
    `CITATION_PAYMENT` and `delta_cents` equal to the negative of `amount_cents`,
    then recomputes `outstanding_fine_cents`. When the balance reaches exactly 0
    the citation moves to `SETTLED` ... and a partial payment leaves the `status`
    exactly where it was while still reducing the balance."

    Design: Corner/endpoints/endpoint_partial_payment_leaves_the_citation_open_with_a_reduced_balance
    """
    code = create_violation_code(
        api,
        severity="MINOR",
        base_points=2.00,
        fine_cents_base=3000,
        category="RECORDKEEPING",
        code="REC-957",
    )
    salon = create_establishment(
        api, station_capacity=4, county_code="ACY", legal_name="Partial Salon"
    )
    finalized = setup_finalized_inspection(
        api, salon["id"], findings=[{"violation_code_id": code["id"]}], window_index=0
    )
    citation = issue_citation(api, finalized["inspection"]["id"])
    assert_fine_breakdown(citation, 5000, 250, 5250, 5250)
    owner_headers = make_establishment_owner_headers(salon["id"])

    first = api.pay_citation(
        citation["id"], payment_payload(2000, payer_reference="ACH-4401"), owner_headers
    )
    first_entry = get_success_data(first)
    assert_ledger_entry_shape(first_entry)
    assert first_entry["ledger_type"] == "FINE_CENTS"
    assert first_entry["entry_reason"] == "CITATION_PAYMENT"
    assert_cents(first_entry["delta_cents"], -2000, "delta_cents")

    half_paid = refresh_citation(api, citation["id"])
    assert half_paid["status"] == "ISSUED"
    assert_cents(half_paid["outstanding_fine_cents"], 3250, "outstanding_fine_cents")

    second = api.pay_citation(
        citation["id"], payment_payload(3250, payer_reference="ACH-4402"), owner_headers
    )
    second_entry = get_success_data(second)
    assert_cents(second_entry["delta_cents"], -3250, "delta_cents")

    settled = refresh_citation(api, citation["id"])
    assert settled["status"] == "SETTLED"
    assert_cents(settled["outstanding_fine_cents"], 0, "outstanding_fine_cents")

    facility = refresh_establishment(api, salon["id"])
    assert_cents(
        facility["outstanding_fine_total_cents"], 0, "outstanding_fine_total_cents"
    )
    assert_cents(
        facility["delinquent_fine_total_cents"], 0, "delinquent_fine_total_cents"
    )

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"citation_id": citation["id"], "ledger_type": "FINE_CENTS"},
        )
    )
    assert meta["total_count"] == 3
    assert_ledger_sum(rows, "delta_cents", 0)


def test_ledger_listing_reconciles_with_the_establishment_derived_totals(api):
    """The derived establishment fields are projections of the ledger rows.

    PRD 2.5: "An establishment's `demerit_balance` is the sum of `delta_points`
    over `DEMERIT_POINTS` entries carrying that establishment's `id` in
    `establishment_id`", while `citation_id` "is set on every `FINE_CENTS` entry"
    and `establishment_id` "is set on every `DEMERIT_POINTS` entry and null
    otherwise"; per PRD 2.6 `outstanding_fine_total_cents` then sums the
    `outstanding_fine_cents` of the establishment's open citations.

    Design: Corner/endpoints/endpoint_ledger_listing_reconciles_with_the_establishment_derived_totals
    """
    code = create_violation_code(
        api,
        severity="MAJOR",
        base_points=2.00,
        fine_cents_base=6000,
        category="SANITATION",
        code="SAN-958",
    )
    salon = create_establishment(
        api, station_capacity=4, county_code="ACZ", legal_name="Ledger Salon"
    )
    finalized = setup_finalized_inspection(
        api, salon["id"], findings=[{"violation_code_id": code["id"]}], window_index=0
    )
    inspection_id = finalized["inspection"]["id"]

    citation = issue_citation(api, inspection_id)
    assert_fine_breakdown(citation, 6000, 300, 6300, 6300)

    demerit_rows, demerit_meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"establishment_id": salon["id"], "ledger_type": "DEMERIT_POINTS"},
        )
    )
    assert demerit_meta["total_count"] == 1
    demerit = demerit_rows[0]
    assert_ledger_entry_shape(demerit)
    assert demerit["entry_reason"] == "INSPECTION_DEMERIT_ASSESSMENT"
    assert demerit["inspection_id"] == inspection_id
    assert demerit["delta_cents"] is None
    assert_points(demerit["delta_points"], 5.00, "delta_points")

    fine_rows, fine_meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"citation_id": citation["id"], "ledger_type": "FINE_CENTS"},
        )
    )
    assert fine_meta["total_count"] == 1
    fine = fine_rows[0]
    assert fine["entry_reason"] == "CITATION_ASSESSMENT"
    assert fine["citation_id"] == citation["id"]
    assert fine["delta_points"] is None
    assert_cents(fine["delta_cents"], 6300, "delta_cents")

    facility = refresh_establishment(api, salon["id"])
    assert_points(facility["demerit_balance"], 5.00, "demerit_balance")
    assert_cents(
        facility["outstanding_fine_total_cents"], 6300, "outstanding_fine_total_cents"
    )
    assert facility["compliance_posture"] == "CLEAR"

    unpaid, unpaid_meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"establishment_id": salon["id"], "entry_reason": "CITATION_PAYMENT"},
        )
    )
    assert unpaid == []
    assert unpaid_meta["total_count"] == 0


def test_violation_finding_listing_honours_each_declared_filter_and_their_pair(api):
    """Each declared finding filter narrows independently and they combine.

    PRD 2.3: "Violation findings filter on `inspection_id`, `violation_code_id`,
    `attributed_practitioner_id`, `workstation_id` and `declared_hazard`", and
    they are ordered "by `created_at` ascending, which is deliberately the same
    order the scoring calculation walks them in"; PRD 3.5 runs the provisional
    pass only on submit, so a still-`IN_PROGRESS` visit's findings carry null
    point values.

    Design: Corner/endpoints/endpoint_violation_finding_listing_filters_by_inspection_and_code
    """
    sanitation = create_violation_code(
        api,
        severity="MAJOR",
        base_points=2.00,
        fine_cents_base=6000,
        category="SANITATION",
        code="SAN-959",
    )
    recordkeeping = create_violation_code(
        api,
        severity="MINOR",
        base_points=2.00,
        fine_cents_base=3000,
        category="RECORDKEEPING",
        code="REC-959",
    )
    salon_a = create_establishment(
        api, station_capacity=4, county_code="ADA", legal_name="Filter Salon A"
    )
    salon_b = create_establishment(
        api, station_capacity=4, county_code="ADB", legal_name="Filter Salon B"
    )
    visit_a = setup_inspection_in_progress(api, salon_a["id"], window_index=0)
    finding_a1 = record_finding(api, visit_a["id"], sanitation["id"])
    visit_b = setup_inspection_in_progress(api, salon_b["id"], window_index=0)
    finding_b1 = record_finding(api, visit_b["id"], recordkeeping["id"])

    created = api.create_finding(
        visit_a["id"],
        finding_payload(
            recordkeeping["id"],
            observed_count=2,
            corrected_on_site=True,
            note="Two client cards missing service dates.",
        ),
        INSPECTOR_HEADERS,
    )
    finding_a2 = validate_success(created, 201)
    assert_finding_shape(finding_a2)
    assert finding_a2["severity"] == "MINOR"
    assert finding_a2["observed_count"] == 2
    assert finding_a2["corrected_on_site"] is True
    assert finding_a2["declared_hazard"] is False

    submitted = validate_success(api.submit_inspection(visit_a["id"], INSPECTOR_HEADERS))
    assert submitted["status"] == "PENDING_REVIEW"

    by_visit, by_visit_meta = validate_paginated(
        api.list_violation_findings(BOARD_ADMIN_HEADERS, {"inspection_id": visit_a["id"]})
    )
    assert by_visit_meta["total_count"] == 2
    assert_sorted_asc(by_visit, "created_at")
    assert [row["id"] for row in by_visit] == [finding_a1["id"], finding_a2["id"]]

    by_code, by_code_meta = validate_paginated(
        api.list_violation_findings(
            BOARD_ADMIN_HEADERS, {"violation_code_id": recordkeeping["id"]}
        )
    )
    assert by_code_meta["total_count"] == 2
    assert {row["id"] for row in by_code} == {finding_b1["id"], finding_a2["id"]}

    both, both_meta = validate_paginated(
        api.list_violation_findings(
            BOARD_ADMIN_HEADERS,
            {
                "inspection_id": visit_a["id"],
                "violation_code_id": recordkeeping["id"],
            },
        )
    )
    assert both_meta["total_count"] == 1
    assert [row["id"] for row in both] == [finding_a2["id"]]

    major = validate_success(
        api.get_violation_finding(finding_a1["id"], BOARD_ADMIN_HEADERS)
    )
    assert_points(major["provisional_points"], 5.00, "provisional_points")
    assert_points(major["repeat_factor_provisional"], 1.0, "repeat_factor_provisional")
    assert major["final_points"] is None
    assert major["repeat_factor_final"] is None

    minor = validate_success(
        api.get_violation_finding(finding_a2["id"], BOARD_ADMIN_HEADERS)
    )
    assert_points(minor["provisional_points"], 2.00, "provisional_points")

    untouched = validate_success(
        api.get_violation_finding(finding_b1["id"], BOARD_ADMIN_HEADERS)
    )
    assert untouched["provisional_points"] is None

    scored = refresh_inspection(api, visit_a["id"])
    assert scored["finding_count"] == 2
    assert_points(scored["provisional_adjusted_score"], 7.00, "provisional_adjusted_score")
    assert scored["provisional_outcome"] == "PASS"
    assert scored["status"] == "PENDING_REVIEW"
