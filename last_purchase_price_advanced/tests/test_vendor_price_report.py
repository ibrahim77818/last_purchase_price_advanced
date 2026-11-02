# -*- coding: utf-8 -*-
import base64
import io
import statistics
from datetime import date, datetime

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import LppCommon


@tagged('post_install', '-at_install')
class TestVendorPriceReport(LppCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # vendor A: 100 -> 110 -> 99 (volatile, falling overall)
        cls._make_po(cls.vendor_a, [(cls.product, 10, 100.0)], date=datetime(2024, 2, 1))
        cls._make_po(cls.vendor_a, [(cls.product, 10, 110.0)], date=datetime(2024, 3, 1))
        cls._make_po(cls.vendor_a, [(cls.product, 10, 99.0)], date=datetime(2024, 4, 1))
        # vendor B: perfectly stable, bought by the dozen (12 per dozen)
        cls._make_po(cls.vendor_b, [(cls.product, 2, 600.0, cls.uom_dozen)], date=datetime(2024, 2, 5))
        cls._make_po(cls.vendor_b, [(cls.product, 24, 50.0, cls.uom_unit)], date=datetime(2024, 3, 5))
        # draft and cancelled orders never show up
        cls._make_po(cls.vendor_a, [(cls.product, 10, 1.0)], confirm=False, date=datetime(2024, 4, 5))
        cls.Report = cls.env['lpp.vendor.price.report']

    def _report_lines(self, partner):
        self.env.flush_all()
        return self.Report.search([('partner_id', '=', partner.id),
                                   ('product_id', '=', self.product.id)], order='date, id')

    def _rows(self, **wizard_vals):
        # Scope to the test category: demo databases (Odoo 17 loads demo
        # purchase orders by default) must not leak into the assertions.
        wizard_vals.setdefault('categ_ids', [(6, 0, self.categ.ids)])
        wizard = self.env['lpp.stability.wizard'].create(wizard_vals)
        return wizard, {(r['partner'], r['product']): r for r in wizard._get_stability_rows()}

    def test_01_line_level_trend(self):
        lines = self._report_lines(self.vendor_a)
        self.assertEqual(len(lines), 3, 'Only confirmed orders are analyzed')
        self.assertEqual(lines.mapped('trend'), ['first', 'up', 'down'])
        self.assertAlmostEqual(lines[1].previous_price, 100.0, places=4)
        self.assertAlmostEqual(lines[1].variance_pct, 10.0, places=2)
        self.assertAlmostEqual(lines[2].variance_pct, -10.0, places=2)
        self.assertAlmostEqual(lines[2].abs_variance_pct, 10.0, places=2)
        self.assertEqual(lines[0].previous_price, 0.0)

    def test_02_uom_normalization(self):
        lines = self._report_lines(self.vendor_b)
        self.assertEqual(len(lines), 2)
        # 600 per dozen == 50 per unit: no price change
        self.assertAlmostEqual(lines[0].unit_price, 50.0, places=4)
        self.assertAlmostEqual(lines[0].qty, 24.0, places=4)
        self.assertEqual(lines[1].trend, 'stable')

    def test_03_pivot_aggregates(self):
        self.env.flush_all()
        groups = self.Report._read_group(
            [('product_id', '=', self.product.id), ('partner_id', '=', self.vendor_a.id)],
            ['partner_id'],
            ['unit_price:avg', 'min_price:min', 'max_price:max', 'nbr_purchases:sum', 'qty:sum'])
        self.assertEqual(len(groups), 1)
        group = dict(zip(['partner_id', 'unit_price', 'min_price', 'max_price', 'nbr_purchases', 'qty'],
                         groups[0]))
        self.assertAlmostEqual(group['unit_price'], (100 + 110 + 99) / 3.0, places=4)
        self.assertAlmostEqual(group['min_price'], 99.0, places=4)
        self.assertAlmostEqual(group['max_price'], 110.0, places=4)
        self.assertEqual(group['nbr_purchases'], 3)
        self.assertAlmostEqual(group['qty'], 30.0, places=4)

    def test_04_stability_statistics(self):
        _wizard, rows = self._rows()
        a = rows[(self.vendor_a, self.product)]
        b = rows[(self.vendor_b, self.product)]
        prices = [100.0, 110.0, 99.0]
        expected_cv = statistics.stdev(prices) / statistics.mean(prices) * 100
        self.assertEqual(a['nbr'], 3)
        self.assertAlmostEqual(a['cv'], round(expected_cv, 2), places=2)
        self.assertEqual(a['first_price'], 100.0)
        self.assertEqual(a['last_price'], 99.0)
        self.assertEqual(a['direction'], 'down')
        self.assertEqual(a['stability'], 'moderate')   # 2% < CV ~6.1% <= 10%
        self.assertEqual((a['nbr_up'], a['nbr_down']), (1, 1))
        self.assertEqual(b['cv'], 0.0)
        self.assertEqual(b['stability'], 'stable')
        self.assertEqual(b['direction'], 'flat')
        self.assertEqual(b['score'], 100.0)

    def test_05_wizard_filters(self):
        _w, rows = self._rows(direction='down')
        self.assertEqual(set(p for p, _prod in rows), {self.vendor_a})
        _w, rows = self._rows(stability='stable')
        self.assertEqual(set(p for p, _prod in rows), {self.vendor_b})
        _w, rows = self._rows(min_purchases=3)
        self.assertEqual(set(p for p, _prod in rows), {self.vendor_a})
        _w, rows = self._rows(partner_ids=[(6, 0, self.vendor_b.ids)])
        self.assertEqual(set(p for p, _prod in rows), {self.vendor_b})
        _w, rows = self._rows(date_from=date(2024, 3, 1), date_to=date(2024, 4, 30))
        a = rows[(self.vendor_a, self.product)]
        self.assertEqual(a['nbr'], 2)
        self.assertEqual(a['first_price'], 110.0)
        _w, rows = self._rows(categ_ids=[(6, 0, self.categ.ids)], product_ids=[(6, 0, self.product_2.ids)])
        self.assertFalse(rows)

    def test_06_wizard_constraints(self):
        with self.assertRaises(ValidationError):
            self.env['lpp.stability.wizard'].create({
                'date_from': date(2024, 5, 1), 'date_to': date(2024, 1, 1)})
        with self.assertRaises(ValidationError):
            self.env['lpp.stability.wizard'].create({'min_purchases': 0})
        with self.assertRaises(ValidationError):
            self.company.write({'lpp_stable_cv': 20.0, 'lpp_volatile_cv': 5.0})

    def test_07_excel_export(self):
        wizard = self.env['lpp.stability.wizard'].create({
            'categ_ids': [(6, 0, self.categ.ids)]})
        action = wizard.action_export_xlsx()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        content = base64.b64decode(wizard.excel_file)
        self.assertTrue(content.startswith(b'PK'), 'An xlsx file is a zip archive')
        self.assertTrue(wizard.excel_filename.endswith('.xlsx'))
        try:
            import openpyxl
        except ImportError:
            return
        book = openpyxl.load_workbook(io.BytesIO(content))
        self.assertEqual(len(book.sheetnames), 2)
        values = [c for row in book.worksheets[0].iter_rows(values_only=True) for c in row if c]
        self.assertIn('LPP Vendor A', values)
        history = list(book.worksheets[1].iter_rows(values_only=True))
        self.assertEqual(len(history), 1 + 5, 'header + 5 confirmed lines')

    def test_08_pdf_report(self):
        wizard = self.env['lpp.stability.wizard'].create({})
        html, _fmt = self.env['ir.actions.report']._render_qweb_html(
            'last_purchase_price_advanced.report_vendor_stability', wizard.ids)
        html = html.decode()
        self.assertIn('LPP Vendor A', html)
        self.assertIn('LPP Vendor B', html)
        self.assertIn('lpp_badge_moderate', html)
        action = wizard.with_context(discard_logo_check=True).action_print_pdf()
        self.assertEqual(action['report_name'], 'last_purchase_price_advanced.report_vendor_stability')

    def test_09_arabic_rtl(self):
        lang = self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(
            ['last_purchase_price_advanced'], ['ar_001'], overwrite=True)
        env_ar = self.env(context=dict(self.env.context, lang='ar_001'))
        self.assertEqual(lang.direction, 'rtl')

        field = env_ar['ir.model.fields']._get('purchase.order.line', 'lpp_last_price')
        self.assertEqual(field.with_context(lang='ar_001').field_description, 'آخر سعر')

        wizard = env_ar['lpp.stability.wizard'].create({})
        html, _fmt = env_ar['ir.actions.report']._render_qweb_html(
            'last_purchase_price_advanced.report_vendor_stability', wizard.ids)
        html = html.decode()
        self.assertIn('dir="rtl"', html)
        self.assertIn('استقرار أسعار الموردين', html)

        self.assertTrue(wizard._generate_xlsx().startswith(b'PK'))

    def test_10_multi_company_rule(self):
        other = self.env['res.company'].create({'name': 'LPP Other Co'})
        user = self.env['res.users'].create({
            'name': 'LPP Buyer', 'login': 'lpp_buyer',
            'company_id': other.id, 'company_ids': [(6, 0, other.ids)],
            'group_ids': [(6, 0, [self.env.ref('purchase.group_purchase_manager').id])],
        })
        self.env.flush_all()
        self.assertFalse(self.Report.with_user(user).search([]),
                         'Users must not see price history of other companies')
        self.assertFalse(self.env['lpp.stability.wizard'].with_user(user).create({})._get_stability_rows())
