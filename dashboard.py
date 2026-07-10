"""
MCP Chat UI — Streamlit test harness for the Universal Bot V2 MCP endpoint.
Usage:
    pip install -r requirements.txt
    streamlit run dashboard.py
"""
import json
import re
import time
import random
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

# ── Fun: bot moods & waiting messages ─────────────────────────────────────────
BOT_MOODS = {
    "🧘 Zen":       {"emoji": "🧘", "label": "Zen",       "waiting": ["Inhaling packets… exhaling responses…", "Finding inner protocol peace…", "The bot is meditating on your query…", "Aligning chakras with the API…"]},
    "🚀 Hyped":     {"emoji": "🚀", "label": "Hyped",     "waiting": ["FIRING ALL THRUSTERS!!!", "LET'S GOOOOO!!!", "Maximum overdrive engaged!!!", "Sending your message at LUDICROUS SPEED!!!"]},
    "🕵️ Detective": {"emoji": "🕵️", "label": "Detective", "waiting": ["Dusting the server for fingerprints…", "Following the digital breadcrumbs…", "The case of the missing response…", "Interrogating the endpoint…"]},
    "🤖 Normal":    {"emoji": "🤖", "label": "Normal",    "waiting": ["Thinking…", "Processing your request…", "Agent is working on it…", "Waiting for response…"]},
    "🐢 Sleepy":    {"emoji": "🐢", "label": "Sleepy",    "waiting": ["*yawwwn*… sending your message… slowly…", "Zzzz… oh! Right, your message…", "Let me just… *stretches*… okay sending…", "Five more minutes… fine, I'll send it…"]},
    "🎩 Fancy":     {"emoji": "🎩", "label": "Fancy",     "waiting": ["Dispatching your query posthaste, good sir/madam…", "The butler is delivering your request…", "One moment whilst the servers deliberate…", "Preparing a most exquisite response…"]},
}

def get_waiting_msg(mood_key):
    mood = BOT_MOODS.get(mood_key, BOT_MOODS["🤖 Normal"])
    return random.choice(mood["waiting"])

def get_bot_avatar(mood_key):
    mood = BOT_MOODS.get(mood_key, BOT_MOODS["🤖 Normal"])
    return mood["emoji"]

# ══════════════════════════════════════════════════════════════════════════════
# MCP HELPERS  (all logic preserved exactly)
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
# HTML PARSER — extract form fields into a Python structure  (unchanged)
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
        self.current_select = None
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
st.set_page_config(page_title="MCP Chat", page_icon="💬", layout="wide", initial_sidebar_state="expanded")

# ── CSS — Clean light design with depth ───────────────────────────────────────
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

/* ── FOUNDATIONS ──────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], .stApp,
[data-testid="stApp"], [data-testid="stMainBlockContainer"],
.main .block-container {
  background: #F4F6FB !important;
  font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
.stApp {
  background:
    radial-gradient(ellipse 60% 45% at 10% 0%, rgba(99,102,241,0.07), transparent),
    radial-gradient(ellipse 50% 40% at 90% 0%, rgba(236,72,153,0.05), transparent),
    #F4F6FB !important;
}

/* Kill toolbar & deploy button */
[data-testid="stToolbar"], [data-testid="stDecoration"],
header[data-testid="stHeader"], footer { display: none !important; }

/* Force sidebar always visible */
[data-testid="stSidebar"] {
  min-width: 320px !important;
  max-width: 320px !important;
  width: 320px !important;
  transform: none !important;
  position: relative !important;
}
[data-testid="stSidebar"][aria-expanded="false"] {
  min-width: 320px !important;
  width: 320px !important;
  transform: none !important;
  margin-left: 0 !important;
}
/* Hide the collapse button so it can't be hidden */
button[kind="header"] ,
[data-testid="stSidebar"] button[aria-label="Close sidebar"],
[data-testid="collapsedControl"] {
  display: none !important;
}

.block-container, [data-testid="stMainBlockContainer"] {
  padding-top: 2rem !important;
  padding-bottom: 7rem !important;
  max-width: 900px !important;
}

