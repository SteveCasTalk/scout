"use client";

import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import Link from 'next/link';
import { ArrowLeft, ArrowRight, ArrowUpRight, Check, ChevronDown, ChevronRight, Copy, Menu, Rocket, Search, Terminal, X } from 'lucide-react';
import { documentation, documentationSearchText, type DocBlock, type DocSection } from '@/lib/documentation';
import { brand } from '@/lib/brand';

function CodeExample({ block }: { block: Extract<DocBlock, { kind: 'code' }> }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  async function copy() {
    try {
      await navigator.clipboard.writeText(block.code);
      setCopied(true);
      setError('');
    } catch {
      setError('Copy unavailable. Select the example text to copy it.');
    }
  }
  return <div className="docs-code">
    <div className="docs-code-heading"><span>{block.title}</span><button type="button" onClick={() => void copy()} aria-label={`Copy ${block.title}`}>{copied ? <Check size={14}/> : <Copy size={14}/>} {copied ? 'Copied' : 'Copy'}</button></div>
    <pre aria-label={`${block.language} example`}><code>{block.code}</code></pre>
    {error && <p role="status">{error}</p>}
  </div>;
}

function Block({ block }: { block: DocBlock }) {
  switch (block.kind) {
    case 'text': return <p>{block.text}</p>;
    case 'callout': return <aside className="docs-callout"><strong>{block.title}</strong><p>{block.text}</p></aside>;
    case 'code': return <CodeExample block={block}/>;
    case 'list': {
      const List = block.ordered ? 'ol' : 'ul';
      return <div className="docs-list">{block.title && <h2>{block.title}</h2>}<List>{block.items.map(item => <li key={item}>{item}</li>)}</List></div>;
    }
    case 'table': return <div className="docs-table" role="region" aria-label={`${block.columns.join(' and ')} reference`} tabIndex={0}><table><thead><tr>{block.columns.map(column => <th scope="col" key={column}>{column}</th>)}</tr></thead><tbody>{block.rows.map(row => <tr key={row[0]}>{row.map((cell, index) => index === 0 ? <th scope="row" key={index}>{cell}</th> : <td key={index}>{cell}</td>)}</tr>)}</tbody></table></div>;
  }
}

function blockTitle(block: DocBlock): string | null {
  return block.kind === 'list' ? block.title || null : block.kind === 'code' || block.kind === 'callout' ? block.title : null;
}

type Navigate = (event: MouseEvent<HTMLAnchorElement>, id: string) => void;
const referenceCategories = new Set(['Integrations', 'Reference']);

function TopicLink({ section, navigate }: { section: DocSection; navigate: Navigate }) {
  return <a href={`#${section.id}`} className="docs-topic-link" onClick={event => navigate(event, section.id)}><strong>{section.title}</strong><p>{section.summary}</p></a>;
}

