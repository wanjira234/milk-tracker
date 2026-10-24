"""The public site a visitor sees before logging in: one scrolling page (Home, How it works, About us, FAQ, Contact us).

Everything here is fixed text, except the contact form, which only stores what it is given. Log in and Sign up are
separate views that the big buttons open (the tab strip itself is hidden by src.auth)."""
import html
import os
import time

import streamlit as st
import streamlit.components.v1 as components

from src import contact
from src.messages import APP_NAME

# Relative on purpose: Streamlit Cloud serves the app under a prefix, so a leading slash would miss the files.
IMG = "app/static/img/"
HERO_VIDEO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "hero.mp4")

# Line icons (24x24, stroke only). Drawn here so there is nothing to download and they take the text colour.
_ICONS = {
    "drop": '<path d="M12 2.7s7 7.2 7 12.3a7 7 0 0 1-14 0C5 9.9 12 2.7 12 2.7z"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "phone": '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
    "coins": '<circle cx="12" cy="12" r="9"/><path d="M12 6v12M9 9.5c0-1 1.3-1.5 3-1.5s3 .7 3 1.7-1.3 1.6-3 2-3 1-3 2 1.3 1.8 3 1.8 3-.6 3-1.6"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "cross": '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    "leaf": '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10z"/><path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12"/>',
    "pin": '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 7L2 7"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "trend": '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    "notebook": '<path d="M4 4h13a3 3 0 0 1 3 3v13H7a3 3 0 0 1-3-3z"/><path d="M8 9h8M8 13h5"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>',
    "tel": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
}


def icon(name, size="1.5rem"):
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>'
    )


