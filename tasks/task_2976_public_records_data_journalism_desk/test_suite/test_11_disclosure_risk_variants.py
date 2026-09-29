"""The two disclosure-risk variants and the publish ceiling of PRD S3.9.

Every test here exercises the arithmetic that decides whether an investigation
may be released: the ``AGGREGATE_MAX`` worst-single-field score, the
``COMPOSITE_WEIGHTED`` average-density score with its pinned
round-then-penalize-then-clamp order, the inclusive ceiling of 60, and the
``NONE`` variant a ``METHODOLOGY_ONLY`` investigation selects.

The read-only rehearsal endpoint is used wherever a score has to be observed
without publishing, because PRD S3.9 says of it: "It persists nothing and
advances no state machine."
"""

import pytest

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_DISCLOSURE_RISK_TOO_HIGH,
    ERR_RELEASE_DATASET_REQUIRED,
    ERR_SOURCE_EXPOSURE_RISK,
)
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_instant_equals,
    validate_error,
    validate_ok,
    validate_unpaginated,
)
from test_helpers.test_users import editor_headers, reporter_headers

# --------------------------------------------------------------------------
# Private helpers and literals (this file only)
# --------------------------------------------------------------------------

_DROP_COLUMN = "DROP_COLUMN"
_HASH_REDACT = "HASH_REDACT"


def _preview(api, investigation_id, release_dataset_id=None):
    """Run the read-only disclosure-risk rehearsal of PRD S3.9."""
    params = None
    if release_dataset_id is not None:
        params = {"release_dataset_id": release_dataset_id}
    return validate_ok(
        api.preview_disclosure_risk(
            investigation_id, editor_headers(), params=params
        )
    )


def _field_id(fields, field_name):
    """The id of one documented column out of a ``document_fields`` result."""
    for row in fields:
        if row["field_name"] == field_name:
            return row["id"]
    raise AssertionError(
        f"field {field_name!r} was not documented; got "
        f"{[row['field_name'] for row in fields]}"
    )


def _fields_by_name(api, dataset_id):
    """The documented columns of an already-built dataset, keyed by ``field_name``."""
    rows = validate_unpaginated(
        api.list_field_definitions(dataset_id, reporter_headers())
    )
    return {row["field_name"]: row for row in rows}


def _probe_dataset(api, request_id, investigation_id, record_count, specs, prefix):
    """A delivered dataset with its columns documented; returns (dataset, fields)."""
    dataset = X.delivered_dataset(
        api,
        request_id,
        investigation_id,
        record_count=record_count,
        name=F.unique_dataset_name(prefix),
        expected_field_count=len(specs),
    )
    fields = X.document_fields(api, dataset["id"], specs)
    return X.read_dataset(api, dataset["id"]), fields


def _divergence_setup(api):
    """An ``AGGREGATES_ONLY`` investigation whose release dataset holds risks 8 and 3."""
    X.set_clock(api, C.STD_CLOCK)
    desk, agency = X.desk_and_agency(api)
    request = X.released_request(api, desk["id"], agency["id"])
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_AGGREGATES_ONLY
    )
    dataset, _fields = _probe_dataset(
        api,
        request["id"],
        investigation["id"],
        500,
        [
            {
                "field_name": "tenant_zip",
                "reidentification_risk": 8,
                "null_rate_pct": 1.5,
            },
            {
                "field_name": "violation_class",
                "reidentification_risk": 3,
                "null_rate_pct": 0.0,
            },
        ],
        "housing-inspections",
    )
    return investigation, dataset


