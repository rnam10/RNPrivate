#!/usr/bin/env python3
"""
Business Acquisition Database
ETA (Entrepreneurship Through Acquisition) deal tracker.

Usage:
  python acquisition_db.py <command> [options]

Commands:
  init                    Initialize the database
  summary                 Pipeline summary across all deals
  list                    List businesses (filter by type/stage)
  show <id>               Show full detail for a business
  add-business            Add a new business (listing or prospect)
  update-stage <id>       Update pipeline stage for a business
  add-financial <id>      Add/update financials for a business
  add-contact             Add a contact (broker, owner, etc.)
  add-source              Add a deal source
  link-contact <biz_id> <contact_id>   Link a contact to a business
  link-source  <biz_id> <source_id> [url]  Link a source to a business
  log-interaction <biz_id>  Log a call, email, or meeting
  list-contacts           List all contacts
  list-sources            List all sources
"""

import sqlite3
import argparse
import os
import sys
from datetime import date, datetime
from textwrap import wrap

DB_PATH = os.path.join(os.path.dirname(__file__), "acquisition.db")

# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------
LISTING_STAGES = [
    "initial_review",
    "nda_requested",
    "nda_signed",
    "financials_review",
    "management_meeting",
    "loi_submitted",
    "loi_accepted",
    "due_diligence",
    "closed_won",
    "closed_lost",
    "passed",
]

PROSPECT_STAGES = [
    "identified",
    "researching",
    "outreach_planned",
    "outreach_sent",
    "engaged",
    "converted_to_listing",
    "passed",
]

ALL_STAGES = sorted(set(LISTING_STAGES + PROSPECT_STAGES))

BUSINESS_TYPES = ["listing", "prospect"]
CONTACT_ROLES = ["broker", "owner", "advisor", "lender", "other"]
SOURCE_TYPES = ["marketplace", "broker", "direct", "referral", "other"]
INTERACTION_TYPES = ["call", "email", "meeting", "nda", "loi", "note", "other"]


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    type        TEXT CHECK(type IN ('marketplace','broker','direct','referral','other')),
    website     TEXT,
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT,
    phone       TEXT,
    role        TEXT CHECK(role IN ('broker','owner','advisor','lender','other')),
    company     TEXT,
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS businesses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    type                TEXT NOT NULL CHECK(type IN ('listing','prospect')),
    stage               TEXT NOT NULL DEFAULT 'initial_review',
    city                TEXT,
    state               TEXT,
    industry            TEXT,
    naics_code          TEXT,
    employee_count      INTEGER,
    year_founded        INTEGER,
    website             TEXT,
    description         TEXT,
    reason_for_sale     TEXT,
    notes               TEXT,
    date_found          DATE DEFAULT (date('now')),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    fiscal_year     INTEGER,
    revenue         REAL,
    ebitda          REAL,
    sde             REAL,
    asking_price    REAL,
    ebitda_multiple REAL,
    sde_multiple    REAL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(business_id, fiscal_year)
);

CREATE TABLE IF NOT EXISTS business_contacts (
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    contact_id  INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
    PRIMARY KEY (business_id, contact_id)
);

CREATE TABLE IF NOT EXISTS business_sources (
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    source_id   INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    listing_url TEXT,
    PRIMARY KEY (business_id, source_id)
);

CREATE TABLE IF NOT EXISTS pipeline_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    from_stage  TEXT,
    to_stage    TEXT NOT NULL,
    event_date  DATE DEFAULT (date('now')),
    notes       TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS interactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id      INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    contact_id       INTEGER REFERENCES contacts(id),
    interaction_type TEXT CHECK(interaction_type IN ('call','email','meeting','nda','loi','note','other')),
    interaction_date DATE DEFAULT (date('now')),
    summary          TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS businesses_updated
AFTER UPDATE ON businesses
BEGIN
    UPDATE businesses SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""

