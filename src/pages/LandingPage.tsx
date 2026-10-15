import { Link } from "react-router-dom";
import { Brand } from "../components/Brand";

const steps = [
  { number: "01", title: "Start with a real problem", text: "Choose a challenge that matters to people, communities, or the world around you." },
  { number: "02", title: "Build on evidence", text: "Make room for credible sources and keep the reasoning behind decisions in view." },
  { number: "03", title: "Design with intent", text: "Give requirements and engineering decisions a thoughtful starting point." },
];

export function LandingPage() {
  return (
    <div className="landing">
      <header className="landing-header">
        <Brand />
        <nav aria-label="Account navigation" className="landing-nav">
          <Link className="text-link" to="/login">Sign in</Link>
          <Link className="button button-small button-primary" to="/register">Get started <span aria-hidden="true">↗</span></Link>
        </nav>
      </header>
      <main>
        <section className="hero">
          <div className="hero-copy">
            <span className="eyebrow"><span className="eyebrow-dot" /> A better foundation for your next build</span>
            <h1 aria-label="Make something that matters">Make something<br /><em>that matters.</em></h1>
            <p className="hero-lede">
              Turn real-world problems into thoughtful engineering projects — grounded in evidence, shaped by clear decisions.
            </p>
            <div className="hero-actions">
              <Link className="button button-primary" to="/register">Create your workspace <span aria-hidden="true">↗</span></Link>
              <Link className="button button-quiet" to="/login">I already have an account</Link>
            </div>
            <div className="hero-note"><span className="note-line" /> A clearer path from curiosity to code.</div>
          </div>
          <div className="hero-art" aria-label="A preview of a project workspace">
            <div className="orbit orbit-one" /><div className="orbit orbit-two" />
            <div className="project-card">
              <div className="project-card-top"><span className="mini-mark">P</span><span>WORKSPACE PREVIEW</span><span className="live-dot" /></div>
              <div className="project-card-title">Urban heat<br />resilience</div>
              <p>How might cities help residents stay safe during extreme heat?</p>
              <div className="project-meta"><span>01 / PROBLEM BRIEF</span><span>IN PROGRESS</span></div>
              <div className="project-progress"><i /></div>
              <div className="project-foot"><span>Evidence-led planning</span><span>01 — 03</span></div>
            </div>
            <div className="art-caption">YOUR NEXT IDEA, WITH ROOM TO GROW</div>
          </div>
        </section>
        <section className="capabilities">
          <div className="section-intro"><span className="eyebrow">A more considered process</span><h2>Good engineering begins<br />before the build.</h2></div>
          <div className="steps-grid">
            {steps.map((step) => (
              <article className="step-card" key={step.number}>
                <span className="step-number">{step.number}</span><h3>{step.title}</h3><p>{step.text}</p>
              </article>
            ))}
          </div>
          <p className="roadmap-note">          Private project workspaces are live. Research, evidence, requirements, and architecture tools are on the roadmap.</p>
        </section>
      </main>
      <footer className="landing-footer"><Brand linked={false} /><span>Made for curious minds and careful builders.</span><span>© ProjectForge</span></footer>
    </div>
  );
}
