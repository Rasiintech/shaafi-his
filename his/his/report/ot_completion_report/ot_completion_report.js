// Copyright (c) 2026, Rasiin Technologies
// OT Completion Report

// Change if the report lives in another app/module.
const OT_REPORT_PY = "his.his.report.ot_completion_report.ot_completion_report";

// Default exclusions (users can add/remove in the filters; no code change needed).
const OT_DEFAULT_EXCLUDE = {
	practitioners: ["DIALYSIS", "Dressing", "Referal"],
	templates: ["HEMODIALYSIS", "Hemodialys", "Dental Implants"],
	item_groups: [],
};

const OT_BUCKETS = {
	// fieldname: [label used in the Bucket filter, indicator colour]
	done_closed: ["Done & Closed", "green"],
	done_not_closed: ["Done, not closed", "orange"],
	closed_no_proc: ["Closed, no procedure", "orange"],
	in_progress: ["In progress", "blue"],
	overdue: ["Overdue", "red"],
	upcoming: ["Upcoming", "gray"],
	refunded: ["Refunded / Cancelled", "gray"],
};

// Click on a number in the Summary -> open Details for that practitioner + bucket
frappe.ot_report_drill = function (el) {
	const r = frappe.query_report;
	const vals = { bucket: el.dataset.bucket || "" };
	if (!r._ot_locked) vals.practitioner = el.dataset.practitioner || "";
	vals.view = "Details"; // keep last: it always changes, so it triggers the refresh
	r.set_filter_value(vals);
	return false;
};

frappe.query_reports["OT Completion Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "practitioner",
			label: __("Healthcare Practitioner"),
			fieldtype: "Link",
			options: "Healthcare Practitioner",
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Medical Department",
		},
		{
			fieldname: "procedure_template",
			label: __("Procedure Template"),
			fieldtype: "Link",
			options: "Clinical Procedure Template",
		},
		{
			fieldname: "bucket",
			label: __("Bucket (Details)"),
			fieldtype: "Select",
			options: ["", "Needs action"].concat(Object.values(OT_BUCKETS).map((b) => b[0])).join("\n"),
		},
		{
			fieldname: "view",
			label: __("View"),
			fieldtype: "Select",
			options: "Summary\nDetails",
			default: "Summary",
			reqd: 1,
		},
		{
			fieldname: "exclude_practitioners",
			label: __("Exclude Practitioners"),
			fieldtype: "MultiSelectList",
			default: OT_DEFAULT_EXCLUDE.practitioners,
			get_data: (txt) => frappe.db.get_link_options("Healthcare Practitioner", txt),
		},
		{
			fieldname: "exclude_templates",
			label: __("Exclude Procedure Templates"),
			fieldtype: "MultiSelectList",
			default: OT_DEFAULT_EXCLUDE.templates,
			get_data: (txt) => frappe.db.get_link_options("Clinical Procedure Template", txt),
		},
		{
			fieldname: "exclude_item_groups",
			label: __("Exclude Item Groups"),
			fieldtype: "MultiSelectList",
			default: OT_DEFAULT_EXCLUDE.item_groups,
			get_data: (txt) => frappe.db.get_link_options("Item Group", txt),
		},
	],

	onload(report) {
		frappe.call({
			method: `${OT_REPORT_PY}.get_report_context`,
			callback(r) {
				const ctx = r.message || {};
				const vals = {};

				if (ctx.default_from_date) vals.from_date = ctx.default_from_date;

				if (!ctx.full_access) {
					// doctors get the default exclusions, they don't edit them
					["exclude_practitioners", "exclude_templates", "exclude_item_groups"].forEach((f) =>
						report.get_filter(f).toggle(false)
					);
					const pracs = ctx.practitioners || [];
					if (pracs.length === 1) {
						report._ot_locked = true;
						vals.practitioner = pracs[0];
						const f = report.get_filter("practitioner");
						f.df.read_only = 1;
						f.refresh();
					}
				}

				if (Object.keys(vals).length) report.set_filter_value(vals);
			},
		});
	},

	formatter(value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);
		const fn = column.fieldname;

		if (data.is_total && fn === "practitioner") return `<b>${__("Total")}</b>`;

		let out = default_formatter(value, row, column, data);

		// Summary: clickable numbers
		const drillable = fn === "total" || (OT_BUCKETS[fn] && data.bucket_key === undefined);
		if (drillable && cint(data[fn]) > 0) {
			const bucket = fn === "total" ? "" : OT_BUCKETS[fn][0];
			const prac = frappe.utils.escape_html(data.practitioner || "");
			out = `<a href="#" data-bucket="${bucket}" data-practitioner="${prac}"
				onclick="return frappe.ot_report_drill(this)">${out}</a>`;
		}

		// Details: coloured bucket pill
		if (fn === "bucket" && data.bucket_key && OT_BUCKETS[data.bucket_key]) {
			out = `<span class="indicator-pill ${OT_BUCKETS[data.bucket_key][1]}">${value}</span>`;
		}

		return data.is_total ? `<b>${out}</b>` : out;
	},
};