class TestDisclosureRiskDualVariant:
    """Both variants on one dataset, 25 points apart across the ceiling."""

    def test_both_variants_are_reported_and_diverge_by_twenty_five_points(self, api):
        """The rehearsal reports both scores for record_count 500 at risks 8 and 3.

        PRD S3.9: "The sharpest case is opposite-gate divergence:
        `record_count` 500 with two unsuppressed fields at risks 8 and 3 and no
        source-identifying column. `AGGREGATE_MAX` is 8 × 10 = 80, while
        `COMPOSITE_WEIGHTED` is base 11 over count 2 for density 5.5, times 10
        is 55, times 1.0 is 55."

        Design: Difficulty/dual_variant_calc/disclosure_risk_aggregate_max_versus_composite_weighted
        """
        investigation, dataset = _divergence_setup(api)

        preview = _preview(api, investigation["id"], dataset["id"])

        assert preview["aggregate_max_score"] == 80, (
            f"aggregate_max_score: expected 80, got {preview['aggregate_max_score']}"
        )
        assert preview["composite_weighted_score"] == 55, (
            "composite_weighted_score: expected 55, got "
            f"{preview['composite_weighted_score']}"
        )
        assert (
            preview["aggregate_max_score"] - preview["composite_weighted_score"] == 25
        ), "the two variants must land exactly 25 points apart on this field data"

    def test_aggregates_only_selects_the_aggregate_max_variant(self, api):
        """The publication mode, not the data, decides which score is authoritative.

        PRD S3.9: "`FULL_DATA_RELEASE` stamps `applicable_risk_variant`
        `COMPOSITE_WEIGHTED` and takes the composite score; `AGGREGATES_ONLY`
        stamps `AGGREGATE_MAX` and takes the aggregate score".

        Design: Difficulty/dual_variant_calc/disclosure_risk_aggregate_max_versus_composite_weighted
        """
        investigation, dataset = _divergence_setup(api)

        preview = _preview(api, investigation["id"], dataset["id"])

        assert preview["applicable_variant"] == C.VARIANT_AGGREGATE_MAX, (
            "applicable_variant: expected AGGREGATE_MAX under AGGREGATES_ONLY, got "
            f"{preview['applicable_variant']!r}"
        )
        assert preview["applicable_score"] == 80, (
            f"applicable_score: expected 80, got {preview['applicable_score']}"
        )

    def test_the_blocking_reason_names_the_disclosure_risk_gate(self, api):
        """80 is over the ceiling, so the rehearsal names that gate as the blocker.

        PRD S3.9: "a `blocking_reason_code` naming the first publication gate
        that would fail right now, or `NONE` when publication would succeed."

        Design: Difficulty/dual_variant_calc/disclosure_risk_aggregate_max_versus_composite_weighted
        """
        investigation, dataset = _divergence_setup(api)

        preview = _preview(api, investigation["id"], dataset["id"])

        assert preview["blocking_reason_code"] == ERR_DISCLOSURE_RISK_TOO_HIGH, (
            "blocking_reason_code: expected ERR_DISCLOSURE_RISK_TOO_HIGH because the "
            f"applicable score 80 exceeds {C.PUBLISH_RISK_CEILING}, got "
            f"{preview['blocking_reason_code']!r}"
        )

    def test_the_rehearsal_persists_nothing_on_either_row(self, api):
        """After the rehearsal the investigation carries no score at all.

        PRD S3.9: "It persists nothing and advances no state machine."

        Design: Difficulty/dual_variant_calc/disclosure_risk_aggregate_max_versus_composite_weighted
        """
        investigation, dataset = _divergence_setup(api)

        _preview(api, investigation["id"], dataset["id"])

        after = X.read_investigation(api, investigation["id"])
        assert_field_absent_or_null(after, "disclosure_risk_score", "investigation")
        assert_field_absent_or_null(after, "applicable_risk_variant", "investigation")
        stored_dataset = X.read_dataset(api, dataset["id"])
        assert stored_dataset["field_definition_count"] == 2, (
            "field_definition_count: expected 2, got "
            f"{stored_dataset['field_definition_count']}"
        )
        assert stored_dataset["documentation_status"] == C.DOC_STATUS_COMPLETE, (
            "documentation_status: expected COMPLETE once field_definition_count "
            f"reached expected_field_count, got {stored_dataset['documentation_status']!r}"
        )


_PRECISION_SPECS = [
    {"field_name": "tenant_zip", "reidentification_risk": 8},
    {"field_name": "violation_class", "reidentification_risk": 3},
    {
        "field_name": "inspector_badge_id",
        "reidentification_risk": 6,
        "is_source_identifying": True,
    },
]

_CLAMP_SPECS = [
    {"field_name": "full_address", "reidentification_risk": 10},
    {
        "field_name": "tipster_phone",
        "reidentification_risk": 10,
        "is_source_identifying": True,
    },
]

