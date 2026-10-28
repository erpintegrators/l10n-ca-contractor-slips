**ERPintegrators.com** | by **Solvync Inc.**

Prepare T4A box 048 and T5018 contractor tax slips in Odoo 19, using the vendor payments
recorded in your accounting. Review each contractor's total, trace the bills and payments behind
it, and create a CRA XML file for your business to review and upload.

The module covers two Canadian contractor reporting workflows:

- **T4A, box 048**: fees for services paid to self-employed people and businesses,
  before GST/HST and PST, for each recipient paid more than $500 in the calendar year.
- **T5018**: payments to construction subcontractors, GST/HST and PST included, for the
  reporting period (calendar or fiscal year). By default a slip is issued when the services part,
  tax included, reaches $500 (Form T5018SUM); a setting applies the slip page's test of more than
  $500 before tax instead.

Amounts come from what you actually paid. The module reads posted vendor bills and the cash
matched to them, so a bill dated in December and paid in January counts in January, a refund
lowers the total. T4A leaves goods out; T5018 follows the selected mixed-bill setting.
A credit note applied to a bill
counts as settling both, each at its own mix of services and goods. Foreign-currency bills count
the Canadian dollars actually paid, and an early payment discount reduces only the bill that
earned it. Every amount on a slip links back to the bills and payments behind it.

From there you can:

- review and adjust slips (each adjustment needs a reason and is logged),
- finalize the return, which produces the CRA XML file and checks it against CRA's published
  2026 schemas now, with the 2027 package selected from 11 January 2027,
- print customized slips laid out to follow CRA's rules for slips you print yourself (Information
  Circular IC97-2R20), two copies per sheet, email them to recipients who agreed to electronic
  slips, and let recipients download their own slip from the portal,
- amend a filed return or cancel a slip, with the report codes CRA expects, and give recipients a
  copy marked amended or cancelled.

It runs on Odoo Community and Enterprise, on Odoo.sh or your own server, and uses standard Odoo
records throughout: contacts, the Tax ID field, account tags, vendor bills, payments and bank
reconciliation. Odoo Online databases cannot install modules from the app store. The module
downloads CRA's public XML schemas from canada.ca the first time you finalize a return.

## Before you file

This module helps you prepare T4A and T5018 returns for the Canada Revenue Agency (CRA). It gives
no tax, accounting or legal advice; decide what is reportable with your accountant.

You remain responsible for every slip, the file you upload, deadlines, delivery to recipients, and
any CRA penalty or interest. Check each slip against your records before filing.

Schema validation checks the file's format only. It cannot tell you whether amounts or identifiers
are correct, or whether CRA will accept the return.

Solvync Inc. has no affiliation with CRA, and CRA has not endorsed this module.

This software is licensed under the GNU Lesser General Public License, version 3. To the extent
the law allows, it is provided as is, without warranty of any kind, including as to accuracy, and
Solvync Inc. is not liable for any loss arising from its use.

## Privacy

The business using this module is accountable for the personal information in it under PIPEDA or its
provincial equivalent. Solvync receives none of it. The only outside call the module makes downloads
CRA's public schemas from canada.ca, and it sends no data.

SINs are collected under section 237 of the Income Tax Act and used for these slips only. Odoo stores
them in the database and its backups without encryption, so give accounting administrators two-step
login and mask SINs in any copy made for support. Each SIN sits on the contact, kept for the main
company that collected it, on every slip that reported it and in the CRA file stored with each
return. Clearing it from the contact leaves those
copies, and the module cannot yet remove SINs from final or filed returns, so agree with your
accountant how you will destroy them once each return's six-year record period ends.
CRA requires the recipient's consent before slips are emailed, and emailed slips carry the full SIN
over ordinary email. Odoo deletes the emailed copy once it is sent; a failed email keeps its PDF
until the slip is emailed again, for at most 30 days. Odoo 19 controls dynamic template editing
through system administration and **Mail Template Editor** permissions. Give those rights only
to people trusted to see SINs; Odoo 19 has no separate Restrict Template Rendering setting. An exposed SIN will usually meet the real risk of significant harm test, which brings
duties to report and notify (PIPEDA section 10.1; Alberta PIPA section 34.1).

Uninstalling the module deletes every return, slip and CRA file it holds, any slip email still
waiting, and the SINs, slip settings and email consents stored on contacts. Download the CRA files,
keep the PDFs you need and export your consent records first. The T4A and T5018 tags are removed
from your accounts as well.

