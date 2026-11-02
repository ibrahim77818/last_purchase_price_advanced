# -*- coding: utf-8 -*-
from datetime import datetime
from unittest.mock import patch

from odoo.tests import Form, tagged

from .common import LppCommon


@tagged('post_install', '-at_install')
class TestLastPurchasePrice(LppCommon):

    def test_01_disabled_by_default_and_toggle(self):
        company = self.env['res.company'].create({'name': 'LPP Fresh Co'})
        self.assertFalse(company.lpp_tracking_enabled, 'Tracking must be off by default')

        self._make_po(self.vendor_a, [(self.product, 1, 100.0)])
        draft = self._make_po(self.vendor_a, [(self.product, 1, 110.0)], confirm=False)
        line = draft.order_line

        self.company.lpp_tracking_enabled = False
        self.assertFalse(line.lpp_price_signal)
        self.assertEqual(line.lpp_last_price, 0.0)
        self.assertFalse(line.lpp_last_order_id)

        settings = self.env['res.config.settings'].create({})
        settings.lpp_tracking_enabled = True
        settings.execute()
        self.assertTrue(self.company.lpp_tracking_enabled)
        line.invalidate_recordset()
        self.assertEqual(line.lpp_last_price, 100.0)

    def test_02_variance_and_signals(self):
        first = self._make_po(self.vendor_a, [(self.product, 5, 100.0)])
        draft = self._make_po(self.vendor_a, [(self.product, 5, 110.0)], confirm=False)
        line = draft.order_line

        self.assertEqual(line.lpp_last_order_id, first)
        self.assertEqual(line.lpp_last_line_id, first.order_line)
        self.assertEqual(line.lpp_last_partner_id, self.vendor_a)
        self.assertEqual(line.lpp_last_price, 100.0)
        self.assertAlmostEqual(line.lpp_price_variance, 10.0, places=2)
        self.assertEqual(line.lpp_price_signal, 'up')

        line.price_unit = 90.0
        self.assertAlmostEqual(line.lpp_price_variance, -10.0, places=2)
        self.assertEqual(line.lpp_price_signal, 'down')

        line.price_unit = 100.0
        self.assertEqual(line.lpp_price_variance, 0.0)
        self.assertEqual(line.lpp_price_signal, 'same')

    def test_03_no_history(self):
        draft = self._make_po(self.vendor_a, [(self.product_2, 1, 10.0)], confirm=False)
        self.assertEqual(draft.order_line.lpp_price_signal, 'new')
        self.assertEqual(draft.order_line.lpp_last_price, 0.0)

    def test_04_only_confirmed_orders_count(self):
        self._make_po(self.vendor_a, [(self.product, 1, 100.0)], date=datetime(2024, 2, 1))
        self._make_po(self.vendor_a, [(self.product, 1, 40.0)], confirm=False,
                      date=datetime(2024, 4, 1))
        cancelled = self._make_po(self.vendor_a, [(self.product, 1, 30.0)],
                                  date=datetime(2024, 4, 2))
        cancelled.button_cancel()
        draft = self._make_po(self.vendor_a, [(self.product, 1, 100.0)], confirm=False)
        self.assertEqual(draft.order_line.lpp_last_price, 100.0)

    def test_05_most_recent_confirmed_wins(self):
        self._make_po(self.vendor_a, [(self.product, 1, 100.0)], date=datetime(2024, 2, 1))
        latest = self._make_po(self.vendor_a, [(self.product, 1, 120.0)], date=datetime(2024, 5, 1))
        # created later but confirmed for an earlier date: must not win
        self._make_po(self.vendor_a, [(self.product, 1, 95.0)], date=datetime(2024, 1, 15))
        draft = self._make_po(self.vendor_a, [(self.product, 1, 120.0)], confirm=False)
        self.assertEqual(draft.order_line.lpp_last_order_id, latest)
        self.assertEqual(draft.order_line.lpp_last_price, 120.0)
        self.assertEqual(draft.order_line.lpp_price_signal, 'same')

    def test_06_own_order_is_excluded(self):
        previous = self._make_po(self.vendor_a, [(self.product, 1, 100.0)], date=datetime(2024, 2, 1))
        current = self._make_po(self.vendor_a, [(self.product, 1, 125.0)], date=datetime(2024, 3, 1))
        line = current.order_line
        self.assertEqual(line.lpp_last_order_id, previous,
                         'A confirmed order must be compared with the order before it, not itself')
        self.assertAlmostEqual(line.lpp_price_variance, 25.0, places=2)

    def test_07_uom_normalization(self):
        # last purchase: 1 dozen at 120 -> 10 per unit
        self._make_po(self.vendor_a, [(self.product, 1, 120.0, self.uom_dozen)])
        draft = self._make_po(self.vendor_a, [
            (self.product, 12, 11.0, self.uom_unit),
            (self.product, 1, 120.0, self.uom_dozen),
        ], confirm=False)
        line_unit, line_dozen = draft.order_line
        self.assertEqual(line_unit.lpp_last_uom_id, self.uom_dozen)
        self.assertEqual(line_unit.lpp_last_price_original, 120.0)
        self.assertAlmostEqual(line_unit.lpp_last_price, 10.0, places=4)
        self.assertAlmostEqual(line_unit.lpp_price_variance, 10.0, places=2)
        self.assertEqual(line_unit.lpp_price_signal, 'up')
        self.assertAlmostEqual(line_dozen.lpp_last_price, 120.0, places=4)
        self.assertEqual(line_dozen.lpp_price_signal, 'same')

    def test_08_multi_currency(self):
        company_currency = self.company.currency_id
        # historical order in foreign currency at the 2024-01-01 rate
        hist = self._make_po(self.vendor_a, [(self.product, 1, 50.0)], currency=self.foreign,
                             date=datetime(2024, 2, 1))
        self.assertNotEqual(hist.currency_rate, 1.0)

        # current order in company currency: historical price / historical rate
        po_company = self._make_po(self.vendor_a, [(self.product, 1, 1.0)],
                                   currency=company_currency, confirm=False,
                                   date=datetime(2024, 7, 1))
        line = po_company.order_line
        self.assertEqual(line.lpp_last_currency_id, self.foreign)
        self.assertAlmostEqual(line.lpp_last_currency_rate, hist.currency_rate, places=6)
        self.assertAlmostEqual(line.lpp_last_price, round(50.0 / hist.currency_rate, 2), places=2)

        # current order in the foreign currency at another rate: still no
        # conversion, the same currency is compared as is
        po_foreign = self._make_po(self.vendor_a, [(self.product, 1, 50.0)],
                                   currency=self.foreign, confirm=False,
                                   date=datetime(2024, 7, 1))
        self.assertNotEqual(po_foreign.currency_rate, hist.currency_rate)
        self.assertEqual(po_foreign.order_line.lpp_last_price, 50.0)
        self.assertEqual(po_foreign.order_line.lpp_price_signal, 'same')

    def test_09_cross_currency_conversion_uses_both_rates(self):
        hist = self._make_po(self.vendor_a, [(self.product, 1, 100.0)],
                             currency=self.company.currency_id, date=datetime(2024, 2, 1))
        po_foreign = self._make_po(self.vendor_a, [(self.product, 1, 1.0)],
                                   currency=self.foreign, confirm=False,
                                   date=datetime(2024, 7, 1))
        expected = 100.0 / (hist.currency_rate or 1.0) * po_foreign.currency_rate
        self.assertAlmostEqual(po_foreign.order_line.lpp_last_price, round(expected, 2), places=2)

    def test_10_vendor_scope(self):
        self._make_po(self.vendor_a, [(self.product, 1, 100.0)], date=datetime(2024, 2, 1))
        self._make_po(self.vendor_b, [(self.product, 1, 80.0)], date=datetime(2024, 5, 1))
        # order placed on a contact of vendor A: matched on the commercial partner
        draft = self._make_po(self.vendor_a_contact, [(self.product, 1, 100.0)], confirm=False)
        line = draft.order_line
        self.assertEqual(line.lpp_last_price, 100.0)

        self.company.lpp_lookup_scope = 'any'
        line.invalidate_recordset()
        self.assertEqual(line.lpp_last_price, 80.0)
        self.assertEqual(line.lpp_last_partner_id, self.vendor_b)
        self.assertEqual(line.lpp_price_signal, 'up')

    def test_11_neutral_band(self):
        self._make_po(self.vendor_a, [(self.product, 1, 100.0)])
        draft = self._make_po(self.vendor_a, [(self.product, 1, 103.0)], confirm=False)
        line = draft.order_line
        self.assertEqual(line.lpp_price_signal, 'up')
        self.company.lpp_neutral_band = 5.0
        line.invalidate_recordset()
        self.assertEqual(line.lpp_price_signal, 'same')
        self.assertAlmostEqual(line.lpp_price_variance, 3.0, places=2)

    def test_12_section_and_note_lines_are_ignored(self):
        self._make_po(self.vendor_a, [(self.product, 1, 100.0)])
        draft = self._make_po(self.vendor_a, [(self.product, 1, 100.0)], confirm=False)
        note = self.env['purchase.order.line'].create({
            'order_id': draft.id, 'display_type': 'line_note', 'name': 'note',
            'product_qty': 0,
        })
        self.assertFalse(note.lpp_price_signal)
        self.assertEqual(draft.order_line.filtered('product_id').lpp_price_signal, 'same')

    def test_13_large_order_single_query(self):
        products = self.env['product.product'].create([{
            'name': 'LPP Bulk %s' % i, 'type': 'consu', 'categ_id': self.categ.id,
            'uom_id': self.uom_unit.id, 'uom_po_id': self.uom_unit.id,
        } for i in range(300)])
        self._make_po(self.vendor_a, [(p, 1, 10.0 + i) for i, p in enumerate(products)])
        draft = self._make_po(self.vendor_a, [(p, 1, 20.0) for p in products], confirm=False)
        draft.order_line.invalidate_recordset()

        Line = type(self.env['purchase.order.line'])
        original = Line._lpp_fetch_history
        calls = []

        def counting(model, *args, **kwargs):
            calls.append(args)
            return original(model, *args, **kwargs)

        with patch.object(Line, '_lpp_fetch_history', counting):
            signals = draft.order_line.mapped('lpp_price_signal')
        self.assertEqual(len(calls), 1, 'All 300 lines must be resolved with one history query')
        self.assertEqual(len(signals), 300)
        by_product = {l.product_id: l for l in draft.order_line}
        self.assertEqual(by_product[products[0]].lpp_last_price, 10.0)
        self.assertEqual(by_product[products[0]].lpp_price_signal, 'up')
        self.assertEqual(by_product[products[299]].lpp_last_price, 309.0)
        self.assertEqual(by_product[products[299]].lpp_price_signal, 'down')

    def test_14_onchange_on_new_line(self):
        self._make_po(self.vendor_a, [(self.product, 1, 100.0)])
        with Form(self.env['purchase.order']) as po_form:
            po_form.partner_id = self.vendor_a
            with po_form.order_line.new() as line:
                line.product_id = self.product
                line.price_unit = 130.0
                self.assertEqual(line.lpp_last_price, 100.0)
                self.assertEqual(line.lpp_price_signal, 'up')
                self.assertAlmostEqual(line.lpp_price_variance, 30.0, places=2)

    def test_15_price_stability_action(self):
        po = self._make_po(self.vendor_a, [(self.product, 1, 100.0)])
        action = po.order_line.action_lpp_price_stability()
        self.assertEqual(action['res_model'], 'lpp.vendor.price.report')
        self.assertIn(('product_id', '=', self.product.id), action['domain'])
        self.assertIn(('partner_id', '=', self.vendor_a.id), action['domain'])
        tmpl_action = self.product.product_tmpl_id.action_lpp_price_stability()
        self.assertEqual(tmpl_action['domain'], [('product_tmpl_id', '=', self.product.product_tmpl_id.id)])
