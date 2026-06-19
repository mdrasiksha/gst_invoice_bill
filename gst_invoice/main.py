"""Tkinter desktop UI for GST Smart."""
from __future__ import annotations

import shutil
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .database import Database
from .invoice_generator import calculate_invoice
from .models import Company, Customer, Invoice, InvoiceItem
from .pdf_generator import PDFGenerator
from .utils import parse_date, state_code_from_gstin, validate_email, validate_gstin, validate_phone


class GSTInvoiceApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GST Smart")
        self.geometry("1180x760")
        self.minsize(1000, 650)
        self.db = Database()
        self.pdf = PDFGenerator()
        self.items: list[InvoiceItem] = []
        self._build_ui()
        self.load_company()
        self.refresh_invoices()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        tabs = ttk.Notebook(self); tabs.grid(row=0, column=0, sticky="nsew")
        self.create_tab = ttk.Frame(tabs, padding=10); self.history_tab = ttk.Frame(tabs, padding=10)
        tabs.add(self.create_tab, text="Create New Invoice"); tabs.add(self.history_tab, text="View Previous Invoices")
        self._build_create_tab(); self._build_history_tab()

    def _entry(self, parent, label, row, col, width=28, value=""):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=3)
        var = tk.StringVar(value=value)
        ent = ttk.Entry(parent, textvariable=var, width=width)
        ent.grid(row=row, column=col+1, sticky="ew", padx=4, pady=3)
        return var

    def _build_create_tab(self) -> None:
        self.create_tab.columnconfigure(0, weight=1)
        top = ttk.Frame(self.create_tab); top.grid(row=0, column=0, sticky="ew")
        for i in range(6): top.columnconfigure(i, weight=1)
        company = ttk.LabelFrame(top, text="Company Details", padding=8); company.grid(row=0, column=0, columnspan=3, sticky="ew", padx=5)
        customer = ttk.LabelFrame(top, text="Customer Details", padding=8); customer.grid(row=0, column=3, columnspan=3, sticky="ew", padx=5)
        self.company_name = self._entry(company, "Seller Name", 0, 0)
        self.company_gstin = self._entry(company, "GSTIN", 1, 0)
        self.company_address = self._entry(company, "Address", 2, 0)
        self.company_phone = self._entry(company, "Phone", 3, 0)
        self.company_email = self._entry(company, "Email", 4, 0)
        self.company_logo = self._entry(company, "Logo Path", 5, 0)
        ttk.Button(company, text="Browse", command=self.pick_logo).grid(row=5, column=2, padx=4)
        self.customer_name = self._entry(customer, "Customer Name", 0, 0)
        self.customer_gstin = self._entry(customer, "GSTIN (optional)", 1, 0)
        self.customer_address = self._entry(customer, "Address", 2, 0)
        self.customer_phone = self._entry(customer, "Phone", 3, 0)
        self.customer_state = self._entry(customer, "State Code", 4, 0)

        inv = ttk.LabelFrame(self.create_tab, text="Invoice Details", padding=8); inv.grid(row=1, column=0, sticky="ew", pady=8)
        for i in range(8): inv.columnconfigure(i, weight=1)
        self.invoice_number = self._entry(inv, "Invoice No", 0, 0, value="")
        self.invoice_date = self._entry(inv, "Invoice Date (YYYY-MM-DD)", 0, 2, value=date.today().isoformat())
        self.due_date = self._entry(inv, "Due Date", 0, 4, value=(date.today()+timedelta(days=15)).isoformat())
        self.place_supply = self._entry(inv, "Place of Supply", 1, 0, value="Karnataka")
        self.supply_state = self._entry(inv, "State Code", 1, 2, value="29")
        ttk.Button(inv, text="New Number", command=self.set_next_invoice_number).grid(row=1, column=4, padx=4)

        item = ttk.LabelFrame(self.create_tab, text="Product / Service Item", padding=8); item.grid(row=2, column=0, sticky="ew")
        for i in range(12): item.columnconfigure(i, weight=1)
        self.item_name = self._entry(item, "Item Name", 0, 0, 18)
        self.hsn = self._entry(item, "HSN/SAC", 0, 2, 12)
        self.qty = self._entry(item, "Qty", 0, 4, 8, "1")
        self.rate = self._entry(item, "Unit Price", 0, 6, 10, "0")
        self.gst = self._entry(item, "GST %", 0, 8, 8, "18")
        ttk.Button(item, text="Add Item", command=self.add_item).grid(row=0, column=10, padx=4)
        ttk.Button(item, text="Remove Selected", command=self.remove_item).grid(row=0, column=11, padx=4)

        columns = ("item", "hsn", "qty", "rate", "gst", "taxable", "gst_amt", "total")
        self.item_tree = ttk.Treeview(self.create_tab, columns=columns, show="headings", height=9)
        for col, text in zip(columns, ["Item", "HSN/SAC", "Qty", "Rate", "GST %", "Taxable", "GST Amount", "Total"]):
            self.item_tree.heading(col, text=text); self.item_tree.column(col, anchor="e" if col not in ("item", "hsn") else "w")
        self.item_tree.grid(row=3, column=0, sticky="nsew", pady=8); self.create_tab.rowconfigure(3, weight=1)
        bottom = ttk.Frame(self.create_tab); bottom.grid(row=4, column=0, sticky="ew")
        self.total_label = ttk.Label(bottom, text="Taxable: 0.00 | CGST: 0.00 | SGST: 0.00 | IGST: 0.00 | Grand Total: 0.00", font=("TkDefaultFont", 11, "bold"))
        self.total_label.pack(side="left")
        ttk.Button(bottom, text="Save & Generate PDF", command=self.save_invoice).pack(side="right")
        self.set_next_invoice_number()

    def _build_history_tab(self) -> None:
        self.history_tab.columnconfigure(0, weight=1); self.history_tab.rowconfigure(1, weight=1)
        search = ttk.Frame(self.history_tab); search.grid(row=0, column=0, sticky="ew")
        self.search_var = tk.StringVar(); ttk.Entry(search, textvariable=self.search_var, width=35).pack(side="left", padx=4)
        ttk.Button(search, text="Search Invoice by Number", command=self.refresh_invoices).pack(side="left")
        ttk.Button(search, text="Export Invoice PDF", command=self.export_selected).pack(side="right", padx=4)
        ttk.Button(search, text="Delete Invoice", command=self.delete_selected).pack(side="right", padx=4)
        self.invoice_tree = ttk.Treeview(self.history_tab, columns=("no", "date", "customer", "total", "pdf"), show="headings")
        for c, t in zip(("no", "date", "customer", "total", "pdf"), ("Invoice No", "Date", "Customer", "Grand Total", "PDF Path")):
            self.invoice_tree.heading(c, text=t)
        self.invoice_tree.grid(row=1, column=0, sticky="nsew", pady=8)

    def load_company(self):
        c = self.db.get_company(); self.company_name.set(c.seller_name); self.company_gstin.set(c.gstin); self.company_address.set(c.address); self.company_phone.set(c.phone); self.company_email.set(c.email); self.company_logo.set(c.logo_path)

    def pick_logo(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg")])
        if path: self.company_logo.set(path)

    def set_next_invoice_number(self): self.invoice_number.set(self.db.next_invoice_number())

    def add_item(self):
        try:
            item = InvoiceItem(self.item_name.get().strip(), self.hsn.get().strip(), float(self.qty.get()), float(self.rate.get()), float(self.gst.get()))
            if not item.item_name or not item.hsn_sac: raise ValueError("Item name and HSN/SAC are required.")
            item.calculate(); self.items.append(item); self.refresh_item_tree()
        except Exception as exc: messagebox.showerror("Invalid item", str(exc))

    def remove_item(self):
        sel = self.item_tree.selection()
        if sel:
            del self.items[self.item_tree.index(sel[0])]; self.refresh_item_tree()

    def refresh_item_tree(self):
        self.item_tree.delete(*self.item_tree.get_children())
        dummy = self._build_invoice(validate=False); calculate_invoice(dummy)
        for it in self.items:
            self.item_tree.insert("", "end", values=(it.item_name, it.hsn_sac, f"{it.quantity:g}", f"{it.unit_price:.2f}", f"{it.gst_percentage:.2f}", f"{it.taxable_value:.2f}", f"{it.gst_amount:.2f}", f"{it.total_amount:.2f}"))
        self.total_label.config(text=f"Taxable: {dummy.taxable_amount:.2f} | CGST: {dummy.cgst:.2f} | SGST: {dummy.sgst:.2f} | IGST: {dummy.igst:.2f} | Grand Total: {dummy.grand_total:.2f}")

    def _build_invoice(self, validate=True) -> Invoice:
        company = Company(self.company_name.get().strip(), self.company_gstin.get().strip().upper(), self.company_address.get().strip(), self.company_phone.get().strip(), self.company_email.get().strip(), state_code_from_gstin(self.company_gstin.get().strip().upper()) or "29", self.company_logo.get().strip(), id=self.db.get_company().id)
        cust_gstin = self.customer_gstin.get().strip().upper(); state_code = self.supply_state.get().strip() or state_code_from_gstin(cust_gstin)
        customer = Customer(self.customer_name.get().strip(), cust_gstin, self.customer_address.get().strip(), self.customer_phone.get().strip(), self.customer_state.get().strip() or state_code)
        if validate:
            if not company.seller_name or not company.address or not customer.customer_name or not customer.address: raise ValueError("Seller, customer and address fields are required.")
            if not validate_gstin(company.gstin): raise ValueError("Seller GSTIN is invalid.")
            if not validate_gstin(cust_gstin, optional=True): raise ValueError("Customer GSTIN is invalid.")
            if not validate_phone(company.phone) or not validate_phone(customer.phone): raise ValueError("Phone number is invalid.")
            if not validate_email(company.email): raise ValueError("Email is invalid.")
            if not self.items: raise ValueError("Add at least one item.")
        return Invoice(self.invoice_number.get().strip(), parse_date(self.invoice_date.get()) if validate else date.today(), parse_date(self.due_date.get()) if validate else date.today(), self.place_supply.get().strip() or "Karnataka", state_code or "29", company, customer, list(self.items))

    def save_invoice(self):
        try:
            invoice = calculate_invoice(self._build_invoice())
            self.db.save_company(invoice.company); invoice.company = self.db.get_company()
            invoice.pdf_path = self.pdf.generate(invoice)
            self.db.save_invoice(invoice)
            messagebox.showinfo("Success", f"Invoice saved and PDF generated:\n{invoice.pdf_path}")
            self.items.clear(); self.refresh_item_tree(); self.set_next_invoice_number(); self.refresh_invoices()
        except Exception as exc: messagebox.showerror("Unable to save invoice", str(exc))

    def refresh_invoices(self):
        self.invoice_tree.delete(*self.invoice_tree.get_children())
        for row in self.db.list_invoices(self.search_var.get().strip() if hasattr(self, 'search_var') else ""):
            self.invoice_tree.insert("", "end", values=(row["invoice_number"], row["invoice_date"], row["customer_name"], f"{row['grand_total']:.2f}", row["pdf_path"]))

    def selected_invoice_no(self):
        sel = self.invoice_tree.selection()
        return self.invoice_tree.item(sel[0], "values")[0] if sel else None

    def export_selected(self):
        no = self.selected_invoice_no()
        if not no: return messagebox.showwarning("Select invoice", "Select an invoice first.")
        inv = self.db.get_invoice(no); path = self.pdf.generate(inv)
        target = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=f"{no}.pdf")
        if target: shutil.copy(path, target); messagebox.showinfo("Exported", target)

    def delete_selected(self):
        no = self.selected_invoice_no()
        if no and messagebox.askyesno("Confirm", f"Delete invoice {no}?"):
            self.db.delete_invoice(no); self.refresh_invoices()


def main() -> None:
    GSTInvoiceApp().mainloop()


if __name__ == "__main__":
    main()
