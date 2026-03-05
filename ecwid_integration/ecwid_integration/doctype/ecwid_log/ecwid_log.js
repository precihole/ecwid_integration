// Copyright (c) 2026, Precihole Sports Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Ecwid Log", {
	refresh(frm) {

		// Add Retry Button
		frm.add_custom_button(__('Retry'), function () {

			frm.save();
			
		});
	},
});