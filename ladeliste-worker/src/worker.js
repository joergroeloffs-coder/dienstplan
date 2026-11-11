const BASE="https://faehre2.de/fileadmin/wdr/Schiffe/Ladeliste";
const SHIPS=[["NA","Norderaue"],["NORDFRIES","Nordfriesland"],["UTHLANDE","Uthlande"],["S-H","Schleswig-Holstein"]];
function text(s){return (s||"").replace(/<[^>]+>/g,"").replace(/&nbsp;?/gi," ").replace(/&amp;/gi,"&").trim()}
function number(s){if(!s||!/^\d+(?:[,.]\d+)?$/.test(s))return null;return Number(s.replace(",","."))}
function cells(html){return [...html.matchAll(/<TD\b[^>]*>([\s\S]*?)<\/TD>/gi)].map(m=>text(m[1]))}
function meters(block){const i=block.indexOf("Summe gebuchter Meter:");if(i<0)return null;const v=cells(block.slice(i,i+1200)).filter(x=>/^\d+,\d+$/.test(x));return v.length>1?number(v[1]):null}
export function parse(html,ship){
  const starts=[...html.matchAll(/Fahrt:\s*([^<]+?)-([^<]+?)</gi)];
  if(!starts.length)throw Error("Keine Fahrten: "+ship);
  return starts.map((m,i)=>{
    const block=html.slice(m.index,starts[i+1]?.index??html.length);
    const time=/Abfahrzeit:\s*(\d{2}:\d{2})/i.exec(block)?.[1];
    if(!time)return null;
    const counts=/gebuchte PKW (\d+), Motorr.der (\d+) und Transporter (\d+)/i.exec(block);
    const specials=[];
    for(const row of block.matchAll(/<TR>([\s\S]*?)<\/TR>/gi)){
      const c=cells(row[1]).filter((_,i)=>i%2===0);
      if(c.length<8||!/^\d+$/.test(c[0]))continue;
      const d=c[3]||"";
      const type=/LKW/i.test(d)?"LKW":/Transporter/i.test(d)?"Transporter":/PKW[- ]Anh/i.test(d)?"PKW-Anhänger":/Motorrad/i.test(d)?"Motorrad":null;
      if(type)specials.push({art:type,laenge_m:number(c[7])});
    }
    return {schiff:ship,abfahrt:time,von:m[1].trim(),nach:m[2].trim(),
      pkw:counts?Number(counts[1]):null,motorraeder:counts?Number(counts[2]):null,
      transporter:counts?Number(counts[3]):null,lademeter:meters(block),sonderfahrzeuge:specials};
  }).filter(Boolean);
}
const CATEGORIES={Norderaue:"NORDERAUE",Nordfriesland:"NORDFRIESLAND",Uthlande:"UTHLANDE","Schleswig-Holstein":"SCHLESWIG - HOLSTEIN"};
const PORTS={"Wittdün":"AMRUM",Wyk:"FÖHR","Dagebüll":"DAGEBÜLL"};
const DIRECT={"Wittdün-Wyk":"Dagebüll","Dagebüll-Wyk":"Wittdün"};
const dateBerlin=()=>new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Berlin",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
const minutes=t=>Number(t.slice(0,2))*60+Number(t.slice(3));
export function departures(blocks,schedule,ship,date){
  const legs=(schedule.schiffe?.[CATEGORIES[ship]]||[]).filter(e=>e.datum===date);
  if(!legs.length)return blocks.map(b=>({...b,hinweis:"Kein Fahrplan für diesen Tag verfügbar – laut Buchung"}));
  const used=new Set(), output=[];
  for(const leg of legs){
    const [from,to]=leg.route.split("-").map(s=>s.trim());
    if(!from||!to||!/^\d{2}:\d{2}$/.test(leg.zeit))throw Error("Ungültiger Fahrplan");
    const target=leg.direkt&&DIRECT[leg.route]||to;
    const matches=blocks.filter(b=>b.von===(PORTS[from]||from.toUpperCase())&&Math.abs(minutes(b.abfahrt)-minutes(leg.zeit))<=5);
    if(!matches.length)output.push({schiff:ship,abfahrt:leg.zeit,von:PORTS[from]||from,nach:PORTS[target]||target,pkw:null,motorraeder:null,transporter:null,lademeter:null,sonderfahrzeuge:[],hinweis:"Noch keine eigene Buchung zu dieser Etappe"});
    for(const b of matches){used.add(b);output.push({...b,abfahrt:leg.zeit});}
  }
  for(const b of blocks)if(!used.has(b))output.push({...b,hinweis:"Nicht im Fahrplan enthalten – laut aktueller Buchung"});
  return output;
}
export async function refresh(env){
  const attemptedAt=new Date().toISOString();
  try{
    if(!env.WDR_USER||!env.WDR_PASS)throw Error("Zugangsdaten fehlen");
    const auth="Basic "+btoa(env.WDR_USER+":"+env.WDR_PASS);
    const scheduleResponse=await fetch("https://raw.githubusercontent.com/joergroeloffs-coder/dienstplan/main/fahrplan_schedule.json",{cache:"no-store",signal:AbortSignal.timeout(15000)});
    if(!scheduleResponse.ok)throw Error("Fahrplan nicht erreichbar");
    const schedule=await scheduleResponse.json();
    if(!schedule.schiffe)throw Error("Fahrplan ungültig");
    const datum=dateBerlin();
    const results=await Promise.allSettled(SHIPS.map(async ([code,name])=>{
      const r=await fetch(BASE+"/"+code+".html",{headers:{Authorization:auth,"Cache-Control":"no-cache"},signal:AbortSignal.timeout(15000),redirect:"error"});
      if(!r.ok)throw Error("HTTP "+r.status);
      // WDR reports use legacy German encodings; never store the original HTML.
      const bytes=await r.arrayBuffer();
      const charset=/charset=([^; ]+)/i.exec(r.headers.get("content-type")||"")?.[1]||"windows-1252";
      const html=new TextDecoder(charset).decode(bytes);
      return departures(parse(html,name),schedule,name,datum);
    }));
    const errors=results.flatMap((r,i)=>r.status==="rejected"?[SHIPS[i][1]+": Abruf oder Auswertung fehlgeschlagen"]:[]);
    if(errors.length)throw Error(errors.join("; "));
    if(dateBerlin()!==datum)throw Error("Datumswechsel während des Abrufs");
    const abfahrten=results.flatMap(r=>r.value).sort((a,b)=>a.abfahrt.localeCompare(b.abfahrt)||a.schiff.localeCompare(b.schiff));
    const result={updatedAt:new Date().toISOString(),datum,fahrplanStand:schedule.generated_at,abfahrten};
    await env.LADELISTE.put("latest",JSON.stringify(result));
    await env.LADELISTE.put("health",JSON.stringify({attemptedAt,ok:true}));
    return result;
  }catch(error){
    // Never include source HTML, credentials, or arbitrary exception text in logs/API.
    await env.LADELISTE.put("health",JSON.stringify({attemptedAt,ok:false,message:"Abruf mindestens einer Quelle fehlgeschlagen"}));
    throw Error("Ladelisten-Aktualisierung fehlgeschlagen");
  }
}
export default{
  async scheduled(event,env,ctx){ctx.waitUntil(refresh(env).catch(()=>console.error("Ladelisten-Aktualisierung fehlgeschlagen")))},
  async fetch(request,env){
    const u=new URL(request.url);
    if(u.pathname!=="/api/ladeliste")return new Response("Not found",{status:404});
    if(request.method!=="GET")return new Response("Method not allowed",{status:405});
    const headers={"Content-Type":"application/json;charset=utf-8","Cache-Control":"no-store","Access-Control-Allow-Origin":"https://joergroeloffs-coder.github.io","X-Content-Type-Options":"nosniff"};
    try{
      const [saved,health]=await Promise.all([env.LADELISTE.get("latest","json"),env.LADELISTE.get("health","json")]);
      if(!saved)return Response.json({status:"nicht_bereit",health},{status:503,headers});
      const age=Date.now()-Date.parse(saved.updatedAt);
      const stale=!Number.isFinite(age)||age>300000||age<0||saved.datum!==dateBerlin();
      return Response.json({...saved,health,status:stale?"veraltet":health?.ok===false?"abruffehler":"aktuell"},{headers});
    }catch{return Response.json({status:"fehler"},{status:503,headers})}
  }
};