SEED_SOURCES = [
    ("BizBuySell",      "marketplace", "https://www.bizbuysell.com",       None),
    ("BizQuest",        "marketplace", "https://www.bizquest.com",          None),
    ("DealStream",      "marketplace", "https://www.dealstream.com",        None),
    ("Axial",           "marketplace", "https://www.axial.net",             None),
    ("Quiet Light",     "broker",      "https://quietlight.com",            None),
    ("Website Closers","broker",       "https://www.websiteclosers.com",    None),
    ("Direct Outreach", "direct",      None,                                "Cold outreach to business owners"),
    ("Referral",        "referral",    None,                                "Warm referral from network"),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    cur = conn.cursor()
    for name, stype, website, notes in SEED_SOURCES:
        cur.execute(
            "INSERT OR IGNORE INTO sources (name, type, website, notes) VALUES (?,?,?,?)",
            (name, stype, website, notes),
        )
    conn.commit()
    conn.close()
    print(f"Database initialized: {DB_PATH}")
    print(f"Seeded {len(SEED_SOURCES)} default sources.")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_money(val):
    if val is None:
        return "—"
    if val >= 1_000_000:
        return f"${val/1_000_000:.2f}M"
    if val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:,.0f}"


def fmt_multiple(val):
    return f"{val:.1f}x" if val is not None else "—"


def col_width(rows, header, key, min_w=None):
    vals = [str(r[key] or "") for r in rows] + [header]
    w = max(len(v) for v in vals)
    return max(w, min_w or 0)


def print_table(headers, rows, keys):
    widths = [max(len(h), max((len(str(r.get(k) or "")) for r in rows), default=0))
              for h, k in zip(headers, keys)]
    sep = "  ".join("-" * w for w in widths)
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(sep)
    for r in rows:
        print(fmt.format(*[str(r.get(k) or "") for k in keys]))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_summary(args, conn):
    print("\n=== PIPELINE SUMMARY ===\n")

    # Active listings
    print("-- LISTINGS --")
    rows = conn.execute("""
        SELECT stage, COUNT(*) as cnt FROM businesses
        WHERE type='listing' GROUP BY stage ORDER BY stage
    """).fetchall()
    if rows:
        for r in rows:
            print(f"  {r['stage']:<25} {r['cnt']}")
    else:
        print("  (none)")

    print()
    print("-- PROSPECTS --")
    rows = conn.execute("""
        SELECT stage, COUNT(*) as cnt FROM businesses
        WHERE type='prospect' GROUP BY stage ORDER BY stage
    """).fetchall()
    if rows:
        for r in rows:
            print(f"  {r['stage']:<25} {r['cnt']}")
    else:
        print("  (none)")

    print()
    print("-- FINANCIALS OVERVIEW (Listings with data) --")
    rows = conn.execute("""
        SELECT b.name, b.stage, f.fiscal_year, f.revenue, f.ebitda, f.sde,
               f.asking_price, f.ebitda_multiple, f.sde_multiple
        FROM businesses b
        JOIN financials f ON f.business_id = b.id
        WHERE b.type='listing'
        ORDER BY f.asking_price DESC NULLS LAST
    """).fetchall()
    if rows:
        headers = ["Business", "Stage", "Year", "Revenue", "EBITDA", "SDE", "Ask Price", "EBITDA Mx", "SDE Mx"]
        data = [{
            "Business": r["name"],
            "Stage": r["stage"],
            "Year": str(r["fiscal_year"] or ""),
            "Revenue": fmt_money(r["revenue"]),
            "EBITDA": fmt_money(r["ebitda"]),
            "SDE": fmt_money(r["sde"]),
            "Ask Price": fmt_money(r["asking_price"]),
            "EBITDA Mx": fmt_multiple(r["ebitda_multiple"]),
            "SDE Mx": fmt_multiple(r["sde_multiple"]),
        } for r in rows]
        print_table(headers, data, headers)
    else:
        print("  (no financial data yet)")
    print()


