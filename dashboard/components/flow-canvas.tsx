'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Minus, Plus, RotateCcw, Scan } from 'lucide-react';
import Image from 'next/image';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import type { Evidence, Run } from '@/lib/contracts';

type FlowNode = { step: number; operation: string; label?: string | null; elapsed?: number; file: Evidence };
const CARD_W = 320;
const DEFAULT_RATIO = 2340 / 1080;
const GAP_X = 112;
const GAP_Y = 104;
const PAD = 44;
const COLUMNS = 4;
const clampScale = (scale: number) => Math.max(0.05, Math.min(1.8, scale));

export function FlowCanvas({ run, files }: { run: Run; files: Evidence[] }) {
    const viewport = useRef<HTMLDivElement>(null);
    const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
    const [view, setView] = useState({ x: 28, y: 28, scale: 0.8 });
    const [ratios, setRatios] = useState<Record<string, number>>({});
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
    const CARD_H = Math.max(DEFAULT_RATIO, ...Object.values(ratios)) * CARD_W + 100;
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
    const resetView = useCallback(() => {
        const bounds = viewport.current?.getBoundingClientRect();
        if (!bounds) return;
        const visibleColumns = Math.min(3, Math.max(1, nodes.length));
        const rowWidth = PAD * 2 + visibleColumns * CARD_W + (visibleColumns - 1) * GAP_X;
        const scale = Math.max(.15, Math.min(.7, (bounds.width - 24) / rowWidth, (bounds.height - 24) / (CARD_H + PAD * 2)));
        setView({ x: 12, y: 12, scale });
    }, [nodes.length, CARD_H]);
    useEffect(() => { resetView(); }, [run.id, resetView]);
    function changeScale(factor: number) { setView(current => ({ ...current, scale: clampScale(current.scale * factor) })); }
    // Native, non-passive listener: React's onWheel is passive, so it cannot stop the page from scrolling as well.
    useEffect(() => {
        const element = viewport.current;
        if (!element) return;
        function onWheel(event: WheelEvent) {
            event.preventDefault();
            // Ctrl/Cmd + wheel, and trackpad pinch (reported with ctrlKey), zoom; any other scroll pans.
            if (event.ctrlKey || event.metaKey) {
                const factor = event.deltaY < 0 ? 1.08 : .92;
                setView(current => ({ ...current, scale: clampScale(current.scale * factor) }));
                return;
            }
            const unit = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? element!.clientHeight : 1;
            // Shift + wheel scrolls sideways on mice without a horizontal wheel.
            const dx = (event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX) * unit;
            const dy = (event.shiftKey && !event.deltaX ? 0 : event.deltaY) * unit;
            setView(current => ({ ...current, x: current.x - dx, y: current.y - dy }));
        }
        element.addEventListener('wheel', onWheel, { passive: false });
        return () => element.removeEventListener('wheel', onWheel);
    }, []);
    function startPan(event: React.PointerEvent<HTMLDivElement>) {
        if ((event.target as HTMLElement).closest('[data-flow-card]')) return;
        drag.current = { x: event.clientX, y: event.clientY, panX: view.x, panY: view.y };
        // The pointer can already be gone (quick touch, or the browser took the gesture); panning still works without capture.
        try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* no active pointer to capture */ }
    }
    function movePan(event: React.PointerEvent<HTMLDivElement>) {
        // Read the drag start now: React may run the state updater after pointerup/pointercancel has cleared it.
        const start = drag.current;
        if (!start) return;
        const x = start.panX + event.clientX - start.x;
        const y = start.panY + event.clientY - start.y;
        setView(current => ({ ...current, x, y }));
    }
    return <div className="flow-editor">
        <div className="flow-toolbar">
            <div><b>Execution flow</b><span>{nodes.length} captured {nodes.length === 1 ? 'image' : 'images'} · {run.trace?.length || 0} steps</span></div>
            <div className="flow-controls">
                <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => changeScale(.85)}><Minus size={15}/></button>
                <span>{Math.round(view.scale * 100)}%</span>
                <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => changeScale(1.18)}><Plus size={15}/></button>
                <button type="button" aria-label="Fit flow" title="Fit flow" onClick={fit}><Scan size={15}/></button>
                <button type="button" aria-label="Reset canvas" title="Reset canvas" onClick={resetView}><RotateCcw size={14}/></button>
            </div>
        </div>
        <div ref={viewport} className="flow-viewport" onPointerDown={startPan} onPointerMove={movePan} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
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
                    <div className="flow-step-label">STEP {String(node.step + 1).padStart(2, '0')}</div><div className="flow-card-image"><Image unoptimized width={320} height={Math.round(CARD_W * (ratios[node.file.id] || DEFAULT_RATIO))} onLoad={event => { const img = event.currentTarget; const ratio = img.naturalHeight / img.naturalWidth; if (ratio > 0) setRatios(old => old[node.file.id] === ratio ? old : { ...old, [node.file.id]: ratio }); }} src={`/api/evidence/${node.file.id}`} alt={`Screenshot for step ${node.step}`}/></div>
                    <div className="flow-card-meta"><b>{node.operation.replaceAll('_', ' ')}</b><small>{node.label || node.file.name}</small><small>{node.elapsed == null ? node.file.name : `${(node.elapsed / 1000).toFixed(1)}s · ${node.file.name}`}</small></div>
                </button>; })}
            </div> : <div className="flow-empty"><b>No captured images in this run</b><span>Import or attach screenshots to see the execution flow here.</span></div>}
        </div>
        <Dialog open={!!selected} onOpenChange={open => { if (!open) setSelected(null); }}><DialogContent className="flow-image-dialog">{selected && <><DialogTitle>Step {selected.step + 1} · {selected.operation.replaceAll('_', ' ')}</DialogTitle><DialogDescription>{selected.label || selected.file.name}</DialogDescription><img src={`/api/evidence/${selected.file.id}`} alt={`Full screenshot for step ${selected.step + 1}`}/><a href={`/api/evidence/${selected.file.id}`} target="_blank" rel="noreferrer">Open original image</a></>}</DialogContent></Dialog>
    </div>;
}
