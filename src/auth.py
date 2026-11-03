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
from html import escape as html_escape
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
    "<style>@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@600&display=swap');"
    '[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"]'
    "{display:none}"
    ".block-container{max-width:1120px;padding-top:0;padding-bottom:0}"
    '[data-testid="stHeader"]{display:none}'
    # The page links live in our own top bar; hide only the outer tab strip (not the Email / SMS tabs inside Log in).
    '[data-testid="stTabs"]:not([data-testid="stTabs"] [data-testid="stTabs"]) > div > [role="tablist"]{display:none}'
    # Large touch targets and 16px text in the boxes (a smaller size makes phones zoom in on focus).
    "button[kind],[data-testid='stFormSubmitButton'] button{min-height:3rem}"
    "input{font-size:16px !important}"
    "</style>"
)

PEEK_COW = (
    '<div class="peek" aria-hidden="true"><svg viewBox="0 0 260 190" xmlns="http://www.w3.org/2000/svg">'
    "<defs>"
    '<radialGradient id="pk-face" cx="45%" cy="35%" r="70%"><stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#EFE3CB"/></radialGradient>'
    '<radialGradient id="pk-snout" cx="45%" cy="30%" r="75%"><stop offset="0" stop-color="#FFC9C0"/><stop offset="1" stop-color="#EE9C95"/></radialGradient>'
    '<linearGradient id="pk-ear" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#C9803C"/><stop offset="1" stop-color="#A9622A"/></linearGradient>'
    '<filter id="pk-sh" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="7" stdDeviation="6" flood-color="#000" flood-opacity=".28"/></filter>'
    "</defs>"
    # horns, ears
    '<path d="M86 50 C74 28 84 14 98 12 C92 24 96 36 104 46Z" fill="#F2C14E" filter="url(#pk-sh)"/>'
    '<path d="M174 50 C186 28 176 14 162 12 C168 24 164 36 156 46Z" fill="#F2C14E" filter="url(#pk-sh)"/>'
    '<ellipse cx="52" cy="78" rx="30" ry="17" transform="rotate(-18 52 78)" fill="url(#pk-ear)" filter="url(#pk-sh)"/>'
    '<ellipse cx="208" cy="78" rx="30" ry="17" transform="rotate(18 208 78)" fill="url(#pk-ear)" filter="url(#pk-sh)"/>'
    '<ellipse cx="54" cy="79" rx="17" ry="8" transform="rotate(-18 54 79)" fill="#F7B7A8"/>'
    '<ellipse cx="206" cy="79" rx="17" ry="8" transform="rotate(18 206 79)" fill="#F7B7A8"/>'
    # head
    '<ellipse cx="130" cy="98" rx="76" ry="68" fill="url(#pk-face)" filter="url(#pk-sh)"/>'
    '<path d="M70 70 C74 44 112 40 116 66 C118 86 84 98 70 70Z" fill="#7A4524" opacity=".92"/>'
    # eyes (blink)
    '<g class="pk-eyes"><ellipse cx="100" cy="92" rx="8" ry="10" fill="#26211C"/><ellipse cx="160" cy="92" rx="8" ry="10" fill="#26211C"/>'
    '<circle cx="103" cy="88" r="3" fill="#fff"/><circle cx="163" cy="88" r="3" fill="#fff"/></g>'
    '<ellipse cx="82" cy="116" rx="11" ry="7" fill="#FFB3A7" opacity=".6"/><ellipse cx="178" cy="116" rx="11" ry="7" fill="#FFB3A7" opacity=".6"/>'
    # muzzle, chewing
    '<g class="pk-chew"><ellipse cx="130" cy="130" rx="40" ry="28" fill="url(#pk-snout)"/>'
    '<ellipse cx="116" cy="124" rx="5" ry="6.5" fill="#B9625C"/><ellipse cx="144" cy="124" rx="5" ry="6.5" fill="#B9625C"/>'
    '<path d="M112 140 Q130 152 148 140" fill="none" stroke="#B9625C" stroke-width="3.5" stroke-linecap="round"/>'
    '<path class="pk-grass" d="M146 142 C168 134 182 138 196 128" fill="none" stroke="#5CBF7A" stroke-width="5" stroke-linecap="round"/>'
    '<path class="pk-grass" d="M146 144 C166 148 180 156 192 160" fill="none" stroke="#3E9E5E" stroke-width="4" stroke-linecap="round"/></g>'
    # hooves resting on the card
    '<g filter="url(#pk-sh)"><rect x="76" y="150" width="40" height="42" rx="18" fill="url(#pk-face)"/><rect x="76" y="176" width="40" height="16" rx="8" fill="#3B2A22"/>'
    '<rect x="144" y="150" width="40" height="42" rx="18" fill="url(#pk-face)"/><rect x="144" y="176" width="40" height="16" rx="8" fill="#3B2A22"/></g>'
    "</svg>"
    '<span class="pk-cloud c1"></span><span class="pk-cloud c2"></span>'
    '<span class="pk-flower"><i></i><i></i><i></i><i></i><i></i><b></b></span></div>'
)

