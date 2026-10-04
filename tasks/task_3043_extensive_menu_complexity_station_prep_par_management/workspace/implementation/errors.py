class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Convenience constructors
def err_missing_user_context():
    return ApiError(
        "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
        400,
        "X-User-ID and X-User-Role headers must be present and non-empty",
    )


def err_invalid_request(msg="Request body failed validation"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_forbidden():
    return ApiError("ERR_FORBIDDEN", 403, "Role is not authorized for this endpoint")


NOT_FOUND = {
    "restaurant": ("ERR_RESTAURANT_NOT_FOUND", "Restaurant id does not exist"),
    "menu_revision": ("ERR_MENU_REVISION_NOT_FOUND", "MenuRevision id does not exist"),
    "recipe": ("ERR_RECIPE_NOT_FOUND", "Recipe id does not exist"),
    "prep_item": ("ERR_PREP_ITEM_NOT_FOUND", "PrepItem id does not exist"),
    "station": ("ERR_STATION_NOT_FOUND", "Station id does not exist"),
    "station_par": ("ERR_STATION_PAR_NOT_FOUND", "StationPar id does not exist"),
    "cook": ("ERR_COOK_NOT_FOUND", "Cook id does not exist"),
    "demand_forecast": ("ERR_DEMAND_FORECAST_NOT_FOUND", "DemandForecast id does not exist"),
    "prep_list": ("ERR_PREP_LIST_NOT_FOUND", "PrepList id does not exist"),
    "prep_batch": ("ERR_PREP_BATCH_NOT_FOUND", "PrepBatch id does not exist"),
    "shift_assignment": ("ERR_SHIFT_ASSIGNMENT_NOT_FOUND", "ShiftAssignment id does not exist"),
    "bakery_order": ("ERR_BAKERY_ORDER_NOT_FOUND", "BakeryOrder id does not exist"),
    "waste_entry": ("ERR_WASTE_ENTRY_NOT_FOUND", "WasteEntry id does not exist"),
    "service_ticket": ("ERR_SERVICE_TICKET_NOT_FOUND", "ServiceTicket id does not exist"),
}


def err_not_found(kind):
    eid, msg = NOT_FOUND[kind]
    return ApiError(eid, 404, msg)
