"""Professional PDF invoice generation using ReportLab with a tiny fallback writer."""
from __future__ import annotations

from pathlib import Path

from .models import Invoice
from .utils import amount_to_words

BASE_DIR = Path(__file__).resolve().parent
INVOICE_DIR = BASE_DIR / "invoices"


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
        return str(path)

    def _generate_reportlab(self, invoice: Invoice, path: Path) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=14*mm, leftMargin=14*mm, topMargin=12*mm, bottomMargin=12*mm)
        story = []
        header_cells = []
        logo_path = BASE_DIR / invoice.company.logo_path if invoice.company.logo_path else None
        if logo_path and logo_path.exists():
            header_cells.append(Image(str(logo_path), width=28*mm, height=20*mm))
        else:
            header_cells.append(Paragraph("<b>GST Invoice Generator</b>", styles["Normal"]))
        header_cells.append(Paragraph("<b>TAX INVOICE</b><br/>Original for Recipient", styles["Title"]))
        header = Table([header_cells], colWidths=[55*mm, 125*mm])
        header.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story += [header, Spacer(1, 5*mm)]
        seller = f"<b>Seller</b><br/>{invoice.company.seller_name}<br/>GSTIN: {invoice.company.gstin}<br/>{invoice.company.address}<br/>Phone: {invoice.company.phone}<br/>Email: {invoice.company.email}"
        buyer = f"<b>Buyer</b><br/>{invoice.customer.customer_name}<br/>GSTIN: {invoice.customer.gstin or 'Unregistered'}<br/>{invoice.customer.address}<br/>Phone: {invoice.customer.phone}"
        meta = f"<b>Invoice No:</b> {invoice.invoice_number}<br/><b>Date:</b> {invoice.invoice_date:%d-%m-%Y}<br/><b>Due Date:</b> {invoice.due_date:%d-%m-%Y}<br/><b>Place of Supply:</b> {invoice.place_of_supply}<br/><b>State Code:</b> {invoice.state_code}"
        details = Table([[Paragraph(seller, styles["BodyText"]), Paragraph(buyer, styles["BodyText"]), Paragraph(meta, styles["BodyText"])]], colWidths=[60*mm, 60*mm, 60*mm])
        details.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [details, Spacer(1, 5*mm)]
        data = [["#", "Item", "HSN/SAC", "Qty", "Rate", "GST %", "Taxable", "GST", "Total"]]
        for idx, item in enumerate(invoice.items, 1):
            data.append([idx, item.item_name, item.hsn_sac, f"{item.quantity:g}", f"{item.unit_price:.2f}", f"{item.gst_percentage:.2f}", f"{item.taxable_value:.2f}", f"{item.gst_amount:.2f}", f"{item.total_amount:.2f}"])
        table = Table(data, repeatRows=1, colWidths=[8*mm, 39*mm, 20*mm, 14*mm, 20*mm, 16*mm, 22*mm, 18*mm, 23*mm])
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("ALIGN", (3, 1), (-1, -1), "RIGHT")]))
        story += [table, Spacer(1, 5*mm)]
        summary = Table([["Taxable Amount", f"INR {invoice.taxable_amount:.2f}"], ["CGST", f"INR {invoice.cgst:.2f}"], ["SGST", f"INR {invoice.sgst:.2f}"], ["IGST", f"INR {invoice.igst:.2f}"], ["Grand Total", f"INR {invoice.grand_total:.2f}"]], colWidths=[120*mm, 60*mm])
        summary.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("BACKGROUND", (0, -1), (-1, -1), colors.lightgrey), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]))
        story += [summary, Spacer(1, 4*mm), Paragraph(f"<b>Amount in words:</b> {amount_to_words(invoice.grand_total)}", styles["Normal"]), Spacer(1, 8*mm)]
        footer = Table([[Paragraph("<b>Terms and Conditions</b><br/>1. Goods/services once sold will not be taken back unless agreed in writing.<br/>2. Payment is due on or before the due date.<br/>3. Subject to local jurisdiction.", styles["BodyText"]), Paragraph("For " + invoice.company.seller_name + "<br/><br/><br/><b>Authorized Signatory</b>", styles["BodyText"])]], colWidths=[115*mm, 65*mm])
        footer.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(footer)
        doc.build(story)

    def _generate_minimal_pdf(self, invoice: Invoice, path: Path) -> None:
        lines = ["TAX INVOICE", f"Invoice: {invoice.invoice_number}  Date: {invoice.invoice_date:%d-%m-%Y}", f"Seller: {invoice.company.seller_name} GSTIN: {invoice.company.gstin}", f"Buyer: {invoice.customer.customer_name} GSTIN: {invoice.customer.gstin or 'Unregistered'}", "Items:"]
        for item in invoice.items:
            lines.append(f"{item.item_name} HSN:{item.hsn_sac} Qty:{item.quantity:g} Taxable:{item.taxable_value:.2f} GST:{item.gst_amount:.2f} Total:{item.total_amount:.2f}")
        lines += [f"Taxable: INR {invoice.taxable_amount:.2f}", f"CGST: INR {invoice.cgst:.2f} SGST: INR {invoice.sgst:.2f} IGST: INR {invoice.igst:.2f}", f"Grand Total: INR {invoice.grand_total:.2f}", amount_to_words(invoice.grand_total), "Terms and Conditions apply.", "Authorized Signatory"]
        content = "BT /F1 10 Tf 50 800 Td " + " T* ".join(f"({line.replace('(', '[').replace(')', ']')})" for line in lines) + " ET"
        objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", f"<< /Length {len(content.encode())} >>\nstream\n{content}\nendstream"]
        pdf = "%PDF-1.4\n"; offsets = []
        for i, obj in enumerate(objects, 1):
            offsets.append(len(pdf.encode())); pdf += f"{i} 0 obj\n{obj}\nendobj\n"
        xref = len(pdf.encode()); pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets) + f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
        path.write_bytes(pdf.encode())
