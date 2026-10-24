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
    ":root{--deep:#0A2016;--forest:#12402B;--leaf:#1F5A3A;--amber:#F2A93B;--amber2:#FFC766;--cream:#FFF8EA;--ink:#1B2B22;--mute:#4A5A50}"
    ".land{font-family:'DM Sans',system-ui,sans-serif;color:var(--ink)}"
    ".land *{box-sizing:border-box}"
    ".land h1,.land h2,.land h3{font-family:'Fredoka','DM Sans',sans-serif;font-weight:600;color:inherit;margin:0;padding:0;letter-spacing:-.01em}"
    ".land svg{flex:none}"
    "[data-anchor]{scroll-margin-top:5.5rem}"
    # buttons
    ".land a.btn{display:inline-flex;align-items:center;gap:.5rem;border-radius:999px;padding:.9rem 1.6rem;font-weight:700;"
    "text-decoration:none;margin:.25rem .6rem .25rem 0;cursor:pointer;min-height:3rem;transition:transform .18s,box-shadow .18s,background .18s}"
    ".land a.btn:hover{transform:translateY(-2px)}"
    ".land a.btn.main{background:linear-gradient(135deg,#FFC766,#F2A93B);color:#0A2016;box-shadow:0 10px 24px rgba(242,169,59,.38)}"
    ".land a.btn.main:hover{box-shadow:0 14px 30px rgba(242,169,59,.5)}"
    ".land a.btn.ghost{border:2px solid rgba(255,248,234,.7);color:#FFF8EA;background:rgba(255,248,234,.06)}"
    ".land a.btn.ghost:hover{background:rgba(255,248,234,.16)}"
    # top bar (fixed, frosted)
    ".topbar{position:fixed;top:0;left:0;right:0;z-index:1000;background:rgba(255,248,234,.8);backdrop-filter:blur(16px);"
    "-webkit-backdrop-filter:blur(16px);box-shadow:0 1px 0 rgba(15,46,32,.08),0 10px 30px rgba(15,46,32,.06)}"
    ".topin{max-width:1120px;margin:0 auto;padding:.55rem 1.2rem;display:flex;align-items:center;justify-content:space-between;gap:1rem}"
    ".topbar a{text-decoration:none;cursor:pointer}"
    ".brand{display:flex;align-items:center;gap:.65rem;color:#0A2016}"
    ".brand svg{width:2.7rem;height:2.7rem}"
    ".brand .bn{font-family:'Fredoka',sans-serif;font-weight:600;font-size:1.65rem;line-height:1;color:#0A2016}"
    ".brand .bn b{color:#D98A0B;font-weight:600}"
    ".nav{display:flex;gap:.2rem}"
    ".nav a{white-space:nowrap;color:#1B2B22;font-weight:500;font-size:1.02rem;padding:.6rem 1rem;border-radius:999px}"
    ".nav a:hover{background:rgba(31,90,58,.12);color:#0A2016}"
    # hero
    ".hero{position:relative;display:grid;grid-template-columns:1.1fr .9fr;gap:1rem;border-radius:32px;overflow:hidden;color:#FFF8EA;"
    "background:radial-gradient(60% 70% at 88% 8%,rgba(242,169,59,.38),transparent 62%),radial-gradient(50% 60% at 0% 100%,rgba(75,160,110,.28),transparent 60%),"
    "linear-gradient(135deg,#0A2016 0%,#12402B 62%,#1B5A3B 100%);box-shadow:0 30px 60px rgba(10,32,22,.35)}"
    ".hero .txt{position:relative;z-index:2;padding:3.4rem 2.6rem;display:flex;flex-direction:column;justify-content:center}"
    ".pill{display:inline-flex;align-items:center;gap:.5rem;align-self:flex-start;background:rgba(255,248,234,.1);border:1px solid rgba(255,248,234,.22);"
    "border-radius:999px;padding:.4rem .9rem;font-size:.88rem;color:#FFE2A8;font-weight:500}"
    ".pill i{width:.55rem;height:.55rem;border-radius:50%;background:var(--amber);box-shadow:0 0 0 4px rgba(242,169,59,.25)}"
    ".hero h1{font-size:3.5rem;line-height:1.04;margin:1rem 0 1rem !important}"
    ".hero h1 em{font-style:normal;background:linear-gradient(90deg,#FFC766,#F2A93B);-webkit-background-clip:text;background-clip:text;color:transparent}"
    ".hero p.lead{font-size:1.2rem;line-height:1.55;color:#DDEBE1;max-width:34rem;margin:0 0 1.5rem}"
    ".hero .stage{position:relative;padding:2rem 2rem 2rem 0;display:flex;align-items:center;justify-content:center}"
    ".hero .arch{position:relative;width:100%;max-width:21rem;height:27rem;border-radius:999px 999px 28px 28px;overflow:hidden;"
    "border:6px solid rgba(255,248,234,.14);box-shadow:0 30px 60px rgba(0,0,0,.45),0 0 80px rgba(242,169,59,.22)}"
    ".hero .arch img{width:100%;height:100%;object-fit:cover;object-position:center 35%;display:block}"
    ".chip{position:absolute;z-index:3;display:flex;align-items:center;gap:.7rem;padding:.65rem .95rem;border-radius:18px;color:#FFF8EA;"
    "background:rgba(10,32,22,.55);border:1px solid rgba(255,248,234,.22);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);"
    "box-shadow:0 14px 30px rgba(0,0,0,.3);animation:floaty 6s ease-in-out infinite}"
    ".chip .ic{width:2.3rem;height:2.3rem;border-radius:12px;display:flex;align-items:center;justify-content:center;"
    "background:linear-gradient(135deg,#FFC766,#F2A93B);color:#0A2016}"
    ".chip b{display:block;font-size:.95rem}.chip span{font-size:.8rem;color:#CFE3D6}"
    ".chip.c1{left:-.5rem;top:18%}.chip.c2{right:.6rem;top:44%;animation-delay:-2s}.chip.c3{left:.4rem;bottom:9%;animation-delay:-4s}"
    ".hero video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:0}"
    ".hero.vid{display:block}"
    ".hero.vid:before{content:'';position:absolute;inset:0;z-index:1;"
    "background:linear-gradient(90deg,rgba(10,32,22,.93) 0%,rgba(10,32,22,.72) 55%,rgba(10,32,22,.3) 100%)}"
    ".hero.vid .txt{max-width:46rem}"
    # trust strip
    ".trust{display:flex;flex-wrap:wrap;gap:.6rem;justify-content:center;padding:1.3rem 0 .2rem}"
    ".trust span{display:inline-flex;align-items:center;gap:.5rem;background:#fff;border:1px solid #EADFC4;border-radius:999px;"
    "padding:.5rem 1rem;color:#2F4237;font-weight:500;box-shadow:0 4px 12px rgba(15,46,32,.06)}"
    ".trust svg{color:#1F5A3A}"
    # sections
    ".sec{margin:4.2rem 0 1.4rem}"
    ".eyebrow{display:inline-flex;align-items:center;gap:.5rem;color:#1F5A3A;font-weight:700;letter-spacing:.12em;text-transform:uppercase;font-size:.8rem}"
    ".eyebrow:before{content:'';width:1.6rem;height:2px;background:var(--amber)}"
    ".sec h2{font-size:2.4rem;line-height:1.12;margin:.5rem 0 .5rem !important;color:#0A2016}"
    ".sec p.sub{color:var(--mute);font-size:1.08rem;max-width:40rem;line-height:1.55;margin:0}"
    ".grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:1.2rem}"
    ".step{position:relative;background:#fff;border:1px solid #EADFC4;border-radius:26px;padding:1.6rem;box-shadow:0 12px 30px rgba(15,46,32,.08);"
    "transition:transform .25s,box-shadow .25s}"
    ".step:hover,.tile:hover,.role:hover{transform:translateY(-6px);box-shadow:0 22px 44px rgba(15,46,32,.16)}"
    ".tileic{flex:none;width:3.2rem;height:3.2rem;border-radius:16px;display:flex;align-items:center;justify-content:center;color:#FFF8EA;"
    "background:linear-gradient(135deg,#2A6F46,#12402B);box-shadow:0 8px 18px rgba(31,90,58,.35);margin-bottom:1rem}"
    ".tileic.amb{background:linear-gradient(135deg,#FFC766,#F2A93B);color:#0A2016;box-shadow:0 8px 18px rgba(242,169,59,.4)}"
    ".step .num{position:absolute;right:1.3rem;top:.9rem;font-family:'Fredoka',sans-serif;font-size:3.4rem;font-weight:600;color:#F2E7C9;line-height:1}"
    ".step h3,.tile h3{font-size:1.3rem;margin-bottom:.4rem !important;color:#0A2016}"
    ".step p,.tile p{color:var(--mute);margin:0;line-height:1.55}"
    # bento
    ".bento{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:minmax(11rem,auto);gap:1.2rem}"
    ".tile{position:relative;border-radius:26px;padding:1.5rem;background:#fff;border:1px solid #EADFC4;box-shadow:0 12px 30px rgba(15,46,32,.08);"
    "transition:transform .25s,box-shadow .25s;overflow:hidden}"
    ".tile.photo{grid-column:span 2;grid-row:span 2;color:#FFF8EA;border:0;display:flex;flex-direction:column;justify-content:flex-end;min-height:24rem}"
    ".tile.photo img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}"
    ".tile.photo:after{content:'';position:absolute;inset:0;background:linear-gradient(0deg,rgba(10,32,22,.92) 0%,rgba(10,32,22,.35) 55%,rgba(10,32,22,0) 100%)}"
    ".tile.photo>div{position:relative;z-index:2}"
    ".tile.photo h3,.tile.dark h3{color:#FFF8EA}.tile.photo p,.tile.dark p{color:#DDEBE1}"
    ".tile.dark{grid-column:span 2;background:linear-gradient(135deg,#12402B,#0A2016);border:0;color:#FFF8EA}"
    ".tile.warm{background:linear-gradient(135deg,#FFF1D2,#FFE2A8);border-color:#F2D391}"
    ".tile.wide{grid-column:span 2}"
    # roles
    ".role{position:relative;border-radius:26px;overflow:hidden;min-height:20rem;display:flex;flex-direction:column;justify-content:flex-end;"
    "color:#FFF8EA;box-shadow:0 12px 30px rgba(15,46,32,.14);transition:transform .25s,box-shadow .25s}"
    ".role img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}"
    ".role:after{content:'';position:absolute;inset:0;background:linear-gradient(0deg,rgba(10,32,22,.94) 0%,rgba(10,32,22,.3) 60%,rgba(10,32,22,0) 100%)}"
    ".role .rb{position:relative;z-index:2;padding:1.4rem}"
    ".role h3{font-size:1.5rem;margin-bottom:.35rem !important}.role p{margin:0;color:#DDEBE1;line-height:1.5}"
    # stat band
    ".band{position:relative;display:grid;grid-template-columns:1.2fr .8fr;border-radius:32px;overflow:hidden;color:#FFF8EA;margin:4rem 0 0;"
    "background:radial-gradient(60% 90% at 100% 0%,rgba(242,169,59,.3),transparent 60%),linear-gradient(135deg,#0A2016,#12402B);box-shadow:0 26px 50px rgba(10,32,22,.3)}"
    ".band .bt{padding:2.6rem 2.6rem}"
    ".band .bigstat{font-family:'Fredoka',sans-serif;font-size:5.4rem;font-weight:600;line-height:1;background:linear-gradient(90deg,#FFC766,#F2A93B);"
    "-webkit-background-clip:text;background-clip:text;color:transparent}"
    ".band p{color:#DDEBE1;font-size:1.15rem;line-height:1.55;margin:.7rem 0 0}.band .src{color:#9FBFAB;font-size:.85rem}"
    ".band .im{position:relative;min-height:17rem}.band .im img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}"
    ".band .im:before{content:'';position:absolute;inset:0;z-index:1;background:linear-gradient(90deg,#12402B 0%,rgba(18,64,43,0) 40%)}"
    # about
    ".about{display:grid;grid-template-columns:1.1fr .9fr;gap:2.4rem;align-items:center}"
    ".about .ph{position:relative}.about .ph img{width:100%;height:30rem;object-fit:cover;border-radius:30px;display:block;box-shadow:0 26px 50px rgba(10,32,22,.25)}"
    ".about .ph:before{content:'';position:absolute;inset:1.2rem -1rem -1rem 1.2rem;border-radius:30px;border:2px solid var(--amber);z-index:-1}"
    ".about p{color:var(--mute);line-height:1.65;font-size:1.05rem}"
    ".prom{display:flex;gap:.9rem;align-items:flex-start;margin:1rem 0}.prom .tileic{margin:0;width:2.8rem;height:2.8rem;border-radius:14px}"
    ".prom b{display:block;color:#0A2016;font-size:1.05rem}.prom span{color:var(--mute);line-height:1.5}"
    ".datagrid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-top:1.6rem}"
    ".datagrid .tile{padding:1.2rem}.datagrid h3{font-size:1.05rem}.datagrid p{font-size:.95rem}"
    # contact
    ".cinfo{background:radial-gradient(70% 70% at 100% 0%,rgba(242,169,59,.28),transparent 60%),linear-gradient(135deg,#0A2016,#12402B);color:#FFF8EA;"
    "border-radius:28px;padding:2rem;height:100%;box-shadow:0 20px 44px rgba(10,32,22,.28)}"
    ".cinfo h3{font-size:1.6rem;margin-bottom:.5rem !important}.cinfo p{color:#DDEBE1;line-height:1.55}"
    ".crow{display:flex;align-items:center;gap:.9rem;margin:1rem 0;color:#FFF8EA}"
    ".crow .tileic{margin:0;width:2.7rem;height:2.7rem;border-radius:14px}"
    # CTA + footer
    ".cta{position:relative;overflow:hidden;background:radial-gradient(50% 90% at 50% 0%,rgba(242,169,59,.3),transparent 65%),linear-gradient(135deg,#0A2016,#1F5A3A);"
    "color:#FFF8EA;border-radius:32px;padding:3.2rem 2rem;text-align:center;margin:4rem 0 0;box-shadow:0 26px 50px rgba(10,32,22,.3)}"
    ".cta h2{font-size:2.6rem;margin-bottom:.5rem !important}.cta p{color:#DDEBE1;font-size:1.12rem;margin:0 0 1.4rem}"
    ".foot2{background:#0A2016;color:#E8F1EA;border-radius:32px 32px 0 0;padding:2.6rem 2.6rem 1.3rem;margin:2.5rem 0 0}"
    ".fgrid{display:grid;grid-template-columns:1.6fr 1fr 1fr 1.2fr;gap:2rem}"
    ".foot2 h4{font-family:'Fredoka',sans-serif;color:#F2A93B;font-weight:600;font-size:1.05rem;margin:0 0 .7rem;letter-spacing:.04em}"
    ".foot2 a{display:block;color:#E8F1EA;text-decoration:none;padding:.3rem 0;cursor:pointer}"
    ".foot2 a.brand{display:flex;padding:0}"
    ".foot2 a:hover{color:#F2A93B;text-decoration:underline}"
    ".foot2 p{margin:.4rem 0;color:#A9C6B3;line-height:1.5}"
    ".foot2 .brand .bn{color:#FFF8EA}.foot2 .brand .bn b{color:#F2A93B}"
    ".fbot{display:flex;flex-wrap:wrap;justify-content:space-between;gap:.4rem 1.5rem;border-top:1px solid rgba(255,248,234,.16);"
    "margin-top:1.6rem;padding-top:1rem;font-size:.88rem;color:#A9C6B3}"
    ".ptitle{padding:1rem 0 .4rem}.ptitle h2{font-size:2rem;color:#0A2016}.ptitle p{color:var(--mute);margin:.3rem 0 0}"
    # Streamlit parts: FAQ and the contact form
    "[data-testid='stExpander']{border:1px solid #EADFC4 !important;border-radius:18px !important;background:#fff;box-shadow:0 6px 16px rgba(15,46,32,.06);"
    "margin-bottom:.6rem;overflow:hidden}"
    "[data-testid='stExpander'] summary{font-weight:600;padding:.8rem 1rem;font-size:1.05rem}"
    "[data-testid='stForm']{background:#fff;border:1px solid #EADFC4 !important;border-radius:28px !important;padding:1.6rem !important;"
    "box-shadow:0 20px 44px rgba(15,46,32,.12)}"
    # motion: rise as sections scroll in (browsers without scroll timelines just show everything)
    "@keyframes floaty{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}"
    "@keyframes rise{from{opacity:0;transform:translateY(28px)}to{opacity:1;transform:none}}"
    "@supports (animation-timeline:view()){.step,.tile,.role,.about,.cinfo,.band,.cta{animation:rise both;animation-timeline:view();animation-range:entry 0% entry 35%}}"
    "@media (max-width:900px){.bento{grid-template-columns:1fr 1fr}.tile.photo{grid-column:span 2;grid-row:span 1;min-height:18rem}"
    ".tile.dark,.tile.wide{grid-column:span 2}.datagrid{grid-template-columns:1fr 1fr}}"
    "@media (max-width:760px){"
    ".topin{padding:.45rem .8rem}.nav a{padding:.5rem .55rem;font-size:.92rem}.brand .bn{display:none}.brand svg{width:2.4rem;height:2.4rem}"
    ".hero,.band,.about{grid-template-columns:1fr}"
    ".hero .txt{padding:2.2rem 1.4rem 1rem}.hero h1{font-size:2.5rem}"
    ".hero .stage{padding:1rem 1rem 2rem}.hero .arch{height:20rem;max-width:17rem}.chip.c1{left:0}.chip.c2{right:0}"
    ".hero video{display:none}.hero.vid:before{background:#0A2016}"
    ".grid3,.bento,.datagrid{grid-template-columns:1fr}.tile.photo,.tile.dark,.tile.wide{grid-column:auto}"
    ".sec{margin:3rem 0 1.1rem}.sec h2{font-size:1.8rem}.cta h2{font-size:1.8rem}"
    ".band .bt{padding:1.8rem 1.4rem}.band .bigstat{font-size:4rem}.band .im{min-height:12rem}"
    ".about .ph img{height:20rem}.fgrid{grid-template-columns:1fr 1fr}.foot2{padding:1.8rem 1.3rem 1rem}}"
    "@media (prefers-reduced-motion:reduce){.chip{animation:none}.hero video{display:none}"
    ".step,.tile,.role,.about,.cinfo,.band,.cta{animation:none !important}}"
    "</style>"
)

