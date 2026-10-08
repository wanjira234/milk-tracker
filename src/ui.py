"""Small Streamlit helpers shared by app.py and the pages."""
import streamlit as st

from src import db


def farmer_selector():
    """Sidebar farmer picker. Returns the selected farmer id, or stops the page if none exist."""
    farmers = db.list_farmers()
    if not farmers:
        st.info("No farmers yet. Add one on the home page first.")
        st.stop()
    labels = {f["id"]: f"{f['name']} ({f['farm_name'] or f['phone']})" for f in farmers}
    ids = list(labels)
    current = st.session_state.get("farmer_id")
    index = ids.index(current) if current in ids else 0
    farmer_id = st.sidebar.selectbox("Farmer", ids, index=index, format_func=labels.get)
    st.session_state["farmer_id"] = farmer_id
    return farmer_id


def cap(message):
    """Uppercase the first letter only (str.capitalize() would lowercase 'Kenyan')."""
    message = str(message)
    return message[:1].upper() + message[1:]
