# Copyright (c) 2026, Cibaar Technologies
# Customer Group Discount Analysis — v2
#
# Report types:
#   Detail          -> one row per discounted invoice line
#   Summary         -> Customer Group x Item Group
#   Patient Summary -> one row per patient (visits, first/last visit, top item group)
#   Item Summary    -> one row per item
#   Daily Summary   -> one row per day (trend)
#
# Every mode returns number cards (report_summary) + a chart.
# IMPORTANT: untick "Add Total Row" on the Report doc — this report adds its own
# correct total row (Frappe's built-in one averages the Discount % column).

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

FULL_ACCESS_ROLES = {"System Manager", "Accounts Manager", "Accounts User", "Auditor"}
CRM_ROLES = {"CRM", "Marketing"}
CRM_EXCLUDED_ITEM_GROUPS = ("OT", "Drug", "Consultation", "Anesthesia", "ENT Procedure", "Services")

REPORT_TYPES = ("Detail", "Summary", "Patient Summary", "Item Summary", "Daily Summary")

COLOR_BILLED = "#2490EF"
COLOR_DISCOUNT = "#E24C4C"


def execute(filters=None):
    filters = frappe._dict(filters or {})
    report_type = filters.report_type if filters.report_type in REPORT_TYPES else "Detail"

    meta = frappe.get_meta("Sales Invoice")
    ctx = frappe._dict(
        has_patient=meta.has_field("patient"),
        has_patient_name=meta.has_field("patient_name"),
        currency=get_currency(),
    )

    rows = get_rows(filters, ctx)
    by_item_group = sorted(
        group_rows(rows, lambda r: r.item_group, lambda r: {"item_group": r.item_group}),
        key=lambda g: -g["discount_amount"],
    )

    builder = {
        "Detail": build_detail,
        "Summary": build_item_group_summary,
        "Patient Summary": build_patient_summary,
        "Item Summary": build_item_summary,
        "Daily Summary": build_daily_summary,
    }[report_type]

    columns, data, chart, label_field = builder(rows, ctx, by_item_group)

    total = finalize(fill_bucket(new_bucket(), rows))
    if data:
        data.append(make_total_row(total, label_field))

    summary = get_report_summary(total, by_item_group, ctx) if rows else []

    return columns, data, None, chart, summary


# ---------------------------------------------------------------- data

def get_conditions(filters, ctx):
    user_roles = set(frappe.get_roles(frappe.session.user))
    can_see_all = bool(user_roles & FULL_ACCESS_ROLES)
    is_crm = bool(user_roles & CRM_ROLES)
    excluded_item_groups = CRM_EXCLUDED_ITEM_GROUPS if (is_crm and not can_see_all) else ()

    conditions = [
        "si.docstatus = 1",
        "si.posting_date BETWEEN %(from_date)s AND %(to_date)s",
        "IFNULL(sii.amount, 0) > IFNULL(sii.net_amount, 0)",
    ]
    values = {"from_date": filters.from_date, "to_date": filters.to_date}

    if not can_see_all:
        if is_crm:
            conditions.append("c.customer_group IN ('Membership', 'Corporate')")
        else:
            conditions.append("c.customer_group = 'Membership'")

    if filters.customer_group:
        conditions.append("c.customer_group = %(customer_group)s")
        values["customer_group"] = filters.customer_group

    if filters.item_group:
        if filters.item_group in excluded_item_groups:
            conditions.append("1 = 0")
        else:
            conditions.append("sii.item_group = %(item_group)s")
            values["item_group"] = filters.item_group
    elif excluded_item_groups:
        conditions.append("sii.item_group NOT IN %(excluded_item_groups)s")
        values["excluded_item_groups"] = excluded_item_groups

    if filters.patient:
        conditions.append("si.patient = %(patient)s" if ctx.has_patient else "si.customer = %(patient)s")
        values["patient"] = filters.patient

    if filters.customer:
        conditions.append("si.customer = %(customer)s")
        values["customer"] = filters.customer

    if filters.item_code:
        conditions.append("sii.item_code = %(item_code)s")
        values["item_code"] = filters.item_code

    return " AND ".join(conditions), values


