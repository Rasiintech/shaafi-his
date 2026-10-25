// Copyright (c) 2023, Rasiin Tech and contributors
// For license information, please see license.txt

// frappe.ui.form.on('HIS Settings', {
// 	// refresh: function(frm) {

// 	// }
// });

frappe.ui.form.on("HIS Settings", {
    refresh(frm) {
        frm.add_custom_button(
            __("Update Bed Occupancy"),
            () => show_occupancy_dialog(),
            __("Utilities")
        );
    },
});

function show_occupancy_dialog() {
    const d = new frappe.ui.Dialog({
        title: __("Update Service Unit Occupancy"),
        fields: [
            {
                fieldname: "service_unit_type",
                label: __("Healthcare Service Unit Type"),
                fieldtype: "Link",
                options: "Healthcare Service Unit Type",
                reqd: 1,
                onchange() {
                    d.set_value("service_unit", "");
                    d.set_value("current_status", "");
                },
            },
            {
                fieldname: "service_unit",
                label: __("Healthcare Service Unit"),
                fieldtype: "Link",
                options: "Healthcare Service Unit",
                reqd: 1,
                get_query() {
                    return {
                        filters: {
                            service_unit_type: d.get_value("service_unit_type"),
                            is_group: 0,
                        },
                    };
                },
                onchange() {
                    const su = d.get_value("service_unit");
                    if (!su) return d.set_value("current_status", "");
                    frappe.db
                        .get_value("Healthcare Service Unit", su, "occupancy_status")
                        .then((r) => d.set_value("current_status", r.message.occupancy_status));
                },
            },
            { fieldname: "current_status", label: __("Current Status"), fieldtype: "Data", read_only: 1 },
            {
                fieldname: "occupancy_status",
                label: __("Set Status To"),
                fieldtype: "Select",
                options: "Vacant\nOccupied",
                default: "Vacant",
                reqd: 1,
            },
        ],
        primary_action_label: __("Update"),
        primary_action(values) {
            submit(values, 0);
        },
    });

    function submit(values, force) {
        frappe.call({
            method: "his.api.service_unit.set_service_unit_occupancy",
            args: {
                service_unit: values.service_unit,
                occupancy_status: values.occupancy_status,
                force: force,
            },
            freeze: true,
            callback(r) {
                const m = r.message || {};
                if (m.blocked) {
                    frappe.confirm(
                        __("{0} still has an active admission ({1}). Force it to Vacant anyway?",
                           [values.service_unit, m.inpatient_record]),
                        () => submit(values, 1)
                    );
                    return;
                }
                frappe.show_alert({
                    message: m.changed
                        ? __("{0}: {1} → {2}", [values.service_unit, m.old, m.new])
                        : __("No change, already {0}", [m.new]),
                    indicator: m.changed ? "green" : "orange",
                });
                d.hide();
            },
        });
    }

    d.show();
}