export function Documentation() {
  const [query, setQuery] = useState('');
  const [topicId, setTopicId] = useState('home');
  const [anchor, setAnchor] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [navMode, setNavMode] = useState<'guide' | 'reference'>('guide');
  const [tocActive, setTocActive] = useState('docs-content');
  const [scrollRequest, setScrollRequest] = useState(0);

  useEffect(() => {
    function readLocation() {
      const hash = window.location.hash.slice(1);
      const id = hash.split('--')[0];
      const target = documentation.find(section => section.id === id);
      setTopicId(target ? id : 'home');
      setNavMode(target && referenceCategories.has(target.category) ? 'reference' : 'guide');
      setQuery('');
      setAnchor(hash.includes('--') ? hash : '');
      setScrollRequest(value => value + 1);
    }
    readLocation();
    window.addEventListener('popstate', readLocation);
    window.addEventListener('hashchange', readLocation);
    return () => {
      window.removeEventListener('popstate', readLocation);
      window.removeEventListener('hashchange', readLocation);
    };
  }, []);

  useEffect(() => {
    if (anchor) document.getElementById(anchor)?.scrollIntoView();
    else window.scrollTo({ top: 0 });
  }, [topicId, anchor, scrollRequest]);

  function navigate(event: MouseEvent<HTMLAnchorElement>, id: string) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    const target = id.split('--')[0];
    setTopicId(target);
    const targetSection = documentation.find(item => item.id === target);
    setNavMode(targetSection && referenceCategories.has(targetSection.category) ? 'reference' : 'guide');
    setAnchor(id.includes('--') ? id : '');
    setQuery('');
    setMenuOpen(false);
    setScrollRequest(value => value + 1);
    window.history.pushState(null, '', id === 'home' ? window.location.pathname : `#${id}`);
  }

  const sections = useMemo(() => {
    const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return documentation.filter(section => terms.every(term => documentationSearchText(section).includes(term)));
  }, [query]);
  const section = documentation.find(item => item.id === topicId);
  const categories = [...new Set(documentation.map(item => item.category))];
  const visibleCategories = categories.filter(category => query.trim() || (navMode === 'reference' ? referenceCategories.has(category) : !referenceCategories.has(category)));
  const sectionIndex = section ? documentation.indexOf(section) : -1;
  const toc = section ? [{ id: 'docs-content', title: section.title }, ...section.blocks.flatMap((block, index) => {
    const title = blockTitle(block);
    return title ? [{ id: `${section.id}--${index}`, title }] : [];
  })] : [];
  const tocKey = toc.map(item => item.id).join('|');
  useEffect(() => {
    if (query.trim() || !section) return;
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]) setTocActive(visible[0].target.id);
    }, { rootMargin: '-90px 0px -60% 0px' });
    tocKey.split('|').forEach(id => {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    });
    return () => observer.disconnect();
  }, [tocKey, section, query]);

  const searching = !!query.trim();
  return <div className="scout-docs">
    <a className="docs-skip" href="#docs-content">Skip to documentation</a>
    <header className="docs-header">
      <button type="button" className="docs-menu-toggle" aria-label={menuOpen ? 'Close documentation menu' : 'Open documentation menu'} aria-expanded={menuOpen} aria-controls="docs-sidebar" onClick={() => setMenuOpen(value => !value)}>{menuOpen ? <X size={21}/> : <Menu size={21}/>}</button>
      <Link href="/" className="docs-brand"><span className="docs-logo" aria-hidden="true"><img src="/favicon.svg" width="28" height="28" alt=""/></span>{brand.name}</Link>
      <nav className="docs-header-nav" aria-label="Documentation shortcuts"><a href="#home" className="active" onClick={event => navigate(event, 'home')}>Docs</a><a href="#mcp" onClick={event => navigate(event, 'mcp')}>MCP</a><a href="#sandbox" onClick={event => navigate(event, 'sandbox')}>Sandbox</a></nav>
      <Link href="/" className="docs-back">Workspace <ArrowUpRight size={15}/></Link>
    </header>
    <div className="docs-layout">
      <aside id="docs-sidebar" className={`docs-sidebar ${menuOpen ? 'is-open' : ''}`}>
        <div className="docs-nav-tabs" role="group" aria-label="Documentation category"><button type="button" aria-pressed={navMode === 'guide'} onClick={() => setNavMode('guide')}>Guide</button><button type="button" aria-pressed={navMode === 'reference'} onClick={() => setNavMode('reference')}>Reference</button></div>
        <label className="docs-search"><Search size={16}/><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search docs" aria-label="Search documentation"/>{query && <button type="button" onClick={() => setQuery('')} aria-label="Clear documentation search"><X size={14}/></button>}</label>
        <nav aria-label="Documentation topics"><a className={`docs-home-link ${topicId === 'home' && !searching ? 'active' : ''}`} href="#home" onClick={event => navigate(event, 'home')}>Home</a>{visibleCategories.map(category => <details className="docs-nav-group" key={category} open><summary><ChevronRight size={13}/>{category}</summary>{sections.filter(item => item.category === category).map(item => <a className={topicId === item.id && !searching ? 'active' : undefined} aria-current={topicId === item.id && !searching ? 'page' : undefined} href={`#${item.id}`} key={item.id} onClick={event => navigate(event, item.id)}>{item.title}</a>)}</details>)}</nav>
        <p className="docs-sidebar-note">Android & iOS testing<br/>Current implementation guide</p>
      </aside>
      <div className={`docs-reading-layout ${!section || searching ? 'docs-home-layout' : ''}`}>
        <main id="docs-content" className="docs-main">
          {searching ? <><h1>Search results</h1><p className="docs-lead" role="status">{sections.length} topics matching “{query}”</p><div className="docs-search-results">{sections.map(item => <TopicLink section={item} navigate={navigate} key={item.id}/>)}</div>{!sections.length && <div className="docs-empty"><p>Try checkpoints, iOS, sync, sandbox, or a tool name.</p><button type="button" onClick={() => setQuery('')}>Clear search</button></div>}</> : !section ? <>
            <h1>{brand.name} docs</h1><p className="docs-lead">{brand.tagline}</p>
            <div className="docs-start-cards"><a href="#quick-start" onClick={event => navigate(event, 'quick-start')}><Rocket size={55} strokeWidth={1.3}/><h2>Get started with {brand.name}</h2><p>Prepare your device, define your first case, and review its saved result.</p></a><a href="#mcp" onClick={event => navigate(event, 'mcp')}><Terminal size={55} strokeWidth={1.3}/><h2>Connect your LLM</h2><p>Use MCP to discover cases, run regressions, and inspect the evidence.</p></a></div>
            <h2>First steps</h2><div className="docs-topic-grid">{documentation.filter(item => ['overview', 'setup'].includes(item.id)).map(item => <TopicLink section={item} navigate={navigate} key={item.id}/>)}</div>
            <h2>Run and review</h2><div className="docs-topic-grid">{documentation.filter(item => ['verification', 'dashboard', 'platforms', 'review'].includes(item.id)).map(item => <TopicLink section={item} navigate={navigate} key={item.id}/>)}</div>
            <h2>Featured topics</h2><div className="docs-topic-grid">{documentation.filter(item => ['concepts', 'architecture', 'sandbox', 'matrices', 'boundaries', 'troubleshooting'].includes(item.id)).map(item => <TopicLink section={item} navigate={navigate} key={item.id}/>)}</div>
          </> : <>
            <div className="docs-breadcrumb"><a href="#home" onClick={event => navigate(event, 'home')}>{brand.name} docs</a><ChevronRight size={13}/><span>{section.category}</span></div>
            <h1>{section.title}</h1><p className="docs-article-meta">Product guide <span>·</span> Android & iOS</p><p className="docs-summary">{section.summary}</p>
            <details className="docs-mobile-toc"><summary>On this page <ChevronDown size={15}/></summary>{toc.slice(1).map(item => <a href={`#${item.id}`} onClick={event => navigate(event, item.id)} key={item.id}>{item.title}</a>)}</details>
            <article className="docs-article" aria-label={section.title}>{section.blocks.map((block, index) => <div className="docs-block" id={`${section.id}--${index}`} key={index}><Block block={block}/></div>)}</article>
            <nav className="docs-page-navigation" aria-label="Previous and next topics">{sectionIndex > 0 ? <a href={`#${documentation[sectionIndex - 1].id}`} onClick={event => navigate(event, documentation[sectionIndex - 1].id)}><ArrowLeft size={17}/><div><small>Previous</small>{documentation[sectionIndex - 1].title}</div></a> : <span/>}{sectionIndex < documentation.length - 1 && <a href={`#${documentation[sectionIndex + 1].id}`} onClick={event => navigate(event, documentation[sectionIndex + 1].id)}><div><small>Next</small>{documentation[sectionIndex + 1].title}</div><ArrowRight size={17}/></a>}</nav>
          </>}
          <footer className="docs-footer"><span>{brand.name} documentation</span><Link href="/">Open workspace <ArrowUpRight size={14}/></Link></footer>
        </main>
        {section && !searching && <aside className="docs-toc" aria-label="On this page"><nav>{toc.map(item => <a className={tocActive === item.id ? 'active' : undefined} href={`#${item.id === 'docs-content' ? section.id : item.id}`} onClick={event => navigate(event, item.id === 'docs-content' ? section.id : item.id)} key={item.id}>{item.title}</a>)}</nav></aside>}
      </div>
    </div>
  </div>;
}
