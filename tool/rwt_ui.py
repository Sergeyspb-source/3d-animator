"""Small Gradio panel for optional weight repair on an existing rig."""
import contextlib
from pathlib import Path
import gradio as gr
from rwt_strings import TEXT as S


# GPT: Own all RWT controls and callbacks here so the large generation UI contains wiring only.
def mount(config_loader, accordion=True):
    with (gr.Accordion(S['title'],open=False) if accordion else contextlib.nullcontext()):
        gr.Markdown(S['intro']);gr.Markdown(S['limit'])
        with gr.Row():
            with gr.Column():
                upload=gr.File(label=S['upload'],file_types=['.glb','.blend'],type='filepath')
                path=gr.Textbox(label=S['path'])
                mesh=gr.Textbox(label=S['mesh'])
                region=gr.Radio(choices=[(S['auto'],'auto'),(S['group'],'group')],value='auto',label=S['region'])
                group=gr.Textbox(label=S['group_name'],visible=False)
                strength=gr.Slider(0,1,value=1,step=.05,label=S['strength'])
                size=gr.Slider(.5,1.5,value=1,step=.05,label=S['size'])
                go=gr.Button(S['go'],variant='primary')
            with gr.Column():
                view=gr.Model3D(label=S['view'],height=360)
                log=gr.Textbox(label=S['log'],lines=8,interactive=False)
                files=gr.File(label=S['files'],file_count='multiple',interactive=False)
        region.change(lambda r:gr.update(visible=r=='group'),region,group,show_progress='hidden')
        def execute(uploaded,local,mesh_name,mode,mask_group,power,scale):
            source=uploaded or local
            if not source or not Path(source).is_file():
                yield S['missing'],None,None
                return
            if mode=='group' and not (mask_group or '').strip():
                yield S['group_name'],None,None
                return
            messages=[S['start']];yield '\n'.join(messages),None,None
            try:
                from rwt_pipeline import run
                for step,info in run(source,config_loader(),mesh_name,mask_group if mode=='group' else '',power,scale):
                    if step=='done':
                        out=Path(info['glb']).parent;messages.append(S['done'])
                        yield '\n'.join(messages),str(out/'model.glb'),[str(out/n) for n in ['model.glb','review.blend','report.json']]
                    else:
                        messages.append(S[{'extract':'extract','solve':'apply','apply':'apply'}[step]])
                        yield '\n'.join(messages),None,None
            except Exception as error:
                messages.append(S['error']+'\n'+str(error));yield '\n'.join(messages),None,None
        go.click(execute,[upload,path,mesh,region,group,strength,size],[log,view,files],concurrency_id='rwt_cpu',concurrency_limit=1,api_name='rwt_inpaint')