#!/usr/bin/env python3
"""
Oracle GL Report Dashboard Generator
=====================================
Reads an Oracle GL data dump Excel file and produces a formatted Excel dashboard
workbook with:
  1. Clean Data       – normalised copy of the raw data
  2. Mapping          – editable mapping sheet (product‑line → lead, cost‑type buckets, etc.)
  3. Summary by Product Line
  4. Summary by Cost Type
  5. Department Detail
  6. Pivot‑style cross‑tab (Product Line × Cost Type)
  7. Charts sheet

Usage:
    python oracle_gl_dashboard.py <input_gl_file.xlsx> [output_dashboard.xlsx]

Requirements (install once):
    pip install openpyxl xlsxwriter pandas
"""

import sys
import os
import re
import warnings
from pathlib import Path
from datetime import datetime

import pandas as pd

# ---------------------------------------------------------------------------
# Suppress noisy openpyxl / xlsxwriter warnings
# ---------------------------------------------------------------------------
warnings.filterwarnings("ignore", category=UserWarning)

# =====================================================================
# CONFIGURATION – column name normalisation
# =====================================================================
# The GL dump may have slightly different header names.  We map common
# variations to canonical names used throughout the script.

CANONICAL_COLUMNS = {
    # canonical_name : list of possible raw header substrings (case‑insensitive)
    "Company": ["company"],
    "Company_Desc": ["company desc", "company description", "comp desc"],
    "Business_Line": ["business line"],
    "Business_Line_Desc": ["business line desc", "business line description", "bl desc"],
    "Product_Line": ["product line"],
    "Product_Line_Desc": ["product line desc", "product line description", "pl desc"],
    "Department": ["department"],
    "Department_Account": ["department account", "dept account", "dept acct"],
    "Account": ["account"],
    "Dr_Cr": ["dr cr", "dr/cr", "debit credit", "debit/credit", "dr_cr"],
    "Cost_Object": ["cost obj", "cost object"],
    "Cost_Object_Desc": ["cost obj desc", "cost object desc", "cost object description"],
    "Intercompany": ["intercompany"],
    "Intercompany_Desc": ["intercompany desc", "intercompany description", "ic desc"],
    "Ending_Bal_USD": ["ending bal", "ending balance", "end bal"],
}

# Amount / period columns are everything that doesn't match the above and is numeric.

# =====================================================================
# HELPERS
# =====================================================================

def normalise_header(raw: str) -> str:
    """Return a cleaned, lowercase version of a header string."""
    return re.sub(r"[^a-z0-9 /]", "", str(raw).strip().lower())


def map_columns(raw_headers: list[str]) -> dict[str, str]:
    """
    Build a mapping  { raw_header : canonical_name }.
    Headers that don't match any canonical name are treated as amount/period columns.
    """
    mapping: dict[str, str] = {}
    norm_headers = [normalise_header(h) for h in raw_headers]

    for canon, patterns in CANONICAL_COLUMNS.items():
        for idx, norm in enumerate(norm_headers):
            if any(p in norm for p in patterns):
                if raw_headers[idx] not in mapping:
                    mapping[raw_headers[idx]] = canon
                    break  # first match wins
    return mapping


def detect_amount_columns(df: pd.DataFrame, col_map: dict[str, str]) -> list[str]:
    """Return raw column names that appear to be numeric amount / period columns."""
    mapped_raw = set(col_map.keys())
    amount_cols = []
    for col in df.columns:
        if col in mapped_raw:
            continue
        # Try to see if > 30 % of non‑null values are numeric
        sample = df[col].dropna().head(200)
        if len(sample) == 0:
            continue
        numeric_count = pd.to_numeric(sample, errors="coerce").notna().sum()
        if numeric_count / max(len(sample), 1) > 0.3:
            amount_cols.append(col)
    return amount_cols


def safe_canon(df: pd.DataFrame, name: str):
    """Return the column Series if it exists, else None."""
    return df[name] if name in df.columns else None


# =====================================================================
# READING & CLEANING
# =====================================================================

