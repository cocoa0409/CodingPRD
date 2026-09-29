"""The refusal catalogue: which code comes back, and what it leaves behind.

A refusal is part of the contract, not an accident, so each family of failure is
exercised for its own code and its own HTTP status: every path identifier has its
own 404, every natural key its own 409, every ill-formed interval its own 400,
and every gate that reads state outside the request body its own conflict. Each
refusal is also checked for the absence of side effects, because a rejection that
half-writes is worse than one that answers the wrong code.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BATCH_MEMBER_NOT_FOUND,
    ERR_BATCH_NOT_FOUND,
    ERR_CLIENT_NOT_FOUND,
    ERR_CLIENT_SUSPENDED,
    ERR_CONTAINER_NOT_FOUND,
    ERR_DELIVERY_ALREADY_SCANNED,
    ERR_DROP_SHIPMENT_NOT_FOUND,
    ERR_DUPLICATE_CLIENT_CODE,
    ERR_DUPLICATE_FACILITY_CODE,
    ERR_DUPLICATE_PERMIT_NUMBER,
    ERR_ENTRY_FACILITY_NOT_FOUND,
    ERR_INTERVAL_INVALID,
    ERR_INVOICE_NOT_FOUND,
    ERR_JOB_ALREADY_POOLED,
    ERR_NO_BILLABLE_JOBS,
    ERR_PERMIT_ACCOUNT_NOT_FOUND,
    ERR_PERMIT_ANNUAL_FEE_LAPSED,
    ERR_PERMIT_HAS_RESERVED_FUNDS,
    ERR_PROCESSING_CATEGORY_MISMATCH,
    ERR_SERVICE_LEVEL_RECORD_NOT_FOUND,
    ERR_SHIPMENT_ALREADY_SCHEDULED,
    ERR_SHIPMENT_WINDOW_IN_PAST,
    ERR_STATEMENT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_batch_ledger,
    assert_field_values,
    assert_job_state,
    assert_permit_funds,
    assert_row_count,
    assert_service_level_index,
    assert_unchanged,
    assert_version_unchanged,
)
from test_helpers.constants import FIXTURE_CLOCK_UTC
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    BUREAU_ADMIN,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
)


# One read per path-identifier family, each addressed with an identifier that
# resolves to nothing at all.
PATH_ID_READS = [
    ("client_id", ERR_CLIENT_NOT_FOUND, lambda api, unknown: api.get_client(unknown, BUREAU_ADMIN)),
    (
        "permit_account_id",
        ERR_PERMIT_ACCOUNT_NOT_FOUND,
        lambda api, unknown: api.get_permit_account(unknown, POSTAGE_MANAGER),
    ),
    (
        "commingle_batch_id",
        ERR_BATCH_NOT_FOUND,
        lambda api, unknown: api.get_commingle_batch(unknown, PRESORT_OPERATOR),
    ),
    (
        "sort_container_id",
        ERR_CONTAINER_NOT_FOUND,
        lambda api, unknown: api.get_sort_container(unknown, PRESORT_OPERATOR),
    ),
    (
        "entry_facility_id",
        ERR_ENTRY_FACILITY_NOT_FOUND,
        lambda api, unknown: api.get_entry_facility(unknown, BUREAU_ADMIN),
    ),
    (
        "postage_statement_id",
        ERR_STATEMENT_NOT_FOUND,
        lambda api, unknown: api.get_postage_statement(unknown, POSTAGE_MANAGER),
    ),
    (
        "drop_shipment_id",
        ERR_DROP_SHIPMENT_NOT_FOUND,
        lambda api, unknown: api.get_drop_shipment(unknown, PRESORT_OPERATOR),
    ),
    (
        "service_level_record_id",
        ERR_SERVICE_LEVEL_RECORD_NOT_FOUND,
        lambda api, unknown: api.get_service_level_record(unknown, ACCEPTANCE_CLERK),
    ),
    (
        "client_invoice_id",
        ERR_INVOICE_NOT_FOUND,
        lambda api, unknown: api.get_client_invoice(unknown, POSTAGE_MANAGER),
    ),
]


class TestNotFoundFamilyForEveryPathId:
    """Ten addressable families, ten distinct 404 codes."""

    @pytest.mark.parametrize(
        "path_id_name, expected_error, read",
        PATH_ID_READS,
        ids=[row[0] for row in PATH_ID_READS],
    )
    def test_each_unresolvable_path_identifier_answers_its_own_code(
        self, api, path_id_name, expected_error, read
    ):
        """A single shared not-found code would fail every one of these reads.

        "The mapping from an unresolvable identifier to its error is fixed: a
        `client_id` yields `ERR_CLIENT_NOT_FOUND`, a `permit_account_id` yields
        `ERR_PERMIT_ACCOUNT_NOT_FOUND`, a `mail_job_id` yields
        `ERR_MAIL_JOB_NOT_FOUND`, a `commingle_batch_id` yields
        `ERR_BATCH_NOT_FOUND`, a `batch_member_id` yields
        `ERR_BATCH_MEMBER_NOT_FOUND`, a `sort_container_id` yields
        `ERR_CONTAINER_NOT_FOUND`, an `entry_facility_id` yields
        `ERR_ENTRY_FACILITY_NOT_FOUND`, a `postage_statement_id` yields
        `ERR_STATEMENT_NOT_FOUND`, a `drop_shipment_id` yields
        `ERR_DROP_SHIPMENT_NOT_FOUND`, a `service_level_record_id` yields
        `ERR_SERVICE_LEVEL_RECORD_NOT_FOUND`, and a `client_invoice_id` yields
        `ERR_INVOICE_NOT_FOUND`. All of these are HTTP 404."

        Design: Corner/errors/not_found_family_for_every_path_id_in_the_catalog
        """
        facility = fx.setup_facility(api)
        fx.create_batch(api, f.commingle_batch_payload(facility["id"]))

        validate_error(read(api, NON_EXISTENT_UUID), expected_error, expected_status=404)

    def test_an_unknown_member_under_a_real_batch_names_the_member(self, api):
        """The batch in the path resolves, so the miss is reported on the child.

        "Resolving a nested identifier is not enough on its own: the child must
        actually belong to the parent named earlier in the path. Withdrawing a
        batch member is the case where this bites — if the `BatchMember` addressed
        by `batch_member_id` exists but its `commingle_batch_id` is some other
        batch than the `commingle_batch_id` in the path, the request is rejected
        with `ERR_BATCH_MEMBER_NOT_FOUND` rather than being allowed to operate
        across batch boundaries."

        Design: Corner/errors/not_found_family_for_every_path_id_in_the_catalog
        """
        facility = fx.setup_facility(api)
        batch = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))

        validate_error(
            api.remove_batch_member(batch["id"], NON_EXISTENT_UUID, PRESORT_OPERATOR),
            ERR_BATCH_MEMBER_NOT_FOUND,
            expected_status=404,
        )

        members, meta = validate_paginated(
            api.list_batch_members(batch["id"], PRESORT_OPERATOR)
        )
        assert_row_count(members, 0, "batch members")
        assert meta["total_count"] == 0
        after = validate_success(api.get_commingle_batch(batch["id"], PRESORT_OPERATOR))
        assert_field_values(after, {"status": "OPEN", "member_job_count": 0})
        assert_version_unchanged(batch, after)


def _build_duplicate_key_world(api):
    """Client DUPE holding permit PI-380380, a second client OTHER, and the
    SCF-021 entry facility — one existing holder for each of the three globally
    unique natural keys."""
    world = fx.World()
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    dupe = fx.setup_client_with_permit(
        api,
        name="Duplicate Mailers",
        client_code="DUPE",
        permit_number="PI-380380",
        payment_method="METER",
    )
    world.client = dupe.client
    world.client_id = dupe.client_id
    world.permit = dupe.permit
    world.permit_id = dupe.permit_id
    world.other = fx.create_client(
        api,
        f.client_payload(
            name="Other Mailers",
            client_code="OTHER",
            service_fee_rate_per_thousand_cents=1000,
        ),
    )
    world.other_id = world.other["id"]
    world.facility = fx.setup_facility(api)
    world.facility_id = world.facility["id"]
    return world


class TestDuplicateNaturalKeys:
    """Client code, permit number and facility code are each unique bureau-wide."""

    def test_a_second_client_may_not_take_a_client_code_already_held(self, api):
        """The code is the operator-facing handle, so it may name only one mailer.

        Registration takes "a short operator-facing `client_code` of 2 to 16
        characters drawn only from uppercase letters and digits, which must be
        globally unique across all clients; a collision is rejected with
        `ERR_DUPLICATE_CLIENT_CODE`." The ladder states the check and its status:
        "**Client code uniqueness** — the supplied `client_code` is not already
        held by another `Client`. Violation: `ERR_DUPLICATE_CLIENT_CODE` (409)."

        Design: Corner/errors/duplicate_natural_keys_on_client_permit_and_facility_are_rejected
        """
        world = _build_duplicate_key_world(api)

        validate_error(
            api.create_client(
                f.client_payload(
                    name="Impostor Mailers",
                    client_code="DUPE",
                    service_fee_rate_per_thousand_cents=2000,
                ),
                BUREAU_ADMIN,
            ),
            ERR_DUPLICATE_CLIENT_CODE,
            expected_status=409,
        )

        held = validate_success(api.get_client(world.client_id, BUREAU_ADMIN))
        assert_field_values(held, {"name": "Duplicate Mailers", "client_code": "DUPE"})
        assert_version_unchanged(world.client, held)
        other = validate_success(api.get_client(world.other_id, BUREAU_ADMIN))
        assert_field_values(other, {"name": "Other Mailers", "client_code": "OTHER"})

    def test_a_permit_number_is_unique_bureau_wide_not_per_client(self, api):
        """Offering the same permit number for a different mailer is still a clash.

        The account "records the `permit_number` issued by the acceptance unit — 4
        to 24 characters, globally unique, with a collision rejected as
        `ERR_DUPLICATE_PERMIT_NUMBER`". The ladder names the comparison and leaves
        no room for a per-client index: "**Permit number uniqueness** — the
        supplied `permit_number` is not already held by another `PermitAccount`.
        Violation: `ERR_DUPLICATE_PERMIT_NUMBER` (409)."

        Design: Corner/errors/duplicate_natural_keys_on_client_permit_and_facility_are_rejected
        """
        world = _build_duplicate_key_world(api)

        validate_error(
            api.create_permit_account(
                f.permit_account_payload(
                    world.other_id,
                    permit_number="PI-380380",
                    payment_method="PERMIT_IMPRINT",
                ),
                POSTAGE_MANAGER,
            ),
            ERR_DUPLICATE_PERMIT_NUMBER,
            expected_status=409,
        )

        held, meta = validate_paginated(
            api.list_client_permit_accounts(world.client_id, POSTAGE_MANAGER)
        )
        assert_row_count(held, 1, "permit accounts on the original client")
        assert meta["total_count"] == 1
        assert_field_values(
            held[0], {"permit_number": "PI-380380", "payment_method": "METER"}
        )
        rival_accounts, rival_meta = validate_paginated(
            api.list_client_permit_accounts(world.other_id, POSTAGE_MANAGER)
        )
        assert_row_count(rival_accounts, 0, "permit accounts on the second client")
        assert rival_meta["total_count"] == 0

    def test_a_second_facility_may_not_take_a_facility_code_already_held(self, api):
        """A clashing registration cannot overwrite the dock it collides with.

        A facility is registered "with a globally unique `facility_code` of 3 to 24
        characters — a collision is `ERR_DUPLICATE_FACILITY_CODE`". The ladder
        states it as a rung of its own: "**Facility code uniqueness** — the
        supplied `facility_code` is not already held by another `EntryFacility`.
        Violation: `ERR_DUPLICATE_FACILITY_CODE` (409)."

        Design: Corner/errors/duplicate_natural_keys_on_client_permit_and_facility_are_rejected
        """
        world = _build_duplicate_key_world(api)

        validate_error(
            api.create_entry_facility(
                f.entry_facility_payload(
                    facility_code="SCF-021",
                    facility_type="NDC",
                    zip3="022",
                    dock_capacity_pallets_per_slot=20,
                    drop_ship_discount_bp=200,
                    served_zip3_list=["022"],
                ),
                BUREAU_ADMIN,
            ),
            ERR_DUPLICATE_FACILITY_CODE,
            expected_status=409,
        )

        held = validate_success(api.get_entry_facility(world.facility_id, BUREAU_ADMIN))
        assert_field_values(
            held,
            {
                "facility_code": "SCF-021",
                "facility_type": "SCF",
                "zip3": "021",
                "dock_capacity_pallets_per_slot": fx.FACILITY_DOCK_CAPACITY,
                "drop_ship_discount_bp": fx.FACILITY_DISCOUNT_BP,
            },
        )
        assert_version_unchanged(world.facility, held)


def _build_empty_period_world(api):
    """The clock at 2026-08-10T09:00:00.000Z, one OPEN facility, one OPEN batch,
    and one ACTIVE client that has never tendered a single piece of mail."""
    world = fx.World()
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    world.client = fx.create_client(
        api,
        f.client_payload(
            name="Empty Period Mailers",
            client_code="EMPTY",
            service_fee_rate_per_thousand_cents=1000,
        ),
    )
    world.client_id = world.client["id"]
    world.facility = fx.setup_facility(api)
    world.facility_id = world.facility["id"]
    world.batch = fx.create_batch(api, f.commingle_batch_payload(world.facility_id))
    world.batch_id = world.batch["id"]
    return world


class TestIntervalTemporalAndEmptyPeriodRejections:
    """Malformed intervals, a window in the past, and a period with nothing in it."""

    def test_a_zero_length_dock_window_is_malformed(self, api):
        """Equal endpoints are not an empty appointment, they are a bad one.

        An appointment is booked with "an inclusive `window_start_utc` and an
        exclusive `window_end_utc` that must be strictly after it". The ladder
        states the comparison and its status: "**Interval well-formedness** —
        `window_end_utc` is strictly after `window_start_utc`, and `period_end_utc`
        is strictly after `period_start_utc`. Violation: `ERR_INTERVAL_INVALID`
        (400)."

        Design: Corner/errors/interval_temporal_and_empty_period_rejections_on_booking_and_billing
        """
        world = _build_empty_period_world(api)
        instant = f.instant(2026, 8, 12, 10, 0, 0)

        validate_error(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    world.batch_id, world.facility_id, instant, instant, pallet_count=2
                ),
                PRESORT_OPERATOR,
            ),
            ERR_INTERVAL_INVALID,
            expected_status=400,
        )

        shipments, meta = validate_paginated(
            api.list_batch_drop_shipments(world.batch_id, PRESORT_OPERATOR)
        )
        assert_row_count(shipments, 0, "drop shipments")
        assert meta["total_count"] == 0

    def test_a_window_starting_before_the_clock_is_in_the_past(self, api):
        """A well-formed window is still refused when the dock date has gone by.

        "An ill-formed window is `ERR_INTERVAL_INVALID`, and a `window_start_utc`
        earlier than the current logical clock is `ERR_SHIPMENT_WINDOW_IN_PAST` —
        appointments may not be booked into the past, though a window starting
        exactly at the current clock instant is acceptable." The clock is the only
        time source consulted: "The logical clock is what decides whether a permit
        account's annual mailing fee has lapsed, whether a dock appointment window
        is in the past, whether a deposit is happening inside its window, and what
        instant is stamped into `deposited_at_utc` and `mailed_at_utc`."

        Design: Corner/errors/interval_temporal_and_empty_period_rejections_on_booking_and_billing
        """
        world = _build_empty_period_world(api)

        validate_error(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    world.batch_id,
                    world.facility_id,
                    f.instant(2026, 8, 9, 10, 0, 0),
                    f.instant(2026, 8, 9, 18, 0, 0),
                    pallet_count=2,
                ),
                PRESORT_OPERATOR,
            ),
            ERR_SHIPMENT_WINDOW_IN_PAST,
            expected_status=422,
        )

        shipments, meta = validate_paginated(
            api.list_batch_drop_shipments(world.batch_id, PRESORT_OPERATOR)
        )
        assert_row_count(shipments, 0, "drop shipments")
        assert meta["total_count"] == 0

    def test_a_reversed_billing_period_is_malformed(self, api):
        """A period that ends before it starts is refused before anything is billed.

        An invoice is issued "for a closed billing period bounded by
        `period_start_utc` and `period_end_utc`, the latter strictly after the
        former", and the ladder puts that at the request-shape end of the order:
        "**Interval well-formedness** — `window_end_utc` is strictly after
        `window_start_utc`, and `period_end_utc` is strictly after
        `period_start_utc`. Violation: `ERR_INTERVAL_INVALID` (400)."

        Design: Corner/errors/interval_temporal_and_empty_period_rejections_on_booking_and_billing
        """
        world = _build_empty_period_world(api)

        validate_error(
            api.create_client_invoice(
                world.client_id,
                f.invoice_payload(
                    period_start_utc=f.instant(2026, 8, 31, 0, 0, 0),
                    period_end_utc=f.instant(2026, 8, 1, 0, 0, 0),
                ),
                POSTAGE_MANAGER,
            ),
            ERR_INTERVAL_INVALID,
            expected_status=400,
        )

        invoices, meta = validate_paginated(
            api.list_client_invoices(world.client_id, POSTAGE_MANAGER)
        )
        assert_row_count(invoices, 0, "invoices")
        assert meta["total_count"] == 0

    def test_a_period_with_no_mailed_job_has_nothing_to_bill(self, api):
        """An empty month yields a refusal, not an invoice for nothing.

        "First, select the client's jobs that are in `MAILED` and whose
        `mailed_at_utc` falls inside the requested period treated as closed at both
        ends, ordered by `created_at` ascending. If that selection is empty the
        request is rejected with `ERR_NO_BILLABLE_JOBS`." The ladder fixes the
        status: "**At least one billable job** — the requested invoice period covers
        at least one billable job. Violation: `ERR_NO_BILLABLE_JOBS` (422)."

        Design: Corner/errors/interval_temporal_and_empty_period_rejections_on_booking_and_billing
        """
        world = _build_empty_period_world(api)

        validate_error(
            api.create_client_invoice(
                world.client_id,
                f.invoice_payload(
                    period_start_utc=f.AUGUST_2026_START,
                    period_end_utc=f.AUGUST_2026_END,
                ),
                POSTAGE_MANAGER,
            ),
            ERR_NO_BILLABLE_JOBS,
            expected_status=422,
        )

        invoices, meta = validate_paginated(
            api.list_client_invoices(world.client_id, POSTAGE_MANAGER)
        )
        assert_row_count(invoices, 0, "invoices")
        assert meta["total_count"] == 0


def _build_pooling_gate_world(api):
    """Client GATE2 with an ACTIVE permit, one hygiene-cleared 1000-piece LETTERS
    job already pooled into an OPEN LETTERS batch, and one hygiene-cleared
    800-piece FLATS job standing outside it."""
    world = fx.World()
    fx.set_clock(api, FIXTURE_CLOCK_UTC)
    account = fx.setup_client_with_permit(
        api,
        name="Gate Two Mail",
        client_code="GATE2",
        permit_number="PI-390390",
        payment_method="METER",
    )
    world.client = account.client
    world.client_id = account.client_id
    world.permit = account.permit
    world.permit_id = account.permit_id
    world.facility = fx.setup_facility(api)
    world.facility_id = world.facility["id"]

    letters = fx.setup_cleared_job(
        api, world.client_id, world.permit_id, declared_piece_count=1000
    )
    world.job_letters = letters.job
    world.job_letters_id = letters.job_id
    flats = fx.setup_cleared_job(
        api,
        world.client_id,
        world.permit_id,
        processing_category="FLATS",
        declared_piece_count=800,
    )
    world.job_flats = flats.job
    world.job_flats_id = flats.job_id

    world.batch = fx.create_batch(api, f.commingle_batch_payload(world.facility_id))
    world.batch_id = world.batch["id"]
    world.member = fx.add_member(api, world.batch_id, world.job_letters_id)
    world.member_id = world.member["id"]
    return world


class TestPoolingGateErrors:
    """Already pooled, wrong processing category, and a suspended mailer."""

    def test_re_pooling_an_already_pooled_job_has_its_own_code(self, api):
        """The second attempt is not a generic bad-state error.

        "The job must be in `HYGIENE_CLEARED`; a job already in `POOLED` is refused
        with `ERR_JOB_ALREADY_POOLED` and a job in any other status with
        `ERR_INVALID_JOB_STATE`." The ladder gives the already-pooled case a rung of
        its own: "**Job not already pooled** — the referenced `MailJob` does not
        already hold a `BatchMember`, that is, its status is not `POOLED`. Violation:
        `ERR_JOB_ALREADY_POOLED` (409)."

        Design: Corner/errors/pooling_gate_errors_for_already_pooled_category_mismatch_and_suspension
        """
        world = _build_pooling_gate_world(api)

        validate_error(
            api.add_batch_member(
                world.batch_id,
                f.batch_member_payload(world.job_letters_id),
                PRESORT_OPERATOR,
            ),
            ERR_JOB_ALREADY_POOLED,
            expected_status=409,
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            batch, member_job_count=1, total_piece_count=1000, container_count=0
        )
        members, meta = validate_paginated(
            api.list_batch_members(world.batch_id, PRESORT_OPERATOR)
        )
        assert_row_count(members, 1, "batch members")
        assert meta["total_count"] == 1
        assert members[0]["contributed_piece_count"] == 1000
        assert_unchanged(
            world.member,
            members[0],
            "id",
            "mail_job_id",
            "contributed_piece_count",
            "allocated_postage_cents",
        )
        assert_version_unchanged(world.member, members[0])

    def test_a_flats_job_may_not_join_a_letters_batch(self, api):
        """A matching mail class is not enough; the physical shape must match too.

        "And the job's `mail_class` and `processing_category` must each equal the
        batch's, otherwise `ERR_MAIL_CLASS_MISMATCH` or
        `ERR_PROCESSING_CATEGORY_MISMATCH`." The ladder fixes the status:
        "**Processing category agreement** — the job's `processing_category` equals
        the batch's `processing_category`. Violation:
        `ERR_PROCESSING_CATEGORY_MISMATCH` (422)."

        Design: Corner/errors/pooling_gate_errors_for_already_pooled_category_mismatch_and_suspension
        """
        world = _build_pooling_gate_world(api)

        validate_error(
            api.add_batch_member(
                world.batch_id,
                f.batch_member_payload(world.job_flats_id),
                PRESORT_OPERATOR,
            ),
            ERR_PROCESSING_CATEGORY_MISMATCH,
            expected_status=422,
        )

        refused_job = validate_success(
            api.get_mail_job(world.job_flats_id, PRESORT_OPERATOR)
        )
        assert_job_state(refused_job, status="HYGIENE_CLEARED", accepted_piece_count=800)
        assert refused_job["commingle_batch_id"] is None
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            batch, member_job_count=1, total_piece_count=1000, container_count=0
        )

    def test_a_suspended_mailer_may_not_tender_new_mail(self, api):
        """Suspension reaches plain intake, not merely the pooling of cleaned mail.

        "Suspension is not merely advisory: while a client is `SUSPENDED`, tendering
        new jobs for it, running a hygiene pass on its jobs, pooling its jobs into a
        batch, and issuing it an invoice are all refused with
        `ERR_CLIENT_SUSPENDED`." The ladder fixes the status and the endpoints:
        "**Owning client active** — the `Client` that owns the target resource has
        status `ACTIVE`, checked through `MailJob.client_id` on job creation, on a
        hygiene run and on pooling, and against the path client identifier on
        invoice issuance. Violation: `ERR_CLIENT_SUSPENDED` (409)."

        Design: Corner/errors/pooling_gate_errors_for_already_pooled_category_mismatch_and_suspension
        """
        world = _build_pooling_gate_world(api)

        suspended = validate_success(
            api.set_client_status(
                world.client_id,
                f.client_status_payload("SUSPENDED", reason="credit hold"),
                BUREAU_ADMIN,
            )
        )
        assert suspended["status"] == "SUSPENDED"

        validate_error(
            api.create_mail_job(
                f.mail_job_payload(
                    world.client_id,
                    world.permit_id,
                    declared_piece_count=400,
                    declared_weight_oz_per_piece=1.0,
                ),
                PRESORT_OPERATOR,
            ),
            ERR_CLIENT_SUSPENDED,
            expected_status=409,
        )

        jobs, meta = validate_paginated(
            api.list_client_mail_jobs(world.client_id, PRESORT_OPERATOR)
        )
        assert_row_count(jobs, 2, "mail jobs on the suspended client")
        assert meta["total_count"] == 2


class TestPermitFiscalAndShipmentUniquenessGates:
    """Three gates that read state the request body never mentions."""

    def test_an_account_holding_reserved_funds_cannot_be_closed(self, api):
        """Money encumbered by a statement in flight keeps the account open.

        "Closure is terminal and can be reached from either live state — `ACTIVE →
        CLOSED` or `HOLD → CLOSED` — but only while `reserved_cents` is exactly 0,
        because an account with money encumbered by a statement in flight still has
        obligations; a close attempted with any reserved funds is rejected with
        `ERR_PERMIT_HAS_RESERVED_FUNDS`." The reservation is what filing created:
        "`declared_postage_cents` is subtracted from the account's `balance_cents`
        and added to its `reserved_cents`, which changes nothing about the account's
        total funds."

        Design: Corner/errors/permit_fiscal_and_shipment_uniqueness_gate_errors
        """
        world = fx.build_submitted_world(api)
        before = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            before,
            balance_cents=fx.HOUSE_FUNDING_CENTS - fx.POOLED_POSTAGE_CENTS,
            reserved_cents=fx.POOLED_POSTAGE_CENTS,
        )

        validate_error(
            api.set_permit_account_status(
                world.permit_house_id,
                f.permit_status_payload("CLOSED", reason="consolidating accounts"),
                POSTAGE_MANAGER,
            ),
            ERR_PERMIT_HAS_RESERVED_FUNDS,
            expected_status=409,
        )

        after = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert after["status"] == "ACTIVE"
        assert_permit_funds(
            after,
            balance_cents=fx.HOUSE_FUNDING_CENTS - fx.POOLED_POSTAGE_CENTS,
            reserved_cents=fx.POOLED_POSTAGE_CENTS,
        )
        assert_version_unchanged(before, after)

    def test_a_lapsed_annual_fee_blocks_intake_on_an_otherwise_active_account(
        self, api
    ):
        """The lapse is a tender-time gate, never a bar on opening the account.

        "It also records `annual_fee_paid_through_utc`, the instant through which the
        annual mailing fee has been paid. That instant is a hard regulatory gate:
        whenever the current logical clock is strictly later than
        `annual_fee_paid_through_utc`, mail may not be tendered under the account, no
        hygiene pass may be run on a job funded by it, and no statement drawing on it
        may be filed — all three are refused with `ERR_PERMIT_ANNUAL_FEE_LAPSED`. A
        permit account opens in `ACTIVE` status with `balance_cents` and
        `reserved_cents` both zero."

        Design: Corner/errors/permit_fiscal_and_shipment_uniqueness_gate_errors
        """
        world = fx.build_submitted_world(api)

        lapsed = validate_success(
            api.create_permit_account(
                f.permit_account_payload(
                    world.acme_id,
                    permit_number="PI-410410",
                    payment_method="PERMIT_IMPRINT",
                    annual_fee_paid_through_utc=f.instant(2026, 8, 9, 23, 59, 59),
                ),
                POSTAGE_MANAGER,
            ),
            expected_status=201,
        )
        assert lapsed["status"] == "ACTIVE"
        assert_permit_funds(lapsed, balance_cents=0, reserved_cents=0)

        validate_error(
            api.create_mail_job(
                f.mail_job_payload(
                    world.acme_id,
                    lapsed["id"],
                    declared_piece_count=600,
                    declared_weight_oz_per_piece=1.0,
                ),
                PRESORT_OPERATOR,
            ),
            ERR_PERMIT_ANNUAL_FEE_LAPSED,
            expected_status=409,
        )

    def test_a_batch_may_hold_only_one_live_appointment(self, api):
        """A second booking on a different day and a free dock is still refused.

        "A batch may have at most one live appointment at a time: if the batch
        already has a shipment in `SCHEDULED` or `IN_TRANSIT`, the booking is refused
        with `ERR_SHIPMENT_ALREADY_SCHEDULED`." The ladder states the same rule as a
        rung: "**One live appointment per batch** — at most one `DropShipment` per
        `CommingleBatch` may be in `SCHEDULED` or `IN_TRANSIT`. Violation:
        `ERR_SHIPMENT_ALREADY_SCHEDULED` (409)."

        Design: Corner/errors/permit_fiscal_and_shipment_uniqueness_gate_errors
        """
        world = fx.build_submitted_world(api)

        booked = validate_success(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    world.batch_id,
                    world.facility_id,
                    fx.SHIPMENT_WINDOW_START,
                    fx.SHIPMENT_WINDOW_END,
                    pallet_count=2,
                ),
                PRESORT_OPERATOR,
            ),
            expected_status=201,
        )
        assert booked["status"] == "SCHEDULED"

        validate_error(
            api.create_drop_shipment(
                f.drop_shipment_payload(
                    world.batch_id,
                    world.facility_id,
                    f.instant(2026, 8, 13, 8, 0, 0),
                    f.instant(2026, 8, 13, 16, 0, 0),
                    pallet_count=2,
                ),
                PRESORT_OPERATOR,
            ),
            ERR_SHIPMENT_ALREADY_SCHEDULED,
            expected_status=409,
        )

        shipments, meta = validate_paginated(
            api.list_batch_drop_shipments(world.batch_id, PRESORT_OPERATOR)
        )
        assert_row_count(shipments, 1, "drop shipments on the batch")
        assert meta["total_count"] == 1
        assert shipments[0]["id"] == booked["id"]


FIRST_SCAN_AT = f.instant(2026, 8, 16, 10, 0, 0)
SECOND_SCAN_AT = f.instant(2026, 8, 21, 10, 0, 0)


def _build_deposited_records_world(api):
    """The canonical batch deposited at 14:00 on 12 August, with the two unscanned
    service-level records the deposit opened looked up from their containers."""
    world = fx.build_departed_world(api)
    fx.deposit_drop_shipment(api, world.shipment_id)
    records_1, _meta_1 = validate_paginated(
        api.list_container_service_level_records(world.container_1_id, ACCEPTANCE_CLERK)
    )
    records_2, _meta_2 = validate_paginated(
        api.list_container_service_level_records(world.container_2_id, ACCEPTANCE_CLERK)
    )
    world.slr_1 = records_1[0]
    world.slr_1_id = records_1[0]["id"]
    world.slr_2 = records_2[0]
    world.slr_2_id = records_2[0]["id"]
    return world


class TestDeliveryScanIsSingleShot:
    """One record, one scan — a later correction cannot rewrite the verdict."""

    def test_a_second_scan_cannot_overwrite_the_first_verdict(self, api):
        """The guard is that the record is still unscanned, so the retry is refused.

        "The record's `on_time` is then set to true when `actual_delivery_days` is
        less than or equal to the record's `committed_days`, and false otherwise;
        delivering in exactly the committed number of days counts as on time. The
        record's `version` increments. A record may be scanned only once — its
        `actual_delivery_days` must still be null when the scan arrives, and a second
        scan is refused with `ERR_DELIVERY_ALREADY_SCANNED`."

        Design: Corner/errors/delivery_scan_may_not_be_recorded_twice_on_one_record
        """
        world = _build_deposited_records_world(api)
        assert world.slr_1["actual_delivery_days"] is None

        first = validate_success(
            api.record_delivery_scan(
                world.slr_1_id,
                f.delivery_scan_payload(4, FIRST_SCAN_AT),
                ACCEPTANCE_CLERK,
            ),
            expected_status=200,
        )
        assert_field_values(
            first,
            {
                "committed_days": 4,
                "actual_delivery_days": 4,
                "on_time": True,
                "scanned_at_utc": FIRST_SCAN_AT,
                "version": 2,
            },
        )

        validate_error(
            api.record_delivery_scan(
                world.slr_1_id,
                f.delivery_scan_payload(9, SECOND_SCAN_AT),
                ACCEPTANCE_CLERK,
            ),
            ERR_DELIVERY_ALREADY_SCANNED,
            expected_status=409,
        )

        after = validate_success(
            api.get_service_level_record(world.slr_1_id, POSTAGE_MANAGER)
        )
        assert_field_values(
            after,
            {
                "actual_delivery_days": 4,
                "on_time": True,
                "scanned_at_utc": FIRST_SCAN_AT,
                "version": 2,
            },
        )
        assert_version_unchanged(first, after)

    def test_the_refused_correction_never_enters_the_service_index(self, api):
        """The index reflects the scan that landed, not the one that was refused.

        "The population is every service-level record that has actually been
        delivery-scanned — that is, whose `actual_delivery_days` is not null — whose
        container belongs to a batch that has at least one member whose job's
        `client_id` is the client being asked about. Unscanned records are excluded
        from both numerator and denominator entirely."

        Design: Corner/errors/delivery_scan_may_not_be_recorded_twice_on_one_record
        """
        world = _build_deposited_records_world(api)

        validate_success(
            api.record_delivery_scan(
                world.slr_1_id,
                f.delivery_scan_payload(4, FIRST_SCAN_AT),
                ACCEPTANCE_CLERK,
            ),
            expected_status=200,
        )
        validate_error(
            api.record_delivery_scan(
                world.slr_1_id,
                f.delivery_scan_payload(9, SECOND_SCAN_AT),
                ACCEPTANCE_CLERK,
            ),
            ERR_DELIVERY_ALREADY_SCANNED,
            expected_status=409,
        )

        index = validate_success(
            api.get_client_service_level(world.acme_id, POSTAGE_MANAGER)
        )
        assert_service_level_index(
            index,
            record_count=1,
            on_time_count=1,
            zone_weighted_index=100.00,
            piece_weighted_index=100.00,
        )

        untouched = validate_success(
            api.get_service_level_record(world.slr_2_id, POSTAGE_MANAGER)
        )
        assert untouched["actual_delivery_days"] is None
        assert untouched["on_time"] is None
