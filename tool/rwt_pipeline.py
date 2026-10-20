"""Optional CPU weight-repair pipeline, separate from skeleton generation."""
import hashlib,json,re,subprocess,sys,uuid
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent


# GPT: Allocate unique work/output folders and validate each process; never overwrite or regenerate the source rig.
def run(source,config,mesh='',group='',strength=1.0,size=1.0):
    source=Path(source).resolve()
    if not source.is_file() or source.suffix.lower() not in {'.glb','.blend'}: raise ValueError('Expected existing GLB or Blender source')
    tag=re.sub('[^a-z0-9_]+','_',source.stem.lower()).strip('_') or 'asset'
    tag+='_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    work=Path(config['work_dir']).resolve()/'rwt_inpaint'/tag
    output=Path(config['export_dir']).resolve()/'rwt_inpaint'/tag
    work.mkdir(parents=True,exist_ok=False)
    options={'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'work':str(work),'output':str(output),'mesh':(mesh or '').strip(),'group':(group or '').strip(),'strength':float(strength),'size':float(size)}
    option_file=work/'options.json';option_file.write_text(json.dumps(options,indent=2),encoding='utf-8')
    blender=str(config.get('blender_exe') or 'D:/Blender 5.2/blender.exe')
    stages=[('extract',[blender,'--disable-autoexec','-b','-t','8','--python-exit-code','1','-P',str(ROOT/'blender_rwt.py'),'--','extract',str(option_file)]),('solve',[sys.executable,str(ROOT/'rwt_solve.py'),str(option_file)]),('apply',[blender,'--disable-autoexec','-b','-t','8','--python-exit-code','1','-P',str(ROOT/'blender_rwt.py'),'--','apply',str(option_file)])]
    for label,args in stages:
        log=work/(label+'.log')
        with log.open('w',encoding='utf-8') as handle:
            result=subprocess.run(args,stdout=handle,stderr=subprocess.STDOUT,timeout=900,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode!=0:
            detail=log.read_text(encoding='utf-8',errors='replace')[-4500:]
            raise RuntimeError(f'RWT {label}: exit {result.returncode}\n{detail}\nLog: {log}')
        yield label,{'work':str(work),'output':str(output)}
    if hashlib.sha256(source.read_bytes()).hexdigest()!=options['source_sha256']: raise RuntimeError('Source changed during operation')
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    if source.suffix.lower()=='.glb':
        b=source.read_bytes();import struct
        before=json.loads(b[20:20+struct.unpack_from('<I',b,12)[0]])
        if len(report['exported_animations'])<len(before.get('animations',[])): raise RuntimeError('Animation export lost source clips; inspect the saved Blender copy')
    for name in ['model.glb','review.blend','report.json']:
        if not (output/name).is_file(): raise RuntimeError('Missing RWT output: '+name)
    yield 'done',report