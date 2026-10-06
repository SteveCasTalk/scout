"""Shared public evidence inventory. Journals and private snapshots remain private."""
import json
import re

FILES={'result.json','trace.json','jev-output.json','run-verification.json','sandbox.json','execution-evidence.json'}

def declared_media(folder):
    try:
        definition=json.loads((folder/'result.json').read_text()).get('execution',{}).get('definition',{})
        return {r['artifact'] for r in definition.get('media_assertions',[]) if re.fullmatch(r'[A-Za-z0-9_-]+\.(?:mp4|webm|mov|wav|mp3)',r.get('artifact',''))}
    except (OSError,ValueError,TypeError,KeyError):return set()

def allowed(folder,name):
    if name not in FILES and not re.fullmatch(r'\d{3}\.png|screen-recording-\d+\.mp4',name) and name not in declared_media(folder):return False
    path=folder/name
    return not path.is_symlink() and path.is_file() and path.resolve().parent==folder.resolve() and (name not in declared_media(folder) or path.stat().st_size<=25_000_000)

def inventory(folder):
    return sorted((p for p in folder.iterdir() if allowed(folder,p.name)),key=lambda p:p.name)
