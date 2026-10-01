"""Interfaz web local de Veritas para siniestros.

Corre solo en este equipo (http://127.0.0.1:8765) y guarda los casos en una carpeta local.
    python -m veritas.web                 # usa la carpeta ./casos
    python -m veritas.web --dir D:\\casos --puerto 8765
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, send_file, session, url_for
from jinja2 import DictLoader
from markupsafe import Markup
from werkzeug.utils import secure_filename

from veritas.core import export
from veritas.claims import service
from veritas.core.case import Case, sha256_file
from veritas.core.ledger import verify_chain, verify_seal

FORM_FIELDS = ("numero", "poliza", "asegurado", "rut", "telefono", "email", "direccion", "cuenta_bancaria", "patente",
               "lugar", "taller", "testigos", "parte_policial", "fecha_denuncia", "inicio_poliza", "fin_poliza",
               "cambio_cobertura", "suma_asegurada", "deducible", "monto_reclamado", "descripcion")

# ---- plantillas ---------------------------------------------------------------
BASE = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block title %}Veritas{% endblock %} · Veritas</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
--bg:#f3f5f8;--card:#fff;--ink:#0f1b2d;--ink2:#344255;--muted:#667588;--line:#e3e8ef;--line2:#d3dae4;
--navy:#0b1f36;--navy2:#132c4a;--accent:#14508c;--accent2:#0e3d6c;--accentbg:#eaf2fb;
--red:#b42318;--redbg:#fef3f2;--redln:#fecdca;--amb:#b54708;--ambbg:#fffaeb;--ambln:#fedf89;
--grn:#067647;--grnbg:#ecfdf3;--grnln:#abefc6;--gray:#475467;--graybg:#f2f4f7;
--amber:#c77d00;--radius:10px;--shadow:0 1px 2px rgba(16,24,40,.05);--side:244px}
*{box-sizing:border-box}
html,body{margin:0}
body{font:14px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:var(--bg);-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
/* ---- estructura ---- */
.side{position:fixed;inset:0 auto 0 0;width:var(--side);background:var(--navy);color:#c6d2e0;display:flex;flex-direction:column;z-index:20}
.brand{display:flex;align-items:center;gap:10px;padding:18px 20px 16px;color:#fff;text-decoration:none;border-bottom:1px solid rgba(255,255,255,.07)}
.brand:hover{text-decoration:none}
.brand .mark{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,#2f7ac4,#14508c);display:grid;place-items:center}
.brand b{font-size:15px;letter-spacing:.14em;display:block;line-height:1.1}.brand small{font-size:11.5px;color:#8fa3ba;letter-spacing:.02em}
.navs{flex:1;overflow-y:auto;padding:10px 10px 16px}
.navs .grp{font-size:10.5px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:#7b90a8;padding:16px 12px 6px}
.navs a{display:flex;align-items:center;gap:10px;color:#c6d2e0;padding:8px 12px;border-radius:7px;font-weight:500;font-size:13.5px;position:relative}
.navs a:hover{background:rgba(255,255,255,.06);color:#fff;text-decoration:none}
.navs a.on{background:rgba(255,255,255,.1);color:#fff}
.navs a.on::before{content:"";position:absolute;left:-10px;top:8px;bottom:8px;width:3px;border-radius:0 3px 3px 0;background:#5aa0e6}
.navs a .n{margin-left:auto;background:#b42318;color:#fff;font-size:11px;font-weight:700;border-radius:99px;padding:0 7px;line-height:18px}
.navs svg{flex:none;opacity:.9}
.sidefoot{padding:12px 20px 16px;border-top:1px solid rgba(255,255,255,.07);font-size:11.5px;color:#7b90a8}
.sidefoot b{color:#c6d2e0;font-weight:500}
.userbox{display:flex;align-items:center;gap:10px}.userbox .av{width:30px;height:30px;border-radius:50%;background:#2f7ac4;color:#fff;
display:grid;place-items:center;font-weight:700;flex:none}.userbox a{margin-left:auto;color:#8ec5ff;font-size:12px}
.mtop{display:none}
.wrap{margin-left:var(--side);min-height:100vh}
.pagehead{background:var(--card);border-bottom:1px solid var(--line);padding:18px 32px 16px;display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap}
.pagehead .tt{flex:1 1 560px;min-width:260px}
.crumbs{font-size:12.5px;color:var(--muted);margin-bottom:4px}.crumbs a{color:var(--muted)}.crumbs a:hover{color:var(--accent)}
h1{font-size:21px;line-height:1.25;margin:0;font-weight:700;letter-spacing:-.01em;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.sub{color:var(--muted);margin:4px 0 0;font-size:13.5px;max-width:860px}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
main{padding:24px 32px 64px;max-width:1440px}
h2{font-size:15px;margin:0;font-weight:600}
/* ---- componentes ---- */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--line2);background:var(--card);color:var(--ink2);
padding:7px 13px;border-radius:8px;font:600 13px Inter,system-ui,sans-serif;cursor:pointer;text-decoration:none;white-space:nowrap;box-shadow:var(--shadow)}
.btn:hover{background:#f8fafc;border-color:#c0c9d6;text-decoration:none}
.btn.pri{background:var(--accent);border-color:var(--accent);color:#fff}.btn.pri:hover{background:var(--accent2)}
.btn.ghost{background:transparent;box-shadow:none;border-color:transparent}.btn.ghost:hover{background:var(--graybg)}
.btn.sm{padding:5px 10px;font-size:12.5px}
.btn[disabled]{opacity:.6;cursor:wait}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow)}
.card>h2:first-child,.card .ch{margin-bottom:12px}
.ch{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.ch h2{margin:0}.ch .r{margin-left:auto}
.panel{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}
.panel>.ph{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.panel>.ph h2{margin:0}.panel>.ph .r{margin-left:auto}.panel>.pb{padding:16px 18px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow);position:relative}
.tile b,.tile .big{display:block;font-size:26px;font-weight:700;letter-spacing:-.02em;line-height:1.15;margin-bottom:2px}
.tile span{color:var(--muted);font-size:12.5px}
.tile .lbl{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.tile.accent-red{border-top:3px solid var(--red)}.tile.accent-amb{border-top:3px solid var(--amber)}.tile.accent-blue{border-top:3px solid var(--accent)}.tile.accent-grn{border-top:3px solid var(--grn)}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;border-radius:99px;padding:2px 10px 2px 8px;white-space:nowrap;border:1px solid transparent;line-height:20px}
.badge::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.badge.bad{background:var(--redbg);color:var(--red);border-color:var(--redln)}.badge.warn{background:var(--ambbg);color:var(--amb);border-color:var(--ambln)}
.badge.ok{background:var(--grnbg);color:var(--grn);border-color:var(--grnln)}.badge.none{background:var(--graybg);color:var(--gray);border-color:var(--line)}
h1 .badge{font-size:12.5px;font-weight:600;letter-spacing:0}
table{border-collapse:collapse;width:100%}
th{text-align:left;color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;background:#f8fafc;border-bottom:1px solid var(--line);padding:9px 12px;white-space:nowrap}
td{border-bottom:1px solid var(--line);padding:11px 12px;vertical-align:middle}
tr:last-child td{border-bottom:0}
tr.row{cursor:pointer}tr.row:hover td{background:#f6f9fc}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.panel table th:first-child,.panel table td:first-child{padding-left:18px}.panel table th:last-child,.panel table td:last-child{padding-right:18px}
.scroll{overflow-x:auto}
.flash{border-radius:8px;padding:11px 14px;margin-bottom:16px;font-weight:500;border:1px solid}
.flash.ok{background:var(--grnbg);color:var(--grn);border-color:var(--grnln)}.flash.bad{background:var(--redbg);color:var(--red);border-color:var(--redln)}
.flash.info{background:var(--accentbg);color:var(--accent);border-color:#c7dcf2}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.empty{text-align:center;padding:56px 24px}.empty h2{font-size:18px;margin-bottom:6px}.empty p{color:var(--muted);max-width:560px;margin:8px auto 18px}
input,textarea,select{font:inherit;font-size:13.5px;width:100%;padding:8px 11px;border:1px solid var(--line2);border-radius:8px;background:#fff;color:var(--ink)}
input[type=file]{padding:6px 8px;background:#fafbfc}
input:focus,textarea:focus,select:focus{outline:3px solid #cfe1f5;border-color:var(--accent)}
select{width:auto}
label{display:block;font-weight:600;font-size:12.5px;margin-bottom:5px;color:var(--ink2)}
.hint{color:var(--muted);font-size:12.5px;font-weight:400}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}
.full{grid-column:1/-1}
.drop{border:2px dashed #c3ccd8;border-radius:10px;padding:28px;text-align:center;color:var(--muted);cursor:pointer;background:#fafbfd}
.drop.over{border-color:var(--accent);background:var(--accentbg)}
.thumbs{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.thumbs img{width:96px;height:72px;object-fit:cover;border-radius:6px;border:1px solid var(--line)}
iframe.report{width:100%;height:calc(100vh - 150px);min-height:620px;border:1px solid var(--line);border-radius:var(--radius);background:#fff;display:block}
.search{position:relative;flex:0 1 320px}.search input{padding-left:34px}.search svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--muted)}
.risk{display:inline-flex;align-items:center;gap:8px;font-weight:700;font-variant-numeric:tabular-nums}
.risk i{display:block;width:54px;height:6px;border-radius:9px;background:var(--graybg);overflow:hidden}.risk i::after{content:"";display:block;height:100%;width:var(--w);background:currentColor;border-radius:9px}
.risk.bad{color:var(--red)}.risk.warn{color:var(--amber)}.risk.ok{color:var(--grn)}.risk.none{color:var(--muted)}
h3.sec{grid-column:1/-1;font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:12px 0 -4px;border-top:1px solid var(--line);padding-top:18px;font-weight:600}
h3.sec:first-child{border:0;padding-top:0;margin-top:0}
.files{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.files span{background:var(--accentbg);color:var(--accent);border-radius:6px;padding:3px 8px;font-size:12.5px}
.chips{display:flex;flex-wrap:wrap;gap:4px;background:var(--graybg);padding:3px;border-radius:9px}
.chip{border:0;background:transparent;border-radius:7px;padding:5px 11px;font:600 12.5px Inter,system-ui,sans-serif;cursor:pointer;color:var(--muted)}
.chip:hover{color:var(--ink)}.chip.on{background:#fff;color:var(--ink);box-shadow:0 1px 2px rgba(16,24,40,.1)}
.chip .c{font-weight:500;color:var(--muted);margin-left:4px}
.dec{display:inline-block;font-size:12.5px;font-weight:600;color:var(--muted);white-space:nowrap}
.dec.fraude{color:var(--red)}.dec.legitimo{color:var(--grn)}.dec.en_revision{color:var(--amb)}.dec.rechazado{color:var(--gray)}
.cols2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:20px}
.layout-side{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:20px;align-items:start}
.layout-side>aside{display:grid;gap:16px;position:sticky;top:16px}
.bars{display:grid;grid-template-columns:minmax(120px,max-content) 1fr;gap:8px 12px;align-items:center;font-size:13px}
.bars .track{position:relative;height:18px}
.bars .bar{height:18px;background:var(--accent);border-radius:0 4px 4px 0;min-width:2px}
.bars .val{position:absolute;top:0;font-size:12px;line-height:18px;color:var(--ink);padding-left:6px}
.matrix td,.matrix th{text-align:center}.matrix td:first-child,.matrix th:first-child{text-align:left}
.matrix b{font-size:22px;display:block}.matrix small{color:var(--muted)}
.cell-good{background:var(--grnbg)}.cell-bad{background:var(--redbg)}
.big{font-size:28px;font-weight:700;line-height:1.1;letter-spacing:-.02em}
.netcard{margin-bottom:20px}
.reasons{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 8px}.reasons span{background:var(--accentbg);color:var(--accent);border-radius:6px;padding:2px 8px;font-size:12.5px;font-weight:500}
svg.net{width:100%;height:auto;max-height:340px;display:block;margin:4px 0 8px}
svg.net .edge{stroke:#9aa7b5;stroke-width:2}svg.net .edge.direct{stroke:var(--red);stroke-width:2.5}
svg.net .nlabel{font:600 12.5px Inter,system-ui,sans-serif;fill:var(--ink)}svg.net .nsub{font:11px Inter,system-ui,sans-serif;fill:var(--muted)}
svg.net .n-bad{fill:var(--red)}svg.net .n-warn{fill:var(--amber)}svg.net .n-ok{fill:var(--grn)}svg.net .n-none{fill:#8a96a3}
svg.net .n-center{fill:var(--accent)}svg.net .halo{fill:#fff;stroke:var(--line);stroke-width:1}
.verdict{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;border-radius:var(--radius);padding:14px 18px;margin-bottom:16px;font-size:15px;border:1px solid}
.verdict.ok{background:var(--grnbg);color:var(--grn);border-color:var(--grnln)}.verdict.warn{background:var(--ambbg);color:var(--amb);border-color:var(--ambln)}.verdict.bad{background:var(--redbg);color:var(--red);border-color:var(--redln)}
.verdict span{font-size:13px;font-weight:500}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px}
.grid4 .tile{padding:12px 14px}.grid4 .tile b{font-size:20px}
h3.cat{font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:24px 0 8px;font-weight:600}
.finding{background:var(--card);border-radius:8px;padding:11px 14px;margin:8px 0;border:1px solid var(--line);border-left:4px solid var(--line2)}
.finding.alta{border-left-color:var(--red)}.finding.media{border-left-color:var(--amber)}
.finding p{margin:4px 0 6px;color:var(--ink2)}
.sev{font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:8px;letter-spacing:.04em}
.sev.alta{background:var(--redbg);color:var(--red)}.sev.media{background:var(--ambbg);color:var(--amb)}.sev.baja{background:var(--graybg);color:var(--muted)}
.quote{background:#f8fafc;border:1px solid var(--line);border-radius:6px;padding:7px 10px;margin:5px 0;font-size:13px}
.cite{font:11.5px ui-monospace,SFMono-Regular,Consolas,monospace;background:var(--accentbg);color:var(--accent);border-radius:4px;padding:1px 5px;text-decoration:none}
.alert-card{border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;margin:10px 0;background:var(--card);box-shadow:var(--shadow)}
.alert-card h4{margin:0 0 10px;font-size:14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.evlist{display:grid;gap:4px;margin:8px 0;font-size:13px;max-height:220px;overflow:auto}
.evlist label{font-weight:400;display:flex;gap:8px;align-items:flex-start;color:var(--ink)}.evlist input{width:auto;margin-top:3px}
.ivblock{border:1px dashed var(--line2);border-radius:10px;padding:14px;margin-bottom:12px;background:#fcfdfe}
details summary{cursor:pointer;font-weight:600}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;font-size:13px;margin:0}.kv dt{color:var(--muted)}.kv dd{margin:0;font-weight:500}
.dist{display:flex;height:10px;border-radius:9px;overflow:hidden;background:var(--graybg);margin:6px 0 10px}
.checklist li.thumbs::before,.checklist li.thumbs::after{display:none!important}.checklist li.thumbs{padding-left:0}
.evfiles{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:8px}.evfiles li{border:1px solid var(--line);border-radius:8px;padding:7px 9px;font-size:13px}
.evfiles li>a{font-weight:600;overflow-wrap:anywhere}.evfiles li .hint{display:block;font-size:12px;margin:2px 0 0}.evfiles li.off{background:#f6f7f9}.evfiles li.off>a{text-decoration:line-through;color:var(--muted)}
.evfiles form{margin:4px 0 0}.linkbtn{border:0;background:none;padding:0;color:var(--red);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;text-decoration:underline;list-style:none;display:inline}
.evfiles summary::-webkit-details-marker{display:none}
.capthumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:8px;margin:4px 0 6px}
.capthumbs a{display:block;text-decoration:none;color:var(--ink);border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff}
.capthumbs a:hover{border-color:var(--accent)}.capthumbs img{display:block;width:100%;height:70px;object-fit:cover;background:#eef1f5}
.capthumbs span{display:block;font-size:12px;font-weight:600;padding:4px 6px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.capthumbs small{display:block;font-size:11px;color:var(--muted);padding:0 6px 5px}
.dist i{display:block;height:100%}.dist .d-bad{background:var(--red)}.dist .d-warn{background:var(--amber)}.dist .d-ok{background:var(--grn)}.dist .d-none{background:#b8c2cf}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;color:var(--ink2)}.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{width:9px;height:9px;border-radius:2px;display:inline-block}
.quick{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.quick a{display:flex;align-items:center;gap:10px;border:1px solid var(--line);border-radius:8px;padding:10px 12px;color:var(--ink2);font-weight:600;font-size:13px;background:#fff}
.quick a:hover{border-color:var(--accent);color:var(--accent);text-decoration:none;background:var(--accentbg)}
.quick svg{color:var(--accent)}
.mini td{padding:9px 12px}.mini tr:last-child td{border-bottom:0}
.muted{color:var(--muted)}.nowrap{white-space:nowrap}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12.5px}
.step{display:flex;gap:12px;align-items:flex-start;margin:10px 0;text-align:left}.step b.n{flex:none;width:26px;height:26px;border-radius:50%;background:var(--accentbg);color:var(--accent);display:grid;place-items:center;font-size:13px}
.portalpanel{border-color:#c7dcf2}.portalpanel>.ph{background:var(--accentbg)}
.checklist{list-style:none;margin:0;padding:0;display:grid;gap:5px;font-size:13px}
.checklist li{padding-left:22px;position:relative;color:var(--ink2)}.checklist li::before{content:"";position:absolute;left:2px;top:4px;width:12px;height:12px;border-radius:50%;border:2px solid var(--line2)}
.checklist li.ok::before{background:var(--grn);border-color:var(--grn)}.checklist li.ok{color:var(--ink)}
.checklist li.sub{padding-left:40px;font-size:12.5px}.checklist li.sub::before{left:22px;width:8px;height:8px;top:5px;border-width:1px;background:#9fd8b8;border-color:#9fd8b8}
.sharebtns{display:grid;gap:8px;margin-top:14px}
.portalbox{background:var(--accentbg);border:1px solid #c7dcf2;border-radius:10px;padding:14px 16px}
.docpick{display:flex;flex-wrap:wrap;gap:6px 18px;margin:12px 0 0 28px}.docpick label{font-weight:500;display:flex;gap:6px;align-items:center;margin:0;font-size:13px}
.docpick input{width:auto}
.formrow{display:grid;grid-template-columns:minmax(240px,1fr) 240px auto;gap:14px;align-items:end}
.split{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(280px,1fr);gap:24px;align-items:start}
@media (max-width:1100px){.layout-side{grid-template-columns:1fr}.layout-side>aside{position:static}}
@media (max-width:860px){
 .side{transform:translateX(-100%);transition:transform .2s}.side.open{transform:none;box-shadow:0 0 0 100vmax rgba(0,0,0,.35)}
 .wrap{margin-left:0}
 .mtop{display:flex;align-items:center;gap:12px;background:var(--navy);color:#fff;padding:10px 16px;position:sticky;top:0;z-index:10}
 .mtop button{background:none;border:0;color:#fff;padding:4px;cursor:pointer}.mtop b{letter-spacing:.14em;font-size:14px}
 .pagehead{padding:16px}main{padding:16px 16px 48px}
 iframe.report{height:75vh;min-height:0}
 .tiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.tile{padding:12px 14px}.tile b,.tile .big{font-size:20px}
 .tile .lbl{font-size:10.5px;letter-spacing:.04em}.tile .lbl svg{display:none}
 .formrow,.split{grid-template-columns:1fr}.cols2{grid-template-columns:1fr}.quick{grid-template-columns:1fr 1fr}
 .panel>.ph .hint{flex-basis:100%;order:3}
}
</style></head><body>
<aside class="side" id="side">
<a class="brand" href="{{ url_for('dashboard') }}"><span class="mark">{{ icon('shield', 18, '#fff') }}</span><span><b>VERITAS</b><small>Forense de siniestros</small></span></a>
<nav class="navs">
{% if can('ver_siniestros') %}<a href="{{ url_for('dashboard') }}" class="{{ 'on' if active=='dash' }}">{{ icon('grid') }}Panel</a>
<div class="grp">Siniestros</div>
<a href="{{ url_for('index') }}" class="{{ 'on' if active=='index' }}">{{ icon('list') }}Cola de trabajo{% if nav_pending %}<span class="n" title="Derivados sin decisión">{{ nav_pending }}</span>{% endif %}</a>
{% if can('editar_siniestros') %}<a href="{{ url_for('new_claim') }}" class="{{ 'on' if active=='new' }}">{{ icon('plus') }}Nuevo siniestro</a>{% endif %}
<a href="{{ url_for('photo_check') }}" class="{{ 'on' if active=='foto' }}">{{ icon('camera') }}Revisar foto</a>{% endif %}
{% if can('investigaciones') %}<div class="grp">Investigaciones</div>
<a href="{{ url_for('investigations') }}" class="{{ 'on' if active=='inv' }}">{{ icon('folder') }}Expedientes y auditorías</a>
<a href="{{ url_for('inv_new') }}" class="{{ 'on' if active=='inv_new' }}">{{ icon('plus') }}Nuevo expediente</a>{% endif %}
{% if can('redes') %}<div class="grp">Cartera</div>
<a href="{{ url_for('networks') }}" class="{{ 'on' if active=='redes' }}">{{ icon('network') }}Redes de fraude</a>{% endif %}
{% if can('cartera') %}<a href="{{ url_for('metrics_view') }}" class="{{ 'on' if active=='metricas' }}">{{ icon('chart') }}Métricas</a>
<a href="{{ url_for('import_view') }}" class="{{ 'on' if active=='importar' }}">{{ icon('upload') }}Importar historial</a>{% endif %}
{% if can('admin') %}<div class="grp">Sistema</div>
<a href="{{ url_for('users_view') }}" class="{{ 'on' if active=='usuarios' }}">{{ icon('users') }}Usuarios y accesos</a>
<a href="{{ url_for('settings') }}" class="{{ 'on' if active=='config' }}">{{ icon('gear') }}Configuración</a>{% endif %}
</nav>
{% if current_user %}<div class="sidefoot userbox"><span class="av">{{ current_user.name[:1]|upper }}</span><span><b>{{ current_user.name }}</b><br>{{ roles[current_user.role] }}</span>
<a href="{{ url_for('logout') }}" title="Cerrar sesión">Salir</a></div>
{% elif not auth_on %}<div class="sidefoot"><b style="color:#fdb022">Sin usuarios creados</b><br>Cualquiera en este equipo puede entrar. <a href="{{ url_for('users_view') }}" style="color:#8ec5ff">Crear administrador</a></div>{% endif %}
</aside>
<div class="wrap">
<div class="mtop"><button type="button" aria-label="Abrir menú" onclick="document.getElementById('side').classList.toggle('open')">{{ icon('menu', 22) }}</button><b>VERITAS</b></div>
<header class="pagehead"><div class="tt"><div class="crumbs">{% block crumbs %}{% endblock %}</div>{% block heading %}{% endblock %}</div>
<div class="actions">{% block actions %}{% endblock %}</div></header>
<main>
{% with msgs = get_flashed_messages(with_categories=true) %}{% for cat, m in msgs %}<div class="flash {{ cat }}">{{ m }}</div>{% endfor %}{% endwith %}
{% block body %}{% endblock %}
</main></div>
<script>
document.querySelectorAll('form[data-busy]').forEach(f=>f.addEventListener('submit',()=>{
  f.querySelectorAll('button[type=submit]').forEach(b=>{b.disabled=true;b.textContent=f.dataset.busy})}));
document.addEventListener('click',e=>{const s=document.getElementById('side');if(s.classList.contains('open')&&!s.contains(e.target)&&!e.target.closest('.mtop'))s.classList.remove('open')});
</script>
</body></html>"""

