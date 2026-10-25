# Copyright (c) 2026, Shaafi Hospital
# Daily Cash Dashboard - Script Report (Python side)
#
# Reads: Sales Invoice, Payment Entry, Purchase Invoice, Expenses (custom)
# Counts ONLY submitted documents (docstatus = 1).
#
# HOW THE FILTERS WORK
#   From/To Date, Company ........ everything
#   Cost Center .................. everything (invoices/purchases by their item lines,
#                                  expenses by their expense lines)
#
#   When Cost Center is set, customer receipts are counted only where a Payment Entry
#   is linked to a matching invoice (payments not linked to any invoice are left out).
#
# MONEY IN also includes Journal Entries that put money INTO a Cash/Bank account,
# classified using Journal Entry Account.reference_invoice (a Sales Invoice, when set):
#   - reference_invoice's posting_date before the period -> Old Debt Collected
#   - reference_invoice's posting_date inside the period  -> counted as same-period payment
#   - no reference_invoice (or it's not found)             -> Unallocated Money
#
# RECEIVABLE is the honest version of Credit Sales: it reads the General Ledger
# MOVEMENT of the Receivable (Debtors) account between From Date and To Date only
# (same as the "Total" row of the standard General Ledger report, NOT "Opening" or
# "Closing" - opening/old-debt balances are excluded on purpose). It nets every GL
# Entry posted in the period - new invoices (debit) against ANY money credited in the
# same period, whether a Payment Entry or Journal Entry, allocated to an invoice or
# not - so it is the true amount still owed from what happened in this exact period,
# not from outstanding_amount (which only changes once a payment is allocated to a
# specific invoice).
#
# MONEY OUT = Expenses Paid (Expenses form)
#           + Purchase Invoices paid at purchase (Is Paid)
#           + EVERY Payment Entry of type "Pay" (any party: Supplier, Employee, ...),
#             including advances that are not linked to an invoice
#           + Journal Entries that take money out of a Cash/Bank account (salary, etc.).
#             Journal Entries created by the Expenses form are skipped (already counted).

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

# ────────────────────────────────────────────────────────────────
# SETTINGS - change these if your real field names are different
# ────────────────────────────────────────────────────────────────
# Fields inside the child table "Expense Line" (parent: Expenses)
# NOTE: "amount" in Expense Line is a Data field (text), so it is converted
# to a number in the SQL below.
EXPENSE_LINE_ACCOUNT_FIELD = "expense_account"
EXPENSE_LINE_AMOUNT_FIELD = "amount"
EXPENSE_LINE_COST_CENTER_FIELD = "cost_center"

# Field on "Journal Entry Account" that links a row to the Sales Invoice it settles
# (e.g. debiting Bank / crediting Debtors against a specific invoice).
JE_REFERENCE_INVOICE_FIELD = "reference_invoice"
# ────────────────────────────────────────────────────────────────


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.from_date = filters.from_date or today()
	filters.to_date = filters.to_date or filters.from_date
	filters.company = filters.company or frappe.defaults.get_user_default("Company")

	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date"))

	currency = frappe.get_cached_value("Company", filters.company, "default_currency")

	notes = []

	# customer receipts are limited to invoice-linked payments when Cost Center is set
	filters.inv_level = 1 if filters.cost_center else 0
	if filters.inv_level:
		notes.append(
			_("Cost Center filter is on: customer receipts count only payments linked to matching invoices. "
			  "Payments made (Pay) are filtered by the Cost Center saved on the Payment Entry itself.")
		)

	if not frappe.db.exists("Account", {"company": filters.company, "account_type": ["in", ["Cash", "Bank"]]}):
		notes.append(
			_("No account with Account Type Cash or Bank was found, so Journal Entry payments are not counted.")
		)

	if not frappe.db.has_column("Journal Entry Account", JE_REFERENCE_INVOICE_FIELD):
		notes.append(
			_("Field '{0}' was not found on Journal Entry Account, so money received by Journal Entry is "
			  "treated as Unallocated Money.").format(JE_REFERENCE_INVOICE_FIELD)
		)

	f = get_figures(filters)

	columns = get_columns()
	data = get_data(f, currency)
	chart = get_chart(f)
	summary = get_summary(f, filters, currency)
	message = "<br>".join(notes) if notes else None

	return columns, data, message, chart, summary


