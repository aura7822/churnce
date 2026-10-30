import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Login } from "./App";
import { Boot } from "./components/Boot";
import { AuthProvider } from "./hooks/useAuth";

describe("login and boot screens", () => {
  it("renders a password visibility toggle", () => {
    const html = renderToStaticMarkup(
      <AuthProvider>
        <Login onStart={() => {}} onFail={() => {}} />
      </AuthProvider>,
    );

    expect(html).toContain('aria-label="Toggle password visibility"');
    expect(html).toContain('type="password"');
  });

  it("does not wrap the boot screen in a card container", () => {
    const html = renderToStaticMarkup(<Boot onDone={() => {}} />);

    expect(html).not.toContain("boot-card");
  });
});
