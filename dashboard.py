# """
# MCP Chat UI — Streamlit test harness for the Universal Bot V2 MCP endpoint.

# Usage:
#     pip install -r requirements.txt
#     streamlit run mcp_chat.py
# """

# import json
# import re
# import time
# from html.parser import HTMLParser
# from typing import Optional, Tuple

# import requests
# import streamlit as st
# import urllib3

# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# # ── Configuration ─────────────────────────────────────────────────────────────
# DEFAULT_MCP_URL = "https://aiworkspacetktcreation-esanfcahd6gvenf4.eastus2-01.azurewebsites.net/mcp"
# DEFAULT_API_KEY = "sk-faq-x9Km2pLqR7vNwT4eJdYc8BhA3uZsGfX1"
# DEFAULT_OHR     = "703324710"
# REQUEST_TIMEOUT = 120
# # ──────────────────────────────────────────────────────────────────────────────


# # ══════════════════════════════════════════════════════════════════════════════
# # MCP HELPERS
# # ══════════════════════════════════════════════════════════════════════════════

# def build_headers(api_key, session_id=None):
#     h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "x-api-key": api_key}
#     if session_id:
#         h["mcp-session-id"] = session_id
#     return h


# def parse_sse_response(raw_text):
#     collected = []
#     for line in raw_text.splitlines():
#         line = line.strip()
#         if not line.startswith("data:"):
#             continue
#         payload_str = line[len("data:"):].strip()
#         if not payload_str or payload_str == "[DONE]":
#             continue
#         try:
#             data = json.loads(payload_str)
#         except json.JSONDecodeError:
#             continue
#         content = data.get("result", {}).get("content", [])
#         for block in content:
#             if block.get("type") == "text" and block.get("text"):
#                 collected.append(block["text"].strip())
#         if "error" in data:
#             collected.append(f"SERVER ERROR: {data['error'].get('message', str(data['error']))}")
#     return "\n".join(collected).strip() if collected else raw_text.strip()


# def initialize_mcp_session(mcp_url, api_key):
#     payload = {
#         "jsonrpc": "2.0", "id": "init-1", "method": "initialize",
#         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
#                    "clientInfo": {"name": "mcp-streamlit-ui", "version": "1.0"}},
#     }
#     resp = requests.post(mcp_url, json=payload, headers=build_headers(api_key), timeout=30, verify=False)
#     resp.raise_for_status()
#     session_id = resp.headers.get("mcp-session-id") or resp.headers.get("x-session-id")
#     if not session_id:
#         raise RuntimeError(f"No session ID returned. Headers: {dict(resp.headers)}")
#     return session_id


# def call_work_agent(mcp_url, api_key, session_id, ohr, query, new_session=False):
#     payload = {
#         "jsonrpc": "2.0", "id": f"req-{int(time.time() * 1000)}",
#         "method": "tools/call",
#         "params": {"name": "work_agent",
#                    "arguments": {"ohr": ohr, "query": query, "new_session": new_session}},
#     }
#     start = time.perf_counter()
#     try:
#         resp = requests.post(mcp_url, json=payload, headers=build_headers(api_key, session_id),
#                              timeout=REQUEST_TIMEOUT, verify=False)
#         elapsed = round(time.perf_counter() - start, 2)
#         resp.raise_for_status()

#         content_type = resp.headers.get("Content-Type", "")
#         raw = resp.text.strip()

#         if "text/event-stream" in content_type or raw.startswith("data:") or raw.startswith("event:"):
#             inner_text = parse_sse_response(raw)
#         elif raw:
#             data = resp.json()
#             content_blocks = data.get("result", {}).get("content", [])
#             inner_text = "\n".join(b.get("text", "") for b in content_blocks if b.get("type") == "text").strip()
#         else:
#             inner_text = ""

#         try:
#             parsed = json.loads(inner_text)
#             if not isinstance(parsed, dict):
#                 parsed = {"text": str(parsed), "agent_name": "", "country_name": ""}
#         except (json.JSONDecodeError, TypeError):
#             parsed = {"text": inner_text or "[empty response]", "agent_name": "", "country_name": ""}

#         return parsed, elapsed
#     except requests.exceptions.Timeout:
#         return {"text": "ERROR: Request timed out.", "agent_name": "", "country_name": ""}, round(time.perf_counter() - start, 2)
#     except requests.exceptions.HTTPError as e:
#         return {"text": f"ERROR: HTTP {e.response.status_code} — {e.response.text[:400]}",
#                 "agent_name": "", "country_name": ""}, round(time.perf_counter() - start, 2)
#     except Exception as e:
#         return {"text": f"ERROR: {e}", "agent_name": "", "country_name": ""}, round(time.perf_counter() - start, 2)


# # ══════════════════════════════════════════════════════════════════════════════
# # HTML PARSER — extract form fields into a Python structure
# # ══════════════════════════════════════════════════════════════════════════════

