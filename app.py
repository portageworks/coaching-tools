from gevent import monkey
monkey.patch_all()

import os
import re
import json
import io
import queue
import threading
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_file
import anthropic

from prompts.session_generator import SYNTHESIS_SYSTEM, COACH_GUIDE_SYSTEM
from prompts.session_builder import (
    interview_program_prompt, stories_prompt,
    positioning_prompt, resume_diagnostic_prompt, resume_rewrite_prompt,
)
from prompts.session_builder_part2 import (
    summary_prompt, roleplay_a_prompt, roleplay_b_prompt,
    branding_prompt, training_prompt,
)
from docx_builder import markdown_to_docx
from resume_docx_builder import resume_to_docx
from pdf_builder import build_client_html, build_positioning_html, render_pdf

app = Flask(__name__)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


# ── Generic endpoints ─────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    messages = data.get("messages", [])
    system = data.get("system", "")
    model = data.get("model", "claude-sonnet-4-6")
    max_tokens = data.get("max_tokens", 8096)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return jsonify({"content": response.content[0].text})


# ── Session Generator ─────────────────────────────────────────────────────────

@app.route("/session-generator")
def session_generator():
    return render_template("session_generator.html")


@app.route("/api/session/generate", methods=["POST"])
def session_generate():
    data = request.get_json()
    prework = (data.get("prework") or "").strip()
    resume = (data.get("resume") or "").strip()

    if not prework or len(prework) < 100:
        return jsonify({"error": "Client pre-work is required."}), 400

    client_input = (
        f"PREWORK:\n\n{prework}\n\n---\n\nRESUME:\n\n{resume}"
        if resume
        else f"PREWORK:\n\n{prework}\n\n(No resume provided -- work from pre-work only)"
    )

    def _sse(event, data_obj):
        return f"event: {event}\ndata: {json.dumps(data_obj)}\n\n"

    def generate():
        yield _sse("step", {"step": 1})
        synthesis_chunks = []
        try:
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=12000,
                system=SYNTHESIS_SYSTEM,
                messages=[{"role": "user", "content":
                    f"Here is the client data:\n\n{client_input}\n\nProduce the complete synthesis."}],
            ) as stream:
                for text in stream.text_stream:
                    synthesis_chunks.append(text)
                    yield _sse("ping", {})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            return

        synthesis = "".join(synthesis_chunks)
        yield _sse("step", {"step": 2})

        guide_chunks = []
        try:
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=32000,
                system=COACH_GUIDE_SYSTEM,
                messages=[{"role": "user", "content":
                    f"Here is the client data:\n\n{client_input}\n\n---\n\nSYNTHESIS:\n\n{synthesis}\n\nProduce the complete coach session guide."}],
            ) as stream:
                for text in stream.text_stream:
                    guide_chunks.append(text)
                    yield _sse("guide_chunk", {"text": text})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            return

        yield _sse("done", {"guide": "".join(guide_chunks)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/session/guide.docx", methods=["POST"])
def session_guide_docx():
    data = request.get_json()
    guide_md = data.get("guide", "")
    first = (data.get("first_name") or "client").strip().lower()
    last = (data.get("last_name") or "").strip().lower()
    slug = re.sub(r"\s+", "_", f"{first}_{last}".strip("_"))

    docx_bytes = markdown_to_docx(guide_md)
    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"{slug}_coach_guide.docx",
    )


# ── Session Builder ───────────────────────────────────────────────────────────

@app.route("/session-builder")
def session_builder():
    return render_template("session_builder.html")


@app.route("/api/builder/generate", methods=["POST"])
def builder_generate():
    data        = request.get_json()
    transcript  = (data.get("transcript") or "").strip()
    resume      = (data.get("resume") or "").strip()
    intake      = (data.get("intake") or "").strip()
    client_name = (data.get("client_name") or "").strip()

    if not transcript:
        return jsonify({"error": "Transcript is required."}), 400
    if not client_name:
        return jsonify({"error": "Client name is required."}), 400

    def _user_msg():
        msg = f"Here is the session transcript:\n\n{transcript}"
        if resume:
            msg += f"\n\n---\nRESUME:\n\n{resume}"
        if intake:
            msg += f"\n\n---\nINTAKE ANSWERS:\n\n{intake}"
        return msg

    def _sse(event, obj):
        return f"event: {event}\ndata: {json.dumps(obj)}\n\n"

    # Each job runs in its own thread and posts results to a queue
    q = queue.Queue()

    JOBS = [
        ("ip",          interview_program_prompt(client_name), 16000),
        ("stories",     stories_prompt(client_name),           16000),
        ("positioning", positioning_prompt(client_name, bool(resume), bool(intake)), 8000),
    ]

    def run_job(job_id, system_prompt, max_tokens):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": _user_msg()}],
            )
            content = (resp.content[0].text or "").strip()
            q.put(("done", job_id, content))
        except Exception as e:
            q.put(("error", job_id, str(e)))

    def run_resume_job():
        try:
            # Step 1: diagnostic brief
            diag_resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=resume_diagnostic_prompt(),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            brief_raw = (diag_resp.content[0].text or "").strip()
            brief_raw = brief_raw.replace("```json", "").replace("```", "").strip()

            # Step 2: rewrite informed by brief
            rewrite_msg = f"STRATEGY BRIEF:\n{brief_raw}\n\n---\n\n{_user_msg()}"
            rewrite_resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8000,
                system=resume_rewrite_prompt(),
                messages=[{"role": "user", "content": rewrite_msg}],
            )
            content = (rewrite_resp.content[0].text or "").strip()
            q.put(("done", "resume", content))
        except Exception as e:
            q.put(("error", "resume", str(e)))

    def generate():
        # Signal all jobs as running
        for job_id, _, _ in JOBS:
            yield _sse("status", {"id": job_id, "state": "running"})
        yield _sse("status", {"id": "resume", "state": "running"})

        # Launch all jobs in parallel threads
        threads = []
        for job_id, system_prompt, max_tokens in JOBS:
            t = threading.Thread(target=run_job, args=(job_id, system_prompt, max_tokens), daemon=True)
            t.start()
            threads.append(t)
        t = threading.Thread(target=run_resume_job, daemon=True)
        t.start()
        threads.append(t)

        # Stream results as each job completes
        remaining = len(JOBS) + 1  # +1 for resume
        while remaining > 0:
            try:
                event_type, job_id, payload = q.get(timeout=300)
            except queue.Empty:
                yield _sse("error", {"id": "all", "message": "Timeout waiting for results."})
                return

            remaining -= 1
            if event_type == "done":
                yield _sse("result", {"id": job_id, "state": "done", "content": payload})
            else:
                yield _sse("result", {"id": job_id, "state": "error", "message": payload})

        yield _sse("complete", {})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/builder/resume.docx", methods=["POST"])
