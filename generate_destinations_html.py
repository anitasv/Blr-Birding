#!/usr/bin/env python3
import os
import re
import json
import html
from datetime import date
from parse_destinations import parse_markdown_tables

# ---------------------------------------------------------------------------
# Timetable parser
# ---------------------------------------------------------------------------

def parse_timetable(path="timetable.md"):
    """Parse timetable.md and return two lists:
      scheduled  – list of dicts with keys: month, year, destination, why, focus, slug
      unscheduled – list of destination name strings (remaining/not picked)
    Also returns notes – list of note strings from the ## Notes section.
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    scheduled = []
    unscheduled = []
    notes = []

    # --- main month-by-month table ---
    plan_match = re.search(
        r'## Month-by-month plan\s*\n.*?\n\|---.*?\n(.*?)(?=\n##|\Z)',
        text, re.DOTALL
    )
    if plan_match:
        for line in plan_match.group(1).splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) < 4:
                continue
            month_str, dest_str, why_str, focus_str = parts[0], parts[1], parts[2], parts[3]
            # Parse "Oct 2026"
            m = re.match(r'(\w+)\s+(\d{4})', month_str)
            if not m:
                continue
            month_name, year = m.group(1), int(m.group(2))
            if dest_str.lower().startswith("skip"):
                scheduled.append({
                    "month": month_name, "year": year,
                    "destination": None, "why": why_str, "focus": focus_str, "slug": None
                })
            else:
                # Build a slug from destination name — try to match a known destination file
                scheduled.append({
                    "month": month_name, "year": year,
                    "destination": dest_str, "why": why_str, "focus": focus_str, "slug": None
                })

    # --- remaining/unscheduled destinations ---
    remaining_match = re.search(
        r'## Remaining useful destinations.*?\n\n(.*?)(?=\n##|\Z)',
        text, re.DOTALL
    )
    if remaining_match:
        for line in remaining_match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- "):
                unscheduled.append(line[2:].strip())

    # --- notes section ---
    notes_match = re.search(
        r'## Notes\s*\n\n(.*?)(?=\n##|\Z)',
        text, re.DOTALL
    )
    if notes_match:
        for line in notes_match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- "):
                notes.append(line[2:].strip())

    return scheduled, unscheduled, notes


def assign_timetable_slugs(scheduled, destinations):
    """Try to match each scheduled destination to a known destination slug
    (filename without .html) so the JS can link to the detail page."""
    def word_overlap(a, b):
        """Count significant words shared between two strings."""
        stop = {'/', '-', 'and', 'the', 'of', 'in', 'a'}
        wa = set(re.sub(r'[^a-z0-9 ]', ' ', a.lower()).split()) - stop
        wb = set(re.sub(r'[^a-z0-9 ]', ' ', b.lower()).split()) - stop
        return len(wa & wb)

    def best_slug(dest_str):
        if not dest_str:
            return None
        dest_lower = dest_str.lower()
        # 1. Direct substring match either way
        for d in destinations:
            name_lower = d["name"].lower()
            if name_lower in dest_lower or dest_lower in name_lower:
                return get_destination_filename(d).replace(".html", "")
        # 2. Word-overlap match (pick best if ≥ 2 words overlap)
        best_d, best_score = None, 1
        for d in destinations:
            score = word_overlap(dest_str, d["name"])
            if score > best_score:
                best_score = score
                best_d = d
        if best_d:
            return get_destination_filename(best_d).replace(".html", "")
        return None

    for entry in scheduled:
        entry["slug"] = best_slug(entry["destination"])
    return scheduled

DETAILS_DIR = "destination_details"

# ── Site-wide SEO constants ──────────────────────────────────────────────────
SITE_URL   = "https://blrbirding.com"
GA_ID      = "G-WRCDXDCFF0"
SITE_NAME  = "India Birding & Wildlife Photography from Bengaluru"
# ────────────────────────────────────────────────────────────────────────────

# Slugs are generated from destination name (+ state if needed to prevent duplicates)
def slugify(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '_', text)
    return text.strip('_')

def get_destination_filename(dest):
    base = slugify(dest["name"])
    if dest["state"]:
        base = f"{base}_{slugify(dest['state'])}"
    return f"{base}.html"

def get_destination_detail_filename(dest):
    return get_destination_filename(dest).replace(".html", ".md")

def get_destination_detail_path(dest):
    return os.path.join(DETAILS_DIR, get_destination_detail_filename(dest))

def ensure_destination_detail_file(dest):
    os.makedirs(DETAILS_DIR, exist_ok=True)
    detail_path = get_destination_detail_path(dest)
    if not os.path.exists(detail_path):
        display_name = f"{dest['name']}, {dest['state']}" if dest["state"] else dest["name"]
        generated_page = f"output/destinations/{get_destination_filename(dest)}"
        starter = f"""<!--
Add custom content for {display_name} here.
This content appears only on {generated_page}.

