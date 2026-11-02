# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    lpp_tracking_enabled = fields.Boolean(
        related='company_id.lpp_tracking_enabled',
        string='Last Price Tracking')
