"""
MCP Chat UI — Streamlit test harness for the Universal Bot V2 MCP endpoint.

Usage:
    pip install -r requirements.txt
    streamlit run mcp_chat.py
"""

import json
import time
from typing import Optional, Tuple

import requests
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_MCP_URL = "https://corp-wap-weu-uat-tas-scout-02-h0fmgaf5achmfkb0.a03.azurefd.net/mcp"
DEFAULT_API_KEY = "sk-faq-x9Km2pLqR7vNwT4eJdYc8BhA3uZsGfX1"
DEFAULT_OHR     = "703324710"
REQUEST_TIMEOUT = 120
# ──────────────────────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
# MCP HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def build_headers(api_key: str, session_id: Optional[str] = None) -> dict:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "x-api-key": api_key,
    }
    if session_id:
        h["mcp-session-id"] = session_id
    return h


def parse_sse_response(raw_text: str) -> str:
    collected = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload_str = line[len("data:"):].strip()
        if not payload_str or payload_str == "[DONE]":
            continue
        try:
            data = json.loads(payload_str)
        except json.JSONDecodeError:
            continue
        content = data.get("result", {}).get("content", [])
        for block in content:
            if block.get("type") == "text" and block.get("text"):
                collected.append(block["text"].strip())
        if "error" in data:
            collected.append(f"SERVER ERROR: {data['error'].get('message', str(data['error']))}")
    return "\n".join(collected).strip() if collected else raw_text.strip()


def initialize_mcp_session(mcp_url: str, api_key: str) -> str:
    payload = {
        "jsonrpc": "2.0",
        "id": "init-1",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-streamlit-ui", "version": "1.0"},
        },
    }
    resp = requests.post(mcp_url, json=payload, headers=build_headers(api_key), timeout=30, verify=False)
    resp.raise_for_status()
    session_id = resp.headers.get("mcp-session-id") or resp.headers.get("x-session-id")
    if not session_id:
        raise RuntimeError(f"No session ID returned. Headers: {dict(resp.headers)}")
    return session_id


def call_work_agent(mcp_url, api_key, session_id, ohr, query, new_session=False) -> Tuple[dict, float]:
    payload = {
        "jsonrpc": "2.0",
        "id": f"req-{int(time.time() * 1000)}",
        "method": "tools/call",
        "params": {
            "name": "work_agent",
            "arguments": {"ohr": ohr, "query": query, "new_session": new_session},
        },
    }
    start = time.perf_counter()
    try:
        resp = requests.post(mcp_url, json=payload, headers=build_headers(api_key, session_id),
                             timeout=REQUEST_TIMEOUT, verify=False)
        elapsed = round(time.perf_counter() - start, 2)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        raw = resp.text.strip()

        if "text/event-stream" in content_type or raw.startswith("data:") or raw.startswith("event:"):
            inner_text = parse_sse_response(raw)
        elif raw:
            data = resp.json()
            content_blocks = data.get("result", {}).get("content", [])
            inner_text = "\n".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()
        else:
            inner_text = ""

        try:
            parsed = json.loads(inner_text)
            if not isinstance(parsed, dict):
                parsed = {"text": str(parsed), "agent_name": "", "country_name": ""}
        except (json.JSONDecodeError, TypeError):
            parsed = {"text": inner_text or "[empty response]", "agent_name": "", "country_name": ""}

        return parsed, elapsed

    except requests.exceptions.Timeout:
        return {"text": "ERROR: Request timed out.", "agent_name": "", "country_name": ""}, round(time.perf_counter() - start, 2)
    except requests.exceptions.HTTPError as e:
        return {"text": f"ERROR: HTTP {e.response.status_code} — {e.response.text[:400]}",
                "agent_name": "", "country_name": ""}, round(time.perf_counter() - start, 2)
    except Exception as e:
        return {"text": f"ERROR: {e}", "agent_name": "", "country_name": ""}, round(time.perf_counter() - start, 2)


# ══════════════════════════════════════════════════════════════════════════════
# HTML RENDER HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def wrap_for_render(html_content: str) -> str:
    """
    Wrap HTML fragment in a doc. Adds submit-interception JS that gathers
    form values on submit click and posts them to parent window, which then
    stuffs them into a hidden Streamlit input via clipboard.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
  margin: 0;
  padding: 4px 8px;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: transparent;
  color: #1e293b;
  font-size: 14px;
}}
</style>
</head>
<body>
{html_content}
<script>
(function() {{
  // Intercept any submit button click inside the form
  document.querySelectorAll('form.agent-form').forEach(function(form) {{
    var btn = form.querySelector('button[type="submit"], button.agent-submit');
    if (!btn) return;
    btn.addEventListener('click', function(e) {{
      e.preventDefault();
      var values = [];
      form.querySelectorAll('select, input[type="text"]').forEach(function(el) {{
        if (el.disabled) return;
        var v = (el.value || '').trim();
        if (!v) return;
        // Prefer visible label text for selects (nicer for user to see)
        if (el.tagName === 'SELECT') {{
          var opt = el.options[el.selectedIndex];
          if (opt && opt.text && opt.value) v = opt.text.trim();
        }}
        values.push(v);
      }});
      var combined = values.join(', ');
      // Copy to clipboard + notify parent
      window.parent.postMessage({{type: 'form_submit', value: combined}}, '*');
      // Visual feedback in the iframe
      btn.textContent = 'Submitted ✓';
      btn.disabled = true;
      btn.style.background = '#16a34a';
    }});
  }});
}})();
</script>
</body>
</html>"""