DASH = r"""{% extends "base.html" %}{% block title %}Panel{% endblock %}
{% block heading %}<h1>Panel</h1><p class="sub">Resumen al {{ today }} · {{ cases|length }} siniestro(s) en la cartera</p>{% endblock %}
{% block actions %}<a class="btn" href="{{ url_for('photo_check') }}">{{ icon('camera', 15) }}Revisar foto</a>
<a class="btn pri" href="{{ url_for('new_claim') }}">{{ icon('plus', 15, '#fff') }}Nuevo siniestro</a>{% endblock %}
{% block body %}
{% if cases %}
<div class="tiles">
<div class="tile accent-red"><div class="lbl">{{ icon('alert', 14) }}Derivados sin decisión</div><b>{{ k.pend_bad }}</b><span>de {{ counts.bad }} derivados a investigación</span></div>
<div class="tile accent-amb"><div class="lbl">{{ icon('clock', 14) }}Revisión manual pendiente</div><b>{{ k.pend_warn }}</b><span>de {{ counts.warn }} con alertas medias</span></div>
<div class="tile accent-blue"><div class="lbl">{{ icon('network', 14) }}Redes detectadas</div><b>{{ k.rings }}</b><span>{{ k.involved }} siniestros involucrados · {{ k.pairs }} par(es)</span></div>
<div class="tile accent-grn"><div class="lbl">{{ icon('money', 14) }}Monto en revisión</div><b>${{ money(k.monto_pend) }}</b><span>reclamado en derivados sin decisión</span></div>
</div>
<div class="layout-side">
<div style="display:grid;gap:20px">
<section class="panel"><div class="ph"><h2>Prioridad</h2><span class="hint">Casos con alertas y sin decisión final, de mayor a menor riesgo</span>
<a class="r btn sm" href="{{ url_for('index') }}">Ver cola completa</a></div>
{% if priority %}<div class="scroll"><table><tr><th>N° siniestro</th><th>Asegurado</th><th>Fecha</th><th>Riesgo</th><th class="num">Monto</th><th>Recomendación</th></tr>
{% for c in priority %}<tr class="row" onclick="location.href='{{ url_for('case_view', cid=c.id) }}'">
<td class="nowrap"><a href="{{ url_for('case_view', cid=c.id) }}"><b>{{ c.numero }}</b></a><div class="hint">{{ c.patente }}</div></td>
<td>{{ c.asegurado }}</td><td class="nowrap">{{ c.fecha[:10] }}</td>
<td><span class="risk {{ c.level }}" style="--w:{{ c.score if c.score is number else 0 }}%"><i></i>{{ c.score }}</span></td>
<td class="num nowrap">{{ '$' ~ money(c.monto) if c.monto else '—' }}</td>
<td><span class="badge {{ c.level }}">{{ level_text.get(c.level, c.rec) }}</span></td></tr>{% endfor %}</table></div>
{% else %}<div class="pb"><p class="hint" style="margin:0">No hay casos con alertas pendientes de decisión.</p></div>{% endif %}
</section>
{% if waiting %}<section class="panel"><div class="ph"><h2>Esperando al asegurado</h2><span class="hint">Enlaces enviados que aún no se completan</span></div>
<table class="mini">{% for w in waiting %}<tr class="row" onclick="location.href='{{ url_for('case_view', cid=w.id) }}#portal'">
<td class="nowrap"><a href="{{ url_for('case_view', cid=w.id) }}"><b>{{ w.numero }}</b></a><div class="hint">{{ w.asegurado }}</div></td>
<td style="min-width:140px"><div class="dist" style="margin:0"><i class="d-ok" style="width:{{ w.pct }}%"></i></div><span class="hint">{{ w.done }} de {{ w.total }} pasos</span></td>
<td class="hint nowrap">enviado hace {{ w.days }} día(s)</td>
<td style="text-align:right">{% if w.expired %}<span class="badge bad">Vencido</span>{% elif w.opened %}<span class="badge warn">Abierto</span>{% else %}<span class="badge none">Sin abrir</span>{% endif %}</td></tr>{% endfor %}</table></section>{% endif %}
<section class="panel"><div class="ph"><h2>Investigaciones</h2><span class="hint">Expedientes en curso e informes auditados</span>
<a class="r btn sm" href="{{ url_for('investigations') }}">Ver todo</a></div>
{% if expedientes or audits %}<table class="mini">
{% for x in expedientes[:4] %}<tr class="row" onclick="location.href='{{ url_for('inv_view', cid=x.id) }}'"><td class="nowrap">{{ icon('folder', 15) }} <a href="{{ url_for('inv_view', cid=x.id) }}"><b>{{ x.numero }}</b></a></td>
<td class="hint">Expediente · {{ x.answered }} de {{ x.alerts }} alertas respondidas</td>
<td style="text-align:right">{% if x.pending %}<span class="badge warn">{{ x.pending }} pendiente(s)</span>{% else %}<span class="badge ok">Listo para enviar</span>{% endif %}</td></tr>{% endfor %}
{% for x in audits[:3] %}<tr class="row" onclick="location.href='{{ url_for('audit_view', cid=x.id) }}'"><td class="nowrap">{{ icon('filecheck', 15) }} <a href="{{ url_for('audit_view', cid=x.id) }}"><b>{{ x.name[:34] }}</b></a></td>
<td class="hint">Auditoría · {{ x.ts }}</td>
<td style="text-align:right"><span class="badge {{ 'bad' if x.alta else ('warn' if x.media else 'ok') }}">{{ x.alta }} alta · {{ x.media }} media</span></td></tr>{% endfor %}
</table>{% else %}<div class="pb"><p class="hint" style="margin:0">Aún no hay expedientes ni auditorías. <a href="{{ url_for('investigations') }}">Auditar un informe</a></p></div>{% endif %}
</section>
</div>
<aside>
<section class="panel"><div class="ph"><h2>Estado de la cartera</h2></div><div class="pb">
{% set tot = cases|length %}
<div class="dist">{% for lv in ('bad','warn','ok','none') %}{% if counts[lv] %}<i class="d-{{ lv }}" style="width:{{ 100 * counts[lv] / tot }}%" title="{{ level_text[lv] }}: {{ counts[lv] }}"></i>{% endif %}{% endfor %}</div>
<div class="legend"><span><i style="background:var(--red)"></i>Derivar {{ counts.bad }}</span><span><i style="background:var(--amber)"></i>Revisión {{ counts.warn }}</span>
<span><i style="background:var(--grn)"></i>Sin alertas {{ counts.ok }}</span>{% if counts.none %}<span><i style="background:#b8c2cf"></i>Sin analizar {{ counts.none }}</span>{% endif %}</div>
<dl class="kv" style="margin-top:14px"><dt>Fraudes confirmados</dt><dd>{{ k.fraude }}</dd><dt>Legítimos</dt><dd>{{ k.legitimo }}</dd><dt>Sin decisión</dt><dd>{{ k.sin_decision }}</dd></dl>
</div></section>
<section class="panel"><div class="ph"><h2>Redes principales</h2><a class="r btn sm" href="{{ url_for('networks') }}">Ver redes</a></div>
{% if comps %}<table class="mini">{% for c in comps[:3] %}<tr class="row" onclick="location.href='{{ url_for('networks') }}'">
<td><b>{{ 'Red' if c.members|length >= 3 else 'Par' }} de {{ c.members|length }}</b><div class="hint">{{ c.reasons[0][0] if c.reasons else '' }}</div></td>
<td class="num nowrap"><b>${{ money(c.monto) }}</b></td></tr>{% endfor %}</table>
{% else %}<div class="pb"><p class="hint" style="margin:0">No se encontraron redes. Importe el historial para buscarlas en toda la cartera.</p></div>{% endif %}
</section>
<section class="panel"><div class="ph"><h2>Accesos rápidos</h2></div><div class="pb"><div class="quick">
<a href="{{ url_for('new_claim') }}">{{ icon('plus', 16) }}Nuevo siniestro</a><a href="{{ url_for('photo_check') }}">{{ icon('camera', 16) }}Revisar foto</a>
<a href="{{ url_for('investigations') }}">{{ icon('filecheck', 16) }}Auditar informe</a><a href="{{ url_for('inv_new') }}">{{ icon('folder', 16) }}Nuevo expediente</a>
<a href="{{ url_for('import_view') }}">{{ icon('upload', 16) }}Importar historial</a><a href="{{ url_for('metrics_view') }}">{{ icon('chart', 16) }}Métricas</a>
</div></div></section>
</aside></div>
{% else %}
<div class="card empty"><h2>Aún no hay siniestros</h2>
<p>Empiece de una de estas formas. Todo lo que cargue queda bajo cadena de custodia desde el primer momento.</p>
<div style="max-width:460px;margin:0 auto 22px">
<div class="step"><b class="n">1</b><div><b>Cargar un ejemplo</b><div class="hint">Cinco siniestros ficticios: tres forman una red, uno sospechoso conectado a ellos y uno limpio.</div></div></div>
<div class="step"><b class="n">2</b><div><b>Importar el historial</b><div class="hint">Excel o CSV de siniestros pasados, para buscar redes en toda la cartera.</div></div></div>
<div class="step"><b class="n">3</b><div><b>Crear un siniestro</b><div class="hint">Con la declaración, las fotos y los documentos del asegurado.</div></div></div></div>
<div class="toolbar" style="justify-content:center">
<form method="post" action="{{ url_for('load_demo') }}" data-busy="Cargando…"><button class="btn pri" type="submit">Cargar ejemplo</button></form>
<a class="btn" href="{{ url_for('import_view') }}">Importar historial</a><a class="btn" href="{{ url_for('new_claim') }}">Nuevo siniestro</a></div></div>
{% endif %}
{% endblock %}"""

INDEX = r"""{% extends "base.html" %}{% block title %}Cola de trabajo{% endblock %}
{% block heading %}<h1>Cola de trabajo</h1><p class="sub">Siniestros ordenados por riesgo. Haga clic en una fila para abrir el caso.</p>{% endblock %}
{% block actions %}<a class="btn" href="{{ url_for('export_xlsx', what='cola') }}">{{ icon('download', 15) }}Excel</a>
<a class="btn" href="{{ url_for('import_view') }}">{{ icon('upload', 15) }}Importar historial</a>
<a class="btn pri" href="{{ url_for('new_claim') }}">{{ icon('plus', 15, '#fff') }}Nuevo siniestro</a>{% endblock %}
{% block body %}
{% if cases %}
<section class="panel">
<div class="ph"><label class="search" style="margin:0">{{ icon('search', 15) }}<input id="q" placeholder="Buscar por número, patente o asegurado" aria-label="Buscar"></label>
<div class="chips" id="chips"><button class="chip on" data-f="">Todos<span class="c">{{ cases|length }}</span></button>
<button class="chip" data-f="bad">Derivar<span class="c">{{ counts.bad }}</span></button>
<button class="chip" data-f="warn">Revisión<span class="c">{{ counts.warn }}</span></button>
<button class="chip" data-f="ok">Sin alertas<span class="c">{{ counts.ok }}</span></button>
<button class="chip" data-f="pend">Alerta sin decisión<span class="c">{{ counts.pend }}</span></button></div>
<span class="r hint" id="shown"></span></div>
<div class="scroll"><table id="t"><tr><th>N° siniestro</th><th>Asegurado</th><th>Fecha</th><th>Riesgo</th><th class="num">Hallazgos</th><th class="num">Vinculados</th><th class="num">Monto</th><th>Recomendación</th><th>Decisión</th></tr>
{% for c in cases %}<tr class="row" data-level="{{ c.level }}" data-pend="{{ 1 if c.level == 'bad' and c.decision in (None, 'en_revision') else 0 }}" onclick="location.href='{{ url_for('case_view', cid=c.id) }}'">
<td class="nowrap"><a href="{{ url_for('case_view', cid=c.id) }}"><b>{{ c.numero }}</b></a><div class="hint">{{ c.patente }}</div></td><td>{{ c.asegurado }}</td>
<td class="nowrap">{{ c.fecha[:10] }}<div class="hint">{{ c.fecha[11:] }}</div></td>
<td><span class="risk {{ c.level }}" style="--w:{{ c.score if c.score is number else 0 }}%"><i></i>{{ c.score }}</span></td>
<td class="num">{{ c.findings }}</td><td class="num">{{ c.linked }}</td><td class="num nowrap">{{ '$' ~ money(c.monto) if c.monto else '—' }}</td>
<td><span class="badge {{ c.level }}" title="{{ c.rec }}">{{ level_text.get(c.level, c.rec) }}</span></td>
<td><span class="dec {{ c.decision or '' }}">{{ c.decision_label or '—' }}</span></td></tr>{% endfor %}
</table></div></section>
<script>
const q=document.getElementById('q');let lf='';
function apply(){const v=q.value.toLowerCase();let n=0;document.querySelectorAll('#t tr.row').forEach(r=>{
 const okf=!lf||(lf==='pend'?r.dataset.pend==='1':r.dataset.level===lf);const s=okf&&r.textContent.toLowerCase().includes(v);r.style.display=s?'':'none';n+=s});
 document.getElementById('shown').textContent=n+' caso(s)'}
q.addEventListener('input',apply);
document.querySelectorAll('#chips .chip').forEach(c=>c.onclick=()=>{document.querySelectorAll('#chips .chip').forEach(x=>x.classList.remove('on'));
 c.classList.add('on');lf=c.dataset.f;apply()});apply();
</script>
{% else %}
<div class="card empty"><h2>Aún no hay siniestros</h2>
<p>Cree uno con la declaración, las fotos y los documentos del asegurado, o cargue un ejemplo para ver cómo funciona.</p>
<div class="toolbar" style="justify-content:center"><a class="btn pri" href="{{ url_for('new_claim') }}">Nuevo siniestro</a>
<form method="post" action="{{ url_for('load_demo') }}" data-busy="Cargando…"><button class="btn" type="submit">Cargar ejemplo</button></form>
<a class="btn" href="{{ url_for('import_view') }}">Importar historial</a></div></div>
{% endif %}
{% endblock %}"""