PUBLIC_CSS = (
    "<style>"
    "@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Fredoka:wght@500;600&display=swap');"
    ":root{--bg:#07140E;--mint:#8FE0A8;--amber:#F2A93B;--amber2:#FFC766;--ink:#E8F1EA;--mute:#A9C6B3}"
    # one continuous dark page: soft green and amber glows, no blank bands
    ".stApp{background:#07140E;background-image:radial-gradient(900px 600px at 8% 28%,rgba(42,111,70,.30),transparent 70%),"
    "radial-gradient(800px 600px at 100% 62%,rgba(242,169,59,.10),transparent 70%),radial-gradient(900px 700px at 0% 100%,rgba(42,111,70,.22),transparent 70%);"
    "background-attachment:fixed}"
    "[data-testid='stMain']{overflow-x:hidden}"
    ".land{font-family:'DM Sans',system-ui,sans-serif;color:var(--ink)}"
    ".land *{box-sizing:border-box}"
    ".land h1,.land h2,.land h3{font-family:'Fredoka','DM Sans',sans-serif;font-weight:600;color:inherit;margin:0;padding:0;letter-spacing:-.01em}"
    ".land svg{flex:none}"
    "[data-anchor]{scroll-margin-top:5rem}"
    ".wrap{max-width:1120px;margin:0 auto;padding:0 1.2rem}"
    ".bleed{width:100vw;margin-left:calc(50% - 50vw)}"
    # buttons
    ".land a.btn{display:inline-flex;align-items:center;gap:.5rem;border-radius:999px;padding:.9rem 1.6rem;font-weight:700;"
    "text-decoration:none;margin:.25rem .6rem .25rem 0;cursor:pointer;min-height:3rem;transition:transform .18s,box-shadow .18s,background .18s}"
    ".land a.btn:hover{transform:translateY(-2px)}"
    ".land a.btn.main{background:linear-gradient(135deg,#FFC766,#F2A93B);color:#07140E;box-shadow:0 10px 26px rgba(242,169,59,.35)}"
    ".land a.btn.main:hover{box-shadow:0 14px 34px rgba(242,169,59,.5)}"
    ".land a.btn.ghost{border:1.5px solid rgba(232,241,234,.55);color:#E8F1EA;background:rgba(232,241,234,.06)}"
    ".land a.btn.ghost:hover{background:rgba(232,241,234,.16)}"
    # glass
    ".g{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.11);border-radius:24px;backdrop-filter:blur(14px);"
    "-webkit-backdrop-filter:blur(14px);box-shadow:0 18px 40px rgba(0,0,0,.28);transition:transform .25s,border-color .25s,box-shadow .25s}"
    ".g:hover{transform:translateY(-5px);border-color:rgba(143,224,168,.4);box-shadow:0 24px 50px rgba(0,0,0,.4)}"
    # top bar
    ".topbar{position:fixed;top:0;left:0;right:0;z-index:1000;background:rgba(7,20,14,.55);backdrop-filter:blur(18px);"
    "-webkit-backdrop-filter:blur(18px);border-bottom:1px solid rgba(255,255,255,.08)}"
    ".topin{max-width:1120px;margin:0 auto;padding:.55rem 1.2rem;display:flex;align-items:center;justify-content:space-between;gap:1rem}"
    ".topbar a{text-decoration:none;cursor:pointer}"
    ".brand{display:flex;align-items:center;gap:.65rem}"
    ".brand svg{width:2.6rem;height:2.6rem}"
    ".brand .bn{font-family:'Fredoka',sans-serif;font-weight:600;font-size:1.6rem;line-height:1;color:#FFF8EA}"
    ".brand .bn b{color:#F2A93B;font-weight:600}"
    ".nav{display:flex;gap:.2rem}"
    ".nav a{white-space:nowrap;color:#DCEBE1;font-weight:500;font-size:1rem;padding:.6rem 1rem;border-radius:999px}"
    ".nav a:hover{background:rgba(255,255,255,.1);color:#fff}"
    # hero (full width photo that melts into the page)
    ".hero{position:relative;min-height:min(100vh,860px);display:flex;flex-direction:column;justify-content:center;overflow:hidden;padding:11rem 0 2rem;margin-top:-8rem}"
    ".hero .bg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center 42%;z-index:0}"
    ".hero .shade{position:absolute;inset:0;z-index:1;background:linear-gradient(90deg,rgba(7,20,14,.82) 0%,rgba(7,20,14,.5) 42%,rgba(7,20,14,0) 85%),"
    "linear-gradient(180deg,rgba(7,20,14,.5) 0%,rgba(7,20,14,0) 22%),radial-gradient(55% 55% at 78% 22%,rgba(242,169,59,.28),transparent 70%)}"
    ".hero:after{content:'';position:absolute;left:0;right:0;bottom:0;height:11rem;z-index:2;background:linear-gradient(0deg,#07140E 0%,rgba(7,20,14,0) 100%)}"
    ".hero .wrap{position:relative;z-index:3}"
    ".hero .cols{display:grid;grid-template-columns:1.15fr .85fr;gap:2rem;align-items:center}"
    ".pill{display:inline-flex;align-items:center;gap:.5rem;background:rgba(7,20,14,.5);border:1px solid rgba(143,224,168,.4);"
    "border-radius:999px;padding:.4rem .9rem;font-size:.86rem;color:#BDEBCB;font-weight:500;backdrop-filter:blur(8px)}"
    ".pill i{width:.5rem;height:.5rem;border-radius:50%;background:var(--mint);box-shadow:0 0 0 4px rgba(143,224,168,.2)}"
    ".hero h1{font-size:3.9rem;line-height:1.03;margin:1rem 0 1rem !important;color:#fff}"
    ".hero h1 em{font-style:normal;background:linear-gradient(90deg,#FFC766,#F2A93B);-webkit-background-clip:text;background-clip:text;color:transparent}"
    ".hero p.lead{font-size:1.2rem;line-height:1.6;color:#DCEBE1;max-width:33rem;margin:0 0 1.6rem}"
    ".insight{padding:1.2rem 1.3rem;max-width:25rem;margin-left:auto;background:rgba(7,20,14,.55)}"
    ".insight .ih{display:flex;justify-content:space-between;align-items:center;font-weight:600;color:#fff;margin-bottom:.8rem}"
    ".insight .ih{gap:.8rem}.insight .ih span{display:inline-flex;gap:.5rem;align-items:center;white-space:nowrap}"
    ".insight .ih em{font-style:normal;font-size:.72rem;color:#FFE2A8;border:1px solid rgba(242,169,59,.5);padding:.1rem .5rem;border-radius:999px}"
    ".irow{margin:.85rem 0}.irow .l{display:flex;justify-content:space-between;font-size:.9rem;color:#C9DDD0}.irow .l b{color:#fff}"
    ".bar{height:.4rem;border-radius:99px;background:rgba(255,255,255,.12);margin-top:.4rem;overflow:hidden}"
    ".bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#8FE0A8,#4DB878)}"
    ".bar.am i{background:linear-gradient(90deg,#FFC766,#F2A93B)}"
    ".stats{display:grid;grid-template-columns:repeat(4,1fr);gap:.4rem;padding:1.1rem 1.2rem;margin-top:3rem}"
    ".stat{display:flex;gap:.8rem;align-items:center;padding:.2rem .6rem}"
    ".stat .tileic{margin:0;width:2.7rem;height:2.7rem;border-radius:14px}"
    ".stat b{display:block;color:#fff;font-size:1.1rem}.stat span{color:var(--mute);font-size:.85rem}"
    # sections
    ".sec{margin:5rem 0 1.6rem}"
    ".eyebrow{display:inline-flex;align-items:center;gap:.5rem;color:#8FE0A8;font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:.78rem}"
    ".eyebrow:before{content:'';width:1.6rem;height:2px;background:var(--amber)}"
    ".sec h2{font-size:2.5rem;line-height:1.1;margin:.5rem 0 .5rem !important;color:#fff}"
    ".sec p.sub{color:var(--mute);font-size:1.08rem;max-width:40rem;line-height:1.6;margin:0}"
    ".grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem}"
    ".step{position:relative;padding:1.7rem}"
    ".tileic{flex:none;width:3.2rem;height:3.2rem;border-radius:16px;display:flex;align-items:center;justify-content:center;color:#8FE0A8;"
    "background:rgba(143,224,168,.12);border:1px solid rgba(143,224,168,.35);margin-bottom:1rem}"
    ".tileic.amb{color:#FFC766;background:rgba(242,169,59,.14);border-color:rgba(242,169,59,.45)}"
    ".step .num{position:absolute;right:1.3rem;top:.9rem;font-family:'Fredoka',sans-serif;font-size:3.4rem;font-weight:600;color:rgba(255,255,255,.07);line-height:1}"
    ".step h3,.tile h3{font-size:1.3rem;margin-bottom:.4rem !important;color:#fff}"
    ".step p,.tile p{color:var(--mute);margin:0;line-height:1.6}"
    # dashboard preview
    ".split{display:grid;grid-template-columns:.85fr 1.15fr;gap:2.4rem;align-items:center;margin-top:5rem}"
    ".split h2{font-size:2.3rem;line-height:1.1;color:#fff;margin:.5rem 0 .7rem !important}"
    ".split p{color:var(--mute);line-height:1.6;font-size:1.05rem}"
    ".checks{list-style:none;padding:0;margin:1rem 0 1.4rem}"
    ".checks li{display:flex;gap:.7rem;align-items:center;padding:.4rem 0;color:#E8F1EA}"
    ".checks svg{color:#8FE0A8}"
    ".win{padding:1rem;background:rgba(7,20,14,.6);border-radius:22px}"
    ".win .bar0{display:flex;gap:.4rem;align-items:center;padding:.2rem .4rem .8rem;color:#C9DDD0;font-size:.85rem}"
    ".win .bar0 i{width:.6rem;height:.6rem;border-radius:50%;background:rgba(255,255,255,.2)}"
    ".win .bar0 em{margin-left:auto;font-style:normal;font-size:.72rem;color:#FFE2A8;border:1px solid rgba(242,169,59,.5);padding:.1rem .5rem;border-radius:99px}"
    ".tiles3{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem}"
    ".mini{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09);border-radius:16px;padding:.8rem .9rem}"
    ".mini span{font-size:.78rem;color:var(--mute)}.mini b{display:block;font-size:1.5rem;color:#fff;font-family:'Fredoka',sans-serif}.mini b small{font-size:.8rem;color:var(--mute);font-weight:400}"
    ".chart{display:flex;align-items:flex-end;gap:.3rem;height:6.5rem;padding:.9rem .4rem 0;margin-top:.7rem}"
    ".chart i{flex:1;border-radius:6px 6px 2px 2px;background:linear-gradient(0deg,rgba(143,224,168,.25),#8FE0A8)}"
    ".chart i.a{background:linear-gradient(0deg,rgba(242,169,59,.3),#F2A93B)}"
    ".acts{margin-top:.8rem}.act{display:flex;gap:.7rem;align-items:center;padding:.55rem .3rem;border-top:1px solid rgba(255,255,255,.08);color:#DCEBE1;font-size:.92rem}"
    ".act svg{color:#8FE0A8}.act time{margin-left:auto;color:var(--mute);font-size:.8rem}"
    # bento
    ".bento{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:minmax(10.5rem,auto);gap:1.2rem}"
    ".tile{position:relative;padding:1.5rem;overflow:hidden}"
    ".tile.photo{grid-column:span 2;grid-row:span 2;display:flex;flex-direction:column;justify-content:flex-end;min-height:24rem;padding:0}"
    ".tile.photo img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}"
    ".tile.photo:after{content:'';position:absolute;inset:0;background:linear-gradient(0deg,rgba(7,20,14,.95) 0%,rgba(7,20,14,.4) 55%,rgba(7,20,14,.05) 100%)}"
    ".tile.photo>div{position:relative;z-index:2;padding:1.5rem}"
    ".tile.wideg{grid-column:span 2;background:linear-gradient(135deg,rgba(143,224,168,.14),rgba(255,255,255,.04))}"
    ".tile.warm{background:linear-gradient(135deg,rgba(242,169,59,.2),rgba(255,255,255,.04))}"
    ".tile.wide{grid-column:span 2}"
    # roles and sdg
    ".role{position:relative;min-height:22rem;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden;padding:0}"
    ".role img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}"
    ".role.front:after{content:'';position:absolute;inset:0;background:linear-gradient(0deg,rgba(7,20,14,.95) 0%,rgba(7,20,14,.3) 60%,rgba(7,20,14,0) 100%)}"
    ".role .rb{position:relative;z-index:2;padding:1.4rem}"
    ".role h3{font-size:1.5rem;margin-bottom:.35rem !important;color:#fff}.role p{margin:0;color:#DCEBE1;line-height:1.5}"
    ".sdg{padding:1.5rem}"
    ".sdgn{display:flex;align-items:center;gap:.8rem;margin-bottom:.9rem}"
    ".sdgn b{width:3.2rem;height:3.2rem;border-radius:14px;display:flex;align-items:center;justify-content:center;color:#fff;font-family:'Fredoka',sans-serif;font-size:1.6rem}"
    ".sdgn span{font-weight:700;color:#fff;line-height:1.2}"
    ".sdg p{color:var(--mute);line-height:1.6;margin:0}.sdg em{display:block;margin-top:.6rem;font-style:normal;color:#FFE2A8;font-size:.85rem}"
    ".fine{color:#7E9A89;font-size:.82rem;margin-top:1.4rem}"
    # band, about
    ".band{position:relative;display:grid;grid-template-columns:1.2fr .8fr;overflow:hidden;margin-top:5rem;padding:0}"
    ".band .bt{padding:2.6rem}"
    ".band .bigstat{font-family:'Fredoka',sans-serif;font-size:5.4rem;font-weight:600;line-height:1;background:linear-gradient(90deg,#FFC766,#F2A93B);"
    "-webkit-background-clip:text;background-clip:text;color:transparent}"
    ".band p{color:#DCEBE1;font-size:1.15rem;line-height:1.55;margin:.7rem 0 0}.band .src{color:#8FAE9B;font-size:.85rem}"
    ".band .im{position:relative;min-height:17rem}.band .im img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}"
    ".band .im:before{content:'';position:absolute;inset:0;z-index:1;background:linear-gradient(90deg,#0c241a 0%,rgba(12,36,26,0) 45%)}"
    ".about{display:grid;grid-template-columns:1.1fr .9fr;gap:2.4rem;align-items:center}"
    ".about .ph{position:relative}.about .ph img{width:100%;height:30rem;object-fit:cover;border-radius:28px;display:block;box-shadow:0 26px 50px rgba(0,0,0,.5)}"
    ".about .ph:before{content:'';position:absolute;inset:1.2rem -1rem -1rem 1.2rem;border-radius:28px;border:2px solid rgba(242,169,59,.6)}"
    ".about p{color:var(--mute);line-height:1.7;font-size:1.05rem}"
    ".prom{display:flex;gap:.9rem;align-items:flex-start;margin:1.1rem 0}.prom .tileic{margin:0;width:2.8rem;height:2.8rem;border-radius:14px}"
    ".prom b{display:block;color:#fff;font-size:1.05rem}.prom span{color:var(--mute);line-height:1.55}"
    ".datagrid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-top:1.4rem}"
    ".datagrid .tile{padding:1.2rem}.datagrid h3{font-size:1.05rem}.datagrid p{font-size:.95rem}"
    # contact
    ".cinfo{padding:2rem;height:100%;background:linear-gradient(135deg,rgba(143,224,168,.14),rgba(242,169,59,.08))}"
    ".cinfo h3{font-size:1.6rem;margin-bottom:.5rem !important;color:#fff}.cinfo p{color:#DCEBE1;line-height:1.6}"
    ".crow{display:flex;align-items:center;gap:.9rem;margin:1rem 0;color:#fff}.crow .tileic{margin:0;width:2.7rem;height:2.7rem;border-radius:14px}"
    # CTA and footer
    ".cta{position:relative;overflow:hidden;margin-top:5rem;padding:4rem 2rem;text-align:center;border-radius:30px;border:1px solid rgba(255,255,255,.12)}"
    ".cta img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0}"
    ".cta:before{content:'';position:absolute;inset:0;z-index:1;background:linear-gradient(135deg,rgba(7,20,14,.9),rgba(18,64,43,.72))}"
    ".cta>div{position:relative;z-index:2}"
    ".cta h2{font-size:2.6rem;margin-bottom:.5rem !important;color:#fff}.cta p{color:#DCEBE1;font-size:1.12rem;margin:0 0 1.4rem}"
    ".foot2{margin-top:4rem;margin-bottom:-1.2rem;background:#050E0A;border-top:1px solid rgba(255,255,255,.08);padding:3rem 0 1.4rem}"
    ".fgrid{display:grid;grid-template-columns:1.6fr 1fr 1fr 1.2fr;gap:2rem}"
    ".foot2 h4{font-family:'Fredoka',sans-serif;color:#F2A93B;font-weight:600;font-size:1.05rem;margin:0 0 .7rem;letter-spacing:.04em}"
    ".foot2 a{display:block;color:#DCEBE1;text-decoration:none;padding:.3rem 0;cursor:pointer}"
    ".foot2 a.brand{display:flex;padding:0}.foot2 a:hover{color:#F2A93B}"
    ".foot2 p{margin:.4rem 0;color:#8FAE9B;line-height:1.5}"
    ".fbot{display:flex;flex-wrap:wrap;justify-content:space-between;gap:.4rem 1.5rem;border-top:1px solid rgba(255,255,255,.1);margin-top:1.6rem;padding-top:1rem;font-size:.88rem;color:#8FAE9B}"
    ".ptitle{padding:6.2rem 0 .6rem;text-align:center}.ptitle h2{font-size:2.3rem;color:#fff}.ptitle p{color:var(--mute);margin:.4rem 0 0}"
    # Streamlit parts (log in, sign up, FAQ, contact form)
    "[data-testid='stVerticalBlockBorderWrapper']{background:#FFF8EA;border-radius:26px !important;border:0 !important;padding:1.2rem !important;box-shadow:0 24px 50px rgba(0,0,0,.45)}"
    "[data-testid='stExpander']{border:1px solid rgba(255,255,255,.12) !important;border-radius:18px !important;background:rgba(255,255,255,.05);"
    "margin-bottom:.6rem;overflow:hidden}"
    "[data-testid='stExpander'] summary{padding:.8rem 1rem}[data-testid='stExpander'] summary p{font-size:1.05rem}[data-testid='stExpander']{margin-left:1.2rem;margin-right:1.2rem}"
    "[data-testid='stHorizontalBlock']{padding:0 1.2rem}"
    "[data-testid='stExpander'] summary,[data-testid='stExpander'] summary *,[data-testid='stExpander'] p{color:#E8F1EA !important}"
    "[data-testid='stExpander'] summary{font-weight:600;font-size:1.05rem}"
    "[data-testid='stForm']{background:#FFF8EA;border:0 !important;border-radius:26px !important;padding:1.6rem !important;box-shadow:0 24px 50px rgba(0,0,0,.45)}"
    "[role='tab']{color:#C9DDD0 !important}[role='tab'][aria-selected='true']{color:#8FE0A8 !important}"
    "[data-testid='stWidgetLabel'] p,[data-testid='stRadio'] label p,[data-testid='stCaptionContainer'],[data-testid='stMarkdownContainer'] p,[data-testid='stMarkdownContainer'] li{color:#E8F1EA}"
    "[data-testid='stForm'] [data-testid='stMarkdownContainer'] p,[data-testid='stAlert'] p,[data-testid='stAlert'] li{color:#1B2B22}"
    "[data-testid='stForm'] [data-testid='stWidgetLabel'] p,[data-testid='stForm'] label p,[data-testid='stForm'] [data-testid='stCaptionContainer']{color:#1B2B22}"
    "[data-testid='stForm'] button p,[data-testid='stFormSubmitButton'] button p{color:#fff !important}"
    # interactive: tap or click to flip, tilt toward the pointer
    ".flipc{height:100%;perspective:1100px;cursor:pointer;outline-offset:5px;-webkit-tap-highlight-color:transparent}"
    ".flipc .fi{height:100%;display:grid;transform-style:preserve-3d;transition:transform .7s cubic-bezier(.2,.8,.2,1);"
    "transform:rotateX(var(--rx,0deg)) rotateY(calc(var(--ry,0deg) + var(--fl,0deg)))}"
    ".flipc.on{--fl:180deg}"
    ".flipc .front,.flipc .back{grid-area:1/1;backface-visibility:hidden;-webkit-backface-visibility:hidden;backdrop-filter:none;-webkit-backdrop-filter:none}"
    ".flipc .back{transform:rotateY(180deg);background:linear-gradient(135deg,#14452F,#0A2016);padding:1.7rem;display:flex;flex-direction:column;justify-content:center;overflow:hidden}"
    ".flipc .g:hover{transform:none}.flipc .back:hover{transform:rotateY(180deg)}"
    ".flipc:active .fi{filter:brightness(1.08)}"
    ".flipc .back h3{font-size:1.4rem;color:#fff;margin-bottom:.7rem !important}"
    ".flipc .back ul{list-style:none;padding:0;margin:0}.flipc .back li{display:flex;gap:.6rem;align-items:flex-start;padding:.35rem 0;color:#DCEBE1;line-height:1.45}"
    ".flipc .back li svg{color:#8FE0A8;margin-top:.15rem}"
    ".flipc .back .eg{color:#FFE2A8;font-style:italic;line-height:1.55;font-size:1.05rem;border-left:3px solid #F2A93B;padding-left:.9rem}"
    ".hint{display:inline-flex;align-items:center;gap:.4rem;margin-top:.8rem;font-size:.8rem;font-weight:700;color:#FFE2A8;letter-spacing:.04em}"
    ".step.front,.step.back{min-height:15rem}"
    ".g[data-tilt]{transition:transform .18s ease-out,border-color .25s,box-shadow .25s}"
    ".g[data-tilt]:hover{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateY(-5px)}"
    # motion
    "@keyframes rise{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:none}}"
    "@supports (animation-timeline:view()){.flipc,.tile,.about,.cinfo,.band,.cta,.sdg,.win,.stats{animation:rise both;animation-timeline:view();animation-range:entry 0% entry 35%}}"
    "@media (max-width:900px){.bento{grid-template-columns:1fr 1fr}.tile.photo{grid-column:span 2;grid-row:span 1;min-height:18rem}"
    ".tile.wideg,.tile.wide{grid-column:span 2}.datagrid{grid-template-columns:1fr 1fr}.split{grid-template-columns:1fr}}"
    "@media (max-width:760px){"
    ".topin{padding:.45rem .8rem}.nav a{padding:.5rem .55rem;font-size:.92rem}.brand .bn{display:none}.brand svg{width:2.4rem;height:2.4rem}"
    ".hero{padding-top:9.5rem}.hero .cols{grid-template-columns:1fr}.hero h1{font-size:2.6rem}.insight{margin:1rem 0 0;max-width:none}"
    ".hero .shade{background:linear-gradient(180deg,rgba(7,20,14,.7) 0%,rgba(7,20,14,.8) 100%)}.hero video{display:none}"
    ".stats{grid-template-columns:1fr 1fr;margin-top:1.6rem}"
    ".grid3,.bento,.datagrid{grid-template-columns:1fr}.tile.photo,.tile.wideg,.tile.wide{grid-column:auto}"
    ".sec{margin:3.4rem 0 1.2rem}.sec h2,.split h2{font-size:1.9rem}.cta h2{font-size:1.9rem}"
    ".band{grid-template-columns:1fr}.band .bt{padding:1.8rem 1.4rem}.band .bigstat{font-size:4rem}.band .im{min-height:12rem}"
    ".about{grid-template-columns:1fr}.about .ph img{height:20rem}.tiles3{grid-template-columns:1fr 1fr 1fr}"
    ".fgrid{grid-template-columns:1fr 1fr}}"
    "@media (prefers-reduced-motion:reduce){.hero video{display:none}.flipc .fi{transition:none}.tile,.about,.cinfo,.band,.cta,.sdg,.win,.stats{animation:none !important}}"
    "</style>"
)

