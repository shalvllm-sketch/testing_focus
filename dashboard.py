"""
MCP Chat UI — Streamlit test harness for the Universal Bot V2 MCP endpoint.
Talks to MCP over Streamable HTTP + SSE, renders the returned agent HTML
(the "text" field from work_agent's JSON response) so you can see dropdowns,
forms, and layouts exactly as they'd appear in the real UI.

Usage:
    pip install streamlit requests urllib3
    streamlit run mcp_chat.py
"""

import json
import time
import uuid
from typing import Optional, Tuple

import requests
import streamlit as st
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_MCP_URL = "https://corp-wap-weu-uat-tas-scout-02-h0fmgaf5achmfkb0.a03.azurefd.net/mcp"
DEFAULT_API_KEY = "sk-faq-x9Km2pLqR7vNwT4eJdYc8BhA3uZsGfX1"
DEFAULT_OHR     = "703324710"
# ──────────────────────────────────────────────────────────────────────────────


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
    """
    Parse SSE-formatted response. Return joined text content.
    Lines: 'data: {"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"..."}]}}'
    """
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
    resp = requests.post(
        mcp_url, json=payload,
        headers=build_headers(api_key),
        timeout=30, verify=False,
    )
    resp.raise_for_status()
    session_id = resp.headers.get("mcp-session-id") or resp.headers.get("x-session-id")
    if not session_id:
        raise RuntimeError(f"No session ID returned. Headers: {dict(resp.headers)}")
    return session_id


