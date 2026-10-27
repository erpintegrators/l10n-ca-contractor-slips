# Seed a demo database with a Canadian company, contractors, bills and payments for 2026.
# Run with: odoo shell -d <db> < dev/seed_demo.py
from odoo import Command

company = env.company
ca = env.ref("base.ca")
company.write({"name": "Northern Build Co", "country_id": ca.id})
if company.chart_template != "ca_2023":
    env["account.chart.template"].try_loading("ca_2023", company=company, install_demo=False)
company.partner_id.write({
    "street": "100 Main Street NE", "city": "Calgary", "state_id": env.ref("base.state_ca_ab").id,
    "zip": "T2E 2N4", "country_id": ca.id, "lang": "en_US",
})
# Business numbers and SINs below are made-up values that pass the check digits.
contact = env["res.partner"].create({
    "name": "Jordan Filer", "phone": "403-555-0142", "email": "filings@example.com", "parent_id": company.partner_id.id,
})
company.write({
    "l10n_ca_slip_rp_account": "123026635RP0001",
    "l10n_ca_slip_rz_account": "123026635RZ0001",
    "l10n_ca_slip_transmitter_account": "123026635",
    "l10n_ca_slip_contact_id": contact.id,
})
expense = env["account.account"].search([("account_type", "=", "expense"), ("company_ids", "in", company.id)], limit=1)
fees = expense.copy({"name": "Professional fees", "code": "511900",
                     "tag_ids": [Command.set(env.ref("l10n_ca_contractor_slips.account_tag_t4a_fees").ids)]})
subs = expense.copy({"name": "Subcontractors", "code": "511950",
                     "tag_ids": [Command.set(env.ref("l10n_ca_contractor_slips.account_tag_t5018_construction").ids)]})
gst = env["account.tax"].search([("type_tax_use", "=", "purchase"), ("company_id", "=", company.id),
                                 ("amount", "=", 5.0)], limit=1)
address = {"street": "12 River Road", "city": "Calgary", "state_id": env.ref("base.state_ca_ab").id,
           "zip": "T2P 1J9", "country_id": ca.id}
P = env["res.partner"]
people = [
    P.create({"name": "Alex Martin", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1",
              "email": "alex@example.com", "l10n_ca_slip_email_consent": True, **address}),
    P.create({"name": "Bailey Chen", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1", **address}),
    P.create({"name": "Casey Roy", "l10n_ca_slip_type": "t4a", "l10n_ca_recipient_type": "1", **address}),
    P.create({"name": "Lévesque & Fils Construction Ltée", "is_company": True, "vat": "897012340RT0001",
              "l10n_ca_slip_type": "t5018", "l10n_ca_recipient_type": "3", **address}),
]
bank = env["account.journal"].search([("type", "=", "bank"), ("company_id", "=", company.id)], limit=1)
for partner, account, amount, day in ((people[0], fees, 1850.0, "03"), (people[1], fees, 620.0, "05"),
                                      (people[2], fees, 480.0, "06"), (people[3], subs, 24000.0, "07")):
    bill = env["account.move"].create({
        "move_type": "in_invoice", "partner_id": partner.id, "invoice_date": f"2026-{day}-01",
        "invoice_line_ids": [Command.create({"name": "Services", "account_id": account.id, "price_unit": amount,
                                             "tax_ids": [Command.set(gst.ids)]})],
    })
    bill.action_post()
    env["account.payment.register"].with_context(active_model="account.move", active_ids=bill.ids).create({
        "payment_date": f"2026-{day}-20", "journal_id": bank.id,
    })._create_payments()
for slip_type in ("t4a", "t5018"):
    env["l10n.ca.slip.return"].create({"slip_type": slip_type, "year": 2026}).action_compute()
env.cr.commit()
print("seeded", company.name, company.chart_template)