# class FormFieldParser(HTMLParser):
#     """
#     Extract form fields (labels, selects/options, text inputs) from MCP HTML.
#     Returns a list of dicts:
#       {"kind": "select", "label": "...", "name": "...", "options": [(label,value),...], "default": "..."}
#       {"kind": "text",   "label": "...", "name": "...", "default": "..."}
#       {"kind": "info",   "text": "..."}  ← <p class="agent-text"> content
#     """
#     def __init__(self):
#         super().__init__()
#         self.fields = []
#         self.current_label = ""
#         self.in_label = False
#         self.in_strong = False
#         self.strong_text = ""
#         self.in_select = False
#         self.current_select = None  # dict being built
#         self.in_option = False
#         self.option_value = ""
#         self.option_selected = False
#         self.option_disabled = False
#         self.option_text = ""
#         self.in_p_text = False
#         self.p_text = ""
#         self.in_input = False

#     def handle_starttag(self, tag, attrs):
#         attrs_d = dict(attrs)
#         if tag == "label":
#             self.in_label = True
#             self.strong_text = ""
#         elif tag == "strong" and self.in_label:
#             self.in_strong = True
#             self.strong_text = ""
#         elif tag == "select":
#             self.in_select = True
#             self.current_select = {
#                 "kind": "select",
#                 "label": self.strong_text.strip() or self.current_label.strip() or "Select",
#                 "name": attrs_d.get("name", f"field_{len(self.fields)}"),
#                 "options": [],
#                 "default": "",
#                 "disabled": "disabled" in attrs_d,
#             }
#         elif tag == "option" and self.in_select:
#             self.in_option = True
#             self.option_value = attrs_d.get("value", "")
#             self.option_selected = "selected" in attrs_d
#             self.option_disabled = "disabled" in attrs_d
#             self.option_text = ""
#         elif tag == "input":
#             input_type = attrs_d.get("type", "text")
#             if input_type == "text":
#                 self.fields.append({
#                     "kind": "text",
#                     "label": self.strong_text.strip() or self.current_label.strip() or "Field",
#                     "name": attrs_d.get("name", f"field_{len(self.fields)}"),
#                     "default": attrs_d.get("value", ""),
#                     "placeholder": attrs_d.get("placeholder", ""),
#                 })
#         elif tag == "p":
#             if "agent-text" in attrs_d.get("class", ""):
#                 self.in_p_text = True
#                 self.p_text = ""

#     def handle_endtag(self, tag):
#         if tag == "strong":
#             self.in_strong = False
#         elif tag == "label":
#             self.in_label = False
#             self.current_label = ""
#         elif tag == "select":
#             if self.current_select:
#                 if not self.current_select["disabled"]:
#                     self.fields.append(self.current_select)
#             self.current_select = None
#             self.in_select = False
#         elif tag == "option" and self.in_option:
#             if self.current_select and not self.option_disabled and self.option_value:
#                 lbl = self.option_text.strip() or self.option_value
#                 self.current_select["options"].append((lbl, self.option_value))
#                 if self.option_selected:
#                     self.current_select["default"] = self.option_value
#             self.in_option = False
#         elif tag == "p" and self.in_p_text:
#             txt = self.p_text.strip()
#             if txt:
#                 self.fields.append({"kind": "info", "text": txt})
#             self.in_p_text = False

#     def handle_data(self, data):
#         if self.in_strong:
#             self.strong_text += data
#         elif self.in_option:
#             self.option_text += data
#         elif self.in_p_text:
#             self.p_text += data
#         elif self.in_label and not self.in_select:
#             self.current_label += data


# def parse_agent_form(html):
#     """Return a list of parsed field dicts."""
#     if not html:
#         return []
#     p = FormFieldParser()
#     try:
#         p.feed(html)
#     except Exception:
#         return []
#     return p.fields


# def has_interactive_fields(fields):
#     return any(f["kind"] in ("select", "text") for f in fields)


# def clean_html_for_preview(html):
#     """Strip <style>, <script> from HTML for cleaner preview."""
#     if not html:
#         return ""
#     html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
#     html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
#     return html


# # ══════════════════════════════════════════════════════════════════════════════
# # STREAMLIT APP
# # ══════════════════════════════════════════════════════════════════════════════

# st.set_page_config(page_title="MCP Chat Tester", page_icon="💬", layout="wide")

# st.markdown("""
# <style>
#   [data-testid="stChatMessage"] {
#     padding: 8px 12px !important;
#     margin-bottom: 6px !important;
#     border-radius: 12px;
#   }
#   [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
#     background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%) !important;
#   }
#   [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
#     background: #ffffff !important;
#     border: 1px solid #e2e8f0 !important;
#   }
#   [data-testid="stSidebar"] { background: #f8fafc; }
#   .block-container { padding-top: 1.5rem; padding-bottom: 6rem; }
#   .msg-badge {
#     display: inline-block;
#     padding: 2px 8px;
#     border-radius: 10px;
#     font-size: 11px;
#     font-weight: 500;
#     margin-right: 4px;
#   }
#   .badge-agent { background: #eef2ff; color: #4f46e5; }
#   .badge-country { background: #f0fdf4; color: #16a34a; }
#   .badge-time { background: #fef3c7; color: #92400e; }
#   .badge-newsess { background: #fee2e2; color: #b91c1c; }
# </style>
# """, unsafe_allow_html=True)


