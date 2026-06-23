"""
Server-side PDF rendering via WeasyPrint.
Ported from the local pdf_server.py — same CSS, same HTML builders.
"""
import io
import json
import re
import html as html_lib
from pathlib import Path
from datetime import datetime

from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration

# ── Font embedding ─────────────────────────────────────────────────────────────
_FONT_DIR = Path(__file__).parent / "fonts"

def _load_font_faces():
    b64_path = _FONT_DIR / "fonts_b64.json"
    if not b64_path.exists():
        return ""
    fonts = json.loads(b64_path.read_text())
    def face(family, style, weight, key):
        if key not in fonts:
            return ""
        return (f"@font-face{{font-family:'{family}';font-style:{style};"
                f"font-weight:{weight};"
                f"src:url('data:font/truetype;base64,{fonts[key]}') format('truetype');}}")
    return "\n".join([
        face("Roboto", "normal", "300",   "Roboto-Light.ttf"),
        face("Roboto", "normal", "400",   "Roboto-Regular.ttf"),
        face("Roboto", "normal", "700",   "Roboto-Bold.ttf"),
        face("Roboto", "italic", "400",   "Roboto-Italic.ttf"),
        face("Roboto", "italic", "700",   "Roboto-BoldItalic.ttf"),
        face("Roboto Slab", "normal", "100 900", "RobotoSlab-VF.ttf"),
    ])

FONT_FACES = _load_font_faces()

# ── Markdown → HTML ────────────────────────────────────────────────────────────
import re as _re
_EMOJI_RE = _re.compile(
    "[\U0001F300-\U0001FFFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F]+",
    flags=_re.UNICODE,
)

def _clean_markdown(text, strip_emoji=True):
    lines = []
    for line in text.split("\n"):
        if _re.match(r"^#{1,4}\s", line) and strip_emoji:
            m = _re.match(r"^(#{1,4}\s+)", line)
            prefix = m.group(1)
            rest = _EMOJI_RE.sub("", line[len(prefix):]).strip()
            line = prefix + rest
        lines.append(line)
    return "\n".join(lines)

def _md_to_html(text, strip_emoji=True):
    import markdown as md_lib
    text = _clean_markdown(text, strip_emoji=strip_emoji)
    converter = md_lib.Markdown(extensions=["extra", "tables", "sane_lists"])
    return converter.convert(text)

def esc(s):
    return html_lib.escape(str(s or ""))

# ── CSS ────────────────────────────────────────────────────────────────────────
def _client_css(client_name, subtitle):
    cn = esc(client_name)
    st = esc(subtitle)
    return f"""
{FONT_FACES}
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;
  -webkit-print-color-adjust:exact;print-color-adjust:exact;}}
:root{{
  --charcoal:#1e2022;--charcoal-mid:#3d4145;
  --slate:#3a5a7c;--slate-mid:#5579a0;--slate-light:#dce8f5;--slate-pale:#eef4fb;
  --text:#2c3035;--text-mid:#4a5058;--text-dim:#7a8088;
  --surface2:#f0ede9;--border:#e0dbd4;
  --green:#2e6b4a;--green-bg:#ddf0e8;--green-border:#b0d9c4;
}}
@page{{
  size:letter;margin:0.75in 0.85in 0.9in 0.85in;
  @bottom-left{{content:"{cn}  —  {st}";
    font-family:'Roboto',sans-serif;font-size:7pt;color:#9ba0a6;
    padding-top:10pt;border-top:0.5pt solid #e0dbd4;}}
  @bottom-right{{content:"Page " counter(page) " of " counter(pages) "  |  Confidential";
    font-family:'Roboto',sans-serif;font-size:7pt;color:#9ba0a6;
    padding-top:10pt;border-top:0.5pt solid #e0dbd4;}}
}}
@page :first{{margin-top:0;}}
body{{font-family:'Roboto','DejaVu Sans',sans-serif;font-size:10.5pt;
  line-height:1.72;color:var(--text);background:white;}}
.doc-header{{border-top:3pt solid var(--charcoal);border-bottom:0.5pt solid var(--border);
  padding:22pt 0.85in 20pt;margin:-0.75in -0.85in 0;}}
.eyebrow{{font-size:7.5pt;letter-spacing:.18em;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:8pt;}}
.client-name{{font-family:'Roboto Slab',serif;font-size:24pt;font-weight:700;
  color:var(--charcoal);margin-bottom:3pt;line-height:1.1;}}
.doc-sub{{font-size:10pt;font-weight:300;color:var(--text-mid);}}
.header-rule{{display:none;}}
.doc-body{{padding-top:28pt;}}
h1{{font-family:'Roboto Slab',serif;font-size:16pt;font-weight:700;
  color:var(--charcoal);margin-top:30pt;margin-bottom:6pt;
  padding-bottom:7pt;border-bottom:1.5pt solid var(--charcoal);
  break-after:avoid;line-height:1.25;}}
h1:first-child{{margin-top:0;}}
h2{{font-family:'Roboto Slab',serif;font-size:12.5pt;font-weight:700;
  color:var(--charcoal);margin-top:24pt;margin-bottom:5pt;
  break-after:avoid;line-height:1.3;}}
h3{{font-family:'Roboto',sans-serif;font-size:10.5pt;font-weight:600;
  color:var(--charcoal);margin-top:18pt;margin-bottom:4pt;break-after:avoid;}}
h4{{font-family:'Roboto',sans-serif;font-size:10pt;font-weight:600;
  color:var(--charcoal-mid);margin-top:13pt;margin-bottom:3pt;break-after:avoid;}}
p{{margin-bottom:9pt;color:var(--text-mid);orphans:3;widows:3;}}
strong{{font-weight:600;color:var(--charcoal);}}
em{{font-style:italic;}}
ul,ol{{margin:4pt 0 10pt 18pt;padding:0;}}
li{{margin-bottom:4pt;color:var(--text-mid);padding-left:2pt;}}
li::marker{{color:var(--charcoal);font-weight:500;}}
ul li::marker{{content:"–  ";}}
blockquote{{border-left:2pt solid var(--charcoal-mid);
  padding:12pt 16pt;margin:10pt 0 14pt;break-inside:avoid;}}
blockquote p{{font-style:italic;color:var(--charcoal);margin-bottom:0;
  font-size:10.5pt;line-height:1.8;font-weight:300;}}
blockquote p+p{{margin-top:7pt;}}
hr{{border:none;border-top:0.5pt solid var(--border);margin:16pt 0;}}
code{{font-family:'DejaVu Sans Mono',monospace;font-size:8.5pt;
  border:0.5pt solid var(--border);padding:1pt 4pt;border-radius:2pt;color:var(--charcoal);}}
table{{width:100%;border-collapse:collapse;margin:8pt 0 14pt;font-size:10pt;break-inside:avoid;}}
th{{background:#f0f0f0;color:var(--charcoal);font-weight:700;padding:7pt 10pt;
  text-align:left;font-size:9pt;letter-spacing:.03em;
  border-top:1pt solid var(--charcoal);border-bottom:1pt solid var(--charcoal);}}
td{{padding:6pt 10pt;border-bottom:0.5pt solid var(--border);color:var(--text-mid);vertical-align:top;}}
tr:nth-child(even) td{{background:#f8f8f8;}}
"""

