"""
Local chat UI for Jeeves: normalized-request review via explicit actions (no free-text review).
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


def _request(method: str, path: str, *, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    url = f"{API_BASE}{path}"
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.request(method, url, params=params, **kwargs)
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
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("last_state", None)
    st.session_state.setdefault("user_id", "local-ui-user")
    st.session_state.setdefault("chat_id", None)
    st.session_state.setdefault("ui_mode", "normal")


def _append_assistant_turn(state: dict[str, Any]) -> None:
    for line in state.get("assistant_messages") or []:
        st.session_state.messages.append(("assistant", line))


def _fetch_memory_candidates(chat_id: str) -> list[dict[str, Any]]:
    data = _request("GET", "/memory/candidates", params={"chat_id": chat_id})
    return data if isinstance(data, list) else []


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
        if st.button("Закрыть чат", disabled=not st.session_state.chat_id):
            data = _request("POST", "/chat/close", json={"chat_id": st.session_state.chat_id})
            if data:
                st.session_state.last_state = data["state"]
                _append_assistant_turn(data["state"])
                st.session_state.ui_mode = "normal"
                st.rerun()

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

        prompt = st.chat_input("Message", key="chat_in_single_flow")
        if prompt:
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
                    st.session_state.messages.append(("user", prompt))
                    st.session_state.last_state = out0["state"]
                    _append_assistant_turn(out0["state"])
                    st.rerun()
            else:
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
        return
        # --- OVERRIDE: single-input chat flow only ---
        nr = state.get("normalized_request")
        if nr:
            with st.expander("Normalized request (read-only)", expanded=False):
                st.json(nr)
        prompt = st.chat_input("Message", key="chat_in_single_flow")
        if prompt:
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
                    st.session_state.messages = [("user", prompt)]
                    st.session_state.last_state = out0["state"]
                    _append_assistant_turn(out0["state"])
                    st.rerun()
            else:
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
        return
        nr = state.get("normalized_request")
        awaiting_fb = bool(state.get("awaiting_user_feedback"))
        closed = bool(state.get("chat_closed"))
        candidates = _fetch_memory_candidates(st.session_state.chat_id) if st.session_state.chat_id else []

        if nr:
            with st.expander("Normalized request", expanded=False):
                st.json(nr)

        if closed:
            st.info("Чат закрыт.")
        else:
            review_mode = bool(st.session_state.chat_id) and awaiting_fb and not closed
            if review_mode:
                st.caption("Подтвердите или отклоните нормализованный запрос.")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Подтверждаю", type="primary", key="btn_confirm_review"):
                        out = _request("POST", "/chat/confirm", json={"chat_id": st.session_state.chat_id})
                        if out:
                            st.session_state.last_state = out["state"]
                            _append_assistant_turn(out["state"])
                            st.rerun()
                with c2:
                    if st.button("Не подтверждаю", key="btn_reject_review"):
                        out = _request(
                            "POST",
                            "/chat/reject_review",
                            json={"chat_id": st.session_state.chat_id},
                        )
                        if out:
                            st.session_state.last_state = out["state"]
                            _append_assistant_turn(out["state"])
                            st.rerun()
            elif candidates:
                st.warning("Есть pending memory candidates: свободный ввод отключён.")
                for candidate in candidates:
                    with st.container(border=True):
                        st.markdown(f"**{candidate.get('memory_type', '')}** · `{candidate.get('target_layer', '')}`")
                        st.write(candidate.get("normalized_memory", ""))
                        col1, col2 = st.columns(2)
                        if col1.button(f"Подтверждаю##{candidate['id']}", use_container_width=True):
                            data = _request(
                                "POST",
                                f"/memory/candidates/{candidate['id']}/confirm",
                                json={"user_id": st.session_state.user_id},
                            )
                            if data:
                                st.rerun()
                        if col2.button(f"Не подтверждаю##{candidate['id']}", use_container_width=True):
                            data = _request(
                                "POST",
                                f"/memory/candidates/{candidate['id']}/reject",
                                json={},
                            )
                            if data:
                                st.rerun()
            else:
                prompt = st.chat_input("Message", key="chat_in")
                if prompt:
                    if not st.session_state.chat_id:
                        out0 = _request(
                            "POST",
                            "/chat/turn",
                            json={"chat_id": None, "user_id": st.session_state.user_id, "user_message": prompt},
                        )
                        if out0:
                            st.session_state.chat_id = out0["chat_id"]
                            st.session_state.messages = [("user", prompt)]
                            st.session_state.last_state = out0["state"]
                            _append_assistant_turn(out0["state"])
                            st.rerun()
                    else:
                        st.session_state.messages.append(("user", prompt))
                        out = _request(
                            "POST",
                            "/chat/turn",
                            json={"chat_id": st.session_state.chat_id, "user_id": st.session_state.user_id, "user_message": prompt},
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
            data = _fetch_memory_candidates(st.session_state.chat_id)
            if not data:
                st.caption("No candidates for this chat.")
            for row in data:
                with st.container(border=True):
                    st.markdown(f"**{row.get('memory_type', '')}** · `{row.get('target_layer', '')}`")
                    st.write(row.get("normalized_memory", ""))
                    st.caption(
                        f"id `{row.get('id')}` · {row.get('status')} · "
                        f"source {row.get('source')} · conf {row.get('confidence')}"
                    )


if __name__ == "__main__":
    main()