_TIER_SPECS = [{"field_name": "closure_district", "reidentification_risk": 4}]


def _full_release_base(api):
    """A ``FULL_DATA_RELEASE`` investigation with a released request to hang datasets on."""
    X.set_clock(api, C.STD_CLOCK)
    desk, agency = X.desk_and_agency(api)
    request = X.released_request(api, desk["id"], agency["id"])
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_FULL_DATA_RELEASE
    )
    return request, investigation


def _precision_probe(api, request_id, investigation_id):
    """5000 records at risks 8 and 3 unsuppressed, the risk-6 source column suppressed."""
    dataset, fields = _probe_dataset(
        api, request_id, investigation_id, 5000, _PRECISION_SPECS, "precision-probe"
    )
    X.suppress_field(
        api,
        dataset["id"],
        _field_id(fields, "inspector_badge_id"),
        suppression_method=_DROP_COLUMN,
    )
    return dataset


def _clamp_probe(api, request_id, investigation_id):
    """5000 records at risks 10 and 10, one of them an unsuppressed source column."""
    dataset, _fields = _probe_dataset(
        api, request_id, investigation_id, 5000, _CLAMP_SPECS, "clamp-probe"
    )
    return dataset


def _tier_probe(api, request_id, investigation_id, record_count, prefix):
    """One risk-4 column over a record count chosen to straddle the 1000-record tier."""
    dataset, _fields = _probe_dataset(
        api, request_id, investigation_id, record_count, _TIER_SPECS, prefix
    )
    return dataset


