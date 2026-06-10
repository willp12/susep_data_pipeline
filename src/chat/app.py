"""Streamlit UI for the analyst chat.

    make chat-ui        # = uv run streamlit run src/chat/app.py

Same prerequisites as the CLI (bucket populated, GCP ADC creds, and either
ANTHROPIC_API_KEY or AGENT_PROVIDER=local with LM Studio serving a model).
The conversation lives in a ChatBridge stored in st.session_state — one
session per browser tab; "Nova conversa" resets it.
"""

from __future__ import annotations

import streamlit as st

from src.chat.bridge import ChatBridge

st.set_page_config(page_title="Chat SUSEP SES", page_icon="📊", layout="wide")


def _bridge() -> ChatBridge:
    if "bridge" not in st.session_state:
        with st.spinner("Conectando ao agente…"):
            bridge = ChatBridge()
            bridge.start()
        st.session_state["bridge"] = bridge
        st.session_state["messages"] = []
    return st.session_state["bridge"]  # type: ignore[no-any-return]


bridge = _bridge()

# -- sidebar ------------------------------------------------------------------

with st.sidebar:
    st.title("📊 Chat SUSEP SES")
    st.caption(f"provider: `{bridge.provider}` · modelo: `{bridge.model}`")

    if st.button("🔄 Nova conversa", use_container_width=True):
        with st.spinner("Reiniciando sessão…"):
            bridge.restart()
        st.session_state["messages"] = []
        st.rerun()

    if bridge.provider == "anthropic":
        st.metric("Custo da sessão", f"US$ {bridge.total_cost_usd:.4f}")

    st.divider()
    st.subheader("Reports publicados")
    st.caption("Clique em **Explorar** pra puxar um report pra conversa.")
    for entry in bridge.manifest_entries:
        stem = entry["stem"]
        with st.expander(stem):
            for title in entry.get("titles") or []:
                st.markdown(f"- {title}")
            if st.button("Explorar", key=f"explore-{stem}"):
                st.session_state["queued_prompt"] = (
                    f"Leia o report {stem} e me dê um resumo dos achados, "
                    "apontando o que vale aprofundar."
                )

# -- conversation -------------------------------------------------------------

for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        for tool in message.get("tools", []):
            st.caption(f"⚙ {tool}")
        st.markdown(message["content"])

prompt = st.chat_input("Pergunte sobre o mercado segurador…")
prompt = prompt or st.session_state.pop("queued_prompt", None)

if prompt:
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        tool_area = st.container()
        body = st.empty()
        chunks: list[str] = []
        tools: list[str] = []
        error = False
        with st.spinner("Analisando…"):
            for event in bridge.ask(prompt):
                if event.kind == "text":
                    chunks.append(event.text)
                    body.markdown("\n\n".join(chunks))
                elif event.kind == "tool":
                    tools.append(event.text)
                    tool_area.caption(f"⚙ {event.text}")
                elif event.kind == "result" and event.data:
                    error = bool(event.data.get("is_error"))
        if error:
            st.warning("A resposta terminou com erro — veja o conteúdo acima.")

    st.session_state["messages"].append(
        {"role": "assistant", "content": "\n\n".join(chunks), "tools": tools}
    )
    # Refresh sidebar widgets (session cost) without re-asking anything.
    st.rerun()
