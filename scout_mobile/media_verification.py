"""Optional bounded file metadata verifier. No playback/mute claims from metadata."""
from __future__ import annotations
import json
import hashlib
import shutil
import subprocess


def _digest(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):digest.update(chunk)
    return digest.hexdigest()

def verify_metadata(output, assertions):
    results=[]
    for rule in assertions:
        result={'id':rule['id'],'required':rule['required'],'verdict':'not_observable','verifier':'ffprobe-metadata-v1','evidence':rule['artifact']}
        path=output/rule['artifact']
        if path.is_symlink() or not path.is_file() or path.resolve().parent!=output.resolve() or path.stat().st_size>250_000_000:
            result['reason']='Media artifact missing, outside the evidence directory, or exceeds 250 MB.'
        elif not shutil.which('ffprobe'):
            result['reason']='Optional ffprobe verifier is unavailable.'
        else:
            try:
                p=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height:format=duration','-of','json',str(path)],capture_output=True,timeout=15)
                if p.returncode or len(p.stdout)>64000:raise ValueError()
                data=json.loads(p.stdout);duration=round(float(data['format']['duration'])*1000)
                videos=[s for s in data.get('streams',[]) if s.get('codec_type')=='video']
                matches=rule['duration_min_ms']<=duration<=rule['duration_max_ms']
                if rule['width'] is not None or rule['height'] is not None:
                    if len(videos)!=1:raise ValueError()
                    matches=matches and (rule['width'] is None or videos[0].get('width')==rule['width']) and (rule['height'] is None or videos[0].get('height')==rule['height'])
                result.update(verdict='satisfied' if matches else 'violated',reason='Inspected actual file duration and dimensions only.',observed={'duration_ms':duration,'video_dimensions':[{k:s.get(k) for k in ('width','height')} for s in videos]})
                result['source_sha256']=_digest(path)
                if rule['kind']=='frame_change':
                    if not shutil.which('ffmpeg') or rule['frame_end_ms']>=duration:
                        raise ValueError()
                    frames=[]
                    for stamp in (rule['frame_start_ms'],rule['frame_end_ms']):
                        capture=subprocess.run(['ffmpeg','-v','error','-ss',str(stamp/1000),'-i',str(path),'-frames:v','1','-vf','scale=64:64,format=gray','-f','rawvideo','pipe:1'],capture_output=True,timeout=15)
                        if capture.returncode or len(capture.stdout)!=4096:raise ValueError()
                        frames.append(capture.stdout)
                    change=sum(abs(a-b) for a,b in zip(*frames))/(4096*255)
                    result.update(verdict='satisfied' if matches and change>=rule['minimum_change'] else 'violated',verifier='ffmpeg-frame-change-v1',reason='Measured change between two declared file frames; this does not prove correct playback or audio.',observed={'frame_change':change,'sample_ms':[rule['frame_start_ms'],rule['frame_end_ms']]})
            except (OSError,ValueError,KeyError,TypeError,OverflowError,subprocess.TimeoutExpired):
                result.update(verdict='not_observable',reason='Requested media evidence could not be established.')
                result.pop('observed',None)
        results.append(result)
    return results