def builder_resume_docx():
    data        = request.get_json()
    resume_text = data.get("content", "")
    client_name = (data.get("client_name") or "client").strip()

    docx_bytes = resume_to_docx(resume_text)

    # Build filename: LastName_FirstName_Resume.docx
    parts = client_name.split()
    if len(parts) >= 2:
        filename = f"{parts[-1]}_{parts[0]}_Resume.docx"
    else:
        filename = f"{client_name.replace(' ', '_')}_Resume.docx"

    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/api/builder/ip.pdf", methods=["POST"])
def builder_ip_pdf():
    data        = request.get_json()
    content     = data.get("content", "")
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    pdf_bytes   = render_pdf(build_client_html(content, client_name, "Interview Program"))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_interview_program.pdf")


@app.route("/api/builder/stories.pdf", methods=["POST"])
def builder_stories_pdf():
    data        = request.get_json()
    content     = data.get("content", "")
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    pdf_bytes   = render_pdf(build_client_html(content, client_name, "Success Stories"))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_success_stories.pdf")


@app.route("/api/builder/positioning.pdf", methods=["POST"])
def builder_positioning_pdf():
    data        = request.get_json()
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    pos_data    = data.get("positioning")
    if isinstance(pos_data, str):
        pos_data = json.loads(pos_data)
    pdf_bytes = render_pdf(build_positioning_html(pos_data, client_name))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_where_to_look.pdf")


# ── Session Builder Part 2 ────────────────────────────────────────────────────

@app.route("/session-builder-part2")
def session_builder_part2():
    return render_template("session_builder_part2.html")


@app.route("/api/builder2/generate", methods=["POST"])
def builder2_generate():
    data        = request.get_json()
    transcript  = (data.get("transcript") or "").strip()
    resume      = (data.get("resume") or "").strip()
    intake      = (data.get("intake") or "").strip()
    client_name = (data.get("client_name") or "").strip()

    if not transcript:
        return jsonify({"error": "Transcript is required."}), 400
    if not client_name:
        return jsonify({"error": "Client name is required."}), 400

    def _user_msg():
        msg = f"Here is the session transcript:\n\n{transcript}"
        if resume:
            msg += f"\n\n---\nRESUME:\n\n{resume}"
        if intake:
            msg += f"\n\n---\nINTAKE ANSWERS:\n\n{intake}"
        return msg

    def _sse(event, obj):
        return f"event: {event}\ndata: {json.dumps(obj)}\n\n"

    q = queue.Queue()

    def run_job(job_id, system_prompt, max_tokens):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": _user_msg()}],
            )
            q.put(("done", job_id, (resp.content[0].text or "").strip()))
        except Exception as e:
            q.put(("error", job_id, str(e)))

    def run_roleplay_job():
        try:
            resp_a = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=16000,
                system=roleplay_a_prompt(client_name),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            part_a = (resp_a.content[0].text or "").strip()
            resp_b = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=16000,
                system=roleplay_b_prompt(client_name),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            part_b = (resp_b.content[0].text or "").strip()
            q.put(("done", "roleplay", part_a + "\n\n---\n\n" + part_b))
        except Exception as e:
            q.put(("error", "roleplay", str(e)))

    JOBS = [
        ("summary",  summary_prompt(client_name),                          12000),
        ("branding", branding_prompt(client_name, bool(resume), bool(intake)), 12000),
        ("training", training_prompt(client_name),                          8000),
    ]

    def generate():
        for job_id, _, _ in JOBS:
            yield _sse("status", {"id": job_id, "state": "running"})
        yield _sse("status", {"id": "roleplay", "state": "running"})

        threads = []
        for job_id, system_prompt, max_tokens in JOBS:
            t = threading.Thread(target=run_job, args=(job_id, system_prompt, max_tokens), daemon=True)
            t.start()
            threads.append(t)
        t = threading.Thread(target=run_roleplay_job, daemon=True)
        t.start()
        threads.append(t)

        remaining = len(JOBS) + 1
        while remaining > 0:
            try:
                event_type, job_id, payload = q.get(timeout=600)
            except queue.Empty:
                yield _sse("error", {"id": "all", "message": "Timeout waiting for results."})
                return
            remaining -= 1
            if event_type == "done":
                yield _sse("result", {"id": job_id, "state": "done", "content": payload})
            else:
                yield _sse("result", {"id": job_id, "state": "error", "message": payload})

        yield _sse("complete", {})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/builder2/summary.pdf", methods=["POST"])
