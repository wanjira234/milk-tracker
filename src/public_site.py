"""The public pages a visitor sees before logging in: Home, About us and Contact us.

Everything here is fixed text, except the contact form, which only stores what it is given."""
import html
import os
import time

import streamlit as st
import streamlit.components.v1 as components

from src import contact
from src.messages import APP_NAME

IMG = "app/static/img/"  # relative on purpose: Streamlit Cloud serves the app under a prefix, so a leading slash would miss the files
HERO_VIDEO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "hero.mp4")

PUBLIC_CSS = (
    "<style>"
    "@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Fredoka:wght@500;600&display=swap');"
    ".land{font-family:'DM Sans',system-ui,sans-serif;color:#1B2B22}"
    ".land h1,.land h2,.land h3{font-family:'Fredoka','DM Sans',sans-serif;font-weight:600;color:inherit;margin:0;padding:0}"
    ".land a.btn{display:inline-block;border-radius:999px;padding:.85rem 1.5rem;font-weight:700;text-decoration:none;"
    "margin:.25rem .6rem .25rem 0;cursor:pointer;min-height:3rem;box-sizing:border-box}"
    ".land a.btn.main{background:#F2A93B;color:#0F2E20}"
    ".land a.btn.main:hover{background:#FFBE5C}"
    ".land a.btn.ghost{border:2px solid #FFF8EA;color:#FFF8EA}"
    ".land a.btn.ghost:hover{background:rgba(255,248,234,.15)}"
    ".land a.btn.dark{background:#0F2E20;color:#FFF8EA}"
    # top bar
    ".topbar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.6rem 1.5rem;padding:.2rem 0 1.1rem}"
    ".topbar a{text-decoration:none;cursor:pointer}"
    ".brand{display:flex;align-items:center;gap:.7rem;color:#0F2E20}"
    ".brand svg{width:3.1rem;height:3.1rem;flex:none}"
    ".brand .bn{font-family:'Fredoka',sans-serif;font-weight:600;font-size:1.9rem;line-height:1;color:#0F2E20}"
    ".brand .bn b{color:#D98A0B;font-weight:600}"
    ".nav{display:flex;gap:.3rem;flex-wrap:wrap}"
    ".nav a{color:#1B2B22;font-weight:500;font-size:1.1rem;padding:.65rem 1.1rem;border-radius:999px;min-height:2.75rem;box-sizing:border-box}"
    ".nav a:hover{background:#E4EFE2;color:#0F2E20}"
    # footer
    ".foot2{background:#0F2E20;color:#E8F1EA;border-radius:28px;padding:2.4rem 2.4rem 1.2rem;margin:2.5rem 0 1rem}"
    ".fgrid{display:grid;grid-template-columns:1.6fr 1fr 1fr 1.2fr;gap:2rem}"
    ".foot2 h4{font-family:'Fredoka',sans-serif;color:#F2A93B;font-weight:600;font-size:1.05rem;margin:0 0 .7rem;letter-spacing:.04em}"
    ".foot2 a{display:block;color:#E8F1EA;text-decoration:none;padding:.3rem 0;cursor:pointer}"
    ".foot2 a.brand{display:flex;padding:0}"
    ".foot2 a:hover{color:#F2A93B;text-decoration:underline}"
    ".foot2 p{margin:.4rem 0;color:#B8D3C2;line-height:1.5}"
    ".foot2 .brand .bn{color:#FFF8EA}.foot2 .brand .bn b{color:#F2A93B}"
    ".fbot{display:flex;flex-wrap:wrap;justify-content:space-between;gap:.4rem 1.5rem;border-top:1px solid rgba(255,248,234,.2);"
    "margin-top:1.6rem;padding-top:1rem;font-size:.88rem;color:#B8D3C2}"
    # hero
    ".hero{position:relative;display:grid;grid-template-columns:1.15fr .85fr;min-height:30rem;border-radius:28px;"
    "overflow:hidden;background:#0F2E20;color:#FFF8EA}"
    ".hero .txt{position:relative;z-index:2;padding:3rem 2.5rem;display:flex;flex-direction:column;justify-content:center}"
    ".hero .eyebrow{color:#F2A93B;font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:.85rem}"
    ".hero h1{font-size:3.1rem;line-height:1.08;margin:.5rem 0 1rem !important}"
    ".hero h1 em{font-style:normal;color:#F2A93B}"
    ".hero p.lead{font-size:1.2rem;line-height:1.5;color:#E8F1EA;max-width:34rem;margin:0 0 1.4rem}"
    ".hero .pic{position:relative}"
    ".hero .pic img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center 30%}"
    ".hero .pic:after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,#0F2E20 0%,rgba(15,46,32,0) 35%)}"
    ".hero video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0}"
    ".hero.vid{display:block}"
    ".hero.vid:before{content:'';position:absolute;inset:0;z-index:1;"
    "background:linear-gradient(90deg,rgba(15,46,32,.92) 0%,rgba(15,46,32,.7) 55%,rgba(15,46,32,.25) 100%)}"
    ".hero.vid .txt{max-width:44rem}"
    # trust strip
    ".trust{display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;justify-content:center;padding:1rem .5rem;color:#2F4237;font-weight:500}"
    ".trust span:before{content:'\\2713';color:#2A6F46;font-weight:700;margin-right:.4rem}"
    # sections
    ".sec{margin:3.2rem 0 1.2rem}"
    ".sec .eyebrow{color:#2A6F46;font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:.8rem}"
    ".sec h2{font-size:2.1rem;line-height:1.15;margin:.3rem 0 .4rem !important}"
    ".sec p{color:#3F5247;font-size:1.05rem;max-width:40rem}"
    ".grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:1.1rem}"
    ".step,.role{background:#fff;border:2px solid #E8DCC0;border-radius:22px;overflow:hidden}"
    ".step{padding:1.4rem}"
    ".step .n{display:inline-block;width:2.4rem;height:2.4rem;line-height:2.4rem;text-align:center;border-radius:50%;"
    "background:#F2A93B;color:#0F2E20;font-weight:700;margin-bottom:.6rem}"
    ".step h3,.role h3{font-size:1.35rem;margin-bottom:.35rem !important}"
    ".step p,.role p{color:#3F5247;margin:0;line-height:1.5}"
    ".role img{width:100%;height:12rem;object-fit:cover;display:block}"
    ".role .rb{padding:1.1rem 1.3rem 1.3rem}"
    ".feat{display:grid;grid-template-columns:1fr 1fr;gap:2.5rem;align-items:center;margin:2.6rem 0}"
    ".feat.flip .ph{order:2}"
    ".feat .ph img{width:100%;height:22rem;object-fit:cover;border-radius:24px;display:block;box-shadow:0 12px 30px rgba(15,46,32,.15)}"
    ".feat h2{font-size:1.9rem;line-height:1.15;margin:.3rem 0 .7rem !important}"
    ".feat p{color:#3F5247;font-size:1.05rem;line-height:1.55}"
    ".feat ul{list-style:none;padding:0;margin:.8rem 0 0}"
    ".feat li{padding:.25rem 0 .25rem 1.7rem;position:relative;color:#1B2B22}"
    ".feat li:before{content:'\\2713';position:absolute;left:0;color:#2A6F46;font-weight:700}"
    ".feat .eyebrow{color:#2A6F46;font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:.8rem}"
    ".band{display:grid;grid-template-columns:1.2fr .8fr;background:#0F2E20;color:#FFF8EA;border-radius:28px;overflow:hidden;margin:3rem 0}"
    ".band .bt{padding:2.2rem 2.4rem}"
    ".band .bigstat{font-family:'Fredoka',sans-serif;font-size:4.2rem;font-weight:600;color:#F2A93B;line-height:1}"
    ".band p{color:#E8F1EA;font-size:1.1rem;line-height:1.5;margin:.6rem 0 0}"
    ".band .src{color:#B8D3C2;font-size:.85rem}"
    ".band .im{position:relative;min-height:16rem}.band .im img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}"
    ".cta{background:linear-gradient(135deg,#0F2E20 0%,#1F5A3A 100%);color:#FFF8EA;border-radius:28px;padding:2.6rem 2rem;text-align:center;margin:3rem 0 1rem}"
    ".cta h2{font-size:2.2rem;margin-bottom:.4rem !important}"
    ".cta p{color:#E8F1EA;font-size:1.1rem;margin:0 0 1.2rem}"
        ".small{color:#5A6A60;font-size:.9rem}"
    ".card{background:#FFFFFF;border:2px solid #E8DCC0;border-radius:20px;padding:1.25rem 1.25rem 1rem;height:100%}"
    ".card h4{margin:.1rem 0 .4rem;color:#0F2E20}"
    ".card p{color:#3F5247;margin:0}"
    ".banner{width:100%;height:14rem;object-fit:cover;border-radius:24px;display:block;margin-bottom:1rem}"
    "@media (max-width:760px){"
    ".fgrid{grid-template-columns:1fr 1fr}.foot2{padding:1.6rem 1.3rem 1rem}.nav a{padding:.6rem .8rem}.brand .bn{font-size:1.6rem}"
    ".hero,.band,.feat{grid-template-columns:1fr}"
    ".hero .txt{padding:2rem 1.4rem}.hero h1{font-size:2.3rem}"
    ".hero .pic{height:15rem;order:-1}"
    ".hero .pic:after{background:linear-gradient(0deg,#0F2E20 0%,rgba(15,46,32,0) 45%)}"
    ".hero video{display:none}.hero.vid:before{background:#0F2E20}"
    ".grid3{grid-template-columns:1fr}"
    ".feat{gap:1rem;margin:2rem 0}.feat.flip .ph{order:0}.feat .ph img{height:15rem}"
    ".band .bt{padding:1.6rem 1.4rem}.band .im{min-height:12rem}"
    ".sec h2,.feat h2{font-size:1.65rem}.cta h2{font-size:1.7rem}"
    "}"
    "@media (prefers-reduced-motion:reduce){.hero video{display:none}}"
    "</style>"
)

