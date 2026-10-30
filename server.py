from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import subprocess, uuid, json, shutil, re, zipfile, math, array, sys, os, urllib.request, urllib.error

ROOT=Path(__file__).parent
WORK=ROOT/'work'; WORK.mkdir(exist_ok=True)
app=FastAPI(title='Classified Trial Reel Studio')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
@app.get('/')
def home():return FileResponse(ROOT/'static'/'desktop.html')
def ff(args):
 p=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*args],capture_output=True,text=True)
 if p.returncode:raise HTTPException(400,p.stderr[-1600:])
def probe(path):
 p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],capture_output=True,text=True)
 try:return float(json.loads(p.stdout)['format']['duration'])
 except:return 0
def detect_drop(path):
 # Estimate the strongest musical energy transition, not a guaranteed musical drop.
 cmd=['ffmpeg','-v','error','-i',str(path),'-vn','-ac','1','-ar','8000','-f','s16le','-']
 try:
  raw=subprocess.run(cmd,capture_output=True,timeout=110,check=True).stdout
  pcm=array.array('h');pcm.frombytes(raw)
  if sys.byteorder!='little':pcm.byteswap()
  frame=800; energy=[]
  for pos in range(0,len(pcm)-frame+1,frame):
   chunk=pcm[pos:pos+frame]
   energy.append(math.sqrt(sum(v*v for v in chunk)/frame)/32768)
  if len(energy)<35:return None
  best=(-1,None)
  for i in range(30,len(energy)-10):
   before=energy[max(0,i-20):i-2];after=energy[i:i+10]
   if not before:continue
   prev=sum(before)/len(before);now=sum(after)/len(after)
   rise=(now-prev)/(prev+.025)
   score=rise*min(1,now/.10)+max(0,now-prev)*1.5
   if score>best[0]:best=(score,i/10)
  return round(best[1],2) if best[1] is not None and best[0]>.09 else None
 except (subprocess.SubprocessError,ValueError,OSError):return None

