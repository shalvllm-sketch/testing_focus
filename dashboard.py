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
from streamlit_js_eval import streamlit_js_eval

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_MCP_URL = "https://corp-wap-weu-uat-tas-scout-02-h0fmgaf5achmfkb0.a03.azurefd.net/mcp"
DEFAULT_API_KEY = "sk-faq-x9Km2pLqR7vNwT4eJdYc8BhA3uZsGfX1"
DEFAULT_OHR     = "703324710"
REQUEST_TIMEOUT = 120
# ──────────────────────────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
# MCP HELPERS (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def build_headers(api_key, session_id=None):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "x-api-key": api_key}
    if session_id:
        h["mcp-session-id"] = session_id
    return h


def parse_sse_response(raw_text):
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


def initialize_mcp_session(mcp_url, api_key):
    payload = {
        "jsonrpc": "2.0", "id": "init-1", "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "mcp-streamlit-ui", "version": "1.0"}},
    }
    resp = requests.post(mcp_url, json=payload, headers=build_headers(api_key), timeout=30, verify=False)
    resp.raise_for_status()
    session_id = resp.headers.get("mcp-session-id") or resp.headers.get("x-session-id")
    if not session_id:
        raise RuntimeError(f"No session ID returned. Headers: {dict(resp.headers)}")
    return session_id


