# Copyright (c) 2026, Rasiin Technologies
# OT Completion Report: how many OT Schedules were really done (Clinical Procedure
# completed) vs still pending, per practitioner. Doctors see only themselves.

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, today

# ---------------------------------------------------------------------------
# Field map: if a fieldname differs on your site, change it HERE only.
# ---------------------------------------------------------------------------
F = frappe._dict(
	practitioner="practitioner",
	date="appointment_date",
	status="status",
	patient="patient",
	patient_name="patient_name",
	template="procedure_template",
	department="department",
	amount="net_amount",
	company="company",
)
CP_LINK = "ot_schedule"  # Clinical Procedure field that links back to OT Schedule

# ---------------------------------------------------------------------------
# Settings: edit these lists, then `bench restart` (no doctype needed).
# ---------------------------------------------------------------------------
# Exclusions are report filters (multi-select); their defaults are in the .js file.

# Users with these Role Profiles see all practitioners.
# Administrator and System Manager always see all.
FULL_ACCESS_ROLE_PROFILES = ["Finance", "Audit", "OT Manager"]

OVERDUE_DAYS = 7  # Scheduled with no completed procedure, older than this = Overdue
DEFAULT_FROM_DATE = "2026-03-01"  # Jan-Feb 2026 data is unreliable

# key -> (label, indicator colour, action for the OT team)
BUCKETS = {
	"done_closed": ("Done & Closed", "green", ""),
	"done_not_closed": ("Done, not closed", "orange", "Close the schedule"),
	"closed_no_proc": ("Closed, no procedure", "orange", "Verify / create procedure"),
	"in_progress": ("In progress", "blue", "Submit the procedure"),
	"overdue": ("Overdue", "red", "Follow up patient / refund"),
	"upcoming": ("Upcoming", "gray", ""),
	"refunded": ("Refunded / Cancelled", "gray", ""),
}
LABEL_TO_KEY = {v[0]: k for k, v in BUCKETS.items()}
NEEDS_ACTION = ("done_not_closed", "closed_no_proc", "in_progress", "overdue")
RANK_SQL = (
	"case cp.status when 'Completed' then 4 when 'In Progress' then 3 "
	"when 'Pending' then 2 when 'Draft' then 1 else 0 end"
)
RANK_TO_STATUS = {4: "Completed", 3: "In Progress", 2: "Pending", 1: "Draft"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("From Date and To Date are required"))

	full_access, allowed = get_access()

	if not full_access:
		if not allowed:
			frappe.msgprint(
				_("Your user is not linked to a Healthcare Practitioner. Please ask the administrator to add a User Permission.")
			)
			return [], []
		if filters.practitioner and filters.practitioner not in allowed:
			frappe.throw(_("You are not allowed to view {0}").format(filters.practitioner), frappe.PermissionError)

	rows = get_data(filters, None if full_access else allowed)
	cards = get_cards(rows)

	if filters.view == "Details":
		return get_detail_columns(), get_detail_rows(rows, filters), None, None, cards

	summary = get_summary_rows(rows)
	return get_summary_columns(), summary, None, get_chart(summary), cards


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------
def get_access():
	"""Return (full_access, allowed_practitioners)."""
	user = frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True, []

	profile = frappe.db.get_value("User", user, "role_profile_name")
	if profile and profile in FULL_ACCESS_ROLE_PROFILES:
		return True, []

	perms = frappe.permissions.get_user_permissions(user).get("Healthcare Practitioner") or []
	return False, sorted({p.get("doc") for p in perms if p.get("doc")})