# Lets the big buttons on the Home page open the Log in / Sign up / Contact us tab. If scripts are blocked the
# buttons do nothing and the tabs along the top still work. The page text is fixed; nothing typed is used here.
GOTO_JS = (
    "<script>(function(){var p=window.parent,d=p.document;if(p.__gotoReady)return;p.__gotoReady=true;"
    "d.addEventListener('click',function(e){var a=e.target.closest('[data-goto]');if(!a)return;e.preventDefault();"
    "var t=[].slice.call(d.querySelectorAll('[role=tab]')).find(function(b){return b.innerText.trim()===a.getAttribute('data-goto')});"
    "if(t){t.click();var m=d.querySelector('[data-testid=stMain]');if(m)m.scrollTo({top:0,behavior:'smooth'});}},true);})();</script>"
)


LOGO_SVG = (
    '<svg viewBox="0 0 64 64" role="img" aria-label="Maziwa Plus logo" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="32" r="30" fill="#1F5A3A" stroke="#F2A93B" stroke-width="3"/>'
    '<path d="M32 11C32 11 17 27 17 38a15 15 0 0 0 30 0C47 27 32 11 32 11z" fill="#FFF8EA"/>'
    '<rect x="30" y="31" width="4" height="15" rx="1.5" fill="#F2A93B"/><rect x="24.5" y="36.5" width="15" height="4" rx="1.5" fill="#F2A93B"/></svg>'
)


