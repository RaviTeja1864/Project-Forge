import { Link } from "react-router-dom";

export function Brand({ linked = true }: { linked?: boolean }) {
  const content = (
    <>
      <span className="brand-mark" aria-hidden="true">P</span>
      <span>ProjectForge</span>
    </>
  );
  return linked ? (
    <Link className="brand" to="/" aria-label="ProjectForge home">{content}</Link>
  ) : (
    <span className="brand">{content}</span>
  );
}
