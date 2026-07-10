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
st.set_page_config(page_title="MCP Chat", page_icon="📡", layout="wide")

# ── MEGA CSS — every selector uses !important to beat Streamlit defaults ──────
st.markdown("""
<style>
/* ═══════════════════════════════════════════════════════════
   DESIGN SYSTEM – "Midnight Signal"
   Palette: deep navy base, warm amber accent, teal secondary
   Type: system stack (no external font loads = faster)
   ═══════════════════════════════════════════════════════════ */

/* ── 0. GLOBAL RESET ──────────────────────────────────────── */
:root {
  --bg-base:     #0C0F1A;
  --bg-raised:   #111627;
  --bg-surface:  #161C2E;
  --bg-hover:    #1B2340;
  --border:      #232D4A;
  --border-lit:  #2E3B5E;
  --text-1:      #EDF0F7;
  --text-2:      #A0AABF;
  --text-3:      #697080;
  --amber:       #F5A623;
  --amber-dim:   #C4851C;
  --amber-glow:  rgba(245,166,35,0.15);
  --amber-ghost: rgba(245,166,35,0.08);
  --teal:        #4DD9C0;
  --teal-dim:    rgba(77,217,192,0.12);
  --green:       #5FD068;
  --red:         #F06B5E;
  --font:        -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --mono:        "SF Mono", "Cascadia Code", "JetBrains Mono", "Fira Code", Consolas, monospace;
  --radius-sm:   8px;
  --radius-md:   12px;
  --radius-lg:   16px;
}

/* Kill Streamlit default backgrounds everywhere */
html, body, [data-testid="stAppViewContainer"],
[data-testid="stApp"], .stApp,
[data-testid="stAppViewBlockContainer"],
.main .block-container,
[data-testid="stMainBlockContainer"] {
  background-color: var(--bg-base) !important;
  color: var(--text-1) !important;
  font-family: var(--font) !important;
}
.stApp {
  background:
    radial-gradient(ellipse 80% 50% at 5% 0%, rgba(245,166,35,0.06), transparent 60%),
    radial-gradient(ellipse 70% 50% at 95% 5%, rgba(77,217,192,0.05), transparent 55%),
    var(--bg-base) !important;
}

/* Header bar — transparent */
header[data-testid="stHeader"],
[data-testid="stHeader"] {
  background: transparent !important;
  backdrop-filter: none !important;
}
/* Top toolbar / decoration bar */
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }

/* Main content container */
.block-container, [data-testid="stMainBlockContainer"] {
  padding-top: 1.8rem !important;
  padding-bottom: 7rem !important;
  max-width: 880px !important;
}

/* All text defaults */
p, li, span, div, label, [class*="css"] {
  color: var(--text-1) !important;
  font-family: var(--font) !important;
}
small, .stCaption, [data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p {
  color: var(--text-3) !important;
}
h1, h2, h3, h4, h5, h6 { color: var(--text-1) !important; }

/* Dividers */
hr, [data-testid="stDivider"] {
  border-color: var(--border) !important;
  opacity: 1 !important;
}

/* ── 1. SIDEBAR ───────────────────────────────────────────── */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] > div > div,
section[data-testid="stSidebar"] {
  background-color: var(--bg-raised) !important;
  background-image: none !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] *,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span {
  color: var(--text-2) !important;
  font-family: var(--font) !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
  color: var(--text-1) !important;
}

/* Sidebar section labels */
.sb-label {
  font-family: var(--mono) !important;
  font-size: 10.5px !important;
  font-weight: 700 !important;
  letter-spacing: 0.14em !important;
  text-transform: uppercase !important;
  color: var(--amber) !important;
  margin: 0 0 10px 0 !important;
  padding: 0 !important;
  display: flex !important;
  align-items: center !important;
  gap: 8px !important;
}
.sb-label::before {
  content: '' !important;
  width: 5px !important; height: 5px !important; border-radius: 50% !important;
  background: var(--amber) !important;
  box-shadow: 0 0 6px var(--amber) !important;
  flex-shrink: 0 !important;
}

/* ── 2. INPUTS (text, selectbox, radio, checkbox) ─────────── */
/* Text inputs */
[data-testid="stTextInput"] > div > div > input,
input[type="text"],
input[type="password"] {
  background-color: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  color: var(--text-1) !important;
  font-family: var(--mono) !important;
  font-size: 13px !important;
  caret-color: var(--amber) !important;
  padding: 8px 12px !important;
}
[data-testid="stTextInput"] > div > div > input:focus,
input[type="text"]:focus,
input[type="password"]:focus {
  border-color: var(--amber) !important;
  box-shadow: 0 0 0 2px var(--amber-glow) !important;
  outline: none !important;
}
/* Input labels */
[data-testid="stTextInput"] label,
[data-testid="stSelectbox"] label,
.stSelectbox label {
  color: var(--text-2) !important;
  font-size: 13px !important;
  font-weight: 500 !important;
}

/* Select / dropdown */
[data-baseweb="select"],
[data-baseweb="select"] > div {
  background-color: var(--bg-surface) !important;
  border-color: var(--border) !important;
  border-radius: var(--radius-sm) !important;
}
[data-baseweb="select"] > div:hover,
[data-baseweb="select"] > div:focus-within {
  border-color: var(--amber) !important;
}
[data-baseweb="select"] span,
[data-baseweb="select"] div[role="option"] {
  color: var(--text-1) !important;
}
/* Dropdown popover */
[data-baseweb="popover"],
[data-baseweb="popover"] > div {
  background-color: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
}
[data-baseweb="menu"] li,
ul[role="listbox"] li {
  background-color: var(--bg-surface) !important;
  color: var(--text-1) !important;
}
[data-baseweb="menu"] li:hover,
ul[role="listbox"] li:hover,
[data-baseweb="menu"] li[aria-selected="true"] {
  background-color: var(--bg-hover) !important;
}

/* Radio buttons */
[data-testid="stRadio"] label {
  color: var(--text-2) !important;
  font-size: 13px !important;
}
[data-testid="stRadio"] [role="radiogroup"] label div[data-testid="stMarkdownContainer"] p {
  color: var(--text-2) !important;
}

/* Checkbox */
[data-testid="stCheckbox"] label span {
  color: var(--text-2) !important;
  font-size: 13px !important;
}

/* ── 3. BUTTONS ───────────────────────────────────────────── */
.stButton > button,
[data-testid="stBaseButton-secondary"],
button[kind="secondary"] {
  background-color: var(--bg-surface) !important;
  color: var(--text-1) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  font-family: var(--font) !important;
  font-weight: 600 !important;
  font-size: 13px !important;
  padding: 6px 16px !important;
  transition: all 0.15s ease !important;
}
.stButton > button:hover,
[data-testid="stBaseButton-secondary"]:hover {
  background-color: var(--bg-hover) !important;
  border-color: var(--amber-dim) !important;
  color: var(--amber) !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
}

/* Primary buttons */
[data-testid="stBaseButton-primary"],
button[kind="primary"],
[data-testid="stFormSubmitButton"] button {
  background: linear-gradient(135deg, var(--amber), var(--amber-dim)) !important;
  color: #0C0F1A !important;
  border: none !important;
  border-radius: var(--radius-sm) !important;
  font-weight: 700 !important;
  font-size: 13px !important;
  padding: 8px 20px !important;
  transition: all 0.15s ease !important;
}
[data-testid="stBaseButton-primary"]:hover,
button[kind="primary"]:hover,
[data-testid="stFormSubmitButton"] button:hover {
  box-shadow: 0 6px 18px rgba(245,166,35,0.4) !important;
  transform: translateY(-1px) !important;
}

/* ── 4. ALERTS (success, warning, info, error) ────────────── */
[data-testid="stAlert"],
[data-testid="stAlertContainer"],
[data-testid="stAlert"] > div,
.stAlert, .element-container .stAlert {
  background-color: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-md) !important;
  color: var(--text-1) !important;
}
[data-testid="stAlert"] p { color: var(--text-1) !important; }
/* Success green left border */
[data-baseweb="notification"][kind="positive"],
div[data-testid="stAlert"]:has(svg[data-testid="stIconMaterial"]) {
  border-left: 3px solid var(--teal) !important;
}

/* ── 5. CHAT MESSAGES ─────────────────────────────────────── */
[data-testid="stChatMessage"] {
  background-color: var(--bg-raised) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  padding: 16px 18px !important;
  margin-bottom: 12px !important;
  box-shadow: 0 2px 12px rgba(0,0,0,0.25) !important;
}
/* User message — warm tint, right-aligned feel */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: linear-gradient(135deg, rgba(245,166,35,0.10), rgba(245,166,35,0.03)) !important;
  border-color: rgba(245,166,35,0.20) !important;
  margin-left: 12% !important;
}
/* Assistant message */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  background-color: var(--bg-raised) !important;
  margin-right: 12% !important;
}
/* Avatar circles */
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {
  background-color: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
}

/* ── 6. BADGES ────────────────────────────────────────────── */
.msg-badge {
  display: inline-flex !important;
  align-items: center !important;
  gap: 4px !important;
  font-family: var(--mono) !important;
  font-size: 10.5px !important;
  font-weight: 600 !important;
  letter-spacing: 0.02em !important;
  padding: 3px 8px !important;
  border-radius: 6px !important;
  margin-right: 6px !important;
  margin-bottom: 4px !important;
  border: 1px solid transparent !important;
}
.badge-agent   { background: var(--teal-dim) !important; color: var(--teal) !important; border-color: rgba(77,217,192,0.25) !important; }
.badge-country { background: rgba(95,208,104,0.10) !important; color: var(--green) !important; border-color: rgba(95,208,104,0.25) !important; }
.badge-time    { background: var(--amber-ghost) !important; color: var(--amber) !important; border-color: rgba(245,166,35,0.25) !important; }
.badge-newsess { background: rgba(240,107,94,0.10) !important; color: var(--red) !important; border-color: rgba(240,107,94,0.25) !important; }

/* ── 7. HERO HEADER ───────────────────────────────────────── */
.hero-wrap {
  display: flex !important;
  align-items: flex-end !important;
  justify-content: space-between !important;
  gap: 20px !important;
  padding-bottom: 20px !important;
  margin-bottom: 24px !important;
  border-bottom: 1px solid var(--border) !important;
  flex-wrap: wrap !important;
}
.hero-eyebrow {
  font-family: var(--mono) !important;
  font-size: 10.5px !important;
  font-weight: 700 !important;
  letter-spacing: 0.16em !important;
  text-transform: uppercase !important;
  color: var(--teal) !important;
  margin-bottom: 6px !important;
}
.hero-title {
  font-size: 28px !important;
  font-weight: 800 !important;
  letter-spacing: -0.025em !important;
  color: var(--text-1) !important;
  margin: 0 0 4px 0 !important;
  line-height: 1.1 !important;
}
.hero-sub {
  font-size: 14px !important;
  color: var(--text-3) !important;
  margin: 0 !important;
  max-width: 44ch !important;
  line-height: 1.5 !important;
}
.status-pill {
  display: inline-flex !important;
  align-items: center !important;
  gap: 8px !important;
  font-family: var(--mono) !important;
  font-size: 11px !important;
  font-weight: 700 !important;
  letter-spacing: 0.05em !important;
  padding: 7px 14px !important;
  border-radius: 999px !important;
  background: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  white-space: nowrap !important;
}
.status-pill--live { color: var(--amber) !important; border-color: rgba(245,166,35,0.30) !important; }
.status-pill--off  { color: var(--text-3) !important; }
.status-dot {
  width: 7px !important; height: 7px !important;
  border-radius: 50% !important;
  background: currentColor !important;
  flex-shrink: 0 !important;
}
.status-pill--live .status-dot {
  animation: pulse 2s ease-in-out infinite !important;
}
@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245,166,35,0.5); }
  50%      { box-shadow: 0 0 0 6px rgba(245,166,35,0); }
}

/* ── 8. FORMS ─────────────────────────────────────────────── */
[data-testid="stForm"],
[data-testid="stForm"] > div {
  background-color: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-md) !important;
  padding: 16px !important;
}

/* ── 9. CODE BLOCKS ───────────────────────────────────────── */
[data-testid="stCodeBlock"] pre,
pre, code {
  background-color: var(--bg-base) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
  color: var(--text-1) !important;
  font-family: var(--mono) !important;
  font-size: 12.5px !important;
}

/* ── 10. CHAT INPUT (bottom bar) ──────────────────────────── */
[data-testid="stChatInput"],
[data-testid="stChatInput"] > div {
  background-color: var(--bg-raised) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-md) !important;
}
[data-testid="stChatInput"] textarea {
  color: var(--text-1) !important;
  font-family: var(--font) !important;
  font-size: 14px !important;
  caret-color: var(--amber) !important;
}
[data-testid="stChatInput"] textarea::placeholder {
  color: var(--text-3) !important;
}
/* Fade gradient at bottom */
[data-testid="stBottomBlockContainer"] {
  background: linear-gradient(0deg, var(--bg-base), var(--bg-base) 60%, transparent) !important;
}

/* ── 11. SPINNER ──────────────────────────────────────────── */
[data-testid="stSpinner"] > div,
.stSpinner > div { color: var(--amber) !important; }

/* ── 12. SCROLLBAR ────────────────────────────────────────── */
::-webkit-scrollbar { width: 8px !important; }
::-webkit-scrollbar-track { background: var(--bg-base) !important; }
::-webkit-scrollbar-thumb { background: var(--border) !important; border-radius: 8px !important; }
::-webkit-scrollbar-thumb:hover { background: var(--border-lit) !important; }

/* ── 13. FOCUS + a11y ─────────────────────────────────────── */
a:focus-visible, button:focus-visible, input:focus-visible,
[tabindex]:focus-visible, textarea:focus-visible {
  outline: 2px solid var(--amber) !important;
  outline-offset: 2px !important;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    transition-duration: 0.001ms !important;
  }
}
::selection { background: rgba(245,166,35,0.30) !important; }

/* ── 14. MESSAGE COUNT CHIP ───────────────────────────────── */
.msg-count-chip {
  font-family: var(--mono) !important;
  font-size: 11px !important;
  color: var(--text-3) !important;
  background: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  display: inline-block !important;
  padding: 5px 10px !important;
  border-radius: var(--radius-sm) !important;
}

/* ── 15. MISC STREAMLIT OVERRIDES ─────────────────────────── */
/* Expander */
[data-testid="stExpander"] {
  background: var(--bg-surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-md) !important;
}
/* Tooltip / help icon */
[data-testid="stTooltipIcon"] svg { color: var(--text-3) !important; }
/* Markdown links */
a { color: var(--amber) !important; }
a:hover { color: var(--teal) !important; }
/* Remove Streamlit bottom "Made with Streamlit" */
footer { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
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
    st.markdown('<p class="sb-label">Configuration</p>', unsafe_allow_html=True)
    st.session_state.config["mcp_url"] = st.text_input("MCP URL", st.session_state.config["mcp_url"])
    st.session_state.config["api_key"] = st.text_input("API Key", st.session_state.config["api_key"], type="password")
    st.session_state.config["ohr"] = st.text_input("OHR", st.session_state.config["ohr"])
    st.divider()

    st.markdown('<p class="sb-label">Session</p>', unsafe_allow_html=True)
    if st.session_state.mcp_session_id:
        st.success(f"**Connected**\n\n`{st.session_state.mcp_session_id[:28]}...`")
    else:
        st.warning("Not connected")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Connect", use_container_width=True, type="primary"):
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
        if st.button("New Session", use_container_width=True):
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
    if st.button("Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.divider()

    st.markdown('<p class="sb-label">Options</p>', unsafe_allow_html=True)
    st.session_state.always_new_session = st.checkbox(
        "Send new_session=True every message",
        value=st.session_state.always_new_session,
    )
    if st.session_state.next_new_session:
        st.info("Next message will use new_session=True")
    st.divider()

    st.markdown('<p class="sb-label">Display</p>', unsafe_allow_html=True)
    st.session_state.render_mode = st.radio(
        "Show agent replies as",
        ["Interactive Form", "HTML Preview", "Raw HTML"],
        index=["Interactive Form", "HTML Preview", "Raw HTML"].index(st.session_state.render_mode),
        help="Interactive Form = native Streamlit dropdowns. HTML Preview = read-only styled. Raw HTML = source.",
    )
    st.session_state.show_meta = st.checkbox("Show badges", value=st.session_state.show_meta)
    st.divider()

    st.markdown(
        f'<span class="msg-count-chip">{len(st.session_state.messages)} messages</span>',
        unsafe_allow_html=True,
    )

# ── Hero Header ───────────────────────────────────────────────────────────────
_connected = bool(st.session_state.mcp_session_id)
if _connected:
    _pill_label = f"LIVE &middot; {st.session_state.mcp_session_id[:12]}&hellip;"
    _pill_cls = "status-pill status-pill--live"
else:
    _pill_label = "OFFLINE"
    _pill_cls = "status-pill status-pill--off"

st.markdown(f"""
<div class="hero-wrap">
  <div>
    <div class="hero-eyebrow">MCP &middot; Universal Bot V2</div>
    <h1 class="hero-title">MCP Chat Tester</h1>
    <p class="hero-sub">Interactive test harness &mdash; real dropdowns, real submissions, real telemetry.</p>
  </div>
  <span class="{_pill_cls}"><span class="status-dot"></span>{_pill_label}</span>
</div>
""", unsafe_allow_html=True)

if not st.session_state.mcp_session_id:
    st.info("Click **Connect** in the sidebar to start a session.")
    st.stop()

# ── send_message (unchanged logic) ────────────────────────────────────────────
def send_message(text, use_new_session):
    """Add user msg, call MCP, add assistant msg."""
    st.session_state.messages.append({
        "role": "user",
        "content": text,
        "meta": {"new_session": use_new_session},
    })
    with st.chat_message("user", avatar="🧑"):
        st.markdown(text)
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Agent thinking..."):
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

# ── Render chat history (unchanged logic) ─────────────────────────────────────
for i, msg in enumerate(st.session_state.messages):
    role = msg["role"]
    if role == "system":
        st.info(f"🔄 {msg['content']}")
        continue
    with st.chat_message(role, avatar="🧑" if role == "user" else "🤖"):
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
            if "<" in content and ">" in content:
                st.markdown(clean_html_for_preview(content), unsafe_allow_html=True)
            else:
                st.markdown(content)
            continue
        # mode == "Interactive Form"
        fields = parse_agent_form(content)
        if not fields:
            if "<" in content and ">" in content:
                st.markdown(clean_html_for_preview(content), unsafe_allow_html=True)
            else:
                st.markdown(content)
            continue
        is_latest_assistant = (i == len(st.session_state.messages) - 1)
        for f in fields:
            if f["kind"] == "info":
                st.markdown(f["text"])
        interactive_fields = [f for f in fields if f["kind"] in ("select", "text")]
        if not interactive_fields:
            continue
        if not is_latest_assistant:
            st.caption("*(Form from earlier turn — interact with the latest message.)*")
            for f in interactive_fields:
                if f["kind"] == "select":
                    st.markdown(f"**{f['label']}** — options: {', '.join(o[0] for o in f['options'])}")
                elif f["kind"] == "text":
                    st.markdown(f"**{f['label']}** — [text input]")
            continue
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
            submitted = st.form_submit_button("Submit", type="primary", use_container_width=False)
            if submitted:
                combined = ", ".join(str(v).strip() for v in widget_vals.values() if str(v).strip())
                if combined:
                    use_new = st.session_state.always_new_session or st.session_state.next_new_session
                    st.session_state.next_new_session = False
                    send_message(combined, use_new)
                    st.rerun()

# ── Chat input ────────────────────────────────────────────────────────────────
user_query = st.chat_input("Type your message...")
if user_query:
    use_new = st.session_state.always_new_session or st.session_state.next_new_session
    st.session_state.next_new_session = False
    send_message(user_query, use_new)
    st.rerun()
