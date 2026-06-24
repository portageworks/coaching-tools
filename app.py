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

from prompts.session_generator import SYNTHESIS_SYSTEM, COACH_GUIDE_SYSTEM, WORKSHEET_SYSTEM
from prompts.session_builder import (
    interview_program_prompt, stories_prompt,
    positioning_prompt, resume_diagnostic_prompt, resume_rewrite_prompt,
)
from prompts.resume_tool import DIAGNOSTIC_SYSTEM, REWRITE_SYSTEM
from prompts.session_builder_part2 import (
    summary_prompt, roleplay_a_prompt, roleplay_b_prompt,
    branding_prompt, training_prompt,
)
from docx_builder import markdown_to_docx
from resume_docx_builder import resume_to_docx
from pdf_builder import (
    build_client_html, build_positioning_html, build_strategy_package_html,
    build_worksheet_html, render_pdf,
)
import strategy_store

app = Flask(__name__)

# max_retries handles transient API failures (overloaded, rate limits, timeouts,
# 5xx) with exponential backoff so a run succeeds the first time instead of
# erroring out and forcing a full re-run. Default is 2; raised for reliability.
client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    max_retries=5,
)

# ── Model selection ───────────────────────────────────────────────────────────
# SMART = higher-quality, client-facing deliverables (resume rewrites, branding,
#         session guides, roleplay). FAST = cheap internal jobs (diagnostics,
#         coach-only training notes). Flip these in one place.
def complete_json(system, user_content, model, max_tokens, attempts=3):
    """Call the model and parse a JSON object from its reply. If the reply
    isn't valid JSON, hand the model its own output back with a correction and
    re-ask, up to `attempts` times. This catches malformed-JSON failures, which
    the client's transient-error retries do not. Raises ValueError if it never
    returns parseable JSON."""
    messages = [{"role": "user", "content": user_content}]
    last_raw = ""
    for _ in range(attempts):
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system, messages=messages,
        )
        last_raw = (resp.content[0].text or "").strip()
        cleaned = last_raw.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            messages = [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": last_raw},
                {"role": "user", "content": "That was not valid JSON. Reply with ONLY "
                 "the JSON object — no preface, no explanation, no markdown code fences."},
            ]
    raise ValueError(f"Model did not return valid JSON after {attempts} attempts. "
                     f"Last reply began: {last_raw[:200]}")


MODEL_SMART = "claude-opus-4-8"
MODEL_FAST  = "claude-sonnet-4-6"


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


# ── Resume Tool ───────────────────────────────────────────────────────────────

@app.route("/resume-tool")
def resume_tool():
    return render_template("resume_tool.html")


@app.route("/api/resume/diagnose", methods=["POST"])
def resume_diagnose():
    data       = request.get_json()
    resume     = (data.get("resume") or "").strip()
    transcript = (data.get("transcript") or "").strip()
    target     = (data.get("target") or "").strip()

    if not resume:
        return jsonify({"error": "Resume text is required."}), 400

    user_msg = f"RESUME:\n\n{resume}"
    if target:
        user_msg += f"\n\n---\nTARGET POSITIONING:\n\n{target}"
    if transcript:
        user_msg += f"\n\n---\nSESSION TRANSCRIPT (Primary Truth — overrides resume where they conflict):\n\n{transcript}"

    try:
        result = complete_json(DIAGNOSTIC_SYSTEM, user_msg, MODEL_FAST, 4000)
    except Exception as e:
        return jsonify({"error": f"Evaluation failed: {e}"}), 500
    return jsonify(result)