def get_rows(filters, ctx):
    conditions, values = get_conditions(filters, ctx)

    patient_expr = "COALESCE(NULLIF(si.patient, ''), si.customer)" if ctx.has_patient else "si.customer"
    name_expr = (
        "COALESCE(NULLIF(si.patient_name, ''), si.customer_name)"
        if ctx.has_patient_name
        else "si.customer_name"
    )

    return frappe.db.sql(
        f"""
        SELECT
            si.posting_date AS date,
            si.name AS invoice,
            si.customer,
            {patient_expr} AS patient,
            {name_expr} AS patient_name,
            IFNULL(c.customer_group, '') AS customer_group,
            sii.item_code,
            sii.item_name,
            IFNULL(sii.item_group, '') AS item_group,
            IFNULL(sii.qty, 0) AS qty,
            IFNULL(sii.amount, 0) AS original_amount,
            IFNULL(sii.net_amount, 0) AS billed_amount,
            IFNULL(sii.amount, 0) - IFNULL(sii.net_amount, 0) AS discount_amount
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        LEFT JOIN `tabCustomer` c ON c.name = si.customer
        WHERE {conditions}
        ORDER BY si.posting_date, si.name, sii.idx
        """,
        values,
        as_dict=True,
    )


# ---------------------------------------------------------------- aggregation

def new_bucket():
    return {
        "_patients": set(),
        "_invoices": set(),
        "_ig_discount": {},
        "lines": 0,
        "qty": 0.0,
        "original_amount": 0.0,
        "billed_amount": 0.0,
        "discount_amount": 0.0,
        "first_date": None,
        "last_date": None,
    }


def add_row(b, r):
    b["_patients"].add(r.patient)
    b["_invoices"].add(r.invoice)
    b["_ig_discount"][r.item_group] = b["_ig_discount"].get(r.item_group, 0) + flt(r.discount_amount)
    b["lines"] += 1
    b["qty"] += flt(r.qty)
    b["original_amount"] += flt(r.original_amount)
    b["billed_amount"] += flt(r.billed_amount)
    b["discount_amount"] += flt(r.discount_amount)
    if r.date and (not b["first_date"] or r.date < b["first_date"]):
        b["first_date"] = r.date
    if r.date and (not b["last_date"] or r.date > b["last_date"]):
        b["last_date"] = r.date


def fill_bucket(b, rows):
    for r in rows:
        add_row(b, r)
    return b


def finalize(b):
    ig = b.pop("_ig_discount")
    b["patients"] = len(b.pop("_patients"))
    b["invoices"] = len(b.pop("_invoices"))
    b["discount_percentage"] = pct(b["discount_amount"], b["original_amount"])
    b["avg_discount_per_patient"] = safe_div(b["discount_amount"], b["patients"])
    b["avg_bill_per_patient"] = safe_div(b["billed_amount"], b["patients"])
    b["top_item_group"] = max(ig, key=ig.get) if ig else None
    return b


def group_rows(rows, key_fn, init_fn):
    groups = {}
    for r in rows:
        key = key_fn(r)
        b = groups.get(key)
        if b is None:
            b = groups[key] = new_bucket()
            b.update(init_fn(r))
        add_row(b, r)
    return [finalize(b) for b in groups.values()]


def add_share(groups):
    total = sum(g["discount_amount"] for g in groups)
    for g in groups:
        g["discount_share"] = pct(g["discount_amount"], total)
    return groups


def make_total_row(total, label_field):
    row = dict(total)
    for key in ("first_date", "last_date", "top_item_group"):
        row.pop(key, None)
    row["discount_share"] = 100 if total["discount_amount"] else 0
    row["is_total_row"] = 1
    row["total_label_field"] = label_field
    return row


def pct(part, whole):
    return round(flt(part) / flt(whole) * 100, 2) if flt(whole) else 0


def safe_div(a, b):
    return flt(a) / flt(b) if flt(b) else 0