def read_gl_dump(filepath: str) -> pd.DataFrame:
    """Read the GL dump, auto‑detecting the header row."""
    ext = Path(filepath).suffix.lower()
    if ext in (".xlsx", ".xls", ".xlsm", ".xlsb"):
        # Try first few rows to find the header
        raw = pd.read_excel(filepath, header=None, nrows=20)
        header_row = _find_header_row(raw)
        df = pd.read_excel(filepath, header=header_row)
    elif ext == ".csv":
        raw = pd.read_csv(filepath, header=None, nrows=20)
        header_row = _find_header_row(raw)
        df = pd.read_csv(filepath, header=header_row)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Strip whitespace from column names
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _find_header_row(raw: pd.DataFrame) -> int:
    """Heuristic: the header row is the one that contains ≥3 known keywords."""
    keywords = {"company", "business", "product", "account", "department", "ending"}
    for idx, row in raw.iterrows():
        vals = " ".join(str(v).lower() for v in row.values)
        hits = sum(1 for k in keywords if k in vals)
        if hits >= 3:
            return int(idx)
    return 0  # fallback


def build_clean_df(df: pd.DataFrame) -> tuple[pd.DataFrame, dict, list[str]]:
    """
    Return (clean_df, col_map, amount_columns).
    clean_df has canonical column names for dimension columns and keeps
    the original names for amount columns.
    """
    col_map = map_columns(list(df.columns))
    amount_cols = detect_amount_columns(df, col_map)

    rename = {raw: canon for raw, canon in col_map.items()}
    clean = df.rename(columns=rename).copy()

    # Ensure amount columns are numeric
    for ac in amount_cols:
        clean[ac] = pd.to_numeric(clean[ac], errors="coerce").fillna(0)

    # If Ending_Bal_USD exists, make sure it's numeric
    if "Ending_Bal_USD" in clean.columns:
        clean["Ending_Bal_USD"] = pd.to_numeric(clean["Ending_Bal_USD"], errors="coerce").fillna(0)

    # Add a Total_Amount helper (sum of all detected amount cols)
    if amount_cols:
        clean["Total_Amount"] = clean[amount_cols].sum(axis=1)
    elif "Ending_Bal_USD" in clean.columns:
        clean["Total_Amount"] = clean["Ending_Bal_USD"]
    else:
        clean["Total_Amount"] = 0

    return clean, col_map, amount_cols


# =====================================================================
# MAPPING SHEET BUILDER
# =====================================================================

