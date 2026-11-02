# -*- coding: utf-8 -*-
{
    'name': 'Last Purchase Price Advanced',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Purchase',
    'summary': 'Last purchase price on PO lines with UoM / multi-currency '
               'normalization, variance signals and a Vendor Price Stability '
               'report (Pivot, Graph, Excel, PDF).',
    'description': """
Last Purchase Price Advanced
============================
* Company-level toggle in Purchase Settings (Price Intelligence section).
* On every purchase order line: last confirmed purchase price normalized to
  the line's unit of measure and currency, original UoM, original currency
  and the historical currency rate, variance %% and an up/down signal.
* Vendor Price Stability analysis (pivot / graph / list) under
  Purchase > Reporting, plus a filterable Excel export and QWeb PDF.
* Last price, variance and signal in the "Compare Product Lines" view of
  alternative RFQs (Purchase Agreements).
* All lookups are batched into a single SQL query per compute, whatever
  the number of lines.
* Full Arabic (ar_001) translation, RTL-ready PDF and Excel layouts.
""",
    'author': 'Ibrahim Yahia',
    'website': 'https://www.linkedin.com/in/ibrahim-yahia',
    'license': 'LGPL-3',
    'depends': ['purchase', 'purchase_requisition'],
    'external_dependencies': {'python': ['xlsxwriter']},
    'data': [
        'security/ir.model.access.csv',
        'security/lpp_security.xml',
        'views/lpp_vendor_price_report_views.xml',
        'views/res_config_settings_views.xml',
        'views/purchase_order_views.xml',
        'views/purchase_order_line_compare_views.xml',
        'views/product_views.xml',
        'wizard/lpp_stability_wizard_views.xml',
        'report/lpp_stability_report.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'last_purchase_price_advanced/static/src/scss/lpp_backend.scss',
        ],
        'web.report_assets_common': [
            'last_purchase_price_advanced/static/src/scss/lpp_report.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
