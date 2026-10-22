"""Your login: set an email and password so you can log in without waiting for an SMS."""
import streamlit as st

from src import accounts, db
from src.auth import require_login
from src.ui import cap

st.set_page_config(page_title="My account", page_icon="🥛", layout="centered")
user = require_login()

st.title("My account")
st.write(f"**{user['name']}** · {user['role']}")

if user["id"] is None:
    st.info("You are signed in with the owner password. Create an admin login on the **admin** page to get your own email and password.")
    st.stop()

row = db.get_user(user["id"])
st.write(f"Phone: {row['phone'] or 'not set'}  \nEmail: {row['email'] or 'not set'}")
st.subheader("Email and password login")
with st.form("set_password", clear_on_submit=True):
    email = st.text_input("Email", value=row["email"] or "", key="acct_email")
    new = st.text_input("New password (at least 8 characters)", type="password", key="acct_new")
    again = st.text_input("New password again", type="password", key="acct_again")
    if st.form_submit_button("Save", type="primary"):
        try:
            if new != again:
                raise ValueError("the two passwords are not the same")
            accounts.set_password(user["id"], new, email=email)
            st.success("Saved. You can now log in with your email and password.")
        except ValueError as e:
            st.error(cap(e))
