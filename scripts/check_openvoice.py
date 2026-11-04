"""Real local OpenVoice smoke check. Does not send Telegram messages."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.openvoice_service import convert_segment,close_worker
from app.services.media import probe_audio_duration

async def check(args):
    started=time.monotonic()
    try:
        output=await convert_segment(args.source_wav,args.reference_video,args.start_ms,args.end_ms,args.output)
        first=time.monotonic()-started
        cached=await convert_segment(args.source_wav,args.reference_video,args.start_ms,args.end_ms,args.output)
        print(json.dumps({'engine':'openvoice_v2','output':str(output),'source_seconds':probe_audio_duration(args.source_wav),
            'output_seconds':probe_audio_duration(output),'first_seconds':round(first,2),'cache_hit':cached==output}))
    finally:
        await close_worker()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-wav',required=True)
    parser.add_argument('--reference-video',required=True)
    parser.add_argument('--start-ms',type=int,default=0)
    parser.add_argument('--end-ms',type=int,default=5000)
    parser.add_argument('--output',required=True)
    asyncio.run(check(parser.parse_args()))
