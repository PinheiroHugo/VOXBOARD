const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = file => fs.readFileSync(path.join(__dirname, '../static', file), 'utf8');

function fixture() {
  let Processor, node, processor, uploads = 0, commands = 0, microphoneCalls = 0, stopped = false;
  class Base { constructor() { this.port = { postMessage: data => node?.port.onmessage({data}) }; } }
  vm.runInNewContext(source('recorder-worklet.js'), { AudioWorkletProcessor: Base, sampleRate: 48000,
    registerProcessor: (_, type) => { Processor = type; } });
  const elements = Object.fromEntries(['record-start','record-stop','record-cancel','voice-status','voice-text'].map(id => [id, {
    disabled:false,handlers:{},addEventListener(event,fn){this.handlers[event]=fn;},
    click(){this.lastCall=this.handlers.click();},
  }]));
  class Context {
    constructor(){this.state='running';this.sampleRate=48000;this.audioWorklet={addModule:async()=>{}};}
    async resume(){} async close(){this.state='closed';}
    createMediaStreamSource(){return {connect(){},disconnect(){}};}
  }
  class Node {
    constructor(_,__,options){node=this;this.port={postMessage:data=>processor.port.onmessage({data})};processor=new Processor(options);}
    connect(){} disconnect(){}
  }
  const hooks={onText:async()=>{commands++;return 'Listo';},onNoSpeech:()=> 'No detecté voz. Reintentá.'};
  const context={document:{getElementById:id=>elements[id],querySelector:()=>({dataset:{autoStop:'true',statusUrl:'/estado',transcribeUrl:'/voz',workletUrl:'/worklet'}})},
    window:{AudioWorkletNode:Node,VoxAudio:{encodeWav:()=>new Blob()},VoxVoiceHooks:hooks,addEventListener(){}},
    navigator:{mediaDevices:{getUserMedia:async()=>{microphoneCalls++;return {getTracks:()=>[{stop:()=>{stopped=true;}}]};}}},
    AudioContext:Context,AudioWorkletNode:Node,setTimeout,clearTimeout,AbortSignal,
    fetch:async url=>{
      if(url==='/estado')return {ok:true,json:async()=>({available:true})};
      assert.equal(stopped,true);uploads++;
      return {ok:true,json:async()=>({text:'mostrar ciclo del agua'})};
    }};
  vm.runInNewContext(source('voice.js'),context);
  const feed=(level,ms)=>{for(let i=0;i<ms/10;i++)processor.process([[new Float32Array(480).fill(level)]]);};
  return {elements,feed,counts:()=>({uploads,commands,microphoneCalls,stopped})};
}

test('voz seguida de pausa finaliza sin boton y ejecuta una sola vez aunque llegue un clic manual',async()=>{
  const f=fixture();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.counts().microphoneCalls,0);
  await f.elements['record-start'].handlers.click();
  f.feed(0.08,250);f.feed(0,500);
  assert.equal(f.counts().uploads,0);
  f.feed(0,500);
  await f.elements['record-stop'].handlers.click();
  await f.elements['record-stop'].lastCall;
  f.feed(0,1000);
  assert.deepEqual(f.counts(),{uploads:1,commands:1,microphoneCalls:1,stopped:true});
});

test('sin voz se libera el microfono sin enviar audio; cancelar tampoco transcribe',async()=>{
  for(const cancel of [false,true]){
    const f=fixture();await f.elements['record-start'].handlers.click();
    if(cancel)await f.elements['record-cancel'].handlers.click();
    else {f.feed(0,6600);await f.elements['record-stop'].lastCall;}
    assert.equal(f.counts().uploads,0);assert.equal(f.counts().commands,0);assert.equal(f.counts().stopped,true);
    assert.equal(f.elements['record-start'].disabled,false);
  }
});
