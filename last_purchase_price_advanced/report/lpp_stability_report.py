# -*- coding: utf-8 -*-
from itertools import groupby

from odoo import api, fields, models


class ReportVendorPriceStability(models.AbstractModel):
    _name = 'report.last_purchase_price_advanced.report_vendor_stability'
    _description = 'Vendor Price Stability PDF Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizards = self.env['lpp.stability.wizard'].browse(docids)
        reports = []
        for wizard in wizards:
            rows = wizard._get_stability_rows()
            groups = []
            for (company, partner), items in groupby(
                    rows, key=lambda r: (r['company'], r['partner'])):
                items = list(items)
                groups.append({
                    'company': company,
                    'partner': partner,
                    'rows': items,
                    'nbr': sum(i['nbr'] for i in items),
                    'avg_score': round(sum(i['score'] for i in items) / len(items), 1),
                    'amount': sum(i['amount'] for i in items),
                    'currency': items[0]['currency'],
                })
            reports.append({
                'wizard': wizard,
                'groups': groups,
                'summary': wizard._get_summary(rows),
                'filters': wizard._get_filter_labels(),
                'labels': wizard._get_label_maps(),
            })
        lang = self.env['res.lang']._lang_get(self.env.lang or self.env.user.lang)
        return {
            'doc_ids': docids,
            'doc_model': 'lpp.stability.wizard',
            'docs': wizards,
            'reports': reports,
            'price_digits': self.env['decimal.precision'].precision_get('Product Price'),
            'is_rtl': bool(lang and lang.direction == 'rtl'),
            'printed_on': fields.Datetime.now(),
        }
