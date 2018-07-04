# -*- coding: utf-8 -*-
# Copyright (C) 2018 Akretion France (www.akretion.com)
# @author Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import fields, models, api


class JenjiTransactionStatusUpdate(models.TransientModel):
    _name = 'jenji.transaction.status.update'
    _description = 'Update Jenji Transaction Statuts'

    jenji_state = fields.Selection([
        ('posted', 'Posted'),
        ('paid', 'Paid'),
        ], string='New Jenji Status', required=True)
    paid_date = fields.Date(
        string='Payment Date', default=fields.Date.context_today)
    paid_method = fields.Char(
        string='Payment Method', default=u'Virement')

    @api.multi
    def run(self):
        self.ensure_one()
        assert self.env.context.get('active_model') == 'jenji.transaction',\
            'Source model must be jenji transactions'
        assert self.env.context.get('active_ids'), 'No transactions selected'
        transactions = self.env['jenji.transaction'].browse(
            self.env.context['active_ids'])
        if self.jenji_state == 'posted':
            transactions.jenji_posted_status()
        elif self.jenji_state == 'paid':
            transactions.jenji_paid_status(
                date=self.paid_date or None,
                method=self.paid_method)
        return
