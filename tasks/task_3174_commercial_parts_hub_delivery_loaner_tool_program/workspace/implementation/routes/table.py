"""The complete §4 route table."""

from middleware import paginate_and_wrap
from response import as_bool, sort_by_created
from router import Book
from services import handlers as h

BOOK = Book()

READ_ALL = ("CommercialSalesRep", "CreditAnalyst", "RouteDispatcher", "DeliveryDriver",
            "PartsCategoryManager", "Any")

# --- clock -----------------------------------------------------------------
BOOK.add("POST", "/commercial/_clock/set_current_utc", h.set_clock, ["PlatformAdmin"])
BOOK.add("POST", "/commercial/_epoch/advance", h.advance_epoch, ["PlatformAdmin"])

# --- CommercialAccount -----------------------------------------------------
BOOK.add("POST", "/commercial/commercial-accounts", h.create_account, ["CommercialSalesRep"], 201)
BOOK.add("GET", "/commercial/commercial-accounts", h.list_accounts, READ_ALL)
BOOK.add("GET", "/commercial/commercial-accounts/{accountId}", h.get_account, READ_ALL)
BOOK.add("GET", "/commercial/commercial-accounts/{accountId}/part-orders",
         h.list_account_orders, READ_ALL)
BOOK.add("GET", "/commercial/commercial-accounts/{accountId}/tool-loans",
         h.list_account_loans, ("ToolCribAttendant", "CommercialSalesRep", "CreditAnalyst",
                                "DeliveryDriver", "Any"))
BOOK.add("GET", "/commercial/commercial-accounts/{accountId}/core-returns",
         h.list_account_core_returns, ("CommercialSalesRep", "CreditAnalyst",
                                       "ToolCribAttendant", "DeliveryDriver", "Any"))
BOOK.add("GET", "/commercial/commercial-accounts/{accountId}/rep-coverages",
         h.list_account_coverages, READ_ALL)
BOOK.add("GET", "/commercial/commercial-accounts/{accountId}/warranty-registrations",
         h.list_account_warranties, ("CommercialSalesRep", "CreditAnalyst",
                                     "ToolCribAttendant", "DeliveryDriver", "Any"))
BOOK.add("PUT", "/commercial/commercial-accounts/{accountId}", h.update_account,
         ["CommercialSalesRep", "CreditAnalyst"])
BOOK.add("GET", "/commercial/commercial-accounts/{accountId}/posture", h.read_posture, READ_ALL)
BOOK.add("POST", "/commercial/commercial-accounts/{accountId}/hold", h.hold_account,
         ["CreditAnalyst"])
BOOK.add("POST", "/commercial/commercial-accounts/{accountId}/release", h.release_account,
         ["CreditAnalyst"])
BOOK.add("POST", "/commercial/commercial-accounts/{accountId}/restore", h.restore_account,
         ["CreditAnalyst"])
BOOK.add("POST", "/commercial/commercial-accounts/{accountId}/close", h.close_account,
         ["CreditAnalyst"])
BOOK.add("POST", "/commercial/commercial-accounts/{accountId}/archive", h.archive_account,
         ["CreditAnalyst"])

# --- Store -----------------------------------------------------------------
BOOK.add("POST", "/commercial/stores", h.create_store, ["PartsCategoryManager"], 201)
BOOK.add("GET", "/commercial/stores", h.list_stores, READ_ALL)
BOOK.add("GET", "/commercial/stores/{storeId}", h.get_store, READ_ALL)
BOOK.add("GET", "/commercial/stores/{storeId}/child-stores", h.list_child_stores, READ_ALL)
BOOK.add("GET", "/commercial/stores/{storeId}/commercial-accounts", h.list_store_accounts, READ_ALL)
BOOK.add("GET", "/commercial/stores/{storeId}/inventory-items", h.list_store_inventory, READ_ALL)
BOOK.add("POST", "/commercial/stores/{storeId}/archive", h.archive_store, ["PartsCategoryManager"])

# --- InventoryItem ---------------------------------------------------------
BOOK.add("POST", "/commercial/inventory-items", h.create_inventory_item,
         ["PartsCategoryManager"], 201)
BOOK.add("GET", "/commercial/inventory-items", h.list_inventory, READ_ALL)
BOOK.add("GET", "/commercial/inventory-items/{itemId}", h.get_inventory_item, READ_ALL)
BOOK.add("PUT", "/commercial/inventory-items/{itemId}", h.update_inventory_item,
         ["PartsCategoryManager"])
BOOK.add("GET", "/commercial/parts/{partId}/inventory-items", h.list_part_inventory, READ_ALL)

