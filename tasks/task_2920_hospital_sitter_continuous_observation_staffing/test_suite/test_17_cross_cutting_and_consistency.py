"""
Cross-cutting layers and the consistency model: the one optimistic-concurrency guard
in the API and the re-read that clears it, the asymmetry between a reversal that
never releases a restricted unit and the cost close that does, and the single
schedule whose every derived consequence is already readable on the next request.
"""

from test_helpers import (
    HTTP_CREATED,
    HTTP_PRECONDITION_FAILED,
    ObservationApiClient,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_fields, assert_row_count, exactly_one
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    COST_POSTED,
    COST_REVERSED,
    DOC_PENDING,
    DOC_WAIVED,
    ENTRY_KIND_PROVISIONAL,
    ERR_STALE_ORDER_VERSION,
    MODALITY_ONE_TO_ONE_SITTER,
    ORDER_ACTIVE,
    POOL_INTERNAL_FLOAT,
    RESTRICTION_BUDGET_THRESHOLD_REACHED,
    RISK_FALL,
    STAFF_AVAILABLE,
    UNIT_OPEN,
    UNIT_RESTRICTED,
    WATCH_SCHEDULED,
    WATCH_VOIDED,
)
from test_helpers.factories import assignment_payload, cost_close_payload
from test_helpers.fixtures import (
    advance_clock,
    make_assignment,
    make_order,
    make_patient,
    make_staff,
    make_unit,
    order_assignments,
    read_assignment,
    read_order,
    read_staff,
    read_unit,
    unit_cost_entries,
)
from test_helpers.test_users import COORDINATOR, MANAGER, PROVIDER_1

CERT_VALID = "2027-01-01T00:00:00Z"


