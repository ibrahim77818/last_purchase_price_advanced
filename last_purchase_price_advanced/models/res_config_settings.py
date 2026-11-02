# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    lpp_tracking_enabled = fields.Boolean(
        related='company_id.lpp_tracking_enabled', readonly=False)
    lpp_lookup_scope = fields.Selection(
        related='company_id.lpp_lookup_scope', readonly=False)
    lpp_neutral_band = fields.Float(
        related='company_id.lpp_neutral_band', readonly=False)
    lpp_stable_cv = fields.Float(
        related='company_id.lpp_stable_cv', readonly=False)
    lpp_volatile_cv = fields.Float(
        related='company_id.lpp_volatile_cv', readonly=False)
