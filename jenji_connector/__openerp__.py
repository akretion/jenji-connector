# -*- coding: utf-8 -*-
# Copyright 2018 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Jenji Connector',
    'version': '8.0.1.0.0',
    'category': 'Accounting',
    'license': 'AGPL-3',
    'summary': 'Odoo-Jenji Connector',
    'description' : 'Connecteur Jenji',
    'author': 'Akretion',
    'website': 'http://www.akretion.com',
    'depends': ['account', 'base_vat_sanitized'],
    'data': [
        'security/jenji_security.xml',
        'security/ir.model.access.csv',
        'views/jenji_transaction.xml',
        'wizard/jenji_transaction_import_view.xml',
        'data/sequence.xml',
        'data/cron.xml',
        'wizard/transaction_validate_view.xml',
        'wizard/transaction_status_update_view.xml',
    ],
    'installable': True,
    'application': True,
}
