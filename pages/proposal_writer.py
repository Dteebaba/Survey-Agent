import streamlit as st
import streamlit.components.v1 as components
from auth import check_access

st.set_page_config(
    page_title="Survey Agent | Proposal Assistant",
    page_icon="🧾",
    layout="wide"
)

check_access()

st.markdown("<div class='app-shell'>", unsafe_allow_html=True)
st.markdown("<div class='app-title'>🧾 Proposal & Writer Assistant</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='app-subtitle'>Use your custom GPT to draft proposals and responses based on the exported Excel/CSV.</div>",
    unsafe_allow_html=True,
)

st.markdown("<div class='app-card'>", unsafe_allow_html=True)
st.write(
    "You can upload the filtered Excel/CSV you downloaded from the Document Assistant directly into the embedded GPT below."
)

# Embed your custom GPT (note: embedding might depend on OpenAI / browser policies)
components.iframe(
    "https://chatgpt.com/g/g-6926512d2a5c8191b7260d3fe8d2b5d9-sam-excel-solicitation-analyzer",
    height=800,
    scrolling=True,
)
st.markdown("</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)
