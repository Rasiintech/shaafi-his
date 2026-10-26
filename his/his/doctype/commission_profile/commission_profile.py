# Copyright (c) 2026, Rasiin Tech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_link_to_form


def _norm(v):
    return (v or "").strip()


def _so(v):
    v = _norm(v)
    return "Any" if (not v or v.lower() == "any") else v


class CommissionProfile(Document):
    def validate(self):
        self.validate_one_enabled_profile()
        rows = self._rule_rows()
        self.validate_no_duplicate_rules(rows)
        self.validate_surgery_requester_rules(rows)
        self.warn_stackable(rows)

    # ------------------------------------------------------------
    def _rule_rows(self):
        """Rows of the Commission Profile Rule table, whatever the table field is called."""
        for df in self.meta.get_table_fields():
            if df.options == "Commission Profile Rule":
                return self.get(df.fieldname) or []
        return []

    # 1) Only one enabled profile per doctor
    def validate_one_enabled_profile(self):
        if not self.get("practitioner") or cint(self.get("disabled")):
            return
        other = frappe.db.get_value(
            "Commission Profile",
            {"practitioner": self.practitioner, "disabled": 0, "name": ["!=", self.name]},
            "name",
        )
        if other:
            frappe.throw(
                _("{0} already has an enabled Commission Profile: {1}. Edit that one, or disable it first.")
                .format(frappe.bold(self.practitioner), get_link_to_form("Commission Profile", other)),
                title=_("Duplicate Profile"),
            )

    # 2) No duplicate rule rows
    def validate_no_duplicate_rules(self, rows):
        seen = {}
        for r in rows:
            key = (_norm(r.item_group), _norm(r.rule_type), _norm(r.applies_when), _so(r.get("source_order")))
            if key in seen:
                frappe.throw(
                    _("Rows {0} and {1} are the same rule ({2} · {3} · {4} · {5}). Delete one of them.")
                    .format(seen[key], r.idx, *key),
                    title=_("Duplicate Rule"),
                )
            seen[key] = r.idx

    # 3) Surgery: do not mix "Requester" with "Requester Only" / "Requester = Performer"
    def validate_surgery_requester_rules(self, rows):
        by_group = {}
        for r in rows:
            if _norm(r.rule_type) == "Procedure Percent":
                by_group.setdefault(_norm(r.item_group), {})[_norm(r.applies_when)] = r.idx

        for ig, whens in by_group.items():
            if "Requester" in whens and ({"Requester Only", "Requester = Performer"} & set(whens)):
                mixed = [str(whens[w]) for w in ("Requester", "Requester Only", "Requester = Performer") if w in whens]
                frappe.throw(
                    _("Item Group {0}: rows {1} mix 'Requester' with 'Requester Only' / 'Requester = Performer'. "
                      "Use one 'Requester' row, or the two separate rows, not both.")
                    .format(frappe.bold(ig), ", ".join(mixed)),
                    title=_("Overlapping Surgery Rules"),
                )

    # 4) Stackable: allowed, but remind
    def warn_stackable(self, rows):
        stacked = [str(r.idx) for r in rows if cint(r.get("stackable"))]
        if stacked:
            frappe.msgprint(
                _("Stackable is ticked on rows {0}. These rows pay on top of the doctor's other matching rules "
                  "(e.g. owner % + requester %). Untick it unless that is intended.").format(", ".join(stacked)),
                title=_("Stackable Rules"),
                indicator="orange",
            )