def cmd_list(args, conn):
    q = "SELECT id, name, type, stage, city, state, industry, employee_count FROM businesses WHERE 1=1"
    params = []
    if args.type:
        q += " AND type=?"
        params.append(args.type)
    if args.stage:
        q += " AND stage=?"
        params.append(args.stage)
    if args.state:
        q += " AND state=?"
        params.append(args.state.upper())
    q += " ORDER BY updated_at DESC"

    rows = conn.execute(q, params).fetchall()
    if not rows:
        print("No businesses found.")
        return

    headers = ["ID", "Name", "Type", "Stage", "City", "State", "Industry", "Employees"]
    data = [{
        "ID": str(r["id"]),
        "Name": r["name"],
        "Type": r["type"],
        "Stage": r["stage"],
        "City": r["city"] or "",
        "State": r["state"] or "",
        "Industry": (r["industry"] or "")[:30],
        "Employees": str(r["employee_count"]) if r["employee_count"] else "",
    } for r in rows]
    print_table(headers, data, headers)
    print(f"\n{len(rows)} record(s)")


def cmd_show(args, conn):
    b = conn.execute("SELECT * FROM businesses WHERE id=?", (args.id,)).fetchone()
    if not b:
        print(f"No business with id {args.id}")
        return

    print(f"\n{'='*60}")
    print(f"  [{b['id']}] {b['name']}")
    print(f"{'='*60}")
    print(f"  Type         : {b['type']}")
    print(f"  Stage        : {b['stage']}")
    print(f"  Location     : {b['city'] or ''}, {b['state'] or ''}".rstrip(", "))
    print(f"  Industry     : {b['industry'] or '—'}")
    print(f"  NAICS Code   : {b['naics_code'] or '—'}")
    print(f"  Employees    : {b['employee_count'] or '—'}")
    print(f"  Year Founded : {b['year_founded'] or '—'}")
    print(f"  Website      : {b['website'] or '—'}")
    print(f"  Date Found   : {b['date_found'] or '—'}")
    if b["reason_for_sale"]:
        print(f"  Reason/Sale  : {b['reason_for_sale']}")
    if b["description"]:
        for line in wrap(b["description"], 55):
            print(f"  Description  : {line}")
    if b["notes"]:
        for line in wrap(b["notes"], 55):
            print(f"  Notes        : {line}")

    # Financials
    fins = conn.execute(
        "SELECT * FROM financials WHERE business_id=? ORDER BY fiscal_year DESC", (args.id,)
    ).fetchall()
    if fins:
        print(f"\n  FINANCIALS")
        for f in fins:
            print(f"    FY{f['fiscal_year'] or '?'}  Revenue:{fmt_money(f['revenue'])}  "
                  f"EBITDA:{fmt_money(f['ebitda'])}  SDE:{fmt_money(f['sde'])}  "
                  f"Ask:{fmt_money(f['asking_price'])}  "
                  f"EBITDA Mx:{fmt_multiple(f['ebitda_multiple'])}  SDE Mx:{fmt_multiple(f['sde_multiple'])}")

    # Sources
    sources = conn.execute("""
        SELECT s.name, s.type, bs.listing_url
        FROM business_sources bs JOIN sources s ON s.id=bs.source_id
        WHERE bs.business_id=?
    """, (args.id,)).fetchall()
    if sources:
        print(f"\n  SOURCES")
        for s in sources:
            url = f"  {s['listing_url']}" if s["listing_url"] else ""
            print(f"    {s['name']} ({s['type']}){url}")

    # Contacts
    contacts = conn.execute("""
        SELECT c.id, c.name, c.role, c.company, c.email, c.phone
        FROM business_contacts bc JOIN contacts c ON c.id=bc.contact_id
        WHERE bc.business_id=?
    """, (args.id,)).fetchall()
    if contacts:
        print(f"\n  CONTACTS")
        for c in contacts:
            print(f"    [{c['id']}] {c['name']} ({c['role']}) — {c['company'] or ''}")
            if c["email"]: print(f"         email: {c['email']}")
            if c["phone"]: print(f"         phone: {c['phone']}")

    # Pipeline history
    events = conn.execute(
        "SELECT * FROM pipeline_events WHERE business_id=? ORDER BY event_date", (args.id,)
    ).fetchall()
    if events:
        print(f"\n  PIPELINE HISTORY")
        for e in events:
            arrow = f"{e['from_stage']} → " if e["from_stage"] else ""
            note = f"  [{e['notes']}]" if e["notes"] else ""
            print(f"    {e['event_date']}  {arrow}{e['to_stage']}{note}")

    # Recent interactions
    interactions = conn.execute("""
        SELECT i.interaction_date, i.interaction_type, c.name as contact_name, i.summary
        FROM interactions i
        LEFT JOIN contacts c ON c.id=i.contact_id
        WHERE i.business_id=?
        ORDER BY i.interaction_date DESC LIMIT 10
    """, (args.id,)).fetchall()
    if interactions:
        print(f"\n  RECENT INTERACTIONS")
        for i in interactions:
            contact = f" w/ {i['contact_name']}" if i["contact_name"] else ""
            print(f"    {i['interaction_date']}  [{i['interaction_type']}]{contact}")
            if i["summary"]:
                for line in wrap(i["summary"], 50):
                    print(f"           {line}")
    print()