# ---------------------------------------------------------------- columns

def col(label, fieldname, fieldtype="Data", width=120, options=None):
    c = {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width}
    if options:
        c["options"] = options
    return c


def money_columns(share=False):
    cols = [
        col("Original Amount", "original_amount", "Currency", 140),
        col("Billed Amount", "billed_amount", "Currency", 140),
        col("Discount Amount", "discount_amount", "Currency", 140),
        col("Discount %", "discount_percentage", "Percent", 100),
    ]
    if share:
        cols.append(col("% of Total Discount", "discount_share", "Percent", 140))
    return cols


def patient_column(ctx, width=150):
    return (
        col("Patient", "patient", "Link", width, "Patient")
        if ctx.has_patient
        else col("Customer", "patient", "Link", width, "Customer")
    )


# ---------------------------------------------------------------- builders
# each returns (columns, data, chart, total_label_field)

def build_detail(rows, ctx, by_item_group):
    columns = [
        col("Date", "date", "Date", 100),
        col("Invoice", "invoice", "Link", 180, "Sales Invoice"),
        patient_column(ctx, 130),
        col("Patient Name", "patient_name", "Data", 220),
        col("Customer Group", "customer_group", "Link", 130, "Customer Group"),
        col("Item", "item_name", "Data", 260),
        col("Item Group", "item_group", "Link", 130, "Item Group"),
        col("Qty", "qty", "Float", 70),
    ] + money_columns()

    for r in rows:
        r["discount_percentage"] = pct(r.discount_amount, r.original_amount)

    return columns, list(rows), item_group_chart(by_item_group), "patient_name"


def build_item_group_summary(rows, ctx, by_item_group):
    columns = [
        col("Customer Group", "customer_group", "Link", 150, "Customer Group"),
        col("Item Group", "item_group", "Link", 150, "Item Group"),
        col("Patients", "patients", "Int", 90),
        col("Invoices", "invoices", "Int", 90),
        col("Qty", "qty", "Float", 90),
    ] + money_columns(share=True) + [
        col("Avg Discount / Patient", "avg_discount_per_patient", "Currency", 160),
    ]

    data = group_rows(
        rows,
        lambda r: (r.customer_group, r.item_group),
        lambda r: {"customer_group": r.customer_group, "item_group": r.item_group},
    )
    data.sort(key=lambda g: (g["customer_group"], -g["discount_amount"]))
    return columns, add_share(data), item_group_chart(by_item_group), "customer_group"


def build_patient_summary(rows, ctx, by_item_group):
    columns = [
        patient_column(ctx, 130),
        col("Patient Name", "patient_name", "Data", 220),
        col("Customer Group", "customer_group", "Link", 130, "Customer Group"),
        col("Visits (Invoices)", "invoices", "Int", 120),
        col("Items", "lines", "Int", 70),
        col("First Visit", "first_date", "Date", 100),
        col("Last Visit", "last_date", "Date", 100),
        col("Top Item Group", "top_item_group", "Data", 130),
    ] + money_columns(share=True)

    data = group_rows(
        rows,
        lambda r: r.patient,
        lambda r: {"patient": r.patient, "patient_name": r.patient_name, "customer_group": r.customer_group},
    )
    data.sort(key=lambda g: -g["discount_amount"])
    data = add_share(data)

    top = data[:10]
    chart = bar_chart(
        [g["patient_name"] or g["patient"] for g in top],
        [{"name": _("Discount"), "values": [round(g["discount_amount"], 2) for g in top]}],
        [COLOR_DISCOUNT],
    )
    return columns, data, chart, "patient_name"


