"""Dataset lifecycle: delivery, the cleaning-lock gates, quarantine and requalification.

Every test builds its own preconditions through the endpoints of PRD S4, because
the harness restarts the server and wipes the database before each test.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_DATASET_DOCUMENTATION_INCOMPLETE,
    ERR_DATASET_NOT_FOUND,
    ERR_DATASET_NOT_LINKED,
    ERR_FIELD_LIMIT_EXCEEDED,
    ERR_FIELD_NAME_CONFLICT,
    ERR_FIELD_NOT_FOUND,
    ERR_FORMAT_NOT_NEGOTIATED,
    ERR_INVESTIGATION_NOT_FOUND,
    ERR_SOURCE_REQUEST_UNRESOLVED,
)
from test_helpers.assertions import (
    assert_deadline_stamp,
    assert_field_absent_or_null,
    assert_partition_counts,
    assert_version_is,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated_page,
)
from test_helpers.test_users import editor_headers, reporter_headers, coordinator_headers


class TestDatasetDeliveryTransition:
    """Delivery drives RAW -> CLEANING and fixes the retention horizon."""

    @staticmethod
    def _raw_dataset_ready_for_delivery(api):
        """A RAW dataset on a RELEASED request under a 365-day retention desk."""
        X.set_clock(api, C.STD_CLOCK)
        desk, agency = X.desk_and_agency(
            api, desk_overrides={"retention_policy_days": 365}
        )
        request = X.released_request(api, desk["id"], agency["id"])
        investigation = X.create_investigation(
            api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Delivery probe"
        )
        dataset = X.register_dataset(
            api,
            request["id"],
            investigation["id"],
            name=F.unique_dataset_name("delivery-probe"),
            negotiated_format=C.FORMAT_CSV,
            expected_field_count=1,
            sensitivity_tier="PUBLIC",
        )
        X.set_clock(api, "2026-08-20T14:30:00Z")
        return request, dataset

    def test_delivery_moves_raw_to_cleaning_and_agrees_the_matching_format(self, api):
        """A delivery in the negotiated format leaves RAW for CLEANING as AGREED.

        PRD S3.6: "It records the `delivered_format` the agency really sent and
        the `record_count` of rows received, and it drives `RAW -> CLEANING`. ...
        `format_negotiation_status` becomes `AGREED` when `delivered_format`
        equals `negotiated_format`, and `REFUSED` when it does not."

        Design: Corner/state_machines/dataset_delivery_moves_raw_to_cleaning_and_stamps_the_retention_clock
        """
        _request, dataset = self._raw_dataset_ready_for_delivery(api)

        delivered = validate_ok(
            api.deliver_dataset(
                dataset["id"],
                F.delivery_payload(C.FORMAT_CSV, 4200),
                reporter_headers(),
            )
        )

        assert delivered["status"] == C.DS_CLEANING
        assert delivered["delivered_format"] == C.FORMAT_CSV
        assert delivered["record_count"] == 4200
        assert delivered["format_negotiation_status"] == C.FORMAT_NEG_AGREED
        assert_field_absent_or_null(delivered, "quarantine_reason_code", "dataset")
        assert_version_is(delivered, 2, "dataset")

    def test_delivery_stamps_the_retention_clock_from_the_desks_calendar_horizon(
        self, api
    ):
        """The retention horizon is 365 calendar days from the delivery instant.

        PRD S3.6: "`retention_expires_at` is the UTC calendar date of the
        delivery instant advanced by the owning desk's `retention_policy_days` in
        **calendar** days -- retention never uses the agency's `deadline_basis`
        -- stamped at `23:59:59.000Z` ... under the minimum 365-day policy at
        `2027-08-20T23:59:59.000Z`."

        Design: Corner/state_machines/dataset_delivery_moves_raw_to_cleaning_and_stamps_the_retention_clock
        """
        _request, dataset = self._raw_dataset_ready_for_delivery(api)

        delivered = validate_ok(
            api.deliver_dataset(
                dataset["id"],
                F.delivery_payload(C.FORMAT_CSV, 4200),
                reporter_headers(),
            )
        )

        assert_deadline_stamp(
            delivered["retention_expires_at"], "2027-08-20", "retention_expires_at"
        )

    def test_delivery_is_persisted_and_leaves_the_parent_request_untouched(self, api):
        """The CLEANING row survives a re-read and the parent request stays RELEASED.

        PRD S2.4: "A read that merely returns a resource never advances
        `version`."

        Design: Corner/state_machines/dataset_delivery_moves_raw_to_cleaning_and_stamps_the_retention_clock
        """
        request, dataset = self._raw_dataset_ready_for_delivery(api)

        validate_ok(
            api.deliver_dataset(
                dataset["id"],
                F.delivery_payload(C.FORMAT_CSV, 4200),
                reporter_headers(),
            )
        )

        reread = validate_ok(api.get_dataset(dataset["id"], reporter_headers()))
        assert reread["status"] == C.DS_CLEANING
        assert reread["record_count"] == 4200
        assert reread["format_negotiation_status"] == C.FORMAT_NEG_AGREED
        assert_deadline_stamp(
            reread["retention_expires_at"], "2027-08-20", "retention_expires_at"
        )
        assert_version_is(reread, 2, "dataset")

        parent = validate_ok(
            api.get_records_request(request["id"], coordinator_headers())
        )
        assert parent["status"] == C.REQ_RELEASED


class TestCleaningLockGateLadder:
    """The cleaning lock refuses each unmet gate on its own, then succeeds."""

    @staticmethod
    def _investigation_on_released_request(api):
        """A RELEASED request plus an investigation on the same desk."""
        X.set_clock(api, C.STD_CLOCK)
        desk, agency = X.desk_and_agency(
            api, desk_overrides={"retention_policy_days": 365}
        )
        request = X.released_request(
            api, desk["id"], agency["id"], subject_summary="Cleaning lock probe"
        )
        investigation = X.create_investigation(
            api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Cleaning lock probe"
        )
        return request, investigation

    @classmethod
    def _refused_format_dataset(cls, api, request, investigation):
        """A CLEANING dataset whose delivered format was not the negotiated one."""
        return X.delivered_dataset(
            api,
            request["id"],
            investigation["id"],
            500,
            C.FORMAT_XLSX,
            name=F.unique_dataset_name("ds-refused"),
            negotiated_format=C.FORMAT_CSV,
            expected_field_count=2,
            sensitivity_tier="PUBLIC",
        )

    def test_documenting_every_expected_column_completes_the_documentation(self, api):
        """Two of two expected columns flip documentation_status to COMPLETE.

        PRD S3.6: "Each new definition ... increments the dataset's
        `field_definition_count` by 1 ... and sets `documentation_status` to
        `COMPLETE` once `field_definition_count` has reached
        `expected_field_count` (which is always at least 1) and `INCOMPLETE`
        otherwise."

        Design: Corner/state_machines/cleaning_lock_enforces_documentation_then_format_and_then_succeeds
        """
        request, investigation = self._investigation_on_released_request(api)
        dataset = self._refused_format_dataset(api, request, investigation)

        after_first = X.document_field(
            api, dataset["id"], "case_number", data_type="STRING", null_rate_pct=0.0
        )
        assert after_first["field_name"] == "case_number"
        interim = X.read_dataset(api, dataset["id"])
        assert interim["field_definition_count"] == 1
        assert interim["documentation_status"] == C.DOC_STATUS_INCOMPLETE

        X.document_field(
            api, dataset["id"], "closed_on", data_type="DATE", null_rate_pct=12.5
        )
        final = X.read_dataset(api, dataset["id"])
        assert final["field_definition_count"] == 2
        assert final["documentation_status"] == C.DOC_STATUS_COMPLETE

    def test_cleaning_lock_refuses_a_refused_format_once_documentation_is_complete(
        self, api
    ):
        """With documentation COMPLETE the only remaining violation is the format.

        PRD S3.6: "It accepts `cleaning_notes` and drives `CLEANING ->
        CLEAN_LOCKED`, but only past two gates ... `format_negotiation_status`
        must be `AGREED`, otherwise `ERR_FORMAT_NOT_NEGOTIATED` -- a `REFUSED`
        format has to be renegotiated with the agency and redelivered".

        Design: Corner/state_machines/cleaning_lock_enforces_documentation_then_format_and_then_succeeds
        """
        request, investigation = self._investigation_on_released_request(api)
        dataset = self._refused_format_dataset(api, request, investigation)
        X.document_field(
            api, dataset["id"], "case_number", data_type="STRING", null_rate_pct=0.0
        )
        X.document_field(
            api, dataset["id"], "closed_on", data_type="DATE", null_rate_pct=12.5
        )

        validate_error(
            api.lock_cleaning(
                dataset["id"],
                F.cleaning_lock_payload(
                    cleaning_notes="Documentation now complete; format still refused."
                ),
                reporter_headers(),
            ),
            ERR_FORMAT_NOT_NEGOTIATED,
        )

        after = X.read_dataset(api, dataset["id"])
        assert after["status"] == C.DS_CLEANING
        assert after["format_negotiation_status"] == C.FORMAT_NEG_REFUSED
        assert after["documentation_status"] == C.DOC_STATUS_COMPLETE

    def test_cleaning_lock_refuses_incomplete_documentation_on_an_agreed_format(
        self, api
    ):
        """An AGREED format alone is not enough while a column is undocumented.

        PRD S3.6: "`documentation_status` must be `COMPLETE`, otherwise
        `ERR_DATASET_DOCUMENTATION_INCOMPLETE`."

        Design: Corner/state_machines/cleaning_lock_enforces_documentation_then_format_and_then_succeeds
        """
        request, investigation = self._investigation_on_released_request(api)
        dataset = X.delivered_dataset(
            api,
            request["id"],
            investigation["id"],
            500,
            C.FORMAT_CSV,
            name=F.unique_dataset_name("ds-undocumented"),
            negotiated_format=C.FORMAT_CSV,
            expected_field_count=1,
            sensitivity_tier="PUBLIC",
        )
        assert dataset["format_negotiation_status"] == C.FORMAT_NEG_AGREED
        assert dataset["documentation_status"] == C.DOC_STATUS_INCOMPLETE

        validate_error(
            api.lock_cleaning(
                dataset["id"],
                F.cleaning_lock_payload(cleaning_notes="No columns documented yet."),
                reporter_headers(),
            ),
            ERR_DATASET_DOCUMENTATION_INCOMPLETE,
        )

        after = X.read_dataset(api, dataset["id"])
        assert after["status"] == C.DS_CLEANING
        assert after["field_definition_count"] == 0

    def test_cleaning_lock_succeeds_when_both_gates_are_cleared(self, api):
        """AGREED plus COMPLETE clears both gates and freezes the dataset.

        PRD S3.6: "The cleaning lock freezes the dataset for analysis. It accepts
        `cleaning_notes` and drives `CLEANING -> CLEAN_LOCKED`".

        Design: Corner/state_machines/cleaning_lock_enforces_documentation_then_format_and_then_succeeds
        """
        request, investigation = self._investigation_on_released_request(api)
        still_cleaning = self._refused_format_dataset(api, request, investigation)
        dataset = X.delivered_dataset(
            api,
            request["id"],
            investigation["id"],
            500,
            C.FORMAT_CSV,
            name=F.unique_dataset_name("ds-clean"),
            negotiated_format=C.FORMAT_CSV,
            expected_field_count=1,
            sensitivity_tier="PUBLIC",
        )
        X.document_field(
            api, dataset["id"], "case_number", data_type="STRING", null_rate_pct=0.0
        )

        locked = validate_ok(
            api.lock_cleaning(
                dataset["id"],
                F.cleaning_lock_payload(
                    cleaning_notes="Both preconditions satisfied."
                ),
                reporter_headers(),
            )
        )
        assert locked["status"] == C.DS_CLEAN_LOCKED

        rows, meta = validate_paginated_page(
            api.list_datasets(
                reporter_headers(),
                {
                    "investigation_id": investigation["id"],
                    "status": C.DS_CLEAN_LOCKED,
                },
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [dataset["id"]]
        assert still_cleaning["id"] != dataset["id"]


class TestQuarantineRequalificationCycle:
    """Quarantine is not a dead end: the lifecycle is a genuine cycle."""

    _FIELD_SPECS = [
        {
            "field_name": "unit_count",
            "data_type": "INTEGER",
            "null_rate_pct": 0.0,
            "reidentification_risk": 1,
        }
    ]

    @classmethod
    def _clean_locked(cls, api):
        """One CLEAN_LOCKED dataset of 900 records on its own investigation."""
        X.set_clock(api, C.STD_CLOCK)
        desk, agency = X.desk_and_agency(
            api, desk_overrides={"retention_policy_days": 365}
        )
        request = X.released_request(
            api, desk["id"], agency["id"], subject_summary="Cycle probe"
        )
        investigation = X.create_investigation(
            api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Cycle probe"
        )
        dataset = X.clean_locked_dataset(
            api,
            request["id"],
            investigation["id"],
            900,
            cls._FIELD_SPECS,
            name=F.unique_dataset_name("cycle-probe"),
            negotiated_format=C.FORMAT_CSV,
            sensitivity_tier="PUBLIC",
        )
        return dataset

    def test_requalification_clears_the_quarantine_reason_back_to_null(self, api):
        """Quarantine records a reason and zeroes the allocation; requalification clears it.

        PRD S3.6: "Requalification accepts `remediation_notes`, drives
        `QUARANTINED -> CLEANING`, and clears `quarantine_reason_code` back to
        null".

        Design: Corner/state_machines/dataset_quarantine_and_requalification_loop_without_a_round_limit
        """
        dataset = self._clean_locked(api)

        quarantined = validate_ok(
            api.quarantine_dataset(
                dataset["id"],
                F.quarantine_payload("MISMATCHED_TOTALS"),
                editor_headers(),
            )
        )
        assert quarantined["status"] == C.DS_QUARANTINED
        assert quarantined["quarantine_reason_code"] == "MISMATCHED_TOTALS"
        assert quarantined["allocated_cost_cents"] == 0

        requalified = validate_ok(
            api.requalify_dataset(
                dataset["id"],
                F.requalification_payload(
                    remediation_notes=(
                        "Totals re-reconciled against the agency's certified summary."
                    )
                ),
                reporter_headers(),
            )
        )
        assert requalified["status"] == C.DS_CLEANING
        assert_field_absent_or_null(requalified, "quarantine_reason_code", "dataset")

    def test_a_requalified_dataset_locks_again_and_quarantines_on_a_new_reason(
        self, api
    ):
        """A remediated dataset re-locks, and the second reason replaces the first.

        PRD S3.6: "so a remediated dataset can be documented further, locked
        again, and made allocable again -- the dataset lifecycle is a genuine
        cycle."

        Design: Corner/state_machines/dataset_quarantine_and_requalification_loop_without_a_round_limit
        """
        dataset = self._clean_locked(api)
        validate_ok(
            api.quarantine_dataset(
                dataset["id"],
                F.quarantine_payload("MISMATCHED_TOTALS"),
                editor_headers(),
            )
        )
        validate_ok(
            api.requalify_dataset(
                dataset["id"], F.requalification_payload(), reporter_headers()
            )
        )

        relocked = validate_ok(
            api.lock_cleaning(
                dataset["id"],
                F.cleaning_lock_payload(
                    cleaning_notes="Second lock, first lap complete."
                ),
                reporter_headers(),
            )
        )
        assert relocked["status"] == C.DS_CLEAN_LOCKED
        assert relocked["documentation_status"] == C.DOC_STATUS_COMPLETE
        assert relocked["format_negotiation_status"] == C.FORMAT_NEG_AGREED

        requarantined = validate_ok(
            api.quarantine_dataset(
                dataset["id"],
                F.quarantine_payload("UNRESOLVED_NULLS"),
                editor_headers(),
            )
        )
        assert requarantined["status"] == C.DS_QUARANTINED
        assert requarantined["quarantine_reason_code"] == "UNRESOLVED_NULLS"

    def test_two_full_laps_are_accepted_and_leave_the_delivery_facts_intact(self, api):
        """The cycle carries no round limit and never rewrites the delivery.

        PRD S3.6: "The dataset's `version`, each affected run's `version` and the
        investigation's `version` each increment by 1."

        Design: Corner/state_machines/dataset_quarantine_and_requalification_loop_without_a_round_limit
        """
        dataset = self._clean_locked(api)
        version_before = dataset["version"]

        for reason, notes in (
            ("MISMATCHED_TOTALS", "Totals re-reconciled."),
            ("UNRESOLVED_NULLS", "Null-coded rows resolved against the source ledger."),
        ):
            validate_ok(
                api.quarantine_dataset(
                    dataset["id"], F.quarantine_payload(reason), editor_headers()
                )
            )
            validate_ok(
                api.requalify_dataset(
                    dataset["id"],
                    F.requalification_payload(remediation_notes=notes),
                    reporter_headers(),
                )
            )
            relocked = validate_ok(
                api.lock_cleaning(
                    dataset["id"],
                    F.cleaning_lock_payload(cleaning_notes="Lap complete."),
                    reporter_headers(),
                )
            )
            assert relocked["status"] == C.DS_CLEAN_LOCKED

        final = X.read_dataset(api, dataset["id"])
        assert final["status"] == C.DS_CLEAN_LOCKED
        assert final["record_count"] == 900
        assert final["delivered_format"] == C.FORMAT_CSV
        assert_version_is(final, version_before + 6, "dataset")


class TestFieldDefinitionParentResolution:
    """A field definition lives strictly inside one addressed parent dataset."""

    @staticmethod
    def _two_documented_datasets(api):
        """Two RAW sibling datasets, each carrying exactly one documented column."""
        X.set_clock(api, C.STD_CLOCK)
        desk, agency = X.desk_and_agency(
            api, desk_overrides={"retention_policy_days": 1095}
        )
        request = X.draft_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Parent relationship probe",
        )
        investigation = X.create_investigation(
            api,
            desk["id"],
            C.MODE_METHODOLOGY_ONLY,
            headline="Parent relationship probe",
        )
        datasets = []
        for prefix in ("ds-a", "ds-b"):
            datasets.append(
                X.register_dataset(
                    api,
                    request["id"],
                    investigation["id"],
                    name=F.unique_dataset_name(prefix),
                    negotiated_format=C.FORMAT_CSV,
                    expected_field_count=1,
                    sensitivity_tier="PUBLIC",
                )
            )
        ds_a, ds_b = datasets
        fd_a = X.document_field(
            api, ds_a["id"], "field_of_a", data_type="STRING", null_rate_pct=0.0
        )
        fd_b = X.document_field(
            api, ds_b["id"], "field_of_b", data_type="STRING", null_rate_pct=0.0
        )
        return ds_a, ds_b, fd_a, fd_b

    def test_field_definition_endpoints_reject_an_unresolvable_parent_dataset(
        self, api
    ):
        """Both the create and the list resolve the path parent before anything else.

        PRD S2.11: "On every endpoint with path parameters, each path parameter
        must resolve to an existing entity, checked left to right, with the
        leftmost unresolved segment determining which not-found code is
        returned."

        Design: Corner/entities/field_definition_requires_an_existing_parent_dataset
        """
        self._two_documented_datasets(api)

        validate_error(
            api.create_field_definition(
                C.UNRESOLVABLE_ID,
                F.field_definition_payload(
                    "orphan_field", reidentification_risk=1, null_rate_pct=0.0
                ),
                reporter_headers(),
            ),
            ERR_DATASET_NOT_FOUND,
        )
        validate_error(
            api.list_field_definitions(C.UNRESOLVABLE_ID, reporter_headers()),
            ERR_DATASET_NOT_FOUND,
        )

    def test_suppression_refuses_a_definition_owned_by_a_sibling_dataset(self, api):
        """A real definition of another dataset is as unfindable as a fictional one.

        PRD S3.6: "The named definition must belong to the addressed dataset,
        otherwise `ERR_FIELD_NOT_FOUND`".

        Design: Corner/entities/field_definition_requires_an_existing_parent_dataset
        """
        ds_a, _ds_b, _fd_a, fd_b = self._two_documented_datasets(api)

        validate_error(
            api.suppress_field(
                ds_a["id"],
                F.field_suppression_payload(
                    fd_b["id"], suppression_method="DROP_COLUMN"
                ),
                editor_headers(),
            ),
            ERR_FIELD_NOT_FOUND,
        )
        validate_error(
            api.suppress_field(
                ds_a["id"],
                F.field_suppression_payload(
                    C.UNRESOLVABLE_ID, suppression_method="DROP_COLUMN"
                ),
                editor_headers(),
            ),
            ERR_FIELD_NOT_FOUND,
        )

    def test_the_refused_cross_dataset_suppression_wrote_nothing(self, api):
        """Neither dataset gained or lost a column, and nothing was suppressed.

        PRD S3.6: "Suppression sets `suppression_applied` to true and records the
        method".

        Design: Corner/entities/field_definition_requires_an_existing_parent_dataset
        """
        ds_a, ds_b, _fd_a, fd_b = self._two_documented_datasets(api)
        validate_error(
            api.suppress_field(
                ds_a["id"],
                F.field_suppression_payload(
                    fd_b["id"], suppression_method="DROP_COLUMN"
                ),
                editor_headers(),
            ),
            ERR_FIELD_NOT_FOUND,
        )

        rows, meta = validate_paginated_page(
            api.list_field_definitions(ds_b["id"], reporter_headers())
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == fd_b["id"]
        assert rows[0]["suppression_applied"] is False
        assert_field_absent_or_null(rows[0], "suppression_method", "field definition")

        assert X.read_dataset(api, ds_a["id"])["field_definition_count"] == 1
        assert X.read_dataset(api, ds_b["id"])["field_definition_count"] == 1


class TestCrossDeskDatasetLinkage:
    """A dataset may only name an investigation on its own request's desk."""

    @staticmethod
    def _two_desks_one_request(api):
        """A request on desk A, one investigation per desk."""
        X.set_clock(api, C.STD_CLOCK)
        desk_a = X.create_desk(
            api, name="Metro Investigations Desk", retention_policy_days=1095
        )
        desk_b = X.create_desk(
            api, name="Statehouse Investigations Desk", retention_policy_days=1095
        )
        agency = X.create_agency(api)
        request_a = X.draft_request(
            api,
            desk_a["id"],
            agency["id"],
            subject_summary="Cross-desk linkage probe",
        )
        inv_a = X.create_investigation(
            api, desk_a["id"], C.MODE_METHODOLOGY_ONLY, headline="Desk A investigation"
        )
        inv_b = X.create_investigation(
            api, desk_b["id"], C.MODE_METHODOLOGY_ONLY, headline="Desk B investigation"
        )
        return request_a, inv_a, inv_b

    def test_dataset_creation_refuses_an_investigation_owned_by_another_desk(self, api):
        """Both references resolve, yet the desks do not match.

        PRD S3.6: "When an investigation is named, it must belong to the same desk
        as the named records request, otherwise the create is refused with
        `ERR_DATASET_NOT_LINKED`."

        Design: Corner/entities/dataset_creation_rejects_an_investigation_belonging_to_another_desk
        """
        request_a, _inv_a, inv_b = self._two_desks_one_request(api)

        validate_error(
            api.create_dataset(
                F.dataset_payload(
                    request_a["id"],
                    inv_b["id"],
                    name=F.unique_dataset_name("cross-desk-dataset"),
                    negotiated_format=C.FORMAT_CSV,
                    expected_field_count=1,
                    sensitivity_tier="PUBLIC",
                ),
                reporter_headers(),
            ),
            ERR_DATASET_NOT_LINKED,
        )

        _rows, meta = validate_paginated_page(
            api.list_datasets(reporter_headers(), {"investigation_id": inv_b["id"]})
        )
        assert meta["total_count"] == 0

    def test_an_unresolvable_investigation_is_not_found_before_the_linkage_check(
        self, api
    ):
        """Reference resolution answers first, so the linkage rule never runs.

        PRD S2.11: "On every endpoint carrying reference fields in the body, each
        reference must resolve to an existing entity, checked in the field order
        the input contract declares, yielding that entity's not-found code."

        Design: Corner/entities/dataset_creation_rejects_an_investigation_belonging_to_another_desk
        """
        request_a, _inv_a, _inv_b = self._two_desks_one_request(api)

        validate_error(
            api.create_dataset(
                F.dataset_payload(
                    request_a["id"],
                    C.UNRESOLVABLE_ID,
                    name=F.unique_dataset_name("cross-desk-dataset"),
                    negotiated_format=C.FORMAT_CSV,
                    expected_field_count=1,
                    sensitivity_tier="PUBLIC",
                ),
                reporter_headers(),
            ),
            ERR_INVESTIGATION_NOT_FOUND,
        )

    def test_the_refused_create_persisted_nothing_so_the_slug_is_still_free(self, api):
        """The same globally unique slug is accepted once the desks line up.

        PRD S3.6: "A fresh dataset opens in `RAW` with `format_negotiation_status`
        at `REQUESTED`, `documentation_status` at `INCOMPLETE`, `record_count` at
        0, `field_definition_count` at 0, `known_issue_count` at 0 and
        `allocated_cost_cents` at 0."

        Design: Corner/entities/dataset_creation_rejects_an_investigation_belonging_to_another_desk
        """
        request_a, inv_a, inv_b = self._two_desks_one_request(api)
        slug = F.unique_dataset_name("cross-desk-dataset")

        validate_error(
            api.create_dataset(
                F.dataset_payload(
                    request_a["id"],
                    inv_b["id"],
                    name=slug,
                    negotiated_format=C.FORMAT_CSV,
                    expected_field_count=1,
                    sensitivity_tier="PUBLIC",
                ),
                reporter_headers(),
            ),
            ERR_DATASET_NOT_LINKED,
        )

        created = validate_created(
            api.create_dataset(
                F.dataset_payload(
                    request_a["id"],
                    inv_a["id"],
                    name=slug,
                    negotiated_format=C.FORMAT_CSV,
                    expected_field_count=1,
                    sensitivity_tier="PUBLIC",
                ),
                reporter_headers(),
            )
        )
        assert created["name"] == slug
        assert created["investigation_id"] == inv_a["id"]
        assert created["request_id"] == request_a["id"]
        assert created["status"] == C.DS_RAW
        assert created["format_negotiation_status"] == C.FORMAT_NEG_REQUESTED
        assert created["documentation_status"] == C.DOC_STATUS_INCOMPLETE
        assert created["record_count"] == 0
        assert created["field_definition_count"] == 0
        assert created["known_issue_count"] == 0
        assert created["allocated_cost_cents"] == 0


class TestFieldDefinitionAggregateLimit:
    """Forty columns are allowed; the forty-first is refused in aggregate."""

    @staticmethod
    def _dataset_with_forty_columns(api):
        """A CLEANING dataset carrying exactly forty documented columns."""
        X.set_clock(api, C.STD_CLOCK)
        desk, agency = X.desk_and_agency(
            api,
            desk_overrides={"retention_policy_days": 1095},
            agency_overrides={
                "name": "Wide Schema Agency",
                "jurisdiction_code": "CA-WIDE",
                "tolling_allowed": False,
                "appeal_venue": C.VENUE_INTERNAL,
                "appeal_decision_days": 15,
            },
        )
        request = X.released_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Wide schema extract",
            public_interest_score=20,
        )
        investigation = X.create_investigation(
            api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Wide schema probe"
        )
        dataset = X.delivered_dataset(
            api,
            request["id"],
            investigation["id"],
            1200,
            C.FORMAT_CSV,
            name=F.unique_dataset_name("limit-probe"),
            negotiated_format=C.FORMAT_CSV,
            expected_field_count=C.MAX_FIELD_DEFINITIONS,
            sensitivity_tier="PUBLIC",
        )
        last = None
        for index in range(1, C.MAX_FIELD_DEFINITIONS + 1):
            last = validate_created(
                api.create_field_definition(
                    dataset["id"],
                    F.field_definition_payload(
                        f"field_{index:02d}",
                        reidentification_risk=1,
                        null_rate_pct=0.0,
                        data_type="STRING",
                    ),
                    reporter_headers(),
                )
            )
        return dataset, last

    def test_the_forty_first_column_is_refused_by_the_aggregate_count_alone(self, api):
        """Forty is a ceiling, not an exclusive bound, and the next one is refused.

        PRD S3.6: "A dataset may carry at most 40 documented columns, and the
        forty-first is refused with `ERR_FIELD_LIMIT_EXCEEDED`."

        Design: Corner/validations/field_definition_limit_binds_only_in_aggregate_and_name_conflict_wins
        """
        dataset, fortieth = self._dataset_with_forty_columns(api)
        assert fortieth["field_name"] == "field_40"

        validate_error(
            api.create_field_definition(
                dataset["id"],
                F.field_definition_payload(
                    "field_41",
                    reidentification_risk=1,
                    null_rate_pct=0.0,
                    data_type="STRING",
                ),
                reporter_headers(),
            ),
            ERR_FIELD_LIMIT_EXCEEDED,
        )

    def test_a_duplicate_name_at_the_limit_answers_with_the_name_conflict(self, api):
        """A call violating both rules gets the earlier rung of the ladder.

        PRD S2.11: "the rules are evaluated in ascending priority order, and the
        first rule whose condition is violated determines the response", with
        ``ERR_FIELD_NAME_CONFLICT`` at rung 36 and ``ERR_FIELD_LIMIT_EXCEEDED``
        at rung 37.

        Design: Corner/validations/field_definition_limit_binds_only_in_aggregate_and_name_conflict_wins
        """
        dataset, _fortieth = self._dataset_with_forty_columns(api)

        validate_error(
            api.create_field_definition(
                dataset["id"],
                F.field_definition_payload(
                    "field_01",
                    reidentification_risk=1,
                    null_rate_pct=0.0,
                    data_type="INTEGER",
                ),
                reporter_headers(),
            ),
            ERR_FIELD_NAME_CONFLICT,
        )

    def test_neither_refusal_wrote_to_the_dataset_or_its_columns(self, api):
        """The parent counters, version and the existing columns are all untouched.

        PRD S3.6: "Each new definition ... increments the dataset's
        `field_definition_count` by 1, adds the number of entries in its
        `known_issue_codes` to the dataset's `known_issue_count`".

        Design: Corner/validations/field_definition_limit_binds_only_in_aggregate_and_name_conflict_wins
        """
        dataset, _fortieth = self._dataset_with_forty_columns(api)
        before = X.read_dataset(api, dataset["id"])

        validate_error(
            api.create_field_definition(
                dataset["id"],
                F.field_definition_payload(
                    "field_41", reidentification_risk=1, null_rate_pct=0.0
                ),
                reporter_headers(),
            ),
            ERR_FIELD_LIMIT_EXCEEDED,
        )
        validate_error(
            api.create_field_definition(
                dataset["id"],
                F.field_definition_payload(
                    "field_01",
                    reidentification_risk=1,
                    null_rate_pct=0.0,
                    data_type="INTEGER",
                ),
                reporter_headers(),
            ),
            ERR_FIELD_NAME_CONFLICT,
        )

        after = X.read_dataset(api, dataset["id"])
        assert after["field_definition_count"] == C.MAX_FIELD_DEFINITIONS
        assert after["documentation_status"] == C.DOC_STATUS_COMPLETE
        assert after["known_issue_count"] == 0
        assert after["status"] == C.DS_CLEANING
        assert_version_is(after, before["version"], "dataset")

        rows, meta = validate_paginated_page(
            api.list_field_definitions(
                dataset["id"], reporter_headers(), {"limit": 100, "offset": 0}
            )
        )
        assert meta["total_count"] == C.MAX_FIELD_DEFINITIONS
        assert meta["has_more"] is False
        by_name = {row["field_name"]: row for row in rows}
        assert "field_41" not in by_name
        assert by_name["field_01"]["data_type"] == "STRING"


class TestDeliveryGatedOnParentRequestStatus:
    """Whether a dataset may leave RAW is decided on the parent request."""

    @staticmethod
    def _raw_dataset_on_an_awaiting_request(api):
        """A RAW dataset whose request is still AWAITING_AGENCY_RESPONSE."""
        X.set_clock(api, C.STD_CLOCK)
        desk, agency = X.desk_and_agency(
            api, desk_overrides={"retention_policy_days": 1095}
        )
        request = X.submitted_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Inspector narratives 2025",
            estimated_page_count=100,
            public_interest_score=70,
        )
        assert request["status"] == C.REQ_AWAITING_AGENCY_RESPONSE
        investigation = X.create_investigation(
            api,
            desk["id"],
            C.MODE_FULL_DATA_RELEASE,
            headline="Inspector narratives withheld",
        )
        dataset = X.register_dataset(
            api,
            request["id"],
            investigation["id"],
            name=F.unique_dataset_name("inspector-narratives"),
            negotiated_format=C.FORMAT_CSV,
            expected_field_count=1,
            sensitivity_tier="SOURCE_LINKED",
        )
        return request, dataset

    def test_delivery_is_refused_while_the_agency_has_not_decided(self, api):
        """Nothing about the dataset row is wrong; only its parent's status is.

        PRD S3.6: "Delivery is only permitted when the parent records request has
        actually produced records, meaning its status is `RELEASED` or
        `PARTIALLY_RELEASED`; anything else is refused with
        `ERR_SOURCE_REQUEST_UNRESOLVED`."

        Design: Difficulty/cross_entity_state_dependency/dataset_delivery_gated_on_parent_records_request_status
        """
        _request, dataset = self._raw_dataset_on_an_awaiting_request(api)

        validate_error(
            api.deliver_dataset(
                dataset["id"],
                F.delivery_payload(C.FORMAT_CSV, 500),
                reporter_headers(),
            ),
            ERR_SOURCE_REQUEST_UNRESOLVED,
        )

    def test_the_refused_delivery_left_the_dataset_wholly_in_raw(self, api):
        """No delivery field was written and the retention clock never started.

        PRD S3.6: "A fresh dataset opens in `RAW` with `format_negotiation_status`
        at `REQUESTED`, `documentation_status` at `INCOMPLETE`, `record_count` at
        0".

        Design: Difficulty/cross_entity_state_dependency/dataset_delivery_gated_on_parent_records_request_status
        """
        _request, dataset = self._raw_dataset_on_an_awaiting_request(api)
        validate_error(
            api.deliver_dataset(
                dataset["id"],
                F.delivery_payload(C.FORMAT_CSV, 500),
                reporter_headers(),
            ),
            ERR_SOURCE_REQUEST_UNRESOLVED,
        )

        after = X.read_dataset(api, dataset["id"])
        assert after["status"] == C.DS_RAW
        assert_field_absent_or_null(after, "delivered_format", "dataset")
        assert after["record_count"] == 0
        assert_field_absent_or_null(after, "retention_expires_at", "dataset")
        assert after["format_negotiation_status"] == C.FORMAT_NEG_REQUESTED

    def test_a_partial_release_on_the_parent_unblocks_the_same_delivery(self, api):
        """Only the parent's status changed between the refusal and the success.

        PRD S2.11: "A dataset delivery requires its parent records request to be
        `RELEASED` or `PARTIALLY_RELEASED` ... otherwise
        `ERR_SOURCE_REQUEST_UNRESOLVED`."

        Design: Difficulty/cross_entity_state_dependency/dataset_delivery_gated_on_parent_records_request_status
        """
        request, dataset = self._raw_dataset_on_an_awaiting_request(api)
        validate_error(
            api.deliver_dataset(
                dataset["id"],
                F.delivery_payload(C.FORMAT_CSV, 500),
                reporter_headers(),
            ),
            ERR_SOURCE_REQUEST_UNRESOLVED,
        )

        decided = validate_ok(
            api.record_agency_decision(
                request["id"],
                F.agency_decision_payload(C.OUTCOME_RELEASED_PARTIAL),
                coordinator_headers(),
            )
        )
        assert decided["status"] == C.REQ_PARTIALLY_RELEASED

        delivered = validate_ok(
            api.deliver_dataset(
                dataset["id"],
                F.delivery_payload(C.FORMAT_CSV, 500),
                reporter_headers(),
            )
        )
        assert delivered["status"] == C.DS_CLEANING
        assert delivered["delivered_format"] == C.FORMAT_CSV
        assert delivered["record_count"] == 500
        assert delivered["format_negotiation_status"] == C.FORMAT_NEG_AGREED

    def test_the_retention_horizon_resolves_the_desk_two_hops_out(self, api):
        """1095 calendar days come from the desk reached through the request.

        PRD S3.6: "`retention_expires_at` is the UTC calendar date of the delivery
        instant advanced by the owning desk's `retention_policy_days` in
        **calendar** days ... with the desk resolved through the dataset's records
        request."

        Design: Difficulty/cross_entity_state_dependency/dataset_delivery_gated_on_parent_records_request_status
        """
        request, dataset = self._raw_dataset_on_an_awaiting_request(api)
        validate_ok(
            api.record_agency_decision(
                request["id"],
                F.agency_decision_payload(C.OUTCOME_RELEASED_PARTIAL),
                coordinator_headers(),
            )
        )

        delivered = validate_ok(
            api.deliver_dataset(
                dataset["id"],
                F.delivery_payload(C.FORMAT_CSV, 500),
                reporter_headers(),
            )
        )
        assert_deadline_stamp(
            delivered["retention_expires_at"], "2029-08-02", "retention_expires_at"
        )


class TestQuarantineThreeHopCascade:
    """One quarantine runs upward through the run and the investigation."""

    @staticmethod
    def _locked_investigation_with_an_allocated_run(api):
        """A FINDINGS_LOCKED investigation whose only run is APPROVED and ALLOCATED."""
        X.set_clock(api, C.STD_CLOCK)
        desk, agency = X.desk_and_agency(
            api, desk_overrides={"retention_policy_days": 1095}
        )
        request = X.released_request(
            api,
            desk["id"],
            agency["id"],
            subject_summary="Emergency repair orders 2025",
            estimated_page_count=90,
            public_interest_score=70,
        )
        investigation = X.create_investigation(
            api,
            desk["id"],
            C.MODE_FULL_DATA_RELEASE,
            headline="Repair orders closed without repairs",
        )
        dataset = X.clean_locked_dataset(
            api,
            request["id"],
            investigation["id"],
            400,
            [
                {
                    "field_name": "order_id",
                    "data_type": "STRING",
                    "null_rate_pct": 0.0,
                    "reidentification_risk": 1,
                }
            ],
            name=F.unique_dataset_name("repair-orders-2025"),
            negotiated_format=C.FORMAT_CSV,
            sensitivity_tier="PUBLIC",
        )
        run = X.approved_and_allocated_run(
            api, investigation["id"], compute_cost_cents=5000, labor_hours=1.0
        )
        finding = X.doc_matched_finding(
            api,
            investigation["id"],
            run["id"],
            14,
            claim_text=(
                "One in five repair orders was closed with no inspection record."
            ),
        )
        reviewer, assignment, _completed = X.verdict_on_finding(
            api, finding["id"], C.VERDICT_CONFIRMED
        )
        locked = X.lock_findings(api, investigation["id"])
        assert locked["status"] == C.INV_FINDINGS_LOCKED
        return {
            "desk": desk,
            "investigation": investigation,
            "dataset": dataset,
            "run": run,
            "finding": finding,
            "reviewer": reviewer,
            "assignment": assignment,
        }

    def test_hop_one_quarantines_the_dataset_and_zeroes_its_allocated_cost(self, api):
        """The leaf artefact moves out of CLEAN_LOCKED and gives back its cost.

        PRD S3.6: "**Hop one:** the dataset moves `CLEAN_LOCKED -> QUARANTINED`,
        the reason code is recorded, and its `allocated_cost_cents` is reset to
        0."

        Design: Difficulty/transitive_cascade/dataset_quarantine_three_hop_analysis_invalidation
        """
        bundle = self._locked_investigation_with_an_allocated_run(api)
        assert X.read_dataset(api, bundle["dataset"]["id"])["allocated_cost_cents"] == 11500

        quarantined = validate_ok(
            api.quarantine_dataset(
                bundle["dataset"]["id"],
                F.quarantine_payload("MISMATCHED_TOTALS"),
                editor_headers(),
            )
        )
        assert quarantined["status"] == C.DS_QUARANTINED
        assert quarantined["quarantine_reason_code"] == "MISMATCHED_TOTALS"
        assert quarantined["allocated_cost_cents"] == 0

    def test_hop_two_downgrades_both_run_dimensions_without_erasing_its_own_cost(
        self, api
    ):
        """Two independent fields of the same run row move at once.

        PRD S3.6: "**Hop two:** because the dataset is quarantined, every analysis
        run belonging to the same investigation as that dataset has an `APPROVED`
        `code_review_status` downgraded to `CHANGES_REQUESTED` and an `ALLOCATED`
        `cost_allocation_status` downgraded to `NOT_ALLOCATED` with its
        `allocated_total_cents` reset to 0."

        Design: Difficulty/transitive_cascade/dataset_quarantine_three_hop_analysis_invalidation
        """
        bundle = self._locked_investigation_with_an_allocated_run(api)
        validate_ok(
            api.quarantine_dataset(
                bundle["dataset"]["id"],
                F.quarantine_payload("MISMATCHED_TOTALS"),
                editor_headers(),
            )
        )

        run = X.read_run(api, bundle["run"]["id"])
        assert run["code_review_status"] == C.REVIEW_CHANGES_REQUESTED
        assert run["cost_allocation_status"] == C.ALLOC_NOT_ALLOCATED
        assert run["allocated_total_cents"] == 0
        assert run["total_cost_cents"] == 11500
        assert run["labor_cost_cents"] == C.LABOR_RATE_CENTS_PER_HOUR

    def test_hop_three_reverts_the_investigation_out_of_findings_locked(self, api):
        """Losing the approved and allocated current run reopens the analysis.

        PRD S3.6: "**Hop three:** because the current run is no longer approved
        and allocated, the investigation's `analysis_readiness` recomputes to
        `NOT_READY`, and an investigation sitting in `FINDINGS_LOCKED` reverts to
        `ANALYSIS`."

        Design: Difficulty/transitive_cascade/dataset_quarantine_three_hop_analysis_invalidation
        """
        bundle = self._locked_investigation_with_an_allocated_run(api)
        validate_ok(
            api.quarantine_dataset(
                bundle["dataset"]["id"],
                F.quarantine_payload("MISMATCHED_TOTALS"),
                editor_headers(),
            )
        )

        investigation = X.read_investigation(api, bundle["investigation"]["id"])
        assert investigation["analysis_readiness"] == C.READINESS_NOT_READY
        assert investigation["status"] == C.INV_ANALYSIS

    def test_the_cascade_leaves_the_verification_partition_and_the_desk_alone(
        self, api
    ):
        """The confirmed finding, its assignment, its reviewer and the desk are untouched.

        PRD S3.7: "`finding_count` equals the sum of `unverified_finding_count`,
        `doc_matched_finding_count`, `sme_confirmed_finding_count` and
        `sme_disputed_finding_count`".

        Design: Difficulty/transitive_cascade/dataset_quarantine_three_hop_analysis_invalidation
        """
        bundle = self._locked_investigation_with_an_allocated_run(api)
        validate_ok(
            api.quarantine_dataset(
                bundle["dataset"]["id"],
                F.quarantine_payload("MISMATCHED_TOTALS"),
                editor_headers(),
            )
        )

        finding = X.read_finding(api, bundle["finding"]["id"])
        assert finding["verification_status"] == C.FIND_SME_CONFIRMED
        assert finding["matched_page"] == 14

        investigation = X.read_investigation(api, bundle["investigation"]["id"])
        assert_partition_counts(investigation, 1, 0, 0, 1, 0)

        assignment = validate_ok(
            api.get_review_assignment(bundle["assignment"]["id"], editor_headers())
        )
        assert assignment["status"] == C.ASSIGN_COMPLETED
        reviewer = validate_ok(
            api.get_expert_reviewer(bundle["reviewer"]["id"], editor_headers())
        )
        assert reviewer["active_assignment_count"] == 0

        desk = X.read_desk(api, bundle["desk"]["id"])
        assert desk["security_posture"] == C.POSTURE_OPEN
        assert desk["litigation_exposure_count"] == 0
