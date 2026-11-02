# -*- coding: utf-8 -*-
from datetime import datetime

from odoo.tests.common import TransactionCase


class LppCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.company.write({
            'lpp_tracking_enabled': True,
            'lpp_lookup_scope': 'vendor',
            'lpp_neutral_band': 0.0,
            'lpp_stable_cv': 2.0,
            'lpp_volatile_cv': 10.0,
        })
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.uom_dozen = cls.env.ref('uom.product_uom_dozen')
        cls.vendor_a = cls.env['res.partner'].create({'name': 'LPP Vendor A', 'is_company': True})
        cls.vendor_b = cls.env['res.partner'].create({'name': 'LPP Vendor B', 'is_company': True})
        cls.vendor_a_contact = cls.env['res.partner'].create({
            'name': 'LPP Vendor A - Buyer', 'parent_id': cls.vendor_a.id})
        cls.categ = cls.env['product.category'].create({'name': 'LPP Category'})
        cls.product = cls._make_product('LPP Widget')
        cls.product_2 = cls._make_product('LPP Bolt')

        # Foreign currency with fully controlled rates for this company.
        company_currency = cls.company.currency_id
        cls.foreign = cls.env.ref('base.EUR') if company_currency != cls.env.ref('base.EUR') \
            else cls.env.ref('base.USD')
        cls.foreign.active = True
        cls.env['res.currency.rate'].search([
            ('currency_id', '=', cls.foreign.id),
            ('company_id', 'in', [cls.company.id, False]),
        ]).unlink()
        cls.env['res.currency.rate'].create([
            {'name': '2024-01-01', 'rate': 0.5, 'currency_id': cls.foreign.id,
             'company_id': cls.company.id},
            {'name': '2024-06-01', 'rate': 0.8, 'currency_id': cls.foreign.id,
             'company_id': cls.company.id},
        ])

    @classmethod
    def _make_product(cls, name, **vals):
        return cls.env['product.product'].create(dict({
            'name': name,
            'type': 'consu',
            'categ_id': cls.categ.id,
            'uom_id': cls.uom_unit.id,
            'purchase_ok': True,
        }, **vals))

    @classmethod
    def _make_po(cls, partner, lines, confirm=True, currency=None, date=None):
        """lines: list of (product, qty, price[, uom])."""
        date = date or datetime(2024, 3, 1, 10, 0)
        order_lines = []
        for spec in lines:
            product, qty, price = spec[:3]
            uom = spec[3] if len(spec) > 3 else product.uom_id
            order_lines.append((0, 0, {
                'product_id': product.id,
                'name': product.name,
                'product_qty': qty,
                'product_uom_id': uom.id,
                'price_unit': price,
                'date_planned': date,
            }))
        po = cls.env['purchase.order'].create({
            'partner_id': partner.id,
            'company_id': cls.company.id,
            'currency_id': (currency or cls.company.currency_id).id,
            'date_order': date,
            'order_line': order_lines,
        })
        # keep the price we asked for (onchanges may apply a pricelist price)
        for line, spec in zip(po.order_line, lines):
            line.price_unit = spec[2]
        if confirm:
            po.button_confirm()
            po.date_approve = date
        return po
