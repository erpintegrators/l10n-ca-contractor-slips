## Review the contractor reporting workflow

These screens show fictional T5018 records in Odoo 19 Community. The closed 2025 calendar
return has three slips totalling CAD34,650. The example uses the 2026 XML submission format.
The accounting and filing limits below apply to both Community and Enterprise.

<div class="row">
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/01-reporting-period.png" alt="T5018 return in Odoo 19 showing the closed 2025 calendar period, three slips and CAD34,650 reported" />
</div>
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/02-reported-amount.png" alt="T5018 example: Cedarline Framing Ltd., CAD24,000 before tax and CAD25,200 reported with tax" />
</div>
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/03-payment-trace.png" alt="Two dated matched vendor bills supporting Cedarline Framing Ltd. T5018 payments" />
</div>
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/04-cra-xml.png" alt="Finalized T5018 return with Download CRA file, ready for review and separate upload to CRA" />
</div>
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/05-recipient-portal.png" alt="Recipient portal showing the contractor's own 2025 T5018 slip, CAD25,200 reported and a PDF download" />
</div>
</div>

### Watch the workflow in Odoo 19

<img width="720" height="450" src="t4a-t5018-odoo-19-walkthrough.gif" alt="Odoo 19 T5018 walkthrough: calculate three slips, inspect the amount and payment trace, finalize and download the CRA XML file" />

This 16-second walkthrough uses a camera and cursor over reproduced Odoo screens. Calculate
slips, review the contractor's amount and matched bills, finalize, then download the CRA file.
Review the file and upload it to CRA separately using your own authorized account. Downloading
the XML does not file the return or establish CRA acceptance.

## Questions about T4A and T5018 in Odoo

### Which T4A slips does this module prepare?

It prepares T4A box 048, fees for services, from supported contractor payments in Odoo.
It does not prepare the full range of T4A income boxes or employee T4 payroll slips.
Review the setup instructions and known limits with the person responsible for your return.

### Does it submit the return to CRA?

You download the T4A or T5018 XML file and upload it through CRA's Internet File Transfer
service using your own authorized account. The module checks XML structure against the
published schema. It does not submit the return or verify CRA acceptance.

### Can I trace an amount back to the vendor payments?

Each calculated slip lists the supported payments and bills behind its amount. Review these
lines, the return's warnings and any adjustments before filing. Opening balances and journal
settlements need the checks described in the setup instructions and known limits.

### How do recipients get their copies?

You can print recipient PDFs or provide them through the recipient's Odoo portal. Email
delivery requires the recipient's consent and your own configured outgoing mail server.
Review portal access, consent, paper requests and delivery results before treating delivery
as complete.

### Can I install it on Odoo Online?

Use Odoo 19 Community or Enterprise on Odoo.sh or your own server. Odoo Online does not
allow installation of this custom Python module. The accounting workflow uses Canadian
localization and the setup described below.

### What does the module cost?

The Odoo Apps price is **US$199** for this Odoo version. The LGPL-3 license remains in place,
and the source repository is public. Hosting and Odoo subscriptions are separate. Bug fixes and
configuration advice follow the Odoo Apps support terms; installation, customization and other
services are quoted separately. Check each slip against your records before filing. Your business
remains responsible for the return and recipient delivery.

### Who should maintain the annual filing setup?

Assign an owner to check the current CRA schema, form requirements and your reporting
settings before each filing season. Read the known issues and roadmap before choosing a
filing workflow. Solvync Inc. maintains the module; your filing owner checks the reporting
treatment and submission requirements for your business.
