/* Prompt Library — client-side fill-in, search, and copy.
   Generation (calling Claude inline) is layered on in Phase 3. */
let activeFilter = 'all';

function toggleCard(toggleEl) {
  const body = toggleEl.nextElementSibling;
  const arrow = toggleEl.querySelector('.toggle-arrow');
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  arrow.classList.toggle('open', !isOpen);
  if (!isOpen) renderPrompt(body);
}

function renderPrompt(body) {
  const box = body.querySelector('.prompt-box');
  if (!box) return;
  const template = box.dataset.template;
  if (!template) return;
  const fields = body.querySelectorAll('.field-input');
  let rendered = template;
  fields.forEach(f => {
    const placeholder = f.dataset.field;
    const val = f.value.trim();
    if (val) {
      rendered = rendered.split('[' + placeholder + ']').join(val);
    }
  });
  // Highlight remaining unfilled placeholders
  rendered = rendered.replace(/\[([^\]]+)\]/g, (m, p1) =>
    `<span class="placeholder">[${p1}]</span>`
  );
  box.innerHTML = rendered;
}

function updatePrompt(inputEl) {
  const body = inputEl.closest('.card-body');
  if (body && body.classList.contains('open')) renderPrompt(body);
}

function copyPrompt(btn) {
  const body = btn.closest('.card-body');
  const box = body.querySelector('.prompt-box');
  if (!box) return;
  // Get plain text — strip placeholder spans
  const text = box.innerText || box.textContent;
  navigator.clipboard.writeText(text).then(() => {
    btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M3 8l4 4 6-6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg> Copied!';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.innerHTML = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><rect x="5" y="5" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M3 11H2.5A1.5 1.5 0 0 1 1 9.5v-7A1.5 1.5 0 0 1 2.5 1h7A1.5 1.5 0 0 1 11 2.5V3" stroke="currentColor" stroke-width="1.5"/></svg> Copy prompt';
      btn.classList.remove('copied');
    }, 2000);
  }).catch(() => {
    const range = document.createRange();
    range.selectNodeContents(box);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
  });
}

/* ── Inline generation ─────────────────────────────────────────────────── */

// Minimal, dependency-free Markdown -> HTML for Claude's output. HTML is escaped
// FIRST, so model output can never inject markup (XSS-safe), then a small subset
// (headings, bold/italic, inline code, lists, rules) is formatted.
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderInline(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
}

function renderMarkdown(md) {
  const lines = escapeHtml(md).split('\n');
  let html = '', listType = null, m;
  const closeList = () => { if (listType) { html += `</${listType}>`; listType = null; } };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '');
    if (!line.trim()) { closeList(); continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) { closeList(); html += '<hr>'; continue; }
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { closeList(); const n = m[1].length; html += `<h${n}>${renderInline(m[2])}</h${n}>`; continue; }
    if ((m = line.match(/^\s*[-*]\s+(.*)$/))) { if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; } html += `<li>${renderInline(m[1])}</li>`; continue; }
    if ((m = line.match(/^\s*\d+\.\s+(.*)$/))) { if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; } html += `<li>${renderInline(m[1])}</li>`; continue; }
    closeList();
    html += `<p>${renderInline(line)}</p>`;
  }
  closeList();
  return html;
}

/* Cloudflare Turnstile — fetch a fresh token per generation (invisible until a
   challenge is actually needed). A no-op when the widget isn't configured, so
   nothing changes until TURNSTILE_SITE_KEY is set server-side. */
let _tsWidgetId = null, _tsResolve = null;

function initTurnstile() {
  if (!window.TURNSTILE_SITE_KEY) return;
  const render = () => {
    if (!(window.turnstile && document.getElementById('turnstile-widget'))) {
      return setTimeout(render, 200);  // wait for Cloudflare's async script
    }
    _tsWidgetId = window.turnstile.render('#turnstile-widget', {
      sitekey: window.TURNSTILE_SITE_KEY,
      execution: 'execute',          // don't run until we ask
      appearance: 'interaction-only', // stay invisible unless a challenge is needed
      callback: t => { if (_tsResolve) { _tsResolve(t); _tsResolve = null; } },
      'error-callback': () => { if (_tsResolve) { _tsResolve(''); _tsResolve = null; } },
    });
  };
  render();
}
document.addEventListener('DOMContentLoaded', initTurnstile);

