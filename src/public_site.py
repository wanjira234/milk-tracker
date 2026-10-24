"""The public pages a visitor sees before logging in: Home, About us and Contact us.

Everything here is fixed text, except the contact form, which only stores what it is given."""
import os
import time

import streamlit as st

from src import contact
from src.messages import APP_NAME

PUBLIC_CSS = (
    "<style>"
    ".block-container{max-width:980px}"
    ".card{background:#FFFFFF;border:2px solid #E8DCC0;border-radius:20px;padding:1.25rem 1.25rem 1rem;height:100%}"
    ".card h4{margin:.1rem 0 .4rem;color:#0F2E20}"
    ".card p{color:#3F5247;margin:0}"
    ".step{display:inline-block;width:2.2rem;height:2.2rem;line-height:2.2rem;text-align:center;border-radius:50%;"
    "background:#F2A93B;color:#0F2E20;font-weight:700;margin-bottom:.5rem}"
    ".bigstat{font-size:3.2rem;font-weight:800;color:#F2A93B;line-height:1}"
    ".band{background:#0F2E20;color:#FFF8EA;border-radius:24px;padding:1.5rem 1.75rem;margin:1rem 0}"
    ".band p{color:#E8F1EA;margin:.3rem 0 0}"
    ".small{color:#5A6A60;font-size:.9rem}"
    "</style>"
)


def _cards(items, steps=False):
    cols = st.columns(len(items))
    for i, (col, (title, text)) in enumerate(zip(cols, items), start=1):
        badge = f'<div class="step">{i}</div>' if steps else ""
        col.markdown(f'<div class="card">{badge}<h4>{title}</h4><p>{text}</p></div>', unsafe_allow_html=True)


def render_home():
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.subheader("How it works")
    _cards([
        ("Log your day", "Record the milk and what you fed, in the buckets, bags or bales you really use."),
        ("Ask and book", "Request the vet, choose AI semen from your route vet's price list, book vaccination days."),
        ("Hear what matters", "Get an outbreak alert, or one short SMS about one feed, only when the records are clear."),
    ], steps=True)
    st.subheader("Who it is for")
    _cards([
        ("Farmers", "See what is left after feed and semen, keep herd records, and reach your vet without phone tag."),
        ("Vets", "Open one sheet with today's farms, each visit and what to carry. Keep your own priced semen list."),
        ("Milk buyers", "Set up routes, send alerts to the farms that need them, and see which visits were attended."),
    ])
    st.markdown(
        '<div class="band"><div class="bigstat">43–58%</div>'
        "<p>of what it costs to make a litre of milk is feed, and farmers buy it by feel. "
        "We help each farm see which feed pays on its own cows.</p>"
        '<p class="small" style="color:#B8D3C2">Source: Tegemeo Institute and Kenya Dairy Board cost study (2014 data).</p></div>',
        unsafe_allow_html=True,
    )
    st.info("New here? Open **Sign up** above. Already registered? Open **Log in**.")


def render_about():
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.subheader(f"About {APP_NAME}")
    st.write(
        "We are HustleWindow, a team building tools for smallholder dairy farmers in Kenya. Most farms buy feed by feel and "
        "arrange vets and vaccination by phone call. We wanted one place where the farmer, the route vet and the milk buyer "
        "see the same facts."
    )
    team = os.environ.get("ABOUT_TEAM", "").strip()
    if team:
        st.write(team)
    _cards([
        ("Honest by design", "Advice appears only after 14 full days of records and when even the cautious estimate pays. Otherwise you get a plain note, not a guess."),
        ("Private by default", "A farmer sees only their own farm. A vet sees only the farms on their route. Nobody can sign up as an admin."),
        ("Yours to delete", "You can delete your account and every record on it at any time, from My account."),
    ])
    st.subheader("Your data")
    st.markdown(
        "- **What we keep:** your name, phone or email, and the farm records you enter: milk, feed, herd, vet requests.\n"
        "- **Who sees it:** you, the vet on your route, and the milk buyer's admins.\n"
        "- **SMS:** sent through Africa's Talking. During this demo it reaches a simulator, not real phones.\n"
        "- **AI:** Claude only rewords advice that the app has already worked out. It is never sent your name or phone number.\n"
        "- **Demo data:** the demo farms are simulated, not real people."
    )


def render_contact():
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.subheader("Contact us")
    st.write("Questions, a problem, or want to bring your milk route on? Write to us and we will reply.")
    email, phone = os.environ.get("CONTACT_EMAIL", "").strip(), os.environ.get("CONTACT_PHONE", "").strip()
    if email or phone:
        st.markdown("  \n".join(x for x in (f"**Email:** {email}" if email else "", f"**Phone:** {phone}" if phone else "") if x))
    with st.form("contact_form", clear_on_submit=True):
        name = st.text_input("Your name", max_chars=contact.MAX_NAME, key="contact_name")
        how = st.text_input("Your email or phone", max_chars=contact.MAX_CONTACT, key="contact_how")
        message = st.text_area("Your message", max_chars=contact.MAX_MESSAGE, key="contact_message")
        if st.form_submit_button("Send message", type="primary"):
            last = st.session_state.get("contact_last", 0)
            if time.time() - last < 60:
                st.error("Please wait a minute before sending another message.")
            else:
                try:
                    contact.post_message(name, how, message)
                except ValueError as e:
                    st.error(str(e)[:1].upper() + str(e)[1:] + ".")
                else:
                    st.session_state["contact_last"] = time.time()
                    st.success("Thank you. We have your message and will reply to the contact you gave.")
