const BASE="https://faehre2.de/fileadmin/wdr/Schiffe/Ladeliste";
const SHIPS=[["NA","Norderaue"],["NORDFRIES","Nordfriesland"],["UTHLANDE","Uthlande"],["S-H","Schleswig-Holstein"]];
function text(s){return (s||"").replace(/<[^>]+>/g,"").replace(/&nbsp;?/gi," ").replace(/&amp;/gi,"&").trim()}
function number(s){if(!s||!/^\d+(?:[,.]\d+)?$/.test(s))return null;return Number(s.replace(",","."))}
function cells(html){return [...html.matchAll(/<TD\b[^>]*>([\s\S]*?)<\/TD>/gi)].map(m=>text(m[1]))}
function meters(block){const i=block.indexOf("Summe gebuchter Meter:");if(i<0)return null;const v=cells(block.slice(i,i+1200)).filter(x=>/^\d+,\d+$/.test(x));return v.length>1?number(v[1]):null}
function parse(html,ship){
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
async function refresh(env){
  if(!env.WDR_USER||!env.WDR_PASS)throw Error("Zugangsdaten fehlen");
  const auth="Basic "+btoa(env.WDR_USER+":"+env.WDR_PASS);
  const results=await Promise.allSettled(SHIPS.map(async ([code,name])=>{
    const r=await fetch(BASE+"/"+code+".html",{headers:{"Authorization":auth,"Cache-Control":"no-cache"},signal:AbortSignal.timeout(15000)});
    if(!r.ok)throw Error(name+" HTTP "+r.status);
    return parse(await r.text(),name);
  }));
  const errors=results.flatMap((r,i)=>r.status==="rejected"?[SHIPS[i][1]+": "+String(r.reason)]:[]);
  if(errors.length)throw Error(errors.join("; "));
  const abfahrten=results.flatMap(r=>r.value).sort((a,b)=>a.abfahrt.localeCompare(b.abfahrt)||a.schiff.localeCompare(b.schiff));
  if(!abfahrten.length)throw Error("Keine Abfahrten");
  const updatedAt=new Date().toISOString();
  const datum=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Berlin",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  const result={updatedAt,datum,abfahrten};
  await env.LADELISTE.put("latest",JSON.stringify(result));
  return result;
}
export default{
  async scheduled(event,env,ctx){ctx.waitUntil(refresh(env).catch(e=>console.error("Abruf fehlgeschlagen:",e.message)))},
  async fetch(request,env){
    const u=new URL(request.url);
    if(u.pathname!=="/api/ladeliste")return new Response("Not found",{status:404});
    if(request.method!=="GET")return new Response("Method not allowed",{status:405});
    const headers={"Content-Type":"application/json;charset=utf-8","Cache-Control":"no-store","Access-Control-Allow-Origin":"https://joergroeloffs-coder.github.io"};
    try{
      const saved=await env.LADELISTE.get("latest","json");
      if(!saved)return new Response(JSON.stringify({status:"nicht_bereit"}),{status:503,headers});
      const age=Date.now()-Date.parse(saved.updatedAt);
      const today=new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Berlin",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
      return new Response(JSON.stringify({...saved,status:age>300000||saved.datum!==today?"veraltet":"aktuell"}),{headers});
    }catch(e){return new Response(JSON.stringify({status:"fehler"}),{status:503,headers})}
  }
};