# Lets the big buttons and the links open a view (Home, Log in, Sign up) and scroll to a section. If scripts are
# blocked the buttons do nothing. The page text is fixed; nothing typed is used here.
GOTO_JS = (
    "<script>(function(){var p=window.parent,d=p.document;if(p.__gotoReady)return;p.__gotoReady=true;"
    "d.addEventListener('click',function(e){var a=e.target.closest('[data-goto]');if(!a)return;e.preventDefault();"
    "var want=a.getAttribute('data-goto'),sc=a.getAttribute('data-scroll');"
    "var t=[].slice.call(d.querySelectorAll('[role=tab]')).find(function(b){return b.innerText.trim()===want});"
    "var go=function(){var el=sc&&d.querySelector('[data-anchor=\"'+sc+'\"]');"
    "if(el){el.scrollIntoView({behavior:'smooth',block:'start'});return}"
    "var m=d.querySelector('[data-testid=stMain]');if(m)m.scrollTo({top:0,behavior:'smooth'});};"
    "if(t&&t.getAttribute('aria-selected')!=='true'){t.click();setTimeout(go,300);}else{go();}},true);})();</script>"
)

LOGO_SVG = (
    '<svg viewBox="0 0 64 64" role="img" aria-label="Maziwa Plus logo" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2A6F46"/><stop offset="1" stop-color="#0F3A26"/></linearGradient></defs>'
    '<circle cx="32" cy="32" r="30" fill="url(#lg)" stroke="#F2A93B" stroke-width="3"/>'
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
        f'<div class="land"><footer class="foot2"><div class="fgrid"><div>{_brand()}'
        "<p>Know what your feed is worth.</p><p>Karibu. A tool for farmers, vets and milk buyers.</p></div>"
        '<div><h4>Explore</h4><a href="#" data-goto="Home">Home</a>' + _nav_link("How it works", "how")
        + _nav_link("About us", "about") + "</div>"
        '<div><h4>Get started</h4><a href="#" data-goto="Sign up">Create an account</a><a href="#" data-goto="Log in">Log in</a></div>'
        f"<div><h4>Contact</h4>{lines}" + _nav_link("Write to us", "contact") + "</div></div>"
        '<div class="fbot"><span>© 2026 HustleWindow</span>'
        "<span>Built for the FNB App of the Year hackathon. Demo data is simulated.</span></div></footer></div>",
        unsafe_allow_html=True,
    )


