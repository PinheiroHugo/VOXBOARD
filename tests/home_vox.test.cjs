const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function home(active = '') {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {dataset:{},value:'',textContent:'',hidden:true,options:[],handlers:{},
      addEventListener(event,fn){this.handlers[event]=fn;},focus(){this.focused=true;},
      showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();},add(option){this.options.push(option);this.value=option.value;}});
    return nodes.get(id);
  };
  const panel=element('panel');
  panel.dataset={previewUrl:'/preview',confirmUrl:'/confirm',activeCourse:active,performanceUrl:'/cursos/1/rendimiento',courseUrl:'/mi-curso',dailyUrl:'/mi-curso/registro'};
  element('vox-resources').textContent=JSON.stringify([['ciclo-del-agua','Ciclo del agua'],['sistema-solar','Sistema solar']]);
  element('vox-resources').dataset.root='/static/resources/';
  if(active) element('vox-session').options.push({value:active,textContent:'Sesion '+active});
  element('vox-session').value=active;
  element('vox-date').value='2026-11-18';
  const navigations=[], requests=[], writes=[];
  const context={window:{location:{assign:url=>navigations.push(url)}},
    document:{getElementById:element,querySelector:()=>panel,querySelectorAll:()=>[]},AbortSignal,
    Option:function(text,value){this.textContent=text;this.value=value;},
    fetch:async(url,options)=>{
      const body=JSON.parse(options.body);requests.push({url,body});
      let data;
      if(url==='/preview') {
        if(!body.course_id) data={needs:['course'],kind:'grade'};
        else if(body.text==='registrar nota'&&!body.student_id) data={needs:['student','value'],kind:'grade'};
        else data={needs:[],preview:{name:'Ana Garcia',student_id:1,kind:'grade',value:85,course_id:1,class_date:body.class_date,context:'Curso 2026 - '+body.class_date,source_text:body.text,token:'signed'}};
      }
      else if(url==='/create') data={session_id:1,class_date:'2026-11-18'};
      else {writes.push(body);data={message:'Cambio confirmado y guardado.'};}
      return {ok:true,json:async()=>data};
    }};
  for(const file of ['resource-commands.js','home-vox.js']) vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static',file),'utf8'),context);
  return {hooks:context.window.VoxVoiceHooks,element,navigations,requests,writes};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('todos los recursos se abren en modal sin sesion y cerrar conserva la portada',async()=>{
  const {hooks,element,navigations,requests}=home();
  assert.equal(requests.length,0);
  for(const [command,id] of [['MOSTRAR CICLO DEL AGUA','ciclo-del-agua'],['mostrar sistema solar','sistema-solar']]) {
    await hooks.onText(command);
    assert.equal(element('vox-resource-dialog').open,true);
    assert.equal(element('vox-resource-image').src,'/static/resources/'+id+'.svg');
    assert.equal(element('vox-school-fields').hidden,true);
    element('vox-close-resource').handlers.click();
    assert.equal(element('vox-resource-dialog').open,false);
  }
  assert.equal(navigations.length,0);assert.equal(requests.length,0);
  assert.match(await hooks.onText('hola clase'),/mostrar ciclo del agua/);
});

test('nota incompleta pide estudiante y valor, retoma la frase y cancelar no confirma',async()=>{
  const {hooks,element,requests,writes}=home('1');
  await hooks.onText('registrar nota');
  assert.equal(element('vox-school-fields').hidden,false);
  element('vox-student').value='1';element('vox-grade-value').value='85';
  element('vox-complete-command').handlers.submit({preventDefault(){}});await flush();
  assert.equal(element('vox-school-preview').hidden,false);
  assert.match(element('vox-preview-description').textContent,/85/);
  assert.equal(requests[1].body.text,requests[0].body.text);
  element('vox-cancel-confirmation').handlers.click();await flush();
  assert.equal(element('vox-school-preview').hidden,true);assert.equal(writes.length,0);
});

test('curso activo y fecha permiten vista previa directa; solamente Confirmar guarda',async()=>{
  const {hooks,element,writes}=home('1');
  await hooks.onText('registrar nota 85 al estudiante uno');
  assert.equal(element('vox-school-fields').hidden,true);
  assert.equal(element('vox-school-preview').hidden,false);
  assert.equal(writes.length,0);
  element('vox-confirm-command').handlers.click();await flush();
  assert.equal(writes.length,1);assert.equal(writes[0].token,'signed');
  hooks.onStart();hooks.onRecording();
  assert.equal(element('vox-character').dataset.state,'listening');
  hooks.onNoSpeech();hooks.onFinish();
  assert.equal(element('vox-character').dataset.state,'idle');
});

test('corregir la fecha descarta el token previo y vuelve a pedir la vista previa sin repetir voz',async()=>{
  const {hooks,element,requests}=home('1');
  await hooks.onText('registrar nota 85 al estudiante uno');
  element('vox-date').value='2026-11-17';
  element('vox-date').handlers.change();await flush();
  assert.equal(requests.length,2);
  assert.equal(requests[1].body.class_date,'2026-11-17');
  assert.equal(requests[1].body.text,requests[0].body.text);
  assert.match(element('vox-preview-description').textContent,/2026-11-17/);
  assert.equal(element('vox-confirm-command').disabled,false);
});
