"""
Composable scenario builders.

The harness restarts the API server before every individual test, so every
precondition here is built from scratch through the published endpoints. The
builders are layered: tier 1 creates single rows, tier 2 puts an extract under a
cycle, tier 3 seals the census, tier 4 raises a survey component through
preparation and certification, and tier 5 freezes the cycle and reaches the
publication, cohort, submission and disclosure worlds that depend on a frozen or
census-locked cycle.

Every builder reads its results with get_success_data so that a setup failure
surfaces as a readable error identifier rather than a bare status mismatch.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_AFTER_CENSUS,
    COVERAGE_END,
    COVERAGE_START,
    DOMAIN_ENROLLMENT,
    EFFECTIVE_FROM,
    ENTRY_FULL_TIME,
    METRIC_TOTAL_HEADCOUNT,
    OUTCOME_STILL_ENROLLED,
)
from .test_users import (
    make_analyst_headers,
    make_director_headers,
    make_disclosure_headers,
    make_registrar_headers,
    make_steward_headers,
)


@dataclass
class Scenario:
    """The rows a builder created, in the order the domain layers them."""

    cycle: Dict[str, Any]
    extracts: List[Dict[str, Any]] = field(default_factory=list)
    components: List[Dict[str, Any]] = field(default_factory=list)
    metrics: List[Dict[str, Any]] = field(default_factory=list)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    cohorts: List[Dict[str, Any]] = field(default_factory=list)
    members: List[Dict[str, Any]] = field(default_factory=list)
    definitions: List[Dict[str, Any]] = field(default_factory=list)
    mappings: List[Dict[str, Any]] = field(default_factory=list)
    publications: List[Dict[str, Any]] = field(default_factory=list)
    restatements: List[Dict[str, Any]] = field(default_factory=list)
    submissions: List[Dict[str, Any]] = field(default_factory=list)
    requests: List[Dict[str, Any]] = field(default_factory=list)
    cells: List[Dict[str, Any]] = field(default_factory=list)

    # ── convenience accessors ──
    @property
    def cycle_id(self) -> str:
        return self.cycle["id"]

    @property
    def cycle_version(self) -> int:
        return self.cycle["version"]

    @property
    def extract(self) -> Dict[str, Any]:
        return self.extracts[0]

    @property
    def extract_id(self) -> str:
        return self.extracts[0]["id"]

    @property
    def component(self) -> Dict[str, Any]:
        return self.components[0]

    @property
    def component_id(self) -> str:
        return self.components[0]["id"]

    @property
    def cohort(self) -> Dict[str, Any]:
        return self.cohorts[0]

    @property
    def cohort_id(self) -> str:
        return self.cohorts[0]["id"]

    @property
    def publication(self) -> Dict[str, Any]:
        return self.publications[0]

    @property
    def publication_id(self) -> str:
        return self.publications[0]["id"]

    @property
    def submission(self) -> Dict[str, Any]:
        return self.submissions[0]

    @property
    def submission_id(self) -> str:
        return self.submissions[0]["id"]

    @property
    def request(self) -> Dict[str, Any]:
        return self.requests[0]

    @property
    def request_id(self) -> str:
        return self.requests[0]["id"]

    def metric(self, metric_key: str) -> Dict[str, Any]:
        for row in self.metrics:
            if row["metric_key"] == metric_key:
                return row
        raise KeyError(f"no metric {metric_key!r} was created in this scenario")

    def member(self, student_local_id: str) -> Dict[str, Any]:
        for row in self.members:
            if row["student_local_id"] == student_local_id:
                return row
        raise KeyError(f"no member {student_local_id!r} was created in this scenario")


# ═══ Tier 1 — the logical clock and single rows ═══════════════════


def move_clock(api: ApiClient, instant: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Set the authoritative logical clock every server-written timestamp is minted from."""
    response = api.set_clock(instant, headers or make_registrar_headers())
    return get_success_data(response)


