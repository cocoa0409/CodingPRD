"""Corner coverage for the immediate consistency model (SCAFFOLD_CORNER_DESIGN §consistency_model).

PRD 2.10 pins the model: "Cascades in this system are immediate and complete
within the responding request ... there is no deferred or eventual
reconciliation."  Each test below reads the mutation's OWN response body before
it reads anything back.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    add_workstation,
    assert_cents,
    assert_citation_shape,
    assert_fine_breakdown,
    assert_instants_equal,
    assert_points,
    citation_payload,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    make_establishment_owner_headers,
    posting_payload,
    propose_rental,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    refresh_practitioner,
    setup_finalized_inspection,
    validate_paginated,
    validate_success,
)


def test_citation_response_already_carries_every_derived_money_field(api):
    """The 201 body itself holds the tier, the fine, the fee, the total and both deadlines.

    PRD 3.7 pins the whole derivation inside the create, and PRD 2.10: "When a
    write changes a parent, every dependent value the specification names as
    derived from that parent is recomputed before the response is emitted."
    Design: Corner/consistency_model/consistency_citation_response_already_carries_every_derived_money_field
    """
    code = create_violation_code(
        api, severity="MAJOR", base_points=4.00, fine_cents_base=12000, code="SAN-970"
    )
    est = create_establishment(api, county_code="AEA", station_capacity=4)
    finalized = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code["id"], "observed_count": 1}],
        window_index=0,
    )
    inspection = refresh_inspection(api, finalized["inspection"]["id"])
    # 4.00 base x 2.5 MAJOR weight x 1 observed x 1.0 repeat factor = 10.00.
    assert_points(inspection["final_adjusted_score"], 10.00, "final_adjusted_score")

    created = validate_success(
        api.create_citation(
            citation_payload(
                inspection_id=inspection["id"],
                expected_inspection_version=inspection["version"],
                subject_type="ESTABLISHMENT",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )

    assert_citation_shape(created)
    assert created["status"] == "ISSUED"
    assert created["citation_number"] is not None
    assert created["hearing_round_count"] == 0
    assert created["max_finding_severity"] == "MAJOR"
    assert_points(created["demerit_tier_multiplier"], 1.00, "demerit_tier_multiplier")
    # base 12000 x tier 1.00 x subject factor 1.00, no surcharge; fee is 5% of
    # 12000 because the assessed fine is at most 25000 cents.
    assert_fine_breakdown(created, 12000, 600, 12600, outstanding_fine_cents=12600)
    assert_instants_equal(created["issued_at"], "2026-08-01T00:00:00.000Z", "issued_at")
    assert_instants_equal(created["due_at"], "2026-08-31T00:00:00.000Z", "due_at")
    assert_instants_equal(
        created["contest_deadline_at"], "2026-08-21T00:00:00.000Z", "contest_deadline_at"
    )

    facility = refresh_establishment(api, est["id"])
    assert_cents(
        facility["outstanding_fine_total_cents"], 12600, "outstanding_fine_total_cents"
    )
    assert_points(facility["demerit_balance"], 10.00, "demerit_balance")
    assert facility["open_critical_citation_count"] == 0
    assert facility["compliance_posture"] == "CLEAR"

    fetched = refresh_citation(api, created["id"])
    assert_fine_breakdown(
        fetched,
        created["assessed_fine_cents"],
        created["administrative_fee_cents"],
        created["total_due_cents"],
        outstanding_fine_cents=created["outstanding_fine_cents"],
    )

    rows, meta = validate_paginated(
        api.list_ledger_entries(BOARD_ADMIN_HEADERS, {"citation_id": created["id"]})
    )
    assert meta["total_count"] == 1
    assert_cents(rows[0]["delta_cents"], 12600, "delta_cents")


def test_posting_projection_is_recomputed_within_the_request_that_changes_it(api):
    """The posting body already reads STALE_POSTING; the activation flips it to COMPLIANT.

    PRD 3.3: "Posting recomputes the station's `posting_status`" and "Activation
    recomputes the parent station's `posting_status`, which typically moves
    `STALE_POSTING` -> `COMPLIANT` once the term covers the current clock", with
    PRD 2.10 forbidding any deferred reconciliation.
    Design: Corner/consistency_model/consistency_posting_projection_is_recomputed_within_the_request_that_changes_it
    """
    school = create_school(
        api, required_clock_hours=16.00, accreditation_status="ACCREDITED", county_code="AEB"
    )
    practitioner = create_licensed_practitioner(
        api,
        school_id=school["id"],
        license_type="COSMETOLOGIST",
        effective_at="2026-08-01T00:00:00.000Z",
        full_name="Juno Vasilev",
    )
    est = create_establishment(api, county_code="AEC", station_capacity=4)
    owner_headers = make_establishment_owner_headers(est["id"])
    station = add_workstation(api, est["id"], station_number=1, station_type="STYLING_CHAIR")
    rental = propose_rental(
        api,
        station["id"],
        practitioner["id"],
        term_start_at="2026-08-01T00:00:00.000Z",
        rental_type="BOOTH_RENTER_INDEPENDENT_CONTRACTOR",
        monthly_rent_cents=65000,
    )
    assert rental["status"] == "PROPOSED"

    posted = validate_success(
        api.post_licence_at_workstation(
            station["id"], posting_payload(practitioner["id"]), owner_headers
        )
    )
    # The rental is still PROPOSED, so the third condition of PRD 3.3 fails and
    # the posting response itself must already say so.
    assert posted["posted_practitioner_id"] == practitioner["id"]
    assert posted["posting_status"] == "STALE_POSTING"

    activated = validate_success(
        api.activate_booth_rental(rental["id"], owner_headers)
    )
    assert activated["status"] == "ACTIVE"

    # The activation response is a BoothRental, so the station verdict is only
    # observable on the immediately following read - with no intervening write.
    station_after = validate_success(api.get_workstation(station["id"], owner_headers))
    assert station_after["posting_status"] == "COMPLIANT"
    assert station_after["posted_practitioner_id"] == practitioner["id"]

    licensee = refresh_practitioner(api, practitioner["id"])
    assert licensee["license_status"] == "ACTIVE"
    assert licensee["license_expires_on"] == "2028-07-31"

    _, meta = validate_paginated(
        api.list_booth_rentals(
            BOARD_ADMIN_HEADERS, {"workstation_id": station["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1