@app.route("/api/resume/rewrite", methods=["POST"])
def resume_rewrite():
    data       = request.get_json()
    resume     = (data.get("resume") or "").strip()
    transcript = (data.get("transcript") or "").strip()
    target     = (data.get("target") or "").strip()
    diag       = data.get("diagnostic") or {}

    if not resume:
        return jsonify({"error": "Resume text is required."}), 400

    level = diag.get("level", "EXECUTIVE")
    score = diag.get("readinessScore", 5)
    mode  = diag.get("revisionMode", "REWRITE")

    user_msg  = f"CANDIDATE LEVEL: {level}\n"
    user_msg += f"READINESS SCORE: {score}/10\n"
    user_msg += f"REVISION MODE: {mode}\n\n"
    user_msg += "STRATEGY BRIEF:\n"
    user_msg += f"Strengths to Preserve: {diag.get('strengths', '')}\n"
    user_msg += f"Narrative Arc: {diag.get('narrativeArc', '')}\n"
    user_msg += f"Impact Opportunities: {diag.get('impactOpportunities', '')}\n"
    user_msg += f"Keyword Alignment: {diag.get('keywordAlignment', '')}\n"
    user_msg += f"Positioning Hypothesis: {diag.get('positioningHypothesis', '')}\n\n"
    user_msg += f"RESUME:\n\n{resume}"
    if target:
        user_msg += f"\n\n---\nTARGET POSITIONING:\n\n{target}"
    if transcript:
        user_msg += f"\n\n---\nSESSION TRANSCRIPT (Primary Truth):\n\n{transcript}"

    resp = client.messages.create(
        model=MODEL_SMART,
        max_tokens=8000,
        system=REWRITE_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    content = (resp.content[0].text or "").strip()
    return jsonify({"content": content})


@app.route("/api/resume/download.docx", methods=["POST"])
def resume_download_docx():
    data        = request.get_json()
    resume_text = data.get("content", "")
    font        = (data.get("font") or "Calibri").strip()

    docx_bytes = resume_to_docx(resume_text, font=font)

    first_line = resume_text.strip().splitlines()[0] if resume_text.strip() else ""
    import re as _re
    name = _re.sub(r"[^a-zA-Z\s'-]", "", first_line).strip()
    parts = name.split()
    if len(parts) >= 2:
        filename = f"{parts[-1]}_{parts[0]}_Resume.docx"
    elif parts:
        filename = f"{parts[0]}_Resume.docx"
    else:
        filename = "Resume.docx"

    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


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
                model=MODEL_SMART,
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
                model=MODEL_SMART,
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

        guide = "".join(guide_chunks)
        yield _sse("step", {"step": 3})

        worksheet_chunks = []
        try:
            with client.messages.stream(
                model=MODEL_FAST,
                max_tokens=16000,
                system=WORKSHEET_SYSTEM,
                messages=[{"role": "user", "content":
                    f"Here is the client data:\n\n{client_input}\n\n---\n\nSYNTHESIS:\n\n{synthesis}\n\n---\n\nCOACH GUIDE:\n\n{guide}\n\nProduce the lean session worksheet."}],
            ) as stream:
                for text in stream.text_stream:
                    worksheet_chunks.append(text)
                    yield _sse("ping", {})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            return

        yield _sse("done", {"guide": guide, "worksheet": "".join(worksheet_chunks)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _session_slug(data):
    first = (data.get("first_name") or "client").strip().lower()
    last  = (data.get("last_name") or "").strip().lower()
    return re.sub(r"\s+", "_", f"{first}_{last}".strip("_")) or "client"


def _client_full_name(data):
    return " ".join(p for p in [(data.get("first_name") or "").strip(),
                                (data.get("last_name") or "").strip()] if p) or "Client"


@app.route("/api/session/reference.pdf", methods=["POST"])
def session_reference_pdf():
    data       = request.get_json()
    guide_md   = data.get("guide", "")
    name       = _client_full_name(data)
    slug       = _session_slug(data)
    pdf_bytes  = render_pdf(build_client_html(guide_md, name, "Coach Reference"))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_coach_reference.pdf")


@app.route("/api/session/worksheet.pdf", methods=["POST"])
def session_worksheet_pdf():
    data          = request.get_json()
    worksheet_md  = data.get("worksheet", "")
    name          = _client_full_name(data)
    slug          = _session_slug(data)
    pdf_bytes     = render_pdf(build_worksheet_html(worksheet_md, name))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_session_worksheet.pdf")


@app.route("/api/session/guide.docx", methods=["POST"])
def session_guide_docx():
    data = request.get_json()
    guide_md = data.get("guide", "")
    slug = _session_slug(data)
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
    client_id   = (data.get("client_id") or "").strip()

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
        ("positioning", positioning_prompt(client_name, bool(resume), bool(intake)), 16000),
    ]

    def run_job(job_id, system_prompt, max_tokens):
        try:
            if job_id == "positioning":
                # Positioning returns a large structured JSON object. Route it
                # through complete_json so a truncated/malformed reply self-heals
                # and a genuine failure surfaces as an error instead of being
                # silently dropped at package-build time.
                data = complete_json(system_prompt, _user_msg(), MODEL_SMART, max_tokens)
                content = json.dumps(data)
            else:
                resp = client.messages.create(
                    model=MODEL_SMART,
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
                model=MODEL_FAST,
                max_tokens=1500,
                system=resume_diagnostic_prompt(),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            brief_raw = (diag_resp.content[0].text or "").strip()
            brief_raw = brief_raw.replace("```json", "").replace("```", "").strip()

            # Step 2: rewrite informed by brief
            rewrite_msg = f"STRATEGY BRIEF:\n{brief_raw}\n\n---\n\n{_user_msg()}"
            rewrite_resp = client.messages.create(
                model=MODEL_SMART,
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
                try:
                    strategy_store.save_piece(client_name, job_id, payload, client_id=client_id)
                except Exception:
                    pass
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
    font        = (data.get("font") or "Calibri").strip()

    docx_bytes = resume_to_docx(resume_text, font=font)

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
    client_id   = (data.get("client_id") or "").strip()

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
            # Training is coach-only internal notes; everything else is client-facing.
            job_model = MODEL_FAST if job_id == "training" else MODEL_SMART
            resp = client.messages.create(
                model=job_model,
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
                model=MODEL_SMART,
                max_tokens=16000,
                system=roleplay_a_prompt(client_name),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            part_a = (resp_a.content[0].text or "").strip()
            resp_b = client.messages.create(
                model=MODEL_SMART,
                max_tokens=16000,
                system=roleplay_b_prompt(client_name),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            part_b = (resp_b.content[0].text or "").strip()
            q.put(("done", "roleplay", part_a + "\n\n" + part_b))
        except Exception as e:
            q.put(("error", "roleplay", str(e)))

    def run_resume_job():
        try:
            diag_msg = f"RESUME:\n\n{resume}" if resume else "No resume provided."
            if transcript:
                diag_msg += f"\n\n---\nSESSION TRANSCRIPT (Primary Truth — overrides resume where they conflict):\n\n{transcript}"
            diag = complete_json(DIAGNOSTIC_SYSTEM, diag_msg, MODEL_FAST, 2000)

            rw_msg = f"CANDIDATE LEVEL: {diag.get('level','EXECUTIVE')}\n"
            rw_msg += f"READINESS SCORE: {diag.get('readinessScore', 5)}/10\n"
            rw_msg += f"REVISION MODE: {diag.get('revisionMode','REWRITE')}\n\n"
            rw_msg += f"STRATEGY BRIEF:\n"
            rw_msg += f"Strengths to Preserve: {diag.get('strengths','')}\n"
            rw_msg += f"Narrative Arc: {diag.get('narrativeArc','')}\n"
            rw_msg += f"Impact Opportunities: {diag.get('impactOpportunities','')}\n"
            rw_msg += f"Keyword Alignment: {diag.get('keywordAlignment','')}\n"
            rw_msg += f"Positioning Hypothesis: {diag.get('positioningHypothesis','')}\n\n"
            if resume:
                rw_msg += f"RESUME:\n\n{resume}"
            if transcript:
                rw_msg += f"\n\n---\nSESSION TRANSCRIPT (Primary Truth):\n\n{transcript}"
            rw_resp = client.messages.create(
                model=MODEL_SMART,
                max_tokens=8000,
                system=REWRITE_SYSTEM,
                messages=[{"role": "user", "content": rw_msg}],
            )
            q.put(("done", "resume", (rw_resp.content[0].text or "").strip()))
        except Exception as e:
            q.put(("error", "resume", str(e)))

    JOBS = [
        ("summary",  summary_prompt(client_name),                          12000),
        ("branding", branding_prompt(client_name, bool(resume), bool(intake)), 12000),
        ("training", training_prompt(client_name),                          8000),
    ]

    def generate():
        for job_id, _, _ in JOBS:
            yield _sse("status", {"id": job_id, "state": "running"})
        yield _sse("status", {"id": "roleplay", "state": "running"})
        yield _sse("status", {"id": "resume", "state": "running"})

        threads = []
        for job_id, system_prompt, max_tokens in JOBS:
            t = threading.Thread(target=run_job, args=(job_id, system_prompt, max_tokens), daemon=True)
            t.start()
            threads.append(t)
        t = threading.Thread(target=run_roleplay_job, daemon=True)
        t.start()
        threads.append(t)
        t = threading.Thread(target=run_resume_job, daemon=True)
        t.start()
        threads.append(t)

        remaining = len(JOBS) + 2
        while remaining > 0:
            try:
                event_type, job_id, payload = q.get(timeout=600)
            except queue.Empty:
                yield _sse("error", {"id": "all", "message": "Timeout waiting for results."})
                return
            remaining -= 1
            if event_type == "done":
                try:
                    strategy_store.save_piece(client_name, job_id, payload, client_id=client_id)
                except Exception:
                    pass
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


@app.route("/api/builder2/resume.docx", methods=["POST"])
def builder2_resume_docx():
    data        = request.get_json()
    content     = data.get("content", "")
    font        = (data.get("font") or "Calibri").strip()
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    docx_bytes  = resume_to_docx(content, font=font)
    return send_file(io.BytesIO(docx_bytes), mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     as_attachment=True, download_name=f"{slug}_resume.docx")


@app.route("/api/builder2/training.pdf", methods=["POST"])
def builder2_training_pdf():
    data        = request.get_json()
    content     = data.get("content", "")
    client_name = (data.get("client_name") or "client").strip()
    slug        = re.sub(r"[^a-z0-9_]", "", client_name.lower().replace(" ", "_"))
    pdf_bytes   = render_pdf(build_client_html(
        content, client_name, "Training Assessment — Coach Reference",
        eyebrow="Challenger, Gray &amp; Christmas  /  Coach Reference",
    ))
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_training_assessment.pdf")


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


# ── All-in-one (full day: both runs + package build) ────────────────────────────

@app.route("/full-session")
def full_session_page():
    return render_template("full_session.html")


@app.route("/api/full/generate", methods=["POST"])
def full_generate():
    data        = request.get_json()
    transcript  = (data.get("transcript") or "").strip()
    resume      = (data.get("resume") or "").strip()
    intake      = (data.get("intake") or "").strip()
    client_name = (data.get("client_name") or "").strip()
    client_id   = (data.get("client_id") or "").strip()

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

    # Single-call jobs: (id, system_prompt, max_tokens, model)
    JOBS = [
        ("ip",          interview_program_prompt(client_name),                       16000, MODEL_SMART),
        ("stories",     stories_prompt(client_name),                                 16000, MODEL_SMART),
        ("summary",     summary_prompt(client_name),                                 12000, MODEL_SMART),
        ("branding",    branding_prompt(client_name, bool(resume), bool(intake)),    12000, MODEL_SMART),
        ("positioning", positioning_prompt(client_name, bool(resume), bool(intake)), 16000, MODEL_SMART),
        ("training",    training_prompt(client_name),                                 8000, MODEL_FAST),
    ]

    def run_job(job_id, system_prompt, max_tokens, model):
        try:
            if job_id == "positioning":
                # Positioning returns a large structured JSON object. Route it
                # through complete_json so a truncated/malformed reply self-heals
                # and a genuine failure surfaces as an error instead of being
                # silently dropped at package-build time.
                data = complete_json(system_prompt, _user_msg(), model, max_tokens)
                q.put(("done", job_id, json.dumps(data)))
                return
            resp = client.messages.create(
                model=model, max_tokens=max_tokens, system=system_prompt,
                messages=[{"role": "user", "content": _user_msg()}],
            )
            q.put(("done", job_id, (resp.content[0].text or "").strip()))
        except Exception as e:
            q.put(("error", job_id, str(e)))

    def run_roleplay_job():
        try:
            resp_a = client.messages.create(
                model=MODEL_SMART, max_tokens=16000, system=roleplay_a_prompt(client_name),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            part_a = (resp_a.content[0].text or "").strip()
            resp_b = client.messages.create(
                model=MODEL_SMART, max_tokens=16000, system=roleplay_b_prompt(client_name),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            part_b = (resp_b.content[0].text or "").strip()
            q.put(("done", "roleplay", part_a + "\n\n" + part_b))
        except Exception as e:
            q.put(("error", "roleplay", str(e)))

    def run_resume_job():
        try:
            diag_resp = client.messages.create(
                model=MODEL_FAST, max_tokens=1500, system=resume_diagnostic_prompt(),
                messages=[{"role": "user", "content": _user_msg()}],
            )
            brief = (diag_resp.content[0].text or "").strip().replace("```json", "").replace("```", "").strip()
            rewrite_msg = f"STRATEGY BRIEF:\n{brief}\n\n---\n\n{_user_msg()}"
            rewrite_resp = client.messages.create(
                model=MODEL_SMART, max_tokens=8000, system=resume_rewrite_prompt(),
                messages=[{"role": "user", "content": rewrite_msg}],
            )
            q.put(("done", "resume", (rewrite_resp.content[0].text or "").strip()))
        except Exception as e:
            q.put(("error", "resume", str(e)))

    def generate():
        all_ids = [j[0] for j in JOBS] + ["roleplay", "resume"]
        for jid in all_ids:
            yield _sse("status", {"id": jid, "state": "running"})

        threads = []
        for job_id, system_prompt, max_tokens, model in JOBS:
            t = threading.Thread(target=run_job, args=(job_id, system_prompt, max_tokens, model), daemon=True)
            t.start(); threads.append(t)
        for runner in (run_roleplay_job, run_resume_job):
            t = threading.Thread(target=runner, daemon=True)
            t.start(); threads.append(t)

        remaining = len(JOBS) + 2
        while remaining > 0:
            try:
                event_type, job_id, payload = q.get(timeout=600)
            except queue.Empty:
                yield _sse("error", {"id": "all", "message": "Timeout waiting for results."})
                return
            remaining -= 1
            if event_type == "done":
                try:
                    strategy_store.save_piece(client_name, job_id, payload, client_id=client_id)
                except Exception:
                    pass
                yield _sse("result", {"id": job_id, "state": "done", "content": payload})
            else:
                yield _sse("result", {"id": job_id, "state": "error", "message": payload})

        yield _sse("complete", {})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Strategy Package (combined client book) ─────────────────────────────────────

@app.route("/strategy-package")
def strategy_package_page():
    return render_template("strategy_package.html")


@app.route("/api/package/clients")
def package_clients():
    return jsonify(strategy_store.list_clients())


@app.route("/api/package/build.pdf", methods=["POST"])
def package_build_pdf():
    data        = request.get_json()
    client_name = (data.get("client_name") or "").strip()
    # The package page sends back the storage slug from list_clients() so we
    # load the exact folder that was saved (identifier slug or legacy name
    # slug); fall back to the name slug for older clients that send only a name.
    storage_key = (data.get("client_key") or "").strip() or strategy_store.slugify(client_name)
    if not client_name:
        return jsonify({"error": "Client name is required."}), 400

    pieces = strategy_store.load_all(storage_key)
    if not pieces:
        return jsonify({"error": f"No saved content found for {client_name}. Run the Session Builder for this client first."}), 404

    html      = build_strategy_package_html(client_name, pieces)
    pdf_bytes = render_pdf(html)
    slug      = storage_key
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{slug}_strategy_package.pdf")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
