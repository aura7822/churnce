import { Component, type ErrorInfo, type ReactNode } from "react";

/** A render error on one page must never blank the whole app. Resets when the route changes. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("page crashed", error, info.componentStack); }
  componentDidUpdate(prev: { resetKey: string }) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page"><div className="card" role="alert">
        <h3>This page hit an error</h3>
        <p className="card-sub" style={{ margin: "8px 0 14px" }}>{this.state.error.message}</p>
        <button className="btn btn-clay" onClick={() => this.setState({ error: null })}>Try again</button>
      </div></div>
    );
  }
}