# --- Part / catalogue ------------------------------------------------------
BOOK.add("POST", "/commercial/parts", h.create_part, ["PartsCategoryManager"], 201)
BOOK.add("GET", "/commercial/parts", h.list_parts, READ_ALL)
BOOK.add("GET", "/commercial/parts/current", h.resolve_current_part, READ_ALL)
BOOK.add("GET", "/commercial/parts/fitment-lookup", h.fitment_lookup, READ_ALL)
BOOK.add("GET", "/commercial/parts/{partId}", h.get_part, READ_ALL)
BOOK.add("GET", "/commercial/parts/{partId}/fitments", h.list_part_fitments, READ_ALL)
BOOK.add("POST", "/commercial/parts/{partId}/fitments", h.create_part_fitment,
         ["PartsCategoryManager"], 201)
BOOK.add("GET", "/commercial/parts/{partId}/interchanges", h.list_part_interchanges, READ_ALL)
BOOK.add("POST", "/commercial/parts/{partId}/interchanges", h.create_interchange,
         ["PartsCategoryManager"], 201)
BOOK.add("GET", "/commercial/parts/{partId}/tool-fitments", h.list_part_tool_fitments,
         ("PartsCategoryManager", "ToolCribAttendant", "CommercialSalesRep", "DeliveryDriver",
          "RouteDispatcher", "CreditAnalyst", "Any"))
BOOK.add("POST", "/commercial/parts/{partId}/supersede", h.supersede_part,
         ["PartsCategoryManager"])
BOOK.add("POST", "/commercial/parts/{partId}/unsupersede", h.unsupersede_part,
         ["PartsCategoryManager"])
BOOK.add("POST", "/commercial/parts/{partId}/archive", h.archive_part, ["PartsCategoryManager"])
BOOK.add("GET", "/commercial/part-fitments", h.list_fitments, READ_ALL)
BOOK.add("GET", "/commercial/part-fitments/{fitmentId}", h.get_fitment, READ_ALL)
BOOK.add("GET", "/commercial/part-interchanges", h.list_interchanges, READ_ALL)
BOOK.add("GET", "/commercial/part-interchanges/{interchangeId}", h.get_interchange, READ_ALL)
BOOK.add("GET", "/commercial/tool-fitments", h.list_tool_fitments,
         ("PartsCategoryManager", "ToolCribAttendant", "CommercialSalesRep", "DeliveryDriver",
          "RouteDispatcher", "CreditAnalyst", "Any"))
BOOK.add("GET", "/commercial/tool-fitments/{fitmentId}", h.get_tool_fitment,
         ("PartsCategoryManager", "ToolCribAttendant", "CommercialSalesRep", "DeliveryDriver",
          "RouteDispatcher", "CreditAnalyst", "Any"))

# --- Vehicle ---------------------------------------------------------------
BOOK.add("POST", "/commercial/vehicles", h.create_vehicle, ["CommercialSalesRep"], 201)
BOOK.add("GET", "/commercial/vehicles", h.list_vehicles,
         ("CommercialSalesRep", "PartsCategoryManager", "RouteDispatcher", "DeliveryDriver",
          "CreditAnalyst", "Any"))
BOOK.add("GET", "/commercial/vehicles/{vehicleId}", h.get_vehicle,
         ("CommercialSalesRep", "PartsCategoryManager", "RouteDispatcher", "DeliveryDriver",
          "CreditAnalyst", "Any"))

# --- SalesRep / RepCoverage ------------------------------------------------
BOOK.add("POST", "/commercial/sales-reps", h.create_sales_rep, ["CommercialSalesRep"], 201)
BOOK.add("GET", "/commercial/sales-reps", h.list_sales_reps, READ_ALL)
BOOK.add("GET", "/commercial/sales-reps/{repId}", h.get_sales_rep, READ_ALL)
BOOK.add("GET", "/commercial/sales-reps/{repId}/coverages", h.list_rep_coverages, READ_ALL)
BOOK.add("POST", "/commercial/rep-coverages", h.create_coverage, ["CommercialSalesRep"], 201)
BOOK.add("GET", "/commercial/rep-coverages", h.list_coverages, READ_ALL)
BOOK.add("GET", "/commercial/rep-coverages/{coverageId}", h.get_coverage, READ_ALL)
BOOK.add("POST", "/commercial/rep-coverages/{coverageId}/extend", h.extend_coverage,
         ["CommercialSalesRep"])
BOOK.add("POST", "/commercial/rep-coverages/{coverageId}/end", h.end_coverage,
         ["CommercialSalesRep"])

