"""Cross-cutting layer corners (SCAFFOLD_CORNER_DESIGN ``cross_cutting_layers``).

Three of the four cases below are optimistic-concurrency corners: the two
stale-token guards of PRD 2.8, and the precision of PRD 2.10's rule that a write
advances the ``version`` of every entity it actually mutates — by exactly one —
and leaves an entity it merely reads untouched.  The fourth is the instantaneous
arm of the PRD 2.6 posture gate, where a single open ``CRITICAL`` citation
forces ``RESTRICTED`` on a balance far below the ``WATCH`` threshold.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    POSTURE_WATCH_DEMERITS,
    ApiErrorId,
    add_workstation,
    assert_cents,
    assert_fine_breakdown,
    assert_instants_equal,
    assert_ledger_entry_shape,
    assert_points,
    assert_version_incremented,
    booth_rental_payload,
    citation_payload,
    create_establishment,
    create_licensed_practitioner,
    create_violation_code,
    get_success_data,
    make_establishment_owner_headers,
    payment_payload,
    refresh_booth_rental,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    refresh_workstation,
    setup_finalized_inspection,
    setup_submitted_inspection,
    validate_error,
    validate_paginated,
    validate_success,
    workstation_payload,
)


def test_stale_workstation_version_blocks_the_second_booth_rental_create(api):
    """The first rental's own version bump is what makes the held token stale.

    PRD 2.8: creating a booth rental "requires the non-optional field
    ``expected_workstation_version`` ... If it does not equal the workstation's
    current ``version``, the create is rejected with
    ``ERR_STALE_WORKSTATION_VERSION`` (HTTP 412)", and the guard exists
    "precisely because a chain of successive rentals on one station is a
    legitimate product operation".  PRD 3.3 makes the second, adjacent term
    lawful — "two rentals that merely touch ... are accepted" — so the refusal
    is the stale token and never ``ERR_BOOTH_RENTAL_OVERLAP``.

    Design: Corner/cross_cutting_layers/cross_cutting_stale_workstation_version_blocks_the_second_booth_rental_create
    """
    practitioner = create_licensed_practitioner(api)
    establishment = create_establishment(api, station_capacity=4)
    station = add_workstation(
        api, establishment["id"], station_number=1, station_type="STYLING_CHAIR"
    )
    ws_v1 = station["version"]

    first = validate_success(
        api.create_booth_rental(
            booth_rental_payload(
                workstation_id=station["id"],
                practitioner_id=practitioner["id"],
                expected_workstation_version=ws_v1,
                rental_type="BOOTH_RENTER_INDEPENDENT_CONTRACTOR",
                term_start_at="2026-08-01T00:00:00.000Z",
                term_end_at="2026-09-01T00:00:00.000Z",
                monthly_rent_cents=70000,
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )

    # The second term starts exactly where the first ends, so the only thing
    # wrong with this request is the token the caller is still holding.
    stale_payload = booth_rental_payload(
        workstation_id=station["id"],
        practitioner_id=practitioner["id"],
        expected_workstation_version=ws_v1,
        rental_type="BOOTH_RENTER_INDEPENDENT_CONTRACTOR",
        term_start_at="2026-09-01T00:00:00.000Z",
        term_end_at="2026-10-01T00:00:00.000Z",
        monthly_rent_cents=70000,
    )
    validate_error(
        api.create_booth_rental(stale_payload, BOARD_ADMIN_HEADERS),
        ApiErrorId.ERR_STALE_WORKSTATION_VERSION,
        412,
    )

    reread = refresh_workstation(api, station["id"])
    assert_version_incremented(reread["version"], ws_v1)
    assert reread["version"] == ws_v1 + 1, (
        "the first rental create advanced the station exactly once (PRD 2.10)"
    )

    retry_payload = dict(stale_payload, expected_workstation_version=reread["version"])
    second = validate_success(
        api.create_booth_rental(retry_payload, BOARD_ADMIN_HEADERS), 201
    )
    assert second["status"] == "PROPOSED"
    assert_instants_equal(second["term_start_at"], "2026-09-01T00:00:00.000Z")
    assert_instants_equal(second["term_end_at"], "2026-10-01T00:00:00.000Z")

    assert refresh_booth_rental(api, first["id"])["status"] == "PROPOSED", (
        "the refused create left the existing rental alone"
    )

    rows, meta = validate_paginated(
        api.list_booth_rentals(
            BOARD_ADMIN_HEADERS, {"workstation_id": station["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_stale_inspection_version_blocks_citation_issuance(api):
    """The token read at submit is already stale once finalize has scored.

    PRD 2.8: creating a citation "requires the non-optional field
    ``expected_inspection_version`` ... If it does not equal the inspection's
    current ``version``, the create is rejected with
    ``ERR_STALE_INSPECTION_VERSION`` (HTTP 412)".  PRD 2.9 step 12 puts the
    concurrency token after the state gates, so an inspection that IS
    ``FINALIZED`` reports the stale token and never
    ``ERR_INSPECTION_NOT_FINALIZED``.

    Design: Corner/cross_cutting_layers/cross_cutting_stale_inspection_version_blocks_citation_issuance
    """
    code = create_violation_code(
        api,
        severity="MINOR",
        base_points=2.00,
        fine_cents_base=3000,
        category="RECORDKEEPING",
    )
    establishment = create_establishment(api, station_capacity=4)

    submitted = setup_submitted_inspection(
        api,
        establishment["id"],
        findings=[
            {
                "violation_code_id": code["id"],
                "observed_count": 1,
                "corrected_on_site": False,
            }
        ],
        window_index=0,
    )
    inspection_id = submitted["inspection"]["id"]
    version_at_submit = submitted["inspection"]["version"]

    finalized = validate_success(
        api.finalize_inspection(inspection_id, BOARD_ADMIN_HEADERS)
    )
    assert finalized["status"] == "FINALIZED"
    # 2.00 base points x 1.0 MINOR weight x 1 observed x 1.0 repeat factor.
    assert_points(finalized["final_adjusted_score"], 2.00, "final_adjusted_score")

    validate_error(
        api.create_citation(
            citation_payload(
                inspection_id=inspection_id,
                expected_inspection_version=version_at_submit,
                subject_type="ESTABLISHMENT",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        ApiErrorId.ERR_STALE_INSPECTION_VERSION,
        412,
    )

    after_refusal = refresh_inspection(api, inspection_id)
    assert after_refusal["citation_count"] == 0, "the refused create issued nothing"
    assert_version_incremented(after_refusal["version"], version_at_submit)
    assert_cents(
        refresh_establishment(api, establishment["id"])["outstanding_fine_total_cents"],
        0,
        "outstanding_fine_total_cents",
    )

    citation = validate_success(
        api.create_citation(
            citation_payload(
                inspection_id=inspection_id,
                expected_inspection_version=after_refusal["version"],
                subject_type="ESTABLISHMENT",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    assert citation["status"] == "ISSUED"
    assert citation["max_finding_severity"] == "MINOR"
    # PRD 3.7: base 3000 x tier 1.00 x subject 1.00, no surcharge at 2.00
    # points, clamped up to the 5000-cent floor; the fee is 5% of 5000.
    assert_fine_breakdown(
        citation,
        assessed_fine_cents=5000,
        administrative_fee_cents=250,
        total_due_cents=5250,
        outstanding_fine_cents=5250,
    )
    assert refresh_inspection(api, inspection_id)["citation_count"] == 1


def test_every_mutating_write_advances_exactly_the_touched_entity_versions(api):
    """Version movement follows derived state, not the URL.

    PRD 3.3: adding a workstation "refreshes the parent establishment's
    ``station_count`` and ``foot_spa_biofilm_current`` and increments its
    ``version``", while a rental's "creation increments the parent
    workstation's ``version``".  PRD 2.10: "Each entity a cascade actually
    mutates has its ``updated_at`` refreshed and its ``version`` incremented by
    exactly 1, and an entity a cascade merely reads is left untouched" — so the
    rental create must not move the establishment at all.

    Design: Corner/cross_cutting_layers/cross_cutting_every_mutating_write_advances_the_touched_entity_versions
    """
    practitioner = create_licensed_practitioner(api, license_type="BARBER")
    establishment = create_establishment(
        api, station_capacity=4, establishment_type="BARBERSHOP"
    )
    est_v0 = establishment["version"]
    assert establishment["station_count"] == 0

    station = validate_success(
        api.create_workstation(
            establishment["id"],
            workstation_payload(station_number=1, station_type="STYLING_CHAIR"),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    ws_v0 = station["version"]

    after_station = refresh_establishment(api, establishment["id"])
    est_v1 = after_station["version"]
    assert_version_incremented(est_v1, est_v0)
    assert est_v1 == est_v0 + 1, "the child create advanced the parent exactly once"
    assert after_station["station_count"] == 1
    assert after_station["foot_spa_biofilm_current"] is True, (
        "PRD 2.6: a facility with no FOOT_SPA station satisfies the flag vacuously"
    )

    rental = validate_success(
        api.create_booth_rental(
            booth_rental_payload(
                workstation_id=station["id"],
                practitioner_id=practitioner["id"],
                expected_workstation_version=ws_v0,
                rental_type="BOOTH_RENTER_INDEPENDENT_CONTRACTOR",
                term_start_at="2026-08-01T00:00:00.000Z",
                monthly_rent_cents=60000,
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    assert rental["status"] == "PROPOSED"

    after_rental_station = refresh_workstation(api, station["id"])
    assert_version_incremented(after_rental_station["version"], ws_v0)
    assert after_rental_station["version"] == ws_v0 + 1, (
        "the rental create advanced the workstation exactly once"
    )
    assert after_rental_station["posting_status"] == "MISSING_POSTING"
    assert after_rental_station["last_biofilm_cycle_at"] is None

    after_rental_est = refresh_establishment(api, establishment["id"])
    assert after_rental_est["version"] == est_v1, (
        "the rental create only reads the establishment, so it is left untouched"
    )


def test_one_open_critical_citation_forces_restricted_and_settling_it_resets(api):
    """The instantaneous arm of the posture gate, on a 10.00-point balance.

    PRD 2.6: the posture is "``RESTRICTED`` when ``demerit_balance`` has
    reached 50.00 points or more, or when ``open_critical_citation_count`` is at
    least 1", and that count covers "those same non-dismissed, non-settled
    citations whose ``max_finding_severity`` is ``CRITICAL`` or
    ``IMMINENT_HAZARD``".  Settling drops the citation out of the count, "but
    the reversal ledger rows they produced remain in ``demerit_balance``
    forever", so the posture falls back to whatever the surviving balance alone
    dictates.

    Design: Corner/cross_cutting_layers/cross_cutting_one_open_critical_citation_forces_restricted_posture_and_settling_it_resets
    """
    code = create_violation_code(
        api,
        severity="CRITICAL",
        base_points=2.00,
        fine_cents_base=20000,
        category="SANITATION",
    )
    establishment = create_establishment(api, station_capacity=4)

    finalized = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[
            {
                "violation_code_id": code["id"],
                "observed_count": 1,
                "corrected_on_site": False,
            }
        ],
        window_index=0,
    )
    inspection = finalized["inspection"]
    # 2.00 x 5.0 CRITICAL weight x 1 observed x 1.0 repeat, no on-site credit.
    assert_points(inspection["final_adjusted_score"], 10.00, "final_adjusted_score")
    assert inspection["final_outcome"] == "FAIL", (
        "PRD 3.5: a CRITICAL finding fails the visit whatever the arithmetic says"
    )

    before_citation = refresh_establishment(api, establishment["id"])
    assert_points(before_citation["demerit_balance"], 10.00, "demerit_balance")
    assert before_citation["open_critical_citation_count"] == 0
    assert before_citation["compliance_posture"] == "CLEAR", (
        "10.00 points is below the 20.00-point WATCH threshold"
    )
    assert before_citation["license_status"] == "PENDING_INSPECTION", (
        "PRD 3.7 hop four only promotes on PASS or CONDITIONAL_PASS"
    )

    citation = validate_success(
        api.create_citation(
            citation_payload(
                inspection_id=inspection["id"],
                expected_inspection_version=refresh_inspection(
                    api, inspection["id"]
                )["version"],
                subject_type="ESTABLISHMENT",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    assert citation["max_finding_severity"] == "CRITICAL"
    # PRD 3.7: base 20000 x tier 1.00 (snapshot 0.00) x subject 1.00, no
    # surcharge below 30.00 points; the 5% band applies at 20000 cents.
    assert_fine_breakdown(
        citation,
        assessed_fine_cents=20000,
        administrative_fee_cents=1000,
        total_due_cents=21000,
        outstanding_fine_cents=21000,
    )

    with_open_citation = refresh_establishment(api, establishment["id"])
    assert with_open_citation["open_critical_citation_count"] == 1
    assert with_open_citation["compliance_posture"] == "RESTRICTED"
    assert_points(with_open_citation["demerit_balance"], 10.00, "demerit_balance")
    assert_cents(
        with_open_citation["outstanding_fine_total_cents"],
        21000,
        "outstanding_fine_total_cents",
    )

    # PRD 3.8: the payment endpoint returns the appended ledger entry, not the
    # citation, so both the citation and the establishment must be re-read.
    entry = get_success_data(
        api.pay_citation(
            citation["id"],
            payment_payload(21000, payer_reference="WIRE-3301"),
            make_establishment_owner_headers(establishment["id"]),
        )
    )
    assert_ledger_entry_shape(entry)
    assert entry["ledger_type"] == "FINE_CENTS"
    assert entry["entry_reason"] == "CITATION_PAYMENT"
    assert_cents(entry["delta_cents"], -21000, "delta_cents")

    settled = refresh_citation(api, citation["id"])
    assert settled["status"] == "SETTLED"
    assert_cents(settled["outstanding_fine_cents"], 0, "outstanding_fine_cents")

    after = refresh_establishment(api, establishment["id"])
    assert after["open_critical_citation_count"] == 0
    assert_cents(after["outstanding_fine_total_cents"], 0, "outstanding_fine_total_cents")
    assert_points(after["demerit_balance"], 10.00, "demerit_balance")
    # The posture falls back to the demerit arm alone: 10.00 < 20.00 -> CLEAR.
    expected_posture = (
        "WATCH" if after["demerit_balance"] >= POSTURE_WATCH_DEMERITS else "CLEAR"
    )
    assert after["compliance_posture"] == expected_posture
