# Copyright 2026 Solvync Inc.
# License LGPL-3.0 (https://www.gnu.org/licenses/lgpl-3.0).
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ca_contractor_slips.models import cra_format as fmt

from .common import CONTRACTOR_BN, PAYER_BN, VALID_SIN, FakeResponse, L10nCaSlipsCommon


@tagged("post_install", "-at_install")
class TestCraXml(L10nCaSlipsCommon):

    def test_t15_t4a_file_validates_and_totals_match(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 1234.56, taxes=self.gst), "2026-03-10")
        self._pay(self._fee_bill(self.contractor_c, "2026-03-01", 765.44), "2026-03-10")
        self.sub_corp.l10n_ca_slip_type = "t4a"
        self._pay(self._fee_bill(self.sub_corp, "2026-03-01", 2000.0), "2026-03-10")
        slip_return = self._return()
        root = self._finalize(slip_return)
        self.assertEqual(slip_return.state, "final")
        self.assertEqual(root.tag, "Submission")
        self.assertEqual(root.findtext("T619/TransmitterAccountNumber/bn9"), PAYER_BN)
        self.assertEqual(root.findtext("T619/sbmt_ref_id"), slip_return.sbmt_ref_id)
        self.assertEqual(root.findtext("T619/CNTC/cntc_area_cd"), "403")
        self.assertEqual(root.findtext("T619/CNTC/cntc_phn_nbr"), "555-0142")
        slips = root.findall("Return/T4A/T4ASlip")
        self.assertEqual(len(slips), 3)
        amounts = [float(s.findtext("T4A_AMT/fee_or_oth_srvc_amt")) for s in slips]
        self.assertAlmostEqual(sum(amounts), 4000.0)
        summary = root.find("Return/T4A/T4ASummary")
        self.assertEqual(summary.findtext("T4A_TAMT/rpt_tot_fee_srvc_amt"), "4000.00")
        self.assertEqual(summary.findtext("slp_cnt"), "3")
        self.assertEqual(summary.findtext("tx_yr"), "2026")
        self.assertEqual(summary.findtext("bn"), f"{PAYER_BN}RP0001")
        self.assertEqual({s.findtext("bn") for s in slips}, {f"{PAYER_BN}RP0001"})

        by_name = {(s.findtext("RCPNT_NM/snm") or s.findtext("RCPNT_CORP_NM/l1_nm")): s for s in slips}
        self.assertEqual(by_name["Martin"].findtext("sin"), VALID_SIN)
        self.assertEqual(by_name["Martin"].findtext("RCPNT_NM/gvn_nm"), "Alex")
        self.assertEqual(by_name["Martin"].findtext("RCPNT_ADDR/pstl_cd"), "T2P1J9")
        self.assertEqual(by_name["Martin"].findtext("RCPNT_ADDR/cntry_cd"), "CAN")
        self.assertEqual(by_name["Roy"].findtext("sin"), fmt.SIN_PLACEHOLDER)
        corp = by_name["Prairie Framing Ltd"]
        self.assertEqual(corp.findtext("sin"), fmt.SIN_PLACEHOLDER)
        self.assertEqual(corp.findtext("rcpnt_bn"), f"{CONTRACTOR_BN}RT0001")
        self.assertIsNone(corp.find("RCPNT_NM"))

    def test_t16_special_characters(self):
        self.sub_corp.write({"name": "Lévesque & Fils Construction Ltée", "l10n_ca_slip_type": "t4a"})
        self.contractor_a.write({"name": "Liam O'Brien", "street": "12 Rue du Pré <B>"})
        self._pay(self._fee_bill(self.sub_corp, "2026-03-01", 900.0), "2026-03-10")
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self.assertEqual(self._slip(slip_return, self.contractor_a).surname, "O'Brien")
        root = self._finalize(slip_return)
        raw = self._xml_bytes(slip_return).decode()
        self.assertTrue(raw.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn("Lévesque &amp; Fils", raw)
        self.assertIn("O&apos;Brien", raw)
        self.assertNotIn("<B>", raw)
        corp = [s for s in root.iter("T4ASlip") if s.find("RCPNT_CORP_NM") is not None][0]
        self.assertEqual(corp.findtext("RCPNT_CORP_NM/l1_nm"), "Lévesque & Fils Construction")
        self.assertEqual(corp.findtext("RCPNT_CORP_NM/l2_nm"), "Ltée")

    def test_t21_t5018_file_validates_and_totals_match(self):
        self._pay(self._bill(self.sub_corp, "2026-03-01", [(10000.0, self.construction_account, self.gst)]), "2026-03-10")
        self._pay(self._bill(self.sub_individual, "2026-05-01", [(2000.0, self.construction_account, self.gst)]), "2026-05-10")
        slip_return = self._return("t5018")
        root = self._finalize(slip_return)
        slips = root.findall("Return/T5018/T5018Slip")
        self.assertEqual(len(slips), 2)
        summary = root.find("Return/T5018/T5018Summary")
        self.assertEqual(summary.findtext("tot_sbctrcr_amt"), "12600.00")
        self.assertEqual(summary.findtext("slp_cnt"), "2")
        self.assertEqual(summary.findtext("bn"), f"{PAYER_BN}RZ0001")
        self.assertEqual(
            (summary.findtext("PRD_END_DT/dy"), summary.findtext("PRD_END_DT/mo"), summary.findtext("PRD_END_DT/yr")),
            ("31", "12", "2026"),
        )
        by_type = {s.findtext("rcpnt_tcd"): s for s in slips}
        self.assertEqual(by_type["3"].findtext("CORP_PTNRP_NM/l1_nm"), "Prairie Framing Ltd")
        self.assertEqual(by_type["3"].findtext("sbctrcr_amt"), "10500.00")
        self.assertEqual(by_type["1"].findtext("sin"), VALID_SIN)
        self.assertEqual(by_type["1"].findtext("sbctrcr_amt"), "2100.00")

    def test_transmitter_bn15_and_repid(self):
        self.company.write({
            "l10n_ca_slip_signin": "rac", "l10n_ca_slip_transmitter_account": f"{PAYER_BN}RP0001",
            "l10n_ca_slip_transmitter_repid": "R123456",
        })
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        root = self._finalize(self._return())
        self.assertEqual(root.findtext("T619/TransmitterAccountNumber/bn15"), f"{PAYER_BN}RP0001")
        self.assertIsNone(root.find("T619/TransmitterAccountNumber/bn9"))
        self.assertEqual(root.findtext("T619/TransmitterRepID/RepID"), "R123456")

    def test_schema_failure_blocks_finalize(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self._load_schemas()
        with patch.object(type(slip_return), "_build_xml", lambda self: b"<Submission><T619/></Submission>"):
            with self.assertRaisesRegex(UserError, "schema"):
                slip_return.action_finalize()
        self.assertEqual(slip_return.state, "draft")
        self.assertFalse(slip_return.xml_filename)

    def test_unreachable_schemas_block_finalize(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        slip_return = self._return()
        self.env["ir.attachment"].search([("name", "=like", "l10n_ca_contractor_slips.%")]).unlink()
        with patch("requests.get", return_value=FakeResponse(b"")):
            with self.assertRaisesRegex(UserError, "could not be downloaded"):
                slip_return.action_finalize()

    def test_text_cleaning(self):
        self.assertEqual(fmt.clean_text("  Café   Ltée \n Ste. #2 (rear)  ", "address_line"), "Café Ltée Ste. #2 (rear)")
        self.assertEqual(fmt.clean_text("Smith/Jones, Ltd.", "name_line"), "Smith Jones Ltd.")
        self.assertEqual(fmt.clean_text("Peña Gómez", "surname"), "Pena Gomez")
        self.assertEqual(fmt.clean_text("Strauß Wałęsa", "name_line"), "Strauss Walesa")
        self.assertEqual(fmt.clean_text("O\u2019Brien", "surname"), "O'Brien")
        self.assertEqual(fmt.clean_text("Cost: $500; 50% off!", "amendment_note"), "Cost: $500; 50% off!")
        self.assertEqual(fmt.clean_text("A very long surname over twenty", "surname"), "A very long surname")
        self.assertEqual(fmt.postal_code("t2e 2n4"), "T2E2N4")
        self.assertEqual(fmt.phone_parts("(403) 555-0142 ext. 12"), ("403", "555-0142", "12"))
        self.assertIsNone(fmt.phone_parts("555-0142"))
        self.assertEqual(fmt.split_lines("Lévesque & Fils Construction Ltée", "name_line", 2),
                         ["Lévesque & Fils Construction", "Ltée"])


@tagged("post_install", "-at_install")
class TestTransmitterAccount(L10nCaSlipsCommon):

    def test_represent_a_client_leaves_out_a_nine_digit_account(self):
        self._pay(self._fee_bill(self.contractor_a, "2026-03-01", 900.0), "2026-03-10")
        self.company.write({
            "l10n_ca_slip_signin": "rac", "l10n_ca_slip_transmitter_repid": "ABC1234",
            "l10n_ca_slip_transmitter_account": PAYER_BN,
        })
        root = self._finalize(self._return())
        self.assertIsNone(root.find("T619/TransmitterAccountNumber/bn9"))
        self.assertEqual(root.findtext("T619/TransmitterRepID/RepID"), "ABC1234")
