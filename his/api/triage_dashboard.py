import frappe
from frappe.utils import nowdate, flt


def calculate_triage(respiratory_rate, pulse, bp_systolic, temperature):
    """Isla mantiqda scoring ee server script-ka Vital Signs isticmaalo."""
    score = 0
    single_critical = False

    if respiratory_rate not in (None, ""):
        rr = flt(respiratory_rate)
        if rr <= 8:
            score += 3
            single_critical = True
        elif rr <= 11:
            score += 1
        elif rr <= 20:
            pass
        elif rr <= 24:
            score += 2
        else:
            score += 3
            single_critical = True

    if pulse not in (None, ""):
        p = flt(pulse)
        if p <= 40:
            score += 3
            single_critical = True
        elif p <= 50:
            score += 1
        elif p <= 90:
            pass
        elif p <= 110:
            score += 1
        elif p <= 130:
            score += 2
        else:
            score += 3
            single_critical = True

    if bp_systolic not in (None, ""):
        sbp = flt(bp_systolic)
        if sbp <= 90:
            score += 3
            single_critical = True
        elif sbp <= 100:
            score += 2
        elif sbp <= 110:
            score += 1
        elif sbp <= 219:
            pass
        else:
            score += 3
            single_critical = True

    if temperature not in (None, ""):
        t = flt(temperature)
        if t <= 35.0:
            score += 3
            single_critical = True
        elif t <= 36.0:
            score += 1
        elif t <= 38.0:
            pass
        elif t <= 39.0:
            score += 1
        else:
            score += 2

    if single_critical or score >= 7:
        return "Red"
    elif score >= 5:
        return "Yellow"
    else:
        return "Green"


@frappe.whitelist()
def get_triage_dashboard():
    today = nowdate()
    vitals = frappe.get_all(
        "Vital Signs",
        filters={"creation": ["between", [f"{today} 00:00:00", f"{today} 23:59:59"]]},
        fields=["name", "patient", "patient_name", "respiratory_rate",
                "pulse", "bp_systolic", "temperature"],
        order_by="creation desc"
    )

    seen_patients = set()
    rows = []
    counts = {"Red": 0, "Yellow": 0, "Green": 0}

    for v in vitals:
        if v.patient in seen_patients:
            continue
        seen_patients.add(v.patient)

        triage_level = calculate_triage(
            v.respiratory_rate, v.pulse, v.bp_systolic, v.temperature
        )
        counts[triage_level] += 1

        rows.append({
            "patient": v.patient,
            "patient_name": v.patient_name,
            "triage_level": triage_level,
            "respiratory_rate": v.respiratory_rate,
            "pulse": v.pulse,
            "bp_systolic": v.bp_systolic,
            "temperature": v.temperature,
        })

    priority = {"Red": 0, "Yellow": 1, "Green": 2}
    rows.sort(key=lambda r: priority.get(r["triage_level"], 3))

    return {"counts": counts, "rows": rows}


@frappe.whitelist()
def send_to_emergency(patient, triage_level):
    """Abuur Emergency document cusub oo leh patient + triage_level"""
    doc = frappe.get_doc({
        "doctype": "Emergency",
        "patient": patient,
        "triage_level": triage_level,
        "practitioner": "Emergency"
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"status": "created", "emergency": doc.name}
