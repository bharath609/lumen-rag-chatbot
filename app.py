"""Streamlit UI.  Run:  streamlit run app.py"""
import streamlit as st

from src.chunking import chunk_pages
from src.config import settings
from src.loaders import load_file
from src.rag import answer
from src.vectorstore import VectorStore

st.set_page_config(page_title="RAG Document Chatbot", page_icon="📚")
st.title("📚 Chat with your documents")


@st.cache_resource(show_spinner="Loading embedding model...")
def get_store() -> VectorStore:
    return VectorStore(settings.persist_dir, settings.collection, settings.embedding_model)


store = get_store()

with st.sidebar:
    st.header("Documents")
    uploads = st.file_uploader("Upload PDF / TXT / MD", type=["pdf", "txt", "md"],
                               accept_multiple_files=True)
    if st.button("Index uploaded files", disabled=not uploads):
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        for up in uploads:
            path = settings.upload_dir / up.name
            path.write_bytes(up.getbuffer())
            n = store.add(chunk_pages(load_file(path), settings.chunk_size, settings.chunk_overlap))
            st.success(f"{up.name}: {n} chunks indexed")
    st.caption("Indexed: " + (", ".join(store.sources()) or "nothing yet"))
    if st.button("Clear all documents"):
        store.reset()
        st.session_state.pop("messages", None)
        st.rerun()
    st.caption(f"LLM: {settings.llm_provider} / {settings.llm_model}")

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        for i, src in enumerate(m.get("sources", []), start=1):
            with st.expander(f"[{i}] {src['source']}" + (f" p.{src['page']}" if src["page"] else "")
                             + f"  (match {src['score']:.2f})"):
                st.write(src["text"])

if q := st.chat_input("Ask a question about your documents"):
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    st.session_state.messages.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Thinking..."):
                result = answer(q, store, settings, history)
            st.markdown(result["answer"])
            st.session_state.messages.append(
                {"role": "assistant", "content": result["answer"], "sources": result["sources"]}
            )
        except Exception as e:  # e.g. Ollama not running
            st.error(f"Could not get an answer: {e}")