# --- PartOrder -------------------------------------------------------------
BOOK.add("POST", "/commercial/part-orders", h.create_order, ["CommercialSalesRep"], 201)
BOOK.add("GET", "/commercial/part-orders", h.list_orders, READ_ALL)
BOOK.add("GET", "/commercial/part-orders/{orderId}", h.get_order, READ_ALL)
BOOK.add("PUT", "/commercial/part-orders/{orderId}", h.update_order, ["CommercialSalesRep"])
BOOK.add("POST", "/commercial/part-orders/{orderId}/confirm", h.confirm_order,
         ["CommercialSalesRep"])
BOOK.add("POST", "/commercial/part-orders/{orderId}/allocate", h.allocate_order,
         ["CommercialSalesRep"])
BOOK.add("POST", "/commercial/part-orders/{orderId}/pick", h.pick_order, ["CommercialSalesRep"])
BOOK.add("POST", "/commercial/part-orders/{orderId}/dispatch", h.dispatch_order, ["DeliveryDriver"])
BOOK.add("POST", "/commercial/part-orders/{orderId}/deliver", h.deliver_order, ["DeliveryDriver"])
BOOK.add("POST", "/commercial/part-orders/{orderId}/refit", h.refit_order, ["CommercialSalesRep"])
BOOK.add("POST", "/commercial/part-orders/{orderId}/return", h.return_order,
         ["CommercialSalesRep"])
BOOK.add("POST", "/commercial/part-orders/{orderId}/void", h.void_order,
         ["CommercialSalesRep", "CreditAnalyst"])
BOOK.add("GET", "/commercial/part-orders/{orderId}/core-returns", h.list_order_core_returns,
         ("CommercialSalesRep", "CreditAnalyst", "ToolCribAttendant", "DeliveryDriver", "Any"))
BOOK.add("GET", "/commercial/part-orders/{orderId}/route-stops", h.list_order_route_stops,
         ("RouteDispatcher", "DeliveryDriver", "CommercialSalesRep", "CreditAnalyst", "Any"))

# --- ToolCatalog -----------------------------------------------------------
BOOK.add("POST", "/commercial/tool-catalog", h.create_tool, ["ToolCribAttendant"], 201)
BOOK.add("GET", "/commercial/tool-catalog", h.list_tools,
         ("ToolCribAttendant", "CommercialSalesRep", "DeliveryDriver", "RouteDispatcher",
          "CreditAnalyst", "Any"))
BOOK.add("GET", "/commercial/tool-catalog/{toolCatalogId}", h.get_tool,
         ("ToolCribAttendant", "CommercialSalesRep", "DeliveryDriver", "RouteDispatcher",
          "CreditAnalyst", "Any"))
BOOK.add("POST", "/commercial/tool-catalog/{toolCatalogId}/adjust-wear", h.adjust_wear,
         ["ToolCribAttendant"])
BOOK.add("POST", "/commercial/tool-catalog/{toolCatalogId}/reset-wear", h.reset_wear,
         ["ToolCribAttendant"])
BOOK.add("GET", "/commercial/tool-catalog/{toolCatalogId}/fitments", h.list_tool_fitments_of_tool,
         ("ToolCribAttendant", "CommercialSalesRep", "DeliveryDriver", "RouteDispatcher",
          "CreditAnalyst", "Any"))
BOOK.add("POST", "/commercial/tool-catalog/{toolCatalogId}/fitments", h.create_tool_fitment,
         ["ToolCribAttendant"], 201)

# --- ToolLoan --------------------------------------------------------------
BOOK.add("POST", "/commercial/tool-loans", h.create_loan, ["CommercialSalesRep"], 201)
BOOK.add("GET", "/commercial/tool-loans", h.list_loans,
         ("ToolCribAttendant", "CommercialSalesRep", "DeliveryDriver", "RouteDispatcher",
          "CreditAnalyst", "Any"))
BOOK.add("GET", "/commercial/tool-loans/{loanId}", h.get_loan,
         ("ToolCribAttendant", "CommercialSalesRep", "DeliveryDriver", "RouteDispatcher",
          "CreditAnalyst", "Any"))
BOOK.add("PUT", "/commercial/tool-loans/{loanId}", h.update_loan, ["CreditAnalyst"])
BOOK.add("POST", "/commercial/tool-loans/{loanId}/checkout", h.checkout_loan,
         ["CommercialSalesRep"])
BOOK.add("POST", "/commercial/tool-loans/{loanId}/return", h.return_loan, ["DeliveryDriver"])
BOOK.add("POST", "/commercial/tool-loans/{loanId}/inspect", h.inspect_loan, ["ToolCribAttendant"])
BOOK.add("POST", "/commercial/tool-loans/{loanId}/close", h.close_loan, ["ToolCribAttendant"])
BOOK.add("POST", "/commercial/tool-loans/{loanId}/forfeit", h.forfeit_loan, ["ToolCribAttendant"])

