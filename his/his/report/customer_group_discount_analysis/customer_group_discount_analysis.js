// Copyright (c) 2026, Cibaar Technologies
// Customer Group Discount Analysis — v2

frappe.query_reports["Customer Group Discount Analysis"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "report_type",
			label: __("Report Type"),
			fieldtype: "Select",
			options: "Detail\nSummary\nPatient Summary\nItem Summary\nDaily Summary",
			default: "Summary",
			reqd: 1,
		},
		{
			fieldname: "customer_group",
			label: __("Customer Group"),
			fieldtype: "Link",
			options: "Customer Group",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "patient",
			label: __("Patient"),
			fieldtype: "Link",
			options: "Patient",
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		// Our own total row: show the "Total" label in the right column, bold everything
		if (data && data.is_total_row) {
			if (column.fieldname === data.total_label_field) {
				return `<b>${__("Total")}</b>`;
			}
			value = default_formatter(value, row, column, data);
			return value ? `<b>${value}</b>` : "";
		}

		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === "discount_amount" && flt(data.discount_amount) > 0) {
			return `<span style="color: var(--red-600); font-weight: 600;">${value}</span>`;
		}

		if (column.fieldname === "billed_amount") {
			return `<span style="color: var(--green-700);">${value}</span>`;
		}

		if (column.fieldname === "discount_percentage") {
			const p = flt(data.discount_percentage);
			const color = p >= 30 ? "red" : p >= 10 ? "orange" : "blue";
			return `<span class="indicator-pill ${color}" style="padding: 2px 8px;">${value}</span>`;
		}

		if (column.fieldname === "discount_share" && flt(data.discount_share) >= 20) {
			return `<b>${value}</b>`;
		}

		return value;
	},

	onload(report) {
		// Quick jump: from any summary, open the Patient Summary for the current filters
		report.page.add_inner_button(__("Patient Summary"), () => {
			report.set_filter_value("report_type", "Patient Summary");
		});
		report.page.add_inner_button(__("Daily Trend"), () => {
			report.set_filter_value("report_type", "Daily Summary");
		});
	},
};