# # ── Session state ─────────────────────────────────────────────────────────────
# if "messages" not in st.session_state:
#     st.session_state.messages = []
# if "mcp_session_id" not in st.session_state:
#     st.session_state.mcp_session_id = None
# if "always_new_session" not in st.session_state:
#     st.session_state.always_new_session = False
# if "next_new_session" not in st.session_state:
#     st.session_state.next_new_session = False
# if "config" not in st.session_state:
#     st.session_state.config = {"mcp_url": DEFAULT_MCP_URL, "api_key": DEFAULT_API_KEY, "ohr": DEFAULT_OHR}
# if "render_mode" not in st.session_state:
#     st.session_state.render_mode = "Interactive Form"
# if "show_meta" not in st.session_state:
#     st.session_state.show_meta = True


# # ── Sidebar ───────────────────────────────────────────────────────────────────
# with st.sidebar:
#     st.markdown("### ⚙️ Configuration")
#     st.session_state.config["mcp_url"] = st.text_input("MCP URL", st.session_state.config["mcp_url"])
#     st.session_state.config["api_key"] = st.text_input("API Key", st.session_state.config["api_key"], type="password")
#     st.session_state.config["ohr"] = st.text_input("OHR", st.session_state.config["ohr"])

#     st.divider()

#     st.markdown("### 🔗 Session")
#     if st.session_state.mcp_session_id:
#         st.success(f"**Connected**\n\n`{st.session_state.mcp_session_id[:28]}...`")
#     else:
#         st.warning("Not connected")

#     c1, c2 = st.columns(2)
#     with c1:
#         if st.button("🔌 Init", use_container_width=True, type="primary"):
#             try:
#                 with st.spinner("Connecting..."):
#                     sid = initialize_mcp_session(
#                         st.session_state.config["mcp_url"],
#                         st.session_state.config["api_key"],
#                     )
#                     st.session_state.mcp_session_id = sid
#                 st.rerun()
#             except Exception as e:
#                 st.error(f"Init failed: {e}")
#     with c2:
#         if st.button("🔄 Reset", use_container_width=True):
#             try:
#                 with st.spinner("Resetting..."):
#                     sid = initialize_mcp_session(
#                         st.session_state.config["mcp_url"],
#                         st.session_state.config["api_key"],
#                     )
#                     st.session_state.mcp_session_id = sid
#                 st.session_state.next_new_session = True
#                 st.session_state.messages.append({
#                     "role": "system",
#                     "content": "Session reset. Fresh conversation starting.",
#                 })
#                 st.rerun()
#             except Exception as e:
#                 st.error(f"Reset failed: {e}")

#     if st.button("🗑️ Clear Chat", use_container_width=True):
#         st.session_state.messages = []
#         st.rerun()

#     st.divider()

#     st.markdown("### 🔀 New Session Flag")
#     st.session_state.always_new_session = st.checkbox(
#         "Send `new_session=True` on every message",
#         value=st.session_state.always_new_session,
#     )
#     if st.session_state.next_new_session:
#         st.info("🔄 Next msg will use new_session=True")

#     st.divider()

#     st.markdown("### 👁️ Display Mode")
#     st.session_state.render_mode = st.radio(
#         "Show agent replies as",
#         ["Interactive Form", "HTML Preview", "Raw HTML"],
#         index=["Interactive Form", "HTML Preview", "Raw HTML"].index(st.session_state.render_mode),
#         help="Interactive Form = native Streamlit dropdowns (recommended). HTML Preview = read-only styled preview. Raw HTML = source.",
#     )
#     st.session_state.show_meta = st.checkbox("Show badges", value=st.session_state.show_meta)

#     st.divider()
#     st.caption(f"💬 {len(st.session_state.messages)} messages")


# # ── Main ──────────────────────────────────────────────────────────────────────
# st.markdown("## 💬 MCP Chat Tester")
# st.caption("Universal Bot V2 test harness. Interactive Form mode gives you real dropdowns you can submit.")

# if not st.session_state.mcp_session_id:
#     st.info("👈 Click **🔌 Init** in the sidebar to connect.")
#     st.stop()


# def send_message(text, use_new_session):
#     """Add user msg, call MCP, add assistant msg."""
#     st.session_state.messages.append({
#         "role": "user",
#         "content": text,
#         "meta": {"new_session": use_new_session},
#     })
#     with st.chat_message("user", avatar="🧑"):
#         st.markdown(text)
#     with st.chat_message("assistant", avatar="🤖"):
#         with st.spinner("Agent thinking..."):
#             parsed, elapsed = call_work_agent(
#                 mcp_url=st.session_state.config["mcp_url"],
#                 api_key=st.session_state.config["api_key"],
#                 session_id=st.session_state.mcp_session_id,
#                 ohr=st.session_state.config["ohr"],
#                 query=text,
#                 new_session=use_new_session,
#             )
#     st.session_state.messages.append({
#         "role": "assistant",
#         "content": parsed.get("text", ""),
#         "meta": {
#             "agent_name": parsed.get("agent_name", ""),
#             "country_name": parsed.get("country_name", ""),
#             "elapsed": elapsed,
#             "new_session": use_new_session,
#         },
#     })