def create_cycle(api: ApiClient, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
    response = api.create_reporting_cycle(
        f.make_reporting_cycle_payload(**overrides), headers or make_registrar_headers()
    )
    return get_success_data(response, 201)


def read_cycle(api: ApiClient, cycle_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_reporting_cycle(cycle_id, headers or make_registrar_headers()))


def create_definition(api: ApiClient, headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
    response = api.create_federal_definition(
        f.make_federal_definition_payload(**overrides), headers or make_steward_headers()
    )
    return get_success_data(response, 201)


def propose_mapping(
    api: ApiClient,
    cycle_id: str,
    definition_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    response = api.propose_element_mapping(
        f.make_element_mapping_payload(cycle_id, definition_id, **overrides),
        headers or make_analyst_headers(),
    )
    return get_success_data(response, 201)


def validated_mapping(
    api: ApiClient,
    cycle_id: str,
    definition_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A mapping that has passed the data steward's value-domain check."""
    mapping = propose_mapping(api, cycle_id, definition_id, **overrides)
    response = api.validate_element_mapping(
        mapping["id"], f.make_mapping_verdict_payload(), make_steward_headers()
    )
    return get_success_data(response)


# ═══ Tier 2 — a cycle carrying census extracts ════════════════════


def register_extract(
    api: ApiClient,
    cycle_id: str,
    expected_cycle_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register one census extract, refreshing the optimistic concurrency token if needed."""
    if expected_cycle_version is None:
        expected_cycle_version = read_cycle(api, cycle_id)["version"]
    response = api.register_frozen_file(
        cycle_id,
        f.make_frozen_file_payload(expected_cycle_version, **overrides),
        headers or make_registrar_headers(),
    )
    return get_success_data(response, 201)


def open_cycle_with_extract(
    api: ApiClient,
    domain: str = DOMAIN_ENROLLMENT,
    record_count: int = 1000,
    coverage_start_date: str = COVERAGE_START,
    coverage_end_date: str = COVERAGE_END,
    checksum: Optional[str] = None,
    **cycle_overrides: Any,
) -> Scenario:
    """An OPEN cycle with one ACTIVE extract, the state census locking requires."""
    cycle = create_cycle(api, **cycle_overrides)
    extract = register_extract(
        api,
        cycle["id"],
        expected_cycle_version=cycle["version"],
        domain=domain,
        record_count=record_count,
        coverage_start_date=coverage_start_date,
        coverage_end_date=coverage_end_date,
        checksum=checksum,
    )
    return Scenario(cycle=read_cycle(api, cycle["id"]), extracts=[extract])


# ═══ Tier 3 — a sealed census snapshot ════════════════════════════


def census_locked_cycle(
    api: ApiClient,
    domain: str = DOMAIN_ENROLLMENT,
    record_count: int = 1000,
    clock: str = CLOCK_AFTER_CENSUS,
    checksum: Optional[str] = None,
    **cycle_overrides: Any,
) -> Scenario:
    """A CENSUS_LOCKED cycle whose extracts are all LOCKED, ready for components."""
    scenario = open_cycle_with_extract(
        api, domain=domain, record_count=record_count, checksum=checksum, **cycle_overrides
    )
    move_clock(api, clock)
    cycle = get_success_data(api.census_lock_cycle(scenario.cycle_id, make_registrar_headers()))
    scenario.cycle = cycle
    scenario.extracts = [get_success_data(api.get_frozen_file(scenario.extract_id, make_registrar_headers()))]
    return scenario


# ═══ Tier 4 — a survey component through preparation and certification ═══

DEFAULT_METRICS: Sequence[Dict[str, Any]] = (
    {"metric_key": METRIC_TOTAL_HEADCOUNT, "reported_value": 1000, "prior_year_value": 1000},
)


def add_metrics(
    api: ApiClient,
    component_id: str,
    specs: Sequence[Dict[str, Any]] = DEFAULT_METRICS,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Attach reported survey metrics, each carrying its value as a JSON number."""
    rows: List[Dict[str, Any]] = []
    for spec in specs:
        response = api.add_component_metric(
            component_id, f.make_metric_payload(**spec), headers or make_analyst_headers()
        )
        rows.append(get_success_data(response, 201))
    return rows


def component_on_locked_cycle(
    api: ApiClient,
    domain: str = DOMAIN_ENROLLMENT,
    record_count: int = 1000,
    metrics: Sequence[Dict[str, Any]] = DEFAULT_METRICS,
    clock: str = CLOCK_AFTER_CENSUS,
    checksum: Optional[str] = None,
    **cycle_overrides: Any,
) -> Scenario:
    """A DRAFT survey component bound to a locked extract of the same domain."""
    scenario = census_locked_cycle(
        api,
        domain=domain,
        record_count=record_count,
        clock=clock,
        checksum=checksum,
        **cycle_overrides,
    )
    component = get_success_data(
        api.create_survey_component(
            f.make_survey_component_payload(
                scenario.cycle_id, scenario.extract_id, component_code=domain
            ),
            make_analyst_headers(),
        ),
        201,
    )
    scenario.components = [component]
    scenario.metrics = add_metrics(api, component["id"], metrics)
    return scenario


def prepared_component(
    api: ApiClient,
    domain: str = DOMAIN_ENROLLMENT,
    record_count: int = 1000,
    metrics: Sequence[Dict[str, Any]] = DEFAULT_METRICS,
    clock: str = CLOCK_AFTER_CENSUS,
    checksum: Optional[str] = None,
    **cycle_overrides: Any,
) -> Scenario:
    """A PREPARED component whose edit checks have already been raised."""
    scenario = component_on_locked_cycle(
        api,
        domain=domain,
        record_count=record_count,
        metrics=metrics,
        clock=clock,
        checksum=checksum,
        **cycle_overrides,
    )
    scenario.components = [
        get_success_data(api.prepare_component(scenario.component_id, make_analyst_headers()))
    ]
    scenario.checks = list_checks(api, scenario.component_id)
    return scenario


def list_checks(api: ApiClient, component_id: str) -> List[Dict[str, Any]]:
    """The component's edit checks in their declared sequence_no ascending order."""
    response = api.list_edit_checks(make_analyst_headers(), component_id=component_id, limit=100)
    return get_success_data(response)


def resolve_all_checks(api: ApiClient, component_id: str) -> List[Dict[str, Any]]:
    """Explain then accept every open check so the component reaches CLEARED."""
    resolved: List[Dict[str, Any]] = []
    for check in list_checks(api, component_id):
        explained = get_success_data(
            api.explain_edit_check(check["id"], f.make_explanation_payload(), make_analyst_headers())
        )
        resolved.append(
            get_success_data(
                api.adjudicate_edit_check(
                    explained["id"], f.make_adjudication_payload(), make_director_headers()
                )
            )
        )
    return resolved


def certified_component(
    api: ApiClient,
    domain: str = DOMAIN_ENROLLMENT,
    record_count: int = 1000,
    metrics: Sequence[Dict[str, Any]] = DEFAULT_METRICS,
    clock: str = CLOCK_AFTER_CENSUS,
    checksum: Optional[str] = None,
    **cycle_overrides: Any,
) -> Scenario:
    """A CERTIFIED component: prepared by the analyst and certified by the director."""
    scenario = prepared_component(
        api,
        domain=domain,
        record_count=record_count,
        metrics=metrics,
        clock=clock,
        checksum=checksum,
        **cycle_overrides,
    )
    if scenario.checks:
        scenario.checks = resolve_all_checks(api, scenario.component_id)
    scenario.components = [
        get_success_data(
            api.certify_component(
                scenario.component_id, f.make_certification_payload(), make_director_headers()
            )
        )
    ]
    return scenario


# ═══ Tier 5 — a frozen cycle and the worlds that depend on it ═════


def frozen_cycle(
    api: ApiClient,
    domain: str = DOMAIN_ENROLLMENT,
    record_count: int = 1000,
    metrics: Sequence[Dict[str, Any]] = DEFAULT_METRICS,
    clock: str = CLOCK_AFTER_CENSUS,
    checksum: Optional[str] = None,
    **cycle_overrides: Any,
) -> Scenario:
    """A FROZEN cycle: one certified component, publication and disclosure now open."""
    scenario = certified_component(
        api,
        domain=domain,
        record_count=record_count,
        metrics=metrics,
        clock=clock,
        checksum=checksum,
        **cycle_overrides,
    )
    scenario.cycle = get_success_data(api.freeze_cycle(scenario.cycle_id, make_director_headers()))
    return scenario


# ── cohorts ──


def add_members(
    api: ApiClient,
    cohort_id: str,
    roster: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for spec in roster:
        response = api.add_cohort_member(
            cohort_id, f.make_member_payload(**spec), make_registrar_headers()
        )
        rows.append(get_success_data(response, 201))
    return rows


def roster_of(*outcomes: str, entry_status: str = ENTRY_FULL_TIME) -> List[Dict[str, Any]]:
    """Build a roster of S001..S00n, one entry per supplied tracked outcome."""
    return [
        {
            "student_local_id": f"S{index:03d}",
            "entry_status": entry_status,
            "outcome": outcome or OUTCOME_STILL_ENROLLED,
        }
        for index, outcome in enumerate(outcomes, start=1)
    ]


def cohort_on_scenario(
    api: ApiClient,
    scenario: Scenario,
    roster: Sequence[Dict[str, Any]] = (),
    **cohort_overrides: Any,
) -> Scenario:
    """Define a cohort against an existing cycle and seat its roster."""
    cohort = get_success_data(
        api.create_cohort(
            scenario.cycle_id, f.make_cohort_payload(**cohort_overrides), make_registrar_headers()
        ),
        201,
    )
    scenario.cohorts.append(cohort)
    if roster:
        scenario.members.extend(add_members(api, cohort["id"], roster))
        scenario.cohorts[-1] = get_success_data(
            api.get_cohort(cohort["id"], make_registrar_headers())
        )
    return scenario


def cohort_with_roster(
    api: ApiClient,
    roster: Sequence[Dict[str, Any]],
    metrics: Sequence[Dict[str, Any]] = DEFAULT_METRICS,
    record_count: int = 1000,
    checksum: Optional[str] = None,
    **cohort_overrides: Any,
) -> Scenario:
    """A DRAFT cohort with a seated roster on a census-locked cycle."""
    scenario = census_locked_cycle(api, record_count=record_count, checksum=checksum)
    return cohort_on_scenario(api, scenario, roster, **cohort_overrides)


# ── publications and restatements ──


def publish_metric(
    api: ApiClient,
    scenario: Scenario,
    metric_key: str = "TOTAL_HEADCOUNT_FALL",
    published_value: float = 1000.0,
    effective_from: str = EFFECTIVE_FROM,
    **overrides: Any,
) -> Dict[str, Any]:
    """Publish one dashboard figure over a half-open effective window."""
    response = api.create_publication(
        f.make_publication_payload(
            scenario.component_id,
            metric_key=metric_key,
            published_value=published_value,
            effective_from=effective_from,
            **overrides,
        ),
        make_analyst_headers(),
    )
    publication = get_success_data(response, 201)
    scenario.publications.append(publication)
    return publication


def published_figure(
    api: ApiClient,
    metric_key: str = "TOTAL_HEADCOUNT_FALL",
    published_value: float = 1000.0,
    metrics: Sequence[Dict[str, Any]] = DEFAULT_METRICS,
    record_count: int = 1000,
    checksum: Optional[str] = None,
    **cycle_overrides: Any,
) -> Scenario:
    """A FROZEN cycle carrying one PUBLISHED dashboard figure."""
    scenario = frozen_cycle(
        api, metrics=metrics, record_count=record_count, checksum=checksum, **cycle_overrides
    )
    publish_metric(api, scenario, metric_key=metric_key, published_value=published_value)
    return scenario


def file_restatement(
    api: ApiClient,
    scenario: Scenario,
    proposed_value: float,
    publication: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_publication_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    target = publication or scenario.publication
    if expected_publication_version is None:
        expected_publication_version = get_success_data(
            api.get_publication(target["id"], make_analyst_headers())
        )["version"]
    response = api.file_restatement(
        target["id"],
        f.make_restatement_payload(proposed_value, expected_publication_version, **overrides),
        headers or make_analyst_headers(),
    )
    restatement = get_success_data(response, 201)
    scenario.restatements.append(restatement)
    return restatement


# ── external submissions ──


def draft_submission(
    api: ApiClient,
    scenario: Scenario,
    **overrides: Any,
) -> Dict[str, Any]:
    response = api.create_external_submission(
        f.make_external_submission_payload(scenario.cycle_id, scenario.component_id, **overrides),
        make_analyst_headers(),
    )
    submission = get_success_data(response, 201)
    scenario.submissions.append(submission)
    return submission


# ── data requests and disclosure cells ──


def intake_request(
    api: ApiClient,
    scenario: Scenario,
    **overrides: Any,
) -> Dict[str, Any]:
    response = api.create_data_request(
        scenario.cycle_id, f.make_data_request_payload(**overrides), make_disclosure_headers()
    )
    request = get_success_data(response, 201)
    scenario.requests.append(request)
    return request


def add_cells(
    api: ApiClient,
    scenario: Scenario,
    dimension_group: str,
    counts: Sequence[Any],
    request: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Add one raw crosstab cell per (dimension_key, raw_count) pair supplied."""
    target = request or scenario.request
    rows: List[Dict[str, Any]] = []
    for dimension_key, raw_count in counts:
        response = api.add_disclosure_cell(
            target["id"],
            f.make_disclosure_cell_payload(dimension_group, dimension_key, raw_count),
            make_disclosure_headers(),
        )
        rows.append(get_success_data(response, 201))
    scenario.cells.extend(rows)
    return rows


def request_with_cells(
    api: ApiClient,
    dimension_group: str,
    counts: Sequence[Any],
    metrics: Sequence[Dict[str, Any]] = DEFAULT_METRICS,
    record_count: int = 1000,
    checksum: Optional[str] = None,
    **request_overrides: Any,
) -> Scenario:
    """A RECEIVED data request holding a crosstab, on a FROZEN cycle ready to screen."""
    scenario = frozen_cycle(api, metrics=metrics, record_count=record_count, checksum=checksum)
    intake_request(api, scenario, **request_overrides)
    add_cells(api, scenario, dimension_group, counts)
    scenario.requests = [
        get_success_data(api.get_data_request(scenario.request_id, make_disclosure_headers()))
    ]
    return scenario


def screened_request(
    api: ApiClient,
    dimension_group: str,
    counts: Sequence[Any],
    **request_overrides: Any,
) -> Scenario:
    """A SCREENED data request whose crosstab has already run through avoidance."""
    scenario = request_with_cells(api, dimension_group, counts, **request_overrides)
    scenario.requests = [
        get_success_data(api.screen_data_request(scenario.request_id, make_disclosure_headers()))
    ]
    scenario.cells = get_success_data(
        api.list_disclosure_cells(make_disclosure_headers(), request_id=scenario.request_id, limit=100)
    )
    return scenario
