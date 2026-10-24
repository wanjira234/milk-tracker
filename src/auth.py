"""Login in front of every page, and who the logged-in person is.

Three ways in, all ending in `st.session_state["user"]`:
  - SMS code (farmers, vets and admin with a phone number on file),
  - email + password,
  - the shared owner password APP_PASSWORD, which acts as admin. It keeps the app usable before any
    account exists and lets the owner create the first ones.
Roles: admin sees everything, a vet sees the farms on their routes, a farmer sees their own farm.

With neither APP_PASSWORD nor ADMIN_PHONE set the app stays LOCKED rather than open, so a
forgotten setting can't expose farmers' records. A login screen never touches the database
until someone actually submits it.

Every page calls `require_login()` straight after `st.set_page_config`, because a visitor can
open any page's address directly and skip the home page.
"""
import hmac
import os
import time

import streamlit as st

from src.messages import APP_NAME

MAX_WRONG = 5  # wrong guesses allowed per browser session before it locks until reload

OWNER_USER = {"id": None, "role": "admin", "name": "Owner", "farmer_id": None, "must_change_password": False}


def configured_password():
    """The owner password, from APP_PASSWORD in the environment or in Streamlit secrets; '' if unset."""
    value = os.environ.get("APP_PASSWORD", "")
    if not value:
        try:
            value = str(st.secrets.get("APP_PASSWORD", ""))
        except Exception:  # no secrets file: normal on a laptop
            value = ""
    return value


def configure_admin_phone():
    """Make ADMIN_PHONE from Streamlit secrets visible to src.accounts, which reads the environment."""
    if not os.environ.get("ADMIN_PHONE"):
        try:
            value = str(st.secrets.get("ADMIN_PHONE", ""))
        except Exception:
            value = ""
        if value:
            os.environ["ADMIN_PHONE"] = value


def password_ok(entered, expected):
    """True only for a non-empty expected password that matches exactly (constant-time compare)."""
    if not expected or not entered:
        return False
    return hmac.compare_digest(entered.encode(), expected.encode())


# Before login there is nothing to navigate to, so the page menu is hidden: a visitor sees only the
# sign-in box. (Tidiness only: every page still refuses a visitor who is not logged in.)
LOGGED_OUT_CSS = (
    "<style>"
    '[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"]'
    "{display:none}"
    ".block-container{max-width:520px;padding-top:4rem}"
    "</style>"
)
TAGLINE = "Know what your feed is worth."


def current_user():
    return st.session_state.get("user")


def _sms_sender(phone, text):
    from src import sms

    try:
        return bool(sms.send_sms(phone, text)["ok"])
    except Exception:  # a refused or failed SMS is reported to the person, never a traceback
        return False


def _too_many():
    return st.session_state.get("wrong_guesses", 0) >= MAX_WRONG


def _wrong():
    st.session_state["wrong_guesses"] = st.session_state.get("wrong_guesses", 0) + 1
    time.sleep(1)  # slows guessing


def _log_in(user):
    st.session_state["user"] = user
    st.session_state["wrong_guesses"] = 0
    st.session_state.pop("code_sent_to", None)
    st.rerun()


def _tab_sms():
    from src import accounts

    st.caption("We text a 6-digit code to your phone.")
    with st.form("sms_login"):
        phone = st.text_input("Phone number", placeholder="0712 345 678", key="sms_phone")
        entered = st.text_input("Code (after you get it)", key="sms_code", max_chars=8)
        c1, c2 = st.columns(2)
        ask = c1.form_submit_button("Send me a code")
        go = c2.form_submit_button("Log in", type="primary")
    if ask:
        try:
            r = accounts.request_code(phone, _sms_sender)
        except ValueError as e:
            st.error(str(e)[:1].upper() + str(e)[1:] + ".")
        else:
            (st.success if r["status"] == "sent" else st.error)(r["message"])
    if go:
        user = accounts.verify_code(phone, entered)
        if user:
            _log_in(accounts.session_user(user))
        _wrong()
        st.error("That code didn't work. It may have expired: ask for a new one.")


def _tab_email():
    from src import accounts

    with st.form("email_login"):
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        go = st.form_submit_button("Log in", type="primary")
    if go:
        try:
            user = accounts.login_password(email, password)
        except accounts.PendingApproval:
            st.info("Your signup is waiting for an admin to approve it. Try again later.")
            return
        if user:
            _log_in(accounts.session_user(user))
        _wrong()
        st.error(accounts.locked_message(email) or "Wrong email or password.")


def _tab_signup():
    from src import accounts

    st.caption("Sign up here. An admin must approve you before you can log in.")
    with st.form("signup", clear_on_submit=True):
        role = st.radio("I am a", ["farmer", "vet"], horizontal=True, key="su_role")
        name = st.text_input("Your name", key="su_name")
        phone = st.text_input("Phone (needed for farmers)", placeholder="0712 345 678", key="su_phone")
        farm = st.text_input("Farm name (farmers)", key="su_farm")
        email = st.text_input("Email", key="su_email")
        pw = st.text_input("Choose a password (at least 8 characters)", type="password", key="su_pw")
        if st.form_submit_button("Sign up", type="primary"):
            try:
                accounts.signup(role, name, email, pw, phone or None, farm or None)
            except ValueError as e:
                st.error(str(e)[:1].upper() + str(e)[1:] + ".")
            else:
                st.success("Thank you. An admin will approve your signup. Then log in with your email and password.")


