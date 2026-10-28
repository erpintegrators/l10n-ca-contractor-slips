# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
import base64
import logging
import os
import re
import tempfile
from datetime import date

from dateutil.relativedelta import relativedelta
from lxml import etree
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import date_utils, email_normalize
from odoo.tools.xml_utils import load_xsd_files_from_url

from . import cra_format as fmt
from .l10n_ca_slip import RECIPIENT_FIELDS
from .res_company import check_program_account

_logger = logging.getLogger(__name__)

XSD_PREFIX = "l10n_ca_contractor_slips"
XSD_URL_PARAM = "l10n_ca_contractor_slips.cra_schema_url"  # optional override
XSD_LOADED_PARAM = "l10n_ca_contractor_slips.cra_schema_loaded_url"
AMENDMENT_NOTE_LIMIT = 1309  # CRA's T619 specification
XSD_DEFAULT_URL = "https://www.canada.ca/content/dam/cra-arc/serv-info/eservices/xmlschm1-27-1.zip"
XSD_ENTRY_POINTS = {"t4a": "T619_T4A.xsd", "t5018": "T619_T5018.xsd"}
THRESHOLD = 500.0
# Set only by the return's own steps (finalize, file, amend, back to draft).
WORKFLOW_FIELDS = {
    "state", "xml_file", "xml_filename", "sbmt_ref_id", "filed_date", "report_type", "origin_id", "filed_settings",
}
# Fixed once the return leaves draft.
LOCKED_FIELDS = {"slip_type", "year", "date_from", "date_to", "company_id", "amendment_note"}


class SchemaUnavailable(UserError):
    """CRA's schemas could not be loaded, so the file was not checked."""