function getTurnstileToken() {
  if (!window.TURNSTILE_SITE_KEY || _tsWidgetId === null) return Promise.resolve('');
  return new Promise(resolve => {
    _tsResolve = resolve;
    try { window.turnstile.reset(_tsWidgetId); window.turnstile.execute(_tsWidgetId); }
    catch (e) { _tsResolve = null; return resolve(''); }
    setTimeout(() => { if (_tsResolve) { _tsResolve(''); _tsResolve = null; } }, 15000);
  });
}

function onResumeFile(input) {
  const label = input.closest('.gen-file-pick').querySelector('.gen-file-name');
  const file = input.files && input.files[0];
  if (file) {
    label.textContent = file.name;
    label.classList.add('has-file');
  } else {
    label.textContent = 'Choose a PDF, Word, or text file';
    label.classList.remove('has-file');
  }
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(new Error('Could not read that file.'));
    r.readAsDataURL(file);
  });
}

async function generate(btn) {
  const card = btn.closest('.prompt-card');
  const body = btn.closest('.card-body');
  const status = card.querySelector('.gen-status');
  const resultWrap = card.querySelector('.gen-result');
  const output = card.querySelector('.gen-output');

  // Collect the short fill-in fields.
  const fields = {};
  body.querySelectorAll('.field-input').forEach(f => {
    const v = f.value.trim();
    if (v) fields[f.dataset.field] = v;
  });

  // Resume: uploaded file takes priority over pasted text.
  let resume = null;
  const fileEl = card.querySelector('.gen-file');
  const pasteEl = card.querySelector('.gen-resume-text');
  try {
    if (fileEl && fileEl.files && fileEl.files[0]) {
      const file = fileEl.files[0];
      resume = { kind: 'file', data: await readFileAsDataURL(file), mime: file.type, name: file.name };
    } else if (pasteEl && pasteEl.value.trim()) {
      resume = { kind: 'text', text: pasteEl.value.trim() };
    }
  } catch (e) {
    status.textContent = e.message;
    status.classList.add('error');
    return;
  }

  const jdEl = card.querySelector('.gen-jd');
  const clEl = card.querySelector('.gen-cl');
  const extras = {};
  card.querySelectorAll('.gen-extra').forEach(el => {
    const v = el.value.trim();
    if (v) extras[el.dataset.key] = v;
  });
  const payload = {
    id: card.dataset.id,
    fields,
    resume,
    job_description: jdEl ? jdEl.value.trim() : '',
    cover_letter: clEl ? clEl.value.trim() : '',
    extras,
  };

  btn.disabled = true;
  btn.classList.add('loading');
  status.classList.remove('error');
  status.textContent = 'Generating…';
  output.textContent = '';
  resultWrap.style.display = 'block';

  payload.turnstile_token = await getTurnstileToken();

  let accumulated = '';
  try {
    const res = await fetch('/api/prompt-library/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let msg = `Error ${res.status}`;
      try { msg = (await res.json()).error || msg; } catch (e) {}
      throw new Error(msg);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '', lastEvent = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith('event: ')) { lastEvent = line.slice(7).trim(); continue; }
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6);
        if (raw === '[DONE]') { buffer = ''; break; }
        if (lastEvent === 'error') throw new Error(JSON.parse(raw));
        accumulated += JSON.parse(raw);
        output.innerHTML = renderMarkdown(accumulated);
        resultWrap.scrollIntoView({ block: 'nearest' });
      }
    }
    status.textContent = '';
  } catch (e) {
    status.textContent = e.message || 'Something went wrong. Please try again.';
    status.classList.add('error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
  }
}

function copyResult(btn) {
  const output = btn.closest('.gen-result').querySelector('.gen-output');
  const text = output.innerText || output.textContent;
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy result'; btn.classList.remove('copied'); }, 2000);
  });
}

function setFilter(cat, btn) {
  activeFilter = cat;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterPrompts();
}

function filterPrompts() {
  const query = document.getElementById('searchInput').value.toLowerCase().trim();
  let visible = 0;

  document.querySelectorAll('.prompt-card').forEach(card => {
    const catMatch = activeFilter === 'all' || card.dataset.cat === activeFilter;
    const searchMatch = !query || card.dataset.search.includes(query) ||
      card.querySelector('.card-title').textContent.toLowerCase().includes(query) ||
      card.querySelector('.card-purpose').textContent.toLowerCase().includes(query);
    const show = catMatch && searchMatch;
    card.classList.toggle('hidden', !show);
    if (show) visible++;
  });

  // Show/hide category headers
  document.querySelectorAll('.category-section').forEach(section => {
    const visibleCards = section.querySelectorAll('.prompt-card:not(.hidden)').length;
    section.style.display = visibleCards ? '' : 'none';
  });

  document.getElementById('noResults').style.display = visible ? 'none' : 'block';
}