class TestCompositeRoundsThenPenalizesThenClamps:
    """The composite variant's three pinned operations, in order, on four datasets."""

    def test_the_product_is_rounded_half_up_exactly_once_after_the_multiplier(
        self, api
    ):
        """68.75 becomes 69, and the suppressed source column feeds neither variant.

        PRD S3.9: "`COMPOSITE_WEIGHTED` gives base 11 over count 2 for a density
        of 5.5, times 10 is 55, times the 1.25 multiplier is 68.75, which rounds
        half up to 69, plus a 0 penalty, so 69."

        Design: Corner/calculations/composite_disclosure_score_rounds_once_then_penalizes_then_clamps
        """
        request, investigation = _full_release_base(api)
        dataset = _precision_probe(api, request["id"], investigation["id"])

        preview = _preview(api, investigation["id"], dataset["id"])

        assert preview["composite_weighted_score"] == 69, (
            "composite_weighted_score: 5.5 density x 10 x 1.25 = 68.75 must round "
            f"half up once to 69, got {preview['composite_weighted_score']}"
        )
        assert preview["aggregate_max_score"] == 80, (
            "aggregate_max_score: expected 80 with no source bump because the "
            f"source-identifying column is suppressed, got {preview['aggregate_max_score']}"
        )
        assert preview["applicable_variant"] == C.VARIANT_COMPOSITE_WEIGHTED, (
            "applicable_variant: expected COMPOSITE_WEIGHTED under FULL_DATA_RELEASE, "
            f"got {preview['applicable_variant']!r}"
        )
        assert preview["applicable_score"] == 69, (
            f"applicable_score: expected the composite 69, got {preview['applicable_score']}"
        )

    def test_the_source_penalty_is_added_before_the_clamp_not_after(self, api):
        """Density 10 scales to 125, the penalty makes 150, and only then it clamps.

        PRD S3.9: "round that product half up to an integer **once**, after the
        multiplier and **before** any penalty; add 25 if any unsuppressed field
        is source-identifying; and clamp to at most 100 last."

        Design: Corner/calculations/composite_disclosure_score_rounds_once_then_penalizes_then_clamps
        """
        request, investigation = _full_release_base(api)
        dataset = _clamp_probe(api, request["id"], investigation["id"])

        preview = _preview(api, investigation["id"], dataset["id"])

        assert preview["composite_weighted_score"] == 100, (
            "composite_weighted_score: density 10 x 10 x 1.25 = 125, plus the 25 "
            "penalty is 150, clamped last to 100, got "
            f"{preview['composite_weighted_score']}"
        )
        assert preview["aggregate_max_score"] == 100, (
            "aggregate_max_score: 10 x 10 plus the 10 source bump is 110, clamped "
            f"to 100, got {preview['aggregate_max_score']}"
        )
        assert preview["applicable_score"] == 100, (
            f"applicable_score: expected the composite 100, got {preview['applicable_score']}"
        )

    def test_the_size_multiplier_steps_up_at_exactly_one_thousand_records(self, api):
        """999 records keep the 1.0 multiplier; 1000 records take the 1.25 one.

        PRD S3.9: "multiply the density by 10 and then by the size multiplier —
        1.0 when `record_count` is below 1000, 1.25 when it is at least 1000 and
        below 100000, and 1.5 when it is at least 100000".

        Design: Corner/calculations/composite_disclosure_score_rounds_once_then_penalizes_then_clamps
        """
        request, investigation = _full_release_base(api)
        below = _tier_probe(api, request["id"], investigation["id"], 999, "tier-999-probe")
        at = _tier_probe(api, request["id"], investigation["id"], 1000, "tier-1000-probe")

        preview_below = _preview(api, investigation["id"], below["id"])
        preview_at = _preview(api, investigation["id"], at["id"])

        assert preview_below["composite_weighted_score"] == 40, (
            "composite_weighted_score at 999 records: density 4 x 10 x 1.0 = 40, got "
            f"{preview_below['composite_weighted_score']}"
        )
        assert preview_at["composite_weighted_score"] == 50, (
            "composite_weighted_score at 1000 records: density 4 x 10 x 1.25 = 50, got "
            f"{preview_at['composite_weighted_score']}"
        )
        assert preview_below["aggregate_max_score"] == 40, (
            "aggregate_max_score at 999 records: expected 40, got "
            f"{preview_below['aggregate_max_score']}"
        )
        assert preview_at["aggregate_max_score"] == 40, (
            "aggregate_max_score must ignore record_count entirely: expected 40, got "
            f"{preview_at['aggregate_max_score']}"
        )

    def test_four_rehearsals_leave_the_investigation_untouched(self, api):
        """Scoring four candidate release datasets advances nothing at all.

        PRD S3.9: "It persists nothing and advances no state machine."

        Design: Corner/calculations/composite_disclosure_score_rounds_once_then_penalizes_then_clamps
        """
        request, investigation = _full_release_base(api)
        precision = _precision_probe(api, request["id"], investigation["id"])
        clamp = _clamp_probe(api, request["id"], investigation["id"])
        below = _tier_probe(api, request["id"], investigation["id"], 999, "tier-999-probe")
        at = _tier_probe(api, request["id"], investigation["id"], 1000, "tier-1000-probe")

        for dataset_id in (precision["id"], clamp["id"], below["id"], at["id"]):
            _preview(api, investigation["id"], dataset_id)

        after = X.read_investigation(api, investigation["id"])
        assert_field_absent_or_null(after, "disclosure_risk_score", "investigation")
        assert_field_absent_or_null(after, "applicable_risk_variant", "investigation")
        assert_field_absent_or_null(after, "published_at", "investigation")
        assert after["status"] == C.INV_DRAFTING, (
            f"status: expected DRAFTING after four rehearsals, got {after['status']!r}"
        )


_CEILING_SPECS = [
    {"field_name": "ward_code", "reidentification_risk": 6},
    {
        "field_name": "inspector_badge_id",
        "reidentification_risk": 7,
        "is_source_identifying": True,
    },
    {"field_name": "case_number", "reidentification_risk": 7},
]

_METHODOLOGY_REF = "methodology-v1"


def _ceiling_bundle(api):
    """A ``FINDINGS_LOCKED`` AGGREGATES_ONLY investigation whose release dataset scores 70+."""
    X.set_clock(api, C.STD_CLOCK)
    bundle = X.locked_investigation(
        api,
        C.MODE_AGGREGATES_ONLY,
        subject_count=0,
        record_count=500,
        field_specs=_CEILING_SPECS,
    )
    bundle["fields"] = _fields_by_name(api, bundle["dataset"]["id"])
    return bundle