CLAY_CSS = (
    "<style>"
    ".peek{position:relative;width:min(17rem,70vw);margin:2.2rem auto -2.6rem;z-index:3;pointer-events:none;animation:bob 6s ease-in-out infinite}"
    ".peek svg{width:100%;height:auto;display:block;overflow:visible}"
    ".pk-eyes{transform-origin:130px 92px;animation:blink 5s infinite}"
    ".pk-chew{transform-origin:130px 130px;animation:chew 1.1s ease-in-out infinite}"
    ".pk-grass{transform-origin:146px 142px;animation:wag 1.1s ease-in-out infinite}"
    "@keyframes blink{0%,92%,100%{transform:scaleY(1)}95%{transform:scaleY(.1)}}"
    "@keyframes chew{0%,100%{transform:translateY(0) scaleY(1)}50%{transform:translateY(3px) scaleY(.94)}}"
    "@keyframes wag{0%,100%{transform:rotate(0)}50%{transform:rotate(5deg)}}"
    "@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}"
    ".pk-cloud{position:absolute;height:1.5rem;width:4.6rem;border-radius:999px;background:rgba(255,255,255,.9);box-shadow:0 8px 18px rgba(0,0,0,.25);animation:bob 7s ease-in-out infinite}"
    ".pk-cloud:before{content:'';position:absolute;left:.7rem;top:-.8rem;width:2rem;height:2rem;border-radius:50%;background:inherit}"
    ".pk-cloud.c1{left:-5.2rem;top:2.2rem}.pk-cloud.c2{right:-5rem;top:.6rem;transform:scale(.7);animation-delay:-3s}"
    ".pk-flower{position:absolute;right:-3.6rem;bottom:.2rem;width:2.6rem;height:2.6rem;animation:bob 5s ease-in-out -1s infinite}"
    ".pk-flower i{position:absolute;width:1.05rem;height:1.05rem;border-radius:50%;background:radial-gradient(circle at 35% 30%,#FFD1DD,#F0709A);box-shadow:0 4px 8px rgba(0,0,0,.25)}"
    ".pk-flower i:nth-child(1){left:.8rem;top:0}.pk-flower i:nth-child(2){left:1.55rem;top:.7rem}.pk-flower i:nth-child(3){left:1.2rem;top:1.5rem}"
    ".pk-flower i:nth-child(4){left:.35rem;top:1.5rem}.pk-flower i:nth-child(5){left:0;top:.7rem}"
    ".pk-flower b{position:absolute;left:.8rem;top:.8rem;width:1rem;height:1rem;border-radius:50%;background:radial-gradient(circle at 35% 30%,#FFE79A,#F2A93B)}"
    # the card: soft, raised, clay-like
    "[class*='st-key-clay']{border:0 !important;border-radius:32px !important;background:linear-gradient(180deg,#FFFBF0,#F6EBD3) !important;"
    "box-shadow:0 34px 60px -12px rgba(0,0,0,.55),0 8px 0 #D8C7A0,inset 0 3px 0 rgba(255,255,255,.95),inset 0 -8px 16px rgba(160,130,70,.18) !important;padding:1.4rem 1.2rem .6rem !important}"
    "[class*='st-key-clay'] [data-testid='stFormSubmitButton'],[class*='st-key-clay'] [data-testid='stFormSubmitButton']>div{width:100%}"
    "[class*='st-key-clay'] [data-testid='stForm']{border:0 !important;padding:0 !important;background:transparent !important;box-shadow:none !important;border-radius:0 !important}"
    "[class*='st-key-clay'] [data-testid='stCaptionContainer'],[class*='st-key-clay'] [data-testid='stCaptionContainer'] *,[class*='st-key-clay'] [data-testid='stRadio'] label p{color:#4A5A4F !important}"
    "[class*='st-key-clay'] [data-testid='stFormSubmitButton'],[class*='st-key-clay'] [data-testid='stFormSubmitButton']>div,[class*='st-key-clay'] [data-testid='stFormSubmitButton'] button{width:100% !important;display:block}"
    "[class*='st-key-clay'] [data-testid='stTextInputRootElement']{border-radius:999px !important;background:#EFE6D2 !important;border:0 !important;"
    "box-shadow:inset 0 3px 7px rgba(120,95,45,.28) !important;overflow:hidden}"
    "[class*='st-key-clay'] [data-baseweb='input'],[class*='st-key-clay'] [data-baseweb='base-input'],[class*='st-key-clay'] input{background:transparent !important;border:0 !important;box-shadow:none !important}"
    "[class*='st-key-clay'] input{padding-left:1.1rem !important}"
    "[class*='st-key-clay'] [role='tab'],[class*='st-key-clay'] [role='tab'] *{color:#2B3A30 !important;font-weight:600}"
    "[class*='st-key-clay'] [role='tab'][aria-selected='true'],[class*='st-key-clay'] [role='tab'][aria-selected='true'] *{color:#1F6B3F !important}"
    "[class*='st-key-clay'] label p{color:#3A4A3F !important;font-weight:600}"
    "[class*='st-key-clay'] [data-testid='stFormSubmitButton'] button,[class*='st-key-clay'] .stButton button{border-radius:999px !important;min-height:3.1rem;width:100%;display:block;font-weight:700;border:0 !important;"
    "background:linear-gradient(180deg,#3E9E5E,#2A6F46) !important;color:#fff !important;box-shadow:0 7px 0 #164A2E,0 14px 22px rgba(22,74,46,.4);transition:transform .1s,box-shadow .1s}"
    "[class*='st-key-clay'] [data-testid='stFormSubmitButton'] button:active{transform:translateY(5px);box-shadow:0 2px 0 #164A2E,0 6px 12px rgba(22,74,46,.4)}"
    "[class*='st-key-clay_signup']{padding:2.6rem 1.2rem 1.6rem !important}"
    "[class*='st-key-clay'] [data-testid='stElementContainer']:has([data-testid='stFormSubmitButton']),[class*='st-key-clay'] div:has(>[data-testid='stFormSubmitButton']){width:100% !important}"
    "@media (prefers-reduced-motion:reduce){.peek,.pk-cloud,.pk-flower,.pk-eyes,.pk-chew,.pk-grass{animation:none !important}}"
    "@media (max-width:640px){.pk-cloud,.pk-flower{display:none}}"
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
        phone = st.text_input("Phone number", placeholder="0712 345 678", key="sms_phone", autocomplete="tel")
        entered = st.text_input("Code (after you get it)", key="sms_code", max_chars=8, autocomplete="one-time-code")
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
        email = st.text_input("Email", key="login_email", autocomplete="username")
        password = st.text_input("Password", type="password", key="login_password", autocomplete="current-password")
        go = st.form_submit_button("Log in", type="primary")
    if go:
        try:
            user = accounts.login_password(email, password)
        except accounts.PendingApproval:
            st.info("Your signup is waiting for an admin to approve it. Try again later.")
            return
        if user:
            if accounts.totp_required(user["id"]):
                st.session_state["pending_2fa"] = accounts.session_user(user)  # password right; the code is still to come
                st.rerun()
            _log_in(accounts.session_user(user))
        _wrong()
        st.error(accounts.locked_message(email) or "Wrong email or password.")


def _second_factor_screen(pending):
    """Password was right and this person uses two-factor: ask for the code from their authenticator app."""
    from src import accounts, public_site

    st.markdown(LOGGED_OUT_CSS, unsafe_allow_html=True)
    public_site.render_header()
    public_site.page_title("One more step", "Open your authenticator app and type the 6-digit code for Maziwa Plus.")
    with st.columns([1, 3, 1])[1], st.container(border=True):
        with st.form("second_factor"):
            code = st.text_input("6-digit code", max_chars=7, key="second_factor_code", autocomplete="one-time-code")
            go = st.form_submit_button("Verify", type="primary")
        if go:
            if accounts.verify_totp_login(pending["id"], code):
                st.session_state.pop("pending_2fa", None)
                _log_in(pending)
            _wrong()
            st.error(accounts.locked_message_for_id(pending["id"]) or "That code didn't work. Codes change every 30 seconds.")
        if st.button("Start again"):
            st.session_state.pop("pending_2fa", None)
            st.rerun()
    public_site.render_footer()
    st.stop()


def _tab_signup():
    from src import accounts

    st.caption("Three quick steps: sign up here, the milk buyer's admin approves you, then log in on the Email & password tab.")
    role = st.radio("I am a", ["farmer", "vet"], horizontal=True, key="su_role")  # outside the form so the fields change
    with st.form("signup", clear_on_submit=True):
        name = st.text_input("Your name", key="su_name", autocomplete="name")
        phone = farm = None
        if role == "farmer":
            phone = st.text_input("Phone", placeholder="0712 345 678", key="su_phone", help="Your SMS advice and alerts come to this number.")
            farm = st.text_input("Farm name (optional)", key="su_farm")
        email = st.text_input("Email", key="su_email", autocomplete="username")
        pw = st.text_input("Choose a password (at least 8 characters)", type="password", key="su_pw", autocomplete="new-password")
        if st.form_submit_button("Sign up", type="primary"):
            try:
                accounts.signup(role, name, email, pw, phone or None, farm or None)
            except ValueError as e:
                st.error(str(e)[:1].upper() + str(e)[1:] + ".")
            else:
                st.success(
                    "You are signed up. The admin has to approve you before you can log in. "
                    "Once approved, log in on the Email & password tab. "
                    + ("Your Home page will then guide you through setting up your farm." if role == "farmer"
                       else "Your My day page will show your route's visits.")
                )


def _tab_owner(expected):
    from src import accounts

    locked = accounts.owner_locked_message()
    if locked:
        st.error(locked)
        return
    with st.form("owner_login"):
        entered = st.text_input("Owner password", type="password", key="owner_password", autocomplete="current-password")
        if st.form_submit_button("Log in", type="primary"):
            if password_ok(entered, expected):
                accounts.owner_login_ok()
                _log_in(dict(OWNER_USER))
            accounts.owner_login_failed()
            _wrong()
            st.error("Wrong password.")


def _force_password_change(user):
    from src import accounts

    st.title("Choose your own password")
    st.write("You are using a temporary password. Choose one only you know.")
    with st.form("change_password"):
        email = st.text_input("Your email (you will log in with this)", key="cp_email", autocomplete="username")
        new = st.text_input("New password (at least 8 characters)", type="password", key="cp_new", autocomplete="new-password")
        again = st.text_input("New password again", type="password", key="cp_again", autocomplete="new-password")
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
_ACCOUNT = [("pages/13_website.py", "Website"), ("pages/6_account.py", "Account")]  # Website: the public Home / About / Contact pages
MENU = {
    # A route admin runs one or more routes: attendance and notices for them, but no set-up or sign-up approval.
    "route_admin": [("app.py", "Home"), ("pages/10_attendance.py", "Attendance")] + _COMMON + _ACCOUNT,
    # Daily jobs first, then the vet and notices; the set-up pages come last because the Home checklist leads there.
    "farmer": [("app.py", "Home"), ("pages/2_feed_log.py", "Feed log"), ("pages/1_dashboard.py", "Dashboard"),
               ("pages/9_ask_the_vet.py", "Ask the vet")] + _COMMON
              + [("pages/5_cows.py", "Cows"), ("pages/3_budget.py", "Budget"), ("pages/4_farm_setup.py", "Farm setup")] + _ACCOUNT,
    # The vet works from My day; a farm's dashboard and cow records are the farmer's own view.
    "vet": [("app.py", "Home"), ("pages/8_my_day.py", "My day")] + _COMMON + _ACCOUNT,
    # The admin runs the business and sees no farm-data pages: to see a farmer's view, log in as that farmer.
    "admin": [("app.py", "Home"), ("pages/7_admin.py", "Admin"), ("pages/10_attendance.py", "Attendance")] + _COMMON
             + _ACCOUNT,
}
HIDE_BUILT_IN_NAV_CSS = '<style>[data-testid="stSidebarNav"]{display:none}</style>'


def menu_for(role):
    """[(page file, label)] for a role; empty for an unknown role."""
    return MENU.get(role, [])


def menu_key(user):
    return "route_admin" if user["role"] == "admin" and user.get("route_admin") else user["role"]


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


TOPBAR_CSS = (
    "<style>"
    # a bar fixed to the top of the screen on computers; on phones the sidebar menu (the arrow at the top left) is used instead
    "@media (min-width:900px){"
    '[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"]{display:none}'
    ".st-key-topbar{position:fixed;top:0;left:0;right:0;z-index:999;background:rgba(7,20,14,.94);backdrop-filter:blur(14px);"
    "box-shadow:0 8px 28px rgba(0,0,0,.28);padding:.45rem 1.4rem}"
    ".st-key-topbar>div{max-width:1120px;margin:0 auto}"
    ".block-container{padding-top:6.5rem !important}"
    '[data-testid="stHeader"]{display:none}'
    "}"
    "@media (max-width:899px){.st-key-topbar{display:none}}"
    ".st-key-topbar [data-testid='stPageLink-NavLink']{border-radius:999px !important;padding:.35rem .8rem !important;background:transparent !important;color:#E9F3EC !important;white-space:nowrap}"
    ".st-key-topbar [data-testid='stPageLink-NavLink'] *{color:#E9F3EC !important;font-weight:600;font-size:.95rem;margin:0}"
    ".st-key-topbar [data-testid='stPageLink-NavLink']:hover{background:rgba(255,255,255,.14) !important}"
    ".st-key-topbar [data-testid='stPageLink-NavLink'][aria-current='page']{background:#F2A93B !important}"
    ".st-key-topbar [data-testid='stPageLink-NavLink'][aria-current='page'] *{color:#1B2B22 !important}"
    ".st-key-topbar button{color:#E9F3EC !important;border-color:rgba(255,255,255,.4) !important;background:transparent !important;min-height:2.2rem}"
    ".st-key-topbar button *{color:#E9F3EC !important}"
    ".st-key-topbar .tb-brand{display:flex;align-items:center;gap:.55rem;color:#fff;font-weight:700;font-size:1.15rem;white-space:nowrap;font-family:'Fredoka','DM Sans',sans-serif}"
    ".st-key-topbar .tb-brand svg{width:2.3rem;height:2.3rem;flex:none}"
    ".st-key-topbar .tb-brand b{color:#F2A93B}"
    ".st-key-topbar .tb-who{color:#CFE3D6;font-size:.85rem;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
    "</style>"
)
TOPBAR_SHOWN = 4  # links shown on the bar itself; the rest sit under "More"


def render_topbar(user, role):
    """A navigation bar at the top of every page once logged in, so Home and the main pages are always one click away."""
    from src import public_site

    items = menu_for(role)
    if not items:
        return
    from urllib.parse import quote

    logo = "data:image/svg+xml;utf8," + quote(public_site.LOGO_SVG)
    st.markdown(
        TOPBAR_CSS + "<style>.st-key-tb_brand [data-testid='stPageLink-NavLink']{padding-left:3rem !important;border-radius:12px !important;"
        f"background:url(\"{logo}\") no-repeat .25rem center/2.3rem !important}}"
        ".st-key-tb_brand [data-testid='stPageLink-NavLink'] *{font-family:'Fredoka','DM Sans',sans-serif;font-size:1.15rem !important;color:#fff !important}"
        ".st-key-tb_brand [data-testid='stPageLink-NavLink']:hover{background-color:rgba(255,255,255,.1) !important}</style>",
        unsafe_allow_html=True,
    )
    head, rest = items[:TOPBAR_SHOWN], items[TOPBAR_SHOWN:]
    try:
        with st.container(key="topbar"):
            cols = st.columns([2.3] + [1.15] * len(head) + [1.0, 0.8, 1.0, 1.0], vertical_alignment="center")
            with cols[0], st.container(key="tb_brand"):
                st.page_link("pages/13_website.py", label="Maziwa Plus")  # the logo goes to the public Home page
            for col, (path, label) in zip(cols[1:], head):
                with col:
                    st.page_link(path, label=label)
            with cols[len(head) + 1]:
                with st.popover("More"):
                    for path, label in rest:
                        st.page_link(path, label=label)
            with cols[len(head) + 2]:
                from src import notifications

                bell = notifications.for_user(user)
                with st.popover(f"🔔 {len(bell)}" if bell else "🔔"):
                    if not bell:
                        st.caption("Nothing needs your attention.")
                    for text, page in bell:
                        st.page_link(page, label=text)
            cols[len(head) + 3].markdown(f'<div class="tb-who">{html_escape(user["name"])}</div>', unsafe_allow_html=True)
            with cols[len(head) + 4]:
                if st.button("Log out", key="topbar_logout"):
                    st.session_state.clear()
                    st.rerun()
    except Exception:  # a page run on its own (as in tests) has no page registry to link into
        pass


def loader_css():
    """While the app is working (loading a page, saving a form): a thin progress bar across the top and our cow bobbing
    in the corner, instead of Streamlit's small 'Running...' label. Pure CSS, keyed on Streamlit's own running flag."""
    from urllib.parse import quote

    from src import public_site

    cow = "data:image/svg+xml;utf8," + quote(public_site.LOGO_SVG)
    return (
        "<style>"
        '[data-testid="stStatusWidget"]{display:none !important}'
        '.stApp[data-test-script-state="running"]::before{content:"";position:fixed;top:0;left:0;height:4px;width:100%;z-index:100000;'
        "background:linear-gradient(90deg,#2A6F46,#F2A93B,#2A6F46);background-size:200% 100%;animation:ldbar 1.1s linear infinite}"
        '.stApp[data-test-script-state="running"]::after{content:"";position:fixed;right:1.1rem;bottom:1.1rem;width:3.4rem;height:3.4rem;z-index:100000;'
        f'background:url("{cow}") center/contain no-repeat;border-radius:50%;box-shadow:0 10px 24px rgba(0,0,0,.35);animation:ldbob .9s ease-in-out infinite}}'
        "@keyframes ldbar{from{background-position:200% 0}to{background-position:0 0}}"
        "@keyframes ldbob{0%,100%{transform:translateY(0) rotate(-4deg)}50%{transform:translateY(-9px) rotate(4deg)}}"
        "@media (prefers-reduced-motion:reduce){.stApp[data-test-script-state=\"running\"]::before,.stApp[data-test-script-state=\"running\"]::after{animation:none !important}}"
        "</style>"
    )


def require_login(roles=None):
    """Show the login screen and stop the page until someone is logged in; returns the user.

    `roles`: if given, only these roles may see the page (others are told so and stopped).
    """
    configure_admin_phone()
    st.markdown(loader_css(), unsafe_allow_html=True)
    owner_pw = configured_password()
    if not owner_pw and not os.environ.get("ADMIN_PHONE") and not st.session_state.get("user"):
        st.error("This app is locked: no password has been set. Set APP_PASSWORD (see README).")
        st.stop()
    user = current_user()
    if not user and st.session_state.get("pending_2fa"):
        if _too_many():
            st.session_state.pop("pending_2fa", None)
        else:
            _second_factor_screen(st.session_state["pending_2fa"])
    if not user:
        st.markdown(LOGGED_OUT_CSS, unsafe_allow_html=True)
        from src import public_site

        public_site.render_header()
        if st.session_state.pop("account_deleted", False):
            st.success("Your account and its records have been deleted.")
        if _too_many():
            st.error("Too many wrong tries. Reload the page to try again.")
            st.stop()
        top = ["Home", "Log in", "Sign up"]
        t_home, t_login, t_signup = st.tabs(top)
        with t_home:
            public_site.render_home()
        with t_login:
            public_site.page_title("Welcome back", "Log in to see your farm, your route or the admin view.")
            st.markdown(CLAY_CSS + PEEK_COW, unsafe_allow_html=True)
            mid = st.columns([1, 3, 1])[1]  # a narrow form reads better than one stretched across the page
            with mid, st.container(border=True, key="clay"):
                methods = ["Email & password", "SMS code"] + (["Owner password"] if owner_pw else [])
                for tab, name in zip(st.tabs(methods), methods):
                    with tab:
                        {"SMS code": _tab_sms, "Email & password": _tab_email}.get(name, lambda: _tab_owner(owner_pw))()
            public_site.render_footer()
        with t_signup:
            public_site.page_title("Create your account", "Farmers, vets and milk-buyer staff each get their own view.")
            st.markdown(PEEK_COW.replace('id="pk-', 'id="pk2-').replace("url(#pk-", "url(#pk2-"), unsafe_allow_html=True)  # own gradient ids: a hidden tab's copy would break the other
            with st.columns([1, 3, 1])[1], st.container(border=True, key="clay_signup"):
                _tab_signup()
            public_site.render_footer()
        st.stop()
    if user.get("must_change_password"):
        _force_password_change(user)
    render_menu(menu_key(user))
    render_topbar(user, menu_key(user))
    st.sidebar.caption(f"Signed in: {user['name']} ({user['role']})")
    if st.sidebar.button("Log out"):
        st.session_state.clear()
        st.rerun()
    if roles and user["role"] not in roles:
        st.error("This page is not available for your account.")
        st.stop()
    return user