def estimate_height(html_content: str) -> int:
    """Smart height: compact for plain text, generous for form controls."""
    if not html_content:
        return 60

    char_count = len(html_content)
    has_form = any(t in html_content for t in ("<select", "<input", "<fieldset", "<button"))

    if has_form:
        form_bonus = (
            html_content.count("<select") * 60
            + html_content.count("<input") * 50
            + html_content.count("<fieldset") * 70
            + html_content.count("<label") * 30
            + html_content.count("<button") * 40
        )
        text_lines = max(1, char_count // 100)
        return min(max(120 + text_lines * 20 + form_bonus, 200), 2400)
    else:
        text_lines = max(1, char_count // 90)
        return min(max(30 + text_lines * 22, 60), 1200)


def has_html_tags(text: str) -> bool:
    if not text:
        return False
    return any(t in text for t in ("<form", "<select", "<input", "<button", "<div", "<p", "<label", "<fieldset"))


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT APP
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="MCP Chat Tester", page_icon="💬", layout="wide")

# ── Custom CSS for a cleaner chat feel ────────────────────────────────────────
st.markdown("""
<style>
  /* Tighter chat message spacing */
  [data-testid="stChatMessage"] {
    padding: 8px 12px;
    margin-bottom: 8px;
    border-radius: 12px;
  }
  /* User message color */
  [data-testid="stChatMessage"]:has(> div > [data-testid="stChatMessageAvatarUser"]) {
    background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%);
  }
  /* Assistant message color */
  [data-testid="stChatMessage"]:has(> div > [data-testid="stChatMessageAvatarAssistant"]) {
    background: #ffffff;
    border: 1px solid #e2e8f0;
  }
  /* Chat input box */
  [data-testid="stChatInput"] {
    border-radius: 12px;
  }
  /* Sidebar polish */
  [data-testid="stSidebar"] {
    background: #f8fafc;
  }
  /* Reduce top padding */
  .block-container {
    padding-top: 2rem;
    padding-bottom: 6rem;
  }
  /* Latency badge */
  .msg-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 500;
    margin-right: 6px;
  }
  .badge-agent { background: #eef2ff; color: #4f46e5; }
  .badge-country { background: #f0fdf4; color: #16a34a; }
  .badge-time { background: #fef3c7; color: #92400e; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "mcp_session_id" not in st.session_state:
    st.session_state.mcp_session_id = None
if "next_new_session" not in st.session_state:
    st.session_state.next_new_session = False
if "config" not in st.session_state:
    st.session_state.config = {
        "mcp_url": DEFAULT_MCP_URL,
        "api_key": DEFAULT_API_KEY,
        "ohr": DEFAULT_OHR,
    }
if "render_mode" not in st.session_state:
    st.session_state.render_mode = "Rendered"
if "show_meta" not in st.session_state:
    st.session_state.show_meta = True
if "pending_form_value" not in st.session_state:
    st.session_state.pending_form_value = None


# ── Handle form submission bounced from iframe via URL query params ───────────
qp = st.query_params
if "form_submit" in qp:
    form_val = qp["form_submit"]
    if form_val:
        st.session_state.pending_form_value = form_val
    st.query_params.clear()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    st.session_state.config["mcp_url"] = st.text_input("MCP URL", st.session_state.config["mcp_url"])
    st.session_state.config["api_key"] = st.text_input("API Key", st.session_state.config["api_key"], type="password")
    st.session_state.config["ohr"] = st.text_input("OHR", st.session_state.config["ohr"])

    st.divider()

    st.markdown("### 🔗 Session")
    if st.session_state.mcp_session_id:
        st.success(f"**Connected**\n\n`{st.session_state.mcp_session_id[:28]}...`")
    else:
        st.warning("Not connected")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔌 Init", use_container_width=True, type="primary"):
            try:
                with st.spinner("Connecting..."):
                    sid = initialize_mcp_session(
                        st.session_state.config["mcp_url"],
                        st.session_state.config["api_key"],
                    )
                    st.session_state.mcp_session_id = sid
                st.rerun()
            except Exception as e:
                st.error(f"Init failed: {e}")

    with c2:
        if st.button("🔄 Reset", use_container_width=True):
            try:
                with st.spinner("Resetting..."):
                    sid = initialize_mcp_session(
                        st.session_state.config["mcp_url"],
                        st.session_state.config["api_key"],
                    )
                    st.session_state.mcp_session_id = sid
                st.session_state.next_new_session = True
                st.session_state.messages.append({
                    "role": "system",
                    "content": "Session reset. Fresh conversation starting.",
                    "meta": {},
                })
                st.rerun()
            except Exception as e:
                st.error(f"Reset failed: {e}")

    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    st.divider()

    st.markdown("### 👁️ Display")
    st.session_state.render_mode = st.radio(
        "Show agent replies as",
        ["Rendered", "Raw HTML", "Both"],
        index=["Rendered", "Raw HTML", "Both"].index(st.session_state.render_mode),
    )
    st.session_state.show_meta = st.checkbox("Show badges", value=st.session_state.show_meta)

    st.divider()
    st.caption(f"💬 {len(st.session_state.messages)} messages")


# ── Main area ─────────────────────────────────────────────────────────────────
st.markdown("## 💬 MCP Chat Tester")
st.caption("Universal Bot V2 test harness. Fill form fields and click Submit — values will send as your next message.")

if not st.session_state.mcp_session_id:
    st.info("👈 Click **🔌 Init** in the sidebar to connect.")
    st.stop()


# ── Render chat history ───────────────────────────────────────────────────────
for i, msg in enumerate(st.session_state.messages):
    role = msg["role"]

    if role == "system":
        st.info(f"🔄 {msg['content']}")
        continue

    with st.chat_message(role, avatar="🧑" if role == "user" else "🤖"):
        if role == "user":
            st.markdown(msg["content"])
        else:
            meta = msg.get("meta", {})

            if st.session_state.show_meta:
                badges_html = ""
                if meta.get("agent_name"):
                    badges_html += f'<span class="msg-badge badge-agent">🎯 {meta["agent_name"]}</span>'
                if meta.get("country_name"):
                    badges_html += f'<span class="msg-badge badge-country">🌍 {meta["country_name"]}</span>'
                if meta.get("elapsed") is not None:
                    badges_html += f'<span class="msg-badge badge-time">⏱️ {meta["elapsed"]}s</span>'
                if badges_html:
                    st.markdown(badges_html, unsafe_allow_html=True)

            content = msg["content"]

            if st.session_state.render_mode == "Rendered":
                if has_html_tags(content):
                    st.components.v1.html(
                        wrap_for_render(content),
                        height=estimate_height(content),
                        scrolling=False,
                    )
                else:
                    st.markdown(content)
            elif st.session_state.render_mode == "Raw HTML":
                st.code(content, language="html")
            else:  # Both
                left, right = st.columns(2)
                with left:
                    st.markdown("**Rendered:**")
                    if has_html_tags(content):
                        st.components.v1.html(
                            wrap_for_render(content),
                            height=estimate_height(content),
                            scrolling=False,
                        )
                    else:
                        st.markdown(content)
                with right:
                    st.markdown("**Raw:**")
                    st.code(content, language="html")


# ── Bridge: iframe postMessage → Streamlit ───────────────────────────────────
# Injects a listener on the parent page that catches form_submit from iframes
# and reloads the app with the value as a query param.
st.components.v1.html("""
<script>
(function() {
  if (window.__mcp_bridge_installed) return;
  window.__mcp_bridge_installed = true;
  window.parent.addEventListener('message', function(e) {
    if (!e.data || e.data.type !== 'form_submit') return;
    var val = e.data.value || '';
    if (!val) return;
    var url = new URL(window.parent.location.href);
    url.searchParams.set('form_submit', val);
    window.parent.location.href = url.toString();
  });
})();
</script>
""", height=0)


# ── Chat input + form-submit intake ───────────────────────────────────────────
user_query = st.chat_input("Type your message...")

# Prefer pending form value from iframe over typed input if both arrived
if st.session_state.pending_form_value:
    user_query = st.session_state.pending_form_value
    st.session_state.pending_form_value = None

if user_query:
    st.session_state.messages.append({
        "role": "user",
        "content": user_query,
        "meta": {},
    })

    new_session_flag = st.session_state.next_new_session
    st.session_state.next_new_session = False

    # Show user message immediately + spinner while waiting
    with st.chat_message("user", avatar="🧑"):
        st.markdown(user_query)

    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Agent thinking..."):
            parsed, elapsed = call_work_agent(
                mcp_url=st.session_state.config["mcp_url"],
                api_key=st.session_state.config["api_key"],
                session_id=st.session_state.mcp_session_id,
                ohr=st.session_state.config["ohr"],
                query=user_query,
                new_session=new_session_flag,
            )

    st.session_state.messages.append({
        "role": "assistant",
        "content": parsed.get("text", ""),
        "meta": {
            "agent_name": parsed.get("agent_name", ""),
            "country_name": parsed.get("country_name", ""),
            "elapsed": elapsed,
        },
    })

    st.rerun()
