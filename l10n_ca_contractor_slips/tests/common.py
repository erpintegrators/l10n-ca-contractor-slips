# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
import base64
import os
from unittest.mock import patch

from lxml import etree

from odoo import Command, fields
from odoo.modules import get_module_path

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

# Made-up test values that pass the business number and SIN check digits.
PAYER_BN = "123026635"
CONTRACTOR_BN = "897012340"
VALID_SIN = "130692544"
OTHER_SIN = "193456787"
# How the slip prints a full SIN, and how it prints the masked one.
PRINTED_SIN = "130 692 544"
MASKED_SIN = "*** *** 544"


def cra_schema_zip_path():
    """The CRA schema package is downloaded by CI (and by dev/fetch_schemas.sh locally) next to
    the module, never committed."""
    if os.environ.get("L10N_CA_SLIPS_XSD_ZIP"):
        return os.environ["L10N_CA_SLIPS_XSD_ZIP"]
    repo = os.path.dirname(get_module_path("l10n_ca_contractor_slips"))
    return os.path.join(repo, ".cra", "zip", "xmlschm1-27-1.zip")


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class L10nCaSlipsCommon(AccountTestInvoicingCommon):
    # Credit notes count on the day they are matched, so tests run on a fixed date in 2026.
    freeze_time = "2026-11-15 12:00:00"

    @classmethod
    @AccountTestInvoicingCommon.setup_country("ca")
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data["company"]
        cls.cad = cls.company.currency_id
        cls.filing_contact = cls.env["res.partner"].create({
            "name": "Jordan Filer",
            "phone": "+1 403-555-0142",
            "email": "filings@example.com",
            "parent_id": cls.company.partner_id.id,
        })
        cls.company.partner_id.write({
            "street": "100 Main Street NE",
            "city": "Calgary",
            "state_id": cls.env.ref("base.state_ca_ab").id,
            "zip": "T2E 2N4",
            "country_id": cls.env.ref("base.ca").id,
        })
        cls.company.write({
            "name": "Northern Build Co",
            "l10n_ca_slip_rp_account": f"{PAYER_BN}RP0001",
            "l10n_ca_slip_rz_account": f"{PAYER_BN}RZ0001",
            "l10n_ca_slip_transmitter_account": PAYER_BN,
            "l10n_ca_slip_contact_id": cls.filing_contact.id,
        })

        expense = cls.company_data["default_account_expense"]
        cls.tag_t4a = cls.env.ref("l10n_ca_contractor_slips.account_tag_t4a_fees")
        cls.tag_t5018 = cls.env.ref("l10n_ca_contractor_slips.account_tag_t5018_construction")
        cls.fees_account = cls.copy_account(expense, {"name": "Professional fees", "tag_ids": [Command.set(cls.tag_t4a.ids)]})
        cls.construction_account = cls.copy_account(
            expense, {"name": "Subcontractors", "tag_ids": [Command.set(cls.tag_t5018.ids)]}
        )
        cls.supplies_account = cls.copy_account(expense, {"name": "Supplies"})
        cls.goods_product = cls._create_product(name="Lumber", type="consu", property_account_expense_id=cls.construction_account)
        cls.service_product = cls._create_product(name="Site labour", type="service", property_account_expense_id=cls.supplies_account)
        cls.gst = cls.env["account.tax"].create({
            "name": "GST 5% (purchases)",
            "amount": 5.0,
            "amount_type": "percent",
            "type_tax_use": "purchase",
            "company_id": cls.company.id,
        })

        ca, ab = cls.env.ref("base.ca"), cls.env.ref("base.state_ca_ab")
        address = {"street": "12 River Road", "city": "Calgary", "state_id": ab.id, "zip": "T2P 1J9", "country_id": ca.id}
        Partner = cls.env["res.partner"]
        person = {"l10n_ca_recipient_type": "1", **address}
        cls.contractor_a = Partner.create({"name": "Alex Martin", "l10n_ca_slip_type": "t4a", "l10n_ca_sin": VALID_SIN, **person})
        cls.contractor_b = Partner.create({"name": "Bailey Chen", "l10n_ca_slip_type": "t4a", "l10n_ca_sin": OTHER_SIN, **person})
        cls.contractor_c = Partner.create({"name": "Casey Roy", "l10n_ca_slip_type": "t4a", **person})
        cls.sub_corp = Partner.create({
            "name": "Prairie Framing Ltd",
            "is_company": True,
            "vat": f"{CONTRACTOR_BN}RT0001",
            "l10n_ca_slip_type": "t5018",
            "l10n_ca_recipient_type": "3",
            **address,
        })
        cls.sub_individual = Partner.create({
            "name": "Sam Okafor", "l10n_ca_slip_type": "t5018", "l10n_ca_sin": VALID_SIN, **person,
        })

        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.moveless_journal = cls.env["account.journal"].create({
            "name": "Bank without outstanding accounts",
            "type": "bank",
            "code": "BNKX",
            "company_id": cls.company.id,
        })
        (cls.moveless_journal.inbound_payment_method_line_ids
         | cls.moveless_journal.outbound_payment_method_line_ids).payment_account_id = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _bill(cls, partner, date, lines, move_type="in_invoice", currency=None, post=True):
        """lines: list of (price_unit, account or product record, taxes)."""
        invoice_lines = []
        for price, target, taxes in lines:
            vals = {"price_unit": price, "quantity": 1.0, "tax_ids": [Command.set(taxes.ids if taxes else [])]}
            if target._name == "product.product":
                vals["product_id"] = target.id
            else:
                vals.update(name="Services", account_id=target.id)
            invoice_lines.append(Command.create(vals))
        move = cls.env["account.move"].create({
            "move_type": move_type,
            "partner_id": partner.id,
            "invoice_date": date,
            "date": date,
            "currency_id": (currency or cls.cad).id,
            "invoice_line_ids": invoice_lines,
        })
        if post:
            move.action_post()
        return move

    @classmethod
    def _fee_bill(cls, partner, date, amount, taxes=None, move_type="in_invoice"):
        return cls._bill(partner, date, [(amount, cls.fees_account, taxes)], move_type=move_type)

    @classmethod
    def _pay(cls, moves, date, amount=None, journal=None, currency=None):
        vals = {"payment_date": date, "journal_id": (journal or cls.bank_journal).id}
        if amount is not None:
            vals["amount"] = amount
        if currency:
            vals["currency_id"] = currency.id
        return cls._register_payment(moves, **vals)

    def _return(self, slip_type="t4a", year=2026, compute=True):
        record = self.env["l10n.ca.slip.return"].create({"slip_type": slip_type, "year": year})
        if compute:
            record.action_compute()
        return record

    def _slip(self, slip_return, partner):
        return slip_return.slip_ids.filtered(lambda s: s.partner_id == partner)

    def _load_schemas(self):
        path = cra_schema_zip_path()
        if not os.path.exists(path):
            message = f"CRA schema package not found at {path}; run dev/fetch_schemas.sh"
            if os.environ.get("L10N_CA_SLIPS_REQUIRE_SCHEMAS"):
                self.fail(message)
            self.skipTest(message)
        with open(path, "rb") as handle:
            content = handle.read()
        with patch("requests.get", return_value=FakeResponse(content)):
            self.assertTrue(self.env["l10n.ca.slip.return"]._l10n_ca_load_cra_schemas(force=True))

    def _finalize(self, slip_return):
        self._load_schemas()
        slip_return.action_finalize()
        return etree.fromstring(self._xml_bytes(slip_return))

    def _filed(self, slip_return):
        self._finalize(slip_return)
        slip_return.action_mark_filed()
        return slip_return

    def _amend(self, slip_return):
        return self.env["l10n.ca.slip.return"].browse(slip_return.action_create_amendment()["res_id"])

    @classmethod
    def _user(cls, login, groups, companies=None, partner=None):
        companies = companies or cls.company
        values = {
            # A user takes its contact's name, so a login made for an existing contact keeps it.
            "name": partner.name if partner else login.replace(".", " ").title(),
            "login": login,
            "groups_id": [Command.set([cls.env.ref(xmlid).id for xmlid in groups])],
            "company_ids": [Command.set(companies.ids)],
            "company_id": companies[:1].id,
        }
        if partner:
            values["partner_id"] = partner.id
        else:
            values["email"] = f"{login}@example.com"
        return cls.env["res.users"].create(values)

    def _send(self, slip_return):
        """Queue the return's slip emails and run the scheduled job's work at once."""
        action = slip_return.action_send_slips()
        self.env["l10n.ca.slip"].sudo().search([("send_requested_uid", "!=", False)])._send_pending()
        return action

    def _slip_mail(self, partner):
        return self.env["mail.mail"].sudo().search([("email_to", "ilike", partner.email)])

    @staticmethod
    def _xml_bytes(slip_return):
        return base64.b64decode(slip_return.with_context(bin_size=False).xml_file)

    @staticmethod
    def _today():
        return fields.Date.today()
