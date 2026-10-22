"""Small Streamlit helpers shared by app.py and the pages."""
import streamlit as st

from src import db


def farmer_selector():
    """Sidebar farmer picker, limited to the farms this login may see (a farmer: only their own,
    without a picker). Returns the selected farmer id, or stops the page if there are none."""
    from src import accounts

    user = st.session_state.get("user")
    if not user:  # a page that forgot require_login() must show nothing, not everything
        st.stop()
    farmers = accounts.visible_farmers(user)
    if not farmers:
        st.info(
            "No farmers yet. Add one on the home page first." if user["role"] == "admin"
            else "No farm is linked to your login yet. Ask your admin."
        )
        st.stop()
    if user["role"] == "farmer":
        st.session_state["farmer_id"] = farmers[0]["id"]
        return farmers[0]["id"]
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
