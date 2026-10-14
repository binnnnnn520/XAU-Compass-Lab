export function LoadingPanel({
  title = "Loading market context",
  copy = "The page is fetching the latest REST data from the backend.",
}: {
  title?: string;
  copy?: string;
}) {
  return (
    <section className="state-card" aria-live="polite">
      <div>
        <div className="state-card__icon">...</div>
        <h2 className="state-card__title">{title}</h2>
        <p className="state-card__copy">{copy}</p>
      </div>
    </section>
  );
}

export function EmptyPanel({
  title,
  copy,
}: {
  title: string;
  copy: string;
}) {
  return (
    <section className="state-card">
      <div>
        <div className="state-card__icon">0</div>
        <h2 className="state-card__title">{title}</h2>
        <p className="state-card__copy">{copy}</p>
      </div>
    </section>
  );
}

export function ErrorPanel({
  title = "Could not load this view",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <section className="state-card">
      <div>
        <div className="state-card__icon">!</div>
        <h2 className="state-card__title">{title}</h2>
        <p className="state-card__copy">{message}</p>
        {onRetry ? (
          <div className="button-row" style={{ justifyContent: "center", marginTop: 18 }}>
            <button type="button" className="button" onClick={onRetry}>
              Retry
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}
