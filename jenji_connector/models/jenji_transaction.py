# -*- coding: utf-8 -*-
# Copyright 2018 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import models, fields, api, tools, _
from openerp.exceptions import Warning as UserError
import openerp.addons.decimal_precision as dp
from openerp.tools import float_compare, float_is_zero
from datetime import datetime, timedelta
import time
import requests
import logging

logger = logging.getLogger(__name__)


class JenjiTransaction(models.Model):
    _name = 'jenji.transaction'
    _description = 'Jenji Transaction'
    _order = 'date desc'

    name = fields.Char(string='Number', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, readonly=True,
        default=lambda self: self.env['res.company']._company_default_get(
            'jenji.transaction'))
    company_currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True,
        string="Company Currency")
    description = fields.Char(
        string='Description', readonly=True,
        states={'draft': [('readonly', False)]})
    unique_import_id = fields.Char(
        string='Unique Identifier', readonly=True, copy=False)
    date = fields.Date(
        string='Date', required=True, readonly=True,
        help="This is the date of the bank transaction. It may be a few "
        "days after the payment date.")
    expense_categ_code = fields.Char(
        string='Expense Category Code', readonly=True)
    product_id = fields.Many2one(
        'product.product', string='Expense Product', ondelete='restrict',
        readonly=True, states={'draft': [('readonly', False)]})
    expense_account_id = fields.Many2one(
        'account.account', compute='compute_expense_account_id', readonly=True,
        string='Expense Account of the Product')
    force_expense_account_id = fields.Many2one(
        'account.account', string='Override Expense Account',
        help="Override the expense account configured on the product",
        domain=[('type', 'not in', ('view', 'closed', 'consolidation'))])
    account_analytic_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account',
        domain=[('type', '!=', 'view')], readonly=True,
        states={'draft': [('readonly', False)]}, ondelete='restrict')
    country_id = fields.Many2one(
        'res.country', string='Country', readonly=True)
    merchant = fields.Char(string='Merchant', readonly=True)
    total_untaxed_company_currency = fields.Float(
        digits=dp.get_precision('Account'),
        states={'draft': [('readonly', False)]},
        readonly=True, string='Untaxed Company Currency')
    vat_company_currency = fields.Float(
        string='VAT Amount',
        # not readonly, because accountant may have to change the value
        digits=dp.get_precision('Account'), store=True,
        compute='_compute_vat_company_currency',
        help='VAT Amount in Company Currency')
    deductible_vat_company_currency = fields.Float(
        string='Deductible VAT Amount',
        digits=dp.get_precision('Account'), store=True,
        compute='_compute_vat_company_currency',
        help='Deductible VAT Amount in Company Currency')
    total_company_currency = fields.Float(
        string='Total Amount in Company Currency',
        digits=dp.get_precision('Account'), readonly=True)

    currency_id = fields.Many2one(
        'res.currency', string='Expense Currency', readonly=True)
    total_currency = fields.Float(
        string='Total Amount in Expense Currency', readonly=True)
    total_untaxed_currency = fields.Float(
        string='Total Untaxed in Expense Currency', readonly=True)
    image_url = fields.Char(string='Image URL', readonly=True)
    receipt_lost = fields.Boolean(
        string='Receipt Lost', readonly=True,
        states={'draft': [('readonly', False)]})
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Accounted'),
        ('paid', 'Paid'),
        ], string='State', default='draft', readonly=True)
    jenji_state = fields.Selection([
        ('accounted', 'Accounted'),
        ('paid', 'Paid'),
        ], string='Status of the Transaction on Jenji', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='User', ondelete='restrict',
        readonly=True, states={'draft': [('readonly', False)]})
    partner_id = fields.Many2one(
        'res.partner', string='Partner', required=True,
        domain=[('supplier', '=', True), ('parent_id', '=', False)],
        states={'draft': [('readonly', False)]}, ondelete='restrict',
        readonly=True)
    force_expense_account_id = fields.Many2one(
        'account.account', string='Override Expense Account',
        help="Override the expense account configured on the product",
        states={'draft': [('readonly', False)]}, readonly=True,
        domain=[('type', 'not in', ('view', 'closed', 'consolidation'))])
    mileage_expense = fields.Boolean(string='Mileage Expense', readonly=True)
    move_id = fields.Many2one(
        'account.move', string='Expense Journal Entry', readonly=True)
    billable = fields.Boolean(
        string='Billable', states={'draft': [('readonly', True)]},
        readonly=True)
    customer_invoice_id = fields.Many2one(
        'account.invoice', string='Customer Invoice', readonly=True)
    tags = fields.Char(
        string='Tags', readonly=True, size=128)
    meal_type = fields.Char(
        string='Meal Type', readonly=True)

    _sql_constraints = [(
        'unique_import_id',
        'unique(unique_import_id)',
        'A jenji transaction can be imported only once!')]

    @api.multi
    @api.depends(
        'product_id.product_tmpl_id.property_account_expense',
        'product_id.product_tmpl_id.categ_id.'
        'property_account_expense_categ')
    def compute_expense_account_id(self):
        for trans in self:
            account_id = False
            if trans.product_id:
                account_id = trans.product_id.property_account_expense.id
                if not account_id:
                    account_id = trans.product_id.categ_id.\
                        property_account_expense_categ.id
            trans.expense_account_id = account_id

    @api.multi
    @api.depends(
        'total_untaxed_company_currency', 'total_company_currency',
        'product_id')
    def _compute_vat_company_currency(self):
        # cf get_precision_tax() in addons/account/account.py line 1832
        prec = self.env['decimal.precision'].precision_get('Account') + 3
        for trans in self:
            vat_company_currency = trans.total_company_currency -\
                trans.total_untaxed_company_currency
            trans.vat_company_currency = vat_company_currency
            deductible_vat_cc = 0
            taxamount = 0.0
            for tax in trans.sudo().product_id.supplier_taxes_id:
                if tax.company_id.id==trans.company_id.id:
                    taxamount = tax.amount
                    break
            if not float_is_zero( taxamount, precision_digits=prec):
                deductible_vat_cc = vat_company_currency
            trans.deductible_vat_company_currency = deductible_vat_cc

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'jenji.transaction')
        return super(JenjiTransaction, self).create(vals)

    @api.model
    def get_connection_params(self):
        username = tools.config.get('jenji_user', False)
        password = tools.config.get('jenji_password', False)
        environment = tools.config.get('jenji_envir', 'demo')
        if not username or not password or not environment:
            raise UserError(_(
                "One of the 3 Jenji config parameters is missing in the Odoo "
                "server config file."))
        if environment == 'prod':
            url = 'https://api.jenji.io'
        else:
            url = 'https://api-test.jenji.io'
        logger.info(
            'Jenji url %s login %s', url, username)
        cxp = {
            'url': url,
            'login': username,
            'password': password,
            'auth': (username, password),
            }
        return cxp

    @api.model
    def timestamp2date(self, timestamp):
        if not timestamp or not isinstance(timestamp, (int, long)):
            return False
        dt = datetime.fromtimestamp(timestamp/1000.0)
        date_str = fields.Date.to_string(dt)
        return date_str

    @api.model
    def date2timestamp(self, date_dt=None):
        if date_dt is None:
            date_dt = datetime.now()
        timestamp = time.mktime(date_dt.timetuple())
        jenji_ts = timestamp * 1000
        return jenji_ts

    @api.model
    def convert_datetime_to_utc(self, date_time_str):
        # %z can only be used in strptime() starting from python 3.2
        if date_time_str[-2:].isdigit():
            date_time_dt = datetime.strptime(
                date_time_str[:19], '%Y-%m-%d %H:%M:%S')
            if date_time_str[20] == '+':
                date_time_dt -= timedelta(
                    hours=int(date_time_str[21:23]),
                    minutes=int(date_time_str[23:]))
            elif date_time_str[20] == '-':
                date_time_dt += timedelta(
                    hours=int(date_time_str[21:23]),
                    minutes=int(date_time_str[23:]))
        else:
            date_time_dt = datetime.strptime(
                date_time_str, '%Y-%m-%d %H:%M:%S %Z')
        return date_time_dt

    @api.multi
    def open_image_url(self):
        if not self.image_url:
            raise UserError(_(
                "Missing image URL for jenji transaction %s.") % self.name)
        action = {
            'type': 'ir.actions.act_url',
            'url': self.image_url,
            'target': 'new',
            }
        return action

    @api.multi
    def unlink(self):
        for line in self:
            if line.state != 'draft':
                raise UserError(_(
                    "Cannot delete Jenji transaction '%s' which is in "
                    "not in draft state.") % line.name)
            if line.move_id:
                raise UserError(_(
                    "Cannot delete Jenji transaction '%s which is linked "
                    "to a journal item.") % line.name)
        return super(JenjiTransaction, self).unlink()

    @api.multi
    def _prepare_move(self):
        prec = self.env['decimal.precision'].precision_get('Account')
        firstline = self[0]
        company = firstline.company_id
        partner_group = {}  # key = partner recordset
        # value = {'lines': lines multirecordset, 'vals': vals}
        # group by partner
        for line in self:
            if line.state != 'draft':
                continue
            if company:
                if company != line.company_id:
                    raise UserError(_(
                        "The selected Jenji transaction are not all from "
                        "the same company"))
            else:
                company = line.company_id
            if line.move_id:
                raise UserError(_(
                    "The Jenji transaction %s is already linked to an "
                    "expense journal entry") % line.name)
            if not line.product_id:
                raise UserError(_(
                    "Missing Expense Product on Jenji transaction %s")
                    % line.name)
            if not line.partner_id:
                raise UserError(_(
                    "Missing partner on Jenji transaction %s") % line.name)
            if line.partner_id in partner_group:
                partner_group[line.partner_id]['lines'] += line
            else:
                partner_group[line.partner_id] = {'lines': line}

        journal = self.env['account.journal'].search([
            ('type', '=', 'purchase'),
            ('company_id', '=', company.id)], limit=1)
        if not journal:
            raise UserError(_(
                "Missing purchase journal in company %s") % company.name)
        date = fields.Date.context_today(self)
        period = self.env['account.period'].with_context(
            company_id=company.id).find(dt=date)
        for partner, pdict in partner_group.items():
            ref = '-'.join([line.name for line in pdict['lines']])
            if len(ref) > 40:
                ref = ref[:40] + '...'
            vals = {
                'ref': ref,
                'journal_id': journal.id,
                'date': date,
                'period_id': period.id,
                'company_id': company.id,
            }
            mlines = []
            total = 0.0
            for line in pdict['lines']:
                account_id = line.product_id.property_account_expense.id
                if not account_id:
                    account_id = line.product_id.categ_id.\
                        property_account_expense_categ.id
                if not account_id:
                    raise UserError(_(
                        "Missing expense account on product '%s' or on it's "
                        "related product category.")
                        % line.product_id.display_name)
                debit = credit = 0
                amount_without_tax = line.total_company_currency -\
                    line.deductible_vat_company_currency
                if float_compare(
                        line.total_company_currency, 0,
                        precision_digits=prec) > 0:
                    debit = amount_without_tax
                else:
                    credit = amount_without_tax * -1
                name = line.name
                if line.description and line.merchant:
                    name = u'%s %s (%s)' % (
                        name, line.description, line.merchant)
                elif line.description:
                    name = u'%s %s' % (name, line.description)
                elif line.merchant:
                    name = u'%s %s' % (name, line.merchant)
                mlines.append((0, 0, {
                    'debit': debit,
                    'credit': credit,
                    'account_id': account_id,
                    'partner_id': line.partner_id.id,
                    'name': name,
                    }))
                total += (debit - credit)
                if not float_is_zero(
                        line.deductible_vat_company_currency,
                        precision_digits=prec):
                    tax = line.product_id.supplier_taxes_id[0]
                    debit = credit = 0
                    if float_compare(
                            line.deductible_vat_company_currency, 0,
                            precision_digits=prec) > 0:
                        debit = line.deductible_vat_company_currency
                        account_id = tax.account_collected_id.id
                    else:
                        credit = line.deductible_vat_company_currency * -1
                        account_id = tax.account_paid_id.id
                    if not account_id:
                        raise UserError(_(
                            "Missing account on tax '%s'") % tax.display_name)
                    mlines.append((0, 0, {
                        'debit': debit,
                        'credit': credit,
                        'account_id': account_id,
                        'partner_id': line.partner_id.id,
                        'name': name,
                        }))
                    total += (debit - credit)
            # Counter-part
            debit = credit = 0
            if float_compare(total, 0, precision_digits=prec) > 0:
                credit = total
            else:
                debit = total
            mlines.append((0, 0, {
                'debit': debit,
                'credit': credit,
                'name': ref,
                'partner_id': line.partner_id.id,
                'account_id': line.partner_id.property_account_payable.id,
                }))
            vals['line_id'] = mlines
            partner_group[partner]['vals'] = vals
        return partner_group

    def generate_move(self):
        partner_group = self._prepare_move()
        for pdict in partner_group.values():
            move = self.env['account.move'].create(pdict['vals'])
            move.post()
            pdict['lines'].write({'move_id': move.id})
        return move

    @api.multi
    def process_lines(self):
        self.generate_move()
        self.write({'state': 'open'})

    @api.multi
    def back2draft(self):
        for trans in self:
            if trans.move_id:
                trans.move_id.button_cancel()
                trans.move_id.unlink()
        self.write({'state': 'draft'})
        return True

    @api.multi
    def open2paid(self):
        self.write({'state': 'paid'})

    @api.model
    def cron_jenji_state_update(self):
        logger.info('START cron jenji state update')
        trans_to_mark_as_accounted = self.search([
            ('state', 'not in', ('draft', 'paid')),
            '|', ('jenji_state', '!=', 'accounted'), ('jenji_state', '=', False)])
        if trans_to_mark_as_accounted:
            trans_to_mark_as_accounted.jenji_accounted_status()
        trans_to_mark_as_paid = self.search([
            ('state', '=', 'paid'),
            '|', ('jenji_state', '!=', 'paid'), ('jenji_state', '=', False)])
        if trans_to_mark_as_paid:
            trans_to_mark_as_paid.jenji_paid_status()
        logger.info('END cron jenji state update')

    @api.multi
    def jenji_accounted_status(self):
        trans_to_update = self.filtered(
            lambda t: t.move_id and t.unique_import_id and t.jenji_state != 'paid')
        logger.info(
            "transactions to update to accounted: %s", trans_to_update)
        if not trans_to_update:
            raise UserError(_(
                "There are no transactions to update."))
        cxp = self.get_connection_params()
        expense_jids = [t.unique_import_id for t in trans_to_update]
        payload = {
            'expenseIds': expense_jids,
            }
        res = False
        try:
            res = requests.post(
                cxp['url'] + '/s/bookkeeper/v2/expense',
                auth=cxp['auth'],
                json=payload)
        except Exception as e:
            raise UserError(_(
                "Failure in the webservice request to Jenji: "
                "%s") % e)
        assert res
        if res.status_code not in (200, 201):
            raise UserError(_(
                "Error in the connexion to the Jenji webservice "
                "/s/bookkeeper/v2/expense. "
                "Received HTTP error code %s") % res.status_code)
        answer = res.json()
        export_id = answer.get('id')
        if not export_id:
            raise UserError(_(
                "Missing Export ID in the answer of the webservice"))
        logger.info('Successful Jenji bookkeeper export_id = %s', export_id)
        res = False
        try:
            res = requests.post(
                cxp['url'] + '/s/export/v1/export/%s' % export_id,
                auth=cxp['auth'],
                json={'state': 'ACCOUNTED'})
        except Exception as e:
            raise UserError(_(
                "Failure in the webservice request for Jenji: "
                "%s") % e)
        assert res
        if res.status_code != 200:
            raise UserError(_(
                "Error in the connexion to the Jenji webservice "
                "/s/export/v1/export/%s. "
                "Received HTTP error code %s")
                % (export_id, res.status_code))
        trans_to_update.write({'jenji_state': 'accounted'})
        logger.info('Successfully tagged jenji export ID %s as ACCOUNTED',
                    export_id)

    @api.multi
    def jenji_paid_status(self, method='Virement', date=None):
        trans_to_update = self.filtered(
            lambda t: t.move_id and t.unique_import_id and t.state == 'paid')
        logger.info("transactions to update to paid: %s", trans_to_update)
        if not trans_to_update:
            return
        cxp = self.get_connection_params()
        expense_jids = [t.unique_import_id for t in trans_to_update]
        payload = {
            'expenseIds': expense_jids,
            }
        res = False
        try:
            res = requests.post(
                cxp['url'] + '/s/payroll/v1/expense',
                auth=cxp['auth'],
                json=payload)
        except Exception as e:
            raise UserError(_(
                "Failure in the webservice request to Jenji: "
                "%s") % e)
        if res.status_code not in (200, 201):
            raise UserError(_(
                "Error in the connexion to the Jenji webservice "
                "/s/payroll/v1/expense. "
                "Received HTTP error code %s") % res.status_code)
        answer = res.json()
        export_id = answer.get('id')
        if not export_id:
            raise UserError(_(
                "Missing Export ID in the answer of the webservice"))
        logger.info('Successful Jenji payroll export_id = %s', export_id)
        res = False
        if date is None:
            date = fields.Date.context_today(self)
        date_dt = fields.Date.from_string(date)

        payload = {
            'state': 'PAID',
            'method': method,
            'time': self.date2timestamp(date_dt),
            }
        try:
            res = requests.post(
                cxp['url'] + '/s/payroll/v1/export/%s' % export_id,
                auth=cxp['auth'], json=payload)
        except Exception as e:
            raise UserError(_(
                "Failure in the webservice request for Jenji: "
                "%s") % e)
        if res.status_code != 200:
            raise UserError(_(
                "Error in the connexion to the Jenji webservice "
                "/s/payroll/v1/export/%s. "
                "Received HTTP error code %s")
                % (export_id, res.status_code))
        trans_to_update.write({'jenji_state': 'paid'})
        logger.info(
            'Successfully tagged jenji export ID %s as PAID with method %s',
            export_id, method)

    @api.model
    def custom_field_create_new_entry(
            self, field_name, code, labels, user_email):
        # Use sample:
        # self.env['jenji.transaction'].custom_field_create_new_entry(
        #    'analytic', 'TESTALEXIS3',
        #     {'en': 'Alexis3 English', 'fr': 'Alexis3 Français'},
        #     'alexis.delattre@akretion.com')
        logger.info(
            'Requesting Jenji to add a new entry %s (labels=%s) '
            'to custom field %s scope %s',
            code, labels, field_name, user_email)
        cxp = self.get_connection_params()
        assert isinstance(labels, dict), 'labels must be a dict'
        assert labels.get('en'), 'missing en entry in labels dict'
        payload = {
            'code': code,
            'labels': labels,
            }
        if user_email:
            payload['scope'] = user_email
        res = False
        url_end = '/s/group-custom-list/v1/%s/%s' % (field_name, code)
        logger.info('Connecting to Jenji %s with payload %s', url_end, payload)
        try:
            res = requests.put(
                cxp['url'] + url_end, auth=cxp['auth'], json=payload)
        except Exception as e:
            raise UserError(_(
                "Failure in the webservice request to Jenji: "
                "%s") % e)
        if res.status_code != 200:
            raise UserError(_(
                "Error in the connexion to the Jenji webservice %s"
                "Received HTTP error code %s") % (url_end, res.status_code))
        logger.info('Successfully used Jenji WS %s', url_end)

    def get_detailed_pdf(self):
        cxp = self.get_connection_params()
        logger.info('Starting to get detailed PDF for transactions %s', self)
        expense_uuids = [
            trans.unique_import_id for trans in self if trans.unique_import_id]
        datetime_in_tz_dt = fields.Datetime.context_timestamp(
            self, datetime.now())
        cur_date_tz = datetime_in_tz_dt.strftime('%Y%m%d%H%M%S')
        res = False
        url_pdf = '/s/user-exports/v1/pdf/detailed-light'
        try:
            json = {
                'expenseIds': expense_uuids,
                'label': 'Jenji_export_%s' % cur_date_tz,
                }
            res = requests.post(
                cxp['url'] + url_pdf, auth=cxp['auth'], json=json, stream=True)
        except Exception as e:
            raise UserError(_(
                "Failure in the webservice request to Jenji: "
                "%s") % e)
        if res.status_code not in (200, 201):
            raise UserError(_(
                "Error in the connexion to the Jenji webservice %s"
                "Received HTTP error code %s") % (url_pdf, res.status_code))
        logger.info('Successfully used Jenji WS %s', url_pdf)
        res_dict = res.json()
        export_id = res_dict['exportId']
        logger.debug('Got export_id=%s', export_id)
        try_count = 0
        pdf_file_b64 = False
        # I would have prefered to use
        # /user-export-download/v1/dl/{orgId}/{exportId}
        # but the WS supposed to give orgID doesn't give it
        url_search = '/s/user-exports/v1/search'
        now = datetime.now()
        search_json = {
            'endMonth': now.month,
            'endYear': now.year,
            'startMonth': now.month,
            'startYear': now.year,
            }
        url_dl = 'http://export-user.jenji.io'
        while try_count <= 10:
            try_count += 1
            logger.debug('Updated try_count to %d', try_count)
            rsearch = False
            export_file = False
            try:
                logger.debug(
                    'Starting request on %s with payload %s',
                    url_search, search_json)
                rsearch = requests.post(
                    cxp['url'] + url_search, auth=cxp['auth'],
                    json=search_json, stream=True)
            except Exception as e:
                logger.info('Failed to call URL %s', url_search)
                time.sleep(5)
                continue
            if rsearch and rsearch.status_code == 200:
                exports = rsearch.json().get('exports', [])
                for export in exports:
                    if export.get('id') == export_id and export.get('file'):
                        export_file = export['file']
                        break
            if export_file:
                rdl = False
                try:
                    logger.debug(
                        'GET request on %s with export_file=%s',
                        url_dl, export_file)
                    rdl = requests.get(
                        url_dl + '/' + export_file, auth=cxp['auth'],
                        stream=True)
                except Exception as e:
                    logger.info('Failed to call URL %s', url_dl)
                    time.sleep(5)
                    continue
                if rdl.status_code == 200:
                    pdf_file = rdl.content
                    pdf_file_b64 = pdf_file.encode('base64')
                    logger.info('PDF download ok (trycount=%d)', try_count)
                    return pdf_file_b64
            logger.info(
                'Waiting 5 sec before next try (trycount=%d)', try_count)
            time.sleep(5)
        return pdf_file_b64
