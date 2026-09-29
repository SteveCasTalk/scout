'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Minus, Plus, RotateCcw, Scan } from 'lucide-react';
import Image from 'next/image';
import type { Evidence, Run } from '@/lib/contracts';

type FlowNode = { step: number; operation: string; label?: string | null; elapsed?: number; file: Evidence };
const CARD_W = 258;
const CARD_H = 224;
const GAP_X = 112;
const GAP_Y = 104;
const PAD = 44;
const COLUMNS = 4;

export function FlowCanvas({ run, files }: { run: Run; files: Evidence[] }) {
    const viewport = useRef<HTMLDivElement>(null);
    const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
    const [view, setView] = useState({ x: 28, y: 28, scale: 0.8 });
    const [selected, setSelected] = useState<FlowNode | null>(null);
    const nodes = useMemo(() => {
        const images = new Map(files.filter(file => file.mime.startsWith('image/')).map(file => [file.name, file]));
        const linked: FlowNode[] = [];
        const used = new Set<string>();
        for (const step of [...(run.trace || [])].sort((a, b) => a.step - b.step)) {
            if (!step.screenshot) continue;
            const file = images.get(step.screenshot);
            if (!file) continue;
            linked.push({ step: step.step, operation: step.operation, label: step.label, elapsed: step.elapsed_ms, file });
            used.add(file.id);
        }
        for (const file of files.filter(file => file.mime.startsWith('image/') && !used.has(file.id))) {
            linked.push({ step: linked.length ? linked[linked.length - 1].step + 1 : linked.length, operation: 'ATTACHED IMAGE', label: file.name, file });
        }
        return linked;
    }, [files, run.trace]);
    const rows = Math.ceil(nodes.length / COLUMNS);
    const width = PAD * 2 + COLUMNS * CARD_W + (COLUMNS - 1) * GAP_X;
    const height = PAD * 2 + Math.max(1, rows) * CARD_H + Math.max(0, rows - 1) * GAP_Y;
    const coords = nodes.map((_, index) => {
        const row = Math.floor(index / COLUMNS);
        const col = row % 2 === 0 ? index % COLUMNS : COLUMNS - 1 - (index % COLUMNS);
        return { x: PAD + col * (CARD_W + GAP_X), y: PAD + row * (CARD_H + GAP_Y) };
    });
    const fit = useCallback(() => {
        const bounds = viewport.current?.getBoundingClientRect();
        if (!bounds) return;
        const scale = Math.min(1, (bounds.width - 40) / width, (bounds.height - 40) / height);
        setView({ x: (bounds.width - width * scale) / 2, y: (bounds.height - height * scale) / 2, scale: Math.max(0.05, scale) });
    }, [height, width]);
    useEffect(() => { requestAnimationFrame(fit); }, [run.id, fit]);
    useEffect(() => {
        const element = viewport.current;
        if (!element) return;
        const observer = new ResizeObserver(fit);
        observer.observe(element);
        return () => observer.disconnect();
    }, [fit]);
    function changeScale(factor: number) { setView(current => ({ ...current, scale: Math.max(0.05, Math.min(1.8, current.scale * factor)) })); }
    function startPan(event: React.PointerEvent<HTMLDivElement>) {
        if ((event.target as HTMLElement).closest('[data-flow-card]')) return;
        drag.current = { x: event.clientX, y: event.clientY, panX: view.x, panY: view.y };
        event.currentTarget.setPointerCapture(event.pointerId);
    }
    function movePan(event: React.PointerEvent<HTMLDivElement>) {
        if (!drag.current) return;
        setView(current => ({ ...current, x: drag.current!.panX + event.clientX - drag.current!.x, y: drag.current!.panY + event.clientY - drag.current!.y }));
    }
    return <div className="flow-editor">
        <div className="flow-toolbar">
            <div><b>Execution flow</b><span>{nodes.length} captured {nodes.length === 1 ? 'image' : 'images'} · {run.trace?.length || 0} steps</span></div>
            <div className="flow-controls">
                <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => changeScale(.85)}><Minus size={15}/></button>
                <span>{Math.round(view.scale * 100)}%</span>
                <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => changeScale(1.18)}><Plus size={15}/></button>
                <button type="button" aria-label="Fit flow" title="Fit flow" onClick={fit}><Scan size={15}/></button>
                <button type="button" aria-label="Reset canvas" title="Reset canvas" onClick={() => setView({ x: 28, y: 28, scale: .8 })}><RotateCcw size={14}/></button>
            </div>
        </div>
        <div ref={viewport} className="flow-viewport" onPointerDown={startPan} onPointerMove={movePan} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onWheel={event => { if (event.ctrlKey || event.metaKey) { event.preventDefault(); changeScale(event.deltaY < 0 ? 1.08 : .92); } }}>
            {nodes.length ? <div className="flow-world" style={{ width, height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
                <svg className="flow-connectors" width={width} height={height} aria-hidden="true"><defs><marker id="flow-arrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9 z" fill="#7ca895"/></marker></defs>{coords.slice(0, -1).map((point, index) => {
                    const next = coords[index + 1];
                    const sameRow = point.y === next.y;
                    const x1 = sameRow ? point.x + (next.x > point.x ? CARD_W : 0) : point.x + CARD_W / 2;
                    const y1 = sameRow ? point.y + CARD_H / 2 : point.y + CARD_H;
                    const x2 = sameRow ? next.x + (next.x > point.x ? 0 : CARD_W) : next.x + CARD_W / 2;
                    const y2 = sameRow ? next.y + CARD_H / 2 : next.y;
                    const path = sameRow ? `M${x1} ${y1} C${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}` : `M${x1} ${y1} C${x1} ${y1 + GAP_Y / 2}, ${x2} ${y2 - GAP_Y / 2}, ${x2} ${y2}`;
                    return <path key={index} d={path} fill="none" stroke="#89ae9d" strokeWidth="2.5" markerEnd="url(#flow-arrow)"/>;
                })}</svg>
                {nodes.map((node, index) => { const point = coords[index]; return <button type="button" data-flow-card className={`flow-card ${selected?.file.id === node.file.id ? 'active' : ''}`} key={node.file.id} style={{ left: point.x, top: point.y, width: CARD_W }} onClick={() => setSelected(node)}>
                    <div className="flow-card-image"><Image unoptimized width={258} height={142} src={`/api/evidence/${node.file.id}`} alt={`Screenshot for step ${node.step}`}/><span>STEP {String(node.step + 1).padStart(2, '0')}</span></div>
                    <div className="flow-card-meta"><b>{node.operation.replaceAll('_', ' ')}</b><small>{node.label || node.file.name}</small><small>{node.elapsed == null ? node.file.name : `${(node.elapsed / 1000).toFixed(1)}s · ${node.file.name}`}</small></div>
                </button>; })}
            </div> : <div className="flow-empty"><b>No captured images in this run</b><span>Import or attach screenshots to see the execution flow here.</span></div>}
        </div>
        {selected && <div className="flow-inspector"><div><b>Step {selected.step + 1} · {selected.operation.replaceAll('_', ' ')}</b><span>{selected.label || selected.file.name}{selected.elapsed == null ? '' : ` · ${(selected.elapsed / 1000).toFixed(1)}s`}</span></div><button type="button" onClick={() => setSelected(null)}>Close</button><Image unoptimized width={1080} height={1920} src={`/api/evidence/${selected.file.id}`} alt={selected.label || `Step ${selected.step + 1} screenshot`}/></div>}
    </div>;
}
