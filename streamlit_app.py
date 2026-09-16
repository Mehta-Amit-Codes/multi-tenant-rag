"""
Streamlit front-end for the Multi-Tenant RAG-as-a-Service API.

This is a thin client -- all isolation/auth/rate-limiting logic lives in
the FastAPI backend. The UI just exercises the API as a real tenant would,
and doubles as a demo you can screen-record for a portfolio.

Run:
    streamlit run streamlit_app.py

Requires the API running (see README) at API_BASE_URL.
"""
import os

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Multi-Tenant RAG", page_icon="🗂️", layout="wide")


# ---------------------------------------------------------------- session --
def _init_state():
    st.session_state.setdefault("api_key", "")
    st.session_state.setdefault("tenant_id", "")
    st.session_state.setdefault("tenant_name", "")
    st.session_state.setdefault("last_onboard_key", "")  # shown once, then cleared


_init_state()


def api_headers() -> dict:
    return {"X-API-Key": st.session_state["api_key"]}


# ------------------------------------------------------------------ sidebar --
with st.sidebar:
    st.title("🗂️ Multi-Tenant RAG")
    st.caption(f"API: {API_BASE_URL}")

    st.subheader("Session")
    if st.session_state["api_key"]:
        st.success(f"Authenticated as **{st.session_state['tenant_name'] or 'tenant'}**")
        st.code(st.session_state["tenant_id"], language=None)
        if st.button("Log out"):
            st.session_state["api_key"] = ""
            st.session_state["tenant_id"] = ""
            st.session_state["tenant_name"] = ""
            st.rerun()
    else:
        st.info("Not authenticated. Onboard a new tenant or paste an existing API key below.")
        pasted_key = st.text_input("Existing API key", type="password")
        if st.button("Use this key") and pasted_key:
            st.session_state["api_key"] = pasted_key
            st.rerun()


# -------------------------------------------------------------------- tabs --
tab_onboard, tab_ingest, tab_query, tab_usage = st.tabs(
    ["🆕 Onboard Tenant", "📄 Ingest Documents", "💬 Query", "📊 Usage"]
)

# ---- Onboard -----------------------------------------------------------
with tab_onboard:
    st.header("Provision a new tenant")
    st.write(
        "Each tenant gets an isolated document namespace (via Postgres RLS), "
        "its own embedding config, and a unique API key issued once."
    )

    with st.form("onboard_form"):
        name = st.text_input("Organization name", placeholder="Acme Corp")
        col1, col2, col3 = st.columns(3)
        with col1:
            embedding_model = st.selectbox("Embedding model", ["all-MiniLM-L6-v2"])
        with col2:
            chunk_size = st.number_input("Chunk size (words)", value=500, min_value=50, step=50)
        with col3:
            chunk_overlap = st.number_input("Chunk overlap", value=50, min_value=0, step=10)

        submitted = st.form_submit_button("Create tenant", type="primary")

    if submitted and name:
        resp = requests.post(
            f"{API_BASE_URL}/tenants",
            json={
                "name": name,
                "embedding_model": embedding_model,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            },
        )
        if resp.ok:
            data = resp.json()
            st.session_state["last_onboard_key"] = data["api_key"]
            st.session_state["api_key"] = data["api_key"]
            st.session_state["tenant_id"] = data["tenant_id"]
            st.session_state["tenant_name"] = name
            st.success("Tenant created — you are now logged in as this tenant.")
        else:
            st.error(f"Failed: {resp.status_code} {resp.text}")

    if st.session_state["last_onboard_key"]:
        st.warning(
            "⚠️ Save this API key now — it will not be shown again "
            "(only its hash is stored server-side)."
        )
        st.code(st.session_state["last_onboard_key"], language=None)

# ---- Ingest --------------------------------------------------------------
with tab_ingest:
    st.header("Ingest a document")
    if not st.session_state["api_key"]:
        st.info("Authenticate first (sidebar or Onboard tab).")
    else:
        filename = st.text_input("Filename", placeholder="handbook.txt")
        text = st.text_area("Document text", height=250,
                             placeholder="Paste the document content to embed...")

        if st.button("Ingest", type="primary") and filename and text:
            with st.spinner("Chunking + embedding..."):
                resp = requests.post(
                    f"{API_BASE_URL}/documents",
                    headers=api_headers(),
                    json={"filename": filename, "text": text},
                )
            if resp.ok:
                data = resp.json()
                status_emoji = {"created": "✅", "updated": "🔄", "unchanged": "⏭️"}
                st.success(
                    f"{status_emoji.get(data['status'], '')} **{data['status']}** — "
                    f"{data['chunks_embedded']} chunk(s) embedded "
                    f"(document_id: `{data['document_id']}`)"
                )
                if data["status"] == "unchanged":
                    st.caption(
                        "Content hash matched an existing document — nothing was "
                        "re-embedded. Try editing the text and re-ingesting to see "
                        "an incremental update instead."
                    )
            else:
                st.error(f"Failed: {resp.status_code} {resp.text}")

        st.divider()
        st.subheader("Delete a document")
        doc_id = st.text_input("Document ID to delete")
        if st.button("Delete", type="secondary") and doc_id:
            resp = requests.delete(f"{API_BASE_URL}/documents/{doc_id}", headers=api_headers())
            if resp.status_code == 204:
                st.success("Deleted.")
            else:
                st.error(f"Failed: {resp.status_code} {resp.text}")

# ---- Query -----------------------------------------------------------
with tab_query:
    st.header("Ask a question")
    if not st.session_state["api_key"]:
        st.info("Authenticate first (sidebar or Onboard tab).")
    else:
        question = st.text_input("Question", placeholder="What is the refund policy?")
        top_k = st.slider("Chunks to retrieve (top_k)", 1, 10, 5)

        if st.button("Ask", type="primary") and question:
            with st.spinner("Retrieving + generating..."):
                resp = requests.post(
                    f"{API_BASE_URL}/query",
                    headers=api_headers(),
                    json={"question": question, "top_k": top_k},
                )
            if resp.ok:
                data = resp.json()
                st.markdown("### Answer")
                st.write(data["answer"])
                st.caption(f"Latency: {data['latency_ms']} ms")

                with st.expander(f"📚 Sources ({len(data['sources'])} chunks retrieved)"):
                    for s in data["sources"]:
                        st.markdown(f"**[{s['chunk_index']}]** _{s['document_id']}_")
                        st.text(s["text"])
                        st.divider()
            elif resp.status_code == 429:
                st.warning("Rate limit hit — this tenant's request bucket is empty. Wait a moment.")
            else:
                st.error(f"Failed: {resp.status_code} {resp.text}")

# ---- Usage -----------------------------------------------------------
with tab_usage:
    st.header("Usage & metering")
    if not st.session_state["api_key"]:
        st.info("Authenticate first (sidebar or Onboard tab).")
    else:
        window_days = st.slider("Window (days)", 1, 90, 30)
        if st.button("Refresh usage") or True:
            resp = requests.get(
                f"{API_BASE_URL}/usage",
                headers=api_headers(),
                params={"window_days": window_days},
            )
            if resp.ok:
                data = resp.json()
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Queries", data["total_queries"])
                col2.metric("Ingests", data["total_ingests"])
                col3.metric("Tokens in / out", f"{data['tokens_in']} / {data['tokens_out']}")
                col4.metric("Avg latency", f"{data['avg_query_latency_ms']:.0f} ms")

                col5, col6 = st.columns(2)
                col5.metric("Chunks stored", data["chunk_count"])
                col6.metric("Documents stored", data["document_count"])
            else:
                st.error(f"Failed: {resp.status_code} {resp.text}")
