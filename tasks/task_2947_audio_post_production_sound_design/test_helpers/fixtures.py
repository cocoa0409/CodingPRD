"""Composite setup helpers and pytest fixtures.

The harness restarts the service before every test, so each fixture builds its
preconditions from scratch through the public endpoints. :class:`World` bundles
the multi-step chains — a locked project, a conformed stem package, a completed
stage session, a prepared deliverable — that the scenarios below reuse.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import QC_ONE_USER_ID, QC_TWO_USER_ID
from .test_users import (
    ADMIN_HEADERS,
    CLIENT_HEADERS,
    EDITOR_HEADERS,
    QC_ONE_HEADERS,
    QC_TWO_HEADERS,
    SUPERVISOR_HEADERS,
    mixer_headers,
    qc_headers,
)


class World:
    """Builds facility configuration and project state through the API."""

    def __init__(self, api: ApiClient):
        self.api = api

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc):
        return get_success_data(
            self.api.set_clock(f.clock_payload(current_utc=current_utc), ADMIN_HEADERS)
        )["current_utc"]

    def clock(self):
        return get_success_data(self.api.get_clock(ADMIN_HEADERS))["current_utc"]

    # ------------------------------------------------------------------
    # Facility configuration
    # ------------------------------------------------------------------

    def platform_spec(self, **overrides):
        return get_success_data(
            self.api.create_platform_spec(f.platform_spec_payload(**overrides), ADMIN_HEADERS)
        )

    def mix_stage(self, **overrides):
        return get_success_data(
            self.api.create_mix_stage(f.mix_stage_payload(**overrides), ADMIN_HEADERS)
        )

    def mixer(self, **overrides):
        return get_success_data(self.api.create_mixer(f.mixer_payload(**overrides), ADMIN_HEADERS))

    def voice_talent(self, **overrides):
        return get_success_data(
            self.api.create_voice_talent(f.voice_talent_payload(**overrides), ADMIN_HEADERS)
        )

    def library_asset(self, **overrides):
        return get_success_data(
            self.api.create_library_asset(f.library_asset_payload(**overrides), ADMIN_HEADERS)
        )

    def revoke_asset(self, asset_id, **overrides):
        return get_success_data(
            self.api.revoke_library_asset(asset_id, f.revoke_payload(**overrides), ADMIN_HEADERS)
        )

    def get_asset(self, asset_id):
        return get_success_data(self.api.get_library_asset(asset_id, ADMIN_HEADERS))

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def project(self, **overrides):
        return get_success_data(
            self.api.create_project(f.project_payload(**overrides), SUPERVISOR_HEADERS)
        )

    def get_project(self, project_id):
        return get_success_data(self.api.get_project(project_id, SUPERVISOR_HEADERS))

    def project_version(self, project_id):
        return self.get_project(project_id)["version"]

    def ledger(self, project_id):
        return get_success_data(self.api.get_project_ledger(project_id, SUPERVISOR_HEADERS))

    def lock_picture(self, project_id, **overrides):
        return get_success_data(
            self.api.picture_lock(project_id, f.picture_lock_payload(**overrides), SUPERVISOR_HEADERS)
        )

    def break_lock(self, project_id, **overrides):
        return get_success_data(
            self.api.break_picture_lock(
                project_id, f.break_picture_lock_payload(**overrides), SUPERVISOR_HEADERS
            )
        )

    def locked_project(self, **overrides):
        project = self.project(**overrides)
        self.lock_picture(project["id"])
        return self.get_project(project["id"])

    def archive(self, project_id, **overrides):
        return get_success_data(
            self.api.create_archive_package(
                project_id, f.archive_package_payload(**overrides), SUPERVISOR_HEADERS
            )
        )

    # ------------------------------------------------------------------
    # Editorial
    # ------------------------------------------------------------------

    def stem_package(self, project_id, **overrides):
        return get_success_data(
            self.api.create_stem_package(
                f.stem_package_payload(project_id, **overrides), EDITOR_HEADERS
            )
        )

    def get_stem_package(self, stem_package_id):
        return get_success_data(self.api.get_stem_package(stem_package_id, EDITOR_HEADERS))

    def add_cue(self, stem_package_id, **overrides):
        version = self.get_stem_package(stem_package_id)["version"]
        return get_success_data(
            self.api.create_music_cue(
                stem_package_id, f.music_cue_payload(version, **overrides), EDITOR_HEADERS
            )
        )

    def conform(self, stem_package_id):
        return get_success_data(
            self.api.conform_stem_package(stem_package_id, {}, EDITOR_HEADERS)
        )

    def conformed_package(self, project_id, cue_durations=(120,), **overrides):
        package = self.stem_package(project_id, **overrides)
        for index, duration in enumerate(cue_durations, start=1):
            self.add_cue(package["id"], cue_number=f"1M{index}", duration_seconds=duration)
        return self.conform(package["id"])

    def asset_usage(self, library_asset_id, stem_package_id, **overrides):
        return get_success_data(
            self.api.create_asset_usage(
                f.asset_usage_payload(library_asset_id, stem_package_id, **overrides),
                EDITOR_HEADERS,
            )
        )

    def get_usage(self, usage_id):
        return get_success_data(self.api.get_asset_usage(usage_id, EDITOR_HEADERS))

    # ------------------------------------------------------------------
    # ADR
    # ------------------------------------------------------------------

    def adr_session(self, project_id, voice_talent_id, **overrides):
        return get_success_data(
            self.api.create_adr_session(
                f.adr_session_payload(project_id, voice_talent_id, **overrides), EDITOR_HEADERS
            )
        )

    def confirm_adr(self, session_id):
        return get_success_data(self.api.confirm_adr_session(session_id, {}, EDITOR_HEADERS))

    def record_adr(self, session_id, **overrides):
        return get_success_data(
            self.api.record_adr_session(session_id, f.adr_record_payload(**overrides), EDITOR_HEADERS)
        )

    def cancel_adr(self, session_id, **overrides):
        return get_success_data(
            self.api.cancel_adr_session(session_id, f.adr_cancel_payload(**overrides), SUPERVISOR_HEADERS)
        )

    def get_adr(self, session_id):
        return get_success_data(self.api.get_adr_session(session_id, EDITOR_HEADERS))

    # ------------------------------------------------------------------
    # Mix stage bookings
    # ------------------------------------------------------------------

    def booking(self, project_id, mix_stage_id, mixer_id, **overrides):
        version = self.project_version(project_id)
        return get_success_data(
            self.api.create_mix_booking(
                f.mix_booking_payload(version, project_id, mix_stage_id, mixer_id, **overrides),
                SUPERVISOR_HEADERS,
            )
        )

    def get_booking(self, booking_id):
        return get_success_data(self.api.get_mix_booking(booking_id, SUPERVISOR_HEADERS))

    def confirm_booking(self, booking_id, mixer_id):
        return get_success_data(
            self.api.confirm_mix_booking(booking_id, {}, mixer_headers(mixer_id))
        )

    def start_booking(self, booking_id, mixer_id):
        return get_success_data(self.api.start_mix_booking(booking_id, {}, mixer_headers(mixer_id)))

    def complete_booking(self, booking_id, mixer_id):
        return get_success_data(
            self.api.complete_mix_booking(booking_id, {}, mixer_headers(mixer_id))
        )

    def release_booking(self, booking_id, **overrides):
        return get_success_data(
            self.api.release_mix_booking(booking_id, f.release_payload(**overrides), SUPERVISOR_HEADERS)
        )

    def client_signoff(self, booking_id, headers=None):
        return get_success_data(
            self.api.client_signoff_mix_booking(booking_id, {}, headers or CLIENT_HEADERS)
        )

    def completed_booking(
        self,
        project_id,
        mix_stage_id,
        mixer_id,
        window_start_utc="2026-09-14T10:00:00Z",
        window_end_utc="2026-09-14T13:00:00Z",
        completed_at=None,
        **overrides,
    ):
        """Reserve, accept, open and close one stage session."""
        booking = self.booking(
            project_id,
            mix_stage_id,
            mixer_id,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            **overrides,
        )
        self.confirm_booking(booking["id"], mixer_id)
        self.set_clock(window_start_utc)
        self.start_booking(booking["id"], mixer_id)
        self.set_clock(completed_at or window_end_utc)
        return self.complete_booking(booking["id"], mixer_id)

    # ------------------------------------------------------------------
    # Deliverables and QC
    # ------------------------------------------------------------------

    def deliverable(self, project_id, platform_spec_id, stem_package_id, mix_booking_id, headers=None):
        version = self.project_version(project_id)
        return get_success_data(
            self.api.create_deliverable(
                f.deliverable_payload(
                    version, project_id, platform_spec_id, stem_package_id, mix_booking_id
                ),
                headers or SUPERVISOR_HEADERS,
            )
        )

    def get_deliverable(self, deliverable_id):
        return get_success_data(self.api.get_deliverable(deliverable_id, SUPERVISOR_HEADERS))

    def qc_submit(self, deliverable_id, submitter=QC_ONE_USER_ID, **measurements):
        return get_success_data(
            self.api.qc_submit(
                deliverable_id, f.qc_submit_payload(**measurements), qc_headers(submitter)
            )
        )

    def qc_evaluate(self, deliverable_id, evaluator=QC_TWO_USER_ID):
        return get_success_data(
            self.api.qc_evaluate(deliverable_id, {}, qc_headers(evaluator)), expected_status=201
        )

    def remediate(self, deliverable_id, **overrides):
        return get_success_data(
            self.api.remediate_deliverable(
                deliverable_id, f.remediate_payload(**overrides), SUPERVISOR_HEADERS
            )
        )

    def deliver(self, deliverable_id, **overrides):
        return get_success_data(
            self.api.deliver_deliverable(
                deliverable_id, f.deliver_payload(**overrides), SUPERVISOR_HEADERS
            )
        )

    def qc_reports(self, deliverable_id):
        return get_success_data(self.api.list_qc_reports(deliverable_id, SUPERVISOR_HEADERS))

    # ------------------------------------------------------------------
    # Whole-pipeline composites
    # ------------------------------------------------------------------

    def prepared_environment(
        self,
        clock_start="2026-09-01T00:00:00Z",
        spec=None,
        stage=None,
        mixer=None,
        project=None,
        cue_durations=(120,),
        window_start_utc="2026-09-14T10:00:00Z",
        window_end_utc="2026-09-14T13:00:00Z",
        platform="THEATRICAL",
        booking_type="FINAL_MIX",
        client_attendance="ONSITE",
        completed_at=None,
        prepare=True,
        prepared_by=None,
    ):
        """Facility, locked project, conformed stems, a closed stage session and
        — unless ``prepare`` is false — a deliverable prepared against them."""
        self.set_clock(clock_start)
        spec_record = self.platform_spec(platform=platform, **(spec or {}))
        stage_record = self.mix_stage(**(stage or {}))
        mixer_record = self.mixer(certified_platforms=[platform], **(mixer or {}))
        project_record = self.locked_project(**(project or {}))
        package = self.conformed_package(project_record["id"], cue_durations=cue_durations)
        booking = self.completed_booking(
            project_record["id"],
            stage_record["id"],
            mixer_record["id"],
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            completed_at=completed_at,
            platform=platform,
            booking_type=booking_type,
            client_attendance=client_attendance,
        )
        environment = {
            "spec": spec_record,
            "stage": stage_record,
            "mixer": mixer_record,
            "project": self.get_project(project_record["id"]),
            "package": self.get_stem_package(package["id"]),
            "booking": booking,
        }
        if prepare:
            environment["deliverable"] = self.deliverable(
                project_record["id"],
                spec_record["id"],
                package["id"],
                booking["id"],
                headers=prepared_by,
            )
        return environment

    def qc_passed_environment(self, **kwargs):
        """A prepared deliverable carried through one passing QC round."""
        environment = self.prepared_environment(**kwargs)
        deliverable = environment["deliverable"]
        spec = environment["spec"]
        self.qc_submit(
            deliverable["id"],
            measured_integrated_lufs=spec["target_lufs"],
            measured_true_peak_dbtp=spec["true_peak_max_dbtp"],
            me_stems_present=True,
        )
        environment["report"] = self.qc_evaluate(deliverable["id"])
        environment["deliverable"] = self.get_deliverable(deliverable["id"])
        return environment

    def delivered_environment(self, **kwargs):
        """A deliverable carried all the way to DELIVERED."""
        environment = self.qc_passed_environment(**kwargs)
        environment["deliverable"] = self.deliver(environment["deliverable"]["id"])
        environment["project"] = self.get_project(environment["project"]["id"])
        return environment


# --------------------------------------------------------------------------
# pytest fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def api():
    """A client pointed at the service under test."""
    return ApiClient()


@pytest.fixture
def world(api):
    """A builder that stands up facility and project state through the API."""
    return World(api)


@pytest.fixture
def theatrical_spec(world):
    return world.platform_spec()


@pytest.fixture
def standard_stage(world):
    return world.mix_stage()


@pytest.fixture
def theatrical_mixer(world):
    return world.mixer()


@pytest.fixture
def union_talent(world):
    return world.voice_talent()


@pytest.fixture
def open_project(world):
    """A freshly taken-in project at INTAKE with picture NOT_LOCKED."""
    return world.project()


@pytest.fixture
def locked_project(world):
    """A project whose picture is LOCKED and which therefore sits at EDITORIAL."""
    return world.locked_project()


@pytest.fixture
def prepared_environment(world):
    """A prepared deliverable over a closed three-hour theatrical session."""
    return world.prepared_environment()


@pytest.fixture
def qc_passed_environment(world):
    """The same environment carried through one passing QC round."""
    return world.qc_passed_environment()


@pytest.fixture
def delivered_environment(world):
    """The same environment carried through to a delivered deliverable."""
    return world.delivered_environment()
