"""Error catalog for the Battery Pack Assembly & UN38.3 Compliance API.
Every error id and HTTP status below is taken verbatim from PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Auth ---
def err_missing_user_context(msg="X-User-ID or X-User-Role missing or malformed"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_insufficient_permissions(msg="Role not permitted for this operation"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


# --- Not found ---
def err_program_not_found(msg="IntegrationProgram not found"):
    return ApiError("ERR_PROGRAM_NOT_FOUND", 404, msg)


def err_lot_not_found(msg="CellLot not found"):
    return ApiError("ERR_LOT_NOT_FOUND", 404, msg)


def err_bom_not_found(msg="PackBOM not found"):
    return ApiError("ERR_BOM_NOT_FOUND", 404, msg)


def err_pack_not_found(msg="BatteryPack not found"):
    return ApiError("ERR_PACK_NOT_FOUND", 404, msg)


def err_weld_record_not_found(msg="WeldingParameterRecord not found"):
    return ApiError("ERR_WELD_RECORD_NOT_FOUND", 404, msg)


def err_firmware_not_found(msg="BMSFirmware not found"):
    return ApiError("ERR_FIRMWARE_NOT_FOUND", 404, msg)


def err_dossier_not_found(msg="SafetyTestDossier not found"):
    return ApiError("ERR_DOSSIER_NOT_FOUND", 404, msg)


def err_location_not_found(msg="StorageLocation not found"):
    return ApiError("ERR_LOCATION_NOT_FOUND", 404, msg)


def err_placement_not_found(msg="StoragePlacement not found"):
    return ApiError("ERR_PLACEMENT_NOT_FOUND", 404, msg)


def err_shipment_not_found(msg="TransportShipment not found"):
    return ApiError("ERR_SHIPMENT_NOT_FOUND", 404, msg)


def err_rma_not_found(msg="ReturnAuthorization not found"):
    return ApiError("ERR_RMA_NOT_FOUND", 404, msg)


def err_recall_not_found(msg="RecallCampaign not found"):
    return ApiError("ERR_RECALL_NOT_FOUND", 404, msg)


def err_not_found(msg="Referenced resource does not exist"):
    # fallback for event-record flat gets that have no dedicated catalog id
    return ApiError("ERR_NOT_FOUND", 404, msg)


# --- Generic request ---
def err_invalid_request(msg="Malformed request, missing required fields, or type mismatch"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_enum(msg="Enum field contains a value outside its declared set"):
    return ApiError("ERR_INVALID_ENUM", 400, msg)


# --- Program state ---
def err_program_not_open(msg="Operation requires program OPEN"):
    return ApiError("ERR_PROGRAM_NOT_OPEN", 409, msg)


def err_program_not_suspended(msg="Resume requires program SUSPENDED"):
    return ApiError("ERR_PROGRAM_NOT_SUSPENDED", 409, msg)


def err_unresolved_packs(msg="Program close blocked by non-terminal packs"):
    return ApiError("ERR_UNRESOLVED_PACKS_REMAIN", 409, msg)


def err_open_shipments(msg="Program close blocked by open shipments"):
    return ApiError("ERR_OPEN_SHIPMENTS_REMAIN", 409, msg)


def err_active_recall_exists(msg="Program close blocked by an ACTIVE recall"):
    return ApiError("ERR_ACTIVE_RECALL_EXISTS", 409, msg)


# --- Cell lot ---
def err_lot_not_received(msg="Quarantine transition requires lot RECEIVED"):
    return ApiError("ERR_LOT_NOT_RECEIVED", 409, msg)


def err_lot_not_in_quarantine(msg="Inspection requires lot QUARANTINE"):
    return ApiError("ERR_LOT_NOT_IN_QUARANTINE", 409, msg)


def err_lot_not_rejected(msg="Retest requires lot REJECTED"):
    return ApiError("ERR_LOT_NOT_REJECTED", 409, msg)


def err_lot_not_accepted(msg="PackBOM creation requires ACCEPTED lot"):
    return ApiError("ERR_LOT_NOT_ACCEPTED", 409, msg)


def err_lot_depleted(msg="Lot has no remaining cells"):
    return ApiError("ERR_LOT_DEPLETED", 409, msg)


def err_inspection_not_pass(msg="Acceptance requires outcome=PASS"):
    return ApiError("ERR_INSPECTION_NOT_PASS", 409, msg)


def err_soc_out_of_tolerance(msg="Measured SOC deviates from declared by more than ±2.0 percent"):
    return ApiError("ERR_SOC_OUT_OF_TOLERANCE", 422, msg)


def err_retest_limit(msg="quarantine_cycle_count >= 2"):
    return ApiError("ERR_RETEST_LIMIT_EXCEEDED", 409, msg)


# --- Pack / BOM ---
def err_pack_not_built(msg="Weld record requires pack BUILT"):
    return ApiError("ERR_PACK_NOT_BUILT", 409, msg)


def err_pack_not_weld_recorded(msg="Certify requires pack WELD_RECORDED"):
    return ApiError("ERR_PACK_NOT_WELD_RECORDED", 409, msg)


def err_pack_not_weld_certified(msg="BMS flash requires pack WELD_CERTIFIED"):
    return ApiError("ERR_PACK_NOT_WELD_CERTIFIED", 409, msg)


def err_pack_not_bms_flashed(msg="Dossier open requires pack BMS_FLASHED or TEST_QUEUED (retest)"):
    return ApiError("ERR_PACK_NOT_BMS_FLASHED", 409, msg)


def err_pack_not_test_queued(msg="Submit requires pack TEST_QUEUED"):
    return ApiError("ERR_PACK_NOT_TEST_QUEUED", 409, msg)


def err_pack_not_classified(msg="Approve requires pack CLASSIFIED"):
    return ApiError("ERR_PACK_NOT_CLASSIFIED", 409, msg)


def err_pack_not_ready_to_store(msg="Storage placement requires pack READY_TO_STORE"):
    return ApiError("ERR_PACK_NOT_READY_TO_STORE", 409, msg)


def err_pack_already_stored(msg="Pack already has an active placement"):
    return ApiError("ERR_PACK_ALREADY_STORED", 409, msg)


def err_pack_not_stored(msg="Pick requires logistics_status STORED"):
    return ApiError("ERR_PACK_NOT_STORED", 409, msg)


def err_pack_not_picked(msg="Attach requires logistics_status PICKED"):
    return ApiError("ERR_PACK_NOT_PICKED", 409, msg)


def err_pack_already_attached(msg="Pack already attached to a non-terminal shipment"):
    return ApiError("ERR_PACK_ALREADY_ATTACHED", 409, msg)


def err_pack_not_delivered(msg="RMA approve requires pack DELIVERED"):
    return ApiError("ERR_PACK_NOT_DELIVERED", 409, msg)


def err_pack_under_recall(msg="Operation blocked: pack captured by an ACTIVE recall"):
    return ApiError("ERR_PACK_UNDER_RECALL", 409, msg)


def err_weld_already_certified(msg="Weld record already certified"):
    return ApiError("ERR_WELD_ALREADY_CERTIFIED", 409, msg)


def err_weld_profile_mismatch(msg="Record profile does not match PackBOM.welding_profile"):
    return ApiError("ERR_WELD_PROFILE_MISMATCH", 422, msg)


def err_heat_dose_exceeded(msg="Computed heat dose exceeds profile ceiling"):
    return ApiError("ERR_HEAT_DOSE_EXCEEDED", 422, msg)


# --- Firmware ---
def err_firmware_not_draft(msg="submit-review requires DRAFT (or DEPRECATED via re-cert path)"):
    return ApiError("ERR_FIRMWARE_NOT_DRAFT", 409, msg)


def err_firmware_not_pending_review(msg="Approval requires PENDING_REVIEW"):
    return ApiError("ERR_FIRMWARE_NOT_PENDING_REVIEW", 409, msg)


def err_firmware_not_approved(msg="Flash or deprecate requires APPROVED"):
    return ApiError("ERR_FIRMWARE_NOT_APPROVED", 409, msg)


def err_firmware_not_deprecated(msg="Re-submit review requires DEPRECATED"):
    return ApiError("ERR_FIRMWARE_NOT_DEPRECATED", 409, msg)


def err_firmware_in_use(msg="Deprecate blocked: firmware referenced by a non-terminal pack"):
    return ApiError("ERR_FIRMWARE_IN_USE", 409, msg)


# --- Dossier ---
def err_dossier_already_open(msg="A non-terminal dossier already exists for this pack"):
    return ApiError("ERR_DOSSIER_ALREADY_OPEN", 409, msg)


def err_dossier_not_open(msg="PUT matrix requires dossier OPEN"):
    return ApiError("ERR_DOSSIER_NOT_OPEN", 409, msg)


def err_dossier_not_tests_recorded(msg="Submit requires dossier TESTS_RECORDED"):
    return ApiError("ERR_DOSSIER_NOT_TESTS_RECORDED", 409, msg)


def err_dossier_not_submitted(msg="Approve requires dossier SUBMITTED"):
    return ApiError("ERR_DOSSIER_NOT_SUBMITTED", 409, msg)


def err_dossier_not_pass(msg="Approve requires outcome=PASS"):
    return ApiError("ERR_DOSSIER_NOT_PASS", 409, msg)


def err_incomplete_test_matrix(msg="All eight T1..T8 fields must be non-null"):
    return ApiError("ERR_INCOMPLETE_TEST_MATRIX", 422, msg)


# --- Storage ---
def err_placement_not_staged(msg="Store/release transition requires placement STAGED or STORED"):
    return ApiError("ERR_PLACEMENT_NOT_STAGED", 409, msg)


def err_soc_band_not_accepted(msg="Pack soc_band not in location.accepts_soc_band"):
    return ApiError("ERR_SOC_BAND_NOT_ACCEPTED", 422, msg)


def err_location_capacity(msg="Placement would exceed location.capacity_wh"):
    return ApiError("ERR_LOCATION_CAPACITY_EXCEEDED", 422, msg)


def err_program_capacity(msg="Placement would exceed program.storage_capacity_wh"):
    return ApiError("ERR_PROGRAM_CAPACITY_EXCEEDED", 422, msg)


# --- Shipment ---
def err_shipment_not_draft(msg="Operation requires shipment DRAFT"):
    return ApiError("ERR_SHIPMENT_NOT_DRAFT", 409, msg)


def err_shipment_empty(msg="Tender requires total_pack_count > 0"):
    return ApiError("ERR_SHIPMENT_EMPTY", 422, msg)


def err_shipment_not_tendered(msg="Carrier decision requires TENDERED"):
    return ApiError("ERR_SHIPMENT_NOT_TENDERED", 409, msg)


def err_shipment_not_carrier_accepted(msg="mark-in-transit requires CARRIER_ACCEPTED"):
    return ApiError("ERR_SHIPMENT_NOT_CARRIER_ACCEPTED", 409, msg)


def err_shipment_not_in_transit(msg="mark-delivered requires IN_TRANSIT"):
    return ApiError("ERR_SHIPMENT_NOT_IN_TRANSIT", 409, msg)


def err_un_class_mismatch(msg="Pack shipping_classification does not match shipment.un_class_code"):
    return ApiError("ERR_UN_CLASS_MISMATCH", 422, msg)


# --- RMA ---
def err_rma_not_requested(msg="Approve/deny requires RMA REQUESTED"):
    return ApiError("ERR_RMA_NOT_REQUESTED", 409, msg)


def err_rma_not_approved(msg="begin-discharge requires APPROVED"):
    return ApiError("ERR_RMA_NOT_APPROVED", 409, msg)


def err_rma_not_discharge_pending(msg="complete-discharge requires DISCHARGE_PENDING"):
    return ApiError("ERR_RMA_NOT_DISCHARGE_PENDING", 409, msg)


def err_rma_not_discharged(msg="receive requires DISCHARGED"):
    return ApiError("ERR_RMA_NOT_DISCHARGED", 409, msg)


def err_rma_not_received(msg="close requires RECEIVED"):
    return ApiError("ERR_RMA_NOT_RECEIVED", 409, msg)


def err_rma_pack_mismatch(msg="RMA references a different pack than the one being received"):
    return ApiError("ERR_RMA_PACK_MISMATCH", 409, msg)


def err_target_soc_too_high(msg="target_soc_percent > SAFE_DISCHARGE_MAX_PERCENT (30.0)"):
    return ApiError("ERR_TARGET_SOC_TOO_HIGH", 422, msg)


def err_discharge_target_not_met(msg="final_soc_percent > target_soc_percent"):
    return ApiError("ERR_DISCHARGE_TARGET_NOT_MET", 422, msg)


# --- Recall ---
def err_recall_not_draft(msg="Activate requires DRAFT"):
    return ApiError("ERR_RECALL_NOT_DRAFT", 409, msg)


def err_recall_not_active(msg="mark-contained requires ACTIVE"):
    return ApiError("ERR_RECALL_NOT_ACTIVE", 409, msg)


def err_recall_not_contained(msg="close requires CONTAINED"):
    return ApiError("ERR_RECALL_NOT_CONTAINED", 409, msg)


def err_recall_scope_empty(msg="At least one scope_* selector must be set"):
    return ApiError("ERR_RECALL_SCOPE_EMPTY", 422, msg)


def err_recall_not_fully_contained(msg="packs_contained < packs_in_scope"):
    return ApiError("ERR_RECALL_NOT_FULLY_CONTAINED", 409, msg)


# --- Segregation of duties ---
def err_sod_weld_certify(msg="Certifier must differ from weld operator"):
    return ApiError("ERR_SOD_WELD_CERTIFY", 403, msg)


def err_sod_firmware_approve(msg="Approver must differ from firmware submitter"):
    return ApiError("ERR_SOD_FIRMWARE_APPROVE", 403, msg)


def err_sod_rma_approve(msg="RMA approver must differ from RMA requester"):
    return ApiError("ERR_SOD_RMA_APPROVE", 403, msg)


# --- Referential ---
def err_cross_program(msg="Referenced resource belongs to a different program"):
    return ApiError("ERR_CROSS_PROGRAM_REFERENCE", 422, msg)


# --- OCC ---
def err_stale_version(msg="expected_<parent>_version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