# Lets the big buttons and the links open a view (Home, Log in, Sign up) and scroll to a section. If scripts are
# blocked the buttons do nothing. The page text is fixed; nothing typed is used here.
GOTO_JS = (
    "<script>(function(){var p=window.parent,d=p.document;if(p.__gotoReady)return;p.__gotoReady=true;"
    "var flip=function(f){f.classList.toggle('on')};"
    "d.addEventListener('click',function(e){var f=e.target.closest('.flipc');if(f){flip(f);return;}"
    "var a=e.target.closest('[data-goto]');if(!a)return;e.preventDefault();"
    "var want=a.getAttribute('data-goto'),sc=a.getAttribute('data-scroll');"
    "var t=[].slice.call(d.querySelectorAll('[role=tab]')).find(function(b){return b.innerText.trim()===want});"
    "var go=function(){var el=sc&&d.querySelector('[data-anchor=\"'+sc+'\"]');"
    "if(el){el.scrollIntoView({behavior:'smooth',block:'start'});return}"
    "var m=d.querySelector('[data-testid=stMain]');if(m)m.scrollTo({top:0,behavior:'smooth'});};"
    "if(t&&t.getAttribute('aria-selected')!=='true'){t.click();setTimeout(go,300);}else{go();}},true);"
    "d.addEventListener('keydown',function(e){var f=e.target.classList&&e.target.classList.contains('flipc')&&e.target;"
    "if(f&&(e.key==='Enter'||e.key===' ')){e.preventDefault();flip(f);}},true);"
    "var raf=0,reduce=p.matchMedia&&p.matchMedia('(prefers-reduced-motion: reduce)').matches;"
    "d.addEventListener('pointermove',function(e){if(reduce||e.pointerType==='touch'||!e.target.closest)return;"
    "var t=e.target.closest('[data-tilt]');if(!t)return;var r=t.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;"
    "cancelAnimationFrame(raf);raf=requestAnimationFrame(function(){t.style.setProperty('--ry',(x*9).toFixed(2)+'deg');t.style.setProperty('--rx',(-y*9).toFixed(2)+'deg');});},true);"
    "d.addEventListener('pointerout',function(e){var t=e.target.closest&&e.target.closest('[data-tilt]');"
    "if(t&&!t.contains(e.relatedTarget)){t.style.setProperty('--rx','0deg');t.style.setProperty('--ry','0deg');}},true);"
    "})();</script>"
)

