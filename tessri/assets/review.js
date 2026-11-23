/* Repository data is text, never HTML or executable code. No agent messages or test commands are sent. */
(()=>{'use strict';
let data=JSON.parse(document.getElementById('review-data').textContent), selectedPath='', selectedFinding='', version='current';
const $=id=>document.getElementById('tr-'+id), text=(id,value)=>{$(id).textContent=value;};
const node=(tag,value,cls)=>{const el=document.createElement(tag);if(value!==undefined)el.textContent=value;if(cls)el.className=cls;return el;};
const b=()=>data.brief, rows=()=>b().triage.files, findings=()=>b().consequences.findings;
function choosePath(path){selectedPath=path;version=rows().find(r=>r.path===path)?.change==='deleted'?'base':'current';$('version').value=version;drawFiles();drawSource();}
function drawFiles(){
 const box=$('files');box.replaceChildren();const changed=new Set(rows().map(r=>r.path)),seen=new Set();
 const groups=[['Look first · '+rows().length+' changed files',rows().map(r=>r.path)],['Outside the diff',Object.values(data.related).flat().filter(p=>!changed.has(p))],['Candidate tests',b().triage.tests.paths]];
 const query=$('filter').value.toLowerCase();
 groups.forEach(([label,paths])=>{const group=node('div');let count=0;paths.forEach(path=>{if(seen.has(path))return;seen.add(path);if(!path.toLowerCase().includes(query))return;count++;const button=node('button',undefined,'tr-file'+(path===selectedPath?' selected':''));button.type='button';button.setAttribute('aria-pressed',String(path===selectedPath));button.append(node('span',path,'tr-name'));const row=rows().find(r=>r.path===path);button.append(node('small',row?row.change:'context'));button.addEventListener('click',()=>choosePath(path));group.append(button);});if(count){box.append(node('p',label,'tr-group'),group);}});
 if(!box.childNodes.length)box.append(node('p','No matching files.','tr-hint'));
}
function drawSource(){
 text('path',selectedPath||'No source file selected');const row=rows().find(r=>r.path===selectedPath);text('state',row?.change||'outside the diff');
 const src=data.sources[selectedPath]?.[version];text('source-note',version==='base'?'Base '+b().change.base:'Working tree captured at '+b().generated_at);
 const code=$('code');code.replaceChildren();
 if(src?.text!==null&&src?.text!==undefined){const lines=src.text.split('\n');if(lines.at(-1)==='')lines.pop();if(!lines.length)code.append(node('span','Empty file.','tr-source-note'));lines.forEach((line,i)=>{const item=node('span',undefined,'tr-line');const number=node('span',String(i+1),'tr-ln');number.setAttribute('aria-hidden','true');const content=node('span',undefined,'tr-code-text');line.split(/(\b(?:from|import|def|class|return|if|else|for|in|const|function)\b)/).forEach((part,j)=>content.append(node('span',part,j%2?'tr-keyword':'')));item.append(number,content,document.createTextNode("\n"));code.append(item);});}
 else code.append(node('span',src?.reason||'Source not captured. Capture is limited to '+data.source_limit+' relevant files; the full evidence remains below.','tr-source-note'));
 text('reason',row?('Rank '+row.rank+' · '+row.commits_active+' base-history commits in '+b().attention.window_days+' days.\n'+(row.flags.join('; ')||'No file flags recorded.')):'Context outside the changed-file list. Inspect the selected finding for why this path belongs in the review.');
}
function drawFinding(){
 const box=$('finding');box.replaceChildren();const f=findings().find(f=>f.id===selectedFinding);
 if(!f){box.append(node('h2','No structural findings','tr-finding-title'),node('p',b().meta.analysis.structure==='skipped'?'No code comparison was made.':'No structural finding in the analyzed code. This is not proof that the change is safe.','tr-finding-detail'));return;}
 box.append(node('p',f.severity+' · '+f.kind,'tr-severity '+f.severity),node('h2',f.title.replaceAll('`',''),'tr-finding-title'),node('p',f.detail.replaceAll('`',''),'tr-finding-detail'));
 const links=node('div',undefined,'tr-relations');(data.related[f.id]||f.files).forEach(path=>{const button=node('button',path);button.type='button';button.addEventListener('click',()=>choosePath(path));links.append(button);});box.append(links);
 if(f.action)box.append(node('p','Next check. '+f.action.replaceAll('`',''),'tr-finding-detail'));
 const copy=node('button','Copy context for your agent','tr-copy');copy.type='button';copy.addEventListener('click',async()=>{
  const c=b().change;const report=b().validation;const context=['Tessri review: '+b().repo.name,'Scope: '+c.since+' · base '+c.base+' · HEAD '+c.head+(c.uncommitted?' · includes uncommitted contents':''),'Captured: '+b().generated_at,'Finding ('+f.severity+'): '+f.title,f.detail,'Paths: '+(data.related[f.id]||f.files).join(', '),'Next check: '+f.action,'Host-recorded checks: '+(report.ran.join('; ')||'none recorded'),'Code snapshot association of validation: unknown. Candidate tests are paths, not executions.','Static evidence does not prove runtime behavior.'].join('\n');
  try{await navigator.clipboard.writeText(context);copy.textContent='Context copied';}catch{const area=node('textarea');area.value=context;area.setAttribute('aria-label','Context to copy manually');area.style.width='100%';area.rows=9;box.append(area);area.focus();area.select();copy.textContent='Select and copy the context below';}
 });box.append(copy);
}
function draw(){
 const c=b().change;text('repo',b().repo.name);text('ref',c.since+' → '+c.head.slice(0,9));text('mode',data.live?'Local session':data.example?'Worked example':'Offline snapshot');text('counts',c.code_files+' changed code files · '+c.lines+' lines'+(c.uncommitted?' · includes uncommitted files':''));text('time',b().generated_at);
 $('refresh').hidden=!data.live;$('example').hidden=!data.example;
 const select=$('findings');select.replaceChildren();findings().forEach(f=>{const opt=node('option',f.severity+' · '+f.title.replaceAll('`',''));opt.value=f.id;select.append(opt);});select.disabled=!findings().length;
 if(!findings().some(f=>f.id===selectedFinding))selectedFinding=findings()[0]?.id||'';select.value=selectedFinding;
 if(!selectedPath||(!data.sources[selectedPath]&&!rows().some(r=>r.path===selectedPath)))selectedPath=data.related[selectedFinding]?.[0]||rows()[0]?.path||'';
 version=rows().find(r=>r.path===selectedPath)?.change==='deleted'?'base':version;$('version').value=version;drawFiles();drawSource();drawFinding();
 const validation=$('validation');validation.replaceChildren();const v=b().validation;
 validation.append(node('p',v.candidates.count+' candidate test files. Paths, not executions.','tr-validation-note'));
 (v.ran.length?v.ran:['No host check was recorded as run.']).forEach(line=>validation.append(node('p',line,'tr-validation-note')));
 if(v.report)validation.append(node('p','JUnit: '+v.report.passed+' candidate files passed; '+v.report.failed.length+' failed; '+v.report.not_run.length+' not in the report.','tr-validation-note'));
 if(v.coverage)validation.append(node('p','Coverage: '+v.coverage.not_run+' changed statements not executed; '+Object.keys(v.coverage.not_measured).length+' changed files not measured. See full evidence.','tr-validation-note'));
 validation.append(node('p','Code snapshot association: '+((v.ran.length||v.report||v.coverage)?'unknown. Host results have not been verified against the current code.':'unavailable. No validation result supplied.'),'tr-unknown'));
 const people=$('people');people.replaceChildren();const reviewers=b().people.reviewers;if(reviewers.length)reviewers.forEach(p=>people.append(node('p',p.name)));else people.append(node('p','No other maintainer identified.'));people.append(node('p','History records commits, not who reviewed.'));
 text('json',JSON.stringify(b(),null,2));setStale(Boolean(data.changed_during_capture));
}
function setStale(stale,message){$('stale').hidden=!stale;text('stale',message||'The checkout or supplied reports changed. This view contains an older snapshot; refresh before using it for this change.');}
let refreshing=false;
$('refresh').addEventListener('click',async()=>{if(refreshing)return;refreshing=true;$('refresh').disabled=true;text('refresh','Refreshing…');$('error').hidden=true;try{const token=location.pathname.split('/')[1];const response=await fetch('refresh',{method:'POST',headers:{'X-Tessri-Review':token}});const result=await response.json();if(!response.ok)throw Error(result.error||'Refresh failed');data={...result,live:true,example:false};draw();}catch(e){$('error').hidden=false;text('error',e.message);setStale(true,'Refresh failed. The previous snapshot remains visible.');}finally{refreshing=false;$('refresh').disabled=false;text('refresh','Refresh analysis');}});
$('filter').addEventListener('input',drawFiles);$('version').addEventListener('change',()=>{version=$('version').value;drawSource();});$('findings').addEventListener('change',()=>{selectedFinding=$('findings').value;drawFinding();const first=data.related[selectedFinding]?.[0];if(first)choosePath(first);});
draw();
if(data.live){const poll=async()=>{try{if(!refreshing){const response=await fetch('status');if(!response.ok)throw Error();setStale((await response.json()).stale);}}catch{setStale(true,'The local session is unavailable. This is a captured snapshot; restart tessri review to continue.');}setTimeout(poll,4000);};setTimeout(poll,4000);}
})();