def build_item_summary(rows, ctx, by_item_group):
    columns = [
        col("Item Code", "item_code", "Link", 140, "Item"),
        col("Item Name", "item_name", "Data", 260),
        col("Item Group", "item_group", "Link", 130, "Item Group"),
        col("Patients", "patients", "Int", 90),
        col("Invoices", "invoices", "Int", 90),
        col("Qty", "qty", "Float", 90),
    ] + money_columns(share=True)

    data = group_rows(
        rows,
        lambda r: r.item_code,
        lambda r: {"item_code": r.item_code, "item_name": r.item_name, "item_group": r.item_group},
    )
    data.sort(key=lambda g: -g["discount_amount"])
    data = add_share(data)

    top = data[:10]
    chart = bar_chart(
        [g["item_name"] for g in top],
        [{"name": _("Discount"), "values": [round(g["discount_amount"], 2) for g in top]}],
        [COLOR_DISCOUNT],
    )
    return columns, data, chart, "item_name"


def build_daily_summary(rows, ctx, by_item_group):
    columns = [
        col("Date", "date", "Date", 110),
        col("Patients", "patients", "Int", 90),
        col("Invoices", "invoices", "Int", 90),
        col("Items", "lines", "Int", 80),
    ] + money_columns() + [
        col("Avg Discount / Patient", "avg_discount_per_patient", "Currency", 160),
    ]

    data = group_rows(rows, lambda r: r.date, lambda r: {"date": r.date})  # rows already date-ordered
    labels = [frappe.format(g["date"], {"fieldtype": "Date"}) for g in data]
    chart = {
        "data": {
            "labels": labels,
            "datasets": [
                {"name": _("Billed"), "values": [round(g["billed_amount"], 2) for g in data]},
                {"name": _("Discount"), "values": [round(g["discount_amount"], 2) for g in data]},
            ],
        },
        "type": "line",
        "colors": [COLOR_BILLED, COLOR_DISCOUNT],
        "lineOptions": {"regionFill": 1},
        "fieldtype": "Currency",
    }
    return columns, data, chart, "date"


# ---------------------------------------------------------------- chart + cards

def bar_chart(labels, datasets, colors, stacked=False):
    chart = {
        "data": {"labels": labels, "datasets": datasets},
        "type": "bar",
        "colors": colors,
        "fieldtype": "Currency",
    }
    if stacked:
        chart["barOptions"] = {"stacked": 1}
    return chart


def item_group_chart(by_item_group):
    """Stacked bar: Billed + Discount = Original amount, per item group."""
    return bar_chart(
        [g["item_group"] or _("Not Set") for g in by_item_group],
        [
            {"name": _("Billed"), "values": [round(g["billed_amount"], 2) for g in by_item_group]},
            {"name": _("Discount"), "values": [round(g["discount_amount"], 2) for g in by_item_group]},
        ],
        [COLOR_BILLED, COLOR_DISCOUNT],
        stacked=True,
    )


def get_report_summary(total, by_item_group, ctx):
    cur = ctx.currency
    top = by_item_group[0] if by_item_group else None
    top_label = f"{top['item_group']} ({fmt_money(top['discount_amount'], currency=cur)})" if top else "-"

    def card(label, value, datatype, indicator):
        c = {"label": _(label), "value": value, "datatype": datatype, "indicator": indicator}
        if datatype == "Currency":
            c["currency"] = cur
        return c

    return [
        card("Patients Served", total["patients"], "Int", "Blue"),
        card("Invoices", total["invoices"], "Int", "Blue"),
        card("Avg Visits / Patient", round(safe_div(total["invoices"], total["patients"]), 2), "Float", "Blue"),
        card("Original Amount", total["original_amount"], "Currency", "Grey"),
        card("Billed Amount", total["billed_amount"], "Currency", "Green"),
        card("Total Discount Given", total["discount_amount"], "Currency", "Red"),
        card("Effective Discount %", total["discount_percentage"], "Percent", "Orange"),
        card("Avg Discount / Patient", total["avg_discount_per_patient"], "Currency", "Red"),
        card("Avg Bill / Patient", total["avg_bill_per_patient"], "Currency", "Green"),
        card("Biggest Discount Group", top_label, "Data", "Orange"),
    ]


def get_currency():
    company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
        "Global Defaults", "default_company"
    )
    currency = company and frappe.get_cached_value("Company", company, "default_currency")
    return currency or frappe.db.get_default("currency")