def _publish(api, investigation_id, release_dataset_id=F.OMIT):
    """Attempt the publication of PRD S3.9 with the methodology write-up named.

    ``release_dataset_id`` is left out of the payload entirely unless one is
    given, which is what a ``METHODOLOGY_ONLY`` release requires.
    """
    return api.publish_investigation(
        investigation_id,
        F.publication_payload(
            release_dataset_id=release_dataset_id,
            methodology_doc_ref=_METHODOLOGY_REF,
        ),
        editor_headers(),
    )


class TestPublishRiskCeiling:
    """Exactly 60 publishes, 70 does not, and source exposure answers first."""

    def test_an_unsuppressed_source_column_answers_before_the_risk_score(self, api):
        """Source exposure sits one rung above disclosure risk, so it wins.

        PRD S2.11: "a release dataset that still carries any field definition
        with `is_source_identifying` true and `suppression_applied` false is
        `ERR_SOURCE_EXPOSURE_RISK`, because an unsuppressed source-identifying
        column would burn a source."

        Design: Corner/calculations/publish_risk_ceiling_admits_exactly_sixty_and_refuses_seventy
        """
        bundle = _ceiling_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        version_before = X.investigation_version(api, investigation_id)

        validate_error(
            _publish(api, investigation_id, bundle["dataset"]["id"]),
            ERR_SOURCE_EXPOSURE_RISK,
        )

        after = X.read_investigation(api, investigation_id)
        assert after["status"] == C.INV_FINDINGS_LOCKED, (
            f"status: expected FINDINGS_LOCKED after the refusal, got {after['status']!r}"
        )
        assert_field_absent_or_null(after, "published_at", "investigation")
        assert_field_absent_or_null(after, "disclosure_risk_score", "investigation")
        assert after["version"] == version_before, (
            f"version: a refused publication must not bump it from {version_before}, "
            f"got {after['version']}"
        )

    def test_seventy_is_one_step_above_the_ceiling_and_is_refused(self, api):
        """With the source column suppressed the remaining risks 6 and 7 read 70.

        PRD S3.9: "raise that one field to risk 7 and both variants read 70 and
        the publication is refused."

        Design: Corner/calculations/publish_risk_ceiling_admits_exactly_sixty_and_refuses_seventy
        """
        bundle = _ceiling_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        suppressed = X.suppress_field(
            api,
            bundle["dataset"]["id"],
            bundle["fields"]["inspector_badge_id"]["id"],
            suppression_method=_DROP_COLUMN,
        )
        assert suppressed["suppression_applied"] is True, (
            "suppression_applied: expected true once the column is suppressed, got "
            f"{suppressed['suppression_applied']!r}"
        )

        validate_error(
            _publish(api, investigation_id, bundle["dataset"]["id"]),
            ERR_DISCLOSURE_RISK_TOO_HIGH,
        )

        after = X.read_investigation(api, investigation_id)
        assert after["status"] == C.INV_FINDINGS_LOCKED, (
            f"status: expected FINDINGS_LOCKED after the refusal, got {after['status']!r}"
        )
        assert_field_absent_or_null(after, "published_at", "investigation")

    def test_a_score_of_exactly_sixty_blocks_nothing_in_the_rehearsal(self, api):
        """Both candidate datasets sit at or below the ceiling, so neither blocks.

        PRD S3.9: "exactly at the boundary: `record_count` 500 with a single
        unsuppressed field at risk 6 scores 60 under both variants and
        publishes".

        Design: Corner/calculations/publish_risk_ceiling_admits_exactly_sixty_and_refuses_seventy
        """
        bundle = _ceiling_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        X.suppress_field(
            api,
            bundle["dataset"]["id"],
            bundle["fields"]["inspector_badge_id"]["id"],
            suppression_method=_DROP_COLUMN,
        )
        X.suppress_field(
            api,
            bundle["dataset"]["id"],
            bundle["fields"]["case_number"]["id"],
            suppression_method=_HASH_REDACT,
        )
        below, _fields = _probe_dataset(
            api,
            bundle["request"]["id"],
            investigation_id,
            500,
            [{"field_name": "permit_class", "reidentification_risk": 5}],
            "below-probe",
        )

        at_ceiling = _preview(api, investigation_id, bundle["dataset"]["id"])
        under_ceiling = _preview(api, investigation_id, below["id"])

        assert at_ceiling["aggregate_max_score"] == C.PUBLISH_RISK_CEILING, (
            "aggregate_max_score: the single remaining risk-6 column scores 60, got "
            f"{at_ceiling['aggregate_max_score']}"
        )
        assert at_ceiling["applicable_variant"] == C.VARIANT_AGGREGATE_MAX, (
            "applicable_variant: expected AGGREGATE_MAX, got "
            f"{at_ceiling['applicable_variant']!r}"
        )
        assert at_ceiling["applicable_score"] == C.PUBLISH_RISK_CEILING, (
            f"applicable_score: expected 60, got {at_ceiling['applicable_score']}"
        )
        assert at_ceiling["blocking_reason_code"] == C.BLOCKING_REASON_NONE, (
            "blocking_reason_code: exactly 60 publishes, so nothing blocks; got "
            f"{at_ceiling['blocking_reason_code']!r}"
        )
        assert under_ceiling["aggregate_max_score"] == 50, (
            "aggregate_max_score for the risk-5 candidate: expected 50, got "
            f"{under_ceiling['aggregate_max_score']}"
        )
        assert under_ceiling["blocking_reason_code"] == C.BLOCKING_REASON_NONE, (
            "blocking_reason_code: 50 is under the ceiling, so nothing blocks; got "
            f"{under_ceiling['blocking_reason_code']!r}"
        )

    def test_a_score_of_exactly_sixty_publishes_and_stamps_the_release(self, api):
        """The publication succeeds at the boundary and records the variant it used.

        PRD S3.9: "A successful publication drives `FINDINGS_LOCKED` or
        `CLEARED` to `PUBLISHED`, stamps `methodology_doc_ref`,
        `release_dataset_id` and `published_at` from the logical clock, stamps
        `disclosure_risk_score` and `applicable_risk_variant` from the selected
        variant, and increments the investigation's `version` by 1."

        Design: Corner/calculations/publish_risk_ceiling_admits_exactly_sixty_and_refuses_seventy
        """
        bundle = _ceiling_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        X.suppress_field(
            api,
            bundle["dataset"]["id"],
            bundle["fields"]["inspector_badge_id"]["id"],
            suppression_method=_DROP_COLUMN,
        )
        X.suppress_field(
            api,
            bundle["dataset"]["id"],
            bundle["fields"]["case_number"]["id"],
            suppression_method=_HASH_REDACT,
        )
        version_before = X.investigation_version(api, investigation_id)

        published = validate_ok(
            _publish(api, investigation_id, bundle["dataset"]["id"])
        )

        assert published["status"] == C.INV_PUBLISHED, (
            f"status: expected PUBLISHED, got {published['status']!r}"
        )
        assert published["disclosure_risk_score"] == C.PUBLISH_RISK_CEILING, (
            "disclosure_risk_score: expected the stamped 60, got "
            f"{published['disclosure_risk_score']}"
        )
        assert published["applicable_risk_variant"] == C.VARIANT_AGGREGATE_MAX, (
            "applicable_risk_variant: expected AGGREGATE_MAX, got "
            f"{published['applicable_risk_variant']!r}"
        )
        assert published["release_dataset_id"] == bundle["dataset"]["id"], (
            "release_dataset_id: expected the dataset that was published, got "
            f"{published['release_dataset_id']!r}"
        )
        assert published["methodology_doc_ref"] == _METHODOLOGY_REF, (
            "methodology_doc_ref: expected the submitted write-up reference, got "
            f"{published['methodology_doc_ref']!r}"
        )
        assert_instant_equals(
            published["published_at"], C.STD_CLOCK, label="published_at"
        )
        assert published["version"] == version_before + 1, (
            f"version: expected {version_before + 1} after publication, got "
            f"{published['version']}"
        )