NEW = r"""{% extends "base.html" %}{% block title %}Nuevo siniestro{% endblock %}
{% block crumbs %}<a href="{{ url_for('index') }}">Cola de trabajo</a> / Nuevo{% endblock %}
{% block heading %}<h1>Nuevo siniestro</h1><p class="sub">Solo el número, la fecha y la evidencia son obligatorios; mientras más datos, más verificaciones puede hacer Veritas. Todo queda bajo cadena de custodia desde este momento.</p>{% endblock %}
{% block body %}
{% if error %}<div class="flash bad">{{ error }}</div>{% endif %}
<form class="card" method="post" enctype="multipart/form-data" data-busy="Analizando…" style="max-width:1100px">
<div class="grid">
<h3 class="sec">Siniestro</h3>
<div><label>N° de siniestro *</label><input name="numero" required value="{{ f.numero }}" placeholder="SIN-2026-1234"></div>
<div><label>Fecha y hora del siniestro *</label><input type="datetime-local" name="fecha_siniestro" required value="{{ f.fecha_siniestro }}"></div>
<div><label>Fecha de denuncia</label><input type="date" name="fecha_denuncia" value="{{ f.fecha_denuncia }}"></div>
<div><label>Patente</label><input name="patente" value="{{ f.patente }}" placeholder="ABCD-12"></div>
<div class="full"><label>Lugar</label><input name="lugar" value="{{ f.lugar }}" placeholder="Dirección o referencia"></div>
<div><label>Latitud <span class="hint">(opcional)</span></label><input name="lat" value="{{ f.lat }}" placeholder="-33.4263"></div>
<div><label>Longitud <span class="hint">(opcional)</span></label><input name="lon" value="{{ f.lon }}" placeholder="-70.6167"></div>
<div><label>Taller</label><input name="taller" value="{{ f.taller }}"></div>
<div><label>Testigos</label><input type="number" min="0" name="testigos" value="{{ f.testigos }}" placeholder="0"></div>
<div><label>N° parte policial</label><input name="parte_policial" value="{{ f.parte_policial }}"></div>
<p class="hint full" style="margin:-6px 0 0">Con las coordenadas del lugar, Veritas compara dónde se tomó cada foto. Puede copiarlas desde Google Maps (clic derecho sobre el punto).</p>

<h3 class="sec">Asegurado</h3>
<div><label>Nombre</label><input name="asegurado" value="{{ f.asegurado }}"></div>
<div><label>RUT</label><input name="rut" value="{{ f.rut }}" placeholder="12.345.678-9"></div>
<div><label>Teléfono</label><input name="telefono" value="{{ f.telefono }}" placeholder="+56 9 1234 5678"></div>
<div><label>Correo</label><input type="email" name="email" value="{{ f.email }}"></div>
<div class="full"><label>Dirección</label><input name="direccion" value="{{ f.direccion }}"></div>
<div><label>Cuenta bancaria para el pago</label><input name="cuenta_bancaria" value="{{ f.cuenta_bancaria }}"></div>

<h3 class="sec">Póliza</h3>
<div><label>N° de póliza</label><input name="poliza" value="{{ f.poliza }}"></div>
<div><label>Inicio de vigencia</label><input type="date" name="inicio_poliza" value="{{ f.inicio_poliza }}"></div>
<div><label>Vencimiento</label><input type="date" name="fin_poliza" value="{{ f.fin_poliza }}"></div>
<div><label>Último cambio de cobertura</label><input type="date" name="cambio_cobertura" value="{{ f.cambio_cobertura }}"></div>
<div><label>Suma asegurada ($)</label><input name="suma_asegurada" value="{{ f.suma_asegurada }}" placeholder="5.000.000"></div>
<div><label>Deducible ($)</label><input name="deducible" value="{{ f.deducible }}"></div>
<div><label>Monto reclamado ($)</label><input name="monto_reclamado" value="{{ f.monto_reclamado }}"></div>

<h3 class="sec">Relato</h3>
<div class="full"><label>Relato del asegurado</label><textarea name="descripcion" rows="4" placeholder="Cómo ocurrió, con las palabras del asegurado">{{ f.descripcion }}</textarea></div>

<h3 class="sec">Evidencia</h3>
<div class="full portalbox"><label style="display:flex;gap:10px;align-items:flex-start;font-size:14px;margin:0">
<input type="checkbox" name="enviar_enlace" value="1" {{ 'checked' if not f or f.get('enviar_enlace') == '1' }} style="width:auto;margin-top:3px">
<span><b>Pedirle al asegurado que suba todo por un enlace</b> (recomendado)<br><span class="hint">Se genera un enlace para enviarle por WhatsApp, SMS o correo.
Toma las fotos con la cámara en vivo y sube los documentos originales: no se pierden la fecha ni el lugar, como pasa al reenviarlos por WhatsApp.</span></span></label>
<div class="docpick"><span class="hint" style="width:100%">Documentos que le vamos a pedir:</span>
{% for k, v in doc_types.items() if k != 'otro' %}<label><input type="checkbox" name="docs" value="{{ k }}" {{ 'checked' if k in (f.getlist('docs') if f.getlist else default_docs) }}> {{ v }}</label>{% endfor %}
<input type="hidden" name="docs_sent" value="1">
<div style="width:100%;margin-top:6px"><input name="docs_custom" value="{{ f.get('docs_custom', '') if f else '' }}" placeholder="Otro documento que necesite (escríbalo; separe varios con punto y coma)" style="font-size:13px"></div></div>
<p class="hint" style="margin:10px 0 0 28px">El asegurado siempre puede subir además otros documentos que quiera agregar.</p></div>
<div class="full"><label>Fotos y documentos que ya tiene <span class="hint">(opcional si envía el enlace)</span></label>
<div class="drop" id="drop"><span id="droptxt">Arrastre aquí fotos y documentos PDF, o haga clic para elegirlos</span><br><span class="hint">Fotos JPG, PNG, WEBP, TIFF o HEIC y documentos PDF (presupuestos, facturas, partes) · se analizan los originales, sin modificarlos</span>
<input type="file" id="fotos" name="fotos" multiple accept="image/*,.heic,.pdf,application/pdf,.txt,.zip" style="display:none"></div>
<div class="thumbs" id="thumbs"></div><div class="files" id="files"></div></div>
</div>
<div class="toolbar" style="margin-top:18px"><button class="btn pri" type="submit">Registrar siniestro</button>
<a class="btn" href="{{ url_for('index') }}">Cancelar</a></div>
</form>
<script>
const drop=document.getElementById('drop'),inp=document.getElementById('fotos'),th=document.getElementById('thumbs');
drop.onclick=()=>inp.click();
const fl=document.getElementById('files'),dt=document.getElementById('droptxt');
function show(){th.innerHTML='';fl.innerHTML='';[...inp.files].forEach(f=>{if(f.type.startsWith('image/')){const i=document.createElement('img');i.src=URL.createObjectURL(f);i.title=f.name;th.appendChild(i)}
 else{const s=document.createElement('span');s.textContent='📄 '+f.name;fl.appendChild(s)}});
 dt.textContent=inp.files.length?inp.files.length+' archivo(s) seleccionado(s) · clic para cambiar':'Arrastre aquí fotos y documentos PDF, o haga clic para elegirlos'}
inp.onchange=show;
['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',ev=>{inp.files=ev.dataTransfer.files;show()});
</script>
{% endblock %}"""

CASE = r"""{% extends "base.html" %}{% block title %}{{ c.numero }}{% endblock %}
{% block crumbs %}<a href="{{ url_for('index') }}">Cola de trabajo</a> / {{ c.numero }}{% endblock %}
{% block heading %}<h1>Siniestro {{ c.numero }} <span class="badge {{ c.level }}">{{ c.rec }}</span></h1>
<p class="sub">{{ c.patente }} · {{ c.asegurado }} · ocurrido {{ c.fecha }} · analizado {{ c.analyzed }}</p>
<div class="toolbar" style="gap:18px;margin-top:10px;font-size:13px"><span class="muted">Riesgo</span><span class="risk {{ c.level }}" style="--w:{{ c.score if c.score is number else 0 }}%;margin-left:-10px"><i></i>{{ c.score }}</span>
<span class="muted">Monto</span><b style="margin-left:-10px">{{ '$' ~ money(c.monto) if c.monto else '—' }}</b>
<span class="muted">Decisión</span><a href="#decision" class="dec {{ c.decision or '' }}" style="margin-left:-10px">{{ c.decision_label or 'Pendiente' }}</a></div>{% endblock %}
{% block actions %}
<form method="post" action="{{ url_for('reanalyze', cid=c.id) }}" data-busy="Analizando…"><button class="btn" type="submit">{{ icon('refresh', 15) }}Reanalizar</button></form>
<form method="post" action="{{ url_for('verify', cid=c.id) }}"><button class="btn" type="submit">{{ icon('shield', 15) }}Verificar integridad</button></form>
<a class="btn" href="{{ url_for('report', cid=c.id) }}#linea" target="informe">{{ icon('timeline', 15) }}Línea de tiempo</a>
<a class="btn" href="{{ url_for('report', cid=c.id) }}" target="_blank">{{ icon('external', 15) }}Abrir informe</a>
<a class="btn pri" href="{{ url_for('export_zip', cid=c.id) }}">{{ icon('download', 15, '#fff') }}Paquete verificable</a>{% endblock %}
{% block body %}
<div class="layout-side">
<div><iframe class="report" name="informe" src="{{ url_for('report', cid=c.id) }}" title="Informe del siniestro"></iframe></div>
<aside>
<section class="panel portalpanel" id="portal"><div class="ph"><h2>{{ icon('link', 16) }} Portal del asegurado</h2>
{% if cap %}<span class="r">{% if pr.finished %}<span class="badge ok">Entregado</span>{% elif cap_state %}<span class="badge none">{{ cap_state }}</span>{% elif cap.opened %}<span class="badge warn">Abierto</span>{% else %}<span class="badge none">Enviado</span>{% endif %}</span>{% endif %}</div><div class="pb">
{% if cap %}
<div class="dist" style="margin:0 0 6px"><i class="d-ok" style="width:{{ pr.pct }}%"></i></div>
<div class="hint" style="margin-bottom:10px">{{ pr.done }} de {{ pr.total }} pasos{% if pr.finished %} · enviado {{ pr.finished[8:10] }}-{{ pr.finished[5:7] }} {{ pr.finished[11:16] }}{% elif cap.opened %} · abierto por el asegurado{% endif %}</div>
<ul class="checklist">
<li class="{{ 'ok' if pr.photos_ok }}">Fotos: {{ pr.photos|length + pr.shots_done|length }}</li>
{% if pr.photos %}<li class="sub thumbs"><div class="capthumbs">{% for f in pr.photos %}<a href="{{ url_for('evidence_file', cid=c.id, digest=f.sha256) }}" target="_blank" rel="noopener" title="Abrir {{ f.title or f.original_name }}">
<img src="{{ url_for('evidence_file', cid=c.id, digest=f.sha256, mini=1) }}" alt="{{ f.title or f.original_name }}" loading="lazy">
<span>{{ f.title or f.original_name }}</span><small>{{ f.server_time[8:10] }}-{{ f.server_time[5:7] }} {{ f.server_time[11:16] }}</small></a>{% endfor %}</div></li>{% endif %}
<li class="{{ 'ok' if pr.docs_ok }}">Documentos: {{ pr.docs|length }}</li>
{% for f in pr.docs %}<li class="ok sub"><a href="{{ url_for('evidence_file', cid=c.id, digest=f.sha256) }}" target="_blank" rel="noopener">{{ f.title or f.original_name }}</a> <span class="hint">{{ f.server_time[8:10] }}-{{ f.server_time[5:7] }} {{ f.server_time[11:16] }}</span></li>{% endfor %}
{% if pr.story %}<li class="ok">Relato del asegurado</li>{% endif %}
</ul>
{% if pr.requested and not pr.finished %}<p class="hint" style="margin:8px 0 0">Se le pidió: {{ pr.requested|join(', ') }}.</p>{% endif %}
{% if not pr.finished and not cap_state %}
{% if cap_local %}<div class="flash bad" style="margin:0 0 10px;font-size:13px"><b>El asegurado no podrá abrir este enlace.</b>
Apunta a {{ 'la red interna' if cap_lan else 'este computador' }} ({{ cap_url.split('/c/')[0] }}), por eso WhatsApp tampoco lo muestra como enlace.
Cierre Veritas y ábralo con <code>iniciar_publico.bat</code>: el enlace pasa a ser https://…trycloudflare.com y funciona desde cualquier celular.
En producción, configure el dominio de la compañía en Configuración.</div>{% endif %}
<div class="sharebtns">
{% if wa_url %}<a class="btn pri" href="{{ wa_url }}" target="_blank" rel="noopener">Enviar por WhatsApp</a>{% endif %}
{% if mail_url %}<a class="btn" href="{{ mail_url }}">Enviar por correo</a>{% endif %}
<button class="btn" type="button" onclick="navigator.clipboard.writeText(document.getElementById('capmsg').value);this.textContent='Mensaje copiado'">Copiar mensaje</button></div>
{% if not wa_url %}<p class="hint" style="margin:6px 0 0">Sin teléfono en la declaración: copie el mensaje y envíelo por el medio que use.</p>{% endif %}
<textarea id="capmsg" readonly rows="4" class="hint" style="margin-top:10px;font-size:12.5px">{{ share_msg }}</textarea>
<details style="margin-top:8px"><summary class="hint">Enlace, código QR y código</summary>
<div style="display:flex;gap:12px;align-items:flex-start;margin-top:8px">{% if cap_qr %}<img src="data:image/png;base64,{{ cap_qr }}" alt="Código QR del enlace" style="width:104px;height:104px;border:1px solid var(--line);border-radius:8px;flex:none">{% endif %}
<dl class="kv"><dt>Código</dt><dd style="letter-spacing:.12em">{{ cap.code }}</dd><dt>Vence</dt><dd>{{ cap.expires[:16]|replace('T',' ') }}</dd></dl></div>
<input readonly value="{{ cap_url }}" onclick="this.select()" class="mono" style="margin-top:8px" aria-label="Enlace">
</details>
{% endif %}
<details style="margin-top:10px"><summary class="hint">{{ 'Pedir más antecedentes (enlace nuevo)' if pr.finished or cap_state else 'Cambiar documentos o renovar el enlace' }}</summary>
<form method="post" action="{{ url_for('capture_link', cid=c.id) }}" style="margin-top:8px"><input type="hidden" name="docs_sent" value="1">
{% for k, v in doc_types.items() if k != 'otro' %}<label style="font-weight:400;display:flex;gap:6px;margin:3px 0"><input type="checkbox" name="docs" value="{{ k }}" style="width:auto" {{ 'checked' if k in cap.doc_ids }}> {{ v }}</label>{% endfor %}
<input name="docs_custom" value="{{ (cap.custom or [])|join('; ') }}" placeholder="Otros documentos (separe con punto y coma)" style="font-size:12.5px;margin-top:4px">
<button class="btn sm" type="submit" style="margin-top:6px">Crear enlace nuevo</button>
<p class="hint" style="margin:6px 0 0">El enlace anterior deja de funcionar. Lo ya recibido se conserva.</p></form></details>
{% else %}
<p class="hint" style="margin:0 0 10px">Envíe al asegurado un enlace donde toma las fotos con la cámara en vivo y sube sus documentos originales, sin pasar por WhatsApp.</p>
<form method="post" action="{{ url_for('capture_link', cid=c.id) }}"><input type="hidden" name="docs_sent" value="1">
{% for k, v in doc_types.items() if k != 'otro' %}<label style="font-weight:400;display:flex;gap:6px;margin:3px 0"><input type="checkbox" name="docs" value="{{ k }}" style="width:auto" {{ 'checked' if k in default_docs }}> {{ v }}</label>{% endfor %}
<input name="docs_custom" placeholder="Otros documentos (separe con punto y coma)" style="font-size:12.5px;margin-top:4px">
<button class="btn pri" type="submit" style="width:100%;margin-top:8px">{{ icon('link', 15, '#fff') }}Crear enlace para el asegurado</button></form>
{% endif %}
</div></section>
<section class="panel" id="decision"><div class="ph"><h2>Decisión del liquidador</h2></div><div class="pb">
<form method="post" action="{{ url_for('decide', cid=c.id) }}" style="display:grid;gap:10px">
<select name="decision" required style="width:100%">{% for k, v in decisions.items() %}<option value="{{ k }}" {{ 'selected' if c.decision == k }}>{{ v }}</option>{% endfor %}</select>
{% if current_user %}<input type="hidden" name="actor" value="{{ current_user.name }}">{% else %}<input name="actor" placeholder="Su nombre" required>{% endif %}<input name="nota" placeholder="Nota (opcional)">
<button class="btn pri" type="submit">Registrar decisión</button></form>
{% if history %}<div style="margin-top:14px;border-top:1px solid var(--line);padding-top:10px">{% for h in history|reverse %}
<div class="hint" style="margin:4px 0"><b class="dec {{ h.subject }}">{{ h.data.label }}</b> · {{ h.actor }} · {{ h.ts[:16]|replace('T',' ') }} UTC{% if h.data.note %}<br>{{ h.data.note }}{% endif %}</div>{% endfor %}</div>
{% else %}<p class="hint" style="margin:10px 0 0">Cada decisión queda en la cadena de custodia con su autor y sirve para medir la precisión de Veritas.</p>{% endif %}
</div></section>
<section class="panel"><div class="ph"><h2>Evidencia</h2></div><div class="pb">
<form method="post" action="{{ url_for('add_photos', cid=c.id) }}" enctype="multipart/form-data" data-busy="Analizando…" style="display:grid;gap:10px">
<input type="file" name="fotos" multiple accept="image/*,.heic,.pdf,application/pdf,.txt,.zip" required aria-label="Fotos o documentos">
<button class="btn" type="submit">{{ icon('upload', 15) }}Agregar y reanalizar</button></form>
<p class="hint" style="margin:10px 0 0">{{ c.photos }} foto(s) en el caso. Se guardan los originales, sin modificarlos.</p>
{% if files %}<details style="margin-top:10px"{{ ' open' if request.args.get('archivos') }}><summary class="hint">Archivos del caso ({{ files|length }}) · quitar uno agregado por error</summary>
<ul class="evfiles">{% for f in files %}<li class="{{ 'off' if f.excluded }}">
<a href="{{ url_for('evidence_file', cid=c.id, digest=f.digest) }}" target="_blank" rel="noopener">{{ f.title }}</a>
<span class="hint">{{ f.kind }} · {{ f.who }}</span>
{% if f.excluded %}<div class="hint">Quitado del análisis por {{ f.excluded.actor }}: {{ f.excluded.data.reason }}</div>
{% if can('editar_siniestros') %}<form method="post" action="{{ url_for('evidence_restore', cid=c.id, digest=f.digest) }}"><button class="linkbtn" type="submit">Restaurar</button></form>{% endif %}
{% elif can('editar_siniestros') %}<details><summary class="linkbtn">Quitar</summary>
<form method="post" action="{{ url_for('evidence_exclude', cid=c.id, digest=f.digest) }}" style="display:grid;gap:6px;margin-top:6px">
<select name="motivo" required><option value="">Motivo…</option><option>Se agregó por error</option><option>Es de otro siniestro</option><option>Está duplicado</option><option>Archivo ilegible o dañado</option></select>
<button class="btn sm" type="submit">Quitar del análisis</button></form></details>{% endif %}</li>{% endfor %}</ul>
<p class="hint" style="margin:6px 0 0">Quitar no borra el archivo: queda guardado y registrado en la cadena de custodia (quién, cuándo y por qué), pero deja de analizarse y de aparecer en el informe.</p></details>{% endif %}</div></section>
{% if accesos %}<section class="panel"><div class="ph"><h2>Accesos a este caso</h2></div>
<table class="mini">{% for e in accesos %}<tr><td class="nowrap hint">{{ e.ts[5:16]|replace('T',' ') }}</td><td>{{ e.user }}</td>
<td class="hint">{{ {'ver_caso': 'abrió', 'decision': 'decidió'}.get(e.action, e.action) }}</td></tr>{% endfor %}</table></section>{% endif %}
</aside></div>
{% endblock %}"""


