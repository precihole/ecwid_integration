# Copyright (c) 2026, Precihole Sports Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.integrations.utils import make_get_request
from frappe.utils import nowdate, add_days


class EcwidLog(Document):
	def before_save(doc):
		try:
			settings = frappe.get_single("Ecwid Settings")
			ECWID_TOKEN = settings.get_password("secret_token")
			store_id = settings.get("store_id")
			default_price_list = settings.get("default_price_list")
			default_customer_group = settings.get("default_customer_group")
			# 1) Read details payload
			if doc.details and not doc.reference_name:
				order = ecwid_get_order(store_id, doc.orderid, ECWID_TOKEN)
				doc.ecwid_order = str(order)
				# 4) Decide tax category from billing state
				bp = order.get("billingPerson") or {}
				state = (bp.get("stateOrProvinceName") or bp.get("stateOrProvinceCode") or "").strip()
				tax = "Instate" if state == "Maharashtra" else "Outstate"
				
				# 5) Customer
				customer_name = get_or_create_customer(order, tax,default_price_list,default_customer_group)
				
				# 6) Addresses
				shipping_person = order.get("shippingPerson") or {}
				billing_person = order.get("billingPerson") or {}
				
				# If billing == shipping, mark billing as shipping too
				same = (billing_person.get("street") == shipping_person.get("street") and billing_person.get("city") == shipping_person.get("city") and billing_person.get("postalCode") == shipping_person.get("postalCode") and (billing_person.get("stateOrProvinceName") or billing_person.get("stateOrProvinceCode")) == (shipping_person.get("stateOrProvinceName") or shipping_person.get("stateOrProvinceCode")))
				billing_address = get_or_create_address(customer_name, billing_person, "Billing", tax, 1 if same else 0,order)
				shipping_address = billing_address if same else get_or_create_address(customer_name, shipping_person, "Shipping", tax, 1)
				
				# 7) Sales Order
				so_name = make_sales_order(order, customer_name, billing_address, shipping_address, tax)
				doc.reference_doctype = "Sales Order"
				doc.reference_name = so_name
				doc.status = "Completed"
		except Exception as e:
			doc.status = "Failed"
			doc.error = str(e)

@frappe.whitelist()
#fetch ecwid order details
def ecwid_get_order(store_id, order_id, token):
	url = f"https://app.ecwid.com/api/v3/{store_id}/orders/{order_id}"
	headers = {"Authorization": f"Bearer {token}"}
	return make_get_request(url, headers=headers)
#get_or_create_customer
def get_or_create_customer(order, tax,default_price_list,default_customer_group):
	email = (order.get("email") or "").strip()
	bp = order.get("billingPerson") or {}

	cust_name = (bp.get("name") or "").strip()
	if not cust_name:
		fn = (bp.get("firstName") or "").strip()
		ln = (bp.get("lastName") or "").strip()
		cust_name = (fn + " " + ln).strip()

	if not cust_name:
		cust_name = email or "Ecwid Customer"

	phone = (bp.get("phone") or "").strip()
	state = (bp.get("stateOrProvinceName") or bp.get("stateOrProvinceCode") or "").strip()

	# Find existing customer by email first
	customer_name = None
	if email:
		customer_name = frappe.db.get_value("Customer", {"email_id": email}, "name")

	# Fallback by customer_name
	if not customer_name:
		customer_name = frappe.db.get_value("Customer", {"customer_name": cust_name}, "name")

	# Create if missing
	if not customer_name:
		cust = frappe.get_doc({
			"doctype": "Customer",
			"customer_name": cust_name,
			"customer_type": "Individual",
			"customer_group": default_customer_group,
			"default_currency": "INR",
			"default_price_list": default_price_list,
			"tax_category": tax,
			"territory": state or "India"
		}).insert(ignore_permissions=True)
		customer_name = cust.name

		# Contact
		if email or phone:
			contact = frappe.get_doc({
				"doctype": "Contact",
				"first_name": cust_name,
				"is_primary_contact": 1,
				"email_ids": [{"email_id": email, "is_primary": 1}] if email else [],
				"phone_nos": [{"phone": phone, "is_primary_mobile_no": 1}] if phone else [],
				"links": [{"link_doctype": "Customer", "link_name": customer_name}]
			}).insert(ignore_permissions=True)

			frappe.db.set_value("Customer", customer_name, {
				"customer_primary_contact": contact.name,
				"mobile_no": phone,
				"email_id": email
			}, update_modified=False)

	return customer_name
def get_or_create_address(customer_name, person, addr_type, tax, make_shipping_flag,order):
	# addr_type: "Billing" / "Shipping"
	# make_shipping_flag: set is_shipping_address=1 for billing if same etc.
	if not person:
		return None

	title = customer_name
	existing = frappe.db.get_value(
		"Address",
		{"address_title": title, "address_type": addr_type},
		"name"
	)
	if existing:
		return existing

	addr = frappe.get_doc({
		"doctype": "Address",
		"address_title": title,
		"address_type": addr_type,
		"address_line1": (person.get("street") or ""),
		"city": (person.get("city") or ""),
		"state": (person.get("stateOrProvinceName") or person.get("stateOrProvinceCode") or ""),
		"country": (person.get("countryName") or "India"),
		"pincode": (person.get("postalCode") or ""),
		"phone": (person.get("phone") or ""),
		"email_id": (order.get("email") or ""),
		"tax_category": tax,
		"is_primary_address": 1 if addr_type == "Billing" else 0,
		"is_shipping_address": 1 if make_shipping_flag else 0,
		"links": [{"link_doctype": "Customer", "link_name": customer_name}]
	}).insert(ignore_permissions=True)

	return addr.name

def make_sales_order(order, customer_name, billing_address, shipping_address, tax):
	order_id = order.get("id") or order.get("orderNumber")

	# prevent duplicates
	existing = frappe.db.get_value(
		"Sales Order",
		{"po_no": str(order_id), "docstatus": ["!=", 2]},
		"name"
	)
	if existing:
		return existing

	so_items = []
	for it in (order.get("items") or []):
		item_code = (it.get("sku") or "").strip()
		if not item_code:
			# if no SKU, you can fallback to a mapped item or productId logic
			item_code = (it.get("name") or "").strip()

		so_items.append({
			"item_code": item_code,
			"qty": it.get("quantity") or 1,
			"rate": it.get("price") or 0,
			"description": it.get("name") or "",
			"uom": "Nos"
		})

	if not so_items:
		frappe.throw("No items found in Ecwid order {0}".format(order_id))

	so = frappe.get_doc({
		"doctype": "Sales Order",
		"customer": customer_name,
		"order_type": "Online Sales",
		"currency": "INR",
		"delivery_date":add_days(nowdate(), 3),
		"po_date":nowdate(),
		"price_list_currency": "INR",
		"selling_price_list": "Job-Work",
		"customer_address": billing_address,
		"business_category_c":"Local",
		"shipping_address_name": shipping_address or billing_address,
		"po_no": str(order_id),
		"items": so_items
	}).insert(ignore_permissions=True)

	# taxes
	if tax == "Instate":
		so.append("taxes", {"charge_type": "On Net Total", "account_head": "Output SGST - PMTPL", "description": "Output SGST"})
		so.append("taxes", {"charge_type": "On Net Total", "account_head": "Output CGST - PMTPL", "description": "Output CGST"})
	else:
		so.append("taxes", {"charge_type": "On Net Total", "account_head": "Output IGST - PMTPL", "description": "Output IGST"})

	so.save(ignore_permissions=True)
	return so.name