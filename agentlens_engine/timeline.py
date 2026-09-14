"""HTML timeline viewer for AgentLens runs.

Generates a single self-contained HTML file: three-panel debugging UI with a
span list, latency strip, full span detail, and an optional diagnosis banner.
No external dependencies, no server — open the file directly in a browser.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agentlens_core.trace import normalize_run


def generate_html(run: dict[str, Any], diagnosis: dict[str, Any] | None = None) -> str:
    """Return a fully self-contained HTML timeline for the given run.

    diagnosis is the optional output of diagnose_run() for this run; when
    present the viewer shows a root-cause banner and highlights the failed step.
    """
    run = normalize_run(run)
    run_json = _embed(run)
    diag_json = _embed(diagnosis) if diagnosis else "null"
    title = _esc(str(run.get("name") or run.get("run_id") or "AgentLens Run"))
    values = {"/*__RUN__*/null": run_json, "/*__DIAG__*/null": diag_json, "__TITLE__": title}
    return re.sub(r"/\*__RUN__\*/null|/\*__DIAG__\*/null|__TITLE__", lambda match: values[match.group(0)], _TEMPLATE)


def _embed(obj: Any) -> str:
    # Escape </script> so injected JSON cannot break out of the <script> block.
    encoded = json.dumps(obj, ensure_ascii=True, default=str)
    return encoded.replace('<', r'\u003c').replace('>', r'\u003e').replace('&', r'\u0026')


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentLens — __TITLE__</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d0d0d;--bg2:#111111;--bg3:#161616;--border:#222222;--border2:#2a2a2a;
  --green:#22c55e;--green-dim:#16a34a;--amber:#f59e0b;--red:#ef4444;--blue:#3b82f6;
  --purple:#a855f7;--purple2:#7c3aed;
  --text:#e5e5e5;--text2:#a3a3a3;--text3:#525252;
  --mono:'JetBrains Mono','Fira Code','Cascadia Code',monospace;
  --sans:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',sans-serif;
}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased;display:flex;flex-direction:column}

/* ── TOP BAR ── */
#topbar{flex-shrink:0;background:var(--bg2);border-bottom:1px solid var(--border);padding:10px 20px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.tb-name{font-family:var(--mono);font-size:14px;font-weight:600}
.tb-id{font-family:var(--mono);font-size:11px;color:var(--text3)}
.tb-badge{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:1px;padding:2px 8px;border:1px solid;border-radius:3px}
.b-pass{color:var(--green);border-color:var(--green)}
.b-fail{color:var(--red);border-color:var(--red)}
.b-partial{color:var(--amber);border-color:var(--amber)}
.tb-stat{font-family:var(--mono);font-size:11px;color:var(--text2);white-space:nowrap}
.tb-stat b{color:var(--text);font-weight:600}
.tb-diag{font-family:var(--mono);font-size:11px;color:var(--amber);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:560px}

/* ── LATENCY STRIP ── */
#latstrip{flex-shrink:0;display:flex;height:14px;background:var(--bg3);border-bottom:1px solid var(--border);cursor:pointer}
.lat-seg{height:100%;min-width:3px;opacity:.75;transition:opacity .1s}
.lat-seg:hover,.lat-seg.hot{opacity:1;outline:1px solid var(--text)}

/* ── MAIN LAYOUT ── */
#main{flex:1;display:flex;min-height:0}

/* ── LEFT PANEL ── */
#spanlist{width:280px;flex-shrink:0;overflow-y:auto;background:var(--bg2);border-right:1px solid var(--border)}
.srow{padding:8px 10px 8px 12px;border-bottom:1px solid var(--border);border-left:3px solid transparent;cursor:pointer;font-family:var(--mono)}
.srow:hover{background:var(--bg3)}
.srow.sel{background:var(--bg3);outline:1px solid var(--border2)}
.srow.failed{background:rgba(239,68,68,.10)}
.sl-llm{border-left-color:var(--blue)}
.sl-tool{border-left-color:var(--green)}
.sl-error{border-left-color:var(--red)}
.sl-lgnode{border-left-color:var(--purple)}
.sl-lgrun{border-left-color:var(--purple2)}
.sl-mem{border-left-color:var(--amber)}
.srow-top{display:flex;align-items:baseline;gap:6px;font-size:11px}
.srow-step{color:var(--text3);min-width:18px}
.srow-name{color:var(--text);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.srow-rc{font-size:9px;color:var(--red);font-weight:700;letter-spacing:.5px;flex-shrink:0}
.srow-meta{display:flex;align-items:center;gap:6px;margin-top:3px}
.srow-bar{height:3px;background:var(--border);border-radius:1px;flex:1;max-width:120px;overflow:hidden}
.srow-fill{height:100%}
.srow-ms{font-size:10px;color:var(--text2);white-space:nowrap}
.srow-tok{font-size:10px;color:var(--text3);white-space:nowrap}

/* ── RIGHT PANEL ── */
#detail{flex:1;overflow-y:auto;padding:18px 24px}

/* diagnosis banner */
#diagbanner{border:1px solid var(--amber);background:rgba(245,158,11,.06);border-radius:4px;padding:14px 16px;margin-bottom:18px;font-family:var(--mono);font-size:12px}
#diagbanner .db-row{margin-bottom:5px}
#diagbanner .db-lbl{color:var(--amber);font-weight:700}
#diagbanner .db-val{color:var(--text)}

/* span header */
.sh{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.sh-type{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:1px;padding:2px 8px;border:1px solid;border-radius:3px}
.sh-name{font-family:var(--mono);font-size:15px;font-weight:600}
.sh-meta{font-family:var(--mono);font-size:11px;color:var(--text2)}

/* sections */
.sec{margin-bottom:16px;border:1px solid var(--border);border-radius:4px;background:var(--bg2)}
.sec-hd{padding:7px 12px;font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:1px;color:var(--text2);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.sec-hd.clickable{cursor:pointer;user-select:none}
.sec-hd.clickable:hover{color:var(--text)}
.sec-body{padding:10px 12px;overflow-x:auto}
.sec-body.hidden{display:none}
.chev{font-size:9px;color:var(--text3)}

/* code blocks */
pre.code{font-family:var(--mono);font-size:11.5px;line-height:1.55;white-space:pre;color:var(--text)}
pre.code .ln{display:inline-block;width:34px;color:var(--text3);user-select:none;text-align:right;padding-right:12px}
pre.wrap{white-space:pre-wrap;word-break:break-word}
.err-text{color:var(--red)}

/* key-value grid */
.kv{display:grid;grid-template-columns:140px 1fr;gap:4px 14px;font-family:var(--mono);font-size:12px}
.kv .k{color:var(--text2)}
.kv .v{color:var(--text)}

/* tools table */
table.tools{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11.5px}
table.tools th{text-align:left;color:var(--text2);font-weight:600;padding:4px 10px 6px 0;border-bottom:1px solid var(--border)}
table.tools td{padding:5px 10px 5px 0;border-bottom:1px solid var(--border);vertical-align:top}
table.tools tr:last-child td{border-bottom:none}
table.tools .tn{color:var(--green);white-space:nowrap}

/* hallucination cards */
.hcard{border:1px solid var(--red);background:rgba(239,68,68,.06);border-radius:4px;padding:9px 12px;margin-bottom:8px;font-family:var(--mono);font-size:11.5px}
.hcard .hs{color:var(--red);font-weight:700}

/* response text */
.resp-text{font-family:var(--mono);font-size:12px;white-space:pre-wrap;word-break:break-word}

::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:4px}
</style>
</head>
<body>
<div id="topbar"></div>
<div id="latstrip"></div>
<div id="main">
  <div id="spanlist"></div>
  <div id="detail"></div>
</div>
<script>
const RUN = /*__RUN__*/null;
const DIAG = /*__DIAG__*/null;

/* ── helpers ── */
const TYPE_META = {
  llm_call:        {cls:'sl-llm',    color:'var(--blue)',    label:'LLM',   icon:'◆'},
  tool_call:       {cls:'sl-tool',   color:'var(--green)',   label:'TOOL',  icon:'▸'},
  error:           {cls:'sl-error',  color:'var(--red)',     label:'ERROR', icon:'✗'},
  langgraph_node:  {cls:'sl-lgnode', color:'var(--purple)',  label:'NODE',  icon:'●'},
  langgraph_run:   {cls:'sl-lgrun',  color:'var(--purple2)', label:'GRAPH', icon:'◎'},
  memory_snapshot: {cls:'sl-mem',    color:'var(--amber)',   label:'MEM',   icon:'■'},
};
function meta(t){return TYPE_META[t]||{cls:'sl-tool',color:'var(--text3)',label:(t||'?').toUpperCase().slice(0,6),icon:'·'}}
function esc(s){if(s==null)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function ms(v){if(v==null||v<=0)return'';return v<1000?(+v).toFixed(v<10?2:0)+'ms':(v/1000).toFixed(2)+'s'}
function cost(v){if(!v||v<=0)return'';return v<0.0001?'<$0.0001':'$'+v.toFixed(6)}
function usage(s){const u=s.usage||{};const i=(u.input_tokens||0)+(u.prompt_tokens||0);const o=(u.output_tokens||0)+(u.completion_tokens||0);return{i,o,tot:i+o}}
function fmtJson(o,maxLen){let s;try{s=JSON.stringify(o,null,2)}catch{s=String(o)}if(maxLen&&s.length>maxLen)s=s.slice(0,maxLen)+'\n…(truncated)';return s}
function codeBlock(o,opts){
  opts=opts||{};
  const text=typeof o==='string'?o:fmtJson(o,opts.max||40000);
  if(opts.lineNumbers){
    const lines=text.split('\n').map((l,i)=>`<span class="ln">${i+1}</span>${esc(l)}`).join('\n');
    return `<pre class="code">${lines}</pre>`;
  }
  return `<pre class="code wrap${opts.err?' err-text':''}">${esc(text)}</pre>`;
}
function spanTitle(s){
  const t=s.type;
  if(t==='llm_call')return s.model||'llm_call';
  if(t==='tool_call')return s.tool_name||'tool_call';
  if(t==='error')return String(s.error||'error').slice(0,40);
  if(t==='langgraph_node')return s.tool_name||s.node_name||'node';
  if(t==='langgraph_run')return 'graph '+(s.mode||'run');
  if(t==='memory_snapshot')return s.label||'snapshot';
  return t||'span';
}
function isErrOutput(o){return o&&typeof o==='object'&&!Array.isArray(o)&&(o.status==='error'||!!o.error)}

/* ── data prep ── */
const spans=(Array.isArray(RUN.spans)?RUN.spans:[]).filter(s=>s&&typeof s==='object');
const failedStep=DIAG?DIAG.failed_at_step:null;
const hallByStep={};
if(DIAG&&Array.isArray(DIAG.hallucinations)){
  for(const h of DIAG.hallucinations){(hallByStep[h.step]=hallByStep[h.step]||[]).push(h)}
}
let maxLat=0,latSum=0,llm=0,tool=0,errs=0,intok=0,outtok=0,costSum=0;
for(const s of spans){
  const l=+s.latency_ms||0;latSum+=l;if(l>maxLat)maxLat=l;
  if(s.type==='llm_call'){llm++;const u=usage(s);intok+=u.i;outtok+=u.o;costSum+=(+s.cost_usd||0)}
  else if(s.type==='tool_call')tool++;
  else if(s.type==='error')errs++;
}
let sel=0;

/* ── top bar ── */
function renderTopbar(){
  const st=RUN.status||'unknown';
  const badge=st==='success'?['PASS','b-pass']:st==='error'||st==='failure'?['FAILED','b-fail']:['PARTIAL','b-partial'];
  const started=(RUN.started_at||'').slice(0,19).replace('T',' ');
  let h=`<span class="tb-name">${esc(RUN.name||'run')}</span>
<span class="tb-id">${esc((RUN.run_id||'').slice(0,8))} · ${esc(started)} UTC</span>
<span class="tb-badge ${badge[1]}">${badge[0]}</span>
<span class="tb-stat"><b>${spans.length}</b> spans</span>
<span class="tb-stat"><b>${llm}</b> llm</span>
<span class="tb-stat"><b>${tool}</b> tool</span>
<span class="tb-stat" style="${errs?'color:var(--red)':''}"><b>${errs}</b> err</span>
<span class="tb-stat"><b>${(intok+outtok).toLocaleString()}</b> tok</span>`;
  if(costSum>0)h+=`<span class="tb-stat"><b>${cost(costSum)}</b></span>`;
  if(latSum>0)h+=`<span class="tb-stat"><b>${ms(latSum)}</b></span>`;
  if(DIAG)h+=`<span class="tb-diag">ROOT CAUSE: ${esc(DIAG.root_cause_category)} · FAILED AT: Step ${esc(DIAG.failed_at_step)} · CONFIDENCE: ${(+DIAG.confidence).toFixed(2)}</span>`;
  document.getElementById('topbar').innerHTML=h;
}

/* ── latency strip ── */
function renderStrip(){
  const total=latSum||1;
  const segs=spans.map((s,i)=>{
    const l=+s.latency_ms||0;
    const pct=latSum>0?Math.max((l/total)*100,0.6):100/spans.length;
    return `<div class="lat-seg" data-i="${i}" style="width:${pct}%;background:${meta(s.type).color}" title="step ${s.original_index||i+1}: ${esc(spanTitle(s))} ${ms(l)}"></div>`;
  }).join('');
  const el=document.getElementById('latstrip');
  el.innerHTML=segs;
  el.querySelectorAll('.lat-seg').forEach(seg=>{
    seg.addEventListener('mouseenter',()=>hotRow(+seg.dataset.i,true));
    seg.addEventListener('mouseleave',()=>hotRow(+seg.dataset.i,false));
    seg.addEventListener('click',()=>select(+seg.dataset.i));
  });
}
function hotRow(i,on){
  const row=document.querySelector(`.srow[data-i="${i}"]`);
  if(row){row.style.background=on?'var(--bg3)':'';if(on)row.scrollIntoView({block:'nearest'})}
}

/* ── left panel ── */
function renderList(){
  const h=spans.map((s,i)=>{
    const m=meta(s.type);
    const step=s.original_index||i+1;
    const isFailed=failedStep===step;
    const l=+s.latency_ms||0;
    const pct=maxLat>0?Math.max(Math.round(l/maxLat*100),l>0?4:0):0;
    const u=usage(s);
    return `<div class="srow ${m.cls}${i===sel?' sel':''}${isFailed?' failed':''}" data-i="${i}" onclick="select(${i})">
  <div class="srow-top">
    <span class="srow-step">${step}</span>
    <span style="color:${m.color}">${m.icon}</span>
    <span class="srow-name">${esc(spanTitle(s))}</span>
    ${isFailed?'<span class="srow-rc">⚠ ROOT CAUSE</span>':''}
  </div>
  <div class="srow-meta">
    ${l>0?`<div class="srow-bar"><div class="srow-fill" style="width:${pct}%;background:${m.color}"></div></div><span class="srow-ms">${ms(l)}</span>`:''}
    ${u.tot>0?`<span class="srow-tok">${u.tot} tok</span>`:''}
  </div>
</div>`;
  }).join('');
  document.getElementById('spanlist').innerHTML=h||'<div style="padding:16px;color:var(--text3);font-family:var(--mono);font-size:12px">No spans captured.</div>';
}

/* ── right panel sections ── */
let secId=0;
function section(title,bodyHtml,opts){
  opts=opts||{};
  const id='sec'+(secId++);
  const collapsed=opts.collapsed;
  return `<div class="sec">
  <div class="sec-hd${opts.collapsible?' clickable':''}"${opts.collapsible?` onclick="toggleSec('${id}',this)"`:''}>
    <span>${title}</span>${opts.collapsible?`<span class="chev">${collapsed?'▶':'▼'}</span>`:''}
  </div>
  <div class="sec-body${collapsed?' hidden':''}" id="${id}">${bodyHtml}</div>
</div>`;
}
function toggleSec(id,hd){
  const b=document.getElementById(id);
  const hidden=b.classList.toggle('hidden');
  hd.querySelector('.chev').textContent=hidden?'▶':'▼';
}
function kv(pairs){
  return '<div class="kv">'+pairs.filter(p=>p[1]!==''&&p[1]!=null).map(p=>`<span class="k">${p[0]}</span><span class="v">${p[1]}</span>`).join('')+'</div>';
}

function renderDiagBanner(){
  if(!DIAG)return'';
  const tool=DIAG.failed_at_tool?` (${esc(DIAG.failed_at_tool)})`:'';
  return `<div id="diagbanner">
  <div class="db-row"><span class="db-lbl">⚠ ROOT CAUSE:</span> <span class="db-val">${esc(DIAG.root_cause_category)}</span></div>
  <div class="db-row"><span class="db-lbl">FAILED AT:</span> <span class="db-val">Step ${esc(DIAG.failed_at_step)}${tool}</span></div>
  <div class="db-row"><span class="db-lbl">WHY:</span> <span class="db-val">${esc(DIAG.explanation||'')}</span></div>
  <div class="db-row"><span class="db-lbl">FIX:</span> <span class="db-val">${esc(DIAG.fix||'')}</span></div>
  <div class="db-row"><span class="db-lbl">CONFIDENCE:</span> <span class="db-val">${(+DIAG.confidence).toFixed(2)}</span></div>
</div>`;
}

function respText(content){
  if(content==null)return'';
  if(typeof content==='string')return content;
  if(Array.isArray(content)){
    return content.map(b=>{
      if(typeof b==='string')return b;
      if(b&&b.type==='text')return b.text||'';
      if(b&&b.type==='tool_use')return `[tool_use: ${b.name}(${JSON.stringify(b.input)})]`;
      return JSON.stringify(b);
    }).join('\n');
  }
  if(typeof content==='object'){
    const ch=content.choices;
    if(Array.isArray(ch)&&ch.length){
      const m=ch[0].message||{};
      let out=m.content||'';
      if(Array.isArray(m.tool_calls))for(const tc of m.tool_calls){const f=tc.function||{};out+=`\n[tool_call: ${f.name}(${f.arguments||''})]`}
      return out;
    }
    return JSON.stringify(content,null,2);
  }
  return String(content);
}

function toolRows(tools){
  return tools.map(t=>{
    const f=(t&&t.function)||t||{};
    const name=t.name||f.name||'?';
    const desc=t.description||f.description||'';
    return `<tr><td class="tn">${esc(name)}</td><td>${esc(desc)}</td></tr>`;
  }).join('');
}

function renderDetail(){
  secId=0;
  const s=spans[sel];
  const el=document.getElementById('detail');
  if(!s){el.innerHTML=renderDiagBanner()+'<div style="color:var(--text3);font-family:var(--mono)">No span selected.</div>';return}
  const m=meta(s.type);
  const step=s.original_index||sel+1;
  let h=renderDiagBanner();

  h+=`<div class="sh">
  <span class="sh-type" style="color:${m.color};border-color:${m.color}">${m.label}</span>
  <span class="sh-name">${esc(spanTitle(s))}</span>
  <span class="sh-meta">step ${step}${s.ts?' · '+esc(String(s.ts).slice(11,23)):''}${s.latency_ms?' · '+ms(+s.latency_ms):''}</span>
</div>`;

  if(s.type==='llm_call'){
    const u=usage(s);
    h+=section('OVERVIEW',kv([
      ['model',esc(s.model||'')],['provider',esc(s.provider||'')],
      ['input tokens',u.i||''],['output tokens',u.o||''],['total tokens',u.tot||''],
      ['cost',cost(+s.cost_usd||0)],['stop reason',esc(s.stop_reason||'')],
      ['streaming',s.streaming?'yes':''],
    ]));
    if(s.input_messages!=null)
      h+=section('PROMPT',codeBlock(s.input_messages,{lineNumbers:true,max:60000}),{collapsible:true});
    const rt=respText(s.response_content);
    if(rt)h+=section('RESPONSE',`<div class="resp-text">${esc(rt)}</div>`);
    const tools=s.tools||[];
    if(tools.length)
      h+=section(`TOOLS AVAILABLE (${tools.length})`,`<table class="tools"><tr><th>name</th><th>description</th></tr>${toolRows(tools)}</table>`);
  }
  else if(s.type==='tool_call'){
    const bad=isErrOutput(s.output);
    h+=section('OVERVIEW',kv([
      ['tool',esc(s.tool_name||'')],['tool_use_id',esc(s.tool_use_id||'')],
      ['result',bad?'<span class="err-text">⚠ error</span>':(s.output!=null?'ok':'pending')],
    ]));
    if(s.input!=null)h+=section('INPUT',codeBlock(s.input));
    if(s.output!=null)h+=section(bad?'OUTPUT — ERROR':'OUTPUT',codeBlock(s.output,{err:bad}));
  }
  else if(s.type==='error'){
    h+=section('ERROR',codeBlock(String(s.error||'unknown error'),{err:true}));
    if(s.context!=null)h+=section('CONTEXT',codeBlock(s.context));
  }
  else if(s.type==='langgraph_node'){
    h+=section('OVERVIEW',kv([
      ['node',esc(s.tool_name||s.node_name||'')],['node index',s.node_index!=null?s.node_index:''],
    ]));
    if(s.input!=null)h+=section('INPUT',codeBlock(s.input));
    if(s.output!=null)h+=section('OUTPUT',codeBlock(s.output));
  }
  else if(s.type==='langgraph_run'){
    h+=section('OVERVIEW',kv([
      ['mode',esc(s.mode||'')],
      ['nodes executed',Array.isArray(s.nodes_executed)?esc(s.nodes_executed.join(' → ')):''],
    ]));
    if(s.output!=null)h+=section('OUTPUT',codeBlock(s.output));
  }
  else if(s.type==='memory_snapshot'){
    h+=section('OVERVIEW',kv([['label',esc(s.label||'')]]));
    if(s.state!=null)h+=section('MEMORY STATE',codeBlock(s.state));
  }

  const halls=hallByStep[step]||[];
  if(halls.length){
    const cards=halls.map(hl=>`<div class="hcard"><span class="hs">[${esc((hl.severity||'?').toUpperCase())}]</span> ${esc(hl.type||'')}: ${esc(hl.detail||'')}</div>`).join('');
    h+=section(`HALLUCINATIONS (${halls.length})`,cards);
  }

  h+=section('RAW JSON',codeBlock(s,{max:80000}),{collapsible:true,collapsed:true});
  el.innerHTML=h;
  el.scrollTop=0;
}

/* ── selection + keyboard ── */
function select(i){
  if(i<0||i>=spans.length)return;
  sel=i;
  document.querySelectorAll('.srow').forEach(r=>r.classList.toggle('sel',+r.dataset.i===i));
  const row=document.querySelector(`.srow[data-i="${i}"]`);
  if(row)row.scrollIntoView({block:'nearest'});
  renderDetail();
}
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'||e.key==='j'){e.preventDefault();select(sel+1)}
  else if(e.key==='ArrowUp'||e.key==='k'){e.preventDefault();select(sel-1)}
});

renderTopbar();
renderStrip();
renderList();
renderDetail();
</script>
</body>
</html>"""
