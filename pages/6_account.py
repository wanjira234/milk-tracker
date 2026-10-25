"""Your login: set an email and password so you can log in without waiting for an SMS."""
import streamlit as st

from src.messages import ICON

from src import accounts, db
from src.auth import require_login
from src.ui import cap

st.set_page_config(page_title="My account", page_icon=ICON, layout="centered")
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
    email = st.text_input("Email", value=row["email"] or "", key="acct_email", autocomplete="username")
    new = st.text_input("New password (at least 8 characters)", type="password", key="acct_new", autocomplete="new-password")
    again = st.text_input("New password again", type="password", key="acct_again", autocomplete="new-password")
    if st.form_submit_button("Save", type="primary"):
        try:
            if new != again:
                raise ValueError("the two passwords are not the same")
            accounts.set_password(user["id"], new, email=email)
            st.success("Saved. You can now log in with your email and password.")
        except ValueError as e:
            st.error(cap(e))

st.subheader("Two-factor login (extra protection)")
if not row["email"] or not db.get_user(user["id"]):
    st.caption("Set an email and password above first.")
elif accounts.totp_required(user["id"]):
    st.success("Two-factor login is ON. After your password you also type a 6-digit code from your authenticator app.")
    with st.form("totp_off", clear_on_submit=True):
        code = st.text_input("To turn it off, type a current code", key="totp_off_code", max_chars=7, autocomplete="one-time-code")
        if st.form_submit_button("Turn off two-factor"):
            if accounts.disable_totp(user["id"], code):
                st.success("Two-factor login is off.")
                st.rerun()
            else:
                st.error("That code didn't work.")
else:
    st.write("Add a second step to your login: even if someone learns your password, they also need your phone. "
             "Use any authenticator app (Google Authenticator, Microsoft Authenticator, Authy).")
    if st.button("Set up two-factor", key="totp_begin"):
        accounts.begin_totp_setup(user["id"])
        st.rerun()
    pending = db.get_totp(user["id"])
    if pending and pending["secret"] and not pending["enabled"]:
        from src import totp

        link = totp.uri(pending["secret"], row["email"])
        try:
            import segno

            st.markdown(f'<img alt="QR code to scan with your authenticator app" src="{segno.make(link).svg_data_uri(scale=5, dark="#1B2B22")}" '
                        'style="width:12rem;background:#fff;padding:.5rem;border-radius:12px">', unsafe_allow_html=True)
        except ImportError:
            pass
        st.write("Scan the picture, or choose *enter a setup key* in the app and type this key:")
        st.code(pending["secret"])
        with st.form("totp_on", clear_on_submit=True):
            code = st.text_input("Then type the 6-digit code the app shows", key="totp_on_code", max_chars=7, autocomplete="one-time-code")
            if st.form_submit_button("Turn on two-factor", type="primary"):
                if accounts.confirm_totp_setup(user["id"], code):
                    st.success("Two-factor login is on.")
                    st.rerun()
                else:
                    st.error("That code didn't work. Check the key and your phone's clock, then try again.")

st.header("Delete my account")
if user["role"] == "farmer":
    st.warning("This permanently deletes your login, your farm and every record on it: milk, feed, cows, requests. It cannot be undone.")
elif user["role"] == "vet":
    st.warning("This permanently deletes your login and your semen list. Your route is left without a vet until the admin allocates one.")
else:
    st.warning("This permanently deletes your admin login. You cannot delete the only admin.")
with st.form("delete_me"):
    confirm = st.text_input("Type DELETE to confirm", key="delete_me_confirm")
    if st.form_submit_button("Delete my account"):
        try:
            accounts.delete_own_account(user, confirm)
        except ValueError as e:
            st.error(cap(e))
        else:
            st.session_state.clear()
            st.session_state["account_deleted"] = True
            st.rerun()
