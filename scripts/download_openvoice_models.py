import hashlib,json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests

repo='myshell-ai/OpenVoiceV2'
info=requests.get(f'https://huggingface.co/api/models/{repo}',timeout=30).json()
revision=info['sha']
items=requests.get(f'https://huggingface.co/api/models/{repo}/tree/{revision}/converter',timeout=30).json()
root=Path('models/openvoice_v2/converter')
root.mkdir(parents=True,exist_ok=True)
manifest={'repository':repo,'revision':revision,'files':{}}
for name in ('config.json','checkpoint.pth'):
    item=next(x for x in items if x['path']==f'converter/{name}')
    url=f'https://huggingface.co/{repo}/resolve/{revision}/converter/{name}?download=true'
    expected=item.get('lfs',{}).get('oid')
    target=root/name
    if target.exists() and target.stat().st_size==item['size'] and (not expected or hashlib.sha256(target.read_bytes()).hexdigest()==expected):
        payload=target.read_bytes()
    elif item['size']<10000:
        response=requests.get(url,timeout=30);response.raise_for_status();payload=response.content
    else:
        first=requests.get(url,headers={'Range':'bytes=0-0'},timeout=30)
        first.raise_for_status()
        resolved=first.url
        first.close()
        def fetch(index):
            start=item['size']*index//8;end=item['size']*(index+1)//8-1
            part=root/f'{name}.part{index}'
            if part.exists() and part.stat().st_size==end-start+1:return part.read_bytes()
            for attempt in range(4):
                try:
                    r=requests.get(resolved,headers={'Range':f'bytes={start}-{end}'},timeout=(20,90))
                    r.raise_for_status()
                    if r.status_code!=206 or len(r.content)!=end-start+1:raise RuntimeError('Model range invalid')
                    part.write_bytes(r.content)
                    print('Model range complete',index,flush=True)
                    return r.content
                except requests.RequestException:
                    if attempt==3:raise
        with ThreadPoolExecutor(max_workers=8) as pool:payload=b''.join(pool.map(fetch,range(8)))
    digest=hashlib.sha256(payload).hexdigest()
    assert len(payload)==item['size'] and (not expected or digest==expected)
    temp=target.with_suffix('.verified');temp.write_bytes(payload);temp.replace(target)
    manifest['files'][name]={'sha256':digest,'size':len(payload)}
    print('Verified',name,len(payload),flush=True)
(root.parent/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
