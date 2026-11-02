# -*- coding: utf-8 -*-
import base64
import io
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import get_lang

try:
    import xlsxwriter
except ImportError:  # pragma: no cover - declared as external dependency
    xlsxwriter = None


DIRECTIONS = [
    ('all', 'All Trends'),
    ('up', 'Rising'),
    ('down', 'Falling'),
    ('flat', 'Flat'),
]
STABILITIES = [
    ('all', 'All'),
    ('stable', 'Stable'),
    ('moderate', 'Moderate'),
    ('volatile', 'Volatile'),
]


class LppStabilityWizard(models.TransientModel):
    _name = 'lpp.stability.wizard'
    _description = 'Vendor Price Stability Report Wizard'

    date_from = fields.Date('From')
    date_to = fields.Date('To')
    partner_ids = fields.Many2many('res.partner', string='Vendors')
    product_ids = fields.Many2many('product.product', string='Products')
    categ_ids = fields.Many2many('product.category', string='Product Categories')
    company_ids = fields.Many2many(
        'res.company', string='Companies',
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)])
    direction = fields.Selection(
        DIRECTIONS, string='Price Trend', default='all', required=True,
        help='Rising / Falling: last price of the period above / below the '
             'first one by more than the neutral band.')
    stability = fields.Selection(
        STABILITIES, string='Stability', default='all', required=True,
        help='Based on the coefficient of variation of the unit price and '
             'the thresholds set in Purchase Settings.')
    min_purchases = fields.Integer(
        'Minimum Purchases', default=1,
        help='Ignore vendor/product pairs bought fewer times than this in the period.')
    show_history = fields.Boolean(
        'Include Price History', default=True,
        help='Add the line-by-line price history sheet to the Excel export.')
    excel_file = fields.Binary('Excel File', readonly=True, attachment=False)
    excel_filename = fields.Char('Excel File Name', readonly=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(_('The start date must be earlier than the end date.'))

    @api.constrains('min_purchases')
    def _check_min_purchases(self):
        for wizard in self:
            if wizard.min_purchases < 1:
                raise ValidationError(_('The minimum number of purchases must be at least 1.'))

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _get_domain(self):
        self.ensure_one()
        domain = []
        if self.date_from:
            domain.append(('date', '>=', self._local_day_start_utc(self.date_from)))
        if self.date_to:
            domain.append(('date', '<', self._local_day_start_utc(self.date_to + timedelta(days=1))))
        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.mapped('commercial_partner_id').ids))
        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))
        if self.categ_ids:
            domain.append(('categ_id', 'child_of', self.categ_ids.ids))
        companies = self.company_ids or self.env.companies
        domain.append(('company_id', 'in', companies.ids))
        return domain

    def _local_day_start_utc(self, day):
        """Midnight of ``day`` in the user's timezone, as naive UTC."""
        tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        local = tz.localize(datetime.combine(day, time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _get_stability_rows(self):
        self.ensure_one()
        rows = self.env['lpp.vendor.price.report']._lpp_get_stability_rows(self._get_domain())
        return [
            row for row in rows
            if row['nbr'] >= self.min_purchases
            and (self.direction == 'all' or row['direction'] == self.direction)
            and (self.stability == 'all' or row['stability'] == self.stability)
        ]

    def _get_history_lines(self, rows):
        """Detail lines for the vendor/product pairs kept in ``rows``."""
        self.ensure_one()
        if not rows:
            return self.env['lpp.vendor.price.report']
        keys = {(r['company'].id, r['partner'].id, r['product'].id) for r in rows}
        domain = self._get_domain() + [
            ('partner_id', 'in', list({k[1] for k in keys})),
            ('product_id', 'in', list({k[2] for k in keys})),
        ]
        lines = self.env['lpp.vendor.price.report'].search(
            domain, order='partner_id, product_id, date, id')
        return lines.filtered(
            lambda l: (l.company_id.id, l.partner_id.id, l.product_id.id) in keys)

    def _get_summary(self, rows):
        count = len(rows)
        return {
            'pairs': count,
            'vendors': len({r['partner'].id for r in rows}),
            'products': len({r['product'].id for r in rows}),
            'purchases': sum(r['nbr'] for r in rows),
            'rising': len([r for r in rows if r['direction'] == 'up']),
            'falling': len([r for r in rows if r['direction'] == 'down']),
            'volatile': len([r for r in rows if r['stability'] == 'volatile']),
            'avg_score': round(sum(r['score'] for r in rows) / count, 1) if count else 0.0,
        }

    def _get_filter_labels(self):
        self.ensure_one()
        lang = get_lang(self.env)
        date_fmt = lang.date_format
        labels = []
        if self.date_from or self.date_to:
            labels.append((_('Period'), '%s → %s' % (
                self.date_from and self.date_from.strftime(date_fmt) or '…',
                self.date_to and self.date_to.strftime(date_fmt) or '…')))
        if self.partner_ids:
            labels.append((_('Vendors'), ', '.join(self.partner_ids.mapped('display_name'))))
        if self.product_ids:
            labels.append((_('Products'), ', '.join(self.product_ids.mapped('display_name'))))
        if self.categ_ids:
            labels.append((_('Categories'), ', '.join(self.categ_ids.mapped('display_name'))))
        selection = dict(self._fields['direction']._description_selection(self.env))
        if self.direction != 'all':
            labels.append((_('Price Trend'), selection[self.direction]))
        selection = dict(self._fields['stability']._description_selection(self.env))
        if self.stability != 'all':
            labels.append((_('Stability'), selection[self.stability]))
        if self.min_purchases > 1:
            labels.append((_('Minimum Purchases'), str(self.min_purchases)))
        return labels

    def _get_label_maps(self):
        return {
            'direction': {
                'up': _('Rising'), 'down': _('Falling'), 'flat': _('Flat'),
            },
            'stability': {
                'stable': _('Stable'), 'moderate': _('Moderate'), 'volatile': _('Volatile'),
            },
            'trend': dict(self.env['lpp.vendor.price.report']._fields['trend']._description_selection(self.env)),
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_open_analysis(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'last_purchase_price_advanced.action_lpp_vendor_price_report')
        action['domain'] = self._get_domain()
        return action

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'last_purchase_price_advanced.action_report_lpp_vendor_price_stability'
        ).report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        if xlsxwriter is None:
            raise UserError(_('The Python library xlsxwriter is required for the Excel export.'))
        content = self._generate_xlsx()
        filename = '%s.xlsx' % _('Vendor Price Stability').replace(' ', '_')
        self.write({
            'excel_file': base64.b64encode(content),
            'excel_filename': filename,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model=%s&id=%s&field=excel_file'
                   '&filename_field=excel_filename&download=true' % (self._name, self.id),
            'target': 'self',
        }

    # ------------------------------------------------------------------
    # Excel
    # ------------------------------------------------------------------
    def _to_local(self, value):
        """UTC naive datetime -> user's timezone naive datetime."""
        if not value:
            return value
        return fields.Datetime.context_timestamp(self, value).replace(tzinfo=None)

    @api.model
    def _lpp_print_setup(self, sheet, header_row):
        """A4 landscape, one page wide, header row repeated on every page."""
        sheet.set_paper(9)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(header_row)
        sheet.set_margins(left=0.4, right=0.4, top=0.5, bottom=0.5)

    def _generate_xlsx(self):
        self.ensure_one()
        rows = self._get_stability_rows()
        summary = self._get_summary(rows)
        labels = self._get_label_maps()
        lang = get_lang(self.env)
        rtl = lang.direction == 'rtl'
        price_digits = self.env['decimal.precision'].precision_get('Product Price')
        price_fmt = '#,##0.%s' % ('0' * price_digits) if price_digits else '#,##0'
        date_fmt = 'yyyy-mm-dd hh:mm'

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True, 'remove_timezone': True})
        align = 'right' if rtl else 'left'
        base = {'font_name': 'Arial', 'font_size': 10, 'valign': 'vcenter'}

        def fmt(**kw):
            return workbook.add_format(dict(base, **kw))

        f_title = fmt(bold=True, font_size=16, font_color='#1F3A5F', align=align)
        f_sub = fmt(italic=True, font_color='#5B6770', align=align)
        f_head = fmt(bold=True, font_color='#FFFFFF', bg_color='#1F3A5F', border=1,
                     border_color='#C9D3DD', align='center', text_wrap=True)
        f_text = fmt(border=1, border_color='#DDE3EA', align=align)
        f_int = fmt(border=1, border_color='#DDE3EA', num_format='0', align='center')
        f_price = fmt(border=1, border_color='#DDE3EA', num_format=price_fmt)
        f_qty = fmt(border=1, border_color='#DDE3EA', num_format='#,##0.00')
        f_pct = fmt(border=1, border_color='#DDE3EA', num_format='0.00"%"')
        f_rate = fmt(border=1, border_color='#DDE3EA', num_format='0.000000')
        f_date = fmt(border=1, border_color='#DDE3EA', num_format=date_fmt, align='center')
        f_kpi_lbl = fmt(bold=True, bg_color='#EEF2F6', border=1, border_color='#DDE3EA', align=align)
        f_kpi_val = fmt(bold=True, font_size=12, border=1, border_color='#DDE3EA', align='center')
        f_up = fmt(border=1, border_color='#DDE3EA', font_color='#B42318', bg_color='#FDECEA', bold=True, align='center')
        f_down = fmt(border=1, border_color='#DDE3EA', font_color='#067647', bg_color='#E7F6EC', bold=True, align='center')
        f_flat = fmt(border=1, border_color='#DDE3EA', font_color='#475467', bg_color='#F2F4F7', align='center')
        f_red = workbook.add_format({'font_color': '#B42318', 'bg_color': '#FDECEA'})
        f_green = workbook.add_format({'font_color': '#067647', 'bg_color': '#E7F6EC'})
        status_fmt = {'up': f_up, 'down': f_down, 'flat': f_flat,
                      'volatile': f_up, 'stable': f_down, 'moderate': f_flat}

        # ---------------- Summary sheet ----------------
        ws = workbook.add_worksheet(_('Stability Summary')[:31])
        if rtl:
            ws.right_to_left()
        ws.write(0, 0, _('Vendor Price Stability'), f_title)
        ws.write(1, 0, '%s: %s' % (_('Printed on'), fields.Datetime.context_timestamp(
            self, fields.Datetime.now()).strftime('%s %s' % (lang.date_format, lang.time_format))), f_sub)
        row = 2
        for label, value in self._get_filter_labels():
            ws.write(row, 0, '%s: %s' % (label, value), f_sub)
            row += 1
        row += 1
        kpis = [
            (_('Vendor/Product Pairs'), summary['pairs']),
            (_('Purchases Analyzed'), summary['purchases']),
            (_('Rising Prices'), summary['rising']),
            (_('Falling Prices'), summary['falling']),
            (_('Volatile Pairs'), summary['volatile']),
            (_('Avg Stability Score'), summary['avg_score']),
        ]
        for label, value in kpis:
            ws.merge_range(row, 0, row, 1, label, f_kpi_lbl)
            ws.write(row, 2, value, f_kpi_val)
            row += 1
        row += 1

        headers = [
            (_('Company'), 18), (_('Vendor'), 28), (_('Product'), 32), (_('UoM'), 8),
            (_('Currency'), 9), (_('Purchases'), 10), (_('First Date'), 16),
            (_('Last Date'), 16), (_('First Price'), 13), (_('Last Price'), 13),
            (_('Min Price'), 13), (_('Max Price'), 13), (_('Avg Price'), 13),
            (_('Std Dev'), 12), (_('CV %'), 9), (_('Spread %'), 10),
            (_('Change %'), 10), (_('# Increases'), 10), (_('# Decreases'), 10),
            (_('Trend'), 11), (_('Stability'), 12), (_('Score'), 9),
            (_('Quantity'), 12), (_('Amount'), 14),
        ]
        header_row = row
        for col, (title, width) in enumerate(headers):
            ws.write(row, col, title, f_head)
            ws.set_column(col, col, width)
        ws.set_row(row, 30)
        row += 1
        for r in rows:
            values = [
                (r['company'].name, f_text), (r['partner'].display_name, f_text),
                (r['product'].display_name, f_text), (r['uom'].name, f_text),
                (r['currency'].name, f_text), (r['nbr'], f_int),
                (r['first_date'], f_date), (r['last_date'], f_date),
                (r['first_price'], f_price), (r['last_price'], f_price),
                (r['min_price'], f_price), (r['max_price'], f_price),
                (r['avg_price'], f_price), (r['stddev'], f_price),
                (r['cv'], f_pct), (r['spread_pct'], f_pct), (r['change_pct'], f_pct),
                (r['nbr_up'], f_int), (r['nbr_down'], f_int),
                (labels['direction'][r['direction']], status_fmt[r['direction']]),
                (labels['stability'][r['stability']], status_fmt[r['stability']]),
                (r['score'], f_qty), (r['qty'], f_qty), (r['amount'], f_price),
            ]
            for col, (value, cell_fmt) in enumerate(values):
                if isinstance(value, datetime):
                    ws.write_datetime(row, col, self._to_local(value), cell_fmt)
                else:
                    ws.write(row, col, value, cell_fmt)
            row += 1
        if rows:
            ws.autofilter(header_row, 0, row - 1, len(headers) - 1)
            change_col = 16
            ws.conditional_format(header_row + 1, change_col, row - 1, change_col,
                                  {'type': 'cell', 'criteria': '>', 'value': 0, 'format': f_red})
            ws.conditional_format(header_row + 1, change_col, row - 1, change_col,
                                  {'type': 'cell', 'criteria': '<', 'value': 0, 'format': f_green})
            ws.conditional_format(header_row + 1, 21, row - 1, 21, {
                'type': '3_color_scale', 'min_color': '#F8696B',
                'mid_color': '#FFEB84', 'max_color': '#63BE7B'})
        else:
            ws.write(row, 0, _('No purchases match the selected filters.'), f_sub)
        ws.freeze_panes(header_row + 1, 3)
        self._lpp_print_setup(ws, header_row)

        # ---------------- History sheet ----------------
        if self.show_history and rows:
            hs = workbook.add_worksheet(_('Price History')[:31])
            if rtl:
                hs.right_to_left()
            h_headers = [
                (_('Date'), 16), (_('Purchase Order'), 16), (_('Vendor'), 28),
                (_('Product'), 32), (_('UoM'), 8), (_('Order Currency'), 10),
                (_('Order Unit Price'), 14), (_('Currency Rate'), 12),
                (_('Unit Price'), 13), (_('Currency'), 9), (_('Previous Price'), 13),
                (_('Change'), 12), (_('Variance (%)'), 11), (_('Trend'), 13),
                (_('Quantity'), 12), (_('Amount'), 14),
            ]
            for col, (title, width) in enumerate(h_headers):
                hs.write(0, col, title, f_head)
                hs.set_column(col, col, width)
            hs.set_row(0, 30)
            trend_fmt = {'up': f_up, 'down': f_down, 'stable': f_flat, 'first': f_flat}
            hrow = 1
            for line in self._get_history_lines(rows):
                hs.write_datetime(hrow, 0, self._to_local(line.date), f_date)
                hs.write(hrow, 1, line.order_id.name, f_text)
                hs.write(hrow, 2, line.partner_id.display_name, f_text)
                hs.write(hrow, 3, line.product_id.display_name, f_text)
                hs.write(hrow, 4, line.uom_id.name, f_text)
                hs.write(hrow, 5, line.order_currency_id.name, f_text)
                hs.write(hrow, 6, line.order_price_unit, f_price)
                hs.write(hrow, 7, line.currency_rate, f_rate)
                hs.write(hrow, 8, line.unit_price, f_price)
                hs.write(hrow, 9, line.currency_id.name, f_text)
                if line.trend == 'first':
                    hs.write_blank(hrow, 10, None, f_price)
                    hs.write_blank(hrow, 11, None, f_price)
                    hs.write_blank(hrow, 12, None, f_pct)
                else:
                    hs.write(hrow, 10, line.previous_price, f_price)
                    hs.write(hrow, 11, line.price_change, f_price)
                    hs.write(hrow, 12, line.variance_pct, f_pct)
                hs.write(hrow, 13, labels['trend'].get(line.trend, ''), trend_fmt.get(line.trend, f_flat))
                hs.write(hrow, 14, line.qty, f_qty)
                hs.write(hrow, 15, line.amount, f_price)
                hrow += 1
            hs.autofilter(0, 0, max(hrow - 1, 1), len(h_headers) - 1)
            hs.freeze_panes(1, 4)
            self._lpp_print_setup(hs, 0)

        workbook.close()
        return output.getvalue()
