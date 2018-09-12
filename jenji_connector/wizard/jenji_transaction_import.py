# -*- coding: utf-8 -*-
# Copyright 2018 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import models, fields, api, _
from openerp.exceptions import Warning as UserError
from openerp.tools import float_is_zero
import requests
import logging

logger = logging.getLogger(__name__)


class JenjiTransactionImport(models.TransientModel):
    _name = 'jenji.transaction.import'
    _description = 'Import Jenji Transactions'

    start_date = fields.Date(
        string='Start Month', required=True, default='2018-01-01')
    end_date = fields.Date(
        string='End Month', required=True,
        default=fields.Date.context_today)

    @api.model
    def _prepare_speeddict(self):
        # TODO think multi-company
        company = self.env.user.company_id
        prec = self.env['decimal.precision'].precision_get('Account')
        jenji_partner = self.env['res.partner'].search([
            ('parent_id', '=', False),
            ('supplier', '=', True),
            ('sanitized_vat', '=', 'FR96799321641'),
            ], limit=1)
        if not jenji_partner:
            raise UserError(_(
                "Missing Supplier Gleetr SAS (Jenji) "
                "with VAT number FR96799321641."))

        speeddict = {
            'products': {}, 'analytic': {}, 'partners': {},
            'countries': {}, 'currencies': {},
            'company_currency_id': company.currency_id.id,
            'prec': prec, 'jenji_partner': jenji_partner}
        product_sinfos = self.env['product.supplierinfo'].search([
            ('name', '=', jenji_partner.id),
            '|', ('company_id', '=', False), ('company_id', '=', company.id)])
        for product_sinfo in product_sinfos:
            if not product_sinfo.product_code:
                raise UserError(_(
                    "Missing Supplier Product Code on supplier info of "
                    "product '%s' with partner '%s'")
                    % (product_sinfo.product_tmpl_id.display_name,
                       jenji_partner.display_name))
            speeddict['products'][product_sinfo.product_code.strip()] =\
                product_sinfo.product_tmpl_id.product_variant_ids[0].id
        partners = self.env['res.partner'].search(
            [('email', '!=', False)], order='supplier')
        for partner in partners:
            email = partner.email.strip()
            if email:
                if email in speeddict['partners']:
                    logger.warning(
                        'Email %s present twice on partners (ID %d and %d)',
                        partner.id, speeddict['partners'][email])
                else:
                    speeddict['partners'][email] =\
                        partner.commercial_partner_id.id
        for country in self.env['res.country'].search([('code', '!=', False)]):
            speeddict['countries'][country.code.strip()] = country.id
        analytic_res = self.env['account.analytic.account'].search_read(
            [('company_id', '=', company.id), ('code', '!=', False)], ['code'])
        for analytic in analytic_res:
            analytic_code = analytic['code'].strip().lower()
            speeddict['analytic'][analytic_code] = analytic['id']

        countries = self.env['res.country'].search_read(
            [('code', '!=', False)], ['code'])
        for country in countries:
            speeddict['countries'][country['code'].strip()] = country['id']

        currencies = self.env['res.currency'].search_read(
            ['|', ('active', '=', True), ('active', '=', False)], ['name'])
        for curr in currencies:
            speeddict['currencies'][curr['name']] = curr['id']

        return speeddict

    @api.model
    def _prepare_transaction(self, line, speeddict, action='create'):
        jto = self.env['jenji.transaction']
        product_id = account_analytic_id = expense_categ_code = False
        country_id = speeddict['countries'].get(line.get('country'))
        currency_id = speeddict['currencies'].get(line.get('currency'))
        if not currency_id:
            currency_id = speeddict['company_currency_id']
        if line.get('type') == 'M':
            total_currency = line.get('mileageTotal', 0.0)
            total_untaxed_currency = total_currency
            mileage_expense = True
            expense_categ_code = 'KM'
            description = line.get('description')
        else:
            mileage_expense = False
            total_currency = line.get('total', 0.0)
            total_untaxed_currency =\
                line.get('totalWoT', 0.0) or total_currency
            if not line.get('category'):
                raise UserError(_(
                    "Missing category on expense ID %s") % line.get('id'))
            expense_categ_code = line['category']
            description = line.get('explanation')
        if expense_categ_code not in speeddict['products']:
            raise UserError(_(
                "No product in Odoo with supplier %s and "
                "supplier product code %s") % (
                    speeddict['jenji_partner'].display_name,
                    expense_categ_code))
        product_id = speeddict['products'][expense_categ_code]
        if currency_id != speeddict['company_currency_id']:
            total_company_currency = line.get('totalConverted', 0.0)
            if not float_is_zero(
                    total_currency,
                    precision_digits=speeddict['prec']):
                total_untaxed_company_currency =\
                    total_company_currency *\
                    total_untaxed_currency / total_currency
            else:
                total_untaxed_company_currency = 0
        else:
            total_company_currency = total_currency
            total_untaxed_company_currency = total_untaxed_currency
        analytic_id =line.get('customFields').get('analytic')
        if analytic_id:
                analytic_id = analytic_id.replace('odoo-','')
        if 'tags' in line.keys():
            tags=', '.join(line.get('tags'))
        else:
            tags=None
        vals = {
            'unique_import_id': line.get('id'),
            'date': jto.timestamp2date(line['time']),
            'country_id': country_id,
            'merchant': line.get('seller'),
            'billable': line.get('billable'),
            'currency_id': currency_id,
            'expense_categ_code': expense_categ_code,
            'description': description,
            'product_id': product_id,
           'account_analytic_id': analytic_id,
            'partner_id': speeddict['partners'][line['userId']],
            'tags' : tags,
            'total_company_currency': total_company_currency,
            'total_untaxed_company_currency': total_untaxed_company_currency,
            'total_currency': total_currency,
            'total_untaxed_currency': total_untaxed_currency,
            # 'image_url': line.get('attachment'),
            'mileage_expense': mileage_expense,
        }
        return vals

    @api.multi
    def jenji_import(self):
        jto = self.env['jenji.transaction']
        speeddict = self._prepare_speeddict()
        logger.info('Importing Jenji transaction via API')
        exiting_transactions = {}
        existings = jto.search([])
        for l in existings:
            exiting_transactions[l.unique_import_id] = l
        jt_ids = []
        cxp = jto.get_connection_params()
        start_date_dt = fields.Date.from_string(self.start_date)
        end_date_dt = fields.Date.from_string(self.end_date)
        payload = {
            'endMonth': end_date_dt.month,
            'endYear': end_date_dt.year,
            'startMonth': start_date_dt.month,
            'startYear': start_date_dt.year,
            }

        try:
            res = requests.post(
                cxp['url'] + '/s/search/v1',
                auth=(cxp['login'], cxp['password']),
                json=payload)
        except Exception as e:
            raise UserError(_(
                "Failed to connect to %s. Technical error: %s")
                % (cxp['url'], e))
        if res.status_code != 200:
            raise UserError(_(
                "Error in the connexion to the Jenji webservice. "
                "Received HTTP error code %s") % res.status_code)
        answer = res.json()
        from pprint import pprint
        pprint(answer)
        pprint(speeddict)
        for user in answer['hierarchy'][0]['users']:
            # print "user=", user
            user_email = user['id']
            if user_email not in speeddict['partners']:
                print "RAISE USER not in speedict partner"
                # raise UserError(_(  # TODO
                #    "No partner with email %s") % user_email)

            for line in user['expenses']:
                if not line.get('state'):
                    continue
                if line.get('state') != 'ACCEPTED':
                    continue
                print "line=", line
                existing_import_id = exiting_transactions.get(line['id'])
                if existing_import_id:
                    logger.info('Transaction %s already imported', line['id'])
                    continue
                    transaction = exiting_transactions[existing_import_id]
                    logger.debug(
                        'Existing line with unique ID %s (odoo ID %s, '
                        'state %s)', existing_import_id, transaction.id,
                        transaction.state)
                    if transaction.state == 'draft':
                        # update existing lines
                        wvals = self._prepare_transaction(
                            line, speeddict, action='update')
                        transaction.write(wvals)
                        jt_ids.append(transaction.id)
                    continue
                vals = self._prepare_transaction(line, speeddict)
                transaction = jto.create(vals)
                jt_ids.append(transaction.id)
        if not jt_ids:
            raise UserError(_("No Jenji transaction created nor updated."))
        action = self.env['ir.actions.act_window'].for_xml_id(
            'jenji_connector', 'jenji_transaction_action')
        action.update({
            'domain': "[('id', 'in', %s)]" % jt_ids,
            'views': False,
            'nodestroy': False,
            })
        return action

    # TODO libellé frais KM
