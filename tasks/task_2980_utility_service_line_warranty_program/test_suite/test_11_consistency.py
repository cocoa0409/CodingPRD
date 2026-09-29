"""The immediate consistency model of the API (PRD §2.2, §2.3, §2.4, §2.9, §3.9).

Every accepted write in this system is visible to the very next read: the row a
create returns is the row a fetch by id returns, a cascade lands inside the
request that triggered it rather than in a later batch, a refusal leaves no
half-written row or moved version behind, and the nightly run's own audit record
never disagrees with the rows it names.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_OWNERSHIP_NOT_ELIGIBLE,
    ERR_PREMISES_NOT_FOUND,
    ERR_STALE_PREMISES_VERSION,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_created_resource,
    assert_fields,
    assert_ids_in_order,
    assert_instant,
    assert_list_envelope,
    assert_nightly_lists_empty,
    assert_nightly_report_shape,
    assert_object_envelope,
    assert_refused,
    assert_request_meta,
    assert_version_bumped,
)
from test_helpers.constants import (
    CLOCK_COVERAGE_ACTIVE,
    CLOCK_ENROLLMENT_DAY,
    CLOCK_START,
    COVERAGE_EFFECTIVE_AT,
    DEFAULT_LIMIT,
    ENROLLMENT_TERM_START,
)
from test_helpers.test_users import (
    BILLING_OPS,
    CLAIMS_ADJUSTER,
    CUSTOMER_SERVICE_REP,
    MARKETING_OPS,
    OPERATIONS_ADMIN,
    PLATFORM_ADMIN,
)

# A well-formed UUID that matches no row of any collection.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# One day short of the coverage_effective_at of a policy written on 2026-08-05
# under the thirty-day waiting period.
CLOCK_BEFORE_COVERAGE = "2026-09-03T00:00:00.000Z"


def _create_envelope(response, expected_status: int = 201) -> dict:
    """The single-resource envelope of a create, at its own 2xx status.

    ``assert_object_envelope`` fixes the status at 200, so the 201 creating
    endpoints of PRD §4 need the same two envelope checks at their own status:
    ``response_type`` is ``object`` and the four pagination keys of PRD §2.3 are
    absent from ``meta``.
    """
    body = response.json()
    assert body.get("response_type") == "object", (
        f"response_type expected 'object', got {body.get('response_type')!r}"
    )
    meta = body.get("meta", {})
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta or meta[key] is None, (
            f"a single-resource response omits meta.{key}, got {meta.get(key)!r}"
        )
    return validate_success(response, expected_status)


class TestImmediateVisibility:
    """A write and the read that follows it never disagree."""

    def test_envelope_shape_and_read_your_write_on_every_create(self, api):
        """A create's own row is exactly the row the next fetch and list return.

        PRD: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/consistency_envelope_shape_and_read_your_write_on_every_create
        """
        fixtures.set_clock(api, CLOCK_START)

        create = api.create_partner(factories.partner_payload(), PLATFORM_ADMIN)
        created = _create_envelope(create)
        create_meta = assert_request_meta(create)
        assert_created_resource(created)
        assert_fields(
            created,
            {
                "name": "Cascadia Water",
                "utility_type": "WATER",
                "state_code": "OR",
                "status": "ONBOARDING",
                "suspension_reason": None,
                "enrolled_premises_count": 0,
            },
        )
        # There is no wall clock: created_at is the logical clock (PRD §2.5).
        assert_instant(created["created_at"], CLOCK_START, "created_at")

        read = api.get_partner(created["id"], PLATFORM_ADMIN)
        read_data = assert_object_envelope(read)
        read_meta = assert_request_meta(read)
        assert read_data == created, (
            "the fetched partner must be the created partner field for field: "
            f"{created!r} -> {read_data!r}"
        )
        assert create_meta["api_request_id"] != read_meta["api_request_id"], (
            "meta.api_request_id is minted per request, not per resource: "
            f"{create_meta['api_request_id']!r}"
        )

        # A collection response carries response_type array and all four
        # pagination keys, and it already sees the new row (PRD §2.2, §2.3).
        rows, meta = assert_list_envelope(api.list_partners(PLATFORM_ADMIN), expected_total=1)
        assert meta["limit"] == DEFAULT_LIMIT, f"limit defaults to 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"
        assert meta["has_more"] is False, "a single row leaves nothing beyond the window"
        assert rows == [created], f"the listed partner must be the created row, got {rows!r}"

        premises_response = api.create_premises(
            factories.premises_payload(created["id"], street_address="18 Alder Court"),
            MARKETING_OPS,
        )
        premises = _create_envelope(premises_response)
        assert_request_meta(premises_response)
        assert_created_resource(premises)
        # PRD §3.1 fixes every derived opening value of a fresh premises.
        assert_fields(
            premises,
            {
                "partner_id": created["id"],
                "suppression_reason": "NONE",
                "suppressed": False,
                "last_mail_decision": "NOT_EVALUATED",
                "last_mail_suppression_reason": None,
                "last_mailed_campaign_id": None,
                "mail_count_current_year": 0,
            },
        )
        assert_instant(premises["created_at"], CLOCK_START, "created_at")

        premises_read = assert_object_envelope(api.get_premises(premises["id"], MARKETING_OPS))
        assert premises_read == premises, (
            "the fetched premises must be the created premises field for field: "
            f"{premises!r} -> {premises_read!r}"
        )

    def test_same_request_cascade_is_visible_to_the_very_next_read(self, api):
        """Termination's fan-out is readable at once and the batch re-applies none of it.

        PRD: "Those secondary mutations are not incidental — they are part of the contract, they are ordered, and each of them advances its own record's `version` by 1 and refreshes its own `updated_at`."

        Design: Corner/consistency_model/consistency_same_request_cascade_is_visible_to_the_very_next_read
        """
        world = fixtures.active_partner_with_product(api)
        assert world["product"]["status"] == "AVAILABLE"
        assert world["partner"]["status"] == "ACTIVE"

        premises = fixtures.create_premises(api, world["partner_id"], street_address="18 Alder Court")
        campaign = fixtures.create_campaign(
            api, world["partner_id"], world["product_id"],
            name="August water drop", drop_date="2026-08-20",
        )
        submitted = fixtures.submit_campaign(api, campaign["id"])
        assert submitted["status"] == "PARTNER_REVIEW"

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment = fixtures.create_enrollment(
            api, premises["id"], world["product_id"], premises["version"]
        )
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        fixtures.run_nightly(api)
        before = fixtures.refresh_enrollment(api, enrollment["id"])
        assert before["coverage_status"] == "ACTIVE"

        partner_before = validate_success(api.get_partner(world["partner_id"], PLATFORM_ADMIN))
        terminated = assert_object_envelope(
            api.change_partner_status(
                world["partner_id"],
                factories.partner_status_change_payload(
                    "TERMINATED", partner_before["version"],
                    reason="Partner exited the program.",
                ),
                PLATFORM_ADMIN,
            )
        )
        assert terminated["status"] == "TERMINATED"
        assert_version_bumped(terminated, partner_before)

        # The product moved inside the same request, not on a later batch.
        product_after = assert_object_envelope(
            api.get_product(world["product_id"], PLATFORM_ADMIN)
        )
        assert product_after["status"] == "WITHDRAWN"
        assert_version_bumped(product_after, world["product"])

        # So did the in-flight PARTNER_REVIEW campaign.
        campaign_after = assert_object_envelope(api.get_campaign(campaign["id"], MARKETING_OPS))
        assert campaign_after["status"] == "WITHDRAWN"
        assert_version_bumped(campaign_after, submitted)

        # The cascade is visible through the filtered collection too, not only by id.
        rows, _meta = assert_list_envelope(
            api.list_products(
                PLATFORM_ADMIN,
                params={"partner_id": world["partner_id"], "status": "WITHDRAWN"},
            ),
            expected_total=1,
        )
        assert_ids_in_order(rows, [world["product_id"]])

        # In-force coverage is deliberately untouched, so its version does not move.
        enrollment_after = assert_object_envelope(
            api.get_enrollment(enrollment["id"], CUSTOMER_SERVICE_REP)
        )
        assert enrollment_after["coverage_status"] == "ACTIVE"
        assert enrollment_after["version"] == before["version"], (
            "termination touches no enrollment, so its version must not move: "
            f"{before['version']} -> {enrollment_after['version']}"
        )

        # Nothing was left pending for the batch to finish.
        report = validate_success(api.run_nightly(OPERATIONS_ADMIN))
        assert_nightly_report_shape(report)
        assert_nightly_lists_empty(report)

        campaign_after_batch = assert_object_envelope(
            api.get_campaign(campaign["id"], MARKETING_OPS)
        )
        assert campaign_after_batch["status"] == "WITHDRAWN"
        assert campaign_after_batch["version"] == campaign_after["version"], (
            "a batch run after the cascade re-applies nothing"
        )


class TestRefusalAtomicity:
    """A refused write is atomic: nothing it would have written is observable."""

    def test_a_refused_write_leaves_no_partial_state_behind(self, api):
        """Three refused enrollments leave no row, no counter and no version behind.

        PRD: "`version` is an integer that starts at 1 when the record is created and increases by exactly 1 on every accepted mutation of that record."

        Design: Corner/consistency_model/consistency_a_refused_write_leaves_no_partial_state_behind
        """
        world = fixtures.active_partner_with_product(api)
        unowned = fixtures.create_premises(
            api, world["partner_id"],
            street_address="18 Alder Court",
            owned_segments=["WATER_METER_TO_HOME"],
        )
        water = fixtures.create_premises(
            api, world["partner_id"], street_address="22 Birch Lane"
        )
        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)

        partner_before = validate_success(api.get_partner(world["partner_id"], PLATFORM_ADMIN))
        assert partner_before["enrolled_premises_count"] == 0

        # Refusal 1 — the address does not own the product's required segment.
        segment_refusal = api.create_enrollment(
            factories.enrollment_payload(
                unowned["id"], world["product_id"], unowned["version"]
            ),
            CUSTOMER_SERVICE_REP,
        )
        segment_error = assert_refused(segment_refusal, ERR_OWNERSHIP_NOT_ELIGIBLE)
        refusal_body = segment_refusal.json()
        assert refusal_body["response_type"] == "error", (
            f"response_type expected 'error', got {refusal_body['response_type']!r}"
        )
        # On a failure data is exactly {error_id, message} and meta carries only
        # the two request fields (PRD §2.2).
        assert set(refusal_body["data"]) == {"error_id", "message"}, (
            f"an error body carries only error_id and message, got {sorted(refusal_body['data'])}"
        )
        assert set(refusal_body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
            "the meta object of an error response carries only api_request_id and "
            f"api_request_timestamp, got {sorted(refusal_body['meta'])}"
        )
        assert_request_meta(segment_refusal)
        assert segment_error["message"].strip(), "message must be a human-readable string"

        # Refusal 2 — a premises version the caller never observed.
        stale_refusal = api.create_enrollment(
            factories.enrollment_payload(water["id"], world["product_id"], 7),
            CUSTOMER_SERVICE_REP,
        )
        stale_error = assert_refused(stale_refusal, ERR_STALE_PREMISES_VERSION)
        assert stale_error["message"].strip(), "message must be a human-readable string"

        # Refusal 3 — a body foreign key that resolves to nothing.
        missing_refusal = api.create_enrollment(
            factories.enrollment_payload(MISSING_UUID, world["product_id"], 1),
            CUSTOMER_SERVICE_REP,
        )
        assert_refused(missing_refusal, ERR_PREMISES_NOT_FOUND)
        assert missing_refusal.json()["response_type"] == "error"

        # Three refusals, zero rows.
        rows, meta = assert_list_envelope(
            api.list_enrollments(CUSTOMER_SERVICE_REP), expected_total=0
        )
        assert rows == [], f"no enrollment may exist after three refusals, got {rows!r}"
        assert meta["has_more"] is False

        # A refused write never bumps the version it validated against.
        water_after = assert_object_envelope(api.get_premises(water["id"], MARKETING_OPS))
        assert water_after["version"] == water["version"], (
            f"the premises version moved on a refusal: {water['version']} -> "
            f"{water_after['version']}"
        )
        unowned_after = assert_object_envelope(api.get_premises(unowned["id"], MARKETING_OPS))
        assert unowned_after["version"] == unowned["version"], (
            f"the premises version moved on a refusal: {unowned['version']} -> "
            f"{unowned_after['version']}"
        )
        # The rejected enrollment left no trace on the premises it named.
        assert unowned_after["suppression_reason"] == "NONE"
        assert unowned_after["suppressed"] is False

        partner_after = validate_success(api.get_partner(world["partner_id"], PLATFORM_ADMIN))
        assert partner_after["enrolled_premises_count"] == 0, (
            "a refused enrollment contributes nothing to enrolled_premises_count"
        )
        assert partner_after["version"] == partner_before["version"], (
            f"the partner version moved on a refusal: {partner_before['version']} -> "
            f"{partner_after['version']}"
        )

        # No orphan ledger row was written before the ladder refused.
        ledger_rows, _ledger_meta = assert_list_envelope(
            api.list_ledger_entries(BILLING_OPS), expected_total=0
        )
        assert ledger_rows == [], f"no ledger row may exist, got {ledger_rows!r}"

        # The same call succeeds once the fresh version is used, proving the
        # earlier refusals were the only difference.
        accepted = _create_envelope(
            api.create_enrollment(
                factories.enrollment_payload(
                    water["id"], world["product_id"], water_after["version"]
                ),
                CUSTOMER_SERVICE_REP,
            )
        )
        assert_created_resource(accepted)
        assert accepted["coverage_status"] == "PENDING_WAITING_PERIOD"
        assert accepted["term_start"] == ENROLLMENT_TERM_START

        rows_after, _meta_after = assert_list_envelope(
            api.list_enrollments(CUSTOMER_SERVICE_REP), expected_total=1
        )
        assert_ids_in_order(rows_after, [accepted["id"]])


class TestBatchReportAgreement:
    """The nightly run's report and the rows it names are one transaction."""

    def test_batch_output_and_the_rows_it_names_never_disagree(self, api):
        """Every id the run reports is already committed on the very next read.

        PRD: "The run's response is not an entity but a purpose-built audit record of what it did, and it names every affected record so that a caller can verify the run rather than trust it."

        Design: Corner/consistency_model/consistency_batch_output_and_the_rows_it_names_never_disagree
        """
        world = fixtures.active_partner_with_product(api)
        premises_one = fixtures.create_premises(
            api, world["partner_id"], street_address="18 Alder Court"
        )
        premises_two = fixtures.create_premises(
            api, world["partner_id"], street_address="22 Birch Lane"
        )

        fixtures.set_clock(api, CLOCK_ENROLLMENT_DAY)
        enrollment_one = fixtures.create_enrollment(
            api, premises_one["id"], world["product_id"], premises_one["version"]
        )
        enrollment_two = fixtures.create_enrollment(
            api, premises_two["id"], world["product_id"], premises_two["version"]
        )
        assert enrollment_one["coverage_status"] == "PENDING_WAITING_PERIOD"
        assert_instant(
            enrollment_one["coverage_effective_at"], COVERAGE_EFFECTIVE_AT, "coverage_effective_at"
        )
        assert enrollment_one["version"] == 1
        assert enrollment_two["version"] == 1

        # One day short of the effective instant: the run reports nothing and
        # changes nothing.
        fixtures.set_clock(api, CLOCK_BEFORE_COVERAGE)
        early_report = validate_success(api.run_nightly(OPERATIONS_ADMIN))
        assert_nightly_report_shape(early_report)
        assert_nightly_lists_empty(early_report)
        _pending_rows, pending_meta = assert_list_envelope(
            api.list_enrollments(
                CUSTOMER_SERVICE_REP, params={"coverage_status": "PENDING_WAITING_PERIOD"}
            ),
            expected_total=2,
        )
        assert pending_meta["has_more"] is False

        # Past the effective instant, the run activates both policies.
        fixtures.set_clock(api, CLOCK_COVERAGE_ACTIVE)
        report = validate_success(api.run_nightly(OPERATIONS_ADMIN))
        assert_nightly_report_shape(report)
        assert_instant(report["ran_at"], CLOCK_COVERAGE_ACTIVE, "ran_at")
        # The phase processes its rows in created_at ascending order.
        assert report["activated_enrollment_ids"] == [enrollment_one["id"], enrollment_two["id"]], (
            "activated_enrollment_ids expected "
            f"{[enrollment_one['id'], enrollment_two['id']]}, got "
            f"{report['activated_enrollment_ids']}"
        )
        # A phase that had nothing to do contributes an empty list rather than
        # being omitted (PRD §3.9).
        assert_nightly_lists_empty(report, except_for=("activated_enrollment_ids",))

        one_after = assert_object_envelope(
            api.get_enrollment(enrollment_one["id"], CUSTOMER_SERVICE_REP)
        )
        assert one_after["coverage_status"] == "ACTIVE"
        assert_version_bumped(one_after, enrollment_one)
        two_after = assert_object_envelope(
            api.get_enrollment(enrollment_two["id"], CUSTOMER_SERVICE_REP)
        )
        assert two_after["coverage_status"] == "ACTIVE"
        assert_version_bumped(two_after, enrollment_two)

        # The filtered collection equals the reported set, in created_at ASC order.
        active_rows, _active_meta = assert_list_envelope(
            api.list_enrollments(CUSTOMER_SERVICE_REP, params={"coverage_status": "ACTIVE"}),
            expected_total=2,
        )
        assert_created_at_ascending(active_rows)
        assert_ids_in_order(active_rows, [enrollment_one["id"], enrollment_two["id"]])

        # Nothing lingers in the pre-batch status.
        assert_list_envelope(
            api.list_enrollments(
                CUSTOMER_SERVICE_REP, params={"coverage_status": "PENDING_WAITING_PERIOD"}
            ),
            expected_total=0,
        )

        # A row created after the batch is immediately visible to a filtered read.
        claim = _create_envelope(
            api.create_claim(
                factories.claim_payload(
                    enrollment_one["id"],
                    incident_description="Wet patch above the service line.",
                ),
                CUSTOMER_SERVICE_REP,
            )
        )
        assert claim["status"] == "TRIAGE"
        claim_rows, _claim_meta = assert_list_envelope(
            api.list_claims(CLAIMS_ADJUSTER, params={"enrollment_id": enrollment_one["id"]}),
            expected_total=1,
        )
        assert_ids_in_order(claim_rows, [claim["id"]])
        assert claim_rows[0]["status"] == "TRIAGE"
