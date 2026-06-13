/**
 * Send a message to the backend and return the full response text.
 * @param {Object} opts
 * @param {Array}  opts.messages  - Anthropic messages array
 * @param {string} [opts.system]  - System prompt
 * @param {string} [opts.model]   - Model ID (defaults to server default)
 * @param {number} [opts.max_tokens]
 * @returns {Promise<string>}
 */
async function claudeChat({ messages, system = "", model, max_tokens }) {
  const body = { messages, system };
  if (model) body.model = model;
  if (max_tokens) body.max_tokens = max_tokens;

  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API error ${res.status}: ${err}`);
  }

  const data = await res.json();
  return data.content;
}

/**
 * Stream a response from the backend, calling onChunk for each text delta.
 * @param {Object}   opts
 * @param {Array}    opts.messages
 * @param {string}   [opts.system]
 * @param {string}   [opts.model]
 * @param {number}   [opts.max_tokens]
 * @param {Function} opts.onChunk  - called with each text chunk
 * @returns {Promise<void>}
 */
async function claudeStream({ messages, system = "", model, max_tokens, onChunk }) {
  const body = { messages, system };
  if (model) body.model = model;
  if (max_tokens) body.max_tokens = max_tokens;

  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) throw new Error(`API error ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const text = line.slice(6);
      if (text === "[DONE]") return;
      onChunk(text);
    }
  }
}
