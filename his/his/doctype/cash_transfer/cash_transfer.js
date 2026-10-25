// Copyright (c) 2023, Rasiin Tech and contributors
// For license information, please see license.txt

// frappe.ui.form.on('Cash Transfer', {
// 	refresh: function(frm) {
// 		if(frm.is_new()){
// 			frm.set_value("username",frappe.session.user)
// 			// alert(frappe.session.full_name)
// 		}
// 	}
// });


frappe.ui.form.on('Cash Transfer', {
	refresh: function(frm) {
		if(frm.is_new()){
			frm.set_value("username",frappe.session.user)
			// alert(frappe.session.full_name)
		}
	},
    from_account: function(frm) {
        fetch_from_account_balance(frm);
    },

    date: function(frm) {
        if (frm.doc.from_account) {
            fetch_from_account_balance(frm);
        }
    }
});

function fetch_from_account_balance(frm) {
    if (!frm.doc.from_account || !frm.doc.date) {
        frm.set_value('balance', 0);
        return;
    }

    frm.call({
        method: 'get_from_account_balance',
        doc: frm.doc,
        callback: function(r) {
            if (!r.exc) {
                frm.set_value('balance', r.message || 0);
            }
        }
    });
}
