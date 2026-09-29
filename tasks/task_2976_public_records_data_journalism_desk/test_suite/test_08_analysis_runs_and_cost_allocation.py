"""Analysis runs: the two independent dimensions and the cost allocation.

Every test builds its own preconditions through the endpoints of PRD S4, because
the harness restarts the server and wipes the database before each test.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_NO_ALLOCABLE_INPUTS
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_version_is,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated_page,
)
from test_helpers.test_users import (
    REPORTER_ID,
    PEER_REVIEWER_ID,
    editor_headers,
    peer_reviewer_headers,
    reporter_headers,
)

_PERMIT_FIELD_SPECS = [
    {
        "field_name": "permit_id",
        "data_type": "STRING",
        "null_rate_pct": 0.0,
        "reidentification_risk": 1,
    }
]


def _released_request_and_investigation(
    api,
    retention_policy_days=1095,
    publication_mode=C.MODE_FULL_DATA_RELEASE,
    subject_summary="Building permit approvals 2025",
    headline="Permit fast-tracking at the housing authority",
    agency_overrides=None,
):
    """A RELEASED records request plus an investigation on the same desk."""
    desk, agency = X.desk_and_agency(
        api,
        desk_overrides={"retention_policy_days": retention_policy_days},
        agency_overrides=agency_overrides,
    )
    request = X.released_request(
        api, desk["id"], agency["id"], subject_summary=subject_summary
    )
    investigation = X.create_investigation(
        api, desk["id"], publication_mode, headline=headline
    )
    return desk, request, investigation


class TestAllocationRoundsSharesThenReconciles:
    """The worked three-dataset case of a negative residual on the earliest row."""

    @staticmethod
    def _three_locked_datasets_and_a_run(api):
        """alpha/beta/gamma at 333/333/334 records and a 12000-cent, 3.5-hour run."""
        X.set_clock(api, C.STD_CLOCK)
        _desk, request, investigation = _released_request_and_investigation(api)
        datasets = {}
        for prefix, record_count in (
            ("alpha-permits", 333),
            ("beta-permits", 333),
            ("gamma-permits", 334),
        ):
            datasets[prefix] = X.clean_locked_dataset(
                api,
                request["id"],
                investigation["id"],
                record_count,
                _PERMIT_FIELD_SPECS,
                name=F.unique_dataset_name(prefix),
                negotiated_format=C.FORMAT_CSV,
                sensitivity_tier="PUBLIC",
            )
        run = X.create_run(
            api, investigation["id"], compute_cost_cents=12000, labor_hours=3.5
        )
        return investigation, datasets, run

    def test_the_labour_cost_and_total_cost_are_computed_before_apportioning(
        self, api
    ):
        """3.5 hours at 6500 cents an hour is 22750, so the total cost is 34750.

        PRD S3.7: "First, `labor_cost_cents` is the run's `labor_hours` multiplied
        by a labour rate of 6500 cents per hour -- sixty-five dollars an hour --
        rounded half up, and `total_cost_cents` is `compute_cost_cents` plus
        `labor_cost_cents`."

        Design: Difficulty/combinatorial_formula/cost_allocation_round_each_share_then_residual_to_earliest
        """
        _investigation, _datasets, run = self._three_locked_datasets_and_a_run(api)

        allocated = validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        assert allocated["labor_cost_cents"] == 22750
        assert allocated["total_cost_cents"] == 34750
        assert allocated["allocated_total_cents"] == 34750
        assert allocated["cost_allocation_status"] == C.ALLOC_ALLOCATED
        assert allocated["code_review_status"] == C.REVIEW_PENDING

    def test_the_negative_residual_lands_entirely_on_the_earliest_dataset(self, api):
        """Rounded shares of 11572/11572/11607 overshoot by one cent, taken off alpha.

        PRD S3.7: "over three allocable datasets in creation order with record
        counts 333, 333 and 334 and a `total_records` of 1000, the rounded shares
        are 11572, 11572 and 11607, summing to 34751, so the residual of negative
        one lands on the earliest dataset, giving final values of 11571, 11572 and
        11607".

        Design: Difficulty/combinatorial_formula/cost_allocation_round_each_share_then_residual_to_earliest
        """
        _investigation, datasets, run = self._three_locked_datasets_and_a_run(api)

        validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        alpha = X.read_dataset(api, datasets["alpha-permits"]["id"])
        beta = X.read_dataset(api, datasets["beta-permits"]["id"])
        gamma = X.read_dataset(api, datasets["gamma-permits"]["id"])
        assert alpha["allocated_cost_cents"] == 11571
        assert beta["allocated_cost_cents"] == 11572
        assert gamma["allocated_cost_cents"] == 11607

    def test_the_allocated_shares_sum_to_the_total_cost_with_nothing_lost(self, api):
        """No cent is created or destroyed by the reconciliation.

        PRD S3.7: "that sum to exactly 34750."

        Design: Difficulty/combinatorial_formula/cost_allocation_round_each_share_then_residual_to_earliest
        """
        _investigation, datasets, run = self._three_locked_datasets_and_a_run(api)

        allocated = validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        shares = [
            X.read_dataset(api, dataset["id"])["allocated_cost_cents"]
            for dataset in datasets.values()
        ]
        assert sum(shares) == 34750
        assert sum(shares) == allocated["allocated_total_cents"]


class TestRunReviewAndAllocationDimensions:
    """Two independent status dimensions live on the same analysis-run row."""

    _BACKLOG_FIELD_SPECS = [
        {
            "field_name": "inspection_id",
            "data_type": "STRING",
            "null_rate_pct": 0.0,
            "reidentification_risk": 1,
        }
    ]

    @classmethod
    def _one_locked_dataset_and_a_run(cls, api):
        """A 500-record CLEAN_LOCKED dataset and a 5000-cent, 1.0-hour run."""
        X.set_clock(api, C.STD_CLOCK)
        _desk, request, investigation = _released_request_and_investigation(
            api,
            subject_summary="Inspection backlog 2025",
            headline="Inspection backlog doubled",
        )
        dataset = X.clean_locked_dataset(
            api,
            request["id"],
            investigation["id"],
            500,
            cls._BACKLOG_FIELD_SPECS,
            name=F.unique_dataset_name("backlog-2025"),
            negotiated_format=C.FORMAT_CSV,
            sensitivity_tier="PUBLIC",
        )
        run = X.create_run(
            api, investigation["id"], compute_cost_cents=5000, labor_hours=1.0
        )
        return investigation, dataset, run

    def test_a_changes_requested_review_moves_only_the_review_dimension(self, api):
        """The first review round leaves the allocation dimension where it was.

        PRD S3.7: "Either decision increments `review_cycle_count` by 1 and
        records `peer_review_note` and `reviewed_by_user_id` from `X-User-ID`;
        both decisions leave `cost_allocation_status` completely untouched".

        Design: Difficulty/non_linear_state_machine/analysis_run_parallel_review_and_allocation_dimensions
        """
        _investigation, _dataset, run = self._one_locked_dataset_and_a_run(api)

        reviewed = validate_ok(
            api.submit_peer_review(
                run["id"],
                F.peer_review_payload(
                    C.REVIEW_CHANGES_REQUESTED,
                    peer_review_note=(
                        "Weighting of vacancy adjustment is undocumented."
                    ),
                ),
                peer_reviewer_headers(),
            )
        )

        assert reviewed["code_review_status"] == C.REVIEW_CHANGES_REQUESTED
        assert reviewed["review_cycle_count"] == 1
        assert reviewed["cost_allocation_status"] == C.ALLOC_NOT_ALLOCATED
        assert reviewed["allocated_total_cents"] == 0

    def test_a_second_review_approves_and_still_allocates_nothing(self, api):
        """The review dimension cycles twice while the allocation stays put.

        PRD S3.7: "so review rounds may cycle `PENDING_REVIEW ->
        CHANGES_REQUESTED -> APPROVED`."

        Design: Difficulty/non_linear_state_machine/analysis_run_parallel_review_and_allocation_dimensions
        """
        investigation, dataset, run = self._one_locked_dataset_and_a_run(api)
        validate_ok(
            api.submit_peer_review(
                run["id"],
                F.peer_review_payload(C.REVIEW_CHANGES_REQUESTED),
                peer_reviewer_headers(),
            )
        )

        approved = validate_ok(
            api.submit_peer_review(
                run["id"],
                F.peer_review_payload(
                    C.REVIEW_APPROVED,
                    peer_review_note=(
                        "Weighting now documented; methodology reproducible."
                    ),
                ),
                peer_reviewer_headers(),
            )
        )

        assert approved["code_review_status"] == C.REVIEW_APPROVED
        assert approved["review_cycle_count"] == 2
        assert approved["reviewed_by_user_id"] == PEER_REVIEWER_ID
        assert approved["cost_allocation_status"] == C.ALLOC_NOT_ALLOCATED
        assert approved["allocated_total_cents"] == 0
        assert X.read_dataset(api, dataset["id"])["allocated_cost_cents"] == 0
        assert (
            X.read_investigation(api, investigation["id"])["analysis_readiness"]
            == C.READINESS_NOT_READY
        )

    def test_the_allocation_dimension_moves_on_its_own_calculation(self, api):
        """Allocation is the only hop that writes the cost fields.

        PRD S3.7: "the run's `allocated_total_cents` is set to
        `total_cost_cents`, and `cost_allocation_status` moves `NOT_ALLOCATED ->
        ALLOCATED`."

        Design: Difficulty/non_linear_state_machine/analysis_run_parallel_review_and_allocation_dimensions
        """
        _investigation, dataset, run = self._one_locked_dataset_and_a_run(api)
        validate_ok(
            api.submit_peer_review(
                run["id"],
                F.peer_review_payload(C.REVIEW_CHANGES_REQUESTED),
                peer_reviewer_headers(),
            )
        )
        validate_ok(
            api.submit_peer_review(
                run["id"], F.peer_review_payload(C.REVIEW_APPROVED), peer_reviewer_headers()
            )
        )

        allocated = validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        assert allocated["cost_allocation_status"] == C.ALLOC_ALLOCATED
        assert allocated["labor_cost_cents"] == 6500
        assert allocated["total_cost_cents"] == 11500
        assert allocated["allocated_total_cents"] == 11500
        assert X.read_dataset(api, dataset["id"])["allocated_cost_cents"] == 11500

    def test_the_allocation_leaves_the_review_dimension_exactly_as_it_found_it(
        self, api
    ):
        """The combined APPROVED and ALLOCATED state needs both hops, and neither undoes the other.

        PRD S3.7: "The `code_review_status` dimension is untouched,
        `analysis_readiness` is recomputed".

        Design: Difficulty/non_linear_state_machine/analysis_run_parallel_review_and_allocation_dimensions
        """
        _investigation, _dataset, run = self._one_locked_dataset_and_a_run(api)
        validate_ok(
            api.submit_peer_review(
                run["id"],
                F.peer_review_payload(C.REVIEW_CHANGES_REQUESTED),
                peer_reviewer_headers(),
            )
        )
        validate_ok(
            api.submit_peer_review(
                run["id"], F.peer_review_payload(C.REVIEW_APPROVED), peer_reviewer_headers()
            )
        )
        validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        final = X.read_run(api, run["id"])
        assert final["code_review_status"] == C.REVIEW_APPROVED
        assert final["review_cycle_count"] == 2
        assert final["cost_allocation_status"] == C.ALLOC_ALLOCATED


class TestAllocationDegenerateBoundaries:
    """Two adjacent degenerate boundaries: zero records, then no allocable set."""

    _ORDER_FIELD_SPECS = [
        {
            "field_name": "order_id",
            "data_type": "STRING",
            "null_rate_pct": 0.0,
            "reidentification_risk": 0,
        }
    ]

    @classmethod
    def _two_empty_locked_datasets_and_a_run(cls, api):
        """alpha-orders and beta-orders, both CLEAN_LOCKED with a record_count of 0."""
        X.set_clock(api, C.STD_CLOCK)
        _desk, request, investigation = _released_request_and_investigation(
            api,
            subject_summary="Empty repair order extracts",
            headline="The records that were not there",
        )
        datasets = {}
        for prefix in ("alpha-orders", "beta-orders"):
            datasets[prefix] = X.clean_locked_dataset(
                api,
                request["id"],
                investigation["id"],
                0,
                cls._ORDER_FIELD_SPECS,
                name=F.unique_dataset_name(prefix),
                negotiated_format=C.FORMAT_CSV,
                sensitivity_tier="PUBLIC",
            )
        run = X.create_run(
            api, investigation["id"], compute_cost_cents=5000, labor_hours=1.0
        )
        return investigation, datasets, run

    def test_a_zero_total_record_count_sends_the_whole_cost_to_the_earliest_dataset(
        self, api
    ):
        """No division by zero: every share is zero and the residual is the whole total.

        PRD S3.7: "over two allocable datasets both with a `record_count` of 0,
        every share is zero and the whole residual of 11500 goes to the earliest
        dataset, leaving the second at 0."

        Design: Difficulty/boundary_precision_check/cost_allocation_zero_record_share_and_empty_allocable_set
        """
        _investigation, datasets, run = self._two_empty_locked_datasets_and_a_run(api)

        allocated = validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        assert allocated["total_cost_cents"] == 11500
        assert allocated["allocated_total_cents"] == 11500
        assert allocated["cost_allocation_status"] == C.ALLOC_ALLOCATED
        alpha = X.read_dataset(api, datasets["alpha-orders"]["id"])
        beta = X.read_dataset(api, datasets["beta-orders"]["id"])
        assert alpha["allocated_cost_cents"] == 11500
        assert beta["allocated_cost_cents"] == 0

    def test_quarantining_the_funded_dataset_rolls_the_allocation_back(self, api):
        """The cascade takes back both the dataset's share and the run's total.

        PRD S3.6: "**Hop two:** because the dataset is quarantined, every analysis
        run belonging to the same investigation as that dataset has ... an
        `ALLOCATED` `cost_allocation_status` downgraded to `NOT_ALLOCATED` with its
        `allocated_total_cents` reset to 0."

        Design: Difficulty/boundary_precision_check/cost_allocation_zero_record_share_and_empty_allocable_set
        """
        _investigation, datasets, run = self._two_empty_locked_datasets_and_a_run(api)
        validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        quarantined = validate_ok(
            api.quarantine_dataset(
                datasets["alpha-orders"]["id"],
                F.quarantine_payload("UNRESOLVED_NULLS"),
                editor_headers(),
            )
        )
        assert quarantined["status"] == C.DS_QUARANTINED
        assert quarantined["allocated_cost_cents"] == 0

        after = X.read_run(api, run["id"])
        assert after["cost_allocation_status"] == C.ALLOC_NOT_ALLOCATED
        assert after["allocated_total_cents"] == 0

    def test_an_empty_allocable_set_refuses_the_allocation(self, api):
        """With both datasets quarantined there is nothing left to apportion onto.

        PRD S3.7: "it requires at least one `CLEAN_LOCKED` dataset on that
        investigation, otherwise `ERR_NO_ALLOCABLE_INPUTS` with nothing written."

        Design: Difficulty/boundary_precision_check/cost_allocation_zero_record_share_and_empty_allocable_set
        """
        _investigation, datasets, run = self._two_empty_locked_datasets_and_a_run(api)
        validate_ok(api.allocate_cost(run["id"], reporter_headers()))
        for prefix in ("alpha-orders", "beta-orders"):
            quarantined = validate_ok(
                api.quarantine_dataset(
                    datasets[prefix]["id"],
                    F.quarantine_payload("UNRESOLVED_NULLS"),
                    editor_headers(),
                )
            )
            assert quarantined["status"] == C.DS_QUARANTINED
            assert quarantined["allocated_cost_cents"] == 0

        validate_error(
            api.allocate_cost(run["id"], reporter_headers()), ERR_NO_ALLOCABLE_INPUTS
        )

    def test_the_refused_allocation_wrote_nothing_anywhere(self, api):
        """Neither dataset, nor the run, nor the investigation was touched.

        PRD S3.7: "otherwise `ERR_NO_ALLOCABLE_INPUTS` with nothing written."

        Design: Difficulty/boundary_precision_check/cost_allocation_zero_record_share_and_empty_allocable_set
        """
        investigation, datasets, run = self._two_empty_locked_datasets_and_a_run(api)
        validate_ok(api.allocate_cost(run["id"], reporter_headers()))
        for prefix in ("alpha-orders", "beta-orders"):
            validate_ok(
                api.quarantine_dataset(
                    datasets[prefix]["id"],
                    F.quarantine_payload("UNRESOLVED_NULLS"),
                    editor_headers(),
                )
            )
        run_before = X.read_run(api, run["id"])

        validate_error(
            api.allocate_cost(run["id"], reporter_headers()), ERR_NO_ALLOCABLE_INPUTS
        )

        for prefix in ("alpha-orders", "beta-orders"):
            assert X.read_dataset(api, datasets[prefix]["id"])["allocated_cost_cents"] == 0
        run_after = X.read_run(api, run["id"])
        assert run_after["cost_allocation_status"] == C.ALLOC_NOT_ALLOCATED
        assert run_after["allocated_total_cents"] == 0
        assert_version_is(run_after, run_before["version"], "analysis run")

        final = X.read_investigation(api, investigation["id"])
        assert final["analysis_readiness"] == C.READINESS_NOT_READY
        assert final["status"] == C.INV_ANALYSIS


class TestAllocationInputSetFiltering:
    """Only CLEAN_LOCKED datasets of the run's investigation are allocable."""

    _CASE_FIELD_SPECS = [
        {
            "field_name": "case_number",
            "data_type": "STRING",
            "null_rate_pct": 0.0,
            "reidentification_risk": 1,
        }
    ]

    @classmethod
    def _one_locked_and_one_cleaning_dataset(cls, api):
        """A 200-record CLEAN_LOCKED dataset beside an 800-record CLEANING one."""
        X.set_clock(api, C.STD_CLOCK)
        _desk, request, investigation = _released_request_and_investigation(
            api,
            retention_policy_days=365,
            publication_mode=C.MODE_METHODOLOGY_ONLY,
            subject_summary="Filtering probe",
            headline="Filtering probe",
        )
        locked = X.clean_locked_dataset(
            api,
            request["id"],
            investigation["id"],
            200,
            cls._CASE_FIELD_SPECS,
            name=F.unique_dataset_name("ds-locked"),
            negotiated_format=C.FORMAT_CSV,
            sensitivity_tier="PUBLIC",
        )
        cleaning = X.delivered_dataset(
            api,
            request["id"],
            investigation["id"],
            800,
            C.FORMAT_CSV,
            name=F.unique_dataset_name("ds-cleaning"),
            negotiated_format=C.FORMAT_CSV,
            expected_field_count=1,
            sensitivity_tier="PUBLIC",
        )
        run = X.create_run(
            api, investigation["id"], compute_cost_cents=5000, labor_hours=1.0
        )
        return locked, cleaning, run

    def test_the_run_allocates_its_whole_cost_and_leaves_the_review_dimension_alone(
        self, api
    ):
        """1.0 hour of labour on 5000 cents of compute allocates 11500 in total.

        PRD S3.7: "the run's `allocated_total_cents` is set to `total_cost_cents`
        ... The `code_review_status` dimension is untouched".

        Design: Corner/calculations/cost_allocation_includes_only_clean_locked_datasets
        """
        _locked, _cleaning, run = self._one_locked_and_one_cleaning_dataset(api)

        allocated = validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        assert allocated["labor_cost_cents"] == C.LABOR_RATE_CENTS_PER_HOUR
        assert allocated["total_cost_cents"] == 11500
        assert allocated["allocated_total_cents"] == 11500
        assert allocated["cost_allocation_status"] == C.ALLOC_ALLOCATED
        assert allocated["code_review_status"] == C.REVIEW_PENDING

    def test_the_sole_allocable_dataset_absorbs_the_entire_cost(self, api):
        """The 800 CLEANING records never enter total_records, so 200 records take it all.

        PRD S3.7: "the allocable set is every dataset whose `investigation_id` is
        the run's investigation and whose status is `CLEAN_LOCKED`, ordered by
        `created_at` ascending and then by `name` ascending".

        Design: Corner/calculations/cost_allocation_includes_only_clean_locked_datasets
        """
        locked, _cleaning, run = self._one_locked_and_one_cleaning_dataset(api)

        validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        share = X.read_dataset(api, locked["id"])["allocated_cost_cents"]
        assert share == 11500
        assert share != 2300

    def test_a_cleaning_dataset_is_skipped_entirely_rather_than_zeroed(self, api):
        """A dataset outside the allocable set is never written at all.

        PRD S3.7: "Datasets outside the allocable set keep their existing
        `allocated_cost_cents` unchanged."

        Design: Corner/calculations/cost_allocation_includes_only_clean_locked_datasets
        """
        _locked, cleaning, run = self._one_locked_and_one_cleaning_dataset(api)
        before = X.read_dataset(api, cleaning["id"])

        validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        after = X.read_dataset(api, cleaning["id"])
        assert after["status"] == C.DS_CLEANING
        assert after["allocated_cost_cents"] == 0
        assert_version_is(after, before["version"], "dataset")


class TestResidualFollowsCreationOrder:
    """created_at ascending decides the earliest dataset, not the name."""

    @staticmethod
    def _earlier_zulu_and_later_alpha(api):
        """zulu-permits created an hour before alpha-permits, 333 against 667 records."""
        X.set_clock(api, C.STD_CLOCK)
        _desk, request, investigation = _released_request_and_investigation(
            api,
            publication_mode=C.MODE_METHODOLOGY_ONLY,
            subject_summary="Permit approvals 2025",
            headline="Permit fast-tracking",
            agency_overrides={
                "name": "City Building Department",
                "jurisdiction_code": "CA-CITY",
                "tolling_allowed": False,
                "appeal_venue": C.VENUE_INTERNAL,
                "appeal_decision_days": 15,
            },
        )
        zulu = X.clean_locked_dataset(
            api,
            request["id"],
            investigation["id"],
            333,
            _PERMIT_FIELD_SPECS,
            name=F.unique_dataset_name("zulu-permits"),
            negotiated_format=C.FORMAT_CSV,
            sensitivity_tier="PUBLIC",
        )
        X.set_clock(api, "2026-08-03T10:00:00Z")
        alpha = X.clean_locked_dataset(
            api,
            request["id"],
            investigation["id"],
            667,
            _PERMIT_FIELD_SPECS,
            name=F.unique_dataset_name("alpha-permits"),
            negotiated_format=C.FORMAT_CSV,
            sensitivity_tier="PUBLIC",
        )
        run = X.create_run(
            api, investigation["id"], compute_cost_cents=5000, labor_hours=1.0
        )
        return zulu, alpha, run

    def test_the_two_creation_instants_order_the_allocable_set_unambiguously(self, api):
        """zulu was registered a full hour before alpha, so the ordering key is decided.

        PRD S3.7: "the allocable set is every dataset whose `investigation_id` is
        the run's investigation and whose status is `CLEAN_LOCKED`, ordered by
        `created_at` ascending and then by `name` ascending".

        Design: Corner/calculations/allocation_residual_follows_creation_order_not_name_order
        """
        zulu, alpha, _run = self._earlier_zulu_and_later_alpha(api)

        assert_instant_equals(zulu["created_at"], C.STD_CLOCK, "zulu.created_at")
        assert_instant_equals(
            alpha["created_at"], "2026-08-03T10:00:00Z", "alpha.created_at"
        )
        assert alpha["name"] < zulu["name"]

    def test_the_residual_lands_on_the_earlier_dataset_not_the_earlier_name(self, api):
        """A name-first ordering would give zulu 3830 and alpha 7670 instead.

        PRD S3.7: "the residual is the total cost minus the sum of the rounded
        shares, and that residual, which may be negative, is added in its entirety
        to the share of the **earliest** dataset in the ordering."

        Design: Corner/calculations/allocation_residual_follows_creation_order_not_name_order
        """
        zulu, alpha, run = self._earlier_zulu_and_later_alpha(api)

        allocated = validate_ok(api.allocate_cost(run["id"], reporter_headers()))
        assert allocated["total_cost_cents"] == 11500
        assert allocated["allocated_total_cents"] == 11500

        assert X.read_dataset(api, zulu["id"])["allocated_cost_cents"] == 3829
        assert X.read_dataset(api, alpha["id"])["allocated_cost_cents"] == 7671

    def test_the_reconciled_shares_still_sum_to_the_total_cost(self, api):
        """3829 plus 7671 is 11500 with no cent created or destroyed.

        PRD S2.10: "the result is rounded **half up**: add one half to the exact
        decimal product and truncate toward zero".

        Design: Corner/calculations/allocation_residual_follows_creation_order_not_name_order
        """
        zulu, alpha, run = self._earlier_zulu_and_later_alpha(api)

        validate_ok(api.allocate_cost(run["id"], reporter_headers()))

        total = (
            X.read_dataset(api, zulu["id"])["allocated_cost_cents"]
            + X.read_dataset(api, alpha["id"])["allocated_cost_cents"]
        )
        assert total == 11500


class TestRunComputedFieldsAndSequence:
    """run_sequence and every opening status are derived by the server."""

    @staticmethod
    def _investigation_in_drafting(api):
        """A bare investigation with no run yet, still in DRAFTING."""
        X.set_clock(api, C.STD_CLOCK)
        desk = X.create_desk(
            api, name="Metro Investigations Desk", retention_policy_days=1095
        )
        investigation = X.create_investigation(
            api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Computed field probe"
        )
        assert investigation["status"] == C.INV_DRAFTING
        return investigation

    @staticmethod
    def _record_run(api, investigation_id, compute_cost_cents, labor_hours, commit_sha):
        """Record one run, reading a fresh investigation version first."""
        payload = F.analysis_run_payload(
            investigation_id,
            X.investigation_version(api, investigation_id),
            compute_cost_cents,
            labor_hours,
            code_repo_ref="github.com/metro-desk/closures",
            code_commit_sha=commit_sha,
        )
        return validate_created(api.create_analysis_run(payload, reporter_headers()))

    def test_the_first_run_opens_with_sequence_one_and_the_declared_defaults(
        self, api
    ):
        """Nothing in the payload sets the sequence or either status dimension.

        PRD S3.7: "Each run receives a `run_sequence` equal to 1 plus the count of
        runs that already exist for the same investigation ... A run opens with
        `code_review_status` at `PENDING_REVIEW`, `cost_allocation_status` at
        `NOT_ALLOCATED`, `review_cycle_count` at 0, `allocated_total_cents` at 0,
        `authored_by_user_id` set from `X-User-ID`, `peer_review_note` and
        `reviewed_by_user_id` null."

        Design: Corner/entities/analysis_run_computed_fields_and_run_sequence_are_server_derived
        """
        investigation = self._investigation_in_drafting(api)

        run = self._record_run(api, investigation["id"], 5000, 2.5, F.COMMIT_SHA)

        assert run["run_sequence"] == 1
        assert run["code_review_status"] == C.REVIEW_PENDING
        assert run["cost_allocation_status"] == C.ALLOC_NOT_ALLOCATED
        assert run["review_cycle_count"] == 0
        assert run["allocated_total_cents"] == 0
        assert run["authored_by_user_id"] == REPORTER_ID
        assert_field_absent_or_null(run, "peer_review_note", "analysis run")
        assert_field_absent_or_null(run, "reviewed_by_user_id", "analysis run")
        assert_version_is(run, 1, "analysis run")

    def test_the_first_run_drives_the_investigation_out_of_drafting(self, api):
        """Opening the analysis is a side effect of the first run, not its own call.

        PRD S3.7: "The first run on an investigation drives `DRAFTING ->
        ANALYSIS` ... and a fresh run always drops it to `NOT_READY`, because the
        new current run is neither approved nor allocated".

        Design: Corner/entities/analysis_run_computed_fields_and_run_sequence_are_server_derived
        """
        investigation = self._investigation_in_drafting(api)

        self._record_run(api, investigation["id"], 5000, 2.5, F.COMMIT_SHA)

        after = X.read_investigation(api, investigation["id"])
        assert after["status"] == C.INV_ANALYSIS
        assert after["analysis_readiness"] == C.READINESS_NOT_READY

    def test_a_superseding_run_takes_sequence_two_without_re_entering_drafting(
        self, api
    ):
        """The second run counts the first and leaves the investigation in ANALYSIS.

        PRD S3.7: "a later run leaves the investigation in `ANALYSIS` but becomes
        the current run and legitimately supersedes its predecessor."

        Design: Corner/entities/analysis_run_computed_fields_and_run_sequence_are_server_derived
        """
        investigation = self._investigation_in_drafting(api)
        first = self._record_run(api, investigation["id"], 5000, 2.5, F.COMMIT_SHA)

        second = self._record_run(api, investigation["id"], 0, 0.0, F.COMMIT_SHA_ALT)

        assert second["run_sequence"] == 2
        assert second["id"] != first["id"]
        assert (
            X.read_investigation(api, investigation["id"])["status"] == C.INV_ANALYSIS
        )

        rows, meta = validate_paginated_page(
            api.list_analysis_runs(
                reporter_headers(), {"investigation_id": investigation["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["run_sequence"] for row in rows} == {1, 2}
