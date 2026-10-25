import frappe
from frappe import _

ALLOWED_ROLES = {"System Manager", "IPD Manager"}

@frappe.whitelist()
def set_service_unit_occupancy(service_unit, occupancy_status, force=0):
    if occupancy_status not in ("Vacant", "Occupied"):
        frappe.throw(_("Invalid occupancy status"))

    if not (ALLOWED_ROLES & set(frappe.get_roles())):
        frappe.throw(_("You are not permitted to change bed occupancy"), frappe.PermissionError)

    unit = frappe.get_doc("Healthcare Service Unit", service_unit)
    if unit.is_group:
        frappe.throw(_("{0} is a group node; select a bed/room").format(service_unit))

    old = unit.occupancy_status
    if old == occupancy_status:
        return {"changed": False, "old": old, "new": occupancy_status}

    # Guard: don't silently vacate a bed that still has an active admission
    if occupancy_status == "Vacant" and not int(force):
        record = frappe.db.get_value(
            "Inpatient Occupancy", {"service_unit": service_unit, "left": 0}, "parent"
        )
        if record:
            return {"blocked": True, "inpatient_record": record}

    unit.db_set("occupancy_status", occupancy_status)
    unit.add_comment(
        "Info",
        _("Occupancy changed from {0} to {1} by {2} via HIS Settings").format(
            old, occupancy_status, frappe.session.user
        ),
    )
    return {"changed": True, "old": old, "new": occupancy_status}