def builder2_summary_pdf():
    data        = request.get_json()
    content     = data.get("content", "")
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    pdf_bytes   = render_pdf(build_client_html(content, client_name, "Strategy Session Summary"))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_session_summary.pdf")


@app.route("/api/builder2/roleplay.pdf", methods=["POST"])
def builder2_roleplay_pdf():
    data        = request.get_json()
    content     = data.get("content", "")
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    pdf_bytes   = render_pdf(build_client_html(content, client_name, "Roleplay Interview Analysis"))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_roleplay_analysis.pdf")


@app.route("/api/builder2/branding.pdf", methods=["POST"])
def builder2_branding_pdf():
    data        = request.get_json()
    content     = data.get("content", "")
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    pdf_bytes   = render_pdf(build_client_html(content, client_name, "Branding Profile"))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_branding_profile.pdf")


@app.route("/api/builder2/training.html", methods=["POST"])
def builder2_training_html():
    import markdown as md_lib
    data        = request.get_json()
    content     = data.get("content", "")
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    from datetime import date
    today = date.today().strftime("%B %d, %Y")
    rendered = md_lib.markdown(content, extensions=["extra"])
    html_out = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Training Assessment — {client_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@400;700&family=Roboto:wght@300;400;600&family=Roboto+Mono&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'Roboto',sans-serif;font-size:15px;line-height:1.7;color:#2c3035;background:#f5f3f0;padding:40px 20px;}}
.doc{{max-width:780px;margin:0 auto;background:#fff;border:1px solid #ddd;border-radius:4px;overflow:hidden;}}
.doc-header{{background:#1e2022;padding:28px 40px 22px;}}
.doc-header-label{{font-family:'Roboto Mono',monospace;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:#5579a0;margin-bottom:6px;}}
.doc-header-name{{font-family:'Roboto Slab',serif;font-size:26px;font-weight:700;color:#fff;line-height:1.1;}}
.doc-header-sub{{font-size:12px;font-weight:300;color:#9ba0a6;margin-top:4px;}}
.doc-body{{padding:36px 40px 48px;}}
.doc-body h1{{font-family:'Roboto Slab',serif;font-size:20px;font-weight:700;color:#1e2022;margin:32px 0 10px;padding-bottom:7px;border-bottom:2px solid #3a5a7c;}}
.doc-body h1:first-child{{margin-top:0;}}
.doc-body h2{{font-family:'Roboto Slab',serif;font-size:16px;font-weight:600;color:#3a5a7c;margin:22px 0 7px;}}
.doc-body h3{{font-size:14px;font-weight:600;color:#1e2022;margin:16px 0 5px;}}
.doc-body p{{margin-bottom:11px;}}
.doc-body ul,.doc-body ol{{margin:6px 0 11px 22px;}}
.doc-body li{{margin-bottom:5px;}}
.doc-body blockquote{{border-left:3px solid #3a5a7c;padding:10px 0 10px 18px;margin:14px 0;background:#eef4fb;border-radius:0 2px 2px 0;}}
.doc-body blockquote p{{margin-bottom:0;font-style:italic;}}
.doc-body strong{{font-weight:600;color:#1e2022;}}
.doc-body hr{{border:none;border-top:1px solid #e0dbd4;margin:22px 0;}}
.doc-footer{{padding:14px 40px;border-top:1px solid #e0dbd4;font-family:'Roboto Mono',monospace;font-size:10px;color:#9ba0a6;letter-spacing:.08em;display:flex;justify-content:space-between;}}
</style></head><body>
<div class="doc">
  <div class="doc-header">
    <div class="doc-header-label">Coach Reference Only</div>
    <div class="doc-header-name">{client_name}</div>
    <div class="doc-header-sub">Training Assessment</div>
  </div>
  <div class="doc-body">{rendered}</div>
  <div class="doc-footer"><span>{client_name} — Training Assessment</span><span>{today}</span></div>
</div>
</body></html>"""
    return send_file(
        io.BytesIO(html_out.encode("utf-8")),
        mimetype="text/html",
        as_attachment=True,
        download_name=f"{slug}_training_assessment.html",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