def _run_script(script):
    """Run a fixed script in a tiny hidden frame. st.iframe replaces components.html on newer Streamlit."""
    doc = f"<!doctype html><html><body>{script}</body></html>"
    if hasattr(st, "iframe"):
        st.iframe(doc, height=1)
    else:
        components.html(doc, height=0)


def _brand():
    return f'<a class="brand" href="#" data-goto="Home">{LOGO_SVG}<span class="bn">Maziwa <b>Plus</b></span></a>'


def render_header():
    """Logo and the three page links above the pages. Log in and Sign up have their own big buttons on the Home page
    and in the footer, so they are not repeated here."""
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="land"><div class="topbar">{_brand()}<nav class="nav" aria-label="Main">'
        '<a href="#" data-goto="Home">Home</a><a href="#" data-goto="About us">About us</a>'
        '<a href="#" data-goto="Contact us">Contact us</a></nav></div></div>',
        unsafe_allow_html=True,
    )
    _run_script(GOTO_JS)


def render_footer():
    email, phone = os.environ.get("CONTACT_EMAIL", "").strip(), os.environ.get("CONTACT_PHONE", "").strip()
    lines = "".join(f"<p>{html.escape(x)}</p>" for x in (email, phone) if x) or "<p>Send us a message and we will reply.</p>"
    st.markdown(
        f'<div class="land"><footer class="foot2"><div class="fgrid"><div>{_brand()}'
        "<p>Know what your feed is worth.</p><p>Karibu. A tool for farmers, vets and milk buyers.</p></div>"
        '<div><h4>Explore</h4><a href="#" data-goto="Home">Home</a><a href="#" data-goto="About us">About us</a>'
        '<a href="#" data-goto="Contact us">Contact us</a></div>'
        '<div><h4>Get started</h4><a href="#" data-goto="Sign up">Create an account</a><a href="#" data-goto="Log in">Log in</a></div>'
        f'<div><h4>Contact</h4>{lines}<a href="#" data-goto="Contact us">Write to us</a></div></div>'
        '<div class="fbot"><span>© 2026 HustleWindow</span>'
        "<span>Built for the FNB App of the Year hackathon. Demo data is simulated.</span></div></footer></div>",
        unsafe_allow_html=True,
    )


