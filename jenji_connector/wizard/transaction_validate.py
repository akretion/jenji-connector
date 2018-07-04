# -*- coding: utf-8 -*-
# Copyright (C) 2018 Akretion France (www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import models, api


class JenjiTransactionValidate(models.TransientModel):
    _name = 'jenji.transaction.validate'
    _description = 'Validate several Jenji Transaction'

    @api.multi
    def run(self):
        self.ensure_one()
        assert self.env.context.get('active_model') == 'jenji.transaction',\
            'Source model must be jenji transactions'
        assert self.env.context.get('active_ids'), 'No trdonations selected'
        transactions = self.env['jenji.transaction'].browse(
            self.env.context['active_ids'])
        transactions.process_lines()
        return