def page_title(title, text):
    st.markdown(f'<div class="land"><div class="ptitle"><h2>{title}</h2><p>{text}</p></div></div>', unsafe_allow_html=True)


def _chip(cls, ic, title, sub):
    return f'<div class="chip {cls}"><div class="ic">{icon(ic, "1.25rem")}</div><div><b>{title}</b><span>{sub}</span></div></div>'


def _hero():
    has_video = os.path.exists(HERO_VIDEO)
    txt = (
        '<div class="txt"><div class="pill"><i></i>Karibu · built for Kenyan dairy farmers</div>'
        "<h1>Know what your milk <em>really earns</em>.</h1>"
        '<p class="lead">Feed is the biggest cost on a dairy farm. Record your day, see what each feed pays back, '
        "and reach your vet and your milk route from one phone.</p>"
        f'<div><a class="btn main" href="#" data-goto="Sign up">Get started {icon("check", "1.2rem")}</a>'
        '<a class="btn ghost" href="#" data-goto="Log in">I have an account</a></div></div>'
    )
    if has_video:
        media = (
            f'<video autoplay muted loop playsinline preload="metadata" poster="{IMG}hero-cow.jpg" aria-hidden="true">'
            '<source src="app/static/hero.mp4" type="video/mp4"></video>'
        )
        return f'<div class="hero vid">{media}{txt}</div>'
    stage = (
        f'<div class="stage"><div class="arch"><img src="{IMG}hero-cow.jpg" alt="A curious brown cow looking into the camera"></div>'
        + _chip("c1", "trend", "Feed advice", "after 14 days of records")
        + _chip("c2", "cross", "Vet booked", "your route vet, one tap")
        + _chip("c3", "bell", "Vaccination day", "reminder set")
        + "</div>"
    )
    return f'<div class="hero">{txt}{stage}</div>'