REDES = r"""{% extends "base.html" %}{% block title %}Redes{% endblock %}
{% block heading %}<h1>Redes de fraude</h1><p class="sub">Grupos de siniestros de distintos asegurados conectados por teléfono, correo, cuenta bancaria,
fotos, documentos o relatos compartidos. Ordenados por tamaño y monto reclamado.</p>{% endblock %}
{% block actions %}<a class="btn" href="{{ url_for('export_xlsx', what='redes') }}">{{ icon('download', 15) }}Excel</a>
<a class="btn" href="{{ url_for('import_view') }}">{{ icon('upload', 15) }}Importar historial</a>{% endblock %}
{% block body %}
<div class="tiles">
<div class="tile accent-red"><div class="lbl">Redes</div><b>{{ rings|length }}</b><span>de 3 o más siniestros</span></div>
<div class="tile"><div class="lbl">Pares vinculados</div><b>{{ pairs|length }}</b><span>2 siniestros conectados</span></div>
<div class="tile"><div class="lbl">Siniestros involucrados</div><b>{{ involved }}</b><span>en redes y pares</span></div>
<div class="tile accent-blue"><div class="lbl">Monto reclamado</div><b>${{ money(total) }}</b><span>en redes y pares</span></div>
</div>
{% for c in comps %}
<section class="panel netcard"><div class="ph"><h2>{{ 'Red' if c.members|length >= 3 else 'Par vinculado' }} de {{ c.members|length }} siniestros
· {{ c.people }} asegurados</h2><span class="r"><b>${{ money(c.monto) }}</b> <span class="hint">reclamados · {{ c.first[:10] }} a {{ c.last[:10] }}</span></span></div><div class="pb">
<div class="reasons">{% for r, n in c.reasons %}<span>{{ r }} ×{{ n }}</span>{% endfor %}</div>
{{ c.svg|safe }}<p class="hint" style="margin:0 0 6px">Punto rojo: derivado a investigación · ámbar: revisión · verde: sin alertas. Cada línea es un dato o evidencia compartida.</p>
</div><div class="scroll"><table><tr><th>Siniestro</th><th>Asegurado</th><th>Fecha</th><th class="num">Monto</th><th>Recomendación</th><th>Decisión</th></tr>
{% for m in c.members %}{% set i = c.info[m] %}<tr class="row" onclick="location.href='{{ url_for('case_view', cid=i.id) }}'">
<td style="white-space:nowrap"><a href="{{ url_for('case_view', cid=i.id) }}"><b>{{ m }}</b></a></td><td>{{ i.asegurado }}</td>
<td class="nowrap">{{ (i.fecha or '')[:10] }}</td><td class="num nowrap">{{ '$' ~ money(i.monto) if i.monto else '—' }}</td>
<td><span class="badge {{ i.level or 'none' }}">{{ level_text[i.level] }}</span></td><td><span class="dec {{ i.decision or '' }}">{{ i.decision_label or '—' }}</span></td></tr>{% endfor %}
</table></div></section>
{% else %}
<div class="card empty"><h2>No se encontraron redes</h2><p>Las redes aparecen cuando hay siniestros de distintos asegurados que comparten datos o evidencia.
Importe el historial para buscarlas en toda la cartera.</p><a class="btn pri" href="{{ url_for('import_view') }}">Importar historial</a></div>
{% endfor %}
{% endblock %}"""

METRICAS = r"""{% extends "base.html" %}{% block title %}Métricas{% endblock %}
{% block heading %}<h1>Métricas</h1><p class="sub">Desempeño de Veritas frente a las decisiones finales de los liquidadores. "Alerta" = recomendación de derivar
a investigación. Solo cuentan los siniestros con decisión de fraude confirmado o legítimo.</p>{% endblock %}
{% block actions %}<a class="btn" href="{{ url_for('export_xlsx', what='metricas') }}">{{ icon('download', 15) }}Excel</a>{% endblock %}
{% block body %}
{% if m.tp + m.fn + m.fp + m.tn == 0 %}
<div class="card empty"><h2>Aún no hay decisiones para medir</h2><p>Registre decisiones en los siniestros o importe un historial con la columna "resultado".</p>
<a class="btn pri" href="{{ url_for('import_view') }}">Importar historial</a></div>
{% else %}
<div class="tiles">
<div class="tile accent-grn"><div class="lbl">Detección</div><div class="big">{{ m.recall }}%</div><span>de los fraudes confirmados fueron detectados ({{ m.tp }} de {{ m.tp + m.fn }})</span></div>
<div class="tile accent-blue"><div class="lbl">Precisión</div><div class="big">{{ m.precision }}%</div><span>de las alertas resultaron fraude ({{ m.tp }} de {{ m.tp + m.fp }})</span></div>
<div class="tile accent-amb"><div class="lbl">Falsas alarmas</div><div class="big">{{ m.false_alarm }}%</div><span>de los siniestros legítimos recibió una alerta ({{ m.fp }} de {{ m.fp + m.tn }})</span></div>
<div class="tile accent-red"><div class="lbl">Monto detectado</div><div class="big">${{ money(m.monto_detectado) }}</div><span>reclamados en fraudes detectados, de ${{ money(m.monto_fraude) }} en fraudes confirmados</span></div>
</div>
<div class="cols2">
<div class="card"><h2 style="margin:0 0 14px">Aciertos y errores</h2>
<table class="matrix"><tr><th></th><th>Veritas alertó</th><th>Veritas no alertó</th></tr>
<tr><td><b style="font-size:13.5px;display:inline">Fraude confirmado</b></td><td class="cell-good"><b>{{ m.tp }}</b><small>detectados</small></td><td class="cell-bad"><b>{{ m.fn }}</b><small>no detectados</small></td></tr>
<tr><td><b style="font-size:13.5px;display:inline">Legítimo</b></td><td class="cell-bad"><b>{{ m.fp }}</b><small>falsas alarmas</small></td><td class="cell-good"><b>{{ m.tn }}</b><small>correctamente sin alerta</small></td></tr>
</table>
<p class="hint">{{ m.total }} siniestros en total · {{ m.decisions.get('pendiente', 0) }} sin decisión · {{ m.decisions.get('rechazado', 0) }} rechazados por otra causa.</p></div>
<div class="card"><h2 style="margin:0 0 14px">Señales más frecuentes</h2>
<div class="bars">{% set mx = (m.rules[0][1] if m.rules else 1) %}{% for r, n in m.rules[:8] %}
<span>{{ rule_names.get(r, r) }}</span><div class="track" title="{{ rule_names.get(r, r) }}: {{ n }} siniestro(s)"><div class="bar" style="width:calc((100% - 40px) * {{ n / mx }})"></div>
<span class="val" style="left:calc((100% - 40px) * {{ n / mx }})">{{ n }}</span></div>{% endfor %}</div>
<p class="hint">Cantidad de siniestros en que apareció cada señal.</p></div>
</div>
<div class="cols2" style="margin-top:16px">
<div class="card"><h2 style="margin:0 0 4px">Alertas pendientes de decisión</h2><p class="hint" style="margin:0 0 8px">
{{ m.pendientes_alerta|length }} siniestros derivados sin decisión · ${{ money(m.monto_pendiente_alerta) }} reclamados</p>
<table>{% for r in m.pendientes_alerta[:8] %}<tr class="row" onclick="location.href='{{ url_for('case_view', cid=r.id) }}'"><td style="white-space:nowrap"><a href="{{ url_for('case_view', cid=r.id) }}"><b>{{ r.numero }}</b></a></td>
<td><span class="risk bad" style="--w:{{ r.score }}%"><i></i>{{ r.score }}</span></td><td class="num">${{ money(r.monto) }}</td></tr>{% else %}<tr><td class="hint">No hay alertas pendientes.</td></tr>{% endfor %}</table></div>
<div class="card"><h2 style="margin:0 0 4px">Para mejorar</h2><p class="hint" style="margin:0 0 8px">Revisar estos casos ayuda a ajustar los umbrales.</p>
<table>{% for r in m.missed %}<tr class="row" onclick="location.href='{{ url_for('case_view', cid=r.id) }}'"><td style="white-space:nowrap"><a href="{{ url_for('case_view', cid=r.id) }}"><b>{{ r.numero }}</b></a></td><td>Fraude no detectado</td></tr>{% endfor %}
{% for r in m.false_alarms %}<tr class="row" onclick="location.href='{{ url_for('case_view', cid=r.id) }}'"><td style="white-space:nowrap"><a href="{{ url_for('case_view', cid=r.id) }}"><b>{{ r.numero }}</b></a></td><td>Falsa alarma · {{ r.rules|map('extract', rule_names)|join(', ') if r.rules else '' }}</td></tr>{% endfor %}</table></div>
</div>
{% endif %}
{% endblock %}"""

IMPORTAR = r"""{% extends "base.html" %}{% block title %}Importar historial{% endblock %}
{% block heading %}<h1>Importar historial</h1><p class="sub">Cargue siniestros pasados desde Excel o CSV. Veritas crea un caso por fila, los analiza en orden
cronológico y busca redes en toda la cartera. El archivo original queda guardado con su hash.</p>{% endblock %}
{% block actions %}<a class="btn" href="{{ url_for('template_download') }}">{{ icon('download', 15) }}Descargar plantilla</a>{% endblock %}
{% block body %}
{% if report %}
<div class="card" style="margin-bottom:16px">
{% if report.error %}<div class="flash bad" style="margin:0">{{ report.error }}</div>{% else %}
<h2 style="margin:0 0 14px">Resultado de la importación · {{ report.file }}</h2>
<div class="tiles" style="margin-bottom:8px">
<div class="tile accent-blue"><b>{{ report.imported|length }}</b><span>siniestros importados de {{ report.rows }} filas</span></div>
<div class="tile accent-red"><b>{{ report.levels.bad }}</b><span>derivar a investigación</span></div>
<div class="tile accent-amb"><b>{{ report.levels.warn }}</b><span>revisión manual</span></div>
<div class="tile"><b>{{ nets }}</b><span>redes y pares vinculados en la cartera</span></div>
</div>
<p class="hint">Columnas reconocidas: {{ report.recognized|join(', ') }}{% if report.ignored %} · ignoradas: {{ report.ignored|join(', ') }}{% endif %}<br>
Huella del archivo (SHA-256): <code>{{ report.sha256 }}</code></p>
{% if report.skipped %}<details><summary>{{ report.skipped|length }} fila(s) omitida(s)</summary><ul class="hint">{% for r, why in report.skipped[:50] %}<li>Fila {{ r }}: {{ why }}</li>{% endfor %}</ul></details>{% endif %}
<div class="toolbar" style="margin-top:10px"><a class="btn pri" href="{{ url_for('networks') }}">Ver redes</a><a class="btn" href="{{ url_for('metrics_view') }}">Ver métricas</a>
<a class="btn" href="{{ url_for('index') }}">Ver siniestros</a></div>{% endif %}
</div>{% endif %}
<div class="cols2">
<form class="card" method="post" enctype="multipart/form-data" data-busy="Importando y analizando…">
<h2 style="margin:0 0 14px">Subir archivo</h2>
<input type="file" name="archivo" accept=".csv,.xlsx,.xlsm,text/csv" required style="margin-bottom:10px">
{% if not current_user %}<label>Responsable de la importación</label>{% endif %}{% if current_user %}<input type="hidden" name="actor" value="{{ current_user.name }}">{% else %}<input name="actor" placeholder="Su nombre" required style="margin-bottom:12px">{% endif %}
<button class="btn pri" type="submit">Importar y analizar</button>
<p class="hint">Obligatorias: número de siniestro y fecha. Opcionales: todos los campos de la plantilla. La columna <b>resultado</b>
(fraude, pagado, rechazado) se registra como decisión y permite medir la detección.</p></form>
<div class="card"><h2 style="margin:0 0 10px">¿Primera vez?</h2>
<p>Descargue la plantilla con las columnas esperadas, o pruebe con un historial ficticio de 147 siniestros que esconde dos redes.</p>
<div class="toolbar"><a class="btn" href="{{ url_for('template_download') }}">Descargar plantilla CSV</a>
<form method="post" action="{{ url_for('import_demo') }}" data-busy="Importando…"><button class="btn" type="submit">Importar historial de ejemplo</button></form></div>
<p class="hint">Encabezados flexibles ("N° Siniestro", "Relato", "Monto", "Cuenta pago"...), fechas chilenas (20-09-2026) y separador coma o punto y coma.</p></div>
</div>
{% endblock %}"""


FOTO = r"""{% extends "base.html" %}{% block title %}Revisar foto{% endblock %}
{% block heading %}<h1>Revisar una foto</h1>
<p class="sub">Revisa metadatos y píxeles: fechas cambiadas, ediciones, zonas pegadas o clonadas y pantallazos. No se crea un caso ni se guarda la foto.</p>{% endblock %}
{% block body %}
<form class="card" method="post" enctype="multipart/form-data" data-busy="Analizando…" style="margin-bottom:20px"><div class="formrow">
<div><label for="fotos">Fotos</label><input id="fotos" type="file" name="fotos" accept="image/*" multiple required></div>
<div><label for="fecha">Fecha del siniestro <span class="hint">(opcional)</span></label><input id="fecha" type="datetime-local" name="fecha"></div>
<button class="btn pri" type="submit">Revisar</button></div></form>
{% for r in results %}
<section class="panel" style="margin-bottom:20px">
<div class="ph"><h2>{{ r.name }}</h2><span class="r">
{% if r.level == 'bad' %}<span class="badge bad">Señales graves</span>{% elif r.level == 'warn' %}<span class="badge warn">Revisar</span>
{% else %}<span class="badge ok">Sin señales</span>{% endif %}</span></div>
<div class="pb split">
<div>{% for f in r.findings %}<div class="finding {{ f.severity }}"><span class="sev {{ f.severity }}">{{ f.severity|upper }}</span><b>{{ f.title.split(' (')[0] }}</b><p>{{ f.summary }}</p></div>
{% else %}<p style="margin:0">No se encontraron señales. Eso no prueba que la foto sea auténtica: una edición cuidadosa puede no dejar rastros.</p>{% endfor %}
{% if r.marked %}<h3 class="cat">Zonas marcadas</h3>
<img src="data:image/png;base64,{{ r.marked }}" alt="Zonas sospechosas marcadas" style="max-width:100%;border-radius:8px;border:1px solid var(--line)">{% endif %}</div>
<div><h3 class="cat" style="margin-top:0">Datos leídos</h3><dl class="kv">{% for k, v in r.rows %}<dt>{{ k }}</dt><dd>{{ v }}</dd>{% endfor %}</dl></div>
</div></section>
{% endfor %}
{% endblock %}"""

