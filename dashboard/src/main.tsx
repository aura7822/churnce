import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/pages.css";
import "./styles/final.css";
import { App } from "./App";
import { AuthProvider } from "./hooks/useAuth";
import { ToastProvider } from "./hooks/useToast";
import { ThemeProvider } from "./hooks/useTheme";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <ThemeProvider><AuthProvider>
        <App />
      </AuthProvider></ThemeProvider>
    </ToastProvider>
  </StrictMode>,
);
