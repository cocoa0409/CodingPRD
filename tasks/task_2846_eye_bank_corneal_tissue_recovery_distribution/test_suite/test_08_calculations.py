"""
Arithmetic: the recovery window's banded credits, the serology cascade's hemodilution gate,
the occupation interval's input set, and the two shelf-life and quality clamps.

Every case pins an exact figure — minutes, hours, points — rather than a direction of
movement, and several sit deliberately on the wrong side of a neighbouring band.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    LAB_TECHNICIAN_HEADERS,
    T_NOW,
    assert_instant_equals,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)


def _consented_donor_with_a_drawn_panel(pinned_api, donor_code, hemodilution_pct):
    """A consented donor whose single panel is still DRAWN at the given dilution."""
    donor = fixtures.create_donor(
        pinned_api,
        donor_code=donor_code,
        death_at="2026-08-03T02:00:00.000Z",
        body_cooled_at=None,
        age_years=52,
    )
    fixtures.add_screening(pinned_api, donor["id"], "TATTOO_12M", "NO", "SPOUSE")
    fixtures.record_consent(pinned_api, donor["id"])
    panel = fixtures.draw_panel(
        pinned_api,
        donor["id"],
        drawn_at="2026-08-03T04:00:00.000Z",
        hemodilution_pct=hemodilution_pct,
    )
    assert panel["status"] == "DRAWN"
    return donor, panel


def test_donor_recovery_window_charges_the_slow_cooling_credit_and_the_age_penalty(
    pinned_api,
):
    """
    A five-hour cooling delay earns the middle two-hour credit rather than the four-hour one,
    and the elderly donor's penalty comes off on top: 660 + 120 - 60 = 720 minutes.

    PRD 3.1: "Otherwise the cooling delay is the number of whole minutes from `death_at` to
    `body_cooled_at`, floored; a delay of at most four hours (240 minutes) earns a credit of
    four hours, a delay of more than four hours but at most eight hours (480 minutes) earns a
    credit of two hours (120 minutes), and a delay beyond eight hours earns nothing."

    PRD 3.1: "Advanced age costs time: a donor aged 71 years or more incurs a penalty of one
    hour (60 minutes), and every younger donor incurs none."

    PRD 3.1: "The stored `recovery_window_minutes` is the base window plus the cooling credit
    minus the age penalty, **but never less than six hours (360 minutes)** — that floor is a
    hard clamp applied after the addition and subtraction, not a separate branch."

    Design: Corner/calculations/donor_recovery_window_charges_the_slow_cooling_credit_and_the_age_penalty
    """
    response = pinned_api.create_donor(
        factories.donor_payload(
            donor_code="D-2846-K01",
            referral_source="HOSPICE",
            death_at="2026-08-02T20:00:00.000Z",
            death_time_basis="PRONOUNCED",
            body_cooled_at="2026-08-03T01:00:00.000Z",
            age_years=75,
            cause_of_death_category="NEUROLOGIC",
        ),
        COORDINATOR_HEADERS,
    )

    donor = validate_success(response, 201)
    assert donor["recovery_window_minutes"] == 720
    assert_instant_equals(
        donor["recovery_deadline_at"], "2026-08-03T08:00:00.000Z", "recovery_deadline_at"
    )


def test_hemodilution_above_the_gate_forces_indeterminate_despite_four_clean_markers(
    pinned_api,
):
    """
    Four non-reactive markers cannot rescue a specimen diluted to 55.00 percent: the verdict
    is INDETERMINATE and the donor's published serology follows it.

    PRD 3.2: "The panel's `overall_result` is then resolved by an ordered cascade in which
    **reactivity dominates everything**: if any one of the four markers is `REACTIVE`,
    `overall_result` is `REACTIVE`; otherwise, if `hemodilution_pct` is strictly greater than
    50.00 the specimen is too dilute to trust and `overall_result` is `INDETERMINATE` — a
    `hemodilution_pct` of exactly 50.00 does **not** trip this gate; otherwise, if any marker
    is `INDETERMINATE` then `overall_result` is `INDETERMINATE`; and only when none of those
    conditions holds is `overall_result` `NON_REACTIVE`."

    PRD 3.2: "The panel moves `DRAWN → RESULTED` with `resulted_at` stamped from the logical
    clock, and the donor's `serology_status` is republished from the verdict: `NON_REACTIVE`
    becomes `NEGATIVE`, `REACTIVE` becomes `REACTIVE`, and `INDETERMINATE` becomes
    `INDETERMINATE`."

    PRD 3.2: "The donor's risk score is then recomputed under the
    `POST_SEROLOGY_RECONCILED` variant and `screening_risk_variant` is set to that value."

    Design: Corner/calculations/hemodilution_above_the_gate_forces_indeterminate_despite_four_clean_markers
    """
    donor, panel = _consented_donor_with_a_drawn_panel(pinned_api, "D-2846-K02", 55.00)

    resulted = fixtures.post_results(pinned_api, panel["id"])

    assert resulted["overall_result"] == "INDETERMINATE"
    assert resulted["status"] == "RESULTED"
    assert_instant_equals(resulted["resulted_at"], T_NOW, "resulted_at")
    reread = fixtures.read_donor(pinned_api, donor["id"])
    assert reread["serology_status"] == "INDETERMINATE"
    assert reread["screening_risk_variant"] == "POST_SEROLOGY_RECONCILED"
    assert reread["status"] == "CONSENT_OBTAINED"


def test_hemodilution_exactly_at_fifty_point_zero_zero_stays_non_reactive(pinned_api):
    """
    The dilution gate is strictly greater than 50.00, so a specimen at exactly 50.00 with
    four clean markers resolves NON_REACTIVE and publishes NEGATIVE.

    PRD 3.2: "The panel's `overall_result` is then resolved by an ordered cascade in which
    **reactivity dominates everything**: if any one of the four markers is `REACTIVE`,
    `overall_result` is `REACTIVE`; otherwise, if `hemodilution_pct` is strictly greater than
    50.00 the specimen is too dilute to trust and `overall_result` is `INDETERMINATE` — a
    `hemodilution_pct` of exactly 50.00 does **not** trip this gate; otherwise, if any marker
    is `INDETERMINATE` then `overall_result` is `INDETERMINATE`; and only when none of those
    conditions holds is `overall_result` `NON_REACTIVE`."

    PRD 3.2: "The panel moves `DRAWN → RESULTED` with `resulted_at` stamped from the logical
    clock, and the donor's `serology_status` is republished from the verdict: `NON_REACTIVE`
    becomes `NEGATIVE`, `REACTIVE` becomes `REACTIVE`, and `INDETERMINATE` becomes
    `INDETERMINATE`."

    Design: Corner/calculations/hemodilution_exactly_at_fifty_point_zero_zero_stays_non_reactive
    """
    donor, panel = _consented_donor_with_a_drawn_panel(pinned_api, "D-2846-K03", 50.00)

    resulted = fixtures.post_results(pinned_api, panel["id"])

    assert resulted["overall_result"] == "NON_REACTIVE"
    assert resulted["status"] == "RESULTED"
    assert fixtures.read_donor(pinned_api, donor["id"])["serology_status"] == "NEGATIVE"
    panels = get_success_data(
        pinned_api.list_serology_panels(donor["id"], LAB_TECHNICIAN_HEADERS)
    )
    assert len(panels) == 1


def test_aborted_recoveries_leave_the_technician_occupation_set_empty(pinned_api):
    """
    An aborted dispatch drops out of the overlap candidate set entirely, so a second dispatch
    squarely inside the abandoned interval is admitted.

    PRD 3.3: "That end is computed as **the recovery's `preservation_at` once the recovery has
    reached `COMPLETED`, and otherwise its `planned_release_at`**, in either case advanced by a
    fixed turnaround allowance of **one hour — 60 minutes** — covering transport and instrument
    reprocessing."

    PRD 3.3: "The candidate set against which a proposed dispatch is checked is every recovery
    already recorded for that same technician whose `status` is `DISPATCHED`, `ON_SITE` or
    `COMPLETED`; recoveries in `ABORTED` are excluded entirely, because an aborted dispatch
    releases the technician."

    PRD 3.3: "Abort is legal from `DISPATCHED` or from `ON_SITE`, records the supplied
    `abort_reason`, moves the recovery to the terminal `ABORTED` status, and releases the
    technician: `open_dispatch_count` falls by 1 and the recovery drops out of the overlap
    candidate set, so the freed window becomes immediately dispatchable."

    Design: Corner/calculations/aborted_recoveries_leave_the_technician_occupation_set_empty
    """
    technician = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    donor_a = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-K04A",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    donor_b = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-K04B",
        death_at="2026-08-03T02:30:00.000Z",
        body_cooled_at="2026-08-03T03:30:00.000Z",
        age_years=60,
        cause_of_death_category="TRAUMA",
    )
    first = fixtures.create_recovery(
        pinned_api,
        donor_a["id"],
        technician["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T10:00:00.000Z",
    )
    assert_instant_equals(
        first["occupation_end_at"], "2026-08-03T11:00:00.000Z", "occupation_end_at"
    )
    aborted = fixtures.abort_recovery(
        pinned_api,
        first["id"],
        technician["id"],
        abort_reason="Family withdrew at bedside",
    )
    assert aborted["status"] == "ABORTED"
    assert fixtures.read_technician(pinned_api, technician["id"])["open_dispatch_count"] == 0

    second = fixtures.create_recovery(
        pinned_api,
        donor_b["id"],
        technician["id"],
        dispatched_at="2026-08-03T07:00:00.000Z",
        planned_release_at="2026-08-03T11:00:00.000Z",
    )

    assert second["status"] == "DISPATCHED"
    assert_instant_equals(
        second["occupation_end_at"], "2026-08-03T12:00:00.000Z", "occupation_end_at"
    )
    assert fixtures.read_technician(pinned_api, technician["id"])["open_dispatch_count"] == 1


def test_within_extended_band_docks_forty_eight_hours_from_the_provisional_shelf_life(
    pinned_api,
):
    """
    Preservation thirteen hours after death is still inside the 960 minute window but lands in
    the extended band, which costs the fresh cornea 48 of its 336 hours.

    PRD 3.3: "On success, `death_to_preservation_minutes` is set to the number of whole
    minutes from the donor's `death_at` to `preservation_at`, floored, and `time_limit_band` is
    banded from that figure: `WITHIN_STANDARD` when it is at most twelve hours (720 minutes),
    `WITHIN_EXTENDED` when it is more than 720 but at most fifteen hours (900 minutes), and
    `EXCEEDED` when it is greater still."

    PRD 3.3: "The medium sets the base: **`OPTISOL_GS` gives 336 hours (fourteen days) and
    `LIFE4C` gives 264 hours (eleven days)**."

    PRD 3.3: "From that base, 48 hours are deducted when the recovery's `time_limit_band` is
    `WITHIN_EXTENDED`, and nothing is deducted for the other two bands."

    PRD 3.3: "The result is then raised to a floor of 24 hours if it fell below, and stored in
    `shelf_life_hours`, with `expires_at` set to `preserved_at` advanced by that many whole
    hours."

    Design: Corner/calculations/within_extended_band_docks_forty_eight_hours_from_the_provisional_shelf_life
    """
    technician = fixtures.create_technician(pinned_api, "Rosa Field", "RECOVERY_ONLY")
    donor = fixtures.approved_donor(
        pinned_api,
        donor_code="D-2846-K05",
        body_cooled_at="2026-08-03T03:00:00.000Z",
        age_years=52,
    )
    assert donor["recovery_window_minutes"] == 960
    assert_instant_equals(
        donor["recovery_deadline_at"], "2026-08-03T18:00:00.000Z", "recovery_deadline_at"
    )
    recovery = fixtures.create_recovery(
        pinned_api,
        donor["id"],
        technician["id"],
        dispatched_at="2026-08-03T06:30:00.000Z",
        planned_release_at="2026-08-03T16:00:00.000Z",
    )
    fixtures.arrive(
        pinned_api, recovery["id"], technician["id"], "2026-08-03T07:00:00.000Z"
    )

    completed = fixtures.complete_recovery(
        pinned_api,
        recovery["id"],
        technician["id"],
        preservation_at="2026-08-03T15:00:00.000Z",
    )

    assert completed["status"] == "COMPLETED"
    assert completed["death_to_preservation_minutes"] == 780
    assert completed["time_limit_band"] == "WITHIN_EXTENDED"
    tissues = fixtures.tissues_of_recovery(pinned_api, recovery["id"])
    assert len(tissues) == 1
    tissue = tissues[0]
    assert tissue["shelf_life_hours"] == 288
    assert tissue["shelf_life_variant"] == "PROVISIONAL_AT_RECOVERY"
    assert_instant_equals(tissue["expires_at"], "2026-08-15T15:00:00.000Z", "expires_at")


def test_tissue_quality_score_clamps_at_one_hundred_and_the_ecd_points_cap_at_forty(
    pinned_api,
):
    """
    A flawless young donor's cornea overshoots twice — 4000 cells would earn 44 endothelial
    points and the raw total would be 105 — and both clamps bite.

    PRD 3.5: "**Endothelial points** reward cell density above a baseline of 1800 cells per
    square millimetre: subtract 1800 from `endothelial_cell_count`, divide by 50 and take the
    floor, then raise the result to 0 if it went negative and cap it at 40 — the clamps are
    applied in exactly that order, so a count of 1799 earns zero rather than a negative
    contribution and a count of 4000 earns 40 rather than 44."

    PRD 3.5: "The five component figures and the age adjustment are added together, and the
    sum is then raised to at least 0 and lowered to at most 100."

    PRD 3.5: "Otherwise, when `tissue_quality_score` is 70 or above **and** the specular
    `endothelial_cell_count` is 2000 or above **and** the recovery's `time_limit_band` is
    `WITHIN_STANDARD`, the classification is `TRANSPLANT_OPTICAL`."

    PRD 3.5: "The base less all three applicable penalties is then raised to a floor of 24
    hours, stored in `shelf_life_hours`, and `expires_at` is recomputed as `preserved_at`
    advanced by that many whole hours."

    Design: Corner/calculations/tissue_quality_score_clamps_at_one_hundred_and_the_ecd_points_cap_at_forty
    """
    chain = fixtures.tissue_chain(
        pinned_api,
        donor_code="D-2846-K06",
        donor_kwargs={"age_years": 30, "cause_of_death_category": "TRAUMA"},
        endothelial_cell_count=4000,
        classify_tissues=False,
        evaluation_technician_name="Nils Abadi",
    )
    assert chain["recovery"]["time_limit_band"] == "WITHIN_STANDARD"
    provisional = chain["tissues"][0]
    assert_instant_equals(
        provisional["expires_at"], "2026-08-17T09:00:00.000Z", "provisional expires_at"
    )

    classified = fixtures.classify(pinned_api, chain["tissue_ids"][0])

    assert classified["tissue_quality_score"] == 100
    assert classified["classification"] == "TRANSPLANT_OPTICAL"
    assert classified["disposition_status"] == "ELIGIBLE"
    assert classified["shelf_life_hours"] == 336
    assert classified["shelf_life_variant"] == "FINAL_AT_CLASSIFICATION"
    assert_instant_equals(
        classified["expires_at"], "2026-08-17T09:00:00.000Z", "final expires_at"
    )
