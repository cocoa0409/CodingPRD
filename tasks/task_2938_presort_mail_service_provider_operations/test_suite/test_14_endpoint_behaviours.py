"""Endpoint behaviours: an action, a computed read, a cross-reference, a
conditional action and a full create-then-settle cycle.

Each test drives one endpoint against a history built from an empty database and
then reads the state back through other endpoints, because an action that
reports the right body while leaving the wrong state behind is still wrong.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DOCK_CAPACITY_EXCEEDED,
    ERR_INVALID_INVOICE_STATE,
    ERR_MAIL_JOB_NOT_FOUND,
    ERR_OUTSIDE_APPOINTMENT_WINDOW,
    ERR_PAYMENT_AMOUNT_MISMATCH,
)
from test_helpers.assertions import (
    assert_batch_ledger,
    assert_cents,
    assert_container_state,
    assert_field_values,
    assert_invoice_figures,
    assert_job_state,
    assert_row_count,
    assert_version_unchanged,
)
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    BUREAU_ADMIN,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
    make_client_contact_headers,
)

# A morning appointment on 12 August, booked while the clock still reads
# 10 August: inclusive start, exclusive end.
MORNING_WINDOW_START = f.instant(2026, 8, 12, 8, 0, 0)
MORNING_WINDOW_END = f.instant(2026, 8, 12, 12, 0, 0)
AFTER_THE_MORNING_WINDOW = f.instant(2026, 8, 12, 13, 0, 0)

# One hour past the end of the canonical 08:00-to-16:00 appointment.
AFTER_THE_DEPOSIT_WINDOW = f.instant(2026, 8, 12, 17, 0, 0)

# A UUID that is well formed but names nothing at all.
ABSENT_MAIL_JOB_ID = "11111111-2222-3333-4444-555555555555"


def _deposited_canonical_world(api):
    """The canonical two-client batch inducted at 14:00 on 12 August."""
    world = fx.build_departed_world(api)
    validate_success(api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK))
    return world


class TestDepartureMovesTheLoadOntoTheRoad:
    """A four-pallet load on a dock that holds exactly four pallets a slot."""

    def _four_pallet_load_scheduled(self, api):
        fx.set_clock(api, fx.FIXTURE_CLOCK_UTC)
        facility = fx.setup_facility(api, dock_capacity_pallets_per_slot=4)
        batch_1 = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        batch_2 = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        shipment = fx.create_drop_shipment(
            api,
            f.drop_shipment_payload(
                batch_1["id"],
                facility["id"],
                MORNING_WINDOW_START,
                MORNING_WINDOW_END,
                pallet_count=4,
            ),
        )
        assert_field_values(
            shipment,
            {"status": "SCHEDULED", "pallet_count": 4, "version": 1},
        )
        assert shipment["deposited_at_utc"] is None
        return facility, batch_1, batch_2, shipment

    def test_departure_moves_the_shipment_in_transit_and_bumps_its_version(self, api):
        """Dispatch is one move and nothing more.

        "Dispatch is a simple move: a `PresortOperator` drives the load
        `SCHEDULED → IN_TRANSIT`, incrementing the shipment's `version`." Nothing is
        inducted yet, and the pool is untouched: the deposit is what stamps
        `deposited_at_utc`, since only "On success the shipment moves
        `IN_TRANSIT → DEPOSITED` and its `deposited_at_utc` is stamped from the
        logical clock."

        Design: Corner/endpoints/action_endpoint_depart_moves_the_shipment_to_in_transit
        """
        _facility, batch_1, _batch_2, shipment = self._four_pallet_load_scheduled(api)

        departed = validate_success(
            api.depart_drop_shipment(shipment["id"], PRESORT_OPERATOR)
        )
        assert_field_values(departed, {"status": "IN_TRANSIT", "version": 2})
        assert departed["deposited_at_utc"] is None

        after_batch = validate_success(
            api.get_commingle_batch(batch_1["id"], PRESORT_OPERATOR)
        )
        assert after_batch["status"] == "OPEN", (
            "driving the truck away does not induct the mail"
        )

    def test_a_departed_load_still_occupies_its_pallets(self, api):
        """A truck on the road has not released the dock.

        "To evaluate a booking, take every drop shipment at the same facility whose
        status is `SCHEDULED` or `IN_TRANSIT`; shipments in `CANCELLED`, `NO_SHOW` or
        `DEPOSITED` have released their pallets and take no part." "The booking is
        refused with `ERR_DOCK_CAPACITY_EXCEEDED` exactly when those occupied pallets
        plus the requested `pallet_count` are strictly greater than the facility's
        `dock_capacity_pallets_per_slot`; a total exactly equal to capacity is
        accepted."

        Design: Corner/endpoints/action_endpoint_depart_moves_the_shipment_to_in_transit
        """
        facility, _batch_1, batch_2, shipment = self._four_pallet_load_scheduled(api)
        fx.depart_drop_shipment(api, shipment["id"])

        validate_error(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    batch_2["id"],
                    facility["id"],
                    MORNING_WINDOW_START,
                    MORNING_WINDOW_END,
                    pallet_count=1,
                ),
                PRESORT_OPERATOR,
            ),
            ERR_DOCK_CAPACITY_EXCEEDED,
            409,
        )

    def test_the_clock_sweep_leaves_a_departed_load_alone(self, api):
        """Past the window end, the truck is late but not a no-show.

        "Shipments in `IN_TRANSIT` are exempt from the sweep — a truck on the road is
        not a no-show." "The response reports the new clock as `current_utc` together
        with `no_show_shipment_ids`, the array of identifiers of the shipments the
        advance just marked."

        Design: Corner/endpoints/action_endpoint_depart_moves_the_shipment_to_in_transit
        """
        _facility, _batch_1, _batch_2, shipment = self._four_pallet_load_scheduled(api)
        fx.depart_drop_shipment(api, shipment["id"])

        advance = validate_success(
            api.set_clock(AFTER_THE_MORNING_WINDOW, BUREAU_ADMIN)
        )
        assert advance["current_utc"] == AFTER_THE_MORNING_WINDOW
        assert advance["no_show_shipment_ids"] == [], (
            "the only shipment at this dock left in IN_TRANSIT, so nothing is swept"
        )

        after = validate_success(
            api.get_drop_shipment(shipment["id"], PRESORT_OPERATOR)
        )
        assert after["status"] == "IN_TRANSIT"


class TestStandalonePostageEstimateForOneJob:
    """What 1200 surviving pieces would cost with no pool behind them."""

    def _cleared_job_of_twelve_hundred(self, api):
        owner = fx.setup_client_with_permit(
            api,
            name="Estimator Mailings",
            client_code="ESTIM",
            permit_number="PI-360360",
            payment_method="METER",
        )
        job = fx.setup_cleared_job(
            api,
            owner.client_id,
            owner.permit_id,
            declared_piece_count=1250,
            submitted_piece_count=1250,
            cass_matched_count=1235,
            ncoa_move_updated_count=40,
            undeliverable_removed_count=50,
            move_update_age_days=30,
        )
        assert job.job["accepted_piece_count"] == 1200
        return owner, job

    def test_the_estimate_prices_the_jobs_own_pieces_with_no_entry_discount(self, api):
        """1200 pieces alone at the BASIC tier: 29440 mills and 35328 cents.

        "The estimate prices the job's own `accepted_piece_count` alone, using the
        same rate machinery as a pooled batch but with two differences. The presort
        tier is derived from that single job's piece count rather than from any pooled
        total, and the drop-ship discount in basis points is forced to zero, because
        an unpooled job is not tendered at an entry point on its own and therefore
        earns no entry discount." "For a 1200-piece `MARKETING_MAIL` job this prices
        at the `BASIC` tier with a `standalone_rate_mills_per_piece` of 29440 — 29.44
        cents a piece."

        Design: Corner/endpoints/computed_read_standalone_postage_estimate_for_one_job
        """
        owner, job = self._cleared_job_of_twelve_hundred(api)

        estimate = validate_success(
            api.get_postage_estimate(
                job.job_id, make_client_contact_headers(owner.client_id)
            )
        )
        assert_field_values(
            estimate,
            {
                "piece_count": 1200,
                "standalone_tier": "BASIC",
                "standalone_rate_mills_per_piece": 29440,
                "standalone_postage_cents": 35328,
            },
        )
        assert estimate["standalone_rate_mills_per_piece"] == (
            32 * 1000 * (10000 - 800) * (10000 - 0) // 100_000_000
        ), "the entry factor is forced to a full ten thousand for a standalone job"

    def test_the_estimate_persists_nothing_on_the_job(self, api):
        """A quotation is not a charge.

        "The response reports `piece_count`, the resulting `standalone_tier`, the
        resulting `standalone_rate_mills_per_piece`, and the resulting
        `standalone_postage_cents`; nothing is persisted."

        Design: Corner/endpoints/computed_read_standalone_postage_estimate_for_one_job
        """
        owner, job = self._cleared_job_of_twelve_hundred(api)
        before = validate_success(api.get_mail_job(job.job_id, PRESORT_OPERATOR))

        validate_success(
            api.get_postage_estimate(
                job.job_id, make_client_contact_headers(owner.client_id)
            )
        )

        after = validate_success(api.get_mail_job(job.job_id, PRESORT_OPERATOR))
        assert_job_state(
            after,
            status="HYGIENE_CLEARED",
            accepted_piece_count=1200,
            postage_due_cents=0,
            commingle_batch_id=None,
        )
        assert_version_unchanged(before, after)


class TestMemberAddBindsJobAndBatchBothWays:
    """The junction row, seen from the job and seen from the pool."""

    def _one_cleared_job_and_one_open_pool(self, api):
        owner = fx.setup_client_with_permit(
            api,
            name="Linkage Mail Works",
            client_code="LINKS",
            permit_number="PI-370370",
            payment_method="METER",
        )
        facility = fx.setup_facility(api)
        job = fx.setup_cleared_job(
            api, owner.client_id, owner.permit_id, declared_piece_count=1000
        )
        batch = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        return owner, job, batch

    def test_pooling_a_job_that_does_not_exist_is_a_not_found(self, api):
        """The body identifier is resolved before anything is pooled.

        "Foreign keys arriving in a request *body* are resolved after path identifiers,
        and among themselves they are resolved in the order the endpoint lists them:
        `client_id` first, then `permit_account_id`, then `entry_facility_id`, then
        `commingle_batch_id`, then `mail_job_id`." The mapping is fixed: "a `mail_job_id`
        yields `ERR_MAIL_JOB_NOT_FOUND`".

        Design: Corner/endpoints/cross_reference_link_member_add_binds_job_to_batch_both_ways
        """
        _owner, _job, batch = self._one_cleared_job_and_one_open_pool(api)

        validate_error(
            api.add_batch_member(
                batch["id"],
                f.batch_member_payload(ABSENT_MAIL_JOB_ID),
                PRESORT_OPERATOR,
            ),
            ERR_MAIL_JOB_NOT_FOUND,
            404,
        )

        after_batch = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            after_batch, member_job_count=0, total_piece_count=0, container_count=0
        )

    def test_the_membership_is_reachable_from_the_job_and_from_the_pool(self, api):
        """One junction row, two ways to walk to it.

        "A successful pooling creates a **batch member** — the junction row that makes
        the job-to-batch relationship many-to-many over time — carrying the
        `commingle_batch_id` of the pool and the `mail_job_id` of the job." From the
        job's side, "The second read lists the commingle memberships the job holds,
        each carrying that membership's allocated postage share"; from the pool's side,
        "A batch's members can be listed with their pro-rata shares". The job also
        keeps a direct pointer: "The job itself moves `HYGIENE_CLEARED → POOLED` and
        has its denormalized `commingle_batch_id` pointer set to the batch."

        Design: Corner/endpoints/cross_reference_link_member_add_binds_job_to_batch_both_ways
        """
        _owner, job, batch = self._one_cleared_job_and_one_open_pool(api)

        member = validate_success(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job.job_id), PRESORT_OPERATOR
            ),
            201,
        )
        assert_field_values(
            member,
            {
                "mail_job_id": job.job_id,
                "commingle_batch_id": batch["id"],
                "contributed_piece_count": 1000,
            },
        )

        from_the_job, job_meta = validate_paginated(
            api.list_job_batch_memberships(job.job_id, PRESORT_OPERATOR)
        )
        assert_row_count(from_the_job, 1, what="memberships held by the job")
        assert from_the_job[0]["id"] == member["id"]
        assert job_meta["total_count"] == 1

        from_the_pool, pool_meta = validate_paginated(
            api.list_batch_members(batch["id"], PRESORT_OPERATOR)
        )
        assert_row_count(from_the_pool, 1, what="members attached to the pool")
        assert from_the_pool[0]["id"] == member["id"]
        assert pool_meta["total_count"] == 1

        after_job = validate_success(api.get_mail_job(job.job_id, PRESORT_OPERATOR))
        assert_job_state(
            after_job, status="POOLED", commingle_batch_id=batch["id"]
        )


class TestDepositOnlyInsideTheAppointmentWindow:
    """A truck that arrives an hour after its 08:00-to-16:00 window closed."""

    def _departed_load_past_its_window(self, api):
        world = fx.build_departed_world(api)
        advance = validate_success(
            api.set_clock(AFTER_THE_DEPOSIT_WINDOW, BUREAU_ADMIN)
        )
        return world, advance

    def test_a_late_arrival_cannot_be_deposited(self, api):
        """The window is closed at both ends, and 17:00 is outside it.

        "The shipment must be in `IN_TRANSIT`, its batch must be in `DOCUMENTED`, that
        batch must have a statement in `ACCEPTED_CLEAN` or `ACCEPTED_WITH_ADJUSTMENT` —
        otherwise `ERR_STATEMENT_NOT_ACCEPTED` — and the logical clock must lie inside
        the appointment window treated as a closed interval, at or after
        `window_start_utc` and at or before `window_end_utc`, otherwise
        `ERR_OUTSIDE_APPOINTMENT_WINDOW`."

        Design: Corner/endpoints/conditional_action_deposit_only_inside_the_appointment_window
        """
        world, _advance = self._departed_load_past_its_window(api)

        validate_error(
            api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK),
            ERR_OUTSIDE_APPOINTMENT_WINDOW,
            422,
        )

        shipment = validate_success(
            api.get_drop_shipment(world.shipment_id, PRESORT_OPERATOR)
        )
        assert_field_values(shipment, {"status": "IN_TRANSIT"})
        assert shipment["deposited_at_utc"] is None

    def test_the_refused_deposit_fires_none_of_the_four_cascade_links(self, api):
        """No batch closes, no container is inducted, no job is mailed.

        "A partial cascade is never an acceptable outcome: if any precondition of the
        driving operation fails, nothing at all changes." Each link the deposit would
        otherwise have driven stays where it was: "Link 1: the batch moves
        `DOCUMENTED → CLOSED`, which is terminal for a batch. Link 2, caused by link 1:
        every container of the batch still in `DOCUMENTED` moves
        `DOCUMENTED → DEPOSITED`, which is terminal for a container." "Link 4, caused
        by link 3: each newly mailed job's `accepted_piece_count` is added to that
        job's client's `lifetime_pieces_mailed`."

        Design: Corner/endpoints/conditional_action_deposit_only_inside_the_appointment_window
        """
        world, advance = self._departed_load_past_its_window(api)
        assert advance["no_show_shipment_ids"] == [], (
            "the load is already IN_TRANSIT, so the clock advance sweeps nothing"
        )

        validate_error(
            api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK),
            ERR_OUTSIDE_APPOINTMENT_WINDOW,
            422,
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert batch["status"] == "DOCUMENTED"

        container = validate_success(
            api.get_sort_container(world.container_1_id, PRESORT_OPERATOR)
        )
        assert_container_state(
            container,
            status="DOCUMENTED",
            qualifies=True,
            placard_id="SCF-021-021-0",
            sequence_index=0,
        )

        job_a = validate_success(api.get_mail_job(world.job_a_id, PRESORT_OPERATOR))
        assert_job_state(job_a, status="PRESORTED")
        assert job_a["mailed_at_utc"] is None

        records, meta = validate_paginated(
            api.list_container_service_level_records(
                world.container_1_id, ACCEPTANCE_CLERK
            )
        )
        assert_row_count(records, 0, what="service-level records")
        assert meta["total_count"] == 0

        acme = validate_success(api.get_client(world.acme_id, POSTAGE_MANAGER))
        assert acme["lifetime_pieces_mailed"] == 0


class TestInvoiceIssueThenExactPaymentSettlesIt:
    """August billed for one mailed job, then paid to the cent."""

    def test_issuing_the_invoice_prices_the_period_and_drains_the_ledger(self, api):
        """1200 billed pieces, 31660 cents of postage and the 2500-cent floor.

        "First, select the client's jobs that are in `MAILED` and whose
        `mailed_at_utc` falls inside the requested period treated as closed at both
        ends, ordered by `created_at` ascending." "The invoice's `postage_cents` is the
        sum of `allocated_postage_cents` over those members, its `adjustment_cents` is
        the sum of `allocated_adjustment_cents` over the same members, its
        `billed_piece_count` is the sum of `accepted_piece_count` over the selected
        jobs, and its `included_job_count` is the number of jobs selected." Two whole
        thousands at 900 cents each is a gross fee of 1800, and "The invoice's
        `service_fee_cents` is then the greater of the bureau's minimum charge of 2500
        cents and that discounted fee." "Finally `total_cents` is `postage_cents` plus
        `adjustment_cents` plus `service_fee_cents`." Issuing also settles the ledger:
        "The client's `unbilled_postage_cents` decreases by the invoice's
        `postage_cents` plus its `adjustment_cents`." "Every included job moves
        `MAILED → BILLED` with its `version` incremented".

        Design: Corner/endpoints/standard_crud_invoice_issue_then_exact_payment_settles_it
        """
        world = _deposited_canonical_world(api)
        before_client = validate_success(
            api.get_client(world.acme_id, POSTAGE_MANAGER)
        )
        assert_cents(
            before_client, "unbilled_postage_cents", fx.MEMBER_A_POSTAGE_CENTS
        )

        invoice = validate_success(
            api.create_client_invoice(
                world.acme_id, f.invoice_payload(), POSTAGE_MANAGER
            ),
            201,
        )
        assert_invoice_figures(
            invoice,
            status="ISSUED",
            billed_piece_count=fx.JOB_A_ACCEPTED,
            included_job_count=1,
            postage_cents=fx.MEMBER_A_POSTAGE_CENTS,
            adjustment_cents=0,
            service_fee_cents=2500,
            total_cents=34160,
        )
        assert_cents(invoice, "paid_amount_cents", 0)

        after_client = validate_success(api.get_client(world.acme_id, POSTAGE_MANAGER))
        assert_cents(after_client, "unbilled_postage_cents", 0)

        after_job = validate_success(api.get_mail_job(world.job_a_id, POSTAGE_MANAGER))
        assert_job_state(after_job, status="BILLED")

    def test_only_the_exact_total_settles_the_invoice_and_only_once(self, api):
        """A cent short is refused; the exact figure pays; a replay is refused.

        "A `PostageManager` records a payment against an invoice in `ISSUED` by
        supplying an `amount_cents` that must equal the invoice's `total_cents`
        exactly; any other figure is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`, and a
        second payment against an already-`PAID` invoice is rejected with
        `ERR_INVALID_INVOICE_STATE`." "On success the invoice moves `ISSUED → PAID`,
        its `paid_amount_cents` is set to the `amount_cents` paid, and its `version`
        increments."

        Design: Corner/endpoints/standard_crud_invoice_issue_then_exact_payment_settles_it
        """
        world = _deposited_canonical_world(api)
        invoice = validate_success(
            api.create_client_invoice(
                world.acme_id, f.invoice_payload(), POSTAGE_MANAGER
            ),
            201,
        )

        validate_error(
            api.pay_client_invoice(
                invoice["id"], f.payment_payload(34159), POSTAGE_MANAGER
            ),
            ERR_PAYMENT_AMOUNT_MISMATCH,
            422,
        )
        still_issued = validate_success(
            api.get_client_invoice(invoice["id"], POSTAGE_MANAGER)
        )
        assert still_issued["status"] == "ISSUED"
        assert_cents(still_issued, "paid_amount_cents", 0)

        paid = validate_success(
            api.pay_client_invoice(
                invoice["id"], f.payment_payload(34160), POSTAGE_MANAGER
            )
        )
        assert paid["status"] == "PAID"
        assert_cents(paid, "paid_amount_cents", 34160)

        validate_error(
            api.pay_client_invoice(
                invoice["id"], f.payment_payload(34160), POSTAGE_MANAGER
            ),
            ERR_INVALID_INVOICE_STATE,
            409,
        )
