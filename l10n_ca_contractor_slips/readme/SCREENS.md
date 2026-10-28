## Review the contractor reporting workflow

These screens show a staged T5018 return in Odoo 18 Enterprise. Names, amounts and records
are demo data. The module also supports T4A box 048. Each image focuses on one part of the
workflow; the accounting and filing limits below apply to both editions.

<div class="row">
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/01-reporting-period.png" alt="T5018 return in Odoo showing the reporting period, ten slips and a total reported of 778,869 Canadian dollars" />
</div>
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/02-reported-amount.png" alt="A contractor's T5018 slip showing 186,400 dollars before tax and 195,720 dollars reported with tax" />
</div>
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/03-payment-trace.png" alt="The payment trace on an Odoo contractor slip, with four paid dates and the vendor bills each payment settled" />
</div>
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/04-cra-xml.png" alt="A finalized T5018 return with Download CRA file and its generated XML attachment, prepared for the buyer to upload" />
</div>
<div class="col-12 col-lg-6 mb-4">
<img width="1200" height="1200" src="screenshots/05-recipient-portal.png" alt="The contractor portal listing a T5018 for 2026, the recipient's amount and a PDF download link" />
</div>
</div>

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

Use Odoo 18 Community or Enterprise on Odoo.sh or your own server. Odoo Online does not
allow installation of this custom Python module. The accounting workflow uses Canadian
localization and the setup described below.

### What does the beta cost?

The module is free under LGPL-3. Hosting, Odoo subscriptions and any separately agreed
implementation or support services are outside that price. Check each slip against your
records before filing. Your business remains responsible for the return and recipient delivery.

### Who should maintain the annual filing setup?

Assign an owner to check the current CRA schema, form requirements and your reporting
settings before each filing season. Read the known issues and roadmap before choosing a
filing workflow. Current CRA interpretation questions remain part of the beta review.