def _positioning_css(client_name):
    cn = esc(client_name)
    return f"""
{FONT_FACES}
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;
  -webkit-print-color-adjust:exact;print-color-adjust:exact;}}
:root{{
  --charcoal:#1e2022;--charcoal-mid:#3d4145;
  --slate:#3a5a7c;--slate-mid:#5579a0;--slate-light:#dce8f5;--slate-pale:#eef4fb;
  --text:#2c3035;--text-mid:#4a5058;--text-dim:#7a8088;
  --surface2:#f0ede9;--border:#e0dbd4;
  --green:#2e6b4a;--green-bg:#ddf0e8;--green-border:#b0d9c4;
  --amber:#7a4f00;--amber-bg:#fff0cc;
}}
@page{{
  size:letter;margin:0.5in 0.6in 0.6in 0.6in;
  @bottom-left{{content:"{cn}  —  Where to Look";
    font-family:'Roboto',sans-serif;font-size:7pt;color:#9ba0a6;
    padding-top:7pt;border-top:0.5pt solid #e0dbd4;}}
  @bottom-right{{content:"Page " counter(page) " of " counter(pages) "  |  Confidential";
    font-family:'Roboto',sans-serif;font-size:7pt;color:#9ba0a6;
    padding-top:7pt;border-top:0.5pt solid #e0dbd4;}}
}}
@page :first{{margin-top:0;}}
body{{font-family:'Roboto','DejaVu Sans',sans-serif;font-size:9.5pt;
  line-height:1.5;color:var(--text);background:white;}}
.doc-header{{border-top:3pt solid var(--charcoal);border-bottom:0.5pt solid var(--border);
  padding:16pt 0.6in 12pt;margin:-0.5in -0.6in 0;}}
.eyebrow{{font-size:7.5pt;letter-spacing:.18em;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:6pt;}}
.client-name{{font-family:'Roboto Slab',serif;font-size:21pt;font-weight:700;
  color:var(--charcoal);margin-bottom:2pt;line-height:1.1;}}
.doc-sub{{font-size:9.5pt;font-weight:300;color:var(--text-mid);margin-bottom:8pt;}}
.pill{{display:inline-block;font-size:8pt;padding:2pt 8pt;
  border:0.5pt solid var(--border);color:var(--text-dim);
  border-radius:100pt;margin-right:5pt;margin-bottom:4pt;}}
.header-rule{{display:none;}}
.doc-body{{padding-top:16pt;}}
.section-label{{font-size:7.5pt;letter-spacing:.18em;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:7pt;padding-bottom:5pt;
  border-bottom:0.5pt solid var(--border);margin-top:14pt;}}
.section-label:first-child{{margin-top:0;}}
.confirmed-block{{border-left:2pt solid var(--charcoal-mid);
  padding:9pt 12pt;margin-bottom:14pt;}}
.confirmed-label{{font-size:7pt;letter-spacing:.14em;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:4pt;}}
.confirmed-text{{font-size:9.5pt;color:var(--charcoal-mid);line-height:1.55;}}
.brand-card{{border:0.5pt solid var(--border);border-radius:2pt;
  padding:12pt 15pt;margin-bottom:4pt;break-inside:avoid;}}
.brand-quote{{font-family:'Roboto Slab',serif;font-size:10pt;color:var(--charcoal);
  line-height:1.6;font-style:italic;border-left:2pt solid var(--charcoal-mid);
  padding-left:12pt;font-weight:400;}}
.brand-note{{font-size:8.5pt;color:var(--text-dim);margin-top:7pt;
  padding-left:14pt;font-style:italic;}}
.lane-header{{border-top:2pt solid var(--charcoal);
  border-left:0.5pt solid var(--border);border-right:0.5pt solid var(--border);
  padding:9pt 12pt;break-after:avoid;margin-top:4pt;}}
.lane-label{{font-size:7pt;letter-spacing:.14em;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:3pt;}}
.lane-title{{font-family:'Roboto Slab',serif;font-size:12pt;font-weight:700;
  color:var(--charcoal);line-height:1.2;}}
.lane-body{{border:0.5pt solid var(--border);border-top:none;
  border-radius:0 0 2pt 2pt;padding:12pt 14pt;margin-bottom:14pt;}}
.hook{{border-left:2pt solid var(--charcoal-mid);
  padding:8pt 11pt;margin-bottom:9pt;break-inside:avoid;}}
.hook-label{{font-size:7pt;letter-spacing:.14em;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:4pt;}}
.hook-text{{font-size:9.5pt;color:var(--charcoal);font-style:italic;line-height:1.55;}}
.lane-why{{font-size:9.5pt;color:var(--text-mid);line-height:1.55;margin-bottom:9pt;}}
.comp-note{{font-size:9pt;color:var(--text-mid);padding:6pt 10pt;
  border:0.5pt solid var(--border);border-radius:2pt;margin-bottom:12pt;}}
.comp-note strong{{color:var(--charcoal);font-weight:600;}}
.company-card{{border:0.5pt solid var(--border);border-radius:2pt;
  margin-bottom:9pt;break-inside:avoid;}}
.company-top{{padding:9pt 12pt 8pt;border-bottom:0.5pt solid var(--border);}}
.company-fit{{font-size:7pt;letter-spacing:.12em;text-transform:uppercase;
  color:var(--charcoal-mid);margin-bottom:3pt;font-weight:600;}}
.company-fit.stretch{{color:var(--charcoal-mid);}}
.company-name{{font-family:'Roboto Slab',serif;font-size:12pt;font-weight:700;
  color:var(--charcoal);margin-bottom:2pt;}}
.company-desc{{font-size:9pt;color:var(--text-dim);}}
.tag{{display:inline-block;font-size:8pt;padding:1pt 7pt;
  border:0.5pt solid var(--border);border-radius:2pt;color:var(--text-dim);
  margin-right:4pt;margin-top:5pt;background:white;}}
.company-body{{padding:9pt 12pt 10pt;}}
.why-label{{font-size:7pt;letter-spacing:.14em;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:5pt;}}
.why-text{{font-size:9.5pt;color:var(--text-mid);line-height:1.55;margin-bottom:9pt;}}
.search-block{{border:0.5pt solid var(--border);border-radius:2pt;overflow:hidden;}}
.search-header{{font-size:7pt;letter-spacing:.16em;text-transform:uppercase;
  color:var(--text-dim);padding:4pt 10pt;background:#f0f0f0;
  border-bottom:0.5pt solid var(--border);}}
.search-row{{border-bottom:0.5pt solid var(--border);padding:6pt 10pt;break-inside:avoid;}}
.search-row:last-child{{border-bottom:none;}}
.search-type-label{{display:inline-block;font-size:7.5pt;letter-spacing:.1em;
  text-transform:uppercase;color:var(--charcoal-mid);font-weight:600;
  margin-right:6pt;}}
.search-instruction{{display:inline;font-size:9pt;color:var(--text-mid);line-height:1.5;}}
.search-note{{font-size:8pt;color:var(--text-dim);font-style:italic;
  margin-top:3pt;line-height:1.45;}}
.action-card{{border:0.5pt solid var(--border);border-radius:2pt;
  padding:12pt 14pt;margin-top:4pt;}}
.action-item{{padding:7pt 0;border-bottom:0.5pt solid var(--border);
  break-inside:avoid;overflow:hidden;}}
.action-item:last-child{{border-bottom:none;}}
.action-num{{display:inline-block;width:20pt;font-size:8.5pt;
  color:var(--charcoal);border:1pt solid var(--charcoal);text-align:center;
  padding:2pt 0;border-radius:2pt;font-weight:700;
  float:left;margin-right:10pt;margin-top:1pt;}}
.action-text{{display:block;overflow:hidden;font-size:9.5pt;
  color:var(--text);line-height:1.55;}}
"""

