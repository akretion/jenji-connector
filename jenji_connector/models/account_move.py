# -*- coding: utf-8 -*-
# Copyright 2019 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import models, fields


class AccountMove(models.Model):
    _inherit = 'account.move'

    jenji_transaction_ids = fields.One2many(
        'jenji.transaction', 'move_id', string='Jenji Transactions')
