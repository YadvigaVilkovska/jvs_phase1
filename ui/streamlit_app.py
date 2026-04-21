"""
Local chat UI for Jeeves — talks to the FastAPI backend only (no duplicated business logic).

Run:
  export JEEVES_API_BASE=http://127.0.0.1:8000
  streamlit run ui/streamlit_app.py
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API_BASE = os.environ.get("JEEVES_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def _format_http_error(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
        detail = body.get("detail")
        if detail is None:
            return exc.response.text or str(exc)
        if isinstance(detail, list):
            parts = []
            for item in detail:
                if isinstance(item, dict):
                    loc = item.get("loc", ())
                    msg = item.get("msg", item)
                    parts.append(f"{'/'.join(str(x) for x in loc)}: {msg}")
                else:
                    parts.append(str(item))
            return "; ".join(parts)
        return str(detail)
    except Exception:
        return exc.response.text or str(exc)


def _request(method: str, path: str, **kwargs: Any) -> Any:
    url = f"{API_BASE}{path}"
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.request(method, url, **kwargs)
            r.raise_for_status()
            if r.content:
                return r.json()
            return None
    except httpx.HTTPStatusError as e:
        st.error(_format_http_error(e))
        return None
    except httpx.RequestError as e:
        st.error(f"Cannot reach backend at {API_BASE!r}: {e}")
        return None


def _init_session() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []  # list[tuple[str, str]] role, text
    if "last_state" not in st.session_state:
        st.session_state.last_state = None
    if "user_id" not in st.session_state:
        st.session_state.user_id = "local-ui-user"
    if "chat_id" not in st.session_state:
        st.session_state.chat_id = None


def _append_assistant_turn(state: dict[str, Any]) -> None:
    for line in state.get("assistant_messages") or []:
        st.session_state.messages.append(("assistant", line))


def main() -> None:
    st.set_page_config(page_title="Jeeves Chat", layout="wide")
    _init_session()

    st.title("Jeeves")
    st.caption(f"Backend: `{API_BASE}` — set `JEEVES_API_BASE` to change.")

    with st.sidebar:
        st.subheader("Session")
        st.session_state.user_id = st.text_input("User ID", value=st.session_state.user_id)
        if st.session_state.chat_id:
            st.caption("chat_id")
            st.code(st.session_state.chat_id, language=None)
        st.caption("No buttons: all actions happen via chat text.")

    col_chat, col_mem = st.columns([2, 1])

    with col_chat:
        st.subheader("Conversation")
        for role, text in st.session_state.messages:
            with st.chat_message(role):
                st.markdown(text)

        state = st.session_state.last_state or {}
        nr = state.get("normalized_request")
        if nr:
            with st.expander("Normalized request (auto-reviewed via chat)", expanded=False):
                st.json(nr)

        prompt = st.chat_input("Message", key="chat_in")
        if prompt:
            # Lazily start a chat on first user message (no buttons).
            if not st.session_state.chat_id:
                out0 = _request(
                    "POST",
                    "/chat/turn",
                    json={
                        "chat_id": None,
                        "user_id": st.session_state.user_id,
                        "user_message": prompt,
                    },
                )
                if out0:
                    st.session_state.chat_id = out0["chat_id"]
                    st.session_state.messages = []
                    st.session_state.last_state = out0["state"]
                    _append_assistant_turn(out0["state"])
                    st.rerun()
            if st.session_state.chat_id:
                st.session_state.messages.append(("user", prompt))
                out = _request(
                    "POST",
                    "/chat/turn",
                    json={
                        "chat_id": st.session_state.chat_id,
                        "user_id": st.session_state.user_id,
                        "user_message": prompt,
                    },
                )
                if out:
                    st.session_state.chat_id = out["chat_id"]
                    st.session_state.last_state = out["state"]
                    _append_assistant_turn(out["state"])
                    st.rerun()

    with col_mem:
        st.subheader("Memory candidates")
        if not st.session_state.chat_id:
            st.caption("Start a chat to load candidates for this chat_id.")
        else:
            data = _request(
                "GET",
                "/memory/candidates",
                params={"chat_id": st.session_state.chat_id},
            )
            if data is not None:
                if not data:
                    st.caption("No candidates for this chat.")
                for row in data:
                    with st.container():
                        st.markdown(f"**{row.get('memory_type', '')}** · `{row.get('target_layer', '')}`")
                        st.write(row.get("normalized_memory", ""))
                        st.caption(
                            f"id `{row.get('id')}` · {row.get('status')} · "
                            f"source {row.get('source')} · conf {row.get('confidence')}"
                        )
                        if row.get("status") == "candidate":
                            st.caption("Confirm/reject this candidate via chat text (no buttons).")


if __name__ == "__main__":
    main()
