"""Validation corners: siting, drainage, uniqueness, seals and the pass ban."""
from test_helpers import (
    PROGRAM_ADMIN,
    ApiErrorId,
    add_watercraft,
    api_client,
    create_reciprocity_agreement,
    create_water_body,
    disposition_payload,
    fetch_record,
    fetch_station,
    fetch_water_body,
    fetch_watercraft,
    make_inspector_headers,
    move_reciprocity_agreement,
    quarantine_order_payload,
    reciprocity_agreement_payload,
    register_watercraft,
    screening_payload,
    set_clock,
    setup_decon_required,
    setup_inspection,
    setup_program,
    station_payload,
    validate_error,
    validate_paginated,
    validate_success,
    water_body_patch_payload,
    watercraft_payload,
)

ARRIVAL = "2026-08-05T09:00:00Z"


class TestStationSitingCoherence:
    """The siting rule is two-sided: each type demands one field and forbids the other."""

    def test_a_highway_corridor_station_may_not_name_a_water_body(self):
        """A corridor station carrying water_body_id is a 422 and persists nothing.

        PRD: "Any other combination — an access station missing its water body or
        carrying a route code, a corridor station missing its route code or
        carrying a water body — is rejected with `ERR_STATION_SITING_INVALID`."

        Design: Corner/validations/violation_to_error_highway_station_carrying_a_water_body_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        water_body = create_water_body(risk_tier="HIGH")

        response = api_client.create_station(
            station_payload(
                name="I-90 Corridor", station_type="HIGHWAY_CORRIDOR",
                corridor_route_code="I-90-EB", water_body_id=water_body["id"],
            ),
            PROGRAM_ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_STATION_SITING_INVALID, 422)
        _rows, meta = validate_paginated(api_client.list_stations(PROGRAM_ADMIN))
        assert meta["total_count"] == 0

    def test_the_same_corridor_station_without_a_water_body_is_accepted(self):
        """Dropping water_body_id leaves a well-sited corridor checkpoint.

        PRD: "a `HIGHWAY_CORRIDOR` station must supply a non-null
        `corridor_route_code` and must leave `water_body_id` null."

        Design: Corner/validations/violation_to_error_highway_station_carrying_a_water_body_rejected
        """
        set_clock("2026-08-01T00:00:00Z")

        data = validate_success(
            api_client.create_station(
                station_payload(
                    name="I-90 Corridor", station_type="HIGHWAY_CORRIDOR",
                    corridor_route_code="I-90-EB",
                ),
                PROGRAM_ADMIN,
            ),
            201,
        )

        assert data["station_type"] == "HIGHWAY_CORRIDOR"
        assert data["corridor_route_code"] == "I-90-EB"
        assert data["water_body_id"] is None
        assert data["status"] == "PLANNED"

    def test_an_access_station_without_a_water_body_is_refused_on_the_same_rule(self):
        """The mirror violation draws the identical error.

        PRD: "A `WATERBODY_ACCESS` station must supply a non-null `water_body_id`
        and must leave `corridor_route_code` null"

        Design: Corner/validations/violation_to_error_highway_station_carrying_a_water_body_rejected
        """
        set_clock("2026-08-01T00:00:00Z")

        response = api_client.create_station(
            station_payload(name="Orphan Access", station_type="WATERBODY_ACCESS"),
            PROGRAM_ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_STATION_SITING_INVALID, 422)


def _two_water_bodies():
    """A headwater lake A and a river B that already drains into it."""
    set_clock("2026-08-01T00:00:00Z")
    lake = create_water_body(name="Flathead Lake", risk_tier="HIGH")
    river = create_water_body(
        name="Flathead River", water_body_class="RIVER", risk_tier="LOW",
        downstream_of_water_body_id=lake["id"],
    )
    return lake, river


class TestDrainageCorrectionMayNotCloseACycle:
    """The cycle check is re-run from the corrected row, and self-reference counts."""

    def test_pointing_the_lake_back_at_its_own_river_is_refused(self):
        """The two-hop loop is a 422 and the lake keeps its null parent.

        PRD: "Following that chain from the new or corrected water body must never
        arrive back at the same water body, and a water body may not name itself;
        either shape is rejected with `ERR_WATER_BODY_CYCLE`."

        Design: Corner/validations/violation_to_error_drainage_correction_that_revisits_the_same_water_body
        """
        lake, river = _two_water_bodies()
        assert lake["downstream_of_water_body_id"] is None
        assert river["downstream_of_water_body_id"] == lake["id"]

        response = api_client.patch_water_body(
            lake["id"],
            water_body_patch_payload(downstream_of_water_body_id=river["id"]),
            PROGRAM_ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_WATER_BODY_CYCLE, 422)
        after = fetch_water_body(lake["id"])
        assert after["downstream_of_water_body_id"] is None
        assert after["version"] == lake["version"]

    def test_a_self_reference_is_refused_on_the_same_rule(self):
        """Naming itself as its own drainage parent is the degenerate cycle.

        PRD: "a water body may not name itself; either shape is rejected with
        `ERR_WATER_BODY_CYCLE`."

        Design: Corner/validations/violation_to_error_drainage_correction_that_revisits_the_same_water_body
        """
        lake, _river = _two_water_bodies()

        response = api_client.patch_water_body(
            lake["id"],
            water_body_patch_payload(downstream_of_water_body_id=lake["id"]),
            PROGRAM_ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_WATER_BODY_CYCLE, 422)
        assert fetch_water_body(lake["id"])["version"] == lake["version"]

    def test_a_risk_tier_correction_is_accepted_and_leaves_the_posture_alone(self):
        """The narrow correction bumps the version and never touches infestation.

        PRD: "Correction after a survey is deliberately narrow: only
        `downstream_of_water_body_id` and `risk_tier` may be changed once the row
        exists, the drainage cycle check is re-run from the corrected water body,
        and the correction leaves `detection_count`, `live_detection_count` and
        `infestation_status` untouched while advancing the water body's `version`
        by 1."

        Design: Corner/validations/violation_to_error_drainage_correction_that_revisits_the_same_water_body
        """
        lake, _river = _two_water_bodies()

        data = validate_success(
            api_client.patch_water_body(
                lake["id"], water_body_patch_payload(risk_tier="MODERATE"),
                PROGRAM_ADMIN,
            ),
            200,
        )

        assert data["risk_tier"] == "MODERATE"
        assert data["version"] == lake["version"] + 1
        assert data["detection_count"] == 0
        assert data["live_detection_count"] == 0
        assert data["infestation_status"] == "CLEAN"


class TestDuplicateIdentifiersAreRefused:
    """Registration numbers and partner state codes are both globally unique."""

    def test_a_repeated_registration_number_is_refused(self):
        """The second MT-2001 is a 409 even though every other field differs.

        PRD: "A vessel is registered with its state `registration_number`
        (non-empty, at most 32 characters, and unique across the whole registry — a
        repeat is rejected with `ERR_DUPLICATE_IDENTIFIER`), the two-letter
        `home_state_code` of the state it is registered in, its hull class in
        `vessel_type`, and its `hull_length_ft` in feet, which must be greater than
        zero."

        Design: Corner/validations/violation_to_error_duplicate_registration_number_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        first = register_watercraft(
            registration_number="MT-2001", vessel_type="OPEN_HULL", hull_length_ft=16
        )

        response = api_client.create_watercraft(
            watercraft_payload(
                registration_number="MT-2001", home_state_code="WY",
                vessel_type="BALLASTED_WAKEBOAT", hull_length_ft=24,
            ),
            PROGRAM_ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
        rows, meta = validate_paginated(
            api_client.list_watercraft(PROGRAM_ADMIN, {"registration_number": "MT-2001"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["vessel_type"] == "OPEN_HULL"

    def test_a_repeated_partner_state_code_is_refused_on_the_same_rule(self):
        """A second ID agreement draws the identical error.

        PRD: "An agreement is created with the partner's two-letter
        `partner_state_code`, unique across agreements and likewise guarded by
        `ERR_DUPLICATE_IDENTIFIER`, and the `accepted_seal_prefix` (non-empty, at
        most 8 characters) that a seal number from that state must begin with
        before this program will look at it."

        Design: Corner/validations/violation_to_error_duplicate_registration_number_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        first = create_reciprocity_agreement(
            partner_state_code="ID", accepted_seal_prefix="ID-"
        )

        response = api_client.create_reciprocity_agreement(
            reciprocity_agreement_payload(
                partner_state_code="ID", accepted_seal_prefix="IDAHO-"
            ),
            PROGRAM_ADMIN,
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_IDENTIFIER, 409)
        rows, meta = validate_paginated(
            api_client.list_reciprocity_agreements(
                PROGRAM_ADMIN, {"partner_state_code": "ID"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["accepted_seal_prefix"] == "ID-"


def _record_awaiting_screening(*, risk_tier="MODERATE", with_agreement=True,
                               max_seal_age_hours=72, ctx=None):
    """An INITIATED record at a station on a clean water body, clock at arrival."""
    if ctx is None:
        ctx = setup_program(
            risk_tier=risk_tier, infestation_status="CLEAN", mandatory_inspection=True
        )
        if with_agreement:
            ctx["agreement"] = create_reciprocity_agreement(
                partner_state_code="ID", accepted_seal_prefix="ID-",
                honors_our_seals=True, max_seal_age_hours=max_seal_age_hours,
                fee_waiver=False,
            )
    ctx = setup_inspection(ctx, screen=False, arrived_at=ARRIVAL)
    set_clock(ARRIVAL)
    return ctx


def _screen(ctx, **fields):
    """Screen the context's current record as its owning inspector."""
    watercraft = fetch_watercraft(ctx["watercraft"]["id"])
    return api_client.screen_inspection_record(
        ctx["record"]["id"],
        screening_payload(watercraft["version"], **fields),
        make_inspector_headers(ctx["inspector_a"]["id"]),
    )


class TestPresentedSealPrefixMismatch:
    """A wrong prefix is an error; only a suspended agreement is silently ignored."""

    def test_a_seal_number_without_the_agreed_prefix_is_refused(self):
        """XX-99 against an ID- agreement is a 422 and nothing on the record moves.

        PRD: "First, `presented_seal_number` must begin with the agreement's
        `accepted_seal_prefix`, on an agreement that is active and whose
        `honors_our_seals` is true; a number that does not carry the prefix, or an
        agreement that does not reciprocate, is rejected with
        `ERR_SEAL_PREFIX_MISMATCH`."

        Design: Corner/validations/violation_to_error_presented_seal_prefix_mismatch_rejected
        """
        ctx = _record_awaiting_screening()
        vessel_version = fetch_watercraft(ctx["watercraft"]["id"])["version"]

        response = _screen(
            ctx, residual_water_present=False,
            prior_water_body_id=ctx["water_body"]["id"],
            presented_seal_number="XX-99", presented_seal_state_code="ID",
            presented_seal_issued_at="2026-08-04T09:00:00Z",
        )

        validate_error(response, ApiErrorId.ERR_SEAL_PREFIX_MISMATCH, 422)
        record = fetch_record(ctx["record"]["id"])
        assert record["inspection_status"] == "INITIATED"
        assert record["risk_score"] == 0
        assert record["reciprocity_seal_honored"] is False
        assert record["honored_agreement_id"] is None
        assert fetch_watercraft(ctx["watercraft"]["id"])["version"] == vessel_version

    def test_a_state_with_no_agreement_at_all_is_a_not_found(self):
        """A UT seal cannot be evaluated, so the screening is a 404.

        PRD: "If no agreement exists for that state code, the screening is
        rejected outright with `ERR_RECIPROCITY_AGREEMENT_NOT_FOUND`."

        Design: Corner/validations/violation_to_error_presented_seal_prefix_mismatch_rejected
        """
        ctx = _record_awaiting_screening()

        response = _screen(
            ctx, residual_water_present=False,
            prior_water_body_id=ctx["water_body"]["id"],
            presented_seal_number="UT-99", presented_seal_state_code="UT",
            presented_seal_issued_at="2026-08-04T09:00:00Z",
        )

        validate_error(response, ApiErrorId.ERR_RECIPROCITY_AGREEMENT_NOT_FOUND, 404)
        assert fetch_record(ctx["record"]["id"])["inspection_status"] == "INITIATED"

    def test_a_suspended_agreement_makes_the_same_seal_harmless(self):
        """With the agreement suspended the screening succeeds without the credit.

        PRD: "If the matched agreement is `SUSPENDED`, the seal is simply not
        honoured — this is not an error."

        Design: Corner/validations/violation_to_error_presented_seal_prefix_mismatch_rejected
        """
        ctx = _record_awaiting_screening()
        move_reciprocity_agreement(ctx["agreement"]["id"], "SUSPENDED")

        data = validate_success(
            _screen(
                ctx, residual_water_present=False,
                prior_water_body_id=ctx["water_body"]["id"],
                presented_seal_number="ID-99", presented_seal_state_code="ID",
                presented_seal_issued_at="2026-08-04T09:00:00Z",
            ),
            200,
        )

        assert data["inspection_status"] == "SCREENED"
        assert data["reciprocity_seal_honored"] is False
        assert data["honored_agreement_id"] is None
        assert data["risk_score"] == 20


class TestSealExactlyAtMaxAgeIsHonored:
    """Seal age is floored to hours, measured to arrived_at, and rejected only above."""

    def test_a_seal_exactly_seventy_two_hours_old_is_honored(self):
        """An age equal to max_seal_age_hours buys the full 20-point credit.

        PRD: "Second, the seal must not be too old: the seal's age in whole hours
        is the elapsed time from `presented_seal_issued_at` to the record's
        `arrived_at`, floored to a whole number of hours — the arrival instant,
        deliberately, and never the current logical time — and the screening is
        rejected with `ERR_SEAL_RECIPROCITY_EXPIRED` only when that age is strictly
        greater than the agreement's `max_seal_age_hours`. An age exactly equal to
        `max_seal_age_hours` is honoured."

        Design: Corner/validations/satisfaction_to_pass_seal_exactly_at_max_age_is_honored
        """
        ctx = _record_awaiting_screening()

        data = validate_success(
            _screen(
                ctx, residual_water_present=False,
                prior_water_body_id=ctx["water_body"]["id"],
                presented_seal_number="ID-72", presented_seal_state_code="ID",
                presented_seal_issued_at="2026-08-02T09:00:00Z",
            ),
            200,
        )

        assert data["reciprocity_seal_honored"] is True
        assert data["honored_agreement_id"] == ctx["agreement"]["id"]
        assert data["risk_score"] == 0
        assert data["risk_band"] == "LOW"

    def test_a_seal_seventy_three_hours_old_is_refused(self):
        """One hour past the ceiling is a 422 and the record stays INITIATED.

        PRD: "the screening is rejected with `ERR_SEAL_RECIPROCITY_EXPIRED` only
        when that age is strictly greater than the agreement's
        `max_seal_age_hours`."

        Design: Corner/validations/satisfaction_to_pass_seal_exactly_at_max_age_is_honored
        """
        ctx = _record_awaiting_screening()

        response = _screen(
            ctx, residual_water_present=False,
            prior_water_body_id=ctx["water_body"]["id"],
            presented_seal_number="ID-73", presented_seal_state_code="ID",
            presented_seal_issued_at="2026-08-02T08:00:00Z",
        )

        validate_error(response, ApiErrorId.ERR_SEAL_RECIPROCITY_EXPIRED, 422)
        record = fetch_record(ctx["record"]["id"])
        assert record["inspection_status"] == "INITIATED"
        assert record["reciprocity_seal_honored"] is False

    def test_presenting_no_seal_at_all_scores_the_bare_tier(self):
        """Without any seal fields the decision is trivially negative.

        PRD: "When the boater presents nothing — `presented_seal_number` is null —
        the decision is trivially negative: `reciprocity_seal_honored` is set
        false, `reciprocity_credit_points` is set to 0, `honored_agreement_id` is
        set null, and the decision stops there without consulting any agreement."

        Design: Corner/validations/satisfaction_to_pass_seal_exactly_at_max_age_is_honored
        """
        ctx = _record_awaiting_screening()

        data = validate_success(
            _screen(
                ctx, residual_water_present=False,
                prior_water_body_id=ctx["water_body"]["id"],
            ),
            200,
        )

        assert data["reciprocity_seal_honored"] is False
        assert data["honored_agreement_id"] is None
        assert data["risk_score"] == 20
        assert data["risk_band"] == "LOW"


def _vessel_recorded_at_another_lake():
    """A vessel whose registry entry names a HIGH lake, presented at a MODERATE one."""
    ctx = setup_program(
        risk_tier="MODERATE", infestation_status="CLEAN", mandatory_inspection=True
    )
    ctx["other_water_body"] = create_water_body(
        name="Flathead Lake", risk_tier="HIGH", infestation_status="CLEAN"
    )
    vessel = add_watercraft(ctx, ctx["other_water_body"]["id"])
    ctx = setup_inspection(ctx, screen=False, watercraft=vessel, arrived_at=ARRIVAL)
    set_clock(ARRIVAL)
    return ctx


class TestPriorWaterBodyMustAgreeWithTheRegistry:
    """A declared prior water body must match the recorded one, or be omitted."""

    def test_a_contradicting_declaration_is_refused(self):
        """Naming the station's own lake contradicts the registry and is a 422.

        PRD: "When it *is* supplied and the vessel already has a
        `last_water_body_id` on file, the two must agree, or the screening is
        rejected with `ERR_PRIOR_WATER_BODY_MISMATCH`."

        Design: Corner/validations/violation_to_error_prior_water_body_contradicts_the_registry_rejected
        """
        ctx = _vessel_recorded_at_another_lake()
        vessel_version = fetch_watercraft(ctx["watercraft"]["id"])["version"]

        response = _screen(
            ctx, residual_water_present=False,
            prior_water_body_id=ctx["water_body"]["id"],
        )

        validate_error(response, ApiErrorId.ERR_PRIOR_WATER_BODY_MISMATCH, 422)
        record = fetch_record(ctx["record"]["id"])
        assert record["prior_water_body_id"] is None
        assert record["inspection_status"] == "INITIATED"
        vessel = fetch_watercraft(ctx["watercraft"]["id"])
        assert vessel["last_water_body_id"] == ctx["other_water_body"]["id"]
        assert vessel["version"] == vessel_version

    def test_omitting_the_declaration_falls_back_to_the_registry(self):
        """The same call without the field scores the recorded HIGH lake at 40.

        PRD: "`prior_water_body_id` names the water body the boater declares the
        vessel last launched in; when it is omitted the service falls back to the
        vessel's recorded `last_water_body_id`, and when the vessel has none
        recorded and none is supplied the call is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/violation_to_error_prior_water_body_contradicts_the_registry_rejected
        """
        ctx = _vessel_recorded_at_another_lake()

        data = validate_success(_screen(ctx, residual_water_present=False), 200)

        assert data["prior_water_body_id"] == ctx["other_water_body"]["id"]
        assert data["risk_score"] == 40
        assert data["risk_band"] == "MODERATE"


class TestQuarantineRequiresAWarrant:
    """A mandatory decontamination does not by itself justify a seal."""

    def test_a_clean_water_body_leaves_a_high_band_record_unsealable(self):
        """quarantine_warranted false is a 409 and the seal shelf is untouched.

        PRD: "The record's `quarantine_warranted` must be true, or the issuance is
        rejected with `ERR_QUARANTINE_NOT_WARRANTED`."

        Design: Corner/validations/violation_to_error_quarantine_on_a_record_not_warranted_rejected
        """
        ctx = setup_decon_required(
            risk_tier="HIGH", infestation_status="CLEAN", seal_stock_initial_count=3,
            arrived_at=ARRIVAL, screen_at=ARRIVAL,
        )
        record = ctx["record"]
        assert record["risk_band"] == "HIGH"
        assert record["decon_mandatory"] is True
        assert record["quarantine_warranted"] is False

        response = api_client.create_quarantine_order(
            quarantine_order_payload(record["id"], "MT-SEAL-0001"),
            make_inspector_headers(ctx["inspector_a"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_QUARANTINE_NOT_WARRANTED, 409)
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 3
        assert station["seals_in_circulation_count"] == 0
        assert fetch_watercraft(ctx["watercraft"]["id"])["quarantine_hold_until"] is None
        _rows, meta = validate_paginated(
            api_client.list_quarantine_orders(PROGRAM_ADMIN)
        )
        assert meta["total_count"] == 0

    def test_a_confirmed_infested_water_body_makes_the_same_issuance_legal(self):
        """The infestation clause supplies the warrant and consumes one seal.

        PRD: "`quarantine_warranted` is true when the band is `EXTREME`, or when
        the prior water body's `infestation_status` is `CONFIRMED_INFESTED`."

        Design: Corner/validations/violation_to_error_quarantine_on_a_record_not_warranted_rejected
        """
        ctx = setup_decon_required(
            risk_tier="HIGH", infestation_status="CONFIRMED_INFESTED",
            seal_stock_initial_count=3, arrived_at=ARRIVAL, screen_at=ARRIVAL,
        )
        assert ctx["record"]["quarantine_warranted"] is True

        data = validate_success(
            api_client.create_quarantine_order(
                quarantine_order_payload(ctx["record"]["id"], "MT-SEAL-0001"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            201,
        )

        assert data["status"] == "SEALED"
        station = fetch_station(ctx["station"]["id"])
        assert station["seal_stock_count"] == 2
        assert station["seals_in_circulation_count"] == 1


def _flagged_vessel_screened_a_third_time():
    """A twice-refused, watchlisted vessel screened again with nothing found."""
    ctx = setup_inspection(
        risk_tier="LOW", infestation_status="CLEAN", mandatory_inspection=True,
        arrived_at=ARRIVAL, screen_at=ARRIVAL, residual_water_present=False,
        disposition="REFUSE",
    )
    ctx = setup_inspection(
        ctx, watercraft=ctx["watercraft"], arrived_at="2026-08-05T11:00:00Z",
        screen_at="2026-08-05T11:00:00Z", residual_water_present=False,
        disposition="REFUSE",
    )
    ctx = setup_inspection(
        ctx, watercraft=ctx["watercraft"], arrived_at="2026-08-05T13:00:00Z",
        screen_at="2026-08-05T13:00:00Z", residual_water_present=False,
    )
    return ctx


class TestPassRefusedWhileTheVesselCarriesTheDeconFlag:
    """The standing vessel obligation forces decon_mandatory on a 5-point screening."""

    def test_a_watchlisted_vessel_cannot_be_passed_from_a_low_band_screening(self):
        """The flag alone turns a LOW 5-point record into a 409 on PASS.

        PRD: "A pass is refused when the record's `decon_mandatory` is true, and
        equally when the vessel carries `mandatory_decon_flag` true, unless some
        decontamination order belonging to this record has already reached
        `VERIFIED`; the rejection is `ERR_DECON_REQUIRED_BEFORE_PASS`."

        Design: Corner/validations/conditional_validation_pass_refused_while_the_vessel_carries_the_decon_flag
        """
        ctx = _flagged_vessel_screened_a_third_time()
        vessel = fetch_watercraft(ctx["watercraft"]["id"])
        assert vessel["compliance_strikes"] == 2
        assert vessel["watchlist_status"] == "WATCHLISTED"
        assert vessel["mandatory_decon_flag"] is True
        third = ctx["record"]
        assert third["risk_score"] == 5
        assert third["risk_band"] == "LOW"
        assert third["decon_mandatory"] is True

        response = api_client.dispose_inspection_record(
            third["id"], disposition_payload("PASS"),
            make_inspector_headers(ctx["inspector_a"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_DECON_REQUIRED_BEFORE_PASS, 409)
        after = fetch_record(third["id"])
        assert after["inspection_status"] == "SCREENED"
        assert after["total_fee_cents"] == 0
        assert after["version"] == third["version"]
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 5000

    def test_only_the_pass_is_blocked_and_decon_is_still_available(self):
        """The identical record accepts DECON, so the ban is disposition-specific.

        PRD: "`SCREENED → DECON_REQUIRED` opens the decontamination pathway of
        §3.6 and leaves the record's fee open for the treatment charge still to
        come."

        Design: Corner/validations/conditional_validation_pass_refused_while_the_vessel_carries_the_decon_flag
        """
        ctx = _flagged_vessel_screened_a_third_time()

        data = validate_success(
            api_client.dispose_inspection_record(
                ctx["record"]["id"], disposition_payload("DECON"),
                make_inspector_headers(ctx["inspector_a"]["id"]),
            ),
            200,
        )

        assert data["inspection_status"] == "DECON_REQUIRED"
        assert data["total_fee_cents"] == 2500
        assert fetch_station(ctx["station"]["id"])["collected_fees_cents"] == 7500