def approved_caption_references():
 path=ROOT/'caption_library.txt'
 if not path.exists():return []
 return [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

class TextVariantsRequest(BaseModel):
 examples:list[str]
 count:int=5
 genre:str=''
 allow_emojis:bool=False

@app.get('/api/generate-texts/status')
def text_generation_status():
 return {'configured':bool(os.getenv('OPENAI_API_KEY','').strip())}

@app.post('/api/generate-texts')
def generate_texts(data:TextVariantsRequest):
 examples=list(dict.fromkeys(s.strip() for s in data.examples if s.strip()))
 if not examples:raise HTTPException(400,'Vul eerst voorbeeldzinnen in')
 if not 1<=data.count<=100:raise HTTPException(400,'Aantal moet tussen 1 en 100 liggen')
 key=os.getenv('OPENAI_API_KEY','').strip()
 if not key:raise HTTPException(503,'AI-tekstgeneratie is nog niet geconfigureerd. Voeg OPENAI_API_KEY toe aan de Render-omgevingsvariabelen.')
 instruction=('You write authentic on-screen text for short raw hardstyle and uptempo fan videos, NOT advertising copy. '
 'Your writing should feel like something an actual 18-25 year old scene fan or creator would put on a reel: '
 'specific, dry, sometimes cheeky, understated, immediate and believable. '
 'Treat the supplied examples as the PRIMARY reference for language, sentence structure, humor, attitude, '
 'capitalization and level of intensity. Match their vibe without copying or closely paraphrasing them. '
 'Never sound like a brand, promoter, inspirational speaker or marketing agency. '
 'Avoid generic hype and filler such as PURE ENERGY, THE CROWD GOES WILD, UNREAL MOMENT, '
 'INSANE VIBES, NEXT LEVEL, THIS IS WHAT WE LIVE FOR, LEGENDARY, UNMATCHED, '
 'GET READY, EXPERIENCE THE, and similar phrases unless explicitly present in user examples. '
 'Do not automatically mention crowds, drops, bass or energy unless the examples actually focus on those things. '
 'Prefer natural short sentences, specific observations, relatable POVs and unexpected but plausible hooks. '
 'Use the approved style references as guidance for tone and structure, not as text to copy. Avoid last kick and final kick phrasing. Vary sentence patterns and angles; do not create a list of interchangeable slogans. '
 'Never describe an event as happening today, tonight, yesterday or right now. Clips are often published later. Use timeless wording, or past-looking wording such as that day or that night when a time reference is genuinely useful. ' 
 'Use the same language as the examples. Write generated captions in normal sentence case: capitalize only the first letter of the sentence and proper nouns, never use ALL CAPS for emphasis. The user can separately enable full caps in text settings. Do not invent facts about a clip you have not seen. '
 'Each caption MUST be exactly ONE short sentence, never two clauses separated into separate sentences, never a second line or follow-up sentence. No line breaks. Usually 3-12 words; longer only if the examples demand it. '
 'When a music genre is provided by the user, treat it as an important creative keyword and naturally weave the exact genre phrase into a meaningful share of the captions (roughly half to three quarters), but not every caption. ' 
 'Keep genre mentions grammatically natural and avoid forcing the same phrase structure repeatedly. ' 
 'If allow_emojis is true, emojis are permitted sparingly when natural and relevant; do not force emojis into every caption. If allow_emojis is false, never use emojis. ' 
 'Return exactly the requested number of distinct, original captions. '
 'No numbering, hashtags, marketing buzzwords or explanations. '
 'Return valid JSON only: {"texts":["..."]}.')
 payload={'model':os.getenv('OPENAI_TEXT_MODEL','gpt-4o-mini'),'temperature':0.85,
  'response_format':{'type':'json_object'},
  'messages':[{'role':'system','content':instruction},
   {'role':'user','content':json.dumps({'examples':examples[:30],'approved_style_references':approved_caption_references(),'count':data.count,'music_genre':data.genre.strip()[:80],'allow_emojis':data.allow_emojis,'instructions':'Return exactly count distinct captions. Do not copy examples.'})}]}
 req=urllib.request.Request('https://api.openai.com/v1/chat/completions',
  data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=75) as response: result=json.load(response)
  raw=json.loads(result['choices'][0]['message']['content'])
  texts=[];seen=set();source={re.sub(r'\\s+',' ',s).strip().casefold() for s in examples}
  for item in raw.get('texts',[]):
   if not isinstance(item,str):continue
   t=re.sub(r'\\s+',' ',item).strip()
   t=t.lower()
   t=t[:1].upper()+t[1:]
   for pattern,replacement in [
    (r'\bright now\b','at that moment'),
    (r'\bthis morning\b','that morning'),
    (r'\bthis afternoon\b','that afternoon'),
    (r'\bthis evening\b','that evening'),
    (r'\btonight\b','that night'),
    (r'\btoday\b','that day'),
    (r'\byesterday\b','that day')
   ]:
    t=re.sub(pattern,replacement,t,flags=re.IGNORECASE)
   if t and t[-1] not in '.!?':t+='.'
   norm=t.casefold()
   if t and norm not in seen and norm not in source:
    texts.append(t);seen.add(norm)
   if len(texts)>=data.count:break
  if not texts:raise HTTPException(502,'Het AI-model leverde geen bruikbare unieke teksten op. Probeer andere voorbeelden.')
  return {'texts':texts,'requested':data.count}
 except urllib.error.HTTPError as err:
  # Do not expose provider response bodies or credentials to clients.
  if err.code==429:
   raise HTTPException(429,'OpenAI weigert de aanvraag (429). Controleer het API-tegoed, de betaalmethode en de gebruikslimieten van je OpenAI Platform-project. ChatGPT Plus bevat geen API-tegoed.')
  if err.code==401:
   raise HTTPException(502,'OpenAI accepteert de API-sleutel niet (401). Controleer de sleutel in Render → Environment.')
  if err.code==403:
   raise HTTPException(502,'Dit OpenAI-project heeft geen toegang tot het gekozen model (403). Controleer de projectrechten.')
  if err.code==400:
   raise HTTPException(502,'OpenAI heeft de AI-aanvraag afgewezen (400). Controleer de modelinstelling OPENAI_TEXT_MODEL.')
  raise HTTPException(502,'OpenAI kon de aanvraag niet verwerken (status '+str(err.code)+').')
 except (urllib.error.URLError,TimeoutError,KeyError,ValueError) as err:
  raise HTTPException(502,'AI-tekstgeneratie is tijdelijk niet beschikbaar.')

@app.post('/api/upload')
async def upload(file:UploadFile=File(...)):
 ext=Path(file.filename or '').suffix.lower()
 if ext not in ('.mp4','.mov'):raise HTTPException(400,'Upload MP4 of MOV')
 ident=uuid.uuid4().hex; dest=WORK/(ident+ext)
 with dest.open('wb') as out:
  while chunk:=await file.read(1024*1024):out.write(chunk)
 return {'id':ident,'filename':file.filename,'duration':probe(dest),'estimated_drop':None,'url':'/api/media/'+ident}
@app.get('/api/media/{ident}')
def media(ident:str):
 if not re.fullmatch('[0-9a-f]{32}',ident):raise HTTPException(404)
 path=next(iter(WORK.glob(ident+'.*')),None)
 if not path:raise HTTPException(404)
 return FileResponse(path,media_type='video/mp4' if path.suffix=='.mp4' else 'video/quicktime')
class TrimRequest(BaseModel):
 id:str
 start:float
 end:float

@app.post('/api/trim')
def trim_video(data:TrimRequest):
 if not re.fullmatch('[0-9a-f]{32}',data.id):raise HTTPException(400,'Ongeldig bestand')
 source=next((p for p in WORK.glob(data.id+'.*') if p.suffix in ('.mp4','.mov')),None)
 if not source:raise HTTPException(404,'Video niet gevonden; upload opnieuw')
 duration=probe(source)
 start=max(0,min(float(data.start),duration))
 end=max(start,min(float(data.end),duration))
 if end-start<0.2:raise HTTPException(400,'Selecteer minimaal 0.2 seconde')
 output_id=uuid.uuid4().hex
 target=WORK/(output_id+'.mp4')
 ff(['-ss',str(start),'-i',str(source),'-t',str(end-start),'-map','0:v:0','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(target)])
 return {'url':'/api/media/'+output_id,'duration':probe(target),'start':start,'end':end}

@app.post('/api/lut')
async def lut(file:UploadFile=File(...)):
 if Path(file.filename or '').suffix.lower() not in ('.cube','.3dl'):raise HTTPException(400,'Alleen .cube of .3dl')
 ident=uuid.uuid4().hex; dest=WORK/(ident+Path(file.filename).suffix.lower())
 with dest.open('wb') as out:shutil.copyfileobj(file.file,out)
 return {'id':ident,'name':file.filename}
class Render(BaseModel):
 id:str
 start:float=0
 length:float=12
 hook:bool=False
 hook_start:float=0
 hook_end:float=2
 layout:str='cover'
 blur:int=35
 blur_background:bool=False
 blur_intensity:int=24
 mirror_half:bool=False
 auto:bool=False
 contrast:float=0
 shadows:float=0
 saturation:float=100
 lut_id:str|None=None
 lut_strength:float=100
 texts:list[str]=[]
 name:str='Trial_Reel'
 resolution:str='1080x1920'
 fps:float=25
 csv:bool=False
 zip:bool=True
 position:str='center'
 textbar:bool=False
 full_caps:bool=False
 italic:bool=False
 outline:bool=True
 shadow:bool=True
 outline_width:float=2
 outline_fade:float=2
 shadow_distance:float=0
 shadow_opacity:float=95
 shadow_angle:float=135
@app.post('/api/render')
def render(data:Render):
 if not re.fullmatch('[0-9a-f]{32}',data.id):raise HTTPException(400,'Ongeldig bestand')
 source=next((p for p in WORK.glob(data.id+'.*') if p.suffix in ('.mp4','.mov')),None)
 if not source:raise HTTPException(404,'Video niet gevonden')
 if not data.texts or len(data.texts)>100:raise HTTPException(400,'Kies 1-100 teksten')
 w,h=map(int,data.resolution.split('x'))
 if (w,h) not in ((1080,1920),(2160,3840)):raise HTTPException(400,'Ongeldige resolutie')
 if data.fps not in (23.976,24,25,29.97,30,50,59.94,60):raise HTTPException(400,'Ongeldige fps')
 dur=probe(source); start=max(0,min(data.start,dur)); length=min(max(.2,data.length),max(.2,dur-start))
 job=uuid.uuid4().hex; outdir=WORK/job;outdir.mkdir()
 # The overlay is built using a drawtext filter with an escaped UTF-8 text file.
 results=[]
 for i,txt in enumerate(data.texts):
  clip=outdir/f'clip_{i}.mp4'
  if data.hook:
   hs=max(0,min(data.hook_start,dur));hd=min(max(.1,data.hook_end-hs),dur-hs)
   ff(['-ss',str(hs),'-i',str(source),'-t',str(hd),'-c:v','libx264','-preset','veryfast','-c:a','aac',str(outdir/'hook.mp4')]) if not (outdir/'hook.mp4').exists() else None
   ff(['-ss',str(start),'-i',str(source),'-t',str(length),'-c:v','libx264','-preset','veryfast','-c:a','aac',str(outdir/'main.mp4')]) if not (outdir/'main.mp4').exists() else None
   # concat via filter handles sources with differing time bases
   concat=outdir/'combined.mp4'
   if not concat.exists():ff(['-i',str(outdir/'hook.mp4'),'-i',str(outdir/'main.mp4'),'-filter_complex','[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]','-map','[v]','-map','[a]','-c:v','libx264','-preset','veryfast','-c:a','aac',str(concat)])
   inp=concat;ss=[]
  else:inp=source;ss=['-ss',str(start),'-t',str(length)]
  if data.layout=='contain':
   vf=f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black'
  else:vf=f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}'
  if data.blur_background and data.layout=='contain':
   # Split source into a blurred full-frame background and a sharp centered foreground.
   radius=max(0,min(int(data.blur_intensity),60))
   bg=f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=luma_radius={min(radius,40)}:luma_power=2:chroma_radius={min(radius,40)}:chroma_power=2'
   fg=f'scale={w}:{h}:force_original_aspect_ratio=decrease'
   vf=f'split=2[bgsrc][fgsrc];[bgsrc]{bg}[bg];[fgsrc]{fg}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2'
  if data.mirror_half and i%2:vf+=',hflip'
  if data.auto:vf+=',eq=contrast=1.12:saturation=1.12:brightness=0.015'
  # Expose approximate, not Premiere-identical, color mapping
  if data.contrast or data.saturation!=100 or data.shadows:
   c=max(.2,min(2,1+data.contrast/200));s=max(0,min(3,data.saturation/100));b=max(-.12,min(.12,data.shadows/1000))
   vf+=f',eq=contrast={c:.3f}:saturation={s:.3f}:brightness={b:.3f}'
  if data.lut_id:
   lut=next((p for p in WORK.glob(data.lut_id+'.*') if p.suffix in ('.cube','.3dl')),None)
   if lut:vf+=f',lut3d=file={lut.as_posix()}'
  txtfile=outdir/f'text_{i}.txt';txtfile.write_text(txt.upper() if data.full_caps else txt,encoding='utf-8')
  y={'top':'h*0.22','center':'(h-text_h)/2','bottom':'h*0.72'}.get(data.position,'(h-text_h)/2')
  font='/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf' if data.italic else '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
  border=max(0,min(4,int(round(float(data.outline_width)*96/72)))) if data.outline else 0
  fade=max(0,min(20,int(round(data.outline_fade)))) if data.shadow else 0
  vf+=f",drawtext=fontfile={font}:textfile={txtfile.as_posix()}:fontcolor=white:fontsize={int(w*.055)}:x=(w-text_w)/2:y={y}:borderw={border}:bordercolor=black@1"
  distance=max(0,min(40,float(data.shadow_distance))) if data.shadow else 0
  angle=math.radians(float(data.shadow_angle)%360)
  shadow_x=int(round(math.cos(angle)*distance))
  shadow_y=int(round(math.sin(angle)*distance))
  if data.shadow and (distance or fade) and data.shadow_opacity>0:
   opacity=max(0,min(100,float(data.shadow_opacity)))/100
   vf+=f":shadowcolor=black@{opacity:.3f}:shadowx={shadow_x}:shadowy={shadow_y}"
  if data.textbar:vf+=':box=1:boxcolor=black@0.7:boxborderw=20'
  name=re.sub(r'[^A-Za-z0-9_-]','_',data.name)[:80] or 'Trial_Reel'
  target=outdir/f'{name}_{i+1}.mp4'
  ff([*ss,'-i',str(inp),'-vf',vf,'-r',str(data.fps),'-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(target)])
  results.append(target)
 if data.csv:
  import csv
  with (outdir/'captions.csv').open('w',newline='',encoding='utf-8-sig') as f:
   writer=csv.writer(f);writer.writerow(['filename','on_screen_text']);writer.writerows((p.name,t) for p,t in zip(results,data.texts))
 archive=WORK/(job+'.zip')
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
  for p in outdir.iterdir():
   if p in results or p.name=='captions.csv':z.write(p,p.name)
 return {'download':'/api/download/'+job,'files':[p.name for p in results]}
@app.get('/api/download/{ident}')
def download(ident:str):
 if not re.fullmatch('[0-9a-f]{32}',ident):raise HTTPException(404)
 path=WORK/(ident+'.zip')
 if not path.exists():raise HTTPException(404)
 return FileResponse(path,filename='Trial_Reels.zip',media_type='application/zip')