def build_mapping_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Build editable mapping DataFrames:
      - Product_Line_Mapping: Product_Line → Product_Line_Desc, Lead_Owner (blank)
      - Business_Line_Mapping
      - Cost_Type_Mapping: Account → Account_Desc, Cost_Type_Bucket (blank)
      - Department_Mapping: Department → Department_Account, Owner (blank)
    """
    tables: dict[str, pd.DataFrame] = {}

    # Product Line mapping
    if "Product_Line" in df.columns:
        pl = df[["Product_Line"]].drop_duplicates().dropna().sort_values("Product_Line").reset_index(drop=True)
        if "Product_Line_Desc" in df.columns:
            desc_map = df.dropna(subset=["Product_Line"]).drop_duplicates("Product_Line").set_index("Product_Line")["Product_Line_Desc"]
            pl["Product_Line_Desc"] = pl["Product_Line"].map(desc_map)
        pl["Lead_Owner"] = ""
        pl["Notes"] = ""
        tables["Product_Line_Mapping"] = pl

    # Business Line mapping
    if "Business_Line" in df.columns:
        bl = df[["Business_Line"]].drop_duplicates().dropna().sort_values("Business_Line").reset_index(drop=True)
        if "Business_Line_Desc" in df.columns:
            desc_map = df.dropna(subset=["Business_Line"]).drop_duplicates("Business_Line").set_index("Business_Line")["Business_Line_Desc"]
            bl["Business_Line_Desc"] = bl["Business_Line"].map(desc_map)
        bl["Lead_Owner"] = ""
        bl["Notes"] = ""
        tables["Business_Line_Mapping"] = bl

    # Account / Cost Type mapping
    if "Account" in df.columns:
        acct = df[["Account"]].drop_duplicates().dropna().sort_values("Account").reset_index(drop=True)
        acct["Cost_Type_Bucket"] = ""  # user fills in: e.g. Personnel, Software, Travel…
        acct["Notes"] = ""
        tables["Cost_Type_Mapping"] = acct

    # Department mapping
    if "Department" in df.columns:
        dept = df[["Department"]].drop_duplicates().dropna().sort_values("Department").reset_index(drop=True)
        if "Department_Account" in df.columns:
            desc_map = df.dropna(subset=["Department"]).drop_duplicates("Department").set_index("Department")["Department_Account"]
            dept["Department_Account"] = dept["Department"].map(desc_map)
        dept["Owner"] = ""
        dept["Notes"] = ""
        tables["Department_Mapping"] = dept

    return tables


# =====================================================================
# SUMMARY BUILDERS
# =====================================================================

def summary_by_product_line(df: pd.DataFrame, amount_cols: list[str]) -> pd.DataFrame:
    if "Product_Line" not in df.columns:
        return pd.DataFrame()
    group_cols = ["Product_Line"]
    if "Product_Line_Desc" in df.columns:
        group_cols.append("Product_Line_Desc")
    agg_cols = {c: "sum" for c in amount_cols if c in df.columns}
    if "Ending_Bal_USD" in df.columns:
        agg_cols["Ending_Bal_USD"] = "sum"
    agg_cols["Total_Amount"] = "sum"
    result = df.groupby(group_cols, dropna=False).agg(agg_cols).reset_index()
    result = result.sort_values("Total_Amount", ascending=False)
    return result


def summary_by_account(df: pd.DataFrame, amount_cols: list[str]) -> pd.DataFrame:
    if "Account" not in df.columns:
        return pd.DataFrame()
    group_cols = ["Account"]
    agg_cols = {c: "sum" for c in amount_cols if c in df.columns}
    if "Ending_Bal_USD" in df.columns:
        agg_cols["Ending_Bal_USD"] = "sum"
    agg_cols["Total_Amount"] = "sum"
    result = df.groupby(group_cols, dropna=False).agg(agg_cols).reset_index()
    result = result.sort_values("Total_Amount", ascending=False)
    return result


def summary_by_department(df: pd.DataFrame, amount_cols: list[str]) -> pd.DataFrame:
    if "Department" not in df.columns:
        return pd.DataFrame()
    group_cols = ["Department"]
    if "Department_Account" in df.columns:
        group_cols.append("Department_Account")
    if "Product_Line" in df.columns:
        group_cols.append("Product_Line")
    if "Product_Line_Desc" in df.columns:
        group_cols.append("Product_Line_Desc")
    agg_cols = {c: "sum" for c in amount_cols if c in df.columns}
    if "Ending_Bal_USD" in df.columns:
        agg_cols["Ending_Bal_USD"] = "sum"
    agg_cols["Total_Amount"] = "sum"
    result = df.groupby(group_cols, dropna=False).agg(agg_cols).reset_index()
    result = result.sort_values("Total_Amount", ascending=False)
    return result


def pivot_product_account(df: pd.DataFrame) -> pd.DataFrame:
    """Product Line × Account cross‑tab on Total_Amount."""
    if "Product_Line" not in df.columns or "Account" not in df.columns:
        return pd.DataFrame()
    piv = pd.pivot_table(
        df,
        values="Total_Amount",
        index="Product_Line",
        columns="Account",
        aggfunc="sum",
        fill_value=0,
    )
    piv["Grand_Total"] = piv.sum(axis=1)
    piv = piv.sort_values("Grand_Total", ascending=False)
    return piv


# =====================================================================
# EXCEL WRITER with xlsxwriter
# =====================================================================

def _add_table(writer, df: pd.DataFrame, sheet_name: str, title: str,
               workbook, header_fmt, money_fmt, title_fmt, num_fmt):
    """Write a DataFrame as a formatted Excel table on a new sheet."""
    if df.empty:
        return
    df.to_excel(writer, sheet_name=sheet_name, startrow=2, index=False)
    ws = writer.sheets[sheet_name]

    # Title
    ws.write(0, 0, title, title_fmt)

    # Timestamp
    ws.write(1, 0, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Format header row
    for col_idx, col_name in enumerate(df.columns):
        ws.write(2, col_idx, col_name, header_fmt)

    # Auto‑width & number format
    for col_idx, col_name in enumerate(df.columns):
        max_len = max(len(str(col_name)), df[col_name].astype(str).str.len().max() if len(df) > 0 else 0)
        max_len = min(max_len + 3, 45)
        is_numeric = pd.api.types.is_numeric_dtype(df[col_name])

        # Check if it looks like money
        is_money = any(kw in str(col_name).lower() for kw in ["amount", "bal", "usd", "total", "ending"])

        if is_money:
            ws.set_column(col_idx, col_idx, max_len, money_fmt)
        elif is_numeric:
            ws.set_column(col_idx, col_idx, max_len, num_fmt)
        else:
            ws.set_column(col_idx, col_idx, max_len)

    # Freeze header
    ws.freeze_panes(3, 0)

    # Auto‑filter
    if len(df) > 0:
        ws.autofilter(2, 0, 2 + len(df), len(df.columns) - 1)


def _add_pivot_table(writer, df: pd.DataFrame, sheet_name: str, title: str,
                     workbook, header_fmt, money_fmt, title_fmt, num_fmt):
    """Write a pivot DataFrame (with index) as a formatted sheet."""
    if df.empty:
        return
    df.to_excel(writer, sheet_name=sheet_name, startrow=2)
    ws = writer.sheets[sheet_name]
    ws.write(0, 0, title, title_fmt)
    ws.write(1, 0, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Format header
    ws.write(2, 0, df.index.name or "Product_Line", header_fmt)
    for col_idx, col_name in enumerate(df.columns):
        ws.write(2, col_idx + 1, str(col_name), header_fmt)

    # Column widths
    ws.set_column(0, 0, 20)
    ws.set_column(1, len(df.columns), 15, money_fmt)
    ws.freeze_panes(3, 1)


def _add_charts(writer, summary_pl: pd.DataFrame, summary_acct: pd.DataFrame,
                workbook, title_fmt):
    """Create a Charts sheet with bar charts."""
    ws = workbook.add_worksheet("Charts")
    writer.sheets["Charts"] = ws
    ws.write(0, 0, "Dashboard Charts", title_fmt)

    chart_row = 2

    # --- Chart 1: Top Product Lines by Total Amount ---
    if not summary_pl.empty and "Total_Amount" in summary_pl.columns:
        top = summary_pl.head(15).copy()
        label_col = "Product_Line_Desc" if "Product_Line_Desc" in top.columns else "Product_Line"
        # Write hidden data for chart
        data_sheet = workbook.add_worksheet("_chart_data_pl")
        writer.sheets["_chart_data_pl"] = data_sheet
        for i, (_, row) in enumerate(top.iterrows()):
            data_sheet.write(i, 0, str(row.get(label_col, row.get("Product_Line", f"PL{i}"))))
            data_sheet.write(i, 1, float(row["Total_Amount"]))
        data_sheet.hide()

        chart1 = workbook.add_chart({"type": "bar"})
        chart1.add_series({
            "name": "Total Amount",
            "categories": ["_chart_data_pl", 0, 0, len(top) - 1, 0],
            "values": ["_chart_data_pl", 0, 1, len(top) - 1, 1],
            "fill": {"color": "#4472C4"},
        })
        chart1.set_title({"name": "Top Product Lines by Total Amount"})
        chart1.set_size({"width": 800, "height": 480})
        chart1.set_legend({"none": True})
        chart1.set_y_axis({"reverse": True})
        ws.insert_chart(chart_row, 0, chart1)
        chart_row += 26

    # --- Chart 2: Top Accounts by Total Amount ---
    if not summary_acct.empty and "Total_Amount" in summary_acct.columns:
        top = summary_acct.head(15).copy()
        data_sheet2 = workbook.add_worksheet("_chart_data_acct")
        writer.sheets["_chart_data_acct"] = data_sheet2
        for i, (_, row) in enumerate(top.iterrows()):
            data_sheet2.write(i, 0, str(row["Account"]))
            data_sheet2.write(i, 1, float(row["Total_Amount"]))
        data_sheet2.hide()

        chart2 = workbook.add_chart({"type": "bar"})
        chart2.add_series({
            "name": "Total Amount",
            "categories": ["_chart_data_acct", 0, 0, len(top) - 1, 0],
            "values": ["_chart_data_acct", 0, 1, len(top) - 1, 1],
            "fill": {"color": "#ED7D31"},
        })
        chart2.set_title({"name": "Top Accounts by Total Amount"})
        chart2.set_size({"width": 800, "height": 480})
        chart2.set_legend({"none": True})
        chart2.set_y_axis({"reverse": True})
        ws.insert_chart(chart_row, 0, chart2)


def _add_instructions(writer, workbook, title_fmt, header_fmt):
    """Add an Instructions / README sheet as the first sheet."""
    ws = workbook.add_worksheet("Instructions")
    writer.sheets["Instructions"] = ws

    wrap_fmt = workbook.add_format({"text_wrap": True, "valign": "top", "font_size": 11})
    bold_fmt = workbook.add_format({"bold": True, "font_size": 11})

    ws.set_column(0, 0, 80)
    row = 0
    ws.write(row, 0, "Oracle GL Dashboard – Instructions", title_fmt); row += 2

    instructions = [
        ("Overview",
         "This workbook was auto‑generated from your Oracle GL data dump. "
         "It contains summary views sliced by Product Line, Account / Cost Type, "
         "and Department so that cross‑functional leads can review their budgets."),
        ("Sheet Descriptions", None),
        ("  Clean Data",
         "A normalised copy of the raw GL data with standardised column names. "
         "All amount columns are preserved as‑is."),
        ("  Mapping",
         "Editable lookup tables. Fill in the Lead_Owner, Cost_Type_Bucket, "
         "and Notes columns to customise how data is grouped in future runs. "
         "New values (e.g. a new Business Line) will auto‑appear here on re‑run."),
        ("  Summary – Product Line",
         "Aggregated totals per Product Line. Use the auto‑filters to slice."),
        ("  Summary – Account",
         "Aggregated totals per Account (cost type). Fill in Cost_Type_Bucket "
         "in the Mapping sheet to group accounts into higher‑level buckets."),
        ("  Department Detail",
         "Granular view by Department × Product Line. Great for leads who need "
         "to drill into specific cost centres."),
        ("  Pivot – PL × Account",
         "Cross‑tab of Product Line rows vs Account columns. Shows where money "
         "is being spent across cost types within each product line."),
        ("  Charts",
         "Visual bar charts of the top Product Lines and Accounts by amount."),
        ("How to Re‑run with New Data", None),
        ("",
         "1. Place your new GL dump file in the same folder as the script.\n"
         "2. Run:  python oracle_gl_dashboard.py <new_file.xlsx>\n"
         "3. A new dashboard workbook is generated. Your Mapping sheet edits "
         "are NOT automatically carried over – copy them from the old file."),
        ("Tips", None),
        ("",
         "• Every summary sheet has auto‑filters and frozen headers.\n"
         "• Right‑click any column header → Filter to slice by specific values.\n"
         "• The Pivot sheet is useful for presenting to leads who own a Product Line.\n"
         "• To share a single lead's view: filter the Product Line, copy the "
         "visible rows, and paste into a new workbook."),
    ]

    for heading, body in instructions:
        if body is None:
            ws.write(row, 0, heading, bold_fmt)
            row += 1
        else:
            if heading.strip():
                ws.write(row, 0, heading, bold_fmt)
                row += 1
            ws.write(row, 0, body, wrap_fmt)
            row += 2


def write_dashboard(clean_df: pd.DataFrame, amount_cols: list[str],
                    mapping_tables: dict, output_path: str):
    """Compose and write the full dashboard workbook."""

    # Build summaries
    s_pl = summary_by_product_line(clean_df, amount_cols)
    s_acct = summary_by_account(clean_df, amount_cols)
    s_dept = summary_by_department(clean_df, amount_cols)
    piv = pivot_product_account(clean_df)

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        workbook = writer.book

        # -- Formats --
        title_fmt = workbook.add_format({
            "bold": True, "font_size": 16, "font_color": "#1F4E79",
            "bottom": 2, "bottom_color": "#1F4E79",
        })
        header_fmt = workbook.add_format({
            "bold": True, "font_size": 11, "bg_color": "#4472C4",
            "font_color": "white", "border": 1, "text_wrap": True,
        })
        money_fmt = workbook.add_format({"num_format": "#,##0.00", "font_size": 10})
        num_fmt = workbook.add_format({"num_format": "#,##0", "font_size": 10})

        # 0. Instructions
        _add_instructions(writer, workbook, title_fmt, header_fmt)

        # 1. Clean Data
        _add_table(writer, clean_df, "Clean Data", "Oracle GL – Clean Data",
                   workbook, header_fmt, money_fmt, title_fmt, num_fmt)

        # 2. Mapping sheets
        for map_name, map_df in mapping_tables.items():
            sheet = map_name.replace("_", " ")[:31]  # Excel 31‑char limit
            _add_table(writer, map_df, sheet, f"Mapping – {map_name.replace('_', ' ')}",
                       workbook, header_fmt, money_fmt, title_fmt, num_fmt)

        # 3. Summary – Product Line
        _add_table(writer, s_pl, "Summary – Product Line",
                   "Summary by Product Line",
                   workbook, header_fmt, money_fmt, title_fmt, num_fmt)

        # 4. Summary – Account / Cost Type
        _add_table(writer, s_acct, "Summary – Account",
                   "Summary by Account (Cost Type)",
                   workbook, header_fmt, money_fmt, title_fmt, num_fmt)

        # 5. Department Detail
        _add_table(writer, s_dept, "Department Detail",
                   "Department × Product Line Detail",
                   workbook, header_fmt, money_fmt, title_fmt, num_fmt)

        # 6. Pivot
        _add_pivot_table(writer, piv, "Pivot – PL x Account",
                         "Product Line × Account Cross‑Tab",
                         workbook, header_fmt, money_fmt, title_fmt, num_fmt)

        # 7. Charts
        _add_charts(writer, s_pl, s_acct, workbook, title_fmt)

    print(f"\n  Dashboard saved to: {os.path.abspath(output_path)}")


# =====================================================================
# MAIN
# =====================================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("ERROR: Please provide the path to your Oracle GL Excel file.")
        print("  Example:  python oracle_gl_dashboard.py GL_Report_Q1.xlsx")
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.isfile(input_path):
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)

    # Default output name
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        stem = Path(input_path).stem
        output_path = f"{stem}_Dashboard.xlsx"

    print(f"Reading GL dump from: {input_path}")
    raw_df = read_gl_dump(input_path)
    print(f"  Rows: {len(raw_df):,}  |  Columns: {len(raw_df.columns)}")

    print("Normalising columns …")
    clean_df, col_map, amount_cols = build_clean_df(raw_df)
    print(f"  Mapped dimension columns: {len(col_map)}")
    print(f"  Detected amount/period columns: {len(amount_cols)}")
    if amount_cols:
        print(f"    → {amount_cols[:5]}{'…' if len(amount_cols) > 5 else ''}")

    print("Building mapping tables …")
    mapping_tables = build_mapping_tables(clean_df)
    for name, tbl in mapping_tables.items():
        print(f"  {name}: {len(tbl)} unique entries")

    print("Generating dashboard …")
    write_dashboard(clean_df, amount_cols, mapping_tables, output_path)

    print("\nDone!  Open the .xlsx file in Excel on your work laptop.")
    print("Tip: Start with the 'Instructions' tab for a guided walkthrough.\n")


if __name__ == "__main__":
    main()
