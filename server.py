from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import subprocess, uuid, json, shutil, re, zipfile, math, array, sys

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
  if data.mirror_half and i%2:vf+=',hflip'
  if data.auto:vf+=',eq=contrast=1.12:saturation=1.12:brightness=0.015'
  # Expose approximate, not Premiere-identical, color mapping
  if data.contrast or data.saturation!=100 or data.shadows:
   c=max(.2,min(2,1+data.contrast/200));s=max(0,min(3,data.saturation/100));b=max(-.12,min(.12,data.shadows/1000))
   vf+=f',eq=contrast={c:.3f}:saturation={s:.3f}:brightness={b:.3f}'
  if data.lut_id:
   lut=next((p for p in WORK.glob(data.lut_id+'.*') if p.suffix in ('.cube','.3dl')),None)
   if lut:vf+=f',lut3d=file={lut.as_posix()}'
  txtfile=outdir/f'text_{i}.txt';txtfile.write_text(txt,encoding='utf-8')
  y={'top':'h*0.22','center':'(h-text_h)/2','bottom':'h*0.72'}.get(data.position,'(h-text_h)/2')
  font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
  vf+=f",drawtext=fontfile={font}:textfile={txtfile.as_posix()}:fontcolor=white:fontsize={int(w*.055)}:x=(w-text_w)/2:y={y}:borderw=2:bordercolor=black@0.8"
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