# ────────────────────────────────────────────────────────────────
# SQL condition builders
# ────────────────────────────────────────────────────────────────
def si_cond(f, date=True):
	c = ["si.docstatus = 1", "si.company = %(company)s"]
	if date:
		c.append("si.posting_date BETWEEN %(from_date)s AND %(to_date)s")
	if f.cost_center:
		c.append(
			"EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii "
			"WHERE sii.parent = si.name AND sii.cost_center = %(cost_center)s)"
		)
	return " AND ".join(c)


def pe_cond(f, payment_type, party_type):
	c = [
		"pe.docstatus = 1",
		f"pe.payment_type = '{payment_type}'",
		f"pe.party_type = '{party_type}'",
		"pe.company = %(company)s",
		"pe.posting_date BETWEEN %(from_date)s AND %(to_date)s",
	]
	return " AND ".join(c)


def pi_cond(f, date=True):
	c = ["pi.docstatus = 1", "pi.company = %(company)s"]
	if date:
		c.append("pi.posting_date BETWEEN %(from_date)s AND %(to_date)s")
	if f.cost_center:
		c.append(
			"EXISTS (SELECT 1 FROM `tabPurchase Invoice Item` pii "
			"WHERE pii.parent = pi.name AND pii.cost_center = %(cost_center)s)"
		)
	return " AND ".join(c)


def exp_cond(f):
	c = [
		"e.docstatus = 1",
		"e.company = %(company)s",
		"e.posting_date BETWEEN %(from_date)s AND %(to_date)s",
	]
	if f.cost_center:
		c.append(f"el.`{EXPENSE_LINE_COST_CENTER_FIELD}` = %(cost_center)s")
	return " AND ".join(c)