# # ── Render chat history ───────────────────────────────────────────────────────
# for i, msg in enumerate(st.session_state.messages):
#     role = msg["role"]

#     if role == "system":
#         st.info(f"🔄 {msg['content']}")
#         continue

#     with st.chat_message(role, avatar="🧑" if role == "user" else "🤖"):
#         if role == "user":
#             st.markdown(msg["content"])
#             continue

#         # assistant message
#         meta = msg.get("meta", {})
#         if st.session_state.show_meta:
#             bh = ""
#             if meta.get("agent_name"):
#                 bh += f'<span class="msg-badge badge-agent">🎯 {meta["agent_name"]}</span>'
#             if meta.get("country_name"):
#                 bh += f'<span class="msg-badge badge-country">🌍 {meta["country_name"]}</span>'
#             if meta.get("elapsed") is not None:
#                 bh += f'<span class="msg-badge badge-time">⏱️ {meta["elapsed"]}s</span>'
#             if meta.get("new_session"):
#                 bh += f'<span class="msg-badge badge-newsess">🔄 new_session</span>'
#             if bh:
#                 st.markdown(bh, unsafe_allow_html=True)

#         content = msg["content"]
#         mode = st.session_state.render_mode

#         if mode == "Raw HTML":
#             st.code(content, language="html")
#             continue

#         if mode == "HTML Preview":
#             # Static preview only, no interaction
#             if "<" in content and ">" in content:
#                 # Render as-is via markdown (unsafe html)
#                 st.markdown(clean_html_for_preview(content), unsafe_allow_html=True)
#             else:
#                 st.markdown(content)
#             continue

#         # mode == "Interactive Form"
#         fields = parse_agent_form(content)

#         if not fields:
#             # No parseable form, just show text/HTML as-is
#             if "<" in content and ">" in content:
#                 st.markdown(clean_html_for_preview(content), unsafe_allow_html=True)
#             else:
#                 st.markdown(content)
#             continue

#         # Only the LATEST assistant message gets interactive form
#         is_latest_assistant = (i == len(st.session_state.messages) - 1)

#         # Info text (agent prose)
#         for f in fields:
#             if f["kind"] == "info":
#                 st.markdown(f["text"])

#         interactive_fields = [f for f in fields if f["kind"] in ("select", "text")]

#         if not interactive_fields:
#             continue

#         if not is_latest_assistant:
#             # Show static preview for historical assistant messages
#             st.caption("*(Form from earlier turn — interact with the latest message.)*")
#             for f in interactive_fields:
#                 if f["kind"] == "select":
#                     st.markdown(f"**{f['label']}** — options: {', '.join(o[0] for o in f['options'])}")
#                 elif f["kind"] == "text":
#                     st.markdown(f"**{f['label']}** — [text input]")
#             continue

#         # Build native Streamlit widgets
#         with st.form(key=f"agent_form_{i}", clear_on_submit=False):
#             widget_vals = {}
#             for j, f in enumerate(interactive_fields):
#                 widget_key = f"agent_form_{i}_field_{j}"
#                 if f["kind"] == "select":
#                     opt_labels = [o[0] for o in f["options"]]
#                     if not opt_labels:
#                         continue
#                     default_idx = 0
#                     if f.get("default"):
#                         for k, (lbl, val) in enumerate(f["options"]):
#                             if val == f["default"]:
#                                 default_idx = k
#                                 break
#                     widget_vals[f["label"]] = st.selectbox(
#                         f["label"], opt_labels, index=default_idx, key=widget_key,
#                     )
#                 elif f["kind"] == "text":
#                     widget_vals[f["label"]] = st.text_input(
#                         f["label"],
#                         value=f.get("default", ""),
#                         placeholder=f.get("placeholder", ""),
#                         key=widget_key,
#                     )

#             submitted = st.form_submit_button("📤 Submit", type="primary", use_container_width=False)
#             if submitted:
#                 # Combine values into a comma-separated string (matches how real UI would post)
#                 combined = ", ".join(str(v).strip() for v in widget_vals.values() if str(v).strip())
#                 if combined:
#                     use_new = st.session_state.always_new_session or st.session_state.next_new_session
#                     st.session_state.next_new_session = False
#                     send_message(combined, use_new)
#                     st.rerun()


# # ── Chat input ────────────────────────────────────────────────────────────────
# user_query = st.chat_input("Type your message...")
# if user_query:
#     use_new = st.session_state.always_new_session or st.session_state.next_new_session
#     st.session_state.next_new_session = False
#     send_message(user_query, use_new)
#     st.rerun()