_FORCE_REPORT_SPECS = [
    {
        "field_name": "tipster_phone",
        "reidentification_risk": 10,
        "is_source_identifying": True,
    }
]


def _methodology_only_bundle(api):
    """A ``FINDINGS_LOCKED`` METHODOLOGY_ONLY investigation over frankly risky data."""
    X.set_clock(api, C.STD_CLOCK)
    return X.locked_investigation(
        api,
        C.MODE_METHODOLOGY_ONLY,
        subject_count=0,
        record_count=5000,
        field_specs=_FORCE_REPORT_SPECS,
    )


class TestMethodologyOnlySelectsTheNoneVariant:
    """A methodology write-up carries no data, so it carries no disclosure risk."""

    def test_the_none_variant_scores_zero_and_blocks_nothing(self, api):
        """Even over an unsuppressed risk-10 source column the applicable score is 0.

        PRD S3.9: "`METHODOLOGY_ONLY` stamps `NONE` and takes a score of 0, so a
        methodology-only publication is never blocked on disclosure risk."

        Design: Corner/calculations/methodology_only_selects_the_none_variant_and_forbids_a_release_dataset
        """
        bundle = _methodology_only_bundle(api)

        preview = _preview(api, bundle["investigation"]["id"])

        assert preview["applicable_variant"] == C.VARIANT_NONE, (
            "applicable_variant: expected NONE under METHODOLOGY_ONLY, got "
            f"{preview['applicable_variant']!r}"
        )
        assert preview["applicable_score"] == 0, (
            f"applicable_score: expected 0, got {preview['applicable_score']}"
        )
        assert preview["blocking_reason_code"] == C.BLOCKING_REASON_NONE, (
            "blocking_reason_code: a methodology-only release is never blocked on "
            f"disclosure risk; got {preview['blocking_reason_code']!r}"
        )

    def test_naming_a_release_dataset_is_refused_in_this_mode(self, api):
        """The release-dataset rule is bidirectional: this mode must not supply one.

        PRD S2.11: "a `publication_mode` of `FULL_DATA_RELEASE` or
        `AGGREGATES_ONLY` with no `release_dataset_id`, or a `METHODOLOGY_ONLY`
        publication that supplies one, is `ERR_RELEASE_DATASET_REQUIRED`".

        Design: Corner/calculations/methodology_only_selects_the_none_variant_and_forbids_a_release_dataset
        """
        bundle = _methodology_only_bundle(api)
        investigation_id = bundle["investigation"]["id"]
        version_before = X.investigation_version(api, investigation_id)

        validate_error(
            _publish(api, investigation_id, bundle["dataset"]["id"]),
            ERR_RELEASE_DATASET_REQUIRED,
        )

        after = X.read_investigation(api, investigation_id)
        assert after["status"] == C.INV_FINDINGS_LOCKED, (
            f"status: expected FINDINGS_LOCKED after the refusal, got {after['status']!r}"
        )
        assert_field_absent_or_null(after, "published_at", "investigation")
        assert after["version"] == version_before, (
            f"version: a refused publication must not bump it from {version_before}, "
            f"got {after['version']}"
        )

    def test_publishing_without_a_release_dataset_succeeds(self, api):
        """The same investigation releases as soon as no dataset is named.

        PRD S3.9: "A successful publication drives `FINDINGS_LOCKED` or
        `CLEARED` to `PUBLISHED`, stamps `methodology_doc_ref`,
        `release_dataset_id` and `published_at` from the logical clock, stamps
        `disclosure_risk_score` and `applicable_risk_variant` from the selected
        variant, and increments the investigation's `version` by 1."

        Design: Corner/calculations/methodology_only_selects_the_none_variant_and_forbids_a_release_dataset
        """
        bundle = _methodology_only_bundle(api)
        investigation_id = bundle["investigation"]["id"]

        published = validate_ok(_publish(api, investigation_id))

        assert published["status"] == C.INV_PUBLISHED, (
            f"status: expected PUBLISHED, got {published['status']!r}"
        )
        assert published["applicable_risk_variant"] == C.VARIANT_NONE, (
            "applicable_risk_variant: expected NONE, got "
            f"{published['applicable_risk_variant']!r}"
        )
        assert published["disclosure_risk_score"] == 0, (
            f"disclosure_risk_score: expected 0, got {published['disclosure_risk_score']}"
        )
        assert_field_absent_or_null(published, "release_dataset_id", "investigation")
        assert published["methodology_doc_ref"] == _METHODOLOGY_REF, (
            "methodology_doc_ref: expected the submitted write-up reference, got "
            f"{published['methodology_doc_ref']!r}"
        )
        assert_instant_equals(
            published["published_at"], C.STD_CLOCK, label="published_at"
        )