def _prompt(label, default=None, choices=None, required=False):
    hint = ""
    if choices:
        hint = f" [{'/'.join(choices)}]"
    if default is not None:
        hint += f" (default: {default})"
    while True:
        val = input(f"  {label}{hint}: ").strip()
        if not val:
            if default is not None:
                return default
            if not required:
                return None
            print("  (required)")
            continue
        if choices and val not in choices:
            print(f"  Must be one of: {', '.join(choices)}")
            continue
        return val


def _prompt_float(label, default=None):
    hint = f" (default: {default})" if default is not None else ""
    while True:
        val = input(f"  {label}{hint}: ").strip()
        if not val:
            return default
        try:
            return float(val.replace(",", "").replace("$", "").replace("K","e3").replace("M","e6"))
        except ValueError:
            print("  Enter a number (e.g. 500000 or 500K or 1.2M)")


def _prompt_int(label, default=None):
    hint = f" (default: {default})" if default is not None else ""
    while True:
        val = input(f"  {label}{hint}: ").strip()
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            print("  Enter a whole number")


def cmd_add_business(args, conn):
    print("\n-- Add Business --")
    btype = _prompt("Type", choices=BUSINESS_TYPES, required=True)
    default_stage = "initial_review" if btype == "listing" else "identified"
    stages = LISTING_STAGES if btype == "listing" else PROSPECT_STAGES
    name = _prompt("Business name", required=True)
    stage = _prompt("Stage", default=default_stage, choices=stages)
    city = _prompt("City")
    state = _prompt("State (2-letter)")
    if state:
        state = state.upper()
    industry = _prompt("Industry description")
    naics = _prompt("NAICS code")
    employees = _prompt_int("Employee count")
    year_founded = _prompt_int("Year founded")
    website = _prompt("Website")
    description = _prompt("Description")
    reason = _prompt("Reason for sale") if btype == "listing" else None
    notes = _prompt("Notes")
    date_found = _prompt("Date found (YYYY-MM-DD)", default=str(date.today()))

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO businesses
            (name, type, stage, city, state, industry, naics_code,
             employee_count, year_founded, website, description,
             reason_for_sale, notes, date_found)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (name, btype, stage, city, state, industry, naics,
          employees, year_founded, website, description, reason, notes, date_found))
    biz_id = cur.lastrowid

    # Log initial pipeline event
    cur.execute("""
        INSERT INTO pipeline_events (business_id, from_stage, to_stage, notes)
        VALUES (?,NULL,?,?)
    """, (biz_id, stage, "Initial entry"))

    conn.commit()
    print(f"\n  Added [{biz_id}] {name} ({btype}, stage: {stage})")


def cmd_update_stage(args, conn):
    b = conn.execute("SELECT * FROM businesses WHERE id=?", (args.id,)).fetchone()
    if not b:
        print(f"No business with id {args.id}")
        return
    print(f"\n  [{b['id']}] {b['name']}  current stage: {b['stage']}")
    stages = LISTING_STAGES if b["type"] == "listing" else PROSPECT_STAGES
    new_stage = _prompt("New stage", choices=stages, required=True)
    notes = _prompt("Notes (optional)")
    conn.execute(
        "UPDATE businesses SET stage=? WHERE id=?", (new_stage, args.id)
    )
    conn.execute("""
        INSERT INTO pipeline_events (business_id, from_stage, to_stage, notes)
        VALUES (?,?,?,?)
    """, (args.id, b["stage"], new_stage, notes))
    conn.commit()
    print(f"  Stage updated: {b['stage']} → {new_stage}")


