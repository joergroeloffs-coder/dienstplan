import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker,{departures,parse,refresh} from '../src/worker.js';
const block={schiff:'Uthlande',abfahrt:'10:02',von:'DAGEBÜLL',nach:'AMRUM',pkw:8};
const schedule={schiffe:{UTHLANDE:[{datum:'2026-11-11',route:'Dagebüll-Wyk',zeit:'10:00'},{datum:'2026-11-11',route:'Wyk-Wittdün',zeit:'11:00'}]}};
test('Through bookings stay at boarding port; intermediate departure has unknown counts',()=>{
 const rows=departures([block],schedule,'Uthlande','2026-11-11');
 assert.equal(rows[0].nach,'AMRUM');assert.equal(rows[0].abfahrt,'10:00');assert.equal(rows[1].von,'FÖHR');assert.equal(rows[1].pkw,null);
});
test('Direct sailings and unmatched bookings survive',()=>{
 const s=structuredClone(schedule);s.schiffe.UTHLANDE[0].direkt=true;
 const rows=departures([{...block,abfahrt:'14:00'}],s,'Uthlande','2026-11-11');
 assert.equal(rows[0].nach,'AMRUM');assert.equal(rows.at(-1).pkw,8);assert.match(rows.at(-1).hinweis,/Nicht im Fahrplan/);
});
test('Parser uses PKW meter column and excludes personal fields',()=>{
 const values=['12345','PRIVATE NAME','','LKW','','PRIVATE PLATE','9,0','12,5'];
 const row='<TR>'+values.map(v=>'<TD>'+v+'</TD><TD></TD>').join('')+'</TR>';
 const html='Fahrt: DAGEBÜLL-AMRUM<BR>Abfahrzeit: 10:00 gebuchte PKW 8, Motorräder 2 und Transporter 1'+row+'Summe gebuchter Meter:<TD>9,0</TD><TD>12,5</TD>';
 const result=parse(html,'Uthlande');assert.equal(result[0].lademeter,12.5);assert.equal(result[0].sonderfahrzeuge[0].art,'LKW');assert.doesNotMatch(JSON.stringify(result),/PRIVATE|12345/);
});
test('Failed refresh preserves snapshot and records failed attempt',async()=>{
 const db=new Map([['latest','unchanged']]);const env={LADELISTE:{put:async(k,v)=>db.set(k,v)}};
 await assert.rejects(refresh(env));assert.equal(db.get('latest'),'unchanged');assert.equal(JSON.parse(db.get('health')).ok,false);
});
test('API marks stale snapshot, including after midnight',async()=>{
 const env={LADELISTE:{get:async(k)=>k==='latest'?{updatedAt:new Date().toISOString(),datum:'2000-01-01',abfahrten:[]}:{ok:false}}};
 const response=await worker.fetch(new Request('https://test/api/ladeliste'),env);
 assert.equal((await response.json()).status,'veraltet');assert.equal(response.headers.get('cache-control'),'no-store');
});
