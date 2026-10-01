'use client';

import type { Evidence } from '@/lib/contracts';
import { Film, Download } from 'lucide-react';

export function RunRecordings({ files }: { files: Evidence[] }) {
    const recordings = files.filter(file => file.mime.startsWith('video/'));
    return <section className="run-recordings" aria-label="Screen recordings">
        <h3><Film size={18}/> Screen recordings <span>{recordings.length}</span></h3>
        {recordings.length ? recordings.map((file, index) => <div className="run-recording" id={`recording-${file.id}`} key={file.id}>
            <div><b>Recording {index + 1}</b><a href={`/api/evidence/${file.id}`} download={file.name}><Download size={14}/> Download</a></div>
            <video controls playsInline preload="metadata" src={`/api/evidence/${file.id}`} aria-label={`Screen recording ${index + 1}`}/>
        </div>) : <p>No recording is attached to this run. Use Sync MCP runs in Test cases to import a saved recording, or Attach evidence to upload one.</p>}
    </section>;
}
