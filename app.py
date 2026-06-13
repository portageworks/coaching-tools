import os
import re
import json
import io
from flask import Flask, render_template, request, jsonify, Response, stream_with_context, send_file
import anthropic

from prompts.session_generator import SYNTHESIS_SYSTEM, COACH_GUIDE_SYSTEM
from docx_builder import markdown_to_docx

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
        # ── Call 1: Synthesis ──────────────────────────────────────────────
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
                    # Yield a heartbeat so the connection stays alive.
                    # We don't show synthesis text in the UI, just keep alive.
                    yield _sse("ping", {})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            return

        synthesis = "".join(synthesis_chunks)

        # ── Call 2: Coach Guide ────────────────────────────────────────────
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

        guide = "".join(guide_chunks)
        yield _sse("done", {"guide": guide})

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