@frappe.whitelist()
def get_report_context():
	"""Used by the JS on load to lock the practitioner filter for doctors."""
	full_access, allowed = get_access()
	return {
		"full_access": full_access,
		"practitioners": allowed,
		"default_from_date": DEFAULT_FROM_DATE,
	}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def get_data(filters, allowed):
	cond = [f"ots.`{F.date}` between %(from_date)s and %(to_date)s", "ots.docstatus < 2"]
	params = {"from_date": filters.from_date, "to_date": filters.to_date}

	for key, field in (
		("company", F.company),
		("practitioner", F.practitioner),
		("department", F.department),
		("procedure_template", F.template),
	):
		if filters.get(key):
			cond.append(f"ots.`{field}` = %({key})s")
			params[key] = filters.get(key)

	if allowed is not None:
		cond.append(f"ots.`{F.practitioner}` in %(allowed)s")
		params["allowed"] = tuple(allowed)

	groups = as_list(filters.exclude_item_groups)
	templates = as_list(filters.exclude_templates)
	pracs = as_list(filters.exclude_practitioners)
	if groups:
		cond.append("ifnull(cpt.item_group, '') not in %(ex_groups)s")
		params["ex_groups"] = groups
	if templates:
		cond.append(f"ifnull(ots.`{F.template}`, '') not in %(ex_templates)s")
		params["ex_templates"] = templates
	if pracs:
		cond.append(f"ifnull(ots.`{F.practitioner}`, '') not in %(ex_pracs)s")
		params["ex_pracs"] = pracs

	rows = frappe.db.sql(
		f"""
		select
			ots.name, ots.`{F.date}` as date, ots.`{F.practitioner}` as practitioner,
			ifnull(hp.practitioner_name, ots.`{F.practitioner}`) as practitioner_name,
			ots.`{F.patient}` as patient, ots.`{F.patient_name}` as patient_name,
			ots.`{F.template}` as procedure_template, ots.`{F.department}` as department,
			ots.`{F.status}` as status, ots.`{F.amount}` as amount,
			ifnull(cpa.cp_count, 0) as cp_count, ifnull(cpa.best_rank, 0) as best_rank, cpa.cp_name
		from `tabOT Schedule` ots
		left join `tabHealthcare Practitioner` hp on hp.name = ots.`{F.practitioner}`
		left join `tabClinical Procedure Template` cpt on cpt.name = ots.`{F.template}`
		left join (
			select
				cp.`{CP_LINK}` as ots_name,
				count(*) as cp_count,
				max({RANK_SQL}) as best_rank,
				substring_index(group_concat(cp.name order by {RANK_SQL} desc, cp.creation desc), ',', 1) as cp_name
			from `tabClinical Procedure` cp
			where ifnull(cp.`{CP_LINK}`, '') != '' and cp.docstatus < 2
			group by cp.`{CP_LINK}`
		) cpa on cpa.ots_name = ots.name
		where {" and ".join(cond)}
		order by ots.`{F.date}` desc, ots.name desc
		""",
		params,
		as_dict=True,
	)

	td = getdate(today())
	for r in rows:
		r.days = date_diff(td, r.date) if r.date else 0
		r.bucket = get_bucket(r, OVERDUE_DAYS)
	return rows


def as_list(value):
	"""MultiSelectList filter value -> tuple (accepts list, JSON string or comma text)."""
	if not value:
		return ()
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.startswith("[") else value.split(",")
	return tuple(v.strip() for v in value if v and v.strip())


def get_bucket(r, overdue_days):
	if r.status in ("Refunded", "Cancelled"):
		return "refunded"
	if r.best_rank == 4:
		return "done_closed" if r.status == "Closed" else "done_not_closed"
	if r.best_rank in (1, 2, 3):
		return "in_progress"
	if r.status == "Closed":
		return "closed_no_proc"
	return "overdue" if r.days > overdue_days else "upcoming"


def completion(c):
	base = c["total"] - c["refunded"] - c["upcoming"]
	return round((c["done_closed"] + c["done_not_closed"]) * 100.0 / base, 1) if base else None


def count(rows):
	c = {k: 0 for k in BUCKETS}
	c.update(total=len(rows), overdue_amount=0.0)
	for r in rows:
		c[r.bucket] += 1
		if r.bucket == "overdue":
			c["overdue_amount"] += flt(r.amount)
	return c


# ---------------------------------------------------------------------------
# Summary view
# ---------------------------------------------------------------------------
def get_summary_columns():
	cols = [
		{"fieldname": "practitioner", "label": _("Healthcare Practitioner"), "fieldtype": "Link",
		 "options": "Healthcare Practitioner", "width": 280},
		{"fieldname": "total", "label": _("Total"), "fieldtype": "Int", "width": 80},
	]
	for key, (label, _c, _a) in BUCKETS.items():
		cols.append({"fieldname": key, "label": _(label), "fieldtype": "Int", "width": 115})
	cols += [
		{"fieldname": "completion", "label": _("Completion %"), "fieldtype": "Percent", "width": 115},
		{"fieldname": "overdue_amount", "label": _("Overdue Paid"), "fieldtype": "Currency", "width": 120},
	]
	return cols


def get_summary_rows(rows):
	grouped = {}
	for r in rows:
		grouped.setdefault(r.practitioner or "", {"name": r.practitioner_name, "rows": []})["rows"].append(r)

	out = []
	for prac, g in grouped.items():
		c = count(g["rows"])
		c.update(practitioner=prac, practitioner_name=g["name"], completion=completion(c))
		out.append(c)
	out.sort(key=lambda x: -x["total"])

	if len(out) > 1:
		t = count(rows)
		t.update(practitioner="", practitioner_name=_("Total"), completion=completion(t), is_total=1)
		out.append(t)
	return out


