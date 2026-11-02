# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.tools import create_index, float_compare, float_is_zero, float_round

LPP_SIGNALS = [
    ('new', 'No History'),
    ('up', 'Price Up'),
    ('down', 'Price Down'),
    ('same', 'Unchanged'),
]

# One row per (company, product[, vendor]) and per historical order, ranked
# by confirmation date. Only the two most recent orders are kept: the first
# one that is not the line's own order is the "last price".
_LPP_HISTORY_QUERY = """
    WITH hist AS (
        SELECT DISTINCT ON (po.company_id, pol.product_id,
                            rp.commercial_partner_id, po.id)
               po.company_id,
               pol.product_id,
               rp.commercial_partner_id                 AS vendor_id,
               po.id                                    AS order_id,
               po.partner_id                            AS partner_id,
               pol.id                                   AS line_id,
               pol.price_unit                           AS price_unit,
               pol.product_uom_id                       AS uom_id,
               po.currency_id                           AS currency_id,
               po.currency_rate                         AS currency_rate,
               COALESCE(po.date_approve, po.date_order) AS ref_date
          FROM purchase_order_line pol
          JOIN purchase_order po ON po.id = pol.order_id
          JOIN res_partner rp ON rp.id = po.partner_id
         WHERE po.state = 'purchase'
           AND pol.display_type IS NULL
           AND pol.product_qty > 0
           AND pol.price_unit > 0
           AND po.company_id = ANY(%(company_ids)s)
           AND pol.product_id = ANY(%(product_ids)s)
           {vendor_clause}
      ORDER BY po.company_id, pol.product_id, rp.commercial_partner_id,
               po.id, pol.id DESC
    ), ranked AS (
        SELECT hist.*,
               ROW_NUMBER() OVER (
                   PARTITION BY {partition}
                   ORDER BY ref_date DESC, order_id DESC
               ) AS rn
          FROM hist
    )
    SELECT company_id, product_id, vendor_id, order_id, partner_id, line_id,
           price_unit, uom_id, currency_id, currency_rate, ref_date
      FROM ranked
     WHERE rn <= 2
  ORDER BY rn
"""


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    lpp_enabled = fields.Boolean(
        related='order_id.company_id.lpp_tracking_enabled',
        string='Last Price Tracking Enabled')
    lpp_last_line_id = fields.Many2one(
        'purchase.order.line', string='Last Purchase Line',
        compute='_compute_lpp_values')
    lpp_last_order_id = fields.Many2one(
        'purchase.order', string='Last Purchase Order',
        compute='_compute_lpp_values')
    lpp_last_partner_id = fields.Many2one(
        'res.partner', string='Last Vendor',
        compute='_compute_lpp_values')
    lpp_last_date = fields.Datetime(
        string='Last Purchase Date', compute='_compute_lpp_values')
    lpp_last_price_original = fields.Float(
        string='Last Price (Original)', digits='Product Price',
        compute='_compute_lpp_values',
        help='Unit price as recorded on the last confirmed purchase, in its '
             'own currency and unit of measure.')
    lpp_last_currency_id = fields.Many2one(
        'res.currency', string='Last Price Currency',
        compute='_compute_lpp_values')
    lpp_last_uom_id = fields.Many2one(
        'uom.uom', string='Last Price UoM',
        compute='_compute_lpp_values')
    lpp_last_currency_rate = fields.Float(
        string='Historical Currency Rate', digits=(16, 6),
        compute='_compute_lpp_values',
        help='Rate between the company currency and the currency of the last '
             'purchase, as applied on that order.')
    lpp_last_price = fields.Float(
        string='Last Price', digits='Product Price',
        compute='_compute_lpp_values',
        help='Last confirmed purchase price, converted to the unit of measure '
             'and the currency of this line.')
    lpp_price_variance = fields.Float(
        string='Variance (%)', digits=(16, 2),
        compute='_compute_lpp_values',
        help='Relative difference between the unit price of this line and '
             'the normalized last purchase price.')
    lpp_price_signal = fields.Selection(
        LPP_SIGNALS, string='Price Signal',
        compute='_compute_lpp_values')

    def init(self):
        super().init()
        create_index(
            self.env.cr, 'purchase_order_line_lpp_product_order_idx',
            self._table, ['product_id', 'order_id'],
            where='display_type IS NULL')

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    def _lpp_empty_values(self):
        return {
            'lpp_last_line_id': False,
            'lpp_last_order_id': False,
            'lpp_last_partner_id': False,
            'lpp_last_date': False,
            'lpp_last_price_original': 0.0,
            'lpp_last_currency_id': False,
            'lpp_last_uom_id': False,
            'lpp_last_currency_rate': 0.0,
            'lpp_last_price': 0.0,
            'lpp_price_variance': 0.0,
            'lpp_price_signal': False,
        }

    def _lpp_is_eligible(self):
        self.ensure_one()
        return bool(
            not self.display_type
            and self.product_id
            and self.order_id.company_id.lpp_tracking_enabled
        )

    def _lpp_history_key(self):
        self.ensure_one()
        company = self.order_id.company_id
        key = (company.id, self.product_id.id)
        if company.lpp_lookup_scope == 'vendor':
            key += (self.order_id.partner_id.commercial_partner_id.id,)
        return key

    @api.model
    def _lpp_fetch_history(self, scope, company_ids, product_ids, vendor_ids):
        """Return {key: [row, row]} with the two most recent confirmed orders
        for every requested key, in a single query."""
        if not company_ids or not product_ids:
            return {}
        self.env['purchase.order.line'].flush_model([
            'order_id', 'product_id', 'product_qty', 'price_unit',
            'product_uom_id', 'display_type'])
        self.env['purchase.order'].flush_model([
            'state', 'company_id', 'partner_id', 'currency_id',
            'currency_rate', 'date_order', 'date_approve'])
        self.env['res.partner'].flush_model(['commercial_partner_id'])

        params = {
            'company_ids': list(company_ids),
            'product_ids': list(product_ids),
        }
        if scope == 'vendor':
            partition = 'company_id, product_id, vendor_id'
            vendor_clause = 'AND rp.commercial_partner_id = ANY(%(vendor_ids)s)'
            params['vendor_ids'] = list(vendor_ids)
        else:
            partition = 'company_id, product_id'
            vendor_clause = ''
        query = _LPP_HISTORY_QUERY.format(
            partition=partition, vendor_clause=vendor_clause)
        self.env.cr.execute(query, params)

        history = defaultdict(list)
        for row in self.env.cr.dictfetchall():
            key = (row['company_id'], row['product_id'])
            if scope == 'vendor':
                key += (row['vendor_id'],)
            history[key].append(row)
        return history

    def _lpp_normalize_price(self, row, uom_by_id):
        """Convert a historical price to this line's currency and UoM.

        Same currency: the raw price is used as is (no rate round-trip).
        Other currency: historical price -> company currency with the rate
        stored on the historical order, then -> this order's currency with
        the rate stored on this order. Rounding happens only once, at the
        very end, with the 'Product Price' precision."""
        self.ensure_one()
        price = float(row['price_unit'])
        order = self.order_id
        if row['currency_id'] != order.currency_id.id:
            hist_rate = float(row['currency_rate'] or 1.0)
            current_rate = float(order.currency_rate or 1.0)
            price = price / hist_rate * current_rate
        src_uom = uom_by_id.get(row['uom_id'])
        if src_uom and self.product_uom_id and src_uom != self.product_uom_id:
            price = src_uom._compute_price(price, self.product_uom_id)
        return price

    @api.depends(
        'display_type', 'product_id', 'product_uom_id', 'price_unit',
        'order_id.partner_id', 'order_id.currency_id',
        'order_id.currency_rate', 'order_id.company_id',
        'order_id.company_id.lpp_tracking_enabled',
        'order_id.company_id.lpp_lookup_scope',
        'order_id.company_id.lpp_neutral_band')
    def _compute_lpp_values(self):
        empty = self._lpp_empty_values()
        eligible = self.browse()
        for line in self:
            if line._lpp_is_eligible():
                eligible |= line
            else:
                line.update(empty)
        if not eligible:
            return

        # Group the lookups by scope (at most two queries, one per scope).
        requests = defaultdict(lambda: (set(), set(), set()))
        for line in eligible:
            company = line.order_id.company_id
            companies, products, vendors = requests[company.lpp_lookup_scope]
            companies.add(company.id)
            products.add(line.product_id.id)
            vendors.add(line.order_id.partner_id.commercial_partner_id.id)

        history = {}
        for scope, (companies, products, vendors) in requests.items():
            history.update(self._lpp_fetch_history(
                scope, companies, products, vendors))

        uom_ids = {row['uom_id'] for rows in history.values() for row in rows}
        uom_by_id = {uom.id: uom for uom in self.env['uom.uom'].browse(uom_ids)}
        price_digits = self.env['decimal.precision'].precision_get('Product Price')

        for line in eligible:
            own_order_id = line.order_id._origin.id
            row = next(
                (r for r in history.get(line._lpp_history_key(), [])
                 if r['order_id'] != own_order_id),
                None)
            if not row:
                line.update(dict(empty, lpp_price_signal='new'))
                continue

            last_price = float_round(
                line._lpp_normalize_price(row, uom_by_id),
                precision_digits=price_digits)
            current_price = line.price_unit
            band = line.order_id.company_id.lpp_neutral_band or 0.0
            if float_is_zero(last_price, precision_digits=price_digits):
                variance, signal = 0.0, 'new'
            else:
                variance = float_round(
                    (current_price - last_price) / last_price * 100.0,
                    precision_digits=2)
                cmp = float_compare(current_price, last_price,
                                    precision_digits=price_digits)
                if cmp == 0 or (band and float_compare(
                        abs(variance), band, precision_digits=2) <= 0):
                    signal = 'same'
                else:
                    signal = 'up' if cmp > 0 else 'down'
            line.update({
                'lpp_last_line_id': row['line_id'],
                'lpp_last_order_id': row['order_id'],
                'lpp_last_partner_id': row['partner_id'],
                'lpp_last_date': row['ref_date'],
                'lpp_last_price_original': float(row['price_unit']),
                'lpp_last_currency_id': row['currency_id'],
                'lpp_last_uom_id': row['uom_id'],
                'lpp_last_currency_rate': float(row['currency_rate'] or 1.0),
                'lpp_last_price': last_price,
                'lpp_price_variance': variance,
                'lpp_price_signal': signal,
            })

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_lpp_price_stability(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'last_purchase_price_advanced.action_lpp_vendor_price_report')
        domain = [('product_id', '=', self.product_id.id)]
        if self.order_id.company_id.lpp_lookup_scope == 'vendor':
            domain.append(('partner_id', '=',
                           self.order_id.partner_id.commercial_partner_id.id))
        action.update({
            'name': _('Price Stability: %s', self.product_id.display_name),
            'domain': domain,
            'views': [
                (self.env.ref('last_purchase_price_advanced.lpp_vendor_price_report_view_tree').id, 'list'),
                (self.env.ref('last_purchase_price_advanced.lpp_vendor_price_report_view_graph').id, 'graph'),
                (self.env.ref('last_purchase_price_advanced.lpp_vendor_price_report_view_pivot').id, 'pivot'),
            ],
            'context': {'search_default_group_partner': 1},
        })
        return action