"""
MCP Chat UI — Streamlit test harness for the Universal Bot V2 MCP endpoint.
Usage:
    pip install -r requirements.txt
    streamlit run dashboard.py
"""
import json
import re
import time
from html.parser import HTMLParser
from typing import Optional, Tuple
import requests
import streamlit as st
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_MCP_URL = "https://aiworkspacetktcreation-esanfcahd6gvenf4.eastus2-01.azurewebsites.net/mcp"
DEFAULT_API_KEY = "sk-faq-x9Km2pLqR7vNwT4eJdYc8BhA3uZsGfX1"
DEFAULT_OHR     = "703324710"
REQUEST_TIMEOUT = 120
# ──────────────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
# MCP HELPERS
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
# HTML PARSER — extract form fields into a Python structure
# ══════════════════════════════════════════════════════════════════════════════
class FormFieldParser(HTMLParser):
    """
    Extract form fields (labels, selects/options, text inputs) from MCP HTML.
    Returns a list of dicts:
      {"kind": "select", "label": "...", "name": "...", "options": [(label,value),...], "default": "..."}
      {"kind": "text",   "label": "...", "name": "...", "default": "..."}
      {"kind": "info",   "text": "..."}  ← <p class="agent-text"> content
    """
    def __init__(self):
        super().__init__()
        self.fields = []
        self.current_label = ""
        self.in_label = False
        self.in_strong = False
        self.strong_text = ""
        self.in_select = False
        self.current_select = None  # dict being built
        self.in_option = False
        self.option_value = ""
        self.option_selected = False
        self.option_disabled = False
        self.option_text = ""
        self.in_p_text = False
        self.p_text = ""
        self.in_input = False
    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "label":
            self.in_label = True
            self.strong_text = ""
        elif tag == "strong" and self.in_label:
            self.in_strong = True
            self.strong_text = ""
        elif tag == "select":
            self.in_select = True
            self.current_select = {
                "kind": "select",
                "label": self.strong_text.strip() or self.current_label.strip() or "Select",
                "name": attrs_d.get("name", f"field_{len(self.fields)}"),
                "options": [],
                "default": "",
                "disabled": "disabled" in attrs_d,
            }
        elif tag == "option" and self.in_select:
            self.in_option = True
            self.option_value = attrs_d.get("value", "")
            self.option_selected = "selected" in attrs_d
            self.option_disabled = "disabled" in attrs_d
            self.option_text = ""
        elif tag == "input":
            input_type = attrs_d.get("type", "text")
            if input_type == "text":
                self.fields.append({
                    "kind": "text",
                    "label": self.strong_text.strip() or self.current_label.strip() or "Field",
                    "name": attrs_d.get("name", f"field_{len(self.fields)}"),
                    "default": attrs_d.get("value", ""),
                    "placeholder": attrs_d.get("placeholder", ""),
                })
        elif tag == "p":
            if "agent-text" in attrs_d.get("class", ""):
                self.in_p_text = True
                self.p_text = ""
    def handle_endtag(self, tag):
        if tag == "strong":
            self.in_strong = False
        elif tag == "label":
            self.in_label = False
            self.current_label = ""
        elif tag == "select":
            if self.current_select:
                if not self.current_select["disabled"]:
                    self.fields.append(self.current_select)
            self.current_select = None
            self.in_select = False
        elif tag == "option" and self.in_option:
            if self.current_select and not self.option_disabled and self.option_value:
                lbl = self.option_text.strip() or self.option_value
                self.current_select["options"].append((lbl, self.option_value))
                if self.option_selected:
                    self.current_select["default"] = self.option_value
            self.in_option = False
        elif tag == "p" and self.in_p_text:
            txt = self.p_text.strip()
            if txt:
                self.fields.append({"kind": "info", "text": txt})
            self.in_p_text = False
    def handle_data(self, data):
        if self.in_strong:
            self.strong_text += data
        elif self.in_option:
            self.option_text += data
        elif self.in_p_text:
            self.p_text += data
        elif self.in_label and not self.in_select:
            self.current_label += data
def parse_agent_form(html):
    """Return a list of parsed field dicts."""
    if not html:
        return []
    p = FormFieldParser()
    try:
        p.feed(html)
    except Exception:
        return []
    return p.fields
def has_interactive_fields(fields):
    return any(f["kind"] in ("select", "text") for f in fields)
def clean_html_for_preview(html):
    """Strip <style>, <script> from HTML for cleaner preview."""
    if not html:
        return ""
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    return html
# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT APP
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="MCP Chat Tester", page_icon="📡", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {
  --ink-950: #0B0E16;
  --ink-900: #0F1420;
  --ink-850: #131A2B;
  --ink-800: #161C2C;
  --ink-700: #1E2740;
  --hairline: #232B42;
  --text-primary: #E8EAF2;
  --text-secondary: #9AA3BE;
  --text-tertiary: #6B7390;
  --copper: #F2A65A;
  --copper-dim: #C97D3B;
  --teal: #56D8C4;
  --green: #7BD88F;
  --coral: #F1685E;
  --font-display: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }
}

html, body, [class*="css"] { font-family: var(--font-display); }

