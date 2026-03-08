# Oracle GL Report Dashboard Generator

Transforms an Oracle GL data dump (Excel) into a formatted, filterable Excel dashboard you can share with cross-functional leads.

## Quick Start

### 1. Install Python dependencies (one time)

```bash
pip install pandas openpyxl xlsxwriter
```

### 2. Run the tool

```bash
python oracle_gl_dashboard.py  YourGLReport.xlsx
```

This produces `YourGLReport_Dashboard.xlsx` in the same folder.

You can also specify a custom output name:

```bash
python oracle_gl_dashboard.py  YourGLReport.xlsx  Q1_Dashboard.xlsx
```

## What You Get

| Sheet | Purpose |
|---|---|
| **Instructions** | Guided walkthrough of every tab |
| **Clean Data** | Normalised copy of the raw GL data with auto-filters |
| **Product Line Mapping** | Editable: assign Lead Owners and notes per product line |
| **Business Line Mapping** | Editable: assign owners per business line |
| **Cost Type Mapping** | Editable: group accounts into cost-type buckets (Personnel, Software, Travel, etc.) |
| **Department Mapping** | Editable: assign owners per department |
| **Summary - Product Line** | Totals aggregated by product line |
| **Summary - Account** | Totals aggregated by account / cost type |
| **Department Detail** | Granular view: Department x Product Line |
| **Pivot - PL x Account** | Cross-tab for leads to see cost types under their product line |
| **Charts** | Bar charts of top product lines and accounts |

## Key Features

- **Dynamic column detection** - automatically identifies dimension vs. amount columns regardless of naming variations.
- **New values auto-appear** - if a new Business Line or Product Line is added to the GL dump, it shows up in the mapping and summary sheets on the next run.
- **Editable mapping sheets** - manually assign Lead Owners, Cost Type Buckets, and Notes.  Copy these mappings forward when you re-run with updated data.
- **Auto-filters & frozen headers** on every sheet - filter by any dimension to slice data for a specific lead.
- **Pivot cross-tab** - lets each product-line lead see their costs broken down by account.

## Sharing with Leads

1. Open the dashboard in Excel.
2. Go to the relevant summary sheet (e.g., *Summary - Product Line*).
3. Use the auto-filter dropdowns to select a specific Product Line.
4. Copy the visible rows → paste into a new workbook → send to that lead.

Or share the whole file and tell each lead which Product Line filter to apply.

## Requirements

- Python 3.9+
- pandas
- openpyxl (for reading .xlsx input)
- xlsxwriter (for writing the formatted dashboard)
