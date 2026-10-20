"""CPU-only RWT surface inpaint; existing skeleton and outside weights stay fixed."""
import json, sys
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def normalized(name):
    return ''.join(c for c in name.lower().replace('mixamorig', '') if c.isalnum())


# GPT: Derive an axilla band from actual humerus lengths and torso axes, never fixed character coordinates.
def auto_mask(data, size=1.0):
    names=list(data['names']); keys=[normalized(n) for n in names]
    def bone(*aliases):
        found=[i for i,n in enumerate(keys) if n in aliases]
        if len(found)!=1: raise ValueError('Expected one bone: '+str(aliases))
        return found[0]
    left=bone('leftupperarm','leftarm','upperarml');right=bone('rightupperarm','rightarm','upperarmr')
    spine=bone('spine');tops=[i for i,n in enumerate(keys) if n in {'upperchest','chest','spine1','spine2'}]
    if not tops: raise ValueError('Missing chest bones for automatic mask; use a Blender vertex group')
    heads=data['joints'];tails=data['tails'];up=tails[tops[-1]]-heads[spine];up/=np.linalg.norm(up)
    center=(heads[left]+heads[right])/2;axis=heads[left]-heads[right];axis-=up*np.dot(axis,up);axis/=np.linalg.norm(axis)
    points=data['vertices']-center;side=points@axis;height=points@up;mask=np.zeros(len(points),dtype=bool)
    for i,sign in [(left,1),(right,-1)]:
        length=np.linalg.norm(tails[i]-heads[i]);h=abs(np.dot(heads[i]-center,axis))
        mask|=(side*sign>max(.1*h,h-(.6*h*size)))&(side*sign<h+.6*length*size)&(height>-.875*length*size)&(height<.5*length*size)
    protected=[i for i,n in enumerate(keys) if n in {'head','neck','leftlowerarm','rightlowerarm','leftforearm','rightforearm','lefthand','righthand'} or any(f in n for f in ['thumb','index','middle','ring','pinky'])]
    mask&=data['skin'][:,protected].sum(axis=1)<.05
    return mask


# GPT: Weld only the calculation graph; map the solved values back onto the untouched mesh and preserve fingers exactly.
def solve(work, strength=1.0, size=1.0, group=False):
    work=Path(work);data=np.load(work/'input.npz',allow_pickle=False)
    if not 0<=strength<=1 or not .5<=size<=1.5: raise ValueError('Invalid strength or region size')
    roi=data['mask'].astype(bool) if group else auto_mask(data,size)
    x,inv=np.unique(data['vertices'],axis=0,return_inverse=True);f=inv[data['faces']]
    f=f[(f[:,0]!=f[:,1])&(f[:,1]!=f[:,2])&(f[:,0]!=f[:,2])]
    old=data['skin'].astype(np.float64);counts=np.bincount(inv);w=np.zeros((len(x),old.shape[1]));np.add.at(w,inv,old);w/=counts[:,None]
    free=np.ones(len(x),dtype=bool);np.logical_and.at(free,inv,roi)
    if not np.any(free): raise ValueError('Empty mask: check bone names, mesh or vertex group')
    e=np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]);g=coo_matrix((np.ones(len(e)),(e[:,0],e[:,1])),shape=(len(x),len(x)))
    _,labels=connected_components(g,directed=False)
    if any(np.all(free[labels==i]) for i in np.unique(labels[free])): raise ValueError('Unanchored mask component: retain known weights around the mask')
    vendor=Path(__file__).parent/'vendor/rwt';sys.path[:0]=[str(vendor/'deps'),str(vendor)]
    from weighttransfer import inpaint
    pred=inpaint(x.astype(np.float64),f.astype(np.int64),w,~free,False)
    if not np.all(np.isfinite(pred)): raise ValueError('RWT returned non-finite values')
    raw_min=float(pred[free].min());pred=np.maximum(pred,0)
    if np.any(pred[free].sum(axis=1)<1e-12): raise ValueError('RWT returned zero-weight vertices')
    pred/=np.maximum(pred.sum(axis=1,keepdims=True),1e-12)
    selected=free[inv];result=old.copy();result[selected]=(1-strength)*old[selected]+strength*pred[inv[selected]]
    fingers=np.array([any(f in normalized(n) for f in ['thumb','index','middle','ring','pinky']) for n in data['names']])
    result[:,fingers]=old[:,fingers];ids=np.where(selected)[0];non=np.where(~fingers)[0];sub=result[np.ix_(ids,non)]
    if strength>0: sub*=(1-old[ids][:,fingers].sum(axis=1))[:,None]/np.maximum(sub.sum(axis=1,keepdims=True),1e-12)
    result[np.ix_(ids,non)]=sub
    assert np.array_equal(result[~selected],old[~selected]) and np.array_equal(result[:,fingers],old[:,fingers])
    info={'method':'RWT surface inpaint','vertices':len(old),'welded_vertices':len(x),'selected_vertices':int(selected.sum()),'strength':strength,'region_scale':size,'raw_weight_min':raw_min,'max_influences':int((result>0).sum(axis=1).max()),'outside_weights_unchanged':True,'finger_weights_unchanged':True,'limitations':['Shoulder volume loss can remain during arm elevation','Weight repair does not fit equipment geometry']}
    if info['max_influences']>8: raise ValueError('More than 8 influences: refuse to truncate protected source weights')
    np.savez_compressed(work/'weights.npz',weights=result.astype(np.float32),roi=selected)
    (work/'solve.json').write_text(json.dumps(info,indent=2),encoding='utf-8');return info


if __name__=='__main__':
    options=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    print(json.dumps(solve(options['work'],options['strength'],options['size'],bool(options['group'])),indent=2))