def call_work_agent(mcp_url, api_key, session_id, ohr, query, new_session=False):
    payload = {
        "jsonrpc": "2.0", "id": f"req-{int(time.time() * 1000)}",
        "method": "tools/call",
        "params": {"name": "work_agent",
                   "arguments": {"ohr": ohr, "query": query, "new_session": new_session}},
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
# HTML RENDER
# ══════════════════════════════════════════════════════════════════════════════

def wrap_for_render(html_content, msg_id):
    """
    Wrap HTML fragment. Submit button gathers values and stores them
    in localStorage under a unique key that Python polls.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: transparent;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    color: #1e293b;
    font-size: 14px;
  }}
  body {{ padding: 2px 4px; }}
</style>
</head>
<body>
{html_content}
<script>
(function() {{
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
        if (el.tagName === 'SELECT') {{
          var opt = el.options[el.selectedIndex];
          if (opt && opt.text) v = opt.text.trim();
        }}
        values.push(v);
      }});
      var combined = values.join(', ');
      if (!combined) return;
      // Write to top-window localStorage for Python to pick up
      try {{
        window.top.localStorage.setItem('mcp_form_submit', combined);
        window.top.localStorage.setItem('mcp_form_ts', String(Date.now()));
      }} catch(err) {{
        window.localStorage.setItem('mcp_form_submit', combined);
        window.localStorage.setItem('mcp_form_ts', String(Date.now()));
      }}
      btn.textContent = '✓ Sending...';
      btn.disabled = true;
      btn.style.background = '#16a34a';
      // Force parent Streamlit page to reload so Python picks up the value
      setTimeout(function() {{
        try {{ window.top.location.reload(); }}
        catch(e) {{ window.parent.location.reload(); }}
      }}, 300);
    }});
  }});
}})();
</script>
</body>
</html>"""


def estimate_height(html_content):
    if not html_content:
        return 50
    has_form = any(t in html_content for t in ("<select", "<input", "<button", "<fieldset"))
    char_count = len(html_content)

    if has_form:
        form_bonus = (
            html_content.count("<select") * 55 +
            html_content.count("<input") * 45 +
            html_content.count("<fieldset") * 60 +
            html_content.count("<label") * 25 +
            html_content.count("<button") * 40
        )
        text_lines = max(1, char_count // 110)
        return min(max(100 + text_lines * 18 + form_bonus, 180), 2200)
    else:
        text_lines = max(1, char_count // 90)
        return min(max(20 + text_lines * 20, 50), 1000)


def has_html_tags(text):
    if not text:
        return False
    return any(t in text for t in ("<form", "<select", "<input", "<button", "<div", "<label", "<fieldset"))


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT APP
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="MCP Chat Tester", page_icon="💬", layout="wide")

st.markdown("""
<style>
  /* Tighter chat spacing */
  [data-testid="stChatMessage"] {
    padding: 6px 10px !important;
    margin-bottom: 4px !important;
    border-radius: 12px;
  }
  /* User bubble */
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%) !important;
  }
  /* Assistant bubble */
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
  }
  /* Kill excess space around iframes */
  [data-testid="stChatMessage"] iframe {
    display: block;
    margin: 0 !important;
    padding: 0 !important;
  }
  [data-testid="stChatMessage"] [data-testid="stCustomComponentV1"] {
    margin: 0 !important;
  }
  /* Sidebar polish */
  [data-testid="stSidebar"] { background: #f8fafc; }
  .block-container { padding-top: 1.5rem; padding-bottom: 6rem; }
  /* Badges */
  .msg-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 500;
    margin-right: 4px;
  }
  .badge-agent { background: #eef2ff; color: #4f46e5; }
  .badge-country { background: #f0fdf4; color: #16a34a; }
  .badge-time { background: #fef3c7; color: #92400e; }
  .badge-newsess { background: #fee2e2; color: #b91c1c; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "mcp_session_id" not in st.session_state:
    st.session_state.mcp_session_id = None
if "always_new_session" not in st.session_state:
    st.session_state.always_new_session = False
if "next_new_session" not in st.session_state:
    st.session_state.next_new_session = False
if "config" not in st.session_state:
    st.session_state.config = {"mcp_url": DEFAULT_MCP_URL, "api_key": DEFAULT_API_KEY, "ohr": DEFAULT_OHR}
if "render_mode" not in st.session_state:
    st.session_state.render_mode = "Rendered"
if "show_meta" not in st.session_state:
    st.session_state.show_meta = True
if "last_form_ts" not in st.session_state:
    st.session_state.last_form_ts = "0"


# ── Poll localStorage for form submission ─────────────────────────────────────
form_submit_val = streamlit_js_eval(
    js_expressions="localStorage.getItem('mcp_form_submit')",
    key="poll_submit",
    want_output=True,
)
form_submit_ts = streamlit_js_eval(
    js_expressions="localStorage.getItem('mcp_form_ts')",
    key="poll_ts",
    want_output=True,
)

pending_from_form = None
if form_submit_val and form_submit_ts and form_submit_ts != st.session_state.last_form_ts:
    pending_from_form = form_submit_val
    st.session_state.last_form_ts = form_submit_ts
    # Clear localStorage so this doesn't re-trigger
    streamlit_js_eval(
        js_expressions="localStorage.removeItem('mcp_form_submit'); localStorage.removeItem('mcp_form_ts');",
        key="clear_ls",
    )


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

    st.markdown("### 🔀 New Session Flag")
    st.session_state.always_new_session = st.checkbox(
        "Send `new_session=True` on every message",
        value=st.session_state.always_new_session,
        help="When ON, every request forces a fresh MCP conversation. Like re-authenticating each turn.",
    )
    if st.session_state.next_new_session:
        st.info("🔄 Next message will use `new_session=True` (one-time)")

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
st.caption("Universal Bot V2 test harness. Fill form fields and click Submit — values auto-send as your next message.")

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
                bh = ""
                if meta.get("agent_name"):
                    bh += f'<span class="msg-badge badge-agent">🎯 {meta["agent_name"]}</span>'
                if meta.get("country_name"):
                    bh += f'<span class="msg-badge badge-country">🌍 {meta["country_name"]}</span>'
                if meta.get("elapsed") is not None:
                    bh += f'<span class="msg-badge badge-time">⏱️ {meta["elapsed"]}s</span>'
                if meta.get("new_session"):
                    bh += f'<span class="msg-badge badge-newsess">🔄 new_session</span>'
                if bh:
                    st.markdown(bh, unsafe_allow_html=True)

            content = msg["content"]

            if st.session_state.render_mode == "Rendered":
                if has_html_tags(content):
                    st.components.v1.html(
                        wrap_for_render(content, f"msg_{i}"),
                        height=estimate_height(content),
                        scrolling=False,
                    )
                else:
                    st.markdown(content)
            elif st.session_state.render_mode == "Raw HTML":
                st.code(content, language="html")
            else:
                left, right = st.columns(2)
                with left:
                    st.markdown("**Rendered:**")
                    if has_html_tags(content):
                        st.components.v1.html(
                            wrap_for_render(content, f"msg_{i}"),
                            height=estimate_height(content),
                            scrolling=False,
                        )
                    else:
                        st.markdown(content)
                with right:
                    st.markdown("**Raw:**")
                    st.code(content, language="html")


# ── Chat input + form intake ──────────────────────────────────────────────────
user_query = st.chat_input("Type your message...")

# Form submission takes precedence
if pending_from_form:
    user_query = pending_from_form

if user_query:
    # Determine new_session flag
    use_new_session = (
        st.session_state.always_new_session or st.session_state.next_new_session
    )
    st.session_state.next_new_session = False  # one-time flag consumed

    st.session_state.messages.append({
        "role": "user",
        "content": user_query,
        "meta": {"new_session": use_new_session},
    })

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
                new_session=use_new_session,
            )

    st.session_state.messages.append({
        "role": "assistant",
        "content": parsed.get("text", ""),
        "meta": {
            "agent_name": parsed.get("agent_name", ""),
            "country_name": parsed.get("country_name", ""),
            "elapsed": elapsed,
            "new_session": use_new_session,
        },
    })

    st.rerun()
