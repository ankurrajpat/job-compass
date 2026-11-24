const $ = s => document.querySelector(s);
let busy = false;
function el(tag, text, cls) { const n = document.createElement(tag); if(text !== undefined) n.textContent = text; if(cls) n.className = cls; return n; }
async function api(path, options = {}) { const r = await fetch(path, {headers: {'Content-Type':'application/json'}, ...options}); const d = await r.json(); if(!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Request could not be completed.'); return d; }
function memory(p) { const box = $('#memory-content'); box.replaceChildren(); const values = p.skills || []; values.forEach(s => box.append(el('span',s,'memory-chip'))); if(p.target_role) box.append(el('div',p.target_role,'memory-location')); if(p.location || p.remote_only) box.append(el('div',[p.location, p.remote_only ? 'Remote only' : ''].filter(Boolean).join(' · '),'memory-location')); if(!values.length && !p.target_role && !p.location && !p.remote_only) box.append(el('span','No preferences saved yet.','muted')); $('#memory-state').textContent = box.querySelector('.muted') ? 'EMPTY' : 'SAVED'; }
function result(d) {
 const node = $('#result-template').content.cloneNode(true); node.querySelector('.summary').textContent = d.summary; node.querySelector('.response-mode').textContent = `${d.provider === 'groq' ? 'LIVE LLM' : 'PREVIEW · NO LLM'} · ${d.retrieval_mode} · ${(d.milliseconds/1000).toFixed(1)}s`;
 const grid = node.querySelector('.job-grid');
 d.recommendations.forEach((rec, i) => { const j = d.jobs.find(j => j.id === rec.job_id); if(!j) return; const card=el('section',undefined,'job-card'); card.append(el('div',`${String(i+1).padStart(2,'0')} / ${j.company}`,'job-company'), el('h3',j.title),el('div',`${j.location} · ${j.work_mode}`,'job-meta')); const tags=el('div'); j.skills.forEach(s => tags.append(el('span',s,'skill-chip'))); card.append(tags,el('p',rec.reason)); if(rec.gaps.length) card.append(el('div',`Explore next: ${rec.gaps.join(' · ')}`,'gap')); card.append(el('div',`Retrieval score ${j.score.toFixed(3)} · ${j.source}`,'score')); grid.append(card); });
 node.querySelector('.follow-up').textContent = d.follow_up;
 node.querySelector('.trace-count').textContent = `${d.trace.length} calls`;
 d.trace.forEach(t => { const row=el('div',undefined,'trace-row'); row.append(el('span',t.tool),el('span',`${t.status} · ${t.result_count === null ? '' : t.result_count + ' results · '}${t.milliseconds}ms`)); node.querySelector('.trace-body').append(row); });
 node.querySelector('.export').addEventListener('click',() => { const url=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'})); const a=el('a');a.href=url;a.download='compass-shortlist.json';a.click();setTimeout(() => URL.revokeObjectURL(url),1000); });
 $('#conversation').append(node);memory(d.preferences);
}
async function send(text) {
 if(busy || !text.trim()) return; busy=true;$('#send').disabled=true;document.querySelectorAll('[data-prompt]').forEach(b=>b.disabled=true);$('#conversation').append(el('div',text,'user-message'));$('#prompt').value=''; const loading=el('div','Finding direction. Checking context and tools...','thinking');$('#conversation').append(loading);
 try { const d=await api('/api/chat',{method:'POST',body:JSON.stringify({message:text})});result(d); } catch(e) { $('#conversation').append(el('div',e.message,'error')); } finally { loading.remove();busy=false;$('#send').disabled=false;document.querySelectorAll('[data-prompt]').forEach(b=>b.disabled=false);$('#prompt').focus(); }
}
$('#chat-form').addEventListener('submit',e=>{e.preventDefault();send($('#prompt').value);});
$('#prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send(e.target.value);}});
document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>send(b.dataset.prompt)));
$('#clear-memory').addEventListener('click',async()=>{if(busy)return;try{await api('/api/session',{method:'DELETE'});memory({});$('#conversation').replaceChildren();}catch(e){$('#conversation').append(el('div',e.message,'error'));}});
(async()=>{try{const h=await api('/api/health');$('#status').replaceChildren(el('i'),document.createTextNode(h.provider==='groq'?'Live agent online':'Preview mode · no LLM'));const s=await api('/api/session');memory(s.preferences);if(s.history.length)$('#conversation').append(el('p','Your session preferences are restored. Ask a follow-up to continue.','summary'));}catch(e){$('#status').textContent='Temporarily offline';}})();