class TestOptimisticConcurrencyOnTheOrder:
    """The API's only version-guarded write, refused on a stale token and retried."""

    def test_a_stale_order_version_is_refused_and_the_reread_retry_succeeds(
        self, api: ObservationApiClient
    ) -> None:
        """
        A relief watch that is a perfectly legal business action is refused with
        `ERR_STALE_ORDER_VERSION` purely because the first schedule advanced the order's
        `version` after the coordinator read it; the refusal writes no assignment, no
        ledger row and no unit mutation, and the byte-identical body re-sent with the
        re-read version is accepted, which is what proves the refusal was about the token
        and not about the watch.

        PRD 2.8: "Scheduling a sitter watch — `POST /observation/sitter-assignments` —
        requires a non-optional `expected_order_version` field carrying the `version` of the
        target `ObservationOrder` as the client last observed it."
        PRD 2.8: "If `expected_order_version` does not equal the order's current `version`,
        the request is rejected with `ERR_STALE_ORDER_VERSION` and HTTP 412, and no
        assignment row, no cost row and no unit mutation results."
        PRD 2.8: "One consequence follows directly and is intentional: because a successful
        schedule increments the order's `version` by 1, replaying the identical request with
        the same `expected_order_version` fails the second time with
        `ERR_STALE_ORDER_VERSION`."
        PRD 2.8: "The check forces the coordinator to re-read the order before spending money
        on it."
        PRD 2.6: "Optimistic concurrency on the observation order — `ERR_STALE_ORDER_VERSION`."
        PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant
        refreshed on every mutation, and `version`, an integer that starts at 1 on creation
        and increments by exactly 1 on every mutation of that resource — including mutations
        the server performs on its own initiative as part of a cascade, and including
        mutations that only touch a derived field such as a recomputed ledger head or feed
        count."
        PRD 3.1: "Two derived figures ride along on the observer record: `last_shift_end_at`
        is the latest `shift_end_at` among all of that observer's assignments whose
        `watch_status` is anything other than `VOIDED`, and is null when the observer holds no
        non-voided assignment at all; `total_watch_minutes` is the sum of closed watch-segment
        minutes across all of that observer's assignments whose `watch_status` is not
        `VOIDED`."
        PRD 3.4: "It bills the entire scheduled window at the observer's base rate scaled by
        their pool: the observer's `hourly_rate_cents` is multiplied by `scheduled_minutes`
        divided by 60, and that product is multiplied by the pool multiplier — 1.00 for
        `INTERNAL_FLOAT`, 1.45 for `AGENCY`, and 0.00 for `VOLUNTEER`, whose labor is donated
        and therefore free."
        PRD 3.4: "The order's `version`, the unit's `version` and the observer's `version`
        each advance by 1."
        PRD 2.10: "A unit's `observed_cost_to_date_cents` is the sum of `amount_cents` across
        every `CostEntry` whose `unit_id` is that unit and whose `status` is `POSTED`."

        Design: Corner/cross_cutting_layers/stale_order_version_is_refused_and_the_reread_retry_succeeds
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C51",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fiftyone",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C5101", full_name="Occ Patient", age_years=60
        )
        day_sitter = make_staff(
            api,
            unit["id"],
            full_name="Occ Sitter One",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        relief_sitter = make_staff(
            api,
            unit["id"],
            full_name="Occ Sitter Two",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Fall watch needing relief coverage",
        )
        version_as_read = order["version"]
        relief_version_before = relief_sitter["version"]

        first = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    day_sitter["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                    version_as_read,
                ),
                COORDINATOR,
            ),
            HTTP_CREATED,
        )
        assert_fields(first, label="the day watch", version=1, watch_status=WATCH_SCHEDULED)
        version_after_first = read_order(api, order["id"])["version"]
        assert version_after_first == version_as_read + 1, "the schedule bumped the order"

        relief_body = assignment_payload(
            order["id"],
            relief_sitter["id"],
            "2026-08-01T16:00:00Z",
            "2026-08-02T00:00:00Z",
            version_as_read,
        )
        validate_error(
            api.create_assignment(relief_body, COORDINATOR),
            ERR_STALE_ORDER_VERSION,
            HTTP_PRECONDITION_FAILED,
        )
        assert_row_count(
            order_assignments(api, order["id"]), 1, "watches after the stale attempt"
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit after the stale attempt",
            observed_cost_to_date_cents=16000,
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the order after the stale attempt",
            version=version_after_first,
        )
        assert_fields(
            read_staff(api, relief_sitter["id"]),
            label="the relief sitter after the stale attempt",
            last_shift_end_at=None,
            version=relief_version_before,
        )

        retry_body = assignment_payload(
            order["id"],
            relief_sitter["id"],
            "2026-08-01T16:00:00Z",
            "2026-08-02T00:00:00Z",
            version_after_first,
        )
        assert {k: v for k, v in retry_body.items() if k != "expected_order_version"} == {
            k: v for k, v in relief_body.items() if k != "expected_order_version"
        }, "the retry differs from the refused body only in the version token"
        relief = validate_success(
            api.create_assignment(retry_body, COORDINATOR), HTTP_CREATED
        )
        assert_fields(
            relief,
            label="the relief watch on the re-read version",
            version=1,
            watch_status=WATCH_SCHEDULED,
            provisional_cost_cents=16000,
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit carrying both watches",
            observed_cost_to_date_cents=32000,
        )
        assert_row_count(
            order_assignments(api, order["id"]), 2, "watches after the retry"
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the order after the retry",
            version=version_after_first + 1,
        )
        assert_fields(
            read_staff(api, relief_sitter["id"]),
            label="the relief sitter after the retry",
            last_shift_end_at="2026-08-02T00:00:00.000Z",
            version=relief_version_before + 1,
        )


class TestUnitRestrictionLifecycle:
    """A threshold that engages inside a posting request and only ever lifts on a close."""

    def test_a_reversal_never_releases_the_unit_and_only_the_cost_close_does(
        self, api: ObservationApiClient
    ) -> None:
        """
        Two watches take the ledger head to exactly the budget, which restricts the unit on
        the inclusive threshold. Voiding the second watch reverses its row and drops the head
        well below the budget, and the unit stays `RESTRICTED` regardless; only the cost close
        lifts it — landing on the bottom surcharge tier, where the charge equals the subtotal
        to the cent, and moving no money at all.

        PRD 3.4: "First, the candidate watch is costed provisionally, and the unit's current
        `observed_cost_to_date_cents` plus that `provisional_cost_cents` must not exceed the
        unit's `observation_cost_budget_cents`."
        PRD 3.4: "The comparison is generous at the boundary — a total that lands exactly on the
        budget is accepted, and only a total strictly greater than the budget is rejected, with
        `ERR_UNIT_BUDGET_EXCEEDED` and HTTP 402."
        PRD 3.4: "The unit's `observed_cost_to_date_cents` is then recomputed over the posted
        set, and if the recomputed head has reached or passed `observation_cost_budget_cents`
        the unit transitions `OPEN → RESTRICTED` with `restriction_reason` set to
        `BUDGET_THRESHOLD_REACHED` — the threshold is inclusive, so a head exactly equal to the
        budget restricts the unit."
        PRD 3.5: "Voiding stamps `voided_at`, moves `documentation_status` `PENDING → WAIVED`,
        and sets the assignment's `PROVISIONAL` ledger row to `REVERSED` with `reversed_at`
        stamped and `amount_cents` untouched."
        PRD 3.5: "One thing a reversal explicitly does **not** do is change the unit's posture:
        a `RESTRICTED` unit stays `RESTRICTED` even when the reversal drops the ledger head well
        back below the budget."
        PRD 3.5: "The only operation that lifts a restriction is the cost close described in
        §3.9."
        PRD 3.9: "Step one computes `subtotal_cents` as the exact integer sum of `amount_cents`
        over the unit's ledger rows whose `status` is `POSTED` and whose `posted_at` falls
        strictly before `close_through_utc`; the bound is strict, so a row posted at exactly
        `close_through_utc` is excluded, and rows in `status` `REVERSED` are excluded entirely —
        which is why a voided watch leaves no trace whatsoever in the charge."
        PRD 3.9: "Step two selects `coverage_surcharge_pct` from a tier keyed on
        `subtotal_cents` **alone**, over inclusive thresholds: a subtotal of 150000 cents or
        more takes 0.12, a subtotal below that but 60000 cents or more takes 0.08, a subtotal
        below that but 20000 cents or more takes 0.04, and anything below 20000 cents takes
        0.00."
        PRD 3.9: "Step four computes `charge_total_cents` as `subtotal_cents` plus
        `coverage_surcharge_cents`."
        PRD 3.9: "The response returns `subtotal_cents`, `coverage_surcharge_pct`,
        `coverage_surcharge_cents` and `charge_total_cents`, together with the unit's resulting
        posture as `unit_status` and its resulting `version` as `unit_version`."
        PRD 3.9: "A unit in `RESTRICTED` then transitions `RESTRICTED → OPEN` with
        `restriction_reason` cleared to null when two conditions hold together: the unit's
        `observed_cost_to_date_cents` is strictly less than the (possibly just-increased)
        `observation_cost_budget_cents`, and no observation order on this unit sits in `LAPSED`."
        PRD 3.9: "No ledger row is created, mutated or reversed by a cost close under any
        circumstances, and the unit's `version` advances by 1."
        PRD 2.10: "A unit's `observed_cost_to_date_cents` is the sum of `amount_cents` across
        every `CostEntry` whose `unit_id` is that unit and whose `status` is `POSTED`."

        Design: Corner/cross_cutting_layers/unit_restriction_resets_only_after_a_reversal_and_a_close
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C52",
            budget_cents=30000,
            video_monitoring_enabled=False,
            name="Corner Unit Fiftytwo",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C5201", full_name="Reset Patient", age_years=60
        )
        keeper = make_staff(
            api,
            unit["id"],
            full_name="Reset Sitter One",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        voided_sitter = make_staff(
            api,
            unit["id"],
            full_name="Reset Sitter Two",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Fall watch on a capped budget",
        )
        kept = make_assignment(
            api,
            order["id"],
            keeper["id"],
            "2026-08-01T08:00:00Z",
            "2026-08-01T16:00:00Z",
        )
        doomed = make_assignment(
            api,
            order["id"],
            voided_sitter["id"],
            "2026-08-01T16:00:00Z",
            "2026-08-01T23:00:00Z",
        )
        assert_fields(kept, label="the eight-hour watch", provisional_cost_cents=16000)
        assert_fields(doomed, label="the seven-hour watch", provisional_cost_cents=14000)
        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit spent exactly to its budget",
            observed_cost_to_date_cents=30000,
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_BUDGET_THRESHOLD_REACHED,
        )

        voided = validate_success(api.void_assignment(doomed["id"], MANAGER))
        assert_fields(
            voided,
            label="the voided watch",
            watch_status=WATCH_VOIDED,
            documentation_status=DOC_WAIVED,
            voided_at=CLOCK_START,
        )
        reversed_row = exactly_one(
            unit_cost_entries(api, unit["id"]),
            assignment_id=doomed["id"],
            status=COST_REVERSED,
        )
        assert_fields(
            reversed_row,
            label="the reversed provisional row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            amount_cents=14000,
            reversed_at=CLOCK_START,
        )
        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit after the reversal",
            observed_cost_to_date_cents=16000,
            status=UNIT_RESTRICTED,
            restriction_reason=RESTRICTION_BUDGET_THRESHOLD_REACHED,
        )

        advance_clock(api, "2026-08-01T06:00:00Z")
        close = validate_success(
            api.cost_close(
                unit["id"], cost_close_payload("2026-08-01T06:00:00Z"), COORDINATOR
            )
        )
        assert_fields(
            close,
            label="the cost close on the bottom tier",
            subtotal_cents=16000,
            coverage_surcharge_pct=0.00,
            coverage_surcharge_cents=0,
            charge_total_cents=16000,
            unit_status=UNIT_OPEN,
        )
        reopened = read_unit(api, unit["id"])
        assert_fields(
            reopened,
            label="the reopened unit",
            status=UNIT_OPEN,
            restriction_reason=None,
            observed_cost_to_date_cents=16000,
        )
        assert close["unit_version"] == reopened["version"], "the close reports the new version"

        entries = unit_cost_entries(api, unit["id"])
        assert_row_count(entries, 2, "ledger rows the close left alone")
        surviving = exactly_one(entries, assignment_id=kept["id"], status=COST_POSTED)
        assert_fields(
            surviving,
            label="the surviving posted row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            amount_cents=16000,
            reversed_at=None,
        )
        assert_fields(
            read_assignment(api, kept["id"]),
            label="the watch the close never touched",
            watch_status=WATCH_SCHEDULED,
            documentation_status=DOC_PENDING,
        )