def get_chart(summary):
	rows = [s for s in summary if not s.get("is_total")][:12]
	if not rows:
		return None

	def pct(s, keys):
		active = s["total"] - s["refunded"]
		return round(sum(s[k] for k in keys) * 100.0 / active, 1) if active else 0

	series = [
		(_("Done & Closed"), ["done_closed"]),
		(_("Done not closed / No procedure"), ["done_not_closed", "closed_no_proc"]),
		(_("Overdue"), ["overdue"]),
		(_("Upcoming / In progress"), ["upcoming", "in_progress"]),
	]
	return {
		"data": {
			"labels": [s["practitioner_name"] for s in rows],
			"datasets": [{"name": n, "values": [pct(s, k) for s in rows]} for n, k in series],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
		"colors": ["#2F8F55", "#E8A33C", "#C8372D", "#C9D1D9"],
		"fieldtype": "Percent",
		"height": 300,
	}


def get_cards(rows):
	c = count(rows)
	comp = completion(c)
	return [
		{"value": c["total"], "label": _("Total Scheduled"), "datatype": "Int"},
		{"value": c["done_closed"], "label": _("Done & Closed"), "datatype": "Int", "indicator": "Green"},
		{"value": comp or 0, "label": _("Completion %"), "datatype": "Percent", "indicator": "Green"},
		{"value": c["done_not_closed"], "label": _("Done, not closed"), "datatype": "Int", "indicator": "Orange"},
		{"value": c["closed_no_proc"], "label": _("Closed, no procedure"), "datatype": "Int", "indicator": "Orange"},
		{"value": c["in_progress"], "label": _("In progress"), "datatype": "Int", "indicator": "Blue"},
		{"value": c["overdue"], "label": _("Overdue"), "datatype": "Int", "indicator": "Red"},
		{"value": c["overdue_amount"], "label": _("Overdue Paid"), "datatype": "Currency", "indicator": "Red"},
		{"value": c["upcoming"], "label": _("Upcoming"), "datatype": "Int"},
		{"value": c["refunded"], "label": _("Refunded / Cancelled"), "datatype": "Int"},
	]


# ---------------------------------------------------------------------------
# Details view
# ---------------------------------------------------------------------------
def get_detail_columns():
	return [
		{"fieldname": "ot_schedule", "label": _("OT Schedule"), "fieldtype": "Link", "options": "OT Schedule", "width": 140},
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "practitioner", "label": _("Practitioner"), "fieldtype": "Link", "options": "Healthcare Practitioner", "width": 200},
		{"fieldname": "patient", "label": _("Patient"), "fieldtype": "Link", "options": "Patient", "width": 110},
		{"fieldname": "patient_name", "label": _("Patient Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "procedure_template", "label": _("Procedure Template"), "fieldtype": "Link", "options": "Clinical Procedure Template", "width": 200},
		{"fieldname": "schedule_status", "label": _("Schedule Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "clinical_procedure", "label": _("Clinical Procedure"), "fieldtype": "Link", "options": "Clinical Procedure", "width": 160},
		{"fieldname": "procedure_status", "label": _("Procedure Status"), "fieldtype": "Data", "width": 110},
		{"fieldname": "cp_count", "label": _("# Proc."), "fieldtype": "Int", "width": 70},
		{"fieldname": "days", "label": _("Days"), "fieldtype": "Int", "width": 70},
		{"fieldname": "amount", "label": _("Paid"), "fieldtype": "Currency", "width": 100},
		{"fieldname": "bucket", "label": _("Bucket"), "fieldtype": "Data", "width": 150},
		{"fieldname": "action", "label": _("Action for OT"), "fieldtype": "Data", "width": 190},
	]


def get_detail_rows(rows, filters):
	if filters.bucket == "Needs action":
		rows = [r for r in rows if r.bucket in NEEDS_ACTION]
	elif filters.bucket in LABEL_TO_KEY:
		rows = [r for r in rows if r.bucket == LABEL_TO_KEY[filters.bucket]]

	out = []
	for r in rows:
		label, _color, action = BUCKETS[r.bucket]
		out.append({
			"ot_schedule": r.name,
			"date": r.date,
			"practitioner": r.practitioner,
			"patient": r.patient,
			"patient_name": r.patient_name,
			"procedure_template": r.procedure_template,
			"schedule_status": r.status,
			"clinical_procedure": r.cp_name,
			"procedure_status": RANK_TO_STATUS.get(r.best_rank, ""),
			"cp_count": r.cp_count,
			"days": r.days,
			"amount": r.amount,
			"bucket": _(label),
			"bucket_key": r.bucket,
			"action": _(action) if action else "",
		})
	return out