# ────────────────────────────────────────────────────────────────
# Data collection
# ────────────────────────────────────────────────────────────────
def get_figures(filters):
	f = frappe._dict()

	# 1) Sales Invoices in the period
	s = frappe.db.sql(
		f"""
		SELECT
			COUNT(*) AS invoices,
			IFNULL(SUM(si.base_grand_total), 0) AS total,
			IFNULL(SUM(CASE WHEN si.is_pos = 1
				THEN si.base_paid_amount - IFNULL(si.base_change_amount, 0) ELSE 0 END), 0) AS pos_cash
		FROM `tabSales Invoice` si
		WHERE {si_cond(filters)}
		""",
		filters,
		as_dict=True,
	)[0]
	f.invoices = s.invoices
	f.sales_total = flt(s.total)
	f.pos_cash = flt(s.pos_cash)

	# 2) Customer receipts linked to invoices: old invoices vs invoices of this period
	r = frappe.db.sql(
		f"""
		SELECT
			IFNULL(SUM(CASE WHEN si.posting_date < %(from_date)s
				THEN per.allocated_amount ELSE 0 END), 0) AS old_debt,
			IFNULL(SUM(CASE WHEN si.posting_date BETWEEN %(from_date)s AND %(to_date)s
				THEN per.allocated_amount ELSE 0 END), 0) AS same_period,
			IFNULL(SUM(per.allocated_amount), 0) AS total_alloc
		FROM `tabPayment Entry` pe
		JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		JOIN `tabSales Invoice` si ON si.name = per.reference_name
		WHERE {pe_cond(filters, 'Receive', 'Customer')}
			AND per.reference_doctype = 'Sales Invoice'
			AND {si_cond(filters, date=False)}
		""",
		filters,
		as_dict=True,
	)[0]
	f.old_debt = flt(r.old_debt)
	f.same_period_pe = flt(r.same_period)

	# 3) Total customer receipts
	if filters.inv_level:
		f.pe_total = flt(r.total_alloc)
	else:
		f.pe_total = flt(
			frappe.db.sql(
				f"""
				SELECT IFNULL(SUM(pe.base_paid_amount), 0)
				FROM `tabPayment Entry` pe
				WHERE {pe_cond(filters, 'Receive', 'Customer')}
				""",
				filters,
			)[0][0]
		)
	f.pe_other = flt(f.pe_total - f.old_debt - f.same_period_pe)

	# 3b) Money received by Journal Entry (e.g. debit Bank / credit Debtors), classified
	# the same way as Payment Entry: by the Sales Invoice it settles, when known.
	je_in_cc = ""
	if filters.cost_center:
		je_in_cc = "AND jea.cost_center = %(cost_center)s"
	ref_ok = frappe.db.has_column("Journal Entry Account", JE_REFERENCE_INVOICE_FIELD)
	ref_col = f"jea.`{JE_REFERENCE_INVOICE_FIELD}`" if ref_ok else "NULL"
	je_in_rows = frappe.db.sql(
		f"""
		SELECT {ref_col} AS invoice, si.posting_date AS inv_date,
			(jea.debit - jea.credit) AS amount
		FROM `tabJournal Entry` je
		JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
		JOIN `tabAccount` acc ON acc.name = jea.account
		LEFT JOIN `tabSales Invoice` si ON si.name = {ref_col}
		WHERE je.docstatus = 1
			AND je.company = %(company)s
			AND je.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND IFNULL(je.is_opening, 'No') != 'Yes'
			AND acc.account_type IN ('Cash', 'Bank')
			AND (jea.debit - jea.credit) > 0
			AND je.name NOT IN (
				SELECT journal_entry FROM `tabExpenses` WHERE IFNULL(journal_entry, '') != ''
			)
			{je_in_cc}
		""",
		filters,
		as_dict=True,
	)
	f.je_old_debt = 0.0
	f.je_same_period = 0.0
	f.je_unallocated = 0.0
	for r in je_in_rows:
		amt = flt(r.amount)
		if r.invoice and r.inv_date:
			if getdate(r.inv_date) < getdate(filters.from_date):
				f.je_old_debt += amt
			else:
				f.je_same_period += amt
		else:
			f.je_unallocated += amt
	f.je_old_debt = flt(f.je_old_debt)
	f.je_same_period = flt(f.je_same_period)
	f.je_unallocated = flt(f.je_unallocated)

	# fold the Journal Entry receipts into the same totals as Payment Entry receipts
	f.old_debt = flt(f.old_debt + f.je_old_debt)
	f.same_period_pe = flt(f.same_period_pe + f.je_same_period)
	f.pe_other = flt(f.pe_other + f.je_unallocated)
	f.pe_total = flt(f.pe_total + f.je_old_debt + f.je_same_period + f.je_unallocated)

	# 4) KPI 2, 3, 5
	f.cash_sales = flt(f.pos_cash + f.same_period_pe)
	f.credit_sales = flt(f.sales_total - f.cash_sales)
	f.cash_in = flt(f.pos_cash + f.pe_total)

	# 5) Expenses (custom doctype "Expenses" + child "Expense Line")
	amount_expr = (
		f"CAST(IFNULL(NULLIF(REPLACE(el.`{EXPENSE_LINE_AMOUNT_FIELD}`, ',', ''), ''), 0) AS DECIMAL(21,6))"
	)
	f.expense_by_account = frappe.db.sql(
		f"""
		SELECT IFNULL(el.`{EXPENSE_LINE_ACCOUNT_FIELD}`, 'Not set') AS account,
			IFNULL(SUM({amount_expr}), 0) AS amount
		FROM `tabExpenses` e
		JOIN `tabExpense Line` el ON el.parent = e.name AND el.parenttype = 'Expenses'
		WHERE {exp_cond(filters)}
		GROUP BY el.`{EXPENSE_LINE_ACCOUNT_FIELD}`
		ORDER BY amount DESC
		""",
		filters,
		as_dict=True,
	)
	f.expenses = flt(sum(flt(x.amount) for x in f.expense_by_account))

	# 6) Purchases
	p = frappe.db.sql(
		f"""
		SELECT
			IFNULL(SUM(pi.base_grand_total), 0) AS total,
			IFNULL(SUM(CASE WHEN pi.is_paid = 1 THEN pi.base_paid_amount ELSE 0 END), 0) AS paid_at_purchase
		FROM `tabPurchase Invoice` pi
		WHERE {pi_cond(filters)}
		""",
		filters,
		as_dict=True,
	)[0]
	f.purchase_total = flt(p.total)
	f.purchase_paid_at_purchase = flt(p.paid_at_purchase)

	# 7) EVERY Payment Entry of type "Pay" (Supplier, Employee, advances, ...)
	pay_cc = ""
	if filters.cost_center and frappe.db.has_column("Payment Entry", "cost_center"):
		pay_cc = "AND pe.cost_center = %(cost_center)s"
	f.pay_rows = frappe.db.sql(
		f"""
		SELECT IFNULL(pe.party_type, 'No party') AS party_type,
			IFNULL(SUM(pe.base_paid_amount), 0) AS amount,
			IFNULL(SUM(pe.unallocated_amount), 0) AS unallocated
		FROM `tabPayment Entry` pe
		WHERE pe.docstatus = 1
			AND pe.payment_type = 'Pay'
			AND pe.company = %(company)s
			AND pe.posting_date BETWEEN %(from_date)s AND %(to_date)s
			{pay_cc}
		GROUP BY pe.party_type
		ORDER BY amount DESC
		""",
		filters,
		as_dict=True,
	)
	f.pay_total = flt(sum(flt(r.amount) for r in f.pay_rows))
	f.pay_unallocated = flt(sum(flt(r.unallocated) for r in f.pay_rows))
	f.purchase_paid = flt(f.purchase_paid_at_purchase + f.pay_total)
	f.purchase_credit = flt(f.purchase_total - f.purchase_paid_at_purchase)

	# 7b) Journal Entries that take money OUT of a Cash/Bank account (e.g. salary).
	# Net per entry (credit - debit on Cash/Bank rows), so transfers between bank and cash = 0.
	# Journal Entries created by the Expenses form are excluded (already in "Expenses Paid").
	je_cc = ""
	if filters.cost_center:
		je_cc = (
			"AND EXISTS (SELECT 1 FROM `tabJournal Entry Account` jc "
			"WHERE jc.parent = je.name AND jc.cost_center = %(cost_center)s)"
		)
	f.je_rows = frappe.db.sql(
		f"""
		SELECT je.name AS name, IFNULL(je.user_remark, '') AS remark,
			SUM(jea.credit - jea.debit) AS amount
		FROM `tabJournal Entry` je
		JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
		JOIN `tabAccount` acc ON acc.name = jea.account
		WHERE je.docstatus = 1
			AND je.company = %(company)s
			AND je.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND IFNULL(je.is_opening, 'No') != 'Yes'
			AND acc.account_type IN ('Cash', 'Bank')
			AND je.name NOT IN (
				SELECT journal_entry FROM `tabExpenses` WHERE IFNULL(journal_entry, '') != ''
			)
			{je_cc}
		GROUP BY je.name, je.user_remark
		HAVING SUM(jea.credit - jea.debit) > 0
		ORDER BY amount DESC
		""",
		filters,
		as_dict=True,
	)
	f.je_out = flt(sum(flt(r.amount) for r in f.je_rows))

	# 7c) Debt remaining today, from the ledger (Accounts Receivable), per customer.
	# balance = debit (new invoices) - credit (any money received, allocated or not).
	ar_cc = ""
	if filters.cost_center:
		ar_cc = "AND gl.cost_center = %(cost_center)s"
	ar_rows = frappe.db.sql(
		f"""
		SELECT gl.party AS customer, SUM(gl.debit - gl.credit) AS balance
		FROM `tabGL Entry` gl
		JOIN `tabAccount` acc ON acc.name = gl.account
		WHERE gl.is_cancelled = 0
			AND gl.company = %(company)s
			AND gl.party_type = 'Customer'
			AND acc.account_type = 'Receivable'
			AND gl.posting_date BETWEEN %(from_date)s AND %(to_date)s
			{ar_cc}
		GROUP BY gl.party
		""",
		filters,
		as_dict=True,
	)
	f.ar_rows = [r for r in ar_rows if round(flt(r.balance), 2) != 0]
	f.ar_owed_today = flt(sum(flt(r.balance) for r in f.ar_rows if flt(r.balance) > 0))
	f.ar_overpaid_today = flt(-sum(flt(r.balance) for r in f.ar_rows if flt(r.balance) < 0))

	# 8) KPI 7 and net
	f.money_out = flt(f.expenses + f.purchase_paid + f.je_out)
	f.net_cash = flt(f.cash_in - f.money_out)

	# 10) Money in by mode of payment
	# NOTE: POS "Cash" rows can include the change given back, so Cash may look
	# slightly higher here than in "Total cash in".
	if filters.inv_level:
		pe_part = f"""
			SELECT pe.mode_of_payment AS mode, per.allocated_amount AS amt
			FROM `tabPayment Entry` pe
			JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
			JOIN `tabSales Invoice` si ON si.name = per.reference_name
			WHERE {pe_cond(filters, 'Receive', 'Customer')}
				AND per.reference_doctype = 'Sales Invoice'
				AND {si_cond(filters, date=False)}
		"""
	else:
		pe_part = f"""
			SELECT pe.mode_of_payment AS mode, pe.base_paid_amount AS amt
			FROM `tabPayment Entry` pe
			WHERE {pe_cond(filters, 'Receive', 'Customer')}
		"""

	f.by_mode = frappe.db.sql(
		f"""
		SELECT IFNULL(t.mode, 'Not set') AS mode, SUM(t.amt) AS amount
		FROM (
			SELECT sip.mode_of_payment AS mode, sip.base_amount AS amt
			FROM `tabSales Invoice Payment` sip
			JOIN `tabSales Invoice` si ON si.name = sip.parent
			WHERE si.is_pos = 1 AND {si_cond(filters)}
			UNION ALL
			{pe_part}
		) t
		GROUP BY t.mode
		ORDER BY amount DESC
		""",
		filters,
		as_dict=True,
	)

	return f


