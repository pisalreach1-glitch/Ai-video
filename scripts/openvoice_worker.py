"""Local JSON-lines OpenVoice V2 worker; model stays loaded between utterances."""
import contextlib
import hashlib
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'engines'/'openvoice_vendor'))

def main():
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from openvoice.api import ToneColorConverter
        directory=Path(sys.argv[1]).resolve()
        torch.manual_seed(0)
        converter=ToneColorConverter(str(directory/'config.json'),device='cuda:0' if torch.cuda.is_available() else 'cpu',enable_watermark=False)
        converter.load_ckpt(str(directory/'checkpoint.pth'))
        if converter.version!='v2':
            raise RuntimeError('Expected OpenVoice V2 weights')
    print(json.dumps({'ready':True,'engine':'openvoice_v2'}),flush=True)
    embeddings={}
    def embedding(path):
        key=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if key not in embeddings:
            if len(embeddings)>=128:embeddings.pop(next(iter(embeddings)))
            embeddings[key]=converter.extract_se(str(path))
        return embeddings[key]
    for line in sys.stdin:
        try:
            request=json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                converter.convert(request['source'],embedding(request['source']),embedding(request['reference']),output_path=request['output'])
            print(json.dumps({'ok':True,'engine':'openvoice_v2'}),flush=True)
        except Exception as exc:
            print(json.dumps({'ok':False,'error':str(exc)}),flush=True)

if __name__=='__main__':main()