# ── HTML builders ──────────────────────────────────────────────────────────────
def build_client_html(markdown_text, client_name, subtitle,
                      eyebrow="Challenger, Gray &amp; Christmas  /  Strategy Session"):
    today = datetime.now().strftime("%B %d, %Y")
    body = _md_to_html(markdown_text, strip_emoji=False)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<style>{_client_css(client_name, subtitle)}</style></head><body>
<div class="doc-header">
  <div class="eyebrow">{eyebrow}</div>
  <div class="client-name">{esc(client_name)}</div>
  <div class="doc-sub">{esc(subtitle)}  —  {today}</div>
  <div class="header-rule"></div>
</div>
<div class="doc-body">{body}</div>
</body></html>"""


# ── Session Worksheet (reMarkable, ruled note space) ─────────────────────────────
def _worksheet_css(client_name):
    cn = esc(client_name)
    return f"""
{FONT_FACES}
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;
  -webkit-print-color-adjust:exact;print-color-adjust:exact;}}
:root{{
  --charcoal:#1e2022;--charcoal-mid:#3d4145;--slate:#3a5a7c;--slate-mid:#5579a0;
  --slate-pale:#eef4fb;--text:#2c3035;--text-mid:#4a5058;--text-dim:#7a8088;
  --border:#e0dbd4;--rule:#c2ccd6;
}}
@page{{
  size:letter;margin:0.6in 0.7in 0.7in 0.7in;
  @bottom-right{{content:"{cn}  —  Session Worksheet  —  Page " counter(page);
    font-family:'Roboto',sans-serif;font-size:7.5pt;color:#9ba0a6;
    padding-top:7pt;border-top:0.5pt solid #e0dbd4;}}
}}
@page :first{{margin-top:0;}}
body{{font-family:'Roboto','DejaVu Sans',sans-serif;font-size:12pt;
  line-height:1.5;color:var(--text);background:white;}}
.doc-header{{border-top:3pt solid var(--charcoal);border-bottom:0.5pt solid var(--border);
  padding:18pt 0.7in 14pt;margin:-0.6in -0.7in 0;}}
.eyebrow{{font-size:8pt;letter-spacing:.2em;text-transform:uppercase;color:var(--slate-mid);margin-bottom:7pt;}}
.client-name{{font-family:'Roboto Slab',serif;font-size:22pt;font-weight:700;color:var(--charcoal);line-height:1.1;}}
.doc-sub{{font-size:10pt;font-weight:300;color:var(--text-mid);margin-top:3pt;}}
.doc-body{{padding-top:18pt;}}
h1{{display:none;}}
h2{{font-family:'Roboto Slab',serif;font-size:15pt;font-weight:700;color:var(--charcoal);
  margin-top:22pt;margin-bottom:7pt;padding-bottom:6pt;border-bottom:1.5pt solid var(--charcoal);
  break-after:avoid;break-before:auto;}}
h2:first-of-type{{margin-top:0;}}
h3{{font-family:'Roboto',sans-serif;font-size:12.5pt;font-weight:600;color:var(--slate);
  margin-top:16pt;margin-bottom:6pt;break-after:avoid;}}
p{{margin-bottom:7pt;color:var(--text-mid);}}
p em{{color:var(--charcoal-mid);font-style:italic;}}
strong{{font-weight:600;color:var(--charcoal);}}
ul,ol{{margin:4pt 0 8pt 20pt;padding:0;}}
li{{margin-bottom:6pt;color:var(--charcoal);break-inside:avoid;}}
li::marker{{color:var(--slate-mid);}}
blockquote{{border-left:2.5pt solid var(--slate);background:var(--slate-pale);
  padding:8pt 12pt;margin:7pt 0 9pt;break-inside:avoid;border-radius:0 2pt 2pt 0;}}
blockquote p{{margin-bottom:0;color:var(--charcoal);font-size:11pt;line-height:1.55;}}
hr{{border:none;border-top:0.5pt solid var(--border);margin:14pt 0;}}
.note{{margin:6pt 0 12pt;}}
.note .rule{{height:30pt;border-bottom:0.75pt solid var(--rule);}}
/* One question cluster (+ its note space) per page. */
.qpage{{break-before:page;}}
.qpage:first-of-type{{break-before:auto;}}
li.chk{{list-style:none;margin-left:-12pt;}}
li.chk::before{{content:"\\2610";font-size:15pt;line-height:1;margin-right:9pt;color:var(--charcoal);vertical-align:-1pt;}}
li.chk-done::before{{content:"\\2611";}}
"""


def _ruled_note(size):
    counts = {"small": 3, "standard": 6, "large": 12}
    n = counts.get(size or "standard", 6)
    return '<div class="note">' + ('<div class="rule"></div>' * n) + "</div>"


def build_worksheet_html(worksheet_md, client_name):
    today = datetime.now().strftime("%B %d, %Y")
    # Split on note markers; the optional size is captured.
    parts = re.split(r"(?m)^[ \t]*\[\[NOTES(?::([a-zA-Z]+))?\]\][ \t]*$", worksheet_md)
    # parts alternates: [text, size, text, size, ..., text]. Each text chunk is
    # one question cluster (heading + questions); the size that follows is its
    # note area. Wrap each cluster + its notes in a .qpage section so the
    # worksheet renders roughly one cluster per page with room to write.
    texts = parts[0::2]
    sizes = parts[1::2]
    body = ""
    for i, chunk in enumerate(texts):
        inner = ""
        if chunk and chunk.strip():
            inner += _md_to_html(chunk, strip_emoji=True)
        if i < len(sizes):
            inner += _ruled_note(sizes[i])  # sizes[i] is the captured size (or None)
        if inner:
            body += f'<section class="qpage">{inner}</section>'
    # Render markdown task-list items ("- [ ] item") as printable checkboxes.
    body = re.sub(r"<li>(\s*<p>)?\s*\[ \]\s*",
                  lambda m: '<li class="chk">' + (m.group(1) or ""), body)
    body = re.sub(r"<li>(\s*<p>)?\s*\[[xX]\]\s*",
                  lambda m: '<li class="chk chk-done">' + (m.group(1) or ""), body)
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<style>{_worksheet_css(client_name)}</style></head><body>
<div class="doc-header">
  <div class="eyebrow">Challenger, Gray &amp; Christmas  /  Coach Worksheet</div>
  <div class="client-name">{esc(client_name)}</div>
  <div class="doc-sub">Session Worksheet  —  {today}</div>
</div>
<div class="doc-body">{body}</div>
</body></html>"""


def _positioning_body_html(pos):
    """The inner content of the positioning guide (everything inside .doc-body),
    reusable both as a standalone PDF and as a section of the strategy package."""
    lanes_html = []
    for lane in pos.get("lanes", []):
        comp_note_raw = lane.get("compRange", "")
        cos = []
        for co in lane.get("companies", []):
            tags_html = "".join(
                f'<span class="tag">{esc(t)}</span>'
                for t in [co.get("size", ""), co.get("workStyle", "")] if t
            )
            search_types = [
                ("Peer",       co.get("peer", {})),
                ("Hiring Mgr", co.get("hiringMgr", {})),
                ("Recruiter",  co.get("recruiter", {})),
            ]
            rows_html = ""
            for label, s in search_types:
                if not s or not s.get("instruction"):
                    continue
                fallback_html = (f'<div class="search-note">{esc(s.get("fallback",""))}</div>'
                                 if s.get("fallback") else "")
                rows_html += f"""<div class="search-row">
  <span class="search-type-label">{esc(label)}</span><span class="search-instruction">{esc(s.get("instruction",""))}</span>
  {fallback_html}
</div>"""
            fit_text = co.get("fit", "")
            stretch = "stretch" if "stretch" in fit_text.lower() else ""
            fit_prefix = "◇ " if stretch else "● "
            cos.append(f"""<div class="company-card">
  <div class="company-top">
    <div class="company-fit {stretch}">{fit_prefix}{esc(fit_text)}</div>
    <div class="company-name">{esc(co.get("name",""))}</div>
    <div class="company-desc">{esc(co.get("descriptor",""))}</div>
    <div>{tags_html}</div>
  </div>
  <div class="company-body">
    <div class="why-label">Why It Fits</div>
    <div class="why-text">{esc(co.get("whyItFits",""))}</div>
    <div class="search-block">
      <div class="search-header">LinkedIn Search Strings</div>
      {rows_html}
    </div>
  </div>
</div>""")
        comp_note_html = (f'<div class="comp-note"><strong>Typical total comp at your level:</strong> {esc(comp_note_raw)}</div>'
                          if comp_note_raw else "")
        lanes_html.append(f"""<div class="lane-header">
  <div class="lane-label">Target Lane</div>
  <div class="lane-title">{esc(lane.get("label",""))}</div>
</div>
<div class="lane-body">
  <div class="hook"><div class="hook-label">Your Opening Hook</div>
    <div class="hook-text">{esc(lane.get("hook",""))}</div></div>
  <div class="lane-why">{esc(lane.get("why",""))}</div>
  {comp_note_html}
  {"".join(cos)}
</div>""")

    actions = pos.get("actionSequence", [])
    action_html = ""
    if actions:
        items = "".join(
            f"""<div class="action-item">
  <div class="action-num">{i+1:02d}</div>
  <div class="action-text">{esc(a.get("text", a) if isinstance(a, dict) else a)}</div>
</div>""" for i, a in enumerate(actions)
        )
        action_html = f"""<div class="section-label">Your First Week — Action Sequence</div>
<div class="action-card">{items}</div>"""

    return f"""<div class="section-label">Confirmed in Session</div>
<div class="confirmed-block">
  <div class="confirmed-label">How We Got Here</div>
  <div class="confirmed-text">{esc(pos.get("confirmedFrom",""))}</div>
</div>
<div class="section-label">Your Brand Statement</div>
<div class="brand-card">
  <div class="brand-quote">{esc(pos.get("brandStatement",""))}</div>
  <div class="brand-note">Written from your session. Adjust any language that doesn't feel like you.</div>
</div>
<div class="section-label">Target Lanes — Where to Focus</div>
{"".join(lanes_html)}
{action_html}"""


def build_positioning_html(pos, client_name):
    pills_html = "".join(
        f'<span class="pill">{esc(p)}</span>'
        for p in [
            f"{len(pos.get('lanes', []))} Target Lanes",
            f"{sum(len(l.get('companies', [])) for l in pos.get('lanes', []))} Companies",
            "LinkedIn Search Strings",
            "Action Sequence",
        ]
    )
    today = datetime.now().strftime("%B %d, %Y")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<style>{_positioning_css(client_name)}</style></head><body>
<div class="doc-header">
  <div class="eyebrow">Challenger, Gray &amp; Christmas  /  Target Company Guide</div>
  <div class="client-name">{esc(client_name)}</div>
  <div class="doc-sub">{esc(pos.get("targetTitle",""))}  —  {today}</div>
  <div>{pills_html}</div>
  <div class="header-rule"></div>
</div>
<div class="doc-body">
{_positioning_body_html(pos)}
</div></body></html>"""


# ── Strategy Package (combined client book) ─────────────────────────────────────

# Section order and display titles for the assembled package. "actionplan" is
# derived by splitting it out of the summary at compose time.
PACKAGE_ORDER = [
    ("summary",     "Session Summary"),
    ("actionplan",  "Your Action Plan"),
    ("branding",    "Branding Profile"),
    ("ip",          "Interview Program"),
    ("stories",     "Success Stories"),
    ("roleplay",    "Roleplay Analysis"),
    ("positioning", "Where to Look"),
]


def _strip_leading_h1(md):
    return re.sub(r"^\s*#\s+.*?(\n|$)", "", md, count=1)


def _split_action_plan(md):
    """Pull the Action Plan subsection out of the summary markdown.
    Returns (summary_without_action_plan, action_plan_markdown_or_None)."""
    lines = md.split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(r"^#{2,4}\s+.*action plan", l, re.I):
            start = i
            break
    if start is None:
        return md, None
    level = len(re.match(r"^(#{2,4})", lines[start]).group(1))
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    action_block = "\n".join(lines[start + 1:end]).strip()
    remaining = "\n".join(lines[:start] + lines[end:]).strip()
    return remaining, (action_block or None)


def _package_css(client_name):
    cn = esc(client_name)
    return f"""
{FONT_FACES}
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;
  -webkit-print-color-adjust:exact;print-color-adjust:exact;}}