# ────────────────────────────────────────────────────────────────
# Table
# ────────────────────────────────────────────────────────────────
def get_columns():
	return [
		{"fieldname": "item", "label": _("Item"), "fieldtype": "Data", "width": 420},
		{
			"fieldname": "amount",
			"label": _("Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 180,
		},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Data", "hidden": 1, "width": 0},
	]


def get_data(f, currency):
	rows = []

	def header(title):
		rows.append({"item": title, "amount": None, "is_header": 1, "currency": currency})

	def line(item, amount, color=None, bold=0, indent=0):
		rows.append(
			{
				"item": ("    " * indent) + item,
				"amount": flt(amount, 2),
				"currency": currency,
				"color": color,
				"is_bold": bold,
			}
		)

	header(_("1. Sales ({0} invoices)").format(f.invoices))
	line(_("Total sales (cash + credit)"), f.sales_total, "blue", 1)
	line(_("Cash sales (paid at sale + paid same period)"), f.cash_sales, "green", indent=1)
	line(_("Credit sales (still owed)"), f.credit_sales, "orange", indent=1)

	header(_("2. Money received"))
	line(_("Cash from sales (POS)"), f.pos_cash, indent=1)
	line(_("Old debt collected"), f.old_debt, "green", indent=1)
	if f.je_old_debt:
		line(_("of which via Journal Entry"), f.je_old_debt, indent=2)
	line(_("Payments on this period's invoices"), f.same_period_pe, indent=1)
	if f.je_same_period:
		line(_("of which via Journal Entry"), f.je_same_period, indent=2)
	line(_("Unallocated money (not linked to any invoice)"), f.pe_other, "orange", indent=1)
	if f.je_unallocated:
		line(_("of which via Journal Entry"), f.je_unallocated, indent=2)
	line(_("Total cash in"), f.cash_in, "green", 1)
	for m in f.by_mode:
		line(m.mode, m.amount, indent=2)

	header(_("3. Expenses paid (Expenses form)"))
	line(_("Total expenses paid"), f.expenses, "red", 1)
	for e in f.expense_by_account:
		line(e.account, e.amount, indent=2)

	header(_("4. Purchases and payments made"))
	line(_("Total purchases"), f.purchase_total, "blue", 1)
	line(_("Paid at purchase"), f.purchase_paid_at_purchase, indent=1)
	line(_("Payments made (all Payment Entry - Pay)"), f.pay_total, indent=1)
	for r in f.pay_rows:
		line(r.party_type, r.amount, indent=2)
	line(_("of which advances (not linked to an invoice)"), f.pay_unallocated, "orange", indent=2)
	line(_("Purchases on credit (owed to suppliers)"), f.purchase_credit, "orange", indent=1)

	header(_("5. Receivable (movement From Date to To Date, like GL \"Total\" row)"))
	line(_("Still owed (from this period only, excludes old debt)"), f.ar_owed_today, "orange", 1)
	if f.ar_overpaid_today:
		line(_("Overpaid (credit balance)"), f.ar_overpaid_today, "green", 1)

	header(_("6. Journal Entry payments (salary, etc.)"))
	line(_("Total paid by Journal Entry"), f.je_out, "red", 1)
	for r in f.je_rows[:15]:
		label = r.name + (" - " + r.remark.strip()[:40] if r.remark and r.remark.strip() else "")
		line(label, r.amount, indent=2)
	if len(f.je_rows) > 15:
		rest = sum(flt(r.amount) for r in f.je_rows[15:])
		line(_("Other {0} entries").format(len(f.je_rows) - 15), rest, indent=2)

	header(_("7. Money out and net"))
	line(_("Expenses"), f.expenses, indent=1)
	line(_("Purchases and payments paid"), f.purchase_paid, indent=1)
	line(_("Journal Entry payments"), f.je_out, indent=1)
	line(_("Total money out"), f.money_out, "red", 1)
	line(_("Net cash (in - out)"), f.net_cash, "green" if f.net_cash >= 0 else "red", 1)

	return rows


# ────────────────────────────────────────────────────────────────
# Cards (KPIs) and chart
# ────────────────────────────────────────────────────────────────
def get_summary(f, filters, currency):
	def card(label, value, indicator):
		return {
			"value": flt(value, 2),
			"label": label,
			"datatype": "Currency",
			"currency": currency,
			"indicator": indicator,
		}

	is_today = filters.from_date == filters.to_date == today()
	when = _("Today") if is_today else _("Period")

	cards = [
		card(_("{0} Sales").format(when), f.sales_total, "Blue"),
		card(_("Cash Sales"), f.cash_sales, "Green"),
		card(_("Credit Sales"), f.credit_sales, "Orange"),
		card(_("Old Debt Collected"), f.old_debt, "Green"),
		card(_("Unallocated Money"), f.pe_other, "Orange"),
		card(_("Total Cash In"), f.cash_in, "Green"),
		card(_("Expenses Paid"), f.expenses, "Red"),
		card(_("Total Money Out"), f.money_out, "Red"),
		card(_("Net Cash"), f.net_cash, "Green" if f.net_cash >= 0 else "Red"),
		card(_("Receivable"), f.ar_owed_today, "Orange"),
	]

	return cards


def get_chart(f):
	# Two stacked series so money in is green and money out is red
	labels = [
		_("Cash Sales"),
		_("Old Debt"),
		_("Expenses Paid"),
		_("Purchases + Payments"),
		_("Journal Entry"),
	]
	money_in = [f.cash_sales, f.old_debt, 0, 0, 0]
	money_out = [0, 0, f.expenses, f.purchase_paid, f.je_out]
	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Money In"), "values": [flt(v, 2) for v in money_in]},
				{"name": _("Money Out"), "values": [flt(v, 2) for v in money_out]},
			],
		},
		"type": "bar",
		"colors": ["#1b7f5c", "#c0392b"],
		"barOptions": {"stacked": 1},
		"fieldtype": "Currency",
	}