/* Text defaults */
p, li, span, label, div, [class*="css"] {
  color: #1E293B !important;
  font-family: 'DM Sans', -apple-system, sans-serif !important;
}
h1, h2, h3, h4, h5, h6 { color: #0F172A !important; }
small, .stCaption, [data-testid="stCaptionContainer"] p { color: #94A3B8 !important; }
hr { border-color: #E2E8F0 !important; }

/* ── SIDEBAR ─────────────────────────────────────────────── */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] > div > div,
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%) !important;
  border-right: 1px solid #E2E8F0 !important;
}
[data-testid="stSidebar"] *, [data-testid="stSidebar"] p,
[data-testid="stSidebar"] label, [data-testid="stSidebar"] span {
  color: #475569 !important;
}

/* Sidebar section headers */
.sec-head {
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 10px !important; font-weight: 600 !important;
  letter-spacing: 0.12em !important; text-transform: uppercase !important;
  color: #6366F1 !important; margin: 0 0 8px 0 !important;
  padding: 4px 0 !important;
  border-bottom: 2px solid #6366F1 !important;
  display: inline-block !important;
}

/* ── INPUTS ──────────────────────────────────────────────── */
[data-testid="stTextInput"] > div > div > input,
input[type="text"], input[type="password"] {
  background: #FFFFFF !important;
  border: 1.5px solid #E2E8F0 !important;
  border-radius: 10px !important;
  color: #1E293B !important;
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 13px !important;
  padding: 9px 12px !important;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
  transition: all 0.15s !important;
}
[data-testid="stTextInput"] > div > div > input:focus,
input:focus {
  border-color: #6366F1 !important;
  box-shadow: 0 0 0 3px rgba(99,102,241,0.12) !important;
  outline: none !important;
}
[data-testid="stTextInput"] label, [data-testid="stSelectbox"] label {
  color: #64748B !important; font-size: 12px !important; font-weight: 600 !important;
}

