"""Professional PDF invoice generation using ReportLab with a tiny fallback writer."""
from __future__ import annotations

import logging
from pathlib import Path

from .models import Invoice
from .utils import amount_to_words

BASE_DIR = Path(__file__).resolve().parent
INVOICE_DIR = BASE_DIR / "invoices"
logger = logging.getLogger(__name__)


class PDFGenerator:
    def __init__(self, output_dir: Path = INVOICE_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, invoice: Invoice) -> str:
        path = self.output_dir / f"{invoice.invoice_number}.pdf"
        try:
            self._generate_reportlab(invoice, path)
        except ModuleNotFoundError:
            self._generate_minimal_pdf(invoice, path)
        except Exception:
            logger.exception("ReportLab PDF generation failed", extra={"invoice_number": invoice.invoice_number})
            raise
        return str(path)

    def _generate_reportlab(self, invoice: Invoice, path: Path) -> None:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        font = "Helvetica"
        bold = "Helvetica-Bold"
        for font_path in (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
            if font_path.exists():
                try:
                    pdfmetrics.registerFont(TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
                    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
                    font, bold = "DejaVuSans", "DejaVuSans-Bold"
                except Exception:
                    logger.warning("Unable to register DejaVu fonts for rupee symbol", exc_info=True)
                break

        blue = colors.HexColor("#123C69"); accent = colors.HexColor("#1F7A8C"); light = colors.HexColor("#EEF5FF"); border = colors.HexColor("#94A3B8"); text = colors.HexColor("#1F2937")
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle("Small", parent=styles["BodyText"], fontName=font, fontSize=8, leading=10, textColor=text))
        styles.add(ParagraphStyle("Tiny", parent=styles["BodyText"], fontName=font, fontSize=7, leading=9, textColor=text))
        styles.add(ParagraphStyle("Cell", parent=styles["Small"], wordWrap="CJK"))
        styles.add(ParagraphStyle("CellRight", parent=styles["Small"], alignment=TA_RIGHT))
        styles.add(ParagraphStyle("CellCenter", parent=styles["Small"], alignment=TA_CENTER))
        styles.add(ParagraphStyle("SmallCenter", parent=styles["Small"], alignment=TA_CENTER))
        styles.add(ParagraphStyle("Section", parent=styles["Small"], fontName=bold, textColor=blue, fontSize=9, leading=11))
        styles.add(ParagraphStyle("Badge", parent=styles["BodyText"], alignment=TA_CENTER, fontName=bold, fontSize=14, leading=16, textColor=colors.white))
        styles.add(ParagraphStyle("Company", parent=styles["BodyText"], fontName=bold, fontSize=12, leading=15, textColor=blue, wordWrap="CJK"))

        def esc(value) -> str:
            return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        def money(value) -> str: return f"₹{float(value or 0):,.2f}"
        def company_address() -> str: return ", ".join([p for p in [invoice.company.address, invoice.company.city, invoice.company.state, invoice.company.pin_code] if p])
        def image_path(value: str | None) -> Path | None:
            if not value: return None
            p = Path(value)
            return p if p.is_absolute() else BASE_DIR.parent / p
        def fitted_image(path_value: Path, box_width, box_height) -> Image:
            """Return a ReportLab image scaled proportionally inside a fixed box."""
            reader = ImageReader(str(path_value))
            width, height = reader.getSize()
            if not width or not height:
                raise ValueError("Invalid image dimensions")
            scale = min(box_width / width, box_height / height)
            return Image(str(path_value), width=width * scale, height=height * scale)

        doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=12*mm, leftMargin=12*mm, topMargin=13*mm, bottomMargin=18*mm)
        story = []
        logo_path = image_path(invoice.company.logo_path)
        logo_box = 30*mm
        if logo_path and logo_path.exists():
            try:
                logo_content = fitted_image(logo_path, logo_box, logo_box)
            except Exception:
                logger.warning("Skipping invalid company logo", exc_info=True, extra={"company_id": invoice.company_id})
                logo_content = Paragraph("<b>LOGO</b>", styles["Section"])
        else:
            logo_content = Paragraph("<b>LOGO</b>", styles["Section"])
        logo = Table(
            [[logo_content]],
            colWidths=[logo_box],
            rowHeights=[logo_box],
            style=[
                ("BOX", (0,0), (-1,-1), 0.35, border),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("ALIGN", (0,0), (-1,-1), "CENTER"),
                ("LEFTPADDING", (0,0), (-1,-1), 0),
                ("RIGHTPADDING", (0,0), (-1,-1), 0),
                ("TOPPADDING", (0,0), (-1,-1), 0),
                ("BOTTOMPADDING", (0,0), (-1,-1), 0),
            ],
        )
        company = Paragraph(f"<b>{esc(invoice.company.company_name)}</b><br/><font size='8'>GSTIN: {esc(invoice.company.gstin)}<br/>{esc(company_address())}<br/>Phone: {esc(invoice.company.phone)} &nbsp; Email: {esc(invoice.company.email)}</font>", styles["Company"])
        badge = Table([[Paragraph("TAX INVOICE", styles["Badge"])]], colWidths=[38*mm], rowHeights=[12*mm], style=[("BACKGROUND", (0,0), (-1,-1), blue), ("VALIGN", (0,0), (-1,-1), "MIDDLE")])
        header = Table([[logo, company, badge]], colWidths=[36*mm, 104*mm, 42*mm])
        header.setStyle(TableStyle([("BOX", (0,0), (-1,-1), 0.8, border), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
        story += [header, Spacer(1, 4*mm)]

        meta_rows = [["Invoice Number", invoice.invoice_number, "Invoice Date", invoice.invoice_date.strftime("%d-%m-%Y")], ["Due Date", invoice.due_date.strftime("%d-%m-%Y"), "Place of Supply", invoice.place_of_supply or invoice.company.state], ["Supply State Code", invoice.state_code, "Tax Type", "CGST + SGST" if invoice.is_intrastate else "IGST"]]
        meta = Table(meta_rows, colWidths=[35*mm, 56*mm, 35*mm, 56*mm], style=[("GRID", (0,0), (-1,-1), 0.45, border), ("BACKGROUND", (0,0), (0,-1), light), ("BACKGROUND", (2,0), (2,-1), light), ("FONTNAME", (0,0), (-1,-1), font), ("FONTNAME", (0,0), (0,-1), bold), ("FONTNAME", (2,0), (2,-1), bold), ("FONTSIZE", (0,0), (-1,-1), 8)])
        story += [meta, Spacer(1, 4*mm)]
        customer_address = ", ".join([p for p in [invoice.customer.address, invoice.customer.city, invoice.customer.state, invoice.customer.pin_code] if p])
        bill = f"<b>Bill To</b><br/>{esc(invoice.customer.customer_name)}<br/>GSTIN: {esc(invoice.customer.gstin or 'Unregistered')}<br/>{esc(customer_address)}<br/>Phone: {esc(invoice.customer.phone)}<br/>Email: {esc(invoice.customer.email)}"
        story += [Table([[Paragraph(bill, styles["Small"])]], colWidths=[182*mm], style=[("GRID", (0,0), (-1,-1), 0.45, border), ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F8FAFC")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 8), ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7)]), Spacer(1, 4*mm)]

        data = [["Sr No", "Description", "HSN/SAC", "Qty", "Unit Price", "GST %", "Amount"]]
        for idx, item in enumerate(invoice.items, 1):
            data.append([str(idx), Paragraph(esc(item.item_name), styles["Cell"]), Paragraph(esc(item.hsn_sac or "-"), styles["CellCenter"]), Paragraph(f"{item.quantity:g}", styles["CellCenter"]), Paragraph(money(item.unit_price), styles["CellCenter"]), Paragraph(f"{item.gst_percentage:g}%", styles["CellCenter"]), Paragraph(money(item.total_amount), styles["CellCenter"])])
        items = Table(data, repeatRows=1, colWidths=[10*mm, 68*mm, 22*mm, 15*mm, 28*mm, 18*mm, 21*mm])
        items.setStyle(TableStyle([("GRID", (0,0), (-1,-1), 0.4, border), ("BACKGROUND", (0,0), (-1,0), blue), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), bold), ("FONTNAME", (0,1), (-1,-1), font), ("FONTSIZE", (0,0), (-1,-1), 7.5), ("ALIGN", (0,0), (0,-1), "CENTER"), ("ALIGN", (2,1), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4), ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFCFF")])]))
        story += [items, Spacer(1, 4*mm)]

        summary_rows = [["Taxable Amount", money(invoice.taxable_amount)]]
        if invoice.is_intrastate:
            rate = max((i.gst_percentage for i in invoice.items), default=0) / 2
            summary_rows += [[f"CGST ({rate:g}%)", money(invoice.cgst)], [f"SGST ({rate:g}%)", money(invoice.sgst)], ["IGST (0%)", money(0)]]
        else:
            rate = max((i.gst_percentage for i in invoice.items), default=0)
            summary_rows += [["CGST (0%)", money(0)], ["SGST (0%)", money(0)], [f"IGST ({rate:g}%)", money(invoice.igst)]]
        summary_rows += [["Round Off", money(invoice.round_off)], ["Grand Total", money(invoice.grand_total)]]
        summary = Table(summary_rows, colWidths=[44*mm, 38*mm], style=[("GRID", (0,0), (-1,-1), 0.45, border), ("ALIGN", (1,0), (1,-1), "RIGHT"), ("FONTNAME", (0,0), (-1,-1), font), ("FONTNAME", (0,0), (0,-1), bold), ("BACKGROUND", (0,-1), (-1,-1), accent), ("TEXTCOLOR", (0,-1), (-1,-1), colors.white), ("FONTNAME", (0,-1), (-1,-1), bold), ("FONTSIZE", (0,0), (-1,-1), 8.5)])
        words = Paragraph(f"<b>Amount in Words:</b><br/>{esc(amount_to_words(invoice.grand_total))}", styles["Small"])
        story += [Table([[words, summary]], colWidths=[98*mm, 84*mm], style=[("VALIGN", (0,0), (-1,-1), "TOP")]), Spacer(1, 4*mm)]

        bank = Paragraph(f"<b>Bank Details</b><br/>Bank Name: {esc(invoice.company.bank_name)}<br/>Account Number: {esc(invoice.company.account_number)}<br/>IFSC: {esc(invoice.company.ifsc)}<br/>UPI ID: {esc(invoice.company.upi_id)}", styles["Small"])
        qr_cell = ""
        qr_path = image_path(getattr(invoice.company, "upi_qr_image_url", ""))
        if qr_path and qr_path.exists():
            try:
                qr_cell = [Image(str(qr_path), width=27*mm, height=27*mm, kind="proportional"), Paragraph("<b>Scan &amp; Pay via UPI</b>", styles["Tiny"])]
            except Exception:
                logger.warning("Skipping invalid UPI QR image", exc_info=True, extra={"company_id": invoice.company_id})
        terms_text = esc(getattr(invoice, "terms", "") or "1. Payment is due on or before the due date.\n2. Goods/services once sold will not be taken back unless agreed in writing.\n3. Subject to local jurisdiction.")
        terms = Paragraph(f"<b>Terms &amp; Conditions</b><br/>{terms_text}", styles["Small"])
        story += [Table([[bank, qr_cell, terms]], colWidths=[67*mm, 38*mm, 77*mm], style=[("GRID", (0,0), (-1,-1), 0.45, border), ("VALIGN", (0,0), (-1,-1), "TOP"), ("ALIGN", (1,0), (1,0), "CENTER"), ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F8FAFC")), ("LEFTPADDING", (0,0), (-1,-1), 7), ("RIGHTPADDING", (0,0), (-1,-1), 7), ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7)]), Spacer(1, 5*mm)]

        signature_parts = []
        signature_path = image_path(getattr(invoice.company, "signature_image_path", ""))
        if signature_path and signature_path.exists():
            try:
                signature_parts.append(Table([[fitted_image(signature_path, 42*mm, 14*mm)]], colWidths=[56*mm], style=[("ALIGN", (0,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 0), ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 0)]))
            except Exception:
                logger.warning("Skipping invalid signature image", exc_info=True, extra={"company_id": invoice.company_id})
        if getattr(invoice.company, "authorized_signature_name", ""):
            signature_parts.append(Paragraph(f"<b>{esc(invoice.company.authorized_signature_name)}</b>", styles["SmallCenter"]))
        signature_parts.append(Paragraph("<b>Authorized Signature</b>", styles["SmallCenter"]))
        sig = Table([["Customer Signature", "Company Seal", signature_parts]], colWidths=[60*mm, 52*mm, 70*mm], rowHeights=[28*mm], style=[("GRID", (0,0), (-1,-1), 0.45, border), ("VALIGN", (0,0), (-1,-1), "BOTTOM"), ("ALIGN", (0,0), (-1,-1), "CENTER"), ("FONTNAME", (0,0), (1,0), bold), ("FONTSIZE", (0,0), (-1,-1), 8), ("TOPPADDING", (2,0), (2,0), 4), ("BOTTOMPADDING", (2,0), (2,0), 4)])
        story.append(KeepTogether(sig))
        def page_footer(canvas: Canvas, _doc):
            canvas.saveState(); canvas.setFont(font, 8); canvas.setFillColor(colors.HexColor("#64748B")); canvas.drawString(12*mm, 8*mm, f"Smart GST · {invoice.company.company_name} · {invoice.invoice_number}"); canvas.drawRightString(198*mm, 8*mm, f"Page {canvas.getPageNumber()}"); canvas.restoreState()
        doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)

    def _generate_minimal_pdf(self, invoice: Invoice, path: Path) -> None:
        lines = ["TAX INVOICE", f"Invoice: {invoice.invoice_number}  Date: {invoice.invoice_date:%d-%m-%Y}", f"Seller: {invoice.company.seller_name} GSTIN: {invoice.company.gstin}", f"Buyer: {invoice.customer.customer_name} GSTIN: {invoice.customer.gstin or 'Unregistered'}", "Items:"]
        for item in invoice.items:
            lines.append(f"{item.item_name} HSN:{item.hsn_sac or '-'} Qty:{item.quantity:g} Total:{item.total_amount:.2f}")
        lines += [f"Taxable: INR {invoice.taxable_amount:.2f}", f"CGST: INR {invoice.cgst:.2f} SGST: INR {invoice.sgst:.2f} IGST: INR {invoice.igst:.2f}", f"Grand Total: INR {invoice.grand_total:.2f}", amount_to_words(invoice.grand_total), "Terms and Conditions apply.", getattr(invoice.company, "authorized_signature_name", "") or "", "Authorized Signature"]
        content = "BT /F1 10 Tf 50 800 Td " + " T* ".join(f"({line.replace('(', '[').replace(')', ']')})" for line in lines) + " ET"
        objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", f"<< /Length {len(content.encode())} >>\nstream\n{content}\nendstream"]
        pdf = "%PDF-1.4\n"; offsets = []
        for i, obj in enumerate(objects, 1): offsets.append(len(pdf.encode())); pdf += f"{i} 0 obj\n{obj}\nendobj\n"
        xref = len(pdf.encode()); pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets) + f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
        path.write_bytes(pdf.encode())