def call_work_agent(
    mcp_url: str,
    api_key: str,
    session_id: str,
    ohr: str,
    query: str,
    new_session: bool = False,
) -> Tuple[dict, float]:
    """
    Call MCP's work_agent tool. Return (parsed_response_dict, elapsed_seconds).
    parsed_response_dict = {"text": "<html>", "agent_name": "...", "country_name": "..."}
    On error, returns {"text": "<error>", "agent_name": "", "country_name": ""}.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": f"req-{int(time.time() * 1000)}",
        "method": "tools/call",
        "params": {
            "name": "work_agent",
            "arguments": {
                "ohr": ohr,
                "query": query,
                "new_session": new_session,
            },
        },
    }
    start = time.perf_counter()
    try:
        resp = requests.post(
            mcp_url, json=payload,
            headers=build_headers(api_key, session_id),
            timeout=120, verify=False,
        )
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

        # work_agent returns a JSON string as the "text" field
        try:
            parsed = json.loads(inner_text)
            if not isinstance(parsed, dict):
                parsed = {"text": str(parsed), "agent_name": "", "country_name": ""}
        except (json.JSONDecodeError, TypeError):
            parsed = {"text": inner_text or "[empty response]", "agent_name": "", "country_name": ""}

        return parsed, elapsed

    except requests.exceptions.Timeout:
        elapsed = round(time.perf_counter() - start, 2)
        return {"text": "ERROR: Request timed out.", "agent_name": "", "country_name": ""}, elapsed
    except requests.exceptions.HTTPError as e:
        elapsed = round(time.perf_counter() - start, 2)
        return {
            "text": f"ERROR: HTTP {e.response.status_code} — {e.response.text[:400]}",
            "agent_name": "", "country_name": "",
        }, elapsed
    except Exception as e:
        elapsed = round(time.perf_counter() - start, 2)
        return {"text": f"ERROR: {e}", "agent_name": "", "country_name": ""}, elapsed


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT UI
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="MCP Chat Tester", page_icon="💬", layout="wide")

# ── Session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {"role": "user|assistant", "content": str, "meta": {}}
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


# ── Sidebar: config + controls ────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Config")
    st.session_state.config["mcp_url"] = st.text_input("MCP URL", st.session_state.config["mcp_url"])
    st.session_state.config["api_key"] = st.text_input("API Key", st.session_state.config["api_key"], type="password")
    st.session_state.config["ohr"] = st.text_input("OHR", st.session_state.config["ohr"])

    st.divider()

    st.subheader("Session")
    if st.session_state.mcp_session_id:
        st.success(f"Connected\n\nID: `{st.session_state.mcp_session_id[:20]}...`")
    else:
        st.warning("Not connected")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔌 Init", use_container_width=True):
            try:
                with st.spinner("Initializing..."):
                    sid = initialize_mcp_session(
                        st.session_state.config["mcp_url"],
                        st.session_state.config["api_key"],
                    )
                    st.session_state.mcp_session_id = sid
                st.rerun()
            except Exception as e:
                st.error(f"Init failed: {e}")

    with col2:
        if st.button("🔄 Reset", use_container_width=True):
            st.session_state.next_new_session = True
            st.session_state.messages.append({
                "role": "system",
                "content": "— Session reset triggered. Next message will start fresh. —",
                "meta": {},
            })
            st.rerun()

    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    st.divider()

    st.subheader("View Options")
    render_mode = st.radio(
        "How to render agent response",
        ["Rendered HTML (see dropdowns/forms)", "Raw HTML source", "Both side-by-side"],
        index=0,
    )
    show_meta = st.checkbox("Show agent_name / country / latency", value=True)

    st.divider()

    st.caption(f"Total messages: {len(st.session_state.messages)}")


# ── Main area ─────────────────────────────────────────────────────────────────
st.title("💬 MCP Chat Tester")
st.caption("Test the Universal Bot V2 MCP endpoint. Type a message below to see how the UI would render.")

if not st.session_state.mcp_session_id:
    st.info("👈 Click **Init** in the sidebar to connect to MCP before chatting.")

# ── Render chat history ───────────────────────────────────────────────────────
for msg in st.session_state.messages:
    role = msg["role"]

    if role == "system":
        st.info(msg["content"])
        continue

    with st.chat_message(role):
        if role == "user":
            st.write(msg["content"])
        else:
            meta = msg.get("meta", {})

            if show_meta:
                badges = []
                if meta.get("agent_name"):
                    badges.append(f"🎯 **{meta['agent_name']}**")
                if meta.get("country_name"):
                    badges.append(f"🌍 {meta['country_name']}")
                if meta.get("elapsed") is not None:
                    badges.append(f"⏱️ {meta['elapsed']}s")
                if badges:
                    st.caption(" · ".join(badges))

            content = msg["content"]

            if render_mode.startswith("Rendered"):
                # Render the HTML directly so dropdowns, forms, etc. show up
                st.components.v1.html(
                    _wrap_for_render(content),
                    height=_estimate_height(content),
                    scrolling=True,
                )
            elif render_mode.startswith("Raw"):
                st.code(content, language="html")
            else:  # Both side-by-side
                left, right = st.columns([1, 1])
                with left:
                    st.markdown("**Rendered:**")
                    st.components.v1.html(
                        _wrap_for_render(content),
                        height=_estimate_height(content),
                        scrolling=True,
                    )
                with right:
                    st.markdown("**Raw HTML:**")
                    st.code(content, language="html")

# ── Chat input ────────────────────────────────────────────────────────────────
def _wrap_for_render(html_content: str) -> str:
    """Wrap the fragment in a minimal HTML doc so it renders cleanly in the iframe."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
  margin: 0;
  padding: 12px;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  background: #ffffff;
  color: #1e293b;
}}
</style>
</head>
<body>
{html_content}
</body>
</html>"""


def _estimate_height(html_content: str) -> int:
    """
    Estimate iframe height so long forms don't get cut off.
    Rough: 20px per line + extra for form controls.
    """
    line_count = html_content.count("\n") + 1
    form_bonus = html_content.count("<select") * 30 + html_content.count("<input") * 30
    fieldset_bonus = html_content.count("<fieldset") * 40
    estimate = max(300, line_count * 18 + form_bonus + fieldset_bonus + 100)
    return min(estimate, 2000)  # cap at 2000px


# Streamlit's chat_input goes at the bottom automatically
user_query = st.chat_input("Type your message...", disabled=(st.session_state.mcp_session_id is None))

if user_query:
    # Append user message immediately
    st.session_state.messages.append({
        "role": "user",
        "content": user_query,
        "meta": {},
    })

    # Call MCP
    new_session_flag = st.session_state.next_new_session
    st.session_state.next_new_session = False  # consume the flag

    with st.spinner("Waiting for agent response..."):
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
