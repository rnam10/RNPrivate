#!/usr/bin/env python3
"""
Business Acquisition Web Dashboard
Run: python acquisition_web.py
Open: http://localhost:5050
"""
import sqlite3
from datetime import date
from flask import Flask, render_template_string, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'eta-acq-2026'

DB_PATH = '/home/user/RNPrivate/acquisition.db'

LISTING_STAGES = ['initial_review','nda_requested','nda_signed','financials_review',
                  'management_meeting','loi_submitted','loi_accepted','due_diligence',
                  'closed_won','closed_lost','passed']
PROSPECT_STAGES = ['identified','researching','outreach_planned','outreach_sent',
                   'engaged','converted_to_listing','passed']
ALL_STAGES = sorted(set(LISTING_STAGES + PROSPECT_STAGES))
CONTACT_ROLES = ['broker','owner','advisor','lender','other']
SOURCE_TYPES  = ['marketplace','broker','direct','referral','other']
INTERACTION_TYPES = ['call','email','meeting','nda','loi','note','other']

STAGE_COLORS = {
    'initial_review':'secondary','identified':'secondary','researching':'secondary',
    'nda_requested':'primary','outreach_planned':'primary','outreach_sent':'primary',
    'nda_signed':'info','engaged':'info',
    'financials_review':'warning','management_meeting':'warning','loi_submitted':'warning',
    'loi_accepted':'success','due_diligence':'success','closed_won':'success','converted_to_listing':'success',
    'closed_lost':'danger','passed':'danger',
}

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def fmt_money(val):
    if val is None: return '—'
    if val >= 1_000_000: return f'${val/1_000_000:.2f}M'
    if val >= 1_000: return f'${val/1_000:.0f}K'
    return f'${val:,.0f}'

def badge(stage):
    color = STAGE_COLORS.get(stage, 'secondary')
    return f'<span class="badge bg-{color}">{stage.replace("_"," ")}</span>'

