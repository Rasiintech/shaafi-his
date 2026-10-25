// Copyright (c) 2026, Shaafi Hospital
// Daily Cash Dashboard - Script Report (JS side)
// The report name below MUST match the Report name exactly.

frappe.query_reports["Daily Cash Dashboard"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
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
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
			get_query: function () {
				const company = frappe.query_report.get_filter_value("company");
				return { filters: { company: company, is_group: 0 } };
			},
		},
	],

	onload: function (report) {
		// slightly bigger KPI numbers
		frappe.dom.set_style(
			`.report-summary .summary-value { font-size: 1.55rem !important; font-weight: 700; }
			 .report-summary .summary-label { font-size: 12px; opacity: .8; }`,
			"daily-cash-dashboard-style"
		);

		const set_range = (from, to) => {
			frappe.query_report.set_filter_value({ from_date: from, to_date: to });
			frappe.query_report.refresh();
		};

		report.page.add_inner_button(__("Today"), () => {
			const t = frappe.datetime.get_today();
			set_range(t, t);
		});

		report.page.add_inner_button(__("Yesterday"), () => {
			const y = frappe.datetime.add_days(frappe.datetime.get_today(), -1);
			set_range(y, y);
		});

		report.page.add_inner_button(__("This Month"), () => {
			set_range(frappe.datetime.month_start(), frappe.datetime.get_today());
		});
	},

	// Section headers in bold with a rule, totals in bold, amounts coloured by meaning
	formatter: function (value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);

		// header rows have no amount: show it empty (not $ 0.00)
		if (data.is_header) {
			if (column.fieldname !== "item") return "";
			value = default_formatter(value, row, column, data);
			return `<span style="display:block;font-weight:700;font-size:13px;
				padding:4px 0;border-bottom:2px solid var(--border-color);">${value}</span>`;
		}

		value = default_formatter(value, row, column, data);

		const colors = {
			green: "#1b7f5c",
			red: "#c0392b",
			orange: "#b7791f",
			blue: "#2b6cb0",
		};
		const color = colors[data.color];
		let style = "";
		if (data.is_bold) style += "font-weight:700;";
		if (color && column.fieldname === "amount") style += `color:${color};`;

		if (column.fieldname === "item") {
			// keep the indent spaces visible
			return `<span style="white-space:pre;${style}">${value}</span>`;
		}
		return style ? `<span style="${style}">${value}</span>` : value;
	},
};
