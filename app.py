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
    positioning_prompt, resume_rewrite_prompt,
)
from docx_builder import markdown_to_docx
from resume_docx_builder import resume_to_docx

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
        ("resume",      resume_rewrite_prompt(client_name),    8000),
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

    def generate():
        # Signal all jobs as running
        for job_id, _, _ in JOBS:
            yield _sse("status", {"id": job_id, "state": "running"})

        # Launch all jobs in parallel threads
        threads = []
        for job_id, system_prompt, max_tokens in JOBS:
            t = threading.Thread(target=run_job, args=(job_id, system_prompt, max_tokens), daemon=True)
            t.start()
            threads.append(t)

        # Stream results as each job completes
        remaining = len(JOBS)
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