def _tab_owner(expected):
    with st.form("owner_login"):
        entered = st.text_input("Owner password", type="password", key="owner_password")
        if st.form_submit_button("Log in", type="primary"):
            if password_ok(entered, expected):
                _log_in(dict(OWNER_USER))
            _wrong()
            st.error("Wrong password.")


def _force_password_change(user):
    from src import accounts

    st.title("Choose your own password")
    st.write("You are using a temporary password. Choose one only you know.")
    with st.form("change_password"):
        email = st.text_input("Your email (you will log in with this)", key="cp_email")
        new = st.text_input("New password (at least 8 characters)", type="password", key="cp_new")
        again = st.text_input("New password again", type="password", key="cp_again")
        if st.form_submit_button("Save password", type="primary"):
            try:
                if new != again:
                    raise ValueError("the two passwords are not the same")
                accounts.set_password(user["id"], new, email=email or None)
            except ValueError as e:
                st.error(str(e)[:1].upper() + str(e)[1:] + ".")
            else:
                st.session_state["user"] = {**user, "must_change_password": False}
                st.rerun()
    st.stop()


# Each role gets its own sidebar menu. Streamlit's built-in page list is replaced because it folds
# everything after the tenth page behind "View more", which would hide Alerts and Vaccination.
# This is tidiness, not security: every page still checks the role itself (require_login(roles=...))
# and the data is filtered by role.
_COMMON = [("pages/11_alerts.py", "Alerts"), ("pages/12_vaccination.py", "Vaccination")]
_FARM_DATA = [("pages/1_dashboard.py", "Dashboard"), ("pages/2_feed_log.py", "Feed log"), ("pages/3_budget.py", "Budget"),
              ("pages/4_farm_setup.py", "Farm setup"), ("pages/5_cows.py", "Cows")]
_ACCOUNT = [("pages/6_account.py", "Account")]
MENU = {
    "farmer": [("app.py", "Home"), ("pages/9_ask_the_vet.py", "Ask the vet")] + _COMMON + _FARM_DATA + _ACCOUNT,
    "vet": [("app.py", "Home"), ("pages/8_my_day.py", "My day")] + _COMMON
           + [("pages/1_dashboard.py", "Dashboard"), ("pages/5_cows.py", "Cows")] + _ACCOUNT,
    # The admin runs the business and sees no farm-data pages: to see a farmer's view, log in as that farmer.
    "admin": [("app.py", "Home"), ("pages/7_admin.py", "Admin"), ("pages/10_attendance.py", "Attendance")] + _COMMON
             + _ACCOUNT,
}
HIDE_BUILT_IN_NAV_CSS = '<style>[data-testid="stSidebarNav"]{display:none}</style>'


def menu_for(role):
    """[(page file, label)] for a role; empty for an unknown role."""
    return MENU.get(role, [])


def render_menu(role):
    """Show this role's menu in the sidebar, and hide Streamlit's built-in list only if ours rendered."""
    shown = 0
    for path, label in menu_for(role):
        try:
            st.sidebar.page_link(path, label=label)
            shown += 1
        except Exception:  # a page run on its own (as in tests) has no page registry to link into
            pass
    if shown:
        st.markdown(HIDE_BUILT_IN_NAV_CSS, unsafe_allow_html=True)


def require_login(roles=None):
    """Show the login screen and stop the page until someone is logged in; returns the user.

    `roles`: if given, only these roles may see the page (others are told so and stopped).
    """
    configure_admin_phone()
    owner_pw = configured_password()
    if not owner_pw and not os.environ.get("ADMIN_PHONE") and not st.session_state.get("user"):
        st.error("This app is locked: no password has been set. Set APP_PASSWORD (see README).")
        st.stop()
    user = current_user()
    if not user:
        st.markdown(LOGGED_OUT_CSS, unsafe_allow_html=True)
        st.title(APP_NAME)
        st.caption(TAGLINE)
        if _too_many():
            st.error("Too many wrong tries. Reload the page to try again.")
            st.stop()
        names = ["SMS code", "Email & password", "Sign up"] + (["Owner password"] if owner_pw else [])
        for tab, name in zip(st.tabs(names), names):
            with tab:
                {"SMS code": _tab_sms, "Email & password": _tab_email, "Sign up": _tab_signup}.get(name, lambda: _tab_owner(owner_pw))()
        st.stop()
    if user.get("must_change_password"):
        _force_password_change(user)
    render_menu(user["role"])
    st.sidebar.caption(f"Signed in: {user['name']} ({user['role']})")
    if st.sidebar.button("Log out"):
        st.session_state.clear()
        st.rerun()
    if roles and user["role"] not in roles:
        st.error("This page is not available for your account.")
        st.stop()
    return user
