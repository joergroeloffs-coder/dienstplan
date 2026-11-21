const BASE="https://faehre2.de/fileadmin/wdr/Schiffe/Ladeliste";
const SHIPS=[["NA","Norderaue"],["NORDFRIES","Nordfriesland"],["UTHLANDE","Uthlande"],["S-H","Schleswig-Holstein"]];
const WRITE_THROTTLE_MS=8*60*1000;
const STALE_MS=60*60*1000;
function text(s){return (s||"").replace(/<[^>]+>/g,"").replace(/&nbsp;?/gi," ").replace(/&amp;/gi,"&").trim()}
function number(s){if(!s||!/^\d+(?:[,.]\d+)?$/.test(s))return null;return Number(s.replace(",","."))}
function cells(html){return [...html.matchAll(/<TD\b[^>]*>([\s\S]*?)<\/TD>/gi)].map(m=>text(m[1]))}
function meters(block){const i=block.indexOf("Summe gebuchter Meter:");if(i<0)return null;const v=cells(block.slice(i,i+1200)).filter(x=>/^\d+,\d+$/.test(x));return v.length>1?number(v[1]):null}
// Jede Fahrzeugkategorie wird direkt aus der Beschreibung der Buchung
// abgeleitet statt aus einer festen Liste - so entsteht automatisch ein
// eigenes Feld fuer jede tatsaechlich vorkommende Art (PKW, LKW,
// Transporter, Wohnmobil, Wohnwagenanhaenger, ...). Dazu werden reine
// Buchungszusaetze (Hin-/Rueckfahrt, Reservierung, Einfach, Doppelt) vom
// Ende der Beschreibung abgeschnitten, bis nur noch die Fahrzeugart uebrig
// bleibt, und gaengige Abkuerzungen vereinheitlicht (z.B. "PKW-Anh." und
// "PKW Anhänger" sollen dieselbe Kategorie sein).
const SUFFIX_RE=/\s*(?:hin-?\s*&?\s*r(?:ü|ue)ckf(?:ahrt)?\.?|hin\/?rf\.?|r(?:ü|ue)ckf(?:ahrt)?\.?|reservierung|einfach|doppelt)\.?$/i;
const ANHAENGER_RE=/[-\s]*anh(?:\.|ä?nger)?$/i;
function kategorieVon(beschreibung){
  let s=(beschreibung||"").trim(),prev;
  do{prev=s;s=s.replace(SUFFIX_RE,"").trim();}while(s&&s!==prev);
  s=s.replace(ANHAENGER_RE," Anhänger").trim();
  return s||"Sonstige";
}
// Die Boarding-Spalte (eine Zelle nach der Beschreibung) nennt ein- bis
// zweistellig die Häfen, an denen das Fahrzeug den Check-in schon
// durchlaufen hat (F=Föhr, D=Dagebüll, A=Amrum). "Eingecheckt für diese
// Abfahrt" heißt: der Anfangsbuchstabe des Abfahrtshafens dieser Fahrt
// steckt in der Boarding-Zelle - sonst koennte bei Durchgangsbuchungen
// faelschlich ein anderer Hafen der Reise mitgezaehlt werden.
export function parse(html,ship){
  const starts=[...html.matchAll(/Fahrt:\s*([^<]+?)-([^<]+?)</gi)];
  return starts.map((m,i)=>{
    const block=html.slice(m.index,starts[i+1]?.index??html.length);
    const time=/Abfahrzeit:\s*(\d{2}:\d{2})/i.exec(block)?.[1];
    if(!time)return null;
    const von=m[1].trim();
    const originLetter=von.charAt(0).toUpperCase();
    const fahrzeuge=[],checkedIn={},kategorien={};
    for(const row of block.matchAll(/<TR>([\s\S]*?)<\/TR>/gi)){
      const c=cells(row[1]).filter((_,i)=>i%2===0);
      if(c.length<8||!/^\d+$/.test(c[0]))continue;
      const kategorie=kategorieVon(c[3]);
      kategorien[kategorie]=(kategorien[kategorie]||0)+1;
      checkedIn[kategorie]=(checkedIn[kategorie]||0)+((c[4]||"").toUpperCase().includes(originLetter)?1:0);
      if(kategorie!=="PKW")fahrzeuge.push({art:kategorie,kunde:c[1]||null,kennzeichen:c[5]||null,laenge_m:number(c[7])});
    }
    return {schiff:ship,abfahrt:time,von,nach:m[2].trim(),
      kategorien,lademeter:meters(block),sonderfahrzeuge:fahrzeuge,checkedIn};
  }).filter(Boolean);
}
const CATEGORIES={Norderaue:"NORDERAUE",Nordfriesland:"NORDFRIESLAND",Uthlande:"UTHLANDE","Schleswig-Holstein":"SCHLESWIG - HOLSTEIN"};
const PORTS={"Wittdün":"AMRUM",Wyk:"FÖHR","Dagebüll":"DAGEBÜLL"};
const DIRECT={"Wittdün-Wyk":"Dagebüll","Dagebüll-Wyk":"Wittdün"};
const dateBerlin=()=>new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Berlin",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
const minutes=t=>Number(t.slice(0,2))*60+Number(t.slice(3));
// Tide-Text aus dem Fahrplan-PDF, z.B. "HW 3:04 / NW 9:31 / HW 15:15 /
// NW 22:09" - ein Wert pro Kalendertag, gilt fuer alle Schiffe/Routen
// dieses Tages gleich.
function parseTiden(text){
  if(!text)return[];
  return text.split("/").map(s=>s.trim()).map(s=>{
    const m=/^(HW|NW)\s+(\d{1,2}):(\d{2})$/.exec(s);
    return m?{typ:m[1],zeit:m[2].padStart(2,"0")+":"+m[3]}:null;
  }).filter(Boolean);
}
// Fuer eine Abfahrtszeit die zeitlich davor- und danachliegende Tide
// ermitteln (Trend: steigend/fallend Richtung des naechsten Extrems).
function tideFuerAbfahrt(tiden,abfahrtZeit){
  if(!tiden.length)return null;
  const t=minutes(abfahrtZeit);
  let vorherige=null,naechste=null;
  for(const e of tiden){
    if(minutes(e.zeit)<=t)vorherige=e;
    else if(!naechste)naechste=e;
  }
  return vorherige||naechste?{vorherige,naechste}:null;
}
export function departures(blocks,schedule,ship,date){
  // fahrplan_schedule.json kann je Route+Zeit doppelte Eintraege enthalten
  // (Fehler in der vorgelagerten Fahrplan-Generierung) - deshalb hier je
  // Schiff/Tag auf eindeutige Route+Zeit-Kombinationen eindampfen, sonst
  // erscheint jede Abfahrt zweimal.
  const seenLegs=new Set();
  const legs=(schedule.schiffe?.[CATEGORIES[ship]]||[]).filter(e=>e.datum===date).filter(e=>{
    const key=e.route+"|"+e.zeit;
    if(seenLegs.has(key))return false;
    seenLegs.add(key);
    return true;
  });
  if(!legs.length)return blocks.map(b=>({...b,hinweis:"Kein Fahrplan für diesen Tag verfügbar – laut Buchung"}));

  // Vorberechnung je Etappe (Hafen, Ziel, passende Buchungsbloecke, deren
  // Lademeter-Summe): so kann am Abfahrtshafen schon angezeigt werden, wie
  // viel an der naechsten Etappe (sofern direkt anschliessend, Hafen=Ziel
  // dieser Etappe) bereits zugeladen ist - die Ladung reist ja an Bord
  // weiter und blockiert dort schon Kapazitaet.
  const etappen=legs.map(leg=>{
    const [from,to]=leg.route.split("-").map(s=>s.trim());
    if(!from||!to||!/^\d{2}:\d{2}$/.test(leg.zeit))throw Error("Ungültiger Fahrplan");
    const target=leg.direkt&&DIRECT[leg.route]||to;
    const origin=PORTS[from]||from.toUpperCase();
    const ziel=PORTS[target]||target;
    const matches=blocks.filter(b=>b.von===origin&&Math.abs(minutes(b.abfahrt)-minutes(leg.zeit))<=5);
    const lademeterGesamt=matches.reduce((sum,b)=>sum+(b.lademeter||0),0);
    return {leg,origin,ziel,matches,lademeterGesamt};
  }).sort((a,b)=>minutes(a.leg.zeit)-minutes(b.leg.zeit));

  const tidenDesTages=parseTiden(schedule.tiden?.[date]);
  const used=new Set(), output=[];
  for(let i=0;i<etappen.length;i++){
    const {leg,origin,ziel,matches,lademeterGesamt}=etappen[i];
    // Nur ein echter Zwischenstopp auf dem Weg zu einem anderen Hafen ist
    // relevant: faehrt das Schiff ab dem Zwischenhafen nur wieder zurueck
    // zum Ausgangshafen (reiner Pendelverkehr, keine Durchgangsladung),
    // ist das schon auf der naechsten Abfahrtskarte selbst zu sehen.
    const naechste=etappen.slice(i+1).find(e=>e.origin===ziel);
    const zuladungNaechsteEtappe=(naechste&&naechste.ziel!==origin)?{hafen:naechste.origin,lademeter:naechste.lademeterGesamt}:null;
    const tide=tideFuerAbfahrt(tidenDesTages,leg.zeit);
    if(!matches.length)output.push({schiff:ship,abfahrt:leg.zeit,von:origin,nach:ziel,lademeter:null,sonderfahrzeuge:[],checkedIn:{},kategorien:{},hinweis:"Noch keine eigene Buchung zu dieser Etappe",zuladungNaechsteEtappe,tide});
    for(const b of matches){used.add(b);output.push({...b,abfahrt:leg.zeit,zuladungNaechsteEtappe,tide});}
  }
  for(const b of blocks)if(!used.has(b))output.push({...b,hinweis:"Nicht im Fahrplan enthalten – laut aktueller Buchung"});
  return output;
}
function dueForWrite(previous,attemptedAt){
  if(!previous?.attemptedAt)return true;
  const elapsed=Date.parse(attemptedAt)-Date.parse(previous.attemptedAt);
  return !Number.isFinite(elapsed)||elapsed>=WRITE_THROTTLE_MS;
}
export async function refresh(env){
  const attemptedAt=new Date().toISOString(), datum=dateBerlin();
  if(!env.WDR_USER||!env.WDR_PASS)throw Error("Zugangsdaten fehlen");
  const auth="Basic "+btoa(env.WDR_USER+":"+env.WDR_PASS);
  let schedule={};
  try{const r=await fetch("https://raw.githubusercontent.com/joergroeloffs-coder/dienstplan/main/fahrplan_schedule.json",{cache:"no-store",signal:AbortSignal.timeout(15000)});if(r.ok)schedule=await r.json();}catch{}
  const ships=await Promise.all(SHIPS.map(async([code,name])=>{
    const previous=await env.LADELISTE.get("ship:"+code,"json");
    try{
      // "-PKW" liefert zusätzlich zur Basis-Datei jede normale PKW-Buchung
      // einzeln (inkl. Boarding-Spalte) statt nur die Sonderfahrzeuge.
      const r=await fetch(BASE+"/"+code+"-PKW.html?t="+Date.now(),{headers:{Authorization:auth,"Cache-Control":"no-cache"},signal:AbortSignal.timeout(15000),redirect:"manual"});
      if(!r.ok)throw Error((r.status===401||r.status===403?"AUTH":"SOURCE")+":"+r.status);
      const charset=/charset=([^; ]+)/i.exec(r.headers.get("content-type")||"")?.[1]||"windows-1252";
      const html=new TextDecoder(charset).decode(await r.arrayBuffer());
      const blocks=parse(html,name);
      if(dateBerlin()!==datum)throw Error("DATE");
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(html)))).map(n=>n.toString(16).padStart(2,"0")).join("");
      const changed=previous?.digest!==digest;
      const result={code,name,datum,updatedAt:new Date().toISOString(),attemptedAt,ok:true,sourceModified:r.headers.get("last-modified"),sourceUnchangedSince:changed?attemptedAt:previous?.sourceUnchangedSince,digest,fahrplanStand:schedule.generated_at||null,fahrplanOk:!!schedule.schiffe?.[CATEGORIES[name]]?.some(e=>e.datum===datum),abfahrten:departures(blocks,schedule,name,datum)};
      // Abruf laeuft nur noch auf Anforderung (Button/erster Seitenaufruf),
      // kein Hintergrund-Cron mehr - die Drosselung schuetzt lediglich vor
      // mehrfachen Schreibvorgaengen bei schnell aufeinanderfolgenden Klicks.
      if(changed||dueForWrite(previous,attemptedAt))await env.LADELISTE.put("ship:"+code,JSON.stringify(result));
      return result;
    }catch(e){
      const msg=String(e&&e.message||e);
      const friendly=msg.startsWith("AUTH")?"WDR-Anmeldung abgelehnt. Zugangsdaten prüfen.":msg.startsWith("SOURCE")?"Quelle antwortet mit Fehlerstatus ("+msg.split(":")[1]+").":msg==="DATE"?"Quelle meldet Datumswechsel während des Abrufs.":"Unerwarteter Fehler beim Abruf: "+msg;
      const result={...(previous||{code,name,abfahrten:[],updatedAt:null}),attemptedAt,ok:false,error:friendly};
      const wasAlreadyError=previous?.ok===false;
      if(!wasAlreadyError||dueForWrite(previous,attemptedAt))await env.LADELISTE.put("ship:"+code,JSON.stringify(result));
      return result;
    }
  }));
  return {ships};
}
export function shipStatus(s,now=Date.now()){
  const age=now-Date.parse(s.updatedAt),sourceAge=s.sourceModified?now-Date.parse(s.sourceModified):null;
  return {...s,digest:undefined,status:!s.updatedAt?"fehlt":!Number.isFinite(age)||age<0||age>STALE_MS||s.datum!==dateBerlin()||sourceAge!==null&&sourceAge>STALE_MS?"veraltet":!s.ok?"fehler":"abgerufen",sourceWarning:!s.sourceModified?"Erstellungszeit der Quelle nicht bestätigt.":null};
}
export default{
  async fetch(request,env){
    const u=new URL(request.url),headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"};
    if(!env.API_TOKEN||request.headers.get("Authorization")!=="Bearer "+env.API_TOKEN)return Response.json({error:"Nicht berechtigt"},{status:401,headers});
    if(u.pathname==="/api/refresh"&&request.method==="POST"){
      try{await refresh(env)}catch{return Response.json({error:"Zugangsdaten oder Speicher fehlen"},{status:503,headers})}
    }else if(u.pathname!=="/api/ladeliste"||request.method!=="GET")return new Response("Not found",{status:404,headers});
    const ships=await Promise.all(SHIPS.map(async([code,name])=>shipStatus(await env.LADELISTE.get("ship:"+code,"json")||{code,name,abfahrten:[],updatedAt:null})));
    return Response.json({ships,abfahrten:ships.flatMap(s=>s.abfahrten).sort((a,b)=>a.abfahrt.localeCompare(b.abfahrt)||a.schiff.localeCompare(b.schiff)),checkedAt:new Date().toISOString(),datum:dateBerlin(),interval:120},{headers});
  }
};
