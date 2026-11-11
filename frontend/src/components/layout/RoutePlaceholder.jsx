export default function RoutePlaceholder({ title, description, stage }) {
  return (
    <section className="route-placeholder" aria-labelledby="route-placeholder-title">
      <div className="route-placeholder-icon" aria-hidden="true">{stage === "notFound" ? "?" : "◈"}</div>
      <p className="eyebrow">WORKSPACE PAGE</p>
      <h1 id="route-placeholder-title">{title}</h1>
      <p>{description}</p>
      <div className="route-placeholder-note">
        <strong>Page foundation is ready.</strong>
        <span>This page will receive its existing workflow components in the next migration update. Your current dataset and API workflows have not been changed.</span>
      </div>
    </section>
  );
}
