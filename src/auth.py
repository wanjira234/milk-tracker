"""A password screen in front of every page.

The password is APP_PASSWORD, read from the environment (.env on a laptop) or from
Streamlit's secrets (when hosted). It is never in the code. With no password set the app
stays LOCKED rather than open, so forgetting the setting can't expose farmers' records.

Every page calls `require_login()` straight after `st.set_page_config`, because a visitor
can open any page's address directly and skip the home page.
"""
import hmac
import os
import time

import streamlit as st

MAX_WRONG = 5  # wrong guesses allowed per browser session before it locks until reload


def configured_password():
    """The password, from APP_PASSWORD in the environment or in Streamlit secrets; '' if unset."""
    value = os.environ.get("APP_PASSWORD", "")
    if not value:
        try:
            value = str(st.secrets.get("APP_PASSWORD", ""))
        except Exception:  # no secrets file: normal on a laptop
            value = ""
    return value


def password_ok(entered, expected):
    """True only for a non-empty expected password that matches exactly (constant-time compare)."""
    if not expected or not entered:
        return False
    return hmac.compare_digest(entered.encode(), expected.encode())


def require_login():
    """Show the password screen and stop the page until the right password is entered."""
    expected = configured_password()
    if not expected:
        st.error("This app is locked: no password has been set. Set APP_PASSWORD (see README).")
        st.stop()
    if st.session_state.get("logged_in"):
        if st.sidebar.button("Log out"):
            st.session_state.clear()
            st.rerun()
        return
    st.title("Milk Tracker")
    wrong = st.session_state.get("wrong_guesses", 0)
    if wrong >= MAX_WRONG:
        st.error("Too many wrong tries. Reload the page to try again.")
        st.stop()
    with st.form("login"):
        entered = st.text_input("Password", type="password")
        if st.form_submit_button("Log in", type="primary"):
            if password_ok(entered, expected):
                st.session_state["logged_in"] = True
                st.session_state["wrong_guesses"] = 0
                st.rerun()
            st.session_state["wrong_guesses"] = wrong + 1
            time.sleep(1)  # slows guessing
            st.error("Wrong password.")
    st.stop()