class TestImmediateVisibilityOfDerivedFields:
    """One write, and every derived consequence already readable on the next request."""

    def test_one_schedule_publishes_its_ledger_marker_and_version_effects_at_once(
        self, api: ObservationApiClient
    ) -> None:
        """
        A single schedule must publish everything it derives inside the request that made
        it: its own computed window and provisional charge in the create response, and the
        unit's recomputed ledger head, the observer's recomputed next-shift marker and the
        order's bumped version on the very next plain read of each, with no settling step,
        no filter and no retry.

        PRD 3.4: "The new assignment lands with `watch_status` at `SCHEDULED` and
        `documentation_status` at `PENDING`, with `scheduled_minutes` derived as the whole
        minutes between `shift_start_at` and `shift_end_at`, and with `final_cost_cents`,
        `current_segment_started_at`, `break_started_at`, `completion_reason` and
        `voided_at` all null and `watch_segment_count` and `watched_minutes` both 0."
        PRD 3.4: "It bills the entire scheduled window at the observer's base rate scaled by
        their pool: the observer's `hourly_rate_cents` is multiplied by `scheduled_minutes`
        divided by 60, and that product is multiplied by the pool multiplier — 1.00 for
        `INTERNAL_FLOAT`, 1.45 for `AGENCY`, and 0.00 for `VOLUNTEER`, whose labor is donated
        and therefore free."
        PRD 3.4: "The row copies the `unit_id` from the unit occupied by the patient of the
        assignment's order, records the `assignment_id` it bills, carries the provisional
        figure as `amount_cents`, opens in `status` `POSTED` with `posted_at` stamped from the
        logical clock and `reversed_at` null, freezes the observer's `source_pool` as of this
        moment, sets `night_differential_applied` to `false`, and leaves both `segment_index`
        and `segment_minutes` null because a provisional row bills no particular segment."
        PRD 3.4: "The observer's `last_shift_end_at` is recomputed as well, but the observer's
        `status` is explicitly not changed by scheduling."
        PRD 3.4: "The order's `version`, the unit's `version` and the observer's `version`
        each advance by 1."
        PRD 3.1: "Two derived figures ride along on the observer record: `last_shift_end_at`
        is the latest `shift_end_at` among all of that observer's assignments whose
        `watch_status` is anything other than `VOIDED`, and is null when the observer holds no
        non-voided assignment at all; `total_watch_minutes` is the sum of closed watch-segment
        minutes across all of that observer's assignments whose `watch_status` is not
        `VOIDED`."
        PRD 3.1: "The `open_order_count` field is a derived figure — the number of observation
        orders written for patients who occupy this unit whose own status is `ACTIVE`,
        `REASSESSMENT_DUE`, `ESCALATED` or `DISCONTINUATION_REVIEW` — and it is recomputed
        whenever a new order is written for one of the unit's patients, which is itself a
        mutation of the unit and therefore advances the unit's `version` by 1."
        PRD 2.10: "A unit's `observed_cost_to_date_cents` is the sum of `amount_cents` across
        every `CostEntry` whose `unit_id` is that unit and whose `status` is `POSTED`."
        PRD 2.10: "It is recomputed in full — over the whole posted set, never as an
        incremental delta applied to the previous value — on every single post and every single
        reversal, wherever those occur: scheduling a watch, starting a break, completing a
        watch, voiding a watch, and every cascade that posts or reverses on the system's own
        initiative."
        PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant
        refreshed on every mutation, and `version`, an integer that starts at 1 on creation
        and increments by exactly 1 on every mutation of that resource — including mutations
        the server performs on its own initiative as part of a cascade, and including
        mutations that only touch a derived field such as a recomputed ledger head or feed
        count."

        Design: Corner/consistency_model/derived_ledger_and_version_fields_never_lag_a_request
        """
        unit = make_unit(
            api,
            unit_code="UNIT-C53",
            budget_cents=250000,
            video_monitoring_enabled=False,
            name="Corner Unit Fiftythree",
        )
        patient = make_patient(
            api, unit["id"], mrn="MRN-C5301", full_name="Immediate Patient", age_years=60
        )
        sitter = make_staff(
            api,
            unit["id"],
            full_name="Immediate Sitter",
            source_pool=POOL_INTERNAL_FLOAT,
            hourly_rate_cents=2000,
            competency_level=COMPETENCY_ADVANCED,
            deescalation_cert_expires_on=CERT_VALID,
        )
        order = make_order(
            api,
            patient["id"],
            provider_headers=PROVIDER_1,
            risk_categories=[RISK_FALL],
            required_modality=MODALITY_ONE_TO_ONE_SITTER,
            clinical_rationale="Fall watch, single shift",
        )
        order_version_before = order["version"]

        watch = validate_success(
            api.create_assignment(
                assignment_payload(
                    order["id"],
                    sitter["id"],
                    "2026-08-01T08:00:00Z",
                    "2026-08-01T16:00:00Z",
                    order_version_before,
                ),
                COORDINATOR,
            ),
            HTTP_CREATED,
        )
        assert_fields(
            watch,
            label="the create response itself",
            scheduled_minutes=480,
            provisional_cost_cents=16000,
            watch_status=WATCH_SCHEDULED,
            documentation_status=DOC_PENDING,
            version=1,
            final_cost_cents=None,
            current_segment_started_at=None,
            break_started_at=None,
            completion_reason=None,
            voided_at=None,
            watch_segment_count=0,
            watched_minutes=0,
        )

        assert_fields(
            read_unit(api, unit["id"]),
            label="the unit on the very next read",
            observed_cost_to_date_cents=16000,
            open_order_count=1,
            status=UNIT_OPEN,
        )
        assert_fields(
            read_staff(api, sitter["id"]),
            label="the observer on the very next read",
            last_shift_end_at="2026-08-01T16:00:00.000Z",
            status=STAFF_AVAILABLE,
            total_watch_minutes=0,
        )
        assert_fields(
            read_order(api, order["id"]),
            label="the order on the very next read",
            version=order_version_before + 1,
            status=ORDER_ACTIVE,
        )

        entries = unit_cost_entries(api, unit["id"])
        assert_row_count(entries, 1, "ledger rows after the single schedule")
        assert_fields(
            entries[0],
            label="the provisional row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            status=COST_POSTED,
            amount_cents=16000,
            posted_at=CLOCK_START,
            reversed_at=None,
            unit_id=unit["id"],
            assignment_id=watch["id"],
            source_pool=POOL_INTERNAL_FLOAT,
            night_differential_applied=False,
            segment_index=None,
            segment_minutes=None,
        )
