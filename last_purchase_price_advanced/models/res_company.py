# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    lpp_tracking_enabled = fields.Boolean(
        string='Advanced Last Purchase Price',
        default=False,
        help='Show the last confirmed purchase price, its variance and a '
             'price signal on every purchase order line.')
    lpp_lookup_scope = fields.Selection(
        selection=[
            ('vendor', 'Same Vendor'),
            ('any', 'Any Vendor'),
        ],
        string='Last Price Source',
        default='vendor',
        required=True,
        help='Same Vendor: compare with the last price paid to the vendor of '
             'the order.\nAny Vendor: compare with the last price paid to '
             'any vendor for the product.')
    lpp_neutral_band = fields.Float(
        string='Neutral Variance Band (%)',
        default=0.0,
        digits=(16, 2),
        help='Variations whose absolute value does not exceed this '
             'percentage are flagged as unchanged.')
    lpp_stable_cv = fields.Float(
        string='Stable Threshold (CV %)',
        default=2.0,
        digits=(16, 2),
        help='Vendor/product pairs whose coefficient of variation does not '
             'exceed this value are classified as Stable.')
    lpp_volatile_cv = fields.Float(
        string='Volatile Threshold (CV %)',
        default=10.0,
        digits=(16, 2),
        help='Vendor/product pairs whose coefficient of variation exceeds '
             'this value are classified as Volatile.')

    @api.constrains('lpp_neutral_band', 'lpp_stable_cv', 'lpp_volatile_cv')
    def _check_lpp_thresholds(self):
        for company in self:
            if min(company.lpp_neutral_band, company.lpp_stable_cv,
                   company.lpp_volatile_cv) < 0:
                raise ValidationError(_('Price intelligence thresholds cannot be negative.'))
            if company.lpp_volatile_cv < company.lpp_stable_cv:
                raise ValidationError(_('The volatile threshold must be greater than or equal to the stable threshold.'))
