CREATE TABLE IF NOT EXISTS company (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_name TEXT NOT NULL,
    gstin TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    state_code TEXT,
    logo_path TEXT
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    gstin TEXT,
    address TEXT NOT NULL,
    phone TEXT,
    state_code TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE,
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    place_of_supply TEXT NOT NULL,
    state_code TEXT NOT NULL,
    company_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    taxable_amount REAL NOT NULL,
    cgst REAL NOT NULL,
    sgst REAL NOT NULL,
    igst REAL NOT NULL,
    grand_total REAL NOT NULL,
    pdf_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(company_id) REFERENCES company(id),
    FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    hsn_sac TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    gst_percentage REAL NOT NULL,
    taxable_value REAL NOT NULL,
    gst_amount REAL NOT NULL,
    total_amount REAL NOT NULL,
    FOREIGN KEY(invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);