/* ── App shell ───────────────────────────────────────────── */
.stApp {
  background:
    radial-gradient(ellipse 900px 500px at 6% -8%, rgba(242,166,90,0.10), transparent 60%),
    radial-gradient(ellipse 900px 600px at 100% 8%, rgba(86,216,196,0.08), transparent 55%),
    var(--ink-950);
}
.stApp::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  opacity: 0.035;
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
[data-testid="stHeader"] { background: transparent; }
.block-container {
  padding-top: 1.6rem;
  padding-bottom: 7rem;
  max-width: 940px;
  position: relative;
  z-index: 1;
}
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] strong { color: var(--text-primary); }
[data-testid="stCaptionContainer"] { color: var(--text-tertiary) !important; }
hr { border-color: var(--hairline) !important; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--ink-950); }
::-webkit-scrollbar-thumb { background: var(--ink-700); border-radius: 8px; }
::-webkit-scrollbar-thumb:hover { background: var(--copper-dim); }
::selection { background: rgba(242,166,90,0.35); }
a:focus-visible, button:focus-visible, input:focus-visible, [tabindex]:focus-visible {
  outline: 2px solid var(--copper) !important; outline-offset: 2px;
}

/* ── Hero ────────────────────────────────────────────────── */
.hero {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 24px; padding-bottom: 18px; margin-bottom: 20px;
  border-bottom: 1px solid var(--hairline); flex-wrap: wrap;
}
.hero-eyebrow {
  font-family: var(--font-mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.18em; text-transform: uppercase; color: var(--teal);
  display: block; margin-bottom: 8px;
}
.hero-title {
  font-family: var(--font-display); font-weight: 800; font-size: 30px;
  letter-spacing: -0.02em; margin: 0 0 6px 0; color: var(--text-primary);
}
.hero-sub { font-size: 14px; color: var(--text-secondary); margin: 0; max-width: 48ch; }
.status-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--font-mono); font-size: 12px; font-weight: 600; letter-spacing: 0.04em;
  padding: 8px 14px; border-radius: 999px; border: 1px solid var(--hairline);
  background: var(--ink-800); white-space: nowrap;
}
.status-live { color: var(--copper); border-color: rgba(242,166,90,0.35); }
.status-offline { color: var(--text-tertiary); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.status-live .status-dot { animation: ping 1.8s ease-out infinite; }
@keyframes ping {
  0%   { box-shadow: 0 0 0 0 rgba(242,166,90,0.55); }
  100% { box-shadow: 0 0 0 9px rgba(242,166,90,0); }
}

/* ── Sidebar ─────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, var(--ink-900), var(--ink-850));
  border-right: 1px solid var(--hairline);
}
[data-testid="stSidebar"] * { color: var(--text-primary); }
[data-testid="stSidebar"] hr { border-color: var(--hairline) !important; margin: 1.1rem 0; }
.sidebar-eyebrow {
  font-family: var(--font-mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--copper);
  margin: 2px 0 12px 0; display: flex; align-items: center; gap: 7px;
}
.sidebar-eyebrow::before {
  content: ''; width: 6px; height: 6px; border-radius: 50%;
  background: var(--copper); box-shadow: 0 0 8px rgba(242,166,90,0.7); flex-shrink: 0;
}
.msg-count {
  font-family: var(--font-mono); font-size: 11.5px; color: var(--text-tertiary);
  background: var(--ink-800); border: 1px solid var(--hairline); display: inline-block;
  padding: 5px 10px; border-radius: 8px; letter-spacing: 0.02em;
}

/* ── Chat messages ───────────────────────────────────────── */
[data-testid="stChatMessage"] {
  background: var(--ink-850) !important;
  border: 1px solid var(--hairline) !important;
  border-radius: 16px !important;
  padding: 14px 16px !important;
  margin-bottom: 14px !important;
  animation: rise 0.22s ease both;
  box-shadow: 0 8px 20px -14px rgba(0,0,0,0.6);
}
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: linear-gradient(135deg, rgba(242,166,90,0.14), rgba(242,166,90,0.05)) !important;
  border-color: rgba(242,166,90,0.25) !important;
  flex-direction: row-reverse;
  margin-left: 14%;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  margin-right: 14%;
}
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {
  background: var(--ink-700) !important; border: 1px solid var(--hairline);
}
.msg-badge {
  display: inline-flex; align-items: center; gap: 5px;
  font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: 0.02em;
  padding: 3px 9px; border-radius: 6px; margin-right: 6px; margin-bottom: 4px; border: 1px solid transparent;
}
.badge-agent { background: rgba(86,216,196,0.12); color: var(--teal); border-color: rgba(86,216,196,0.28); }
.badge-country { background: rgba(123,216,143,0.12); color: var(--green); border-color: rgba(123,216,143,0.28); }
.badge-time { background: rgba(242,166,90,0.12); color: var(--copper); border-color: rgba(242,166,90,0.28); }
.badge-newsess { background: rgba(241,104,94,0.12); color: var(--coral); border-color: rgba(241,104,94,0.28); }

