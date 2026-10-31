import type { AnalysisMode } from "../types/analysis";

type HomePageProps = { onSelectMode: (mode: AnalysisMode) => void };

export function HomePage({ onSelectMode }: HomePageProps) {
  return (
    <div className="home-page">
      <div className="home-grid-lines" aria-hidden="true" />
      <header className="public-header page-width">
        <a className="brand" href="#top" aria-label="司法证据核查助手首页">
          <span className="brand-mark">证</span>
          <span><strong>司法证据核查助手</strong><small>司法竞争性证据工作台</small></span>
        </a>
        <div className="header-meta"><span className="status-dot" /> LIVE · CV-0005</div>
      </header>
      <main className="home-main page-width" id="top">
        <section className="hero-block" aria-labelledby="home-title">
          <p className="eyebrow">EVIDENCE REVIEW WORKSPACE</p>
          <h1 id="home-title">不只寻找支持答案的材料，<br /><em>也主动寻找可能削弱当前判断的证据。</em></h1>
          <p className="hero-copy">从案件事实或你的已有判断出发，系统动态识别争点，进行多路竞争性检索，并逐条核查来源权威性与适用边界。</p>
          <div className="hero-trust-row" aria-label="分析能力">
            <span><i>01</i> 争点识别</span>
            <span><i>02</i> 支持 / 削弱并行检索</span>
            <span><i>03</i> Authority &amp; Applicability Audit</span>
          </div>
        </section>
        <section className="entry-section" aria-labelledby="entry-title">
          <div className="section-heading">
            <div><p className="eyebrow">START AN ANALYSIS</p><h2 id="entry-title">选择一种工作方式</h2></div>
            <span className="demo-note"><span className="mini-pulse" /> Live runtime 已就绪</span>
          </div>
          <div className="entry-grid">
            <button className="entry-card entry-card-primary" type="button" onClick={() => onSelectMode("case-analysis")}>
              <div className="entry-card-top"><span className="entry-index">A</span><span className="arrow">↗</span></div>
              <div className="entry-icon">⌕</div>
              <h3>分析案件</h3>
              <p>从案件事实出发，识别争点并同时检索支持与削弱不同判断的证据。</p>
              <span className="entry-action">输入案件 <span>→</span></span>
            </button>
            <button className="entry-card entry-card-secondary" type="button" onClick={() => onSelectMode("viewpoint-check")}>
              <div className="entry-card-top"><span className="entry-index">B</span><span className="arrow">↗</span></div>
              <div className="entry-icon viewpoint-icon">◌</div>
              <h3>核查我的观点</h3>
              <p>已经形成初步判断？让系统同时检查支持依据、可能削弱它的证据和适用边界。</p>
              <span className="entry-action">开始核查 <span>→</span></span>
            </button>
          </div>
        </section>
        <section className="principles-row" aria-label="产品原则">
          <div><span className="principle-number">/ 01</span><strong>保持证据竞争</strong><small>不将检索简化为单向支持</small></div>
          <div><span className="principle-number">/ 02</span><strong>展示推理边界</strong><small>权威性、适用性和未决事实分开呈现</small></div>
          <div><span className="principle-number">/ 03</span><strong>保留来源轨迹</strong><small>每条引用都可以回到原文和检索原因</small></div>
        </section>
      </main>
      <footer className="public-footer page-width"><span>司法证据核查助手 · Live runtime / Phase 2</span><span>CV-0005 × local analysis API</span></footer>
    </div>
  );
}