def _cards(items, steps=False):
    cols = st.columns(len(items))
    for i, (col, (title, text)) in enumerate(zip(cols, items), start=1):
        badge = f'<div class="n" style="display:inline-block;width:2.2rem;height:2.2rem;line-height:2.2rem;text-align:center;border-radius:50%;background:#F2A93B;color:#0F2E20;font-weight:700;margin-bottom:.5rem">{i}</div>' if steps else ""
        col.markdown(f'<div class="card">{badge}<h4>{title}</h4><p>{text}</p></div>', unsafe_allow_html=True)


def _hero():
    has_video = os.path.exists(HERO_VIDEO)
    txt = (
        '<div class="txt"><div class="eyebrow">For smallholder dairy farmers</div>'
        "<h1>Know what your milk <em>really earns</em>.</h1>"
        '<p class="lead">Feed is the biggest cost on a dairy farm. Record your day, see what each feed pays back, '
        "and reach your vet and your milk route from one phone.</p>"
        '<div><a class="btn main" href="#" data-goto="Sign up">Get started</a>'
        '<a class="btn ghost" href="#" data-goto="Log in">I have an account</a></div></div>'
    )
    if has_video:
        media = (
            f'<video autoplay muted loop playsinline preload="metadata" poster="{IMG}hero-cow.jpg" aria-hidden="true">'
            '<source src="app/static/hero.mp4" type="video/mp4"></video>'
        )
        return f'<div class="hero vid">{media}{txt}</div>'
    pic = f'<div class="pic"><img src="{IMG}hero-cow.jpg" alt="A curious brown cow looking into the camera"></div>'
    return f'<div class="hero">{txt}{pic}</div>'


def _steps():
    items = [
        ("Log your day", "Record the milk and what you fed, in the buckets, bags or bales you really use."),
        ("Ask and book", "Request the vet, choose AI semen from your route vet's price list, book vaccination days."),
        ("Hear what matters", "Get an outbreak alert, or one short SMS about one feed, only when the records are clear."),
    ]
    return "".join(f'<div class="step"><div class="n">{i}</div><h3>{t}</h3><p>{p}</p></div>' for i, (t, p) in enumerate(items, 1))


def _roles():
    items = [
        ("cow-sky.jpg", "A farm cow looking happily at the camera", "Farmers",
         "See what is left after feed and semen, keep herd records, and reach your vet without phone tag."),
        ("calves.jpg", "Calves standing together in a field", "Vets",
         "Open one sheet with today's farms, each visit and what to carry. Keep your own priced semen list."),
        ("milk-can.jpg", "Fresh milk being poured into a milk can", "Milk buyers",
         "Set up routes, send alerts to the farms that need them, and see which visits were attended."),
    ]
    return "".join(
        f'<div class="role"><img src="{IMG}{f}" alt="{a}" loading="lazy"><div class="rb"><h3>{t}</h3><p>{p}</p></div></div>'
        for f, a, t, p in items
    )


