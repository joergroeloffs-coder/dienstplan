import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker,{departures,parse,refresh,shipStatus} from '../src/worker.js';
const date=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Berlin'}).format(new Date());
const block={schiff:'Uthlande',abfahrt:'10:02',von:'DAGEBÜLL',nach:'AMRUM',kategorien:{PKW:8}};
const schedule={schiffe:{UTHLANDE:[{datum:date,route:'Dagebüll-Wyk',zeit:'10:00'},{datum:date,route:'Wyk-Wittdün',zeit:'11:00'}]}};
test('Through bookings stay at boarding port; intermediate counts unknown',()=>{const rows=departures([block],schedule,'Uthlande',date);assert.equal(rows[0].nach,'AMRUM');assert.equal(rows[0].abfahrt,'10:00');assert.deepEqual(rows[0].kategorien,{PKW:8});assert.equal(rows[1].von,'FÖHR');assert.deepEqual(rows[1].kategorien,{})});
test('Direct sailings and unmatched bookings survive',()=>{const s=structuredClone(schedule);s.schiffe.UTHLANDE[0].direkt=true;const rows=departures([{...block,abfahrt:'14:00'}],s,'Uthlande',date);assert.equal(rows[0].nach,'AMRUM');assert.deepEqual(rows.at(-1).kategorien,{PKW:8})});
test('Duplicate schedule entries (route+time repeated) do not duplicate the departure',()=>{
  const dupedSchedule={schiffe:{UTHLANDE:[
    {datum:date,route:'Dagebüll-Wyk',zeit:'10:00'},
    {datum:date,route:'Dagebüll-Wyk',zeit:'10:00'},
    {datum:date,route:'Wyk-Wittdün',zeit:'11:00'},
  ]}};
  const rows=departures([block],dupedSchedule,'Uthlande',date);
  assert.equal(rows.length,2);
  assert.equal(rows[0].nach,'AMRUM');
  assert.equal(rows[1].von,'FÖHR');
});
test('Categories are discovered from the description, not a fixed list, and booking suffixes/abbreviations are normalized',()=>{
  const row=(beschreibung,kurzname,kennzeichen)=>'<TR>'+['1',kurzname,'',beschreibung,'','',kennzeichen,'3,0','5,0'.split(' ')[0]].slice(0,8).map(v=>'<TD>'+v+'</TD><TD></TD>').join('')+'</TR>';
  const html='Fahrt: FÖHR-DAGEBÜLL<BR>Abfahrzeit: 09:00'
    +row('PKW Hin- & Rückfahrt','Muster','AB-1')
    +row('Wohnmobil Hin- & Rückfahrt','Camper','AB-2')
    +row('Wohnwagenanhänger Hin/Rf.','Camper','AB-3')
    +row('LKW-Gefahrgut Einfach','Spedition','AB-4')
    +row('PKW-Anh. Hin/Rf.','Camper2','AB-5')
    +row('PKW Spartarif','Sparfuchs','AB-6')
    +'Summe gebuchter Meter:<TD>1,0</TD><TD>2,0</TD>';
  const result=parse(html,'Uthlande');
  assert.deepEqual(result[0].kategorien,{PKW:2,Wohnmobil:1,'Wohnwagen Anhänger':1,'LKW-Gefahrgut':1,'PKW Anhänger':1});
  const arten=result[0].sonderfahrzeuge.map(f=>f.art).sort();
  assert.deepEqual(arten,['LKW-Gefahrgut','PKW Anhänger','Wohnmobil','Wohnwagen Anhänger']);
  assert.ok(!result[0].sonderfahrzeuge.some(f=>f.art==='PKW'));
});
test('Parser keeps customer designation and plate but drops booking number',()=>{const values=['12345','Muster GmbH','','LKW','','AB-CD 123','9,0','12,5'];const row='<TR>'+values.map(v=>'<TD>'+v+'</TD><TD></TD>').join('')+'</TR>';const result=parse('Fahrt: DAGEBÜLL-AMRUM<BR>Abfahrzeit: 10:00'+row+'Summe gebuchter Meter:<TD>9,0</TD><TD>12,5</TD>','Uthlande');assert.equal(result[0].lademeter,12.5);assert.equal(result[0].sonderfahrzeuge[0].kunde,'Muster GmbH');assert.equal(result[0].sonderfahrzeuge[0].kennzeichen,'AB-CD 123');assert.doesNotMatch(JSON.stringify(result),/12345/)});
test('Source with zero current bookings is a valid, successful result',()=>{const result=parse('<HTML>Keine aktuellen Buchungen</HTML>','Schleswig-Holstein');assert.deepEqual(result,[])});
test('Boarding column counts check-in only for the matching departure port, not any port in a through-booking',()=>{
  const rowFor=(boarding,beschreibung)=>'<TR>'+['1',' ','',beschreibung,boarding,'','1,0','2,0'].map(v=>'<TD>'+v+'</TD><TD></TD>').join('')+'</TR>';
  const html='Fahrt: FÖHR-DAGEBÜLL<BR>Abfahrzeit: 09:00'
    +rowFor('F','PKW')      // eingecheckt in Föhr -> zaehlt
    +rowFor('D','PKW')      // nur in Dagebüll eingecheckt (anderer Hafen der Durchgangsbuchung) -> zaehlt NICHT
    +rowFor('DF','LKW')     // auch in Föhr eingecheckt -> zaehlt
    +'Summe gebuchter Meter:<TD>1,0</TD><TD>2,0</TD>';
  const result=parse(html,'Uthlande');
  assert.equal(result[0].checkedIn.PKW,1);
  assert.equal(result[0].checkedIn.LKW,1);
  assert.equal(result[0].sonderfahrzeuge[0].eingecheckt,true);
});
test('Departure card shows the total lademeter already booked for the next physical stop',()=>{
  const naechsterBlock={schiff:'Uthlande',abfahrt:'11:02',von:'FÖHR',nach:'AMRUM',kategorien:{PKW:3},lademeter:7.5};
  const rows=departures([block,naechsterBlock],schedule,'Uthlande',date);
  assert.deepEqual(rows[0].zuladungNaechsteEtappe,{hafen:'FÖHR',lademeter:7.5});
  assert.equal(rows[1].von,'FÖHR');
  assert.equal(rows[1].zuladungNaechsteEtappe,null);
});
test('A shuttle back to the same departure port is not a stopover and gets no preview box',()=>{
  const hinSchedule={schiffe:{UTHLANDE:[{datum:date,route:'Dagebüll-Wyk',zeit:'10:00'},{datum:date,route:'Wyk-Dagebüll',zeit:'11:00'}]}};
  const rueckBlock={schiff:'Uthlande',abfahrt:'11:02',von:'FÖHR',nach:'DAGEBÜLL',kategorien:{PKW:2},lademeter:5};
  const rows=departures([block,rueckBlock],hinSchedule,'Uthlande',date);
  assert.equal(rows[0].zuladungNaechsteEtappe,null);
});
test('Departure shows the tide events bracketing its own departure time',()=>{
  const tideSchedule={...schedule,tiden:{[date]:'HW 3:04 / NW 9:31 / HW 15:15 / NW 22:09'}};
  const rows=departures([block],tideSchedule,'Uthlande',date);
  assert.deepEqual(rows[0].tide,{vorherige:{typ:'NW',zeit:'09:31'},naechste:{typ:'HW',zeit:'15:15'}});
});
test('Tide text whose entries are not in chronological order (PDF column order, not time order) is sorted before use',()=>{
  const mittagsSchedule={schiffe:{UTHLANDE:[{datum:date,route:'Dagebüll-Wyk',zeit:'12:00'}]},tiden:{[date]:'HW 10:48 / NW 4:56 / HW 23:25 / NW 17:36'}};
  const rows=departures([{...block,abfahrt:'12:02'}],mittagsSchedule,'Uthlande',date);
  assert.deepEqual(rows[0].tide,{vorherige:{typ:'HW',zeit:'10:48'},naechste:{typ:'NW',zeit:'17:36'}});
});
test('A departure before the first tide of the day only gets the next one',()=>{
  const fruehSchedule={schiffe:{UTHLANDE:[{datum:date,route:'Dagebüll-Wyk',zeit:'01:00'}]},tiden:{[date]:'HW 3:04 / NW 9:31 / HW 15:15 / NW 22:09'}};
  const rows=departures([{...block,abfahrt:'01:02'}],fruehSchedule,'Uthlande',date);
  assert.deepEqual(rows[0].tide,{vorherige:null,naechste:{typ:'HW',zeit:'03:04'}});
});
test('Missing tide data for the day yields no tide field crash',()=>{
  const rows=departures([block],schedule,'Uthlande',date);
  assert.equal(rows[0].tide,null);
});
test('Fresh retrieval cannot hide old source',()=>{const s={updatedAt:new Date().toISOString(),datum:date,ok:true,sourceModified:'2000-01-01'};assert.equal(shipStatus(s).status,'veraltet');assert.equal(shipStatus({...s,sourceModified:null}).sourceWarning,'Erstellungszeit der Quelle nicht bestätigt.')});
test('Missing timestamps and date rollover fail closed',()=>{assert.equal(shipStatus({}).status,'fehlt');assert.equal(shipStatus({updatedAt:'invalid',datum:date}).status,'veraltet');assert.equal(shipStatus({updatedAt:new Date().toISOString(),datum:'2000-01-01'}).status,'veraltet')});
test('API rejects unauthenticated requests',async()=>{assert.equal((await worker.fetch(new Request('https://test/api/ladeliste'),{})).status,401)});
test('Partial source failure preserves that ship and updates other ships',async()=>{const original=globalThis.fetch;const db=new Map([['ship:NA',{code:'NA',name:'Norderaue',updatedAt:'2000-01-01',abfahrten:[block],datum:date}]]);globalThis.fetch=async(url)=>String(url).includes('github')?Response.json(schedule):String(url).includes('/NA-PKW.html')?new Response('',{status:500}):new Response('Fahrt: DAGEBÜLL-AMRUM<BR>Abfahrzeit: 10:00');try{await refresh({WDR_USER:'fixture',WDR_PASS:'fixture',LADELISTE:{get:async k=>db.get(k),put:async(k,v)=>db.set(k,JSON.parse(v))}});assert.equal(db.get('ship:NA').updatedAt,'2000-01-01');assert.equal(db.get('ship:NA').ok,false);assert.equal(db.get('ship:UTHLANDE').ok,true)}finally{globalThis.fetch=original}});