/* ── Buttons ─────────────────────────────────────────────── */
.stButton button, [data-testid="stFormSubmitButton"] button, button[kind="secondary"], button[kind="primary"] {
  font-family: var(--font-display) !important; font-weight: 600 !important;
  border-radius: 10px !important; border: 1px solid var(--hairline) !important;
  background: var(--ink-800) !important; color: var(--text-primary) !important;
  transition: all 0.15s ease !important;
}
.stButton button:hover, [data-testid="stFormSubmitButton"] button:hover {
  transform: translateY(-1px); border-color: var(--copper) !important;
  box-shadow: 0 6px 16px -8px rgba(242,166,90,0.4);
}
button[kind="primary"] {
  background: linear-gradient(135deg, var(--copper), var(--copper-dim)) !important;
  border-color: transparent !important; color: #1A1206 !important;
}
button[kind="primary"]:hover { box-shadow: 0 8px 20px -8px rgba(242,166,90,0.55) !important; }

/* ── Inputs ──────────────────────────────────────────────── */
[data-testid="stTextInput"] input {
  background: var(--ink-800) !important; border: 1px solid var(--hairline) !important;
  border-radius: 10px !important; color: var(--text-primary) !important;
  font-family: var(--font-mono) !important; font-size: 13px !important;
}
[data-testid="stTextInput"] input:focus {
  border-color: var(--copper) !important; box-shadow: 0 0 0 3px rgba(242,166,90,0.15) !important;
}
[data-baseweb="select"] > div {
  background: var(--ink-800) !important; border-color: var(--hairline) !important; border-radius: 10px !important;
}
[data-baseweb="popover"] { background: var(--ink-800) !important; }
[data-baseweb="menu"] li { background: var(--ink-800) !important; color: var(--text-primary) !important; }
[data-baseweb="menu"] li:hover { background: var(--ink-700) !important; }
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label { color: var(--text-primary) !important; font-size: 13.5px; }

/* ── Alerts / form / code ────────────────────────────────── */
[data-testid="stAlert"], [data-testid="stAlertContainer"] {
  background: var(--ink-800) !important; border: 1px solid var(--hairline) !important;
  border-radius: 12px !important; color: var(--text-primary) !important;
}
[data-testid="stForm"] {
  background: var(--ink-850); border: 1px solid var(--hairline);
  border-radius: 16px; padding: 18px 18px 6px 18px;
}
[data-testid="stCodeBlock"] pre {
  background: var(--ink-900) !important; border: 1px solid var(--hairline) !important; border-radius: 10px !important;
}
[data-testid="stCodeBlock"] code { font-family: var(--font-mono) !important; font-size: 12.5px !important; }

/* ── Chat input ──────────────────────────────────────────── */
[data-testid="stChatInput"] {
  background: var(--ink-850) !important; border: 1px solid var(--hairline) !important; border-radius: 14px !important;
}
[data-testid="stChatInput"] textarea { color: var(--text-primary) !important; font-family: var(--font-display) !important; }
[data-testid="stBottomBlockContainer"] { background: linear-gradient(180deg, transparent, var(--ink-950) 45%) !important; }
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
    st.session_state.render_mode = "Interactive Form"
if "show_meta" not in st.session_state:
    st.session_state.show_meta = True
# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-eyebrow">Configuration</div>', unsafe_allow_html=True)
    st.session_state.config["mcp_url"] = st.text_input("MCP URL", st.session_state.config["mcp_url"])
    st.session_state.config["api_key"] = st.text_input("API Key", st.session_state.config["api_key"], type="password")
    st.session_state.config["ohr"] = st.text_input("OHR", st.session_state.config["ohr"])
    st.divider()
    st.markdown('<div class="sidebar-eyebrow">Session</div>', unsafe_allow_html=True)
    if st.session_state.mcp_session_id:
        st.success(f"**Connected**\n\n`{st.session_state.mcp_session_id[:28]}...`")
    else:
        st.warning("Not connected")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🛰️ Connect", use_container_width=True, type="primary"):
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
        if st.button("↺ New Session", use_container_width=True):
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
                })
                st.rerun()
            except Exception as e:
                st.error(f"Reset failed: {e}")
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.divider()
    st.markdown('<div class="sidebar-eyebrow">Auto New-Session</div>', unsafe_allow_html=True)
    st.session_state.always_new_session = st.checkbox(
        "Send `new_session=True` on every message",
        value=st.session_state.always_new_session,
    )
    if st.session_state.next_new_session:
        st.info("↺ Next message will use new_session=True")
    st.divider()
    st.markdown('<div class="sidebar-eyebrow">Display Mode</div>', unsafe_allow_html=True)
    st.session_state.render_mode = st.radio(
        "Show agent replies as",
        ["Interactive Form", "HTML Preview", "Raw HTML"],
        index=["Interactive Form", "HTML Preview", "Raw HTML"].index(st.session_state.render_mode),
        help="Interactive Form = native Streamlit dropdowns (recommended). HTML Preview = read-only styled preview. Raw HTML = source.",
    )
    st.session_state.show_meta = st.checkbox("Show badges", value=st.session_state.show_meta)
    st.divider()
    st.markdown(f'<span class="msg-count">💬 {len(st.session_state.messages)} messages</span>', unsafe_allow_html=True)