Markdown supported: headings (#, ##, ###), bullet lists (- item), numbered lists (1. item), paragraphs, **bold**, *italic*, and links [text](url).
-->
"""
        with open(detail_path, "w", encoding="utf-8") as f:
            f.write(starter)
    return detail_path

def has_visible_markdown_content(markdown_text):
    without_comments = re.sub(r'<!--.*?-->', '', markdown_text, flags=re.DOTALL).strip()
    return bool(without_comments)

def render_inline_markdown(text):
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
    return text

def markdown_to_html(markdown_text):
    markdown_text = re.sub(r'<!--.*?-->', '', markdown_text, flags=re.DOTALL).strip()
    if not markdown_text:
        return ""

    html_lines = []
    paragraph_lines = []
    list_type = None

    def flush_paragraph():
        nonlocal paragraph_lines
        if paragraph_lines:
            paragraph = " ".join(paragraph_lines).strip()
            html_lines.append(f"<p>{render_inline_markdown(paragraph)}</p>")
            paragraph_lines = []

    def close_list():
        nonlocal list_type
        if list_type:
            html_lines.append(f"</{list_type}>")
            list_type = None

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            close_list()
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        bullet_match = re.match(r'^[-*]\s+(.+)$', line)
        numbered_match = re.match(r'^\d+\.\s+(.+)$', line)

        if heading_match:
            flush_paragraph()
            close_list()
            level = min(len(heading_match.group(1)) + 1, 6)
            html_lines.append(f"<h{level}>{render_inline_markdown(heading_match.group(2))}</h{level}>")
        elif bullet_match:
            flush_paragraph()
            if list_type != "ul":
                close_list()
                html_lines.append("<ul>")
                list_type = "ul"
            html_lines.append(f"<li>{render_inline_markdown(bullet_match.group(1))}</li>")
        elif numbered_match:
            flush_paragraph()
            if list_type != "ol":
                close_list()
                html_lines.append("<ol>")
                list_type = "ol"
            html_lines.append(f"<li>{render_inline_markdown(numbered_match.group(1))}</li>")
        else:
            close_list()
            paragraph_lines.append(line)

    flush_paragraph()
    close_list()
    return "\n".join(html_lines)

def read_destination_detail_html(dest):
    detail_path = ensure_destination_detail_file(dest)
    with open(detail_path, "r", encoding="utf-8") as f:
        markdown_text = f.read()

    if not has_visible_markdown_content(markdown_text):
        return ""

    rendered = markdown_to_html(markdown_text)
    if not rendered:
        return ""

    return f"""
        <div class="card additional-details">
            {rendered}
        </div>
"""

def generate_html():
    os.makedirs("output/destinations", exist_ok=True)
    os.makedirs("output/resources", exist_ok=True)
    
    # CSS styles for beautiful, modern looking HTML
    styles_css = """:root {
    --primary: #2d5a27;
    --primary-light: #e8f0e6;
    --accent: #d4af37;
    --dark: #222;
    --light: #f9f9f9;
    --border: #ddd;
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.6;
    color: var(--dark);
    background-color: #f4f6f4;
    margin: 0;
    padding: 0;
}
.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}
header {
    background-color: var(--primary);
    color: white;
    padding: 40px 20px;
    text-align: center;
    border-bottom: 5px solid var(--accent);
}
header h1 {
    margin: 0 0 10px 0;
    font-size: 2.5em;
}
header p {
    margin: 0;
    font-size: 1.1em;
    opacity: 0.9;
}
.card {
    background: white;
    border-radius: 8px;
    box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    padding: 25px;
    margin-bottom: 25px;
}
h2 {
    color: var(--primary);
    border-bottom: 2px solid var(--primary-light);
    padding-bottom: 8px;
    margin-top: 0;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 15px;
}
th, td {
    padding: 12px 15px;
    text-align: left;
    border-bottom: 1px solid var(--border);
}
th {
    background-color: var(--primary-light);
    color: var(--primary);
    font-weight: 600;
}
th.sortable {
    cursor: pointer;
    user-select: none;
    position: relative;
    padding-right: 25px;
}
th.sortable:hover {
    background-color: #d8ebd4;
}
th.sortable::after {
    content: ' ↕';
    font-size: 0.8em;
    color: #999;
    position: absolute;
    right: 8px;
}
th.sortable.asc::after {
    content: ' ▲';
    color: var(--primary);
}
th.sortable.desc::after {
    content: ' ▼';
    color: var(--primary);
}
tr:hover {
    background-color: #fcfdfc;
}
.rating {
    color: var(--accent);
    font-weight: bold;
}
.badge {
    display: inline-block;
    background-color: var(--primary-light);
    color: var(--primary);
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 0.85em;
    font-weight: 500;
}
a {
    color: var(--primary);
    text-decoration: none;
    font-weight: 500;
}
a:hover {
    text-decoration: underline;
}
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 20px;
    margin-top: 15px;
}
.ranking-card {
    background: #fff;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 15px;
}
.ranking-card h3 {
    margin-top: 0;
    color: var(--primary);
    font-size: 1.1em;
    border-bottom: 1px solid var(--border);
    padding-bottom: 5px;
}
.ranking-list {
    padding-left: 20px;
    margin: 10px 0 0 0;
}
.ranking-list li {
    margin-bottom: 6px;
}
.notes-list {
    padding-left: 20px;
}
.notes-list li {
    margin-bottom: 10px;
}
.back-btn {
    display: inline-block;
    margin-bottom: 20px;
    background-color: var(--primary);
    color: white;
    padding: 10px 20px;
    border-radius: 4px;
    font-weight: bold;
}
.back-btn:hover {
    background-color: #1e3d1a;
    text-decoration: none;
}
.details-table th {
    width: 30%;
}
.additional-details h2:first-child,
.additional-details h3:first-child,
.additional-details p:first-child {
    margin-top: 0;
}
.additional-details ul,
.additional-details ol {
    padding-left: 24px;
}
.additional-details li {
    margin-bottom: 8px;
}

/* ── Destination selection checkboxes ──────────────────────────────────── */
.sel-col {
    width: 42px;
    text-align: center;
    padding: 8px 6px;
}
.sel-all-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    font-size: 0.82em;
    font-weight: 600;
    color: var(--primary);
    white-space: nowrap;
}
.dest-cb,
.sel-all-cb {
    width: 15px;
    height: 15px;
    cursor: pointer;
    accent-color: var(--primary);
}
tr.dest-deselected td {
    opacity: 0.38;
}
tr.dest-deselected td a {
    pointer-events: none;
}

/* ── Section collapse ───────────────────────────────────────────────────── */
.section-heading {
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: default;
    margin-bottom: 0;
}
.collapse-btn {
    flex-shrink: 0;
    background: none;
    border: none;
    padding: 0 4px;
    font-size: 1.15em;
    line-height: 1;
    color: var(--primary);
    cursor: pointer;
    transition: transform 0.2s ease;
    transform-origin: center;
}
.collapse-btn[aria-expanded="false"] {
    transform: rotate(-90deg);
}
.section-body {
    overflow: hidden;
    transition: max-height 0.28s ease, opacity 0.22s ease;
    max-height: 4000px;   /* large enough for any table */
    opacity: 1;
}
.section-body.collapsed {
    max-height: 0;
    opacity: 0;
}
.section-card.is-collapsed {
    padding-bottom: 16px;
}

