# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools
from odoo.tools import SQL

TRENDS = [
    ('first', 'First Purchase'),
    ('up', 'Price Up'),
    ('down', 'Price Down'),
    ('stable', 'Stable'),
]


class LppVendorPriceReport(models.Model):
    """One row per confirmed purchase order line, with its unit price
    normalized to the product's UoM and the company currency, and compared
    to the previous purchase of the same product from the same vendor."""
    _name = 'lpp.vendor.price.report'
    _description = 'Vendor Price Stability Analysis'
    _auto = False
    _rec_name = 'product_id'
    _order = 'date desc, id desc'

    date = fields.Datetime('Purchase Date', readonly=True)
    order_id = fields.Many2one('purchase.order', 'Purchase Order', readonly=True)
    order_line_id = fields.Many2one('purchase.order.line', 'Order Line', readonly=True)
    company_id = fields.Many2one('res.company', 'Company', readonly=True)
    currency_id = fields.Many2one('res.currency', 'Currency', readonly=True)
    order_currency_id = fields.Many2one('res.currency', 'Order Currency', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Vendor', readonly=True)
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', 'Product Template', readonly=True)
    categ_id = fields.Many2one('product.category', 'Product Category', readonly=True)
    uom_id = fields.Many2one('uom.uom', 'Unit of Measure', readonly=True)
    user_id = fields.Many2one('res.users', 'Buyer', readonly=True)

    order_price_unit = fields.Float('Order Unit Price', digits='Product Price',
                                    readonly=True, aggregator='avg')
    currency_rate = fields.Float('Currency Rate', digits=(16, 6),
                                 readonly=True, aggregator='avg')
    unit_price = fields.Float('Avg Unit Price', digits='Product Price',
                              readonly=True, aggregator='avg')
    min_price = fields.Float('Min Unit Price', digits='Product Price',
                             readonly=True, aggregator='min')
    max_price = fields.Float('Max Unit Price', digits='Product Price',
                             readonly=True, aggregator='max')
    previous_price = fields.Float('Previous Unit Price', digits='Product Price',
                                  readonly=True, aggregator='avg')
    price_change = fields.Float('Price Change', digits='Product Price',
                                readonly=True, aggregator='avg')
    variance_pct = fields.Float('Variance (%)', digits=(16, 2),
                                readonly=True, aggregator='avg')
    abs_variance_pct = fields.Float('Avg Fluctuation (%)', digits=(16, 2),
                                    readonly=True, aggregator='avg')
    qty = fields.Float('Quantity', digits='Product Unit of Measure',
                       readonly=True)
    amount = fields.Monetary('Purchased Amount', readonly=True)
    nbr_purchases = fields.Integer('# Purchases', readonly=True)
    nbr_increases = fields.Integer('# Increases', readonly=True)
    nbr_decreases = fields.Integer('# Decreases', readonly=True)
    trend = fields.Selection(TRENDS, 'Trend', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
            WITH base AS (
                SELECT pol.id                                     AS id,
                       pol.id                                     AS order_line_id,
                       po.id                                      AS order_id,
                       po.company_id                              AS company_id,
                       c.currency_id                              AS currency_id,
                       po.currency_id                             AS order_currency_id,
                       rp.commercial_partner_id                   AS partner_id,
                       pol.product_id                             AS product_id,
                       pt.id                                      AS product_tmpl_id,
                       pt.categ_id                                AS categ_id,
                       pt.uom_id                                  AS uom_id,
                       po.user_id                                 AS user_id,
                       COALESCE(po.date_approve, po.date_order)   AS date,
                       pol.price_unit                             AS order_price_unit,
                       COALESCE(NULLIF(po.currency_rate, 0), 1.0) AS currency_rate,
                       COALESCE(c.lpp_neutral_band, 0.0)          AS neutral_band,
                       -- UoM factors of "bigger" units are stored as 1/n
                       -- (e.g. 0.0833.. for a dozen): round to 6 decimals so
                       -- 600/dozen and 50/unit compare as the same price.
                       ROUND(pol.product_qty::numeric
                             / lu.factor::numeric
                             * pu.factor::numeric, 6)             AS qty,
                       ROUND(pol.price_unit::numeric
                             / COALESCE(NULLIF(po.currency_rate, 0), 1.0)::numeric
                             * lu.factor::numeric
                             / pu.factor::numeric, 6)             AS unit_price
                  FROM purchase_order_line pol
                  JOIN purchase_order po ON po.id = pol.order_id
                  JOIN res_company c ON c.id = po.company_id
                  JOIN res_partner rp ON rp.id = po.partner_id
                  JOIN product_product pp ON pp.id = pol.product_id
                  JOIN product_template pt ON pt.id = pp.product_tmpl_id
                  JOIN uom_uom lu ON lu.id = pol.product_uom
                  JOIN uom_uom pu ON pu.id = pt.uom_id
                 WHERE po.state IN ('purchase', 'done')
                   AND pol.display_type IS NULL
                   AND pol.product_qty > 0
                   AND pol.price_unit > 0
                   AND lu.factor <> 0
                   AND pu.factor <> 0
            ), seq AS (
                SELECT base.*,
                       LAG(unit_price) OVER (
                           PARTITION BY company_id, partner_id, product_id
                           ORDER BY date, id
                       ) AS previous_price
                  FROM base
            ), measured AS (
                SELECT seq.*,
                       CASE WHEN previous_price IS NULL OR previous_price = 0
                            THEN NULL
                            ELSE (unit_price - previous_price) / previous_price * 100
                       END AS raw_variance
                  FROM seq
            )
            SELECT id, order_line_id, order_id, company_id, currency_id,
                   order_currency_id, partner_id, product_id, product_tmpl_id,
                   categ_id, uom_id, user_id, date, order_price_unit,
                   currency_rate,
                   ROUND(unit_price, 6)                           AS unit_price,
                   ROUND(unit_price, 6)                           AS min_price,
                   ROUND(unit_price, 6)                           AS max_price,
                   ROUND(previous_price, 6)                       AS previous_price,
                   ROUND(unit_price - previous_price, 6)          AS price_change,
                   ROUND(raw_variance, 4)                         AS variance_pct,
                   ROUND(ABS(raw_variance), 4)                    AS abs_variance_pct,
                   qty,
                   ROUND(qty * unit_price, 6)                     AS amount,
                   1                                              AS nbr_purchases,
                   CASE WHEN raw_variance > neutral_band THEN 1 ELSE 0 END
                                                                  AS nbr_increases,
                   CASE WHEN raw_variance < -neutral_band THEN 1 ELSE 0 END
                                                                  AS nbr_decreases,
                   CASE WHEN previous_price IS NULL THEN 'first'
                        WHEN raw_variance > neutral_band THEN 'up'
                        WHEN raw_variance < -neutral_band THEN 'down'
                        ELSE 'stable'
                   END                                            AS trend
              FROM measured
            )
        """ % self._table)

    # ------------------------------------------------------------------
    # Aggregated statistics (used by the PDF and Excel outputs)
    # ------------------------------------------------------------------
    @api.model
    def _lpp_get_stability_rows(self, domain):
        """Aggregate the analysis rows matching ``domain`` (record rules
        applied) per company / vendor / product, in one SQL query, and
        classify each pair by direction and stability."""
        # the view reads purchase tables directly: push pending ORM writes
        self.env.flush_all()
        query = self._where_calc(domain)
        self._apply_ir_rules(query, 'read')
        # Odoo 18: Query.get_sql() is gone; build the statement with
        # Query.select() so the WHERE clause and its parameters stay SQL objects.
        tbl = '"%s"' % self._table
        query.groupby = SQL("{t}.company_id, {t}.partner_id, {t}.product_id".format(t=tbl))
        self.env.cr.execute(query.select(SQL("""
                   {t}.company_id, {t}.partner_id, {t}.product_id,
                   MIN({t}.currency_id)                      AS currency_id,
                   MIN({t}.uom_id)                           AS uom_id,
                   COUNT(*)                                  AS nbr,
                   MIN({t}.unit_price)                       AS min_price,
                   MAX({t}.unit_price)                       AS max_price,
                   AVG({t}.unit_price)                       AS avg_price,
                   COALESCE(STDDEV_SAMP({t}.unit_price), 0)  AS stddev,
                   (ARRAY_AGG({t}.unit_price ORDER BY {t}.date, {t}.id))[1]
                                                             AS first_price,
                   (ARRAY_AGG({t}.unit_price ORDER BY {t}.date DESC, {t}.id DESC))[1]
                                                             AS last_price,
                   MIN({t}.date)                             AS first_date,
                   MAX({t}.date)                             AS last_date,
                   SUM({t}.nbr_increases)                    AS nbr_up,
                   SUM({t}.nbr_decreases)                    AS nbr_down,
                   SUM({t}.qty)                              AS qty,
                   SUM({t}.amount)                           AS amount,
                   AVG({t}.abs_variance_pct)                 AS avg_fluctuation
        """.format(t=tbl))))
        raw_rows = self.env.cr.dictfetchall()

        partners = self.env['res.partner'].browse({r['partner_id'] for r in raw_rows})
        products = self.env['product.product'].browse({r['product_id'] for r in raw_rows})
        currencies = self.env['res.currency'].browse({r['currency_id'] for r in raw_rows})
        uoms = self.env['uom.uom'].browse({r['uom_id'] for r in raw_rows})
        companies = self.env['res.company'].browse({r['company_id'] for r in raw_rows})
        by_id = {}
        for records in (partners, products, currencies, uoms, companies):
            by_id.update({'%s%s' % (rec._name, rec.id): rec for rec in records})

        result = []
        for r in raw_rows:
            row_company = by_id['res.company%s' % r['company_id']]
            stable_cv = row_company.lpp_stable_cv
            volatile_cv = row_company.lpp_volatile_cv
            band = row_company.lpp_neutral_band or 0.0
            avg_price = float(r['avg_price'] or 0.0)
            stddev = float(r['stddev'] or 0.0)
            first_price = float(r['first_price'] or 0.0)
            last_price = float(r['last_price'] or 0.0)
            cv = (stddev / avg_price * 100.0) if avg_price else 0.0
            change_pct = ((last_price - first_price) / first_price * 100.0) if first_price else 0.0
            if change_pct > band:
                direction = 'up'
            elif change_pct < -band:
                direction = 'down'
            else:
                direction = 'flat'
            if cv <= stable_cv:
                stability = 'stable'
            elif cv <= volatile_cv:
                stability = 'moderate'
            else:
                stability = 'volatile'
            # 100 = no fluctuation, 50 = at the volatile threshold, 0 = twice it
            scale = (2.0 * volatile_cv) or 1.0
            score = max(0.0, 100.0 - cv * 100.0 / scale)
            result.append({
                'company': row_company,
                'partner': by_id['res.partner%s' % r['partner_id']],
                'product': by_id['product.product%s' % r['product_id']],
                'currency': by_id['res.currency%s' % r['currency_id']],
                'uom': by_id['uom.uom%s' % r['uom_id']],
                'nbr': r['nbr'],
                'min_price': float(r['min_price'] or 0.0),
                'max_price': float(r['max_price'] or 0.0),
                'avg_price': avg_price,
                'stddev': stddev,
                'first_price': first_price,
                'last_price': last_price,
                'first_date': r['first_date'],
                'last_date': r['last_date'],
                'nbr_up': r['nbr_up'] or 0,
                'nbr_down': r['nbr_down'] or 0,
                'qty': float(r['qty'] or 0.0),
                'amount': float(r['amount'] or 0.0),
                'avg_fluctuation': float(r['avg_fluctuation'] or 0.0),
                'cv': round(cv, 2),
                'change_pct': round(change_pct, 2),
                'direction': direction,
                'stability': stability,
                'score': round(score, 1),
                'spread_pct': round(((float(r['max_price'] or 0.0) - float(r['min_price'] or 0.0))
                                     / avg_price * 100.0) if avg_price else 0.0, 2),
            })
        result.sort(key=lambda d: (d['company'].id, (d['partner'].display_name or '').lower(),
                                   (d['product'].display_name or '').lower()))
        return result