def cmd_add_financial(args, conn):
    b = conn.execute("SELECT name FROM businesses WHERE id=?", (args.id,)).fetchone()
    if not b:
        print(f"No business with id {args.id}")
        return
    print(f"\n-- Financials for [{args.id}] {b['name']} --")
    fy = _prompt_int("Fiscal year", default=date.today().year - 1)
    revenue = _prompt_float("Revenue")
    ebitda = _prompt_float("EBITDA")
    sde = _prompt_float("SDE (Seller's Discretionary Earnings)")
    asking_price = _prompt_float("Asking price")

    # Auto-calculate multiples if possible
    ebitda_mult = None
    sde_mult = None
    if asking_price and ebitda:
        ebitda_mult = round(asking_price / ebitda, 2)
        print(f"  → Auto-calculated EBITDA multiple: {ebitda_mult:.1f}x")
    if asking_price and sde:
        sde_mult = round(asking_price / sde, 2)
        print(f"  → Auto-calculated SDE multiple: {sde_mult:.1f}x")

    conn.execute("""
        INSERT INTO financials
            (business_id, fiscal_year, revenue, ebitda, sde, asking_price,
             ebitda_multiple, sde_multiple)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(business_id, fiscal_year) DO UPDATE SET
            revenue=excluded.revenue, ebitda=excluded.ebitda,
            sde=excluded.sde, asking_price=excluded.asking_price,
            ebitda_multiple=excluded.ebitda_multiple,
            sde_multiple=excluded.sde_multiple
    """, (args.id, fy, revenue, ebitda, sde, asking_price, ebitda_mult, sde_mult))
    conn.commit()
    print(f"  Financials saved for FY{fy}.")


