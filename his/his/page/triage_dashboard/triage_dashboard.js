frappe.pages['triage-dashboard'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Triage Dashboard',
        single_column: true
    });
    new TriageDashboard(page);
};

class TriageDashboard {
    constructor(page) {
        this.page = page;
        this.make();
        this.refresh();
        this.setup_realtime();
        this.setup_auto_refresh();
    }

    make() {
        this.wrapper = $(`
            <div class="triage-dashboard" style="padding: 10px;">
                <div style="display:flex; gap:16px; margin-bottom:24px;">
                    <div style="flex:1; padding:24px; border-radius:10px; background:linear-gradient(135deg,#ff4d4f,#cf1322); color:#fff; text-align:center; box-shadow:0 4px 12px rgba(0,0,0,0.15);">
                        <div style="font-size:2.5rem; font-weight:bold;" id="count-red">0</div>
                        <div style="font-size:1rem; letter-spacing:1px; text-transform:uppercase;">🔴 Red - Degdeg</div>
                    </div>
                    <div style="flex:1; padding:24px; border-radius:10px; background:linear-gradient(135deg,#fadb14,#d4b106); color:#000; text-align:center; box-shadow:0 4px 12px rgba(0,0,0,0.15);">
                        <div style="font-size:2.5rem; font-weight:bold;" id="count-yellow">0</div>
                        <div style="font-size:1rem; letter-spacing:1px; text-transform:uppercase;">🟡 Yellow - Sugitaan</div>
                    </div>
                    <div style="flex:1; padding:24px; border-radius:10px; background:linear-gradient(135deg,#52c41a,#389e0d); color:#fff; text-align:center; box-shadow:0 4px 12px rgba(0,0,0,0.15);">
                        <div style="font-size:2.5rem; font-weight:bold;" id="count-green">0</div>
                        <div style="font-size:1rem; letter-spacing:1px; text-transform:uppercase;">🟢 Green - Degan</div>
                    </div>
                </div>
                <div style="background:#fff; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.08); overflow:hidden;">
                    <table class="table" id="triage-table" style="margin-bottom:0;">
                        <thead style="background:#fafafa;">
                            <tr>
                                <th>Patient</th><th>Triage</th><th>RR</th><th>Pulse</th>
                                <th>BP (Sys)</th><th>Temp</th><th>Action</th>
                            </tr>
                        </thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>
        `).appendTo(this.page.body);

        this.wrapper.on('click', '.send-to-emergency-btn', (e) => {
            const $btn = $(e.currentTarget);
            const patient = $btn.data('patient');
            const triage_level = $btn.data('triage');

            frappe.confirm(
                `Ma hubtaa inaad u gudbinayso <b>${patient}</b> Emergency (${triage_level})?`,
                () => {
                    $btn.prop('disabled', true).text('...');
                    frappe.call({
                        method: "his.api.triage_dashboard.send_to_emergency",
                        args: { patient, triage_level },
                        callback: (r) => {
                            if (r.message) {
                                frappe.show_alert({
                                    message: `Emergency la abuuray: ${r.message.emergency}`,
                                    indicator: 'green'
                                });
                                $btn.replaceWith(`<span style="color:#52c41a; font-weight:bold;">✓ ${r.message.emergency}</span>`);
                            }
                        },
                        error: () => {
                            $btn.prop('disabled', false).text('Gudbi Emergency');
                        }
                    });
                }
            );
        });
    }

    refresh() {
        frappe.call({
            method: "his.api.triage_dashboard.get_triage_dashboard",
            callback: (r) => {
                if (r.message) this.render(r.message);
            }
        });
    }

    render(data) {
        $('#count-red').text(data.counts.Red || 0);
        $('#count-yellow').text(data.counts.Yellow || 0);
        $('#count-green').text(data.counts.Green || 0);

        const colors = { Red: '#ff4d4f', Yellow: '#fadb14', Green: '#52c41a' };
        const textColors = { Red: '#fff', Yellow: '#000', Green: '#fff' };
        const rowBg = { Red: '#fff1f0', Yellow: '#feffe6', Green: '#f6ffed' };

        const rows = data.rows.map(row => `
            <tr style="background:${rowBg[row.triage_level]};">
                <td style="font-weight:500;">${row.patient_name || row.patient}</td>
                <td>
                    <span style="background:${colors[row.triage_level]}; color:${textColors[row.triage_level]}; padding:3px 12px; border-radius:12px; font-weight:bold; font-size:0.8rem;">
                        ${row.triage_level}
                    </span>
                </td>
                <td>${row.respiratory_rate ?? '-'}</td>
                <td>${row.pulse ?? '-'}</td>
                <td>${row.bp_systolic ?? '-'}</td>
                <td>${row.temperature ?? '-'}</td>
                <td>
                    ${row.triage_level === 'Red' ? `
                        <button class="btn btn-xs btn-danger send-to-emergency-btn"
                            data-patient="${row.patient}" data-triage="${row.triage_level}">
                            Gudbi Emergency
                        </button>
                    ` : ''}
                </td>
            </tr>
        `).join('');
        $('#triage-table tbody').html(rows);
    }

    setup_realtime() {
        frappe.realtime.on('triage_dashboard_update', () => this.refresh());
    }

    setup_auto_refresh() {
        this.interval = setInterval(() => this.refresh(), 30000);
    }
}