/* ── Timetable ──────────────────────────────────────────────────────────── */
.timetable-controls {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 24px;
    padding: 16px 20px;
    background: var(--primary-light);
    border-radius: 6px;
}
.timetable-controls label {
    font-weight: 600;
    color: var(--primary);
    font-size: 1em;
}
.timetable-controls input[type="month"] {
    padding: 8px 12px;
    border: 2px solid var(--primary);
    border-radius: 4px;
    font-size: 1em;
    color: var(--dark);
    background: white;
    cursor: pointer;
}
.timetable-controls input[type="month"]:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(212,175,55,0.2);
}
.timetable-controls .tt-hint {
    font-size: 0.88em;
    color: #666;
}
#timetable-table-wrap {
    overflow-x: auto;
}
#timetable-table {
    margin-top: 0;
}
#timetable-table thead th {
    white-space: nowrap;
}
.tt-row-skip td {
    color: #999;
    font-style: italic;
    background: #fafafa;
}
.tt-row-skip .tt-month-cell {
    color: #bbb;
}
.tt-month-cell {
    white-space: nowrap;
    font-weight: 600;
    color: var(--primary);
}
.tt-dest-cell a {
    font-weight: 600;
}
.tt-dest-cell .tt-no-dest {
    color: #bbb;
}
.tt-focus-cell {
    font-size: 0.9em;
    color: #555;
}
.tt-unscheduled {
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
}
.tt-unscheduled h4 {
    margin: 0 0 8px 0;
    color: #777;
    font-size: 0.95em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.tt-unscheduled ul {
    margin: 0;
    padding-left: 20px;
    color: #888;
    font-size: 0.9em;
}
.tt-unscheduled ul li {
    margin-bottom: 4px;
}
.tt-notes {
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    font-size: 0.88em;
    color: #666;
}
.tt-notes ul {
    margin: 6px 0 0 0;
    padding-left: 20px;
}
.tt-notes ul li {
    margin-bottom: 5px;
}
.tt-count-badge {
    display: inline-block;
    background: var(--primary);
    color: white;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 0.82em;
    font-weight: 600;
    margin-left: 8px;
    vertical-align: middle;
}
"""

    sort_js = """document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('th.sortable').forEach(header => {
        header.addEventListener('click', () => {
            const table = header.closest('table');
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));
            const index = Array.from(header.parentNode.children).indexOf(header);
            const isAsc = header.classList.contains('asc');
            
            // Clear all sort classes in this table's headers
            table.querySelectorAll('th.sortable').forEach(h => {
                h.classList.remove('asc', 'desc');
            });
            
            if (isAsc) {
                header.classList.add('desc');
            } else {
                header.classList.add('asc');
            }
            
            const direction = isAsc ? -1 : 1;
            
            rows.sort((a, b) => {
                const cellA = a.children[index].textContent.trim();
                const cellB = b.children[index].textContent.trim();
                
                // Extract rating number from text like "5★" or just a number
                const valA = parseInt(cellA) || 0;
                const valB = parseInt(cellB) || 0;
                
                if (valA !== valB) {
                    return (valA - valB) * direction;
                }
                
                // Secondary sort: alphabetical by place name (column index 1, after checkbox)
                const nameA = a.children[1].textContent.trim().toLowerCase();
                const nameB = b.children[1].textContent.trim().toLowerCase();
                return nameA.localeCompare(nameB) * direction;
            });
            
            // Re-append rows in new order
            rows.forEach(row => tbody.appendChild(row));
        });
    });
});
"""

    # Write separate CSS and JS files
    with open("output/resources/styles.css", "w", encoding="utf-8") as f:
        f.write(styles_css)
        
    with open("output/resources/sort.js", "w", encoding="utf-8") as f:
        f.write(sort_js)

    timetable_js = r"""/* timetable.js – greedy seasonal schedule generator */