:root{{
  --charcoal:#1e2022;--charcoal-mid:#3d4145;
  --slate:#3a5a7c;--slate-mid:#5579a0;--slate-light:#dce8f5;--slate-pale:#eef4fb;
  --text:#2c3035;--text-mid:#4a5058;--text-dim:#7a8088;
  --surface2:#f0ede9;--border:#e0dbd4;
  --green:#2e6b4a;--green-bg:#ddf0e8;--green-border:#b0d9c4;
}}
@page{{
  size:letter;margin:0.7in 0.7in 0.7in 0.7in;
  @bottom-left{{content:"{cn}  —  Strategy Package";
    font-family:'Roboto',sans-serif;font-size:7pt;color:#9ba0a6;
    padding-top:7pt;border-top:0.5pt solid #e0dbd4;}}
  @bottom-right{{content:"Page " counter(page) " of " counter(pages) "  |  Confidential";
    font-family:'Roboto',sans-serif;font-size:7pt;color:#9ba0a6;
    padding-top:7pt;border-top:0.5pt solid #e0dbd4;}}
}}
@page cover{{margin:0;@bottom-left{{content:none;}}@bottom-right{{content:none;}}}}
body{{font-family:'Roboto','DejaVu Sans',sans-serif;font-size:10pt;
  line-height:1.6;color:var(--text);background:white;}}

/* Cover */
.cover{{page:cover;height:100vh;display:flex;flex-direction:column;
  justify-content:space-between;padding:1.4in 1in 1in;
  border-top:18pt solid var(--charcoal);}}
.cover-eyebrow{{font-size:9pt;letter-spacing:.22em;text-transform:uppercase;
  color:var(--slate-mid);margin-bottom:18pt;}}
.cover-name{{font-family:'Roboto Slab',serif;font-size:44pt;font-weight:700;
  color:var(--charcoal);line-height:1.05;margin-bottom:10pt;}}
.cover-title{{font-family:'Roboto Slab',serif;font-size:18pt;font-weight:400;
  color:var(--slate);margin-bottom:6pt;}}
.cover-sub{{font-size:11pt;font-weight:300;color:var(--text-mid);}}
.cover-foot{{font-size:8.5pt;letter-spacing:.06em;color:var(--text-dim);
  border-top:0.5pt solid var(--border);padding-top:12pt;}}

/* Table of contents */
.toc{{page-break-before:always;padding-top:6pt;}}
.toc-h{{font-family:'Roboto Slab',serif;font-size:20pt;font-weight:700;
  color:var(--charcoal);margin-bottom:18pt;padding-bottom:8pt;
  border-bottom:1.5pt solid var(--charcoal);}}
.toc ol{{list-style:none;margin:0;padding:0;counter-reset:toc;}}
.toc li{{margin-bottom:11pt;}}
.toc a{{display:block;text-decoration:none;color:var(--charcoal);
  font-size:12pt;font-weight:500;}}
.toc a::before{{counter-increment:toc;content:counter(toc,decimal-leading-zero) "  ";
  color:var(--slate-mid);font-family:'Roboto Mono',monospace;font-size:10pt;}}
.toc a::after{{content:leader('.') target-counter(attr(href), page);
  color:var(--text-dim);font-weight:400;font-family:'Roboto Mono',monospace;font-size:10pt;}}

/* Section dividers + content */
.pkg-section{{page-break-before:always;}}
h1.pkg-section-title{{font-family:'Roboto Slab',serif;font-size:23pt;font-weight:700;
  color:var(--charcoal);line-height:1.15;margin-bottom:4pt;}}
.pkg-section-eyebrow{{font-size:8pt;letter-spacing:.2em;text-transform:uppercase;
  color:var(--slate-mid);margin-bottom:6pt;}}
.pkg-section-rule{{border:none;border-top:2pt solid var(--charcoal);
  margin:10pt 0 18pt;}}
.pkg-body h2{{font-family:'Roboto Slab',serif;font-size:14pt;font-weight:700;
  color:var(--charcoal);margin-top:20pt;margin-bottom:5pt;break-after:avoid;line-height:1.3;}}
.pkg-body h3{{font-family:'Roboto',sans-serif;font-size:11.5pt;font-weight:600;
  color:var(--slate);margin-top:15pt;margin-bottom:4pt;break-after:avoid;}}
.pkg-body h4{{font-family:'Roboto',sans-serif;font-size:10pt;font-weight:600;
  color:var(--charcoal-mid);margin-top:12pt;margin-bottom:3pt;break-after:avoid;}}
.pkg-body p{{margin-bottom:8pt;color:var(--text-mid);orphans:3;widows:3;}}
.pkg-body strong{{font-weight:600;color:var(--charcoal);}}
.pkg-body em{{font-style:italic;}}
.pkg-body ul,.pkg-body ol{{margin:4pt 0 10pt 18pt;padding:0;}}
.pkg-body li{{margin-bottom:4pt;color:var(--text-mid);padding-left:2pt;}}
.pkg-body li::marker{{color:var(--charcoal);font-weight:500;}}
.pkg-body ul li::marker{{content:"–  ";}}
.pkg-body blockquote{{border-left:2pt solid var(--slate);background:var(--slate-pale);
  padding:10pt 14pt;margin:10pt 0 12pt;break-inside:avoid;border-radius:0 2pt 2pt 0;}}
.pkg-body blockquote p{{font-style:italic;color:var(--charcoal);margin-bottom:0;
  font-size:10pt;line-height:1.7;}}
.pkg-body hr{{border:none;border-top:0.5pt solid var(--border);margin:14pt 0;}}
.pkg-body table{{width:100%;border-collapse:collapse;margin:8pt 0 12pt;font-size:9.5pt;break-inside:avoid;}}
.pkg-body th{{background:#f0f0f0;color:var(--charcoal);font-weight:700;padding:6pt 9pt;
  text-align:left;font-size:9pt;border-top:1pt solid var(--charcoal);border-bottom:1pt solid var(--charcoal);}}
.pkg-body td{{padding:5pt 9pt;border-bottom:0.5pt solid var(--border);color:var(--text-mid);vertical-align:top;}}

/* Positioning components (Where to Look section) */
.section-label{{font-size:7.5pt;letter-spacing:.18em;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:7pt;padding-bottom:5pt;
  border-bottom:0.5pt solid var(--border);margin-top:16pt;}}
.confirmed-block{{border-left:2pt solid var(--charcoal-mid);padding:9pt 12pt;margin-bottom:14pt;}}
.confirmed-label{{font-size:7pt;letter-spacing:.14em;text-transform:uppercase;color:var(--text-dim);margin-bottom:4pt;}}
.confirmed-text{{font-size:9.5pt;color:var(--charcoal-mid);line-height:1.55;}}
.brand-card{{border:0.5pt solid var(--border);border-radius:2pt;padding:12pt 15pt;margin-bottom:4pt;break-inside:avoid;}}
.brand-quote{{font-family:'Roboto Slab',serif;font-size:10pt;color:var(--charcoal);line-height:1.6;
  font-style:italic;border-left:2pt solid var(--charcoal-mid);padding-left:12pt;font-weight:400;}}
.brand-note{{font-size:8.5pt;color:var(--text-dim);margin-top:7pt;padding-left:14pt;font-style:italic;}}
.lane-header{{border-top:2pt solid var(--charcoal);border-left:0.5pt solid var(--border);
  border-right:0.5pt solid var(--border);padding:9pt 12pt;break-after:avoid;margin-top:4pt;}}
.lane-label{{font-size:7pt;letter-spacing:.14em;text-transform:uppercase;color:var(--text-dim);margin-bottom:3pt;}}
.lane-title{{font-family:'Roboto Slab',serif;font-size:12pt;font-weight:700;color:var(--charcoal);line-height:1.2;}}
.lane-body{{border:0.5pt solid var(--border);border-top:none;border-radius:0 0 2pt 2pt;
  padding:12pt 14pt;margin-bottom:14pt;}}
.hook{{border-left:2pt solid var(--charcoal-mid);padding:8pt 11pt;margin-bottom:9pt;break-inside:avoid;}}
.hook-label{{font-size:7pt;letter-spacing:.14em;text-transform:uppercase;color:var(--text-dim);margin-bottom:4pt;}}
.hook-text{{font-size:9.5pt;color:var(--charcoal);font-style:italic;line-height:1.55;}}
.lane-why{{font-size:9.5pt;color:var(--text-mid);line-height:1.55;margin-bottom:9pt;}}
.comp-note{{font-size:9pt;color:var(--text-mid);padding:6pt 10pt;border:0.5pt solid var(--border);
  border-radius:2pt;margin-bottom:12pt;}}
.comp-note strong{{color:var(--charcoal);font-weight:600;}}
.company-card{{border:0.5pt solid var(--border);border-radius:2pt;margin-bottom:9pt;break-inside:avoid;}}
.company-top{{padding:9pt 12pt 8pt;border-bottom:0.5pt solid var(--border);}}
.company-fit{{font-size:7pt;letter-spacing:.12em;text-transform:uppercase;color:var(--charcoal-mid);
  margin-bottom:3pt;font-weight:600;}}
.company-name{{font-family:'Roboto Slab',serif;font-size:12pt;font-weight:700;color:var(--charcoal);margin-bottom:2pt;}}
.company-desc{{font-size:9pt;color:var(--text-dim);}}
.tag{{display:inline-block;font-size:8pt;padding:1pt 7pt;border:0.5pt solid var(--border);
  border-radius:2pt;color:var(--text-dim);margin-right:4pt;margin-top:5pt;background:white;}}
.company-body{{padding:9pt 12pt 10pt;}}
.why-label{{font-size:7pt;letter-spacing:.14em;text-transform:uppercase;color:var(--text-dim);margin-bottom:5pt;}}
.why-text{{font-size:9.5pt;color:var(--text-mid);line-height:1.55;margin-bottom:9pt;}}
.search-block{{border:0.5pt solid var(--border);border-radius:2pt;overflow:hidden;}}
.search-header{{font-size:7pt;letter-spacing:.16em;text-transform:uppercase;color:var(--text-dim);
  padding:4pt 10pt;background:#f0f0f0;border-bottom:0.5pt solid var(--border);}}
.search-row{{border-bottom:0.5pt solid var(--border);padding:6pt 10pt;break-inside:avoid;}}
.search-row:last-child{{border-bottom:none;}}
.search-type-label{{display:inline-block;font-size:7.5pt;letter-spacing:.1em;text-transform:uppercase;
  color:var(--charcoal-mid);font-weight:600;margin-right:6pt;}}
.search-instruction{{display:inline;font-size:9pt;color:var(--text-mid);line-height:1.5;}}
.search-note{{font-size:8pt;color:var(--text-dim);font-style:italic;margin-top:3pt;line-height:1.45;}}
.action-card{{border:0.5pt solid var(--border);border-radius:2pt;padding:12pt 14pt;margin-top:4pt;}}
.action-item{{padding:7pt 0;border-bottom:0.5pt solid var(--border);break-inside:avoid;overflow:hidden;}}
.action-item:last-child{{border-bottom:none;}}
.action-num{{display:inline-block;width:20pt;font-size:8.5pt;color:var(--charcoal);
  border:1pt solid var(--charcoal);text-align:center;padding:2pt 0;border-radius:2pt;font-weight:700;
  float:left;margin-right:10pt;margin-top:1pt;}}
.action-text{{display:block;overflow:hidden;font-size:9.5pt;color:var(--text);line-height:1.55;}}
"""


def build_strategy_package_html(client_name, pieces, target_title="", date=None):
    """Compose all available pieces into one client book with cover + TOC.
    `pieces` is {key: content}; positioning content is a JSON string."""
    today = date or datetime.now().strftime("%B %d, %Y")

    # Prepare section bodies keyed by section id.
    bodies = {}

    summary_md = pieces.get("summary")
    if summary_md:
        summary_md = _strip_leading_h1(summary_md)
        summary_md, action_md = _split_action_plan(summary_md)
        bodies["summary"] = _md_to_html(summary_md, strip_emoji=False)
        if action_md:
            bodies["actionplan"] = _md_to_html(action_md, strip_emoji=False)

    for key in ("branding", "ip", "stories", "roleplay"):
        md = pieces.get(key)
        if md:
            bodies[key] = _md_to_html(_strip_leading_h1(md), strip_emoji=False)

    pos_raw = pieces.get("positioning")
    if pos_raw:
        try:
            pos = json.loads(pos_raw) if isinstance(pos_raw, str) else pos_raw
            bodies["positioning"] = _positioning_body_html(pos)
            if not target_title:
                target_title = pos.get("targetTitle", "")
        except Exception:
            pass

    # Build ordered sections that actually have content.
    sections = [(k, title) for (k, title) in PACKAGE_ORDER if k in bodies]

    toc_items = "".join(
        f'<li><a href="#sec-{k}">{esc(title)}</a></li>' for k, title in sections
    )

    sections_html = ""
    for k, title in sections:
        is_positioning = (k == "positioning")
        body_class = "" if is_positioning else "pkg-body"
        sections_html += f"""<div class="pkg-section">
  <div class="pkg-section-eyebrow">Challenger, Gray &amp; Christmas  /  Strategy Package</div>
  <h1 id="sec-{k}" class="pkg-section-title">{esc(title)}</h1>
  <hr class="pkg-section-rule">
  <div class="{body_class}">{bodies[k]}</div>
</div>"""

    sub = esc(target_title) if target_title else "Career Transition Strategy"

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<style>{_package_css(client_name)}</style></head><body>
<div class="cover">
  <div>
    <div class="cover-eyebrow">Challenger, Gray &amp; Christmas</div>
    <div class="cover-name">{esc(client_name)}</div>
    <div class="cover-title">Strategy Package</div>
    <div class="cover-sub">{sub}</div>
  </div>
  <div class="cover-foot">Prepared {today}  •  Confidential — for {esc(client_name)}</div>
</div>
<div class="toc">
  <div class="toc-h">Contents</div>
  <ol>{toc_items}</ol>
</div>
{sections_html}
</body></html>"""


# ── Renderer ───────────────────────────────────────────────────────────────────
def render_pdf(html_content: str) -> bytes:
    font_config = FontConfiguration()
    buf = io.BytesIO()
    HTML(string=html_content).write_pdf(buf, font_config=font_config,
                                        presentational_hints=True)
    buf.seek(0)
    return buf.read()
