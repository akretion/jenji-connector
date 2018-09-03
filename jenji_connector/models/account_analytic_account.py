# -*- coding: utf-8 -*-
# Copyright 2018 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import models, fields, api, _
from openerp.exceptions import Warning as UserError
import requests
import logging
logger = logging.getLogger(__name__)


class AccountAnalyticAccount(models.Model):
    _inherit = 'account.analytic.account'

    # TODO: move to akuit-specific module and use method
    # custom_field_create_new_entry()
    @api.model
    def jenji_sync(self):
        logger.info('Start to sync contracts to jenji')
        cxp = self.env['jenji.transaction'].get_connection_params()
        # The last part of the URL ('analytic') is the technical name
        # of the custom field in Jenji
        url = cxp['url'] + '/s/group-custom-list/v1/analytic/'
        auth = (cxp['login'], cxp['password'])
        for aa in self.search([('type', '=', 'contract')]):
            print "aa=", aa
            aa_jenji_code = 'odoo-%d' % aa.id
            jdict = {
                'code': aa_jenji_code,
                'labels': {
                    'en': aa.name,
                    'fr': aa.name,
                    }
                }
            if aa.manager_id and aa.manager_id.partner_id.email:
                jdict['scope'] = aa.manager_id.partner_id.email.strip()

            url_complete = url + aa_jenji_code
            try:
                logger.info(
                    'Try to sync contract ID %d with payload %s', aa.id, jdict)
                res = requests.put(url_complete, auth=auth, json=jdict)
            except Exception as e:
                logger.error('Request to %s failed: %s', url_complete, e)
                continue
            logger.info('Answer code=%d', res.status_code)
            if res.status_code != 200:
                logger.error(
                    'Request to %s with payload %s answered status code %s',
                    url_complete, jdict, res.status_code)
            else:
                logger.info(
                    'Successfuly sync of contract %s ID %d', aa.name, aa.id)

        logger.info('End sync contracts to jenji')