# ---------------------------------------------------------------------------
# Base layout
# ---------------------------------------------------------------------------
BASE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>ETA Deal Tracker</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
  <style>
    body { background:#f8f9fa; }
    .navbar-brand { font-weight:700; letter-spacing:.5px; }
    tr.clickable { cursor:pointer; }
    tr.clickable:hover { background:#e9ecef; }
    .stage-badge { white-space:nowrap; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
  <div class="container-fluid">
    <a class="navbar-brand" href="/">ETA Deal Tracker</a>
    <div class="navbar-nav me-auto">
      <a class="nav-link" href="/">Summary</a>
      <a class="nav-link" href="/businesses?type=listing">Listings</a>
      <a class="nav-link" href="/businesses?type=prospect">Prospects</a>
      <a class="nav-link" href="/contacts">Contacts</a>
      <a class="nav-link" href="/sources">Sources</a>
    </div>
    <a class="btn btn-success btn-sm" href="/businesses/add">+ Add Business</a>
  </div>
</nav>
<div class="container-fluid px-4">
  {% for cat, msg in messages %}
  <div class="alert alert-{{ 'success' if cat == 'success' else 'danger' }} alert-dismissible fade show">
    {{ msg }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
  </div>
  {% endfor %}
  {{ content }}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""

def render(content, **ctx):
    from flask import get_flashed_messages
    messages = get_flashed_messages(with_categories=True)
    return render_template_string(BASE, content=content, messages=messages, **ctx)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
@app.route('/')
def summary():
    conn = get_conn()
    l_stages = conn.execute(
        "SELECT stage, COUNT(*) c FROM businesses WHERE type='listing' GROUP BY stage ORDER BY stage"
    ).fetchall()
    p_stages = conn.execute(
        "SELECT stage, COUNT(*) c FROM businesses WHERE type='prospect' GROUP BY stage ORDER BY stage"
    ).fetchall()
    fins = conn.execute("""
        SELECT b.id, b.name, b.stage, f.fiscal_year, f.revenue, f.ebitda, f.sde,
               f.asking_price, f.ebitda_multiple, f.sde_multiple
        FROM businesses b JOIN financials f ON f.business_id=b.id
        WHERE b.type='listing' ORDER BY f.asking_price DESC
    """).fetchall()
    conn.close()

    l_rows = ''.join(f'<tr><td>{r["stage"].replace("_"," ")}</td><td class="fw-bold">{r["c"]}</td></tr>' for r in l_stages) or '<tr><td colspan=2 class="text-muted">None yet</td></tr>'
    p_rows = ''.join(f'<tr><td>{r["stage"].replace("_"," ")}</td><td class="fw-bold">{r["c"]}</td></tr>' for r in p_stages) or '<tr><td colspan=2 class="text-muted">None yet</td></tr>'
    fin_rows = ''.join(f'''<tr>
      <td><a href="/businesses/{r["id"]}">{r["name"]}</a></td>
      <td>{badge(r["stage"])}</td>
      <td>{r["fiscal_year"] or "—"}</td>
      <td>{fmt_money(r["revenue"])}</td><td>{fmt_money(r["ebitda"])}</td>
      <td>{fmt_money(r["sde"])}</td><td>{fmt_money(r["asking_price"])}</td>
      <td>{f'{r["ebitda_multiple"]:.1f}x' if r["ebitda_multiple"] else "—"}</td>
      <td>{f'{r["sde_multiple"]:.1f}x' if r["sde_multiple"] else "—"}</td>
    </tr>''' for r in fins) or '<tr><td colspan=9 class="text-muted">No financial data yet</td></tr>'

    html = f"""
<h4 class="mb-3">Pipeline Summary</h4>
<div class="row g-3 mb-4">
  <div class="col-md-6">
    <div class="card h-100"><div class="card-header fw-bold bg-primary text-white">Listings</div>
    <div class="card-body p-0"><table class="table table-sm mb-0">
      <thead><tr><th>Stage</th><th>#</th></tr></thead><tbody>{l_rows}</tbody>
    </table></div></div>
  </div>
  <div class="col-md-6">
    <div class="card h-100"><div class="card-header fw-bold bg-secondary text-white">Prospects</div>
    <div class="card-body p-0"><table class="table table-sm mb-0">
      <thead><tr><th>Stage</th><th>#</th></tr></thead><tbody>{p_rows}</tbody>
    </table></div></div>
  </div>
</div>
<h5 class="mb-2">Listings with Financials</h5>
<div class="table-responsive"><table class="table table-sm table-hover bg-white rounded shadow-sm">
  <thead class="table-dark"><tr><th>Business</th><th>Stage</th><th>FY</th>
    <th>Revenue</th><th>EBITDA</th><th>SDE</th><th>Ask Price</th><th>EBITDA Mx</th><th>SDE Mx</th></tr></thead>
  <tbody>{fin_rows}</tbody>
</table></div>"""
    return render(html)

# ---------------------------------------------------------------------------
# Business list
# ---------------------------------------------------------------------------
@app.route('/businesses')
def business_list():
    btype = request.args.get('type','')
    stage = request.args.get('stage','')
    state = request.args.get('state','')
    q = "SELECT * FROM businesses WHERE 1=1"
    params = []
    if btype:  q += " AND type=?";  params.append(btype)
    if stage:  q += " AND stage=?"; params.append(stage)
    if state:  q += " AND state=?"; params.append(state.upper())
    q += " ORDER BY updated_at DESC"
    conn = get_conn()
    rows = conn.execute(q, params).fetchall()
    conn.close()

    stage_opts = ''.join(f'<option value="{s}" {"selected" if s==stage else ""}>{s.replace("_"," ")}</option>' for s in ALL_STAGES)
    type_opts  = ''.join(f'<option value="{t}" {"selected" if t==btype else ""}>{t.capitalize()}</option>' for t in ['listing','prospect'])
    trows = ''.join(f'''<tr class="clickable" onclick="location='/businesses/{r["id"]}'">
      <td>{r["id"]}</td><td>{r["name"]}</td>
      <td><span class="badge bg-{'primary' if r['type']=='listing' else 'secondary'}">{r["type"]}</span></td>
      <td>{badge(r["stage"])}</td>
      <td>{r["city"] or ""}</td><td>{r["state"] or ""}</td>
      <td>{(r["industry"] or "")[:35]}</td>
      <td>{r["employee_count"] or ""}</td>
      <td>{r["date_found"] or ""}</td>
    </tr>''' for r in rows) or '<tr><td colspan=9 class="text-muted text-center py-3">No businesses found</td></tr>'

    html = f"""
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0">Businesses</h4>
  <a class="btn btn-success btn-sm" href="/businesses/add">+ Add Business</a>
</div>
<form class="row g-2 mb-3 bg-white p-3 rounded shadow-sm">
  <div class="col-auto"><select name="type" class="form-select form-select-sm">
    <option value="">All Types</option>{type_opts}</select></div>
  <div class="col-auto"><select name="stage" class="form-select form-select-sm">
    <option value="">All Stages</option>{stage_opts}</select></div>
  <div class="col-auto"><input name="state" class="form-control form-control-sm" placeholder="State" value="{state}" style="width:80px"></div>
  <div class="col-auto"><button class="btn btn-primary btn-sm">Filter</button>
  <a class="btn btn-outline-secondary btn-sm ms-1" href="/businesses">Clear</a></div>
</form>
<div class="table-responsive"><table class="table table-hover bg-white rounded shadow-sm">
  <thead class="table-dark"><tr><th>ID</th><th>Name</th><th>Type</th><th>Stage</th>
    <th>City</th><th>State</th><th>Industry</th><th>Employees</th><th>Date Found</th></tr></thead>
  <tbody>{trows}</tbody>
</table></div>
<p class="text-muted small">{len(rows)} record(s)</p>"""
    return render(html)

# ---------------------------------------------------------------------------
# Add business
# ---------------------------------------------------------------------------
@app.route('/businesses/add', methods=['GET','POST'])
def add_business():
    if request.method == 'POST':
        f = request.form
        btype = f.get('type','listing')
        stage = f.get('stage', 'initial_review' if btype=='listing' else 'identified')
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""INSERT INTO businesses
            (name,type,stage,city,state,industry,naics_code,employee_count,year_founded,
             website,description,reason_for_sale,notes,date_found)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f['name'], btype, stage,
             f.get('city') or None, (f.get('state') or '').upper() or None,
             f.get('industry') or None, f.get('naics_code') or None,
             int(f['employee_count']) if f.get('employee_count') else None,
             int(f['year_founded']) if f.get('year_founded') else None,
             f.get('website') or None, f.get('description') or None,
             f.get('reason_for_sale') or None, f.get('notes') or None,
             f.get('date_found') or str(date.today())))
        bid = cur.lastrowid
        conn.execute("INSERT INTO pipeline_events (business_id,from_stage,to_stage,notes) VALUES (?,NULL,?,'Initial entry')",
                     (bid, stage))
        conn.commit(); conn.close()
        flash(f'Added "{f["name"]}"', 'success')
        return redirect(url_for('business_detail', id=bid))

    l_opts = ''.join(f'<option value="{s}">{s.replace("_"," ")}</option>' for s in LISTING_STAGES)
    p_opts = ''.join(f'<option value="{s}">{s.replace("_"," ")}</option>' for s in PROSPECT_STAGES)
    html = f"""
<h4 class="mb-4">Add Business</h4>
<div class="card shadow-sm"><div class="card-body">
<form method="post">
  <div class="row g-3">
    <div class="col-md-6"><label class="form-label fw-bold">Business Name *</label>
      <input name="name" class="form-control" required></div>
    <div class="col-md-3"><label class="form-label fw-bold">Type *</label>
      <select name="type" class="form-select" id="bizType" onchange="updateStages()">
        <option value="listing">Listing</option><option value="prospect">Prospect</option>
      </select></div>
    <div class="col-md-3"><label class="form-label fw-bold">Stage *</label>
      <select name="stage" class="form-select" id="stageSelect">{l_opts}</select></div>
    <div class="col-md-4"><label class="form-label">City</label><input name="city" class="form-control"></div>
    <div class="col-md-2"><label class="form-label">State</label><input name="state" class="form-control" maxlength="2" placeholder="TX"></div>
    <div class="col-md-3"><label class="form-label">Employees</label><input name="employee_count" type="number" class="form-control"></div>
    <div class="col-md-3"><label class="form-label">Year Founded</label><input name="year_founded" type="number" class="form-control" placeholder="2005"></div>
    <div class="col-md-6"><label class="form-label">Industry</label><input name="industry" class="form-control"></div>
    <div class="col-md-3"><label class="form-label">NAICS Code</label><input name="naics_code" class="form-control"></div>
    <div class="col-md-3"><label class="form-label">Date Found</label><input name="date_found" type="date" class="form-control" value="{date.today()}"></div>
    <div class="col-md-6"><label class="form-label">Website</label><input name="website" class="form-control" placeholder="https://"></div>
    <div class="col-md-6"><label class="form-label">Reason for Sale</label><input name="reason_for_sale" class="form-control"></div>
    <div class="col-12"><label class="form-label">Description</label><textarea name="description" class="form-control" rows="3"></textarea></div>
    <div class="col-12"><label class="form-label">Notes</label><textarea name="notes" class="form-control" rows="2"></textarea></div>
    <div class="col-12">
      <button class="btn btn-success">Save Business</button>
      <a class="btn btn-outline-secondary ms-2" href="/businesses">Cancel</a>
    </div>
  </div>
</form></div></div>
<script>
const listingStages = {[f'"{s}"' for s in LISTING_STAGES]};
const prospectStages = {[f'"{s}"' for s in PROSPECT_STAGES]};
function updateStages() {{
  const t = document.getElementById('bizType').value;
  const sel = document.getElementById('stageSelect');
  const stages = t === 'listing' ? listingStages : prospectStages;
  sel.innerHTML = stages.map(s => `<option value="${{s}}">${{s.replace(/_/g,' ')}}</option>`).join('');
}}
</script>"""
    return render(html)

# ---------------------------------------------------------------------------
# Business detail
# ---------------------------------------------------------------------------
@app.route('/businesses/<int:id>')
def business_detail(id):
    conn = get_conn()
    b = conn.execute("SELECT * FROM businesses WHERE id=?", (id,)).fetchone()
    if not b:
        conn.close(); flash('Business not found','danger'); return redirect(url_for('business_list'))

    fins    = conn.execute("SELECT * FROM financials WHERE business_id=? ORDER BY fiscal_year DESC", (id,)).fetchall()
    sources = conn.execute("""SELECT s.id,s.name,s.type,bs.listing_url FROM business_sources bs
                              JOIN sources s ON s.id=bs.source_id WHERE bs.business_id=?""", (id,)).fetchall()
    contacts= conn.execute("""SELECT c.id,c.name,c.role,c.company,c.email,c.phone FROM business_contacts bc
                              JOIN contacts c ON c.id=bc.contact_id WHERE bc.business_id=?""", (id,)).fetchall()
    events  = conn.execute("SELECT * FROM pipeline_events WHERE business_id=? ORDER BY event_date", (id,)).fetchall()
    acts    = conn.execute("""SELECT i.*,c.name as cname FROM interactions i
                              LEFT JOIN contacts c ON c.id=i.contact_id
                              WHERE i.business_id=? ORDER BY i.interaction_date DESC""", (id,)).fetchall()
    all_contacts = conn.execute("SELECT id,name,role FROM contacts ORDER BY name").fetchall()
    all_sources  = conn.execute("SELECT id,name FROM sources ORDER BY name").fetchall()
    conn.close()

    stages = LISTING_STAGES if b['type']=='listing' else PROSPECT_STAGES

    # ---- Tab 1: Overview ----
    def field(label, val):
        return f'<div class="col-md-4 mb-2"><span class="text-muted small">{label}</span><div class="fw-semibold">{val or "—"}</div></div>'

    tab1 = f"""<div class="row mt-3">
      {field("Type", b["type"].capitalize())}
      {field("Stage", badge(b["stage"]))}
      {field("Date Found", b["date_found"])}
      {field("City", b["city"])}{field("State", b["state"])}
      {field("Industry", b["industry"])}{field("NAICS", b["naics_code"])}
      {field("Employees", b["employee_count"])}{field("Year Founded", b["year_founded"])}
      {field("Website", f'<a href="{b["website"]}" target="_blank">{b["website"]}</a>' if b["website"] else None)}
      {field("Reason for Sale", b["reason_for_sale"])}
    </div>
    <div class="mt-2"><span class="text-muted small">Description</span><p>{b["description"] or "—"}</p></div>
    <div class="mt-2"><span class="text-muted small">Notes</span><p>{b["notes"] or "—"}</p></div>"""

    # ---- Tab 2: Financials + Update Stage ----
    fin_rows = ''.join(f"""<tr><td>{r["fiscal_year"] or "?"}</td>
      <td>{fmt_money(r["revenue"])}</td><td>{fmt_money(r["ebitda"])}</td>
      <td>{fmt_money(r["sde"])}</td><td>{fmt_money(r["asking_price"])}</td>
      <td>{f'{r["ebitda_multiple"]:.1f}x' if r["ebitda_multiple"] else "—"}</td>
      <td>{f'{r["sde_multiple"]:.1f}x' if r["sde_multiple"] else "—"}</td></tr>""" for r in fins
    ) or '<tr><td colspan=7 class="text-muted">No financials yet</td></tr>'

    stage_opts = ''.join(f'<option value="{s}" {"selected" if s==b["stage"] else ""}>{s.replace("_"," ")}</option>' for s in stages)

    tab2 = f"""
    <div class="row mt-3">
      <div class="col-md-8">
        <h6>Financials</h6>
        <div class="table-responsive"><table class="table table-sm table-hover">
          <thead class="table-light"><tr><th>FY</th><th>Revenue</th><th>EBITDA</th>
            <th>SDE</th><th>Ask Price</th><th>EBITDA Mx</th><th>SDE Mx</th></tr></thead>
          <tbody>{fin_rows}</tbody>
        </table></div>
        <a class="btn btn-outline-primary btn-sm" href="/businesses/{id}/add-financial">+ Add / Update Financials</a>
      </div>
      <div class="col-md-4">
        <h6>Update Stage</h6>
        <form method="post" action="/businesses/{id}/update-stage">
          <div class="mb-2"><select name="stage" class="form-select form-select-sm">{stage_opts}</select></div>
          <div class="mb-2"><textarea name="notes" class="form-control form-control-sm" rows="2" placeholder="Notes (optional)"></textarea></div>
          <button class="btn btn-warning btn-sm">Update Stage</button>
        </form>
      </div>
    </div>"""

    # ---- Tab 3: Contacts & Sources ----
    c_rows = ''.join(f"""<tr><td>{c["name"]}</td><td>{c["role"] or ""}</td>
      <td>{c["company"] or ""}</td><td>{c["email"] or ""}</td><td>{c["phone"] or ""}</td></tr>""" for c in contacts
    ) or '<tr><td colspan=5 class="text-muted">None linked</td></tr>'

    s_rows = ''.join(f"""<tr><td>{s["name"]}</td><td>{s["type"] or ""}</td>
      <td>{"<a href='"+s["listing_url"]+"' target='_blank'>"+s["listing_url"]+"</a>" if s["listing_url"] else "—"}</td></tr>""" for s in sources
    ) or '<tr><td colspan=3 class="text-muted">None linked</td></tr>'

    c_opts = ''.join(f'<option value="{c["id"]}">{c["name"]} ({c["role"] or "?"})</option>' for c in all_contacts)
    s_opts = ''.join(f'<option value="{s["id"]}">{s["name"]}</option>' for s in all_sources)

    tab3 = f"""
    <div class="row mt-3 g-4">
      <div class="col-md-7">
        <h6>Linked Contacts</h6>
        <table class="table table-sm"><thead class="table-light"><tr><th>Name</th><th>Role</th>
          <th>Company</th><th>Email</th><th>Phone</th></tr></thead><tbody>{c_rows}</tbody></table>
        <form method="post" action="/businesses/{id}/link-contact" class="d-flex gap-2 mt-1">
          <select name="contact_id" class="form-select form-select-sm">{c_opts or '<option disabled>No contacts yet</option>'}</select>
          <button class="btn btn-outline-primary btn-sm">Link</button>
        </form>
        <a class="btn btn-link btn-sm ps-0" href="/contacts/add">+ Add New Contact</a>
      </div>
      <div class="col-md-5">
        <h6>Linked Sources</h6>
        <table class="table table-sm"><thead class="table-light"><tr><th>Source</th><th>Type</th><th>URL</th></tr></thead>
          <tbody>{s_rows}</tbody></table>
        <form method="post" action="/businesses/{id}/link-source" class="mt-1">
          <div class="d-flex gap-2 mb-1">
            <select name="source_id" class="form-select form-select-sm">{s_opts}</select>
            <button class="btn btn-outline-secondary btn-sm">Link</button>
          </div>
          <input name="listing_url" class="form-control form-control-sm" placeholder="Listing URL (optional)">
        </form>
      </div>
    </div>"""

    # ---- Tab 4: Activity ----
    ev_rows = ''.join(f"""<tr><td>{e["event_date"]}</td>
      <td>{(e["from_stage"] or "").replace("_"," ")} → {e["to_stage"].replace("_"," ")}</td>
      <td>{e["notes"] or ""}</td></tr>""" for e in events
    ) or '<tr><td colspan=3 class="text-muted">No events</td></tr>'

    act_rows = ''.join(f"""<tr><td>{a["interaction_date"]}</td>
      <td><span class="badge bg-secondary">{a["interaction_type"]}</span></td>
      <td>{a["cname"] or "—"}</td><td>{a["summary"] or ""}</td></tr>""" for a in acts
    ) or '<tr><td colspan=4 class="text-muted">No interactions yet</td></tr>'

    ia_c_opts = '<option value="">— none —</option>' + ''.join(f'<option value="{c["id"]}">{c["name"]}</option>' for c in all_contacts)
    ia_type_opts = ''.join(f'<option value="{t}">{t}</option>' for t in INTERACTION_TYPES)

    tab4 = f"""
    <div class="row mt-3 g-4">
      <div class="col-md-8">
        <h6>Pipeline History</h6>
        <table class="table table-sm mb-4"><thead class="table-light"><tr><th>Date</th><th>Transition</th><th>Notes</th></tr></thead>
          <tbody>{ev_rows}</tbody></table>
        <h6>Interactions</h6>
        <table class="table table-sm"><thead class="table-light"><tr><th>Date</th><th>Type</th><th>Contact</th><th>Summary</th></tr></thead>
          <tbody>{act_rows}</tbody></table>
      </div>
      <div class="col-md-4">
        <h6>Log Interaction</h6>
        <form method="post" action="/businesses/{id}/log-interaction">
          <div class="mb-2"><select name="interaction_type" class="form-select form-select-sm">{ia_type_opts}</select></div>
          <div class="mb-2"><input name="interaction_date" type="date" class="form-control form-control-sm" value="{date.today()}"></div>
          <div class="mb-2"><select name="contact_id" class="form-select form-select-sm">{ia_c_opts}</select></div>
          <div class="mb-2"><textarea name="summary" class="form-control form-control-sm" rows="3" placeholder="Summary / notes"></textarea></div>
          <button class="btn btn-primary btn-sm">Log</button>
        </form>
      </div>
    </div>"""

    html = f"""
<div class="d-flex justify-content-between align-items-center mb-3">
  <div>
    <a class="text-muted text-decoration-none small" href="/businesses">← All Businesses</a>
    <h4 class="mb-0">{b["name"]} <small class="fs-6">{badge(b["stage"])}</small></h4>
  </div>
</div>
<div class="card shadow-sm">
  <div class="card-header">
    <ul class="nav nav-tabs card-header-tabs">
      <li class="nav-item"><a class="nav-link active" data-bs-toggle="tab" href="#overview">Overview</a></li>
      <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#financials">Financials</a></li>
      <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#contacts">Contacts &amp; Sources</a></li>
      <li class="nav-item"><a class="nav-link" data-bs-toggle="tab" href="#activity">Activity</a></li>
    </ul>
  </div>
  <div class="card-body">
    <div class="tab-content">
      <div class="tab-pane fade show active" id="overview">{tab1}</div>
      <div class="tab-pane fade" id="financials">{tab2}</div>
      <div class="tab-pane fade" id="contacts">{tab3}</div>
      <div class="tab-pane fade" id="activity">{tab4}</div>
    </div>
  </div>
</div>"""
    return render(html)

# ---------------------------------------------------------------------------
# Update stage
# ---------------------------------------------------------------------------
@app.route('/businesses/<int:id>/update-stage', methods=['POST'])
def update_stage(id):
    conn = get_conn()
    b = conn.execute("SELECT stage FROM businesses WHERE id=?", (id,)).fetchone()
    if b:
        new_stage = request.form.get('stage')
        notes = request.form.get('notes') or None
        conn.execute("UPDATE businesses SET stage=? WHERE id=?", (new_stage, id))
        conn.execute("INSERT INTO pipeline_events (business_id,from_stage,to_stage,notes) VALUES (?,?,?,?)",
                     (id, b['stage'], new_stage, notes))
        conn.commit()
        flash(f'Stage updated to {new_stage.replace("_"," ")}', 'success')
    conn.close()
    return redirect(url_for('business_detail', id=id) + '#financials')

# ---------------------------------------------------------------------------
# Add financial
# ---------------------------------------------------------------------------
@app.route('/businesses/<int:id>/add-financial', methods=['GET','POST'])
def add_financial(id):
    conn = get_conn()
    b = conn.execute("SELECT name FROM businesses WHERE id=?", (id,)).fetchone()
    if not b:
        conn.close(); return redirect(url_for('business_list'))

    if request.method == 'POST':
        f = request.form
        def flt(k): v=f.get(k); return float(v.replace(',','')) if v else None
        rev=flt('revenue'); ebitda=flt('ebitda'); sde=flt('sde'); ask=flt('asking_price')
        emx = round(ask/ebitda,2) if ask and ebitda else None
        smx = round(ask/sde,2) if ask and sde else None
        conn.execute("""INSERT INTO financials
            (business_id,fiscal_year,revenue,ebitda,sde,asking_price,ebitda_multiple,sde_multiple)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(business_id,fiscal_year) DO UPDATE SET
              revenue=excluded.revenue, ebitda=excluded.ebitda, sde=excluded.sde,
              asking_price=excluded.asking_price,
              ebitda_multiple=excluded.ebitda_multiple, sde_multiple=excluded.sde_multiple""",
            (id, int(f['fiscal_year']) if f.get('fiscal_year') else None,
             rev, ebitda, sde, ask, emx, smx))
        conn.commit(); conn.close()
        flash('Financials saved', 'success')
        return redirect(url_for('business_detail', id=id) + '#financials')

    conn.close()
    html = f"""
<h4 class="mb-4">Add / Update Financials — {b["name"]}</h4>
<div class="card shadow-sm" style="max-width:500px"><div class="card-body">
<form method="post">
  <div class="mb-3"><label class="form-label fw-bold">Fiscal Year</label>
    <input name="fiscal_year" class="form-control" type="number" value="{date.today().year - 1}"></div>
  <div class="mb-3"><label class="form-label">Revenue ($)</label>
    <input name="revenue" class="form-control" placeholder="e.g. 2500000"></div>
  <div class="mb-3"><label class="form-label">EBITDA ($)</label>
    <input name="ebitda" class="form-control" placeholder="e.g. 500000"></div>
  <div class="mb-3"><label class="form-label">SDE — Seller's Discretionary Earnings ($)</label>
    <input name="sde" class="form-control" placeholder="e.g. 600000"></div>
  <div class="mb-3"><label class="form-label">Asking Price ($)</label>
    <input name="asking_price" class="form-control" placeholder="e.g. 2000000">
    <div class="form-text">EBITDA &amp; SDE multiples are auto-calculated.</div></div>
  <button class="btn btn-success">Save Financials</button>
  <a class="btn btn-outline-secondary ms-2" href="/businesses/{id}#financials">Cancel</a>
</form></div></div>"""
    return render(html)

# ---------------------------------------------------------------------------
# Log interaction
# ---------------------------------------------------------------------------
@app.route('/businesses/<int:id>/log-interaction', methods=['POST'])
def log_interaction(id):
    f = request.form
    conn = get_conn()
    conn.execute("""INSERT INTO interactions (business_id,contact_id,interaction_type,interaction_date,summary)
                    VALUES (?,?,?,?,?)""",
                 (id, int(f['contact_id']) if f.get('contact_id') else None,
                  f.get('interaction_type'), f.get('interaction_date') or str(date.today()),
                  f.get('summary') or None))
    conn.commit(); conn.close()
    flash('Interaction logged', 'success')
    return redirect(url_for('business_detail', id=id) + '#activity')

# ---------------------------------------------------------------------------
# Link source / contact
# ---------------------------------------------------------------------------
@app.route('/businesses/<int:id>/link-source', methods=['POST'])
def link_source(id):
    f = request.form
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO business_sources (business_id,source_id,listing_url) VALUES (?,?,?)",
                 (id, f.get('source_id'), f.get('listing_url') or None))
    conn.commit(); conn.close()
    flash('Source linked', 'success')
    return redirect(url_for('business_detail', id=id) + '#contacts')

@app.route('/businesses/<int:id>/link-contact', methods=['POST'])
def link_contact(id):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO business_contacts (business_id,contact_id) VALUES (?,?)",
                 (id, request.form.get('contact_id')))
    conn.commit(); conn.close()
    flash('Contact linked', 'success')
    return redirect(url_for('business_detail', id=id) + '#contacts')

# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------
@app.route('/contacts')
def contacts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    conn.close()
    trows = ''.join(f"""<tr><td>{r["id"]}</td><td>{r["name"]}</td><td>{r["role"] or ""}</td>
      <td>{r["company"] or ""}</td><td>{r["email"] or ""}</td><td>{r["phone"] or ""}</td></tr>""" for r in rows
    ) or '<tr><td colspan=6 class="text-muted text-center">No contacts yet</td></tr>'
    html = f"""
<div class="d-flex justify-content-between align-items-center mb-3">
  <h4 class="mb-0">Contacts</h4>
  <a class="btn btn-success btn-sm" href="/contacts/add">+ Add Contact</a>
</div>
<div class="table-responsive"><table class="table table-hover bg-white rounded shadow-sm">
  <thead class="table-dark"><tr><th>ID</th><th>Name</th><th>Role</th>
    <th>Company</th><th>Email</th><th>Phone</th></tr></thead>
  <tbody>{trows}</tbody>
</table></div>"""
    return render(html)

@app.route('/contacts/add', methods=['GET','POST'])
def add_contact():
    if request.method == 'POST':
        f = request.form
        conn = get_conn()
        conn.execute("INSERT INTO contacts (name,role,company,email,phone,notes) VALUES (?,?,?,?,?,?)",
                     (f['name'], f.get('role'), f.get('company') or None,
                      f.get('email') or None, f.get('phone') or None, f.get('notes') or None))
        conn.commit(); conn.close()
        flash(f'Contact "{f["name"]}" added', 'success')
        return redirect(url_for('contacts'))
    role_opts = ''.join(f'<option value="{r}">{r.capitalize()}</option>' for r in CONTACT_ROLES)
    html = f"""
<h4 class="mb-4">Add Contact</h4>
<div class="card shadow-sm" style="max-width:500px"><div class="card-body">
<form method="post">
  <div class="mb-3"><label class="form-label fw-bold">Name *</label>
    <input name="name" class="form-control" required></div>
  <div class="mb-3"><label class="form-label fw-bold">Role</label>
    <select name="role" class="form-select">{role_opts}</select></div>
  <div class="mb-3"><label class="form-label">Company / Brokerage</label>
    <input name="company" class="form-control"></div>
  <div class="mb-3"><label class="form-label">Email</label>
    <input name="email" type="email" class="form-control"></div>
  <div class="mb-3"><label class="form-label">Phone</label>
    <input name="phone" class="form-control"></div>
  <div class="mb-3"><label class="form-label">Notes</label>
    <textarea name="notes" class="form-control" rows="2"></textarea></div>
  <button class="btn btn-success">Save Contact</button>
  <a class="btn btn-outline-secondary ms-2" href="/contacts">Cancel</a>
</form></div></div>"""
    return render(html)

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
@app.route('/sources')
def sources():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sources ORDER BY type, name").fetchall()
    conn.close()
    trows = ''.join(f"""<tr><td>{r["id"]}</td><td>{r["name"]}</td><td>{r["type"] or ""}</td>
      <td>{"<a href='"+r["website"]+"' target='_blank'>"+r["website"]+"</a>" if r["website"] else "—"}</td>
      <td>{r["notes"] or ""}</td></tr>""" for r in rows
    ) or '<tr><td colspan=5 class="text-muted text-center">No sources yet</td></tr>'
    html = f"""
<h4 class="mb-3">Sources</h4>
<div class="table-responsive"><table class="table table-hover bg-white rounded shadow-sm">
  <thead class="table-dark"><tr><th>ID</th><th>Name</th><th>Type</th><th>Website</th><th>Notes</th></tr></thead>
  <tbody>{trows}</tbody>
</table></div>"""
    return render(html)

# ---------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, port=5050)