(function () {
  'use strict';

  const MONTH_NAMES = [
    'Jan','Feb','Mar','Apr','May','Jun',
    'Jul','Aug','Sep','Oct','Nov','Dec'
  ];

  /* ---------- greedy scheduler ----------
   *
   * destCatalog: array of {slug, name, state, bestMonths:[1-12], bestTime,
   *                         focus, birding, wildlife, score}
   * selectedSet: Set of slugs currently checked
   * startMonth:  1-12  (the calendar month the user chose to start)
   * startYear:   e.g. 2026
   *
   * For each month in sequence, pick the highest-score unused destination
   * whose bestMonths includes that calendar month.
   * Runs until all selected destinations are placed (or 48-month cap).
   * -------------------------------------------------------------------- */
  function buildSchedule(catalog, selectedSet, startMonth, startYear) {
    const pool = catalog.filter(d => selectedSet.has(d.slug));
    const used   = new Set();
    const result = [];
    let month = startMonth;
    let year  = startYear;
    let steps = 0;

    while (used.size < pool.length && steps < 48) {
      const candidates = pool.filter(d =>
        !used.has(d.slug) && d.bestMonths.includes(month)
      );

      if (candidates.length === 0) {
        result.push({ year, monthNum: month, dest: null });
      } else {
        candidates.sort((a, b) =>
          b.score !== a.score ? b.score - a.score : a.slug.localeCompare(b.slug)
        );
        const pick = candidates[0];
        used.add(pick.slug);
        result.push({ year, monthNum: month, dest: pick });
      }

      month++;
      if (month > 12) { month = 1; year++; }
      steps++;
    }
    return result;
  }

  /* ---------- helpers ---------- */

  function escHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function selectedSlugs() {
    return new Set(
      Array.from(document.querySelectorAll('.dest-cb:checked'))
           .map(cb => cb.dataset.slug)
    );
  }

  /* ---------- rendering ---------- */

  function renderTable(catalog, startMonth, startYear, selected) {
    const schedule = buildSchedule(catalog, selected, startMonth, startYear);
    const tbody = document.getElementById('timetable-tbody');
    if (!tbody) return;

    const rows = schedule.map(entry => {
      const monthLabel = MONTH_NAMES[entry.monthNum - 1] + ' ' + entry.year;

      if (!entry.dest) {
        return `<tr class="tt-row-skip">
          <td class="tt-month-cell">${escHtml(monthLabel)}</td>
          <td class="tt-dest-cell"><span class="tt-no-dest">—</span></td>
          <td>No unvisited destination has its best window in this month</td>
          <td class="tt-focus-cell">—</td>
        </tr>`;
      }

      const d = entry.dest;
      const label = d.state ? `${d.name}, ${d.state}` : d.name;
      const destHtml = `<a href="destinations/${escHtml(d.slug)}.html">${escHtml(label)}</a>`;

      return `<tr>
        <td class="tt-month-cell">${escHtml(monthLabel)}</td>
        <td class="tt-dest-cell">${destHtml}</td>
        <td>${escHtml(d.bestTime)}</td>
        <td class="tt-focus-cell">${escHtml(d.focus)}</td>
      </tr>`;
    });

    tbody.innerHTML = rows.join('\n');

    const badge = document.getElementById('tt-trip-count');
    if (badge) {
      const tripCount = schedule.filter(e => e.dest !== null).length;
      badge.textContent = tripCount + ' trip' + (tripCount !== 1 ? 's' : '');
    }
  }

  function renderUnscheduled(unscheduled) {
    const ul = document.getElementById('tt-unscheduled-list');
    if (!ul) return;
    if (!unscheduled.length) { ul.parentElement.style.display = 'none'; return; }
    ul.innerHTML = unscheduled.map(item => {
      const text = escHtml(item.name);
      return item.slug
        ? `<li><a href="destinations/${escHtml(item.slug)}.html">${text}</a></li>`
        : `<li>${text}</li>`;
    }).join('\n');
  }

  function renderNotes(notes) {
    const ul = document.getElementById('tt-notes-list');
    if (!ul) return;
    if (!notes.length) { ul.parentElement.style.display = 'none'; return; }
    ul.innerHTML = notes.map(n => `<li>${escHtml(n)}</li>`).join('\n');
  }

  /* ---------- date picker ---------- */

  function defaultStartValue() {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth() + 1;
    return `${y}-${String(m).padStart(2, '0')}`;
  }

  /* ---------- collapse ---------- */

  function wireCollapse() {
    document.querySelectorAll('.collapse-btn').forEach(btn => {
      btn.addEventListener('click', function () {
        const section = this.dataset.section;
        const body = document.getElementById('section-body-' + section);
        const card = document.getElementById('section-' + section);
        if (!body) return;
        const isExpanded = this.getAttribute('aria-expanded') === 'true';
        this.setAttribute('aria-expanded', isExpanded ? 'false' : 'true');
        body.classList.toggle('collapsed', isExpanded);
        if (card) card.classList.toggle('is-collapsed', isExpanded);
      });
    });
  }

  /* ---------- checkboxes ---------- */

  function applyDestCb(cb, checked) {
    cb.checked = checked;
    const row = cb.closest('tr');
    if (row) row.classList.toggle('dest-deselected', !checked);
  }

  function syncSectionHeader(section) {
    const allCb = document.querySelector(`.sel-all-cb[data-section="${section}"]`);
    if (!allCb) return;
    const cbs = Array.from(document.querySelectorAll(`.dest-cb[data-section="${section}"]`));
    const n   = cbs.filter(c => c.checked).length;
    allCb.checked       = n === cbs.length;
    allCb.indeterminate = n > 0 && n < cbs.length;
  }

  function wireCheckboxes(onchange) {
    document.querySelectorAll('.sel-all-cb').forEach(allCb => {
      allCb.addEventListener('change', function () {
        const section = this.dataset.section;
        document.querySelectorAll(`.dest-cb[data-section="${section}"]`).forEach(cb => {
          applyDestCb(cb, this.checked);
        });
        this.indeterminate = false;
        onchange();
      });
    });

    document.querySelectorAll('.dest-cb').forEach(cb => {
      cb.addEventListener('change', function () {
        applyDestCb(this, this.checked);
        syncSectionHeader(this.dataset.section);
        onchange();
      });
    });
  }

  /* ---------- boot ---------- */

  document.addEventListener('DOMContentLoaded', function () {
    const data = window.__TIMETABLE__;
    if (!data) return;

    const { destCatalog, unscheduled, notes } = data;

    const input = document.getElementById('tt-start');
    if (!input) return;

    input.value = defaultStartValue();

    function update() {
      const val = input.value;
      if (!val) return;
      const [y, m] = val.split('-').map(Number);
      renderTable(destCatalog, m, y, selectedSlugs());
    }

    renderUnscheduled(unscheduled);
    renderNotes(notes);
    wireCollapse();
    wireCheckboxes(update);
    update();

    input.addEventListener('change', update);
    input.addEventListener('input',  update);
  });

}());
"""

    with open("output/resources/timetable.js", "w", encoding="utf-8") as f:
        f.write(timetable_js)

    # Parse the markdown tables
    destinations = parse_markdown_tables("destinations.md")

    # Parse timetable
    scheduled, unscheduled_dests, timetable_notes = parse_timetable("timetable.md")
    scheduled = assign_timetable_slugs(scheduled, destinations)
    
    # Read destinations.md to extract sections like title, practical rankings, and notes
    with open("destinations.md", "r", encoding="utf-8") as f:
        md_content = f.read()
        
    # Extract Title & Legend
    title_match = re.search(r'^#\s+(.*)', md_content)
    title = title_match.group(1).strip() if title_match else "Photography Destinations"
    
    legend_match = re.search(r'Legend:\s*(.*)', md_content)
    legend = legend_match.group(1).strip() if legend_match else ""
    # Convert bold markers to html inside legend
    legend_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', legend)
    
    # Parse notes section
    notes_match = re.search(r'## Notes\s*\n\n(.*?)(?=\n\n##|\Z)', md_content, re.DOTALL)
    notes_list = []
    if notes_match:
        for line in notes_match.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith("- "):
                note_text = line[2:].strip()
                # bold conversion
                note_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', note_text)
                notes_list.append(note_text)

    # Parse rankings
    rankings_section = re.search(r'## Practical ranking from Bengaluru\s*\n\n(.*?)(?=\n\n## Notes|\Z)', md_content, re.DOTALL)
    rankings_data = []
    if rankings_section:
        subsections = re.split(r'###\s+', rankings_section.group(1))
        for sub in subsections:
            sub = sub.strip()
            if not sub:
                continue
            lines = sub.split("\n")
            sub_title = lines[0].strip()
            items = []
            for l in lines[1:]:
                l = l.strip()
                if l and re.match(r'^\d+\.\s+', l):
                    item_name = re.sub(r'^\d+\.\s+', '', l).strip()
                    items.append(item_name)
            rankings_data.append({
                "title": sub_title,
                "items": items
            })

    # Group destinations by section
    sections = {}
    for d in destinations:
        sect = d["section"]
        if sect not in sections:
            sections[sect] = []
        sections[sect].append(d)

    # Google Maps place URLs keyed by destination filename (without .html)
    MAPS_URLS = {
        # Karnataka
        "kabini_nagarhole_karnataka":               "https://www.google.com/maps/search/?api=1&query=Kabini+Wildlife+Sanctuary+Karnataka",
        "bandipur_mudumalai_katn":                  "https://www.google.com/maps/search/?api=1&query=Bandipur+National+Park+Karnataka",
        "bhadra_tiger_reserve_karnataka":           "https://www.google.com/maps/search/?api=1&query=Bhadra+Wildlife+Sanctuary+Karnataka",
        "dandeli_kali_tiger_reserve_karnataka":     "https://www.google.com/maps/search/?api=1&query=Dandeli+Wildlife+Sanctuary+Karnataka",
        "agumbe_someshwara_kudremukh_belt":         "https://www.google.com/maps/search/?api=1&query=Kudremukh+National+Park+Karnataka",
        "hampi_daroji_bear_sanctuary_region":       "https://www.google.com/maps/search/?api=1&query=Hampi+Karnataka",
        "ranganathittu_karnataka":                  "https://www.google.com/maps/search/?api=1&query=Ranganathittu+Bird+Sanctuary+Karnataka",
        # Kerala
        "thattekad_kerala":                         "https://www.google.com/maps/search/?api=1&query=Thattekad+Bird+Sanctuary+Kerala",
        "munnar_eravikulam_chinnar_kerala":         "https://www.google.com/maps/search/?api=1&query=Eravikulam+National+Park+Kerala",
        "valparai_anamalai_tamil_nadu":             "https://www.google.com/maps/search/?api=1&query=Valparai+Anamalai+Tiger+Reserve+Tamil+Nadu",
        "kumarakom_vembanad_kerala":                "https://www.google.com/maps/search/?api=1&query=Kumarakom+Bird+Sanctuary+Kerala",
        "wayanad_kerala":                           "https://www.google.com/maps/search/?api=1&query=Wayanad+Wildlife+Sanctuary+Kerala",
        "periyar_kerala":                           "https://www.google.com/maps/search/?api=1&query=Periyar+National+Park+Kerala",
        # Tamil Nadu
        "vedanthangal_pulicat_tamil_nadu":          "https://www.google.com/maps/search/?api=1&query=Vedanthangal+Bird+Sanctuary+Tamil+Nadu",
        # Rajasthan
        "ranthambore_rajasthan":                    "https://www.google.com/maps/search/?api=1&query=Ranthambore+National+Park+Rajasthan",
        "keoladeo_bharatpur_rajasthan":             "https://www.google.com/maps/search/?api=1&query=Keoladeo+National+Park+Bharatpur+Rajasthan",
        "tal_chhapar_rajasthan":                    "https://www.google.com/maps/search/?api=1&query=Tal+Chhapar+Wildlife+Sanctuary+Rajasthan",
        "desert_national_park_rajasthan":           "https://www.google.com/maps/search/?api=1&query=Desert+National+Park+Jaisalmer+Rajasthan",
        # Gujarat
        "little_rann_of_kutch_gujarat":             "https://www.google.com/maps/search/?api=1&query=Little+Rann+of+Kutch+Gujarat",
        "banni_greater_rann_kutch_gujarat":         "https://www.google.com/maps/search/?api=1&query=Banni+Grasslands+Kutch+Gujarat",
        "gir_gujarat":                              "https://www.google.com/maps/search/?api=1&query=Gir+National+Park+Gujarat",
        "velavadar_gujarat":                        "https://www.google.com/maps/search/?api=1&query=Velavadar+National+Park+Gujarat",
        # Madhya Pradesh / Maharashtra
        "kanha_madhya_pradesh":                     "https://www.google.com/maps/search/?api=1&query=Kanha+National+Park+Madhya+Pradesh",
        "bandhavgarh_madhya_pradesh":               "https://www.google.com/maps/search/?api=1&query=Bandhavgarh+National+Park+Madhya+Pradesh",
        "pench_mpmaharashtra":                      "https://www.google.com/maps/search/?api=1&query=Pench+National+Park+Madhya+Pradesh",
        "tadoba_maharashtra":                       "https://www.google.com/maps/search/?api=1&query=Tadoba+Andhari+Tiger+Reserve+Maharashtra",
        "satpura_madhya_pradesh":                   "https://www.google.com/maps/search/?api=1&query=Satpura+National+Park+Madhya+Pradesh",
        "panna_madhya_pradesh":                     "https://www.google.com/maps/search/?api=1&query=Panna+National+Park+Madhya+Pradesh",
        # Assam / Northeast
        "kaziranga_assam":                          "https://www.google.com/maps/search/?api=1&query=Kaziranga+National+Park+Assam",
        "eaglenest_arunachal_pradesh":              "https://www.google.com/maps/search/?api=1&query=Eaglenest+Wildlife+Sanctuary+Arunachal+Pradesh",
        "mishmi_hills_dibang_arunachal":            "https://www.google.com/maps/search/?api=1&query=Dibang+Valley+Arunachal+Pradesh",
        "namdapha_arunachal":                       "https://www.google.com/maps/search/?api=1&query=Namdapha+National+Park+Arunachal+Pradesh",
        # East / Odisha / West Bengal
        "sundarbans_west_bengal":                   "https://www.google.com/maps/search/?api=1&query=Sundarbans+National+Park+West+Bengal",
        "mangalajodi_chilika_odisha":               "https://www.google.com/maps/search/?api=1&query=Mangalajodi+Chilika+Lake+Odisha",
        # Uttarakhand
        "pangotsattalcorbett_uttarakhand":          "https://www.google.com/maps/search/?api=1&query=Jim+Corbett+National+Park+Uttarakhand",
        "chopta_mandal_munsiyari_uttarakhand":      "https://www.google.com/maps/search/?api=1&query=Chopta+Uttarakhand",
        # Himachal / Ladakh
        "hemis_ladakh":                             "https://www.google.com/maps/search/?api=1&query=Hemis+National+Park+Ladakh",
        "great_himalayan_national_park_himachal":   "https://www.google.com/maps/search/?api=1&query=Great+Himalayan+National+Park+Himachal+Pradesh",
    }

    # 1. Generate Individual Destination Detail HTML Files
    for d in destinations:
        filename = get_destination_filename(d)
        filepath = os.path.join("output/destinations", filename)
        additional_details_html = read_destination_detail_html(d)

        # Google Maps link
        slug = filename.replace(".html", "")
        maps_url = MAPS_URLS.get(slug)
        if maps_url:
            maps_row = f"""
                <tr>
                    <th>Location</th>
                    <td><a href="{maps_url}" target="_blank" rel="noopener">Open in Google Maps ↗</a></td>
                </tr>"""
        else:
            maps_row = ""

        # Per-page SEO helpers
        page_url      = f"{SITE_URL}/destinations/{filename}"
        page_title    = f"{d['name']}{', ' + d['state'] if d['state'] else ''} – Birding & Wildlife Photography Guide"
        page_desc     = f"Plan a birding and wildlife photography trip to {d['name']}{', ' + d['state'] if d['state'] else ''}. {d['expect'][:120]}..."
        page_desc_esc = html.escape(page_desc)

        # JSON-LD: BreadcrumbList + TouristAttraction
        jsonld = json.dumps({
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "Home",         "item": f"{SITE_URL}/"},
                        {"@type": "ListItem", "position": 2, "name": d["name"],      "item": page_url}
                    ]
                },
                {
                    "@type": "TouristAttraction",
                    "name": f"{d['name']}{', ' + d['state'] if d['state'] else ''}",
                    "description": d["expect"],
                    "url": page_url,
                    "touristType": ["Birding", "Wildlife Photography", "Nature Tourism"],
                    "isAccessibleForFree": False
                }
            ]
        }, indent=2)

        ga_snippet = f"""<!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', '{GA_ID}');
    </script>"""

        # Link map/index back to the main file
        dest_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>

    <!-- SEO -->
    <meta name="description" content="{page_desc_esc}">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{page_url}">

    <!-- Open Graph -->
    <meta property="og:type"        content="article">
    <meta property="og:site_name"   content="{SITE_NAME}">
    <meta property="og:title"       content="{html.escape(page_title)}">
    <meta property="og:description" content="{page_desc_esc}">
    <meta property="og:url"         content="{page_url}">

    <!-- Twitter Card -->
    <meta name="twitter:card"        content="summary">
    <meta name="twitter:title"       content="{html.escape(page_title)}">
    <meta name="twitter:description" content="{page_desc_esc}">

    <!-- Structured data -->
    <script type="application/ld+json">
{jsonld}
    </script>

    {ga_snippet}
    <link rel="stylesheet" href="../resources/styles.css">
</head>
<body>
    <div class="container" style="margin-top: 40px; max-width: 800px;">
        <a href="../" class="back-btn">← Back to Destinations List</a>
        
        <div class="card">
            <h1>{d['name']} {f'<span style="font-weight: normal; font-size: 0.6em; color: #666;">({d["state"]})</span>' if d['state'] else ''}</h1>
            <p style="font-size: 1.1em; color: #555; font-style: italic;">Category: {d['section']}</p>
            
            <table class="details-table">
                <tr>
                    <th>Best Time & Weather</th>
                    <td>{d['best_time']}</td>
                </tr>
                <tr>
                    <th>Ease of Getting There</th>
                    <td><span class="rating">{d['ease_get']}</span></td>
                </tr>
                <tr>
                    <th>Ease of Stay</th>
                    <td><span class="rating">{d['ease_stay']}</span></td>
                </tr>
                <tr>
                    <th>Transit from Bengaluru</th>
                    <td>{d['transit']}</td>
                </tr>
                <tr>
                    <th>What to Expect</th>
                    <td>{d['expect']}</td>
                </tr>
                <tr>
                    <th>Birding Rating</th>
                    <td><span class="rating">{d['birding']}</span></td>
                </tr>
                <tr>
                    <th>Wildlife Rating</th>
                    <td><span class="rating">{d['wildlife']}</span></td>
                </tr>{maps_row}
            </table>
        </div>
{additional_details_html}
    </div>
</body>
</html>
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(dest_html)

    # 2. Generate Main destinations.html File
    index_url   = f"{SITE_URL}/"
    index_desc  = ("Complete guide to India's best birding and wildlife photography destinations, "
                   "rated by ease of access, birding quality, and wildlife sightings. "
                   "Planned from Bengaluru.")
    index_jsonld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "name": SITE_NAME,
                "url": f"{SITE_URL}/"
            },
            {
                "@type": "ItemList",
                "name": "India Birding & Wildlife Photography Destinations",
                "url": index_url,
                "numberOfItems": len(destinations),
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": i + 1,
                        "name": f"{d['name']}{', ' + d['state'] if d['state'] else ''}",
                        "url": f"{SITE_URL}/destinations/{get_destination_filename(d)}"
                    }
                    for i, d in enumerate(destinations)
                ]
            }
        ]
    }, indent=2)

    index_ga_snippet = f"""<!-- Google tag (gtag.js) -->
    <script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', '{GA_ID}');
    </script>"""

    main_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>

    <!-- SEO -->
    <meta name="description" content="{html.escape(index_desc)}">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{index_url}">
    <link rel="alternate" hreflang="en" href="{index_url}">

    <!-- Open Graph -->
    <meta property="og:type"        content="website">
    <meta property="og:site_name"   content="{SITE_NAME}">
    <meta property="og:title"       content="{html.escape(title)}">
    <meta property="og:description" content="{html.escape(index_desc)}">
    <meta property="og:url"         content="{index_url}">

    <!-- Twitter Card -->
    <meta name="twitter:card"        content="summary">
    <meta name="twitter:title"       content="{html.escape(title)}">
    <meta name="twitter:description" content="{html.escape(index_desc)}">

    <!-- Structured data -->
    <script type="application/ld+json">
{index_jsonld}
    </script>

    {index_ga_snippet}
    <link rel="stylesheet" href="resources/styles.css">
</head>
<body>
    <header>
        <div class="container">
            <h1>{title}</h1>
            <p>{legend_html}</p>
        </div>
    </header>
    
    <div class="container">
"""

    # ── Timetable section (top) ──────────────────────────────────────────────
    # Parse best months from each destination's best_time field.
    # "Oct–May" → [10,11,12,1,2,3,4,5]   "Jun–Sep" → [6,7,8,9]
    # Also handles "Nov–Feb; ..." and "Dec–Apr; ..." with semicolons, multiple ranges.
    MONTH_NUM = {
        "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
        "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    }

    def parse_best_months(best_time_str):
        """Return a sorted list of month numbers (1-12) from a best_time string."""
        # strip everything after ; or , for the primary window
        primary = re.split(r'[;,]', best_time_str)[0].strip()
        months = set()
        # find all "Mon–Mon" or "Mon-Mon" patterns
        for m in re.finditer(r'([A-Za-z]{3})\s*[–—-]\s*([A-Za-z]{3})', primary):
            start_abbr = m.group(1).lower()[:3]
            end_abbr   = m.group(2).lower()[:3]
            s = MONTH_NUM.get(start_abbr)
            e = MONTH_NUM.get(end_abbr)
            if s and e:
                if s <= e:
                    for mn in range(s, e + 1):
                        months.add(mn)
                else:  # wraps year e.g. Oct–May
                    for mn in list(range(s, 13)) + list(range(1, e + 1)):
                        months.add(mn)
        # also pick up standalone month names not part of a range
        for m in re.finditer(r'\b([A-Za-z]{3})\b', primary):
            abbr = m.group(1).lower()[:3]
            if abbr in MONTH_NUM:
                months.add(MONTH_NUM[abbr])
        return sorted(months) if months else list(range(1, 13))

    def parse_rating(rating_str):
        """Extract integer from '4★' → 4, '5★ / 3★' → first value."""
        m = re.search(r'(\d)', str(rating_str))
        return int(m.group(1)) if m else 0

    # Build destination catalog for JS
    js_dest_catalog = []
    for d in destinations:
        slug = get_destination_filename(d).replace(".html", "")
        best_months = parse_best_months(d["best_time"])
        birding_score  = parse_rating(d["birding"])
        wildlife_score = parse_rating(d["wildlife"])
        js_dest_catalog.append({
            "slug":     slug,
            "name":     d["name"],
            "state":    d["state"] or "",
            "bestTime": d["best_time"].split(";")[0].strip(),
            "bestMonths": best_months,
            "focus":    d["expect"],
            "birding":  birding_score,
            "wildlife": wildlife_score,
            "score":    birding_score + wildlife_score,
        })

    js_unscheduled = []
    for dest_str in unscheduled_dests:
        slug = None
        best_score = 1
        for d in destinations:
            name_lower = d["name"].lower()
            dest_lower = dest_str.lower()
            if name_lower in dest_lower or dest_lower in name_lower:
                slug = get_destination_filename(d).replace(".html", "")
                break
            stop = {'/', '-', 'and', 'the', 'of', 'in', 'a'}
            wa = set(re.sub(r'[^a-z0-9 ]', ' ', dest_lower).split()) - stop
            wb = set(re.sub(r'[^a-z0-9 ]', ' ', name_lower).split()) - stop
            score = len(wa & wb)
            if score > best_score:
                best_score = score
                slug = get_destination_filename(d).replace(".html", "")
        js_unscheduled.append({"name": dest_str, "slug": slug})

    # Build a flat list of all destination slugs
    all_dest_slugs = [get_destination_filename(d).replace(".html", "") for d in destinations]

    dest_catalog_json = json.dumps(js_dest_catalog,   ensure_ascii=False)
    unscheduled_json  = json.dumps(js_unscheduled,    ensure_ascii=False)
    notes_json        = json.dumps(timetable_notes,   ensure_ascii=False)
    all_slugs_json    = json.dumps(all_dest_slugs,    ensure_ascii=False)

    total_trips = len([d for d in js_dest_catalog])  # badge shows full count, JS updates it

    main_html += f"""
        <div class="card section-card" id="section-timetable">
            <h2 class="section-heading" data-section="timetable">
                <button class="collapse-btn" data-section="timetable" aria-expanded="true" aria-controls="section-body-timetable" title="Collapse section">▾</button>
                Travel Timetable <span class="tt-count-badge" id="tt-trip-count">{total_trips} trips</span>
            </h2>
            <div class="section-body" id="section-body-timetable">
            <p style="color:#555; margin-top:8px; margin-bottom:16px;">
                The schedule is built around the best season for each destination, starting from Bengaluru.
                Choose a start month and use the checkboxes below to include only the destinations you want.
            </p>
            <div class="timetable-controls">
                <label for="tt-start">Start travelling from:</label>
                <input type="month" id="tt-start" />

            </div>
            <div id="timetable-table-wrap">
                <table id="timetable-table">
                    <thead>
                        <tr>
                            <th>Month</th>
                            <th>Destination</th>
                            <th>Why this month</th>
                            <th>Main focus</th>
                        </tr>
                    </thead>
                    <tbody id="timetable-tbody">
                    </tbody>
                </table>
            </div>
            <div class="tt-unscheduled">
                <h4>Remaining destinations (not scheduled under best-window rule)</h4>
                <ul id="tt-unscheduled-list"></ul>
            </div>
            <div class="tt-notes">
                <strong>Notes</strong>
                <ul id="tt-notes-list"></ul>
            </div>
            </div>
        </div>
        <script>
        window.__TIMETABLE__ = {{
            destCatalog: {dest_catalog_json},
            unscheduled: {unscheduled_json},
            notes: {notes_json},
            allSlugs: {all_slugs_json}
        }};
        </script>
"""

    # Add each destination section
    for section_name, dest_list in sections.items():
        section_id = re.sub(r'[^a-z0-9]', '_', section_name.lower()).strip('_')
        main_html += f"""
        <div class="card section-card" id="section-{section_id}">
            <h2 class="section-heading" data-section="{section_id}">
                <button class="collapse-btn" data-section="{section_id}" aria-expanded="true" aria-controls="section-body-{section_id}" title="Collapse section">▾</button>
                {section_name}
            </h2>
            <div class="section-body" id="section-body-{section_id}">
            <div style="overflow-x: auto;">
                <table data-section="{section_id}">
                    <thead>
                        <tr>
                            <th class="sel-col">
                                <label class="sel-all-label" title="Select / deselect all in this section">
                                    <input type="checkbox" class="sel-all-cb" data-section="{section_id}" checked>
                                    <span>All</span>
                                </label>
                            </th>
                            <th>Place</th>
                            <th>Best Time + Weather</th>
                            <th class="sortable">Ease Get</th>
                            <th class="sortable">Ease Stay</th>
                            <th>Transit from BLR</th>
                            <th>What to Expect</th>
                            <th class="sortable">Birding</th>
                            <th class="sortable">Wildlife</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        for d in dest_list:
            detail_link = f"destinations/{get_destination_filename(d)}"
            slug = get_destination_filename(d).replace(".html", "")
            place_str = f"<strong>{d['name']}</strong>"
            if d['state']:
                place_str += f", {d['state']}"

            main_html += f"""
                        <tr data-slug="{slug}">
                            <td class="sel-col">
                                <input type="checkbox" class="dest-cb" data-slug="{slug}" data-section="{section_id}" checked>
                            </td>
                            <td><a href="{detail_link}">{place_str}</a></td>
                            <td>{d['best_time']}</td>
                            <td><span class="rating">{d['ease_get']}</span></td>
                            <td><span class="rating">{d['ease_stay']}</span></td>
                            <td>{d['transit']}</td>
                            <td>{d['expect']}</td>
                            <td><span class="rating">{d['birding']}</span></td>
                            <td><span class="rating">{d['wildlife']}</span></td>
                        </tr>
"""
        main_html += """
                    </tbody>
                </table>
            </div>
            </div>
        </div>
"""

    # Add Rankings Section if present
    if rankings_data:
        main_html += """
        <div class="card section-card" id="section-rankings">
            <h2 class="section-heading" data-section="rankings">
                <button class="collapse-btn" data-section="rankings" aria-expanded="true" aria-controls="section-body-rankings" title="Collapse section">▾</button>
                Practical ranking from Bengaluru
            </h2>
            <div class="section-body" id="section-body-rankings">
            <div class="grid">
"""
        for rank in rankings_data:
            main_html += f"""
                <div class="ranking-card">
                    <h3>{rank['title']}</h3>
                    <ol class="ranking-list">
"""
            for item in rank['items']:
                # See if we can find the matching destination to link to it!
                # Simple name matching
                matching_dest = None
                for d in destinations:
                    if d["name"].lower() in item.lower() or item.lower() in d["name"].lower():
                        matching_dest = d
                        break
                
                if matching_dest:
                    link_href = f"destinations/{get_destination_filename(matching_dest)}"
                    main_html += f'                        <li><a href="{link_href}">{item}</a></li>\n'
                else:
                    main_html += f'                        <li>{item}</li>\n'
            main_html += """
                    </ol>
                </div>
"""
        main_html += """
            </div>
            </div>
        </div>
"""

    # Add Notes Section if present
    if notes_list:
        main_html += """
        <div class="card section-card" id="section-notes">
            <h2 class="section-heading" data-section="notes">
                <button class="collapse-btn" data-section="notes" aria-expanded="true" aria-controls="section-body-notes" title="Collapse section">▾</button>
                Notes
            </h2>
            <div class="section-body" id="section-body-notes">
            <ul class="notes-list">
"""
        for note in notes_list:
            # We can also attempt to hyper-link destinations mentioned in the notes
            for d in destinations:
                # Use word boundaries or exact name to replace it safely with a link
                pattern = r'\b' + re.escape(d["name"]) + r'\b'
                # But only if it's not already in an <a> tag
                link_href = f"destinations/{get_destination_filename(d)}"
                note = re.sub(pattern, f'<a href="{link_href}">{d["name"]}</a>', note)
                
            main_html += f"                <li>{note}</li>\n"
        main_html += """
            </ul>
            </div>
        </div>
"""

    main_html += """
    </div>
    <script src="resources/sort.js"></script>
    <script src="resources/timetable.js"></script>
</body>
</html>
"""

    with open("output/index.html", "w", encoding="utf-8") as f:
        f.write(main_html)

    # 3. Generate sitemap.xml
    today = date.today().isoformat()
    sitemap_urls = []

    # sitemap — highest priority
    sitemap_urls.append(f"""  <url>
    <loc>{SITE_URL}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
  </url>""")

    # One entry per destination detail page
    for d in destinations:
        filename = get_destination_filename(d)
        sitemap_urls.append(f"""  <url>
    <loc>{SITE_URL}/destinations/{filename}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>""")

    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(sitemap_urls)
        + "\n</urlset>\n"
    )
    with open("output/sitemap.xml", "w", encoding="utf-8") as f:
        f.write(sitemap_xml)

    # 4. Generate robots.txt
    robots_txt = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    with open("output/robots.txt", "w", encoding="utf-8") as f:
        f.write(robots_txt)

    print("Successfully generated HTML output files.")

if __name__ == "__main__":
    generate_html()
