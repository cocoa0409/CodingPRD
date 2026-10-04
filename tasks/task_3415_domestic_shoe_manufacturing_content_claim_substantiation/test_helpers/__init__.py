"""Barrel export: framework generics + PRD-specific helpers."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_allocation, assert_claim, assert_component, assert_contract,
    assert_document, assert_enrollment, assert_factory, assert_lot,
    assert_model, assert_order, assert_report, assert_run, assert_worker,
)
from .constants import (
    ASSEMBLED_IN_USA_MIN_PCT, BERRY_REQUIRED_PCT, CLOCK_START_ISO,
    CLOCK_START_PREFIX, COLORWAY_FEE_CENTS, CUSTOM_BATCH_EXTRA_PCT,
    CUSTOM_FALLBACK_MARKUP, DISCOUNT_TIER_1_MIN_CENTS, DISCOUNT_TIER_1_PCT,
    DISCOUNT_TIER_2_MIN_CENTS, DISCOUNT_TIER_2_PCT, DOC_VALID_FROM,
    DOC_VALID_UNTIL, GOVERNMENT_PCT, MADE_IN_USA_MIN_PCT,
    MADE_IN_USA_OF_IMPORTED_MIN_PCT, MAX_CUSTOM_ORDER_UNITS,
    MONOGRAM_FEE_CENTS, OP_WEIGHTS, PIPELINE_CREDIT,
    REQUIRED_WORKERS_PER_RUN, RUN_END_DAY, RUN_START_DAY, TIER_1_MAX_UNITS,
    TIER_1_PCT, TIER_2_MAX_UNITS, TIER_2_PCT, TIER_3_MAX_UNITS, TIER_3_PCT,
    TRAINING_PASS_SCORE, WEEK_36, WEEK_37, WEEK_38, WEEK_39, WEEK_40,
)
from .factories import (
    DEFAULTS, bom_line, complete_run_payload, create_allocation_payload,
    create_claim_payload, create_component_payload, create_contract_payload,
    create_document_payload, create_enrollment_payload, create_factory_payload,
    create_lot_payload, create_model_payload, create_order_payload,
    create_report_payload, create_run_payload, create_worker_payload,
    record_assessment_payload, shift_allocation_payload,
)
from .fixtures import (
    accept_order, accepted_order, assess, berry_completed_run,
    certify_pair, certify_worker, claim_with_verified_docs, complete_run,
    completed_run_kit, create_report, enroll, get_allocation, get_claim,
    get_contract, get_document, get_lot, get_order, get_run, lock_allocation,
    m70_completed_run, m95_completed_run, make_allocation, make_claim,
    make_component, make_contract, make_factory, make_lot, make_model,
    make_order, make_run, make_verified_document, make_worker, publish,
    release_run, reserve_run, run_version, schedule_order, set_clock,
    standard_kit, start_run, substantiate, substantiated_claim_95,
    published_claim_95, upload_document, verify_document,
)
from .test_users import (
    TEST_USERS, make_admin_headers, make_compliance_headers,
    make_customer_headers, make_factory_manager_headers,
    make_planner_headers, make_sourcing_headers, make_training_headers,
)
from .types import (
    AllocationStatus, BomLine, CapacityAllocation, Certification, CertStatus,
    ClaimStatus, ClaimType, Component, ComponentType, ConsumedLot,
    CustomOrder, DocStatus, DocType, DomesticContentReport, EnrollmentStatus,
    EvidenceDocument, Factory, FactoryStatus, GovContract, ContractStatus,
    LabelClaim, LocationType, MaterialLot, ModelStatus, Operation,
    ProductionPolicy, ProductionRun, ReportStatus, ReportVariant, RunStatus,
    RunType, ShiftDirection, ShoeModel, SourcingRequirement,
    TrainingEnrollment, UserRole, Worker, WorkerStatus, OrderStatus,
)
