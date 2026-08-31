"""The deep cascades, the conserved energy ledger, and the top of the rejection
ladder: authentication and role permission."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    alarm_reading_payload,
    approx_2dp,
    assert_energy_balance_read,
    create_plant_payload,
    create_site_payload,
    fixtures,
    no_auth_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWellfieldShortfallCascade:
    def test_one_alarm_reading_isolates_the_well_and_starves_the_plant_into_flaring(
        self, api, technician_headers, operator_headers
    ):
        """PRD §2.9: "The **wellfield-shortfall cascade** starts at a tuning reading that
        alarms or throttles a well. The well's credited flow drops, which changes the
        site's collected flow, which can drop a plant below its minimum feed, which forces
        that plant from upgrading to flaring, which diverts every in-flight injection
        batch of that plant to the flare, which curtails whatever nominations those
        batches were attached to. That is five hops from one field reading, and every hop
        is mandatory."
        PRD §3.4: "When it fires **automatically**, three additional things happen that a
        manual switch does not do: the plant's `spec_status` is forced to `OFF_SPEC`, and
        a downtime record is opened for this plant with `cause` set to
        `WELLFIELD_SHORTFALL`, `disposition` set to `FLARED`, `start_at` set to
        `current_utc`, `status` `OPEN`, and `auto_generated` set to true."

        Design: Difficulty/transitive_cascade/alarm_reading_cascades_well_site_plant_batch_nomination
        """
        context = fixtures.setup_nominated_batch()
        site_id = context["site"]["id"]
        plant_id = context["plant"]["id"]
        well_one, well_two = context["wells"]

        reading = validate_success(
            api.create_reading(
                well_one["id"],
                alarm_reading_payload("2026-08-10T06:00:00Z"),
                technician_headers,
            ),
            201,
        )
        assert reading["quality_class"] == "ALARM"
        assert reading["air_intrusion_index"] == approx_2dp(17.70)

        isolated = fixtures.read_well(well_one["id"])
        assert isolated["operating_state"] == "ISOLATED"
        assert isolated["current_flow_scfm"] == approx_2dp(0.0)

        site = fixtures.read_site(site_id)
        assert site["collected_flow_scfm"] == approx_2dp(470.0)
        assert site["collection_efficiency_pct"] == approx_2dp(47.0)

        plant = fixtures.read_plant(plant_id)
        assert plant["process_mode"] == "FLARING"
        assert plant["spec_status"] == "OFF_SPEC"

        rows, meta = validate_paginated(
            api.list_downtime_events(
                operator_headers,
                params={"plant_id": plant_id, "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        outage = rows[0]
        assert outage["cause"] == "WELLFIELD_SHORTFALL"
        assert outage["disposition"] == "FLARED"
        assert outage["status"] == "OPEN"
        assert outage["auto_generated"] is True

        untouched = fixtures.read_well(well_two["id"])
        assert untouched["operating_state"] == "ONLINE"
        assert untouched["current_flow_scfm"] == approx_2dp(470.0)

    def test_the_shortfall_cascade_diverts_the_in_flight_batch_and_curtails_its_nomination(
        self, api, technician_headers
    ):
        """PRD §3.4: "In **both** cases, every injection batch of this plant whose
        `status` is `DRAFT`, `PENDING_ANALYSIS`, `ON_SPEC` or `NOMINATED` is diverted to
        the flare; each such divert credits the site's `energy_produced_mmbtu` and
        `energy_flared_mmbtu` by that batch's `gross_mmbtu`, and any nomination such a
        batch was attached to is curtailed from `CONFIRMED` or `SCHEDULED` to
        `CURTAILED`"
        PRD §3.2: "If the recomputed collected flow has fallen below the `min_feed_scfm`
        of any plant of that site that is currently upgrading, that plant is forced out of
        upgrading and into flaring, with all the consequences described in §3.4 — five
        hops in total, from one technician's handheld reading to a curtailed pipeline
        nomination."

        Design: Difficulty/transitive_cascade/alarm_reading_cascades_well_site_plant_batch_nomination
        """
        context = fixtures.setup_nominated_batch()
        site_id = context["site"]["id"]
        batch_id = context["batch"]["id"]
        nomination_id = context["nomination"]["id"]
        assert context["batch"]["status"] == "NOMINATED"

        api.create_reading(
            context["wells"][0]["id"],
            alarm_reading_payload("2026-08-10T06:00:00Z"),
            technician_headers,
        )

        assert fixtures.read_injection_batch(batch_id)["status"] == "DIVERTED_TO_FLARE"

        nomination = fixtures.read_nomination(nomination_id)
        assert nomination["status"] == "CURTAILED"
        assert nomination["committed_dth"] == approx_2dp(0.0)

        site = fixtures.read_site(site_id)
        assert site["energy_flared_mmbtu"] == approx_2dp(340.14)
        assert site["energy_produced_mmbtu"] == approx_2dp(340.14)
        assert site["energy_injected_mmbtu"] == approx_2dp(0.0)


class TestConservedEnergyLedger:
    def test_diverting_a_batch_credits_the_produced_and_flared_buckets(self, api):
        """PRD §2.8: "The first is energy. `energy_produced_mmbtu` is the running total
        of all landfill-gas energy the site has accounted for, and it must always equal
        the sum of `energy_injected_mmbtu`, `energy_flared_mmbtu` and
        `energy_vented_mmbtu`."
        PRD §2.8: "A dedicated computed read exposes this as `balance_ok`, true when
        `energy_produced_mmbtu` rounded to two decimal places equals the sum of the other
        three rounded to two decimal places."
        PRD §3.7: "The site's `energy_produced_mmbtu` and `energy_flared_mmbtu` each rise
        by the batch's `gross_mmbtu`, and when the batch had been attached to a
        nomination, that nomination's `committed_dth` falls by the same figure and the
        nomination is curtailed from `CONFIRMED` or `SCHEDULED` to `CURTAILED`."

        Design: Difficulty/compensating_invariant/site_energy_mmbtu_conserved_across_divert_and_void
        """
        context = fixtures.setup_on_spec_batch()
        site_id = context["site"]["id"]
        assert context["batch"]["gross_mmbtu"] == approx_2dp(340.14)

        fixtures.divert_batch(context["batch"]["id"])

        balance = fixtures.read_energy_balance(site_id)
        assert_energy_balance_read(balance)
        assert balance["energy_produced_mmbtu"] == approx_2dp(340.14)
        assert balance["energy_flared_mmbtu"] == approx_2dp(340.14)
        assert balance["energy_injected_mmbtu"] == approx_2dp(0.0)
        assert balance["energy_vented_mmbtu"] == approx_2dp(0.0)
        assert balance["balance_ok"] is True

    def test_voiding_a_diverted_batch_debits_exactly_the_pair_the_divert_credited(
        self, api, operator_headers
    ):
        """PRD §3.7: "Voiding a batch that had been diverted debits
        `energy_produced_mmbtu` and `energy_flared_mmbtu` by its `gross_mmbtu` — exactly
        the pair the divert credited, which is why the energy identity holds either side
        of the operation."
        PRD §2.8: "Every forward action credits `energy_produced_mmbtu` and exactly one
        destination bucket — a batch reaching the pipeline credits injected, a batch sent
        to the flare credits flared, a closed downtime record credits flared and vented by
        the amounts booked on it — and every compensating action debits precisely the same
        pair it credited."

        Design: Difficulty/compensating_invariant/site_energy_mmbtu_conserved_across_divert_and_void
        """
        context = fixtures.setup_on_spec_batch()
        site_id = context["site"]["id"]
        batch_id = context["batch"]["id"]
        fixtures.divert_batch(batch_id)

        voided = validate_success(
            api.set_injection_batch_status(
                batch_id,
                {
                    "to_status": "VOIDED",
                    "void_reason": "Chromatograph calibration error - batch withdrawn",
                },
                operator_headers,
            )
        )
        assert voided["status"] == "VOIDED"

        balance = fixtures.read_energy_balance(site_id)
        assert_energy_balance_read(balance)
        assert balance["energy_produced_mmbtu"] == approx_2dp(0.0)
        assert balance["energy_flared_mmbtu"] == approx_2dp(0.0)
        assert balance["energy_injected_mmbtu"] == approx_2dp(0.0)
        assert balance["energy_vented_mmbtu"] == approx_2dp(0.0)
        assert balance["balance_ok"] is True, "no residual drift after the compensation"


class TestAccessLadder:
    def test_a_request_carrying_no_identity_headers_is_unauthenticated(
        self, api, admin_headers
    ):
        """PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`,
        identifying the caller, and `X-User-Role`, naming the authority the caller is
        acting under. If either header is absent, or if `X-User-Role` holds a value that
        is not one of the seven declared roles, the request is rejected with
        `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD §2.5: "**Authentication (priority 10).** Both headers present and the role
        recognised, or `ERR_UNAUTHENTICATED`. Applies to every endpoint."

        Design: Corner/validations/request_missing_x_user_role_header_returns_unauthenticated
        """
        site = validate_success(
            api.create_site(create_site_payload(), admin_headers), 201
        )

        validate_error(
            api.get_site(site["id"], no_auth_headers()),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
        )

    def test_the_role_check_is_reported_before_the_path_lookup(
        self, api, admin_headers, technician_headers
    ):
        """PRD §2.5: "**Role permission (priority 20).** The acting role appears in the
        endpoint's permitted list, or `ERR_ROLE_NOT_PERMITTED`. Applies to every
        endpoint."
        PRD §2.5: "**Path existence (priority 30).** Every resource identifier in the URL
        path resolves, validated left to right, or the not-found error naming that
        resource type: `ERR_SITE_NOT_FOUND`, `ERR_WELL_NOT_FOUND`,
        `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`, `ERR_DOWNTIME_EVENT_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`,
        `ERR_INJECTION_BATCH_NOT_FOUND`, `ERR_ATTRIBUTE_BATCH_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND` or `ERR_ROYALTY_STATEMENT_NOT_FOUND`, each with HTTP 404."

        Design: Corner/validations/role_check_beats_path_existence_returns_forbidden
        """
        validate_success(api.create_site(create_site_payload(), admin_headers), 201)

        error = validate_error(
            api.get_royalty_statement(NON_EXISTENT_UUID, technician_headers),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        assert error["error_id"] != ApiErrorId.ERR_ROYALTY_STATEMENT_NOT_FOUND.value, (
            "the authorization gate runs before the lookup"
        )

    def test_a_wellfield_technician_may_not_register_a_processing_plant(
        self, api, admin_headers, technician_headers
    ):
        """PRD §3.4: "A `ProjectAdmin` registers an upgrading skid — a
        `ProcessingPlant` — against a site by supplying the owning `site_id`, an operator
        label `plant_code` of at most 20 characters, the `receipt_point_code` of the
        pipeline interconnect it injects into (at most 20 characters), the
        `receipt_point_mdq_dth_per_day` that interconnect will accept in dekatherms per
        day, which must be greater than zero, and the `min_feed_scfm` — the minimum site
        collected flow required to sustain upgrading — which must also be greater than
        zero."
        PRD §2.1: "When the acting role is not listed among the roles permitted for the
        endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` and
        HTTP 403."

        Design: Corner/rbac/wellfield_technician_cannot_register_a_processing_plant
        """
        site = validate_success(
            api.create_site(create_site_payload(), admin_headers), 201
        )

        validate_error(
            api.create_plant(create_plant_payload(site["id"]), technician_headers),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )

        _, meta = validate_paginated(
            api.list_plants(
                admin_headers, params={"site_id": site["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 0