# ── Main ──────────────────────────────────────────────────────────────────────
_connected = bool(st.session_state.mcp_session_id)
_status_label = f"LIVE · {st.session_state.mcp_session_id[:10]}…" if _connected else "OFFLINE"
_status_class = "status-live" if _connected else "status-offline"
st.markdown(f"""
<div class="hero">
  <div>
    <span class="hero-eyebrow">MCP · Universal Bot V2</span>
    <h1 class="hero-title">MCP Chat Tester</h1>
    <p class="hero-sub">Interactive test harness — real dropdowns, real submissions, real telemetry.</p>
  </div>
  <span class="status-chip {_status_class}"><span class="status-dot"></span>{_status_label}</span>
</div>
""", unsafe_allow_html=True)
if not st.session_state.mcp_session_id:
    st.info("👈 Click **Connect** in the sidebar to link this tester to the MCP endpoint.")
    st.stop()
def send_message(text, use_new_session):
    """Add user msg, call MCP, add assistant msg."""
    st.session_state.messages.append({
        "role": "user",
        "content": text,
        "meta": {"new_session": use_new_session},
    })
    with st.chat_message("user", avatar="🧑"):
        st.markdown(text)
    with st.chat_message("assistant", avatar="🛰️"):
        with st.spinner("Awaiting agent response…"):
            parsed, elapsed = call_work_agent(
                mcp_url=st.session_state.config["mcp_url"],
                api_key=st.session_state.config["api_key"],
                session_id=st.session_state.mcp_session_id,
                ohr=st.session_state.config["ohr"],
                query=text,
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
# ── Render chat history ───────────────────────────────────────────────────────
for i, msg in enumerate(st.session_state.messages):
    role = msg["role"]
    if role == "system":
        st.info(f"🔄 {msg['content']}")
        continue
    with st.chat_message(role, avatar="🧑" if role == "user" else "🛰️"):
        if role == "user":
            st.markdown(msg["content"])
            continue
        # assistant message
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
        mode = st.session_state.render_mode
        if mode == "Raw HTML":
            st.code(content, language="html")
            continue
        if mode == "HTML Preview":
            # Static preview only, no interaction
            if "<" in content and ">" in content:
                # Render as-is via markdown (unsafe html)
                st.markdown(clean_html_for_preview(content), unsafe_allow_html=True)
            else:
                st.markdown(content)
            continue
        # mode == "Interactive Form"
        fields = parse_agent_form(content)
        if not fields:
            # No parseable form, just show text/HTML as-is
            if "<" in content and ">" in content:
                st.markdown(clean_html_for_preview(content), unsafe_allow_html=True)
            else:
                st.markdown(content)
            continue
        # Only the LATEST assistant message gets interactive form
        is_latest_assistant = (i == len(st.session_state.messages) - 1)
        # Info text (agent prose)
        for f in fields:
            if f["kind"] == "info":
                st.markdown(f["text"])
        interactive_fields = [f for f in fields if f["kind"] in ("select", "text")]
        if not interactive_fields:
            continue
        if not is_latest_assistant:
            # Show static preview for historical assistant messages
            st.caption("*(Form from earlier turn — interact with the latest message.)*")
            for f in interactive_fields:
                if f["kind"] == "select":
                    st.markdown(f"**{f['label']}** — options: {', '.join(o[0] for o in f['options'])}")
                elif f["kind"] == "text":
                    st.markdown(f"**{f['label']}** — [text input]")
            continue
        # Build native Streamlit widgets
        st.markdown('<div class="sidebar-eyebrow" style="margin:10px 0 2px 0;">Respond to agent</div>', unsafe_allow_html=True)
        with st.form(key=f"agent_form_{i}", clear_on_submit=False):
            widget_vals = {}
            for j, f in enumerate(interactive_fields):
                widget_key = f"agent_form_{i}_field_{j}"
                if f["kind"] == "select":
                    opt_labels = [o[0] for o in f["options"]]
                    if not opt_labels:
                        continue
                    default_idx = 0
                    if f.get("default"):
                        for k, (lbl, val) in enumerate(f["options"]):
                            if val == f["default"]:
                                default_idx = k
                                break
                    widget_vals[f["label"]] = st.selectbox(
                        f["label"], opt_labels, index=default_idx, key=widget_key,
                    )
                elif f["kind"] == "text":
                    widget_vals[f["label"]] = st.text_input(
                        f["label"],
                        value=f.get("default", ""),
                        placeholder=f.get("placeholder", ""),
                        key=widget_key,
                    )
            submitted = st.form_submit_button("📤 Send", type="primary", use_container_width=False)
            if submitted:
                # Combine values into a comma-separated string (matches how real UI would post)
                combined = ", ".join(str(v).strip() for v in widget_vals.values() if str(v).strip())
                if combined:
                    use_new = st.session_state.always_new_session or st.session_state.next_new_session
                    st.session_state.next_new_session = False
                    send_message(combined, use_new)
                    st.rerun()
# ── Chat input ────────────────────────────────────────────────────────────────
user_query = st.chat_input("Message the agent…")
if user_query:
    use_new = st.session_state.always_new_session or st.session_state.next_new_session
    st.session_state.next_new_session = False
    send_message(user_query, use_new)
    st.rerun()