def cmd_add_contact(args, conn):
    print("\n-- Add Contact --")
    name = _prompt("Name", required=True)
    role = _prompt("Role", choices=CONTACT_ROLES, required=True)
    company = _prompt("Company / brokerage")
    email = _prompt("Email")
    phone = _prompt("Phone")
    notes = _prompt("Notes")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO contacts (name, role, company, email, phone, notes)
        VALUES (?,?,?,?,?,?)
    """, (name, role, company, email, phone, notes))
    cid = cur.lastrowid
    conn.commit()
    print(f"  Added contact [{cid}] {name} ({role})")


def cmd_add_source(args, conn):
    print("\n-- Add Source --")
    name = _prompt("Source name", required=True)
    stype = _prompt("Type", choices=SOURCE_TYPES, required=True)
    website = _prompt("Website")
    notes = _prompt("Notes")
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO sources (name, type, website, notes) VALUES (?,?,?,?)",
        (name, stype, website, notes),
    )
    conn.commit()
    print(f"  Added source: {name}")


def cmd_link_contact(args, conn):
    conn.execute(
        "INSERT OR IGNORE INTO business_contacts (business_id, contact_id) VALUES (?,?)",
        (args.biz_id, args.contact_id),
    )
    conn.commit()
    print(f"  Linked contact {args.contact_id} to business {args.biz_id}")


def cmd_link_source(args, conn):
    url = args.url if hasattr(args, "url") else None
    conn.execute(
        "INSERT OR IGNORE INTO business_sources (business_id, source_id, listing_url) VALUES (?,?,?)",
        (args.biz_id, args.source_id, url),
    )
    conn.commit()
    print(f"  Linked source {args.source_id} to business {args.biz_id}")


def cmd_log_interaction(args, conn):
    b = conn.execute("SELECT name FROM businesses WHERE id=?", (args.id,)).fetchone()
    if not b:
        print(f"No business with id {args.id}")
        return
    print(f"\n-- Log Interaction for [{args.id}] {b['name']} --")
    itype = _prompt("Type", choices=INTERACTION_TYPES, required=True)
    idate = _prompt("Date (YYYY-MM-DD)", default=str(date.today()))
    summary = _prompt("Summary / notes")
    contact_id = _prompt_int("Contact ID (optional)")
    conn.execute("""
        INSERT INTO interactions
            (business_id, contact_id, interaction_type, interaction_date, summary)
        VALUES (?,?,?,?,?)
    """, (args.id, contact_id, itype, idate, summary))
    conn.commit()
    print("  Interaction logged.")


def cmd_list_contacts(args, conn):
    rows = conn.execute(
        "SELECT id, name, role, company, email, phone FROM contacts ORDER BY name"
    ).fetchall()
    if not rows:
        print("No contacts yet.")
        return
    data = [{
        "ID": str(r["id"]),
        "Name": r["name"],
        "Role": r["role"] or "",
        "Company": r["company"] or "",
        "Email": r["email"] or "",
        "Phone": r["phone"] or "",
    } for r in rows]
    print_table(["ID", "Name", "Role", "Company", "Email", "Phone"], data,
                ["ID", "Name", "Role", "Company", "Email", "Phone"])


def cmd_list_sources(args, conn):
    rows = conn.execute(
        "SELECT id, name, type, website FROM sources ORDER BY type, name"
    ).fetchall()
    if not rows:
        print("No sources yet.")
        return
    data = [{
        "ID": str(r["id"]),
        "Name": r["name"],
        "Type": r["type"] or "",
        "Website": r["website"] or "",
    } for r in rows]
    print_table(["ID", "Name", "Type", "Website"], data, ["ID", "Name", "Type", "Website"])


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Business Acquisition Database — ETA Deal Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize the database")
    sub.add_parser("summary", help="Pipeline summary")

    p_list = sub.add_parser("list", help="List businesses")
    p_list.add_argument("--type", choices=BUSINESS_TYPES)
    p_list.add_argument("--stage")
    p_list.add_argument("--state")

    p_show = sub.add_parser("show", help="Show business detail")
    p_show.add_argument("id", type=int)

    sub.add_parser("add-business", help="Add a business")

    p_stage = sub.add_parser("update-stage", help="Update pipeline stage")
    p_stage.add_argument("id", type=int)

    p_fin = sub.add_parser("add-financial", help="Add/update financials")
    p_fin.add_argument("id", type=int)

    sub.add_parser("add-contact", help="Add a contact")
    sub.add_parser("add-source", help="Add a source")

    p_lc = sub.add_parser("link-contact", help="Link contact to business")
    p_lc.add_argument("biz_id", type=int)
    p_lc.add_argument("contact_id", type=int)

    p_ls = sub.add_parser("link-source", help="Link source to business")
    p_ls.add_argument("biz_id", type=int)
    p_ls.add_argument("source_id", type=int)
    p_ls.add_argument("url", nargs="?", default=None)

    p_log = sub.add_parser("log-interaction", help="Log interaction")
    p_log.add_argument("id", type=int)

    sub.add_parser("list-contacts", help="List all contacts")
    sub.add_parser("list-sources", help="List all sources")

    args = parser.parse_args()

    if args.command == "init" or not os.path.exists(DB_PATH):
        init_db()
        if args.command == "init":
            return

    conn = get_conn()

    dispatch = {
        "summary":         cmd_summary,
        "list":            cmd_list,
        "show":            cmd_show,
        "add-business":    cmd_add_business,
        "update-stage":    cmd_update_stage,
        "add-financial":   cmd_add_financial,
        "add-contact":     cmd_add_contact,
        "add-source":      cmd_add_source,
        "link-contact":    cmd_link_contact,
        "link-source":     cmd_link_source,
        "log-interaction": cmd_log_interaction,
        "list-contacts":   cmd_list_contacts,
        "list-sources":    cmd_list_sources,
    }

    if not args.command:
        parser.print_help()
        return

    fn = dispatch.get(args.command)
    if fn:
        fn(args, conn)
    conn.close()


if __name__ == "__main__":
    main()