# --- CoreReturn / WarrantyRegistration -------------------------------------
BOOK.add("POST", "/commercial/core-returns", h.create_core_return, ["CommercialSalesRep"], 201)
BOOK.add("GET", "/commercial/core-returns", h.list_core_returns,
         ("CommercialSalesRep", "CreditAnalyst", "ToolCribAttendant", "DeliveryDriver", "Any"))
BOOK.add("GET", "/commercial/core-returns/{coreReturnId}", h.get_core_return,
         ("CommercialSalesRep", "CreditAnalyst", "ToolCribAttendant", "DeliveryDriver", "Any"))
BOOK.add("POST", "/commercial/core-returns/{coreReturnId}/transit", h.transit_core,
         ["DeliveryDriver"])
BOOK.add("POST", "/commercial/core-returns/{coreReturnId}/inspect", h.inspect_core,
         ["ToolCribAttendant"])
BOOK.add("POST", "/commercial/core-returns/{coreReturnId}/credit", h.credit_core,
         ["CreditAnalyst"])
BOOK.add("POST", "/commercial/core-returns/{coreReturnId}/reject", h.reject_core,
         ["ToolCribAttendant"])
BOOK.add("POST", "/commercial/warranty-registrations", h.create_warranty,
         ["CommercialSalesRep"], 201)
BOOK.add("GET", "/commercial/warranty-registrations", h.list_warranties,
         ("CommercialSalesRep", "CreditAnalyst", "ToolCribAttendant", "DeliveryDriver", "Any"))
BOOK.add("GET", "/commercial/warranty-registrations/{registrationId}", h.get_warranty,
         ("CommercialSalesRep", "CreditAnalyst", "ToolCribAttendant", "DeliveryDriver", "Any"))

# --- ServiceRoute / RouteStop ----------------------------------------------
BOOK.add("POST", "/commercial/service-routes", h.create_route, ["RouteDispatcher"], 201)
BOOK.add("GET", "/commercial/service-routes", h.list_routes,
         ("RouteDispatcher", "DeliveryDriver", "CommercialSalesRep", "CreditAnalyst", "Any"))
BOOK.add("GET", "/commercial/service-routes/{routeId}", h.get_route,
         ("RouteDispatcher", "DeliveryDriver", "CommercialSalesRep", "CreditAnalyst", "Any"))
BOOK.add("POST", "/commercial/service-routes/{routeId}/stops", h.add_stop,
         ["RouteDispatcher"], 201)
BOOK.add("GET", "/commercial/service-routes/{routeId}/stops", h.list_route_stops,
         ("RouteDispatcher", "DeliveryDriver", "CommercialSalesRep", "CreditAnalyst", "Any"))
BOOK.add("GET", "/commercial/service-routes/{routeId}/stops/{stopId}", h.get_route_stop,
         ("RouteDispatcher", "DeliveryDriver", "CommercialSalesRep", "CreditAnalyst", "Any"))
BOOK.add("POST", "/commercial/service-routes/{routeId}/plan", h.plan_route, ["RouteDispatcher"])
BOOK.add("POST", "/commercial/service-routes/{routeId}/dispatch", h.dispatch_route,
         ["RouteDispatcher"])
BOOK.add("POST", "/commercial/service-routes/{routeId}/revert-to-draft", h.revert_to_draft,
         ["RouteDispatcher"])
BOOK.add("POST", "/commercial/service-routes/{routeId}/complete", h.complete_route,
         ["RouteDispatcher"])
BOOK.add("POST", "/commercial/service-routes/{routeId}/cancel", h.cancel_route,
         ["RouteDispatcher"])
BOOK.add("GET", "/commercial/route-stops", h.list_stops,
         ("RouteDispatcher", "DeliveryDriver", "CommercialSalesRep", "CreditAnalyst", "Any"))
BOOK.add("GET", "/commercial/route-stops/{stopId}", h.get_stop,
         ("RouteDispatcher", "DeliveryDriver", "CommercialSalesRep", "CreditAnalyst", "Any"))
BOOK.add("GET", "/commercial/route-stops/{stopId}/orders", h.list_stop_orders,
         ("RouteDispatcher", "DeliveryDriver", "CommercialSalesRep", "CreditAnalyst", "Any"))
BOOK.add("POST", "/commercial/route-stops/{stopId}/deliver", h.deliver_stop, ["DeliveryDriver"])
BOOK.add("POST", "/commercial/route-stops/{stopId}/miss", h.miss_stop, ["DeliveryDriver"])
BOOK.add("POST", "/commercial/route-stops/{stopId}/reject", h.reject_stop, ["RouteDispatcher"])


def route_count():
    return len(BOOK.routes)