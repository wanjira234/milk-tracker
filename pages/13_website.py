"""The public website (Home, How it works, About us, Contact us) for someone who is logged in, so they never have to log out to read it."""
import streamlit as st

from src.messages import ICON

st.set_page_config(page_title="Maziwa Plus", page_icon=ICON, layout="centered")

from src import public_site  # noqa: E402
from src.auth import LOGGED_OUT_CSS, loader_css, require_login  # noqa: E402

require_login()  # a visitor who is not logged in gets the login page, like every other page

st.markdown(LOGGED_OUT_CSS, unsafe_allow_html=True)
st.markdown(loader_css(), unsafe_allow_html=True)
public_site.render_header()
public_site.render_home()
