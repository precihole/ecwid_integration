import frappe

@frappe.whitelist()
def create_ecwid_order():
    payload = dict(frappe.form_dict) if frappe.form_dict else {}

    raw_data = payload.get("data")  # can be dict OR string OR None

    orderId = None

    # ✅ Case 1: data is already a dict
    if isinstance(raw_data, dict):
        orderId = raw_data.get("orderId")

    # ✅ Case 2: data is a string (sometimes broken JSON with comments)
    elif isinstance(raw_data, str):
        # remove JS comments (anything after // on each line)
        cleaned_lines = []
        for line in raw_data.splitlines():
            if "//" in line:
                line = line.split("//", 1)[0]
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines)

        # extract orderId in either "orderId":"X" or 'orderId':'X'
        # Try double-quote style first
        key = '"orderId"'
        idx = cleaned.find(key)
        if idx != -1:
            after = cleaned[idx + len(key):]
            colon = after.find(":")
            if colon != -1:
                after = after[colon + 1:].lstrip()
                if after.startswith('"'):
                    after = after[1:]
                    endq = after.find('"')
                    if endq != -1:
                        orderId = after[:endq]

        # Try single-quote style if still not found
        if not orderId:
            key = "'orderId'"
            idx = cleaned.find(key)
            if idx != -1:
                after = cleaned[idx + len(key):]
                colon = after.find(":")
                if colon != -1:
                    after = after[colon + 1:].lstrip()
                    if after.startswith("'"):
                        after = after[1:]
                        endq = after.find("'")
                        if endq != -1:
                            orderId = after[:endq]

    # Save log
    doc = frappe.get_doc({
        "doctype": "Ecwid Log",
        "orderid": orderId or payload.get("entityId"),
        "details": str(payload),  # will store dict nicely
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.response["message"] = {"orderId": orderId}