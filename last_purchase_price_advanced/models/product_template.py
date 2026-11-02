# -*- coding: utf-8 -*-
from odoo import _, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def action_lpp_price_stability(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'last_purchase_price_advanced.action_lpp_vendor_price_report')
        action.update({
            'name': _('Price Stability: %s', self.display_name),
            'domain': [('product_tmpl_id', '=', self.id)],
            'context': {
                'search_default_group_partner': 1,
                'pivot_row_groupby': ['partner_id'],
                'pivot_column_groupby': ['date:quarter'],
                'graph_groupbys': ['date:month', 'partner_id'],
            },
        })
        return action