def _head(eyebrow, title, sub="", anchor=None):
    a = f' data-anchor="{anchor}"' if anchor else ""
    s = f'<p class="sub">{sub}</p>' if sub else ""
    return f'<div class="sec"{a}><div class="eyebrow">{eyebrow}</div><h2>{title}</h2>{s}</div>'


def _steps():
    items = [
        ("notebook", "Log your day", "Record the milk and what you fed, in the buckets, bags or bales you really use."),
        ("cross", "Ask and book", "Request the vet, choose AI semen from your route vet's price list, book vaccination days."),
        ("bell", "Hear what matters", "Get an outbreak alert, or one short SMS about one feed, only when the records are clear."),
    ]
    return "".join(
        f'<div class="step"><div class="num">{i}</div><div class="tileic{" amb" if i == 2 else ""}">{icon(ic)}</div><h3>{t}</h3><p>{p}</p></div>'
        for i, (ic, t, p) in enumerate(items, 1)
    )


def _tile(ic, title, text, cls="", amb=False):
    return f'<div class="tile {cls}"><div class="tileic{" amb" if amb else ""}">{icon(ic)}</div><h3>{title}</h3><p>{text}</p></div>'


def _bento():
    photo = (
        f'<div class="tile photo"><img src="{IMG}farmer-feeding.jpg" alt="A farmer hand-feeding fresh grass to a brown cow" loading="lazy">'
        f'<div><div class="tileic amb">{icon("drop")}</div><h3>Log your day in the buckets you already use</h3>'
        "<p>Feeding a truckload of napier, shredded and mixed with hay? Record it as 20-litre buckets, 50 kg bags or bales. "
        "Weigh one full bucket once and the app does the sums. Bought or grown on your own land, both count.</p></div></div>"
    )
    return (
        '<div class="bento">' + photo
        + _tile("trend", "Advice that shows its working",
                "After 14 full days of records, the app compares what each feed costs with what the cows gave back. "
                "If the evidence is thin it says so, and does not guess.", "dark", amb=True)
        + _tile("cross", "Ask your vet", "Request a visit and pick AI semen from your route vet's own price list.")
        + _tile("calendar", "Vaccination days", "Book ahead and get a reminder, with one list for the whole route.", "warm", amb=True)
        + _tile("shield", "Private by default", "A farmer sees only their own farm. A vet sees only the farms on their route.")
        + _tile("coins", "Know your margin", "Costs in shillings per litre, and what is left after feed and semen.")
        + _tile("phone", "Made for a phone", "Big buttons, short pages, and a get-started list that tells you the next step.", "wide")
        + "</div>"
    )


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
        '<div class="land">' + _head("About us", f"Why we built {APP_NAME}", anchor="about")
        + '<div class="about"><div>'
        "<p>We are HustleWindow, a team building tools for smallholder dairy farmers in Kenya. Most farms buy feed by feel and "
        "arrange vets and vaccination by phone call. We wanted one place where the farmer, the route vet and the milk buyer "
        f"see the same facts.</p>{team_html}{prom_html}</div>"
        f'<div class="ph"><img src="{IMG}trough.jpg" alt="Cows feeding at a wooden trough at sunset" loading="lazy"></div></div>'
        '<div class="sec" style="margin-top:2.6rem"><h2 style="font-size:1.7rem">Your data</h2></div>'
        f'<div class="datagrid">{data_html}</div></div>'
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
        '<div class="land"><div class="cinfo"><h3>Talk to us</h3>'
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
    """The whole public page, top to bottom."""
    st.markdown(
        '<div class="land">' + _hero()
        + '<div class="trust"><span>' + icon("phone", "1.1rem") + "Works on any phone</span><span>" + icon("shield", "1.1rem")
        + "Your records stay yours</span><span>" + icon("trash", "1.1rem") + "Delete your account any time</span><span>"
        + icon("trend", "1.1rem") + "Advice shows its working</span></div>"
        + _head("How it works", "Three steps, a few minutes a day", anchor="how")
        + f'<div class="grid3">{_steps()}</div>'
        + _head("What you get", "Everything a dairy farm runs on, in one place", "Built around the way smallholders really feed and farm.")
        + _bento()
        + '<div class="band"><div class="bt"><div class="bigstat">43–58%</div>'
        "<p>of what it costs to make a litre of milk is feed, and most farms buy it by feel. "
        "We help each farm see which feed pays on its own cows.</p>"
        '<p class="src">Source: Tegemeo Institute and Kenya Dairy Board cost study (2014 data).</p></div>'
        f'<div class="im"><img src="{IMG}bottling.jpg" alt="Milk being filled into clear bottles" loading="lazy"></div></div>'
        + _head("Who it is for", "Built for every person on the route")
        + f'<div class="grid3">{_roles()}</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(_about_html(), unsafe_allow_html=True)
    st.markdown('<div class="land">' + _head("Questions", "Before you sign up") + "</div>", unsafe_allow_html=True)
    for q, a in FAQ:
        with st.expander(q):
            st.write(a)
    st.markdown('<div class="land">' + _head("Contact us", "We would love to hear from you", anchor="contact") + "</div>", unsafe_allow_html=True)
    left, right = st.columns([5, 6], gap="large")
    with left:
        st.markdown(_contact_info_html(), unsafe_allow_html=True)
    with right:
        _contact_form()
    st.markdown(
        '<div class="land"><div class="cta"><h2>Ready to see what your feed is worth?</h2>'
        "<p>Sign up takes a minute. Farmers, vets and milk-buyer admins each get their own view.</p>"
        f'<a class="btn main" href="#" data-goto="Sign up">Create my account {icon("check", "1.2rem")}</a>'
        '<a class="btn ghost" href="#" data-goto="Log in">Log in</a></div></div>',
        unsafe_allow_html=True,
    )
    render_footer()
