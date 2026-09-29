"""Scenario builders that assemble programme state through the public API.

Every test begins against an empty store, so all state is built by walking the
documented workflow: reposition the clock, publish a methodology, onboard a
grower, register and survey a field, file the historical evidence base, create
and screen an enrollment, adjudicate a baseline, file and quality-control
observations, quantify, verify and issue.

Setup calls go through the lenient success reader, so a setup failure raises a
clear assertion naming the refused step rather than a downstream key error.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import (
    BASELINE_HISTORICAL_DATA,
    CLOCK_2026,
    CROP_YEAR_2026,
    EVIDENCE_EQUIPMENT_TELEMETRY,
    EVIDENCE_FARM_RECORD,
    EVIDENCE_REMOTE_SENSING,
    METHOD_MODEL,
    OPINION_POSITIVE,
    POOL_CODE_PROGRAM_BUFFER,
)
from .test_users import (
    ADMIN_BASELINE_HEADERS,
    ADMIN_HEADERS,
    ADMIN_SCREENER_HEADERS,
    REGISTRY_HEADERS,
    grower_headers,
    verifier_headers,
)

#: The five historical crop years of the reference evidence base (§3.2, §3.3).
#: The 2021 farm record and the 2022 remote-sensing record report adopted acres;
#: the last three years document the field without claiming adoption.
REFERENCE_HISTORY = (
    {
        "crop_year": 2021,
        "evidence_source": EVIDENCE_FARM_RECORD,
        "adopted": True,
        "acres": 200.00,
        "observed_emissions_per_acre": 0.1000,
    },
    {
        "crop_year": 2022,
        "evidence_source": EVIDENCE_REMOTE_SENSING,
        "adopted": True,
        "acres": 500.00,
        "observed_emissions_per_acre": 0.1200,
    },
    {
        "crop_year": 2023,
        "evidence_source": EVIDENCE_FARM_RECORD,
        "adopted": False,
        "acres": 0.00,
        "observed_emissions_per_acre": 0.1400,
    },
    {
        "crop_year": 2024,
        "evidence_source": EVIDENCE_EQUIPMENT_TELEMETRY,
        "adopted": False,
        "acres": 0.00,
        "observed_emissions_per_acre": 0.1600,
    },
    {
        "crop_year": 2025,
        "evidence_source": EVIDENCE_FARM_RECORD,
        "adopted": False,
        "acres": 0.00,
        "observed_emissions_per_acre": 0.1800,
    },
)


class Scenario:
    """A mutable handle on one scenario's rows, built step by step."""

    def __init__(self, api: ApiClient):
        self.api = api
        self.grower: Optional[Dict[str, Any]] = None
        self.field: Optional[Dict[str, Any]] = None
        self.standard: Optional[Dict[str, Any]] = None
        self.enrollment: Optional[Dict[str, Any]] = None
        self.baseline: Optional[Dict[str, Any]] = None
        self.packets: List[Dict[str, Any]] = []
        self.run: Optional[Dict[str, Any]] = None
        self.body: Optional[Dict[str, Any]] = None
        self.verification: Optional[Dict[str, Any]] = None
        self.batch: Optional[Dict[str, Any]] = None

    # ── identities ────────────────────────────────────────────────────────
    @property
    def grower_id(self) -> str:
        assert self.grower is not None, "no grower in this scenario yet"
        return self.grower["id"]

    @property
    def field_id(self) -> str:
        assert self.field is not None, "no field in this scenario yet"
        return self.field["id"]

    @property
    def standard_id(self) -> str:
        assert self.standard is not None, "no practice standard in this scenario yet"
        return self.standard["id"]

    @property
    def enrollment_id(self) -> str:
        assert self.enrollment is not None, "no enrollment in this scenario yet"
        return self.enrollment["id"]

    @property
    def baseline_id(self) -> str:
        assert self.baseline is not None, "no baseline in this scenario yet"
        return self.baseline["id"]

    @property
    def run_id(self) -> str:
        assert self.run is not None, "no quantification run in this scenario yet"
        return self.run["id"]

    @property
    def body_id(self) -> str:
        assert self.body is not None, "no verification body in this scenario yet"
        return self.body["id"]

    @property
    def verification_id(self) -> str:
        assert self.verification is not None, "no verification in this scenario yet"
        return self.verification["id"]

    @property
    def batch_id(self) -> str:
        assert self.batch is not None, "no credit batch in this scenario yet"
        return self.batch["id"]

    @property
    def grower_auth(self) -> Dict[str, str]:
        """Headers for the scenario's grower acting on its own records."""
        return grower_headers(self.grower_id)

    @property
    def verifier_auth(self) -> Dict[str, str]:
        """Headers for the scenario's verification body."""
        return verifier_headers(self.body_id)

    # ── the logical clock ────────────────────────────────────────────────
    def set_clock(self, current_utc: str = CLOCK_2026) -> Dict[str, Any]:
        """Reposition the logical programme clock."""
        return get_success_data(self.api.set_clock(f.clock_payload(current_utc)))

    # ── growers, fields and history ──────────────────────────────────────
    def create_grower(self, **overrides: Any) -> Dict[str, Any]:
        """Onboard a grower and remember it as the scenario's grower."""
        self.grower = get_success_data(
            self.api.create_grower(f.grower_payload(**overrides), ADMIN_HEADERS)
        )
        return self.grower

    def create_field(self, grower_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        """Register a field under a grower and remember it."""
        self.field = get_success_data(
            self.api.create_field(
                grower_id or self.grower_id, f.field_payload(**overrides), ADMIN_HEADERS
            )
        )
        return self.field

    def register_field(self, grower_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        """Register an additional field without replacing the scenario's field."""
        return get_success_data(
            self.api.create_field(
                grower_id or self.grower_id, f.field_payload(**overrides), ADMIN_HEADERS
            )
        )

    def map_confirm(self, field_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        """Confirm a draft field's survey, making it eligible for enrollment."""
        confirmed = get_success_data(
            self.api.map_confirm_field(
                field_id or self.field_id, f.map_confirm_payload(**overrides), ADMIN_HEADERS
            )
        )
        if self.field is not None and confirmed["id"] == self.field["id"]:
            self.field = confirmed
        return confirmed

    def mapped_field(self, grower_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        """Register a field and confirm its survey in one step."""
        self.create_field(grower_id, **overrides)
        return self.map_confirm()

    def file_history(self, crop_year: int, field_id: Optional[str] = None,
                     **overrides: Any) -> Dict[str, Any]:
        """File one crop year of historical practice evidence."""
        return get_success_data(
            self.api.file_practice_history(
                field_id or self.field_id,
                f.practice_history_payload(crop_year, **overrides),
                ADMIN_HEADERS,
            )
        )

    def file_reference_history(self, field_id: Optional[str] = None,
                               **overrides: Any) -> List[Dict[str, Any]]:
        """File the reference five-year evidence base against a field."""
        rows = []
        for row in REFERENCE_HISTORY:
            merged = dict(row)
            merged.update(overrides)
            crop_year = merged.pop("crop_year")
            rows.append(self.file_history(crop_year, field_id, **merged))
        return rows

    def file_scaled_history(self, farm_acres: float, remote_acres: float,
                            field_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The reference evidence base with the two adopted rows rescaled.

        Scaling both adopted rows in proportion to the field's acreage keeps the
        weighted prior adoption at the reference 12.00 per cent on a larger field.
        """
        rows = []
        for row in REFERENCE_HISTORY:
            merged = dict(row)
            crop_year = merged.pop("crop_year")
            if crop_year == 2021:
                merged["acres"] = farm_acres
            elif crop_year == 2022:
                merged["acres"] = remote_acres
            rows.append(self.file_history(crop_year, field_id, **merged))
        return rows

    # ── methodologies ────────────────────────────────────────────────────
    def publish_standard(self, **overrides: Any) -> Dict[str, Any]:
        """Publish a methodology and remember it as the scenario's standard."""
        self.standard = get_success_data(
            self.api.create_practice_standard(
                f.practice_standard_payload(**overrides), ADMIN_HEADERS
            )
        )
        return self.standard

    # ── enrollment and screening ─────────────────────────────────────────
    def create_enrollment(self, field_id: Optional[str] = None,
                          standard_id: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None,
                          **overrides: Any) -> Dict[str, Any]:
        """Create a draft enrollment and remember it."""
        self.enrollment = get_success_data(
            self.api.create_enrollment(
                f.enrollment_payload(
                    field_id or self.field_id, standard_id or self.standard_id, **overrides
                ),
                headers or ADMIN_HEADERS,
            )
        )
        return self.enrollment

    def create_per_acre_enrollment(self, field_id: Optional[str] = None,
                                   standard_id: Optional[str] = None,
                                   **overrides: Any) -> Dict[str, Any]:
        """Create a draft per-acre enrollment and remember it."""
        self.enrollment = get_success_data(
            self.api.create_enrollment(
                f.per_acre_enrollment_payload(
                    field_id or self.field_id, standard_id or self.standard_id, **overrides
                ),
                ADMIN_HEADERS,
            )
        )
        return self.enrollment

    def submit_enrollment(self, enrollment_id: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Submit an enrollment for additionality screening."""
        self.enrollment = get_success_data(
            self.api.submit_enrollment(
                enrollment_id or self.enrollment_id, None, headers or ADMIN_HEADERS
            )
        )
        return self.enrollment

    def screen_enrollment(self, decision: str = "ACCEPT",
                          enrollment_id: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None,
                          **overrides: Any) -> Dict[str, Any]:
        """Adjudicate a screened enrollment as the screening administrator."""
        self.enrollment = get_success_data(
            self.api.screen_enrollment(
                enrollment_id or self.enrollment_id,
                f.screen_payload(decision, **overrides),
                headers or ADMIN_SCREENER_HEADERS,
            )
        )
        return self.enrollment

    def reload_enrollment(self, enrollment_id: Optional[str] = None) -> Dict[str, Any]:
        """Re-read the enrollment, refreshing its stored version."""
        self.enrollment = get_success_data(
            self.api.get_enrollment(enrollment_id or self.enrollment_id, ADMIN_HEADERS)
        )
        return self.enrollment

    @property
    def enrollment_version(self) -> int:
        """The enrollment's version as last observed."""
        return self.reload_enrollment()["version"]

    # ── baselines ────────────────────────────────────────────────────────
    def propose_baseline(self, method: str = BASELINE_HISTORICAL_DATA,
                         enrollment_id: Optional[str] = None,
                         headers: Optional[Dict[str, str]] = None,
                         expected_enrollment_version: Optional[int] = None,
                         **overrides: Any) -> Dict[str, Any]:
        """Propose a baseline against the enrollment's current version."""
        version = (expected_enrollment_version if expected_enrollment_version is not None
                   else self.enrollment_version)
        self.baseline = get_success_data(
            self.api.propose_baseline(
                enrollment_id or self.enrollment_id,
                f.baseline_payload(version, method, **overrides),
                headers or ADMIN_BASELINE_HEADERS,
            )
        )
        return self.baseline

    def approve_baseline(self, baseline_id: Optional[str] = None,
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Approve a proposed baseline, activating the commitment."""
        approved = get_success_data(
            self.api.approve_baseline(
                baseline_id or self.baseline_id, None, headers or ADMIN_BASELINE_HEADERS
            )
        )
        if self.baseline is not None and approved["id"] == self.baseline["id"]:
            self.baseline = approved
        return approved

    def baselines_of_enrollment(self, enrollment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The baselines of one enrollment, the only channel to superseded rows."""
        data, _meta = validate_paginated(
            self.api.list_baselines(
                {"enrollment_id": enrollment_id or self.enrollment_id}, ADMIN_HEADERS
            )
        )
        return data

    # ── data packets ─────────────────────────────────────────────────────
    def file_packet(self, crop_year: int = CROP_YEAR_2026,
                    enrollment_id: Optional[str] = None,
                    headers: Optional[Dict[str, str]] = None,
                    **overrides: Any) -> Dict[str, Any]:
        """File one crop year of observations against the enrollment."""
        packet = get_success_data(
            self.api.file_data_packet(
                enrollment_id or self.enrollment_id,
                f.data_packet_payload(crop_year, **overrides),
                headers or ADMIN_HEADERS,
            )
        )
        self.packets.append(packet)
        return packet

    def qc_packet(self, packet_id: str, decision: str = "PASS",
                  headers: Optional[Dict[str, str]] = None,
                  **overrides: Any) -> Dict[str, Any]:
        """Run quality control on a packet."""
        return get_success_data(
            self.api.qc_data_packet(
                packet_id, f.qc_payload(decision, **overrides), headers or ADMIN_HEADERS
            )
        )

    def passed_packet(self, crop_year: int = CROP_YEAR_2026, **overrides: Any) -> Dict[str, Any]:
        """File a packet and take it through quality control to passed."""
        packet = self.file_packet(crop_year, **overrides)
        return self.qc_packet(packet["id"], "PASS")

    # ── quantification ───────────────────────────────────────────────────
    def create_run(self, method: str = METHOD_MODEL, crop_year: int = CROP_YEAR_2026,
                   baseline_id: Optional[str] = None,
                   enrollment_id: Optional[str] = None,
                   expected_enrollment_version: Optional[int] = None,
                   headers: Optional[Dict[str, str]] = None,
                   **overrides: Any) -> Dict[str, Any]:
        """Open a draft quantification run against the enrollment's version."""
        version = (expected_enrollment_version if expected_enrollment_version is not None
                   else self.enrollment_version)
        self.run = get_success_data(
            self.api.create_quantification_run(
                f.quantification_run_payload(
                    enrollment_id or self.enrollment_id,
                    baseline_id or self.baseline_id,
                    version,
                    crop_year,
                    method,
                    **overrides
                ),
                headers or ADMIN_HEADERS,
            )
        )
        return self.run

    def submit_run(self, run_id: Optional[str] = None,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Freeze a draft run and submit it for verification."""
        submitted = get_success_data(
            self.api.submit_quantification_run(
                run_id or self.run_id, None, headers or ADMIN_HEADERS
            )
        )
        if self.run is not None and submitted["id"] == self.run["id"]:
            self.run = submitted
        return submitted

    def reload_run(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Re-read a quantification run."""
        self.run = get_success_data(
            self.api.get_quantification_run(run_id or self.run_id, ADMIN_HEADERS)
        )
        return self.run

    # ── verification ─────────────────────────────────────────────────────
    def accredit_body(self, **overrides: Any) -> Dict[str, Any]:
        """Accredit a verification body and remember it."""
        self.body = get_success_data(
            self.api.create_verification_body(
                f.verification_body_payload(**overrides), ADMIN_HEADERS
            )
        )
        return self.body

    def commission_verification(self, run_id: Optional[str] = None,
                                body_id: Optional[str] = None,
                                headers: Optional[Dict[str, str]] = None,
                                **overrides: Any) -> Dict[str, Any]:
        """Commission a verification of a submitted run."""
        self.verification = get_success_data(
            self.api.create_verification(
                f.verification_payload(
                    run_id or self.run_id, body_id or self.body_id, **overrides
                ),
                headers or ADMIN_HEADERS,
            )
        )
        return self.verification

    def opine(self, opinion: str = OPINION_POSITIVE, verification_id: Optional[str] = None,
              headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        """Issue a verification opinion as the assigned body."""
        opined = get_success_data(
            self.api.opine_verification(
                verification_id or self.verification_id,
                f.opinion_payload(opinion, **overrides),
                headers or self.verifier_auth,
            )
        )
        if self.verification is not None and opined["id"] == self.verification["id"]:
            self.verification = opined
        return opined

    def accrue_payment(self, crop_year: int = CROP_YEAR_2026,
                       enrollment_id: Optional[str] = None,
                       headers: Optional[Dict[str, str]] = None,
                       **overrides: Any) -> Dict[str, Any]:
        """Accrue the per-acre annual incentive for one crop year."""
        return get_success_data(
            self.api.accrue_payment(
                enrollment_id or self.enrollment_id,
                f.accrual_payload(crop_year, **overrides),
                headers or ADMIN_HEADERS,
            )
        )

    # ── issuance, registry and discovery ─────────────────────────────────
    def issue(self, run_id: Optional[str] = None, vintage_year: int = CROP_YEAR_2026,
              headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
        """Mint a credit batch from a verified run and discover the batch."""
        get_success_data(
            self.api.issue_credits(
                run_id or self.run_id,
                f.issue_payload(vintage_year, **overrides),
                headers or ADMIN_HEADERS,
            )
        )
        batches = self.batches_of_run(run_id or self.run_id)
        assert batches, "issuance minted no discoverable credit batch"
        self.batch = batches[-1]
        return self.batch

    def batches_of_run(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The batches minted from one run, discovered through the filtered list."""
        data, _meta = validate_paginated(
            self.api.list_credit_batches(
                {"quantification_run_id": run_id or self.run_id}, ADMIN_HEADERS
            )
        )
        return data

    def batches_of_enrollment(self, enrollment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The batches of one enrollment, oldest first."""
        data, _meta = validate_paginated(
            self.api.list_credit_batches(
                {"enrollment_id": enrollment_id or self.enrollment_id}, ADMIN_HEADERS
            )
        )
        return data

    def reload_batch(self, batch_id: Optional[str] = None) -> Dict[str, Any]:
        """Re-read a credit batch, refreshing its stored version."""
        self.batch = get_success_data(
            self.api.get_credit_batch(batch_id or self.batch_id, ADMIN_HEADERS)
        )
        return self.batch

    @property
    def batch_version(self) -> int:
        """The batch's version as last observed."""
        return self.reload_batch()["version"]

    def list_batch(self, batch_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
        """Place a batch on the public registry as the registry custodian."""
        listed = get_success_data(
            self.api.list_batch_on_registry(
                batch_id or self.batch_id, f.registry_listing_payload(**overrides),
                REGISTRY_HEADERS,
            )
        )
        if self.batch is not None and listed["id"] == self.batch["id"]:
            self.batch = listed
        return listed

    def payments_of_enrollment(self, enrollment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The payments of one enrollment, the only channel to accrued rows."""
        data, _meta = validate_paginated(
            self.api.list_grower_payments(
                {"enrollment_id": enrollment_id or self.enrollment_id}, ADMIN_HEADERS
            )
        )
        return data

    def payments_of_batch(self, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The payments accrued against one credit batch."""
        data, _meta = validate_paginated(
            self.api.list_grower_payments(
                {"credit_batch_id": batch_id or self.batch_id}, ADMIN_HEADERS
            )
        )
        return data

    def reversals_of_batch(self, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The reversal events reported against one batch."""
        data, _meta = validate_paginated(
            self.api.list_reversal_events(
                {"credit_batch_id": batch_id or self.batch_id}, ADMIN_HEADERS
            )
        )
        return data

    def buffer_pool(self) -> Dict[str, Any]:
        """The single programme buffer pool, discovered by its pool code."""
        data, _meta = validate_paginated(
            self.api.list_buffer_accounts({"pool_code": POOL_CODE_PROGRAM_BUFFER}, ADMIN_HEADERS)
        )
        assert data, "the programme buffer pool was not seeded"
        return data[0]

    def reload_grower(self, grower_id: Optional[str] = None) -> Dict[str, Any]:
        """Re-read the grower, refreshing its running aggregates."""
        self.grower = get_success_data(
            self.api.get_grower(grower_id or self.grower_id, ADMIN_HEADERS)
        )
        return self.grower

    def reload_field(self, field_id: Optional[str] = None) -> Dict[str, Any]:
        """Re-read a field."""
        return get_success_data(self.api.get_field(field_id or self.field_id, ADMIN_HEADERS))

    # ── composite scenarios ──────────────────────────────────────────────
    def accepted_enrollment(self, clock: str = CLOCK_2026,
                            standard_overrides: Optional[Dict[str, Any]] = None,
                            field_overrides: Optional[Dict[str, Any]] = None,
                            enrollment_overrides: Optional[Dict[str, Any]] = None,
                            per_acre: bool = False,
                            file_history: bool = True,
                            history_adopted_acres: Optional[Any] = None) -> Dict[str, Any]:
        """Clock, methodology, grower, surveyed field, evidence base, accepted enrollment."""
        self.set_clock(clock)
        self.publish_standard(**(standard_overrides or {}))
        self.create_grower()
        self.mapped_field(**(field_overrides or {}))
        if file_history and history_adopted_acres is not None:
            self.file_scaled_history(*history_adopted_acres)
        elif file_history:
            self.file_reference_history()
        if per_acre:
            self.create_per_acre_enrollment(**(enrollment_overrides or {}))
        else:
            self.create_enrollment(**(enrollment_overrides or {}))
        self.submit_enrollment()
        return self.screen_enrollment("ACCEPT")

    def active_enrollment(self, baseline_method: str = BASELINE_HISTORICAL_DATA,
                          **kwargs: Any) -> Dict[str, Any]:
        """An accepted enrollment carried through baseline approval to active."""
        self.accepted_enrollment(**kwargs)
        self.propose_baseline(baseline_method)
        self.approve_baseline()
        return self.reload_enrollment()

    def verified_run(self, run_method: str = METHOD_MODEL,
                     baseline_method: str = BASELINE_HISTORICAL_DATA,
                     packet_overrides: Optional[Dict[str, Any]] = None,
                     verification_overrides: Optional[Dict[str, Any]] = None,
                     opinion_overrides: Optional[Dict[str, Any]] = None,
                     **kwargs: Any) -> Dict[str, Any]:
        """An active enrollment with one quality-passed packet, verified positively."""
        self.active_enrollment(baseline_method=baseline_method, **kwargs)
        self.passed_packet(**(packet_overrides or {}))
        self.create_run(run_method)
        self.submit_run()
        self.accredit_body()
        self.commission_verification(**(verification_overrides or {}))
        self.opine(OPINION_POSITIVE, **(opinion_overrides or {}))
        return self.reload_run()

    def issued_batch(self, **kwargs: Any) -> Dict[str, Any]:
        """A verified run carried through issuance to a minted credit batch."""
        self.verified_run(**kwargs)
        return self.issue()

    def additional_active_enrollment(
        self,
        field_overrides: Optional[Dict[str, Any]] = None,
        enrollment_overrides: Optional[Dict[str, Any]] = None,
        baseline_method: str = BASELINE_HISTORICAL_DATA,
    ):
        """A second surveyed field, evidence base and active enrollment for the same grower.

        The default rectangle sits immediately east of the reference field, sharing one
        edge, which the boundary rule permits.
        """
        overrides = {
            "field_name": "East Quarter",
            "boundary_min_x": 2000,
            "boundary_min_y": 0,
            "boundary_max_x": 4000,
            "boundary_max_y": 2000,
            "gross_acres": 1005.00,
        }
        overrides.update(field_overrides or {})
        field = self.register_field(**overrides)
        self.map_confirm(field["id"])
        self.file_reference_history(field["id"])
        enrollment = get_success_data(
            self.api.create_enrollment(
                f.enrollment_payload(field["id"], self.standard_id,
                                     **(enrollment_overrides or {})),
                ADMIN_HEADERS,
            )
        )
        self.submit_enrollment(enrollment["id"])
        self.screen_enrollment("ACCEPT", enrollment["id"])
        baseline = self.propose_baseline(
            baseline_method,
            enrollment_id=enrollment["id"],
            expected_enrollment_version=self.reload_enrollment(enrollment["id"])["version"],
        )
        self.approve_baseline(baseline["id"])
        return self.reload_enrollment(enrollment["id"]), baseline, field

    def listed_batch(self, **kwargs: Any) -> Dict[str, Any]:
        """An issued batch placed on the public registry."""
        self.issued_batch(**kwargs)
        return self.list_batch()


def new_scenario(api: ApiClient) -> Scenario:
    """A fresh scenario handle over one API client."""
    return Scenario(api)
