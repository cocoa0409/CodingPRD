"""Refusals along the validation-precedence ladder, part one (PRD §2.7).

Every test here drives a request that violates exactly one rung and asserts the
error id and HTTP status the PRD's error table declares for it, so the rung
ordering itself is under test: the sanitary intake gates of §3.5, the
business-constraint rungs behind classification decisions (§3.1, §3.2) and lease
revisions (§3.4), the temporal-coherence rungs behind deployments (§3.6),
authorization windows (§3.7), seed screening and nursery completion (§3.5),
landings (§3.8), and the compliance gate that only bites at tagging (§3.9).

Each setup is arranged so that no earlier rung is also violated -- that is the
whole point of a rung-ordering test, and the PRD spells the two hardest cases
out explicitly at §2.7: a deployment window is only reachable with dates that
are themselves in the past, and a missing vibrio plan answers before out-of-order
harvest instants.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    classification_decision_payload,
    create_draft_lease,
    create_hatchery,
    date_of,
    design_world,
    DW_DEALER_CERT_NO,
    DW_HARVEST_CLOCK,
    dw_hatchery_payload,
    dw_lease_payload_overrides,
    dw_lot_payload_overrides,
    dw_seed_lot_payload_overrides,
    dw_unit_payload_overrides,
    get_success_data,
    growout_unit_payload,
    harvest_authorization_payload,
    harvest_lot_payload,
    iso,
    make_hatchery_operator_headers,
    nursery_complete_payload,
    review_payload,
    screening_payload,
    seed_lot_payload,
    set_clock,
    TEST_USERS,
    tag_payload,
    validate_error,
    validate_paginated,
    validate_success,
    water_sample_payload,
)

AUTHORITY = TEST_USERS["authority_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _intake(hatchery, lease, **overrides):
    """Post one seed-lot intake as the named hatchery's own operator, so the
    ownership rung (rung 4) is always satisfied and only an intake rule can
    answer."""
    payload = seed_lot_payload(
        hatchery["id"], lease["id"],
        **dw_seed_lot_payload_overrides(**overrides))
    return api_client.create_seed_lot(
        payload, make_hatchery_operator_headers(hatchery["id"]))


def _decide(area, classification, note, version=None):
    """Record a classification decision at the area's current version, so the
    OCC rung (rung 6) never pre-empts the business rung under test."""
    return api_client.create_classification_decision(
        area["id"],
        classification_decision_payload(
            classification,
            area["version"] if version is None else version,
            decision_note=note),
        AUTHORITY)


def _deploy(world, **overrides):
    """Deploy one more grow-out unit on the reference lease and seed lot."""
    return api_client.create_growout_unit(
        growout_unit_payload(
            world["lease"]["id"], world["seed_lot"]["id"],
            **dw_unit_payload_overrides(**overrides)),
        OPERATOR)


def _land(world, first_out, last_out, placed, lot_code):
    """Land one lot under the world's authorization without unwrapping the
    response, so a refusal can be inspected."""
    return api_client.create_harvest_lot(
        world["authorization"]["id"],
        harvest_lot_payload(first_out, last_out, placed,
                            lot_code=lot_code,
                            **dw_lot_payload_overrides()),
        OPERATOR)


# --------------------------------------------------------------------------
# Rung 8 — the sanitary intake gates on a seed lot
# --------------------------------------------------------------------------
def test_seed_lot_intake_certificate_rungs_answer_in_order():
    """Three independent intake rules live on the same endpoint and each is
    reached in turn. A hatchery whose NCSP certificate expired on 2026-03-31
    cannot ship on 2026-04-01, so the first intake is ERR_HATCHERY_CERTIFICATE_
    EXPIRED. Against the hatchery certified through 2027-03-31, a species absent
    from its `pathogen_free_species` list is ERR_SPECIES_NOT_CERTIFIED. And a
    disease certificate issued 2026-02-20 is 40 days old at a 2026-04-01
    shipment, past the 30-day maximum, so the third is
    ERR_DISEASE_CERTIFICATE_STALE. All three sit in rung 8 at HTTP 409, and each
    payload is otherwise clean so no earlier rung can answer.

    Design: Corner/validations/seed_lot_intake_certificate_rules_are_enforced
    """
    world = design_world(stage="lease")
    expired = create_hatchery(dw_hatchery_payload(
        name="Expired Point Hatchery",
        ncsp_certificate_no="NCSP-11",
        certificate_expires_on="2026-03-31"))
    current = create_hatchery(dw_hatchery_payload())

    validate_error(
        _intake(expired, world["lease"], disease_certificate_no="DC-9001"),
        ApiErrorId.ERR_HATCHERY_CERTIFICATE_EXPIRED, 409)
    validate_error(
        _intake(current, world["lease"], species="MERCENARIA_MERCENARIA",
                disease_certificate_no="DC-9002"),
        ApiErrorId.ERR_SPECIES_NOT_CERTIFIED, 409)
    validate_error(
        _intake(current, world["lease"], disease_certificate_no="DC-9003",
                disease_cert_issued_on="2026-02-20"),
        ApiErrorId.ERR_DISEASE_CERTIFICATE_STALE, 409)

    _rows, meta = validate_paginated(api_client.list_seed_lots(AUTHORITY))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Rung 12 — the business rungs behind a classification decision
# --------------------------------------------------------------------------
def test_four_accepted_samples_cannot_carry_any_classification_decision():
    """`MIN_SAMPLES_FOR_DECISION` is 5 with an inclusive comparison, and the
    sample-count floor applies to every decision on the area -- including a
    downgrade, which is otherwise exempt from the data-support rule. With four
    accepted MPN-200 samples the request is ERR_INSUFFICIENT_SAMPLE_DATA at 409,
    not ERR_CLASSIFICATION_NOT_SUPPORTED_BY_DATA (that rung is later) and not
    ERR_STALE_AREA_VERSION (the version was read after the fourth ingest). Below
    five samples the sweep cannot fire either, so the area is still APPROVED and
    OPEN with `eligible_classification` INSUFFICIENT_DATA.

    Design: Corner/validations/classification_decision_without_five_samples_returns_insufficient_sample_data
    """
    world = design_world(stage="area", sample_mpns=[200] * 4)

    response = _decide(world["area"], "RESTRICTED",
                       "four adverse samples on file")

    body = validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SAMPLE_DATA, 409)
    assert body["error_id"] != ApiErrorId.ERR_STALE_AREA_VERSION
    assert body["error_id"] != ApiErrorId.ERR_CLASSIFICATION_NOT_SUPPORTED_BY_DATA
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["classification"] == "APPROVED"
    assert area["harvest_status"] == "OPEN"
    assert area["accepted_sample_count"] == 4
    assert area["eligible_classification"] == "INSUFFICIENT_DATA"


def test_conditionally_approved_needs_the_management_plan_flag():
    """CONDITIONALLY_APPROVED is purely administrative -- the eligibility ladder
    never produces it -- and it additionally demands the area's
    `conditional_management_plan_on_file` flag. Five clean MPN-2 samples clear
    the sample-count rung and make `eligible_classification` APPROVED, which
    satisfies the data-support bar for CONDITIONALLY_APPROVED, so the refusal is
    ERR_CONDITIONAL_PLAN_REQUIRED at 409 and nothing earlier. A refused decision
    writes nothing, so the area keeps its APPROVED classification at the version
    read before the call.

    Design: Corner/validations/conditionally_approved_without_a_management_plan_on_file_is_refused
    """
    world = design_world(stage="area", sample_mpns=[2] * 5)
    version_before = world["area"]["version"]

    response = _decide(world["area"], "CONDITIONALLY_APPROVED",
                       "seasonal management proposal")

    body = validate_error(response, ApiErrorId.ERR_CONDITIONAL_PLAN_REQUIRED, 409)
    assert body["error_id"] != ApiErrorId.ERR_INSUFFICIENT_SAMPLE_DATA
    assert body["error_id"] != ApiErrorId.ERR_CLASSIFICATION_NOT_SUPPORTED_BY_DATA
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["classification"] == "APPROVED"
    assert area["version"] == version_before


def test_upgrade_must_advance_exactly_one_restrictiveness_rank():
    """Downgrades may skip ranks -- APPROVED straight to PROHIBITED is legal --
    but an upgrade must improve the restrictiveness rank by exactly 1. From
    PROHIBITED, a decision to APPROVED improves by three ranks and is
    ERR_CLASSIFICATION_STEP_SKIPPED at 409; the data-support rung ahead of it is
    satisfied because five clean samples leave `eligible_classification`
    APPROVED. The very next call to RESTRICTED is a one-rank upgrade and
    succeeds at the same `expected_area_version`, because the refused decision
    never bumped the version, and it leaves `harvest_status` at
    CLOSED_SAMPLE_FAILURE: reopening is the other, orthogonal dimension.

    Design: Corner/validations/upgrading_two_ranks_in_one_decision_returns_classification_step_skipped
    """
    world = design_world(stage="area", sample_mpns=[2] * 5,
                         classification="PROHIBITED")
    area = world["area"]
    assert area["classification"] == "PROHIBITED"
    assert area["harvest_status"] == "CLOSED_SAMPLE_FAILURE"
    assert area["eligible_classification"] == "APPROVED"

    refused = _decide(area, "APPROVED", "source removed")
    validate_error(refused, ApiErrorId.ERR_CLASSIFICATION_STEP_SKIPPED, 409)

    upgraded = validate_success(
        _decide(area, "RESTRICTED", "one rank at a time"), 200)
    assert upgraded["classification"] == "RESTRICTED"
    assert upgraded["harvest_status"] == "CLOSED_SAMPLE_FAILURE"
    assert upgraded["eligible_classification"] == "APPROVED"


def test_upgrade_beyond_the_eligible_classification_is_refused():
    """Five MPN-200 samples drive the sample sweep on the fifth ingest -- the
    geometric mean is 200.0, strictly above 14.0, and the eligibility is
    PROHIBITED, a strictly higher restrictiveness rank than the area's APPROVED
    -- so the system itself condemns the area. The authority then cannot lift it
    even one rank: an upgrade to RESTRICTED out of PROHIBITED needs
    `eligible_classification` to read APPROVED or RESTRICTED, and it reads
    PROHIBITED, so the answer is ERR_CLASSIFICATION_NOT_SUPPORTED_BY_DATA at 409
    rather than ERR_CLASSIFICATION_STEP_SKIPPED, which sits one rung later and
    would not fire anyway because PROHIBITED to RESTRICTED is a one-rank move.

    Design: Corner/validations/upgrade_beyond_what_the_data_supports_is_refused
    """
    world = design_world(stage="area", sample_mpns=[200] * 5)

    response = _decide(world["area"], "RESTRICTED", "operator appeal")

    body = validate_error(
        response, ApiErrorId.ERR_CLASSIFICATION_NOT_SUPPORTED_BY_DATA, 409)
    assert body["error_id"] != ApiErrorId.ERR_CLASSIFICATION_STEP_SKIPPED
    assert body["error_id"] != ApiErrorId.ERR_INSUFFICIENT_SAMPLE_DATA
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["classification"] == "PROHIBITED"
    assert area["harvest_status"] == "CLOSED_SAMPLE_FAILURE"
    assert area["geometric_mean_mpn"] == 200.0
    assert area["p90_mpn"] == 200.0
    assert area["eligible_classification"] == "PROHIBITED"


def test_a_fifth_submission_past_three_revision_rounds_is_refused():
    """`MAX_REVISION_ROUNDS` is 3 and `revision_round` counts completed
    re-entries rather than submissions: the first submit leaves it at 0 and three
    resubmissions take it to 3. The fourth navigation objection parks the lease
    back in REVISION_REQUESTED, which is a declared from-state of the submission
    capability, so the next submit is not ERR_INVALID_LEASE_STATE but
    ERR_REVISION_LIMIT_EXCEEDED at 409 -- the application is stuck in
    REVISION_REQUESTED and never reaches a decision, so `rent_paid_through_date`
    is still null.

    Design: Corner/validations/resubmission_beyond_the_revision_limit_is_refused
    """
    world = design_world(stage="area")
    lease = create_draft_lease(
        world["area"]["id"], OPERATOR, dw_lease_payload_overrides())
    for round_index in range(4):
        validate_success(api_client.submit_lease(
            lease["id"],
            {"submission_note": f"siting package revision {round_index}"},
            OPERATOR), 200)
        validate_success(api_client.navigation_review(
            lease["id"],
            review_payload("OBJECTION",
                           review_note="still inside the marked channel"),
            REVIEWER), 200)

    response = api_client.submit_lease(
        lease["id"], {"submission_note": "one more try"}, OPERATOR)

    body = validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED, 409)
    assert body["error_id"] != ApiErrorId.ERR_INVALID_LEASE_STATE
    stored = get_success_data(api_client.get_lease(lease["id"], AUTHORITY))
    assert stored["status"] == "REVISION_REQUESTED"
    assert stored["revision_round"] == 3
    assert stored["navigation_clearance"] == "OBJECTION"
    assert stored["rent_paid_through_date"] is None


# --------------------------------------------------------------------------
# Rung 10 — temporal coherence
# --------------------------------------------------------------------------
def test_future_dated_sample_and_zero_length_deployment_window_are_refused():
    """The future-dating rung outranks the deployment-window rung, so the window
    rule is only reachable with dates that are themselves in the past. First a
    water sample collected 2026-08-02T09:00:00Z against a 2026-08-01T00:00:00Z
    clock is ERR_FUTURE_DATED_EVENT at 422 and nothing is stored, leaving
    `accepted_sample_count` at 0. Then a deployment whose `planned_retrieval_on`
    equals -- rather than strictly follows -- its 2026-05-05 `deployed_on` is
    ERR_INVALID_DEPLOYMENT_WINDOW at 422; both dates are safely behind the clock,
    so the future-dating rung cannot answer first.

    Design: Corner/validations/future_dated_and_backwards_windows_are_rejected
    """
    world = design_world(stage="seed")

    future_sample = api_client.create_water_sample(
        world["area"]["id"],
        water_sample_payload(station_code="ST-1",
                             collected_at=iso(2026, 8, 2, 9),
                             fecal_coliform_mpn=2),
        AUTHORITY)
    validate_error(future_sample, ApiErrorId.ERR_FUTURE_DATED_EVENT, 422)
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["accepted_sample_count"] == 0

    backwards_window = _deploy(world, planned_retrieval_on="2026-05-05")
    validate_error(backwards_window,
                   ApiErrorId.ERR_INVALID_DEPLOYMENT_WINDOW, 422)

    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], AUTHORITY))
    assert lease["deployed_gear_units"] == 0
    assert seed_lot["unallocated_seed_count"] == 60000


def test_authorization_window_must_be_positive_and_within_a_day():
    """The window rule has two limbs and both refuse with the same
    ERR_AUTHORIZATION_WINDOW_INVALID at 422. A 2026-08-10T06:00:00Z to
    2026-08-11T13:00:00Z window is correctly ordered but spans 31 hours, past the
    24-hour `MAX_AUTHORIZATION_WINDOW_HOURS`; a window whose `window_end` equals
    its `window_start` is zero-length rather than silently acceptable. Both
    windows describe future intent and are exempt from future-dating, so the
    window rung really is the first one violated, and neither refusal creates an
    authorization or moves the vessel and area counters.

    Design: Corner/validations/authorization_windows_longer_than_a_day_or_of_zero_length_are_rejected
    """
    world = design_world(stage="unit")

    for start, end in ((iso(2026, 8, 10, 6), iso(2026, 8, 11, 13)),
                       (iso(2026, 8, 10, 6), iso(2026, 8, 10, 6))):
        response = api_client.create_harvest_authorization(
            harvest_authorization_payload(
                world["lease"]["id"], world["unit"]["id"],
                world["vessel"]["id"], world["dealer"]["id"], start, end,
                projected_bushels=600),
            OPERATOR)
        validate_error(response,
                       ApiErrorId.ERR_AUTHORIZATION_WINDOW_INVALID, 422)

    _rows, meta = validate_paginated(
        api_client.list_harvest_authorizations(AUTHORITY))
    vessel = get_success_data(
        api_client.get_harvest_vessel(world["vessel"]["id"], AUTHORITY))
    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert meta["total_count"] == 0
    assert vessel["active_authorization_count"] == 0
    assert area["open_authorization_count"] == 0


def test_screening_before_the_shipment_date_is_refused():
    """`screened_on` must be at or after the lot's own `shipped_on`, a relation
    between two stored dates rather than a comparison against the clock. A
    screening dated 2026-03-20 against a 2026-04-01 shipment is therefore
    ERR_SCREENING_DATE_INVALID at 422 even though 2026-03-20 is comfortably
    behind the 2026-08-01 clock, so it is not ERR_FUTURE_DATED_EVENT; nor is it
    ERR_INVALID_SEED_LOT_STATE, because RECEIVED is the declared from-state.
    A refused screening stamps nothing.

    Design: Corner/validations/screening_dated_before_the_shipment_is_rejected
    """
    world = design_world(stage="seed", seed_stage="received")

    response = api_client.screen_seed_lot(
        world["seed_lot"]["id"],
        screening_payload("NEGATIVE", "2026-03-20"), AUTHORITY)

    body = validate_error(response, ApiErrorId.ERR_SCREENING_DATE_INVALID, 422)
    assert body["error_id"] != ApiErrorId.ERR_FUTURE_DATED_EVENT
    assert body["error_id"] != ApiErrorId.ERR_INVALID_SEED_LOT_STATE
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], AUTHORITY))
    assert seed_lot["status"] == "RECEIVED"
    assert seed_lot["screening_result"] is None
    assert seed_lot["screened_on"] is None


def test_out_of_order_harvest_instants_are_refused():
    """Both ordering limbs are enforced before any time-to-temperature
    arithmetic runs, so neither lot can ever produce a negative `ttt_minutes`.
    A lot whose `last_out_of_water_at` 06:00:00Z precedes its
    `first_out_of_water_at` 08:00:00Z, and a lot placed into temperature control
    at 07:00:00Z before its last animal left the water at 08:00:00Z, are both
    ERR_INVALID_HARVEST_INSTANTS at 422. Each `first_out_of_water_at` sits inside
    the 06:00-18:00 window and behind the 11:00 clock, so neither the
    future-dating rung nor the window rung can answer first.

    Design: Corner/validations/out_of_order_harvest_instants_are_rejected
    """
    world = design_world(stage="active")
    set_clock(DW_HARVEST_CLOCK)

    for first_out, last_out, placed, lot_code in (
            (iso(2026, 8, 10, 8), iso(2026, 8, 10, 6),
             iso(2026, 8, 10, 10, 30), "LOT-BAD1"),
            (iso(2026, 8, 10, 6), iso(2026, 8, 10, 8),
             iso(2026, 8, 10, 7), "LOT-BAD2")):
        validate_error(_land(world, first_out, last_out, placed, lot_code),
                       ApiErrorId.ERR_INVALID_HARVEST_INSTANTS, 422)

    authorization = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))
    _rows, meta = validate_paginated(api_client.list_authorization_harvest_lots(
        world["authorization"]["id"], OPERATOR))
    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    assert authorization["harvested_bushels"] == 0
    assert authorization["status"] == "ACTIVE"
    assert meta["total_count"] == 0
    assert lease["royalty_accrued_cents"] == 0


# --------------------------------------------------------------------------
# Rung 8 — the compliance gate that only bites at tagging
# --------------------------------------------------------------------------
def test_tagging_is_where_a_time_and_temperature_failure_bites():
    """A NONCOMPLIANT lot is still recorded: the landing answers 201 and stamps
    the arithmetic. The month-8 plan allows 300 minutes, 24.0C water is at or
    above the plan's 23.0C so 60 come off, BOTTOM gear costs another 30, and
    MECHANICAL refrigeration credits 60 back, giving `allowed_ttt_minutes` 270.
    With the first animal out at 06:00:00Z, the last at 08:00:00Z and temperature
    control reached at 12:40:00Z the two bases are 400 and 280 minutes, and an
    APPROVED area governs on FIRST_HARVEST_BASIS, so 400 exceeds 270. The tag is
    then refused with ERR_TIME_TEMPERATURE_EXCEEDED at 409 -- not
    ERR_TAG_HARVEST_DATE_MISMATCH or ERR_TAG_DEALER_CERT_MISMATCH, since both
    payload fields match and both of those rungs sit later -- and the lot stays
    HARVESTED with all four tag fields null, so it can never reach a shipment.

    Design: Corner/validations/tagging_a_noncompliant_lot_returns_time_temperature_exceeded
    """
    world = design_world(
        stage="landed",
        harvest_clock=iso(2026, 8, 10, 14),
        placed_in_temperature_control_at=iso(2026, 8, 10, 12, 40))
    lot = world["lot"]

    response = api_client.tag_harvest_lot(
        lot["id"],
        tag_payload(date_of(lot["first_out_of_water_at"]), DW_DEALER_CERT_NO),
        OPERATOR)

    body = validate_error(response, ApiErrorId.ERR_TIME_TEMPERATURE_EXCEEDED, 409)
    assert body["error_id"] != ApiErrorId.ERR_TAG_HARVEST_DATE_MISMATCH
    assert body["error_id"] != ApiErrorId.ERR_TAG_DEALER_CERT_MISMATCH
    stored = get_success_data(api_client.get_harvest_lot(lot["id"], OPERATOR))
    assert stored["ttt_minutes_first_basis"] == 400
    assert stored["ttt_minutes_last_basis"] == 280
    assert stored["ttt_basis_variant"] == "FIRST_HARVEST_BASIS"
    assert stored["governing_ttt_minutes"] == 400
    assert stored["allowed_ttt_minutes"] == 270
    assert stored["compliance_status"] == "NONCOMPLIANT"
    assert stored["status"] == "HARVESTED"
    for field in ("tag_harvest_date", "tag_area_code", "tag_lease_code",
                  "tag_dealer_certification_no"):
        assert stored[field] is None


def test_landing_without_a_plan_for_the_harvest_month_is_refused():
    """The vibrio plan is selected by the UTC month of `first_out_of_water_at`
    and there is no default allowance, so an ACTIVE month-7 plan does not cover a
    2026-08-10 harvest: the landing is refused with
    ERR_NO_VIBRIO_PLAN_FOR_SEASON at 409 rather than falling back to the plan's
    raw maximum. The area is APPROVED and OPEN and the instants are well ordered,
    so this rung really is the first violated -- and §2.7 says the plan rung
    would answer even ahead of out-of-order instants. The plan inventory is
    checked against the unfiltered list read, which is exact here because the
    database starts empty.

    Design: Corner/validations/landing_in_a_month_without_an_active_vibrio_plan_is_refused
    """
    world = design_world(stage="active", season_month=7)
    set_clock(DW_HARVEST_CLOCK)

    response = _land(world, iso(2026, 8, 10, 6), iso(2026, 8, 10, 8),
                     iso(2026, 8, 10, 10, 30), "LOT-A")

    validate_error(response, ApiErrorId.ERR_NO_VIBRIO_PLAN_FOR_SEASON, 409)
    authorization = get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))
    assert authorization["status"] == "ACTIVE"
    assert authorization["harvested_bushels"] == 0

    plans, meta = validate_paginated(
        api_client.list_vibrio_control_plans(AUTHORITY))
    assert meta["total_count"] == 1
    assert plans[0]["season_month"] == 7
    assert plans[0]["status"] == "ACTIVE"
    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    assert lease["royalty_accrued_cents"] == 0


# --------------------------------------------------------------------------
# Rung 12 — the two deployment ceilings and the survival band
# --------------------------------------------------------------------------
def test_gear_ceiling_answers_before_the_seed_allocation_ceiling():
    """Both ceilings are read against the current deployed totals rather than the
    request in isolation, and the gear check runs first. With 40 of 200 gear
    units already out on P1, a second deployment of 161 units on P2 would reach
    201 and is ERR_LEASE_GEAR_CAPACITY_EXCEEDED at 409. Drop the request to 10
    gear units and the gear rung is satisfied, which exposes the next one: 35001
    seed against the 35000 left unallocated after the first deployment's 25000 is
    ERR_SEED_ALLOCATION_EXCEEDED at 409. P2 has never held gear, so neither the
    occupancy nor the fallow rung can answer first, and both refusals leave every
    counter untouched. Unit inventory is checked on the unfiltered list read,
    exact here because the database starts empty.

    Design: Corner/validations/lease_gear_and_seed_ceilings_are_enforced_on_deployment
    """
    world = design_world(stage="unit")

    over_gear = _deploy(world, plot_code="P2", gear_type="RACK_AND_BAG",
                        gear_units=161, seed_count_planted=100,
                        deployed_on="2026-05-06",
                        planned_retrieval_on="2026-10-20")
    validate_error(over_gear, ApiErrorId.ERR_LEASE_GEAR_CAPACITY_EXCEEDED, 409)

    over_seed = _deploy(world, plot_code="P2", gear_type="RACK_AND_BAG",
                        gear_units=10, seed_count_planted=35001,
                        deployed_on="2026-05-06",
                        planned_retrieval_on="2026-10-20")
    validate_error(over_seed, ApiErrorId.ERR_SEED_ALLOCATION_EXCEEDED, 409)

    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], AUTHORITY))
    _rows, meta = validate_paginated(api_client.list_growout_units(OPERATOR))
    assert lease["deployed_gear_units"] == 40
    assert seed_lot["allocated_seed_count"] == 25000
    assert seed_lot["unallocated_seed_count"] == 35000
    assert seed_lot["status"] == "READY_FOR_PLANTING"
    assert meta["total_count"] == 1


def test_nursery_survivors_outside_the_permitted_band_are_refused():
    """One error code guards two limbs of the same rule. 30000 survivors of
    100000 received is a 30.00% survival rate, below the 40.00%
    `SURVIVAL_FLOOR_PCT`, and 120000 of 100000 is an impossible survival above
    the intake; both are ERR_SEED_SURVIVAL_BELOW_FLOOR at 409. The 2026-04-05 to
    2026-05-01 nursery ran 26 days, past the 21-day minimum, so neither call can
    be answered ERR_NURSERY_PERIOD_TOO_SHORT, and 2026-05-01 is behind the clock
    so the future-dating rung is quiet too. Both refusals leave the lot in
    NURSERY with nothing stamped.

    Design: Corner/validations/nursery_survivor_counts_outside_the_permitted_band_are_refused
    """
    world = design_world(stage="seed", seed_stage="nursery")

    for surviving in (30000, 120000):
        response = api_client.complete_nursery(
            world["seed_lot"]["id"],
            nursery_complete_payload("2026-05-01", surviving), OPERATOR)
        body = validate_error(
            response, ApiErrorId.ERR_SEED_SURVIVAL_BELOW_FLOOR, 409)
        assert body["error_id"] != ApiErrorId.ERR_NURSERY_PERIOD_TOO_SHORT

    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], AUTHORITY))
    assert seed_lot["status"] == "NURSERY"
    assert seed_lot["nursery_completed_on"] is None
    assert seed_lot["surviving_seed_count"] is None
    assert seed_lot["survival_rate_pct"] is None
    assert seed_lot["unallocated_seed_count"] == 0