CAPTURE = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Siniestro {{ numero }} · entrega de antecedentes</title>
<style>
:root{--ink:#0f1b2d;--muted:#5d6b7c;--line:#e3e8ef;--accent:#14508c;--red:#b42318;--redbg:#fef3f2;--grn:#067647;--grnbg:#ecfdf3}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink);background:#f3f5f8}
header{background:#0b1f36;color:#fff;padding:16px 18px 18px}header b{font-size:17px;display:block}header div{opacity:.75;font-size:13.5px}
.bar{height:6px;background:rgba(255,255,255,.18);border-radius:9px;margin-top:12px;overflow:hidden}.bar i{display:block;height:100%;background:#5aa0e6;width:0;transition:width .3s}
.bartxt{font-size:12.5px;opacity:.8;margin-top:5px}
main{padding:14px;max-width:560px;margin:0 auto}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:14px}
.card h2{font-size:17px;margin:0 0 4px;display:flex;align-items:center;gap:10px}
.card h2 .n{width:26px;height:26px;border-radius:50%;background:#eaf2fb;color:var(--accent);display:grid;place-items:center;font-size:14px;flex:none}
.card h2 .n.ok{background:var(--grnbg);color:var(--grn)}
.card p.lead{margin:0 0 12px;color:var(--muted);font-size:14.5px}
.opt{font-size:12px;font-weight:600;color:var(--muted);background:#f2f4f7;border-radius:99px;padding:1px 8px;margin-left:auto}
.btn{display:block;width:100%;border:0;border-radius:12px;padding:14px;font:700 16px system-ui;background:var(--accent);color:#fff;text-align:center;cursor:pointer}
.btn.sec{background:#fff;color:var(--accent);border:1.5px solid #b9cde4}.btn:disabled{opacity:.5}
.pick{display:block;border:2px dashed #b9cde4;border-radius:12px;padding:16px;text-align:center;color:var(--accent);font-weight:700;cursor:pointer;background:#f7faff}
.pick small{display:block;font-weight:400;color:var(--muted);font-size:13px;margin-top:2px}
input[type=file]{display:none}
.pending{display:grid;gap:10px;margin-top:12px}
.row{display:grid;grid-template-columns:64px 1fr;gap:10px;align-items:center;border:1px solid var(--line);border-radius:12px;padding:10px;background:#fff}
.row .th{width:64px;height:64px;border-radius:8px;background:#eef2f7;object-fit:cover;display:grid;place-items:center;font-size:12px;font-weight:700;color:var(--muted)}
.row input{width:100%;font:inherit;font-size:15px;border:1px solid #cfd6de;border-radius:8px;padding:9px 10px}
.row input.bad{border-color:var(--red);background:var(--redbg)}
.row .fn{font-size:12px;color:var(--muted);margin-top:3px;overflow-wrap:anywhere}.row .er{font-size:12.5px;color:var(--red);margin-top:3px}
.sent{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:6px}
.sent li{display:flex;gap:8px;align-items:baseline;font-size:14.5px;background:var(--grnbg);color:var(--grn);border-radius:8px;padding:7px 10px}
.sent li small{color:var(--muted);margin-left:auto;font-size:12px}
.sent li .rm{border:0;background:none;color:var(--red);font:inherit;font-size:13px;font-weight:600;padding:0 0 0 6px;cursor:pointer;text-decoration:underline}
.need{font-size:14px;color:var(--ink);background:#f7faff;border-radius:10px;padding:10px 12px;margin:0 0 12px}.need ul{margin:4px 0 0;padding-left:18px}
textarea{width:100%;font:inherit;font-size:15px;border:1px solid #cfd6de;border-radius:10px;padding:10px;min-height:110px}
.msg{padding:10px 12px;border-radius:10px;margin:10px 0;font-size:14.5px}.err{background:var(--redbg);color:var(--red)}.ok{background:var(--grnbg);color:var(--grn)}
.small{font-size:13px;color:var(--muted)}
.done-card{text-align:center;padding:28px 18px}.done-card .big{font-size:44px}
[hidden]{display:none!important}
</style></head><body>
<header><b>{{ empresa or 'Entrega de antecedentes' }}</b><div>Siniestro {{ numero }}{% if nombre %} · {{ nombre }}{% endif %}</div>
{% if not error %}<div class="bar"><i id="bar"></i></div><div class="bartxt" id="bartxt"></div>{% endif %}</header>
<main>
{% if error %}<div class="card"><div class="msg {{ 'ok' if finished else 'err' }}">{{ error }}</div></div>{% else %}
<div class="card"><p style="margin:0">Aquí puede entregar las fotos y documentos de su siniestro. <b>No los envíe por WhatsApp:</b>
WhatsApp borra la fecha y el lugar de cada foto. Puede avanzar por partes y volver a este enlace hasta el {{ vence }}.</p></div>

{% for sec in sections %}
<section class="card" id="sec-{{ sec.kind }}"><h2><span class="n" id="n-{{ sec.kind }}">{{ loop.index }}</span>{{ sec.title }}</h2>
<p class="lead">{{ sec.lead }}</p>
{% if sec.kind == 'doc' and requested %}<div class="need">Le pedimos:<ul>{% for r in requested %}<li>{{ r }}</li>{% endfor %}</ul></div>{% endif %}
<label class="pick">{{ sec.button }}<small>{{ sec.hint }}</small><input type="file" data-kind="{{ sec.kind }}" accept="{{ sec.accept }}" multiple></label>
<div class="pending" id="pend-{{ sec.kind }}"></div>
<div class="msg err" id="msg-{{ sec.kind }}" hidden></div>
<button class="btn" id="up-{{ sec.kind }}" data-kind="{{ sec.kind }}" style="margin-top:10px" hidden>Subir</button>
<ul class="sent" id="sent-{{ sec.kind }}">{% for f in sec.files %}<li data-id="{{ f.sha256 }}" data-kind="{{ sec.kind }}">✓ {{ f.title or f.original_name }}<small>{{ f.server_time[11:16] }}</small><button type="button" class="rm" aria-label="Quitar {{ f.title }}">Quitar</button></li>{% endfor %}</ul>
</section>
{% endfor %}

<section class="card"><h2><span class="n">3</span>¿Qué pasó? <span class="opt">opcional</span></h2>
<p class="lead">Cuéntelo con sus palabras: dónde iba, a qué hora, qué ocurrió.</p>
<textarea id="story" maxlength="8000" placeholder="Escriba aquí…">{{ story or '' }}</textarea>
<button class="btn sec" id="savestory" style="margin-top:10px">Guardar relato</button></section>

<div id="globalmsg" class="msg" hidden></div>
<button class="btn" id="finish" style="margin-bottom:24px">Enviar todo</button>
<p class="small" style="text-align:center;margin:-10px 0 30px">Al enviar, su ejecutivo recibe los antecedentes. Cada archivo queda registrado con la hora de recepción.</p>
<div class="card done-card" id="done" hidden><div class="big">✓</div><h2 style="justify-content:center">Recibimos sus antecedentes</h2>
<p class="lead">Gracias. Su ejecutivo revisará la información y lo contactará si necesita algo más. Ya puede cerrar esta página.</p></div>
{% endif %}
</main>
{% if not error %}
<script>
const $ = id => document.getElementById(id);
const base = location.pathname.replace(/\/$/, "");
const count = {photo: {{ sections[0].files|length }}, doc: {{ sections[1].files|length }}};
const queue = {photo: [], doc: []};
function bar(){ const ok = (count.photo > 0) + (count.doc > 0);
  $("bar").style.width = (50*ok) + "%"; $("bartxt").textContent = ok + " de 2 pasos completos";
  for (const k of ["photo", "doc"]) { const n = $("n-" + k); n.className = "n" + (count[k] ? " ok" : ""); n.textContent = count[k] ? "✓" : (k === "photo" ? "1" : "2"); } }
function say(t, bad){ const el = $("globalmsg"); el.hidden = false; el.className = "msg " + (bad ? "err" : "ok"); el.textContent = t; }
bar();
function rmButton(){ const b = Object.assign(document.createElement("button"), {type: "button", className: "rm", textContent: "Quitar"}); return b; }
document.querySelectorAll(".sent").forEach(ul => ul.addEventListener("click", async ev => {
  const b = ev.target.closest(".rm"); if (!b) return;
  const li = b.closest("li");
  if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "¿Quitar? Toque de nuevo"; setTimeout(() => { b.dataset.sure = ""; b.textContent = "Quitar"; }, 4000); return; }
  b.disabled = true; const fd = new FormData(); fd.append("id", li.dataset.id);
  const r = await fetch(base + "/quitar", {method:"POST", body:fd}); const j = await r.json();
  if (!r.ok) { say(j.error, true); b.disabled = false; return; }
  count[li.dataset.kind]--; li.remove(); bar(); say("Archivo quitado. Si se equivocó, súbalo de nuevo.", false);
}));
document.querySelectorAll("input[type=file]").forEach(inp => inp.onchange = () => {
  const kind = inp.dataset.kind, box = $("pend-" + kind);
  for (const f of inp.files) {
    const row = document.createElement("div"); row.className = "row";
    const isImg = f.type.startsWith("image/") && !/heic|heif/i.test(f.type);
    const th = isImg ? Object.assign(document.createElement("img"), {className: "th", src: URL.createObjectURL(f)})
                     : Object.assign(document.createElement("div"), {className: "th", textContent: (f.name.split(".").pop() || "").toUpperCase()});
    const right = document.createElement("div");
    const t = Object.assign(document.createElement("input"), {placeholder: kind === "photo" ? "Título (ej: Parachoques trasero)" : "Título (ej: Licencia de conducir)", maxLength: 80});
    t.oninput = () => t.classList.remove("bad");
    right.append(t, Object.assign(document.createElement("div"), {className: "fn", textContent: f.name}));
    row.append(th, right); box.appendChild(row);
    queue[kind].push({file: f, input: t, row: row});
  }
  inp.value = ""; $("up-" + kind).hidden = queue[kind].length === 0;
  if (queue[kind].length) queue[kind][queue[kind].length - 1].input.focus();
});
document.querySelectorAll("button[id^=up-]").forEach(btn => btn.onclick = async () => {
  const kind = btn.dataset.kind;
  const missing = queue[kind].filter(q => q.input.value.trim().length < 3);
  missing.forEach(q => q.input.classList.add("bad"));
  const m = $("msg-" + kind);
  if (missing.length) { missing[0].input.focus(); m.hidden = false; m.textContent = "Escriba un título para cada " + (kind === "photo" ? "foto" : "documento") + " antes de subir."; return; }
  m.hidden = true;
  btn.disabled = true; btn.textContent = "Subiendo…";
  for (const q of [...queue[kind]]) {
    const fd = new FormData(); fd.append("archivo", q.file, q.file.name); fd.append("kind", kind); fd.append("titulo", q.input.value.trim());
    try { const r = await fetch(base + "/archivo", {method:"POST", body:fd}); const j = await r.json(); if (!r.ok) throw new Error(j.error || "error");
      const li = document.createElement("li"); li.innerHTML = "✓ "; li.append(j.titulo); const sm = document.createElement("small"); sm.textContent = j.hora; li.append(sm);
      li.dataset.id = j.id; li.dataset.kind = j.tipo; li.append(rmButton());
      $("sent-" + j.tipo).appendChild(li); count[j.tipo]++; q.row.remove(); queue[kind].splice(queue[kind].indexOf(q), 1);
    } catch(e) { let er = q.row.querySelector(".er"); if (!er) { er = document.createElement("div"); er.className = "er"; q.row.lastChild.append(er); } er.textContent = e.message; }
  }
  btn.disabled = false; btn.textContent = "Subir"; btn.hidden = queue[kind].length === 0; bar();
  if (!queue[kind].length) $("globalmsg").hidden = true;
});
$("savestory").onclick = async () => {
  const fd = new FormData(); fd.append("texto", $("story").value);
  const r = await fetch(base + "/relato", {method:"POST", body:fd}); const j = await r.json();
  say(r.ok ? "Relato guardado." : j.error, !r.ok);
};
$("finish").onclick = async () => {
  if (queue.photo.length || queue.doc.length) { say("Tiene archivos elegidos sin subir: escríbales un título y presione Subir.", true); return; }
  const falta = [count.photo ? "" : "fotos", count.doc ? "" : "documentos"].filter(Boolean);
  if (falta.length && !confirm("No ha subido " + falta.join(" ni ") + ". ¿Enviar de todas formas?")) return;
  if ($("story").value.trim().length >= 10) { const fd = new FormData(); fd.append("texto", $("story").value); await fetch(base + "/relato", {method:"POST", body:fd}); }
  const r = await fetch(base + "/terminar", {method:"POST"}); const j = await r.json();
  if (!r.ok) { say(j.error, true); return; }
  document.querySelectorAll("main > :not(#done)").forEach(e => e.hidden = true); $("done").hidden = false; $("bar").style.width = "100%"; $("bartxt").textContent = "Enviado";
  window.scrollTo(0, 0);
};
</script>{% endif %}
</body></html>"""

CONFIG = r"""{% extends "base.html" %}{% block title %}Configuración{% endblock %}
{% block heading %}<h1>Configuración</h1><p class="sub">Datos de su empresa y servicios externos opcionales para revisar fotos.</p>{% endblock %}
{% block body %}
<form method="post" class="cols2" style="align-items:start">
<section class="panel"><div class="ph"><h2>Empresa</h2></div><div class="pb">
<label for="empresa">Nombre en los informes de investigación</label><input id="empresa" name="empresa" value="{{ cfg.empresa or '' }}" placeholder="Nombre de la consultora o compañía">
<label for="dp" style="margin-top:12px">Dirección pública del portal del asegurado</label><input id="dp" name="direccion_publica" value="{{ cfg.direccion_publica or '' }}" placeholder="https://siniestros.sucompania.cl" autocomplete="off">
<p class="hint" style="margin:4px 0 0">Dominio con HTTPS por el que los asegurados abren el enlace. Déjelo vacío en la demo: <code>iniciar_publico.bat</code> crea una dirección temporal.</p>
</div></section>
<section class="panel"><div class="ph"><h2>Servicios externos para fotos</h2>
<span class="r">{% if on.ai or on.web %}<span class="badge ok">Activos</span>{% else %}<span class="badge none">Desactivados</span>{% endif %}</span></div><div class="pb" style="display:grid;gap:14px">
<div class="flash info" style="margin:0">Estos servicios reciben una copia de cada foto del siniestro. Úselos solo con autorización de la aseguradora
y después de revisar la política de datos personales del proveedor. Son de pago por uso; cada foto se consulta una sola vez.</div>
<div><b>Detector de imágenes generadas con IA</b> <span class="hint">· Sightengine, modelo genai</span>
<div class="grid" style="margin-top:8px;gap:10px"><div><label for="su">API user</label><input id="su" name="sightengine_user" value="{{ cfg.sightengine_user or '' }}" autocomplete="off"></div>
<div><label for="ss">API secret</label><input id="ss" name="sightengine_secret" type="password" value="{{ cfg.sightengine_secret or '' }}" autocomplete="off"></div></div></div>
<div><b>Búsqueda inversa en internet</b> <span class="hint">· Google Cloud Vision, detección web</span>
<div style="margin-top:8px"><label for="gv">Clave de API</label><input id="gv" name="google_vision_key" type="password" value="{{ cfg.google_vision_key or '' }}" autocomplete="off"></div></div>
<p class="hint" style="margin:0">Las claves se guardan en config.json, en la carpeta de casos de este equipo. Después de configurarlas, use Reanalizar en cada siniestro.</p>
</div></section>
<div class="full"><button class="btn pri" type="submit">Guardar configuración</button></div>
</form>
{% endblock %}"""

LOGIN = r"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ingresar · Veritas</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1f36;
font:14px/1.5 Inter,system-ui,"Segoe UI",sans-serif;color:#0f1b2d;padding:16px}
.box{background:#fff;border-radius:14px;padding:32px 30px;width:100%;max-width:380px;box-shadow:0 20px 50px rgba(0,0,0,.3)}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:22px}.brand .mark{width:36px;height:36px;border-radius:9px;
background:linear-gradient(135deg,#2f7ac4,#14508c);display:grid;place-items:center}
.brand b{letter-spacing:.14em;font-size:16px;display:block}.brand small{color:#667588;font-size:12px}
h1{font-size:18px;margin:0 0 4px}p.sub{color:#667588;margin:0 0 18px;font-size:13px}
label{display:block;font-weight:600;font-size:12.5px;margin:12px 0 5px;color:#344255}
input{font:inherit;width:100%;padding:10px 12px;border:1px solid #d3dae4;border-radius:8px}
input:focus{outline:3px solid #cfe1f5;border-color:#14508c}
button{margin-top:20px;width:100%;border:0;border-radius:8px;padding:11px;background:#14508c;color:#fff;font:600 14px Inter,system-ui,sans-serif;cursor:pointer}
button:hover{background:#0e3d6c}.err{background:#fef3f2;color:#b42318;border:1px solid #fecdca;border-radius:8px;padding:9px 12px;font-size:13px;margin-bottom:6px}
.foot{color:#667588;font-size:11.5px;margin-top:18px;text-align:center}
</style></head><body><form class="box" method="post">
<div class="brand"><span class="mark">{{ icon('shield', 20, '#fff') }}</span><span><b>VERITAS</b><small>Forense de siniestros</small></span></div>
<h1>Ingresar</h1><p class="sub">Use el usuario que le entregó el administrador.</p>
{% if error %}<div class="err">{{ error }}</div>{% endif %}
<label for="u">Usuario</label><input id="u" name="usuario" autocomplete="username" required autofocus value="{{ usuario or '' }}">
<label for="p">Contraseña</label><input id="p" name="clave" type="password" autocomplete="current-password" required>
<input type="hidden" name="next" value="{{ next or '' }}">
<button type="submit">Ingresar</button>
<div class="foot">Cada ingreso queda registrado.</div></form></body></html>"""

USERS = r"""{% extends "base.html" %}{% block title %}Usuarios{% endblock %}
{% block heading %}<h1>Usuarios y accesos</h1><p class="sub">Quién puede entrar, con qué rol, y el registro de cada ingreso y de cada caso abierto.</p>{% endblock %}
{% block body %}
{% if not users %}<div class="flash info">Todavía no hay usuarios: Veritas está abierto para cualquiera en este equipo. Cree el primer usuario
(administrador). Desde ese momento se pedirá usuario y contraseña para todo.</div>{% endif %}
<div class="layout-side" style="grid-template-columns:minmax(0,1fr) 380px">
<div style="display:grid;gap:20px">
<section class="panel"><div class="ph"><h2>Usuarios</h2><span class="hint">{{ users|length }}</span></div>
{% if users %}<div class="scroll"><table><tr><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Estado</th><th></th></tr>
{% for u, d in users.items() %}<tr><td class="mono">{{ u }}</td><td>{{ d.name }}</td><td>{{ roles[d.role] }}</td>
<td>{% if d.active is not sameas false %}<span class="badge ok">Activo</span>{% else %}<span class="badge none">Desactivado</span>{% endif %}</td>
<td style="text-align:right"><form method="post" action="{{ url_for('user_toggle', username=u) }}" style="display:inline">
<button class="btn sm ghost" type="submit">{{ 'Desactivar' if d.active is not sameas false else 'Activar' }}</button></form></td></tr>{% endfor %}</table></div>
{% else %}<div class="pb"><p class="hint" style="margin:0">Sin usuarios.</p></div>{% endif %}</section>
<section class="panel"><div class="ph"><h2>Registro de accesos</h2><span class="hint">últimos {{ log|length }}</span></div>
{% if log %}<div class="scroll" style="max-height:520px"><table><tr><th>Hora (UTC)</th><th>Usuario</th><th>Acción</th><th>Caso o detalle</th><th>Equipo</th></tr>
{% for e in log %}<tr><td class="nowrap">{{ e.ts[:16]|replace('T',' ') }}</td><td>{{ e.user }}</td><td>{{ actions.get(e.action, e.action) }}</td>
<td>{{ e.subject }}</td><td class="mono">{{ e.ip }}</td></tr>{% endfor %}</table></div>
{% else %}<div class="pb"><p class="hint" style="margin:0">Aún no hay registros.</p></div>{% endif %}</section>
</div>
<aside><section class="panel"><div class="ph"><h2>{{ 'Crear administrador' if not users else 'Crear o actualizar usuario' }}</h2></div><div class="pb">
<form method="post" style="display:grid;gap:10px">
<div><label for="nu">Usuario</label><input id="nu" name="usuario" required placeholder="ana.perez" autocomplete="off"></div>
<div><label for="nn">Nombre completo</label><input id="nn" name="nombre" required></div>
<div><label for="nr">Rol</label><select id="nr" name="rol" style="width:100%">{% for k, v in roles.items() %}<option value="{{ k }}" {{ 'selected' if not users and k == 'administrador' }}>{{ v }}</option>{% endfor %}</select></div>
<div><label for="np">Contraseña</label><input id="np" name="clave" type="password" autocomplete="new-password" {{ 'required' if not users }}>
<span class="hint">Mínimo 10 caracteres. Para actualizar un usuario existente sin cambiar su clave, déjela en blanco.</span></div>
<button class="btn pri" type="submit">Guardar usuario</button></form>
<dl class="kv" style="margin-top:16px;font-size:12.5px">{% for k, v in role_help.items() %}<dt>{{ roles[k] }}</dt><dd style="font-weight:400">{{ v }}</dd>{% endfor %}</dl>
</div></section></aside></div>
{% endblock %}"""

DENIED = r"""{% extends "base.html" %}{% block title %}Sin acceso{% endblock %}
{% block heading %}<h1>Sin acceso</h1>{% endblock %}
{% block body %}<div class="card empty"><h2>Su rol no permite abrir esta sección</h2>
<p>Si necesita acceso, pídalo al administrador de Veritas.</p></div>{% endblock %}"""

INV_LIST = r"""{% extends "base.html" %}{% block title %}Investigaciones{% endblock %}
{% block heading %}<h1>Expedientes y auditorías</h1><p class="sub">Expedientes con entrevistas y documentos, e informes auditados antes de enviarlos a la compañía.</p>{% endblock %}
{% block actions %}<a class="btn pri" href="{{ url_for('inv_new') }}">{{ icon('plus', 15, '#fff') }}Nuevo expediente</a>{% endblock %}
{% block body %}
<div class="cols2" style="margin-bottom:20px">
<form class="card" method="post" action="{{ url_for('audit_upload') }}" enctype="multipart/form-data" data-busy="Auditando…">
<h2 style="margin:0 0 6px">Auditar un informe terminado</h2><p class="hint" style="margin:0 0 10px">Suba el PDF antes de enviarlo a la compañía:
Veritas revisa contradicciones entre entrevistados, secciones que se contradicen, errores de transcripción, alertas sin respuesta y la solidez de la conclusión.</p>
<input type="file" name="pdf" accept=".pdf,application/pdf" required style="margin-bottom:8px">
{% if current_user %}<input type="hidden" name="actor" value="{{ current_user.name }}">{% else %}<input name="actor" placeholder="Su nombre" required style="margin-bottom:10px">{% endif %}<button class="btn pri" type="submit">Auditar informe</button></form>
<div class="card"><h2 style="margin:0 0 10px">Configuración y ejemplo</h2>
<form class="toolbar" method="post" action="{{ url_for('inv_settings') }}" style="margin-bottom:12px"><label style="margin:0">Nombre de su empresa en los informes</label>
<input name="empresa" value="{{ empresa }}" placeholder="Nombre de la consultora" style="flex:1"><button class="btn" type="submit">Guardar</button></form>
<form method="post" action="{{ url_for('inv_demo') }}" data-busy="Cargando…"><button class="btn" type="submit">Cargar ejemplo ficticio</button></form>
<p class="hint">Crea un expediente inventado a medio trabajar y la auditoría de un informe inventado con errores sembrados.</p></div></div>
<section class="panel" style="margin-bottom:20px"><div class="ph"><h2>Expedientes</h2><span class="hint">{{ expedientes|length }}</span></div>
{% if expedientes %}<div class="scroll"><table><tr><th>Siniestro</th><th>Aseguradora</th><th>Ocurrencia</th><th>Entrevistas</th><th>Contradicciones</th><th>Alertas respondidas</th><th>Revisión previa</th></tr>
{% for x in expedientes %}<tr class="row" onclick="location.href='{{ url_for('inv_view', cid=x.id) }}'"><td style="white-space:nowrap"><a href="{{ url_for('inv_view', cid=x.id) }}"><b>{{ x.numero }}</b></a></td>
<td>{{ x.aseguradora }}</td><td style="white-space:nowrap">{{ x.fecha }}</td><td>{{ x.interviews }}</td><td>{{ x.findings }}</td><td>{{ x.answered }} de {{ x.alerts }}</td>
<td>{% if x.pending %}<span class="badge warn">{{ x.pending }} pendiente(s)</span>{% else %}<span class="badge ok">Lista para enviar</span>{% endif %}</td></tr>{% endfor %}</table></div>
{% else %}<div class="pb"><p class="hint" style="margin:0">Aún no hay expedientes.</p></div>{% endif %}</section>
<section class="panel"><div class="ph"><h2>Informes auditados</h2><span class="hint">{{ audits|length }}</span></div>
{% if audits %}<div class="scroll"><table><tr><th>Archivo</th><th>Auditado</th><th>Por</th><th>Resultado</th></tr>
{% for x in audits %}<tr class="row" onclick="location.href='{{ url_for('audit_view', cid=x.id) }}'"><td><a href="{{ url_for('audit_view', cid=x.id) }}"><b>{{ x.name }}</b></a></td>
<td style="white-space:nowrap">{{ x.ts }}</td><td>{{ x.actor }}</td><td><span class="badge {{ 'bad' if x.alta else ('warn' if x.media else 'ok') }}">{{ x.alta }} alta · {{ x.media }} media · {{ x.baja }} baja</span></td></tr>{% endfor %}</table></div>
{% else %}<div class="pb"><p class="hint" style="margin:0">Aún no hay informes auditados.</p></div>{% endif %}</section>
{% endblock %}"""

INV_NEW = r"""{% extends "base.html" %}{% block title %}Nuevo expediente{% endblock %}
{% block crumbs %}<a href="{{ url_for('investigations') }}">Investigaciones</a> / Nuevo expediente{% endblock %}
{% block heading %}<h1>Nuevo expediente de investigación</h1><p class="sub">Todo lo que cargue queda en la cadena de custodia con su autor y hora.</p>{% endblock %}
{% block body %}
{% if error %}<div class="flash bad">{{ error }}</div>{% endif %}
<form class="card" method="post" enctype="multipart/form-data" data-busy="Creando y analizando…" style="max-width:1100px"><div class="grid">
<h3 class="sec">Siniestro</h3>
<div><label>N° de siniestro *</label><input name="numero" required value="{{ f.numero }}"></div>
<div><label>Aseguradora</label><input name="aseguradora" value="{{ f.aseguradora }}"></div>
<div><label>Tipo de siniestro</label><input name="tipo" value="{{ f.tipo or 'Colisión' }}"></div>
<div><label>Fecha y hora de ocurrencia *</label><input type="datetime-local" name="fecha_ocurrencia" required value="{{ f.fecha_ocurrencia }}"></div>
<div><label>Dirección</label><input name="direccion" value="{{ f.direccion }}"></div>
<div><label>Comuna / Ciudad</label><input name="comuna" value="{{ f.comuna }}"></div>
<div><label>Vehículo</label><input name="vehiculo" value="{{ f.vehiculo }}" placeholder="Marca modelo año - patente"></div>
<div><label>Patente</label><input name="patente" value="{{ f.patente }}"></div>
<div><label>RUT del asegurado</label><input name="rut_asegurado" value="{{ f.rut_asegurado }}"></div>
<div class="full"><label>Descripción registrada</label><textarea name="descripcion" rows="2">{{ f.descripcion }}</textarea></div>
<div class="full"><label>Alertas de la compañía <span class="hint">(una por línea)</span></label><textarea name="alertas" rows="4" placeholder="posible uso comercial&#10;pedir carta app">{{ f.alertas }}</textarea></div>
<h3 class="sec">Entrevistas</h3>
<p class="hint full" style="margin-top:-6px">Pegue la transcripción con preguntas numeradas ("1. ¿Pregunta?" y en la línea siguiente la respuesta) o en formato "P:" / "R:".</p>
<div class="full" id="ivs">{% for i in range(2) %}<div class="ivblock"><div class="grid">
<div><label>Declarante</label><input name="iv_declarante" placeholder="Nombre completo"></div>
<div><label>Rol</label><input name="iv_rol" placeholder="Asegurado, conductor, testigo…"></div>
<div><label>Fecha de entrevista</label><input name="iv_fecha" placeholder="dd/mm/aaaa hh:mm"></div>
<div class="full"><label>Transcripción</label><textarea name="iv_texto" rows="6"></textarea></div></div></div>{% endfor %}</div>
<div class="full"><button class="btn" type="button" id="addiv">+ Agregar entrevista</button></div>
<h3 class="sec">Documentos</h3>
<div class="full"><input type="file" name="docs" multiple accept=".pdf,image/*"><p class="hint">Nota de venta, permiso de circulación, SOAP, bonos, TAG… Veritas lee el texto de los PDF para cruzar kilometraje y RUT.</p></div>
<div>{% if not current_user %}<label>Su nombre *</label>{% endif %}{% if current_user %}<input type="hidden" name="actor" value="{{ current_user.name }}">{% else %}<input name="actor" required value="{{ f.actor }}">{% endif %}</div>
</div><div class="toolbar" style="margin-top:16px"><button class="btn pri" type="submit">Crear y analizar</button><a class="btn" href="{{ url_for('investigations') }}">Cancelar</a></div></form>
<script>document.getElementById('addiv').onclick=()=>{const b=document.querySelector('.ivblock').cloneNode(true);b.querySelectorAll('input,textarea').forEach(x=>x.value='');document.getElementById('ivs').appendChild(b)}</script>
{% endblock %}"""

INV_VIEW = r"""{% extends "base.html" %}{% block title %}{{ d.numero }}{% endblock %}
{% block crumbs %}<a href="{{ url_for('investigations') }}">Investigaciones</a> / {{ d.numero }}{% endblock %}
{% block heading %}<h1>Expediente {{ d.numero }}</h1>
<p class="sub">{{ d.aseguradora }} · {{ d.tipo }} · {{ (d.fecha_ocurrencia or '')|replace('T',' ') }} · {{ d.vehiculo }}</p>{% endblock %}
{% block actions %}<a class="btn" href="{{ url_for('inv_report', cid=cid) }}" target="_blank">{{ icon('external', 15) }}Ver informe</a>
<a class="btn pri" href="{{ url_for('inv_export', cid=cid) }}">{{ icon('download', 15, '#fff') }}Paquete verificable</a>{% endblock %}
{% block body %}
<div class="verdict {{ 'ok' if not review else 'warn' }}"><b>{{ 'Revisión previa: listo para enviar' if not review else 'Revisión previa: ' ~ review|length ~ ' punto(s) pendiente(s)' }}</b>
<span>{{ answered }} de {{ d.alertas|length }} alertas respondidas · {{ a.findings|length }} contradicciones detectadas</span></div>
{% if review %}<div class="card" style="margin-bottom:20px"><ul style="margin:0;padding-left:18px;display:grid;gap:4px">{% for r in review %}<li><b>{{ r.title }}</b> — <span class="hint" style="font-size:13px">{{ r.summary }}</span></li>{% endfor %}</ul></div>{% endif %}
<div class="cols2">
<div><h3 class="cat" style="margin-top:0">Contradicciones detectadas</h3>
{% for f in a.findings %}<div class="finding {{ f.severity }}"><span class="sev {{ f.severity }}">{{ f.severity|upper }}</span><b>{{ f.title }}</b><p>{{ f.summary }}</p>
{% for ev in f.evidence %}{% set v = a.index.get(ev) %}{% if v and v.kind == 'qa' %}<div class="quote"><span class="cite">{{ v.label }}</span> <b>{{ v.who }}</b> — <i>{{ v.q[:120] }}</i><br>“{{ v.text[:260] }}”</div>
{% elif v %}<div class="quote"><span class="cite">{{ v.label }}</span> documento del expediente</div>{% endif %}{% endfor %}</div>
{% else %}<p class="hint">No se detectaron contradicciones.</p>{% endfor %}</div>
<div><h3 class="cat" style="margin-top:0">Qué dice cada declarante</h3>
{% if matrix %}<div class="panel scroll"><table><tr><th>Tema</th>{% for iv in a.interviews %}<th>{{ iv.declarante }}<br><span class="hint">{{ iv.rol }}</span></th>{% endfor %}</tr>
{% for t, cells in matrix %}<tr><td><b>{{ t }}</b></td>{% for c in cells %}<td>{{ c }}</td>{% endfor %}</tr>{% endfor %}</table></div>{% endif %}
<h3 class="cat">Conclusión</h3>
<form class="alert-card" method="post" action="{{ url_for('inv_conclusion', cid=cid) }}">
<select name="recomendacion">{% for r in recommendations %}<option {{ 'selected' if a.conclusion and a.conclusion.recomendacion == r }}>{{ r }}</option>{% endfor %}</select>
<textarea name="texto" rows="4" style="margin:8px 0" placeholder="Fundamento de la recomendación">{{ a.conclusion.texto if a.conclusion else '' }}</textarea>
<div class="toolbar">{% if current_user %}<input type="hidden" name="actor" value="{{ current_user.name }}">{% else %}<input name="actor" placeholder="Su nombre" required style="width:auto;flex:1">{% endif %}<button class="btn pri" type="submit">Guardar conclusión</button></div>
{% if a.conclusion %}<p class="hint">Última versión: {{ a.conclusion.actor }} · {{ a.conclusion.ts[:16]|replace('T',' ') }} UTC</p>{% endif %}</form></div></div>
<h3 class="cat">Respuesta a las alertas</h3>
{% for al in d.alertas %}{% set i = loop.index %}{% set r = a.responses.get(i, {}) %}
<form class="alert-card" method="post" action="{{ url_for('inv_response', cid=cid, idx=i) }}"><h4>{{ i }}. {{ al }} {% if r.estado %}<span class="badge {{ 'warn' if r.estado in ('No descartado','Indeterminado') else 'ok' }}">{{ r.estado }}</span>{% endif %}</h4>
<div class="toolbar"><select name="estado" required><option value="" {{ 'selected' if not r.estado }}>Elija un estado…</option>{% for s in states %}<option {{ 'selected' if r.estado == s }}>{{ s }}</option>{% endfor %}</select>
{% if current_user %}<input type="hidden" name="actor" value="{{ current_user.name }}">{% else %}<input name="actor" placeholder="Su nombre" required style="width:auto;flex:0 1 200px">{% endif %}</div>
<textarea name="hallazgo" rows="2" style="margin:8px 0" placeholder="Hallazgo">{{ r.hallazgo }}</textarea>
<div class="hint">Evidencia sugerida (marque la que respalda el hallazgo):</div><div class="evlist">
{% for ev in (a.suggestions.get(i, []) + (r.evidencia or []))|unique %}{% set v = a.index.get(ev) %}{% if v %}<label><input type="checkbox" name="evidencia" value="{{ ev }}" {{ 'checked' if ev in (r.evidencia or []) }}>
<span><span class="cite">{{ v.label }}</span> {% if v.kind == 'qa' %}<b>{{ v.who.split()[0] }}:</b> {{ v.text[:170] }}{% else %}documento{% endif %}</span></label>{% endif %}{% endfor %}</div>
<details><summary class="hint">Toda la evidencia del expediente</summary><div class="evlist">{% for ev, v in a.index.items() %}<label><input type="checkbox" name="evidencia" value="{{ ev }}"><span><span class="cite">{{ v.label }}</span> {{ (v.q ~ ' ' ~ v.text)[:150] }}</span></label>{% endfor %}</div></details>
<button class="btn" type="submit" style="margin-top:8px">Guardar respuesta</button>{% if r.actor %}<span class="hint"> · {{ r.actor }} · {{ r.ts[:16]|replace('T',' ') }} UTC</span>{% endif %}</form>{% endfor %}
<h3 class="cat">Entrevistas y documentos</h3>
{% for iv in a.interviews %}<details class="card" style="margin-bottom:8px"><summary>E{{ iv.index }} · {{ iv.declarante }} — {{ iv.rol }} ({{ iv.items|length }} preguntas, {{ iv.fecha }})</summary>
{% for qa in iv.items %}<p style="margin:8px 0 0"><span class="cite">P{{ qa.n }}</span> <b>{{ qa.q }}</b><br>{{ qa.a }}</p>{% endfor %}</details>{% endfor %}
<div class="card"><b>Documentos</b><ul>{% for doc in a.docs %}<li>{{ doc.name }} <span class="hint">· {{ doc.digest[:16] }}…{% if doc.facts.km %} · km: {{ doc.facts.km|join(', ') }}{% endif %}{% if doc.facts.ruts %} · RUT: {{ doc.facts.ruts|length }}{% endif %}</span></li>{% endfor %}</ul></div>
{% endblock %}"""

AUDIT_VIEW = r"""{% extends "base.html" %}{% block title %}Auditoría{% endblock %}
{% block crumbs %}<a href="{{ url_for('investigations') }}">Investigaciones</a> / Auditoría{% endblock %}
{% block heading %}<h1>Auditoría de informe</h1><p class="sub">{{ name }} · huella {{ digest[:16] }}…</p>{% endblock %}
{% block actions %}<a class="btn pri" href="{{ url_for('inv_export', cid=cid) }}">{{ icon('download', 15, '#fff') }}Paquete verificable</a>{% endblock %}
{% block body %}
{{ body|safe }}
{% endblock %}"""



ICONS = {
    "grid": "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
    "list": "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    "plus": "M12 5v14M5 12h14",
    "camera": "M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "folder": "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z",
    "filecheck": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M9 15l2 2 4-4",
    "network": "M5 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM19 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM12 22a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM6.3 6.6l4.4 10.8M17.7 6.6l-4.4 10.8M7.5 4.5h9",
    "chart": "M3 3v18h18M7 15l4-4 3 3 5-6",
    "upload": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
    "download": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
    "shield": "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4",
    "menu": "M3 6h18M3 12h18M3 18h18",
    "refresh": "M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5",
    "external": "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3",
    "link": "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
    "alert": "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
    "search": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
    "money": "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
    "clock": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
    "gear": "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
    "timeline": "M12 2v20M5 6h7M12 12h7M5 18h7",
    "users": "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
    "lock": "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
}


def icon(name: str, size: int = 17, color: str = "currentColor") -> Markup:
    return Markup(f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
                  f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{ICONS[name]}"/></svg>')


def _amount(v) -> int:
    digits = re.sub(r"[^0-9]", "", str(v or "").split(",")[0])
    return int(digits) if digits else 0

from veritas.portal.links import DEFAULT_DOCS, DOC_TYPES  # noqa: E402

LEVEL_TEXT = {"bad": "Derivar a investigación", "warn": "Revisión manual", "ok": "Sin alertas", "none": "Esperando evidencia"}


# ---- aplicación ---------------------------------------------------------------
def create_app(workdir: Path) -> Flask:
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    registry = workdir / "registro.jsonl"

    app = Flask(__name__)
    key_path = workdir / ".clave_sesion"          # la sesión sobrevive a reiniciar Veritas
    if not key_path.exists():
        key_path.write_bytes(os.urandom(32))
    app.secret_key = key_path.read_bytes()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    from veritas.accounts import users as U
    store = U.Store(workdir)
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
    app.config.setdefault("PUBLIC_BASE", "http://127.0.0.1:8765")
    app.jinja_loader = DictLoader({"base.html": BASE, "index.html": INDEX, "new.html": NEW, "case.html": CASE,
                                   "redes.html": REDES, "metricas.html": METRICAS, "importar.html": IMPORTAR,
                                   "inv_list.html": INV_LIST, "inv_new.html": INV_NEW, "inv_view.html": INV_VIEW,
                                   "audit_view.html": AUDIT_VIEW, "foto.html": FOTO, "capture.html": CAPTURE,
                                   "dash.html": DASH, "config.html": CONFIG, "login.html": LOGIN,
                                   "users.html": USERS, "denied.html": DENIED})
    app.jinja_env.globals["icon"] = icon
    app.jinja_env.globals["level_text"] = LEVEL_TEXT
    app.jinja_env.globals["roles"] = U.ROLES

    def _user():
        if not store.enabled():
            return None
        name = session.get("user")
        u = store.get(name) if name else None
        return u if u and u.get("active", True) else None

    def _actor() -> str:
        u = getattr(g, "user", None)
        return u["name"] if u else request.form.get("actor", "").strip()

    def _log(action, subject=""):
        u = getattr(g, "user", None)
        if u:
            store.log(u["username"], action, subject, request.remote_addr or "")

    @app.before_request
    def auth_guard():
        g.user = None
        # contra envíos desde otras páginas web: si el navegador declara el origen, debe ser este mismo servidor
        if request.method == "POST" and not request.path.startswith("/c/"):
            origin = request.headers.get("Origin")
            if origin and origin.split("://", 1)[-1] != request.host:
                abort(403)
        if request.endpoint in ("login", "logout", "capture_page", "capture_upload", "portal_file", "portal_story",
                                "portal_finish", "portal_remove", "static") or request.endpoint is None:
            return None
        if not store.enabled():
            return None                                   # modo demo: sin usuarios creados
        g.user = _user()
        if g.user is None:
            return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
        if not U.allowed(g.user["role"], request.endpoint):
            return render_template("denied.html", active=""), 403

    @app.context_processor
    def _auth_ctx():
        u = getattr(g, "user", None)
        on = store.enabled()
        return {"current_user": u, "auth_on": on, "can": lambda perm: (not on) or (u is not None and U.can(u["role"], perm))}
    app.jinja_env.globals["money"] = lambda n: f"{int(n or 0):,}".replace(",", ".")
    app.jinja_env.filters["extract"] = lambda k, d: d.get(k, k)

    def _case(cid: str) -> Case:
        if not re.fullmatch(r"[\w\-.]+", cid):
            abort(404)
        case = Case(workdir / cid)
        if not case.meta_path.exists() or case.kind != "claim":
            abort(404)
        return case

    def _summary(case: Case) -> dict:
        decl = service.declaration(case) or {}
        last = service.last_analysis(case) or {}
        return {
            "id": case.root.name, "numero": decl.get("numero", case.root.name),
            "patente": decl.get("patente", "—"), "asegurado": decl.get("asegurado", "—"),
            "fecha": decl.get("fecha_siniestro", "").replace("T", " ")[:16],
            "photos": last.get("photos", "—"), "findings": last.get("findings", "—"),
            "score": last.get("score", "—"), "linked": last.get("linked", "—"),
            "decision": (dec := service.current_decision(case)) and dec["subject"],
            "decision_label": dec and dec["data"]["label"],
            "rec": last.get("recommendation", "Sin analizar"), "level": last.get("level", "none"),
            "analyzed": last.get("ts", "—").replace("T", " ").rstrip("Z")[:16] + " UTC" if last else "—",
            "created": case.ledger.entries()[0]["ts"],
            "monto": _amount(decl.get("monto_reclamado")),
        }

    def _save_uploads(files, folder: Path) -> tuple[list[Path], list[str]]:
        saved, rejected, used = [], [], set()
        for fs in files:
            if not fs or not fs.filename:
                continue
            name = secure_filename(fs.filename) or "archivo"
            if Path(name).suffix.lower() not in service.whatsapp.CHAT_EXT and service.evidence_note(name) is None:
                rejected.append(fs.filename)
                continue
            base, n = name, 1
            while name.lower() in used:
                name = f"{Path(base).stem}_{n}{Path(base).suffix}"; n += 1
            used.add(name.lower())
            dest = folder / name
            fs.save(dest)
            if service.evidence_note(dest) is None:     # .txt o .zip que no es un chat exportado
                dest.unlink()
                rejected.append(fs.filename)
                continue
            saved.append(dest)
        return saved, rejected

    def _all_cases() -> list[dict]:
        cases = []
        for d in sorted(workdir.iterdir()):
            if (d / "case.json").exists():
                c = Case(d)
                if c.kind == "claim":
                    cases.append(_summary(c))
        # cola de trabajo: primero el mayor riesgo, luego los más recientes
        cases.sort(key=lambda c: c["created"], reverse=True)
        cases.sort(key=lambda c: c["score"] if isinstance(c["score"], int) else -1, reverse=True)
        return cases

    def _counts(cases):
        counts = {k: sum(1 for c in cases if c["level"] == k) for k in ("bad", "warn", "ok", "none")}
        counts["pend"] = sum(1 for c in cases if c["level"] == "bad" and c["decision"] in (None, "en_revision"))
        return counts

    @app.context_processor
    def _nav():
        if request.endpoint in ("capture_page", "capture_upload", "portal_file", "portal_story", "portal_finish",
                                "portal_remove", "report", "inv_report") or request.method != "GET":
            return {}
        n = 0
        for d in workdir.iterdir():
            if (d / "case.json").exists():
                last = service.last_analysis(Case(d)) or {}
                if last.get("level") == "bad":
                    dec = service.current_decision(Case(d))
                    n += not dec or dec["subject"] == "en_revision"
        return {"nav_pending": n}

    @app.get("/")
    def dashboard():
        from datetime import date
        cases = _all_cases()
        counts = _counts(cases)
        undecided = [c for c in cases if c["decision"] in (None, "en_revision")]
        comps = _comps() if cases else []
        exps, audits = _inv_lists()
        k = {"pend_bad": counts["pend"],
             "pend_warn": sum(1 for c in undecided if c["level"] == "warn"),
             "rings": sum(1 for c in comps if len(c["members"]) >= 3),
             "pairs": sum(1 for c in comps if len(c["members"]) == 2),
             "involved": sum(len(c["members"]) for c in comps),
             "monto_pend": sum(c["monto"] for c in undecided if c["level"] == "bad"),
             "fraude": sum(1 for c in cases if c["decision"] == "fraude"),
             "legitimo": sum(1 for c in cases if c["decision"] == "legitimo"),
             "sin_decision": len(undecided)}
        priority = [c for c in undecided if c["level"] in ("bad", "warn")][:10]
        from veritas.portal import links as capture
        from datetime import datetime as _dt
        waiting = []
        for c in cases:
            cc = Case(workdir / c["id"])
            data = capture.load(cc)
            if data and not data.get("finished"):
                pr = capture.progress(data, cc.excluded())
                waiting.append({**c, "pct": pr["pct"], "done": pr["done"], "total": pr["total"], "opened": data.get("opened"),
                                "expired": _dt.now() > _dt.fromisoformat(data["expires"]),
                                "days": (_dt.now() - _dt.fromisoformat(data["created"])).days})
        waiting.sort(key=lambda w: (w["expired"], -w["days"]))
        months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                  "octubre", "noviembre", "diciembre"]
        t = date.today()
        return render_template("dash.html", cases=cases, counts=counts, k=k, priority=priority, comps=comps,
                               waiting=waiting[:8], expedientes=exps, audits=audits, today=f"{t.day} de {months[t.month - 1]} de {t.year}",
                               active="dash")

    @app.get("/siniestros")
    def index():
        cases = _all_cases()
        return render_template("index.html", cases=cases, counts=_counts(cases), workdir=workdir, active="index")

    @app.route("/nuevo", methods=["GET", "POST"])
    def new_claim():
        f = request.form
        if request.method == "GET":
            return render_template("new.html", f={}, error=None, active="new", doc_types=DOC_TYPES, default_docs=DEFAULT_DOCS)

        def fail(msg):
            return render_template("new.html", f=f, error=msg, active="new", doc_types=DOC_TYPES, default_docs=DEFAULT_DOCS), 400

        numero = f.get("numero", "").strip()
        fecha = f.get("fecha_siniestro", "").strip()
        if not numero or not fecha:
            return fail("El número de siniestro y la fecha son obligatorios.")
        cid = service.case_id(numero)
        if not cid:
            return fail("El número de siniestro debe contener letras o números.")
        if (workdir / cid / "case.json").exists():
            return fail(f"Ya existe un siniestro con el número {numero}.")
        decl = {k: f.get(k, "").strip() for k in FORM_FIELDS}
        decl["fecha_siniestro"] = fecha if len(fecha) > 16 else fecha + ":00"
        lat, lon = f.get("lat", "").strip(), f.get("lon", "").strip()
        if lat or lon:
            try:
                decl["lat"], decl["lon"] = float(lat.replace(",", ".")), float(lon.replace(",", "."))
            except ValueError:
                return fail("Latitud y longitud deben ser números, por ejemplo -33.4263 y -70.6167.")
        decl = {k: v for k, v in decl.items() if v != ""}

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            photos, rejected = _save_uploads(request.files.getlist("fotos"), td)
            if rejected:
                return fail("Estos archivos no son fotos ni PDF ni chats de WhatsApp: " + ", ".join(rejected))
            send_link = f.get("enviar_enlace") == "1"
            if not photos and not send_link:
                return fail("Agregue al menos una foto o documento del siniestro, o marque la opción de enviar el enlace al asegurado.")
            dpath = td / "declaracion.json"
            dpath.write_text(json.dumps(decl, indent=2, ensure_ascii=False), encoding="utf-8")
            case = service.create_claim(workdir, cid, dpath, photos)
        if send_link:
            from veritas.portal import links as capture
            capture.create_link(case, actor=_actor() or "liquidador", docs=f.getlist("docs"),
                                custom=f.get("docs_custom", "").split(";"))
        r = service.analyze_claim(case, registry)
        if send_link:
            flash("Siniestro registrado. Envíe ahora el enlace al asegurado con los botones de la derecha.", "ok")
        else:
            flash(f"Siniestro creado y analizado: {r['photos']} foto(s), {r['documents']} documento(s), "
                  f"{r['findings']} hallazgo(s).", "ok")
        if r.get("reanalyzed"):
            flash("Se reanalizaron los siniestros vinculados: " + ", ".join(r["reanalyzed"]) + ".", "info")
        return redirect(url_for("case_view", cid=cid))

    @app.get("/caso/<cid>")
    def case_view(cid):
        case = _case(cid)
        # analiza si no hay informe o si llegaron fotos o documentos nuevos desde el último análisis
        n_ev = sum(1 for e in case.ledger.entries()
                   if e["action"] in ("evidence_added", "evidence_excluded", "evidence_restored"))
        mark = case.root / "informe.evidencias"
        try:
            seen = int(mark.read_text())
        except (OSError, ValueError):
            seen = -1
        if not (case.root / "informe.html").exists() or seen != n_ev:
            service.analyze_claim(case, registry)
            mark.write_text(str(n_ev))
        from veritas.portal import links as capture
        from veritas.portal import tunnel
        import base64
        cap = capture.load(case)
        cap_url = cap_qr = None
        if cap:
            base = _public_base()
            cap_url = f"{base}/c/{cap['token']}"
            png = capture.qr_png(cap_url)
            cap_qr = base64.b64encode(png).decode() if png else None
        summary = _summary(case)
        _log("ver_caso", summary["numero"])
        excl = case.excluded()
        kinds = {"foto": "Foto", "documento": "Documento", "chat": "Chat de WhatsApp"}
        files = []
        for e in case.ledger.entries():
            if e["action"] != "evidence_added" or e["data"].get("note") == "declaracion":
                continue
            d = e["data"]
            note = d.get("note") or ("documento" if Path(d["original_name"]).suffix.lower() == ".pdf" else "foto")
            files.append({"digest": e["subject"], "title": (d.get("portal") or {}).get("title") or d["original_name"],
                          "kind": kinds.get(note, note.capitalize()),
                          "who": "asegurado" if e["actor"].startswith("asegurado") else e["actor"],
                          "excluded": excl.get(e["subject"])})
        pr = capture.progress(cap, case.excluded()) if cap else None
        share = wa_url = mail_url = None
        cap_state = None
        if cap:
            import urllib.parse as up
            decl = service.declaration(case) or {}
            share = capture.share_message(summary["numero"], decl.get("asegurado", ""), cap_url, cap["expires"],
                                          _config().get("empresa", ""))
            if num := capture.wa_number(decl.get("telefono", "")):
                wa_url = f"https://wa.me/{num}?text={up.quote(share)}"
            if decl.get("email"):
                mail_url = (f"mailto:{decl['email']}?subject={up.quote('Siniestro ' + summary['numero'] + ': fotos y documentos')}"
                            f"&body={up.quote(share)}")
            st = capture.status(cap)
            cap_state = "Vencido" if st and not cap.get("finished") else None
        return render_template("case.html", c=summary, active="", decisions=service.DECISIONS,
                               accesos=store.entries(subject=summary["numero"], limit=8) if store.enabled() else [],
                               history=service.decision_history(case), files=files, cap=cap, cap_url=cap_url, cap_qr=cap_qr,
                               cap_lan=app.config.get("LAN", False),
                               cap_local=bool(cap_url) and tunnel.is_local(cap_url), pr=pr, share_msg=share, wa_url=wa_url,
                               mail_url=mail_url, cap_state=cap_state, doc_types=DOC_TYPES, default_docs=DEFAULT_DOCS)

    @app.get("/caso/<cid>/informe")
    def report(cid):
        case = _case(cid)
        return send_file(case.root / "informe.html", mimetype="text/html")

    @app.post("/caso/<cid>/analizar")
    def reanalyze(cid):
        r = service.analyze_claim(_case(cid), registry)
        flash(f"Análisis actualizado: {r['findings']} hallazgo(s). {r['recommendation']}.", "info")
        if r.get("reanalyzed"):
            flash("También se reanalizaron los siniestros vinculados: " + ", ".join(r["reanalyzed"]) + ".", "info")
        return redirect(url_for("case_view", cid=cid))

    @app.post("/caso/<cid>/fotos")
    def add_photos(cid):
        case = _case(cid)
        with tempfile.TemporaryDirectory() as td:
            photos, rejected = _save_uploads(request.files.getlist("fotos"), Path(td))
            added = 0
            for p in photos:
                if not service.has_evidence(case, sha256_file(p)):
                    case.add_evidence(p, note=service.evidence_note(p))
                    added += 1
        if rejected:
            flash("No se agregaron (no son fotos ni PDF ni chats de WhatsApp): " + ", ".join(rejected), "bad")
        if added:
            service.analyze_claim(case, registry)
            flash(f"{added} archivo(s) agregado(s) y caso reanalizado.", "ok")
        elif photos:
            flash("Esos archivos ya estaban en el caso.", "info")
        return redirect(url_for("case_view", cid=cid))

    @app.post("/caso/<cid>/verificar")
    def verify(cid):
        case = _case(cid)
        entries = case.ledger.entries()
        chain_ok, chain_msg = verify_chain(entries)
        ev_ok, problems = case.verify_evidence()
        seal_path = case.root / "seal.json"
        seal_ok, seal_msg = (verify_seal(entries, json.loads(seal_path.read_text(encoding="utf-8")),
                                         case.ledger.pub_path.read_bytes())
                             if seal_path.exists() else (False, "sin firma"))
        if chain_ok and ev_ok and seal_ok:
            flash(f"Integridad verificada: {chain_msg}, hashes de evidencia coinciden, firma digital válida.", "ok")
        else:
            detail = [m for ok, m in [(chain_ok, chain_msg), (seal_ok, seal_msg)] if not ok] + problems
            flash("Problema de integridad: " + "; ".join(detail), "bad")
        return redirect(url_for("case_view", cid=cid))

    @app.get("/caso/<cid>/exportar")
    def export_zip(cid):
        _log("descarga", f"paquete verificable {cid}")
        case = _case(cid)
        html = (case.root / "informe.html").read_text(encoding="utf-8")
        fd, tmp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            export.export_bundle(case, html, Path(tmp))
            data = io.BytesIO(Path(tmp).read_bytes())
        finally:
            os.unlink(tmp)
        return send_file(data, mimetype="application/zip", as_attachment=True, download_name=f"{cid}_veritas.zip")

    @app.post("/caso/<cid>/decision")
    def decide(cid):
        case = _case(cid)
        value, actor = request.form.get("decision", ""), _actor()
        if value not in service.DECISIONS or not actor:
            flash("Indique la decisión y su nombre.", "bad")
        else:
            service.set_decision(case, value, actor, request.form.get("nota", "").strip())
            _log("decision", (service.declaration(case) or {}).get("numero", cid))
            flash(f"Decisión registrada: {service.DECISIONS[value]}.", "ok")
        return redirect(url_for("case_view", cid=cid))

    def _comps():
        from veritas.claims import analysis as _claims
        from veritas.forensics import network
        from veritas.claims.report import _net_svg
        comps = network.components(_claims.load_registry(registry))
        for c in comps:
            for m in c["members"]:
                case = service.find_case(workdir, m)
                dec = service.current_decision(case) if case else None
                last = service.last_analysis(case) if case else None
                c["info"][m].update({"id": case.root.name if case else service.case_id(m),
                                     "level": (last or {}).get("level", c["info"][m]["level"]),
                                     "decision": dec and dec["subject"], "decision_label": dec and dec["data"]["label"]})
            degree = {m: 0 for m in c["members"]}
            for a, b, _ in c["edges"]:
                degree[a] += 1
                degree[b] += 1
            hub = max(c["members"], key=lambda m: degree[m])
            c["svg"] = _net_svg({"center": hub, "group": [m for m in c["members"] if m != hub], "group_edges": c["edges"],
                                 "group_info": {m: c["info"][m] for m in c["members"]}}, center_label="más conexiones")
        return comps

    @app.get("/redes")
    def networks():
        comps = _comps()
        rings = [c for c in comps if len(c["members"]) >= 3]
        pairs = [c for c in comps if len(c["members"]) == 2]
        return render_template("redes.html", comps=comps, rings=rings, pairs=pairs, active="redes",
                               involved=sum(len(c["members"]) for c in comps), total=sum(c["monto"] for c in comps),
                               level_text={"bad": "Derivar", "warn": "Revisión", "ok": "Sin alertas", None: "Sin analizar"})

    @app.get("/metricas")
    def metrics_view():
        from veritas.claims.report import RULE_NAMES
        return render_template("metricas.html", m=service.metrics(workdir), rule_names=RULE_NAMES, active="metricas")

    def _import(path: Path, actor: str, name: str):
        from veritas.claims import importer
        rep = importer.import_history(workdir, path, actor=actor, original_name=name)
        return render_template("importar.html", report=rep, nets=len(_comps()) if not rep.get("error") else 0, active="importar")

    @app.route("/importar", methods=["GET", "POST"])
    def import_view():
        if request.method == "GET":
            return render_template("importar.html", report=None, active="importar")
        fs = request.files.get("archivo")
        actor = _actor() or "importación"
        if not fs or not fs.filename or Path(fs.filename).suffix.lower() not in (".csv", ".xlsx", ".xlsm"):
            flash("Seleccione un archivo CSV o Excel (.xlsx).", "bad")
            return redirect(url_for("import_view"))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / (secure_filename(fs.filename) or "historial.csv")
            fs.save(path)
            return _import(path, actor, fs.filename)

    @app.post("/importar/ejemplo")
    def import_demo():
        script = service.DEMO_SCRIPT.parent / "make_history_demo.py"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "historial_demo.csv"
            import subprocess
            import sys
            subprocess.run([sys.executable, str(script), str(path)], check=True, capture_output=True)
            return _import(path, "importación de ejemplo", "historial_demo.csv")

    @app.get("/plantilla.csv")
    def template_download():
        from veritas.claims import importer
        return send_file(io.BytesIO(importer.template_csv().encode("utf-8")), mimetype="text/csv",
                         as_attachment=True, download_name="plantilla_siniestros.csv")

    # ---- investigaciones -------------------------------------------------------------
    from veritas.investigations import dossier as INV
    config_path = workdir / "config.json"

    def _public_base() -> str:
        """Dirección que recibe el asegurado: dominio configurado > túnel público > red local > este equipo."""
        cfg_url = (_config().get("direccion_publica") or "").strip().rstrip("/")
        if cfg_url.startswith("https://"):
            return cfg_url
        if app.config.get("PUBLIC") or app.config.get("LAN"):
            return app.config["PUBLIC_BASE"]
        return request.host_url.rstrip("/")

    def _config() -> dict:
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _inv_case(cid: str, kind: str) -> Case:
        if not re.fullmatch(r"[\w\-.]+", cid):
            abort(404)
        case = Case(workdir / cid)
        if not case.meta_path.exists() or case.kind != kind:
            abort(404)
        return case

    @app.get("/investigaciones")
    def investigations():
        exps, audits = _inv_lists()
        return render_template("inv_list.html", expedientes=exps, audits=audits, empresa=_config().get("empresa", ""), active="inv")

    def _inv_lists():
        exps = []
        for c in INV.list_cases(workdir, "investigacion"):
            a = INV.analyze(c)
            d = a["data"]
            exps.append({"id": c.root.name, "numero": d.get("numero"), "aseguradora": d.get("aseguradora", ""),
                         "fecha": (d.get("fecha_ocurrencia") or "").replace("T", " ")[:16], "interviews": len(a["interviews"]),
                         "findings": len(a["findings"]), "alerts": len(d.get("alertas", [])),
                         "answered": sum(1 for r in a["responses"].values() if r.get("estado")), "pending": len(INV.review(a))})
        audits = []
        for c in INV.list_cases(workdir, "auditoria"):
            run = next((e for e in reversed(c.ledger.entries()) if e["action"] == "audit_run"), None)
            first = c.ledger.entries()[0]
            audits.append({"id": c.root.name, "name": run["subject"] if run else c.name, "ts": first["ts"][:16].replace("T", " "),
                           "actor": first["actor"], **(run["data"] if run else {"alta": 0, "media": 0, "baja": 0})})
        return exps, audits

    @app.post("/investigaciones/config")
    def inv_settings():
        cfg = _config()
        cfg["empresa"] = request.form.get("empresa", "").strip()
        config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        flash("Configuración guardada.", "ok")
        return redirect(url_for("investigations"))

    @app.post("/investigaciones/ejemplo")
    def inv_demo():
        done = INV.load_demo(workdir)
        flash("Ejemplo ficticio cargado: " + ", ".join(done) if done else "El ejemplo ya estaba cargado.", "info")
        return redirect(url_for("investigations"))

    @app.route("/investigaciones/nuevo", methods=["GET", "POST"])
    def inv_new():
        f = request.form
        if request.method == "GET":
            return render_template("inv_new.html", f={}, error=None, active="inv_new")
        numero, fecha, actor = f.get("numero", "").strip(), f.get("fecha_ocurrencia", "").strip(), _actor()
        if not numero or not fecha or not actor:
            return render_template("inv_new.html", f=f, error="Número de siniestro, fecha y su nombre son obligatorios.", active="inv_new"), 400
        cid = service.case_id(numero)
        if (workdir / cid / "case.json").exists():
            return render_template("inv_new.html", f=f, error=f"Ya existe un expediente {numero}.", active="inv_new"), 400
        data = {k: f.get(k, "").strip() for k in ("numero", "aseguradora", "tipo", "direccion", "comuna", "vehiculo", "patente",
                                                  "rut_asegurado", "descripcion")}
        data["fecha_ocurrencia"] = fecha if len(fecha) > 16 else fecha + ":00"
        data["alertas"] = [x.strip() for x in f.get("alertas", "").splitlines() if x.strip()]
        ivs = [{"declarante": dcl.strip(), "rol": rol.strip(), "fecha": fch.strip(), "texto": txt}
               for dcl, rol, fch, txt in zip(f.getlist("iv_declarante"), f.getlist("iv_rol"), f.getlist("iv_fecha"), f.getlist("iv_texto"))
               if dcl.strip() and txt.strip()]
        with tempfile.TemporaryDirectory() as td:
            saved = []
            for fs in request.files.getlist("docs"):
                if fs and fs.filename:
                    dest = Path(td) / (secure_filename(fs.filename) or "documento")
                    fs.save(dest)
                    saved.append(dest)
            INV.create(workdir, cid, data, ivs, saved, actor=actor)
        flash("Expediente creado y analizado.", "ok")
        return redirect(url_for("inv_view", cid=cid))

    @app.get("/investigacion/<cid>")
    def inv_view(cid):
        _log("ver_expediente", cid)
        from veritas.investigations import audit as RA
        a = INV.analyze(_inv_case(cid, "investigacion"))
        review = INV.review(a)
        return render_template("inv_view.html", a=a, d=a["data"], cid=cid, review=review, states=INV.STATES,
                               recommendations=INV.RECOMMENDATIONS, matrix=RA.topic_matrix(a["interviews"]), active="inv",
                               answered=sum(1 for r in a["responses"].values() if r.get("estado")))

    @app.post("/investigacion/<cid>/alerta/<int:idx>")
    def inv_response(cid, idx):
        case = _inv_case(cid, "investigacion")
        INV.save_response(case, idx, request.form.get("estado", ""), request.form.get("hallazgo", "").strip(),
                          sorted(set(request.form.getlist("evidencia"))), _actor())
        flash(f"Respuesta a la alerta {idx} guardada.", "ok")
        return redirect(url_for("inv_view", cid=cid))

    @app.post("/investigacion/<cid>/conclusion")
    def inv_conclusion(cid):
        case = _inv_case(cid, "investigacion")
        INV.save_conclusion(case, request.form.get("recomendacion", ""), request.form.get("texto", "").strip(), _actor())
        flash("Conclusión guardada.", "ok")
        return redirect(url_for("inv_view", cid=cid))

    @app.get("/investigacion/<cid>/informe")
    def inv_report(cid):
        case = _inv_case(cid, "investigacion")
        return INV.build_report(case, INV.analyze(case), _config().get("empresa", ""))

    @app.get("/investigacion/<cid>/exportar")
    def inv_export(cid):
        case = Case(workdir / cid)
        if not re.fullmatch(r"[\w\-.]+", cid) or not case.meta_path.exists() or case.kind not in ("investigacion", "auditoria"):
            abort(404)
        if case.kind == "investigacion":
            html_doc = INV.build_report(case, INV.analyze(case), _config().get("empresa", ""))
        else:
            r = INV.run_audit(case)
            html_doc = INV.audit_page(r)
        fd, tmp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            export.export_bundle(case, html_doc, Path(tmp))
            data = io.BytesIO(Path(tmp).read_bytes())
        finally:
            os.unlink(tmp)
        return send_file(data, mimetype="application/zip", as_attachment=True, download_name=f"{cid}_veritas.zip")

    @app.post("/auditar")
    def audit_upload():
        fs = request.files.get("pdf")
        actor = _actor() or "revisor"
        if not fs or not fs.filename.lower().endswith(".pdf"):
            flash("Seleccione un informe en PDF.", "bad")
            return redirect(url_for("investigations"))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / (secure_filename(fs.filename) or "informe.pdf")
            fs.save(path)
            aid = "AUD-" + sha256_file(path)[:8]
            if (workdir / aid / "case.json").exists():
                flash("Ese informe ya estaba auditado; se muestra el resultado.", "info")
                return redirect(url_for("audit_view", cid=aid))
            case = INV.create_audit(workdir, aid, path, actor=actor, original_name=fs.filename)
        try:
            r = INV.run_audit(case)
        except Exception as ex:  # PDF escaneado, protegido o con otro formato
            flash(f"No se pudo leer el PDF ({type(ex).__name__}). Si es un escaneo, requiere OCR.", "bad")
            return redirect(url_for("investigations"))
        case.ledger.append("veritas", "audit_run", fs.filename, INV._audit_counts(r["findings"]))
        case.ledger.seal()
        return redirect(url_for("audit_view", cid=aid))

    @app.get("/auditoria/<cid>")
    def audit_view(cid):
        case = _inv_case(cid, "auditoria")
        r = INV.run_audit(case)
        return render_template("audit_view.html", body=INV.audit_html(r), name=r["name"], digest=r["digest"], cid=cid, active="inv")

    @app.post("/demo")
    def load_demo():
        if not service.DEMO_SCRIPT.exists():
            flash("No se encontró el generador de ejemplo (demo/make_claim_demo.py).", "bad")
            return redirect(url_for("index"))
        done = service.load_demo(workdir)
        if done:
            flash(f"Ejemplo cargado: {len(done)} siniestros ficticios, con fotos y documentos sintéticos. "
                  "Abra SIN-2026-0987 para ver la red de siniestros vinculados.", "info")
        else:
            flash("El ejemplo ya estaba cargado.", "info")
        return redirect(url_for("index"))

    @app.route("/foto", methods=["GET", "POST"])
    def photo_check():
        from veritas.claims.analysis import quick_check
        results = []
        if request.method == "POST":
            fecha = (request.form.get("fecha") or "").strip() or None
            if fecha and len(fecha) == 16:
                fecha += ":00"
            for up in request.files.getlist("fotos"):
                if not up or not up.filename:
                    continue
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / (secure_filename(up.filename) or "foto")
                    up.save(path)
                    meta, findings = quick_check(path, up.filename, fecha)
                    from veritas.forensics.image_content import overlay
                    import base64
                    ov = overlay(path, meta.get("content") or {})
                    marked = base64.b64encode(ov).decode() if ov else None
                level = "bad" if any(f.severity == "alta" for f in findings) else \
                    "warn" if any(f.severity == "media" for f in findings) else "ok"
                fx = meta.get("forensics") or {}
                dates = fx.get("dates") or {}
                rows = [("Formato y tamaño", f"{meta.get('format')} {meta.get('width')}×{meta.get('height')}"),
                        ("Cámara", " ".join(filter(None, [meta.get("make"), meta.get("model")])) or "—"),
                        ("Software", meta.get("software") or "—")]
                rows += [(f"Fecha {k}", v.replace("T", " ")) for k, v in dates.items()] or [("Fecha", "—")]
                rows += [("Zona horaria", fx.get("offset") or "—"),
                         ("Hora GPS (UTC)", (fx.get("gps_utc") or "—").replace("T", " ")),
                         ("Ubicación GPS", ", ".join(f"{x:.5f}" for x in meta["gps"]) if meta.get("gps") else "—"),
                         ("Datos de exposición", "sí" if fx.get("exposure") else "no"),
                         ("Miniatura interna", "sí" if fx.get("thumb_dhash") else "no"),
                         ("Herramientas detectadas", ", ".join(fx.get("tools") or []) or "—")]
                ct = meta.get("content") or {}
                g = ct.get("ghost") or {}
                rows += [("Calidad JPEG estimada", g.get("q_final") or "—"),
                         ("Compresión anterior", f"sí, calidad ~{g['q_first']}" if g.get("q_first") else "no detectada"),
                         ("Zonas clonadas", "sí" if (ct.get("clone") or {}).get("src") else "no detectadas")]
                cp = ct.get("c2pa")
                rows.append(("Firma de autenticidad (C2PA)", "no tiene" if not cp else
                             cp.get("note") or ("válida" if cp.get("valid") else f"inválida ({cp.get('state')})")
                             + (f" · {cp['generator']}" if cp.get("generator") else "")))
                if "error" in meta:
                    rows = [("Error", meta["error"])]
                results.append({"name": up.filename, "findings": findings, "level": level, "rows": rows, "marked": marked})
        return render_template("foto.html", results=results, active="foto")

    # ---- captura segura ----------------------------------------------------------------
    @app.post("/caso/<cid>/captura")
    def capture_link(cid):
        from veritas.portal import links as capture
        sent = request.form.get("docs_sent")
        docs = request.form.getlist("docs") if sent else None
        custom = request.form.get("docs_custom", "").split(";") if sent else None
        capture.create_link(_case(cid), actor=_actor() or "liquidador", docs=docs, custom=custom)
        flash("Enlace creado. Envíelo al asegurado con los botones de la derecha.", "ok")
        return redirect(url_for("case_view", cid=cid))

    def _portal(token):
        from veritas.portal import links as capture
        case, data = capture.find(workdir, token)
        if not case:
            abort(404)
        return case, data

    @app.get("/c/<token>")
    def capture_page(token):
        from veritas.portal import links as capture
        case, data = capture.find(workdir, token)
        empresa = _config().get("empresa", "")
        if not case:
            return render_template("capture.html", error="El enlace no existe o fue reemplazado por uno nuevo.", shots=[],
                                   empresa=empresa, numero="", finished=False), 404
        capture.mark_opened(case, data)
        decl = service.declaration(case) or {}
        pr = capture.progress(data, case.excluded())
        sections = [
            {"kind": "photo", "title": "Fotos", "files": pr["photos"], "accept": "image/*,.heic,.heif",
             "lead": "Fotos del vehículo y del daño. Si las tomó el día del choque, súbalas desde la galería de su teléfono: "
                     "así conservamos la fecha y el lugar en que las sacó. Si no tiene, puede tomarlas ahora.",
             "button": "Elegir o tomar fotos", "hint": "Después escriba un título para cada foto"},
            {"kind": "doc", "title": "Documentos", "files": pr["docs"], "accept": "application/pdf,.pdf,image/*,.heic",
             "lead": "PDF o foto del documento. Si lo tiene en papel, tómele una foto donde se lea bien; si es un PDF que le "
                     "enviaron, súbalo tal cual.",
             "button": "Elegir documentos", "hint": "Después escriba un título para cada documento"},
        ]
        return render_template("capture.html", error=capture.status(data), finished=bool(data.get("finished")),
                               numero=decl.get("numero", ""), nombre=decl.get("asegurado", ""), empresa=empresa,
                               sections=sections, requested=pr["requested"],
                               story=(data.get("story") or {}).get("text", ""),
                               vence=data["expires"][8:10] + "-" + data["expires"][5:7] + "-" + data["expires"][:4])

    @app.post("/c/<token>/archivo")
    def portal_file(token):
        from veritas.portal import links as capture
        case, data = _portal(token)
        f = request.files.get("archivo")
        if not f or not f.filename:
            return {"error": "No llegó el archivo."}, 400
        try:
            rec = capture.receive_file(case, data, f.filename, f.read(capture.MAX_FILE_BYTES + 1), request.form.get("kind", ""),
                                       request.form.get("titulo", ""), request.headers.get("User-Agent", ""))
        except ValueError as ex:
            return {"error": str(ex)}, 400
        return {"ok": True, "tipo": rec["kind"], "titulo": rec["title"], "hora": rec["server_time"][11:16], "id": rec["sha256"]}

    @app.post("/c/<token>/quitar")
    def portal_remove(token):
        from veritas.portal import links as capture
        case, data = _portal(token)
        try:
            capture.remove_file(case, data, request.form.get("id", ""))
        except ValueError as ex:
            return {"error": str(ex)}, 400
        return {"ok": True}

    @app.post("/c/<token>/relato")
    def portal_story(token):
        from veritas.portal import links as capture
        case, data = _portal(token)
        try:
            capture.save_story(case, data, request.form.get("texto", ""))
        except ValueError as ex:
            return {"error": str(ex)}, 400
        return {"ok": True}

    @app.post("/c/<token>/terminar")
    def portal_finish(token):
        from veritas.portal import links as capture
        case, data = _portal(token)
        try:
            capture.finish(case, data)
        except ValueError as ex:
            return {"error": str(ex)}, 400
        try:
            service.analyze_claim(case, registry)
        except Exception:
            pass
        return {"ok": True}

    @app.post("/c/<token>/foto")
    def capture_upload(token):
        from veritas.portal import links as capture
        case, data = capture.find(workdir, token)
        if not case:
            return {"error": "El enlace no existe."}, 404
        f = request.files.get("foto")
        if not f:
            return {"error": "No llegó la foto."}, 400
        try:
            rec = capture.receive(case, data, f.read(capture.MAX_BYTES + 1), request.form,
                                  request.headers.get("User-Agent", ""))
        except ValueError as ex:
            return {"error": str(ex)}, 400
        if len(data["received"]) >= len(data["shots"]):
            try:
                service.analyze_claim(case, registry)
            except Exception:
                pass
        return {"ok": True, "hora": rec["server_time"][11:16]}

    @app.before_request
    def lan_guard():
        """Desde otros equipos (red local o túnel público) solo se puede abrir el portal del asegurado."""
        if request.path.startswith("/c/"):
            return None
        via_tunnel = any(h in request.headers for h in ("Cf-Connecting-Ip", "Cf-Ray", "X-Forwarded-For"))
        host = (request.host or "").rsplit(":", 1)[0].strip("[]").lower()
        if via_tunnel or (app.config.get("PUBLIC") and host not in ("127.0.0.1", "localhost", "::1")):
            abort(404)
        if app.config.get("LAN") and request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403)

    @app.route("/configuracion", methods=["GET", "POST"])
    def settings():
        from veritas.forensics import external
        cfg = _config()
        if request.method == "POST":
            for k in ("empresa", "direccion_publica", "sightengine_user", "sightengine_secret", "google_vision_key"):
                cfg[k] = request.form.get(k, "").strip()
            (workdir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            flash("Configuración guardada.", "ok")
            return redirect(url_for("settings"))
        return render_template("config.html", cfg=cfg, on=external.configured(cfg), active="config")

    @app.post("/caso/<cid>/archivo/<digest>/quitar")
    def evidence_exclude(cid, digest):
        case = _case(cid)
        motivo = request.form.get("motivo", "").strip()[:200]
        if not service.has_evidence(case, digest) or not motivo:
            flash("Indique el motivo para quitar el archivo.", "bad")
        elif digest not in case.excluded():
            case.exclude_evidence(digest, _actor() or "analista", motivo)
            _log("quitar_archivo", digest[:12])
            service.analyze_claim(case, registry)
            flash("Archivo quitado del análisis y caso reanalizado. Sigue guardado en la cadena de custodia.", "ok")
        return redirect(url_for("case_view", cid=cid, archivos=1))

    @app.post("/caso/<cid>/archivo/<digest>/restaurar")
    def evidence_restore(cid, digest):
        case = _case(cid)
        if digest in case.excluded():
            case.restore_evidence(digest, _actor() or "analista")
            service.analyze_claim(case, registry)
            flash("Archivo restaurado y caso reanalizado.", "ok")
        return redirect(url_for("case_view", cid=cid, archivos=1))

    @app.get("/caso/<cid>/archivo/<digest>")
    def evidence_file(cid, digest):
        """Archivo recibido (foto o documento), para verlo desde el caso. mini=1 entrega una miniatura."""
        case = _case(cid)
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not service.has_evidence(case, digest):
            abort(404)
        path = case.evidence_dir / digest
        name = next((e["data"]["original_name"] for e in case.ledger.entries()
                     if e["action"] == "evidence_added" and e["subject"] == digest), "archivo")
        ext = Path(name).suffix.lower()
        if request.args.get("mini") or ext in (".heic", ".heif"):
            try:
                from PIL import Image, ImageOps
                with Image.open(path) as img:
                    img = ImageOps.exif_transpose(img).convert("RGB")
                    if request.args.get("mini"):
                        img.thumbnail((240, 240))
                    buf = io.BytesIO()
                    img.save(buf, "JPEG", quality=82)
                return send_file(io.BytesIO(buf.getvalue()), mimetype="image/jpeg", max_age=3600)
            except Exception:
                if request.args.get("mini"):
                    abort(404)
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf",
                ".webp": "image/webp"}.get(ext, "application/octet-stream")
        _log("ver_archivo", name)
        return send_file(path, mimetype=mime, download_name=name, as_attachment=mime == "application/octet-stream")

    @app.get("/caso/<cid>/documento/<digest>/version/<int:n>")
    def doc_version(cid, digest, n):
        from veritas.forensics.pdf_versions import version_bytes
        case = _case(cid)
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not service.has_evidence(case, digest):
            abort(404)
        name = next((e["data"]["original_name"] for e in case.ledger.entries()
                     if e["action"] == "evidence_added" and e["subject"] == digest), "documento.pdf")
        data = version_bytes((case.evidence_dir / digest).read_bytes(), n)
        _log("descarga", f"{name} versión {n}")
        if data is None:
            abort(404)
        return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                         download_name=f"{Path(name).stem}_version{n}.pdf")

    @app.get("/exportar/<what>.xlsx")
    def export_xlsx(what):
        from veritas.claims import excel
        from datetime import date
        _log("exporta_excel", what)
        if what == "cola":
            data = excel.queue(_all_cases(), LEVEL_TEXT)
        elif what == "redes":
            data = excel.networks(_comps(), LEVEL_TEXT)
        elif what == "metricas":
            from veritas.claims.report import RULE_NAMES
            data = excel.metrics(service.metrics(workdir), RULE_NAMES)
        else:
            abort(404)
        return send_file(io.BytesIO(data), as_attachment=True, download_name=f"veritas_{what}_{date.today():%Y-%m-%d}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ---- usuarios -------------------------------------------------------------------------
    @app.route("/ingresar", methods=["GET", "POST"])
    def login():
        if not store.enabled():
            return redirect(url_for("dashboard"))
        nxt = request.values.get("next") or ""
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = ""
        if request.method == "POST":
            u, err = store.check(request.form.get("usuario", ""), request.form.get("clave", ""))
            if u:
                session.clear()
                session["user"] = u["username"]
                store.log(u["username"], "ingreso", "", request.remote_addr or "")
                return redirect(nxt or url_for("dashboard" if U.can(u["role"], "ver_siniestros") else "investigations"))
            store.log(request.form.get("usuario", "")[:40], "ingreso_fallido", "", request.remote_addr or "")
            return render_template("login.html", error=err, usuario=request.form.get("usuario"), next=nxt), 401
        return render_template("login.html", error=None, next=nxt)

    @app.get("/salir")
    def logout():
        if session.get("user"):
            store.log(session["user"], "salida", "", request.remote_addr or "")
        session.clear()
        return redirect(url_for("login"))

    ROLE_HELP = {"administrador": "Todo, más usuarios y configuración.",
                 "jefe": "Siniestros, investigaciones, redes, métricas e importación.",
                 "liquidador": "Siniestros: ver, crear, agregar evidencia, decidir y pedir captura segura; ver redes.",
                 "investigador": "Expedientes y auditorías; ver siniestros sin decidir."}
    ACTIONS = {"ingreso": "Ingresó", "ingreso_fallido": "Ingreso fallido", "salida": "Salió", "ver_caso": "Abrió el caso",
               "decision": "Registró decisión", "descarga": "Descargó", "ver_expediente": "Abrió expediente",
               "usuario": "Cambió un usuario", "exporta_excel": "Exportó a Excel"}

    @app.route("/usuarios", methods=["GET", "POST"])
    def users_view():
        first = not store.enabled()
        if request.method == "POST":
            err = store.add(request.form.get("usuario", ""), request.form.get("nombre", ""), request.form.get("rol", ""),
                            request.form.get("clave", ""))
            if err:
                flash(err, "bad")
            else:
                uname = request.form.get("usuario", "").strip().lower()
                if first:
                    session.clear()
                    session["user"] = uname
                    store.log(uname, "usuario", f"creó el administrador {uname}", request.remote_addr or "")
                    flash("Administrador creado. Desde ahora Veritas pide usuario y contraseña.", "ok")
                else:
                    _log("usuario", f"guardó {uname}")
                    flash(f"Usuario {uname} guardado.", "ok")
            return redirect(url_for("users_view"))
        return render_template("users.html", users=store.all(), log=store.entries(), roles=U.ROLES, role_help=ROLE_HELP,
                               actions=ACTIONS, active="usuarios")

    @app.post("/usuarios/<username>/estado")
    def user_toggle(username):
        u = store.get(username)
        if not u:
            abort(404)
        err = store.set_active(username, u.get("active", True) is False)
        flash(err or f"Usuario {username} {'activado' if u.get('active', True) is False else 'desactivado'}.", "bad" if err else "ok")
        if not err:
            _log("usuario", f"{'activó' if u.get('active', True) is False else 'desactivó'} {username}")
        return redirect(url_for("users_view"))

    return app


def main(argv=None):
    p = argparse.ArgumentParser(prog="veritas.web", description="Interfaz web local de Veritas")
    p.add_argument("--dir", default="casos", help="carpeta donde se guardan los casos (por defecto ./casos)")
    p.add_argument("--puerto", type=int, default=8765)
    p.add_argument("--no-abrir", action="store_true", help="no abrir el navegador automáticamente")
    p.add_argument("--red", action="store_true",
                   help="permitir que celulares de la misma red abran los enlaces de captura (HTTPS con certificado propio)")
    p.add_argument("--publico", action="store_true",
                   help="abrir un túnel https (cloudflared) para que el asegurado abra el enlace desde cualquier celular")
    a = p.parse_args(argv)
    app = create_app(Path(a.dir))
    url = f"http://127.0.0.1:{a.puerto}"
    if a.red:
        from veritas.portal.links import lan_ip
        url = f"https://127.0.0.1:{a.puerto}"
        app.config.update(LAN=True, PUBLIC_BASE=f"https://{lan_ip()}:{a.puerto}")
        print(f"Enlaces de captura disponibles en la red local: {app.config['PUBLIC_BASE']}")
        print("El navegador mostrará un aviso de certificado: es normal en la demo (Configuración avanzada > Continuar).")
    if a.publico and not a.red:
        from veritas.portal import tunnel
        print("Abriendo dirección pública para el portal del asegurado...")
        pub, msg = tunnel.start(a.puerto, Path.cwd())
        if pub:
            app.config.update(PUBLIC=True, PUBLIC_BASE=pub)
            print(f"Portal del asegurado disponible en internet: {pub}/c/...  (solo el portal; el resto sigue local)")
        else:
            print("AVISO: " + msg + " Los enlaces solo funcionarán en este computador.")
    print(f"Veritas está corriendo en {url}  (casos en {Path(a.dir).resolve()})")
    print("Para detenerlo, cierre esta ventana o presione Ctrl+C.")
    if not a.no_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    if a.red:
        app.run(host="0.0.0.0", port=a.puerto, debug=False, ssl_context="adhoc")
    else:
        app.run(host="127.0.0.1", port=a.puerto, debug=False)


if __name__ == "__main__":
    main()