/* Select / dropdown */
[data-baseweb="select"] > div {
  background: #FFFFFF !important; border: 1.5px solid #E2E8F0 !important;
  border-radius: 10px !important; box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
}
[data-baseweb="select"] > div:hover { border-color: #6366F1 !important; }
[data-baseweb="select"] span { color: #1E293B !important; }
[data-baseweb="popover"] > div {
  background: #FFFFFF !important; border: 1px solid #E2E8F0 !important;
  border-radius: 10px !important; box-shadow: 0 12px 28px rgba(0,0,0,0.10) !important;
}
[data-baseweb="menu"] li { background: #FFFFFF !important; color: #1E293B !important; }
[data-baseweb="menu"] li:hover { background: #F1F5F9 !important; }

/* Radio & checkbox */
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label span {
  color: #475569 !important; font-size: 13px !important;
}

/* ── BUTTONS ─────────────────────────────────────────────── */
.stButton > button, [data-testid="stBaseButton-secondary"], button[kind="secondary"] {
  background: #FFFFFF !important; color: #374151 !important;
  border: 1.5px solid #E2E8F0 !important; border-radius: 10px !important;
  font-family: 'DM Sans', sans-serif !important; font-weight: 600 !important;
  font-size: 13px !important; padding: 7px 16px !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
  transition: all 0.15s !important;
}
.stButton > button:hover, [data-testid="stBaseButton-secondary"]:hover {
  background: #F8FAFC !important; border-color: #6366F1 !important;
  color: #6366F1 !important; transform: translateY(-1px) !important;
  box-shadow: 0 4px 12px rgba(99,102,241,0.15) !important;
}
/* Primary */
[data-testid="stBaseButton-primary"], button[kind="primary"],
[data-testid="stFormSubmitButton"] button {
  background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
  color: #FFFFFF !important; border: none !important; border-radius: 10px !important;
  font-weight: 700 !important; font-size: 13px !important;
  padding: 8px 22px !important;
  box-shadow: 0 2px 8px rgba(99,102,241,0.30) !important;
  transition: all 0.15s !important;
}
[data-testid="stBaseButton-primary"]:hover, button[kind="primary"]:hover,
[data-testid="stFormSubmitButton"] button:hover {
  box-shadow: 0 6px 20px rgba(99,102,241,0.40) !important;
  transform: translateY(-1px) !important;
}

/* ── ALERTS ──────────────────────────────────────────────── */
[data-testid="stAlert"], [data-testid="stAlertContainer"], .stAlert {
  background: #FFFFFF !important; border: 1px solid #E2E8F0 !important;
  border-radius: 12px !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
}
[data-testid="stAlert"] p { color: #334155 !important; }

/* ── CHAT MESSAGES ───────────────────────────────────────── */
[data-testid="stChatMessage"] {
  background: #FFFFFF !important;
  border: 1px solid #E8ECF4 !important;
  border-radius: 18px !important;
  padding: 16px 20px !important;
  margin-bottom: 10px !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
  transition: box-shadow 0.2s !important;
}
[data-testid="stChatMessage"]:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,0.07) !important;
}
/* User = indigo tint, nudged right */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: linear-gradient(135deg, #EEF2FF, #F5F3FF) !important;
  border-color: #C7D2FE !important;
  margin-left: 10% !important;
}
/* Bot = white, nudged left */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
  margin-right: 10% !important;
}
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {
  background: #F1F5F9 !important; border: 1px solid #E2E8F0 !important;
}

/* ── BADGES ──────────────────────────────────────────────── */
.msg-badge {
  display: inline-flex !important; align-items: center !important; gap: 4px !important;
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 10.5px !important; font-weight: 600 !important;
  padding: 3px 9px !important; border-radius: 6px !important;
  margin-right: 5px !important; margin-bottom: 4px !important;
}
.badge-agent   { background: #EEF2FF !important; color: #4F46E5 !important; }
.badge-country { background: #F0FDF4 !important; color: #16A34A !important; }
.badge-time    { background: #FFF7ED !important; color: #C2410C !important; }
.badge-newsess { background: #FEF2F2 !important; color: #DC2626 !important; }

/* ── HERO ────────────────────────────────────────────────── */
.hero-card {
  background: #FFFFFF !important;
  border: 1px solid #E2E8F0 !important;
  border-radius: 20px !important;
  padding: 28px 32px !important;
  margin-bottom: 24px !important;
  box-shadow: 0 4px 20px rgba(0,0,0,0.05) !important;
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  flex-wrap: wrap !important;
  gap: 16px !important;
}
.hero-left {}
.hero-chip {
  display: inline-block !important;
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 10px !important; font-weight: 600 !important;
  letter-spacing: 0.1em !important; text-transform: uppercase !important;
  color: #6366F1 !important; background: #EEF2FF !important;
  padding: 4px 10px !important; border-radius: 6px !important;
  margin-bottom: 10px !important;
}
.hero-title {
  font-family: 'DM Sans', sans-serif !important;
  font-size: 26px !important; font-weight: 700 !important;
  color: #0F172A !important; margin: 0 0 4px 0 !important;
  letter-spacing: -0.02em !important;
}
.hero-sub {
  font-size: 14px !important; color: #64748B !important;
  margin: 0 !important; line-height: 1.5 !important;
}
/* Status pill */
.st-pill {
  display: inline-flex !important; align-items: center !important; gap: 8px !important;
  font-family: 'IBM Plex Mono', monospace !important;
  font-size: 11px !important; font-weight: 600 !important;
  padding: 8px 16px !important; border-radius: 999px !important;
  white-space: nowrap !important;
}
.st-pill--on {
  background: #F0FDF4 !important; color: #15803D !important;
  border: 1px solid #BBF7D0 !important;
}
.st-pill--off {
  background: #FEF2F2 !important; color: #B91C1C !important;
  border: 1px solid #FECACA !important;
}
.st-dot {
  width: 8px !important; height: 8px !important; border-radius: 50% !important;
  background: currentColor !important;
}
.st-pill--on .st-dot { animation: blink 1.8s ease-in-out infinite !important; }
@keyframes blink {
  0%,100% { opacity:1; } 50% { opacity:0.3; }
}

/* ── FORMS ───────────────────────────────────────────────── */
[data-testid="stForm"], [data-testid="stForm"] > div {
  background: #FAFBFD !important; border: 1px solid #E8ECF4 !important;
  border-radius: 14px !important; padding: 16px !important;
}

/* ── CODE ────────────────────────────────────────────────── */
pre, code, [data-testid="stCodeBlock"] pre {
  background: #F8FAFC !important; border: 1px solid #E2E8F0 !important;
  border-radius: 10px !important; font-family: 'IBM Plex Mono', monospace !important;
  font-size: 12.5px !important; color: #334155 !important;
}

/* ── CHAT INPUT ──────────────────────────────────────────── */
[data-testid="stChatInput"], [data-testid="stChatInput"] > div {
  background: #FFFFFF !important; border: 1.5px solid #E2E8F0 !important;
  border-radius: 14px !important; box-shadow: 0 2px 8px rgba(0,0,0,0.05) !important;
}
[data-testid="stChatInput"] textarea {
  color: #1E293B !important; font-size: 14px !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: #94A3B8 !important; }
[data-testid="stBottomBlockContainer"] {
  background: linear-gradient(0deg, #F4F6FB, #F4F6FB 55%, transparent) !important;
}

/* Spinner */
[data-testid="stSpinner"] > div { color: #6366F1 !important; }

/* Scrollbar */
::-webkit-scrollbar { width: 7px !important; }
::-webkit-scrollbar-track { background: transparent !important; }
::-webkit-scrollbar-thumb { background: #CBD5E1 !important; border-radius: 8px !important; }
::-webkit-scrollbar-thumb:hover { background: #94A3B8 !important; }

/* a11y */
a:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible {
  outline: 2px solid #6366F1 !important; outline-offset: 2px !important;
}
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
::selection { background: rgba(99,102,241,0.20) !important; }
a { color: #6366F1 !important; } a:hover { color: #4F46E5 !important; }
footer, [data-testid="stToolbar"] { display: none !important; }

/* ── FUN: Mood badge ─────────────────────────────────────── */
.mood-badge {
  display: inline-flex !important; align-items: center !important; gap: 6px !important;
  font-size: 13px !important; font-weight: 600 !important;
  padding: 6px 14px !important; border-radius: 10px !important;
  background: linear-gradient(135deg, #FDF4FF, #EEF2FF) !important;
  border: 1px solid #E9D5FF !important; color: #7C3AED !important;
  margin-top: 6px !important;
}
</style>""", unsafe_allow_html=True)

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
if "bot_mood" not in st.session_state:
    st.session_state.bot_mood = "🤖 Normal"
if "msg_count_total" not in st.session_state:
    st.session_state.msg_count_total = 0

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="sec-head">Connection</p>', unsafe_allow_html=True)
    st.session_state.config["mcp_url"] = st.text_input("MCP Endpoint", st.session_state.config["mcp_url"])
    st.session_state.config["api_key"] = st.text_input("API Key", st.session_state.config["api_key"], type="password")
    st.session_state.config["ohr"] = st.text_input("OHR", st.session_state.config["ohr"])
    st.divider()

    st.markdown('<p class="sec-head">Session</p>', unsafe_allow_html=True)
    if st.session_state.mcp_session_id:
        st.success(f"**Connected**\n\n`{st.session_state.mcp_session_id[:28]}…`")
    else:
        st.warning("No active session")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Connect", use_container_width=True, type="primary"):
            try:
                with st.spinner("Connecting…"):
                    sid = initialize_mcp_session(
                        st.session_state.config["mcp_url"],
                        st.session_state.config["api_key"],
                    )
                    st.session_state.mcp_session_id = sid
                st.rerun()
            except Exception as e:
                st.error(f"Init failed: {e}")
    with c2:
        if st.button("Reset", use_container_width=True):
            try:
                with st.spinner("Resetting…"):
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
        st.session_state.msg_count_total = 0
        st.rerun()
    st.divider()

    st.markdown('<p class="sec-head">Options</p>', unsafe_allow_html=True)
    st.session_state.always_new_session = st.checkbox(
        "Send new_session=True every message",
        value=st.session_state.always_new_session,
    )
    if st.session_state.next_new_session:
        st.info("Next message will use new_session=True")
    st.divider()

    st.markdown('<p class="sec-head">Display</p>', unsafe_allow_html=True)
    st.session_state.render_mode = st.radio(
        "Show agent replies as",
        ["Interactive Form", "HTML Preview", "Raw HTML"],
        index=["Interactive Form", "HTML Preview", "Raw HTML"].index(st.session_state.render_mode),
        help="Interactive Form = native Streamlit dropdowns. HTML Preview = styled read-only. Raw HTML = source code.",
    )
    st.session_state.show_meta = st.checkbox("Show response badges", value=st.session_state.show_meta)
    st.divider()

    # ── FUN FEATURE: Bot Mood Selector ────────────────────────────────────────
    st.markdown('<p class="sec-head">Bot Mood 🎭</p>', unsafe_allow_html=True)
    st.session_state.bot_mood = st.selectbox(
        "Set the bot's personality",
        list(BOT_MOODS.keys()),
        index=list(BOT_MOODS.keys()).index(st.session_state.bot_mood),
        help="Changes the bot's avatar and waiting messages. Purely cosmetic — doesn't affect the actual API.",
    )
    mood_data = BOT_MOODS[st.session_state.bot_mood]
    st.markdown(
        f'<div class="mood-badge">{mood_data["emoji"]} Currently: {mood_data["label"]}</div>',
        unsafe_allow_html=True,
    )
    st.caption(f'_Example: "{random.choice(mood_data["waiting"])}"_')
    st.divider()
    msg_count = len([m for m in st.session_state.messages if m["role"] != "system"])
    st.caption(f"💬 {msg_count} messages this session · {st.session_state.msg_count_total} all-time")

# ── Hero ──────────────────────────────────────────────────────────────────────
_connected = bool(st.session_state.mcp_session_id)
if _connected:
    _pill = f'<span class="st-pill st-pill--on"><span class="st-dot"></span>Connected · {st.session_state.mcp_session_id[:12]}…</span>'
else:
    _pill = '<span class="st-pill st-pill--off"><span class="st-dot"></span>Disconnected</span>'

st.markdown(f"""
<div class="hero-card">
  <div class="hero-left">
    <div class="hero-chip">MCP · Universal Bot V2</div>
    <h1 class="hero-title">Chat Tester</h1>
    <p class="hero-sub">Interactive test harness — real dropdowns, real submissions, real telemetry.</p>
  </div>
  {_pill}
</div>
""", unsafe_allow_html=True)

if not st.session_state.mcp_session_id:
    st.info("Click **Connect** in the sidebar to start a session.")
    st.stop()

# ── send_message (logic preserved — mood integrated for UX only) ──────────────
def send_message(text, use_new_session):
    """Add user msg, call MCP, add assistant msg."""
    st.session_state.messages.append({
        "role": "user",
        "content": text,
        "meta": {"new_session": use_new_session},
    })
    bot_avatar = get_bot_avatar(st.session_state.bot_mood)
    with st.chat_message("user", avatar="🧑"):
        st.markdown(text)
    with st.chat_message("assistant", avatar=bot_avatar):
        waiting_msg = get_waiting_msg(st.session_state.bot_mood)
        with st.spinner(waiting_msg):
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
    st.session_state.msg_count_total += 1

# ── Render chat history ───────────────────────────────────────────────────────
bot_avatar = get_bot_avatar(st.session_state.bot_mood)

for i, msg in enumerate(st.session_state.messages):
    role = msg["role"]
    if role == "system":
        st.info(f"🔄 {msg['content']}")
        continue
    with st.chat_message(role, avatar="🧑" if role == "user" else bot_avatar):
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
user_query = st.chat_input("Type your message…")
if user_query:
    use_new = st.session_state.always_new_session or st.session_state.next_new_session
    st.session_state.next_new_session = False
    send_message(user_query, use_new)
    st.rerun()