class L10nCaSlipReturn(models.Model):
    _name = "l10n.ca.slip.return"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Canadian contractor slip return"
    _order = "year desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    # One return per business number: branches share their main company's, so returns always
    # belong to the main company and cover every branch.
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company.root_id, readonly=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    slip_type = fields.Selection(
        [("t4a", "T4A: fees for services"), ("t5018", "T5018: contract payments")],
        string="Slip type",
        required=True,
        default="t4a",
        tracking=True,
    )
    year = fields.Integer(
        required=True,
        default=lambda self: fields.Date.context_today(self).year - 1,
        tracking=True,
        help="Tax year for T4A. For T5018, the year in which the reporting period ends.",
    )
    date_from = fields.Date(compute="_compute_dates", store=True, readonly=False, required=True, precompute=True)
    date_to = fields.Date(compute="_compute_dates", store=True, readonly=False, required=True, precompute=True)
    report_type = fields.Selection(
        [("O", "Original"), ("A", "Amended")], default="O", required=True, readonly=True
    )
    origin_id = fields.Many2one("l10n.ca.slip.return", string="Amends", readonly=True, index="btree_not_null")
    amendment_ids = fields.One2many("l10n.ca.slip.return", "origin_id", string="Amendments")
    amendment_note = fields.Text(help="Explanation sent to CRA with an amended return.")
    state = fields.Selection(
        [("draft", "Draft"), ("final", "Final"), ("filed", "Filed")],
        default="draft",
        required=True,
        tracking=True,
    )
    slip_ids = fields.One2many("l10n.ca.slip", "return_id", string="Slips")
    slip_count = fields.Integer(compute="_compute_totals")
    exported_slip_count = fields.Integer(compute="_compute_totals")
    total_reported = fields.Monetary(
        compute="_compute_totals",
        help="Box 048 total for T4A, box 22 total for T5018, over the slips in the file.",
    )
    xml_file = fields.Binary(
        string="CRA file", attachment=True, readonly=True, copy=False, groups="account.group_account_manager",
        help="Holds recipients' SINs, so only accounting administrators can open it.",
    )
    xml_filename = fields.Char(readonly=True, copy=False)
    has_xml_file = fields.Boolean(compute="_compute_has_xml_file")
    sbmt_ref_id = fields.Char(string="Submission reference", readonly=True, copy=False)
    filed_date = fields.Date(readonly=True, copy=False, tracking=True)
    cra_confirmation = fields.Char(string="CRA confirmation number", copy=False, tracking=True)
    warning_message = fields.Text(readonly=True, copy=False)
    filed_settings = fields.Char(readonly=True, copy=False, help="The T5018 settings in force when the return was finalized.")
    due_date = fields.Date(
        string="Due date",
        compute="_compute_due_date",
        help="When CRA expects the return and the recipients expect their slips. A due date on a weekend "
        "or public holiday moves to the next business day.",
    )

    _sql_constraints = [
        ("year_check", "CHECK(year >= 2000 AND year <= 2099)", "The year must be between 2000 and 2099."),
    ]

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends("slip_type", "year", "report_type")
    def _compute_name(self):
        for record in self:
            label = dict(record._fields["slip_type"].selection).get(record.slip_type, "").split(":")[0]
            suffix = self.env._(" (amended)") if record.report_type == "A" else ""
            record.name = f"{label} {record.year or ''}{suffix}".strip()

    @api.depends("slip_type", "year")
    def _compute_dates(self):
        """Set from the company's T5018 period when the return is created or its type or year
        changes. Changing the setting later leaves existing returns alone."""
        for record in self:
            if not record.year:
                record.date_from = record.date_to = False
                continue
            if record.slip_type == "t5018" and record.company_id.l10n_ca_t5018_period == "fiscal":
                company = record.company_id
                last_month = int(company.fiscalyear_last_month or 12)
                last_day = min(company.fiscalyear_last_day or 31, 28 if last_month == 2 else 31)
                end_probe = date(record.year, last_month, 1)
                record.date_from, record.date_to = date_utils.get_fiscal_year(
                    end_probe, day=last_day, month=last_month
                )
            else:
                record.date_from = date(record.year, 1, 1)
                record.date_to = date(record.year, 12, 31)

    @api.depends("state", "report_type", "slip_ids.amount_reported", "slip_ids.rpt_tcd", "slip_ids.is_cancelled")
    def _compute_totals(self):
        for record in self:
            to_file = record._slips_to_file()
            record.slip_count = len(record.slip_ids)
            record.exported_slip_count = len(to_file)
            record.total_reported = sum(to_file.mapped("amount_reported"))

    def _slips_to_file(self):
        """Slips that go in the CRA file: fixed at finalization, forecast while in draft."""
        self.ensure_one()
        if self.state != "draft":
            return self.slip_ids.filtered("rpt_tcd")
        if self.report_type == "O":
            return self.slip_ids
        return self.slip_ids.filtered(lambda s: s.is_cancelled or s._differs_from_origin())

    @api.model
    def default_get(self, fields):  # noqa: A002  the field-list argument used by Odoo
        values = super().default_get(fields)
        if "company_id" in fields:
            self._l10n_ca_main_company()
        return values

    @api.model
    def _l10n_ca_main_company(self):
        root = self.env.company.root_id
        if not self.env.su and root not in self.env.user.company_ids:
            raise UserError(self.env._(
                "Returns belong to %s, the main company. Ask an administrator to give you access to it.",
                root.sudo().name,
            ))
        return root

    @api.constrains("company_id")
    def _check_main_company(self):
        for record in self:
            if record.company_id.parent_id:
                raise ValidationError(self.env._(
                    "Prepare the return on %(main)s: branches file under their main company's business number.",
                    main=record.company_id.root_id.name,
                ))

    @api.constrains("slip_type", "year", "date_from", "date_to")
    def _check_period(self):
        for record in self:
            if record.date_from > record.date_to:
                raise ValidationError(self.env._("The period must start before it ends."))
            if record.slip_type == "t4a" and (record.date_from, record.date_to) != (
                date(record.year, 1, 1), date(record.year, 12, 31)
            ):
                raise ValidationError(self.env._(
                    "A T4A return covers the calendar year in which the amounts were paid."
                ))
            if record.slip_type == "t5018" and record.date_to.year != record.year:
                raise ValidationError(self.env._("A T5018 return's period ends in its year."))
            if (record.date_to - record.date_from).days > 371:
                raise ValidationError(self.env._("A reporting period cannot be longer than a year."))

    def _overlapping_returns(self):
        """Final or filed returns of the same slip for another period that overlaps this one."""
        self.ensure_one()
        related = self.env["res.company"].sudo().search([
            "|", ("id", "child_of", self.company_id.id), ("id", "parent_of", self.company_id.id),
        ])
        return self.sudo().search([
            ("id", "!=", self.id),
            ("company_id", "in", related.ids),
            ("slip_type", "=", self.slip_type),
            ("state", "in", ("final", "filed")),
            ("date_from", "<=", self.date_to),
            ("date_to", ">=", self.date_from),
            ("date_to", "!=", self.date_to),
        ])

    @api.depends("slip_type", "date_to")
    def _compute_due_date(self):
        """T4A: the last day of February after the year. T5018: six months after the period ends."""
        for record in self:
            if not record.date_to:
                record.due_date = False
            elif record.slip_type == "t4a":
                record.due_date = date_utils.end_of(date(record.date_to.year + 1, 2, 1), "month")
            else:
                due = record.date_to + relativedelta(months=6)
                if record.date_to == date_utils.end_of(record.date_to, "month"):
                    due = date_utils.end_of(due, "month")
                record.due_date = due

    @api.depends("xml_filename")
    def _compute_has_xml_file(self):
        for record in self:
            record.has_xml_file = bool(record.xml_filename)

    @api.model
    def _sets_workflow_fields(self, vals):
        defaults = {"state": "draft", "report_type": "O"}
        return any(vals.get(name, defaults.get(name)) not in (defaults.get(name), False, None) for name in WORKFLOW_FIELDS)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(self._sets_workflow_fields(vals) for vals in vals_list):
            raise UserError(self.env._("The state, report type and CRA file of a return are set by its buttons."))
        # The return belongs to the main company even when a branch is selected. Keep the
        # main company in the active context so its standard record rule also covers creation.
        return super(L10nCaSlipReturn, self.with_company(self._l10n_ca_main_company())).create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if WORKFLOW_FIELDS.intersection(vals):
                raise UserError(self.env._("The state, report type and CRA file of a return are set by its buttons."))
            if LOCKED_FIELDS.intersection(vals) and any(record.state != "draft" for record in self):
                raise UserError(self.env._("A final or filed return cannot be changed. Amend it instead."))
            # An amendment covers the period of the return it amends.
            if {"slip_type", "year", "date_from", "date_to", "company_id"}.intersection(vals) and any(
                record.report_type == "A" for record in self
            ):
                raise UserError(self.env._("An amendment keeps the slip type and period of the return it amends."))
        return super().write(vals)

    def _workflow_write(self, vals):
        """Write fields only the return's own steps may set, once the user is known to be allowed."""
        self.check_access("write")
        return self.sudo().write(vals)

    # ------------------------------------------------------------------
    # Slip computation
    # ------------------------------------------------------------------

    def action_compute(self):
        for record in self:
            if record.state != "draft":
                raise UserError(self.env._("Only draft returns can be recalculated."))
            record._scoped()._compute_slips()
        return True

    def _branch_companies(self):
        """The company and its active branches. A return covers all of them, so the user must have
        access to each one. Archived branches cannot be given to any user; their bills still count."""
        self.ensure_one()
        companies = self.env["res.company"].sudo().search([("id", "child_of", self.company_id.id)])
        missing = companies - self.env.user.company_ids
        if missing:
            raise UserError(self.env._(
                "This return includes bills from %(branches)s. Ask an administrator for access to "
                "those companies before preparing it.",
                branches=", ".join(missing.mapped("name")),
            ))
        return companies

    def _scoped(self):
        """This return with every branch selected, whatever the user picked in the company switcher."""
        self.ensure_one()
        others = (self._branch_companies() - self.company_id).ids
        return self.with_context(allowed_company_ids=[self.company_id.id, *others])

    def _slip_targets(self):
        """What a recalculation would put on this return now: ({partner id: (partner, data, above
        threshold)}, notes)."""
        self.ensure_one()
        engine = self.env["l10n.ca.slip.engine"]
        Partner = self.env["res.partner"].sudo().with_context(active_test=False)
        flagged = Partner.with_company(self.company_id).search(
            [("l10n_ca_slip_type", "=", self.slip_type), ("parent_id", "=", False)]
        )
        # Vendors nobody flagged are calculated too, so the return can name the ones it would miss.
        unflagged = self._unflagged_vendors(flagged)
        amounts = engine._compute_partner_amounts(
            self.company_id, self.slip_type, self.date_from, self.date_to, partners=flagged | unflagged
        )
        partners = Partner.browse(list(amounts))
        notes = self._other_slip_bill_notes()
        existing = set(self.slip_ids.partner_id.ids)
        already_filed = self._currently_reported_slips().partner_id
        cancelled = self._cancelled_slips() if self.report_type == "O" else self.env["l10n.ca.slip"]
        qualified = {}
        for partner in partners:
            data = amounts[partner.id]
            if partner in unflagged:
                amount = data["base"] if self.slip_type == "t4a" else data["incl"]
                if not self.currency_id.is_zero(amount):
                    notes.append(self.env._(
                        "%(partner)s was paid %(amount)s on accounts tagged for this slip, but the contact is not set "
                        "to %(slip)s. Set Canadian slip on the contact and recalculate, or set those bills to Not "
                        "reported.",
                        partner=partner.display_name, amount=self.currency_id.format(amount),
                        slip=self.slip_type.upper(),
                    ))
                continue
            if self.report_type == "O" and partner in already_filed:
                continue
            for slip in cancelled.filtered(lambda s, p=partner: s.partner_id == p):
                notes.append(self.env._(
                    "%(partner)s: the slip for this period was cancelled in %(cancelled_in)s (%(note)s). If those "
                    "payments were not fees for services, set the bills to Not reported and recalculate. File the slip "
                    "again here only if it was cancelled to correct the SIN or business number.",
                    partner=partner.display_name, cancelled_in=slip.return_id.display_name,
                    note=(slip.return_id.amendment_note or "").strip()[:200] or self.env._("no note"),
                ))
            if partner.country_id and partner.country_id.code != "CA":
                notes.append(self.env._(
                    "%(partner)s has an address outside Canada and was left out: fees paid to non-residents "
                    "for services in Canada go on the T4A-NR. If %(partner)s is a resident of Canada, correct "
                    "the address and recalculate.",
                    partner=partner.display_name,
                ))
                continue
            above = self._passes_threshold(data)
            if not above and partner.id not in existing:
                for warning in data["warnings"]:
                    notes.append(f"{partner.display_name}: {warning}")
                continue
            qualified[partner.id] = (partner, data, above)
        return qualified, notes

    def _compute_slips(self):
        self.ensure_one()
        qualified, notes = self._slip_targets()
        existing = {slip.partner_id.id: slip for slip in self.slip_ids}
        if self.report_type == "A":
            self._update_amendment_slips(qualified, notes)
        else:
            for partner_id, slip in existing.items():
                if partner_id in qualified:
                    continue
                if slip._has_adjustment():
                    slip._clear_computed()
                else:
                    slip.unlink()
            for partner_id, (partner, data, above) in qualified.items():
                slip = existing.get(partner_id)
                if not above and not slip._has_adjustment():
                    slip.unlink()
                    continue
                self._write_slip(slip, partner, data)
        self.warning_message = "\n".join(self._return_notes() + notes) or False
        self.message_post(
            body=self.env._("Slips recalculated: %s slip(s).", len(self.slip_ids)), subtype_xmlid="mail.mt_note"
        )

    def _return_notes(self):
        """Notes about the return itself rather than one contractor."""
        self.ensure_one()
        notes = []
        if self.date_to >= fields.Date.context_today(self):
            notes.append(self.env._(
                "This period has not ended. Payments made after you finalize will not be on the slips; CRA expects "
                "an early return only when the business has stopped operating."
            ))
        if self.slip_type == "t5018" and self.report_type == "O":
            previous = self.sudo().search([
                ("id", "!=", self.id), ("company_id", "=", self.company_id.id), ("slip_type", "=", "t5018"),
                ("state", "in", ("final", "filed")), ("report_type", "=", "O"), ("date_to", "<", self.date_from),
            ], order="date_to desc", limit=1)
            if previous and previous.date_to + relativedelta(days=1) != self.date_from:
                notes.append(self.env._(
                    "The previous T5018 period ended on %(end)s, so payments from %(start)s to %(gap)s are on no "
                    "return.",
                    end=previous.date_to, start=previous.date_to + relativedelta(days=1),
                    gap=self.date_from - relativedelta(days=1),
                ))
        if self.slip_type == "t5018" and not 364 <= (self.date_to - self.date_from).days <= 365:
            notes.append(self.env._(
                "This period is not twelve months. CRA expects the same reporting period every year unless it "
                "authorizes a change in writing; a shorter first period is normal for a new business."
            ))
        Company = self.env["res.company"].sudo().with_context(active_test=False)
        branches = Company.search([("id", "child_of", self.company_id.id), ("id", "!=", self.company_id.id)])
        for branch in branches.filtered(lambda c: not c.active):
            notes.append(self.env._("Bills from the archived branch %s are included.", branch.name))
        Partner = self.env["res.partner"].sudo().with_context(active_test=False)
        flagged = Partner.with_company(self.company_id).search([("l10n_ca_slip_type", "=", self.slip_type)])
        for branch in branches:
            for partner in Partner.with_company(branch).search([
                ("l10n_ca_slip_type", "=", self.slip_type), ("id", "not in", flagged.ids), ("parent_id", "=", False),
            ]):
                notes.append(self.env._(
                    "%(partner)s is flagged for this slip only while working in %(branch)s. Flag the contact while "
                    "working in %(main)s so its payments count.",
                    partner=partner.display_name, branch=branch.name, main=self.company_id.name,
                ))
        origin = self.origin_id
        if self.slip_type == "t5018" and origin and origin.filed_settings and origin.filed_settings != self._settings_key():
            notes.append(self.env._(
                "The T5018 settings for mixed bills or the slip threshold changed since %s was filed. Amounts here "
                "follow today's settings; make sure the change is intended before filing the amendment.",
                origin.display_name,
            ))
        return notes

    def _settings_key(self):
        company = self.company_id
        return f"{bool(company.l10n_ca_t5018_include_mixed_goods)}/{company.l10n_ca_t5018_threshold_basis}"

    def _stale_slips(self):
        """Recipients whose slip no longer matches what a recalculation would give, because a bill,
        a payment or the contact changed after the last calculation."""
        self.ensure_one()
        qualified, _notes = self._slip_targets()
        Slip = self.env["l10n.ca.slip"]
        compare = self.currency_id.compare_amounts
        stale = []
        # Contractors already on another final return are reported separately as duplicates.
        elsewhere = self._currently_reported_slips().partner_id if self.report_type == "O" else self.env["res.partner"]
        for slip in self.slip_ids.filtered(lambda s: not s.is_cancelled and s.partner_id not in elsewhere):
            target = qualified.get(slip.partner_id.id)
            data = target[1] if target else {"base": 0.0, "incl": 0.0}
            changed = compare(slip.computed_base, data["base"]) or compare(slip.computed_incl, data["incl"])
            # Below the threshold now (a setting changed, say): a recalculation would drop the slip.
            if not changed and target and not target[2] and not slip._has_adjustment() and self.report_type == "O":
                changed = True
            # A contractor now left out keeps the details already on the slip, so only the amounts count.
            if not changed and target:
                values = Slip._recipient_values(slip.partner_id, self.company_id)
                changed = any((slip.sudo()[name] or False) != (values[name] or False) for name in RECIPIENT_FIELDS)
            if changed:
                stale.append(slip.partner_id.display_name)
        if self.report_type == "O":
            on_return = set(self.slip_ids.partner_id.ids)
            stale += [partner.display_name for pid, (partner, _d, above) in qualified.items() if above and pid not in on_return]
        return stale

    def _unflagged_vendors(self, flagged):
        """Vendors not set to this slip whose bills or bank payments use an account tagged for it,
        in the period or the seven years before. The engine works out what they were paid."""
        tag = self.env["l10n.ca.slip.engine"]._get_slip_tag(self.slip_type)
        companies = self.env["res.company"].sudo().with_context(active_test=False).search(
            [("id", "child_of", self.company_id.id)]
        )
        groups = self.env["account.move.line"].sudo()._read_group([
            ("company_id", "in", companies.ids),
            ("parent_state", "=", "posted"),
            ("account_id.tag_ids", "in", tag.ids),
            ("partner_id", "!=", False),
            ("move_id.l10n_ca_slip_type", "=", False),
            ("date", ">=", self.date_from - relativedelta(years=7)),
            ("date", "<=", self.date_to),
        ], ["partner_id"])
        partners = self.env["res.partner"].sudo().browse([partner.id for partner, in groups]).commercial_partner_id
        return partners - flagged

    def _other_slip_bill_notes(self):
        """Bills set to the other slip whose lines use an account tagged for this one: neither
        return counts those lines."""
        tag = self.env["l10n.ca.slip.engine"]._get_slip_tag(self.slip_type)
        companies = self.env["res.company"].sudo().with_context(active_test=False).search(
            [("id", "child_of", self.company_id.id)]
        )
        other = "t5018" if self.slip_type == "t4a" else "t4a"
        bills = self.env["account.move"].sudo().search([
            ("company_id", "in", companies.ids),
            ("state", "=", "posted"),
            ("l10n_ca_slip_type", "=", other),
            ("invoice_line_ids.account_id.tag_ids", "in", tag.ids),
            "|", "|",
            ("matched_payment_ids.date", ">=", self.date_from),
            ("line_ids.matched_debit_ids.max_date", ">=", self.date_from),
            ("line_ids.matched_credit_ids.max_date", ">=", self.date_from),
        ])
        # Paid by a registered payment or matched to a bank statement line within the period.
        engine = self.env["l10n.ca.slip.engine"]
        bills = bills.filtered(lambda b: engine._settled_in(b, self.date_from, self.date_to))
        # Goods lines never count on either slip, so they do not raise the question.
        bills = bills.filtered(lambda b: b.invoice_line_ids.filtered(
            lambda l_: l_.display_type == "product" and tag in l_.account_id.tag_ids and l_.product_id.type != "consu"
        ))
        notes = []
        for partner in bills.commercial_partner_id:
            names = bills.filtered(lambda b, p=partner: b.commercial_partner_id == p).mapped("name")
            notes.append(self.env._(
                "%(partner)s is reported on %(other)s, and bills paid in this period use accounts tagged for this "
                "slip: %(bills)s. Check which slip those payments belong on.",
                partner=partner.display_name, other=other.upper(), bills=", ".join(names),
            ))
        return notes

    def _cancelled_slips(self):
        """Slips for this period that a filed or final amendment cancelled with CRA."""
        self.ensure_one()
        related = self.env["res.company"].sudo().search([
            "|", ("id", "child_of", self.company_id.id), ("id", "parent_of", self.company_id.id),
        ])
        return self.env["l10n.ca.slip"].sudo().search([
            ("return_id", "!=", self.id),
            ("company_id", "in", related.ids),
            ("slip_type", "=", self.slip_type),
            ("return_id.date_to", "=", self.date_to),
            ("state", "in", ("final", "filed")),
            ("rpt_tcd", "=", "C"),
            ("superseded", "=", False),
        ])

    def _currently_reported_slips(self):
        """Slips CRA currently holds for this period from other returns: original or amended,
        not replaced or cancelled since. A second original return only picks up contractors
        missing from these."""
        self.ensure_one()
        related = self.env["res.company"].sudo().search([
            "|", ("id", "child_of", self.company_id.id), ("id", "parent_of", self.company_id.id),
        ])
        return self.env["l10n.ca.slip"].sudo().search([
            ("return_id", "!=", self.id),
            ("company_id", "in", related.ids),
            ("slip_type", "=", self.slip_type),
            ("return_id.date_to", "=", self.date_to),
            ("state", "in", ("final", "filed")),
            ("rpt_tcd", "in", ("O", "A")),
            ("superseded", "=", False),
        ])

    def _passes_threshold(self, data):
        """T4A: more than $500 before tax. T5018: by the company's setting, either the services part
        with tax at $500 or more (Form T5018SUM), or before tax more than $500 (the slip page)."""
        self.ensure_one()
        compare = self.currency_id.compare_amounts
        if self.slip_type == "t4a":
            return compare(data["base"], THRESHOLD) > 0
        if self.company_id.l10n_ca_t5018_threshold_basis == "base_over_500":
            return compare(data["svc_base"], THRESHOLD) > 0
        return compare(data["svc_incl"], THRESHOLD) >= 0

    def _update_amendment_slips(self, qualified, notes):
        """An amended return keeps the slips it copied from the filed return and refreshes their
        amounts. Contractors missing from the filed return are listed for a separate original return."""
        by_partner = {slip.partner_id.id: slip for slip in self.slip_ids.filtered(lambda s: not s.is_cancelled)}
        cancelled = self.slip_ids.filtered("is_cancelled").partner_id.ids
        for partner_id, (partner, data, above) in qualified.items():
            slip = by_partner.get(partner_id)
            if partner_id in cancelled:
                continue
            if slip:
                self._write_slip(slip, partner, data)
            elif above:
                notes.append(self.env._(
                    "%(partner)s now qualifies but is not on the filed return. Report the slip in a new "
                    "original return for the same year.",
                    partner=partner.display_name,
                ))
        for partner_id, slip in by_partner.items():
            if partner_id not in qualified:
                slip._clear_computed()

    def _write_slip(self, slip, partner, data):
        move_ids = {line[key] for line in data["lines"] for key in ("move_id", "payment_move_id") if line[key]}
        names = {move.id: move.name for move in self.env["account.move"].sudo().browse(move_ids)}
        lines = self._rounded_lines(data)
        vals = {
            "computed_base": data["base"],
            "computed_incl": data["incl"],
            "line_ids": [fields.Command.clear()] + [
                fields.Command.create({
                    "date": line["date"],
                    "move_id": line["move_id"],
                    "move_ref": names.get(line["move_id"]),
                    "payment_move_id": line["payment_move_id"],
                    "payment_ref": names.get(line["payment_move_id"]),
                    "payment_id": line["payment_id"],
                    "source": line["source"],
                    "cash": line["cash"],
                    "amount_base": line["amount_base"],
                    "amount_incl": line["amount_incl"],
                })
                for line in lines
            ],
            **self.env["l10n.ca.slip"]._recipient_values(partner, self.company_id),
        }
        vals["engine_warnings"] = "\n".join(data["warnings"]) or False
        if slip:
            slip.write(vals)
        else:
            self.env["l10n.ca.slip"].with_context(mail_create_nolog=True, mail_create_nosubscribe=True).create(
                {"return_id": self.id, "partner_id": partner.id, **vals}
            )

    def _rounded_lines(self, data):
        """Payment lines rounded to the cent, with any rounding difference on the last line so the
        lines add up to the slip."""
        currency = self.currency_id
        lines = [dict(line) for line in sorted(data["lines"], key=lambda line: line["date"])]
        for key, total in (("amount_base", data["base"]), ("amount_incl", data["incl"])):
            for line in lines:
                line[key] = currency.round(line[key])
            if lines:
                lines[-1][key] = currency.round(lines[-1][key] + total - sum(line[key] for line in lines))
        return lines

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def action_finalize(self):
        for record in self:
            record = record._scoped()
            record.check_access("write")
            if record.state != "draft":
                raise UserError(self.env._("Only draft returns can be finalized."))
            if stale := record._stale_slips():
                raise UserError(self.env._(
                    "Recalculate first: bills, payments or contacts changed since the last calculation for %s.",
                    ", ".join(stale),
                ))
            record._assign_report_codes()
            errors = record._get_blocking_errors()
            if record.report_type == "O":
                duplicates = record.slip_ids.partner_id & record._currently_reported_slips().partner_id
                errors.extend(
                    self.env._("%s is already reported on another final or filed return for this period.", p.display_name)
                    for p in duplicates
                )
            if errors:
                raise UserError(
                    self.env._("Fix these before finalizing:\n%s", "\n".join(f"- {e}" for e in errors))
                )
            # A new reference every time: a file changed after going back to draft must not reuse one.
            record._workflow_write({"sbmt_ref_id": self.env["ir.sequence"].next_by_code("l10n.ca.slip.submission")})
            record._generate_xml()
            record._workflow_write({"state": "final", "filed_settings": record._settings_key()})
            if record.warning_message:
                # The notes stay on record with the return, as they stood when it was finalized.
                record.message_post(body=Markup("<p>%s</p><ul>%s</ul>") % (
                    self.env._("Finalized with these notes:"),
                    Markup().join(Markup("<li>%s</li>") % note for note in record.warning_message.split("\n")),
                ), subtype_xmlid="mail.mt_note")
            record._mark_superseded_slips(True)
            for slip in record.slip_ids:
                slip._portal_ensure_token()
        return True

    def action_reset_to_draft(self):
        for record in self:
            if record.state != "final":
                raise UserError(self.env._("Only final returns can go back to draft. Filed returns are amended."))
            record._workflow_write({"xml_file": False, "xml_filename": False, "state": "draft"})
            record._mark_superseded_slips(False)
            record.slip_ids.sudo().write({"rpt_tcd": False})
            # Whatever was emailed showed the final amounts: queued emails are withdrawn and the next
            # send starts again.
            slips = record.slip_ids.sudo()
            slips.mail_id.filtered(lambda m: m.state in ("outgoing", "exception", "cancel")).unlink()
            slips.write({"sent_date": False, "mail_id": False, "send_requested_uid": False, "send_to_email": False})
        return True

    def action_mark_filed(self):
        for record in self:
            if record.state != "final":
                raise UserError(self.env._("Finalize the return before marking it filed."))
            record._workflow_write({"state": "filed", "filed_date": fields.Date.context_today(record)})
        return True

    def action_create_amendment(self):
        self.ensure_one()
        if self.state != "filed":
            raise UserError(self.env._("Only filed returns can be amended."))
        if self.amendment_ids:
            latest = self.amendment_ids.sorted("id")[-1]
            raise UserError(self.env._(
                "This return already has an amendment (%s). Amend the most recent filed version.", latest.display_name
            ))
        self.check_access("create")
        amendment = self.sudo().create({
            "company_id": self.company_id.id,
            "slip_type": self.slip_type,
            "year": self.year,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "report_type": "A",
            "origin_id": self.id,
        })
        for slip in self.slip_ids.filtered(lambda s: not s.is_cancelled):
            slip.sudo().copy({"return_id": amendment.id, "origin_slip_id": slip.id})
        return amendment._get_form_action()

    def _mark_superseded_slips(self, value):
        """On an amended return, the slip each amended or cancelled slip replaces drops out of
        the recipient's portal."""
        self.ensure_one()
        for slip in self.slip_ids.filtered(lambda s: s.rpt_tcd in ("A", "C")):
            previous = slip.origin_slip_id
            while previous and previous.rpt_tcd not in ("O", "A"):
                previous = previous.origin_slip_id
            previous.sudo().superseded = value

    def _get_form_action(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
        }

    def _assign_report_codes(self):
        self.ensure_one()
        for slip in self.slip_ids:
            if self.report_type == "O":
                code = "O"
            elif slip.is_cancelled:
                slip._copy_filed_values()
                code = "C"
            elif slip._differs_from_origin():
                code = "A"
            else:
                code = False
            slip.sudo().rpt_tcd = code

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _payer_account(self):
        self.ensure_one()
        company = self.company_id
        return company.l10n_ca_slip_rp_account if self.slip_type == "t4a" else company.l10n_ca_slip_rz_account

    def _get_blocking_errors(self):
        self.ensure_one()
        errors = []
        company = self.company_id
        program = "RP" if self.slip_type == "t4a" else "RZ"
        account = self._payer_account()
        if not account:
            errors.append(self.env._("Set the payer's %s account in Accounting settings.", program))
        elif message := check_program_account(self.env, account, program):
            errors.append(message)
        signin = company.l10n_ca_slip_signin
        if signin == "rac":
            if not re.fullmatch(r"[A-Za-z0-9]{1,7}", (company.l10n_ca_slip_transmitter_repid or "").strip()):
                errors.append(self.env._(
                    "Enter your RepID (up to 7 letters and digits) in Accounting settings: CRA matches the file "
                    "to the representative who uploads it."
                ))
        elif signin == "myba" and not company.l10n_ca_slip_transmitter_account:
            errors.append(self.env._("Set the transmitter CRA account number in Accounting settings."))
        if self.year > fields.Date.context_today(self).year:
            errors.append(self.env._("CRA does not take returns for a year that has not started."))
        if self.currency_id != self.env.ref("base.CAD"):
            errors.append(self.env._(
                "CRA takes slip amounts in Canadian dollars, and this company keeps its books in %s.",
                self.currency_id.name,
            ))
        if self.report_type == "O":
            for other in self._overlapping_returns():
                errors.append(self.env._(
                    "%(other)s already covers part of this period (%(start)s to %(end)s). CRA expects the same "
                    "reporting period every year unless it authorizes a change in writing.",
                    other=other.display_name, start=other.date_from, end=other.date_to,
                ))
        contact = company.l10n_ca_slip_contact_id
        if not contact:
            errors.append(self.env._("Choose a filing contact in Accounting settings."))
        else:
            if not fmt.phone_parts(contact.phone):
                errors.append(self.env._("The filing contact needs a 10-digit phone number."))
            if not contact.email:
                errors.append(self.env._("The filing contact needs an email address."))
            elif len(contact.email) > fmt.LIMITS["email"]:
                errors.append(self.env._(
                    "The filing contact's email address is longer than CRA's limit of %s characters.", fmt.LIMITS["email"]
                ))
        if not fmt.clean_text(company.name):
            errors.append(self.env._("The company needs a name."))
        if self.report_type == "A" and not (self.amendment_note or "").strip():
            errors.append(self.env._("Explain the amendment in the amendment note."))
        if len(self.amendment_note or "") > AMENDMENT_NOTE_LIMIT:
            errors.append(self.env._("Shorten the amendment note to %s characters, CRA's limit.", AMENDMENT_NOTE_LIMIT))
        codes = set(self.slip_ids.filtered("rpt_tcd").mapped("rpt_tcd"))
        if {"A", "C"} <= codes:
            errors.append(self.env._(
                "CRA takes amended slips and cancelled slips in separate submissions. Untick the "
                "cancellations here, file this amendment, then cancel those slips in a further amendment."
            ))
        exported = self.slip_ids.filtered("rpt_tcd")
        if not exported:
            errors.append(self.env._("There are no slips to file."))
        for slip in exported:
            errors.extend(f"{slip.partner_id.display_name}: {error}" for error in slip._get_blocking_errors())
        return errors

    # ------------------------------------------------------------------
    # CRA file
    # ------------------------------------------------------------------

    @api.model
    def _l10n_ca_schema_url(self):
        return self.env["ir.config_parameter"].sudo().get_param(XSD_URL_PARAM) or XSD_DEFAULT_URL

    @api.model
    def _l10n_ca_schemas_current(self):
        """Schemas are reloaded whenever the package they came from is no longer the one in use,
        so a release that moves to CRA's next package refreshes existing installs."""
        loaded_from = self.env["ir.config_parameter"].sudo().get_param(XSD_LOADED_PARAM)
        return bool(self._l10n_ca_schema_attachments()) and loaded_from == self._l10n_ca_schema_url()

    @api.model
    def _l10n_ca_load_cra_schemas(self, force=False):
        if not force and self._l10n_ca_schemas_current():
            return True
        url = self._l10n_ca_schema_url()
        loaded = load_xsd_files_from_url(self.env(su=True), url, xsd_name_prefix=XSD_PREFIX)
        # A proxy or error page can answer with something other than CRA's package. The download
        # only counts when it brought both entry points; schemas loaded earlier stay in place.
        loaded = loaded or self.env["ir.attachment"]
        names = set(loaded.mapped("name"))
        complete = all(f"{XSD_PREFIX}.{entry}" in names for entry in XSD_ENTRY_POINTS.values())
        if complete:
            self.env["ir.config_parameter"].sudo().set_param(XSD_LOADED_PARAM, url)
        else:
            loaded.filtered(lambda attachment: not attachment.name.endswith(".xsd")).sudo().unlink()
        return complete

    def _validate_xml(self, xml_bytes):
        """Check the file against CRA's schemas. They are written to a temporary folder and
        parsed from disk: CRA's package imports some schemas more than once, which libxml2
        2.9 cannot resolve from memory."""
        self.ensure_one()
        if not self._l10n_ca_schemas_current() and not self._l10n_ca_load_cra_schemas(force=True):
            raise SchemaUnavailable(self.env._(
                "The CRA schemas could not be downloaded, so the file cannot be checked. "
                "Try again later, or load them from Accounting settings."
            ))
        attachments = self._l10n_ca_schema_attachments()
        with tempfile.TemporaryDirectory() as folder:
            for attachment in attachments:
                name = os.path.basename(attachment.name[len(XSD_PREFIX) + 1:])
                content = attachment.raw
                with open(os.path.join(folder, name), "wb") as handle:
                    handle.write(getattr(content, "content", content))
            # CRA's schemas are files on disk; nothing is fetched from the network while parsing.
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            schema = etree.XMLSchema(etree.parse(os.path.join(folder, XSD_ENTRY_POINTS[self.slip_type]), parser))
        if not schema.validate(etree.fromstring(xml_bytes, parser)):
            raise UserError("\n".join(str(error) for error in schema.error_log))

    @api.model
    def _l10n_ca_schema_attachments(self):
        # Underscores are wildcards in LIKE patterns, so they are escaped.
        prefix = XSD_PREFIX.replace("_", "\\_")
        return self.env["ir.attachment"].sudo().search([("name", "=like", f"{prefix}.%.xsd")])

    def _generate_xml(self):
        self.ensure_one()
        xml_bytes = self._build_xml()
        try:
            self._validate_xml(xml_bytes)
        except SchemaUnavailable:
            raise
        except UserError as error:
            raise UserError(self.env._("The file does not pass CRA's schema:\n%s", error.args[0])) from error
        filename = f"{self.slip_type.upper()}_{self.year}_{self.report_type}_{self.sbmt_ref_id}.xml"
        self._workflow_write({"xml_file": base64.b64encode(xml_bytes), "xml_filename": filename})

    def _build_xml(self):
        """Build the T619 submission. Optional elements are left out when empty, as CRA asks."""
        self.ensure_one()
        company = self.company_id
        contact = company.l10n_ca_slip_contact_id
        area, number, extension = fmt.phone_parts(contact.phone) or ("", "", "")

        def node(parent, tag, value=None):
            element = etree.SubElement(parent, tag)
            if value is not None:
                element.text = str(value)
            return element

        def optional(parent, tag, value):
            if value not in (None, False, ""):
                node(parent, tag, value)

        submission = etree.Element("Submission")
        t619 = node(submission, "T619")
        # CRA matches the file to the sign-in: a 9-digit business number only with My Business
        # Account, the 15-character account signed in with for a web access code, and the RepID for
        # Represent a Client, where the account is optional.
        account_node = node(t619, "TransmitterAccountNumber")
        signin = company.l10n_ca_slip_signin
        entered = (company.l10n_ca_slip_transmitter_account or "").strip()
        transmitter = fmt.program_account(entered)
        if signin == "wac":
            node(account_node, "bn15", transmitter or fmt.program_account(self._payer_account()))
        elif transmitter:
            node(account_node, "bn15", transmitter)
        elif entered and signin == "myba":
            node(account_node, "bn9", entered[:9])
        if signin == "rac" and company.l10n_ca_slip_transmitter_repid:
            node(node(t619, "TransmitterRepID"), "RepID", company.l10n_ca_slip_transmitter_repid.strip())
        node(t619, "sbmt_ref_id", self.sbmt_ref_id)
        node(t619, "summ_cnt", 1)
        node(t619, "lang_cd", "F" if (company.partner_id.lang or "").startswith("fr") else "E")
        transmitter_name = (signin == "rac" and company.l10n_ca_slip_transmitter_name) or company.name
        node(node(t619, "TransmitterName"), "l1_nm", fmt.clean_text(transmitter_name, "transmitter_name"))
        node(t619, "TransmitterCountryCode", "CAN")
        cntc = node(t619, "CNTC")
        node(cntc, "cntc_nm", fmt.clean_text(contact.name, "transmitter_contact_name"))
        node(cntc, "cntc_area_cd", area)
        node(cntc, "cntc_phn_nbr", number)
        optional(cntc, "cntc_extn_nbr", extension)
        node(cntc, "cntc_email_area", contact.email or "")

        return_node = node(submission, "Return")
        body = node(return_node, "T4A" if self.slip_type == "t4a" else "T5018")
        exported = self.slip_ids.filtered("rpt_tcd").sorted(lambda s: s.partner_id.display_name or "")
        payer_account = fmt.program_account(self._payer_account())
        for slip in exported:
            slip._append_xml(body, payer_account, node, optional)
        self._append_summary(body, exported, payer_account, area, number, extension, node, optional)

        etree.indent(submission, space="  ")
        text = etree.tostring(submission, encoding="unicode")
        # CRA's character rules ask for the apostrophe as an entity reference.
        text = text.replace("'", "&apos;")
        return ('<?xml version="1.0" encoding="UTF-8"?>\n' + text + "\n").encode("utf-8")

    def _append_summary(self, body, exported, payer_account, area, number, extension, node, optional):
        company = self.company_id
        contact = company.l10n_ca_slip_contact_id
        summary = node(body, "T4ASummary" if self.slip_type == "t4a" else "T5018Summary")
        node(summary, "bn", payer_account)
        payer_name = node(summary, "PAYR_NM")
        for index, line in enumerate(fmt.split_lines(company.name, "name_line", 3), start=1):
            node(payer_name, f"l{index}_nm", line)
        self.env["l10n.ca.slip"]._append_address(summary, "PAYR_ADDR", company.partner_id, node, optional)
        cntc = node(summary, "CNTC")
        node(cntc, "cntc_nm", fmt.clean_text(contact.name, "contact_name"))
        node(cntc, "cntc_area_cd", area)
        node(cntc, "cntc_phn_nbr", number)
        optional(cntc, "cntc_extn_nbr", extension)
        # Each submission's summary counts and totals its own slips, cancelled ones included.
        total = fmt.amount(sum(exported.mapped("amount_reported")))
        if self.slip_type == "t4a":
            node(summary, "tx_yr", self.year)
            node(summary, "slp_cnt", len(exported))
            node(summary, "rpt_tcd", self.report_type)
            if self.report_type == "A":
                node(summary, "fileramendmentnote", fmt.clean_text(self.amendment_note, "amendment_note"))
            node(node(summary, "T4A_TAMT"), "rpt_tot_fee_srvc_amt", total)
        else:
            end = node(summary, "PRD_END_DT")
            node(end, "dy", self.date_to.day)
            node(end, "mo", self.date_to.month)
            node(end, "yr", self.date_to.year)
            node(summary, "slp_cnt", len(exported))
            node(summary, "tot_sbctrcr_amt", total)
            node(summary, "rpt_tcd", self.report_type)
            if self.report_type == "A":
                node(summary, "fileramendmentnote", fmt.clean_text(self.amendment_note, "amendment_note"))

    def action_download_xml(self):
        self.ensure_one()
        if not self.xml_filename:
            raise UserError(self.env._("Finalize the return to create the CRA file."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self._name}/{self.id}/xml_file/{self.xml_filename}?download=true",
            "target": "download",
        }

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    def action_print_slips(self):
        """Two copies of each slip on one sheet, as CRA asks for slips delivered on paper."""
        return self._print_slips({"l10n_ca_copies": 2})

    def action_print_duplicates(self):
        """Replacement copies for slips already delivered, marked DUPLICATE as CRA asks."""
        return self._print_slips({"l10n_ca_copies": 2, "l10n_ca_duplicate": True})

    def _print_slips(self, data):
        self.ensure_one()
        if self.state == "draft":
            raise UserError(self.env._("Finalize the return before printing slips."))
        # Delivery reads only this return's slips, so access to every branch is not needed.
        slips = self._slips_to_deliver()
        if not slips:
            raise UserError(self.env._("No slips on this return are current: they were amended or cancelled since."))
        # The slip uses no company letterhead, so Odoo's prompt to set one up is skipped.
        report = self.env.ref("l10n_ca_contractor_slips.action_report_l10n_ca_slip")
        # With options, the web client leaves the record ids out of the report URL, so they travel
        # in the options too (see report_l10n_ca_slip.py).
        return report.report_action(slips, data={**data, "ids": slips.ids}, config=False)

    def _slips_to_deliver(self):
        """Slips the recipient should hold: filed as original or amended and not replaced since, and
        cancellations, which the recipient is told about with a copy marked cancelled."""
        self.ensure_one()
        return self.slip_ids.filtered(lambda s: s.rpt_tcd in ("O", "A", "C") and not s.superseded)

    def action_send_slips(self):
        """Queue an email to each consenting recipient with their own slip. A scheduled job renders
        and sends them in batches, so a large return does not hit the request time limit."""
        self.ensure_one()
        if self.state == "draft":
            raise UserError(self.env._("Finalize the return before sending slips."))
        self.check_access("write")
        return self._queue_slip_emails()

    def _queue_slip_emails(self):
        # The access check is done; contacts kept to one branch must not stop head office.
        slips = self._slips_to_deliver().sudo()
        # Consent covers only the payer it was given to: this return's company.
        consenting = slips.filtered(
            lambda s: s.partner_id.with_company(self.company_id).l10n_ca_slip_email_consent and s.partner_id.email
        )
        invalid = consenting.filtered(lambda s: not email_normalize(s.partner_id.email))
        consenting -= invalid
        already = consenting.filtered(lambda s: s.email_state in ("outgoing", "sent", "received"))
        to_send = consenting - already
        for slip in to_send:
            slip.write({"send_requested_uid": self.env.uid, "send_to_email": slip.partner_id.email_formatted})
        if to_send:
            self.env.ref("l10n_ca_contractor_slips.ir_cron_send_slips")._trigger()
        others = slips - consenting
        # Only an active portal login that has been used counts, and not for a recipient who asked
        # for paper: someone who never signed in cannot be expected to find the slip there.
        portal_slips = others.filtered(
            lambda s: not s.partner_id.l10n_ca_slip_paper and s.partner_id.user_ids.filtered("share")
        )
        on_portal = portal_slips.filtered(lambda s: s.partner_id.user_ids.filtered(lambda u: u.share and u.login_date))
        never_signed_in = portal_slips - on_portal
        parts = [self.env._("%(count)s slip email(s) queued; they go out within a few minutes.", count=len(to_send))]
        if already:
            parts.append(self.env._("%(count)s already emailed were skipped.", count=len(already)))
        if invalid:
            parts.append(self.env._(
                "%(count)s recipient(s) gave consent but have an email address that is not valid: %(names)s. Correct "
                "it, or give them their slips another way.",
                count=len(invalid), names=", ".join(invalid.partner_id.mapped("display_name")),
            ))
        if on_portal:
            parts.append(self.env._(
                "%(count)s recipient(s) without email consent have a portal account and can download their slip there.",
                count=len(on_portal),
            ))
        if never_signed_in:
            parts.append(self.env._(
                "%(count)s recipient(s) have a portal login they have never used, so they are listed for paper.",
                count=len(never_signed_in),
            ))
        paper = others - on_portal
        if paper and self.slip_type == "t4a":
            parts.append(self.env._(
                "Give the other %(count)s recipient(s) two paper copies (Print slips): %(names)s.",
                count=len(paper), names=", ".join(paper.partner_id.mapped("display_name")),
            ))
        elif paper:
            parts.append(self.env._(
                "Giving T5018 slips to subcontractors is optional. To give paper copies, print slips for: %s.",
                ", ".join(paper.partner_id.mapped("display_name")),
            ))
        message = " ".join(parts)
        self.message_post(body=message, subtype_xmlid="mail.mt_note")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": "success", "sticky": bool(others - on_portal)},
        }

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(record.state != "draft" for record in self):
            raise UserError(self.env._("Only draft returns can be deleted."))