LOGO_SVG = (
    '<svg viewBox="0 0 64 64" role="img" aria-label="Maziwa Plus logo: a friendly cow chewing grass" xmlns="http://www.w3.org/2000/svg"> <defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2A6F46"/><stop offset="1" stop-color="#0F3A26"/></linearGradient></defs> <circle cx="32" cy="32" r="30" fill="url(#lg)" stroke="#F2A93B" stroke-width="3"/> <g stroke-linecap="round" fill="none"><path d="M23 19Q19 11 14.5 12.5" stroke="#F2A93B" stroke-width="3"/><path d="M41 19Q45 11 49.5 12.5" stroke="#F2A93B" stroke-width="3"/></g> <ellipse cx="14" cy="24" rx="6.5" ry="3.8" transform="rotate(-28 14 24)" fill="#C9772B"/><ellipse cx="14.5" cy="24" rx="3.6" ry="1.9" transform="rotate(-28 14.5 24)" fill="#F2B27A"/> <ellipse cx="50" cy="24" rx="6.5" ry="3.8" transform="rotate(28 50 24)" fill="#C9772B"/><ellipse cx="49.5" cy="24" rx="3.6" ry="1.9" transform="rotate(28 49.5 24)" fill="#F2B27A"/> <path d="M21 19Q32 14 43 19Q47 29 44.5 39Q42 51 32 53Q22 51 19.5 39Q17 29 21 19Z" fill="#FFF8EA"/> <path d="M21.5 20Q27 17.5 30 21Q27 30 21 31Q19.5 25 21.5 20Z" fill="#7A3E16"/> <circle cx="25.5" cy="27" r="2" fill="#1B2B22"/><circle cx="26.1" cy="26.3" r=".6" fill="#fff"/> <circle cx="38.5" cy="27" r="2" fill="#1B2B22"/><circle cx="39.1" cy="26.3" r=".6" fill="#fff"/> <path d="M29.5 19Q32 15.5 34.5 19" fill="none" stroke="#E6CFA0" stroke-width="2" stroke-linecap="round"/> <ellipse cx="32" cy="43.5" rx="10.5" ry="7.5" fill="#F4B9A6"/> <ellipse cx="28.3" cy="41.5" rx="1.5" ry="2.1" fill="#B35F52"/><ellipse cx="35.7" cy="41.5" rx="1.5" ry="2.1" fill="#B35F52"/> <path d="M26.5 47Q32 50.5 37.5 47" fill="none" stroke="#A8574B" stroke-width="1.5" stroke-linecap="round"/> <g fill="none" stroke-linecap="round"><path d="M36.5 47.6Q45 46 53 39" stroke="#8FE0A8" stroke-width="2.6"/><path d="M36.5 48.4Q46 50.5 55 47" stroke="#4DB878" stroke-width="2.6"/><path d="M36.8 48Q43 44.5 49 43" stroke="#B5F0C6" stroke-width="2"/></g> </svg>'
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


def _nav_link(label, anchor=None):
    sc = f' data-scroll="{anchor}"' if anchor else ""
    return f'<a href="#" data-goto="Home"{sc}>{label}</a>'


def render_header():
    """Frosted top bar with the logo and the page links. Log in and Sign up have their own big buttons below."""
    st.markdown(PUBLIC_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="land"><div class="topbar"><div class="topin">{_brand()}<nav class="nav" aria-label="Main">'
        + _nav_link("How it works", "how")
        + _nav_link("About us", "about")
        + _nav_link("Contact us", "contact")
        + "</nav></div></div></div>",
        unsafe_allow_html=True,
    )
    _run_script(GOTO_JS)


def render_footer():
    email, phone = os.environ.get("CONTACT_EMAIL", "").strip(), os.environ.get("CONTACT_PHONE", "").strip()
    lines = "".join(f"<p>{html.escape(x)}</p>" for x in (email, phone) if x) or "<p>Send us a message and we will reply.</p>"
    st.markdown(
        f'<div class="land"><footer class="bleed foot2"><div class="wrap"><div class="fgrid"><div>{_brand()}'
        "<p>Know what your feed is worth.</p><p>Karibu. A tool for farmers, vets and milk buyers.</p></div>"
        '<div><h4>Explore</h4><a href="#" data-goto="Home">Home</a>' + _nav_link("How it works", "how")
        + _nav_link("About us", "about") + "</div>"
        '<div><h4>Get started</h4><a href="#" data-goto="Sign up">Create an account</a><a href="#" data-goto="Log in">Log in</a></div>'
        f"<div><h4>Contact</h4>{lines}" + _nav_link("Write to us", "contact") + "</div></div>"
        '<div class="fbot"><span>© 2026 HustleWindow</span>'
        "<span>Built for the FNB App of the Year hackathon. Demo data is simulated.</span></div></div></footer></div>",
        unsafe_allow_html=True,
    )


def page_title(title, text):
    st.markdown(f'<div class="land"><div class="ptitle"><h2>{title}</h2><p>{text}</p></div></div>', unsafe_allow_html=True)


def _hero():
    has_video = os.path.exists(HERO_VIDEO)
    if has_video:
        bg = (
            f'<video class="bg" autoplay muted loop playsinline preload="metadata" poster="{IMG}hero-farm.jpg" aria-hidden="true">'
            '<source src="app/static/hero.mp4" type="video/mp4"></video>'
        )
    else:
        bg = f'<img class="bg" src="{IMG}hero-farm.jpg" alt="Cows grazing in a misty pasture at sunrise, with a farmhouse behind">'
    txt = (
        '<div><div class="pill"><i></i>Karibu · built for Kenyan dairy farmers</div>'
        "<h1>Know what your milk <em>really earns</em>.</h1>"
        '<p class="lead">Feed is the biggest cost on a dairy farm. Record your day, see what each feed pays back, '
        "and reach your vet and your milk route from one phone.</p>"
        f'<div><a class="btn main" href="#" data-goto="Sign up">Get started {icon("check", "1.2rem")}</a>'
        '<a class="btn ghost" href="#" data-goto="Log in">I have an account</a></div></div>'
    )
    insight = (
        f'<div class="g insight" data-tilt><div class="ih"><span>{icon("leaf", "1.2rem")} Farm snapshot</span><em>Example data</em></div>'
        '<div class="irow"><div class="l"><span>Milk today</span><b>38 L</b></div><div class="bar"><i style="width:76%"></i></div></div>'
        '<div class="irow"><div class="l"><span>Feed cost per litre</span><b>KES 17</b></div><div class="bar am"><i style="width:40%"></i></div></div>'
        '<div class="irow"><div class="l"><span>Left after feed, per litre</span><b>KES 26</b></div><div class="bar"><i style="width:62%"></i></div></div>'
        "</div>"
    )
    stats = [
        ("users", "3 views", "farmer, vet, milk buyer"),
        ("calendar", "14 days", "of records before advice"),
        ("phone", "Web + SMS", "reaches any phone"),
        ("trash", "Delete anytime", "your data, your call"),
    ]
    strip = "".join(
        f'<div class="stat"><div class="tileic{" amb" if i % 2 else ""}">{icon(ic, "1.3rem")}</div><div><b>{t}</b><span>{x}</span></div></div>'
        for i, (ic, t, x) in enumerate(stats)
    )
    return (
        f'<section class="bleed hero">{bg}<div class="shade"></div><div class="wrap"><div class="cols">{txt}{insight}</div>'
        f'<div class="g stats">{strip}</div></div></section>'
    )


def _head(eyebrow, title, sub="", anchor=None):
    a = f' data-anchor="{anchor}"' if anchor else ""
    s = f'<p class="sub">{sub}</p>' if sub else ""
    return f'<div class="sec"{a}><div class="eyebrow">{eyebrow}</div><h2>{title}</h2>{s}</div>'


def _flip(front, back, label):
    return (
        f'<div class="flipc" tabindex="0" role="button" aria-label="{label}" data-tilt><div class="fi">{front}{back}</div></div>'
    )


def _steps():
    items = [
        ("notebook", "Log your day", "Record the milk and what you fed, in the buckets, bags or bales you really use.",
         "3 buckets of napier mixed with hay, one 50 kg bag of dairy meal, and 38 litres of milk. A minute, and it is done."),
        ("cross", "Ask and book", "Request the vet, choose AI semen from your route vet's price list, book vaccination days.",
         "Tap Ask the vet, pick the day you want, and choose semen from your own route vet's list. The vet sees it straight away."),
        ("bell", "Hear what matters", "Get an outbreak alert, or one short SMS about one feed, only when the records are clear.",
         "Maziwa Plus: OUTBREAK: Foot and mouth near Tigoni. Keep cows in. Call your vet."),
    ]
    out = ""
    for i, (ic, t, p, eg) in enumerate(items, 1):
        front = (f'<div class="g step front"><div class="num">{i}</div><div class="tileic{" amb" if i == 2 else ""}">{icon(ic)}</div>'
                 f'<h3>{t}</h3><p>{p}</p><span class="hint">{icon("check", "0.9rem")} Tap for an example</span></div>')
        back = f'<div class="g step back"><h3>For example</h3><p class="eg">{eg}</p><span class="hint">Tap to flip back</span></div>'
        out += _flip(front, back, f"{t}: tap to see an example")
    return out


def _dash():
    bars = [40, 55, 48, 62, 58, 70, 66, 74, 69, 78, 72, 80, 76, 84]
    chart = "".join(f'<i class="{"a" if i == len(bars) - 1 else ""}" style="height:{h}%"></i>' for i, h in enumerate(bars))
    acts = [
        ("cross", "Vet visit requested", "Thu"),
        ("notebook", "Dairy meal, 50 kg bag logged", "Today"),
        ("calendar", "Vaccination day booked", "Mon"),
    ]
    acts_html = "".join(f'<div class="act">{icon(ic, "1.1rem")}<span>{t}</span><time>{w}</time></div>' for ic, t, w in acts)
    left = (
        '<div><div class="eyebrow">Your farm at a glance</div><h2>Records in, decisions out</h2>'
        "<p>Everything you log lands on one clear page: the milk, the feed, the vet and the days that matter.</p>"
        '<ul class="checks">'
        + "".join(f"<li>{icon('check', '1.2rem')}{t}</li>" for t in (
            "Milk by day, with a chart that moves", "Feed in buckets, bags or bales", "Vet requests and visit status", "Vaccination days for your route"))
        + f'</ul><a class="btn main" href="#" data-goto="Sign up">Create my account {icon("check", "1.2rem")}</a></div>'
    )
    right = (
        '<div class="g win" data-tilt><div class="bar0"><i></i><i></i><i></i><span style="margin-left:.4rem">Farm overview</span><em>Example data</em></div>'
        '<div class="tiles3"><div class="mini"><span>Milk today</span><b>38 <small>L</small></b></div>'
        '<div class="mini"><span>Feed cost</span><b><small>KES</small> 646</b></div>'
        '<div class="mini"><span>Left after feed</span><b><small>KES</small> 988</b></div></div>'
        f'<div class="chart">{chart}</div><div class="acts">{acts_html}</div></div>'
    )
    return f'<div class="split">{left}{right}</div>'


def _tile(ic, title, text, cls="", amb=False):
    return f'<div class="g tile {cls}" data-tilt><div class="tileic{" amb" if amb else ""}">{icon(ic)}</div><h3>{title}</h3><p>{text}</p></div>'


def _bento():
    photo = (
        f'<div class="g tile photo"><img src="{IMG}farmer-feeding.jpg" alt="A farmer hand-feeding fresh grass to a brown cow" loading="lazy">'
        f'<div><div class="tileic amb">{icon("drop")}</div><h3>Log your day in the buckets you already use</h3>'
        "<p>Feeding a truckload of napier, shredded and mixed with hay? Record it as 20-litre buckets, 50 kg bags or bales. "
        "Weigh one full bucket once and the app does the sums. Bought or grown on your own land, both count.</p></div></div>"
    )
    return (
        '<div class="bento">' + photo
        + _tile("trend", "Advice that shows its working",
                "After 14 full days of records, the app compares what each feed costs with what the cows gave back. "
                "If the evidence is thin it says so, and does not guess.", "wideg")
        + _tile("cross", "Ask your vet", "Request a visit and pick AI semen from your route vet's own price list.")
        + _tile("calendar", "Vaccination days", "Book ahead and get a reminder, with one list for the whole route.", "warm", amb=True)
        + _tile("shield", "Private by default", "A farmer sees only their own farm. A vet sees only the farms on their route.")
        + _tile("coins", "Know your margin", "Costs in shillings per litre, and what is left after feed and semen.", amb=True)
        + _tile("phone", "Made for a phone", "Big buttons, short pages, and a get-started list that tells you the next step.", "wide")
        + "</div>"
    )


def _roles():
    items = [
        ("farmer-milking.jpg", "A farmer in a straw hat milking a cow into a bucket in a green pasture", "Farmers",
         "See what is left after feed and semen, keep herd records, and reach your vet without phone tag.",
         ["Log milk and feed every day", "See your margin per litre", "Ask the vet and book vaccination days", "Get alerts by SMS"], "center 55%"),
        ("vet-check.jpg", "A vet listening to a cow's side with a stethoscope", "Vets",
         "Open one sheet with today's farms, each visit and what to carry. Keep your own priced semen list.",
         ["See today's farms on one sheet", "Keep your own semen price list", "Mark visits as done", "See each request from ask to done"], "center 35%"),
        ("milk-can.jpg", "Fresh milk being poured into a milk can", "Milk buyers",
         "Set up routes, send alerts to the farms that need them, and see which visits were attended.",
         ["Approve farmers and vets", "Set up routes and route admins", "Send outbreak alerts to chosen routes", "See which visits were attended"], "center"),
    ]
    out = ""
    for f, a, t, p, bullets, pos in items:
        front = (f'<div class="g role front"><img src="{IMG}{f}" alt="{a}" loading="lazy" style="object-position:{pos}"><div class="rb">'
                 f'<h3>{t}</h3><p>{p}</p><span class="hint">{icon("check", "0.9rem")} Tap to see what you can do</span></div></div>')
        lis = "".join(f"<li>{icon('check', '1.1rem')}{b}</li>" for b in bullets)
        back = f'<div class="g role back"><h3>{t}</h3><ul>{lis}</ul><span class="hint">Tap to flip back</span></div>'
        out += _flip(front, back, f"{t}: tap to see what you can do")
    return out


def _sdgs():
    items = [
        ("2", "#DDA63A", "Zero Hunger", "Target 2.3: raise the productivity and incomes of small-scale food producers.",
         "We help smallholder dairy farms feed their cows by evidence, not by feel."),
        ("8", "#A21942", "Decent Work and Economic Growth", "Target 8.3: support small enterprises and productive activity.",
         "A farm's margin becomes visible, and the vet and the milk route run on facts."),
        ("9", "#FD6925", "Industry, Innovation and Infrastructure", "Target 9.c: widen access to information and communication technology.",
         "It works on the web and by plain SMS, so it reaches phones of every kind."),
    ]
    cards = "".join(
        f'<div class="g sdg"><div class="sdgn"><b style="background:{c}">{n}</b><span>{t}</span></div><p>{x}</p><em>{y}</em></div>'
        for n, c, t, x, y in items
    )
    return (
        '<div class="land"><div class="wrap">'
        + _head("Our goals", "Built with the Sustainable Development Goals in mind",
                "These are the goals we aim to contribute to. They are our aims, not measured results yet: the pilot is how we will find out.")
        + f'<div class="grid3">{cards}</div>'
        '<p class="fine">Goal names and numbers belong to the United Nations. This page is not endorsed by the UN.</p></div></div>'
    )


def _about_html():
    team = html.escape(os.environ.get("ABOUT_TEAM", "").strip())
    team_html = f"<p>{team}</p>" if team else ""
    prom = [
        ("check", "Honest by design", "Advice appears only after 14 full days of records and when even the cautious estimate pays."),
        ("shield", "Private by default", "Nobody can sign up as an admin, and every farm stays private to its own people."),
        ("trash", "Yours to delete", "Delete your account and every record on it at any time, from My account."),
    ]
    prom_html = "".join(
        f'<div class="prom"><div class="tileic{" amb" if i == 1 else ""}">{icon(ic)}</div><div><b>{t}</b><span>{x}</span></div></div>'
        for i, (ic, t, x) in enumerate(prom)
    )
    data = [
        ("notebook", "What we keep", "Your name, phone or email, and the farm records you enter: milk, feed, herd, vet requests."),
        ("users", "Who sees it", "You, the vet on your route, and the milk buyer's admins."),
        ("phone", "SMS", "Sent through Africa's Talking. In this demo it reaches a simulator, not real phones."),
        ("leaf", "AI", "Claude only rewords advice the app has already worked out. It never sees your name or phone."),
    ]
    data_html = "".join(_tile(ic, t, x, amb=(i % 2 == 1)) for i, (ic, t, x) in enumerate(data))
    return (
        '<div class="land"><div class="wrap">' + _head("About us", f"Why we built {APP_NAME}", anchor="about")
        + '<div class="about"><div>'
        "<p>We are HustleWindow, a team building tools for smallholder dairy farmers in Kenya. Most farms buy feed by feel and "
        "arrange vets and vaccination by phone call. We wanted one place where the farmer, the route vet and the milk buyer "
        f"see the same facts.</p>{team_html}{prom_html}</div>"
        f'<div class="ph"><img src="{IMG}trough.jpg" alt="Cows feeding at a wooden trough at sunset" loading="lazy"></div></div>'
        '<div class="sec" style="margin:2.6rem 0 0"><h2 style="font-size:1.7rem">Your data</h2></div>'
        f'<div class="datagrid">{data_html}</div></div></div>'
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


def _contact_info_html():
    email, phone = os.environ.get("CONTACT_EMAIL", "").strip(), os.environ.get("CONTACT_PHONE", "").strip()
    rows = ""
    if email:
        rows += f'<div class="crow"><div class="tileic amb">{icon("mail")}</div><div>{html.escape(email)}</div></div>'
    if phone:
        rows += f'<div class="crow"><div class="tileic amb">{icon("tel")}</div><div>{html.escape(phone)}</div></div>'
    rows += f'<div class="crow"><div class="tileic amb">{icon("pin")}</div><div>Nairobi, Kenya</div></div>'
    return (
        '<div class="land"><div class="g cinfo"><h3>Talk to us</h3>'
        "<p>Questions, a problem, or want to bring your milk route on? Write to us and we will reply to the contact you give.</p>"
        f"{rows}</div></div>"
    )


def _contact_form():
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


def render_home():
    """The whole public page, top to bottom, on one dark background."""
    st.markdown('<div class="land">' + _hero() + "</div>", unsafe_allow_html=True)
    st.markdown(
        '<div class="land"><div class="wrap">' + _head("How it works", "Three steps, a few minutes a day", anchor="how")
        + f'<div class="grid3">{_steps()}</div>' + _dash()
        + _head("What you get", "Everything a dairy farm runs on, in one place", "Built around the way smallholders really feed and farm.")
        + _bento()
        + '<div class="g band"><div class="bt"><div class="bigstat">43–58%</div>'
        "<p>of what it costs to make a litre of milk is feed, and most farms buy it by feel. "
        "We help each farm see which feed pays on its own cows.</p>"
        '<p class="src">Source: Tegemeo Institute and Kenya Dairy Board cost study (2014 data).</p></div>'
        f'<div class="im"><img src="{IMG}bottling.jpg" alt="Milk being filled into clear bottles" loading="lazy"></div></div>'
        + _head("Who it is for", "Built for every person on the route")
        + f'<div class="grid3">{_roles()}</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(_sdgs(), unsafe_allow_html=True)
    st.markdown(_about_html(), unsafe_allow_html=True)
    st.markdown('<div class="land"><div class="wrap">' + _head("Questions", "Before you sign up") + "</div></div>", unsafe_allow_html=True)
    for q, a in FAQ:
        with st.expander(q):
            st.write(a)
    st.markdown('<div class="land"><div class="wrap">' + _head("Contact us", "We would love to hear from you", anchor="contact") + "</div></div>", unsafe_allow_html=True)
    left, right = st.columns([5, 6], gap="large")
    with left:
        st.markdown(_contact_info_html(), unsafe_allow_html=True)
    with right:
        _contact_form()
    st.markdown(
        '<div class="land"><div class="wrap"><div class="cta"><img src="' + IMG + 'farmer-feeding.jpg" alt="" loading="lazy"><div>'
        "<h2>Ready to see what your feed is worth?</h2>"
        "<p>Sign up takes a minute. Farmers, vets and milk-buyer admins each get their own view.</p>"
        f'<a class="btn main" href="#" data-goto="Sign up">Create my account {icon("check", "1.2rem")}</a>'
        '<a class="btn ghost" href="#" data-goto="Log in">Log in</a></div></div></div></div>',
        unsafe_allow_html=True,
    )
    render_footer()