def _feature(img, alt, eyebrow, title, text, bullets, flip=False):
    lis = "".join(f"<li>{b}</li>" for b in bullets)
    return (
        f'<div class="feat{" flip" if flip else ""}"><div class="ph"><img src="{IMG}{img}" alt="{alt}" loading="lazy"></div>'
        f'<div><div class="eyebrow">{eyebrow}</div><h2>{title}</h2><p>{text}</p><ul>{lis}</ul></div></div>'
    )


FAQ = [
    ("Who can see my records?",
     "You, the vet on your route, and the milk buyer's admins. A farmer never sees another farm, and nobody can sign up as an admin."),
    ("What does the advice need from me?",
     "About 14 full days of milk and feed records. Until then the app tells you what it is waiting for instead of guessing. "
     "Weigh one full bucket of each feed once, and it works out the rest."),
    ("Can I delete my account?",
     "Yes. Open My account after you log in. Your account and every record on it are removed."),
    ("Is the demo data real?",
     "No. The demo farms are simulated, and demo texts reach a simulator, not real phones."),
]


def render_home():
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.markdown('<div class="land">' + _hero() + "</div>", unsafe_allow_html=True)
    st.markdown(
        '<div class="land"><div class="trust"><span>Works on any phone</span><span>Your records stay yours</span>'
        "<span>Delete your account any time</span><span>Advice shows its working</span></div></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="land"><div class="sec"><div class="eyebrow">How it works</div><h2>Three steps, a few minutes a day</h2></div>'
        f'<div class="grid3">{_steps()}</div>'
        + _feature("farmer-feeding.jpg", "A farmer hand-feeding fresh grass to a brown cow", "For the farmer",
                   "Log your day in the buckets you already use",
                   "Feeding a truckload of napier, shredded and mixed with hay? Record it as 20-litre buckets, 50 kg bags or bales. "
                   "Weigh one full bucket once and the app does the sums.",
                   ["Bought or grown on your own land, both count", "A chart of your milk, day by day", "A get-started list that tells you the next step"])
        + _feature("pellets.jpg", "A hand holding feed pellets towards two cows", "Honest advice",
                   "Advice that shows its working",
                   "After 14 full days of records, the app compares what each feed costs with what the cows gave back. "
                   "If the evidence is thin it says so, and does not guess.",
                   ["One short SMS about one feed", "Costs in shillings per litre", "Your vet's semen prices in one list"], flip=True)
        + _feature("barn.jpg", "A farm worker walking between cows in a barn at sunrise", "For vets and milk buyers",
                   "One view for the whole route",
                   "Vets see today's farms and what to carry. Milk buyers see which visits were attended and send an outbreak alert "
                   "only to the routes that need it.",
                   ["Vaccination days booked in advance", "Route admins see only their own routes", "Every request tracked from ask to done"])
        + '<div class="sec"><div class="eyebrow">Who it is for</div><h2>Built for every person on the route</h2></div>'
        f'<div class="grid3">{_roles()}</div>'
        '<div class="band"><div class="bt"><div class="bigstat">43–58%</div>'
        "<p>of what it costs to make a litre of milk is feed, and most farms buy it by feel. "
        "We help each farm see which feed pays on its own cows.</p>"
        '<p class="src">Source: Tegemeo Institute and Kenya Dairy Board cost study (2014 data).</p></div>'
        f'<div class="im"><img src="{IMG}bottling.jpg" alt="Milk being filled into clear bottles" loading="lazy"></div></div>'
        '<div class="sec"><div class="eyebrow">Questions</div><h2>Before you sign up</h2></div></div>',
        unsafe_allow_html=True,
    )
    for q, a in FAQ:
        with st.expander(q):
            st.write(a)
    st.markdown(
        '<div class="land"><div class="cta"><h2>Ready to see what your feed is worth?</h2>'
        "<p>Sign up takes a minute. Farmers, vets and milk-buyer admins each get their own view.</p>"
        '<a class="btn main" href="#" data-goto="Sign up">Create my account</a>'
        '<a class="btn ghost" href="#" data-goto="Contact us">Talk to us</a></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    render_footer()


def render_about():
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="land"><img class="banner" src="{IMG}trough.jpg" alt="Cows feeding at a wooden trough at sunset"></div>', unsafe_allow_html=True)
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
    render_footer()


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
    render_footer()
